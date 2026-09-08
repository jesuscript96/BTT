"""Tests del PRD_METRICAS_Y_OOS_BACKTESTER (2026-09-08, Álvaro).

Cubre lo implementado ese día:
  · _aggregate_metrics: claves nuevas r_total / total_return_net_pct /
    calmar_ratio_annualized (más su presencia en el dict `empty`).
  · compute_is_oos_metrics: split IS/OOS server-side con la MISMA semántica de
    cutoff que el memo del frontend (índice de equity, partición por
    entry_time_epoch; los trades del día límite van a OOS).
  · _map_aggregate_metrics: la columna total_return_r lee r_total.
  · _autosave_success: backtest_params persiste el rango EJECUTADO.

Unitarios puros con trades sintéticos — nada de BD remota ni del lago
(mismo patrón que test_compounding_r_metrics.py / test_daily_streak_metrics.py).
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.backtest_service import _aggregate_metrics, compute_is_oos_metrics
from app.routers.strategy_search import _map_aggregate_metrics


# ── _aggregate_metrics: claves nuevas ────────────────────────────────────────


def _agg(trades, init_cash=10000.0, monthly_expenses=0.0, global_dd=None):
    return _aggregate_metrics(
        day_results=[],
        trades=trades,
        global_eq=[],
        global_dd=global_dd or [],
        init_cash=init_cash,
        risk_r=1.0,
        monthly_expenses=monthly_expenses,
    )


def test_r_total_es_la_suma_de_r_multiples():
    trades = [
        {"date": "2026-01-05", "pnl": 300.0, "r_multiple": 3.0},
        {"date": "2026-06-10", "pnl": -100.0, "r_multiple": -1.0},
        # r_multiple None (risk_unit<=0 en su día): no rompe la suma.
        {"date": "2026-06-11", "pnl": 0.0, "r_multiple": None},
    ]
    metrics = _agg(trades)
    assert metrics["r_total"] == 2.0


def test_total_return_net_pct_resta_gastos():
    # Σpnl = 200 sobre 10.000 → bruto 2.0%; un mes de 100 $ de gastos → neto 1.0%.
    trades = [
        {"date": "2026-06-01", "pnl": 300.0, "r_multiple": 3.0},
        {"date": "2026-06-02", "pnl": -100.0, "r_multiple": -1.0},
    ]
    metrics = _agg(trades, monthly_expenses=100.0)
    assert metrics["total_return_pct"] == 2.0
    assert metrics["total_return_net_pct"] == 1.0
    # Sin gastos, neto == bruto.
    assert _agg(trades)["total_return_net_pct"] == 2.0


def test_calmar_ratio_annualized_cagr_sobre_maxdd():
    # Año casi exacto (364 días), +2% total, maxDD −10%:
    # CAGR = 1.02^(365/364) − 1 ≈ 2.0056% → Calmar_anual ≈ 0.20056.
    # Calmar clásico (retorno total) queda en 0.2 para comparar.
    trades = [
        {"date": "2026-01-01", "pnl": 300.0, "r_multiple": 3.0},
        {"date": "2026-12-31", "pnl": -100.0, "r_multiple": -1.0},
    ]
    dd = [{"time": 0, "value": -10.0}]
    metrics = _agg(trades, global_dd=dd)
    expected = (((10200.0 / 10000.0) ** (365.0 / 364.0)) - 1.0) * 100.0 / 10.0
    assert metrics["calmar_ratio"] == pytest.approx(0.2)
    assert metrics["calmar_ratio_annualized"] == pytest.approx(expected, rel=1e-3)


def test_calmar_annualized_degenerados():
    # Un solo día (span 0), cuenta arrasada o dd 0 → 0.0, nunca excepción.
    assert _agg([{"date": "2026-06-01", "pnl": 50.0, "r_multiple": 1.0}],
                global_dd=[{"time": 0, "value": -5.0}])["calmar_ratio_annualized"] == 0.0
    assert _agg([{"date": "2026-01-01", "pnl": 50.0, "r_multiple": 1.0},
                 {"date": "2026-06-01", "pnl": 50.0, "r_multiple": 1.0}],
                global_dd=[{"time": 0, "value": -5.0}])["calmar_ratio_annualized"] != 0.0
    # Cuenta arrasada: final_equity <= 0 → CAGR indefinido → 0.0.
    assert _agg([{"date": "2026-01-01", "pnl": -6000.0, "r_multiple": -6.0},
                 {"date": "2026-06-01", "pnl": -6000.0, "r_multiple": -6.0}],
                init_cash=10000.0,
                global_dd=[{"time": 0, "value": -100.0}])["calmar_ratio_annualized"] == 0.0


def test_empty_aggregate_trae_las_claves_nuevas():
    metrics = _aggregate_metrics([], [], [], [], 10000.0)
    assert metrics["r_total"] == 0.0
    assert metrics["total_return_net_pct"] == 0.0
    assert metrics["calmar_ratio_annualized"] == 0.0


# ── compute_is_oos_metrics ───────────────────────────────────────────────────


def _synthetic_result():
    """10 puntos de equity (init + 9 días) y 10 trades repartidos.

    Días D1..D9 con midnights t1..t9; los trades entran intradía (t+60s). Con
    is_percent=80 el cutoff cae en el índice 8 → cutoff_time = t7 (medianoche
    de D7): los trades de D1..D6 son IS y los de D7 (día límite), D8 y D9 son
    OOS — exactamente la asimetría del memo del frontend.
    """
    dates = [f"2026-06-{d:02d}" for d in range(1, 10)]
    times = [int(pd.Timestamp(d, tz="UTC").timestamp()) for d in dates]
    t0 = times[0] - 86400
    values = [1000, 1100, 1050, 1200, 1150, 1300, 1250, 1400, 1350, 1500]
    eq = [{"time": t, "value": v} for t, v in zip([t0] + times, values)]

    trades = []
    pnls = [100, -50, 100, 100, -50, 100, -50, 100, 100, -50]
    rs = [1.0, -0.5, 1.0, 1.0, -0.5, 1.0, -0.5, 1.0, 1.0, -0.5]
    for i, (d, t) in enumerate(zip(dates, times)):
        trades.append({
            "date": d, "entry_time_epoch": t + 60, "pnl": float(pnls[i]),
            "r_multiple": rs[i],
        })

    day_results = [
        {"date": d, "locates_fee": 10.0} for d in dates
    ]
    return {"global_equity": eq, "trades": trades, "day_results": day_results}


def test_is_oos_none_cuando_no_toca():
    result = _synthetic_result()
    assert compute_is_oos_metrics(result, 100) is None
    assert compute_is_oos_metrics(result, None) is None
    assert compute_is_oos_metrics({"global_equity": [], "trades": []}, 80) is None
    assert compute_is_oos_metrics({"global_equity": [{"time": 1, "value": 1}]}, 80) is None


def test_is_oos_particion_y_cutoff():
    result = _synthetic_result()
    block = compute_is_oos_metrics(result, 80)
    assert block is not None
    assert block["is_percent"] == 80

    eq = result["global_equity"]
    assert block["cutoff_time"] == eq[7]["time"]

    is_m, oos_m = block["is_metrics"], block["oos_metrics"]
    # 6 trades IS (D1..D6), 3 OOS (día límite D7 + D8 + D9).
    assert is_m["total_trades"] == 6
    assert oos_m["total_trades"] == 3
    # ΣR por segmento.
    assert is_m["r_total"] == pytest.approx(3.0)
    assert oos_m["r_total"] == pytest.approx(1.5)
    # total_pnl = Σpnl − locates del segmento. OJO la asimetría del frontend
    # que aquí replicamos: los day_results particionan por FECHA (medianoche
    # <= cutoff), así que las locates del día límite D7 (cuyo midnight ==
    # cutoff_time) cuentan en IS aunque sus trades vayan a OOS.
    # IS: 7 días × 10 $; OOS: 2 días (D8, D9) × 10 $.
    assert is_m["total_pnl"] == pytest.approx(300.0 - 70.0)
    assert oos_m["total_pnl"] == pytest.approx(150.0 - 20.0)
    # Return sobre init_cash (punto 0 de la curva).
    assert is_m["total_return_pct"] == pytest.approx(230.0 / 1000.0 * 100)
    assert oos_m["total_return_pct"] == pytest.approx(130.0 / 1000.0 * 100)
    # WR: IS 4/6, OOS 2/3.
    assert is_m["win_rate_pct"] == pytest.approx(66.67, abs=0.01)
    assert oos_m["win_rate_pct"] == pytest.approx(66.67, abs=0.01)
    # PF sobre pnl: IS 400/100, OOS 200/50.
    assert is_m["avg_profit_factor"] == 4.0
    assert oos_m["avg_profit_factor"] == 4.0
    # maxDD IS desde eq[:8]: pico 1200 (índice 4) → valle 1150 → −4.1667%.
    is_vals = np.array([p["value"] for p in eq[:8]])
    is_dd = float((is_vals / np.maximum.accumulate(is_vals) - 1).min() * 100)
    assert is_m["max_drawdown_pct"] == pytest.approx(is_dd, abs=0.01)
    # maxDD OOS desde eq[7:]: pico 1400 → valle 1350 → −3.5714%.
    oos_vals = np.array([p["value"] for p in eq[7:]])
    oos_dd = float((oos_vals / np.maximum.accumulate(oos_vals) - 1).min() * 100)
    assert oos_m["max_drawdown_pct"] == pytest.approx(oos_dd, abs=0.01)


def test_is_oos_is_percent_50_cae_en_medio():
    result = _synthetic_result()
    block = compute_is_oos_metrics(result, 50)
    # floor(10 * 0.5) = 5 → cutoff_time = eq[4] (medianoche de D4):
    # IS = D1..D3 (3 trades), OOS = D4..D9 (6, día límite incluido).
    eq = result["global_equity"]
    assert block["cutoff_time"] == eq[4]["time"]
    assert block["is_metrics"]["total_trades"] == 3
    assert block["oos_metrics"]["total_trades"] == 6


# ── Columna total_return_r ───────────────────────────────────────────────────


def test_map_aggregate_metrics_total_return_r():
    mapped = _map_aggregate_metrics({"aggregate_metrics": {"r_total": 356.55}})
    assert mapped["total_return_r"] == pytest.approx(356.55)
    # Corridas viejas sin r_total: fallback a la clave legacy (0 si tampoco).
    legacy = _map_aggregate_metrics({"aggregate_metrics": {"total_return_r": 12.0}})
    assert legacy["total_return_r"] == pytest.approx(12.0)
    assert _map_aggregate_metrics({"aggregate_metrics": {}})["total_return_r"] == 0


# ── _autosave_success: fechas ejecutadas ────────────────────────────────────


def test_autosave_persiste_rango_ejecutado(monkeypatch):
    from app.routers import backtest as backtest_router
    from app.services.backtest_orchestrator import BacktestRequest

    captured = {}

    def _capture(job_id, *, strategy_ids, results_json, user_id):
        captured["results_json"] = results_json

    monkeypatch.setattr(
        "app.routers.strategy_search.autosave_backtest", _capture
    )

    req = BacktestRequest(
        dataset_id="ds-1",
        start_date="2026-01-02",
        end_date="2026-09-04",
        strategy_definition={"name": "Sobri"},
    )
    result = {
        "aggregate_metrics": {"r_total": 5.0},
        "trades": [],
        "executed_date_range": {"start": "2025-01-02", "end": "2025-12-31"},
    }
    backtest_router._autosave_success(req, "job-1", result, user_id=None)

    params = captured["results_json"]["backtest_params"]
    assert params["start_date"] == "2025-01-02"
    assert params["end_date"] == "2025-12-31"
    assert "2025-01-02 → 2025-12-31" in captured["results_json"]["label"]
    # El rango ejecutado viaja además como hecho del run.
    assert captured["results_json"]["executed_date_range"] == {
        "start": "2025-01-02", "end": "2025-12-31"
    }


def test_autosave_sin_rango_ejecutado_cae_al_formulario(monkeypatch):
    from app.routers import backtest as backtest_router
    from app.services.backtest_orchestrator import BacktestRequest

    captured = {}
    monkeypatch.setattr(
        "app.routers.strategy_search.autosave_backtest",
        lambda job_id, *, strategy_ids, results_json, user_id: captured.update(
            results_json=results_json
        ),
    )
    req = BacktestRequest(
        dataset_id="ds-1", start_date="2026-01-01", end_date="2026-02-01"
    )
    backtest_router._autosave_success(req, "job-2", {"trades": []}, user_id=None)
    params = captured["results_json"]["backtest_params"]
    assert params["start_date"] == "2026-01-01"
    assert params["end_date"] == "2026-02-01"


def test_backtest_request_acepta_is_percent():
    from app.services.backtest_orchestrator import BacktestRequest

    assert BacktestRequest(dataset_id="ds-1").is_percent == 100
    assert BacktestRequest(dataset_id="ds-1", is_percent=90).is_percent == 90
