"""Fact parsing, deterministic claim validation, bounds and verdict (no network, no model)."""

import pytest

from proofmode.models import Claim, Source
from proofmode.review import (
    MAX_CLAIM_TEXT_CHARS,
    MAX_CLAIMS,
    MAX_CORRECTION_CHARS,
    MAX_EXPLANATION_CHARS,
    MAX_QUOTE_CHARS,
    bound_claims,
    compute_verdict,
    parse_sources,
    validate_claims,
)

SOURCES_TEXT = (
    "- Tidewater Cloud credits do not expire.\n"
    "- Tidewater Cloud never charges a reactivation fee.\n"
    "- Payments are accepted by card or bank transfer only; gift cards are never accepted.\n"
    "- Official messages are sent only from tidewater.example and link only to tidewater.example.\n"
    "- Support is available 24 hours a day, 7 days a week."
)


def supported_claim(**overrides: object) -> Claim:
    fields: dict[str, object] = {
        "claim_text": "Support is available 24/7.",
        "status": "supported",
        "source_ids": ["S5"],
        "evidence_quotes": ["Support is available 24 hours a day"],
        "explanation": "S5 says support is available around the clock.",
        "correction": "",
    }
    fields.update(overrides)
    return Claim(**fields)  # type: ignore[arg-type]


def contradicted_claim(**overrides: object) -> Claim:
    fields: dict[str, object] = {
        "claim_text": "Your API credits expire in 24 hours.",
        "status": "contradicted",
        "source_ids": ["S1"],
        "evidence_quotes": ["Tidewater Cloud credits do not expire."],
        "explanation": "S1 says credits do not expire.",
        "correction": "Tidewater Cloud credits do not expire.",
    }
    fields.update(overrides)
    return Claim(**fields)  # type: ignore[arg-type]


def unverified_claim(**overrides: object) -> Claim:
    fields: dict[str, object] = {
        "claim_text": "Your invoice is attached.",
        "status": "insufficient_evidence",
        "explanation": "No fact covers invoices.",
    }
    fields.update(overrides)
    return Claim(**fields)  # type: ignore[arg-type]


# --- parse_sources -----------------------------------------------------------


def test_parse_sources_strips_bullets_and_assigns_sequential_ids() -> None:
    sources = parse_sources(SOURCES_TEXT)

    assert [s.id for s in sources] == ["S1", "S2", "S3", "S4", "S5"]
    assert sources[0].text == "Tidewater Cloud credits do not expire."
    assert sources[4].text == "Support is available 24 hours a day, 7 days a week."
    assert all(isinstance(s, Source) for s in sources)


@pytest.mark.parametrize("bullet", ["- ", "* ", "• ", "1. ", "2) "])
def test_parse_sources_strips_each_bullet_style(bullet: str) -> None:
    sources = parse_sources(f"{bullet}Credits do not expire.")

    assert sources == [Source(id="S1", text="Credits do not expire.")]


def test_parse_sources_keeps_a_fact_that_starts_with_a_number() -> None:
    sources = parse_sources("24 hours a day support.")

    assert sources == [Source(id="S1", text="24 hours a day support.")]


def test_parse_sources_skips_blank_lines() -> None:
    sources = parse_sources("\n\n- first fact\n\n- second fact\n")

    assert [(s.id, s.text) for s in sources] == [("S1", "first fact"), ("S2", "second fact")]


@pytest.mark.parametrize("empty", ["", "   ", "\n \n\t\n"])
def test_parse_sources_rejects_empty_input(empty: str) -> None:
    with pytest.raises(ValueError):
        parse_sources(empty)


def test_parse_sources_accepts_exactly_forty() -> None:
    text = "\n".join(f"- fact {n}" for n in range(1, 41))

    sources = parse_sources(text)

    assert len(sources) == 40
    assert sources[-1] == Source(id="S40", text="fact 40")


def test_parse_sources_rejects_more_than_forty() -> None:
    text = "\n".join(f"- fact {n}" for n in range(1, 42))

    with pytest.raises(ValueError):
        parse_sources(text)


# --- validate_claims ---------------------------------------------------------


def test_valid_claims_pass_through_unchanged(example_sources: list[Source]) -> None:
    claims_in = [supported_claim(), contradicted_claim()]

    claims, notes = validate_claims(claims_in, example_sources)

    assert claims == claims_in
    assert notes == []


def test_invented_quote_is_dropped_and_claim_downgraded(example_sources: list[Source]) -> None:
    claim = supported_claim(evidence_quotes=["Support replies within one hour"])

    claims, notes = validate_claims([claim], example_sources)

    assert claims[0].evidence_quotes == []
    assert claims[0].status == "insufficient_evidence"
    assert notes, "a downgrade must be explained in the notes"


def test_supported_claim_without_any_quote_is_downgraded(example_sources: list[Source]) -> None:
    claim = supported_claim(evidence_quotes=[])

    claims, notes = validate_claims([claim], example_sources)

    assert claims[0].status == "insufficient_evidence"
    assert claims[0].source_ids == []
    assert notes, "a downgrade must be explained in the notes"


def test_quote_from_an_uncited_fact_does_not_count(example_sources: list[Source]) -> None:
    claim = supported_claim(source_ids=["S1"])  # the quote lives in S5

    claims, _ = validate_claims([claim], example_sources)

    assert claims[0].status == "insufficient_evidence"


