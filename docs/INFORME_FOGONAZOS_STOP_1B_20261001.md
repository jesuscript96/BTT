# Informe — Fogonazos vs stop de la 1B: ¿nos protege el StopLimitP donde lo ponemos?

> **Para:** Álvaro (estudio pedido 2026-09-30; re-hecho 2026-10-01 con el PM del nivel B
> **causal** — la versión anterior contaminaba el PM con el futuro y se descarta).
> **Rol:** pruebas y análisis (protocolo REPORTAR, NO ARREGLAR). Cero cambios de código del repo.
> **Datos:** cinta consolidada Massive (todas las bolsas + TRF, marca de ejecución y de
> publicación, filtro de prints limpios <10 ms) + XNAS.ITCH trades/mbp-10 y EQUS.MINI mbp-1
> (Databento). 126 ticker-días de fogonazo + 201 SL normales de validación.
> **Coste:** 2,23 $ de 25 $ autorizados.
> **Unidades:** las tablas trade a trade van en **% de la posición** del trade correspondiente
> (y entre paréntesis, R de distancia al stop V0). El balance de la Fase 4 va en la **unidad
> del motor** (PnL por $ de nocional desplegado, entrada + añadido), que es como el motor cuenta.

## 0. La pregunta de Álvaro: ¿qué habría pasado en los 3 trades reales con fogonazo?

En 2,7 años (4.473 trades de la 1B), **3 posiciones reales vivieron un fogonazo ≥×2 limpio en
≤60 s**: PLYX (17-feb-2026, ×23 sobre la entrada), SLGB (9-jun-2026, ×10) e IMCC (2-jun-2025,
×2,2). Su PM sale del CSV (Stop/1,10) y no depende del arreglo del nivel B. Con el stop actual
en PM+10 % y límite PM+65 %:

| Trade | Variante | ¿Qué pasa? | % fuera a 1 s / 5 s / 60 s | Precio medio salida | Pérdida (% posición) |
|---|---|---|---|---|---|
| **PLYX** (entra 3,40) | **V0 PM+10 % (stop 4,25)** | **Le pilla el fogonazo** | **0 % / 0 % / 6,5 %** | **6,15 $ «a la vuelta»** | **−80,9 %** (2,38 R) |
| PLYX | V1 PM (stop 3,86) | Le pilla el fogonazo | 100 / 100 / 100 % | 3,99 $ | −17,4 % (0,52 R) |
| PLYX | V2 PM−1 % (stop 3,82) | Le pilla el fogonazo | 100 / 100 / 100 % | 3,99 $ | −17,4 % (0,51 R) |
| PLYX | V3 PM−5 % (stop 3,67) | Saltó antes del fogonazo | 100 / 100 / — | 3,70 $ | −8,8 % (0,26 R) |
| SLGB (entra 0,758) | V0 | Saltó antes del fogonazo | 100 / 100 / — | 1,00 $ | −31,6 % (0,74 R) |
| SLGB | V1 | Saltó antes | 100 / 100 / — | 0,94 $ | −24,1 % (0,56 R) |
| SLGB | V2 | Saltó antes | 100 / 100 / — | 0,94 $ | −24,1 % (0,54 R) |
| SLGB | V3 | Saltó antes | 100 / 100 / — | 0,90 $ | −18,8 % (0,42 R) |
| IMCC (entra 9,17) | V0 | Le pilla el fogonazo | 100 / 100 / 100 % | 11,86 $ | −34,7 % (0,85 R) |
| IMCC | V1 | Le pilla el fogonazo | 100 / 100 / 100 % | 11,49 $ | −30,6 % (0,71 R) |
| IMCC | V2 | Le pilla el fogonazo | 100 / 100 / 100 % | 11,49 $ | −30,6 % (0,70 R) |
| IMCC | V3 | Le pilla el fogonazo | 100 / 100 / 100 % | 11,28 $ | −28,2 % (0,65 R) |

**En lenguaje llano — PLYX con el stop de hoy:** la entrada real fue **3,40 $ a las 06:04**. A
las 06:34:51 el precio de mercado (3,27 $, el nivel desde el que arranca el fogonazo) se
despega y sube hasta 76 $ en un minuto. El stop dispara en 4,25 $ y la compra límite a 6,37 $
**casi no llena durante la subida** (el ask pasa de largo: 0 % a 1 s, 0 % a 5 s, solo el 6,5 %
a los 60 s). El resto sale **«a la vuelta»**, cuando el precio se desploma por debajo de
6,37 $: precio medio **6,15 $ = −80,9 % de la posición** (−2,38 R). Con el stop en el PM
exacto (3,86 $) la misma posición sale en el primer segundo a **3,99 $: −17,4 %**. Con PM−5 %
ni llega al fogonazo: salta antes, en el ruido de la mañana, y pierde −8,8 %.

