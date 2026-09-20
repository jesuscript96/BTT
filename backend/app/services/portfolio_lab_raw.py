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

«SOLO UNA ESTRATEGIA ABIERTA A LA VEZ POR ACCION» (`one_per_ticker`, Jaume,
15-sep-2026): en cada ticker entra la primera estrategia que da senal y,
mientras su posicion este abierta, ninguna otra entra en ese ticker; cuando
sale (stop, take profit, lo que sea) vuelve a entrar la primera que de senal.
Se resuelve ANTES de dimensionar, por ticker y al minuto, con la hora de
entrada y de salida guardadas; a igual minuto manda el orden de la lista
(la estrategia mas arriba). Limite honesto: las senales que una estrategia
BLOQUEADA habria tenido despues, mientras en su propio backtest estaba dentro,
no existen en los trades guardados; el resultado es, si acaso, conservador.

La R de cada trade se define por su stop: neto / (|entrada - stop| * acciones).
Es la misma en todas las estrategias y modos; sin stop guardado, 0.

16-sep-2026 (Jaume): LOCATES DEL PORTFOLIO y ESCALADO.
  - Locates: la cuenta es una y el broker es uno. Con `cfg["locates"]` el
    modelo (fijo / aleatorio) vale para todas y, si `shared`, se alquila UNA
    vez por ticker-dia lo que la cuenta necesita: el maximo de acciones en
    corto A LA VEZ sumando estrategias, al minuto. La que cubre libera; la
    siguiente que cabe en lo alquilado va gratis (la PM paga, la RTH no).
    Paga la que provoca el paquete de mas. Puerta por EV opcional: la misma
    cuenta que `locates_gate` (EV en sombra de SU estrategia vs fade necesario
    de los paquetes DE MAS respecto a lo alquilado por CUALQUIERA hoy). Banda:
    N semillas sobre los mismos paquetes, sin volver a simular.
  - Tamano por SETUP (`cfg["setup"]`, 20-sep): el tamano del paso 1 de cada
    trade se multiplica por la Kelly relativa de su setup (EV/sigma^2 del
    tramo de precio de entrada, estimada walk-forward por anos con todo lo
    anterior). El nivel de la cuenta lo siguen poniendo los % del paso 1: la
    tabla mueve tamano de los setups flojos a los buenos con el mismo
    nocional medio. Ver `setup_sizing`.
