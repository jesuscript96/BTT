# Divergencias rama Álvaro vs `staging` — 2026-08-27

> Lista para que Jaime decida qué adoptar; nada aquí está pedido para merge
> automático.

Divergencia real medida con (no de memoria):

```
git fetch origin
git log --oneline origin/staging..HEAD
git diff --stat origin/staging...HEAD
git diff origin/staging...HEAD -- backend/app/init_db.py backend/app/services/lake_db_loader.py
```

Resultado: `staging` no tiene ningún commit que le falte a esta rama (el merge
`347e127` ya lo trajo todo). En dirección contraria quedan **10 commits, pero
solo 2 ficheros de código divergen de verdad** (`init_db.py` +40,
`lake_db_loader.py` +55); el resto son docs. Los fixes de "Days por sesión" y
del glob del loader principal que nacieron aquí **ya están en `staging` con
SHA propio de Jaime** (verificado por contenido, no por mensaje).

## Resumen para triaje

| # | Qué es | Archivos / commits | ¿Específico del lago de Álvaro o agnóstico? | Recomendación | Motivo |
|---|--------|--------------------|---------------------------------------------|---------------|--------|
| 1 | Ajuste de split de `pmh_gap_pct` (recálculo en arranque + carga mensual) | `backend/app/init_db.py`, `backend/app/services/lake_db_loader.py` (`_alinear_pmh_gap_pct`) — commits `19979bc`, `6c05066` | **Específico del lago de Álvaro** | **No adoptar** | El `prev_close` del lago de Álvaro es CRUDO y se ajusta al calcular; en el lago de Sailor/Jaime YA viene ajustado desde el ETL. Aplicarlo allí DUPLICARÍA el ajuste (NVDA 2024-06-10 → 910,77 % falso, 436 candidatos fantasma). Ya auditado y rechazado por Jaime en `MEMORIA_MADRE.md` (§ "Auditoría del reporte de splits/gaps" y "Seguimiento Sailor ↔ Álvaro", 2026-08-26); esta entrada solo lo cierra formalmente |
| 2 | Glob de mes con/sin cero en la función de **caché** (`anadir_dias_al_cache`) | `backend/app/services/lake_db_loader.py` — commit `8777d17` (parte de) | **Agnóstico** | **Adoptar** (mejora de robustez pequeña) | Jaime ya arregló el mismo glob del loader principal (`cargar_meses_en_duckdb`) en `staging` (`919ea1c`, línea 161: `for pad in (f"{m:02d}", str(m))`), pero el de la función de caché quedó con el padding fijo (`month={m:02d}`) — en staging, línea ~490. Sin esto, una partición `month=8` hace que la caché se salte el mes en silencio |
| 3 | Fix de "Days por sesión" (sesiones de calendario, no ticker-días) | `backend/app/services/backtest_service.py` — commit `40920cc` | Agnóstico | **Ya convergido** | Jaime lo adoptó en `staging` como `7415eed`. No queda diff de este fix entre ramas (verificado: `git diff origin/staging...HEAD -- backend/app/services/backtest_service.py` está vacío) |
| 4 | Glob de mes con/sin cero en el **loader principal** (`cargar_meses_en_duckdb`) | `backend/app/services/lake_db_loader.py` — commit `8777d17` (parte de) | Agnóstico | **Ya convergido** | Jaime lo adoptó en `staging` como `919ea1c`. Lo que queda divergente del commit `8777d17` es SOLO el glob de la caché (ítem 2) |

Docs de referencia, sin impacto en código (aditivos, se listan aparte):

| Fichero | Contenido |
|---|---|
| `docs/PRD_FIX_SPLITS_GAPS_Y_PIPELINE_20260826.md` (+93, nuevo) | PRD del paquete 26/08 para Sailor: splits/gaps, carga incremental y Days |
| `docs/PRD_PERF_BACKTEST_STREAMBUILD_20260827.md` (+115, nuevo) | PRD de rendimiento de `stream_build` (95 % del run, medido) con propuesta de precalculados |
| `docs/MEMORIA_MADRE.md` (+142 neto) | Entradas del 26/08 (tarde), auditoría/seguimiento del 26/08 (noche) y estado de rama del 27/08 |

Nota de contexto: en el árbol de trabajo de Álvaro hay además WIP **sin
commit** (`backtest_service.py`, `indicators.py`, `strategy_engine.py`,
`subphase_profiler.py`) que NO forma parte de esta divergencia porque no está
en la rama todavía.

