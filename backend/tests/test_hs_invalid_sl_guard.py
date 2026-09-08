"""Guard de SL estructural invalidado + fallback en reentradas.

Regresion de un bug real (2026-08-27): en corto, si al entrar el nivel del
hard stop estructural (p.ej. PMH) quedaba POR DEBAJO del precio de entrada
(stock que salto al scanner ya en RTH, sin subir tanto en premarket), el
chequeo `high >= SL` disparaba en la propia vela de entrada y el fill se
hacia al precio del nivel — un precio FUERA del rango de la vela —
contando un beneficio instantaneo imposible. En el run manual de RTH 2.3
de esa fecha, el 43% de los trades (540/1261) eran asi y aportaban el 87%
del PnL.

Semantica nueva (portfolio_sim.py y portfolio_sim_jit.py, paridad bit a bit):

  * Un nivel estructural que queda en el lado GANADOR de la entrada no es
    un stop: la premisa esta invalidada y NO SE ENTRA.
  * `hard_stop.fallback_value` (p.ej. "Previous Max" = el ultimo alto antes
    de entrar) rescata el stop en REENTRADAS, aplicando el mismo offset.
  * La primera entrada con el nivel roto no se hace aunque haya fallback.
  * Si el nivel de respaldo tambien queda invalidado, no se entra.
"""
import numpy as np
import pandas as pd
import pytest

from app.services.portfolio_sim import simulate as sim_py
from app.services.sim_dispatch import simulate_jit, warmup

HS = "Market Structure (HOD/LOD)"
BASE_TS = np.datetime64("2026-08-24T09:30:00").astype("datetime64[ns]").astype(np.int64)


@pytest.fixture(scope="module", autouse=True)
def _warm():
    warmup()


def _ts(n):
    return (BASE_TS + np.arange(n) * 60_000_000_000).astype(np.int64)


# ── Builders: un kwargs fresco por escenario ────────────────────────────────

def _base_short(n=40, **over):
    """Corto con hard stop estructural PMH. Constantes con overrides."""
    kw = dict(
        close=np.full(n, 10.0), open_=np.full(n, 10.0),
        high=np.full(n, 10.05), low=np.full(n, 9.95),
        entries=np.zeros(n, dtype=bool), exits=np.zeros(n, dtype=bool),
        timestamps=_ts(n),
        direction="shortonly", init_cash=10_000.0, risk_r=100.0,
        risk_type="FIXED",
        hs_type=HS, hs_value="PMH", hs_operator=">=", hs_offset_pct=0.0,
        pm_highs=np.full(n, 10.2),
        accumulate=True, max_reentries=2,
    )
    kw.update(over)
    return kw


def _dia_con_reentrada_sobre_pmh():
    """Trade 1 valido (stop en PMH) y reentrada ya por encima del PMH.

    Barras 0-12 a 10.0 (entrada en open[6]); barra 12 toca 10.3 -> stop en
    el PMH 10.2. Desde la barra 13 el precio pasa a 10.4 (squeeze posterior
    al stop-out). Segunda señal en la barra 20: entrada en open[21]=10.4,
    PMH ya roto, prev_high 10.9 (ultimo alto antes de entrar). Barra 25
    toca 11.0 -> stop de la reentrada en 10.9.
    """
    kw = _base_short()
    kw["open_"] = np.where(np.arange(40) < 13, 10.0, 10.4).astype(np.float64)
    kw["close"] = kw["open_"].copy()
    kw["high"] = np.where(np.arange(40) < 13, 10.05, 10.45).astype(np.float64)
    kw["low"] = np.where(np.arange(40) < 13, 9.95, 10.35).astype(np.float64)
    kw["high"][12] = 10.3   # stop del trade 1
    kw["high"][25] = 11.0   # stop de la reentrada
    kw["entries"][5] = True
    kw["entries"][20] = True
    kw["prev_highs"] = np.full(40, 10.05)
    kw["prev_highs"][20] = 10.9
    return kw


def _kw_pmh_roto():
    kw = _base_short()
    kw["entries"][5] = True
    kw["pm_highs"] = np.full(40, 9.0)  # PMH muy por debajo de la entrada
    return kw


def _kw_pmh_roto_con_fallback():
    kw = _kw_pmh_roto()
    kw["hs_fallback_value"] = "Previous Max"
    kw["prev_highs"] = np.full(40, 12.0)  # respaldo valido, pero es 1a entrada
    return kw


def _kw_pmh_valido():
    kw = _base_short()
    kw["entries"][5] = True
    kw["high"][12] = 10.3  # toca el stop
    return kw


def _kw_reentrada_con_fallback():
    kw = _dia_con_reentrada_sobre_pmh()
    kw["hs_fallback_value"] = "Previous Max"
    return kw


