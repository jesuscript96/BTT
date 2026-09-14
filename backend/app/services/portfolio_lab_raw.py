"""Portfolio EN CRUDO: varias corridas guardadas sumadas con la ejecucion que se
fije AQUI, estrategia por estrategia.

Modulo LOCAL del laboratorio (gated por PORTFOLIO_LAB_ENABLED, ver
routers/portfolio_lab.py). No lo usa el bot ni comparte nada con el motor.

LA IDEA (Jaume, 14-sep-2026): «fijar nosotros aqui en el portfolio el
slippage, el capital a apostar por trade en fijo o en %, los locates (y sus
tipos) tal y como se usan en el backtester y las comisiones en % o en $, POR
ESTRATEGIA; lo que ajustamos en el panel izquierdo del backtest, pero aqui,
de manera que no tengamos en cuenta lo que ya tiene ajustado de base la
estrategia: la reseteamos para esta visualizacion». Los gastos fijos van
aparte, a nivel de portfolio, y los de cada corrida NO se cuentan.

COMO SE RESETEA UN TRADE GUARDADO SIN REHACER EL BACKTEST. El trade guardado
trae `size`, `avg_entry_price`, `exit_price`, `pnl` (neto de comisiones y
slippage, limpio de locates), `fees`, `stop_loss` y, si la corrida sorteo
locates, `locate_ref_price` (precio de referencia del ticker-dia). Con eso:

  1. Se DESHACEN los costes de la corrida: bruto = pnl + fees + slippage
     estimado (fraccion * (entrada + salida) * acciones, la formula literal
     de portfolio_sim). Es la unica pata aproximada (el slippage va dentro de
     los precios de fill); comisiones y tamano se deshacen exactos.
  2. Bruto POR ACCION = bruto / acciones. Es la senal pura del trade.
  3. Se decide el tamano nuevo segun la ejecucion de SU estrategia, igual
     que dimensiona el motor real (portfolio_sim: `risk_amount / precio` o
     `risk_amount / distancia al stop`), sobre la ENTRADA del trade (primera
     ejecucion) y conservando la proporcion de las piramides:
       El modo lo decide LA ESTRATEGIA ("auto": su «Tamaño por SL»), aqui
       solo se pone el R por trade, fijo o en %, como en el backtester.
       - "capital": entrada = X / precio de entrada, con X en $ o en % del
         capital del portfolio CON EL QUE EMPEZO EL DIA (compound);
       - "risk":    entrada = R / distancia inicial al stop, con R en $ o en
         %. La distancia inicial se recupera exacta si la corrida dimensiono
         por stop (riesgo de la corrida / acciones de la entrada); si no, se
         usa el ultimo stop guardado (aproximado, se cuenta en `stop_aprox`);
       - "as_saved": las acciones de la corrida y su neto tal cual
         (pnl_with_locates), sin tocar nada.
     Los topes de caja, hibrido y locates de la corrida NO se reproducen: eso
     es justo lo que se resetea.
  4. Se REAPLICAN los costes fijados aqui: comisiones ($ por accion en los dos
     lados, o % del valor operado en cada lado), slippage (fraccion del precio
     en cada lado) y locates por ticker-dia sobre el mayor corto del dia, por
     paquetes de 100: fijos ($ por paquete) o ALEATORIOS con el mismo sorteo
     del backtester (`locates_random.precio_locate`, determinista por
     (semilla, ticker, fecha) y centrado por el precio de referencia del dia,
     que el trade guarda; si no lo guarda, se usa el precio de entrada).

Lo que NO se puede reconstruir desde los trades y queda para una fase con
backtest de verdad (efimero, sin guardar): Black Swan y Halts, que dependen de
lo que paso vela a vela dentro de cada trade.

Ademas: la exposicion (nocional abierto a la vez entre TODAS las estrategias,
AL MINUTO: un trade de premercado que cierra a las 09:29 y uno de RTH que abre
a las 09:35 no coinciden) y un tope opcional que salta o recorta lo que no cabe.

La R de cada trade se define por su stop: neto / (|entrada - stop| * acciones).
Es la misma en todas las estrategias y modos; sin stop guardado, 0.
"""
from __future__ import annotations

import heapq
import math
import threading
from datetime import datetime
from typing import Any, Optional

import numpy as np

