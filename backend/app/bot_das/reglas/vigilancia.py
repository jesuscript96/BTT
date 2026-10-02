"""Lo que comprueba el vigilante en cada pasada: stops de cada posición, plan B, locates, margen, precio y ping externo.

QUÉ HACE. `comprobar` recibe una `Foto` (lo que el vigilante ve por su
conexión watch + los diarios) y devuelve las acciones del vigilante:
  (a) por posición corta con lotes: exactamente UN stop por nivel L con las
      acciones de sus lotes (Jaume 29-sep, stop único, R-C-01 v4: disparo en
      L, límite L + 50 %) → `stops.plan` con los tokens del vigilante
      (Origen.VIGILANTE) y el propósito de lo ajeno al diario inferido
      (`stops.inferir_proposito`, corrección 3);
  (b) sobrantes → cancelar la más nueva (lo hace el mismo `plan`);
  (c) posición que no está en ningún diario → `stops.stop_proteccion` por lo
      descubierto + Avisar(3) (R-C-10 caso 4); D10 (Jaume 30-sep): con un
      stop VIVO del humano en el ticker, ninguna protección del bot (solo
      aviso 2 si no cubre toda la posición, `_con_stop_manual`);
  (d) R-H-02 (dos compras Located no pedidas del mismo ticker-estrategia-día)
      y R-H-03 (gasto > tope del día en $, decisión 60) → Avisar(3) + Anotar
      («locates_deshabilitar»);
  (e) 2c: margen de mantenimiento de los cortos > equity·margen_aviso → Avisar(2);
  (f) R-C-08 (a): el precio pasó el límite del stop de un nivel sin fill →
      SOLO aviso (cerrar queda [PENDIENTE]; `cerrar_si_descubierta` no se
      usa); con el ejecutor muerto, aviso 3 de cisne negro (R-G-01 v4);
  (g) corrección 16: si hay que enviar y `puede_enviar` es False → Avisar(3) +
      PedirAlSupervisor("relanzar ejecutor").
  (h) decisión 61 (Jaume 2-oct), con `halts.silencio` (defecto true): con el
      símbolo PARADO (`Foto.parados`, que el proceso saca de SU conexión) no
      sale ninguna orden ni se toca un stop (`_filtrar_halt`): solo el stop
      de acciones cortas SIN ningún stop vivo, como el ejecutor; lo retenido
      se anota (`halt_retenidas`) y se avisa (2). Al reabrir, durante
      `GRACIA_REAPERTURA_S` el plazo de «descubierta» no hace actuar al
      vigilante (el ejecutor está cerrando según la 57); muerto el ejecutor,
      todo como siempre. Los avisos no cambian.
`debe_hacer_ping` es R-J-05. `descubiertas_por_ticker` y
`actualizar_descubierta_desde` ayudan al proceso vigilante a llevar la cuenta
de cuánto lleva cada posición descubierta.

POR QUÉ ESTÁ AQUÍ. Lógica PURA: el proceso `vigilante.py` (lote G) solo
junta la foto, ejecuta lo que esto devuelve y escribe su propio diario. Toda
la aritmética de stops es la de `reglas.stops` (una sola): el ejecutor y el
vigilante calculan EXACTAMENTE lo mismo y por eso el neteo por propósito y
disparo es inequívoco (R-C-07 plan B).

LAS TRAMPAS.
  * Cerrojo sin lock (R-C-08.2, §6.1): con el ejecutor VIVO (latido ≤
    `plan_b_latido_s`) el vigilante NO actúa aunque falte un stop; solo si la
    posición lleva DESCUBIERTA (acciones sin un stop de nivel o de protección
    confirmado, R-C-03) más de `plan_b_descubierta_s`. Con el ejecutor muerto
    o sin latido, actúa en la primera pasada. Si hay algo raro y no le toca
    actuar, solo `Anotar("vigilancia")`; si todo cuadra, nada (el diario no se
    llena cada segundo). Es también lo que repone un stop que el ejecutor dejó
    de reponer tras los 5 rechazos de R-C-03 (Jaume 29-sep: con el stop único
    esa posición queda SIN stop): el decisor la pasa a CONTROL HUMANO y el
    vigilante, que no mira ese estado, la sigue viendo descubierta y lo
    intenta en cada pasada (con la separación y el tope de rechazos del
    proceso vigilante, riesgo 11).
  * La cuenta de «descubierta desde» NO la lleva esta función (es pura): la
    trae la foto (`descubierta_desde`), y el proceso la actualiza con
    `actualizar_descubierta_desde(…, descubiertas_por_ticker(…), ahora)`.
  * Lo que el vigilante acaba de enviar y DAS aún no ha devuelto por watch
    viaja en `Foto.pendientes`: sin eso, la pasada siguiente pondría otra
    protección igual (riesgo 11).
  * Solo se tocan órdenes NUESTRAS (`reconciliacion.es_ajena`): una orden
    manual que casara con un disparo nunca se reemplaza ni se cancela.
  * Una posición que la foto no lista es «sin información»: no se toca.
  * Un lote sin nivel de stop válido (A12) no cuenta: si NINGÚN lote de la
    posición lo tiene, nadie puede calcular su stop y se trata como (c),
    protección al 25 %, para no dejarla desnuda.
  * De lo que devuelve `plan` se quitan `Programar` y `Consultar` (son
    temporizadores y consultas del ejecutor; el vigilante vuelve a mirar en
    1 s). El vigilante NUNCA cierra una posición corta. E2c-02 (R-C-11 (3):
    «ejecutor + vigilante», el libro manda sobre §3.25): con el ejecutor
    MUERTO y la cuenta LARGA con lotes cortos, el vigilante vende SOLO el
    exceso con sus tokens (`stops.limpieza_tras_fill_stop`, sujeto a
    `puede_enviar`); con el ejecutor vivo solo avisa (lo limpia el ejecutor).
  * E2c-04: con el ejecutor vivo, la misma propuesta no se anota cada segundo:
    `comprobar_con_firmas` devuelve una firma por ticker que el proceso pasa
    en `Foto.anotado`; se vuelve a anotar al cambiar o al actuar.
  * (d) no dispara si la foto ya dice `locates_deshabilitados` (no se repite
    cada segundo). Una segunda compra PEDIDA (un «locate_intencion» por
    compra: parcial de R-H-04, reentrada de EP-9) no es repetida. Decisión
    60 (Jaume 2-oct): el tope de R-H-03 son dólares fijos del cuadro
    (`locates.tope_gasto_dia_usd`), así que ya no hace falta el equity.
  * El margen de mantenimiento (2c) se calcula aquí con los tramos FINRA:
    `reglas.capital` es de otro lote y la regla de reparto (§12) prohíbe
    importarlo; el test compara las dos si existen.
"""
from __future__ import annotations

