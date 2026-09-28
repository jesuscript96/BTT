"""Prealerta SIMPLE: «todas las condiciones de la estrategia menos una» sobre la
vela OFICIAL cerrada (26-sep-2026, decisión de Jaume del 25-sep).

QUÉ ES. En vez de montar la vela en curso con los prints y mirar del segundo 44
al 59 si ya cumple (la prealerta «por ticks»), se espera a que cierre el minuto
y se mira, condición a condición, cuántas cumple la última vela. Si cumple
TODAS MENOS UNA, se avisa: «este ticker está a una condición de dar señal», y
se dice cuál falta. No construye velas, no lee prints, no añade latencia: es la
misma evaluación de la señal, partida por condiciones.

FRENO. Un ticker puede quedarse a una condición durante una hora; sin freno
saldría un aviso por minuto. Se avisa como mucho una vez por ticker y
estrategia cada `cada_min` minutos (por defecto 10), solo dentro de la ventana
de entrada de la estrategia, y nunca si ya hay posición viva en ese ticker
(entonces lo que toca es la salida, no la entrada).

CÓMO EVALÚA. Con `_evaluate_single_condition`, la MISMA función con la que el
motor evalúa cada condición dentro de `translate_strategy`, sobre el frame que
el runner ya tiene (`build_market_frame` del día entero). Solo para raíces AND:
con OR «falta una» no significa nada.

NO TOCA ESTADO: ni el del motor ni el del runner. Lo único que guarda es el
freno (último aviso por ticker y estrategia), que se reinicia con el día.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from app.services.bot_alerts_engine import Evento
from app.services.market_frame import build_market_frame
from app.services.strategy_engine import _evaluate_single_condition

logger = logging.getLogger("btt.bot_alerts.prealerta_simple")

_OPS = {
    "GREATER_THAN": ">", "LESS_THAN": "<",
    "GREATER_THAN_OR_EQUAL": ">=", "LESS_THAN_OR_EQUAL": "<=",
    "EQUAL": "=", "CROSSES_ABOVE": "cruza arriba", "CROSSES_BELOW": "cruza abajo",
}


def etiqueta(cond: dict) -> str:
    """Nombre legible de una condición, como la ve el usuario en el constructor."""
    src = (cond.get("source") or {}).get("name", "?")
    per = (cond.get("source") or {}).get("period")
    if per:
        src = f"{src}({per})"
    op = _OPS.get(cond.get("comparator", ""), cond.get("comparator", "?"))
    tgt = cond.get("target")
    if isinstance(tgt, dict):
        tgt = tgt.get("name", "?")
    return f"{src} {op} {tgt}"


def _en_ventana(compiled: dict, momento) -> bool:
    ventanas = compiled.get("entry_time_windows") or []
    if not ventanas:
        return True
    ts = pd.Timestamp(momento)
    m = ts.hour * 60 + ts.minute
    for w in ventanas:
        try:
            fh, fm = map(int, str(w["from_time"]).split(":")[:2])
            th, tm = map(int, str(w["to_time"]).split(":")[:2])
        except (KeyError, ValueError, TypeError):
            continue
        if fh * 60 + fm <= m <= th * 60 + tm:
            return True
    return False


class PrealertaSimple:
    """Guarda solo el freno. Una instancia por proceso."""

    def __init__(self, cada_min: int = 10, max_seguidas: int = 3):
        self.cada_min = int(cada_min)
        # SILENCIO (28-sep-2026, Jaume): tras `max_seguidas` prealertas seguidas del mismo ticker y estrategia
        # con la MISMA condicion pendiente y sin llegar a entrar, se calla hasta que cambie la condicion que
        # falta (o entre). 0 = sin silencio.
        self.max_seguidas = int(max_seguidas)
        self._ultimo: dict[tuple[str, str], pd.Timestamp] = {}
        self._racha: dict[tuple[str, str], tuple[str, int]] = {}   # (condicion que falta, avisos seguidos)

    def reiniciar(self) -> None:
        self._ultimo.clear()
        self._racha.clear()

    def soltar(self, ticker: str) -> None:
        for k in [k for k in self._ultimo if k[0] == ticker]:
            self._ultimo.pop(k, None)
        for k in [k for k in self._racha if k[0] == ticker]:
            self._racha.pop(k, None)

    def _silenciada(self, clave: tuple[str, str], falta: str) -> bool:
        """Cuenta la racha por condicion pendiente; True si ya se avisó `max_seguidas` veces seguidas por la misma."""
        if self.max_seguidas <= 0:
            return False
        previa, n = self._racha.get(clave, (None, 0))
        if previa != falta:
            n = 0                                  # cambio la condicion que falta: la racha empieza de nuevo
        if n >= self.max_seguidas:
            return True
        self._racha[clave] = (falta, n + 1)
        return False

    def evaluar(self, runner, ticker: str) -> list[Evento]:
        """Los avisos «falta una» del ticker con su última vela cerrada."""
        velas = getattr(runner, "_velas", {}).get(ticker) or []
        if len(velas) < 2:
            return []
        try:
            if runner.tiene_posicion(ticker):
                return []
        except Exception:  # noqa: BLE001
            pass
        stats = getattr(runner, "_stats", {}).get(ticker, {}) or {}
        try:
            frame = build_market_frame(pd.DataFrame(velas), ticker, stats)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[PREALERTA SIMPLE] %s: no se pudo montar el frame: %s", ticker, exc)
            return []
        momento = frame["timestamp"].iloc[-1]
        precio = float(frame["close"].iloc[-1])

        eventos: list[Evento] = []
        vistas: set[str] = set()
        for est in runner.motor.estrategias:
            sid = est["strategy_id"]
            # Una vez por estrategia: las otras cuentas comparten la señal.
            if sid in vistas or est.get("cuenta"):
                continue
            vistas.add(sid)
            sdef = est.get("definition") or {}
            compiled = est.get("compiled") or {}
            entry = sdef.get("entry_logic") or {}
            root = entry.get("root_condition") or {}
            conds = root.get("conditions") or []
            if str(root.get("operator", "AND")).upper() != "AND" or len(conds) < 2:
                continue
            if not _en_ventana(compiled, momento):
                continue
            tf = entry.get("timeframe", "1m")
            cache: dict = {}
            cumple: list[bool] = []
            try:
                for c in conds:
                    serie = _evaluate_single_condition(c, frame, tf, stats, cache)
                    v = np.asarray(serie, dtype=bool)
                    cumple.append(bool(v[-1]) if len(v) else False)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[PREALERTA SIMPLE] %s / %s: fallo al evaluar: %s",
                               ticker, est.get("name"), exc)
                continue
            n = len(cumple)
            if sum(cumple) != n - 1:
                continue
            falta = etiqueta(conds[cumple.index(False)])

            clave = (ticker, sid)
            ultimo = self._ultimo.get(clave)
            ts = pd.Timestamp(momento)
            if ultimo is not None and (ts - ultimo) < pd.Timedelta(minutes=self.cada_min):
                continue
            if self._silenciada(clave, falta):
                continue
            self._ultimo[clave] = ts

            direccion = str(compiled.get("direction") or sdef.get("direction") or "shortonly")
            direccion = "Long" if direccion.lower().startswith("long") else "Short"
            eventos.append(Evento(
                tipo="entrada", ticker=ticker, strategy_id=sid,
                estrategia=est.get("name") or sid, momento=momento, precio=precio,
                direccion=direccion, estado="prealerta",
                motivo=f"Falta: {falta}", cuenta=None,
                riesgo_usd=est.get("riesgo_usd"),
            ))
        return eventos
