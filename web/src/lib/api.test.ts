import {
  ApiError,
  errorMessage,
  isHttpsUrl,
  parseBaseline,
  parseReview,
  parseWhy,
  postReview,
  retryAfterSeconds,
  type ReviewRequest,
} from "@/lib/api";
import { jsonResponse, review } from "@/test/fixtures";

const REQUEST: ReviewRequest = {
  image: null,
  text: "Pay a fee with a gift card.",
  sources: "Gift cards are never accepted.",
  officialDomain: "",
  investigate: false,
};

function stubFetch(response: Response | Error) {
  const mock = vi.fn(async () => {
    if (response instanceof Error) throw response;
    return response;
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

async function failure(request: ReviewRequest = REQUEST): Promise<ApiError> {
  try {
    await postReview(request);
  } catch (error) {
    if (error instanceof ApiError) return error;
    throw error;
  }
  throw new Error("postReview did not reject");
}

describe("errorMessage", () => {
  const base = { detail: "", retryAfter: null, hadImage: true };

  it("says how many seconds to wait on 429", () => {
    expect(errorMessage({ ...base, status: 429, retryAfter: "42" })).toBe(
      "Too many checks in a short time. Wait 42 seconds, then try again.",
    );
    expect(errorMessage({ ...base, status: 429, retryAfter: "1" })).toContain("Wait 1 second,");
  });

  it("falls back to a general wait when Retry-After is missing", () => {
    expect(errorMessage({ ...base, status: 429 })).toBe(
      "Too many checks in a short time. Wait a moment, then try again.",
    );
  });

  it("says the investigation took too long on 504", () => {
    expect(errorMessage({ ...base, status: 504, detail: "ignored" })).toMatch(
      /investigation took too long/i,
    );
  });

  it("explains size and type limits", () => {
    expect(errorMessage({ ...base, status: 413 })).toMatch(/under 8 MB/);
    expect(
      errorMessage({ ...base, status: 413, hadImage: false, detail: "The message is longer than 10,000 characters." }),
    ).toBe("The message is longer than 10,000 characters.");
    expect(errorMessage({ ...base, status: 415 })).toMatch(/PNG, JPEG or WebP/);
  });

  it("passes on the server's own sentence for 400 and 502", () => {
    expect(errorMessage({ ...base, status: 400, detail: "The image is empty." })).toBe(
      "The image is empty.",
    );
    expect(errorMessage({ ...base, status: 502, detail: "The model did not reply." })).toBe(
      "The model did not reply.",
    );
    expect(errorMessage({ ...base, status: 502 })).toMatch(/could not complete the check/);
  });

  it("covers a backend that cannot be reached and unknown statuses", () => {
    expect(errorMessage({ ...base, status: 500 })).toMatch(/could not be reached/);
    expect(errorMessage({ ...base, status: 418 })).toBe("The check failed (HTTP 418). Please try again.");
  });
});

describe("retryAfterSeconds", () => {
  it("reads seconds and HTTP dates", () => {
    expect(retryAfterSeconds("7")).toBe(7);
    expect(retryAfterSeconds("0")).toBe(1);
    const now = Date.parse("2026-11-09T10:00:00Z");
    expect(retryAfterSeconds("Mon, 09 Nov 2026 10:00:30 GMT", now)).toBe(30);
    expect(retryAfterSeconds("soon")).toBeNull();
    expect(retryAfterSeconds(null)).toBeNull();
  });
});

describe("postReview", () => {
  it("sends the form the backend expects and returns the parsed review", async () => {
    const fetchMock = stubFetch(jsonResponse(review()));
    const image = new File(["png"], "message.png", { type: "image/png" });
    const result = await postReview({
      image,
      text: "",
      sources: "Fact one\nFact two",
      officialDomain: " tidewater.example ",
      investigate: true,
    });

    expect(result.verdict).toBe("contradicts_facts");
    const [path, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(path).toBe("/api/review");
    expect(init.method).toBe("POST");
    const form = init.body as FormData;
    expect(form.get("image")).toBeInstanceOf(File);
    expect(form.get("sources")).toBe("Fact one\nFact two");
    expect(form.get("investigate")).toBe("1");
    expect(form.get("official_domain")).toBe("tidewater.example");
    expect(form.has("text")).toBe(false);
  });

  it("leaves out the investigation fields unless investigation is on", async () => {
    const fetchMock = stubFetch(jsonResponse(review()));
    await postReview({ ...REQUEST, officialDomain: "tidewater.example" });
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const form = init.body as FormData;
    expect(form.get("text")).toBe(REQUEST.text);
    expect(form.has("investigate")).toBe(false);
    expect(form.has("official_domain")).toBe(false);
    expect(form.has("image")).toBe(false);
  });

  it.each([
    [400, { detail: "Attach a screenshot of the message or paste its text." }, {}, /Attach a screenshot/],
    [413, { detail: "The message is longer than 10,000 characters." }, {}, /longer than 10,000/],
    [415, { detail: "Upload a PNG, JPEG or WebP image." }, {}, /PNG, JPEG or WebP/],
    [429, { detail: "Too many requests." }, { "Retry-After": "12" }, /Wait 12 seconds/],
    [502, { detail: "The model call failed." }, {}, /model call failed/],
    [504, { detail: "The investigation took too long and was stopped." }, {}, /took too long/],
  ] as const)("maps HTTP %i to a clear message", async (status, body, headers, expected) => {
    stubFetch(jsonResponse(body, { status, headers: { "Content-Type": "application/json", ...headers } }));
    const error = await failure();
    expect(error.status).toBe(status);
    expect(error.message).toMatch(expected);
  });

  it("handles an error reply that is not JSON", async () => {
    stubFetch(new Response("Internal Server Error", { status: 500 }));
    const error = await failure();
    expect(error.message).toMatch(/could not be reached/);
  });

  it("reports a network failure", async () => {
    stubFetch(new TypeError("Failed to fetch"));
    const error = await failure();
    expect(error.status).toBe(0);
    expect(error.message).toMatch(/Could not reach the ProofMode server/);
  });

  it("rejects a reply without a known verdict", async () => {
    stubFetch(jsonResponse({ model: "m", claims: [], verdict: "safe" }));
    const error = await failure();
    expect(error.message).toMatch(/no verdict/);
  });
});

describe("parsers", () => {
  it("narrows a review and never upgrades an unknown status", () => {
    const parsed = parseReview({
      model: " meta/muse-ember ",
      verdict: "unverified",
      claims: [{ claim_text: "A", status: "verified", source_ids: ["S1", 2], evidence_quotes: null }, "junk"],
      notes: ["one", 2],
      sources: [{ id: "S1", text: "Fact", url: "https://tidewater.example/a", origin: "fetched" }, { text: "no id" }],
      steps: [{ tool: "finish", ok: false }, {}],
    });
    expect(parsed.model).toBe("meta/muse-ember");
    expect(parsed.claims).toHaveLength(1);
    expect(parsed.claims[0]?.status).toBe("insufficient_evidence");
    expect(parsed.claims[0]?.source_ids).toEqual(["S1"]);
    expect(parsed.notes).toEqual(["one"]);
    expect(parsed.sources).toEqual([
      { id: "S1", text: "Fact", url: "https://tidewater.example/a", origin: "fetched" },
    ]);
    expect(parsed.steps).toEqual([{ tool: "finish", argument: "", outcome: "", ok: false }]);
  });

  it("only accepts https links", () => {
    expect(isHttpsUrl("https://consumer.ftc.gov/articles/gift-card-scams")).toBe(true);
    expect(isHttpsUrl("http://consumer.ftc.gov/")).toBe(false);
    expect(isHttpsUrl("javascript:alert(1)")).toBe(false);
    expect(isHttpsUrl("not a url")).toBe(false);

    const baseline = parseBaseline({
      facts: ["Rule one", "  "],
      source_name: "FTC",
      source_url: "https://consumer.ftc.gov/articles/how-avoid-scam",
      more_sources: [{ name: "Bad", url: "javascript:alert(1)" }],
    });
    expect(baseline?.facts).toEqual(["Rule one"]);
    expect(baseline?.links).toEqual([
      { name: "FTC", url: "https://consumer.ftc.gov/articles/how-avoid-scam" },
    ]);

    const why = parseWhy({ headline: "H", points: [{ stat: "Never", text: "T", source_name: "FTC", source_url: "http://x.test" }] });
    expect(why?.points[0]?.sourceUrl).toBeNull();
  });
});
