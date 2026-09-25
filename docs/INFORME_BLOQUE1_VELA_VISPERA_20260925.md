# Informe — Bloque 1 · La vela de la víspera (filtros de universo con umbral movible)

> **Fecha:** 2026-09-25 · **Pide:** Álvaro · **Ejecuta:** GLM (ZCode) · **Rama:** `alvaro-rama-desarrollo`
> **Hoja de ruta:** `docs/INVESTIGACION_CRITERIOS_UNIVERSO.md` (Bloque 1)
> **Datos:** `daily_metrics` de `backend/local_data.duckdb`, 2019-01-02 → 2026-09-04, extraída en
> una pasada read-only (ciclo taskkill+watchdog autorizado por Álvaro, §7). Trades: corridas B0
> del estudio 1B ya existentes (2024 `f574e70b` · 2025 `d4409208` · 2026 `73a6e649`), **sin
> backtests nuevos**.
> **Resultado principal (vista A):** `pmh_fade_pct` = cuánto cae del máximo del premarket a la
> apertura (lo que explota un short de fade). Secundario: `day_return_pct` (open→close RTH).
> **Vista B:** `return_pct` por trade de la 1B.

---

## 0. Tabla-resumen

| # | Criterio (víspera) | Veredicto | Dirección (lo que significaría el filtro) | ¿Filtrable hoy en la app (Gap −1)? |
|---|---|---|---|---|
| 1.1 | Posición del cierre en su rango | **DUDOSO** | Cierre cerca del mínimo → algo más de fade y mejor short; señal débil y redundante con 1.6 (ρ 0,71) | No — habría que añadir columna derivada (los lag existentes no incluyen rth_high/rth_low como fuentes UI) |
| 1.2 | Fade de la víspera (`rth_fade_pct`) | **SIRVE** | Víspera que se desinfla (cierra lejos de su máximo) → el gap del día siguiente cae más premarket y el short rinde más (D1 5,3 % vs D10 2,6 % en trades) | No — añadir `rth_fade_pct` a `PREV_DAY_LAG_SOURCES` |
| 1.3 | Hora del máximo (`hod_time`) | **NO SIRVE** | Nada sobre el fade premarket (tramos planos 27,4–28,6). Sólo asoma en day_ret (HOD tarde → día RTH más rojo, 6/8 años) que no es lo que cobra la 1B | No — además necesitaría tramos (columna derivada de un string) |
| 1.4 | PMH Gap de la víspera | **NO SIRVE** | Sin gradiente: <10/10-30/30-50 iguales; sólo un escalón aislado en ≥50 (−2 pp de fade) que B no replica. 21 % de vísperas sin dato | **Sí** (`lag_pmh_gap_pct_1` ya existe) — pero no vale la pena |
| 1.5 | Rango RTH (÷open) | **DUDOSO** (fuerte para day_ret, nulo para fade) | Rango alto → día RTH posterior más rojo (8/8 años, el ρ más alto de todos: −0,045…−0,153) pero NO mueve el fade premarket y en B es débil. Añade ~1,2 pp sobre el neto en el cruce 2×2 | **Sí** (`lag_rth_range_pct_1` existe; ojo: esa columna es ÷low — para deciles da igual, ρ 0,998) |
| 1.6 | Neto RTH (`(close−open)/open`) | **SIRVE — el mejor** | Víspera roja → el gap se desinfla ANTES de la apertura: +2 a 4 pp de fade y el short pasa de ~1-3 % a 4-8 % de retorno; víspera muy verde (>+10) es el grupo peor… salvo en 2026, que rindió (inversión F2 ya conocida) → usar como keep-roja, no como excluir-verde | No — la columna base (`day_return_pct`) existe; falta añadirla a `PREV_DAY_LAG_SOURCES` |

Tres conclusiones:

1. **El único criterio que pasa todo es 1.6 (neto de la víspera)**: misma dirección en 7/8 años
   sobre el fade y en 3/3 años sobre trades reales (extremos por decil: D1 7,6 % vs D10 1,1 %
   pooled), aguanta ticker-día, sin-2020, sin huecos largos y el gradiente con umbral absoluto
   (≤−10 / −10..0 / 0..+10 / >+10) va en la misma dirección en los DOS periodos. 1.2 (fade) es
   la misma señal en otra métrica (8/8 años en day_ret) y también sirve.
