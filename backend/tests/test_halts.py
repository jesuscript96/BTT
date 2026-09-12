"""
Coste de Halts (2026-09-12). Ver app/services/halts.py.

  1. Sin `halts` NADA cambia, y `halts=None` pasa por `sim_dispatch` al JIT.
  2. Traduccion de la tabla a indices de vela (halt_idx / resume_idx / None).
  3. Modo «primero»: sale en la reapertura penalizado, no reentra ese dia, un
     stop cruzado durante el halt NO se ejecuta, y con halt antes de entrar no
     pasa nada.
  4. Modo «n»: cuenta desde la apertura del dia (los halts anteriores a la
     entrada cuentan), y el que dispara es el N-esimo.
  5. Sin reapertura ese dia: cierra al ultimo precio antes del halt, marcado
     «atrapado».
  6. Carga de la tabla desde parquets diarios y E2E por `run_backtest`.
"""
import numpy as np
import pandas as pd
import pytest

from app.services import sim_dispatch
from app.services.halts import ConfigHalts, TablaHalts, cargar_halts, halts_a_indices
from app.services.backtest_service import _enrich_trades, _group_partial_exits
from app.services.portfolio_sim import simulate as sim_py

NS_MIN = 60_000_000_000
T0 = 1_756_800_000 * 1_000_000_000 + 4 * 3600 * 1_000_000_000

KW = dict(direction="shortonly", init_cash=100_000.0, risk_r=1000.0, risk_type="FIXED",
          sl_stop=0.20, fees=0.0, slippage=0.0, look_ahead_prevention=True)


def _velas(n=20, precio=1.0):
    """Dia plano a `precio`; entrada en la vela 2 -> fill en la apertura de la 3."""
    close = np.full(n, precio)
    open_ = np.full(n, precio)
    high = np.full(n, precio * 1.01)
    low = np.full(n, precio * 0.99)
    ts = (T0 + np.arange(n) * NS_MIN).astype(np.int64)
    entries = np.zeros(n, dtype=bool)
    entries[2] = True
    exits = np.zeros(n, dtype=bool)
    return dict(close=close, open_=open_, high=high, low=low,
                entries=entries, exits=exits, timestamps=ts)


def _halt(orden, halt_bar, resume_bar, reason=50, seg=30):
    """Un halt que para `seg` segundos dentro de `halt_bar` y reabre en
    `resume_bar` (None = no reabre ese dia), en el mismo reloj que _velas."""
    return {"halt_ns": int(T0 + halt_bar * NS_MIN + seg * 1_000_000_000),
            "resume_ns": (int(T0 + resume_bar * NS_MIN) if resume_bar is not None else None),
            "reason": reason, "motivo": "LULD" if reason == 50 else "T1", "minutos": 5.0,
            "orden": orden}


def _con(v, cfg, lista):
    return sim_py(**v, **KW, halts=(cfg, halts_a_indices(lista, v["timestamps"])))


# ── 1. Sin coste no cambia nada ────────────────────────────────────────────

def test_sin_coste_ni_claves_ni_resumen():
    v = _velas()
    r = sim_py(**v, **KW)
    assert "halts" not in r
    assert not any(k.startswith("halt_") for t in r["trades"] for k in t)


def test_halts_none_pasa_por_el_dispatcher_al_jit(monkeypatch):
    monkeypatch.setenv("BACKTEST_NUMBA_SIM", "1")
    v = _velas()
    assert sim_dispatch.simulate(**v, **KW, halts=None)["trades"] == sim_py(**v, **KW)["trades"]


def test_con_coste_el_dispatcher_desvia_al_python(monkeypatch):
    monkeypatch.setenv("BACKTEST_NUMBA_SIM", "1")
    v = _velas()
    lista = halts_a_indices([_halt(1, 6, 9)], v["timestamps"])
    r = sim_dispatch.simulate(**v, **KW, halts=(ConfigHalts(), lista))
    assert r["trades"][0]["exit_reason"] == "Halt"


