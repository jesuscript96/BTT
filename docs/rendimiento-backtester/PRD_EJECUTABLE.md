# PRD EJECUTABLE — Motor V2: rendimiento del backtester (slab + réplica local + JIT + paralelismo)

> **Qué es esto.** El paquete de requerimientos ejecutable para que una IA (Claude Code en modo
> *goal*) implemente el plan de rendimiento completo del backtester **en una sola pasada**, con
> resultados **bit-idénticos** a los actuales y una mejora medida de **≥8x end-to-end**.
> Estado: **PLAN — listo para ejecutar**.
>
> **Diagnóstico de base (leer primero):** [`docs/PERFORMANCE_ANALYSIS_CTO.md`](../PERFORMANCE_ANALYSIS_CTO.md)
> — todas las cifras de este PRD salen de ahí (medidas, no estimadas).
>
> Formato: suite condensado en un solo fichero (guía: `docs/manual-prd/GUIA_PRD_EJECUTABLE.md`,
> tipo de feature: **transversal / no funcional** → pesa en restricciones globales, DoD con
> medición y no romper contratos).

---

## 00 — Índice y fuentes auditadas

### Documentos de este PRD (capítulos)

| # | Capítulo | Propósito |
|---|---|---|
| 01 | Viabilidad y restricciones | hardware real, riesgos, veredicto |
| 02 | PRD (qué / para quién / alcance) | MVP, Fase 2, fuera de alcance, glosario, éxito |
| 03 | **Contratos de datos** | los que NO cambian (anclados) + los NUEVOS (slab, índice, SimParams, flags, logs) |
| 04 | UI | (sin cambios — declaración explícita) |
| 05 | Arquitectura | ficheros nuevos/tocados, lista no-tocar, flujo antes/después |
| 06 | **PROMPT MAESTRO** | el guion atómico para el loop (EPICs A-F, TDD, comandos) |
| 07 | Decisiones abiertas | A: Jesús · B: defaults reversibles · C: consenso Adrián |
| Ax | Apéndices | minuta de decisiones, mediciones de referencia |

Orden de lectura para el ejecutor: **00 → 01 → 03 → 05 → 06** (02 y 07 como contexto).

### Fuentes auditadas (verdad anclada en código — verificado 2026-07-02)

| Pieza real | Fichero | Qué aporta |
|---|---|---|
| Flujo del backtest (orquestación, fases, timing logs) | `backend/app/services/backtest_orchestrator.py` (`run_backtest_orchestrator`, `BacktestRequest`) | contrato de entrada y fases |
| Motor streaming + loop secuencial + métricas | `backend/app/services/backtest_service.py` (`run_backtest`:65, `_aggregate_metrics`:1096, `_enrich_trades`:845, import de `simulate`:21) | contrato de resultado; **punto único de import del simulador** |
| Generación de señales por par + pipeline paralelo | `backend/app/services/backtest_signals.py` (`_compute_signals_for_pair`:73, `_preprocess_pair`:336, `run_pipelined_signals`:558, `simulate_and_accumulate`:661, `get_parallel_workers`:42) | contrato interno del dict de señales; worker forkserver |
| Simulador Python puro (LA especificación del kernel JIT) | `backend/app/services/portfolio_sim.py` (`simulate`:14-756) | semántica exacta bar-a-bar, redondeos, literales de exit_reason |
| Capa de datos GCS + caché por-ticker + stream | `backend/app/db/gcs_cache.py` (`_fetch_and_cache_month`:818, `iter_intraday_groups_streamed`:1041, `_gcs_fetch_tickers`:711, `prewarm_gap_universe`:1166) | el path a sustituir por el slab |
| Conexión DuckDB (threads, memoria, httpfs) | `backend/app/db/connection.py` (`_create_connection`:40) | settings actuales (8GB / 8 threads) |
| Qualifying (hot RAM / GCS window) | `backend/app/services/data_service.py` (`fetch_qualifying_data`:602, `get_intraday_stream`:1061), `backend/app/services/cache_service.py` (`load_hot_daily_cache`:66) | de dónde sale `qualifying_df` |
| Jobs async + persistencia de resultado | `backend/app/routers/backtest.py` (`run_backtest_endpoint`:115), `backend/app/services/backtest_jobs.py` | API pública que NO cambia |
| Motor Numba precedente (prueba de viabilidad JIT) | `backend/app/backtester/engine.py` (`_core_backtest_jit`:78, `@njit(cache=True)`) | patrón JIT ya validado en el repo |
| **Port JIT previo de `simulate()` — REUTILIZAR** | rama `origin/feat/f2-numba-engine`, commit `435ef11` (Adrián, 2026-06-29): `portfolio_sim_jit.py` (687 líneas, enums+wrapper, **MATCHED tol 0**, fastmath OFF) | punto de partida del EPIC D; su medición fue solo **1.7x "on loop"** — el commit lo aparcó por "not bottleneck for gap datasets" (coherente con este análisis: simulate es ~15-20% del total HOY). Ojo: esa rama REESCRIBIÓ `portfolio_sim.py` (−671 líneas) — este PRD NO hace eso (dispatcher + módulo nuevo) |
| Revert en main | `8c9fa96` "Revert Merge PR #4 from jesuscript96/performance" | la optimización de señales N1+N2a fue mergeada a main y **revertida**; la rama `performance` la conserva. Aclarar el porqué antes de re-mergear (07.A6) |
| Gate de regresión existente | `backend/tests/test_backtest_golden.py` (tolerancia 0; **se ejecuta en el servidor**, ver su docstring) | el gate de "resultados idénticos" |
| Benchmarks previos | `backend/scripts/rigorous_benchmark.py`, `profile_2a_full.py`, `benchmark_post_optim.py` (commit `5bdaf8c`) | patrón de benchmark del repo |
| Layout real del bucket | GCS `strategybuilderbbdd` (verificado en vivo): `cold_storage/intraday_1m_optimized/year=Y/month=M/data.parquet` = 1 fichero/mes ~37M filas, 304 row-groups ordenados por ticker; `intraday_1m/year=2017/month=M/` = ~250 ficheros raw/mes; bucket en **US** | fuente del builder de slabs |

**Cifras medidas de referencia** (M4 local; prod ≈ ×1.8-2): ensamblado actual **1.909 µs/par**
(desglose en Apéndice B), señales fast-path **66 µs/par**, `simulate()` **51-159 µs/par**,
serialización 20k trades **~0,7 s**, GCS 20 tickers×1 mes **74 s** (red doméstica).

---

## 01 — Viabilidad y restricciones

### 1.1 Hardware real de producción (confirmado por Jesús, 2026-07-02)

| Recurso | Valor real | Implicación de diseño |
|---|---|---|
| CPU | Intel Xeon W-2145 — **8 cores / 16 threads**, 3.7-4.5 GHz (Skylake-W, 2017) | paralelismo útil hasta ~6-7 workers de proceso + threads DuckDB; single-core ≈ 0,5-0,55× un M4 |
| RAM | **128 GB ECC** | el histórico intradía completo (~30-60 GB parquet) **cabe en page cache**; los gates "off until CCX33" del código están desfasados |
| Discos | 1×10 TB + 2×6 TB **Enterprise HDD (SIN NVMe)** | ⚠️ acceso aleatorio ~8-12 ms/seek → **prohibido diseñar con muchos ficheros pequeños**; diseño correcto: ficheros grandes secuenciales + warm de page cache |
| Red | Hetzner FSN1-DC6 (Alemania) ↔ bucket GCS **US** | cada miss GCS cruza el Atlántico; la réplica local elimina GCS del hot path |
| Deploy | Coolify, contenedor (python en `/opt/venv`), 1 proceso uvicorn | los jobs de sync van como hilo daemon in-app (patrón `_startup_recovery_precache` de `main.py:15`), no cron de host |

> **PASO 0 del prompt maestro re-verifica esto** con comandos (`nproc`, `free -g`,
> `lsblk -d -o NAME,ROTA,SIZE`, cgroup limits) porque los comentarios del código (CCX23/CCX33,
> 15/30 GB) demuestran que el conocimiento del hardware envejece.

