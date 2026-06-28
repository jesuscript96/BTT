"""HTTP endpoints for the `portfolio` module.

Every handler: auth -> rate-limit -> gating hook -> work (via Facade) -> meter.
SYNCHRONOUS pure-analytics over saved backtests; never touches the engine.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api_public.core.auth import Principal, authenticate
from app.api_public.core import metering, ratelimit
from app.api_public.core.gating import require_access
from app.api_public.facade import Facade, get_facade
from app.api_public.modules.portfolio.models import (
    AllocationRequest, AllocationResponse,
    CombineRequest, CombineResponse,
    CorrelationRequest, CorrelationResponse,
    MontecarloRequest, MontecarloResponse,
)

MODULE = "portfolio"

router = APIRouter(tags=["portfolio"])


def authed(request: Request) -> Principal:
    principal = authenticate(request)
    ratelimit.enforce(principal)
    return principal


@router.post("/portfolio/combine", response_model=CombineResponse)
def combine(
    payload: CombineRequest,
    principal: Principal = Depends(authed),
    facade: Facade = Depends(get_facade),
):
    require_access(principal, MODULE, "combine")
    result = facade.portfolio_combine(principal.owner_id, payload.model_dump())
    metering.record_run(principal, MODULE, "combine", 0, 0)
    return result


@router.post("/portfolio/montecarlo", response_model=MontecarloResponse)
def montecarlo(
    payload: MontecarloRequest,
    principal: Principal = Depends(authed),
    facade: Facade = Depends(get_facade),
):
    require_access(principal, MODULE, "montecarlo")
    result = facade.portfolio_montecarlo(principal.owner_id, payload.model_dump())
    metering.record_run(principal, MODULE, "montecarlo", 0, 0)
    return result


@router.post("/portfolio/correlation", response_model=CorrelationResponse)
def correlation(
    payload: CorrelationRequest,
    principal: Principal = Depends(authed),
    facade: Facade = Depends(get_facade),
):
    require_access(principal, MODULE, "correlation")
    result = facade.portfolio_correlation(principal.owner_id, payload.model_dump())
    metering.record_run(principal, MODULE, "correlation", 0, 0)
    return result


@router.post("/portfolio/allocation", response_model=AllocationResponse)
def allocation(
    payload: AllocationRequest,
    principal: Principal = Depends(authed),
    facade: Facade = Depends(get_facade),
):
    require_access(principal, MODULE, "allocation")
    result = facade.portfolio_allocation(principal.owner_id, payload.model_dump())
    metering.record_run(principal, MODULE, "allocation", 0, 0)
    return result
