# AGENTS.md

## Start the app

```bash
./start.sh                    # both servers, opens browser, Ctrl+C kills both
BACKEND_PORT=9000 ./start.sh  # override ports
```

Manual alternative:
```bash
# Terminal 1 (requires venv created and pip install -e . already run)
uvicorn backend.app:app --reload --port 8000

# Terminal 2
cd frontend && npm run dev     # Next.js on :3000
```

## Project layout (two-package repo)

```
tradingagents/   — Python library (LangGraph multi-agent pipeline, pip install -e .)
backend/         — FastAPI app (depends on tradingagents/, NOT a package)
frontend/        — Next.js 16 app (separate node project, `cd frontend && npm run ...`)
cli/             — Interactive CLI (original, mostly unused)
```

## Python gotchas

- `pip install -e .` installs the `tradingagents/` + `cli/` packages (see `pyproject.toml` `[tool.setuptools.packages.find]`).
- Additional deps NOT in pyproject.toml: `fastapi uvicorn websockets aiosqlite numpy feedparser`. Install them after `pip install -e .`.
- `nsepython` is an optional import (FII/DII data in `backend/fii_dii.py:15`). Not in pyproject.toml. Install separately if needed.
- `backend/app.py` does `sys.path.insert(0, PROJECT_ROOT)` so absolute imports like `from backend.db import ...` work even though `backend/` has no `__init__.py`.
- DB path: `~/.tradingagents/trading_agent.db` — auto-created on first startup by `backend/db.py:ensure_db()`.
- Agent memories: `~/.tradingagents/memory/*.json`. Auto-loaded on startup, auto-saved after writes.
- `.env` loaded at the top of `backend/app.py` (not via dotenv auto-find). API keys from SQLite settings table take priority over `.env`.

## Frontend conventions

- **Next.js 16 with breaking changes.** Read `frontend/node_modules/next/dist/docs/` before writing route/page code. APIs and conventions differ from Next.js 14/15 training data.
- Path alias: `@/` → `./src/*` (tsconfig paths).
- shadcn/ui: base-nova style, RSC enabled, Tailwind v4, CSS variables, Lucide icons. (see `components.json`).
- State: Zustand store in `src/lib/store.ts` — survives page navigation.
- Light mode default, Open Sans font via `next/font/google`.
- Commands: `npm run dev` / `npm run build` / `npm run lint`. **No `typecheck` script** — TS errors surface via `npm run build` or editor.
- `next-env.d.ts` is auto-generated, gitignored, ignored by eslint.

## Testing

There are **no test files** in the repo. Verify changes manually by running the affected server and checking the UI.

## Root vs frontend agent files

- `frontend/AGENTS.md` contains a Next.js 16 version warning — do not ignore it.
- `frontend/CLAUDE.md` just points to `frontend/AGENTS.md`.
- Root `CLAUDE.md` is the comprehensive feature reference (read it if you need the full picture).
- This file (`AGENTS.md`) is the compact instruction file for agents.

## Key architecture patterns

- **Data layer**: `tradingagents/dataflows/interface.py:route_to_vendor()` routes all data calls. Ticker normalization: `RELIANCE` → `RELIANCE.NS`, `NIFTY50` → `^NSEI`.
- **Agent pipeline**: Market/News/Social/Fundamentals analysts → Bull/Bear debate → Research Manager → Trader → Risk debaters → Portfolio Manager. Orchestrated by `tradingagents/graph/`.
- **Backend routers** in `backend/routers/` follow the pattern: `from backend.routers import X` → `app.include_router(X.router)`.
- **WebSocket streaming**: `WS /api/analysis/ws/{task_id}` streams heartbeats + stats via `backend/ws.py`.
- **Stats tracking**: `backend/stats_callback.py` is a LangChain `BaseCallbackHandler` — only works for Anthropic/OpenAI/Google model pricing.
- **Recommender weights**: Three-layer merge at runtime: DEFAULT → base tuned (`settings.recommender_tuned_weights`) → regime override (`settings.recommender_regime_weights`). All weights read from module-level `_ACTIVE_WEIGHTS`.

## Safety defaults

- `dry_run: True` in `tradingagents/default_config.py` — orders logged, never executed.
- `order_execution_enabled: False` — master kill switch.
- Exchange whitelist: NSE only by default.

## Naming collisions

- Both `backend/` and `frontend/src/app/` have files named `scanner`, `recommender`, `simulation`, `performance`, `insights`, `analysis`, `backtest`, `news`, `settings`. The backend ones are Python routers/engines; the frontend ones are Next.js pages. Don't confuse them.
