"""Motor de alarmas: universo, evaluación, enfriamiento y disparo.

Se cuelga del stream que el live screener ya consume (`A.*`, agregados por
segundo). No abre una segunda conexión a Massive: la cuenta admite una sola por
clase de activo y el propio consumidor del screener ya registra el kick-loop 1008
cuando hay dos.

Dos ritmos de evaluación, deducidos de los campos que use cada alarma:

  * INSTANT — una vez por segundo contra el estado en RAM del screener. Es lo que
    ya hacían las alarmas sonoras client-side, ahora en servidor (funciona con el
    navegador cerrado y puede ir a Telegram).
  * BAR — al cerrar cada minuto del ticker, sobre la serie anclada a las 04:00.

Alcance: las dos evaluaciones ven el UNIVERSO ENTERO, no el top 50 de la pestaña
abierta como hacía la alarma client-side. Un ticker con gap del 55% que no entre
en la tabla visible sigue disparando la alarma.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import httpx

from . import fields as F
from . import store, telegram
from .bars import BarStore, et_date_key, et_minute_of_day, PM_OPEN_MIN
from .evaluator import evaluate, mode_of, normalize_conditions

logger = logging.getLogger("btt.alarms.engine")

API_KEY = os.getenv("MASSIVE_API_KEY", "")
REST_BASE = os.getenv("MASSIVE_API_BASE_URL", "https://api.massive.com")

ALARM_REFRESH_SECONDS = 20      # recarga de definiciones desde la BD
INSTANT_TICK_SECONDS = 1.0      # cadencia de las alarmas instantáneas
STALE_SWEEP_SECONDS = 5.0       # cierre de barras que se quedaron abiertas
DEFAULT_MAX_PER_TICKER_DAY = 3  # enfriamiento por defecto
DEFAULT_MIN_MINUTES_BETWEEN = 5


def _f(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        fv = float(v)
        return fv if fv == fv and fv not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


class AlarmEngine:
    def __init__(self) -> None:
        self._bars = BarStore()
        self._alarms: List[Dict[str, Any]] = []
        self._compiled: Dict[str, Dict[str, Any]] = {}   # alarm_id -> plan compilado
        self._watched: Set[str] = set()
        self._candidates: Dict[str, Set[str]] = {}       # alarm_id -> tickers (pegajoso)
        self._backfilled: Set[str] = set()
        self._split_tickers: Set[str] = set()
        self._session_date: Optional[str] = None
        self._queue: "asyncio.Queue[Tuple[str, Dict[str, float]]]" = asyncio.Queue(maxsize=5000)
        self._listeners: List[Callable[[Dict[str, Any]], None]] = []
        self._tasks: List[asyncio.Task] = []
        self._stop = False
        self._fired: Dict[Tuple[str, str], Tuple[int, float]] = {}  # (alarm,ticker) -> (n, last_ts)
        self._started = False
        # Minuto más alto visto EN LOS DATOS. Es el reloj del feed, y no tiene por
        # qué coincidir con el de pared: con MASSIVE_WS_URL apuntando al feed
        # retrasado (wss://delayed.massive.com/stocks) va 15 minutos por detrás.
        self._feed_minute: Optional[int] = None

    # ── ciclo de vida ────────────────────────────────────────────────────────
    async def start(self) -> None:
        if os.getenv("ALARMS_ENABLED", "1").strip().lower() in ("0", "false", "no", "off"):
            logger.info("[ALARMS] desactivadas por ALARMS_ENABLED")
            return
        await asyncio.to_thread(store.ensure_schema)
        await self._reload_alarms()
        await self._refresh_splits()
        self._started = True

        from app.services.live_screener_service import live_screener_service
        live_screener_service.add_aggregate_listener(self.on_aggregate)

        loop = asyncio.get_running_loop()
        self._tasks = [
            loop.create_task(self._bar_worker()),
            loop.create_task(self._instant_loop()),
            loop.create_task(self._reload_loop()),
            loop.create_task(self._stale_sweep_loop()),
            loop.create_task(telegram.poller.run()),
        ]
        logger.info("[ALARMS] motor arrancado (%d alarmas activas, telegram=%s)",
                    len(self._alarms), "sí" if telegram.is_configured() else "no")

    async def stop(self) -> None:
        self._stop = True
        await telegram.poller.stop()
        for t in self._tasks:
            t.cancel()

    @property
    def running(self) -> bool:
        return self._started

    # ── suscripción de la UI ─────────────────────────────────────────────────
    def add_listener(self, fn: Callable[[Dict[str, Any]], None]) -> None:
        self._listeners.append(fn)

    def remove_listener(self, fn: Callable[[Dict[str, Any]], None]) -> None:
        try:
            self._listeners.remove(fn)
        except ValueError:
            pass

    # ── camino caliente: un agregado de segundo ──────────────────────────────
    def on_aggregate(self, ev: Dict[str, Any]) -> None:
        """Llamado por el live screener para CADA mensaje del WS. Tiene que ser
        barato: solo alimenta barras de los tickers vigilados y encola los cierres.
        Toda la evaluación, la BD y Telegram ocurren en el worker."""
        if not self._started:
            return
        sym = ev.get("sym")
        if not sym or sym not in self._watched:
            return
        ts = ev.get("s") or ev.get("e") or ev.get("t")
        if ts is None:
            return
        try:
            ts = int(ts)
        except (TypeError, ValueError):
            return
        session = et_date_key(ts)
        minute = et_minute_of_day(ts)
        if self._feed_minute is None or minute > self._feed_minute:
            self._feed_minute = minute
        series = self._bars.get(sym, session)
        closed = series.ingest(ts, _f(ev.get("o")), _f(ev.get("h")),
                               _f(ev.get("l")), _f(ev.get("c")), _f(ev.get("v")))
        if closed is not None:
            try:
                self._queue.put_nowait((sym, closed))
            except asyncio.QueueFull:
                logger.warning("[ALARMS] cola llena; se descarta el cierre de %s", sym)

    # ── bucles ───────────────────────────────────────────────────────────────
    async def _reload_loop(self) -> None:
        while not self._stop:
            try:
                await asyncio.sleep(ALARM_REFRESH_SECONDS)
                await self._reload_alarms()
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                logger.debug("[ALARMS] recarga: %s", e)

    async def _reload_alarms(self) -> None:
        rows = await asyncio.to_thread(store.iter_active_alarms)
        compiled: Dict[str, Dict[str, Any]] = {}
        for a in rows:
            try:
                compiled[a["id"]] = self._compile(a)
            except Exception as e:  # noqa: BLE001
                logger.warning("[ALARMS] alarma %s inválida, se ignora: %s", a["id"], e)
        self._alarms = [a for a in rows if a["id"] in compiled]
        self._compiled = compiled
        # Una alarma borrada o apagada deja de tener candidatos pegajosos.
        for aid in list(self._candidates):
            if aid not in compiled:
                self._candidates.pop(aid, None)

    def _compile(self, alarm: Dict[str, Any]) -> Dict[str, Any]:
        d = alarm.get("definition") or {}
        conditions = normalize_conditions(d.get("conditions"))
        universe = normalize_conditions(d.get("universe"))
        cooldown = d.get("cooldown") or {}
        window = d.get("window") or {}
        return {
            "conditions": conditions,
            "universe": universe,
            # Medias configurables (ema_<n>/sma_<n>) que usan las condiciones. Se
            # calculan a demanda desde la serie y se inyectan en el contexto antes
            # de evaluar (no salen del snapshot como el resto de campos de barra).
            "ma_keys": _collect_ma_keys(conditions, (d.get("sizing") or {}).get("stop_ref")),
            "mode": mode_of(conditions),
            "window_from": _minutes(window.get("from")),
            "window_to": _minutes(window.get("to")),
            "max_per_ticker": int(cooldown.get("max_per_ticker_per_day") or DEFAULT_MAX_PER_TICKER_DAY),
            "min_minutes": float(cooldown.get("min_minutes_between") or DEFAULT_MIN_MINUTES_BETWEEN),
            "watchlist": {str(t).upper() for t in (d.get("watchlist") or [])},
            "sizing": d.get("sizing") or {},
            "channels": d.get("channels") or {"browser": True, "telegram": True, "sound": True},
        }

    async def _instant_loop(self) -> None:
        """Cada segundo: refresca el universo pegajoso, decide qué tickers hay que
        vigilar con barras y evalúa las alarmas instantáneas."""
        while not self._stop:
            try:
                await asyncio.sleep(INSTANT_TICK_SECONDS)
                if not self._alarms:
                    continue
                await self._tick_instant()
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                logger.debug("[ALARMS] tick instantáneo: %s", e)

    async def _tick_instant(self) -> None:
        from app.services.live_screener_service import live_screener_service

        session = _today_key()
        if session != self._session_date:
            self._session_date = session
            self._candidates.clear()
            self._backfilled.clear()
            self._fired.clear()
            self._watched = set()
            await self._refresh_splits()

        rows = live_screener_service.snapshot_metrics()
        if not rows:
            return
        by_ticker = {r["ticker"]: r for r in rows}
        # El contexto se construye UNA vez por ticker y tick, no una por alarma.
        # Antes se rearmaba dentro de los dos bucles: con ~8.000 tickers y unas
        # pocas alarmas salían decenas de miles de dicts por segundo y el tick de
        # 1 s no llegaba. Ahora el coste lo acota el mercado, no cuánta gente use
        # el sistema.
        ctx_by_ticker = {tk: _instant_ctx(m) for tk, m in by_ticker.items()}

        new_watch: Set[str] = set()
        for alarm in self._alarms:
            plan = self._compiled.get(alarm["id"])
            if not plan:
                continue
            sticky = self._candidates.setdefault(alarm["id"], set())

            # Universo. Pegajoso a propósito: «gap del máximo de premarket ≥ 50%»
            # es una propiedad del DÍA. Si el gap afloja a las 7:00, el ticker
            # sigue siendo del universo — igual que en el backtest.
            for tk in by_ticker:
                if tk in self._split_tickers:
                    continue     # día de split: gap fantasma, no es un runner
                if plan["watchlist"] and tk not in plan["watchlist"]:
                    continue
                if tk in sticky:
                    continue
                if not plan["universe"]:
                    if plan["watchlist"]:
                        sticky.add(tk)
                    continue
                ok, _ = evaluate(plan["universe"], ctx_by_ticker[tk])
                if ok:
                    sticky.add(tk)

            candidates = sticky if (plan["universe"] or plan["watchlist"]) else set(by_ticker)
            if plan["mode"] == F.BAR:
                new_watch |= candidates

            if plan["mode"] != F.INSTANT:
                continue
            for tk in candidates:
                m = by_ticker.get(tk)
                if not m or tk in self._split_tickers:
                    continue
                ok, reasons = evaluate(plan["conditions"], ctx_by_ticker[tk])
                if ok:
                    await self._fire(alarm, plan, tk, _f(m.get("price")), reasons, {}, m)

        await self._sync_watched(new_watch)

    async def _sync_watched(self, new_watch: Set[str]) -> None:
        added = new_watch - self._watched
        self._watched = new_watch
        for tk in added:
            if tk not in self._backfilled:
                self._backfilled.add(tk)
                asyncio.create_task(self._backfill(tk))

    async def _backfill(self, ticker: str) -> None:
        """Rellena la serie del día desde REST antes de vigilar un ticker nuevo.

        Sin esto, un ticker que entra en el universo a las 06:12 empezaría su
        serie a las 06:12 y su VWAP no sería el de nadie: el VWAP es acumulado
        desde la primera barra del frame, y el ancla tiene que ser las 04:00.
        Resuelve a la vez el arranque en frío: si el backend reinicia a media
        sesión, cada ticker se rellena al volver a vigilarse."""
        if not API_KEY:
            return
        session = self._session_date or _today_key()
        url = f"{REST_BASE}/v2/aggs/ticker/{ticker}/range/1/minute/{session}/{session}"
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                r = await client.get(url, params={"apiKey": API_KEY, "limit": 50000,
                                                  "adjusted": "true", "sort": "asc"})
                data = r.json()
            results = data.get("results") or []
        except Exception as e:  # noqa: BLE001
            logger.warning("[ALARMS] backfill de %s falló: %s", ticker, e)
            return
        if not results:
            return
        series = self._bars.get(ticker, session)
        if series.bar_count > 0:
            return   # ya tenía serie viva; no la pisamos
        for b in results:
            ts = b.get("t")
            if ts is None:
                continue
            series.ingest(int(ts), _f(b.get("o")), _f(b.get("h")),
                          _f(b.get("l")), _f(b.get("c")), _f(b.get("v")))
        series.close_stale(et_minute_of_day(int(results[-1]["t"])) + 1)
        logger.info("[ALARMS] backfill %s: %d barras hasta el minuto %s",
                    ticker, series.bar_count, series.last_close_min)

    async def _stale_sweep_loop(self) -> None:
        """Un ticker que deja de operar no manda más agregados y su última barra
        se quedaría abierta para siempre. Cada pocos segundos se cierran las que
        el feed ya dejó atrás.

        Se usa el reloj del FEED (el minuto más alto visto en los datos), no el de
        pared. Con el feed retrasado de Massive los datos llegan 15 minutos tarde:
        contra el reloj de pared la barra en curso siempre parecería vencida y se
        cerraría tras su primer tick, dejando barras de un segundo y VWAP, máximos
        y dollar volume mal. Con el reloj del feed funciona igual en tiempo real y
        en retrasado."""
        while not self._stop:
            try:
                await asyncio.sleep(STALE_SWEEP_SECONDS)
                now_min = self._feed_minute
                if now_min is None:
                    continue
                for tk in list(self._watched):
                    series = self._bars.peek(tk)
                    if series is None:
                        continue
                    closed = series.close_stale(now_min)
                    if closed is not None:
                        try:
                            self._queue.put_nowait((tk, closed))
                        except asyncio.QueueFull:
                            pass
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                logger.debug("[ALARMS] barrido: %s", e)

    async def _bar_worker(self) -> None:
        """Consume cierres de barra y evalúa las alarmas de modo BAR."""
        from app.services.live_screener_service import live_screener_service

        while not self._stop:
            try:
                ticker, _bar = await self._queue.get()
                series = self._bars.peek(ticker)
                if series is None:
                    continue
                bar_ctx = series.snapshot()
                if not bar_ctx:
                    continue
                metrics = live_screener_service.metrics_for(ticker) or {}
                ctx = {**_instant_ctx(metrics), **bar_ctx}
                minute = series.last_close_min

                for alarm in list(self._alarms):
                    plan = self._compiled.get(alarm["id"])
                    if not plan or plan["mode"] != F.BAR:
                        continue
                    if ticker not in self._candidates.get(alarm["id"], set()):
                        continue
                    if not _in_window(minute, plan["window_from"], plan["window_to"]):
                        continue
                    # Medias configurables: se calculan a demanda y se meten en el
                    # contexto (no vienen del snapshot como el resto de campos).
                    for mk in plan["ma_keys"]:
                        if mk not in ctx:
                            ma = F.parse_ma(mk)
                            if ma:
                                ctx[mk] = series.ma(ma[0], ma[1])
                    ok, reasons = evaluate(plan["conditions"], ctx,
                                           prev_lookup=series.prev_snapshot_value)
                    if ok:
                        await self._fire(alarm, plan, ticker, ctx.get("close"),
                                         reasons, ctx, metrics)
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                logger.warning("[ALARMS] worker de barra: %s", e)

    # ── disparo ──────────────────────────────────────────────────────────────
    async def _fire(self, alarm: Dict[str, Any], plan: Dict[str, Any], ticker: str,
                    price: Optional[float], reasons: List[str],
                    ctx: Dict[str, Optional[float]], metrics: Dict[str, Any]) -> None:
        key = (alarm["id"], ticker)
        session = self._session_date or _today_key()
        n, last_ts = self._fired.get(key, (None, 0.0))
        if n is None:
            # Primer disparo del proceso para este par: se pregunta a la tabla, no
            # a RAM, para que un reinicio a media sesión no reabra el spam.
            n = await asyncio.to_thread(store.count_events_today, alarm["id"], ticker, session)
        if n >= plan["max_per_ticker"]:
            return
        now = time.monotonic()
        if last_ts and (now - last_ts) < plan["min_minutes"] * 60.0:
            return
        self._fired[key] = (n + 1, now)

        sizing = _compute_sizing(plan["sizing"], alarm.get("side", "long"), price, ctx)
        payload = {
            "alarm_name": alarm["name"], "ticker": ticker, "side": alarm.get("side", "long"),
            "price": price, "reasons": reasons, "sizing": sizing,
            "mode": plan["mode"], "fired_minute": _hhmm(_now_minute()),
            "change_pct": metrics.get("change_pct"), "pmh_gap_pct": metrics.get("pre_pct"),
        }

        delivered: Dict[str, Any] = {}
        chat_id = alarm.get("chat_id")
        if plan["channels"].get("telegram", True) and chat_id:
            delivered["telegram"] = await telegram.send_message(chat_id, _format_message(payload))

        await asyncio.to_thread(store.record_event, alarm["id"], alarm["user_id"],
                                ticker, session, price, payload, delivered)
        # Throttled: sin esto las señales solo llegarían a GCS en un apagado
        # ordenado, y un contenedor matado en seco se llevaría el día entero.
        store.sync_to_gcs()

        if plan["channels"].get("browser", True):
            event = {"type": "alarm", "user_id": alarm["user_id"],
                     "sound": bool(plan["channels"].get("sound", True)), **payload}
            for fn in list(self._listeners):
                try:
                    fn(event)
                except Exception:  # noqa: BLE001
                    pass
        logger.info("[ALARMS] %s → %s @ %s", alarm["name"], ticker, price)

    # ── splits ───────────────────────────────────────────────────────────────
    async def _refresh_splits(self) -> None:
        """Tickers con split ejecutándose HOY. El día de un reverse split el
        cierre de ayer es pre-split y la apertura post-split, así que el gap sale
        fantasma: sobre los datos de 2026 medimos que el 25,3% de los tickers con
        gap de premarket ≥100% son exactamente esto. Sin el filtro, una de cada
        cuatro alarmas de universo sería basura."""
        session = self._session_date or _today_key()
        try:
            from app.services.massive_service import get_splits_since
            rows = await asyncio.to_thread(get_splits_since, session)
            tickers = set()
            for r in rows or []:
                tk = r.get("ticker") or r.get("symbol")
                exec_date = str(r.get("execution_date") or r.get("date") or "")
                if tk and exec_date.startswith(session):
                    tickers.add(str(tk).upper())
            self._split_tickers = tickers
            if tickers:
                logger.info("[ALARMS] %d tickers con split hoy, excluidos: %s",
                            len(tickers), ", ".join(sorted(tickers)[:10]))
        except Exception as e:  # noqa: BLE001
            # Fail-open con aviso: preferimos alarmas con algún split colado a
            # quedarnos sin alarmas por un fallo de la API de referencia.
            logger.warning("[ALARMS] no se pudo cargar la lista de splits (%s); "
                           "hoy pueden colarse gaps fantasma de split", e)

    # ── utilidades de estado para la API ─────────────────────────────────────
    def status(self) -> Dict[str, Any]:
        # `screener_ws_connected` es el diagnóstico de «¿por qué no salta nada?»:
        # sin stream no hay barras y las alarmas de modo BAR no se evalúan jamás.
        # En false lo normal es que este entorno no tenga la clave de Massive, o
        # que otro backend con la MISMA clave esté expulsando a este (Massive
        # admite una sola conexión por clave).
        try:
            from app.services.live_screener_service import live_screener_service
            ws_connected = live_screener_service.ws_connected
        except Exception:  # noqa: BLE001
            ws_connected = False
        return {
            "running": self._started,
            "screener_ws_connected": ws_connected,
            "active_alarms": len(self._alarms),
            "watched_tickers": sorted(self._watched),
            "series_live": len(self._bars),
            "session_date": self._session_date,
            "splits_excluded": sorted(self._split_tickers),
            "telegram_configured": telegram.is_configured(),
        }


# ── helpers de módulo ────────────────────────────────────────────────────────
def _collect_ma_keys(conditions: List[Dict[str, Any]], stop_ref: Any = None) -> List[str]:
    """Claves de media configurable (ema_<n>/sma_<n>) que aparecen en las
    condiciones o como referencia del stop, para calcularlas a demanda al evaluar."""
    keys = set()
    for c in conditions:
        for side in (c.get("left"), c.get("right_field")):
            if side and F.parse_ma(side):
                keys.add(side)
    if stop_ref and F.parse_ma(str(stop_ref)):
        keys.add(str(stop_ref))
    return list(keys)


def _instant_ctx(m: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Traduce una fila del screener al vocabulario de campos instantáneos."""
    if not m:
        return {}
    return {
        "price": _f(m.get("price")),
        "change_pct": _f(m.get("change_pct")),
        "volume": _f(m.get("day_volume")),
        # `pre_pct` del screener ES el gap del máximo de premarket contra el
        # cierre de ayer: misma fórmula, otro nombre.
        "pmh_gap_pct": _f(m.get("pre_pct")),
        "pre_volume": _f(m.get("pre_volume")),
        "pre_high": _f(m.get("pre_high")),
        "gap_pct": _f(m.get("gap_pct")),
        "prev_close": _f(m.get("prev_close")),
        "day_high": _f(m.get("high")),
        "day_low": _f(m.get("low")),
        "rvol": _f(m.get("rvol")),
    }