### 1.2 Restricciones técnicas

- **Resultados bit-idénticos.** Ningún cambio puede alterar `aggregate_metrics`, `trades`,
  `day_results`, `equity` — ni en una décima. Gates: equivalencia sintética local (nueva, offline)
  + Golden B en servidor (existente, tol 0).
- **Lista NO TOCAR** (`.agent/CODING_RULES.md`): `backtester/engine.py`,
  `services/indicators.py`, `services/portfolio_sim.py`, schema de `daily_metrics`/`intraday_1m`
  y estructura Parquet **en GCS**. Todo lo nuevo va en **módulos nuevos + un dispatcher**;
  el slab es un formato de **caché local**, no toca GCS. Detalle en §05.3.
- **Memoria:** aunque hay 128 GB, el proceso corre con `BACKTEST_MIN_AVAIL_GB` y
  `DUCKDB_MEMORY_LIMIT`; los slabs se acceden por **memory-map** (page cache, no heap) para que
  el RSS del proceso no explote.
- **Numba:** `numba>=0.59.1` ya es dependencia (requirements.txt). Kernel `@njit(cache=True)`,
  warmup en startup, sin `numba.typed.List` en el hot path (arrays preasignados).
- **Fork-safety:** los workers son **forkserver** (fix del commit `c4fc113`); un worker NO puede
  heredar memmaps del padre → cada worker abre sus memmaps en el initializer (§03.7).

### 1.3 Riesgos y mitigaciones

| Riesgo | Prob. | Mitigación |
|---|---|---|
| El kernel JIT difiere en el último bit (orden de operaciones float) | media | el kernel replica `portfolio_sim.py` **rama a rama en el mismo orden**; redondeos en el adapter Python con `round()`; gate: trades exactos en ≥200 configs × 50 pares; si tras eso queda un residuo, SOLO se admite en `equity` con `atol=1e-9` y se documenta en 07.B (los trades siempre exactos) |
| Dedup/orden del slab difiere del path pandas actual | media | test de equivalencia de **stream**: mismos pares, mismos arrays, mismo orden, bit a bit (EPIC B, T-B6) |
| BROAD sigue lento (universo enorme) | baja | el slab mensual es **de mes completo** (todos los tickers): BROAD deja de ser especial; el builder es el mismo |
| Primera lectura de slab fría en HDD | media | warm secuencial de page cache al boot (hilo daemon, `BTT_SLAB_PAGECACHE_WARM`) — 50 GB ≈ 4-6 min en background |
| Meses 2017 (raw, 250 ficheros) | baja | el builder consume raw igual que opt (una query DuckDB por mes); queda igual de rápido servido como slab |
| Regresión de RAM (mmap + workers) | baja | mmap no cuenta como heap; medir RSS en bench E2E; backpressure del pipeline ya existe |
| Golden B requiere servidor | — | el loop entrega equivalencias sintéticas verdes + deja Golden B como tarea marcada para Jesús/Adrián (no bloquea el desarrollo) |

### 1.4 Veredicto

**Viable con condiciones**: (1) todo detrás de flags con default OFF hasta pasar gates;
(2) Golden B en servidor antes de activar en prod; (3) el swap del import de `simulate` (1 línea
en `backtest_service.py:21`) se consensúa con Adrián (07.C).

---

## 02 — PRD: qué, para quién, alcance

### 2.1 Visión en una frase

Que cualquier backtest —típico o BROAD, primera vez o repetido— corra en **segundos, no
minutos**, con exactamente los mismos resultados, para igualar y superar a la competencia
(hoy 5-10x más rápida).

### 2.2 Usuarios

| Perfil | Necesidad | Cómo la sirve este plan |
|---|---|---|
| Trader (cliente) | iterar estrategias rápido; hoy espera minutos por run | típico 35k pares: ~2,5-3 min → **~8-15 s** |
| Trader (primera vez / rango nuevo) | hoy la primera ejecución añade minutos de GCS o revienta | réplica local: primera = siguientes |
| Optimizador (grid) | corre decenas de runs | hereda el motor rápido gratis (misma ruta `run_backtest`) |
| Nosotros (negocio) | argumento competitivo vs Flash Research | benchmark publicable |

### 2.3 Jobs-to-be-done

1. Ejecutar un backtest sobre un dataset gap (~35k pares) y ver resultado en <15 s.
2. Ejecutar sobre un dataset recién creado (meses nunca tocados) sin penalización de frío.
3. Ejecutar un BROAD sin OOM ni timeout.
4. (Interno) medir cada fase con logs `[TIMING]` para detectar regresiones.

### 2.4 Alcance del MVP (lo que SÍ se construye ahora — los 6 EPICs del §06)

- **A. Instrumentación + baseline**: logs de fase homogéneos y bench E2E reproducible.
- **B. Slab store**: caché local mensual columnar (Arrow IPC + índice de pares) y stream que
  sirve pares como slices numpy zero-copy. Flag `BTT_SLAB_STREAM_ENABLED`.
- **C. Réplica local**: builder de slabs para TODO el histórico desde GCS + sync nightly in-app
  + warm de page cache. Flags `BTT_REPLICA_*`.
- **D. Motor JIT**: kernel Numba equivalente a `simulate()` + encoder de parámetros + dispatcher.
  Flag `BACKTEST_NUMBA_SIM`.
- **E. Paralelismo + tuning**: workers slab-aware; ajustar envs a la caja real (128 GB);
  bench final vs baseline.
- **F. Limpieza + docs**: comentarios de hardware desfasados, runbook de operación, informe.

### 2.5 Fase 2 (NO se construye ahora; decisión que impone al MVP)

| Ítem Fase 2 | Decisión que impone al MVP |
|---|---|
| Qualifying BROAD precomputado (LEAD/LAG materializados en un parquet **nuevo** `daily_metrics_enriched`) | el slab/manifest lleva `engine_version` para poder versionar artefactos derivados |
| RAM-cache estructurado de slabs (dict de arrays en heap) | la API `slab_store.get_month()` devuelve un objeto (`MonthSlab`) — el backing (mmap hoy, RAM mañana) es interno |
| Migrar bucket a `europe-west3` / NVMe / CPU moderna | nada — transparente al código |
| API v2 columnar para resultados (arrays en vez de lista de dicts) + orjson | no renombrar claves actuales; el resultado sigue siendo el contrato de hoy |
| Reclusterizar 2017-2020 raw→optimized en GCS (cuando acabe el backfill) | el builder acepta `kind=raw` desde el día 1 |

### 2.6 Fuera de alcance (NO se hará en este PRD)

- Cambiar **cualquier** semántica de trading, métrica, clave de resultado o API pública.
- Tocar frontend (el lazy-render y el split de equity por día ya existen).
- Reescritura en Rust/C++/otro lenguaje; GPU; volver a VectorBT (justificado en el análisis §5).
- Tocar `portfolio_sim.py`, `indicators.py`, `backtester/engine.py` o el Parquet de GCS.
- El optimizador (`optimization_service.py`): hereda mejoras vía `run_backtest`, no se refactoriza.
- Monetización/gating de la velocidad (decisión de Jesús, diferida).
- MotherDuck (`DB_PROVIDER=motherduck`): path legacy, no se optimiza.

### 2.7 Glosario de dominio (nomenclatura oficial de este PRD)

