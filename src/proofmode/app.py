"""FastAPI web layer: one page, one review endpoint, and two small probes.

POST /api/review runs one of three checks, chosen by the form fields:

* a screenshot, no `investigate`: review.run_review (one model call);
* pasted text only, no `investigate`: investigate.run_review_text (one model call);
* `investigate=1`: investigate.investigate, in which the model gathers evidence
  with guarded network tools. It has its own, stricter rate limit and an overall
  deadline, and can be switched off with PROOFMODE_INVESTIGATE=0.

Data handling: an uploaded screenshot, the pasted message and the pasted facts
live in memory for the duration of one request. This module never writes them to
disk and never logs them. The multipart parser below is configured so that it
cannot spill an upload to a temporary file, and the only log line this module
emits records an exception type and code locations, never request content.
"""

import asyncio
import base64
import hashlib
import logging
import math
import os
import re
import time
import traceback
from collections import OrderedDict, deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from python_multipart.multipart import parse_options_header
from starlette.datastructures import FormData, UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from proofmode.investigate import (
    MODEL_CALL_TIMEOUT_SECONDS,
    TIME_BUDGET_SECONDS,
    investigate,
    run_review_text,
)
from proofmode.models import Review, Source
from proofmode.openrouter import ReviewError, client_from_env
from proofmode.review import model_from_env, parse_sources, run_review
from proofmode.tools import (
    Network,
    ToolError,
    extract_domains,
    normalise_domain_input,
    registrable_domain,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_PATH = STATIC_DIR / "index.html"
SAMPLE_PATH = STATIC_DIR / "sample.png"

MAX_IMAGE_BYTES = 8 * 1024 * 1024
# Whole request body: the image plus the facts field and multipart framing.
MAX_BODY_BYTES = 9 * 1024 * 1024
MAX_FACTS_CHARS = 20_000
MAX_TEXT_CHARS = 10_000
# Longest official_domain field read at all; a valid name is at most 253 characters,
# and the allowance covers a pasted URL with a scheme and a path.
MAX_DOMAIN_FIELD_CHARS = 2_000
ALLOWED_MIME_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})

REVIEW_PATH = "/api/review"
RATE_LIMIT_ENV_VAR = "PROOFMODE_RATE_LIMIT"
TRUST_PROXY_ENV_VAR = "PROOFMODE_TRUST_PROXY"
DEFAULT_RATE_LIMIT = 10
INVESTIGATE_ENV_VAR = "PROOFMODE_INVESTIGATE"
INVESTIGATE_RATE_LIMIT_ENV_VAR = "PROOFMODE_INVESTIGATE_RATE_LIMIT"
DEFAULT_INVESTIGATE_RATE_LIMIT = 3
# Server-side deadline for one investigation: the engine's evidence budget plus
# one model call for the final answer. The engine checks its own budget only
# between steps, so a slow provider or site could otherwise hold a request open
# for much longer. Past the deadline the run is cancelled and answered with 504.
INVESTIGATE_DEADLINE_SECONDS = TIME_BUDGET_SECONDS + MODEL_CALL_TIMEOUT_SECONDS
RATE_WINDOW_SECONDS = 60.0
MAX_TRACKED_CLIENTS = 10_000

GENERIC_ERROR = "Something went wrong on the server. Try again."

logger = logging.getLogger("proofmode")

_INLINE_SCRIPT = re.compile(
    r"<script(?![^>]*\bsrc\s*=)[^>]*>([\s\S]*?)</script>", re.IGNORECASE
)


