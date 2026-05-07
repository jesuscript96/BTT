---
name: quant-shorts-expert
description: Expert in quantitative trading strategies specialized in short selling and backtesting.
category: Trading & Finance
---

# Quant Trading (Shorts) Specialist Skill

Knowledge module for developing and backtesting short-selling trading strategies.

## Short Selling Fundamentals

### 1. Borrowing Mechanics
- **Stock Loan**: To short, you must borrow shares first.
- **Hard to Borrow (HTB)**: Be aware of stocks with limited availability.
- **Margin Requirements**: 150% initial margin is common (Reg T).

### 2. Risk Management
- **Short Squeeze**: Rapid price rises forcing shorts to cover.
- **Daily Borrow Fees**: Cost of maintaining a short position over time.
- **Unlimited Risk**: Unlike long positions, shorts have theoretical infinite loss potential.

## Backtesting Frameworks (Python)

### 1. VectorBT / Backtesting.py
- **Vectorized Backtesting**: High speed for large datasets.
- **Trailing Stop-Loss**: Critical for protecting gains in short positions.

### 2. Modeling Borrow Fees
```python
# Example logic for modeling fees
daily_fee = position_value * (annual_borrow_rate / 360)
equity -= daily_fee
```

## Strategy Patterns
- **Mean Reversion**: Shorting assets that are significantly overextended (e.g., 2+ Standard Deviations from SMA).
- **Fundamental Decay**: Overvalued firms with deteriorating balance sheets.
- **Market Neutral**: Balancing long and short positions to eliminate market beta.

## Critical Checklist
- [ ] Are borrow fees included in the backtest?
- [ ] Are margin calls modeled?
- [ ] Is slippage adjusted for liquidity (wider spreads in HTB stocks)?
- [ ] Does the stop-loss account for overnight gaps?
