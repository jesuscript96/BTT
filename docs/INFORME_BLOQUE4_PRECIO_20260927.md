# INFORME · BLOQUE 4 — Dónde está el precio (2026-09-27)

> Mismo método que los Bloques 1-3: deciles con bordes fijos sobre la muestra
> A completa, curva por año, 2019-22 búsqueda / 2023-26 confirmación, trades
> reales (1B, DT, 2B), Spearman parcial contra 1.6 (c16) y 3.2 (c32_5) ya
> construidos, grupo sin-dato contado y con su retorno (nunca descartado), y
> prueba de cartera a IGUAL RIESGO TOTAL para lo que pase todo.
> Solo con lo extraído en el Bloque 1 (hist_universo 3,6 M filas 2019-2026,
> vistaA, trades) + features recalculadas aquí. Backend intacto, cero código
> del repo, cero backtests. Scripts en `.tmp_bloque4/`.

## Tabla-resumen

| Criterio | Veredicto | Dirección (fade) | ¿Aporta sobre 1.6/3.2? | ¿Filtrable hoy? |
|---|---|---|---|---|
| 4.1 Cierre vs MÁX 20 sesiones | 🟡 DUDOSO | víspera lejos del máximo → algo MÁS fade (A 8/8, ρ −0,02..−0,15; 1B 3/3 pero débil) | NO — corr 0,75 con 3.2; parcial por año 4/8 con signo | No (columna nueva) |
| 4.1 vs MÁX 250 | 🟡 DUDOSO | igual, más flojo (6/8) y 49 % sin dato | NO | No |
| 4.2 Cierre vs MÍN 20 | 🟡 DUDOSO | víspera cerca del mínimo → MÁS fade | NO — corr 0,81 con 3.2 (espejo de 4.1) | No |
| 4.2 vs MÍN 250 | 🟡 DUDOSO | igual (6/8) | NO | No |
| 4.3 Distancia a SMA 20 | 🟡 DUDOSO | víspera bajo la media → MÁS fade (A 8/8, gradiente limpio 30,4→23,9) | NO — corr 0,87 con 3.2: es «venía cayendo» re-expresado | No |
| 4.3 SMA 50 | 🟡 DUDOSO | igual (8/8) | NO | No |
| **4.4 PMH Gap ÷ ATR%14** | **✅ SIRVE (con asterisco)** | **PM: gap grande EN ATRs → trade PEOR (1B D1 +7,0 % → D10 −8,7 %, ρ −0,19 los 3 años; DT −0,16). RTH (2B): SE INVIETE (+0,10 3/3, como la vista A)** | **SÍ — parcial ctrl 1.6+3.2: −0,17..−0,22 los 3 años. PERO ~2/3 del edge es el gap CRUDO (c44 ctrl gap: −0,05..−0,08 3/3); el tope de PMH Gap % ya es filtrable HOY** | c44: No (falta ATR). Tope de PMH Gap % (día del gap, ≤): **SÍ hoy** |

**Conclusión (3 líneas):** 4.1-4.3 miden los tres lo mismo — debilidad reciente
de la víspera — y viven dentro de 3.2 (corr 0,75-0,87): ninguna puerta nueva.
4.4 es el segundo criterio que cruza todo (tras 3.2) y el MÁS FUERTE en la
cartera: en la 1B, el 32 % de trades con gap > ~7,6 ATRs pierde de media
(−3,8 %) y recortarlos a la mitad sube Calmar 40,9→79,7 (+95 %) Y Sharpe
6,03→8,91 (+48 %) a igual riesgo, 3/3 años (el uniforme no mueve nada: mejora
pura de reasignación). Asterisco honesto: la mayor parte del edge es el TAMAÑO
crudo del gap (que nunca se estudió como filtro y se puede topar HOY); la
normalización por ATR añade una capa real pero menor (3/3, −0,05..−0,08) —
y en la vista A (fade del día) no aporta nada sobre el gap crudo.

## 1. Definiciones (declaradas antes de mirar)

- Día del gap = D, víspera = D−1. Retorno r = close/prev_close − 1 con la
  `prev_close` PERSISTIDA (splits horneados, hallazgo 25-sep·01). Día
  inválido: prev_close ≤ 0 ó |r| > 500 % (mismo umbral de higiene que B3).
- **Índice ajustado I** = prod(1+r) por ticker: los niveles comparan bien a
  través de splits (la cadena usa la prev_close persistida). TODAS las
  ventanas de 4.1-4.3 se calculan sobre I de las N sesiones D−N..D−1 y quedan
  **NaN si algún día de la ventana es inválido o falta historia** (grupo
  sin-dato, igual filosofía que B3).
