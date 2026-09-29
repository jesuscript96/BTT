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

AÑADIDOS (29-sep-2026, Jaume: «prefiero que avise añadido por condiciones»).
Con posición viva en ESA estrategia, en vez de la entrada se miran sus niveles
de piramidación: el mismo «todas menos una» sobre el `root_condition` de cada
nivel que AÑADE. Se saltan los que no tienen condiciones que partir: los de
solo recorrido (dependen del precio de entrada, que aquí no se conoce), los
caminos por pasos y los que ya se han disparado sus `times` veces en la
posición actual. Mismo freno y mismo silencio que la entrada, por nivel. La
posición se mira POR ESTRATEGIA: que otra estrategia esté dentro del ticker ya
no calla la prealerta de entrada de esta.

POR DISTANCIA (29-sep-2026, Jaume: «cuando una de las condiciones esté a X % de
distancia de cumplirse»). `PrealertaDistancia`, modo `distancia`. Cada segundo,
con la vela EN CURSO que el proceso de prealertas ya monta con los agregados
`A.` (el precio en vivo: ningún socket nuevo), se evalúan las mismas
condiciones. Avisa si las que no son de precio se cumplen TODAS y, de las de
precio contra un nivel, falta como mucho UNA y está a menos del X % (por
defecto 2 %). Si ya se cumplen todas, avisa «se cumple ahora, pendiente del
cierre». Lo que no se puede medir en % (tiempo, sí/no, cruces, otro
timeframe) tiene que estar cumplido. Mismo recorrido, freno y silencio que el
modo simple.

CÓMO EVALÚA. Con `_evaluate_single_condition`, la MISMA función con la que el
motor evalúa cada condición dentro de `translate_strategy`, sobre el frame que
el runner ya tiene (`build_market_frame` del día entero). Solo para raíces AND:
con OR «falta una» no significa nada.

NO TOCA ESTADO: ni el del motor ni el del runner. Lo único que guarda es el
freno (último aviso por ticker y estrategia), que se reinicia con el día.
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from app.services.bot_alerts_engine import Evento
from app.services.market_frame import build_market_frame
from app.services.strategy_engine import _compute_from_config, _evaluate_single_condition

logger = logging.getLogger("btt.bot_alerts.prealerta_simple")

_OPS = {
    "GREATER_THAN": ">", "LESS_THAN": "<",
    "GREATER_THAN_OR_EQUAL": ">=", "LESS_THAN_OR_EQUAL": "<=",
    "EQUAL": "=", "CROSSES_ABOVE": "cruza arriba", "CROSSES_BELOW": "cruza abajo",
}
_POSICION = {"below": "bajo", "above": "sobre"}

# Nombres del PRECIO como fuente de una condición: son las que se pueden medir en
# % contra un nivel. Todo lo demás (tiempo, volumen, patrones) no tiene distancia.
_PRECIOS = {"close", "bar close", "price", "last", "last price", "precio"}
_COMPARA = {"GREATER_THAN", "LESS_THAN", "GREATER_THAN_OR_EQUAL", "LESS_THAN_OR_EQUAL"}


def _nombre(cfg) -> str:
    """«EMA(10)», «VWAP», «20»: el indicador con su periodo, o el número."""
    if isinstance(cfg, dict):
        n = cfg.get("name", "?")
        per = cfg.get("period")
        return f"{n}({per})" if per else str(n)
    return str(cfg)


def etiqueta(cond: dict) -> str:
    """Nombre legible de una condición, como la ve el usuario en el constructor.

    29-sep-2026: salían mal dos casos. La distancia a un nivel se escribía
    «Close DISTANCE_LT None» y el objetivo perdía el periodo («Close > EMA»)."""
    src = _nombre(cond.get("source") or {})
    if cond.get("type") == "price_level_distance":
        comp = str(cond.get("comparator", "")).upper().replace("DISTANCE_", "")
        signo = ">" if comp in ("GT", "GREATER_THAN") else "<"
        pos = _POSICION.get(cond.get("position") or "", "de")
        return f"{src} a {signo}{cond.get('value_pct')} % {pos} {_nombre(cond.get('level') or {})}"
    op = _OPS.get(cond.get("comparator", ""), cond.get("comparator", "?"))
    return f"{src} {op} {_nombre(cond.get('target'))}"


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


