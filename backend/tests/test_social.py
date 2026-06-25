"""
Tests de la integración social de Stocktwits (capa de ingesta + caché SWR).

Filosofía: estos tests NO tocan la red ni DuckDB. Se mockea la capa HTTP de
bajo nivel del servicio (`_http_get_json` / `_http_get_text`) con payloads
canónicos representativos de la API de Stocktwits, y se verifica que el
servicio los mapea EXACTAMENTE al contrato de datos definido en
`docs/stocktwits-integration/03_CONTRATO_DATOS.md`.

Convención de nombres: las pruebas del EPIC 1 (servicio) incluyen "Tarea1" en
el nombre para poder filtrarlas con `pytest tests/test_social.py -k Tarea1`.
"""
import sys
from pathlib import Path

import pytest

# El servicio se importa por su nombre de paquete `app.*` igual que el resto
# de la suite (conftest.py inserta backend/ en sys.path).
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.services import stocktwits_service as st  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Payloads canónicos (forma cruda esperada de la API oficial de Stocktwits)
# ─────────────────────────────────────────────────────────────────────────────

RAW_TRENDING = {
    "symbols": [
        {
            # Small cap (1,850.4M < 2,000M) → se conserva
            "symbol": "CRWD",
            "title": "CrowdStrike Holdings",
            "trending_score": 92.4,
            "price": 12.45,
            "change_percent": 18.5,
            "volume": 4200150.0,
            "market_cap": 1_850_400_000.0,
            "sentiment_score": 82,
        },
        {
            # Small cap pequeña sin sentimiento → sentiment_score null
            "symbol": "XYZ",
            "title": "XYZ Biotech",
            "trending_score": 87.1,
            "price": 3.10,
            "change_percent": 5.2,
            "volume": 900000.0,
            "market_cap": 450_000_000.0,
            "sentiment_score": None,
        },
        {
            # Large cap (2,900,000M >> 2,000M) → DEBE filtrarse por el backend
            "symbol": "AAPL",
            "title": "Apple Inc.",
            "trending_score": 99.0,
            "price": 195.0,
            "change_percent": 0.8,
            "volume": 50000000.0,
            "market_cap": 2_900_000_000_000.0,
            "sentiment_score": 70,
        },
    ]
}

RAW_SUMMARY = {
    "symbol": "CRWD",
    "summary": (
        "CrowdStrike ($CRWD) is experiencing a surge in attention due to its "
        "Q1 earnings beat and raised full-year guidance."
    ),
    "updated_at": "2026-06-25T01:40:00Z",
}

RAW_SENTIMENT = {
    "symbol": "CRWD",
    "sentiment_score": 85,
    "message_volume_score": 78,
}

RAW_STREAM = {
    "messages": [
        {
            # Cumple el filtro (likes >= 2, 1 ticker) → se conserva
            "id": 987654321,
            "body": "<p>CRWD volume is surging in premarket. Squeeze over 12.50.</p>",
            "created_at": "2026-06-25T01:41:05Z",
            "user": {"username": "TraderJoe", "avatar_url": "https://avatars.stocktwits.com/traderjoe.jpg"},
            "entities": {"sentiment": {"basic": "Bullish"}},
            "likes": {"total": 5},
            "symbols": [{"symbol": "CRWD"}],
        },
        {
            # likes < MIN_LIKES_THRESHOLD → se descarta (anti-spam)
            "id": 11111,
            "body": "to the moon!!!",
            "created_at": "2026-06-25T01:30:00Z",
            "user": {"username": "botspam", "avatar_url": ""},
            "entities": {"sentiment": None},
            "likes": {"total": 0},
            "symbols": [{"symbol": "CRWD"}],
        },
        {
            # menciona > 3 tickers → se descarta (pump & dump)
            "id": 22222,
            "body": "$CRWD $AAA $BBB $CCC $DDD all running!",
            "created_at": "2026-06-25T01:20:00Z",
            "user": {"username": "pumper", "avatar_url": ""},
            "entities": {"sentiment": {"basic": "Bullish"}},
            "likes": {"total": 9},
            "symbols": [
                {"symbol": "CRWD"}, {"symbol": "AAA"}, {"symbol": "BBB"},
                {"symbol": "CCC"}, {"symbol": "DDD"},
            ],
        },
    ]
}

RAW_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Stocktwits Newsletter</title>
    <item>
      <title>Chart Art: A Small Cap Breakthrough</title>
      <pubDate>Tue, 24 Jun 2026 18:00:00 GMT</pubDate>
      <author>Chart Art</author>
      <link>https://stocktwits.com/newsletter/chart-art-xyz-breakout</link>
      <description><![CDATA[<p>Analyzing the breakout on $XYZ...</p><img src="https://charts.stocktwits.com/chart_123.png" />]]></description>
    </item>
  </channel>
