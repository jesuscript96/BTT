# Alarmas del Screener — Cierre (2026-09-15)

**Estado: FEATURE CORREGIDA, DESPLEGADA Y VALIDADA EN PRODUCCIÓN.** Los dos bugs que rompían las
alarmas están arreglados y probados de punta a punta. Historia completa en `HALLAZGOS.md` y el plan
por fases en `PLAN_FASES.md`.

## Qué estaba roto y qué se arregló

- **BUG A — el PM High Gap salía mal tras un reinicio.** El máximo de premarket (`pre_high`) vivía
  solo en memoria (alimentado por el WS) y el snapshot REST no lo recuperaba. Si el backend
  arrancaba/reiniciaba después del pico de premarket (y cada deploy reinicia), el ticker salía con
  un gap bajo, se caía del universo y **la alarma nunca disparaba**. **Fix:** reconstruir todo el
  estado de sesión desde barras de minuto REST al arrancar / cambiar de día / reconectar el WS, con
  merge y sin disparar avisos. Gate `SESSION_BACKFILL_ENABLED` (activado en prod).
- **BUG B — las instantáneas ignoraban la franja horaria.** `_tick_instant` disparaba sin comprobar
  la ventana (el camino de barra sí la respetaba). **Fix:** `_in_window(_now_minute(), …)` antes de
  disparar.

## Cómo se validó (sin robarle el WS único de prod)

1. **Simulador de WebSocket** (`backend/scripts/sim_ws_alarms.py`): reproduce el BUG A con datos
   reales y verifica el fix. 40 tests en verde.
2. **QA en `develop`**: los dos bugs sobre el código desplegado + cadena de Telegram al bot de dev.
3. **Prod (canary + premarket real):**
   - **2026-09-14 (RTH):** evidencia de que el backfill funciona (backend reiniciado a mediodía y aun
     así PM High Gap correcto de los movers) + **disparo en vivo**: alarma creada desde el navegador
     (FTFT, `Change % > 30`) → disparó → aviso a Telegram del bot de prod `@Edgiethebot`.
   - **2026-09-15 (premarket real):** el observer confirmó en vivo el PM High Gap correcto de los
     gappers del día (BDRX 203,57 %, VEEA 97,82 %, MYSZ 98,8 %…).

## Desplegado

- Merge `develop → main` = `99f6ae5`. Prod (`kvcfvkb…`) con `SESSION_BACKFILL_ENABLED=1`, WS conectado.
- BUG B activo (no gateado). Frontend re-desplegado por Vercel → UI de Alarmas visible para admins.

## Flecos abiertos (no bloquean; decisión de producto)

1. **BUG D (frontend):** el botón *Conectar Telegram* abre `tg://resolve?...` → falla en máquinas sin
   la app de escritorio de Telegram. **Fix propuesto:** enlace universal `https://t.me/<bot>?start=<token>`.
2. **BUG C (preexistente, de Jesús §6):** en los avisos rápidos client-side, la regla "PMH Gap %" no
   casa con el campo del backend (`pre_pct`) → añadir esa regla apaga la alarma en silencio. Fix de
   1 línea, pero cambia comportamiento vivo → consultar con Jesús.
3. **Alcance del backfill:** hoy "movers primero + resto en 2º plano". Solo "todos" es 100 % correcto
   para el gapper que picó a las 04:00 y ya se desinfló. Decisión de coste/correctitud.
4. **Vigía permanente de las 04:00 ET** (item de Jesús §9): dejar un monitor fijo que garantice
   backend + WS arriba antes del premarket y avise si se cae. El observer temporal de F6 es el germen.
5. **Housekeeping:** quitar el observer temporal (cron + `/root/alarms_premarket_observer.py`) y
   desactivar/borrar las alarmas de prueba (canary) en prod.
