# Informe — No-determinismo del backtester (70R ↔ 137R) y caché intradía desfasado

**Fecha:** 2026-08-21
**Rama:** `alvaro-rama-desarrollo` — commit del fix principal: `1ec8ce9`
**Autor de la investigación:** Álvaro + Claude (Opus 4.8); diagnóstico forense inicial de GLM.
**Estado:** fix principal committeado y verificado end-to-end contra el backend local. Dos
refuerzos adicionales activos en runtime pero **sin commitear** (ver §5).

---

## 1. Síntoma

El **mismo** backtest (misma estrategia, mismas fechas, mismo 1R) devolvía resultados
distintos según el orden/momento de ejecución:

- Return saltaba entre **~70% y ~137%** (y `11R → 46R` al reejecutar con el mismo $1).
- Al comparar **local vs producción** de la "misma" estrategia, salían métricas muy dispares
  (win rate 40% ↔ 53%, trades y días descuadrados hasta 6×).

El motor de simulación (SL, EOD, sizing, reentradas) **NO estaba roto**: dado un mismo
conjunto de candidatos, produce resultados idénticos (verificado: 2.900 pares comunes con
trades idénticos en comparaciones cruzadas). El problema era **qué datos llegaban al motor**.

---

## 2. Causa raíz #1 — Fallback silencioso del qualifying entre fuentes NO equivalentes

`fetch_qualifying_data` (`backend/app/services/data_service.py`) tenía una cadena de fallback:

- **Vía autoritativa:** bygap / `daily_metrics` vía DuckDB → universo completo (p.ej. **4.902**
  candidatos PMH-gap ≥ 50).
- **Fallback:** hot-cache en RAM = `SELECT * FROM daily_metrics WHERE gap_pct >= 10.0`
  (`cache_service.py:211`) → prefiltrado por gap de **APERTURA** ≥ 10% → universo **distinto**
  (p.ej. **4.013** candidatos).

**Disparador:** un error transitorio `Table with name daily_metrics does not exist`. Ocurría
porque `_establish_connection` (`database.py`) devuelve una conexión DuckDB **en memoria y sin
las vistas del lago** ante cualquier fallo al crearlas. Como cada hilo worker tiene su propia
conexión (`threading.local`), bastaba con que un run cayera en un hilo con la conexión
degradada para que el qualifying pegara contra una conexión sin `daily_metrics`, fallara, y
**cayera EN SILENCIO** al hot-cache prefiltrado.

Resultado: el **mismo** request daba 70R o 137R según qué rama sirviera el qualifying.

### ⚠️ El bug es latente y COMPARTIDO — la migración a parquet lo activa

El fallback silencioso (`data_service.py`, el `except` que cae a `if use_hot_cache:`) está
**presente igual en `jaumen-rama-desarrollo`** — es código compartido, latente. La diferencia
entre ramas es el **modelo de datos de `daily_metrics`**:

- **Rama de Jaume (pre-migración):** `daily_metrics` es una **TABLA persistente** en
  `local_data.duckdb` (`CREATE VIEW massive.daily_metrics AS SELECT * FROM main.daily_metrics`).
  Siempre está → nunca lanza "table does not exist" → el fallback **nunca se dispara** → no hay
  síntoma. Por eso "Jaume la tenía bien".
- **Rama de Álvaro (migración GCS→local-parquet):** `daily_metrics` son **vistas perezosas sobre
  parquet** (`create_lake_views` → `read_parquet(lake_glob)`). Esas vistas **sí** pueden fallar
  transitoriamente al crearse → `daily_metrics` desaparece un instante → el fallback latente se
  **activa** → no-determinismo.

**Conclusión operativa:** esto NO es limpieza específica de la rama de Álvaro. La migración a
parquet es la dirección del producto (DATA.md, `PRD_migracion_datos_local.md`). **Cuando la
migración llegue a staging/main, el bug latente se activará para todos.** El fail-fast (§2, fix)
es por tanto un **prerrequisito de seguridad de la migración** y debe viajar CON ella al
mergear. Es inocuo para el mundo pre-migración (con la tabla persistente, el `except` nunca se
dispara → cero cambio de comportamiento).

> **El número correcto es el de la vía autoritativa (~137% / universo completo).**
> El 70R era el resultado **degradado** por el universo recortado del fallback. Los números
> del socio (~131R) caían del lado autoritativo (correcto) — su data no era mejor, era la buena.

### Fix (COMMITTEADO, `1ec8ce9`)

- **`data_service.py` — FAIL-FAST:** cualquier fallo de la vía autoritativa **se propaga**
  (error 500/503 explícito). Nunca se sirve el hot-cache como si fuera el universo completo. La
  rama hot-cache queda **inalcanzable** para estrategias con reglas de universo propias. Sin
  reintento de query: o sale el universo correcto, o sale error. Además descarta la conexión
  degradada (`reset_connection`) para que la siguiente petición nazca sana.
- **`backtest_orchestrator.py` — guardián de completitud:** reconcilia ticker-días candidatos
  vs ejecutados y lo reporta en `data_completeness` (en el payload del resultado). Con
  `BACKTEST_STRICT_COMPLETENESS=true` **rechaza runs parciales (503)** en vez de devolver un
  número al que le faltan trades.

---

## 3. Causa raíz #2 — Caché intradía por-ticker-mes desfasado (mes en crecimiento)

