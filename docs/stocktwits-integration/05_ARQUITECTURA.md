# 05 — Arquitectura de Software

Este documento describe la estructura técnica de la integración de la API de Stocktwits, el flujo de datos y la persistencia en caché.

---

## 1. Estructura de Ficheros (Handoff Técnico)

El desarrollo se organizará de forma modular respetando los patrones de diseño establecidos en el repositorio:

### Backend (`backend/app/`)
*   **[NEW]** `services/stocktwits_service.py` - Cliente de API de Stocktwits, serialización de respuestas y lógica de almacenamiento en caché.
*   **[MODIFY]** `routers/news.py` - Se inyectará el router de Stocktwits o se creará un router nuevo `routers/social.py`. (Recomendación: crear `routers/social.py` y registrar en `main.py`).
*   **[MODIFY]** `main.py` - Registro del nuevo router `/api/market/social` bajo `app.include_router`.

### Frontend (`frontend/src/`)
*   **[NEW]** `components/SentimentGauge.tsx` - Componente velocímetro de sentimiento.
*   **[NEW]** `components/StocktwitsStream.tsx` - Pestaña de feed de debate filtrado.
*   **[NEW]** `components/RadarMomentum.tsx` - Tabla de Small Caps en tendencia.
*   **[MODIFY]** `lib/api.ts` - Añadir funciones de fetch correspondientes a los 5 endpoints.
*   **[MODIFY]** `components/TickerAnalysis.tsx` - Inclusión de `SentimentGauge` y `StocktwitsStream`.
*   **[MODIFY]** `components/Screener.tsx` - Enlace del Radar de Momentum en las tabs.

---

## 2. Flujo de Datos End-to-End

El siguiente diagrama detalla cómo se procesa una consulta a la API de sentimiento:

```
+---------------+           +-------------+           +------------------+           +--------------+
|   Frontend    |           |  Router API |           |    ST Service    |           |   DuckDB     |
| (Componente)  |           |  (FastAPI)  |           |     (Python)     |           | (users.db)   |
+---------------+           +-------------+           +------------------+           +--------------+
        |                          |                           |                            |
        |--- 1. getSentiment() --->|                           |                            |
        |    (via lib/api.ts)      |--- 2. _swr_cache() ------>|                            |
        |                          |    (read cache request)   |--- 3. SELECT payload ----->|
        |                          |                           |<-- 4. returns payload -----|
        |                          |                           |    (if exists)             |
        |                          |<-- 5. returns payload ----|                            |
        |<-- 6. Renders (stale) ---|    (síncrono, <10ms)      |                            |
        |                          |                           |                            |
        |                          |    [Si TTL expiró]        |                            |
        |                          |     Lanzar daemon thread  |                            |
        |                          |     (background refresh)  |                            |
        |                          |           |               |--- 7. Fetch Stocktwits --->| (External API)
        |                          |           |               |<-- 8. Returns JSON --------|
        |                          |           |               |                            |
        |                          |           |               |--- 9. INSERT OR REPLACE -->| (Update cache)
        |                          |           |               |    (users.duckdb)          |
```

---

## 3. Modelo de Persistencia y Caché (DuckDB)

Reusaremos la tabla `ticker_analysis_cache` en `users.duckdb` gestionada a través de locks compartidos para evitar conflictos de escritura concurrentes.

### Estructura de la caché en DuckDB:
*   `ticker`: El ticker oficial (ej: `"CRWD"`) o una clave global como `"TRENDING_SMALL_CAPS"` o `"NEWSLETTER_RSS"`.
*   `endpoint`: Identificador del recurso (ej: `"sentiment"`, `"summary"`, `"stream"`, `"trending"`, `"newsletter"`).
*   `payload`: El payload JSON limpio retornado por el backend.
*   `updated_at`: Timestamp de la última petición exitosa a Stocktwits.

El lock de DuckDB se obtendrá mediante `get_user_db_lock()` antes de instanciar `get_user_db_connection()`, garantizando consistencia transaccional.

---

## 4. Respeto a las Reglas de No Tocar (Core Isolation)

*   **Aislamiento del Motor:** El motor de backtesting (`backend/app/backtester/engine.py`) y las librerías JIT/NumPy se mantienen 100% aisladas. Esta feature social corre exclusivamente en la capa de servicios de red e interfaz.
*   **Independencia de DuckDB:** DuckDB soporta múltiples conexiones concurrentes pero es sensible al bloqueo de escritura. Por eso, el `stocktwits_service` usará conexiones rápidas transaccionales que se abren, ejecutan y cierran inmediatamente bajo un bloque `try...finally` asegurando liberar el lock de base de datos.
