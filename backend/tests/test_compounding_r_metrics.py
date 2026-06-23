import pytest
from app.services.backtest_service import _aggregate_metrics

def test_compounding_r_metrics_avg_r_per_day():
    # Arrange
    trades = [
        {"date": "2026-06-22", "pnl": 200.0, "r_multiple": 2.0},
        {"date": "2026-06-23", "pnl": -100.0, "r_multiple": -1.0},
    ]
    # 2 trades over 2 days. Sum of R = 1.0. Avg R per day should be 1.0 / 2 = 0.5.
    
    # Act
    metrics = _aggregate_metrics(
        day_results=[],
        trades=trades,
        global_eq=[],
        global_dd=[],
        init_cash=10000.0,
        risk_r=1.0,  # 1% compounding risk
        monthly_expenses=0.0
    )
    
    # Assert
    assert metrics["avg_r_per_day"] == 0.5
    assert metrics["total_trades"] == 2
    assert metrics["total_days"] == 2
