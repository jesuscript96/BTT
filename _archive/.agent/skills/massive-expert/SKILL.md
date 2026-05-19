---
name: massive-expert
description: Expert in Massive API (REST & WebSocket) for market data, stocks, options, and crypto.
category: Financial API
---

# Massive API Expert Skill

Skills and knowledge for integrating with the Massive API for high-frequency and historical financial data.

## Core Concepts

### 1. Authentication
Massive uses API Keys. Authenticate via:
- **Header**: `Authorization: Bearer YOUR_API_KEY`
- **Query**: `?apiKey=YOUR_API_KEY`

### 2. Base URLs
- **REST**: `https://api.massive.com`
- **WebSocket**: `wss://socket.massive.com`

## Endpoints Catalog

### Stocks
- **Dividends**: `/v3/reference/stocks/corporate-actions/dividends`
- **Trades**: `/v2/ticks/stocks/trades/{ticker}`
- **Quotes**: `/v2/ticks/stocks/nbbo/{ticker}`
- **Snapshots**: `/v2/snapshot/locale/us/markets/stocks/tickers`

### Options
- **Quotes**: `/v3/quotes/options/{ticker}`
- **Chain**: `/v3/snapshot/options/{underlyingTicker}`

### Crypto
- **Exchanges**: `/v3/reference/crypto/exchanges`
- **Trades**: `/v1/historic/crypto/{from}/{to}/{date}`

## Best Practices
- **Rate Limiting**: Monitor `X-RateLimit-*` headers to avoid 429 errors.
- **Pagination**: Use `cursor` for large datasets.
- **WebSocket**: Always handle reconnection logic and heartbeat pings.
- **Data Integrity**: Verify `request_id` for traceability.
