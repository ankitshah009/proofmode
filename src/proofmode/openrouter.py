"""OpenRouter Chat Completions client, plus a canned-output mock for demos.

Image message format (verified against the OpenRouter docs on 2026-11-09):

    {"type": "image_url", "image_url": {"url": "data:image/png;base64,<...>"}}

Sources:
- Chat Completions request schema, ``ChatContentImage`` and ``ChatUserMessage``
  (content may be an array of ``ChatContentItems``):
  https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion.md
- ``image_url`` accepts ``data:`` URLs (same page, ``ChatContentImage.url``).
- Supported types (png, jpeg, webp, gif) and the base64 data-URL approach:
  https://openrouter.ai/docs/guides/overview/multimodal/image-understanding.md
  That guide documents the Responses API ``input_image`` part; the Chat
  Completions equivalent is the ``image_url`` part above.
- Structured outputs (``response_format`` with ``type: "json_schema"``) and
  ``provider.require_parameters``: same Chat Completions page
  (``ChatFormatJsonSchemaConfig``, ``ProviderPreferences``).

Tool calling (verified on 2026-11-09):
- https://openrouter.ai/docs/llms.txt lists the guide
  https://openrouter.ai/docs/guides/features/tool-calling.md. Its Chat Completions
  section confirms the shapes used by ``complete_tools``:
  request ``tools: [{"type": "function", "function": {"name", "description",
  "parameters": <JSON schema>}}]``; the reply is an assistant message carrying
  ``tool_calls: [{"id", "type": "function", "function": {"name", "arguments":
  "<JSON string>"}}]`` with ``content`` possibly null; each result goes back as
  ``{"role": "tool", "tool_call_id": <id>, "content": <string>}`` after the
  assistant message, with ``tools`` repeated on every request.
- ``tool_choice`` is "auto", "none", or, to force one function on Chat
  Completions, ``{"type": "function", "function": {"name": <name>}}``. In a live
  run on 2026-11-09 ``meta/muse-ember`` handled "auto" over several turns, but a
  request forcing one function came back as HTTP 404 (with
  ``provider.require_parameters`` no provider accepted it), so callers in this
  project use "auto" only.
- https://openrouter.ai/api/v1/models lists ``tools`` and ``tool_choice`` in
  ``supported_parameters`` for ``meta/muse-ember`` (alongside ``response_format``
  and ``structured_outputs``).

Privacy and error hygiene:
- The optional ``user`` field (an opaque end-user identifier OpenRouter uses for
  abuse detection) is sent only when PROOFMODE_USER_ID is set.
- Error messages carry the HTTP status code and a short generic reason. They never
  include the API key or any part of the upstream response body.
"""

from __future__ import annotations

import importlib.resources
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from proofmode.tools import (
    DEMO_LOOKUP_DOMAIN,
    DEMO_OFFICIAL_URL,
    TOOL_FETCH,
    TOOL_FINISH,
    TOOL_LOOKUP,
)

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_TIMEOUT = 120.0
MOCK_ENV_VAR = "PROOFMODE_MOCK"
API_KEY_ENV_VAR = "OPENROUTER_API_KEY"
USER_ID_ENV_VAR = "PROOFMODE_USER_ID"
FIXTURE_NAME = "example_review.json"
# schema_name of the call that reads a screenshot's domains in investigation mode.
READ_SCHEMA_NAME = "proofmode_message"
_MAX_USER_ID_CHARS = 128

# Generic reasons by status code. The upstream body is deliberately never echoed.
_STATUS_REASONS: dict[int, str] = {
    400: "the request was rejected as invalid",
    401: "the API key was rejected",
    402: "the account has insufficient credits",
    403: "access to this model was refused",
    404: "the model or a provider that supports this request was not found",
    408: "the request timed out",
    413: "the image is too large",
    429: "the rate limit was reached, try again shortly",
}


def _status_reason(status_code: int) -> str:
    """Return a short, fixed reason for a non-2xx status code."""
    if status_code in _STATUS_REASONS:
        return _STATUS_REASONS[status_code]
    if status_code >= 500:
        return "the provider is unavailable, try again shortly"
    return "the request failed"


class ReviewError(Exception):
    """A provider, transport, or response-parsing failure with a user-safe message."""


@dataclass(frozen=True)
class ToolCall:
    """One function call requested by the model.

    arguments is None when the model sent arguments that are not a JSON object.
    """

    id: str
    name: str
    arguments: dict[str, Any] | None


@dataclass(frozen=True)
class ToolTurn:
    """One assistant turn of a tool-calling conversation.

    message is the assistant message to append to the history before the tool
    results; tool_calls is the parsed view of the same calls.
    """

    message: dict[str, Any]
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


ToolChoice = str | dict[str, Any]