def test_lista_vacia_es_como_sin_coste():
    v = _velas()
    base = sim_py(**v, **KW)
    r = sim_py(**v, **KW, halts=(ConfigHalts(), []))
    assert r["trades"] == base["trades"] and "halts" not in r


# ── 2. Traduccion a indices ───────────────────────────────────────────────

def test_halts_a_indices():
    ts = (T0 + np.arange(10) * NS_MIN).astype(np.int64)
    out = halts_a_indices([_halt(1, 3, 6), _halt(2, 8, None), _halt(3, 9, 12)], ts)
    assert [(h["halt_idx"], h["resume_idx"]) for h in out] == [(3, 6), (8, None), (9, None)]
    # Un halt anterior a la primera vela del frame se descarta.
    assert halts_a_indices([{"halt_ns": T0 - 1, "resume_ns": None, "orden": 1}], ts) == []
    # Y uno POSTERIOR al ultimo minuto tambien (el bug de la primera corrida
    # real: los halts de RTH de una estrategia de premercado caian en la
    # ultima vela como «atrapados»). Dentro del ultimo minuto si cuenta.
    assert halts_a_indices([{"halt_ns": T0 + 10 * NS_MIN, "resume_ns": None, "orden": 1}], ts) == []
    assert halts_a_indices([{"halt_ns": T0 + 60 * NS_MIN, "resume_ns": None, "orden": 1}], ts) == []
    dentro = halts_a_indices([{"halt_ns": T0 + 9 * NS_MIN + 30 * 10**9, "resume_ns": None, "orden": 1}], ts)
    assert [(h["halt_idx"], h["resume_idx"]) for h in dentro] == [(9, None)]
    assert halts_a_indices([], ts) == [] and halts_a_indices(None, ts) == []


# ── 3. Modo «primero» ─────────────────────────────────────────────────────

def test_primero_sale_en_la_reapertura_penalizado_y_no_reentra():
    """Corto en 1,00. Halt en la vela 6, reabre en la 9 a 1,50; con 10 % de
    slippage sale a 1,65. Un stop cruzado en la vela 7 (dentro del halt) no
    se ejecuta. La senal de la vela 12 no entra: bloqueado el resto del dia."""
    v = _velas()
    v["high"][7] = 2.0                     # cruzaria el stop (1,20) durante el halt
    v["open_"][9] = 1.5
    v["entries"][12] = True
    kw = {**KW, "accumulate": True}
    base = sim_py(**v, **kw)
    assert [t["exit_reason"] for t in base["trades"]] == ["SL", "EOD"]

    r = sim_py(**v, **kw, halts=(ConfigHalts(modo="primero", slippage_pct=10.0),
                                  halts_a_indices([_halt(1, 6, 9)], v["timestamps"])))
    t = r["trades"]
    assert len(t) == 1
    assert t[0]["exit_reason"] == "Halt" and t[0]["exit_idx"] == 9
    assert t[0]["halt_base_price"] == pytest.approx(1.5)
    assert t[0]["exit_price"] == pytest.approx(1.65)
    assert t[0]["pnl"] == pytest.approx((1.0 - 1.65) * 1000.0)
    assert t[0]["halt_penalty"] == pytest.approx(0.15 * 1000.0)
    assert t[0]["halt_n"] == 1 and t[0]["halt_atrapado"] is False and t[0]["halt_reason"] == 50
    assert r["halts"] == [{"idx": 6, "orden": 1, "reason": 50, "atrapado": False, "penalizacion": 150.0}]
    # La equity de las velas del halt y la reapertura ya lleva el cierre.
    assert r["equity"][7] == pytest.approx(100_000.0 + t[0]["pnl"])
    assert r["equity"][-1] == pytest.approx(100_000.0 + t[0]["pnl"])


def test_halt_antes_de_entrar_no_hace_nada():
    v = _velas()
    base = sim_py(**v, **KW)
    r = _con(v, ConfigHalts(), [_halt(1, 0, 1)])
    assert r["trades"] == base["trades"] and r["halts"] == []


