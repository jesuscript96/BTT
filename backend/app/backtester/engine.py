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

from app.schemas.strategy import Strategy, Condition, ConditionGroup, RiskType, Operator, IndicatorType


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

@njit(cache=True)
def _core_backtest_jit(
    timestamps,      # int64 array (ns)
    opens,           # float64 array
    highs,           # float64 array
    lows,            # float64 array
    closes,          # float64 array
    ticker_ids,      # int64 array (mapped IDs)
    
    signals,         # bool array (n_rows, n_strats)
    
    # Strategy Configs
    strat_sl_types,   # int32 array (n_strats)
    strat_sl_values,  # float64 array
    strat_tp_types,   # int32 array
    strat_tp_values,  # float64 array
    strat_weights,    # float64 array
    
    # Global Config
    initial_balance,
    commission,
    max_holding_sec,  # float64
    
    # Optional Data Columns (pass arrays of zeros if missing)
    atrs,            # float64 array
    pm_highs,        # float64 array
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
    
    # Needs explicit typing hack for Numba empty list?
    # Usually appending float makes it float list.
    # To be safe we can initialize with dummy and clear, or trust inference.
    # Inference is usually fine with append.
    # But NumbaList() creates a typed list.
    
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
                trade_sl = active_sl[j]
                trade_tp = active_tp[j]
                entry_time = active_entry_time[j]
                
                exit_signal = False
                exit_px = 0.0
                reason_code = -1
                
                # Check Short Logic
                if bar_close >= trade_sl:
                    exit_signal = True
                    exit_px = trade_sl
                    reason_code = 0 # SL
                elif bar_close <= trade_tp:
                    exit_signal = True
                    exit_px = trade_tp
                    reason_code = 1 # TP
                elif (current_ts - entry_time) / 1e9 >= max_holding_sec:
                    exit_signal = True
                    exit_px = bar_close
                    reason_code = 2 # TIME
                elif row_hours[i] >= 15 and row_minutes[i] >= 59:
                     exit_signal = True
                     exit_px = bar_close
                     reason_code = 3 # EOD
                
                if exit_signal:
                    qty = active_qty[j]
                    pnl = (active_entry_px[j] - exit_px) * qty - commission
                    current_balance += pnl
                    
                    res_entry_idx.append(active_metadata_idx[j])
                    res_exit_idx.append(i)
                    res_strat_idx.append(active_strat_idx[j])
                    res_entry_px.append(active_entry_px[j])
                    res_exit_px.append(exit_px)
                    res_qty.append(qty)
                    res_pnl.append(pnl)
                    res_sl.append(trade_sl)
                    res_tp.append(trade_tp)
                    res_reason.append(reason_code)
                    
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
        # Sum weights for this row
        row_weight_sum = 0.0
        for s in range(n_strats):
            if signals[i, s]:
                row_weight_sum += strat_weights[s]
        
        if row_weight_sum > 0 and current_balance > 0:
            for s in range(n_strats):
                if signals[i, s]:
                    w = strat_weights[s]
                    allocated = current_balance * (w / row_weight_sum)
                    
                    if allocated > 0:
                        sl_type = strat_sl_types[s]
                        sl_val = strat_sl_values[s]
                        tp_type = strat_tp_types[s]
                        tp_val = strat_tp_values[s]
                        
                        # Calculate SL
                        stop_loss = 0.0
                        if sl_type == RISK_FIXED:
                            stop_loss = bar_close + sl_val
                        elif sl_type == RISK_PERCENT:
                            stop_loss = bar_close * (1 + sl_val/100)
                        elif sl_type == RISK_ATR:
                            val_atr = atrs[i] if atrs[i] > 0 else bar_close * 0.02
                            stop_loss = bar_close + (val_atr * sl_val)
                        elif sl_type == RISK_STRUCTURE:
                            val_pm = pm_highs[i] if pm_highs[i] > 0 else bar_close * 1.05
                            stop_loss = val_pm
                        else:
                            stop_loss = bar_close * 1.05
                            
                        # Calculate TP
                        take_profit = 0.0
                        if tp_type == RISK_FIXED:
                            take_profit = bar_close - tp_val
                        elif tp_type == RISK_PERCENT:
                            take_profit = bar_close * (1 - tp_val/100)
                        elif tp_type == RISK_ATR:
                            val_atr = atrs[i] if atrs[i] > 0 else bar_close * 0.02
                            take_profit = bar_close - (val_atr * tp_val)
                        elif tp_type == RISK_STRUCTURE:
                            val_vwap = vwaps[i] if vwaps[i] > 0 else bar_close * 0.95
                            take_profit = val_vwap
                        else:
                            take_profit = bar_close * 0.95
                            
                        risk = abs(stop_loss - bar_close)
                        if risk > 0:
                            qty = allocated / risk
                            if qty > 0:
                                active_entry_px.append(bar_close)
                                active_sl.append(stop_loss)
                                active_tp.append(take_profit)
                                active_qty.append(qty)
                                active_entry_time.append(current_ts)
                                active_strat_idx.append(s)
                                active_ticker_id.append(bar_ticker)
                                active_metadata_idx.append(i)
                                
                                current_balance -= commission
        
        if (i + 1) % sample_step == 0:
            eq_times.append(current_ts)
            eq_balances.append(current_balance)
            eq_positions.append(len(active_entry_px))
            
    # Force close remaining
    final_exit_px = closes[-1] if n_rows > 0 else 0.0
    for k in range(len(active_entry_px)):
        pnl = (active_entry_px[k] - final_exit_px) * active_qty[k] - commission
        current_balance += pnl
        
        res_entry_idx.append(active_metadata_idx[k])
        res_exit_idx.append(n_rows - 1)
        res_strat_idx.append(active_strat_idx[k])
        res_entry_px.append(active_entry_px[k])
        res_exit_px.append(final_exit_px)
        res_qty.append(active_qty[k])
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
        commission_per_trade: float,
        initial_capital: float = 100000,
        max_holding_minutes: int = 390
    ):
        self.strategies = strategies
        self.weights = weights
        self.market_data = market_data.sort_values('timestamp').reset_index(drop=True)
        self.commission = commission_per_trade
        self.initial_capital = initial_capital
        self.max_holding_minutes = max_holding_minutes
        
        # Output state
        self.closed_trades: List[Trade] = []
        self.equity_curve: List[Dict] = []
        self.current_balance = initial_capital
        
    def generate_boolean_signals(self) -> np.ndarray:
        """Generate (n_rows, n_strats) boolean matrix"""
        # We reuse the existing logic but ensure output is numpy array
        # This part assumes vectorized pandas ops which are fast enough
        signals = []
        for strategy in self.strategies:
            # We need to temporarily instantiate the old engine methods or just copy implementation?
            # To simulate 'generate_signals' logic we need 'evaluate_condition_vectorized'.
            # I will include `evaluate_condition_vectorized` method in this class as well.
            s_series = self._generate_signals_for_strategy(strategy, self.market_data)
            signals.append(s_series.values) # Convert to numpy array
            
        if not signals:
            return np.zeros((len(self.market_data), 0), dtype=bool)
            
        return np.stack(signals, axis=1)

    def _generate_signals_for_strategy(self, strategy: Strategy, df: pd.DataFrame) -> pd.Series:
        if not strategy.entry_logic:
            return pd.Series(False, index=df.index)
        
        final_signal = pd.Series(True, index=df.index)
        
        for group in strategy.entry_logic:
            if not group.conditions:
                continue
            
            group_signal = pd.Series(True if group.logic == "AND" else False, index=df.index)
            
            for condition in group.conditions:
                cond_result = self._evaluate_condition(condition, df)
                if group.logic == "AND":
                    group_signal = group_signal & cond_result
                else:
                    group_signal = group_signal | cond_result
            
            final_signal = final_signal & group_signal
            
        return final_signal

    def _evaluate_condition(self, condition: Condition, df: pd.DataFrame) -> pd.Series:
        # Copied from original, simplified
        indicator = condition.indicator
        operator = condition.operator
        value = condition.value
        
        series = None
        if indicator == IndicatorType.PRICE:
            series = df['close']
        elif indicator == IndicatorType.VWAP:
            series = df['vwap'] if 'vwap' in df.columns else pd.Series(0, index=df.index)
        elif indicator == IndicatorType.RVOL:
            series = df['rvol'] if 'rvol' in df.columns else pd.Series(1.0, index=df.index)
        elif indicator == IndicatorType.TIME_OF_DAY:
            series = df['timestamp'].dt.time
            try:
                target_time = datetime.strptime(str(value), "%H:%M").time()
                value = target_time
            except:
                return pd.Series(False, index=df.index)
        elif indicator == IndicatorType.EXTENSION:
            if condition.compare_to == "VWAP" and 'vwap' in df.columns:
                series = ((df['close'] - df['vwap']) / df['vwap'] * 100)
            else:
                series = pd.Series(0, index=df.index)
        else:
             col_name = indicator.value.lower().replace(' ', '_')
             series = df[col_name] if col_name in df.columns else pd.Series(False, index=df.index)
        
        try:
            target_value = value
            if isinstance(value, str) and not isinstance(series.iloc[0], (str, time)) and indicator != IndicatorType.TIME_OF_DAY:
                 target_value = float(value)

            if operator == Operator.GT: return series > target_value
            elif operator == Operator.LT: return series < target_value
            elif operator == Operator.GTE: return series >= target_value
            elif operator == Operator.LTE: return series <= target_value
            elif operator == Operator.EQ:
                # Handle Time Comparison carefully
                return series == target_value
        except Exception:
            return pd.Series(False, index=df.index)
        return pd.Series(False, index=df.index)

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
        
        timestamps = df['timestamp'].values.astype(np.int64) # ns
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
        vwaps = get_col_or_zeros('vwap')
        
        row_hours = df['timestamp'].dt.hour.values.astype(np.int64)
        row_minutes = df['timestamp'].dt.minute.values.astype(np.int64)
        
        # 2. Prepare Strategies Config
        signals = self.generate_boolean_signals()
        
        strat_sl_types = []
        strat_sl_values = []
        strat_tp_types = []
        strat_tp_values = []
        strat_weights = []
        
        risk_map = {
            RiskType.FIXED: RISK_FIXED,
            RiskType.PERCENT: RISK_PERCENT,
            RiskType.ATR: RISK_ATR,
            RiskType.STRUCTURE: RISK_STRUCTURE
        }
        
        for s in self.strategies:
            strat_weights.append(self.weights.get(s.id, 0.0))
            strat_sl_types.append(risk_map.get(s.exit_logic.stop_loss_type, RISK_PERCENT))
            strat_sl_values.append(s.exit_logic.stop_loss_value)
            strat_tp_types.append(risk_map.get(s.exit_logic.take_profit_type, RISK_PERCENT))
            strat_tp_values.append(s.exit_logic.take_profit_value)
            
        # 3. Call JIT Function
        print(f"JIT Warmup/Execution for {len(df)} rows...")
        output = _core_backtest_jit(
            timestamps, opens, highs, lows, closes, ticker_ids,
            signals,
            np.array(strat_sl_types, dtype=np.int32),
            np.array(strat_sl_values, dtype=np.float64),
            np.array(strat_tp_types, dtype=np.int32),
            np.array(strat_tp_values, dtype=np.float64),
            np.array(strat_weights, dtype=np.float64),
            self.initial_capital,
            self.commission,
            float(self.max_holding_minutes * 60.0),
            atrs, pm_highs, vwaps,
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
        
        reason_map = {0: "SL", 1: "TP", 2: "TIME", 3: "EOD", 4: "FORCE_CLOSE"}
        
        start_reconstruct = pytime.time()
        for k in range(len(res_entry_idx)):
            meta_idx = res_entry_idx[k] # Original row index
            strat_i = res_strat_idx[k]
            
            # Reconstruct ID: stratId_ticker_timestamp
            strat_obj = self.strategies[strat_i]
            ticker_name = ticker_map_rev.get(ticker_ids[meta_idx], "UNKNOWN")
            entry_ts_val = timestamps[meta_idx]
            # Convert ns to datetime
            entry_dt = pd.Timestamp(entry_ts_val)
            
            trade = Trade(
                id=f"{strat_obj.id}_{ticker_name}_{entry_ts_val}",
                strategy_id=strat_obj.id,
                strategy_name=strat_obj.name,
                ticker=ticker_name,
                entry_time=entry_dt,
                entry_price=res_entry_px[k],
                exit_time=pd.Timestamp(timestamps[res_exit_idx[k]]),
                exit_price=res_exit_px[k],
                stop_loss=res_sl[k],
                take_profit=res_tp[k],
                position_size=res_qty[k],
                allocated_capital=(res_qty[k] * abs(res_sl[k] - res_entry_px[k])), # Approx? No, alloc = risk * size? 
                # Re-calc allocated from size? or just store it. 
                # Optimization: We didn't store allocated in JIT to save memory. 
                # allocated = size * risk per share
                r_multiple=0.0, # Will be calc by _calculate_results logic or here?
                fees=self.commission,
                exit_reason=reason_map.get(res_reason[k], "UNKNOWN"),
                is_open=False
            )
            
            # Calculate R-multiple
            risk = abs(trade.entry_price - trade.stop_loss)
            pnl_gross = (trade.entry_price - trade.exit_price) * trade.position_size # Short PnL
            if risk > 0:
                trade.r_multiple = (trade.entry_price - trade.exit_price) / risk
                
            trade.allocated_capital = trade.position_size * risk # Re-infer
            
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
            "exit_reason": trade.exit_reason
        }
