import json
import logging
import os
import random
import time

import pandas as pd

from datetime import datetime, timezone

from fastapi import HTTPException

from app.services.advanced_backtest import AdvancedModelError
from pydantic import BaseModel

from app.services.data_service import (
    get_strategy,
    fetch_qualifying_data,
    get_intraday_stream,
    _resolve_filters,
)
from app.services.backtest_service import run_backtest

logger = logging.getLogger("backtester.orchestrator")

# ── Guardián de completitud de datos ────────────────────────────────────────
# El stream intradía (gcs_cache.iter_intraday_groups_streamed) SOLO emite los
# ticker-días cuyo M1 se pudo leer en ese instante; los que fallan (query del
# lago que peta por memoria/concurrencia, caché fría, prewarm a medias) se
# descartan SIN error y SIN aviso. Efecto medido: el MISMO backtest da resultados
# distintos entre runs (p.ej. 11R → 46R) según lo caliente que esté la caché →
# el motor no es reproducible. Reconciliamos ejecutados vs candidatos y lo
# reportamos siempre en el resultado; con el flag en 'true' se rechaza el
# resultado parcial en vez de devolver un número mentiroso.
# Default OFF (solo reporta) → no cambia el comportamiento de prod ni de nadie.
_STRICT_COMPLETENESS = os.getenv(
    "BACKTEST_STRICT_COMPLETENESS", "false"
).strip().lower() in ("1", "true", "yes", "on")


class BacktestRequest(BaseModel):
    dataset_id: str
    strategy_id: str | None = None
    strategy_definition: dict | None = None
    init_cash: float = 10000.0
    risk_r: float = 100.0
    risk_type: str = "FIXED"
    fixed_ratio_delta: float = 500.0
    size_by_sl: bool = False
    fees: float = 0.0
    fee_type: str = "PERCENT"
    monthly_expenses: float = 0.0
    slippage: float = 0.0
    start_date: str | None = None
    end_date: str | None = None
    market_sessions: list[str] | None = None
    custom_start_time: str | None = None
    custom_end_time: str | None = None
    locates_cost: float = 0.0
    # FLAT = coste en $ por cada 100 acciones reutilizables en corto (lo que
    # cuesta un locate). Antes "PERCENT" (% del riesgo) — semántica corregida
    # por decisión de producto (Jaume 2026-07-07). backtest_service ya default FLAT.
    locate_type: str = "FLAT"
    # Tope de locates: máximo de paquetes de 100 acciones que se está dispuesto
    # a alquilar por ticker-día. 0 = sin tope. Limita el tamaño en CORTO a
    # max_locates * 100 acciones (Jaume 2026-08-26).
    max_locates: int = 0
    look_ahead_prevention: bool = True


