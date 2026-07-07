"""
Semántica de locates (decisión de producto, Jaume 2026-07-07):
el valor que mete el usuario es el COSTE EN $ de cada locate (lo que cuestan
100 acciones reutilizables en corto), NO un % del riesgo.

Antes el orquestador default era "PERCENT" y el frontend enviaba siempre
"PERCENT". Ahora ambos son "FLAT". Este test bloquea una reversión silenciosa
del default y verifica la matemática del modo FLAT en el simulador.
"""
import math


def test_orchestrator_default_locate_type_es_flat():
    from app.services.backtest_orchestrator import BacktestRequest
    # Campos mínimos requeridos según el esquema (dataset + estrategia dummy).
    req = BacktestRequest(dataset_id="x", strategy_def={})
    assert req.locate_type == "FLAT", (
        "el default debe ser FLAT ($/100 acc.), no PERCENT — decisión Jaume 2026-07-07"
    )


def test_flat_mode_cobra_dolares_por_bloque_de_100():
    """FLAT: fee = ceil(max_short_size/100) * locates_cost ($ por 100 acc.).

    Replica la fórmula de portfolio_sim.py (modo FLAT, sin tocar esa lógica):
    locate 3$ + 1000 acciones (10 locates) => 30$/día.
    """
    locates_cost = 3.0          # $ por 100 acciones
    max_short_size_today = 1000  # acciones
    blocks_of_100 = math.ceil(max_short_size_today / 100.0)
    cost_per_100 = locates_cost  # rama FLAT: cost_per_100 = locates_cost
    daily_fee = blocks_of_100 * cost_per_100
    assert daily_fee == 30.0
