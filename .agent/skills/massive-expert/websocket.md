# Massive WebSocket Reference

## Connection
- **URL**: `wss://socket.massive.com`
- **Auth**: Send action `auth` with your API key immediately after connection.

## Subscriptions
Send action `subscribe` with params for specific streams:
- `T.*`: All trades
- `Q.*`: All quotes
- `A.*`: Second aggregates
- `AM.*`: Minute aggregates

### Example Message
```json
{
  "action": "subscribe",
  "params": "T.TSLA,Q.AAPL"
}
```

## Response Messages
Messages are delivered as an array of objects:
- `ev`: Event type (e.g., `T` for trade)
- `sym`: Ticker symbol
- `p`: Price
- `s`: Size
- `t`: Timestamp (Unix MS)
