"""Network tools for investigation mode: read an official page, look up a domain.

Both tools are called with arguments chosen by a model that has just read an
attacker-written message, so every argument is treated as hostile.

Outbound request rules (see docs/INVESTIGATION.md):

* https only, port 443 only, no credentials in the URL;
* the host must be a dotted DNS name with an alphabetic top-level label, never an
  IP literal;
* the host is resolved first and every address it resolves to must be public
  (not loopback, private, link-local, multicast, reserved, unspecified, or an
  IPv6 form that embeds an IPv4 address);
* the request is sent to that vetted address, with the original name used for
  the Host header, TLS server name and certificate check, so a second DNS answer
  cannot redirect it;
* redirects are never followed automatically: at most 3 are followed by hand and
  each target goes through all of the checks again;
* 5 s to connect, 8 s for one request in total, 300 KB of body at most;
* nothing fetched is ever logged, and error messages carry a fixed reason only.

Which sites may be read is decided by SitePolicy, not by the model.
"""

from __future__ import annotations

import asyncio
import importlib.resources
import ipaddress
import json
import re
import socket
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

import httpx

USER_AGENT = "ProofMode/0.1"
CONNECT_TIMEOUT_SECONDS = 5.0
TOTAL_TIMEOUT_SECONDS = 8.0
MAX_BODY_BYTES = 300_000
MAX_REDIRECTS = 3
MAX_URL_CHARS = 2000
MAX_LINES_PER_PAGE = 40
MAX_LINE_CHARS = 300
MAX_LINKS_PER_PAGE = 20
MAX_TOPICS = 12
RDAP_URL = "https://rdap.org/domain/"

# Tool names shared by the loop, the prompt and the mock client.
TOOL_REPORT = "report_message"
TOOL_FETCH = "fetch_official_page"
TOOL_LOOKUP = "lookup_domain"
TOOL_FINISH = "finish"

# Demo mode (PROOFMODE_MOCK=1): the fictional organisation's site and the
# look-alike domain used by the built-in example. Both are served from fixtures.
DEMO_OFFICIAL_DOMAIN = "tidewater.example"
DEMO_OFFICIAL_URL = f"https://{DEMO_OFFICIAL_DOMAIN}/help/billing"
DEMO_LOOKUP_DOMAIN = "tidewater-accounts.co"
DEMO_DOMAIN_AGE_DAYS = 7
# A public address handed out by the demo resolver. It is never contacted: the
# demo transport answers every request from the fixtures.
_DEMO_ADDRESS = "93.184.216.34"

Resolver = Callable[[str], Awaitable[list[str]]]


class ToolError(Exception):
    """A refused or failed tool call. The message is safe to show and to send back
    to the model: it never contains fetched content or an upstream body."""


# --- host names and domains --------------------------------------------------

_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_TLD_RE = re.compile(r"^(?:[a-z]{2,24}|xn--[a-z0-9-]{1,59})$")
# Second-level labels that act as a public suffix under a two-letter country
# code, e.g. "co.uk" or "com.au". There is no bundled public suffix list.
_GENERIC_SECOND_LEVEL = frozenset(
    {"ac", "co", "com", "edu", "go", "gob", "gov", "ltd", "mil", "ne", "net", "nom", "or", "org"}
)
# Candidate host names in free text. Deliberately loose: denying too much is safe.
_DOMAIN_IN_TEXT_RE = re.compile(r"(?<![\w-])[\w-]{1,63}(?:\.[\w-]{1,63})+(?![\w-])")
_OBFUSCATED_DOT_RE = re.compile(r"\s*[\[({]\s*(?:\.|dot)\s*[\])}]\s*", re.IGNORECASE)


def normalise_host(raw: str) -> str:
    """Return a lowercase ASCII DNS name, or raise ToolError.

    Rejects IP literals, names without a dot, names whose last label is not
    alphabetic (which covers every numeric address spelling), and anything that
    is not letters, digits and hyphens.
    """
    host = raw.strip().lower().rstrip(".")
    if not host or len(host) > 253 or not host.isascii():
        raise ToolError("That is not a valid host name.")
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    else:
        raise ToolError("IP addresses cannot be used; give a domain name.")
    labels = host.split(".")
    if len(labels) < 2:
        raise ToolError("The host name must contain a dot.")
    if not all(_LABEL_RE.match(label) for label in labels) or not _TLD_RE.match(labels[-1]):
        raise ToolError("That is not a valid host name.")
    return host


