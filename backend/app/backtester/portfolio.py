"""
Portfolio Management Utilities - Correlation, Monte Carlo, and Capital Allocation
"""
from typing import List, Dict, Tuple
import random
from dataclasses import dataclass


@dataclass
class MonteCarloResult:
    """Results from Monte Carlo simulation"""
    worst_drawdown_pct: float
    best_final_balance: float
    worst_final_balance: float
    median_final_balance: float
    percentile_5: float
    percentile_25: float
    percentile_75: float
    percentile_95: float
    probability_of_ruin: float  # % of simulations ending below initial capital


import numpy as np
import pandas as pd

def calculate_correlation_matrix(equity_curves: Dict[str, List[float]]) -> Dict[str, Dict[str, float]]:
    """
    Calculate Pearson correlation using Pandas for precision and speed
    """
    if not equity_curves:
        return {}
    
    # Align lengths if necessary by padding with last value
    max_len = max(len(c) for c in equity_curves.values())
    padded_curves = {}
    for sid, curve in equity_curves.items():
        if len(curve) < max_len:
            padded_curves[sid] = curve + [curve[-1]] * (max_len - len(curve))
        else:
            padded_curves[sid] = curve
            
    df = pd.DataFrame(padded_curves)
    corr_df = df.corr()
    return corr_df.to_dict()


def monte_carlo_simulation(
    trades: List[Dict],
    initial_capital: float,
    num_simulations: int = 1000
) -> MonteCarloResult:
    """
    Run vectorized Monte Carlo simulation
    """
    if not trades:
        return MonteCarloResult(0.0, initial_capital, initial_capital, initial_capital, 
                               initial_capital, initial_capital, initial_capital, initial_capital, 0.0)

    # Use actual USD PnL inferred from R-multiple and allocated risk
    usd_pnls = []
    for t in trades:
        # In our engine, allocated_capital stores the risk (qty * abs(entry - sl))
        risk_usd = t.get('allocated_capital', initial_capital * 0.01)
        r = t.get('r_multiple', 0.0)
        usd_pnls.append(r * risk_usd)

    usd_pnls = np.array(usd_pnls)
    n_trades = len(usd_pnls)
    if n_trades == 0:
        return MonteCarloResult(0.0, initial_capital, initial_capital, initial_capital, 
                               initial_capital, initial_capital, initial_capital, initial_capital, 0.0)
    
    # Vectorized simulation
    # (num_simulations, n_trades)
    indices = np.random.randint(0, n_trades, size=(num_simulations, n_trades))
    sim_pnls = usd_pnls[indices]
    
    # (num_simulations, n_trades + 1)
    equity_paths = np.zeros((num_simulations, n_trades + 1))
    equity_paths[:, 0] = initial_capital
    equity_paths[:, 1:] = np.cumsum(sim_pnls, axis=1) + initial_capital
    
    final_balances = equity_paths[:, -1]
    
    # Drawdown calculation (Vectorized across all paths)
    running_max = np.maximum.accumulate(equity_paths, axis=1)
    drawdowns = (running_max - equity_paths) / (running_max + 1e-10) * 100
    max_drawdowns = np.max(drawdowns, axis=1)
    
    # Probability of ruin (balance < 50% initial)
    ruined = np.any(equity_paths < initial_capital * 0.5, axis=1)
    prob_ruin = np.mean(ruined) * 100
    
    return MonteCarloResult(
        worst_drawdown_pct=float(np.max(max_drawdowns)),
        best_final_balance=float(np.max(final_balances)),
        worst_final_balance=float(np.min(final_balances)),
        median_final_balance=float(np.median(final_balances)),
        percentile_5=float(np.percentile(final_balances, 5)),
        percentile_25=float(np.percentile(final_balances, 25)),
        percentile_75=float(np.percentile(final_balances, 75)),
        percentile_95=float(np.percentile(final_balances, 95)),
        probability_of_ruin=float(prob_ruin)
    )