- **4.1** c41_maxN = (I[D−1] − max I) / max × 100 (0 = cierra EN el máximo).
  **4.2** c42_minN = (I[D−1] − min I) / min × 100 (0 = cierra EN el mínimo).
  **4.3** c43_smaN = (I[D−1] − media I) / media × 100. N = 20/250 (4.1, 4.2),
  20/50 (4.3).
- **4.4** TR%_t = max(H−L, |H−pc|, |L−pc|)/pc × 100 (misma base ese día, en
  splits también: pc persistida); ATR%14 = media de TR% en D−14..D−1 (14 filas
  válidas); **c44 = pmh_gap_pct[D] / ATR%14** (el gap de HOY en unidades de
  ATR; usa el PMH, causal al premarket). Bordes de deciles en A: 1,6 · 2,6 ·
  3,5 · 4,3 · 5,2 · 6,2 · **7,6 (D8)** · **9,8 (D9)** · **14,7 (D10)**.
- Controles: c16 = day_return_pct[D−1] (1.6); c32_5 RECALCULADA con la
  fórmula declarada del B3 sobre el hist actual (la de features_b3 arrastraba
  el artefacto de los 203 — ver FEATURE 27-sep · MISSING). Universo A limpio:
  13.920 ticker-días (sin sin_prev, hueco ≤ 7), igual que B3.

## 2. Vista A — universo (fade primario)

- 4.1/4.3 (20 sesiones): ρ(decil, fade) negativo **8/8** años (−0,02..−0,18)
  y en ambos periodos: víspera DÉBIL (lejos del máximo, cerca del mínimo,
  bajo la media) → más fade. Gradiente pooled limpio en SMA20: 30,4 → 23,9.
- Las variantes 250: 6/8, más flojas, y **49 % sin dato** (poca historia).
- **c44: ρ POSITIVO 7/8** (solo 2019 negativo) y en ambos periodos (+0,099 /
  +0,093); gradiente pooled 26,2 → 31,6. El gap grande en ATRs → el día
  deshace MÁS el hueco (fade del DÍA, que vive en RTH).
- Cobertura: 96 % (c44) · 89 % (ventanas 20) · 82 % (SMA50) · 51 % (250).

## 3. ¿Aporta por encima de 1.6 y 3.2? (parciales)

- 4.1-4.3: **NO**. Correlación con c32_5 de 0,75-0,87 («cerrar bajo la media
  de 20» ≈ «venía cayendo»). El Spearman parcial (ctrl c16+c32_5) pierde
  magnitud (pooled −0,05..−0,07) y el signo por año se mezcla (4-5/8): son la
  MISMA señal ya construida. En trades 1B el parcial queda en −0,02..−0,05.
- **c44: SÍ.** Parcial ctrl c16+c32_5: **−0,196 pooled y 3/3 años** en 1B
  (−0,215 · −0,194 · −0,172); corr con los controles ≈ 0 (−0,09/+0,01):
  información nueva.
- **Diagnóstico c44 vs gap crudo** (corr(c44, pmh_gap) = 0,54 en 1B, 0,48 en A):
  - 1B: rho(gap crudo, ret) = −0,24 (3/3) — más fuerte que c44 (−0,19).
    c44 controlando el gap: **−0,066, 3/3 negativo** (−0,081 · −0,048 ·
    −0,053): la normalización por ATR aporta una capa real pero menor.
  - Vista A: rho(gap, fade) = +0,161 vs c44 +0,066, y c44 ctrl gap = −0,031
    (el gap ctrl c44 no se mueve: +0,161): **en el fade del día, la
    normalización no aporta nada** — manda el tamaño del gap.

## 4. Vista B — trades reales

| Estrategia | c44: ρ por año (trade) | 4.1-4.3 (todas las ventanas) |
|---|---|---|
| **1B Sobri3 (PM fade)** | 2024 **−0,196** · 2025 **−0,193** · 2026 **−0,169**; deciles D1 +7,0 → D8 +0,5 → D9 −2,4 → D10 **−8,7** | 3/3 negativos pero pequeños (−0,00..−0,10) |
| Doble Techo 1 (PM short) | 2024 −0,169 · 2025 −0,164 · 2026 −0,147; D10 −1,6 | planos / mezclados (±0,03) |
| 2B RTH (Sailor) | 2024 +0,026 · 2025 +0,146 · 2026 +0,116 (D10 +6,2) | planos |

