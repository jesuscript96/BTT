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
    label: Optional[str] = None
    is_test: bool = False


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
            # Safe migration: add columns introduced after first release.
            for ddl in (
                "ALTER TABLE api_keys ADD COLUMN label TEXT",
                "ALTER TABLE api_keys ADD COLUMN is_test INTEGER NOT NULL DEFAULT 0",
            ):
                try:
                    self._con.execute(ddl)
                except sqlite3.OperationalError:
                    pass  # column already exists
            self._con.commit()

    # ── API keys ─────────────────────────────────────────────────────────────
    def create_api_key(
        self,
        owner_id: Optional[str] = None,
        plan: str = "default",
        test: bool = False,
        label: Optional[str] = None,
    ) -> tuple[str, ApiKeyRow]:
        """Create a key. Returns (plaintext_token, row). Plaintext shown once."""
        token, prefix = new_token(test=test)
        kid = "key_" + secrets.token_hex(8)
        row = ApiKeyRow(
            id=kid, prefix=prefix, owner_id=owner_id, plan=plan,
            status="active", created_at=_now(), last_used_at=None,
            label=label, is_test=test,
        )
        with self._lock:
            self._con.execute(
                "INSERT INTO api_keys (id, prefix, key_hash, owner_id, plan, status, created_at, last_used_at, label, is_test)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (kid, prefix, hash_token(token), owner_id, plan, "active", row.created_at, None, label, 1 if test else 0),
            )
            self._con.commit()
        return token, row

    def _row_to_key(self, r: sqlite3.Row) -> ApiKeyRow:
        keys = r.keys()
        return ApiKeyRow(
            id=r["id"], prefix=r["prefix"], owner_id=r["owner_id"], plan=r["plan"],
            status=r["status"], created_at=r["created_at"], last_used_at=r["last_used_at"],
            label=r["label"] if "label" in keys else None,
            is_test=bool(r["is_test"]) if "is_test" in keys else False,
        )

    def get_key_by_token(self, token: str) -> Optional[ApiKeyRow]:
        h = hash_token(token)
        with self._lock:
            r = self._con.execute(
                "SELECT * FROM api_keys WHERE key_hash = ?", (h,)
            ).fetchone()
        return self._row_to_key(r) if r else None

    def get_key_by_id(self, key_id: str) -> Optional[ApiKeyRow]:
        with self._lock:
            r = self._con.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone()
        return self._row_to_key(r) if r else None

    def list_keys_by_owner(self, owner_id: str) -> list[ApiKeyRow]:
        with self._lock:
            rows = self._con.execute(
                "SELECT * FROM api_keys WHERE owner_id = ? ORDER BY created_at DESC", (owner_id,)
            ).fetchall()
        return [self._row_to_key(r) for r in rows]

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

    def usage_for_owner(self, owner_id: str, since_ts: float) -> dict:
        """Aggregate usage across all of an owner's keys (for the dashboard)."""
        with self._lock:
            r = self._con.execute(
                "SELECT COUNT(*) n, COALESCE(SUM(l.ticker_days),0) td, COALESCE(SUM(l.trades),0) tr"
                " FROM usage_ledger l JOIN api_keys k ON k.id = l.api_key_id"
                " WHERE k.owner_id = ? AND l.ts >= ?",
                (owner_id, since_ts),
            ).fetchone()
        return {"runs": r["n"], "ticker_days": r["td"], "trades": r["tr"]}

    def recent_activity_for_owner(self, owner_id: str, limit: int = 20) -> list[dict]:
        """Recent ledger entries across the owner's keys (most recent first)."""
        with self._lock:
            rows = self._con.execute(
                "SELECT l.module, l.action, l.ticker_days, l.trades, l.ts, k.prefix"
                " FROM usage_ledger l JOIN api_keys k ON k.id = l.api_key_id"
                " WHERE k.owner_id = ? ORDER BY l.ts DESC LIMIT ?",
                (owner_id, int(limit)),
            ).fetchall()
        return [
            {
                "module": r["module"], "action": r["action"],
                "ticker_days": r["ticker_days"], "trades": r["trades"],
                "ts": r["ts"], "key_prefix": r["prefix"],
            }
            for r in rows
        ]

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
