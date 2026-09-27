"""Exclusiones del radar: lista negra, SPAC, IPO reciente, split del día, banda de OPA y símbolo DAS.

QUÉ HACE. `excluida` aplica R-A-03 v2 en un orden fijo y devuelve el MOTIVO
(texto) o None; `banda_opa` detecta el precio clavado en una banda estrecha
tras el máximo de premercado (aviso, nunca salida automática); `simbolo_das`
es la equivalencia Massive → DAS (A7), hoy la identidad.

POR QUÉ ESTÁ AQUÍ. Son guardas puras: reciben la `Ficha` que trajo
`referencia_massive.py` (o None si no se pudo), el conjunto de splits del día
(o None si no se pudo) y la config; ninguna consulta nada. El decisor las
llama ANTES de `reglas.entrada.evaluar_senal` (ajuste (c)) y le pasa el motivo.

LAS TRAMPAS.
  * `ficha is None` → «sin_ficha»: A12, no se opera y se reintenta la carga.
    Pero `splits_hoy is None` NO excluye (corrección 17, riesgo 35): sin lista
    de splits el decisor avisa una vez y sigue; jamás «excluir todo».
  * SPAC (SIC 6770) fuera SIEMPRE, en todas las estrategias. IPO < 30 días
    SOLO si la estrategia es de sesión regular (`es_rth`) Y tiene la casilla
    (`excluir_ipo`): en premercado (1B) no se excluyen. Los límites son
    exactos: con 30 días, `list_date` = hoy − 30 d ya NO es reciente y hoy −
    29 d sí. Una ficha sin `list_date` cuenta como reciente (no se sabe → no se
    opera en RTH con casilla).
  * La banda de OPA se mide desde el máximo de PM hacia abajo: 30 min en los
    que todo el rango cabe en el 1,5 % bajo ese máximo con ≥ 100 k$
    negociados. Hace falta que las muestras CUBRAN la ventana (no bastan tres
    velas sueltas). Es AVISO: Jaume mira el gráfico (R-A-03 v2, 20-sep).
  * Comparaciones de tickers en mayúsculas y sin espacios: la lista negra la
    escribe una persona en el cuadro.
  * La config llega del JSON del cuadro: enteros y casillas se validan
    (`ipo_dias` = «30» de texto o `split_del_dia` = «0» lanzan ValueError en
    vez de excluir o dejar pasar en silencio); H-5 lo convierte en pausa.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from app.bot_das.reglas.precios import de_float
from app.bot_das.tipos import (
    IPO_DIAS,
    OPA_BANDA_MIN,
    OPA_DOLARES_MIN,
    OPA_RANGO_MAX_PCT,
    SPAC_SIC,
    EstrategiaConfig,
    Ficha,
)

MOTIVOS = ("lista_negra", "sin_ficha", "spac", "ipo", "split")
_CIEN = Decimal("100")


def excluida(ticker: str, e: EstrategiaConfig, ficha: Optional[Ficha], splits_hoy: Optional[set[str]],
             lista_negra: list[str], hoy: date, cfg_ex: dict) -> Optional[str]:
    """R-A-03 v2 en este orden: lista negra → sin ficha (A12) → SPAC → IPO (solo RTH con casilla) → split del día.

    Devuelve el motivo («lista_negra», «sin_ficha», «spac», «ipo», «split») o
    None si se puede operar. `splits_hoy = None` no excluye (corrección 17).
    `cfg_ex` es el bloque «exclusiones» del cuadro (`spac_sic`, `ipo_dias`,
    `split_del_dia`: con false el split del día deja de excluir; ausente =
    true, lo del libro). La lista negra va PRIMERO: ni siquiera hace falta
    ficha para no operar un ticker que Jaume ha vetado a mano.
    """
    simbolo = _norm(ticker)
    if simbolo in {_norm(x) for x in (lista_negra or ())}:
        return "lista_negra"
    if ficha is None:
        return "sin_ficha"
    spac = {str(s).strip() for s in cfg_ex.get("spac_sic", SPAC_SIC)}
    if ficha.sic_code is not None and str(ficha.sic_code).strip() in spac:
        return "spac"
    if e.es_rth and e.excluir_ipo:
        dias = _entero(cfg_ex.get("ipo_dias", IPO_DIAS), "ipo_dias")
        if ficha.list_date is None or ficha.list_date > hoy - timedelta(days=dias):
            return "ipo"
    if splits_hoy is not None and _booleano(cfg_ex.get("split_del_dia", True), "split_del_dia") \
            and simbolo in {_norm(s) for s in splits_hoy}:
        return "split"
    return None


def banda_opa(muestras: list[tuple[float, Decimal, Decimal, Decimal]], max_pm: Optional[Decimal],
              cfg_ex: dict) -> bool:
    """R-A-03 v2 (banda clavada = AVISO): 30 min con todo el rango ≤ 1,5 % bajo el máximo de PM y ≥ 100 k$ negociados.

    `muestras` = (t en segundos, high, low, dólares negociados) de cada vela
    de 1 min (t = inicio de la vela); se ordenan por t y se mira la ventana de
    `opa_banda.minutos` que acaba en la última. Condiciones: la ventana está
    cubierta (primera y última muestra separadas al menos `minutos − 1`
    minutos: 30 velas seguidas de t = 0 a t = 29 min valen; no bastan tres
    sueltas), el tope de referencia es max(`max_pm`, highs de la ventana),
    (tope − mínimo de los lows) / tope ≤ `rango_max_pct` (inclusive) y Σ
    dólares ≥ `dolares_min` (inclusive). Sin `max_pm` (None) el tope es el
    high de la ventana. Lo devuelto es un AVISO: jamás una salida automática.
    """
    if not muestras:
        return False
    cfg = cfg_ex.get("opa_banda") or {}
    minutos = _entero(cfg.get("minutos", OPA_BANDA_MIN), "opa_banda.minutos")
    rango_max = de_float(cfg.get("rango_max_pct", OPA_RANGO_MAX_PCT))
    dolares_min = de_float(cfg.get("dolares_min", OPA_DOLARES_MIN))
    if minutos <= 0:
        return False
    ordenadas = sorted(muestras, key=lambda m: float(m[0]))
    t_fin = float(ordenadas[-1][0])
    ventana = [m for m in ordenadas if float(m[0]) > t_fin - minutos * 60]
    if t_fin - float(ventana[0][0]) < (minutos - 1) * 60:
        return False
    tope = de_float(max_pm) if max_pm is not None else Decimal("0")
    minimo: Optional[Decimal] = None
    dolares = Decimal("0")
    for _, hi, lo, usd in ventana:
        alto, bajo = de_float(hi), de_float(lo)
        if alto > tope:
            tope = alto
        minimo = bajo if minimo is None or bajo < minimo else minimo
        dolares += de_float(usd)
    if tope <= 0 or minimo is None or minimo <= 0:
        return False
    rango_pct = (tope - minimo) / tope * _CIEN
    return rango_pct <= rango_max and dolares >= dolares_min


def simbolo_das(ticker_massive: str) -> str:
    """A7: símbolo de DAS para un ticker de Massive. Hoy la identidad (mayúsculas, sin espacios).

    La equivalencia real se aprende con `MercadoDAS.sin_cotizacion_desde`
    (símbolo que no casa → SIN_SIMBOLO + aviso) y se anota «simbolo_no_casa».
    """
    return _norm(ticker_massive)


def _norm(ticker: str) -> str:
    return str(ticker).strip().upper()


def _entero(valor, nombre: str) -> int:
    if isinstance(valor, bool) or not isinstance(valor, (int, float, Decimal)) or int(valor) != valor:
        raise ValueError(f"exclusiones.{nombre} debe ser entero: {valor!r}")
    return int(valor)


def _booleano(valor, nombre: str) -> bool:
    """Una casilla del cuadro: solo `true`/`false` (un «0» de texto no es falso para Python y sí para Jaume)."""
    if not isinstance(valor, bool):
        raise ValueError(f"exclusiones.{nombre} debe ser true/false: {valor!r}")
    return valor
