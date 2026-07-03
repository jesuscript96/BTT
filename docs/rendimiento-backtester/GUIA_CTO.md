# Guía para el CTO — Revisar, mergear y activar Motor V2 ([PR #5](https://github.com/jesuscript96/BTT/pull/5))

> **Para:** Adrián. **De:** Jesús (+ IA). **Tiempo estimado:** revisión 45-90 min · merge 5 min ·
> activación 3 fases en 2 días (la noche de por medio construye la réplica).
>
> **La frase clave: mergear este PR no cambia NINGÚN comportamiento.** Todo va detrás de
> flags con default OFF. La mejora (backtests 15x, mismos resultados bit a bit) solo aparece
> cuando actives los envs de la §4, en orden, con el golden entre medias.

---

## 0. Qué es esto en 60 segundos

El cuello de botella del backtester NO eran las señales ni el simulador: era el **ensamblado
pandas** del intradía (85% del tiempo: read_parquet×N + concat + merge + strftime + sort +
groupby + dedup por par, re-ejecutado en cada run) y la **distancia a los datos** (bucket US
↔ Falkenstein, con amplificación de lectura enorme). Motor V2:

1. **Slab store** — caché local mensual columnar (1 fichero Arrow mmap por mes + índice
   `(ticker,date)→[row_start,row_end)`): el backtest lee slices numpy zero-copy. 1.831ms → 12ms.
2. **Réplica local** — daemon que construye slabs de todo el histórico (fuente configurable:
   GCS hoy, tu mirror local cuando migres los datos — cambiar 1 env).
3. **Tu kernel F2** (`feat/f2-numba-engine`, `435ef11`) rescatado **verbatim** a
   `portfolio_sim_jit.py` + dispatcher. En junio midió 1.7x porque el cuello era el ensamblado;
   con el slab delante rinde como debía. `portfolio_sim.py` está **intacto**.

**Números** (bench del pipeline real, checksum de resultados idéntico en todas las variantes):
1.200 pares 2.589→**154ms (16,8x)** · 3.000 pares 6.623→**582ms (11,4x)** · RSS pico −49% ·
extrapolado a prod (35k pares, W-2145): ~2,5-3 min → **~12-25 s**, y la primera ejecución
deja de pagar GCS.

Contexto completo: [`RESUMEN_EJECUTIVO.md`](RESUMEN_EJECUTIVO.md) ·
[`../PERFORMANCE_ANALYSIS_CTO.md`](../PERFORMANCE_ANALYSIS_CTO.md) (análisis medido) ·
[`INFORME_FINAL.md`](INFORME_FINAL.md) (gates) · [`PRD_EJECUTABLE.md`](PRD_EJECUTABLE.md) (contratos).

---

## 1. ⚠️ LO PRIMERO — la pregunta del revert (bloquea el merge, nada más)

`main` contiene `8c9fa96` = revert del merge de **PR #4** (N1+N2a, las señales). Este PR
**re-introduce ese código deliberadamente**: Motor V2 lo requiere (`backtest_signals` importa
`translate_strategy_native`).

- **¿Por qué se revirtió PR #4?** Si fue por un bug/incidente real en prod → hay que saberlo
  y arreglarlo ANTES de mergear. Si fue por proceso/precaución → adelante.
- Nota de git: como el revert fue de un merge, re-mergear la rama no re-aplicaba lo revertido.
  El commit de merge `25b3c2b` lo resuelve explícitamente: ficheros del revert → versión de
  `performance` (verificado byte a byte), y tus fixes de develop conservados (el guard
  *stale optimized shadow* de `gcs_cache.py` está — solapamiento revert∩develop = cero ficheros).

## 2. Cómo revisar el PR (orden sugerido, ~45-90 min)

Los 10 commits van en orden lógico; los 4 que merecen tu ojo fino:

| Commit | Qué revisar | Dónde mirar |
|---|---|---|
| `61af2e7` slab store | La **semántica de limpieza** replica exactamente el path actual: orden estable (ticker,date,ts) + dedup keep-first = `sort_values("timestamp").drop_duplicates(keep="first")` por par; swing cross-month; exclusiones | `app/db/slab_builder.py::_normalize_month_df`, `app/db/slab_store.py::iter_slab_items` — y el gate `tests/test_slab_stream_equivalence.py` (bit a bit) |
| `5bb2ba7` JIT + run_backtest | (a) tu kernel está **sin tocar** (diff contra tu rama = solo el módulo/imports); (b) el **único cambio en zona core**: `backtest_service.py:21` importa `simulate` desde `sim_dispatch` (decisión C1 — es tuya); (c) la rama `_slab_mode` en `run_backtest` no toca el path legacy (con flag OFF, diff funcional = 0) | `app/services/sim_dispatch.py`, `app/services/portfolio_sim_jit.py`, rama `if _slab_mode:` en `backtest_service.py` |
| `cad5ef7` fingerprint | Un slab construido sobre fuente que mutó se reconstruye (staleness); relevante para tu migración de datos | `slab_builder.ticker_cache_fingerprint`, `tests/test_slab_staleness.py` |
| `25b3c2b` merge de main | La resolución del revert (§1): motor = versión performance, develop = conservado | `git show 25b3c2b` |

