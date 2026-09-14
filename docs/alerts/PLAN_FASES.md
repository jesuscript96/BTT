# Alertas del Screener — Plan por fases (0 → 7)

> Hoja de ruta para dejar la feature de Alarmas al **100 % en producción**, con pinzas.
> Complementa la bitácora `docs/alerts/HALLAZGOS.md` y el traspaso `docs/alarmas/README.md`.
>
> **Principio rector:** *testing antes que arreglar, y prod lo último.* Cada fase tiene una
> **puerta de salida** — no se avanza a la siguiente hasta cerrarla.

## Decisiones fijadas (2026-09-09)
- **Cómo probamos el camino en vivo → SIMULADOR de WS** (Fase 2). Gratis y repetible; no se
  amplía cupo de Massive (descartado por coste recurrente).
- **Validación final → CANARY en prod** (Fase 6). Alarma de prueba + ticker líquido, **fuera de
  premarket**, sobre el WS real de prod con cuidado. Gratis; se asume prueba controlada en prod.

## Estado de fases
| Fase | Título | Estado |
|---|---|---|
| 0 | Terreno y seguridad | ✅ hecha |
| 1 | Reproducir el fallo (BUG A) | ✅ hecha (`F1_BUG_A_REPRODUCCION.md`) |
| 2 | Simulador de WS | ✅ hecha (F2.1+F2.2 ✅; F2.3 Telegram cerrado en F5) |
| 3 | Arreglar BUG A (pre_high backfill) | ✅ hecha (F3.0 análisis · F3.1 código+verificado · F3.3 tests 10✅) |
| 4 | Arreglar BUG B + barrido en vivo | ✅ hecha (BUG B tests 4✅ · barrido en F5) |
| 5 | Validación end-to-end en QA (develop) | ✅ hecha (backend en verde sobre `6f03987`) |
| 6 | Canary en prod | 🟡 arrancada 2026-09-14 (desplegado `99f6ae5`, WS ok, backfill confirmado; falta validar premarket real 2026-09-15 vía observer) |
| 7 | Go-live 100 % (destape frontend) | ⬜ pendiente (UI ya re-expuesto por Vercel; falta E2E navegador + vigía 04:00 ET) |

*(Marcar 🟡 en curso / ✅ hecha a medida que avanzamos.)*

---

## Fase 0 — Terreno y seguridad  *(no se toca código)*
**Objetivo:** dejar el campo claro y seguro antes de nada.
- ✅ Jesús confirma que **él arrancó el backend** el 9-sep 06:14. El rollback del frontend NO fue git
  (main conservaba el UI); era un "promote" de Vercel → un push a main lo re-expone (asumido en F6).
- ✅ **Estado seguro:** las 3 alarmas (de prueba) **desactivadas** (`enabled=FALSE`, `active_alarms:0`). Reversible; backup en `scratchpad/alarms_backup_2026-09-09.json`.
- ✅ QA (develop, no "staging" de Jaume/Álvaro) corre con `LIVE_SCREENER_ENABLED=false` → no le roba el WS a prod.
- ✅ Build/commit vivo anotado para rollback: `5608136` (=main antes del fix).
- ✅ Regla operativa fijada: **no desplegar en premarket** (borra `pre_high`); el backfill lo mitiga pero la regla se mantiene.

**🚪 Puerta:** ✅ respuestas de Jesús + estado seguro + QA aislado verificado.

---

## Fase 1 — Reproducir el fallo de forma controlada  *(entender BUG A al 100 %)*
**Objetivo:** convertir "no entra bien" en un **caso reproducible y escrito**, sin adivinar.
- Con `scripts/trace_alarm.py` + replay, reproducir el caso medido (BAOS 4-sep: real +55,8 % vs
  mostrado +26,86 %).
- Demostrar la cadena exacta: universo filtra por `PM High Gap` → `pre_high` sin sembrar → el
  ticker se cae del universo → nunca se vigila → nunca avisa.