def generate_mock_candles(ticker: str, date: str) -> dict:
    """Generate synthetic 1-min candles (390 bars, 9:30→16:00 ET) for mock dataset testing."""
    random.seed(hash(f"{ticker}{date}") & 0xFFFFFF)
    try:
        base_dt = datetime.strptime(date, "%Y-%m-%d").replace(
            hour=9, minute=30, tzinfo=timezone.utc
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date format")

    price = random.uniform(50, 300)
    candles = []
    for i in range(390):
        ts = int(base_dt.timestamp()) + i * 60
        change = random.gauss(0, 0.003) * price
        open_ = round(price, 2)
        close = round(max(price + change, 0.5), 2)
        high = round(max(open_, close) * (1 + abs(random.gauss(0, 0.001))), 2)
        low = round(min(open_, close) * (1 - abs(random.gauss(0, 0.001))), 2)
        volume = random.randint(1000, 50000)
        candles.append({
            "time": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "vwap": None,
        })
        price = close

    return {"ticker": ticker, "date": date, "candles": candles}


def sanitize_floats(obj):
    import math
    if isinstance(obj, dict):
        return {k: sanitize_floats(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_floats(x) for x in obj]
    elif isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif hasattr(obj, 'dtype') and ('float' in str(obj.dtype) or 'int' in str(obj.dtype)):
        try:
            val = float(obj)
            if math.isnan(val) or math.isinf(val):
                return None
            return val
        except Exception:
            return None
    return obj


def run_backtest_orchestrator(req: BacktestRequest, on_progress=None) -> dict:
    # on_progress: optional callback(current, total, percent) used by the async
    # job runner (F3) to mirror progress into Redis keyed by job_id. When None
    # (sync retrocompat path + public API facade) behaviour is unchanged.
    t0 = time.time()
    logger.info(f"BACKTEST START dataset={req.dataset_id} strategy={req.strategy_id or 'inline'}")

    # ── STRATEGY LOAD + VALIDATION ──
    if req.strategy_id:
        strategy = get_strategy(req.strategy_id)
        if not strategy:
            if req.strategy_definition:
                logger.info(f"Strategy {req.strategy_id} not found in database; using provided strategy_definition as fallback")
                strategy = {
                    "id": req.strategy_id,
                    "name": req.strategy_definition.get("name") or "Draft",
                    "definition": req.strategy_definition,
                }
            else:
                raise HTTPException(status_code=404, detail="Strategy not found")
    elif req.strategy_definition:
        strategy = {
            "id": "draft",
            "name": req.strategy_definition.get("name") or "Draft",
            "definition": req.strategy_definition,
        }
    else:
        raise HTTPException(
            status_code=400,
            detail="strategy_id or strategy_definition required",
        )

    strategy_rm = strategy.get("definition", {}).get("risk_management", {})
    size_by_sl = req.size_by_sl or strategy_rm.get("size_by_sl", False)

    if size_by_sl:
        rm = strategy_rm
        hs = rm.get("hard_stop", {})
        hs_value = hs.get("value", 0)
        if isinstance(hs_value, (int, float)):
            has_hard_stop = rm.get("use_hard_stop") and hs_value > 0
        else:
            has_hard_stop = rm.get("use_hard_stop") and bool(hs_value)
        has_trailing = rm.get("trailing_stop", {}).get("active", False)
        if not has_hard_stop and not has_trailing:
            raise HTTPException(
                status_code=400,
                detail="La estrategia no tiene configurado un Stop Loss. "
                       "Desactiva 'Size por Distancia al SL' o añade un Stop Loss a la estrategia.",
            )

    logger.info(f"  strategy loaded ({round(time.time()-t0, 2)}s)")

    try:
        strategy_def = strategy["definition"]
        preconditions = strategy_def.get("postgap_preconditions", [])
        apply_day = strategy_def.get("apply_day", "gap_day")

        # Modelos avanzados: se valida AQUI, antes de cargar un solo dato.
        # Una configuracion imposible (fechas solapadas, sin features) tiene que
        # fallar en un segundo, no despues de varios minutos de lago.
        from app.services.advanced_backtest import parse_config as _parse_modelo
        _sdef_modelo = strategy["definition"]
        _cfg_modelo = _parse_modelo(_sdef_modelo.get("advanced_model")
                                    if isinstance(_sdef_modelo, dict) else None)
        if _cfg_modelo is not None:
            # Y que la estrategia no se pise con el modelo: en modo «estrategia»
            # las entradas las pone el, asi que una logica de entrada, la
            # piramidacion o el swing serian dos sistemas compitiendo. Se para
            # aqui, con el motivo escrito, antes de cargar nada.
            from app.services.advanced_backtest import validate_strategy as _val_modelo
            _val_modelo(_cfg_modelo, strategy_def)
            logger.info("[MODELO] bloque activo, modo=%s", _cfg_modelo["mode"])

        # ── PHASE 1: qualifying data (from local cache — fast) ──
        t_fetch = time.time()
        qualifying = fetch_qualifying_data(
            req.dataset_id, 
            req.start_date, 
            req.end_date, 
            preconditions=preconditions, 
            apply_day=apply_day
        )

        if qualifying is None or qualifying.empty:
            logger.warning(f"  No qualifying data for dataset={req.dataset_id}")
            return {
                "aggregate_metrics": {},
                "day_results": [],
                "trades": [],
                "equity_curves": [],
                "global_equity": [],
                "global_drawdown": [],
            }

        if req.start_date:
            qualifying = qualifying[qualifying["date"].astype(str) >= req.start_date]
        if req.end_date:
            qualifying = qualifying[qualifying["date"].astype(str) <= req.end_date]

        n_qualifying = len(qualifying)
        n_tickers = qualifying["ticker"].nunique()
        t_qualifying = time.time()
        qualifying_elapsed = round(t_qualifying - t0, 2)
        logger.info(
            f"  qualifying: {n_qualifying} rows, {n_tickers} tickers "
            f"({round(time.time()-t_fetch, 2)}s)"
        )
        print(f"[TIMING] qualifying: {qualifying_elapsed}s — {n_qualifying} filas")
        from app.services.perf_timing import log_phase
        log_phase("qualifying", (t_qualifying - t_fetch) * 1000, dataset=req.dataset_id,
                  pairs=n_qualifying, tickers=n_tickers)

        # ── PHASE 2: resolve date range for streaming ──
        filters = _resolve_filters(req.dataset_id, req.start_date, req.end_date)
        date_from = filters.get("start_date") or filters.get("date_from")
        date_to = filters.get("end_date") or filters.get("date_to")

        # Populate dataset_pairs dynamically when the backtest is run for the first time
        # (so the dataset details show the real number of pairs).
        try:
            # Check if pairs already exist for this dataset using a read-only query
            need_pairs = False
            from app.database import get_user_db_connection, get_user_db_lock
            lock = get_user_db_lock()
            with lock:
                con = get_user_db_connection(read_only=True)
                try:
                    pc_row = con.execute("SELECT COUNT(*) FROM dataset_pairs WHERE dataset_id = ?", [req.dataset_id]).fetchone()
                    need_pairs = (pc_row and pc_row[0] == 0)
                finally:
                    con.close()

            if need_pairs:
                # Fetch base qualifying data (without preconditions/apply_day shifts) to get the dataset's base pairs
                # This is fetched OUTSIDE of the user DB lock to prevent deadlocking or locking database connections.
                base_qualifying = fetch_qualifying_data(
                    req.dataset_id,
                    None,
                    None,
                    preconditions=None,
                    apply_day='gap_day'
                )
                if base_qualifying is not None and not base_qualifying.empty:
                    pairs_to_insert = base_qualifying[['ticker', 'date']].drop_duplicates()
                    uploaded_db = False
                    with lock:
                        con = get_user_db_connection(read_only=False)
                        try:
                            # Double check inside the write lock to be absolutely safe
                            pc_row = con.execute("SELECT COUNT(*) FROM dataset_pairs WHERE dataset_id = ?", [req.dataset_id]).fetchone()
                            if pc_row and pc_row[0] == 0:
                                con.register("pairs_tmp", pairs_to_insert)
                                con.execute(
                                    "INSERT INTO dataset_pairs (dataset_id, ticker, date) "
                                    "SELECT ? as dataset_id, ticker, CAST(date AS DATE) FROM pairs_tmp "
                                    "ON CONFLICT DO NOTHING",
                                    [req.dataset_id],
                                )
                                print(f"[BACKTEST] Saved {len(pairs_to_insert)} base dataset pairs dynamically")
                                uploaded_db = True
                        finally:
                            con.close()

                    if uploaded_db:
                        # Update GCS DB so the sync persists this info
                        try:
                            from app.gcs_sync import upload_user_db
                            upload_user_db()
                        except Exception as upload_err:
                            print(f"[WARN] GCS upload after dynamic pairs save failed: {upload_err}")
        except Exception as pc_err:
            print(f"[WARN] Could not dynamically save dataset pairs: {pc_err}")

        # ── PHASE 3: create streaming iterator ──
        print(f"[DEBUG] calling get_intraday_stream with qualifying={len(qualifying)} rows, date_from={date_from}, date_to={date_to}")
        intraday_stream = get_intraday_stream(qualifying, date_from, date_to)
        print(f"[DEBUG] intraday_stream created: type={type(intraday_stream)}")

        # Registro de completitud: envolvemos el iterador para anotar qué
        # (ticker, date) llegan de verdad a la simulación. Lo que no se emita aquí
        # es un candidato descartado en silencio aguas abajo (ver nota del flag
        # _STRICT_COMPLETENESS arriba). No altera el orden ni los datos: solo mira.
        _executed_keys: set[tuple[str, str]] = set()

        def _tracked_stream(inner):
            for (d, tk), day_df in inner:
                _executed_keys.add((str(tk), str(d)[:10]))
                yield (d, tk), day_df

        intraday_stream = _tracked_stream(intraday_stream)

        # ── PHASE 4: run backtest with streaming ──
        strategy_def = strategy["definition"]
        print(f"[DEBUG ORCH] strategy_def type: {type(strategy_def)}")
        print(f"[DEBUG ORCH] strategy_def keys: {strategy_def.keys() if isinstance(strategy_def, dict) else 'NOT A DICT'}")
        print(f"[DEBUG ORCH] bias: {strategy_def.get('bias') if isinstance(strategy_def, dict) else 'N/A'}")

        # Initialize progress tracking
        from app.routers.backtest import backtest_progress
        if backtest_progress.get(req.dataset_id, {}).get("status") == "cancelled":
            backtest_progress[req.dataset_id] = {
                "status": "cancelled",
                "current": 0,
                "total": 0,
                "percent": 0.0
            }
            raise HTTPException(status_code=400, detail="Backtest cancelado")

        backtest_progress[req.dataset_id] = {
            "status": "running",
            "current": 0,
            "total": n_qualifying,
            "percent": 0.0
        }
        # Empuja el total (nº de pares) al estado async de inmediato → el frontend
        # muestra "0 / N pares" desde el primer poll, sin esperar al primer chunk.
        if on_progress is not None:
            try:
                on_progress(0, n_qualifying, 0.0)
            except Exception:
                pass

        _prog_last = {"pct": -1.0}

        def update_prog(current, total):
            from app.routers.backtest import backtest_progress
            state = backtest_progress.get(req.dataset_id)
            if state and state.get("status") == "cancelled":
                raise RuntimeError("BACKTEST_CANCELLED")

            pct = min(100.0, round((current / total) * 100.0, 1)) if total > 0 else 0.0
            # Reporta solo cuando el % (a 1 decimal) cambió → barra fluida en el
            # frontend sin escribir a Redis en cada chunk.
            if pct == _prog_last["pct"] and current != total:
                return
            _prog_last["pct"] = pct
            backtest_progress[req.dataset_id] = {
                "status": "running",
                "current": current,
                "total": total,
                "percent": pct,
            }
            if on_progress is not None:
                try:
                    on_progress(current, total, pct)
                except Exception:
                    # Progress mirroring must never break the backtest itself.
                    pass

        # Session config fallback: when the request omits market_sessions /
        # custom times, fall back to the values saved on the strategy before the
        # safe RTH default. Without this, a strategy saved with premarket
        # sessions ran RTH-only via paths that don't echo the field (e.g. the
        # public API defaults market_sessions to ["RTH"]) → premarket entries
        # were silently dropped. strategy_def may not be a dict — guard it.
        _sdef = strategy_def if isinstance(strategy_def, dict) else {}
        market_sessions = req.market_sessions or _sdef.get("market_sessions") or ["RTH"]
        custom_start_time = req.custom_start_time or _sdef.get("custom_start_time")
        custom_end_time = req.custom_end_time or _sdef.get("custom_end_time")

        _bt_kwargs = dict(
            strategy_def=strategy_def,
            init_cash=req.init_cash,
            risk_r=req.risk_r,
            risk_type=req.risk_type,
            fixed_ratio_delta=req.fixed_ratio_delta,
            size_by_sl=size_by_sl,
            fees=req.fees,
            fee_type=req.fee_type,
            slippage=req.slippage,
            market_sessions=market_sessions,
            custom_start_time=custom_start_time,
            custom_end_time=custom_end_time,
            locates_cost=req.locates_cost,
            locate_type=req.locate_type,
            max_locates=req.max_locates,
            look_ahead_prevention=req.look_ahead_prevention,
            monthly_expenses=req.monthly_expenses,
            progress_callback=update_prog,
        )

        # ── Modelos avanzados (2026-08-31) ────────────────────────────────
        # Sin el bloque `advanced_model`, esto es EXACTAMENTE la llamada de
        # siempre: mismos argumentos, mismo stream, mismo resultado.
        if _cfg_modelo is None:
            results = run_backtest(
                qualifying_df=qualifying,
                day_group_iter=intraday_stream,
                n_groups_hint=n_qualifying,
                **_bt_kwargs,
            )
        else:
            # Cada pasada necesita su PROPIO stream: `intraday_stream` es un
            # generador de un solo uso y el de arriba ya no sirve. Se crea uno
            # por ventana, y acotado a las fechas de esa ventana — asi la pasada
            # de entrenamiento no arrastra los meses de la de prueba ni al reves.
            from app.services.advanced_backtest import run_with_model

            def _pasada(qualifying_df=None, **extra):
                if qualifying_df is None or qualifying_df.empty:
                    return {"trades": [], "aggregate_metrics": {}, "day_results": [],
                            "equity_curves": []}
                _f = qualifying_df["date"].astype(str)
                stream = _tracked_stream(
                    get_intraday_stream(qualifying_df, _f.min(), _f.max()))
                return run_backtest(
                    qualifying_df=qualifying_df,
                    day_group_iter=stream,
                    n_groups_hint=len(qualifying_df),
                    **_bt_kwargs,
                    **extra,
                )

            logger.info("[MODELO] modo=%s entrena %s→%s, prueba %s→%s",
                        _cfg_modelo["mode"], _cfg_modelo["train_from"],
                        _cfg_modelo["train_to"], _cfg_modelo["test_from"],
                        _cfg_modelo["test_to"])
            results = run_with_model(_cfg_modelo, qualifying, _pasada, {})

        backtest_progress[req.dataset_id] = {
            "status": "completed",
            "current": n_qualifying,
            "total": n_qualifying,
            "percent": 100.0
        }

        # ── Reconciliación de completitud de datos ──
        # Candidatos (qualifying) vs ejecutados de verdad (lo que emitió el
        # stream). Si faltan, hubo descarte silencioso de intradía → el resultado
        # es parcial y NO reproducible. Se reporta SIEMPRE en el payload; con
        # BACKTEST_STRICT_COMPLETENESS=true además se rechaza (503).
        try:
            q_keys = set(
                zip(
                    qualifying["ticker"].astype(str),
                    pd.to_datetime(qualifying["date"]).dt.strftime("%Y-%m-%d"),
                )
            )
            n_expected = len(q_keys)
            missing = q_keys - _executed_keys
            n_missing = len(missing)
            n_executed = n_expected - n_missing
            pct_complete = round(100.0 * n_executed / n_expected, 2) if n_expected else 100.0
            missing_sample = sorted(f"{t}:{d}" for t, d in list(missing)[:50])
            results["data_completeness"] = {
                "expected_ticker_days": n_expected,
                "executed_ticker_days": n_executed,
                "missing_ticker_days": n_missing,
                "completeness_pct": pct_complete,
                "missing_sample": missing_sample,
            }
            if n_missing:
                logger.error(
                    f"[COMPLETENESS] {n_missing}/{n_expected} ticker-días candidatos "
                    f"SIN intradía → descartados en silencio (completitud "
                    f"{pct_complete:.1f}%). El resultado es PARCIAL y no reproducible "
                    f"hasta que la caché intradía esté completa. Muestra: "
                    f"{missing_sample[:10]}"
                )
                if _STRICT_COMPLETENESS:
                    raise HTTPException(
                        status_code=503,
                        detail=(
                            f"Backtest incompleto: {n_missing} de {n_expected} "
                            f"ticker-días candidatos no tienen intradía disponible "
                            f"({pct_complete:.1f}% completo). Con "
                            f"BACKTEST_STRICT_COMPLETENESS=true el motor rechaza "
                            f"resultados parciales — calienta la caché o revisa el lago."
                        ),
                    )
            else:
                logger.info(
                    f"[COMPLETENESS] 100% — {n_executed}/{n_expected} ticker-días ejecutados"
                )
        except HTTPException:
            raise
        except Exception as _rec_err:
            logger.warning(f"[COMPLETENESS] reconciliación falló (no crítico): {_rec_err}")

        t_end = time.time()
        total_elapsed = round(t_end - t0, 2)
        n_trades = len(results.get("trades", []))
        n_days = len(results.get("day_results", []))
        print(f"[TIMING] total backtest: {total_elapsed}s")
        log_phase("total", (t_end - t0) * 1000, dataset=req.dataset_id,
                  pairs=n_qualifying, trades=n_trades, days=n_days)
        logger.info(
            f"BACKTEST DONE {n_days} days, {n_trades} trades, total={total_elapsed}s"
        )
    except HTTPException:
        raise
    except AdvancedModelError as e:
        # Un modelo mal configurado (fechas que se solapan, sin features, un
        # periodo de entrenamiento vacio) es culpa de la configuracion, no un
        # fallo del servidor. Va como 400 y con el texto tal cual, porque el
        # diagnostico del frontend pinta los 5xx como "Response Data: {}" y
        # parece un error mudo.
        logger.warning("[MODELO] configuracion invalida: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        if isinstance(e, RuntimeError) and str(e) == "BACKTEST_CANCELLED":
            from app.routers.backtest import backtest_progress
            backtest_progress[req.dataset_id] = {
                "status": "cancelled",
                "current": 0,
                "total": 0,
                "percent": 0.0
            }
            logger.info(f"BACKTEST CANCELLED dataset={req.dataset_id}")
            raise HTTPException(status_code=400, detail="Backtest cancelado")
        logger.error(f"  backtest FAILED after {round(time.time()-t0, 2)}s: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error en backtest: {str(e)}")

    return sanitize_floats(results)