def registrable_domain(host: str) -> str:
    """Best-effort registrable domain of a normalised host name.

    The last two labels, or the last three when the name ends in a generic
    second-level label under a two-letter country code ("example.co.uk").
    """
    labels = host.split(".")
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _GENERIC_SECOND_LEVEL:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def normalise_domain_input(raw: str) -> str:
    """Normalise a domain typed by a person: drop scheme, path, port and "www."."""
    value = raw.strip().lower()
    value = re.sub(r"^[a-z][a-z0-9+.-]*://", "", value)
    value = re.split(r"[/?#]", value, maxsplit=1)[0]
    value = value.rsplit("@", 1)[-1]
    value = re.sub(r":\d+$", "", value)
    host = normalise_host(value)
    return host[4:] if host.startswith("www.") and host.count(".") >= 2 else host


def extract_domains(text: str) -> set[str]:
    """Return every host name that appears in free text, normalised.

    Covers sender addresses, links and bare domains, including "[.]" and "(dot)"
    spellings and non-ASCII names (returned in their punycode form). Tokens that
    only look like a domain, such as "file.txt", are returned too: the result is
    used as a deny-list, where a false positive is harmless.
    """
    cleaned = unicodedata.normalize("NFKC", text)
    cleaned = _OBFUSCATED_DOT_RE.sub(".", cleaned)
    found: set[str] = set()
    for match in _DOMAIN_IN_TEXT_RE.finditer(cleaned):
        candidate = match.group(0).lower().strip("-_.")
        if not candidate.isascii():
            try:
                candidate = candidate.encode("idna").decode("ascii")
            except UnicodeError:
                continue
        try:
            found.add(normalise_host(candidate))
        except ToolError:
            continue
    return found


# --- address vetting ---------------------------------------------------------

_NAT64_NETWORK = ipaddress.ip_network("64:ff9b::/96")
_NAT64_LOCAL_NETWORK = ipaddress.ip_network("64:ff9b:1::/48")


