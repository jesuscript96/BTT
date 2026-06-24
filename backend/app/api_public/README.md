# Edgecute Backtest API (`api_public`)

Public B2D API layer, **isolated from the engine**. It only reaches the engine through
`facade.py`; it never imports `engine.py` / `indicators.py` / `portfolio_sim.py` (enforced
by a test). Design: `docs/b2d-gateway/`.

## Structure (modular by module — docs/b2d-gateway/05 §0)

```
api_public/
  app.py                # ASGI app; mounts EDGECUTE_ENABLED_MODULES
  config.py             # env-driven technical config (NO pricing policy)
  facade.py             # the ONLY bridge to the engine (lazy imports)
  admin.py              # CLI: create/revoke API keys, usage
  core/                 # cross-cutting: auth, gating(hook), metering, ratelimit, errors, payload, store
  modules/backtest/     # the MVP module: router, models, mapper, catalog, meta
  tests/                # 36 tests (no engine/data needed; facade faked)
```

## Run

```bash
cd backend
uvicorn app.api_public.app:app --port 8100
# health: GET http://localhost:8100/v1/health
# docs:   http://localhost:8100/docs   (OpenAPI: /v1/openapi.json)
```

Store defaults to SQLite (`EDGECUTE_STORE_PATH`, default `./edgecute_api.sqlite`). Prod can
point to Postgres via `EDGECUTE_DATABASE_URL` (the store abstraction; v2).

## API keys

```bash
python -m app.api_public.admin create-key --owner <clerk_user_id> --test   # sandbox key
python -m app.api_public.admin create-key --owner <clerk_user_id>          # live key
python -m app.api_public.admin revoke-key --id key_xxx
python -m app.api_public.admin usage --id key_xxx
```

## Endpoints (`/v1`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | no | Healthcheck |
| GET | `/openapi.json` | no | OpenAPI document |
| GET | `/catalog/indicators` | yes | Indicator catalog |
| POST | `/strategies/validate` | yes | Validate a strategy (Pydantic) |
| POST | `/universe/preview` | yes | Ticker-days of an existing dataset |
| POST | `/backtests` | yes | Run a backtest (synchronous, capped) |
| GET | `/backtests/{id}` | yes | Retrieve a stored result (`include`/pagination) |
| GET | `/backtests/{id}/intraday` | yes | One intraday equity series |
| POST | `/backtests/{id}/cancel` | yes | Cancel (409 for finished sync jobs) |

## Scope notes

- **Synchronous with a technical cap** (`EDGECUTE_MAX_TICKER_DAYS`). Async jobs = v2 (the
  `status` field already leaves room).
- **Universe** = an existing `dataset_ref` (or `mock_dataset_1`). Filter-based universe
  creation is v2 (returns a clear `not_implemented`).
- **Gating is a hook with a default allow** — the monetization policy is a deferred product
  decision, applied as config later (`core/gating.set_policy`).

## Test

```bash
cd backend && .venv_313/bin/python -m pytest app/api_public/tests -q
```
