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
| 1 | iMessage bridge | Surface for user input/output | macOS Messages + relay (TBD: BlueBubbles / sendblue / AppleScript) |
| 2 | Photon Agent | Conversation state, tool routing, "leak" memory | Photon API — **Docs: TBD** |
| 3 | Local server | HTTP entrypoint from Photon; orchestrates crawler + GMI calls | This repo (`lease_crawler_agent`) |
| 4 | Crawler | Fetch + parse target lease pages | GitHub repo — **link: TBD** |
| 5 | GMI inference | Hosts Pexiverse + Claude 4.7 | GMI endpoint — **base URL / auth: TBD** |
| 6 | Pexiverse | Generates a video walkthrough of discussed leaks | Hosted on GMI |
| 7 | Second model | TBD purpose (image? structured extraction?) — **Name & purpose: TBD** | Hosted on GMI |

### 5.2 Request Flows

**Flow A — Crawl & analyze a URL**
1. User texts URL via iMessage.
2. iMessage bridge → Photon agent.
3. Photon calls local server tool: `POST /crawl { url }`.
4. Local server invokes crawler → returns extracted page content.
5. Local server calls GMI Claude 4.7 with the page content + current leak context.
6. Claude 4.7 returns updated leak list + summary.
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

## 7. Open Questions / TBDs
1. **Photon docs** — auth, tool registration format, webhook vs. long-poll, max payload size.
2. **iMessage bridge** — which bridge does Photon support natively? Or do we self-host one and forward to Photon?
3. **Crawler repo** — URL, language, invocation surface (CLI vs. library), JS rendering or static only.
4. **GMI access** — base URL, auth scheme (API key / OIDC), request/response shapes for Pexiverse and Claude 4.7.
5. **Second GMI model** — name and role in the pipeline.
6. **Pexiverse I/O** — input format (text? structured leaks?), output (URL vs. raw mp4), generation latency, async job vs. sync.
7. **Context size** — does Photon hold the full leak list, or does the local server need its own store?
8. **Local exposure** — Photon needs to reach the local server: ngrok / Cloudflare Tunnel / Tailscale Funnel?

## 8. Milestones
- **M0 — Skeleton (this repo):** PRD, project structure, `.env.example`, healthcheck.
- **M1 — Crawler integration:** vendor the crawler repo, wire `/crawl`.
- **M2 — GMI Claude 4.7 path:** wire `/analyze`, end-to-end from a curl call.
- **M3 — Photon agent live:** tool registration, iMessage round-trip working with text only.
- **M4 — Pexiverse path:** `/walkthrough` returning a playable video link via iMessage.
- **M5 — Second GMI model integrated:** once role is defined.
- **M6 — Polish:** error handling, retries, basic observability (request log).

## 9. Risks
- **iMessage delivery reliability** — Apple has no official API; bridges drift.
- **Pexiverse latency** — video gen may exceed iMessage UX patience; may need async + push.
- **Crawler blocked** — listing sites often gate scrapers; may need headless browser or proxies.
- **Photon ↔ local exposure** — tunneling adds an external dependency.

## 10. Verification Plan
- Unit: each local server endpoint with mocked GMI + crawler.
- Integration: `curl` against the running local server reproduces both flows.
- E2E: iMessage in → video link out, with at least one real listing URL.

---

*This PRD has placeholders ("TBD") for Photon docs, the crawler repo link, the second GMI model, and GMI auth details. Send those over and I'll fold them in.*
