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
| 0 | Terreno y seguridad | 🟡 en curso |
| 1 | Reproducir el fallo (BUG A) | ✅ hecha (`F1_BUG_A_REPRODUCCION.md`) |
| 2 | Simulador de WS | 🟡 en curso (F2.1+F2.2 ✅; falta F2.3 Telegram) |
| 3 | Arreglar BUG A (pre_high backfill) | ✅ hecha (F3.0 análisis · F3.1 código+verificado · F3.3 tests 10✅) |
| 4 | Arreglar BUG B + barrido en vivo | ✅ BUG B hecho (tests 4✅) · barrido en vivo → F5 |
| 5 | Validación end-to-end en staging | ⬜ pendiente |
| 6 | Canary en prod | ⬜ pendiente |
| 7 | Go-live 100 % (destape frontend) | ⬜ pendiente |

*(Marcar 🟡 en curso / ✅ hecha a medida que avanzamos.)*

---

## Fase 0 — Terreno y seguridad  *(no se toca código)*
**Objetivo:** dejar el campo claro y seguro antes de nada.
- ✅ Jesús confirma que **él arrancó el backend** el 9-sep 06:14. *(Pendiente: ¿sigue el rollback de Vercel?)*
- ✅ **Estado seguro:** las 3 alarmas (de prueba) **desactivadas** (`enabled=FALSE`, `active_alarms:0`). Reversible; backup en `scratchpad/alarms_backup_2026-09-09.json`.
- ⬜ Confirmar que **staging corre con `LIVE_SCREENER_ENABLED=false`** → no le roba el WS a prod.
- ✅ Build/commit vivo anotado para rollback: `5608136` (=main).
- ⬜ Fijar **ventana de deploy fuera de premarket** como regla operativa.

**🚪 Puerta:** ~~respuestas de Jesús~~ (falta rollback Vercel) + ✅ estado seguro + ⬜ staging aislado verificado.

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
- **F2.3 ⬜** camino completo (motor + disparo → Telegram dev `@Edgecute_dev_alerts_bot`).

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

## Fase 5 — Validación end-to-end en STAGING  *(sin tocar prod)*
**Objetivo:** desplegar los fixes a staging y correr los criterios de aceptación de Jesús
(`README.md` §6) de forma offline: persistencia tras redeploy, aislamiento entre usuarios, franja
horaria, Telegram a bot DEV.

**🚪 Puerta:** suite completa en verde en staging.

---

## Fase 6 — Canary en PROD  *(validación final del vivo REAL, con pinzas)*
**Objetivo:** probar el WS real de prod sin exponer a usuarios.
- Deploy a prod **fuera de premarket**, con rollback listo.
- Alarma "canary" en un ticker líquido → confirmar que `watched_tickers` se puebla, dispara y
  llega el Telegram.
- Un **día de premarket real:** confirmar que el `pre_high` sembrado funciona en vivo (cruzar
  PM High Gap contra el real de Massive, como el caso BAOS).

**🚪 Puerta:** el camino en vivo real funciona en prod, medido, sin usuarios afectados.

---

## Fase 7 — Go-live 100 %  *(destape)*
**Objetivo:** abrir la feature a los admins.
- **Frontend:** quitar el rollback de Vercel (redeploy con el UI de Alarmas). E2E desde el navegador.
- **Vigía a las 04:00 ET** (item abierto de Jesús §9): backend vivo + WS conectado antes del
  premarket, o el `pre_high` depende de uptime perfecto.
- Documentación final + handoff en `docs/alerts/`.

**🚪 Puerta:** un admin crea una alarma desde el navegador, dispara en vivo y llega el aviso. **100 %.**
