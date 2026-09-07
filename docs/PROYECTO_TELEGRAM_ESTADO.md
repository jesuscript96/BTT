# `/estado TICKER` — preguntarle al bot cómo va una posición

> **Estado: PROYECTO, sin implementar.** Lo pidió Jaume el 2026-09-02 y quiere
> darle el visto bueno antes de que se escriba nada. Aquí está lo que hay ya
> hecho, lo que falta, las aristas y las decisiones.

## Qué se pide

> «Distancia en este momento en % del stop loss, de la entrada y del take
> profit; si le queda alguna orden pendiente (ej. pirámide para añadir) o cosas
> así.» — y **lo que lleva ganado o perdido**.

---

## 1. Lo que YA está y no hay que rehacer

El comando `/evf` de anoche dejó montado **todo el mecanismo de escuchar**:

- `bot_alerts_telegram.recibir()` — long polling con `getUpdates`, filtrando por
  el `chat_id` configurado.
- El despachador de `bot_alerts_comandos.responder()`, que no lanza ni con
  basura (hay un test que le mete de todo).
- La tarea en el bucle del bot, aislada en su propio `try`, llamando en un hilo
  para no bloquear el procesado de velas, y descartando el backlog al arrancar.

**Añadir un comando nuevo es escribir su función y una línea en el despachador.**

## 2. De dónde sale cada dato

| dato | fuente | ¿existe hoy? |
|---|---|---|
| precio actual | `MercadoEnVivo.precio_de()` | ✅ |
| stop actual | `nivel_stop()` sobre el frame en vivo | ✅ |
| entradas que quedan | `MotorAlertas._quedan_entradas()` | ✅ |
| ¿hay posición? | `RunnerAlertas.tiene_posicion()` | ✅ |
| precio y tamaño de entrada | los avisos publicados (`bot_alert_eventos`) | ⚠️ ver §3.1 |
| take profit | la definición de la estrategia | ⚠️ ver §3.2 |

`nivel_stop()` calcula **con las mismas funciones del simulador**, así que el
stop que conteste el bot es el que usaría el backtest. Nada nuevo que validar.

## 3. Las aristas

### 3.1 El bot no guarda el precio de entrada

`_EstadoPar` solo recuerda **índices de vela avisados** (`entradas_avisadas`,
`salidas_avisadas`, `piramides_avisadas`). El precio y el tamaño viajaron en el
`Evento` y se publicaron, pero el motor no los conserva.

Dos salidas:

- **(a) Preguntarle al backend** por los eventos del día de ese ticker
  (`/api/bot-alerts/eventos` ya existe). Sin tocar el motor. Coste: una llamada
  HTTP por comando, y depende de que el backend responda.
- **(b) Guardar el último evento de entrada en `_EstadoPar`.** Un campo más,
  puramente aditivo. Más rápido y sin dependencias, pero toca el motor.

> **Recomendación: (a).** El motor decide órdenes reales; cuanto menos se toque
> para una comodidad, mejor. Un comando de consulta puede permitirse una llamada
> HTTP.

### 3.2 El «take profit» de 1B no es una distancia, es una hora

`take_profit: {type: "Hour", value: "09:00"}`. No hay un precio objetivo del que
medir un %. La respuesta honesta para 1B es **cuánto queda de ventana**, no una
distancia:

```
TP: cierre por hora a las 15:00 (quedan 47 min)
```

Con un TP de precio (`Percent`, `Fixed Price`) sí saldría el %. El comando tiene
que **mirar el tipo** y contestar una cosa u otra; enseñar «TP: —» sería peor
que no enseñar nada.

### 3.3 Sin posición abierta, ¿qué contesta?

Lo útil no es «no hay nada»: es **por qué**. El bot sabe si el ticker está en el
radar, si cumple el universo, y cuántas entradas le quedan:

```
GELS · sin posición
  en el radar desde 13:11 (PMH Gap 57,1 %)
  quedan 2 entradas de 3
```

### 3.4 La que Jaume ya descartó

El bot no conoce la posición REAL del bróker, solo la que la simulación cree.
**Decidido el 2026-09-04: no se aborda ahora** — «esto es un bot de alarmas, ya
nos preocuparemos cuando hagamos la integración con el bróker, en otra
pantalla». Queda anotado, no resuelto.

## 4. Cómo quedaría

```
/estado MIMI

MIMI · CORTO · 1.213 acc
entrada media   0,8315 $
precio ahora    0,9110 $        −9,56 %  ·  −96,42 $
stop            1,1990 $        a 31,6 % (queda margen)
TP              cierre por hora a las 15:00 (47 min)
pirámides       1 disparada, 0 pendientes
reentradas      quedan 2 de 3
```

**El P&L es el de la simulación**, no el de tu cuenta: si entraste a otro precio
o con otro tamaño, no coincide. Va con una marca visible para que no se
confunda.

## 5. Decisiones para Jaume

1. **¿El precio de entrada se pide al backend (a) o se guarda en el motor (b)?**
   Recomiendo (a): no tocar el motor por una consulta.
2. **¿Con una sola estrategia vigilando basta una respuesta, o hay que separar
   por estrategia?** Hoy solo hay 1B activa, pero el mismo ticker puede estar
   vigilado por varias y cada una tendría su posición y su stop.
3. **¿El P&L en dólares, en %, o los dos?** El de dólares depende del tamaño,
   que es justo lo que puede no coincidir con tu cuenta.

Con esas tres, es un rato de trabajo: el mecanismo de escuchar ya está.
