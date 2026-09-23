# PRD — Scalping UI: vocabulario de trading, frase-resumen y esquema de la escalera (EJECUTADO el mismo día)

- **Fecha:** 2026-09-23
- **Autor:** Álvaro (decisión y petición: «nombres que no sean una puta mierda,
  coherentes con el lenguaje de trading, más visual, sin cargarse nada») +
  ZCode/GLM (exploración, propuesta de renombres aprobada por AskUserQuestion,
  implementación y verificación).
- **Aplica sobre:** `alvaro-rama-desarrollo`, a la altura del merge de staging
  `f5b1be7` + tags `9016fb1` + docs `039f334`.
- **Tipo:** cambio de PRESENTACIÓN. Cero cambios de comportamiento: el motor,
  las claves JSON del bloque y los payloads son byte a byte los de siempre.
- **No toca el bot de avisos** ni `market_frame.py` ni `strategy_explain.py`
  (futuro, con Jaume — ver §8).
- **Origen de la decisión:** Álvaro quería usar el modo Scalping y aprenderlo,
  pero los nombres («Topo/techo», «core», «recorrido máximo», «rearmar») y la
  falta de referencias visuales lo hacían hostil. Elección explícita entre tres
  opciones de naming (elegida: verbos de trading) y tres niveles de «visual»
  (elegido: esquema + frase-resumen), AskUserQuestion del 23-sep.

---

## 1. Resumen en una frase

El bloque Scalping del builder sigue haciendo exactamente lo mismo, pero ahora
se llama como hablan los traders (Piramidar, Tomar parcial, Promediar, Posición
mínima/máxima, Rango, Repetir niveles), lleva una **frase-resumen en vivo** que
siempre dice lo que hará la estrategia, y en modo escalera un **esquema SVG**
que se redibuja con los valores del formulario.

## 2. Por qué

- Los nombres originales eran de implementación, no de trading: «core (suelo)»,
  «tope (techo)», «recorrido máximo», «rearmar niveles». Ámbiguo además: «core»
  y «tope» no dicen que son el SUELO y el TECHO de la POSICIÓN.
- Las acciones «Añadir/Quitar» no dicen QUÉ estás haciendo en trading: añadir a
  favor es **piramidar**, quitar a favor es **tomar parcial**, añadir en contra
  es **promediar** (martingala — la parte peligrosa, ahora con su aviso).
- No había ninguna pista visual de cómo es una escalera de niveles; el usuario
  tenía que imaginársela leyendo tooltips.
- El vocabulario tenía que ser coherente con el resto de la app («Stop Loss
  Fijo», «Take Profit», «Parciales», «Trailing Stop», «Piramidación» — y la
  palabra «escalera»/«peldaño» ya existe en el TP por lote).

## 3. Mapa de renombres (solo etiquetas visibles; las claves NO cambian)

### 3.1 Parte general (`ScalpingBuilder.tsx`)

| Antes | Ahora |
|---|---|
| Modo (select: Simple / Complejo (escalera)) | Dos botones estilo Take Profit: **«Simple (entra y sale)»** / **«Con escalera»** (subtítulo: piramidar · parciales · promediar) |
| Capital por entrada | **«Tamaño de cada operación»** (% de la cifra del panel) |
| Salida por tiempo | **«Cierre por tiempo»** — el help explicita que es un *time stop* y que con valor > 0 **PISA** el take profit «Tiempo» de la estrategia |
| Pausa tras salir | **«Espera antes de reentrar»** (velas) |
| Timeframe del gatillo / Gatillo | Sin cambio (ya coherentes) |

### 3.2 Escalera (modo «Con escalera»)