def _minutes(hhmm: Optional[str]) -> Optional[int]:
    if not hhmm:
        return None
    try:
        h, m = str(hhmm).split(":")
        return int(h) * 60 + int(m)
    except (TypeError, ValueError):
        return None


def _hhmm(minute: Optional[int]) -> Optional[str]:
    if minute is None:
        return None
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _in_window(minute: Optional[int], f: Optional[int], t: Optional[int]) -> bool:
    if minute is None:
        return False
    if f is None and t is None:
        return True
    if f is not None and minute < f:
        return False
    if t is not None and minute > t:
        return False
    return True


def _now_minute() -> int:
    return et_minute_of_day(int(time.time() * 1000))


def _today_key() -> str:
    return et_date_key(int(time.time() * 1000))


def _compute_sizing(cfg: Dict[str, Any], side: str, price: Optional[float],
                    ctx: Dict[str, Optional[float]]) -> Dict[str, Any]:
    """Stop, acciones y (si está configurado el coste del paquete) locates.

    Todo esto es calculable SIN saber si el usuario está dentro: el nivel del stop
    es un dato de mercado y el riesgo es configuración. Por eso el aviso lo lleva
    aunque en esta fase el sistema no siga posiciones."""
    out: Dict[str, Any] = {}
    if not cfg or price is None or price <= 0:
        return out
    ref_key = cfg.get("stop_ref")
    offset = _f(cfg.get("stop_offset_pct")) or 0.0
    risk = _f(cfg.get("risk_usd"))
    is_short = str(side).lower() == "short"

    stop: Optional[float] = None
    if ref_key:
        ref = ctx.get(F.normalize_key(str(ref_key)))
        if ref is not None and ref > 0:
            stop = ref * (1 + offset / 100.0) if is_short else ref * (1 - offset / 100.0)
    elif _f(cfg.get("stop_pct")) is not None:
        p = _f(cfg.get("stop_pct")) or 0.0
        stop = price * (1 + p / 100.0) if is_short else price * (1 - p / 100.0)
    if stop is None:
        return out
    out["stop"] = round(stop, 4)
    out["stop_ref"] = ref_key
    out["stop_offset_pct"] = offset

    # Dos formas de dimensionar, y no son intercambiables: «riesgo» reparte una
    # cantidad fija de pérdida sobre la distancia al stop; «nominal» compra una
    # cantidad fija de exposición. Con un stop cercano la primera da muchas más
    # acciones que la segunda. Se soportan ambas de forma explícita en vez de
    # elegir una en silencio y que el usuario descubra la diferencia operando.
    distance = abs(stop - price)
    notional = _f(cfg.get("notional_usd"))
    shares = 0
    if risk and distance > 0:
        shares = int(risk / distance)
        out["shares"] = shares
        out["risk_usd"] = risk
        out["sizing_mode"] = "risk"
    elif notional and price > 0:
        shares = int(notional / price)
        out["shares"] = shares
        out["notional_usd"] = notional
        out["risk_usd"] = round(shares * distance, 2)   # riesgo IMPLÍCITO del nominal
        out["sizing_mode"] = "notional"
    if shares > 0:
        package_cost = _f(cfg.get("locate_package_cost"))
        if is_short and package_cost is not None and shares > 0:
            try:
                from app.services.locates import calc_locates
                loc = calc_locates(precio_entrada=price, precio_stop=stop,
                                   coste_paquete=package_cost, shares=shares)
                if not loc.get("error"):
                    out["locates"] = loc
            except Exception:  # noqa: BLE001
                pass
    return out


