# CLAUDE.md

Conversational lease-crawler agent. iMessage → Photon (spectrum-ts) → local FastAPI server → GMI (OpenAI-compatible Claude). Per-sender state holds accumulated leaks + summary + chat history; users can crawl URLs and ask follow-up questions about them.

See [PRD.md](./PRD.md) and [plan.md](./plan.md) for product context.

## Stack

- **Server** (`server/`): Python 3.12 + FastAPI + uv. OpenAI SDK pointed at GMI's `/v1` endpoint (NOT the Anthropic SDK on this branch). Routes: `/health`, `/crawl`, `/analyze`, `/ask`.
- **Agent** (`agent/`): TypeScript + Bun runtime + **pnpm** (not bun pkg manager). spectrum-ts (Photon SDK) for iMessage transport. Auto-falls-back to Terminal provider when `SPECTRUM_PROJECT_ID/SECRET` are unset.
- **Crawler**: plain `httpx` with a Chrome UA. Works for SSR sites (Avalon homepage, etc.); **fails 403 on anti-bot sites** like Irvine Company. Obscura headless browser is downloaded at `.tools/obscura/obscura` but not yet wired into `crawler.py` — see "Known limitations" below.
- **Inference**: GMI Cloud (`https://api.gmi-serving.com/v1`) via OpenAI SDK. Default model `anthropic/claude-opus-4.7`.

## Quick start

```bash
make install          # uv sync (server) + pnpm install (agent)
cp .env.example .env  # then fill in GMI_API_KEY + SPECTRUM_PROJECT_ID + SPECTRUM_PROJECT_SECRET
make dev-server       # uvicorn :8000  (terminal 1)
make dev-agent        # spectrum-ts agent (terminal 2)
```

`make dev` prints instructions; it does not boot both. Use the two `dev-*` targets in separate terminals.

## Tests

```bash
make test                # both suites
make test-server         # uv run pytest (server/)
make test-agent          # pnpm vitest run (agent/)
```

Integration tests use VCR cassettes in `server/tests/integration/cassettes/`. To re-record against real GMI:

```bash
cd server && uv run pytest tests/integration/ --record-mode=once -v
```

Cassettes filter `authorization`/`api-key` headers — never commit raw secrets.

## Env vars

`.env` lives at repo root (gitignored). Required:

| Var | Source |
|---|---|
| `GMI_API_KEY` | console.gmicloud.ai (JWT, starts with `eyJ`) |
| `GMI_LLM_BASE_URL` | `https://api.gmi-serving.com/v1` |
| `GMI_LLM_MODEL` | `anthropic/claude-opus-4.7` (or sonnet variant) |
| `SPECTRUM_PROJECT_ID` | Photon project page (UUID) |
| `SPECTRUM_PROJECT_SECRET` | Photon project page |
| `OBSCURA_BIN` | absolute path; default `/usr/local/bin/obscura` (or `.tools/obscura/obscura` if downloaded locally) |

### Env-precedence trap (important)

`pydantic-settings` v2 default precedence is **shell env > `.env` file**. If your shell exports `ANTHROPIC_BASE_URL` or similar, it can shadow `.env`. The current `settings.py` reads `.env` via `env_file=".env"` (CWD-relative). When pytest runs from `server/`, that resolves to `server/.env` which doesn't exist — `.env` at repo root won't be read. Either:

- run from repo root (e.g. `cd server && uv run ...` works because the relative path resolves there)
- or compute an absolute env_file path: `Path(__file__).resolve().parents[3] / ".env"`

The `implement-milestones` branch (see below) has the absolute-path fix.

## Architecture

```
iMessage  →  Photon hosted bridge  →  spectrum-ts agent (Bun, pnpm)
                                                ↓
                                          intent classify
                                              ↓ ↓ ↓
                                       url   walkthrough  chat
                                        ↓        ↓         ↓
                                     /crawl    canned    /ask
                                        ↓                  ↑
                                     /analyze ─→ leaks ────┘
                                        ↑
                              GMI via OpenAI SDK
```

State is **per-sender**, keyed by phone number (`stateByUser` Map in `agent/src/index.ts`). Two phones = two separate conversations. Each state holds `leaks[]` (deduped by id), `summary` (overwritten per URL — known limitation), `lastUrl`, and `history`.

## Files worth knowing