| Antes | Ahora |
|---|---|
| Paso | **«Distancia entre niveles»** (%) |
| A favor [Añadir/Quitar] | **«Por cada nivel a favor (+)»** → **Piramidar (añadir) / Tomar parcial (quitar) / Nada** |
| En contra [Añadir/Quitar] | **«Por cada nivel en contra (−)»** → **Promediar (añadir) / Reducir (quitar) / Nada** |
| Core (suelo) | **«Posición mínima»** |
| Tope (techo) | **«Posición máxima»** |
| Recorrido máximo | **«Rango de la escalera»** (% desde la entrada) |
| Rearmar niveles (checkbox) | **«Repetir niveles»**: dos botones **«Una vez por nivel»** / **«Grid (siempre)»** |

Los tooltips se reescriben con el vocabulario nuevo conservando los avisos
importantes: promediar ALEJA el stop (va sobre el precio medio), el cierre por
tiempo pisa el TP-Tiempo, el grid es donde «se ven los costes».

### 3.3 Resumen de definición (`BacktestPanel.tsx`, la línea «SCALPING: …»)

Antes: `salida a los N min · pausa de N velas · N% de la cifra del panel por
entrada · ESCALERA paso X%: a favor añade…, core…, tope…, recorrido…, rearma`.

Ahora: `cierre por tiempo a los N min · espera de N velas antes de reentrar ·
tamaño de cada operación: N% de la cifra del panel · ESCALERA cada X%: a favor
piramida N / toma parcial de N; en contra promedia N / reduce N; posición mín
…, posición máx …, rango ±X%, cada nivel una sola vez / grid: cada nivel opera
en cada cruce`.

### 3.4 Etiquetas del gráfico (`backtest_service.py`, SOLO la cadena `label`)

Antes: `«Escalera nivel 2: añade|quita»`.
Ahora: `«Escalera nivel 2 (a favor): piramida|toma parcial»` /
`«(en contra): promedia|reduce»` — usa el campo `lado` que ya viaja en
`escalera_executions` (portfolio_sim 1808/1849). Las corridas viejas sin
`lado` caen al texto de siempre. La palabra «Escalera» se conserva en todos
los casos (el test `test_escalera.py:288` comprueba esa subcadena).

## 4. Lo visual nuevo (dentro de `ScalpingBuilder.tsx`)

### 4.1 Frase-resumen en vivo

Caja con filete cobre a la izquierda bajo el header, visible con el bloque ON.
Ejemplo real (ganadora «SCALP PM · Fade Escalera 10», modo simple):

> La entrada lógica abre la ventana y la salida lógica la cierra. Dentro, cada
> gatillo abre una operación con el 100 % de la cifra del panel, que cierra por
> objetivo o stop. Antes de reentrar, espera 5 velas.

En modo escalera añade una segunda frase con distancia/acciones/límites/rango/
repetición. Se recalcula en cada cambio del formulario.

### 4.2 Esquema SVG de la escalera (`EsquemaEscalera`, solo modo «Con escalera»)

- Línea de **ENTRADA** al centro (única línea cobre del esquema; el texto nunca
  va en cobre, regla del sistema de diseño).
- Niveles discontinuos **+k·distancia** arriba (A FAVOR, verde) y **−k·distancia**
  abajo (EN CONTRA, ámbar), máx. 3 por lado; a cada lado, la acción en texto
  («Piramidar 10 % pos. inicial», «Promediar 50 $»…). El lado en «Nada» queda
  atenuado con «la escalera no actúa».
- Si el rango recorta más allá de los niveles dibujados: línea discontinua con
  «rango ±X %». Sin rango: «más niveles…».
- Con «Promediar» activo: aviso «cada promedio aleja el stop».
- Nota inferior: posición mín/máx (si > 0), «cada nivel una sola vez» / «grid»,
  y «stop y objetivo sobre el precio medio».
- Simbólico, no a escala; se redibuja en vivo (verificado: rango 5→8 al vuelo).
- Idioma SVG del repo (`BandaLocates.tsx`): tokens de `@/components/ui/tokens`,
  sin hex crudos, `font.mono` para números.

## 5. Ficheros tocados (3)

