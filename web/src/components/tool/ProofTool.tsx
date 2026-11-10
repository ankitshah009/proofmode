"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";

import {
  ACCEPTED_IMAGE_TYPES,
  ApiError,
  MAX_IMAGE_BYTES,
  MAX_TEXT_CHARS,
  fetchBaseline,
  fetchCapabilities,
  fetchSampleImage,
  plural,
  postReview,
  type Baseline,
  type Capabilities,
  type Review,
  type Source,
} from "@/lib/api";
import {
  EXAMPLE_FACTS,
  FALLBACK_BASELINE,
  INVESTIGATING,
  WORDING,
  factsAsSources,
  type EvidenceMode,
} from "@/lib/wording";

import { ClaimCard } from "./ClaimCard";
import { UploadIcon } from "./icons";
import {
  FactsChecked,
  InvestigationTimeline,
  OfficialFactsPanel,
  ResultsSkeleton,
  Tally,
  countByStatus,
} from "./ResultParts";
import { VerdictBanner } from "./VerdictBanner";

interface ProofToolProps {
  /** Read on the server when the backend answered in time; otherwise fetched in the browser. */
  initialBaseline: Baseline | null;
  initialCapabilities: Capabilities | null;
}

/** Everything a check depends on. Passed explicitly so a click never reads stale state. */
interface CheckInput {
  file: File | null;
  text: string;
  mode: EvidenceMode;
  facts: string;
  website: string;
  investigate: boolean;
}

/** What the last finished check was run with, so the results keep their own wording. */
interface Checked {
  review: Review;
  mode: EvidenceMode;
  sources: string;
  investigated: boolean;
  website: string;
  previewUrl: string | null;
  text: string;
}

function prefersReducedMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function scrollTo(node: Element | null, block: ScrollLogicalPosition): void {
  node?.scrollIntoView({ block, behavior: prefersReducedMotion() ? "auto" : "smooth" });
}

function validateImage(file: File): string {
  if (!ACCEPTED_IMAGE_TYPES.includes(file.type)) return "Choose a PNG, JPEG or WebP image.";
  if (file.size > MAX_IMAGE_BYTES) return "That image is larger than 8 MB.";
  return "";
}

function clipboardImage(data: DataTransfer | null): File | null {
  if (!data) return null;
  const files = Array.from(data.files);
  if (files.length === 0) {
    for (const item of Array.from(data.items)) {
      const file = item.kind === "file" ? item.getAsFile() : null;
      if (file) files.push(file);
    }
  }
  return files.find((file) => file.type.startsWith("image/")) ?? null;
}

function hasFiles(event: DragEvent): boolean {
  return Array.from(event.dataTransfer?.types ?? []).includes("Files");
}

/** The facts text to send for the chosen mode, and the mode the check really runs in. */
function resolveEvidence(
  input: CheckInput,
  baseline: Baseline,
): { mode: EvidenceMode; sources: string } {
  const typed = input.facts.trim();
  if (input.mode === "org" && typed) return { mode: "org", sources: typed };
  // An investigation may start with no facts: it gathers its own.
  if (input.mode === "org" && input.investigate) return { mode: "org", sources: "" };
  return { mode: "general", sources: baseline.facts.join("\n") };
}