| Término | Definición | Fuente |
|---|---|---|
| **par** | unidad de trabajo `(date 'YYYY-MM-DD', ticker)` con sus velas 1m del día | `groupby(["date","ticker"])` en `gcs_cache.py:1109` |
| **qualifying / daily_stats** | filas del screener que definen el universo; la fila del par como dict | `data_service.fetch_qualifying_data`, `_build_qualifying_lookup` |
| **Mitad A / Mitad B** | señales por par (pura, paralelizable) / simulate+acumulación (serial por compounding) | docstring `backtest_signals.py:1-22` |
| **slab** | fichero mensual local, columnar, ordenado y deduplicado, con TODOS los tickers del mes | nuevo (§03.5) |
| **índice de pares** | tabla `(ticker, date) → [row_start, row_end)` de un slab | nuevo (§03.5) |
| **manifest** | JSON de metadatos/versión de un slab | nuevo (§03.5) |
| **kind** | `opt` (intraday_1m_optimized) o `raw` (intraday_1m) | `gcs_cache.py:835` |
| **steady-state / frío** | meses ya en caché local / meses que hay que traer de GCS | análisis §1 |
| **golden (tol-0)** | backtest de referencia cuyo resultado no puede moverse ni un bit | `tests/test_backtest_golden.py` |
| **fast path / legacy path** | señales vía `_indicator_plan` numpy / vía DataFrame | `backtest_signals.py:127,157` |

### 2.8 Métricas de éxito (medibles, van al informe final del loop)

1. Bench sintético de ensamblado: **≥6x** vs baseline (1.909 → ≤320 µs/par en la máquina de dev).
2. Microbench `simulate`: **≥10x** warm (p. ej. 100 µs → ≤10 µs/par, 960 barras).
3. E2E dataset real en prod (steady): **≥8x** vs `BASELINE.md`.
4. Primera ejecución de un dataset nuevo ≤ **1.3x** su steady-state (hoy: 2-4x+).
5. Golden B en servidor: **MATCHED** en todos los casos con todos los flags ON.
6. RSS pico del proceso durante un backtest típico: ≤ hoy +10%.

### 2.9 Principios de diseño para el agente

1. **`portfolio_sim.py` es la especificación.** El kernel lo replica rama a rama; ante duda,
   gana el Python actual, aunque parezca un bug (p. ej. el patch 08:00-08:45, el fee FLAT ×2,
   la asignación del locates fee al primer short). No "arreglar" nada de pasada.
2. **Todo detrás de flag, default OFF.** El path legacy queda intacto y seleccionable.
3. **Medir antes y después de cada EPIC** con los mismos scripts; los números van al informe.
4. **Ficheros grandes secuenciales** (HDD): nunca crear un formato de N-ficheros-pequeños.
5. **Zero-copy hasta el final:** del mmap del slab a los arrays del motor sin pasar por pandas.
6. Commits convencionales pequeños; sin push sin avisar; merges los hace otra persona.

---

## 03 — Contratos de datos

> Este capítulo es la clave del "a la primera". Primero los contratos que **NO cambian** (la IA
> los debe preservar bit a bit), luego los **nuevos** (slab, índice, SimParams, flags, logs).

### 03.1 API pública — NO CAMBIA (ni una clave)

- `POST /api/backtest` → 202 `{job_id, dataset_id, status}` (o sync con header
  `X-Backtest-Sync: true`). Modelo de entrada: `BacktestRequest`
  (`backtest_orchestrator.py:22-42`): `dataset_id: str`, `strategy_id: str|None`,
  `strategy_definition: dict|None`, `init_cash: float=10000`, `risk_r: float=100`,
  `risk_type: str="FIXED"`, `fixed_ratio_delta: float=500`, `size_by_sl: bool=False`,
  `fees: float=0`, `fee_type: str="PERCENT"`, `monthly_expenses: float=0`, `slippage: float=0`,
  `start_date/end_date: str|None`, `market_sessions: list[str]|None`,
  `custom_start_time/custom_end_time: str|None`, `locates_cost: float=0`,
  `locate_type: str="PERCENT"`, `look_ahead_prevention: bool=False`.
- `GET /api/backtest/{job_id}` (estado), `GET /api/backtest/{job_id}/result` (resultado SIN
  `equity_curves`), `GET /api/backtest/{job_id}/equity/{date}` (equity por día),
  `GET /api/backtest/progress/{dataset_id}`, `POST /api/backtest/cancel/{dataset_id}`.
- Resultado (claves literales — `backtest_service.py:744-752` y `_aggregate_metrics`:1274-1301):
  `aggregate_metrics{total_days, total_trades, win_rate_pct, avg_return_per_day_pct,
  total_return_pct, avg_sharpe, max_drawdown_pct, avg_profit_factor, avg_pnl, total_pnl,
  sortino_ratio, calmar_ratio, dd_return_ratio, r_squared, max_mae, max_profit_pct, avg_win,
  avg_loss, max_consecutive_wins, max_consecutive_losses, expectancy, payoff_ratio,
  total_expenses, total_pnl_net, avg_r_per_day, avg_r_ui}`, `day_results[]`, `trades[]`,
  `equity_curves[]`, `global_equity[]`, `global_equity_expenses[]`, `global_drawdown[]`.
- **Trade** (claves de `_enrich_trades`, `backtest_service.py:870-896`): `ticker, date,
  entry_time, exit_time, entry_idx, exit_idx, entry_time_epoch, exit_time_epoch, entry_price,
  exit_price, pnl, fees, return_pct, direction("Long"|"Short"), status("Closed"), size,
  exit_reason, mae, mfe, r_multiple, entry_hour, entry_weekday, gap_pct, stop_loss`.
- Punto de equity: `{time: int epoch_s, value: float}`.

### 03.2 Contrato del stream de pares — SEMÁNTICA QUE EL SLAB DEBE REPRODUCIR

`get_intraday_stream(qualifying_df, date_from, date_to)` (`data_service.py:1061`) devuelve un
iterador de `((date, ticker), day_df)` donde HOY (`gcs_cache.iter_intraday_groups_streamed`):

- `date`: `str "YYYY-MM-DD"` (viene de la **columna `date` del parquet fuente**, no derivada del
  timestamp) — el slab debe agrupar por esa misma columna.
- `day_df` columnas y dtypes actuales: `ticker` (category/str), `date` (str), `timestamp`
  (datetime64[ns] **naive**, hora de pared ET), `open/high/low/close` (float32), `volume` (int32).
- Orden de emisión: meses en orden cronológico; dentro del mes, orden de
  `groupby(["date","ticker"])` = **lexicográfico por (date, ticker)**.
- Aguas abajo, `_preprocess_pair` (`backtest_signals.py:400`) hace
  `sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="first")` y descarta
  pares con `len < 5`.

**Contrato del stream slab (nuevo, equivalente):** emite pares en el MISMO orden, con arrays ya
ordenados por timestamp y deduplicados con la MISMA regla (primera fila tras orden estable), y
`len ≥ 5`. La equivalencia se verifica bit a bit en T-B6.

### 03.3 Contrato interno del dict de señales — NO CAMBIA

Salida de `_compute_signals_for_pair` (`backtest_signals.py:311-329`), consumida por
`simulate_and_accumulate`: claves `date, ticker, entries_arr(bool[n]), exits_arr(bool[n]),
arrays{open,high,low,close,volume: float64[n], timestamp: datetime64[n], hod, lod, pm_high,
pm_low, prev_high, prev_low: float64[n]}, patch_mask(bool[n]), timestamps_arr(int64 ns),
sig_direction("longonly"|"shortonly"), sig_accept_reentries(bool), sig_max_reentries(int),
sig_sl_stop(float|None), sig_sl_trail(bool), sig_tp_stop(float|None),
sig_tp_time_limit(float|str|None), sig_trail_pct(float|None), sig_partial_tps(list|None),
gap_pct(float|None)`.

### 03.4 Contrato de `simulate()` — LA especificación del kernel JIT

Firma completa en `portfolio_sim.py:14-55`. Semántica que el kernel replica **en el mismo orden
de ramas** (línea de referencia):

