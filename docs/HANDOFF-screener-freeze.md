# Handoff — Screener: freeze al cerrar + reset al abrir + badge

**Rama:** `screener` (base `93a15c0`). Todo en backend salvo el badge.
**Archivo backend:** `backend/app/services/live_screener_service.py`
**Archivo frontend (badge):** `frontend/src/components/Screener.tsx`

## Objetivo
- Mercado CERRADO → **congelar** la última lista (la del cierre del after) hasta que abra una sesión.
- Transición `closed → (pre/rth/after)` → **resetear** el día y empezar a registrar gap/run nuevo.
- Badge UI que indique "Cierre/Congelado" cuando `session==closed`.

## Backend (`live_screener_service.py`)
1. **Estado de sesión.** En `__init__` añadir `self._session: str = current_session()`.
2. **Watcher.** Nuevo task `_session_watch_loop` (sleep 30s):
   - `new = current_session()`; `prev = self._session`; `self._session = new`.
   - Si `prev == "closed" and new != "closed"` → `await asyncio.to_thread(self._reset_session)` (log "session opened").
   - Registrarlo en `start()` junto a los otros `loop.create_task(...)`.
3. **FREEZE:**
   - `_poll_snapshot_loop`: al principio del bucle, `if self._session == "closed": continue` (hoy hace lo contrario: refresca al cerrar — cambiarlo). Mantener el resto (si `ws_connected` → continue; si no, snapshot como fallback).
   - `_apply_aggregate`: tras obtener `sym`, `if self._session == "closed": return` (antes del lock).
4. **RESET.** Nuevo `_reset_session(self)`:
   - Bajo `self._lock`: por cada `st` en `self._states`: `session_high=None, session_low=None, session_volume=0.0, rth_open=None, last_price=None`. Luego `self._top_cache.clear()`.
   - Fuera del lock: `self._refresh_from_snapshot()` (re-ancla `prev_close` = nuevo `prevDay.c` y siembra `last_price`). Envolver en try/except con log.
5. **prev_close exacto (pedido por Jesús).** Capturar el cierre de RTH como base del día siguiente:
   - En el watcher, detectar transición `rth → after` (`prev=="rth" and new=="after"`): bajo lock, por cada `st` con `last_price`, guardar `st.rth_close = st.last_price` (añadir campo `rth_close: Optional[float] = None` al dataclass).
   - En `_reset_session`, ANTES de limpiar: si `st.rth_close` no es None, usarlo como `prev_close` candidato; setear `st.prev_close = st.rth_close` y `st.rth_close = None`. El `_refresh_from_snapshot` posterior solo rellena lo que falte (no pisar `prev_close` si ya viene del rth_close: en snapshot usar `st.prev_close = st.prev_close or _f(prev.get("c"))`). Revisar esa línea para no sobrescribir.

## Frontend (badge)
- `Screener.tsx` ya recibe `session` en el frame WS y lo guarda en el estado `session`. En el header, junto al `<Pill>` "LIVE/Desconectado", añadir cuando `session==="closed"` un `<Pill tone="neutral">Cierre · congelado</Pill>` (o cambiar el texto del Pill existente). Mantener tokens DS. Sin más cambios.

## Tests (`backend/tests/test_live_screener_service.py`)
- `_reset_session` limpia acumuladores y, si había `rth_close`, lo pasa a `prev_close`.
- `_apply_aggregate` con `_session="closed"` no muta estado (freeze).
- Transición `closed→pre` dispara reset; `rth→after` captura `rth_close`. (Pueden llamar a los métodos directamente seteando `svc._session`.)

## Verificación
- `cd backend && PYTHONPATH=. .venv_313/bin/python -m pytest tests/test_live_screener_service.py -q`
- Levantar local: `DEV_TIER=Admin PYTHONPATH=backend backend/.venv_313/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir backend` (front en :3000 apunta a :8000 vía `.env.local`).

## Deploy (patrón ya usado)
- Commit en `screener` → push `origin screener`.
- A prod: `git checkout main && git cherry-pick <sha> && git push origin main` (auto-deploy). Volver a `screener`.

## Notas
- Festivos: `current_session()` no los conoce; el reset dispararía a las 4am y la lista quedaría vacía ese día. Diferido a F2 (calendario de mercado).
- No tocar el contrato WS cliente ni el modelo de escaneo (`subscribe A.*`). Universo ya filtrado a CS+ADRC (allow-list, hecho).
