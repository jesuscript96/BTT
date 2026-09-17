# MEMORIA — Álvaro × Claude (edgecute_app / BTT)

> Documento vivo. Se actualiza **cada sesión** en la que tocamos algo. Entradas
> por fecha, **lo más nuevo arriba**. Sirve para retomar con contexto: qué
> hicimos, por qué, qué decidimos y dónde lo dejamos.

---

## Estado actual del proyecto

- **Repo:** `edgecute_app` (monorepo BTT, GitHub `jesuscript96/BTT`).
- **Rama de trabajo de Álvaro:** `alvaro-rama-desarrollo` → integra a `staging`.
  Sailor: `sailor-rama-desarrollo`. **`main` NO se toca jamás** (producción con
  clientes de pago). Push solo con confirmación explícita de Álvaro.
- **Entorno local:** `DB_PROVIDER=local`, `DISABLE_GCS_SYNC=true`,
  `LIVE_SCREENER_ENABLED=false` (obligatorias; aíslan de producción).
- **Datos:** `daily_metrics` = **tabla** en `backend/local_data.duckdb` (~61 GB),
  **19.177.136 filas, 2019-01-02 → 2026-08-14**. Lago Parquet aparte en
  `.../TRADING APPs/cangrejo_data/datos/parquet/edgecute/`.
- **Nunca commitear** secretos ni datos: `.env`, `gcs-key.json`, `*.duckdb`,
  `data/`, `.cache/`. Ya en `.gitignore`.

## Reglas de trabajo entre Álvaro y Claude

- **No profundizar de más.** Si algo funciona en local y no aporta, se cierra.
- **No llenar `staging` de mierda.** Lo que funciona en local en
  `alvaro-rama-desarrollo` se queda ahí salvo decisión explícita de subir.
- Sailor también puede subir a `staging`; no somos los únicos.
- Esta memoria se actualiza al final de cada sesión con cambios.

---

## 2026-09-17 (Sailor, Backtester + Portfolio) — EV fijo por rango de precio, la puerta auditada, calendario y Monte Carlo del escalado, y la piramidación de Álvaro (SL por lote + camino) integrada

Sesión larga con el bot de alertas encendido casi todo el día: el backend se tocó en disco y se relanzó SOLO cuando Jaume lo apagó (16:36, y 17:16 tras la integración). Todo en `sailor`, commits locales; **sin subir** hasta que Jaume lo pida.

### La puerta por EV: auditoría y «EV fijo» (completo o por rango de precio)

- **Auditoría (portfolio crudo, R fijo 200 $, locates aleatorios 1-10 compartidos):** sin puerta 131.188 $; con EV rodante de 30 trades 94.732 $ (2.188 cortos fuera que, hechos, daban +33.551 $ netos). La causa no es el coste: el movimiento medio del corto es 3,40 % con desviación 22,75 %, así que el EV rodante de 30 trades lleva un error típico de 4,15 %, mayor que el propio EV: **rechaza por rachas, no por el trade** (1.362 de los 2.188 rechazados tenían un fade ≤ 3 %). Un EV fijo ≈ 3,5-4 % (el movimiento medio) da 146 k (+12 %); el EV histórico (ventana 0) 136,8 k.
- **Dos modos y nada más (decisión de Jaume):** `EV rodante` (Trades | Días, con el EV por defecto hasta tener historia; ventana 0 = todo el histórico) y `EV fijo` (siempre el EV que pongas: el que midas en IS para probarlo en OOS). El fijo es **completo** (un EV) o **por rango de precio de entrada** (0-0,5 / 0,5-1 / 1-3 / 3-5 / 5-10 / >10 $): cada corto se compara con el EV del tramo de su precio.
- **UNA definición para todos** (`locates_gate.py`): `RANGOS_PRECIO_EV`, `rangos_ev_normalizados`, `ev_fijo_para_precio(ev_completo, rangos, precio) -> (ev, "rango"|"completo")`, `ConfigPuerta(modo, ev_fijo_pct, ev_rangos)`; `evaluar` resuelve los dos modos y devuelve `ev_origen`. La usan el backtest (`ev_gate_by = "fijo"`, `ev_gate_fixed_pct`, `ev_gate_ranges`; resumen `ev_gate` con modo/ev_fijo_pct/ev_rangos), el portfolio crudo (`gate.mode = "ev_fixed"`, `ev_ranges`), el cuadro de mandos del bot (columna `ev_rangos_json` en `bot_alert_watch`, migración en `ensure_watch_table`; seis casillas junto al EV) y el `/evf` (dice «del tramo de precio»). El bot NO se tocó: importa estos módulos del backend y los coge al arrancar.
- **Semántica del tramo vacío:** en el backtest «por rango» no viaja EV completo (`ev_gate_fixed_pct: 0`): un tramo sin número = **en ese tramo no se entra** (0 > fade es falso, también con fade 0). En el cuadro de mandos sí hay EV de la estrategia y el tramo vacío cae a él. Como Jaume «siempre pone números», las seis casillas se precargan con el EV completo al pulsar «Por rango» (solo las que estén en blanco).
- **Panel de costes opcionales** (tras su queja de que los botones «se comían la frase»): el check «Puerta por EV» va solo; debajo «Con qué EV» con Trades | Días | Fijo; en Fijo, Completo | Por rango; en Por rango desaparece la casilla del completo y los seis tramos van **uno por fila** (el panel mide ~245 px: una rejilla 3×2 desbordaba a 478 px, medido). Casillas alineadas con las demás del bloque.
- **Charts → «EV por precio»** (`tabs/EvPorPrecio.tsx`): el EV de la estrategia (media del movimiento a favor en % del precio, antes de locates) y barras por tramo con su n, para anotar los valores y ponerlos en la puerta y en el cuadro de mandos.
- **Locates por rangos con EV fijo, en los dos sitios** («no te preocupes por el coste»): Backtester → Banda de locates → bloque 3 (`RangosLocatesBacktest.tsx`: relanza la última petición por cada rango, sin puerta y con EV fijo, un backtest por fila EN SERIE con «parar tras este»; tabla + calendario de la fila; OJO: cada fila se autoguarda en «Últimas pruebas»; columna «Vetos» = veredictos negativos, uno por vela con señal, no por trade) y Portfolio crudo paso 3 (`RangosLocatesCrudo.tsx`, contra `/raw`, 0,3 s por fila). Probado en vivo: PM 1A, 1-10 $: sin puerta −2.402 $ (locates 23.057 $); EV fijo 4 % +849 $ (locates 1.590 $).
- Verificado tras el reinicio con la API: por rango 87 trades / completo 4 % 41 / 2 % 0 / sin puerta 282 (junio 2026, PM 1A); `ev_gate.modo = "fijo"` con los seis tramos; ida y vuelta de `ev_rangos` por `/api/bot-alerts/watch` (restaurado después); `/evf` con tramo y con respaldo.

### Portfolio «En crudo»: calendario y Monte Carlo del escalado, «hasta qué precio compensan»

- Paso 4 (escalado): sub-pestañas Curva (% / $ / R) · **Calendario** (`CalendarioCrudo`, profits / gastos / profits−gastos) · **Monte Carlo** (bootstrap COMPUESTO sobre los retornos diarios de la simulación escalada, `McResultado.tsx` compartido con el del paso 3).
- Paso 3: bloque **«Locates — hasta qué precio compensan»** (`locates_analysis` de `/raw`): precio de equilibrio por paquete = PnL de los cortos antes de locates / paquetes (11,62 $; RTH 19,5, PM 10,8; pagado medio 5,70), por estrategia, curva neto vs precio del paquete, tramos de fade y la tabla de EV fijo con «usar». El pool compartido corre también con modo «none» (precio 0) para contar paquetes.
- Pendiente de Jaume: el **cruce real-simulado** (Kelly sobre su curva real; CSV con operaciones sueltas y PnL, sin estrategia) — diseño en la memoria del asistente, a la espera del CSV.

### Integrada la piramidación de Álvaro (rama `alvaro-rama-desarrollo`, 15-16 sep) — SIN romper nada nuestro

Jaume pidió mirar «memoria madre» / la rama de Álvaro: había dos funciones nuevas de piramidación, con PRD, en su rama (no en la memoria madre de sailor): **SL por lote** (`docs/PRD_SL_POR_LOTE_EN_PIRAMIDACION_20260915.md`: cada añadido con su propio stop, por % o por estructura, congelado en la vela de señal; cierra SOLO ese lote, PnL contra el precio del lote; `exit_reason: "Pyramid Lot Stop"`) y el **camino de condiciones** (`docs/PRD_CAMINITO_CONDICIONES_PIRAMIDACION_20260916.md` + `PRD_CAMINO_REARME_DISPARO_DESCARTADO_20260916.md`: un nivel con `steps`, una lista ORDENADA de árboles; cada paso engancha en su turno por flanco y el nivel dispara al engancharse el último; `same_bar`; rearme al disparar aunque el añadido se descarte por caja/locates). Ambos son opt-in por nivel: sin `lot_stop`/`steps` el compilado y la simulación son idénticos.

- **Cómo se integró:** cherry-pick de sus 6 commits (044c720, 9ba49bd, 4014f36, 2fbbe5a, 5f19ef9, 099a189) sobre sailor, resolviendo a mano los conflictos con nuestros grupos/recorrido del 16-sep (`strategy_engine` compila `group/sequential/move/def_index` también en un nivel-camino — si no, un camino perdería su grupo en silencio; `portfolio_sim` detecta el disparo en dos ramas: nivel normal como siempre y camino con su bucle de pasos). **El recorrido del precio va pegado al ÚLTIMO paso del camino** (`_recorrido_cumplido`, helper a nivel de módulo): los pasos intermedios no lo miran; test `tests/test_camino_con_recorrido.py` (5). Frontend: `nivelPiramideValido` (PyramidingBuilder) entiende camino, recorrido o condiciones, y es la única definición (InlineStrategyBuilder y StrategyForm la importan); tarjeta del panel = grupo + recorrido + SL del lote + camino.
- **Los dorados de Álvaro se recongelaron** (`test_lot_stop_nivel`, `test_pyramid_steps_nivel`): su hash del compilado con pirámide era el de SU rama; en sailor cada nivel lleva desde el 16-sep las claves de grupos. Comprobado que el hash nuevo es EXACTAMENTE el que sailor daba antes de integrar nada (mismo `compile_strategy_def` viejo cargado aparte).
- **Regresión real, trade a trade:** `PM (A) - Principal + 2 piramidada` ene-jun 2026 (893 trades con añadidos de pirámide, 37.319,95 $) y PM 1A abr-jun con locates + puerta fija (22 trades): **idénticos** antes y después de la integración (firma de cada trade y de cada ejecución, y todas las métricas agregadas). Suite: **1.394 passed** (1.278 antes + las suyas 116 + 5 nuevas), tsc limpio.
- **También traído (17:40, Jaume: «sí sería un bug»):** el fix `70ff4d7` de «Config. Estrategia guardada abre la estrategia ANTERIOR» (abres Config con A, eliges B, corres B, Config abre A y se queda pillado; y «Guardar en el Baúl» proponía reescribir B con A). El borrador recuerda de qué estrategia desciende (`builderDraftOriginId`); correr otra lo jubila. Nuestro «Nueva Estrategia» se adaptó (miraba `loadedStrategyId`, que el fix elimina): arranca en blanco si hay estrategia activa o borrador con origen. Verificado en el navegador con la secuencia exacta: ahora abre B. **NO traído** (no era piramidación): su visor modal de trade (3575d3a).
- Ojo: `git fetch` de este repo solo trae `sailor` y `staging` (refspec recortado); la rama de Álvaro se trae a mano: `git fetch origin +refs/heads/alvaro-rama-desarrollo:refs/remotes/origin/alvaro-rama-desarrollo`.

### Tarde (18:00-18:40): tres cosas más de Jaume

- **El recorrido dentro de un camino va como PRIMER paso** (Jaume: «¿no puede ser el primer paso, como una condición inicial, y cuando se cumpla ya pasa a la siguiente?»). Sí: `move.pos = "first"` (por defecto) = el recorrido es un paso más, engancha por flanco y, cumplido, da paso al siguiente aunque luego el precio se vuelva; `"last"` = se exige en la vela del disparo, pegado al último paso (lo que había hecho yo primero). En la UI, con el camino encendido y «recorrido del precio», un desplegable elige dónde va (`move_pos`); la tarjeta lo dice «(1º paso)» / «(en el disparo)». Tests en `test_camino_con_recorrido.py` (7). Los niveles normales no cambian (regresión trade a trade de PM (A), que lleva un nivel por recorrido: idéntica).
- **EV = el CAMINO DEL PRECIO tras la señal, independiente del capital (segunda vuelta, 18:50).** Con el PnL sobre el nocional, Jaume vio el EV de todos los tramos NEGATIVO con la ejecución «fijo en $» y POSITIVO con «% del equity» para el mismo backtest («el EV debería ser independiente del dinero que meto»). Causa: con pirámides que añaden «% del equity» sobre una base fija en $, los añadidos dominan la posición y el precio medio (y el PnL) dependen del tamaño. Definición final de `locates_gate.movimiento_pct`: del **fill de la entrada** (`entry_price`, no el precio medio) al **precio medio de todas las salidas** ponderado por acciones (`precio_salida_medio`, piernas exit/reduce/lot_stop de `executions`; el crudo lo precalcula como `exit_vwap` en el registro recortado), bruto, sin comisiones ni locates. Verificado en PM (A) (893 trades con pirámides): «fijo 100 $» y «1 % del equity» dan el MISMO EV por tramo (4,54 / 4,33 / 4,45 / 7,67 / 9,01 %; media 5,64 %), mientras que por PnL/nocional daban 1,78 % vs 2,21 %. El «ponderado» se quitó (dependía del capital). Es el número que se enfrenta al fade del locate en la entrada.
- **BUG REAL en el EV en sombra y en «EV por precio»: el movimiento se medía con el precio de la ÚLTIMA pierna.** Los trades llegan agrupados (parciales, quitas de pirámide, SL de lote en una fila) y `exit_price` es solo el de la última salida: con un take profit parcial a buen precio y el resto a EOD peor, el trade «ganaba dinero» pero el movimiento salía negativo. Jaume lo vio en Charts («EV negativo en casi todos los rangos y la estrategia es ganadora: imposible»). Afectaba a `locates_gate.sombra_desde_trades` (la puerta rodante del backtest), a `portfolio_lab_raw._sombra_de` (la del crudo) y a `EvPorPrecio.tsx`; el bloque «hasta qué precio compensan» ya iba por PnL/nocional (por eso sus 3,40 % no cuadraban con la sombra). Arreglo: UNA definición, `locates_gate.movimiento_pct(trade)` = (pnl + comisiones) / (precio medio × acciones), que es exactamente la magnitud que se compara con el fade (el coste del locate sobre ese mismo nocional); sin pnl/size cae al precio de salida. El frontend la calca. Test en `test_puerta_ev_fijo.py`. **OJO: los números de la auditoría de la mañana sobre el EV rodante (94.732 $, «rechaza por rachas») se hicieron con la medida mala**; la conclusión de fondo (el EV de 30 trades es ruidoso) sigue, pero conviene repetir la comparación rodante vs fijo con la sombra corregida. PM 1A entero: EV 4,68 % (todos los tramos positivos: 3,46 / 4,34 / 4,44 / 4,62 / 6,90 %).
- **«EV por precio» rehecho** (Jaume: ejes ilegibles y solapados, gráfico muy ancho, quería más barras): barras de 0,5 $ hasta 20 $ (+ «> 20») en divs (sin SVG estirado), línea del cero, etiqueta del eje cada 2 $, hover con tramo/EV/n, barras claras con < 20 trades; a la derecha la tabla con los seis tramos de la puerta (los números que se copian) y arriba el EV medio y el ponderado por nocional.
- **Panel de la puerta, v3:** los selectores Trades | Días | Fijo y Completo | Por rango van solos, cada uno en su fila a todo el ancho debajo del check (se comían «Con qué EV»); el EV completo en su fila etiqueta | casilla.

### 19:00 — el «no entra en ninguna» era la trampa de las tres capas, no el EV

Jaume corrió PM (A) (4 % del equity, locates 1-20 $, «Fijo → por rango» con sus EV) y la puerta rechazó los 45.934 veredictos. En la corrida guardada: `ev_gate_fixed_pct: 0`, `ev_gate_ranges: None`. `backtester/page.tsx` copia los parámetros del panel campo a campo en TRES sitios (borrador, definición y estrategia guardada) y a esa lista le faltaban los dos campos nuevos; mis pruebas por API sí los mandaban, por eso no lo vi. Arreglado (`b8002b4`) y verificado desde la interfaz (llegan los seis tramos; con 3 % en todos y 100 $ fijos por trade acepta 139 de 4.430: con posiciones de 100 $ un paquete entero de 1-10 $ es un fade del 1-10 %, los paquetes son enteros). Fórmula del fade confirmada a Jaume: `paquetes × precio_paquete / acciones / precio × 100` (un paquete entero = precio del paquete / 100 por acción). Camino + recorrido: fuera el desplegable, el recorrido va SIEMPRE primero (decisión suya).

### 19:10-19:40 — Puerta por EV / MFE / Fade (el enfoque nuevo de Jaume)

Jaume: «quizás lo sensato no es verlo desde el EV»: quiere enfrentar al fade necesario del locate, a elegir, el **EV**, el **MFE medio** (lo máximo que el precio se movió a favor desde la entrada hasta la salida final) o el **Fade medio** (lo que se movió a favor desde la entrada hasta la salida FINAL, la última pierna), todo desde la primera entrada e ignorando pirámides; con las mismas opciones que el EV (Trades | Días = rodante de esa medida, Fijo = completo o por rango) y el valor por defecto en la misma unidad.

- **Backend, una definición** (`locates_gate`): `METRICAS_PUERTA`, `normaliza_metrica`, `fade_salida_pct` (entry_price → exit_price), `mfe_pct` (el `mfe` del simulador: desde el fill de la entrada, % del precio, acotado por el stop/TP ejecutado; con parciales el mayor de las piernas cubre la vida entera), `metrica_trade(t, metrica)`; `sombra_desde_trades(trades, metrica)` construye la sombra con la medida pedida y `ev_rodante_pct` hace el rolling igual que siempre; `ConfigPuerta.metrica`; el veredicto y el resumen `ev_gate` llevan `metrica`. Backtest: `BacktestRequest.ev_gate_metric` ("ev" | "mfe" | "fade"). Crudo: `RawGateIn.metric`, `_sombra_de(run, metrica)`.
- **Frontend**: Charts → «EV · MFE · Fade por precio» (toggle para las barras, tabla con las tres columnas por tramo y los tres totales de la corrida). Costes opcionales → «Puerta por EV/MFE/Fade»: primera fila EV | MFE | Fade, luego lo de siempre; «EV/MFE/Fade por defecto (%)» y «… fijo (%)» siguen a la medida. `ev_gate_metric` en el panel, en `api_backtester.ts` y en las TRES copias de `page.tsx`. Portfolio crudo: toggle de medida junto a rodante/fijo (`gateMetric`, `RawGateIn.metric`). Tabla de rangos: etiqueta según la medida.
- Verificado: desde la interfaz llega `ev_gate_metric: mfe` y el resumen dice `metrica: mfe`; por API en junio (PM 1A, rodante 30 trades): EV 158 aceptados / MFE 271 / Fade 161 (el MFE es mayor → pasan más). Test `test_las_tres_medidas_de_la_puerta_ev_mfe_fade`. Suite 1.398.
- Con la configuración real de Jaume (PM (A), 4 % del equity, locates 1-20 $, fees 5 pb, slip 0,3 %): sin locates +273 M (compuesto, liquidez infinita); con locates aleatorios y SIN puerta **−100 %** (los locates se lo comen); con la puerta por rango con los EV de la tabla **+5.108 %**, DD −21,6 %, 2.577 trades de 4.449. Los paquetes son ENTEROS: con posiciones pequeñas el fade de un paquete es enorme (100 $ a 5 $ = 20 acciones, pero pagas el paquete de 100: 5 %).

### 19:50 — Charts con las tres medidas en todos los visores

Jaume: «en Charts sigo viendo solo EV». Ahora la medida se elige en cada visor de la primera fila con las MISMAS definiciones por trade que la puerta (`EvPorPrecio.metricaTrade`): **Rolling** con R | EV % | MFE % | Fade % (el «%» de antes miraba la última pierna y el precio medio con pirámides: ya es el EV bueno; con MFE/Fade la media simple, sin separar por el signo del PnL, porque el MFE nunca es negativo); **por tiempo** y **por día** con $ (el PnL medio de siempre) | EV | MFE | Fade, un selector para los dos; y «EV · MFE · Fade por precio» con su toggle. La tabla de rangos de la banda de locates también elige la medida y completo/por rango (`0ad1f14`).

### Trampas del día

- **Dos sesiones en el mismo repo:** mientras yo encadenaba cherry-picks, la sesión del bot commiteó en sailor (`9f17b65`, `edc9c8d`, 17:04). No pasó nada porque cada uno añadió sus ficheros por ruta, pero es una carrera real: **nunca `git add -A`** con otra sesión viva, y leer MEMORIA.md justo antes de escribirlo.
- **Nunca `git stash`** (lo prohíbe Jaume): se me escapó uno el 17-sep por la mañana dentro de una comprobación, `stash pop` inmediato y sin efecto.
- El guardián de memoria del backend (`BACKTEST_MIN_AVAIL_GB=1.0`) devuelve 503 con Chrome + Claude + el backend a 5 GB tras recargar la caché; se pasa solo en un par de minutos.
- El backtest de una estrategia GUARDADA usa las fechas de su universo (`universe_filters.date_from/to`), no las del panel: 7.504 pares aunque el panel diga junio.

