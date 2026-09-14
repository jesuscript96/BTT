# Fase 1 — Reproducción controlada de BUG A (PM High Gap en vivo)

> Resultado de la Fase 1: el "no entra bien" queda convertido en un **caso reproducible,
> con código y datos reales**. Este es el "test que falla" que la Fase 2 (simulador) debe
> reproducir y que la Fase 3 (fix) debe hacer pasar.
>
> Fecha: 2026-09-10. Ver también `HALLAZGOS.md` §3 y `docs/alarmas/README.md`.

## La cadena del fallo (probada)

```
universo de la alarma filtra por PM High Gap ≥ 50
   → pre_high (máx. de premarket) del live screener es SOLO memoria, sin backfill
   → si el backend arrancó DESPUÉS del máximo real, pre_high sale bajo (o None)
   → pmh_gap_pct sale por debajo de 50
   → el ticker NO pasa el filtro de universo
   → nunca entra en watched_tickers
   → la alarma nunca dispara   ← "no entra bien"
```

## F1.1 — Evidencia en el código (`backend/app/services/`)

- `live_screener_service.py:594` — `pre_high` **solo lo escribe el handler del WS** (rama premarket):
  `st.pre_high = hi if st.pre_high is None else max(st.pre_high, hi)`.
- `live_screener_service.py:383` — `_refresh_from_snapshot` siembra `day_high` desde el `day.h`
  del snapshot REST, **pero NO toca `pre_high`** → no hay backfill por REST.
- `live_screener_service.py:466,470` — `_reset_day` pone `pre_high=None` y vuelve a llamar al
  snapshot, que **tampoco lo restaura**.
- `live_screener_service.py:618` — `pre_pct = ((st.pre_high / prev - 1)*100) if st.pre_high else None`.
- `engine.py:516` — el motor mapea `pmh_gap_pct = pre_pct` del screener.
- `engine.py:255-265` — el filtro de universo (`evaluate(plan["universe"], ctx)`) descarta al
  ticker que no cumple → no se añade a `watched`.

→ El gate del universo depende de un `pre_high` de solo-memoria. Cualquier reinicio (deploy, OOM)
pierde el máximo acumulado y no se recupera.

## F1.2 — Evidencia en los datos: BAOS, 2026-09-04

Consultado en prod (GCS `daily_metrics` + `intraday_1m`):

| Dato | Valor |
|---|---|
| `prev_close` | 0,2807 |
| **PM high real** (barras de minuto 04:00–09:30) | **0,4372** |
| **`pmh_gap_pct` real** | **+55,75 %** |
| **Hora del PM high** | **04:00 ET (la PRIMERA barra de premarket)** |
| gap en apertura RTH | +22,98 % |

El máximo real ocurrió en el minuto **04:00**. El día del incidente se desplegó *durante* el
premarket → el backend reinició **después** de las 04:00 → `pre_high` solo capturó barras
posteriores (más bajas) → el screener mostró **+26,86 %** en vez de **+55,75 %**.

## F1.3 — Demostración del filtro (con el `evaluate()` real del motor)

`evaluate([pmh_gap_pct > 50], ctx)`:

| `pmh_gap_pct` que ve el motor | Universo |
|---|---|
| 55,75 (real, con backfill) | **PASA → se vigila → dispararía** |
| 26,86 (degradado por reinicio tras 04:00) | FALLA → se descarta |
| `None` (fresh restart, sin barras aún) | FALLA → se descarta |

El motor y la lógica de condiciones **son correctos**: el fallo es puramente el dato de entrada
(`pre_high`) del camino en vivo. Por eso la reproducción histórica (replay) nunca lo pilla —
ahí el `pmh_gap` se calcula bien desde barras históricas.

## El "test que falla" (spec reproducible)

**Dado:** una alarma con universo `pmh_gap_pct > 50`, un ticker cuyo PM high real da +55,75 %
(BAOS 2026-09-04), y un backend que arranca **después** de la hora del PM high (04:00).
**Entonces (hoy, con el bug):** `pre_high` no refleja el máximo real → `pmh_gap_pct` < 50 →
el ticker se cae del universo → `watched_tickers` no lo contiene → la alarma no dispara.

## Criterio de "ARREGLADO" (aceptación para Fase 2 y Fase 3)

Tras arrancar el backend **a cualquier hora del premarket**, `pre_high` debe reflejar el máximo
real de premarket (0,4372 para BAOS) → `pmh_gap_pct ≈ 55,75` → el ticker **pasa** el universo y
entra en `watched_tickers`. Es decir: **sembrar `pre_high`/`pre_volume` al arrancar desde barras
de minuto REST** (`_refresh_from_snapshot`/`_reset_day`), tal como el motor de alarmas ya hace su
propio `_backfill` de series.

- **Fase 2 (simulador):** debe reproducir el fallo — arrancar "a media premarket" y ver a BAOS
  caerse del universo — y servir de banco para verificar el fix.
- **Fase 3 (fix):** con el backfill, BAOS se queda en el universo; decisión de alcance pendiente
  (todos los ~8.000 tickers vs solo movers).
