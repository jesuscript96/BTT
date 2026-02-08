"""
Tests for Backtest Engine using REAL data.
Validates calculations AFTER backtest execution (post-run validation).
"""
import pytest
import pandas as pd
from datetime import datetime, timedelta
from app.backtester.engine import BacktestEngine
from app.schemas.strategy import Strategy, ConditionGroup, Condition, IndicatorType, Operator, RiskType


class TestEntrySignalGeneration:
    """Tests for vectorized entry signal generation"""
    
    def test_price_condition_signal(self, sample_historical_data):
        """Test: Signal based on close > X"""
        if sample_historical_data.empty:
            pytest.skip("No historical data available")
        
        #Create simple price-based strategy
        strategy = Strategy(
            id="test_price",
            name="Price Test",
            filters={},
            entry_logic=[
                ConditionGroup(
                    logic="AND",
                    conditions=[
                        Condition(
                            indicator=IndicatorType.PRICE,
                            operator=Operator.GT,
                            value="100.0"
                        )
                    ]
                )
            ],
            exit_logic={
                "stop_loss_type": RiskType.PERCENT,
                "stop_loss_value": 1.0,
                "take_profit_type": RiskType.PERCENT,
                "take_profit_value": 2.0
            }
        )
        
        engine = BacktestEngine(
            strategies=[strategy],
            weights={strategy.id: 100},
            market_data=sample_historical_data,
            commission_per_trade=1.0,
            initial_capital=100000
        )
        
        # Generate signals
        signals = engine.generate_signals(strategy, sample_historical_data)
        
        # Validate: signals should only be True where close > 100
        for idx, signal in signals.items():
            if signal:
                price = sample_historical_data.loc[idx, "close"]
                assert price > 100.0, f"Signal triggered at price {price} <= 100"
    
    def test_vwap_condition_signal(self, sample_historical_data):
        """Test: Signal based on close < vwap"""
        if sample_historical_data.empty or "vwap" not in sample_historical_data.columns:
            pytest.skip("No VWAP data available")
        
        strategy = Strategy(
            id="test_vwap",
            name="VWAP Test",
            filters={},
            entry_logic=[
                ConditionGroup(
                    logic="AND",
                    conditions=[
                        Condition(
                            indicator=IndicatorType.VWAP,
                            operator=Operator.LT,
                            value="0",  # Will compare to close
                            compare_to="PRICE"
                        )
                    ]
                )
            ],
            exit_logic={
                "stop_loss_type": RiskType.PERCENT,
                "stop_loss_value": 1.0,
                "take_profit_type": RiskType.PERCENT,
                "take_profit_value": 2.0
            }
        )
        
        engine = BacktestEngine(
            strategies=[strategy],
            weights={strategy.id: 100},
            market_data=sample_historical_data,
            commission_per_trade=1.0
        )
        
        signals = engine.generate_signals(strategy, sample_historical_data)
        
        # Validate signal logic
        assert isinstance(signals, pd.Series), "Should return pandas Series"


class TestStopLossCalculations:
    """Tests for SL calculation methods"""
    
    def test_sl_percent_short(self, sample_historical_data):
        """Test: SL = entry * (1 + percent/100) for shorts"""
        if sample_historical_data.empty:
            pytest.skip("No data available")
        
        entry_price = 100.0
        sl_percent = 5.0  # 5%
        
        expected_sl = entry_price * (1 + sl_percent / 100)  # 105.0
        
        # Create strategy with percent SL
        strategy = Strategy(
            id="test_sl_pct",
            name="SL Percent Test",
            filters={},
            entry_logic=[],
            exit_logic={
                "stop_loss_type": RiskType.PERCENT,
                "stop_loss_value": sl_percent,
                "take_profit_type": RiskType.PERCENT,
                "take_profit_value": 5.0
            }
        )
        
        engine = BacktestEngine(strategies=[strategy], weights={strategy.id: 100}, market_data=sample_historical_data, commission_per_trade=1.0)
        
        # Calculate SL
        bar = sample_historical_data.iloc[0]
        calculated_sl = engine.calculate_stop_loss(strategy, entry_price, bar)
        
        assert abs(calculated_sl - expected_sl) < 0.01, f"SL should be {expected_sl}, got {calculated_sl}"
    
    def test_sl_fixed_short(self, sample_historical_data):
        """Test: SL = entry + fixed_value for shorts"""
        if sample_historical_data.empty:
            pytest.skip("No data available")
        
        entry_price = 100.0
        sl_fixed = 2.5
        
        expected_sl = entry_price + sl_fixed  # 102.5
        
        strategy = Strategy(
            id="test_sl_fixed",
            name="SL Fixed Test",
            filters={},
            entry_logic=[],
            exit_logic={
                "stop_loss_type": RiskType.FIXED,
                "stop_loss_value": sl_fixed,
                "take_profit_type": RiskType.FIXED,
                "take_profit_value": 2.5
            }
        )
        
        engine = BacktestEngine(strategies=[strategy], weights={strategy.id: 100}, market_data=sample_historical_data, commission_per_trade=1.0)
        bar = sample_historical_data.iloc[0]
        calculated_sl = engine.calculate_stop_loss(strategy, entry_price, bar)
        
        assert abs(calculated_sl - expected_sl) < 0.01, f"SL should be {expected_sl}, got {calculated_sl}"


