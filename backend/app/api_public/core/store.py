"""Persistence for the public API: API keys, usage ledger and backtest results.

MVP backend = SQLite (stdlib, zero-infra, runnable & testable). Prod swaps to
Postgres behind this same interface via EDGECUTE_DATABASE_URL (v2). NOTE: this is
a SEPARATE store from users.duckdb — never reuse the engine DB (avoids its locks;
docs/b2d-gateway/05 §4).

API keys are stored as a SHA-256 hash of a high-entropy token; the plaintext is
shown exactly once at creation.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Optional

from app.api_public import config


def _now() -> float:
    return time.time()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token(test: bool = False) -> tuple[str, str]:
    """Return (plaintext_token, prefix). Token = ek_(live|test)_<43 url-safe chars>."""
    env = "test" if test else "live"
    body = secrets.token_urlsafe(32)
    token = f"ek_{env}_{body}"
    prefix = f"ek_{env}_{body[:8]}"
    return token, prefix


@dataclass
class ApiKeyRow:
    id: str
    prefix: str
    owner_id: Optional[str]
    plan: str
    status: str  # "active" | "revoked"
    created_at: float
    last_used_at: Optional[float]


class Store:
    """Thread-safe SQLite-backed store. One connection guarded by a lock — fine
    for the MVP's in-process, low-concurrency profile."""

    def __init__(self, path: Optional[str] = None):
        self.path = path or config.STORE_PATH
        self._lock = threading.RLock()
        self._con = sqlite3.connect(self.path, check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._con.executescript(
                """
                CREATE TABLE IF NOT EXISTS api_keys (
                    id TEXT PRIMARY KEY,
                    prefix TEXT NOT NULL,
                    key_hash TEXT NOT NULL UNIQUE,
                    owner_id TEXT,
                    plan TEXT NOT NULL DEFAULT 'default',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at REAL NOT NULL,
                    last_used_at REAL
                );
                CREATE TABLE IF NOT EXISTS usage_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    api_key_id TEXT NOT NULL,
                    module TEXT NOT NULL,
                    action TEXT NOT NULL,
                    ticker_days INTEGER NOT NULL DEFAULT 0,
                    trades INTEGER NOT NULL DEFAULT 0,
                    ts REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS backtest_results (
                    job_id TEXT PRIMARY KEY,
                    api_key_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    meta_json TEXT NOT NULL,
                    ts REAL NOT NULL
                );
                """
            )
            self._con.commit()

    # ── API keys ─────────────────────────────────────────────────────────────
    def create_api_key(
        self, owner_id: Optional[str] = None, plan: str = "default", test: bool = False
    ) -> tuple[str, ApiKeyRow]:
        """Create a key. Returns (plaintext_token, row). Plaintext shown once."""
        token, prefix = new_token(test=test)
        kid = "key_" + secrets.token_hex(8)
        row = ApiKeyRow(
            id=kid, prefix=prefix, owner_id=owner_id, plan=plan,
            status="active", created_at=_now(), last_used_at=None,
        )
        with self._lock:
            self._con.execute(
                "INSERT INTO api_keys (id, prefix, key_hash, owner_id, plan, status, created_at, last_used_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (kid, prefix, hash_token(token), owner_id, plan, "active", row.created_at, None),
            )
            self._con.commit()
        return token, row

    def get_key_by_token(self, token: str) -> Optional[ApiKeyRow]:
        h = hash_token(token)
        with self._lock:
            r = self._con.execute(
                "SELECT * FROM api_keys WHERE key_hash = ?", (h,)
            ).fetchone()
        if not r:
            return None
        return ApiKeyRow(
            id=r["id"], prefix=r["prefix"], owner_id=r["owner_id"], plan=r["plan"],
            status=r["status"], created_at=r["created_at"], last_used_at=r["last_used_at"],
        )

    def touch_key(self, key_id: str) -> None:
        with self._lock:
            self._con.execute(
                "UPDATE api_keys SET last_used_at = ? WHERE id = ?", (_now(), key_id)
            )
            self._con.commit()

    def revoke_key(self, key_id: str) -> None:
        with self._lock:
            self._con.execute(
                "UPDATE api_keys SET status = 'revoked' WHERE id = ?", (key_id,)
            )
            self._con.commit()

    # ── Usage ledger ─────────────────────────────────────────────────────────
    def record_usage(
        self, api_key_id: str, module: str, action: str, ticker_days: int = 0, trades: int = 0
    ) -> None:
        with self._lock:
            self._con.execute(
                "INSERT INTO usage_ledger (api_key_id, module, action, ticker_days, trades, ts)"
                " VALUES (?,?,?,?,?,?)",
                (api_key_id, module, action, int(ticker_days), int(trades), _now()),
            )
            self._con.commit()

    def usage_since(self, api_key_id: str, since_ts: float) -> dict:
        with self._lock:
            r = self._con.execute(
                "SELECT COUNT(*) n, COALESCE(SUM(ticker_days),0) td, COALESCE(SUM(trades),0) tr"
                " FROM usage_ledger WHERE api_key_id = ? AND ts >= ?",
                (api_key_id, since_ts),
            ).fetchone()
        return {"runs": r["n"], "ticker_days": r["td"], "trades": r["tr"]}

    # ── Backtest results ─────────────────────────────────────────────────────
    def save_result(
        self, job_id: str, api_key_id: str, status: str, raw: dict, meta: dict
    ) -> None:
        with self._lock:
            self._con.execute(
                "INSERT OR REPLACE INTO backtest_results (job_id, api_key_id, status, raw_json, meta_json, ts)"
                " VALUES (?,?,?,?,?,?)",
                (job_id, api_key_id, status, json.dumps(raw), json.dumps(meta), _now()),
            )
            self._con.commit()

    def get_result(self, job_id: str, api_key_id: str) -> Optional[dict]:
        with self._lock:
            r = self._con.execute(
                "SELECT * FROM backtest_results WHERE job_id = ? AND api_key_id = ?",
                (job_id, api_key_id),
            ).fetchone()
        if not r:
            return None
        return {
            "job_id": r["job_id"], "status": r["status"],
            "raw": json.loads(r["raw_json"]), "meta": json.loads(r["meta_json"]),
        }

    def close(self) -> None:
        with self._lock:
            self._con.close()


# ── Singleton accessor (overridable in tests via set_store) ──────────────────
_store: Optional[Store] = None
_store_lock = threading.Lock()


def get_store() -> Store:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = Store()
    return _store


def set_store(store: Optional[Store]) -> None:
    global _store
    _store = store