def is_public_address(address: str) -> bool:
    """True only for a globally routable unicast address.

    IPv6 forms that carry an IPv4 address (IPv4-mapped, 6to4, Teredo, NAT64) are
    refused outright, since they can point at an internal IPv4 host.
    """
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and (
        ip.ipv4_mapped is not None
        or ip.sixtofour is not None
        or ip.teredo is not None
        or ip in _NAT64_NETWORK
        or ip in _NAT64_LOCAL_NETWORK
    ):
        return False
    return ip.is_global and not (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def system_resolver(host: str) -> list[str]:
    """Resolve a host name with the system resolver and return its addresses."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


async def vetted_address(host: str, resolver: Resolver) -> str:
    """Resolve host and return one address to connect to.

    Raises ToolError unless the name resolves and every address is public. A name
    with even one internal address is refused, so mixed answers cannot be used to
    reach an internal host.
    """
    try:
        async with asyncio.timeout(CONNECT_TIMEOUT_SECONDS):
            addresses = await resolver(host)
    except (OSError, TimeoutError):
        raise ToolError(f"{host} could not be resolved.") from None
    unique = list(dict.fromkeys(addresses))
    if not unique:
        raise ToolError(f"{host} could not be resolved.")
    if not all(is_public_address(address) for address in unique):
        raise ToolError(f"{host} resolves to a non-public address and was not contacted.")
    ipv4 = [address for address in unique if ":" not in address]
    return (ipv4 or unique)[0]


def parse_https_url(raw: str) -> httpx.URL:
    """Parse a URL and apply the syntactic rules: https, port 443, plain DNS host."""
    text = raw.strip()
    if not text or len(text) > MAX_URL_CHARS or any(ord(char) < 0x21 for char in text):
        raise ToolError("That is not a valid URL.")
    try:
        url = httpx.URL(text)
    except (httpx.InvalidURL, ValueError, TypeError):
        raise ToolError("That is not a valid URL.") from None
    if url.scheme != "https":
        raise ToolError("Only https URLs can be fetched.")
    if url.userinfo:
        raise ToolError("URLs with a user name or password cannot be fetched.")
    if url.port not in (None, 443):
        raise ToolError("Only port 443 can be used.")
    host = normalise_host(url.host)
    return url.copy_with(host=host, port=None, fragment=None)


# --- which sites may be read -------------------------------------------------


@dataclass
class SitePolicy:
    """Decides which hosts fetch_official_page may read.

    * official_domain set (supplied by the user): only that domain and its
      subdomains, and not even those when the domain appears in the message.
    * otherwise the model proposes a site, but never one whose registrable domain
      appears in the message, and only one site per check: the first site read
      successfully becomes chosen_domain and later fetches must stay on it.
    * fetch_disabled_reason set: nothing may be fetched.
    """

    official_domain: str | None = None
    denied_domains: set[str] = field(default_factory=set)
    chosen_domain: str | None = None
    fetch_disabled_reason: str | None = None

    def deny(self, hosts: set[str]) -> None:
        """Add the registrable domains of hosts seen in the message to the deny-list."""
        self.denied_domains.update(registrable_domain(host) for host in hosts)

    def check(self, host: str) -> None:
        """Raise ToolError unless host may be fetched."""
        if self.official_domain is not None:
            official = self.official_domain
            if registrable_domain(host) in self.denied_domains:
                # A domain typed by the user gets no more trust than one proposed
                # by the model: if the message names it, it is under suspicion.
                raise ToolError(
                    f"{registrable_domain(host)} appears in the message under review, "
                    "so it is never fetched, even though it was given as the official "
                    "domain."
                )
            if host != official and not host.endswith("." + official):
                raise ToolError(
                    f"Only {official} and its subdomains may be fetched in this check; "
                    f"{host} was not contacted."
                )
            return
        if self.fetch_disabled_reason:
            raise ToolError(self.fetch_disabled_reason)
        domain = registrable_domain(host)
        if domain in self.denied_domains:
            raise ToolError(
                f"{domain} appears in the message under review, so it is never fetched "
                "and never treated as the official site. Use the organisation's real "
                "domain, or finish without it."
            )
        if self.chosen_domain is not None and domain != self.chosen_domain:
            raise ToolError(
                f"This check already uses {self.chosen_domain} as the official site; "
                f"{host} was not contacted."
            )

    def record_success(self, host: str) -> None:
        """Remember the site the model chose once a page has been read from it."""
        if self.official_domain is None and self.chosen_domain is None:
            self.chosen_domain = registrable_domain(host)


# --- one vetted request ------------------------------------------------------


@dataclass
class Network:
    """The injectable network: an HTTP client and a resolver."""

    http: httpx.AsyncClient
    resolver: Resolver = system_resolver


@dataclass(frozen=True)
class _Reply:
    status: int
    content_type: str
    location: str | None
    body: bytes
    charset: str | None


def _failure(exc: Exception) -> ToolError:
    """Turn a transport failure into a fixed, body-free reason."""
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return ToolError("The request timed out.")
    return ToolError(f"The request failed ({type(exc).__name__}).")


async def _get(net: Network, url: httpx.URL, *, accept: str) -> _Reply:
    """Send one GET to the vetted address for url.host and read a capped body.

    No redirect is followed here. The body is read as a stream and reading stops
    at MAX_BODY_BYTES.
    """
    host = url.host
    address = await vetted_address(host, net.resolver)
    headers = {
        "Host": host,
        "User-Agent": USER_AGENT,
        "Accept": accept,
        "Accept-Encoding": "identity",
    }
    body = bytearray()
    try:
        async with (
            asyncio.timeout(TOTAL_TIMEOUT_SECONDS),
            net.http.stream(
                "GET",
                url.copy_with(host=address),
                headers=headers,
                # TLS server name and certificate check use the real host name
                # even though the connection goes to the vetted address.
                extensions={"sni_hostname": host},
                follow_redirects=False,
                timeout=httpx.Timeout(TOTAL_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS),
            ) as response,
        ):
            encoding = response.headers.get("content-encoding", "identity").strip().lower()
            if encoding not in {"", "identity", "gzip", "deflate"}:
                raise ToolError("The server used a content encoding that is not accepted.")
            location = response.headers.get("location")
            if not response.is_redirect:
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) >= MAX_BODY_BYTES:
                        break
            return _Reply(
                status=response.status_code,
                content_type=response.headers.get("content-type", "")
                .split(";", 1)[0]
                .strip()
                .lower(),
                location=location if response.is_redirect else None,
                body=bytes(body[:MAX_BODY_BYTES]),
                charset=response.charset_encoding,
            )
    except ToolError:
        raise
    except (httpx.HTTPError, httpx.InvalidURL, TimeoutError, OSError, ValueError) as exc:
        raise _failure(exc) from None


# --- fetch_official_page -----------------------------------------------------


@dataclass(frozen=True)
class Page:
    """Text read from one page. Everything in it is untrusted."""

    url: str
    text: str
    links: list[str]


_SKIPPED_TAGS = frozenset(
    {"script", "style", "noscript", "template", "svg", "iframe", "object", "select", "textarea"}
)
_BLOCK_TAGS = frozenset(
    {
        "address", "article", "aside", "blockquote", "br", "button", "dd", "details", "div",
        "dl", "dt", "figcaption", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6",
        "header", "hr", "label", "li", "main", "nav", "ol", "option", "p", "pre", "section",
        "summary", "table", "td", "th", "title", "tr", "ul",
    }
)  # fmt: skip


_WHITESPACE_RE = re.compile(r"\s+")


class _TextExtractor(HTMLParser):
    """Collects visible text and link targets; drops scripts, styles and markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED_TAGS:
            self._skip_depth += 1
            return
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "a" and not self._skip_depth:
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            # Line breaks in the markup are plain whitespace; only block tags
            # start a new line.
            self.parts.append(_WHITESPACE_RE.sub(" ", data))


def html_to_text(html: str) -> tuple[str, list[str]]:
    """Reduce HTML to visible text (one block per line) and its raw link targets."""
    extractor = _TextExtractor()
    try:
        extractor.feed(html)
        extractor.close()
    except (AssertionError, ValueError):
        # A malformed page: keep whatever text was collected before the failure.
        pass
    return "".join(extractor.parts), extractor.links


def _same_site_links(raw_links: list[str], base: httpx.URL, policy: SitePolicy) -> list[str]:
    """Absolute https links on the same registrable domain that the policy allows."""
    site = registrable_domain(base.host)
    kept: list[str] = []
    for raw in raw_links:
        try:
            url = parse_https_url(urljoin(str(base), raw.strip()))
            if registrable_domain(url.host) != site:
                continue
            policy.check(url.host)
        except (ToolError, ValueError):
            continue
        text = str(url)
        if text != str(base) and text not in kept and len(text) <= 300:
            kept.append(text)
    kept.sort(key=lambda link: 0 if _LINK_HINT_RE.search(link) else 1)
    return kept[:MAX_LINKS_PER_PAGE]


_LINK_HINT_RE = re.compile(
    r"faq|help|support|billing|pricing|payment|refund|security|phishing|scam|fraud|terms"
    r"|polic|contact|docs|legal|trust",
    re.IGNORECASE,
)


async def fetch_page(url: str, *, net: Network, policy: SitePolicy) -> Page:
    """Read one text page from a site the policy allows.

    Redirects are followed by hand, at most MAX_REDIRECTS, and only to a URL that
    passes every check again and stays on the starting registrable domain.
    Raises ToolError with a fixed reason on refusal or failure.
    """
    current = parse_https_url(url)
    policy.check(current.host)
    start_domain = registrable_domain(current.host)

    for hop in range(MAX_REDIRECTS + 1):
        reply = await _get(net, current, accept="text/html, text/plain;q=0.9")
        if reply.location is None:
            break
        if hop == MAX_REDIRECTS:
            raise ToolError(f"Too many redirects (more than {MAX_REDIRECTS}).")
        target = parse_https_url(urljoin(str(current), reply.location))
        if registrable_domain(target.host) != start_domain:
            raise ToolError(
                f"The page redirects to another site ({registrable_domain(target.host)}), "
                "which was not followed."
            )
        policy.check(target.host)
        current = target

    if reply.status != 200:
        raise ToolError(f"The site answered with HTTP {reply.status}.")
    if reply.content_type not in {"text/html", "text/plain"}:
        raise ToolError("The page is not HTML or plain text.")

    try:
        decoded = reply.body.decode(reply.charset or "utf-8", errors="replace")
    except LookupError:
        decoded = reply.body.decode("utf-8", errors="replace")
    if reply.content_type == "text/html":
        text, raw_links = html_to_text(decoded)
    else:
        text, raw_links = decoded, []
    policy.record_success(current.host)
    return Page(url=str(current), text=text, links=_same_site_links(raw_links, current, policy))


# --- relevance ---------------------------------------------------------------

# Word stems that matter in a fraud check, matched as substrings.
_CORE_TERMS = (
    "account", "bank", "billing", "card", "charge", "contact", "credit", "crypto", "deadline",
    "domain", "email", "expir", "fee", "fraud", "gift", "impersonat", "invoice", "legitimate",
    "never", "official", "only", "password", "pay", "phishing", "reactivat", "refund", "scam",
    "security", "support", "suspend", "transfer", "verif", "wire",
)  # fmt: skip
_STOPWORDS = frozenset(
    {
        "about", "after", "again", "also", "been", "before", "being", "click", "dear", "from",
        "have", "here", "hours", "into", "just", "keep", "more", "must", "need", "once", "over",
        "please", "should", "than", "that", "their", "them", "then", "there", "these", "they",
        "this", "those", "today", "under", "until", "very", "were", "what", "when", "where",
        "which", "while", "will", "with", "within", "would", "your", "yours",
    }
)  # fmt: skip
_WORD_RE = re.compile(r"[a-z][a-z'-]{3,}")
# A sentence ends at ". ", "! " or "? " before a capital, digit or quote, and also
# at a full stop glued to the next capital, which is how adjacent inline elements
# come out of the tag stripper ("...tokens.Once you...").
_SENTENCE_SPLIT_RE = re.compile(
    r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])|(?<=[a-z0-9)][.!?])(?=[A-Z][a-z])"
)
MAX_KEYWORDS = 40


