"""
Diagnostico: la Version A del backtest (PMH>=50 + PM open>1, corto,
entrada 05-08 close<prev_close, stop 30%, salida 11:00) dio 0 operaciones
sobre 2.761 pares dia-ticker. Sospecha: backtest_service.py traga una
excepcion real dentro de un `except Exception: continue` silencioso:

    try:
        signals = translate_strategy(mini_df, strategy_def, daily_stats, compiled=compiled_strategy)
    except Exception:
        del mini_df
        continue

Este script NO modifica backend/app/*. Solo importa las funciones reales
del motor en este mismo proceso (nada de HTTP, nada de uvicorn -- asi
tampoco se dispara el precache de arranque) y monkeypatchea la referencia
a translate_strategy que backtest_service.py ya importo, para que la
version parcheada imprima el traceback real antes de relanzar la MISMA
excepcion (el except original de la app se sigue comportando exactamente
igual, solo que ahora vemos por que).

Alcance: UN SOLO MES (2025-09), no los 12, para que sea barato.
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.chdir(os.path.join(os.path.dirname(__file__), "..", "backend"))  # users.duckdb es ruta relativa

from dotenv import load_dotenv
load_dotenv(".env")

# Import de las funciones reales del motor (mismo codigo que usa la API).
from app.services import backtest_service as bs
from app.services.backtest_orchestrator import BacktestRequest, run_backtest_orchestrator

_original_translate_strategy = bs.translate_strategy
_exception_log = []

def _instrumented_translate_strategy(*args, **kwargs):
    try:
        return _original_translate_strategy(*args, **kwargs)
    except Exception as e:
        _exception_log.append((repr(e), traceback.format_exc()))
        if len(_exception_log) <= 3:
            print(f"\n{'='*70}\n[DIAGNOSTICO] translate_strategy lanzo una excepcion real:\n{'='*70}")
            traceback.print_exc()
        raise  # mismo comportamiento que hoy: el `except Exception: continue` de la app la sigue tragando

bs.translate_strategy = _instrumented_translate_strategy

# IDs reales ya creados en users.duckdb (dataset A y estrategia, del intento anterior)
DATASET_A_ID = "8bb15d22-5065-468d-9aeb-18165596cc47"
STRATEGY_ID = "d18f8f01-d9d0-4176-85f3-a6e61ef47f35"

req = BacktestRequest(
    dataset_id=DATASET_A_ID,
    strategy_id=STRATEGY_ID,
    init_cash=10000.0,
    risk_r=100.0,
    risk_type="FIXED",
    size_by_sl=True,
    look_ahead_prevention=False,
    start_date="2025-09-01",
    end_date="2025-09-30",
)

print(f"Lanzando backtest de UN mes (2025-09) sobre dataset A, con translate_strategy instrumentado...")
result = run_backtest_orchestrator(req)

n_days = len(result.get("day_results", []))
n_trades = len(result.get("trades", []))
print(f"\n{'='*70}\nRESULTADO: {n_days} dias con entradas, {n_trades} operaciones")
print(f"Excepciones capturadas dentro de translate_strategy: {len(_exception_log)}")
print(f"{'='*70}")

if _exception_log:
    from collections import Counter
    counts = Counter(msg for msg, _ in _exception_log)
    print("\nResumen de excepciones (mensaje -> num. de pares que la sufrieron):")
    for msg, n in counts.most_common(10):
        print(f"  [{n}x] {msg}")
else:
    print("\nNo se capturo NINGUNA excepcion en translate_strategy para este mes.")
    print("Si aun asi n_trades=0, el problema NO es una excepcion tragada;")
    print("hay que mirar mas abajo en la logica de señales/ventana horaria.")
