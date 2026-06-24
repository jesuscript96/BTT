#!/usr/bin/env bash
#
# Run the Edgecute Backtest API Bruno collection end-to-end:
#   1. boot the API with the deterministic demo facade (no engine/data),
#   2. mint a sandbox API key in the same store,
#   3. run the whole collection with @usebruno/cli,
#   4. tear everything down.
#
# Usage:  ./run.sh            (uses backend/.venv_313 + npx @usebruno/cli)
# Env:    EDGECUTE_PY=...     python with fastapi+uvicorn (default .venv_313)
#         EDGECUTE_API_PORT=  port to bind (default 8155)
#         BRU="bru"           use a globally-installed bru instead of npx
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$(cd "$HERE/.." && pwd)"
PY="${EDGECUTE_PY:-$BACKEND/.venv_313/bin/python}"
PORT="${EDGECUTE_API_PORT:-8155}"
BRU="${BRU:-npx --yes @usebruno/cli}"
STORE="$(mktemp -t edgecute_bruno).sqlite"

export EDGECUTE_STORE_PATH="$STORE"
export EDGECUTE_DEMO_FACADE=1
export EDGECUTE_AUTH_REQUIRED=true

SERVER_PID=""
cleanup() {
  [ -n "$SERVER_PID" ] && kill "$SERVER_PID" >/dev/null 2>&1 || true
  rm -f "$STORE" "$STORE"-* >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "→ Starting API on :$PORT (demo facade) ..."
( cd "$BACKEND" && exec "$PY" -m uvicorn app.api_public.app:app --port "$PORT" --log-level warning ) &
SERVER_PID=$!

echo "→ Waiting for health ..."
for _ in $(seq 1 60); do
  if curl -fsS "http://localhost:$PORT/v1/health" >/dev/null 2>&1; then ok=1; break; fi
  if ! kill -0 "$SERVER_PID" >/dev/null 2>&1; then echo "API process died on startup"; exit 1; fi
  sleep 0.25
done
[ "${ok:-}" = 1 ] || { echo "API did not become healthy in time"; exit 1; }

echo "→ Minting sandbox API key ..."
TOKEN="$(cd "$BACKEND" && "$PY" -m app.api_public.admin create-key --owner bruno_ci --test \
  | awk '/^[[:space:]]*token[[:space:]]*:/ {print $NF}')"
[ -n "$TOKEN" ] || { echo "Failed to mint API key"; exit 1; }

echo "→ Minting + revoking a key (to test the 403 forbidden path) ..."
REVOKED_OUT="$(cd "$BACKEND" && "$PY" -m app.api_public.admin create-key --owner bruno_ci_revoked --test)"
REVOKED_TOKEN="$(printf '%s\n' "$REVOKED_OUT" | awk '/^[[:space:]]*token[[:space:]]*:/ {print $NF}')"
REVOKED_ID="$(printf '%s\n' "$REVOKED_OUT" | awk '/^[[:space:]]*key_id[[:space:]]*:/ {print $NF}')"
[ -n "$REVOKED_TOKEN" ] && [ -n "$REVOKED_ID" ] || { echo "Failed to mint revoked key"; exit 1; }
( cd "$BACKEND" && "$PY" -m app.api_public.admin revoke-key --id "$REVOKED_ID" ) >/dev/null

echo "→ Running Bruno collection ..."
cd "$HERE"
# Extra args (e.g. --reporter-junit results.xml) are forwarded to `bru run`,
# which is how CI produces report artifacts.
$BRU run -r \
  --env local \
  --env-var baseUrl="http://localhost:$PORT" \
  --env-var apiKey="$TOKEN" \
  --env-var revokedKey="$REVOKED_TOKEN" \
  "$@"
