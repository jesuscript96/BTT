"""El bot en marcha: mantiene los frames vivos y saca los avisos.

SEPARA LA FUENTE DE DATOS DEL RESTO A PROPOSITO. Aqui solo se sabe que "llega
una vela de un ticker". De donde venga —una reproduccion del lago hoy, el
WebSocket de Massive cuando haya clave— no cambia nada de este fichero. Eso
permite construir y probar el bot entero sin socket, y que enchufarlo despues
sea cambiar quien llama a `nueva_vela`.

EL CICLO DE UN TICKER:

    entra al radar  ->  hidratar(ticker, velas_del_dia_hasta_ahora)
                        (una sola vez: el pasado que el motor necesita)
    cada minuto     ->  nueva_vela(ticker, vela)
                        (devuelve los avisos que genere esa vela)
    fin del dia     ->  reiniciar()

POR QUE HACE FALTA HIDRATAR. Las condiciones de 1B son acumulados desde el
inicio del premercado (VWAP, dollar volume, maximo de premercado). Un ticker que
cruza el umbral a las 07:00 y empieza su frame ahi da numeros que no son los del
backtest. El pasado hay que traerlo entero antes de evaluar nada.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from app.services.bot_alerts_engine import Evento, MotorAlertas
from app.services.market_frame import build_market_frame
from app.services.bot_alerts_engine import estimar_por_estrategia
from app.services.strategy_engine import translate_strategy

logger = logging.getLogger("btt.bot_alerts.runner")

# Columnas minimas de una vela.
COLUMNAS = ("timestamp", "open", "high", "low", "close", "volume")
ET = "America/New_York"     # los frames van en hora de Nueva York, sin zona


class RunnerAlertas:
    """Frames en memoria + motor, ticker a ticker.

    `al_avisar` se llama con cada evento nuevo: es el enganche para Telegram, el
    log o lo que haga falta. Se le deja fuera a proposito para que el runner no
    dependa de a donde van los avisos.
    """

    def __init__(
        self,
        estrategias: list[dict],
        al_avisar: Optional[Callable[[Evento], Any]] = None,
    ):
        self.motor = MotorAlertas(estrategias)
        self.al_avisar = al_avisar
        # Velas crudas por ticker. Crudas y no el frame calculado porque los
        # niveles de estructura son acumulados: hay que recalcularlos sobre el
        # dia entero cada vez, no se pueden ir anyadiendo por partes.
        self._velas: dict[str, list[dict]] = {}
        self._stats: dict[str, dict] = {}
        self._hidratados: set[str] = set()

    # ── ciclo de vida ────────────────────────────────────────────────────────
    def reiniciar(self) -> None:
        """Nuevo dia: se tira todo, frames y avisos ya emitidos."""
        self._velas.clear()
        self._stats.clear()
        self._hidratados.clear()
        self.motor.reiniciar()

    def actualizar(self, estrategias: list[dict]) -> dict:
        """Cambia las estrategias vigiladas sin tocar frames ni avisos dados.
        Ver `MotorAlertas.actualizar`."""
        return self.motor.actualizar(estrategias)

    @property
    def tickers(self) -> list[str]:
        return sorted(self._velas)

    def esta_hidratado(self, ticker: str) -> bool:
        return ticker in self._hidratados

    # ── entrada de datos ─────────────────────────────────────────────────────
    def hidratar(self, ticker: str, day_df: pd.DataFrame, daily_stats: dict | None = None,
                 ahora: Optional[pd.Timestamp] = None) -> list[Evento]:
        """Carga de golpe el pasado del dia. Se llama UNA vez, al entrar al radar.

        Devuelve los avisos de la ULTIMA VELA COMPLETA, que son de verdad.

        EL PASADO SE SELLA, NO SE AVISA. El motor recuerda lo que ya aviso. Si
        el pasado no se le ensenya, la primera vela nueva le hace descubrir de
        golpe todas las salidas y piramides del dia y las avisa como si acabaran
        de pasar. Medido en vivo el 2026-09-01 a las 20:28: el bot aviso de una
        piramide y una salida de FLYE ocurridas por la manyana, y salieron a
        Telegram. Pasandole el pasado una vez y tirando lo que salga, todo eso
        queda marcado como visto.

        PERO LA ULTIMA VELA COMPLETA NO ES PASADO: ES AHORA. El radar admite un
        ticker cuando su metrica cruza el umbral, y eso pasa en una vela
        concreta —la ultima cerrada—. Si la senyal de entrada cae en esa misma
        vela, sellarla la tira. Paso el 14-sep-2026 con ELMT: la vela de las
        06:59 NY hizo el maximo nuevo (gap 49,4 % -> 51,1 %) Y cerro por debajo
        del minimo anterior. El radar lo admitio a las 13:00:07 (7 segundos
        despues del cierre), hidrato 104 velas y el aviso de entrada salio como
        «1 avisos del pasado descartados». Jaume se quedo sin la senyal, y el
        simulador con una posicion abierta cuyas salidas SI iban a avisar.

        Es sistematico, no mala suerte: el filtro del radar y la entrada de 1B
        comparten el umbral (gap >= 50), asi que la vela que admite es a menudo
        la vela que entra.

        Y LA VELA EN CURSO NO ES NI UNA COSA NI OTRA: Massive la devuelve por
        REST a medias. Se aparta; el feed la traera entera cuando cierre.

            filas del REST  =  [ pasado ... ] [ ultima completa ] [ en curso ]
                                   sellar        evaluar HOY        fuera
        """
        self._stats[ticker] = daily_stats or {}
        filas = day_df[list(COLUMNAS)].to_dict("records") if not day_df.empty else []
        corte = (ahora if ahora is not None
                 else pd.Timestamp(datetime.now(tz=ZoneInfo(ET)).replace(tzinfo=None))).floor("min")
        completas = [f for f in filas if pd.Timestamp(f["timestamp"]) < corte]
        en_curso = len(filas) - len(completas)
        pasado, ultima = (completas[:-1], completas[-1]) if completas else ([], None)

        self._velas[ticker] = pasado
        self._hidratados.add(ticker)

        sellados = 0
        if len(pasado) >= 2:
            frame = build_market_frame(pd.DataFrame(pasado), ticker, self._stats[ticker])
            try:
                sellados = len(self.motor.procesar_vela(ticker, frame, self._stats[ticker]))
            except Exception as exc:  # noqa: BLE001
                # Si el sellado falla, es MEJOR no seguir con este ticker que
                # arriesgarse a avisar de su manyana entera.
                logger.warning("[BOT] %s: fallo al sellar el pasado (%s); se descarta", ticker, exc)
                self.soltar(ticker)
                return []

        eventos: list[Evento] = []
        if ultima is not None:
            eventos = self.nueva_vela(ticker, ultima, self._stats[ticker])

        logger.info("[BOT] %s hidratado: %d velas de pasado selladas (%d avisos tirados), "
                    "la de las %s evaluada como ACTUAL (%d avisos)%s",
                    ticker, len(pasado), sellados,
                    pd.Timestamp(ultima["timestamp"]).strftime("%H:%M") if ultima else "-",
                    len(eventos),
                    f", {en_curso} en curso apartada" if en_curso else "")
        return eventos

    def nueva_vela(self, ticker: str, vela: dict, daily_stats: dict | None = None) -> list[Evento]:
        """Anyade una vela cerrada y devuelve los avisos que produzca.

        Si el ticker no estaba hidratado se acepta igual, pero se avisa en el
        log: el frame arranca donde arranque y los acumulados saldran cortos.
        Es un fallo de integracion, no un caso normal.
        """
        if ticker not in self._hidratados:
            logger.warning(
                "[BOT] %s recibe velas SIN hidratar; los acumulados del dia saldran mal",
                ticker,
            )
            self._velas.setdefault(ticker, [])
            self._hidratados.add(ticker)
        if daily_stats is not None:
            self._stats[ticker] = daily_stats

        self._velas[ticker].append({c: vela.get(c) for c in COLUMNAS})

        frame = build_market_frame(
            pd.DataFrame(self._velas[ticker]), ticker, self._stats.get(ticker, {}),
        )
        eventos = self.motor.procesar_vela(ticker, frame, self._stats.get(ticker, {}))

        for ev in eventos:
            logger.info("[BOT] %s", ev)
            if self.al_avisar is not None:
                try:
                    self.al_avisar(ev)
                except Exception as exc:  # noqa: BLE001
                    # Que falle Telegram no puede hacerle perder la vela siguiente.
                    logger.warning("[BOT] fallo al notificar %s: %s", ev.ticker, exc)
        return eventos

    def ultima_vela_ts(self, ticker: str):
        """El timestamp de la ultima vela que tiene el motor para ese ticker, o None."""
        lista = self._velas.get(ticker) or []
        return pd.Timestamp(lista[-1]["timestamp"]) if lista else None

    def tiene_vela(self, ticker: str, ts) -> bool:
        """Si ya hay una vela con ese timestamp (propia u oficial)."""
        clave = str(pd.Timestamp(ts))[:16]
        return any(str(pd.Timestamp(v.get("timestamp")))[:16] == clave for v in self._velas.get(ticker, [])[-3:])

    def sustituir_vela(self, ticker: str, vela: dict) -> bool:
        """Reemplaza EN SILENCIO la vela de ese minuto por otra (la oficial), sin
        reevaluar: el aviso ya se dio con la propia (21-sep-2026). Devuelve si
        habia una que sustituir. Solo se mira entre las tres ultimas: la
        oficial llega ~2 s despues de que la propia cerrara el minuto."""
        clave = str(pd.Timestamp(vela.get("timestamp")))[:16]
        lista = self._velas.get(ticker, [])
        for k in range(len(lista) - 1, max(-1, len(lista) - 4), -1):
            if str(pd.Timestamp(lista[k].get("timestamp")))[:16] == clave:
                lista[k] = {c: vela.get(c) for c in COLUMNAS}
                return True
        return False

    def estimacion_locates(self, ticker: str, precio: float) -> list[dict]:
        """Para `/evf`: que pediria cada estrategia si entrara a `precio` ahora.

        **NO TOCA NINGUN ESTADO.** Reconstruye el frame a partir de las velas que
        ya tiene guardadas y no llama al motor de senales: no puede generar un
        aviso, ni marcar una entrada como avisada, ni mover nada. Preguntar por
        Telegram no puede tener efectos secundarios sobre el bot.

        Lista vacia si no hay velas de ese ticker todavia (no esta en el radar,
        o acaba de entrar).
        """
        velas = self._velas.get(ticker)
        if not velas:
            return []
        frame = build_market_frame(
            pd.DataFrame(velas), ticker, self._stats.get(ticker, {}),
        )
        # El `sl_stop` de cada estrategia sale de `translate_strategy`, igual
        # que en el camino del aviso: es la fraccion que el simulador aplica
        # sobre el precio de entrada, y cubre Percentage, Fixed Amount y ATR.
        # Se recalcula aqui (y no se cachea) porque `/evf` es una consulta
        # manual y ocasional; el coste no importa y asi no puede quedarse rancio.
        stats = self._stats.get(ticker, {})

        def _sl_stop_de(est):
            try:
                senales = translate_strategy(frame, est["definition"], stats,
                                             compiled=est.get("compiled"))
                return senales.get("sl_stop")
            except Exception:          # noqa: BLE001
                return None            # una consulta no puede tumbar nada

        # Con varias cuentas la misma estrategia aparece repetida en el motor
        # (una entrada por cuenta); para estimar el stop basta una por estrategia.
        unicas = list({e["strategy_id"]: e for e in self.motor.estrategias}.values())
        return estimar_por_estrategia(
            unicas, lambda e: e["definition"],
            frame, len(frame) - 1, precio, _sl_stop_de,
        )

    def tiene_posicion(self, ticker: str) -> bool:
        """Si el motor cree que hay una posicion viva en ese ticker.

        Lo usa el radar antes de soltarlo: dejar de mirar un ticker con posicion
        abierta seria perderse su SALIDA, que es justo la orden que hay que
        ejecutar. Un ticker puede caer del filtro (deja de subir) estando dentro
        — de hecho es lo normal en un corto que va bien.
        """
        for (tk, _sid), estado in self.motor._estado.items():
            if tk != ticker:
                continue
            # Hay entrada avisada cuya salida aun no se ha avisado.
            if len(estado.entradas_avisadas) > len(estado.salidas_avisadas):
                return True
        return False

    def evaluar_parcial(self, ticker: str, vela: dict) -> list[Evento]:
        """Evalua la vela EN FORMACION, para las prealertas.

        NO TOCA EL ESTADO. Ni guarda la vela, ni marca nada como avisado, ni
        deja rastro: se le anyade la vela a medias al frame, se mira lo que
        sale y se tira. Si se guardara, la vela definitiva (que puede ser
        distinta) no podria sustituirla, y el motor decidiria sobre una vela
        que nunca existio.

        Como el motor recuerda lo avisado en su propio estado, aqui se usa un
        motor APARTE con el mismo estado ya sellado — asi una prealerta no
        impide que luego se avise la alerta de verdad.
        """
        if ticker not in self._hidratados:
            return []
        filas = self._velas.get(ticker) or []
        if len(filas) < 1:
            return []

        frame = build_market_frame(
            pd.DataFrame(filas + [{c: vela.get(c) for c in COLUMNAS}]),
            ticker, self._stats.get(ticker, {}),
        )
        try:
            return self.motor.mirar_sin_marcar(ticker, frame, self._stats.get(ticker, {}))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[BOT] %s: fallo al mirar la vela en curso: %s", ticker, exc)
            return []

    def soltar(self, ticker: str) -> None:
        """Deja de seguir un ticker y libera su frame."""
        self._velas.pop(ticker, None)
        self._stats.pop(ticker, None)
        self._hidratados.discard(ticker)
