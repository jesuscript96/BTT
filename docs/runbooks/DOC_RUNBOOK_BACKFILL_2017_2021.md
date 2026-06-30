# RUNBOOK — Backfill histórico intraday 2017-2021 (chunked por año)

> Volcado de intraday 1m + daily_metrics a GCS para el rango 2017-01-01 → 2021-12-31,
> año por año con verificación de integridad entre cada uno. Script: `catchup_gcs.py`
> (ya con el fix de robustez 429, deploy main `97478fc`). **Plan revisado y aprobado.**

## Decisiones aprobadas
- **Alcance: solo candidatos gap** (gap≥5% o pmh-est≥10%) — mismo filtro que 2022-2026, consistencia total.
- **Solape con lead-in** (FROM = mediados de dic del año previo) para evitar seed vacío; se acepta perder solo **2017-01-03** (sin dato previo).
- **Año a año con verificación** entre cada chunk.
- **Correr en el contenedor de prod** con monitoreo de RAM activo.

---

## Hechos verificados (solo lectura)
| Aspecto | Hallazgo |
|---|---|
| `get_trading_days(start,end)` | **start EXCLUSIVO** (`current = start+1día`), solo filtra Lun-Vie (sin calendario de festivos; los festivos dan grouped vacío → skip) |
| `_seed_prev_closes(FROM)` | lee closes **exactamente en la fecha FROM** desde GCS daily_metrics → FROM debe ser día hábil con datos o el seed sale vacío |
| `new_prev_closes` | se llena de **TODOS** los tickers del grouped_daily (línea 572, antes del filtro) → día 2+ del chunk tiene universo completo; **solo el día 1 depende del seed** |
| Escrituras GCS | **idempotentes**: daily_metrics lee-mergea-dedupe `(ticker,timestamp) keep=last`; intraday sobrescribe por día → **re-correr un año NO duplica** |
| RAM | host ~19.8 GB disponibles; el script **NO importa módulos de app → NO carga el RAM cache** (footprint modesto, flush por día/mes) |
| Checkpoint | `/app/scripts/catchup_checkpoint.json`; `get_last_gcs_date()=max(GCS,checkpoint)` → tras backfill el cron resume bien de 2026 (GCS gana) |
| Cron real | `0 6 * * 2-6 docker exec $(docker ps -q -f name=ur7zf7) sh -c '...' >> /var/log/catchup_gcs.log` |
| TZ | `_to_ny_naive` con guard que **aborta el batch** si las horas caen fuera de 4-20 ET → datos escritos garantizan NY correcto |
| **Hot cache** | **regen AUTOMÁTICO** al final de cada `catchup_gcs.py` (línea 633-635 → `generate_hot_cache_parquet.py`); lee TODO el histórico sin filtro de fecha; sube a GCS vía `GCS_KEY_B64` (verificado SET). **App tiene el hot cache en memoria → requiere RESTART para recargarlo.** |
| WORKDIR | `/app` (default del docker exec) → el `os.system('scripts/...')` del regen resuelve correcto |

---

## Chunks definitivos

| Año | `INTRADAY_BACKFILL_FROM` | `INTRADAY_BACKFILL_TO` | Nota |
|---|---|---|---|
| 2017 | `2016-12-30` | `2017-12-31` | sin pre-2017 → **2017-01-03 sub-detectado** (1 día, inevitable) |
| 2018 | `2017-12-15` | `2018-12-31` | solape ~10 días de dic-2017 (idempotente) → ene-2018 completo |
| 2019 | `2018-12-15` | `2019-12-31` | |
| 2020 | `2019-12-15` | `2020-12-31` | |
| 2021 | `2020-12-15` | `2021-12-31` | |

El solape garantiza `prev_closes` completo (todo el mercado) antes del 1 de enero del año objetivo.

---

## PASO 0 — Backups de seguridad
```bash
CID=$(ssh root@178.156.221.50 'docker ps --format "{{.Names}}" | grep "^ur7zf7"')
ssh root@178.156.221.50 'crontab -l > /tmp/crontab_backup_historico.txt && wc -l /tmp/crontab_backup_historico.txt'
ssh root@178.156.221.50 "docker exec $CID cp /app/scripts/catchup_checkpoint.json /tmp/checkpoint_backup.json 2>/dev/null; echo ok"
```

## PASO 1 — Pausar el cron normal
```bash
ssh root@178.156.221.50 'crontab -l | grep -v catchup_gcs | crontab - && crontab -l | grep -c catchup_gcs'
# debe imprimir 0
```

## PASO 2 — Loop por año (uno a la vez, detached, cwd=/app)
Para cada `(YEAR, FROM, TO)` de la tabla:
```bash
ssh root@178.156.221.50 "docker exec -d $CID sh -c '
  cd /app
  set -a
  eval \$(cat /proc/1/environ | tr \"\\0\" \"\\n\" | grep -E \"^(LD_LIBRARY_PATH|PATH|VIRTUAL_ENV)=\" | sed \"s/=/=\\\"/;s/\$/\\\"/\")
  set +a
  export INTRADAY_BACKFILL_FROM=<FROM> INTRADAY_BACKFILL_TO=<TO> MASSIVE_THROTTLE_ENABLED=false
  /opt/venv/bin/python /app/scripts/catchup_gcs.py > /tmp/backfill_<YEAR>.log 2>&1
'"
```
> `cd /app` es importante: el regen del hot cache al final usa `os.system('scripts/...')` (ruta relativa).