def _kw_reentrada_sin_fallback():
    return _dia_con_reentrada_sobre_pmh()


def _kw_reentrada_respaldo_invalido():
    kw = _dia_con_reentrada_sobre_pmh()
    kw["hs_fallback_value"] = "Previous Max"
    kw["prev_highs"][20] = 10.3  # tambien por debajo de la entrada (10.4)
    return kw


def _kw_long_hod_sobre_entrada():
    kw = _base_short(40, direction="longonly", hs_value="HOD",
                     hods=np.full(40, 10.5))  # nivel por ENCIMA de la entrada
    kw["entries"][5] = True
    return kw


def _kw_long_hod_valido():
    kw = _base_short(40, direction="longonly", hs_value="HOD",
                     hods=np.full(40, 9.5))
    kw["entries"][5] = True
    kw["low"][10] = 9.4
    return kw


def _kw_primera_entrada_rescatada():
    """Primera entrada con PMH roto + fallback Previous Max + flag
    `hs_fallback_first`: el respaldo aplica desde el primer trade."""
    kw = _kw_pmh_roto()  # entrada 10.0, PMH 9.0
    kw["hs_fallback_value"] = "Previous Max"
    kw["hs_fallback_first"] = True
    kw["prev_highs"] = np.full(40, 10.6)  # ultimo alto, sobre la entrada
    kw["high"][12] = 10.7                  # toca el stop de respaldo
    return kw


def _kw_flag_sin_nivel_de_respaldo():
    """El flag solo hace algo si hay nivel de respaldo elegido."""
    kw = _kw_pmh_roto()
    kw["hs_fallback_first"] = True
    return kw


ESCENARIOS = [
    ("pmh_roto", _kw_pmh_roto),
    ("pmh_roto_con_fallback", _kw_pmh_roto_con_fallback),
    ("pmh_valido", _kw_pmh_valido),
    ("reentrada_con_fallback", _kw_reentrada_con_fallback),
    ("reentrada_sin_fallback", _kw_reentrada_sin_fallback),
    ("reentrada_respaldo_invalido", _kw_reentrada_respaldo_invalido),
    ("long_hod_sobre_entrada", _kw_long_hod_sobre_entrada),
    ("long_hod_valido", _kw_long_hod_valido),
    ("primera_entrada_rescatada", _kw_primera_entrada_rescatada),
    ("flag_sin_nivel_de_respaldo", _kw_flag_sin_nivel_de_respaldo),
]


def _assert_equal(res_py, res_jit, ctx):
    assert res_py["trades"] == res_jit["trades"], (
        f"trades difieren [{ctx}]:\npy : {res_py['trades'][:3]}\njit: {res_jit['trades'][:3]}")
    np.testing.assert_array_equal(res_py["equity"], res_jit["equity"],
                                  err_msg=f"equity difiere [{ctx}]")


# ── Unit: semantica del guard + fallback (motor Python) ────────────────────

def test_short_con_pmh_roto_no_entra():
    """EL BUG: antes del guard esto producia un trade 'SL' ganador al instante."""
    res = sim_py(**_kw_pmh_roto())
    assert res["trades"] == []
    np.testing.assert_array_equal(res["equity"], np.full(40, 10_000.0))


def test_el_fallback_no_rescata_la_primera_entrada():
    """El respaldo es cosa de reentradas: la primera con nivel roto, no va."""
    assert sim_py(**_kw_pmh_roto_con_fallback())["trades"] == []


def test_short_con_pmh_valido_funciona_igual():
    """Regresion: PMH sobre la entrada = stop de toda la vida."""
    res = sim_py(**_kw_pmh_valido())
    assert len(res["trades"]) == 1
    t = res["trades"][0]
    assert t["exit_reason"] == "SL"
    assert t["stop_loss"] == pytest.approx(10.2)
    assert t["pnl"] < 0


def test_reentrada_rescatada_con_previous_max():
    res = sim_py(**_kw_reentrada_con_fallback())
    assert len(res["trades"]) == 2
    t1, t2 = res["trades"]
    assert t1["stop_loss"] == pytest.approx(10.2)
    assert t2["stop_loss"] == pytest.approx(10.9)  # el ultimo alto, no el PMH roto
    assert t2["entry_price"] == pytest.approx(10.4)
    assert t2["exit_reason"] == "SL"


def test_reentrada_sin_fallback_se_salta():
    res = sim_py(**_kw_reentrada_sin_fallback())
    assert len(res["trades"]) == 1
    assert res["trades"][0]["stop_loss"] == pytest.approx(10.2)


def test_reentrada_con_respaldo_tambien_invalido_se_salta():
    res = sim_py(**_kw_reentrada_respaldo_invalido())
    assert len(res["trades"]) == 1


def test_long_con_hod_sobre_la_entrada_no_entra():
    assert sim_py(**_kw_long_hod_sobre_entrada())["trades"] == []


