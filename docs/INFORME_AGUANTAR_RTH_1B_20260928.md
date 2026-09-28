# Informe — Aguantar en RTH y peores operaciones · 1B Sobri 3 (2024-2026)

> Línea priorizada por Álvaro el 2026-09-28 (ORDEN DE TRABAJO §1). Contexto:
> en Portfolio 2025, aguantar el 50 % hasta las 11:00 sube el Sharpe
> (9,51→10,67/10,68) pero duplica el DD (−3,6→−7,6 %) y la exposición
> (28→70 %). Preguntas: ¿en quiénes RESTA aguantar? ¿y qué tienen en común
> las peores operaciones de la 1B en general?

## Datos y método

- **Trades:** baseline 1B (corrida B0, dataset PMH≥50 2024-01-01→2026-09-04):
  4.482 trades, salida actual = parciales 25 %/08:15 + 50 %/08:30 +
  25 %/08:45 (el resto lo cierra el EOD de sesión ~08:44). Sin tocar código:
  trades guardados + velas 1m del lago hasta las 11:00.
- **Métrica «% del camino al stop»** (solo precios, independiente del sizing):
  `camino(p) = (p − E) / (S − E) · 100` con **E = precio medio real de entrada
  (con pirámide)** y **S = stop del trade** (estructura: PMH+10 %). Short: 0 %
  = en la entrada, +100 % = en el stop, negativo = a favor. 1 unidad de camino
  = 1 R.
- **Efecto de aguantar** (por trade, sobre la porción que hoy sale ~08:45):
  simular 08:45→11:00 contra el stop estático (si alguna vela toca S → sale en
  S; si no, cierre de la última vela ≤11:00): `efecto = camino(salida_hold) −
  camino(salida_actual)` en puntos de camino. **Negativo = aguantar AÑADE.**
- Vivos a las 08:45: **3.261** trades (los 1.221 restantes ya habían salido
  por stop). Simulación sin código del motor, sin comisiones (B0 las tiene a 0).

## A1-A2 · ¿En qué trades RESTA aguantar? La variable principal dice: NO HAY corte por camino

Efecto medio de aguantar: **−4,5 camino pp** (mediana −9,7) — a favor en
promedio. Pero la pregunta era el corte por «% del camino a las 08:30»:

| camino a las 08:30 | n | media | mediana | % toca stop |
|---|---|---|---|---|
| < −100 (ya ganó más de 1R) | 331 | **−11,0** | −10,8 | **2,1 %** |
| −100/−75 | 364 | −7,0 | −12,5 | 5,5 % |
| −75/−50 | 676 | −2,6 | −9,7 | 8,0 % |
| −50/−25 | 833 | −3,7 | −9,8 | 9,7 % |
| −25/0 | 654 | −2,4 | −8,5 | 15,3 % |
| 0/+25 | 285 | −6,1 | −5,7 | 22,1 % |
| +25/+50 | 92 | −3,4 | −0,3 | 41,3 % |
| > +50 (cerca del stop) | 26 | −1,6 | +9,7 | 57,7 % |

**Contra-intuitivo pero claro:** los que MÁS ganan al aguantar son los que ya
van ganando mucho (los «recorridos» < −100 son el mejor grupo y casi no tocan
stop: el fade sigue). No existe corte tipo «cortar si ya recorrió más del X %».
El RIESGO de aguantar está en los que van PERDIENDO a las 08:30 (camino > 0:
22-58 % de stops). Pero incluso ahí la media es levemente favorable — el
problema es la cola, no la media. **Por año:** 2024 y 2025 favorecen aguantar
en TODOS los tramos; **2026 es otro régimen** (aguantar hace daño en los
tramos intermedios: +3,6/+5,1/+12,7) — ojo con eso.

## A3 · Las auxiliares: el VWAP del premarket es EL discriminador

| precio vs VWAP PM a las 08:30 | n | media efecto | % stop |
|---|---|---|---|
| < −15 % | 1.040 | −5,1 | 2,4 % |
| −15/−8 % | 861 | −6,6 | 6,7 % |
| −8/−4 % | 470 | −6,5 | 11,7 % |
| −4/0 % | 398 | −2,9 | 18,6 % |
| 0/+4 % | 273 | **+1,3** | 27,5 % |
| > +4 % | 219 | **+0,4** | **41,6 %** |