El fenómeno 4.4 tiene **signo opuesto PM vs RTH**: en RTH el fade del día se
materializa (como en la vista A); en premarket, el gap enorme en ATRs es
demasiado violento para la 1B/DT (el D10 de la 1B tiene esperanza NEGATIVA:
532 trades a −8,7 %).

**Sin dato (nunca descartados):** 1B — c44: 202 trades **+11,07 %**; ventanas
20: 778 trades +6,53 %; 250: 2.874 a +3,60 %. Vista A — c44: 555 (fade +35,7,
más que los válidos); 20: 1.497 (+31,8); 250: 6.840 (+29,2). Como en 1.6/3.2:
los sin-dato son de los MEJORES; cualquier uso con filtro debe marcar
«incluir» (la opción ya existe desde el 27-sep).

## 5. Prueba de CARTERA (1B, igual riesgo total, sizing lineal)

Grupo = c44 alto (deciles de A; los sin-dato se quedan a peso 1):

| Escenario | Total (pp) | MaxDD | Calmar | Sharpe |
|---|---|---|---|---|
| todos 1 | 14.134 | −346 | 40,9 | 6,03 |
| todos 0,839 uniforme (= riesgo del mixto) | 11.864 | −290 | 40,9 | 6,03 |
| **todos 1 + D8-10 (c44 > 7,6) a 0,5** | **16.894** | **−212** | **79,7** | **8,91** |
| todos 1 + D9-10 (> 9,8) a 0,5 | 17.002 | −224 | 75,8 | 8,35 |
| todos 1 + D6-10 (> 6,2) a 0,5 | 14.937 | −208 | 71,7 | 8,60 |

D8-10 = 32 % de los trades con retorno medio **−3,83 %** (el resto +6,46 %).
El mixto mejora Calmar y Sharpe los **3/3 años** (p. ej. 2025: 19,6→32,8 y
6,4→9,7). A diferencia del 3.2, aquí el Sharpe SÍ mejora (+48 %): no solo se
recorta la peor caída — el grupo recortado es el que PIERDE. El uniforme da
ratios idénticos al base (como debe ser): toda la mejora es reasignación, no
apalancamiento. **La última palabra, la prueba de Álvaro en Portfolio.**

## 6. Múltiple testing (acumulado)

Van **~20 criterios** (6 B1 + 2 B2 + 5 B3 + 7 B4) × varios resultados y
vistas. 4.4 es el SEGUNDO que cruza todas las puertas (tras 3.2) — con el
matiz añadido de que buena parte de su edge es el gap CRUDO, que nunca se
probó como criterio propio (el universo solo lo acota por abajo, ≥ 50). Con
20 tiradas una racha así puede salir por azar, pero: signo estable 3/3 en dos
estrategias PM, inversión coherente en RTH (donde el fade sí se cobra) y
economía clara (gap gigante = nombre violento que el fade premarket no
domina) apuntan a señal real. Vigilarlo en vivo antes de construir.

## 7. ¿Filtrable hoy?

- **4.1-4.3: no** (necesitarían columnas de ventana: máx/mín/media de la
  víspera — como el 3.2, decisión de Álvaro; y tampoco vale la pena: no
  aportan sobre 3.2).
- **4.4: el c44 completo no** (falta la columna ATR%14). **PERO el tope de
  PMH Gap % (≈ 2/3 del edge) SÍ**: «PM High Gap ≤ X» el día del gap, umbral
  movible, ya funciona en el dataset builder y en la UI. Recomendación:
  probar en Portfolio «todos 1 + gap enorme a 0,5» antes de decidir si se
  construye el ATR; si el tope de gap ya recoge la mayor parte, la columna
  ATR solo añade el resto.

## 8. Reproducibilidad

- Features: `.tmp_bloque4/paso1_features.py` → `features_b4.parquet` (índice
  ajustado por splits vía prev_close persistida; validez |r| ≤ 500 %).
- Vista A + trades: `paso23_vistas.py` → `resultados_A.txt`,
  `resultados_trades.txt` (deciles con bordes de A, por año y periodo).
- Parciales y diagnóstico gap-crudo: `paso4_parciales.py` →
  `resultados_parciales.txt`.
- Cartera: `paso5_cartera.py` → `resultados_cartera.txt`.
- Universo A: 13.920 filas (534/1.709/1.112/1.132/1.945/2.551/2.927/2.010).
