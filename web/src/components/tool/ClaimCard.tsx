import type { Claim, ClaimStatus } from "@/lib/api";
import { WORDING, type EvidenceMode } from "@/lib/wording";

import { CheckIcon, CrossIcon, QuestionIcon } from "./icons";

interface ClaimCardProps {
  claim: Claim;
  index: number;
  total: number;
  mode: EvidenceMode;
  /** Ids that exist in the "Facts as checked" list; only these become buttons. */
  knownSourceIds: ReadonlySet<string>;
  onCite: (id: string, scroll: boolean) => void;
}

const BADGE_CLASSES: Record<ClaimStatus, string> = {
  supported: "border-success/70 text-success",
  contradicted: "border-primary bg-primary text-primary-foreground",
  insufficient_evidence: "border-dashed border-muted-foreground text-muted-foreground",
};

function StatusIcon({ status }: { status: ClaimStatus }) {
  if (status === "supported") return <CheckIcon />;
  if (status === "contradicted") return <CrossIcon />;
  return <QuestionIcon />;
}

interface SourceRefProps {
  id: string;
  known: boolean;
  onCite: (id: string, scroll: boolean) => void;
}

function SourceRef({ id, known, onCite }: SourceRefProps) {
  if (!known) return <span className="font-mono text-[13px]">{id}</span>;
  return (
    <button
      type="button"
      aria-label={`${id}, show this line in the list that was checked`}
      aria-describedby={`fact-${id}`}
      onFocus={() => onCite(id, false)}
      onMouseEnter={() => onCite(id, false)}
      onClick={() => onCite(id, true)}
      className="inline-flex min-h-11 min-w-11 cursor-pointer items-center justify-center rounded-md px-2.5 font-mono text-[13px] font-semibold text-accent-text underline underline-offset-4 hover:bg-primary/10"
    >
      {id}
    </button>
  );
}

interface SourceLineProps {
  label: string;
  ids: string[];
  knownSourceIds: ReadonlySet<string>;
  onCite: (id: string, scroll: boolean) => void;
}

function SourceLine({ label, ids, knownSourceIds, onCite }: SourceLineProps) {
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-muted-foreground">
      <span>{label}</span>
      {ids.map((id) => (
        <SourceRef key={id} id={id} known={knownSourceIds.has(id)} onCite={onCite} />
      ))}
    </span>
  );
}

/** Pair each quote with its source id when the two lists line up. */
function quoteSourceId(sourceIds: string[], quoteCount: number, quoteIndex: number): string {
  if (sourceIds.length === quoteCount) return sourceIds[quoteIndex] ?? "";
  if (sourceIds.length === 1) return sourceIds[0] ?? "";
  return "";
}

/**
 * One claim from the message. Every string here came from the model or the
 * backend, so each is rendered as a plain text node and never as markup.
 */
export function ClaimCard({ claim, index, total, mode, knownSourceIds, onCite }: ClaimCardProps) {
  const wording = WORDING[mode];
  const quotes = claim.evidence_quotes;
  const ids = claim.source_ids;
  const looseSources = ids.length > 0 && (quotes.length === 0 || (ids.length > 1 && ids.length !== quotes.length));

  return (
    <li
      data-status={claim.status}
      className="reveal min-w-0 rounded-lg border border-border bg-card p-5"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span
          className={`inline-flex items-center gap-1.5 rounded border px-2.5 py-1 text-[13px] font-semibold leading-tight ${BADGE_CLASSES[claim.status]}`}
        >
          <StatusIcon status={claim.status} />
          <span>{wording.labels[claim.status]}</span>
        </span>
        <span className="mono-label">
          Claim {index + 1} of {total}
        </span>
      </div>

      <h3
        className={`mt-3 font-serif text-[22px] leading-snug ${
          claim.status === "contradicted"
            ? "line-through decoration-primary decoration-2"
            : ""
        }`}
      >
        {claim.claim_text}
      </h3>

      {claim.explanation ? (
        <p className="mt-2 text-[15px] text-muted-foreground">{claim.explanation}</p>
      ) : null}

      {quotes.length > 0 ? (
        <>
          <p className="mono-label mt-4">{wording.quote[quotes.length === 1 ? 0 : 1]}</p>
          {quotes.map((quote, quoteIndex) => {
            const id = quoteSourceId(ids, quotes.length, quoteIndex);
            return (
              <blockquote
                key={`${quoteIndex}-${quote}`}
                className="mt-2 border-l-2 border-primary/70 pl-4 text-[15px]"
              >
                <p>{quote}</p>
                {id ? (
                  <footer className="mt-0.5">
                    <SourceLine label="Source" ids={[id]} knownSourceIds={knownSourceIds} onCite={onCite} />
                  </footer>
                ) : null}
              </blockquote>
            );
          })}
        </>
      ) : null}

      {looseSources ? (
        <p className="mt-2">
          <SourceLine label="Sources" ids={ids} knownSourceIds={knownSourceIds} onCite={onCite} />
        </p>
      ) : null}

      {claim.status === "contradicted" && claim.correction ? (
        <>
          <p className="mono-label mt-4">{wording.afterTitle}</p>
          <p className="mt-1 font-serif text-xl leading-snug">{claim.correction}</p>
        </>
      ) : null}

      {claim.status === "insufficient_evidence" ? (
        <p className="mt-3 text-[15px] text-muted-foreground">{wording.nextStep}</p>
      ) : null}
    </li>
  );
}
