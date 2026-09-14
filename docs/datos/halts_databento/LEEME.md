# Halts de todo el mercado Nasdaq, 2019-01-02 → 2026-09-04 (Databento, dataset XNAS.ITCH, esquema `status`)

Descarga hecha el 11-sep-2026 por Jaume (script `25_status_mercado.py`, 1.930 días, 50,61 $ estimados).
Los CSV brutos por día (3,7 GB) no van aquí; esto es el resultado ya procesado (`28_halts_mercado_analisis.py`).

## halts_mercado_2019_2026.parquet / .csv — un halt por fila (278.976)
| columna | qué es |
|---|---|
| symbol | ticker ese día (Nasdaq reasigna instrument_id; el mapa es POR DÍA) |
| date | día |
| halt_ts | hora de parada, hora de Nueva York, sin zona |
| resume_ts | hora de reanudación (vacío = no reabrió ese día) |
| reason | código Nasdaq: 50 = LULD (volatilidad); 30 = T1 noticia pendiente; 32 = T2 noticia + hora; 70 = T12 Nasdaq pide información; 0 = sin abrir/otro; 10 regulatorio; 14 suspensión SEC; 40 desequilibrio; 120 MWCB |
| ssr | Y/N: restricción de venta en corto activa en ese momento |
| instrument_id | id interno de Nasdaq ese día |

## Trampas conocidas
- Los T1/T12 a las 19:45-19:55 son acciones corporativas (T1 = contrasplit que «reabre» ×100; T12 = baja por fusión), no halts reales. Filtrar por hora.
- Símbolos reutilizados o cambios de ticker generan reaperturas falsas (SMR, GOLD ×70): filtrar precio antes ≥ 0,5 $ y coherencia con el cierre anterior.
- Incluye warrants, units y when-issued (sufijos W, U, V…). Para acciones comunes / ADR cruzar con la tabla `tickers` del lago.
- Solo Nasdaq (XNAS). Halts de NYSE/AMEX no están.

## tras_reapertura_t1.csv / tras_reapertura_luld.csv (14-sep-2026, `34_tras_reapertura.py`)
Halts T1 y LULD que pararon y reabrieron entre 04:00 y 16:00 del mismo día, con precios de las velas de 1 min del lago:
px_antes (último cierre antes del halt), px_reap (open de la primera vela tras reabrir), reap_pct (reapertura vs antes),
max_tras_pct / min_tras_pct (máximo y mínimo del resto del día sobre px_reap), min_hasta_max (minutos desde la reapertura al máximo),
n5/n30/n60 (nivel a 5/30/60 min sobre px_reap), cierre_pct (cierre del día sobre px_reap), max_vs_antes_pct (máximo del día sobre px_antes).
