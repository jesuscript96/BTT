# Alertas del Screener — Bitácora de hallazgos (Adrian + Claude)

> Documento **vivo**. Aquí registramos TODO lo que vamos descubriendo mientras dejamos
> la feature de Alarmas al 100 % en producción. Cada hallazgo con fecha y evidencia.
>
> **No repite** la arquitectura ni el "cómo probar" — eso está en `docs/alarmas/README.md`
> (referencia técnica de Jesús) y en el PDF de traspaso `TraspasoAlarmasProduccion.pdf`.
> Este doc cuenta **nuestra investigación y decisiones**.

- **Objetivo:** dejar Alarmas funcionando de verdad en prod, verificando el **camino EN VIVO**
  (`WS → barra → evaluación → disparo → Telegram`), que es justo lo que nunca se probó.
- **Participантes:** Adrian (owner) + Claude. Handoff original de Jesús (jesuscript96).
- **Arrancado:** 2026-09-09.

---

## 0 · Restricción CENTRAL de testing — por qué acabó en prod sin probar

Esto es la raíz operativa del incidente, contada por Jesús y confirmada en su doc (§7) y en
memoria del proyecto:

- **Solo hay UNA conexión WebSocket de Massive disponible.** `1 MASSIVE_API_KEY = 1 conexión`.
  Si dev/staging y prod usan la misma key, **se expulsan en bucle (cierre 1008)** y **ambos
  screeners caen**.
- El **feed retrasado** (`wss://delayed.massive.com/stocks`) **también consume el cupo** de la
  cuenta (medido) → **no sirve** como segunda conexión sin ampliar cupo con Massive.
- La **reproducción histórica** (replay) **NO usa el WS** → valida el motor, pero **no** el
  camino en vivo. Y **BUG A solo aparece en vivo** (ver §3).
- **Consecuencia:** Jesús no pudo validar el camino en vivo en dev sin robarle el WS a prod;
  se desesperó y **subió a prod para poder probar con el único WS que hay** → incidente del 4-sep.

### → Cómo probamos el camino en vivo — **DECIDIDO (2026-09-09)**
- **Simulador de WS** (mock que reinyecta agregados históricos como si fueran en vivo) para
  iterar offline y repetible → **Fase 2** del plan.
- **Canary en prod** (alarma de prueba + ticker líquido, fuera de premarket) como validación
  final → **Fase 6**.
- Descartado: ampliar cupo de Massive (coste recurrente).

**Plan completo por fases: `docs/alerts/PLAN_FASES.md`.**

---

## 1 · Estado verificado de PRODUCCIÓN (2026-09-09)

| Capa | Estado | Certeza |
|---|---|---|
| **Backend** | **FORWARD** — alarmas vivas, motor corriendo, bot Telegram polleando | ✅ Definitivo |
| **Frontend (Vercel)** | **Probablemente ROLLBACK** (UI de alarmas oculta) | 🟡 Fuerte, no definitivo |

### Backend — verificado FORWARD (sirviendo alarmas)
- **Build desplegado:** `SOURCE_COMMIT=5608136…` en rama `main` = **`origin/main` exacto** (contiene TODO el código de alarmas). Módulo presente en el contenedor: `/app/app/routers/alarms.py` + `/app/app/services/alarms/`.
- **`GET /api/alarms/status` → HTTP 200** (público vía Traefik, no solo localhost):
  `running:true, screener_ws_connected:true, telegram_configured:true, active_alarms:3, watched_tickers:[], series_live:0`.
- **`TELEGRAM_BOT_TOKEN` presente** en Coolify (len 46). Bot = **`@Edgiethebot`**.
- **Logs del motor** (24h):
  ```
  [ALARMS] motor arrancado (3 alarmas activas, telegram=sí)
  [TG] poller arrancado como @Edgiethebot
  [ALARMS] TEST → AAPL @ 316.35
  [ALARMS] 11 tickers con split hoy, excluidos: ALP, AVXX, CYCN, IONZ, JFIL, KEEX, LNOK, PHGE, RCAX, RKLZ
  ```

