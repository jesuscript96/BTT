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
from typing import Any, Callable, Optional

import pandas as pd

from app.services.bot_alerts_engine import Evento, MotorAlertas
from app.services.market_frame import build_market_frame

logger = logging.getLogger("btt.bot_alerts.runner")

# Columnas minimas de una vela.
COLUMNAS = ("timestamp", "open", "high", "low", "close", "volume")


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

    @property
    def tickers(self) -> list[str]:
        return sorted(self._velas)

    def esta_hidratado(self, ticker: str) -> bool:
        return ticker in self._hidratados

    # ── entrada de datos ─────────────────────────────────────────────────────
    def hidratar(self, ticker: str, day_df: pd.DataFrame, daily_stats: dict | None = None) -> None:
        """Carga de golpe el pasado del dia. Se llama UNA vez, al entrar al radar.

        NO GENERA AVISOS, y hacerlo bien no es no llamar al motor: es llamarlo y
        TIRAR lo que salga.

        El motor recuerda lo que ya aviso. Si el pasado no se le ensenya, la
        primera vela nueva le hace descubrir de golpe todas las salidas y
        piramides del dia y las avisa como si acabaran de pasar. Medido en vivo
        el 2026-09-01 a las 20:28: el bot aviso de una piramide y una salida de
        FLYE ocurridas por la manyana, y salieron a Telegram.

        Pasandole el frame hidratado una vez y descartando los eventos, todo eso
        queda marcado como visto y solo se avisa de lo que pase A PARTIR de
        ahora, que es lo unico operable.
        """
        self._stats[ticker] = daily_stats or {}
        filas = day_df[list(COLUMNAS)].to_dict("records") if not day_df.empty else []
        self._velas[ticker] = filas
        self._hidratados.add(ticker)

        sellados = 0
        if len(filas) >= 2:
            frame = build_market_frame(pd.DataFrame(filas), ticker, self._stats[ticker])
            try:
                sellados = len(self.motor.procesar_vela(ticker, frame, self._stats[ticker]))
            except Exception as exc:  # noqa: BLE001
                # Si el sellado falla, es MEJOR no seguir con este ticker que
                # arriesgarse a avisar de su manyana entera.
                logger.warning("[BOT] %s: fallo al sellar el pasado (%s); se descarta", ticker, exc)
                self.soltar(ticker)
                return

        logger.info("[BOT] %s hidratado con %d velas (%d avisos del pasado descartados)",
                    ticker, len(filas), sellados)

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
