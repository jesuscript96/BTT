"""HTTP endpoints for the public `robustness` module.

Every handler: auth -> rate-limit -> gating -> work via the Facade -> metering.
The three fast modules (Monte Carlo, sensitivity, Black Swan) are synchronous and
cheap (in-memory over the saved trade array). Walk-Forward is heavy/async and is
deferred to v2 in the commercial API (consistent with the MVP-synchronous design,
docs/b2d-gateway/05 §4) — it is available in-app today.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api_public.core.auth import Principal, authenticate
from app.api_public.core import metering, ratelimit
from app.api_public.core.errors import ApiError
from app.api_public.core.gating import require_access
from app.api_public.facade import Facade, get_facade
from app.api_public.modules.robustness.models import (
    BlackSwanBody,
    BlackSwanResult,
    MontecarloBody,
    MontecarloResult,
    SensitivityBody,
    SensitivityResult,
)

MODULE = "robustness"

router = APIRouter(tags=["robustness"])


def authed(request: Request) -> Principal:
    principal = authenticate(request)
    ratelimit.enforce(principal)
    return principal


@router.post("/robustness/montecarlo", response_model=MontecarloResult)
def montecarlo(
    body: MontecarloBody,
    principal: Principal = Depends(authed),
    facade: Facade = Depends(get_facade),
):
    require_access(principal, MODULE, "run")
    result = facade.robustness_montecarlo(
        body.run_id,
        init_cash=body.init_cash,
        simulations=body.simulations,
        ruin_pct=body.ruin_pct,
        n_trades_limit=body.n_trades_limit,
        period_unit=body.period_unit,
    )
    metering.record_run(principal, MODULE, "montecarlo", 0, result.get("n_trades_calculated", 0))
    return result


@router.post("/robustness/sensitivity", response_model=SensitivityResult)
def sensitivity(
    body: SensitivityBody,
    principal: Principal = Depends(authed),
    facade: Facade = Depends(get_facade),
):
    require_access(principal, MODULE, "run")
    result = facade.robustness_sensitivity(
        body.run_id,
        locate_range=body.locate_range.model_dump(),
        slippage_probability=body.slippage_probability,
        slippage_value=body.slippage_value,
        init_cash=body.init_cash,
    )
    metering.record_run(principal, MODULE, "sensitivity", 0, len(result.get("curves", {})))
    return result


@router.post("/robustness/black-swan", response_model=BlackSwanResult)
def black_swan(
    body: BlackSwanBody,
    principal: Principal = Depends(authed),
    facade: Facade = Depends(get_facade),
):
    require_access(principal, MODULE, "run")
    result = facade.robustness_black_swan(
        body.run_id,
        init_cash=body.init_cash,
        black_swan_count=body.black_swan_count,
        severity_multiplier=body.severity_multiplier,
        ruin_pct=body.ruin_pct,
    )
    metering.record_run(principal, MODULE, "black-swan", 0, len(result.get("sensitivity_matrix", [])))
    return result


@router.post("/robustness/walk-forward")
def walk_forward(principal: Principal = Depends(authed)):
    """[v2] Walk-Forward is heavy/async; not exposed in the synchronous MVP API.
    Available in the Edgecute web app today."""
    require_access(principal, MODULE, "run")
    raise ApiError(
        "not_implemented",
        "El Walk-Forward (proceso pesado/async) es v2 en la API comercial; disponible en la app web.",
        status=501,
    )
