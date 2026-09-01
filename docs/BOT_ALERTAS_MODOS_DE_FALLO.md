# Bot de alertas — modos de fallo y comportamiento ante caídas

> **Por qué existe este documento.** Hoy el bot solo avisa y la orden la mete
> Jaume a mano: si algo falla, lo peor que pasa es perderse una operación. El día
> que se conecte a la API de un bróker, cada uno de estos fallos pasa a poder
> mover dinero real. Este mapa es la base de esa conversación, y hay que
> mantenerlo al día conforme el bot cambie.
>
> Última revisión: 2026-09-01. Estado: el bot NO ejecuta órdenes.

---

## 1. Las piezas y de qué depende cada una

```
    [ Massive ]            [ Bot ]  proceso propio           [ App ]
    WebSocket   ── velas ──►  motor + frames        ── HTTP ──►  backend :8010
    (pendiente                │                                     │
     de clave)                └──── HTTPS directo ────► Telegram    │
                                                                    ▼
                                                          navegador :3000
```

Lo importante de este dibujo: **Telegram NO pasa por la app**. El bot habla
directamente con la API de Telegram. Por eso los avisos al móvil sobreviven a
una caída del backend, y son hoy la vía más fiable de las dos.

| Pieza | Dónde vive | Si se cae, ¿qué se pierde? |
|---|---|---|
| Backend (`:8010`) | Ventana del lanzador | Configuración, publicación de avisos y el interruptor. **No** las alertas de Telegram |
| Frontend (`:3000`) | Ventana del lanzador | Solo la pantalla. Nada funcional |
| Proceso del bot | Ventana propia, sin recarga automática | **Todo.** Es el único que evalúa |
| Telegram | Servicio externo | El aviso al móvil. Queda en la página y en el log |
| Massive | Servicio externo | Las velas. Sin datos no hay nada que evaluar |

---

## 2. Qué pasa en cada caída

| Situación | Comportamiento | ¿Se pierden alertas? |
|---|---|---|
| Cierras la pestaña del navegador | Ninguno: el bot no depende del navegador | No |
| Navegas a otra página / lanzas un backtest | Ninguno | No |
| Se reinicia el backend (guardar código, `--reload`) | El bot sigue evaluando. No puede leer el interruptor ni publicar | **No** desde el arreglo del 1-sep: se reintenta. Telegram no se entera |
| **Botón «Vigilando / Parado»** del cuadro de mandos | Deja de evaluar en < 5 s y **queda EN PAUSA**, sin morir. Vuelve a arrancar solo al encenderlo otra vez | No: es deliberado |
| **Botón de apagado de la app** (esquina inferior derecha) | Mata `:3000`, `:8010` **y el bot** (desde el 1-sep-2026) | No: apagas tú, a propósito |
| Cierras la ventana de consola del bot | **Muere y no vuelve solo** | Sí, todo lo posterior |
| Se corta internet | El WS se reconecta con espera creciente; Telegram falla y queda en el log | Depende de la duración |
| Se cuelga el bot sin morir | La página lo marca en rojo a los 30 s sin latido | Sí, y es el caso más peligroso |

---

## 3. Decisiones de diseño que gobiernan esto

### El bot no se apaga ante la duda

`ClienteBackend.debe_vigilar()` devuelve **tres** valores, no dos:

- `True` → vigilar
- `False` → parar
- `None` → **no se pudo preguntar**

Ante `None` el bot **sigue como estaba**. Un backend reiniciándose no puede
apagar la vigilancia en mitad de la sesión sin que nadie se entere. El precio es
que un backend caído de verdad tampoco lo para: para eso está cerrar su ventana.

### Los avisos no publicados se reintentan

Los eventos llevan un **id estable** — `ticker|estrategia|momento|tipo` — y el
backend hace `INSERT OR REPLACE`. Por eso reenviar la misma tanda es inofensivo
y el bot puede reintentar sin miedo a duplicar.

> **Bug real, encontrado el 2026-09-01.** La primera versión limpiaba la cola de
> pendientes aunque la publicación hubiera fallado: con el backend
> reiniciándose, la alerta desaparecía sin dejar rastro. Se arregló limpiando
> solo si el backend confirmó. Tope: `MAX_PENDIENTES = 200`.

### Nada de la comunicación puede tumbar el bot

Todas las llamadas del cliente van envueltas y devuelven un valor por defecto en
vez de lanzar. Un fallo de red no puede hacerle perder la vela siguiente, que es
justo el minuto que hay que operar.

