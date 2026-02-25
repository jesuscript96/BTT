import pandas as pd
import duckdb
from app.backtester.engine import BacktestEngine
from app.schemas.strategy import Strategy, EntryLogic, ConditionGroup, ComparisonCondition, IndicatorConfig, IndicatorType, Comparator, RiskManagement

db = duckdb.connect("backend/market_data_test.duckdb")
df = db.execute("SELECT * FROM intraday_1m LIMIT 1000").df()

strategy = Strategy(
    id="test-1",
    name="Test",
    bias="long",
    entry_logic=EntryLogic(
        root_condition=ConditionGroup(
            conditions=[
                ComparisonCondition(
                    source=IndicatorConfig(name=IndicatorType.CLOSE),
                    comparator=Comparator.GT,
                    target=IndicatorConfig(name=IndicatorType.OPEN)
                )
            ]
        )
    ),
    risk_management=RiskManagement()
)

engine = BacktestEngine([strategy], {strategy.id: 1.0}, df)
res = engine.run()
print("Total trades:", res.total_trades)
for t in res.trades[:10]:
    print("Entry Time:", t['entry_time'], "| Ticker:", t['ticker'], "| Entry Price:", t['entry_price'])
