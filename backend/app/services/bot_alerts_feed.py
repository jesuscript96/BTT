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
import time
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

# ESPERA ANTES DE CUALQUIER RECONEXION (Jaume, 18-sep-2026: «un delay de 1
# minuto para cualquier reconexion»).
#
# La cuenta de Massive la comparten dos claves (la nuestra y la del otro
# socio) con un tope de conexiones simultaneas. Cuando un cliente se cae
# SIN cerrar bien (un contenedor que reinicia, un cable, un proceso matado),
# Massive tarda un rato en darse cuenta de que el socket viejo esta muerto;
# si ese cliente reconecta al segundo, la cuenta suma una conexion de mas y
# Massive echa a OTRA: asi nos tiraba a nosotros el reinicio rapido del
# Docker de nuestro socio (los 1008 de las 04:01-04:03 NY del 10 al 18-sep).
# Reconectar nosotros al segundo le haria lo mismo a el. Esperar un minuto da
# tiempo a que el socket viejo desaparezca de su lista.
#
# Lo que cuesta: durante ese minuto no llegan velas, y el motor no rellena
# hacia atras al reconectar (una vela de minuto de cada ticker vigilado sin
# evaluar). En premercado a las 04:02 NY no hay posiciones y da igual; en la
# apertura RTH seria la primera vela. Decision de Jaume; ajustable por .env.
ESPERA_RECONEXION = float(os.getenv("MASSIVE_WS_ESPERA_RECONEXION", "5"))
# 21-sep-2026 (Jaume): la primera vuelta a los 5 s —el corte real dura 1-2 s y
# la conexion sobrante del socio ya no suele estar—; si nos vuelven a echar sin
# aguantar un minuto, la siguiente espera se dobla (10, 20, 40) hasta el tope.
# Las velas que falten se recuperan por REST al reconectar (`al_reconectar`).
ESPERA_RECONEXION_MAX = float(os.getenv("MASSIVE_WS_ESPERA_RECONEXION_MAX", "60"))


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