def keywords_from(text: str) -> list[str]:
    """Distinct lowercase words of four or more letters, without common filler."""
    seen: list[str] = []
    for word in _WORD_RE.findall(text.lower()):
        word = word.strip("'-")
        if len(word) >= 4 and word not in _STOPWORDS and word not in seen:
            seen.append(word)
            if len(seen) == MAX_KEYWORDS:
                break
    return seen


def select_lines(text: str, keywords: list[str]) -> list[str]:
    """Split page text into sentences and keep the relevant ones, in page order.

    A sentence is relevant when it contains a word from the message (or a topic
    the model asked for) or a fraud-check term. Message words count three times
    as much. At most MAX_LINES_PER_PAGE sentences are kept, each cut to
    MAX_LINE_CHARS characters.
    """
    wanted = [keyword.lower() for keyword in keywords if len(keyword) >= 3]
    candidates: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split())
        if not line:
            continue
        for sentence in _SENTENCE_SPLIT_RE.split(line):
            sentence = sentence.strip()[:MAX_LINE_CHARS].strip()
            lowered = sentence.lower()
            if len(sentence) < 12 or len(sentence.split()) < 3 or lowered in seen:
                continue
            seen.add(lowered)
            score = 3 * sum(1 for keyword in wanted if keyword in lowered)
            score += sum(1 for term in _CORE_TERMS if term in lowered)
            if score:
                candidates.append((score, len(candidates), sentence))
    best = sorted(candidates, key=lambda item: (-item[0], item[1]))[:MAX_LINES_PER_PAGE]
    return [sentence for _, _, sentence in sorted(best, key=lambda item: item[1])]