La prueba definitiva de que manda la ESTRUCTURA y no el P&L propio:
«ganando pero SOBRE el VWAP» (n=213): efecto **+6,9**, 32 % de stops — el peor
grupo para aguantar; «perdiendo pero BAJO el VWAP» (n=128): −7,1, 16 % —
se aguanta tranquilo. (Correlacionado: caída desde el PMH > −15 % a las 08:30
también separa: +3,5 de media, 36 % stops.)

Las demás (todas causales, medidas a las 08:30):
- **vol$ del premarket**: monótono — más volumen, mejor aguanta (<5 M$: −1,2 ·
  >150 M$: **−14,1**).
- **días desde IPO**: <365 d mejor (−7,6/−14,3/−8,8) que viejas (−2,5/−3,2).
- **hora de inicio del gap**: nacidos en el AH de la víspera los mejores
  (−9,8); los de 05-06 h los peores (+2,5); los tardíos (07-08:29) más stops
  (16,5 %).
- precio, shares en circulación, gappers activos +50 %: flojos o nulos (el
  contador de gappers vuelve a no separar — coherente con la invalidación del
  7.2b).

## La regla

> **Aguantar (hasta las 11:00 o stop) solo lo que a las 08:30 sigue ≤ 4 %
> DEBAJO del VWAP del premarket. Lo que esté en o sobre el VWAP, cerrarlo a
> las 08:45 como hoy.**

Añadir «y días desde IPO < 365» la afina (los dos mejoran; el IPO joven aguanta
mejor) — versión estrecha, n=633.

## A4 · Cartera a igual riesgo por año (lineal, 1R/trade, sin componer)

Método: `R_política = r_multiple − frac_última_porción · efecto_hold/100` donde
la política aplica; días con trades; exposición = minutos medios con posición
abierta por día. Validación del método: el «no aguantar» 2025 da **Sharpe 9,51
— el mismo número que tu Portfolio**; el aguantar-todo 10,20 vs tu 10,67.

| año | política | ΣR | Sharpe | MaxDD (R) | min con posición |
|---|---|---|---|---|---|
| 2024 | no aguantar | +73,6 | 6,67 | −2,3 | 261 |
| 2024 | **regla VWAP≤−4 %** | +84,1 | **7,42** | −2,0 | 381 |
| 2024 | aguantar TODO | +85,2 | 7,54 | −2,7 | 395 |
| 2025 | no aguantar | +120,2 | 9,51 | −3,4 | 273 |
| 2025 | **regla VWAP≤−4 %** | +130,2 | **10,08** | −3,1 | 403 |
| 2025 | aguantar TODO | +131,3 | 10,20 | −3,0 | 409 |
| 2026 | no aguantar | +101,5 | **10,29** | −3,8 | 270 |
| 2026 | **regla VWAP≤−4 %** | +98,4 | 10,28 | −3,8 | 402 |
| 2026 | aguantar TODO | +97,1 | 10,16 | −3,7 | 406 |

Refinamiento **regla + IPO<365 d**: Sharpe 6,91 / 9,74 / 10,43 — la única
variante que mejora al «no aguantar» en los TRES años (ΣR +77,3/+123,5/+102,3).

- La regla se queda a ~1 punto de camino del «aguantar todo» en Σ pero con la
  MITAD de stops (5,8 % vs 11,6 % de los aguantados) y menos exposición.
- **Sobre tu DD real (−7,6 %):** en unidades R el DD no explota al aguantar
  (−3,4→−3,0 R en 2025) — tu duplicación del DD viene del sizing en $ (cada
  stop duele más que 1R con posición real). El mecanismo que la regla ataca
  es exactamente ese: **menos stops** (los stops del hold caen 11,6 %→5,8 %,
  y en los excluidos «sobre VWAP» eran 27-42 %).

## B5 · Las peores operaciones de la 1B en general (peor 10 % = 448 trades, 444 por stop, ΣR −237)

> **CORREGIDO el 28-sep tarde (look-ahead detectado por Álvaro — es mi propio
> hallazgo 18 aplicado a mi análisis).** La primera versión de esta sección
> usaba el **PMH FINAL del día** (que los propios perdedores empujan hacia
> arriba al subir hasta el stop) y «piramidó» (pasa DESPUÉS de entrar). Con el
> PMH final, el peor 10 % parecía tener gaps monstruosos (mediana +166 % vs
> +96 %) y una exclusión «pmh≥200 % ∨ (≥150 % ∧ vol<5 M$)» parecía quitar
> −54 R. **Todo eso era un artefacto.** Re-hecho abajo SOLO con lo conocido en
> el minuto de entrada o antes: PM High Gap % ACUMULADO hasta la vela de
> entrada, Current Gap % al precio de entrada, vol$ del premarket HASTA la
> entrada, caída desde el PMH-hasta-entonces, precio vs VWAP-hasta-entonces,
> hora de entrada, primera/reentrada, variables de la víspera (1.6 neto RTH,
> 3.2 retorno), shares, días IPO, gappers a la entrada.

