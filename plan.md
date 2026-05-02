# Implementation Plan: Lease Crawler Agent

> Self-contained plan for a fresh Claude (or human) to implement this project end-to-end. Read this top-to-bottom before writing code. Companion document: [`PRD.md`](./PRD.md) (product context, not required to start).

---

## 0. What you're building

A conversational agent that:
1. Receives a property/listing URL from the user (locally via a TUI, eventually via iMessage).
2. Crawls the rendered page (JS executed) using **Obscura**, a Rust headless browser.
3. Sends crawled content to **GMI Cloud** (Anthropic-SDK-compatible) running **Claude Sonnet 4.6** to extract "leaks" — lease red flags (rent, lease term, fees, parking, utilities, etc.).
4. Maintains the running list of leaks in agent state.
5. On request, generates a **video walkthrough** of the leaks via **Pexiverse** on GMI.

User: a single person evaluating leases. No multi-tenant, no auth, no billing.

---

## 1. Stack (locked)

| Layer | Tech |
|---|---|
| Agent | **Bun** + `spectrum-ts` (TypeScript). Terminal provider for dev, iMessage in prod. |
| Local server | **Python 3.12** + **FastAPI** + **Uvicorn**, deps via **uv** (`pyproject.toml`, `uv.lock`). |
| Crawler | **Obscura** (`https://github.com/h4ckf0r0day/obscura`) — Rust, CDP, no Chrome dep. |
| Inference | **GMI Cloud** at `https://api.gmi-serving.com`, Anthropic-compatible. Models: `anthropic/claude-sonnet-4.6` (default), `anthropic/claude-opus-4.6` (hard cases), `anthropic/claude-haiku-4.6` (cheap). |
| Video gen | **Pexiverse** on GMI — endpoint shape **TBD**. |
| Tests | `pytest` (server, run via `uv run pytest`) + `bun:test` (agent). |

---

## 2. Repo layout

```
lease_crawler_agent/
├── server/                       # Python local server
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── src/lease_crawler/
│   │   ├── __init__.py
│   │   ├── main.py               # FastAPI app, route registration
│   │   ├── crawler.py            # Obscura subprocess wrapper
│   │   ├── inference.py          # GMI / Anthropic SDK client
│   │   ├── models.py             # pydantic schemas (Leak, requests, responses)
│   │   └── settings.py           # env loading (pydantic-settings)
│   └── tests/
│       ├── conftest.py
│       ├── unit/
│       └── integration/
├── agent/                        # Bun / spectrum-ts agent
│   ├── package.json
│   ├── tsconfig.json
│   ├── src/
│   │   ├── index.ts              # Spectrum app entry
│   │   ├── tools.ts              # crawl / analyze / walkthrough HTTP clients
│   │   ├── classifier.ts         # message → intent
│   │   └── state.ts              # leak reducer
│   └── tests/
│       ├── unit/
│       └── integration/
├── e2e/                          # full-stack tests, gated by RUN_E2E=1
├── .env.example
├── PRD.md
├── plan.md                       # this file
└── README.md
```

---

## 3. Environment

Copy `.env.example` → `.env`. The server reads env via `pydantic-settings`.

```
# GMI Cloud (Anthropic-compatible)
ANTHROPIC_BASE_URL=https://api.gmi-serving.com
ANTHROPIC_AUTH_TOKEN=<your GMI key from console.gmicloud.ai>
ANTHROPIC_MODEL=anthropic/claude-sonnet-4.6
API_TIMEOUT_MS=600000

# Pexiverse (TBD — fill in once endpoint is known)
PEXIVERSE_BASE_URL=
PEXIVERSE_API_KEY=

# Obscura
OBSCURA_BIN=/usr/local/bin/obscura      # or absolute path to built binary
OBSCURA_CDP_URL=ws://127.0.0.1:9222     # if using `obscura serve`

# Local server
SERVER_HOST=127.0.0.1
SERVER_PORT=8000

# Agent
SERVER_BASE_URL=http://127.0.0.1:8000
```

---

## 4. Milestones (do these in order)

Each milestone is **not done** until both unit and integration tests are green.

### M0 — Skeleton
**Goal:** repo compiles and runs `/health` + a TUI hello-world; CI green.

Server:
```bash
cd server
uv init --package lease_crawler
uv add fastapi uvicorn[standard] httpx pydantic pydantic-settings anthropic
uv add --group dev pytest pytest-asyncio respx pytest-recording
```
Implement `GET /health` → `{"ok": true}`.

