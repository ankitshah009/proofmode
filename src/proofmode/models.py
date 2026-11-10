"""Shared data contract. Every module imports these types; change them only deliberately."""

from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["supported", "contradicted", "insufficient_evidence"]
Verdict = Literal["contradicts_facts", "consistent", "unverified"]
# Where a source came from: pasted by the user, shipped with the app, read from a
# web page by the investigation tools, or produced by a domain registration lookup.
Origin = Literal["user", "baseline", "fetched", "lookup"]


class Source(BaseModel):
    """One numbered fact, e.g. id='S1'.

    origin says where it came from; url is set for facts read from a web page.
    """

    id: str
    text: str
    url: str | None = None
    origin: Origin = "user"


class Step(BaseModel):
    """One tool call made during an investigation, and how it ended."""

    tool: str
    argument: str = ""
    outcome: str = ""
    ok: bool = True


class Claim(BaseModel):
    """One claim extracted from the suspicious message, judged against the facts."""

    claim_text: str
    status: Status
    source_ids: list[str] = Field(default_factory=list)
    evidence_quotes: list[str] = Field(default_factory=list)
    explanation: str = ""
    # One short sentence stating what the official facts actually say.
    # Empty unless status is "contradicted".
    correction: str = ""


class Review(BaseModel):
    """Result of one fraud check run.

    verdict is computed locally from the validated claims and is never taken from
    the model: "contradicts_facts" when any claim is contradicted, "consistent"
    when there is at least one claim and every claim is supported, otherwise
    "unverified".
    """

    model: str
    claims: list[Claim]
    notes: list[str] = Field(default_factory=list)  # validation downgrades, warnings
    verdict: Verdict = "unverified"
    # Filled by investigation mode: every numbered source the claims could cite,
    # and the tool calls the model made, in order.
    sources: list[Source] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
