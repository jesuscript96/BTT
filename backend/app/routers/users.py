"""User identity endpoints backed by Clerk session verification."""
from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from app.auth.clerk import AUTH_ENABLED, verify_clerk_token, _extract_bearer

router = APIRouter()


@router.get("/me")
def get_me(authorization: Optional[str] = Header(default=None)):
    """
    Return the authenticated user's identity from the Clerk session token.

    When auth is disabled this reports an anonymous/shared identity so the
    frontend can still render without forcing a login during migration.
    """
    if not AUTH_ENABLED:
        return {"authenticated": False, "user_id": None, "email": None, "auth_enabled": False}

    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    claims = verify_clerk_token(token)
    return {
        "authenticated": True,
        "auth_enabled": True,
        "user_id": claims.get("sub"),
        "email": claims.get("email"),
        "session_id": claims.get("sid"),
        "claims": {
            k: claims.get(k)
            for k in ("sub", "email", "sid", "azp", "iss", "exp", "iat")
            if k in claims
        },
    }