```
server/src/lease_crawler/
  main.py            # FastAPI app + observability middleware (request_id, timing)
  log_setup.py       # stdlib logging + RequestIdFilter
  crawler.py         # httpx fetcher; CrawlError taxonomy
  inference.py       # GMI client + analyze() + ask(); JSON-mode + 1 retry
  extract.py         # pre-process Avalon-style "units":[...] JSON blobs
  models.py          # Leak, AnalyzeRequest/Response, etc.
  routers/{crawl,analyze,ask}.py
  settings.py        # pydantic-settings; reads .env

agent/src/
  index.ts           # Spectrum loop, per-sender state, intent dispatch
  classifier.ts      # url | walkthrough | chat
  state.ts           # addLeaks (dedupe), appendTurn (history)
  tools.ts           # postJson wrapper; logs duration + req_id correlation
```

## Logs

Server log format: `HH:MM:SS LEVEL [req_id] logger.name: event key=value ...`. Each request gets a 12-char `req_id` (from middleware), echoed in the response's `x-request-id` header.

Agent log format: `[agent] ...` for state events, `[tools] -> POST /path body_chars=N` and `[tools] <- POST /path status=N ms=N req_id=abc resp_chars=N` for HTTP. The `req_id` matches server's bracketed prefix — grep one ID across both logs to follow a request end-to-end.

## Known limitations

1. **Anti-bot sites blocked** (Irvine Company, anything behind Akamai/CF Bot Manager). `httpx` can't bypass TLS-fingerprinting. Fix path: implement the Obscura backend the `crawler.py` doc-string mentions (`CRAWLER_BACKEND` switch). Obscura binary is at `.tools/obscura/obscura` (`fetch <url> --dump html --wait-until=load --stealth`) — supports JS rendering + stealth.
2. **Hydration-heavy SPAs**: even with Obscura, sites that fetch listing data via XHR after `load`/`networkidle` may not be fully scrape-able. Avalon's homepage SSRs enough; their per-listing pages don't.
3. **Per-URL summary is overwritten**, not accumulated. `state.summary` only holds the latest. Multi-listing comparison still works because `state.leaks` accumulates with `source_url` tags, but `/ask` only sees one summary.
4. **No Pexiverse video walkthrough** yet (`agent/src/index.ts` returns a canned "isn't wired yet (F1)" reply).
5. **No state persistence**: `stateByUser` is in-memory; agent restart wipes it.

## Conventions

- **Branch policy**: do not commit to `main` directly. Use a feature branch (e.g. `feat/<name>`). The user explicitly asked for this in past sessions.
- **`.env`**: gitignored. Never paste real keys into tracked files. Cassette recordings filter auth headers via `vcr_config` fixtures.
- **Cassettes**: stay committed (sanitized). Re-record only when prompts/contracts change.
- **Tests**: integration tests need either a recorded cassette or `--record-mode=once`. Don't push code that records on every CI run.

## Parallel implementation (`implement-milestones` branch)

A separate local branch `implement-milestones` (5 commits, not pushed) contains a different M0–M7 implementation with several pieces that may be useful here:

- **Obscura subprocess wrapper** (real `crawler.py` swap-in for anti-bot)
- **structlog** + middleware (more polished than the stdlib observability on main)
- **sqlite leak persistence** (`leaks_repo.py`, `GET /leaks`, agent boot-time hydration)
- **tenacity retries** on GMI 5xx
- **`/walkthrough` 501 stub** for the Pexiverse path
- **Anthropic SDK** (vs main's OpenAI SDK) — main's choice is correct for GMI's OpenAI-compat surface

Don't merge it wholesale — file layouts differ (router structure, AnalyzeRequest fields, etc.). Cherry-pick specific commits if you need a piece. Run `git diff main..implement-milestones -- server/src/lease_crawler/` to compare.

## Active dev loop

When the system is running and the user is exchanging messages with the Photon bot:

- Tail server log with: `tail -f /tmp/server.log` (uvicorn writes here when started via the helper used in past sessions; `make dev-server` writes to its terminal)
- Tail agent log: `tail -f /tmp/agent.log` (similarly)
- Restart agent after editing `agent/src/*.ts` — `tsx` doesn't auto-reload, only `tsx watch` does
- Server hot-reloads on file changes (uvicorn `--reload`)
