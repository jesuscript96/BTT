# INFORME · BLOQUE 2-bis — Volumen de la víspera, lo que el Bloque 2 no probó (2026-09-27)

> Mismo método de siempre: tramos en $ redondos + deciles, 2019-22 búsqueda /
> 2023-26 confirmación, trades reales (1B, DT, 2B), Spearman parcial contra
> 1.6 (c16) y 3.2 (c32_5), grupo sin-dato contado y con su retorno, cartera a
> igual riesgo total para lo que llegue lejos. Todo causal: SOLO datos de la
> víspera (D−1) o anteriores — nada del día D (regla del hallazgo 25-sep·18).
> Backend intacto, cero código del repo, cero backtests. Scripts en
> `.tmp_bloque2bis/`. Para la rotación se DESCARGÓ la circulación (ver §0).

## Tabla-resumen

| Criterio | Veredicto | Dirección (fade) | ¿Aporta sobre 1.6/3.2? | ¿Filtrable hoy? |
|---|---|---|---|---|
| 2.4 Vol$ víspera (rth_volume × rth_close de D−1) y de 3 días | 🟡 FUERTE EN UNIVERSO, FLOJO EN TRADES | víspera con MUCHOS dólares negociados → MENOS fade (A 8/8, ρ −0,11..−0,23, monótono 30,9 % → 19,7 %) | SÍ en universo (parcial ctrl 1.6+3.2 = −0,21, intacto; eje liquidez-tamaño nuevo). PERO trades: 1B −0,04 (2/3), DT +0,05 3/3 INVERTIDO, 2B −0,06 3/3 → no confirma en PM | No (producto de dos columnas: haría falta columna derivada, fácil) |
| 2.2 Rotación víspera (vol ÷ shares_outstanding ASOF) | ❌ NO SIRVE | alta rotación → menos fade (A 7/8) | NO — al controlar el vol$ desaparece (parcial +0,03 vs −0,19 del vol$ controlándolo a él; corr 0,55) y 47 % sin dato (los sin-dato: fade +29, mejor que los válidos) | No (necesita la tabla de circulación + ASOF) |
| 2.5 Cruce vol × neto víspera (1.6 roja/verde × vol alto) | ✅ SEÑAL PER-TRADE (priorizador); 🟡 como sizing | «COMPRA FUERTE» (verde + vol$ > 2 M$) = la PEOR celda de la 1B: +0,89 %/trade vs +3,51 el resto, 3/3 años; afinada por 3.2: verde × venía-subiendo × vol$alto = **−0,40 %** (n=466). «Distribución» (roja + vol alto) NO es mejor que roja normal (2/3 inconsistente) | SÍ — dentro de verde el vol$ resta 3/3 (−1,4/−1,4/−3,2) y dentro de c32-alto también 3/3; la dirección replica en DT (0,79 vs 1,43) y 2B (2,51 vs 4,94) | No (cruce de dos columnas) |

**Conclusión (3 líneas):** el eje nuevo de este bloque es el DÓLAR de la
víspera (liquidez/tamaño): en el universo es el criterio más fuerte desde el
1.6 (8/8 años, independiente de 1.6 y 3.2), pero en los trades no se confirma
para la 1B y el DT lo invierte — se queda en descriptor de universo, no en
filtro. La rotación es el vol$ re-expresado (al controlarlo desaparece) con la
mitad de cobertura: descartada. Lo accionable es la celda «compra fuerte»
(víspera verde + >2 M$ negociados, peor aún si además venía subiendo): la peor
celda de la 1B los 3 años y la dirección replica en DT y 2B — pero su retorno
sigue siendo POSITIVO (+0,89 %), así que la cartera no mejora recortándola
(Calmar 39,6→38-39, Sharpe ~igual): misma familia que el 1.6, priorizador
cuando falta poder de compra, nunca exclusión.

## 0. Datos nuevos (para este bloque y los Bloques 5-9)

- **Circulación** (`shares_outstanding` por informe trimestral con fecha):
  descargada con el ETL del repo (`backend/scripts/acciones_circulacion_etl.py`,
  reutilizado SIN tocar) para los 3.541 tickers del universo: **48.203
  informes de 2.472 tickers** (2009-2026) → `.cache/intraday/circulacion/`
  (el formato/ruta que ya lee el buscador). Los 1.069 tickers sin informes =
  sin dato. Sin parar el backend (el ETL solo escribe su parquet).
