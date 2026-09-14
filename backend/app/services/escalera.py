"""
Escalera del modo Scalping «complejo» (2026-09-12, a peticion de Jaume).

QUE ES. Dentro de UN scalp (una posicion abierta por el gatillo), por cada
PASO de X % que el precio se mueve desde el ultimo nivel ejecutado, la escalera
hace algo mecanico, siempre igual:

    a favor  -> añadir | quitar | nada, una cantidad ($ fijos o % de la
                posicion inicial)
    en contra-> añadir | quitar | nada, idem

con dos limites de TAMANO y uno de RECORRIDO:

    core   = suelo: la posicion nunca baja de ahi al quitar (0 = puede vaciarse;
             entonces el scalp queda cerrado y el siguiente gatillo abre otro).
    tope   = techo: la posicion nunca pasa de ahi al añadir (0 = sin techo
             propio; manda la caja, como siempre).
    recorrido = hasta que % desde el precio de la primera entrada actua la
             escalera; mas alla no añade ni quita y la posicion queda en manos
             de la salida principal (salida logica, stop, take profit, tiempo),
             que SIEMPRE cierra todo lo que haya.

Los niveles son una malla entera sobre el precio de la primera entrada:
nivel k = entrada0 x (1 + signo x k x paso), con k > 0 «a favor» (arriba en
largo, abajo en corto). El estado es el indice del ultimo nivel alcanzado; un
movimiento a favor es pasar de k a k+1, uno en contra de k a k-1, y lo que se
hace depende de LA DIRECCION DEL MOVIMIENTO, no del signo de k (volver de +2 a
+1 es «en contra»).

REARMAR (opcion B de Jaume). Con `rearm=False` cada nivel se ejecuta UNA vez
por scalp Y POR DIRECCION: añadir al bajar a 9,90 no gasta el «quitar» de
volver a subir a 9,90, pero una segunda bajada a 9,90 ya no añade. Pasar otra
vez por un nivel gastado mueve el estado, no opera. Con `rearm=True` cada nivel
opera cada vez que el precio lo cruza de nuevo: un grid puro, que en small caps
con spread y locates es donde se ven los costes.

STOP Y TAKE PROFIT sobre el PRECIO MEDIO (decision de Jaume): tras cada
añadido, el % del stop y del take profit se aplican sobre la media ponderada.
Ojo: añadir en contra ALEJA el stop en precio y el riesgo en $ crece con cada
escalon. Es lo pedido y es coherente con una martingala.

RELLENO. Cada nivel se ejecuta AL PRECIO DEL NIVEL (una orden limitada que
descansa ahi) con el slippage adverso de siempre, en la vela cuyo maximo/minimo
lo toca. Una vela grande puede cruzar varios niveles: se procesan en orden,
primero el lado que la vela visito antes (si cierra por encima de la apertura,
primero los de abajo). Los añadidos respetan el tope de caja, el de locates y
el cortacircuitos diario igual que la piramide.

La logica de ejecucion vive en `portfolio_sim.simulate` (parametro `ladder`,
None por defecto = ni una rama nueva); aqui estan la configuracion y los
calculos puros, que asi se prueban solos y no engordan el fichero compartido.
"""
from __future__ import annotations

from dataclasses import dataclass

ACCIONES = ("add", "reduce", "none")
UNIDADES = ("usd", "pct")


@dataclass(frozen=True)
class ConfigEscalera:
    step_pct: float            # paso, en % del precio (1 = 1 %)
    favor_action: str          # add | reduce | none
    favor_amount: float
    favor_unit: str            # usd | pct (% de la posicion INICIAL)
    contra_action: str
    contra_amount: float
    contra_unit: str
    core_amount: float         # suelo (0 = puede vaciarse)
    core_unit: str
    cap_amount: float          # techo (0 = sin techo propio)
    cap_unit: str
    max_travel_pct: float      # recorrido maximo desde la entrada (0 = sin limite)
    rearm: bool                # B: cada nivel opera cada vez que se cruza

    @property
    def max_k(self) -> int:
        """Cuantos escalones caben en el recorrido (0 = sin limite)."""
        if self.max_travel_pct <= 0 or self.step_pct <= 0:
            return 0
        return int(self.max_travel_pct / self.step_pct + 1e-9)


