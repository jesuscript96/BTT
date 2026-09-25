# Informe — ¿El rango RTH del día anterior al gap predice el resultado del trade?

> **Fecha:** 2026-09-25 · **Pide:** Álvaro · **Ejecuta:** GLM (ZCode) · **Rama:** `alvaro-rama-desarrollo`
> **CSV de trades:** `C:\Users\Alvaro\Downloads\estrategia-1b-modelizaci-n-sobri-3_trades_1831_202609250845.csv` (IS 2025, corrida C1 del estudio 1B)
> **Datos RTH:** `daily_metrics` de `backend/local_data.duckdb` (vía copia read-only; ver §Auditoría)
> **Métrica principal:** `Retorno (%)` por trade. `R múltiplo` solo secundaria — es la R del motor
> (PnL/nocional de entrada con sizing MV, `docs/INFORME_ESTUDIO_1B_SOBRI3_20260924.md` §1), NO R real.
> **PnL ($)** no se usa para comparar grupos (sizing compuesto; solo informativo).

---

## 0. Resumen (10 líneas)

1. **RANGO_PREV NO SIRVE como filtro.** Quintiles, umbrales 10/15 %, por trimestre y a nivel
   ticker-día: todas las diferencias caen dentro del ruido (permutación p = 0,52–0,96) y la
   dirección cambia de trimestre a trimestre (2 de 4 a favor, 2 en contra).
2. **NETO_PREV (a dónde cerró la víspera) SÍ separa.** Víspera roja (neto < 0): retorno medio
   **+4,57 %** · win 66,6 % · PF 1,64. Víspera verde (neto ≥ 0): **+1,36 %** · win 61,7 % · PF 1,16.
   IC95 bootstrap sin solape ([3,10, 6,00] vs [−0,06, 2,76]); permutación **p = 0,0012** (trade)
   y **p = 0,0006** (ticker-día).
3. **Monótono y estable:** en tramos absolutos el retorno medio cae de **7,56 %** (neto ≤ −10 %)
   a **0,74 %** (neto > +10 %) sin saltos; gana la víspera roja en **los 4 trimestres**
   (dif −2,65 a −3,58 pp). No depende de un corte exacto.
4. Se mantiene **quitando los días-previo runner** (4,83 % vs 1,17 %) → no es un proxy de "runner".
5. **Perfil del filtro:** la víspera roja no cambia el gap del día (62,8 % vs 64,3 %) ni el precio
   (6,77 $ vs 8,07 $, leve); cambia CÓMO se mueve el trade: menos SL (25,5 % vs 29,2 %), menos MAE
   (13,9 vs 15,0), más MFE (19,6 vs 18,5). En clave short: acción que cierra débil la víspera
   → su gap up al día siguiente es más frágil y cede mejor.
6. **Cruce 2×2:** el rango solo importa condicionado al neto — el mejor grupo es rango alto ·
   neto < 0 (**+6,04 %**; ticker-día +7,75 %) y el peor rango alto · neto ≥ 0 (+0,83 %).
   "Mucho movimiento" sin dirección no aporta nada (punto 1).
7. **Efecto de filtrar:** keep neto < 0 se come el 47 % de los trades y el 25 % del retorno total
   (5.236 → 3.931 pp) a cambio de subir el retorno medio 2,88 → 4,57 % y recortar el DD acumulado
   −303 → −181 pp. Exclusión suave (neto ≤ +10 %) pierde solo el 19 % de trades y retiene el 95 %
   del retorno total (medio 3,40 %).
8. **Recomendación:** NO poner filtro de rango. El neto sí merece filtro de universo:
   haría falta **añadir `day_return_pct` a las fuentes LAG** (`qualifying_windows.py`) — la columna
   base ya existe en `daily_metrics` con exactamente esta fórmula. Umbral sugerido en §11.
9. **Hallazgos reportados (3):** `prev_close` persistida ≠ `close` de la fila previa (explica el
   `Gap (%)` "raro" del CSV, incluidos los negativos); `rth_range_pct` es ÷`rth_low` en el 100 %
   de esta muestra (difere media +5,77 pp vs ÷open); WAL de `local_data.duckdb` dañado que impide
   reabrir la BD. Detalle en `docs/MEMORIA_MADRE.md` (2026-09-25 · 01/02/03).