2. **La víspera roja es un filtro de FADE PREMARKET, no de "día rojo"**: sube el
   `pmh_fade_pct` y el retorno del short que sale antes de las 08:45, pero el día RTH es
   MENOS rojo (el daño ya ocurrió antes de abrir). Un hipotético short de sesión querría al
   revés la víspera verde.
3. **Nada de esto es operable aún**: son 6 criterios × deciles × 8 años de comparaciones
   (múltiple testing alto); lo que salva a 1.6/1.2 es que acumulan dirección + monotonicidad +
   las dos vistas + las robustez. Siguiente paso de la hoja de ruta (punto 5): probarlos en
   2-3 estrategias distintas con el motor antes de construirlos como filtro en la app.

---

## 1. Método

- **Criterios** (todos de la sesión RTH de la víspera, fila previa del ticker en
  `daily_metrics`): 1.1 `(close−low)/(high−low)` · 1.2 `rth_fade_pct` (columna) · 1.3
  `hod_time` (tramos de 60 min 09:30→16:00) · 1.4 `pmh_gap_pct` víspera (tramos <10 / 10-30 /
  30-50 / ≥50 / sin dato) · 1.5 `(high−low)/open` · 1.6 `day_return_pct` (≡ neto, fórmula
  verificada al 100 % en `INFORME_RANGO_PREV_RTH_20260925.md` §4-D).
- **Vista A (universo, sin estrategia):** todos los días gap del universo base 1B
  (PMH Gap ≥ 50 + filtros EXACTOS de la materialización de pares de dataset: tipo
  CS/ADRC/OS vía `tickers`, sin split ese día vía `splits`, y `_filtrar_universo`:
  mapa de tipos CS/ADRC + suelo de precio 0,10 $ sobre `open`). 2019-2026.
  **2019-2022 búsqueda, 2023-2026 confirmación, fijado antes de mirar.**
- **Vista B (trades reales):** B0 de la 1B (2024/2025/2026) con `return_pct` por trade.
- **Deciles** calculados sobre la muestra A completa 2019-2026 (bordes absolutos fijos →
  eso es lo que necesitaría un filtro de umbral movible). Por año: Spearman fila a fila +
  extremos de decil; por periodo: Spearman agregado.
- **Veredicto (reglas declaradas antes de mirar):** SIRVE = mismo signo en ≥6/8 años (A)
  o ≥2/3 años (B), los dos periodos de A con el mismo signo, magnitud no nula
  (|ρ periodo| ≥ 0,02) y curva pooled sin depender de un solo tramo. DUDOSO = dirección
  consistente pero débil/redundante, o sólo funciona en el resultado secundario. NO SIRVE
  = dirección inestable o sin gradiente.

## 2. Datos y auditoría

- **Extracción** (una pasada read-only, autorizada): `universo.parquet` (14.525 filas
  PMH ≥ 50 con filtros de dataset, 2019-2026), `hist_universo.parquet` (3.609.816 filas =
  historial completo de los 3.541 tickers del universo — deja servidos los Bloques 2-4:
  volumen relativo, retornos acumulados, medias/máximos están derivables de aquí),
  `ref_tipos.parquet`, `ref_splits.parquet`, `fidelidad.csv`.
- **Después de `_filtrar_universo`:** 14.144 días gap (539/1.716/1.127/1.158/1.987/2.580/
  2.983/2.054 por año). Sin fila de víspera: 161 (1,1 %, excluidos). Hueco >7 días
  naturales: 63 (marcados; sensibilidad sin ellos no cambia nada).
- **Fidelidad vs pair_count de datasets existentes:** 2022: 1.158 vs 1.157 (dataset
  `5ee3cf8c`) ✓ · 2025: 2.983 vs 3.103 (`c8bcddc7`, construido 31-ago) ✓ −3,9 % · 2026
  (a 4-sep): 2.054 vs 2.072 (`180d7b20`) ✓ −0,9 % · **2024: 2.580 vs 4.200
  (`d088a358`, construido 16-ago): hoy la MISMA regla sin filtros da 3.821 filas** → el
  dataset anuncia un 10 % más de lo que la regla encuentra hoy en la BD (el lago cambió
  desde su construcción; nota en MEMORIA_MADRE).
- **Trades B:** 4.482 (1.392/1.831/1.259), 34 sin víspera (0,8 %), 4.448 válidos.
  Reentradas: 4.482 trades → 3.466 ticker-día (robustez §4.1).