### El latido distingue «apagado» de «colgado»

El bot manda una señal de vida cada pocos segundos. Sin ella, la página no
podría diferenciar un bot parado a propósito de uno bloqueado. Umbral:
`LATIDO_VIVO_MS = 30 s`.

### Apagar a propósito ≠ que se caiga solo

Son dos cosas distintas y el sistema las trata distinto, porque significan
distinto:

- **Apagas tú** (botón de apagado de la app, o «Parado» en el cuadro de mandos)
  → se para todo, incluido el bot. Es una decisión tuya.
- **Se cae solo** (el backend se reinicia, la red parpadea) → el bot **sigue
  vigilando**. Dejar de avisar en silencio justo cuando algo va mal es
  precisamente lo que no se quiere.

Como el bot no escucha en ningún puerto, `apagar_btt.ps1` no lo alcanzaba con
sus bloques por puerto: se añadió una búsqueda por línea de comandos.

> **Cuidado con ese filtro.** Buscar solo por `*bot_senales*bot.py*` cazaba
> también la consola desde la que se lanzó el bot (`bash.exe`,
> `powershell.exe`), porque su propia línea de comandos contiene ese texto —
> habría matado terminales del usuario. Se exige además que el proceso sea
> `python.exe` o `pythonw.exe`. Verificado el 1-sep: mata los bots y deja el
> backend en pie.

---

## 4. Lo que hoy NO está resuelto

Todo esto es tolerable mientras el bot solo avise. **Ninguno lo será cuando
ejecute órdenes.**

1. **El bot no se reinicia solo.** Si muere, muere. No hay supervisor.
2. **El estado es teórico.** El bot supone que entraste en todas las señales. Si
   un día no entras, seguirá creyéndote dentro y no te avisará de la reentrada.
3. **No hay reconciliación con el bróker.** Nadie compara lo que el bot cree que
   tienes con lo que tienes de verdad.
4. **Si el bot se cuelga sin morir**, la página lo dice pero nadie actúa.
5. **Los frames viven solo en memoria.** Reiniciar el bot a media sesión obliga
   a rehidratar todos los tickers (barato hoy: 26 ms por ticker).

---

## 5. Lo que habrá que añadir antes de automatizar la ejecución

Por orden de importancia:

1. **Reconciliación con el bróker al arrancar y periódicamente.** La posición
   real manda sobre la teórica, siempre. Sin esto, un bot que cree estar fuera
   puede abrir una segunda posición sobre una que ya existe.
2. **Idempotencia de las órdenes.** Igual que los avisos llevan id estable, cada
   orden necesita el suyo para que un reintento tras un fallo de red no compre
   dos veces. La mayoría de brókers lo admiten como *client order id*.
3. **Interruptor de emergencia que llegue al bróker**, no solo al bot: cerrar
   todo y cancelar pendientes desde un único sitio.
4. **Supervisor que reinicie el bot** y que, mientras esté caído, avise por
   Telegram — nunca en silencio.
5. **Confirmación de ejecución.** Una orden enviada no es una orden ejecutada.
   El estado tiene que venir del bróker, no de haber mandado la petición.
6. **Límite diario de pérdida que actúe de verdad.** Existe en el backtest
   (`daily_loss_limit`); en vivo tendría que cortar y cerrar.
7. **Registro de auditoría**: cada decisión, con los datos que la produjeron, para
   poder reconstruir qué pasó un día concreto.

---

## 6. Cosas que ya se decidieron y conviene no volver a discutir

- **El bot lee `MASSIVE_BOT_API_KEY`**, nunca `MASSIVE_API_KEY`. Esa es la de
  producción y un segundo consumidor tumba el screener de los clientes en bucle
  (el propio código lo documenta en `live_screener_service.py`). El modo `--vivo`
  se niega a arrancar mientras no exista la clave propia.
- **El bot no lee `users.duckdb`.** El backend lo tiene abierto y DuckDB no
  admite un segundo escritor; en Windows ni siquiera deja copiarlo. Por eso toda
  la comunicación es HTTP.
- **Proceso aparte, sin recarga automática.** El reloader del backend borraría
  los frames del día a cada fichero guardado.
- **Sin costes.** El bot avisa, no contabiliza: ni locates, ni comisiones, ni
  slippage. Eso sigue viviendo en el backtester.
