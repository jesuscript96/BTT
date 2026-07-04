# PRD — Screener: métricas de DÍA vs SESIÓN (persistencia + Aftermarket real)

**Rama:** `screener` · **Archivos:** `backend/app/services/live_screener_service.py`, `backend/tests/test_live_screener_service.py`, `backend/app/routers/screener.py`, `frontend/src/lib/api.ts`, `frontend/src/components/Screener.tsx`
**Estado:** Ejecutable. Fuentes de datos verificadas contra la API real de Massive (snapshot bulk, 12.919 tickers).

---

## 1. Problema

Hoy los tickers **desaparecen** al cambiar de sesión (p.ej. RTH→Aftermarket) y el tab **Aftermarket** muestra los mismos movers del día entero en vez de los que se mueven *ahora* en after-hours. Causas raíz en `live_screener_service.py`:

1. `session_volume`, `session_high`, `session_low` y `last_price` se **resetean en cada cambio de sesión** (`_reset_session`), dejando un window sin datos → el ticker sale temporalmente del top.
2. No existe `after_pct` (movimiento real desde el close de RTH). El tab Aftermarket filtra por `change_pct` del día OR un gap de session-high, así que un ticker que subió en RTH pero está plano en after aparece en "Aftermarket".
3. `amh_gap_pct` == `pmh_gap_pct` (ambos = `session_high/prev_close`): no distinguen pre vs after.

El screener de referencia (capturas) resuelve esto **sin truco de persistencia**: cada tab mide su ventana temporal y las métricas **del día nunca se resetean** entre sesiones.

## 2. Fuentes de datos (verificado contra Massive)

El snapshot REST `GET /v2/snapshot/locale/us/markets/stocks/tickers` entrega, por ticker:
- `prevDay.c` → **prev_close** (cierre del día anterior). Base de `day_change_pct`.
- `day.o/h/l/c/v` → **day_open, day_high, day_low, rth_close (day.c), day_volume**.
  - **`day.c` se congela al close de RTH (16:00 ET)**: en after-hours NO se actualiza con el last extendido. Confirmado: 2.801 tickers con after-actividad tienen `day.c ≠ lastTrade.p`.
- `lastTrade.p` → **last_price** (en after-hours, es el último print extendido).

El WS de aggregates `A.*` (cuando conecta) refresca en tiempo real: `last_price`, `day_high/low` (max/min), `day_volume` (`a` = acumulado diario), y suma volumen/high a la ventana de la sesión del timestamp (`pre`/`after`).

**Consecuencia clave:** `after_pct = last_price / rth_close − 1` se computa **desde el snapshot REST**, sin WS. El tab Aftermarket se puede probar hoy en local.

## 3. Modelo de datos nuevo (`TickerLiveState`)

Métricas **del DÍA** (persistentes todo el día; reset **solo al cambiar de día**, no de sesión):
| Campo | Origen | Notas |
|---|---|---|
| `prev_close` | `prevDay.c` | base del day_change |
| `rth_close` | `day.c` (+ cross-check en transición rth→after) | base del after_pct |
| `day_open` | `day.o` (antes `rth_open`) | base del gap/return |
| `day_high`, `day_low` | `day.h`, `day.l` (antes `session_high/low`) | |
| `day_volume` | `day.v` (antes `session_volume`) | |
| `last_price` | `lastTrade.p` / WS `c` | global, no se resetea entre sesiones |
| `avg_vol_20d` | DuckDB | RVol |

Métricas **de SESIÓN** (acumuladas solo en su ventana; se inicializan al entrar a esa sesión):
| Campo | Ventana | Origen |
|---|---|---|
| `after_volume`, `after_high`, `after_low` | 16:00–20:00 ET | WS aggregates en after (snapshot no las da → `None` en fallback REST) |
| `pre_volume`, `pre_high` | 04:00–09:30 ET | WS aggregates en pre |

> `rth_open`/`session_high`/`session_low`/`session_volume` se **renombran** a `day_open`/`day_high`/`day_low`/`day_volume` para reflejar que son del día. El `rth_close` ya existe (añadido en el freeze/reset).

## 4. Métricas derivadas (`_metrics`)

```
day_change_pct = (last_price / prev_close  − 1) · 100      # movimiento del DÍA
gap_pct        = (day_open   / prev_close  − 1) · 100      # gap al open de RTH
return_pct     = (last_price / day_open    − 1) · 100      # retorno intra-RTH
after_pct      = (last_price / rth_close   − 1) · 100      # movimiento en AFTER (desde close RTH)
pre_pct        = (pre_high   / prev_close  − 1) · 100      # pico de pre-market (proxy si arranca fuera de pre)
```

