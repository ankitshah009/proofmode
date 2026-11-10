import type { Ref } from "react";

import type { Verdict } from "@/lib/api";
import { WORDING, verdictDetail, type EvidenceMode, type VerdictTone } from "@/lib/wording";

import { CheckIcon, CrossIcon, QuestionIcon } from "./icons";

interface VerdictBannerProps {
  verdict: Verdict;
  mode: EvidenceMode;
  /** Used only for the count in the sentence under the title. */
  contradicted: number;
  ref?: Ref<HTMLDivElement>;
}

const TONE_CLASSES: Record<VerdictTone, string> = {
  danger: "border-primary bg-primary/10",
  ok: "border-success/70 bg-success/10",
  open: "border-dashed border-muted-foreground bg-card",
};

const TITLE_CLASSES: Record<VerdictTone, string> = {
  danger: "text-accent-text",
  ok: "text-success",
  open: "text-foreground",
};

function ToneIcon({ tone }: { tone: VerdictTone }) {
  const className = "mt-1 size-7 md:mt-2 md:size-9";
  if (tone === "danger") return <CrossIcon className={className} />;
  if (tone === "ok") return <CheckIcon className={className} />;
  return <QuestionIcon className={className} />;
}

/**
 * The overall answer. Its tone and title come from the `verdict` field alone,
 * which the backend computes in code; nothing here is inferred from the claims.
 */
export function VerdictBanner({ verdict, mode, contradicted, ref }: VerdictBannerProps) {
  const wording = WORDING[mode].verdicts[verdict];
  return (
    <div
      ref={ref}
      role="status"
      tabIndex={-1}
      data-verdict={verdict}
      className={`reveal scroll-mt-4 rounded-xl border-2 p-5 focus:outline-none md:p-8 ${TONE_CLASSES[wording.tone]}`}
    >
      <p className="mono-label">Verdict</p>
      <p
        className={`mt-3 flex items-start gap-3 font-serif text-4xl leading-[1.05] tracking-tight md:text-6xl ${TITLE_CLASSES[wording.tone]}`}
      >
        <ToneIcon tone={wording.tone} />
        <span>{wording.title}</span>
      </p>
      <p className="mt-4 max-w-[70ch] text-base text-foreground md:text-lg">
        {verdictDetail(verdict, mode, contradicted)}
      </p>
    </div>
  );
}