## 2026-09-16 (Sailor, Portfolio) — «En crudo» en cuatro pasos, locates de la cuenta, Kelly exacta por estrategia, y el ATR del día entero

Todo el día sobre Portfolio → «En crudo», con el bot vigilando por la mañana (backend en worktree, frontend en sitio) y apagado por la tarde (fusión + tres reinicios del 8010). Commits `67c8b3f` (ATR), `2a1a2c6` (En crudo) y esta MEMORIA, subidos a `sailor-rama-desarrollo` y `staging` por orden de Jaume. Suite: 1.273 pasados, 0 fallos.

### La página, en cuatro pasos

Jaume: «me pierdo en datos y gráficas… quiero un flujo de trabajo que se intuya, diseño técnico estilo Genético, nada de minimalismo extremo». `CrudoTab` es ahora solo el hilo: una tira arriba con los pasos y cuatro cajas numeradas y plegables con su resumen (`Paso`, `PasoBar`, `SubTabs`, `Nota` en `hoja.tsx`): **1 Ejecución** (tabla por estrategia + bloque «Portfolio — la cuenta»), **2 Visión general** (pestañas Resumen · Exposición · Por estrategia · Correlación · Calendario), **3 Límites de pérdida** (histórico + Monte Carlo + banda de locates), **4 Escalado y pesos**. Los pasos 2-4 no se abren sin calcular el 1. Un fichero por paso (`PasoEjecucion`, `PasoVision`, `PasoMonteCarlo`, `PasoEscalado`) y los cálculos puros en `modelo.ts`.

### Locates de la cuenta (motor `portfolio_lab_raw` v2)

Jaume: «si contamos los locates separados los estamos sobrecontando… la RTH sería gratis porque ya se han pagado en premercado». El modelo de locate pasa al bloque Portfolio (un bróker para todas; las filas ya no llevan locates). **Compartidos**: por ticker-día se alquila una vez el máximo de acciones en corto *a la vez* sumando estrategias (barrido al minuto); la que cubre libera; la que cabe en lo alquilado va gratis; paga la que provoca el paquete de más. **Puerta por EV**: la misma cuenta que `locates_gate` (EV en sombra de *su* estrategia contra el fade necesario de los paquetes *de más* respecto a lo alquilado hoy por cualquiera). **Banda**: N semillas sobre los mismos paquetes, sin volver a simular (como `locates_banda`). Sin el bloque, el motor es idéntico al anterior (probado contra el commit `75cd028` con corridas sintéticas). Con las reales (R fijo 200 $): por estrategia 76.338 $ vs compartidos 66.549 $ (−13 %, 1.532 entradas gratis); la puerta con EV 2 % quita 1.635 cortos y *baja* el retorno (rechaza entradas tras rachas malas que luego eran buenas), como en el backtester.

**Los «90 M de locates sobre 150 M de beneficio» no eran un bug.** Con R fijo: 459 acciones de media a 6,68 $ (nocional 1.067 $), a 3 $ el paquete el locate medio es 11,58 $ = 1,08 % del nocional, contra 44,84 $ de PnL medio por corto → 26 % del bruto; con aleatorios 1-10 $, 50-60 %. Las corridas se guardaron sin locates (la página lo pide así) y por eso nunca lo había visto. Pregunta abierta: qué paga de verdad por paquete.

### Escalado: de HRP a «solo Kelly» (tres versiones en un día)

- **v2 (mañana)**: Kelly del conjunto repartida por HRP/iguales/momentum/EV/DD, con la regla que dictó Jaume («si Kelly dice 5 % y tengo 5 estrategias, cada una 1 %»: la suma = Kelly ≤ tope).
- **Auditoría (noche)**, pedida por él («hay algo que no debe estar bien»): tres bugs y una lección. (1) **Monte Carlo con DD de −40.000 %**: remuestreaba los $ de cada día en modo aditivo sobre una curva que compone; ahora remuestrea el retorno diario y compone (`mode: "compound"`, `risk_pct: 1`) → DD p95 −18 %. (2) **«25 % (topado)» con tope 10 %**: el periodo guardaba lo pedido tras el techo interno del 25 % heredado de Modelos; ahora guarda `x_pct` (pedido) y `applied_pct` (aplicado) y el gráfico pinta lo aplicado; el techo interno está fuera. (3) **Kelly μ/σ² se pasaba**: ahora `_kelly_exacta` (la f que maximiza la media de log(1 + f·R) sobre los días de la ventana, acotada por el peor día); hoy 11,9 % vs 21,2 % de la aproximación, que se enseña al lado. **La lección**: con estas curvas (liquidez infinita, PF 1,7, 8,6 trades/día) el crecimiento sube con el riesgo hasta el 15 % sin encontrar óptimo, y **Kelly entera sin tope arruina** (−100 %): la óptima del pasado sobre-apuesta el futuro. El tope no afina, hace realista el resultado; aviso en pantalla cuando Kelly > 15 %. Verificado trade a trade que el riesgo aplicado = capital del día × aplicado × peso.
- **«Con el escalado gano menos que con compound»** era semántica: el % del escalado era el TOTAL repartido y el de las filas es POR ESTRATEGIA; y la pestaña Modelos multiplica Kelly por el número de estrategias (X × n × w). Explicado con números; Jaume: «ahí me columpié».
- **v3 (noche, la que queda)**: **solo Kelly, HRP fuera** (reparte por varianza, no por edge: dio el 86 % a la PM por estable y bajó el crecimiento; y su objetivo es «más peso a la que mejor vaya»). `kelly_scope`: **de cada estrategia** (Kelly exacta propia × fracción; si la suma pasa del tope, recorte *proporcional* de todas: la mejor sigue llevando más) o **global** (Kelly del conjunto × fracción, topada, repartida por las Kellys propias). Fracción libre (`kelly_mult` hasta 3) con botones ¼ ½ óptima. Real, ¼ y tope 10 %: RTH 28,8 % y PM 11,9 % de Kelly propia → piden 7,19 + 2,97 → 7,08 / 2,92 (71/29); crecimiento 7 %/día frente a 1,9 %/día de las filas al 1 %; DD −48 %. Ahora la RTH lleva más (mejor Kelly propia): lo contrario que con HRP. Le conté la literatura sin inventar: Kelly/Thorp sólido y fraccional por ruido; HRP (López de Prado 2016) es de riesgo; «Kelly + HRP» era heurística mía.
- «Desde el inicio» en % / $ / R; «Hoy» = tabla Kelly propia → × fracción → aplicado → $ → peso. Todo es RIESGO (lo que se pierde al stop), no nocional: lo pone la pantalla porque Jaume lo leyó como «exposición».

### El ATR del stop, desde la primera vela del premercado

Jaume: «tiene que coger todas las velas desde el inicio de premarket, independientemente de la sesión» (= lo que ya hacía el bot). Ninguna versión miraba el futuro; el backtest recortaba a la sesión ANTES de calcular y en RTH las 14 primeras velas iban sin ATR (respaldo o sin entrar). Ahora `backtest_service` usa la columna `atr` de `market_frame` (día entero, recortada con la sesión, como hod/vwap) y `backtest_signals` calcula `_atr_full` y recorta; misma receta que el VWAP del 15-sep. `test_stop_atr_dia_entero.py`: el stop = entrada + k × ATR de la vela de la SEÑAL (no la de relleno), hay entradas entre 09:30 y 09:43 que antes no existían, y los tres caminos + JIT coinciden.

### Trampas del día

- `_ts` del motor crudo espera `YYYY-MM-DD HH:MM:SS` con espacio; con «T» todo cae a medianoche y los solapes desaparecen sin error.
- Comparar «por estrategia» vs «compartidos» con R en % del capital no vale: el compound cambia los tamaños entre corridas y parecía que el pool cobraba MÁS.
- `_hrp_weights` devuelve None (pesos iguales para todas) si una columna no tiene varianza; por eso «viva» = con trades en la ventana.
- El worktree sale con CRLF; los parches conservan el final de línea del fichero. Y la herramienta Bash volvió a comerse `\n` dentro de un script: los parches van por fichero.
- **PENDIENTE que Jaume dejó dicho: revisar mañana todo lo metido hoy en «En crudo»** (locates de la cuenta, puerta, banda, Monte Carlo, escalado Kelly v3) — se suma a la auditoría suya pendiente desde el 14-sep.

---

## 2026-09-16 (Sailor, noche) — Piramidación por grupos, disparo por recorrido, y una cantidad por pirámide en el bot

Pedido de Jaume: (1) «tres pirámides donde dos sean secuenciales y una individual» — el modo era uno solo para toda la lista; (2) que una pirámide pueda añadir o quitar «si X % de recorrido del precio (no de la vela), a favor o en contra», como un take profit / stop loss de la propia pirámide; (3) que el bot de alarmas y el cuadro de mandos pidan el riesgo de CADA pirámide. Commits `c2c1b5d`, `1121289`, `960cc26` en `sailor-rama-desarrollo`; sin subir al escribir esto. Backend relanzado a mano con el bot parado.

### Grupos y recorrido (compilador → traductor → simulador)

- **JSON:** cada nivel lleva `group` (índice) y `pyramiding.groups[g].mode`; `trigger: "move"` + `move_pct` + `move_dir` (favor/contra) + `move_ref` (entry/last). **Sin `groups`, todo es el grupo 0 con el `mode` de siempre**: las estrategias guardadas se compilan y simulan igual (test). El compilador mete `group`, `sequential`, `move` y `def_index` EN EL NIVEL para que el simulador no cruce dos listas (las tres capas otra vez).
- **Semántica:** grupos independientes; dentro de un grupo secuencial solo vigila el primer nivel con veces. El recorrido se mide con el cierre de cada vela respecto al precio de entrada o al del último añadido/quita **de su grupo**; cruzar el umbral es un evento (flanco); con condiciones además, AND; la orden en la vela siguiente; la ventana de entradas se aplica también. Un nivel solo por recorrido ya no necesita condiciones (antes se descartaba en silencio: `nivelPiramideValido` en `InlineStrategyBuilder` es la lista blanca del frontend).
- **Lo que salió probando en real** (estrategia del GA + G1 secuencial «+3 % a favor, otro +3 % desde el añadido» y G2 «quita 50 % si 4 % en contra», 2 semanas, 115 ejecuciones cruzadas con las velas del gráfico): con «desde el último disparo» = cualquier nivel, una quita del G2 reseteaba la escalera del G1 (7 de 115). Ahora es por grupo: 111/111 cuadran. Test que falla con la semántica anterior.
- **UI:** `PyramidingBuilder` por grupos (modo por grupo, «+ Añadir pirámide al grupo N», «+ Añadir grupo»); en cada pirámide «Dispara por: condiciones | recorrido del precio» con dirección, % y desde dónde. La descripción del panel lo cuenta.
- OJO al leer un resultado de `run_backtest`: las ejecuciones de pirámide van en `trade["executions"]` (kind add/reduce, label «Pirámide N: añade»); `pyr_executions` se quita al fusionar. Me costó un rato pensar que no disparaba nada.

### Riesgo por pirámide en el bot y el cuadro de mandos

`bot_alert_watch.riesgos_piramide_json`: lista JSON, una cantidad por pirámide en el orden de la definición guardada (`def_index`: la lista compilada descarta niveles inválidos y su índice no vale). Prioridad: por nivel → `riesgo_piramide_usd` global (respaldo) → la estrategia. `/bot-alerts/strategies` describe las pirámides (`describir_piramides`: grupo, modo, añade/quita, cantidad, disparo) y el cuadro pinta una casilla por pirámide (P1·G1 +), prellenada con el global de antes si no hay lista. `_niveles_con_riesgo(niveles, global, por_nivel)` y `_kwargs_simulate` llevan la lista; la firma de recompilación también.

Tests: 15 + 7 nuevos; suite 1.273 pasados, 0 fallos.

---

## 2026-09-17 (Sailor, bot de alertas) — 38/38, el cuadre confirmado en real, un aviso de Telegram perdido y la auditoría del 1008

Bot 09:51→15:46 (parado por Jaume), sin reinicios. **38 avisos = 38 en la base = 38 en el cuaderno** (`D:/bot_senales/logs/bot_2026-09-17.log`, 285 líneas), 0 timeouts, 0 errores, 14 admisiones al radar con «evaluada como ACTUAL». **Primer día en real del cuadre de cantidades (`3b87b62`)**: DAIC entra 492 → stop cierra 492; pirámides KXIN 422+365=787, DCX 1.363+953=2.316, RETO 435+448=883; tramos 25/50/25 % de lo avisado sumando exacto (KXIN 197+394+196). PM 1A: 5 posiciones, 5 pirámides, 3 oleadas de TP (14:16/14:31/14:46), stop RETO 14:25. RTH 1B: 6 entradas, 3 pirámides; al parar quedaban 5 abiertas en el simulador (AEMD, BIAF, KXIN, WETO, TURB). AEMD sin señal fue correcto: la única vela de fade (06:49 NY) estaba un 54 % bajo el máximo PM (14,00 real) y «% Fade < 30» la descartó.

### Un aviso de Telegram perdido y el bot parado 10 s (arreglado, SIN subir)

14:31: cinco tramos 2 del TP a la vez; el de **KXIN (cierra 394 de 787 @ 1,76)** → `[TELEGRAM] fallo de envio: timed out` a las 14:31:13. `enviar_texto` era UN intento con 10 s de tope, **sin reintento y en línea**: mientras esperaba, el bot no procesaba (MKDW salió 10 s tarde; latencia p99 12 s ese minuto). Arreglo en `bot_alerts_telegram.py`: `_post` (un intento; 4xx no se reintenta, timeout/5xx sí), `enviar_con_reintentos` (3 intentos, esperas 2 s y 4 s, log «enviado al intento N» o `ERROR PERDIDO tras 3` con el texto), cola + **un solo hilo** `telegram-envio` (`encolar` vuelve al instante y mantiene el orden), `pendientes_de_envio`, `vaciar(30)` al cerrar, contador `perdidos`. `bot.py` (fuera de git) usa `tg.encolar` en `al_avisar` y en las prealertas, y vacía la cola en el `finally`; el modo reproducción y las respuestas a comandos siguen síncronos. 8 tests (`test_bot_alerts_telegram_cola.py`); 211 de bot_alerts pasan. Entra en vigor con el siguiente Vigilar.

### El 1008 «límite de conexiones»: auditoría intensa, causa FUERA de este PC

Hoy otra vez, 10:01:28 y 10:02:38 (70 s). Con el 10-sep (10:02:39) y el 16-sep (10:01:35 y 15:43:59): **siempre a las 04:01–04:02 NY, apertura del premercado, con cero o un reintento y luego nada**; Massive echa a la conexión vieja (el bot) y se queda la nueva, el bot reconecta en 1 s y echa al otro. Un servicio con reconexión normal daría ping-pong todo el día: esto es una máquina con horario. Descartado en el PC con datos: el feed abre UN socket; `CuadroMandos.tsx` habla con el backend (`/bot-alerts/live`), no con Massive; el **screener heredado** (`live_screener_service.py`, `A.*` del mercado entero, reconecta 1–60 s) está apagado por `LIVE_SCREENER_ENABLED=false` y el backend vivo lo confirma (`ws_connected: False`); ningún otro proceso ni tarea; `validar_datos_vivo.py` es manual. **Las claves**: en `.env` hay UNA sola clave de API (el mismo valor en `MASSIVE_API_KEY`, `MASSIVE_BOT_API_KEY` y `MASSIVE_S3_SECRET_KEY`); la «de websockets» que Jaume cree tener no está; y el límite es **por cuenta** (1 conexión al cluster de acciones). Hipótesis principal: la producción de Edgecute (mismo linaje de código, `LIVE_SCREENER_ENABLED` encendido por defecto, alojamiento serverless que solo avanza cuando recibe peticiones). **Preguntas para Álvaro**: (1) ¿producción arranca `live_screener_service` y con qué `LIVE_SCREENER_ENABLED`? buscar `[LIVE] Massive WS connected` y `1008` hacia las 04:01 NY; (2) ¿qué clave/cuenta de Massive usa?; (3) ¿dónde está alojado? Borrar nuestro screener NO lo arregla (ya no conecta). Sin daño real: dos cortes de 2 s antes de que haya posiciones.

### Grabaciones y el spread

8 sesiones (8→17 sep), 577.963 agregados por segundo, 17.452 velas 1m, 58 tickers, 27 MB, solo tickers del radar y con el bot encendido. **El spread se puede reconstruir a posteriori**: `/v3/quotes/{ticker}` del plan actual devuelve bid/ask por sesión (probado, 200). Pendiente un script fuera del bot que baje las cotizaciones de cada ticker-día grabado y las resuma por segundo (filtrar bid/ask a 0 en premercado); Jaume prefiere hacerlo ya para validar los datos antes de invertir el mes.

## 2026-09-16 (Sailor, bot de alertas) — Día de 55 avisos sin un fallo, y las cantidades que no cuadraban

Bot arrancado desde la página a las 09:49 y parado por Jaume a las 16:31. **55 avisos = 55 en Telegram = 55 en la base = 55 en el cuaderno**. **0 «timed out»** (ayer 22): el `/estado` en memoria hace lo que tenía que hacer. El cuaderno nuevo (`D:/bot_senales/logs/bot_2026-09-16.log`, 354 líneas) tiene el día entero y de él sale la auditoría. 14 admisiones al radar, todas con «evaluada como ACTUAL». PM 1A: 7 posiciones y 21 tramos de TP en tres oleadas simultáneas (14:16, 14:31, 14:46), 21 de 21. RTH 1B (riesgo 150) muy activa. Al parar quedaban 7 posiciones RTH abiertas en el simulador (avisado a Jaume: sin bot no hay avisos de sus salidas).

Dos cortes `1008` «límite de conexiones de la cuenta» (10:01 y 15:43): algo más se conectó a Massive con la misma clave; el bot reconectó en 2 s sin perder velas. Pendiente saber qué es.

### Las cantidades no cuadraban: «entra 284, cierra 289» (`3b87b62`)

Jaume: «debe salir con las mismas que entra, y si ha añadido pues con las que toque, al igual que con los parciales. Las cantidades deben estar cuadradas». El aviso de entrada dimensiona con el cierre de la vela de señal; el simulador interno rellena en la apertura siguiente y calcula SUS acciones con ese precio; salidas y pirámides salían del simulador. Medido hoy: MEDS RTH 284→289, RETO 208→210, MEDS PM 507+359=866 pero «posición 890», JZXN 449+486=935 pero tramos 232+464+232=928. Sin error ni log (caso 13 de «bugs que no dan error»).

Arreglo en `bot_alerts_engine` (`_cuadre`): la posición **avisada** es la verdad. El motor apunta las acciones del aviso de entrada (enteras) por vela de señal; entrada + añadidos = total; cada tramo de salida es la misma fracción que en el simulador pero sobre ese total, en enteros, y el último tramo se lleva el resto. Los añadidos valen tal cual (el simulador los dimensiona por riesgo/importe, no desde la entrada). Posición heredada al hidratar (entrada no avisada) → cantidades del simulador, como antes. **Verificado repitiendo el día real por REST** con el motor nuevo, sin Telegram ni base: MEDS 284→284, RETO 208→208, MEDS PM 866→866, JZXN 935→234+468+233. 6 tests (`test_bot_alerts_cantidades_cuadradas.py`); un stub que devolvía tupla en vez de float, corregido. Entra en vigor con el siguiente Vigilar. Subido a sailor y staging.

**Receta**: repetir un ticker del día con el motor actual sin tocar nada → `scratchpad/verificar_cuadre.py TICKER HH:MM [PM|RTH]` (hidrata por REST hasta HH:MM NY y da las velas una a una al RunnerAlertas; solo imprime).

## 2026-09-15 (Sailor, Portfolio) — El timeout volvió, el bot que se encendía solo, orden manual ▲▼, Robustez en filas finas y «una a la vez por acción»

Dos sesiones de Jaume en el día sobre Portfolio/Baúl (la del VWAP y el bot va en la entrada de al lado). Commits `3e9d174` (mañana, subido a mediodía) y `6accbec` (tarde), los dos **subidos a `sailor-rama-desarrollo` y `staging`** por orden suya; con el segundo subieron también `d1d4632` y `7fbe10c` (bot de alertas, de su otra sesión). Backend relanzado a mano tres veces (09:02, 17:53 la otra sesión, 19:21), siempre con el bot parado salvo la metedura de pata de las 17:42 que cuenta la otra entrada.

### El timeout de 20 s del listado volvió (mañana) — arreglo de raíz

El 14-sep lo «arreglé» quitando las 13 curvas en paralelo; el 15 por la mañana Jaume lo vio otra vez en la **primera llamada del día**: `GET /portfolio-lab/strategies` tardaba 16 s medidos con el disco mecánico saturado (backend y bot recién arrancados, `users.duckdb` de 3 GB frío). El coste estaba en `json_extract` sobre `backtest_params` de cada corrida. Arreglo: tabla persistente `portfolio_lab_params_cache(run_id, executed_at, params)` (`ensure_params_cache_table` + `list_runs_light` en `portfolio_lab_service.py`): el listado hace un scan tipado y solo las corridas que no están en la caché pasan por `json_extract`; una corrida re-ejecutada cambia de `executed_at` y se recalcula sola. Listado a 0,05-0,12 s en caliente. En el frontend el listado va con 120 s de timeout, aviso «está tardando» a los 6 s y botón «reintentar» (el `setState` va en el click, no en el efecto: la regla `set-state-in-effect` del lint).

### «¿Por qué coño el bot se enciende al abrir la aplicación?»

