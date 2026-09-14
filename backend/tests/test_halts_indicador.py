"""Indicadores «Halt Down» / «Halt Up» (12-sep-2026). Ver halts.serie_halts_direccion.

  - Contador acumulado por dia: sube en la vela de entrada al halt segun sea
    bajista (Down) o alcista (Up); un doji no cuenta en ninguno.
  - Sin fichero del dia, sin ticker o sin fecha: ceros (nunca error).
  - Pasa por `compute_indicator` con `daily_stats` (ticker + date) y por
    `translate_strategy`: una condicion «Halt Down >= 1» da UNA senal de
    entrada en la vela del primer halt bajista (flanco), no una por vela.
"""
import numpy as np
import pandas as pd
import pytest

from app.services import halts as H
from app.services.indicators import compute_indicator
from app.services.strategy_engine import translate_strategy


def _dia(n=30, date="2025-09-01"):
    ts = pd.date_range(f"{date} 09:30", periods=n, freq="1min")
    o = np.full(n, 1.0); c = np.full(n, 1.0)
    return pd.DataFrame({"timestamp": ts, "open": o, "high": o * 1.01, "low": o * 0.99,
                         "close": c, "volume": np.full(n, 1000.0)})


def _tabla(directorio, date, filas):
    directorio.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(filas, columns=["instrument_id", "date", "halt_ts", "resume_ts", "reason",
                                      "ssr", "symbol", "minutos", "motivo"])
    df.to_parquet(directorio / f"{date}.parquet", index=False)


@pytest.fixture
def tabla(tmp_path, monkeypatch):
    d = tmp_path / "dias"
    _tabla(d, "2025-09-01", [
        (1, "2025-09-01", pd.Timestamp("2025-09-01 09:35:20"), pd.Timestamp("2025-09-01 09:41"), 50, "N", "XHG", 5.0, "LULD"),
        (1, "2025-09-01", pd.Timestamp("2025-09-01 09:50:05"), pd.Timestamp("2025-09-01 09:56"), 50, "N", "XHG", 5.0, "LULD"),
        (1, "2025-09-01", pd.Timestamp("2025-09-01 09:52:00"), pd.NaT, 70, "N", "XHG", None, "T12"),
        (2, "2025-09-01", pd.Timestamp("2025-09-01 09:40:00"), pd.Timestamp("2025-09-01 09:45"), 50, "N", "OTRO", 5.0, "LULD"),
    ])
    monkeypatch.setenv("HALTS_DIR", str(d))
    H._cache_dias.clear()
    yield d
    H._cache_dias.clear()


def test_contador_down_up_por_vela(tabla):
    df = _dia()
    # Vela 5 (09:35) bajista -> halt 1 cuenta en Down. Vela 20 (09:50) alcista
    # -> halt 2 cuenta en Up. Vela 22 (09:52) doji -> halt 3 no cuenta.
    df.loc[5, "close"] = 0.9
    df.loc[20, "close"] = 1.1
    down = H.serie_halts_direccion(df["open"], df["close"], df["timestamp"], "XHG", "2025-09-01", "down")
    up = H.serie_halts_direccion(df["open"], df["close"], df["timestamp"], "XHG", "2025-09-01", "up")
    assert list(down.values[:5]) == [0] * 5 and down.iloc[5] == 1 and down.iloc[-1] == 1
    assert up.iloc[19] == 0 and up.iloc[20] == 1 and up.iloc[-1] == 1
    assert down.iloc[22] == 1 and up.iloc[22] == 1        # el doji no suma
    # Otro ticker: solo su halt. Ticker sin halts: ceros.
    assert H.serie_halts_direccion(df["open"], df["close"], df["timestamp"], "OTRO", "2025-09-01", "down").iloc[-1] == 0
    assert H.serie_halts_direccion(df["open"], df["close"], df["timestamp"], "ZZZ", "2025-09-01", "down").sum() == 0
    # Dia sin fichero, o sin ticker: ceros, sin error.
    assert H.serie_halts_direccion(df["open"], df["close"], df["timestamp"], "XHG", "2030-01-01", "down").sum() == 0
    assert H.serie_halts_direccion(df["open"], df["close"], df["timestamp"], None, "2025-09-01", "down").sum() == 0


def test_compute_indicator_y_alias(tabla):
    df = _dia()
    df.loc[5, "close"] = 0.9
    s = compute_indicator("Halt Down", df, daily_stats={"ticker": "XHG", "date": "2025-09-01"})
    assert len(s) == len(df) and s.iloc[5] == 1 and s.iloc[4] == 0
    s2 = compute_indicator("Halt Up", df, daily_stats={"ticker": "XHG", "date": "2025-09-01"})
    assert s2.sum() == 0
    # Sin daily_stats: ceros, no excepcion.
    assert compute_indicator("Halt Down", df).sum() == 0


def test_translate_strategy_dispara_en_el_flanco(tabla):
    df = _dia()
    df.loc[5, "close"] = 0.9
    df.loc[20, "close"] = 0.8      # segundo halt tambien bajista
    sdef = {
        "bias": "short", "apply_day": "gap_day",
        "entry_logic": {"timeframe": "1m", "root_condition": {"operator": "AND", "conditions": [
            {"type": "indicator_comparison", "timeframe": "1m",
             "source": {"name": "Halt Down"}, "comparator": "GREATER_THAN_OR_EQUAL", "target": 1},
        ]}},
        "risk_management": {"use_hard_stop": True, "hard_stop": {"type": "Percentage", "value": 10}},
    }
    sig = translate_strategy(df, sdef, {"ticker": "XHG", "date": "2025-09-01"})
    e = np.asarray(sig["entries"])
    # La condicion es verdad de la vela 5 en adelante; la senal (flanco) la
    # decide el simulador, pero `entries` marca todas las velas en que se
    # cumple: la primera es la 5.
    assert not e[:5].any() and e[5]
    sdef["entry_logic"]["root_condition"]["conditions"][0]["target"] = 2
    e2 = np.asarray(translate_strategy(df, sdef, {"ticker": "XHG", "date": "2025-09-01"})["entries"])
    assert not e2[:20].any() and e2[20]