- Patch de misprints 08:00-08:45 (`patch_mask`), `skip_exits` salvo última barra (86-91).
- Orden de exits: hard stop (Market Structure o `sl_stop`) → trailing (activación por
  `trail_pct`, high-water mark, no pisar un hard stop mejor) → TP full / `tp_time_limit`
  (`float` minutos o `"HOUR:h:m"`) → **partial TPs** (lista, cada uno una vez; tipos
  `float` distancia | `"EOD"` | `"TIME:<mins>"` | `"HOUR:<h>:<m>"`; cierre de `capital_pct`
  sobre el size original; si el size llega a ≤0.0001 la posición se cierra) → MAE/MFE (acotados
  por el precio de stop/TP ejecutado) → elapsed time (`elapsed_limit` + `elapsed_operator` en
  {GREATER_THAN_OR_EQUAL/GTE, GREATER_THAN/GT, LESS_THAN/LT, LESS_THAN_OR_EQUAL/LTE, EQUAL/EQ})
  → exit por señal (con `look_ahead_prevention` → fill en `open[i+1]`) → EOD forzado en `n-1`.
- Entradas: detección de flanco (`current_signal and not prev_signal`), reentries
  (`max_reentries`/`accumulate`), sizing (`risk_type` FIXED|PERCENT|FIXED_RATIO con fórmula
  Ryan Jones, `size_by_sl` por distancia al stop, cap por `available_cash`), slippage al precio.
- Locates: fee diario por bloques de 100 shares sobre `max_short_size_today`, restado al PRIMER
  trade Short y a TODA la curva equity (717-744).
- Equity: `init_cash + realized + unrealized(close[i])` por barra.
- **Redondeos (contrato de salida, hacer en el adapter Python con `round()`):**
  `entry_price/exit_price/stop_loss/size` → 6 decimales; `pnl/fees/return_pct/mae/mfe` → 4.
- **Literales de `exit_reason`:** `"Signal", "SL", "Trailing", "TP", "Time Limit", "EOD",
  "Partial TP", "Partial TP (EOD)", "Partial TP (Time)", "Partial TP (Hour)"`.
- **Quirk a preservar:** los trades de partial TP **no llevan clave `fees`** (el consumidor usa
  `t.get("fees", 0.0)`); el trade de cierre final sí.
- `hs_type` literal: `"Market Structure (HOD/LOD)"`; `hs_value` literales: `"HOD","LOD","PMH",
  "PML","Previous Max","PrevMax","Previous Min","PrevMin","Previous Low","PrevLow"`.
- Hora para `"HOUR:h:m"`: hoy `datetime.fromtimestamp(ts/1e9, tz=UTC)` sobre timestamps naive →
  equivale a `hour = (ts_ns // 3.6e12) % 24`, `minute = (ts_ns // 6e10) % 60`. El kernel usa la
  aritmética entera (idéntica para ts ≥ 0).
- Retorno: `{"equity": float64[n], "trades": list[dict], "last_risk_amount": float}`.

### 03.5 NUEVO — Slab store (formato en disco)

```
{BTT_SLAB_DIR}/                        (default: {CACHE_DIR}/slabs → /tmp/btt_intraday_cache/slabs; en prod definir volumen persistente)
  v1/
    {kind}/{year}/{month:02d}/
      slab.arrow        # Arrow IPC file (Feather v2) SIN compresión (mmap zero-copy)
      index.parquet     # índice de pares
      manifest.json     # metadatos/validez
```

**`slab.arrow`** — un solo RecordBatch (o batches contiguos), TODAS las filas del mes de la
fuente GCS (todos los tickers), con esquema EXACTO:

| Columna | Tipo Arrow | Semántica |
|---|---|---|
| `ts_ns` | int64 | timestamp naive ET en ns (el `timestamp` fuente castado) |
| `open`,`high`,`low`,`close` | float32 | precios (mismo downcast que hoy) |
| `volume` | int32 | mismo downcast que hoy (`gcs_cache._downcast_intraday`) |

Orden global: `(ticker, date_str, ts_ns)` ascendente, **deduplicado por (ticker, date_str,
ts_ns) conservando la primera fila** del orden estable — réplica exacta de
`sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="first")` que hoy se
aplica POR PAR (`backtest_signals.py:400`); la clave incluye `date_str` para no colapsar el
caso degenerado de un mismo (ticker, ts) etiquetado con dos `date` distintos en la fuente.
Ni `ticker` ni `date` se almacenan como columnas del slab (viven en el índice): los slices
por par son contiguos.

**`index.parquet`** — una fila por par presente en el mes:

| Columna | Tipo | Semántica |
|---|---|---|
| `ticker` | str | tal cual la fuente |
| `date` | str `YYYY-MM-DD` | la columna `date` de la fuente (NO derivada de ts) |
| `row_start` | int64 | inicio del slice en el slab (incl.) |
| `row_end` | int64 | fin (excl.); garantía: rangos contiguos, no solapados, ordenados por (date? NO: por posición física = ticker,date) |
| `n_rows` | int32 | `row_end - row_start` |

**`manifest.json`**: `{schema_version: 1, kind, year, month, source_glob, source_kind,
n_rows, n_pairs, built_at_iso, builder_git_sha, duckdb_version}`. Un slab es válido si existe
el trío y `schema_version` coincide; el sync lo reconstruye si cambia la fuente (nuevo fichero
en el glob o difiere `n_rows` del origen).

**Builder (contrato de construcción):** una query DuckDB por mes contra
`gs://…/{kind}/year=Y/month=M/*.parquet` (o contra la réplica local si existe):
`SELECT ticker, date, timestamp, open, high, low, close, volume … ORDER BY ticker, date, timestamp`
→ dedup por (ticker, ts) → escribir slab+índice+manifest de forma **atómica** (tmp + `os.replace`,
patrón de `gcs_cache._atomic_write_parquet:652`).

### 03.6 NUEVO — API interna del slab store (`app/db/slab_store.py`)

```python
class PairArrays(NamedTuple):
    ts_ns: np.ndarray      # int64[n], ordenado, sin duplicados
    open:  np.ndarray      # float64[n]  (upcast desde float32 del slab)
    high:  np.ndarray      # float64[n]
    low:   np.ndarray      # float64[n]
    close: np.ndarray      # float64[n]
    volume: np.ndarray     # float64[n]  (upcast desde int32)

def get_month(kind: str, year: int, month: int) -> MonthSlab | None
    # None si no hay slab válido (el caller decide fallback al path legacy)

class MonthSlab:
    pairs(self) -> pd.DataFrame            # el índice (ticker, date, row_start, row_end)
    slice(self, row_start: int, row_end: int) -> PairArrays   # zero-copy + upcast
    # backing: pyarrow.memory_map; NUNCA carga el fichero entero al heap

def iter_slab_groups(qualifying_df, date_from, date_to, strategy_def) -> Iterator[tuple[tuple[str,str], PairArrays, dict]]
    # Drop-in del stream actual PERO devolviendo PairArrays + daily_stats resueltos.
    # Orden de emisión idéntico al actual: mes cronológico, (date, ticker) lexicográfico.
    # Para meses SIN slab: fallback interno al path legacy (convierte el day_df legacy a
    #   PairArrays en el borde para que el consumidor vea UN solo tipo).
    # RESPONSABILIDADES QUE ABSORBE de _preprocess_pair (backtest_signals.py:336-404), con
    #   la MISMA semántica:
    #   - exclude_days / exclude_months (weekday()/month-1 sobre la fecha del par);
    #   - swing_option: si está activa, resolver lead_timestamp_1/2 desde daily_stats y
    #     CONCATENAR las velas del/los día(s) swing — sacándolas del slab del mes que toque
    #     (mismo ticker, date del lead) — y re-ordenar+dedup por ts como hoy;
    #   - descartar pares con n_rows < 5 (tras el concat swing).
```

Nota de tipos: `arrays["timestamp"]` del dict de señales (03.3) se obtiene de `ts_ns` con
`ts_ns.view("datetime64[ns]")` (vista zero-copy, no una conversión).

El upcast float32→float64 y la construcción de `timestamp` datetime64 (para las claves
`arrays["timestamp"]` del dict de señales) se hacen en el borde, una vez por par (~10 µs).

`daily_stats` sigue siendo **la fila completa de qualifying como dict** (sin cambios); claves
que el motor consume hoy y deben seguir llegando: `prev_close, yesterday_open, lag_rth_open_1,
gap_pct, yesterday_high, yesterday_low, rth_high, rth_low, previous_close, lead_timestamp_1,
lead_timestamp_2` (grep verificado 2026-07-02).

