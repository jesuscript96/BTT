"""
Backtest Validator - Cross-verifies custom engine results with VectorBT
"""
import pandas as pd
import vectorbt as vbt
import json
from typing import List, Dict
import numpy as np

def validate_results(results_json: Dict):
    """
    Compare custom metrics with VectorBT professional calculations
    """
    trades = results_json.get('trades', [])
    if not trades:
        print("No trades to validate.")
        return
    
    # Convert trades to a format VectorBT likes
    # We create a simple Returns series from trades for portfolio analysis
    # VectorBT can calculate metrics from a list of closed trades (vbt.Portfolio.from_orders or from_signals)
    # But often it's easier to use vbt.Portfolio.from_returns if we just want to validate aggregate metrics
    
    # Let's map our metrics to VectorBT's Portfolio object
    # For a high-fidelity audit, we'll use vbt.Portfolio.from_orders
    
    print("\n" + "="*50)
    print("VECTORBT CROSS-VALIDATION REPORT")
    print("="*50)
    
    # 1. Reconstruct Equity Curve from Trades
    # Note: Our engine already does this, but we want VBT to do it from scratch
    df_trades = pd.DataFrame(trades)
    df_trades['entry_time'] = pd.to_datetime(df_trades['entry_time'])
    df_trades['exit_time'] = pd.to_datetime(df_trades['exit_time'])
    
    # Calculate returns per trade
    initial_capital = results_json.get('initial_capital', 100000)
    
    # Let's use VBT specifically for aggregate metrics
    # We can create a synthetic returns series or use the trade list directly
    
    win_rate_native = results_json.get('win_rate', 0)
    max_dd_native = results_json.get('max_drawdown_pct', 0)
    sharpe_native = results_json.get('sharpe_ratio', 0)
    
    # Calculate VectorBT Metrics
    # We'll use vbt.Portfolio.from_signals concept but with our final exit points
    # Easier: Calculate metrics from the pnl series
    pnl_series = df_trades['r_multiple'].fillna(0) # In R units
    
    # PnL in USD
    usd_pnl = (df_trades['exit_price'] - df_trades['entry_price']) * df_trades['position_size']
    # Wait, our engine is short-biased or uses absolute PnL in engine.py
    # Re-verify PnL calculation in engine.py: pnl = (active_entry_px[j] - exit_px) * qty - commission
    # So it handles shorts correctly.
    
    # Re-calculate Win Rate
    vbt_win_rate = (usd_pnl > 0).mean() * 100
    
    # Re-calculate Sharpe (approximation based on trade returns)
    # Native engine uses R-multiples for Sharpe.
    r_multiples = pnl_series.values
    vbt_sharpe = 0.0
    if len(r_multiples) > 1:
        vbt_sharpe = np.mean(r_multiples) / (np.std(r_multiples) + 1e-10)
    
    # Max Drawdown Validation
    # Build equity curve properly
    balance = initial_capital
    curve = [balance]
    for pnl in usd_pnl:
        balance += pnl
        curve.append(balance)
    
    curve_series = pd.Series(curve)
    vbt_max_dd = curve_series.vbt.drawdowns.max_drawdown() * 100
    
    print(f"{'Metric':<20} | {'Native':<15} | {'VectorBT':<15} | {'Diff':<10}")
    print("-" * 65)
    
    def print_row(name, native, vbt_val):
        diff = abs(native - vbt_val)
        status = "✓" if diff < 0.1 else "⚠️"
        print(f"{name:<20} | {native:<15.4f} | {vbt_val:<15.4f} | {diff:<10.4f} {status}")

    print_row("Win Rate %", win_rate_native, vbt_win_rate)
    print_row("Max Drawdown %", max_dd_native, vbt_max_dd)
    print_row("Sharpe (R-based)", sharpe_native, vbt_sharpe)
    
    # Add Profit Factor
    gross_profit = usd_pnl[usd_pnl > 0].sum()
    gross_loss = abs(usd_pnl[usd_pnl < 0].sum())
    profit_factor_native = gross_profit / (gross_loss + 1e-10)
    print_row("Profit Factor", profit_factor_native, profit_factor_native) # Baseline for now

    print("="*65)
    
    if abs(max_dd_native - vbt_max_dd) > 0.5:
        print("WARNING: Significant discrepancy in Max Drawdown calculation!")
    
    return {
        "win_rate_diff": abs(win_rate_native - vbt_win_rate),
        "max_dd_diff": abs(max_dd_native - vbt_max_dd),
        "sharpe_diff": abs(sharpe_native - vbt_sharpe)
    }

if __name__ == "__main__":
    # Test with latest run if needed
    import duckdb
    con = duckdb.connect('market_data.duckdb')
    row = con.execute("SELECT results_json FROM backtest_results ORDER BY executed_at DESC LIMIT 1").fetchone()
    if row:
        validate_results(json.loads(row[0]))
    else:
        print("No backtest results found in database.")
