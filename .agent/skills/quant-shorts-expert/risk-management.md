# Quant Shorts: Risk Management & Backtesting

## Risk Management Best Practices
1.  **Stop-Loss Deployment**: Always use hard stop-losses. In shorts, "hope" is a liquidation strategy.
2.  **Position Sizing**: Limit short exposure per ticker to < 2% of total capital due to gap risk.
3.  **Short Squeeze Detection**: Monitor "Short Interest Ratio" and "Days to Cover". High metrics indicate extreme squeeze risk.

## Backtesting Pitfalls
- **Look-ahead Bias**: Ensure you aren't using tomorrow's data to trade today (e.g., using a daily close that hasn't happened yet).
- **Survivor Bias**: Testing only on companies that exist today (ignoring those that went bankrupt or were delisted, which are often the best short targets).

## Backtesting Template (Pseudo-code)
```python
class ShortStrategy(Strategy):
    def init(self):
        self.rsi = self.I(RSI, self.data.Close, 14)

    def next(self):
        if self.rsi > 70 and not self.position:
            self.sell() # Enter Short
        elif self.rsi < 30 and self.position:
            self.position.close() # Cover
```