### 03.7 NUEVO — Contrato del chunk de worker (pipeline slab-aware)

Hoy el pipeline picklea `day_df` por chunk (`backtest_signals.py:520-537`). Con slab:

```python
# chunk enviado al worker (picklable, pequeño):
{
  "slab_ref": (kind, year, month),          # el worker abre su propio memory_map (initializer cachea por mes)
  "items": [
     {"date": str, "ticker": str, "row_start": int, "row_end": int,
      "daily_stats": dict},                  # la fila qualifying (ya es picklable hoy)
     ...
  ]
}
# el worker reconstruye PairArrays con MonthSlab.slice() y llama a
# _compute_signals_for_pair_native(...) → devuelve el dict de señales de 03.3 (sin cambios)
```

Regla forkserver: los memmaps NO se heredan; `_init_pipe_ctx` (patrón existente
`backtest_signals.py:549`) abre y cachea `MonthSlab` por `slab_ref` dentro del worker.

**Quién consume el stream slab (acotación importante):**

- El path slab se engancha SOLO al flujo `run_backtest` directo (el de
  `run_backtest_orchestrator`), que con flag ON usa una rama nueva: iterar `iter_slab_groups`
  → Mitad A (inline si `workers=1`, pipeline forkserver si >1, con los chunks de arriba) →
  `simulate_and_accumulate` sin cambios. **El loop secuencial groupby actual NO se toca** y
  sigue siendo el camino con flag OFF.
- El **optimizador** (`optimization_service.py`) usa `fetch_dataset_data` (monolítico), no
  `get_intraday_stream` → **no se ve afectado** por este PRD (hereda solo el simulador JIT).
- Las exclusiones (`exclude_days/months`) y el swing ya vienen resueltos por
  `iter_slab_groups` (03.6): el worker slab llama a `_compute_signals_for_pair` directamente,
  sin `_preprocess_pair`.

### 03.8 NUEVO — Encoding de parámetros del kernel JIT (`SimParams`)

El encoder (`encode_sim_params`, Python) convierte los kwargs string/None de `simulate()` a
escalares/arrays numba-friendly. Tabla de encoding (cerrada — el kernel no ve strings):

| Campo kernel | dtype | Encoding |
|---|---|---|
| `direction_is_long` | bool | `direction == "longonly"` |
| `risk_type_code` | int8 | 0=FIXED, 1=PERCENT, 2=FIXED_RATIO |
| `fee_is_flat` | bool | `fee_type == "FLAT"` |
| `locate_is_percent` | bool | `locate_type == "PERCENT"` |
| `hs_mode` | int8 | 0=None/`sl_stop`, 1=Market Structure |
| `hs_value_code` | int8 | 0=HOD, 1=LOD, 2=PMH, 3=PML, 4=PrevMax(+"Previous Max"), 5=PrevMin(+"PrevMin","Previous Low","PrevLow"), -1=otro (usa fallback 0.95/1.05) |
| `hs_sign` | float64 | +1 si `hs_operator` ∈ {">",">="} sino −1; `sl_offset = hs_sign*hs_offset_pct/100` |
| `sl_stop_v` | float64 | `sl_stop` o NaN |
| `tp_stop_v` | float64 | `tp_stop` o NaN |
| `tp_time_kind` | int8 | 0=None, 1=minutos (`tp_time_v=float`), 2=HOUR (`tp_time_h`,`tp_time_m` int16) |
| `trail_on` | bool / `trail_pct_v` float64 | `sl_trail and trail_pct is not None` |
| `elapsed_op_code` | int8 | 0=GTE(default), 1=GT, 2=LT, 3=LTE, 4=EQ |
| `ptp_kind[]` | int8[k] | por partial TP: 0=pct, 1=EOD, 2=TIME, 3=HOUR |
| `ptp_v1[], ptp_v2[], ptp_cap[]` | float64[k] | distancia/minutos/hora, minuto, capital_pct |
| `max_reentries, accumulate` | int64, bool | tal cual |

**Salida del kernel** (struct-of-arrays preasignados con capacidad `n*(k+1)+4`):
`entry_idx[], exit_idx[], entry_price[], exit_price[], pnl[], fees[], return_pct[], size[],
exit_reason_code[], mae[], mfe[], stop_loss[], n_trades, equity[n], last_risk_amount`.
Mapa `exit_reason_code → literal` (cerrado): 0=Signal, 1=SL, 2=Trailing, 3=TP, 4=Time Limit,
5=EOD, 6=Partial TP, 7=Partial TP (EOD), 8=Partial TP (Time), 9=Partial TP (Hour).
El **adapter** (`simulate_jit()` Python) aplica redondeos, materializa la lista de dicts con las
claves exactas de 03.4 (incl. omitir `fees` en parciales), aplica el post-proceso de locates y
devuelve el mismo dict que `simulate()`.

### 03.9 NUEVO — Dispatcher del simulador (`app/services/sim_dispatch.py`)

```python
# único punto de selección; backtest_service.py:21 pasa a importar de aquí
def simulate(**kwargs):
    if _numba_sim_enabled():          # BACKTEST_NUMBA_SIM=1 y kernel warm
        return simulate_jit(**kwargs) # misma firma, mismo retorno
    return _legacy_simulate(**kwargs) # from app.services.portfolio_sim import simulate
```

`portfolio_sim.py` **no se toca**. `api_public/tests/test_architecture.py` prohíbe a la API
comercial importar `services.portfolio_sim` — el dispatcher es un módulo nuevo: verificar que
esa prueba de arquitectura sigue verde (la fachada B2D no debe importar el dispatcher tampoco).

### 03.10 NUEVO — Variables de entorno (contrato de configuración)

| Variable | Default | Quién la lee | Significado |
|---|---|---|---|
| `BTT_SLAB_ENABLED` | `false` | slab_store/builder | master switch del slab store |
| `BTT_SLAB_STREAM_ENABLED` | `false` | `data_service.get_intraday_stream` | usar `iter_slab_groups` (con fallback interno por mes) |
| `BTT_SLAB_DIR` | `{CACHE_DIR}/slabs` | slab_store | raíz del store (en prod: volumen persistente) |
| `BTT_SLAB_PAGECACHE_WARM` | `false` | main.py startup | lectura secuencial de slabs al boot (page cache) |
| `BTT_REPLICA_SYNC_ENABLED` | `false` | main.py startup | hilo daemon que construye/refresca slabs de todo el histórico |
| `BTT_REPLICA_SYNC_INTERVAL_H` | `24` | replica_sync | cadencia del refresco |
| `BTT_REPLICA_YEARS` | `2021-2026` | replica_sync | rango a replicar (ampliar cuando aterrice 2018-2020) |
| `BACKTEST_NUMBA_SIM` | `0` | sim_dispatch | activar kernel JIT |
| `BACKTEST_PARALLEL_WORKERS` | `1` (existente) | backtest_signals | nº workers señales (prod: 6 tras EPIC E) |
| `DUCKDB_MEMORY_LIMIT` | `8GB` (existente) | connection.py | subir a `16GB` en prod (128 GB reales) — EPIC E |

### 03.11 NUEVO — Contrato de logs de fase (para medir en prod)

Formato único, greppable, una línea por fase por run:
`[TIMING] phase=<qualifying|stream_build|signals|simulate|aggregate|serialize|total> dataset=<id> pairs=<n> ms=<int> extra=<k=v,…>`
Se añaden SIN retirar los `[TIMING]` existentes (el frontend no los consume; son para operación).

---

## 04 — UI y componentes

**Sin cambios de UI.** La API, el polling de progreso y el shape del resultado no cambian.
Único efecto visible para el usuario: el mismo backtest termina antes. (El límite de este PRD
es el backend; cualquier mejora de FE es otro PRD.)

---

## 05 — Arquitectura

### 5.1 Ficheros NUEVOS

