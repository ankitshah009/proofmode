import { isHttpsUrl, type Claim, type ClaimStatus, type Source, type Step } from "@/lib/api";
import { ORIGIN_LABELS, WORDING, type EvidenceMode } from "@/lib/wording";

import { CheckIcon, CrossIcon } from "./icons";

const STATUS_ORDER: readonly ClaimStatus[] = [
  "supported",
  "contradicted",
  "insufficient_evidence",
];

export function countByStatus(claims: Claim[]): Record<ClaimStatus, number> {
  const counts: Record<ClaimStatus, number> = {
    supported: 0,
    contradicted: 0,
    insufficient_evidence: 0,
  };
  for (const claim of claims) counts[claim.status] += 1;
  return counts;
}

interface TallyProps {
  claims: Claim[];
  mode: EvidenceMode;
}

/** Three counts, each with its text label, so no status is told by colour alone. */
export function Tally({ claims, mode }: TallyProps) {
  const counts = countByStatus(claims);
  const labels = WORDING[mode].labels;
  return (
    <dl className="grid grid-cols-3 rounded-lg border border-border bg-card">
      {STATUS_ORDER.map((status, index) => {
        const tone =
          counts[status] === 0
            ? "text-muted-foreground"
            : status === "contradicted"
              ? "text-accent-text"
              : "text-foreground";
        return (
          <div
            key={status}
            className={`flex min-w-0 flex-col-reverse justify-end gap-1 p-3 md:p-4 ${index > 0 ? "border-l border-border" : ""}`}
          >
            <dt className="text-[13px] font-semibold leading-tight text-muted-foreground">
              {labels[status]}
            </dt>
            <dd className={`font-serif text-5xl leading-none tabular-nums md:text-6xl ${tone}`}>
              {counts[status]}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

interface OfficialFactsPanelProps {
  claims: Claim[];
  mode: EvidenceMode;
}

/** Each claim beside what the facts say, with struck-out text for what is contradicted. */
export function OfficialFactsPanel({ claims, mode }: OfficialFactsPanelProps) {
  const wording = WORDING[mode];
  return (
    <article
      aria-labelledby="after-title"
      className="min-w-0 rounded-lg border border-border border-t-[3px] border-t-primary bg-card p-5"
    >
      <h3 id="after-title" className="font-serif text-2xl leading-tight">
        {wording.afterTitle}
      </h3>
      <p className="hint mt-1">
        Each claim in the message, with the correct position beside any claim that contradicts it.
      </p>
      <ol className="mt-3">
        {claims.length === 0 ? <li className="py-3 text-[15px]">No claims to compare.</li> : null}
        {claims.map((claim, index) => (
          <li key={`${index}-${claim.claim_text}`} className="reveal border-t border-border py-3">
            {claim.status === "contradicted" ? (
              <>
                <del className="block text-[15px] text-muted-foreground line-through decoration-primary decoration-2">
                  <span className="sr-only">The message says: </span>
                  {claim.claim_text}
                </del>
                {claim.correction ? (
                  <ins className="mt-1 block font-serif text-xl leading-snug no-underline">
                    <span className="sr-only">{wording.says}</span>
                    {claim.correction}
                  </ins>
                ) : null}
                <span className="mt-1.5 inline-flex items-center gap-1.5 text-[13px] font-semibold text-accent-text">
                  <CrossIcon />
                  {wording.labels.contradicted}
                </span>
              </>
            ) : (
              <>
                <span className="block font-serif text-xl leading-snug">{claim.claim_text}</span>
                {claim.status === "supported" ? (
                  <span className="mt-1.5 inline-flex items-center gap-1.5 text-[13px] font-semibold text-success">
                    <CheckIcon />
                    {wording.labels.supported}
                  </span>
                ) : (
                  <span className="mt-1.5 inline-flex items-center rounded border border-dashed border-muted-foreground px-2 py-0.5 text-[13px] font-semibold text-muted-foreground">
                    {wording.open}
                  </span>
                )}
              </>
            )}
          </li>
        ))}
      </ol>
    </article>
  );
}

interface FactsCheckedProps {
  title: string;
  sources: Source[];
  citedId: string | null;
}

/** The numbered lines the claims could cite. A cited row is marked in text as well as colour. */
export function FactsChecked({ title, sources, citedId }: FactsCheckedProps) {
  return (
    <section aria-labelledby="fact-list-title" className="rounded-lg border border-border p-5">
      <h3 id="fact-list-title" className="font-serif text-2xl leading-tight">
        {title}
      </h3>
      <ol aria-labelledby="fact-list-title" className="mt-3 grid gap-1">
        {sources.map((source) => {
          const cited = source.id === citedId;
          const linkable = source.origin === "fetched" && source.url !== null && isHttpsUrl(source.url);
          return (
            <li
              key={source.id}
              id={`fact-${source.id}`}
              data-cited={cited ? "true" : undefined}
              className={`grid scroll-mt-24 grid-cols-[3.4em_minmax(0,1fr)] gap-2 rounded-md border px-2.5 py-2 text-[15px] transition-colors ${
                cited
                  ? "border-primary bg-primary/10 text-foreground"
                  : "border-transparent text-muted-foreground"
              }`}
            >
              <span
                className={`font-mono text-[13px] leading-[1.8] ${cited ? "font-semibold text-accent-text" : ""}`}
              >
                {source.id}
                {cited ? <span className="block text-[11px] uppercase tracking-wider">cited</span> : null}
              </span>
              <span className="min-w-0">
                <span className="block text-foreground">{source.text}</span>
                <span className="mt-0.5 flex flex-wrap items-center gap-x-3 text-[13px] text-muted-foreground">
                  <span>{ORIGIN_LABELS[source.origin]}</span>
                  {linkable && source.url ? (
                    <a
                      href={source.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-link inline-flex min-h-11 items-center break-all"
                    >
                      {source.url}
                      <span className="sr-only"> (opens in a new tab)</span>
                    </a>
                  ) : null}
                </span>
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

const TOOL_LABELS: Record<string, string> = {
  report_message: "Read the message",
  fetch_official_page: "Read a page on the official website",
  lookup_domain: "Looked up a domain registration",
  finish: "Finished the investigation",
};

interface InvestigationTimelineProps {
  steps: Step[];
}

/** What the model did during an investigation, in order, including refusals. */
export function InvestigationTimeline({ steps }: InvestigationTimelineProps) {
  if (steps.length === 0) return null;
  return (
    <section aria-labelledby="investigation-title">
      <h3 id="investigation-title" className="font-serif text-2xl leading-tight">
        Investigation
      </h3>
      <p className="hint mt-1">
        Every tool call the model made, in order. Code decides which sites may be read.
      </p>
      <ol className="ml-1.5 mt-4 border-l border-border pl-6">
        {steps.map((step, index) => (
          <li key={`${index}-${step.tool}`} data-ok={step.ok} className="reveal relative pb-5 last:pb-0">
            <span
              aria-hidden="true"
              className={`absolute -left-[30px] top-1.5 size-2.5 rounded-full ${step.ok ? "bg-success" : "bg-primary"}`}
            />
            <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="font-semibold">{TOOL_LABELS[step.tool] ?? step.tool}</span>
              <span
                className={`inline-flex items-center gap-1 text-[13px] font-semibold ${step.ok ? "text-success" : "text-accent-text"}`}
              >
                {step.ok ? <CheckIcon /> : <CrossIcon />}
                {step.ok ? "Done" : "Refused or failed"}
              </span>
            </p>
            {step.argument ? (
              <p className="mt-1 break-all font-mono text-[13px] text-muted-foreground">
                {step.argument}
              </p>
            ) : null}
            {step.outcome ? <p className="mt-1 text-[15px] text-muted-foreground">{step.outcome}</p> : null}
          </li>
        ))}
      </ol>
    </section>
  );
}

/** Placeholder shown while a check is running. Hidden from assistive technology; the status line speaks instead. */
export function ResultsSkeleton() {
  return (
    <div aria-hidden="true" data-testid="results-skeleton" className="grid gap-4">
      <div className="grid gap-3 rounded-xl border-2 border-border p-5 md:p-8">
        <span className="skeleton-bar w-24" />
        <span className="skeleton-bar h-10 w-3/4" />
        <span className="skeleton-bar w-1/2" />
      </div>
      <div className="grid gap-4 md:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <div className="grid h-48 content-start gap-3 rounded-lg border border-border bg-card p-5">
          <span className="skeleton-bar w-1/3" />
          <span className="skeleton-bar" />
          <span className="skeleton-bar w-4/5" />
        </div>
        <div className="grid gap-4">
          {[0, 1, 2].map((item) => (
            <div key={item} className="grid gap-3 rounded-lg border border-border bg-card p-5">
              <span className="skeleton-bar w-1/3" />
              <span className="skeleton-bar" />
              <span className="skeleton-bar w-4/5" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
