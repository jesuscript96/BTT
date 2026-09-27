# INFORME · BLOQUE 7 — El mercado (2026-09-27)

> Método de siempre: tramos/deciles, 2019-22 / 2023-26, trades 1B/DT/2B,
> parciales ctrl 1.6+3.2, sin-dato aparte, cartera a igual riesgo para lo ✅.
> Causalidad (hallazgo 18): 7.1 usa SOLO la víspera; 7.2 en trades cuenta
> solo los cruces +50 % ANTERIORES a la vela de entrada (línea continua
> AH+PM del 5.2-bis). Sin código, sin backtests. Scripts en `.tmp_bloque7/`.

## Tabla-resumen

| Criterio | Veredicto | Dirección | ¿Aporta sobre 1.6/3.2? | ¿Filtrable hoy? |
|---|---|---|---|---|
| 7.1 SPY/IWM víspera (roja/verde y %) | ❌ NO SIRVE | roja 28,1 % vs verde 27,6 % (nada); ρ ±0,03 años mezclados; 5 días igual (−0,03) | NO | N/A (columnas externas al lago) |
| 7.2a Nº de gaps de la VÍSPERA | ✅ EN UNIVERSO (y 2B) — el FADE DEL DÍA más correlacionado del programa | día de microcaps CALIENTE → mucho más fade: <5 gaps → 22,2 % · >30 → 39,5 % (monótono), ρ **8/8** (+0,08..+0,23), pooled +0,27, **parcial +0,29**; en 2B +0,075 3/3 (a RTH le gustan los días calientes); en 1B +0,07 3/3 (flojo) | SÍ (parcial intacto; eje día-de-mercado, ninguno de los anteriores) | Parcialmente: nº de gaps de la víspera = COUNT por fecha de la propia daily_metrics — columna derivada fácil |
| **7.2b Nº de gaps YA EMPEZADOS antes de la entrada (`n_gaps_pre`)** | **✅✅ LA SEÑAL DE TRADE MÁS FUERTE DEL PROGRAMA (1B y DT)** | **en PM: cuantos más gaps lleven empezados ANTES de tu entrada, PEOR: <3 → +12,8 %/trade · 6-10 → +5,4 · ≥10 → −1,6/−3,6 (monótono). 1B ρ −0,23 3/3, parcial ctrl hora-de-entrada −0,23 (NO es la hora: corr 0,18) y ctrl hora+día −0,36 (SE REFUERZA); DT −0,16 3/3; 2B INVERTIDA (+0,08 3/3: el fade de RTH sí quiere días calientes)** | SÍ (independiente de todo lo anterior) | NO hoy: es una feature CROSS-SECTIONAL intradía (cuántos tickers ya cruzaron) — necesita tabla por (fecha, minuto) o market-frame en el motor; ningún filtro de dataset puede expresarla |

**Conclusión (3 líneas):** el bloque encuentra el eje «día de mercado de
microcaps»: los días con muchos gappers deshacen muchísimo más el hueco
(8/8 años, parcial +0,29 — el criterio de universo más fuerte del programa,
con la ventaja de que la versión VÍSPERA es causal pura). Y en trade-level,
la señal más potente jamás medida aquí: para las estrategias PM, entrar
cuando ≥10 gaps llevan ya empezados es PERDER dinero (−1,9 %/trade, 3/3 en
1B y DT, no es la hora de entrada, se refuerza controlando el día), mientras
la 2B (RTH) quiere lo contrario. Cartera 1B a igual riesgo recortando ese
grupo a la mitad: **Calmar 40,9 → 78,3 (+92 %) Y Sharpe 6,03 → 9,46
(+57 %), los 3 años, total AL MISMO TIEMPO que sube** — y esta vez el grupo
recortado es NEGATIVO de verdad (causal verificada, no la trampa del 4.4).

## 1. Definiciones (declaradas antes de mirar)

- 7.1: spy_prev/iwm_prev = `day_return_pct` de SPY/IWM del último día de
  bolsa < D (roja < 0 / verde ≥ 0); *_prev5 = suma de los 5 últimos hasta
  D−1. Fuente: SPY/IWM del propio lago (`.tmp_bloque1/mercado_prev.parquet`,
  1.944 filas cada uno 2019-2026).
- 7.2a: n_gaps_víspera = nº de ticker-días del universo (PMH ≥ 50, cuenta
  sobre vistaA sin limpiar) en el último día de bolsa < D. n_gaps_dia = lo
  mismo en D (DESCRIPTIVO del día: incluye cruces posteriores a una entrada
  PM — caveat declarado, solo para leer el fenómeno).
- 7.2b: n_gaps_pre = nº de tickers cuyo PRIMER cruce de +50 % (línea
  continua AH-víspera→09:30, `g50` del 5.2-bis) fue en minuto ≤ la vela de
  entrada del trade. Causal por construcción (hecho verificado en B5: 0
  cruces posteriores a la entrada).
- Universo A limpio: 13.920. Controles c16/c32_5 de siempre.