10. **Advertencia de múltiple testing:** se han probado 2 indicadores × (5 quintiles + 6 umbrales)
    × 2 niveles + 4 trimestres + cruce 2×2. Un p = 0,0006 con efecto monótono, estable en 4/4
    trimestres y replicado a nivel ticker-día es robusto a ese escrutinio, pero la confirmación
    final debería venir de otro año (2024/2026) antes de operarlo en real.

---

## 1. Pregunta y definiciones exactas

**Pregunta:** ¿filtrar los trades por el rango (y movimiento neto) de la sesión RTH
(09:30–16:00 ET) del día hábil anterior al gap mejora, empeora o no cambia la estrategia?

- `RANGO_A` = (rth_high − rth_low) / rth_open × 100 — **calculado por mí**, definición fija del encargo.
- `RANGO_B` = `rth_range_pct` de daily_metrics **tal cual** — lo que leería el filtro del dataset
  (`lag_rth_range_pct_1`).
- `NETO_PREV` = (rth_close − rth_open) / rth_open × 100 — idéntico a la columna `day_return_pct`
  de daily_metrics (`processor_service.py:122`).
- Día anterior = fila previa del MISMO ticker por fecha en daily_metrics (día hábil real).
- **Look-ahead:** ninguno — el indicador usa la sesión RTH de la víspera (cerrada 16:00 ET);
  el trade entra entre 04:02 y 08:00 del día siguiente y sale a las 08:44 como muy tarde.
  Verificado: el indicador jamás toca datos del propio día de la operación.
- La estrategia opera SOLO el premarket del día del gap (universo PMH Gap % ≥ 50); ningún filtro
  existente mira el día anterior → la pregunta no está contaminada por un filtro directo.

## 2. Datos y recuentos

**CSV:** 1.831 trades · 2025-01-02 → 2025-12-31 · 249 días · 815 tickers · 100 % Short ·
salidas EOD 1.329 / SL 502 · comisiones 0. Base de la corrida: retorno medio +2,95 %,
mediana +7,31 %, win 64,12 %, suma +5.406,99 pp (sobre los 1.831).

**Reentradas:** 412 filas repiten par ticker-fecha en 320 grupos (228×2, 92×3), todas con horas
de entrada distintas → reentradas legítimas (máx. 2 por definición).
**Pares ticker-día únicos: 1.419** (corrijo el 1.511 que circuló antes: 1.831 − 412 = 1.419);
con indicador asignado: 1.409.

**BD:** extracción de `daily_metrics` para los 815 tickers, 2024-12-15 → 2025-12-31:
**187.282 filas, 815/815 tickers, 0 duplicados (ticker, fecha)**, rth_* sin nulos.
`pmh_gap_pct` nulo en 46.767 filas (25 %).

**Casos marcados aparte (de 1.831):**

| Caso | n | Trato |
|---|---|---|
| Sin día anterior en BD | 12 | excluidos (sin indicador) |
| Hueco > 4 días naturales hasta la fila previa | 3 (1×8 d, 2×25 d) | incluidos, marcados |
| Día previo runner (pmh_gap_pct ≥ 50, criterio del universo) | 111 | incluidos + sensibilidad sin ellos |
| Día previo runner "desconocido" (pmh_gap nulo) | 258 | incluidos (limitación) |
| Split | **sin columna split en daily_metrics** | proxy: salto interdía > 60 % → 403 trades |

El proxy de split no separa split de runner real en este universo (saltos interdía enormes son
comunes); queda como limitación, no como exclusión.

**Cobertura: 1.819/1.831 = 99,34 %** (criterio ≥ 95 %: CUMPLE).

## 3. El `Gap (%)` del CSV, explicado y verificado (incluidos los negativos)

- **Fórmula real (verificada):** `Gap (%) = (rth_open_del_día − prev_close_columna) / prev_close_columna × 100`,
  donde `prev_close` es la **columna persistida** de daily_metrics. Reproduce el 99,4 % de los
  trades con |dif| ≤ 0,5 pp (mediana 0,00).
