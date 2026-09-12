"""Scalping (2026-09-12): la entrada lógica abre una ventana, la salida la
cierra, y dentro cada flanco del gatillo es una operación.

Lo que se comprueba, en este orden:
  1. REGLA Nº1: sin el bloque, `compile_strategy_def` y `translate_strategy`
     devuelven exactamente lo de siempre (misma señal, mismos reentries, sin
     pausa). Un bloque sin condiciones cuenta como ausente.
  2. La ventana: se abre con la entrada, se cierra con la salida, se reabre.
  3. Las entradas del scalping son «gatillo dentro de la ventana», respetan
     la ventana horaria de entradas y pisan la salida por tiempo y las
     reentradas.
  4. La pausa entre operaciones en el simulador, y que `sim_dispatch` la
     desvía del kernel JIT (con `BACKTEST_NUMBA_SIM=1` da lo mismo que el
     motor Python).
  5. El esquema conserva el bloque (la capa 2 de las tres listas blancas).
  6. `run_backtest` entero por el camino secuencial: una estrategia normal
     hace 1 operación por día y la misma con scalping hace varias.
"""
import numpy as np
import pandas as pd
import pytest

from app.services import sim_dispatch
from app.services.portfolio_sim import simulate
from app.services.strategy_engine import (
    aplicar_scalping, compile_strategy_def, scalping_tp_time_limit,
    translate_strategy, ventana_scalping,
)


# ── Un día sintético en el que se sabe qué vela cumple qué ─────────────────

def _frame(n=60, inicio="2026-09-10 09:30"):
    """Precio que sube 1 % por vela: `Bar Close > umbral` se cumple a partir
    de una vela concreta y ya no deja de cumplirse."""
    ts = pd.date_range(inicio, periods=n, freq="1min")
    close = 1.0 * (1.01 ** np.arange(n))
    return pd.DataFrame({
        "timestamp": ts, "open": close, "high": close * 1.002,
        "low": close * 0.998, "close": close, "volume": np.full(n, 100000.0),
    })


def _cond_close_mayor(umbral):
    return {"type": "indicator_comparison",
            "source": {"name": "Bar Close", "offset": 0},
            "comparator": "GREATER_THAN", "target": float(umbral), "timeframe": "1m"}


def _cond_close_menor(umbral):
    return {"type": "indicator_comparison",
            "source": {"name": "Bar Close", "offset": 0},
            "comparator": "LESS_THAN", "target": float(umbral), "timeframe": "1m"}


def _grupo(*conds):
    return {"type": "group", "operator": "AND", "conditions": list(conds)}


def _definicion(scalping=None, entry=None, exit_=None, ventana_horaria=None):
    d = {
        "bias": "long",
        "entry_logic": {"timeframe": "1m",
                        "root_condition": entry if entry is not None else _grupo(_cond_close_mayor(1.10)),
                        **({"entry_time_windows": ventana_horaria} if ventana_horaria else {})},
        "exit_logic": {"timeframe": "1m",
                       "root_condition": exit_ if exit_ is not None else _grupo(_cond_close_mayor(1.40))},
        "risk_management": {"size_by_sl": False, "use_hard_stop": True,
                            "hard_stop": {"type": "Percentage", "value": 50},
                            "use_take_profit": True, "take_profit_mode": "Full",
                            "take_profit": {"type": "Time", "value": 30}},
    }
    if scalping is not None:
        d["scalping"] = scalping
    return d


# El gatillo «Bar Close > 1.20» se cumple desde la vela ~19 hasta el final;
# es un solo flanco. Para tener VARIOS flancos se usa el cruce de una media:
# `Bar Close > SMA(3)` en un precio que sube siempre es verdadero siempre, así
# que el gatillo con flancos se construye con las velas rojas/verdes de un
# precio en zigzag (ver _frame_zigzag).

