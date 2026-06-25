# 03 — Contrato de Datos

Este documento define la estructura de datos que viaja entre el frontend y el backend de Edgecute para la integración de Stocktwits. Todos los endpoints se encuentran bajo el prefijo `/api`.

---

## Endpoints de la API de Edgecute (Backend)

### 1. GET /api/market/social/trending
Devuelve la lista de Small Caps en tendencia social (filtradas por capitalización menor a $2B).

*   **Request Params:** Ninguno (Filtro automático en backend).
*   **Response (List of objects):**
    *   `symbol` (str): El ticker oficial (ej: "VRT").
    *   `name` (str): Nombre de la compañía.
    *   `market_cap` (float): Capitalización de mercado en millones de USD.
    *   `daily_volume` (float): Volumen operado en la sesión de hoy.
    *   `trending_score` (float): Score de tracción social en Stocktwits.
    *   `sentiment_score` (int | null): Sentimiento a 15m (1-100), o `null` si no hay mensajes.
    *   `price` (float | null): Precio de cotización en tiempo real.
    *   `change_pct` (float | null): Cambio porcentual del día.

#### Ejemplo de Response:
```json
[
  {
    "symbol": "CRWD",
    "name": "CrowdStrike Holdings",
    "market_cap": 1850.4,
    "daily_volume": 4200150.0,
    "trending_score": 92.4,
    "sentiment_score": 82,
    "price": 12.45,
    "change_pct": 18.5
  }
]
```

---

### 2. GET /api/market/social/ticker/{symbol}/summary
Devuelve la explicación en lenguaje natural del porqué la acción está en tendencia.

*   **Request Params:**
    *   `symbol` (str, path): Símbolo de la acción.
*   **Response:**
    *   `symbol` (str): Ticker.
    *   `why_trending` (str | null): Resumen sintético del catalizador fundamental, o `null` si no está en tendencia crítica.
    *   `updated_at` (str): Timestamp ISO 8601 de la última actualización en caché.

#### Ejemplo de Response:
```json
{
  "symbol": "CRWD",
  "why_trending": "CrowdStrike ($CRWD) is experiencing a surge in attention due to its Q1 earnings beat and raised full-year guidance.",
  "updated_at": "2026-06-25T01:40:00Z"
}
```

---

### 3. GET /api/market/social/ticker/{symbol}/sentiment
Devuelve el sentimiento detallado a corto plazo (15 minutos) y el volumen de mensajes.

*   **Request Params:**
    *   `symbol` (str, path): Símbolo de la acción.
*   **Response:**
    *   `symbol` (str): Ticker.
    *   `sentiment_score` (int): Sentimiento normalizado de 1 a 100 (Bearish to Bullish).
    *   `sentiment_label` (str): Etiqueta descriptiva (`Bullish` | `Bearish` | `Neutral`).
    *   `message_volume_score` (int): Volumen normalizado de 1 a 100.
    *   `message_volume_label` (str): Etiqueta descriptiva (`High` | `Medium` | `Low`).
    *   `updated_at` (str): Timestamp de caché.

#### Ejemplo de Response:
```json
{
  "symbol": "CRWD",
  "sentiment_score": 85,
  "sentiment_label": "Bullish",
  "message_volume_score": 78,
  "message_volume_label": "High",
  "updated_at": "2026-06-25T01:42:00Z"
}
```

---

### 4. GET /api/market/social/ticker/{symbol}/stream
Devuelve los hilos y mensajes más populares libres de spam.

*   **Request Params:**
    *   `symbol` (str, path): Símbolo de la acción.
    *   `limit` (int, query): Opcional. Límite de mensajes (default: 15, max: 50).
*   **Response (List of objects):**
    *   `message_id` (int): Identificador único del mensaje.
    *   `body` (string): Contenido del mensaje en texto plano (tags HTML eliminados).
    *   `created_at` (str): Timestamp de publicación.
    *   `username` (str): Nombre del usuario en Stocktwits.
    *   `avatar_url` (str): URL de la imagen de perfil del usuario.
    *   `user_sentiment` (str | null): Sentimiento declarado por el usuario (`Bullish` | `Bearish` | `null`).
    *   `likes_count` (int): Cantidad de likes.

#### Ejemplo de Response:
```json
[
  {
    "message_id": 987654321,
    "body": "CRWD volume is surging in premarket. Looking for a squeeze over 12.50.",
    "created_at": "2026-06-25T01:41:05Z",
    "username": "TraderJoe",
    "avatar_url": "https://avatars.stocktwits.com/traderjoe.jpg",
    "user_sentiment": "Bullish",
    "likes_count": 5
  }
]
```

---

### 5. GET /api/market/social/newsletter
Agregador RSS de boletines formatados en JSON.

*   **Request Params:** Ninguno.
*   **Response (List of objects):**
    *   `title` (str): Título del boletín (ej: "Chart Art: Tesla Double Bottom").
    *   `published_at` (str): Fecha de publicación.
    *   `author` (str): Autor o publicación (ej: "Stocktwits Editorial").
    *   `content_html` (str): Contenido HTML sanitizado y formateado.
    *   `charts` (List[str]): Listado de URLs de las imágenes de gráficos extraídas del HTML para renderizado nativo.
    *   `link` (str): Enlace original.

#### Ejemplo de Response:
```json
[
  {
    "title": "Chart Art: A Small Cap Breakthrough",
    "published_at": "2026-06-24T18:00:00Z",
    "author": "Chart Art",
    "content_html": "<p>Analyzing the breakout on $XYZ...</p>",
    "charts": [
      "https://charts.stocktwits.com/chart_123.png"
    ],
    "link": "https://stocktwits.com/newsletter/chart-art-xyz-breakout"
  }
]
```

---

## Catálogo de Códigos de Error

El backend capturará fallos de comunicación con Stocktwits y devolverá códigos estructurados de error para que el frontend los maneje con elegancia:

| Código HTTP | Detalle (`detail`) | Causa | Acción en Frontend |
|---|---|---|---|
| **404** | `TICKER_NOT_FOUND` | El ticker ingresado no existe en Stocktwits. | Mostrar mensaje: *"Acción no listada en redes."* |
| **429** | `RATE_LIMIT_EXCEEDED` | Límite de peticiones de Stocktwits agotado y no hay caché disponible. | Mostrar advertencia: *"Picos de tráfico. Cargando datos locales..."* |
| **503** | `STOCKTWITS_API_UNAVAILABLE` | Caída del servicio externo de Stocktwits. | Utilizar caché existente en DuckDB y notificar *"Modo Offline: datos de hace X min."* |
