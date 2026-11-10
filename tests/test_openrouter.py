"""OpenRouter client behaviour, exercised through httpx.MockTransport (no real network)."""

import asyncio
import json
from typing import Any

import httpx
import pytest

from proofmode.openrouter import (
    MockClient,
    OpenRouterClient,
    ReviewError,
    client_from_env,
)

API_KEY = "sk-or-test-SECRET-0123456789"
MODEL = "test/vision-model"
SCHEMA_NAME = "proofmode_review"
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"claims": {"type": "array"}},
    "required": ["claims"],
    "additionalProperties": False,
}
IMAGE_URL = "data:image/png;base64,iVBORw0KGgo="
MESSAGES: list[dict[str, Any]] = [
    {
        "role": "user",
        "content": [
            {"type": "text", "text": "Check this message against the facts."},
            {"type": "image_url", "image_url": {"url": IMAGE_URL}},
        ],
    }
]


def ok_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"role": "assistant", "content": content}}]},
    )


def make_client(handler: Any) -> OpenRouterClient:
    return OpenRouterClient(API_KEY, transport=httpx.MockTransport(handler))


def complete(client: Any, messages: list[dict[str, Any]] = MESSAGES) -> Any:
    return asyncio.run(
        client.complete_json(
            model=MODEL,
            messages=messages,
            schema=SCHEMA,
            schema_name=SCHEMA_NAME,
        )
    )


def test_request_asks_for_strict_json_schema_with_required_parameters() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return ok_response(json.dumps({"claims": []}))

    result = complete(make_client(handler))

    body = seen["body"]
    assert seen["url"].endswith("/chat/completions")
    assert body["model"] == MODEL
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["name"] == SCHEMA_NAME
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["response_format"]["json_schema"]["schema"] == SCHEMA
    assert body["provider"]["require_parameters"] is True
    assert result == {"claims": []}


def test_request_carries_image_part_in_messages() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return ok_response(json.dumps({"claims": []}))

    complete(make_client(handler))

    image_parts = [
        part
        for message in seen["body"]["messages"]
        if isinstance(message["content"], list)
        for part in message["content"]
        if part.get("type") == "image_url"
    ]
    assert len(image_parts) == 1
    assert image_parts[0]["image_url"]["url"] == IMAGE_URL


def test_authorization_header_is_bearer_key() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        return ok_response(json.dumps({"claims": []}))

    complete(make_client(handler))

    assert seen["auth"] == f"Bearer {API_KEY}"


UPSTREAM_BODY_MARKER = "upstream-body-detail-7f3a"


@pytest.mark.parametrize("status", [400, 401, 402, 404, 418, 429, 500, 503])
def test_non_2xx_error_has_status_but_no_key_and_no_upstream_body(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            json={
                "error": {
                    "message": f"{UPSTREAM_BODY_MARKER} for key {API_KEY}",
                    "metadata": {"raw": UPSTREAM_BODY_MARKER},
                }
            },
        )

    with pytest.raises(ReviewError) as excinfo:
        complete(make_client(handler))

    for rendered in (str(excinfo.value), repr(excinfo.value)):
        assert str(status) in rendered
        assert API_KEY not in rendered
        assert UPSTREAM_BODY_MARKER not in rendered
    assert excinfo.value.__cause__ is None


def test_transport_failure_raises_review_error_without_leaking_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"connect failed with {API_KEY}", request=request)

    with pytest.raises(ReviewError) as excinfo:
        complete(make_client(handler))

    assert API_KEY not in str(excinfo.value)
    assert excinfo.value.__cause__ is None


def test_bad_success_body_does_not_echo_upstream_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return ok_response(f"{UPSTREAM_BODY_MARKER} not json {{")

    with pytest.raises(ReviewError) as excinfo:
        complete(make_client(handler))

    assert UPSTREAM_BODY_MARKER not in str(excinfo.value)


def sent_request(monkeypatch: pytest.MonkeyPatch, user_id: str | None) -> httpx.Request:
    seen: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return ok_response(json.dumps({"claims": []}))

    if user_id is not None:
        monkeypatch.setenv("PROOFMODE_USER_ID", user_id)
    complete(make_client(handler))
    return seen["request"]


def test_user_field_is_omitted_when_env_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    request = sent_request(monkeypatch, None)

    assert "user" not in json.loads(request.content)


@pytest.mark.parametrize("blank", ["", "   "])
def test_user_field_is_omitted_when_env_is_blank(
    monkeypatch: pytest.MonkeyPatch, blank: str
) -> None:
    request = sent_request(monkeypatch, blank)

    assert "user" not in json.loads(request.content)


def test_user_field_is_sent_when_env_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    request = sent_request(monkeypatch, " team-42 ")

    assert json.loads(request.content)["user"] == "team-42"


def test_title_header_is_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    request = sent_request(monkeypatch, None)

    assert request.headers["x-openrouter-title"] == "ProofMode"


def test_invalid_json_content_raises_review_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return ok_response("this is not json {")

    with pytest.raises(ReviewError):
        complete(make_client(handler))


def test_client_from_env_returns_mock_when_mock_flag_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROOFMODE_MOCK", "1")

    assert isinstance(client_from_env(), MockClient)


def test_client_from_env_without_key_or_mock_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROOFMODE_MOCK", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(ReviewError):
        client_from_env()


def test_client_from_env_with_key_returns_openrouter_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROOFMODE_MOCK", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", API_KEY)

    assert isinstance(client_from_env(), OpenRouterClient)


def test_mock_client_returns_example_fixture_with_six_items() -> None:
    result = complete(MockClient())

    assert [claim["status"] for claim in result["claims"]] == ["contradicted"] * 5 + ["supported"]
    assert all(set(claim) == CLAIM_FIELDS for claim in result["claims"])
    assert result["claims"][5]["correction"] == ""


CLAIM_FIELDS = {
    "claim_text",
    "status",
    "source_ids",
    "evidence_quotes",
    "explanation",
    "correction",
}