def _frame_zigzag(n=60, inicio="2026-09-10 09:30"):
    """Sube 3 velas, baja 1, sube 3, baja 1... Tendencia alcista con retrocesos
    periódicos: `Bar Close > Bar Close[1]` se enciende y se apaga cada 4 velas."""
    ts = pd.date_range(inicio, periods=n, freq="1min")
    pasos = np.where(np.arange(n) % 4 == 3, -0.01, 0.01)
    close = 1.0 + np.cumsum(pasos)
    return pd.DataFrame({
        "timestamp": ts, "open": close, "high": close + 0.002,
        "low": close - 0.002, "close": close, "volume": np.full(n, 100000.0),
    })


def _gatillo_vela_verde():
    return _grupo({"type": "indicator_comparison",
                   "source": {"name": "Bar Close", "offset": 0},
                   "comparator": "GREATER_THAN",
                   "target": {"name": "Bar Close", "offset": 1}, "timeframe": "1m"})


# ── 1. Regla nº1 ───────────────────────────────────────────────────────────

class TestReglaNumeroUno:
    def test_sin_bloque_compila_a_none(self):
        c = compile_strategy_def(_definicion())
        assert c["scalping"] is None
        assert not c["_indicator_plan"].get("has_special")

    def test_bloque_sin_condiciones_es_como_no_tenerlo(self):
        c = compile_strategy_def(_definicion(scalping={
            "timeframe": "1m", "root_condition": _grupo(), "max_minutes": 5, "cooldown_bars": 2}))
        assert c["scalping"] is None
        assert not c["_indicator_plan"].get("has_special")

    def test_translate_sin_bloque_no_cambia(self):
        df = _frame()
        d = _definicion()
        s = translate_strategy(df, d, {}, compiled=compile_strategy_def(d))
        # Entradas: la entrada lógica tal cual, sin ventana ni gatillo.
        esperado = (df["close"] > 1.10).values
        assert np.array_equal(s["entries"].values, esperado)
        assert s["tp_time_limit"] == 30.0
        assert s["accept_reentries"] is False
        assert s["max_reentries"] == 0
        assert s["reentry_cooldown_bars"] == 0

    def test_tp_time_limit_sin_scalping_no_se_toca(self):
        assert scalping_tp_time_limit(None, 30.0) == 30.0
        assert scalping_tp_time_limit({"scalping": None}, "HOUR:15:30") == "HOUR:15:30"
        assert scalping_tp_time_limit({"scalping": {"max_minutes": 0}}, 12.0) == 12.0

    def test_simulate_sin_pausa_es_identico(self):
        n = 10
        close = np.array([100.0] * n); high = close + 1; low = close - 1
        entries = np.array([0, 1, 0, 1, 0, 1, 0, 1, 0, 0], dtype=bool)
        exits = np.array([0, 0, 1, 0, 1, 0, 1, 0, 1, 0], dtype=bool)
        kw = dict(close=close, open_=close, high=high, low=low, entries=entries, exits=exits,
                  direction="longonly", init_cash=10000.0, risk_r=100.0, risk_type="FIXED",
                  accumulate=True, max_reentries=-1)
        a = simulate(**kw)
        b = simulate(**kw, reentry_cooldown_bars=0)
        assert a["trades"] == b["trades"]
        assert np.array_equal(a["equity"], b["equity"])


# ── 2. La ventana ──────────────────────────────────────────────────────────