### Cronología del rollback — reconstruida por forense de Docker
- El contenedor tiene `CreatedAt = 2026-09-04 09:07` y `StartedAt = 2026-09-09 06:14`, con
  `RestartCount = 0`, `OOMKilled = false`, política `unless-stopped`, y **host con 70 días de
  uptime** (sin reboot). Eso solo se explica con un **`stop` + `start` manual** (no crash, no
  auto-restart, no rebuild — si fuera redeploy, `CreatedAt` habría cambiado).
- **Reconstrucción:**
  1. **4-sep 09:07** → deploy del build de alarmas (`5608136`) → falla en premarket → **incidente**.
  2. **Rollback de Jesús** → **paró el contenedor del backend** (rollback real y efectivo).
  3. **9-sep 06:14** → **alguien volvió a arrancar el MISMO contenedor** → alarmas vivas otra vez.
- **→ El rollback fue real, pero ya NO está en efecto en el backend.** *(Pendiente confirmar con
  Jesús quién lo arrancó el 9-sep; probablemente él, preparando el traspaso.)*

### Frontend — probablemente ROLLBACK (no verificable al 100 % desde fuera)
- Servido por **Vercel** con **Turbopack**. La página Screener (donde vive `AlarmsPanel`) es un
  chunk **hasheado, lazy y tras el muro de Clerk** → **inalcanzable sin loguearse**.
- Se rastreó el grafo de chunks alcanzable **pre-login** (17 chunks: framework, sign-in, cliente
  de API, navegación): **0 marcadores de alarmas**. Es **esperable** y **no demuestra nada** (ese
  grafo excluye la página Screener por diseño).
- **Evidencia indirecta (fuerte):** en **72 h de logs del backend, 0 peticiones de navegador** a
  `/api/alarms/*` (solo mis propias comprobaciones de `/status`). Si el UI estuviera expuesto y un
  admin abriera el Screener, veríamos su navegador pegándole a esos endpoints. *Matiz:* el Screener
  está gateado a Admin, así que también podría ser que ningún admin lo abrió en 72 h.
- **Cierre definitivo pendiente:** mirar en **Vercel → Deployments** cuál es el de *Production* y
  su commit (solo Jesús tiene acceso). Pregunta directa: *"¿el rollback de Vercel sigue puesto?"*.

---

## 2 · Riesgo operativo — RESUELTO (2026-09-09)

- ~~3 alarmas activas + @Edgiethebot podían avisar a usuarios reales.~~ **Desactivadas** en
  Fase 0: las 3 (todas de prueba del 4-sep: `HOLA1`, `HHHH`, `AAPL/TEST`) pasadas a
  `enabled=FALSE`. `/api/alarms/status` → `active_alarms: 0` verificado. El bot sigue vivo pero
  no hay nada que disparar → **cero avisos**.
- **Reversible:** las filas están intactas. Reactivar = `UPDATE alarms SET enabled=TRUE WHERE id
  IN (...)`. IDs y backup completo en `scratchpad/alarms_backup_2026-09-09.json` y abajo.
- **Persistencia:** prod usa `USER_DB_PATH=/data/btt_prod_userdb/users.duckdb` (mount persistente)
  + `DISABLE_GCS_SYNC=true` → `users.duckdb` **no baja de GCS al arrancar**, el cambio sobrevive a
  reinicios sin subir nada. *(Ojo: el mount es la ÚNICA copia; ya no hay respaldo en GCS.)*

**IDs desactivados:** `21181a95-…db2` · `eb4ecf89-…de95` · `fc7d6091-…6b75`.

---

## 3 · Bugs abiertos (heredados del traspaso de Jesús)

### BUG A — Premarket High Gap incorrecto en vivo (hipótesis principal del "no entra bien")
- `pre_high` (máx. de premarket del live screener) es un **máximo corrido en memoria, solo del WS,
  sin backfill**. Se pierde en cada reinicio; el snapshot REST no lo recupera (`day.h` de Massive
  = 0 en premarket).
