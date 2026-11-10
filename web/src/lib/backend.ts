import "server-only";

import {
  parseBaseline,
  parseCapabilities,
  parseHealth,
  parseWhy,
  type Baseline,
  type Capabilities,
  type Health,
  type Why,
} from "@/lib/api";

/**
 * Server-side reads of the backend's public, read-only endpoints, used to
 * render the first view without a loading flash. Each read is optional: when
 * the backend is slow or down the page still renders and the browser retries.
 */

const TIMEOUT_MS = 2500;

function backendOrigin(): string {
  return (process.env.PROOFMODE_API_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
}

async function readJson(path: string): Promise<unknown> {
  try {
    const response = await fetch(`${backendOrigin()}${path}`, {
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

export interface BackendSnapshot {
  baseline: Baseline | null;
  capabilities: Capabilities | null;
  health: Health | null;
  why: Why | null;
}

export async function loadBackendSnapshot(): Promise<BackendSnapshot> {
  const [baseline, capabilities, health, why] = await Promise.all([
    readJson("/baseline.json"),
    readJson("/api/capabilities"),
    readJson("/api/health"),
    readJson("/why.json"),
  ]);
  return {
    baseline: parseBaseline(baseline),
    capabilities: parseCapabilities(capabilities),
    health: parseHealth(health),
    why: parseWhy(why),
  };
}