Agent:
```bash
cd agent
bun init -y
bun add spectrum-ts@latest
```
Minimal Spectrum app using the Terminal provider that echoes input.

CI:
- GitHub Actions workflow: matrix runs `uv run pytest` in `server/` and `bun test` in `agent/`.

**Tests:**
- Unit: `test_health.py` hits `/health` via `httpx.AsyncClient(app=app)`.
- Unit: `agent/tests/unit/echo.test.ts` asserts the echo handler.

### M1 — Obscura wired
**Goal:** `POST /crawl { url }` returns rendered HTML / extracted text.

Build Obscura locally:
```bash
git clone https://github.com/h4ckf0r0day/obscura.git
cd obscura && cargo build --release
# binary at target/release/obscura
```

Implement `crawler.py`:
- Two modes selectable by env: one-shot (`obscura fetch <url> --dump html --wait-until=load --stealth`) and CDP (`obscura serve` sidecar, connect via `chrome-remote-interface`-style client).
- Start with one-shot subprocess (simpler). Capture stdout, parse, return `{ content, metadata: { url, status, fetched_at } }`.
- Surface clean errors: timeout, non-zero exit, empty body.

**Tests:**
- Unit (`tests/unit/test_crawler.py`): monkeypatch `subprocess.run`, assert command construction + parsing of fixture stdout.
- Integration (`tests/integration/test_crawl_integration.py`): start a local `http.server` serving a static HTML file with a `<script>` that injects `$3,415` after load; run real Obscura against it; assert the rendered output contains the post-JS token.

### M2 — GMI reasoning path
**Goal:** `POST /analyze { content, context }` returns `{ leaks[], summary }`.

Implement `inference.py`:
- Use the official `anthropic` Python SDK. Construct the client with `base_url=settings.ANTHROPIC_BASE_URL` and `auth_token=settings.ANTHROPIC_AUTH_TOKEN`.
- Use **prompt caching** on the system prompt and the leak schema (long-lived, reused across calls).
- System prompt teaches the model what a "leak" is: anything in the listing that affects total cost of occupancy, lease flexibility, or quality of life. Output strict JSON matching the `Leak` schema.
- Use tool/function-calling style (response_format JSON) with retries on parse failure.

`Leak` schema (`models.py`):
```python
class Leak(BaseModel):
    id: str                              # stable hash of (source_url, title)
    source_url: str
    title: str
    severity: Literal["low", "med", "high"]
    detail: str
    evidence: str | None = None          # quoted snippet from page
```

**Tests:**
- Unit: prompt-builder snapshot test; response-parser handles malformed JSON with one retry.
- Unit: `respx`-mock the Anthropic endpoint, assert `Leak[]` round-trips.
- Integration: VCR cassette captured once against real GMI using the Avalon fixture (§7); replay in CI. Asserts at minimum:
  - `len(leaks) >= 3`
  - some leak title matches `/furnished/i` with severity `med` or `high`
  - some leak title matches `/lease.term|14.month/i`

### M3 — Spectrum agent (Terminal)
**Goal:** TUI session: paste a URL → agent calls `/crawl` then `/analyze` → replies with summary; ask "make walkthrough" → 501 stub for now.

Agent code:
- `tools.ts`: typed wrappers `crawl(url)`, `analyze(content, context)`, `walkthrough(leaks)` hitting `SERVER_BASE_URL`.
- `classifier.ts`: pure function `classify(text) → { kind: "url"|"walkthrough"|"chat", url?: string }`. URL detection via regex; walkthrough via keyword set (`walkthrough|video|recap`).
- `state.ts`: `addLeaks(state, newLeaks)` deduplicates by `id`.
- `index.ts`: Spectrum loop:
  ```ts
  for await (const [space, message] of app.messages) {
    const intent = classify(message.text);
    if (intent.kind === "url") {
      const { content } = await crawl(intent.url);
      const { leaks, summary } = await analyze(content, state.leaks);
      state.leaks = addLeaks(state.leaks, leaks);
      await message.reply(summary);
    } else if (intent.kind === "walkthrough") {
      const { videoUrl } = await walkthrough(state.leaks);
      await message.reply(videoUrl);
    } else {
      await message.reply("Send me a listing URL or ask for a walkthrough.");
    }
  }
  ```

**Tests:**
- Unit: classifier truth table; reducer dedupes.
- Integration (`agent/tests/integration/terminal-roundtrip.test.ts`): spawn Spectrum with the Terminal provider, point `SERVER_BASE_URL` at a Bun-hosted stub returning canned `/crawl` and `/analyze` responses; script an input line; assert the printed reply.

