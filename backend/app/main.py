from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
import time
from contextlib import asynccontextmanager
from fastapi import Request
from fastapi.responses import JSONResponse

from app.scheduler import start_scheduler
from app.database import get_db_connection
from app.init_db import init_db


def _startup_recovery_precache() -> None:
    """Scan saved_queries created in the last 48h and re-trigger their intraday
    precache so a backend restart can't leave warm datasets stranded. Runs in
    a daemon thread — must NOT raise. Idempotent: cached months hit disk cache.
    """
    try:
        import json as _json
        import threading as _threading
        from datetime import datetime, timedelta
        from app.database import get_user_db_connection, get_user_db_lock
        from app.routers.query import _write_precache_state

        # PASO 1 — pre-warm the gap-universe intraday to local disk (idempotent,
        # bounded, env-gated via INTRADAY_PREWARM_ENABLED). PASO 3 — optionally
        # mirror it into RAM (INTRADAY_RAM_CACHE_ENABLED, off until CCX33).
        # Both are best-effort and must never block or break startup recovery.
        try:
            from app.db.gcs_cache import prewarm_gap_universe, load_ram_cache
            prewarm_gap_universe()
            load_ram_cache()
        except Exception as e:
            print(f"[RECOVERY] gap-universe prewarm/ram skipped: {e}")

        cutoff = datetime.now() - timedelta(hours=48)
        lock = get_user_db_lock()
        with lock:
            con = get_user_db_connection()
            try:
                rows = con.execute(
                    "SELECT id, name, filters FROM saved_queries "
                    "WHERE created_at >= ? "
                    "ORDER BY created_at DESC LIMIT 10",
                    [cutoff],
                ).fetchall()
            finally:
                con.close()

        if not rows:
            print("[RECOVERY] No recent datasets (<48h) found; nothing to re-precache.")
            return

        print(f"[RECOVERY] Found {len(rows)} recent dataset(s); re-triggering precache...")
        for row in rows:
            dataset_id, ds_name, raw_filters = row[0], row[1], row[2]
            # filters comes back as a dict or JSON string depending on DuckDB driver path.
            if isinstance(raw_filters, str):
                try:
                    filters = _json.loads(raw_filters)
                except Exception:
                    filters = {}
            else:
                filters = raw_filters or {}

            date_from = filters.get("start_date") or filters.get("date_from") or ""
            date_to = filters.get("end_date") or filters.get("date_to") or ""

            # Fetch the dataset's ticker-date pairs into memory.
            with lock:
                con = get_user_db_connection()
                try:
                    pairs_df = con.execute(
                        "SELECT ticker, CAST(date AS VARCHAR) as date "
                        "FROM dataset_pairs WHERE dataset_id = ?",
                        [dataset_id],
                    ).fetchdf()
                finally:
                    con.close()

            if pairs_df is None or pairs_df.empty:
                print(f"[RECOVERY] Dataset {dataset_id} ({ds_name}): no pairs; skipping.")
                continue
            if not date_from:
                date_from = str(pairs_df["date"].min())
            if not date_to:
                date_to = str(pairs_df["date"].max())

            print(f"[RECOVERY] -> Marking precache completed for {dataset_id} ({ds_name})")
            _write_precache_state(dataset_id, "completed", 100.0)
    except Exception as e:
        print(f"[RECOVERY] startup recovery failed: {e}")