Medido en R (= camino acumulado) con la salida actual. Qué hacen a la ENTRADA
frente al resto (mediana):

| variable CAUSAL a la entrada | peor 10 % | resto |
|---|---|---|
| **vol$ premarket hasta la entrada** | **3,4 M$** | 6,1 M$ |
| · tramo <3 M$ | **45,3 %** | 32,6 % |
| · tramo ≥20 M$ | **1,6 %** | 15,1 % |
| **neto RTH víspera (1.6)** | **+17,4 %** | +10,1 % |
| · tramo ≥40 % | **38,1 %** | 31,4 % |
| **hora de entrada <04:30** | **50,4 %** | 34,4 % |
| **primera entrada (no reentrada)** | **90,4 %** | 76,5 % |
| caída desde el PMH-acumulado a la entrada | −19,1 % | −14,9 % |
| precio vs VWAP (hasta la entrada) | −3,0 % | −0,3 % |
| shares (mediana) | 2,5 M | 4,8 M |
| **PMH Gap % ACUMULADO a la entrada** | +87,5 % | **+84,5 % (= NADA)** |
| Current Gap % a la entrada | +56 % | +57 % (= nada) |
| días IPO / gappers activos a la entrada | ≈ igual | ≈ igual |
| piramidó *(descriptivo, post-entrada — no filtrable)* | 70,8 % | 58,3 % |

**Lo que queda en pie (causal):** el peor 10 % se CONCENTRA en el premarket
fino (vol$ <3 M$ a la entrada), víspera RTH fuerte, primera entrada temprana
tras una caída ya grande desde el PMH. La celda más enriquecida: **vol<3 M$ y
víspera RTH ≥+40 %** (20,1 % del peor-10 vs 12,7 % del resto, 1,6×).

**Lo que NO sobrevive:** el «gap monstruoso». Con el PMH acumulado HASTA la
entrada, el peor 10 % tiene +87,5 % vs +84,5 % del resto (nada) y el tramo
causal ≥200 % es de los MEJORES (+0,146 R de media). **Ninguna exclusión
causal quita un grupo perdedor** — todas las candidatas dejan fuera grupos
POSITIVOS (+16 a +87 R):

| celda causal | n | % del peor-10 | % del resto | R medio de la celda |
|---|---|---|---|---|
| vol<3 M$ ∧ víspera RTH ≥+40 % | 603 | 20,1 % | 12,7 % | **+0,025** (3/3 años) |
| vol<5 M$ ∧ 1ª entrada ∧ <04:30 | 1.141 | 37,7 % | 24,1 % | +0,052 |
| vol ≥20 M$ (control «rico») | 945 | 8,0 % | 22,5 % | **+0,070** |

**Conclusión honesta de la Parte B:** no hay regla de EXCLUSIÓN gratis a la
entrada (el look-ahead la fabricó). Lo que sí hay es un gradiente de edge por
liquidez medido causalmente: de **+0,025 R/trade** (premarket <3 M$ con
víspera ≥+40 %) a **+0,070 R/trade** (vol ≥20 M$) — ≈3× de diferencia. La
acción correcta es **tamaño/prioridad de poder de compra** (más pequeño o
último en la celda fina-fuerte-víspera; tamaño pleno en premarket rico), no
excluir. Coherente con el uso ya validado de 6.1 y 3.2 como priorizadores.

## Conclusiones

1. **No cortes por «cuánto recorrió»** — al revés de lo esperado, lo muy
   recorrido es lo MEJOR de aguantar. El filtro útil es estructural: **el
   precio debajo del VWAP del premarket**.
2. Regla: aguantar solo si a las 08:30 precio ≤ VWAP−4 % (+ opcional IPO<365 d
   para blindar 2026). MISMA suma que aguantar-todo con la mitad de stops y
   algo menos de exposición — y en $ debería comerse mucho menos DD que el
   aguantar-todo de Portfolio.
3. Lo que NO separa: el propio % camino, el precio, las shares, el contador de
   gappers (re-invalida 7.2b por la vía práctica).