from app.services import locates_random as lr
from app.services import portfolio_lab_engine as ple
from app.services import robustness_service as rs

_TRADE_FIELDS = (
    "ticker", "date", "entry_time", "exit_time", "entry_price", "avg_entry_price",
    "exit_price", "pnl", "pnl_with_locates", "fees", "direction", "size", "exit_reason",
    "r_multiple", "stop_loss", "locate_ref_price", "locate_pkg_price", "mae", "mfe",
)

# Ejecucion por defecto de una estrategia (lo que sale en la fila del panel).
EXEC_DEFAULT: dict[str, Any] = {
    # auto = lo que diga la ESTRATEGIA (su «Tamaño por SL»): risk si dimensiona
    # por stop, capital si no. Igual que el panel del backtester: ahi solo se
    # pone el R por trade y el modo viene de la estrategia. capital | risk
    # fuerzan uno; as_saved deja el trade tal cual.
    "sizing": "auto",
    "size_value": 5.0,
    "size_unit": "pct",         # usd | pct (% del capital del dia)
    "fees": 0.0,
    "fee_type": "FLAT",         # FLAT ($ por accion) | PERCENT (% del valor, unidad de la UI)
    "slippage_pct": 0.0,        # % de la UI
    "locates": "none",          # none | fixed | random
    "locates_cost": 0.0,        # $ por paquete de 100 (fixed)
    "locates_min": 1.0,
    "locates_max": 10.0,
    "locates_seed": 1,
}


# ── Cache en proceso de las corridas ────────────────────────────────────
# Una corrida guardada es inmutable (su id es el job_id; un re-guardado del
# mismo job renueva `executed_at`, que forma parte de la clave). Parsear el
# results_json de 13 corridas cuesta 2-3 s con la cache del disco fria; con
# esto, la segunda vez es instantanea.
_CACHE_LOCK = threading.Lock()
_RUN_CACHE: dict[tuple[str, str], dict] = {}
_RUN_CACHE_MAX = 40


def _cache_get(key: tuple[str, str]) -> Optional[dict]:
    with _CACHE_LOCK:
        return _RUN_CACHE.get(key)


def _cache_put(key: tuple[str, str], value: dict) -> None:
    with _CACHE_LOCK:
        if len(_RUN_CACHE) >= _RUN_CACHE_MAX:
            _RUN_CACHE.pop(next(iter(_RUN_CACHE)))
        _RUN_CACHE[key] = value


def latest_run_ids(con, strategy_ids: set[str]) -> dict[str, tuple[str, str]]:
    """{strategy_id: (run_id, executed_at)} de la corrida mas reciente.

    Solo columnas tipadas: es el escaneo barato de list_runs_for_strategies,
    SIN el `_attach_params` que parsea el JSON de cada corrida (esa era la
    parte cara del endpoint de la curva del baul: ~1 s por llamada).
    """
    rows = con.execute(
        "SELECT id, strategy_ids, executed_at FROM backtest_results ORDER BY executed_at DESC"
    ).fetchall()
    best: dict[str, tuple[str, str]] = {}
    for run_id, sids, ts in rows:
        for sid in rs._as_list(sids):
            if sid in strategy_ids and sid not in best:
                best[sid] = (run_id, str(ts) if ts else "")
    return best


