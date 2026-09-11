"""
Coste de Black Swan (2026-09-11, a peticion de Jaume).

QUE ES UNA «MECHA BLACK SWAN». En las small caps de premercado hay velas de un
minuto cuyo maximo se dispara cientos o miles de % sobre su apertura y vuelve
en segundos (PLYX ~5.000 %, ENSC de 0,35 $ a 24,71 $ en 3 s). Un stop que este
en medio se ejecuta a un precio de pesadilla. La medida es, para cada vela:

    mecha (%) = (extremo ADVERSO - open) / open x 100

donde el extremo adverso es el `high` para un corto y el `low` para un largo.
Un largo no puede caer mas de un 100 % dentro de una vela, asi que en la
practica esto es una herramienta para cortos; el largo se contempla para no
dejar un agujero silencioso si alguien lo activa con una estrategia larga.

Ojo: las velas oficiales de minuto a veces OCULTAN el pico (MEMORIA §3.1: los
trades individuales lo muestran y la vela no). Lo que se mide aqui es lo que
hay en el lago; el pico real puede ser peor.

DOS USOS, separados a proposito:

1. DESCRIPTIVO (siempre, sin coste ni cambio de resultado): a cada trade se le
   anota la mecha adversa MAXIMA que sufrio mientras estuvo dentro
   (`bs_wick_pct`, `bs_wick_idx`). De ahi sale la vista «BS» del grafico de
   MAE/MFE: cuantas veces estuvo la estrategia expuesta a un mechazo.

2. COSTE OPCIONAL (`ConfigBSwan`): el motor cierra la posicion cuando una vela
   supera el umbral. Dos modos:
     - «mercado»: cierra EN ESA VELA a un precio peor que donde se habria
       salido (el stop si esa vela lo cruza; si no, la apertura de la vela),
       penalizado un `slippage_pct`, y por TRAMOS de `particion` acciones si la
       posicion es mayor: el tramo k paga k x slippage (1.000 acciones al
       +100 %, las 500 siguientes al +200 %...). NO se recorta al maximo de
       la vela: es una penalizacion, no un fill, y las velas esconden picos.
     - «manual»: NO cierra en la vela (modela un stop mental, sin orden en el
       mercado, que la barrida no puede ejecutar): suspende stop, TP, parciales
       y salida por senal, y cierra TODA la posicion al cierre de la primera
       vela que este a `minutos` o mas de la deteccion. EOD, limite de tiempo
       y cortacircuitos diario siguen mandando.

   Solo se mira MIENTRAS SE ESTA DENTRO: desde la vela del fill de entrada
   hasta la vela del fill de salida (una salida por senal, que se ejecuta en
   la apertura de la vela siguiente, deja de estar expuesta en esa vela).

La logica de cierre vive en `portfolio_sim.simulate` (parametro `bswan`, None
por defecto = ni una rama nueva); aqui estan la configuracion y los calculos
puros, que asi se prueban solos y no engordan el fichero compartido con el bot.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


MODOS = ("mercado", "manual")


@dataclass(frozen=True)
class ConfigBSwan:
    """Configuracion del coste de Black Swan. Inmutable: viaja por kwargs a
    cada ticker-dia y no debe poder cambiar por el camino."""
    modo: str = "mercado"
    # Mecha minima (open -> extremo adverso, en % del open) para considerar
    # que la vela es un Black Swan. 100 = el precio se duplico en un minuto.
    umbral_pct: float = 100.0
    # Modo «mercado»: penalizacion del tramo 1, en % del precio base. El tramo
    # k paga k x este valor.
    slippage_pct: float = 100.0
    # Modo «mercado»: acciones por tramo. 0 = todo en un tramo.
    particion: float = 0.0
    # Modo «manual»: minutos desde la vela de deteccion hasta el cierre.
    minutos: float = 15.0

    def __post_init__(self):
        if self.modo not in MODOS:
            raise ValueError(f"modo de Black Swan desconocido: {self.modo!r}")
        if not (float(self.umbral_pct) > 0.0):
            raise ValueError("el umbral de Black Swan debe ser > 0")
        if float(self.slippage_pct) < 0.0:
            raise ValueError("el slippage de Black Swan no puede ser negativo")
        if float(self.particion) < 0.0:
            raise ValueError("la particion no puede ser negativa")
        if self.modo == "manual" and float(self.minutos) <= 0.0:
            raise ValueError("los minutos del modo manual deben ser > 0")

    def resumen(self) -> dict:
        return {
            "modo": self.modo,
            "umbral_pct": float(self.umbral_pct),
            "slippage_pct": float(self.slippage_pct),
            "particion": float(self.particion),
            "minutos": float(self.minutos),
        }


def mecha_adversa_pct(open_px: float, high_px: float, low_px: float, is_long: bool) -> float:
    """Mecha adversa de UNA vela, en % de su apertura. 0 si el open no vale."""
    if not (open_px > 0.0):
        return 0.0
    if is_long:
        return (open_px - low_px) / open_px * 100.0
    return (high_px - open_px) / open_px * 100.0


def mechas_adversas(open_: np.ndarray, high: np.ndarray, low: np.ndarray, is_long: bool) -> np.ndarray:
    """La mecha adversa de cada vela (vectorizado). Velas con open <= 0 dan 0."""
    o = np.asarray(open_, dtype=np.float64)
    ext = np.asarray(low if is_long else high, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        m = ((o - ext) if is_long else (ext - o)) / o * 100.0
    m = np.where(o > 0.0, m, 0.0)
    return np.nan_to_num(m, nan=0.0, posinf=0.0, neginf=0.0)


def ultima_vela_expuesta(trade: dict, look_ahead_prevention: bool) -> int:
    """Indice de la ultima vela en la que la posicion de este registro estuvo
    abierta. Una salida por senal con look-ahead se ejecuta en la APERTURA de
    `exit_idx`: esa vela ya no expone. El resto de salidas se ejecutan dentro de
    su vela (stop, TP, cierre) y cuentan entera.

    Mismo criterio que el MAE del motor, que en una salida por senal deja de
    medir en la vela de la senal.
    """
    xi = int(trade.get("exit_idx", 0))
    ei = int(trade.get("entry_idx", 0))
    if look_ahead_prevention and trade.get("exit_reason") == "Signal" and xi > ei:
        return xi - 1
    return xi


def anotar_mechas(raw_trades: list, open_, high, low, is_long: bool,
                  look_ahead_prevention: bool = True) -> None:
    """Pega a cada registro crudo del simulador la mecha adversa maxima que
    sufrio en su ventana de exposicion (`bs_wick_pct`) y la vela en que
    ocurrio (`bs_wick_idx`). Muta los dicts; no toca ninguna otra clave.

    Es puramente descriptivo: no cambia PnL, salidas ni metricas. Con
    parciales/piramide cada leg mide su propia ventana [entry, exit del leg] y
    el agrupador se queda con el maximo, que es el de la leg de cierre.
    """
    if not raw_trades:
        return
    m = mechas_adversas(open_, high, low, is_long)
    n = len(m)
    if n == 0:
        return
    for t in raw_trades:
        a = min(max(int(t.get("entry_idx", 0)), 0), n - 1)
        b = min(max(ultima_vela_expuesta(t, look_ahead_prevention), a), n - 1)
        tramo = m[a:b + 1]
        k = int(np.argmax(tramo))
        t["bs_wick_pct"] = round(float(tramo[k]), 4)
        t["bs_wick_idx"] = a + k


def tramos_bs(size: float, particion: float, slippage_pct: float) -> list[tuple[float, float]]:
    """Reparte `size` acciones en tramos de `particion` y asigna a cada tramo
    su penalizacion: el tramo k paga k x `slippage_pct`.

    Devuelve [(acciones, slippage_pct_del_tramo), ...] en orden. Con
    particion 0 (o >= size) sale un unico tramo al slippage base. El ultimo
    tramo puede ser mas pequeno (1.500 con particion 1.000 -> 1.000 y 500).
    """
    size = float(size)
    if size <= 0.0:
        return []
    p = float(particion or 0.0)
    if p <= 0.0 or p >= size:
        return [(size, float(slippage_pct))]
    n_tramos = int(math.ceil(size / p - 1e-12))
    out: list[tuple[float, float]] = []
    restante = size
    for k in range(1, n_tramos + 1):
        sz = min(p, restante)
        out.append((sz, float(slippage_pct) * k))
        restante -= sz
        if restante <= 1e-12:
            break
    return out


def precio_bs(base: float, slip_pct: float, is_long: bool) -> float:
    """Precio de un tramo: `slip_pct` por ciento PEOR que `base`. Un largo no
    puede cobrar menos de cero."""
    f = float(slip_pct) / 100.0
    if is_long:
        return max(0.0, float(base) * (1.0 - f))
    return float(base) * (1.0 + f)
