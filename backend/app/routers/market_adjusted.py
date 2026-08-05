"""Router para Market Analysis sobre data ajustada por splits.

Espejo de /api/market pero leyendo de daily_metrics_adj (split-adjusted).
Permite comparar lado a lado: pestaña Market Analysis (raw) vs Adjusted.
"""
from fastapi import APIRouter, Depends, HTTPException, Request

from app.entitlements.middleware import require
from app.services.market_analysis_service import (
    get_market_analysis,
    get_avg_change_from_open,
    get_gaps_by_sector,
)

router = APIRouter(
    prefix="/api/market-adjusted",
    tags=["market-adjusted"],
)


@router.get("/screener")
def market_analysis_adjusted(request: Request, _=Depends(require("market.analysis.access"))):
    try:
        filters = dict(request.query_params)
        return get_market_analysis(filters, adjusted=True)
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/aggregate/intraday")
def avg_change_adjusted(request: Request, _=Depends(require("market.analysis.access"))):
    try:
        filters = dict(request.query_params)
        return get_avg_change_from_open(filters)
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/gaps-by-sector")
def gaps_by_sector_adjusted(request: Request, _=Depends(require("market.analysis.access"))):
    try:
        filters = dict(request.query_params)
        return get_gaps_by_sector(filters, adjusted=True)
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
