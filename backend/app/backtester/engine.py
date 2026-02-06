"""
Backtesting Engine - Core logic for simulating trading strategies
"""
from typing import List, Dict, Optional, Tuple
from datetime import datetime, time, timedelta
from dataclasses import dataclass
import pandas as pd
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


class BacktestEngine:
    """Main backtesting engine"""
    
    def __init__(
        self,
        strategies: List[Strategy],
        weights: Dict[str, float],
        market_data: pd.DataFrame,
        commission_per_trade: float,
        initial_capital: float = 100000,
        max_holding_minutes: int = 390  # Full RTH session
    ):
        self.strategies = strategies
        self.weights = weights
        self.market_data = market_data.sort_values('timestamp')
        self.commission = commission_per_trade
        self.initial_capital = initial_capital
        self.max_holding_minutes = max_holding_minutes
        
        # State
        self.current_balance = initial_capital
        self.open_positions: List[Trade] = []
        self.closed_trades: List[Trade] = []
        self.equity_curve: List[Dict] = []
        
        # RTH session times
        self.rth_start = time(9, 30)
        self.rth_end = time(16, 0)
    
    
    def calculate_stop_loss(self, strategy: Strategy, entry_price: float, bar: pd.Series) -> float:
        """Calculate stop loss price based on strategy settings"""
        sl_type = strategy.exit_logic.stop_loss_type
        sl_value = strategy.exit_logic.stop_loss_value
        
        if sl_type == RiskType.FIXED:
            return entry_price + sl_value  # For shorts, SL is above entry
        elif sl_type == RiskType.PERCENT:
            return entry_price * (1 + sl_value / 100)
        elif sl_type == RiskType.ATR:
            atr = bar.get('atr', entry_price * 0.02)  # Default 2% if ATR not available
            return entry_price + (atr * sl_value)
        elif sl_type == RiskType.STRUCTURE:
            # Use high of day or premarket high
            return bar.get('pm_high', entry_price * 1.05)
        
        return entry_price * 1.05  # Default 5% above entry
    
    def calculate_take_profit(self, strategy: Strategy, entry_price: float, bar: pd.Series) -> float:
        """Calculate take profit price based on strategy settings"""
        tp_type = strategy.exit_logic.take_profit_type
        tp_value = strategy.exit_logic.take_profit_value
        
        if tp_type == RiskType.FIXED:
            return entry_price - tp_value  # For shorts, TP is below entry
        elif tp_type == RiskType.PERCENT:
            return entry_price * (1 - tp_value / 100)
        elif tp_type == RiskType.ATR:
            atr = bar.get('atr', entry_price * 0.02)
            return entry_price - (atr * tp_value)
        elif tp_type == RiskType.STRUCTURE:
            # Use VWAP or low of day
            return bar.get('vwap', entry_price * 0.95)
        
        return entry_price * 0.95  # Default 5% below entry
    
    def calculate_position_size(self, allocated_capital: float, entry_price: float, stop_loss: float) -> float:
        """Calculate position size (number of shares)"""
        risk_per_share = abs(stop_loss - entry_price)
        if risk_per_share <= 0:
            return 0
        
        # Risk 1R = allocated capital
        # Position size = allocated_capital / risk_per_share
        return allocated_capital / risk_per_share
    
    def calculate_r_multiple(self, entry_price: float, exit_price: float, stop_loss: float) -> float:
        """Calculate R-multiple for a trade"""
        risk = abs(entry_price - stop_loss)
        if risk <= 0:
            return 0
        
        # For short positions: profit when exit < entry
        profit = entry_price - exit_price
        return profit / risk
    
    def check_exit_conditions(self, trade: Trade, bar: pd.Series) -> Tuple[bool, Optional[float], Optional[str]]:
        """Check if trade should be exited. Returns (should_exit, exit_price, reason)"""
        current_price = bar.get('close', 0)
        current_time = pd.to_datetime(bar['timestamp'])
        
        # Check Stop Loss (price goes above SL for shorts)
        if current_price >= trade.stop_loss:
            return True, trade.stop_loss, "SL"
        
        # Check Take Profit (price goes below TP for shorts)
        if current_price <= trade.take_profit:
            return True, trade.take_profit, "TP"
        
        # Check Time Exit (max holding period)
        holding_time = (current_time - trade.entry_time).total_seconds() / 60
        if holding_time >= self.max_holding_minutes:
            return True, current_price, "TIME"
        
        # Check End of Day (force exit at 15:59)
        if current_time.time() >= time(15, 59):
            return True, current_price, "EOD"
        
        return False, None, None
    
    def allocate_capital_for_signals(self, signals: List[Tuple[Strategy, pd.Series]]) -> Dict[str, float]:
        """Allocate available capital among multiple simultaneous signals"""
        if not signals:
            return {}
        
        available_capital = self.current_balance
        
        # Calculate total weight of signaling strategies
        total_weight = sum(self.weights.get(strategy.id, 0) for strategy, _ in signals)
        
        if total_weight <= 0:
            return {}
        
        # Allocate proportionally
        allocations = {}
        for strategy, _ in signals:
            weight = self.weights.get(strategy.id, 0)
            allocations[strategy.id] = (weight / total_weight) * available_capital
        
        return allocations
    
    def open_trade(self, strategy: Strategy, bar: pd.Series, allocated_capital: float) -> Optional[Trade]:
        """Open a new trade"""
        entry_price = bar.get('close', 0)
        if entry_price <= 0:
            return None
        
        stop_loss = self.calculate_stop_loss(strategy, entry_price, bar)
        take_profit = self.calculate_take_profit(strategy, entry_price, bar)
        position_size = self.calculate_position_size(allocated_capital, entry_price, stop_loss)
        
        if position_size <= 0:
            return None
        
        trade = Trade(
            id=f"{strategy.id}_{bar['ticker']}_{bar['timestamp']}",
            strategy_id=strategy.id,
            strategy_name=strategy.name,
            ticker=bar['ticker'],
            entry_time=pd.to_datetime(bar['timestamp']),
            entry_price=entry_price,
            exit_time=None,
            exit_price=None,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size=position_size,
            allocated_capital=allocated_capital,
            r_multiple=None,
            fees=self.commission,
            exit_reason=None,
            is_open=True
        )
        
        # Deduct capital
        self.current_balance -= self.commission
        
        return trade
    
    def close_trade(self, trade: Trade, exit_price: float, exit_time: datetime, reason: str):
        """Close an open trade"""
        trade.exit_price = exit_price
        trade.exit_time = exit_time
        trade.exit_reason = reason
        trade.is_open = False
        
        # Calculate R-multiple
        trade.r_multiple = self.calculate_r_multiple(
            trade.entry_price,
            exit_price,
            trade.stop_loss
        )
        
        # Calculate P&L (for shorts: profit when exit < entry)
        pnl = (trade.entry_price - exit_price) * trade.position_size
        
        # Update balance
        self.current_balance += pnl - self.commission
        
        # Move to closed trades
        self.closed_trades.append(trade)
    
    def evaluate_condition_vectorized(self, condition: Condition, df: pd.DataFrame) -> pd.Series:
        """Evaluate a condition against the entire dataframe at once (Vectorized)"""
        indicator = condition.indicator
        operator = condition.operator
        value = condition.value
        
        # 1. Get Actual Values Series
        series = None
        
        if indicator == IndicatorType.PRICE:
            series = df['close']
        elif indicator == IndicatorType.VWAP:
            series = df['vwap'] if 'vwap' in df.columns else pd.Series(0, index=df.index)
        elif indicator == IndicatorType.RVOL:
            series = df['rvol'] if 'rvol' in df.columns else pd.Series(1.0, index=df.index)
        elif indicator == IndicatorType.TIME_OF_DAY:
            # Pre-calculated in check_entry_signals to avoid doing it per condition
            # But if needed here:
            series = df['timestamp'].dt.time
            # For time comparison, we need to convert value string "HH:MM" to time object
            try:
                target_time = datetime.strptime(str(value), "%H:%M").time()
                value = target_time # Override value for comparison
            except:
                return pd.Series(False, index=df.index)
        elif indicator == IndicatorType.EXTENSION:
            if condition.compare_to == "VWAP" and 'vwap' in df.columns:
                series = ((df['close'] - df['vwap']) / df['vwap'] * 100)
            else:
                series = pd.Series(0, index=df.index)
        else:
            # Generic column fallback
            col_name = indicator.value.lower().replace(' ', '_')
            if col_name in df.columns:
                series = df[col_name]
            else:
                return pd.Series(False, index=df.index)
        
        # 2. Apply Operator
        try:
            # Handle numeric conversion if value is string but series is numeric
            target_value = value
            if isinstance(value, str) and not isinstance(series.iloc[0], (str, time)) and indicator != IndicatorType.TIME_OF_DAY:
                 target_value = float(value)

            if operator == Operator.GT:
                return series > target_value
            elif operator == Operator.LT:
                return series < target_value
            elif operator == Operator.GTE:
                return series >= target_value
            elif operator == Operator.LTE:
                return series <= target_value
            elif operator == Operator.EQ:
                return series == target_value
        except Exception:
            return pd.Series(False, index=df.index)
            
        return pd.Series(False, index=df.index)

    def generate_signals(self, strategy: Strategy, df: pd.DataFrame) -> pd.Series:
        """Generate entry signals for the strategy using vectorization"""
        if not strategy.entry_logic:
            return pd.Series(False, index=df.index)
        
        # Initialize final signal as True (since groups are ANDed)
        # We start with True, and intersect with each group result
        final_signal = pd.Series(True, index=df.index)
        
        for group in strategy.entry_logic:
            if not group.conditions:
                continue
                
            # Initialize group signal
            # If logic is AND, start with True. If OR, start with False.
            group_signal = pd.Series(True if group.logic == "AND" else False, index=df.index)
            
            for condition in group.conditions:
                cond_result = self.evaluate_condition_vectorized(condition, df)
                
                if group.logic == "AND":
                    group_signal = group_signal & cond_result
                else:  # OR
                    group_signal = group_signal | cond_result
            
            # Combine group into final
            final_signal = final_signal & group_signal
            
        return final_signal

    def run(self) -> BacktestResult:
        """Execute the backtest with optimized loop"""
        print(f"Starting optimized backtest with {len(self.strategies)} strategies...")
        print(f"Market data: {len(self.market_data)} bars")
        
        # 1. Pre-calculate Signals (Vectorized)
        # Result: A dict of {strategy_id: boolean_series}
        strategy_signals = {}
        for strategy in self.strategies:
            strategy_signals[strategy.id] = self.generate_signals(strategy, self.market_data)
        
        # 2. Event Loop
        # Even with vectorization, we need a loop for trade management (PnL, SL/TP)
        # because these depend on the state (entry price) which changes dynamically.
        # However, checking entry is now just a dict lookup `signals[i]`, not a calculation.
        
        # Ensure timestamp is datetime type for comparisons
        self.market_data['timestamp'] = pd.to_datetime(self.market_data['timestamp'])
        
        # We iteration using itertuples which is much faster than iterrows
        # row will have attributes: row.timestamp, row.close, row.high, ...
        # Note: Index is row[0]
        
        # Create a fast lookup for strategy weights
        strategy_weights = {s.id: self.weights.get(s.id, 0) for s in self.strategies}
        
        # Calculate sampling interval for equity curve
        # We want ~500-1000 points max for performance
        total_rows = len(self.market_data)
        sample_interval = max(1, total_rows // 500)  # Sample every Nth row
        
        # Record initial equity point
        if total_rows > 0:
            first_row = self.market_data.iloc[0]
            self.equity_curve.append({
                "timestamp": pd.to_datetime(first_row['timestamp']).isoformat(),
                "balance": self.current_balance,
                "open_positions": 0
            })
        
        row_counter = 0
        
        # Iterate row by row
        for row in self.market_data.itertuples(index=True): 
            # row.Index is the integer index of the dataframe
            idx = row.Index 
            current_time = row.timestamp
            current_price = row.close
            
            # --- Exit Logic (Manage Open Positions) ---
            # We iterate a copy of the list to allow removal
            for i in range(len(self.open_positions) - 1, -1, -1):
                trade = self.open_positions[i]
                
                # Check based on ticker
                if trade.ticker != row.ticker:
                    continue
                
                # Manual inline check needed because we can't pass 'row' to the old function easily
                # causing type mismatches. Inline is faster anyway.
                should_exit = False
                exit_price = None
                reason = None
                
                # Stop Loss (Short)
                if current_price >= trade.stop_loss:
                    should_exit, exit_price, reason = True, trade.stop_loss, "SL"
                
                # Take Profit (Short)
                elif current_price <= trade.take_profit:
                    should_exit, exit_price, reason = True, trade.take_profit, "TP"
                
                # Time Exit
                elif (current_time - trade.entry_time).total_seconds() / 60 >= self.max_holding_minutes:
                    should_exit, exit_price, reason = True, current_price, "TIME"
                
                # EOD Exit
                elif current_time.hour >= 15 and current_time.minute >= 59:
                     should_exit, exit_price, reason = True, current_price, "EOD"
                
                if should_exit:
                    self.close_trade(trade, exit_price, current_time, reason)
                    self.open_positions.pop(i)

            # --- Entry Logic ---
            # Check pre-calculated signals for this row index and ticker
            for strategy in self.strategies:
                # Check if this strategy has a signal at this index
                # Series access via .at is fast
                if strategy_signals[strategy.id].at[idx]:
                    
                    # Allocate capital
                    weight = strategy_weights.get(strategy.id, 0)
                    if weight > 0:
                        allocated = self.current_balance * (weight / 100) # Simple allocation for now
                        
                        # Open Trade (using helper which expects dict-like access? No, let's adapt it)
                        if allocated > 0:
                            # Re-create bar dict just for the helper or inline the helper
                            # Inline is better for speed
                             
                            sl_type = strategy.exit_logic.stop_loss_type
                            sl_val = strategy.exit_logic.stop_loss_value
                            tp_type = strategy.exit_logic.take_profit_type
                            tp_val = strategy.exit_logic.take_profit_value
                            
                            # Calc SL/TP (Simplified common cases for speed)
                            # Assuming Fixed/Percent for now to avoid looking up ATR in helper
                            stop_loss = current_price * (1 + sl_val/100) if sl_type == RiskType.PERCENT else current_price + sl_val
                            take_profit = current_price * (1 - tp_val/100) if tp_type == RiskType.PERCENT else current_price - tp_val
                            
                            risk = abs(stop_loss - current_price)
                            pos_size = allocated / risk if risk > 0 else 0
                            
                            if pos_size > 0:
                                trade = Trade(
                                    id=f"{strategy.id}_{row.ticker}_{row.Index}",
                                    strategy_id=strategy.id,
                                    strategy_name=strategy.name,
                                    ticker=row.ticker,
                                    entry_time=current_time,
                                    entry_price=current_price,
                                    exit_time=None,
                                    exit_price=None,
                                    stop_loss=stop_loss,
                                    take_profit=take_profit,
                                    position_size=pos_size,
                                    allocated_capital=allocated,
                                    r_multiple=None,
                                    fees=self.commission,
                                    exit_reason=None,
                                    is_open=True
                                )
                                self.current_balance -= self.commission
                                self.open_positions.append(trade)

            # Record equity curve at intervals
            row_counter += 1
            if row_counter % sample_interval == 0:
                self.equity_curve.append({
                    "timestamp": current_time.isoformat(),
                    "balance": self.current_balance,
                    "open_positions": len(self.open_positions)
                })

        # Record final equity point
        if total_rows > 0:
            final_row = self.market_data.iloc[-1]
            final_time = pd.to_datetime(final_row['timestamp'])
            self.equity_curve.append({
                "timestamp": final_time.isoformat(),
                "balance": self.current_balance,
                "open_positions": len(self.open_positions)
            })

        # Close remaining
        if self.open_positions:
            final_time = self.market_data['timestamp'].max()
            # Need final prices map
            # Assuming the loop finished at final_time, we can use last known price for each ticker
            # Or just close at current_price from last iteration (approx)
            
            for trade in self.open_positions:
                self.close_trade(trade, trade.entry_price, final_time, "FORCE_CLOSE") # Breakeven close
            self.open_positions.clear()

        return self._calculate_results()
    
    def _calculate_results(self) -> BacktestResult:
        """Calculate final backtest metrics"""
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
        
        # Sharpe ratio (simplified)
        sharpe = self._calculate_sharpe_ratio(r_multiples)
        
        return BacktestResult(
            run_id="",  # Will be set by API
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
            trades=[self._trade_to_dict(t) for t in self.closed_trades],
            r_distribution=r_distribution,
            ev_by_time=ev_by_time,
            ev_by_day=ev_by_day,
            monthly_returns=monthly_returns
        )
    
    def _calculate_max_drawdown(self, equity_curve: List[float]) -> Tuple[float, float]:
        """Calculate maximum drawdown percentage and value"""
        if not equity_curve:
            return 0.0, 0.0
        
        peak = equity_curve[0]
        max_dd_pct = 0.0
        max_dd_value = 0.0
        
        for balance in equity_curve:
            if balance > peak:
                peak = balance
            
            dd_value = peak - balance
            dd_pct = (dd_value / peak * 100) if peak > 0 else 0
            
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct
                max_dd_value = dd_value
        
        return max_dd_pct, max_dd_value
    
    def _calculate_r_distribution(self, r_multiples: List[float]) -> Dict[str, int]:
        """Calculate R-multiple distribution"""
        bins = {
            "-3R": 0, "-2R": 0, "-1R": 0, "0R": 0,
            "+1R": 0, "+2R": 0, "+3R": 0, "+4R": 0, "+5R+": 0
        }
        
        for r in r_multiples:
            if r < -2.5:
                bins["-3R"] += 1
            elif r < -1.5:
                bins["-2R"] += 1
            elif r < -0.5:
                bins["-1R"] += 1
            elif r < 0.5:
                bins["0R"] += 1
            elif r < 1.5:
                bins["+1R"] += 1
            elif r < 2.5:
                bins["+2R"] += 1
            elif r < 3.5:
                bins["+3R"] += 1
            elif r < 4.5:
                bins["+4R"] += 1
            else:
                bins["+5R+"] += 1
        
        return bins
    
    def _calculate_ev_by_time(self) -> Dict[str, float]:
        """Calculate expected value by entry time"""
        time_buckets = {}
        
        for trade in self.closed_trades:
            if trade.r_multiple is None:
                continue
            
            hour = trade.entry_time.hour
            time_key = f"{hour:02d}:00"
            
            if time_key not in time_buckets:
                time_buckets[time_key] = []
            time_buckets[time_key].append(trade.r_multiple)
        
        return {
            time_key: sum(r_list) / len(r_list)
            for time_key, r_list in time_buckets.items()
        }
    
    def _calculate_ev_by_day(self) -> Dict[str, float]:
        """Calculate expected value by day of week"""
        day_buckets = {}
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
        
        for trade in self.closed_trades:
            if trade.r_multiple is None:
                continue
            
            day_name = day_names[trade.entry_time.weekday()]
            
            if day_name not in day_buckets:
                day_buckets[day_name] = []
            day_buckets[day_name].append(trade.r_multiple)
        
        return {
            day: sum(r_list) / len(r_list)
            for day, r_list in day_buckets.items()
        }
    
    def _calculate_monthly_returns(self) -> Dict[str, float]:
        """Calculate monthly returns in R"""
        monthly = {}
        
        for trade in self.closed_trades:
            if trade.r_multiple is None:
                continue
            
            month_key = trade.entry_time.strftime("%Y-%m")
            
            if month_key not in monthly:
                monthly[month_key] = 0
            monthly[month_key] += trade.r_multiple
        
        return monthly
    
    def _calculate_sharpe_ratio(self, r_multiples: List[float]) -> float:
        """Calculate Sharpe ratio (simplified)"""
        if not r_multiples or len(r_multiples) < 2:
            return 0.0
        
        mean_r = sum(r_multiples) / len(r_multiples)
        variance = sum((r - mean_r) ** 2 for r in r_multiples) / len(r_multiples)
        std_dev = variance ** 0.5
        
        if std_dev == 0:
            return 0.0
        
        return mean_r / std_dev
    
    def _trade_to_dict(self, trade: Trade) -> Dict:
        """Convert Trade to dictionary"""
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
