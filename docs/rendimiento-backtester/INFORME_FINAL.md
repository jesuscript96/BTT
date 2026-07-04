# INFORME FINAL — Motor V2 del backtester (ejecución del PRD, 2026-07-02)

**Rama:** `performance` · **Commits:** `c81d394` (PASO 0) → `31db8ef` (A) → `61af2e7` (B) →
`080acb7` (C) → `5bb2ba7` (D+E) → este (F).
**Todo detrás de flags con default OFF** — desplegar sin tocar envs = comportamiento actual.
Activación por fases: [`RUNBOOK.md`](RUNBOOK.md). Baseline completo: [`BASELINE.md`](BASELINE.md).

---

## 1. El resultado en una tabla (mismo dataset, mismo checksum, código real)

Bench E2E sintético reproducible (`scripts/bench_e2e.py`): 1.200 pares, 3 meses,
840 barras/día, estrategia SHORT 1m del repo, sesión RTH. Máquina: M4 (dev).
**Checksum idéntico en TODAS las variantes: 639 trades, PnL −17.49, win rate 50.39.**

| Variante | assemble | preproc | señales | simulate+accum | total | **speedup** |
|---|---|---|---|---|---|---|
| **Baseline** (path actual, caché disco caliente) | 1.831 ms | 331 ms | 144 ms | 224 ms | **2.532 ms** | 1x |
| + Slab store (EPIC B) | **12 ms** | 0 | 66 ms | 219 ms | **299 ms** | **8,5x** |
| + Kernel JIT + Mitad B slim (EPIC D) | 13 ms | 0 | 66 ms | **72 ms** | **152-154 ms** | **16,8x** |
| Por `run_backtest` REAL (slab+JIT, incl. agregados) | — | — | — | — | **169,5 ms** | **~15x** |

**Matriz final con directorios aislados (tras el fix de staleness `cad5ef7`):**

| Escala | Legacy | Slab+JIT | Speedup | Checksum (idéntico en ambos) |
|---|---|---|---|---|
| 1.200 pares (200 tk/mes) | 2.589 ms (2.158 µs/par) | **154,3 ms** (129 µs/par) | **16,8x** | 639 trades · PnL −17,49 |
| 3.000 pares (500 tk/mes) | 6.623 ms (2.208 µs/par) | **581,6 ms** (194 µs/par) | **11,4x** | 1.557 trades · PnL −20,28 |

El coste por par del path legacy es constante con la escala (~2.200 µs) → extrapolación
lineal válida. Backtest típico de prod (gap ≥20%, 2022-2026 ≈ 35.000 pares, W-2145 ≈
×1,8-2 vs M4): **~2,5-3 min → ~12-25 s** en steady-state. Y con la réplica local (EPIC C),
la **primera ejecución cuesta lo mismo que las siguientes** (hoy: +minutos de GCS US↔EU).

## 2. Qué se construyó (y qué NO se tocó)

| Pieza | Archivo(s) | Flag |
|---|---|---|
| Logs de fase greppables `[TIMING] phase=...` | `app/services/perf_timing.py` + hooks | (siempre on, inocuo) |
| Slab store: 1 fichero Arrow/mes mmap + índice de pares + manifest | `app/db/slab_builder.py`, `app/db/slab_store.py` | `BTT_SLAB_ENABLED` implícito |
| Stream slab en `run_backtest` (con fallback por mes al path legacy) | rama en `backtest_service.py`, driver en `backtest_signals.py` | `BTT_SLAB_STREAM_ENABLED` |
| Réplica local del histórico + warm de page cache (fuente configurable GCS→mirror local) | `app/db/replica_sync.py` + startup `main.py` | `BTT_REPLICA_SYNC_ENABLED`, `BTT_REPLICA_SOURCE` |
| Kernel Numba del simulador (rescatado de `feat/f2-numba-engine` de Adrián) + dispatcher | `app/services/portfolio_sim_jit.py`, `app/services/sim_dispatch.py` | `BACKTEST_NUMBA_SIM` |
| Mitad B sin pandas por par (réplicas exactas de enrich/equity) | `backtest_signals.py` | (con el resto) |
| Bench E2E + informes | `scripts/bench_e2e.py`, docs/ | — |

**Intocados (lista sagrada):** `portfolio_sim.py` (queda como especificación y fallback),
`indicators.py`, `backtester/engine.py`, Parquet de GCS. Único cambio en zona core:
el import de `simulate` en `backtest_service.py:21` ahora apunta al dispatcher
(**consenso pendiente con Adrián — C1 del PRD**). El optimizador no se toca (hereda el JIT).

## 3. Gates de equivalencia (todo verde en local)