- **Contexto de niveles** (para leer las tablas): el `pmh_fade_pct` medio del universo sube
  de régimen entre periodos: 2019-22 ≈ 23 % · 2023-26 ≈ 30 %. Las comparaciones son siempre
  DENTRO de periodo/año.

## 3. Resultado por criterio (tablas clave)

Deciles pooled 2019-2026 (bordes sobre A completa; medias, no medianas — en
`resultados_stats.txt` están completas). Año a año: nº de años con signo del Spearman
coincidente + ρ por periodo.

### 1.6 Neto de la víspera — SIRVE (el mejor)

| Decil neto víspera | D1 (≤−12,5) | D5 | D10 (≥+16,7) |
|---|---|---|---|
| A · pmh_fade (%) | **29,68** | 27,47 | **25,84** |
| B · retorno trade (%) | **7,62** | 3,54 | **1,13** |

- A·pmh_fade: ρ<0 en **7/8 años** (sólo 2023 ≈ 0, +0,003); periodos −0,025 / −0,037.
- A·day_ret: 7/8; periodos −0,070 / −0,012.
- B: ρ<0 en **3/3 años** (−0,041/−0,088/−0,035); extremos por año D1 vs D10:
  2024: 5,7 vs −0,1 · 2025: 8,6 vs 0,9 · 2026: 8,2 vs 4,1. Ticker-día pooled −0,065.
- **Umbral movible (tramos absolutos):** fade por tramo — 2019-22: 24,6 → 23,0 → 23,2 →
  22,7 · 2023-26: 30,9 → 30,2 → 29,7 → 29,3. Gradiente en ambos periodos, sin corte crítico.
- **Matiz importante:** en day_ret la víspera roja va con día RTH MENOS rojo (2019-22:
  −1,1 % vs −6,0 %) — el fade se come premarket. Es filtro de fade premarket, no de día rojo.
- **Ojo con excluir la víspera muy verde:** en B, el tramo >+10 de 2026 rindió 6,03 %
  (la inversión F2 del informe anterior, reproducida aquí). La forma segura del filtro es
  **keep víspera roja** (neto ≤ 0: media 4,4-7,9 %), no "excluir >+10".

### 1.2 Fade de la víspera — SIRVE (misma señal, otra métrica; ρ 0,41 con 1.6)

| Decil fade víspera (D1 = más fade, cierre débil) | D1 | D10 (cierre en máximos) |
|---|---|---|
| A · day_ret (%) | **−3,85** | **−1,38** |
| B · retorno trade (%) | **5,31** | **2,62** |

- A·day_ret: ρ>0 en **8/8 años**; periodos +0,043 / +0,052 (p<0,05 en 5/8 años).
- A·pmh_fade: sólo dudoso (5/8; los extremos van bien: D1 28,9 vs D8-D9 26,4-26,7, D10 sube).
- B: ρ<0 en **3/3 años** (−0,024/−0,056/−0,026); ticker-día −0,043.

### 1.5 Rango de la víspera — DUDOSO (fuerte para day_ret, nulo para el fade)

| Decil rango víspera | D1 (≤4,7 %) | D10 (≥45,6 %) |
|---|---|---|
| A · day_ret (%) | −0,61 | **−3,89** |
| A · pmh_fade (%) | 26,9 | 26,2 (pico en D8: 29,7) |

- A·day_ret: ρ<0 en **8/8 años**, los ρ más altos del bloque (−0,045…−0,153; p<0,05 en
  7/8); periodos −0,108 / −0,073; sin 2020 sigue 7/7. Rango alto víspera → día RTH más rojo.
- A·pmh_fade: nada (5/3, curva no monótona). B: 3/3 positivo pero diminuto
  (+0,021/+0,013/+0,063; sólo 2026 significativo).
- **Cruce rango × neto (A, ambos periodos):** la mejor celda de fade es rango alto × víspera
  roja (24,2/31,0) — el rango añade ~1,2 pp sobre el neto solo, consistente en los dos
  periodos (replica el 2×2 del informe de rango/neto de esta mañana, ahora a nivel universo
  y 2019-2026). Como filtro de universo para la 1B no justifica sola; como refinamiento
  sobre 1.6, quizá.

### 1.1 Posición del cierre — DUDOSO (redundante con 1.6; ρ 0,71)