**Nota sobre el fill de V1 por debajo del trigger** (3,99 $ < 3,86 $ del trigger... el promedio
queda en 3,99 $, ligeramente por encima; el primer tramo llena por debajo): el print que cruzó
3,86 $ a las 06:35:38,667 fue un **print aislado** — la cinta a su alrededor, un segundo antes
y después, estaba a 3,73-3,75 $ (prints limpios, retraso 0-0,3 ms). El StopLimitP dispara por
último precio, pero el precio de la límite lo pone el mercado del momento: la orden aterriza
+250 ms después y llena en 0,56 s contra el ask real, que había vuelto a 3,7-3,9 $, y remata a
medida que el precio retoma la subida. Un fill por debajo del trigger no es un error: es lo
normal en un stop limitado cuando el print de disparo no representa al mercado.

## 1. Lo mismo en los 15 fogonazos representativos del universo (nivel B, posición hipotética)

Con **PM causal** (máximo de velas M1 totalmente cerradas antes del arranque — sin mirar el
futuro), el stop V0 **dispara en los 15 de 15**: ya no hay «fogonazos que nacen en el máximo
del día y no te tocan» (eso era un artefacto de la versión anterior, que contenía el propio
pico en AEHL, GLE, SPHL y XHG). R final emparejada y su equivalente en % de la posición
hipotética:

| Grupo | Stop | R mediana | R peor | % posición mediana | % posición peor |
|---|---|---|---|---|---|
| **B·PURO (4)** | V0 PM+10 % | 1,11 | 2,95 | −32,3 % | −88,1 % |
| | V1 PM | 0,90 | 1,12 | −23,5 % | −26,3 % |
| | V2 PM−1 % | 0,67 | 1,05 | −21,7 % | −25,0 % |
| | V3 PM−5 % | 0,58 | 1,05 | −19,1 % | −25,0 % |
| **B·SUBIDA (11)** | V0 PM+10 % | 1,20 | 2,12 | −26,7 % | −70,2 % |
| | V1 PM | 0,59 | 1,46 | −14,9 % | −41,5 % |
| | V2 PM−1 % | 0,59 | 1,46 | −13,1 % | −41,5 % |
| | V3 PM−5 % | 0,59 | 1,46 | −13,1 % | −41,5 % |

Detalle trade a trade de los 15 episodios × 4 variantes en `f3_emparejada.csv` (mismas
columnas que la tabla de arriba: destino, % a 1/5/60 s, VWAP, % de posición).

## 2. Muestra y método

- **Nivel A**: los 3 trades reales (§0). PM = el del trade (Stop/1,10, verificado 50/50 contra
  velas M1 en la Fase 0). Sus números no dependen del arreglo del nivel B: los R simulados son
  idénticos en todas las pasadas (PLYX V1: 0,6974 R antes y después).
- **Nivel B**: de 27 episodios de fogonazo ≥×2,0 confirmado con ticks se quitan 3 con el stop
  causal por debajo de la entrada (ABTS, SBET, ULY: premisa muerta) y 9 fuera del rango real
  de distancia entrada→stop de la 1B (p10-p90 del CSV: +16,8 % a +46,2 %; fuera: CIIT +59 %,
  GLE +57 %, SPHL +63 %, XHG +6/+15 %, GXAI +3 %, HIND +10 %, SGBX +55 %, FRTT +17 %).
  **Quedan 15** (§1), todos entre +19 % y +36 %.
- **PM causal** (nivel B): máximo de velas M1 del lago **totalmente cerradas antes del
  arranque del fogonazo** (apertura + 60 s ≤ t0). Verificado a mano en CIIT (0,61 $) y AEHL
  (17,09 $).
- **Simulación StopLimitP**: disparo por último print (D1), último print limpio (D2) o ask
  NBBO ≥ T (D3); latencia 0 / 250 ms / 1 s (tablas a 250 ms); límite L = 1,5×T; la ejecución
  consume el 50 % de cada print **pagando max(print, ask NBBO vigente ≤60 s)** y nunca por
  encima de L; los días sin cobertura NBBO caen a precio de cinta (marcados).
- **Fogonazo**: t0 < t1 con t1−t0 ≤ 60 s y P(t1)/P(t0) ≥ 2,0 sobre prints limpios, con la
  posición abierta. 27 episodios confirmados antes de filtros.

## 3. Validación del modelo de ejecución (201 SL normales sin fogonazo)

| Regla | mediana | p95 | colgados |
|---|---|---|---|
| v1 (solo cinta; optimista) | ×0,9992 | ×1,0270 | 0 |
| **v2.1 (paga el ask; tope en L; fallback si el día no tiene NBBO)** | **×1,0069** | **×1,0828** | **0** |

Coincide con los 454 fills reales del socio (×1,007 / ×1,07). Los 10 «colgados» de una pasada
intermedia eran un artefacto de cobertura NBBO en 2024 (días con 0-1 quotes), no stops reales
sin ejecutar; con el fallback quedan resueltos.

## 4. El otro lado: coste en días normales (motor real, mismo dataset y rango que el CSV)

Mismo dataset (7.659 pares, 2024-01→2026-09), FIXED 1 $ + pirámide 1 $, sin costes,
`look_ahead_prevention: true`, todo explícito, cambiando solo `hard_stop.offset_pct`.
Verificado en la salida: stop usado = PM×(1+offset) exacto en las 4 corridas.

