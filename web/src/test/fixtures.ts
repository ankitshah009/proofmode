import type { Claim, Review } from "@/lib/api";

export function claim(overrides: Partial<Claim> = {}): Claim {
  return {
    claim_text: "Your API credits expire in 24 hours.",
    status: "contradicted",
    source_ids: ["S1"],
    evidence_quotes: ["Tidewater Cloud credits do not expire."],
    explanation: "The message sets an expiry deadline, but S1 says credits do not expire.",
    correction: "Tidewater Cloud credits do not expire.",
    ...overrides,
  };
}

export function review(overrides: Partial<Review> = {}): Review {
  return {
    model: "meta/muse-ember",
    verdict: "contradicts_facts",
    claims: [
      claim(),
      claim({
        claim_text: "Support is available 24/7.",
        status: "supported",
        source_ids: ["S5"],
        evidence_quotes: ["Support is available 24 hours a day, 7 days a week."],
        explanation: "S5 confirms that support is available around the clock.",
        correction: "",
      }),
    ],
    notes: [],
    sources: [],
    steps: [],
    ...overrides,
  };
}

export function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}
