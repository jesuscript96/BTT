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

import numpy as np

NS_POR_DIA = 86_400_000_000_000


@dataclass
class ConfigPuerta:
    """Lo que la pantalla decide; ver el `?` de cada campo en BacktestPanel."""
    ventana: int = 30                # cuantos trades o cuantos dias mirar
    por: str = "trades"              # "trades" | "dias"
    ev_defecto_pct: float = 2.0      # EV que se asume mientras no hay historia
    min_trades: int = 10             # por debajo de esto se usa el defecto
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
    if cfg.por == "dias":
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
    ev, n, defecto = ev_rodante_pct(cfg, ahora_ns)
    return {
        "entra": bool(ev > fade),
        "ev_pct": round(ev, 4),
        "fade_pct": round(fade, 4),
        "margen_pct": round(ev - fade, 4),
        "paquetes": int(paq),
        "coste": round(paq * precio_paquete, 4),
        "n_ev": int(n),
        "ev_por_defecto": bool(defecto),
    }


def sombra_desde_trades(trades: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Arrays de sombra a partir de los trades de la pasada SIN puerta.

    Solo cortos. El movimiento es en % del precio, bruto: (entrada - salida) /
    entrada, con el precio MEDIO de la posicion (con piramide es el que manda).
    Ordenados por cierre para que `searchsorted` funcione.
    """
    cierres, moves = [], []
    for t in trades:
        if str(t.get("direction", "")).lower().startswith("l"):
            continue
        ent = float(t.get("avg_entry_price") or t.get("entry_price") or 0.0)
        sal = float(t.get("exit_price") or 0.0)
        ex = t.get("exit_time_epoch")
        if ent <= 0 or sal <= 0 or ex is None:
            continue
        cierres.append(int(ex) * 1_000_000_000)
        moves.append((ent - sal) / ent * 100.0)
    if not cierres:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.float64)
    orden = np.argsort(np.asarray(cierres, dtype=np.int64), kind="stable")
    return (np.asarray(cierres, dtype=np.int64)[orden],
            np.asarray(moves, dtype=np.float64)[orden])
