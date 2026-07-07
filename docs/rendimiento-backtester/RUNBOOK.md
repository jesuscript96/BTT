# RUNBOOK — Activación del Motor V2 en producción

> Para: Jesús + Adrián (CTO). Todo lo nuevo está **detrás de flags con default OFF**:
> desplegar este código SIN tocar envs = comportamiento idéntico al actual.
> Rollback de cualquier fase = poner su flag a 0/false y reiniciar. Sin migraciones.

## 0. Pre-requisito único: Golden B en el servidor (gate de Adrián)

Antes de activar NINGÚN flag, en el contenedor de prod:

```bash
# 1) con los flags OFF (estado actual), capturar/verificar goldens:
/opt/venv/bin/python tests/test_backtest_golden.py     # → MATCHED en todos los casos
# 2) activar los flags de la fase que toque (abajo), reiniciar, y re-ejecutar:
/opt/venv/bin/python tests/test_backtest_golden.py     # → debe seguir MATCHED (tol 0)
```

Si algún caso no hace MATCH: flag a OFF, reportar, no seguir.

## 1. Orden de activación (una fase cada 1-2 días, con Golden B entre medias)

### Fase 1 — Réplica local de slabs (construye datos, no cambia el backtest)
```
BTT_REPLICA_SYNC_ENABLED=true
BTT_REPLICA_SOURCE=gcs              # ← cambiar al path local cuando el CTO migre los datos
BTT_REPLICA_YEARS=2021-2026
BTT_SLAB_DIR=/data/btt/slabs        # volumen PERSISTENTE (no /tmp — sobrevive deploys)
BTT_SLAB_PAGECACHE_WARM=true
```
- La primera construcción baja ~30-60 GB desde GCS US: **lanzarla de noche**. Progreso en
  logs `[REPLICA]`/`[SLAB]`. Idempotente: si se corta, la siguiente pasada continúa.
- Verificar: `find $BTT_SLAB_DIR -name manifest.json | wc -l` ≈ nº de meses (2021-2026 ≈ 66).
- **Migración de datos (CTO):** cuando el histórico viva en el hardware propio con el
  layout hive (`<root>/intraday_1m_optimized/year=Y/month=M/*.parquet`), basta
  `BTT_REPLICA_SOURCE=/data/mirror` — mismo código, builds locales (minutos, no horas).

### Fase 2 — Stream slab en el backtester (la palanca grande)
```
BTT_SLAB_STREAM_ENABLED=true
```
- Los meses sin slab caen solos al path legacy (primeros días de mes nuevo, etc.).
- Verificar: logs `[TIMING] phase=signals ... mode=slab` + tiempos de backtest.
- Rollback: `BTT_SLAB_STREAM_ENABLED=false`.

### Fase 3 — Kernel Numba del simulador
```
BACKTEST_NUMBA_SIM=1
```
- El warmup compila en el arranque (~4 s la primera vez; después usa caché en disco).
- Verificar: log `[JIT] simulate kernel warm en X.Xs` + Golden B.

### Fase 3b — Fast-path nativo de señales (N2a)
```
BTT_N2A_NATIVE_ENABLED=1
```
- Requiere el fix de paridad `fix/n2a-parity` (2026-07-06): gate por-estrategia
  (lo no soportado cae SOLO al motor clásico — nunca 0-trades silencioso),
  resample tf→1m por reloj + closed-bar, herencia de timeframe, ventanas
  horarias, CROSSES, PM causal, ATR-stop y partial TPs nativos.
- Solo acelera los paths paralelo/slab (`_compute_signals_for_pair`); el loop
  secuencial sigue usando el motor clásico siempre.
- Verificar: Golden B MATCHED con el flag ON (workers 1 y N) + suites
  `tests/test_n2a_native_equivalence.py` y `tests/test_n2a_e2e_equivalence.py`.
- Rollback: `BTT_N2A_NATIVE_ENABLED=0`.

### Fase 4 — Tuning de la caja real (W-2145, 128 GB)
```
DUCKDB_MEMORY_LIMIT=16GB            # hoy 4-8GB; la caja tiene 128GB
BACKTEST_PARALLEL_WORKERS=1         # ¡SÍ, 1! — ver nota
```
- **Nota workers:** con slab+JIT, las señales cuestan ~55 µs/par: el pool forkserver solo
  compensa en estrategias multi-timeframe pesadas o universos gigantes (medido: a 1.200
  pares el spawn cuesta más que el trabajo). Dejar 1 salvo evidencia en logs de que
  `phase=signals` domina; entonces probar 4-6.

## 2. Medición del antes/después real (para el informe de prod)

Con EPIC A desplegado, cada backtest emite líneas greppables:
```bash
grep "\[TIMING\] phase=" <logs> | tail -50
# phase=qualifying|stream_build|signals|simulate|aggregate|serialize|total  ms=... pairs=...
```
Capturar 2 datasets representativos (gap chico + mediano) antes de Fase 2, tras Fase 2 y
tras Fase 3 → tabla antes/después en INFORME_FINAL.md §prod.

## 3. Verificación de entorno (una vez, dentro del contenedor)

```bash
nproc; free -g; lsblk -d -o NAME,ROTA,SIZE       # esperado: 16 hilos, ~125Gi, ROTA=1 (HDD)
cat /sys/fs/cgroup/memory.max                     # límite del contenedor (¿o max?)
df -h /data                                       # espacio para slabs (~60-100 GB libres)
env | grep -E 'BACKTEST|INTRADAY|DUCKDB|CACHE|BTT'
```

## 4. Mantenimiento

- El sync corre cada `BTT_REPLICA_SYNC_INTERVAL_H` (24h) y reconstruye siempre el mes
  corriente. Cuando aterrice el backfill 2018-2020: ampliar `BTT_REPLICA_YEARS=2018-2026`.
- El caché por-ticker antiguo queda como fallback; NO borrarlo aún (Fase 2 del PRD).
- Espacio slabs: ~0,5-1 GB/mes (float32) → 2021-2026 ≈ 40-70 GB. Sin cuota propia: vigilar `df`.

## 5. Qué hacer si algo va mal

| Síntoma | Acción |
|---|---|
| Resultados distintos en cualquier backtest | flags OFF (Fase 2 y 3), capturar dataset+estrategia, abrir issue con el par exacto |
| RAM alta tras Fase 1 | el warm usa page cache (no RSS del proceso) — `free -g` col "available" es lo que cuenta; si el RSS del proceso sube, revisar `[SLAB]` logs |
| Primer backtest lento tras deploy | warmup JIT/replica en curso — ver logs `[JIT]`/`[REPLICA]` |
| Mes recién cerrado va lento | aún sin slab → fallback legacy; el sync nocturno lo construye |
