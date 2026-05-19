# Hot Storage — Especificación Técnica

## Objetivo

Pre-cachear el subset de datos más consultado para que el backtester responda en menos de 30 segundos en runs repetidos.

## Criterio de selección

### Datos intradía (1m bars)

- `gap_pct` entre 20% y 500%
- `price > $0.10` (sin límite superior)
- Volumen: sin restricción

Por cada día que cumpla el criterio, incluir una ventana de 6 trading days:

`[T-2] [T-1] [GAP DAY] [T+1] [T+2] [T+3]`

- Los días se cuentan en trading days, no días calendario
- Cada día incluye todas las sesiones: pre-market + RTH + after-hours

### Datos diarios (daily_metrics)

- Todos los registros sin filtro de gap ni precio
- Sin restricción de volumen

## Implementación actual

### Caché en RAM al arrancar

| Caché | Filas | Fuente | Tiempo |
|---|---|---|---|
| tickers | 27,159 | `massive.tickers` | ~1s |
| splits | 16,000 | `massive.splits` | ~0.7s |
| gap days | 31,188 | Parquet pre-construido en GCS | ~1s |

Startup total: ~2.5 segundos

### Parquet pre-construido

- **Ubicación en GCS:** `cold_storage/hot_cache/daily_metrics_gaps.parquet`
- **Columnas:** 30 columnas + 3 calculadas (`close_red`, `high_spike_pct`, `low_spike_pct`)
- **Tamaño en RAM:** ~7.3 MB (float32 + category)
- **Regenerar cuando haya nuevos datos:** `python scripts/generate_hot_cache_parquet.py`

### Fast path del screener

- Si `min_gap >= 20%` → sirve desde RAM (<100ms)
- Si `min_gap < 20%` → query a GCS (~33 seg)

## Resultados de performance

| Operación | Antes | Después |
|---|---|---|
| Startup hot cache | 216s | 1s |
| Screener gap ≥20% | 1-2 min | <100ms |
| Chart intradía aggregate | 2-3 min | 6.5s |

## Pendiente

- Implementar ventana [T-2, T+3] para intradía de gap days
- Regeneración automática del Parquet cuando lleguen datos nuevos