def test_long_con_hod_valido_funciona_igual():
    res = sim_py(**_kw_long_hod_valido())
    assert len(res["trades"]) == 1
    t = res["trades"][0]
    assert t["exit_reason"] == "SL"
    assert t["stop_loss"] == pytest.approx(9.5)
    assert t["pnl"] < 0


def test_primera_entrada_rescatada_con_flag():
    """`fallback_first_entry`: la primera entrada con nivel roto tambien
    puede usar el respaldo (no solo las reentradas)."""
    res = sim_py(**_kw_primera_entrada_rescatada())
    assert len(res["trades"]) == 1
    t = res["trades"][0]
    assert t["stop_loss"] == pytest.approx(10.6)  # Previous Max, no el PMH roto
    assert t["exit_reason"] == "SL"
    assert t["pnl"] < 0


def test_el_flag_sin_nivel_de_respaldo_no_hace_nada():
    assert sim_py(**_kw_flag_sin_nivel_de_respaldo())["trades"] == []


# ── Paridad Python ↔ JIT en todos los escenarios ───────────────────────────

@pytest.mark.parametrize("nombre,builder", ESCENARIOS, ids=[n for n, _ in ESCENARIOS])
def test_paridad_py_jit(nombre, builder):
    kw = builder()
    _assert_equal(sim_py(**kw), simulate_jit(**kw), nombre)


# ── Invariante global: ningun trade puede quedar con el SL del lado ganador ─

@pytest.mark.parametrize("nombre,builder", ESCENARIOS, ids=[n for n, _ in ESCENARIOS])
def test_invariante_lado_del_sl(nombre, builder):
    for t in sim_py(**builder())["trades"]:
        if t["direction"] == "Short":
            assert t["stop_loss"] > t["entry_price"], (
                f"[{nombre}] short con SL bajo la entrada: {t}")
        else:
            assert 0.0 < t["stop_loss"] < t["entry_price"], (
                f"[{nombre}] long con SL sobre la entrada: {t}")


# ── E2E: `hard_stop.fallback_value` llega al simulador por el camino
# secuencial de run_backtest (el que corre por defecto en local) ───────────

from app.db import gcs_cache, slab_store
from app.services.backtest_service import run_backtest

STRATEGY_E2E = {
    "bias": "short", "apply_day": "gap_day",
    "entry_logic": {"timeframe": "1m", "root_condition": {"operator": "AND", "conditions": [
        {"type": "indicator_comparison", "timeframe": "1m",
         "source": {"name": "Volume"}, "comparator": "GREATER_THAN", "target": 500.0},
    ]}},
    "risk_management": {
        "use_hard_stop": True,
        "hard_stop": {"type": HS, "value": "PMH", "offset_pct": 0},
        "accept_reentries": True, "max_reentries": 2,
    },
}


