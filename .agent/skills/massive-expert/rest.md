# Massive API REST Reference

## Historical Data
Endpoints typically follow the pattern: `/v2/historic/{asset_class}/{type}/{ticker}/{date}`

### Dividends
`GET /v3/reference/stocks/corporate-actions/dividends`
- **Params**: `ticker`, `ex_dividend_date`, `order`, `limit`.

### Ticker Details
`GET /v3/reference/tickers/{ticker}`
- Returns fundamental data, market cap, and listing info.

## Snapshots
`GET /v2/snapshot/locale/us/markets/stocks/tickers`
- Returns the most recent trade, quote, and minute bar for all tickers.

## Technical Indicators
`GET /v1/indicators/{indicator}/{ticker}`
- Supports: `sma`, `ema`, `rsi`, `macd`.
