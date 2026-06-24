# Edgecute Backtest API — Bruno collection

Automated HTTP tests for the public API (`/v1/*`), runnable from the CLI with
[`@usebruno/cli`](https://docs.usebruno.com/testing/automate-test/automate-test).
They exercise the **real HTTP surface** end-to-end — auth, validation, the payload
rules, and the run → retrieve → intraday → cancel flow.

## How it stays runnable without market data

A real backtest needs MotherDuck/GCS data and the engine. To keep these tests
deterministic and CI-friendly, the API exposes an **opt-in demo facade**
(`EDGECUTE_DEMO_FACADE=1`, wired in `app/api_public/app.py`) that serves canned,
deterministic results with **no engine and no external data**. It is never enabled
in production. The canned numbers match the pytest suite (3 trades, 10 ticker-days,
a 10-point intraday series for `AAPL`/`2024-01-02`).

## Run it

One command boots the API with the demo facade, mints a sandbox API key, and runs
the whole collection:

```bash
cd backend/bruno
./run.sh
```

`run.sh` honours:

- `EDGECUTE_PY` — python with fastapi+uvicorn (default `backend/.venv_313/bin/python`)
- `EDGECUTE_API_PORT` — port to bind (default `8155`)
- `BRU` — set to `bru` to use a global install instead of `npx`

### Manual / against an already-running server

```bash
# 1. start the API yourself with the demo facade
cd backend
EDGECUTE_DEMO_FACADE=1 EDGECUTE_STORE_PATH=/tmp/edgecute.sqlite \
  .venv_313/bin/python -m uvicorn app.api_public.app:app --port 8155

# 2. mint a key (same store)
EDGECUTE_STORE_PATH=/tmp/edgecute.sqlite \
  .venv_313/bin/python -m app.api_public.admin create-key --owner me --test

# 3. run the collection (install once: npm i -g @usebruno/cli)
cd backend/bruno
bru run -r --env local --env-var apiKey=ek_test_xxx
```

### CI

```bash
cd backend/bruno && npm install && npm test
```

`bru run` exits non-zero if any assertion fails. For machine-readable output add
`--reporter-junit results.xml` or `--reporter-json results.json`.

## What's covered (`/v1/*`)

All 10 `/v1` endpoints are covered; 27 requests, 27 tests.

| # | Endpoint | Checks |
|---|----------|--------|
| 01–03 | `GET /health`, `/openapi.json`, `/modules` | liveness, OpenAPI envelope, module mounted |
| 04–05, 24 | auth matrix | missing → 401 `unauthorized`; bad format → 401 `invalid_api_key`; revoked → 403 `forbidden` |
| 06–07 | `GET /catalog/indicators` | known indicators present; `?category=` filter |
| 08–09 | `POST /strategies/validate` | valid → `valid:true`; invalid → field error paths |
| 10–13 | `POST /universe/preview` | within-cap; over-cap; filters → 501; missing → 422 |
| 14–15 | `POST /backtests` | default include (metrics+equity, no trades); `include:[trades]` paginated |
| 16–18 | `POST /backtests` | missing universe → 422; over-cap → 422 `universe_too_large`; `mock_dataset_1` skips cap |
| 27 | `POST /backtests` | bad enum (`fee_type`) → 422 `validation_error` with field details |
| 19–20, 25–26 | `GET /backtests/{id}` | retrieve stored job; unknown id → 404; `include=trades` cursor pagination (page 1 → page 2) |
| 21–22 | `GET /backtests/{id}/intraday` | series found; unknown ticker/date → 404 |
| 23 | `POST /backtests/{id}/cancel` | finished sync job → 409 `conflict` |

The chained flow (19, 21–23, 25–26) reuses the `job_id` captured from request 14
via a post-response script (`bru.setVar("jobId", ...)`); request 25 likewise hands
its `next_cursor` to 26. Requests run in `seq` order.

The revoked-key test (24) needs `run.sh`, which mints a key, revokes it, and
injects it as `revokedKey`. Running the collection by hand without that var will
fail only that one request.

### Error codes covered

`unauthorized`, `invalid_api_key`, `forbidden`, `not_implemented`,
`invalid_universe`, `validation_error`, `universe_too_large`, `job_not_found`,
`conflict`.

### Not covered here (covered by pytest instead)

`rate_limited`, metering totals, the gating policy hook, `internal_error`
non-leakage, and the engine-path codes (`job_failed`, `invalid_strategy`) need
in-process hooks/state or the real engine — see `backend/app/api_public/tests/`.
The developer console (`/api/console/*`) needs a Clerk session, out of scope for
this key-auth collection.
