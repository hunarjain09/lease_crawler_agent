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
iMessage  ──►  Photon Agent (Bun / spectrum-ts)  ──►  Local Server (Python / FastAPI, uv-managed)
                    ▲                                       │
                    │                                       ├──► Obscura crawler (Rust, sidecar)
                    │                                       │
                    │                                       └──► GMI Inference (api.gmi-serving.com)
                    │                                              ├── Pexiverse (video gen)
                    │                                              └── Claude Sonnet 4.6 (reasoning)
                    │
                    └────────────  responses (text + video URL)
```

### 5.1 Components
| # | Component | Responsibility | Tech / Source |
|---|-----------|----------------|---------------|
| 1 | iMessage surface | User-facing channel | Photon's iMessage provider (Spectrum) — Terminal provider used for local dev |
| 2 | Photon Agent | Conversation state, tool routing, "leak" memory | `spectrum-ts` SDK (Bun/TypeScript). Unified provider API: `app.messages` async iterator, `message.reply()`, `message.react()`, `space.send()` |
| 3 | Local server | HTTP entrypoint invoked by Photon agent tools; orchestrates Obscura + GMI calls | This repo — **Python 3.12 + FastAPI + Uvicorn**, deps via **uv** (`pyproject.toml`, `uv.lock`) |
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

## 6. Repo Layout

```
lease_crawler_agent/
├── server/                  # Python local server (FastAPI, uv-managed)
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── src/lease_crawler/
│   │   ├── main.py          # FastAPI app
│   │   ├── crawler.py       # Obscura wrapper
│   │   ├── inference.py     # GMI / Anthropic SDK client
│   │   ├── models.py        # pydantic schemas
│   │   └── settings.py      # env loading
│   └── tests/
│       ├── unit/            # pure-fn + mocked-deps tests (pytest)
│       └── integration/     # boots FastAPI + real/mocked Obscura + recorded GMI
├── agent/                   # Bun / spectrum-ts agent
│   ├── package.json
│   ├── tsconfig.json
│   ├── src/index.ts         # Spectrum app, tool handlers → server HTTP
│   └── tests/
│       ├── unit/            # bun:test
│       └── integration/     # spawns Terminal provider, hits a stub server
└── PRD.md
```

## 6.1 API Surface (Python server)
- `POST /crawl` → `{ url: string }` → `{ content: string, metadata: {...} }`
- `POST /analyze` → `{ content: string, context: Leak[] }` → `{ leaks: Leak[], summary: string }`
- `POST /walkthrough` → `{ leaks: Leak[] }` → `{ video_url: string }`
- `GET  /health` → `{ ok: true }`

```python
class Leak(BaseModel):
    id: str
    source_url: str
    title: str
    severity: Literal["low", "med", "high"]
    detail: str
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
Every milestone ships with both **unit** and **integration** tests in CI green before it's considered done.

- **M0 — Skeleton:** monorepo layout, `server/` (uv + FastAPI `/health`) and `agent/` (Bun + spectrum-ts hello), `.env.example`, CI running `uv run pytest` and `bun test`.
- **M1 — Obscura wired:** Obscura built locally, `crawler.py` wraps it, `/crawl` live. *Tests:* unit (mocked subprocess), integration (real Obscura against local static HTML).
- **M2 — GMI reasoning path:** `/analyze` calls Claude Sonnet 4.6 via Anthropic SDK pointed at GMI. *Tests:* unit (respx-mocked), integration (recorded VCR cassette of Avalon fixture).
- **M3 — Spectrum agent (Terminal):** message loop in TUI calls `/crawl` + `/analyze`, accumulates leaks. *Tests:* unit (reducers/classifiers), integration (Terminal provider scripted against stub server).
- **M4 — iMessage provider live:** swap Terminal → iMessage provider, end-to-end round-trip. *Tests:* manual E2E checklist; integration tests stay on Terminal provider.
- **M5 — Pexiverse `/walkthrough`:** generate video from leak list, return URL via iMessage. *Tests:* unit + integration with Pexiverse cassette.
- **M6 — Second GMI model integrated:** once role is defined.
- **M7 — Polish:** retries, structured logs, simple sqlite for leak persistence.