def _content_security_policy(html: bytes) -> str:
    """Build the CSP, allowing each inline script in the page by its SHA-256 hash.

    The page keeps its JavaScript inline (one self-contained file), so `script-src 'self'`
    alone would block it. Hashing the exact bytes that are served keeps the policy strict.
    """
    text = html.decode("utf-8")
    hashes = [
        "'sha256-"
        + base64.b64encode(
            hashlib.sha256(match.group(1).encode("utf-8")).digest()
        ).decode("ascii")
        + "'"
        for match in _INLINE_SCRIPT.finditer(text)
    ]
    script_src = " ".join(["'self'", *hashes])
    return (
        "default-src 'self'; "
        "img-src 'self' data: blob:; "
        "style-src 'self' 'unsafe-inline'; "
        f"script-src {script_src}; "
        "object-src 'none'; "
        "base-uri 'none'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )


def _normalise_mime(value: str | None) -> str:
    return (value or "").split(";", 1)[0].strip().lower()


def sniff_image_type(data: bytes) -> str | None:
    """Return the MIME type implied by the leading bytes, or None if unrecognised.

    The declared Content-Type of an upload is chosen by the sender, so it is only
    accepted when the file's own signature agrees with it.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


class SlidingWindowLimiter:
    """In-memory sliding-window limiter: at most `limit` hits per key per window.

    Memory is bounded twice over: each key stores at most `limit` timestamps, and
    the table holds at most `max_keys` keys. When the table is full, expired keys
    are purged first; if none have expired, the least recently seen key is evicted.
    State is per process and is lost on restart.
    """

    def __init__(
        self,
        limit: int,
        window: float = RATE_WINDOW_SECONDS,
        max_keys: int = MAX_TRACKED_CLIENTS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = limit
        self.window = window
        self.max_keys = max_keys
        self._clock = clock
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._hits)

    def check(self, key: str) -> int:
        """Record a hit for `key`. Return 0 if allowed, else seconds until a retry."""
        if self.limit <= 0:
            return 0
        now = self._clock()
        cutoff = now - self.window
        hits = self._hits.get(key)
        if hits is None:
            if len(self._hits) >= self.max_keys:
                self._make_room(cutoff)
            hits = deque()
            self._hits[key] = hits
        else:
            self._hits.move_to_end(key)
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= self.limit:
            return max(1, math.ceil(hits[0] + self.window - now))
        hits.append(now)
        return 0

    def _make_room(self, cutoff: float) -> None:
        expired = [key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff]
        for key in expired:
            del self._hits[key]
        while len(self._hits) >= self.max_keys:
            self._hits.popitem(last=False)


def rate_limit_from_env(
    name: str = RATE_LIMIT_ENV_VAR, default: int = DEFAULT_RATE_LIMIT
) -> int:
    """Return a per-client, per-minute limit from the environment; 0 disables it.

    By default this reads PROOFMODE_RATE_LIMIT (all checks). The investigation
    limit is read the same way from PROOFMODE_INVESTIGATE_RATE_LIMIT.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = -1
    if value < 0:
        raise ValueError(f"{name} must be a whole number, 0 or greater.")
    return value


def investigation_enabled_from_env() -> bool:
    """Investigation mode is on unless PROOFMODE_INVESTIGATE=0."""
    return os.environ.get(INVESTIGATE_ENV_VAR, "").strip() != "0"


def _text_field(form: FormData, name: str, label: str) -> str:
    """Return a form field as a string ("" when absent); a file part is a 400."""
    value = form.get(name)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"Send {label} as text.")
    return value


def _official_domain(raw: str) -> str | None:
    """Reduce the official_domain field to a bare domain name, or None when empty.

    Scheme, path and port are dropped. What remains must be a dotted DNS name of
    letters, digits and hyphens, at most 253 characters, and not an IP address.
    """
    if not raw.strip():
        return None
    if len(raw) > MAX_DOMAIN_FIELD_CHARS:
        raise HTTPException(status_code=400, detail="The official domain is too long.")
    try:
        return normalise_domain_input(raw)
    except ToolError:
        raise HTTPException(
            status_code=400,
            detail=(
                "The official domain is not a valid domain name. "
                "Give a bare domain such as example.org."
            ),
        ) from None


def _refuse_domain_from_message(domain: str, message_text: str) -> None:
    """Raise a 400 when the official domain the user gave is named in the message.

    The same rule the engine applies to a site proposed by the model: a domain in
    a suspicious message is what is being checked, so it is never the official
    site. A screenshot's domains are known only after the model reads it; that
    case is refused inside the engine (SitePolicy.check).
    """
    named = {registrable_domain(host) for host in extract_domains(message_text)}
    if registrable_domain(domain) in named:
        raise HTTPException(
            status_code=400,
            detail=(
                f"The official domain you gave ({domain}) appears in the message "
                "itself. A domain named in a suspicious message is never used as the "
                "official site. Give the organisation's real domain from a source "
                "you already trust, or leave the field empty."
            ),
        )