# --- lookup_domain -----------------------------------------------------------


@dataclass(frozen=True)
class DomainRecord:
    """Registration data for one domain, from RDAP."""

    domain: str
    found: bool
    registered_on: date | None = None
    registrar: str | None = None
    age_days: int | None = None

    def sentence(self) -> str:
        """One line of evidence. The domain and date are produced here, in Python."""
        if not self.found:
            return (
                f"No registration record was found for {self.domain}: it is either "
                "unregistered or its registry does not publish registration data."
            )
        if self.registered_on is None:
            line = f"{self.domain} is registered, but its registration date is not published."
        else:
            unit = "day" if self.age_days == 1 else "days"
            line = (
                f"{self.domain} was registered on {self.registered_on.isoformat()} "
                f"({self.age_days} {unit} ago)."
            )
        if self.registrar:
            line += f" Registrar: {self.registrar}."
        return line


def _clean_label(value: object, limit: int = 80) -> str | None:
    """Reduce an upstream string to one short line of printable text."""
    if not isinstance(value, str):
        return None
    cleaned = " ".join("".join(char if char.isprintable() else " " for char in value).split())
    return cleaned[:limit].rstrip(" .") or None


def _registrar_name(data: dict[str, Any]) -> str | None:
    entities = data.get("entities")
    for entity in entities if isinstance(entities, list) else []:
        if not isinstance(entity, dict):
            continue
        roles = entity.get("roles")
        if not isinstance(roles, list) or "registrar" not in roles:
            continue
        vcard = entity.get("vcardArray")
        if isinstance(vcard, list) and len(vcard) == 2 and isinstance(vcard[1], list):
            for item in vcard[1]:
                if isinstance(item, list) and len(item) >= 4 and item[0] == "fn":
                    name = _clean_label(item[3])
                    if name:
                        return name
        return _clean_label(entity.get("handle"))
    return None