class TestVentana:
    def test_abre_con_entrada_cierra_con_salida(self):
        e = np.array([0, 0, 1, 0, 0, 0, 0, 0], dtype=bool)
        x = np.array([0, 0, 0, 0, 0, 1, 0, 0], dtype=bool)
        v = ventana_scalping(e, x)
        assert v.tolist() == [False, False, True, True, True, False, False, False]

    def test_se_reabre_si_la_entrada_vuelve(self):
        e = np.array([1, 0, 0, 1, 0, 0], dtype=bool)
        x = np.array([0, 1, 0, 0, 0, 1], dtype=bool)
        v = ventana_scalping(e, x)
        assert v.tolist() == [True, False, False, True, True, False]

    def test_salida_y_entrada_en_la_misma_vela_gana_la_salida(self):
        e = np.array([1, 1, 0], dtype=bool)
        x = np.array([0, 1, 0], dtype=bool)
        assert ventana_scalping(e, x).tolist() == [True, False, False]

    def test_sin_salida_la_ventana_dura_hasta_el_final(self):
        e = np.array([0, 1, 0, 0], dtype=bool)
        x = np.zeros(4, dtype=bool)
        assert ventana_scalping(e, x).tolist() == [False, True, True, True]

    def test_aplicar_scalping_respeta_ventana_horaria(self):
        e = np.array([1, 0, 0, 0, 0], dtype=bool)
        x = np.zeros(5, dtype=bool)
        g = np.array([1, 1, 1, 1, 1], dtype=bool)
        mask = np.array([1, 1, 0, 0, 1], dtype=bool)
        assert aplicar_scalping(e, x, g, mask).tolist() == [True, True, False, False, True]
        assert aplicar_scalping(e, x, g).tolist() == [True] * 5


# ── 3. translate_strategy con el bloque ────────────────────────────────────

class TestTranslate:
    def test_entradas_son_gatillo_dentro_de_la_ventana(self):
        df = _frame_zigzag()
        close = df["close"].values
        # Ventana: abre cuando close > 1.10, cierra cuando close > 1.20.
        d = _definicion(
            entry=_grupo(_cond_close_mayor(1.10)), exit_=_grupo(_cond_close_mayor(1.20)),
            scalping={"timeframe": "1m", "root_condition": _gatillo_vela_verde(),
                      "max_minutes": 4, "cooldown_bars": 2})
        s = translate_strategy(df, d, {}, compiled=compile_strategy_def(d))
        entradas = s["entries"].values
        verde = np.zeros(len(df), dtype=bool)
        verde[1:] = close[1:] > close[:-1]
        ventana = ventana_scalping(close > 1.10, close > 1.20)
        assert np.array_equal(entradas, ventana & verde)
        # Hay varias entradas (varios flancos), no una.
        flancos = int(np.sum(entradas[1:] & ~entradas[:-1]) + int(entradas[0]))
        assert flancos >= 3
        # Ninguna fuera de la ventana.
        assert not np.any(entradas & ~ventana)
        # Lo que pisa: salida por tiempo, reentradas ilimitadas, pausa.
        assert s["tp_time_limit"] == 4.0
        assert s["accept_reentries"] is True
        assert s["max_reentries"] == -1
        assert s["reentry_cooldown_bars"] == 2
        # Las salidas son las de siempre.
        assert np.array_equal(s["exits"].values, close > 1.20)

    def test_sin_max_minutes_manda_el_take_profit_por_tiempo(self):
        df = _frame_zigzag()
        d = _definicion(scalping={"timeframe": "1m", "root_condition": _gatillo_vela_verde(),
                                  "max_minutes": 0, "cooldown_bars": 0})
        s = translate_strategy(df, d, {}, compiled=compile_strategy_def(d))
        assert s["tp_time_limit"] == 30.0
        assert s["reentry_cooldown_bars"] == 0

    def test_ventana_horaria_de_entradas_vale_para_cada_operacion(self):
        df = _frame_zigzag()
        d = _definicion(
            entry=_grupo(_cond_close_mayor(0.0)), exit_=_grupo(),
            ventana_horaria=[{"from_time": "09:30", "to_time": "09:45"}],
            scalping={"timeframe": "1m", "root_condition": _gatillo_vela_verde(),
                      "max_minutes": 3, "cooldown_bars": 0})
        s = translate_strategy(df, d, {}, compiled=compile_strategy_def(d))
        minutos = df["timestamp"].dt.hour * 60 + df["timestamp"].dt.minute
        fuera = (minutos > 9 * 60 + 45).values
        assert not np.any(s["entries"].values & fuera)
        assert np.any(s["entries"].values)

    def test_capital_por_entrada_escala_el_riesgo(self):
        df = _frame_zigzag()
        d = _definicion(scalping={"timeframe": "1m", "root_condition": _gatillo_vela_verde(),
                                  "max_minutes": 3, "cooldown_bars": 0, "capital_pct": 10})
        s = translate_strategy(df, d, {}, compiled=compile_strategy_def(d))
        assert s["risk_scale"] == pytest.approx(0.10)
        # Sin capital_pct → la cifra entera; sin scalping → 1.0 también.
        d2 = _definicion(scalping={"timeframe": "1m", "root_condition": _gatillo_vela_verde()})
        assert translate_strategy(df, d2, {}, compiled=compile_strategy_def(d2))["risk_scale"] == 1.0
        d3 = _definicion()
        assert translate_strategy(df, d3, {}, compiled=compile_strategy_def(d3))["risk_scale"] == 1.0
        # Un 0 o un valor no numérico no anulan el tamaño: vuelven al 100 %.
        d4 = _definicion(scalping={"timeframe": "1m", "root_condition": _gatillo_vela_verde(), "capital_pct": 0})
        assert compile_strategy_def(d4)["scalping"]["capital_frac"] == 1.0

    def test_valores_raros_no_rompen(self):
        d = _definicion(scalping={"timeframe": "1m", "root_condition": _gatillo_vela_verde(),
                                  "max_minutes": "abc", "cooldown_bars": None})
        c = compile_strategy_def(d)
        assert c["scalping"]["max_minutes"] == 0.0
        assert c["scalping"]["cooldown_bars"] == 0