| Fichero | Contenido |
|---|---|
| `backend/app/db/slab_store.py` | `MonthSlab`, `PairArrays`, `get_month`, `iter_slab_groups` (03.6) |
| `backend/app/db/slab_builder.py` | build de un mes (query DuckDB → slab+índice+manifest atómicos) |
| `backend/app/db/replica_sync.py` | hilo daemon: descubrir meses en GCS, construir los que falten/invalidar, warm de page cache |
| `backend/app/services/portfolio_sim_jit.py` | `encode_sim_params`, kernel `@njit(cache=True)`, adapter `simulate_jit` |
| `backend/app/services/sim_dispatch.py` | dispatcher (03.9) + warmup |
| `backend/scripts/bench_e2e.py` | benchmark E2E reproducible (sintético + real si hay caché) con salida JSON |
| `backend/scripts/bench_simulate_jit.py` | microbench legacy vs JIT |
| `backend/tests/test_slab_store.py` | unidad slab/índice/slices + builder |
| `backend/tests/test_slab_stream_equivalence.py` | stream legacy vs slab bit a bit (T-B6) |
| `backend/tests/test_sim_jit_equivalence.py` | grid de configs × pares → trades exactos (T-D4) |
| `docs/rendimiento-backtester/BASELINE.md` | números de baseline capturados por el loop |
| `docs/rendimiento-backtester/INFORME_FINAL.md` | resultados antes/después por EPIC |

### 5.2 Ficheros EXISTENTES que se tocan (mínimo imprescindible)

| Fichero | Cambio | Tamaño |
|---|---|---|
| `backend/app/services/backtest_service.py` | línea 21: `from app.services.sim_dispatch import simulate` | 1 línea (consenso 07.C) |
| `backend/app/services/data_service.py` | `get_intraday_stream`: rama por flag → `iter_slab_groups` | ~10 líneas |
| `backend/app/services/backtest_signals.py` | variante de chunk slab-aware (03.7) + `_compute_signals_for_pair` aceptando `PairArrays` (rama aditiva; el path day_df queda intacto) | ~60 líneas aditivas |
| `backend/app/main.py` | startup: lanzar `replica_sync`/warm si flags ON (patrón del hilo recovery existente) | ~15 líneas |
| `backend/requirements.txt` | ninguna dependencia nueva prevista (pyarrow/numba/duckdb ya están) | 0 |

### 5.3 Lista NO-TOCAR y cómo se respeta

| Elemento no-tocar | Estrategia |
|---|---|
| `services/portfolio_sim.py` | queda intacto como especificación y fallback; el JIT vive en módulo nuevo; selección vía dispatcher |
| `services/indicators.py`, `backtester/engine.py` | no se tocan (las señales ya están optimizadas) |
| Parquet GCS / schemas `daily_metrics`/`intraday_1m` | el slab es caché **local** derivado; GCS sigue siendo fuente de verdad inmutable |
| Maquinaria caché por-ticker (`gcs_cache.py`) | NO se borra en este PRD: queda como fallback del stream (flag OFF → path actual). Su retirada es Fase 2 tras semanas de estabilidad |

### 5.4 Flujo end-to-end (antes → después)

```
HOY   : qualifying → [GCS ticker IN(...) → parquets por-ticker HDD → read×N → concat → to_datetime
        → merge → strftime → sort → groupby → sort+dedup por par] → señales → simulate(Py) → métricas
V2    : qualifying → [slab mmap (page cache 128GB) + índice → slices numpy zero-copy] → señales
        (6 workers, chunks de índices) → simulate_jit (Numba) serial → métricas
SYNC  : GCS (fuente de verdad, US) → replica_sync nightly → slabs locales v1 (todo el histórico)
```

### 5.5 Decisiones técnicas y alternativas descartadas

| Decisión | Alternativa descartada | Por qué |
|---|---|---|
| Slab Arrow IPC sin compresión + mmap | query DuckDB por run (5,5x medido) | el slab+índice da >10x y coste ~0 por par; DuckDB re-escanea por run |
| float32 en slab, upcast al slice | float64 en slab | paridad exacta con los datos de hoy (ya son float32) y la mitad de page cache; upcast medido despreciable |
| Slab de mes completo (todos los tickers) | slab por dataset | reusable entre datasets/usuarios, BROAD deja de ser especial, invalidación trivial |
| Kernel JIT paralelo a portfolio_sim + dispatcher | editar portfolio_sim.py | lista no-tocar; rollback = flag |
| Sync in-app (hilo daemon) | cron de host | el deploy es contenedor Coolify; sin acceso garantizado al host |
| simulate serial (post-JIT) | paralelizar Mitad B | compounding entre fechas es secuencial; a 2-5 µs/par la Mitad B deja de importar |

---

## 06 — PROMPT MAESTRO DE EJECUCIÓN (el guion para `/goal`)

> **Cómo usarlo:** pegar en Claude Code:
> `/goal Ejecuta docs/rendimiento-backtester/PRD_EJECUTABLE.md §06 de principio a fin: EPICs A→F en orden, cada tarea con test primero, comando de verificación en verde y commit; sin push; al terminar entrega INFORME_FINAL.md con los speedups medidos vs BASELINE.md`

### 6.0 Contexto que el agente DEBE leer antes de tocar nada

1. Este PRD entero (especialmente §03 contratos y §2.9 principios).
2. `docs/PERFORMANCE_ANALYSIS_CTO.md` (el porqué de cada palanca).
3. `backend/app/services/portfolio_sim.py` **completo** (es la spec del kernel).
4. `backend/app/services/backtest_signals.py` y `backend/app/services/backtest_service.py` completos.
5. `backend/app/db/gcs_cache.py` (el path que se reemplaza) y `backend/app/db/connection.py`.
6. `backend/tests/test_backtest_golden.py` (el gate) y `backend/tests/conftest.py`.
7. `.agent/CODING_RULES.md` (lista no-tocar, reglas de repo).

### 6.1 Restricciones globales no negociables

1. **Bit-idéntico**: si un test de equivalencia falla, se arregla el código nuevo, jamás se
   relaja el test (única excepción documentada: equity `atol=1e-9` en 03.8/07.B).
2. **No tocar**: `portfolio_sim.py`, `indicators.py`, `backtester/engine.py`, Parquet GCS.
3. **TDD**: por tarea → (a) test, (b) implementación hasta verde, (c) comando de verificación,
   (d) commit convencional. **No avanzar con algo en rojo.**
4. **Flags default OFF**; el path legacy debe seguir funcionando con flags OFF al final de cada EPIC.
5. Python del repo con pyarrow: en dev usar `backend/.venv_311/bin/python` (o `.venv_313`);
   en prod `/opt/venv/bin/python`. Verificar `import pyarrow` antes de asumir.
6. Rama de trabajo: la actual (`performance`) o una derivada `perf/motor-v2`. **Sin push ni
   merge sin aviso explícito de Jesús.** No commitear `.env`, `gcs-key*.json`, `*.duckdb`, datos.
7. Los datos de test se generan **sintéticos y offline** (fixtures en `tmp_path`); ningún test
   nuevo puede requerir red/GCS. Lo que exija servidor se marca `@pytest.mark.server` y se
   documenta como tarea manual.
8. Comandos de verificación base: `cd backend && .venv_311/bin/python -m pytest tests/<X> -q`.

### 6.2 PASO 0 — Verificación de entorno y baseline (antes de cualquier código)

- **T-00 · Entorno local**: verificar venv con pyarrow+duckdb+numba (`python -c "import pyarrow,
  duckdb, numba, pandas"`); correr `pytest tests/ -q` y anotar el estado de partida (hay tests
  que requieren datos/red: registrar cuáles fallan YA antes de tocar nada, para no atribuirse
  regresiones ajenas). Commit: `chore(perf): registrar estado de partida de la suite`.
- **T-01 · Entorno prod (si hay acceso; si no, dejar el guion para Jesús en BASELINE.md)**:
  dentro del contenedor: `nproc; free -g; lsblk -d -o NAME,ROTA,SIZE; cat /sys/fs/cgroup/memory.max;
  df -h; du -sh $CACHE_DIR; env | grep -E 'BACKTEST|INTRADAY|DUCKDB|CACHE|BTT'`.
