# PRD: Lease Crawler Agent

**Status:** Draft v0
**Owner:** Hunar Jain
**Last updated:** 2026-05-02

---

## 1. Summary
A conversational agent that, triggered from iMessage, crawls leasing-related web pages, runs inference on a self-hosted GMI stack, and returns a generated video walkthrough of "leaks" (lease findings/gaps) discussed in the conversation. Photon orchestrates the dialogue; a local server runs the crawler and brokers calls to GMI-hosted models.

## 2. Goals
- Accept natural-language input from iMessage and route it through a Photon agent.
- Maintain conversation context (the running list of "leaks") inside the Photon agent.
- On request, generate a video walkthrough of all discussed leaks via **Pexiverse** on GMI.
- Crawl target web pages on demand and feed the extracted content back through GMI inference (using Claude 4.7 as the reasoning model) to enrich the leak list.
- End-to-end runnable locally, with the GMI inference layer remote.

## 3. Non-Goals
- Productionizing iMessage delivery beyond a local bridge.
- Multi-tenant / multi-user support.
- Persisting crawl history beyond the current Photon conversation context.
- Authentication / billing.

## 4. Users & Use Cases
- **Primary user:** Hunar, evaluating leases.
- **Use case 1:** Send a property/listing URL via iMessage → agent crawls it → returns a summary of red flags ("leaks").
- **Use case 2:** After several listings have been discussed, ask the agent to "make me a walkthrough" → Pexiverse generates a video covering each leak.

## 5. System Architecture

```
iMessage  ──►  Photon Agent (cloud)  ──►  Local Server (FastAPI/Express)
                    ▲                          │
                    │                          ├──► Crawler (GitHub: TBD)
                    │                          │
                    │                          └──► GMI Inference Endpoint
                    │                                 ├── Pexiverse (video gen)
                    │                                 └── Claude 4.7 (reasoning)
                    │
                    └────────────  responses (text + video URL)
```

### 5.1 Components
| # | Component | Responsibility | Tech / Source |
|---|-----------|----------------|---------------|
| 1 | iMessage surface | User-facing channel | Photon's iMessage provider (Spectrum) — Terminal provider used for local dev |
| 2 | Photon Agent | Conversation state, tool routing, "leak" memory | `spectrum-ts` SDK (Bun/TypeScript). Unified provider API: `app.messages` async iterator, `message.reply()`, `message.react()`, `space.send()` |
| 3 | Local server | HTTP entrypoint invoked by Photon agent tools; orchestrates Obscura + GMI calls | This repo — Bun + Hono (or Express) |
| 4 | Crawler | Fetch + render lease pages with JS execution | **Obscura** (`h4ckf0r0day/obscura`) — Rust headless browser, CDP-compatible. Commands: `obscura serve`, `obscura fetch <URL>`, `obscura scrape <URL...>`. Supports `--eval`, `--dump`, `--wait-until`, `--stealth` |
| 5 | GMI inference | Anthropic-compatible inference endpoint | `https://api.gmi-serving.com`, auth via `ANTHROPIC_AUTH_TOKEN` |
| 6 | Reasoning model | Extract & rank "leaks" from crawled content | `anthropic/claude-sonnet-4.6` (or `opus-4.6` for harder cases) on GMI. *Note: original spec said "Claude 4.7"; GMI currently exposes 4.6 — confirm if 4.7 is needed.* |
| 7 | Pexiverse | Video walkthrough generation from leak list | Hosted on GMI — **endpoint / request shape: TBD** |
| 8 | Second GMI model | TBD purpose — **Name & role: TBD** | Hosted on GMI |

### 5.2 Request Flows

**Flow A — Crawl & analyze a URL**
1. User texts URL via iMessage.
2. iMessage bridge → Photon agent.
3. Photon agent (in its message handler) calls local server tool: `POST /crawl { url }`.
4. Local server shells out to `obscura fetch <url> --dump html` (or hits a long-running `obscura serve` over CDP) → returns rendered content.
5. Local server calls GMI Claude Sonnet 4.6 with the page content + current leak context.
6. Claude returns updated leak list + summary.
7. Local server responds to Photon → Photon replies via iMessage.