def _client_key(request: Request, trust_proxy: bool) -> str:
    """Identify the caller for rate limiting.

    The socket peer address is used by default. X-Forwarded-For is set by whoever
    sends the request, so it is read only when PROOFMODE_TRUST_PROXY=1 says a
    reverse proxy sits in front. Then the last entry is used: that is the address
    the nearest proxy observed, while earlier entries are supplied by the sender.
    """
    if trust_proxy:
        entries = [
            part.strip()
            for part in request.headers.get("x-forwarded-for", "").split(",")
            if part.strip()
        ]
        if entries:
            return entries[-1]
    return request.client.host if request.client else "unknown"


def _frame_summary(exc: BaseException) -> str:
    """List where an exception travelled as `file:line in function`, one per line.

    Source lines and the exception message are omitted on purpose.
    """
    return "\n".join(
        f"  {frame.filename}:{frame.lineno} in {frame.name}"
        for frame in traceback.extract_tb(exc.__traceback__)
    )


class _BodyTooLarge(Exception):
    pass


class _InMemoryMultiPartParser(MultiPartParser):
    # The stock parser moves any file part over 1 MB to a temporary file on disk.
    # A threshold above the whole-body cap means an upload can never reach it.
    spool_max_size = MAX_BODY_BYTES + 1


async def _capped_stream(request: Request, limit: int) -> AsyncIterator[bytes]:
    """Yield the request body, stopping once it exceeds `limit` bytes.

    This also covers chunked requests, which carry no Content-Length to check.
    """
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > limit:
            raise _BodyTooLarge
        yield chunk


async def _read_form(request: Request) -> FormData:
    """Parse the multipart body entirely in memory, within the body size cap."""
    content_type, _ = parse_options_header(request.headers.get("content-type"))
    if content_type != b"multipart/form-data":
        raise HTTPException(
            status_code=400, detail="Send the image and facts as multipart/form-data."
        )
    try:
        parser = _InMemoryMultiPartParser(
            request.headers,
            _capped_stream(request, MAX_BODY_BYTES),
            max_files=1,
            max_fields=8,
            # Field size is governed by the body cap; the facts length is checked
            # in characters afterwards so an overlong field gets a clear 413.
            max_part_size=MAX_BODY_BYTES,
        )
        return await parser.parse()
    except _BodyTooLarge:
        raise HTTPException(status_code=413, detail="The upload is too large.") from None
    except MultiPartException:
        raise HTTPException(
            status_code=400, detail="The upload could not be read as a form."
        ) from None