# ── 4. La pausa en el simulador y el despachador ───────────────────────────

def _kw_pausa():
    n = 12
    close = np.array([100.0] * n); high = close + 0.5; low = close - 0.5
    # Entradas en 1,3,5,7,9; salidas por señal en 2,4,6,8,10 (se ejecutan en
    # la apertura de la vela siguiente: exit_idx = 3,5,7,9,11).
    entries = np.array([0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 0], dtype=bool)
    exits = np.array([0, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0], dtype=bool)
    return dict(close=close, open_=close, high=high, low=low, entries=entries, exits=exits,
                direction="longonly", init_cash=10000.0, risk_r=100.0, risk_type="FIXED",
                accumulate=True, max_reentries=-1)


class TestPausa:
    def test_sin_pausa_cinco_operaciones(self):
        assert len(simulate(**_kw_pausa())["trades"]) == 5

    def test_con_pausa_se_pierden_las_senales_que_caen_dentro(self):
        # Con pausa de 2: tras salir en la 3 (fill), la señal de la 3 se
        # consume (3-3 < 2) y no se puede entrar hasta la 5 → entra en 5,
        # sale en 7, la señal de la 7 cae dentro, entra en 9, sale en 11.
        res = simulate(**_kw_pausa(), reentry_cooldown_bars=2)
        assert [t["entry_idx"] for t in res["trades"]] == [2, 6, 10]

    def test_pausa_grande_deja_una(self):
        res = simulate(**_kw_pausa(), reentry_cooldown_bars=50)
        assert len(res["trades"]) == 1

    def test_dispatch_desvia_del_jit(self, monkeypatch):
        monkeypatch.setenv("BACKTEST_NUMBA_SIM", "1")
        kw = _kw_pausa()
        con_jit = sim_dispatch.simulate(**kw, reentry_cooldown_bars=2)
        python = simulate(**kw, reentry_cooldown_bars=2)
        assert con_jit["trades"] == python["trades"]
        assert len(con_jit["trades"]) == 3

    def test_dispatch_con_cero_no_rompe_el_jit(self, monkeypatch):
        # Con 0 el kwarg se retira y el kernel ni lo ve: no puede fallar con
        # «unexpected keyword argument».
        monkeypatch.setenv("BACKTEST_NUMBA_SIM", "1")
        kw = _kw_pausa()
        res = sim_dispatch.simulate(**kw, reentry_cooldown_bars=0)
        assert len(res["trades"]) == 5


