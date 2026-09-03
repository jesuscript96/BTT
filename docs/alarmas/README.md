# Alarmas del Screener

> **Documento único.** Qué se ha construido, qué puede configurar el usuario,
> cómo validarlo, qué falta para producción y el plan de las fases siguientes.
>
> **Estado:** F1 completa en `develop`. Código probado en unidad. **Nada
> desplegado, nada ejercitado contra el mercado en vivo.**

## Índice

1. [Qué es y qué no es](#1) · 2. [Qué puede configurar el usuario](#2) ·
3. [Cómo funciona por dentro](#3) · 4. [Estado real](#4) ·
5. [Cómo validarlo](#5) · 6. [Qué falta para producción](#6) ·
7. [Trampas](#7) · 8. [Plan de fases](#8) · 9. [Decisiones abiertas](#9)

---

<a id="1"></a>
## 1 · Qué es y qué no es

Un sistema que vigila el mercado en vivo y avisa cuando se cumplen unas
condiciones que **configura el usuario**. Los avisos llegan al móvil por Telegram
y al navegador si está abierto.

**No manda órdenes, no sabe si hay acciones prestables, no sigue posiciones y no
valida si una regla gana dinero.** Solo dice «esto que pediste está pasando».

**Es independiente del backtester, por decisión de diseño.** No importa nada de
`app/backtester/`, `strategy_engine.py` ni `indicators.py`; tiene su propia
aritmética de VWAP, EMA y extremos de sesión. Consecuencia asumida: un resultado
de alarmas y uno de backtest **no son comparables** y no deben presentarse como
si lo fueran. Si te ves importando del backtester, para.

**Amplía las alarmas sonoras que ya existían** (`Screener.tsx`, commit
`a445b34`), no las sustituye. Aquellas viven en el navegador, solo ven la tabla
abierta y no saben de barras. Su modelo (`{field, op:"gte", value}`) es un caso
degenerado del nuevo y se acepta sin traducción — ver `ALIASES` en `fields.py`.

---

<a id="2"></a>
## 2 · Qué puede configurar el usuario

### El modelo de regla

Una alarma es una lista de condiciones combinadas con **AND**. Cada condición es:

```
campo  ·  operador  ·  (número o cualquier otro campo)
```

Operadores: `>` `>=` `<` `<=` `==`, más `cruza hacia arriba` y `cruza hacia
abajo` (estos dos solo sobre campos de barra, donde «anterior» significa la barra
previa y es reproducible).

Además, una alarma puede llevar:

| Pieza | Para qué |
|---|---|
| **Universo** | Qué tickers vigilar hoy. Es **pegajoso**: una vez que un ticker entra, se queda el resto de la sesión aunque la condición deje de cumplirse. |
| **Watchlist** | Vigilar tickers concretos y nada más. La vía rápida de «avísame de este». |
| **Ventana horaria** | Desde–hasta en hora de Nueva York. |
| **Enfriamiento** | Máximo de avisos por ticker y día, y minutos mínimos entre avisos. |
| **Stop y tamaño** | Referencia del stop + offset %, y riesgo $ **o** nominal $. Sale calculado en el mensaje, con locates si se configura el coste del paquete. |
| **Canales** | Telegram, navegador, sonido. |

### El modo de disparo se deduce, no se elige

- Todos los campos **instantáneos** → se evalúa cada segundo contra el estado del
  screener.
- Alguno **de barra** → se evalúa al cerrar cada minuto, sobre la serie anclada a
  las 04:00 ET.

La ficha de la alarma se lo dice al usuario; él no decide.

### El vocabulario: 34 campos

**Instantáneos**

| Campo | Qué es | Unidad |
|---|---|---|
| `price` | Último precio negociado | $ |
| `change_pct` | Variación sobre el cierre de ayer | % |
| `volume` | Volumen acumulado de la sesión | acciones |
| `pmh_gap_pct` | Máximo de premarket contra el cierre de ayer | % |
| `pre_volume` | Volumen acumulado desde las 4:00 ET | acciones |
| `pre_high` | Máximo de premarket | $ |
| `gap_pct` | Apertura RTH contra el cierre de ayer | % |
| `prev_close` | Cierre de ayer | $ |
| `day_high` · `day_low` | Extremos del día | $ |
| `rvol` | Volumen del día contra la media de 20 sesiones | x |

**De barra** (fuerzan evaluación al cierre del minuto)

| Campo | Qué es | Unidad |
|---|---|---|
| `close` `open` `high` `low` | La barra de 1 minuto que acaba de cerrar | $ |
| `bar_volume` | Volumen de esa barra | acciones |
| `dollar_volume` | Cierre × volumen de esa barra | $ |
| `prev_bar_close` `prev_bar_high` `prev_bar_low` | La barra anterior | $ |
| `vwap` | Anclado a las 4:00 ET, incluye premarket | $ |
| `dist_vwap_pct` | Separación respecto al VWAP, con signo | % |
| `pm_high` · `pm_low` | Extremos de premarket **corridos** (hasta este minuto) | $ |
| `previous_max` · `previous_min` | Extremos corridos de la sesión | $ |
| `mins_since_high` | Minutos sin hacer un máximo nuevo | min |
| `ema9` `ema15` `ema20` `ema50` `ema200` | Medias exponenciales | $ |
| `sma20` `sma50` | Medias simples | $ |

### Ejemplos del abanico

Todos se configuran desde la misma interfaz. Son **sintéticos**, para entender el
rango: no son la configuración de nadie.

**Umbral simple** — lo que hacían los avisos sonoros, ahora en servidor y al móvil
```
change_pct >= 30
```

**Ruptura del máximo de premarket**
```
close cruza hacia arriba pm_high      ·      dollar_volume > 250000
```

**Recuperación del VWAP**
```
close cruza hacia arriba vwap      ·      rvol >= 3
```

**Pico de volumen relativo en un rango de precio**
```
rvol >= 5      ·      price >= 1      ·      price <= 20
```

**Consolidación tras el impulso**
```
mins_since_high >= 20   ·   close < ema20   ·   dist_vwap_pct <= -5
```

**Nivel manual sobre un ticker concreto** (watchlist: `XYZ`)
```
price >= 3.85
```

**Gapper que se gira, con filtro de universo y ventana**
```
universo:    pmh_gap_pct >= 40   ·   pre_volume >= 1000000
condiciones: close < prev_bar_low   ·   close > vwap   ·   dollar_volume > 200000
ventana:     04:00 → 09:00
stop:        previous_max, offset +8%
```

### Lo que el modelo NO puede expresar

- **No hay OR ni grupos anidados.** Es una decisión: el constructor del
  backtester ya tiene ese árbol y cuesta leerlo. Aquí una alarma se entiende de
  un vistazo. Para un OR, dos alarmas.
- **No hay aritmética entre campos.** No se puede escribir `close > vwap * 1.02`;
  para eso está `dist_vwap_pct > 2`. Si aparecen más casos, el camino es añadir
  campos derivados, no un intérprete de expresiones.
- **No hay lookback más allá de una barra**, salvo los extremos corridos y
  `mins_since_high`.
- **No hay multi-timeframe.** Todo es 1 minuto o instantáneo.
- **No hay patrones de velas.**

---

<a id="3"></a>
## 3 · Cómo funciona por dentro

```
Massive WS  ──A.*──►  live_screener_service          (UNA sola conexión)
                          │ add_aggregate_listener()
                          ▼
                    alarms/engine.py
                      ├─ bars.py        barras 1m ancladas a las 04:00 ET
                      ├─ fields.py      vocabulario y alias
                      ├─ evaluator.py   {left, op, right} con AND
                      ├─ store.py       BD, TODO filtrado por dueño
                      ├─ telegram.py    bot: vinculación y reparto
                      └─ replay.py      reproducir un día histórico
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
     WS /api/alarms/live        Telegram
     (toast + beep)             (móvil)
```

| Fichero | Qué hace |
|---|---|
| `backend/app/services/alarms/fields.py` | Los 34 campos, operadores y alias del modelo antiguo |
| `backend/app/services/alarms/bars.py` | Barras 1m y derivados incrementales |
| `backend/app/services/alarms/evaluator.py` | Evaluación y validación de reglas |
| `backend/app/services/alarms/store.py` | Persistencia; todas las lecturas con `WHERE user_id = ?` |
| `backend/app/services/alarms/telegram.py` | Bot API + long-polling de `/start` |
| `backend/app/services/alarms/engine.py` | Universo, ritmos de evaluación, enfriamiento, disparo |
| `backend/app/services/alarms/replay.py` | Reproducir un día histórico por el mismo camino |
| `backend/app/routers/alarms.py` | CRUD, catálogo, estado, Telegram, replay, WS |
| `backend/tests/test_alarms.py` | 21 tests |
| `frontend/src/components/screener/AlarmsPanel.tsx` | Configuración, dentro del modal de Alarmas |
| `frontend/src/lib/api_alarms.ts` | Cliente |

Tocado fuera del módulo, lo mínimo:
- `live_screener_service.py` — 3 enganches (`add_aggregate_listener`,
  `snapshot_metrics`, `metrics_for`). Los listeners se invocan **fuera del lock**.
- `main.py` — import, router, arranque y parada.
- `Screener.tsx` — monta el panel y se suscribe al WS de alarmas.

### Variables de entorno

| Variable | Para qué |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token de @BotFather. Sin él funciona, pero solo avisa en el navegador. |
| `ALARMS_ENABLED` | `0` apaga el motor sin desplegar. Encendido por defecto. |
| `MASSIVE_API_KEY` | Ya existente. La usan el backfill de barras y la reproducción. |

El token **nunca va al repo**: `backend/.env` en local, variables de Coolify en
servidor. Rotarlo es cambiar el valor y reiniciar.

---

<a id="4"></a>
## 4 · Estado real

### Verificado

| Qué | Cómo |
|---|---|
| 21 tests | `cd backend && pytest tests/test_alarms.py -q` |
| Tipos del frontend | `cd frontend && npx tsc --noEmit` |
| Build de producción | `cd frontend && npx next build` ✓ |
| Motor contra datos reales | Reproducción de una alarma de gapper sobre un día con gap y otro sin él |
| Token del bot | `getMe` responde |

### NO verificado — lo primero que te toca

| Qué | Por qué no se hizo |
|---|---|
| **El panel nunca se ha renderizado en un navegador** | Compila y tipa, pero nadie lo ha visto pintar |
| **Camino en vivo completo** (WS → barra → evaluación → Telegram) | Massive admite una conexión por API key y producción la ocupa |
| **La vinculación de Telegram nunca se ha completado** | Nadie ha pulsado Start |
| **Nada desplegado** | Falta la variable de entorno |

> El riesgo está concentrado en `AlarmsPanel.tsx`: ~510 líneas de React que
> compilan pero que nadie ha visto funcionar. Empieza por ahí.

---

<a id="5"></a>
## 5 · Cómo validarlo

### El feed retrasado NO sirve como segunda conexión — medido

`wss://delayed.massive.com/stocks` funciona: acepta la clave, manda datos y el
retraso es exactamente 15,0 minutos. Pero **el cupo de conexiones es de la CUENTA,
no del host**. Probado el 2026-09-03 abriendo dos conexiones al feed retrasado:

```
status: max_connections → "Maximum number of websocket connections exceeded.
        You have reached the connection limit for your account."
cierre: 1008 (policy violation)
```

O sea: apuntar QA al feed retrasado **sigue peleando con producción**.

Comprobado también el caso mixto (una al feed normal + una al retrasado a la vez,
misma clave): la conexión normal cae con `max_connections` / 1008 y la retrasada
sobrevive. El cupo cuenta conexiones **de la cuenta**, dé igual el host — normal
en prod y retrasado en dev son dos conexiones y una muere.

Y peor — cuál de las dos cae no es determinista: en una prueba se expulsó la primera
conexión y en otra la segunda. QA podría tirar el screener de producción en
cualquier momento.

**Conclusión: no uses el WebSocket fuera de producción.** Ni el de tiempo real ni
el retrasado. Para desarrollo, `LIVE_SCREENER_ENABLED=0` + reproducción.

*(El motor sí quedó preparado para datos retrasados —el barrido de barras usa el
reloj del feed y no el de pared— por si algún día se contrata un cupo mayor.)*

### ¿Avisa en el momento exacto? — el trazador

`replay` te dice a qué minuto y precio salta. Para verificar que salta en el
minuto CORRECTO (ni tarde ni pronto), `scripts/trace_alarm.py` imprime la condición
minuto a minuto sobre un día real, con los valores que ve la alarma marcados donde
dispara. Cotéjalo contra un gráfico que ya conozcas: el minuto justo antes no debe
cumplir, el del evento sí.

```bash
cd backend
python -m scripts.trace_alarm LGHL 2026-07-27 "close crosses_above vwap" --from 04:05 --to 04:35
python -m scripts.trace_alarm XYZ  2026-07-27 "close < prev_bar_low;close > vwap"
```

Condiciones separadas por `;` (AND). El valor es un número o el nombre de otro
campo. Corre por el MISMO motor que en vivo, así que lo que ves aquí es lo que
haría la alarma.

Lo único que el trazador NO cubre es el retardo de 1-3 s con que el aviso llega
DESPUÉS del cierre de la barra en vivo. Eso no es de timing de la señal (la señal
es exacta), es el hueco de ejecución, y se mide en shadow mode (F3).

### Reproducir un día real, sin WebSocket ninguno

Massive admite **una conexión WS por API key**. Si QA y producción levantan las
dos el screener con la misma clave, se expulsan en bucle (cierre 1008) y ninguno
sirve — lo que dejaría QA sin forma de probar.

Para eso está la reproducción: pide las barras de un día por REST y las mete por
**el mismo camino** que el stream (`SessionBars` → `snapshot()` → `evaluate()`).
Mismo anclaje a las 04:00, mismo VWAP acumulado, mismo universo pegajoso, mismo
enfriamiento. Funciona a cualquier hora y en fin de semana.

En la interfaz: editor de una alarma guardada → **Probar con un día pasado**.
Por API:

```bash
curl -X POST https://TU-BACKEND/api/alarms/<ALARM_ID>/replay \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"ticker":"XYZ","date":"2026-07-27","deliver":true}'
```

`deliver: true` manda además la primera señal a tu Telegram, marcada como
reproducción. **No es un backtest:** no simula ejecuciones, no aplica slippage ni
comisiones y no calcula rendimiento.

### Checklist de humo

- [ ] `GET /api/alarms/status` responde con `running: true`
- [ ] El modal de Alarmas abre y **el panel pinta** (lo que nadie ha visto)
- [ ] Conectar Telegram → Start → llega «✅ Telegram conectado»
- [ ] Botón *Probar* → llega el mensaje de prueba
- [ ] Crear una alarma, guardarla, apagarla y encenderla; recargar y comprobar
      que persiste
- [ ] Reproducir un día que **debe** disparar y otro que **no**. Una alarma que
      dispara siempre no está probada, está rota. Para conseguir un par de
      fechas, coge un gapper de la pestaña de premarket y usa el día del gap
      contra el siguiente
- [ ] **Redesplegar y comprobar que las alarmas siguen ahí** (§7, persistencia)
- [ ] En producción con mercado abierto: alarma con un ticker en watchlist y
      `price > 0.01` → debe avisar en un par de segundos

### Diagnóstico

`GET /api/alarms/status` devuelve `screener_ws_connected`. Es la respuesta a
«¿por qué no salta nada?»: sin stream no hay barras y las alarmas de modo barra
no se evalúan nunca. En `false`, o el entorno no tiene clave de Massive, o otro
backend con la misma clave está expulsando a este.

Logs por prefijo: `[ALARMS]` el motor, `[TG]` Telegram, `[LIVE]` el screener. Un
`[LIVE] WS disconnected … reconnecting` en bucle es el choque de claves.

---

<a id="6"></a>
## 6 · Qué falta para producción

1. **`TELEGRAM_BOT_TOKEN` en las variables del backend** en Coolify, **no en
   Vercel** (el frontend no lo necesita y ahí acabaría expuesto al navegador).
   Reinicia el servicio: el poller arranca en el lifespan.
2. **Desplegar el backend desde `develop`.** Comprueba antes a qué backend apunta
   el `NEXT_PUBLIC_API_URL` de la QA: si apunta al de producción (que corre
   `main`), `/api/alarms/*` dará 404 y no estarás probando nada.
3. **En QA, no pongas `MASSIVE_API_KEY`** si producción ya la usa. Para probar el
   motor no hace falta: usa la reproducción.
4. Pasar la checklist de humo de §5.

### Deuda conocida, no bloqueante

- `AlarmsPanel.tsx` dispara `react-hooks/set-state-in-effect` en eslint. Es un
  falso positivo (el `setState` ocurre tras un `await`) y **Next 16 ya no corre
  eslint en el build**, así que no bloquea. No lo "arregles" a ciegas.
- Sin panel de historial: en F1 el historial es el chat de Telegram. La API
  `GET /api/alarms/events/list` ya devuelve los datos.

### Bug preexistente, ajeno a esta fase

En los avisos rápidos client-side (`Screener.tsx`, en producción desde
`a445b34`): el desplegable ofrece «PMH Gap %», pero el backend en vivo nunca
emite ese campo — manda `pre_pct`. Como `matchesRules` exige que **todas** las
reglas casen, añadir una regla de PMH Gap **desactiva la alarma entera en
silencio**. Fix de una línea, pero cambia el comportamiento de una feature viva:
reglas que hoy no suenan empezarían a sonar. Consúltalo con Jesús antes.

---

<a id="7"></a>
## 7 · Trampas: no deshacer sin leer

**Una sola conexión a Massive.** El motor se cuelga del stream del screener vía
`add_aggregate_listener()`. Una segunda conexión con la misma API key provoca el
kick-loop 1008 que ya aparece en los logs.

**Serie anclada a las 04:00.** El VWAP es acumulado desde la primera barra del
frame. Por eso `_backfill()` rellena el día por REST antes de vigilar un ticker
nuevo: sin él, uno que entra en el universo a las 06:12 tendría un VWAP que no es
el de nadie. Resuelve a la vez el arranque en frío tras un despliegue a media
sesión.

**`None` nunca es 0.** Un campo sin valor hace que la condición no se cumpla. Con
cero, `volumen > X` sería siempre falso pero `precio < X` siempre cierto.

**El enfriamiento es obligatorio.** Muchas condiciones de reversión se cumplen en
barras consecutivas. Sin tope, el sistema es spam y se apaga el primer día. El
contador se lee de la tabla, no de RAM, para que un reinicio no reabra la puerta.

**El contexto instantáneo se calcula una vez por tick**, no una por alarma. Con
~8.000 tickers y varias alarmas activas, rearmarlo dentro de los bucles daba
decenas de miles de dicts por segundo y el tick de 1 s no cerraba.

**Persistencia en GCS.** `users.duckdb` se descarga al arrancar y se sube al
apagar **solo si algo la marcó como sucia**. Toda escritura nueva debe llamar a
`_mark_dirty()`, y el contenido que crea el usuario además se sube en background
en el acto (`_sync_user_db`). Ya costó un bug: sin esto las alarmas desaparecían
en el primer redeploy, en silencio. Si añades tablas, replica el patrón.

**El chat_id viaja con su dueño.** `iter_active_alarms()` lo trae en el MISMO
JOIN que el `user_id`. Nunca lo resuelvas después contra un diccionario
compartido: por ahí se cuela el aviso de un usuario al teléfono de otro. Cubierto
por `test_el_chat_id_viaja_con_su_dueno`.

**Aislamiento por usuario.** Ninguna fila nace sin dueño (centinela
`__local_dev__` en desarrollo, nunca NULL), ni un SELECT sin `WHERE user_id = ?`,
y ningún respaldo a tabla compartida. Es la cicatriz del commit `b2ac1eb`.

**Las configuraciones de los usuarios son privadas.** Las reglas de una alarma
son la estrategia de quien la escribe. No las repliques en documentación, tests,
mensajes de commit ni ejemplos: los de este documento son sintéticos a propósito.

---

<a id="8"></a>
## 8 · Plan de fases

Cada fase llega a producción y se prueba sola. Ninguna depende de la siguiente.

### F1 · La alarma existe y avisa ✅ (esto)

Configurar, encender y apagar alarmas; avisos por Telegram y navegador; universo,
ventana, enfriamiento, filtro de splits, stop y tamaño en el mensaje; registro de
señales en BD y reproducción histórica.

### F2 · El historial se ve

Panel de señales en el Screener: qué disparó, cuándo, a qué precio y por qué.

- Panel de historial (`GET /api/alarms/events/list` ya existe).
- Eventos LULD (halts): marcar el ticker como no operable.
- Aviso visible cuando el motor arranca a media sesión con premarket incompleto.

*Abierto:* si salta la condición con el ticker en halt, ¿silenciamos o avisamos
marcado?

### F3 · Marcar y medir

**La fase que decide si existe F5.**

- Botones «La tomé» / «Paso» en el mensaje de Telegram y en el panel.
- Precio provisional (el del aviso) vs confirmado (el que teclea el usuario).
- Rendimiento a **doble columna**: todas las señales frente a las tomadas.

> Las dos columnas contestan preguntas distintas y hacen falta las dos. La de
> todas las señales **debe incluirlas todas** o deja de ser una medición: si solo
> mides las que tomaste, la muestra está sesgada por tu propia selección. La
> resta de ambas dice si la discreción del trader suma o resta.

*Abierto:* si nunca confirmas que entraste y el precio llega al stop teórico,
¿avisamos igual?

### F4 · Alarmas de precio manual

Armar a mano «avísame si XYZ toca tal precio». Técnicamente ya cabe (`price >= X`
+ watchlist); falta el atajo de un clic desde la ficha del ticker.

### F5 · Tracker de posición

Máquina de estados: confirmas la entrada y el sistema vigila stop, hora de
salida, ventana de adición y reentradas. **Solo si F3 dice que merece la pena.**
Si el hueco entre el cierre teórico de la barra y el precio real de entrada se
come el edge, esta fase no se construye.

### F6 · Journal

El estado de cuenta real (P&L, win rate, expectancy sobre operaciones reales) es
el [Journal](../manual-prd/PRD_EJEMPLO_JOURNAL.md), no este módulo. Las alarmas
se enchufan a él pre-rellenando una entrada al marcar una señal como tomada.

---

<a id="9"></a>
## 9 · Decisiones abiertas

De producto, no del developer:

| | Estado |
|---|---|
| **Audiencia.** Hoy cae detrás de `screener.access` (Admin) | Sin decidir |
| **Vigilancia del servidor** a las 04:00 ET / 10:00 España. Un sistema de avisos que falla el día que más se mueve el mercado no vale nada | **Sin resolver** |
| Presentación del aviso de adición a posición (F5) | Sin decidir |
| Qué hacer con un aviso sobre un ticker halted (F2) | Sin decidir |

### Riesgos vivos

| Riesgo | Estado |
|---|---|
| Splits fingiendo ser runners (25,3% de los gaps de premarket ≥100% de 2026 son días de split) | Cubierto en F1 |
| Halts (LULD) | F2 |
| El aviso llega tras el cierre de la barra | Decisión de diseño; se mide en F3 |
| Backend caído a las 04:00 ET | **Sin resolver** |
| Arranque en frío a media sesión | Cubierto por el backfill de F1 |