Era el paso 5 de `D:\lanzador_btt\arrancar_btt.ps1` (fuera del repo): el acceso directo del escritorio arrancaba backend, frontend **y el bot**. Jaume: «debe encenderse cuando le doy a Vigilar, no debe ir a su aire nunca». Paso quitado, cabecera del script explicándolo, pasos renumerados 1/4..4/4; copia en `arrancar_btt.ps1.bak-2026-09-15`. Ahora el único bot que existe es el que arranca el botón Vigilar.

### Orden manual de las estrategias (▲▼) — un orden para todas las listas

Botones ▲▼ en el Baúl (los tres cuadros), en «En crudo» y en Robustez. `frontend/src/lib/ordenEstrategias.ts`: `leerOrden` / `guardarOrden` / `aplicarOrden` / `moverEnOrden`, guardado en `localStorage` (`btt.orden_estrategias`). Mover dentro de un cuadro que es un subconjunto (p. ej. solo las de Portfolio) intercambia con el **vecino visible** en el orden global, así el orden no se rompe entre cuadros. Es por navegador y no por usuario, a propósito: no toca base de datos ni lógica, y el bot lee el Baúl igual que antes (el orden solo es visual… y desempata en «una a la vez», ver abajo). Al arrancar la página el estado sale de `useState(() => leerOrden())` para no pisar el SSR.

### Robustez en filas finas

`StrategyPicker` reescrito como filas de una línea de 28 px con cabecera de columnas (`COLS = "14px minmax(180px, 1fr) 150px 64px 60px 52px 48px 56px 44px"`), como el Baúl y «En crudo». Jaume: «son todas como muy anchas». Lógica del picker intacta; `robustez/page.tsx` aplica el orden compartido.

### Auditoría de «Gen. Debilidad (PM Top)»: sin look-ahead

Jaume vio en un gráfico que la estrategia entraba «al principio del gráfico» con PM High Gap > 50 y sospechó de mirar el futuro. Comprobado sobre el código y sobre los trades guardados: los 7 indicadores de la entrada son causales (PM High Gap = máximo acumulado del premercado hasta esa vela frente al cierre de ayer; el perfil de volumen es acumulado; etc.), ninguna entrada en las velas 0-1 (mínimo `entry_idx` 2), y el 5,7 % que entra en las velas 2-5 rinde igual que el resto. Lo que ve como «principio del gráfico» es que el gráfico arranca en la **primera vela del ticker ese día** (tickers ilíquidos con pocas velas de premercado), no a las 04:00.

### «Solo una estrategia abierta a la vez por acción» (`one_per_ticker`)

Pedido de Jaume: «¿se podría hacer sin corromper nada?». Sí: es un filtro sobre los trades guardados, no toca corridas ni estrategias. Check en el bloque Portfolio de «En crudo». En `portfolio_lab_raw.simulate`, entre preparar los trades y el bucle diario: barrido de TODOS los trades por (hora de entrada, orden de la lista); si el ticker tiene una posición abierta (de la estrategia que sea) hasta un minuto posterior, el trade se bloquea. Va **antes** de dimensionar para que el capital del día no cuente con los bloqueados. Al salir (stop, TP, lo que sea) entra la primera que dé señal, **sea la que sea** — Jaume preguntó si tras un stop seguiría con la primera o entraría la segunda: entra la segunda si da señal antes; a igual minuto manda el orden manual ▲▼. Contador «Bloqueadas» (tarjeta y columna por estrategia). Verificado por API: 0 solapes por ticker; con 3 estrategias, 1.746 bloqueadas.

**Límite honesto:** las señales que una estrategia bloqueada habría tenido *después*, mientras en su propio backtest estaba dentro de la posición, no existen en los trades guardados: el resultado es, si acaso, conservador. Reproducirlo exacto exigiría un backtest conjunto. Variante ofrecida y no pedida: «la que entró primero se queda el ticker».

### Menudencias

- Aviso de consola «uncontrolled → controlled» en el checkbox: `checked={!!cfg.onePerTicker}` (la config guardada de antes no traía la clave).
- `useMemo` sin importar en `robustez/page.tsx` (tsc lo cazó); tsc y eslint limpios al commitear.
- **PENDIENTE que Jaume dejó dicho:** tiene que **auditar el Portfolio «En crudo»** («encontré alguna cosilla», noche del 14-sep). Recordárselo al empezar.

---

## 2026-09-15 (Sailor, tarde) — El VWAP como nivel del stop de estructura, y la simulación interna del bot iba sin niveles

Pedido de Jaume: «como tenemos Previous Max y demás, lo mismo respecto al VWAP», dentro de Market Structure. Commit `6ae48ab` en `sailor-rama-desarrollo`, sin subir al escribir esto. Backend relanzado a mano (sin `--reload`) con el bot parado por él.

### El VWAP como stop (misma receta que el pivote, `194e41e`)

Nueve niveles ya: HOD, LOD, PMH, PML, Previous Max/Min, **VWAP**, Último pivote alto/bajo. El VWAP se fija en la vela de la SEÑAL como todos los demás (no persigue al VWAP después), con operador y margen, pasa por Cangrejo A/B, híbrido y «Shares por SL», paridad Python/JIT (`HS_VWAP`), en los dos caminos del backtest y en el bot por la misma `_structural_level`. Un corto entrado POR ENCIMA del VWAP tiene el nivel del lado ganador y no entra — igual que un Previous Max ya roto.

**La decisión de diseño que importa: ES EL MISMO VWAP que el de las condiciones y el gráfico** (`indicators._vwap`, precio típico ponderado por volumen, acumulado desde la primera vela del día). Por eso viaja como columna `vwap` de `market_frame` sobre el **día entero** y se recorta con la sesión, como hod/pm_high — y NO se calcula sobre los arrays recortados, que es lo que hacen el ATR y los pivotes (esos solo miran N velas atrás). Un VWAP que arrancara a las 09:30 sería «el VWAP de RTH», otro indicador. `test_stop_vwap_run_backtest.py` pasa por `run_backtest` entero con sesión RTH y comprueba que el stop es el VWAP del día completo y no el de la sesión, y que secuencial = slab = pool = JIT. Cruzado además sobre datos reales (APLM, LGCL, NCRA del 2025-11-03): el stop coincide al céntimo con el `vwap` que devuelve `/api/candles` (el del gráfico) en la vela de la señal.

Detalle que costó un rato: el `time` de `/api/candles` lleva la hora ET como si fuera UTC (así la pinta lightweight-charts); convertirlo a ET otra vez desplaza 5 h y parece que el VWAP «no cuadra».

### El fallo del bot que salió de paso (no daba error)

El bot tiene DOS vías: `nivel_stop` (el precio del aviso) y `simulate(**_kwargs_simulate(...))` (la simulación interna de la que deduce pirámides y salidas). El 10-sep se actualizó la primera con el ATR por barra, el pivote y el respaldo ajustable; la segunda no recibía `atrs`, `pivot_highs/lows`, `hs_atr_fallback_pct` ni `hs_struct_fallback_pct`. **Medido con el código viejo: con stop por ATR la simulación interna daba 0 trades** (el motor no entra sin ATR ni respaldo), **con el pivote el stop era 105 en vez de 110** (respaldo del 5 %). El aviso salía bien y las salidas se deducían de otra operación. Arreglado: `_kwargs_simulate` pasa los mismos niveles que el aviso, y los tests nuevos pasan por `_kwargs_simulate` de verdad con un frame de `market_frame`. Regla: todo nivel nuevo va en los dos sitios.

**Pendiente relacionado, no tocado:** el ATR del stop en el backtest se calcula sobre los arrays recortados a la sesión; el bot usa `frame["atr"]` del día entero. En premercado desde las 04:00 da igual; en RTH con stop por ATR divergen las primeras 14 velas. Decidir cuál es el bueno y unificar.

### Menudencias

- El texto de las opciones «Último pivote» del desplegable llevaba un `\u00da` literal (JSX no interpreta escapes en texto): se leía «\u00daltimo».
- Metedura de pata mía: reinicié el backend a las 17:42 creyendo que el bot estaba apagado, y estaba vigilando (mi filtro de procesos exigía `bot_senales` en la línea de comando; el bot se lanza como `python bot.py --vivo` desde su carpeta). 50 s sin backend en RTH; el bot siguió latiendo y conectado. El filtro bueno es `CommandLine -match 'bot\.py'`.
- Suite: 1.236 pasados, 0 fallos.

---

## 2026-09-14 (Sailor, bot de alertas) — ELMT sin señal, un aviso perdido en silencio, y el `--reload` fuera del lanzador

Jaume: «¿Puedes mirarme por qué no ha dado señal de ELMT?». Luego, al parar el bot a las 20:01: «haz una auditoría rápida de hoy».

### ELMT: la vela que acababa de cerrar se sellaba como «pasado»

Al admitir un ticker, `RunnerAlertas.hidratar()` traía el día por REST y lo pasaba entero por el motor **tirando lo que saliera** (para no reavisar la mañana; el caso FLYE del 1-sep). Pero la última fila del REST era la vela cerrada **7 segundos antes**, y el radar y la entrada de 1B comparten umbral (gap ≥ 50 %): la vela que admite es a menudo la vela que entra. ELMT, 06:59 NY: PMH gap 49,4 → 51,1 % **y** cierre por debajo del mínimo anterior → «1 avisos del pasado descartados» = la entrada. Segundo orden: el simulador sí abrió la posición, así que 07:03/07:09/07:12 no eran entradas nuevas, y sus salidas sí iban a avisar.

Arreglo (`09fa852`, subido): las filas del REST se parten en **pasado** (sellar y tirar) / **última completa** (evaluar como AHORA; sus avisos vuelven a `bot.py` y salen por `al_avisar`) / **minuto en curso** (fuera: Massive lo da a medias, llega por el feed al cerrar). `hidratar()` devuelve `list[Evento]`; 7 tests en `test_bot_alerts_hidratar_ultima_vela.py`. El log ahora dice «N velas de pasado selladas (M avisos tirados), la de las HH:MM evaluada como ACTUAL (K avisos)». **Entra en vigor con el bot de mañana**; comprobar esa línea con el primer ticker que entre al radar.

### Auditoría del día: 23 avisos en Telegram, 22 en la base

Parado cerró el proceso; las dos estrategias marcadas; universo 5.696, cierres del 11-sep, calendario OK; 7 tickers en el radar; los **tres tramos** del take profit de 1B salieron para ELMT/SCNI/HAIN (el arreglo del 10-sep funciona en vivo); 14 prealertas; dos `1011 keepalive ping timeout` del feed, reconectados solos.

**Un aviso perdido sin error**: el 3.er tramo de SCNI (08:45 NY) llegó a Telegram y al diario pero no a la base. En `bot.py`, `await to_thread(cliente.publicar, pendientes)` seguido de `pendientes.clear()`: httpx serializa la lista al empezar el envío, y lo que se añade DURANTE el envío (los tres cierres de las 08:45 fueron en el mismo segundo) se borra sin salir. Con los tramos saliendo a la vez para todas las posiciones, iba a pasar casi cada día. Arreglo en `bot.py` (fuera de git): copiar el lote, enviar la copia, `del pendientes[:len(lote)]`. Probado con una simulación fiel (antes pierde SCNI, ahora queda en cola). Receta de auditoría: contar avisos del diario (hora ES) contra `/api/bot-alerts/eventos?fecha=` (hora NY).

### El `--reload` tumbó el backend en sesión (4 de 4) → quitado del lanzador

Guardar `bot_alerts_runner.py` con el backend en `--reload` lo dejó ~8 min sin responder con el mercado abierto (13:22–13:30; el worker no volvía). Cuarta recarga atascada en tres días. El bot no se enteró (no es hijo del backend desde `2036971`; Telegram lo manda él). **Con el visto bueno de Jaume, `D:\lanzador_btt\arrancar_btt.ps1` ya arranca uvicorn SIN `--reload`.** Consecuencia para el siguiente chat: **tocar el backend no llega al backend que corre; hay que reiniciarlo a mano** (matar el cmd «BTT backend» + sus python sin `/T`, relanzar sin reload, fuera de sesión) y verificar el efecto. Ojo con el sandbox de PowerShell: `Stop-Process` se bloquea; usar `powershell -NoProfile -Command` desde Bash.

### Por la noche: los dos huecos, arreglados

Jaume aprobó los dos arreglos («Vale a las dos cosas»), con el bot apagado:

- **Cuaderno propio del bot.** `bot.py` abre un `FileHandler` al arrancar: `D:/bot_senales/logs/bot_AAAA-MM-DD.log` (append, cabecera «arranque … (PID)», borra los de más de 90 días, ~100 KB/día). Probado lanzándolo DETACHED como lo hace la página: escribe. La causa del hueco era ese `DETACHED_PROCESS`: sin consola, cmd no consigue pasarle a python la redirección `>> bot_hoy.log 2>&1` del .bat (los `echo` sí entran; python no). **Desde el 16-sep el log del bot se lee en `logs/`.**
- **`/estado` 100 % memoria** (`d1d4632`): `bas.estado_cacheado()` y la base solo con la cache fría; Telegram por `tg.probar_sin_esperar()` (hilo de fondo, fallos cacheados 15 s). Verificado tras relanzar el backend (19:53, sin `--reload`): con 6 curvas de equity en paralelo (17,5 s), `/estado` pasó de 1,93 s a 0,14 s en el peor sondeo. 7 tests nuevos; 197 de bot_alerts pasan.

### Desde el 9-sep, para quien retome el bot (todo en commits y en la memoria de Claude)

9-sep: festivos NYSE y horario de verano (`bot_alerts_calendario.py`); el botón Vigilar no encendía (env `BOT_ALERTS_ARRANCADO_POR_LA_PAGINA`). 10-sep: solo avisaba el primer tramo de un TP parcial → dedup por `(entry_idx, n_tramo)`, para cualquier tipo de parcial; fuga del token de Telegram en los logs de httpx **aplazada por decisión de Jaume** (no replantearla). 11-sep: Parado CIERRA el proceso, Vigilar arranca limpio, y recarga en caliente de estrategias (`estrategias_version` en `/estado`, `MotorAlertas.actualizar()` conserva la memoria del día). Pendientes conocidos: el bucle «sin estrategias activas» no publica el diario mientras espera; `posicion_restante` no se guarda en la base (solo va en Telegram, a propósito).

---

## 2026-09-14 (Sailor) — Portfolio: el Baúl en filas finas, el timeout del listado, y la sub-pestaña «En crudo» con tope de exposición

Jaume quería tres cosas en la página de Portfolio: (1) el Baúl con «celdas finas alargadas estilo excel» y scroll, sin tocar su lógica (es de donde el bot de alertas saca las estrategias); (2) mirar el `Request timed out after 20s: /portfolio-lab/strategies`; (3) una sub-sub-página para estudiar un portfolio con las corridas **tal cual se guardaron** —cada una con sus comisiones y condiciones— en vez de normalizadas, y encima pesos, Kelly, Monte Carlo y un calendario como el del Backtester. La pestaña normalizada («Imagen general») no se toca: sigue siendo la fuente del bot.

### El timeout: trece llamadas a la vez que se serializaban

Medido con el backend en marcha: el listado solo tarda 1,5-2,5 s en caliente (11,8 s en frío, disco mecánico + `json_extract` de `backtest_params`). Pero nada más llegar, el Baúl lanzaba **13 llamadas en paralelo** a `/strategies/{id}/equity` para precargar los minigráficos; cada una hacía `list_runs_for_strategies` + `_attach_params` (parsear el JSON entero de la corrida para tirar los parámetros, ~1 s) y **se serializaban: las 13 acababan a los 12 s a la vez**, y un listado pedido mientras tanto tardaba 11 s más. Con la caché fría, > 20 s.

Arreglo en dos capas:
- **Frontend:** la curva se pide **al desplegar** la fila (`onOpen` de `StrategyShelf`, `cargarCurva` en `BaulTab`), no las trece al abrir.
- **Backend:** `strategy_equity` ya no pasa por `_attach_params`; usa `portfolio_lab_raw.latest_run_ids` (escaneo tipado) y `load_runs` (una consulta con `json_extract(results_json, ['$.trades','$.backtest_params','$.global_equity','$.aggregate_metrics'])` que parsea cada documento **una vez**) con **caché en proceso por `(run_id, executed_at)`** (las corridas son inmutables; un re-guardado del mismo job renueva `executed_at`). Medido: 1,5 s la primera vez, 0,02 s después.

### El motor en crudo (`backend/app/services/portfolio_lab_raw.py`, nuevo; `POST /api/portfolio-lab/raw`)

Decisión de Jaume sobre qué es «peso»: **no** un multiplicador ni un reparto de un capital común. La página debe **ignorar el capital con el que se guardó cada corrida**, poner aquí «la cantidad de capital asignado por trade» (global, o por estrategia) y simular «un portfolio en el cual mi exposición máxima por la suma de los trades de todas las estrategias en un momento dado sea menor que la que le pongamos».

Cómo se hace, y por qué es exacto salvo un detalle:
- Un trade guardado lleva `size`, `avg_entry_price`, `pnl` (neto de comisiones y slippage, **limpio de locates**) y `fees`. Comisiones (por acción o % del valor) y slippage (fracción del precio) son **lineales en el número de acciones**, así que `pnl_nuevo = pnl × size_nuevo / size` conserva las condiciones de la corrida. Los locates se **recalculan** por paquetes de 100 sobre el mayor corto del ticker-día, con `locates_cost`/`locate_type` de la propia corrida (misma regla que `portfolio_sim`).
- `sizing = "notional"`: `size_nuevo = nocional / avg_entry_price` (el nocional es lo que cuenta contra el tope). `sizing = "as_saved"`: el tamaño guardado, para ver la cruda pura.
- **Tope de exposición:** todos los trades de todas las estrategias, por orden de `entry_time`, con un heap de posiciones abiertas por `exit_time` (al minuto). Un trade que llevaría la suma de nocionales por encima del tope se **salta** o se **recorta al hueco libre** (`cap_mode`). Se devuelve la exposición máxima y el máximo de posiciones abiertas de cada día. Con nocionales iguales «recortar» nunca actúa (el hueco libre es 0 o ≥ un nocional): no es un bug.
- El capital es el del portfolio (base del retorno, del Kelly y del MC). Los gastos fijos de las corridas **no se arrastran** (tres corridas con 300 $/mes serían tres cuentas): se piden aparte, a 0 por defecto, y se cargan el primer día operado de cada mes.
- Reutiliza `compute_stats`, `var_stats` y `correlation_stats` de `portfolio_lab_engine`. La «R» de `expectancy_r` en crudo es PnL/nocional del trade (no hay una R común); la UI lo dice.
- **Kelly multi-estrategia** sobre el retorno diario (PnL/capital): `f* = Σ⁻¹ μ`, media de cada una sobre sus días vivos y covarianza de cada pareja sobre los días en que ambas existen. `f*_i` = **cuántas veces el tamaño actual** de la estrategia i. Se devuelven f, ½f y ¼f y el crecimiento esperado; con < 60 días vivos no se calcula. En la UI, «Aplicar ½ Kelly» rellena el $/trade por estrategia (`base × f_half`) y desmarca las que salen ≤ 0; luego hay que Calcular, y el tope sigue mandando. Ojo: con estas corridas (Sharpe diario > 4 sin costes reales) f* sale 10-20×; es lo que dice la muestra, no un bug.
- Los trades aceptados vuelven en **columnas** (`trades`: date, si, ticker, dir, entry, exit, entry_px, exit_px, size, notional, pnl, fees, r, reason): 18.951 trades ≈ 2,5 MB. La `r_multiple` de la corrida es **invariante al tamaño** (PnL y riesgo escalan igual), por eso vale tal cual.

Probado contra la base real (solo lectura, con `importlib` desde el scratchpad, sin tocar el árbol): 13 estrategias, 33.625 trades, carga 1,5 s en frío / 0 en caché, simulación 0,1-0,4 s; suma de trades − locates − gastos = curva al céntimo (0,32 $ de redondeo sobre 18.951 trades). Con 5.000 $/trade y sin tope, las 4 del cuadro Portfolio llegan a **165.000 $ abiertos a la vez** (33 posiciones) sobre 50.000 de capital; con tope de 15.000 se saltan 4.080 de 7.868 trades y el DD pasa de −19 % a −12 %.

### La vista (`frontend/src/components/portfolio/crudo/`)

Cuarta sub-pestaña de Portfolio, «En crudo», estilo hoja de datos del Genético (primitivos copiados en `hoja.tsx`: `Sec`, `Row`, `Num`, `Toggle`, `Btn`, `Stat`; formato propio sin ICU). Su selector son **todas** las estrategias con corrida, no solo las del cuadro Portfolio, y se pinta aunque el cuadro esté vacío (`PortfolioTab` lo despacha antes del `Placeholder`).

Bloques: (1) tabla de estrategias con **con qué se corrió cada una** (capital, riesgo, comisiones —`fees` PERCENT va en fracción, se pinta ×100—, slippage ×100, locates, gastos, periodo) y la casilla $/trade por estrategia; (2) capital, tamaño, nocional, tope, «si no cabe», gastos fijos, periodo, Calcular; (3) cifras grandes; (4) `LineChart` (PnL acumulado por estrategia y el portfolio en cobre, $ o % del capital, ejes, rejilla, leyenda con valor final y cursor con lectura de todas las series) + `ExposureChart` (área de exposición máxima diaria, línea del tope en rojo, marcas ámbar en la base los días en que mordió, línea del capital) + `DrawdownRibbon`; (5) tabla por estrategia con fila Portfolio; (6) `CorrelationMatrix` + tabla Kelly con botones; (7) **`CalendarioCrudo`**: Profits / Gastos / Profits − Gastos en $ o R, meses con columna de semana, y al pulsar un día sus trades **agrupados por estrategia** con subtotales; (8) Monte Carlo por día con el endpoint y los gráficos existentes (`mode: "additive"`; `risk_pct` tiene que ir > 0 aunque no se use). La paleta de series **no lleva cobre ni naranjas** para que ninguna estrategia se confunda con la línea del portfolio.

