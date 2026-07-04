# Análisis de rendimiento del backtester — propuesta por impactos

**Fecha:** 2026-07-02 (rev. 2 — hardware real corregido)
**Método:** medido sobre el código real (rama `performance`), no estimado. Benchmarks en M4 local; extrapolación a prod (Xeon W-2145) con factor ×1.8-2 single-core.
**Hardware prod REAL (verificado por Jesús):** Hetzner dedicado FSN1-DC6 — Intel Xeon W-2145 (8C/16T, 3.7-4.5 GHz, 2017), **128 GB RAM ECC**, discos **1×10TB + 2×6TB Enterprise HDD (sin NVMe)**, ~€135/mes. ⚠️ Los comentarios del código que hablan de "CCX23/CCX33, 15/30GB" están **desfasados** — la caja real tiene 128 GB.
**Contexto:** la competencia corre backtests equivalentes 5-10x más rápido. Objetivo: cerrar ese gap y superarlo.

---

## 1. Resumen ejecutivo

La optimización de señales del 2026-07-01 (commit `5bdaf8c`, 18.6x en señales) atacó una fase que hoy es solo **~3% del tiempo total**. El cuello de botella real está en otro sitio:

| Fase (por par, steady-state, caché disco caliente) | Coste medido (M4) | Coste est. prod (W-2145) | % del total |
|---|---|---|---|
| **Ensamblado de datos** (leer parquets por-ticker → concat → to_datetime+merge → strftime → sort → groupby → sort+dedup por par) | **~1.900 µs/par** | ~3.400 µs/par | **~75-80%** |
| Mitad B serial (simulate + enrich + stats por día) | ~300-600 µs/par | ~550-1.100 µs/par | ~15-20% |
| Señales (fast path N2a, ya optimizado) | ~66 µs/par | ~120 µs/par | ~3% |
| Serialización resultado (sanitize + msgpack, 20k trades) | ~0,7 s total | ~1,3 s total | ~1% |

**Para un backtest típico (gap ≥20%, 2022-2026 ≈ 35.000 pares): ~2,5-3 min en prod solo de CPU, sin contar misses de GCS.** Y en primera ejecución (meses no cacheados) el fetch desde GCS añade minutos: el bucket está en **US** y el servidor en Hetzner **Europa**, y el patrón "1 parquet de 37M filas/mes + `ticker IN (...)`" tiene una amplificación de lectura enorme (medido: 20 tickers × 1 mes = 86k filas útiles pero decenas/cientos de MB transferidos).

**La conclusión central:** el motor de cálculo ya es razonablemente rápido; lo que nos hace 5-10x más lentos que la competencia es la **maquinaria pandas de ensamblado** y la **distancia a los datos**. Ambas cosas tienen arreglo directo, sin cambiar de lenguaje.

**Proyección del plan completo (P1→P5):** 35k pares pasan de ~2,5-3 min a **~8-15 s** en el hardware actual, y ~4-8 s con upgrade de hardware. La primera ejecución pasa a costar lo mismo que las siguientes.

---

## 2. Cómo se midió

- `simulate()` (motor Python puro): microbenchmark con datos sintéticos, 390/960 barras, 1-5 trades → **51-159 µs/par**.
- Ensamblado: réplica sintética del path real (`_fetch_and_cache_month` paso 1+6 + `iter_intraday_groups_streamed` + `_preprocess_pair`) con 300 ticker-mes (5,3M filas), qualifying de 600 pares → **1.145 ms = 1.909 µs/par**. Desglose:
  - `pd.read_parquet` × 300 archivos: 340 ms (1,1 ms/archivo)
  - `pd.to_datetime` + merge a valid_pairs: 413 ms
  - `dt.strftime("%Y-%m-%d")`: 110 ms
  - `sort_values` + `groupby` + materializar: 87 ms
  - `_preprocess_pair` (sort+drop_duplicates+reset_index **por par**): 202 µs/par
- La misma tarea en **una query DuckDB** (scan dir + semijoin + sort): **208 ms = 5,5x más rápido** — y aún devuelve DataFrame; con slices numpy sobre un slab ordenado el coste por par baja a <100 µs.
- GCS real: 1 ticker × 1 mes = 2,7 s; 20 tickers × 1 mes = 74 s (red doméstica; en datacenter menos, pero el patrón de amplificación es el mismo). Bucket `strategybuilderbbdd` = **US multi-región**; prod = Hetzner EU.
- Layout real del bucket: `intraday_1m_optimized` = 1 archivo/mes, ~37M filas, 304 row-groups de 122.880 filas ordenados por ticker. **2017 sigue en raw: 250 archivos/mes** sin reclusterizar.
- Serialización de un resultado de 20k trades: `sanitize_floats` 397 ms + msgpack 275 ms (35 MB).
- Universo típico: hot cache 320.793 filas; gap ≥20% ⇒ 6-11k pares/año (~35k pares 2022-2026).

