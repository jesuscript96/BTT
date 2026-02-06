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


def calculate_correlation_matrix(equity_curves: Dict[str, List[float]]) -> Dict[str, Dict[str, float]]:
    """
    Calculate Pearson correlation between strategy equity curves
    
    Args:
        equity_curves: Dict of strategy_id -> list of balance values
    
    Returns:
        Dict of strategy_id -> Dict of strategy_id -> correlation coefficient
    """
    strategy_ids = list(equity_curves.keys())
    matrix = {}
    
    for id1 in strategy_ids:
        matrix[id1] = {}
        for id2 in strategy_ids:
            if id1 == id2:
                matrix[id1][id2] = 1.0
            else:
                correlation = _pearson_correlation(
                    equity_curves[id1],
                    equity_curves[id2]
                )
                matrix[id1][id2] = correlation
    
    return matrix


def _pearson_correlation(x: List[float], y: List[float]) -> float:
    """Calculate Pearson correlation coefficient"""
    if len(x) != len(y) or len(x) == 0:
        return 0.0
    
    n = len(x)
    
    # Calculate means
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    
    # Calculate covariance and standard deviations
    covariance = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n)) / n
    std_x = (sum((xi - mean_x) ** 2 for xi in x) / n) ** 0.5
    std_y = (sum((yi - mean_y) ** 2 for yi in y) / n) ** 0.5
    
    if std_x == 0 or std_y == 0:
        return 0.0
    
    return covariance / (std_x * std_y)


def monte_carlo_simulation(
    trades: List[Dict],
    initial_capital: float,
    num_simulations: int = 1000
) -> MonteCarloResult:
    """
    Run Monte Carlo simulation by randomizing trade order
    
    Args:
        trades: List of trade dictionaries with 'r_multiple' field
        initial_capital: Starting capital
        num_simulations: Number of random permutations to test
    
    Returns:
        MonteCarloResult with worst-case scenarios and percentiles
    """
    if not trades:
        return MonteCarloResult(
            worst_drawdown_pct=0,
            best_final_balance=initial_capital,
            worst_final_balance=initial_capital,
            median_final_balance=initial_capital,
            percentile_5=initial_capital,
            percentile_25=initial_capital,
            percentile_75=initial_capital,
            percentile_95=initial_capital,
            probability_of_ruin=0
        )
    
    # Extract R-multiples
    r_multiples = [t.get('r_multiple', 0) for t in trades if t.get('r_multiple') is not None]
    
    if not r_multiples:
        return MonteCarloResult(
            worst_drawdown_pct=0,
            best_final_balance=initial_capital,
            worst_final_balance=initial_capital,
            median_final_balance=initial_capital,
            percentile_5=initial_capital,
            percentile_25=initial_capital,
            percentile_75=initial_capital,
            percentile_95=initial_capital,
            probability_of_ruin=0
        )
    
    final_balances = []
    max_drawdowns = []
    ruin_count = 0
    
    for _ in range(num_simulations):
        # Randomize trade order
        shuffled_r = r_multiples.copy()
        random.shuffle(shuffled_r)
        
        # Simulate equity curve
        balance = initial_capital
        peak = initial_capital
        max_dd = 0
        
        for r in shuffled_r:
            # Assume 1R = 1% of current capital (simplified)
            risk_amount = balance * 0.01
            pnl = r * risk_amount
            balance += pnl
            
            # Track drawdown
            if balance > peak:
                peak = balance
            
            dd = (peak - balance) / peak * 100 if peak > 0 else 0
            max_dd = max(max_dd, dd)
            
            # Check for ruin (balance drops below 50% of initial)
            if balance < initial_capital * 0.5:
                ruin_count += 1
                break
        
        final_balances.append(balance)
        max_drawdowns.append(max_dd)
    
    # Sort for percentiles
    final_balances.sort()
    max_drawdowns.sort(reverse=True)
    
    n = len(final_balances)
    
    return MonteCarloResult(
        worst_drawdown_pct=max_drawdowns[0] if max_drawdowns else 0,
        best_final_balance=final_balances[-1],
        worst_final_balance=final_balances[0],
        median_final_balance=final_balances[n // 2],
        percentile_5=final_balances[int(n * 0.05)],
        percentile_25=final_balances[int(n * 0.25)],
        percentile_75=final_balances[int(n * 0.75)],
        percentile_95=final_balances[int(n * 0.95)],
        probability_of_ruin=(ruin_count / num_simulations * 100)
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