def create_app(
    client_factory: Callable[[], object] | None = None,
    *,
    clock: Callable[[], float] = time.monotonic,
    network_factory: Callable[[], Network] | None = None,
    investigate_deadline: float = INVESTIGATE_DEADLINE_SECONDS,
) -> FastAPI:
    """Build the ASGI app.

    Tests inject `client_factory` to avoid the network and API keys, `clock` to
    move the rate limiters' time forward, `network_factory` to give each
    investigation a fake internet, and `investigate_deadline` to make a slow
    investigation time out quickly.
    """
    factory = client_factory or client_from_env
    # A missing API key must not stop the page or /api/health from starting; the
    # review route reports the stored configuration error instead.
    client: Any = None
    client_error: ReviewError | None = None
    try:
        client = factory()
    except ReviewError as exc:
        client_error = exc
    html = INDEX_PATH.read_bytes()
    csp = _content_security_policy(html)
    limiter = SlidingWindowLimiter(rate_limit_from_env(), clock=clock)
    investigate_limiter = SlidingWindowLimiter(
        rate_limit_from_env(INVESTIGATE_RATE_LIMIT_ENV_VAR, DEFAULT_INVESTIGATE_RATE_LIMIT),
        clock=clock,
    )
    investigation_enabled = investigation_enabled_from_env()
    # httpx logs every request URL at INFO. In an investigation the URL is chosen
    # by the model after reading the message, so it is request content: keep it
    # out of the log whatever logging configuration the host applies.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    trust_proxy = os.environ.get(TRUST_PROXY_ENV_VAR) == "1"

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            close = getattr(client, "aclose", None)
            if close is not None:
                await close()

    app = FastAPI(
        title="ProofMode",
        lifespan=lifespan,
        docs_url=None,  # Swagger UI loads assets from a CDN, which the CSP forbids.
        redoc_url=None,
        openapi_url=None,
    )

    def _reject_early(request: Request) -> Response | None:
        """Checks that run before any of the request body is read."""
        if request.method == "POST" and request.url.path == REVIEW_PATH:
            retry_after = limiter.check(_client_key(request, trust_proxy))
            if retry_after:
                return JSONResponse(
                    {"detail": "Too many requests. Wait a moment and try again."},
                    status_code=429,
                    headers={"Retry-After": str(retry_after)},
                )
        declared = request.headers.get("content-length")
        if declared is not None:
            if not declared.isdecimal():
                return JSONResponse(
                    {"detail": "Invalid Content-Length header."}, status_code=400
                )
            if int(declared) > MAX_BODY_BYTES:
                return JSONResponse(
                    {"detail": "The upload is too large."}, status_code=413
                )
        return None

    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = _reject_early(request)
        if response is None:
            try:
                response = await call_next(request)
            except Exception as exc:  # noqa: BLE001 - last-resort handler, see below
                # Anything unanticipated becomes a generic 500. The log records the
                # exception type and the code locations only: the message is left
                # out because it can quote request content (facts, filenames).
                logger.error(
                    "Unhandled %s on %s %s\n%s",
                    type(exc).__name__,
                    request.method,
                    request.url.path,
                    _frame_summary(exc),
                )
                response = JSONResponse({"detail": GENERIC_ERROR}, status_code=500)

        headers = response.headers
        headers["Content-Security-Policy"] = csp
        headers["X-Content-Type-Options"] = "nosniff"
        headers["X-Frame-Options"] = "DENY"
        headers["Referrer-Policy"] = "no-referrer"
        headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        headers["Cross-Origin-Opener-Policy"] = "same-origin"
        if request.url.path.startswith("/api/"):
            headers["Cache-Control"] = "no-store"
        return response

    @app.get("/", include_in_schema=False)
    async def index() -> Response:
        return Response(content=html, media_type="text/html; charset=utf-8")

    @app.get("/sample.png", include_in_schema=False)
    async def sample() -> FileResponse:
        return FileResponse(SAMPLE_PATH, media_type="image/png")

    @app.get("/why.json", include_in_schema=False)
    async def why() -> FileResponse:
        return FileResponse(STATIC_DIR / "why.json", media_type="application/json")

    @app.get("/baseline.json", include_in_schema=False)
    async def baseline() -> FileResponse:
        return FileResponse(STATIC_DIR / "baseline.json", media_type="application/json")

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        # Deliberately limited to these fields: nothing here says whether an API
        # key is present. `mock` reflects the PROOFMODE_MOCK setting only.
        return {
            "ok": True,
            "mock": os.environ.get("PROOFMODE_MOCK") == "1",
            "model": model_from_env(),
        }

    @app.get("/api/capabilities")
    async def capabilities() -> dict[str, Any]:
        # What POST /api/review accepts on this server, so a page can hide a
        # control that would only return an error.
        return {
            "investigate": investigation_enabled,
            "text": True,
            "model": model_from_env(),
        }

    async def _investigate(
        *,
        data: bytes | None,
        declared_type: str | None,
        message_text: str | None,
        sources: list[Source],
        official_domain: str | None,
    ) -> Review:
        """Run one investigation under the overall deadline."""
        net = network_factory() if network_factory is not None else None
        try:
            async with asyncio.timeout(investigate_deadline):
                return await investigate(
                    image=data,
                    mime_type=declared_type,
                    text=message_text,
                    facts=sources,
                    official_domain=official_domain,
                    client=client,
                    model=model_from_env(),
                    http=net.http if net is not None else None,
                    resolver=net.resolver if net is not None else None,
                )
        except TimeoutError:
            # Cancelling the run closes its outbound connections. Nothing gathered
            # so far is returned: a half-read page is not a result.
            raise HTTPException(
                status_code=504,
                detail=(
                    "The investigation took too long and was stopped. Try again, or "
                    "run the check without investigation."
                ),
            ) from None
        finally:
            if net is not None:
                await net.http.aclose()

    @app.post(REVIEW_PATH)
    async def review(request: Request) -> dict[str, Any]:
        form = await _read_form(request)
        data: bytes | None = None
        declared_type: str | None = None
        try:
            flag = _text_field(form, "investigate", "the investigate field").strip()
            if flag not in {"", "0", "1"}:
                raise HTTPException(
                    status_code=400, detail="The investigate field must be 1 or 0."
                )
            investigating = flag == "1"
            if investigating and not investigation_enabled:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Investigation mode is turned off on this server. Run the "
                        "check without it and supply the official facts yourself."
                    ),
                )

            text = _text_field(form, "text", "the message")
            if len(text) > MAX_TEXT_CHARS:
                raise HTTPException(
                    status_code=413,
                    detail=f"The message is longer than {MAX_TEXT_CHARS:,} characters.",
                )
            message_text = text.strip() or None

            # The page sends the pasted facts as `sources`; `facts` is accepted too.
            facts = form.get("facts")
            if facts is None:
                facts = form.get("sources", "")
            if not isinstance(facts, str):
                raise HTTPException(
                    status_code=400, detail="Paste the official facts as text."
                )
            if len(facts) > MAX_FACTS_CHARS:
                raise HTTPException(
                    status_code=413,
                    detail=f"The facts are longer than {MAX_FACTS_CHARS:,} characters.",
                )

            official_domain = _official_domain(
                _text_field(form, "official_domain", "the official domain")
            )

            image = form.get("image")
            if image is not None and not isinstance(image, UploadFile):
                raise HTTPException(
                    status_code=400, detail="Send the screenshot as a file."
                )
            if image is None and message_text is None:
                raise HTTPException(
                    status_code=400,
                    detail="Attach a screenshot of the message or paste its text.",
                )
            if image is not None:
                declared_type = _normalise_mime(image.content_type)
                if declared_type not in ALLOWED_MIME_TYPES:
                    raise HTTPException(
                        status_code=415, detail="Upload a PNG, JPEG or WebP image."
                    )
                # Read one byte past the limit so an oversized image is detected.
                data = await image.read(MAX_IMAGE_BYTES + 1)
        finally:
            await form.close()

        if data is not None:
            if len(data) > MAX_IMAGE_BYTES:
                raise HTTPException(
                    status_code=413, detail="The image is larger than 8 MB."
                )
            if not data:
                raise HTTPException(status_code=400, detail="The image is empty.")
            if sniff_image_type(data) != declared_type:
                raise HTTPException(
                    status_code=415,
                    detail="The file is not a valid PNG, JPEG or WebP image.",
                )

        if investigating and not facts.strip():
            # An investigation may start with no facts: it gathers its own.
            parsed_sources: list[Source] = []
        else:
            try:
                parsed_sources = parse_sources(facts)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        if investigating:
            if official_domain is not None and message_text is not None:
                _refuse_domain_from_message(official_domain, message_text)
            # Counted only once the request is known to be runnable, so a typo in
            # the form does not use up an allowance. The general limit has
            # already been applied to this request in the middleware.
            retry_after = investigate_limiter.check(_client_key(request, trust_proxy))
            if retry_after:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        "Too many investigations. Wait a moment, or run the check "
                        "without investigation."
                    ),
                    headers={"Retry-After": str(retry_after)},
                )

        try:
            if client is None:
                raise client_error or ReviewError(
                    "The review client is not configured."
                )
            if investigating:
                result = await _investigate(
                    data=data,
                    declared_type=declared_type,
                    message_text=message_text,
                    sources=parsed_sources,
                    official_domain=official_domain,
                )
            elif data is not None and declared_type is not None:
                result = await run_review(
                    data,
                    declared_type,
                    parsed_sources,
                    client=client,
                    model=model_from_env(),
                )
                if message_text is not None:
                    result.notes.append(
                        "The pasted text was not used: without investigation a check "
                        "that has a screenshot reads the screenshot only."
                    )
            else:
                result = await run_review_text(
                    message_text or "",
                    parsed_sources,
                    client=client,
                    model=model_from_env(),
                )
        except ReviewError as exc:
            # ReviewError messages are written for the user and carry no internals.
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        return result.model_dump()

    return app