**🚪 Puerta:** un caso de fallo documentado y repetible (nuestro "test que falla").

**✅ HECHA (2026-09-10)** — `docs/alerts/F1_BUG_A_REPRODUCCION.md`. Cadena probada con código
(pre_high solo-memoria, sin backfill) + datos (BAOS 2026-09-04: PM high real 0,4372 = +55,75 % a
las 04:00) + el `evaluate()` real (universo pasa a 55,75, falla a 26,86/None). Motor correcto; el
fallo es el dato `pre_high` del camino en vivo.

---

## Fase 2 — Simulador de WS  *(la capacidad que nos falta: probar el vivo sin Massive)*
**Objetivo:** un mock que reinyecta agregados históricos **como si fueran en vivo**, alimentando
`live_screener_service` igual que Massive → ejercita `WS → barra → evaluación → disparo → Telegram`
**offline y repetible**.
- Disparo a un **bot de Telegram de DEV** (separado, nunca `@Edgiethebot`).
- **Criterio clave:** el simulador debe **reproducir BUG A** (cierra el lazo con Fase 1).

**🚪 Puerta:** el camino en vivo se puede ejercitar en local/staging sin tocar el WS de prod, y
reproduce el bug.

**Progreso:**
- **F2.1 ✅** interfaz del WS mapeada (inyección por `_apply_aggregate`, evento `A/AM` con `s`=epoch
  ms, sesión por timestamp; gates `_session!="closed"`, allowlist, `prev_close`; nunca `.start()`).
- **F2.2 ✅** harness mínimo (`backend/scripts/sim_ws_alarms.py`) — **BUG A reproducido** con BAOS
  2026-09-04: [A] arranca 04:00 → `pre_high`=0,4372, `pmh_gap`=55,75 → universo **PASA**; [B]
  arranca 05:00 → `pre_high`=0,3749, `pmh_gap`=33,56 → universo **CAE**. Mismo código y datos; solo
  cambia la hora de arranque.
- **F2.3 ✅** (cerrado en F5) camino completo motor → disparo → Telegram dev; entrega confirmada al
  teléfono de Adrian con el bot de dev del QA `@edgiethetradingbot`.

---

## Fase 3 — Arreglar BUG A  *(pre_high con backfill)*
**Objetivo:** sembrar `pre_high`/`pre_volume` al arrancar desde barras de minuto REST
(`backend/app/services/live_screener_service.py` → `_refresh_from_snapshot` / `_reset_day`).
- Decidir alcance: **solo movers primero** (barato) vs todos los ~8.000 tickers.
- Validar **contra el simulador (Fase 2)**: BAOS ahora sale +55,8 %, el ticker se queda en el
  universo, la alarma dispara. + tests unitarios.

**🚪 Puerta:** el caso de Fase 1 pasa de fallar a funcionar, verificado en el simulador.

**Progreso:**
- **F3.1 ✅ (código + verificado)** en `live_screener_service.py`:
  - `_fold_bars_into_state(ticker, bars)` — reconstruye TODOS los acumuladores de sesión
    (`pre_high/pre_volume/after_*/day_*`) desde barras de minuto, con la lógica de
    `_apply_aggregate`, **sin disparar listeners** y con **merge** (max/min; volumen por max, no
    acumula).
  - `_backfill_session_state` / `_backfill_many` / `_seed_session_state` — backfill REST **por
    capas**: capa 1 movers (por cambio actual), capa 2 el resto del allowlist en 2º plano
    (semáforo `SESSION_BACKFILL_CONCURRENCY`).
  - Invocado en **arranque**, **`_reset_day`** (nuevo día) y **reconexión de WS** (solo movers).
  - **Gate `SESSION_BACKFILL_ENABLED` (default OFF)** → no cambia prod hasta activarlo en
    staging/canary.
  - Verificado en local con el código real (números BAOS): arranque 05:00 → `pmh_gap` 33,56 CAE;
    tras el fold → **0,4372 / 55,75 PASA**; **0 listeners** disparados por el fold; re-fold
    idempotente. Simulador ampliado con escenario C (`sim_ws_alarms.py`) para re-verificar en staging.
