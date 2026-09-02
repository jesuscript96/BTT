# Traspaso — Alarmas del Screener, fase 1

> **Para:** el developer que continúa.
> **Rama:** `develop` (7 commits, `10ff248` → `1b9813e`).
> **Estado:** código completo y probado en unidad. **Nada desplegado, nada
> ejercitado contra el mercado en vivo.**

Lee antes [PLAN_FASES.md](PLAN_FASES.md) (qué es esto y qué NO es) y
[FASE_1.md](FASE_1.md) (arquitectura y decisiones).

---

## 1 · Dónde estamos

Fase 1 de 6. Lo que entrega: **configurar alarmas en el Screener, encenderlas y
apagarlas, y recibirlas por Telegram y en el navegador.** Sin seguimiento de
posición, sin panel de historial y sin cálculo de rendimiento — eso es F2, F3 y
F5.

### Verificado

| Qué | Cómo |
|---|---|
| 21 tests | `cd backend && pytest tests/test_alarms.py -q` |
| Tipos del frontend | `cd frontend && npx tsc --noEmit` |
| Build de producción | `cd frontend && npx next build` ✓ |
| Motor contra datos reales | Reproducción de la 1B: `LGHL 2026-07-27` → 3 señales; `2026-07-28` → 0 |
| Token del bot | `getMe` responde `@edgiethetradingbot` |

### NO verificado — esto es lo que te toca

| Qué | Por qué no se hizo |
|---|---|
| **Camino en vivo completo** (WS → barra → evaluación → Telegram) | Massive admite una conexión por API key y producción la ocupa |
| **El panel nunca se ha renderizado en un navegador** | Compila y tipa, pero nadie lo ha visto funcionando |
| **La vinculación de Telegram nunca se ha completado** | Nadie ha pulsado Start todavía |
| **Nada desplegado** | Falta la variable de entorno |

> El riesgo concentrado está en el panel: `AlarmsPanel.tsx` son 450 líneas de
> React que compilan pero que nadie ha visto pintar. Espera encontrar cosas ahí.

---

## 2 · Qué falta para producción

### Bloqueante

1. **`TELEGRAM_BOT_TOKEN` en las variables del backend** (Coolify), no en Vercel.
   Sin él el módulo arranca pero solo avisa en el navegador. Jesús tiene el valor.
   Reinicia el servicio: el poller arranca en el lifespan y no relee en caliente.

2. **Desplegar el backend desde `develop`.** Comprueba a qué backend apunta el
   `NEXT_PUBLIC_API_URL` de la QA: si apunta al de producción (que corre `main`),
   `/api/alarms/*` devolverá 404 y no estarás probando nada.

3. **En QA, NO pongas `MASSIVE_API_KEY`** si producción ya la usa. Se expulsan en
   bucle (cierre 1008) y tumbas el screener de producción mientras pruebas. Para
   probar el motor no hace falta: usa la reproducción (§5).

### Humo antes de dar por buena la fase

```bash
curl -s https://TU-BACKEND/api/alarms/status
# → {"running": true, "screener_ws_connected": ..., "telegram_configured": true, ...}
```

- [ ] `/api/alarms/status` responde con `running: true`
- [ ] El modal de Alarmas del Screener abre y **el panel pinta** (esto es lo que
      nadie ha visto)
- [ ] Conectar Telegram → Start → llega «✅ Telegram conectado»
- [ ] Botón *Probar* → llega el mensaje de prueba
- [ ] Crear la 1B, guardarla, *Reproducir* con `LGHL` / `2026-07-27` → **3 señales**
- [ ] Reproducir `LGHL` / `2026-07-28` → **0 señales** (una alarma que dispara
      siempre no está probada, está rota)
- [ ] Apagar y encender una alarma; recargar y comprobar que persiste
- [ ] **Redesplegar y comprobar que la alarma SIGUE ahí** (ver §6, es el bug que
      más caro sale)
- [ ] Ya en producción y con mercado abierto: alarma con un ticker en watchlist y
      `Precio > 0.01` → debe avisar en un par de segundos

### Deuda conocida, no bloqueante

- `AlarmsPanel.tsx:145` dispara `react-hooks/set-state-in-effect` en eslint. Es
  un falso positivo (el `setState` ocurre tras un `await`), y **Next 16 ya no
  corre eslint en el build**, así que no bloquea. Déjalo o reestructura, pero no
  lo "arregles" a ciegas.
- Sin panel de historial: en F1 el historial es el chat de Telegram. La API
  `GET /api/alarms/events/list` ya devuelve los datos.

---

## 3 · Qué podrá hacer el usuario

En cuanto esto esté en producción, un usuario del Screener (hoy gateado a Admin
vía `screener.access`) puede:

- **Configurar alarmas** desde el modal de Alarmas, con ~34 campos: precio,
  volumen, dollar volume, VWAP y distancia al VWAP, EMA/SMA, máximo y mínimo de
  premarket, gap del máximo de premarket, mínimo de la barra anterior, minutos
  desde el último máximo, RVol…
- **Combinar condiciones** con la gramática `campo · operador · (número u otro
  campo)`. Cuatro condiciones bastan para la 1B entera.
