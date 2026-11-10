"""HTTP surface of the FastAPI app, driven through TestClient with mock or failing clients."""

from typing import Any

import pytest
from conftest import EXAMPLE_FACTS
from fastapi.testclient import TestClient

from proofmode.app import MAX_TEXT_CHARS, create_app
from proofmode.openrouter import MockClient, ReviewError

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
OVERSIZED_IMAGE_BYTES = 8 * 1024 * 1024 + 1


def fixture_facts() -> str:
    """The example organisation's official facts, one per line.

    These are the facts the canned review cites, so the local citation check
    accepts every status the mock returns.
    """
    return "\n".join(EXAMPLE_FACTS)


class FailingClient:
    async def complete_json(self, **_: Any) -> dict[str, Any]:
        raise ReviewError("upstream rejected the request")


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(client_factory=lambda: MockClient()))


def post_review(
    client: TestClient,
    image: bytes,
    mime: str = "image/png",
    sources: str | None = None,
) -> Any:
    return client.post(
        "/api/review",
        files={"image": ("message.png", image, mime)},
        data={"sources": fixture_facts() if sources is None else sources},
    )


def test_index_serves_html_with_security_headers(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "ProofMode" in response.text
    assert "content-security-policy" in response.headers
    assert response.headers["x-content-type-options"] == "nosniff"


def test_health_reports_ok(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_review_returns_six_judged_items_and_a_verdict(
    client: TestClient, png_bytes: bytes
) -> None:
    response = post_review(client, png_bytes)

    assert response.status_code == 200
    body = response.json()
    statuses = [claim["status"] for claim in body["claims"]]
    assert len(statuses) == 6
    assert statuses.count("contradicted") == 5
    assert statuses.count("supported") == 1
    assert body["verdict"] == "contradicts_facts"


def test_claims_carry_correction_not_the_old_field(
    client: TestClient, png_bytes: bytes
) -> None:
    claims = post_review(client, png_bytes).json()["claims"]

    assert all("correction" in claim for claim in claims)
    assert all("suggested_rewrite" not in claim for claim in claims)
    assert all(
        claim["correction"] for claim in claims if claim["status"] == "contradicted"
    )


def test_review_rejects_wrong_mime_type(client: TestClient) -> None:
    response = post_review(client, b"hello", mime="text/plain")

    assert response.status_code == 415


def test_review_rejects_oversized_image(client: TestClient) -> None:
    oversized = PNG_SIGNATURE + b"\x00" * (OVERSIZED_IMAGE_BYTES - len(PNG_SIGNATURE))

    response = post_review(client, oversized)

    assert response.status_code == 413


def test_review_rejects_empty_sources(client: TestClient, png_bytes: bytes) -> None:
    response = post_review(client, png_bytes, sources="   \n  ")

    assert response.status_code == 400


def test_review_requires_an_image_or_text(client: TestClient) -> None:
    response = client.post("/api/review", files={"other": ("x.txt", b"x", "text/plain")})

    assert response.status_code == 400
    assert "screenshot" in response.json()["detail"]
    assert "text" in response.json()["detail"]


def test_review_accepts_facts_field_name(client: TestClient, png_bytes: bytes) -> None:
    response = client.post(
        "/api/review",
        files={"image": ("message.png", png_bytes, "image/png")},
        data={"facts": fixture_facts()},
    )

    assert response.status_code == 200
    assert response.json()["verdict"] == "contradicts_facts"


def test_client_error_returns_502_without_traceback(png_bytes: bytes) -> None:
    app_client = TestClient(create_app(client_factory=lambda: FailingClient()))

    response = post_review(app_client, png_bytes)

    assert response.status_code == 502
    assert response.json() == {"detail": "upstream rejected the request"}
    assert "Traceback" not in response.text
    assert 'File "' not in response.text


def test_sample_image_is_served_as_png(client: TestClient) -> None:
    response = client.get("/sample.png")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(PNG_SIGNATURE)


def test_why_json_is_served(client: TestClient) -> None:
    response = client.get("/why.json")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"


def test_baseline_json_is_served_with_usable_rules(client: TestClient) -> None:
    response = client.get("/baseline.json")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    body = response.json()
    assert body["label"] and body["source_name"]
    assert body["source_url"].startswith("https://")
    facts = body["facts"]
    assert 5 <= len(facts) <= 7
    # Each rule is sent as one line of `sources`, so it must be a single non-empty line.
    assert all(isinstance(fact, str) and fact.strip() for fact in facts)
    assert all(len(fact.splitlines()) == 1 for fact in facts)


def test_review_without_key_reports_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("PROOFMODE_MOCK", raising=False)
    app_client = TestClient(create_app())

    response = post_review(app_client, PNG_SIGNATURE + b"0" * 16)

    assert response.status_code == 502
    assert "OPENROUTER_API_KEY" in response.json()["detail"]


# Pasted text and investigation mode

MESSAGE_TEXT = (
    "From: Tidewater Cloud Billing <billing@tidewater-accounts.co>\n"
    "Your API credits expire in 24 hours. Pay a $49 reactivation fee with a gift card "
    "at https://tidewater-accounts.co/pay to keep your account."
)


class RecordingClient:
    """Returns one canned claim and records which engine entry point was used."""

    def __init__(self) -> None:
        self.json_calls: list[dict[str, Any]] = []
        self.tool_calls = 0

    async def complete_json(self, **kwargs: Any) -> dict[str, Any]:
        self.json_calls.append(kwargs)
        return {
            "claims": [
                {
                    "claim_text": "Your API credits expire in 24 hours.",
                    "status": "contradicted",
                    "source_ids": ["S1"],
                    "evidence_quotes": ["credits do not expire"],
                    "explanation": "S1 says credits do not expire.",
                    "correction": "Credits do not expire.",
                }
            ]
        }

    async def complete_tools(self, **_: Any) -> Any:
        self.tool_calls += 1
        raise AssertionError("the tool loop must not run without investigate=1")


def post_form(client: TestClient, **fields: str) -> Any:
    """POST text fields only, as multipart (a file part with no name is not sent)."""
    return client.post("/api/review", files={name: (None, value) for name, value in fields.items()})


def user_text(call: dict[str, Any]) -> str:
    """The text part of the user message in one recorded model call."""
    content = call["messages"][-1]["content"]
    return content if isinstance(content, str) else content[0]["text"]


def test_capabilities_reports_text_and_investigation(client: TestClient) -> None:
    response = client.get("/api/capabilities")

    assert response.status_code == 200
    assert response.json() == {"investigate": True, "text": True, "model": "meta/muse-ember"}
    assert response.headers["cache-control"] == "no-store"


def test_capabilities_reports_investigation_switched_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROOFMODE_INVESTIGATE", "0")
    monkeypatch.setenv("PROOFMODE_MODEL", "example/other-model")
    app_client = TestClient(create_app(client_factory=lambda: MockClient()))

    assert app_client.get("/api/capabilities").json() == {
        "investigate": False,
        "text": True,
        "model": "example/other-model",
    }


def test_text_only_runs_the_single_call_text_check() -> None:
    recorder = RecordingClient()
    app_client = TestClient(create_app(client_factory=lambda: recorder))

    response = post_form(app_client, text=MESSAGE_TEXT, sources=fixture_facts())

    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "contradicts_facts"
    assert [claim["status"] for claim in body["claims"]] == ["contradicted"]
    assert body["sources"] == [] and body["steps"] == []
    assert len(recorder.json_calls) == 1 and recorder.tool_calls == 0
    # The message went to the model as text, with no image part.
    content = recorder.json_calls[0]["messages"][-1]["content"]
    assert [part["type"] for part in content] == ["text"]
    assert "Pay a $49 reactivation fee" in user_text(recorder.json_calls[0])


def test_text_only_accepts_the_facts_field_name() -> None:
    app_client = TestClient(create_app(client_factory=lambda: RecordingClient()))

    response = post_form(app_client, text=MESSAGE_TEXT, facts=fixture_facts())

    assert response.status_code == 200


def test_text_only_without_facts_is_rejected(client: TestClient) -> None:
    response = post_form(client, text=MESSAGE_TEXT, sources="  ")

    assert response.status_code == 400
    assert "fact" in response.json()["detail"]


def test_blank_text_does_not_count_as_a_message(client: TestClient) -> None:
    response = post_form(client, text="  \n ", sources=fixture_facts())

    assert response.status_code == 400


def test_text_at_the_limit_is_accepted_and_over_it_is_rejected() -> None:
    app_client = TestClient(create_app(client_factory=lambda: RecordingClient()))

    at_limit = post_form(app_client, text="a" * MAX_TEXT_CHARS, sources=fixture_facts())
    over = post_form(app_client, text="a" * (MAX_TEXT_CHARS + 1), sources=fixture_facts())

    assert at_limit.status_code == 200
    assert over.status_code == 413
    assert "10,000" in over.json()["detail"]


def test_image_without_investigate_still_uses_the_screenshot_check(png_bytes: bytes) -> None:
    recorder = RecordingClient()
    app_client = TestClient(create_app(client_factory=lambda: recorder))

    response = app_client.post(
        "/api/review",
        files={"image": ("message.png", png_bytes, "image/png")},
        data={"sources": fixture_facts(), "text": MESSAGE_TEXT, "investigate": "0"},
    )

    assert response.status_code == 200
    content = recorder.json_calls[0]["messages"][-1]["content"]
    assert "image_url" in [part["type"] for part in content]
    # The pasted text is not sent on this path, and the result says so.
    assert "$49" not in user_text(recorder.json_calls[0])
    assert any("pasted text was not used" in note for note in response.json()["notes"])


def test_investigate_with_text_returns_sources_and_steps(client: TestClient) -> None:
    response = post_form(
        client, text=MESSAGE_TEXT, investigate="1", official_domain="tidewater.example"
    )

    assert response.status_code == 200
    body = response.json()
    assert [step["tool"] for step in body["steps"]] == [
        "fetch_official_page",
        "lookup_domain",
        "finish",
    ]
    assert all(set(step) == {"tool", "argument", "outcome", "ok"} for step in body["steps"])
    assert all(set(source) == {"id", "text", "url", "origin"} for source in body["sources"])
    origins = {source["origin"] for source in body["sources"]}
    assert origins == {"fetched", "lookup"}
    fetched = [source for source in body["sources"] if source["origin"] == "fetched"]
    assert all(source["url"].startswith("https://tidewater.example/") for source in fetched)
    assert body["verdict"] == "contradicts_facts"
    assert response.headers["cache-control"] == "no-store"


def test_investigate_with_a_screenshot_and_no_facts(client: TestClient, png_bytes: bytes) -> None:
    response = client.post(
        "/api/review",
        files={"image": ("message.png", png_bytes, "image/png")},
        data={"investigate": "1", "official_domain": "https://www.tidewater.example:443/help"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["steps"][0]["tool"] == "report_message"
    assert any(source["origin"] == "fetched" for source in body["sources"])


def test_investigate_keeps_user_facts_as_the_first_sources(client: TestClient) -> None:
    response = post_form(client, text=MESSAGE_TEXT, investigate="1", sources=fixture_facts())

    body = response.json()
    assert response.status_code == 200
    assert [source["origin"] for source in body["sources"][:5]] == ["user"] * 5
    assert body["sources"][0]["id"] == "S1"


def test_investigate_is_refused_when_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROOFMODE_INVESTIGATE", "0")
    recorder = RecordingClient()
    app_client = TestClient(create_app(client_factory=lambda: recorder))

    refused = post_form(app_client, text=MESSAGE_TEXT, investigate="1")
    plain = post_form(app_client, text=MESSAGE_TEXT, sources=fixture_facts())

    assert refused.status_code == 400
    assert "turned off" in refused.json()["detail"]
    assert plain.status_code == 200
    assert len(recorder.json_calls) == 1  # only the plain check reached the model


def test_investigate_field_must_be_one_or_zero(client: TestClient) -> None:
    response = post_form(client, text=MESSAGE_TEXT, investigate="yes", sources=fixture_facts())

    assert response.status_code == 400
    assert "investigate" in response.json()["detail"]


@pytest.mark.parametrize(
    "value",
    ["localhost", "127.0.0.1", "exa mple.org", "example", "bad_name.org", "a" * 260 + ".org"],
)
def test_invalid_official_domain_is_rejected(client: TestClient, value: str) -> None:
    response = post_form(client, text=MESSAGE_TEXT, investigate="1", official_domain=value)

    assert response.status_code == 400
    assert "official domain" in response.json()["detail"]


def test_official_domain_is_ignored_without_investigate() -> None:
    recorder = RecordingClient()
    app_client = TestClient(create_app(client_factory=lambda: recorder))

    response = post_form(
        app_client,
        text=MESSAGE_TEXT,
        sources=fixture_facts(),
        official_domain="tidewater.example",
    )

    assert response.status_code == 200
    assert response.json()["steps"] == []
    assert recorder.tool_calls == 0
