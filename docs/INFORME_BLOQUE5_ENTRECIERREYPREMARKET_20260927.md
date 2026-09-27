# INFORME · BLOQUE 5 — Entre el cierre de la víspera y el premarket (2026-09-27)

> Método de siempre: deciles/tramos horarios, 2019-22 / 2023-26, trades reales
> (1B, DT, 2B), parciales ctrl 1.6+3.2, sin-dato aparte, cartera a igual
> riesgo para lo ✅. **Causalidad (hallazgo 18): en trades, los cruces de
> premarket solo cuentan si ocurren ANTES de la vela de entrada**; en el
> universo (descriptivo del día) se usa el PM completo. Sin código, sin
> backtests. Scripts en `.tmp_bloque5/`.

## Paso 0 — factibilidad (hecha primero)

- La CACHE de velas no bastaba: PM del día del trade 86-90 %, pero **AH de la
  víspera solo 63-67 %** (y universo 60-93 % según año).
- El LAGO LOCAL sí trae el día completo (04:01-19:32, PM+RTH+AH) 2019-2026:
  extracción en UNA pasada filtrada (18,0 M de velas para los 27.613
  pares ticker-fecha necesarios, ~4 min) → `.tmp_bloque5/velas_b5.parquet`.
  **Sin descargas ni paradas del backend** → Bloque 5 factible.

## Tabla-resumen

| Criterio | Veredicto | Dirección (fade) | ¿Aporta sobre 1.6/3.2? | ¿Filtrable hoy? |
|---|---|---|---|---|
| 5.1 AH de la víspera (cierre 16:00 → último precio AH) | ❌ NO SIRVE | AH muy alcista → algo menos fade (pooled −0,08) | NO — parcial ctrl 1.6+3.2 = −0,02; en 1B −0,05 y parcial 0 | No (necesita velas de la víspera en la query) |
| 5.2 Hora del primer +20 %/+50 % (madrugada vs tarde) | ✅ EN UNIVERSO · 🟡 NO ACCIONABLE EN TRADES | **gap de MADRUGADA → mucho más fade del día**: 8/8 años ρ −0,09..−0,30 (5.2b), parcial −0,24; 04:00-04:30 ~32-33 % vs 08:00-09:30 ~24-25 % | SÍ en universo (independiente de 1.6/3.2) — PERO en trades causales: 1B plana (+0,00; entra tan pronto que no discrimina), DT −0,05 3/3 débil, 2B plana | Como condición de vela, el motor ya puede («PM High Gap» running); no como columna de dataset |
| 5.3 Minutos del primer +50 % a la entrada | ❌ NO SIRVE (en la 1B; DT +0,06 3/3 débil) | — | NO — 1B −0,01, 2B −0,02, DT +0,06 (signos cruzados) | Igual que 5.2 |

**Conclusión (3 líneas):** la única señal del bloque es descriptiva del día:
el gap que nace de madrugada se deshace más durante el DÍA (8/8 años,
parcial −0,24 — el fenómeno «noticia de madrugada» existe). Pero la 1B ya
entra de madrugada por diseño y su retorno no depende de cuándo cruzó el
+50 % (plana, y el 60 % de sus trades tienen el cruce en el primer minuto
cotizado); DT y 2B tampoco lo explotan. El AH de la víspera y la distancia
cruce-entrada no aportan nada sobre 1.6/3.2. **Nada se construye y no hay
prueba de cartera (nada pasó la puerta de trades).**

## 1. Definiciones (declaradas antes de mirar)

- 5.1: c51 = (último close AH 16:00-19:59 de D−1 − close_1559 de D−1) /
  close_1559 × 100. Sin velas AH (microcaps sin negociación AH) = sin dato.
- 5.2: t20/t50 = MINUTO en que el máximo acumulado del PM de HOY (04:00-09:29)
  cruza por primera vez +20 %/+50 % sobre la `prev_close` persistida (misma
  referencia que los gaps del motor). En el universo: PM completo
  (descriptivo; ojo: el fade del día tiene más horas si el gap es temprano —
  parte del efecto es mecánico). En trades: **solo si el cruce es ANTERIOR a
  la vela de entrada** (causal).
- 5.3: mins50 = minutos entre t50 causal y la entrada del trade.
- Datos: 18,0 M de velas 1m del lago local (PM del día + AH de la víspera)
  para universo A + días de trade. Universo A limpio: 13.920.

## 2. Vista A — universo

- **5.2b (hora del primer +50 %): ρ 8/8 NEGATIVO** (−0,091..−0,303), 19-22
  −0,264 / 23-26 −0,125, pooled −0,187, **parcial ctrl 1.6+3.2 = −0,236**
  (se REFUERZA). Tramos horarios: cruz antes de 04:30 → fade 32-33 %;
  07:00-08:00 → 26-27 %; 08:00-09:30 → 24-25 %. El 5.2a (+20 %) igual pero
  más flojo (pooled −0,06, parcial −0,11).
- 5.1: pooled −0,082 pero **parcial −0,017** (vive dentro de 1.6/3.2 y de
  5.2: corr(c51, hora50) = −0,61 — el AH alcista de la víspera adelanta la
  hora del gap). Deciles no monótonos. Cobertura 65 % (sin dato 4.860, fade
  +28,4).
- Nota: en el universo t50 existe el 100 % de los días por definición (el
  universo ES «PMH ≥ +50 %»); la lectura es puramente temporal.

## 3. Vista B — trades (CAUSAL)