---

## Ítem 1 — Ajuste de split de `pmh_gap_pct` (No adoptar)

**Por qué existe:** en el lago local de Álvaro, `prev_close` llega CRUDO del
ETL y el gap se recalcula en crudo; cada reverse-split reinsertaba su gap
falso (+15.000 % / −90 %) en `daily_metrics`. El parche lee
`LOCAL_LAKE_DIR/splits/data.parquet` y ajusta `prev_close` por
`product(split_from/split_to)` solo en los días con split.

**Por qué no se porta:** el código aplica el factor SIEMPRE que exista el
Parquet de splits, sin detectar si `prev_close` ya viene ajustado de fábrica.
En el lago de Sailor/Jaime la columna ya viene ajustada del ETL → doble
ajuste. La regla queda escrita en `MEMORIA_MADRE.md` (§ "Estado actual",
2026-08-27): *los parches de datos NO son intercambiables entre lagos;
verificar en qué capa aplica el ajuste cada uno antes de adoptar nada*.

### Diff `backend/app/init_db.py` (recálculo en arranque)

```diff
--- a/backend/app/init_db.py
+++ b/backend/app/init_db.py
@@ -1,3 +1,5 @@
+import os
+
 from app.database import get_db_connection, get_user_db_connection
 
 def init_db():
@@ -335,9 +337,43 @@ def init_db():
     # The seed_mock_data.py module is kept for local manual use via `python -m app.seed_mock_data`.
 
     # Migration: Recalculate pmh_gap_pct to use the correct Premarket High vs Prev Close formula
+    # AJUSTE POR SPLIT (PRD_FIX_gaps_falsos_splits): replica la formula del ETL del
+    # lago — en dia de execution_date el prev_close se ajusta por
+    # product(split_from/split_to) del cold_storage/splits del lago local. La
+    # version cruda de antes reinsertaba el gap falso (-90% / +15.000%) de cada
+    # split en TODA la tabla en cada arranque. Paridad con
+    # lake_db_loader._alinear_pmh_gap_pct: si cambia una, cambiar la otra.
     try:
-        cur.execute("UPDATE daily_metrics SET pmh_gap_pct = ((pm_high - prev_close) / NULLIF(prev_close, 0) * 100) WHERE prev_close IS NOT NULL AND prev_close > 0")
-        print("[INFO] Successfully migrated local daily_metrics pmh_gap_pct calculation")
+        _lake = os.getenv("LOCAL_LAKE_DIR", "").strip().rstrip("/").rstrip("\\")
+        _cand = [os.path.join(_lake, "splits", "data.parquet"),
+                 os.path.join(_lake, "cold_storage", "splits", "data.parquet")] if _lake else []
+        _sp = next((p for p in _cand if os.path.exists(p)), None)
+        if _sp and os.path.exists(_sp):
+            _sp = _sp.replace("\\", "/")
+            # OJO compatibilidad: DuckDB 1.1.3 (venv del backend) no soporta
+            # "(a, b) NOT IN (SELECT x, y ...)" — anti-join con NOT EXISTS.
+            cur.execute(
+                "UPDATE daily_metrics "
+                "SET pmh_gap_pct = ((pm_high - prev_close) / NULLIF(prev_close, 0) * 100) "
+                "WHERE prev_close IS NOT NULL AND prev_close > 0 "
+                "AND NOT EXISTS (SELECT 1 FROM read_parquet('" + _sp + "') s "
+                "WHERE s.ticker = daily_metrics.ticker "
+                "AND CAST(s.execution_date AS DATE) = CAST(daily_metrics.timestamp AS DATE))"
+            )
+            cur.execute(
+                "UPDATE daily_metrics AS d SET pmh_gap_pct = "
+                "(d.pm_high - d.prev_close * sf.f) / NULLIF(d.prev_close * sf.f, 0) * 100 "
+                "FROM (SELECT ticker, CAST(execution_date AS DATE) AS ed, "
+                "      product(CAST(split_from AS DOUBLE) / CAST(split_to AS DOUBLE)) AS f "
+                f"      FROM read_parquet('{_sp}') GROUP BY 1, 2) sf "
+                "WHERE d.ticker = sf.ticker AND CAST(d.timestamp AS DATE) = sf.ed "
+                "AND d.prev_close IS NOT NULL AND d.prev_close > 0"
+            )
+            print("[INFO] Successfully migrated local daily_metrics pmh_gap_pct calculation (split-adjusted)")
+        else:
+            # Sin lago local no hay factores de split: los valores ya cargados
+            # por el ETL/loader son correctos y NO se recalculan en crudo.
+            print("[INFO] No local lake splits found: pmh_gap_pct left as loaded (split-adjusted by ETL)")
     except Exception as e:
         print(f"[WARN] Could not update local daily_metrics pmh_gap_pct: {e}")
```