El guardián de completitud (una vez el fix #1 estabilizó el universo en 4.902) reveló ~20
ticker-días marcados `missing`, todos en **2026-08-10→14** (AKAN, STKH, OFAL, SURG, DOGZ…).

**No faltaban del lago** — el lago los tenía (AKAN 08-14 = 925 velas de 1m). Era **caché
desfasado**: el caché intradía es **por-ticker-mes** (`.cache/intraday/raw/YYYY/MM/TICKER.parquet`,
`gcs_cache.py`), se **congela en el primer fetch** y **no se refresca** cuando el lago añade días
nuevos al mismo mes en curso. Esos tickers se cachearon a principios de agosto (lago hasta
~08-07); cuando el lago creció a 08-14, el stream seguía leyendo el parquet viejo → los
candidatos recientes desaparecían del backtest en silencio.

### Fix (activo en runtime, **SIN commitear** — ver §5)

- **Inmediato:** borrado de `.cache/intraday/raw/2026/08` (derivado, se reconstruye del lago).
- **Durable:** en `_fetch_and_cache_month` (`gcs_cache.py`) ahora se **re-lee del lago si el
  caché no vacío no alcanza la fecha máxima pedida** para ese ticker-mes. Los marcadores vacíos
  (0 filas) se siguen respetando para no re-descargar tickers sin datos.

---

## 4. Verificación (end-to-end, contra el backend local)

Dos backtests reales lanzados en modo síncrono (`X-Backtest-Sync: true`) al backend en el
puerto 8010, misma config:

```
run1: expected=9187  executed=9187  missing=0  completeness=100%  trades=3992  return=1.907%
run2: expected=9187  executed=9187  missing=0  completeness=100%  trades=3992  return=1.907%
→ IDÉNTICOS  (HTTP 200, sin 503)
```

- **Determinismo:** mismo input → salida byte a byte igual. El `expected` ya no salta 4.902↔4.013.
- **Completitud:** 100%, 0 missing. El bug de caché desfasado resuelto.
- **Sin descarte silencioso:** `expected == executed`.

Comparación local vs prod de "Definitiva 2.3" tras el fix: coinciden **dentro del ~2%** en win
rate (69,5 vs 71,8%), PF (1,700 vs 1,694), return (1,49 vs 1,46%), Sharpe (8,647 vs 8,592). Antes
divergían hasta 6×.

---

## 5. Estado de commits y riesgo de arquitectura

| Fichero | Cambio | Estado |
|---|---|---|
| `data_service.py` | fail-fast qualifying | ✅ Committeado `1ec8ce9` |
| `backtest_orchestrator.py` | guardián de completitud | ✅ Committeado `1ec8ce9` |
| `backend/.env` | `BACKTEST_STRICT_COMPLETENESS=true` | Local (no versionado) |
| `database.py` | reintento+verificación de `create_lake_views` | 🟡 Activo, **sin commitear** |
| `gcs_cache.py` | refresh de caché desfasado | 🟡 Activo, **sin commitear** |

**Por qué `database.py` y `gcs_cache.py` no se committearon:** ambos ficheros ya arrastraban
cambios **sin commitear del refactor de migración GCS→local** del equipo. Mis refuerzos van
encima y dependen de ese refactor (no se separan limpio). No committeo trabajo del equipo bajo
mi autoría en una rama experimental.

> **Recomendación de arquitectura:** committear el refactor de migración GCS→local para tener
> base limpia; entonces los dos refuerzos se posan encima sin entrelazar y quedan versionados.
> Ese trabajo sin commitear flotando es lo que hizo tan difícil razonar "qué código corre de
> verdad" — origen indirecto de todo este lío.

---

## 6. Pendiente

1. **Endurecer `_establish_connection`** (raíz profunda): no devolver una conexión sin vistas del
   lago en silencio. Debe fallar explícito o verificar+reintentar. `get_db_connection` es hot
   path (blast radius alto) → hacerlo con cuidado y quien posea la migración.
2. **Residual local vs prod (~6% de trades):** diferencias finas de cobertura de datos entre el
   lago local y la fuente de prod (velas sucias de premarket ~1%, algún ticker-día distinto). No
   es bug de motor. Para cerrarlo al milímetro: desplegar el guardián de completitud también en
   prod y diff trade-a-trade. Rendimiento decreciente.
3. **Métrica `DAYS` cosmética:** local (días de calendario) y prod (ticker-días) la cuentan
   distinto entre versiones. No comparar entornos por ese número.
4. **Config drift ya resuelto:** "Definitiva 2.3" local ahora incluye `Bar Close ≥ 0.3` (4
   condiciones), igual que prod.

---

## 7. Cómo reproducir / verificar

Backtest síncrono directo al backend (sin UI):

```bash
curl -s -X POST http://localhost:8010/api/backtest \
  -H "Content-Type: application/json" -H "X-Backtest-Sync: true" \
  -d '{"dataset_id":"<id>","strategy_id":"<id>","start_date":"YYYY-MM-DD","end_date":"YYYY-MM-DD","risk_r":1,"risk_type":"FIXED","fees":0,"slippage":0,"look_ahead_prevention":true,"market_sessions":["custom"],"custom_start_time":"04:00","custom_end_time":"08:30"}'
```

Comprobar en la respuesta el bloque `data_completeness` (`expected == executed`, `missing == 0`)
y que dos ejecuciones idénticas dan el mismo número. Si `STRICT=true` y hay incompletitud → 503
explícito (no un número degradado). Si recurre un hueco de caché en el mes en curso: borrar
`.cache/intraday/raw/<año>/<mes>` y reejecutar.