def _accion(v) -> str:
    s = str(v or "none").lower()
    if s in ("quitar", "reduce", "vender", "sell"):
        return "reduce"
    if s in ("anadir", "añadir", "add", "comprar", "buy"):
        return "add"
    return "none"


def _unidad(v) -> str:
    s = str(v or "pct").lower()
    return "usd" if s in ("usd", "$", "dollars", "fijo", "fijos") else "pct"


def _num(v, default=0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if x != x:  # NaN
        return default
    return x


def parse_escalera(d: dict | None) -> ConfigEscalera | None:
    """Del bloque `scalping.ladder` de la definicion a la config, o None.

    None (= sin escalera) si no hay bloque, si el paso no es positivo o si las
    dos direcciones estan en «nada»: una escalera que no hace nada no debe
    encender ninguna rama del simulador.
    """
    if not d or not isinstance(d, dict):
        return None
    step = _num(d.get("step_pct"))
    if step <= 0:
        return None
    favor = _accion(d.get("favor_action"))
    contra = _accion(d.get("contra_action"))
    favor_amt = max(0.0, _num(d.get("favor_amount")))
    contra_amt = max(0.0, _num(d.get("contra_amount")))
    if favor_amt <= 0:
        favor = "none"
    if contra_amt <= 0:
        contra = "none"
    if favor == "none" and contra == "none":
        return None
    return ConfigEscalera(
        step_pct=step,
        favor_action=favor,
        favor_amount=favor_amt,
        favor_unit=_unidad(d.get("favor_unit")),
        contra_action=contra,
        contra_amount=contra_amt,
        contra_unit=_unidad(d.get("contra_unit")),
        core_amount=max(0.0, _num(d.get("core_amount"))),
        core_unit=_unidad(d.get("core_unit")),
        cap_amount=max(0.0, _num(d.get("cap_amount"))),
        cap_unit=_unidad(d.get("cap_unit")),
        max_travel_pct=max(0.0, _num(d.get("max_travel_pct"))),
        rearm=bool(d.get("rearm", False)),
    )


def nivel_precio(entry0: float, is_long: bool, k: int, step_pct: float) -> float:
    """Precio del nivel k de la malla. k > 0 = a favor."""
    signo = 1.0 if is_long else -1.0
    return entry0 * (1.0 + signo * k * step_pct / 100.0)


def a_acciones(amount: float, unit: str, size0: float, px: float) -> float:
    """Una cantidad de la config en acciones: $ al precio del nivel, o % de la
    posicion inicial."""
    if amount <= 0 or px <= 0:
        return 0.0
    if unit == "usd":
        return amount / px
    return size0 * amount / 100.0


def orden_lados(open_px: float, close_px: float, is_long: bool) -> tuple[str, str]:
    """Que lado de la vela se visita primero. Si la vela cierra por encima de
    donde abrio se asume que hizo primero el minimo; en corto, al reves (el
    «contra» de un corto esta arriba)."""
    subio = close_px >= open_px
    if is_long:
        return ("contra", "favor") if subio else ("favor", "contra")
    return ("favor", "contra") if subio else ("contra", "favor")


def nivel_tocado(lado: str, is_long: bool, px_nivel: float, high: float, low: float) -> bool:
    """El nivel esta «tocado» si el extremo de la vela en su direccion lo alcanza."""
    arriba = (lado == "favor") == is_long   # favor en largo y contra en corto = arriba
    return high >= px_nivel - 1e-12 if arriba else low <= px_nivel + 1e-12
