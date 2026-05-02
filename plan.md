# Implementation Plan: Lease Crawler Agent

> Self-contained plan for a fresh Claude (or human) to implement this project end-to-end. Read this top-to-bottom before writing code. Companion document: [`PRD.md`](./PRD.md) (product context, not required to start).

---

## 0. What you're building

**Core flow (text summary):**
```
iMessage  →  Photon (spectrum-ts)  →  Local server (Python + Obscura)
                  ▲                          │
                  │                          └──►  GMI Cloud (Claude Opus)
                  │                                       │
                  └────────────  text summary  ◄──────────┘
```

A conversational agent that:
1. Receives a property/listing URL from the user (Terminal provider in dev, iMessage in prod).
2. Crawls the rendered page (JS executed) using **Obscura**, a Rust headless browser.
3. Sends crawled content to **GMI Cloud** running **Claude Opus 4.7** (`anthropic/claude-opus-4.7`, confirmed in account catalog) to extract "leaks" — lease red flags (rent, lease term, fees, parking, utilities, etc.) — and produce a summary.
4. Maintains the running list of leaks in agent state.
5. Replies to the user with the summary on the same channel.

**Follow-up (not blocking core):** generate a Pixverse video walkthrough of the apartments discussed. Detailed in the *Follow-up milestones* section near the bottom — implement only after the core text loop ships and is stable.

User: a single person evaluating leases. No multi-tenant, no auth, no billing.

---

## 1. Stack (locked)

| Layer | Tech |
|---|---|
| Agent | **Node 20+** + `spectrum-ts` (TypeScript), deps via **pnpm**. Terminal provider for dev, iMessage in prod. |
| Local server | **Python 3.12** + **FastAPI** + **Uvicorn**, deps via **uv** (`pyproject.toml`, `uv.lock`). |
| Crawler | **Obscura** (`https://github.com/h4ckf0r0day/obscura`) — Rust, CDP, no Chrome dep. |
| Reasoning LLM | **GMI Serverless** — OpenAI-compatible. Base `https://api.gmi-serving.com/v1`, bearer auth. Model `anthropic/claude-opus-4.7` (verified present in account catalog). Pricing tier 0: $4.50 / $22.50 per 1M tokens (prompt / completion); 409,600-token context. |
| Video gen *(follow-up)* | **Pixverse via GMI Video API** (request-queue, async). Base `https://console.gmicloud.ai/api/v1/ie/requestqueue/apikey`. Model `pixverse-v5.6-t2v` (text-to-video). Alternatives in catalog: `pixverse-v5.6-i2v` (image-to-video), `pixverse-v5.6-transition`. Off the critical path. |
| Tests | `pytest` (server, run via `uv run pytest`) + `vitest` (agent). |

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
├── agent/                        # Node + pnpm / spectrum-ts agent
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
# GMI Serverless (OpenAI-compatible LLM)
GMI_API_KEY=<your GMI key from console.gmicloud.ai>
GMI_LLM_BASE_URL=https://api.gmi-serving.com/v1
GMI_LLM_MODEL=anthropic/claude-opus-4.6   # upgrade to claude-opus-4-7 when GMI exposes it

# GMI Video API (Pixverse — async request queue)
GMI_VIDEO_BASE_URL=https://console.gmicloud.ai/api/v1/ie/requestqueue/apikey
GMI_VIDEO_MODEL=Pixverse
# GMI_ORG_ID=                              # optional, sent as X-Organization-ID

# Spectrum (Photon) — only needed for non-Terminal providers (iMessage, etc.)
# Get these from the Photon Project Page (project id + API key/secret)
SPECTRUM_PROJECT_ID=
SPECTRUM_PROJECT_SECRET=

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
uv add fastapi uvicorn[standard] httpx pydantic pydantic-settings openai tenacity
uv add --group dev pytest pytest-asyncio respx pytest-recording
```
We use the `openai` SDK (not `anthropic`) because GMI's serverless `/chat/completions` is OpenAI-compatible. Point it at GMI:
```python
from openai import OpenAI
client = OpenAI(base_url=settings.GMI_LLM_BASE_URL, api_key=settings.GMI_API_KEY)
```
Implement `GET /health` → `{"ok": true}`.

Agent (Node 20+, pnpm):
```bash
cd agent
pnpm init
pnpm add spectrum-ts
pnpm add -D typescript tsx vitest @types/node
```
Minimal Spectrum app using the Terminal provider (no project credentials needed):

```ts
import { Spectrum, terminal } from "spectrum-ts";