import html
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from app.bot_das.reglas import reconciliacion, stops
from app.bot_das.reglas.precios import de_float
from app.bot_das.tipos import (
    LOCATES_TOPE_GASTO_DIA_USD,
    PLAN_B_DESCUBIERTA_S,
    PLAN_B_LATIDO_S,
    STOP_LIMITE_PCT,
    STOP_PROTECCION_PCT,
    Accion,
    Anotar,
    Avisar,
    Cancelar,
    CancelarTicker,
    Consultar,
    Cotizacion,
    EnviarOrden,
    EstadoLote,
    EstadoTicker,
    Grupo,
    InvalidarSerie,
    Lado,
    Lote,
    MsgOrden,
    MsgPos,
    Nivel,
    Orden,
    PedirAlSupervisor,
    PosicionTicker,
    Programar,
    Reemplazar,
    Registro,
    TipoOrden,
)

PETICION_RELANZAR_EJECUTOR = "relanzar ejecutor"     # corrección 16 / riesgo 31 (§3.25 g)
TIPO_ANOTACION = "vigilancia"                        # §8: registro del vigilante en cada pasada con algo que decir
TIPO_DESHABILITAR_LOCATES = "locates_deshabilitar"   # §8: `reconstruir` pone locates_deshabilitados = True
LOCATE_LOCATED = "Located"                           # estado de %SLOrder que cobra (manual L1722-1795)
MARGEN_AVISO_DEFECTO = Decimal("0.8")                # §7 tecnicos.vigilante.margen_aviso
MUTANTES = (EnviarOrden, Cancelar, Reemplazar, CancelarTicker)   # lo que necesita la conexión de acción
# Decisión 61 (Jaume 2-oct): tras reabrir un halt, el vigilante no da una posición por descubierta (plan B por el
# plazo) hasta pasado este margen: los 2 s que el ejecutor tiene para conocer lo vivo (decisión 57,
# HALT_SILENCIO_ESTADO_S) + el cierre al ask con sus 3 persecuciones de 1 s (decisión 13) + 5 s de holgura.
GRACIA_REAPERTURA_S = 2.0 + 3 * 1.0 + 5.0
CLAVE_AVISO_HALT = "vigilante_halt"                 # decisión 61: aviso (2) de lo que el vigilante retiene en un halt

_LOTE_MUERTO = (EstadoLote.CERRADO, EstadoLote.CANCELADO)
_D = Decimal
_TRAMO_2_50 = _D("2.50")
_TRAMO_5 = _D("5")
_TRAMO_16_67 = _D("16.67")
_TREINTA_PCT = _D("0.30")
_CIEN = _D("100")


@dataclass(frozen=True)
class Foto:
    """Lo que el vigilante ve en una pasada (§3.25). Los campos tras `equity` son opcionales sobre el documento.

    posiciones: %IPOS por ticker (neta SIGNADA, `protocolo.normalizar_pos`).
    ordenes: %IORDER por id de DAS (todas: propias, del ejecutor y ajenas).
    lotes: lotes por ticker según los diarios (`diario.reconstruir`).
    latido_ejecutor_s: edad del latido del ejecutor (None = no hay latido).
    cotizaciones: $Quote de DAS por ticker. gasto_locates: gasto del día en
    locates (diario). compras_locate: registros «locate_intencion» y
    «locate_estado» del día. equity: None si no se conoce.
    descubierta_desde: monotónico desde el que cada ticker está descubierto
    (lo lleva el proceso con `actualizar_descubierta_desde`). limit_up:
    banda por ticker (R-F-02). pendientes: órdenes que el vigilante envió y
    DAS aún no ha devuelto. estados_ticker: estado de cada ticker según el
    diario (BS → no se repone, R-G-03). locates_deshabilitados: ya se
    deshabilitaron (no se repite (d)).
    """
    posiciones: dict[str, MsgPos]
    ordenes: dict[int, MsgOrden]
    lotes: dict[str, list[Lote]]
    latido_ejecutor_s: Optional[float]
    cotizaciones: dict[str, Cotizacion]
    gasto_locates: Decimal
    compras_locate: list[Registro]
    equity: Optional[Decimal]
    descubierta_desde: dict[str, float] = field(default_factory=dict)
    limit_up: dict[str, Decimal] = field(default_factory=dict)
    pendientes: list[Orden] = field(default_factory=list)
    estados_ticker: dict[str, EstadoTicker] = field(default_factory=dict)
    locates_deshabilitados: bool = False
    anotado: dict[str, str] = field(default_factory=dict)   # E2c-04: firma de lo último anotado por ticker (la devuelve
    #                                                         `comprobar_con_firmas`; el proceso la trae a la foto siguiente)
    locates_tope_dia: bool = False  # decisión 50 (Jaume 1-oct): el ejecutor ya cortó las compras por el tope del día
    # Decisión 61 (Jaume 2-oct): lo que el vigilante sabe de los halts por SU conexión (`$IssueStatus`/`$SymStatus`):
    # tickers PARADOS ahora (TA H/P/Q) y, de los que reabrieron, el monotónico de la reapertura (margen de gracia)
    parados: frozenset = frozenset()
    reabiertos: dict[str, float] = field(default_factory=dict)