### Diff `backend/app/services/lake_db_loader.py::_alinear_pmh_gap_pct` (carga mensual)

```diff
--- a/backend/app/services/lake_db_loader.py
+++ b/backend/app/services/lake_db_loader.py
@@ -227,12 +227,49 @@ def _alinear_pmh_gap_pct(con, ini: str, fin: str) -> None:
     informe. La formula se copia literal de init_db.py: si cambia alli, cambia
     aqui. Va DENTRO de la transaccion de la carga: si falla, el mes entero se
     deshace, porque media carga con el gap sin alinear es peor que ninguna.
+
+    AJUSTE POR SPLIT (PRD_FIX_gaps_falsos_splits): la formula ahora replica la
+    del ETL del lago (etl_to_edgecute.py): en el dia de execution_date el
+    cierre anterior se ajusta por product(split_from/split_to) leido del
+    Parquet de splits del lago (que lleva esas columnas). Sin esto, cada
+    reverse-split reinsertaria su gap falso del +15.000% en la tabla al cargar
+    el mes. La IPO (prev_close NULL) no se toca, igual que la formula original.
     """
+    # Factor de split del lago: <LOCAL_LAKE_DIR>/splits/data.parquet (donde lo
+    # escribe el ETL); cold_storage/splits es un junction al mismo fichero.
+    raiz = os.getenv("LOCAL_LAKE_DIR", "").strip().rstrip("/").rstrip("\\")
+    candidatos = [os.path.join(raiz, "splits", "data.parquet"),
+                  os.path.join(raiz, "cold_storage", "splits", "data.parquet")]
+    splits_parquet = next((p for p in candidatos if p and os.path.exists(p)), None)
+    if not splits_parquet:
+        raise RuntimeError(
+            "no hay splits/data.parquet en el lago local: no se puede alinear "
+            "pmh_gap_pct con el factor de split (LOCAL_LAKE_DIR mal configurado)")
+    sp = _g(splits_parquet)
+    rango = (f"timestamp >= TIMESTAMP '{ini}' AND timestamp < TIMESTAMP '{fin}' "
+             f"AND prev_close IS NOT NULL AND prev_close > 0")
+    # Dias SIN split (la inmensa mayoria): misma formula de siempre.
+    # OJO compatibilidad: el backend corre DuckDB 1.1.3, que no soporta
+    # "(a, b) NOT IN (SELECT x, y ...)" — anti-join con NOT EXISTS.
+    con.execute(
+        f"UPDATE daily_metrics "
+        f"SET pmh_gap_pct = ((pm_high - prev_close) / NULLIF(prev_close, 0) * 100) "
+        f"WHERE {rango} "
+        f"AND NOT EXISTS (SELECT 1 FROM read_parquet('{sp}') s "
+        f"WHERE s.ticker = daily_metrics.ticker "
+        f"AND CAST(s.execution_date AS DATE) = CAST(daily_metrics.timestamp AS DATE))"
+    )
+    # Dias CON split: prev_close ajustado por el factor del lago (espejo del
+    # split_fac del ETL; product() por si hay varios splits el mismo dia).
     con.execute(
-        "UPDATE daily_metrics "
-        "SET pmh_gap_pct = ((pm_high - prev_close) / NULLIF(prev_close, 0) * 100) "
-        f"WHERE timestamp >= TIMESTAMP '{ini}' AND timestamp < TIMESTAMP '{fin}' "
-        "AND prev_close IS NOT NULL AND prev_close > 0"
+        f"UPDATE daily_metrics AS d SET pmh_gap_pct = "
+        f"(d.pm_high - d.prev_close * sf.f) / NULLIF(d.prev_close * sf.f, 0) * 100 "
+        f"FROM (SELECT ticker, CAST(execution_date AS DATE) AS ed, "
+        f"      product(CAST(split_from AS DOUBLE) / CAST(split_to AS DOUBLE)) AS f "
+        f"      FROM read_parquet('{sp}') GROUP BY 1, 2) sf "
+        f"WHERE d.ticker = sf.ticker AND CAST(d.timestamp AS DATE) = sf.ed "
+        f"AND d.timestamp >= TIMESTAMP '{ini}' AND d.timestamp < TIMESTAMP '{fin}' "
+        f"AND d.prev_close IS NOT NULL AND d.prev_close > 0"
     )
```

