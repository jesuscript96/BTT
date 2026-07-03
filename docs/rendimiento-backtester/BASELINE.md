# BASELINE — estado de partida medido (antes de Motor V2)

**Fecha:** 2026-07-02 · **Máquina:** Apple M4, 24 GB (dev de Jesús) · **Venv:** `backend/.venv_313`
(Python 3.13, duckdb 1.1.3, pandas 2.2.3, pyarrow 24.0.0, numba 0.64.0)

> Producción es un Xeon W-2145 (8C/16T, 2017) con HDDs: multiplicar tiempos single-thread
> por ~1.8-2 para estimar prod. Los speedups (ratios) sí son transferibles.

## 1. Bench E2E sintético (código real, offline) — `scripts/bench_e2e.py`

Config: 200 tickers/mes × 3 meses × 840 barras (04:00-18:00), 1.200 pares qualifying,
estrategia SHORT 3 condiciones 1m (la del benchmark del repo), sesiones RTH, mediana de 3 runs.

| Fase | ms (mediana) | µs/par | % |
|---|---|---|---|
| assemble (`_fetch_and_cache_month`, caché disco 100% hit) | 1.831,0 | 1.526 | **72,3%** |
| group_preproc (groupby + `_preprocess_pair`) | 331,5 | 276 | **13,1%** |
| signals (`_compute_signals_for_pair`, fast path N2a) | 144,1 | 120 | 5,7% |
| simulate_accum (`simulate_and_accumulate`, Python puro) | 223,5 | 186 | 8,8% |
| aggregate (equity global + métricas) | 2,1 | 2 | 0,1% |
| **TOTAL** | **2.532,2** | **2.110** | 100% |

**Checksum de referencia (debe coincidir en TODAS las variantes slab/jit):**
`n_trades=639 · total_pnl=-17.49 · win_rate_pct=50.39 · n_days=639` (estable en 3/3 runs).

Comando exacto:
```bash
cd backend && .venv_313/bin/python scripts/bench_e2e.py --runs 3 \
  --json /tmp/btt_bench_e2e/baseline_legacy_py.json
```

## 2. Microbench de referencia (del análisis 2026-07-02, mismo M4)

| Medición | Valor |
|---|---|
| `simulate()` Python puro | 51-159 µs/par (390-960 barras) |
| Señales fast-path (benchmark commit `5bdaf8c`) | ~66 µs/par |
| GCS 1 ticker×mes / 20 tickers×mes (red doméstica, bucket US) | 2,7 s / 74 s |
| Serialización 20k trades (sanitize+msgpack) | ~0,7 s |

## 3. Suite de tests — estado de partida (T-00)

- **Rotos DE ANTES (imports legacy inexistentes, no tocados por este trabajo):**
  - `tests/test_backtest_engine.py` — `ImportError: cannot import name 'Condition' from app.schemas.strategy`
  - `tests/test_backtest_integration.py` — `ImportError: cannot import name 'filter_market_data_by_interval_and_dates' from app.routers.backtest`
- Resto de la suite: ver sección 5 (se completa al terminar la pasada inicial).

## 4. Guion de medición en PRODUCCIÓN (T-01 — para Jesús/CTO, no ejecutado desde dev)

Dentro del contenedor (Coolify):
```bash
nproc; free -g; lsblk -d -o NAME,ROTA,SIZE          # ROTA=1 ⇒ HDD
cat /sys/fs/cgroup/memory.max                        # límite del contenedor
df -h; du -sh $CACHE_DIR
env | grep -E 'BACKTEST|INTRADAY|DUCKDB|CACHE|BTT'
```
Baseline funcional: lanzar 2 backtests representativos (un dataset gap chico y uno mediano,
ya cacheados) y guardar las líneas `[TIMING]` (con EPIC A ya emiten
`phase=qualifying|signals|simulate|stream_build|aggregate|serialize|total`). Repetir tras
activar cada flag (RUNBOOK) para el antes/después real de prod.

## 5. Mapa de la suite (por fichero, con watchdog de 150s — 2026-07-02, tras Motor V2)

**Verdes: 21 ficheros (~135 tests)** — incluidos TODOS los del motor (candle_delay,
compounding_r_metrics, full_tp_hour, max_reentries, partial_tp_hour, swing_option,
temporal_exclusions, timezone_ingestion) con flags OFF, y los 43 nuevos de Motor V2.

**Con fallos — TODOS PRE-EXISTENTES** (verificado ejecutándolos sobre el commit `5bdaf8c`,
anterior a Motor V2, con fallos idénticos):

| Fichero | Estado | Clase |
|---|---|---|
| test_backtest_engine.py / test_backtest_integration.py | error de import | legacy roto (imports inexistentes) → candidatos a `_archive/` |
| test_backtest_golden.py | failed | **diseñado para el servidor** (necesita datasets/caches de prod; su docstring lo dice) |
| test_backtest_queries.py, test_market_calculations.py, test_market_filters_{basic,advanced}.py | COLGADOS >150s (matados) | requieren red/GCS; uno de ellos quema CPU sin fin — la causa de que `pytest tests/` se cuelgue horas en local |
| test_new_metrics_tier{1,2,3}.py | 6+9+8 failed | dependen de datos reales (verificado idéntico en `5bdaf8c`) |
| test_prefetch_parity.py | 1 failed (65s) | red/GCS |
| test_strategy_api.py | 1 failed (422) | pre-existente (idéntico en `5bdaf8c`) |

Recomendación CI: `--timeout=90` global (pytest-timeout ya instalado en `.venv_313`),
mover los 2 legacy a `_archive/` y marcar los de red con `@pytest.mark.server`.