const app = await Spectrum({
  providers: [terminal.config()],
});

for await (const [space, message] of app.messages) {
  if (message.sender.id === message.platform) continue; // skip self if applicable
  switch (message.content.type) {
    case "text":
      await message.reply(`echo: ${message.content.text}`);
      break;
    case "attachment":
      await message.reply(`got ${message.content.name} (${message.content.mimeType})`);
      break;
    default:
      // "custom" — platform-specific raw payload, ignore for now
  }
}
```

For iMessage (M4), swap `terminal.config()` → `imessage.config()` and pass `projectId` / `projectSecret` from env (Photon Project Page → API key & project id).

CI:
- GitHub Actions workflow: matrix runs `uv run pytest` in `server/` and `pnpm vitest run` in `agent/`.

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

Implement `inference.py` against **GMI's OpenAI-compatible serverless** endpoint:
- Client: `OpenAI(base_url=settings.GMI_LLM_BASE_URL, api_key=settings.GMI_API_KEY)`.
- Call `client.chat.completions.create(model=settings.GMI_LLM_MODEL, messages=[...], response_format={"type": "json_object"}, max_tokens=4096, temperature=0.2)`.
- System prompt teaches the model what a "leak" is: anything in the listing affecting total cost of occupancy, lease flexibility, or quality of life. Output strict JSON matching the `Leak` schema.
- Wrap the call with `tenacity` retries on 5xx and on JSON parse failure (one re-prompt with the parser error appended).
- **Model selection:** start with `deepseek-ai/DeepSeek-R1`. Before locking it in, hit `GET https://api.gmi-serving.com/v1/models` with the API key and check whether `anthropic/claude-sonnet-4.6` (or 4.7) is in the catalog; if yes, switch via env. The Anthropic-compatible path used by Claude Code (`api.gmi-serving.com` + `anthropic` SDK) is **not** the same as serverless and may not be exposed for arbitrary apps.

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
- `index.ts`: Spectrum loop using the real API surface:
  ```ts
  import { Spectrum, terminal } from "spectrum-ts";

  const app = await Spectrum({ providers: [terminal.config()] });
  const stateByUser = new Map<string, { leaks: Leak[] }>();

  for await (const [space, message] of app.messages) {
    if (message.content.type !== "text") continue;
    const userId = message.sender.id;
    const state = stateByUser.get(userId) ?? { leaks: [] };
    const intent = classify(message.content.text);

    await space.responding(async () => {
      if (intent.kind === "url") {
        const { content } = await crawl(intent.url);
        const { leaks, summary } = await analyze(content, state.leaks);
        state.leaks = addLeaks(state.leaks, leaks);
        await message.reply(summary);
      } else if (intent.kind === "walkthrough") {
        const { videoUrl } = await walkthrough(state.leaks);
        // iMessage will preview the URL inline; for an actual file send,
        // fetch the bytes and use `attachment(buffer, { mimeType: "video/mp4" })`.
        await message.reply(videoUrl);
      } else {
        await message.reply("Send me a listing URL or ask for a walkthrough.");
      }
    });

    stateByUser.set(userId, state);
  }
  ```