export function ProofTool({ initialBaseline, initialCapabilities }: ProofToolProps) {
  const ids = useId();
  const [baseline, setBaseline] = useState<Baseline>(initialBaseline ?? FALLBACK_BASELINE);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(initialCapabilities);

  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [showText, setShowText] = useState(false);
  const [mode, setMode] = useState<EvidenceMode>("general");
  const [facts, setFacts] = useState("");
  const [website, setWebsite] = useState("");
  const [investigate, setInvestigate] = useState(false);

  const [busy, setBusy] = useState(false);
  const [exampleLoading, setExampleLoading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [checked, setChecked] = useState<Checked | null>(null);
  const [citedId, setCitedId] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const factsRef = useRef<HTMLTextAreaElement>(null);
  const resultsRef = useRef<HTMLElement>(null);
  const verdictRef = useRef<HTMLDivElement>(null);
  const errorRef = useRef<HTMLDivElement>(null);
  const runToken = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const baselineReady = useRef<Promise<Baseline> | null>(null);
  const liveInput = useRef<CheckInput>({ file, text, mode, facts, website, investigate });
  const livePreview = useRef<string | null>(null);

  useEffect(() => {
    liveInput.current = { file, text, mode, facts, website, investigate };
  });

  // Anything the server render could not read is fetched here instead.
  useEffect(() => {
    let active = true;
    if (!initialBaseline) {
      baselineReady.current = fetchBaseline().then((loaded) => {
        const next = loaded ?? FALLBACK_BASELINE;
        if (active) setBaseline(next);
        return next;
      });
    }
    if (!initialCapabilities) {
      void fetchCapabilities().then((loaded) => {
        if (active && loaded) setCapabilities(loaded);
      });
    }
    return () => {
      active = false;
    };
  }, [initialBaseline, initialCapabilities]);

  useEffect(
    () => () => {
      controller.current?.abort();
      if (livePreview.current) URL.revokeObjectURL(livePreview.current);
    },
    [],
  );

  const canInvestigate = capabilities?.investigate === true;
  const canPasteText = capabilities?.text !== false;

  const showError = useCallback((message: string) => {
    setError(message);
    if (message) requestAnimationFrame(() => scrollTo(errorRef.current, "nearest"));
  }, []);

  /** A newer input replaces a check that is still in flight; the older reply is discarded. */
  const cancelRun = useCallback(() => {
    runToken.current += 1;
    controller.current?.abort();
    controller.current = null;
    setBusy(false);
  }, []);

  const runCheck = useCallback(
    async (overrides: Partial<CheckInput> = {}, preview: string | null = livePreview.current) => {
      cancelRun();
      const token = runToken.current;
      const input: CheckInput = { ...liveInput.current, ...overrides };
      setError("");
      setCitedId(null);

      const messageText = input.file ? "" : input.text;
      if (!input.file && !messageText.trim()) {
        showError("Add a screenshot of the message, or paste its text, first.");
        return;
      }
      if (input.file) {
        const problem = validateImage(input.file);
        if (problem) {
          showError(problem);
          return;
        }
      } else if (messageText.length > MAX_TEXT_CHARS) {
        showError("The message is longer than 10,000 characters. Shorten it, then check again.");
        return;
      }

      setBusy(true);
      setChecked(null);
      requestAnimationFrame(() => scrollTo(resultsRef.current, "start"));

      const loadedBaseline = baselineReady.current ? await baselineReady.current : baseline;
      if (token !== runToken.current) return;

      const useInvestigation = input.investigate && canInvestigate;
      const evidence = resolveEvidence({ ...input, investigate: useInvestigation }, loadedBaseline);
      const fellBack = input.mode === "org" && evidence.mode === "general";
      if (fellBack) setMode("general");
      setStatus(
        (fellBack
          ? "No official facts were entered, so the general scam red flags are used. "
          : "") + (useInvestigation ? INVESTIGATING : WORDING[evidence.mode].checking),
      );

      const abort = new AbortController();
      controller.current = abort;
      try {
        const review = await postReview(
          {
            image: input.file,
            text: messageText,
            sources: evidence.sources,
            officialDomain: input.website,
            investigate: useInvestigation,
          },
          abort.signal,
        );
        if (token !== runToken.current) return;
        setStatus("Check complete.");
        setChecked({
          review,
          mode: evidence.mode,
          sources: evidence.sources,
          investigated: useInvestigation,
          website: useInvestigation ? input.website.trim() : "",
          previewUrl: input.file ? preview : null,
          text: messageText,
        });
      } catch (caught) {
        if (token !== runToken.current) return;
        setStatus("");
        showError(
          caught instanceof ApiError ? caught.message : "Something went wrong. Please try again.",
        );
      } finally {
        if (token === runToken.current) {
          controller.current = null;
          setBusy(false);
        }
      }
    },
    [baseline, canInvestigate, cancelRun, showError],
  );

  // Bring the answer to the reader: focus the verdict banner and scroll it into view.
  useEffect(() => {
    if (!checked) return;
    const banner = verdictRef.current;
    banner?.focus({ preventScroll: true });
    scrollTo(banner, "start");
  }, [checked]);

  /** Choosing, dropping or pasting a screenshot all arrive here, and a valid one is checked at once. */
  const acceptImage = useCallback(
    (next: File, overrides: Partial<CheckInput> = {}) => {
      cancelRun();
      setChecked(null);
      const problem = validateImage(next);
      if (problem) {
        setStatus("");
        showError(problem);
        return;
      }
      if (livePreview.current) URL.revokeObjectURL(livePreview.current);
      const url = URL.createObjectURL(next);
      livePreview.current = url;
      setFile(next);
      void runCheck({ ...overrides, file: next }, url);
    },
    [cancelRun, runCheck, showError],
  );

  const removeImage = useCallback(() => {
    if (livePreview.current) URL.revokeObjectURL(livePreview.current);
    livePreview.current = null;
    setFile(null);
  }, []);

  // A file can be dropped anywhere on the page, and an image can be pasted anywhere.
  useEffect(() => {
    const onDragOver = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      setDragOver(true);
    };
    const onDragLeave = (event: DragEvent) => {
      if (!event.relatedTarget) setDragOver(false);
    };
    const onDrop = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      setDragOver(false);
      const dropped = event.dataTransfer?.files[0];
      if (dropped) acceptImage(dropped);
    };
    // Pasted text still reaches the text boxes as usual; only an image is taken over.
    const onPaste = (event: ClipboardEvent) => {
      const pasted = clipboardImage(event.clipboardData);
      if (!pasted) return;
      event.preventDefault();
      acceptImage(pasted);
    };
    document.addEventListener("dragenter", onDragOver);
    document.addEventListener("dragover", onDragOver);
    document.addEventListener("dragleave", onDragLeave);
    document.addEventListener("drop", onDrop);
    document.addEventListener("paste", onPaste);
    return () => {
      document.removeEventListener("dragenter", onDragOver);
      document.removeEventListener("dragover", onDragOver);
      document.removeEventListener("dragleave", onDragLeave);
      document.removeEventListener("drop", onDrop);
      document.removeEventListener("paste", onPaste);
    };
  }, [acceptImage]);

  const loadExample = useCallback(async () => {
    setError("");
    setFacts(EXAMPLE_FACTS);
    setMode("org");
    setStatus("Loading the fictional example message.");
    setExampleLoading(true);
    try {
      const sample = await fetchSampleImage();
      acceptImage(sample, { facts: EXAMPLE_FACTS, mode: "org" });
    } catch {
      setStatus("");
      showError(
        "The example screenshot could not be loaded. Its official facts are filled in, so choose a screenshot to check.",
      );
    } finally {
      setExampleLoading(false);
    }
  }, [acceptImage, showError]);

  const checkText = useCallback(() => {
    removeImage();
    void runCheck({ file: null }, null);
  }, [removeImage, runCheck]);

  const cite = useCallback((id: string, scroll: boolean) => {
    setCitedId(id);
    if (scroll) scrollTo(document.getElementById(`fact-${id}`), "nearest");
  }, []);

  const review = checked?.review ?? null;
  const checkedMode = checked?.mode ?? "general";
  const wording = WORDING[checkedMode];

  const listedSources: Source[] = useMemo(() => {
    if (!checked) return [];
    if (checked.review.sources.length > 0) {
      // The server labels every fact it was sent as supplied by the user, so the
      // general rules this page sent are relabelled as what they are.
      const rules = new Set(checked.mode === "general" ? baseline.facts : []);
      return checked.review.sources.map((source) =>
        source.origin === "user" && rules.has(source.text)
          ? { ...source, origin: "baseline" as const }
          : source,
      );
    }
    return factsAsSources(checked.sources, checked.mode === "general" ? "baseline" : "user");
  }, [checked, baseline.facts]);

  const knownSourceIds = useMemo(
    () => new Set(listedSources.map((source) => source.id)),
    [listedSources],
  );

  const hasInput = file !== null || text.trim().length > 0;
  const evidenceNow = resolveEvidence(
    { file, text, mode, facts, website, investigate: investigate && canInvestigate },
    baseline,
  );
  const stale =
    checked !== null &&
    !busy &&
    (evidenceNow.sources !== checked.sources ||
      (investigate && canInvestigate) !== checked.investigated ||
      (checked.investigated && website.trim() !== checked.website));

  const contradicted = review ? countByStatus(review.claims).contradicted : 0;
  const summary = !review
    ? ""
    : review.claims.length === 0
      ? "No claims were found to check."
      : `Checked ${plural(review.claims.length, "claim")} against ${
          review.sources.length > 0
            ? plural(listedSources.length, "numbered source")
            : plural(listedSources.length, wording.unit)
        }.`;

  return (
    <div>
      <div className="grid gap-8 md:grid-cols-[minmax(0,6fr)_minmax(0,5fr)] md:gap-10">
        {/* The message */}
        <section aria-labelledby={`${ids}-message`} className="min-w-0">
          <h2 id={`${ids}-message`} className="mono-label">
            1. The message
          </h2>
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPTED_IMAGE_TYPES.join(",")}
            tabIndex={-1}
            aria-hidden="true"
            data-testid="image-input"
            className="sr-only"
            onChange={(event) => {
              const chosen = event.target.files?.[0];
              event.target.value = "";
              if (chosen) acceptImage(chosen);
            }}
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            aria-describedby={`${ids}-drop-help ${ids}-handling`}
            className={`mt-2.5 flex min-h-44 w-full cursor-pointer flex-col items-center justify-center gap-1.5 rounded-xl border-2 border-dashed px-5 py-6 text-center transition-colors md:min-h-60 ${
              dragOver
                ? "border-primary bg-primary/10"
                : "border-input bg-card hover:border-primary hover:bg-raised"
            }`}
          >
            <span
              aria-hidden="true"
              className="mb-1 flex size-11 items-center justify-center rounded-full border border-primary/70 text-accent-text"
            >
              <UploadIcon />
            </span>
            <span className="font-serif text-2xl leading-tight md:text-[28px]">
              {dragOver
                ? "Drop to check"
                : file
                  ? "Choose a different screenshot"
                  : "Drop, paste or choose a screenshot"}
            </span>
            <span id={`${ids}-drop-help`} className="hint">
              {file
                ? `Selected: ${file.name}`
                : "Email, SMS or chat. PNG, JPEG or WebP, up to 8 MB. The check starts straight away."}
            </span>
          </button>

          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void loadExample()}
              disabled={exampleLoading}
            >
              Try the example
            </button>
            {canPasteText ? (
              <button
                type="button"
                aria-expanded={showText}
                aria-controls={`${ids}-text-panel`}
                onClick={() => setShowText((open) => !open)}
                className="inline-flex min-h-11 cursor-pointer items-center rounded-md px-1 text-[15px] underline decoration-primary underline-offset-4 hover:text-accent-text"
              >
                or paste the message text
              </button>
            ) : null}
          </div>
          <p className="hint mt-2">
            The example runs a full check in one click. Its organisation, Tidewater Cloud, and its
            message are fictional.
          </p>

          {canPasteText ? (
            <div id={`${ids}-text-panel`} hidden={!showText} className="mt-4">
              <label htmlFor={`${ids}-text`} className="block text-[15px] font-semibold">
                The message text
              </label>
              <textarea
                id={`${ids}-text`}
                rows={5}
                value={text}
                spellCheck={false}
                aria-describedby={`${ids}-text-hint`}
                onChange={(event) => setText(event.target.value)}
                className="field mt-2 resize-y font-mono text-[13px]"
              />
              <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2">
                <button
                  type="button"
                  className="btn"
                  onClick={checkText}
                  disabled={busy || text.trim().length === 0}
                >
                  Check this text
                </button>
                <p id={`${ids}-text-hint`} className="hint min-w-0 flex-1 basis-52">
                  Include the sender line. Up to 10,000 characters. Checking the text replaces any
                  screenshot.
                </p>
              </div>
            </div>
          ) : null}

          <p id={`${ids}-handling`} className="hint mt-3">
            Sent to the model through OpenRouter. Not stored by this app.{" "}
            <a href="#handling" className="text-link">
              How it is handled
            </a>
          </p>
        </section>

        {/* The evidence */}
        <section aria-labelledby={`${ids}-evidence`} className="min-w-0">
          <h2 id={`${ids}-evidence`} className="mono-label">
            2. Checked against
          </h2>
          <fieldset className="mt-2.5 grid min-w-0 gap-2 sm:grid-cols-2">
            <legend className="sr-only">What to check the message against</legend>
            {(
              [
                ["general", baseline.label],
                ["org", "This organisation's official facts"],
              ] as const
            ).map(([value, label]) => (
              <label
                key={value}
                className={`flex min-h-11 min-w-0 cursor-pointer items-center gap-2.5 rounded-lg border px-3.5 py-2.5 text-[15px] font-semibold leading-tight transition-colors has-[:focus-visible]:outline-[3px] has-[:focus-visible]:outline-offset-[3px] has-[:focus-visible]:outline-ring ${
                  mode === value
                    ? "border-primary bg-primary/10 text-foreground"
                    : "border-input bg-card text-muted-foreground hover:border-muted-foreground"
                }`}
              >
                <input
                  type="radio"
                  name={`${ids}-mode`}
                  value={value}
                  checked={mode === value}
                  onChange={() => setMode(value)}
                  className="size-[18px] flex-none accent-primary focus-visible:outline-none"
                />
                <span>{label}</span>
              </label>
            ))}
          </fieldset>

          {mode === "general" ? (
            <div className="mt-3">
              <p className="hint">
                No facts needed. The general check catches common scam patterns only. Adding the
                organisation&apos;s own facts gives a stronger check.
              </p>
              <ol
                aria-label="General scam red-flag rules"
                className="mt-2 grid list-decimal gap-1 pl-6 text-[13.5px] leading-snug text-muted-foreground marker:font-mono marker:text-xs"
              >
                {baseline.facts.map((fact) => (
                  <li key={fact}>{fact}</li>
                ))}
              </ol>
              {baseline.links.length > 0 ? (
                <p className="mt-1 flex flex-wrap items-center gap-x-3.5 text-sm text-muted-foreground">
                  <span>{baseline.links.length === 1 ? "Source:" : "Sources:"}</span>
                  {baseline.links.map((link) => (
                    <a
                      key={link.url}
                      href={link.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-link inline-flex min-h-11 items-center"
                    >
                      {link.name}
                      <span className="sr-only"> (opens in a new tab)</span>
                    </a>
                  ))}
                </p>
              ) : null}
            </div>
          ) : (
            <div className="mt-3">
              <label htmlFor={`${ids}-facts`} className="block text-[15px] font-semibold">
                The organisation&apos;s official facts, one per line
              </label>
              <textarea
                ref={factsRef}
                id={`${ids}-facts`}
                rows={6}
                value={facts}
                spellCheck={false}
                aria-describedby={`${ids}-facts-hint`}
                onChange={(event) => setFacts(event.target.value)}
                className="field mt-2 min-h-36 resize-y"
              />
              <p id={`${ids}-facts-hint`} className="hint mt-1.5">
                Take these from the organisation&apos;s own website or documents, never from the
                message itself. A claim that no fact covers is marked as unverifiable, not as false.
                {canInvestigate
                  ? " Leave the box empty to use the general scam red flags, or to let an investigation gather the facts."
                  : " Leave the box empty to use the general scam red flags."}
              </p>
            </div>
          )}

          {canInvestigate ? (
            <div className="mt-3 border-t border-border pt-3">
              <label htmlFor={`${ids}-website`} className="block text-[15px] font-semibold">
                Official website <span className="font-normal text-muted-foreground">(optional)</span>
              </label>
              <div className="mt-2 flex flex-wrap items-center gap-x-4">
              <input
                id={`${ids}-website`}
                type="text"
                inputMode="url"
                autoComplete="off"
                autoCapitalize="none"
                spellCheck={false}
                placeholder="example.org"
                value={website}
                aria-describedby={`${ids}-investigate-hint`}
                onChange={(event) => setWebsite(event.target.value)}
                className="field min-h-11 min-w-0 flex-1 basis-48"
              />
              <label className="flex min-h-11 cursor-pointer items-center gap-2.5 text-[15px] font-semibold">
                <input
                  type="checkbox"
                  checked={investigate}
                  onChange={(event) => setInvestigate(event.target.checked)}
                  className="size-[18px] flex-none accent-primary"
                />
                <span>Let the model investigate</span>
              </label>
              </div>
              <p id={`${ids}-investigate-hint`} className="hint mt-1.5">
                The model reads the organisation&apos;s real website before it answers. A domain
                named in the message is never read.
              </p>
            </div>
          ) : null}

          {hasInput || stale ? (
            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => void runCheck()}
                disabled={busy || !hasInput}
              >
                Check again
              </button>
              {stale ? (
                <p className="hint min-w-0 flex-1 basis-52">
                  The evidence settings have changed since this check. Check again to update the
                  verdict.
                </p>
              ) : null}
            </div>
          ) : null}
        </section>
      </div>

      <p aria-live="polite" className="mt-5 text-[15px] text-muted-foreground empty:hidden">
        {status}
      </p>
      {error ? (
        <div
          ref={errorRef}
          role="alert"
          className="mt-3 scroll-mt-4 rounded-lg border border-primary bg-primary/10 px-4 py-3 text-[15px]"
        >
          <span className="font-semibold text-accent-text">Could not check. </span>
          {error}
        </div>
      ) : null}

      {/* The verdict */}
      <section
        ref={resultsRef}
        aria-labelledby={`${ids}-results`}
        aria-busy={busy}
        hidden={!busy && !checked}
        className="mt-8 scroll-mt-4 border-t border-border pt-6"
      >
        <h2 id={`${ids}-results`} className="mono-label">
          3. The verdict
        </h2>
        {busy ? (
          <div className="mt-3">
            <ResultsSkeleton />
          </div>
        ) : null}

        {checked && review ? (
          <div className="mt-3">
            <VerdictBanner
              ref={verdictRef}
              verdict={review.verdict}
              mode={checked.mode}
              contradicted={contradicted}
            />
            <p className="mt-3 text-[15px] text-muted-foreground">{summary}</p>

            <div className="mt-6 grid gap-8 md:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] md:gap-10">
              <aside className="grid min-w-0 content-start gap-6 md:sticky md:top-4 md:max-h-[calc(100vh-2rem)] md:self-start md:overflow-y-auto">
                <figure className="overflow-hidden rounded-lg border border-border bg-card">
                  <figcaption className="mono-label border-b border-border px-4 py-2.5">
                    The message
                  </figcaption>
                  {checked.previewUrl ? (
                    // A local blob preview of the person's own file; the image optimiser does not apply.
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={checked.previewUrl}
                      alt="The message screenshot as uploaded"
                      className="max-h-[420px] w-full object-contain"
                    />
                  ) : (
                    <pre className="max-h-[420px] overflow-auto whitespace-pre-wrap p-4 font-mono text-[13px] leading-relaxed">
                      {checked.text}
                    </pre>
                  )}
                </figure>
                <OfficialFactsPanel claims={review.claims} mode={checked.mode} />
              </aside>

              <div className="grid min-w-0 content-start gap-6">
                {review.claims.length > 0 ? <Tally claims={review.claims} mode={checked.mode} /> : null}

                <InvestigationTimeline steps={review.steps} />

                <ol aria-label="Claims in the message" className="grid gap-4">
                  {review.claims.length === 0 ? (
                    <li className="rounded-lg border border-border bg-card p-5">
                      No checkable claims were found in the message.
                    </li>
                  ) : null}
                  {review.claims.map((claim, index) => (
                    <ClaimCard
                      key={`${index}-${claim.claim_text}`}
                      claim={claim}
                      index={index}
                      total={review.claims.length}
                      mode={checked.mode}
                      knownSourceIds={knownSourceIds}
                      onCite={cite}
                    />
                  ))}
                </ol>

                {listedSources.length > 0 ? (
                  <FactsChecked
                    title={review.sources.length > 0 ? "Facts as checked" : wording.listTitle}
                    sources={listedSources}
                    citedId={citedId}
                  />
                ) : null}

                {review.notes.length > 0 ? (
                  <section aria-labelledby={`${ids}-notes`}>
                    <h3 id={`${ids}-notes`} className="mono-label">
                      Notes
                    </h3>
                    <ul className="mt-2 grid list-disc gap-1 pl-5 text-sm text-muted-foreground">
                      {review.notes.map((note, index) => (
                        <li key={`${index}-${note}`}>{note}</li>
                      ))}
                    </ul>
                  </section>
                ) : null}

                <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                  <button type="button" className="btn" onClick={() => void runCheck()} disabled={busy}>
                    Check again
                  </button>
                  {checked.mode === "general" ? (
                    <button
                      type="button"
                      className="btn"
                      onClick={() => {
                        setMode("org");
                        requestAnimationFrame(() => {
                          factsRef.current?.focus({ preventScroll: true });
                          scrollTo(factsRef.current, "center");
                        });
                      }}
                    >
                      Add this organisation&apos;s facts
                    </button>
                  ) : null}
                  <p className="hint min-w-0 flex-1 basis-52">{wording.again}</p>
                </div>
                {review.model ? (
                  <p className="font-mono text-[13px] text-muted-foreground">
                    Checked by {review.model} through OpenRouter
                  </p>
                ) : null}
              </div>
            </div>
          </div>
        ) : null}
      </section>
    </div>
  );
}
