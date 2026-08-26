# PRD — Fix de gaps falsos por split + pipeline diario incremental (2026-08-26)

**Para:** Sailor (y quien sincronice staging). **De:** Álvaro (con GLM).
**Ámbito:** lago `cangrejo_data` + backend BTT. **Commits en `alvaro-rama-desarrollo`:**
`19979bc`, `6c05066`, `40920cc`. El lado del lago (`cangrejo_data/scripts/`) no es repo.

---

## 1. Qué estaba roto

El universo del backtester calculaba el gap diario contra el `prev_close` **crudo**:
cada split/reverse-split entraba como gap gigante **falso** (NVDA 2024-06-10 con
split 1→10 = gap -89,89 %). Medido sobre el bygap real: **2.123 ticker-días**
`pmh_gap>=50` caían en día de split (el 9,4 % del universo short), gap falso medio
+2.752 %, máximo +154.722 %. Un backtest short de gaps disparaba contra acciones
que **no habían gappeado**.

## 2. El fix (lado lago, `cangrejo_data`)

Los 3 gaps (`gap_pct`, `gap_at_open_pct`, `pmh_gap_pct`) dividen por
`close_prev_adj = prev_close * product(split_from/split_to)` del día (en IPO,
primer trade), espejo de `sql/metricas_diarias.sql`. Regenerado `daily_metrics`
+ bygap y verificado: NVDA → **+1,08 %**, FFAI (reverse 150→1) → **+0,79 %**,
universo `pmh>=50` **22.676 → 20.997**, ticker-días sin split idénticos al 6º
decimal. Solo `pmh_gap`/`gap`/`gap_at_open` cambian; ninguna otra derivada usa
`prev_close` (verificado columna a columna). El intradía sigue CRUDO por diseño.

**Impacto al comparar curvas viejas/nuevas:** desaparecen los candidatos
fantasma (con `pmh>=20`, `close>=$1`: 361 pares en 2025, 1.824 en todo el
histórico). Los trades que "faltan" eran ficticios.

Además en el lago: `regenerar_bygap.py` re-ventanea el universo (34 s, misma
SQL stage-2 del backend, staging→verificar→swap) y queda integrado como **paso
final del diario**; `reparar_lago.py` y el bygap llevan guarda de disco; y
existen los junctions `cold_storage/splits` y `cold_storage/tickers`, que el
loader de referencias del backend necesita (antes no existían y el reload de
splits/tickers se saltaba **siempre** en silencio).

## 3. El fix (lado backend, estos commits)

- **`19979bc`** — `lake_db_loader._alinear_pmh_gap_pct` y la migración de
  arranque de `init_db.py` recalculaban `pmh_gap_pct` con la fórmula **cruda**
  (la de arranque sobre TODA la tabla, en cada boot): re-corrompían el fix en
  cuanto cargaba un mes o se reiniciaba. Ahora usan el ajuste por split (factor
  desde el parquet de splits del lago) y, sin lago local, no recalculan.
  Además la tabla `splits` pasa a 4 columnas (`split_from`, `split_to`):
  arranca sin el `[WARN] Failed to load splits cache ... split_from not found`
  y el filtro anti-reverse-split de Market Analysis vuelve a funcionar.
  **Ojo:** esto exige regenerar la tabla (`FASE=3` de `reparar_lago.py` o
  `--full --load`); con la tabla vieja a 2 columnas el recambio falla (capturado,
  no tumba la carga).
- **`6c05066`** — el anti-join va con `NOT EXISTS`: el venv del backend lleva
  **DuckDB 1.1.3**, que no soporta `(a,b) NOT IN (SELECT x,y ...)`. Cualquier
  SQL nueva para el backend debe contar con eso.
- **`40920cc`** — **"Days" de Aggregate Results cuenta sesiones de calendario**,
  no ticker-días (antes una sesión con 6 candidatos sumaba 6: un año mostraba
  "1460 días"). Efecto intencionado: `Avg Ret/Day` y `Avg R/Day` pasan a ser
  **por sesión**. **Cambios de semántica a coordinar:** esas 3 métricas no son
  comparables con resultados anteriores.

## 4. Pipeline diario: carga incremental del DuckDB

`etl_to_edgecute.py --incremental --load` ya no reescribe los ~3.000 M de filas
de `local_data.duckdb`: carga SOLO los meses tocados (DELETE por rango +
INSERT del parquet, transaccional, espejo de `cargar_meses_en_duckdb`). Medido:
paso ETL **30-40 min → 2,2 min**; run manual completo 8/8 pasos en 18,2 min.
La recarga completa queda como reparación (`--full --load` / `FASE=3`).

## 5. Completitud de datos (lo que ya estaba, confirmado vivo)

El guardian (`bb95b61`): cada run reporta `[COMPLETENESS] N/M ticker-días
ejecutados` y con `BACKTEST_STRICT_COMPLETENESS=true` el resultado incompleto
se rechaza con 503. Hoy corre al 100 % (8.219/8.219) bajo modo estricto. La
resolución de intradía sigue prefiriendo `intraday_1m_optimized` > raw con la
guarda anti-copia-obsoleta; en local no hay copia optimizada y cae al raw del
lager, siempre fresco. Recomendado: `BACKTEST_STRICT_COMPLETENESS=true` en
cada `.env`.

## 6. Verificación rápida (5 minutos)

1. `SELECT round(pmh_gap_pct,2) FROM daily_metrics WHERE ticker='NVDA' AND
   CAST(timestamp AS DATE)=DATE '2024-06-10'` → **1.08** (no -89.89).
2. `DESCRIBE splits` → 4 columnas; arranque del backend sin WARN de splits
   (log: `[CACHE] splits loaded: 27151 rows`).
3. Un backtest cualquiera: en el log `[COMPLETENESS] 100%`; en la UI, "Days"
   ≈ sesiones de la ventana (no miles).
4. Diario: paso `etl_edgecute` en ~2 min y paso `bygap` al final (~35 s).

## 7. Qué NO cambia

El intradía crudo (sizing/fees/locates por acción), el motor de simulación
(solo se tocó la métrica Days), el screener más allá del gap corregido, y los
esquemas de `daily_metrics`/`intraday_1m` (38/8 columnas exactas, como siempre).
