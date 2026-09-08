# MEMORIA — Bot TTP (ejecución automática en Trade Evolution por interfaz)

> **Qué es este fichero.** Submemoria APARTE de `MEMORIA_MADRE.md`, de
> `MEMORIA.md` y de `MEMORIA_BOT_EJECUCION.md`. Dedicada SOLO al bot que
> teclea y hace clic en **Trade Evolution** (aplicación de escritorio),
> disparado por las prealertas y alertas del bot de avisos.
> Lo pidió Jaume el 2026-09-06 para no mezclarlo con el bot de DAS.
>
> **No confundir con el bot de DAS** (`MEMORIA_BOT_EJECUCION.md`): aquel va
> por API/socket, es el camino profundo y sigue esperando el PDF del bróker.
> Este es otra cosa: automatización de interfaz, sin API, con lo que ya hay.
>
> Misma regla que la madre: se AÑADE al final, no se reescribe lo anterior;
> la sección «Estado y pendientes» es la única que se sobrescribe.
>
> Estado al abrirlo: **solo plan. Nada instalado, nada programado.**

---

## 0 — 2026-09-06 · Alcance y decisiones de Jaume

### Qué se quiere

Cuando el bot de avisos emite una **prealerta** o una **alerta**, que la orden
se ponga sola en Trade Evolution, sin que Jaume toque el teclado.

Trade Evolution es **aplicación de escritorio** y **NO tiene hotkeys**: cada
orden es una secuencia de clics y tecleo (símbolo, cantidad, precio, botón).

### Decisiones de Jaume (6-sep)

- **Lazo abierto a propósito.** No se lee la posición ni las órdenes vivas
  desde la aplicación. Todo el estado viene por **WebSocket desde nuestra
  propia infraestructura**. El ejecutor solo OBEDECE: escribe y teclea lo que
  la aplicación le diga, con todo ya medido antes.
- **Sin hotkeys** en Trade Evolution: hay que ir por clic + tecleo.
- **Cuenta demo:** cree que existe, pero no bloquea. Se prueba **con 1 acción**
  hasta que funcione.
- **Humanizar el tecleo y el clic.** Se lo recomendaron para **no saturar el
  programa** (no tanto por detección). Jaume quiere hacerles caso aunque sea
  de forma sutil. Ver §1.
- **No se corren varias cosas a la vez** (genético apagado mientras esto
  funcione): los tiempos de interfaz se degradan con la CPU ocupada.
  Ver `btt-un-nucleo-de-veinte` y `btt-maquina-de-jaume`.

### Reparto prealerta / alerta (clave del diseño)

La ventana de prealerta (44-59 s, ver `btt-prealertas-ventana-44`) es lo que
hace viable todo esto:

- **Prealerta = PREPARAR.** Enfocar la ventana, cargar el símbolo, fijar la
  cantidad, dejar el precio puesto. Hay decenas de segundos de holgura: aquí
  el jitter puede ser generoso y humano sin coste ninguno.
- **Alerta = DISPARAR.** Un solo clic en el botón. Presupuesto de latencia
  total ≤ 200-300 ms, jitter acotado dentro de ese presupuesto.

Consecuencia: la parte lenta y frágil sale del camino crítico del dinero.

### Arquitectura propuesta (no confirmada)

```
app / bot de avisos  ── WebSocket ──▶  ejecutor_ttp.py   (proceso APARTE)
                                        ├── planificador   prealerta=preparar, alerta=disparar
                                        ├── humanizador    jitter espacial y temporal
                                        ├── cadencia       token bucket, backoff, presupuesto
                                        ├── driver_ttp     UIA localiza / pyautogui actúa
                                        ├── relectura      Ctrl+A Ctrl+C de los campos propios
                                        └── diario JSONL + captura de pantalla + Telegram
```

Reglas que no se negocian:

- **Un solo actor.** Bucle de un hilo. El teclado y el ratón son un recurso
  con cerrojo: nunca dos secuencias solapadas.
- **Nada de coordenadas absolutas de pantalla.** Se resuelve el rectángulo del
  control en cada acción (UIA, o ancla relativa al área de cliente de la
  ventana) y se hace clic en un punto ALEATORIO dentro de él. Resuelve a la vez
  el «siempre el mismo píxel» y el «la ventana se ha movido».
- **Máquina de estados por evento:** `PREPARADO → DISPARADO → REGISTRADO`.
  Atascado fuera de estado N segundos = aviso y congelar.
- **Modo sombra desde el día uno:** el mismo código con `ENVIAR=False`, hace
  todo menos el clic final.
- **Interruptor de parada:** fichero centinela que bloquea todo + failsafe de
  PyAutoGUI (ratón a la esquina lanza excepción).

