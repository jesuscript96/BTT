import pandas as pd
import numpy as np
from app.services.strategy_engine import translate_strategy, get_lowest_timeframe_mins
from app.services.backtest_service import run_backtest

def test_lowest_timeframe_helper():
    # Test M1
    logic_m1 = {
        "timeframe": "1m",
        "root_condition": {
            "operator": "AND",
            "conditions": []
        }
    }
    assert get_lowest_timeframe_mins(logic_m1) == 1

    # Test M5
    logic_m5 = {
        "timeframe": "5m",
        "root_condition": {
            "operator": "AND",
            "conditions": []
        }
    }
    assert get_lowest_timeframe_mins(logic_m5) == 5

    # Test Nested timeframes
    logic_nested = {
        "timeframe": "15m",
        "root_condition": {
            "operator": "AND",
            "conditions": [
                {
                    "type": "indicator_comparison",
                    "source": {"name": "Bar Close"},
                    "comparator": "GREATER_THAN",
                    "target": 10.0,
                    "timeframe": "5m"
                },
                {
                    "type": "indicator_comparison",
                    "source": {"name": "VWAP"},
                    "comparator": "GREATER_THAN",
                    "target": 9.0,
                    "timeframe": "1m"
                }
            ]
        }
    }
    assert get_lowest_timeframe_mins(logic_nested) == 1


def test_candle_delay_and_session_leakage():
    # Create a DataFrame spanning pre-market and regular hours
    # 09:28:00 to 09:35:00 (8 bars)
    timestamps = pd.date_range("2026-06-01 09:28:00", periods=8, freq="1min")
    
    # We set close = 10.5 only at 09:28 (index 0). All other bars close at 9.5.
    # Since vwap = 10.0, only the 09:28 bar satisfies "close > vwap".
    df = pd.DataFrame({
        "ticker": ["TEST"] * 8,
        "date": ["2026-06-01"] * 8,
        "timestamp": timestamps,
        "open": [10.0] * 8,
        "high": [11.0] * 8,
        "low": [9.0] * 8,
        "close": [10.5, 9.5, 9.5, 9.5, 9.5, 9.5, 9.5, 9.5],
        "volume": [1000] * 8,
        "vwap": [10.0] * 8,
    })

    # Strategy definition: close > vwap, bias long, SL/TP percent
    #
    # candle_delay = 3 -> la entrada se desplaza 3 BARRAS, o sea 09:28 + 3 = 09:31.
    #
    # ESTE COMENTARIO DECIA «(3 - 1) * 1 = 2 bars» Y EL ASSERT ESPERABA 09:30.
    # Era la fórmula vieja: el motor pasó a desplazar `candle_delay` barras
    # exactas y el test se quedó atrás, marcado en rojo desde entonces sin que
    # nada estuviera roto. Medido el 5-sep-2026 sobre esta misma serie:
    #
    #     candle_delay = 1  ->  entra 09:29     <- el ajuste que usa Jaume
    #     candle_delay = 2  ->  entra 09:30
    #     candle_delay = 3  ->  entra 09:31
    #
    # Con delay 1 se entra en la barra SIGUIENTE a la señal, que es lo correcto:
    # desplazar 0 sería operar la vela que aún se está formando. Los tres casos
    # se comprueban abajo en `test_candle_delay_formula`, para que la próxima
    # vez que la fórmula cambie falle diciendo cuánto ha cambiado.
    strategy_def = {
        "name": "Test Session Delay",
        "bias": "long",
        "entry_logic": {
            "timeframe": "1m",
            "candle_delay": 3,
            "root_condition": {
                "operator": "AND",
                "conditions": [
                    {
                        "type": "indicator_comparison",
                        "source": {"name": "Bar Close"},
                        "comparator": "GREATER_THAN",
                        "target": {"name": "VWAP"}
                    }
                ]
            }
        },
        "exit_logic": {
            "timeframe": "1m",
            "root_condition": {
                "operator": "AND",
                "conditions": [
                    {
                        "type": "indicator_comparison",
                        "source": {"name": "Bar Close"},
                        "comparator": "GREATER_THAN",
                        "target": {"name": "VWAP"}
                    }
                ]
            }
        },
        "risk_management": {
            "use_hard_stop": True,
            "hard_stop": {"type": "Percentage", "value": 5.0},
            "use_take_profit": True,
            "take_profit": {"type": "Percentage", "value": 10.0},
            "accept_reentries": False
        }
    }

    # Case 1: All sessions active ("all" or market_sessions is None/empty)
    # The signal at 09:28 shifts by 3 bars (candle_delay=3) and executes at 09:31.
    res_all_sessions = run_backtest(
        intraday_df=df.copy(),
        strategy_def=strategy_def,
        market_sessions=["all"],
        init_cash=10000.0,
    )
    assert len(res_all_sessions["trades"]) == 1
    entry_time = pd.to_datetime(res_all_sessions["trades"][0]["entry_time"])
    assert entry_time.time() == pd.Timestamp("09:31:00").time()

    # Case 2: Regular sessions only ("rth")
    # Since 09:28 is outside RTH, the signal at 09:28 should be discarded BEFORE shifting.
    # Therefore, no trade should execute.
    res_rth_only = run_backtest(
        intraday_df=df.copy(),
        strategy_def=strategy_def,
        market_sessions=["rth"],
        init_cash=10000.0,
    )
    assert len(res_rth_only["trades"]) == 0