@dataclass
class _Vista:
    """Un ticker tal como lo ve el vigilante (interno)."""
    ticker: str
    neta: int
    pos: PosicionTicker
    lotes: list[Lote]
    vivas: list[Orden]
    limit_up: Optional[Decimal]
    cot: Optional[Cotizacion]
    avg: Optional[Decimal]
    manual: int = 0                 # D10 (Jaume 30-sep): lo que cubren los stops VIVOS del humano en este ticker


# ── API pública ──────────────────────────────────────────────────────────
def comprobar(foto: Foto, cfg: Any, ahora: float, tokens: Callable[[], int], hora_et: datetime, ruta_stop: str,
              puede_enviar: bool) -> list[Accion]:
    """R-C-07 plan B, R-C-08, R-C-10 (4), R-C-11 (c), R-H-02/03, 2c, corrección 16: una pasada del vigilante (ver QUÉ HACE).

    `tokens` es el generador del VIGILANTE (`GeneradorTokens(Origen.VIGILANTE,
    hoy).siguiente`): el token dice quién puso cada orden. `cfg` es la
    `Config` (o un dict con «stops», «tecnicos» y «locates»). Orden de la
    salida: por ticker (alfabético) `Anotar("vigilancia")` ANTES de sus
    órdenes (write-ahead, §8) y sus avisos de precio; después (g), (d) y (e).
    """
    return comprobar_con_firmas(foto, cfg, ahora, tokens, hora_et, ruta_stop, puede_enviar)[0]


def comprobar_con_firmas(foto: Foto, cfg: Any, ahora: float, tokens: Callable[[], int], hora_et: datetime,
                         ruta_stop: str, puede_enviar: bool) -> tuple[list[Accion], dict[str, str]]:
    """`comprobar` + las firmas de lo propuesto por ticker (E2c-04: no llenar el diario con una línea por segundo).

    Devuelve (acciones, firmas). `firmas` = {ticker: firma} de los tickers con
    algo que proponer en esta pasada; el proceso vigilante la guarda y la pasa
    en `Foto.anotado` de la pasada siguiente. Con el ejecutor vivo y la MISMA
    propuesta que ya se anotó, no se vuelve a anotar; en cuanto cambia (o el
    vigilante actúa, o el ticker cuadra y vuelve a descuadrar) se anota. Con
    `Foto.anotado` vacío (llamador antiguo) se anota en cada pasada, como antes.
    Lo que el vigilante HACE (acciones reales) se anota siempre antes de hacerlo
    (write-ahead, §8).
    """
    cfg_stops = _bloque(cfg, "stops", requerido=True)
    vig = _bloque(_bloque(cfg, "tecnicos"), "vigilante")
    plan_b_latido = _segundos(vig.get("plan_b_latido_s"), PLAN_B_LATIDO_S)
    plan_b_descubierta = _segundos(vig.get("plan_b_descubierta_s"), PLAN_B_DESCUBIERTA_S)
    hoy = hora_et.date()
    muerto = foto.latido_ejecutor_s is None or foto.latido_ejecutor_s > plan_b_latido
    silencio = _silencio(cfg)
    salida: list[Accion] = []
    firmas: dict[str, str] = {}
    bloqueadas = False
    for vista in _vistas(foto, cfg_stops, hoy):
        desc = _descubiertas(vista, cfg_stops)
        desde = foto.descubierta_desde.get(vista.ticker)
        # Decisión 61: tras reabrir un halt el ejecutor está cerrando (decisión 57): no se da por descubierta antes de
        # la gracia (con el ejecutor MUERTO nadie cierra: se actúa como siempre)
        en_gracia = silencio and _en_gracia(foto, vista.ticker, ahora)
        actua = muerto or (desc > 0 and desde is not None and ahora - desde > plan_b_descubierta and not en_gracia)
        propuesta, reales, motivo = _que_hacer(vista, cfg, cfg_stops, tokens, hora_et, ruta_stop, actua, muerto)
        retenidas: list[Accion] = []
        if silencio and vista.ticker in foto.parados and any(isinstance(a, MUTANTES) for a in reales):
            reales, retenidas = _filtrar_halt(vista, reales)
            motivo = (f"{motivo}; decisión 61: {vista.ticker} en HALT, el vigilante no envía nada salvo el stop de "
                      f"acciones sin ningún stop")
        if propuesta:
            enviar = [a for a in reales if isinstance(a, MUTANTES)]
            bloqueo = bool(enviar) and not puede_enviar
            bloqueadas = bloqueadas or bloqueo
            datos = {
                "ticker": vista.ticker, "neta": vista.neta, "descubiertas": desc, "actua": actua and not bloqueo,
                "motivo": motivo, "latido_ejecutor_s": foto.latido_ejecutor_s, "puede_enviar": puede_enviar,
                "faltan": [_describir(a) for a in propuesta if isinstance(a, EnviarOrden)],
                "sobran": [_describir(a) for a in propuesta if isinstance(a, (Cancelar, CancelarTicker))],
                "ajustes": [_describir(a) for a in propuesta if isinstance(a, Reemplazar)],
                "acciones": [_describir(a, con_token=True) for a in reales], "bloqueado": bloqueo,
                "regla": "R-C-07 plan B / R-C-08"}
            if retenidas:
                datos["halt_retenidas"] = [_describir(a) for a in retenidas]     # decisión 61
            firma = _firma(datos)
            firmas[vista.ticker] = firma
            if any(isinstance(a, MUTANTES) for a in reales) or foto.anotado.get(vista.ticker) != firma:
                salida.append(Anotar(TIPO_ANOTACION, {**datos, "firma": firma}))
            salida.extend(a for a in reales if not (bloqueo and isinstance(a, MUTANTES)))
            if retenidas:
                salida.append(Avisar(nivel=Nivel.AVISO, grupo=Grupo.B, clave=f"{CLAVE_AVISO_HALT}:{vista.ticker}",
                                     texto=(f"Decisión 61: {_esc(vista.ticker)} está en HALT: el vigilante NO envía "
                                            f"nada hasta que reabra ({len(retenidas)} órdenes retenidas: "
                                            f"{_esc(', '.join(_describir(a) for a in retenidas))}); el stop residente "
                                            f"sigue. Posición {vista.neta:+d}")))
        salida.extend(_avisos_precio(vista, foto, cfg_stops, muerto))
    if bloqueadas:
        salida.append(Avisar(nivel=Nivel.MAXIMO, grupo=Grupo.B, clave="vigilante_sin_envio",
                             texto=("R-C-07 plan B: el vigilante tiene que reponer stops y NO puede enviar órdenes (sin "
                                    "conexión de acción); se pide al supervisor relanzar el ejecutor")))
        salida.append(PedirAlSupervisor(PETICION_RELANZAR_EJECUTOR))
    salida.extend(_locates(foto, cfg, hoy))
    salida.extend(_margen(foto, vig))
    return salida, firmas