- La fórmula del processor (`processor_service.py:76`) usa en cambio el `close` de la fila previa:
  solo reproduce el 11,6 %, **diferencia mediana 13,31 pp** → la `prev_close` persistida y el
  `close` de la fila anterior NO son la misma referencia (el ETL del lake hornea el ajuste por
  split dentro de `prev_close`, `lake_db_loader.py:241-242`). **→ Hallazgo 01 en MEMORIA_MADRE.**
- Los 117 trades (6,4 %) con `Gap (%)` ≤ 0 tienen win rate 94,9 %, retorno medio +27,6 % y solo
  4,3 % de SL: son mega-gaps cuyo fade se completó ANTES de las 09:30, de modo que la apertura
  RTH quedó bajo el cierre previo. El campo se mide a las 09:30, **después de salir del trade**
  (salida máx. 08:44) y con otra referencia que la señal (PMH gap ≥ 50 en premarket).
  **No es bug del export** — es semántica del campo. Que un short de gap up muestre gaps
  "negativos" es exactamente el perfil de los fades perfectos.

## 4. El rango medido de dos formas (a vs b)

| | valor |
|---|---|
| Filas comparables | 1.819 |
| (b) reproduce (H−L)/**rth_low** | **1.819 (100,0 %)** |
| (b) reproduce (H−L)/**rth_open** | 219 (12,0 %)* |
| Dif (b)−(a): media / mediana | +5,77 pp / +0.58 pp |
| Filas con \|dif\| > 5 pp | 17,2 % |
| Spearman (a) vs (b) | 0,9976 |
| Corte (a) 10 % ≡ corte (b) | 10,56 % (mismo cuantil) |
| Corte (a) 15 % ≡ corte (b) | 15,92 % (mismo cuantil) |

\* esas 219 filas reproducen ambas fórmulas porque en ellas `rth_open ≈ rth_low`.

En esta muestra (dic-2024 → dic-2025) **toda** la columna es ÷`rth_low`; la mezcla de fórmulas
que se temía no aparece aquí, pero la unidad de `lag_rth_range_pct_1` es ÷low y difiere
materialmente de ÷open (media +5,77 pp). **→ Hallazgo 02 en MEMORIA_MADRE.** El orden
(Spearman 0,998) es casi idéntico, así que para QUINTILES da igual; para UMBRALES ABSOLUTOS
la unidad importa y el veredicto se da en (b).

## 5. Distribución (percentiles 10/25/50/75/90)

| Indicador | p10 | p25 | p50 | p75 | p90 |
|---|---|---|---|---|---|
| RANGO_A (÷open) | 5,01 | 7,65 | 13,22 | 25,40 | 55,86 |
| RANGO_B (÷low) | 5,21 | 7,98 | 14,06 | 28,02 | 74,95 |
| NETO_PREV | −12,95 | −4,52 | 0,32 | 6,88 | 20,20 |

## 6. RANGO_PREV — resultado: SIN SEÑAL

**Quintiles (nivel trade, Retorno %):**

| Quintil | n | win % | ret medio | IC95 | PF | %SL | MAE | MFE |
|---|---|---|---|---|---|---|---|---|
| Q1 (bajo) | 364 | 63,5 | 3,69 | [1,59, 5,79] | 1,54 | 23,6 | 14,3 | 17,6 |
| Q2 | 364 | 62,4 | 2,14 | [0,03, 4,28] | 1,28 | 28,0 | 14,9 | 17,9 |
| Q3 | 363 | 66,1 | 2,18 | [−0,12, 4,42] | 1,27 | 28,4 | 15,3 | 19,1 |
| Q4 | 364 | 62,1 | 3,02 | [0,52, 5,50] | 1,34 | 29,9 | 14,3 | 20,5 |
| Q5 (alto) | 364 | 66,2 | 3,36 | [1,11, 5,55] | 1,45 | 27,2 | 13,7 | 20,2 |

Forma de U suave, IC todos solapados. Permutación Q5 vs Q1: **p = 0,84**.

**Umbrales (trade y ticker-día; permutaciones):**

| Comparación | ret medio g1 | ret medio g2 | p (trade) | p (ticker-día) |
|---|---|---|---|---|
| A < 15 vs ≥ 15 | 2,64 (n=989) | 3,16 (n=830) | 0,61 | 0,53 |
| A < 10 vs ≥ 10 | 2,80 (n=669) | 2,93 (n=1.150) | 0,91 | 0,82 |
| B < 15 vs ≥ 15 | 2,71 (n=950) | 3,07 (n=869) | 0,72 | 0,65 |
| B < 10 vs ≥ 10 | 3,01 (n=619) | 2,81 (n=1.200) | 0,85 | 0,95 |

**Por trimestre (RANGO_A < 15 vs ≥ 15, ret medio):** Q1 +1,29 · Q2 −0,88 · Q3 +1,60 · Q4 −0,75
— la dirección cambia 2 de 4 trimestres. Ni monótono ni estable.

**Conclusión RANGO: NO SIRVE.** Ninguna vista (quintiles, umbrales en las dos unidades,
trimestres, ticker-día, sin runners) muestra nada fuera del ruido.

## 7. NETO_PREV — resultado: SEÑAL CLARA Y ESTABLE

**Quintiles (trade):**

| Quintil | n | win % | ret medio | IC95 | PF | %SL | MAE | MFE |
|---|---|---|---|---|---|---|---|---|
| Q1 (muy neg) | 365 | 69,3 | **6,35** | [4,05, 8,50] | 1,97 | 22,7 | 13,5 | 21,1 |
| Q2 | 363 | 63,9 | 2,53 | [0,28, 4,75] | 1,32 | 29,2 | 14,7 | 18,6 |
| Q3 | 363 | 60,6 | 2,41 | [0,13, 4,67] | 1,31 | 28,7 | 14,4 | 17,6 |
| Q4 | 364 | 64,6 | 2,25 | [−0,08, 4,51] | 1,28 | 26,1 | 15,3 | 19,3 |
| Q5 (muy pos) | 364 | 61,8 | **0,85** | [−1,42, 3,14] | 1,10 | 30,5 | 14,5 | 18,7 |

**Tramos absolutos (monótono perfecto):** ≤ −10 %: **7,56** (n=242, win 70,7 %, PF 2,23) ·
−10..0: 3,27 (n=651) · 0..10: 1,77 (n=572) · > +10 %: **0,74** (n=354, win 61,6 %).

**Por signo:**

| Grupo | n | win % | ret medio | IC95 | ret suma | PF | %SL | MAE | MFE |
|---|---|---|---|---|---|---|---|---|---|
| NETO < 0 | 860 | 66,6 | **4,57** | [3,10, 6,00] | 3.931 | 1,64 | 25,5 | 13,9 | 19,6 |
| NETO ≥ 0 | 959 | 61,7 | **1,36** | [−0,06, 2,76] | 1.306 | 1,16 | 29,2 | 15,0 | 18,5 |

Permutación NETO≥0 − NETO<0: **p = 0,0012** (trade) · **p = 0,0006, dif −3,92 pp** (ticker-día,
n = 686/723, ret medio 5,73 vs 1,81). Los IC95 bootstrap no se solapan.

**Por trimestre (NETO<0 − NETO≥0, ret medio):** Q1 −3,58 · Q2 −2,65 · Q3 −3,26 · Q4 −3,35 →
**4 de 4 trimestres** a favor de la víspera roja, magnitud similar.

**Sensibilidad sin días-previo runner (n = 1.462):** NETO<0 4,83 % vs NETO≥0 1,17 % — se mantiene
(sin los 258 "desconocido" no se probó; limitación).

**Perfil (qué separa el filtro):** la víspera roja no cambia apenas el gap del día (62,8 % vs
64,3 %) ni la hora de entrada; sí el COMPORTAMIENTO del trade: menos SL, menos recorrido en
contra (MAE), más a favor (MFE). El grupo NETO≥0 opera además acciones algo más caras
(8,07 $ vs 6,77 $ de media).

## 8. Estrategia COMPLETA vs FILTRADA (nivel trade)

COMPLETA (1.819 válidos): suma **+5.236 pp** · medio 2,88 · mediano 7,19 · win 64,0 % ·
DD acumulado −303 pp*. (*DD sobre la curva de suma de Retorno % por día — informativo, no DD de equity.)

| Filtro | n (pierde) | suma | medio | mediano | win % | DD acum |
|---|---|---|---|---|---|---|
| A < 15 | 989 (46 %) | 2.615 | 2,64 | 6,70 | 63,8 | −362 |
| A ≥ 15 | 830 (54 %) | 2.622 | 3,16 | 7,78 | 64,3 | −256 |
| B < 15 | 950 (48 %) | 2.572 | 2,71 | 6,76 | 64,0 | −314 |
| B ≥ 15 | 869 (52 %) | 2.664 | 3,07 | 7,75 | 64,1 | −231 |
| **NETO ≤ 0** | 893 (51 %) | **3.961** | **4,44** | 8,40 | 66,4 | **−181** |
| **NETO ≤ +10** | 1.465 (19 %) | **4.974** | **3,40** | 7,67 | 64,6 | −251 |
| (lo que tira NETO > +10) | 354 (19 %) | 263 | 0,74 | 5,65 | 61,6 | — |

Lectura: el filtro por rango no mueve nada (±0,5 pp de media). El filtro por neto estricto
(keep ≤ 0) sube mucho la calidad pero pierde la mitad de los trades y un 24 % del retorno total.
La **exclusión suave (NETO ≤ +10)** es el punto dulce: tira el 19 % de trades que solo aportan
263 pp (5 % del total) y deja la suma casi intacta con mejor media y menos DD.

## 9. Cruce 2×2 — RANGO_A (mediana 13,22) × NETO (signo)

| Grupo | n | win % | ret medio | IC95 | PF | %SL |
|---|---|---|---|---|---|---|
| rango bajo · NETO<0 | 477 | 65,6 | 3,39 | [1,49, 5,25] | 1,48 | 26,0 |
| rango bajo · NETO≥0 | 432 | 62,0 | 2,02 | [0,07, 3,99] | 1,26 | 26,9 |
| **rango alto · NETO<0** | 383 | 67,9 | **6,04** | [3,76, 8,30] | 1,85 | 24,8 |
| rango alto · NETO≥0 | 527 | 61,5 | **0,83** | [−1,16, 2,79] | 1,09 | 31,1 |

(Ticker-día: 4,06 / 2,47 / **7,75** / 1,25.) La conclusión es limpia: **lo que importa es hacia
dónde cerró la víspera, no cuánto se movió**; y cuando el rango fue alto, el signo del cierre lo
separa TODO (6,04 vs 0,83 — los dos extremos de la tabla). "Rango alto" sin más no vale nada (§6);
"rango alto + cierre débil" es el perfil ideal del corto; "rango alto + cierre fuerte" es el peor.

## 10. Veredicto

**RANGO_PREV: NO SIRVE.** Diferencias dentro del ruido en todas las vistas (p 0,52–0,96),
dirección inestable por trimestre, sin monotonía. No poner el filtro.

**NETO_PREV: SIRVE** (criterios del encargo):
- IC95 de los grupos sin solape y permutación p = 0,0012 (trade) / 0,0006 (ticker-día) < 0,05 ✓
- Dirección constante en 4/4 trimestres (regla de mayoría holgada) ✓
- Grupos grandes (860/959 trades; 686/723 ticker-día; hasta el tramo más fino tiene 242) ✓
- Monótono en tramos absolutos (no depende de un corte exacto) ✓
- Aviso: con el número de comparaciones probadas, un resultado aislado sería sospechoso; este
  acumula monotonía + estabilidad + dos niveles de análisis, que es lo que un falso positivo
  no suele aguantar. Aun así, confirmación en 2024/2026 antes de operarlo.

**Trasladabilidad:** el mecanismo plausible — «víspera roja → acción sin compradores residual →
el gap up del día siguiente es más frágil» — es general, pero solo está MEDIDO en este contexto:
fade SHORT de premarket sobre universo PMH ≥ 50 % con salida antes de las 08:45. Para estrategias
long, de sesión RTH, o universos distintos, es hipótesis sin datos. Que la señal viva en el
DATASET (filtro de universo) y no en la mecánica de salida la hace reutilizable por diseño si
el mecanismo es el general.

## 11. Recomendación concreta

1. **NO añadas** `Gap -1 · rth_range_pct_1` — no merece la pena.
2. **El neto sí:** hoy NO existe como filtro (`PREV_DAY_LAG_SOURCES` en
   `qualifying_windows.py:20` no lo incluye). La columna base ya está (`day_return_pct`) —
   haría falta añadirla a las fuentes LAG y verificar que las TRES vías la materializan
   (query.py / data_service DuckDB / gcs_cache Parquet: la del lake necesita que exista allí;
   si una vía no la materializa, la regla se ignora en silencio o tira la query — dice el
   propio docstring del módulo).
3. **Umbral:** si el objetivo es calidad por trade → `lag_day_return_pct_1 < 0`
   (medio 4,44 %, win 66,4 %, DD −181). Si es no sacrificar volumen → `≤ +10`
   (retiene el 95 % del retorno total con el 81 % de los trades, medio 3,40 %).
   En unidad de `day_return_pct` (÷rth_open), que es la que tendría el filtro.
4. Antes de operarlo en real: replicar en 2024 y 2026 (los datasets OOS del estudio 1B ya existen).

## 12. Limitaciones

1. Un solo año (2025) → trimestres en lugar de años; sin OOS.
2. Sin costes (fees/slippage/locates = 0) y sizing compuesto → `Retorno (%)` como métrica
   principal; el tramo sub-1 $ está sobreestimado (nota del estudio 1B).
3. Reentradas correlacionadas → la significación se da a nivel ticker-día (1.409 pares);
   el bootstrap a nivel trade las trata como independientes (aviso).
4. 258 trades con runner-previo "desconocido" (pmh_gap_pct nulo) quedan dentro; la sensibilidad
   sin runners (111) no cambia conclusiones.
5. Split: sin columna en daily_metrics; el proxy (salto interdía > 60 %) no separa split de
   runner (403 trades marcados). El ajuste por split del lake vive dentro de `prev_close`
   (hallazgo 01) y no es visible aquí.
6. `RANGO_B` corresponde a `rth_range_pct` de daily_metrics LOCAL (100 % ÷low en la muestra);
   si el dataset se materializara por la vía GCS, la columna viene del Parquet del lake y no
   he podido verificar su fórmula.
7. `Gap (%)` del CSV medido a las 09:30 (tras la salida del trade) y contra `prev_close`
   persistida — no es el gap de la señal (PMH premarket) ni el del processor local.

## 13. Auditoría

- Scripts (reproducibles, en orden): `.tmp_rango_prev/paso0_csv_bueno.py` (inspección CSV) ·
  `paso1_extraccion.py` (daily_metrics → parquet, vía copia) · `paso2_estudio.py`
  (análisis completo; vuelca `resultados_paso2.txt`) · `paso3_gapcheck.py`
  (identificación de la fórmula del `Gap (%)`).
- Datos: `.tmp_rango_prev/daily_rth_815tickers.parquet` (187.282 filas) ·
  `.tmp_rango_prev/resultados_paso2.txt` (todas las tablas y p-valores).
- Semillas fijas (numpy `default_rng(42)`); bootstrap 10.000 remuestreos, permutaciones 5.000.
- La BD original NO se tocó: la extracción se hizo sobre una copia física
  (`.tmp_rango_prev/copia_local_data.duckdb`, borrada tras el estudio) porque el WAL original
  está dañado e impide reabrir el archivo (hallazgo 03).
- Hallazgos reportados en `docs/MEMORIA_MADRE.md`: [HALLAZGO · 2026-09-25 · 01/02/03].
- Nada commiteado; sin push (pendiente de OK de Álvaro).

---

# Confirmación fuera de muestra (2024 y 2026) — mismo día, tarde

> **Veredicto en una línea: fuera de muestra el efecto NETO_PREV mantiene la DIRECCIÓN pero
> pierde la significación (p 0,47 en 2024, 0,61 en 2026, 0,35 pooled) y F2 SE INVIERTE en
> 2026 → ningún filtro merece la pena operativamente. El edge fuerte era de 2025 (IS).**

## Setup de la confirmación

- **Referencia única: B0** (petición exacta de `corridas.jsonl`, tag `B0`: estrategia `5ed17d89`,
  `PERCENT 4`, `init_cash 10.000`, custom 04:00–08:45, costes 0, `look_ahead_prevention: true`,
  todo explícito). El CSV de Álvaro tenía los MISMOS 1.831 trades (claves 1:1, precio idéntico)
  con otro camino de sizing (suma 5.406,99 vs 5.837,54 de B0) — decisión de Álvaro: B0 vale
  como referencia.
- **F1** = víspera roja (`NETO_PREV < 0`) · **F2** = `NETO_PREV ≤ 10`. Umbrales FIJADOS con 2025,
  sin reoptimizar. `NETO_PREV` recalculado por mí desde `rth_open/rth_close` de `daily_metrics`
  (extracciones frescas por año: 2023-12-15→2024-12-31 y 2025-12-15→2026-09-04).
- Jobs del motor real (backend local, DISABLE_GCS_SYNC verificado):
  repro-2025 `d4409208` (== B0 de ayer al céntimo, 1.831 trades) · 2024 `f574e70b`
  (1.392 trades, año completo) · 2026 `73a6e649` (**1.259 trades, 2026-01-02 → 2026-09-04**,
  hasta donde llega el dataset).

## 0. El efecto en B0-2025 se mantiene igual que con el CSV

| Métrica | CSV | B0 |
|---|---|---|
| F1 rojo / verde (ret medio) | 4,57 / 1,36 | 4,80 / 1,60 |
| Permutación F1 (trade · ticker-día) | p=0,0012 · p=0,0006 | p=0,0016 · p=0,0024 |
| F1 trimestres a favor | 4/4 (+2,65 a +3,58) | 4/4 (+2,67 a +3,53) |
| F2: el grupo >10 aporta | 5 % de la suma (19 % de trades) | 6 % (19 %) |

→ El sizing distinto no afecta al efecto; B0 es una base válida para la confirmación.

## 1. F1 (víspera roja vs verde) fuera de muestra

| | 2024 (1.386 válidos) | 2026 (1.242 válidos) |
|---|---|---|
| Rojo: n · ret medio · win · PF | 640 · **2,70** · 63,9 % · 1,37 | 622 · **4,28** · 66,2 % · 1,54 |
| Verde: n · ret medio · win · PF | 746 · 1,87 · 61,8 % · 1,23 | 620 · 3,60 · 64,2 % · 1,44 |
| IC95 rojo / verde | [1,07, 4,29] / [0,30, 3,39] — solapan | [2,44, 6,07] / [1,72, 5,47] — solapan |
| Permutación trade · ticker-día | p=0,47 · p=0,49 | p=0,61 · p=0,54 |
| Trimestres a favor del rojo | 3 de 4 (+2,5 / −2,0 / +0,8 / +1,0) | 2 de 3 (+1,6 / −0,05 / +0,8) |

Ticker-día: rojo 3,37 vs verde 2,39 (2024) · rojo 5,59 vs verde 4,60 (2026). Perfil (MAE/MFE/%SL)
apenas se separa fuera de 2025.

**Pooled 2024+2026** (2.628 trades): rojo 3,48 vs verde 2,65, dif −0,82 pp, **p = 0,35**.

## 2. F2 (≤ 10 vs > 10) fuera de muestra

| | 2024 | 2026 |
|---|---|---|
| keep ≤10: n · ret medio · % suma | 1.062 · 2,85 · 97 % | 1.050 · 3,56 · 76 % |
| Grupo >10: n · ret medio · % suma | 324 · 0,30 · 3 % | 192 · **6,03** · **24 %** |
| Permutación | p = 0,06 | p = 0,19 |

En 2024 F2 replica el patrón de 2025 (el grupo >10 casi no aporta nada). **En 2026 SE INVIERTE:
la víspera muy verde (>+10 %) rinde MÁS que la resto (6,03 vs 3,56) y concentra el 24 % del
retorno total del año** — el filtro lo habría tirado entero.

## 3. Veredicto (criterio de Álvaro: confirmado solo si la dirección se mantiene en los DOS años)

- **F1 (víspera roja): dirección CONFIRMADA en ambos años, efecto NO demostrado.** El rojo gana
  en 2024 y 2026 (trade, ticker-día y 5 de 7 trimestres), pero la diferencia se reduce de
  −3,2 pp (2025, p=0,0012) a −0,8 pp (p 0,47-0,61; pooled p=0,35). Con 3 años juntos la
  dirección es consistente (9 de 11 trimestres a favor), la magnitud de 2025 no se sostiene.
- **F2 (≤10): NO CONFIRMADO — invertido en 2026.** Un filtro que en un año quita el 15 % de
  trades que aportaban el 24 % del retorno es peligroso, no conservador.
- **Recomendación final revisada: NO añadir el filtro de día anterior.** Ni rango (§6, sin
  señal) ni neto (dirección débil y F2 inestable). Lo que queda es conocimiento direccional
  suave — "víspera roja tiende a ser mejor para cortos" — sin valor operativo como filtro de
  universo. La advertencia de múltiple testing de la primera parte era el riesgo real: el
  p=0,0006 de 2025 era el año bueno, no una ley.
- Si algún día se reconsidera, los datos necesarios serían: más años de OOS (2027+) o una
  variante continua (peso por NETO, no corte), que es donde la dirección consistente podría
  capitalizarse con menos riesgo de corte frágil.

## 4. Punto D — fórmula real de `day_return_pct` (toda daily_metrics, 2019–2026)

Sobre las 19.355.041 filas de la BD local, por año, tolerancia 0,01:

| Año | filas | % = (rth_close−rth_open)/rth_open | % = (rth_close−prev_close)/prev_close | % cero |
|---|---|---|---|---|
| 2019 | 2.073.128 | **100,0** | 8,1 | 6,4 |
| 2020 | 2.168.477 | **100,0** | 5,9 | 4,9 |
| 2021 | 2.569.266 | **100,0** | 7,7 | 6,4 |
| 2022 | 2.717.264 | **100,0** | 7,6 | 8,7 |
| 2023 | 2.565.888 | **100,0** | 7,6 | 7,6 |
| 2024 | 2.568.457 | **100,0** | 7,2 | 6,5 |
| 2025 | 2.711.656 | **100,0** | 6,9 | 6,0 |
| 2026 | 1.980.905 | **100,0** | 6,7 | 6,7 |

**La columna es uniformemente la fórmula "intra-RTH" (la que queríamos) en el 100,0 % de las
filas de todos los años** — los ~7 % que también casan con la variante `prev_close` son días
donde `rth_open ≈ prev_close`. **No hay mezcla en los datos.** Las dos fórmulas conviven solo en
el código (`processor_service.py:122` ÷open vs `catchup_gcs.py:518` ÷prev_close — que además
escribe `rth_range_pct` ÷open mientras el processor lo escribe ÷low); hoy esa divergencia no
se ha materializado en la tabla, pero es una inconsistencia latente → **[HALLAZGO · 2026-09-25
· 05]** en MEMORIA_MADRE. Bonus verificado en la misma pasada: `rth_range_pct` = ÷`rth_low`
en el 100,0 % de las filas de todos los años (refuerza el hallazgo 02: no hay mezcla, la
columna es ÷low de principio a fin).

## 5. Auditoría de la confirmación

- Jobs: repro-2025 `d4409208` · 2024 `f574e70b` · 2026 `73a6e649` (peticiones = B0 literal,
  solo dataset/fechas). Results: `.tmp_rango_prev/resultados/B0-202{4,6}.json`, `REPRO-2025.json`.
- Extracciones: `daily_rth_2024.parquet` (151.062 filas, 647 tickers) ·
  `daily_rth_2026.parquet` (94.368 filas, 567 tickers) · punto D: `puntoD_day_return.csv`,
  `puntoD_rth_range.csv`.
- Scripts: `paso4a/4b/4c/5a/5b/5c/5d/5e/5f*.py` · tablas: `resultados_F1F2_2024_2026.txt`.
- El acceso a la BD (locked por el backend) se resolvió con el ciclo autorizado por Álvaro:
  taskkill del árbol del backend → renombrado del WAL stall (`.wal.stalled_20260925b`) →
  extracción read-only → el watchdog ("BTT backend watchdog") rearrancó el backend solo
  (health OK verificado al terminar).
- Nada commiteado; sin push.
