"""
Dispatcher del simulador (EPIC D, PRD rendimiento-backtester §03.9).

Selecciona entre:
  - portfolio_sim.simulate  (Python puro — LA especificación, intacta; lista no-tocar)
  - simulate_jit            (kernel Numba de app/services/portfolio_sim_jit.py, rescatado
                             de la rama feat/f2-numba-engine `435ef11` de Adrián,
                             MATCHED tol 0 contra el Python)

Flag: BACKTEST_NUMBA_SIM=1 activa el kernel (default 0 = Python). Se lee en cada
llamada (barato) para poder alternar en tests/bench sin reimportar.

`simulate_jit` es el wrapper de la rama F2 adaptado a módulo propio: mapea
strings/None/partial-TPs a enums+arrays, llama al kernel y reconstruye los dicts
de trade EXACTOS (redondeos con round() de Python, `fees` ausente en parciales,
locates fee post-proceso). Contrato completo en el PRD §03.4/§03.8.
"""
import math
import os
from datetime import datetime, timezone

import numpy as np

from app.services.portfolio_sim import simulate as _legacy_simulate
from app.services import portfolio_sim_jit as _pjit
from app.services.portfolio_sim_jit import _core_simulate_jit


def _numba_sim_enabled() -> bool:
    return os.getenv("BACKTEST_NUMBA_SIM", "0").strip().lower() in ("1", "true", "yes", "on")


def simulate(**kwargs) -> dict:
    """Punto único de entrada del simulador (misma firma/retorno que portfolio_sim)."""
    if _numba_sim_enabled():
        return simulate_jit(**kwargs)
    return _legacy_simulate(**kwargs)


def warmup() -> float:
    """Compila el kernel (cache=True) fuera del primer backtest. Devuelve segundos.
    Best-effort: si numba fallara, el dispatcher sigue sirviendo el path Python."""
    import time
    t0 = time.time()
    try:
        n = 8
        close = np.linspace(10.0, 11.0, n)
        entries = np.zeros(n, dtype=bool)
        entries[2] = True
        simulate_jit(
            close=close, open_=close, high=close * 1.01, low=close * 0.99,
            entries=entries, exits=np.zeros(n, dtype=bool),
            direction="longonly", init_cash=1000.0, risk_r=10.0,
            timestamps=(np.arange(n) * 60_000_000_000).astype(np.int64),
        )
    except Exception:
        pass
    return time.time() - t0


# reason code -> exact exit_reason string (1:1 with the original literals)
_REASON_STR = {
    0: "SL",
    1: "TP",
    2: "Time Limit",
    3: "EOD",
    4: "Signal",
    5: "Trailing",
    6: "Partial TP",
    7: "Partial TP (EOD)",
    8: "Partial TP (Time)",
    9: "Partial TP (Hour)",
}
# partial reasons whose trade dict has NO "fees" key (matches original)
_PARTIAL_REASONS = (6, 7, 8, 9)