- **Filtrar el universo** (qué tickers vigilar hoy) y fijar **ventana horaria**.
- **Vigilar tickers concretos** con una watchlist.
- **Encender y apagar** cada alarma con un clic.
- **Recibir el aviso en el móvil por Telegram**, con el motivo desglosado
  («por qué saltó»), el nivel del stop, el número de acciones y el coste de
  locates.
- **Recibir toast y beep** en el navegador si lo tiene abierto.
- **Probar una alarma contra un día pasado** antes de confiar en ella.
- Y **los avisos rápidos de siempre siguen funcionando igual** — esto los amplía,
  no los sustituye.

Lo que **no** podrá hacer: marcar señales como tomadas, ver un historial, saber
su rendimiento, ni que el sistema le vigile un stop. Eso es F2–F5.

---

## 4 · Mapa del código

```
backend/app/services/alarms/
  fields.py      vocabulario + alias del modelo client-side antiguo
  bars.py        barras 1m ancladas a las 04:00 ET, derivados incrementales
  evaluator.py   {left, op, right} con AND; validación
  store.py       persistencia — TODO filtrado por dueño
  telegram.py    Bot API + long-polling de /start
  engine.py      universo, ritmos de evaluación, enfriamiento, disparo
  replay.py      reproducir un día histórico por el mismo camino
backend/app/routers/alarms.py          CRUD, catálogo, estado, Telegram, replay, WS
backend/tests/test_alarms.py           21 tests
frontend/src/components/screener/AlarmsPanel.tsx
frontend/src/lib/api_alarms.ts
```

Tocado fuera del módulo, mínimo y a propósito:
- `live_screener_service.py` — 3 puntos de enganche (`add_aggregate_listener`,
  `snapshot_metrics`, `metrics_for`). Los listeners se invocan **fuera del lock**.
- `main.py` — import, router, arranque y parada.
- `Screener.tsx` — monta el panel y se suscribe al WS de alarmas.

**Nada de `app/backtester/`, `strategy_engine.py` ni `indicators.py`.** Es
deliberado: son productos separados. Si te ves importando de ahí, para y relee
[PLAN_FASES.md](PLAN_FASES.md).

---

## 5 · Probar sin WebSocket

`POST /api/alarms/{id}/replay` con `{"ticker","date","deliver"}` — o el botón
*Probar con un día pasado* en el editor. Pide las barras por REST y las mete por
el **mismo** camino que el stream. Funciona a cualquier hora y en fin de semana.

No es un backtest: no simula ejecuciones ni calcula rendimiento.

---

## 6 · Trampas — no deshagas esto sin leer por qué

**Una sola conexión a Massive.** El motor se cuelga del stream del screener. Una
segunda conexión con la misma API key provoca el kick-loop 1008.

**Serie anclada a las 04:00.** El VWAP es acumulado desde la primera barra. Por
eso `_backfill()` rellena el día por REST antes de vigilar un ticker: sin él, uno
que entra en el universo a las 06:12 tendría un VWAP que no es el de nadie.

**`None` nunca es 0.** Un campo sin valor hace que la condición no se cumpla. Con
cero, «precio < 1» sería siempre cierto.

**El enfriamiento es obligatorio.** «Cierra bajo el mínimo anterior y sigue sobre
el VWAP» se cumple en muchas barras seguidas de un fade. El contador se lee de la
tabla, no de RAM, para que un reinicio no reabra la puerta.

**Persistencia en GCS.** `users.duckdb` se descarga al arrancar y se sube al
apagar solo si algo la marcó como sucia. Toda escritura nueva **debe** llamar a
`_mark_dirty()`, y el contenido que crea el usuario además se sube en background
en el acto (`_sync_user_db`). Ya costó un bug: sin esto, las alarmas desaparecían
en el primer redeploy, en silencio. Si añades tablas, replica el patrón.

**El chat_id viaja con su dueño.** `iter_active_alarms()` lo trae en el mismo
JOIN que el `user_id`. Nunca lo resuelvas después contra un diccionario
compartido: por ahí se cuela el aviso de un usuario al teléfono de otro. Cubierto
por `test_el_chat_id_viaja_con_su_dueno`.

---

## 7 · Decisiones de producto pendientes (de Jesús, no tuyas)

1. **Unidad del dollar volume de la 1B.** «> 0,5» — ¿0,5M por barra o acumulado?
2. **Sizing de la 1B.** Riesgo o nominal. Con entrada 3,42 y stop 3,85 son 697
   acciones frente a 88. El motor soporta los dos (`risk_usd` / `notional_usd`).
3. **Audiencia.** Hoy cae detrás de `screener.access` (Admin).
4. **Vigilancia del servidor** a las 04:00 ET (10:00 España). Un sistema de avisos
   que falla el día que más se mueve el mercado no vale nada. **Sin resolver.**

## 8 · Bug preexistente, ajeno a esta fase

En los avisos rápidos client-side (`Screener.tsx`, ya en producción desde
`a445b34`): el desplegable ofrece «PMH Gap %», pero el backend en vivo nunca
emite ese campo — manda `pre_pct`. Como `matchesRules` exige que **todas** las
reglas casen, añadir una regla de PMH Gap **desactiva la alarma entera en
silencio**. Fix de una línea, pero cambia el comportamiento de una feature viva:
reglas que no sonaban nunca empezarían a sonar. Consúltalo con Jesús antes.