| Variante | Año | Trades (de V0: −inv/+reent) | % SL | Exp %/trade | ΣPnL | DD cuenta |
|---|---|---|---|---|---|---|
| **V0 +10 %** | 2024 / 25 / 26 | 1.392 / 1.831 / 1.250 | 26,8 / 27,4 / 27,6 | +2,04 / +2,95 / +3,73 % | +41,5 / +107,2 / +101,3 $ | −5,07 $ total |
| | **Total** | **4.473** | **27,3 %** | **+2,888 %** | **+323,62 $** | (−0,05 % s/10k) |
| V1 0 % | 2024 / 25 / 26 | 1.705 (−53/+366) / 2.252 (−97/+518) / 1.548 (−66/+364) | 46,6 / 47,3 / 47,9 | +1,61 / +2,28 / +2,28 % | +27,4 / +51,4 / +35,3 $ | −4,98 $ total |
| | **Total** | **5.505** | **47,3 %** | **+2,074 %** | **+313,89 $** | |
| V2 −1 % | 2024 / 25 / 26 | 1.737 (−69/+414) / 2.302 (−110/+581) / 1.577 (−72/+399) | 49,1 / 49,6 / 50,6 | +1,74 / +2,38 / +2,40 % | +30,2 / +54,9 / +37,8 $ | −4,90 $ total |
| | **Total** | **5.616** | **49,7 %** | **+2,187 %** | **+322,05 $** | |
| V3 −5 % | 2024 / 25 / 26 | 1.983 (−180/+771) / 2.570 (−260/+999) / 1.795 (−160/+705) | 62,9 / 61,9 / 62,5 | +1,30 / +1,86 / +1,91 % | +25,8 / +47,9 / +34,3 $ | −4,29 $ total |
| | **Total** | **6.348** | **62,4 %** | **+1,701 %** | **+280,80 $** | |

Sanity vs Jaume v5: %SL del −1 % = 49,7 % vs 27,3 % del +10 % (él midió 50 % vs 30 %). ✓

### Balance final (unidad del motor: PnL por $ de nocional; corrección tick lote a lote)

| Variante | Σ Rnoc motor | Σ Rnoc con ticks | Extra por deslizamiento de SL no modelado |
|---|---|---|---|
| **V0 +10 %** | 129,2 | **128,5** | +14,0 $ (4,3 % de su PnL) |
| V1 0 % | 114,1 | 113,9 | +25,3 $ (8,1 %) |
| V2 −1 % | 122,8 | 122,6 | +26,7 $ (8,3 %) |
| V3 −5 % | 108,0 | 107,7 | +35,2 $ (12,5 %) |

El motor llena todos los SL exactamente a T; con el deslizamiento real (~×1,0069) las
variantes cercanas —que disparan el doble o más— se resienten más que V0. La corrección tick
de los 3 trades con fogonazo mueve ±0,7 puntos: **los fogonazos son 3 en 2,7 años; lo que
decide es el coste en días normales, y ahí V0 gana en expectancy, en PnL total y neto de
deslizamientos.** La contrapartida, vista en §0: cuando el fogonazo es de los grandes (PLYX),
V0 se come un −81 % de la posición frente a −17 % de V1. Es el precio de la protección de cola.

## 5. Fantasmas, halts y preguntas para el bróker/DAS

- **Fantasmas** (FATBB ×2, KELYB; 2026; 2 dentro de posiciones reales): cruces del trigger
  por prints publicados 2-4 h tarde mientras el ask real estaba en otro precio. La límite
  ancha acabó ejecutando contra el mercado real a precio bueno — el daño de un fantasma no es
  el fill, es **que te saca de una posición que no debía salir**. RIESGO condicionado a que
  DAS dispare por último precio/SIP: no es un hecho.
- **Halts**: 0 dentro de los fogonazos (premercado sin LULD); los LULD llegan después, en RTH.
- **Preguntas** (enlazadas con 19 y 22 de `docs/BOT_EJECUCION_PREGUNTAS.md`): (19) ¿el feed de
  DAS es SIP completo (con TRF/dark) o solo Nasdaq? (22) ¿qué precio exacto dispara el
  StopLimitP (último SIP, último Nasdaq, bid/ask) y un print tardío fuera de secuencia,
  ¿puede dispararlo? (3) ¿en premercado el trigger usa el último print de cualquier horario?
  (4) ¿el stop residente se convierte en límite en el servidor de DAS (latencia ~0) o viaja al
  mercado? (5) ¿qué hace DAS con el stop residente en un halt T1 de premercado?

## Artefactos

- Datos con licencia: `.tmp_fogonazos/massive/`, `.tmp_fogonazos/databento/` (fuera de git).
- Scripts y tablas: `.tmp_fogonazos/f3_*`, `f4_*` (motores v2.1, muestra causal, emparejada,
  validación, backtests y balances).
- Coste Databento: 1,9652 $ + 0,2695 $ = **2,2347 $**. Massive: 0 incremental.