La R del calendario: como cada corrida tiene su propio riesgo por trade, no hay un «1 R» común. La R neta del día es la suma de las R de sus trades; el bruto se pasa a R trade a trade (riesgo = |PnL| / |R|); locates y gastos fijos, que no son de ningún trade, con el riesgo medio del día (gastos_R = bruto_R − neto_R, así cuadra).

### El Baúl

`StrategyShelf`: filas de **una línea de 28 px** en `grid` con las columnas compartidas entre cabecera y filas (`COLS`), etiquetas de las métricas **una vez** en la cabecera (sticky), altura tope de 12 filas con scroll interno; con una fila desplegada el cuadro crece para que el detalle no se lea con scroll. El distintivo «se normalizará (aprox.)» pasa a «se normalizará ≈» para caber en 132 px. Sin cambios de lógica.

### Trampas del día

- **`git stash` con el backend en `--reload` es un reload doble** (stash y pop tocan `backend/app/`): lo hice para comparar el lint del fichero original y dejé el 8010 sin responder 09:24 → 09:25. Comparar con `git show HEAD:ruta` a un fichero temporal, nunca con stash.
- Un heredoc **sin comillas** en bash ejecuta los backticks del texto (`` `list_runs_for_strategies` `` se convirtió en una orden y el comentario quedó vacío). Los parches en Python van a fichero con el `Write` y se ejecutan; nunca inline.
- Un `{/* comentario JSX */}` justo detrás de `) : (` en un ternario es un error de sintaxis (posición de expresión): ahí va `//`.
- El backend se tocó **con el bot vivo pero antes de las 10:00** (decisión de Jaume): dos ficheros copiados de golpe, 8010 caído 09:07 → 09:09, verificado. El bot lo arrancó el lanzador (no es hijo del backend) y no se enteró.

### Segunda vuelta (misma mañana): «me salen todas perdedoras» y «ningún trade entra»

Reproducido: **el tope estaba solo en dólares**. Un «30» puesto pensando en un 30 % es un tope de 30 $, ningún trade de 5.000 $ cabe («ningún trade entra» en «saltar») y en «recortar» cada trade entra con 30 $, los PnL son céntimos, el portfolio con gastos fijos queda en negativo y la columna «Aporta» (PnL de cada una / total negativo) sale roja para todas. Ni el motor ni las corridas tenían nada mal; la página sí: unidades sin elegir, mensaje mudo y una columna que engaña.

Arreglado en el frontend (con el bot encendido, sin tocar backend):
- **Por defecto «tal cual la corrida»** (la suma literal de lo que hizo cada backtest, que es la pregunta base de Jaume: «simplemente sumar cada estrategia, ver cuánto ganaría o perdería») y **capital = suma de los capitales de las corridas marcadas** (editable; «usar la suma» para volver). El nocional por trade y el tope son capas opcionales.
- **Nocional y tope en $ o en % del capital** (`aUsd`), con la equivalencia en $ debajo; la casilla por estrategia sigue la unidad del global; Kelly escribe los overrides en esa unidad.
- **Validación antes de Calcular** con números: «El tope (30 $) es menor que el nocional de un trade (5.000 $): no cabría ninguno. Súbelo, ponlo en % del capital o elige recortar». Calcular se desactiva.
- «Aporta» solo cuando el total es positivo; si no, «—» con el porqué en el `title`.
- Ayudas reescritas en cristiano: qué es el nocional (acciones × precio de entrada, con ejemplo), qué es el tope (lo que puedes tener abierto a la vez), qué es recortar al hueco (con ejemplo de 20.000/17.000/3.000), y que recortar no cambia nada con tamaños iguales.

### Tercera vuelta: «simplemente es sumar estrategias sin más»

Jaume, al ver nocional / tope / saltar-recortar: «no entiendo para qué sirve... simplemente es sumar estrategias sin más. Al final tan solo es ver el gráfico cómo quedaría si hubiera aplicado ambas estrategias y se sumaran; después añadiremos algo para el tema de si hubiéramos escalado de X o Y manera». Y una observación buena sobre el tope en %: «si pongo 7 % me pone 700 abiertos como máximo, pero si el portfolio escala esos 700 ya no son el 7 %» → **cuando se haga la capa de escalado, el tope en % va sobre el capital del día, no sobre el inicial** (como el riesgo PERCENT del motor).

`CrudoTab.tsx` reescrito en simple: selector (con las condiciones de cada corrida y su retorno), «La suma» (capital = suma de las corridas, gastos fijos, periodo, Calcular), cifras, curvas por estrategia + suma, «Abierto a la vez, día a día» (informativo: lo que las corridas tuvieron abierto juntas; es el dato para la capa de escalado), drawdown, tabla por estrategia, correlación, calendario, Monte Carlo. **Fuera de la vista**: tamaño por trade, nocional, tope, saltar/recortar y Kelly (el motor lo conserva todo; la petición va siempre con `sizing: "as_saved"` y tope 0). El `Toggle` de `hoja.tsx` lleva ahora `nowrap + ellipsis + padding` porque «% del capital» se salía del botón.

Lo que enseña la suma «tal cual» con las corridas que hay: las guardadas **normalizadas** (riesgo 1 $ sobre 50.000) suman céntimos (92 $ abiertos a la vez, +0,5 %); solo tiene sentido con corridas guardadas con tamaño real. Es la razón de ser de la capa de escalado.

### Cuarta vuelta: la ejecución se fija AQUÍ, por estrategia (el planteamiento definitivo)

Jaume: «vamos a fijar nosotros aquí en el portfolio el slippage, el capital a apostar por trade en fijo o en %, los locates (y sus tipos) tal y como se usan en el backtester, black swans, halts y comisiones en % o en $ POR ESTRATEGIA... la resetearemos para esta visualización». Gastos fijos aparte (del portfolio; los de las corridas no cuentan). Y que no se sobreescriba nada guardado bajo ningún concepto.

**Qué se reconstruye desde los trades guardados sin rehacer backtests (exacto):** tamaño (capital/trade o riesgo/trade, en $ o en % del capital *del día*), comisiones ($/acción o % del valor), slippage, locates fijos y **aleatorios** (cada trade guarda `locate_ref_price` y `locate_pkg_price`: se re-sortea con `locates_random.precio_locate`, determinista por semilla-ticker-fecha), gastos fijos. **Lo que NO:** Black Swan y Halts (dependen de las velas dentro del trade): fase aparte con backtest efímero, y Jaume dijo que quizá no hagan falta aquí.

**Cómo se resetea un trade** (`portfolio_lab_raw.simulate`, reescrito): bruto = pnl + fees + slippage estimado; bruto por acción = bruto / acciones; tamaño nuevo como dimensiona `portfolio_sim` (`risk_amount / precio` o `/ distancia al stop`) sobre la **primera ejecución** (`executions[0]`) y conservando la proporción de las pirámides; distancia inicial al stop = riesgo de la corrida / acciones de la entrada cuando dimensionó por stop (exacta), si no el último `stop_loss` (aprox., `stop_aprox`); costes nuevos lineales en las acciones; locates por ticker-día sobre el mayor corto. Dos trampas que costaron una vuelta: el `size` guardado es la posición ENTERA con pirámides, y el `stop_loss` guardado es el ÚLTIMO stop, no el de la entrada.

**Verificación:** `tal cual` reproduce las 13 corridas al céntimo; reaplicando a cada corrida su propia ejecución, 11 de 13 exactas y las dos con locates aleatorios a +1,5 % (los topes de caja del backtester no se reproducen: es lo que se resetea). Script: `scratchpad/test_exec.py` de la sesión.

**Tope de exposición en % del capital DEL DÍA** (`max_exposure_pct`, manda sobre el de $): tope del día = pct × capital de apertura del día. Efecto de segundo orden sin afinar (la recomposición tras saltar trades mueve el capital de los días siguientes).

**Interfaz:** tabla de estrategias con la ejecución por fila (tamaño con modo/valor/unidad, comisiones con unidad, slippage, locates con tipo y parámetros), fila «por defecto» con «→ todas», botón «= corrida» que rellena la fila con lo que tenía su corrida, y vista «cómo se corrió» de solo lectura. Portfolio: capital, gastos fijos, tope (% del día o $), periodo. Panel PnL + drawdown (técnico, con tabla al lado), exposición en % del capital del día, tabla por estrategia con comisiones/slippage/locates/«stop ≈», correlación, calendario, Monte Carlo. La UI reconoce el motor nuevo por `config.default_exec` y avisa si el backend es el viejo.

**Diferencia capital/trade vs riesgo/trade (explicada a Jaume):** capital = valor fijo por trade, la pérdida al stop depende de la distancia; riesgo = pérdida fija al stop, el tamaño sale de la distancia (la R significa lo mismo en todas).

**Posiciones a la vez:** es la suma de nocionales de todos los trades abiertos en el mismo instante, de todas las estrategias, en % del capital del día; **al minuto**, así que PM y RTH solo cuentan juntas si se solapan (Jaume lo preguntó).

**PENDIENTE DE APLICAR (bot Vigilando, Jaume dijo «cuando pare el bot»):** los tres ficheros están en `docs/pendiente_backend_crudo/` con la receta en `APLICAR.md` (copiar, esperar el 8010, borrar la carpeta). Incluyen también los arreglos anteriores (pico del DD en el capital en `compute_stats`, tramos por trades, locates aleatorios).

**Bug real encontrado de paso (motor, PENDIENTE de aplicar, parche listo y probado en el scratchpad):** el tramo «vivo» de cada estrategia salía de `backtest_params.start_date/end_date`, y «RTH prueba 1» tiene trades desde 2021 con `start_date = 2026-01-01`: el PnL sumaba los cinco años (2,22 M, correcto) pero el retorno por estrategia (418 % en vez de 694 %), la correlación y Kelly solo contaban los días de 2026. El parche toma el tramo de **los trades** (min/max de las fechas en el rango) y deja los parámetros solo de respaldo sin trades. Probado con `importlib` contra la base en solo lectura: 694,5 % = esperado. **No aplicado porque el bot estaba encendido**; es una edición en `backend/app/services/portfolio_lab_raw.py` (reload de ~1 min).

### Noche: backend aplicado, el R lo pone la estrategia, desplegable por fila

- **Backend aplicado a las 20:06** (Jaume apagó el bot): copié los tres ficheros y NO pasó nada — el 8010 corría **sin `--reload`** desde las 13:29 (lo relanzó así otra sesión: ventana «BTT backend (sin reload)»). Maté el árbol (9600/20924/17340) y lo relancé con la misma línea de comando (`cmd /k title BTT backend (sin reload)&& ... uvicorn app.main:app --host 0.0.0.0 --port 8010`, sin reload); 95 s hasta servir. Verificado: `/raw` devuelve `config.default_exec` y `exec.sizing` resuelto por estrategia. Carpeta `docs/pendiente_backend_crudo/` borrada: los buenos son los del árbol.
- **El modo de tamaño lo decide la estrategia** (Jaume: «si va por SL o no ya está en la estrategia; aquí solo el R, fijo o en %, como en el panel del backtester»). `sizing: "auto"` en el motor (= `size_by_sl` de la corrida), la fila solo tiene R + `$`/`%` y una etiqueta «por SL» / «por capital». «= corrida» manda `auto`. Verificado: 10/13 exactas, 3 dentro del 1,6 %.
- **Desplegable por fila** (pedido): `StrategyDetail.tsx` extraído del Baúl (mismo bloque: universo, entrada, salida, riesgo, con qué se corrió, curva) y usado en el Baúl y en «En crudo» (chevron o nombre; la curva se pide al abrir).
- **Defecto 1 %** por trade (con 5 % y miles de trades el compound daba 10^25 %); números ≥ 10^12 en notación científica; aviso en la tarjeta cuando el retorno pasa de 100.000 %. **DD por estrategia** = pérdida desde su máximo relativa al capital de ESE DÍA (compartiendo cuenta, medirlo contra una base fija daba −33.000 %).
- Explicado a Jaume capital/trade vs riesgo/trade (= el interruptor «Tamaño por SL»: 1R es lo que se mete o lo que se pierde al stop) y que nada de la pestaña escribe (ni estrategia, ni corrida, ni cuadros).

### Compartidas y push (mediodía)

Jaume: «mi socio no ve mis 4 compartidas». Diagnóstico: 2 estaban en `staging` (commit `89322f8`, 10-sep); las otras 2 (Cruce con media prueba, Gen. Debilidad (PM Top), compartidas el 13-sep 10:44) se quedaron en disco sin commitear — «Compartir» solo escribe el JSON, nada viaja sin push (README de la carpeta). Por orden suya («las dos, rama entera»): commit `3b60650` solo con esos dos JSON y push de la rama a `sailor` y a `staging` (sin divergencia: staging no tenía nada fuera de sailor). Con ella subieron los 4 commits pendientes de días anteriores. El trabajo de hoy sigue sin commitear.

### Dónde lo dejamos

- **PENDIENTE PARA MAÑANA (Jaume, 14-sep noche): AUDITAR EL PORTFOLIO «En crudo».** Lo probó al final del día y «encontró alguna cosilla»; no dijo cuál. Recordárselo al empezar y repasar con él, uno a uno: el R por trade (fijo/%) por estrategia y la etiqueta por SL/por capital, comisiones/slippage/locates reaplicados, el desplegable por fila, las cifras (el compound del % por trade dispara el retorno con estas corridas sin costes), el drawdown por estrategia relativo al capital del día, la exposición al minuto, el calendario y el Monte Carlo.
- Subido todo a `sailor-rama-desarrollo` y `staging` por orden suya (ver commits de esta noche).
- Hecho y probado en el navegador: Baúl fino, curva perezosa, `/raw`, la sub-pestaña entera, Kelly aplicado, MC, calendario con día abierto. `tsc` y `eslint` limpios en lo nuevo (los avisos que quedan en `PortfolioTab`/`BaulTab` son anteriores).
- **Sin commit ni push** (el trabajo del Portfolio de hoy): `backend/app/routers/portfolio_lab.py`, `backend/app/services/portfolio_lab_raw.py` (nuevo), `backend/app/services/portfolio_lab_engine.py` (pico del DD), `frontend/src/lib/api_portfolio_lab.ts`, `frontend/src/components/portfolio/{StrategyShelf,BaulTab,PortfolioTab,StrategyDetail}.tsx`, `frontend/src/components/portfolio/crudo/*` (nuevo), `docs/MEMORIA.md`. Lo subido hoy fue solo el commit de las compartidas (`3b60650`).
- Pendiente de decidir con Jaume: si el Kelly debería toparse por el tope de exposición antes de proponer el $/trade.

## 2026-09-13 (Sailor) — La noche de vigilante: el perfil de volumen tumbaba el proceso, y la primera corrida con los alternativos

Jaume lanzó «Genético variado 1» (`20260912_220222_31c6`: semilla 50, 80×40, 3 condiciones, los 25 indicadores marcados incluidos los alternativos, ventana 04:00-08:00, IS 2024-01-01 → 2026-01-01, `min_trades` 1200, **fees 0 y slippage 0**, `size_by_sl` apagado) y me dejó de vigilante toda la noche con el bot apagado. Subido a sailor y staging (`b972a32`, `3fb783a`).

### ⚠️ El bug: `_perfil_volumen` escribía fuera del array

La corrida murió a las 22:11 y otra vez a las 22:21, **con el mismo individuo** (`Bar Close cruza abajo Zona baja(0.5, 85) AND Absorption(10) AND Elapsed time(pm)`), sin traceback: el visor de sucesos de Windows la apunta como APPCRASH `0xC0000005` en `ntdll.dll`. `paralelo._apuntar` deja el individuo en `dir_datos/evaluando_<pid>.txt` (OJO: en el directorio de DATOS, no en el de la corrida), y con eso se reprodujo.

La causa: el histograma del perfil tiene 4.096 franjas de anchura fija (% del primer precio del día). `i1` (el máximo) se acotaba; `i0` (el mínimo) NO, y con `i1 < i0 → i1 = i0` un mínimo fuera del histograma escribía fuera del array. numba no comprueba límites: se corrompe el heap y el proceso muere más tarde. OCTO 2025-09-08 hizo **32× el primer precio del día**; con franjas del 0,5 % son 6.400 franjas. En el dataset de la corrida hay 5 días así con bin 0,5 (OCTO, HOLO, CWD, SPRB, TNON); con bin 0,1 —que la UI permite— basta con 4×, o sea el 1 % de los días. **Este bug tumbaba también el backend** en un backtest normal con el perfil y «Detalle %» bajo.

Reproducido con `NUMBA_BOUNDSCHECK=1` sobre el día real: la función de HEAD → `IndexError`; con el arreglo → OK. Lo que se sale por arriba se acumula en la última franja. Test `test_un_precio_fuera_del_histograma_no_revienta`; paridad en `lib/indicators.ts`.

### Amnistía de crashes en el motor del genético

`motor.reanudar()` lee los `evaluando_<pid>.txt` cuyo pid ya no existe, mete al individuo en la caché con fitness 0 y `error`, y renombra el fichero a `crash_<pid>.txt`. Sin esto, un crash determinista es un bucle: crash → reanudar → mismo individuo → crash. Con el vigilante reanudando cada 18 min, la noche aguanta cualquier crash nativo que quede (el «muere sola cada pocas horas» del docstring de `paralelo` sigue sin causa conocida; esta noche no apareció).

### Lo operativo que se aprendió

- **Reanudar recalcula los workers** con la RAM libre del momento (`config.json` guarda `workers: 0`). Tras parar el backend (su hijo `multiprocessing` ES el servidor, con la caché RAM del universo: 3,9 GB), la reanudación cogió 3 workers: 5 s/evaluación frente a 10. Toda la corrida, 232 min.
- Un vigilante en el scratchpad (`vigilante.py`, foto cada 15-20 min: estado, pid vivo, CPU del árbol, RAM, backend; reanuda por API o directo como `_lanzar`; `--backend` relanza el 8010 como el lanzador). Temporal, fuera del repo.
- Escribir en `backend/tests/` dispara el `--reload` igual que `backend/app/`.

### El resultado (BRUTO)

Mejor 56,89 = expectancy 1,55 $ (sobre 100 $ de nocional) × √1.347. PF 1,37, WR 41,6 %, DD −2,8 %, +15 % en 2 años. `Recorrido (%) > -2 AND Vol. de la franja(2.0) > 80 AND Wick Ratio(5, lower) < 0.3 · Stop: Último pivote alto +0 % · TP 15 %`. En cristiano: cortar un gapper de premercado cuando se estanca en el escalón de mayor volumen y nadie compra las caídas, stop pegado al último máximo confirmado, objetivo 15 %.

- **El top 20 es UNA familia**: `Vol. de la franja(2.0) > 80` en los 20, pivote alto como stop en 17; la tercera pata es `Wick Ratio lower < 0,3` o `ATR Extension(hod)`. Ningún clásico entró. Son dos estrategias, no veinte.
- **1,55 % del nocional por operación en premercado está dentro del spread.** No es edge hasta pasar el 2026 (OOS) con costes.
- **74 % de los individuos a fitness 0** por el suelo de 1.200 operaciones. Para la próxima: 500-800 o ventana más ancha.
- La curva de mejora fue sana (15 → 24 → 37 → 54 → 57, meseta desde la gen 36).

---

## 2026-09-12 (Sailor, noche) — Los «Alternativos» entran en el genético, sin cambiar las corridas de siempre

Jaume vio que los indicadores del 9 y 10-sep (regresión, absorción, mecha, retroceso, pivote, perfil de volumen) no estaban en el catálogo del genético y quería lanzar una corrida con ellos esa misma noche. **Premisa suya: no romper nada de lo que ya funciona.**

**Qué hay.** Familia nueva «Alternativos» en `genetico/catalogo.py`:
- **Ocho medidas** con rejilla de valores y parámetros sorteados: `Reg. Slope` (ventana), `Reg. R2` (ventana), `ATR Extension` (periodo del ATR y referencia: VWAP / PMH / cierre de ayer / HOD), `Time vs Level` (referencia y lado), `Absorption` (ventana), `Wick Ratio` (ventana y lado), `Retroceso (%)` (ventana 0/30/60 y dirección del impulso), `Vol. de la franja` (detalle). Las rejillas de absorción y mecha son los **percentiles medidos** el 9-sep (2.476 velas reales): 0,25 / 0,85 / 2,5 / 5 / 10 y 0,2 / 0,3 / 0,4 / 0,5.
- **Cuatro niveles opcionales**: `Ultimo pivote` (velas y dirección), `Punto de control` (detalle), `Zona alta` y `Zona baja` (detalle y % de volumen). Son precios: entran como **destino** de `Bar Close` / `High Bar` / `Low Bar`, y el pivote además como **stop de estructura** («Ultimo pivote alto» / «bajo», los mismos valores que `VALORES_PIVOTE` del motor; ventana 3 y respaldo 5 % por defecto).
- **Fuera a propósito:** «Absorption + Wick» (es `Absorption > a AND Wick Ratio > w`, y el genético ya busca 2-3 condiciones en AND: como dos genes sueltos prueba más). Y **los dos nodos**: son relativos al precio (la primera zona por encima / por debajo del cierre), así que el cierre está SIEMPRE al otro lado y **nunca los cruza** — medido: `Bar Close` cruza el nodo 0 veces en 600 velas; solo la mecha de su lado lo pincha (`High Bar` contra el de arriba, `Low Bar` contra el de abajo). En el genético serían dos de cada tres condiciones muertas de nacimiento. Esto vale también para el constructor de condiciones: «Bar Close cruza Nodo» no dispara nunca.