def test_largo_sale_por_debajo_de_la_reapertura():
    v = _velas()
    v["open_"][9] = 0.5
    kw = {**KW, "direction": "longonly"}
    r = sim_py(**v, **kw, halts=(ConfigHalts(slippage_pct=10.0),
                                  halts_a_indices([_halt(1, 6, 9)], v["timestamps"])))
    t = r["trades"][0]
    assert t["exit_reason"] == "Halt" and t["exit_price"] == pytest.approx(0.45)
    assert t["pnl"] == pytest.approx((0.45 - 1.0) * 1000.0)


# ── 4. Modo «n» ───────────────────────────────────────────────────────────

def test_n_cuenta_desde_la_apertura_del_dia():
    """N=3. Los halts 1 y 2 fueron antes de entrar (orden de la tabla): el
    primero que pilla dentro es el 3.o y dispara. Con N=4 no dispara y el
    trade acaba a EOD como sin coste."""
    v = _velas(n=30)
    lista = [_halt(1, 0, 1), _halt(2, 1, 2), _halt(3, 8, 11), _halt(4, 20, 22)]
    r3 = _con(v, ConfigHalts(modo="n", n_halts=3, slippage_pct=0.0), lista)
    assert r3["trades"][0]["exit_reason"] == "Halt" and r3["trades"][0]["halt_n"] == 3
    assert r3["trades"][0]["exit_idx"] == 11
    r4 = _con(v, ConfigHalts(modo="n", n_halts=4, slippage_pct=0.0), lista)
    assert r4["trades"][0]["exit_reason"] == "Halt" and r4["trades"][0]["halt_n"] == 4
    assert r4["trades"][0]["exit_idx"] == 22
    r9 = _con(v, ConfigHalts(modo="n", n_halts=9), lista)
    assert r9["trades"][0]["exit_reason"] == "EOD" and r9["halts"] == []


def test_n_los_halts_dentro_por_debajo_de_n_no_cierran():
    v = _velas(n=30)
    v["high"][12] = 1.1                    # sigue vivo tras el halt 1
    lista = [_halt(1, 6, 8), _halt(2, 14, 16)]
    r = _con(v, ConfigHalts(modo="n", n_halts=2, slippage_pct=0.0), lista)
    t = r["trades"][0]
    assert t["exit_reason"] == "Halt" and t["halt_n"] == 2 and t["exit_idx"] == 16


# ── 5. Sin reapertura ─────────────────────────────────────────────────────

def test_atrapado_cierra_al_ultimo_precio_antes_del_halt():
    v = _velas()
    v["close"][6] = 1.3
    r = _con(v, ConfigHalts(slippage_pct=10.0), [_halt(1, 6, None, reason=70)])
    t = r["trades"][0]
    assert t["exit_reason"] == "Halt (atrapado)" and t["exit_idx"] == 6
    assert t["halt_base_price"] == pytest.approx(1.3) and t["exit_price"] == pytest.approx(1.43)
    assert t["halt_atrapado"] is True and t["halt_reason"] == 70
    assert r["halts"][0]["atrapado"] is True


# ── agrupado / etiquetas ──────────────────────────────────────────────────

def test_agrupado_y_etiqueta():
    v = _velas()
    v["open_"][9] = 1.5
    r = _con(v, ConfigHalts(slippage_pct=10.0), [_halt(1, 6, 9)])
    ts = pd.Series(pd.to_datetime(v["timestamps"]))
    g = _group_partial_exits(_enrich_trades(r["trades"], ts, "XX", "2025-09-01", {}, 1000.0))
    assert len(g) == 1 and g[0]["halt_n"] == 1 and g[0]["halt_time_epoch"] == int(ts.iloc[6].timestamp())
    assert g[0]["exit_reason"] == "Halt"


def test_config_valida():
    assert ConfigHalts().umbral == 1
    assert ConfigHalts(modo="n", n_halts=3).umbral == 3
    with pytest.raises(ValueError):
        ConfigHalts(modo="loquesea")
    with pytest.raises(ValueError):
        ConfigHalts(modo="n", n_halts=0)
    with pytest.raises(ValueError):
        ConfigHalts(slippage_pct=-1)


# ── 6. Tabla desde parquets y E2E ─────────────────────────────────────────