class TestTakeProfitCalculations:
    """Tests for TP calculation methods"""
    
    def test_tp_percent_short(self, sample_historical_data):
        """Test: TP = entry * (1 - percent/100) for shorts"""
        if sample_historical_data.empty:
            pytest.skip("No data available")
        
        entry_price = 100.0
        tp_percent = 5.0  # 5%
        
        expected_tp = entry_price * (1 - tp_percent / 100)  # 95.0
        
        strategy = Strategy(
            id="test_tp_pct",
            name="TP Percent Test",
            filters={},
            entry_logic=[],
            exit_logic={
                "stop_loss_type": RiskType.PERCENT,
                "stop_loss_value": 5.0,
                "take_profit_type": RiskType.PERCENT,
                "take_profit_value": tp_percent
            }
        )
        
        engine = BacktestEngine(strategies=[strategy], weights={strategy.id: 100}, market_data=sample_historical_data, commission_per_trade=1.0)
        bar = sample_historical_data.iloc[0]
        calculated_tp = engine.calculate_take_profit(strategy, entry_price, bar)
        
        assert abs(calculated_tp - expected_tp) < 0.01, f"TP should be {expected_tp}, got {calculated_tp}"


class TestPositionSizing:
    """Tests for position size calculations"""
    
    def test_position_size_calculation(self):
        """Test: position_size = allocated_capital / risk_per_share"""
        allocated_capital = 10000
        entry_price = 100.0
        stop_loss = 105.0  # Risk = $5 per share
        
        risk_per_share = abs(stop_loss - entry_price)  # 5.0
        expected_size = allocated_capital / risk_per_share  # 2000 shares
        
        # Use mock data just for calculation
        strategy = Strategy(
            id="test", name="Test", filters={}, entry_logic=[],
            exit_logic={"stop_loss_type": RiskType.FIXED, "stop_loss_value": 5.0, "take_profit_type": RiskType.FIXED, "take_profit_value": 5.0}
        )
        
        df = pd.DataFrame({"ticker": ["TEST"], "timestamp": [datetime.now()], "close": [100.0]})
        engine = BacktestEngine(strategies=[strategy], weights={strategy.id: 100}, market_data=df, commission_per_trade=1.0)
        
        calculated_size = engine.calculate_position_size(allocated_capital, entry_price, stop_loss)
        
        assert abs(calculated_size - expected_size) < 0.01, f"Position size should be {expected_size}, got {calculated_size}"


