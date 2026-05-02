.PHONY: install test test-server test-agent dev dev-server dev-agent clean

install:
	cd server && uv sync && cd ../agent && pnpm install

test: test-server test-agent

test-server:
	cd server && uv run pytest

test-agent:
	cd agent && pnpm vitest run

dev-server:
	cd server && uv run uvicorn lease_crawler.main:app --reload --host 127.0.0.1 --port 8000

dev-agent:
	cd agent && pnpm dev

dev:
	@echo "Run the server and agent in two separate terminals:"
	@echo ""
	@echo "  Terminal 1:  make dev-server"
	@echo "  Terminal 2:  make dev-agent"
	@echo ""

clean:
	rm -rf server/.venv server/.pytest_cache server/dist server/build
	rm -rf agent/node_modules agent/dist agent/.vitest_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .mypy_cache -prune -exec rm -rf {} +
	find . -type d -name .ruff_cache -prune -exec rm -rf {} +