@pytest.fixture
def _secuencial(tmp_path, monkeypatch):
    """Aislamiento del camino secuencial (patron de test_daily_limit_sequential)."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr(gcs_cache, "LOCAL_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("BTT_SLAB_DIR", str(tmp_path / "slabs"))
    monkeypatch.delenv("BTT_SLAB_STREAM_ENABLED", raising=False)
    monkeypatch.delenv("BACKTEST_PARALLEL_WORKERS", raising=False)
    monkeypatch.setenv("BACKTEST_NUMBA_SIM", "0")
    slab_store._OPEN_SLABS.clear()
    with gcs_cache._MONTH_CACHE_LOCK:
        gcs_cache._MONTH_CACHE.clear()
        gcs_cache._MONTH_CACHE_SIZES.clear()
    yield
    slab_store._OPEN_SLABS.clear()


def _dia_gap_pmh():
    """Un ticker-dia: premarket plano (PMH 10.2); entrada valida a las 09:32
    que cae en el PMH a las 09:40; squeeze por encima; reentrada a las 09:45
    con el PMH ya roto (prev_high 10.46 sobre la entrada 10.44)."""
    rows = []

    def bar(ts, o, h, l, c, v=100):
        rows.append({"ticker": "GUARD", "date": "2026-08-24", "timestamp": ts,
                     "open": o, "high": h, "low": l, "close": c, "volume": v})

    pm0 = pd.Timestamp("2026-08-24 04:00")
    for i in range(330):  # 04:00-09:29
        bar(pm0 + pd.Timedelta(minutes=i), 10.0,
            10.2 if i == 100 else 10.05, 9.95, 10.0)

    rth0 = pd.Timestamp("2026-08-24 09:30")
    cierres = {11: 10.30, 12: 10.34, 13: 10.38, 14: 10.42, 15: 10.44}
    vol = {2: 1000, 15: 1000}       # señales: 09:32 (valida) y 09:45 (PMH roto)
    highs = {10: 10.25, 14: 10.46, 25: 10.50}  # stop 1, mecha/prev_high, stop 2
    for i in range(390):
        c = cierres.get(i, 10.0 if i <= 10 else 10.44)
        h = highs.get(i, 10.05 if i <= 9 else c + 0.01)
        l = 9.95 if i <= 9 else c - 0.01
        o = cierres.get(i - 1, 10.0 if i <= 11 else 10.44)
        if i == 10:
            o = 10.0
        if i == 16:
            o = 10.44  # fill de la reentrada
        bar(rth0 + pd.Timedelta(minutes=i), o, h, l, c, vol.get(i, 100))
    return pd.DataFrame(rows)


def _dia_gap_pmh_roto_desde_el_principio():
    """Variante: el precio abre YA por encima del PMH (10.2) y la primera
    señal (09:32) llega con el nivel roto. El ultimo alto antes de esa
    señal es 10.46 (mecha de 09:31)."""
    rows = []

    def bar(ts, o, h, l, c, v=100):
        rows.append({"ticker": "GUARD", "date": "2026-08-24", "timestamp": ts,
                     "open": o, "high": h, "low": l, "close": c, "volume": v})

    pm0 = pd.Timestamp("2026-08-24 04:00")
    for i in range(330):
        bar(pm0 + pd.Timedelta(minutes=i), 10.0,
            10.2 if i == 100 else 10.05, 9.95, 10.0)

    rth0 = pd.Timestamp("2026-08-24 09:30")
    vol = {2: 1000}
    highs = {1: 10.46, 10: 10.50}
    for i in range(390):
        c = 10.44
        h = highs.get(i, 10.45)
        o = 10.4 if i == 0 else 10.44
        bar(rth0 + pd.Timedelta(minutes=i), o, h, c - 0.01, c, vol.get(i, 100))
    return pd.DataFrame(rows)


def _corre_e2e(fallback=None, first=False, dia=None):
    hs = dict(STRATEGY_E2E["risk_management"]["hard_stop"])
    if fallback is not None:
        hs["fallback_value"] = fallback
    if first:
        hs["fallback_first_entry"] = True
    sd = {**STRATEGY_E2E,
          "risk_management": {**STRATEGY_E2E["risk_management"], "hard_stop": hs}}
    qual = pd.DataFrame([{"ticker": "GUARD", "date": "2026-08-24",
                          "prev_close": 9.0, "gap_pct": 45.0,
                          "yesterday_open": 6.9, "lag_rth_open_1": 6.9}])
    return run_backtest(
        qualifying_df=qual, intraday_df=(dia if dia is not None else _dia_gap_pmh()),
        strategy_def=sd,
        init_cash=10_000.0, risk_r=100.0, risk_type="FIXED",
        market_sessions=["rth"],
    )


def test_e2e_camino_secuencial_salta_la_reentrada_invalida(_secuencial):
    res = _corre_e2e()
    trades = res["trades"]
    assert len(trades) == 1, (
        f"la reentrada con PMH roto debe saltarse; trades: {trades}")
    assert trades[0]["stop_loss"] == pytest.approx(10.2)
    assert all(t["stop_loss"] > t["entry_price"] for t in trades)


def test_e2e_camino_secuencial_aplica_el_fallback_del_json(_secuencial):
    res = _corre_e2e(fallback="Previous Max")
    trades = res["trades"]
    assert len(trades) == 2, f"la reentrada debe rescatarse con Previous Max: {trades}"
    t1, t2 = trades
    assert t1["stop_loss"] == pytest.approx(10.2)
    assert t2["entry_price"] == pytest.approx(10.44)
    assert t2["stop_loss"] == pytest.approx(10.46)  # el ultimo alto, via JSON
    assert t2["exit_reason"] == "SL"
    assert all(t["stop_loss"] > t["entry_price"] for t in trades)


def test_e2e_primera_entrada_rescatada_con_flag(_secuencial):
    """PMH roto desde el mismo arranque: sin flag no hay trade; con
    `fallback_first_entry` la primera entrada usa el respaldo."""
    dia = _dia_gap_pmh_roto_desde_el_principio()
    res_sin = _corre_e2e(dia=dia)
    assert res_sin["trades"] == [], (
        f"la primera entrada con nivel roto se salta por defecto: {res_sin['trades']}")

    res_con = _corre_e2e(fallback="Previous Max", first=True, dia=dia)
    trades = res_con["trades"]
    assert len(trades) == 1, f"la primera entrada debe rescatarse: {trades}"
    t = trades[0]
    assert t["entry_price"] == pytest.approx(10.44)
    assert t["stop_loss"] == pytest.approx(10.46)  # mecha de las 09:31
    assert t["exit_reason"] == "SL"
    assert t["stop_loss"] > t["entry_price"]