**Qué NO se tocó** (lista no-tocar): `portfolio_sim.py`, `indicators.py`*, `backtester/engine.py`,
Parquet de GCS, el optimizador, la API pública (ni una clave del response).
*`indicators.py` y `strategy_engine.py` traen los cambios de N1+N2a (PR #4) — eso es lo re-introducido, no cambios nuevos de este trabajo.

**Correr las garantías tú mismo** (en el Mac de Jesús o donde haya venv con pyarrow+numba):
```bash
cd backend
# 58 tests: equivalencias Motor V2 (bit a bit) + tests del motor legacy con flags OFF
.venv_313/bin/python -m pytest tests/test_slab_store.py tests/test_slab_stream_equivalence.py \
  tests/test_slab_staleness.py tests/test_replica_sync.py tests/test_sim_jit_equivalence.py \
  tests/test_accum_fast_equivalence.py tests/test_run_backtest_slab_equivalence.py \
  tests/test_timing_logs.py tests/test_candle_delay.py tests/test_compounding_r_metrics.py \
  tests/test_full_tp_hour.py tests/test_max_reentries.py tests/test_partial_tp_hour.py \
  tests/test_swing_option.py tests/test_temporal_exclusions.py -q

# bench antes/después con checksum (el "antes" usa el path actual de verdad)
.venv_313/bin/python scripts/bench_e2e.py --runs 3                      # legacy
.venv_313/bin/python scripts/bench_e2e.py --stream slab --sim jit --runs 3   # Motor V2
# → los dos deben imprimir el MISMO checksum (n_trades / total_pnl)
```
El gate más duro es `test_sim_jit_equivalence.py`: 660 simulaciones (220 configs × 3 tamaños,
espacio completo de parámetros: partial TPs de 4 tipos, hs_value con todos los alias, locates,
elapsed, FIXED_RATIO…) → trades y equity **bit-idénticos** entre tu kernel y el Python.

**Advertencia conocida:** la suite completa (`pytest tests/`) tiene deuda PRE-existente: 2
módulos con imports legacy rotos y 4 ficheros que cuelgan sin red/datos de prod (verificado
idéntico en `5bdaf8c`, el commit anterior a todo esto). Mapa por fichero en
[`BASELINE.md`](BASELINE.md) §5. Nada de eso es de este PR.

## 3. Merge + deploy + Golden B (el gate de resultados en TU entorno)

1. **Merge del PR #5** (squash NO recomendado — el merge `25b3c2b` documenta la resolución
   del revert; merge commit normal).
2. Deploy normal por Coolify. **Comportamiento idéntico** — sin envs nuevos no cambia nada.
   En el arranque verás logs nuevos inofensivos: `[REPLICA] disabled`, `[TIMING] phase=...`.
3. **Golden B dentro del contenedor** (tu runbook de siempre; ~15 min):
   ```bash
   /opt/venv/bin/python tests/test_backtest_golden.py    # flags OFF → todos MATCHED
   ```
   Si algún caso no MATCHea con flags OFF, es un problema del merge (o del revert de PR #4
   — ver §1), no de los flags: parar y avisar.
   > Por qué esto no se pudo hacer desde fuera: los casos del golden referencian estrategias/
   > datasets del `users.duckdb` de prod (en local da `404 Strategy not found`), y la
   > equivalencia bit a bit local se midió en ARM (M4) — el golden confirma en tu x86 con
   > tus versiones de numba/numpy.

## 4. Activación en Coolify (3 fases, con golden entre medias)