- **F3.3 ✅** tests `backend/tests/test_alarms_backfill.py` (10): reconstrucción
  premarket/afterhours/day, merge (no baja / no acumula de más / idempotente), **no dispara
  listeners**, allowlist, recuperación end-to-end de BUG A, selección de movers, gate OFF. **36
  pasan** (26 existentes + 10) sin regresiones.
- **F3.2** (verificación con simulador + código real) → hecha en local con números que replican
  BAOS; re-verificación con datos reales + código desplegado en **F5 (staging)** (escenario C de
  `sim_ws_alarms.py`).

### Análisis previo del fix (planteado 2026-09-10, verificado en código — decidir antes de codificar)
**Dirección confirmada e idiomática:** la app ya usa el endpoint REST de minutos
(`engine.py:_backfill` → `/v2/aggs/ticker/{T}/range/1/minute/{día}/{día}`); sembrar `pre_high`
desde esa misma fuente reusa el patrón y da el valor correcto (BAOS = `daily_metrics.pm_high`).

**3 matices que el one-liner omite:**
1. No sale del snapshot barato (que da `day.h`=0 en premarket): el PM high exige **1 llamada de
   minuto POR ticker** → esto dispara la decisión de alcance.
2. Debe hacer **`max(pre_high_actual, REST)`**, no sobrescribir (no pisar lo acumulado por el WS).
3. Invocarlo desde `_reset_day` (arranque/nuevo día) e **idealmente al reconectar / mientras el WS
   esté caído**, no solo al arrancar.

**Decisión de alcance = tiene implicación de correctitud (para Jesús):**
- **Todos (~8.000):** 100% correcto, pero ~8.000 llamadas de minuto al arrancar (throttle, minutos).
- **Solo movers (por cambio actual del snapshot):** baratísimo, caza a BAOS, **pero falla el caso
  "picó a las 04:00 y ya se desinfló"** (proxy de cambio actual bajo → no se le siembra → bug
  persiste para ese ticker). "Todos" es el único totalmente correcto.

**Asterisco de reglas de negocio (misprints):** el `pre_high` en vivo (WS y REST) usa **dato CRUDO**,
sin el clip NBBO del lago limpio → un misprint de premarket podría meter un ticker por un tick malo.
Preexistente y ortogonal a BUG A, pero a validar. Enlaza con el trabajo de misprints/Augus.

**BUG A ≠ feature al 100%:** cierra el síntoma "no detecta entradas" (universo). Quedan BUG B (F4),
el camino en vivo sin probar entero (F5/F6) y el asterisco de misprints.

---

## Fase 4 — Arreglar BUG B + barrido de bugs solo-en-vivo
**Objetivo:** añadir `_in_window` en `_tick_instant` (instantáneas respeten la franja) y, con el
simulador, cazar otros fallos que solo aparecen en vivo (el "riesgo transversal").

**🚪 Puerta:** BUG B cerrado + una pasada de casos límite en el simulador sin sorpresas.

**Progreso:**
- **BUG B ✅** (`engine.py`): `_tick_instant` ahora comprueba `_in_window(now_minute, window_from,
  window_to)` antes de disparar (con `now_minute = _now_minute()`, ET), igual que el camino de barra.
  Tests `backend/tests/test_alarms_window.py` (4): dispara dentro / no dispara antes / no dispara
  después / sin franja siempre dispara. **40 pasan** sin regresiones.
- **Barrido de bugs solo-en-vivo** (riesgo transversal) → se hace en **F5 (staging)** con el camino
  en vivo real + simulador.

---

## Fase 5 — Validación end-to-end en QA (develop)  *(sin tocar prod)*
**Objetivo:** desplegar los fixes al QA de **develop** y correr los criterios de aceptación de Jesús
(`README.md` §6) de forma offline: persistencia tras redeploy, aislamiento entre usuarios, franja
horaria, Telegram a bot DEV.