def _format_message(p: Dict[str, Any]) -> str:
    # El mensaje va en parse_mode HTML, así que TODO lo dinámico (motivos, nombre,
    # ticker) se escapa: un operador «menor que» mete un «<» literal en el motivo
    # y Telegram lo lee como una etiqueta a medio abrir → 400 y el aviso no llega.
    # Los <b>/<i> estructurales se ponen a mano sobre texto ya escapado.
    from html import escape as _esc

    side = "short" if str(p.get("side")).lower() == "short" else "long"
    price = p.get("price")
    lines = [f"🔔 <b>{_esc(str(p['ticker']))}</b> · {side}"]
    if price is not None:
        lines[0] += f" · ~{price:.4g} $"
    lines.append("")
    if p.get("reasons"):
        lines.append("<b>Por qué</b>")
        lines.extend(f"• {_esc(str(r))}" for r in p["reasons"][:8])
        lines.append("")
    s = p.get("sizing") or {}
    if s.get("stop") is not None:
        ref = s.get("stop_ref")
        ref_label = F.label_of(ref).lower() if ref else "referencia"
        off = s.get("stop_offset_pct") or 0
        lines.append(f"Stop <b>{s['stop']:.4g} $</b> ({_esc(ref_label)} {off:+g}%)")
    if s.get("shares"):
        lines.append(f"{s['shares']} acciones · riesgo {s.get('risk_usd', 0):g} $")
    loc = s.get("locates") or {}
    if loc.get("paquetes"):
        be = loc.get("break_even") or loc.get("breakeven")
        extra = f" · break-even {be:.4g} $" if isinstance(be, (int, float)) else ""
        lines.append(f"{loc['paquetes']} paquete(s) de locates{extra}")
    lines.append("")
    when = p.get("fired_minute") or ""
    lines.append(f"<i>{_esc(str(p['alarm_name']))} · {when} ET</i>")
    return "\n".join(lines)


alarm_engine = AlarmEngine()