Detalle importante del estado actual de esta rama: el commit `6c05066`
("anti-join compatible con DuckDB 1.1.3") es una corrección interna del
mismo parche (DuckDB 1.1.3 del venv del backend no soporta `(a, b) NOT IN
(SELECT x, y ...)`); no aporta nada independiente por sí solo.

---

## Ítem 2 — Glob con/sin cero en la caché (`anadir_dias_al_cache`) (Adoptable)

**Qué hace:** las particiones del lago pueden ir con o sin cero (`month=08` /
`month=8`). El loader principal ya prueba ambos paddings (en staging gracias a
`919ea1c`), pero la función de caché seguía probando solo `month={m:02d}`. Si
la partición existe solo sin cero, la caché se salta el mes **en silencio**
(mismo síntoma que el fix principal: reparador reportando "al día" con
ficheros quedados).

**Qué habría que tocar si se adopta:** únicamente
`anadir_dias_al_cache` en `backend/app/services/lake_db_loader.py`. Es
agnóstico del lago (no toca fórmulas de datos ni splits).

### Diff `backend/app/services/lake_db_loader.py::anadir_dias_al_cache`

```diff
--- a/backend/app/services/lake_db_loader.py
+++ b/backend/app/services/lake_db_loader.py
@@ -487,8 +524,14 @@ def anadir_dias_al_cache(meses, log: Log) -> dict:
         carpeta = os.path.join(G.LOCAL_CACHE_DIR, "raw", str(y), f"{m:02d}")
         if not os.path.isdir(carpeta) or not glob.glob(os.path.join(carpeta, "*.parquet")):
             continue
-        patron_lago = _g(os.path.join(cs, "intraday_1m", f"year={y}", f"month={m:02d}", "*.parquet"))
-        if not glob.glob(patron_lago):
+        # Las particiones del lago van SIN cero (month=8); se prueban ambos.
+        patron_lago = None
+        for pad in (f"{m:02d}", str(m)):
+            p = _g(os.path.join(cs, "intraday_1m", f"year={y}", f"month={pad}", "*.parquet"))
+            if glob.glob(p):
+                patron_lago = p
+                break
+        if not patron_lago:
             continue
 
         try:
```

Es el espejo exacto de lo que Jaime ya hizo en `cargar_meses_en_duckdb`
(staging, `919ea1c`), aplicado a la otra función que lee el mismo lago.

---

## Ítems 3 y 4 — Ya convergidos (sin acción)

- **Days por sesión** (`40920cc` aquí): `staging` lo tiene como `7415eed`
  ("fix(metricas,optimizacion): Days por sesion + panel de optimizacion en
  hora; auditoria de splits"). Diff restante entre ramas en
  `backtest_service.py`: ninguno.
- **Glob del loader principal** (`8777d17`, parte loader): `staging` lo tiene
  como `919ea1c` ("fix(lago,ui): un mes que falta deja de saltarse en
  silencio + aviso de completitud visible") — verificado por contenido:
  `git show origin/staging:backend/app/services/lake_db_loader.py` línea 161
  contiene el `for pad in (f"{m:02d}", str(m))`.

---

## Apéndice — Cómo se verificó

```
git fetch origin
git log --oneline origin/staging..HEAD      # 10 commits propios, staging ⊂ HEAD
git log --oneline HEAD..origin/staging      # (vacío): nada de staging sin traer
git diff --stat origin/staging...HEAD       # solo init_db.py, lake_db_loader.py y 3 docs
git branch -r --contains <sha>              # SHA-confinement de 19979bc/40920cc/8777d17
git log origin/staging -S 'for pad in ...'  # atribución del glob dual a 919ea1c
```

Fecha: 2026-08-27 · Rama: `alvaro-rama-desarrollo` ·HEAD en el momento del
análisis: `296f9f0` · `origin/staging` en `919ea1c`.