**🚪 Puerta:** suite completa en verde en QA.

**Aclaración de entorno (Jesús 2026-09-14):** "staging" = rama de Jaume/Álvaro/Sailor (no se toca).
Adrian+Jesús usan **`develop`** como QA. Backend QA = contenedor Coolify `x2u32befrq2181gmym43yfhn`
(`DISABLE_GCS_SYNC=true`, `LIVE_SCREENER_ENABLED=false`). Prod = `main`.

**Progreso (2026-09-14) — ✅ backend en verde sobre `6f03987` desplegado:**
- **B1 sanity ✅** — `/health` ok; `/api/alarms/status` → `running:true`, `telegram_configured:true`;
  imagen del contenedor = `6f03987`; env verificadas en el proceso (`SESSION_BACKFILL_ENABLED=1`,
  `LIVE_SCREENER_ENABLED=false`, `DISABLE_GCS_SYNC=true`).
- **B2 BUG A (escenario C, datos reales) ✅** — `sim_ws_alarms BAOS 2026-09-04` dentro del
  contenedor: [A] 04:00→pre_high 0,4372 gap 55,75 PASA; [B] 05:00→0,37489 gap 33,56 CAE (bug);
  [C] 05:00+fix→0,4372 gap 55,75 **PASA (recuperado)**.
- **B3 BUG B (reloj real) ✅** — guard presente en `engine.py:237/270-273`; `_tick_instant` real
  contra reloj de pared (ET 11:18): franja que cubre ahora→dispara; pasada/futura→no dispara;
  sin franja→dispara.
- **B4 cadena Telegram ✅** — envío real del motor (`telegram.send_message`+`_format_message`) con el
  bot de dev del QA `@edgiethetradingbot` (id 8514608420, ≠ prod `@Edgiethebot`); `send_message→True`,
  aviso recibido en el teléfono de Adrian (09:41). Poller vivo (respondió al `/start`).
- **B5 criterios de Jesús ✅ (los de backend):** `screener_ws_connected:false` es lo ESPERADO en QA
  (aislado; modo barra no evalúa en vivo aquí→lo cubre el simulador). Persistencia = `users.duckdb`
  es **mount del host** (`/data/btt_staging/users.duckdb`→`/app/users.duckdb`) + `DISABLE_GCS_SYNC` →
  sobrevive a redeploy por construcción. Aislamiento por usuario verificado en código (`store.py`
  `WHERE user_id`, chat_id en la misma fila). "Dispara/no dispara" cubierto por B2+B3.

**Pendiente (no de backend, van en sus fases):** panel/modal en navegador (checklist §5 puntos
2-3-5) → **F7**; comportamiento con mercado abierto y WS real → **F6**. Round-trip real
crear-alarma→redeploy→sigue-ahí = opcional (necesita un redeploy manual de Adrian en Coolify).

---

## Fase 6 — Canary en PROD  *(validación final del vivo REAL, con pinzas)*
**Objetivo:** probar el WS real de prod sin exponer a usuarios.
- Deploy a prod **fuera de premarket**, con rollback listo.
- Alarma "canary" en un ticker líquido → confirmar que `watched_tickers` se puebla, dispara y
  llega el Telegram.
- Un **día de premarket real:** confirmar que el `pre_high` sembrado funciona en vivo (cruzar
  PM High Gap contra el real de Massive, como el caso BAOS).

**🚪 Puerta:** el camino en vivo real funciona en prod, medido, sin usuarios afectados.

**Progreso (2026-09-14) — 🟡 arrancada, desplegado a prod:**
- Merge `develop→main` = `99f6ae5` (solo `6f03987`, sin terceros). Prod contenedor
  `kvcfvkb3e9plgdcwgeq67w24-161706549052` en `99f6ae5`.