Nota importante sobre el paralelismo actual: `BACKTEST_PARALLEL_WORKERS` (default **1** = apagado) solo paraleliza la fase de señales (~3% del coste). El ensamblado corre en el **padre** y es el limitador del pipeline: subir workers hoy casi no mueve la aguja. Por eso el orden de impactos de abajo es el que es.

---

## 3. Cuellos de botella identificados (dónde exactamente)

1. **Ensamblado pandas por mes y por par** — `backend/app/db/gcs_cache.py` (`_fetch_and_cache_month`: read_parquet secuencial por ticker, `pd.to_datetime`+merge, `strftime`, sort; `iter_intraday_groups_streamed`: groupby+yield con copias) y `backend/app/services/backtest_signals.py:400` (`_preprocess_pair`: sort+dedup+reset por par). El mes se re-ensambla en **cada** backtest (el `_MONTH_CACHE` solo retiene frames ≤50MB, y BROAD nunca).
2. **Datos remotos con amplificación de lectura** — `_gcs_fetch_tickers` hace `ticker IN (...)` contra el archivo mensual de 37M filas vía HTTP transatlántico. La maquinaria compensatoria (caché por-ticker en disco, prewarm del universo gap, markers vacíos, cuotas LRU, dedup in-flight) es compleja y aun así deja fríos los BROAD y los rangos nuevos.
3. **Mitad B serial en Python puro** — `backend/app/services/portfolio_sim.py` (bucle barra a barra por par) + `_enrich_trades`/`_extract_day_stats_from_values`. Hoy ~15-20%; cuando se arregle (1) pasará a ser el 60-70% del tiempo y el suelo serial del pipeline paralelo (~25-35 s para 35k pares en prod).
4. **Qualifying BROAD en GCS** — `query_qualifying_gcs` calcula ~40 columnas window (LEAD/LAG) sobre **todas** las filas del rango en cada ejecución no cacheada, leyendo de US.
5. **2017 (y 2018-2020 cuando aterrice el backfill) en formato raw** — 250 archivos/mes sin ordenar por ticker: lecturas lentísimas para esos años.
6. Micro: doble parseo/strftime de fechas a lo largo del path, `sanitize_floats` recursivo, pickling de DataFrames por chunk hacia los workers.

---

## 4. Propuesta por impactos

Ordenada por ganancia end-to-end real. Cada palanca es independiente, con flag de rollout y validación por golden test (`tests/test_backtest_golden.py`, tolerancia 0).

### P1 — Ensamblado columnar: slab mensual + índice de pares + slices numpy
**Ganancia: ~10-20x en la fase dominante del steady-state (el backtest típico pasa de ~2,5-3 min a ~30-50 s por sí sola).** Esfuerzo: 3-5 días. Riesgo: medio-bajo (misma semántica, formato interno nuevo).

- Al escribir el caché local de un mes, guardar **un solo archivo por mes ya limpio y ordenado** por (ticker, date, timestamp) — sin duplicados, fechas como date32, timestamps como int64 — más un **índice liviano** `(ticker, date) → [row_start, row_end)`.
- En el backtest: cargar el slab (Arrow IPC/memmap o una query DuckDB con `threads=8`) y entregar a señales/simulador **vistas numpy por par** (slices contiguos). Desaparecen: read_parquet×N, concat, to_datetime, merge, strftime, sort, groupby, y el sort+dedup+reset **por par** (la limpieza se hace una sola vez al escribir el caché).
- Los workers de señales reciben `(row_start, row_end)` en vez de DataFrames pickleados (IPC ~0).
- Incremento intermedio si se quiere valor en 1 día: sustituir el paso 1+6 de `_fetch_and_cache_month` por una única query DuckDB sobre los parquets del caché (5,5x medido) sin tocar el resto.

### P2 — Réplica local completa del histórico (NVMe) y adiós a GCS en el hot path
**Ganancia: primera ejecución = steady-state (hoy: +minutos o timeout); BROAD y rangos nuevos dejan de doler. 10-100x en los paths fríos.** Esfuerzo: 1-2 días + sincronización nightly. Riesgo: bajo.