class OpenRouterClient:
    """Minimal async client for OpenRouter's Chat Completions endpoint."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._transport = transport
        self._timeout = timeout

    async def complete_json(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        schema_name: str = "proofmode_review",
    ) -> dict[str, Any]:
        """Request a JSON-schema-constrained completion and return the parsed object.

        Raises ReviewError on transport failure, non-2xx status, missing content,
        or content that is not a JSON object. Error messages never contain the API
        key or the upstream response body.
        """
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            },
            "provider": {"require_parameters": True},
        }
        envelope = await self._post(payload, timeout=self._timeout)
        content = _extract_content(envelope)
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            raise ReviewError(
                "The model's reply was not valid JSON. Try again or pick another model."
            ) from None
        if not isinstance(parsed, dict):
            raise ReviewError("The model's reply was JSON but not an object.")
        return parsed


    async def complete_tools(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: ToolChoice = "auto",
        timeout: float | None = None,
    ) -> ToolTurn:
        """Request one assistant turn that may call the given function tools.

        tool_choice is "auto", "none", or an object naming one function. Raises
        ReviewError on transport failure, non-2xx status, or a reply with neither
        text nor a tool call. Error messages never contain the API key or the
        upstream response body.
        """
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "tool_choice": tool_choice,
            "provider": {"require_parameters": True},
        }
        envelope = await self._post(
            payload, timeout=self._timeout if timeout is None else timeout
        )
        return _extract_tool_turn(envelope)

    async def _post(self, payload: dict[str, Any], *, timeout: float) -> object:
        """POST one Chat Completions request and return the decoded JSON envelope."""
        user_id = os.environ.get(USER_ID_ENV_VAR, "").strip()
        if user_id:
            payload["user"] = user_id[:_MAX_USER_ID_CHARS]
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            # Attribution on openrouter.ai (docs/api-reference/overview).
            "X-OpenRouter-Title": "ProofMode",
        }
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=httpx.Timeout(timeout),
            ) as http:
                response = await http.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            raise ReviewError(
                f"Could not reach OpenRouter ({type(exc).__name__}). Try again."
            ) from None

        if not response.is_success:
            raise ReviewError(
                f"OpenRouter returned HTTP {response.status_code}: "
                f"{_status_reason(response.status_code)}."
            )

        try:
            return response.json()
        except ValueError:
            raise ReviewError("OpenRouter returned a response that is not JSON.") from None


# Numbered evidence lines as they appear in the conversation, e.g. "S3: text".
_SOURCE_LINE_RE = re.compile(r"^(S\d+): (.+)$", re.MULTILINE)


class MockClient:
    """Drop-in replacement for OpenRouterClient that returns the canned fixture."""

    async def complete_json(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        schema_name: str = "proofmode_review",
    ) -> dict[str, Any]:
        """Return the fixture JSON; arguments are accepted for interface parity only.

        The one exception is the investigation call that reads a screenshot's
        domains (schema_name READ_SCHEMA_NAME), which gets the example's answer.
        """
        del model, messages, schema
        fixture = importlib.resources.files("proofmode").joinpath("fixtures", FIXTURE_NAME)
        try:
            data = json.loads(fixture.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReviewError(f"Mock fixture could not be loaded: {type(exc).__name__}") from None
        if not isinstance(data, dict):
            raise ReviewError("Mock fixture must contain a JSON object.")
        if schema_name == READ_SCHEMA_NAME:
            claims = data.get("claims")
            transcript = " ".join(
                str(claim.get("claim_text", ""))
                for claim in (claims if isinstance(claims, list) else [])
                if isinstance(claim, dict)
            )
            return {"domains": [DEMO_LOOKUP_DOMAIN], "transcript": transcript}
        return data

    async def complete_tools(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: ToolChoice = "auto",
        timeout: float | None = None,
    ) -> ToolTurn:
        """Play a fixed investigation: read one official page, look up the sender's
        domain, then finish with the fixture claims.

        The script is stateless. It reads the conversation so far to decide the
        next step, and cites the fixture quotes against whichever numbered lines
        actually contain them, so the local citation check passes or fails on its
        merits.
        """
        del model, tools, tool_choice, timeout
        done = _called_tools(messages)
        if TOOL_FETCH not in done:
            return _mock_turn(TOOL_FETCH, {"url": DEMO_OFFICIAL_URL}, len(done))
        if TOOL_LOOKUP not in done:
            return _mock_turn(TOOL_LOOKUP, {"domain": DEMO_LOOKUP_DOMAIN}, len(done))

        fixture = await self.complete_json(
            model="", messages=[], schema={}, schema_name=""
        )
        return _mock_turn(
            TOOL_FINISH, {"claims": _recite(fixture.get("claims"), messages)}, len(done)
        )


def _called_tools(messages: list[dict[str, Any]]) -> list[str]:
    """Names of every tool the assistant has already called in this conversation."""
    names: list[str] = []
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            function = call.get("function") if isinstance(call, dict) else None
            if isinstance(function, dict) and isinstance(function.get("name"), str):
                names.append(function["name"])
    return names


def _mock_turn(name: str, arguments: dict[str, Any], index: int) -> ToolTurn:
    """Build an assistant turn holding one tool call, in the upstream shape."""
    call_id = f"mock_call_{index + 1}"
    message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
    }
    return ToolTurn(
        message=message,
        tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)],
    )


def _conversation_text(messages: list[dict[str, Any]]) -> str:
    """Join the text of user and tool messages, where numbered lines live."""
    parts: list[str] = []
    for message in messages:
        if message.get("role") not in {"user", "tool"}:
            continue
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts.extend(
                part["text"]
                for part in content
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            )
    return "\n".join(parts)


def _recite(raw_claims: object, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Point the fixture claims at the numbered lines present in this conversation.

    Each quote is matched to the first line that contains it. The first claim (the
    sender) also cites the registration lookup line when there is one.
    """
    lines = _SOURCE_LINE_RE.findall(_conversation_text(messages))
    claims: list[dict[str, Any]] = []
    for position, raw in enumerate(raw_claims if isinstance(raw_claims, list) else []):
        if not isinstance(raw, dict):
            continue
        claim = dict(raw)
        quotes = [quote for quote in claim.get("evidence_quotes", []) if isinstance(quote, str)]
        ids: list[str] = []
        for quote in quotes:
            for source_id, text in lines:
                if quote.lower() in text.lower():
                    if source_id not in ids:
                        ids.append(source_id)
                    break
        if position == 0:
            marker = f"{DEMO_LOOKUP_DOMAIN} was registered on"
            for source_id, text in lines:
                if text.startswith(marker):
                    ids.append(source_id)
                    quotes.append(marker)
                    break
        if ids:
            # Keep the explanation in step with the renumbered citation.
            old_ids = [item for item in claim.get("source_ids", []) if isinstance(item, str)]
            if old_ids and isinstance(claim.get("explanation"), str):
                claim["explanation"] = re.sub(
                    rf"\b{re.escape(old_ids[0])}\b", ids[0], claim["explanation"]
                )
            claim["source_ids"] = ids
        claim["evidence_quotes"] = quotes
        claims.append(claim)
    return claims