def descubiertas_por_ticker(foto: Foto, cfg: Any, hoy: date) -> dict[str, int]:
    """R-C-03 / plan B: acciones cortas (o largas desconocidas) sin un stop CONFIRMADO que las cubra, por ticker (> 0).

    Es lo que el proceso vigilante pasa a `actualizar_descubierta_desde` en
    cada pasada. Con lotes: `stops.descubiertas` (el stop de cada nivel o una
    protección, Accepted/Partial/Hold/Triggered); sin lotes: lo que no cubre
    una STOPLMTP nuestra confirmada del lado que reduce.
    """
    cfg_stops = _bloque(cfg, "stops", requerido=True)
    salida: dict[str, int] = {}
    for vista in _vistas(foto, cfg_stops, hoy):
        desc = _descubiertas(vista, cfg_stops)
        if desc > 0:
            salida[vista.ticker] = desc
    return salida


def actualizar_descubierta_desde(previas: Mapping[str, float], actuales: Mapping[str, int], ahora: float) -> dict[str, float]:
    """Plan B (PLAN_B_DESCUBIERTA_S): conserva el inicio de las que siguen descubiertas, estrena las nuevas y olvida las cubiertas."""
    return {ticker: previas.get(ticker, ahora) for ticker, qty in actuales.items() if qty > 0}


def debe_hacer_ping(watch_conectado: bool, latido_ejecutor_s: Optional[float], dentro_de_ventana: bool,
                    max_latido_s: float = PLAN_B_LATIDO_S) -> bool:
    """R-J-05: el ping externo (cada 60 s) solo sale si TODO va bien; su silencio es la alarma (3 fallos = 3 min).

    Fuera de la ventana de encendido (R-L-01) no se pinga. Dentro, hace falta
    la conexión watch viva y un latido del ejecutor fresco (≤ `max_latido_s`,
    opcional sobre §3.25): un ejecutor que no vuelve en 3 min lo ve el
    servicio externo aunque el vigilante siga vivo.
    """
    if not dentro_de_ventana or not watch_conectado or latido_ejecutor_s is None:
        return False
    return 0 <= latido_ejecutor_s <= max_latido_s


def compras_repetidas(registros: Iterable[Registro], hoy: date) -> list[dict]:
    """R-H-02: (ticker, estrategia) del día con más compras Located que peticiones («locate_intencion»), y al menos dos.

    Una compra = entrar en Located (o un Located con un id de DAS distinto del
    anterior). Una actualización del mismo Located (usadas, coste) no cuenta.
    Sin ninguna intención registrada, dos compras ya son repetidas. Solo
    registros del día `hoy` (por el prefijo de `t`).
    """
    compras: dict[tuple[str, str], int] = {}
    pedidas: dict[tuple[str, str], int] = {}
    previo: dict[tuple[str, str], Optional[str]] = {}
    ultimo_id: dict[tuple[str, str], Optional[int]] = {}
    for r in sorted(registros, key=lambda r: (str(r.t), str(r.proceso), r.seq)):
        if r.tipo not in ("locate_intencion", "locate_estado") or not _es_de_hoy(r, hoy):
            continue
        ticker, sid = r.datos.get("ticker"), r.datos.get("strategy_id")
        if ticker is None or sid is None or not str(ticker).strip():
            continue
        clave = (str(ticker).strip(), str(sid))
        if r.tipo == "locate_intencion":
            pedidas[clave] = pedidas.get(clave, 0) + 1
            continue
        estado = r.datos.get("estado")
        id_das = _entero(r.datos.get("id_das"))
        if estado == LOCATE_LOCATED:
            anterior = ultimo_id.get(clave)
            if previo.get(clave) != LOCATE_LOCATED or (id_das is not None and anterior is not None and id_das != anterior):
                compras[clave] = compras.get(clave, 0) + 1
            if id_das is not None:
                ultimo_id[clave] = id_das
        if estado is not None:
            previo[clave] = str(estado)
    return [{"ticker": t, "strategy_id": s, "compras": n, "pedidas": pedidas.get((t, s), 0)}
            for (t, s), n in sorted(compras.items()) if n >= 2 and n > max(pedidas.get((t, s), 0), 1)]


def margen_mantenimiento_corto(precio: Decimal, qty: int) -> Decimal:
    """2c (FINRA 4210, cortos): < 2,50 $ → 2,50 $/acción; 2,50-4,99 → 100 % del valor; 5-16,66 → 5 $/acción; ≥ 16,67 → 30 %."""
    p = de_float(precio)
    if p <= 0 or type(qty) is not int or qty < 0:
        raise ValueError(f"precio o cantidad inválidos para el margen: {precio!r} × {qty!r}")
    if p < _TRAMO_2_50:
        return _TRAMO_2_50 * qty
    if p < _TRAMO_5:
        return p * qty
    if p < _TRAMO_16_67:
        return _TRAMO_5 * qty
    return _TREINTA_PCT * p * qty


