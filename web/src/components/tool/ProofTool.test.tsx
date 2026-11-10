import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { EXAMPLE_FACTS } from "@/lib/wording";
import { jsonResponse, review } from "@/test/fixtures";

import { ProofTool } from "./ProofTool";

const BASELINE = {
  label: "General scam red flags",
  source_name: "FTC: How to Avoid a Scam",
  source_url: "https://consumer.ftc.gov/articles/how-avoid-scam",
  facts: ["Rule about gift cards.", "Rule about pressure."],
};

interface Backend {
  capabilities?: { investigate: boolean; text: boolean; model: string };
  reviewReply?: () => Response;
}

function stubBackend({ capabilities, reviewReply }: Backend = {}) {
  const posts: FormData[] = [];
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path === "/baseline.json") return jsonResponse(BASELINE);
    if (path === "/api/capabilities") {
      return jsonResponse(capabilities ?? { investigate: false, text: true, model: "meta/muse-ember" });
    }
    if (path === "/sample.png") {
      return new Response(new Blob(["png-bytes"], { type: "image/png" }), { status: 200 });
    }
    if (path === "/api/review") {
      posts.push(init?.body as FormData);
      return reviewReply ? reviewReply() : jsonResponse(review());
    }
    return new Response("not found", { status: 404 });
  });
  vi.stubGlobal("fetch", mock);
  return { mock, posts };
}

