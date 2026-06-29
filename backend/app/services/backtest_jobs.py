"""
Job store for async backtests (F3).

Two concerns, deliberately split so the heavy payload never touches Redis:

1. **Job state** (small, hot): status/percent/current/total/error. Lives in
   Redis under ``backtest:job:{job_id}`` with a 1h TTL, plus a
   ``backtest:dataset:{dataset_id}`` index so cancel-by-dataset and the
   anti-double-run guard keep working. Degrades to an in-process dict when
   Redis is unavailable (same graceful pattern as ``redis_client``) — note the
   in-process fallback does NOT survive an OOM-kill of the container, which is
   exactly the failure Redis fixes.

2. **Result payload** (large, cold): written to local disk, never to Redis. The
   result is stored split in two files so the per-day equity bomb is only ever
   read when a day is actually clicked:
     - ``{job_id}.result`` → the full result WITHOUT ``equity_curves``
     - ``{job_id}.equity`` → ``{"TICKER|DATE": [equity points]}``
   Serialized with msgpack when available (more compact), falling back to JSON.
   Files older than the TTL are swept at the start of every new run.
"""

import json
import os
import time
import uuid

from app.redis_client import get_redis

# msgpack is optional: if it isn't installed we fall back to JSON so the feature
# works even before the image is rebuilt with the new dependency.
try:
    import msgpack
except Exception:  # pragma: no cover
    msgpack = None


JOB_TTL_S = int(os.getenv("BACKTEST_JOB_TTL", "3600"))
RESULTS_DIR = os.getenv("BTT_JOB_RESULTS_DIR", "/tmp/btt_job_results")

_JOB_KEY = "backtest:job:{}"
_DATASET_KEY = "backtest:dataset:{}"

# In-process fallback when Redis is down (per-worker, lost on restart).
_MEM_STATE: dict = {}
_MEM_DATASET: dict = {}


# ──────────────────────────────────────────────────────────────────────────
# Serialization helpers (msgpack ↔ json, both safe against odd scalar types)
# ──────────────────────────────────────────────────────────────────────────
def _default(o):
    # Last-resort coercion for anything sanitize_floats() didn't already flatten
    # (e.g. a stray numpy scalar). Booleans/ints/floats/str/None pass through.
    try:
        return o.item()  # numpy scalar → python scalar
    except Exception:
        return str(o)


def _dumps(obj) -> bytes:
    if msgpack is not None:
        return msgpack.packb(obj, use_bin_type=True, default=_default)
    return json.dumps(obj, default=_default).encode("utf-8")


def _loads(blob: bytes):
    # Try msgpack first, then JSON — so a file written under one serializer is
    # still readable if the other is the one currently installed.
    if msgpack is not None:
        try:
            return msgpack.unpackb(blob, raw=False)
        except Exception:
            pass
    return json.loads(blob.decode("utf-8"))


def _result_path(job_id: str) -> str:
    return os.path.join(RESULTS_DIR, f"{job_id}.result")


def _equity_path(job_id: str) -> str:
    return os.path.join(RESULTS_DIR, f"{job_id}.equity")


# ──────────────────────────────────────────────────────────────────────────
# Job id / state
# ──────────────────────────────────────────────────────────────────────────
def new_job_id() -> str:
    return str(uuid.uuid4())


def set_job_state(job_id, dataset_id, status, percent=0.0, current=0, total=0, error=None):
    state = {
        "job_id": job_id,
        "dataset_id": dataset_id,
        "status": status,
        "percent": float(percent),
        "current": int(current),
        "total": int(total),
        "error": error,
    }
    r = get_redis()
    if r is not None:
        try:
            r.setex(_JOB_KEY.format(job_id), JOB_TTL_S, json.dumps(state))
            if dataset_id:
                r.setex(_DATASET_KEY.format(dataset_id), JOB_TTL_S, job_id)
            return state
        except Exception:
            pass  # fall through to in-process mirror
    _MEM_STATE[job_id] = state
    if dataset_id:
        _MEM_DATASET[dataset_id] = job_id
    return state


def get_job_state(job_id):
    r = get_redis()
    if r is not None:
        try:
            raw = r.get(_JOB_KEY.format(job_id))
            if raw is not None:
                return json.loads(raw)
        except Exception:
            pass
    return _MEM_STATE.get(job_id)


def get_job_for_dataset(dataset_id):
    r = get_redis()
    if r is not None:
        try:
            jid = r.get(_DATASET_KEY.format(dataset_id))
            if jid is not None:
                return jid
        except Exception:
            pass
    return _MEM_DATASET.get(dataset_id)


def is_job_cancelled(job_id) -> bool:
    state = get_job_state(job_id)
    return bool(state and state.get("status") == "cancelled")


def mark_dataset_cancelled(dataset_id):
    """Flag the dataset's current job as cancelled. Returns the job_id or None."""
    job_id = get_job_for_dataset(dataset_id)
    if not job_id:
        return None
    state = get_job_state(job_id) or {}
    set_job_state(
        job_id,
        dataset_id,
        "cancelled",
        percent=state.get("percent", 0.0),
        current=state.get("current", 0),
        total=state.get("total", 0),
    )
    return job_id


# ──────────────────────────────────────────────────────────────────────────
# Result payload on disk
# ──────────────────────────────────────────────────────────────────────────
def cleanup_old_results(max_age_s: int = JOB_TTL_S):
    """Remove job result/equity files older than max_age_s. Best-effort."""
    try:
        now = time.time()
        if not os.path.isdir(RESULTS_DIR):
            return
        for name in os.listdir(RESULTS_DIR):
            path = os.path.join(RESULTS_DIR, name)
            try:
                if now - os.path.getmtime(path) > max_age_s:
                    os.remove(path)
            except Exception:
                continue
    except Exception:
        pass


def save_job_result(job_id: str, result: dict):
    """Persist the result split into a light part + a per-day equity map."""
    os.makedirs(RESULTS_DIR, exist_ok=True)

    equity_curves = result.get("equity_curves") or []
    equity_map = {}
    for e in equity_curves:
        try:
            key = f"{e.get('ticker')}|{e.get('date')}"
            equity_map[key] = e.get("equity", [])
        except Exception:
            continue

    light = {k: v for k, v in result.items() if k != "equity_curves"}

    with open(_result_path(job_id), "wb") as f:
        f.write(_dumps(light))
    with open(_equity_path(job_id), "wb") as f:
        f.write(_dumps(equity_map))


def load_job_result_light(job_id: str):
    """Return the result WITHOUT equity_curves (equity served separately)."""
    path = _result_path(job_id)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        light = _loads(f.read())
    if isinstance(light, dict):
        light["equity_curves"] = []  # explicit: lazy-loaded per day
    return light


def load_job_equity(job_id: str, date: str, ticker: str | None = None):
    """Return the equity points for one day, or None if absent."""
    path = _equity_path(job_id)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        equity_map = _loads(f.read())
    if not isinstance(equity_map, dict):
        return None

    if ticker:
        hit = equity_map.get(f"{ticker}|{date}")
        if hit is not None:
            return {"ticker": ticker, "date": date, "equity": hit}

    # Fallback: first key matching the date (date-only lookup).
    suffix = f"|{date}"
    for key, points in equity_map.items():
        if key.endswith(suffix):
            return {"ticker": key.split("|", 1)[0], "date": date, "equity": points}
    return None