# ── privados (puros) ──────────────────────────────────────────────────────
def _bloque(cfg: Any, nombre: str, requerido: bool = False) -> Mapping:
    valor = cfg.get(nombre) if isinstance(cfg, Mapping) else getattr(cfg, nombre, None)
    if isinstance(valor, Mapping):
        return valor
    if requerido:
        raise ValueError(f"el bloque {nombre!r} de la config falta o no es un dict")
    return {}


def _silencio(cfg: Any) -> bool:
    """`halts.silencio` del cuadro (defecto true, decisión 57); un valor que no es bool cuenta como true (lo seguro)."""
    valor = _bloque(cfg, "halts").get("silencio", True)
    return valor if isinstance(valor, bool) else True


def _en_gracia(foto: Foto, ticker: str, ahora: float) -> bool:
    """Decisión 61: ¿el ticker reabrió hace menos de `GRACIA_REAPERTURA_S`? (el ejecutor lo está cerrando o mirando)."""
    reabierto = foto.reabiertos.get(ticker)
    return reabierto is not None and 0 <= ahora - reabierto < GRACIA_REAPERTURA_S


def _filtrar_halt(vista: _Vista, reales: list[Accion]) -> tuple[list[Accion], list[Accion]]:
    """Decisión 61 (Jaume 2-oct): con el símbolo PARADO el vigilante no envía órdenes nuevas ni toca stops. ÚNICA
    excepción, la misma que el ejecutor (decisión 57): acciones CORTAS sin ningún stop vivo → sale el stop (o la
    protección) para ellas, nunca por más acciones de las que no tienen ninguno. Sustituir un stop vivo por otro,
    reducirlo, cancelar huérfanas o vender el exceso: nada (se retiene). Devuelve (lo que sale, lo retenido)."""
    sin_stop = 0
    if vista.neta < 0:
        sin_stop = max(abs(vista.neta) - reconciliacion.cobertura(vista.vivas, vista.ticker, vista.neta) - vista.manual,
                       0)
    stops_nuevos = [a for a in reales if isinstance(a, EnviarOrden) and a.orden.lado is Lado.COMPRA
                    and a.orden.tipo is TipoOrden.STOP_LIMITE_PP]
    if not stops_nuevos or sum(a.orden.qty for a in stops_nuevos) > sin_stop:
        stops_nuevos = []
    retenidas = [a for a in reales if isinstance(a, MUTANTES) and a not in stops_nuevos]
    return [a for a in reales if a not in retenidas], retenidas


def _segundos(valor: Any, defecto: float) -> float:
    if isinstance(valor, bool) or not isinstance(valor, (int, float, Decimal)):
        return float(defecto)
    segundos = float(valor)
    return segundos if segundos > 0 else float(defecto)


def _entero(x: Any) -> Optional[int]:
    if isinstance(x, bool):
        return None
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _es_de_hoy(r: Registro, hoy: date) -> bool:
    t = str(r.t)
    return len(t) < 10 or t[:10] == hoy.isoformat()


def _precio(x: Any) -> Optional[Decimal]:
    if x is None or isinstance(x, bool):
        return None
    try:
        valor = de_float(x)
    except ValueError:
        return None
    return valor if valor > 0 else None


def _lote_vivo(lote: Lote) -> bool:
    return lote.estado not in _LOTE_MUERTO and type(lote.llenas) is int and lote.llenas > 0


def _nivel_valido(lote: Lote) -> Optional[Decimal]:
    nivel = lote.nivel_stop
    return nivel if isinstance(nivel, Decimal) and nivel.is_finite() and nivel > 0 else None


def _vistas(foto: Foto, cfg_stops: Mapping, hoy: date) -> list[_Vista]:
    """Por ticker listado en las posiciones: neta de DAS, lotes vivos del diario y órdenes NUESTRAS vivas (+ pendientes)."""
    vivas: dict[str, list[Orden]] = {}
    tokens_das: set[int] = set()
    ordenes = reconciliacion.fusionar_madres_hijas(foto.ordenes)   # decisión 64: madre SMAT + hija = UNA orden
    for id_das in sorted(ordenes):
        m = ordenes[id_das]
        if reconciliacion.es_ajena(m, hoy):
            continue
        tokens_das.add(m.token)   # type: ignore[arg-type]
        if m.estado in stops.ESTADOS_VIVOS:
            o = reconciliacion.orden_de_msg(m, hoy, None, cfg_stops)
            if o is not None:
                vivas.setdefault(o.ticker, []).append(o)
    for o in foto.pendientes:
        if isinstance(o, Orden) and o.token not in tokens_das and o.estado in stops.ESTADOS_VIVOS:
            vivas.setdefault(o.ticker, []).append(o)
    salida: list[_Vista] = []
    for ticker in sorted(foto.posiciones):
        neta = int(foto.posiciones[ticker].neta)
        lotes = [lote for lote in foto.lotes.get(ticker, [])
                 if isinstance(lote, Lote) and _lote_vivo(lote) and _nivel_valido(lote) is not None]
        pos = PosicionTicker(ticker=ticker, lotes={lote.id: lote for lote in lotes}, neta_fills=neta, neta_das=neta,
                             estado=foto.estados_ticker.get(ticker, EstadoTicker.NORMAL))
        salida.append(_Vista(ticker=ticker, neta=neta, pos=pos, lotes=lotes, vivas=vivas.get(ticker, []),
                             limit_up=_precio(foto.limit_up.get(ticker)), cot=foto.cotizaciones.get(ticker),
                             avg=_precio(foto.posiciones[ticker].avg),
                             manual=reconciliacion.cobertura_manual(foto.ordenes.values(), ticker, neta, hoy, cfg_stops)))
    return salida