- A·pmh_fade: 6/8 años, periodos −0,015/−0,028, pero curva pequeña y D10 rebota
  (D1 29,1 → D9 26,8, D10 28,0). B: 2/3 (−0,014/−0,070/+0,003). Todo apunta a lo mismo que
  1.6 con menos señal: si se implementa uno, que sea el neto.

### 1.3 Hora del máximo — NO SIRVE (para fade)

- A·pmh_fade: tramos planos (27,4-28,6 %), 5/8 años con ρ~0, periodos −0,005/−0,006. Nada.
- A·day_ret: 6/8 (HOD 14:30-16:00 → −4,1/−4,9 % vs −2,5 % temprano; periodos
  −0,029/−0,036) — real pero secundario, y B no lo sostiene (−0,012/−0,056/+0,025, con un
  pico suelto en 13:30-14:30 de 6,0 %).

### 1.4 PMH Gap de la víspera — NO SIRVE

- A·pmh_fade: <10: 27,7 · 10-30: 27,8 · 30-50: 27,6 · **≥50: 25,7** — sin gradiente, un
  escalón solo en "víspera también fue gap ≥50" que además B no ve (ese tramo rinde 3,8 %,
  encima de la media). "Sin dato" (21 % de vísperas): 28,6 — sin castigo.
- A·day_ret: el escalón se invierte (≥50 menos rojo). B: ρ ≈ 0 los tres años.
- Conclusión: la "reincidencia" de gap no da un filtro de umbral movible; a lo sumo una
  variable binaria aislada sin respaldo en trades.

## 4. Robustez (sólo finalistas)

1. **Ticker-día (B):** 1.6: −0,035/−0,101/−0,045 (pooled −0,065) · 1.2: −0,023/−0,060/−0,037.
   Se mantienen o refuerzan.
2. **Sin huecos >7 días (A):** 1.6 igual (6/8 negativos; 2023 ≈ 0).
3. **Sin 2020 (A):** 1.6→fade 6/7 · 1.2→day_ret 7/7 · 1.5→day_ret 7/7. Nada dependía de 2020.
4. **Umbrales absolutos 1.6:** gradiente en ambos periodos (§3).
5. **Cruce 2×2 (§1.5):** consistente en ambos periodos.

## 5. Múltiple testing y límites

- Comparaciones ejecutadas: 6 criterios × 3 vistas (2 resultados de A + trades B) ×
  (10 deciles/tramos + 8 años + 2 periodos) + robustez ≈ varios cientos. Con ese volumen,
  alguna racha de 6-8 signos iguales sale por azar; lo que separa a 1.6/1.2 es que
  **acumulan** dirección + gradiente + las dos vistas + ticker-día + sin-2020 — el perfil
  que un falso positivo no suele aguantar (misma lógica que el informe de rango/neto).
- La vista A no tiene costes ni condiciones de entrada: mide el día, no la estrategia; es
  cribado de universo, no promesa de PnL.
- 1.4 con 21 % de vísperas "sin dato" (pmh_gap_pct nulo): la UI debería decidir si "sin
  dato" pasa o no pasa un hipotético filtro (aquí, indiferente: ese grupo rinde normal).
- Los splits se excluyen por fecha exacta (`splits.execution_date`); un split ajuste-dentro
  de `prev_close` del lake no es visible (limitación heredada, hallazgo 01 del informe
  anterior).
- hod_time es RTH de la víspera; el `pm_high_time` (hora del máximo PREMARKET de la víspera)
  es otro dato (Bloque 5) y ya está extraído en `hist_universo.parquet`.

## 6. Recomendación

1. **No implementar nada todavía.** Pasar al punto 5 de la hoja de ruta: probar 1.6 (y de
   rebote 1.2/1.5) como filtro de universo en 2-3 estrategias distintas CON EL MOTOR
   (`run_backtest_orchestrator`), decidiendo antes la forma del umbral.
2. Forma recomendada del 1.6 para esa prueba: `lag_day_return_pct_1 <= 0` (keep roja) y
   `<= -10` (keep roja fuerte), mirando SIEMPRE cuántos trades/días se tiran. Evitar la
   forma "excluir >+10" (se invirtió en 2026).
