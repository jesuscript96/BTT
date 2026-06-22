"""Per-module gating HOOK (mechanism, not policy).

This is the `if can_access(...)` from docs/b2d-gateway/05 §5. The MECHANISM lives
here; the POLICY (which module/action is free vs paid, for whom, when, at what
price) is a deferred product decision (docs/b2d-gateway/07 §A) and is intentionally
NOT encoded here.

Default behaviour: ALLOW everything. A future policy can register a resolver via
`set_policy(...)` without touching any module — the call site stays identical.
"""
from __future__ import annotations

from typing import Callable, Optional

from app.api_public.core.auth import Principal
from app.api_public.core.errors import ApiError

# A policy is a callable (principal, module, action) -> bool. None = allow all.
_policy: Optional[Callable[[Principal, str, str], bool]] = None


def set_policy(policy: Optional[Callable[[Principal, str, str], bool]]) -> None:
    """Install (or clear) the gating policy. Decided later; not part of the MVP."""
    global _policy
    _policy = policy


def can_access(principal: Principal, module: str, action: str) -> bool:
    if _policy is None:
        return True
    try:
        return bool(_policy(principal, module, action))
    except Exception:
        # A broken policy must fail closed, not crash the request.
        return False


def require_access(principal: Principal, module: str, action: str) -> None:
    """Raise if the (deferred) policy denies access. Default allows."""
    if not can_access(principal, module, action):
        raise ApiError(
            "forbidden",
            f"Tu plan no incluye '{action}' en el módulo '{module}'.",
            details={"module": module, "action": action},
        )