1. `frontend/src/components/strategy-builder/ScalpingBuilder.tsx` — renombres,
   botones de modo, frase-resumen, esquema SVG, tooltips.
2. `frontend/src/components/backtester/BacktestPanel.tsx` — solo el bloque del
   resumen SCALPING/ESCALERA (líneas ~1714-1745).
3. `backend/app/services/backtest_service.py` — solo la cadena `label` de las
   ejecuciones de escalera en `_build_executions`.

`Chart.tsx` no necesita cambio (pinta `ex.label` tal cual). Los 3 ficheros
fueron leídos ENTEROS antes de tocarlos (regla del repo).

## 6. Lo que NO cambia (garantías)

- **Claves JSON del bloque** (`step_pct`, `favor_action`, `core_amount`,
  `cap_amount`, `max_travel_pct`, `rearm`, `mode`, `ladder`…): intactas. Las
  definiciones guardadas — incluidas las 2 ganadoras de scalping del 18-sep —
  y sus backtests son idénticos al céntimo.
- `scalpingForPayload` (InlineStrategyBuilder) y las 12 propagaciones de
  `page.tsx`: sin tocar.
- El motor (`strategy_engine.py`, `escalera.py`, `portfolio_sim.py`,
  `sim_dispatch.py`): sin tocar.
- `exit_reason == "Escalera"`: sin tocar (7 aserciones de tests lo fijan, y la
  palabra es correcta).
- Comportamiento de campos al vaciarlos: idéntico (p. ej. distancia = 0 ⇒
  escalera desactivada, como el «Paso» original).

## 7. Verificación ejecutada (23-sep)

1. `npx tsc --noEmit` limpio.
2. `pytest tests/test_escalera.py tests/test_scalping.py tests/test_strategy_api.py`
   → **44 passed** (incluida la aserción de etiquetas «Escalera»).
3. Navegador (`next dev` 3000 + backend 8010 del usuario), sobre la estrategia
   guardada **«SCALP PM · Fade Escalera 10 (ganadora 3 años)»**:
   - resumen del panel con el vocabulario nuevo, sin cortes ni solapes;
   - builder modo Simple: frase-resumen correcta (omite «a los N min» porque
     `max_minutes=0`), botones de modo, filas renombradas;
   - modo Con escalera: esquema con niveles ±1/2/3 %, «A FAVOR (+) → Tomar
     parcial 50 % pos. inicial», «EN CONTRA (−) → Promediar 50 %», aviso del
     stop, nota de posición máx 300 %, bracket «rango ±5 %»;
   - redibujado en vivo (rango 5→8).
   - NOTA: el estado en memoria del builder se dejó en modo Con escalera SOLO
     en la pestaña de verificación; la estrategia de la BD sigue en simple.
4. Etiquetas del gráfico: cubiertas por tests (no se corrió un backtest en modo
   complejo; el cambio es una cadena de texto con mapeo lado+kind).

## 8. Pendiente / futuro (requiere OK de Jaume o decisión de Álvaro)

- **`strategy_explain.py` no conoce el bloque scalping** y su salida se pinta en
  el cuadro de mandos del BOT (`CuadroMandos.tsx`, zona cerrada). Añadir
  scalping al explicador + un bloque en el cuadro de mandos: con Jaume.
- **El bot no soporta scalping** (usaría el gatillo como entrada sin cierre por
  tiempo ni espera): sigue PROHIBIDO marcar estrategias scalping para el bot.
- Si el modo Complejo/escalera sigue sin producir ganadoras (la búsqueda del
  18-sep concluyó que las escaleras PERJUDICAN por churn de costes), candidato
  a esconderse tras un «avanzado» o retirarse del panel. El motor se queda.

## 9. Cómo revertir

Es presentación pura: `git revert` del commit del feat devuelve los tres
ficheros a sus textos de antes sin tocar datos ni definiciones. No hay
migración, no hay BD, no hay formato persistido nuevo.
