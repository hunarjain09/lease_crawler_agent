# lease_crawler (server)

Python local server (FastAPI) for the lease_crawler_agent project. See repo-root `plan.md` for context.

## Dev

```bash
uv sync
uv run pytest
uv run uvicorn lease_crawler.main:app --reload
```
