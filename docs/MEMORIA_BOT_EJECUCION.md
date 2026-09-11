# MEMORIA — Bot de EJECUCIÓN en DAS Trader Pro (Sage Trading)

> **Qué es este fichero.** Submemoria APARTE de `MEMORIA_MADRE.md` y de
> `MEMORIA.md`, dedicada solo al bot que ejecutará órdenes en DAS. Se lleva
> aquí para no mezclar sus decisiones con las del backtester ni con las del bot
> de avisos. Misma regla que la madre: se AÑADE al final, no se reescribe lo
> anterior; la sección «Estado y pendientes» es la única que se sobrescribe.
>
> Abierto el 2026-09-05. Estado: **análisis y plan. Nada programado, nada
> configurado.** Falta el PDF del API de DAS que tiene que dar el bróker.
>
> Regla de trabajo de Jaume: **por fases, cada fase con sus pruebas, y no se
> pasa a la siguiente hasta que la anterior funciona.** Eficacia y cero
> errores por delante de velocidad.

---

## 0 — 2026-09-05 · Análisis inicial y decisiones de arquitectura

### Punto de partida (lo que ya existe y se reutiliza)

El bot de avisos (`backend/app/services/bot_alerts_*.py`, `D:\bot_senales\bot.py`)
ya tiene resuelto: motor causal con paridad verificada (73 ticker-días, cero
divergencias), feed `AM`/`A` de Massive validado contra REST, radar de universo,
hidratación por REST al entrar al radar, prealertas en la ventana 44-59, ids
de evento estables e idempotentes, Telegram directo (sin pasar por la app).

**El bot de ejecución será un bot DISTINTO** al de la página de Alertas. Coge
código de él (motor, feed, radar, hidratación, prealertas, Telegram) pero es
otro proceso con otra responsabilidad. El de avisos sigue como está.

Lo que NO vale para ejecutar aunque valga para avisar (ver también
`BOT_ALERTAS_MODOS_DE_FALLO.md` §4 y §5):

1. El estado es teórico: el motor supone que se entró en todo.
2. DuckDB está en el camino del aviso (bloqueos de más de 60 s medidos).
3. El interruptor se consulta cada 5 s: demasiado lento como emergencia.
4. Sin supervisor y sin estado en disco: si muere, nadie sabe qué hay abierto.

### Arquitectura propuesta: posición objetivo, cinco capas, tres invariantes

**Posición objetivo, no traducción evento→orden.** El motor dice qué posición
debería haber (lado, acciones, stop). Un ejecutor aparte acerca la posición
REAL de DAS a ese objetivo dentro de límites. Parciales, rechazos y locates
fallidos se corrigen solos en la vela siguiente.

Capas, cada una con interfaz mínima:

1. **Señal** — lo existente. Emite objetivos. Único sitio que sabe de estrategias.
2. **Guarda de riesgo** — función PURA (objetivo + estado real → sí/recorta/no).
   Sin red ni base. Se prueba con tablas. Aquí viven todos los topes.
3. **Ejecutor** — habla solo con DAS. Recibe «pon corto N con stop en P»,
   devuelve lo que el bróker confirmó. Idempotente por id de evento.
4. **Reconciliación** — al arrancar, tras reconectar y cada N s: posiciones,
   órdenes vivas y cuenta según DAS. Posición sin stop → stop o cierre.
   Posición desconocida → aviso y no se toca sin humano.
5. **Diario y supervisión** — JSONL append-only escrito ANTES de enviar y
   DESPUÉS de la respuesta. Supervisor que reinicia y avisa por Telegram.

Invariantes:

- **Ninguna posición sin stop residente en el bróker.** Si el bot muere, la
  posición sigue protegida. (Tipo de stop: ver el punto abierto de abajo.)
- **La orden va antes que cualquier registro que pueda bloquearse.**
- **La posición real manda sobre la teórica, siempre.**

### Decisiones de Jaume del 5-sep (respuesta al análisis)

- **STOP LIMITADO vs STOP DE MERCADO — PUNTO ABIERTO, RECORDÁRSELO.** Se
  propuso stop de mercado para cortos. Jaume lo matiza: en small caps hay
  eventos «cisne negro» en los que el precio se dispara varios cientos de %
  en segundos y **siempre vuelve**, como un error de mercado; un stop de
  mercado ahí es «un suicidio», especialmente en premercado. Hay que modelar
  muy bien: **no ejecutar ninguna orden si el precio se ha disparado más de
  un X % en pocos segundos**, y/o usar stop limitado en vez de mercado. Es
  uno de los mayores riesgos de cola del proyecto. Se decide más adelante con
  datos (los ticks del lago sirven para medir estos picos).
- **Halts en horario de mercado: usar las bandas LULD (limit up / limit
  down).** Salir de la posición si el precio está a un X % de la banda para
  no quedar dentro del halt. Si pilla dentro: cambiar a la ruta que permita
  salir lo antes posible en la reapertura. Cómo se leen las bandas (feed o
  L1 de DAS) está por ver.
- **Exposición al riesgo:** viaja unida al JSON de la estrategia, y habrá un
  cuadro de mandos propio para poner esos valores.
- **Telegram solo para lo que importa:** entradas, salidas, datos concretos y
  errores. **Las prealertas NO van a Telegram** en este bot; pueden servir
  para procesos internos (preparar orden, pedir locate).
- **Tamaño por fracción del volumen reciente desde el principio.** Hoy no es
  problema, con posiciones mayores sí; se deja preparado desde el inicio.
- **Locates — APUNTADO, se verá:** posible cambio de dinámica: vigilar el
  coste de locate de las acciones que «saltan» pronto en la sesión, porque
  suele ser cuando más baratas están. Perderse un trade con locate ya pagado
  puede compensar frente a pagarlo caro en la prealerta.
- **Premercado = órdenes límite.** Para SALIR, prefiere asegurar la salida
  aunque sea a peor precio: límite en el ask o bid ± X.
- **Protocolos por tipo de préstamo:** hard to borrow, easy to borrow,
  locates de un solo uso, etc. Posible regla de NO entrar en acciones en SSR
  porque favorecen squeezes. Depende de lo que diga el PDF.
- **VPS: sí.** Windows, con DAS dentro (el API de DAS es un socket TCP local
  a la aplicación de escritorio). El VPS es producción; el PC de Jaume es
  desarrollo. El bot en el VPS debe ser autosuficiente: estrategias como JSON
  exportado con hash y fecha, sin lago, sin backend, sin DuckDB.
- **El socio debe poder apagar / reiniciar / parar** por si Jaume no puede.
  Ver propuesta de tres niveles en el punto siguiente.

