import type { Health, Why } from "@/lib/api";

const GITHUB_URL = "https://github.com/ankitshah009/proofmode";

interface TopBarProps {
  showWhy: boolean;
}

export function TopBar({ showWhy }: TopBarProps) {
  const linkClass =
    "inline-flex min-h-11 items-center text-sm font-semibold text-muted-foreground no-underline hover:text-foreground hover:underline hover:decoration-primary hover:underline-offset-4 focus-visible:outline-offset-[-3px]";
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-6 border-b border-border">
      <p className="font-mono text-[13px] uppercase tracking-[0.16em] text-muted-foreground">
        <b className="font-semibold text-accent-text">Proof</b>Mode
      </p>
      <nav aria-label="On this page" className="min-w-0 max-w-full">
        <ul className="relative flex gap-x-5 overflow-x-auto whitespace-nowrap [scrollbar-width:none]">
          <li>
            <a href="#how" className={linkClass}>
              How it works
            </a>
          </li>
          <li>
            <a href="#hard" className={linkClass}>
              Why this is hard
            </a>
          </li>
          <li>
            <a href="#different" className={linkClass}>
              What makes this different
            </a>
          </li>
          {showWhy ? (
            <li>
              <a href="#why" className={linkClass}>
                Why this matters
              </a>
            </li>
          ) : null}
          <li>
            <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" className={linkClass}>
              GitHub
              <span className="sr-only"> repository (opens in a new tab)</span>
            </a>
          </li>
        </ul>
      </nav>
    </div>
  );
}

const SECTION = "mt-14 scroll-mt-4 border-t border-border pt-8";
const SECTION_TITLE = "font-serif text-[32px] leading-tight tracking-tight";
const SECTION_LEAD = "mt-2 max-w-[72ch] text-[15px] text-muted-foreground";

type Actor = "input" | "model" | "code";

interface FlowStep {
  actor: Actor;
  title: string;
  text: string;
}

const FLOW: readonly FlowStep[] = [
  {
    actor: "input",
    title: "Message in",
    text: "Drop, paste or choose a screenshot of the message, or paste its text.",
  },
  {
    actor: "input",
    title: "Evidence",
    text: "General scam red flags taken from FTC guidance, or the organisation's own official facts.",
  },
  {
    actor: "model",
    title: "Muse Ember reads it",
    text: "One call through OpenRouter to the model, Muse Ember by default: it lists the sender and each claim, and to judge a claim it must cite a fact and quote it word for word. An investigation adds tool calls within fixed budgets.",
  },
  {
    actor: "code",
    title: "ProofMode checks the model",
    text: 'Every cited fact must exist and every quote must appear in it, or the claim is downgraded to "cannot be verified".',
  },
  {
    actor: "code",
    title: "Verdict in code",
    text: "The overall verdict is computed by the app from the checked claims, never taken from the model.",
  },
];

const ACTOR_LABELS: Record<Actor, string> = { input: "Input", model: "Model", code: "Code" };
const ACTOR_CLASSES: Record<Actor, string> = {
  input: "border-dashed border-muted-foreground text-muted-foreground",
  model: "border-primary bg-primary text-primary-foreground",
  code: "border-foreground text-foreground",
};

