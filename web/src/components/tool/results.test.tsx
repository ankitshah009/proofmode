import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Step, Verdict } from "@/lib/api";
import { claim } from "@/test/fixtures";

import { ClaimCard } from "./ClaimCard";
import { FactsChecked, InvestigationTimeline, OfficialFactsPanel, Tally } from "./ResultParts";
import { VerdictBanner } from "./VerdictBanner";

describe("VerdictBanner", () => {
  it.each([
    ["contradicts_facts", "org", "Do not trust this message", /2 claims in this message contradict the official facts\./],
    ["consistent", "org", "Consistent with the official facts", /not proof that the message is genuine/],
    ["unverified", "org", "Not enough facts to judge", /do not settle the claims/],
    ["contradicts_facts", "general", "Do not trust this message", /contradict the general scam red-flag rules\./],
    ["consistent", "general", "No common scam pattern found", /common scam patterns only/],
    ["unverified", "general", "The general rules do not settle this", /does not make it genuine/],
  ] as const)("shows the %s verdict in %s mode", (verdict, mode, title, detail) => {
    render(<VerdictBanner verdict={verdict} mode={mode} contradicted={2} />);
    const banner = screen.getByRole("status");
    expect(banner).toHaveAttribute("data-verdict", verdict);
    expect(banner).toHaveAttribute("tabindex", "-1");
    expect(within(banner).getByText(title)).toBeInTheDocument();
    expect(banner).toHaveTextContent(detail);
  });

  it("is driven by the verdict alone, whatever the count says", () => {
    const verdict: Verdict = "consistent";
    render(<VerdictBanner verdict={verdict} mode="org" contradicted={5} />);
    expect(screen.getByRole("status")).toHaveTextContent("Consistent with the official facts");
    expect(screen.queryByText("Do not trust this message")).not.toBeInTheDocument();
  });

  it("uses the singular for one contradicted claim", () => {
    render(<VerdictBanner verdict="contradicts_facts" mode="org" contradicted={1} />);
    expect(screen.getByRole("status")).toHaveTextContent(
      "1 claim in this message contradicts the official facts.",
    );
  });
});