### Fase 1 — Réplica de slabs (construye datos; el backtester aún no la usa)
```bash
BTT_REPLICA_SYNC_ENABLED=true
BTT_REPLICA_SOURCE=gcs          # ← cuando migres los datos: /ruta/del/mirror (layout hive year=/month=)
BTT_REPLICA_YEARS=2021-2026     # ampliar a 2018-2026 cuando aterrice tu backfill
BTT_SLAB_DIR=/data/btt/slabs    # VOLUMEN PERSISTENTE (no /tmp): ~40-70 GB; sobrevive deploys
BTT_SLAB_PAGECACHE_WARM=true    # neutraliza los HDD con los 128 GB de RAM
```
Reiniciar **de noche**: la primera construcción baja ~30-60 GB desde el bucket US
(idempotente: si se corta, la siguiente pasada continúa; refresco cada 24h, el mes corriente
se reconstruye siempre). Verificar a la mañana:
```bash
find $BTT_SLAB_DIR -name manifest.json | wc -l    # ≈ 66 (meses 2021-2026)
df -h /data                                        # espacio OK
grep "\[REPLICA\] sync done" <logs> | tail -1
```

### Fase 2 — Stream slab (la palanca grande, ~8x)
```bash
BTT_SLAB_STREAM_ENABLED=true
```
Reiniciar → **Golden B otra vez** (debe seguir MATCHED) → lanzar un backtest conocido y mirar:
```bash
grep "\[TIMING\] phase=" <logs> | tail -8    # phase=signals ... mode=slab + tiempos
```
Meses sin slab (p. ej. mes recién empezado) caen solos al path legacy — verás
`[SLAB] YYYY-MM sin slab — fallback` — el sync nocturno los construye.

### Fase 3 — Kernel JIT (el resto, hasta ~15x) + tuning
```bash
BACKTEST_NUMBA_SIM=1
DUCKDB_MEMORY_LIMIT=16GB        # la caja tiene 128 GB; el cap actual es defensivo de la era CCX
BACKTEST_PARALLEL_WORKERS=1     # sí, 1 — ver nota
```
Reiniciar → verás `[JIT] simulate kernel warm en ~4s` (solo el primer boot; luego usa caché de
compilación) → **Golden B otra vez** → medir.

> **Nota workers=1:** con slab+JIT las señales quedan en ~55 µs/par y el pool forkserver
> cuesta más que el trabajo (medido: 6 workers = 4x MÁS LENTO a 1.200 pares). El knob queda
> para estrategias multi-timeframe pesadas si algún día `phase=signals` domina en los logs.

### Rollback de cualquier fase
Poner su flag a `false`/`0` y reiniciar. Sin migraciones, sin limpieza. Los slabs en disco
son inertes si el flag está OFF (puedes borrarlos si quieres el disco).

## 5. Operación y futuro

- **Medir el antes/después real**: captura `[TIMING] phase=total` de 2 datasets antes de la
  Fase 2 y después de la 3 → esa es la cifra de prod para el informe.
- **Tu migración de datos**: cuando el histórico viva en el servidor con layout hive
  (`<root>/intraday_1m_optimized/year=Y/month=M/*.parquet`), cambia `BTT_REPLICA_SOURCE` al
  path del mirror: mismos builds, sin red (de horas → minutos). GCS queda como fuente de
  verdad/backup. Cero código.
- **Backfill 2018-2020**: al publicarlo, `BTT_REPLICA_YEARS=2018-2026` y el sync los coge.
- **El caché por-ticker viejo** sigue como fallback — no borrarlo aún (retirada = Fase 2 del PRD).
- Decisiones abiertas restantes (PRD §07): mover bucket a EU (con réplica ya no urge), NVMe
  opcional, API v2 columnar para rebajar el último coste (payload contractual de la Mitad B).

## 6. FAQ rápida

| Pregunta | Respuesta |
|---|---|
| ¿Puede el merge romper algo con flags OFF? | El diff funcional con flags OFF es 0 salvo el import del dispatcher (que con flag OFF llama a tu `portfolio_sim.simulate` de siempre) y la re-introducción de N1+N2a (§1). Golden B con flags OFF lo confirma en 15 min. |
| ¿Y si el golden falla con flags ON? | Flag OFF, captura dataset+estrategia del caso, y es un bug nuestro a arreglar — el contrato es tolerancia 0, no se relaja. |
| ¿RAM? | El slab va por mmap: RSS del proceso BAJÓ 49% en el bench. El warm usa page cache (columna *available* de `free -g`, no memoria del proceso). |
| ¿Y el optimizador? | No se tocó: usa su ruta monolítica. Hereda solo el simulador JIT vía dispatcher. |
| ¿API/frontend? | Ni una clave del response cambia. El frontend no se enteró. |
| ¿Por qué tu F2 ahora sí rinde? | En junio simulate era ~9% del tiempo (el ensamblado tapaba todo) y tu wrapper re-codificaba params por par. Con slab delante + encode barato, el mismo kernel deja simulate en ~30ms/639 días. El diagnóstico completo está en RESUMEN_EJECUTIVO §1. |