Herramientas: **pywinauto (backend UIA)** para LOCALIZAR y leer campos;
**pyautogui** para el movimiento y el tecleo humanizados. Venv propio en
`D:\bot_ejecucion_ttp\`, fuera del repo, como los scripts de `D:\bot_senales\`.
Al venv del backend no se le instala nada (ver `btt-arrancar-backend-venv`).

`inspect.exe` ya está en la máquina, no hace falta instalar el SDK:
`C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\inspect.exe`

## 1 — 2026-09-06 · Humanización y cadencia (propuesta)

Distinguir dos objetivos que se mezclan siempre:

**(a) No saturar la aplicación** — esto es lo que de verdad le recomendaron, y
es lo importante. No se consigue con jitter, se consigue con:

1. **Limitador de cadencia global (token bucket):** máximo N eventos de
   entrada por segundo y mínimo M ms entre dos cualesquiera. Arranque
   propuesto: mín. 80 ms entre eventos, máx. 8/s.
2. **Backoff, nunca reintento inmediato.** Si la ventana no responde en el
   tiempo esperado, esperar progresivamente más (200 ms → 500 → 1 s → parar).
   Las tormentas de reintentos son lo que revienta una app de escritorio frágil.
3. **Nada de sondeo agresivo:** si se consulta la interfaz, a 10-20 Hz como
   mucho y con tope de tiempo.
4. **Presupuesto por sesión:** tope de acciones por minuto y por hora; si se
   pasa, parar y avisar. Protege contra un bucle por bug.

**(b) Que no parezca una máquina** — barato, se hace de paso:

5. **Jitter espacial:** clic en un punto gaussiano dentro del 60 % interior del
   rectángulo del control, nunca el centro exacto.
6. **Movimiento del ratón:** `duration` sacado de una distribución (120-280 ms)
   con `pyautogui.easeOutQuad`, y trayectoria Bézier con 2-3 puntos intermedios
   en vez de línea recta.
7. **Tecleo carácter a carácter** con retardo lognormal (media ~70-90 ms,
   desv. ~30), pausa algo mayor tras el primer carácter y antes del Enter.
   `pyautogui.write(interval=...)` usa intervalo CONSTANTE: no sirve.
8. **Espera por condición + jitter**, no `sleep` fijo: esperar a que el campo
   muestre lo esperado, y añadir 40-150 ms aleatorios antes de actuar.
9. **Desplazar el instante de la preparación** dentro de la ventana de
   prealerta (no siempre al mismo offset). Gratis, y es el único jitter que se
   nota fuera del PC.

**Lo que NO se hace:** simular erratas de tecleo (idea pésima en una
aplicación de órdenes); meter jitter grande en el camino de la alerta; usar
`pyautogui.PAUSE` global como único mecanismo.

### Riesgo asumido del lazo abierto (avisado, decisión de Jaume)

El WebSocket dice qué hay que hacer y a qué precio, pero **no dice si el clic
llegó**. Si un campo no se limpia, la cantidad puede quedar «100500» y no salta
ningún error (patrón de `btt-bugs-que-no-dan-error`). Mitigaciones baratas
propuestas que NO requieren leer posiciones ni órdenes del bróker:

- **Relectura del campo propio antes del clic final:** UIA si se puede; si no,
  `Ctrl+A` + `Ctrl+C` y leer el portapapeles. Funciona en casi cualquier caja
  de edición Win32 y no depende de que la app exponga sus tablas.
- **Guarda de símbolo y precio:** comparar el precio que muestra la ventana con
  el que tiene el bot para ese ticker; si difieren más de X %, abortar. Es la
  protección más barata contra la catástrofe peor (orden en el ticker
  equivocado).
- **Captura de pantalla tras el clic final**, archivada y opcionalmente a
  Telegram. Sin parsear nada: sirve de rastro de auditoría.
- **Modales:** enumerar ventanas antes y después de cada acción. Cualquier
  ventana inesperada = parada dura, nunca «pulso Enter a ver qué pasa».

## 2 — Plan de la semana

| Día | Qué | Criterio de salida |
|---|---|---|
| 1 | Instalar Trade Evolution. `inspect.exe` sobre la ventana de órdenes: ¿salen los campos con nombre y valor? Verde = direccionable / Amarillo = solo la ventana / Rojo = árbol vacío (todo dibujado a mano → solo píxeles y OCR) | Semáforo decidido |
| 2 | `driver_ttp.py`: `enfocar`, `cargar_simbolo`, `fijar_cantidad`, `fijar_precio`, `disparar`. Prueba de repetición ×100 con el mercado cerrado o en demo | Nº de fallos en 100. Ese número ES la respuesta a «¿es fácil?» |
| 3 | Enganchar al WebSocket en **modo sombra**. Un premercado entero produciendo «lo que habría hecho» | Un premercado sin caídas |
| 4-5 | Cadencia, humanizador, relectura, captura, Telegram, parada de emergencia. Primera orden real de **1 acción** | Una orden real correcta |

---

## Estado y pendientes

| # | Pendiente | Estado |
|---|---|---|
| T1 | Instalar Trade Evolution y pasarle `inspect.exe` (semáforo verde/amarillo/rojo) | Sin empezar — bloquea todo lo demás |
| T2 | Confirmar si hay cuenta demo | Jaume cree que sí; no bloquea (se prueba con 1 acción) |
| T3 | Definir el contrato del WebSocket: qué campos exactos manda la app en prealerta y en alerta (ticker, lado, acciones, precio, id idempotente) | Sin empezar |
| T4 | Condiciones del bróker sobre operar automáticamente | Sin preguntar |
| T5 | Valores de arranque de la cadencia (80 ms / 8 por s) y del presupuesto por sesión | Propuestos, sin validar contra la app real |
| T6 | Decidir si se acepta la relectura por portapapeles antes del clic final | Propuesto, pendiente de Jaume |
