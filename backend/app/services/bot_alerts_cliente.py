"""El lado del BOT: hablar con el backend por HTTP.

Vive en el repo porque es codigo de produccion, pero lo usa el proceso del bot,
que corre APARTE (su propia ventana, sin recarga automatica). El backend no
importa este modulo.

POR QUE HTTP Y NO LA BASE DE DATOS DIRECTAMENTE: el backend tiene users.duckdb
abierto en escritura y DuckDB no admite un segundo escritor — ni siquiera un
segundo lector. En Windows el bloqueo llega a impedir copiar el fichero. Asi
que el bot pregunta y publica por HTTP, y el backend es el unico duenyo de la
base.

NADA DE AQUI PUEDE TUMBAR EL BOT. Un backend caido o una red lenta no pueden
hacerle perder la vela siguiente: todo va envuelto y devuelve un valor por
defecto en vez de lanzar.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger("btt.bot_alerts.cliente")

TIMEOUT = 8.0


def _base() -> str:
    """URL del backend. El bot corre en la misma maquina que la app."""
    raw = os.getenv("BOT_ALERTS_API", "http://127.0.0.1:8010").rstrip("/")
    return raw if raw.endswith("/api") else f"{raw}/api"


def id_evento(ev: Any) -> str:
    """Identidad estable de un aviso.

    Se construye con lo que lo define y no cambia (ticker, estrategia, momento y
    tipo), de modo que reenviar la misma tanda tras un fallo de red no duplica
    filas: el backend hace INSERT OR REPLACE sobre esta clave.
    """
    return f"{ev.ticker}|{ev.strategy_id}|{str(ev.momento)[:19]}|{ev.tipo}"


def evento_a_dict(ev: Any, origen: str, modo: str) -> dict:
    return {
        "id": id_evento(ev),
        "fecha": str(ev.momento)[:10],
        "momento": str(ev.momento)[:19],
        "tipo": ev.tipo,
        "ticker": ev.ticker,
        "strategy_id": ev.strategy_id,
        "estrategia": ev.estrategia,
        "direccion": ev.direccion,
        "precio": ev.precio,
        "acciones": ev.acciones,
        "stop": ev.stop,
        "riesgo_usd": ev.riesgo_usd,
        "motivo": ev.motivo,
        "nivel": ev.nivel,
        "accion_piramide": ev.accion_piramide,
        "posicion_total": ev.posicion_total,
        "origen": origen,
        "modo": modo,
        "estado": getattr(ev, "estado", "alerta"),
    }


class ClienteBackend:
    """Las cuatro conversaciones del bot con la app."""

    def __init__(self, base: Optional[str] = None):
        self.base = base or _base()
        self._cli = httpx.Client(timeout=TIMEOUT)

    def cerrar(self) -> None:
        try:
            self._cli.close()
        except Exception:  # noqa: BLE001
            pass

    # ── UN REINTENTO CUANDO LA CONEXION VENIA MUERTA ─────────────────────
    #
    # El cliente se crea UNA VEZ y guarda las conexiones abiertas para
    # reaprovecharlas. El bot pregunta cada 5 segundos (`INTERVALO_ESTADO`) y
    # **el keep-alive de uvicorn son tambien 5 segundos**, asi que cliente y
    # servidor hacen las dos cosas a la vez: uno reutiliza la conexion justo
    # cuando el otro la esta cerrando. La peticion sale por un socket que ya no
    # existe y salta sin haber llegado nunca al backend.
    #
    # QUE EL INTERVALO COINCIDA CON EL KEEP-ALIVE ES TODO EL PROBLEMA, y por eso
    # buscarlo mal no encuentra nada. Medido el 9-sep-2026 contra el backend
    # real, 16 clientes en paralelo:
    #
    #     huecos de 12 s (pasado el limite)  ->   0 fallos de  18
    #     huecos de  5 s (en el limite)      ->  29 fallos de 416   (7,0 %)
    #     idem, con reintento                ->   0 fallos de 416
    #
    # Con 12 segundos no falla nunca: el cliente ve el socket cerrado y abre
    # otro tan tranquilo. La carrera solo existe justo en el borde. En el log
    # del bot son 1.371 fallos de este tipo, 28 de ellos en los 80 minutos
    # siguientes al arranque de las 17:50.
    #
    # NO ERA COSMETICO. `debe_vigilar()` devuelve None cuando falla y el bot se
    # queda como estaba, asi que si el fallo caia justo al pulsar «Vigilar», el
    # interruptor tardaba otro ciclo entero en llegar. Es la queja de Jaume de
    # «le doy y no se entera», y desde fuera no se distingue de un boton roto.
    #
    # SIEMPRE FALLA LA PRIMERA PETICION DESPUES DEL HUECO, que es la unica que
    # se encuentra la conexion podrida. En el bot esa primera es el GET del
    # estado, y el POST del latido va justo detras sobre una conexion recien
    # abierta. Medido: de 832 peticiones, 19 fallos y **los 19 en el GET**,
    # ninguno en el POST.
    #
    # AUN ASI SE REINTENTAN TAMBIEN LOS POST, porque el orden de las llamadas
    # no es una garantia que quiera dejar escrita en un sitio y usada en otro:
    # cualquier reordenacion futura dejaria el hueco delante de un POST. Es
    # gratis y es seguro, comprobado uno por uno:
    #
    #   /eventos  ->  `INSERT OR REPLACE` con un id estable
    #                 (ticker+estrategia+momento+tipo). Reenviar la misma tanda
    #                 no duplica filas, y **ese endpoint no manda Telegram** —
    #                 los avisos los manda el bot, no el backend.
    #   /latido, /radar, /diario, /estado  ->  sobrescriben estado. Repetir es
    #                 escribir lo mismo encima.
    #
    # LOS TIMEOUT NO SE REINTENTAN. Un corte de conexion falla al instante,
    # pero un timeout ya ha esperado sus 8 segundos y repetirlo dejaria al bot
    # parado 16 en una llamada que se hace en el hilo principal. Ademas eran 30
    # de 6.114 fallos: no compensa.
    _REINTENTABLES = (httpx.ConnectError, httpx.RemoteProtocolError,
                      httpx.ReadError, httpx.WriteError)

    def _pedir(self, metodo: str, ruta: str, **kw) -> httpx.Response:
        try:
            return self._cli.request(metodo, f"{self.base}{ruta}", **kw)
        except self._REINTENTABLES:
            # El pozo entero puede tener conexiones podridas, no solo la que
            # acaba de fallar. Se tira y se empieza de cero.
            try:
                self._cli.close()
            except Exception:  # noqa: BLE001
                pass
            self._cli = httpx.Client(timeout=TIMEOUT)
            return self._cli.request(metodo, f"{self.base}{ruta}", **kw)

    # ── lo que el bot PREGUNTA ───────────────────────────────────────────
    def vigiladas(self) -> Optional[list[dict]]:
        """Estrategias activas con su definicion y su riesgo. Se pide al
        arrancar el dia; no se vuelve a mirar, porque las estrategias no se
        editan con el bot encendido.

        Devuelve **None si no se pudo preguntar** y **[] si no hay ninguna
        activa**. Son dos problemas distintos con dos soluciones distintas
        (arrancar la app / marcar la casilla), y confundirlos manda a buscar
        donde no es.
        """
        try:
            r = self._pedir("GET", "/bot-alerts/vigiladas")
            r.raise_for_status()
            return r.json().get("estrategias") or []
        except Exception as exc:  # noqa: BLE001
            logger.warning("[BOT] no se pudo leer la configuracion: %s", exc)
            return None

    def debe_vigilar(self) -> Optional[bool]:
        """El interruptor de la pagina. None si no se pudo preguntar — que NO
        es lo mismo que 'apagado': ante la duda, el bot sigue como estaba."""
        try:
            r = self._pedir("GET", "/bot-alerts/estado")
            r.raise_for_status()
            return bool(r.json().get("vigilando"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[BOT] no se pudo leer el estado: %s", exc)
            return None

    # ── lo que el bot CUENTA ─────────────────────────────────────────────
    def publicar(self, eventos: list[dict]) -> int:
        if not eventos:
            return 0
        try:
            r = self._pedir("POST", "/bot-alerts/eventos", json={"eventos": eventos})
            r.raise_for_status()
            return int(r.json().get("guardados", 0))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[BOT] no se pudieron publicar %d avisos: %s", len(eventos), exc)
            return 0

    def dejar_parado(self) -> None:
        """Deja el interruptor en «Parado». Se llama AL ARRANCAR el bot.

        El interruptor se guarda en la base, asi que sobrevive a apagar la app.
        Sin esto, dejarlo encendido un dia haria que al dia siguiente el bot
        empezase a vigilar solo, sin que nadie lo pida — y vigilar tiene que ser
        una decision consciente.

        Se hace aqui y NO al arrancar el backend: el backend se reinicia solo
        cada vez que se guarda un fichero, y eso apagaria la vigilancia en mitad
        de la sesion.
        """
        try:
            self._pedir("POST", "/bot-alerts/estado", json={"vigilando": False})
        except Exception as exc:  # noqa: BLE001
            logger.warning("[BOT] no se pudo dejar el interruptor en parado: %s", exc)

    def publicar_radar(self, candidatos: list[dict]) -> None:
        """Lo que el radar esta viendo, para que la pagina lo pinte.

        Sin esto, el cuadro de mandos no puede ensenyar a quien mira el bot y
        se opera a ciegas: se ven las alertas, pero no de donde salen ni que
        estuvo a punto de salir.
        """
        try:
            self._pedir("POST", "/bot-alerts/radar",
                        json={"candidatos": candidatos})
        except Exception:  # noqa: BLE001
            pass  # el radar de la pagina es informativo; no vale romper por el

    def publicar_diario(self, diario: dict) -> None:
        """El log del bot y lo que le ha saltado, para el cuadro de la pagina.

        SE TRAGA EL FALLO IGUAL QUE EL RADAR, y aqui con mas motivo: esto es lo
        que se mira JUSTO CUANDO ALGO VA MAL. Si el backend no responde y el
        diario reventara por ello, se perderia el bot entero por intentar
        contar que el backend no responde.
        """
        try:
            self._pedir("POST", "/bot-alerts/diario", json=diario)
        except Exception:  # noqa: BLE001
            pass

    def latir(self, tickers: int, fuente: str, detalle: str = "") -> None:
        """Senyal de vida. Sin esto la pagina no distingue apagado de colgado."""
        try:
            self._pedir(
                "POST", "/bot-alerts/latido",
                json={"tickers": tickers, "fuente": fuente, "detalle": detalle},
            )
        except Exception:  # noqa: BLE001
            pass  # un latido perdido no importa; el siguiente llega en segundos
