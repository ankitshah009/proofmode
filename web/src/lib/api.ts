/**
 * Typed client for the ProofMode backend. Every call goes to a same-origin
 * path; next.config.ts forwards those paths to the Python service.
 * Replies are untrusted input and are narrowed field by field before use.
 */

export type ClaimStatus = "supported" | "contradicted" | "insufficient_evidence";
export type Verdict = "contradicts_facts" | "consistent" | "unverified";
export type SourceOrigin = "user" | "baseline" | "fetched" | "lookup";

export interface Claim {
  claim_text: string;
  status: ClaimStatus;
  source_ids: string[];
  evidence_quotes: string[];
  explanation: string;
  correction: string;
}

export interface Source {
  id: string;
  text: string;
  url: string | null;
  origin: SourceOrigin;
}

export interface Step {
  tool: string;
  argument: string;
  outcome: string;
  ok: boolean;
}

export interface Review {
  model: string;
  verdict: Verdict;
  claims: Claim[];
  notes: string[];
  sources: Source[];
  steps: Step[];
}

export interface Capabilities {
  investigate: boolean;
  text: boolean;
  model: string;
}

export interface Health {
  ok: boolean;
  mock: boolean;
  model: string;
}

export interface SourceLink {
  name: string;
  url: string;
}

export interface Baseline {
  label: string;
  facts: string[];
  links: SourceLink[];
}

export interface WhyPoint {
  stat: string;
  text: string;
  sourceName: string;
  sourceUrl: string | null;
}

export interface Why {
  headline: string;
  points: WhyPoint[];
}

export interface ReviewRequest {
  image: File | null;
  text: string;
  sources: string;
  officialDomain: string;
  investigate: boolean;
}

export const MAX_IMAGE_BYTES = 8 * 1024 * 1024;
export const MAX_TEXT_CHARS = 10_000;
export const ACCEPTED_IMAGE_TYPES: readonly string[] = [
  "image/png",
  "image/jpeg",
  "image/webp",
];

const STATUSES: readonly ClaimStatus[] = [
  "supported",
  "contradicted",
  "insufficient_evidence",
];
const VERDICTS: readonly Verdict[] = ["contradicts_facts", "consistent", "unverified"];
const ORIGINS: readonly SourceOrigin[] = ["user", "baseline", "fetched", "lookup"];

// Python splitlines boundaries, so a multi-line value is flattened the way the server would split it.
const LINE_BREAKS = /\r\n|[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]/;

/** An error with a message that is safe and useful to show to the person. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

type JsonObject = Record<string, unknown>;

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function asTrimmed(value: unknown): string {
  return asString(value).trim();
}

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

/** True only for a well-formed https URL. Nothing else is ever turned into a link. */
export function isHttpsUrl(value: string): boolean {
  try {
    return new URL(value).protocol === "https:";
  } catch {
    return false;
  }
}

export function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

function parseClaim(value: unknown): Claim | null {
  if (!isObject(value)) return null;
  const status = STATUSES.find((known) => known === value.status);
  return {
    claim_text: asString(value.claim_text),
    // A status this page does not know is shown as unverifiable, never as a pass.
    status: status ?? "insufficient_evidence",
    source_ids: asStringList(value.source_ids)
      .map((id) => id.trim())
      .filter(Boolean),
    evidence_quotes: asStringList(value.evidence_quotes).filter(Boolean),
    explanation: asTrimmed(value.explanation),
    correction: asTrimmed(value.correction),
  };
}

function parseSource(value: unknown): Source | null {
  if (!isObject(value)) return null;
  const id = asTrimmed(value.id);
  if (!id) return null;
  const url = asTrimmed(value.url);
  return {
    id,
    text: asString(value.text),
    url: url || null,
    origin: ORIGINS.find((known) => known === value.origin) ?? "user",
  };
}

function parseStep(value: unknown): Step | null {
  if (!isObject(value)) return null;
  const tool = asTrimmed(value.tool);
  if (!tool) return null;
  return {
    tool,
    argument: asTrimmed(value.argument),
    outcome: asTrimmed(value.outcome),
    ok: value.ok !== false,
  };
}

function parseList<TItem>(
  value: unknown,
  parse: (item: unknown) => TItem | null,
): TItem[] {
  if (!Array.isArray(value)) return [];
  return value.map(parse).filter((item): item is TItem => item !== null);
}

/** Narrow a /api/review reply. Throws when the verdict is missing or unknown. */
export function parseReview(value: unknown): Review {
  if (!isObject(value)) {
    throw new ApiError(502, "The server reply could not be read. Please try again.");
  }
  const verdict = VERDICTS.find((known) => known === value.verdict);
  if (!verdict) {
    throw new ApiError(502, "The server reply had no verdict. Please try again.");
  }
  return {
    model: asTrimmed(value.model),
    verdict,
    claims: parseList(value.claims, parseClaim),
    notes: asStringList(value.notes).filter(Boolean),
    sources: parseList(value.sources, parseSource),
    steps: parseList(value.steps, parseStep),
  };
}

export function parseCapabilities(value: unknown): Capabilities | null {
  if (!isObject(value)) return null;
  return {
    investigate: value.investigate === true,
    text: value.text !== false,
    model: asTrimmed(value.model),
  };
}

export function parseHealth(value: unknown): Health | null {
  if (!isObject(value)) return null;
  return {
    ok: value.ok === true,
    mock: value.mock === true,
    model: asTrimmed(value.model),
  };
}