- **SPY/IWM** (Bloque 7): 1.944 filas cada uno, 2019-2026 completo →
  `.tmp_bloque1/mercado_prev.parquet`.
- Ya disponibles de antes: velas 1m (cache `raw`, Bloque 5), OHLC diario
  (hist_universo, Bloques 8-9), tipos de instrumento (ref_tipos, Bloque 6).
  Con la circulación por FECHA, el Bloque 6 puede medir además dilución
  (crecimiento de shares entre informes) y tamaño.

## 1. Definiciones (declaradas antes de mirar)

- Todo con datos HASTA la víspera (D−1). Sin nada del día D (hallazgo 18).
- **2.4** volusd_t = rth_volume × rth_close. c24_prev1 = volusd[D−1];
  c24_prev3 = Σ volusd[D−3..D−1]. Tramos $ redondos: 0,1/0,25/0,5/1/2/5/10/
  20/50 M$.
- **2.2** rot_prev = rth_volume[D−1] ÷ shares_outstanding del ÚLTIMO informe
  con fecha_informe ≤ D−1 (ASOF, sin rellenar hacia atrás — un contrasplit no
  recogido da errores de 5-20×). Control de calidad del ETL: rotación > 20× =
  sospechosa → sin dato. Tramos: 0,5/1/2/5/10/20/50/100 %.
- **2.5** cruce del neto de la víspera (c16 < 0 = roja / ≥ 0 = verde) con
  volumen alto/bajo: (i) relativo (volusd[D−1] ÷ media de D−21..D−2, corte
  > 1) y (ii) absoluto (vol$ > 2 M$). Celdas: «distribución» = roja × alto;
  «compra fuerte» = verde × alto.
- Universo A limpio: 13.920 ticker-días (igual que B3/B4).

## 2. Vista A — universo

- **2.4a**: ρ(decil, fade) negativo **8/8** (−0,112..−0,226), 19-22 −0,137 /
  23-26 −0,191, pooled −0,215; **parcial ctrl 1.6+3.2 = −0.214 (intacto)**.
  Tramos monótonos: <0,1 M$ → fade 30,9 %; 2-5 M → 25,7; 20-50 M → 21,0;
  >50 M → 19,7. 2.4b (3 días) igual y algo más fuerte (pooled −0,236,
  parcial −0,225).
- **2.2**: ρ 7/8 (2019 +0,01), pooled −0,102, parcial −0,090; **pero** parcial
  ctrl 1.6+3.2+**vol$** = +0,025: toda su señal es el vol$ (corr 0,55). Y el
  vol$ controlando la rotación sigue en −0,186. Cobertura 53 % (sin dato
  6.569, fade +29,2 — MEJOR que los válidos).
- **2.5 (universo)**: el volumen RELATIVO no interactúa con roja (las 4
  celdas 26,9-27,9). El vol$ alto BAJA el fade en los DOS colores (roja
  29,6→23,3; verde 29,5→22,8, 8/8 años): efecto principal de liquidez, no
  amplificación del efecto roja.

## 3. Vista B — trades reales

| Estrategia | 2.4a vol$ víspera: ρ por año | 2.2 rotación: ρ por año |
|---|---|---|
| 1B Sobri3 | +0,001 · −0,042 · −0,066 (pooled −0,036) | −0,054 · −0,042 · −0,062 (pooled −0,051; 48 % sin dato, ret +4,58) |
| Doble Techo 1 | **+0,051 · +0,048 · +0,049 (INVERTIDO 3/3)** | −0,033 · +0,004 · +0,039 (nada) |
| 2B RTH | −0,065 · −0,071 · −0,045 (3/3) | 0,000 · −0,027 · −0,050 (flojo; 44 % sin dato +5,66) |

**2.5 en trades (la señal del bloque):** celda «compra fuerte» (verde ×
vol$>2 M$):