def _descubiertas(vista: _Vista, cfg_stops: Mapping) -> int:
    """Acciones sin stop CONFIRMADO (R-C-03). Con lotes cortos: `stops.descubiertas`; sin lotes: por cobertura."""
    if vista.neta == 0:
        return 0
    if vista.lotes:
        return stops.descubiertas(vista.pos, vista.vivas, cfg_stops, vista.limit_up) if vista.neta < 0 else 0
    # D10 (Jaume 30-sep): sin lotes, el stop VIVO del humano también cubre (el bot se fía de él)
    return max(abs(vista.neta) - reconciliacion.cobertura(vista.vivas, vista.ticker, vista.neta, solo_confirmadas=True)
               - vista.manual, 0)


def _token_prueba() -> int:
    """Token de la simulación: lo que no se envía no gasta la secuencia del vigilante."""
    return 1


def _sin_temporizadores(acciones_: Iterable[Accion]) -> list[Accion]:
    return [a for a in acciones_ if not isinstance(a, (Programar, Consultar, InvalidarSerie))]


def _cancelar(ordenes: Iterable[Orden], motivo: str) -> list[Accion]:
    return [Cancelar(id_das=o.id_das, token=o.token, motivo=motivo) for o in ordenes if o.id_das is not None]


def _que_hacer(vista: _Vista, cfg: Any, cfg_stops: Mapping, tokens: Callable[[], int], hora_et: datetime,
               ruta_stop: str, actua: bool, muerto: bool) -> tuple[list[Accion], list[Accion], str]:
    """(lo que haría falta, lo que se hace AHORA, motivo). `propuesta` vacía = todo cuadra (no se anota nada)."""
    t, neta = vista.ticker, vista.neta
    if neta < 0 and vista.lotes:
        prueba = stops.plan(vista.pos, vista.vivas, cfg_stops, vista.limit_up, _token_prueba, hora_et, ruta_stop, 0)
        propuesta = [a for a in prueba if isinstance(a, MUTANTES + (Avisar,))]
        if not propuesta:
            return [], [], ""
        if not actua:
            return propuesta, [], "ejecutor vivo y la posición no lleva descubierta el plazo del plan B"
        reales = _sin_temporizadores(stops.plan(vista.pos, vista.vivas, cfg_stops, vista.limit_up, tokens, hora_et,
                                                ruta_stop, 0))
        return propuesta, reales, "R-C-07 plan B: el vigilante repone el stop de cada nivel"
    if neta != 0 and not vista.lotes:
        falta = abs(neta) - reconciliacion.cobertura(vista.vivas, t, neta)
        sobran = reconciliacion.huerfanas(vista.vivas, t, neta)
        if vista.manual > 0 and falta > 0:
            return _con_stop_manual(vista, falta, sobran, actua, muerto)
        if falta <= 0 and not sobran:
            return [], [], ""
        avisos = [] if falta <= 0 else [Avisar(
            nivel=Nivel.MAXIMO, grupo=Grupo.B, clave=f"vigilante_desconocida:{t}",
            texto=(f"R-C-10 (4): {t} tiene una posición ({neta}) sin lote con nivel de stop en ningún diario; "
                   f"{falta} acciones sin stop"))]
        cancelaciones = _cancelar(sobran, f"R-C-11: orden huérfana en {t} ({neta})")
        if not actua:
            return avisos + cancelaciones, [], "posición desconocida: la protege el ejecutor (R-C-10 caso 4)"
        proteccion = _proteccion(vista, falta, cfg_stops, tokens, ruta_stop) if falta > 0 else []
        return avisos + cancelaciones, proteccion + cancelaciones + avisos, "R-C-10 (4): posición sin lote en ningún diario"
    sobran = reconciliacion.huerfanas(vista.vivas, t, neta)
    if neta > 0 and vista.lotes:
        if muerto:
            # E2c-02 (R-C-11 (3) «ejecutor + vigilante»; el libro manda sobre §3.25): con el ejecutor muerto el
            # vigilante VENDE SOLO el exceso con SUS tokens (Origen.VIGILANTE), sujeto a `puede_enviar`. La venta
            # que ya esté viva (suya o del ejecutor) se descuenta: nunca vende de más ni deja un corto sin stops.
            limpieza = _sin_temporizadores(stops.limpieza_tras_fill_stop(
                vista.pos, vista.vivas, vista.cot, tokens, cfg, hora_et, 0, limit_up=vista.limit_up))
            vende = sum(a.orden.qty for a in limpieza if isinstance(a, EnviarOrden))
            if not any(isinstance(a, MUTANTES) for a in limpieza):
                # la venta del exceso ya está en marcha (suya o del ejecutor): nada que hacer, se anota al cambiar
                return ([Avisar(nivel=Nivel.MAXIMO, grupo=Grupo.B, clave=f"vigilante_larga:{t}",
                                texto=(f"R-C-11 (3): {_esc(t)} sigue LARGA {neta} con el ejecutor caído y la venta del "
                                       f"exceso en marcha. Si no llena, VENDER A MANO (cancelando antes la del bot)."))],
                        [], "R-C-11 (3) / E2c-02: venta del exceso ya en marcha")
            aviso = Avisar(nivel=Nivel.MAXIMO, grupo=Grupo.B, clave=f"vigilante_larga:{t}",
                           texto=(f"R-C-11 (3): {_esc(t)} está LARGA {neta} con lotes cortos y el ejecutor caído: el "
                                  f"vigilante VENDE el exceso ({vende} acciones) y cancela las compras. Si no llena, "
                                  f"VENDER A MANO (cancelando antes la venta del bot)."))
            reales = limpieza + [aviso]
            return reales, reales, "R-C-11 (3) / E2c-02: cuenta larga con el ejecutor muerto: el vigilante vende el exceso"
        propuesta = [Avisar(nivel=Nivel.MAXIMO, grupo=Grupo.B, clave=f"vigilante_larga:{t}",
                            texto=(f"R-C-11 (3): {_esc(t)} está LARGA {neta} con lotes cortos en el diario; la venta del "
                                   f"exceso la hace el ejecutor (vivo). Si no, VENDER A MANO {neta}"))]
        propuesta.extend(_cancelar(sobran, f"R-C-11 (3): {t} larga: no se compra más"))
        return propuesta, [], "cuenta larga: la limpia el ejecutor (R-C-11)"
    if not sobran:
        return [], [], ""
    propuesta = _cancelar(sobran, f"R-C-11 (2): {t} plana: se cancela lo nuestro que queda vivo")
    if not propuesta:
        return [], [], ""
    return (propuesta, propuesta, "R-C-11 (2): órdenes huérfanas con el ejecutor muerto") if muerto else \
        (propuesta, [], "órdenes huérfanas: las cancela el ejecutor (R-C-11)")


