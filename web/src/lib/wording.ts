import type { Baseline, ClaimStatus, Source, SourceOrigin, Verdict } from "@/lib/api";

/** What a check is judged against. */
export type EvidenceMode = "general" | "org";

export type VerdictTone = "danger" | "ok" | "open";

export interface VerdictWording {
  tone: VerdictTone;
  title: string;
  detail: string;
}

export interface ModeWording {
  labels: Record<ClaimStatus, string>;
  basis: string;
  unit: string;
  listTitle: string;
  afterTitle: string;
  says: string;
  quote: readonly [string, string];
  open: string;
  nextStep: string;
  again: string;
  checking: string;
  verdicts: Record<Verdict, VerdictWording>;
}

// The banner is chosen by the verdict field alone, never inferred from the claims.
export const WORDING: Record<EvidenceMode, ModeWording> = {
  org: {
    labels: {
      supported: "Matches the official facts",
      contradicted: "Contradicts the official facts",
      insufficient_evidence: "Cannot be verified",
    },
    basis: "the official facts",
    unit: "official fact",
    listTitle: "Official facts as checked",
    afterTitle: "What the official facts say",
    says: "The official facts say: ",
    quote: ["Official fact", "Official facts"],
    open: "Cannot be verified from the facts supplied",
    nextStep:
      "No official fact covers this claim. Add one and check again, or confirm it with the organisation directly.",
    again: "Edit the facts above, then check again.",
    checking: "Checking the message against the official facts. This can take a little while.",
    verdicts: {
      contradicts_facts: { tone: "danger", title: "Do not trust this message", detail: "" },
      consistent: {
        tone: "ok",
        title: "Consistent with the official facts",
        detail:
          "This is not proof that the message is genuine. A fraudulent message can repeat true facts, so confirm the sender through the organisation's official channel before you act.",
      },
      unverified: {
        tone: "open",
        title: "Not enough facts to judge",
        detail:
          "The facts supplied do not settle the claims in this message. Add more official facts and check again.",
      },
    },
  },
  general: {
    labels: {
      supported: "In line with the general rules",
      contradicted: "Scam red flag",
      insufficient_evidence: "Not covered by the general rules",
    },
    basis: "the general scam red-flag rules",
    unit: "general rule",
    listTitle: "General rules as checked",
    afterTitle: "What the general rules say",
    says: "The general rules say: ",
    quote: ["General rule", "General rules"],
    open: "Not covered by the general rules",
    nextStep:
      "No general rule covers this claim. Add the organisation's official facts for a stronger check, or confirm it with the organisation directly.",
    again:
      "The general check catches common scam patterns only. The organisation's own facts give a stronger check.",
    checking:
      "Checking the message against the general scam red flags. This can take a little while.",
    verdicts: {
      contradicts_facts: { tone: "danger", title: "Do not trust this message", detail: "" },
      consistent: {
        tone: "ok",
        title: "No common scam pattern found",
        detail:
          "This is not proof that the message is genuine. The general check catches common scam patterns only. Add the organisation's own facts for a stronger check, and confirm the sender through its official channel before you act.",
      },
      unverified: {
        tone: "open",
        title: "The general rules do not settle this",
        detail:
          "None of the general scam red flags decides the claims in this message. That does not make it genuine. Add the organisation's own facts for a stronger check.",
      },
    },
  },
};

export const INVESTIGATING =
  "Investigating: the model is reading the official website and checking the message. This can take a minute or two.";

export const ORIGIN_LABELS: Record<SourceOrigin, string> = {
  user: "Supplied by you",
  baseline: "General rule",
  fetched: "Read from the official website",
  lookup: "Domain registration record",
};

/** The fictional example organisation. Its facts are invented for this project. */
export const EXAMPLE_FACTS = [
  "Tidewater Cloud credits do not expire.",
  "Tidewater Cloud never charges a reactivation fee.",
  "Payments are accepted by card or bank transfer only; gift cards are never accepted.",
  "Official messages are sent only from tidewater.example and link only to tidewater.example.",
  "Support is available 24 hours a day, 7 days a week.",
].join("\n");

// Used only if /baseline.json cannot be loaded: the one rule every build is known to carry.
export const FALLBACK_BASELINE: Baseline = {
  label: "General scam red flags",
  facts: [
    "No real business or government agency will ever tell you to buy a gift card to pay them.",
  ],
  links: [
    {
      name: "FTC Consumer Advice: Gift Card Scams",
      url: "https://consumer.ftc.gov/articles/gift-card-scams",
    },
  ],
};

// Mirrors parse_sources on the server: Python splitlines boundaries, then a leading list marker.
const LINE_BREAKS = /\r\n|[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]/;
const BULLET = /^(?:[-*\u2022]+|\d+[.)])(?:\s+|$)/;

export function parseFacts(text: string): string[] {
  const facts: string[] = [];
  for (const line of text.split(LINE_BREAKS)) {
    const fact = line.trim().replace(BULLET, "").trim();
    if (fact) facts.push(fact);
  }
  return facts;
}

/** Number the facts that were sent the same way the server does: S1, S2 and so on. */
export function factsAsSources(text: string, origin: SourceOrigin): Source[] {
  return parseFacts(text).map((fact, index) => ({
    id: `S${index + 1}`,
    text: fact,
    url: null,
    origin,
  }));
}

/** Detail line under the banner title. The count is display only; the tone comes from the verdict. */
export function verdictDetail(verdict: Verdict, mode: EvidenceMode, contradicted: number): string {
  const wording = WORDING[mode];
  if (verdict !== "contradicts_facts") return wording.verdicts[verdict].detail;
  if (contradicted <= 0) return `This message contradicts ${wording.basis}.`;
  const verb = contradicted === 1 ? "contradicts" : "contradict";
  return `${contradicted} ${contradicted === 1 ? "claim" : "claims"} in this message ${verb} ${wording.basis}.`;
}