**Cómo se cumple la premisa: los niveles son OPT-IN.** `Indicador.solo_destino=True` + `NIVELES_OPCIONALES` + `objetivos_permitidos(ind, marcados)` / `stop_niveles(sesgo, marcados)`: un nivel solo entra como destino (y el pivote como stop) si está **marcado en la página**. Sin marcar, la lista de destinos de `Bar Close` es la de siempre, **en el mismo orden**, así que con la misma semilla y la misma config nacen exactamente los mismos individuos: comprobado contra HEAD, 300 individuos × 3 semillas × 2 configs idénticos. Y permite comparar una corrida CON el perfil y otra SIN, que es la única forma de saber si aporta. `lado_izquierdo(nombres)` quita los niveles del sorteo de la izquierda; si solo hay niveles marcados salta un `ValueError` que dice qué falta (y la página lo avisa antes de lanzar). En la página los niveles llevan «↳» y una nota; la validación no los cuenta como condiciones y avisa si hay un nivel marcado sin `Bar Close` / `High Bar` / `Low Bar` que lo use (el pivote se salva si el stop de estructura está activo).

**Dos fallos de la mutación que salieron de paso (no daban error):**
- Al mutar el destino se ponía `params: {}`: un Darvas o un Donchian mutados **volvían a los defectos del motor** (línea de arriba, periodo por defecto) en silencio. Ahora `cromosoma.objetivo_aleatorio` sortea los parámetros como al nacer, y solo entre los destinos permitidos en la corrida.
- **Los suelos `stop_min_pct` / `tp_min_pct` solo valían al NACER.** Un stop del 8 % podía bajar al 5 y al 3 a base de vecinos, y al saltar de estructura a porcentaje se sorteaba sin suelo. El suelo de la página parecía puesto y no lo estaba. Ahora `_mutar_stop` / `_mutar_tp` los aplican (rejilla acotada, y `_stop_aleatorio` / `_tp_aleatorio` los reciben).

**Comprobado:** `test_genetico_catalogo.py` (143 pasan: el motor calcula cada nombre nuevo, las sondas de `ref_level` / `level_dir` / `wick_side` / `swing_dir` / `bin_pct` / `liston_pct` / `zona_pct` no encuentran ramas sin sortear, los opcionales solo entran marcados, el pivote solo entra al stop marcado, `necesita_pivotes(hard_stop)` es True, los suelos valen al mutar, el destino mutado conserva parámetros); y por la vía REAL del motor (`a_definicion` → `compile_strategy_def` → `_evaluate_condition_group`): cada alternativo da señal en alguna combinación de su rejilla, y **los parámetros viajan** (la misma condición con `wick_side` upper/lower, `swing_dir` up/down, `ref_level` vwap/prev_close, `bin_pct` 0,5/2 da series distintas). `tsc` limpio.

**Ojo:** el endpoint `/api/genetico/catalogo` importa `genetico.catalogo` **una vez por proceso**: hasta reiniciar el backend, la página sigue enseñando el catálogo viejo (el proceso del genético, que es aparte, sí importa el nuevo). Y **`git add -A` no; ficheros uno a uno** (había trabajo ajeno sin commitear en `docs/BOT_EJECUCION_*.md`).

---

## 2026-09-12 (Sailor) — Modo Scalping: la entrada abre una ventana, la salida la cierra, y dentro cada gatillo es una operación

**Qué es.** Un bloque opcional `scalping` en la definición de la estrategia (en la UI, entre «Salida lógica» y «Piramidación»). Con él encendido:
- La **Entrada Lógica ya no entra: abre la ventana** de scalping en ese ticker-día. La **Salida Lógica la cierra** (y cierra la operación que hubiera abierta). Si la entrada vuelve a cumplirse después, se reabre.
- Dentro de la ventana, **cada flanco del gatillo** (`root_condition`, el mismo árbol de condiciones que entrada/salida, con su timeframe) es una entrada, con **reentradas ilimitadas** (`accept_reentries=True, max_reentries=-1` forzados).
- **Stop loss y take profit son los de la estrategia**, sin cambios. Además: `max_minutes` (salida por tiempo, pisa el take profit «Time» si lo hay; 0 = no pisa), `cooldown_bars` (pausa tras cada salida; 0 = ninguna) y `capital_pct` (% de la cifra de capital/riesgo del panel que usa CADA scalp; 100 = la cifra entera, como una entrada normal; se aplica escalando `risk_r` al simular, así que vale para los tres modos de tamaño y no toca el simulador). No hay techo de exposición aparte: nunca hay dos scalps abiertos a la vez, así que el expuesto ES la cifra por entrada (Jaume lo pidió y lo retiró él mismo al verlo).
- La ventana horaria de entradas (`entry_time_windows`) vale también para cada operación, como con las pirámides.

**Regla nº1, cumplida y probada.** Sin la clave, o con el gatillo sin condiciones, `compile_strategy_def` deja `scalping=None`, `translate_strategy` devuelve lo de siempre, y en `simulate` no se ejecuta ni una rama nueva (`reentry_cooldown_bars=0` por defecto). Suite completa: 1.151 pasan; los 2 fallos son los del backend levantado (DuckDB).

**Dónde vive (para no perderlo en las tres capas).**
- Motor: `strategy_engine.compile_strategy_def` (parsea el bloque, `has_special=True` → va SIEMPRE por el traductor clásico, el nativo no sabe del bloque), `ventana_scalping`, `aplicar_scalping`, `scalping_tp_time_limit`, y `translate_strategy` (sustituye `entries`, pisa `tp_time_limit`, fuerza reentradas, devuelve `reentry_cooldown_bars`).
- Simulador: `portfolio_sim.simulate(reentry_cooldown_bars=0)`: un `if` en la puerta de entrada que mira `trades[-1]["exit_idx"]`. `sim_dispatch` desvía al Python si es > 0 y retira el kwarg antes del JIT.
- Tres caminos: `backtest_service` (secuencial, con la caché de señales de la optimización: ahí se re-parsea el riesgo y hay que volver a pisar el `tp_time_limit`, por eso existe `scalping_tp_time_limit`) y `backtest_signals` (paralelo y slab). El what-if de la pérdida diaria re-simula con copia de los kwargs, así que le llega solo.
- Persistencia: `schemas/strategy.py::StrategyCreate.scalping` (dict opaco) y los dos sitios de `routers/strategies.py`.
- UI: `ScalpingBuilder.tsx` (nuevo, calcado de `PyramidingBuilder`), `InlineStrategyBuilder` (estado, firma, rehidratación, `scalpingForPayload`, reset, render), `page.tsx` (12 sitios, los mismos que `advanced_model`), `types/strategy.ts` (`ScalpingBlock`, `ScalpingConfig`, `initialScalping`), y el resumen del `BacktestPanel` («SCALPING: gatillo con N condiciones · salida a los M min · pausa de K velas»).
- Tests: `backend/tests/test_scalping.py` (21): regla nº1, ventana, translate, pausa + dispatch, esquema y `run_backtest` entero (normal = 1 operación/día; scalping = varias, ninguna más larga que la salida por tiempo).

**Decisiones tomadas con Jaume (12-sep).** Todo en %, no en centavos (el motor ya trabaja así; el spread se mira por tramos de precio en los resultados). Relleno al open de la vela siguiente, como siempre (no se expuso `mid`/`worst`). Locates y costes como están: «los costes son los costes». Va vela a vela de 1 minuto; nada por tick (sin quotes no hay spread, y sin spread un backtest sub-segundo se inventa el edge: Roll 1984). Un gatillo que se cumpla varias velas seguidas cuenta UNA vez (flanco), como cualquier entrada del motor.

**Lo que NO está hecho / avisos.**
- **El bot en vivo** usa `translate_strategy`, así que una estrategia con `scalping` marcada para el bot avisaría en cada gatillo dentro de la ventana, pero **sin salida por tiempo ni pausa** (su `_kwargs_simulate` no pasa `reentry_cooldown_bars`; no se ha tocado nada de `bot_alerts_*`). Hasta adaptarlo: **no marcar estrategias de scalping para el bot.**
- `StrategyForm.tsx` (la página `/strategies/new`) no tiene el bloque; solo el constructor del backtester.
- `strategy_explain.py` («qué hace esta estrategia») no describe el bloque; `SharedStrategiesTab` lo vuelca en «Otros ajustes».
- El NBBO (spread real) queda para más adelante por decisión de Jaume; Massive SÍ da quotes (`Q.*` y `/v3/quotes`) si el plan es el «Advanced»; no comprobado.
- Primeras estrategias que se quieren probar: ORB de 5 minutos (hay literatura: Zarattini & Aziz 2023-24) y «caja tras el spike con fallo de ruptura» en corto. El indicador **Darvas Box ya existe** en el repo (`indicators.py`, 22-ago) y sirve de gatillo.

**Estado.** Fusionado en `sailor-rama-desarrollo` (`9e11fa8` motor+UI, `0d630d1` docs, `0f4a61f` capital por entrada) con permiso de Jaume, con el bot vivo; el `--reload` tardó ~1 min y el bot sobrevivió. Sin subir.

### Modo «Complejo»: la escalera (misma tarde)

Jaume separó claramente «piramidación = reglas sueltas por condiciones» de «scalping = siempre lo mismo, mecánico». Con `scalping.mode = "complex"` y un bloque `ladder`, dentro de cada scalp actúa una **escalera** (`backend/app/services/escalera.py` + `portfolio_sim.simulate(ladder=None)`):
- **Paso** X %: desde el **último nivel ejecutado** (malla entera sobre el precio de la primera entrada: nivel k = entrada0 × (1 ± k·paso), k>0 a favor). Lo que se hace depende de la **dirección del movimiento**, no del signo de k (volver de +2 a +1 es «en contra»).
- **A favor** y **en contra**, cada uno: añadir | quitar | nada, con cantidad en **$ fijos** o **% de la posición INICIAL** (fijo: cada escalón el mismo tamaño).
- **Core** (suelo, $ o %): al quitar nunca se baja de ahí; 0 = puede vaciarse → el scalp queda cerrado y el siguiente gatillo abre otro. **Tope** (techo, $ o %): al añadir nunca se pasa; 0 = manda la caja. **Recorrido máximo** desde la entrada: fuera de él la escalera no actúa y manda la salida principal. La salida principal (salida lógica, stop, TP, tiempo) siempre cierra todo.
- **Rearmar niveles** (opción B de Jaume): OFF = cada (nivel, dirección) se ejecuta una vez por scalp (añadir al bajar a 9,90 no gasta el quitar al volver a subir por 9,90; una segunda bajada a 9,90 ya no añade); ON = grid, cada cruce opera.
- **Stop y take profit en % sobre el precio MEDIO** (decisión de Jaume): tras cada añadido `entry_price` pasa a ser la media (las fórmulas de salida leen `entry_price`); añadir en contra ALEJA el stop. En el trade el `entry_price` registrado es la media, no el fill (la piramidación clásica ancla al fill; aquí no, por diseño).
- **Relleno** al precio del nivel (limitada que descansa ahí) con slippage adverso, en la vela cuyo high/low lo toca; una vela grande procesa varios niveles, primero el lado que la vela visitó antes (`orden_lados`). Añadidos respetan cortacircuitos diario, tope de caja y locates como la piramidación; las quitas son legs `exit_reason="Escalera"`; la bitácora viaja en `escalera_executions` del trade de cierre (y `_enrich_trades` la propaga).
- **Regla nº1:** `ladder=None` (modo simple o sin bloque) → ni una rama nueva; `parse_escalera` devuelve None si el paso no es positivo o las dos direcciones son «nada». `sim_dispatch` desvía al Python. Se lleva por `translate_strategy["ladder"]` → `sig_ladder` en los dos bucles y en la caché de señales.
- **UI:** «Modo: Simple | Complejo (escalera)» en el bloque Scalping; el panel de la escalera con un «?» explicativo en cada campo (petición de Jaume); resumen del BacktestPanel con la línea ESCALERA. Tests: `test_escalera.py` (19: regla nº1, cálculos puros, ejemplo de Jaume, A vs B, core, vaciado + reentrada, tope y recorrido, $ fijos, stop sobre la media, corto, salida principal, dispatch, `run_backtest`). Suite 1.171 pasan.
- **Gráfico y diseño (misma tarde, a petición de Jaume):** `_build_executions` incluye las `escalera_executions` con `escalera: True` y el gráfico las pinta como **triángulos pequeños** (`size: 0.6`): añadido debajo de la vela, quita encima, flecha en el sentido de la orden (compra arriba, venta abajo; al revés en corto), cobre/ámbar como la piramidación. Y el bloque Scalping se rehizo **sobrio**: filas «etiqueta (150 px) | control», sin cajas dentro de cajas, altura 32 px, el `InfoTooltip` «(?)» estándar de la app en cada campo y subtítulos de sección (ESCALERA, GATILLO) con línea inferior; Jaume dijo que el anterior «parecía hecho con IA».
- **No hecho:** el bot ignora la escalera (decisión de Jaume: el bot no usará scalping). Sin probar escalera + piramidación + parciales a la vez.

---

## 2026-09-10 (Sailor) — Los stops dejan de mentir, último pivote y perfil de volumen

Diez commits, del `1ed3d7e` al `5b77e52`, en `sailor-rama-desarrollo` y `staging`.

### ⚠️ Tres stops que daban números equivocados sin avisar

**`ATR Multiplier` miraba al futuro.** Calculaba la distancia como
`media del ATR del DÍA ENTERO / primer cierre del día`, y esa media incluye
barras POSTERIORES a la entrada. Medido sobre un día que explota por la tarde:

| Entrada | Stop del motor | ATR real de esa barra | |
|---|---|---|---|
| barra 30 (mañana) | 3,88 % | 0,85 % | **4,6× más ancho** |
| barra 350 (en la explosión) | 3,88 % | 19,29 % | 5× más estrecho |

Ahora el nivel se resuelve en la barra de ENTRADA, `entrada ∓ k × ATR[i]`, por la
misma vía que el estructural. Con ATR 1 salen 150 acciones y con ATR 6 salen 25;
antes las dos entradas del día compartían fracción.

**`Fixed Amount` dividía por el cierre de la primera vela del día.** Así que
«15 centavos» solo eran 15 centavos si entrabas al precio de apertura. Con un
día que abre en 70 y entrada en 100, pedir 5 $ daba un stop en 107,14 en vez de
105 — un 43 % más ancho. Este NO está en la UI, así que no afectaba a nadie; se
arregla ahora que la maquinaria de niveles existe.

**El respaldo del stop estructural era un 5 % clavado**, y escrito TRES VECES por
separado (portfolio_sim, el kernel JIT y el bot). Ahora es
`hard_stop.struct_fallback_pct`, y sin él sigue siendo 5.

Los tres pasan por `size_by_sl`, el techo híbrido y Cangrejo A y B, porque todos
miran `stop_loss_price` y no la fracción. Portados al kernel JIT con paridad
0,00e+0: sin eso, con `BACKTEST_NUMBA_SIM=1` se habrían ignorado EN SILENCIO por
la vía rápida.

**Y el bot los entiende.** `stop_estimado` resolvía todo lo no estructural como
`precio × (1 ∓ sl_stop)`; sin tocarlo habría avisado con un stop distinto del que
se backtestea, sin error — el mismo patrón que el factor 4 del 8-sep.

### El ATR, unificado

El motor suavizaba con EMA `2/(n+1)` y el gráfico con Wilder `1/n`: coincidían en
el primer valor y se separaban desde el segundo. Los dos usan ya **Wilder**, que
es el ATR canónico. Toca el indicador `ATR`, el stop y `ATR Extension` a la vez.

> Se dijo también que el **VWAP** del gráfico divergía del motor. **Era falso**:
> solo diverge cruzando medianoche UTC, y un ticker-día real nunca la cruza.

### Indicadores nuevos

**`Último pivote`** — el último sitio donde el precio giró de verdad, como
indicador Y como nivel de stop. No es `Previous max`: aquel es el máximo corrido
y nunca baja. Con 10 → 15 → 12 → 14 → 11, `Previous max` se queda en 15 para
siempre; el pivote alto es 14 y el bajo es 12.

Es causal aunque mire a la derecha: en la barra `i` se confirma el pivote
centrado en `i - win`, así que el nivel aparece `win` velas DESPUÉS. Ese retardo
es inevitable — hasta que no pasan velas no se sabe si un máximo era un techo.

**Perfil de volumen intradia** — seis indicadores del mismo cálculo:
`Vol. de la franja` (percentil, una medida) y cinco niveles: `Punto de control`,
`Nodo de arriba`, `Nodo de abajo`, `Zona alta` y `Zona baja`.

Franjas de ANCHURA FIJA (% del primer precio del día), no el rango partido en N:
con bordes móviles habría que rehacer el histograma en cada vela. Y el LISTÓN
(% del volumen del POC) en vez de fijar cuántas zonas hay — un perfil real suele
tener dos crestas y el POC solo señala una.

**La distinción que hay que tener clara**: los NODOS son relativos al precio (la
primera zona por encima/debajo de donde estás), así que saltan cuando el precio
cruza una franja. La ZONA DE VALOR no mira el precio: son las bandas del día.
Medido en OLB: la zona alta cambia 22 veces en 223 velas y el nodo 43.

Validado reconstruyendo OLB del 9-sep desde las grabaciones del bot: el nodo de
abajo desaparece a las 13:33 y desde ahí el precio cae de 0,39 a 0,34.

### Interfaz

- El gráfico del trade se **despliega bajo su fila** en Trades y en Calendario,
  sin salir de la pestaña. Dentro hay un botón para abrirlo en grande.
- El desplegable de indicadores del gráfico enseña **una línea explicando qué
  mide** cada uno.
- El bloque del stop no cabía en el panel (seis controles en fila, ~230 px): pasa
  a `flex-wrap` con anchos flexibles. Y el respaldo solo se enseña donde puede
  hacer falta — con HOD o LOD el nivel existe siempre.
- El desplegable de stops ofrece **`ATR`**, que nunca había estado pese a existir
  en el enum desde siempre.

### El bot, suelto del backend

`_arrancar_bot()` lo lanzaba como HIJO del worker de uvicorn, así que un
`taskkill /T` se lo llevaba y cada `--reload` lo dejaba en el aire. Con
`DETACHED_PROCESS` tiene vida propia. Su feed no depende del backend.

### ⚠️ HALLAZGO SIN ARREGLAR: el log filtra el token de Telegram

`httpx` registra en INFO la URL completa, y la API de Telegram lleva el token
DENTRO de la URL. Medido: **291 líneas con el token en claro** en un solo
arranque redirigido a fichero. `bot.py:112` lo silencia; el backend no tiene nada
equivalente. Se arregla con una línea en `app/main.py:281`, y cierra de paso el
pendiente de rotar la clave de Massive — es el mismo mecanismo.

### Tests

De 992 a **1.076**, 115 saltados, 0 fallan. Lo nuevo cubre: los tres stops
cruzando el tamaño del AVISO contra el del SIMULADOR, paridad Python↔JIT en cada
uno, paridad gráfico↔motor de los seis del perfil (0,00e+0 sobre 320 velas
dispersas) y **causalidad**: el valor en la barra `i` sale igual con el día
entero que con la serie cortada ahí.

---

## 2026-09-09 (Sailor) — Ocho indicadores nuevos en el bloque «Alternativos» + el stop por ATR mira al futuro

### Lo que entra (commit `f1a5764`, en `sailor-rama-desarrollo` y en `staging`)

Ocho indicadores, todos **medidas** (solo se comparan contra una cifra) y todos
disponibles en **entrada, salida y piramidación**. Van en un bloque propio del
desplegable, `Alternativos`, a petición de Jaume: mezclados con SMA o RSI se
esconden.

| Indicador | Qué devuelve |
|---|---|
| `Reg. Slope` | Pendiente de la recta OLS sobre el precio, en **%/minuto** |
| `Reg. R2` | Calidad del ajuste de esa misma recta, 0 a 1 |
| `ATR Extension` | Distancia a una referencia, en ATRs |
| `Time vs Level` | Minutos SEGUIDOS por encima/debajo de un nivel |
| `Absorption` | Millones de $ por cada 1% de desplazamiento **neto** |
| `Wick Ratio` | Fracción del recorrido devuelta en mecha, 0 a 1 |
| `Absorption + Wick` | 1 si se cumplen los dos umbrales, 0 si no |
| `Retroceso (%)` | Fracción del impulso ya devuelta, en % del impulso |

### Las decisiones que no son obvias

**La pendiente va sobre el PRECIO, no sobre una media.** Una EMA es un filtro
causal y va retrasada (la pendiente de la EMA(20) cuenta lo de hace ~10 velas);
la recta de mínimos cuadrados suaviza igual sin retraso, y de paso suelta el R2
del mismo ajuste. Sale normalizada en %/minuto para que el mismo umbral valga en
un ticker de 0,60 $ y en uno de 45 $.

**La absorción divide por el desplazamiento NETO, no por el rango.** La primera
versión usaba `high-low` y una vela de absorción **con mecha larga puntuaba
BAJO** (0,272 frente a 0,305 de una vela normal), justo al revés de lo que se
busca. Con el neto, el mismo muro pasó a **5,72**. Y así deja de pisarse con
`Wick Ratio`: una mide el dinero y la otra la forma, que es lo que hace útil
combinarlas.

