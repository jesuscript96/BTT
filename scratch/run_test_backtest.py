import sys
import os
import json

sys.path.append(os.path.abspath('backend'))
from dotenv import load_dotenv
load_dotenv('backend/.env')

from app.services.backtest_orchestrator import run_backtest_orchestrator, BacktestRequest

# Define the strategy draft
# Test V17 modified to have target 100,000,000 for Accumulated Volume
strategy_def = {
  "name": "Test V17 Modified",
  "description": "Long, close supera el open day, con volumen acumulado de más de 100M",
  "bias": "long",
  "universe_filters": None,
  "entry_logic": {
    "timeframe": "15m",
    "root_condition": {
      "type": "group",
      "operator": "AND",
      "conditions": [
        {
          "type": "indicator_comparison",
          "source": {
            "name": "Close",
            "offset": 0
          },
          "comparator": "CROSSES_ABOVE",
          "target": {
            "name": "Day Open",
            "offset": 0
          },
          "timeframe": "15m"
        },
        {
          "type": "indicator_comparison",
          "source": {
            "name": "Accumulated Volume",
            "offset": 0
          },
          "comparator": "GREATER_THAN",
          "target": 300000000.0,  # 300 million
          "timeframe": "15m"
        }
      ]
    }
  },
  "exit_logic": {
    "timeframe": "1m",
    "root_condition": {
      "type": "group",
      "operator": "AND",
      "conditions": []
    }
  },
  "risk_management": {
    "use_hard_stop": True,
    "use_take_profit": False,
    "take_profit_mode": "Full",
    "accept_reentries": False,
    "hard_stop": {
      "type": "Percentage",
      "value": 15
    },
    "take_profit": {
      "type": "Percentage",
      "value": 6
    },
    "partial_take_profits": [
      {
        "distance_pct": 3.0,
        "capital_pct": 50.0
      },
      {
        "distance_pct": 6.0,
        "capital_pct": 50.0
      }
    ],
    "trailing_stop": {
      "active": True,
      "type": "Percentage",
      "buffer_pct": 15
    },
    "max_drawdown_daily": None
  }
}

req = BacktestRequest(
    dataset_id="5051b5b2-4741-4bb7-9331-b57180e7f40a",
    strategy_definition=strategy_def,
    init_cash=10000.0,
    risk_r=100.0,
    risk_type="FIXED",
    fixed_ratio_delta=500.0,
    size_by_sl=False,
    fees=0.0,
    fee_type="PERCENT",
    monthly_expenses=0.0,
    slippage=0.0,
    start_date="2026-01-16",
    end_date="2026-01-16",
    market_sessions=["all"],  # use all sessions
)

print("Running backtest...")
res = run_backtest_orchestrator(req)
trades = res.get("trades", [])
print(f"Total trades generated: {len(trades)}")
if trades:
    print("First 5 trades:")
    for t in trades[:5]:
        print(f"Ticker: {t['ticker']}, Date: {t['date']}, Entry Time: {t['entry_time']}, Entry Price: {t['entry_price']}, PnL: {t['pnl']}")