describe("ProofTool", () => {
  it("shows the first view with the general rules and their source", async () => {
    stubBackend();
    render(<ProofTool initialBaseline={null} initialCapabilities={null} />);

    expect(screen.getByRole("button", { name: /Drop, paste or choose a screenshot/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "General scam red flags" })).toBeChecked();
    expect(await screen.findByText("Rule about pressure.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /FTC: How to Avoid a Scam/ })).toHaveAttribute(
      "href",
      "https://consumer.ftc.gov/articles/how-avoid-scam",
    );
    expect(screen.queryByRole("checkbox", { name: "Let the model investigate" })).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("runs the example in one click and moves focus to the verdict", async () => {
    const { posts } = stubBackend();
    const user = userEvent.setup();
    render(<ProofTool initialBaseline={null} initialCapabilities={null} />);

    await user.click(screen.getByRole("button", { name: "Try the example" }));

    const banner = await screen.findByRole("status");
    expect(banner).toHaveTextContent("Do not trust this message");
    expect(banner).toHaveTextContent("1 claim in this message contradicts the official facts.");
    await waitFor(() => expect(banner).toHaveFocus());

    expect(posts).toHaveLength(1);
    const form = posts[0] as FormData;
    const image = form.get("image");
    expect(image).toBeInstanceOf(File);
    expect((image as File).name).toBe("tidewater-cloud-message.png");
    expect(form.get("sources")).toBe(EXAMPLE_FACTS);
    expect(form.has("investigate")).toBe(false);

    // The page switched to the organisation's facts and filled them in.
    expect(screen.getByRole("radio", { name: "This organisation's official facts" })).toBeChecked();
    expect(screen.getByLabelText(/official facts, one per line/)).toHaveValue(EXAMPLE_FACTS);

    expect(screen.getByText("Checked 2 claims against 5 official facts.")).toBeInTheDocument();
    expect(screen.getAllByRole("definition").map((cell) => cell.textContent)).toEqual(["1", "1", "0"]);
    expect(screen.getByRole("img", { name: "The message screenshot as uploaded" })).toBeInTheDocument();
    expect(screen.getByText(/Tidewater Cloud, and its\s+message are fictional/)).toBeInTheDocument();
  });

  it("highlights the matching fact when a source id is clicked", async () => {
    stubBackend();
    const user = userEvent.setup();
    render(<ProofTool initialBaseline={null} initialCapabilities={null} />);
    await user.click(screen.getByRole("button", { name: "Try the example" }));
    await screen.findByRole("status");

    const list = screen.getByRole("list", { name: "Official facts as checked" });
    const row = within(list).getByText("Tidewater Cloud credits do not expire.").closest("li");
    expect(row).not.toHaveAttribute("data-cited");
    await user.click(screen.getByRole("button", { name: /S1, show this line/ }));
    expect(row).toHaveAttribute("data-cited", "true");
    expect(row).toHaveTextContent("cited");
  });

  it("checks pasted text against the general rules", async () => {
    const { posts } = stubBackend({
      reviewReply: () => jsonResponse(review({ verdict: "unverified", claims: [] })),
    });
    const user = userEvent.setup();
    render(<ProofTool initialBaseline={null} initialCapabilities={null} />);
    await screen.findByText("Rule about pressure.");

    await user.click(screen.getByRole("button", { name: "or paste the message text" }));
    await user.type(screen.getByLabelText("The message text"), "Pay a $49 fee with a gift card.");
    await user.click(screen.getByRole("button", { name: "Check this text" }));

    const banner = await screen.findByRole("status");
    expect(banner).toHaveTextContent("The general rules do not settle this");
    const form = posts[0] as FormData;
    expect(form.get("text")).toBe("Pay a $49 fee with a gift card.");
    expect(form.get("sources")).toBe("Rule about gift cards.\nRule about pressure.");
    expect(form.has("image")).toBe(false);
    expect(screen.getByText("No claims were found to check.")).toBeInTheDocument();
  });

  it("offers investigation only when the server supports it, and sends the website with it", async () => {
    const { posts } = stubBackend({
      capabilities: { investigate: true, text: true, model: "meta/muse-ember" },
      reviewReply: () =>
        jsonResponse(
          review({
            sources: [
              { id: "S1", text: "Tidewater Cloud credits do not expire.", url: "https://tidewater.example/help/billing", origin: "fetched" },
              { id: "S5", text: "Support is available 24 hours a day, 7 days a week.", url: "https://tidewater.example/help/billing", origin: "fetched" },
            ],
            steps: [
              { tool: "fetch_official_page", argument: "https://tidewater.example/help/billing", outcome: "Read the page.", ok: true },
              { tool: "finish", argument: "", outcome: "Returned 2 claim(s).", ok: true },
            ],
            notes: ["A note from the server."],
          }),
        ),
    });
    const user = userEvent.setup();
    render(<ProofTool initialBaseline={null} initialCapabilities={null} />);

    await user.click(await screen.findByRole("checkbox", { name: "Let the model investigate" }));
    await user.type(screen.getByLabelText(/Official website/), "tidewater.example");
    await user.click(screen.getByRole("radio", { name: "This organisation's official facts" }));
    await user.click(screen.getByRole("button", { name: "or paste the message text" }));
    await user.type(screen.getByLabelText("The message text"), "Credits expire in 24 hours.");
    await user.click(screen.getByRole("button", { name: "Check this text" }));

    await screen.findByRole("status");
    const form = posts[0] as FormData;
    expect(form.get("investigate")).toBe("1");
    expect(form.get("official_domain")).toBe("tidewater.example");
    expect(form.get("sources")).toBe("");

    expect(screen.getByRole("heading", { name: "Investigation" })).toBeInTheDocument();
    const facts = screen.getByRole("list", { name: "Facts as checked" });
    expect(within(facts).getAllByText("Read from the official website")).toHaveLength(2);
    expect(within(facts).getAllByRole("link")[0]).toHaveAttribute(
      "href",
      "https://tidewater.example/help/billing",
    );
    expect(screen.getByText("A note from the server.")).toBeInTheDocument();
  });

  it("shows a clear inline error when the server rate limits the check", async () => {
    stubBackend({
      reviewReply: () =>
        jsonResponse(
          { detail: "Too many requests. Wait a moment and try again." },
          { status: 429, headers: { "Content-Type": "application/json", "Retry-After": "30" } },
        ),
    });
    const user = userEvent.setup();
    render(<ProofTool initialBaseline={null} initialCapabilities={null} />);
    await user.click(screen.getByRole("button", { name: "Try the example" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Wait 30 seconds, then try again.");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByTestId("results-skeleton")).not.toBeInTheDocument();
  });

  it("rejects a file that is not a supported image before anything is sent", async () => {
    const { posts } = stubBackend();
    const user = userEvent.setup({ applyAccept: false });
    render(<ProofTool initialBaseline={null} initialCapabilities={null} />);
    await user.upload(
      screen.getByTestId("image-input"),
      new File(["%PDF"], "letter.pdf", { type: "application/pdf" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Choose a PNG, JPEG or WebP image.");
    expect(posts).toHaveLength(0);
  });
});
