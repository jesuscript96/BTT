"""
Clerk JWT verification for FastAPI.

Verifies Clerk session tokens (RS256) against the instance JWKS. The issuer is
read from CLERK_ISSUER, or derived from CLERK_PUBLISHABLE_KEY when not set.

Enforcement is gated by CLERK_AUTH_ENABLED so the API keeps working unchanged
when the env is absent (e.g. prod that has not been migrated yet): with auth
disabled the dependencies resolve to a None user_id and all data stays visible
via NULL-tolerant scoping (see scope_clause).
"""
import base64
import os
import threading
import time
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastapi import Header, HTTPException
from jose import jwt
from jose.utils import base64url_decode  # noqa: F401  (ensures jose crypto backend is present)

# Module-level config below reads env at import time, which can happen before
# database.py's load_dotenv() runs — load here so CLERK_* is always available.
load_dotenv()


def _derive_issuer() -> Optional[str]:
    """Return the Clerk issuer URL from env, or decode it from the publishable key."""
    explicit = os.getenv("CLERK_ISSUER", "").strip()
    if explicit:
        return explicit.rstrip("/")

    pk = os.getenv("CLERK_PUBLISHABLE_KEY", "").strip()
    if not pk:
        return None
    # pk_test_<base64('frontend-api$')> / pk_live_<...>
    try:
        b64 = pk.split("_", 2)[-1]
        b64 += "=" * (-len(b64) % 4)  # restore padding
        decoded = base64.b64decode(b64).decode("utf-8")
        host = decoded.rstrip("$").strip("/")
        if not host:
            return None
        return f"https://{host}"
    except Exception:
        return None


ISSUER = _derive_issuer()
JWKS_URL = os.getenv("CLERK_JWKS_URL", "").strip() or (f"{ISSUER}/.well-known/jwks.json" if ISSUER else "")
AUTH_ENABLED = os.getenv("CLERK_AUTH_ENABLED", "false").lower() == "true"

_JWKS_TTL_SECONDS = 3600
_jwks_cache: dict = {"keys": None, "fetched_at": 0.0}
_jwks_lock = threading.Lock()


def _get_jwks(force: bool = False) -> dict:
    """Fetch and cache the instance JWKS. Refetches on TTL expiry or when forced."""
    now = time.time()
    if (
        not force
        and _jwks_cache["keys"] is not None
        and (now - _jwks_cache["fetched_at"]) < _JWKS_TTL_SECONDS
    ):
        return _jwks_cache["keys"]

    with _jwks_lock:
        # Re-check inside the lock to avoid a stampede of refetches.
        now = time.time()
        if (
            not force
            and _jwks_cache["keys"] is not None
            and (now - _jwks_cache["fetched_at"]) < _JWKS_TTL_SECONDS
        ):
            return _jwks_cache["keys"]

        if not JWKS_URL:
            raise HTTPException(status_code=500, detail="Clerk issuer not configured")
        try:
            resp = httpx.get(JWKS_URL, timeout=5.0)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            # Serve a stale cache rather than locking everyone out on a transient failure.
            if _jwks_cache["keys"] is not None:
                return _jwks_cache["keys"]
            raise HTTPException(status_code=503, detail=f"Could not reach Clerk JWKS: {e}")

        _jwks_cache["keys"] = data
        _jwks_cache["fetched_at"] = now
        return data


def _find_key(jwks: dict, kid: str) -> Optional[dict]:
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return key
    return None


def verify_clerk_token(token: str) -> dict:
    """Verify a Clerk session JWT and return its claims. Raises 401 on any failure."""
    if not ISSUER:
        raise HTTPException(status_code=500, detail="Clerk issuer not configured")
    try:
        header = jwt.get_unverified_header(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Malformed token")

    kid = header.get("kid")
    if not kid:
        raise HTTPException(status_code=401, detail="Token missing kid")

    jwks = _get_jwks()
    key = _find_key(jwks, kid)
    if key is None:
        # Key rotation: force a refetch once before giving up.
        jwks = _get_jwks(force=True)
        key = _find_key(jwks, kid)
    if key is None:
        raise HTTPException(status_code=401, detail="Signing key not found")

    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=ISSUER,
            # Clerk session tokens carry azp (authorized party), not a standard aud.
            options={"verify_aud": False},
        )
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

    return claims


def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


def get_optional_user_id(authorization: Optional[str] = Header(default=None)) -> Optional[str]:
    """
    Resolve the caller's Clerk user_id for data scoping.

    - Auth disabled  -> None (legacy/shared behavior; reads stay unscoped).
    - Auth enabled, valid token -> the Clerk `sub`.
    - Auth enabled, missing/invalid token -> None (caller is NOT forced here;
      use get_current_user_id on endpoints that must reject anonymous access).
    """
    if not AUTH_ENABLED:
        return None
    token = _extract_bearer(authorization)
    if not token:
        return None
    try:
        claims = verify_clerk_token(token)
    except HTTPException:
        return None
    return claims.get("sub")


def get_current_user_id(authorization: Optional[str] = Header(default=None)) -> Optional[str]:
    """
    Require a valid Clerk session when auth is enabled; return the user_id.

    When auth is disabled this returns None so existing deployments keep working.
    """
    if not AUTH_ENABLED:
        return None
    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    claims = verify_clerk_token(token)
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Token has no subject")
    return sub


def scope_clause(user_id: Optional[str], column: str = "user_id"):
    """
    Build a NULL-tolerant ownership filter for user-scoped reads.

    Returns (sql_fragment, params). When user_id is None (auth disabled) the
    filter is empty so all rows are returned exactly as before. When set, the
    caller sees their own rows plus legacy rows that predate scoping (user_id
    IS NULL), so existing data and the read-only GCS fallback never vanish.
    """
    if not user_id:
        return "", []
    return f" AND ({column} = ? OR {column} IS NULL)", [user_id]
