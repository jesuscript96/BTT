import yfinance as yf
import time

t0 = time.time()
ticker = yf.Ticker("AAPL")
hist = ticker.history(period="1y")
print("Done in", time.time() - t0, "rows:", len(hist))
