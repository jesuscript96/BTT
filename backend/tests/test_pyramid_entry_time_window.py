"""Las PIRÁMIDES respetan `entry_time_windows`. Un añadido es una entrada.

EL BUG (2026-09-03, visto en vivo). `entry_time_windows` se aplicaba solo a
`entries`; `_evaluate_pyramid_levels` no la miraba. Resultado: con la ventana de
entradas cerrada a las 08:00, GELS piramidó a las 08:08 ET — en el bot de
alertas Y en el backtest, porque los dos usan el mismo motor.

No es una diferencia teórica: el añadido mete acciones de verdad, y hacerlo
fuera de la ventana que el usuario definió cambia el riesgo de la posición y
los resultados de cualquier backtest con piramidación.
"""
import numpy as np
import pandas as pd

from app.services.strategy_engine import compile_strategy_def, translate_strategy


def _frame(n=300, inicio="2026-09-03 04:00"):
    """Un día de premercado minuto a minuto, subiendo despacio.

    300 minutos = 04:00-08:59. TIENE que pasar de las 08:00: con 240 el frame
    se acababa justo en el borde de la ventana y el test pasaba por vacuidad,
    sin una sola vela fuera que comprobar.
    """
    ts = pd.date_range(inicio, periods=n, freq="1min")
    close = np.linspace(1.0, 2.0, n)
    return pd.DataFrame({
        "timestamp": ts, "open": close, "high": close * 1.01,
        "low": close * 0.99, "close": close, "volume": np.full(n, 100000.0),
    })


def _definicion(ventana_entradas):
    """1 condición que se cumple SIEMPRE, en la entrada y en la pirámide.

    Así lo único que puede apagar una señal es la ventana horaria, que es
    justo lo que se quiere medir.
    """
    siempre = {
        "type": "group", "operator": "AND",
        "conditions": [{
            "type": "indicator_comparison",
            "source": {"name": "Bar Close", "offset": 0},
            "comparator": "GREATER_THAN", "target": 0.0, "timeframe": "1m",
        }],
    }
    return {
        "bias": "long", "market_sessions": ["custom"],
        "custom_start_time": "04:00", "custom_end_time": "09:00",
        "entry_logic": {
            "timeframe": "1m", "root_condition": siempre,
            "entry_time_windows": ventana_entradas,
        },
        "exit_logic": {"timeframe": "1m",
                       "root_condition": {"type": "group", "operator": "AND", "conditions": []}},
        "risk_management": {"size_by_sl": False, "use_hard_stop": False},
        "pyramiding": {
            "timeframe": "1m", "mode": "individual",
            "levels": [{"times": 1, "root_condition": siempre,
                        "action": "add", "unit": "usd", "capital_pct": 300}],
        },
    }


def _senales(ventana_entradas):
    d = _definicion(ventana_entradas)
    frame = _frame()
    s = translate_strategy(frame, d, {}, compiled=compile_strategy_def(d))
    minutos = pd.to_datetime(frame["timestamp"]).dt.hour * 60 + \
        pd.to_datetime(frame["timestamp"]).dt.minute
    return s, minutos.values


def test_la_piramide_no_dispara_fuera_de_la_ventana_de_entradas():
    """EL BUG. Con la ventana hasta las 08:00, nada de pirámide a las 08:08."""
    s, minutos = _senales([{"from_time": "04:00", "to_time": "08:00"}])
    niveles = s.get("pyramid_levels") or []
    assert niveles, "la estrategia define un nivel de pirámide"

    sig = np.asarray(niveles[0]["signals"], dtype=bool)
    fuera = sig & (minutos > 8 * 60)
    assert not fuera.any(), (
        f"{int(fuera.sum())} señales de pirámide después de las 08:00, "
        f"la primera a las {int(minutos[fuera.argmax()]) // 60:02d}:"
        f"{int(minutos[fuera.argmax()]) % 60:02d}"
    )


def test_dentro_de_la_ventana_la_piramide_sigue_disparando():
    """El arreglo no puede apagar las pirámides legítimas."""
    s, minutos = _senales([{"from_time": "04:00", "to_time": "08:00"}])
    sig = np.asarray((s.get("pyramid_levels") or [])[0]["signals"], dtype=bool)
    assert (sig & (minutos <= 8 * 60)).any(), "no queda ni una señal dentro"


def test_sin_ventana_declarada_la_piramide_no_se_toca():
    """Regla nº1: una definición sin `entry_time_windows` se comporta igual."""
    s, minutos = _senales([])
    sig = np.asarray((s.get("pyramid_levels") or [])[0]["signals"], dtype=bool)
    assert sig.all(), "sin ventana horaria la condición se cumple en todas"


def test_la_entrada_ya_respetaba_la_ventana(  ):
    """Control: si esto falla, el fallo es de la ventana, no de la pirámide."""
    s, minutos = _senales([{"from_time": "04:00", "to_time": "08:00"}])
    entradas = np.asarray(s["entries"], dtype=bool)
    assert not (entradas & (minutos > 8 * 60)).any()