def load_runs(con, wanted: dict[str, tuple[str, str]]) -> dict[str, dict]:
    """Carga (con cache) trades, parametros y curva de las corridas pedidas.

    Las que no esten en cache se extraen en UNA consulta con `json_extract` de
    varias rutas a la vez, que parsea cada documento una sola vez.
    """
    out: dict[str, dict] = {}
    missing: dict[str, str] = {}
    for sid, (run_id, ts) in wanted.items():
        hit = _cache_get((run_id, ts))
        if hit is not None:
            out[sid] = hit
        else:
            missing[run_id] = sid
    if missing:
        ids = list(missing)
        placeholders = ", ".join("?" for _ in ids)
        rows = con.execute(
            "SELECT id, json_extract(results_json, "
            "['$.trades', '$.backtest_params', '$.global_equity', '$.aggregate_metrics']) "
            f"FROM backtest_results WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
        for run_id, parts in rows:
            parts = parts or []
            trades_raw = rs._as_list(parts[0] if len(parts) > 0 else None)
            params = rs._as_dict(parts[1] if len(parts) > 1 else None)
            equity = rs._as_list(parts[2] if len(parts) > 2 else None)
            agg = rs._as_dict(parts[3] if len(parts) > 3 else None)
            trades = []
            for t in trades_raw:
                if not isinstance(t, dict):
                    continue
                slim = {k: t.get(k) for k in _TRADE_FIELDS if k in t}
                # Tamano de la ENTRADA (primera ejecucion): `size` es la
                # posicion entera con las piramides, y para re-dimensionar
                # hay que escalar desde la entrada y conservar la proporcion.
                ejec = t.get("executions") or []
                first = next((e for e in ejec if isinstance(e, dict) and e.get("kind") == "entry"), None)
                slim["init_size"] = _f(first.get("size")) if first else 0.0
                slim["init_price"] = _f(first.get("price")) if first else 0.0
                trades.append(slim)
            payload = {
                "run_id": run_id,
                "backtest_params": params,
                "trades": trades,
                "equity": [{"time": p.get("time"), "value": p.get("value")} for p in equity if isinstance(p, dict)],
                "aggregate_metrics": agg,
            }
            sid = missing[run_id]
            _cache_put(wanted[sid], payload)
            out[sid] = payload
    return out


# ── Utiles ──────────────────────────────────────────────────────────────

def _ts(s: Any) -> Optional[float]:
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:19], "%Y-%m-%d %H:%M:%S").timestamp()
    except ValueError:
        try:
            return datetime.strptime(str(s)[:10], "%Y-%m-%d").timestamp()
        except ValueError:
            return None