3. Implementación (si pasa el motor): añadir `day_return_pct` (y `rth_fade_pct` si se
   confirma 1.2) a `PREV_DAY_LAG_SOURCES` de `qualifying_windows.py` — la columna base ya
   existe en las tres vías; falta exponerla como lag. 1.1/1.3 necesitarían columnas derivadas
   nuevas; con la evidencia actual no lo justifican.

## 7. Auditoría

- Scripts (en orden): `.tmp_bloque1/paso1_universo.py` (intentó API; ver hallazgo NaN) ·
  `paso2_extraer.py` (extracción read-only una pasada) · `paso3_analisis.py` (criterios,
  vistas A/B) · `paso4_stats.py` (deciles/tramos/años/periodos/veredictos →
  `resultados_stats.txt`) · `paso5_robustez.py` (→ `resultados_robustez.txt`).
- Datos: `.tmp_bloque1/{universo,hist_universo,ref_tipos,ref_splits}.parquet`,
  `vistaA.parquet`, `vistaB.parquet`, `fidelidad.csv`, `manifest.json`.
- **Ciclo BD autorizado por Álvaro (2026-09-25 13:12):** taskkill del árbol del backend
  (PID 39956) → renombrado `local_data.duckdb.wal` (160 B) a `.wal.stalled_bloque1_1312`
  → extracción read-only (3,5 s) → el watchdog «BTT backend watchdog» rearrancó el backend
  solo (un intento fallido a las 13:13:07 mientras la BD estaba tomada, normal y previsto);
  health OK verificado y `DISABLE_GCS_SYNC=true` en el log. El `.wal` nuevo de 13:13 no
  bloquea (no se tocó).
- Sin Spearman de scipy (no instalado): implementado rank+Pearson con p aproximado normal
  (n≥300/año, válido). Sin semillas: no hay remuestreo aleatorio, todo son estadísticos
  cerrados.
- **Nada commiteado; sin push.** Código del repo tocado: NINGUNO.

---

# §8 · Punto 5 de la hoja de ruta — 1.6 y 1.2 probados en una 2ª estrategia: «Doble Techo 1» (mismo día, tarde)

> **Decisión de Álvaro:** filtro de UMBRAL MOVIBLE (curva por deciles por estrategia), no corte fijo.

## 8.1 La estrategia

- **«Doble Techo 1», versión del 22-ago** (`2e59ef98-3c36-4eeb-90a6-890720df87cd`; la otra, `050331cd`, es del 21-ago).
- **PREMARKET, SHORT** — sesión `["pre"]` = velas 04:00–09:30 (`backtest_service.py:2454`; los `custom_*` 09:30–16:00 guardados se ignoran con sesión "pre"). `apply_day: gap_day`.
- Entrada (AND, 1m): **Bar Close a <20 % del Previous Max del premarket** (retest del doble techo) · Accumulated Volume > 2M · Bar Close > 0,5 $ · Bar Close > EMA15 · PM High Gap % > 50.
- Salidas: parcial al 20 % de distancia (50 % del capital) + EOD (50 %); stop Market Structure Previous Max +1 %; **reentradas máx 5**.
- Universo guardado: PMH Gap ≥ 50 + Premarket Volume ≥ 2M (dataset propio `941291f8`, 2026-01-01→08-20).
- Perfil resultante (2024-26 pooled, 11.415 trades válidos): media **+1,55 %** · mediana **−1,55 %** · **win 28,1 %** — short de retest de baja tasa de acierto y sesgo positivo. La 1B es lo contrario (win ~64 %, mediana +7 %): corta debilidad (Close ≤ Prev Bar Low, fade ≥ 30 %), DT corta fuerza.

## 8.2 Corridas (motor real, `POST /api/backtest`; peticiones completas en `.tmp_bloque1/paso6_dt_backtests.py`)

Petición única para todas: `strategy_id 2e59ef98` · `PERCENT 4` + `size_by_sl false` (como B0 de la 1B, decidido con Álvaro: «la manera más sencilla de comparar entre años»; el `return_pct` es relativo al nocional y no depende del tamaño) · costes 0 (fees/slippage/locates) · `look_ahead_prevention: true` · `market_sessions` OMITIDO a propósito → aplica el `["pre"]` de la estrategia (fallback documentado en `backtest_orchestrator.py:462-471`).

