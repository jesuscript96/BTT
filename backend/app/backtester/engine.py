"""
Backtesting Engine - Core logic for simulating trading strategies
Optimized with Numba (JIT) for high performance.
"""
from typing import List, Dict, Optional, Tuple
from datetime import datetime, time, timedelta
from dataclasses import dataclass
import pandas as pd
import numpy as np
import time as pytime # Rename to avoid conflict with datetime.time
from numba import njit, int64, float64, int32, boolean
from numba.typed import List as NumbaList

from app.schemas.strategy import (
    Strategy, ConditionGroup, RiskType, Comparator, IndicatorType,
    ComparisonCondition, PriceLevelCondition, CandleCondition, CandlePattern
)


@dataclass
class Trade:
    """Represents a single trade execution"""
    id: str
    strategy_id: str
    strategy_name: str
    ticker: str
    entry_time: datetime
    entry_price: float
    exit_time: Optional[datetime]
    exit_price: Optional[float]
    stop_loss: float
    take_profit: float
    position_size: float
    allocated_capital: float
    r_multiple: Optional[float]
    fees: float
    exit_reason: Optional[str]  # "SL", "TP", "TIME", "EOD"
    is_open: bool = True
    side: str = "long"  # "long" or "short"


@dataclass
class BacktestResult:
    """Complete backtest results"""
    run_id: str
    strategy_ids: List[str]
    weights: Dict[str, float]
    initial_capital: float
    final_balance: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_r_multiple: float
    max_drawdown_pct: float
    max_drawdown_value: float
    sharpe_ratio: float
    equity_curve: List[Dict]  # [{"timestamp": ..., "balance": ..., "strategy_id": ...}]
    trades: List[Dict]
    r_distribution: Dict[str, int]  # R-bucket -> count
    ev_by_time: Dict[str, float]  # Hour -> avg R
    ev_by_day: Dict[str, float]  # Day name -> avg R
    monthly_returns: Dict[str, float]  # "YYYY-MM" -> R return


# --- Numba Constants ---
RISK_FIXED = 0
RISK_PERCENT = 1
RISK_ATR = 2
RISK_STRUCTURE = 3

BIAS_LONG = 0
BIAS_SHORT = 1