# Lifecycle events
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Write gcs-key.json from env var if present
    import base64, json as _json, os as _os
    gcs_key_b64 = _os.getenv("GCS_KEY_B64")
    if gcs_key_b64:
        try:
            key_path = _os.getenv("GCS_KEY_FILE", "gcs-key.json")
            key_bytes = base64.b64decode(gcs_key_b64)
            with open(key_path, "wb") as f:
                f.write(key_bytes)
            print(f"[INFO] gcs-key.json written from GCS_KEY_B64 env var")
        except Exception as e:
            print(f"[WARN] Could not write gcs-key.json: {e}")

    # Startup: Connect to DB so first request is fast. If DB fails, app still starts (avoids 502 on cold start).
    print("Startup: Connecting to database...")
    from app.gcs_sync import download_user_db, upload_user_db
    
    # 1. Download user DB if in GCS mode
    download_user_db()
    
    try:
        con = get_db_connection()
        tables = con.execute("SHOW TABLES").fetchall()
        print(f"[INFO] Connected. Tables: {[t[0] for t in tables]}")
        try:
            init_db()
            print("[INFO] Init DB: strategies and saved_queries tables verified")
        except Exception as e:
            print(f"[WARN] Init DB warning: {e}")

        from app.services.cache_service import load_tickers_cache, load_splits_cache, load_hot_daily_cache
        try:
            t0 = time.time()
            load_tickers_cache()
            print(f"[TIMING] tickers: {round(time.time()-t0, 2)}s")

            t0 = time.time()
            load_splits_cache()
            print(f"[TIMING] splits: {round(time.time()-t0, 2)}s")

            t0 = time.time()
            load_hot_daily_cache()
            print(f"[TIMING] hot cache: {round(time.time()-t0, 2)}s")

            # Log intraday disk cache status
            cache_dir = os.getenv("CACHE_DIR", ".cache/intraday")
            if os.path.exists(cache_dir):
                cache_files = len(os.listdir(cache_dir))
                total_mb = sum(os.path.getsize(os.path.join(cache_dir, f)) for f in os.listdir(cache_dir) if os.path.isfile(os.path.join(cache_dir, f))) / 1024 / 1024
                print(f"[CACHE] intraday disk cache: {cache_files} files, {total_mb:.1f} MB in {cache_dir}")
            else:
                print(f"[CACHE] intraday disk cache dir not found: {cache_dir}")
            print("[INFO] Hot daily cache loaded at startup")

            # Background recovery enables resuming recently started dataset precaching.
            import threading as _threading
            _threading.Thread(target=_startup_recovery_precache, daemon=True).start()
        except Exception as e:
            print(f"[WARN] Cache preload failed: {e}")
    except Exception as e:
        print(f"[WARN] DB not available at startup: {e}. App will start; first API request may fail or be slow.")

    start_scheduler()
    yield
    # Shutdown
    print("Shutdown: Cleaning up...")
    
    # Upload user DB back to GCS explicitly on graceful shutdown
    upload_user_db()


app = FastAPI(title="Short Selling Backtester API", lifespan=lifespan)

# CORS Configuration - MUST be added BEFORE routers
# 502 from the platform (e.g. Render) has no CORS headers; ensuring our app always adds them when it responds.
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "https://www.mystrategybuilder.fun",
    "https://mystrategybuilder.fun",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_cors_headers_to_all_responses(request, call_next):
    """Ensure CORS headers are on every response so 4xx/5xx from our app are not reported as CORS errors."""
    response = await call_next(request)
    origin = request.headers.get("origin")
    if origin and (origin in ALLOWED_ORIGINS or origin.startswith("https://") and "vercel.app" in origin):
        response.headers["Access-Control-Allow-Origin"] = origin
    elif origin is None and request.url.path.startswith("/api/"):
        response.headers["Access-Control-Allow-Origin"] = "https://www.mystrategybuilder.fun"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response

from app.routers import data, strategies, backtest, query, market, strategy_search, ticker_analysis
from app.routers import optimization, users, edgie
from app.routers import screener
from app.routers import assistant
import logging

# Configure logging to show INFO level for backtester namespace
logging.basicConfig(level=logging.INFO)
logging.getLogger("backtester").setLevel(logging.INFO)

app.include_router(data.router, prefix="/api/data", tags=["Data"])
app.include_router(strategies.router, prefix="/api/strategies", tags=["Strategies"])
app.include_router(backtest.router)
app.include_router(optimization.router)
app.include_router(query.router, prefix="/api/queries", tags=["Queries"])
app.include_router(strategy_search.router, prefix="/api/strategy-search", tags=["Strategy Search"])
app.include_router(ticker_analysis.router)
app.include_router(market.router)
app.include_router(users.router, prefix="/api/users", tags=["Users"])
app.include_router(screener.router)
from app.routers import news
app.include_router(news.router, prefix="/api", tags=["News"])
app.include_router(edgie.router, prefix="/api/edgie", tags=["Edgie"])
# assistant.router already declares prefix="/api/assistant" (Edgie AI Gateway: streaming + function calling)
app.include_router(assistant.router)

@app.get("/health")
def read_health():
    return {"status": "ok"}

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"GLOBAL ERROR: {exc}")
    import traceback
    traceback.print_exc()
    origin = request.headers.get("origin")
    allow_origin = origin if origin else "https://www.mystrategybuilder.fun"
    
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error", "message": str(exc)},
        headers={
            "Access-Control-Allow-Origin": allow_origin,
            "Access-Control-Allow-Credentials": "true"
        }
    )

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
