# lease_crawler_agent

A conversational lease-evaluation agent: a user sends a property listing URL via iMessage (Terminal in dev), a Photon/spectrum-ts Node agent forwards it to a local Python FastAPI server, the server crawls the rendered page with Obscura (Rust headless browser) and asks Claude Opus 4.7 on GMI Cloud to extract lease "leaks" (rent, term, fees, parking, utilities, etc.), and a text summary is returned to the user on the same channel.

![Demo](demo.gif)

## Quick start

```bash
git clone <this-repo> lease_crawler_agent
cd lease_crawler_agent
cp .env.example .env
# Fill in at minimum:
#   GMI_API_KEY
#   SPECTRUM_PROJECT_ID
#   SPECTRUM_PROJECT_SECRET
make install
make test
```

Then in two terminals:

```bash
# Terminal 1
make dev-server

# Terminal 2
make dev-agent
```

## What's where

- `plan.md` — implementation plan, milestones (M0–M5), follow-up milestones, definition of done.
- `PRD.md` — product context and requirements.
- `server/` — Python 3.12 FastAPI app, `uv`-managed. Crawler, GMI inference client, route handlers.
- `agent/` — Node 20 + pnpm spectrum-ts agent. Terminal provider in dev, iMessage in prod.
- `.env.example` — every env var the server and agent read; copy to `.env` and fill in.

## Stack

| Layer | Tech |
|---|---|
| Agent | Node 20+ + spectrum-ts (TypeScript), pnpm |
| Local server | Python 3.12 + FastAPI + Uvicorn, uv |
| Crawler | Obscura (Rust, CDP, no Chrome dep) |
| Reasoning LLM | GMI Serverless (`anthropic/claude-opus-4.7`, OpenAI-compatible) |
| Video gen (follow-up) | Pixverse via GMI Video API |
| Tests | pytest (server) + vitest (agent) |

## Testing

Each half has unit and integration tests; CI runs unit suites on every push to `main` and on every pull request, with the Python and Node jobs gating the merge in parallel.
