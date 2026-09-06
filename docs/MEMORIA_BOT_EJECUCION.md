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

---

## Estado y pendientes

| # | Pendiente | Estado |
|---|---|---|
| P1 | Conseguir el PDF del API de DAS y activar el API en Sage | Esperando al bróker |
| P2 | Decidir stop limitado vs mercado y la guarda «X % en segundos» | Abierto, recordárselo |
| P3 | Estudio de picos de cola: Jaume YA LO TIENE; pedírselo con cifras al arrancar | Pendiente de recibirlo |
| P4 | Dinámica de locates: pronto y barato vs en prealerta | Apuntado, se verá |
| P5 | Protocolos por tipo de préstamo y regla sobre SSR | Depende del PDF |
| P6 | Cuadro de mandos de exposición al riesgo | Diseño pendiente |
