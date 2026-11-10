# ProofMode web

The Next.js front end for ProofMode, a fraud check for suspicious messages. A person drops,
pastes or chooses a screenshot of a message (or pastes its text), and each claim in it is judged
against general scam red flags from FTC guidance or against the organisation's own official
facts, with a quoted fact behind every verdict.

This app is only the user interface. The Python FastAPI service in the parent directory stays the
single engine: it calls the model, checks every quote, and computes the verdict. No API key is
ever given to this app.

## How it fits together

```
browser  ->  Next.js app (this directory)  ->  ProofMode backend (FastAPI)  ->  OpenRouter
             same-origin paths only            holds the OpenRouter key
```

The browser only calls same-origin paths. `next.config.ts` rewrites these to the backend:

| Path | Backend route |
|---|---|
| `/api/:path*` | `POST /api/review`, `GET /api/health`, `GET /api/capabilities` |
| `/baseline.json` | The general scam red-flag rules and their sources |
| `/why.json` | The figures in "Why this matters", each with its source |
| `/sample.png` | The fictional Tidewater Cloud example screenshot |

The page itself is a Server Component that reads `baseline.json`, `why.json`, `/api/health` and
`/api/capabilities` from the backend while rendering, with a 2.5 second limit. If the backend
does not answer in time the page still renders, and the browser fetches the rules and the
capabilities itself.

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `PROOFMODE_API_URL` | `http://127.0.0.1:8000` | Origin of the ProofMode backend. Server side only; never sent to the browser. Set it for both `npm run build` and `npm run start`, because rewrites are resolved from the configuration |

Copy `.env.example` to `.env.local` to set it for local work.

## Run it locally

Start the backend from the repository root. Demo mode needs no key:

```bash
PROOFMODE_MOCK=1 uv run python -m proofmode          # canned output on port 8000
# or, for live checks:
OPENROUTER_API_KEY=sk-or-... uv run python -m proofmode
```

Then, in this directory:

```bash
npm install
npm run dev                      # http://localhost:3000, forwards to http://127.0.0.1:8000
```

Production mode against a backend on another port:

```bash
PROOFMODE_API_URL=http://127.0.0.1:8780 npm run build
PROOFMODE_API_URL=http://127.0.0.1:8780 npm run start -- -p 3100
```

## Checks

```bash
npm run lint         # ESLint
npx tsc --noEmit     # strict TypeScript
npm run test         # Vitest and Testing Library on happy-dom
npm run build        # production build
```

The tests cover the API client's error mapping, the verdict banner for each verdict, the claim
card (including that markup in model text is shown as text), the one-click example flow with
`fetch` mocked, pasted text, the investigation flow and timeline, and the facts list.

## Deploy the front end separately

1. Host the backend somewhere reachable over https and give it `OPENROUTER_API_KEY`. See the
   repository README for its settings.
2. Deploy this directory to any host that runs Next.js with a Node server (`npm run build`, then
   `npm run start`). Set `PROOFMODE_API_URL` to the backend's https origin, for example
   `https://proofmode-api.example.org`, for both the build and the running server.
3. Nothing else is needed. The browser never talks to the backend directly, so the backend needs
   no cross-origin settings.

Things to know when the two are deployed apart:

- **Rate limits.** The backend limits requests per client address. Behind this app every request
  arrives from the front end's server, so run the backend with `PROOFMODE_TRUST_PROXY` set as its
  README describes if the forwarded client address should be used, and check that your host
  forwards it.
- **Timeouts.** An investigation can take up to 120 seconds. The rewrite proxy waits 130 seconds
  (`experimental.proxyTimeout` in `next.config.ts`). A host with a shorter request limit will cut
  investigations off; the page then reports that the server could not be reached.
- **Upload size.** Screenshots up to 8 MB are forwarded as they are. A host with a smaller request
  body limit will reject larger screenshots before they reach the backend.
- **Static export is not supported.** Pages are rendered per request so that each response can
  carry a fresh Content-Security-Policy nonce.

## Security

- `src/proxy.ts` sets a nonce-based Content-Security-Policy on every page: scripts need the
  nonce (`'strict-dynamic'`), styles need the nonce, connections and fonts are same-origin only,
  images are same-origin plus local `blob:` previews, and framing is refused. In development the
  policy also allows what the dev tooling needs.
- `next.config.ts` adds `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
  `X-Frame-Options: DENY`, `Cross-Origin-Opener-Policy: same-origin` and a `Permissions-Policy`
  that turns off device features.
- Everything from the model and the backend is rendered as React text. Nothing is injected as
  HTML, and no component sets an inline style.
- A URL from the backend becomes a link only when it parses as `https`.
- Fonts (Newsreader, IBM Plex Sans, IBM Plex Mono) are downloaded at build time by `next/font`
  and served from this app, so the browser makes no request to a font host.

## Layout of the code

```
src/app/            layout, the page (server component), global styles and theme tokens
src/proxy.ts        Content-Security-Policy with a per-request nonce
src/lib/api.ts      typed API client, reply parsing, error messages
src/lib/wording.ts  wording for each evidence mode, the example facts, fact parsing
src/lib/backend.ts  server-side reads of the backend's public endpoints
src/components/tool/      the interactive check (one client component tree)
src/components/sections/  the static sections below the tool (server components)
```
