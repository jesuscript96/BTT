from fastapi import APIRouter, Depends, HTTPException, Request
from datetime import date
from typing import Optional
from app.database import get_db_connection
from app.entitlements.middleware import require
import math
import json
import os

# Suelo del rango que la app ANUNCIA como disponible.
# daily_metrics conserva filas de 2017, pero 2017 es un muestreo (~208 tickers/día
# frente a ~11.000) y de 2018-2021 no hay intraday. Sin este suelo, MIN(timestamp)
# devuelve 2017 y el usuario podía pedir un rango para el que no hay datos y recibir
# cero resultados sin explicación. Alcance acordado (Jesús, 2026-07-13): 2022 → hoy.
# Configurable por si se amplía el histórico en el futuro.
MIN_AVAILABLE_DATE = os.getenv("MIN_AVAILABLE_DATE", "2022-01-01")

def safe_float(v):
    if v is None: return 0.0
    try:
        fv = float(v)
        if math.isnan(fv) or math.isinf(fv): return 0.0
        return fv
    except:
        return 0.0

router = APIRouter(
    prefix="/api/market",
    tags=["market"]
)

from app.services.query_service import build_screener_query, get_stats_sql_logic, map_stats_row
from app.services.cache_service import get_hot_daily_df
from app.services.market_analysis_service import get_market_analysis, get_avg_change_from_open, get_gaps_by_sector
import pandas as pd

@router.get("/screener")
def market_analysis(request: Request, _=Depends(require("market.analysis.access"))):
    """
    Market Analysis — payload analítico del MVP sobre los gappers del periodo filtrado:
    KPIs (MA-01), distribuciones temporales (MA-02), MAE/MFE (MA-05) y Recent Gaps (MA-06).

    Contrato: docs/market-analysis/PRD.md §4.1. Toda la lógica vive en
    services/market_analysis_service.get_market_analysis (router fino, CODING_RULES §6.1).
    Los filtros llegan como query params (gap/vol/precio/fecha/period/fade_threshold/ticker…).
    """
    try:
        filters = dict(request.query_params)
        return get_market_analysis(filters)
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/ticker/{ticker}/intraday")
def get_intraday_data(ticker: str, trade_date: Optional[date] = None):
    con = None
    try:
        con = get_db_connection(read_only=True)
        if not trade_date:
            latest = con.execute("SELECT MAX(date) FROM intraday_1m WHERE ticker = ?", [ticker]).fetchone()
            if latest and latest[0]: trade_date = latest[0]
            else: return []

        query = """
            SELECT timestamp, open, high, low, close, volume
            FROM intraday_1m WHERE ticker = ? AND date = ?
            GROUP BY 1, 2, 3, 4, 5, 6 ORDER BY timestamp ASC
        """
        cur = con.execute(query, [ticker, trade_date])
        cols, rows = [d[0] for d in cur.description], cur.fetchall()
        recs = []
        for r in rows:
            rd = dict(zip(cols, r))
            recs.append({
                "timestamp": str(rd['timestamp']),
                "open": safe_float(rd['open']), "high": safe_float(rd['high']), "low": safe_float(rd['low']),
                "close": safe_float(rd['close']), "volume": safe_float(rd['volume'])
            })
        return recs
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))
    finally:
        if con: con.close()

@router.get("/ticker/{ticker}/metrics_history")
def get_metrics_history(ticker: str, limit: int = 500):
    con = None
    try:
        con = get_db_connection(read_only=True)
        # Using simple query fallback
        query = "SELECT * FROM daily_metrics WHERE ticker = ? ORDER BY timestamp DESC LIMIT ?"
        cur = con.execute(query, [ticker, limit])
        cols, rows = [d[0] for d in cur.description], cur.fetchall()
        
        data = []
        for r in rows:
            rd = dict(zip(cols, r))
            data.append({
                "date": str(rd.get('date', rd.get('timestamp', ''))),
                "rth_range_pct": safe_float(rd.get('rth_range_pct', 0)),
                "return_close_vs_open_pct": safe_float(rd.get('day_return_pct', 0)),
                "high_spike_pct": safe_float(rd.get('high_spike_pct', 0)),
                "gap_extension_pct": 0.0, # Not in schema yet?
                "pmh_gap_pct": safe_float(rd.get('pmh_gap_pct', 0)),
                "pm_fade_at_open_pct": safe_float(rd.get('pmh_fade_pct', 0))
            })
        return data[::-1]
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if con: con.close()

@router.get("/latest-date")
def get_latest_market_date():
    con = None
    try:
        con = get_db_connection(read_only=True)
        latest = con.execute("SELECT CAST(MAX(timestamp) AS VARCHAR)[:10] FROM daily_metrics").fetchone()
        return {"date": str(latest[0])} if latest and latest[0] else {"date": None}
    finally:
        if con: con.close()

# SIN guarda a propósito: vive bajo /api/market pero NO es de Market Analysis — lo
# consumen los builders de dataset/estrategia del Backtester, que el tier Beta sí tiene.
# Cerrar el router entero en vez de endpoint por endpoint rompería el Backtester.
@router.get("/available-date-range")
def get_available_date_range():
    con = None
    try:
        con = get_db_connection(read_only=True)
        row = con.execute(
            "SELECT CAST(MIN(timestamp) AS VARCHAR)[:10], CAST(MAX(timestamp) AS VARCHAR)[:10] "
            "FROM daily_metrics WHERE timestamp >= CAST(? AS DATE)",
            [MIN_AVAILABLE_DATE],
        ).fetchone()
        if row and row[0] and row[1]:
            return {"min_date": str(row[0]), "max_date": str(row[1])}
        return {"min_date": MIN_AVAILABLE_DATE, "max_date": date.today().isoformat()}
    except Exception as e:
        return {"min_date": MIN_AVAILABLE_DATE, "max_date": date.today().isoformat()}
    finally:
        if con: con.close()

@router.get("/aggregate/intraday")
def avg_change_from_open(request: Request, _=Depends(require("market.analysis.access"))):
    """
    Market Analysis MA-04 — Avg Change from Open de los últimos 12 meses naturales.
    Contrato: docs/market-analysis/PRD.md §4.2. Lógica en
    services/market_analysis_service.get_avg_change_from_open (router fino).
    """
    try:
        filters = dict(request.query_params)
        return get_avg_change_from_open(filters)
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/gaps-by-sector")
def gaps_by_sector(request: Request, _=Depends(require("market.analysis.access"))):
    """
    Market Analysis — Gaps Up by Sector (treemap). Gappers con gap>=min_gap de la
    ventana (5d/30d/90d) agregados por sector de la empresa.
    Contrato: docs/market-analysis/PRD_GAPS_BY_SECTOR.md §4.1. Lógica en
    services/market_analysis_service.get_gaps_by_sector (router fino).
    """
    try:
        filters = dict(request.query_params)
        return get_gaps_by_sector(filters)
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
