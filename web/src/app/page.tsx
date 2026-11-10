import { connection } from "next/server";

import {
  BuiltToResist,
  DataHandling,
  Footer,
  HowItWorks,
  TopBar,
  WhatIsDifferent,
  WhyHard,
  WhyMatters,
} from "@/components/sections/StaticSections";
import { ProofTool } from "@/components/tool/ProofTool";
import { loadBackendSnapshot } from "@/lib/backend";

export default async function Page() {
  // Rendered per request: the Content-Security-Policy nonce set in src/proxy.ts
  // exists only while a request is being served.
  await connection();
  const { baseline, capabilities, health, why } = await loadBackendSnapshot();

  return (
    <div className="mx-auto w-full max-w-[1180px] px-4 pb-10 pt-3 md:px-8 md:pb-12">
      <a
        href="#main"
        className="sr-only focus-visible:not-sr-only focus-visible:absolute focus-visible:left-4 focus-visible:top-4 focus-visible:z-10 focus-visible:rounded-md focus-visible:bg-card focus-visible:px-4 focus-visible:py-3"
      >
        Skip to the check
      </a>
      <header>
        <TopBar showWhy={why !== null} />
        <h1 className="mt-4 font-serif text-[44px] leading-none tracking-tight md:text-6xl">
          Is this message <em className="text-accent-text">real?</em>
        </h1>
        <p className="mt-3 max-w-[70ch] text-[17px] text-muted-foreground">
          Drop in a screenshot of a suspicious email, text or chat message, and each claim in it is
          checked against common scam red flags or the organisation&apos;s own official facts.
        </p>
      </header>

      <main id="main" className="mt-5">
        <noscript>
          <p className="mb-5 rounded-lg border border-primary px-4 py-3">
            ProofMode needs JavaScript to upload the message and show the results.
          </p>
        </noscript>
        <ProofTool initialBaseline={baseline} initialCapabilities={capabilities} />
        <DataHandling />
        <HowItWorks />
        <WhyHard />
        <WhatIsDifferent />
        <BuiltToResist />
        {why ? <WhyMatters why={why} /> : null}
      </main>

      <Footer health={health} />
    </div>
  );
}