- Efecto: si el universo filtra por **PM High Gap ≥ X**, el ticker bueno aparece con gap **más bajo
  del real** → **no pasa el filtro → nunca se vigila → nunca avisa**. Medido 4-sep: BAOS real
  +55,8 % vs mostrado +26,86 %.
- La reproducción no lo pilla (ahí el gap se calcula bien desde barras históricas).
- **Fix propuesto (NO hecho):** sembrar `pre_high`/`pre_volume` al arrancar desde barras de minuto
  REST. Archivo: `backend/app/services/live_screener_service.py` (`_refresh_from_snapshot`,
  `_reset_day`). **Decisión de alcance pendiente:** ¿todos los ~8.000 tickers (caro) o solo movers?

### BUG B — Las alarmas instantáneas ignoran la franja horaria
- El camino de barra comprueba `_in_window` antes de disparar; el **instantáneo no** (`engine.py`
  ~L275) → una alarma instantánea avisa **fuera de su ventana**. **Fix:** añadir `_in_window` en
  `_tick_instant`.

### Riesgo transversal
- El camino EN VIVO nunca se ejercitó en prod (solo replay, que usa REST). Puede haber más bugs
  solo-en-vivo además de BUG A.

---

## 4 · Bugs ya arreglados (en `main`, contexto)
Filas ilegibles a 23px (grid) · «cruza VWAP/EMA» no saltaba (`_prev_derived`) · avisos con `<>&`
no llegaban a Telegram (`html.escape`) · alarmas se perdían en redeploy (`_mark_dirty`+GCS) · perf
del contexto (una vez por tick) · el modal abría por lo viejo.

---

## 5 · Reglas operativas (no romper) — de la doc de Jesús
- **No desplegar a prod durante el premarket** (10:00–15:30 ES / 04:00–09:30 ET): un deploy borra
  el estado en vivo (`pre_high`, `pre_volume`, series de barras).
- **Bot de Telegram separado** dev/prod (getUpdates es consumidor único; mismo token = se roban los `/start`).
- **1 `MASSIVE_API_KEY` = 1 conexión WS** (ver §0).
- Toda tabla/escritura nueva → `_mark_dirty` + sync GCS o se pierde en el redeploy.

---

## 6 · Preguntas / decisiones PENDIENTES
1. **A Jesús:** ¿fuiste tú quien arrancó el backend el 9-sep 06:14? ¿El rollback de Vercel (frontend) sigue puesto?
2. ~~Estrategia de testing del WS~~ → **DECIDIDO**: simulador (Fase 2) + canary en prod (Fase 6). Ver §0.
3. **Qué hacer con las 3 alarmas vivas + @Edgiethebot** mientras arreglamos (dejar o pausar) → se resuelve en **Fase 0**.
4. **Alcance del fix de BUG A:** ¿todos los tickers o solo movers? → se decide en **Fase 3**.

---

## Registro cronológico

### 2026-09-10
- **Canal Telegram de DEV listo:** bot `@Edgecute_dev_alerts_bot` (separado de `@Edgiethebot`).
  Prueba de envío punta a punta al móvil de Adrián OK. Token + chat_id se guardan SOLO local, nunca al repo.
- **Fase 2 F2.1 (mapa de interfaz WS) HECHO:** inyección por `_apply_aggregate(ev)` /
  `_handle_ws_message(raw)` (no hace falta WS real); evento `A`/`AM` con `s`=epoch ms UTC; la sesión
  pre/rth/after se decide por el TIMESTAMP del evento (`_ts_window`: ms→ET, pre=04:00–09:30), no por
  reloj; gates a satisfacer: `_session!="closed"`, `sym∈_allowlist`, `st.prev_close` sembrado. Clave
  de seguridad: el harness NO debe llamar `.start()` (arrancaría el WS real y pelearía con prod).
