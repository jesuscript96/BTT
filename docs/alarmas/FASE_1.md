# Fase 1 — cómo funciona y cómo se opera

## Piezas

```
Massive WS  ──A.*──►  live_screener_service            (una sola conexión)
                          │ add_aggregate_listener()
                          ▼
                    alarms/engine.py
                      ├─ bars.py        barras 1m ancladas a las 04:00 ET
                      ├─ fields.py      vocabulario (~34 campos)
                      ├─ evaluator.py   {left, op, right}, AND
                      ├─ store.py       BD, TODO filtrado por dueño
                      └─ telegram.py    bot: vinculación y reparto
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
     WS /api/alarms/live        Telegram
     (toast + beep)             (móvil)
```

| Fichero | Qué hace |
|---|---|
| `backend/app/services/alarms/fields.py` | Campos y operadores. Alias del modelo client-side antiguo. |
| `backend/app/services/alarms/bars.py` | Barras de 1m y derivados incrementales (VWAP, EMA, máximo corrido). |
| `backend/app/services/alarms/evaluator.py` | Evaluación y validación de reglas. |
| `backend/app/services/alarms/store.py` | Persistencia. Todas las lecturas con `WHERE user_id = ?`. |
| `backend/app/services/alarms/telegram.py` | Bot API + long-polling para `/start`. |
| `backend/app/services/alarms/engine.py` | Universo, ritmos de evaluación, enfriamiento, disparo. |
| `backend/app/routers/alarms.py` | CRUD, catálogo, Telegram, WS. |
| `frontend/src/components/screener/AlarmsPanel.tsx` | Configuración, dentro del modal de Alarmas. |
| `frontend/src/lib/api_alarms.ts` | Cliente. |

## Variables de entorno

| Variable | Para qué |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token de @BotFather. **Sin él el módulo funciona, pero solo avisa en el navegador.** |
| `ALARMS_ENABLED` | `0` apaga el motor sin desplegar nada. Por defecto encendido. |
| `MASSIVE_API_KEY` | Ya existente. Lo usa el backfill de barras. |

El token **nunca va al repo**. En local, `backend/.env`; en producción, variables
de entorno de Coolify. Rotarlo es cambiar el valor y reiniciar.

## Decisiones que conviene no deshacer sin leer esto

**Una sola conexión a Massive.** El motor se cuelga del stream del screener vía
`add_aggregate_listener()`. Abrir una segunda conexión con la misma API key
provoca el kick-loop 1008 que ya aparece en los logs del screener.

**Serie anclada a las 04:00.** El VWAP es acumulado desde la primera barra. Si un
ticker entra en el universo a las 06:12 y su serie empieza ahí, su VWAP no es el
de nadie. Por eso `_backfill()` rellena el día desde REST antes de vigilarlo —
que resuelve también el arranque en frío tras un despliegue a media sesión.

**None nunca es 0.** Un campo sin valor hace que la condición no se cumpla. Si se
sustituyera por cero, «precio < 1» sería siempre cierto y dispararía avisos que
nadie sabría explicar.

**El modo de disparo se deduce.** Instantáneo si todos los campos lo son; al
cierre de barra si alguno necesita la serie. El usuario no elige.

**El enfriamiento es obligatorio.** «Cierra por debajo del mínimo anterior y sigue
sobre el VWAP» se cumple en muchas barras seguidas de un fade. Sin tope de avisos
por ticker y día, el sistema es spam y se apaga el primer día. El contador se lee
de la tabla, no de RAM, para que un reinicio no reabra la puerta.

**El chat_id viaja con su dueño.** `iter_active_alarms()` trae el `chat_id` en el
mismo JOIN que el `user_id`. Nunca se resuelve después contra un diccionario
compartido: ahí es por donde se colaría el aviso de un usuario al teléfono de otro.
Está cubierto por `tests/test_alarms.py::test_el_chat_id_viaja_con_su_dueno`.

## Probar

### Sin WebSocket: reproducir un día real

Massive admite **una conexión WS por API key**. Si QA y producción levantan las
dos el screener con la misma clave, se expulsan en bucle (cierre 1008) y ninguno
sirve — lo que deja la rama de QA sin forma de probar alarmas de verdad.

Para eso está `POST /api/alarms/{id}/replay`: pide las barras de un día por REST
y las mete por el MISMO camino que el stream (`SessionBars` → `snapshot()` →
`evaluate()`). Mismo anclaje a las 04:00, mismo VWAP acumulado, mismo
enfriamiento. Funciona a cualquier hora y en fin de semana.

```bash
curl -X POST https://TU-BACKEND/api/alarms/<ALARM_ID>/replay \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"ticker":"LGHL","date":"2026-07-27","deliver":true}'
```

`deliver: true` manda además la primera señal a tu Telegram, marcada como
reproducción, para ver el mensaje real.

**No es un backtest** y no debe presentarse como tal: no simula ejecuciones, no
aplica slippage ni comisiones y no calcula rendimiento. Solo dice a qué horas y
precios habría avisado.

### Tests

```bash
cd backend && python -m pytest tests/test_alarms.py -q
```

21 tests: barras (cierre, ancla, VWAP acumulado, máximo corrido, barrido de
barras huérfanas), evaluador (las cuatro condiciones de la 1B, None, cruces,
compatibilidad con el modelo antiguo), aislamiento entre usuarios y causalidad
de la reproducción.

## Ejemplo: la 1B como alarma

```json
{
  "name": "Fade PM gapper",
  "side": "short",
  "definition": {
    "universe": [
      { "left": "pmh_gap_pct", "op": ">=", "right": 50 },
      { "left": "pre_volume",  "op": ">=", "right": 2000000 }
    ],
    "conditions": [
      { "left": "close",         "op": ">", "right": 0.7 },
      { "left": "dollar_volume", "op": ">", "right": 500000 },
      { "left": "close",         "op": "<", "right": "prev_bar_low" },
      { "left": "close",         "op": ">", "right": "vwap" }
    ],
    "window":   { "from": "04:00", "to": "08:00" },
    "cooldown": { "max_per_ticker_per_day": 3, "min_minutes_between": 5 },
    "sizing":   { "stop_ref": "previous_max", "stop_offset_pct": 10, "risk_usd": 300 }
  }
}
```

La piramidación va como **una segunda alarma independiente** — sus tres
condiciones son hechos de mercado y no necesitan saber si estás dentro:

```json
{ "conditions": [
    { "left": "mins_since_high", "op": ">=", "right": 20 },
    { "left": "dist_vwap_pct",   "op": "<=", "right": -10 },
    { "left": "close",           "op": ">",  "right": "ema15" } ] }
```

## Lo que esta fase NO hace

No sigue posiciones, no sabe si entraste, no vigila tu stop, no cuenta
reentradas y no calcula rendimiento. «Reentradas: 2» de la 1B se traduce aquí al
enfriamiento (`max_per_ticker_per_day`). El stop y la hora de salida son
**información en el aviso**, no algo que el sistema vigile. Ver
[PLAN_FASES.md](PLAN_FASES.md).
