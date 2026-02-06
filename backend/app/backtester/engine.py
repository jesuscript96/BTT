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
    
    def evaluate_condition(self, condition: Condition, bar: pd.Series) -> bool:
        """Evaluate a single condition against a market data bar"""
        indicator = condition.indicator
        operator = condition.operator
        value = condition.value
        
        # Get the actual value from the bar
        actual_value = None
        
        if indicator == IndicatorType.PRICE:
            actual_value = bar.get('close', 0)
        elif indicator == IndicatorType.VWAP:
            actual_value = bar.get('vwap', 0)
        elif indicator == IndicatorType.RVOL:
            # RVOL would need to be pre-calculated in market_data
            actual_value = bar.get('rvol', 1.0)
        elif indicator == IndicatorType.TIME_OF_DAY:
            # Time comparison (e.g., "10:30")
            bar_time = pd.to_datetime(bar['timestamp']).time()
            target_time = datetime.strptime(str(value), "%H:%M").time()
            
            if operator == Operator.GT:
                return bar_time > target_time
            elif operator == Operator.LT:
                return bar_time < target_time
            elif operator == Operator.GTE:
                return bar_time >= target_time
            elif operator == Operator.LTE:
                return bar_time <= target_time
            elif operator == Operator.EQ:
                return bar_time == target_time
            return False
        elif indicator == IndicatorType.EXTENSION:
            # Price vs EMA/VWAP extension
            if condition.compare_to == "VWAP":
                base = bar.get('vwap', 0)
                actual_value = ((bar.get('close', 0) - base) / base * 100) if base > 0 else 0
        else:
            # For other indicators, try to get from bar directly
            actual_value = bar.get(indicator.value.lower().replace(' ', '_'), 0)
        
        if actual_value is None:
            return False
        
        # Apply operator
        try:
            target_value = float(value)
            if operator == Operator.GT:
                return actual_value > target_value
            elif operator == Operator.LT:
                return actual_value < target_value
            elif operator == Operator.GTE:
                return actual_value >= target_value
            elif operator == Operator.LTE:
                return actual_value <= target_value
            elif operator == Operator.EQ:
                return abs(actual_value - target_value) < 0.0001
        except (ValueError, TypeError):
            return False
        
        return False
    
    def evaluate_condition_group(self, group: ConditionGroup, bar: pd.Series) -> bool:
        """Evaluate a condition group (AND/OR logic)"""
        if not group.conditions:
            return False
        
        results = [self.evaluate_condition(cond, bar) for cond in group.conditions]
        
        if group.logic == "AND":
            return all(results)
        else:  # OR
            return any(results)
    
    def check_entry_signal(self, strategy: Strategy, bar: pd.Series) -> bool:
        """Check if strategy generates entry signal for this bar"""
        if not strategy.entry_logic:
            return False
        
        # All condition groups must be satisfied (AND between groups)
        return all(
            self.evaluate_condition_group(group, bar)
            for group in strategy.entry_logic
        )
    
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
    
    def run(self) -> BacktestResult:
        """Execute the backtest"""
        print(f"Starting backtest with {len(self.strategies)} strategies...")
        print(f"Market data: {len(self.market_data)} bars")
        
        # Group data by timestamp for chronological iteration
        for timestamp, group in self.market_data.groupby('timestamp'):
            # Check exit conditions for open positions
            for trade in self.open_positions[:]:  # Copy list to allow modification
                # Find bar for this trade's ticker
                ticker_bar = group[group['ticker'] == trade.ticker]
                if not ticker_bar.empty:
                    bar = ticker_bar.iloc[0]
                    should_exit, exit_price, reason = self.check_exit_conditions(trade, bar)
                    
                    if should_exit:
                        self.close_trade(trade, exit_price, timestamp, reason)
                        self.open_positions.remove(trade)
            
            # Check entry signals for each strategy
            signals = []
            for strategy in self.strategies:
                for _, bar in group.iterrows():
                    if self.check_entry_signal(strategy, bar):
                        signals.append((strategy, bar))
            
            # Allocate capital and open trades
            if signals:
                allocations = self.allocate_capital_for_signals(signals)
                
                for strategy, bar in signals:
                    allocated = allocations.get(strategy.id, 0)
                    if allocated > 0:
                        trade = self.open_trade(strategy, bar, allocated)
                        if trade:
                            self.open_positions.append(trade)
            
            # Record equity curve
            self.equity_curve.append({
                "timestamp": str(timestamp),
                "balance": self.current_balance,
                "open_positions": len(self.open_positions)
            })
        
        # Close any remaining open positions at final price
        if self.open_positions:
            final_timestamp = self.market_data['timestamp'].max()
            for trade in self.open_positions[:]:
                final_bar = self.market_data[
                    (self.market_data['ticker'] == trade.ticker) &
                    (self.market_data['timestamp'] == final_timestamp)
                ]
                if not final_bar.empty:
                    final_price = final_bar.iloc[0]['close']
                    self.close_trade(trade, final_price, final_timestamp, "END")
                    self.open_positions.remove(trade)
        
        # Calculate metrics
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