def _escribe_tabla(directorio, filas):
    directorio.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(filas, columns=["instrument_id", "date", "halt_ts", "resume_ts", "reason",
                                      "ssr", "symbol", "minutos", "motivo"])
    for d, g in df.groupby("date"):
        g.to_parquet(directorio / f"{d}.parquet", index=False)


def test_cargar_halts_desde_parquets(tmp_path):
    d = tmp_path / "dias"
    _escribe_tabla(d, [
        (1, "2025-09-01", pd.Timestamp("2025-09-01 10:00"), pd.Timestamp("2025-09-01 10:05"), 50, "N", "TK00", 5.0, "LULD"),
        (1, "2025-09-01", pd.Timestamp("2025-09-01 09:40"), pd.Timestamp("2025-09-01 09:45"), 50, "N", "TK00", 5.0, "LULD"),
        (2, "2025-09-02", pd.Timestamp("2025-09-02 11:00"), pd.NaT, 70, "N", "TK01", None, "T12"),
        (3, "2025-09-02", pd.Timestamp("2025-09-02 11:00"), pd.NaT, 50, "N", None, None, "LULD"),  # sin simbolo: fuera
    ])
    t = cargar_halts("2025-09-01", "2025-09-02", str(d))
    assert isinstance(t, TablaHalts) and t.n_dias_fichero == 2 and t.n_halts == 3
    h = t.de("TK00", "2025-09-01")
    assert [x["orden"] for x in h] == [1, 2]                     # reordenados por hora
    assert h[0]["halt_ns"] == int(pd.Timestamp("2025-09-01 09:40").value)
    assert t.de("TK01", "2025-09-02")[0]["resume_ns"] is None
    assert t.de("ZZZ", "2025-09-01") == []
    assert cargar_halts("2030-01-01", "2030-01-02", str(d)).n_halts == 0


from app.db import gcs_cache, slab_store
from app.services.backtest_service import run_backtest

STRATEGY = {
    "bias": "short", "apply_day": "gap_day",
    "entry_logic": {"timeframe": "1m", "root_condition": {"operator": "AND", "conditions": [
        {"type": "indicator_comparison", "timeframe": "1m",
         "source": {"name": "Bar Close"}, "comparator": "LESS_THAN", "target": {"name": "VWAP"}},
        {"type": "indicator_comparison", "timeframe": "1m",
         "source": {"name": "Bar Open"}, "comparator": "GREATER_THAN", "target": {"name": "VWAP"}},
    ]}},
    "risk_management": {"use_hard_stop": True, "hard_stop": {"type": "Percentage", "value": 15},
                        "accept_reentries": True, "max_reentries": -1},
}