def calculate_drawdown_series(equity_curve: List[Dict]) -> List[Dict]:
    """
    Calculate drawdown at each point in equity curve
    
    Args:
        equity_curve: List of {"timestamp": ..., "balance": ...}
    
    Returns:
        List of {"timestamp": ..., "drawdown_pct": ..., "drawdown_value": ...}
    """
    if not equity_curve:
        return []
    
    peak = equity_curve[0]['balance']
    drawdown_series = []
    
    for point in equity_curve:
        balance = point['balance']
        
        if balance > peak:
            peak = balance
        
        dd_value = peak - balance
        dd_pct = (dd_value / peak * 100) if peak > 0 else 0
        
        drawdown_series.append({
            "timestamp": point['timestamp'],
            "drawdown_pct": dd_pct,
            "drawdown_value": dd_value,
            "peak": peak
        })
    
    return drawdown_series


def calculate_stagnation_periods(equity_curve: List[Dict]) -> List[Dict]:
    """
    Identify periods where equity is in drawdown (stagnation)
    
    Args:
        equity_curve: List of {"timestamp": ..., "balance": ...}
    
    Returns:
        List of {"start": timestamp, "end": timestamp, "duration_days": int, "max_dd_pct": float}
    """
    if not equity_curve:
        return []
    
    stagnation_periods = []
    current_period = None
    peak = equity_curve[0]['balance']
    peak_timestamp = equity_curve[0]['timestamp']
    
    for point in equity_curve:
        balance = point['balance']
        timestamp = point['timestamp']
        
        if balance >= peak:
            # New peak - end current stagnation period if any
            if current_period:
                current_period['end'] = timestamp
                stagnation_periods.append(current_period)
                current_period = None
            
            peak = balance
            peak_timestamp = timestamp
        else:
            # In drawdown
            dd_pct = (peak - balance) / peak * 100
            
            if current_period is None:
                # Start new stagnation period
                current_period = {
                    "start": peak_timestamp,
                    "end": timestamp,
                    "max_dd_pct": dd_pct
                }
            else:
                # Update existing period
                current_period['end'] = timestamp
                current_period['max_dd_pct'] = max(current_period['max_dd_pct'], dd_pct)
    
    # Close final period if still in drawdown
    if current_period:
        stagnation_periods.append(current_period)
    
    return stagnation_periods


def allocate_capital_by_weight(
    available_capital: float,
    weights: Dict[str, float],
    strategy_ids: List[str]
) -> Dict[str, float]:
    """
    Allocate capital among strategies based on weights
    
    Args:
        available_capital: Total capital to allocate
        weights: Dict of strategy_id -> weight percentage (0-100)
        strategy_ids: List of strategy IDs requesting capital
    
    Returns:
        Dict of strategy_id -> allocated capital
    """
    # Calculate total weight of requesting strategies
    total_weight = sum(weights.get(sid, 0) for sid in strategy_ids)
    
    if total_weight <= 0:
        return {sid: 0 for sid in strategy_ids}
    
    # Allocate proportionally
    allocations = {}
    for sid in strategy_ids:
        weight = weights.get(sid, 0)
        allocations[sid] = (weight / total_weight) * available_capital
    
    return allocations


def calculate_strategy_equity_curves(trades: List[Dict], initial_capital: float) -> Dict[str, List[Dict]]:
    """
    Calculate individual equity curves for each strategy
    
    Args:
        trades: List of all trades with 'strategy_id', 'exit_time', 'r_multiple'
        initial_capital: Starting capital
    
    Returns:
        Dict of strategy_id -> List of {"timestamp": ..., "balance": ...}
    """
    # Group trades by strategy
    strategy_trades = {}
    for trade in trades:
        sid = trade.get('strategy_id')
        if sid:
            if sid not in strategy_trades:
                strategy_trades[sid] = []
            strategy_trades[sid].append(trade)
    
    # Calculate equity curve for each strategy
    equity_curves = {}
    
    for sid, strat_trades in strategy_trades.items():
        # Sort by exit time
        sorted_trades = sorted(
            strat_trades,
            key=lambda t: t.get('exit_time', '')
        )
        
        balance = initial_capital
        curve = [{"timestamp": "start", "balance": balance}]
        
        for trade in sorted_trades:
            r = trade.get('r_multiple', 0)
            if r is not None:
                # Assume 1R = 1% of current balance
                pnl = r * balance * 0.01
                balance += pnl
                
                curve.append({
                    "timestamp": trade.get('exit_time', ''),
                    "balance": balance
                })
        
        equity_curves[sid] = curve
    
    return equity_curves