def test_candle_delay_formula():
    """`candle_delay` = N desplaza la entrada EXACTAMENTE N barras.

    POR QUE ESTE TEST. El de arriba comprobaba un solo valor (3) y con la
    formula vieja `(N-1)`. Cuando la formula cambio a `N`, el test se puso en
    rojo y ahi se quedo meses, mezclado con otros cien fallos de configuracion:
    nadie sabia si el motor entraba tarde o si el test estaba caduco. Con los
    tres valores medidos, un cambio futuro dice EN CUANTO se ha movido, y ese
    es justo el dato que hay que mirar antes de dar por bueno un backtest.

    EL CASO QUE IMPORTA ES delay=1, el que usa Jaume: se entra en la barra
    SIGUIENTE a la senyal. Desplazar 0 seria operar la vela que aun se esta
    formando, o sea mirar el futuro.
    """
    ts = pd.date_range("2026-06-01 09:28:00", periods=8, freq="1min")
    df = pd.DataFrame({
        "ticker": ["TEST"] * 8, "date": ["2026-06-01"] * 8, "timestamp": ts,
        "open": [10.0] * 8, "high": [11.0] * 8, "low": [9.0] * 8,
        "close": [10.5] + [9.5] * 7, "volume": [1000] * 8, "vwap": [10.0] * 8,
    })

    def entrada_con(delay):
        sd = {
            "name": "t", "bias": "long",
            "entry_logic": {
                "timeframe": "1m", "candle_delay": delay,
                "root_condition": {"operator": "AND", "conditions": [{
                    "type": "indicator_comparison",
                    "source": {"name": "Bar Close"},
                    "comparator": "GREATER_THAN",
                    "target": {"name": "VWAP"},
                }]},
            },
            "exit_logic": {"timeframe": "1m",
                           "root_condition": {"operator": "AND", "conditions": []}},
            "risk_management": {
                "use_hard_stop": True, "hard_stop": {"type": "Percentage", "value": 5.0},
                "use_take_profit": True, "take_profit": {"type": "Percentage", "value": 10.0},
                "accept_reentries": False,
            },
        }
        res = run_backtest(intraday_df=df.copy(), strategy_def=sd,
                           market_sessions=["all"], init_cash=10000.0)
        assert len(res["trades"]) == 1, f"delay={delay} no dio ninguna operacion"
        return pd.to_datetime(res["trades"][0]["entry_time"]).strftime("%H:%M")

    assert entrada_con(1) == "09:29"      # senyal 09:28 -> barra siguiente
    assert entrada_con(2) == "09:30"
    assert entrada_con(3) == "09:31"