- Available content builders (per [Content docs](https://docs.photon.codes/spectrum-ts/content)): `text(...)`, `attachment(path | buffer, { mimeType })`, `custom({...})`. `message.reply(...)` and `space.send(...)` accept variadic `ContentInput[]`.
- Note: state is **in-memory per `sender.id`**. Restarting the agent loses it. M7 adds sqlite persistence.

**Tests:**
- Unit: classifier truth table; reducer dedupes.
- Integration (`agent/tests/integration/terminal-roundtrip.test.ts`): spawn Spectrum with the Terminal provider, point `SERVER_BASE_URL` at a Node-hosted stub (e.g. `node:http`) returning canned `/crawl` and `/analyze` responses; script an input line; assert the printed reply.

### M4 — iMessage provider
**Goal:** swap Terminal → iMessage provider via Spectrum config; manual E2E from a real Apple device.

No code changes inside the message loop. Document the iMessage provider setup steps once Photon docs clarify the bridge requirements (Mac relay vs. hosted). Keep integration tests on Terminal.

### M5 — Polish
- Retries (`tenacity`) on GMI 5xx.
- Structured logs (`structlog`).
- sqlite persistence of leaks (`server/leaks.db`) so restarts don't lose state.

---

## 4a. Follow-up milestones (after core ships)

Off the critical path. Implement only after the core text loop is stable and being used.

### F1 — Pixverse walkthrough video
**Goal:** `POST /walkthrough { leaks[] }` returns a `video_url` summarizing the apartments discussed.

The artifact you'd share with a partner/roommate. Pixverse is the chosen model — multi-shot generation with character consistency suits a per-listing walkthrough. Available via GMI Video API (request-queue, async with polling).

Steps:
1. Build a prompt from accumulated leaks: one shot per apartment, naming property, rent, lease term, and 1–2 standout leaks.
2. `POST {GMI_VIDEO_BASE_URL}/requests`:
   ```json
   {"model": "Pixverse", "payload": {"prompt": "<built prompt>", "durationSeconds": "8", "aspectRatio": "16:9"}}
   ```
   Headers: `Authorization: Bearer $GMI_API_KEY`, optional `X-Organization-ID`.
3. Receive `{request_id, status: "dispatched"}`.
4. Poll `GET {GMI_VIDEO_BASE_URL}/requests/{request_id}` every ~5s with exponential backoff, up to a 5-minute deadline.
5. On `status == "success"`, return `outcome.video_url` (and `thumbnail_image_url`).

Verify exact Pixverse model ID via `GET {GMI_VIDEO_BASE_URL}/models` before coding — GMI public docs don't enumerate it explicitly.

Tests: unit (prompt builder; status-machine reducer); integration (VCR cassette of submit + 3 polls + success).

### F2 — Additional GMI model
Add once a second model has a defined role.

---

## 5. API contracts (core)

```
GET  /health              → {"ok": true}

POST /crawl
  body: {"url": "<string>"}
  200:  {"content": "<rendered html or text>", "metadata": {"url": "...", "status": 200, "fetched_at": "<iso8601>"}}
  4xx:  {"error": "<message>"}

POST /analyze
  body: {"content": "<string>", "context": [Leak, ...]}
  200:  {"leaks": [Leak, ...], "summary": "<string>"}
```

Follow-up endpoints (added in F1):
```
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

## 8. Notes on Photon ↔ local server

The Spectrum agent runs on the user's machine inside a Node process. Tool calls are plain `fetch()` from agent code, so:

- **Local dev (Terminal provider):** agent → `http://127.0.0.1:8000` directly. No tunnel.
- **Production (iMessage provider on the same Mac):** still localhost — both processes on the same box.
- **Production (iMessage provider hosted by Photon):** Photon pushes inbound messages into your Node process, your Node process still calls localhost. No inbound tunnel for the Python server.
- **Only if the Node agent itself is moved to the cloud** does the Python server need to be exposed (ngrok / Cloudflare Tunnel / Tailscale Funnel). Avoid that case.

## 9. Open TBDs (don't block on these)

1. ~~Claude on GMI serverless~~ — **resolved**: `anthropic/claude-opus-4.7` confirmed callable via `/v1/chat/completions`.
2. ~~Pixverse exact model ID~~ — **resolved**: `pixverse-v5.6-t2v` (plus `-i2v`, `-transition` variants).
3. **Second GMI model** — still undefined; not blocking.
4. **iMessage provider deployment** — Mac relay (BlueBubbles-style) vs. hosted by Photon. Resolved at M4.
5. **Anti-bot** — if Avalon (or others) block Obscura, add `--stealth` and consider a residential proxy.

---

## 10. Definition of done

**Core (M0–M5):**
- `uv run pytest` in `server/` is green; coverage ≥ 80% on `crawler.py`, `inference.py`, route handlers.
- `pnpm vitest run` in `agent/` is green.
- `RUN_E2E=1 ./scripts/e2e.sh` against the Avalon URL produces a leak summary mentioning rent, lease term, and furnished premium delivered through the Spectrum agent.
- README documents one-command setup: `make dev` boots Obscura sidecar, the FastAPI server, and the Spectrum Terminal agent.

**Follow-up (F1):**
- `POST /walkthrough` returns a playable Pixverse `video_url` for the canonical Avalon session.