**El retroceso NO usa detección de pivotes, a propósito.** Un pivote clásico
mira N barras a la DERECHA, así que en la barra `t` no se sabe todavía que `t-N`
era un pivote: usarlo sería mirar al futuro. El impulso se define solo con
pasado (máximo corrido + mínimo anterior a ese máximo) y se reinicia cada día.

**Los umbrales por defecto están MEDIDOS, no inventados.** Reconstruidas 2.476
velas de minuto desde las grabaciones del bot (10 tickers, 8-9 sep). Absorción:
p50 = 0,26 · p90 = **2,62** · p95 = 5,08. Mecha superior: p50 = **0,21** ·
p90 = 0,37 · p95 = 0,43. El dato que ahorra un error: **la mediana de la mecha
es 0,21**, o sea que en un día normal siempre se devuelve una quinta parte del
recorrido y eso no significa nada. Pedir «> 0,5» dejaría fuera al 97% de las
lecturas y no dispararía casi nunca.

### Verificación

Vía del motor real (`_compute_from_config`), no solo el cálculo del gráfico ·
clave de caché que separa configuraciones · `has_special=True` (van por la vía
clásica, como Squeeze y los fades) · **paridad gráfico↔motor exacta**
(0,00e+0 sobre 280-300 velas dispersas) · `tsc --noEmit` limpio · 83 tests.

### ⚠️ Hallazgo sin arreglar: el stop `ATR Multiplier` mira al futuro

```python
avg_atr = pd.Series(atr_arr).dropna().mean()   # media del ATR de TODO el día
sl_stop = (avg_atr * hs_value) / float(C[0])   # fracción FIJA para todo el día
```

La media incluye barras **posteriores a la entrada**. Medido sobre un día que
explota en la barra 330: una entrada de la mañana recibe un stop **4,6× más
ancho** del que le tocaría, y dentro de la explosión 5× más estrecho. Además no
es un stop por ATR: es una constante diaria, igual entres a las 07:00 o a las
09:31.

**No se arregló en esta sesión a propósito**: toca `portfolio_sim.py`,
`strategy_engine.py` y `market_frame.py`, que comparte el bot en vivo. Dos cosas
que hay que saber antes de meterle mano:

1. **No cabe en `sl_stop`**, que es un escalar. Un ATR por barra tiene que ir por
   la vía del nivel, como el stop estructural (`_structural_level`).
2. **El bot se rompería en silencio**: `bot_alerts_engine.py:399` resuelve todo
   lo no estructural como `precio × (1 ∓ sl_stop)`. Cambiar el backtest sin
   tocar el bot lo dejaría avisando con un stop distinto del que backtestea.
   El test `tests/test_bot_tamano_todos_los_stops.py` existe justo para cazar eso.

Jaume confirmó que **no usa ninguna estrategia con ATR ahora mismo**, así que se
puede arreglar el tipo existente sin respetar compatibilidad hacia atrás.

### Otro hallazgo menor, también sin arreglar

`calculateATR` del gráfico usa el suavizado de **Wilder** (`1/n`) y el motor una
**EMA** (`2/(n+1)`): coinciden en el primer valor y se separan desde el segundo.
Arreglarlo cambiaría todos los gráficos que ya lo usan, así que se dejó y
`calculateAtrExtensionVwap` replica las fórmulas del motor en local, con el
porqué escrito al lado para que nadie lo «simplifique» luego.

> Se dijo por el camino que el **VWAP** del gráfico también divergiía por
> reiniciar en día UTC. **Era falso**: solo diverge cruzando medianoche UTC, y un
> ticker-día real (04:00-20:00 NY) nunca la cruza. El VWAP está bien.

### Pendientes que salen de aquí

- **Stop por ATR de verdad** (lo importante). Receta arriba.
- **Perfil de volumen intradía**: zonas de acumulación por franjas de precio, en
  vez de puntos como PMH/LOD. Diseño hablado, sin cerrar.
- **«Ultimo pivote» como nivel de stop**: distinto de `Previous max`, que es el
  máximo corrido y nunca baja (10→15→12→14→11: previous max = 15 para siempre,
  último pivote alto = 14, último pivote bajo = 12).
- **Microestructura**: el tamaño medio de operación (campo `z` del canal `A`) ya
  se graba solo cada día que corre el bot. El spread **no** sale de ahí ni a
  posteriori: necesita otro canal, y a ser posible en un proceso aparte del bot.

---

## 2026-08-23 (Sailor) — ⚠️ `staging` PASA A SER LA VERSIÓN DE SAILOR + piramidación y auditoría del motor

> **LÉEME ENTERO ANTES DE TRABAJAR SOBRE `staging`.** Este push **sustituye el
> contenido de `staging` por el de `sailor-rama-desarrollo`**. Decisión expresa
> de Jaume: *«lo que manda es lo nuestro ahora mismo, porque quizás son cosas
> antiguas — por ejemplo el tema de comisiones ya se resolvió y está bien como
> lo tenemos nosotros»*.
>
> **NO se ha perdido nada del repositorio.** Se hizo con un merge que **conserva
> todo el historial de Álvaro como ancestro**, no con un force push. Los commits
> siguen siendo alcanzables por hash y esta nota los lista uno a uno.

### 1. Qué se ha retirado del árbol (y cómo recuperarlo)

Para ver cualquiera: `git show <hash>`. Para recuperar un fichero suelto:
`git checkout <hash> -- <ruta>`.

| Commit | Qué era |
|---|---|
| `f281a20` | nota de Sailor sobre el Darvas (documentación) |
| `ab1480c` | Darvas Box — **ya está en la versión de Sailor**, no se pierde |
| `1b8e3f3` | memoria + ALVARO_CAMBIOS del ITEM 4 |
| `cd455ae` | **fix de fees ITEM 4** (entrada cobrada cuando el cierre es 100% por parciales) |
| `ff276ef` | nota de Sailor del 22-ago (documentación) |
| `9d24781` | módulo de Portfolio (versión de Álvaro) |
| `2e06d94` + `78a6b82` + `1ec8ce9` | **fix del no-determinismo del universo (70R↔137R)** |
| `c59684b` | retractación del bug del picker de robustez |

**Lo que SÍ se ha conservado en el árbol** (restaurado a propósito): toda la
documentación de Álvaro (`ALVARO_CAMBIOS/`, `docs/MEMORIA.md` —esta—,
`BASELINE_TESTS_BACKEND.md`, los dos informes del 21-ago,
`MODULO_PORTFOLIO_GUIA_INTEGRACION.md`, `PRD_DIVERGENCIA_*`, `PROXIMOS_ITEMS`,
`fix-locates-attribution/PRD.md`, `mockup_parciales_fade.html`), los scripts
`arrancar_local.bat` / `parar_local.bat`, y los tests `test_bygap_parity`,
`test_current_gap_semantics`, `test_fade_partials`, `test_fees` y
`test_trail_break_even`.

⚠️ **Dos avisos concretos sobre lo conservado:**

1. **`test_fees.py` y `test_trail_break_even.py` van a FALLAR**, y es esperado:
   verifican comportamientos que la versión de Sailor ha cambiado a propósito
   (§3). No están rotos; describen el modelo anterior. Decidid si adaptarlos.
2. **`frontend/src/lib/tradesCsv.ts` se ha tenido que retirar**: usa campos de
   `TradeRecord` que solo existen en la versión de Álvaro (`legs`,
   `partials_skipped`, `exit_reasons`, `stop_loss`) y **rompía la compilación**
   contra el tipo de Sailor. Está en `cd455ae` y anteriores.

**También desaparece el Baúl** (`frontend/src/app/database/` y
`components/database/`): Sailor lo borró a propósito al construir la página de
Portfolio y su entrada de menú ya no existe. No es un descuido.

**Y se limpian 28 ficheros `.parquet`** commiteados en
`backend/app/.cache/intraday/`. Eran datos de caché que no deberían estar en el
repo — la propia regla de esta memoria lo dice: «nunca commitear datos».

### 2. Qué entra: la PIRAMIDACIÓN

Bloque nuevo `pyramiding` en la definición de estrategia: permite **añadir o
quitar posición con la operación abierta**, con el mismo editor de condiciones
que entrada y salida.

> 📄 **La especificación completa está en
> `docs/PRD_PIRAMIDACION_Y_AUDITORIA_MOTOR.md`**, que entra con este push:
> semántica punto por punto, contrato de datos JSON, los cuatro caminos del
> motor que hay que mantener en paridad, los siete fallos con sus cifras
> medidas, lo que se decidió NO tocar y **10 cifras de control** para verificar
> una implementación propia sin compartir un byte de datos.

Resumen (todas son decisiones de Jaume, no criterios de la IA):

- **Añadir** = % del equity **o** cifra fija en $. **Quitar** = % de la posición
  flotante **o** $ de nocional.
- **Todo se ejecuta en la vela INMEDIATAMENTE SIGUIENTE** a la que cumple la
  condición — norma fija para entradas, añadidos y reducciones.
- **TP parciales**: base = **inicial + añadido − reducido**, sin descontar los
  parciales ya tomados. Sin piramidar, 50%+50% cierra el 100%.
- **SL y TP completo** se llevan **toda la posición viva**; sus NIVELES siguen
  anclados a la entrada original, así que un trade piramidado **puede perder
  varias R** al saltar el stop. Es deliberado.
- **Secuencial** = lineal, del nivel 1 al 2, sin volver atrás. **Individual** =
  cada nivel por su cuenta. Una reentrada rearma la secuencia entera.
- **Regla nº1**: sin la clave `pyramiding`, el backtest es **bit-idéntico** al
  de antes. Verificado.

### 3. ⚠️ CUATRO CAMBIOS QUE TOCAN EL MOTOR COMPARTIDO

**Esto es lo que más os afecta.** Un backtest guardado antes de hoy puede dar
números distintos al repetirlo:

| Cambio | A quién afecta |
|---|---|
| **El stop fijo manda sobre el trailing.** El trailing no comprobaba si el stop fijo ya había disparado en esa barra; como se mueve con el máximo de la propia vela, **una vela que tocaba el stop podía registrarse como salida EN BENEFICIO** (+1 donde correspondía −2) | cualquier estrategia con trailing **y** stop fijo |
| **Un comparador desconocido ya no se evalúa como "mayor que".** Antes `_apply_comparator` acababa en `return source > target`: una condición que dijera "menor que" podía ejecutarse como "mayor que" —entrando justo en los máximos— sin error ni rastro. Ahora se **desactiva** y se registra | definiciones mal formadas (antes daban resultados falsos y creíbles) |
| **Un CRUCE en timeframe superior solo vale la primera barra de 1m.** Antes duraba todo el tramo, así que un "cruza por debajo" en 5m permitía entrar hasta 4 minutos después del cruce. Los ESTADOS (`<`, `>`) siguen durando, que es lo correcto | estrategias que mezclen temporalidades **con cruces** |
| **`entry_price` pasa a ser el fill REAL de la entrada**; el precio medio ponderado va ahora en `avg_entry_price`, que es el que gobierna el PnL | cualquier consumidor que usara `entry_price` para calcular capital o rentabilidad |

Las estrategias 100% en 1m, sin trailing y sin piramidar **no se ven afectadas**.

### 4. Sobre el fix de fees (`cd455ae`) que se retira

Jaume lo da por resuelto: *«el tema de comisiones ya se resolvió y está bien como
lo tenemos nosotros»*. La versión de Sailor cobra **`fees × acciones × 2`** (por
acción, los dos lados) y **registra la comisión de los tramos parciales**, que
era el «quirk B» que quedaba abierto entre vosotros. En magnitud total
coincidís; lo que cambia es el reparto entre filas. Si detectáis una diferencia
real, está `cd455ae` para comparar.

### 5. Cómo se verificó que no se rompía nada

La suite local sin GCS arrastra ~119 fallos preexistentes, así que **«pasan los
tests» no significa nada**. El método que sí sirve, y que recomendamos adoptar:
ejecutar la suite y guardar la **lista de nombres** en rojo; `git stash` de los
ficheros tocados; ejecutar otra vez; `git stash pop` y **restar las listas**.

Esa comparación delató 6 tests de equivalencia rotos a mitad del trabajo —por
tocar solo uno de los cuatro caminos del motor— que el recuento global (125 vs
119) habría dejado pasar como ruido. Corregidos, el resultado final es **119
fallos con los cambios y 119 sin ellos, 0 rotos**, más 30/30 en las suites de
paridad de motores, 600 escenarios aleatorios de trailing+stop sin divergencias
y `tsc --noEmit` con 0 errores.

---

## 2026-08-22 — ITEM 4 fees (reporte de Sailor) + merge Portfolio de Jaume

**Qué pasó**
- Sailor reportó por WhatsApp (07:28): "tus comisiones se calculan por shares,
  debería ser 2×shares porque compra Y venta cobran". Cotejo contra el código:
  el modelo por-fill del ITEM 2 **ya cobra los dos lados** en el camino normal
  (round trip = 2×rate×shares, testeado), pero el reporte destapó un **agujero
  real**: si la posición cierra **100% por parciales**, el bloque de cierre
  final nunca corre y **la entrada no se cobra** (1.000 acc FLAT $0.01 →
  pagaba $10 en vez de $20; verificado empíricamente).
- Además: la nota de Sailor en staging (`ff276ef`) **cierra el desacuerdo
  FLAT** ("coincidimos") y avisa de que él corrigió el quirk B (parciales sin
  clave `fees`) **en su rama** — no en staging. Decisión: NO duplicar su
  corrección aquí (evitar conflicto); se adopta cuando su rama llegue.

**El fix (ITEM 4, commit `cd455ae`)**
- Diseño de **mínima superficie bit-preserving** (dirigido por el revisor en
  directiva escrita): el bloque de cierre final queda **intacto** (fórmula
  combinada `(original_size + size)`); solo el parcial que **liquida la
  posición** (`(size − pt_size) <= 0.0001`) añade el lado de entrada UNA vez
  (flag `entry_fee_charged`, reset por apertura). Orden FP fijo: salida
  primero, luego `+=` entrada. Aplicado a los 5 bloques de parciales en
  `portfolio_sim.py` + espejo exacto en `portfolio_sim_jit.py`.
- Tests: T-A (1 parcial 100%) y T-B (50+50) rojo→verde; T-C/T-D
  (anti-doble-cobro, valores **bit-idénticos** a hoy en los caminos que ya
  funcionaban) verdes; paridad JIT del caso nuevo. 17+54 passed, 0 rojos
  nuevos.
- Vestigio `entry_fee_amount` eliminado.

**⚠️ Interacción con el quirk B de Sailor (dejar avisado)**
Con este fix, cuando el cierre es 100% por parciales, el fee de entrada vive
dentro del `pnl` de la leg que cierra pero NO en su clave `fees` (que no
existe — quirk B). Cuando la corrección del quirk B de Sailor llegue a
staging y exponga `fees` por leg, esa leg deberá reflejar salida + entrada
absorbida, o su `fees` no reconciliará con su `pnl`. Avisado en
`ALVARO_CAMBIOS/README.md`.

**También en la sesión**
- FF-merge de `origin/staging` ×2: `9d24781` (módulo **Portfolio** de Jaume —
  baúl, escalado, monitorización, página `/portfolio`) y `ff276ef` (nota de
  Sailor en MEMORIA, commiteada por Jaume).