def datos_del_dia_anterior(ticker: str) -> dict:
    """Cierre y apertura de AYER. Es `daily_stats` para el motor.

    IMPRESCINDIBLE, y su ausencia no da error: si no se pasa, `market_frame`
    cae a un valor de emergencia y usa **el primer precio de hoy como cierre de
    ayer**. Todo lo que dependa de ese dato sale mal en silencio — y de ahi vive
    la condicion principal de 1B (`PM High Gap %`).

    Medido el 2026-09-02 con SGLD: el bot calculaba un gap del 50,4 % cuando el
    real era del 525 %. Ahi coincidio que ambos pasaban el umbral; en otro
    ticker el gap real podria ser del 80 % y el calculado del 5 %, y no avisar.
    """
    key = clave_bot()
    if not key:
        return {}
    try:
        r = httpx.get(
            f"{REST}/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}",
            params={"apiKey": key}, timeout=20, verify=_ssl_ctx(),
        )
        r.raise_for_status()
        t = r.json().get("ticker") or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("[FEED] sin datos de ayer para %s: %s", ticker, exc)
        return {}

    prev = t.get("prevDay") or {}
    out: dict = {}
    if prev.get("c"):
        out["prev_close"] = float(prev["c"])
    if prev.get("o"):
        out["yesterday_open"] = float(prev["o"])
    return out


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
        todo_el_mercado: bool = False,
        al_mercado: Optional[Callable[[dict], Any]] = None,
        al_operacion: Optional[Callable[[str, dict], Any]] = None,
        al_reconectar: Optional[Callable[[float], Any]] = None,
    ):
        self.tickers = [t.upper() for t in tickers]
        self.al_cerrar_vela = al_cerrar_vela
        self.al_tick = al_tick
        # OPERACIONES SUELTAS (`T.`, 21-sep-2026). Los agregados por segundo
        # (`A.`) llegan ~3 s despues de cerrarse el segundo: es el tiempo que
        # Massive tarda en agregarlos, constante, medido en 22.215 mensajes
        # (mediana 3,08 s). Para reaccionar en milisegundos hay que leer las
        # operaciones tal cual salen de bolsa y agregarlas nosotros. Solo se
        # suscriben para los tickers vigilados; el mercado entero sigue en AM.
        self.al_operacion = al_operacion
        self.operaciones_recibidas = 0
        # Tras una RECONEXION (no la primera conexion): recibe los segundos que
        # el socket estuvo caido, para que el bot rellene por REST las velas
        # que se emitieron mientras tanto.
        self.al_reconectar = al_reconectar
        self.reconexiones = 0
        # MEDICION (22-sep-2026): retraso de la vela de minuto de un ticker
        # vigilado EN EL INSTANTE en que sale del socket, antes de tocarla; y
        # el mayor rato que el bucle ha pasado sin leer. Si `lat_socket` ya es
        # alto, el retraso no es nuestro.
        self.lat_socket: list = []
        self.hueco_lectura = 0.0
        self._ultima_lectura: Optional[float] = None
        self._caido_desde: Optional[float] = None
        # Suscribirse al mercado entero para que el radar pueda descubrir gaps.
        # `al_mercado` recibe TODOS los agregados de minuto, incluidos los de
        # los tickers ya vigilados.
        self.todo_el_mercado = todo_el_mercado
        self.al_mercado = al_mercado
        self.conectado = False
        self.velas_recibidas = 0
        self.ticks_recibidos = 0
        self._parar = False
        self._ws = None          # la conexion viva, para suscribir sobre la marcha

    def parar(self) -> None:
        self._parar = True

    def quitar(self, fuera: Iterable[str]) -> list[str]:
        """Deja de seguir tickers. Devuelve los que se quitaron.

        NO se desuscribe del socket: recibir unos mensajes de mas es gratis
        (se descartan al no tener frame), y desuscribirse anyade una via de
        fallo por si el ticker vuelve a entrar al radar dos minutos despues.
        Lo que importa es liberar el CUPO y dejar de evaluarlo.
        """
        quitados = [t.upper() for t in fuera if t.upper() in self.tickers]
        for t in quitados:
            self.tickers.remove(t)
        return quitados

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
            canales = ([f"AM.{t}" for t in pendientes] + [f"A.{t}" for t in pendientes]
                       + ([f"T.{t}" for t in pendientes] if self.al_operacion else []))
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

        espera = ESPERA_RECONEXION
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
                               + [f"A.{t}" for t in self.tickers]
                               + ([f"T.{t}" for t in self.tickers] if self.al_operacion else []))
                    if self.todo_el_mercado:
                        # Los agregados por minuto de TODO el mercado. Es lo que
                        # alimenta al radar: sin ver el mercado entero no se
                        # pueden descubrir gaps, solo seguir los ya conocidos.
                        # Se usa AM y no A: uno por ticker y minuto en vez de uno
                        # por segundo, con el volumen ya oficial.
                        canales.append("AM.*")
                    if canales:
                        await ws.send(json.dumps({"action": "subscribe",
                                                  "params": ",".join(canales)}))
                    self._ws = ws
                    self.conectado = True
                    conectado_en = asyncio.get_event_loop().time()
                    logger.info("[FEED] conectado · %d tickers", len(self.tickers))
                    if self._caido_desde is not None:
                        self.reconexiones += 1
                        sin_datos = time.time() - self._caido_desde
                        self._caido_desde = None
                        if self.al_reconectar is not None:
                            try:
                                self.al_reconectar(sin_datos)
                            except Exception as exc:  # noqa: BLE001
                                logger.warning("[FEED] fallo al recuperar tras reconectar: %s", exc)

                    async for crudo in ws:
                        _ahora = time.time()
                        if self._ultima_lectura is not None:
                            self.hueco_lectura = max(self.hueco_lectura, _ahora - self._ultima_lectura)
                        self._ultima_lectura = _ahora
                        if self._parar:
                            break
                        self._procesar(crudo)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                self.conectado = False
                self._ws = None
                if self._caido_desde is None:
                    self._caido_desde = time.time()
                # 5 s la primera vez; si la conexion NO aguanto ni un minuto (nos
                # han vuelto a echar: la conexion sobrante seguia contando), se
                # dobla hasta ESPERA_RECONEXION_MAX. Un rechazo repetido no se
                # martillea, y volver despacio no tira a otro cliente de la cuenta.
                ahora = asyncio.get_event_loop().time()
                if conectado_en is not None and ahora - conectado_en >= 60:
                    espera = ESPERA_RECONEXION
                logger.warning("[FEED] desconectado (%s); reintento en %.0f s", exc, espera)
                await asyncio.sleep(espera)
                espera = min(espera * 2, ESPERA_RECONEXION_MAX)
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
                sym = str(ev.get("sym", ""))
                if sym in self.tickers and self._ultima_lectura is not None:
                    try:
                        self.lat_socket.append(self._ultima_lectura - int(ev["e"]) / 1000.0)
                    except Exception:   # noqa: BLE001
                        pass
                # Primero al estado del mercado (lo usa el radar): esto entra
                # para TODOS los tickers, esten vigilados o no.
                if self.al_mercado is not None:
                    try:
                        self.al_mercado(ev)
                    except Exception:  # noqa: BLE001
                        pass
                # Y al motor solo si es un ticker que se esta vigilando.
                if sym not in self.tickers:
                    continue
                vela = vela_de_mensaje(ev)
                if vela is None:
                    continue
                self.velas_recibidas += 1
                try:
                    self.al_cerrar_vela(sym, vela)
                except Exception as exc:  # noqa: BLE001
                    # Un fallo con un ticker no puede dejar sordo al bot para
                    # los demas.
                    logger.warning("[FEED] fallo al procesar %s: %s", sym, exc)
            elif tipo == "A":
                self.ticks_recibidos += 1
                if self.al_tick is not None:
                    try:
                        self.al_tick(str(ev.get("sym", "")), ev)
                    except Exception:  # noqa: BLE001
                        pass
            elif tipo == "T":
                # Una operacion: {sym, p (precio), s (tamanyo), t (hora SIP en
                # ms), c (condiciones), x (bolsa), z (tape)}. Llega a decenas
                # de milisegundos del cruce.
                self.operaciones_recibidas += 1
                if self.al_operacion is not None:
                    try:
                        self.al_operacion(str(ev.get("sym", "")), ev)
                    except Exception:  # noqa: BLE001
                        pass