"""
from __future__ import annotations

import heapq
import math
import threading
from datetime import datetime, timedelta
from typing import Any, Optional

import numpy as np

from app.services import locates_gate as lg
from app.services import locates_random as lr
from app.services import portfolio_lab_engine as ple
from app.services import setup_sizing as ss
from app.services import portfolio_lab_scaling as pls
from app.services import robustness_service as rs
from app.services.portfolio_sim import tope_hibrido as _tope_hibrido

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
                # Precio medio de salida (todas las piernas) para el EV en
                # sombra: `executions` no viaja en el registro recortado.
                slim["exit_vwap"] = lg.precio_salida_medio(t)
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


def _r_neta(tr: dict, ex: dict, locate_ps: float = 0.0) -> float:
    """R neta de un trade preparado con los costes de su fila, por accion:
    no depende del tamano. En la UNIDAD de la estrategia (19-sep): si se
    dimensiona por capital, R = neto / valor de la posicion por accion (el
    retorno sobre lo metido); si por stop, neto / riesgo por accion. Sin stop
    ni riesgo guardado (por stop), 0. `locate_ps`: alquiler esperado por
    accion (solo cortos), para que Kelly no ignore lo que cobra la cuenta."""
    if ex["fee_type"] == "PERCENT":
        fee_ps = (ex["fees"] / 100.0) * (tr["entry"] + tr["exit"])
    else:
        fee_ps = ex["fees"] * 2.0
    slip_ps = (ex["slippage_pct"] / 100.0) * (tr["entry"] + tr["exit"])
    net_ps = tr["gross_ps"] - fee_ps - slip_ps
    if locate_ps > 0 and str(tr.get("direction") or "").startswith("S"):
        net_ps -= locate_ps
    if ex["sizing"] == "capital":
        base_ps = tr["init_price"] / tr["pyr"] if tr["pyr"] > 0 else tr["init_price"]
        return net_ps / base_ps if base_ps > 0 else 0.0
    if tr["stop_dist"] > 0:
        risk_ps = tr["stop_dist"] / tr["pyr"] if tr["pyr"] > 0 else tr["stop_dist"]
    elif tr["risk_orig"] > 0 and tr["size_saved"] > 0:
        risk_ps = tr["risk_orig"] / tr["size_saved"]
    else:
        return 0.0
    return net_ps / risk_ps if risk_ps > 0 else 0.0


# ── Locates del portfolio (una cuenta, un broker) ───────────────────────

LOCATES_DEFAULT: dict[str, Any] = {
    "mode": "none",         # none | fixed | random
    "cost": 0.0,            # $ por paquete de 100 (fixed)
    "min": 1.0,             # random: banda de precios del paquete
    "max": 10.0,
    "seed": 1,
    "shared": True,         # True: UN alquiler por ticker-dia para toda la cuenta
    "gate": None,           # None | {ventana, por, ev_defecto_pct, min_trades}
    "band_seeds": 0,        # >0: banda de N semillas (solo random)
}


def _locates_cfg(raw: Optional[dict]) -> Optional[dict]:
    """None = no hay bloque de locates del portfolio (cada estrategia cobra los
    suyos, como antes del 16-sep). Con bloque, manda sobre las filas."""
    if not raw:
        return None
    cfg = dict(LOCATES_DEFAULT)
    for k, v in raw.items():
        if k in cfg:
            cfg[k] = v
    cfg["mode"] = str(cfg["mode"] or "none")
    for k in ("cost", "min", "max"):
        cfg[k] = _f(cfg[k])
    cfg["seed"] = int(_f(cfg["seed"]))
    cfg["shared"] = bool(cfg["shared"])
    cfg["band_seeds"] = max(0, min(int(_f(cfg["band_seeds"])), 500))
    g = cfg.get("gate")
    if g:
        cfg["gate"] = {
            # mode "ev": EV rodante de la estrategia vs fade (EV por defecto
            # hasta que hay historia; ventana 0 = todo el historico). mode
            # "ev_fixed": SIEMPRE se compara ev_fixed_pct con el fade (Jaume,
            # 17-sep: el EV medido en IS para ver que tal va en OOS). Es lo
            # mismo que «no entrar si el fade > EV fijo».
            "mode": "ev_fixed" if str(g.get("mode") or "ev") in ("ev_fixed", "fade") else "ev",
            # Que medida se enfrenta al fade (17-sep): ev | mfe | fade.
            "metric": lg.normaliza_metrica(g.get("metric")),
            "ev_fixed_pct": _f(g.get("ev_fixed_pct", g.get("fade_max_pct")), 3.0),
            # EV por tramo de precio de entrada (17-sep); un tramo sin EV cae al completo.
            "ev_ranges": lg.rangos_ev_normalizados(g.get("ev_ranges")),
            "ventana": max(0, int(_f(g.get("ventana"), 30))),
            "por": "dias" if str(g.get("por") or "trades") == "dias" else "trades",
            "ev_defecto_pct": _f(g.get("ev_defecto_pct"), 2.0),
            "min_trades": max(1, int(_f(g.get("min_trades"), 10))),
        }
    else:
        cfg["gate"] = None
    if cfg["mode"] == "fixed" and cfg["cost"] <= 0:
        cfg["mode"] = "none"
    return cfg


def _sombra_de(run: dict, metrica: str = "ev") -> lg.ConfigPuerta:
    """EV en sombra de UNA estrategia: sus cortos guardados (todos, sin
    recortar por fechas: es su historia), cerrados antes del instante que se
    decide. Movimiento = `locates_gate.movimiento_pct` (el camino del precio
    desde la entrada hasta el precio medio de salida), la MISMA definicion
    que el backtester."""
    cierres: list[int] = []
    moves: list[float] = []
    for t in run.get("trades") or []:
        if str(t.get("direction") or "").lower().startswith("l"):
            continue
        mv = lg.metrica_trade(t, metrica)
        t1 = _ts(t.get("exit_time"))
        if mv is None or t1 is None:
            continue
        cierres.append(int(t1 * 1_000_000_000))
        moves.append(mv)
    if not cierres:
        return lg.ConfigPuerta(metrica=lg.normaliza_metrica(metrica))
    orden = np.argsort(np.asarray(cierres, dtype=np.int64), kind="stable")
    return lg.ConfigPuerta(
        metrica=lg.normaliza_metrica(metrica),
        sombra_cierre_ns=np.asarray(cierres, dtype=np.int64)[orden],
        sombra_move_pct=np.asarray(moves, dtype=np.float64)[orden],
    )


def _banda_locates(
    calendar: list[str],
    pnl_pre: list[float],
    loc_days: list[dict],
    capital: float,
    lo: float,
    hi: float,
    n_seeds: int,
    seed_actual: int,
) -> Optional[dict]:
    """Banda de N semillas sobre los MISMOS paquetes alquilados: solo cambia el
    precio sorteado de cada ticker-dia (como `locates_banda` del backtester:
    sin volver a simular los trades)."""
    if n_seeds <= 0 or not loc_days:
        return None
    idx = {d: k for k, d in enumerate(calendar)}
    pre = np.asarray(pnl_pre, dtype=float)
    finales: list[float] = []
    dds: list[float] = []
    costes: list[float] = []
    curvas: list[np.ndarray] = []
    for s in range(1, n_seeds + 1):
        coste = np.zeros(len(calendar))
        for ld in loc_days:
            k = idx.get(ld["date"])
            if k is None:
                continue
            coste[k] += ld["packages"] * lr.precio_locate(ld["ref"], lo, hi, s, ld["ticker"], ld["date"])["precio"]
        curva = capital + np.cumsum(pre - coste)
        peak = np.maximum(np.maximum.accumulate(curva), capital)
        dd = float(((curva - peak) / peak).min() * 100.0) if len(curva) else 0.0
        finales.append(float(curva[-1]))
        dds.append(dd)
        costes.append(float(coste.sum()))
        curvas.append(curva)
    M = np.vstack(curvas)
    q = lambda xs, p: float(np.percentile(np.asarray(xs), p))
    return {
        "seeds": n_seeds,
        "seed_actual": seed_actual,
        "final": {"p05": q(finales, 5), "p25": q(finales, 25), "p50": q(finales, 50), "p75": q(finales, 75), "p95": q(finales, 95)},
        "max_dd_pct": {"p05": q(dds, 5), "p50": q(dds, 50), "p95": q(dds, 95)},
        "cost": {"p05": q(costes, 5), "p50": q(costes, 50), "p95": q(costes, 95)},
        "bands": {
            "p05": [ple._r6(x) for x in np.percentile(M, 5, axis=0)],
            "p50": [ple._r6(x) for x in np.percentile(M, 50, axis=0)],
            "p95": [ple._r6(x) for x in np.percentile(M, 95, axis=0)],
        },
    }


def kelly_clasica(rs) -> Optional[float]:
    """La Kelly «de toda la vida» por operacion: f = p - q/b, con p = % de
    operaciones ganadoras y b = ganancia media / perdida media (en la misma
    unidad que las R). None sin ganadoras o sin perdedoras."""
    xs = [float(x) for x in rs if x is not None and np.isfinite(x)]
    g = [x for x in xs if x > 0]
    p = [x for x in xs if x < 0]
    if not g or not p or len(xs) < pls.MIN_OBS:
        return None
    pw = len(g) / len(xs)
    b = (sum(g) / len(g)) / (abs(sum(p)) / len(p))
    if b <= 0:
        return None
    return pw - (1.0 - pw) / b


def _kelly_exacta(port_r: np.ndarray) -> Optional[float]:
    """La f que maximiza la media de log(1 + f * R) sobre los dias de la
    ventana: la Kelly de verdad para la distribucion EMPIRICA. mu/sigma^2 (la
    de F2) es su aproximacion de segundo orden y, con colas gordas y varios
    trades al dia, pide mas de la cuenta. La busqueda es ternaria (el
    log-crecimiento es concavo en f) y no pasa de la f que arruinaria con el
    peor dia visto. None = sin muestra; 0 = sin edge (no apostar)."""
    r = np.asarray(port_r, dtype=float)
    if len(r) < pls.MIN_OBS or not np.any(r != 0):
        return None
    rmin = float(r.min())
    hi = (0.999 / -rmin) if rmin < 0 else 5.0
    lo = 0.0
    for _ in range(80):
        m1 = lo + (hi - lo) / 3.0
        m2 = hi - (hi - lo) / 3.0
        if float(np.mean(np.log1p(m1 * r))) < float(np.mean(np.log1p(m2 * r))):
            lo = m1
        else:
            hi = m2
    f = (lo + hi) / 2.0
    if float(np.mean(np.log1p(f * r))) <= 0.0:
        return 0.0
    return float(f)


def kelly_cuenta_real(rows: list[dict], risk_mode: str, risk_value: float, capital_inicial: float,
                      kelly_mult: float, cap_pct: float, cap_strategy_pct: float, lookback_days: int,
                      estrategias: list[dict], capital_siguiente: float, kelly_base: str = "exacta") -> dict:
    """KELLY SOBRE LA CUENTA REAL (19-sep, Jaume): «volcar mi operativa real,
    calcular Kelly ahi y que me diga cuanto apostar el siguiente periodo, y
    repartirlo entre las estrategias segun las Kellys del backtest».

    `rows`: [{"date", "pnl"}] con el PnL NETO de cada dia real (varias filas
    del mismo dia se suman). El riesgo por trade que se uso ese dia:
      - risk_mode "usd": `risk_value` $ fijos por trade -> R_dia = pnl / riesgo;
      - risk_mode "pct": `risk_value` % del equity con el que empezo el dia
        (capital_inicial + PnL acumulado) -> R_dia = pnl / (pct x equity).
    Kelly exacta sobre la R diaria de la ventana (lookback_days; 0 = toda la
    historia), x kelly_mult, topada por cap_pct = TOTAL por trade del siguiente
    periodo. El reparto entre estrategias es el del modo global del escalado:
    proporcional a la Kelly propia de cada una en el backtest (`estrategias`:
    [{"name", "kelly_pct"}]); tope por estrategia primero, tope de la suma
    despues (sin redistribuir).
    """
    por_dia: dict[str, float] = {}
    r_pos_dia: dict[str, float] = {}          # R «por posicion»: pnl / valor de la posicion, sumada por dia
    ops: list[tuple[str, float, float]] = []  # (dia, pnl, notional) de cada operacion
    for r in rows:
        d = str(r.get("date") or "")[:10]
        if len(d) != 10:
            continue
        pnl = _f(r.get("pnl"))
        notional = _f(r.get("notional"))
        por_dia[d] = por_dia.get(d, 0.0) + pnl
        if notional > 0:
            r_pos_dia[d] = r_pos_dia.get(d, 0.0) + pnl / notional
        ops.append((d, pnl, notional))
    dias = sorted(por_dia)
    if not dias:
        raise ValueError("No hay filas con fecha y PnL")
    modo = str(risk_mode) if str(risk_mode) in ("usd", "pct", "notional") else "usd"
    if modo == "notional" and not any(n > 0 for _, _, n in ops):
        raise ValueError("Para la R por posicion hacen falta operaciones con valor de posicion (el CSV de DAS lo trae)")
    if modo != "notional" and risk_value <= 0:
        raise ValueError("El riesgo por trade tiene que ser mayor que cero")
    equity = float(capital_inicial)
    r_por_dia: list[tuple[str, float, float]] = []
    _riesgo_de_dia: dict[str, float] = {}
    for d in dias:
        pnl = por_dia[d]
        if modo != "notional":
            _riesgo_de_dia[d] = float(risk_value) if modo == "usd" else equity * float(risk_value) / 100.0
        if modo == "notional":
            # La R de cada operacion es su retorno sobre la posicion; la del dia,
            # la suma (misma unidad que el crudo cuando la estrategia va por capital).
            r_por_dia.append((d, r_pos_dia.get(d, 0.0), 0.0))
        else:
            riesgo = float(risk_value) if modo == "usd" else equity * float(risk_value) / 100.0
            r_por_dia.append((d, pnl / riesgo if riesgo > 0 else 0.0, riesgo))
        equity += pnl
    # Kelly CLASICA por operacion (p - q/b), como referencia: p = % de
    # operaciones ganadoras, b = ganancia media / perdida media, en la misma
    # unidad que la R (por posicion si hay notional; si no, en $).
    _rs = [(pnl / n if (modo == "notional" and n > 0) else pnl) for _, pnl, n in ops]
    _g = [x for x in _rs if x > 0]
    _p = [x for x in _rs if x < 0]
    clasica = None
    if _g and _p:
        p_win = len(_g) / len(_rs)
        b = (sum(_g) / len(_g)) / (abs(sum(_p)) / len(_p))
        clasica = p_win - (1.0 - p_win) / b if b > 0 else None
    ops_stats = {"n": len(ops), "ganadoras": len(_g), "perdedoras": len(_p), "win_rate": ple._r6(100.0 * len(_g) / len(_rs)) if _rs else 0.0,
                 "ganancia_media": ple._r6(sum(_g) / len(_g)) if _g else 0.0, "perdida_media": ple._r6(abs(sum(_p)) / len(_p)) if _p else 0.0,
                 "kelly_clasica_pct": ple._r6(clasica * 100.0) if clasica is not None else None}
    if lookback_days and lookback_days > 0:
        cut = (ple._parse_day(dias[-1]) - timedelta(days=int(lookback_days))).isoformat()
        ventana = [x for x in r_por_dia if x[0] >= cut]
    else:
        ventana = r_por_dia
    serie = np.asarray([x[1] for x in ventana], dtype=float)
    kg_exacta = _kelly_exacta(serie) if len(serie) else None
    kq = pls._kelly_fraction(serie) if len(serie) >= pls.MIN_OBS else None
    # Kelly clasica sobre las operaciones de la ventana (p - q/b).
    _desde = ventana[0][0] if ventana else None
    _rs_ops = [(pnl / n if (modo == "notional" and n > 0) else (pnl / _riesgo_de_dia.get(d, 1.0)))
               for d, pnl, n in ops if (_desde is None or d >= _desde)]
    kg_clasica = kelly_clasica(_rs_ops)
    kg = kg_clasica if str(kelly_base) == "clasica" else kg_exacta
    if kg is None:
        total = None
        nota = f"sin muestra: hacen falta {pls.MIN_OBS} dias con operaciones en la ventana (hay {int(np.count_nonzero(serie))})"
    elif kg <= 0:
        total = 0.0
        nota = "sin edge en la ventana: Kelly manda no apostar"
    else:
        total = kg * float(kelly_mult)
        nota = None
    # Reparto por las Kellys del backtest.
    ks = [max(0.0, _f(e.get("kelly_pct"))) for e in estrategias]
    suma_k = sum(ks)
    shares = [k / suma_k if suma_k > 0 else (1.0 / len(ks) if ks else 0.0) for k in ks]
    cap_i = float(cap_strategy_pct or 0.0)
    cap = float(cap_pct or 0.0)
    pedido = [(total or 0.0) * 100.0 * sh for sh in shares]
    aplicado = [min(v, cap_i) if cap_i > 0 else v for v in pedido]
    capped_i = any(a < p - 1e-12 for a, p in zip(aplicado, pedido))
    suma_apl = sum(aplicado)
    capped = False
    if cap > 0 and suma_apl > cap + 1e-12:
        aplicado = [a * cap / suma_apl for a in aplicado]
        capped = True
        suma_apl = cap
    if not estrategias:
        # Sin el paso 4 (nada que repartir) el TOTAL sale igual: Kelly x
        # fraccion, topado (20-sep: salia 0 y la UI decia «sale el total»).
        suma_apl = (total or 0.0) * 100.0
        if cap > 0 and suma_apl > cap + 1e-12:
            suma_apl = cap
            capped = True
    peor = float(serie.min()) if len(serie) else 0.0
    return {
        "dias": len(r_por_dia), "dias_ventana": len(ventana), "dias_con_operaciones": int(np.count_nonzero(serie)),
        "desde": ventana[0][0] if ventana else None, "hasta": ventana[-1][0] if ventana else None,
        "equity_final": ple._r6(equity), "risk_mode": modo, "risk_value": float(risk_value),
        "pnl_total": ple._r6(sum(por_dia.values())), "ops": ops_stats,
        "r_media_dia": ple._r6(float(serie.mean())) if len(serie) else 0.0,
        "r_peor_dia": ple._r6(peor), "r_mejor_dia": ple._r6(float(serie.max())) if len(serie) else 0.0,
        "r_total_ventana": ple._r6(float(serie.sum())) if len(serie) else 0.0,
        "kelly_raw_pct": ple._r6(kg * 100.0) if kg is not None else None,
        "kelly_base": "clasica" if str(kelly_base) == "clasica" else "exacta",
        "kelly_exacta_pct": ple._r6(kg_exacta * 100.0) if kg_exacta is not None else None,
        "kelly_clasica_pct": ple._r6(kg_clasica * 100.0) if kg_clasica is not None else None,
        "kelly_quad_pct": ple._r6(kq * 100.0) if kq is not None else None,
        "kelly_mult": float(kelly_mult),
        "total_pedido_pct": ple._r6((total or 0.0) * 100.0) if total is not None else None,
        "cap_pct": cap, "cap_strategy_pct": cap_i, "capped": capped, "capped_strategy": capped_i,
        "total_pct": ple._r6(suma_apl) if total is not None else None,
        "total_usd": ple._r6(capital_siguiente * suma_apl / 100.0) if total is not None else None,
        "capital_siguiente": float(capital_siguiente),
        "nota": nota,
        "per_strategy": [
            {"name": e.get("name"), "kelly_pct": ple._r6(_f(e.get("kelly_pct"))), "share": ple._r6(sh),
             "risk_pct": ple._r6(a) if total is not None else None,
             "risk_usd": ple._r6(capital_siguiente * a / 100.0) if total is not None else None,
             "basis": e.get("basis") or "risk"}
            for e, sh, a in zip(estrategias, shares, aplicado)
        ],
        "serie": [{"date": d, "r": ple._r6(r), "pnl": ple._r6(por_dia[d]), "riesgo": ple._r6(rg)} for d, r, rg in r_por_dia],
    }


def _analisis_locates(accepted: list[dict], n: int, names: list[str], loc_days: list[dict], loc_cfg: Optional[dict]) -> Optional[dict]:
    """Hasta que precio compensan los locates (17-sep, pedido de Jaume).

    - Precio de equilibrio: PnL de los cortos ANTES de locates / paquetes
      alquilados. A ese precio por paquete el portfolio se queda a cero. El
      neto es lineal en el precio, asi que la curva neto(P) sale de ahi.
    - Tramos de fade: el neto tras el locate de cada corto segun su fade
      necesario (% del precio que hay que ganar solo para pagar SUS paquetes
      de mas). Ensena desde que fade deja de compensar.
    - Regla F: «no entrar si el fade necesario > F», estimada sobre los cortos
      aceptados (aprox.: no recalcula el alquiler compartido al quitar cortos).
    Solo con paquetes contados (bloque de locates con alquiler compartido, o
    por estrategia con precio); sin locates no hay fade que mirar.
    """
    shorts = [a for a in accepted if a["dir"] == "S"]
    if not shorts or not loc_days:
        return None
    paquetes = int(sum(ld["packages"] for ld in loc_days))
    if paquetes <= 0:
        return None
    pnl_pre = float(sum(a["pnl"] for a in shorts))          # neto de comisiones y slippage, antes de locates
    pnl_total_pre = float(sum(a["pnl"] for a in accepted))
    equilibrio = pnl_pre / paquetes
    con_precio = bool(loc_cfg and loc_cfg["mode"] != "none")
    por_estrategia = []
    for i in range(n):
        mios = [a for a in shorts if a["si"] == i]
        pk = int(sum(a.get("packages", 0) for a in mios))
        pp = float(sum(a["pnl"] for a in mios))
        por_estrategia.append({
            "idx": i, "name": names[i], "shorts": len(mios), "packages": pk,
            "pnl_pre_locates": ple._r6(pp),
            "breakeven_price": ple._r6(pp / pk) if pk > 0 else None,
            "paid": ple._r6(float(sum(a["locate"] for a in mios))),
        })
    grid = [0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 15.0, 20.0]
    curve = [{"price": P, "net_shorts": ple._r6(pnl_pre - P * paquetes), "net_total": ple._r6(pnl_total_pre - P * paquetes)} for P in grid]
    out: dict[str, Any] = {
        "packages": paquetes, "shorts": len(shorts),
        "pnl_shorts_pre_locates": ple._r6(pnl_pre),
        "pnl_total_pre_locates": ple._r6(pnl_total_pre),
        "breakeven_price": ple._r6(equilibrio),
        "paid": ple._r6(float(sum(a["locate"] for a in shorts))),
        "avg_price_paid": ple._r6(float(sum(a["locate"] for a in shorts)) / paquetes),
        "per_strategy": por_estrategia,
        "curve": curve,
        "mean_move_pct": ple._r6(float(np.mean([a["pnl"] / a["notional"] * 100.0 for a in shorts if a["notional"] > 0]))),
        "fade_buckets": None, "fade_rule": None,
    }
    if con_precio:
        fades = np.array([a.get("fade_pct", 0.0) for a in shorts], dtype=float)
        pnl = np.array([a["pnl"] for a in shorts], dtype=float)
        loc = np.array([a["locate"] for a in shorts], dtype=float)
        nom = np.array([a["notional"] for a in shorts], dtype=float)
        neto = pnl - loc
        tramos = [(0.0, 0.001), (0.001, 0.5), (0.5, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 3.0), (3.0, 5.0), (5.0, 8.0), (8.0, 1e9)]
        buckets = []
        for lo, hi in tramos:
            m = (fades >= lo) & (fades < hi)
            if not m.any():
                continue
            buckets.append({
                "lo": lo, "hi": hi if hi < 1e9 else None, "n": int(m.sum()),
                "move_pct": ple._r6(float(np.mean(pnl[m] / np.where(nom[m] > 0, nom[m], 1.0) * 100.0))),
                "net_mean": ple._r6(float(np.mean(neto[m]))),
                "net_total": ple._r6(float(np.sum(neto[m]))),
                "win_pct": ple._r6(float(np.mean(pnl[m] > 0) * 100.0)),
            })
        out["fade_buckets"] = buckets
        regla = []
        for F in (1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 8.0):
            m = fades < F      # entra si EV fijo (F) > fade
            regla.append({"fade_max_pct": F, "taken": int(m.sum()), "net_est": ple._r6(float(neto[m].sum()))})
        out["fade_rule"] = regla
        out["net_now"] = ple._r6(float(neto.sum()))
        best = max(regla, key=lambda r: r["net_est"])
        out["best_fade_max_pct"] = best["fade_max_pct"] if best["net_est"] > float(neto.sum()) else None
    return out


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
      one_per_ticker     solo una estrategia abierta a la vez por accion
      locates            bloque del portfolio (ver LOCATES_DEFAULT); sin el,
                         cada fila cobra los suyos como antes
      setup              tamano por setup (ver setup_sizing.SETUP_DEFAULT); None = los
                         R de las filas
      max_ticker_pct     tope POR ACCION: lo abierto a la vez en un mismo
                         ticker sumando estrategias, en % del equity del dia
                         (0 = sin tope); se salta o recorta segun cap_mode
      ticker_cap_basis   "risk" (perdida al stop de la entrada, lo que
                         dimensiona Kelly) | "notional" | "trade" (el tope
                         es lo que arriesga UN trade de la estrategia que
                         entra: su fraccion de Kelly o su % por trade; el
                         numero no se usa)
      margin             {"enabled", "broker", "capacity_pct"} (ver margen.py):
                         cada entrada exige margen segun precio y lado; la
                         que no cabe en el equity del dia se salta o recorta
                         (mismo cap_mode que el tope de exposicion)
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
    one_per_ticker = bool(cfg.get("one_per_ticker"))
    # Tope POR ACCION (19-sep, Jaume: «si aplicamos Kelly, en un ticker no debe
    # haber mas de dicha exposicion como maximo; me da igual si hay 20 tickers
    # en paralelo»). Sumando estrategias, primero llega primero entra; la que
    # llega con el ticker lleno se salta o se recorta (cap_mode).
    ticker_cap_pct = _f(cfg.get("max_ticker_pct"))
    _tb = str(cfg.get("ticker_cap_basis") or "risk")
    ticker_basis = _tb if _tb in ("risk", "notional", "trade") else "risk"
    ticker_on = ticker_basis == "trade" or ticker_cap_pct > 0
    # Margen y buying power (19-sep): opcional; apagado, nada cambia.
    _mg_raw = cfg.get("margin") or {}
    margin_on = bool(_mg_raw.get("enabled"))
    margin_broker = str(_mg_raw.get("broker") or "sagetrader")
    margin_cap_pct = _f(_mg_raw.get("capacity_pct"), 100.0) or 100.0
    d_from = str(cfg.get("start_date") or "") or None
    d_to = str(cfg.get("end_date") or "") or None
    default_exec = _exec_cfg(cfg.get("default_exec"))
    per_cfg_raw = cfg.get("per_strategy") or {}

    n = len(runs)
    execs: list[dict] = []
    # REGLAS INTRINSECAS de cada estrategia (19-sep, Jaume: «tal cual las
    # indicaciones que marcaba la estrategia»): el techo hibrido (por SL) y el
    # cangrejo modo B (la perdida al stop no pasa de X % de la cuenta) recortan
    # la ENTRADA al re-dimensionar, con el capital del dia, exactamente como
    # hace el motor (`portfolio_sim`); y el tope de caja (no mas nocional que
    # la cuenta). Se leen de los parametros de la corrida y, si faltan, de la
    # definicion de la estrategia guardada con ella. El modo A del cangrejo
    # (apretar el stop) ya esta dentro del stop guardado del trade.
    reglas: list[dict] = []
    for run in runs:
        raw_e = per_cfg_raw.get(str(run.get("strategy_id")))
        ex = _exec_cfg(raw_e) if raw_e else dict(default_exec)
        params = run.get("backtest_params") or {}
        if ex["sizing"] == "auto":
            ex["sizing"] = "risk" if params.get("size_by_sl") else "capital"
        execs.append(ex)
        rm = ((params.get("strategy_definition") or {}).get("risk_management") or {}) if isinstance(params.get("strategy_definition"), dict) else {}
        def _p(k: str):
            v = params.get(k)
            return rm.get(k) if v is None else v
        reglas.append({
            "hybrid": bool(_p("hybrid_stop")) and bool(params.get("size_by_sl")),
            "bs_pct": _f(_p("hybrid_black_swan_pct")),
            "ml_pct": _f(_p("hybrid_max_loss_pct")),
            "cangrejo_b": bool(_p("cangrejo_active")) and _f(_p("cangrejo_max_loss_at_sl_pct")) > 0,
            "cb_pct": _f(_p("cangrejo_max_loss_at_sl_pct")),
        })
    recortes_reglas = [0] * n

    # ── 1. Preparar los trades: deshacer la corrida, dejar la senal por accion ─
    by_day: list[dict[str, list[dict]]] = []
    spans: list[tuple[str, str]] = []
    unsized = [0] * n
    sin_stop = [0] * n
    stop_aprox_n = [0] * n
    blocked = [0] * n
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

    # ── 1b. Solo una estrategia abierta a la vez por accion ──────────────
    # Barrido de TODOS los trades por (hora de entrada, orden en la lista):
    # un trade cuyo ticker tiene una posicion abierta (de la estrategia que
    # sea) hasta un minuto posterior a su entrada se queda fuera. Va antes de
    # dimensionar para que el capital del dia ya no cuente con los bloqueados.
    if one_per_ticker and n > 1:
        cola = sorted(
            ((tr["t0"], i, tr) for i in range(n) for trades_d in by_day[i].values() for tr in trades_d),
            key=lambda x: (x[0], x[1]),
        )
        abierto_hasta: dict[str, float] = {}
        fuera: set[int] = set()
        for t0, i, tr in cola:
            tk = tr["ticker"]
            if abierto_hasta.get(tk, -1.0) > t0:
                fuera.add(id(tr))
                blocked[i] += 1
                continue
            abierto_hasta[tk] = max(tr["t1"], t0)
        if fuera:
            for i in range(n):
                idx = by_day[i]
                for d in list(idx.keys()):
                    idx[d] = [tr for tr in idx[d] if id(tr) not in fuera]
                    if not idx[d]:
                        del idx[d]
            spans = [
                (min(idx.keys()), max(idx.keys())) if idx else ("", "")
                for idx in by_day
            ]

    calendar = sorted({d for idx in by_day for d in idx})
    if not calendar:
        raise ValueError("Ninguna estrategia tiene trades en el rango elegido")

    # ── 1c. Locates del portfolio, puerta por EV y tamano por setup ──────
    loc_cfg = _locates_cfg(cfg.get("locates"))
    setup_cfg = ss.setup_cfg(cfg.get("setup"))
    # Con bloque de locates y alquiler compartido se hace el barrido aunque el
    # modo sea "none" (precio 0): asi se cuentan los paquetes y sale el precio
    # de equilibrio («si pagaras X por paquete...») sin cobrar nada.
    shared = bool(loc_cfg and loc_cfg["shared"])
    gate_cfgs: list[Optional[lg.ConfigPuerta]] = [None] * n
    gate_mode = (loc_cfg["gate"]["mode"] if loc_cfg and loc_cfg["gate"] else None)
    # EV fijo: el corto entra si ev_fijo > fade (el completo, o el del tramo de
    # precio de la entrada si hay rangos).
    fade_max = (loc_cfg["gate"]["ev_fixed_pct"] if loc_cfg and loc_cfg["gate"] else 0.0)
    ev_ranges = (loc_cfg["gate"]["ev_ranges"] if loc_cfg and loc_cfg["gate"] else [])
    if loc_cfg and loc_cfg["gate"] and loc_cfg["mode"] != "none" and gate_mode == "ev_fixed":
        for i in range(n):
            gate_cfgs[i] = lg.ConfigPuerta(modo="fijo", ev_fijo_pct=fade_max, ev_rangos=ev_ranges,
                                           metrica=loc_cfg["gate"].get("metric", "ev"))
    if loc_cfg and loc_cfg["gate"] and loc_cfg["mode"] != "none" and gate_mode == "ev":
        g = loc_cfg["gate"]
        for i, run in enumerate(runs):
            c = _sombra_de(run, g.get("metric", "ev"))
            c.ventana = g["ventana"]
            c.por = g["por"]
            c.ev_defecto_pct = g["ev_defecto_pct"]
            c.min_trades = g["min_trades"]
            gate_cfgs[i] = c

    def loc_of(i: int) -> tuple[str, float, float, float, int]:
        """(modo, $/paquete, min, max, semilla) que cobra la estrategia i: el
        bloque del portfolio si lo hay; si no, lo de su fila (como antes)."""
        if loc_cfg:
            return loc_cfg["mode"], loc_cfg["cost"], loc_cfg["min"], loc_cfg["max"], loc_cfg["seed"]
        ex = execs[i]
        mode = str(ex["locates"])
        if mode == "fixed" and ex["locates_cost"] <= 0:
            mode = "none"
        return mode, ex["locates_cost"], ex["locates_min"], ex["locates_max"], ex["locates_seed"]

    mults: Optional[ss.Multiplicadores] = None
    if setup_cfg:
        # Una muestra por trade: (fecha, precio de entrada, u), con u la R
        # neta por accion en la UNIDAD de la estrategia (retorno sobre la
        # posicion si dimensiona por capital, R si por stop), con los costes de
        # su fila y el locate esperado por accion (fijo/100 o la mediana del
        # sorteo para su precio de referencia).
        muestras: list[list[tuple[str, float, float]]] = [[] for _ in range(n)]
        for i in range(n):
            ex = execs[i]
            mode_l, cost_l, lo_l, hi_l, _seed_l = loc_of(i)
            for d, trades_d in by_day[i].items():
                for tr in trades_d:
                    if mode_l == "fixed":
                        locate_ps = cost_l / 100.0
                    elif mode_l == "random":
                        locate_ps = lr.centro_por_precio(tr["ref_price"], lo_l, hi_l) / 100.0
                    else:
                        locate_ps = 0.0
                    muestras[i].append((d, float(tr["entry"]), _r_neta(tr, ex, locate_ps)))
            muestras[i].sort()
        mults = ss.Multiplicadores(setup_cfg, muestras, calendar)

    # ── 2. Dia a dia: dimensionar con el capital del dia, costes, locates ──
    equity = capital
    months_seen: set[str] = set()
    ruined = False
    equity_curve: list[float] = []
    daily_pnl: list[float] = []
    daily_ret: list[float] = []
    per_pnl: list[list[float]] = [[] for _ in range(n)]
    per_trades: list[list[int]] = [[] for _ in range(n)]
    per_locates: list[list[float]] = [[] for _ in range(n)]   # cobrados aqui (no los ya dentro de as_saved)
    tot = [
        {"pnl_net": 0.0, "gross": 0.0, "n_trades": 0, "wins": 0, "fees": 0.0, "slippage": 0.0,
         "locates": 0.0, "gross_win": 0.0, "gross_loss": 0.0, "notional": 0.0}
        for _ in range(n)
    ]
    tot_fees = tot_slip = tot_loc = tot_exp = 0.0
    trade_rows: list[tuple[str, str, int, float, float]] = []
    accepted: list[dict] = []
    loc_prices_drawn: list[float] = []
    loc_days: list[dict] = []          # ticker-dia alquilados (paquetes, ref, precio): base de la banda
    gate_out = [0] * n                 # cortos que la puerta por EV dejo fuera
    gate_free = [0] * n                # cortos que cabian en lo ya alquilado hoy (gratis)
    setup_n = [0] * n                  # trades con multiplicador de setup distinto de 1

    # ── Estado de los TOPES (exposicion, margen, por accion), que persiste
    # entre dias: una posicion abierta sigue ocupando sitio hasta su salida.
    # Se aplican DENTRO de cada dia, en orden cronologico, ANTES de locates y
    # de acumular (19-sep): lo que no cabe no existe, y no paga nada.
    from app.services.margen import requisito_por_accion as _req_ps
    open_heap: list[tuple[float, float]] = []
    exposure = 0.0
    day_peak: dict[str, float] = {}
    day_peak_n: dict[str, int] = {}
    open_heap_m: list[tuple[float, float]] = []
    usado_m = 0.0
    day_peak_m: dict[str, float] = {}
    open_tk: dict[str, list[tuple[float, float]]] = {}
    used_tk: dict[str, float] = {}
    ticker_sin_stop = 0
    skipped_by_i = [0] * n
    trimmed_by_i = [0] * n
    margin_skipped = margin_trimmed = 0
    ticker_skipped = ticker_trimmed = 0
    equity_open_by_day: dict[str, float] = {}

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

        # a) Tamano y costes de cada trade del dia (sin locates todavia)
        dia: list[dict] = []
        for i in range(n):
            trades_d = by_day[i].get(d)
            if ruined or not trades_d:
                continue
            ex = execs[i]
            sizing = ex["sizing"]
            for tr in trades_d:
                as_saved = False
                m_setup = 1.0
                if sizing == "as_saved":
                    as_saved = True
                    new_size = tr["size_saved"]
                elif sizing == "risk":
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
                if not as_saved and tr["init_price"] > 0 and equity_open > 0:
                    # Techo hibrido, cangrejo B y tope de caja sobre la ENTRADA
                    # (la piramide conserva su proporcion).
                    pyr_f = tr["pyr"] if tr["pyr"] > 0 else 1.0
                    entrada = new_size / pyr_f
                    tope_e = entrada
                    rg = reglas[i]
                    if rg["hybrid"]:
                        t_h = _tope_hibrido(equity_open, rg["bs_pct"], rg["ml_pct"], tr["init_price"])
                        if t_h is not None:
                            tope_e = min(tope_e, t_h)
                    if rg["cangrejo_b"] and tr["stop_dist"] > 0:
                        tope_e = min(tope_e, (rg["cb_pct"] / 100.0) * equity_open / tr["stop_dist"])
                    tope_e = min(tope_e, equity_open / tr["init_price"])
                    if tope_e < entrada - 1e-12:
                        new_size = tope_e * pyr_f
                        recortes_reglas[i] += 1
                if mults is not None and not as_saved:
                    # Tamano por setup: el % del paso 1 x la Kelly relativa
                    # del tramo de precio de este trade (tabla del ano).
                    m_setup = mults.mult(i, float(tr["entry"]), d)
                    if abs(m_setup - 1.0) > 1e-9:
                        setup_n[i] += 1
                    new_size *= m_setup
                    if new_size <= 0:
                        continue
                if as_saved:
                    net = tr["pnl_saved_net"]
                    fee = tr["fees_saved"]
                    slip = 0.0
                    gross = net + fee + tr["locate_saved"]
                    locate = tr["locate_saved"]
                else:
                    gross = tr["gross_ps"] * new_size
                    if ex["fee_type"] == "PERCENT":
                        fee = (ex["fees"] / 100.0) * (tr["entry"] + tr["exit"]) * new_size
                    else:
                        fee = ex["fees"] * new_size * 2.0
                    slip = (ex["slippage_pct"] / 100.0) * (tr["entry"] + tr["exit"]) * new_size
                    net = gross - fee - slip
                    locate = 0.0
                notional = new_size * tr["entry"]
                risk_new = tr["stop_dist"] * (new_size / tr["pyr"] if tr["pyr"] > 0 else new_size)
                r_ref = (net / risk_new) if risk_new > 0 else 0.0
                dia.append({
                    "si": i, "tr": tr, "as_saved": as_saved, "size": new_size, "gross": gross,
                    "fee": fee, "slip": slip, "net": net, "notional": notional, "r": r_ref, "locate": locate,
                    "risk": risk_new,
                    # Lo que dimensiono este trade (base «por trade» del tope
                    # por accion): el riesgo pedido si fue por riesgo/Kelly,
                    # el nocional pedido si fue por capital; tal cual, lo suyo.
                    "budget": (r_usd if sizing == "risk" else
                               (x_usd if sizing == "capital" else (risk_new if risk_new > 0 else notional))),
                    "budget_basis": ("notional" if sizing == "capital" else ("risk" if (sizing == "risk" or (sizing == "as_saved" and risk_new > 0)) else "notional")),
                    "setup_mult": m_setup,
                })
                if mults is not None and not as_saved:
                    mults.registrar(i, m_setup, notional)

        # Estado de los locates del dia (lo usa _puerta_y_alquiler, dentro del
        # bucle de topes).
        loc_by_i = [0.0] * n
        open_short: dict[str, list[tuple[float, float]]] = {}
        rented: dict[str, int] = {}
        price: dict[str, float] = {}
        ref: dict[str, float] = {}
        max_short: dict[tuple[int, str], float] = {}
        price_s: dict[tuple[int, str], float] = {}
        ref_s: dict[tuple[int, str], float] = {}
        if shared:
            mode_sh, cost_sh, lo_sh, hi_sh, seed_sh = loc_of(0)

        def _puerta_y_alquiler(a: dict) -> bool:
            """Decide si el corto pasa la puerta y le cobra sus paquetes DE MAS.
            False = la puerta lo tumba (gate_out): no entra, no ocupa nada."""
            tr = a["tr"]
            if a["as_saved"] or not tr["direction"].startswith("S"):
                return True
            tk = tr["ticker"]
            if shared:
                mode, cost, lo, hi, seed = mode_sh, cost_sh, lo_sh, hi_sh, seed_sh
                lst = open_short.setdefault(tk, [])
                conc = sum(sz for (t1, sz) in lst if t1 > tr["t0"]) + a["size"]
                if tk not in price:
                    if mode == "fixed":
                        price[tk] = cost
                    elif mode == "random":
                        price[tk] = lr.precio_locate(tr["ref_price"], lo, hi, seed, tk, d)["precio"]
                        loc_prices_drawn.append(price[tk])
                    else:
                        price[tk] = 0.0
                    ref[tk] = tr["ref_price"]
                needed = int(math.ceil(conc / 100.0))
                have = rented.get(tk, 0)
                marginal = max(0, needed - have)
                fade = lg.fade_necesario_pct(tr["entry"], a["size"], marginal, price[tk]) if mode != "none" else 0.0
                if mode != "none" and gate_mode == "ev_fixed":
                    ev_f, _origen = lg.ev_fijo_para_precio(fade_max, ev_ranges, tr["entry"])
                    if not ev_f > fade:
                        a["gate_out"] = True
                        gate_out[a["si"]] += 1
                        return False
                else:
                    gc = gate_cfgs[a["si"]]
                    if gc is not None:
                        ev, _n_ev, _dflt = lg.ev_rodante_pct(gc, int(tr["t0"] * 1_000_000_000))
                        if not ev > fade:
                            a["gate_out"] = True
                            gate_out[a["si"]] += 1
                            return False
                if marginal == 0 and have > 0:
                    gate_free[a["si"]] += 1
                rented[tk] = max(have, needed)
                a["locate"] = marginal * price[tk]
                a["packages"] = marginal
                a["fade_pct"] = fade
                loc_by_i[a["si"]] += a["locate"]
                lst.append((tr["t1"], a["size"]))
                return True
            # Por estrategia (como el backtester de cada una): su maximo en
            # corto del dia por ticker; las reentradas reutilizan lo alquilado.
            i = a["si"]
            mode, cost, lo, hi, seed = loc_of(i)
            if mode == "none":
                return True
            key = (i, tk)
            if key not in price_s:
                if mode == "fixed":
                    price_s[key] = cost
                else:
                    price_s[key] = lr.precio_locate(tr["ref_price"], lo, hi, seed, tk, d)["precio"]
                    loc_prices_drawn.append(price_s[key])
                ref_s[key] = tr["ref_price"]
            m = max_short.get(key, 0.0)
            marginal = lg.paquetes_marginales(m, a["size"])
            fade = lg.fade_necesario_pct(tr["entry"], a["size"], marginal, price_s[key])
            gc = gate_cfgs[i]
            if gc is not None:
                # `evaluar` resuelve los dos modos (rodante y fijo, con o sin rangos).
                v = lg.evaluar(gc, int(tr["t0"] * 1_000_000_000), tr["entry"], a["size"], m, price_s[key])
                if not v["entra"]:
                    a["gate_out"] = True
                    gate_out[i] += 1
                    return False
            if marginal == 0 and m > 0:
                gate_free[i] += 1
            max_short[key] = max(m, a["size"])
            a["locate"] = marginal * price_s[key]
            a["packages"] = marginal
            a["fade_pct"] = fade
            loc_by_i[i] += a["locate"]
            return True

        # a2) TOPES, en orden cronologico del dia: exposicion (nocional abierto
        #     a la vez), margen del broker y tope por accion. El que no cabe se
        #     salta o se recorta (cap_mode) AQUI, antes de locates y de
        #     acumular: no paga alquiler ni cuenta para nada. Y en el mismo
        #     paso, tras el recorte, la puerta de locates: lo que tumba tampoco
        #     ocupa sitio.
        dia.sort(key=lambda a: (a["tr"]["t0"], a["si"]))
        equity_open_by_day[d] = equity_open
        cap_day = (equity_open * cap_pct / 100.0) if cap_pct > 0 else cap
        capacidad_m = equity_open * margin_cap_pct / 100.0
        cap_tk_dia = equity_open * ticker_cap_pct / 100.0
        for a in dia:
            tr = a["tr"]
            t0, t1 = tr["t0"], tr["t1"]
            while open_heap and open_heap[0][0] <= t0:
                _, freed = heapq.heappop(open_heap)
                exposure -= freed
            if exposure < 1e-9:
                exposure = 0.0
            while open_heap_m and open_heap_m[0][0] <= t0:
                _, freed_m = heapq.heappop(open_heap_m)
                usado_m -= freed_m
            if usado_m < 1e-9:
                usado_m = 0.0
            take = a["notional"]
            f_ok = 1.0
            if cap_day > 0 and exposure + take > cap_day + 1e-9:
                free = cap_day - exposure
                f_ok = min(f_ok, (free / a["notional"]) if (trim and free > 1e-9 and a["notional"] > 0) else 0.0)
            take_m = 0.0
            if margin_on:
                es_corto = tr["direction"].startswith("S")
                take_m = _req_ps(tr["entry"], es_corto, margin_broker) * a["size"]
                if capacidad_m > 0 and usado_m + take_m > capacidad_m + 1e-9:
                    free_m = capacidad_m - usado_m
                    f_ok = min(f_ok, (free_m / take_m) if (trim and free_m > 1e-9 and take_m > 0) else 0.0)
                    a["margin_hit"] = True
            take_t = 0.0
            if ticker_on:
                tk = tr["ticker"]
                h_tk = open_tk.setdefault(tk, [])
                while h_tk and h_tk[0][0] <= t0:
                    _, freed_t = heapq.heappop(h_tk)
                    used_tk[tk] = used_tk.get(tk, 0.0) - freed_t
                if used_tk.get(tk, 0.0) < 1e-9:
                    used_tk[tk] = 0.0
                if ticker_basis == "trade":
                    _b = str(a.get("budget_basis") or "risk")
                    take_t = a["notional"] if _b == "notional" else float(a.get("risk") or 0.0)
                    cap_tk = float(a.get("budget") or 0.0)
                else:
                    take_t = a["notional"] if ticker_basis == "notional" else float(a.get("risk") or 0.0)
                    cap_tk = cap_tk_dia
                if ticker_basis != "notional" and take_t <= 0:
                    ticker_sin_stop += 1
                if cap_tk > 0 and take_t > 0 and used_tk[tk] + take_t > cap_tk + 1e-9:
                    free_t = cap_tk - used_tk[tk]
                    f_ok = min(f_ok, (free_t / take_t) if (trim and free_t > 1e-9) else 0.0)
                    a["ticker_hit"] = True
            if f_ok <= 0.0:
                a["skipped"] = True
                skipped_by_i[a["si"]] += 1
                if a.get("margin_hit"):
                    margin_skipped += 1
                if a.get("ticker_hit"):
                    ticker_skipped += 1
                continue
            if f_ok < 1.0:
                for k in ("size", "notional", "gross", "fee", "slip", "net", "risk"):
                    a[k] *= f_ok
                a["trimmed"] = True
                trimmed_by_i[a["si"]] += 1
                if a.get("margin_hit"):
                    margin_trimmed += 1
                if a.get("ticker_hit"):
                    ticker_trimmed += 1
                take *= f_ok
                take_m *= f_ok
                take_t *= f_ok
            # La puerta de locates (y su alquiler) se decide AQUI, con el
            # tamano ya recortado: si la tumba, no ocupa exposicion, margen ni
            # tope por accion (antes se decidia despues y el sitio quedaba
            # ocupado por trades que no existian).
            if not _puerta_y_alquiler(a):
                continue
            if ticker_on:
                heapq.heappush(open_tk[tr["ticker"]], (t1, take_t))
                used_tk[tr["ticker"]] = used_tk.get(tr["ticker"], 0.0) + take_t
            heapq.heappush(open_heap, (t1, take))
            exposure += take
            if exposure > day_peak.get(d, 0.0):
                day_peak[d] = exposure
            if len(open_heap) > day_peak_n.get(d, 0):
                day_peak_n[d] = len(open_heap)
            if margin_on:
                heapq.heappush(open_heap_m, (t1, take_m))
                usado_m += take_m
                if usado_m > day_peak_m.get(d, 0.0):
                    day_peak_m[d] = usado_m
        dia = [a for a in dia if not a.get("skipped")]

        # b) Locates del dia (el estado; la decision va DENTRO del bucle de
        #    topes, mas arriba, trade a trade y en orden cronologico: 20-sep, un
        #    corto que la puerta tumba no debe ocupar exposicion ni margen).
        #    Compartidos: UN alquiler por ticker-dia para toda la cuenta sobre
        #    el maximo en corto A LA VEZ (una que cubre libera; la siguiente
        #    cabe gratis). Puerta por EV: entra si el EV en sombra de SU
        #    estrategia paga los paquetes DE MAS.
        if shared:
            for tk, pk in rented.items():
                if pk > 0:
                    loc_days.append({"ticker": tk, "date": d, "packages": pk, "ref": ref[tk], "price": price[tk]})
        else:
            for (i, tk), m in max_short.items():
                if m > 0:
                    loc_days.append({"ticker": tk, "date": d, "packages": int(math.ceil(m / 100.0)),
                                     "ref": ref_s[(i, tk)], "price": price_s[(i, tk)]})

        # c) Acumular el dia
        pnl_by_i = [0.0] * n
        n_by_i = [0] * n
        for a in dia:
            if a.get("gate_out"):
                continue
            i = a["si"]
            tr = a["tr"]
            st = tot[i]
            st["n_trades"] += 1
            st["gross"] += a["gross"]
            st["fees"] += a["fee"]
            st["slippage"] += a["slip"]
            st["notional"] += a["notional"]
            if a["net"] > 0:
                st["wins"] += 1
                st["gross_win"] += a["net"]
            elif a["net"] < 0:
                st["gross_loss"] += -a["net"]
            if a["as_saved"]:
                st["locates"] += a["locate"]     # ya dentro del neto guardado: solo se ensena
            tot_fees += a["fee"]
            tot_slip += a["slip"]
            pnl_by_i[i] += a["net"]
            n_by_i[i] += 1
            trade_rows.append((d, tr["entry_time"], i, a["r"], a["net"]))
            accepted.append({
                "date": d, "si": i, "t0": tr["t0"], "t1": tr["t1"], "ticker": tr["ticker"],
                "dir": tr["direction"][:1], "entry": tr["entry_time"][11:16], "exit": tr["exit_time"][11:16],
                "entry_px": tr["entry"], "exit_px": tr["exit"], "size": a["size"], "notional": a["notional"],
                "pnl": a["net"], "fees": a["fee"], "slip": a["slip"], "locate": a["locate"], "r": a["r"],
                "risk": float(a.get("risk", 0.0)),
                "budget": float(a.get("budget", 0.0)), "budget_basis": str(a.get("budget_basis") or "risk"),
                "reason": tr["exit_reason"], "packages": int(a.get("packages", 0)), "fade_pct": float(a.get("fade_pct", 0.0)),
                "setup_mult": float(a.get("setup_mult", 1.0)),
            })
        day_total = 0.0
        for i in range(n):
            loc_i = loc_by_i[i]
            pnl_i = pnl_by_i[i] - loc_i
            tot_loc += loc_i
            tot[i]["locates"] += loc_i
            tot[i]["pnl_net"] += pnl_i
            per_pnl[i].append(pnl_i)
            per_trades[i].append(n_by_i[i])
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

    # ── 3. Los topes ya se aplicaron dentro de cada dia (a2). Totales para el informe.
    accepted.sort(key=lambda a: (a["t0"], a["date"]))
    skipped = sum(skipped_by_i)
    trimmed = sum(trimmed_by_i)

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
                "skipped": skipped_by_i[i],
                "trimmed": trimmed_by_i[i],
                "unsized": unsized[i],
                "blocked": blocked[i],
                "gate_out": gate_out[i],
                "gate_free": gate_free[i],
                "setup": setup_n[i],
                # Entradas recortadas por las reglas de la propia estrategia
                # (techo hibrido, cangrejo B, tope de caja).
                "reglas": recortes_reglas[i],
            },
            "reglas": {k: reglas[i][k] for k in ("hybrid", "cangrejo_b", "bs_pct", "ml_pct", "cb_pct")},
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
        # Fade necesario del corto (% del precio que hay que ganar solo para
        # pagar sus paquetes de mas) y esos paquetes.
        "fade": [round(a.get("fade_pct", 0.0), 3) for a in accepted],
        "packages": [int(a.get("packages", 0)) for a in accepted],
        "r": [round(a["r"], 2) for a in accepted],
        "reason": [a["reason"] for a in accepted],
        "setup_mult": [round(float(a.get("setup_mult", 1.0)), 3) for a in accepted],
    }
    locates_analysis = _analisis_locates(accepted, n, [str(r.get("name") or "") for r in runs], loc_days, loc_cfg)

    # Banda de locates: N semillas sobre los mismos paquetes (solo aleatorios).
    locates_band = None
    if loc_cfg and loc_cfg["mode"] == "random" and loc_cfg["band_seeds"] > 0 and loc_days:
        pnl_pre = [daily_pnl[k] + sum(per_locates[i][k] for i in range(n)) for k in range(len(calendar))]
        locates_band = _banda_locates(calendar, pnl_pre, loc_days, capital, loc_cfg["min"], loc_cfg["max"],
                                      loc_cfg["band_seeds"], loc_cfg["seed"])
    locates_report = {
        "mode": loc_cfg["mode"] if loc_cfg else "per_row",
        "shared": shared,
        "gate": bool(loc_cfg and loc_cfg["gate"]),
        "ticker_days": len(loc_days),
        "packages": int(sum(ld["packages"] for ld in loc_days)),
        "cost": ple._r6(tot_loc),
        "gate_out": int(sum(gate_out)),
        "gate_free": int(sum(gate_free)),
    }
    setup_out = None
    if mults is not None:
        setup_out = mults.informe([str(r.get("name") or "") for r in runs],
                                  ["capital" if execs[i]["sizing"] == "capital" else "risk" for i in range(n)])

    return {
        "config": {
            "capital": capital, "monthly_expenses": expenses, "max_exposure_usd": cap, "max_exposure_pct": cap_pct,
            "one_per_ticker": one_per_ticker,
            "max_ticker_pct": ticker_cap_pct, "ticker_cap_basis": ticker_basis,
            "cap_mode": "trim" if trim else "skip", "start_date": d_from, "end_date": d_to,
            "margin": ({"enabled": True, "broker": margin_broker, "capacity_pct": margin_cap_pct} if margin_on else None),
            "default_exec": default_exec,
            "locates": loc_cfg,
            "setup": setup_cfg,
            "sizing": "exec", "notional_usd": 0.0, "per_strategy_usd": {},
        },
        "locates_report": locates_report,
        "locates_band": locates_band,
        "locates_analysis": locates_analysis,
        "setup": setup_out,
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
        "ticker_cap_report": ({
            "pct": ticker_cap_pct, "basis": ticker_basis,
            "skipped": ticker_skipped, "trimmed": ticker_trimmed, "sin_stop": ticker_sin_stop,
        } if ticker_on else None),
        "margin_report": ({
            "enabled": True, "broker": margin_broker, "capacity_pct": margin_cap_pct,
            "skipped": margin_skipped, "trimmed": margin_trimmed,
            "pico_medio_pct": ple._r6(float(np.mean([100.0 * day_peak_m.get(d, 0.0) / (equity_open_by_day.get(d, capital) * margin_cap_pct / 100.0)
                                                      for d in calendar if equity_open_by_day.get(d, capital) > 0])) if calendar else 0.0),
            "pico_max_pct": ple._r6(max([100.0 * day_peak_m.get(d, 0.0) / (equity_open_by_day.get(d, capital) * margin_cap_pct / 100.0)
                                         for d in calendar if equity_open_by_day.get(d, capital) > 0] or [0.0])),
        } if margin_on else None),
        "cap_report": {"taken": len(accepted), "skipped": skipped, "trimmed": trimmed, "unsized": sum(unsized), "blocked": sum(blocked)},
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