### Control compartido del VPS (propuesta, no complica)

Tres niveles, del más simple al más potente, y cada uno independiente:

1. **Telegram**: comandos `/estado`, `/pausar`, `/cerrar_todo` autorizados por
   `chat_id` (el mecanismo de recibir ya existe en `bot_alerts_comandos.py`).
   Los que cambian algo piden confirmación («/cerrar_todo SI»).
2. **Panel del proveedor del VPS** con un segundo usuario: reiniciar o apagar
   la máquina entera sin entrar en Windows. Al reiniciar, el supervisor
   arranca DAS y el bot, y el bot reconcilia antes de hacer nada.
3. **RDP con usuario propio** para lo demás (DAS abierto es el último botón de
   emergencia). Windows de escritorio admite una sesión RDP a la vez: es
   turnarse, no simultáneo; la edición servidor lo permitiría.

Más un **runbook de una página** con los tres niveles y el teléfono del bróker.

### Preguntas para el PDF de DAS (sin respuesta aún)

- ¿Identificador de orden propio del cliente (idempotencia)?
- ¿Stops residentes en el servidor de DAS? ¿Disparan en premercado y con qué precio?
- ¿Qué rutas aceptan extendido y qué tipos de orden admite cada una?
- Comandos de locate: consultar, aceptar, devolver; cómo se sabe si es ETB/HTB.
- ¿Cómo reporta el L1 halt, bandas LULD y SSR?
- ¿Qué pasa con el socket cuando DAS se reloguea o pierde sesión de noche?
- Cuota del API, límite de mensajes/s, ¿entorno de pruebas o demo?
- **¿Un solo login por cuenta?** Si el bot tiene DAS abierto en el VPS y Jaume
  abre DAS en su PC para operar a mano, uno echa al otro. Pedir segunda cuenta
  para el bot o confirmación de dos sesiones. Condiciona la fase sombra.

### Fases (cada una con criterio de salida)

1. **Documentación**: PDF, API activada, demo si existe. Contestar lo de arriba.
2. **Sombra**: el bot calcula la orden y la escribe en el diario SIN enviar;
   se compara con los fills manuales de Jaume. Sale con la divergencia medida.
3. **Adaptador solo lectura**: conectar a DAS, leer posiciones/cuenta/L1,
   reconciliar. Sale cuando un día entero cuadre sin intervención.
4. **Canario**: ejecución real con riesgo mínimo y topes duros.
5. **Riesgo real en el PC** con todo lo demás apagado. Después, VPS.

### Estimación de tiempos (5-sep, con PDF en mano y sin sorpresas)

Manda el número de premercados, no el código. Adaptador solo lectura 2 sem ·
Sombra 3 sem · Canario 3 sem · Riesgo real en PC 2-3 sem · VPS 2 sem.
**Unos 3 meses hasta riesgo real en el PC; 3,5-4 hasta VPS tranquilo.** Lo
estiran: sorpresas del PDF (client order id, stops en premercado, locates por
API), no tener demo, la disponibilidad de Jaume en premercado, y la medición
de picos de cola con ticks (hacerla antes del canario). Comparar luego con lo
real.

**Orden decidido (5-sep): se construye y valida en el PC; el VPS es lo
último.** Pero el VPS se PREPARA pronto (contratar, instalar DAS, usuarios,
RDP: lo puede hacer el socio en la semana 1-2); solo el traslado va al final,
y al trasladar se repite una semana de sombra y unos días de canario allí.
**Más adelante puede haber una estrategia en RTH**: diseñar las guardas desde
el principio para las dos sesiones (LULD, SSR, halts, mercado disponible; el
radar RTH necesita métricas que no existen antes de las 09:30).

**Objetivo de Jaume: 6 semanas** (sem 1 adaptador lectura + guarda + diario;
2-3 sombra y ejecutor contra demo; 4-5 canario; 6 VPS). Condiciones: PDF sin
sorpresas, cuenta demo, Jaume cada premercado, motor compartido congelado, y
**su estudio de picos/cisnes negros YA EXISTE: pedírselo con cifras** (magnitud,
duración, % que vuelve, tiempo) para fijar la guarda y el tipo de stop.

### Tareas de Jaume para la semana del 7-sep (no dependen del PDF)

1. Bróker: PDF + activar API; preguntar demo, dos sesiones o segunda cuenta,
   cuota, locates por API.
2. Estudio de picos con cifras (magnitud, duración, % que vuelve, tiempo; PM
   y RTH aparte) + umbral provisional «X % en Y s».
3. Exportar fills reales de DAS de las últimas sesiones manuales (referencia
   de la sombra).
4. Valores de exposición inicial: riesgo/op, pérdida diaria, exposición total y
   por ticker, fracción máx. de volumen reciente, tope de locates.
5. Elegir estrategia de estreno y exportar su JSON con fecha (versión congelada).
6. Congelar el motor: decidir ya los cambios pendientes en los tres ficheros
   compartidos (p.ej. unidad de riesgo en pirámide); lo demás, tras el canario.
7. Telegram propio para el bot de ejecución (bot + grupo + token nuevos).
8. VPS con el socio: elegir proveedor Windows cerca de NY, confirmar DAS y RDP,
   presupuesto. Contratar en semana 1-2 del plan.
9. Locates tempranos: apuntar a mano precios de locate de 2-3 tickers que
   salten, a distintas horas, durante 5 días (datos para P4).
10. Runbook borrador: teléfono del bróker, guardia diaria, qué hace el socio.

### Criterios de salida por fase (benchmarks)

1. **Solo lectura:** 3 sesiones con reconciliación 100 % igual a DAS; una
   reconexión provocada superada; latido sin fallos.
2. **Sombra:** ≥ 8 sesiones; cada señal con su orden calculada en el diario;
   divergencia vs fills medida (mediana y peor caso); ninguna orden calculada
   que la guarda debiera haber bloqueado; cero caídas.
3. **Canario:** ≥ 10 sesiones a riesgo mínimo; toda posición con stop
   residente en < N s; cero huérfanas, cero duplicadas; cada fill en el
   diario; cerrar-todo probado en vivo con posición abierta.
4. **Riesgo real en PC:** escalones 25/50/100 % con varias sesiones limpias
   cada uno; corte por pérdida diaria probado al menos una vez.
5. **VPS:** 1 semana en sombra + días de canario allí; simulacro completo del
   socio (pausa Telegram, reinicio panel, RDP).

## 1 — 2026-09-06 · Estudio de cisnes negros: directrices de Jaume