| Estrategia | verde-bajo | verde-alto | roja-bajo | roja-alto |
|---|---|---|---|---|
| 1B | +2,83 (n=1.594) | **+0,89 (n=731)** | +3,85 | +4,59 |
| DT | +1,43 | **+0,79** | +1,84 | +2,04 |
| 2B | +4,94 | **+2,51** | +4,78 | +3,57 |

En la 1B el patrón es 3/3 años (verde-alto: +0,95/+0,65/+1,26 vs verde-bajo
+2,33/+2,06/+4,50) y el corte es estable (1-10 M$: dif −1,1..−2,0; mejor
2-5 M). La celda «distribución» (roja × alto) NO gana a roja-normal de forma
consistente (+2,7/−1,1/+1,2). Con 3.2 encima: verde × c32-alto × vol$alto =
**−0,40 %/trade (n=466)** — la celda del momentum-comprador; dentro de
c32-alto el vol$ resta 3/3 (−2,7/−1,8/−2,5). El volumen RELATIVO otra vez no
discrimina (1B: verde-alto 1,11 vs verde-bajo 3,01 — algo, pero menos limpio
que el vol$ absoluto).

**Sin dato (nunca descartados):** 2.4: 34 trades 1B **+12,73 %** (1 día) y
127 **+13,19 %** (3 días) — otra vez los IPOs; 2.2: 2.158 trades 1B (48 %)
**+4,58 %** — mejor que los válidos. Cualquier uso real debe marcar
«incluir» (opción del 27-sep).

## 4. Cartera (igual riesgo total, 1B) — para 2.5

Grupo = verde × vol$ > 2 M$ (n=731, +0,89 %; resto +3,51 %):

| Escenario | Total (pp) | MaxDD | Calmar | Sharpe |
|---|---|---|---|---|
| todos 1 | 13.702 | −346 | 39,6 | 5,89 |
| todos 0,918 uniforme | 12.576 | −317 | 39,6 | 5,89 |
| todos 1 + grupo a 0,5 | 13.376 | −352 | 38,0 | 5,93 |

Con corte 5 M$: 39,6 → 39,0, Sharpe 5,89 → 5,97. Por años: 2024 mejora,
2025/2026 planos. **La cartera NO mejora**: el grupo recortado es flojo pero
POSITIVO — no hay ruido que quitar, igual que pasaba con el 1.6. Uso
recomendado: prioridad de poder de compra (primero lo que no es «compra
fuerte»), nunca exclusión.

## 5. Múltiple testing (acumulado)

Van **~24 criterios** (6 B1 + 2+3 B2/2-bis + 5 B3 + 7 B4 + …). El vol$ de la
víspera es el más fuerte JAMÁS visto en el universo (ρ −0,21, 8/8, parcial
intacto) y aun así NO pasa la puerta de trades — buena lección de por qué la
puerta existe. El cruce 2.5 discrimina 3/3 en TRES estrategias (la
replicación cruzada es su mejor defensa contra el azar) pero sin mejora de
cartera. Nada de este bloque se construye.

## 6. ¿Filtrable hoy?

Nada: el vol$ es un producto de dos columnas (habría que derivarla, como el
3.2 — fácil: `lag` del producto o producto de los `lag`), el cruce necesita
dos condiciones AND de columnas distintas (el builder ya soporta varias
reglas AND, pero falta la columna vol$), y la rotación además necesita la
tabla ASOF (ya descargada en `.cache/intraday/circulacion/` — el buscador ya
la lee para el día D; para la víspera haría falta el lag). Decisión de Álvaro
si algún día se pide; hoy nada lo justifica.

## 7. Reproducibilidad

- Circulación: `.tmp_bloque2bis/paso0_circulacion.py` (reusa el ETL del repo)
  → `.cache/intraday/circulacion/circulacion.parquet` (48.203 filas).
- Features vol$: `paso1_features.py` → `features_b2bis.parquet`.
- Vistas A/B 2.4+2.5: `paso2_vistas.py` → `resultados_A.txt`,
  `resultados_trades.txt`. Interacción por año: `paso25_interaccion.py`;
  control c32 + cartera: `paso25b_control.py`.
- Rotación: `paso3_rotacion.py` → `resultados_rotacion_A/B.txt`,
  `features_b2bis_rot.parquet`.