def _registration_date(data: dict[str, Any]) -> date | None:
    events = data.get("events")
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict) or event.get("eventAction") != "registration":
            continue
        stamp = event.get("eventDate")
        if not isinstance(stamp, str):
            continue
        try:
            parsed = datetime.fromisoformat(stamp.strip())
        except ValueError:
            continue
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(UTC)
        return parsed.date()
    return None


async def lookup_domain(domain: str, *, net: Network, today: date | None = None) -> DomainRecord:
    """Look up the registrable domain of `domain` in RDAP.

    Returns found=False when RDAP has no record, which is a result and not an
    error. The request starts at rdap.org, which redirects to the registry that
    holds the record; those redirects (at most MAX_REDIRECTS) may leave rdap.org
    but each target passes the same address vetting as any other request.
    """
    name = registrable_domain(normalise_domain_input(domain))
    current = parse_https_url(RDAP_URL + name)
    for hop in range(MAX_REDIRECTS + 1):
        reply = await _get(net, current, accept="application/rdap+json, application/json")
        if reply.location is None:
            break
        if hop == MAX_REDIRECTS:
            raise ToolError("The registration lookup redirected too many times.")
        current = parse_https_url(urljoin(str(current), reply.location))

    if reply.status == 404:
        return DomainRecord(domain=name, found=False)
    if reply.status != 200:
        raise ToolError(f"The registration lookup answered with HTTP {reply.status}.")
    if reply.content_type not in {"application/rdap+json", "application/json"}:
        raise ToolError("The registration lookup returned an unexpected content type.")
    try:
        data = json.loads(reply.body.decode("utf-8", errors="replace"))
    except ValueError:
        raise ToolError("The registration lookup returned data that could not be read.") from None
    if not isinstance(data, dict):
        raise ToolError("The registration lookup returned data that could not be read.")

    registered_on = _registration_date(data)
    current_day = today or datetime.now(UTC).date()
    age = max(0, (current_day - registered_on).days) if registered_on is not None else None
    return DomainRecord(
        domain=name,
        found=True,
        registered_on=registered_on,
        registrar=_registrar_name(data),
        age_days=age,
    )


# --- networks ----------------------------------------------------------------


def live_http_client() -> httpx.AsyncClient:
    """The HTTP client used for real fetches: no proxies from the environment, no
    automatic redirects, no cookies kept beyond the one investigation."""
    return httpx.AsyncClient(
        trust_env=False,
        follow_redirects=False,
        timeout=httpx.Timeout(TOTAL_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS),
        limits=httpx.Limits(max_connections=4, max_keepalive_connections=0),
    )


def _fixture(name: str) -> str:
    return importlib.resources.files("proofmode").joinpath("fixtures", name).read_text(
        encoding="utf-8"
    )


def _demo_handler(request: httpx.Request) -> httpx.Response:
    """Answer demo-mode requests from the bundled fixtures. Nothing leaves the machine."""
    host = request.headers.get("host", "")
    if host == DEMO_OFFICIAL_DOMAIN or host.endswith("." + DEMO_OFFICIAL_DOMAIN):
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=_fixture("demo_official_page.html").encode("utf-8"),
        )
    if host == "rdap.org" and request.url.path == f"/domain/{DEMO_LOOKUP_DOMAIN}":
        registered = datetime.now(UTC) - timedelta(days=DEMO_DOMAIN_AGE_DAYS)
        body = _fixture("demo_rdap.json").replace(
            "{{REGISTERED}}", registered.strftime("%Y-%m-%dT00:00:00Z")
        )
        return httpx.Response(
            200, headers={"content-type": "application/rdap+json"}, content=body.encode("utf-8")
        )
    return httpx.Response(404, headers={"content-type": "text/plain"}, content=b"not found")


async def _demo_resolver(host: str) -> list[str]:
    del host
    return [_DEMO_ADDRESS]


def demo_network() -> Network:
    """A network that serves the built-in example from fixtures, for demo mode."""
    return Network(
        http=httpx.AsyncClient(transport=httpx.MockTransport(_demo_handler)),
        resolver=_demo_resolver,
    )
