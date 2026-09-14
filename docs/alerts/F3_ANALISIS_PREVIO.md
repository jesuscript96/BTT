# Fase 3 · F3.0 — Análisis previo del fix (¿directo y completo?)

> Objetivo de F3.0: antes de tocar código, verificar en el código real qué tenemos, qué se ha
> avanzado, y si el fix propuesto es una **solución directa que corrige todo, explorando todos los
> casos**. Verificado el 2026-09-13 sobre `backend/app/services/live_screener_service.py` y
> `backend/app/services/alarms/engine.py`.

## 1 · Qué tenemos / qué se ha avanzado
- **F1:** BUG A reproducido — el `pre_high` (máx. de premarket) es solo-memoria del WS sin backfill;
  al reiniciar tras el máximo, el ticker se cae del universo (`F1_BUG_A_REPRODUCCION.md`).
- **F2:** simulador (`backend/scripts/sim_ws_alarms.py`) que reproduce el bug de forma determinista
  alimentando barras históricas al live screener vía `_apply_aggregate`.
- Endpoint REST de minutos **ya en uso** por la app: `engine._backfill` →
  `/v2/aggs/ticker/{T}/range/1/minute/{día}/{día}` (mismo patrón que reusará el fix).

## 2 · Hallazgo de F3.0: el bug es de una CLASE más amplia que `pre_high`
El snapshot REST (`_refresh_from_snapshot`) recupera al reiniciar: `prev_close`, `rth_close`,
`last_price`, `day_volume`, `day_high`, `day_low`, `day_open`.

**NO recupera (solo-memoria, se pierden en cada reinicio/`_reset_day`):**
`pre_high`, `pre_volume`, `after_high`, `after_low`, `after_volume`.

Además `day_high/low/volume` los da el snapshot con `day.*`, pero `day.*` es **0/parcial en
premarket** (no incluye horario extendido) → durante premarket son *efectivamente* solo-memoria.

Las alarmas pueden filtrar por **todos** esos campos (`_metrics` expone `pre_pct`, `pre_volume`,
`pre_high`, `after_pct`, `after_volume`, `after_high`, `volume`, `high`, `low`, `rvol`).

→ **BUG A (PM High Gap) es la cara visible.** El mismo defecto rompe alarmas de volumen de
premarket, máximo/volumen de afterhours, etc. Todo acumulador de sesión extendida se pierde.

## 3 · Exploración de casos

| Caso | Solución "solo pre_high / movers / al arrancar" | Solución generalizada |
|---|---|---|
| Arranca tras el máx. de premarket (incidente) | ✅ | ✅ |
| Reinicio a media premarket | ✅ | ✅ |
| Alarma de **afterhours** (`after_*`) tras reinicio | ❌ no siembra `after_*` | ✅ |
| Ticker **picó 04:00 y se desinfló** + scope movers | ❌ proxy bajo → no se siembra | ✅ (todos) |
| **WS cae y reconecta** sin reinicio | ❌ solo al arrancar | ✅ (reconexión) |
| Misprint de premarket infla `pre_high` | ❌ dato crudo (orthogonal) | ❌ (fuera de alcance) |

## 4 · La solución (directa y completa PARA SU CLASE)
Reconstruir el **estado completo de sesión** desde las barras de minuto del día (04:00→ahora),
replicando la MISMA lógica de acumulación de `_apply_aggregate` (clasificación pre/rth/after +
max/min/suma) → siembra `pre_high`, `pre_volume`, `after_*`, `day_high/low/volume` de una vez.

- **Invocación:** al arrancar, en `_reset_day` (nuevo día) y **al reconectar el WS** (no solo al
  arrancar); opcionalmente en el poll mientras el WS esté caído.
- **Alcance:** **todos los tickers del allowlist** (único que cubre el caso pico-y-desinfle). Coste
  ≈ una llamada de minuto por ticker (~8.000). Mitigación **por capas**: primero movers por cambio
  actual (cobertura rápida), luego barrido en segundo plano del allowlist completo.