</rss>
"""


# ─────────────────────────────────────────────────────────────────────────────
# EPIC 1 · Tarea 1 — Mapeo y filtrado del servicio (sin red, sin DB)
# ─────────────────────────────────────────────────────────────────────────────

def test_tarea1_trending_maps_and_filters_small_caps():
    # Prueba el mapeo/filtrado de la forma {symbols:[...]} (endpoint dedicado),
    # independiente del proveedor activo.
    rows = st._map_trending_payload(RAW_TRENDING)

    # AAPL (large cap) eliminada; quedan CRWD y XYZ
    symbols = [r["symbol"] for r in rows]
    assert "AAPL" not in symbols
    assert symbols == ["CRWD", "XYZ"]

    crwd = rows[0]
    assert crwd["name"] == "CrowdStrike Holdings"
    assert crwd["market_cap"] == pytest.approx(1850.4)   # convertido a millones
    assert crwd["daily_volume"] == pytest.approx(4200150.0)
    assert crwd["trending_score"] == pytest.approx(92.4)
    assert crwd["sentiment_score"] == 82
    assert crwd["price"] == pytest.approx(12.45)
    assert crwd["change_pct"] == pytest.approx(18.5)

    # contrato: sentiment_score puede ser null
    assert rows[1]["sentiment_score"] is None


def test_tarea1_summary_maps_why_trending(monkeypatch):
    monkeypatch.setattr(st, "_http_get_json", lambda *a, **k: RAW_SUMMARY)
    out = st.fetch_summary("crwd")
    assert out["symbol"] == "CRWD"
    assert out["why_trending"].startswith("CrowdStrike ($CRWD)")
    assert out["updated_at"]


def test_tarea1_summary_null_when_no_catalyst(monkeypatch):
    monkeypatch.setattr(st, "_http_get_json", lambda *a, **k: {"symbol": "CRWD"})
    out = st.fetch_summary("CRWD")
    assert out["why_trending"] is None


def test_tarea1_sentiment_maps_scores_and_labels(monkeypatch):
    monkeypatch.setattr(st, "_http_get_json", lambda *a, **k: RAW_SENTIMENT)
    out = st.fetch_sentiment("CRWD")
    assert out["symbol"] == "CRWD"
    assert out["sentiment_score"] == 85
    assert out["sentiment_label"] == "Bullish"
    assert out["message_volume_score"] == 78
    assert out["message_volume_label"] == "High"
    assert out["updated_at"]


@pytest.mark.parametrize("score,label", [(85, "Bullish"), (52, "Neutral"), (20, "Bearish")])
def test_tarea1_sentiment_label_thresholds(score, label):
    assert st._sentiment_label(score) == label


@pytest.mark.parametrize("score,label", [(78, "High"), (45, "Medium"), (10, "Low")])
def test_tarea1_volume_label_thresholds(score, label):
    assert st._volume_label(score) == label


def test_tarea1_stream_filters_spam_and_sanitizes(monkeypatch):
    monkeypatch.setattr(st, "_http_get_json", lambda *a, **k: RAW_STREAM)
    msgs = st.fetch_stream("CRWD", limit=15)

    # Solo el mensaje legítimo sobrevive (likes>=2, <=3 tickers)
    assert len(msgs) == 1
    m = msgs[0]
    assert m["message_id"] == 987654321
    assert m["username"] == "TraderJoe"
    assert m["likes_count"] == 5
    assert m["user_sentiment"] == "Bullish"
    assert m["avatar_url"].startswith("https://")
    # cuerpo sin tags HTML
    assert "<p>" not in m["body"]
    assert m["body"].startswith("CRWD volume is surging")


def test_tarea1_stream_respects_limit(monkeypatch):
    many = {"messages": [
        {
            "id": i, "body": "ok body", "created_at": "2026-06-25T01:41:05Z",
            "user": {"username": f"u{i}", "avatar_url": ""},
            "entities": {"sentiment": None}, "likes": {"total": 10},
            "symbols": [{"symbol": "CRWD"}],
        } for i in range(40)
    ]}
    monkeypatch.setattr(st, "_http_get_json", lambda *a, **k: many)
    assert len(st.fetch_stream("CRWD", limit=5)) == 5


def test_tarea1_newsletter_maps_rss_and_extracts_charts(monkeypatch):
    monkeypatch.setattr(st, "_http_get_text", lambda *a, **k: RAW_RSS)
    items = st.fetch_newsletter()
    assert len(items) == 1
    it = items[0]
    assert it["title"] == "Chart Art: A Small Cap Breakthrough"
    assert it["author"] == "Chart Art"
    assert it["link"].startswith("https://stocktwits.com/")
    assert it["published_at"]
    assert "https://charts.stocktwits.com/chart_123.png" in it["charts"]


# ─────────────────────────────────────────────────────────────────────────────
# EPIC 1 · Tarea 1 — Resiliencia: errores tipados ante caídas de la API
# ─────────────────────────────────────────────────────────────────────────────

def test_tarea1_ticker_not_found_raises_typed(monkeypatch):
    def _raise(*a, **k):
        raise st.TickerNotFound("no listada")
    monkeypatch.setattr(st, "_http_get_json", _raise)
    with pytest.raises(st.TickerNotFound):
        st.fetch_sentiment("NOPE")


def test_tarea1_no_credentials_returns_safe_default(monkeypatch):
    # Sin credenciales (de ningún proveedor) el servicio no debe explotar ni
    # tocar la red: trending vacío.
    monkeypatch.setattr(st, "STOCKTWITS_API_KEY", "")
    monkeypatch.setattr(st, "STOCKTWITS_API_SECRET", "")
    monkeypatch.setattr(st, "STOCKTWITS_RAPIDAPI_KEY", "")
    assert st.fetch_trending_small_caps() == []