- **T-02 · Baseline medida**: crear `backend/scripts/bench_e2e.py` (dataset sintético
  reproducible: semilla fija, ~600 pares/mes × 3 meses, estrategia short simple tipo la del
  PRD de señales) que mida por fase (stream/señales/simulate/agg) e imprima JSON. Correrlo 3×,
  guardar mediana en `docs/rendimiento-backtester/BASELINE.md` junto a los números del análisis.
  Verif: `python scripts/bench_e2e.py --check` (autovalida shape del output).
  Commit: `feat(perf): benchmark E2E reproducible + baseline`.

### 6.3 EPIC A — Instrumentación (0,5 día)

- **T-A1 · Logs de fase (03.11)**: añadir los `[TIMING] phase=…` en orchestrator/service/signals
  sin retirar los existentes. Test: unit que captura logging y valida formato greppable.
  Verif: `pytest tests/test_timing_logs.py -q`. Commit: `feat(perf): logs de fase homogéneos`.

### 6.4 EPIC B — Slab store (2-3 días) → gate: ensamblado ≥6x + equivalencia bit a bit

- **T-B1 · Esquema y builder de un mes**: `slab_builder.build_month(kind, y, m, source)` con
  fuente inyectable (para tests: dir local de parquets sintéticos con la MISMA forma que GCS:
  columnas ticker,date,timestamp,open,high,low,close,volume, duplicados y desorden incluidos).
  Test primero: mes sintético con (a) timestamps duplicados, (b) tickers intercalados, (c) par
  con <5 filas, (d) día sin datos de un ticker → slab ordenado/dedup + índice con rangos
  contiguos correctos + manifest válido. Verif: `pytest tests/test_slab_store.py -q -k builder`.
- **T-B2 · MonthSlab + slices**: mmap, `pairs()`, `slice()` con upcast float64; test de
  zero-copy (el buffer de `open` comparte memoria con el mmap antes del upcast) y de valores.
- **T-B3 · `iter_slab_groups`**: mismo orden de emisión que el stream actual (mes cronológico,
  (date,ticker) lexicográfico); fallback por-mes al path legacy cuando no hay slab; absorbe
  exclusiones y swing con la semántica exacta de `_preprocess_pair` (tests con swing_option
  activa: el día lead sale del slab y el concat+dedup reproduce el resultado actual).
- **T-B4 · Rama en `get_intraday_stream`** bajo `BTT_SLAB_STREAM_ENABLED` (OFF por defecto).
- **T-B5 · `_compute_signals_for_pair` sobre `PairArrays`** (rama aditiva `pair_arrays=`):
  produce el dict 03.3 idéntico al del path day_df (test con el mismo par por ambas vías).
- **T-B6 · EQUIVALENCIA DE STREAM (el gate)**: con el mismo mes sintético servido (a) por el
  path pandas actual (`_fetch_and_cache_month`+groupby+`_preprocess_pair`) y (b) por slab:
  misma secuencia de pares, y por par `np.array_equal` en O/H/L/C/V/ts tras la limpieza.
  Verif: `pytest tests/test_slab_stream_equivalence.py -q`.
- **T-B7 · Bench**: `bench_e2e.py --stream slab` vs baseline → **≥6x** en fase stream_build.
  Actualizar BASELINE.md con la tabla. Commit final EPIC: `feat(perf): slab store mensual + stream zero-copy (flag OFF)`.

### 6.5 EPIC C — Réplica local + warm (1-2 días) → gate: primera ejecución = steady

- **T-C1 · `replica_sync`**: descubre meses (glob GCS, patrón de `_ensure_glob_metadata_cached`),
  construye slabs que falten (opt preferente, raw fallback), respeta `BTT_REPLICA_YEARS`,
  reintenta con backoff, nunca tumba el proceso. Test: con fuente sintética inyectada.
- **T-C2 · Warm de page cache**: lectura secuencial de slabs existentes al boot (hilo daemon,
  gated). Test: unit del orden (recientes primero) con FS sintético.
- **T-C3 · Arranque en `main.py`** bajo flags + logs de progreso. Verif: arrancar uvicorn local
  con flags ON y dir sintético → logs correctos, API responde.
  Commit: `feat(perf): réplica local de slabs + warm de page cache (flags OFF)`.
- **T-C4 (manual, documentar en BASELINE.md)**: en prod, primera construcción completa
  (~30-60 GB desde US; estimar y loggear); después, medir primera-vs-segunda ejecución de un
  dataset nuevo → objetivo ≤1.3x.

### 6.6 EPIC D — Motor JIT (1-3 días gracias al F2 previo) → gate: trades exactos + Mitad B ≥5x

> **NO escribir el kernel desde cero.** Existe un port previo bit-idéntico:
> `git show origin/feat/f2-numba-engine:backend/app/services/portfolio_sim_jit.py`
> (commit `435ef11`, MATCHED tol 0). Ese intento midió solo **1.7x** porque (a) el simulador
> no es el cuello con el ensamblado actual y (b) su wrapper re-codifica parámetros
> (strings→enums, arrays de partial TPs) EN CADA PAR. Este EPIC lo rescata con dos cambios:
> encoding hoisted a una vez por backtest (T-D1) y dispatcher sin tocar `portfolio_sim.py`.
> Primera tarea: leer entera esa rama y auditar diferencias vs el `portfolio_sim.py` actual
> (la rama es del 29-jun; verificar que no haya cambios posteriores en el Python).

- **T-D1 · `encode_sim_params`**: tabla 03.8 completa, construido UNA vez por backtest (en
  `run_backtest`, junto a `compile_strategy_def`) y pasado por el pipeline; tests de encoding
  para CADA literal (incluye `hs_value` con todos sus alias y partial TPs de los 4 tipos).
  Reusar los enums/códigos de la rama F2 si coinciden (son 1:1 con 03.8).
- **T-D2 · Kernel `@njit`**: partir del `_core_simulate_jit` de la rama F2 (adaptado al módulo
  nuevo); verificar rama a rama contra el `portfolio_sim.py` ACTUAL por si divergió desde
  junio. Sin objetos Python; salidas struct-of-arrays con capacidad `n*(k+1)+4`; fastmath OFF,
  single-thread (reglas del propio docstring de F2).
- **T-D3 · Adapter `simulate_jit`**: redondeos con `round()` de Python, dicts con claves exactas
  (omitir `fees` en parciales), post-proceso de locates, `last_risk_amount`.
- **T-D4 · EQUIVALENCIA MASIVA (el gate)**: property-test con semilla fija: ≥200 configuraciones
  muestreadas del espacio (direction × risk_type × size_by_sl × fees/fee_type × slippage ×
  sl/tp/trailing × partial TPs de los 4 tipos × elapsed × locates × look_ahead × patch_mask ×
  accumulate/max_reentries × hs Market Structure con cada hs_value) × 50 pares sintéticos
  (390/960 barras, con y sin señales) → `trades` **idénticos** (tras redondeo) y `equity`
  exacta (o `atol=1e-9` documentado). Verif: `pytest tests/test_sim_jit_equivalence.py -q`.
- **T-D5 · Dispatcher + swap del import** (`backtest_service.py:21` → `sim_dispatch`), warmup
  del kernel en startup (compilación fuera del primer request), flag `BACKTEST_NUMBA_SIM`.
  Verificar que `api_public/tests/test_architecture.py` sigue verde.
- **T-D6 · Bench**: `bench_simulate_jit.py` → objetivo kernel warm con encode hoisted **≥10x**
  vs Python; **gate duro del EPIC (lo que importa E2E): fase simulate+accumulate ≥5x vs
  baseline y <15% del E2E con slab ON**. Si el kernel no llega a 10x, desglosar dónde se va
  (encode/adapter/kernel) en el informe — no bloquear si el gate E2E pasa.
  Commit: `feat(perf): kernel Numba del simulador + dispatcher (flag OFF)`.