| Tag | Dataset | Rango | Job | Trades |
|---|---|---|---|---|
| DT-2025 | `8cf9028b` (PMH≥50 + PMvol≥2M, su universo) | 2025 completo | `803955fc` | 4.803 |
| DT-2025V | `c8bcddc7` (PMH≥50 SIN volumen) | 2025 completo | `4e27dc01` | 4.803 |
| DT-2024 | `d088a358` (PMH≥50) | 2024 completo | `db8e5a84` | 3.414 |
| DT-2026 | `941291f8` (su dataset) | 2026-01-02→08-20 | `ecc3ff90` | 3.209 |

- **Verificación de universo:** DT-2025 y DT-2025V producen los MISMOS 4.803 trades (claves (ticker, fecha, retorno) idénticas) → la regla «Premarket Volume ≥ 2M» del dataset la absorben por completo las condiciones de entrada (`Accumulated Volume > 2M` dispara en la misma vela). Por eso **DT-2024 sobre `d088a358` (año completo, sin regla de volumen) es fiel** al universo de la estrategia.
- La creación de un dataset 2024 propio estaba descartada de facto: el flujo `POST /api/queries` está roto hoy en local (recursión de vista `tickers`) → **[HALLAZGO · 2026-09-25 · 11]**; el dataset vacío del intento se ha borrado.
- Cobertura de vísperas: 11.426→11.415 válidos (11 sin fila previa, 0,1 %; huecos >7 d: 0).

## 8.3 Curva por deciles (mismos bordes del Bloque 1) — 1.6 NETO de la víspera

**Pooled 2024-26 (media · mediana):**

| | D1 (≤−12,5) | D2 | D5 | D10 (≥+16,7) |
|---|---|---|---|---|
| **Doble Techo** | **2,86** · −1,36 | 1,77 · −1,72 | 1,91 · −1,35 | **1,08** · −1,49 |
| 1B (referencia) | **7,62** · 11,41 | 3,05 · 7,60 | 3,54 · 5,83 | **1,13** · 5,03 |

**Por año (D1 vs D10, media):** DT — 2024: 2,65 vs 0,92 · 2025: 3,14 vs 1,02 · 2026: 2,65 vs 1,53 (**extremos separan 3/3 años, misma dirección que la 1B**). Spearman trade-level ≈ 0 (−0,002/−0,018/−0,004): el gradiente de los deciles medios que tiene la 1B aquí no existe. **Ticker-día (3.905 grupos): ρ 3/3 años (−0,040/−0,063/−0,040; pooled −0,050)** — al colapsar las reentradas (hasta 6 por día) la dirección reaparece con fuerza uniforme.

## 8.4 Curva por deciles — 1.2 FADE de la víspera

**Pooled:** DT D1 2,67 · −1,40 → D10 1,41 · −1,43 (1B: 5,31 → 2,62). Por año: ρ trade-level +0,001/−0,010/+0,015 (nada); ticker-día −0,011/−0,045/−0,022 (3/3 pero débil). **Dirección compatible con la 1B, magnitud no operativa.**

## 8.5 Comparación y conclusión

| Criterio | 1B Sobri3 (PM short, corta debilidad) | Doble Techo 1 (PM short, corta fuerza) | Conclusión |
|---|---|---|---|
| **1.6 Neto víspera** | ✅ Fuerte: D1 7,62 vs D10 1,13; ρ 3/3 años (−0,04/−0,09/−0,04); gradiente en deciles | 🟡 Misma dirección, más débil: D1>D10 3/3 años y ρ ticker-día 3/3 (−0,04/−0,06/−0,04); sin gradiente en deciles medios | **Se mantiene como filtro de umbral movible** (2ª estrategia, misma dirección). El efecto vive en los extremos: keep víspera roja |
| **1.2 Fade víspera** | ✅ Vale: D1 5,31 vs D10 2,62; ρ 3/3 años | ❌ Casi plana: ρ ≈ 0 trade-level; ticker-día débil | **No se sostiene fuera de la 1B** — queda como corroboración menor de 1.6 (misma familia, ρ 0,41) |