**Flow B — Generate walkthrough video**
1. User asks "make the walkthrough".
2. Photon calls local server tool: `POST /walkthrough { leaks[] }` (Photon supplies leak list from its context).
3. Local server calls GMI Pexiverse with the leak list.
4. Pexiverse returns a video URL (or binary).
5. Local server returns URL to Photon → iMessage delivers link/preview.

## 6. API Surface (local server)
*Working contracts — to be finalized once Photon tool schema is known.*

- `POST /crawl` → `{ url: string }` → `{ content: string, metadata: {...} }`
- `POST /analyze` → `{ content: string, context: Leak[] }` → `{ leaks: Leak[], summary: string }`
- `POST /walkthrough` → `{ leaks: Leak[] }` → `{ videoUrl: string }`
- `GET  /health` → `{ ok: true }`

```ts
type Leak = { id: string; source_url: string; title: string; severity: "low"|"med"|"high"; detail: string }
```

## 7. Stack Decisions (resolved)
- **Agent runtime:** `spectrum-ts` on Bun. Bootstrap pattern from Photon docs:
  ```
  bun add spectrum-ts@latest
  cd examples/basic && bun run start
  ```
  Local dev uses Spectrum's **Terminal provider**; production swaps to the iMessage provider — same code.
- **Crawler:** Obscura, run as a sidecar (`obscura serve`) so the Bun server connects via CDP, or one-shot `obscura fetch` per request. Build requires Rust 1.75+; first build compiles V8.
- **GMI / inference auth:** Anthropic-SDK-compatible. Local server reads:
  ```
  ANTHROPIC_BASE_URL=https://api.gmi-serving.com
  ANTHROPIC_AUTH_TOKEN=<gmi key>
  ANTHROPIC_MODEL=anthropic/claude-sonnet-4.6
  ```
  Calls go through `@anthropic-ai/sdk` pointed at the GMI base URL.

## 8. Open Questions / TBDs
1. **Pexiverse on GMI** — endpoint path, request/response schema, sync vs. async job, output format.
2. **Second GMI model** — name and role in the pipeline.
3. **iMessage delivery in production** — does Spectrum's iMessage provider need a Mac relay (BlueBubbles-style) or does Photon host it?
4. **Local exposure** — if Photon production runs in cloud, the local server needs a tunnel: ngrok / Cloudflare Tunnel / Tailscale Funnel.
5. **"Claude 4.7" vs 4.6** — GMI currently exposes 4.6 family; confirm whether 4.7 is required (would block on GMI availability).
6. **Leak memory ownership** — keep in Spectrum agent state, or persist server-side (sqlite) to survive restarts?
7. **Anti-bot** — listing sites may need Obscura's `--stealth` and/or a proxy.

## 9. Milestones
- **M0 — Skeleton (this repo):** PRD, Bun project (`package.json`, `tsconfig.json`), `.env.example` with GMI vars, `/health`.
- **M1 — Obscura wired:** clone & build Obscura, run `obscura serve`, expose `/crawl` from local server.
- **M2 — GMI reasoning path:** `/analyze` calls Claude Sonnet 4.6 via Anthropic SDK pointed at GMI; verified with `curl`.
- **M3 — Spectrum agent (Terminal):** message loop in TUI, calls `/crawl` + `/analyze` as tools, accumulates leaks in agent state.
- **M4 — iMessage provider live:** swap Terminal → iMessage provider, end-to-end round-trip.
- **M5 — Pexiverse `/walkthrough`:** generate video from leak list, return URL via iMessage.
- **M6 — Second GMI model integrated:** once role is defined.
- **M7 — Polish:** retries, structured logs, simple sqlite for leak persistence.

## 10. Risks
- **iMessage delivery reliability** — Apple has no official API; bridges drift.
- **Pexiverse latency** — video gen may exceed iMessage UX patience; may need async + push.
- **Crawler blocked** — listing sites often gate scrapers; may need headless browser or proxies.
- **Photon ↔ local exposure** — tunneling adds an external dependency.

## 11. Verification Plan
- Unit: each local server endpoint with mocked GMI + crawler.
- Integration: `curl` against the running local server reproduces both flows.
- E2E: iMessage in → video link out, with at least one real listing URL.

---

*Open TBDs: Pexiverse endpoint shape, second GMI model, iMessage provider deployment story, "Claude 4.7" vs 4.6 confirmation.*