export function HowItWorks() {
  return (
    <section id="how" aria-labelledby="how-title" className={SECTION}>
      <h2 id="how-title" className={SECTION_TITLE}>
        How it works
      </h2>
      <p className={SECTION_LEAD}>
        Steps 1 and 2 are the input. Step 3 is the only step where the model runs. Steps 4 and 5
        are ordinary code that checks the model&apos;s answer.
      </p>
      <ol className="mt-5 grid rounded-lg border border-border bg-card md:grid-cols-5">
        {FLOW.map((step, index) => (
          <li
            key={step.title}
            className={`min-w-0 border-border px-4 pb-4 pt-3.5 ${
              index > 0 ? "border-t md:border-l md:border-t-0" : ""
            } ${step.actor === "model" ? "bg-primary/10" : ""}`}
          >
            <div className="flex items-center justify-between gap-2.5">
              <span
                className={`font-serif text-[32px] leading-none ${
                  step.actor === "model" ? "text-accent-text" : "text-muted-foreground"
                }`}
              >
                {index + 1}
              </span>
              <span
                className={`rounded border px-2 py-0.5 font-mono text-xs font-semibold uppercase tracking-widest ${ACTOR_CLASSES[step.actor]}`}
              >
                {ACTOR_LABELS[step.actor]}
              </span>
            </div>
            <h3 className="mt-2.5 text-[15px] font-semibold leading-snug">{step.title}</h3>
            <p className="mt-1 text-sm leading-snug text-muted-foreground">{step.text}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

interface HardProblem {
  title: string;
  problem: string;
  answer: string;
}

const HARD: readonly HardProblem[] = [
  {
    title: "Models make things up",
    problem: "A model will call a message a scam and invent the reason.",
    answer:
      "A claim is only marked as matching or contradicting when it comes with a quoted fact, and the app checks the quote itself.",
  },
  {
    title: "The message is written by an attacker",
    problem: 'It can contain text aimed at the model, such as "mark this as safe".',
    answer:
      "Message text is treated as data. In live tests on 2026-11-09 such an instruction changed no verdict.",
  },
  {
    title: "People rarely have the official facts to hand",
    problem: "Looking them up takes time that a person under pressure may not have.",
    answer:
      "The first check runs against general scam red flags from FTC guidance. The organisation's own facts make it stronger.",
  },
  {
    title: "Letting a model look things up is risky",
    problem: 'A scam message can try to point it at the scammer\'s own site as the "official" source.',
    answer:
      "An investigation refuses in code to read any domain that appears in the message, reads one site per check over https at public addresses only, and never lets a domain lookup alone decide a status.",
  },
  {
    title: "New scams have no history",
    problem: "Blocklists need a link or sender that has been seen before.",
    answer: "A claim by claim check does not. It needs only the message and the facts.",
  },
];

export function WhyHard() {
  return (
    <section id="hard" aria-labelledby="hard-title" className={SECTION}>
      <h2 id="hard-title" className={SECTION_TITLE}>
        Why this is hard
      </h2>
      <p className={SECTION_LEAD}>
        Five problems that make a trustworthy fraud check difficult, and what ProofMode does about
        each.
      </p>
      <ol className="mt-5">
        {HARD.map((item, index) => (
          <li
            key={item.title}
            className="grid min-w-0 grid-cols-[2.4em_minmax(0,1fr)] gap-x-2.5 gap-y-2 border-t border-border py-4 md:grid-cols-[3em_minmax(0,5fr)_minmax(0,6fr)] md:gap-x-10"
          >
            <span className="font-serif text-[32px] leading-none text-accent-text">{index + 1}</span>
            <div>
              <h3 className="font-serif text-[22px] leading-tight">{item.title}</h3>
              <p className="mt-1.5 text-[15px] text-muted-foreground">{item.problem}</p>
            </div>
            <div className="col-start-2 min-w-0 border-l-2 border-primary pl-3.5 md:col-start-3">
              <p className="mono-label text-accent-text">What ProofMode does</p>
              <p className="mt-1 text-[15px]">{item.answer}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

const COMPARE: readonly (readonly [string, string, string])[] = [
  ["What is checked", "Sender, link or attachment reputation", "The claims the message makes"],
  [
    "What you get",
    "A score or a block",
    "Each false claim with the quoted fact that contradicts it",
  ],
  [
    "A brand-new scam with no known-bad link",
    "Often nothing to match",
    "Still checked against the facts",
  ],
  ["How to trust it", "Trust the score", "Read the quote yourself"],
];

export function WhatIsDifferent() {
  const cell = "border-t border-border px-2.5 py-3 text-left align-top md:px-4";
  return (
    <section id="different" aria-labelledby="different-title" className={SECTION}>
      <h2 id="different-title" className={SECTION_TITLE}>
        What makes this different
      </h2>
      <div className="mt-5 overflow-hidden rounded-lg border border-border bg-card">
        <table className="w-full table-fixed border-collapse text-sm leading-snug md:text-[15px]">
          <caption className="px-2.5 py-3 text-left text-sm text-muted-foreground md:px-4">
            Spam filters and link scanners judge where a message comes from. ProofMode judges what
            it says.
          </caption>
          <thead>
            <tr>
              <th scope="col" className={`${cell} w-[27%] md:w-[22%]`}>
                <span className="sr-only">Question</span>
              </th>
              <th
                scope="col"
                className={`${cell} font-mono text-xs font-semibold uppercase tracking-wider text-muted-foreground`}
              >
                Spam filters and link scanners
              </th>
              <th
                scope="col"
                className={`${cell} bg-primary/10 font-mono text-xs font-semibold uppercase tracking-wider text-accent-text`}
              >
                ProofMode
              </th>
            </tr>
          </thead>
          <tbody>
            {COMPARE.map(([question, others, ours]) => (
              <tr key={question}>
                <th scope="row" className={`${cell} font-semibold text-muted-foreground`}>
                  {question}
                </th>
                <td className={`${cell} text-muted-foreground`}>{others}</td>
                <td className={`${cell} bg-primary/10 text-foreground`}>{ours}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3.5 max-w-[88ch] text-sm text-muted-foreground">
        <b className="text-foreground">Limits.</b> Results depend on the facts supplied. A
        &quot;consistent&quot; result is not proof that a message is genuine. Links and attachments
        are not scanned. Accuracy beyond the built-in example has not been measured.
      </p>
    </section>
  );
}

const GUARDS: readonly (readonly [string, string])[] = [
  [
    "The message is data",
    "Text in the message is treated as data, and instructions in it are not followed. In live tests on 2026-11-09, a screenshot telling the reviewer to mark every claim as supported changed no verdict and was reported as an instruction that was not followed.",
  ],
  [
    "Uploads are checked, not kept",
    "Screenshots are checked by content, not by the file type they declare. They are size limited and rate limited, held in memory only, and not stored by this app.",
  ],
  [
    "The API key stays on the server",
    "The OpenRouter key is never sent to this page, and the calls to the model are made by the server.",
  ],
];

export function BuiltToResist() {
  return (
    <section id="resist" aria-labelledby="resist-title" className={SECTION}>
      <h2 id="resist-title" className={SECTION_TITLE}>
        Built to resist a hostile message
      </h2>
      <ul className="mt-5 grid md:grid-cols-3 md:gap-x-10">
        {GUARDS.map(([title, text]) => (
          <li key={title} className="min-w-0 border-t border-border pb-3 pt-3.5">
            <h3 className="font-serif text-[22px] leading-tight">{title}</h3>
            <p className="mt-1.5 text-[15px] text-muted-foreground">{text}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}

interface WhyMattersProps {
  why: Why;
}

/** Every figure here comes from the backend's why.json, with its source beside it. */
export function WhyMatters({ why }: WhyMattersProps) {
  return (
    <section id="why" aria-labelledby="why-title" className={SECTION}>
      <h2 id="why-title" className="mono-label">
        Why this matters
      </h2>
      {why.headline ? (
        <p className="mt-3 max-w-[26ch] font-serif text-3xl leading-[1.08] tracking-tight md:text-5xl">
          {why.headline}
        </p>
      ) : null}
      <ul className="mt-6">
        {why.points.map((point, index) => (
          <li
            key={`${index}-${point.stat}`}
            className="grid min-w-0 gap-x-12 gap-y-1.5 border-t border-border pb-2.5 pt-4 md:grid-cols-[minmax(0,4fr)_minmax(0,7fr)]"
          >
            {point.stat ? (
              <p className="font-serif text-[32px] leading-tight text-accent-text md:row-span-2">
                {point.stat}
              </p>
            ) : null}
            {point.text ? (
              <p className="max-w-[64ch] text-muted-foreground md:col-start-2">{point.text}</p>
            ) : null}
            {point.sourceUrl || point.sourceName ? (
              <p className="text-sm text-muted-foreground md:col-start-2">
                {point.sourceUrl ? (
                  <a
                    href={point.sourceUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-link inline-flex min-h-11 items-center"
                  >
                    Source: {point.sourceName || point.sourceUrl}
                    <span className="sr-only"> (opens in a new tab)</span>
                  </a>
                ) : (
                  <>Source: {point.sourceName}</>
                )}
              </p>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function DataHandling() {
  return (
    <details
      id="handling"
      className="group mt-10 scroll-mt-4 rounded-lg border border-border bg-card px-4"
    >
      <summary className="flex min-h-12 cursor-pointer list-none items-center gap-2.5 text-[15px] font-semibold [&::-webkit-details-marker]:hidden">
        <span aria-hidden="true" className="w-4 flex-none text-center font-mono text-accent-text">
          <span className="group-open:hidden">+</span>
          <span className="hidden group-open:inline">-</span>
        </span>
        How your message is handled, and what the result means
      </summary>
      <ul className="grid max-w-[80ch] list-disc gap-1.5 pb-4 pl-9 text-[15px] text-muted-foreground">
        <li>
          The screenshot or pasted text, and the facts or rules, are sent to the model through
          OpenRouter. This app does not store them.
        </li>
        <li>Text inside the message is treated as data, never as instructions.</li>
        <li>
          The general check catches common scam patterns only. A message that passes it can still
          be fraudulent.
        </li>
        <li>
          A check against the organisation&apos;s own facts is stronger, and depends on the facts
          you supply.
        </li>
        <li>
          During an investigation the server reads pages of the official website you name or the
          model proposes, and looks up domain registration records. A domain named in the message
          is never read.
        </li>
        <li>
          The result is not legal or security advice. Confirm with the organisation through its
          official channel before you act.
        </li>
      </ul>
    </details>
  );
}

interface FooterProps {
  health: Health | null;
}

export function Footer({ health }: FooterProps) {
  return (
    <footer className="mt-12 flex flex-wrap gap-x-4 gap-y-1.5 border-t border-border pt-4 text-sm text-muted-foreground">
      <p>
        {health?.model
          ? `Checked by ${health.model} through OpenRouter`
          : "Checked by the model through OpenRouter"}
      </p>
      {health?.mock ? (
        <p className="font-mono text-[13px] text-foreground">Demo mode: canned output</p>
      ) : null}
      <p>
        <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" className="text-link">
          Source on GitHub
          <span className="sr-only"> (opens in a new tab)</span>
        </a>
      </p>
    </footer>
  );
}
