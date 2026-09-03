"""Motor de alertas: de un frame de velas a avisos de entrada y salida.

NO es un backtest. Es el mismo calculo del backtest aplicado a las velas que
llevamos hoy, en memoria, sin tocar la base de datos ni lanzar nada. Con un
punado de tickers son milisegundos por vela.

POR QUE REUTILIZA EL SIMULADOR EN VEZ DE LLEVAR SU PROPIO ESTADO. Saber si
sigues dentro exige seguir el stop estructural, los parciales, el limite horario
y las reentradas. Escribir eso aparte es garantizar que algun dia se separa del
backtest sin que nadie se entere. Aqui se llama a `simulate` sobre el frame
acumulado y el estado se DEDUCE de sus trades: la paridad sale por construccion.

LAS DOS TRAMPAS, que no son obvias:

1. `simulate` NUNCA deja una posicion abierta. Al llegar al final del array
   liquida lo que haya con motivo "EOD" — y "el final del array" es la ultima
   vela que le pasas, no el cierre de la sesion. Dandole el dia a medias, cada
   llamada dice "cerrado" aunque sigas dentro. Ese cierre es SINTETICO y hay que
   leerlo como "posicion viva", no como salida. Se distingue por el reloj: solo
   es un fin de dia real si la vela es la ultima de la ventana de la estrategia.

2. Una senal en la ultima vela todavia NO produce trade, porque la entrada es al
   `open` de la vela siguiente (`look_ahead_prevention`). Si el aviso esperase al
   trade, llegaria un minuto tarde — justo el minuto que hay que operar. Por eso
   la ENTRADA se avisa con la senal (validado en la Fase 1: cero divergencias) y
   el simulador se usa para el ESTADO y las SALIDAS.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

from app.services.portfolio_sim import (
    _structural_level, _sl_side_valid, simulate, tope_hibrido,
)
from app.services.strategy_engine import compile_strategy_def, translate_strategy

logger = logging.getLogger("btt.bot_alerts")

# Capital nominal del simulador. NO es el dinero de la cuenta: el riesgo por
# operacion lo fija el cuadro de mandos y aqui no se contabiliza nada. Se pone
# alto a proposito para que el tope de caja (`size = min(size, cash/precio)`)
# no recorte jamas el tamano; si recortara, el numero de acciones del aviso no
# seria el que pide la estrategia y no habria ninguna senal de que paso.
CAPITAL_NOMINAL = 1e9


@dataclass
class Evento:
    """Un aviso. `tipo` es 'entrada', 'piramide' o 'salida'.

    Los tres son ordenes que hay que meter a mano en el broker, por eso los tres
    avisan. La piramide es facil de olvidar: la entrada inicial de 1B son 2.038
    acciones, pero el backtest acaba con 2.508 porque anyade en una vela
    posterior. Sin ese aviso la posicion se queda corta respecto a la estrategia.
    """
    tipo: str
    ticker: str
    strategy_id: str
    estrategia: str
    momento: Any                    # timestamp de la vela que lo dispara
    precio: float                   # ultimo precio conocido (cierre de la vela)
    direccion: str                  # 'Long' | 'Short'
    # 'prealerta' mientras la vela se esta formando, 'alerta' al cerrar. Vale
    # para entradas Y para piramides: el anyadido tambien se decide al cierre,
    # asi que tambien se puede preavisar.
    estado: str = "alerta"
    # Entradas y piramides:
    acciones: Optional[float] = None
    # Solo en entradas:
    stop: Optional[float] = None
    distancia_stop: Optional[float] = None
    riesgo_usd: Optional[float] = None
    # Solo en salidas:
    motivo: Optional[str] = None
    entrada_idx: Optional[int] = None
    # Solo en piramides:
    nivel: Optional[int] = None
    accion_piramide: Optional[str] = None   # 'add' | 'reduce'
    posicion_total: Optional[float] = None

    def __str__(self) -> str:
        cab = f"[{self.tipo.upper()}] {self.ticker} · {self.estrategia}"
        acc = f"{self.acciones:,.0f}" if self.acciones is not None else "?"
        if self.tipo == "entrada":
            stop = f"{self.stop:.4f}" if self.stop is not None else "sin stop"
            return f"{cab} · {self.direccion} {acc} acc @ {self.precio:.4f} · stop {stop}"
        if self.tipo == "piramide":
            verbo = "AÑADIR" if self.accion_piramide == "add" else "REDUCIR"
            total = f"{self.posicion_total:,.0f}" if self.posicion_total is not None else "?"
            return f"{cab} · {verbo} {acc} acc @ {self.precio:.4f} · posicion queda en {total}"
        return f"{cab} · salida por {self.motivo} @ {self.precio:.4f}"


def _hard_stop(sdef: dict) -> dict:
    rm = sdef.get("risk_management") or {}
    return (rm.get("hard_stop") or {}) if rm.get("use_hard_stop") else {}


def _niveles_con_riesgo(niveles, riesgo_usd: Optional[float]):
    """Los niveles de piramide con la cantidad que diga el cuadro de mandos.

    `None` = no dicho: se deja lo que traiga la estrategia, que es como se ha
    comportado siempre. Con un valor, se fuerza `unit="usd"` porque lo que se
    teclea son dolares, no un porcentaje del equity.
    """
    if not niveles or not riesgo_usd or riesgo_usd <= 0:
        return niveles
    fuera = []
    for lv in niveles:
        n = dict(lv)
        n["unit"] = "usd"
        n["amount_usd"] = float(riesgo_usd)
        fuera.append(n)
    return fuera


def _kwargs_simulate(frame: pd.DataFrame, senales: dict, sdef: dict, riesgo_usd: float,
                     riesgo_piramide_usd: Optional[float] = None,
                     capital_usd: Optional[float] = None) -> dict:
    """Traduce frame + senales + estrategia a los argumentos de `simulate`.

    Los costes van todos a cero por decision de producto: el bot avisa, no
    contabiliza. Eso hace que el PnL que devuelva el simulador sea bruto — no se
    usa para nada, solo interesan las entradas, las salidas y sus motivos.
    """
    rm = sdef.get("risk_management") or {}
    hs = _hard_stop(sdef)
    ts = pd.to_datetime(frame["timestamp"]).values.astype("datetime64[ns]").astype(np.int64)

    return {
        "close": frame["close"].values.astype(np.float64),
        "open_": frame["open"].values.astype(np.float64),
        "high": frame["high"].values.astype(np.float64),
        "low": frame["low"].values.astype(np.float64),
        "entries": np.asarray(senales["entries"], dtype=bool),
        "exits": np.asarray(senales["exits"], dtype=bool),
        "direction": senales["direction"],
        "init_cash": CAPITAL_NOMINAL,
        "risk_r": float(riesgo_usd),
        "risk_type": "FIXED",          # el riesgo del cuadro de mandos manda
        "size_by_sl": bool(rm.get("size_by_sl", False)),
        # El hibrido tambien aqui: si el simulador dimensiona sin techo, el
        # estado que el motor DEDUCE de sus trades (piramides, salidas) seria el
        # de una posicion mas grande que la que se avisa.
        "hybrid_stop": bool(rm.get("hybrid_stop", False)),
        "hybrid_black_swan_pct": rm.get("hybrid_black_swan_pct"),
        "hybrid_max_loss_pct": rm.get("hybrid_max_loss_pct"),
        # EL CAPITAL DE VERDAD, no `init_cash`. Aqui `init_cash` es
        # CAPITAL_NOMINAL (1e9) para que el tope de caja no recorte el aviso; si
        # el techo hibrido se calculara sobre eso, no recortaria nunca y el
        # numero de acciones del aviso saldria sin topar.
        "hybrid_capital": capital_usd,
        "fees": 0.0,
        "slippage": 0.0,
        "locates_cost": 0.0,
        "max_locates": 0,
        "sl_stop": senales.get("sl_stop"),
        "sl_trail": senales.get("sl_trail", False),
        "tp_stop": senales.get("tp_stop"),
        "tp_time_limit": senales.get("tp_time_limit"),
        "trail_pct": senales.get("trail_pct"),
        "accumulate": senales.get("accept_reentries", False),
        "max_reentries": senales.get("max_reentries", -1),
        "partial_take_profits": senales.get("partial_take_profits"),
        # LOS NIVELES, con la cantidad del CUADRO DE MANDOS si se ha puesto.
        # El anyadido puede arriesgar algo distinto de la entrada, y hasta hoy
        # solo se podia fijar el de la entrada: el nivel usaba lo que dijera la
        # estrategia y no habia forma de cambiarlo sin editarla.
        #
        # Que SIGNIFICA ese numero depende del modo del nivel, igual que en la
        # entrada: por valor de mercado es capital a desplegar; por distancia al
        # stop es la perdida maxima.
        "pyramid_levels": _niveles_con_riesgo(senales.get("pyramid_levels"),
                                              riesgo_piramide_usd),
        "pyramid_sequential": senales.get("pyramid_sequential", False),
        "hs_type": hs.get("type"),
        "hs_value": hs.get("value"),
        "hs_operator": hs.get("operator", ">="),
        "hs_offset_pct": hs.get("offset_pct", 0.0),
        "hs_fallback_value": hs.get("fallback_value"),
        "hs_fallback_first": hs.get("fallback_first_entry", False),
        "hods": frame["hod"].values.astype(np.float64),
        "lods": frame["lod"].values.astype(np.float64),
        "pm_highs": frame["pm_high"].values.astype(np.float64),
        "pm_lows": frame["pm_low"].values.astype(np.float64),
        "prev_highs": frame["prev_high"].values.astype(np.float64),
        "prev_lows": frame["prev_low"].values.astype(np.float64),
        "timestamps": ts,
        "look_ahead_prevention": True,
    }


def es_fin_de_ventana(momento, ventana: dict | None) -> bool:
    """True si esa vela es la ULTIMA en la que la estrategia puede operar.

    Es lo que separa un cierre de fin de dia real del borde del frame. Sin esto
    el bot avisaria de una salida en cada vela, porque el simulador liquida
    siempre al final del array que le das.
    """
    fin = (ventana or {}).get("fin")
    if not fin:
        return False
    try:
        t = pd.Timestamp(momento)
        h, m = str(fin).split(":")[:2]
        return (t.hour, t.minute) >= (int(h), int(m))
    except (ValueError, TypeError):
        return False


def nivel_stop(sdef: dict, frame: pd.DataFrame, i: int, precio: float, es_largo: bool) -> Optional[float]:
    """Precio del stop en la barra `i`, con las MISMAS funciones del simulador.

    Devuelve None si la estrategia no lleva stop, o si el nivel cae del lado
    ganador de la entrada — que es el caso en que el simulador descarta la
    operacion entera (por ejemplo, un corto cuyo maximo previo ya se ha roto).
    Avisar de esa entrada seria avisar de algo que el backtest no opera.
    """
    hs = _hard_stop(sdef)
    tipo = hs.get("type")

    if tipo == "Market Structure (HOD/LOD)":
        nivel = _structural_level(
            hs.get("value"), i,
            frame["hod"].values.astype(np.float64),
            frame["lod"].values.astype(np.float64),
            frame["pm_high"].values.astype(np.float64),
            frame["pm_low"].values.astype(np.float64),
            frame["prev_high"].values.astype(np.float64),
            frame["prev_low"].values.astype(np.float64),
        )
        if nivel <= 0.0:
            # Mismo respaldo que el simulador: 5% cuando el nivel no se resuelve.
            nivel = precio * (0.95 if es_largo else 1.05)
        signo = 1.0 if hs.get("operator", ">=") in (">", ">=") else -1.0
        stop = nivel * (1.0 + signo * float(hs.get("offset_pct") or 0.0) / 100.0)
    else:
        # Porcentaje / importe fijo / ATR: el motor ya los dejo en `sl_stop`
        # como fraccion, y se aplican sobre el precio de entrada.
        return None

    return stop if _sl_side_valid(stop, precio, es_largo) else None


def _hibrido_de(rm: dict, est: dict) -> Optional[dict]:
    """Los tres numeros del techo hibrido, o None si no aplica.

    Los porcentajes vienen de la ESTRATEGIA (viajan con ella para que backtest y
    bot dimensionen igual) y el capital del CUADRO DE MANDOS (el bot no conoce
    la cuenta). Si falta cualquiera de los tres se devuelve None y se dimensiona
    por SL sin techo — no deberia pasar, porque `/watch` bloquea la activacion,
    pero inventarse un capital seria peor que quedarse sin techo.
    """
    if not rm.get("hybrid_stop"):
        return None
    capital = est.get("capital_usd")
    if not capital:
        return None
    return {
        "capital": capital,
        "black_swan_pct": rm.get("hybrid_black_swan_pct"),
        "max_loss_pct": rm.get("hybrid_max_loss_pct"),
    }


def calcular_acciones(riesgo_usd: float, precio: float, stop: Optional[float],
                      size_by_sl: bool, hibrido: Optional[dict] = None) -> Optional[float]:
    """Acciones del aviso. Sin redondear: 37,5 es una respuesta valida.

    Con `size_by_sl` el riesgo es la PERDIDA maxima y se divide por la distancia
    al stop en dolares. Sin el, el riesgo es capital a desplegar y se divide por
    el precio. Es la misma cuenta de `portfolio_sim` y de la calculadora de
    locates de la interfaz.

    `hibrido` (opcional) es `{"capital", "black_swan_pct", "max_loss_pct"}` y
    aplica el TECHO del stop hibrido: por SL, pero sin exponer mas de lo que se
    acepta perder ante un evento de cola. **Solo con `size_by_sl`** — sin el ya
    se va por valor de mercado y no hay nada que topar. Recorta, no anula.

    El capital NO sale de la estrategia sino del cuadro de mandos: el bot no
    conoce la cuenta real de Jaume, se la tiene que decir el.
    """
    if precio <= 0:
        return None
    if size_by_sl and stop is not None:
        distancia = abs(precio - stop)
        if distancia > 0:
            acciones = riesgo_usd / distancia
            if hibrido:
                tope = tope_hibrido(
                    float(hibrido.get("capital") or 0.0),
                    hibrido.get("black_swan_pct"),
                    hibrido.get("max_loss_pct"), precio)
                if tope is not None:
                    acciones = min(acciones, tope)
            return acciones
    return riesgo_usd / precio


@dataclass
class _EstadoPar:
    """Lo que el motor recuerda de un par (ticker, estrategia) durante el dia."""
    entradas_avisadas: set = field(default_factory=set)   # indices de vela ya avisados
    salidas_avisadas: set = field(default_factory=set)    # entry_idx de salidas ya avisadas
    piramides_avisadas: set = field(default_factory=set)  # (entry_idx, nivel, vela)


class MotorAlertas:
    """Evalua las estrategias vigiladas sobre los frames en vivo.

    Se le llama una vez por vela cerrada y por ticker. Devuelve solo lo NUEVO:
    lo que ya se aviso no se repite. El estado es del dia; al cambiar de dia se
    tira con `reiniciar()`.
    """

    def __init__(self, estrategias: list[dict]):
        """`estrategias` es lo que devuelve /api/bot-alerts/vigiladas."""
        self.estrategias = []
        for e in estrategias:
            sdef = e["definition"]
            self.estrategias.append({
                "strategy_id": e["strategy_id"],
                "name": e["name"],
                "riesgo_usd": float(e["riesgo_usd"]),
                # Del cuadro de mandos, no de la estrategia: el bot no conoce
                # la cuenta real. Sin capital, el stop hibrido no puede calcular
                # su techo — por eso `/watch` no deja activar una estrategia
                # hibrida sin rellenarlo.
                "capital_usd": e.get("capital_usd"),
                "riesgo_piramide_usd": e.get("riesgo_piramide_usd"),
                "definition": sdef,
                "ventana": e.get("ventana") or {},
                # Se compila UNA vez, no en cada vela: es lo caro del motor.
                "compiled": compile_strategy_def(sdef),
            })
        self._estado: dict[tuple[str, str], _EstadoPar] = {}

    def reiniciar(self) -> None:
        """Nuevo dia: se olvida todo lo avisado."""
        self._estado.clear()

    def _par(self, ticker: str, strategy_id: str) -> _EstadoPar:
        return self._estado.setdefault((ticker, strategy_id), _EstadoPar())

    def mirar_sin_marcar(
        self,
        ticker: str,
        frame: pd.DataFrame,
        daily_stats: dict | None = None,
    ) -> list[Evento]:
        """Que saldria con este frame, SIN dejar constancia de haberlo visto.

        Es lo que usan las prealertas: la vela en formacion puede cambiar en los
        ultimos segundos, asi que mirarla no puede marcar nada como avisado — si
        lo hiciera, la alerta de verdad (al cerrar la vela) se daria por ya dada
        y no llegaria nunca.

        Se hace con una COPIA del estado y se descarta: mas simple y mas seguro
        que intentar deshacer las marcas despues.
        """
        import copy
        guardado = self._estado
        self._estado = copy.deepcopy(guardado)
        try:
            eventos = self.procesar_vela(ticker, frame, daily_stats)
        finally:
            self._estado = guardado
        for ev in eventos:
            ev.estado = "prealerta"
        # Una salida a medio formar no se avisa: el stop puede tocarse y
        # recuperarse dentro del mismo minuto, y no hay nada que ejecutar por
        # adelantado. Solo interesan las ordenes de abrir o anyadir.
        return [e for e in eventos if e.tipo in ("entrada", "piramide")]

    def procesar_vela(
        self,
        ticker: str,
        frame: pd.DataFrame,
        daily_stats: dict | None = None,
    ) -> list[Evento]:
        """Eventos NUEVOS tras cerrar la ultima vela de `frame`."""
        eventos: list[Evento] = []
        n = len(frame)
        if n < 2:
            # `simulate` necesita al menos dos barras: con una sola nunca entra
            # (solo se admiten entradas con i < n-1) y con cero revienta.
            return eventos

        for est in self.estrategias:
            try:
                eventos.extend(self._procesar_estrategia(ticker, frame, daily_stats or {}, est))
            except Exception as exc:  # noqa: BLE001
                # Una estrategia que falla no puede callar a las demas: el bot
                # sigue vigilando el resto y el fallo queda en el log.
                logger.warning("[BOT] %s / %s fallo al evaluar: %s", ticker, est["name"], exc)
        return eventos

    @staticmethod
    def _quedan_entradas(trades: list[dict], senales: dict) -> bool:
        """Si a la estrategia le queda cupo de entradas para hoy.

        SIN ESTO EL BOT SE DESBOCA. Agotado el cupo, el simulador deja de entrar
        y por tanto ya no hay posicion viva — la comprobacion de "estoy dentro"
        da paso libre y la senal, que sigue encendiendose, produce un aviso tras
        otro. Medido en RDAC el 19-ago-2026: 25 avisos donde el backtest opera 3.

        Copia la condicion de portfolio_sim.py:970-977, que compara contra las
        entradas YA hechas (los parciales comparten `entry_idx`, asi que hay que
        contar indices distintos y no filas de trade).
        """
        hechas = len({int(t.get("entry_idx", -1)) for t in trades})
        max_re = int(senales.get("max_reentries", -1))
        if max_re >= 0:
            return hechas <= max_re
        if not senales.get("accept_reentries", False):
            return hechas == 0
        return True

    def _procesar_estrategia(
        self, ticker: str, frame: pd.DataFrame, daily_stats: dict, est: dict,
    ) -> list[Evento]:
        eventos: list[Evento] = []
        n = len(frame)
        i = n - 1
        sdef = est["definition"]
        estado = self._par(ticker, est["strategy_id"])

        senales = translate_strategy(frame, sdef, daily_stats, compiled=est["compiled"])
        res = simulate(**_kwargs_simulate(frame, senales, sdef, est["riesgo_usd"],
                                          est.get("riesgo_piramide_usd"),
                                          est.get("capital_usd")))
        trades = res.get("trades") or []

        es_largo = str(senales["direction"]).lower().startswith("long")
        direccion = "Long" if es_largo else "Short"
        momento = frame["timestamp"].iloc[i]
        precio = float(frame["close"].iloc[i])
        fin_ventana = es_fin_de_ventana(momento, est["ventana"])

        # ── PIRAMIDES ───────────────────────────────────────────────────────
        # Cada anyadido o reduccion es una orden aparte que hay que meter. Van
        # ANTES que las salidas porque un trade que cierra en esta misma vela
        # todavia arrastra sus ejecuciones de piramide, y perderlas dejaria la
        # posicion descuadrada respecto a la estrategia.
        for t in trades:
            entry_idx = int(t.get("entry_idx", -1))
            for ex in (t.get("pyr_executions") or []):
                clave = (entry_idx, int(ex.get("level", 0)), int(ex.get("idx", -1)))
                if clave in estado.piramides_avisadas:
                    continue
                estado.piramides_avisadas.add(clave)
                eventos.append(Evento(
                    tipo="piramide", ticker=ticker,
                    strategy_id=est["strategy_id"], estrategia=est["name"],
                    momento=momento, precio=float(ex.get("price", precio)),
                    direccion=direccion, acciones=float(ex.get("size", 0.0)),
                    nivel=int(ex.get("level", 0)),
                    accion_piramide=str(ex.get("kind") or "add"),
                    posicion_total=float(ex.get("position_size", 0.0)),
                    entrada_idx=entry_idx,
                ))

        # ── SALIDAS ─────────────────────────────────────────────────────────
        # Un trade cuenta como cerrado de verdad salvo que sea el cierre
        # sintetico del borde del frame (motivo EOD en la ultima vela, sin haber
        # llegado al final de la ventana operativa).
        for t in trades:
            entry_idx = int(t.get("entry_idx", -1))
            if entry_idx in estado.salidas_avisadas:
                continue
            sintetico = (
                t.get("exit_reason") == "EOD"
                and int(t.get("exit_idx", -1)) >= i
                and not fin_ventana
            )
            if sintetico:
                continue
            estado.salidas_avisadas.add(entry_idx)
            eventos.append(Evento(
                tipo="salida", ticker=ticker,
                strategy_id=est["strategy_id"], estrategia=est["name"],
                momento=momento, precio=float(t.get("exit_price", precio)),
                direccion=direccion, motivo=str(t.get("exit_reason") or "?"),
                entrada_idx=entry_idx,
            ))

        # ── ENTRADA ─────────────────────────────────────────────────────────
        # Se avisa con la SENAL, no con el trade: el trade no existe hasta la
        # vela siguiente y el aviso llegaria tarde. Se exige flanco (apagada
        # antes, encendida ahora), que es lo que el simulador convierte en
        # operacion; una senal que lleva encendida varias velas no es una
        # entrada nueva.
        entradas = np.asarray(senales["entries"], dtype=bool)
        if i not in estado.entradas_avisadas and entradas[i] and not entradas[i - 1]:
            # Ya dentro? El ultimo trade sintetico ES la posicion viva.
            dentro = any(
                t.get("exit_reason") == "EOD" and int(t.get("exit_idx", -1)) >= i
                for t in trades
            )
            if not dentro and not fin_ventana and self._quedan_entradas(trades, senales):
                stop = nivel_stop(sdef, frame, i, precio, es_largo)
                hs_estructural = _hard_stop(sdef).get("type") == "Market Structure (HOD/LOD)"
                # Con stop estructural, un nivel del lado ganador anula la
                # operacion en el simulador. Avisar seria avisar de algo que el
                # backtest no opera.
                if not (hs_estructural and stop is None):
                    estado.entradas_avisadas.add(i)
                    rm = sdef.get("risk_management") or {}
                    acciones = calcular_acciones(
                        est["riesgo_usd"], precio, stop, bool(rm.get("size_by_sl", False)),
                        hibrido=_hibrido_de(rm, est),
                    )
                    eventos.append(Evento(
                        tipo="entrada", ticker=ticker,
                        strategy_id=est["strategy_id"], estrategia=est["name"],
                        momento=momento, precio=precio, direccion=direccion,
                        acciones=acciones, stop=stop,
                        distancia_stop=abs(precio - stop) if stop is not None else None,
                        riesgo_usd=est["riesgo_usd"],
                    ))

        return eventos
