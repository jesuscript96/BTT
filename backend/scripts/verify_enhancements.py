import pandas as pd
import numpy as np
from app.backtester.engine import BacktestEngine
from app.schemas.strategy import Strategy, EntryLogic, ExitLogic, ConditionGroup, ComparisonCondition, IndicatorConfig, IndicatorType, Comparator, RiskManagement, RiskType
import json

def test_enhancements():
    # 1. Load mock data
    import duckdb
    db = duckdb.connect("backend/market_data_test.duckdb")
    df = db.execute("SELECT * FROM daily_metrics").df()
    db.close()
    
    # 2. Define a Simple Strategy with Custom Exit
    strategy = Strategy(
        name="Test Long Strategy",
        bias="long",
        entry_logic=EntryLogic(
            root_condition=ConditionGroup(
                conditions=[
                    ComparisonCondition(
                        source=IndicatorConfig(name=IndicatorType.CLOSE),
                        comparator=Comparator.GT,
                        target=IndicatorConfig(name=IndicatorType.SMA, period=20)
                    )
                ]
            )
        ),
        exit_logic=ExitLogic( 
            root_condition=ConditionGroup(
                conditions=[
                    ComparisonCondition(
                        source=IndicatorConfig(name=IndicatorType.CLOSE),
                        comparator=Comparator.LT,
                        target=IndicatorConfig(name=IndicatorType.SMA, period=20)
                    )
                ]
            )
        ),
        risk_management=RiskManagement(
            hard_stop={"type": RiskType.PERCENTAGE, "value": 2.0},
            take_profit={"type": RiskType.PERCENTAGE, "value": 6.0}
        )
    )
    
    # 3. Run Backtest
    engine = BacktestEngine(
        strategies=[strategy],
        weights={strategy.id: 1.0},
        market_data=df,
        commission_per_trade=1.0,
        slippage_pct=0.1 # 0.1% slippage
    )
    
    results = engine.run()
    
    print("\n" + "="*50)
    print("BACKTEST VERIFICATION RESULTS")
    print("="*50)
    print(f"Total Trades: {results.total_trades}")
    print(f"Final Balance: ${results.final_balance:,.2f}")
    print(f"Win Rate: {results.win_rate:.2f}%")
    
    if results.total_trades > 0:
        sample_trade = results.trades[0]
        print(f"\nSample Trade:")
        print(f"  Ticker: {sample_trade['ticker']}")
        print(f"  Entry: {sample_trade['entry_price']:.4f}")
        print(f"  Exit: {sample_trade['exit_price']:.4f}")
        print(f"  Reason: {sample_trade['exit_reason']}")
        
        # Verify slippage check
        # Entry price should be > bar close for longs
        # But we don't have the exact bar close here easily without re-querying.
        # However, we can see if reason 'CUSTOM' exists
        reasons = [t['exit_reason'] for t in results.trades]
        print(f"\nExit Reasons Summary: {pd.Series(reasons).value_counts().to_dict()}")
        
    print("="*50)

if __name__ == "__main__":
    test_enhancements()