**Objetivo del estudio:** encontrar reglas para que el bot **NO cierre** un
corto durante un pico absurdo (el cierre arriba «te arruina la vida») y sí lo
haga cuando no es cisne negro. Con exposición adecuada se soporta un 100-200 %,
quizá 500 %; jamás 1000-5000 %. Todos los observados hasta hoy **caen siempre**.
La pregunta es «¿cuándo no cerrar?»: si sube más de X % en X s y no toca el
stop limit, observar y reportar, no cerrar; salir después, cuando el precio se
estabilice lo más cerca posible de la entrada y haya pasado X tiempo (perder
50-100 % de la posición, no media cuenta).

**Tipo 1 — premercado.** Libro vacío, sin contrapartida, el precio salta
100…5000 % en menos de un minuto. Búsqueda: velas de 1 min en premercado con
`(high - open) / open ≥ 50 %`, sin techo. Analizar en conjunto y por tramos
(50-100, 100-500, 500-1000, >1000 %), y también en función de Dollar Volume,
Dollar Volume acumulado y Premarket Volume acumulado. Estadística descriptiva
de: cuánto tardan en caer, hasta dónde caen, disparadores. Luego spread y
ticks antes/después con Massive; después Level 2 con Databento (y cualquier
otro dato útil que Databento ofrezca).

**Tipo 2 — RTH / halts.** Más comunes; basta una MUESTRA, no lista completa.
Mayoría entre 09:30 y 11:00. Hipótesis de detección: velas RTH con volumen 0
= halt (comprobar si Massive marca halts en el histórico). Analizar spread,
liquidez (volumen medio por vela antes del halt y tras reabrir), si daría
tiempo a salir y con qué tamaño. Quiere IDEAS de protección basadas en datos.

**Orden:** primero lista de eventos (lago), luego Massive (spread, ticks),
luego Databento (profundidad). La clave de Databento la da cuando se pida.

### Fase A, paso 1 y 2 HECHOS (6-sep): barrido y contexto