# ── 5. El esquema conserva el bloque ───────────────────────────────────────

def test_esquema_conserva_scalping():
    from app.schemas.strategy import StrategyCreate
    d = _definicion(scalping={"timeframe": "1m", "root_condition": _gatillo_vela_verde(),
                              "max_minutes": 5, "cooldown_bars": 1})
    s = StrategyCreate(name="x", **d)
    assert s.scalping == d["scalping"]
    s2 = StrategyCreate(name="x", **_definicion())
    assert s2.scalping is None


# ── 6. run_backtest entero por el camino secuencial ────────────────────────

def _dia(ticker, date, n=120):
    ts = pd.date_range(f"{date} 09:30", periods=n, freq="1min")
    pasos = np.where(np.arange(n) % 4 == 3, -0.01, 0.01)
    close = 1.0 + np.cumsum(pasos)
    return pd.DataFrame({
        "ticker": ticker, "date": date, "timestamp": ts,
        "open": close, "high": close + 0.002, "low": close - 0.002, "close": close,
        "volume": np.full(n, 100000.0),
    })


def _stream(dias):
    for d in dias:
        yield (d["date"].iloc[0], d["ticker"].iloc[0]), d


def _run(strategy_def, monkeypatch):
    from app.services.backtest_service import run_backtest
    monkeypatch.delenv("BTT_SLAB_STREAM_ENABLED", raising=False)
    monkeypatch.delenv("BACKTEST_PARALLEL_WORKERS", raising=False)
    monkeypatch.setenv("BACKTEST_NUMBA_SIM", "0")
    dias = [_dia("AAA", "2026-09-10"), _dia("BBB", "2026-09-11")]
    qual = pd.DataFrame([{"ticker": "AAA", "date": "2026-09-10", "prev_close": 1.0, "gap_pct": 50.0},
                         {"ticker": "BBB", "date": "2026-09-11", "prev_close": 1.0, "gap_pct": 50.0}])
    return run_backtest(
        qualifying_df=qual, strategy_def=strategy_def,
        init_cash=10000.0, risk_r=100.0, risk_type="FIXED",
        market_sessions=["rth"],
        day_group_iter=_stream(dias), n_groups_hint=2,
    )


def test_run_backtest_normal_vs_scalping(monkeypatch):
    base = _definicion(entry=_grupo(_cond_close_mayor(1.05)), exit_=_grupo(_cond_close_mayor(1.30)))
    normal = _run(base, monkeypatch)
    # Sin reentradas: una operación por día, cerrada por tiempo (30 min) o por salida.
    assert len(normal["trades"]) == 2

    con_scalp = dict(base, scalping={
        "timeframe": "1m", "root_condition": _gatillo_vela_verde(),
        "max_minutes": 2, "cooldown_bars": 1})
    scalp = _run(con_scalp, monkeypatch)
    # Varias operaciones por día, todas dentro de la ventana [close>1.05, close>1.30).
    assert len(scalp["trades"]) > 2 * 3
    for t in scalp["trades"]:
        assert t["ticker"] in ("AAA", "BBB")
    # Y ninguna dura más de la salida por tiempo (2 min → fill en la 3ª vela
    # como mucho, contando la vela de entrada).
    for t in scalp["trades"]:
        assert t["exit_idx"] - t["entry_idx"] <= 3

    # Capital por entrada: con el 10 % de la cifra del panel (100 $ fijos por
    # valor de mercado) cada scalp mueve un 10 % de las acciones.
    con_capital = dict(con_scalp, scalping=dict(con_scalp["scalping"], capital_pct=10))
    diez = _run(con_capital, monkeypatch)
    assert len(diez["trades"]) == len(scalp["trades"])
    for a, b in zip(scalp["trades"], diez["trades"]):
        assert a["entry_idx"] == b["entry_idx"]
        assert b["size"] == pytest.approx(a["size"] * 0.10, rel=1e-6)
