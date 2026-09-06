from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional, List
from pydantic import BaseModel
from app.database import get_db_connection
from app.auth import get_current_user_id, scope_clause
# Lazy imports for memory optimization
# from app.ingestion import ingest_history
# from app.processor import get_dashboard_stats, get_aggregate_time_series
# import pandas as pd

router = APIRouter()

class FilterRule(BaseModel):
    id: str
    category: str
    metric: str
    operator: str
    valueType: str  # "static" or "variable"
    value: str

class FilterRequest(BaseModel):
    ticker: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    min_gap_pct: Optional[float] = None
    max_gap_pct: Optional[float] = None
    min_rth_volume: Optional[float] = None
    min_m15_ret_pct: Optional[float] = None
    max_m15_ret_pct: Optional[float] = None
    min_rth_run_pct: Optional[float] = None
    max_rth_run_pct: Optional[float] = None
    min_high_spike_pct: Optional[float] = None
    max_high_spike_pct: Optional[float] = None
    min_low_spike_pct: Optional[float] = None
    max_low_spike_pct: Optional[float] = None
    hod_after: Optional[str] = None
    lod_before: Optional[str] = None
    rules: Optional[List[FilterRule]] = []

# Etiqueta de la pagina -> columna de `daily_metrics`.
#
# LAS ETIQUETAS TIENEN QUE SER IDENTICAS A LAS DE `metricToParamMap` EN
# frontend/src/app/page.tsx, LETRA POR LETRA. Se buscan con `.get()`, asi que
# una que no case NO da error: la regla se descarta y la busqueda sale SIN
# FILTRAR. Auditado el 5-sep-2026 y medido contra el backend en marcha: de 31
# filtros de la pagina, 14 se caian asi y 5 reventaban por apuntar a columnas
# inexistentes. Un filtro imposible («precio > 999.999») devolvia la lista
# entera. Ejemplo real de como duele: la pagina decia "RTH Fade to Close %" y
# aqui ponia "RTH Fade To Close %" — por esa T mayuscula, el filtro no existia.
#
# ANTES DE ANYADIR UNA ENTRADA, comprobar que la columna existe de verdad:
#   DESCRIBE SELECT * FROM daily_metrics;
# Y `test_filtros_metric_map.py` lo comprueba solo en cada corrida.
METRIC_MAP = {
    "Open Price": "rth_open",
    "Close Price": "rth_close",
    "High Price": "rth_high",
    "Low Price": "rth_low",
    "EOD Volume": "rth_volume",
    "Premarket Volume": "pm_volume",
    "Open Gap %": "gap_at_open_pct",
    "RTH Run %": "rth_run_pct",
    "M15 Return %": "m15_return_pct",
    "M30 Return %": "m30_return_pct",
    "M60 Return %": "m60_return_pct",
    "Previous Close": "prev_close",
    "PMH Gap %": "pmh_gap_pct",
    "RTH Range %": "rth_range_pct",
    "Day Return %": "day_return_pct",
    # RECUPERADOS el 5-sep-2026: la pagina los ofrecia, el dato existe, y solo
    # faltaba la entrada aqui (o casaba mal). Se ignoraban en silencio.
    "Previous Day Close Price": "prev_close",
    "Pre-Market High Price": "pm_high",
    "High Spike Price": "rth_high",          # el maximo de la sesion regular
    "Low Spike Price": "rth_low",            # el minimo de la sesion regular
    "RTH Fade to Close %": "rth_fade_pct",   # ojo: la «to» va en minuscula
    "PMH Fade to Open %": "pmh_fade_pct",
    "M180 Return %": "m180_return_pct",      # existia el dato, faltaba la entrada
    "HOD Time": "hod_time",
    "LOD Time": "lod_time",
    "PM High Time": "pm_high_time",
    #
    # RETIRADAS, y por que. Ninguna de estas columnas existe en el lago (38
    # columnas, comprobadas una a una):
    #
    #   "High Spike %" / "Low Spike %"   -> la pagina ya las mandaba apuntando a
    #       rth_run_pct y rth_range_pct, que YA estan aqui arriba con su nombre
    #       correcto. Eran duplicados, y ademas enganyaban: como dice Jaume,
    #       rth_range_pct es el RANGO de la sesion, no «el menor de los spikes».
    #   "M15/M30/M60 High Spike %" y sus Low  -> nunca se calcularon.
    #   "Return M15/M30/M60 to Close %"  -> hoy son m15/m30/m60_return_pct, que
    #       ya estan arriba como "M15/M30/M60 Return %".
    #   "M1..M180 Price"                 -> el precio a los X minutos no se
    #       guarda; lo que hay son los retornos (mX_return_pct).
    #   "Return at Close %"              -> hoy es "Day Return %".
}