function parseLink(name: unknown, url: unknown): SourceLink | null {
  const cleanUrl = asTrimmed(url);
  if (!isHttpsUrl(cleanUrl)) return null;
  return { name: asTrimmed(name) || cleanUrl, url: cleanUrl };
}

export function parseBaseline(value: unknown): Baseline | null {
  if (!isObject(value)) return null;
  // Each rule becomes one line of the facts sent, so line breaks inside a rule are flattened.
  const facts = asStringList(value.facts)
    .map((fact) => fact.trim().split(LINE_BREAKS).join(" ").trim())
    .filter(Boolean);
  if (facts.length === 0) return null;
  const links = [parseLink(value.source_name, value.source_url)];
  if (Array.isArray(value.more_sources)) {
    for (const extra of value.more_sources) {
      if (isObject(extra)) links.push(parseLink(extra.name, extra.url));
    }
  }
  return {
    label: asTrimmed(value.label) || "General scam red flags",
    facts,
    links: links.filter((link): link is SourceLink => link !== null),
  };
}

export function parseWhy(value: unknown): Why | null {
  if (!isObject(value) || !Array.isArray(value.points)) return null;
  const points: WhyPoint[] = [];
  for (const point of value.points) {
    if (!isObject(point)) continue;
    const stat = asTrimmed(point.stat);
    const text = asTrimmed(point.text);
    if (!stat && !text) continue;
    const url = asTrimmed(point.source_url);
    points.push({
      stat,
      text,
      sourceName: asTrimmed(point.source_name),
      sourceUrl: isHttpsUrl(url) ? url : null,
    });
  }
  if (points.length === 0) return null;
  return { headline: asTrimmed(value.headline), points };
}

/** Retry-After is either a number of seconds or an HTTP date. */
export function retryAfterSeconds(header: string | null, now: number = Date.now()): number | null {
  const raw = (header ?? "").trim();
  if (/^\d+$/.test(raw)) return Math.max(1, Number(raw));
  const when = raw ? Date.parse(raw) : Number.NaN;
  return Number.isNaN(when) ? null : Math.max(1, Math.ceil((when - now) / 1000));
}

export interface ErrorContext {
  status: number;
  detail: string;
  retryAfter: string | null;
  hadImage: boolean;
}

/** One clear sentence for each failure the backend can report. */
export function errorMessage({ status, detail, retryAfter, hadImage }: ErrorContext): string {
  switch (status) {
    case 429: {
      const seconds = retryAfterSeconds(retryAfter);
      return seconds === null
        ? "Too many checks in a short time. Wait a moment, then try again."
        : `Too many checks in a short time. Wait ${plural(seconds, "second")}, then try again.`;
    }
    case 504:
      return "The investigation took too long and was stopped. Try again, or run the check without investigation.";
    case 413:
      if (hadImage) return "That screenshot is too large to check. Use an image under 8 MB.";
      return detail || "That message is too long to check.";
    case 415:
      return "That file type is not supported. Choose a PNG, JPEG or WebP screenshot.";
    case 400:
      return detail || "The check could not be started. Review the message and the facts, then try again.";
    case 502:
      return detail || "The model could not complete the check. Please try again.";
    default:
      if (detail) return detail;
      if (status >= 500) {
        return "The ProofMode server could not be reached. Check that the backend is running, then try again.";
      }
      return `The check failed (HTTP ${status}). Please try again.`;
  }
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

/** Run one check. Rejects with ApiError, or with the abort error when cancelled. */
export async function postReview(request: ReviewRequest, signal?: AbortSignal): Promise<Review> {
  const form = new FormData();
  if (request.image) form.append("image", request.image, request.image.name);
  if (request.text.trim()) form.append("text", request.text);
  form.append("sources", request.sources);
  if (request.investigate) {
    form.append("investigate", "1");
    if (request.officialDomain.trim()) {
      form.append("official_domain", request.officialDomain.trim());
    }
  }

  let response: Response;
  try {
    response = await fetch("/api/review", {
      method: "POST",
      body: form,
      headers: { Accept: "application/json" },
      credentials: "same-origin",
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    if (signal?.aborted) throw error;
    throw new ApiError(
      0,
      "Could not reach the ProofMode server. Check your connection, then try again.",
    );
  }

  const body = await readJson(response);
  if (!response.ok) {
    throw new ApiError(
      response.status,
      errorMessage({
        status: response.status,
        detail: isObject(body) ? asTrimmed(body.detail) : "",
        retryAfter: response.headers.get("Retry-After"),
        hadImage: request.image !== null,
      }),
    );
  }
  return parseReview(body);
}

async function getJson(path: string): Promise<unknown> {
  try {
    const response = await fetch(path, {
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    });
    return response.ok ? await readJson(response) : null;
  } catch {
    return null;
  }
}

export async function fetchBaseline(): Promise<Baseline | null> {
  return parseBaseline(await getJson("/baseline.json"));
}

export async function fetchCapabilities(): Promise<Capabilities | null> {
  return parseCapabilities(await getJson("/api/capabilities"));
}

/** Load the fictional example screenshot as a file ready to upload. */
export async function fetchSampleImage(): Promise<File> {
  const response = await fetch("/sample.png", { credentials: "same-origin" });
  if (!response.ok) throw new ApiError(response.status, "The example screenshot is unavailable.");
  const blob = await response.blob();
  return new File([blob], "tidewater-cloud-message.png", { type: "image/png" });
}