### Detalles de implementación verificados
1. El motor registra `add_aggregate_listener(on_aggregate)`, que `_apply_aggregate` **dispara por
   cada barra** → el backfill **NO debe reusar `_apply_aggregate` tal cual** (dispararía
   procesamiento/avisos espurios por barra histórica). Usar un método dedicado que acumule **sin**
   disparar listeners.
2. **`max`/merge**, no sobrescribir (no pisar lo que el WS ya acumuló).
3. Reusar el patrón/cliente REST de `engine._backfill`; throttle + manejo de 429 al barrer todos.

## 5 · Lo que este fix NO corrige (fronteras)
- **Misprints** (dato crudo en vivo → falso positivo). Data-quality, ligado a Augus. Separado.
- **BUG B** (instantáneas ignoran franja horaria) → Fase 4.
- **Cadena posterior:** evaluación de la condición sobre la serie, cooldown, disparo y **entrega
  Telegram**. El fix solo arregla **vigilar/universo**. Se valida en F5/F6.
- **Coste/robustez del REST** al barrer todos (throttle/429/latencia).

## 6 · Veredicto
- **¿Directa?** Sí — idiomática, reusa código existente, sin dependencias nuevas.
- **¿Corrige todo, todos los casos?** Sí, **para la clase de bug** (estado de sesión perdido por
  reinicio/reconexión en horario extendido) **si se generaliza** (todos los acumuladores + todos los
  tickers + arranque/reset/reconexión + sin listeners + merge). **No** es bala de plata del feature:
  BUG B y la cadena de disparo/entrega son independientes.

## 7 · Decisiones CERRADAS (2026-09-13, Adrian)
1. **Alcance = POR CAPAS.** Al arrancar/reset/reconexión:
   - **Capa 1 (inmediata):** backfill de los "movers" del momento — los tickers cuyo cambio actual
     (del snapshot: `last/prev`) supere un umbral — para cobertura rápida de lo que se mueve ahora.
   - **Capa 2 (segundo plano):** barrido del **allowlist completo** (~8.000) con throttle + manejo
     de 429, que cierra el caso "picó a las 04:00 y se desinfló". Corre sin bloquear el arranque.
2. **GENERALIZAR = SÍ.** El backfill reconstruye TODOS los acumuladores de sesión
   (`pre_high`, `pre_volume`, `after_high`, `after_low`, `after_volume`, `day_high/low/volume`),
   no solo `pre_high` — es el mismo método y cierra la clase entera del bug.
3. **Misprints = FUERA de este fix (limitación conocida aparte).** Verificado: la limpieza de
   misprints vive en **dos batch de INGESTA sobre el LAGO** — `scripts/catchup_gcs.py`
   (`MISSPRINT_CLIP_ENABLED`) y el **lavado diario Augus** `scripts/daily_wash.py` (limpia el
   `/lake` parquet de **días pasados/completos, de madrugada**; ej. lavó 2026-09-11 el 2026-09-12
   06:13; el cron hace `docker restart` para recargar prewarm). Eso alimenta al **backtester/charts**.
   **El camino EN VIVO NO toca el lago** (0 referencias a lake/parquet/prewarm en
   `live_screener_service.py`): el `pre_high` se construye de **Massive CRUDO** (WS + REST de
   minutos). Y por timing, el premarket de HOY nunca está lavado en tiempo real (el lavado corre al
   día siguiente sobre el día cerrado). → Las alarmas en vivo **no** tienen protección de misprints,
   por arquitectura. Este fix es **neutral** (el `pre_high` del WS ya era crudo; el backfill usa la
   misma fuente REST cruda). Sería otro síntoma (falso positivo, no "no entra"). Mitigación futura si
   molesta: un *sanity clip ligero* en el backfill. Ligado al trabajo de Augus.