- **¿Dirección opuesta? No.** DT también es premarket (no RTH), así que la comprobación de inversión pedida no aplicaba — y no hay inversión: víspera roja = mejor en ambas.
- Lectura mecánica: la fragilidad que anuncia la víspera roja se materializa cuando el gap SE ROMPE (disparador de la 1B: vela bajo el mínimo anterior); cuando el gap sigue apretando máximos (disparador de DT: retest), el filtro apenas distingue — de ahí que en DT solo separen los extremos y el ticker-día.
- **Estado en la hoja de ruta (punto 5):** 1.6 pasa la 2ª estrategia en dirección; antes de construirlo como filtro (`lag_day_return_pct_1` en `PREV_DAY_LAG_SOURCES`) quedaría probarlo en una 3ª (idealmente una LONG o una de RTH, donde además se testea la inversión). 1.2 no prosigue sola.
- Mismo aviso de múltiple testing que §5: estas son 2 criterios × 2 estrategias × 3 años más — lo que cuenta es que 1.6 acumula ahora 5/5 "direcciones" (universo 2019-26 en dos periodos, 1B 3/3, DT extremos+ticker-día 3/3).

## 8.6 Auditoría del §8

- Scripts: `.tmp_bloque1/paso6_dt_backtests.py` (4 corridas) · `paso7_dt_deciles.py` (deciles/comparación → `resultados_DT.txt`). Resultados crudos: `.tmp_bloque1/DT_DT-202{4,5,5V,6}.json`.
- 2026 acaba el 20-ago (rango del dataset propio de la estrategia): las cifras 2026 de DT son de enero-agosto.
- Código del repo tocado: NINGUNO. users.duckdb: 4 backtests auto-persistidos por el motor (comportamiento estándar) + borrado de MI dataset vacío `a9257423`.

---

# §9 · Punto 5 (cierre) — 3ª estrategia: «Estrategia RTH. 2B TTP (50k)» de Sailor (RTH short). ¿Se invierte el efecto en RTH?

> Pedido por Álvaro tras ver §8. Misma métrica: deciles con los bordes del Bloque 1,
> por año, trade y ticker-día.

## 9.1 Estrategia y corridas

- **«Estrategia RTH. 2B TTP (50k)»** de Sailor (export staging 10-sep, `c94e2dac`), importada
  al baúl de Álvaro como **COPIA**: `6b2bac54` «2B-RTH-TTP-50k (copia de Sailor)».
  **RTH, SHORT**: sesión custom **09:30–11:30**, ventana de entrada 09:30–10:55, `gap_day`.
  Entra con el precio **>10 % por debajo del PM High** (fade ya iniciado) + Close > 0,70 $ +
  Squeeze > 4 + Accumulated Dollar Volume > 1,5M. Salidas: TP parciales 3 % (50 %) y 6 % (50 %),
  stop Previous Max +1 %, **sin reentradas**, sizing por distancia al stop (`size_by_sl: true`),
  1 nivel de piramidación por %Fade (vwap_cross, ap.RTH — que aquí sí dispara, la sesión es RTH).
- **Universo:** Open Gap % ≥ 45 **y** PMH Gap % ≥ 50 → dataset local gemelo **`96de6bd1`**
  («Universo_Cruce_con_media_prueba_3592», 2024-01-02→2026-09-04, 2.562 pares). Sin crear nada.
- **Petición** (la misma plantilla que DT; lo único distinto: dataset, fechas, init_cash 50.000
  por el «50k» del nombre y `risk_type PERCENT` como en el what-if de Sailor; `risk_r 4` como
  en las otras dos — el `return_pct` por trade es relativo al nocional, así que la curva no
  depende del sizing; `size_by_sl` viaja en la estrategia y el OR del orquestador lo aplica):
  `strategy_id 6b2bac54` · `dataset_id 96de6bd1` · costes 0 (fees/slippage/locates; su
  `monthly_expenses 300` NO se replica) · `look_ahead_prevention: true` · sesiones omitidas
  (aplica el `["custom"]` 09:30–11:30 de la estrategia) · resto de gates off.
- Jobs: `60ccc8bd` (2024) · `68bfeeed` (2025) · `757b4f76` (2026, hasta 04-sep, fin del dataset).
- **Trades: 1.656** (548/661/447; 13 sin víspera, excluidos) · media +4,41 % · mediana +8,50 % ·
  win 65,7 %. Sin reentradas → ticker-día ≡ trade (1.643).
- Nota de proceso: el primer intento dio «0 trades» porque escribí mal el id del dataset
  (`…a54a` en vez de `…a54f`) y un backtest sobre un dataset inexistente **"succeeds" con 0
  días** en vez de fallar → [HALLAZGO · 2026-09-25 · 14].

## 9.2 Curva 1.6 (neto de la víspera) en la 2B — PLANA