Scripts y datos en **`D:ot_senales\estudio_cisnes\`** (fuera del repo, como
los demás del bot): `01_barrer_velas.py` → `candidatos_velas.parquet` (2.701
velas de PM con (high-open)/open ≥ 50 %, 2019-2026, ~6 min de disco);
`02_contexto_eventos.py` → `eventos.parquet` (2.343 eventos; agrupa velas a
< 10 min; `velas_eventos.parquet` es la caché de los días, 4 min de lectura).

Definiciones provisionales (parametrizadas arriba del script 02): nivel_pre =
close de la vela anterior al evento; pico = high máximo en 10 min; vuelta_X =
minutos desde el pico hasta el primer close ≤ nivel_pre·(1+X) dentro del PM
(`_dia` = hasta el cierre); retención = open 09:30 vs nivel_pre.

**Datos del lago que condicionan el estudio:**
- Los ticks (`parquet/trades_premarket`, 21 GB, 2019-2026) solo cubren tickers
  con `es_candidato` (gap día ≥ 10 %, RTH vol ≥ 400k, CS/ADR, sin warrants):
  ~300 tickers/día. Muchos eventos no tendrán ticks.
- El lago NO guarda velas con volumen 0: **un halt es un HUECO en los
  timestamps**, no una vela vacía. Detección tipo 2 por huecos.
- 520 eventos son warrants/rights/units y 383 tienen precio < 0,10 $: fuera
  de la base principal (universo base: 1.776 eventos).

**PRIMER HALLAZGO (cambia la pregunta):** «todos vuelven» NO es cierto en
general; es cierto para los que YA estaban en juego. Con salto ≥ 100 %:
- dollar volume acumulado antes del pico **> 1 M $**: 80 % vuelve a +50 % en
  PM, mediana **1 minuto**, p90 8 min; retención mediana a las 09:30 **+5 %**.
- **< 10 k $** antes del pico (48 % son la primera vela del día): solo 52 %
  vuelve, retención mediana a las 09:30 **+67 %**. Eso es una noticia que
  reprecia, no un libro vacío.
- Los que no vuelven aun con > 1 M $ (21 de 104) abren a las 09:30 entre
  +65 % y +427 %: hay que mirarlos uno a uno (¿noticia a mitad de PM?).

### Fase A v2 (6-sep, tarde): referencia = OPEN de la vela del cisne

Definiciones cerradas con Jaume: ref = open de la primera vela del evento;
tipo A = vela única ≥ 50 %; tipo B = escalera (5 min, ≥ 50 % acumulado sin
vela ≥ 50 %); base = sin warrants/rights/units y ref > 0,50 $; «en juego» =
gap previo ≥ 20 % (máximo de PM antes del evento vs prev_close), que es lo que
opera. Scripts `03_barrer_escalera.py` (12.370 filas) y `02_contexto_eventos.py`
v2 → `eventos.parquet` (7.257 eventos: 2.337 A, 4.920 B; base 4.528).
Ficheros: `top50_en_juego.csv` (44/50 con ticks en el lago),
`no_vuelven_en_juego_triage.csv`.

**Resultados, base, salto ≥ 100 %, en juego (386 eventos, ~50/año):**
- Vuelve a +50 % sobre ref en PM: 72 %. Mediana 8-13 min, p90 110-140 min.
- Camino mediano tras el pico: +81 % a 5 min, +60 % a 30 min, +45 % a 60 min,
  +27 % (A) / +41 % (B) a las 09:30. p95 a 30 min: +200/+290 %. p99: +324/+468 %.
- Mínimo de PM tras el pico (hasta dónde cae): mediana +16 % (100-200),
  +26 % (200-500), +21 % (>500); p25 ≈ ref (−5/−2/−1 %); p95 +86/+136/+157 %.
- 107 no vuelven a +50 % en PM: 62 sí en RTH, 6 sin tiempo (≥ 09:19), 1 split,
  1 sufijo Z/V, y **37 se quedan arriba TODO el día** (10 % de los ≥ 100 %):
  XHG, GRYP, HYFM, FCUV, SBET, MOVE, SPRB, WLDS… Son noticias que reprecian,
  no libros vacíos. **«No cerrar» a ciegas habría sido catastrófico en 1 de
  cada 10.** La regla tiene que distinguirlos; candidatos a discriminador:
  ticks/volumen en el pico, si el precio se sostiene N min, dollar volume.
- Tramo 50-100 % (A: 948, B: 2.438): benigno, 92-94 % vuelve, mediana 1 min.

### Aclaración de Jaume (6-sep) y medida de «devolución» del salto

Jaume: los peligrosos son los **flash BS** (open→high en UNA vela de 1 min);
los **low BS** (escalera) suelen tener liquidez para salir. Centrarse en PM.
Mi «se quedan arriba» le chirriaba: la métrica de vuelta a +50 % sobre el open
del cisne mezclaba el fogonazo con el nivel al que reprecia la acción (XHG
13-ago: 1,38 → 18,08 → cierra la vela en 2,66; el pico se deshizo en el
minuto, la acción no volvió a 1,38). Nueva métrica: **% del salto devuelto**
al cierre de la vela del pico y a los 5 min (`devolucion_en_juego.csv`).

**Resultado, flash (A) en juego, salto ≥ 100 % (208 eventos):** al cierre de
la vela del pico se devuelve de mediana solo el **21-25 %** del salto (>500 %:
57 %); a los 5 min, el **50 %**. El cierre de la vela del pico queda de
mediana a **+100 %** sobre el open del cisne (200-500: +188 %). 166 de 208
devuelven < 50 % dentro de su vela. O sea: **el fogonazo que sube y baja en
segundos es la EXCEPCIÓN en velas de 1 min**; lo típico es que el precio se
quede arriba minutos y baje en decenas de minutos u horas (mínimo de PM
mediana +16/+26 % sobre el open; p95 +86/+136 %). Escalera (B): 178 eventos,
mediana 8 min y 7-11 velas hasta el máximo; devuelve 17 % en la vela, 33 % a
5 min. **Falta la vista por ticks (segundos) de los 44 del top 50 con ticks,
y la lista de ejemplos del estudio de Jaume para calibrar.**

### Niveles a 5-120 min, ticks del top 50 y coste de Databento (6-sep, noche)

Jaume: no hay regla fija de flash por segundos; flash = «se dispara una
barbaridad dentro de un minuto». Lo que quiere para la EXPOSICIÓN: hasta dónde
llegan y en qué nivel se quedan a 10-15-30-60-120 min desde la apertura del BS.
Tabla completa en la respuesta del chat (script inline; reproducible con
`eventos.parquet` + `velas_eventos.parquet`). Resumen flash en juego ≥ 100 %:
tramo 100-200 → nivel mediano +69 % (10 min), +51 % (30), +38 % (60), +27 %
(120); peor visto p95 +184/+236/+274/+315 %. Tramo 200-500 → +131/+101/+78/
+52 %; peor p95 +398/+500/+500/+543 %. Tramo > 500 (n = 12) → +177/+215/+163/
+124 %; peor p99 +4.010 %.

**Ticks del top 50 (`04_ticks_top50.py` → `ticks_top50.csv`, 44 eventos):**
aparecen DOS familias. (1) **Fogonazo de libro vacío**: CIIT, PLYX, XHG
(2026), SLGB, ODP ×2, GLE: el precio está por encima del 50 % del salto
**≤ 10 segundos**, con 75-1.200 operaciones, y devuelve el 83-98 % en 10-30 s.
(2) **Movimiento real**: el resto (37): cientos de segundos por encima del
50 % del salto, miles de operaciones, devuelve solo 20-50 % a los 5 min.
Discriminador candidato para el bot: **segundos sostenidos por encima de X %
del salto** (y operaciones); si lleva > N s arriba con volumen, es real y hay
que salir; si no, esperar. Pendiente de fijar N con los datos y el L2.

**Databento**: clave guardada en `backend/.env` (`DATABENTO_API_KEY`, ignorado
por git). Coste medido con `metadata.get_cost` sin descargar: CIIT 1 día
04:00-10:00 ET → XNAS.ITCH mbp-10 **0,0026 $** (6,9 MB), mbp-1 0,001 $,
trades 0,001 $; EQUS.MINI (consolidado NBBO) mbp-1 0,0016 $. **Los 50 eventos
con las tres capas ≈ 0,30 $ y ≈ 400 MB.** No se ha descargado nada: falta el
OK de Jaume.

### CORRECCIÓN DE JAUME (6-sep, noche): qué es el flash BS de verdad

Los gráficos de «movimiento real» (BTOG, HYFM, POAI, CERO…) **NO son cisnes**:
son el gap normal del día, el salto con el que la acción «salta» desde el
cierre anterior y por el que se tradea. **El flash BS peligroso es el de
PLYX, XHG, SLGB, CIIT: la acción YA había subido ≥ 20 % desde el cierre de
ayer y en algún momento hace un fogonazo que se deshace en segundos.** Los
escalonados de varias velas ≥ 50-100 % también cuentan, pero cree (a
comprobar) que ahí hay liquidez para salir aunque sea con 30-50 % de
slippage. Sugerencia suya: cruzar con las operaciones de 1B para localizar
algunos (habría muchos más que 1B no tomó).

Consecuencia: la vela de 1 min no basta; hay que barrer los TICKS
(`trades_premarket`, universo es_candidato = gap ≥ 10 % y vol ≥ 400k, justo
el universo tradeable) con definición por segundos: precio ya en gap ≥ 20 %,
subida ≥ 50 % en ≤ 60 s sobre el último precio, y devolución ≥ 70 % del salto
en ≤ 60 s tras el máximo. Script `07_barrer_ticks_flash.py`.

### Barrido de ticks por segundos: crudo vs limpio (6-sep, noche)

`07_barrer_ticks_flash.py` (12 min los 8 años; `--limpio` aplica la regla del
lago: `delay_ns < 10 ms` y hora de EJECUCIÓN; la devolución se mide sobre el
último precio de cada segundo, no sobre el low, para que un print bajo suelto
no cuente). Salidas: `flash_ticks.parquet` (crudo, 5.360), `flash_ticks_limpio.parquet`
(377), `flash_reales_limpio.csv` (352), `flash_prints_sueltos_limpio.csv` (25).

**HALLAZGO GORDO: el 93 % de los «flash» del crudo son prints tardíos o
dark pool** (delay > 10 ms) o un print bajo suelto. Jaume avisó de que los
dark pool publican tarde. En el libro real hay **352 flash en 8 años**:

| tramo | n | por año | s hasta máx (med) | s por encima de la mitad del salto (med/p75) | devuelto 60 s | nivel a 5 min med / p95 |
|---|---|---|---|---|---|---|
| 50-100 | 307 | 40 | 49 | 156 / 304 | 84 % | +15 % / +88 % |
| 100-200 | 28 | 3,6 | 40 | 44 / 91 | 83 % | +10 % / +120 % |
| 200-500 | 13 | 1,7 | 34 | 16 / 150 | 87 % | +26 % / +127 % |
| > 500 | 4 | 0,5 | 39 | 4,5 / 66 | 99 % | +39 % / +273 % |

Los > 500 %: ENSC 11-may-2026 (4.836 %, 4 s arriba), CIIT 9-mar-2026 (4.450 %,
5 s), XHG 13-ago-2026 (811 %, 248 s), ODP 30-jun-2020 (537 %, 0 s). 2025-2026
concentran el 65 % de los casos (más universo, más manía). Horas: 04:xx y 08:xx.

**Implicación para el bot:** los prints tardíos NO están en el libro pero SÍ
en la cinta (SIP): entran en el `high` de las velas `AM` de Massive y en el
lago. Un stop que dispare por «último precio» o por `high` de vela se come
esos prints; un stop que mire el libro (bid/ask) no. Pendiente ver cómo
dispara DAS (pregunta del PDF).

Databento: 150 ficheros descargados sin error, **coste real 1,25 $** (estimé
0,30 $; los días activos pesan 70 MB). Cubren el top 50 por velas de 1 min,
que NO coincide del todo con la lista de flash reales por ticks: faltan por
descargar los flash limpios ≥ 100 % que no estén (~30 días, ~1 $).

### Fase B: primer vistazo al LIBRO (6-sep, noche) — `08_libro_eventos.py`

Databento descargado para el top 50 antiguo (1,25 $) y en descarga los 38
flash limpios ≥ 100 % que faltaban (`05b_descargar_pendientes.py`, ~1 $, OK de
Jaume). Libro por segundo en `libro/libro_<ticker>_<fecha>.csv` y resumen en
`libro/libro_resumen.csv`. **Limitación: XNAS.ITCH es SOLO el libro de Nasdaq**,
no el consolidado (ARCA, EDGX, etc.): la profundidad real es mayor.

**Mecanismo visto en los 10 primeros:** el ask visible en 10 niveles era
RIDÍCULO antes del fogonazo: ENSC 4-7 k$, CIIT 1,3 k$, GRYP 0,5-4,5 k$, PLYX
5 k$ (29 k$ un minuto antes → se vació), en acciones que negociaban millones.
Una compra a mercado de 10 k$ se come el libro entero y el precio salta hasta
donde haya la siguiente orden. En el máximo: spread 40-190 %, 2-6 niveles. Los
que NO son fogonazo puro (SCKT) tenían 17-18 k$ en el ask y 10 niveles.
**Indicador candidato en vivo: dólares en el ask a 10 niveles** (DAS da L2).
ODP 30-jun-2020: spread negativo constante = día de contrasplit 1:10, libro
corrupto → EXCLUIR.

### NBBO (lo que el bot verá) — `09_nbbo_eventos.py` → `libro/nbbo_resumen.csv`

**Jaume: DAS NO da Level 2 por API, solo NBBO (bid/ask y su tamaño).** ODP
30-jun-2020 excluido (contrasplit). Descarga extra: 0,60 $ (total Databento
1,85 $). EQUS.MINI cubre 2023+ (FORG, PFIN, VACC, YELL sin NBBO) y en varios
tickers no hay cotización antes de las 08:00 ET.

Resultado sobre 21 flash ≥ 100 % con NBBO: el **spread** en los 60 s previos
está en el percentil 70 del día (mediana 22 % vs 6 % el resto del día) y el
**tamaño en dólares del mejor ask** en el percentil 14 (mediana 178 $ vs 229 $),
pero con enorme dispersión: el mejor ask en estas acciones es casi siempre de
100-200 acciones, con o sin fogonazo. **Conclusión: el NBBO avisa poco y
tarde; no sirve como predictor fiable.** Lo que sí es robusto es lo
posterior: segundos sostenidos por encima del salto + tope de exposición.
La profundidad a 10 niveles (que sí discrimina) no estará en vivo.

### 7-sep: barrido v2, stop limitado escalonado, halts e INFORME PDF

- **Fallo corregido en `07_barrer_ticks_flash.py`**: un candidato que no
  cumplía la devolución bloqueaba los 60 s siguientes y se saltaba el máximo
  real (SLGB quedaba fuera). v2 limpio: **685 flash reales** (v1: 352).
  Tramos: 50-100 → 590 (77/año); 100-200 → 67 (9/año); 200-500 → 22 (3/año);
  > 500 → 6 (ENSC, CIIT, TNON, XHG, ODP-excluido, GRYP). `flash_ticks_limpio_v1.parquet` es la versión vieja.
- **Stop limitado escalonado (`11_stop_limitado.py`)**: pregunta de Jaume
  («¿3-4 limitados escalonados y si no los coge que corra?»). Resultado: el
  precio CAMINA, no salta: en +20 % se ejecutaría en 654 de 678, en +100 % en
  85 de 93; ENSC operó 27.000 acc en la banda +20 %. Y un limitado disparado
  sin ejecutar queda colgado y se ejecuta a la vuelta. **Jaume: NO quiere
  reglas para el bot todavía, solo investigar y sacar conclusiones.**
- **Halts**: la detección por huecos de 1 min es mala (huecos de iliquidez).
  **Databento `status` (XNAS.ITCH) da halt/reanudación exactos con motivo y
  bandera SSR**: 0,03 $/día todo el mercado 09:00-12:00 ET. Pedido OK a Jaume
  para ~2-3 $ (60-90 días). Sin respuesta aún.
- **INFORME PDF ENTREGADO**: `D:ot_senales\estudio_cisnes\Informe_cisnes_negros_premercado.pdf`
  (`12_informe_pdf.py`, venv propio `.venv_informe` con matplotlib+reportlab;
  figuras en `informe_figs/`). Lenguaje llano, 7 secciones, 6 gráficos.
- Coste total Databento hasta hoy: **1,85 $**.

### 7-sep (tarde): informe del socio, cruce con 1B, halts en descarga

- **Informe del socio** (`C:\Users\Famil\OneDrive\Escritorio\informe_blackswans.pdf`,
  texto en `estudio_cisnes/informe_socio.txt`, fechado 3-sep): 2.799 shorts
  reales del diario de Jaume (ene-2025→jul-2026) × 202 velas explosivas (high
  ≥ 2× open en 1 min). COINCIDE con lo mío en lo esencial: «el spike no
  teletransporta, sube printeando cientos de veces por peldaño» (= camina, no
  salta); en PM no hay órdenes a mercado; discriminador squeeze vs re-rating =
  % del spike devuelto a los 15 min (≥ 50 % → squeeze); PSTX/TLPH = mi familia
  «noticia». Aporta además: el «segundo empujón» tras la vela (25 fades
  perdedores), fills reales de stop-limit ×1,007 del trigger (95 % ≤ ×1,07), y
  RECOMIENDA stop-limit con límite ancho ×1,4-2,0 + capa de reversión aparte al
  0,10-0,25 % del equity. (Jaume no quiere reglas aún; es la propuesta del socio.)
- **Cruce con 1B** (run guardado 4d1514df, 3.024 trades 2025-01→2026-08, leído
  de una COPIA de users.duckdb; `cruce_1b_flash.csv`): 413 flash en el rango,
  192 en ticker-días operados. **10 flash DENTRO de una posición** (todos
  salieron por SL, retorno −22 a −65 %): SLGB 9-jun-2026 (pico ×6 la entrada),
  GLE 10-sep-2025 (×5,3), PLYX, GURE, LGHL, TMDE, HCAI, NIVF, GVH, AEHL. Los
  dos grandes coinciden con el informe del socio. **247 trades entran DESPUÉS
  de un flash** (mediana 13 min): retorno mediano +15 % vs +8 % del total; con
  flash de 100-500 % previo, +29/+35 %. Igual que la sección D del socio.
- **Halts**: OK de Jaume. `13_descargar_halts.py` baja `status` de XNAS.ITCH
  de todo el mercado, 92 días (27-abr→4-sep-2026), 0,03 $/día, a
  `databento/status/<dia>.csv`. El mapa instrument_id→símbolo NO se pudo hacer
  al vuelo (límite de símbolos por petición): hacerlo por lotes de 1.000 en el
  análisis. Detección de huecos en velas (`10_halts_rth.py`) DESCARTADA.
- **Backend colgado** el 7-sep: `/api/robustness/strategies` y `/vigiladas` no
  responden en 20 s (`/estado` sí, va por caché). Había DOS uvicorn (uno con el
  venv, otro con el Python global). Avisado a Jaume; no toqué nada.

### 7-sep (noche): espera/exposición PM, halts a fondo, INFORME v3

- **Exposición en PM: Jaume baraja 3-4 % de la cuenta por ticker en total
  (entrada + pirámides). NO ES DECISIÓN: no se decide nada aún; el valor iría
  al cuadro de mandos. No quiere reglas de múltiplos.** Tabla de
  espera (`espera_perdida_cuenta.csv`, 93 flash ≥ 100 %): cerrar en el pico
  con 3 % → media 8,8 %, peor 145 % (ENSC/CIIT ×49); esperando 30 s → media
  2,1 %, peor 14 %; a 5 min → p95 5,2 %. Esperar más de 1 min no baja el p95.
- **Halts a fondo (`15_halts_profundo.py`)**: regla «salir a X % de la banda»
  es MALA como automatismo (10 % de margen: 69 % de halts avisados con 2 % de
  acierto). Liquidez: mediana 725 k$ en el minuto de reapertura, p10 30 k$.
  Cadenas: 6+ halts (21 ticker-días/92) llegan de mediana a ×2 y no vuelven;
  PAVS 9-jun-2026: 7 halts, ×13. Exposición en halts con 3 %: media 1,1 %,
  p95 3,8 %, peor 35 %. Cruce experimental con la estrategia RTH del disco
  (run 02517fef): 23 halts dentro de 175 trades, 20 acabaron bien, 3 SL.
- **Informe v3 entregado** con secciones 9 (espera) y 10 (halts). Coste total
  Databento: 4,7 $.

### 7-sep (noche, 2): barrido definitivo, sensibilidad, controles, informe v4

- **Dos fallos más del barrido corregidos** (los detectó Jaume viendo PLYX a
  10 $ en la tabla cuando llegó a 76 $): (a) los racimos de candidatos se
  cortaban a 60 s y el máximo real venía después; (b) ENSC se perdía porque
  el primer segundo del racimo no tenía «máximo previo». Ahora un racimo = un
  evento, ref = primer segundo con máximo previo, pico = máximo hasta 60 s
  tras el último candidato. `flash_ticks_limpio.parquet` es la versión final
  (297; 276 reales sin ODP); v1/v2/v3a/v4 guardados con sufijo.
- **Sensibilidad** (`flash_ticks_limpio_todos.parquet`, DEVUELTO=0 y el umbral
  al analizar): con devolución ≥ 50 % → 633 eventos; ≥ 70 % → 274; ≥ 90 % → 74.
  Los > 500 % son estables (8-10) y el precio a 5 min también (+16/+26 %
  mediana, p95 ~+112 %). **El recuento es definicional; el comportamiento no.**
- **Recuento final ≥ 100 %: 56 en 8 años, 35 en 2025-2026 (≈ 21/año ahora vs
  7/año de media). > 500 %: 8, 6 de ellos en 2026.** Jaume pidió que el
  informe dé siempre la media de 8 años Y la de los 2 últimos años.
- **Controles** (`16_controles.py`, `17_libro_vs_controles.py`, 0,66 $): 21
  pares fogonazo vs día parecido sin fogonazo (gap ≥ 50 %, 2023+, otro
  ticker). Todo el PM: igual (fogonazo < control en 11/21). 2 min antes:
  −36 % dólares, −25 % órdenes, spread ×5, pero solo en 12/21. **El día no es
  raro; lo local es débil e inconsistente.**
- **Tabla de espera rehecha** (56 eventos ≥ 100 %): en el pico con 3 % →
  media 14 %, peor 145 %; a 30 s → media 2,6 %, p95 5,8 %; a 5 min → p95 7,2 %.
- **Cruce 1B rehecho**: 7 flash dentro de posición (PLYX, SLGB, GLE, AEHL,
  NIVF, LGHL, GVH), 97 antes de entrar.
- **Informe v4 entregado** con sensibilidad, controles, recuento por años y
  las dos aclaraciones de Jaume (no es «su estrategia», es cualquier corto; y
  la media de 8 años engaña). Coste total Databento: ~5,4 $.

### 7-sep (noche, 3): el stop de 1B — nivel, mercado vs limitado, tamaño (informe v5)

Pregunta de Jaume: ¿stop 1 % bajo el Previous Max (más liquidez) o +30-40 %,
mercado o limitado (bandas 10 %, ×1,5, ×2), y a partir de qué tamaño cambia?
Marco: cuenta 10.000 $, 2-3 % por operación (= 300 $ de posición).
`18_stops_1b.py` → `stops_1b_sim.parquet` (2.715 operaciones de 1B con ticks,
4 niveles × 4 tipos × 6 tamaños; se consume la cinta al 50 % de cada print).
Tablas `stops_A_niveles.csv`, `stops_B_resultado.csv`, `stops_C_liquidez_*.csv`,
`stops_P_peor.csv`. OJO signo: en el parquet `perdida_pct` positivo = GANANCIA.

- **Nivel:** +10 % (el actual) es el mejor: 4,3 % medio/op, 63 % ganadoras.
  −1 % bajo el PM: salta el 50 % (vs 30 %), 3,6 % medio, 47 % ganadoras: NO
  compensa. +30/+40 %: salta 1 %, pero cuesta 59/76 % de mediana (p95 99/179 %),
  media 4,1 %.
- **Tipo y tamaño:** hasta 3.000 $/posición (cuenta 100 k al 3 %) igual todo
  (slip p95 < 1 %). A 10.000 $ el limitado 10 % deja 3/814 colgados; a 30.000 $
  20 colgados, slip p95 2 %; a 100.000 $ 4-5 % sin cubrir. Con stop en +30 %
  el mercado se dispara (slip p95 53 % a 100 k) y el limitado 10 % lo tapa (7 %).
  **La única diferencia a tamaño pequeño es la cola: un stop a mercado de 300 $
  se ejecutó una vez contra un print suelto a 5,6× el nivel; el limitado lo tapa.**
- Informe v5 entregado con la sección 11. Sigue sin ser regla.

### 11-sep: cierre forzado, stop a mercado contra el libro, halts largos (informe v6)

Tres análisis pedidos por Jaume; scripts 19-24 en `D:\bot_senales\estudio_cisnes`.
- **Cierre forzado (`19_cierre_forzado.py` → `cierre_forzado.csv`)**: corto a ref,
  stop mental +50/+100 %, cierre a 30/60 min. En ≥ 100 % vuelve al +50 % el 86 %
  y al +100 % el 96 %. En ≥ 500 %: 5 de 8 vuelven en < 2 min; TNON, XHG y GRYP no.
  Con 3 %: peor 22 % (30 min) / 29 % (60 min), siempre TNON. Esperar más no ayuda.
- **Stop a mercado ADITIVO contra el libro (`20_stop_mercado_libro.py`)**: nuestras
  acciones consumen el ask de 10 niveles de Nasdaq en el disparo (+50/+100 %); el
  resto al VWAP de 10 s (opt) o al máximo de 30 s (pes). Libro mediano 2.500 $:
  1.000 $ cabe entero 61 %, 5.000 $ 32 %, 30.000 $ 4 %. Pérdida mediana sobre la
  posición al +50 %: 68 % (1 k$) → 88/144 % (10 k$). **7 de 56 disparos tenían una
  orden basura (25 $, 10.000 $, 199.999 $) dentro de los 10 niveles** — un mercado
  sin protección se la come. Solo libro Nasdaq.
- **Halts largos**: la detección por huecos en velas (`21_halts_largos.py`, 8 años,
  49.668 candidatos) **NO VALE** — calibrada contra status 2026: recall 11 %,
  precisión 10 % (medias sesiones, iliquidez). Massive no lleva halts. Fuente
  exacta: Databento `status`. 2026 (92 días, 09-12h): 11 T1, 66 T2, 3 T12.
  **Estrategias con status exacto (`24_status_estrategias.py`, ~0 $)**: PM 1B TTP
  (4.424 ops, run 8b773d84) → 5 posiciones con T1 de 25-50 min, todas reabren,
  peor −30 % (COMM). RTH 2B TTP (1.323 ops, run 6023ec78) → 404 posiciones (30 %)
  con LULD dentro, 76 con ≥ 3 encadenados; peores RGC −169 % (6 halts), PAVS
  −156 %, HKIT −126 %. **Ningún T12 ni baja dentro de posición; ninguna salida
  atrapada.** OJO MOTOR: 77 de 256 SL de 2B saltan en la vela de reapertura y el
  motor los llena AL NIVEL; real = open de reapertura (mediana −3 %, p90 +4,8 %,
  máx +14,5 %); en conjunto el backtest sale algo pesimista, no optimista.
- Cubrir TODO el mercado 2019-2026 con status exacto cuesta **51 $** (0,027 $/día
  × 1.930). Pendiente de OK de Jaume. Informe v6 entregado (secciones 12-14).

### Convención (Jaume, 11-sep): los datos de estos estudios van FUERA del lago

Todo lo descargado para el estudio (Databento: libro MBP-10, NBBO, cintas,
`status` de 2026, de las estrategias y de TODO el mercado 2019-2026; y cualquier
extracto de Massive) vive en `D:\bot_senales\estudio_cisnes\databento\<tipo>\`,
nunca en `D:\lago_backtester`. Los scripts numerados (01-28) en la carpeta
padre regeneran cada fichero. Es documentación aparte para pruebas futuras.

### 11-sep (tarde): halts de TODO el mercado 2019-2026 y predictores del fogonazo (informe v7)

- **Databento `status` completo**: 1.930 días, 0 errores, **50,61 $** (presupuesto
  exacto pedido antes con get_cost; descarga con tope 55 $). 3,7 GB en
  `databento/status_mercado/`. `25_status_mercado.py`, análisis `28_*.py`,
  parquet `halts_mercado_2019_2026.parquet` (277.645 halts, 20.994 símbolos).
  OJO: el mapa instrument_id→símbolo es POR DÍA (Nasdaq reasigna); se resuelve
  solo para los ids con halt (1 lote/día). Símbolos reutilizados y cambios de
  ticker generan reaperturas falsas (SMR, GOLD ×70): filtrar px_antes ≥ 0,5 y
  coherencia con prev_close. Muchos T12 a las 19:55 son bajas por fusión, no
  suspensiones.
- Resultados: 61.287 LULD, 4.542 T1, 747 T12. T1 reabre mediana +1,7 %, p95
  +64 %, máx +475 % (ABVX 22-jul-2025). LULD ≥ 30 min: mediana +20 %, p95 +307 %,
  máx +2.795 % (INHD 8-jun-2026), QMMM +1.395 %, PGHL +858 %. **Suspensiones
  reales en valores operables (gap ≥ 20 o vol ≥ 200k) sin cotizar 90 días: 8
  en 8 años; 5 en gap ese día (ONCR, ASPA, NOVV, HYZN, GATE), todos T12 a
  partir de las 11:50.** Ninguna con posición de 1B/2B dentro.
- **Predictores (`26_*`, `27_*`)**: nivel día tiene fuga (gap y volumen del
  día incluyen el fogonazo). Nivel instante (253 fogonazos vs 13.620 controles
  a la misma hora): lo que separa es la DELGADEZ: < 14k acciones acumuladas
  (7,8 % vs 1,8 % base), < 107 operaciones, vol medio 20d < 88k, primera media
  hora. Gap previo y precio apenas. Logístico in-sample: top 1 % de instantes →
  19 % de los fogonazos con 34 % de acierto; top 5 % → 46 % con 16 %. Sirve
  como aviso, no como filtro. Sin validación fuera de muestra.
- Informe v7 entregado (secciones 15 y 16).

### 11-sep (noche): T12 y T1 reales, uno a uno (informe v8)

- **TRAMPA DE DATOS**: los T1/T12 de Nasdaq a las 19:50/19:55 son acciones
  corporativas (T1 = contrasplit → «reabre» ×100; T12 = baja por fusión). Los
  reales son los de PM/sesión. `29_t12_detalle.py` → `t12_reales.csv`,
  `t1_sin_reabrir_detalle.csv`.
- **REGLA (Jaume): excluir contrasplits y fusiones, y solo CS/ADRC** (tabla
  `tickers` del lago; `t12_reales_cs_adrc.csv`, `t1_sin_reabrir_cs_adrc.csv`;
  REED 25-ene-2023 es un contrasplit que la tabla de splits no tiene).
- **T12 reales CS/ADRC**: 27 en el lago (2 PM, 25 sesión); 11 volvieron
  (mediana 10 días, máx 142), 16 nunca, 9 de ellos SPAC liquidados. Sin filtro
  de tipo: 106 en 8 años, 33 en el lago ese día (3 PM, 30 sesión,
  08:24-15:35, grueso 11-15h). 16 volvieron (mediana 2 días, máx 142; reabren
  mediana 0 %, p95 +75 %, máx NEXI +201 %). **17 no volvieron nunca** (ONCR,
  ASPA, NOVV, HYZN, GATE, GGAA, XOG…). 7 en gap ≥ 20 ese día + 3 con gap en
  los 30 días previos (mediana 4 días antes). Ninguno reabrió > 500 %.
- **T1 en sesión sin reabrir ese día, CS/ADRC**: 20; ninguno > 500 %; peor
  AMLX +79 % (1 día), SRDX +49 %; 4 no volvieron (LBPS, DUNE, OPT, KRON).
- Fuentes para halts en vivo: Nasdaq Trader Trade Halts (RSS, códigos y
  reanudación), NYSE halts, SEC trading suspensions, Nasdaq Daily List (splits
  con antelación). No hay lista previa de T1/T12; señales: 8-K de
  incumplimiento, cuentas atrasadas, T1 reciente.

### 11-sep (noche, 2): fichas de los T12/T1 peligrosos (`30_fichas_t12_t1.py` → `fichas_t12_t1.csv`)

- **Cadena T1→T12 NO existe**: en 194 T12 reales, 0 con T1 el mismo día, 4 con
  T1 en los 10 días previos. Nasdaq marca el T12 directamente (verificado en
  los mensajes brutos). NEXI: T12 en PM (08:24, gap +438 %) que REABRIÓ el
  mismo día a las 14:26 a 7,47 (bajo el máximo de PM 13,35).
- **T1 sin vuelta (LBPS, DUNE, OPT, KRON)**: ninguno en gap, todos cierres de
  empresa (concurso, baja de SPAC, salida de Nasdaq, adquisición). No es cola.
- **T12 sin vuelta, riesgo de cola REAL para un corto (gap ese día, con
  volumen, no volvieron a Nasdaq)**: GATE 1-abr-2025 (SPAC, +170 %, 21→53→36,
  5 LULD, T12 12:02), GGAA 13-jul-2023 (SPAC, 12→49→22, 16 LULD, 15:35), ASPA
  25-oct-2023 (SPAC, +138 %, 13→38→27, 7 LULD, 14:13), NOVV 13-sep-2024 (SPAC,
  +127 %, 21→55→37, 14 LULD, 13:43). Patrón: cascarón ilíquido que se dispara
  ×2-4 con cadena de LULD y Nasdaq lo para por la tarde. HYZN y ONCR están
  en/bajo el suelo de 0,50 $. Los otros 5 T12 sin vuelta son SPAC liquidados a
  10 $ sin gap (REVH, PCX, DTRT, AFAR, GLST): cero peligro.
- **Conclusión**: con CS/ADRC, gap ese día y precio > 0,50 $: 4 T12 sin salida
  en 8 años, todos SPAC, todos con cadena de LULD antes, todos 12:00-15:35,
  ninguno en PM; 0 T1 peligrosos.

---

## Estado y pendientes

**Estudio de cisnes negros: CERRADO el 7-sep-2026** (Jaume). Informe v4 en
`D:\bot_senales\estudio_cisnes\Informe_cisnes_negros_premercado.pdf`; datos y
scripts en esa carpeta (fuera del repo). Coste Databento total ≈ 5,4 $.
**Nada del estudio es regla del bot**: son conclusiones; los valores irán al
cuadro de mandos cuando se diseñe.

| # | Pendiente | Estado |
|---|---|---|
| P1 | PDF del API de DAS + activación en Sage. Preguntas al bróker: client order id; stops de servidor y si disparan en PM; rutas con extendido; locates por API (inquire/accept/return, ETB/HTB); cómo llega halt/LULD/SSR en el L1; socket al reloguear; cuota, límite msg/s, demo; **un solo login por cuenta → segunda cuenta para el bot**; **qué hace Sage con una cuenta muy en negativo en PM** | Esperando al bróker |
| P2 | Tipo de stop y guarda de fogonazo: SIN decidir. Datos de 1B en v5 §11: +10 % es el mejor nivel; limitado tapa el print suelto; tamaño importa desde 10 k$/posición. Conclusiones en el informe: el precio camina (un limitado se ejecuta en la subida); prints tardíos entran en último precio y velas; lo que separa fogonazo de subida real es cuánto se sostiene | Abierto, para el diseño de guardas |
| P3 | Exposición por ticker: Jaume baraja 3-4 % en total (entrada + pirámides). NO decidido; iría al cuadro de mandos | Abierto |
| P4 | Locates: dinámica «pronto y barato» vs en prealerta; apuntar precios 5 días | Apuntado, sin datos |
| P5 | Protocolos por tipo de préstamo (HTB/ETB/un uso) y regla sobre SSR | Depende del PDF |
| P6 | Cuadro de mandos de exposición al riesgo | Diseño pendiente |
| P7 | Tareas de Jaume de la semana del 7-sep (lista en §0): fills reales de DAS, JSON de la estrategia de estreno, congelar el motor, Telegram propio, VPS con el socio, runbook | Sin empezar |
| P8 | Backend colgado el 7-sep (dos uvicorn); lo lleva Jaume en el chat del genético. Bot de avisos: lo enciende Jaume el 8-sep | Fuera de este chat |
| P9 | Halts largos 2019-2026: HECHO con Databento status (50,61 $). 5 suspensiones T12 en valores en gap en 8 años; ninguna con posición dentro | Cerrado |