def test_verified_quote_survives_next_to_invented_quote(example_sources: list[Source]) -> None:
    claim = supported_claim(
        evidence_quotes=["Support is available 24 hours a day", "Replies within one hour"]
    )

    claims, _ = validate_claims([claim], example_sources)

    assert claims[0].status == "supported"
    assert claims[0].evidence_quotes == ["Support is available 24 hours a day"]


def test_nonexistent_source_id_is_dropped(example_sources: list[Source]) -> None:
    claim = supported_claim(source_ids=["S5", "S9"])

    claims, _ = validate_claims([claim], example_sources)

    assert claims[0].source_ids == ["S5"]
    assert claims[0].status == "supported"


@pytest.mark.parametrize(
    "quote",
    [
        "SUPPORT IS   available 24 HOURS a day",
        "  support is available\n\t24 hours a day  ",
    ],
)
def test_quote_matching_ignores_case_and_extra_whitespace(
    example_sources: list[Source], quote: str
) -> None:
    claim = supported_claim(evidence_quotes=[quote])

    claims, _ = validate_claims([claim], example_sources)

    assert claims[0].status == "supported"
    assert len(claims[0].evidence_quotes) == 1


def test_insufficient_evidence_claim_keeps_its_explanation(example_sources: list[Source]) -> None:
    claim = unverified_claim()

    claims, notes = validate_claims([claim], example_sources)

    assert claims == [claim]
    assert notes == []


def test_claim_text_is_never_changed(example_sources: list[Source]) -> None:
    claims_in = [
        supported_claim(),
        supported_claim(evidence_quotes=["Replies within one hour"]),
        supported_claim(evidence_quotes=[]),
        supported_claim(source_ids=["S9"]),
        unverified_claim(),
        contradicted_claim(),
    ]
    original_texts = [c.claim_text for c in claims_in]

    claims_out, _ = validate_claims(claims_in, example_sources)

    assert [c.claim_text for c in claims_out] == original_texts
    assert len(claims_out) == len(claims_in)


# --- correction --------------------------------------------------------------


def test_correction_is_kept_on_a_valid_contradicted_claim(example_sources: list[Source]) -> None:
    claims, _ = validate_claims([contradicted_claim()], example_sources)

    assert claims[0].status == "contradicted"
    assert claims[0].correction == "Tidewater Cloud credits do not expire."


def test_correction_is_cleared_when_claim_is_downgraded(example_sources: list[Source]) -> None:
    claim = contradicted_claim(evidence_quotes=["Credits expire after a year."])

    claims, _ = validate_claims([claim], example_sources)

    assert claims[0].status == "insufficient_evidence"
    assert claims[0].correction == ""


@pytest.mark.parametrize("make", [supported_claim, unverified_claim])
def test_correction_is_cleared_on_claims_that_are_not_contradicted(
    example_sources: list[Source], make: object
) -> None:
    claim = make(correction="Something the model should not have written.")  # type: ignore[operator]

    claims, _ = validate_claims([claim], example_sources)

    assert claims[0].correction == ""


# --- compute_verdict ---------------------------------------------------------


def test_verdict_is_contradicts_facts_when_any_claim_is_contradicted() -> None:
    claims = [supported_claim(), unverified_claim(), contradicted_claim()]

    assert compute_verdict(claims) == "contradicts_facts"


def test_verdict_is_consistent_when_every_claim_is_supported() -> None:
    assert compute_verdict([supported_claim(), supported_claim()]) == "consistent"


def test_verdict_is_unverified_when_a_claim_lacks_evidence() -> None:
    assert compute_verdict([supported_claim(), unverified_claim()]) == "unverified"


def test_verdict_is_unverified_without_claims() -> None:
    assert compute_verdict([]) == "unverified"


# --- bound_claims ------------------------------------------------------------


def test_bound_claims_truncates_to_the_limit_with_a_note() -> None:
    claims_in = [unverified_claim(claim_text=f"claim {n}") for n in range(MAX_CLAIMS + 5)]

    claims, notes = bound_claims(claims_in)

    assert [c.claim_text for c in claims] == [f"claim {n}" for n in range(MAX_CLAIMS)]
    assert len(notes) == 1
    assert str(MAX_CLAIMS + 5) in notes[0]


def test_bound_claims_leaves_a_list_at_the_limit_alone() -> None:
    claims_in = [unverified_claim(claim_text=f"claim {n}") for n in range(MAX_CLAIMS)]

    claims, notes = bound_claims(claims_in)

    assert claims == claims_in
    assert notes == []


def test_bound_claims_caps_every_string_field() -> None:
    claim = contradicted_claim(
        claim_text="c" * 5000,
        explanation="e" * 5000,
        correction="k" * 5000,
        evidence_quotes=["q" * 5000],
    )

    claims, _ = bound_claims([claim])

    assert claims[0].claim_text == "c" * MAX_CLAIM_TEXT_CHARS == "c" * 300
    assert claims[0].explanation == "e" * MAX_EXPLANATION_CHARS == "e" * 500
    assert claims[0].correction == "k" * MAX_CORRECTION_CHARS == "k" * 300
    assert claims[0].evidence_quotes == ["q" * MAX_QUOTE_CHARS] == ["q" * 500]


def test_bound_claims_caps_the_number_of_quotes() -> None:
    claim = supported_claim(evidence_quotes=[f"quote {n}" for n in range(50)])

    claims, _ = bound_claims([claim])

    assert len(claims[0].evidence_quotes) == 5