@pytest.fixture
def _secuencial(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr(gcs_cache, "LOCAL_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("BTT_SLAB_DIR", str(tmp_path / "slabs"))
    monkeypatch.delenv("BTT_SLAB_STREAM_ENABLED", raising=False)
    monkeypatch.delenv("BACKTEST_PARALLEL_WORKERS", raising=False)
    monkeypatch.setenv("BACKTEST_NUMBA_SIM", "1")
    slab_store._OPEN_SLABS.clear()
    with gcs_cache._MONTH_CACHE_LOCK:
        gcs_cache._MONTH_CACHE.clear()
        gcs_cache._MONTH_CACHE_SIZES.clear()
    yield
    slab_store._OPEN_SLABS.clear()


def _mk_day(ticker, date, n=420, seed=0):
    rng = np.random.default_rng(seed)
    ts = pd.date_range(f"{date} 04:00", periods=n, freq="1min")
    close = 8.0 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    open_ = close * np.exp(rng.normal(0, 0.004, n))
    return pd.DataFrame({
        "ticker": ticker, "date": date, "timestamp": ts,
        "open": open_, "high": np.maximum(open_, close) * 1.004,
        "low": np.minimum(open_, close) * 0.996, "close": close,
        "volume": rng.integers(100, 50000, n),
    })


def _datos(n_tickers=4):
    days = ["2025-09-01", "2025-09-02"]
    qual_rows, trozos = [], []
    for i in range(n_tickers):
        tk = f"TK{i:02d}"
        for j, d in enumerate(days):
            trozos.append(_mk_day(tk, d, seed=i * 10 + j))
            qual_rows.append({"ticker": tk, "date": d, "prev_close": 8.0, "gap_pct": 60.0,
                              "yesterday_open": 7.7, "lag_rth_open_1": 7.7})
    return pd.DataFrame(qual_rows), pd.concat(trozos, ignore_index=True)


def _corre(halts=None):
    qual, intraday = _datos()
    return run_backtest(
        qualifying_df=qual, intraday_df=intraday, strategy_def=STRATEGY,
        init_cash=10000.0, risk_r=100.0, risk_type="FIXED",
        market_sessions=["rth"], day_group_iter=None, n_groups_hint=None,
        halts=halts,
    )


def test_e2e_sin_coste_intacto(_secuencial):
    base = _corre(None)
    assert len(base["trades"]) > 0 and "halts" not in base
    assert not any(k.startswith("halt_") for t in base["trades"] for k in t)


def test_e2e_primero_cierra_y_cuenta(_secuencial, tmp_path):
    base = _corre(None)
    # El frame RTH del fixture va de 09:30 a 10:59 (420 velas desde las 04:00).
    # Un halt cada 10 minutos de 09:40 a 10:50 en cada ticker-dia: cualquier
    # posicion abierta en la sesion acaba pillada. Y uno a las 12:00, FUERA
    # del frame, que debe descartarse (el bug de la primera corrida real).
    filas = []
    for tk in ("TK00", "TK01", "TK02", "TK03"):
        for d in ("2025-09-01", "2025-09-02"):
            for hh, mm in ((9, 40), (9, 50), (10, 0), (10, 10), (10, 20), (10, 30), (10, 40), (10, 50)):
                filas.append((1, d, pd.Timestamp(f"{d} {hh:02d}:{mm:02d}:30"),
                              pd.Timestamp(f"{d} {hh:02d}:{mm + 5:02d}:30"), 50, "N", tk, 5.0, "LULD"))
            filas.append((1, d, pd.Timestamp(f"{d} 12:00"), pd.Timestamp(f"{d} 12:05"), 50, "N", tk, 5.0, "LULD"))
    _escribe_tabla(tmp_path / "dias", filas)
    tabla = cargar_halts("2025-09-01", "2025-09-02", str(tmp_path / "dias"))
    con = _corre((ConfigHalts(modo="primero", slippage_pct=5.0), tabla))
    tr = con["trades"]
    h = [t for t in tr if t["exit_reason"].startswith("Halt")]
    assert h, "con el coste debe haber cierres por halt"
    assert all(1 <= t["halt_n"] <= 8 and t["halt_slip_pct"] == 5.0 for t in h)
    assert all(t["exit_price"] == pytest.approx(t["halt_base_price"] * 1.05, rel=1e-6) for t in h)
    # Ninguno «atrapado»: los halts de dentro reabren en el frame, y el de las
    # 12:00 (fuera) no puede pegarse a la ultima vela.
    assert not any(t.get("halt_atrapado") for t in h)
    assert all(t["exit_time"][-8:] != "10:59:00" for t in h)
    res = con["halts"]
    assert res["enabled"] and res["modo"] == "primero" and res["n_halts"] == 1
    # `dias_con_halts` cuenta ticker-dias SIMULADOS (con senal) que tenian
    # halts en la tabla; los dias sin senal se saltan antes.
    assert res["trades"] == len(h) and 1 <= res["dias_con_halts"] <= 8 and res["tabla_halts"] == 72
    assert res["penalizacion_usd"] == pytest.approx(sum(t["halt_penalty"] for t in h), abs=0.05)
    # Tras un halt no se reentra ese dia: ningun trade del ticker-dia empieza
    # despues del que cerro por halt.
    for t in h:
        despues = [u for u in tr if u["ticker"] == t["ticker"] and u["date"] == t["date"]
                   and u["entry_idx"] > t["entry_idx"]]
        assert despues == [], despues
    assert len(tr) <= len(base["trades"])