| Gate | Resultado |
|---|---|
| T-B6 · Stream legacy vs slab, bit a bit (arrays O/H/L/C/V/ts + orden) | ✅ 12 tests |
| Señales day_df vs pair_arrays (fast path + legacy translate, 3 configs de sesión) | ✅ |
| T-D4 · simulate Python vs JIT: 660 sims (220 configs × 3 tamaños) + cobertura de exit_reasons + edge cases | ✅ trades y equity **bit-idénticos** |
| Helpers rápidos Mitad B vs originales | ✅ dicts exactos |
| `run_backtest` COMPLETO legacy vs slab (inline / pool 2 workers / +JIT / mes sin slab→fallback) | ✅ resultado entero idéntico; el stream legacy ni se consume |
| Bench: checksum estable entre variantes y runs | ✅ 639/−17.49 en todas |
| **Golden B (servidor)** | ⏳ **PENDIENTE — correr en prod antes de activar flags (RUNBOOK §0)** |

## 4. Contra los gates numéricos del PRD

| Gate del PRD | Objetivo | Medido | Veredicto |
|---|---|---|---|
| B7 · fase ensamblado | ≥6x | **152x** (1.831→12 ms; +preproc absorbido) | ✅✅ |
| E3 · E2E | ≥8x | **15-16,6x** | ✅ |
| D6 · microbench kernel | ≥10x | kernel sí (simulate 224→~30 ms dentro de accum); la FASE completa quedó en 3,1x | ✅ kernel / ⚠️ fase |
| D6 · Mitad B <15% del E2E | <15% | 47% (72 de 152 ms) | ⚠️ no alcanzado |
| C4 · primera ejecución ≤1,3x steady | ≤1,3x | pendiente de prod (réplica) | ⏳ |
| §2.8-6 · RSS pico | ≤ hoy +10% | **1.260 MB → 640 MB (−49%)** (mmap: los meses no viven en el heap) | ✅✅ |

**Sobre los ⚠️ de D6 (honestidad):** tras el JIT, lo que queda de la Mitad B NO es el
simulador: es la construcción **contractual** del payload (dicts de equity 200 puntos/día,
dicts de trade) y las métricas por día (`_extract_day_stats_from_values`: ~12 ops numpy/día,
intocada por ser referencia compartida). Reducirlo más exige cambiar el formato del payload
(API v2 columnar — Fase 2 del PRD). El gate que importa al usuario (E2E ≥8x) está superado
con margen, que es exactamente la salida prevista en T-D6.

## 5. Hallazgos operativos (cambian recomendaciones del PRD)

1. **`BACKTEST_PARALLEL_WORKERS=1` es la config recomendada con slab+JIT** (no 6): las
   señales quedaron en ~55 µs/par y el spawn del pool forkserver cuesta más que el trabajo
   (medido: 6 workers = 682 ms vs inline 169 ms a 1.200 pares). El knob queda para
   estrategias multi-timeframe pesadas. El PRD asumía lo contrario — corregido en RUNBOOK.
2. La caída de F2 en junio (1,7x) queda explicada: el kernel era correcto, pero el cuello
   era el ensamblado. Con el slab delante, el mismo kernel rinde (simulate ~30 ms para 639
   días con trades).
3. La suite de tests contiene 2 módulos rotos DE ANTES (imports legacy:
   `test_backtest_engine.py`, `test_backtest_integration.py`) y tests que **cuelgan sin
   red/datos de prod** — la pasada inicial estuvo horas colgada hasta añadir
   `pytest-timeout`. Recomendación: mover esos 2 módulos a `_archive/` y adoptar
   `--timeout=90` en CI.
4. **Staleness de slabs (encontrado por el bench a escala, arreglado en `cad5ef7`):** un
   slab construido sobre una fuente que muta después se servía obsoleto. Ahora el manifest
   lleva `source_fingerprint` y `ensure_slabs_from_ticker_cache` reconstruye al detectar
   cambio (test de regresión incluido). Relevante para la migración de datos (mirror
   local mutable).

## 6. Estado de la suite completa

**21 ficheros verdes (~135 tests)** — todos los del motor con flags OFF + los 43 nuevos de
Motor V2. Los ficheros con fallos (legacy rotos, red/GCS, golden servidor-only) son
**pre-existentes**: verificado ejecutándolos sobre el commit `5bdaf8c` (anterior a este
trabajo) con fallos idénticos. **Cero regresiones atribuibles a Motor V2.**
Detalle por fichero: BASELINE.md §5.

## 7. Pendiente (no bloquea el merge, sí la activación)

- **Golden B en servidor** (RUNBOOK §0) — dueño: Adrián/Jesús.
- Primera construcción de la réplica en prod (~30-60 GB desde US, de noche) y medición
  primera-vs-segunda ejecución (gate C4).
- Consenso C1 (import dispatcher) + revisión del PR de Adrián sobre el kernel rescatado.
- Decisiones abiertas del PRD §07.A (bucket EU, hardware opcional). El revert de PR #4
  quedó aclarado: fue de Jesús por no ver mejora (atacaba el 3% del tiempo); sin bug.
- Migración de datos del CTO: cuando el mirror local exista, `BTT_REPLICA_SOURCE=/data/mirror`
  (cero código).