@router.post("/filter")
def filter_daily_metrics(filters: FilterRequest):
    """
    Filter daily metrics records with support for dynamic rules.
    """
    # Lazy imports (Pandas ~50MB RAM)
    import pandas as pd
    from app.services.processor_service import get_dashboard_stats, get_aggregate_time_series
    
    con = None
    try:
        con = get_db_connection(read_only=True)
        # Derive date from timestamp since daily_metrics has no date column
        query = "SELECT *, CAST(timestamp AS VARCHAR)[:10] as date FROM daily_metrics WHERE 1=1"
        params = []
        
        # 1. Handle Basic Filters (legacy support)
        if filters.ticker:
            query += " AND ticker = ?"
            params.append(filters.ticker.upper())
        
        if filters.min_gap_pct is not None:
            query += " AND gap_at_open_pct >= ?"
            params.append(filters.min_gap_pct)
            
        if filters.max_gap_pct is not None:
            query += " AND gap_at_open_pct <= ?"
            params.append(filters.max_gap_pct)

        if filters.min_rth_volume is not None:
            query += " AND rth_volume >= ?"
            params.append(filters.min_rth_volume)
            
        if filters.date_from:
            query += " AND CAST(timestamp AS VARCHAR)[:10] >= ?"
            params.append(filters.date_from)
            
        if filters.date_to:
            query += " AND CAST(timestamp AS VARCHAR)[:10] <= ?"
            params.append(filters.date_to)

        # 1.1 Handle Extended Filters
        if filters.min_m15_ret_pct is not None:
            query += " AND m15_return_pct >= ?"
            params.append(filters.min_m15_ret_pct)
        if filters.max_m15_ret_pct is not None:
            query += " AND m15_return_pct <= ?"
            params.append(filters.max_m15_ret_pct)
        if filters.min_rth_run_pct is not None:
            query += " AND rth_run_pct >= ?"
            params.append(filters.min_rth_run_pct)
        if filters.max_rth_run_pct is not None:
            query += " AND rth_run_pct <= ?"
            params.append(filters.max_rth_run_pct)
        if filters.min_high_spike_pct is not None:
            query += " AND high_spike_pct >= ?"
            params.append(filters.min_high_spike_pct)
        if filters.max_high_spike_pct is not None:
            query += " AND high_spike_pct <= ?"
            params.append(filters.max_high_spike_pct)
        if filters.min_low_spike_pct is not None:
            query += " AND low_spike_pct >= ?"
            params.append(filters.min_low_spike_pct)
        if filters.max_low_spike_pct is not None:
            query += " AND low_spike_pct <= ?"
            params.append(filters.max_low_spike_pct)
        if filters.hod_after:
            query += " AND hod_time >= ?"
            params.append(filters.hod_after)
        if filters.lod_before:
            query += " AND lod_time <= ?"
            params.append(filters.lod_before)

        # 2. Handle Dynamic Rules
        if filters.rules:
            # UN FILTRO QUE NO SE ENTIENDE ES UN ERROR, NO UN «SIGUIENTE».
            #
            # Esto era `continue` en los dos casos, y ahi estaba el fallo mas
            # caro de esta pagina: una etiqueta que no casaba con METRIC_MAP se
            # descartaba y la busqueda se ejecutaba SIN ESE FILTRO, devolviendo
            # una lista que parecia filtrada y no lo estaba. Medido el
            # 5-sep-2026: «Pre-Market High Price > 999999» devolvia las mismas 5
            # filas que no filtrar nada. Catorce de los treinta y un filtros de
            # la pagina se comportaban asi.
            #
            # Devolver 400 con el nombre del filtro es feo la primera vez y
            # barato siempre: se ve al momento y se arregla anyadiendo la
            # entrada al mapa. Un resultado sin filtrar no se ve NUNCA.
            for rule in filters.rules:
                col = METRIC_MAP.get(rule.metric)
                if not col:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Filtro desconocido: «{rule.metric}». No existe en "
                               f"METRIC_MAP, asi que no se puede aplicar. Si el dato "
                               f"existe en daily_metrics, anyadelo al mapa; si no, "
                               f"quita el filtro de la pagina.",
                    )

                op = rule.operator
                if op not in ["=", "!=", ">", ">=", "<", "<="]:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Operador no valido en el filtro «{rule.metric}»: «{op}».",
                    )

                if rule.valueType == "static":
                    try:
                        val = float(rule.value)
                        query += f" AND {col} {op} ?"
                        params.append(val)
                    except ValueError:
                        if rule.value:
                            query += f" AND {col} {op} ?"
                            params.append(rule.value)
                elif rule.valueType == "variable":
                    target_col = METRIC_MAP.get(rule.value)
                    if target_col:
                        query += f" AND {col} {op} {target_col}"
            
        query += " ORDER BY CAST(timestamp AS VARCHAR)[:10] DESC"
        
        df = con.execute(query, params).fetch_df()

        # Fuera warrants, rights, units, ETFs y preferentes: el buscador enseña
        # el mismo universo que opera el backtest (Jaume, 6-sep-2026 — «no voy a
        # operar nunca un warrant»). Va AQUI, antes de las stats y de la serie
        # agregada, para que los tres numeros cuadren entre si. La consulta no
        # lleva LIMIT, asi que filtrar sobre el resultado es exacto.
        from app.services.data_service import _filtrar_tipo_instrumento
        df = _filtrar_tipo_instrumento(df)

        # Convert date to string for JSON output
        if not df.empty:
            df['date'] = df['date'].astype(str)
            
        records = df.to_dict(orient="records")
        stats = get_dashboard_stats(df)
        
        # Aggregate series for the chart (Limit to top results for performance)
        ticker_date_pairs = df[['ticker', 'date']].head(50).to_dict(orient="records")
        aggregate_series = get_aggregate_time_series(ticker_date_pairs)
        
        return {
            "records": records,
            "stats": stats,
            "aggregate_series": aggregate_series
        }
    except HTTPException:
        # Los 400 de arriba ya dicen QUE filtro falla y por que. Sin esta rama,
        # el `except Exception` de abajo los reetiquetaria como 500 y el mensaje
        # util se perderia entre los errores de servidor.
        raise
    except Exception as e:
        print(f"Filter API Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if con:
            con.close()

@router.get("/tickers")
def get_tickers():
    import pandas as pd
    con = None
    try:
        con = get_db_connection(read_only=True)
        tickers = con.execute("SELECT ticker, name FROM tickers ORDER BY ticker").fetch_df()
        if tickers.empty:
            raise ValueError("Tickers table is empty")
        return tickers.to_dict(orient="records")
    except Exception as e:
        print(f"Tickers API Error: {e}. Falling back to cache or default list.")
        try:
            from app.services.cache_service import get_tickers_df
            df = get_tickers_df()
            if df is not None and not df.empty:
                df_with_name = df.copy()
                if 'name' not in df_with_name.columns:
                    df_with_name['name'] = df_with_name['ticker']
                return df_with_name[['ticker', 'name']].to_dict(orient="records")
        except Exception as cache_err:
            print(f"Tickers Cache Error: {cache_err}")
        
        return [
            {'ticker': 'AAPL', 'name': 'Apple Inc.'},
            {'ticker': 'TSLA', 'name': 'Tesla Inc.'},
            {'ticker': 'NVDA', 'name': 'NVIDIA Corp.'},
            {'ticker': 'MSFT', 'name': 'Microsoft Corp.'}
        ]
    finally:
        if con:
            con.close()
import json
import numpy as np

@router.get("/historical")
def get_historical_ohlc(
    ticker: str, 
    date_from: str, 
    date_to: str,
    indicators: Optional[str] = Query(None, description="JSON array of indicator configs")
):
    """
    Fetch intraday OHLC data for a specific ticker and range.
    Uses intraday_1m table (historical_data no longer exists).
    Adds optional requested indicators to the response.
    """
    import pandas as pd
    con = None
    try:
        fetch_date_from = date_from
        if indicators:
            try:
                # Add a 30-day buffer to calculate moving averages properly
                fetch_date_from = (pd.to_datetime(date_from) - pd.Timedelta(days=30)).strftime('%Y-%m-%d')
            except:
                pass

        con = get_db_connection(read_only=True)
        query = """
            SELECT 
                timestamp, open, high, low, close, volume
            FROM intraday_1m 
            WHERE ticker = ? AND timestamp >= CAST(? AS TIMESTAMP) AND timestamp <= CAST(? AS TIMESTAMP)
            ORDER BY timestamp ASC
        """
        df = con.execute(query, [ticker.upper(), fetch_date_from, date_to]).fetch_df()
        
        if df.empty:
            return []
            
        ind_list = []
        if indicators:
            try:
                ind_list = json.loads(indicators)
            except Exception as e:
                print(f"Error parsing indicators: {e}")
                
        cols_to_return = ['time', 'open', 'high', 'low', 'close', 'volume']
        
        if ind_list:
            df['date'] = df['timestamp'].dt.date
            for ind in ind_list:
                name = ind.get('name')
                period = ind.get('period', 14)
                col_name = f"{name}_{period}" if period and name not in ["VWAP", "MACD"] else name
                
                if name == "SMA":
                    df[col_name] = df['close'].rolling(window=period).mean()
                    cols_to_return.append(col_name)
                elif name == "EMA":
                    df[col_name] = df['close'].ewm(span=period, adjust=False).mean()
                    cols_to_return.append(col_name)
                elif name == "VWAP":
                    def calc_vwap(g):
                        v = g['volume']
                        tp = (g['high'] + g['low'] + g['close']) / 3
                        return (tp * v).cumsum() / (v.cumsum() + 1e-10)
                    df[col_name] = df.groupby('date', group_keys=False).apply(calc_vwap)
                    if len(df[col_name]) == len(df): df[col_name].index = df.index
                    cols_to_return.append(col_name)
                elif name == "RSI":
                    def calc_rsi(s, p):
                        delta = s.diff()
                        up = delta.clip(lower=0)
                        down = -delta.clip(upper=0)
                        ema_up = up.ewm(com=p-1, adjust=False).mean()
                        ema_down = down.ewm(com=p-1, adjust=False).mean()
                        rs = ema_up / (ema_down + 1e-10)
                        return 100 - (100 / (1 + rs))
                    df[col_name] = calc_rsi(df['close'], period)
                    cols_to_return.append(col_name)
                elif name == "MACD":
                    ema12 = df['close'].ewm(span=12, adjust=False).mean()
                    ema26 = df['close'].ewm(span=26, adjust=False).mean()
                    df[col_name] = ema12 - ema26
                    cols_to_return.append(col_name)
                elif name == "ATR":
                    def calc_atr(group, p):
                        high = group['high']
                        low = group['low']
                        prev_close = group['close'].shift(1)
                        tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
                        return tr.rolling(window=p).mean()
                    df[col_name] = calc_atr(df, period)
                    cols_to_return.append(col_name)

        # Filter back to exactly what was requested for date_from to save payload size
        df = df[df['timestamp'] >= pd.to_datetime(date_from).tz_localize(None)]

        if df.empty:
            return []

        # DuckDB datetime64 is [us] (microseconds). To get Unix seconds, divide by 10**6
        df['time'] = df['timestamp'].astype('int64') // 10**6
        df = df.replace({np.nan: None})
        
        return df[cols_to_return].to_dict(orient="records")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Historical OHLC API Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if con:
            con.close()
import numpy as np

@router.post("/api/cache/refresh")
async def refresh_cache():
    from app.db.gcs_cache import sync_hot_tables
    try:
        sync_hot_tables(force=True)
        return {"status": "ok", "message": "Cache refreshed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




@router.get("/datasets")
def list_datasets(user_id: Optional[str] = Depends(get_current_user_id)):
    results = []

    # Primero: leer de users.duckdb local
    try:
        from app.database import get_user_db_connection, get_user_db_lock
        import json as _json
        scope_sql, scope_params = scope_clause(user_id)
        with get_user_db_lock():
            con = get_user_db_connection()
            try:
                rows = con.execute(
                    f"""
                    SELECT 
                        q.id, 
                        q.name, 
                        q.filters, 
                        q.created_at, 
                        q.updated_at,
                        COALESCE(dp.pair_count, 0) as pair_count,
                        dp.min_date,
                        dp.max_date
                    FROM saved_queries q
                    LEFT JOIN (
                        SELECT 
                            dataset_id, 
                            COUNT(*) as pair_count, 
                            CAST(MIN(date) AS VARCHAR) as min_date, 
                            CAST(MAX(date) AS VARCHAR) as max_date
                        FROM dataset_pairs
                        GROUP BY dataset_id
                    ) dp ON q.id = dp.dataset_id
                    WHERE 1=1{scope_sql}
                    ORDER BY q.created_at DESC
                    """,
                    scope_params,
                ).fetchall()
                for row in rows:
                    filters = _json.loads(row[2]) if isinstance(row[2], str) else (row[2] or {})
                    pair_count = row[5]
                    min_date = row[6] if row[6] else (filters.get("start_date") or filters.get("date_from"))
                    max_date = row[7] if row[7] else (filters.get("end_date") or filters.get("date_to"))

                    results.append({
                        "id": row[0],
                        "name": row[1],
                        "filters": filters,
                        "pair_count": pair_count,
                        "min_date": min_date,
                        "max_date": max_date,
                        "created_at": str(row[3]) if row[3] else None,
                        "updated_at": str(row[4]) if row[4] else None,
                    })
            finally:
                con.close()
    except Exception as e:
        print(f"[WARN] Could not read datasets from local DB: {e}")
    
    # Sin respaldo a GCS: el parquet legacy no tiene columna de dueño y se colaba entero
    # en el desplegable de datasets del Backtester, para todos los usuarios. Ver
    # strategies.py:list_strategies.
    return results


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str, user_id: Optional[str] = Depends(get_current_user_id)):
    # Primero: buscar en local DB
    try:
        from app.database import get_user_db_connection
        import json as _json
        scope_sql, scope_params = scope_clause(user_id)
        con = get_user_db_connection()
        try:
            row = con.execute(
                f"SELECT id, name, filters, created_at, updated_at FROM saved_queries WHERE id = ?{scope_sql}",
                [dataset_id, *scope_params],
            ).fetchone()
            if row:
                filters = _json.loads(row[2]) if isinstance(row[2], str) else (row[2] or {})
                pair_count = 0
                try:
                    pc_row = con.execute(
                        "SELECT COUNT(*) FROM dataset_pairs WHERE dataset_id = ?",
                        (row[0],)
                    ).fetchone()
                    pair_count = pc_row[0] if pc_row else 0
                except Exception as pc_err:
                    print(f"[WARN] Could not query pair count for dataset {row[0]}: {pc_err}")
                    pair_count = filters.get("pair_count", 0)

                return {
                    "id": row[0],
                    "name": row[1],
                    "filters": filters,
                    "pair_count": pair_count,
                    "min_date": filters.get("start_date") or filters.get("date_from"),
                    "max_date": filters.get("end_date") or filters.get("date_to"),
                    "created_at": str(row[3]) if row[3] else None,
                    "updated_at": str(row[4]) if row[4] else None,
                }
        finally:
            con.close()
    except Exception as e:
        print(f"[WARN] Could not read dataset from local DB: {e}")
    
    # Sin respaldo a GCS: devolvía el dataset de cualquiera con solo conocer su id.
    raise HTTPException(status_code=404, detail="Dataset not found")


@router.get("/strategies")
def list_strategies_backtester(user_id: Optional[str] = Depends(get_current_user_id)):
    results = []

    # Primero: leer de users.duckdb local
    try:
        from app.database import get_user_db_connection, get_user_db_lock
        import json as _json
        scope_sql, scope_params = scope_clause(user_id)
        with get_user_db_lock():
            con = get_user_db_connection()
            try:
                rows = con.execute(
                    f"SELECT id, name, description, definition FROM strategies "
                    f"WHERE 1=1{scope_sql} ORDER BY created_at DESC",
                    scope_params,
                ).fetchall()
                for row in rows:
                    results.append({
                        "id": row[0],
                        "name": row[1],
                        "description": row[2],
                        "definition": _json.loads(row[3]) if isinstance(row[3], str) else row[3],
                    })
            finally:
                con.close()
    except Exception as e:
        print(f"[WARN] Could not read strategies from local DB: {e}")
    
    # Sin respaldo a GCS: metía las 33 estrategias legacy en el desplegable del Backtester
    # de todos los usuarios. Ver strategies.py:list_strategies.
    return results


@router.get("/strategies/{strategy_id}")
def get_strategy_backtester(strategy_id: str, user_id: Optional[str] = Depends(get_current_user_id)):
    # Primero: buscar en local DB
    try:
        from app.database import get_user_db_connection
        import json as _json
        scope_sql, scope_params = scope_clause(user_id)
        con = get_user_db_connection()
        try:
            row = con.execute(
                f"SELECT id, name, description, definition FROM strategies WHERE id = ?{scope_sql}",
                [strategy_id, *scope_params],
            ).fetchone()
            if row:
                return {
                    "id": row[0],
                    "name": row[1],
                    "description": row[2],
                    "definition": _json.loads(row[3]) if isinstance(row[3], str) else row[3],
                }
        finally:
            con.close()
    except Exception as e:
        print(f"[WARN] Could not read strategy from local DB: {e}")
    
    # Sin respaldo a GCS: devolvía la estrategia de cualquiera con solo conocer su id.
    raise HTTPException(status_code=404, detail="Strategy not found")