## 10. Risks
- **iMessage delivery reliability** — Apple has no official API; bridges drift.
- **Pexiverse latency** — video gen may exceed iMessage UX patience; may need async + push.
- **Crawler blocked** — listing sites often gate scrapers; may need headless browser or proxies.
- **Photon ↔ local exposure** — tunneling adds an external dependency.

## 11. Testing Strategy

Every component is tested at two levels: **atomic unit tests** (pure logic, deps mocked) and **integration tests** (real wiring across at least one boundary). CI gates merge on both.

### 11.1 Server (Python / pytest, run via uv)
- **Tooling:** `pytest`, `pytest-asyncio`, `httpx.AsyncClient` (FastAPI in-process), `respx` (mock httpx outbound), `pytest-recording` / VCR for replayable GMI cassettes.
- **Layout:** `server/tests/unit/` and `server/tests/integration/`.
- **Unit (atomic):**
  - `crawler.py`: parse Obscura stdout/JSON, error mapping, timeout handling — Obscura subprocess monkeypatched.
  - `inference.py`: prompt construction, response parsing into `Leak[]` — Anthropic client mocked via `respx`.
  - `models.py`: pydantic validation edge cases.
  - Each FastAPI route: handler-level test with all deps overridden via `app.dependency_overrides`.
- **Integration:**
  - `test_crawl_integration.py`: spawns real `obscura serve` in a fixture, hits a static local HTML server (no internet), asserts content extraction.
  - `test_analyze_integration.py`: real FastAPI client + recorded GMI cassette → asserts non-empty `leaks[]` against the Avalon fixture (§11.4).
  - `test_walkthrough_integration.py`: same pattern, Pexiverse cassette.
- **Run:** `uv run pytest -m unit` / `uv run pytest -m integration`.

### 11.2 Agent (Bun / `bun:test`)
- **Tooling:** `bun:test`, `msw` or `bun`'s built-in fetch mocking, Spectrum's Terminal provider for headless runs.
- **Layout:** `agent/tests/unit/` and `agent/tests/integration/`.
- **Unit (atomic):**
  - Tool argument builders (URL → `/crawl` payload, leaks → `/walkthrough` payload).
  - Message classifier (URL vs. "make walkthrough" vs. chitchat).
  - Leak-state reducer (merging new leaks into context without dupes).
- **Integration:**
  - `terminal-roundtrip.test.ts`: drives Spectrum's Terminal provider with a scripted input, points the agent at a stub server (FastAPI test app or a Bun mock), asserts the assistant's reply text.
- **Run:** `bun test`.

### 11.3 End-to-end
- **`e2e/`** (top-level, optional in CI, gated by `RUN_E2E=1`): boots the Python server + Obscura sidecar + Spectrum agent, scripts a Terminal session against the canonical Avalon URL, asserts that the reply mentions price, lease length, and at least one fee-related leak.

### 11.4 Canonical test URL & fixture
`https://www.avaloncommunities.com/california/sunnyvale-apartments/avalon-silicon-valley/`

Captured snapshot (from screenshot, 2026-05-02) — used as the golden fixture for `/analyze`:
- Multiple 1bd/1ba/720 sqft units (e.g. `006-1117`, `007-1149`, `003-3045`).
- Base rent **$3,415 / 14-mo lease**.
- Furnished option starting at **$4,696**.
- Availability **May 03**.
- "Available to Tour" / "Virtual tour" indicators.
- 36 results matched the default search.

Server integration test asserts at minimum: extracted unit count > 0, base rent parsed as `3415`, lease term `14`, currency `USD`, and a "furnished premium" leak surfaced ($4,696 − $3,415 = $1,281/mo).

### 11.5 Smoke-test sequence per milestone
- **M1:** `obscura fetch <url> --dump html` returns rendered listing markup containing a `$3,415` token (proves JS executed, not shell HTML).
- **M2:** `POST /analyze` over the crawled content returns a non-empty `leaks[]` referencing fees, lease length, and the furnished premium.
- **M3+:** Send the URL via Terminal/iMessage → agent replies with a leak summary including the rent and lease term.

---

*Open TBDs: Pexiverse endpoint shape, second GMI model, iMessage provider deployment story, "Claude 4.7" vs 4.6 confirmation.*
