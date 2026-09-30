"""FRANJA HORARIA PROPIA POR NIVEL DE PIRÁMIDE (2026-09-30).

El caso que lo motiva (Álvaro, 1B «aguantar RTH»): la estrategia ENTRA en
premercado (horas de entrada 04:00-08:00) y aguanta hasta RTH, y se quiere
piramidar SOLO en RTH. Hasta hoy un añadido era siempre una entrada y
respetaba las horas de entrada: con 04:00-08:00, ninguna pirámide podía
dispararse después de las 08:00.

Con `pyramiding.levels[].time_windows` el nivel usa SU franja EN LUGAR de las
horas de entrada (no la intersección, que haría imposible el caso). Gated por
PYRAMID_LEVEL_WINDOWS_ENABLED (apagado por defecto): sin el flag, todo igual.
"""
import numpy as np
import pandas as pd
import pytest

from app.services.strategy_engine import (
    aplica_ventana_relleno_nivel,
    compile_strategy_def,
    normaliza_ventanas_nivel,
    translate_strategy,
)

SIEMPRE = {
    "type": "group", "operator": "AND",
    "conditions": [{
        "type": "indicator_comparison",
        "source": {"name": "Bar Close", "offset": 0},
        "comparator": "GREATER_THAN", "target": 0.0, "timeframe": "1m",
    }],
}
PM = [{"from_time": "04:00", "to_time": "08:00"}]
RTH = [{"from_time": "09:30", "to_time": "11:00"}]


def _frame(n=480, inicio="2026-09-03 04:00"):
    """04:00-11:59 minuto a minuto: cubre premercado, el hueco y RTH."""
    ts = pd.date_range(inicio, periods=n, freq="1min")
    close = np.linspace(1.0, 2.0, n)
    return pd.DataFrame({
        "timestamp": ts, "open": close, "high": close * 1.01,
        "low": close * 0.99, "close": close, "volume": np.full(n, 100000.0),
    })


def _nivel(ventanas=None):
    lv = {"times": 1, "root_condition": SIEMPRE,
          "action": "add", "unit": "usd", "capital_pct": 300}
    if ventanas is not None:
        lv["time_windows"] = ventanas
    return lv


def _definicion(ventana_entradas, niveles):
    return {
        "bias": "long", "market_sessions": ["custom"],
        "custom_start_time": "04:00", "custom_end_time": "12:00",
        "entry_logic": {"timeframe": "1m", "root_condition": SIEMPRE,
                        "entry_time_windows": ventana_entradas},
        "exit_logic": {"timeframe": "1m",
                       "root_condition": {"type": "group", "operator": "AND", "conditions": []}},
        "risk_management": {"size_by_sl": False, "use_hard_stop": False},
        "pyramiding": {"timeframe": "1m", "mode": "individual", "levels": niveles},
    }


def _senales(d):
    frame = _frame()
    s = translate_strategy(frame, d, {}, compiled=compile_strategy_def(d))
    ts = pd.to_datetime(frame["timestamp"])
    return s, (ts.dt.hour * 60 + ts.dt.minute).values


def _dentro(minutos, ventanas):
    m = np.zeros(len(minutos), dtype=bool)
    for v in ventanas:
        h0, m0 = map(int, v["from_time"].split(":"))
        h1, m1 = map(int, v["to_time"].split(":"))
        m |= (minutos >= h0 * 60 + m0) & (minutos <= h1 * 60 + m1)
    return m


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setenv("PYRAMID_LEVEL_WINDOWS_ENABLED", "true")


@pytest.fixture
def flag_off(monkeypatch):
    monkeypatch.delenv("PYRAMID_LEVEL_WINDOWS_ENABLED", raising=False)


# ── El caso de uso ────────────────────────────────────────────────────────

def test_entra_en_premercado_y_piramida_solo_en_rth(flag_on):
    s, minutos = _senales(_definicion(PM, [_nivel(RTH)]))
    entradas = np.asarray(s["entries"], dtype=bool)
    sig = np.asarray(s["pyramid_levels"][0]["signals"], dtype=bool)

    assert entradas.any() and not (entradas & ~_dentro(minutos, PM)).any(), \
        "la entrada sigue en sus horas de entrada"
    assert sig.any(), "la pirámide tiene que poder disparar en RTH"
    assert not (sig & ~_dentro(minutos, RTH)).any(), "pirámide fuera de su franja"
    assert (sig == _dentro(minutos, RTH)).all(), "franja propia EN LUGAR de las horas de entrada"


def test_la_franja_viaja_en_el_nivel_para_la_vela_de_relleno(flag_on):
    s, _ = _senales(_definicion(PM, [_nivel(RTH)]))
    assert s["pyramid_levels"][0]["time_windows"] == RTH


def test_un_nivel_sin_franja_sigue_las_horas_de_entrada_y_no_hereda_la_del_otro(flag_on):
    """La máscara de un nivel con franja NO se arrastra al siguiente."""
    s, minutos = _senales(_definicion(PM, [_nivel(RTH), _nivel()]))
    con = np.asarray(s["pyramid_levels"][0]["signals"], dtype=bool)
    sin = np.asarray(s["pyramid_levels"][1]["signals"], dtype=bool)
    assert (con == _dentro(minutos, RTH)).all()
    assert (sin == _dentro(minutos, PM)).all()
    assert "time_windows" not in s["pyramid_levels"][1]