Salida por ticker (contrato WS): `ticker, name, price, prev_close, day_change_pct, gap_pct, return_pct, after_pct, after_volume, after_high, pre_pct, pre_volume, day_volume, day_high, day_low, rvol`.
> Se conserva `change_pct = day_change_pct` y `volume = day_volume` por compatibilidad con el frontend actual.

## 5. `get_top` por tab (umbrales SIN cambiar — son de negocio)

Se mantiene `MIN_VOLUME = 25_000` y `MIN_CHANGE_PCT = 20.0` (no se introducen umbrales nuevos):
| Tab | Filtro | Gate de volumen | Orden |
|---|---|---|---|
| `RTH Gainers` | `day_change_pct >= 20` | `day_volume >= 25k` | `day_change_pct` desc |
| `RTH Losers` | `day_change_pct <= -20` | `day_volume >= 25k` | `day_change_pct` asc |
| `Premarket` | `day_change_pct >= 20 OR pre_pct >= 20` | `day_volume >= 25k` | `pre_pct` desc (fallback `day_change_pct`) |
| `Aftermarket` | `after_pct >= 20` | `day_volume >= 25k` | `after_pct` desc |

> El tab Aftermarket solo muestra tickers que **de verdad se mueven >= 20% en after** ( fiel al "scanner del AHORA"). `after_volume`/`after_high` llegan solo vía WS; en fallback REST se muestran como "—".

## 6. Reset de sesión → reset de DÍA

- Renombrar `_reset_session` → `_reset_day`. Se invoca **solo en la transición `closed → (pre/rth/after)`** (cambio de día), no en cada cambio de sesión.
- `_reset_day`: limpia `day_*`, `after_*`, `pre_*`, `rth_close=None`; pasa `rth_close` capturado → `prev_close`; re-snapshotea.
- En transiciones intra-día (`pre→rth`, `rth→after`) **no se resetea nada del día**; solo se inicializan los acumuladores de la sesión que empieza (`after_*=None/0` al entrar a after).
- `_capture_rth_close` (transición `rth→after`) se mantiene como cross-check; el snapshot ya puebla `rth_close = day.c`.

## 7. Frontend

- `ScreenerRecord` (api.ts): añadir opcionales `after_pct?`, `after_volume?`, `after_high?`, `pre_pct?`, `pre_volume?`, `day_change_pct?`.
- Columnas por tab (`COLUMNS_BY_TAB` en Screener.tsx):
  - **Aftermarket**: `ticker, price, change_pct (día), after_pct (Aftermarket %), prev_close, day_volume, after_volume (After Vol), after_high (After High)`.
  - **Premarket**: `ticker, price, pre_pct (Pre %), change_pct, prev_close, day_volume, pre_volume, pre_high`.
  - **Gainers/Losers**: sin cambios (ya son métricas del día).
- Sort por defecto Aftermarket = `after_pct` desc; Premarket = `pre_pct` desc.
- Header: ya muestra `session · N tickers` y el pill "Cierre · congelado".

## 8. Tests (`test_live_screener_service.py`)

- `_metrics` calcula `after_pct` correctamente con `rth_close` del snapshot (`day.c`).
- Tab Aftermarket **solo** incluye tickers con `after_pct >= 20` (un ticker +30% en RTH pero 0% en after **no** aparece).
- Top Gainers **persiste** al pasar de sesión: tras `pre→rth→after` (sin `_reset_day`) los day-movers siguen en la lista.
- `_reset_day` se invoca solo en `closed→pre`, no en `rth→after`.
- Sin `rth_close`, `after_pct` es `None` y el ticker no aparece en Aftermarket (no cae a day_change).

## 9. Verificación en local

**Hoy (after-hours, WS caído por max_connections):**
- Top Gainers/Losers: tickers visibles vía REST, `change_pct` = día.
- Aftermarket: tickers con `after_pct >= 20` reales (move desde close RTH); `After Vol`/`After High` = "—" hasta que el WS conecte.
- Cambio pre→rth→after (si el backend vive el ciclo): los day-movers **no desaparecen**.

**Día completo de mercado (cuando el WS conecte / key aislada):**
- Aftermarket con `After Vol`/`After High` en tiempo real.
- Premarket con `pre_pct` real.

## 10. Out of scope (F2)
- after_volume/after_high vía REST (endpoint de aggregates bulk).
- Calendario de festivos para `current_session`.
- Persistencia de `day_*` a disco para sobrevivir reinicios en medio del día.