def _con_stop_manual(vista: _Vista, falta: int, sobran: list[Orden], actua: bool,
                     muerto: bool) -> tuple[list[Accion], list[Accion], str]:
    """D10 (Jaume 30-sep): posición sin lotes con un stop VIVO del humano → el vigilante SE FÍA y nunca pone protección.

    Si el stop cubre menos que lo que falta, Avisar(2) «el stop manual de X
    cubre N de M acciones»; ese aviso solo SALE con el ejecutor muerto (con el
    ejecutor vivo ya lo da su reconciliación, una vez al día): si no, queda en
    la propuesta (se anota con su firma). Las huérfanas se cancelan como
    siempre cuando le toca actuar.
    """
    t, neta = vista.ticker, vista.neta
    sin_cubrir = max(falta - vista.manual, 0)
    avisos: list[Accion] = [] if sin_cubrir == 0 else [Avisar(
        nivel=Nivel.AVISO, grupo=Grupo.B, clave=f"vigilante_stop_manual:{t}",
        texto=(f"D10: el stop manual de {_esc(t)} cubre {min(vista.manual, abs(neta))} de {abs(neta)} acciones; el bot "
               f"NO pone su protección (ni por la parte sin cubrir): revisar el stop a mano"))]
    cancelaciones = _cancelar(sobran, f"R-C-11: orden huérfana en {t} ({neta})")
    propuesta = avisos + cancelaciones
    if not propuesta:
        return [], [], ""
    reales = (cancelaciones if actua else []) + (avisos if muerto else [])
    return propuesta, reales, "D10: el bot se fía del stop manual del humano (sin protección del bot)"


def _proteccion(vista: _Vista, falta: int, cfg_stops: Mapping, tokens: Callable[[], int], ruta_stop: str) -> list[Accion]:
    """R-C-10 (4) por el vigilante: `stops.stop_proteccion` sobre el último precio de DAS.

    Sin último: el lado que dispararía (ask si corta, bid si larga), el otro y,
    sin cotización, el precio medio de la posición en DAS. Sin ningún precio,
    aviso 3 para ponerla a mano. Porcentaje: `stops.proteccion_desconocidas_pct`
    (defecto `STOP_PROTECCION_PCT`, 25 %); límite: el del stop único,
    `stops.limite_pct` (defecto `STOP_LIMITE_PCT`, 50 %, Jaume 29-sep).
    """
    t, neta = vista.ticker, vista.neta
    precio: Optional[Decimal] = None
    for campo in (("last", "ask", "bid") if neta < 0 else ("last", "bid", "ask")):
        precio = _precio(getattr(vista.cot, campo, None))
        if precio is not None:
            break
    precio = precio if precio is not None else vista.avg
    if precio is None:
        return [Avisar(nivel=Nivel.MAXIMO, grupo=Grupo.B, clave=f"vigilante_sin_precio:{t}",
                       texto=f"R-C-10 (4): {t} tiene {falta} acciones sin stop y no hay precio: PONER LA PROTECCIÓN A MANO")]
    pct = _pct(cfg_stops.get("proteccion_desconocidas_pct"), STOP_PROTECCION_PCT)
    ancho = _pct(cfg_stops.get("limite_pct"), STOP_LIMITE_PCT)
    orden = stops.stop_proteccion(t, falta, neta < 0, precio, pct, tokens(), ruta_stop, 0, limite_pct=ancho)
    return [EnviarOrden(orden=orden)]


def _firma(datos: Mapping[str, Any]) -> str:
    """E2c-04: lo que identifica una propuesta (sin el latido ni los tokens, que cambian en cada pasada)."""
    partes = [str(datos.get(clave)) for clave in ("motivo", "neta", "descubiertas", "actua", "bloqueado", "puede_enviar")]
    for clave in ("faltan", "sobran", "ajustes"):
        partes.append(",".join(sorted(str(x) for x in datos.get(clave) or ())))
    return "|".join(partes)


def _esc(texto: Any) -> str:
    """D2-08: texto variable hacia Telegram (parse_mode HTML) escapado."""
    return html.escape(str(texto), quote=False)


def _describir(a: Accion, con_token: bool = False) -> str:
    """Texto corto de una acción para el diario (el token solo en las REALES: el de la simulación no existe)."""
    if isinstance(a, EnviarOrden):
        o = a.orden
        texto = f"{o.proposito.value} {o.lado.value} {o.qty} {o.stop}/{o.precio}"
        return f"{texto} token {o.token}" if con_token else texto
    if isinstance(a, Reemplazar):
        return f"reemplazar {a.id_das} a {a.qty}"
    if isinstance(a, Cancelar):
        return f"cancelar {a.id_das}"
    if isinstance(a, CancelarTicker):
        return f"cancelar todo {a.ticker}"
    if isinstance(a, Avisar):
        return f"aviso {int(a.nivel)}"
    return type(a).__name__