- El intradía 2021-2026 completo son ~2,4B filas ≈ **30-60 GB en parquet: cabe de sobra en los 22 TB de HDD de la caja actual**, y —clave con discos HDD— **cabe entero en los 128 GB de RAM como page cache** tras un warm secuencial. Sync `gsutil rsync`/`rclone` nightly del bucket a disco local; DuckDB lee rutas locales (cambio de `gs://` a `/data/...`).
- ⚠️ **Los discos son HDD (no NVMe): el acceso aleatorio a miles de parquets pequeños es patológico (~8-12 ms/seek)** — otro motivo por el que el caché por-ticker actual es lento en frío. El diseño correcto en esta caja es **archivos grandes secuenciales + page cache de 128 GB** (exactamente lo que propone P1), no más archivos pequeños.
- GCS queda como fuente de verdad y backup. Se puede retirar (o dejar como fallback) toda la maquinaria de caché por-ticker, prewarm, markers vacíos, cuotas y dedup in-flight — cientos de líneas de complejidad y varios modos de fallo.
- Quick win independiente si no se quiere réplica aún: **mover el bucket a `europe-west3`** (está en US y el servidor en Alemania) — reduce latencia de cada miss varias veces por el mismo coste.

### P3 — Numba en `simulate()` + adelgazar la Mitad B
**Ganancia: elimina el suelo serial del pipeline (~25-35 s → ~2-4 s para 35k pares en prod). Tras P1, esta fase es el 60-70% de lo que queda.** Esfuerzo: 2-4 días. Riesgo: medio (lógica de exits compleja) — mitigado por golden tol-0 y flag de fallback.

- **No partir de cero: ya existe un port bit-idéntico** en la rama `origin/feat/f2-numba-engine` (commit `435ef11`, Adrián, 29-jun: `portfolio_sim_jit.py`, MATCHED tol 0). Se aparcó porque midió solo **1.7x** — coherente con este análisis: con el ensamblado actual, simulate no es el cuello (~15-20%), y además su wrapper re-codifica los parámetros string→enum EN CADA PAR. Rescatarlo con el encoding hoisted (una vez por backtest, como ya se hace con `_indicator_plan`) y detrás de un dispatcher (sin reescribir `portfolio_sim.py` como hacía esa rama). Tras P1, esta pieza es la que evita que la Mitad B serial se convierta en el nuevo cuello.
- Vectorizar `_enrich_trades`/`_extract_equity_from_values` (hoy construyen dicts por punto/por trade con `.iloc`).
- Warmup del JIT en el startup del servidor para no pagar compilación en el primer backtest.

### P4 — Paralelismo real de todo el pipeline
**Ganancia: 4-6x sobre el CPU restante (tras P1+P3 el pipeline es paralelizable de verdad).** Esfuerzo: 1-2 días (la infraestructura ya existe). Riesgo: bajo con el slab (memoria compartida real).

- Con el slab de P1, activar `BACKTEST_PARALLEL_WORKERS=6` deja de estar limitado por el padre: los workers heredan el slab por fork/COW (o memmap) y reciben índices, no datos.
- La única dependencia serial real es el compounding entre fechas; se resuelve como ya está diseñado (señales en paralelo, simulate+acumulación en orden) — y con P3 la parte serial es trivial.
- Hoy, sin P1, subir workers **no** es la palanca: solo acelera el ~3% (señales).

### P5 — Hardware a la medida del problema
**Revisado con el hardware real: la caja actual (W-2145, 128 GB, HDD) ya da para ejecutar TODO el plan.** Los 128 GB permiten page cache del histórico completo (neutraliza los HDD) y activar cachés en RAM que hoy están gateados por comentarios desfasados ("CCX33 30GB"). Ajustes inmediatos de config: `DUCKDB_MEMORY_LIMIT` (hoy 8GB, puede ser 16-24GB), workers y guardas de memoria.

La mejora opcional de hardware, si tras P1-P4 se quiere otro 1,5-2,5x:
- **NVMe** en la caja (o migrar a una auction box con NVMe, p. ej. AX102 ~€104/mes con Ryzen 7950X3D): elimina la dependencia del warm de page cache tras reinicios y sube el single-core ~2x (el W-2145 es de 2017).
- Sin P1-P3, más hardware NO resuelve: el ensamblado pandas es single-thread en el padre.

### P6 — Qualifying BROAD y años fríos
**Ganancia: los datasets BROAD y los años 2017-2020 dejan de ser un caso aparte.** Esfuerzo: 1-2 días. Riesgo: bajo.

- Materializar las columnas LEAD/LAG/SMA del qualifying **en el propio parquet de `daily_metrics`** (son deterministas) o, con P2, correr la query window sobre la réplica local. Hoy se recalculan ~40 columnas window sobre todo el rango en cada ejecución no cacheada.
- Reclusterizar 2017 raw → optimized (y hacer lo mismo con 2018-2020 cuando termine el backfill), o directamente generar los slabs de P1 para esos años.