### 2026-09-13
- **Fase 4 — BUG B CERRADO.** `engine._tick_instant` ahora comprueba `_in_window(_now_minute(), …)`
  antes de disparar (igual que `_bar_worker`) → las instantáneas respetan la franja horaria. Tests
  `test_alarms_window.py` (4): dentro dispara / antes-después no / sin franja siempre. 40 pasan.
- **F3.3 (tests) HECHO — Fase 3 CERRADA.** `backend/tests/test_alarms_backfill.py` (10 tests):
  reconstrucción pre/after/day, merge (no baja/no acumula/idempotente), no dispara listeners,
  allowlist, recuperación end-to-end de BUG A, selección de movers, gate OFF. **36 pasan** (26+10)
  sin regresiones.
- **F3.1 (código del fix) HECHO + VERIFICADO** en `live_screener_service.py`: `_fold_bars_into_state`
  (reconstruye pre_high/pre_volume/after_*/day_* desde REST, sin listeners, con merge) + backfill por
  capas (`_seed_session_state`, movers→allowlist) invocado en arranque/reset/reconexión, gate
  `SESSION_BACKFILL_ENABLED` (default OFF). Verificado en local con código real: arranque 05:00→CAE
  (33,56); tras el fold→PASA (0,4372/55,75); 0 listeners; re-fold idempotente. Compila (py_compile).
- **F3.0 (análisis previo) HECHO** — `F3_ANALISIS_PREVIO.md`. Hallazgo: el bug es de una CLASE más
  amplia — el snapshot NO recupera `pre_*` NI `after_*` (solo-memoria); se pierden todos al reiniciar.
  Solución directa+completa PARA SU CLASE = reconstruir TODO el estado de sesión desde barras de
  minuto (no solo pre_high), en arranque+reset+reconexión, todos los tickers (capas), sin disparar
  listeners, con merge. NO cubre: misprints (crudo), BUG B, ni la cadena disparo/entrega (F5/F6).

- **Análisis previo del fix de BUG A (planteado, para Fase 3):** dirección confirmada e idiomática
  (reusa el REST de minutos de `engine.py:_backfill`), con 3 matices (per-ticker no snapshot; `max`
  no sobrescribir; invocar en `_reset_day`/WS-reconnect) + decisión de alcance con implicación de
  correctitud (todos vs movers → caso "picó y se desinfló") + asterisco de misprints (dato crudo en
  vivo). BUG A ≠ 100%. Detalle en `PLAN_FASES.md` §Fase 3.
- **Fase 2 F2.2 HECHO — BUG A reproducido en el simulador.** `backend/scripts/sim_ws_alarms.py`
  alimenta un live screener aislado con las barras reales: BAOS 2026-09-04 arrancando a las 04:00 →
  `pmh_gap`=55,75 → universo PASA; arrancando a las 05:00 → `pmh_gap`=33,56 → universo CAE. Determinista.
- **Fase 1 HECHA** — BUG A reproducido con código + datos + el `evaluate()` real. BAOS 2026-09-04:
  PM high real 0,4372 = **+55,75 %** a las **04:00** (primera barra); el universo `>50` pasa a
  55,75 y falla a 26,86/None. Motor correcto; el fallo es el `pre_high` de solo-memoria sin
  backfill. Detalle en `F1_BUG_A_REPRODUCCION.md`.

### 2026-09-09
- Bajados `develop`/`main` al día; feature de alarmas presente en git (`5608136`).
- Verificado estado de prod (backend forward, frontend probable rollback) — §1.
- Reconstruida la cronología del rollback por forense de Docker — §1.
- Confirmada la restricción del WS único como raíz del "se subió a prod para probar" — §0.
- Creada esta bitácora.
- **Decidida la estrategia de testing** (simulador + canary) y escrito el **plan por fases 0→7** en `docs/alerts/PLAN_FASES.md`.
- **Fase 0 (parcial):** Jesús confirma que él arrancó el backend el 9-sep. Backup de las 3 alarmas + **desactivadas** (`enabled=FALSE`, `active_alarms:0` verificado). Descubierto que prod usa mount persistente + `DISABLE_GCS_SYNC=true` para `users.duckdb`.
