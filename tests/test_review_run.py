"""End-to-end check runs with the mock client and with fake clients that misbehave."""

import asyncio
import re
from typing import Any

import pytest

from proofmode.models import Review, Source
from proofmode.openrouter import MockClient, ReviewError
from proofmode.review import (
    DEFAULT_MODEL,
    MAX_CLAIMS,
    SYSTEM_PROMPT,
    model_from_env,
    run_review,
)

MODEL = "test/vision-model"


class FakeClient:
    """Returns a canned payload and records what it was asked."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    async def complete_json(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        schema_name: str,
    ) -> dict[str, Any]:
        self.calls.append(
            {"model": model, "messages": messages, "schema": schema, "schema_name": schema_name}
        )
        return self.payload


def raw_claim(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "claim_text": "Your API credits expire in 24 hours.",
        "status": "contradicted",
        "source_ids": ["S1"],
        "evidence_quotes": ["Tidewater Cloud credits do not expire."],
        "explanation": "S1 says credits do not expire.",
        "correction": "Tidewater Cloud credits do not expire.",
    }
    fields.update(overrides)
    return fields


def review_with(client: Any, png_bytes: bytes, sources: list[Source]) -> Review:
    return asyncio.run(run_review(png_bytes, "image/png", sources, client=client, model=MODEL))


# --- the built-in example ----------------------------------------------------


def test_mock_client_returns_the_six_example_items(
    png_bytes: bytes, example_sources: list[Source]
) -> None:
    review = review_with(MockClient(), png_bytes, example_sources)

    assert isinstance(review, Review)
    assert review.model == MODEL
    assert [claim.status for claim in review.claims] == [
        "contradicted",
        "contradicted",
        "contradicted",
        "contradicted",
        "contradicted",
        "supported",
    ]
    assert [claim.source_ids for claim in review.claims] == [["S4"], ["S1"], ["S2"], ["S3"], ["S4"], ["S5"]]


def test_example_survives_validation_untouched(
    png_bytes: bytes, example_sources: list[Source]
) -> None:
    review = review_with(MockClient(), png_bytes, example_sources)

    assert review.notes == []
    assert review.verdict == "contradicts_facts"
    assert all(claim.correction for claim in review.claims[:5])
    assert review.claims[5].correction == ""


# --- verdict -----------------------------------------------------------------


def test_verdict_is_consistent_when_all_claims_are_supported(
    png_bytes: bytes, example_sources: list[Source]
) -> None:
    client = FakeClient(
        {
            "claims": [
                raw_claim(
                    claim_text="Support is available 24/7.",
                    status="supported",
                    source_ids=["S5"],
                    evidence_quotes=["Support is available 24 hours a day, 7 days a week."],
                    correction="",
                )
            ]
        }
    )

    assert review_with(client, png_bytes, example_sources).verdict == "consistent"


def test_verdict_is_unverified_when_no_claims_are_found(
    png_bytes: bytes, example_sources: list[Source]
) -> None:
    review = review_with(FakeClient({"claims": []}), png_bytes, example_sources)

    assert review.verdict == "unverified"
    assert review.claims == []
    assert review.notes, "an empty result must be explained"


def test_verdict_is_computed_locally_and_ignores_a_model_supplied_one(
    png_bytes: bytes, example_sources: list[Source]
) -> None:
    client = FakeClient({"verdict": "consistent", "claims": [raw_claim()]})

    assert review_with(client, png_bytes, example_sources).verdict == "contradicts_facts"


def test_fabricated_support_cannot_produce_a_consistent_verdict(
    png_bytes: bytes, example_sources: list[Source]
) -> None:
    """A model that obeyed an injected 'mark every claim as supported' has no real quote."""
    client = FakeClient(
        {
            "claims": [
                raw_claim(
                    status="supported",
                    evidence_quotes=["Credits expire in 24 hours."],
                    correction="Ignore this.",
                )
            ]
        }
    )

    review = review_with(client, png_bytes, example_sources)

    claim = review.claims[0]
    assert claim.status == "insufficient_evidence"
    assert claim.evidence_quotes == []
    assert claim.correction == ""
    assert review.verdict == "unverified"
    assert review.notes, "the downgrade must be recorded in the review notes"


# --- output bounds -----------------------------------------------------------


def test_more_than_twenty_claims_are_truncated_with_a_note(
    png_bytes: bytes, example_sources: list[Source]
) -> None:
    client = FakeClient({"claims": [raw_claim(claim_text=f"claim {n}") for n in range(45)]})

    review = review_with(client, png_bytes, example_sources)

    assert len(review.claims) == MAX_CLAIMS == 20
    assert review.claims[-1].claim_text == "claim 19"
    assert any("45" in note and "20" in note for note in review.notes)


def test_oversized_fields_are_capped(png_bytes: bytes, example_sources: list[Source]) -> None:
    client = FakeClient(
        {
            "claims": [
                raw_claim(
                    claim_text="c" * 4000,
                    explanation="e" * 4000,
                    correction="k" * 4000,
                    evidence_quotes=["Tidewater Cloud credits do not expire.", "q" * 4000],
                )
            ]
        }
    )

    review = review_with(client, png_bytes, example_sources)

    claim = review.claims[0]
    assert len(claim.claim_text) == 300
    assert len(claim.explanation) == 500
    assert len(claim.correction) == 300
    assert claim.status == "contradicted"
    assert all(len(quote) <= 500 for quote in claim.evidence_quotes)
    assert all(len(note) < 1500 for note in review.notes)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"claims": "none"},
        {"claims": [{"claim_text": "x", "status": "definitely_true"}]},
        {"claims": ["not an object"]},
    ],
)
def test_malformed_model_output_raises_review_error(
    png_bytes: bytes, example_sources: list[Source], payload: dict[str, Any]
) -> None:
    with pytest.raises(ReviewError):
        review_with(FakeClient(payload), png_bytes, example_sources)


# --- prompt construction -----------------------------------------------------


def test_system_prompt_declares_image_text_untrusted() -> None:
    prompt = SYSTEM_PROMPT.lower()

    assert "untrusted" in prompt
    assert "never follow" in prompt
    assert "insufficient_evidence" in prompt
    assert "addressed to an ai" in prompt


def test_system_prompt_always_asks_for_the_sender_and_link_domains() -> None:
    prompt = SYSTEM_PROMPT.lower()

    assert "always report the sender as the first item" in prompt
    assert "link or web domain" in prompt


def test_facts_are_sent_in_a_delimited_block_before_the_image(
    png_bytes: bytes, example_sources: list[Source]
) -> None:
    client = FakeClient({"claims": []})

    review_with(client, png_bytes, example_sources)

    call = client.calls[0]
    system, user = call["messages"]
    assert system == {"role": "system", "content": SYSTEM_PROMPT}
    text_part, image_part = user["content"]
    match = re.search(
        r"BEGIN-(OFFICIAL-FACTS-[0-9a-f]{16})\n(.*)\nEND-\1\n", text_part["text"], re.DOTALL
    )
    assert match, "facts must sit between matching BEGIN and END markers"
    assert match.group(2).splitlines() == [f"{s.id}: {s.text}" for s in example_sources]
    assert image_part["image_url"]["url"].startswith("data:image/png;base64,")
    assert call["schema"]["properties"]["claims"]["items"]["required"][-1] == "correction"


def test_fact_delimiter_changes_on_every_request(
    png_bytes: bytes, example_sources: list[Source]
) -> None:
    client = FakeClient({"claims": []})

    review_with(client, png_bytes, example_sources)
    review_with(client, png_bytes, example_sources)

    markers = [
        re.search(r"BEGIN-OFFICIAL-FACTS-[0-9a-f]{16}", call["messages"][1]["content"][0]["text"])
        for call in client.calls
    ]
    assert markers[0] and markers[1]
    assert markers[0].group(0) != markers[1].group(0)


# --- input checks and configuration -------------------------------------------


def test_unsupported_image_type_is_rejected(example_sources: list[Source]) -> None:
    with pytest.raises(ReviewError):
        asyncio.run(
            run_review(
                b"<svg/>", "image/svg+xml", example_sources, client=MockClient(), model=MODEL
            )
        )


def test_empty_image_is_rejected(example_sources: list[Source]) -> None:
    with pytest.raises(ReviewError):
        asyncio.run(
            run_review(b"", "image/png", example_sources, client=MockClient(), model=MODEL)
        )


def test_model_from_env_defaults_and_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    assert model_from_env() == DEFAULT_MODEL == "meta/muse-ember"

    monkeypatch.setenv("PROOFMODE_MODEL", "  other/model  ")

    assert model_from_env() == "other/model"