| Estrategia | 5.1 AH víspera | 5.2b hora +50 % causal | 5.3 mins a entrada |
|---|---|---|---|
| **1B** | −0,022/−0,072/−0,059, parcial −0,02 | **+0,00 pooled** (−0,02/+0,04/−0,02); 60 % de trades con cruce en el primer minuto cotizado (D1) | −0,01 pooled (±0,00 los 3 años) |
| DT | +0,04 pooled 3/3 positivo (débil) | −0,05 pooled, 3/3 (débil: madrugada algo mejor) | +0,06 pooled 3/3 (débil) |
| 2B | +0,04 pooled (débil) | −0,01 flat | −0,02 flat |

La señal fuerte del universo no aparece en NINGUNA estrategia medida
causalmente: la 1B entra demasiado pronto para que la hora del cruce
discrimine (selección), y el fade que mide la vista A (día completo, con RTH)
no es el fade premarket que la 1B cobra. Sin dato: 5.1 → 1.412 trades 1B
+2,32 % (65 % de cobertura: microcaps sin AH); 5.2/5.3 → los 34 IPOs +12,73 %.

## 4. Cartera

No se hace: nada pasó la puerta de trades (regla declarada: solo para ✅).

## 5. Múltiple testing (acumulado)

**~27 criterios** acumulados. Segundo bloque seguido donde el mejor hallazgo
de universo (aquí 8/8 y parcial −0,24) muere en la puerta de trades: la
vista A mide el DÍA (con RTH dentro) y las estrategias PM cobran un trozo
distinto. Lección que se repite: para la 1B, ningún criterio del día D
(completo) ni del timing intradía ha superado aún a 1.6/3.2 (víspera pura).

## 6. Reproducibilidad

- Factibilidad: `paso0_factibilidad.py` (cobertura cache vs lago).
- Extracción: `paso1_extraer.py` → `velas_b5.parquet` (18,0 M velas: PM del
  día + AH 16:00-19:59 de la víspera, 27.613 pares ticker-fecha).
- Features: `paso2_features.py` → `features_b5.parquet` (c51, t20, t50).
- Vistas: `paso3_vistas.py` → `resultados_A.txt`, `resultados_trades.txt`.
- NOTA de proceso: la primera versión del análisis emparejó entry_time y
  return_pct por ticker-día (producto cartesiano con las pirámides) y dio
  números falsos en la 1B; corregido cargando los trades de sus JSON fuente
  (fila = trade con SU entrada). Los números de este informe son los
  corregidos.

## 7. 5.2-bis — HORA DE INICIO DEL GAP en línea de tiempo continua (16:00 víspera → 09:30), pedido de Álvaro

Misma mecánica que 5.2 pero con el after-hours de la VÍSPERA delante: running
max del high sobre AH(16:00-19:59 de D−1) + PM(04:00-09:29 de D) contra la
`prev_close` persistida; hora del primer cruce de +20 %/+50 %; tramos AH /
04-05 / 05-06 / 06-07 / 07-08 / 08-09:30. Scripts `paso4_gap_inicio.py` →
`resultados_52bis.txt`, `features_b5bis.parquet`.

**Universo (fade PREMARKET primario, n=13.920, todos cruzan +50 % por
definición):**

| Tramo de inicio (+50 %) | n | fade PM | día |
|---|---|---|---|
| AH víspera (16-20h) | 2.294 | 26,4 % | −4,4 % |
| **04-05** | 3.431 | **32,5 %** | −2,2 % |
| **05-06** | 966 | **33,7 %** | +0,1 % |
| 06-07 | 1.257 | 30,8 % | −0,8 % |
| 07-08 | 2.322 | 24,7 % | −3,5 % |
| 08-09:30 | 3.650 | 23,8 % | −3,4 % |

ρ(g50, fadePM) **8/8 negativo** (−0,04..−0,27), pooled −0,156, parcial ctrl
1.6+3.2 **−0,208**. El +20 % como inicio es más flojo (−0,046). **¿Cambia
algo vs el 5.2 sin AH? La conclusión no cambia** (madrugada ≫ tarde, misma
fuerza); lo que añade el AH es una celda nueva con sentido propio: el 16 % de
los gaps del universo YA había cruzado el +50 % en el AH de la víspera, y su
fade queda ENTRE medias (26,4 %) — el gap «de ayer por la tarde» es menos
fresco que el de madrugada pero más que el de última hora.

**Trades (causal CONFIRMADO: 0 de 4.482/11.426/1.656 trades con cruce
posterior a la entrada — la condición de entrada «PM High Gap ≥ 50 en su
vela» lo garantiza):** 1B plana otra vez (ρ +0,014; AH-inicio +2,26 % vs
04-05 +3,76 %: forma sin señal); DT −0,048 3/3 con el mapa completo (tarde
+0,40 % vs madrugada ~+2 %); 2B plano (−0,02). Sin dato: los IPOs de siempre
(34/11/14 trades, +12,7/+7,5/+10,4 %).

**Qué haría falta para construirlo como filtro de dataset («Hora de inicio
del gap»):** no es expresable con columnas de daily_metrics (es intradía).
Dos vías: (a) columna derivada en el ETL del lago — minuto del primer cruce
de +50 % en la línea continua, por ticker-día, computada de las velas 1m
(una pasada offline como la del parquet bygap); viaja luego como cualquier
`lag`/columna de ventana en las tres vías; o (b) indicador de vela en el
motor: «minutos desde que el PM High Gap superó +50 %» (running, causal —
mismo patrón que Elapsed Time Last High). **Dónde tendría más sentido:** en
estrategias que cobran el fade TARDE — fade en la apertura / RTH contra el
máximo premarket (ahí el día completo pesa y es donde la vista A dice que
vive la señal: 33 % vs 24 % de fade); para la 1B/DT tal cual no añade nada.
