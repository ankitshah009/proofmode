"""Investigation tools: host vetting, fetching, text extraction and domain lookup.

No test here touches the network: every request goes through httpx.MockTransport
and every name is resolved by a fake resolver.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from datetime import date
from typing import Any

import httpx
import pytest

from proofmode import tools
from proofmode.tools import (
    MAX_BODY_BYTES,
    MAX_LINE_CHARS,
    MAX_LINES_PER_PAGE,
    Network,
    SitePolicy,
    ToolError,
    demo_network,
    extract_domains,
    fetch_page,
    html_to_text,
    is_public_address,
    keywords_from,
    lookup_domain,
    normalise_domain_input,
    normalise_host,
    parse_https_url,
    registrable_domain,
    select_lines,
    vetted_address,
)

PUBLIC = "93.184.216.34"
OFFICIAL = "tidewater.example"
Handler = Callable[[httpx.Request], httpx.Response]


def html(body: str, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status, headers={"content-type": "text/html; charset=utf-8"}, content=body.encode()
    )


def make_net(
    handler: Handler | Callable[[httpx.Request], Any],
    addresses: dict[str, list[str]] | None = None,
    **client_options: Any,
) -> Network:
    """A Network whose requests go to handler and whose names resolve from a table."""
    table = addresses or {}

    async def resolver(host: str) -> list[str]:
        if host in table:
            return table[host]
        return [PUBLIC]

    return Network(
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler), **client_options),
        resolver=resolver,
    )


def fetch(url: str, net: Network, policy: SitePolicy | None = None) -> tools.Page:
    return asyncio.run(
        fetch_page(url, net=net, policy=policy or SitePolicy(official_domain=OFFICIAL))
    )


# --- host names --------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "[::1]",
        "::1",
        "localhost",
        "intranet",
        "2130706433",
        "127.1",
        "0x7f.0x0.0x0.0x1",
        "example.123",
        "exa mple.com",
        "-bad.example.com",
        "bad_.example.com",
        "tidewater\u0430.example",
        "",
        "a" * 64 + ".com",
    ],
)
def test_normalise_host_rejects_ips_dotless_and_malformed_names(host: str) -> None:
    with pytest.raises(ToolError):
        normalise_host(host)


def test_normalise_host_lowercases_and_strips_trailing_dot() -> None:
    assert normalise_host(" Help.Tidewater.Example. ") == "help.tidewater.example"


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("tidewater.example", "tidewater.example"),
        ("help.eu.tidewater.example", "tidewater.example"),
        ("shop.tidewater.co.uk", "tidewater.co.uk"),
        ("tidewater.com.au", "tidewater.com.au"),
        ("tidewater-accounts.co", "tidewater-accounts.co"),
    ],
)
def test_registrable_domain(host: str, expected: str) -> None:
    assert registrable_domain(host) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.Tidewater.example/help?x=1", "tidewater.example"),
        ("tidewater.example:443", "tidewater.example"),
        ("billing@tidewater.example", "tidewater.example"),
        ("help.tidewater.example", "help.tidewater.example"),
    ],
)
def test_normalise_domain_input(raw: str, expected: str) -> None:
    assert normalise_domain_input(raw) == expected


def test_extract_domains_finds_senders_links_and_obfuscated_names() -> None:
    text = (
        "From: Tidewater Cloud Billing <billing@tidewater-accounts.co>\n"
        "Verify now at https://secure.tidewater-accounts.co/login?next=1 or "
        "tidewater-pay[.]co, or pay (dot) tidewater-refunds.org. Thanks."
    )
    found = extract_domains(text)
    assert {
        "tidewater-accounts.co",
        "secure.tidewater-accounts.co",
        "tidewater-pay.co",
        "pay.tidewater-refunds.org",
    } <= found


def test_extract_domains_returns_non_ascii_names_as_punycode() -> None:
    found = extract_domains("Sign in at tidewat\u0435r.example today")
    assert any(host.startswith("xn--") and host.endswith(".example") for host in found)


def test_extract_domains_ignores_plain_sentences() -> None:
    assert extract_domains("Your credits expire in 24 hours. Pay $49 now.") == set()


# --- address vetting ---------------------------------------------------------


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",  # loopback
        "10.1.2.3",  # private
        "172.16.0.9",  # private
        "192.168.1.1",  # private
        "169.254.169.254",  # link-local, cloud metadata
        "100.64.0.1",  # shared address space
        "224.0.0.1",  # multicast
        "240.0.0.1",  # reserved
        "0.0.0.0",  # unspecified
        "255.255.255.255",  # broadcast
        "192.0.2.10",  # documentation
        "::1",  # loopback
        "::",  # unspecified
        "fe80::1",  # link-local
        "fc00::1",  # unique local
        "fd12:3456::1",  # unique local
        "ff02::1",  # multicast
        "2001:db8::1",  # documentation
        "::ffff:127.0.0.1",  # IPv4-mapped loopback
        "::ffff:93.184.216.34",  # IPv4-mapped, refused in every case
        "64:ff9b::7f00:1",  # NAT64 form of 127.0.0.1
        "2002:7f00:1::",  # 6to4 form of 127.0.0.1
        "fe80::1%eth0",  # scoped link-local
        "not-an-address",
    ],
)
def test_non_public_addresses_are_refused(address: str) -> None:
    assert is_public_address(address) is False


@pytest.mark.parametrize("address", [PUBLIC, "2606:2800:21f:cb07:6820:80da:af6b:8b2c"])
def test_public_addresses_are_accepted(address: str) -> None:
    assert is_public_address(address) is True


def test_vetted_address_refuses_a_name_with_any_internal_address() -> None:
    async def resolver(host: str) -> list[str]:
        return [PUBLIC, "10.0.0.5"]

    with pytest.raises(ToolError, match="non-public"):
        asyncio.run(vetted_address("help.tidewater.example", resolver))


def test_vetted_address_reports_resolution_failure_without_details() -> None:
    async def resolver(host: str) -> list[str]:
        raise OSError("secret resolver detail")

    with pytest.raises(ToolError) as caught:
        asyncio.run(vetted_address("help.tidewater.example", resolver))
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize(
    "url",
    [
        "http://tidewater.example/",
        "ftp://tidewater.example/",
        "file:///etc/passwd",
        "https://tidewater.example:8443/",
        "https://tidewater.example:80/",
        "https://user:pass@tidewater.example/",
        "https://127.0.0.1/",
        "https://[::1]/",
        "https://localhost/",
        "https://2130706433/",
        "https://tidewater.example/a b",
        "//tidewater.example/",
        "",
    ],
)
def test_parse_https_url_refuses_unsafe_urls(url: str) -> None:
    with pytest.raises(ToolError):
        parse_https_url(url)


def test_parse_https_url_accepts_explicit_port_443_and_drops_the_fragment() -> None:
    url = parse_https_url("https://Help.Tidewater.example:443/billing?a=1#top")
    assert str(url) == "https://help.tidewater.example/billing?a=1"


# --- site policy -------------------------------------------------------------


def test_policy_with_user_domain_allows_only_that_domain_and_subdomains() -> None:
    policy = SitePolicy(official_domain=OFFICIAL)
    policy.check("tidewater.example")
    policy.check("help.tidewater.example")
    for host in ("tidewater-accounts.co", "eviltidewater.example", "tidewater.example.evil.co"):
        with pytest.raises(ToolError, match="Only tidewater.example"):
            policy.check(host)


def test_policy_without_user_domain_never_allows_a_domain_from_the_message() -> None:
    policy = SitePolicy()
    policy.deny({"secure.tidewater-accounts.co"})
    with pytest.raises(ToolError, match="appears in the message"):
        policy.check("tidewater-accounts.co")
    with pytest.raises(ToolError, match="appears in the message"):
        policy.check("login.tidewater-accounts.co")
    policy.check("tidewater.example")


def test_policy_locks_onto_the_first_site_the_model_reads() -> None:
    policy = SitePolicy()
    policy.record_success("help.tidewater.example")
    assert policy.chosen_domain == "tidewater.example"
    policy.check("www.tidewater.example")
    with pytest.raises(ToolError, match="already uses tidewater.example"):
        policy.check("other.example")


# --- fetch_page --------------------------------------------------------------


def test_fetch_connects_to_the_vetted_address_and_keeps_the_host_name() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return html("<p>Tidewater Cloud credits do not expire.</p>")

    page = fetch("https://help.tidewater.example/billing", make_net(handler))

    request = seen[0]
    assert request.url.host == PUBLIC  # the address that was vetted, not a new lookup
    assert request.url.scheme == "https"
    assert request.headers["host"] == "help.tidewater.example"
    assert request.extensions["sni_hostname"] == "help.tidewater.example"
    assert request.headers["user-agent"] == "ProofMode/0.1"
    assert page.url == "https://help.tidewater.example/billing"
    assert "credits do not expire" in page.text


def test_fetch_refuses_a_host_that_resolves_to_an_internal_address() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return html("<p>internal</p>")

    net = make_net(handler, {"tidewater.example": ["169.254.169.254"]})
    with pytest.raises(ToolError, match="non-public"):
        fetch("https://tidewater.example/", net)
    assert calls == []


def test_fetch_never_contacts_a_site_the_policy_refuses() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return html("<p>hello</p>")

    with pytest.raises(ToolError, match="Only tidewater.example"):
        fetch("https://tidewater-accounts.co/", make_net(handler))
    assert calls == []


def test_fetch_follows_a_same_site_redirect_by_hand_and_vets_it_again() -> None:
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.headers["host"])
        if request.headers["host"] == "tidewater.example":
            return httpx.Response(301, headers={"location": "https://www.tidewater.example/help"})
        return html("<p>Tidewater Cloud never charges a reactivation fee.</p>")

    # follow_redirects=True on the injected client must not matter.
    page = fetch("https://tidewater.example/help", make_net(handler, follow_redirects=True))
    assert hosts == ["tidewater.example", "www.tidewater.example"]
    assert page.url == "https://www.tidewater.example/help"


def test_fetch_refuses_a_redirect_whose_target_resolves_internally() -> None:
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.headers["host"])
        return httpx.Response(302, headers={"location": "https://admin.tidewater.example/"})

    net = make_net(handler, {"admin.tidewater.example": ["10.0.0.7"]})
    with pytest.raises(ToolError, match="non-public"):
        fetch("https://tidewater.example/", net)
    assert hosts == ["tidewater.example"]


@pytest.mark.parametrize(
    "location",
    [
        "https://tidewater-accounts.co/login",
        "http://tidewater.example/plain",
        "https://127.0.0.1/",
        "https://tidewater.example:8443/",
        "//other.example/path",
    ],
)
def test_fetch_refuses_redirects_off_site_or_to_unsafe_urls(location: str) -> None:
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.headers["host"])
        return httpx.Response(302, headers={"location": location})

    with pytest.raises(ToolError):
        fetch("https://tidewater.example/", make_net(handler), SitePolicy())
    assert hosts == ["tidewater.example"]


def test_fetch_follows_at_most_three_redirects() -> None:
    count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        return httpx.Response(302, headers={"location": f"/step{count}"})

    with pytest.raises(ToolError, match="Too many redirects"):
        fetch("https://tidewater.example/", make_net(handler))
    assert count == 4  # the first request plus three followed redirects


def test_fetch_stops_reading_at_the_body_cap() -> None:
    chunks_sent = 0

    async def body() -> AsyncIterator[bytes]:
        nonlocal chunks_sent
        for _ in range(200):
            chunks_sent += 1
            yield b"<p>Tidewater Cloud credits do not expire.</p>" * 400  # about 18 KB

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=body())

    page = fetch("https://tidewater.example/", make_net(handler))
    assert chunks_sent < 30  # 200 chunks were on offer; reading stopped near 300 KB
    assert len(page.text.encode()) <= MAX_BODY_BYTES


@pytest.mark.parametrize(
    "content_type", ["application/json", "image/png", "application/pdf", "text/javascript", ""]
)
def test_fetch_accepts_only_html_and_plain_text(content_type: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": content_type}, content=b"SECRET-BODY")

    with pytest.raises(ToolError) as caught:
        fetch("https://tidewater.example/", make_net(handler))
    assert "SECRET-BODY" not in str(caught.value)


def test_fetch_reads_plain_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/plain"}, content=b"Credits do not expire."
        )

    assert fetch("https://tidewater.example/a.txt", make_net(handler)).text == (
        "Credits do not expire."
    )


def test_fetch_refuses_an_unrequested_content_encoding() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(
            200, headers={"content-type": "text/html", "content-encoding": "br"}, content=b"x"
        )

    with pytest.raises(ToolError, match="content encoding"):
        fetch("https://tidewater.example/", make_net(handler))


def test_fetch_errors_carry_the_status_but_never_the_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return html("<p>SECRET-UPSTREAM-BODY</p>", status=503)

    with pytest.raises(ToolError) as caught:
        fetch("https://tidewater.example/", make_net(handler))
    assert "503" in str(caught.value)
    assert "SECRET" not in str(caught.value)


def test_fetch_gives_up_after_the_total_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools, "TOTAL_TIMEOUT_SECONDS", 0.05)

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return html("<p>late</p>")

    with pytest.raises(ToolError, match="timed out"):
        fetch("https://tidewater.example/", make_net(handler))


def test_fetch_reports_transport_failures_by_type_only() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("SECRET connection detail")

    with pytest.raises(ToolError) as caught:
        fetch("https://tidewater.example/", make_net(handler))
    assert "ConnectError" in str(caught.value)
    assert "SECRET" not in str(caught.value)


def test_fetched_content_is_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return html("<p>PRIVATE-PAGE-SENTENCE about billing.</p>")

    with caplog.at_level(logging.DEBUG):
        page = fetch("https://tidewater.example/", make_net(handler))
    assert "PRIVATE-PAGE-SENTENCE" in page.text
    assert "PRIVATE-PAGE-SENTENCE" not in caplog.text


def test_fetch_lists_only_same_site_links_the_policy_allows() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return html(
            '<a href="/help/billing">Billing</a> <a href="https://tidewater-accounts.co/x">x</a>'
            '<a href="http://tidewater.example/plain">p</a> <a href="javascript:alert(1)">j</a>'
            '<a href="https://docs.tidewater.example/about">About</a>'
        )

    page = fetch("https://tidewater.example/", make_net(handler))
    assert page.links == [
        "https://tidewater.example/help/billing",
        "https://docs.tidewater.example/about",
    ]


# --- text extraction and relevance -------------------------------------------


def test_html_to_text_drops_scripts_styles_and_tags() -> None:
    text, links = html_to_text(
        "<html><head><title>Billing help</title><style>p{color:red}</style>"
        "<script>var hidden = 'SCRIPT-TEXT';</script></head><body>"
        "<h1>Billing</h1><p>Credits do <b>not</b>\n expire.</p>"
        "<noscript>NOSCRIPT-TEXT</noscript><svg><text>SVG-TEXT</text></svg>"
        '<a href="/help">Help &amp; support</a></body></html>'
    )
    lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    assert lines == ["Billing help", "Billing", "Credits do not expire.", "Help & support"]
    assert links == ["/help"]
    for hidden in ("SCRIPT-TEXT", "NOSCRIPT-TEXT", "SVG-TEXT", "color:red", "<"):
        assert hidden not in text


def test_html_to_text_survives_malformed_markup() -> None:
    text, _ = html_to_text("<p>Credits do not expire.<div><script>never closed")
    assert "Credits do not expire." in text


def test_select_lines_keeps_relevant_sentences_in_page_order() -> None:
    text = (
        "We run regions on three continents.\n"
        "Tidewater Cloud credits do not expire. Gift cards are never accepted.\n"
        "Our mascot is a heron.\n"
        "Support is available 24 hours a day.Refunds take five days."
    )
    assert select_lines(text, keywords_from("Your credits expire. Pay by gift card.")) == [
        "Tidewater Cloud credits do not expire.",
        "Gift cards are never accepted.",
        "Support is available 24 hours a day.",
        "Refunds take five days.",
    ]


def test_select_lines_caps_count_and_length() -> None:
    text = "\n".join(f"Billing rule {index}: " + "fee " * 200 for index in range(100))
    lines = select_lines(text, [])
    assert len(lines) == MAX_LINES_PER_PAGE
    assert all(len(line) <= MAX_LINE_CHARS for line in lines)


def test_select_lines_prefers_sentences_that_share_words_with_the_message() -> None:
    filler = "\n".join(f"Our support team number {index} is friendly." for index in range(60))
    text = filler + "\nA reactivation charge is never applied to any plan."
    lines = select_lines(text, ["reactivation"])
    assert "A reactivation charge is never applied to any plan." in lines


# --- lookup_domain -----------------------------------------------------------

RDAP_RECORD = {
    "objectClassName": "domain",
    "ldhName": "tidewater-accounts.co",
    "events": [
        {"eventAction": "last changed", "eventDate": "2026-11-05T10:00:00Z"},
        {"eventAction": "registration", "eventDate": "2026-11-02T08:30:00Z"},
    ],
    "entities": [
        {"roles": ["abuse"], "handle": "ignored"},
        {
            "roles": ["registrar"],
            "handle": "9999",
            "vcardArray": ["vcard", [["version", {}, "text", "4.0"], ["fn", {}, "text", "Example\nRegistrar"]]],
        },
    ],
}  # fmt: skip


def rdap(payload: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, headers={"content-type": "application/rdap+json"}, json=payload)


def lookup(domain: str, net: Network) -> tools.DomainRecord:
    return asyncio.run(lookup_domain(domain, net=net, today=date(2026, 11, 9)))


def test_lookup_reports_registration_date_age_and_registrar() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return rdap(RDAP_RECORD)

    record = lookup("https://Secure.Tidewater-Accounts.co/login", make_net(handler))

    assert seen[0].headers["host"] == "rdap.org"
    assert seen[0].url.host == PUBLIC
    assert seen[0].url.path == "/domain/tidewater-accounts.co"
    assert record.found and record.registered_on == date(2026, 11, 2)
    assert record.age_days == 7 and record.registrar == "Example Registrar"
    assert record.sentence() == (
        "tidewater-accounts.co was registered on 2026-11-02 (7 days ago). "
        "Registrar: Example Registrar."
    )


def test_lookup_treats_not_found_as_a_result() -> None:
    record = lookup("tidewater-accounts.co", make_net(lambda request: rdap({}, status=404)))
    assert record.found is False
    assert record.sentence().startswith("No registration record was found for tidewater-accounts.co")


def test_lookup_follows_the_bootstrap_redirect_to_a_vetted_registry() -> None:
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.headers["host"])
        if request.headers["host"] == "rdap.org":
            return httpx.Response(
                302, headers={"location": "https://rdap.registry.example/domain/tidewater-accounts.co"}
            )
        return rdap(RDAP_RECORD)

    assert lookup("tidewater-accounts.co", make_net(handler)).age_days == 7
    assert hosts == ["rdap.org", "rdap.registry.example"]


@pytest.mark.parametrize(
    "location", ["https://rdap.internal.example/domain/x", "http://rdap.registry.example/x", "https://10.0.0.1/x"]
)  # fmt: skip
def test_lookup_refuses_a_redirect_to_an_internal_or_unsafe_target(location: str) -> None:
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.headers["host"])
        return httpx.Response(302, headers={"location": location})

    net = make_net(handler, {"rdap.internal.example": ["192.168.0.10"]})
    with pytest.raises(ToolError):
        lookup("tidewater-accounts.co", net)
    assert hosts == ["rdap.org"]


@pytest.mark.parametrize("domain", ["127.0.0.1", "localhost", "", "../../etc/passwd", "a b.co"])
def test_lookup_refuses_values_that_are_not_domains(domain: str) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return rdap(RDAP_RECORD)

    with pytest.raises(ToolError):
        lookup(domain, make_net(handler))
    assert calls == []


def test_lookup_errors_never_carry_the_upstream_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "application/json"}, content=b"SECRET not json"
        )

    with pytest.raises(ToolError) as caught:
        lookup("tidewater-accounts.co", make_net(handler))
    assert "SECRET" not in str(caught.value)


def test_lookup_without_a_registration_date_says_so() -> None:
    record = lookup("tidewater-accounts.co", make_net(lambda request: rdap({"events": []})))
    assert record.sentence() == (
        "tidewater-accounts.co is registered, but its registration date is not published."
    )


# --- demo network ------------------------------------------------------------


def test_demo_network_serves_the_official_page_and_the_lookup_from_fixtures() -> None:
    async def run() -> tuple[tools.Page, tools.DomainRecord, tools.DomainRecord]:
        net = demo_network()
        try:
            page = await fetch_page(tools.DEMO_OFFICIAL_URL, net=net, policy=SitePolicy())
            record = await lookup_domain(tools.DEMO_LOOKUP_DOMAIN, net=net)
            missing = await lookup_domain("another-domain.example", net=net)
        finally:
            await net.http.aclose()
        return page, record, missing

    page, record, missing = asyncio.run(run())
    assert "Tidewater Cloud never charges a reactivation fee." in page.text
    assert "must never reach the model" not in page.text
    assert record.age_days == tools.DEMO_DOMAIN_AGE_DAYS
    assert missing.found is False