def _ultimo(serie) -> Optional[float]:
    v = np.asarray(serie, dtype=float)
    if not len(v) or not np.isfinite(v[-1]):
        return None
    return float(v[-1])


def distancia_pct(cond: dict, frame, tf: str, stats: dict, cache: dict) -> Optional[float]:
    """Cuánto le falta al PRECIO para cumplir la condición, en % del nivel.

    None si la condición no se puede medir así: la fuente no es el precio, es
    un cruce, va en otro timeframe o el nivel no existe todavía."""
    if (cond.get("timeframe") or tf or "1m") != "1m":
        return None
    src_cfg = cond.get("source") or {}
    if isinstance(src_cfg, str):
        src_cfg = {"name": src_cfg}
    if str(src_cfg.get("name", "")).strip().lower() not in _PRECIOS or int(src_cfg.get("offset") or 0) != 0:
        return None
    precio = _ultimo(frame["close"])
    c1m = cache.setdefault("1m", {})
    try:
        if cond.get("type") == "indicator_comparison":
            if cond.get("comparator") not in _COMPARA:
                return None
            tgt = cond.get("target")
            nivel = float(tgt) if isinstance(tgt, (int, float)) else _ultimo(
                _compute_from_config(tgt or {}, frame, stats, c1m))
            if precio is None or not nivel:
                return None
            return abs(precio - nivel) / abs(nivel) * 100
        if cond.get("type") == "price_level_distance":
            comp = str(cond.get("comparator", "")).upper().replace("DISTANCE_", "")
            if comp not in ("LT", "LESS_THAN"):
                return None
            lvl = cond.get("level") or {}
            nivel = _ultimo(_compute_from_config({"name": lvl} if isinstance(lvl, str) else lvl,
                                                 frame, stats, c1m))
            if precio is None or not nivel:
                return None
            v = float(cond.get("value_pct") or 0.0) / 100.0
            pos = cond.get("position") or "any"
            bajo = nivel * (1 - v) if pos in ("below", "any") else nivel
            alto = nivel * (1 + v) if pos in ("above", "any") else nivel
            fuera = (bajo - precio) if precio < bajo else (precio - alto) if precio > alto else 0.0
            return fuera / abs(nivel) * 100
    except Exception:  # noqa: BLE001
        return None
    return None


def _cumple(conds, frame, tf, stats, cache) -> list[bool]:
    out = []
    for c in conds:
        v = np.asarray(_evaluate_single_condition(c, frame, tf, stats, cache), dtype=bool)
        out.append(bool(v[-1]) if len(v) else False)
    return out


