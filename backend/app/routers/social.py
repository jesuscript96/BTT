"""
Router de la integración social de Stocktwits.

Expone los 5 endpoints del contrato (`docs/stocktwits-integration/03_CONTRATO_DATOS.md`)
bajo el prefijo `/api/market/social`. Toda la lógica de red, caché SWR y saneo
vive en `app/services/stocktwits_service.py`; aquí solo se valida la entrada, se
serializa el contrato Pydantic y se mapean los errores tipados a los códigos HTTP
(404/429/503) acordados.

Gating de monetización (DECISIÓN DIFERIDA a Jesús — ver 07_DECISIONES_ABIERTAS.md):
se deja el hook `require_pro_tier` como placeholder no-op. En el MVP todos los
endpoints son públicos; activar el gating en el futuro será cambiar la
implementación del hook SIN tocar las firmas de los endpoints.
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import List, Optional

from app.services import stocktwits_service as st

router = APIRouter(
    prefix="/api/market/social",
    tags=["social"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Placeholder de gating (no-op en MVP). Ver decisión diferida §A.1.
# ─────────────────────────────────────────────────────────────────────────────
def require_pro_tier() -> None:
    """Hook de tier Pro. MVP: público (no-op). Futuro: validar Clerk aquí."""
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Contratos Pydantic (salida)
# ─────────────────────────────────────────────────────────────────────────────
class TrendingItem(BaseModel):
    symbol: str
    name: str
    market_cap: Optional[float] = None
    daily_volume: Optional[float] = None
    trending_score: Optional[float] = None
    sentiment_score: Optional[int] = None
    price: Optional[float] = None
    change_pct: Optional[float] = None


class SummaryResponse(BaseModel):
    symbol: str
    why_trending: Optional[str] = None
    updated_at: str


class SentimentResponse(BaseModel):
    symbol: str
    sentiment_score: int
    sentiment_label: str
    message_volume_score: int
    message_volume_label: str
    updated_at: str


class StreamMessage(BaseModel):
    message_id: Optional[int] = None
    body: str
    created_at: str
    username: str
    avatar_url: str
    user_sentiment: Optional[str] = None
    likes_count: int


class NewsletterItem(BaseModel):
    title: str
    published_at: str
    author: str
    content_html: str
    charts: List[str] = []
    link: str


# ─────────────────────────────────────────────────────────────────────────────
# Mapeo de errores tipados → códigos del contrato
# ─────────────────────────────────────────────────────────────────────────────
def _handle_stocktwits_error(exc: Exception):
    if isinstance(exc, st.TickerNotFound):
        raise HTTPException(status_code=404, detail="TICKER_NOT_FOUND")
    if isinstance(exc, st.RateLimited):
        raise HTTPException(status_code=429, detail="RATE_LIMIT_EXCEEDED")
    if isinstance(exc, st.ApiUnavailable):
        raise HTTPException(status_code=503, detail="STOCKTWITS_API_UNAVAILABLE")
    # Cualquier otro fallo no esperado se propaga como 503 controlado (la UI
    # cae con elegancia a su estado vacío/offline en vez de romperse).
    raise HTTPException(status_code=503, detail="STOCKTWITS_API_UNAVAILABLE")


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/trending", response_model=List[TrendingItem])
def get_social_trending(_: None = Depends(require_pro_tier)):
    """Radar de Momentum: small caps (< $2,000M) en tendencia social."""
    try:
        return st.get_trending()
    except st.StocktwitsError as e:
        _handle_stocktwits_error(e)


@router.get("/ticker/{symbol}/summary", response_model=SummaryResponse)
def get_social_summary(symbol: str, _: None = Depends(require_pro_tier)):
    """Why It's Trending: catalizador en lenguaje natural."""
    try:
        return st.get_summary(symbol)
    except st.StocktwitsError as e:
        _handle_stocktwits_error(e)


@router.get("/ticker/{symbol}/sentiment", response_model=SentimentResponse)
def get_social_sentiment(symbol: str, _: None = Depends(require_pro_tier)):
    """Sentiment Gauge: sentimiento + volumen de mensajes a 15m."""
    try:
        return st.get_sentiment(symbol)
    except st.StocktwitsError as e:
        _handle_stocktwits_error(e)


@router.get("/ticker/{symbol}/stream", response_model=List[StreamMessage])
def get_social_stream(
    symbol: str,
    limit: int = Query(default=st.DEFAULT_STREAM_LIMIT, ge=1, le=st.MAX_STREAM_LIMIT),
    _: None = Depends(require_pro_tier),
):
    """Zona de Debate Limpia: hilos populares filtrados de spam."""
    try:
        return st.get_stream(symbol, limit=limit)
    except st.StocktwitsError as e:
        _handle_stocktwits_error(e)


@router.get("/newsletter", response_model=List[NewsletterItem])
def get_social_newsletter(_: None = Depends(require_pro_tier)):
    """Newsletters & Chart Art: agregador RSS formateado en JSON."""
    try:
        return st.get_newsletter()
    except st.StocktwitsError as e:
        _handle_stocktwits_error(e)