def simulate_jit(
    close: np.ndarray,
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    entries: np.ndarray,
    exits: np.ndarray,
    direction: str = "longonly",
    init_cash: float = 10000.0,
    risk_r: float = 100.0,
    risk_type: str = "FIXED",
    fixed_ratio_delta: float = 500.0,
    size_by_sl: bool = False,
    fees: float = 0.0,
    fee_type: str = "PERCENT",  # "PERCENT" or "FLAT"
    slippage: float = 0.0,
    sl_stop: float | None = None,
    sl_trail: bool = False,
    tp_stop: float | None = None,
    tp_time_limit: float | str | None = None,
    accumulate: bool = False,
    max_reentries: int = -1,
    trail_pct: float | None = None,
    locates_cost: float = 0.0,
    locate_type: str = "FLAT",
    look_ahead_prevention: bool = True,
    patch_mask: np.ndarray | None = None,
    partial_take_profits: list | None = None,
    hs_type: str | None = None,
    hs_value: str | float | None = None,
    hs_operator: str | None = ">=",
    hs_offset_pct: float | None = 0.0,
    hods: np.ndarray | None = None,
    lods: np.ndarray | None = None,
    pm_highs: np.ndarray | None = None,
    pm_lows: np.ndarray | None = None,
    prev_highs: np.ndarray | None = None,
    prev_lows: np.ndarray | None = None,
    timestamps: np.ndarray | None = None,
    elapsed_limit: float = -1.0,
    elapsed_operator: str = "GREATER_THAN_OR_EQUAL",
) -> dict:
    n = len(close)
    is_long = direction == "longonly"

    # --- coerce market arrays to the exact dtypes the JIT core expects ---
    close = np.ascontiguousarray(close, dtype=np.float64)
    open_ = np.ascontiguousarray(open_, dtype=np.float64)
    high = np.ascontiguousarray(high, dtype=np.float64)
    low = np.ascontiguousarray(low, dtype=np.float64)
    entries = np.ascontiguousarray(entries, dtype=np.bool_)
    exits = np.ascontiguousarray(exits, dtype=np.bool_)

    # --- string params -> int enums ---
    if risk_type == "PERCENT":
        risk_type_code = _pjit.RISK_PERCENT
    elif risk_type == "FIXED_RATIO":
        risk_type_code = _pjit.RISK_HSQRT
    else:
        risk_type_code = _pjit.RISK_FIXED

    fee_type_code = _pjit.FEE_FLAT if fee_type == "FLAT" else _pjit.FEE_PERCENT

    hs_type_code = 1 if hs_type == "Market Structure (HOD/LOD)" else 0

    if hs_value == "HOD":
        hs_value_code = _pjit.HS_HOD
    elif hs_value == "LOD":
        hs_value_code = _pjit.HS_LOD
    elif hs_value == "PMH":
        hs_value_code = _pjit.HS_PMH
    elif hs_value == "PML":
        hs_value_code = _pjit.HS_PML
    elif hs_value in ("Previous Max", "PrevMax"):
        hs_value_code = _pjit.HS_PREVMAX
    elif hs_value in ("Previous Min", "PrevMin", "Previous Low", "PrevLow"):
        hs_value_code = _pjit.HS_PREVMIN
    else:
        hs_value_code = _pjit.HS_NONE

    # signed SL offset (constant per call; computed exactly as the original)
    offset_pct = float(hs_offset_pct) if hs_offset_pct is not None else 0.0
    offset_op = hs_operator or ">="
    sign = 1.0 if offset_op in (">", ">=") else -1.0
    sl_offset = sign * offset_pct / 100.0

    if elapsed_operator in ("GREATER_THAN_OR_EQUAL", "GTE"):
        elapsed_op_code = _pjit.ELAPSED_GTE
    elif elapsed_operator in ("GREATER_THAN", "GT"):
        elapsed_op_code = _pjit.ELAPSED_GT
    elif elapsed_operator in ("LESS_THAN", "LT"):
        elapsed_op_code = _pjit.ELAPSED_LT
    elif elapsed_operator in ("LESS_THAN_OR_EQUAL", "LTE"):
        elapsed_op_code = _pjit.ELAPSED_LTE
    elif elapsed_operator in ("EQUAL", "EQ"):
        elapsed_op_code = _pjit.ELAPSED_EQ
    else:
        elapsed_op_code = _pjit.ELAPSED_GTE

    # full take-profit by time (minutes vs HOUR:h:m)
    tp_time_mode = 0
    tp_time_value = 0.0
    tp_hour = 0
    tp_min = 0
    if tp_time_limit is not None:
        if isinstance(tp_time_limit, str) and tp_time_limit.startswith("HOUR:"):
            tp_time_mode = 2
            try:
                _p = tp_time_limit.split(":")
                tp_hour = int(_p[1])
                tp_min = int(_p[2])
            except Exception:
                tp_hour, tp_min = 0, 0
        else:
            tp_time_mode = 1
            try:
                tp_time_value = float(tp_time_limit)
            except Exception:
                tp_time_value = 0.0

    # --- optional scalar flags ---
    has_sl_stop = sl_stop is not None
    sl_stop_v = float(sl_stop) if has_sl_stop else 0.0
    has_tp_stop = tp_stop is not None
    tp_stop_v = float(tp_stop) if has_tp_stop else 0.0
    has_trail_pct = trail_pct is not None
    trail_pct_v = float(trail_pct) if has_trail_pct else 0.0

    # --- optional arrays -> (flag, zeros-or-array) ---
    def _opt(arr):
        if arr is None:
            return False, np.zeros(n, dtype=np.float64)
        return True, np.ascontiguousarray(arr, dtype=np.float64)

    has_hods, hods_a = _opt(hods)
    has_lods, lods_a = _opt(lods)
    has_pm_high, pm_high_a = _opt(pm_highs)
    has_pm_low, pm_low_a = _opt(pm_lows)
    has_prev_high, prev_high_a = _opt(prev_highs)
    has_prev_low, prev_low_a = _opt(prev_lows)

    if timestamps is None:
        has_timestamps = False
        timestamps_a = np.zeros(n, dtype=np.int64)
    else:
        has_timestamps = True
        timestamps_a = np.ascontiguousarray(timestamps, dtype=np.int64)

    if patch_mask is None:
        has_patch_mask = False
        patch_mask_a = np.zeros(n, dtype=np.bool_)
    else:
        has_patch_mask = True
        patch_mask_a = np.ascontiguousarray(patch_mask, dtype=np.bool_)

    # --- partial take-profits -> parallel numeric arrays ---
    pt_list = partial_take_profits or []
    n_pt = len(pt_list)
    _sz = n_pt if n_pt > 0 else 1
    pt_type = np.zeros(_sz, dtype=np.int64)
    pt_value = np.zeros(_sz, dtype=np.float64)
    pt_cap_frac = np.zeros(_sz, dtype=np.float64)
    pt_hour = np.zeros(_sz, dtype=np.int64)
    pt_min = np.zeros(_sz, dtype=np.int64)
    for idx, pt in enumerate(pt_list):
        dist = pt["distance_pct"]
        pt_cap_frac[idx] = pt["capital_pct"]
        if dist == "EOD":
            pt_type[idx] = _pjit.PT_EOD
        elif isinstance(dist, str) and dist.startswith("TIME:"):
            pt_type[idx] = _pjit.PT_TIME
            try:
                pt_value[idx] = float(dist.split(":")[1])
            except Exception:
                pt_value[idx] = 0.0
        elif isinstance(dist, str) and dist.startswith("HOUR:"):
            pt_type[idx] = _pjit.PT_HOUR
            try:
                _p = dist.split(":")
                pt_hour[idx] = int(_p[1])
                pt_min[idx] = int(_p[2])
            except Exception:
                pt_hour[idx], pt_min[idx] = 0, 0
        else:
            pt_type[idx] = _pjit.PT_PCT
            pt_value[idx] = float(dist)

    # --- precompute hour/minute only when an HOUR-based rule exists ---
    # (replica datetime.fromtimestamp(ts/1e9, utc).hour/.minute con aritmética
    #  entera: idéntico para ts >= 0, sin coste de objetos datetime por barra)
    needs_hours = (tp_time_mode == 2) or bool(np.any(pt_type == _pjit.PT_HOUR))
    if needs_hours and has_timestamps:
        has_hours = True
        secs = timestamps_a // 1_000_000_000
        row_hours = ((secs // 3600) % 24).astype(np.int64)
        row_minutes = ((secs // 60) % 60).astype(np.int64)
    else:
        has_hours = False
        row_hours = np.zeros(n, dtype=np.int64)
        row_minutes = np.zeros(n, dtype=np.int64)

    # --- run the JIT core ---
    (
        equity, k,
        r_entry_idx, r_exit_idx, r_entry_px, r_exit_px, r_pnl, r_fees,
        r_return_pct, r_size, r_reason, r_mae, r_mfe, r_stop,
        max_short_size_today, last_risk_amount,
    ) = _core_simulate_jit(
        close, open_, high, low, entries, exits,
        is_long,
        float(init_cash), float(risk_r),
        risk_type_code,
        float(fixed_ratio_delta),
        bool(size_by_sl),
        float(fees), fee_type_code,
        float(slippage),
        has_sl_stop, sl_stop_v,
        bool(sl_trail),
        has_tp_stop, tp_stop_v,
        tp_time_mode, tp_time_value, tp_hour, tp_min,
        bool(accumulate),
        int(max_reentries),
        has_trail_pct, trail_pct_v,
        bool(look_ahead_prevention),
        hs_type_code, hs_value_code, sl_offset,
        has_hods, hods_a,
        has_lods, lods_a,
        has_pm_high, pm_high_a,
        has_pm_low, pm_low_a,
        has_prev_high, prev_high_a,
        has_prev_low, prev_low_a,
        has_timestamps, timestamps_a,
        has_patch_mask, patch_mask_a,
        has_hours, row_hours, row_minutes,
        float(elapsed_limit), elapsed_op_code,
        n_pt, pt_type, pt_value, pt_cap_frac, pt_hour, pt_min,
    )

    # --- rebuild the exact trade dicts (rounding in Python, as the original) ---
    direction_str = "Long" if is_long else "Short"
    trades: list[dict] = []
    for t in range(k):
        rc = int(r_reason[t])
        rec = {
            "entry_idx": int(r_entry_idx[t]),
            "exit_idx": int(r_exit_idx[t]),
            "entry_price": round(r_entry_px[t], 6),
            "exit_price": round(r_exit_px[t], 6),
            "pnl": round(r_pnl[t], 4),
            "return_pct": round(r_return_pct[t], 4),
            "direction": direction_str,
            "status": "Closed",
            "size": round(r_size[t], 6),
            "exit_reason": _REASON_STR[rc],
            "mae": round(r_mae[t], 4),
            "mfe": round(r_mfe[t], 4),
            "stop_loss": round(r_stop[t], 6),
        }
        if rc not in _PARTIAL_REASONS:
            # el trade de cierre final SÍ lleva fees; los parciales NO (quirk contractual)
            rec_final = dict(rec)
            rec_final["fees"] = round(r_fees[t], 4)
            # preservar el ORDEN de claves del original (pnl, fees, return_pct, ...)
            rec = {
                "entry_idx": rec["entry_idx"], "exit_idx": rec["exit_idx"],
                "entry_price": rec["entry_price"], "exit_price": rec["exit_price"],
                "pnl": rec["pnl"], "fees": rec_final["fees"],
                "return_pct": rec["return_pct"], "direction": rec["direction"],
                "status": rec["status"], "size": rec["size"],
                "exit_reason": rec["exit_reason"], "mae": rec["mae"],
                "mfe": rec["mfe"], "stop_loss": rec["stop_loss"],
            }
        trades.append(rec)

    # --- Deduct Daily Locates Fee (verbatim from the original; runs once) ---
    if max_short_size_today > 0 and locates_cost > 0:
        if locate_type == "PERCENT":
            if risk_type == "PERCENT":
                day_risk_unit = init_cash * (risk_r / 100.0)
            else:
                day_risk_unit = risk_r
            cost_per_100 = day_risk_unit * (locates_cost / 100.0)
        else:
            cost_per_100 = locates_cost

        blocks_of_100 = math.ceil(max_short_size_today / 100.0)
        daily_locates_fee = blocks_of_100 * cost_per_100

        # assign the deduction to the first short trade
        for t in trades:
            if t["direction"] == "Short":
                t["pnl"] = round(t["pnl"] - daily_locates_fee, 4)
                t["fees"] = round(t.get("fees", 0.0) + daily_locates_fee, 4)
                break

        # reflect it on the equity curve
        for i in range(len(equity)):
            equity[i] -= daily_locates_fee

    # --- finalize ---
    results = {"equity": equity, "trades": trades}
    if risk_type == "PERCENT":
        results["last_risk_amount"] = last_risk_amount
    else:
        results["last_risk_amount"] = risk_r

    return results