| | D1 (≤−12,5) | D5 | D10 (≥+16,7) | ρ por año (trade=ticker-día) |
|---|---|---|---|---|
| **2B RTH** | 4,35 · 8,23 | **8,53** · 10,19 | 3,96 · 6,81 | **+0,046 · −0,010 · −0,033** (pooled +0,002) |
| 1B (ref) | 7,62 | 3,54 | 1,13 | −0,041 · −0,088 · −0,035 |
| DT (ref) | 2,86 | 1,91 | 1,08 | −0,002 · −0,018 · −0,004 (ticker-día −0,04/−0,06/−0,04) |

- Pooled: los deciles medios (D5-D6, víspera ligeramente roja) son los MEJORES (~8,5 %) y los
  extremos los peores — curva en meseta invertida, sin gradiente rojo→verde.
- Corte signo: víspera roja (≤0) vs verde: 2024: 3,94 vs 2,70 · 2025: 5,38 vs 5,11 ·
  2026: 4,69 vs 4,39 — la roja gana por +0,3…+1,2 pp los TRES años, pero es ruido (n≈250-330
  por grupo y año; sin significación).
- **RESPUESTA A LA PREGUNTA: NO SE INVIERTE — SE APAGA.** La vista A (universo) sugería la
  posibilidad de inversión (víspera roja → día RTH MENOS rojo, §3: −1,1 vs −6,0 en 2019-22),
  pero en la 2B no aparece ni una ni otra: plano. Coherente con §8: la fragilidad de la
  víspera roja se materializa ANTES de la apertura (lo que cobra la 1B, y en parte la DT);
  una vez abierto el mercado, la continuación RTH no distingue la víspera.
- 1.2 (fade víspera) en la 2B: ρ +0,051/+0,006/−0,035 — igual de plana.

## 9.3 Cierre del punto 5 — tabla final

| Criterio | 1B Sobri3 (PM short, corta debilidad) | Doble Techo 1 (PM short, corta fuerza) | 2B RTH (Sailor) (RTH short, fade post-apertura) | Conclusión |
|---|---|---|---|---|
| **1.6 Neto víspera** | ✅ Fuerte: D1 7,6 vs D10 1,1; ρ 3/3 años; gradiente | 🟡 Misma dirección, débil: extremos 3/3 y ticker-día 3/3; sin gradiente | ⬜ Plana: ρ 1+/1−/1−; roja vs verde +0,3…+1,2 pp (ruido) | **Filtro válido SOLO para la familia premarket-fade** (umbral movible, forma keep-roja). En RTH no aporta nada (tampoco perjudica) |
| **1.2 Fade víspera** | ✅ Vale: D1 5,3 vs D10 2,6; ρ 3/3 | ❌ Casi plana | ⬜ Plana | **No prosigue** — su señal era la de 1.6 vestida de otra métrica, y fuera de la 1B no se sostiene |

- **Decisión (punto 5 de la hoja de ruta):** 1.6 mejora 2 de 3 estrategias, las dos de fade
  premarket, y es neutro en la RTH → se construye como filtro de universo **con umbral movible
  para estrategias PM de fade** (`lag_day_return_pct_1` en `PREV_DAY_LAG_SOURCES`, forma
  keep-roja con umbral ajustable), NO como filtro universal. El mecanismo documentado
  («víspera débil → gap frágil premarket») es el que hay que re-testear si algún día cambia
  el régimen.
- Múltiple testing acumulado: +2 criterios × 2 estrategias × 3 años desde §8. La conclusión
  de "efecto premarket, no RTH" descansa en la COINCIDENCIA de tres vistas independientes
  (universo A §3, trades 1B, trades DT+2B), no en un corte suelto.

## 9.4 Auditoría del §9

- Scripts: `.tmp_bloque1/paso10_2b_backtests.py` (3 corridas) · `paso11_2b_deciles.py`
  (→ `resultados_2B.txt`). Resultados: `.tmp_bloque1/2B-202{4,5,6}.json`.
- Estrategia importada como copia (`6b2bac54`) — la de Sailor no se toca. users.duckdb:
  3 backtests auto-persistidos + la copia en el baúl.
- 2026 acaba el 04-sep (fin del dataset `96de6bd1`). Código del repo: NINGUNO (en este §9;
  el fix del hallazgo 11/12 fue aparte, commit `cd180fa`).