def test_franja_propia_sin_horas_de_entrada_en_la_estrategia(flag_on):
    s, minutos = _senales(_definicion([], [_nivel(RTH)]))
    sig = np.asarray(s["pyramid_levels"][0]["signals"], dtype=bool)
    assert (sig == _dentro(minutos, RTH)).all()


def test_nivel_camino_aplica_la_franja_a_cada_paso(flag_on):
    lv = {"times": 1, "steps": [SIEMPRE, SIEMPRE], "same_bar": True,
          "action": "add", "unit": "usd", "capital_pct": 300,
          "time_windows": RTH}
    s, minutos = _senales(_definicion(PM, [lv]))
    for paso in s["pyramid_levels"][0]["steps_signals"]:
        assert (np.asarray(paso, dtype=bool) == _dentro(minutos, RTH)).all()


# ── Vela de relleno ───────────────────────────────────────────────────────

def test_relleno_usa_la_franja_del_nivel_y_no_la_de_entrada():
    minutos = np.arange(9 * 60, 12 * 60)          # 09:00-11:59
    lv = {"signals": np.ones(len(minutos), dtype=bool), "time_windows": RTH}
    out = aplica_ventana_relleno_nivel(lv, minutos, PM, look_ahead_prevention=True)
    sig = np.asarray(out["signals"], dtype=bool)
    # 09:30 a 10:59 (la señal de las 11:00 rellenaría a las 11:01, fuera).
    esperado = (minutos >= 9 * 60 + 30) & (minutos <= 10 * 60 + 59)
    assert (sig == esperado).all()


def test_relleno_sin_franja_de_nivel_sigue_como_siempre():
    minutos = np.arange(4 * 60, 9 * 60)
    lv = {"signals": np.ones(len(minutos), dtype=bool)}
    out = aplica_ventana_relleno_nivel(lv, minutos, PM, look_ahead_prevention=True)
    esperado = (minutos >= 4 * 60) & (minutos <= 7 * 60 + 59)
    assert (np.asarray(out["signals"], dtype=bool) == esperado).all()


# ── Regla nº1: sin clave o sin flag, nada cambia ──────────────────────────

def test_sin_flag_la_franja_se_ignora_y_el_compilado_es_identico(flag_off):
    con = compile_strategy_def(_definicion(PM, [_nivel(RTH)]))
    sin = compile_strategy_def(_definicion(PM, [_nivel()]))
    assert con["pyramid_levels_def"] == sin["pyramid_levels_def"]
    s, minutos = _senales(_definicion(PM, [_nivel(RTH)]))
    sig = np.asarray(s["pyramid_levels"][0]["signals"], dtype=bool)
    assert (sig == _dentro(minutos, PM)).all(), "sin flag, manda la hora de entrada"


def test_con_flag_pero_sin_clave_el_nivel_compilado_no_cambia(flag_on, monkeypatch):
    con_flag = compile_strategy_def(_definicion(PM, [_nivel()]))["pyramid_levels_def"]
    monkeypatch.delenv("PYRAMID_LEVEL_WINDOWS_ENABLED", raising=False)
    sin_flag = compile_strategy_def(_definicion(PM, [_nivel()]))["pyramid_levels_def"]
    assert con_flag == sin_flag
    assert "time_windows" not in con_flag[0]


def test_lista_vacia_equivale_a_no_declarar_franja(flag_on):
    vacia = compile_strategy_def(_definicion(PM, [_nivel([])]))["pyramid_levels_def"]
    sin = compile_strategy_def(_definicion(PM, [_nivel()]))["pyramid_levels_def"]
    assert vacia == sin


# ── Validación (compilador y guardado) ────────────────────────────────────

@pytest.mark.parametrize("malo", [
    "09:30-11:00",
    [{"from_time": "09:30"}],
    [{"from_time": "9h30", "to_time": "11:00"}],
    [{"from_time": "25:00", "to_time": "26:00"}],
    [{"from_time": "11:00", "to_time": "09:30"}],
    ["09:30"],
])
def test_franjas_invalidas_revientan(malo):
    with pytest.raises(ValueError):
        normaliza_ventanas_nivel(malo)


def test_normaliza_rellena_con_ceros():
    assert normaliza_ventanas_nivel([{"from_time": "9:30", "to_time": "11:0"}]) == \
        [{"from_time": "09:30", "to_time": "11:00"}]


def test_el_compilador_revienta_con_franja_invalida_si_el_flag_esta_on(flag_on):
    with pytest.raises(ValueError, match="time_windows"):
        compile_strategy_def(_definicion(PM, [_nivel([{"from_time": "11:00", "to_time": "09:30"}])]))


def test_el_schema_rebota_una_franja_invalida_al_guardar():
    from pydantic import ValidationError
    from app.schemas.strategy import StrategyCreate
    d = _definicion(PM, [_nivel([{"from_time": "11:00", "to_time": "09:30"}])])
    d["name"] = "x"
    d["risk_management"] = {}
    with pytest.raises(ValidationError, match="time_windows"):
        StrategyCreate(**d)