describe("ClaimCard", () => {
  const known = new Set(["S1", "S5"]);

  it("renders the badge text, claim, explanation, quote and correction", () => {
    render(
      <ol>
        <ClaimCard claim={claim()} index={0} total={2} mode="org" knownSourceIds={known} onCite={vi.fn()} />
      </ol>,
    );
    const card = screen.getByRole("listitem");
    expect(card).toHaveAttribute("data-status", "contradicted");
    expect(within(card).getByText("Contradicts the official facts")).toBeInTheDocument();
    expect(within(card).getByText("Claim 1 of 2")).toBeInTheDocument();
    expect(within(card).getByRole("heading", { name: "Your API credits expire in 24 hours." })).toBeInTheDocument();
    expect(within(card).getByText(/S1 says credits do not expire/)).toBeInTheDocument();
    const quote = card.querySelector("blockquote");
    expect(quote).toHaveTextContent("Tidewater Cloud credits do not expire.");
    expect(within(card).getByText("What the official facts say")).toBeInTheDocument();
  });

  it("uses the general wording in general mode and adds a next step when unverifiable", () => {
    render(
      <ol>
        <ClaimCard
          claim={claim({ status: "insufficient_evidence", source_ids: [], evidence_quotes: [], correction: "" })}
          index={0}
          total={1}
          mode="general"
          knownSourceIds={known}
          onCite={vi.fn()}
        />
      </ol>,
    );
    expect(screen.getByText("Not covered by the general rules")).toBeInTheDocument();
    expect(screen.getByText(/No general rule covers this claim/)).toBeInTheDocument();
    expect(document.querySelector("blockquote")).toBeNull();
  });

  it("shows markup in model text as text, never as elements", () => {
    const hostile = '<img src=x onerror="alert(1)"><script>alert(2)</script><b>bold</b>';
    const { container } = render(
      <ol>
        <ClaimCard
          claim={claim({
            claim_text: hostile,
            explanation: `Explained ${hostile}`,
            evidence_quotes: [`Quoted ${hostile}`],
            correction: `Corrected ${hostile}`,
          })}
          index={0}
          total={1}
          mode="org"
          knownSourceIds={known}
          onCite={vi.fn()}
        />
      </ol>,
    );
    expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent(hostile);
    expect(screen.getByText(`Explained ${hostile}`)).toBeInTheDocument();
    expect(screen.getByText(`Quoted ${hostile}`)).toBeInTheDocument();
    expect(screen.getByText(`Corrected ${hostile}`)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
  });

  it("makes a listed source id a button that cites its row, and leaves an unknown id as text", async () => {
    const onCite = vi.fn();
    const user = userEvent.setup();
    render(
      <ol>
        <ClaimCard
          claim={claim({ source_ids: ["S1", "S9"], evidence_quotes: ["Quote one", "Quote two"] })}
          index={0}
          total={1}
          mode="org"
          knownSourceIds={known}
          onCite={onCite}
        />
      </ol>,
    );
    await user.click(screen.getByRole("button", { name: /S1, show this line/ }));
    expect(onCite).toHaveBeenCalledWith("S1", true);
    expect(screen.queryByRole("button", { name: /S9/ })).not.toBeInTheDocument();
    expect(screen.getByText("S9")).toBeInTheDocument();
  });
});

describe("Tally and OfficialFactsPanel", () => {
  const claims = [
    claim(),
    claim({ claim_text: "Support is available 24/7.", status: "supported", correction: "" }),
    claim({ claim_text: "Call us today.", status: "insufficient_evidence", correction: "" }),
  ];

  it("gives each count a text label", () => {
    render(<Tally claims={[...claims, claim()]} mode="org" />);
    const terms = screen.getAllByRole("term").map((term) => term.textContent);
    expect(terms).toEqual([
      "Matches the official facts",
      "Contradicts the official facts",
      "Cannot be verified",
    ]);
    expect(screen.getAllByRole("definition").map((cell) => cell.textContent)).toEqual(["1", "2", "1"]);
  });

  it("marks the contradicted claim with del and ins and hidden labels", () => {
    const { container } = render(<OfficialFactsPanel claims={claims} mode="org" />);
    expect(screen.getByRole("heading", { name: "What the official facts say" })).toBeInTheDocument();
    expect(container.querySelector("del")).toHaveTextContent(
      "The message says: Your API credits expire in 24 hours.",
    );
    expect(container.querySelector("ins")).toHaveTextContent(
      "The official facts say: Tidewater Cloud credits do not expire.",
    );
    expect(container.querySelectorAll("del")).toHaveLength(1);
  });
});

describe("FactsChecked", () => {
  it("labels origins, marks the cited row in text, and links only https fetched sources", () => {
    render(
      <FactsChecked
        title="Facts as checked"
        citedId="S2"
        sources={[
          { id: "S1", text: "Typed fact", url: null, origin: "user" },
          { id: "S2", text: "Fetched fact", url: "https://tidewater.example/help/billing", origin: "fetched" },
          { id: "S3", text: "Insecure fact", url: "http://tidewater.example/help", origin: "fetched" },
          { id: "S4", text: "Script fact", url: "javascript:alert(1)", origin: "fetched" },
          { id: "S5", text: "Registered 7 days ago.", url: null, origin: "lookup" },
        ]}
      />,
    );
    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(5);
    expect(rows[0]).toHaveTextContent("Supplied by you");
    expect(rows[1]).toHaveAttribute("data-cited", "true");
    expect(rows[1]).toHaveTextContent("cited");
    expect(rows[1]).toHaveTextContent("Read from the official website");
    expect(rows[4]).toHaveTextContent("Domain registration record");
    expect(rows[0]).not.toHaveAttribute("data-cited");

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "https://tidewater.example/help/billing");
    expect(links[0]).toHaveAttribute("rel", "noopener noreferrer");
  });
});

describe("InvestigationTimeline", () => {
  const steps: Step[] = [
    {
      tool: "fetch_official_page",
      argument: "https://tidewater.example/help/billing",
      outcome: "Read https://tidewater.example/help/billing: 7 relevant line(s) kept as S1 to S7.",
      ok: true,
    },
    {
      tool: "fetch_official_page",
      argument: "https://tidewater-accounts.co/",
      outcome: "Refused: <b>tidewater-accounts.co</b> appears in the message.",
      ok: false,
    },
    { tool: "lookup_domain", argument: "tidewater-accounts.co", outcome: "Registered 7 days ago.", ok: true },
    { tool: "finish", argument: "", outcome: "Returned 6 claim(s).", ok: true },
  ];

  it("lists every step in order with its outcome and a text status", () => {
    const { container } = render(<InvestigationTimeline steps={steps} />);
    expect(screen.getByRole("heading", { name: "Investigation" })).toBeInTheDocument();
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(4);
    expect(items[0]).toHaveTextContent("Read a page on the official website");
    expect(items[0]).toHaveTextContent("Done");
    expect(items[0]).toHaveTextContent("kept as S1 to S7");
    expect(items[1]).toHaveTextContent("Refused or failed");
    expect(items[1]).toHaveTextContent("Refused: <b>tidewater-accounts.co</b> appears in the message.");
    expect(items[2]).toHaveTextContent("Looked up a domain registration");
    expect(items[3]).toHaveTextContent("Finished the investigation");
    // Arguments are shown as text. A URL the model asked for is never turned into a link.
    expect(container.querySelector("a")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
  });

  it("renders nothing when there are no steps", () => {
    const { container } = render(<InvestigationTimeline steps={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