- Verificado por API pública: `running:true`, **`screener_ws_connected:true`**,
  `telegram_configured:true`. `SESSION_BACKFILL_ENABLED=1` confirmado por `docker inspect`.
- **Evidencia en vivo del fix BUG A:** el backend reinició a mediodía ET (post-premarket) y aun así
  el screener muestra `pre_pct` poblado (SCNI 100,6 %, BMGL 93,89 %, NCT 89,59 %) → sin backfill
  serían `None` → el backfill reconstruye los `pre_high` en prod. Cruce fino vs PM high real = pendiente.
- **Observer de premarket** montado (`/root/alarms_premarket_observer.py` + cron host, checkpoints
  02:00–07:00 GT / 04:00–09:00 ET del 2026-09-15) → postea a Discord el estado del motor + Top PM
  High Gap en vivo. Lee el snapshot por el WS `/api/screener/live` (sin auth en servidor).
- **✅ DISPARO EN VIVO EN PROD (2026-09-14 13:32 ET):** alarma canary creada DESDE EL NAVEGADOR
  (admin) sobre FTFT (tickers concretos) con condición `Change % > 30`; FTFT iba +100% → disparó →
  **llegó el aviso a Telegram del bot de prod `@Edgiethebot`** (@AgarciaDigital). Verificado por los
  dos lados: API (active_alarms=1, FTFT chg=100 en el WS) + recepción en el teléfono. Nota:
  `watched_tickers` queda `[]` con alarmas de *tickers concretos* (esa lista es solo para universo).
- **Falta para cerrar F6:** validar el premarket real del 2026-09-15 (que los gappers salen con su
  PM High Gap correcto) vía observer. El camino en vivo detecta→dispara→avisa YA está probado.

---

## Fase 7 — Go-live 100 %  *(destape)*
**Objetivo:** abrir la feature a los admins, con el camino en vivo ya probado.

**Qué hay que hacer (concreto):**
1. ✅ **Frontend en prod (Vercel):** el panel de Alarmas **abre y pinta** en `app.edgecute.com` (admin)
   y llega al backend de prod (2026-09-14).
2. ✅ **E2E desde el navegador (criterio final de Jesús) — HECHO 2026-09-14:** admin creó una alarma,
   conectó Telegram y **disparó en vivo** con aviso a Telegram (@Edgiethebot). *Pendiente menor:*
   probar recarga+persistencia del panel y el apagar/encender.
   - ⚠️ **BUG D (frontend):** el botón *Conectar Telegram* abre `tg://resolve?...` → falla en máquinas
     sin la app de escritorio ("scheme does not have a registered handler"). **Fix:** usar el enlace
     universal `https://t.me/<bot>?start=<token>` (funciona en navegador y móvil). Workaround usado:
     abrir el `https://t.me/...` a mano.
3. **Reactivar las alarmas de verdad:** las 3 de prueba siguen `enabled=FALSE` desde F0 — decidir si
   se borran o se dejan; a partir de aquí las alarmas de usuarios reales quedan activas.
4. **Vigía a las 04:00 ET** (item abierto de Jesús §9): un cron/monitor que garantice **backend vivo +
   WS conectado antes del premarket**. Aunque el backfill ya recupera el `pre_high` tras un reinicio,
   este vigía avisa si el proceso o el WS se caen justo antes de las 04:00 (cuando más importa). El
   observer temporal de F6 es el germen de esto (hacerlo permanente y con alerta de caída).
5. **Cerrar decisiones abiertas:** alcance del backfill (**movers vs todos** — solo "todos" es 100 %
   correcto para el gapper que picó a las 04:00 y se desinfló) y el **BUG C** (regla "PMH Gap %" del
   aviso rápido client-side que apaga la alarma en silencio; fix de 1 línea, consultar con Jesús).
6. **Documentación final + handoff** en `docs/alerts/`.

**🚪 Puerta:** un admin crea una alarma desde el navegador, dispara en vivo y llega el aviso. **100 %.**