class PrealertaSimple:
    """Guarda solo el freno. Una instancia por proceso."""

    VIA = "simple"
    MIN_CONDICIONES = 2

    def __init__(self, cada_min: int = 10, max_seguidas: int = 3):
        self.cada_min = int(cada_min)
        # SILENCIO (28-sep-2026, Jaume): tras `max_seguidas` prealertas seguidas del mismo ticker y estrategia
        # con la MISMA condicion pendiente y sin llegar a entrar, se calla hasta que cambie la condicion que
        # falta (o entre). 0 = sin silencio.
        self.max_seguidas = int(max_seguidas)
        self._ultimo: dict[tuple, pd.Timestamp] = {}
        self._racha: dict[tuple, tuple[str, int]] = {}   # (condicion que falta, avisos seguidos)

    def reiniciar(self) -> None:
        self._ultimo.clear()
        self._racha.clear()

    def soltar(self, ticker: str) -> None:
        for k in [k for k in self._ultimo if k[0] == ticker]:
            self._ultimo.pop(k, None)
        for k in [k for k in self._racha if k[0] == ticker]:
            self._racha.pop(k, None)

    def _silenciada(self, clave: tuple, falta: str) -> bool:
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

    # ── el juez: ¿esta raíz merece prealerta? ─────────────────────────────
    def _juzgar(self, root: dict, frame, tf: str, stats: dict, ticker: str, nombre: str):
        """(motivo, clave de la racha) o None. Modo simple: falta exactamente una."""
        falta = self._falta_una(root, frame, tf, stats, ticker, nombre)
        return None if falta is None else (f"Falta: {falta}", falta)

    def evaluar(self, runner, ticker: str) -> list[Evento]:
        """Los avisos «falta una» del ticker con su última vela cerrada."""
        velas = getattr(runner, "_velas", {}).get(ticker) or []
        if len(velas) < 2:
            return []
        return self._recorrer(runner, ticker, velas)

    def _recorrer(self, runner, ticker: str, velas: list) -> list[Evento]:
        stats = getattr(runner, "_stats", {}).get(ticker, {}) or {}
        try:
            df = pd.DataFrame(velas)
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            frame = build_market_frame(df, ticker, stats)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[PREALERTA %s] %s: no se pudo montar el frame: %s",
                           self.VIA.upper(), ticker, exc)
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
            # Un añadido es una entrada: con la ventana cerrada, tampoco.
            if not _en_ventana(compiled, momento):
                continue
            direccion = str(compiled.get("direction") or sdef.get("direction") or "shortonly")
            direccion = "Long" if direccion.lower().startswith("long") else "Short"
            nombre = est.get("name") or sid
            estado = self._estado_par(runner, ticker, sid)

            if estado is None or len(estado.entradas_avisadas) <= len(estado.salidas_avisadas):
                # FUERA: la entrada.
                entry = sdef.get("entry_logic") or {}
                juicio = self._juzgar(entry.get("root_condition") or {}, frame,
                                      entry.get("timeframe", "1m"), stats, ticker, nombre)
                if juicio is None or not self._pasa_freno((ticker, sid), momento, juicio[1]):
                    continue
                eventos.append(Evento(
                    tipo="entrada", ticker=ticker, strategy_id=sid,
                    estrategia=nombre, momento=momento, precio=precio,
                    direccion=direccion, estado="prealerta",
                    motivo=juicio[0], cuenta=None,
                    riesgo_usd=est.get("riesgo_usd"),
                ))
                continue

            # DENTRO: los niveles que añaden por condiciones.
            pyr = sdef.get("pyramiding") or {}
            tf = pyr.get("timeframe", "1m")
            for idx, lv in enumerate(pyr.get("levels") or []):
                if str(lv.get("action", "add")).lower() != "add" or lv.get("steps") is not None:
                    continue
                if str(lv.get("trigger", "conditions")).lower() in ("move", "recorrido"):
                    continue
                if self._disparos(estado, idx) >= int(lv.get("times") or 1):
                    continue
                juicio = self._juzgar(lv.get("root_condition") or {}, frame, tf, stats, ticker, nombre)
                if juicio is None or not self._pasa_freno((ticker, sid, "pyr", idx), momento, juicio[1]):
                    continue
                eventos.append(Evento(
                    tipo="piramide", ticker=ticker, strategy_id=sid,
                    estrategia=nombre, momento=momento, precio=precio,
                    direccion=direccion, estado="prealerta",
                    motivo=juicio[0], cuenta=None,
                    riesgo_usd=est.get("riesgo_usd"),
                    # Base 1, como las ejecuciones del simulador (`portfolio_sim`:
                    # «level: lv_idx + 1») y los avisos de añadido de verdad.
                    nivel=idx + 1, accion_piramide="add",
                ))
        return eventos

    # ── piezas ────────────────────────────────────────────────────────────
    @staticmethod
    def _estado_par(runner, ticker: str, sid: str):
        """Lo que el motor recuerda de (ticker, estrategia), o None."""
        try:
            return runner.motor._estado.get((ticker, sid))
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _disparos(estado, idx: int) -> int:
        """Añadidos ya avisados del nivel `idx` (índice desde 0 en la definición)
        en la posición ACTUAL (desde la última entrada avisada).

        La clave es (entry_idx, nivel, vela[, kind, rung]) y el NIVEL VA EN BASE 1:
        el simulador lo numera `lv_idx + 1`. El 29-sep se comparaba con el índice
        desde 0 y el añadido hecho no contaba: BKYI añadió a las 11:21 (times=1) y
        siguió prealertando el añadido hasta el cierre. Los cierres de lote llevan
        kind y no cuentan."""
        desde = getattr(estado, "idx_ultima_entrada_avisada", -1)
        n = 0
        for k in getattr(estado, "piramides_avisadas", ()) or ():
            if len(k) == 3 and int(k[1]) == idx + 1 and int(k[0]) >= desde:
                n += 1
        return n

    def _falta_una(self, root: dict, frame, tf: str, stats: dict, ticker: str, nombre: str):
        """La etiqueta de la ÚNICA condición que falta, o None si no está a una.
        Solo raíces AND con dos o más condiciones: con OR «falta una» no significa nada."""
        conds = root.get("conditions") or []
        if str(root.get("operator", "AND")).upper() != "AND" or len(conds) < 2:
            return None
        try:
            cumple = _cumple(conds, frame, tf, stats, {})
        except Exception as exc:  # noqa: BLE001
            logger.warning("[PREALERTA SIMPLE] %s / %s: fallo al evaluar: %s", ticker, nombre, exc)
            return None
        if sum(cumple) != len(cumple) - 1:
            return None
        return etiqueta(conds[cumple.index(False)])

    def _pasa_freno(self, clave: tuple, momento, falta: str) -> bool:
        """Freno de `cada_min` y silencio por racha. Si pasa, apunta el aviso."""
        ts = pd.Timestamp(momento)
        ultimo = self._ultimo.get(clave)
        if ultimo is not None and (ts - ultimo) < pd.Timedelta(minutes=self.cada_min):
            return False
        if self._silenciada(clave, falta):
            return False
        self._ultimo[clave] = ts
        return True