### P7 — Micro-optimizaciones de cola (opcional, tras lo anterior)
- Redondear floats a 4 decimales antes de serializar y usar `orjson` para la respuesta API (~2x en serialización).
- `sanitize_floats`: hacerlo dentro de la construcción de trades (ya se redondea allí) en vez de un walk recursivo posterior.
- Monte Carlo: vectorizar el loop de permutaciones (hoy 500-1000 × `rng.permutation` en Python; con `argsort` de una matriz aleatoria es una sola op) — solo relevante si se sube el nº de simulaciones.

---

## 5. Qué NO hacer (y por qué)

- **Reescribir en Rust/C++/otro lenguaje.** El cálculo por par es aritmética simple sobre ≤1.000 barras; numpy+Numba+DuckDB quedan a ≤2-3x de código nativo para esta carga, con 10-20x menos esfuerzo y sin bifurcar el equipo. El gap actual no viene del lenguaje: viene de pandas en el hot path y de datos a 8.000 km.
- **GPU.** El trabajo por par es minúsculo y ramificado; el overhead de kernel/transferencia domina. La paralelización útil aquí es por pares en CPU.
- **Seguir micro-optimizando señales.** Ya están en 66 µs/par; es el 3% del problema. Rendimientos decrecientes.
- **Volver a VectorBT.** Se retiró por memoria y control; el plan P3 da lo mismo (JIT) sin la dependencia.
- **Más caché sobre la maquinaria actual** (RAM cache por-ticker, más cuotas, más prewarm). Es tratar el síntoma: con P1+P2 la mayoría de esa maquinaria se borra en vez de crecer.

---

## 6. Proyección combinada (backtest típico: 35k pares, estrategia 1m)

| Estado | Primera ejecución | Ejecuciones siguientes |
|---|---|---|
| Hoy (W-2145, HDD, bucket US) | ~4-10+ min (misses GCS US↔EU + seeks HDD; BROAD: peor/timeout) | ~2,5-3 min |
| + P1 (ensamblado) | ~2-6 min | **~30-50 s** |
| + P2 (réplica local + page cache 128GB) | **= siguientes** | ~30-50 s |
| + P3 (Numba Mitad B) | = | **~12-20 s** |
| + P4 (paralelismo 6-7 workers de 8C/16T) | = | **~8-15 s** |
| + P5 (NVMe / CPU moderna, opcional) | = | **~4-8 s** |

Con P1-P4 en el hardware actual ya se supera el objetivo de "5-10x más rápido". P5 da el margen para datasets BROAD y para crecer en usuarios concurrentes.

## 7. Secuencia recomendada

1. **P2-quick** (horas): evaluar mover bucket a EU o arrancar la réplica local — desbloquea todo lo demás y quita dolor inmediato de first-run.
2. **P1** (3-5 días): slab mensual + índice + slices numpy. Gate: golden tol-0 + benchmark antes/después con `backend/scripts/rigorous_benchmark.py`.
3. **P3** (2-4 días): Numba en simulate + enrich vectorizado. Gate: golden tol-0, flag `BACKTEST_NUMBA_SIM=0` de fallback.
4. **P4** (1-2 días): activar y ajustar workers con el slab.
5. **P5**: decidir hardware con los números reales de P1-P4 en la mano.
6. **P6-P7**: BROAD/qualifying y colas.

Cada paso se despliega con flag y se mide en prod con los logs `[TIMING]` ya existentes (qualifying / loop / total) — conviene añadir un log de fase de ensamblado para ver el antes/después en producción real.

---

## Anexo: entorno de medición

- Local: Apple M4, 24 GB, Python 3.11, duckdb 1.1.3, pandas 2.2.3, pyarrow 24. Red doméstica para GCS (los tiempos GCS en datacenter serán menores; la amplificación de lectura y el cruce US↔EU son estructurales).
- Prod: Hetzner dedicado FSN1-DC6 — Intel Xeon W-2145 (8C/16T), 128 GB ECC, HDDs Enterprise (10TB + 2×6TB, sin NVMe), Coolify, 1 proceso uvicorn, DuckDB cap 8 GB / 8 threads, `BACKTEST_PARALLEL_WORKERS=1`. (Los comentarios "CCX23/CCX33" del código están desfasados respecto a esta caja.)
- Scripts de benchmark de esta sesión: microbench de `simulate()` y del ensamblado (réplica del path `_fetch_and_cache_month`/stream) — reproducibles; los del commit `5bdaf8c` siguen en `backend/scripts/`.