4. Peores operaciones = premarket fino (vol$ <3 M$ a la entrada), víspera RTH
   fuerte (≥+40 %), primera entrada temprana. Con variables causales NO hay
   exclusión gratis (la de «gaps monstruosos» era look-ahead): hay un gradiente
   de edge +0,025 R (celda fina-fuerte) → +0,070 R (vol ≥20 M$) → usar como
   TAMAÑO/prioridad, no como exclusión.
5. 2026 advertencia: aguantar sin filtro fue MALO ese año (solo la versión con
   IPO<365 d se mantuvo positiva).

*Construcción (si Álvaro la quiere): la salida condicional «a las 08:30,
si precio ≤ VWAP_PM−4 % aguantar hasta 11:00/stop; si no, cerrar» no existe
hoy como primitiva del motor (parciales por hora sí; condicionar el parcial a
una condición de vela, no). Tocaría `strategy_engine`/simulador — ficheros
compartidos con el bot: decisión de Álvaro + aviso a Jaume antes de nada.*

## Verificación manual vela a vela (28-sep noche, tras la lección de los 3 falsos)

Petición de Álvaro: comprobar la regla del VWAP a mano en ~20 trades concretos
antes de plantear nada a Jaume, porque los tres últimos resultados
espectacares de GLM eran artefactos (gap÷ATR y peores-trades por look-ahead,
mañanas calientes por cruce de datos). Hecho sobre las velas CRUDAS con
recalculo independiente (`verifica_vwap.py` en scratch):

- **19/19 trades recalculan IDÉNTICO** (VWAP, precio 08:30, camino, stop del
  hold y efecto: Δ=0.000 en todos). Muestra adversarial: los 4 peores efectos
  del grupo regla (stops reales al aguantar), los 4 mejores del grupo
  sobre-VWAP (lo que la regla se ahorra), frontera, y casos de velas ralas.
- **Familias de artefacto descartadas globalmente:** (a) stop estático de
  estructura confirmado — S = PMH_a_la_entrada·1,10 en el 96 % (mediana
  1,0000); (b) 0 velas duplicadas en 6,7 M; (c) precio fresco: 99 % con vela
  EN las 08:30 y 95 % con vela en las 11:00 (>15 min rancio: 0,1 %);
  (d) el edge NO vive en los rancios — con vela fresca en 08:30 (n=2.344) el
  efecto del grupo regla es −6,0 con 5,8 % de stops.
- **Qué NO prueba esto:** que la regla gane ejecutada de verdad. Verifica que
  el CÁLCULO es fiel a las velas (sin artefacto de datos). Queda pendiente el
  backtest en la app, que exige la salida condicional («aguanta solo si…») →
  motor compartido → decisión de Álvaro + aviso a Jaume. Hasta entonces, la
  regla sigue en estado «prometedora, sin verificar en la app».

## Gestión por hora (28-sep noche) — «a una HORA, si CONDICIÓN, ACCIÓN» (línea nueva de Álvaro)

Herramienta GENÉRICA pedida por Álvaro. Primero el dato: combinaciones de
HORA (08:30/09:00/09:30) × CONDICIÓN (precio vs VWAP-PM a esa hora:
encima/debajo/≥4 % debajo; % camino: a favor >15 % / 0-15 % / en contra;
cruces) × ACCIÓN (cerrar todo / cerrar 50 % / stop a BE=entrada / nada), sobre
la porción que hoy sale ~08:45. Para 09:00/09:30 el mundo es «aguantar»
(presuponen extender la sesión a 11:00). Métrica: camino pp de la porción y
cartera 1R lineal por año; comparado contra salida actual y aguantar-todo.

### El mapa (Δcamino de la porción vs no hacer nada; negativo = la acción GANA)

1. **La hora de gestionar es las 08:30.** A las 09:00 la señal se ha
   debilitado (wsup: −1,2) y a las 09:30 no queda nada consistente (todo
   favorece aguantar: cerrar sale +2 a +12 PEOR). Decidir tarde = no decidir.
2. Las celdas que separan a las 08:30 (cerrar todo vs aguantar):
   - **«a favor PERO sobre el VWAP» (cf15∧wsup, n=128): −9,1** — la más
     afilada: ganas >15 % del camino pero el precio recuperó el VWAP.
   - **Álvaro-(i) «sobre el VWAP y por debajo de la entrada» (n=214): −7,5**.
   - wsup genérico (n=517): −2,9 · winf: cerrar +7,3 PEOR (aguanta) ·
     cf15: cerrar +6,7 PEOR (no cortes ganadores).