def _avisos_precio(vista: _Vista, foto: Foto, cfg_stops: Mapping, muerto: bool) -> list[Accion]:
    """R-C-08 (a), SOLO aviso: el ask pasó el límite del stop de un nivel (L + 50 %) sin fill; con el ejecutor muerto y el
    primero ya pasado, aviso 3 de cisne negro (R-G-01 v4, Jaume 29-sep: con el stop único el límite pasado es el del
    stop de ese nivel; en v3 se esperaba al de la emergencia)."""
    if vista.neta >= 0 or not vista.lotes:
        return []
    cot = foto.cotizaciones.get(vista.ticker)
    precio = _precio(getattr(cot, "ask", None)) or _precio(getattr(cot, "last", None))
    if precio is None:
        return []
    salida: list[Accion] = []
    niveles_vivos = sorted({n for n in (_nivel_valido(lote) for lote in vista.lotes) if n is not None})
    pasados: list[tuple[Decimal, Decimal]] = []
    for L in niveles_vivos:
        limite = stops.niveles(L, cfg_stops, vista.limit_up).limite
        if precio > limite:
            pasados.append((L, limite))
            salida.append(Avisar(nivel=Nivel.AVISO, grupo=Grupo.B, clave=f"vigilante_nivel:{vista.ticker}:{L}",
                                 texto=(f"R-C-08 (a): el precio {precio} de {vista.ticker} pasó el límite {limite} del "
                                        f"stop de {L} sin fill; el vigilante solo avisa (cerrar: PENDIENTE)")))
    if muerto and pasados and vista.pos.estado is not EstadoTicker.BS:
        L, limite = pasados[0]
        salida.append(Avisar(nivel=Nivel.MAXIMO, grupo=Grupo.B, clave=f"vigilante_bs:{vista.ticker}",
                             texto=(f"R-G-01 / R-C-08: {vista.ticker} a {precio}, por encima del límite {limite} del stop "
                                    f"de {L} con el ejecutor caído: CISNE NEGRO, el vigilante NO cierra")))
    return salida


def _locates(foto: Foto, cfg: Any, hoy: date) -> list[Accion]:
    """(d) R-H-02 y R-H-03: el vigilante corta las compras de locates si el ejecutor se descontrola."""
    if foto.locates_deshabilitados:
        return []
    motivos: list[str] = []
    datos: dict[str, Any] = {}
    repetidas = compras_repetidas(foto.compras_locate, hoy)
    if repetidas:
        motivos.append("R-H-02")
        datos["repetidas"] = repetidas
    tope = _tope_usd(_bloque(cfg, "locates").get("tope_gasto_dia_usd"))
    gasto = _precio(foto.gasto_locates) or _D("0")
    # Decisión 50 (Jaume 1-oct): si el ejecutor ya CORTÓ el día por el tope (locates_tope_global), un gasto algo por
    # encima es el de una compra que DAS ya había servido antes de cancelarla (se contabiliza): no es un descontrol y la
    # red de R-H-03 no repite el aviso máximo. La de R-H-02 (compra repetida no pedida) sigue igual.
    # Decisión 60 (Jaume 2-oct): el tope son dólares fijos del cuadro (`locates.tope_gasto_dia_usd`), sin equity.
    if not foto.locates_tope_dia and gasto > tope:
        motivos.append("R-H-03")
        datos.update({"gasto": str(gasto), "tope": str(tope)})
    if not motivos:
        return []
    texto = "; ".join(
        (f"R-H-02: compra de locate repetida no pedida en {', '.join(r['ticker'] + '/' + r['strategy_id'] for r in repetidas)}"
         if m == "R-H-02" else f"R-H-03: gasto en locates {gasto} $ > tope del día {tope} $")
        for m in motivos)
    return [Avisar(nivel=Nivel.MAXIMO, grupo=Grupo.B, clave="vigilante_locates",
                   texto=f"{texto}. El vigilante DESHABILITA las compras de locates"),
            Anotar(TIPO_DESHABILITAR_LOCATES, {**datos, "motivos": motivos, "regla": "/".join(motivos)})]


def _tope_usd(valor: Any) -> Decimal:
    """Decisión 60: `locates.tope_gasto_dia_usd` (> 0) o el defecto de tipos (400 $)."""
    if valor is None or isinstance(valor, bool):
        return LOCATES_TOPE_GASTO_DIA_USD
    try:
        tope = de_float(valor)
    except (ValueError, TypeError):
        return LOCATES_TOPE_GASTO_DIA_USD
    return tope if tope.is_finite() and tope > 0 else LOCATES_TOPE_GASTO_DIA_USD


def _pct(valor: Any, defecto: Decimal) -> Decimal:
    if valor is None:
        return defecto
    pct = de_float(valor)
    if pct < 0:
        raise ValueError(f"porcentaje negativo en la config: {valor!r}")
    return pct


def _margen(foto: Foto, vig: Mapping) -> list[Accion]:
    """(e) 2c: margen de mantenimiento total de los cortos frente a equity·margen_aviso → Avisar(2). Sin equity no se evalúa."""
    if foto.equity is None:
        return []
    fraccion = _pct(vig.get("margen_aviso"), MARGEN_AVISO_DEFECTO)
    total = _D("0")
    for ticker in sorted(foto.posiciones):
        msg = foto.posiciones[ticker]
        if int(msg.neta) >= 0:
            continue
        cot = foto.cotizaciones.get(ticker)
        precio = (_precio(getattr(cot, "last", None)) or _precio(getattr(cot, "ask", None))
                  or _precio(getattr(cot, "bid", None)) or _precio(msg.avg))
        if precio is not None:
            total += margen_mantenimiento_corto(precio, -int(msg.neta))
    umbral = foto.equity * fraccion
    if total <= umbral:
        return []
    return [Avisar(nivel=Nivel.AVISO, grupo=Grupo.B, clave="vigilante_margen",
                   texto=(f"2c: margen de mantenimiento de los cortos {total.quantize(_D('0.01'))} $ supera "
                          f"{fraccion} × equity ({foto.equity} $): riesgo de autoliquidación en RTH"))]
