"""La fuente de datos EN VIVO: del WebSocket de Massive a velas de minuto.

Es la pieza que faltaba para que el bot deje de comer del lago. Todo lo demas
—motor, runner, avisos— ya funcionaba; aqui solo se sustituye de donde vienen
las velas.

DOS CANALES, Y NO ES UN CAPRICHO:

  AM.*  velas de MINUTO ya cerradas y oficiales -> lo que come el motor.
  A.*   agregados por SEGUNDO, la vela en formacion -> las prealertas.

Medido el 2026-09-01 con AAPL/TSLA/NVDA/SPY: construir la vela sumando los `A`
da los precios bien pero **el volumen sale corto entre un 1,5% y un 4,6%**,
porque el proveedor cuenta operaciones (bloques fuera de secuencia, lotes
sueltos) que no salen en los agregados por segundo. Y eso no es un detalle: 1B
decide con `Accumulated Dollar Volume` y con el volumen de premercado, asi que
un 3% de menos mueve el minuto en que se cumple la condicion y las senyales
dejan de ser las del backtest. Con `AM`: 20 velas, 20 identicas al REST.

HIDRATACION. Al empezar a seguir un ticker se piden sus velas del dia por REST.
Sin eso, los acumulados (VWAP, dollar volume, maximo de premercado) arrancan
donde se conecto el bot y la operacion ni se ve — medido: entrando al radar 5
minutos antes de la senyal, sin hidratar salen CERO avisos.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import ssl
from datetime import datetime
from typing import Any, Callable, Iterable, Optional
from zoneinfo import ZoneInfo

import httpx
import pandas as pd

try:
    import websockets
except Exception:  # pragma: no cover
    websockets = None  # type: ignore

logger = logging.getLogger("btt.bot_alerts.feed")

WS_URL = os.getenv("MASSIVE_WS_URL", "wss://socket.massive.com/stocks")
REST = os.getenv("MASSIVE_API_BASE_URL", "https://api.massive.com")
ET = "America/New_York"


def clave_bot() -> str:
    """La clave del BOT. Nunca `MASSIVE_API_KEY`.

    Aunque hoy tengan el mismo valor, leer la otra aqui seria justo el error que
    la separacion existe para impedir: si algun dia vuelve a haber dos
    consumidores de tiempo real, se separan cambiando una linea del .env.
    """
    return os.getenv("MASSIVE_BOT_API_KEY", "").strip()


def _ssl_ctx() -> ssl.SSLContext:
    """Almacen de certificados de Windows, no `certifi`.

    Con un antivirus que inspecciona HTTPS (Avast, en esta maquina) el
    certificado lo firma el propio antivirus; `certifi` no conoce esa autoridad
    y la conexion muere con CERTIFICATE_VERIFY_FAILED. El almacen del sistema si
    la conoce — y sin antivirus funciona igual.
    """
    ctx = ssl.create_default_context()
    try:
        ctx.load_default_certs(ssl.Purpose.SERVER_AUTH)
    except Exception:  # noqa: BLE001
        pass
    return ctx


def hidratar_rest(ticker: str, dia: Optional[str] = None) -> pd.DataFrame:
    """Velas de 1m del dia, por REST. Se pide UNA vez, al empezar a seguirlo.

    Devuelve las columnas que espera el motor, con el timestamp en hora de
    mercado (el lago esta en hora de Nueva York, y mezclar husos aqui
    desplazaria la ventana de la estrategia).
    """
    key = clave_bot()
    if not key:
        return pd.DataFrame()
    hoy = dia or datetime.now(tz=ZoneInfo(ET)).strftime("%Y-%m-%d")
    url = f"{REST}/v2/aggs/ticker/{ticker}/range/1/minute/{hoy}/{hoy}"
    try:
        r = httpx.get(url, params={"apiKey": key, "limit": 50000, "sort": "asc"},
                      timeout=30, verify=_ssl_ctx())
        r.raise_for_status()
        filas = r.json().get("results") or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("[FEED] no se pudo hidratar %s: %s", ticker, exc)
        return pd.DataFrame()

    if not filas:
        return pd.DataFrame()
    df = pd.DataFrame([{
        "timestamp": pd.Timestamp(b["t"], unit="ms", tz="UTC").tz_convert(ET).tz_localize(None),
        "open": b["o"], "high": b["h"], "low": b["l"], "close": b["c"], "volume": b["v"],
    } for b in filas])
    return df.sort_values("timestamp").reset_index(drop=True)


def vela_de_mensaje(ev: dict) -> Optional[dict]:
    """Un mensaje `AM` -> una vela lista para el motor."""
    o, h, l, c = ev.get("o"), ev.get("h"), ev.get("l"), ev.get("c")
    ts = ev.get("s")
    if ts is None or None in (o, h, l, c):
        return None
    return {
        "timestamp": pd.Timestamp(int(ts), unit="ms", tz="UTC").tz_convert(ET).tz_localize(None),
        "open": float(o), "high": float(h), "low": float(l), "close": float(c),
        "volume": float(ev.get("v") or 0),
    }


class FeedEnVivo:
    """Escucha el socket y entrega velas de minuto ya cerradas.

    `al_cerrar_vela(ticker, vela)` se llama con cada vela completa. Los
    agregados por segundo se entregan aparte por `al_tick`, que hoy no usa nadie
    y es el enganche de las prealertas.
    """

    def __init__(
        self,
        tickers: Iterable[str],
        al_cerrar_vela: Callable[[str, dict], Any],
        al_tick: Optional[Callable[[str, dict], Any]] = None,
    ):
        self.tickers = [t.upper() for t in tickers]
        self.al_cerrar_vela = al_cerrar_vela
        self.al_tick = al_tick
        self.conectado = False
        self.velas_recibidas = 0
        self.ticks_recibidos = 0
        self._parar = False
        self._ws = None          # la conexion viva, para suscribir sobre la marcha

    def parar(self) -> None:
        self._parar = True

    async def anyadir(self, nuevos: Iterable[str]) -> list[str]:
        """Empieza a seguir tickers con la conexion ya abierta.

        Lo usa el radar: los candidatos aparecen a lo largo de la manyana y no
        se puede reconectar cada vez. Devuelve los que se anyadieron de verdad.

        La lista se actualiza aunque el envio falle: al reconectar se suscribe
        la lista ENTERA, asi que un ticker anyadido con el socket caido entra
        igual en cuanto vuelva.
        """
        pendientes = [t.upper() for t in nuevos if t.upper() not in self.tickers]
        if not pendientes:
            return []
        self.tickers.extend(pendientes)
        ws = self._ws
        if ws is not None:
            canales = ([f"AM.{t}" for t in pendientes] + [f"A.{t}" for t in pendientes])
            try:
                await ws.send(json.dumps({"action": "subscribe",
                                          "params": ",".join(canales)}))
            except Exception as exc:  # noqa: BLE001
                logger.warning("[FEED] no se pudo suscribir a %s: %s", pendientes, exc)
        return pendientes

    async def correr(self) -> None:
        if websockets is None:
            raise RuntimeError("falta la libreria websockets")
        key = clave_bot()
        if not key:
            raise RuntimeError(
                "falta MASSIVE_BOT_API_KEY en backend/.env — el bot NO debe usar "
                "MASSIVE_API_KEY"
            )

        espera = 1.0
        while not self._parar:
            conectado_en = None
            try:
                async with websockets.connect(
                    WS_URL, ssl=_ssl_ctx(), ping_interval=20,
                    max_size=2**22, open_timeout=30,
                ) as ws:
                    await ws.send(json.dumps({"action": "auth", "params": key}))
                    # La lista ENTERA, no solo la inicial: si el radar anyadio
                    # tickers mientras el socket estaba caido, entran aqui.
                    canales = ([f"AM.{t}" for t in self.tickers]
                               + [f"A.{t}" for t in self.tickers])
                    if canales:
                        await ws.send(json.dumps({"action": "subscribe",
                                                  "params": ",".join(canales)}))
                    self._ws = ws
                    self.conectado = True
                    conectado_en = asyncio.get_event_loop().time()
                    logger.info("[FEED] conectado · %d tickers", len(self.tickers))

                    async for crudo in ws:
                        if self._parar:
                            break
                        self._procesar(crudo)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                self.conectado = False
                self._ws = None
                # La espera solo se reinicia si la conexion AGUANTO un rato. Sin
                # esto, que te echen por tener otra sesion con la misma clave
                # convierte la reconexion en un martilleo de 1 s sobre el socket
                # y sobre el log.
                ahora = asyncio.get_event_loop().time()
                if conectado_en is not None and ahora - conectado_en >= 60:
                    espera = 1.0
                logger.warning("[FEED] desconectado (%s); reintento en %.0f s", exc, espera)
                await asyncio.sleep(espera)
                espera = min(espera * 2, 60.0)
        self.conectado = False

    def _procesar(self, crudo: Any) -> None:
        try:
            paquete = json.loads(crudo)
        except (TypeError, ValueError):
            return
        for ev in (paquete if isinstance(paquete, list) else [paquete]):
            if not isinstance(ev, dict):
                continue
            tipo = ev.get("ev")
            if tipo == "status":
                logger.info("[FEED] %s: %s", ev.get("status"), ev.get("message"))
            elif tipo == "AM":
                vela = vela_de_mensaje(ev)
                if vela is None:
                    continue
                self.velas_recibidas += 1
                try:
                    self.al_cerrar_vela(str(ev.get("sym", "")), vela)
                except Exception as exc:  # noqa: BLE001
                    # Un fallo con un ticker no puede dejar sordo al bot para
                    # los demas.
                    logger.warning("[FEED] fallo al procesar %s: %s", ev.get("sym"), exc)
            elif tipo == "A":
                self.ticks_recibidos += 1
                if self.al_tick is not None:
                    try:
                        self.al_tick(str(ev.get("sym", "")), ev)
                    except Exception:  # noqa: BLE001
                        pass