**Monitoreo en vivo** (cada pocos min):
```bash
ssh root@178.156.221.50 "docker exec $CID sh -c '
  echo PROGRESO:; grep -E \"\[[0-9]+/[0-9]+\] Processing\" /tmp/backfill_<YEAR>.log | tail -1
  echo ERRORES:;  grep -c \"\[ERROR\]\" /tmp/backfill_<YEAR>.log
  echo 429:;      grep -c \"\[429\]\"   /tmp/backfill_<YEAR>.log
  echo FLUSHES:;  grep -c \"Flushing\"  /tmp/backfill_<YEAR>.log
'"
ssh root@178.156.221.50 'free -m | sed -n 2p'   # avail no debe bajar de ~4GB
```

**Criterios de aborto limpio** (matar PID del python; re-correr el MISMO año es idempotente):
- `[ERROR]` creciendo sin parar (no aislado) → algo sistemático.
- RAM avail < 4 GB → riesgo OOM.
- `[429]` persistentes que no se resuelven.

## PASO 3 — Verificación de integridad por año (antes del siguiente)
Vía duckdb httpfs+HMAC (mismas creds GCS). Sustituir `<bucket>`/`<YEAR>`:
```sql
-- 3a. Días + candidatos del año
SELECT count(DISTINCT CAST(timestamp AS DATE)) dias, count(*) filas
FROM read_parquet('gs://<bucket>/cold_storage/daily_metrics/year=<YEAR>/*/*.parquet', hive_partitioning=true);

-- 3b. Distribución de gaps (sanity TZ — comparar ratio con 2022-2026 conocido-bueno;
--     NO debe estar invertida ni absurdamente sesgada)
SELECT CASE WHEN gap_pct>0 THEN 'up' ELSE 'down' END dir, count(*), round(avg(gap_pct),2) avg_gap
FROM read_parquet('gs://<bucket>/cold_storage/daily_metrics/year=<YEAR>/*/*.parquet', hive_partitioning=true)
GROUP BY 1;

-- 3c. Horas de barras 1m (TZ correcta 4-19 NY) en un día muestra
SELECT min(hour(timestamp)) h_min, max(hour(timestamp)) h_max, count(*) barras
FROM read_parquet('gs://<bucket>/cold_storage/intraday_1m/year=<YEAR>/month=06/*.parquet', hive_partitioning=true)
WHERE CAST(timestamp AS DATE) = DATE '<YEAR>-06-15';   -- h_min>=4, h_max<=19
```
**Solo si el año sale limpio → siguiente año.**

## PASO 4 — Finalización (tras los 5 años)
1. **Hot cache: YA regenerado automáticamente** al final de cada run (el de 2021 deja el parquet completo en GCS). **Verificar** que se subió:
   ```bash
   ssh root@178.156.221.50 "docker exec $CID sh -c 'grep -E \"Regenerating hot cache|Subido a gs\" /tmp/backfill_2021.log'"
   ```
   (Opcional manual si fallara: `cd /app && /opt/venv/bin/python scripts/generate_hot_cache_parquet.py`)
2. **Reiniciar el contenedor** para que la app recargue el hot cache nuevo (tiene el viejo en memoria):
   ```bash
   # vía Coolify (restart del servicio) o docker restart $CID
   ```
   Verificar en logs de arranque: `[HOT CACHE] loaded from GCS Parquet: <N> rows` con N mayor (incluye 2017-2021).
3. **Restaurar cron:**
   ```bash
   ssh root@178.156.221.50 'crontab /tmp/crontab_backup_historico.txt && crontab -l | grep -c catchup_gcs'  # debe ser 1
   ```
4. **Recalcular RAM cache:** el universo de gaps creció ~5 años → backtests sobre 2017-2021 cargarán más intraday al RAM cache (`INTRADAY_RAM_CACHE_ENABLED=true`). Tras el primer backtest sobre el rango nuevo, medir el pico de RAM y ajustar `DUCKDB_MEMORY_LIMIT` / eviction si hace falta.

---

## Abort / Resume
- Las escrituras son **idempotentes** → abortar a mitad de un año y re-lanzar el MISMO chunk (mismo FROM/TO) re-procesa desde FROM sobrescribiendo/mergeando. Sin duplicados.
- `INTRADAY_BACKFILL_FROM` overridea el checkpoint para el inicio → control explícito en re-runs.

## Riesgos residuales
- **Hot cache regen corre 5 veces** (una por año, escaneo full-history cada vez) — overhead menor; el de 2021 es el autoritativo.
- **Correr en prod**: comparte RAM con la app (~19.8 GB libres) → seguro con monitoreo.
- **2017-01-03**: único día con candidatos sub-detectados (sin dato previo). Aceptado.