class PrealertaDistancia(PrealertaSimple):
    """Modo `distancia`: con el precio EN VIVO, la condición de precio que falta
    tiene que estar a menos de `umbral_pct` % (ver el docstring del módulo)."""

    VIA = "distancia"

    def __init__(self, cada_min: int = 10, max_seguidas: int = 3, umbral_pct: float = 2.0):
        super().__init__(cada_min=cada_min, max_seguidas=max_seguidas)
        self.umbral_pct = float(umbral_pct)

    def evaluar_vivo(self, runner, ticker: str, vela_en_curso: dict) -> list[Evento]:
        """Las velas cerradas del runner + la vela que se está formando (su cierre
        es el precio en vivo del último agregado)."""
        velas = getattr(runner, "_velas", {}).get(ticker) or []
        if len(velas) < 1:
            return []
        return self._recorrer(runner, ticker, list(velas) + [vela_en_curso])

    def _juzgar(self, root: dict, frame, tf: str, stats: dict, ticker: str, nombre: str):
        conds = root.get("conditions") or []
        if str(root.get("operator", "AND")).upper() != "AND" or not conds:
            return None
        cache: dict = {}
        try:
            cumple = _cumple(conds, frame, tf, stats, cache)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[PREALERTA DISTANCIA] %s / %s: fallo al evaluar: %s", ticker, nombre, exc)
            return None
        pendientes = [c for c, ok in zip(conds, cumple) if not ok]
        if not pendientes:
            return ("Se cumple ahora · pendiente del cierre de la vela", "·ahora·")
        if len(pendientes) > 1:
            return None
        c = pendientes[0]
        d = distancia_pct(c, frame, tf, stats, cache)
        if d is None or d > self.umbral_pct:
            return None
        nombre_c = etiqueta(c)
        return (f"Falta: {nombre_c} — a {d:.1f} %", nombre_c)