@njit(cache=True)
def _core_backtest_jit(
    timestamps,      # int64 array (ns)
    opens,           # float64 array
    highs,           # float64 array
    lows,            # float64 array
    closes,          # float64 array
    ticker_ids,      # int64 array (mapped IDs)
    
    entry_signals,   # bool array (n_rows, n_strats)
    exit_signals,    # bool array (n_rows, n_strats)
    
    # Strategy Configs
    strat_sl_types,   # int32 array (n_strats)
    strat_sl_values,  # float64 array
    strat_tp_types,   # int32 array
    strat_tp_values,  # float64 array
    strat_weights,    # float64 array
    strat_biases,     # int32 array (0=Long, 1=Short)
    strat_risk_per_trade,  # float64 array (n_strats): if > 0 use as max allocated USD per trade
    strat_use_hard_stop,   # int32 array (0=no, 1=yes)
    strat_use_take_profit, # int32 array (0=no, 1=yes)
    strat_trailing_active, # int32 array (0=no, 1=yes)
    strat_trailing_pct,    # float64 array (distance %)
    strat_accept_reentries, # int32 array (0=no, 1=yes)
    n_tickers,             # int64
    
    # Global Config
    initial_balance,
    commission,       # fixed per-trade fallback when commission_per_share and locate are 0
    commission_per_share,
    locate_cost_per_100,
    slippage_pct,
    max_holding_sec,  # float64
    
    # Optional Data Columns (pass arrays of zeros if missing)
    atrs,            # float64 array
    pm_highs,        # float64 array
    pm_lows,         # float64 array
    vwaps,           # float64 array
    
    # Pre-calculated time components
    row_hours,       # int64 array
    row_minutes      # int64 array
):
    n_rows = len(closes)
    n_strats = len(strat_weights)
    
    current_balance = float(initial_balance)
    
    # Dynamic Lists for active trades
    active_entry_px = NumbaList()
    active_sl = NumbaList()
    active_tp = NumbaList()
    active_qty = NumbaList()
    active_entry_time = NumbaList()
    active_strat_idx = NumbaList()
    active_ticker_id = NumbaList()
    active_metadata_idx = NumbaList() # Store original row index
    
    # Results containers
    res_entry_idx = NumbaList()
    res_exit_idx = NumbaList()
    res_strat_idx = NumbaList()
    res_entry_px = NumbaList()
    res_exit_px = NumbaList()
    res_qty = NumbaList()
    res_pnl = NumbaList()
    res_sl = NumbaList()
    res_tp = NumbaList()
    res_reason = NumbaList()
    
    # Track open/closed state per strategy and ticker to prevent overlapping trades or re-entries
    has_open = np.zeros((n_strats, n_tickers), dtype=np.bool_)
    has_closed = np.zeros((n_strats, n_tickers), dtype=np.bool_)
    
    # Equity curve (sampled)
    eq_times = NumbaList()
    eq_balances = NumbaList()
    eq_positions = NumbaList()
    
    sample_step = max(1, int(n_rows // 500))
    
    if n_rows > 0:
        eq_times.append(timestamps[0])
        eq_balances.append(current_balance)
        eq_positions.append(0)
    
    for i in range(n_rows):
        current_ts = timestamps[i]
        bar_close = closes[i]
        bar_ticker = ticker_ids[i]
        
        # 1. Manage Open Positions (Iterate backwards)
        j = len(active_entry_px) - 1
        while j >= 0:
            if active_ticker_id[j] == bar_ticker:
                strat_idx = active_strat_idx[j]
                bias = strat_biases[strat_idx]
                trade_sl = active_sl[j]
                trade_tp = active_tp[j]
                entry_time = active_entry_time[j]
                entry_px_pos = active_entry_px[j]
                
                # Trailing stop: update SL when price moves in favor
                if strat_trailing_active[strat_idx] and strat_trailing_pct[strat_idx] > 0:
                    if bias == BIAS_LONG and bar_close > entry_px_pos:
                        new_sl = bar_close * (1.0 - strat_trailing_pct[strat_idx] / 100.0)
                        if new_sl > trade_sl:
                            trade_sl = new_sl
                            active_sl[j] = new_sl
                    elif bias == BIAS_SHORT and bar_close < entry_px_pos:
                        new_sl = bar_close * (1.0 + strat_trailing_pct[strat_idx] / 100.0)
                        if new_sl < trade_sl:
                            trade_sl = new_sl
                            active_sl[j] = new_sl
                
                is_exit_signal = exit_signals[i, strat_idx]
                
                exit_signal_triggered = False
                exit_px = 0.0
                reason_code = -1
                
                # Check Stop Loss / Take Profit / Custom Exit (use bar low/high for intrabar stop)
                bar_low = lows[i]
                bar_high = highs[i]
                if bias == BIAS_LONG:
                    if bar_low <= trade_sl:
                        exit_signal_triggered = True
                        exit_px = trade_sl * (1 - slippage_pct/100)
                        reason_code = 0  # SL
                    elif bar_high >= trade_tp:
                        exit_signal_triggered = True
                        exit_px = trade_tp * (1 - slippage_pct/100)
                        reason_code = 1  # TP
                    elif is_exit_signal:
                        exit_signal_triggered = True
                        exit_px = bar_close * (1 - slippage_pct/100)
                        reason_code = 5  # CUSTOM
                else:  # BIAS_SHORT
                    if bar_high >= trade_sl:
                        exit_signal_triggered = True
                        exit_px = trade_sl * (1 + slippage_pct/100)
                        reason_code = 0  # SL
                    elif bar_low <= trade_tp:
                        exit_signal_triggered = True
                        exit_px = trade_tp * (1 + slippage_pct/100)
                        reason_code = 1  # TP
                    elif is_exit_signal:
                        exit_signal_triggered = True
                        exit_px = bar_close * (1 + slippage_pct/100)
                        reason_code = 5  # CUSTOM
                
                # Time-based exits
                if not exit_signal_triggered:
                    if (current_ts - entry_time) / 1e9 >= max_holding_sec:
                        exit_signal_triggered = True
                        exit_px = bar_close * (1 - slippage_pct/100 if bias == BIAS_LONG else 1 + slippage_pct/100)
                        reason_code = 2 # TIME
                    elif row_hours[i] >= 15 and row_minutes[i] >= 59:
                         exit_signal_triggered = True
                         exit_px = bar_close * (1 - slippage_pct/100 if bias == BIAS_LONG else 1 + slippage_pct/100)
                         reason_code = 3 # EOD
                
                if exit_signal_triggered:
                    qty = active_qty[j]
                    entry_px = active_entry_px[j]
                    if bias == BIAS_LONG:
                        pnl = (exit_px - entry_px) * qty - commission
                    else: # SHORT
                        pnl = (entry_px - exit_px) * qty - commission
                        
                    current_balance += pnl
                    
                    res_entry_idx.append(active_metadata_idx[j])
                    res_exit_idx.append(i)
                    res_strat_idx.append(strat_idx)
                    res_entry_px.append(entry_px)
                    res_exit_px.append(exit_px)
                    res_qty.append(qty)
                    res_pnl.append(pnl)
                    res_sl.append(trade_sl)
                    res_tp.append(trade_tp)
                    res_reason.append(reason_code)
                    
                    has_open[strat_idx, bar_ticker] = False
                    has_closed[strat_idx, bar_ticker] = True
                    
                    active_entry_px.pop(j)
                    active_sl.pop(j)
                    active_tp.pop(j)
                    active_qty.pop(j)
                    active_entry_time.pop(j)
                    active_strat_idx.pop(j)
                    active_ticker_id.pop(j)
                    active_metadata_idx.pop(j)
            j -= 1
            
        # 2. Check Entries
        row_weight_sum = 0.0
        for s in range(n_strats):
            if entry_signals[i, s]:
                row_weight_sum += strat_weights[s]
        
        if row_weight_sum > 0 and current_balance > 0:
            for s in range(n_strats):
                if entry_signals[i, s]:
                    # Check Re-entry constraints
                    if has_open[s, bar_ticker]:
                        continue # Already in a trade for this ticker, skip
                    if strat_accept_reentries[s] == 0 and has_closed[s, bar_ticker]:
                        continue # Re-entries completely forbidden for this strategy, and we've already closed a trade
                        
                    w = strat_weights[s]
                    bias = strat_biases[s]
                    base_allocated = current_balance * (w / row_weight_sum)
                    if strat_risk_per_trade[s] > 0:
                        allocated = min(strat_risk_per_trade[s], base_allocated)
                    else:
                        allocated = base_allocated
                    allocated = min(allocated, current_balance)
                    
                    if allocated > 0:
                        sl_type = strat_sl_types[s]
                        sl_val = strat_sl_values[s]
                        tp_type = strat_tp_types[s]
                        tp_val = strat_tp_values[s]
                        
                        entry_px = bar_close * (1 + slippage_pct/100 if bias == BIAS_LONG else 1 - slippage_pct/100)
                        
                        # Calculate SL
                        stop_loss = 0.0
                        if bias == BIAS_LONG:
                            if sl_type == RISK_FIXED: stop_loss = entry_px - sl_val
                            elif sl_type == RISK_PERCENT: stop_loss = entry_px * (1 - sl_val/100)
                            elif sl_type == RISK_ATR:
                                val_atr = atrs[i] if atrs[i] > 0 else entry_px * 0.02
                                stop_loss = entry_px - (val_atr * sl_val)
                            elif sl_type == RISK_STRUCTURE:
                                val_pm = pm_lows[i] if pm_lows[i] > 0 else entry_px * 0.95
                                stop_loss = val_pm
                            else: stop_loss = entry_px * 0.95
                            if strat_use_hard_stop[s] == 0:
                                stop_loss = 0.0
                        else:  # SHORT
                            if sl_type == RISK_FIXED: stop_loss = entry_px + sl_val
                            elif sl_type == RISK_PERCENT: stop_loss = entry_px * (1 + sl_val/100)
                            elif sl_type == RISK_ATR:
                                val_atr = atrs[i] if atrs[i] > 0 else entry_px * 0.02
                                stop_loss = entry_px + (val_atr * sl_val)
                            elif sl_type == RISK_STRUCTURE:
                                val_pm = pm_highs[i] if pm_highs[i] > 0 else entry_px * 1.05
                                stop_loss = val_pm
                            else: stop_loss = entry_px * 1.05
                            if strat_use_hard_stop[s] == 0:
                                stop_loss = entry_px * 2.0
                            
                        # Calculate TP
                        take_profit = 0.0
                        if bias == BIAS_LONG:
                            if tp_type == RISK_FIXED: take_profit = entry_px + tp_val
                            elif tp_type == RISK_PERCENT: take_profit = entry_px * (1 + tp_val/100)
                            elif tp_type == RISK_ATR:
                                val_atr = atrs[i] if atrs[i] > 0 else entry_px * 0.02
                                take_profit = entry_px + (val_atr * tp_val)
                            elif tp_type == RISK_STRUCTURE:
                                val_vwap = vwaps[i] if vwaps[i] > 0 else entry_px * 1.05
                                take_profit = val_vwap
                            else: take_profit = entry_px * 1.05
                            if strat_use_take_profit[s] == 0:
                                take_profit = entry_px * 2.0
                        else:  # SHORT
                            if tp_type == RISK_FIXED: take_profit = entry_px - tp_val
                            elif tp_type == RISK_PERCENT: take_profit = entry_px * (1 - tp_val/100)
                            elif tp_type == RISK_ATR:
                                val_atr = atrs[i] if atrs[i] > 0 else entry_px * 0.02
                                take_profit = entry_px - (val_atr * tp_val)
                            elif tp_type == RISK_STRUCTURE:
                                val_vwap = vwaps[i] if vwaps[i] > 0 else entry_px * 0.95
                                take_profit = val_vwap
                            else: take_profit = entry_px * 0.95
                            if strat_use_take_profit[s] == 0:
                                take_profit = 0.0
                            
                        if strat_use_hard_stop[s] == 1:
                            risk = abs(stop_loss - entry_px)
                        else:
                            risk = entry_px * 0.02
                        if risk > 0:
                            qty = allocated / risk
                            if qty > 0:
                                if commission_per_share > 0 or locate_cost_per_100 > 0:
                                    fee = commission_per_share * qty + np.ceil(qty / 100.0) * locate_cost_per_100
                                else:
                                    fee = commission
                                if current_balance >= fee:
                                    active_entry_px.append(entry_px)
                                    active_sl.append(stop_loss)
                                    active_tp.append(take_profit)
                                    active_qty.append(qty)
                                    active_entry_time.append(current_ts)
                                    active_strat_idx.append(s)
                                    active_ticker_id.append(bar_ticker)
                                    active_metadata_idx.append(i)
                                    has_open[s, bar_ticker] = True
                                    current_balance -= fee
        
        if (i + 1) % sample_step == 0:
            eq_times.append(current_ts)
            eq_balances.append(current_balance)
            eq_positions.append(len(active_entry_px))
            
    # Force close remaining
    final_bar_px = closes[-1] if n_rows > 0 else 0.0
    for k in range(len(active_entry_px)):
        strat_i = active_strat_idx[k]
        bias = strat_biases[strat_i]
        qty = active_qty[k]
        entry_px = active_entry_px[k]
        
        exit_px = final_bar_px * (1 - slippage_pct/100 if bias == BIAS_LONG else 1 + slippage_pct/100)
        
        if bias == BIAS_LONG:
            pnl = (exit_px - entry_px) * qty - commission
        else: # SHORT
            pnl = (entry_px - exit_px) * qty - commission
            
        current_balance += pnl
        
        res_entry_idx.append(active_metadata_idx[k])
        res_exit_idx.append(n_rows - 1)
        res_strat_idx.append(strat_i)
        res_entry_px.append(entry_px)
        res_exit_px.append(exit_px)
        res_qty.append(qty)
        res_pnl.append(pnl)
        res_sl.append(active_sl[k])
        res_tp.append(active_tp[k])
        res_reason.append(4) # Force
        
    eq_times.append(timestamps[-1])
    eq_balances.append(current_balance)
    eq_positions.append(0)

    return (
        res_entry_idx, res_exit_idx, res_strat_idx, 
        res_entry_px, res_exit_px, res_qty, res_pnl, 
        res_sl, res_tp, res_reason,
        eq_times, eq_balances, eq_positions,
        current_balance
    )


class BacktestEngine:
    """Main backtesting engine"""
    
    def __init__(
        self,
        strategies: List[Strategy],
        weights: Dict[str, float],
        market_data: pd.DataFrame,
        commission_per_trade: float = 1.0,
        commission_per_share: float = 0.0,
        locate_cost_per_100: float = 0.0,
        slippage_pct: float = 0.0,
        lookahead_prevention: bool = False,
        risk_per_trade_usd: Optional[float] = None,
        initial_capital: float = 100000,
        max_holding_minutes: int = 390
    ):
        self.strategies = strategies
        self.weights = weights
        self.market_data = market_data.sort_values('timestamp').reset_index(drop=True)
        self.commission = commission_per_trade
        self.commission_per_share = commission_per_share
        self.locate_cost_per_100 = locate_cost_per_100
        self.slippage_pct = slippage_pct
        self.lookahead_prevention = lookahead_prevention
        self.risk_per_trade_usd = risk_per_trade_usd
        self.initial_capital = initial_capital
        self.max_holding_minutes = max_holding_minutes
        
        # Output state
        self.closed_trades: List[Trade] = []
        self.equity_curve: List[Dict] = []
        self.current_balance = initial_capital
        
    def generate_boolean_signals(self, type: str = "entry") -> np.ndarray:
        """Generate (n_rows, n_strats) boolean matrix for entry or exit"""
        signals = []
        for strategy in self.strategies:
            if type == "entry":
                s_series = self._generate_signals_for_strategy(strategy, self.market_data, "entry")
            else:
                s_series = self._generate_signals_for_strategy(strategy, self.market_data, "exit")
            signals.append(s_series.values)
            
        if not signals:
            return np.zeros((len(self.market_data), 0), dtype=bool)
            
        return np.stack(signals, axis=1)

    def _generate_signals_for_strategy(self, strategy: Strategy, df: pd.DataFrame, type: str) -> pd.Series:
        if type == "entry":
            if not strategy.entry_logic or not strategy.entry_logic.root_condition:
                return pd.Series(False, index=df.index)
            return self._evaluate_group(strategy.entry_logic.root_condition, df)
        else: # exit
            if not strategy.exit_logic or not strategy.exit_logic.root_condition:
                return pd.Series(False, index=df.index)
            return self._evaluate_group(strategy.exit_logic.root_condition, df)

    def _evaluate_group(self, group: ConditionGroup, df: pd.DataFrame) -> pd.Series:
        if not group.conditions:
            return pd.Series(True, index=df.index) if group.operator == "AND" else pd.Series(False, index=df.index)
        
        # Initialize result with Identity element
        # AND -> True, OR -> False
        current_signal = pd.Series(True, index=df.index) if group.operator == "AND" else pd.Series(False, index=df.index)
        
        for condition in group.conditions:
            cond_result = None
            
            if isinstance(condition, ConditionGroup):
                cond_result = self._evaluate_group(condition, df)
            elif hasattr(condition, 'type'):
                # Dispatch based on type
                if condition.type == "indicator_comparison":
                    cond_result = self._evaluate_comparison(condition, df)
                elif condition.type == "price_level_distance":
                    cond_result = self._evaluate_price_level(condition, df)
                elif condition.type == "candle_pattern":
                    cond_result = self._evaluate_candle_pattern(condition, df)
                else:
                    cond_result = pd.Series(False, index=df.index)
            else:
                 cond_result = pd.Series(False, index=df.index)
                 
            if group.operator == "AND":
                current_signal = current_signal & cond_result
            else:
                current_signal = current_signal | cond_result
        
        return current_signal

    def _resolve_indicator(self, config, df: pd.DataFrame) -> pd.Series:
        """Resolve an IndicatorConfig or float to a Series"""
        if isinstance(config, (float, int)):
            return pd.Series(float(config), index=df.index)
            
        # It's an IndicatorConfig
        name = config.name
        period = config.period or 14 # Default period
        
        # We handle tickers separately to avoid leaking data across symbols
        def grouped_rolling(func):
            return df.groupby('ticker')['close'].transform(func)

        series = pd.Series(0.0, index=df.index)
        
        if name == IndicatorType.CLOSE: series = df['close']
        elif name == IndicatorType.OPEN: series = df['open']
        elif name == IndicatorType.HIGH: series = df['high']
        elif name == IndicatorType.LOW: series = df['low']
        elif name == IndicatorType.SMA:
            series = df.groupby('ticker')['close'].transform(lambda x: x.rolling(window=period).mean())
        elif name == IndicatorType.EMA:
            series = df.groupby('ticker')['close'].transform(lambda x: x.ewm(span=period, adjust=False).mean())
        elif name == IndicatorType.WMA:
            weights = np.arange(1, period + 1)
            series = df.groupby('ticker')['close'].transform(
                lambda x: x.rolling(period).apply(lambda bars: np.dot(bars, weights) / weights.sum(), raw=True)
            )
        elif name == IndicatorType.VWAP:
            # VWAP from the first bar of the day
            def calc_vwap(g):
                v = g['volume']
                tp = (g['high'] + g['low'] + g['close']) / 3
                return (tp * v).cumsum() / v.cumsum()
            series = df.groupby(['ticker', df['timestamp'].dt.date], group_keys=False).apply(calc_vwap)
            if len(series) == len(df): series.index = df.index
        elif name == IndicatorType.AVWAP:
            # Anchored VWAP (Day start) - same as VWAP for intraday
            def calc_vwap(g):
                v = g['volume']
                tp = (g['high'] + g['low'] + g['close']) / 3
                return (tp * v).cumsum() / v.cumsum()
            series = df.groupby(['ticker', df['timestamp'].dt.date], group_keys=False).apply(calc_vwap)
            if len(series) == len(df): series.index = df.index
        elif name == IndicatorType.RVOL:
            series = df['rvol'] if 'rvol' in df.columns else pd.Series(1.0, index=df.index)
        elif name == IndicatorType.PMH:
            series = df['pm_high'] if 'pm_high' in df.columns else df['high']
        elif name == IndicatorType.PML:
             series = df['pm_low'] if 'pm_low' in df.columns else df['low']
        elif name == IndicatorType.RSI:
            def calc_rsi(s, p):
                delta = s.diff()
                up = delta.clip(lower=0)
                down = -delta.clip(upper=0)
                ema_up = up.ewm(com=p-1, adjust=False).mean()
                ema_down = down.ewm(com=p-1, adjust=False).mean()
                rs = ema_up / (ema_down + 1e-10)
                return 100 - (100 / (1 + rs))
            series = df.groupby('ticker')['close'].transform(lambda x: calc_rsi(x, period))
        elif name == IndicatorType.MACD:
            ema12 = df.groupby('ticker')['close'].transform(lambda x: x.ewm(span=12, adjust=False).mean())
            ema26 = df.groupby('ticker')['close'].transform(lambda x: x.ewm(span=26, adjust=False).mean())
            series = ema12 - ema26
        elif name == IndicatorType.ATR:
            def calc_atr(group, p):
                high = group['high']
                low = group['low']
                prev_close = group['close'].shift(1)
                tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
                return tr.rolling(window=p).mean()
            series = df.groupby('ticker', group_keys=False).apply(lambda x: calc_atr(x, period))
            if len(series) == len(df): series.index = df.index
        elif name == IndicatorType.HOD:
            series = df.groupby(['ticker', df['timestamp'].dt.date])['high'].transform('cummax')
        elif name == IndicatorType.LOD:
            series = df.groupby(['ticker', df['timestamp'].dt.date])['low'].transform('cummin')
        elif name == IndicatorType.Y_HIGH:
            series = df['prev_high'] if 'prev_high' in df.columns else df['high']
        elif name == IndicatorType.Y_LOW:
            series = df['prev_low'] if 'prev_low' in df.columns else df['low']
        elif name == IndicatorType.Y_CLOSE:
            series = df['prev_close'] if 'prev_close' in df.columns else df['close']
        elif name == IndicatorType.VOLUME:
            series = df['volume'] if 'volume' in df.columns else pd.Series(0.0, index=df.index)
        elif name == IndicatorType.AVOLUME:
            # Cumulative volume from session start (per ticker per date)
            series = df.groupby(['ticker', df['timestamp'].dt.date])['volume'].cumsum()
            if len(series) == len(df):
                series.index = df.index
        elif name == IndicatorType.WILLIAMS_R:
            # %R = -100 * (High_n - Close) / (High_n - Low_n)
            def williams_r(g, p):
                high_n = g['high'].rolling(window=p).max()
                low_n = g['low'].rolling(window=p).min()
                return -100.0 * (high_n - g['close']) / (high_n - low_n + 1e-10)
            series = df.groupby('ticker', group_keys=False).apply(lambda x: williams_r(x, period))
            if len(series) == len(df):
                series.index = df.index
        elif name == IndicatorType.ADX:
            def calc_adx(g, p):
                high = g['high']
                low = g['low']
                close = g['close']
                tr = pd.concat([
                    high - low,
                    (high - close.shift(1)).abs(),
                    (low - close.shift(1)).abs()
                ], axis=1).max(axis=1)
                plus_dm = high.diff()
                minus_dm = -low.diff()
                plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
                minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
                atr = tr.rolling(p).mean()
                plus_di = 100 * (plus_dm.rolling(p).mean() / (atr + 1e-10))
                minus_di = 100 * (minus_dm.rolling(p).mean() / (atr + 1e-10))
                dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
                return dx.rolling(p).mean()
            series = df.groupby('ticker', group_keys=False).apply(lambda x: calc_adx(x, period))
            if len(series) == len(df):
                series.index = df.index
        elif name == IndicatorType.MAX_N_BARS:
            # Max of high over last n bars
            series = df.groupby('ticker')['high'].transform(lambda x: x.rolling(window=period).max())
        elif name == IndicatorType.RET_PCT_PM:
            # % return from first bar of premarket (04:00) or first bar of day per ticker/date
            def ret_pm(g):
                first_close = g['close'].iloc[0]
                return (g['close'] - first_close) / (first_close + 1e-10) * 100
            series = df.groupby(['ticker', df['timestamp'].dt.date], group_keys=False).apply(ret_pm)
            if len(series) == len(df):
                series.index = df.index
        elif name == IndicatorType.RET_PCT_RTH:
            # % return from RTH open (first bar at or after 09:30 per ticker/date)
            def ret_rth(g):
                g = g.sort_values('timestamp')
                rth = g[g['timestamp'].dt.hour * 60 + g['timestamp'].dt.minute >= 9 * 60 + 30]
                if rth.empty:
                    return pd.Series(0.0, index=g.index)
                open_rth = rth['open'].iloc[0]
                return (g['close'] - open_rth) / (open_rth + 1e-10) * 100
            series = df.groupby(['ticker', df['timestamp'].dt.date], group_keys=False).apply(ret_rth)
            if len(series) == len(df):
                series.index = df.index
        elif name == IndicatorType.RET_PCT_AM:
            # % return from previous close (end of RTH) or first AM bar
            def ret_am(g):
                g = g.sort_values('timestamp')
                rth_end = g[g['timestamp'].dt.hour * 60 + g['timestamp'].dt.minute < 16 * 60]
                if rth_end.empty:
                    ref = g['close'].iloc[0]
                else:
                    ref = rth_end['close'].iloc[-1]
                return (g['close'] - ref) / (ref + 1e-10) * 100
            series = df.groupby(['ticker', df['timestamp'].dt.date], group_keys=False).apply(ret_am)
            if len(series) == len(df):
                series.index = df.index
        elif name == IndicatorType.CONSECUTIVE_RED_CANDLES:
            # Count consecutive red candles (close < open) ending at current bar
            def f(g):
                r = g['close'] < g['open']
                c = r.astype(int)
                out = c.copy()
                for i in range(1, len(c)):
                    if r.iloc[i]:
                        out.iloc[i] = out.iloc[i - 1] + 1
                    else:
                        out.iloc[i] = 0
                return out
            series = df.groupby('ticker', group_keys=False).apply(f)
            if len(series) == len(df):
                series.index = df.index
        elif name == IndicatorType.CONSECUTIVE_HIGHER_HIGHS:
            def f_highs(g):
                h = g['high']
                out = pd.Series(0, index=g.index)
                for i in range(1, len(h)):
                    if h.iloc[i] > h.iloc[i - 1]:
                        out.iloc[i] = out.iloc[i - 1] + 1
                    else:
                        out.iloc[i] = 0
                return out
            series = df.groupby('ticker', group_keys=False).apply(f_highs)
            if len(series) == len(df):
                series.index = df.index
        elif name == IndicatorType.CONSECUTIVE_LOWER_LOWS:
            def f_lows(g):
                l = g['low']
                out = pd.Series(0, index=g.index)
                for i in range(1, len(l)):
                    if l.iloc[i] < l.iloc[i - 1]:
                        out.iloc[i] = out.iloc[i - 1] + 1
                    else:
                        out.iloc[i] = 0
                return out
            series = df.groupby('ticker', group_keys=False).apply(f_lows)
            if len(series) == len(df):
                series.index = df.index
        elif name == IndicatorType.TIME_OF_DAY:
            # Minutes since midnight for comparison with (time_hour * 60 + time_minute)
            series = df['timestamp'].dt.hour * 60 + df['timestamp'].dt.minute
            if getattr(config, 'time_hour', None) is not None or getattr(config, 'time_minute', None) is not None:
                # If target is fixed, we still return the series; comparison is done in _evaluate_comparison
                pass
        elif name == IndicatorType.CUSTOM:
            # For custom, multiplier or period might be used as the value
            series = pd.Series(float(config.multiplier if config.multiplier is not None else (config.period or 0)), index=df.index)
        
        if getattr(config, 'offset', 0) and config.offset > 0:
            series = series.groupby(df['ticker']).shift(config.offset)
            series.index = df.index

        return series

    def _evaluate_comparison(self, condition: ComparisonCondition, df: pd.DataFrame) -> pd.Series:
        s1 = self._resolve_indicator(condition.source, df)
        s2 = self._resolve_indicator(condition.target, df)
        
        comp = condition.comparator
        if comp == Comparator.GT: return s1 > s2
        elif comp == Comparator.LT: return s1 < s2
        elif comp == Comparator.GTE: return s1 >= s2
        elif comp == Comparator.LTE: return s1 <= s2
        elif comp == Comparator.EQ: return s1 == s2
        elif comp == Comparator.CROSSES_ABOVE:
            return (s1 > s2) & (s1.shift(1) <= s2.shift(1))
        elif comp == Comparator.CROSSES_BELOW:
             return (s1 < s2) & (s1.shift(1) >= s2.shift(1))
             
        return pd.Series(False, index=df.index)

    def _evaluate_price_level(self, condition: PriceLevelCondition, df: pd.DataFrame) -> pd.Series:
        # source (Close/High/Low) vs level (PMH, etc) +/- value_pct
        source = df[condition.source.lower()]
        
        level_map = {
            IndicatorType.PMH: 'pm_high',
            IndicatorType.PML: 'pm_low',
            IndicatorType.Y_HIGH: 'prev_high', # Assuming this col exists or 0
            IndicatorType.Y_LOW: 'prev_low',
            IndicatorType.Y_CLOSE: 'prev_close'
        }
        
        lvl_col = level_map.get(condition.level)
        if not lvl_col or lvl_col not in df.columns:
            return pd.Series(False, index=df.index)
            
        level_val = df[lvl_col]
        
        # Distance % = (Source - Level) / Level * 100
        dist = (source - level_val) / level_val * 100
        
        if condition.comparator == "DISTANCE_GT":
            return dist > condition.value_pct
        elif condition.comparator == "DISTANCE_LT":
            return dist < condition.value_pct
            
        return pd.Series(False, index=df.index)

    def _evaluate_candle_pattern(self, condition: CandleCondition, df: pd.DataFrame) -> pd.Series:
        pat = condition.pattern
        lookback = condition.lookback or 1
        count = condition.consecutive_count or 1
        
        o, h, l, c = df['open'], df['high'], df['low'], df['close']
        body = (c - o).abs()
        wick_top = h - df[['open', 'close']].max(axis=1)
        wick_bottom = df[['open', 'close']].min(axis=1) - l
        
        res = pd.Series(False, index=df.index)
        
        if pat == CandlePattern.GV: # Green Volume
            # In our schema GV means Green Candle
            res = c > o
        elif pat == CandlePattern.GV_PLUS: # Green Volume Plus
            res = (c > o) & (c > c.shift(1))
        elif pat == CandlePattern.RV: # Red Volume
            res = c < o
        elif pat == CandlePattern.RV_PLUS: # Red Volume Plus
            res = (c < o) & (c < c.shift(1))
        elif pat == CandlePattern.DOJI:
            res = body <= (h - l) * 0.1
        elif pat == CandlePattern.HAMMER:
            res = (wick_bottom > body * 2) & (wick_top < body * 0.5)
        elif pat == CandlePattern.SHOOTING_STAR:
            res = (wick_top > body * 2) & (wick_bottom < body * 0.5)
        
        # Handle lookback/offset
        if lookback > 1:
            res = df.groupby('ticker').transform(lambda x: res.loc[x.index].shift(lookback-1)).iloc[:, 0]
        
        # Handle consecutive count
        if count > 1:
            res = df.groupby('ticker').apply(lambda x: res.loc[x.index].rolling(count).sum() == count).reset_index(level=0, drop=True)
            
        return res

    def run(self) -> BacktestResult:
        print(f"Starting Numba-optimized backtest with {len(self.strategies)} strategies...")
        t0 = pytime.time()
        
        # 1. Prepare Data for JIT
        df = self.market_data
        
        # Ensure timestamp
        if not pd.api.types.is_datetime64_any_dtype(df['timestamp']):
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            
        # Map Tickers to Integers
        unique_tickers = df['ticker'].unique()
        ticker_map = {t: i for i, t in enumerate(unique_tickers)}
        ticker_ids = df['ticker'].map(ticker_map).fillna(-1).astype(np.int64).values
        ticker_map_rev = {i: t for t, i in ticker_map.items()}
        
        timestamps = df['timestamp'].astype('datetime64[ns]').values.astype(np.int64) # ns
        opens = df['open'].values.astype(np.float64)
        highs = df['high'].values.astype(np.float64)
        lows = df['low'].values.astype(np.float64)
        closes = df['close'].values.astype(np.float64)
        
        # Optional columns
        def get_col_or_zeros(name):
            if name in df.columns:
                return df[name].fillna(0).values.astype(np.float64)
            return np.zeros(len(df), dtype=np.float64)
            
        atrs = get_col_or_zeros('atr')
        pm_highs = get_col_or_zeros('pm_high')
        pm_lows = get_col_or_zeros('pm_low')
        vwaps = get_col_or_zeros('vwap')
        
        row_hours = df['timestamp'].dt.hour.values.astype(np.int64)
        row_minutes = df['timestamp'].dt.minute.values.astype(np.int64)
        
        # 2. Prepare Strategies Config
        entry_signals = self.generate_boolean_signals("entry")
        exit_signals = self.generate_boolean_signals("exit")
        
        # Look-ahead prevention: shift signals by 1 bar per ticker
        if self.lookahead_prevention and len(df) > 0:
            n_strats = entry_signals.shape[1]
            entry_shifted = np.zeros_like(entry_signals)
            exit_shifted = np.zeros_like(exit_signals)
            for ticker in unique_tickers:
                mask = df['ticker'].values == ticker
                idx = np.where(mask)[0]
                if len(idx) > 1:
                    entry_shifted[idx[1:], :] = entry_signals[idx[:-1], :]
                    exit_shifted[idx[1:], :] = exit_signals[idx[:-1], :]
            entry_signals = entry_shifted
            exit_signals = exit_shifted
        
        strat_sl_types = []
        strat_sl_values = []
        strat_tp_types = []
        strat_tp_values = []
        strat_weights = []
        strat_biases = []
        
        def _risk_type_to_int(rt):
            if rt is None:
                return RISK_PERCENT
            val = getattr(rt, 'value', rt) if hasattr(rt, 'value') else rt
            return {
                "Fixed Amount": RISK_FIXED,
                "Percentage": RISK_PERCENT,
                "ATR Multiplier": RISK_ATR,
                "Market Structure (HOD/LOD)": RISK_STRUCTURE,
            }.get(val, RISK_PERCENT)
        
        strat_risk_per_trade = []
        strat_use_hard_stop = []
        strat_use_take_profit = []
        strat_trailing_active = []
        strat_trailing_pct = []
        strat_accept_reentries = []
        for s in self.strategies:
            strat_weights.append(self.weights.get(s.id, 0.0))
            strat_biases.append(BIAS_LONG if s.bias == 'long' else BIAS_SHORT)
            strat_risk_per_trade.append(float(self.risk_per_trade_usd) if self.risk_per_trade_usd is not None and self.risk_per_trade_usd > 0 else 0.0)
            rm = getattr(s, 'risk_management', None) or {}
            def _get(obj, key, default=None):
                if isinstance(obj, dict):
                    return obj.get(key, default)
                return getattr(obj, key, default)
            strat_use_hard_stop.append(1 if _get(rm, 'use_hard_stop', True) else 0)
            strat_use_take_profit.append(1 if _get(rm, 'use_take_profit', True) else 0)
            strat_accept_reentries.append(1 if _get(rm, 'accept_reentries', True) else 0)
            ts = _get(rm, 'trailing_stop') or {}
            strat_trailing_active.append(1 if _get(ts, 'active', False) else 0)
            strat_trailing_pct.append(float(_get(ts, 'buffer_pct', 0.5)))
            
            hard_stop = _get(rm, 'hard_stop') or {}
            take_profit = _get(rm, 'take_profit') or {}
            if not isinstance(hard_stop, dict):
                hard_stop = dict(hard_stop) if hard_stop else {}
            if not isinstance(take_profit, dict):
                take_profit = dict(take_profit) if take_profit else {}
            sl_val = hard_stop.get('value', 2.0)
            sl_type_str = hard_stop.get('type', RiskType.PERCENTAGE)
            strat_sl_types.append(_risk_type_to_int(sl_type_str))
            strat_sl_values.append(float(sl_val))
            
            tp_val = take_profit.get('value', 6.0)
            tp_type_str = take_profit.get('type', RiskType.PERCENTAGE)
            strat_tp_types.append(_risk_type_to_int(tp_type_str))
            strat_tp_values.append(float(tp_val))
            
        # 3. Call JIT Function
        print(f"JIT Warmup/Execution for {len(df)} rows...")
        output = _core_backtest_jit(
            timestamps, opens, highs, lows, closes, ticker_ids,
            entry_signals,
            exit_signals,
            np.array(strat_sl_types, dtype=np.int32),
            np.array(strat_sl_values, dtype=np.float64),
            np.array(strat_tp_types, dtype=np.int32),
            np.array(strat_tp_values, dtype=np.float64),
            np.array(strat_weights, dtype=np.float64),
            np.array(strat_biases, dtype=np.int32),
            np.array(strat_risk_per_trade, dtype=np.float64),
            np.array(strat_use_hard_stop, dtype=np.int32),
            np.array(strat_use_take_profit, dtype=np.int32),
            np.array(strat_trailing_active, dtype=np.int32),
            np.array(strat_trailing_pct, dtype=np.float64),
            np.array(strat_accept_reentries, dtype=np.int32),
            len(unique_tickers),
            self.initial_capital,
            self.commission,
            self.commission_per_share,
            self.locate_cost_per_100,
            self.slippage_pct,
            float(self.max_holding_minutes * 60.0),
            atrs, pm_highs, pm_lows, vwaps,
            row_hours, row_minutes
        )
        
        # 4. Unpack Results
        (res_entry_idx, res_exit_idx, res_strat_idx, 
         res_entry_px, res_exit_px, res_qty, res_pnl, 
         res_sl, res_tp, res_reason,
         eq_times, eq_balances, eq_positions,
         final_balance) = output
         
        self.current_balance = final_balance
        
        # Reconstruct Trade Objects
        # Warning: res_* are Typed Lists from Numba, iterating them is fast in Py
        
        reason_map = {0: "Stop Loss", 1: "Take Profit", 2: "Time Limit", 3: "End of Day", 4: "Force Close", 5: "Exit Logic"}
        
        start_reconstruct = pytime.time()
        for k in range(len(res_entry_idx)):
            meta_idx = res_entry_idx[k] # Original row index
            strat_i = res_strat_idx[k]
            strat_obj = self.strategies[strat_i]
            bias = strat_biases[strat_i]
            
            ticker_name = ticker_map_rev.get(ticker_ids[meta_idx], "UNKNOWN")
            entry_ts_val = timestamps[meta_idx]
            entry_dt = pd.Timestamp(entry_ts_val, unit='ns')
            
            trade = Trade(
                id=f"{strat_obj.id}_{ticker_name}_{entry_ts_val}_{k}",
                strategy_id=strat_obj.id,
                strategy_name=strat_obj.name,
                ticker=ticker_name,
                entry_time=entry_dt,
                entry_price=res_entry_px[k],
                exit_time=pd.Timestamp(timestamps[res_exit_idx[k]], unit='ns'),
                exit_price=res_exit_px[k],
                stop_loss=res_sl[k],
                take_profit=res_tp[k],
                position_size=res_qty[k],
                allocated_capital=0.0,
                r_multiple=0.0,
                fees=self.commission,
                exit_reason=reason_map.get(res_reason[k], "UNKNOWN"),
                is_open=False,
                side="long" if bias == BIAS_LONG else "short"
            )
            
            # Calculate R-multiple & Risk
            risk = abs(trade.entry_price - trade.stop_loss)
            if risk > 0:
                if bias == BIAS_LONG:
                    trade.r_multiple = (trade.exit_price - trade.entry_price) / risk
                else: # SHORT
                    trade.r_multiple = (trade.entry_price - trade.exit_price) / risk
            
            trade.allocated_capital = trade.position_size * risk
            self.closed_trades.append(trade)
            
        print(f"Reconstructed {len(self.closed_trades)} trades in {pytime.time() - start_reconstruct:.2f}s")
        
        # Reconstruct Equity Curve
        self.equity_curve = []
        for t, b, p in zip(eq_times, eq_balances, eq_positions):
            self.equity_curve.append({
                "timestamp": pd.Timestamp(t).isoformat(),
                "balance": b,
                "open_positions": p
            })
            
        print(f"Total JIT Execution: {pytime.time() - t0:.2f}s")
        
        return self._calculate_results()

    def _calculate_results(self) -> BacktestResult:
        """Calculate final backtest metrics"""
        # (Same as original)
        total_trades = len(self.closed_trades)
        winning_trades = sum(1 for t in self.closed_trades if t.r_multiple and t.r_multiple > 0)
        losing_trades = sum(1 for t in self.closed_trades if t.r_multiple and t.r_multiple <= 0)
        
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        r_multiples = [t.r_multiple for t in self.closed_trades if t.r_multiple is not None]
        avg_r = sum(r_multiples) / len(r_multiples) if r_multiples else 0
        
        # Drawdown calculation
        equity_values = [e['balance'] for e in self.equity_curve]
        max_dd_pct, max_dd_value = self._calculate_max_drawdown(equity_values)
        
        # R distribution
        r_distribution = self._calculate_r_distribution(r_multiples)
        
        # EV by time and day
        ev_by_time = self._calculate_ev_by_time()
        ev_by_day = self._calculate_ev_by_day()
        
        # Monthly returns
        monthly_returns = self._calculate_monthly_returns()
        
        # Sharpe ratio
        sharpe = self._calculate_sharpe_ratio(r_multiples)
        
        # Convert trades to dicts
        trades_dicts = [self._trade_to_dict(t) for t in self.closed_trades]
        
        return BacktestResult(
            run_id="",
            strategy_ids=[s.id for s in self.strategies],
            weights=self.weights,
            initial_capital=self.initial_capital,
            final_balance=self.current_balance,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            avg_r_multiple=avg_r,
            max_drawdown_pct=max_dd_pct,
            max_drawdown_value=max_dd_value,
            sharpe_ratio=sharpe,
            equity_curve=self.equity_curve,
            trades=trades_dicts,
            r_distribution=r_distribution,
            ev_by_time=ev_by_time,
            ev_by_day=ev_by_day,
            monthly_returns=monthly_returns
        )

    # --- Helper methods (Copied from original) ---
    def _calculate_max_drawdown(self, equity_curve: List[float]) -> Tuple[float, float]:
        if not equity_curve: return 0.0, 0.0
        peak = equity_curve[0]
        max_dd_pct = 0.0
        max_dd_value = 0.0
        for balance in equity_curve:
            if balance > peak: peak = balance
            dd_value = peak - balance
            dd_pct = (dd_value / peak * 100) if peak > 0 else 0
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct
                max_dd_value = dd_value
        return max_dd_pct, max_dd_value

    def _calculate_r_distribution(self, r_multiples: List[float]) -> Dict[str, int]:
        bins = {"-3R": 0, "-2R": 0, "-1R": 0, "0R": 0, "+1R": 0, "+2R": 0, "+3R": 0, "+4R": 0, "+5R+": 0}
        for r in r_multiples:
            if r < -2.5: bins["-3R"] += 1
            elif r < -1.5: bins["-2R"] += 1
            elif r < -0.5: bins["-1R"] += 1
            elif r < 0.5: bins["0R"] += 1
            elif r < 1.5: bins["+1R"] += 1
            elif r < 2.5: bins["+2R"] += 1
            elif r < 3.5: bins["+3R"] += 1
            elif r < 4.5: bins["+4R"] += 1
            else: bins["+5R+"] += 1
        return bins

    def _calculate_ev_by_time(self) -> Dict[str, float]:
        time_buckets = {}
        for trade in self.closed_trades:
            if trade.r_multiple is None: continue
            hour = trade.entry_time.hour
            time_key = f"{hour:02d}:00"
            if time_key not in time_buckets: time_buckets[time_key] = []
            time_buckets[time_key].append(trade.r_multiple)
        return {k: sum(v)/len(v) for k, v in time_buckets.items()}

    def _calculate_ev_by_day(self) -> Dict[str, float]:
        day_buckets = {}
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
        for trade in self.closed_trades:
            if trade.r_multiple is None: continue
            day_name = day_names[trade.entry_time.weekday()]
            if day_name not in day_buckets: day_buckets[day_name] = []
            day_buckets[day_name].append(trade.r_multiple)
        return {k: sum(v)/len(v) for k, v in day_buckets.items()}

    def _calculate_monthly_returns(self) -> Dict[str, float]:
        monthly = {}
        for trade in self.closed_trades:
            if trade.r_multiple is None: continue
            month_key = trade.entry_time.strftime("%Y-%m")
            if month_key not in monthly: monthly[month_key] = 0
            monthly[month_key] += trade.r_multiple
        return monthly

    def _calculate_sharpe_ratio(self, r_multiples: List[float]) -> float:
        if not r_multiples or len(r_multiples) < 2: return 0.0
        mean_r = sum(r_multiples) / len(r_multiples)
        variance = sum((r - mean_r) ** 2 for r in r_multiples) / len(r_multiples)
        std_dev = variance ** 0.5
        if std_dev == 0: return 0.0
        return mean_r / std_dev

    def _trade_to_dict(self, trade: Trade) -> Dict:
        return {
            "id": trade.id,
            "strategy_id": trade.strategy_id,
            "strategy_name": trade.strategy_name,
            "ticker": trade.ticker,
            "entry_time": trade.entry_time.isoformat() if trade.entry_time else None,
            "entry_price": trade.entry_price,
            "exit_time": trade.exit_time.isoformat() if trade.exit_time else None,
            "exit_price": trade.exit_price,
            "stop_loss": trade.stop_loss,
            "take_profit": trade.take_profit,
            "position_size": trade.position_size,
            "r_multiple": trade.r_multiple,
            "fees": trade.fees,
            "exit_reason": trade.exit_reason,
            "side": getattr(trade, "side", "long")
        }


def _max_drawdown_from_curve(equity_curve: List[Dict]) -> Tuple[float, float]:
    """Compute max drawdown from equity curve list of dicts with 'balance' key."""
    if not equity_curve:
        return 0.0, 0.0
    values = [e["balance"] for e in equity_curve]
    peak = values[0]
    max_dd_pct, max_dd_value = 0.0, 0.0
    for balance in values:
        if balance > peak:
            peak = balance
        dd_value = peak - balance
        dd_pct = (dd_value / peak * 100) if peak > 0 else 0
        if dd_pct > max_dd_pct:
            max_dd_pct, max_dd_value = dd_pct, dd_value
    return max_dd_pct, max_dd_value


def _r_distribution_from_trades(trades: List[Dict]) -> Dict[str, int]:
    bins = {"-3R": 0, "-2R": 0, "-1R": 0, "0R": 0, "+1R": 0, "+2R": 0, "+3R": 0, "+4R": 0, "+5R+": 0}
    for t in trades:
        r = t.get("r_multiple")
        if r is None:
            continue
        if r < -2.5: bins["-3R"] += 1
        elif r < -1.5: bins["-2R"] += 1
        elif r < -0.5: bins["-1R"] += 1
        elif r < 0.5: bins["0R"] += 1
        elif r < 1.5: bins["+1R"] += 1
        elif r < 2.5: bins["+2R"] += 1
        elif r < 3.5: bins["+3R"] += 1
        elif r < 4.5: bins["+4R"] += 1
        else: bins["+5R+"] += 1
    return bins


def _sharpe_from_trades(trades: List[Dict]) -> float:
    r_multiples = [t["r_multiple"] for t in trades if t.get("r_multiple") is not None]
    if not r_multiples or len(r_multiples) < 2:
        return 0.0
    mean_r = sum(r_multiples) / len(r_multiples)
    variance = sum((r - mean_r) ** 2 for r in r_multiples) / len(r_multiples)
    std_dev = variance ** 0.5
    return mean_r / std_dev if std_dev else 0.0


def merge_backtest_results(
    chunk_results: List[BacktestResult],
    initial_capital: float,
) -> BacktestResult:
    """
    Merge results from chunked backtest runs (e.g. by month) into a single BacktestResult.
    Use when running the engine on date chunks to bound memory while allowing large datasets.
    """
    if not chunk_results:
        raise ValueError("chunk_results cannot be empty")
    if len(chunk_results) == 1:
        return chunk_results[0]

    merged_trades: List[Dict] = []
    merged_equity: List[Dict] = []
    for r in chunk_results:
        merged_trades.extend(r.trades)
        merged_equity.extend(r.equity_curve)

    total_trades = len(merged_trades)
    winning_trades = sum(1 for t in merged_trades if (t.get("r_multiple") or 0) > 0)
    losing_trades = sum(1 for t in merged_trades if (t.get("r_multiple") or 0) <= 0)
    win_rate = (winning_trades / total_trades * 100) if total_trades else 0.0
    r_list = [t["r_multiple"] for t in merged_trades if t.get("r_multiple") is not None]
    avg_r = sum(r_list) / len(r_list) if r_list else 0.0
    final_balance = chunk_results[-1].final_balance
    max_dd_pct, max_dd_value = _max_drawdown_from_curve(merged_equity)
    sharpe = _sharpe_from_trades(merged_trades)
    r_dist = _r_distribution_from_trades(merged_trades)

    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    ev_by_time_lists: Dict[str, List[float]] = {}
    ev_by_day_lists: Dict[str, List[float]] = {}
    monthly_returns = {}
    for t in merged_trades:
        r = t.get("r_multiple")
        if r is None:
            continue
        et = t.get("entry_time")
        if et:
            try:
                dt = pd.Timestamp(et)
                hk = f"{dt.hour:02d}:00"
                ev_by_time_lists.setdefault(hk, []).append(r)
                dn = day_names[dt.weekday()]
                ev_by_day_lists.setdefault(dn, []).append(r)
                mk = dt.strftime("%Y-%m")
                monthly_returns[mk] = monthly_returns.get(mk, 0) + r
            except Exception:
                pass
    ev_by_time = {k: sum(v) / len(v) for k, v in ev_by_time_lists.items()}
    ev_by_day = {k: sum(v) / len(v) for k, v in ev_by_day_lists.items()}

    first = chunk_results[0]
    return BacktestResult(
        run_id=first.run_id,
        strategy_ids=first.strategy_ids,
        weights=first.weights,
        initial_capital=initial_capital,
        final_balance=final_balance,
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=win_rate,
        avg_r_multiple=avg_r,
        max_drawdown_pct=max_dd_pct,
        max_drawdown_value=max_dd_value,
        sharpe_ratio=sharpe,
        equity_curve=merged_equity,
        trades=merged_trades,
        r_distribution=r_dist,
        ev_by_time=ev_by_time,
        ev_by_day=ev_by_day,
        monthly_returns=monthly_returns,
    )