## 2. Vista A — universo

- 7.2a: **ρ 8/8 POSITIVO** (+0,082..+0,234), 19-22 +0,19 / 23-26 +0,21,
  pooled **+0,274**, **parcial +0,286**. Tramos monótonos: <5 → 22,2 % ·
  5-10 → 27,1 · 10-15 → 29,9 · 15-20 → 32,6 · 20-30 → 35,8 · >30 → 39,5 %.
  El día-caliente es EL driver del fade del día (más fuerte que 1.6, 3.2,
  2.4…). n_gaps_dia (descriptivo) +0,315 — la parte que añade sobre la
  víspera es la del propio día (caveat LA para estrategias PM).
- 7.1: nada (roja 28,14 vs verde 27,62; 5 días ρ −0,03 con años mezclados;
  parcial ≈ 0). El índice amplio no mueve el fade de microcaps.

## 3. Vista B — trades

| Estrategia | 7.1 SPY/IWM | 7.2a víspera | **7.2b pre-entrada** |
|---|---|---|---|
| 1B | plano (±0,02) | +0,070 3/3 (flojo) | **−0,234 3/3 (−0,26/−0,24/−0,21) · parcial ctrl hora −0,23 · ctrl hora+día −0,36** |
| DT | plano | −0,026 | **−0,160 3/3** |
| 2B | plano | **+0,075 3/3** | **+0,077 3/3 (INVERTIDA)** |

Tramos de n_gaps_pre en 1B: <3 (n=251) **+12,76 %** · 3-6 (n=966) +9,46 ·
6-10 (n=1.267) +5,37 · 10-15 (n=1.054) **−1,58** · 15-25 (n=728) −3,59 ·
>25 −3,40. Comprobación «¿es la hora?»: corr(n_gaps_pre, minuto de entrada)
= 0,18; controlando la hora el efecto NO baja (−0,233) y controlando hora +
calor del día SUBE (−0,359): dentro del mismo minuto del mismo día, entrar
con menos competencia vale más. Sin dato: 0 (todo trade tiene el dato —
cobertura 100 % como el 6.1).

**Lectura económica:** los días calientes tienen el mejor fade TOTAL (lo
cobra el RTH: 2B positivo), pero el fade PREMARKET se lo lleva quien llega
temprano: cuando ≥10 gaps llevan ya empezados, el money nuevo que entra en
un fade va tarde y pierde. Frescura/crowding, no calendario.

## 4. Cartera (igual riesgo total, 1B) — para 7.2b

Grupo = n_gaps_pre ≥ 10 (n=2.283, 51 %, **−1,90 %/trade**; resto +8,40):

| Escenario | Total (pp) | MaxDD | Calmar | Sharpe |
|---|---|---|---|---|
| todos 1 | 14.134 | −346 | 40,9 | 6,03 |
| todos 0,745 uniforme | 10.535 | −258 | 40,9 | 6,03 |
| **todos 1 + grupo a 0,5** | **16.306** | **−208** | **78,3** | **9,46** |

Por años (Calmar/Sharpe base → mixto): 2024 12,2/4,4 → 32,3/7,5 · 2025
19,6/6,4 → 32,5/9,9 · 2026 14,7/7,5 → 30,4/11,7. Con corte ≥ 8: Calmar
69,8; con ≥ 15: 46,9 (umbral movible, óptimo ~10). **A diferencia de
1.6/3.2/2.5/6.1, aquí el grupo recortado PIERDE dinero**: la mejora es
mayor que la de cualquier bloque y sin renunciar a beneficio. La última
palabra, la prueba de Álvaro en Portfolio.

## 5. Múltiple testing (acumulado)

**~34 criterios**. Tras la lección del 4.4 (look-ahead), esta vez la señal
pasa el examen triple: (i) causal por construcción y verificada (cruces
previos a la entrada, línea continua del 5.2-bis); (ii) NO es hora de
entrada (parcial la soporta) ni calor del día (se refuerza al controlarlo);
(iii) replica 3/3 en dos estrategias PM con signo coherente e invertido en
la RTH. Aun así, con 34 tiradas y un efecto de cartera de este tamaño, la
prueba de Portfolio y (si se construye) la vigilancia en vivo son
obligatorias antes de creérsela del todo.

## 6. ¿Filtrable hoy? / cómo se construiría

- 7.2a (nº de gaps de la víspera): columna derivada fácil (COUNT de días del
  universo en la fecha anterior — como el 3.2, decisión de Álvaro). Sirve
  para el universo (fade del día), poco para la 1B.
- **7.2b: NO es expresable como filtro de dataset** (cross-sectional
  intradía). Vías: (a) tabla ETL por (fecha, minuto) con el contador
  «gaps_empezados» (running count de cruces +50 %), que el motor joinee al
  evaluar cada vela — la vía natural; o (b) market-frame en el motor (una
  sola serie por día compartida por todos los tickers del frame). Es
  fontanería nueva (ninguna feature previa era cross-sectional) — decisión
  de Álvaro si se pide tras su prueba de Portfolio.

