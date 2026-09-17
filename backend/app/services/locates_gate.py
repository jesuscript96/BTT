"""Puerta de entrada por EV: ¿compensa pagar el locate de ESTE trade?

Es la cuenta del `/evf` del bot de alertas, metida en el backtest y hecha trade
a trade con el precio de locate sorteado de ese ticker-dia:

    fade necesario (%) = coste REAL del locate por accion / precio x 100
    compensa           <=> EV (%) > fade necesario (%)

con el coste real por accion = paquetes ENTEROS x precio del paquete / n.

QUE EV SE MIRA: EL «EV EN SOMBRA»
---------------------------------
El EV rodante sale de las senales de la estrategia SIN puerta (una primera
pasada del backtest), cerradas ANTES del instante de la entrada que se esta
decidiendo: es el edge de la estrategia, no el de lo que se ha ejecutado. Es lo
que Jaume da hoy a mano al `/evf`. La alternativa —EV de lo ejecutado— se
muerde la cola: si la puerta rechaza, no entra informacion nueva y el EV se
congela; es la que tendra en vivo y queda como variante futura.

Unidades: EV y fade en % del PRECIO (lo que se mueve la accion a favor), sobre
cortos —que son los que pagan locate— y BRUTO de locates, que es justo lo que
se esta decidiendo si compensa pagar. NO es `return_pct` (que va sobre capital
en riesgo) ni R.

COSTE MARGINAL, NO TOTAL
------------------------
El locate se alquila una vez por ticker-dia sobre el maximo en corto del dia,
y las reentradas lo reutilizan. Asi que lo que cuesta ESTA entrada son los
paquetes de MAS que hacen falta respecto a lo ya alquilado hoy: la reentrada
que cabe en lo alquilado pasa gratis; el anadido que se sale paga solo lo de
mas.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

NS_POR_DIA = 86_400_000_000_000

# ── EV FIJO, completo o POR RANGO DE PRECIO (Jaume, 17-sep-2026) ──────────
# La puerta puede enfrentar el fade a un EV FIJO en vez de al rodante: el que
# Jaume mide en IS para ver que tal va en OOS. Y ese EV fijo puede ser uno
# solo («completo») o uno por tramo de PRECIO de entrada («por rango»): una
# accion de 0,40 $ no se mueve como una de 8 $. UNA SOLA DEFINICION para el
# backtest, el portfolio en crudo, el cuadro de mandos y el /evf del bot: si
# el tramo se mira en un sitio distinto de otro, el veredicto de la app y el
# del bot se separan sin que nada avise.
RANGOS_PRECIO_EV: tuple[tuple[float, Optional[float]], ...] = (
    (0.0, 0.5), (0.5, 1.0), (1.0, 3.0), (3.0, 5.0), (5.0, 10.0), (10.0, None),
)


def rangos_ev_normalizados(rangos) -> list[dict]:
    """[{lo, hi, ev_pct}] limpio y ordenado por `lo`. `hi` None = sin techo.
    Se descarta lo que no sea un tramo con numeros; un tramo sin EV (None o
    <= 0) se conserva con ev_pct None para que quien lo mire sepa que no hay."""
    out: list[dict] = []
    for r in rangos or []:
        if not isinstance(r, dict):
            continue
        try:
            lo = float(r.get("lo", 0.0) or 0.0)
            hi_raw = r.get("hi")
            hi = float(hi_raw) if hi_raw not in (None, "") else None
            ev_raw = r.get("ev_pct")
            ev = float(ev_raw) if ev_raw not in (None, "") else None
        except (TypeError, ValueError):
            continue
        if hi is not None and hi <= lo:
            continue
        if ev is not None and ev <= 0:
            ev = None
        out.append({"lo": lo, "hi": hi, "ev_pct": ev})
    out.sort(key=lambda r: r["lo"])
    return out


def ev_fijo_para_precio(ev_fijo_pct: float, ev_rangos, precio: float) -> tuple[float, str]:
    """El EV fijo que se enfrenta a un corto que entra a `precio`.

    Con tramos: el del tramo que contiene el precio (lo <= precio < hi; el
    ultimo sin techo) si tiene EV; si el precio no cae en ninguno o el tramo
    no tiene EV, el completo. Devuelve (ev, origen) con origen "rango" o
    "completo", para poder ensenar de donde salio el veredicto."""
    p = float(precio or 0.0)
    for r in rangos_ev_normalizados(ev_rangos):
        if r["ev_pct"] is None:
            continue
        if p >= r["lo"] and (r["hi"] is None or p < r["hi"]):
            return float(r["ev_pct"]), "rango"
    return float(ev_fijo_pct or 0.0), "completo"


@dataclass
class ConfigPuerta:
    """Lo que la pantalla decide; ver el `?` de cada campo en BacktestPanel."""
    ventana: int = 30                # cuantos trades o cuantos dias mirar (0 = todo)
    por: str = "trades"              # "trades" | "dias"
    ev_defecto_pct: float = 2.0      # EV que se asume mientras no hay historia
    min_trades: int = 10             # por debajo de esto se usa el defecto
    # 17-sep: modo "fijo" = SIEMPRE se compara `ev_fijo_pct` (o el EV del tramo
    # de precio de la entrada, si `ev_rangos` lo trae) con el fade; la sombra no
    # se mira. "rodante" = lo de siempre.
    modo: str = "rodante"            # "rodante" | "fijo"
    ev_fijo_pct: float = 0.0
    ev_rangos: list = field(default_factory=list)   # [{lo, hi, ev_pct}]
    # Sombra: senales de la pasada SIN puerta. Ordenadas por instante de cierre.
    sombra_cierre_ns: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    sombra_move_pct: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))


def fade_necesario_pct(precio: float, n_acciones: float, paquetes: int, precio_paquete: float) -> float:
    """% que tiene que moverse el precio a favor solo para pagar el locate."""
    if precio <= 0 or n_acciones <= 0 or paquetes <= 0 or precio_paquete <= 0:
        return 0.0
    coste_real_por_accion = paquetes * precio_paquete / n_acciones
    return coste_real_por_accion / precio * 100.0


def paquetes_marginales(max_corto_hoy: float, size_nueva: float) -> int:
    """Paquetes de 100 de MAS que exige esta entrada respecto a lo ya alquilado."""
    antes = math.ceil(max(0.0, max_corto_hoy) / 100.0)
    despues = math.ceil(max(max_corto_hoy, size_nueva) / 100.0)
    return max(0, despues - antes)


def ev_rodante_pct(cfg: ConfigPuerta, ahora_ns: int) -> tuple[float, int, bool]:
    """EV en sombra a fecha de `ahora_ns`. Devuelve (ev, n_usados, es_defecto).

    Solo entran senales cerradas ESTRICTAMENTE antes del instante: mirar una que
    cierra despues seria mirar el futuro.
    """
    cierres = cfg.sombra_cierre_ns
    if cierres.size == 0:
        return float(cfg.ev_defecto_pct), 0, True
    fin = int(np.searchsorted(cierres, ahora_ns, side="left"))   # cerradas antes
    if int(cfg.ventana) <= 0:
        # Ventana 0 = TODO el historico cerrado antes (media que se va
        # ampliando). 17-sep: con 30 trades el EV rodante tiene un error tipico
        # mayor que el propio EV y la puerta rechaza por ruido.
        ini = 0
    elif cfg.por == "dias":
        ini = int(np.searchsorted(cierres, ahora_ns - int(cfg.ventana) * NS_POR_DIA, side="left"))
    else:
        ini = max(0, fin - int(cfg.ventana))
    n = fin - ini
    if n < max(1, int(cfg.min_trades)):
        return float(cfg.ev_defecto_pct), n, True
    return float(cfg.sombra_move_pct[ini:fin].mean()), n, False


def evaluar(
    cfg: ConfigPuerta,
    ahora_ns: int,
    precio: float,
    size_nueva: float,
    max_corto_hoy: float,
    precio_paquete: float,
) -> dict:
    """Veredicto para UNA entrada en corto. `entra` es lo unico que mira el motor;
    el resto se guarda para poder explicar despues por que."""
    paq = paquetes_marginales(max_corto_hoy, size_nueva)
    fade = fade_necesario_pct(precio, size_nueva, paq, precio_paquete)
    if cfg.modo == "fijo":
        ev, origen = ev_fijo_para_precio(cfg.ev_fijo_pct, cfg.ev_rangos, precio)
        n, defecto = 0, False
    else:
        ev, n, defecto = ev_rodante_pct(cfg, ahora_ns)
        origen = "rodante"
    return {
        "entra": bool(ev > fade),
        "ev_pct": round(ev, 4),
        "fade_pct": round(fade, 4),
        "margen_pct": round(ev - fade, 4),
        "paquetes": int(paq),
        "coste": round(paq * precio_paquete, 4),
        "n_ev": int(n),
        "ev_por_defecto": bool(defecto),
        "ev_origen": origen,
    }


def movimiento_pct(t: dict) -> Optional[float]:
    """Lo que se movio la accion A FAVOR en un trade, en % del precio de
    entrada, bruto (antes de comisiones y de locates). UNA definicion para
    el EV en sombra del backtest, el del portfolio en crudo y el «EV por
    precio» de Charts (el frontend la calca).

    Se mide por el PnL sobre el nocional — (pnl + comisiones) / (precio medio
    x acciones) — y NO por el precio de la ULTIMA salida: los trades que
    llegan aqui vienen agrupados (parciales, quitas de piramide, SL de lote
    en una sola fila) y `exit_price` es solo el de la ultima pierna. Con un
    take profit parcial a buen precio y el resto cerrado a EOD peor, el
    precio de la ultima pierna decia «negativo» en trades que ganaban dinero;
    medido el 17-sep: la estrategia entera daba EV negativo siendo ganadora.
    Es exactamente la magnitud que se compara con el fade: el fade es el
    coste del locate sobre ese mismo nocional. Sin pnl/size (registros
    viejos o a mano) cae al precio de salida, como antes.
    """
    ent = float(t.get("avg_entry_price") or t.get("entry_price") or 0.0)
    if ent <= 0:
        return None
    size = float(t.get("size") or 0.0)
    pnl = t.get("pnl")
    if size > 0 and pnl is not None:
        bruto = float(pnl) + float(t.get("fees") or 0.0)
        return bruto / (ent * size) * 100.0
    sal = float(t.get("exit_price") or 0.0)
    if sal <= 0:
        return None
    largo = str(t.get("direction", "")).lower().startswith("l")
    return ((sal - ent) if largo else (ent - sal)) / ent * 100.0


def sombra_desde_trades(trades: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Arrays de sombra a partir de los trades de la pasada SIN puerta.

    Solo cortos. El movimiento es `movimiento_pct` (% del precio, bruto, por
    el PnL sobre el nocional). Ordenados por cierre para que `searchsorted`
    funcione.
    """
    cierres, moves = [], []
    for t in trades:
        if str(t.get("direction", "")).lower().startswith("l"):
            continue
        ex = t.get("exit_time_epoch")
        mv = movimiento_pct(t)
        if mv is None or ex is None:
            continue
        cierres.append(int(ex) * 1_000_000_000)
        moves.append(mv)
    if not cierres:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.float64)
    orden = np.argsort(np.asarray(cierres, dtype=np.int64), kind="stable")
    return (np.asarray(cierres, dtype=np.int64)[orden],
            np.asarray(moves, dtype=np.float64)[orden])
