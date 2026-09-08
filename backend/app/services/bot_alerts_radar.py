"""El RADAR: de todo el mercado a los pocos tickers que merecen mirarse.

El motor no puede correr sobre 11.000 simbolos, ni falta: la mayoria no se mueve
en todo el dia. El radar aplica un filtro barato —subida minima, volumen y
precio— y solo los que pasan entran al seguimiento de verdad.

POR QUE POR CONSULTA Y NO POR WEBSOCKET. El instinto dice suscribirse a todo el
mercado en tiempo real, pero **no hace falta y complica mucho**: una foto del
mercado entero es UNA llamada y trae ya calculado el cierre de ayer, el precio,
el volumen y el maximo del dia de cada ticker.

Y sobre todo: **detectar tarde no cuesta nada**, porque al promocionar un ticker
se le piden sus velas del dia por REST y el frame queda completo desde las
04:00. Da igual verlo a las 07:00:20 en vez de a las 07:00:00 — no se pierde ni
una vela. Eso es lo que permite que el radar sea tan simple.

EL FILTRO NO ES LA ESTRATEGIA. Aqui solo se decide A QUIEN MIRAR. Quien decide
si se opera es el motor, con las condiciones completas de cada estrategia. Por
eso el umbral del radar debe ser MAS PERMISIVO que el de la estrategia: si el
radar se pasa de estricto, descarta tickers que la estrategia habria operado y
nadie se entera.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import httpx

from app.services.bot_alerts_feed import clave_bot, _ssl_ctx

logger = logging.getLogger("btt.bot_alerts.radar")

REST = os.getenv("MASSIVE_API_BASE_URL", "https://api.massive.com")

# Tipos de instrumento que pueden entrar. Igual que el screener: fuera ETFs,
# warrants, unidades, derechos y preferentes — no son lo que opera la estrategia
# y ensucian el radar.
TIPOS = ("CS", "ADRC")


@dataclass
class CandidatoEstrategia:
    """Un ticker que cumple el filtro de universo de una estrategia concreta."""
    ticker: str
    strategy_id: str
    estrategia: str
    metrica: str            # que regla lo trajo, p.ej. "PM High Gap %"
    valor: float            # cuanto vale esa metrica ahora
    precio: float
    prev_close: float
    volumen: float


class RadarPorEstrategia:
    """El radar de verdad: vigila lo que pide CADA estrategia, no un umbral mio.

    Si 1B pide `PM High Gap % >= 50`, entra lo que pase de 50. Si otra pide 30,
    lo que pase de 30 — y un ticker puede entrar por las dos, cada una con su
    etiqueta.

    UNA VEZ DENTRO, NO SE SALE. El filtro de universo es acumulado: `PM High
    Gap %` es un maximo y no baja. Que el precio haya retrocedido no deshace que
    el gap se hizo, y la estrategia lo seguiria operando. Solo se limpia al
    cambiar de dia.
    """

    def __init__(self, mercado):
        self.mercado = mercado
        # (ticker, strategy_id) ya admitidos. Es lo que hace que no se salga.
        self._admitidos: dict[tuple[str, str], CandidatoEstrategia] = {}
        self._estrategias: list[dict] = []
        self._avisos: list[str] = []

    def configurar(self, estrategias: list[dict]) -> list[str]:
        """Las estrategias vigiladas. Devuelve los avisos que hay que contar."""
        from app.services import bot_alerts_universo as uni
        self._estrategias = estrategias
        self._avisos = []
        for e in estrategias:
            info = uni.analizar(e["definition"])
            reglas = uni.resumen_reglas(e["definition"])
            if info["no_evaluables"]:
                self._avisos.append(
                    f"{e['name']}: NO se puede vigilar — no se sabe calcular en vivo "
                    f"{', '.join(info['no_evaluables'])}")
            elif info["solo_rth"]:
                self._avisos.append(
                    f"{e['name']}: solo vigilable a partir de las 09:30 — "
                    f"{', '.join(info['solo_rth'])} no existe en premercado")
            elif not info["reglas"]:
                self._avisos.append(f"{e['name']}: sin filtro de universo, no aporta candidatos")
            else:
                self._avisos.append(f"{e['name']}: vigilando {reglas}")
        return self._avisos

    def limpiar_dia(self) -> None:
        self._admitidos.clear()

    def escanear(self) -> list[CandidatoEstrategia]:
        """Recorre el mercado y devuelve TODO lo admitido, viejo y nuevo."""
        from app.services import bot_alerts_universo as uni

        for st in self.mercado.todos():
            if st.precio is None or st.prev_close is None:
                continue
            metricas = st.metricas()
            for e in self._estrategias:
                clave = (st.ticker, e["strategy_id"])
                if clave in self._admitidos:
                    continue                     # ya dentro: no se revisa
                if not uni.cumple(metricas, e["definition"]):
                    continue
                # Que regla lo trajo, para poder ensenyarlo.
                metrica = valor = None
                for r in uni.reglas_de(e["definition"]):
                    interna = uni.SOPORTADAS.get(str(r.get("metric") or ""))
                    if interna and metricas.get(interna) is not None:
                        metrica, valor = str(r.get("metric")), metricas[interna]
                        break
                self._admitidos[clave] = CandidatoEstrategia(
                    ticker=st.ticker, strategy_id=e["strategy_id"],
                    estrategia=e["name"], metrica=metrica or "?",
                    valor=float(valor or 0.0), precio=float(st.precio),
                    prev_close=float(st.prev_close), volumen=float(st.day_volume),
                )

        # Refrescar precio y volumen de los admitidos, que sí cambian.
        for (tk, _sid), c in self._admitidos.items():
            st = self.mercado.estado(tk)
            if st is not None:
                if st.precio is not None:
                    c.precio = float(st.precio)
                c.volumen = float(st.day_volume)
                m = st.metricas()
                interna = uni.SOPORTADAS.get(c.metrica)
                if interna and m.get(interna) is not None:
                    c.valor = float(m[interna])

        return sorted(self._admitidos.values(), key=lambda c: c.valor, reverse=True)

    @property
    def tickers(self) -> set[str]:
        """Los tickers a vigilar, sin repetir aunque vengan de varias."""
        return {tk for (tk, _sid) in self._admitidos}


@dataclass
class Umbrales:
    """El filtro barato. Valores pensados para gaps, ajustables desde fuera."""
    # Subida minima desde el cierre de ayer. 1B pide 50 en su filtro de
    # universo; aqui se deja MAS BAJO a proposito para no descartar antes de
    # tiempo lo que la estrategia si miraria.
    cambio_min_pct: float = 30.0
    volumen_min: float = 100_000.0
    precio_min: float = 0.5
    precio_max: float = 100.0
    # Tope de tickers en seguimiento. Cada uno cuesta una hidratacion y una
    # evaluacion por vela; con 2-4 sobra maquina, con 50 hay que medirlo.
    max_seguidos: int = 12


@dataclass
class Candidato:
    ticker: str
    cambio_pct: float
    precio: float
    volumen: float
    prev_close: float


class Radar:
    """Mira el mercado entero y devuelve quien pasa el filtro."""

    def __init__(self, umbrales: Optional[Umbrales] = None):
        self.umbrales = umbrales or Umbrales()
        self._universo: set[str] = set()
        self.ultimo_error: Optional[str] = None

    # ── universo ─────────────────────────────────────────────────────────
    def cargar_universo(self) -> int:
        """Acciones ordinarias y ADR de EEUU. Se pide una vez al arrancar.

        Sin este filtro el radar se llena de ETFs apalancados y warrants, que
        suben mucho por construccion y no son lo que se opera.
        """
        key = clave_bot()
        if not key:
            return 0
        simbolos: set[str] = set()
        try:
            with httpx.Client(timeout=30.0, verify=_ssl_ctx()) as cli:
                for tipo in TIPOS:
                    url: Optional[str] = f"{REST}/v3/reference/tickers"
                    params: Optional[dict] = {
                        "market": "stocks", "active": "true", "type": tipo,
                        "limit": 1000, "apiKey": key,
                    }
                    paginas = 0
                    while url and paginas < 50:
                        r = cli.get(url, params=params)
                        r.raise_for_status()
                        datos = r.json()
                        for fila in (datos.get("results") or []):
                            tk = str(fila.get("ticker", "") or "")
                            if tk:
                                simbolos.add(tk)
                        siguiente = datos.get("next_url")
                        # next_url ya lleva el cursor y los filtros; solo falta
                        # volver a poner la clave.
                        url, params = ((siguiente, {"apiKey": key}) if siguiente
                                       else (None, None))
                        paginas += 1
        except Exception as exc:  # noqa: BLE001
            self.ultimo_error = f"universo: {exc}"
            logger.warning("[RADAR] no se pudo cargar el universo: %s", exc)
            return len(self._universo)

        if simbolos:
            self._universo = simbolos
        return len(self._universo)

    def cierres_de_ayer(self) -> dict[str, float]:
        """El cierre de ayer de TODO el mercado, en una llamada.

        Es la base de cualquier gap y el socket NO la trae: los agregados hablan
        de hoy. Se pide una vez al arrancar y se refresca de tanto en tanto por
        si aparecen tickers nuevos.

        Es `prevDay.c`, el cierre de la sesion REGULAR — no el de after-hours.
        Comprobado el 2026-09-02 con SGLD: prevDay.c = 5,08, que es el `close`
        oficial del dia anterior; su after-hours fue 17,30 y NO es lo que se usa.
        """
        key = clave_bot()
        if not key:
            return {}
        try:
            with httpx.Client(timeout=30.0, verify=_ssl_ctx()) as cli:
                r = cli.get(
                    f"{REST}/v2/snapshot/locale/us/markets/stocks/tickers",
                    params={"apiKey": key},
                )
                r.raise_for_status()
                filas = r.json().get("tickers") or []
        except Exception as exc:  # noqa: BLE001
            self.ultimo_error = f"cierres de ayer: {exc}"
            logger.warning("[RADAR] no se pudieron pedir los cierres de ayer: %s", exc)
            return {}

        out: dict[str, float] = {}
        for f in filas:
            sym = str(f.get("ticker", "") or "")
            if not sym:
                continue
            if self._universo and sym not in self._universo:
                continue
            pc = _num((f.get("prevDay") or {}).get("c"))
            if pc and pc > 0:
                out[sym] = pc
        return out

    # ── barrido ──────────────────────────────────────────────────────────
    def escanear(self) -> list[Candidato]:
        """Una foto del mercado -> los que pasan el filtro, de mayor a menor.

        Es UNA llamada para los ~11.000 simbolos. El cierre de ayer viene en la
        propia respuesta, asi que el cambio porcentual sale sin pedir nada mas.
        """
        key = clave_bot()
        if not key:
            self.ultimo_error = "falta MASSIVE_BOT_API_KEY"
            return []
        try:
            with httpx.Client(timeout=30.0, verify=_ssl_ctx()) as cli:
                r = cli.get(
                    f"{REST}/v2/snapshot/locale/us/markets/stocks/tickers",
                    params={"apiKey": key},
                )
                r.raise_for_status()
                filas = r.json().get("tickers") or []
        except Exception as exc:  # noqa: BLE001
            self.ultimo_error = f"barrido: {exc}"
            logger.warning("[RADAR] fallo el barrido: %s", exc)
            return []

        u = self.umbrales
        fuera: list[Candidato] = []
        for f in filas:
            sym = str(f.get("ticker", "") or "")
            if not sym:
                continue
            if self._universo and sym not in self._universo:
                continue

            prev = (f.get("prevDay") or {}).get("c")
            dia = f.get("day") or {}
            ultimo = (f.get("lastTrade") or {}).get("p")
            minuto = f.get("min") or {}

            precio = _num(ultimo) or _num(minuto.get("c")) or _num(dia.get("c"))
            prev_c = _num(prev)
            # El volumen del dia vale 0 en premercado; ahi manda el acumulado
            # del ultimo minuto, que es lo que hay.
            volumen = _num(dia.get("v")) or _num(minuto.get("av")) or 0.0

            if not precio or not prev_c or prev_c <= 0:
                continue
            if not (u.precio_min <= precio <= u.precio_max):
                continue
            if volumen < u.volumen_min:
                continue

            cambio = (precio - prev_c) / prev_c * 100.0
            # Solo subidas: las estrategias de gap buscan lo que se ha disparado,
            # y quien decide el lado (largo o corto) es la estrategia.
            if cambio < u.cambio_min_pct:
                continue
            # Un salto absurdo casi siempre es un cierre de ayer mal ajustado
            # por un split, no un movimiento real.
            if cambio > 1000.0:
                continue

            fuera.append(Candidato(sym, cambio, precio, volumen, prev_c))

        fuera.sort(key=lambda c: c.cambio_pct, reverse=True)
        self.ultimo_error = None
        return fuera[: u.max_seguidos]


def _num(v) -> Optional[float]:
    try:
        if v is None:
            return None
        f = float(v)
        return None if f != f or f in (float("inf"), float("-inf")) else f
    except (TypeError, ValueError):
        return None