## 7. Reproducibilidad

- Features: `paso1_features.py` → `features_b7.parquet` (SPY/IWM víspera y
  5d con alineación al último día de bolsa; contadores de gaps).
- Vistas: `paso2_vistas.py` → `resultados_A.txt`, `resultados_trades.txt`.
- Controles de la 7.2b (hora/día) y cartera: impresos en la sesión (§3-4).

## 8. ROBUSTEZ de 7.2b (28-sep, antes de plantearse construirlo) — `paso8_robustez.py`

**Sobrevive TODO, y con una sorpresa sobre DÓNDE vive el efecto.**

**(2) Pureza del contador (sin look-ahead):** el contador es SOLO «cruces de
+50 % sobre la `prev_close` persistida en la línea AH-víspera→09:30, con
minuto ≤ la vela de entrada», computado de velas 1m. SIN filtros del dataset
(tipo, volumen, rth_*, pmh final): la población de tickers contables es «los
que cruzaron +50 % alguna vez ese día» — por definición, quien cruza antes de
tu entrada es contable y quien cruza después no. Cobertura de la población:
106 % del PMH≥50 de vistaA (6 % extra = velas que cruzan +50 % pero cuyo
pmh_gap del ETL quedó < 50 — mismatch menor de base; el contador cuenta
cruces reales de vela, no métricas del día). **Nada que rehacer.**

**(3) Curva de umbral — GRADUAL, no cuchillo:** grupo `n_gaps_pre ≥ X`, Calmar
del mixto: X=3 → 44,0 · 5 → 52,0 · 8 → 69,8 · **10 → 78,3 (máximo)** ·
15 → 46,9 · 20 → 43,0. El retorno del grupo cae monótono (+2,97 → −3,67).
Meseta 8-12; el 10 del informe está en el centro, no en un borde.

**(1) Días — no concentrado y a prueba de bootstrap:** el grupo ≥10 toca
**416 días distintos de 668** (5,5 trades/día). Quitando los 3/5/10 peores
días del grupo: ρ −0,230/−0,228/−0,223 y el Calmar del mixto SUBE
(79,3/80,0/80,7). **Bootstrap por día (1.000×)**: ΔCalmar mediana **+27,7**
(p5 +13,1) · ΔSharpe mediana **+2,84** (p5 +2,35) — **el 100 % de las
iteraciones mejoran ambos**. Ningún día ni episodio lleva el efecto.

**(4) Los días más calientes:** 2026-06-10 (44 gaps) · 09-jun (39) · 11-jun
(37) · 2025-09-10/11 (33) · 2024-12-26 (31) · 2025-09-09 (29) · 2024-12-19
(27) · 2024-02-14 (26) · 2024-12-24 (26). **Van en racimos de días
consecutivos** (jun-26, sep-25, dic-24, feb-24 — frenesí retail por olas),
pero el efecto NO depende de ellos (punto 1). Media por año estable
(10-12 gaps/día).

**(6) DÓNDE vive — SOLO EN ENTRADAS TEMPRANAS (el giro):** antes de 05:30 →
ρ **−0,285** y grupo≥10 **−4,51 %**; después de 05:30 → ρ −0,154 y grupo≥10
**+0,34 % (¡positivo!)**. Es decir: el daño es entrar PRONTO en una mañana
que YA venía caliente de madrugada/after-hours (≥10 gaps arrancados antes de
tu entrada temprana = frenesí nocturno); entrar más tarde en un día caliente
no penaliza (para entonces el conteo alto es normal). El efecto es
«frescura del frenesí», no «hora».

**(7)+(5) El proxy a hora fija NO SIRVE — y eso cierra la implementación
barata:** nº de cruces ya hechos a las 05:00 (para entradas ≥05:30) y a las
06:00 (entradas ≥06:30): ρ **+0,05 (signo equivocado)**, grupo ≥10
**+4,12 %/+2,28 %** (positivo), cartera del proxy 44,4/44,0 (nada). Razón:
el efecto vive en las entradas tempranas, donde el corte fijo aún no sabe
nada útil — y en las tardías el conteo fijo no penaliza. **Conclusión de
implementación:** ninguna aproximación a nivel dataset lo captura (no puede
condicionar a la hora de entrada, y los cortes fijos salen con el signo
cruzado). La forma simple real: tabla precomputada (fecha, minuto) con el
contador running de cruces (una pasada sobre el 1m del lago, como esta
extracción) + condición de ENTRADA en el motor que la consulte por (fecha,
minuto). Eso NO toca `market_frame.py` (el contador viajaría como constante
por fecha en el frame/`ds`), pero SÍ toca `strategy_engine`/simulador —
ficheros COMPARTIDOS con el bot en vivo: **avisar a Jaume antes de nada**
(regla del repo). Mientras tanto queda como hallazgo + la prueba de
Portfolio de Álvaro.