3. **Álvaro-(ii) no sale bien**: cerrar todo lo que no esté >15 % a favor
   tira +2,5 de media por trade regalado (los 0-15 % a favor y hasta los en
   contra aguantan mejor la media — el daño está en la cola, no en la media).

### Cartera por año (1R lineal; «else» = aguantar a 11:00 con stop original)

| política (todas a las 08:30) | 2024 ΣR/Sh | 2025 | 2026 | ΣR 3a | Δ vs current | stops* | siguen >08:45 |
|---|---|---|---|---|---|---|---|
| current (salida actual) | +73,6/6,67 | +120,2/9,51 | +101,5/10,29 | +295,3 | — | 0 | 0 % |
| aguantar TODO | +85,2/7,54 | +131,3/10,20 | +97,1/10,16 | +313,6 | +18,3 | 403 (12,2 %) | 100 % |
| **P3 sobre-VWAP→cerrar** (n=517) | +86,0/7,62 | +130,9/10,19 | +98,6/10,31 | **+315,5** | +20,2 | **212 (−47 %)** | 84 % |
| **P4 no ≥4 % bajo VWAP→cerrar** (= regla VWAP de §A, n=915) | +84,4/7,45 | +130,2/10,07 | +98,4/10,35 | +313,0 | +17,7 | **138 (−66 %)** | 72 % |
| **P2 sobre-VWAP→BE** (idea (i) de Álvaro; n=517) | +86,2/7,66 | +131,1/10,14 | +98,0/10,22 | +315,2 | +20,0 | convierte: 171 salen al BE, 303 cierre inmediato (ya >E), 43 aguantan | 84 % |
| P1 cf15∧wsup→cerrar (la celda afilada, n=128) | +86,3/7,63 | +131,2/10,20 | +97,6/10,18 | +315,1 | +19,8 | 359 | 96 % |
| P5 Álvaro-(ii) cf15→BE, resto cerrar | +82,7/7,32 | +126,3/9,73 | +99,0/10,36 | +308,0 | +12,7 | — | — |

*porciones que acaban en stop (S o BE) de las 3.290 gestionadas. La variante
exacta de Álvaro-(i) (solo los que están a favor) da 315,6 — idéntica a P2/P3
(entre sí son ruido de ±2 R en 3 años: elegir por perfil de riesgo, no por Σ).

**Lectura:** todas las políticas VWAP se quedan el Sharpe del aguantar-todo
con MENOS stops (la causa del DD en $ de Portfolio) y algo menos de
exposición. P4 es la más defensiva (2/3 de los stops fuera, 72 % de
exposición), P3/P2 el equilibrio, P1 la más quirúrgica (toca 128 trades en 3
años y aún así +19,8 R vs current). La (ii) de Álvaro, descartada.

**Verificación (regla fija 3): 20/20 trades adversariales recomputados a mano
de las velas crudas — precio 08:30, VWAP y las tres salidas del BE (inmediato,
stop en E, 11:00) IDÉNTICOS.** (El resto del pipeline ya estaba verificado
19/19 en la sección anterior.) Regla 2 aplicada: un trade = una fila con clave
(ticker, fecha, minuto de entrada), sin duplicados; cierre a vela rancia
descartado (99 % fresca a las 08:30).

### Qué permite YA la app y qué falta (para el futuro PRD a Jaume — sin escribir código)

**Existe hoy:** parciales por HORA (`HOUR:08:30` — incondicionales) · salida
total por hora (take_profit Hour) · trailing stop por % con activación (por
precio, sin disparador horario) · stops por estructura/fijos · y **VWAP/AVWAP
ya son indicadores de condición** (la CONDICIÓN de esta línea es expresable
hoy en entradas).

**Falta la pieza genérica «salida programada condicional»**: un plan de reglas
`(hora, condición-de-indicador, acción)` evaluado por vela sobre la POSICIÓN
abierta, con acciones: {cerrar X % · mover el stop a un nivel (BE/precio/otro
indicador) · nada}. Hoy las salidas programadas no consultan estado, y los
stops no tienen disparador horario ni condición. Vive en el gestor de posición
(`strategy_engine`/simulador, compartido con el bot) → decisión de Álvaro y
aviso a Jaume antes de construirla. Con esa pieza, P2/P3/P4 y la regla VWAP
del §A son UNA sola configuración de la herramienta.