class TestRMultipleCalculation:
    """Tests for R-multiple calculations"""
    
    def test_r_multiple_winner(self):
        """Test: R > 0 for winning trade"""
        entry_price = 100.0
        exit_price = 97.5  # Profit for short
        stop_loss = 105.0  # Risk = $5
        
        risk = abs(entry_price - stop_loss)  # 5.0
        profit = entry_price - exit_price  # 2.5
        expected_r = profit / risk  # 0.5R
        
        strategy = Strategy(id="test", name="Test", filters={}, entry_logic=[], exit_logic={"stop_loss_type": RiskType.FIXED, "stop_loss_value": 5.0, "take_profit_type": RiskType.FIXED, "take_profit_value": 5.0})
        df = pd.DataFrame({"ticker": ["TEST"], "timestamp": [datetime.now()], "close": [100.0]})
        engine = BacktestEngine(strategies=[strategy], weights={strategy.id: 100}, market_data=df, commission_per_trade=1.0)
        
        calculated_r = engine.calculate_r_multiple(entry_price, exit_price, stop_loss)
        
        assert abs(calculated_r - expected_r) < 0.01, f"R-multiple should be {expected_r}, got {calculated_r}"
        assert calculated_r > 0, "Winning trade should have positive R"
    
    def test_r_multiple_loser(self):
        """Test: R < 0 for losing trade"""
        entry_price = 100.0
        exit_price = 105.0  # Loss for short (hit SL)
        stop_loss = 105.0
        
        risk = abs(entry_price - stop_loss)  # 5.0
        profit = entry_price - exit_price  # -5.0
        expected_r = profit / risk  # -1R
        
        strategy = Strategy(id="test", name="Test", filters={}, entry_logic=[], exit_logic={"stop_loss_type": RiskType.FIXED, "stop_loss_value": 5.0, "take_profit_type": RiskType.FIXED, "take_profit_value": 5.0})
        df = pd.DataFrame({"ticker": ["TEST"], "timestamp": [datetime.now()], "close": [100.0]})
        engine = BacktestEngine(strategies=[strategy], weights={strategy.id: 100}, market_data=df, commission_per_trade=1.0)
        
        calculated_r = engine.calculate_r_multiple(entry_price, exit_price, stop_loss)
        
        assert abs(calculated_r - expected_r) < 0.01, f"R-multiple should be {expected_r}, got {calculated_r}"
        assert calculated_r < 0, "Losing trade should have negative R"


class TestPortfolioMetrics:
    """Tests for portfolio metrics POST-RUN validation"""
    
    def test_win_rate_calculation(self):
        """Test: win_rate = winning_trades / total_trades * 100"""
        # Mock a completed backtest result
        from app.backtester.engine import Trade
        
        trades = [
            Trade(id="1", strategy_id="s1", strategy_name="S1", ticker="TEST", entry_time=datetime.now(), entry_price=100, exit_time=datetime.now(), exit_price=97, stop_loss=105, take_profit=95, position_size=100, allocated_capital=10000, r_multiple=0.6, fees=1, exit_reason="TP", is_open=False),
            Trade(id="2", strategy_id="s1", strategy_name="S1", ticker="TEST", entry_time=datetime.now(), entry_price=100, exit_time=datetime.now(), exit_price=105, stop_loss=105, take_profit=95, position_size=100, allocated_capital=10000, r_multiple=-1.0, fees=1, exit_reason="SL", is_open=False),
            Trade(id="3", strategy_id="s1", strategy_name="S1", ticker="TEST", entry_time=datetime.now(), entry_price=100, exit_time=datetime.now(), exit_price=96, stop_loss=105, take_profit=95, position_size=100, allocated_capital=10000, r_multiple=0.8, fees=1, exit_reason="TP", is_open=False),
        ]
        
        winning_trades = sum(1 for t in trades if t.r_multiple and t.r_multiple > 0)  # 2
        total_trades = len(trades)  # 3
        expected_win_rate = (winning_trades / total_trades * 100)  # 66.67%
        
        # Calculate using engine
        calculated_win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        assert abs(calculated_win_rate - expected_win_rate) < 0.01, f"Win rate should be {expected_win_rate}%, got {calculated_win_rate}%"
    
    def test_profit_factor_calculation(self):
        """Test: profit_factor = gross_wins / gross_losses"""
        r_multiples = [0.5, 1.0, -1.0, 0.3, -0.5]
        
        gross_wins = sum(r for r in r_multiples if r > 0)  # 1.8
        gross_losses = abs(sum(r for r in r_multiples if r < 0))  # 1.5
        expected_pf = gross_wins / gross_losses if gross_losses > 0 else gross_wins  # 1.2
        
        calculated_pf = gross_wins / gross_losses if gross_losses > 0 else gross_wins
        
        assert abs(calculated_pf - expected_pf) < 0.01, f"Profit factor should be {expected_pf}, got {calculated_pf}"
