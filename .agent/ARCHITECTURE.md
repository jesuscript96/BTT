# Arquitectura

## Stack
- Frontend: Next.js 16, React 19, Tailwind 4
- Backend: FastAPI, Python 3.13
- Base de datos: Google Cloud Storage (Parquet) + DuckDB httpfs
- Charts: recharts, lightweight-charts (BTT), Plotly (backtester2)
- Backtester: Numpy, Numba JIT, Pandas
- Deploy FE: Vercel
- Deploy BE: Hetzner

## Estructura backend BTT
app/
├── routers/      ← solo endpoints, sin lógica de negocio
├── services/     ← lógica de negocio y procesamiento
├── backtester/   ← motor de simulación (engine, indicators, metrics)
├── schemas/      ← modelos Pydantic
└── database.py   ← conexión DuckDB/GCS

## Decisiones técnicas clave
- DuckDB lee Parquet en GCS vía httpfs con autenticación HMAC
- users.duckdb: almacena estrategias y queries del usuario (se sincroniza a GCS)
- El backtester corre como BackgroundTask de FastAPI con polling desde el frontend
- Chunks por mes para evitar límites de memoria en universos grandes
- Numba JIT (@njit) para el bucle bar-by-bar del engine

## Hot Storage en RAM
- **Tickers y splits**: cargados en startup vía `cache_service.py` (27K y 16K filas, <1s)
- **Gap days (daily_metrics donde gap≥20%)**: Parquet pre-filtrado en GCS (`cold_storage/hot_cache/daily_metrics_gaps.parquet`). 31K filas, 7.3 MB. Carga en <1s vs 216s del scan completo.
- **Columnas calculadas en hot cache**: `close_red`, `high_spike_pct`, `low_spike_pct` se derivan de columnas existentes al cargar.
- **Fast path en screener**: cuando `min_gap ≥ 20`, el endpoint `/market/screener` sirve desde RAM en <100ms (400x más rápido que GCS).
- **Actualización**: ejecutar `scripts/generate_hot_cache_parquet.py` para regenerar el Parquet cuando lleguen nuevos datos a GCS.

## Lo que NO existe aún
- Autenticación/autorización
- Rate limiting
- CI/CD
- Docker
- Tests automatizados
