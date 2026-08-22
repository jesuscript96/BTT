"""Persistence for billing/subscription state (Fase 2A).

Thread-safe SQLite store, mirroring the pattern of app/api_public/core/store.py
(one connection guarded by an RLock — fine for the in-process, low-concurrency
webhook/read profile). This is the authoritative local MIRROR of Stripe: a
materialized view of customers/subscriptions/invoices, reconstructible from
Stripe if lost (reconciliation job, Fase 2D). Stripe stays the source of truth
for billing; this table is the source of truth for the ACCESS STATE the app
reads (resolve_tier, Fase 2B).

Scope of this phase: DATA ONLY. No Stripe SDK, no HTTP, no tier policy. The DDL
is docs/FASE1_DISENO_TRIAL_SUSCRIPCION_STRIPE.md §2 verbatim, plus trial_ledger
(anti-recycle, §4) which the same doc specifies.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Optional

from app.billing import config


def _now() -> float:
    return time.time()


# Trial-override bounds (Path B): admins may grant a per-user PREFERENTIAL trial
# of 1..30 days (decision Adrian #4). Enforced in set_trial_override + the CLI so
# a bad value never reaches Stripe's trial_period_days.
MIN_TRIAL_OVERRIDE_DAYS = 1
MAX_TRIAL_OVERRIDE_DAYS = 30


# ── Row types ─────────────────────────────────────────────────────────────────
@dataclass
class BillingCustomer:
    user_id: str
    stripe_customer_id: str
    email: Optional[str]
    created_at: float
    updated_at: float


@dataclass
class Subscription:
    stripe_subscription_id: str
    user_id: str
    stripe_customer_id: str
    status: str  # trialing|active|past_due|canceled|unpaid|incomplete|incomplete_expired
    price_id: Optional[str]
    currency: Optional[str]
    trial_end: Optional[float]
    current_period_end: Optional[float]
    cancel_at_period_end: bool
    canceled_at: Optional[float]
    default_pm_id: Optional[str]
    created_at: float
    updated_at: float


@dataclass
class PaymentMethod:
    stripe_pm_id: str
    user_id: str
    brand: Optional[str]
    last4: Optional[str]
    exp_month: Optional[int]
    exp_year: Optional[int]
    is_default: bool
    updated_at: float


@dataclass
class Invoice:
    stripe_invoice_id: str
    user_id: str
    subscription_id: Optional[str]
    status: str  # paid|open|void|uncollectible|draft
    amount_due: Optional[int]
    amount_paid: Optional[int]
    currency: Optional[str]
    hosted_invoice_url: Optional[str]
    invoice_pdf: Optional[str]
    period_start: Optional[float]
    period_end: Optional[float]
    created_at: float


@dataclass
class EntitlementGrant:
    user_id: str
    grant_tier: str  # 'Pro' (comped/migration-trial) | 'Admin'
    reason: Optional[str]
    granted_by: Optional[str]
    expires_at: Optional[float]  # NULL = perpetual
    created_at: float


@dataclass
class TrialOverride:
    """A per-user preferential trial length (Path B / B1). Set by an admin
    (CLI only, no public endpoint), consumed ONE-SHOT at the next Checkout so it
    cannot be recycled: consumed_at != NULL means it was already handed out."""
    user_id: str
    days: int              # 1..30 (validated on write)
    reason: Optional[str]
    granted_by: Optional[str]
    created_at: float
    consumed_at: Optional[float]  # NULL = still pending; set once when used


class Store:
    """Thread-safe SQLite-backed billing store."""

    def __init__(self, path: Optional[str] = None):
        self.path = path or config.BILLING_DB_PATH
        self._lock = threading.RLock()
        self._con = sqlite3.connect(self.path, check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._con.executescript(
                """
                CREATE TABLE IF NOT EXISTS billing_customers (
                    user_id            TEXT PRIMARY KEY,
                    stripe_customer_id TEXT NOT NULL UNIQUE,
                    email              TEXT,
                    created_at         REAL NOT NULL,
                    updated_at         REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS subscriptions (
                    stripe_subscription_id  TEXT PRIMARY KEY,
                    user_id                 TEXT NOT NULL,
                    stripe_customer_id      TEXT NOT NULL,
                    status                  TEXT NOT NULL,
                    price_id                TEXT,
                    currency                TEXT,
                    trial_end               REAL,
                    current_period_end      REAL,
                    cancel_at_period_end    INTEGER NOT NULL DEFAULT 0,
                    canceled_at             REAL,
                    default_pm_id           TEXT,
                    created_at              REAL NOT NULL,
                    updated_at              REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sub_user ON subscriptions(user_id);

                CREATE TABLE IF NOT EXISTS payment_methods (
                    stripe_pm_id  TEXT PRIMARY KEY,
                    user_id       TEXT NOT NULL,
                    brand         TEXT,
                    last4         TEXT,
                    exp_month     INTEGER,
                    exp_year      INTEGER,
                    is_default    INTEGER NOT NULL DEFAULT 0,
                    updated_at    REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_pm_user ON payment_methods(user_id);

                CREATE TABLE IF NOT EXISTS invoices (
                    stripe_invoice_id   TEXT PRIMARY KEY,
                    user_id             TEXT NOT NULL,
                    subscription_id     TEXT,
                    status              TEXT NOT NULL,
                    amount_due          INTEGER,
                    amount_paid         INTEGER,
                    currency            TEXT,
                    hosted_invoice_url  TEXT,
                    invoice_pdf         TEXT,
                    period_start        REAL,
                    period_end          REAL,
                    created_at          REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_inv_user ON invoices(user_id);

                CREATE TABLE IF NOT EXISTS entitlement_grants (
                    user_id      TEXT PRIMARY KEY,
                    grant_tier   TEXT NOT NULL,
                    reason       TEXT,
                    granted_by   TEXT,
                    expires_at   REAL,
                    created_at   REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS webhook_events (
                    stripe_event_id TEXT PRIMARY KEY,
                    type            TEXT NOT NULL,
                    processed_at    REAL NOT NULL
                );

                -- Anti-recycle: a trial is unique per IDENTITY, not per user_id
                -- (docs Fase 1 §4). identity_key = normalized email and/or Stripe
                -- PaymentMethod.card.fingerprint.
                CREATE TABLE IF NOT EXISTS trial_ledger (
                    identity_key   TEXT PRIMARY KEY,
                    kind           TEXT NOT NULL,   -- 'email' | 'card_fingerprint'
                    first_trial_at REAL NOT NULL
                );

                -- Per-user preferential trial length (Path B / B1, decision
                -- Adrian #4). Admin-granted via CLI; consumed ONE-SHOT at the
                -- next Checkout (consumed_at). Keyed by Clerk user_id.
                CREATE TABLE IF NOT EXISTS trial_overrides (
                    user_id      TEXT PRIMARY KEY,
                    days         INTEGER NOT NULL,   -- 1..30 (validated on write)
                    reason       TEXT,
                    granted_by   TEXT,
                    created_at   REAL NOT NULL,
                    consumed_at  REAL                -- NULL = pending; set when used
                );

                -- Courtesy/comped colleagues by EMAIL (Fase 3). Managed via CLI
                -- (no Coolify redeploy). On login the /me summary reads the user's
                -- TRUSTED email from the Clerk JWT; if listed, it materializes a
                -- perpetual Pro grant (reason='comped') keyed by user_id so the
                -- product gate honors it too. Removing the email revokes on next /me.
                CREATE TABLE IF NOT EXISTS comped_emails (
                    email        TEXT PRIMARY KEY,   -- normalized (lower/trim)
                    granted_by   TEXT,
                    created_at   REAL NOT NULL
                );

                -- Admins by EMAIL (Fase 3, decision #1). Same mechanism as
                -- comped_emails but materializes an ADMIN grant (reason='admin')
                -- keyed by user_id, so the product gate + /me both see "Admin".
                -- Migration-proof: the email survives a Clerk-instance change,
                -- the user_id doesn't. Admin > comped in the reconcile.
                CREATE TABLE IF NOT EXISTS admin_emails (
                    email        TEXT PRIMARY KEY,   -- normalized (lower/trim)
                    granted_by   TEXT,
                    created_at   REAL NOT NULL
                );

                -- Preferential trial length by EMAIL (Fase 3 improvement over the
                -- user_id-keyed trial_overrides). On login the /me summary seeds a
                -- ONE-SHOT trial_override for the user_id (only if they have none
                -- yet — never re-arms, so the preferential trial can't recycle).
                -- Migration-proof: the same email re-seeds under the new user_id
                -- after a Clerk-instance change, so no manual re-seed is needed.
                CREATE TABLE IF NOT EXISTS trial_override_emails (
                    email        TEXT PRIMARY KEY,   -- normalized (lower/trim)
                    days         INTEGER NOT NULL,   -- 1..30 (validated on write)
                    reason       TEXT,
                    granted_by   TEXT,
                    created_at   REAL NOT NULL
                );
                """
            )
            self._con.commit()

    # ── Customers ────────────────────────────────────────────────────────────
    def upsert_customer(
        self, user_id: str, stripe_customer_id: str, email: Optional[str] = None
    ) -> BillingCustomer:
        now = _now()
        with self._lock:
            self._con.execute(
                "INSERT INTO billing_customers (user_id, stripe_customer_id, email, created_at, updated_at)"
                " VALUES (?,?,?,?,?)"
                " ON CONFLICT(user_id) DO UPDATE SET"
                "   stripe_customer_id=excluded.stripe_customer_id,"
                "   email=excluded.email,"
                "   updated_at=excluded.updated_at",
                (user_id, stripe_customer_id, email, now, now),
            )
            self._con.commit()
        return self.get_customer_by_user(user_id)  # type: ignore[return-value]

    def get_customer_by_user(self, user_id: str) -> Optional[BillingCustomer]:
        with self._lock:
            r = self._con.execute(
                "SELECT * FROM billing_customers WHERE user_id = ?", (user_id,)
            ).fetchone()
        return _to_customer(r) if r else None

    def get_customer_by_stripe_id(self, stripe_customer_id: str) -> Optional[BillingCustomer]:
        with self._lock:
            r = self._con.execute(
                "SELECT * FROM billing_customers WHERE stripe_customer_id = ?",
                (stripe_customer_id,),
            ).fetchone()
        return _to_customer(r) if r else None

    def list_customers(self) -> list[BillingCustomer]:
        """All customers (for the reconciliation job)."""
        with self._lock:
            rows = self._con.execute(
                "SELECT * FROM billing_customers ORDER BY created_at ASC"
            ).fetchall()
        return [_to_customer(r) for r in rows]

    # ── Subscriptions ────────────────────────────────────────────────────────
    def upsert_subscription(
        self,
        stripe_subscription_id: str,
        user_id: str,
        stripe_customer_id: str,
        status: str,
        price_id: Optional[str] = None,
        currency: Optional[str] = None,
        trial_end: Optional[float] = None,
        current_period_end: Optional[float] = None,
        cancel_at_period_end: bool = False,
        canceled_at: Optional[float] = None,
        default_pm_id: Optional[str] = None,
    ) -> Subscription:
        now = _now()
        with self._lock:
            self._con.execute(
                "INSERT INTO subscriptions (stripe_subscription_id, user_id, stripe_customer_id,"
                "   status, price_id, currency, trial_end, current_period_end,"
                "   cancel_at_period_end, canceled_at, default_pm_id, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(stripe_subscription_id) DO UPDATE SET"
                "   user_id=excluded.user_id,"
                "   stripe_customer_id=excluded.stripe_customer_id,"
                "   status=excluded.status,"
                "   price_id=excluded.price_id,"
                "   currency=excluded.currency,"
                "   trial_end=excluded.trial_end,"
                "   current_period_end=excluded.current_period_end,"
                "   cancel_at_period_end=excluded.cancel_at_period_end,"
                "   canceled_at=excluded.canceled_at,"
                "   default_pm_id=excluded.default_pm_id,"
                "   updated_at=excluded.updated_at",
                (
                    stripe_subscription_id, user_id, stripe_customer_id, status, price_id,
                    currency, trial_end, current_period_end, 1 if cancel_at_period_end else 0,
                    canceled_at, default_pm_id, now, now,
                ),
            )
            self._con.commit()
        return self.get_subscription(stripe_subscription_id)  # type: ignore[return-value]

    def get_subscription(self, stripe_subscription_id: str) -> Optional[Subscription]:
        with self._lock:
            r = self._con.execute(
                "SELECT * FROM subscriptions WHERE stripe_subscription_id = ?",
                (stripe_subscription_id,),
            ).fetchone()
        return _to_subscription(r) if r else None

    def list_subscriptions_for_user(self, user_id: str) -> list[Subscription]:
        with self._lock:
            rows = self._con.execute(
                "SELECT * FROM subscriptions WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        return [_to_subscription(r) for r in rows]

    def get_latest_subscription_for_user(self, user_id: str) -> Optional[Subscription]:
        """Most recently created subscription for the user. In the MVP there is
        one active subscription per user; resolve_tier (2B) interprets its
        status. History is kept but the latest row drives the current state."""
        with self._lock:
            r = self._con.execute(
                "SELECT * FROM subscriptions WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        return _to_subscription(r) if r else None

    # ── Payment methods ──────────────────────────────────────────────────────
    def upsert_payment_method(
        self,
        stripe_pm_id: str,
        user_id: str,
        brand: Optional[str] = None,
        last4: Optional[str] = None,
        exp_month: Optional[int] = None,
        exp_year: Optional[int] = None,
        is_default: bool = False,
    ) -> PaymentMethod:
        now = _now()
        with self._lock:
            self._con.execute(
                "INSERT INTO payment_methods (stripe_pm_id, user_id, brand, last4, exp_month,"
                "   exp_year, is_default, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?)"
                " ON CONFLICT(stripe_pm_id) DO UPDATE SET"
                "   user_id=excluded.user_id,"
                "   brand=excluded.brand,"
                "   last4=excluded.last4,"
                "   exp_month=excluded.exp_month,"
                "   exp_year=excluded.exp_year,"
                "   is_default=excluded.is_default,"
                "   updated_at=excluded.updated_at",
                (stripe_pm_id, user_id, brand, last4, exp_month, exp_year,
                 1 if is_default else 0, now),
            )
            self._con.commit()
        return self.get_payment_method(stripe_pm_id)  # type: ignore[return-value]

    def get_payment_method(self, stripe_pm_id: str) -> Optional[PaymentMethod]:
        with self._lock:
            r = self._con.execute(
                "SELECT * FROM payment_methods WHERE stripe_pm_id = ?", (stripe_pm_id,)
            ).fetchone()
        return _to_payment_method(r) if r else None

    def list_payment_methods(self, user_id: str) -> list[PaymentMethod]:
        with self._lock:
            rows = self._con.execute(
                "SELECT * FROM payment_methods WHERE user_id = ? ORDER BY is_default DESC, updated_at DESC",
                (user_id,),
            ).fetchall()
        return [_to_payment_method(r) for r in rows]

    def get_default_payment_method(self, user_id: str) -> Optional[PaymentMethod]:
        with self._lock:
            r = self._con.execute(
                "SELECT * FROM payment_methods WHERE user_id = ? AND is_default = 1 LIMIT 1",
                (user_id,),
            ).fetchone()
        return _to_payment_method(r) if r else None

    def set_default_payment_method(self, user_id: str, stripe_pm_id: str) -> None:
        """Mark one PM as default and clear the flag on the user's others,
        atomically, so at most one default exists per user."""
        now = _now()
        with self._lock:
            self._con.execute(
                "UPDATE payment_methods SET is_default = 0, updated_at = ?"
                " WHERE user_id = ? AND stripe_pm_id != ?",
                (now, user_id, stripe_pm_id),
            )
            self._con.execute(
                "UPDATE payment_methods SET is_default = 1, updated_at = ?"
                " WHERE user_id = ? AND stripe_pm_id = ?",
                (now, user_id, stripe_pm_id),
            )
            self._con.commit()

    # ── Invoices ─────────────────────────────────────────────────────────────
    def upsert_invoice(
        self,
        stripe_invoice_id: str,
        user_id: str,
        status: str,
        subscription_id: Optional[str] = None,
        amount_due: Optional[int] = None,
        amount_paid: Optional[int] = None,
        currency: Optional[str] = None,
        hosted_invoice_url: Optional[str] = None,
        invoice_pdf: Optional[str] = None,
        period_start: Optional[float] = None,
        period_end: Optional[float] = None,
    ) -> Invoice:
        now = _now()
        with self._lock:
            self._con.execute(
                "INSERT INTO invoices (stripe_invoice_id, user_id, subscription_id, status,"
                "   amount_due, amount_paid, currency, hosted_invoice_url, invoice_pdf,"
                "   period_start, period_end, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(stripe_invoice_id) DO UPDATE SET"
                "   user_id=excluded.user_id,"
                "   subscription_id=excluded.subscription_id,"
                "   status=excluded.status,"
                "   amount_due=excluded.amount_due,"
                "   amount_paid=excluded.amount_paid,"
                "   currency=excluded.currency,"
                "   hosted_invoice_url=excluded.hosted_invoice_url,"
                "   invoice_pdf=excluded.invoice_pdf,"
                "   period_start=excluded.period_start,"
                "   period_end=excluded.period_end",
                (stripe_invoice_id, user_id, subscription_id, status, amount_due, amount_paid,
                 currency, hosted_invoice_url, invoice_pdf, period_start, period_end, now),
            )
            self._con.commit()
        return self.get_invoice(stripe_invoice_id)  # type: ignore[return-value]

    def get_invoice(self, stripe_invoice_id: str) -> Optional[Invoice]:
        with self._lock:
            r = self._con.execute(
                "SELECT * FROM invoices WHERE stripe_invoice_id = ?", (stripe_invoice_id,)
            ).fetchone()
        return _to_invoice(r) if r else None

    def list_invoices(self, user_id: str) -> list[Invoice]:
        with self._lock:
            rows = self._con.execute(
                "SELECT * FROM invoices WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        return [_to_invoice(r) for r in rows]

    # ── Entitlement grants (comped / migration / admin) ──────────────────────
    def upsert_grant(
        self,
        user_id: str,
        grant_tier: str,
        reason: Optional[str] = None,
        granted_by: Optional[str] = None,
        expires_at: Optional[float] = None,
    ) -> EntitlementGrant:
        now = _now()
        with self._lock:
            self._con.execute(
                "INSERT INTO entitlement_grants (user_id, grant_tier, reason, granted_by, expires_at, created_at)"
                " VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(user_id) DO UPDATE SET"
                "   grant_tier=excluded.grant_tier,"
                "   reason=excluded.reason,"
                "   granted_by=excluded.granted_by,"
                "   expires_at=excluded.expires_at",
                (user_id, grant_tier, reason, granted_by, expires_at, now),
            )
            self._con.commit()
        return self.get_grant(user_id)  # type: ignore[return-value]

    def get_grant(self, user_id: str) -> Optional[EntitlementGrant]:
        with self._lock:
            r = self._con.execute(
                "SELECT * FROM entitlement_grants WHERE user_id = ?", (user_id,)
            ).fetchone()
        return _to_grant(r) if r else None

    def delete_grant(self, user_id: str) -> None:
        with self._lock:
            self._con.execute("DELETE FROM entitlement_grants WHERE user_id = ?", (user_id,))
            self._con.commit()

    # ── Webhook idempotency ──────────────────────────────────────────────────
    def mark_event_processed(self, stripe_event_id: str, type: str) -> bool:
        """Atomically claim a webhook event. Returns True if THIS call recorded
        it (process the event), False if it was already recorded (duplicate
        Stripe retry — skip). The PRIMARY KEY makes the claim race-free."""
        now = _now()
        with self._lock:
            try:
                self._con.execute(
                    "INSERT INTO webhook_events (stripe_event_id, type, processed_at) VALUES (?,?,?)",
                    (stripe_event_id, type, now),
                )
                self._con.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def is_event_processed(self, stripe_event_id: str) -> bool:
        with self._lock:
            r = self._con.execute(
                "SELECT 1 FROM webhook_events WHERE stripe_event_id = ?", (stripe_event_id,)
            ).fetchone()
        return r is not None

    # ── Trial ledger (anti-recycle) ──────────────────────────────────────────
    def record_trial(self, identity_key: str, kind: str) -> bool:
        """Record that an identity consumed a trial. Returns True if newly
        recorded, False if the identity had already used a trial (so the caller
        must offer Checkout WITHOUT a trial — immediate charge)."""
        now = _now()
        with self._lock:
            try:
                self._con.execute(
                    "INSERT INTO trial_ledger (identity_key, kind, first_trial_at) VALUES (?,?,?)",
                    (identity_key, kind, now),
                )
                self._con.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def has_used_trial(self, identity_key: str) -> bool:
        with self._lock:
            r = self._con.execute(
                "SELECT 1 FROM trial_ledger WHERE identity_key = ?", (identity_key,)
            ).fetchone()
        return r is not None

    # ── Trial overrides (Path B: per-user preferential trial length) ──────────
    def set_trial_override(
        self,
        user_id: str,
        days: int,
        reason: Optional[str] = None,
        granted_by: Optional[str] = None,
    ) -> TrialOverride:
        """Grant/replace a user's preferential trial. Re-setting RE-ARMS it
        (consumed_at back to NULL) — a deliberate admin re-grant. Raises
        ValueError if days is outside 1..30 so a bad value never reaches Stripe."""
        days = int(days)
        if not (MIN_TRIAL_OVERRIDE_DAYS <= days <= MAX_TRIAL_OVERRIDE_DAYS):
            raise ValueError(
                f"days must be {MIN_TRIAL_OVERRIDE_DAYS}..{MAX_TRIAL_OVERRIDE_DAYS}, got {days}"
            )
        now = _now()
        with self._lock:
            self._con.execute(
                "INSERT INTO trial_overrides (user_id, days, reason, granted_by, created_at, consumed_at)"
                " VALUES (?,?,?,?,?,NULL)"
                " ON CONFLICT(user_id) DO UPDATE SET"
                "   days=excluded.days,"
                "   reason=excluded.reason,"
                "   granted_by=excluded.granted_by,"
                "   created_at=excluded.created_at,"
                "   consumed_at=NULL",  # re-set re-arms the one-shot
                (user_id, days, reason, granted_by, now),
            )
            self._con.commit()
        return self.get_trial_override(user_id)  # type: ignore[return-value]

    def get_trial_override(self, user_id: str) -> Optional[TrialOverride]:
        with self._lock:
            r = self._con.execute(
                "SELECT * FROM trial_overrides WHERE user_id = ?", (user_id,)
            ).fetchone()
        return _to_trial_override(r) if r else None

    def consume_trial_override(self, user_id: str) -> Optional[int]:
        """Atomically claim the user's PENDING override and return its days, or
        None if there is no override or it was already consumed. The
        `consumed_at IS NULL` guard makes the one-shot race-free (at most one
        caller ever gets the days)."""
        now = _now()
        with self._lock:
            cur = self._con.execute(
                "UPDATE trial_overrides SET consumed_at = ?"
                " WHERE user_id = ? AND consumed_at IS NULL",
                (now, user_id),
            )
            self._con.commit()
            if cur.rowcount == 0:
                return None
            r = self._con.execute(
                "SELECT days FROM trial_overrides WHERE user_id = ?", (user_id,)
            ).fetchone()
        return int(r["days"]) if r else None

    def rearm_trial_override(self, user_id: str) -> None:
        """Give a consumed override back (consumed_at -> NULL). Used to undo a
        claim when the Checkout call that consumed it failed before a session
        was created, so a transient Stripe error never burns the grant."""
        with self._lock:
            self._con.execute(
                "UPDATE trial_overrides SET consumed_at = NULL WHERE user_id = ?",
                (user_id,),
            )
            self._con.commit()

    def delete_trial_override(self, user_id: str) -> None:
        with self._lock:
            self._con.execute("DELETE FROM trial_overrides WHERE user_id = ?", (user_id,))
            self._con.commit()

    def list_trial_overrides(self) -> list[TrialOverride]:
        """All overrides (for the admin CLI --list / audit)."""
        with self._lock:
            rows = self._con.execute(
                "SELECT * FROM trial_overrides ORDER BY created_at DESC"
            ).fetchall()
        return [_to_trial_override(r) for r in rows]

    # ── Comped emails (Fase 3 — courtesy colleagues by email) ────────────────
    @staticmethod
    def _norm_email(email: str) -> str:
        return email.strip().lower()

    def add_comped_email(self, email: str, granted_by: Optional[str] = None) -> None:
        """Add (or refresh) an email to the courtesy list. Idempotent."""
        with self._lock:
            self._con.execute(
                "INSERT INTO comped_emails (email, granted_by, created_at) VALUES (?,?,?)"
                " ON CONFLICT(email) DO UPDATE SET granted_by=excluded.granted_by",
                (self._norm_email(email), granted_by, _now()),
            )
            self._con.commit()

    def remove_comped_email(self, email: str) -> None:
        with self._lock:
            self._con.execute(
                "DELETE FROM comped_emails WHERE email = ?", (self._norm_email(email),)
            )
            self._con.commit()

    def has_comped_email(self, email: str) -> bool:
        with self._lock:
            row = self._con.execute(
                "SELECT 1 FROM comped_emails WHERE email = ?", (self._norm_email(email),)
            ).fetchone()
        return row is not None

    def list_comped_emails(self) -> list[str]:
        with self._lock:
            rows = self._con.execute(
                "SELECT email FROM comped_emails ORDER BY created_at DESC"
            ).fetchall()
        return [r["email"] for r in rows]

    # ── Admin emails (Fase 3 — admins by email, decision #1) ─────────────────
    def add_admin_email(self, email: str, granted_by: Optional[str] = None) -> None:
        """Add (or refresh) an email to the admin list. Idempotent."""
        with self._lock:
            self._con.execute(
                "INSERT INTO admin_emails (email, granted_by, created_at) VALUES (?,?,?)"
                " ON CONFLICT(email) DO UPDATE SET granted_by=excluded.granted_by",
                (self._norm_email(email), granted_by, _now()),
            )
            self._con.commit()

    def remove_admin_email(self, email: str) -> None:
        with self._lock:
            self._con.execute(
                "DELETE FROM admin_emails WHERE email = ?", (self._norm_email(email),)
            )
            self._con.commit()

    def has_admin_email(self, email: str) -> bool:
        with self._lock:
            row = self._con.execute(
                "SELECT 1 FROM admin_emails WHERE email = ?", (self._norm_email(email),)
            ).fetchone()
        return row is not None

    def list_admin_emails(self) -> list[str]:
        with self._lock:
            rows = self._con.execute(
                "SELECT email FROM admin_emails ORDER BY created_at DESC"
            ).fetchall()
        return [r["email"] for r in rows]

    # ── Trial-override emails (Fase 3 — preferential trial by email) ──────────
    def add_trial_override_email(
        self,
        email: str,
        days: int,
        reason: Optional[str] = None,
        granted_by: Optional[str] = None,
    ) -> None:
        """Add (or refresh) an email → preferential trial length. Idempotent.
        Validates days 1..30 (same bound as set_trial_override) so a bad value
        never reaches Stripe's trial_period_days."""
        days = int(days)
        if not (MIN_TRIAL_OVERRIDE_DAYS <= days <= MAX_TRIAL_OVERRIDE_DAYS):
            raise ValueError(
                f"days must be {MIN_TRIAL_OVERRIDE_DAYS}..{MAX_TRIAL_OVERRIDE_DAYS}, got {days}"
            )
        with self._lock:
            self._con.execute(
                "INSERT INTO trial_override_emails (email, days, reason, granted_by, created_at)"
                " VALUES (?,?,?,?,?)"
                " ON CONFLICT(email) DO UPDATE SET"
                "   days=excluded.days,"
                "   reason=excluded.reason,"
                "   granted_by=excluded.granted_by",
                (self._norm_email(email), days, reason, granted_by, _now()),
            )
            self._con.commit()

    def remove_trial_override_email(self, email: str) -> None:
        with self._lock:
            self._con.execute(
                "DELETE FROM trial_override_emails WHERE email = ?",
                (self._norm_email(email),),
            )
            self._con.commit()

    def get_trial_override_email(self, email: str) -> Optional[tuple[int, Optional[str], Optional[str]]]:
        """Return (days, reason, granted_by) for a listed email, or None."""
        with self._lock:
            r = self._con.execute(
                "SELECT days, reason, granted_by FROM trial_override_emails WHERE email = ?",
                (self._norm_email(email),),
            ).fetchone()
        return (int(r["days"]), r["reason"], r["granted_by"]) if r else None

    def list_trial_override_emails(self) -> list[tuple[str, int]]:
        """(email, days) pairs for the admin CLI --list / audit."""
        with self._lock:
            rows = self._con.execute(
                "SELECT email, days FROM trial_override_emails ORDER BY created_at DESC"
            ).fetchall()
        return [(r["email"], int(r["days"])) for r in rows]

    def close(self) -> None:
        with self._lock:
            self._con.close()


# ── Row mappers ───────────────────────────────────────────────────────────────
def _to_customer(r: sqlite3.Row) -> BillingCustomer:
    return BillingCustomer(
        user_id=r["user_id"], stripe_customer_id=r["stripe_customer_id"],
        email=r["email"], created_at=r["created_at"], updated_at=r["updated_at"],
    )


def _to_subscription(r: sqlite3.Row) -> Subscription:
    return Subscription(
        stripe_subscription_id=r["stripe_subscription_id"], user_id=r["user_id"],
        stripe_customer_id=r["stripe_customer_id"], status=r["status"], price_id=r["price_id"],
        currency=r["currency"], trial_end=r["trial_end"], current_period_end=r["current_period_end"],
        cancel_at_period_end=bool(r["cancel_at_period_end"]), canceled_at=r["canceled_at"],
        default_pm_id=r["default_pm_id"], created_at=r["created_at"], updated_at=r["updated_at"],
    )


def _to_payment_method(r: sqlite3.Row) -> PaymentMethod:
    return PaymentMethod(
        stripe_pm_id=r["stripe_pm_id"], user_id=r["user_id"], brand=r["brand"], last4=r["last4"],
        exp_month=r["exp_month"], exp_year=r["exp_year"], is_default=bool(r["is_default"]),
        updated_at=r["updated_at"],
    )


def _to_invoice(r: sqlite3.Row) -> Invoice:
    return Invoice(
        stripe_invoice_id=r["stripe_invoice_id"], user_id=r["user_id"],
        subscription_id=r["subscription_id"], status=r["status"], amount_due=r["amount_due"],
        amount_paid=r["amount_paid"], currency=r["currency"],
        hosted_invoice_url=r["hosted_invoice_url"], invoice_pdf=r["invoice_pdf"],
        period_start=r["period_start"], period_end=r["period_end"], created_at=r["created_at"],
    )


def _to_grant(r: sqlite3.Row) -> EntitlementGrant:
    return EntitlementGrant(
        user_id=r["user_id"], grant_tier=r["grant_tier"], reason=r["reason"],
        granted_by=r["granted_by"], expires_at=r["expires_at"], created_at=r["created_at"],
    )


def _to_trial_override(r: sqlite3.Row) -> TrialOverride:
    return TrialOverride(
        user_id=r["user_id"], days=r["days"], reason=r["reason"],
        granted_by=r["granted_by"], created_at=r["created_at"], consumed_at=r["consumed_at"],
    )


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