def _f(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return x if math.isfinite(x) else default


def run_conditions(params: dict) -> dict:
    """Con que se corrio la corrida (informativo: aqui se resetea)."""
    p = params or {}
    return {
        "init_cash": _f(p.get("init_cash")),
        "risk_type": str(p.get("risk_type") or "FIXED").upper(),
        "risk_r": _f(p.get("risk_r")),
        "size_by_sl": bool(p.get("size_by_sl", True)),
        "fees": _f(p.get("fees")),
        "fee_type": str(p.get("fee_type") or "FLAT").upper(),
        "slippage": _f(p.get("slippage")),
        "locates_cost": _f(p.get("locates_cost")),
        "locate_type": str(p.get("locate_type") or "FLAT").upper(),
        "locates_random": bool(p.get("locates_random")),
        "locates_random_min": _f(p.get("locates_random_min")),
        "locates_random_max": _f(p.get("locates_random_max")),
        "locates_seed": int(_f(p.get("locates_seed"))),
        "monthly_expenses": _f(p.get("monthly_expenses")),
        "start_date": p.get("start_date"),
        "end_date": p.get("end_date"),
    }


def _exec_cfg(raw: Optional[dict]) -> dict:
    cfg = dict(EXEC_DEFAULT)
    for k, v in (raw or {}).items():
        if k in cfg and v is not None:
            cfg[k] = v
    cfg["sizing"] = str(cfg["sizing"])
    cfg["size_unit"] = str(cfg["size_unit"])
    cfg["fee_type"] = str(cfg["fee_type"]).upper()
    cfg["locates"] = str(cfg["locates"])
    for k in ("size_value", "fees", "slippage_pct", "locates_cost", "locates_min", "locates_max"):
        cfg[k] = _f(cfg[k])
    cfg["locates_seed"] = int(_f(cfg["locates_seed"]))
    return cfg


def _start_of_day_equity(global_equity: list[dict], init_cash: float) -> dict[str, float]:
    """Balance de apertura de cada dia de la corrida guardada (para deshacer
    el riesgo PERCENT). El punto i de la curva es el cierre del dia i."""
    out: dict[str, float] = {}
    prev = init_cash
    for p in global_equity or []:
        ts = p.get("time")
        if ts is None:
            continue
        out[rs._epoch_to_day(ts)] = prev
        prev = _f(p.get("value"), prev)
    return out


# ── Motor ───────────────────────────────────────────────────────────────

def simulate(runs: list[dict], cfg: dict) -> dict:
    """Suma N corridas con la ejecucion fijada por estrategia.

    cfg:
      capital            capital del portfolio (base del compound, del
                         retorno y del Monte Carlo)
      per_strategy       {strategy_id: exec}  (ver EXEC_DEFAULT)
      default_exec       exec para las que no esten en per_strategy
      monthly_expenses   $/mes del portfolio (una cuenta)
      max_exposure_usd   tope de nocional abierto a la vez (0 = sin tope)
      cap_mode           "skip" | "trim"
      start_date/end_date
    """
    capital = _f(cfg.get("capital"))
    if capital <= 0:
        raise ValueError("El capital del portfolio tiene que ser mayor que cero")
    expenses = _f(cfg.get("monthly_expenses"))
    cap = _f(cfg.get("max_exposure_usd"))
    # Tope en % del capital DEL DIA: 700 $ dejan de ser el 7 % en cuanto la
    # cuenta crece (Jaume, 14-sep). Manda sobre el tope en $ si viene > 0.
    cap_pct = _f(cfg.get("max_exposure_pct"))
    trim = str(cfg.get("cap_mode") or "skip") == "trim"
    d_from = str(cfg.get("start_date") or "") or None
    d_to = str(cfg.get("end_date") or "") or None
    default_exec = _exec_cfg(cfg.get("default_exec"))
    per_cfg_raw = cfg.get("per_strategy") or {}

    n = len(runs)
    execs: list[dict] = []
    for run in runs:
        raw_e = per_cfg_raw.get(str(run.get("strategy_id")))
        ex = _exec_cfg(raw_e) if raw_e else dict(default_exec)
        if ex["sizing"] == "auto":
            params = run.get("backtest_params") or {}
            ex["sizing"] = "risk" if params.get("size_by_sl") else "capital"
        execs.append(ex)

    # ── 1. Preparar los trades: deshacer la corrida, dejar la senal por accion ─
    by_day: list[dict[str, list[dict]]] = []
    spans: list[tuple[str, str]] = []
    unsized = [0] * n
    sin_stop = [0] * n
    stop_aprox_n = [0] * n
    for i, run in enumerate(runs):
        params = run.get("backtest_params") or {}
        init_saved = _f(params.get("init_cash"), 10000.0)
        is_pct = str(params.get("risk_type") or "").upper() == "PERCENT"
        risk_saved_r = _f(params.get("risk_r"))
        slip_saved = _f(params.get("slippage"))
        by_sl_saved = bool(params.get("size_by_sl"))
        sod = _start_of_day_equity(run.get("equity") or [], init_saved) if is_pct else {}
        idx: dict[str, list[dict]] = {}
        dates: list[str] = []
        for t in run.get("trades") or []:
            d = str(t.get("date") or "")[:10]
            if not d or (d_from and d < d_from) or (d_to and d > d_to):
                continue
            size = _f(t.get("size"))
            entry = _f(t.get("avg_entry_price")) or _f(t.get("entry_price"))
            exitp = _f(t.get("exit_price"))
            t0 = _ts(t.get("entry_time")) or _ts(d)
            if size <= 0 or entry <= 0 or t0 is None:
                unsized[i] += 1
                continue
            t1 = _ts(t.get("exit_time")) or t0
            if t1 < t0:
                t1 = t0
            pnl = _f(t.get("pnl"))
            pnl_loc = _f(t.get("pnl_with_locates"), pnl)
            fees_saved = _f(t.get("fees"))
            gross = pnl + fees_saved + slip_saved * (entry + exitp) * size
            if is_pct:
                e0 = sod.get(d)
                risk_orig = (risk_saved_r / 100.0) * (e0 if e0 and e0 > 0 else init_saved)
            else:
                risk_orig = risk_saved_r
            init_size = _f(t.get("init_size")) or size
            init_price = _f(t.get("init_price")) or _f(t.get("entry_price")) or entry
            pyr = size / init_size if init_size > 0 else 1.0
            # Distancia inicial al stop: exacta si la corrida dimensiono por
            # stop (riesgo / acciones de la entrada); si no, el ultimo stop.
            stop = _f(t.get("stop_loss"))
            if by_sl_saved and risk_orig > 0 and init_size > 0:
                stop_dist = risk_orig / init_size
                stop_aprox = False
            else:
                stop_dist = abs(init_price - stop) if stop > 0 and abs(init_price - stop) > 1e-9 else 0.0
                stop_aprox = stop_dist > 0
            if stop_dist <= 0:
                sin_stop[i] += 1
            elif stop_aprox:
                stop_aprox_n[i] += 1
            dates.append(d)
            idx.setdefault(d, []).append({
                "t0": t0, "t1": t1,
                "ticker": str(t.get("ticker") or ""),
                "direction": str(t.get("direction") or ""),
                "entry": entry, "exit": exitp,
                "size_saved": size,
                "init_price": init_price,
                "pyr": pyr,
                "gross_ps": gross / size,
                "pnl_saved_net": pnl_loc,
                "fees_saved": fees_saved,
                "locate_saved": max(0.0, pnl - pnl_loc),
                "stop_dist": stop_dist,
                "risk_orig": risk_orig,
                "ref_price": _f(t.get("locate_ref_price")) or entry,
                "entry_time": str(t.get("entry_time") or ""),
                "exit_time": str(t.get("exit_time") or ""),
                "exit_reason": str(t.get("exit_reason") or ""),
            })
        by_day.append(idx)
        spans.append((min(dates), max(dates)) if dates else ("", ""))

    calendar = sorted({d for idx in by_day for d in idx})
    if not calendar:
        raise ValueError("Ninguna estrategia tiene trades en el rango elegido")

    # ── 2. Dia a dia: dimensionar con el capital del dia, costes, locates ──
    equity = capital
    months_seen: set[str] = set()
    ruined = False
    equity_curve: list[float] = []
    daily_pnl: list[float] = []
    daily_ret: list[float] = []
    per_pnl: list[list[float]] = [[] for _ in range(n)]
    per_trades: list[list[int]] = [[] for _ in range(n)]
    per_locates: list[list[float]] = [[] for _ in range(n)]
    tot = [
        {"pnl_net": 0.0, "gross": 0.0, "n_trades": 0, "wins": 0, "fees": 0.0, "slippage": 0.0,
         "locates": 0.0, "gross_win": 0.0, "gross_loss": 0.0, "notional": 0.0}
        for _ in range(n)
    ]
    tot_fees = tot_slip = tot_loc = tot_exp = 0.0
    trade_rows: list[tuple[str, str, int, float, float]] = []
    accepted: list[dict] = []
    loc_prices_drawn: list[float] = []

    for d in calendar:
        month = d[:7]
        expense = 0.0
        if expenses > 0 and month not in months_seen:
            months_seen.add(month)
            expense = expenses
        equity_open = equity
        if equity_open <= 0:
            ruined = True
        if ruined:
            expense = 0.0
        day_total = 0.0
        for i in range(n):
            trades_d = by_day[i].get(d)
            if ruined or not trades_d:
                per_pnl[i].append(0.0)
                per_trades[i].append(0)
                per_locates[i].append(0.0)
                continue
            ex = execs[i]
            sizing = ex["sizing"]
            pnl_i = 0.0
            loc_i = 0.0
            shorts_max: dict[str, float] = {}
            shorts_ref: dict[str, float] = {}
            n_i = 0
            for tr in trades_d:
                if sizing == "as_saved":
                    new_size = tr["size_saved"]
                    net = tr["pnl_saved_net"]
                    fee = tr["fees_saved"]
                    slip = 0.0
                    gross = net + fee + tr["locate_saved"]
                    loc_own = tr["locate_saved"]
                    loc_i += loc_own
                else:
                    if sizing == "risk":
                        r_usd = ex["size_value"] if ex["size_unit"] == "usd" else equity_open * ex["size_value"] / 100.0
                        if tr["stop_dist"] > 0:
                            new_size = (r_usd / tr["stop_dist"]) * tr["pyr"]
                        elif tr["risk_orig"] > 0:
                            new_size = tr["size_saved"] * (r_usd / tr["risk_orig"])
                        else:
                            new_size = 0.0
                    else:
                        x_usd = ex["size_value"] if ex["size_unit"] == "usd" else equity_open * ex["size_value"] / 100.0
                        new_size = (x_usd / tr["init_price"]) * tr["pyr"]
                    if new_size <= 0:
                        continue
                    gross = tr["gross_ps"] * new_size
                    if ex["fee_type"] == "PERCENT":
                        fee = (ex["fees"] / 100.0) * (tr["entry"] + tr["exit"]) * new_size
                    else:
                        fee = ex["fees"] * new_size * 2.0
                    slip = (ex["slippage_pct"] / 100.0) * (tr["entry"] + tr["exit"]) * new_size
                    net = gross - fee - slip
                    loc_own = 0.0
                    if tr["direction"] == "Short" and ex["locates"] != "none":
                        tk = tr["ticker"]
                        if new_size > shorts_max.get(tk, 0.0):
                            shorts_max[tk] = new_size
                            shorts_ref[tk] = tr["ref_price"]
                notional = new_size * tr["entry"]
                risk_new = tr["stop_dist"] * (new_size / tr["pyr"] if tr["pyr"] > 0 else new_size)
                r_ref = (net / risk_new) if risk_new > 0 else 0.0
                pnl_i += net
                n_i += 1
                st = tot[i]
                st["n_trades"] += 1
                st["gross"] += gross
                st["fees"] += fee
                st["slippage"] += slip
                st["notional"] += notional
                if net > 0:
                    st["wins"] += 1
                    st["gross_win"] += net
                elif net < 0:
                    st["gross_loss"] += -net
                tot_fees += fee
                tot_slip += slip
                trade_rows.append((d, tr["entry_time"], i, r_ref, net))
                accepted.append({
                    "date": d, "si": i, "t0": tr["t0"], "t1": tr["t1"], "ticker": tr["ticker"],
                    "dir": tr["direction"][:1], "entry": tr["entry_time"][11:16], "exit": tr["exit_time"][11:16],
                    "entry_px": tr["entry"], "exit_px": tr["exit"], "size": new_size, "notional": notional,
                    "pnl": net, "fees": fee, "slip": slip, "locate": loc_own, "r": r_ref, "reason": tr["exit_reason"],
                })
            # Locates del dia por ticker (sobre el mayor corto), fijos o sorteados.
            if sizing != "as_saved":
                if ex["locates"] == "fixed" and ex["locates_cost"] > 0:
                    loc_i = sum(math.ceil(sz / 100.0) * ex["locates_cost"] for sz in shorts_max.values())
                elif ex["locates"] == "random":
                    for tk, sz in shorts_max.items():
                        precio = lr.precio_locate(shorts_ref.get(tk, 0.0), ex["locates_min"], ex["locates_max"], ex["locates_seed"], tk, d)["precio"]
                        loc_prices_drawn.append(precio)
                        loc_i += math.ceil(sz / 100.0) * precio
                pnl_i -= loc_i
            # (en as_saved los locates ya van dentro del neto de cada trade)
            tot_loc += loc_i
            tot[i]["locates"] += loc_i
            tot[i]["pnl_net"] += pnl_i
            per_pnl[i].append(pnl_i)
            per_trades[i].append(n_i)
            per_locates[i].append(loc_i)
            day_total += pnl_i
        day_total -= expense
        tot_exp += expense
        equity += day_total
        if equity < 0:
            day_total -= equity
            equity = 0.0
        equity_curve.append(equity)
        daily_pnl.append(day_total)
        daily_ret.append(day_total / equity_open if equity_open > 0 else 0.0)

    # ── 3. Exposicion: barrido cronologico AL MINUTO de todos los trades ──
    # (con tope opcional: se aplica sobre el tamano ya decidido; un trade que
    # no cabe se marca y despues se descuenta de las series)
    accepted.sort(key=lambda a: (a["t0"], a["date"]))
    equity_open_by_day = {d: (capital if k == 0 else equity_curve[k - 1]) for k, d in enumerate(calendar)}
    open_heap: list[tuple[float, float]] = []
    exposure = 0.0
    day_peak: dict[str, float] = {}
    day_peak_n: dict[str, int] = {}
    for a in accepted:
        while open_heap and open_heap[0][0] <= a["t0"]:
            _, freed = heapq.heappop(open_heap)
            exposure -= freed
        if exposure < 1e-9:
            exposure = 0.0
        take = a["notional"]
        cap_day = (equity_open_by_day.get(a["date"], capital) * cap_pct / 100.0) if cap_pct > 0 else cap
        if cap_day > 0 and exposure + take > cap_day + 1e-9:
            free = cap_day - exposure
            if trim and free > 1e-9 and a["notional"] > 0:
                f = free / a["notional"]
                for k in ("size", "notional", "pnl", "fees", "slip"):
                    a[k] *= f
                a["trimmed"] = True
                take = free
            else:
                a["skipped"] = True
                continue
        heapq.heappush(open_heap, (a["t1"], take))
        exposure += take
        if exposure > day_peak.get(a["date"], 0.0):
            day_peak[a["date"]] = exposure
        if len(open_heap) > day_peak_n.get(a["date"], 0):
            day_peak_n[a["date"]] = len(open_heap)
    skipped = sum(1 for a in accepted if a.get("skipped"))
    trimmed = sum(1 for a in accepted if a.get("trimmed"))
    if skipped or trimmed:
        # Recomponer las series sin los saltados y con los recortados (los
        # locates del dia se mantienen: el tope es un extra, no se afina).
        idx_day = {d: k for k, d in enumerate(calendar)}
        per_pnl = [[-per_locates[i][k] for k in range(len(calendar))] for i in range(n)]
        per_trades = [[0] * len(calendar) for _ in range(n)]
        for i, st in enumerate(tot):
            st.update({"pnl_net": -sum(per_locates[i]), "gross": 0.0, "n_trades": 0, "wins": 0, "fees": 0.0,
                       "slippage": 0.0, "gross_win": 0.0, "gross_loss": 0.0, "notional": 0.0})
        tot_fees = tot_slip = 0.0
        trade_rows = []
        for a in accepted:
            if a.get("skipped"):
                continue
            i, k = a["si"], idx_day[a["date"]]
            per_pnl[i][k] += a["pnl"]
            per_trades[i][k] += 1
            st = tot[i]
            st["n_trades"] += 1
            st["pnl_net"] += a["pnl"]
            st["gross"] += a["pnl"] + a["fees"] + a["slip"]
            st["fees"] += a["fees"]
            st["slippage"] += a["slip"]
            st["notional"] += a["notional"]
            if a["pnl"] > 0:
                st["wins"] += 1
                st["gross_win"] += a["pnl"]
            elif a["pnl"] < 0:
                st["gross_loss"] += -a["pnl"]
            tot_fees += a["fees"]
            tot_slip += a["slip"]
            trade_rows.append((a["date"], a["entry"], i, a["r"], a["pnl"]))
        equity = capital
        equity_curve, daily_pnl, daily_ret = [], [], []
        months_seen = set()
        for k, d in enumerate(calendar):
            month = d[:7]
            expense = expenses if (expenses > 0 and month not in months_seen) else 0.0
            months_seen.add(month)
            equity_open = equity
            day_total = sum(per_pnl[i][k] for i in range(n)) - expense
            equity += day_total
            equity_curve.append(equity)
            daily_pnl.append(day_total)
            daily_ret.append(day_total / equity_open if equity_open > 0 else 0.0)
        accepted = [a for a in accepted if not a.get("skipped")]

    # ── 4. Metricas ─────────────────────────────────────────────────────
    metrics = ple.compute_stats(calendar, equity_curve, daily_ret, trade_rows, capital)
    var_out = ple.var_stats(daily_ret)
    per_arr = [np.asarray(x, dtype=float) for x in per_pnl]
    correlation = ple.correlation_stats([r.get("run_id") for r in runs], calendar, per_arr, spans)

    per_strategy = []
    for i, run in enumerate(runs):
        s0, s1 = spans[i]
        alive = [(s0 <= d <= s1) if s0 and s1 else False for d in calendar]
        cal_i = [d for d, a in zip(calendar, alive) if a]
        pnl_i = [v for v, a in zip(per_pnl[i], alive) if a]
        eq_i: list[float] = []
        ret_i: list[float] = []
        acc = capital
        for v in pnl_i:
            ret_i.append(v / acc if acc > 0 else 0.0)
            acc += v
            eq_i.append(acc)
        rows_i = [r for r in trade_rows if r[2] == i]
        m_i = ple.compute_stats(cal_i, eq_i, ret_i, rows_i, capital) if cal_i else None
        st = tot[i]
        per_strategy.append({
            "strategy_id": run.get("strategy_id"),
            "run_id": run.get("run_id"),
            "name": run.get("name"),
            "alive_from": s0 or None,
            "alive_to": s1 or None,
            "conditions": run_conditions(run.get("backtest_params") or {}),
            "exec": execs[i],
            "capital_base": capital,
            "pnl_daily": [ple._r6(x) for x in per_pnl[i]],
            "trades_daily": per_trades[i],
            "locates_daily": [ple._r6(x) for x in per_locates[i]],
            "expenses_daily": [0.0] * len(calendar),
            "metrics": m_i,
            "totals": {
                "pnl_net": ple._r6(st["pnl_net"]),
                "gross": ple._r6(st["gross"]),
                "n_trades": st["n_trades"],
                "win_rate": ple._r6(100.0 * st["wins"] / st["n_trades"]) if st["n_trades"] else 0.0,
                "profit_factor": ple._r6(st["gross_win"] / st["gross_loss"]) if st["gross_loss"] > 0 else 0.0,
                "fees": ple._r6(st["fees"]),
                "slippage": ple._r6(st["slippage"]),
                "locates": ple._r6(st["locates"]),
                "expenses": 0.0,
                "avg_notional": ple._r6(st["notional"] / st["n_trades"]) if st["n_trades"] else 0.0,
                "sin_stop": sin_stop[i],
                "stop_aprox": stop_aprox_n[i],
            },
            "cap_report": {
                "taken": st["n_trades"],
                "skipped": sum(1 for a in accepted if a["si"] == i and a.get("skipped")),
                "trimmed": sum(1 for a in accepted if a["si"] == i and a.get("trimmed")),
                "unsized": unsized[i],
            },
        })

    trade_rows.sort(key=lambda r: (r[0], r[1]))
    accepted.sort(key=lambda a: (a["date"], a["entry"]))
    trades_out = {
        "date": [a["date"] for a in accepted],
        "si": [a["si"] for a in accepted],
        "ticker": [a["ticker"] for a in accepted],
        "dir": [a["dir"] for a in accepted],
        "entry": [a["entry"] for a in accepted],
        "exit": [a["exit"] for a in accepted],
        "entry_px": [round(a["entry_px"], 4) for a in accepted],
        "exit_px": [round(a["exit_px"], 4) for a in accepted],
        "size": [round(a["size"], 2) for a in accepted],
        "notional": [round(a["notional"], 2) for a in accepted],
        "pnl": [round(a["pnl"], 2) for a in accepted],
        # Comisiones + slippage del trade (los dos costes que se fijan aqui).
        "fees": [round(a["fees"] + a["slip"], 2) for a in accepted],
        "locate": [round(a["locate"], 2) for a in accepted],
        "r": [round(a["r"], 2) for a in accepted],
        "reason": [a["reason"] for a in accepted],
    }

    return {
        "config": {
            "capital": capital, "monthly_expenses": expenses, "max_exposure_usd": cap, "max_exposure_pct": cap_pct,
            "cap_mode": "trim" if trim else "skip", "start_date": d_from, "end_date": d_to,
            "default_exec": default_exec,
            "sizing": "exec", "notional_usd": 0.0, "per_strategy_usd": {},
        },
        "calendar": calendar,
        "equity": [ple._r6(x) for x in equity_curve],
        "daily_pnl": [ple._r6(x) for x in daily_pnl],
        "ruined": ruined,
        "exposure": {
            "peak_daily": [ple._r6(day_peak.get(d, 0.0)) for d in calendar],
            "max_open_daily": [int(day_peak_n.get(d, 0)) for d in calendar],
            "max_usd": ple._r6(max(day_peak.values()) if day_peak else 0.0),
            "cap_usd": cap,
        },
        "cap_report": {"taken": len(accepted), "skipped": skipped, "trimmed": trimmed, "unsized": sum(unsized)},
        "metrics": metrics,
        "costs": {"fees": ple._r6(tot_fees), "slippage": ple._r6(tot_slip), "locates": ple._r6(tot_loc), "expenses": ple._r6(tot_exp)},
        "locates_random": lr.resumen(loc_prices_drawn) if loc_prices_drawn else None,
        "var": var_out,
        "correlation": correlation,
        "kelly": None,
        "per_strategy": per_strategy,
        "trades_seq": {
            "dates": [r[0] for r in trade_rows],
            "strategy_idx": [r[2] for r in trade_rows],
            "pnl_net": [ple._r6(r[4]) for r in trade_rows],
        },
        "trades": trades_out,
    }