- Push a staging de este fix: gate de confirmación de Álvaro al cierre de la
  sesión (regla de oro #3).

---

## 2026-08-22 (Sailor, 2ª) — Indicador nuevo: Darvas Box (código incluido en esta rama)

**Esta vez sí entra CÓDIGO en `staging`**, a petición explícita de Sailor: el
indicador **Darvas Box** completo (backend + builder de condiciones + dibujo en
el gráfico). Es aditivo: no toca ningún comportamiento existente — añade un
indicador al catálogo y nada más. El motor no se modifica: entra por el path
legacy de `strategy_engine` (el gate de `_RAW_INDICATOR_DISPATCH`), como
cualquier indicador no-nativo.

**Qué es:** máquina de 3 estados (buscar techo → buscar suelo → caja
consolidada) según la especificación clásica de Darvas. Las MECHAS construyen y
validan los niveles; solo un CIERRE fuera destruye la caja. Devuelve un NIVEL
por vela (como Donchian): `period` = velas de confirmación, `band_line` =
Upper (resistencia) / Lower (soporte) / Basis. NaN mientras no hay caja; la
vela que rompe aún emite el nivel para que el cruce sea detectable ahí. Causal,
sin lookahead.

**Dónde tocarlo si hace falta:**
- `backend/app/services/indicators.py` — `_darvas_box_core` (njit) + rama
  "Darvas Box" en `_compute_raw` + alias en `INDICATOR_NAME_MAP`.
- `frontend/src/lib/indicators.ts` — `calculateDarvasBox` (serie causal) y
  `calculateDarvasBoxes` (rectángulos para dibujar). ⚠️ **PARIDAD OBLIGADA**
  entre esta versión TS y la de Python: una decide señales, la otra se dibuja.
  Si se toca una, tocar la otra (verificada: 0 diferencias en 400 velas ×
  N=2/3/5).
- `frontend/src/components/backtester/Chart.tsx` — el `case "DARVAS"`: dibuja
  el rectángulo completo de cada caja (formación atenuada, tramo operativo
  sólido), una serie de 2 puntos por línea. Ojo: el *whitespace* de
  lightweight-charts NO corta una línea (lección pagada: salían los techos de
  todas las cajas unidos en diagonal).
- `ConditionBuilder.tsx`, `indicatorValidation.ts`, `types/strategy.ts`,
  `indicatorRegistry.ts` — catálogo, cruces permitidos (está en
  `ALL_INDICATORS`: cruzable contra cualquier variable) y parámetros.

**Verificación hecha en la rama de Sailor:** 5 escenarios de la especificación
en tests a mano (incluido «mecha fuera no rompe, cierre fuera sí»), backtest
real de cruce con 704 trades, y 23/23 rectángulos de un día real conteniendo
todas sus velas. En esta rama: `py_compile` + smoke del indicador + `tsc` sin
errores en `src/`.

---

## 2026-08-22 (Sailor) — Actualización del lago en un botón + FLAT por acción (coincidimos) + 4 bugs del motor

> Entrada informativa: **no se ha subido código a `staging`**, solo esta nota.
> Todo está en `sailor-rama-desarrollo`, commit `9c76e6b`. El resumen técnico
> para decidir qué adoptar está en `docs/CAMBIOS_SAILOR_PARA_STAGING.md` de esa
> rama.

**Comisiones FLAT: hemos llegado al mismo sitio por caminos distintos**

Sailor pidió que FLAT fuera **$ por acción, cobrado en la compra y en la venta**
(su ejemplo: 0,003 con 100 acciones = 0,30 € + 0,30 € = 0,60 €). Nuestra rama
tenía todavía `fees × 2` — cantidad fija por operación que ignoraba el tamaño.
Cambiado a `fees × acciones × 2` en los cuatro motores (14 puntos).

**Esto ya no choca con vuestro ITEM 2 del 08-21**: vuestro modelo por fill
—entrada de `original_size` + salida de cada tramo— **da exactamente el mismo
total**, `fees × acciones × 2`. Cambia solo el reparto entre filas (vosotros
cargáis la entrada entera en el cierre final; nosotros repartimos
proporcionalmente). El punto abierto de la semántica de FLAT se puede dar por
cerrado: coincidimos en magnitud y en significado, y los dos hemos reetiquetado
la UI ($/share ↔ $ por acción).

**Donde SÍ divergimos: el "Quirk B"**

Vosotros lo mantuvisteis a propósito (parciales sin clave `fees`). Nosotros lo
hemos corregido, porque con comisiones por acción deja de ser cosmético: la
comisión del tramo parcial se resta del `pnl` pero se reporta como `0`, y el
agrupador de ejecuciones de `backtest_service` la pierde. Medido sobre 396
trades reales a 0,003 $/acción: la columna mostraba **75 $ de los 114 $
cobrados**, un 34 % de menos. Con comisiones fijas de céntimos era invisible; con
las nuevas no. Tocado en `portfolio_sim_jit.py`, `portfolio_sim.py` y
`sim_dispatch.py`. **Solo afecta al informe; el PnL siempre estuvo bien.**
Si adoptáis nuestro cambio, vuestro `test_fees.py` habrá que actualizarlo: los
tests que afirman "parciales sin clave `fees`" pasarían a fallar a propósito.

**Otros tres bugs del motor compartido, corregidos**

1. **Sortino** (`backtest_service.py`, 2 sitios): usaba `np.std` de solo los
   retornos negativos —medidos alrededor de su propia media y sin dividir por el
   total—, dos sesgos que lo inflan. A downside deviation canónica,
   `sqrt(mean(min(ret,0)²))`, que es lo que ya hacía el módulo de portfolio. La
   misma estrategia mostraba dos Sortinos distintos en dos páginas de la app.
2. **`build_screener_query`**: `require_shortable` y `exclude_dilution` son
   interruptores de la UI, no columnas de `daily_metrics`; pero `float(True)`
   vale 1.0, así que se colaban por el camino numérico y generaban
   `require_shortable >= 1.0` → `BinderException` que tumbaba la consulta
   entera. Cualquier dataset guardado con esos filtros fallaba al recalcular sus
   pares. Una línea: `if isinstance(v, bool): continue`.
3. **Sondeo del backtest** (`frontend/.../backtester/page.tsx`): el registro de
   trabajos vive en memoria; si el backend se reinicia a media corrida el
   `job_id` desaparece y el 404 permanente se trataba como "error de red
   pasajero", reintentando cada 500 ms **indefinidamente**. Ahora se toleran 3
   seguidos y luego para con un mensaje claro.

**Dos avisos que aplican también a producción**

Los dos son el mismo patrón: una copia acelerada que se queda vieja y **el motor
la prefiere sin avisar de nada**.

1. `intraday_1m_optimized` se queda corta cuando se reprocesa un mes.
   `gcs_cache.py` lo documenta como runbook manual («regenerate the optimized
   copy, OR delete it») y nada lo hace cumplir. Aquí costó **41 ticker-días
   descartados en silencio**: el lago llegaba al día 20 y el backtest se cortaba
   exactamente el 14. En local hemos descartado esa copia entera; en producción
   merece la pena automatizar su regeneración, o el guardián.
2. El **caché por ticker-mes** (`CACHE_DIR/{opt,raw}/<año>/<mes>/<ticker>`)
   tiene el mismo problema un nivel más abajo: se escribe una vez y no se revisa
   aunque el mes crezca. Nos costó otros 9 ticker-días. El runbook también lo
   documenta como purga manual.

En ambos casos, quien lo destapó fue **vuestro chivato de `data_completeness`**
(`1ec8ce9`), que nos trajimos. Sin él los backtests seguirían devolviendo
números tranquilamente con días enteros descartados. Muy buena pieza.

**Lo local, que no os interesa adoptar**

El botón de actualizar el lago (gated por `LAKE_UPDATE_ENABLED`, apagado en
producción) ahora cierra la cadena entera: carga el Parquet en
`local_data.duckdb` **desde el propio backend** (varias conexiones de escritura
en el mismo proceso, sin cerrarlo), amplía la ventana `date_to` de los datasets
que iban al día, y **añade** los días nuevos al caché por ticker en vez de
purgarlo. Verificado: completitud 99,82 % → 100 %, último trade del 08-20 al
08-21.

Un cambio de ahí sí es genérico y no cambia comportamiento:
`_populate_dataset_pairs` partido en `_compute_dataset_pairs` +
`_insert_dataset_pairs` (`routers/query.py`), para poder calcular los pares una
vez y reutilizarlos entre datasets con los mismos filtros.

---

## 2026-08-21 (Sailor) — Módulo Portfolio: página nueva `/portfolio`

> Entrada escrita por Sailor (Jaume + Claude). Guía completa de integración en
> **`docs/MODULO_PORTFOLIO_GUIA_INTEGRACION.md`** — leedla antes de tocar nada.

**Qué es**

Página nueva para estudiar varias estrategias **como una sola cartera**: cuánto
rinden juntas, cuánto se solapan, qué drawdown esperar del conjunto, cuánto
riesgo asignar a cada una, y cómo se compara con la operativa real del trader.

Mismo principio que Robustez: **trabaja sobre las corridas ya guardadas**, no
re-ejecuta backtests (salvo la Monitorización, que lo hace bajo petición
explícita). Normaliza cada estrategia a R por trade sin costes y desde ahí
combina, correlaciona y re-aplica costes por reconstrucción.

Tres pestañas: **Baúl** (inventario + cuadros portfolio/incubadora, con todas
las condiciones de cada estrategia al desplegar), **Portfolio** (imagen general
lineal / modelos de escalado y pesos / comparativa) y **Monitorización**
(últimos 6 meses re-ejecutados por estrategia + control en tiempo real con
importación del CSV del bróker).

**Está APAGADO por defecto.** Si no tocáis las variables, esta rama se comporta
igual que antes del commit:

```bash
backend/.env         PORTFOLIO_LAB_ENABLED=true
frontend/.env.local  NEXT_PUBLIC_PORTFOLIO_ENABLED=true
```

**Qué toca de vuestro código** (mínimo imprescindible)

- `backend/app/main.py`: +4 líneas (import + `include_router`). Prefijo
  **`/api/portfolio-lab`** — ojo, `/api/portfolio` (sin `-lab`) es vuestro
  módulo de producción y **no se toca**.
- `frontend/src/components/Sidebar.tsx`: +15 líneas, entrada gated. **El Baúl
  se queda como está**: la de Portfolio se añade *además*.
- `robustez/StrategyPicker.tsx` y `robustez/charts/MonteCarloCharts.tsx`:
  cambios **puramente aditivos** (4 funciones pasan a `export`, y
  `SpaghettiChart` acepta un prop opcional `xLabel` con valor por defecto). No
  cambian el comportamiento de Robustez.
- Tres tablas nuevas en `users.duckdb`, creadas de forma perezosa y solo con el
  módulo activo: `portfolio_lab_assignments`, `portfolio_lab_monitor`,
  `portfolio_lab_real_pnl`. No se toca `init_db.py`.

Todo lo demás son ficheros nuevos (4 en backend, 14 en frontend). Reutiliza
`robustness_service`, `robustness_mc`, `optimization_service` y
`backtest_orchestrator`, que ya están en esta rama — verificado, y `tsc
--noEmit` pasa sin errores **contra el código de staging**.

**Qué NO se ha traído a propósito**

1. **El borrado del Baúl.** En la rama de Sailor, Portfolio lo reemplaza y se
   eliminó `/database`. Aquí el Baúl sigue intacto — decidid vosotros.
2. **El fix de comisiones PERCENT** (`abs(gross_pnl)*fees` → % del nocional por
   lado). Vosotros ya tenéis vuestro modelo por fill (`77236d2`), así que no se
   pisa nada. Ver el punto (a) de abajo.

**Puntos que hay que acordar entre las dos ramas**

- **(a) FLAT.** Vosotros lo redefinisteis como `fees × acciones` ($/acción);
  Sailor mantiene `fees × 2` ($/trade). En PERCENT los dos modelos coinciden en
  el total; **en FLAT no**. Habrá conflicto al mergear: hay que elegir
  convención.
- **(b) El fallback silencioso de `data_service.py`** que documentasteis en
  `INFORME_FIX_NODETERMINISMO_BACKTEST_2026-08-21.md`: en la rama de Sailor no
  se dispara (allí `daily_metrics` es tabla persistente), pero **el código está
  igual de presente**. Cuando la migración GCS→parquet llegue a esa rama, el
  fail-fast (`1ec8ce9`) tiene que viajar CON ella.
- **(c) Sortino y (d) anualización del Sharpe.** El módulo Portfolio usa la
  downside deviation canónica y anualiza con la frecuencia efectiva de la serie
  (el calendario solo tiene días con operaciones, y con 252 fijo el Sharpe sale
  inflado ~1/√fracción_activa). `backtest_service.py:1240-1242` mantiene el
  cálculo anterior — **no se ha tocado** por ser motor compartido. Decidid si se
  unifica.

**Sobre la diferencia 133 R (Sailor) vs 137 R (vosotros)**

Investigada por nuestro lado. **No es un bug de motor.** El lago local de Sailor
llegaba hasta **2026-08-14** (verificado en `/api/market/available-date-range`),
así que un backtest pedido hasta el 19-20 de agosto perdía 3 sesiones enteras
(~1,3 R a su media de agosto). El resto encaja con el residual de cobertura que
vosotros mismos documentáis en §6.2 de vuestro informe. Su universo es estable
(7.809 trades en todos los runs), lo que confirma vuestra predicción de que el
no-determinismo 70R↔137R no le afectaba.

**Cómo se ha verificado el módulo**

- Paridad **exacta a 6 decimales** entre el motor de escalado y la imagen
  general en los dos casos ancla (`fixed $100` → 304,420878%; `percent 3%`
  diario → 699.805,793146%).
- Validación cruzada de la normalización: corridas sucias reconstruidas dan
  305,14% vs 304,42% de copias re-corridas limpias — el 0,24% es el margen
  esperado de la reconstrucción aproximada del slippage.
- Revisión adversaria multi-agente (4 lentes + un escéptico por hallazgo): 7
  hallazgos confirmados y corregidos, 3 refutados.

---

## 2026-08-21 (noche) — Fix no-determinismo del backtester (70R ↔ 137R)

**Qué pasaba**
- El MISMO backtest daba ~70% o ~137% de return según el run (y local vs prod
  descuadraban hasta 6×). El motor NO estaba roto; variaba **qué candidatos**
  llegaban a él.

**Causa raíz (dos cosas)**
1. **Fallback silencioso del qualifying** (`data_service.py`): si la vía
   autoritativa (bygap/`daily_metrics`) fallaba, caía EN SILENCIO al hot-cache en
   RAM (`gap_pct>=10`, universo distinto: 4.013 vs 4.902). Disparador: error
   transitorio `Table daily_metrics does not exist`, porque `_establish_connection`
   devuelve una conexión sin las vistas del lago. ⚠️ **Este fallback está latente
   IGUAL en `jaumen-rama-desarrollo`** — no se manifiesta ahí porque en esa rama
   `daily_metrics` es una **tabla persistente** (pre-migración). En la de Álvaro
   son **vistas perezosas sobre parquet** (migración GCS→local) que sí pueden
   fallar → el bug se activa. **El bug lo despierta la migración, no es de Álvaro.**
2. **Caché intradía por-ticker-mes desfasado** (`gcs_cache.py`): se congela en el
   primer fetch y no se refresca cuando el lago crece en el mes en curso → 20
   ticker-días de 2026-08-10→14 (AKAN, STKH, OFAL…) desaparecían aunque el lago
   los tenía.

**Qué hicimos**
- **Committeado `1ec8ce9`**: `data_service.py` FAIL-FAST (propaga error, nunca
  sirve el hot-cache no equivalente) + `backtest_orchestrator.py` guardián de
  completitud (`data_completeness` en el payload; `BACKTEST_STRICT_COMPLETENESS=true`
  rechaza runs parciales con 503).
- **Sin commitear** (entrelazados con el refactor de migración, no de Álvaro):
  `database.py` (reintento+verificación de vistas) y `gcs_cache.py` (refresh de
  caché desfasado). Activos en runtime.
- Borrado `.cache/intraday/raw/2026/08` (derivado) como fix inmediato del caché.
- Informe completo: `docs/INFORME_FIX_NODETERMINISMO_BACKTEST_2026-08-21.md`
  (commit `78a6b82`).

**Verificado end-to-end** (2 backtests reales al backend 8010): idénticos,
completitud 100%, 0 missing. Local vs prod ahora coinciden dentro del ~2%.

**Para el equipo (NO tocar la rama de Jaume)**: cuando la migración GCS→local-parquet
suba a staging/main, el fail-fast (y los refuerzos) **deben viajar CON ella**, o
todos heredan el 70R↔137R. Es prerrequisito de la migración, no limpieza de rama.

**Pendiente**: endurecer `_establish_connection` (chip de tarea creado); residual
~6% de trades local vs prod (cobertura de datos, no motor); métrica `DAYS`
cosmética entre versiones; config drift de "Definitiva 2.3" ya resuelto.

---

## 2026-08-21 (tarde 2) — Rama handoff a producción con PRDs para Edgecute

**Qué hicimos**
- Álvaro pidió rama para entregar al developer de Edgecute (vía develop→main,
  ese salto es de Adrian) las dos mejoras apremiantes: fees por ejecución y
  calendario/retorno real. Creada **`alvaro/handoff-produccion`** (commit
  `7f65d83`) **basada en `origin/develop` @ `e368839`**, por worktree temporal
  (el working tree de esta rama no se tocó). Es un **canal permanente**: sin
  fecha en el nombre; cada tanda de mejoras va en una carpeta fechada dentro.
- **Solo documentación**: `docs/handoff-produccion/` con README índice vivo +
  tanda `2026-08-21-fees-y-calendario/` (PRD_01 fees, PRD_02 calendario,
  `reference/` con parches + `test_fees.py` copiable tal cual).
  Todas las anclas `fichero:línea` verificadas contra develop@e368839.

**Hechos verificados (importan para el futuro)**
- Cherry-pick de `77236d2` (fees) sobre develop **NO aplica limpio**:
  conflictúa en `portfolio_sim.py` (construido sobre trailing+locates+
  parciales fade de mi rama). Con `59a869d`+`77236d2` el trailing sí aplica,
  fees sigue conflictuando. → Handoff por PRD, no por código. `test_fees.py`
  sí es copiable (archivo nuevo, sin dependencias de features mías).
- `origin/alvaro-rama-desarrollo` == local (0 commits sin push): la nota
  "sin push" de las entradas anteriores quedó desactualizada.
- Clasificación del working tree sin commitear: **paquete calendario/retorno
  (6 ficheros: CalendarTab, PerformanceTab, EquityCurveTab, ChartsTab,
  MetricsCard, page.tsx)** = el fix que el usuario quiere en producción;
  `sl_dist_pct_*` (api_backtester, tradesCsv, MetricsCard, backend) y
  `activation_pct` (strategy.ts) = features aparte, fuera del handoff.
  El parche de referencia del calendario se generó de este diff.

**Decisiones**
- Handoff **docs-only**: nada de mi montaje local (bygap, migración GCS/lago,
  MEMORIA/PROXIMOS) puede colarse. README lista explícitamente lo excluido +
  candidatos futuros (fix locates `2a51b94..de14125`, OOS DD$ `5741202`).
- El fix del calendario sigue **sin commitear** en esta rama (trabajo de la
  sesión paralela); el PRD es autocontenido y el parche documenta el
  comportamiento exacto. Pendiente: validarlo (tsc + visual) y commitearlo
  aquí con su propio commit.

**Continuación (misma tarde)**
- Álvaro pidió mensaje + PRD de orientación para Adri (que sepa qué subir a
  main sin liarse). Añadido **`PRD_00_PLAN_DE_SUBIDA_A_MAIN.md`** a la tanda
  (commit `9f7e22c`, en la rama handoff): resumen simple, 2 PRs pedidos,
  orden recomendado (PRD_02 primero), checklist de verificación antes de
  main (incluye smoke de identidad con fees=0), guarda-raíles (no mergear
  mis ramas, no git apply, quirks intactos) y nota de release sugerida.
  README del handoff actualizado con su fila. Mensaje corto para Adri
  entregado en la conversación (no en el repo).

**Continuación 2 (tarde) — PRD_03 trades vs ejecuciones (mea culpa)**
- Álvaro corrigió: el fix apremiante nº 1 NO era el de fees — era el de
  **trades listados como ejecuciones** (1 trade ≥ 2 ejecuciones; con
  parciales 3+). Lo arreglamos ~08-17/20 (¿sesión con otra IA?): commits
  `39a2d80` (función `_group_partial_exits`, backtest_service.py:992, +
  badge calendario), `3dcd7d0` (n_executions/legs en API+CSV+TradesTab),
  `1249ca1` (EXIT), `93656e0` (chart). Yo lo había clasificado como
  "botón export CSV" y no lo vi. Evidencia de esa sesión en el working
  tree: `backend/.audit_replay.py`, `backend/.audit_all_trades.csv`
  (columna `n_executions`).
- **Verificado contra develop**: el motor hace `trades.append` POR
  EJECUCIÓN (parcial :302, cierres :250/357/404/447/569) y NO existe
  agrupación → develop TIENE el bug (total_trades inflado, win rate
  contaminado).
- Añadido **`PRD_03_trades_vs_ejecuciones.md`** a la tanda (commit
  `33713af`, sin push al escribir esto): portar `_group_partial_exits`
  (copiada íntegra a `reference/group_partial_exits.py.txt`) envolviendo
  `_enrich_trades` (:756 único call-site en develop). PRD_00 y README
  actualizados a **3 PRs** (orden: PRD_02 → PRD_03 → PRD_01). Mensaje para
  Adri reescrito con 3 items.

**Continuación 3 (tarde) — Commiteado el trabajo aprobado que estaba vivo en el working tree + CSV fuera del handoff**
- **Queja de Álvaro (procede):** trabajo YA aprobado seguía sin commitear en
  la rama (ni MEMORIA). Commit `588588b` recoge los 9 ficheros frontend del
  working tree (tsc --noEmit limpio), en 3 bloques: (1) fix
  calendario/retorno real — el que va a producción vía handoff PRD_02;
  (2) métricas `sl_dist_pct_*` — feature LOCAL, no va al handoff; su
  cálculo backend sigue sin commitear (mezclado con migración GCS en
  `backtest_service.py`) → sin él las filas muestran 0; (3) tipo
  `activation_pct` — resto del ITEM 1 (`59a869d`) que quedó sin commitear.
- **Regla a partir de ahora:** cuando Álvaro aprueba algo, SE COMMITEA en la
  misma sesión (su rama + entrada MEMORIA). Nada aprobado queda vivo en el
  working tree. Lo no aprobado se declara en MEMORIA como pendiente.
- **Decisión de Álvaro — handoff solo fixes flagrantes, SIN export CSV** (los
  trades viven dentro del backtester, nada se externaliza): PRD_03 amendado
  (`6185254`) quitando el CSV del T4 y dejándolo dicho; README del handoff
  lo explicita. Sigue pendiente: merge a `staging` (requiere orden
  explícita de Álvaro; Sailor comparte esa rama).
- Pendiente de decisión: extraer algún día los hunks `sl_dist` de
  `backtest_service.py` para completar la feature (hoy bloqueado por la
  migración GCS sin commitear).

**Dónde lo dejamos (final de sesión)**
- `alvaro/handoff-produccion`: PRD_03 (`6185254`) **sin push** al escribir
  esto — pusheado a continuación con OK de Álvaro.
- `alvaro-rama-desarrollo`: `588588b` (trabajo aprobado) + commit de esta
  MEMORIA, **sin push** al escribir esto — pusheados a continuación.
- Working tree: queda SOLO el WIP no aprobado (migración GCS backend +
  renames staged + analisis/ + untracked varios).

---

## 2026-08-21 (noche 5) — RETRACTACIÓN: el "bug de clic" del picker de robustez NO existe

**Qué pasó**
- La entrada "noche 2" reportaba un bug de selección por clic (off-by-one) en
  el picker de estrategias del módulo de robustez, y el mensaje para Sailor
  lo incluía. **Era falso**: fue un artefacto de mi automatización.
- Sesión de diagnóstico exhaustiva: repro "limpia" en pestaña nueva seguía
  fallando, PERO los resultados eran incoherentes entre sí (a veces 1 arriba,
  a veces 2, a veces "teleporta" a la primera tarjeta, a veces clic muerto) —
  ningún patrón compatible con un bug real de la página. El Enter (sin
  coordenadas) SIEMPRE selecciona correcto. El código React revisado línea a
  línea es correcto (`onSelect(s.id)` directo, keys estables, sin CSS
          solapado/absolute/transform). Y el propio Álvaro confirma que con su
  ratón real funciona bien.
- **Causa del artefacto:** el pipeline de input del navegador integrado que
  uso para probar despacha los clics con desfase/contaminación (además la
  pestaña estaba visible en la pantalla de Álvaro → clics suyos simultáneos
  posibles en algunos tests).

**Correcciones**
- El mensaje para Sailor: quitar la sección del bug (versión corregida
  entregada en la conversación). **No hay nada que arreglar en robustez.**
- Lección para futuras sesiones (regla): los clics automatizados del
  navegador integrado NO son evidencia válida de bugs de UI en este repo;
  usar teclado (`press("Enter")`) para probar selección, o pedir a Álvaro
  que clique él. Verificar siempre con el código antes de reportar.

---

## 2026-08-21 (noche 4) — Cierre: staging mergeado + robustez listo para usar en local

**Subido todo (con OK de Álvaro)**
- Pushes: `alvaro-rama-desarrollo` → `e2e084d` y `alvaro/handoff-produccion`
  → `e850d56` (F4).
- **Merge rama→`staging`**: fast-forward limpio `d423046..e2e084d` (47
  ficheros, +3.696/−291) y pusheado. Sailor ya tiene TODO el inventario
  priorizado; su mensajito de handoff está en la conversación (incluye el
  reporte del bug de clic del picker).

**Robustez listo en local (para que Álvaro lo use ya)**
- `backend/.env`: `ROBUSTNESS_ENABLED=true` (gitignored).
- `frontend/.env.local`: `NEXT_PUBLIC_ROBUSTNESS_ENABLED=true` (gitignored,
  añadido sin tocar lo existente) → link "Robustez" visible en el sidebar
  (verificado en navegador).
- Servidores arrancados con `arrancar_local.bat` (ventanas propias); el
  backend responde los 11 endpoints de robustez con las estrategias reales.
- Recordatorio del bug: clic de ratón en el picker selecciona la estrategia
  de ARRIBA (usar teclado o clic en la de abajo mientras Sailor lo arregla).

---

## 2026-08-21 (noche 3) — Revisión externa del handoff+sync: 4 correcciones aplicadas (F1–F4)

**Contexto**
- La IA arquitecta de Álvaro revisó el trabajo contra el repo real: confirma
  handoff docs-only (9 ficheros, +1.740, 100% en docs/handoff-produccion/),
  anclas de los 4 PRDs exactas contra `origin/develop@e368839`,
  independencia de los 3 PRDs verificada (interacción fees↔agrupación
  segura en cualquier orden) y reference copiable. 4 correcciones, ninguna
  bloqueante — **todas aplicadas**.

**F1 (🔴) — Baseline de tests backend (la importante de cara a main)**
- Suite completa: `pytest tests/ -q --continue-on-collection-errors` →
  **108 failed / 337 passed / 15 errors** (2:39). Requiere el flag: 2
  módulos con imports muertos abortan la recolección (Backlog #4).
- Baseline registrada en **`docs/BASELINE_TESTS_BACKEND.md`** (123 rojos,
  agrupados y categorizados: entorno/datos vs Backlog #3/#4 vs conocidos).
- **Regla:** antes de cualquier salto `staging→develop→main`, correr la
  suite y comparar contra esa lista: rojo NUEVO = regresión → parar.

**F2 (🟡) — develop local desfasado**
- El branch local `develop` estaba en `d4065b9` (por detrás de
  `origin/develop@e368839`) → `git branch -f develop origin/develop`.
- **Regla:** las anclas de los PRDs se verifican SIEMPRE contra
  `origin/develop`, nunca contra el branch local.

**F3 (🟡) — 588588b mal etiquetado**
- El inventario lo listaba como 🔴 puro; es **MIXTO** (calendario→prod +
  sl_dist local + activation_pct). Corregido arriba en el inventario.

**F4 (🟡) — PRD_03 sobrevendía portabilidad**
- `_group_partial_exits` tiene 8 subíndices duros (`pnl`, `size`,
  `entry_price`, `exit_idx`, `exit_time`, `exit_time_epoch`, `exit_price`,
  `exit_reason`) → KeyError si develop los toca, no None silencioso.
  PRD_03 §3-T1 corregido (commit `e850d56` en la rama handoff, sin push
  al escribir esto).

**Dónde lo dejamos**
- Pendiente push: `alvaro/handoff-produccion` (`e850d56`) y esta rama.
  El merge rama→`staging` sigue esperando OK de Álvaro (la revisión no lo
  bloquea).

---

## 2026-08-21 (noche 2) — Prueba runtime del módulo de robustez: FUNCIONA, con 1 bug de selección

**Montaje**
- El backend que corría era **pre-merge** (sin endpoints de robustez):
  reiniciado con el código del merge (puerto 8010, queda corriendo en
  background de esta sesión). Frontend ya corría (Next dev recompila solo).
- `ROBUSTNESS_ENABLED=true` añadido a `backend/.env` (local, gitignored; el
  módulo viene apagado por defecto — regla R7). El link del sidebar sigue
  oculto sin `NEXT_PUBLIC_ROBUSTNESS_ENABLED`, pero `/robustez` entra por
  URL directa.

**Verificado ✓**
- Página carga; lista las 4 estrategias reales con sus métricas; auto-análisis
  de la primera al abrir (drawdown, rachas, 5 peores hundimientos, ulcer).
- 11 endpoints del router responden 200; el análisis recalcula al cambiar de
  estrategia; `tsc` limpio (ya verificado en el merge).

**🐛 Bug encontrado (presente en staging; reportado a Sailor)**
- **Clic con ratón en la tarjeta N selecciona la estrategia N−1**: clic en
  "Definitiva 2.3" (4ª) → cargó "Sailor RTH 1" (3ª); clic en "RTH 2" (2ª) →
  cargó "Investigar contextos AH" (1ª). Patrón consistente (verificado en el
  log del backend: los `/run` pedidos no coinciden con la tarjeta clicada).
- **Con teclado (Enter) selecciona la CORRECTA** → el código React está bien
  (`StrategyPicker.tsx` pasa `s.id` directo; `page.tsx:72` también): es un
  problema de **área de clic / hit-testing solapado** entre tarjetas
  (probablemente CSS del header clicable). Un usuario real con ratón lo
  sufrirá igual.

**Dónde lo dejamos**
- Backend corriendo con código del merge + robustez activo (local).
- Merge rama → `staging` sigue **pendiente de OK** de Álvaro.

---

## 2026-08-21 (noche) — Sync con staging (opción A): merge limpio + inventario priorizado para subir

**Qué hicimos**
- Revisión de divergencia con `origin/staging`: ellos +6 / nosotros +28.
- **Merge `38298f1`** (origin/staging → alvaro-rama-desarrollo), **0 conflictos**.
  Truco necesario: los renames STAGED del WIP (backend/scripts → _archive)
  bloqueaban el merge por estado de índice; se des-stagearon, se mergeó y se
  re-stagearon idénticos (12 entradas A/R intactas, disco sin tocar).
- **Nos trae** (33 ficheros, +10.280 líneas): módulo de **robustez** de
  Sailor completo (useLocates/useMonteCarlo/useWfo + api_robustez + analytics,
  30 ficheros nuevos), su aplicación del fix de locates, copia del PRD y
  carpeta `ALVARO_CAMBIOS/` (MEMORIA+PROXIMOS para el equipo).

**Verificado**
- Fix de locates de Sailor = **idéntico al nuestro**: el merge dejó nuestros
  `portfolio_sim.py`/`sim_dispatch.py`/`test_locates.py`/PRD.md byte a byte
  iguales (diff vacío). Nada que reemplazar.
- `test_locates.py` + `test_sim_jit_equivalence.py`: **12/12 verde**.
- `tsc --noEmit`: **limpio** con el módulo de robustez incluido.

**Inventario priorizado de NUESTROS commits para staging (28, decisión de
Álvaro: subir TODOS, con esta prioridad)**

🔴 **Urgente — bug** (van también a main vía handoff):
- `77236d2` fees por ejecución (fill) · `588588b` **MIXTO**: calendario/retorno
  real (→prod vía PRD_02) + métricas `sl_dist_pct_*` (local, NO handoff) +
  tipo `activation_pct` (resto ITEM 1) · `5741202` OOS MAX DD $ ·
  `2a51b94+8896ece+de14125` locates (ya en staging
  por Sailor, duplicado idéntico) · `1249ca1` EXIT parciales invisibles ·
  `6c37f94` hidratación rango dataset · `e42d34b` logging translate_strategy

🟡 **Feature validada** (Sailor decide si las toma):
- `59a869d` trailing break-even (activation_pct) + tests · parciales fade
  1A/1B (`ddba140`,`e251727`,`d334aff`,`1e18432`,`d6a2fab`) · `6631056`
  Current Gap (%) · `447612c` regla/línea chart · `93656e0` ejecuciones
  señaladas al precio · `3dcd7d0` export CSV (interno; NO va a main)

🟢 **Infra/DX**:
- `9f39a17` bygap vía rápida (env-gated, inerte sin `.env`) · arranque 1-clic
  (dentro de `6c37f94`)

📄 **Docs** (nuestro kanban real para el equipo, complementa ALVARO_CAMBIOS):
- `f8a7bd7`, `c779560`, `75f4bee`, `2e431ac`, `478ce55`, `8176d83`,
  `1a04176` + este · `23bd2e1` merge previo (histórico)

**Pendiente**
- Push de `alvaro-rama-desarrollo` (merge + docs) → hecho tras este commit.
- **Merge de nuestra rama → `staging`**: pendiente OK explícito de Álvaro.
  Se haría por worktree (el working tree principal está sucio con el WIP
  GCS). Con eso Sailor recibe TODO el inventario de arriba.

---

## 2026-08-21 — Ejecutados ITEM 3 e ITEM 1 (PROXIMOS_ITEMS); spec ITEM 2 corregida

**Contexto**
- Auditoría del backtester del 2026-08-21 → `docs/PROXIMOS_ITEMS.md` con 3 items.
- Revisión Claude (Opus) con notas 🔎 A/B/C sobre la spec de ITEM 2. Esta sesión:
  verificar esas notas contra el código, ejecutar ITEM 3 e ITEM 1 (aprobados por
  Álvaro, en ese orden), corregir la spec de ITEM 2. **ITEM 2 NO ejecutado.**

**Verificación de las notas A/B/C (todas correctas)**
- **A**: `BacktestPanel.tsx:688` ya divide `fees/100` antes de enviar → al motor
  llega como fracción; el `/100` de la fórmula PERCENT de la spec habría cobrado
  100× de menos.
- **B**: parciales sin clave `fees` a propósito (`sim_dispatch.py:348-351`,
  comentario "quirk contractual"); el total (`backtest_service.py:1033`) los
  excluye. Tocarlo rompería `test_sim_jit_equivalence`.
- **C**: label actual es `Fees ($)` (`BacktestPanel.tsx:1384`); con el cambio
  $/trade → $/share el relabel es obligatorio.
- Anclas de ITEM 1 (7/7) e ITEM 3 verificadas. Ningún test referenciaba
  `trail_activation` (hueco real de cobertura).

**ITEM 3 — MAX DD $ del tab OOS (commit `5741202`)**
- `OOSDegradationTab.tsx`: la serie (`:371`) y el header (`:556`) convertían
  `dd$ = (dd%/100) × initCash`, que subestima el DD cuando el pico supera el
  capital inicial. Arreglado copiando el patrón de `EquityCurveTab.tsx:177-193`:
  memo `ddDollarByTime` (value − running peak sobre `fullGlobalEquity`) para
  serie y header, con fallback a la fórmula vieja si no hay punto. Solo
  presentación; `tsc --noEmit` limpio.

**ITEM 1 — Trailing Break-Even desacoplado (commit `59a869d`)**
- La feature vivía sin commitear en la working tree. Validada contra cálculo
  manual, testeada, documentada y commiteada (solo sus 9 ficheros):
  `strategy_engine.py` (parsing ×2 paths), `portfolio_sim.py`, `portfolio_sim_jit.py`
  (puerto línea a línea, mismo orden FP), `sim_dispatch.py`, `schemas/strategy.py`
  (`activation_pct: None` explícito en el default), `RiskManagement.tsx`,
  `BACKTESTER_BRAIN.md` §4 + checklist.
- Tests nuevos: `backend/tests/test_trail_break_even.py` (T1 BE long, T2
  no-activación → SL, T3 activación+distancia, T4 espejo short, T5 regresión
  bit-identica del trailing clásico via `trail_activation=None` vs
  `=trail_pct`) y `test_sim_jit_equivalence.py::test_trail_activation_equivalence`
  (T6 paridad JIT con BE y mixto). **19/19 verdes** (suite ITEM 1 + fade
  partials). Numba 0.66.0 real, kernel cacheado.
- Nota semántica: `buffer_pct=0` antes era falsy → trailing inerte; ahora
  admite 0.0 → "BE inmediato" (caso documentado en BRAIN §4).

**ITEM 2 — Fix fees: spec corregida, PENDIENTE de orden**
- `docs/PROXIMOS_ITEMS.md` §ITEM 2 reescrito con A/B/C aplicadas: fórmula
  PERCENT sin `/100` (fees llega como fracción), tabla de fórmulas por bloque
  (el fee de ENTRADA cae en el cierre final: `original_size`; parciales solo su
  salida), decisión explícita de **mantener el quirk** de parciales sin `fees`,
  y relabel "$/share" marcado obligatorio.
- **Esperando visto bueno de Álvaro a la spec antes de tocar el motor.**

**Dónde lo dejamos**
- Commits en `alvaro-rama-desarrollo`, **sin push** (pendiente confirmación).
- Working tree: siguen los cambios WIP de Álvaro (migración GCS, renames
  `backend/scripts → backend/_archive/scripts_gcs_2026-08` staged, etc.).
- `test_strategy_api.py::test_create_and_get_strategy` falla 422 de forma
  **preexistente** (verificado con stash, sin relación con estos cambios). No
  estaba en la lista de tests rotos conocidos del Backlog.

---

## 2026-08-21 (tarde) — Ejecutado ITEM 2: fees por ejecución (fill)

**Qué hicimos**
- Álvaro dio el visto bueno a la spec corregida (A/B/C) y ordenó ejecutar.
- Nuevo modelo de comisiones **por fill** en `portfolio_sim.py` (helper
  `_fee_amount`, 6 puntos) y kernel JIT (`_fee_amount_jit`, puerto con mismo
  orden FP): FLAT = $/acción y lado (`fees × qty`); PERCENT = fracción del
  nocional (`notional × fees`, SIN `/100`: el frontend ya divide). El cierre
  final paga la entrada de TODO el tamaño (`original_size`) + la salida del
  restante; cada parcial paga solo su salida. Quirk B intacto: parciales sin
  clave `fees`, totales sin su fee, locates intactos.
- UI: labels `Fees (% notional)` / `Fees ($/share)` en `BacktestPanel.tsx`
  (relabel obligatorio por el cambio de significado de FLAT). BRAIN §5
  actualizado con el modelo por-fill.

**Verificación**
- `backend/tests/test_fees.py` nuevo (6 tests): FLAT/PERCENT full, trade plano
  paga fee (mata el bug `abs(pnl)`), parciales FLAT/PERCENT + quirk sin
  `fees`, paridad JIT. Escrito primero y visto en rojo (5 fallos con el motor
  viejo), verde tras el cambio.
- Paridad: `test_sim_jit_equivalence.py` (grid 220 configs con fees 0.01/2.5
  ambos tipos) + fade partials + trail + locates: **28/28**.
- Suite completa con diff contra stash: **0 fallos nuevos**; los ~119 fallos
  preexistentes son de entorno/datos (GCS 403, bygap Parquet local, DB).
- Humo (34 trades, 1.416 acciones, random walk sembrado): FLAT $0.01/share →
  fee total $28.32 = exacto a $0.02 × 1.416; PERCENT 0.01% → $13.59 ≈
  0.0002 × nocional; paridad JIT exacta en los 3 escenarios.

**Impacto (avisado en spec y commit)**
- PERCENT: cambia la fórmula, no la magnitud con el default 0.01%.
- FLAT: cambio de SIGNIFICADO ($/trade → $/share) — backtests guardados con
  FLAT>0 dan números muy distintos; el relabel de UI lo hace explícito.

**Dónde lo dejamos**
- Commits del día: `5741202` (ITEM 3), `59a869d` (ITEM 1), `75f4bee` (docs),
  + commit de ITEM 2 (fees). Todo en `alvaro-rama-desarrollo`, **sin push**.
- `PROXIMOS_ITEMS.md` queda solo con el Backlog congelado: los 3 items de la
  auditoría están ejecutados y registrados aquí.

---

## 2026-08-20 (tarde) — Diagnóstico inconsistencias de P&L + PRD fix de locates

**Qué hicimos**
- Diagnóstico de por qué los números del backtester **no cuadran entre paneles**
  (Álvaro veía cifras contradictorias en varias estrategias). Solo diagnóstico +
  un PRD: **no se tocó código esta sesión**.
- Revisión concreta del **cálculo de locates** (sospecha de Álvaro).

**Hallazgos (anclados en código)**
- **PnL% del grid mensual COMPONE los retornos diarios** (`PerformanceTab.tsx:148`,
  `∏(1+r/100)−1`) mientras el RETURN del backend es simple `Σpnl/init_cash`
  (`backtest_service.py:1336`). Por eso YTD salía +3133% con RETURN +27.67%. Bug real.
- **Capital por defecto $10.000 hardcodeado** en 4 sitios (`BacktestPanel.tsx:417`,
  `page.tsx:259/465/470/506`). Las métricas en $ del header de la curva usan
  `initCashRef.current` (`EquityCurveTab.tsx:663/682`), que se desincroniza del
  `init_cash` real → firma del $10k en `MAX DD` (−4941/−49.41%) con capital 2.500.
- **3–4 pipelines de P&L en paralelo sin fuente única**: backend agregado
  (`Σpnl/init_cash`), curva backend (`init_cash+cumsum`), calendario (suma cruda
  de `t.pnl`, `CalendarTab.tsx:68-75`), PnL% compuesto, y `page.tsx:1087` recalcula
  el return por su cuenta. Cada uno da un número distinto.
- **Calendario "verde pero plano"**: en modo neto no resta los `$150/mes` (solo en
  modo "gastos", `CalendarTab.tsx:87-89`); el neto real es `total_pnl−total_expenses`
  (`backtest_service.py:1327`).
- **Locates — el total es correcto, el reparto está mal**:
  - Todo el locate del día se imputa al **primer short** (`break`) en
    `portfolio_sim.py:878-882` y **duplicado verbatim** en `sim_dispatch.py:372-395`
    (path JIT). → falsea R por trade y win rate.
  - Se resta de **toda la curva de equity** desde la barra 0 (`equity[i]` para todo
    `i`), incluidas barras premarket sin posición → infla el DD intradía.
  - Evidencia (misma "Definitiva 2.3", 867 trades): locate 0 → 3 pasa RETURN de
    **+9876.73% a −71.73%** y **WIN RATE de 64.1% a 56.2%** (huella del mal reparto).

**Decisiones**
- Modelo de locate **"una sola compra por ticker-día"** confirmado por Álvaro:
  **no** se cobra por reentrada (el `max_short_size_today` + una imputación es
  correcto y se preserva).
- **Reparto FIJADO: proporcional al `size` de cada short**, preservando el total
  exacto (elimina la distorsión de win rate con reentradas).

**Entregable**
- **`docs/fix-locates-attribution/PRD.md`** — PRD ejecutable condensado (formato
  casa, anclado a `fichero:línea`, plan atómico T1–T5, DoD, ejemplo numérico).
  **Pensado para que lo ejecute GLM** en `alvaro-rama-desarrollo`. El fix va en los
  **dos** paths (`portfolio_sim.py` + `sim_dispatch.py`) y debe dejar verde
  `test_locates.py`, `test_locates_flat_semantics.py` y `test_sim_jit_equivalence.py`.

**Abierto (deferred)**
1. **El bug PnL%/initCash NO tiene PRD todavía** — solo diagnóstico. Decidir si se
   unifica todo a una sola curva de equity (fuente única de verdad) y quién lo hace.
2. **Trabajo en paralelo sobre los MISMOS ficheros**: `PerformanceTab.tsx`,
   `EquityCurveTab.tsx`, `page.tsx`, `CalendarTab.tsx` se editaron a las 19:54–19:57
   (otro agente/sesión). Cuidado con pisar al tocar el fix del P&L.

---

## 2026-08-20 — Vía rápida de qualifying (bygap ordenado por gap)

**Qué hicimos**
- Adoptada la optimización de Sailor: leer las 32 columnas de ventana (LAG/LEAD)
  del qualifying de un Parquet materializado y **ordenado por `pmh_gap_pct DESC`**,
  en vez de recalcularlas sobre 19,2 M filas en cada backtest.
- Revalidado que `edgecute_app` = mismo montaje que Sailor (fuente **DuckDB**,
  `main.daily_metrics`), no la vía Parquet (eso fue un despiste del repo `edgecute_lab`,
  que era una prueba desechable y **se borró**).
- Generado el bygap con `opt_por_gap.py` desde `main.daily_metrics` (misma fuente
  que la app → paridad por construcción): **3,51 GB, 173 s**, 19.177.136 filas.
- Implementado + **merge de `origin/staging`** (trae `fbf8757` de Sailor) resuelto
  en **`23bd2e1`**: estructura de Sailor (`_remap_trading_day` extraída, `return`
  temprano, TTL por `QUALIFYING_CACHE_TTL`) + **guardián de frescura** (footer
  `parquet_metadata` + memo, CAST en SQL) + **`QUALIFYING_WINDOWED_STRICT`** con
  centinela `_BygapStaleStrictError` + **remap unificado** (vía lenta llama a la
  función, sin inline duplicado).

**Resultado medido**
- Baseline (vía lenta): 14,7 s (2020→hoy), 17,0 s (2022-2023).
- Vía rápida: **0,18 s** (~80-90×). Guardián: 0,25 s fresco; desfasado → degrada
  con resultados idénticos; desfasado + STRICT → error propagado (no cae al hot-cache).
- **Paridad 7/7, 0 diferencias, `rtol=1e-9`** sin aflojar, incluidos `gap_1_day`,
  `gap_2_day` y borde derecho. `py_compile` OK.

**Decisiones**
- **NO push a `staging`.** `fbf8757` ya está en `staging` (lo subió Sailor); nuestros
  extras (guardián, STRICT, test) se quedan en `alvaro-rama-desarrollo`. Env-gated y
  **apagado por defecto** → cero impacto en producción / resto del equipo.
- No perseguir convergencia total de código con Sailor. Él mantiene su versión.

**Config local añadida a `backend/.env`** (ignorado por git)
- `QUALIFYING_WINDOWED_PARQUET=.../cold_storage/daily_metrics_bygap/*.parquet` (glob, no fichero)
- `QUALIFYING_WINDOWED_STRICT` (default false), `QUALIFYING_CACHE_TTL=604800`,
  `MIN_AVAILABLE_DATE=2019-01-01`, `DUCKDB_MEMORY_LIMIT=3GB`,
  `INTRADAY_PREWARM_ENABLED=false`, `BACKTEST_MIN_AVAIL_GB=1.0`.

**Dónde lo dejamos**
- `23bd2e1` commiteado en `alvaro-rama-desarrollo`, **sin push**. Funciona en local.
  **Tema cerrado.**

**Abierto (deferred — no bloquea, no actuar salvo decisión)**
1. **Dos copias inline más del remap** sin unificar: hot-cache (~1060) y fallback
   GCS (~1131). Si se unifican algún día, acordar con Sailor al subir a `staging`.
2. **`except` ancho del branch local** (`data_service.py` ~975): cualquier excepción
   de la vía local cae al hot-cache, que filtra por `gap_pct` (no `pmh_gap_pct`) →
   "no falla, contesta otra cosa" (por eso 53 vs 65 filas). El centinela cubre STRICT;
   el caso general (`has_custom_rules`) queda como posible follow-up con dueño.
3. **Concurrencia** del `read_parquet` sobre el bygap (varios backtests a la vez)
   no probada. Irrelevante en local de 1 usuario.
4. Script de Sailor `opt_qualifying_incremental.py` tiene bug de orden (borra los
   parquet antes de renombrar el compactado). No lo usamos aún; si se adopta,
   renombrar primero y borrar después.
5. **Inyección SQL preexistente** en `_build_where_clause` (interpola filtros de
   usuario sin parametrizar). No la introduce este cambio; deuda aparte.

**Ficheros de referencia (Downloads)**
- PRDs de Sailor: `PRD_CONSTRUCCION_Y_OPTIMIZACION.md`, `PRD_RESPUESTAS_QUALIFYING.md`,
  `PRD_COORDINACION_QUALIFYING.md`, `PRD_REVISION_RECONCILIACION.md`.
- Nuestros: `PRD_ADOPCION_QUALIFYING_BYGAP_ALVARO.md`, `RECONCILIACION_QUALIFYING_STAGING.md`,
  `opt_por_gap.py`.
- En el repo: `backend/tests/test_bygap_parity.py`.