### M4 — iMessage provider
**Goal:** swap Terminal → iMessage provider via Spectrum config; manual E2E from a real Apple device.

No code changes inside the message loop. Document the iMessage provider setup steps once Photon docs clarify the bridge requirements (Mac relay vs. hosted). Keep integration tests on Terminal.

### M5 — Pexiverse `/walkthrough`
**Goal:** real video URL returned to the agent.

**Blocked** until the Pexiverse endpoint shape is documented. Implement against the spec when it lands. Treat it as a possibly-async job: poll or webhook. Add a cassette for integration.

### M6 — Second GMI model
Add once role is defined.

### M7 — Polish
- Retries (`tenacity`) on GMI 5xx.
- Structured logs (`structlog`).
- sqlite persistence of leaks (`server/leaks.db`) so restarts don't lose state.

---

## 5. API contracts

```
GET  /health              → {"ok": true}

POST /crawl
  body: {"url": "<string>"}
  200:  {"content": "<rendered html or text>", "metadata": {"url": "...", "status": 200, "fetched_at": "<iso8601>"}}
  4xx:  {"error": "<message>"}

POST /analyze
  body: {"content": "<string>", "context": [Leak, ...]}
  200:  {"leaks": [Leak, ...], "summary": "<string>"}

POST /walkthrough
  body: {"leaks": [Leak, ...]}
  200:  {"video_url": "<https url>"}
```

---

## 6. Testing rules (apply across the board)

- **Unit tests are atomic.** No network, no subprocesses, no filesystem outside `tmp_path`. All external deps are mocked or injected.
- **Integration tests cross exactly one boundary** (real Obscura *or* real FastAPI client *or* real Anthropic via cassette — not all three at once).
- **Cassettes live in** `server/tests/integration/cassettes/`. Re-record only with explicit flag (`PYTEST_RECORD=1`).
- **No test reaches the real internet in CI.** Static local HTTP server for Obscura tests; cassettes for GMI.
- **E2E** (`e2e/`) is the only place real services are allowed; it's opt-in via `RUN_E2E=1`.
- Every PR shows: unit count, integration count, both green.

---

## 7. Canonical fixture: Avalon Silicon Valley

URL: `https://www.avaloncommunities.com/california/sunnyvale-apartments/avalon-silicon-valley/`

Captured 2026-05-02 from the rendered listing page:

| Field | Value |
|---|---|
| Sample units | `006-1117`, `007-1149`, `003-3045` (1bd / 1ba / 720 sqft) |
| Base rent | **$3,415 / 14-mo lease** |
| Furnished option | starting at **$4,696** (premium ≈ $1,281/mo) |
| Availability | **May 03** |
| Total results in default search | 36 |
| Indicators present | "Available to Tour", "Virtual tour" |

Save the rendered HTML once into `server/tests/integration/fixtures/avalon_silicon_valley.html` and use it as the input for `/analyze` cassette tests (so we don't re-crawl on every test run).

Required `/analyze` assertions on this fixture:
1. At least one leak whose title matches `/furnished/i` and whose `detail` references `$4,696` or the premium amount.
2. At least one leak referencing the **14-month lease term** (non-standard length is itself a leak).
3. Base rent **$3,415** appears in `summary`.

---

## 8. Open TBDs (don't block on these)

1. **Pexiverse**: endpoint, request schema, sync vs. async, output format (mp4 URL? signed URL? raw bytes?). Implement M5 only after this is documented.
2. **Second GMI model**: name + role.
3. **iMessage provider deployment**: Mac relay vs. hosted bridge.
4. **Local exposure**: if Photon prod runs in cloud, decide tunnel (ngrok / Cloudflare Tunnel / Tailscale Funnel).
5. **"Claude 4.7" vs 4.6**: original spec said 4.7, GMI exposes 4.6. Default to 4.6 (`anthropic/claude-sonnet-4.6`); upgrade if/when 4.7 ships on GMI.
6. **Anti-bot**: if Avalon (or others) block Obscura, add `--stealth` and consider a residential proxy.

---

## 9. Definition of done (whole project)

- `uv run pytest` in `server/` is green; coverage ≥ 80% on `crawler.py`, `inference.py`, route handlers.
- `bun test` in `agent/` is green.
- `RUN_E2E=1 ./scripts/e2e.sh` against the Avalon URL produces a leak summary mentioning rent, lease term, and furnished premium, and (post-M5) a playable video URL.
- README documents one-command setup: `make dev` boots Obscura sidecar, the FastAPI server, and the Spectrum Terminal agent.