def client_from_env() -> OpenRouterClient | MockClient:
    """Return a MockClient when PROOFMODE_MOCK=1, otherwise a live client.

    Raises ReviewError when the live client is requested without OPENROUTER_API_KEY.
    """
    if os.environ.get(MOCK_ENV_VAR) == "1":
        return MockClient()
    api_key = os.environ.get(API_KEY_ENV_VAR, "").strip()
    if not api_key:
        raise ReviewError("OPENROUTER_API_KEY is not set. Set it or use PROOFMODE_MOCK=1.")
    return OpenRouterClient(api_key=api_key)


def _extract_content(envelope: object) -> str:
    """Return choices[0].message.content, or raise ReviewError if it is absent."""
    if not isinstance(envelope, dict):
        raise ReviewError("OpenRouter returned an unexpected response shape.")
    choices = envelope.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ReviewError("OpenRouter returned no choices.")
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ReviewError("The model returned an empty reply.")
    return content


def _extract_tool_turn(envelope: object) -> ToolTurn:
    """Parse choices[0].message of a tool-calling reply into a ToolTurn.

    A call whose arguments are not a JSON object is kept with arguments=None so
    the caller can tell the model what went wrong. Raises ReviewError when the
    reply has neither text nor a tool call.
    """
    if not isinstance(envelope, dict):
        raise ReviewError("OpenRouter returned an unexpected response shape.")
    choices = envelope.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ReviewError("OpenRouter returned no choices.")
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else None
    if not isinstance(message, dict):
        raise ReviewError("OpenRouter returned an unexpected response shape.")

    raw_content = message.get("content")
    content = raw_content if isinstance(raw_content, str) and raw_content.strip() else None

    calls: list[ToolCall] = []
    history_calls: list[dict[str, Any]] = []
    raw_calls = message.get("tool_calls")
    for index, raw in enumerate(raw_calls if isinstance(raw_calls, list) else []):
        function = raw.get("function") if isinstance(raw, dict) else None
        if not isinstance(function, dict) or not isinstance(function.get("name"), str):
            continue
        call_id = raw.get("id")
        if not isinstance(call_id, str) or not call_id:
            call_id = f"call_{index + 1}"
        raw_arguments = function.get("arguments")
        arguments: dict[str, Any] | None = None
        if isinstance(raw_arguments, dict):
            arguments = raw_arguments
        elif isinstance(raw_arguments, str):
            try:
                decoded = json.loads(raw_arguments) if raw_arguments.strip() else {}
            except json.JSONDecodeError:
                decoded = None
            arguments = decoded if isinstance(decoded, dict) else None
        calls.append(ToolCall(id=call_id, name=function["name"], arguments=arguments))
        history_calls.append(
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": function["name"],
                    "arguments": raw_arguments
                    if isinstance(raw_arguments, str)
                    else json.dumps(raw_arguments if isinstance(raw_arguments, dict) else {}),
                },
            }
        )

    if not calls and content is None:
        raise ReviewError("The model returned an empty reply.")

    history: dict[str, Any] = {"role": "assistant", "content": content}
    if history_calls:
        history["tool_calls"] = history_calls
    # Reasoning models may need their reasoning blocks passed back unchanged to
    # continue a tool-calling conversation.
    if isinstance(message.get("reasoning_details"), list):
        history["reasoning_details"] = message["reasoning_details"]
    return ToolTurn(message=history, content=content, tool_calls=calls)