### 6.7 EPIC E — Paralelismo + tuning (1-2 días) → gate: E2E ≥8x

- **T-E1 · Chunks slab-aware** (03.7): `run_pipelined_signals` despacha índices en vez de
  DataFrames cuando el stream es slab; initializer del worker abre memmaps. Test: pipeline con
  2 workers sobre mes sintético → señales idénticas al secuencial (patrón del gate tol-0 que ya
  usa el módulo).
- **T-E2 · Envs de la caja real**: documentar (no aplicar en código) los valores prod
  recomendados: `BACKTEST_PARALLEL_WORKERS=6`, `DUCKDB_MEMORY_LIMIT=16GB`,
  `BTT_SLAB_*=true`, `BACKTEST_NUMBA_SIM=1` → tabla en INFORME_FINAL.md para que Jesús los
  ponga en Coolify.
- **T-E3 · Bench final**: `bench_e2e.py` con todo ON (flags en el entorno del bench, no en
  defaults) → **≥8x** vs BASELINE.md en la máquina de dev; tabla comparativa por fase.
  Commit: `feat(perf): pipeline slab-aware + tuning (flags OFF por defecto)`.

### 6.8 EPIC F — Cierre (0,5 día)

- **T-F1 · Comentarios desfasados**: actualizar los comentarios "CCX23/CCX33/15GB/30GB" de
  `gcs_cache.py`, `backtest_signals.py`, `database.py`, `routers/backtest.py` a la caja real
  (W-2145/128GB/HDD) — solo comentarios, cero lógica.
- **T-F2 · Runbook de operación**: `docs/rendimiento-backtester/RUNBOOK.md` — cómo activar
  flags en Coolify por fases (orden: slab → réplica → JIT → workers), cómo verificar Golden B
  en servidor (referencia al docstring de `test_backtest_golden.py`), cómo hacer rollback
  (flags OFF), y el guion de T-01/T-C4 si no hubo acceso a prod.
- **T-F3 · INFORME_FINAL.md**: tabla antes/después por fase y por EPIC, gates pasados,
  pendientes de servidor (Golden B, medición prod), y decisiones abiertas restantes (07).
  Commit: `docs(perf): runbook + informe final`.

### 6.9 Definition of Done

**Por tarea**: test primero y en verde · comando de verificación pasa · `pytest tests/ -q` sin
NUEVAS regresiones vs T-00 · no se tocó la lista no-tocar · commit convencional.

**Global**: los 4 gates (B6, C4*, D4, E3) verdes (*C4 puede quedar como tarea de servidor
documentada) · con flags OFF el comportamiento es EXACTAMENTE el de hoy (suite completa igual
que en T-00) · métricas de éxito 1-2-6 de §2.8 medidas y ≥ objetivo · BASELINE.md e
INFORME_FINAL.md completos · Golden B documentado como paso previo a activar flags en prod.

### 6.10 Orden de PRs sugerido (revisables por separado)

1. PR-1: PASO 0 + EPIC A (bench + baseline + logs) — inocuo.
2. PR-2: EPIC B (slab store, flag OFF).
3. PR-3: EPIC C (réplica/warm, flags OFF).
4. PR-4: EPIC D (JIT + dispatcher, flag OFF) — el de revisión más fina (Adrián).
5. PR-5: EPIC E + F (pipeline, tuning doc, runbook, informe).

---

## 07 — Decisiones abiertas

### A. Producto / negocio / operación (dueño: **Jesús** — NO las decide la IA)

| # | Decisión | Recomendación |
|---|---|---|
| A1 | ¿Cuándo activar cada flag en prod? (orden sugerido en RUNBOOK) | tras Golden B verde, activar slab→réplica→JIT→workers con 1-2 días entre pasos |
| A2 | ¿Migrar el bucket GCS a `europe-west3`? (coste egress de la copia una vez; menor latencia para siempre) | sí, cuando convenga; con réplica local deja de ser urgente |
| A3 | ¿NVMe / caja nueva (AX102) tras medir P1-P4? | decidir con el INFORME_FINAL en la mano |
| A4 | ¿Publicar benchmark competitivo (marketing)? | diferido |
| A5 | Ventana para la primera construcción de réplica (~30-60 GB desde US, horas) | lanzarla de noche con `BTT_REPLICA_SYNC_ENABLED=true` |
| A6 | ~~¿Por qué se revirtió PR #4?~~ **RESUELTO (2-jul):** lo revirtió Jesús por no ver mejora (el PR atacaba el ~3% del tiempo total); no hubo bug → re-merge desbloqueado | cerrado |

### B. Defaults técnicos reversibles (los asume la IA; cambiarlos = tocar 1 línea/env)

- Slab float32 + volume int32 (paridad con datos actuales); Arrow IPC sin compresión.
- `BTT_SLAB_DIR` bajo `CACHE_DIR`; en prod moverlo a volumen persistente (env).
- Preferencia `opt` sobre `raw`; réplica 2021-2026 por defecto (`BTT_REPLICA_YEARS`).
- Workers prod 6 (de 8C/16T); `DUCKDB_MEMORY_LIMIT` 16GB; warm de page cache recientes-primero.
- Tolerancia residual SOLO en equity (`atol=1e-9`) si el bit-exacto resulta imposible tras
  esfuerzo razonable — trades siempre exactos. Si se usa, documentarlo en INFORME_FINAL.
- El caché por-ticker actual NO se borra (fallback); retirada en Fase 2.

### C. Consenso con Adrián (CTO) — marcar en el PR, no bloquear el desarrollo

| # | Punto | Por qué le toca |
|---|---|---|
| C1 | Swap del import `backtest_service.py:21` → `sim_dispatch` | única línea tocada en zona core |
| C2 | Kernel JIT como módulo paralelo a `portfolio_sim.py` (no-tocar respetado) | dueño del motor |
| C3 | Slab store como formato de caché local v1 (GCS intacto) | dueño de datos |
| C4 | Ejecución de Golden B en servidor antes de activar flags | él tiene el runbook del golden |

---

## Apéndice A — Minuta de decisiones (sesión Jesús ↔ agente, 2026-07-02)

- Jesús: "la competencia va 5-10x más rápido; cualquier solución vale (hardware, software,
  tipos de datos, lenguajes)". → El análisis medido descartó reescritura de lenguaje/GPU y fijó
  las palancas P1-P5 (ver PERFORMANCE_ANALYSIS_CTO.md §4-5). **Confirmado implícitamente** al
  pedir este PRD sobre ese plan.
- Jesús corrigió el hardware asumido: **no** es CCX33 cloud; es dedicado **Xeon W-2145,
  128 GB, HDDs Enterprise, FSN1-DC6** (captura de la Serverbörse, ~€134,70/mes). → §1.1;
  reforzó el diseño slab-secuencial + page cache y desbloqueó cachés RAM.
- Pendiente de Jesús (no bloquea): decisiones A1-A5.
- Asunciones técnicas reversibles tomadas por el agente: 07.B.

## Apéndice B — Mediciones de referencia (resumen; detalle en PERFORMANCE_ANALYSIS_CTO.md)

| Medición (M4, 2026-07-02) | Valor |
|---|---|
| Ensamblado actual, steady, por par | 1.909 µs (read×300=340ms · to_datetime+merge=413ms · strftime=110ms · sort/groupby=87ms · preproc/par=202µs) |
| Misma tarea en 1 query DuckDB | 208 ms (5,5x) — cota inferior del beneficio del slab |
| Señales fast-path | ~66 µs/par |
| `simulate()` Python | 51-159 µs/par (390-960 barras, 1-5 trades) |
| Serialización 20k trades | sanitize 397 ms + msgpack 275 ms (35 MB) |
| GCS 1 ticker×mes / 20 tickers×mes | 2,7 s / 74 s (red doméstica; bucket US) |
| Mes optimizado GCS | 1 fichero, ~37M filas, 304 row-groups ordenados por ticker |
| Universo gap≥20% 2022-2026 | ~35.000 pares |
