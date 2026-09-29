"""Tests de reglas/salidas.py (documento §3.17 y fila de §10; R-D-02/03/04/06/07/08, R-E-03, R-L-01, riesgo 24).

QUÉ DEMUESTRA. Que `LITERALES_EXIT_REASON` cubre TODOS los `exit_reason` del
fichero real `portfolio_sim.py` (extraídos con regex, incluida la f-string
«Lot TP») y el «?» del motor; el tratamiento de cada `ClaseSalida`; los
temporizadores t−60/t/t+30; la persecución al ask por REPLACE y como mucho 3;
el techo del TP dentro/fuera del 3 %; la prioridad de R-D-07; «cerrar todo»
con posiciones manuales; `puede_reentrar` (−1/0/N × true/false, con paridad
contra el if/elif del backtester); `ultimo_eod` con dos estrategias y
`al_desactivar` esperar/cerrar.

POR QUÉ ESTÁ AQUÍ. Las reglas son puras: se prueban con tablas sin DAS, sin
red y sin reloj real. La config se construye a partir de
`fixtures/config_ejemplo.json` sin pasar por `config.py` (otro lote).

LAS TRAMPAS. El test de literales LEE el fichero real del motor: si alguien
añade un `exit_reason` nuevo sin clasificarlo aquí, este test falla (riesgo
24). Nada de floats: todos los precios son `Decimal`.
"""
from __future__ import annotations

import copy
import itertools
import json
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pytest

from app.bot_das.reglas import salidas
from app.bot_das.reglas.salidas import (
    CLAVE_CERRAR_TODO,
    LITERALES_EXIT_REASON,
    MOTIVO_REENTRADA_BS,
    MOTIVO_REENTRADA_INVALIDO,
    MOTIVO_REENTRADA_LOTE_VIVO,
    MOTIVO_REENTRADA_NO_ACEPTA,
    MOTIVO_REENTRADA_PRIMERA,
    MOTIVO_REENTRADA_TOPE,
    MOTIVO_REENTRADA_VETO,
    TRATAR_ANOTAR,
    TRATAR_COMO_TP,
    TRATAR_DIVERGENCIA,
    TRATAR_HORA_EVENTO,
    TRATAR_IGNORAR,
    TRATAR_TP,
    al_desactivar,
    avisos_de_tratamiento,
    cerrar_todo,
    clasificar,
    comprobar_eod,
    es_literal_conocido,
    horas_de_salida,
    orden_al_ask,
    orden_cierre_posicion,
    orden_hora_agregar,
    perseguir_ask,
    prioridad,
    puede_reentrar,
    temporizadores_lote,
    tp_al_vencer,
    tp_parcial,
    tratamiento,
    ultimo_eod,
)
from app.bot_das.reloj import ET
from app.bot_das.tipos import (
    Anotar,
    Avisar,
    Cancelar,
    CancelarTicker,
    ClaseSalida,
    Config,
    Consultar,
    Cotizacion,
    EnviarOrden,
    EstadoLote,
    EstadoOrden,
    EstadoTicker,
    EstrategiaConfig,
    Fase,
    Grupo,
    Lado,
    Lote,
    Nivel,
    Orden,
    OrdenNueva,
    Origen,
    PosicionTicker,
    Programar,
    Proposito,
    Reemplazar,
    Senal,
    TipoOrden,
)

BACKEND = Path(__file__).resolve().parents[2]
PORTFOLIO_SIM = BACKEND / "app" / "services" / "portfolio_sim.py"
MOTOR_ALERTAS = BACKEND / "app" / "services" / "bot_alerts_engine.py"
CONFIG_EJEMPLO = Path(__file__).parent / "fixtures" / "config_ejemplo.json"
MODULO = BACKEND / "app" / "bot_das" / "reglas" / "salidas.py"

DIA = date(2026, 9, 25)
HORA = datetime(2026, 9, 25, 9, 45, tzinfo=ET)
HORA_PM = datetime(2026, 9, 25, 6, 30, tzinfo=ET)
D = Decimal


# ── fábricas ─────────────────────────────────────────────────────────────
def _config(salidas_extra: Optional[dict] = None) -> Config:
    """Config de tipos construida desde config_ejemplo.json (sin config.py, que es de otro lote)."""
    d = json.loads(CONFIG_EJEMPLO.read_text(encoding="utf-8"))
    bloque_salidas = copy.deepcopy(d["salidas"])
    for clave, valor in (salidas_extra or {}).items():
        if isinstance(valor, dict):
            bloque_salidas.setdefault(clave, {}).update(valor)
        else:
            bloque_salidas[clave] = valor
    return Config(schema_version=d["schema_version"], config_version=d["config_version"], sha256=d["sha256"],
                  motor_hash=d["motor_hash"], estrategias_hash=d["estrategias_hash"], generado_at=d["generado_at"],
                  fase=Fase(d["fase"]), vigilando=d["vigilando"], horario=d["horario"],
                  modo_seguridad=d["modo_seguridad"], lista_negra=d["lista_negra"],
                  pausar_entradas=d["pausar_entradas"], locates=d["locates"], entrada=d["entrada"],
                  salidas=bloque_salidas, stops=d["stops"], halts=d["halts"], exclusiones=d["exclusiones"],
                  rutas=d["rutas"], tecnicos=d["tecnicos"], alertas_grupo_a=d["alertas_grupo_a"], estrategias={},
                  cuenta_das="CUENTA_PRUEBA")


CFG = _config()


def _est(strategy_id: str = "s1", *, fin: Optional[str] = "11:30", hora_salida: Optional[str] = None,
         accept: bool = True, maxr: int = -1, al_desactivar_: str = "esperar_fin_dia",
         definition_hash: str = "sha256:v1") -> EstrategiaConfig:
    return EstrategiaConfig(strategy_id=strategy_id, name=f"Estrategia {strategy_id}", origen="portfolio",
                            ejecutar=True, avisar_grupo_a=False, riesgo_usd=D("300"), riesgos_piramide=[],
                            riesgo_piramide_usd=None, ev_pct=D("4"), ev_rangos=[], excluir_ipo=False,
                            al_desactivar=al_desactivar_, hora_fin_sesion=fin, ventana_entradas=[],
                            hora_salida=hora_salida, accept_reentries=accept, max_reentries=maxr,
                            niveles_piramide=[], es_rth=False, definition_hash=definition_hash, definition={})


def _lote(id_: str = "L1", *, strategy_id: str = "s1", ticker: str = "XYZ", direccion: str = "Short",
          llenas: int = 100, estado: EstadoLote = EstadoLote.ABIERTO, tp_pendiente: int = 0,
          reentrada_n: int = 0, nivel_piramide: Optional[int] = None, hora_salida: Optional[str] = None,
          eod: Optional[str] = None) -> Lote:
    return Lote(id=id_, strategy_id=strategy_id, estrategia=f"Estrategia {strategy_id}", ticker=ticker,
                direccion=direccion, pedidas=max(llenas, 1), llenas=llenas, precio_medio=D("10"),
                nivel_stop=D("11"), estado=estado, reentrada_n=reentrada_n, nivel_piramide=nivel_piramide,
                hora_salida=hora_salida, eod=eod, tp_pendiente=tp_pendiente)


def _pos(ticker: str = "XYZ", *, neta_fills: int = -100, neta_das: Optional[int] = None,
         lotes: Optional[list[Lote]] = None, estado: EstadoTicker = EstadoTicker.NORMAL,
         sin_reentrada: bool = False, das_en: Optional[float] = None,
         fill_en: Optional[float] = None) -> PosicionTicker:
    return PosicionTicker(ticker=ticker, lotes={lote.id: lote for lote in (lotes or [])}, neta_fills=neta_fills,
                          neta_das=neta_das, estado=estado, sin_reentrada_hasta_sigue=sin_reentrada,
                          neta_das_en=das_en, ultimo_fill_en=fill_en)


def _cot(bid, ask, last=None, ticker: str = "XYZ") -> Cotizacion:
    return Cotizacion(ticker=ticker, bid=None if bid is None else D(str(bid)), ask=None if ask is None else D(str(ask)),
                      last=None if last is None else D(str(last)), actualizada_en=1000.0)


def _orden(*, token: int = 126800001, lado: Lado = Lado.COMPRA, qty: int = 100, precio: str = "10.00",
           id_das: Optional[int] = 555, estado: EstadoOrden = EstadoOrden.ACCEPTED, lvqty: int = 0, llenas: int = 0,
           proposito: Proposito = Proposito.HORA_ASK, lote_id: Optional[str] = "L1", ticker: str = "XYZ") -> Orden:
    return Orden(token=token, ticker=ticker, lado=lado, tipo=TipoOrden.LIMITE, qty=qty, precio=D(precio), stop=None,
                 ruta="SAGEPRO", proposito=proposito, lote_id=lote_id, nivel=None, origen=Origen.EJECUTOR,
                 id_das=id_das, estado=estado, lvqty=lvqty, llenas=llenas)


def _tokens():
    return itertools.count(126800001).__next__


def _evento(tipo: str, accion: Optional[str] = None, nombre: str = "") -> dict:
    return {"tipo": tipo, "accion_piramide": accion, "nombre": nombre}


def _senal(evento, id_: str) -> Senal:
    return Senal(clase="evento" if evento is not None else "radar", ticker="XYZ", id=id_, evento=evento)


# ── riesgo 24: TODOS los literales del motor real ────────────────────────
_LITERAL = re.compile(r"""(?P<f>[fF]?)(?P<q>["'])(?P<texto>(?:(?!(?P=q)).)*)(?P=q)""")


def _literales_de_portfolio_sim() -> tuple[set[str], set[str]]:
    """(literales planos, prefijos de f-string) de cada línea de código que menciona exit_reason."""
    planos: set[str] = set()
    prefijos: set[str] = set()
    for linea in PORTFOLIO_SIM.read_text(encoding="utf-8").splitlines():
        codigo = linea.split("#", 1)[0] if not linea.lstrip().startswith("#") else ""
        if "exit_reason" not in codigo:
            continue
        for m in _LITERAL.finditer(codigo):
            texto = m.group("texto")
            if texto == "exit_reason":
                continue
            if m.group("f"):
                prefijos.add(re.split(r"[({]", texto, maxsplit=1)[0].strip())
            else:
                planos.add(texto)
    return planos, prefijos


def test_literales_del_fichero_real_existen():
    assert PORTFOLIO_SIM.is_file(), "riesgo 24: el test necesita el portfolio_sim.py real"
    planos, prefijos = _literales_de_portfolio_sim()
    assert len(planos) >= 18
    assert prefijos == {"Lot TP"}, "ajuste (f): la única f-string conocida es «Lot TP (n/m)»"


def test_literales_exit_reason_cubre_todos_los_de_portfolio_sim():
    """Riesgo 24 / corrección 5: cada literal de exit_reason del fichero real está clasificado."""
    planos, prefijos = _literales_de_portfolio_sim()
    faltan = (planos | prefijos) - set(LITERALES_EXIT_REASON)
    assert not faltan, f"exit_reason sin clasificar en salidas.LITERALES_EXIT_REASON: {sorted(faltan)}"


def test_ningun_literal_de_la_tabla_esta_de_sobra():
    """La tabla no tiene claves inventadas: todas salen del fichero real salvo «?» (motor de alertas)."""
    planos, prefijos = _literales_de_portfolio_sim()
    assert set(LITERALES_EXIT_REASON) - {"?"} == planos | prefijos


def test_el_motor_de_alertas_emite_interrogacion_si_falta_el_motivo():
    """bot_alerts_engine l.1142: motivo = str(exit_reason or "?") → "?" está en la tabla y es MOTOR."""
    fuente = MOTOR_ALERTAS.read_text(encoding="utf-8")
    assert re.search(r"""exit_reason"\)\s*or\s*"\?"\s*\)""", fuente)
    assert LITERALES_EXIT_REASON["?"] is ClaseSalida.MOTOR


@pytest.mark.parametrize("literal, clase", [
    ("TP", ClaseSalida.TP), ("Partial TP", ClaseSalida.TP), ("Partial TP (Hour)", ClaseSalida.HORA),
    ("Partial TP (EOD)", ClaseSalida.EOD), ("Partial TP (Time)", ClaseSalida.HORA), ("EOD", ClaseSalida.EOD),
    ("SL", ClaseSalida.STOP), ("Pyramid Lot Stop", ClaseSalida.STOP_LOTE), ("Pyramid Reduce", ClaseSalida.REDUCE),
    ("Escalera", ClaseSalida.MOTOR), ("Signal", ClaseSalida.MOTOR), ("Trailing", ClaseSalida.MOTOR),
    ("Time Limit", ClaseSalida.HORA), ("?", ClaseSalida.MOTOR), ("Halt", ClaseSalida.HALT),
    ("Halt (atrapado)", ClaseSalida.HALT), ("BS", ClaseSalida.BS), ("BS Manual", ClaseSalida.BS),
    ("Daily Limit", ClaseSalida.DAILY_LIMIT), ("Lot TP (1/3)", ClaseSalida.TP), ("Lot TP (3/3)", ClaseSalida.TP),
], ids=lambda v: f"§3.17-{v}" if isinstance(v, str) else v.value)
def test_clasificar_tabla_del_documento(literal, clase):
    assert clasificar(literal) is clase
    assert es_literal_conocido(literal)


class _StrQueLanza:
    def __str__(self) -> str:
        raise RuntimeError("boom")


@pytest.mark.parametrize("motivo, clase", [
    (None, ClaseSalida.MOTOR), ("", ClaseSalida.MOTOR), ("   ", ClaseSalida.MOTOR),
    ("  TP  ", ClaseSalida.TP), ("tp", ClaseSalida.TP), ("daily limit", ClaseSalida.DAILY_LIMIT),
    ("Lot TP(2/2)", ClaseSalida.TP), ("Lot TPX", ClaseSalida.MOTOR), ("Motivo nuevo del motor", ClaseSalida.MOTOR),
    (123, ClaseSalida.MOTOR), (_StrQueLanza(), ClaseSalida.MOTOR),
], ids=["None", "vacio", "blancos", "espacios", "minusculas", "daily_minusculas", "lot_tp_sin_espacio",
        "lot_tpx_no_es_prefijo", "desconocido", "entero", "str_que_lanza"])
def test_clasificar_nunca_lanza_y_desconocido_es_motor(motivo, clase):
    """Riesgo 24: desconocido → MOTOR; nunca lanza."""
    assert clasificar(motivo) is clase


def test_es_literal_conocido_distingue_desconocidos():
    assert not es_literal_conocido(None)
    assert not es_literal_conocido("Motivo nuevo")
    assert not es_literal_conocido(7)  # type: ignore[arg-type]
    assert es_literal_conocido("Lot TP (2/5)")


# ── tratamiento por clase (§3.17, preguntas 3 y 4, I1) ───────────────────
@pytest.mark.parametrize("clase, esperado", [
    (ClaseSalida.TP, TRATAR_TP), (ClaseSalida.HORA, TRATAR_HORA_EVENTO), (ClaseSalida.EOD, TRATAR_ANOTAR),
    (ClaseSalida.STOP, TRATAR_DIVERGENCIA), (ClaseSalida.STOP_LOTE, TRATAR_COMO_TP),
    (ClaseSalida.REDUCE, TRATAR_COMO_TP), (ClaseSalida.MOTOR, TRATAR_COMO_TP), (ClaseSalida.HALT, TRATAR_ANOTAR),
    (ClaseSalida.BS, TRATAR_ANOTAR), (ClaseSalida.DAILY_LIMIT, TRATAR_IGNORAR),
], ids=lambda v: v.value if isinstance(v, ClaseSalida) else v)
def test_tratamiento_por_clase_con_posicion_abierta(clase, esperado):
    lote = _lote()
    assert tratamiento(clase, _pos(lotes=[lote]), lote, []) == esperado


def test_todas_las_clases_tienen_tratamiento():
    lote = _lote()
    for clase in ClaseSalida:
        assert tratamiento(clase, _pos(lotes=[lote]), lote, []) in salidas.TRATAMIENTOS


def test_sl_del_motor_con_posicion_abierta_es_divergencia_sin_orden():
    """Pregunta 4: SL del motor con la posición aún abierta → no perseguir; diario + aviso 2, ninguna orden."""
    lote = _lote()
    pos = _pos(neta_fills=-100, neta_das=-100, lotes=[lote])
    codigo = tratamiento(ClaseSalida.STOP, pos, lote, [])
    assert codigo == TRATAR_DIVERGENCIA
    acciones = avisos_de_tratamiento(codigo, ClaseSalida.STOP, "SL", pos, lote)
    assert not any(isinstance(a, (EnviarOrden, Reemplazar, Cancelar, CancelarTicker)) for a in acciones)
    assert any(isinstance(a, Anotar) and a.tipo == "divergencia_sl" for a in acciones)
    avisos = [a for a in acciones if isinstance(a, Avisar)]
    assert len(avisos) == 1 and avisos[0].nivel is Nivel.AVISO and avisos[0].grupo is Grupo.B


@pytest.mark.parametrize("neta_fills, neta_das, estado, esperado", [
    (0, None, EstadoLote.ABIERTO, TRATAR_ANOTAR),
    (0, 0, EstadoLote.ABIERTO, TRATAR_ANOTAR),
    (0, -100, EstadoLote.ABIERTO, TRATAR_DIVERGENCIA),     # DAS aún la ve abierta
    (-100, None, EstadoLote.CERRADO, TRATAR_ANOTAR),       # el lote ya se cerró por nuestro stop
], ids=["plana", "plana_das", "abierta_solo_das", "lote_cerrado"])
def test_sl_del_motor_segun_la_posicion(neta_fills, neta_das, estado, esperado):
    lote = _lote(estado=estado)
    assert tratamiento(ClaseSalida.STOP, _pos(neta_fills=neta_fills, neta_das=neta_das, lotes=[lote]), lote, []) == esperado


def test_daily_limit_se_ignora_con_aviso_2():
    """I1: sin cortacircuito diario: ignorar + aviso 2 con clave por estrategia."""
    lote = _lote()
    pos = _pos(lotes=[lote])
    codigo = tratamiento(ClaseSalida.DAILY_LIMIT, pos, lote, [])
    assert codigo == TRATAR_IGNORAR
    acciones = avisos_de_tratamiento(codigo, ClaseSalida.DAILY_LIMIT, "Daily Limit", pos, lote)
    avisos = [a for a in acciones if isinstance(a, Avisar)]
    assert [(a.nivel, a.clave) for a in avisos] == [(Nivel.AVISO, "daily_limit:s1")]
    assert not any(isinstance(a, EnviarOrden) for a in acciones)


def test_motor_como_tp_avisa_nivel_1_y_ignorar_por_config():
    """Pregunta 3: Signal/Trailing/Escalera → como TP (provisional) con aviso 1; salida_motor=ignorar → ignorar.

    («Time Limit» ya no es MOTOR: es una salida por tiempo, D2-05.)
    """
    lote = _lote()
    pos = _pos(lotes=[lote])
    codigo = tratamiento(ClaseSalida.MOTOR, pos, lote, [])
    assert codigo == TRATAR_COMO_TP
    acciones = avisos_de_tratamiento(codigo, ClaseSalida.MOTOR, "Trailing", pos, lote)
    assert [a.nivel for a in acciones if isinstance(a, Avisar)] == [Nivel.INFO]
    assert tratamiento(ClaseSalida.MOTOR, pos, lote, [], salida_motor="ignorar") == TRATAR_IGNORAR


def test_motivo_desconocido_se_anota():
    """Riesgo 24: un literal que no está en la tabla se anota como salida_desconocida."""
    lote = _lote()
    pos = _pos(lotes=[lote])
    acciones = avisos_de_tratamiento(TRATAR_COMO_TP, clasificar("Algo nuevo"), "Algo nuevo", pos, lote)
    assert [a.tipo for a in acciones if isinstance(a, Anotar)] == ["salida_motor", "salida_desconocida"]
    conocidas = avisos_de_tratamiento(TRATAR_TP, ClaseSalida.TP, "TP", pos, lote)
    assert [a.tipo for a in conocidas if isinstance(a, Anotar)] == ["salida_motor"]
    assert not any(isinstance(a, Avisar) for a in conocidas)


@pytest.mark.parametrize("lote, vivas", [
    (None, []),
    (_lote(estado=EstadoLote.CERRADO), []),
    (_lote(llenas=100, tp_pendiente=100), []),
    (_lote(), [_orden(proposito=Proposito.HORA_ASK)]),
    (_lote(), [_orden(proposito=Proposito.CIERRE_HUMANO)]),
    (_lote(), [_orden(proposito=Proposito.CIERRE_REINICIO, estado=EstadoOrden.SENDING)]),
], ids=["sin_lote", "lote_cerrado", "todo_con_tp_pendiente", "hora_en_curso", "cierre_humano_en_curso",
        "reinicio_en_curso"])
def test_tp_sin_acciones_libres_o_con_cierre_total_en_curso_solo_se_anota(lote, vivas):
    """Riesgo 6: nunca dos órdenes de compra sobre las mismas acciones."""
    pos = _pos(lotes=[lote] if lote else [])
    assert tratamiento(ClaseSalida.TP, pos, lote, vivas) == TRATAR_ANOTAR
    assert tratamiento(ClaseSalida.MOTOR, pos, lote, vivas) == TRATAR_ANOTAR


def test_orden_de_cierre_ya_terminada_no_bloquea_el_tp():
    lote = _lote()
    vivas = [_orden(proposito=Proposito.HORA_ASK, estado=EstadoOrden.CANCELED),
             _orden(proposito=Proposito.HORA_AGREGAR, lote_id="OTRO")]
    assert tratamiento(ClaseSalida.TP, _pos(lotes=[lote]), lote, vivas) == TRATAR_TP


# ── horas de salida, EOD y temporizadores (R-D-08, R-D-02, R-L-01) ───────
def test_horas_de_salida_en_et():
    salida, eod = horas_de_salida(_est(fin="11:30", hora_salida="10:15"), DIA)
    assert salida == datetime(2026, 9, 25, 10, 15, tzinfo=ET)
    assert eod == datetime(2026, 9, 25, 11, 30, tzinfo=ET)
    assert eod.utcoffset() == datetime(2026, 9, 25, 11, 30, tzinfo=ET).utcoffset()


@pytest.mark.parametrize("fin, hora_salida, esperado_salida, esperado_eod", [
    (None, None, None, (16, 0, 0)),
    ("09:29", None, None, (9, 29, 0)),
    ("11:30", "10:15:30", (10, 15, 30), (11, 30, 0)),
], ids=["R-D-02-sin_fin_16h", "R-D-02-pm", "R-D-08-con_segundos"])
def test_horas_de_salida_casos(fin, hora_salida, esperado_salida, esperado_eod):
    salida, eod = horas_de_salida(_est(fin=fin, hora_salida=hora_salida), DIA)
    assert eod == datetime(2026, 9, 25, *esperado_eod, tzinfo=ET)
    if esperado_salida is None:
        assert salida is None
    else:
        assert salida == datetime(2026, 9, 25, *esperado_salida, tzinfo=ET)


@pytest.mark.parametrize("mala", ["25:00", "11:61", "11", "11h30", "aa:bb"])
def test_horas_de_salida_mal_escritas_lanzan(mala):
    with pytest.raises(ValueError):
        horas_de_salida(_est(fin=mala), DIA)


def test_horas_de_salida_media_sesion_recorta():
    """F10/F12: en media sesión (13:00) el EOD de 16:00 se recorta al cierre."""
    cierre = datetime(2026, 11, 27, 13, 0, tzinfo=ET)
    salida, eod = horas_de_salida(_est(fin="16:00", hora_salida="14:00"), date(2026, 11, 27), cierre_mercado=cierre)
    assert eod == cierre and salida == cierre
    _, eod_pm = horas_de_salida(_est(fin="09:29"), date(2026, 11, 27), cierre_mercado=cierre)
    assert eod_pm == datetime(2026, 11, 27, 9, 29, tzinfo=ET)


def test_ultimo_eod_con_dos_estrategias():
    """R-L-01: el apagado es el ÚLTIMO EOD de las estrategias (más el margen de R-D-02)."""
    assert ultimo_eod([_est("a", fin="09:29"), _est("b", fin="11:30")], DIA) == datetime(2026, 9, 25, 11, 30, tzinfo=ET)
    assert ultimo_eod([_est("b", fin="11:30"), _est("a", fin="09:29")], DIA) == datetime(2026, 9, 25, 11, 30, tzinfo=ET)
    assert ultimo_eod([], DIA) is None


def test_ultimo_eod_hora_mal_escrita_no_adelanta_el_apagado():
    assert ultimo_eod([_est("a", fin="09:29"), _est("b", fin="xx")], DIA) == datetime(2026, 9, 25, 16, 0, tzinfo=ET)


def _por_clave(programas: list[Programar]) -> dict[str, Programar]:
    return {p.clave.split(":", 1)[0]: p for p in programas}


def test_temporizadores_lote_t_menos_60_t_y_t_mas_30():
    """R-D-08 / R-D-02 (F5): hora_agregar t−60, hora_ask t, eod_comprobar t+30; clave y datos con el lote."""
    lote = _lote("L1")
    programas = temporizadores_lote(lote, _est(fin="11:30"), DIA, CFG.salidas, HORA)
    assert [p.clave for p in programas] == ["hora_agregar:L1", "hora_ask:L1", "eod_comprobar:L1"]
    t = (datetime(2026, 9, 25, 11, 30, tzinfo=ET) - HORA).total_seconds()
    assert [p.en_s for p in programas] == [t - 60, t, t + 30]
    for p in programas:
        assert p.datos["lote_id"] == "L1" and p.datos["ticker"] == "XYZ" and p.datos["motivo"] == "eod"
    assert programas[0].datos["proposito"] == Proposito.HORA_AGREGAR.value
    assert programas[1].datos["proposito"] == Proposito.HORA_ASK.value
    assert programas[1].datos["cuando"] == datetime(2026, 9, 25, 11, 30, tzinfo=ET).isoformat()


def test_temporizadores_con_hora_de_salida_anterior_al_eod():
    programas = _por_clave(temporizadores_lote(_lote(), _est(fin="11:30", hora_salida="10:00"), DIA, CFG.salidas, HORA))
    assert programas["hora_ask"].en_s == 15 * 60
    assert programas["hora_agregar"].en_s == 14 * 60
    assert programas["eod_comprobar"].en_s == 15 * 60 + 30
    assert programas["hora_ask"].datos["motivo"] == "hora"


def test_temporizadores_hora_de_salida_posterior_al_eod_manda_el_eod():
    programas = _por_clave(temporizadores_lote(_lote(), _est(fin="10:00", hora_salida="10:30"), DIA, CFG.salidas, HORA))
    assert programas["hora_ask"].en_s == 15 * 60 and programas["hora_ask"].datos["motivo"] == "eod"


def test_temporizadores_usan_las_horas_del_lote_si_las_tiene():
    """R-E-03: el lote conserva las horas de la versión con la que nació."""
    lote = _lote(eod="10:00")
    programas = _por_clave(temporizadores_lote(lote, _est(fin="11:30"), DIA, CFG.salidas, HORA))
    assert programas["hora_ask"].en_s == 15 * 60


def test_temporizadores_con_anticipos_del_cuadro():
    cfg = _config({"eod": {"lanzar_antes_s": 90, "comprobar_despues_s": 45}})
    programas = _por_clave(temporizadores_lote(_lote(), _est(fin="10:00"), DIA, cfg.salidas, HORA))
    assert programas["hora_agregar"].en_s == 15 * 60 - 90
    assert programas["eod_comprobar"].en_s == 15 * 60 + 45


@pytest.mark.parametrize("ahora, esperado", [
    (datetime(2026, 9, 25, 9, 59, 30, tzinfo=ET), {"hora_agregar": 0.0, "hora_ask": 30.0, "eod_comprobar": 60.0}),
    (datetime(2026, 9, 25, 10, 0, 0, tzinfo=ET), {"hora_ask": 0.0, "eod_comprobar": 30.0}),
    (datetime(2026, 9, 25, 10, 5, 0, tzinfo=ET), {"hora_ask": 0.0, "eod_comprobar": 30.0}),
], ids=["R-D-08-dentro_del_minuto", "R-D-08-justo_a_la_hora", "R-D-08-hora_pasada"])
def test_temporizadores_con_la_hora_cerca_o_pasada(ahora, esperado):
    """La hora no se negocia: pasada t no hay agregar; el ask sale ya y la comprobación 30 s después."""
    programas = _por_clave(temporizadores_lote(_lote(), _est(fin="10:00"), DIA, CFG.salidas, ahora))
    assert {k: p.en_s for k, p in programas.items()} == esperado


def test_temporizadores_de_dos_lotes_no_se_pisan():
    claves_a = {p.clave for p in temporizadores_lote(_lote("A"), _est(), DIA, CFG.salidas, HORA)}
    claves_b = {p.clave for p in temporizadores_lote(_lote("B"), _est(), DIA, CFG.salidas, HORA)}
    assert not claves_a & claves_b


def test_temporizadores_exigen_hora_con_zona():
    with pytest.raises(ValueError):
        temporizadores_lote(_lote(), _est(), DIA, CFG.salidas, datetime(2026, 9, 25, 9, 45))


def test_dos_estrategias_con_eod_distinto_cada_lote_a_su_hora():
    """R-D-02 (3): a las 09:29 solo se comprueba el lote de A; el de B no es alarma hasta su EOD."""
    ahora = datetime(2026, 9, 25, 9, 0, tzinfo=ET)
    a = _por_clave(temporizadores_lote(_lote("LA", strategy_id="a"), _est("a", fin="09:29"), DIA, CFG.salidas, ahora))
    b = _por_clave(temporizadores_lote(_lote("LB", strategy_id="b"), _est("b", fin="11:30"), DIA, CFG.salidas, ahora))
    assert a["eod_comprobar"].en_s == 29 * 60 + 30
    assert b["eod_comprobar"].en_s == 150 * 60 + 30


# ── órdenes: agregar, al ask, persecución (R-D-08, D10, corrección 11) ───
def test_orden_hora_agregar_corto_compra_al_punto_medio_postonly():
    orden = orden_hora_agregar(_lote(), 100, _cot("10.00", "10.05"), CFG, 126800001, HORA)
    assert (orden.lado, orden.tipo, orden.post_only, orden.tif) == (Lado.COMPRA, TipoOrden.LIMITE, True, "DAY+")
    assert orden.precio == D("10.02")                  # floor(10,025): por debajo del ask, agregando
    assert orden.ruta == "SAGEREB" and orden.proposito is Proposito.HORA_AGREGAR and orden.lote_id == "L1"
    assert orden.qty == 100 and orden.token == 126800001


@pytest.mark.parametrize("bid, ask, lado, precio, ruta", [
    ("0.5000", "0.5003", Lado.COMPRA, "0.5001", "MIAX"),
    ("10.00", "10.01", Lado.COMPRA, "10.00", "SAGEREB"),
    ("10.00", "10.00", Lado.COMPRA, "9.99", "SAGEREB"),       # libro bloqueado: un tick por debajo del ask
    ("1.00", "1.00", Lado.COMPRA, "0.9999", "MIAX"),          # bloqueado en 1 $: el tick de abajo es 0,0001
], ids=["R-D-08-penny", "R-D-08-spread_1_tick", "R-D-08-bloqueado", "R-D-08-bloqueado_en_1"])
def test_orden_hora_agregar_precios_y_rutas(bid, ask, lado, precio, ruta):
    orden = orden_hora_agregar(_lote(), 100, _cot(bid, ask), CFG, 1, HORA)
    assert (orden.lado, orden.precio, orden.ruta) == (lado, D(precio), ruta)
    assert orden.precio < D(ask) or D(bid) == D(ask) == orden.precio  # nunca cruza


def test_orden_hora_agregar_largo_vende_al_punto_medio_arriba():
    orden = orden_hora_agregar(_lote(direccion="Long"), 50, _cot("10.00", "10.05"), CFG, _tokens(), HORA)
    assert (orden.lado, orden.precio, orden.post_only) == (Lado.VENTA, D("10.03"), True)
    bloqueado = orden_hora_agregar(_lote(direccion="Long"), 50, _cot("10.00", "10.00"), CFG, 1, HORA)
    assert bloqueado.precio == D("10.01")


@pytest.mark.parametrize("cot", [None, _cot(None, "10"), _cot("10", None), _cot("10.05", "10.00"), _cot("0", "1")],
                         ids=["sin_cot", "sin_bid", "sin_ask", "cruzado", "bid_cero"])
def test_orden_hora_agregar_sin_libro_valido_lanza(cot):
    with pytest.raises(ValueError):
        orden_hora_agregar(_lote(), 100, cot, CFG, 1, HORA)


def test_orden_hora_agregar_qty_no_entera_lanza():
    with pytest.raises(ValueError):
        orden_hora_agregar(_lote(), 100.0, _cot("10", "10.05"), CFG, 1, HORA)  # type: ignore[arg-type]


def test_orden_al_ask_sin_tope_compra_al_ask_aunque_se_dispare():
    """R-D-08: a la hora, al ask SIN tope: aunque el ask esté un 20 % sobre el último."""
    orden = orden_al_ask(_lote(), 100, _cot("11.90", "12.00", last="10.00"), CFG, 7, HORA, None, Proposito.HORA_ASK)
    assert (orden.lado, orden.precio, orden.post_only, orden.ruta) == (Lado.COMPRA, D("12.00"), False, "SAGEPRO")
    assert orden.proposito is Proposito.HORA_ASK and orden.lote_id == "L1"


@pytest.mark.parametrize("ask, last, esperado", [
    ("10.20", "10.00", "10.20"),      # dentro del 3 %: al ask
    ("10.30", "10.00", "10.30"),      # justo en el techo
    ("10.50", "10.00", "10.30"),      # fuera: min(ask, last·1,03)
    ("10.31", "10.01", "10.31"),      # techo 10,3103 → redondeado arriba 10,32 ≥ ask
], ids=["R-D-03-dentro", "R-D-03-en_el_techo", "R-D-03-fuera_min", "R-D-03-redondeo_arriba"])
def test_orden_al_ask_con_techo(ask, last, esperado):
    orden = orden_al_ask(_lote(), 10, _cot("9.90", ask, last=last), CFG, 7, HORA, D("3"), Proposito.TP_CRUCE)
    assert orden.precio == D(esperado) and isinstance(orden.precio, Decimal)


def test_orden_al_ask_lote_largo_vende_al_bid_con_suelo():
    lote = _lote(direccion="Long")
    orden = orden_al_ask(lote, 10, _cot("9.90", "9.95", last="10.00"), CFG, 7, HORA, D("3"), Proposito.TP_CRUCE)
    assert (orden.lado, orden.precio) == (Lado.VENTA, D("9.90"))
    bajo = orden_al_ask(lote, 10, _cot("9.50", "9.55", last="10.00"), CFG, 7, HORA, D("3"), Proposito.TP_CRUCE)
    assert bajo.precio == D("9.70")


@pytest.mark.parametrize("hora, ruta", [(HORA_PM, "MIAX"), (HORA, "EDGA")], ids=["penny_antes_0700", "penny_desde_0700"])
def test_orden_al_ask_ruta_de_cruce_en_pennies(hora, ruta):
    orden = orden_al_ask(_lote(), 100, _cot("0.5000", "0.5010"), CFG, 7, hora, None, Proposito.HORA_ASK)
    assert orden.ruta == ruta and orden.precio == D("0.5010")


def test_orden_al_ask_errores():
    with pytest.raises(ValueError):
        orden_al_ask(_lote(), 100, _cot("10", None), CFG, 7, HORA, None, Proposito.HORA_ASK)
    with pytest.raises(ValueError):
        orden_al_ask(_lote(), 100, _cot("10", "10.1"), CFG, 7, HORA, D("3"), Proposito.TP_CRUCE)   # sin último
    with pytest.raises(ValueError):
        orden_al_ask(_lote(), 100, _cot("10", "10.1", last="10"), CFG, 7, HORA, D("-1"), Proposito.TP_CRUCE)


def test_perseguir_ask_reemplaza_precio_con_la_qty_viva():
    """Corrección 11: REPLACE de precio al ask nuevo, con la cantidad que QUEDA (lvqty), nunca lo pedido."""
    orden = _orden(qty=100, lvqty=60, llenas=40, precio="10.00")
    r = perseguir_ask(orden, _cot("10.05", "10.10"), persecuciones=0)
    assert isinstance(r, Reemplazar)
    assert (r.id_das, r.token, r.qty, r.precio, r.stop) == (555, 126800001, 60, D("10.10"), None)


def test_perseguir_ask_sin_lvqty_usa_qty_menos_llenas():
    r = perseguir_ask(_orden(qty=100, lvqty=0, llenas=30), _cot("10.05", "10.10"), 1)
    assert r is not None and r.qty == 70


def test_perseguir_ask_como_mucho_tres_y_solo_por_replace():
    """Corrección 11 / riesgo 11: 3 REPLACE como mucho; nunca Cancelar + nueva."""
    orden = _orden(precio="10.00")
    hechas = []
    persecuciones = 0
    for paso in range(6):
        r = perseguir_ask(orden, _cot("10", str(D("10.01") + D("0.01") * paso)), persecuciones)
        if r is None:
            break
        assert isinstance(r, Reemplazar) and not isinstance(r, Cancelar)
        hechas.append(r)
        orden.precio = r.precio
        persecuciones += 1
    assert len(hechas) == 3
    assert perseguir_ask(orden, _cot("10", "11"), 3) is None
    assert perseguir_ask(orden, _cot("10", "11"), 1, max_persecuciones=1) is None


@pytest.mark.parametrize("orden, cot", [
    (_orden(id_das=None), _cot("10", "10.10")),
    (_orden(estado=EstadoOrden.EXECUTED), _cot("10", "10.10")),
    (_orden(estado=EstadoOrden.CANCELED), _cot("10", "10.10")),
    (_orden(qty=100, llenas=100), _cot("10", "10.10")),
    (_orden(precio="10.10"), _cot("10", "10.10")),
    (_orden(precio="10.20"), _cot("10", "10.10")),
    (_orden(), _cot("10", None)),
], ids=["sin_id_das", "ejecutada", "cancelada", "sin_restante", "ya_en_el_ask", "por_encima_del_ask", "sin_ask"])
def test_perseguir_ask_no_hace_nada(orden, cot):
    assert perseguir_ask(orden, cot, 0) is None


def test_perseguir_venta_baja_al_bid():
    r = perseguir_ask(_orden(lado=Lado.VENTA, precio="10.00"), _cot("9.95", "10.00"), 0)
    assert r is not None and r.precio == D("9.95")
    assert perseguir_ask(_orden(lado=Lado.VENTA, precio="9.95"), _cot("9.95", "10.00"), 0) is None


# ── TP parcial (R-D-03 v2, F4) ───────────────────────────────────────────
def test_tp_parcial_agrega_en_el_punto_medio_y_programa_el_cruce():
    lote = _lote(llenas=500, tp_pendiente=0)
    orden, prog = tp_parcial(lote, 300, _cot("10.00", "10.04"), CFG, 126800009, HORA)
    assert (orden.lado, orden.precio, orden.post_only, orden.qty) == (Lado.COMPRA, D("10.02"), True, 300)
    assert orden.proposito is Proposito.TP_AGREGAR and orden.ruta == "SAGEREB"
    assert prog.clave == "tp_cruce:L1:126800009" and prog.en_s == 60.0      # D2-07: por ORDEN
    assert prog.datos == {"lote_id": "L1", "ticker": "XYZ", "token": 126800009, "qty": 300}


def test_tp_parcial_nunca_supera_lo_libre_del_lote():
    """Área E: la suma de órdenes nunca supera la posición: tope llenas − tp_pendiente."""
    orden, _ = tp_parcial(_lote(llenas=500, tp_pendiente=300), 400, _cot("10", "10.04"), CFG, 1, HORA)
    assert orden.qty == 200


@pytest.mark.parametrize("lote, qty", [(_lote(llenas=100, tp_pendiente=100), 50), (_lote(), 0), (_lote(), -5)],
                         ids=["todo_pendiente", "cero", "negativa"])
def test_tp_parcial_sin_nada_que_cerrar_lanza(lote, qty):
    with pytest.raises(ValueError):
        tp_parcial(lote, qty, _cot("10", "10.04"), CFG, 1, HORA)


def test_tp_parcial_qty_no_entera_lanza():
    with pytest.raises(ValueError):
        tp_parcial(_lote(), True, _cot("10", "10.04"), CFG, 1, HORA)  # type: ignore[arg-type]


@pytest.mark.parametrize("ask, last, cruza", [
    ("10.20", "10.00", True), ("10.30", "10.00", True), ("10.31", "10.00", False), ("12.00", "10.00", False),
], ids=["R-D-03-dentro", "R-D-03-en_el_limite", "R-D-03-un_tick_fuera", "R-D-03-fogonazo"])
def test_tp_al_vencer_dentro_y_fuera_del_3(ask, last, cruza):
    orden, aviso = tp_al_vencer(_lote(), 200, _cot("10.00", ask, last=last), CFG, 11, HORA)
    if cruza:
        assert aviso is None and orden is not None
        assert (orden.lado, orden.precio, orden.qty, orden.proposito) == (Lado.COMPRA, D(ask), 200, Proposito.TP_CRUCE)
        assert orden.ruta == "SAGEPRO" and not orden.post_only
    else:
        assert orden is None
        assert aviso is not None and aviso.nivel is Nivel.AVISO and "limbo" in aviso.texto


def test_tp_al_vencer_usa_el_ultimo_de_ese_momento():
    """R-D-03 v2: el techo es sobre el último DEL MOMENTO del cruce, no sobre el de hace un minuto."""
    orden, _ = tp_al_vencer(_lote(), 100, _cot("10.60", "10.70", last="10.50"), CFG, 1, HORA)
    assert orden is not None and orden.precio == D("10.70")
    orden2, aviso2 = tp_al_vencer(_lote(), 100, _cot("10.60", "10.70", last="10.00"), CFG, 1, HORA)
    assert orden2 is None and aviso2 is not None


def test_tp_al_vencer_techo_del_cuadro():
    cfg = _config({"tp_parcial": {"techo_ask_pct": 1.0}})
    orden, aviso = tp_al_vencer(_lote(), 100, _cot("10.00", "10.20", last="10.00"), cfg, 1, HORA)
    assert orden is None and aviso is not None


@pytest.mark.parametrize("cot", [_cot("10", "10.1"), _cot("10", None, last="10"), None],
                         ids=["sin_ultimo", "sin_ask", "sin_cot"])
def test_tp_al_vencer_sin_datos_es_limbo(cot):
    orden, aviso = tp_al_vencer(_lote(), 100, cot, CFG, 1, HORA)
    assert orden is None and aviso is not None and "limbo" in aviso.texto


def test_tp_al_vencer_sin_resto_no_hace_nada():
    assert tp_al_vencer(_lote(), 0, _cot("10", "10.1", last="10"), CFG, 1, HORA) == (None, None)


def test_tp_al_vencer_lote_largo():
    orden, _ = tp_al_vencer(_lote(direccion="Long"), 50, _cot("9.80", "9.85", last="10.00"), CFG, 1, HORA)
    assert orden is not None and (orden.lado, orden.precio) == (Lado.VENTA, D("9.80"))
    nada, aviso = tp_al_vencer(_lote(direccion="Long"), 50, _cot("9.60", "9.65", last="10.00"), CFG, 1, HORA)
    assert nada is None and aviso is not None


# ── prioridad (R-D-07) ───────────────────────────────────────────────────
def test_prioridad_salidas_reduce_add_entradas_y_estable():
    senales = [
        _senal(_evento("entrada", nombre="e1"), "e1"),
        _senal(None, "radar1"),
        _senal(_evento("piramide", "add", "add1"), "add1"),
        _senal(_evento("salida", nombre="tp1"), "tp1"),
        _senal(_evento("piramide", "lot_tp", "lt1"), "lt1"),
        _senal(_evento("entrada", nombre="e2"), "e2"),
        _senal(_evento("piramide", None, "add2"), "add2"),
        _senal(_evento("piramide", "reduce", "red1"), "red1"),
        _senal(_evento("salida", nombre="tp2"), "tp2"),
        _senal(_evento("piramide", "lot_stop", "ls1"), "ls1"),
        _senal(_evento("raro", nombre="x"), "x"),
    ]
    original = list(senales)
    ordenadas = prioridad(senales)
    assert [s.id for s in ordenadas] == ["tp1", "tp2", "lt1", "red1", "ls1", "add1", "add2", "e1", "e2", "radar1", "x"]
    assert senales == original


def test_prioridad_con_eventos_objeto():
    class Ev:
        def __init__(self, tipo, accion=None):
            self.tipo, self.accion_piramide = tipo, accion
    ordenadas = prioridad([_senal(Ev("entrada"), "e"), _senal(Ev("salida"), "s")])
    assert [s.id for s in ordenadas] == ["s", "e"]
    assert prioridad([]) == []


# ── cerrar todo (R-D-06) ─────────────────────────────────────────────────
def _cot_de(tabla: dict[str, Optional[Cotizacion]]):
    return lambda t: tabla.get(t)


def test_cerrar_todo_incluye_manuales_y_cancela_antes():
    posiciones = {
        "BOT": _pos("BOT", neta_fills=-100, neta_das=-100),
        "MANL": _pos("MANL", neta_fills=0, neta_das=50),
        "MANC": _pos("MANC", neta_fills=0, neta_das=-30),
        "PLANA": _pos("PLANA", neta_fills=0, neta_das=None),
    }
    cots = {"BOT": _cot("10.00", "10.10", ticker="BOT"), "MANL": _cot("5.00", "5.02", ticker="MANL"),
            "MANC": _cot("0.5000", "0.5010", ticker="MANC")}
    acciones = cerrar_todo(posiciones, _cot_de(cots), CFG, _tokens(), HORA)
    ordenes = {a.orden.ticker: a.orden for a in acciones if isinstance(a, EnviarOrden)}
    assert set(ordenes) == {"BOT", "MANL", "MANC"}
    assert (ordenes["BOT"].lado, ordenes["BOT"].qty, ordenes["BOT"].precio) == (Lado.COMPRA, 100, D("10.61"))
    assert (ordenes["MANL"].lado, ordenes["MANL"].qty, ordenes["MANL"].precio) == (Lado.VENTA, 50, D("4.75"))
    assert (ordenes["MANC"].lado, ordenes["MANC"].qty, ordenes["MANC"].precio) == (Lado.COMPRA, 30, D("0.5261"))
    assert ordenes["MANC"].ruta == "EDGA" and ordenes["BOT"].ruta == "SAGEPRO"
    for o in ordenes.values():
        assert o.proposito is Proposito.CIERRE_HUMANO and not o.post_only and o.tipo is TipoOrden.LIMITE
    for ticker in ordenes:
        indices = [i for i, a in enumerate(acciones) if getattr(a, "ticker", None) == ticker
                   or (isinstance(a, EnviarOrden) and a.orden.ticker == ticker)]
        assert isinstance(acciones[indices[0]], CancelarTicker), f"{ticker}: CancelarTicker ANTES de la orden"
    prog = [a for a in acciones if isinstance(a, Programar)]
    # D2-01: UN temporizador por ticker («cerrar_todo:<ticker>»), nunca una clave global
    assert [p.clave for p in prog] == [f"{CLAVE_CERRAR_TODO}:BOT", f"{CLAVE_CERRAR_TODO}:MANC",
                                       f"{CLAVE_CERRAR_TODO}:MANL"]
    assert all(p.datos["intento"] == 1 and p.datos["tickers"] == [p.datos["ticker"]] for p in prog)
    assert isinstance(acciones[0], Anotar) and acciones[0].tipo == "cerrar_todo"


def test_cerrar_todo_neta_das_manda_y_discrepancia_pide_posiciones():
    """M7 + D2-02: con fills −100 y DAS −150 se cierra el MÍNIMO (100), nunca lo de DAS a ciegas; se pide GET POSITIONS.

    Antes este test esperaba 150 (consagraba el fallo: con %POS atrasado el reintento compraba de más). El resto lo
    cierra el reintento con la neta que devuelva GET POSITIONS. R3-SAL-1: el mínimo solo con la cifra de DAS
    CONFIRMADA (%POS posterior a nuestro último fill); atrasada no se compra nada.
    """
    cots = _cot_de({"X": _cot("10", "10.1", ticker="X")})
    confirmada = _pos("X", neta_fills=-100, neta_das=-150, das_en=DESPUES, fill_en=FILL)
    acciones = cerrar_todo({"X": confirmada}, cots, CFG, _tokens(), HORA)
    assert [a.orden.qty for a in acciones if isinstance(a, EnviarOrden)] == [100]
    assert any(isinstance(a, Consultar) and a.comando == "GET POSITIONS" for a in acciones)
    assert any(isinstance(a, Anotar) and a.tipo == "discrepancia" for a in acciones)
    atrasada = _pos("X", neta_fills=-100, neta_das=-150, das_en=ANTES, fill_en=FILL)
    acciones = cerrar_todo({"X": atrasada}, cots, CFG, _tokens(), HORA)
    assert not any(isinstance(a, EnviarOrden) for a in acciones)
    assert any(isinstance(a, Consultar) and a.comando == "GET POSITIONS" for a in acciones)


def test_cerrar_todo_das_plana_con_fills_cortos_no_compra_pero_reintenta():
    acciones = cerrar_todo({"X": _pos("X", neta_fills=-100, neta_das=0)}, _cot_de({"X": _cot("10", "10.1", ticker="X")}),
                           CFG, _tokens(), HORA)
    assert not any(isinstance(a, EnviarOrden) for a in acciones)
    assert any(isinstance(a, Consultar) for a in acciones)
    assert [a.datos["tickers"] for a in acciones if isinstance(a, Programar)] == [["X"]]


def test_cerrar_todo_sin_cotizacion_avisa_nivel_3():
    acciones = cerrar_todo({"X": _pos("X", neta_fills=-100)}, _cot_de({}), CFG, _tokens(), HORA)
    assert not any(isinstance(a, EnviarOrden) for a in acciones)
    avisos = [a for a in acciones if isinstance(a, Avisar)]
    assert len(avisos) == 1 and avisos[0].nivel is Nivel.MAXIMO and "MANO" in avisos[0].texto


@pytest.mark.parametrize("intento, envia", [(0, True), (1, True), (2, True), (3, False)],
                         ids=["R-D-06-primero", "R-D-06-reintento_1", "R-D-06-reintento_2", "R-D-06-agotado"])
def test_cerrar_todo_dos_reintentos_y_luego_aviso(intento, envia):
    posiciones = {"X": _pos("X", neta_fills=-100)}
    acciones = cerrar_todo(posiciones, _cot_de({"X": _cot("10", "10.1", last="10", ticker="X")}), CFG, _tokens(),
                           HORA, intento=intento)
    ordenes = [a for a in acciones if isinstance(a, EnviarOrden)]
    programas = [a for a in acciones if isinstance(a, Programar)]
    if envia:
        assert len(ordenes) == 1 and programas[0].datos["intento"] == intento + 1
    else:
        assert not ordenes and not programas
        avisos = [a for a in acciones if isinstance(a, Avisar)]
        assert len(avisos) == 1 and avisos[0].nivel is Nivel.MAXIMO and "X neta -100" in avisos[0].texto


def test_cerrar_todo_filtra_tickers_y_techo_del_cuadro():
    cfg = _config({"cerrar_todo": {"techo_pct": 10.0}})
    posiciones = {"A": _pos("A", neta_fills=-10), "B": _pos("B", neta_fills=-20)}
    acciones = cerrar_todo(posiciones, _cot_de({"A": _cot("10", "10", ticker="A"), "B": _cot("10", "10", ticker="B")}),
                           cfg, _tokens(), HORA, tickers=["B"])
    ordenes = [a.orden for a in acciones if isinstance(a, EnviarOrden)]
    assert [(o.ticker, o.precio) for o in ordenes] == [("B", D("11.00"))]
    assert not any(isinstance(a, CancelarTicker) and a.ticker == "A" for a in acciones)


def test_cerrar_todo_sin_posiciones_solo_anota():
    acciones = cerrar_todo({"X": _pos("X", neta_fills=0)}, _cot_de({}), CFG, _tokens(), HORA)
    assert len(acciones) == 1 and isinstance(acciones[0], Anotar)


def test_orden_cierre_posicion_errores():
    with pytest.raises(ValueError):
        orden_cierre_posicion("X", 0, _cot("10", "10.1"), CFG, 1, HORA)
    with pytest.raises(ValueError):
        orden_cierre_posicion("X", -10, _cot("10", None), CFG, 1, HORA)
    with pytest.raises(ValueError):
        orden_cierre_posicion("X", 10, _cot(None, "10"), CFG, 1, HORA)


# ── EOD (R-D-02) ─────────────────────────────────────────────────────────
def test_comprobar_eod_con_acciones_vivas_es_control_humano():
    lote = _lote(llenas=40)
    aviso = comprobar_eod(lote, _pos(neta_fills=-40, lotes=[lote]))
    assert aviso is not None and aviso.nivel is Nivel.MAXIMO and aviso.grupo is Grupo.B
    assert "EOD sin cerrar: control humano" in aviso.texto and aviso.clave == "eod:L1"


@pytest.mark.parametrize("lote, neta_fills, neta_das", [
    (_lote(estado=EstadoLote.CERRADO), -100, None),
    (_lote(estado=EstadoLote.CANCELADO, llenas=0), 0, None),
    (_lote(llenas=0), -100, None),
    (_lote(), 0, None),
    (_lote(), 0, 0),
], ids=["cerrado", "cancelado", "sin_llenas", "plano_fills", "plano_fills_y_das"])
def test_comprobar_eod_sin_aviso(lote, neta_fills, neta_das):
    assert comprobar_eod(lote, _pos(neta_fills=neta_fills, neta_das=neta_das, lotes=[lote])) is None


def test_comprobar_eod_plana_en_fills_pero_das_abierta_avisa():
    lote = _lote()
    assert comprobar_eod(lote, _pos(neta_fills=0, neta_das=-100, lotes=[lote])) is not None


# ── reentradas (R-D-04, R-F-03, R-G-03) ─────────────────────────────────
def _cerrados(n: int, strategy_id: str = "s1") -> list[Lote]:
    return [_lote(f"C{i}", strategy_id=strategy_id, estado=EstadoLote.CERRADO, reentrada_n=i) for i in range(n)]


@pytest.mark.parametrize("maxr, accept, previas, permitida, motivo", [
    (-1, True, 0, True, MOTIVO_REENTRADA_PRIMERA),
    (-1, True, 1, True, None),
    (-1, True, 5, True, None),
    (-1, False, 0, True, MOTIVO_REENTRADA_PRIMERA),
    (-1, False, 1, False, MOTIVO_REENTRADA_NO_ACEPTA),
    (0, True, 0, True, MOTIVO_REENTRADA_PRIMERA),
    (0, True, 1, False, MOTIVO_REENTRADA_TOPE),
    (0, False, 1, False, MOTIVO_REENTRADA_TOPE),
    (2, True, 1, True, None),
    (2, True, 2, True, None),
    (2, True, 3, False, MOTIVO_REENTRADA_TOPE),
    (2, False, 2, True, None),          # paridad con el backtester: con N ≥ 0 no mira accept_reentries
    (2, False, 3, False, MOTIVO_REENTRADA_TOPE),
    (-2, True, 1, False, MOTIVO_REENTRADA_INVALIDO),
], ids=["R-D-04-m1_true_primera", "R-D-04-m1_true_1", "R-D-04-m1_true_5", "R-D-04-m1_false_primera",
        "R-D-04-m1_false_1", "R-D-04-0_true_primera", "R-D-04-0_true_1", "R-D-04-0_false_1", "R-D-04-N2_true_1",
        "R-D-04-N2_true_2", "R-D-04-N2_true_3", "R-D-04-N2_false_2", "R-D-04-N2_false_3", "R-D-04-m2_imposible"])
def test_puede_reentrar_tabla(maxr, accept, previas, permitida, motivo):
    e = _est(accept=accept, maxr=maxr)
    lotes = _cerrados(previas)
    ok, porque = puede_reentrar(e, lotes[-1] if lotes else None, _pos(neta_fills=0, lotes=lotes))
    assert ok is permitida
    if motivo is not None:
        assert porque == motivo


def _backtester_can_enter(max_reentries: int, accept: bool, total_trades: int) -> bool:
    """Copia literal del if/elif de portfolio_sim.py l.2313-2318 (R-D-04: paridad)."""
    can_enter = True
    if max_reentries >= 0:
        if total_trades > max_reentries:
            can_enter = False
    elif not accept and total_trades > 0:
        can_enter = False
    return can_enter


@pytest.mark.parametrize("maxr", [-1, 0, 1, 2, 3])
@pytest.mark.parametrize("accept", [True, False])
@pytest.mark.parametrize("previas", [0, 1, 2, 3, 4])
def test_puede_reentrar_paridad_con_el_backtester(maxr, accept, previas):
    lotes = _cerrados(previas)
    ok, _ = puede_reentrar(_est(accept=accept, maxr=maxr), None, _pos(neta_fills=0, lotes=lotes))
    assert ok is _backtester_can_enter(maxr, accept, previas)


def test_el_if_de_paridad_es_el_del_fichero_real():
    """El if/elif copiado en este test sigue siendo el de portfolio_sim.py (si cambia, revisar R-D-04)."""
    fuente = PORTFOLIO_SIM.read_text(encoding="utf-8")
    assert re.search(r"if max_reentries >= 0:\s*\n\s*if total_trades > max_reentries:\s*\n\s*can_enter = False\s*\n"
                     r"\s*elif not accumulate and total_trades > 0:\s*\n\s*can_enter = False", fuente)


def test_lote_cancelado_sin_fills_no_cuenta_como_entrada():
    cancelado = _lote("X0", estado=EstadoLote.CANCELADO, llenas=0)
    ok, motivo = puede_reentrar(_est(maxr=0), cancelado, _pos(neta_fills=0, lotes=[cancelado]))
    assert ok and motivo == MOTIVO_REENTRADA_PRIMERA


def test_reentrada_n_cuenta_aunque_falten_lotes_en_la_posicion():
    """Tras un reinicio con el diario parcial: reentrada_n del lote anterior dice cuántas hubo."""
    anterior = _lote("C2", estado=EstadoLote.CERRADO, reentrada_n=2)
    ok, motivo = puede_reentrar(_est(maxr=2), anterior, _pos(neta_fills=0))
    assert not ok and motivo == MOTIVO_REENTRADA_TOPE


@pytest.mark.parametrize("pos, motivo", [
    (_pos(neta_fills=0, sin_reentrada=True), MOTIVO_REENTRADA_VETO),
    (_pos(neta_fills=-10, estado=EstadoTicker.BS), MOTIVO_REENTRADA_BS),
    (_pos(neta_fills=-100, lotes=[_lote("V")]), MOTIVO_REENTRADA_LOTE_VIVO),
    (_pos(neta_fills=0, lotes=[_lote("A", estado=EstadoLote.ABRIENDO, llenas=0)]), MOTIVO_REENTRADA_LOTE_VIVO),
], ids=["R-G-03-R-F-03-veto", "R-G-03-bs", "R-D-04-lote_vivo", "R-D-04-intento_vivo"])
def test_puede_reentrar_vetos(pos, motivo):
    assert puede_reentrar(_est(maxr=-1, accept=True), None, pos) == (False, motivo)


def test_lotes_de_otra_estrategia_y_piramides_no_cuentan():
    otros = [_lote("O1", strategy_id="otra", estado=EstadoLote.CERRADO), _lote("O2", strategy_id="otra")]
    piramide = _lote("P1", estado=EstadoLote.CERRADO, nivel_piramide=1)
    ok, motivo = puede_reentrar(_est(maxr=0), None, _pos(lotes=otros + [piramide]))
    assert ok and motivo == MOTIVO_REENTRADA_PRIMERA


# ── estrategia desactivada con lote vivo (R-E-03, F14) ───────────────────
def test_al_desactivar_esperar_fin_dia_no_hace_nada():
    lotes = [_lote()]
    assert al_desactivar(_est(), _est(definition_hash="sha256:v2"), lotes, _cot_de({"XYZ": _cot("10", "10.1")}),
                         CFG, _tokens(), HORA) == []
    assert al_desactivar(_est(), _est(al_desactivar_="algo_raro"), lotes, _cot_de({}), CFG, _tokens(), HORA) == []


def test_al_desactivar_cerrar_y_reiniciar_como_r_d_08():
    vieja = _est()
    nueva = _est(al_desactivar_="cerrar_y_reiniciar", definition_hash="sha256:v2")
    lotes = [_lote("L1", llenas=100), _lote("L2", ticker="ABC", llenas=50, tp_pendiente=20),
             _lote("L3", strategy_id="otra"), _lote("L4", estado=EstadoLote.CERRADO)]
    cots = {"XYZ": _cot("10.00", "10.04"), "ABC": _cot("2.00", "2.02", ticker="ABC")}
    acciones = al_desactivar(vieja, nueva, lotes, _cot_de(cots), CFG, _tokens(), HORA)
    ordenes = [a.orden for a in acciones if isinstance(a, EnviarOrden)]
    assert [(o.ticker, o.lado, o.qty, o.precio, o.post_only, o.proposito) for o in ordenes] == [
        ("XYZ", Lado.COMPRA, 100, D("10.02"), True, Proposito.CIERRE_REINICIO),
        ("ABC", Lado.COMPRA, 30, D("2.01"), True, Proposito.CIERRE_REINICIO),
    ]
    programas = {p.clave: p for p in acciones if isinstance(p, Programar)}
    assert programas["hora_ask:L1"].en_s == 60.0 and programas["eod_comprobar:L1"].en_s == 90.0
    assert programas["hora_ask:L2"].datos["proposito"] == Proposito.CIERRE_REINICIO.value
    assert set(programas) == {"hora_ask:L1", "eod_comprobar:L1", "hora_ask:L2", "eod_comprobar:L2"}
    assert isinstance(acciones[-2], Anotar) and acciones[-2].tipo == "cierre_reinicio"
    assert acciones[-2].datos["lotes"] == ["L1", "L2"]
    assert isinstance(acciones[-1], Avisar) and acciones[-1].nivel is Nivel.INFO


def test_al_desactivar_estrategia_retirada_usa_la_eleccion_de_la_vieja():
    vieja = _est(al_desactivar_="cerrar_y_reiniciar")
    acciones = al_desactivar(vieja, None, [_lote()], _cot_de({"XYZ": _cot("10", "10.04")}), CFG, _tokens(), HORA)
    assert any(isinstance(a, EnviarOrden) for a in acciones)


def test_al_desactivar_sin_cotizacion_va_directo_al_ask():
    nueva = _est(al_desactivar_="cerrar_y_reiniciar")
    acciones = al_desactivar(_est(), nueva, [_lote()], _cot_de({}), CFG, _tokens(), HORA)
    assert not any(isinstance(a, EnviarOrden) for a in acciones)
    programas = {p.clave: p.en_s for p in acciones if isinstance(p, Programar)}
    assert programas == {"hora_ask:L1": 0.0, "eod_comprobar:L1": 30.0}


def test_al_desactivar_sin_lotes_con_acciones_no_avisa():
    nueva = _est(al_desactivar_="cerrar_y_reiniciar")
    assert al_desactivar(_est(), nueva, [_lote(llenas=0)], _cot_de({}), CFG, _tokens(), HORA) == []


# ── pureza y tipos (convenciones §3) ─────────────────────────────────────
def test_ninguna_funcion_muta_sus_entradas():
    lote = _lote(llenas=300, tp_pendiente=100)
    pos = _pos(neta_fills=-300, neta_das=-300, lotes=[lote])
    vivas = [_orden()]
    antes = (copy.deepcopy(lote), copy.deepcopy(pos), copy.deepcopy(vivas))
    tratamiento(ClaseSalida.TP, pos, lote, vivas)
    tp_parcial(lote, 50, _cot("10", "10.04"), CFG, 1, HORA)
    perseguir_ask(vivas[0], _cot("10", "10.5"), 0)
    cerrar_todo({"XYZ": pos}, _cot_de({"XYZ": _cot("10", "10.04")}), CFG, _tokens(), HORA)
    comprobar_eod(lote, pos)
    puede_reentrar(_est(), lote, pos)
    al_desactivar(_est(), _est(al_desactivar_="cerrar_y_reiniciar"), [lote], _cot_de({"XYZ": _cot("10", "10.04")}),
                  CFG, _tokens(), HORA)
    assert (lote, pos, vivas) == antes


def test_ordenes_con_precios_decimal_y_acciones_int():
    ordenes: list[OrdenNueva] = [
        orden_hora_agregar(_lote(), 100, _cot("3.44", "3.46"), CFG, 1, HORA),
        orden_al_ask(_lote(), 100, _cot("3.44", "3.46", last="3.45"), CFG, 1, HORA, D("3"), Proposito.TP_CRUCE),
        orden_cierre_posicion("XYZ", -7, _cot("3.44", "3.46"), CFG, 1, HORA),
    ]
    for o in ordenes:
        assert type(o.qty) is int and isinstance(o.precio, Decimal) and not isinstance(o.precio, float)


def test_modulo_puro_sin_reloj_io_ni_logging():
    fuente = MODULO.read_text(encoding="utf-8")
    for prohibido in ("datetime.now", "time.time", "time.monotonic", "import logging", "os.environ", "open(",
                      "import time", "httpx", "socket"):
        assert prohibido not in fuente, prohibido


# ═══════════ correcciones de la revisión del 27-sep (hallazgos D2-*) ═══════════
# ── D2-05: salidas del motor por tiempo → hora_evento ───────────────────
@pytest.mark.parametrize("literal", ["Partial TP (Hour)", "Partial TP (Time)", "Time Limit"])
def test_D2_05_salidas_por_tiempo_son_hora_evento(literal):
    """D2-05: ningún temporizador del bot cubre esas horas: el evento se ejecuta (no solo se anota)."""
    lote = _lote()
    pos = _pos(lotes=[lote])
    assert clasificar(literal) is ClaseSalida.HORA
    assert tratamiento(clasificar(literal), pos, lote, []) == TRATAR_HORA_EVENTO
    acciones = avisos_de_tratamiento(TRATAR_HORA_EVENTO, ClaseSalida.HORA, literal, pos, lote)
    assert [a.tipo for a in acciones if isinstance(a, Anotar)] == ["salida_motor"]
    assert not any(isinstance(a, Avisar) for a in acciones)


@pytest.mark.parametrize("literal", ["Partial TP (EOD)", "EOD"])
def test_D2_05_eod_lo_sigue_cubriendo_el_reloj(literal):
    lote = _lote()
    assert tratamiento(clasificar(literal), _pos(lotes=[lote]), lote, []) == TRATAR_ANOTAR


@pytest.mark.parametrize("lote, vivas", [
    (None, []),
    (_lote(estado=EstadoLote.CERRADO), []),
    (_lote(llenas=100, tp_pendiente=100), []),
    (_lote(), [_orden(proposito=Proposito.HORA_ASK)]),
], ids=["sin_lote", "lote_cerrado", "sin_libres", "cierre_total_en_curso"])
def test_D2_05_hora_evento_sin_nada_que_cerrar_solo_se_anota(lote, vivas):
    """Riesgo 6: la salida por tiempo tampoco añade una segunda orden de compra sobre las mismas acciones."""
    assert tratamiento(ClaseSalida.HORA, _pos(lotes=[lote] if lote else []), lote, vivas) == TRATAR_ANOTAR


def test_D2_05_orden_hora_evento_al_ask_sin_techo_con_la_qty_del_evento():
    lote = _lote(llenas=500, tp_pendiente=100)
    orden = salidas.orden_hora_evento(lote, 300, _cot("11.90", "12.00", last="10.00"), CFG, 7, HORA)
    assert (orden.lado, orden.qty, orden.precio, orden.post_only) == (Lado.COMPRA, 300, D("12.00"), False)
    assert orden.proposito is Proposito.HORA_ASK and orden.lote_id == "L1" and orden.ruta == "SAGEPRO"
    tope = salidas.orden_hora_evento(lote, 1000, _cot("10", "10.05", last="10"), CFG, 8, HORA)
    assert tope.qty == 400, "nunca más de llenas − tp_pendiente (área E)"


@pytest.mark.parametrize("lote, qty, cot", [
    (_lote(), 0, _cot("10", "10.05")),
    (_lote(), -5, _cot("10", "10.05")),
    (_lote(), None, _cot("10", "10.05")),
    (_lote(llenas=100, tp_pendiente=100), 50, _cot("10", "10.05")),
    (_lote(), 50, _cot("10", None)),
], ids=["cero", "negativa", "sin_qty", "sin_libres", "sin_ask"])
def test_D2_05_orden_hora_evento_errores(lote, qty, cot):
    with pytest.raises(ValueError):
        salidas.orden_hora_evento(lote, qty, cot, CFG, 1, HORA)


# ── D2-16: literal desconocido → aviso 2 siempre ─────────────────────────
@pytest.mark.parametrize("codigo", [TRATAR_ANOTAR, TRATAR_COMO_TP, TRATAR_IGNORAR])
def test_D2_16_literal_desconocido_avisa_nivel_2_aunque_se_anote(codigo):
    lote = _lote()
    acciones = avisos_de_tratamiento(codigo, ClaseSalida.MOTOR, "Motivo Nuevo", _pos(lotes=[lote]), lote)
    avisos = [a for a in acciones if isinstance(a, Avisar)]
    assert [(a.nivel, a.clave) for a in avisos] == [(Nivel.AVISO, "salida_desconocida:Motivo Nuevo")]
    assert "DESCONOCIDA" in avisos[0].texto and "Motivo Nuevo" in avisos[0].texto
    assert [a.tipo for a in acciones if isinstance(a, Anotar)] == ["salida_motor", "salida_desconocida"]


def test_D2_16_sin_lote_tambien_avisa():
    acciones = avisos_de_tratamiento(TRATAR_ANOTAR, ClaseSalida.MOTOR, None, _pos(), None)
    assert [a.nivel for a in acciones if isinstance(a, Avisar)] == [Nivel.AVISO]


# ── D2-08: textos de aviso escapados para el HTML de Telegram ────────────
def test_D2_08_avisos_de_salidas_escapan_el_html():
    lote = Lote(id="L1", strategy_id="s1", estrategia="PM <A> & B", ticker="XYZ", direccion="Short", pedidas=100,
                llenas=100, precio_medio=D("10"), nivel_stop=D("11"), estado=EstadoLote.ABIERTO)
    pos = _pos(neta_fills=-100, neta_das=-100, lotes=[lote])
    textos = [a.texto for a in avisos_de_tratamiento(TRATAR_COMO_TP, ClaseSalida.MOTOR, "Raro <x>", pos, lote)
              if isinstance(a, Avisar)]
    textos += [a.texto for a in avisos_de_tratamiento(TRATAR_DIVERGENCIA, ClaseSalida.STOP, "SL", pos, lote)
               if isinstance(a, Avisar)]
    textos.append(comprobar_eod(lote, pos).texto)
    textos.append(tp_al_vencer(lote, 100, _cot("10", "12", last="10"), CFG, 1, HORA)[1].texto)
    textos.append(cerrar_todo({"XYZ": pos}, _cot_de({}), CFG, _tokens(), HORA)[-2].texto)
    for texto in textos:
        assert "<A>" not in texto and "<x>" not in texto and "& B" not in texto, texto
    assert any("PM &lt;A&gt; &amp; B" in t for t in textos)
    assert any("Raro &lt;x&gt;" in t for t in textos)


# ── D2-07: tp_cruce por ORDEN ────────────────────────────────────────────
def test_D2_07_dos_tp_del_mismo_lote_no_se_pisan():
    lote = _lote(llenas=500)
    _, p1 = tp_parcial(lote, 100, _cot("10.00", "10.04"), CFG, 1, HORA)
    _, p2 = tp_parcial(lote, 100, _cot("10.00", "10.04"), CFG, 2, HORA)
    assert (p1.clave, p2.clave) == ("tp_cruce:L1:1", "tp_cruce:L1:2")
    assert (p1.datos["token"], p2.datos["token"]) == (1, 2)
    assert salidas.clave_tp_cruce("L1", 7) == "tp_cruce:L1:7"
    assert p1.clave.startswith(f"{salidas.CLAVE_TP_CRUCE}:L1:"), "el decisor desprograma por prefijo del lote"


# ── D2-12: libro inutilizable no se convierte en excepción ───────────────
@pytest.mark.parametrize("cot, ok", [
    (_cot("10.00", "10.04"), True), (_cot("10.05", "10.00"), False), (_cot(None, "10"), False), (None, False),
    (_cot("0.0001", "0.0001"), False), (_cot("10.00", "10.00"), True),
], ids=["normal", "cruzado", "sin_bid", "sin_cot", "bloqueado_tick_minimo", "bloqueado"])
def test_D2_12_libro_para_agregar(cot, ok):
    assert salidas.libro_para_agregar(cot) is ok


def test_D2_12_tp_parcial_sin_libro_programa_el_cruce_en_vez_de_lanzar():
    lote = _lote(llenas=500)
    orden, prog = tp_parcial(lote, 300, _cot("10.05", "10.00", last="10"), CFG, 41, HORA, sin_libro_espera_s=2.0)
    assert orden is None
    assert prog.clave == "tp_cruce:L1:41" and prog.en_s == 2.0
    assert prog.datos == {"lote_id": "L1", "ticker": "XYZ", "token": None, "token_reservado": 41, "qty": 300,
                          "sin_libro": True}
    normal, prog_normal = tp_parcial(lote, 300, _cot("10.00", "10.04"), CFG, 42, HORA, sin_libro_espera_s=2.0)
    assert normal is not None and prog_normal.datos["token"] == 42
    with pytest.raises(ValueError):
        tp_parcial(lote, 300, _cot("10.05", "10.00"), CFG, 43, HORA)     # sin el parámetro: el contrato de siempre


# ── D2-13: la orden de cruce del TP que no llena → aviso de limbo ────────
def test_D2_13_programa_y_comprobacion_del_limbo_del_tp():
    lote = _lote()
    orden, _ = tp_al_vencer(lote, 100, _cot("10.00", "10.10", last="10.00"), CFG, 55, HORA)
    prog = salidas.programa_limbo_tp(lote, orden, CFG)
    assert prog.clave == "tp_limbo:L1:55" and prog.en_s == 5.0
    assert prog.datos == {"lote_id": "L1", "ticker": "XYZ", "token": 55, "qty": 100}
    viva = _orden(token=55, proposito=Proposito.TP_CRUCE, qty=100, lvqty=60, llenas=40, precio="10.10")
    aviso = salidas.comprobar_limbo_tp(lote, viva)
    assert aviso is not None and aviso.nivel is Nivel.AVISO and aviso.clave == "limbo:L1:55"
    assert "60 acciones" in aviso.texto and "No se persigue" in aviso.texto
    assert salidas.comprobar_limbo_tp(lote, _orden(token=55, estado=EstadoOrden.EXECUTED)) is None
    assert salidas.comprobar_limbo_tp(lote, _orden(token=55, qty=100, llenas=100)) is None
    cfg = _config({"tp_parcial": {"limbo_comprobar_s": 3}})
    assert salidas.programa_limbo_tp(lote, orden, cfg).en_s == 3.0


# ── D2-14: la ruta de cierre por el precio de la ACCIÓN ──────────────────
def test_D2_14_ruta_de_cierre_por_el_precio_de_la_accion():
    compra = orden_cierre_posicion("X", -100, _cot("0.9600", "0.9700"), CFG, 1, HORA)
    assert compra.precio == D("1.02") and compra.ruta == "EDGA", "0,97 $ es de < 1 $ aunque el límite pase de 1 $"
    venta = orden_cierre_posicion("X", 100, _cot("1.02", "1.03"), CFG, 1, HORA)
    assert venta.precio < 1 and venta.ruta == "SAGEPRO", "1,02 $ es de ≥ 1 $ aunque el suelo baje de 1 $"


# ── D2-02 / R3-SAL-1: la neta de «cerrar todo» nunca compra de más ───────
# Horas en el monotónico del decisor: FILL = nuestro último fill en el ticker; el %POS llegó ANTES o DESPUÉS.
FILL, ANTES, DESPUES = 100.0, 90.0, 110.0


def _cerrado(llenas: int = 100, ticker: str = "XYZ") -> Lote:
    return _lote("C", ticker=ticker, estado=EstadoLote.CERRADO, llenas=llenas)


@pytest.mark.parametrize("fills, das, das_en, fill_en, lotes, esperado", [
    pytest.param(-100, None, None, FILL, [], (-100, "fills"), id="D2-02-sin_das"),
    pytest.param(-100, -100, ANTES, FILL, [], (-100, "fills"), id="D2-02-coinciden_aunque_sea_anterior"),
    # sin ningún rastro del bot (D2-02 «manual pura»): nada nuestro puede dejar atrasado el %POS
    pytest.param(0, -30, None, None, [], (-30, "das"), id="R3-SAL-1-manual_pura_sin_hora"),
    pytest.param(0, 50, None, None, [_lote("K", estado=EstadoLote.CANCELADO, llenas=0)], (50, "das"),
                 id="R3-SAL-1-manual_pura_con_lote_cancelado_sin_llenar"),
    pytest.param(0, -30, DESPUES, None, [], (-30, "das"), id="R3-SAL-1-manual_pura_con_hora"),
    # CONFIRMADA: el %POS llegó después de nuestro último fill
    pytest.param(0, -50, DESPUES, FILL, [_cerrado()], (-50, "das"), id="R3-SAL-1-ronda1_lote_cerrado_das_confirmada"),
    pytest.param(0, -50, DESPUES, FILL, [_cerrado(), _lote("V", estado=EstadoLote.ABIERTO, llenas=0)], (-50, "das"),
                 id="R3-SAL-1-manual_con_lote_vivo_sin_acciones"),
    pytest.param(0, -50, DESPUES, None, [_lote("V", estado=EstadoLote.ABIERTO, llenas=0)], (-50, "das"),
                 id="R3-SAL-1-entrada_viva_sin_fills_y_das_con_hora"),
    pytest.param(-100, -150, DESPUES, FILL, [], (-100, "minimo"), id="R3-SAL-1-confirmada_min_das_mayor"),
    pytest.param(-150, -100, DESPUES, FILL, [], (-100, "minimo"), id="R3-SAL-1-confirmada_min_fills_mayor"),
    pytest.param(-100, 0, DESPUES, FILL, [], (0, "cerrada_en_das"), id="R3-SAL-1-das_plana_confirmada"),
    pytest.param(-100, 50, DESPUES, FILL, [], (0, "discrepancia"), id="R3-SAL-1-signos_opuestos_confirmada"),
    # SIN CONFIRMAR: nunca se compra nada
    pytest.param(0, -100, ANTES, FILL, [_cerrado()], (0, "sin_confirmar"), id="R3-SAL-1-pos_atrasado_tras_el_cierre"),
    pytest.param(0, -100, FILL, FILL, [_cerrado()], (0, "sin_confirmar"), id="R3-SAL-1-misma_hora_no_confirma"),
    pytest.param(0, -100, None, FILL, [_cerrado()], (0, "sin_confirmar"), id="R3-SAL-1-das_sin_hora"),
    pytest.param(0, -100, DESPUES, None, [_cerrado()], (0, "sin_confirmar"),
                 id="R3-SAL-1-lote_con_acciones_sin_hora_de_fill"),
    pytest.param(0, -100, DESPUES, None, [_cerrado(llenas=0)], (0, "sin_confirmar"),
                 id="R3-SAL-1-lote_cerrado_sin_hora_de_fill"),
    pytest.param(-40, -100, DESPUES, None, [], (0, "sin_confirmar"), id="R3-SAL-1-fills_sin_hora_de_fill"),
    pytest.param(0, -50, None, None, [_lote("V", estado=EstadoLote.ABIERTO, llenas=0)], (0, "sin_confirmar"),
                 id="R3-SAL-1-entrada_viva_y_das_sin_hora"),
    pytest.param(-100, -150, ANTES, FILL, [], (0, "sin_confirmar"), id="R3-SAL-1-mismo_signo_atrasada_no_da_minimo"),
    pytest.param(-100, 0, ANTES, FILL, [], (0, "sin_confirmar"), id="R3-SAL-1-das_plana_atrasada"),
    pytest.param(-100, 50, ANTES, FILL, [], (0, "sin_confirmar"), id="R3-SAL-1-signos_opuestos_atrasada"),
])
def test_R3_SAL_1_neta_para_cerrar(fills, das, das_en, fill_en, lotes, esperado):
    """R3-SAL-1: la cifra de DAS solo vale CONFIRMADA (%POS posterior a nuestro último fill); si no, 0 y consultar."""
    pos = _pos(neta_fills=fills, neta_das=das, lotes=lotes, das_en=das_en, fill_en=fill_en)
    assert salidas.neta_para_cerrar(pos) == esperado
    assert salidas.das_sin_confirmar(pos) is (esperado[1] == salidas.NETA_SIN_CONFIRMAR)
    if das is not None and das != fills:
        assert salidas.das_confirmada(pos) is (esperado[1] != salidas.NETA_SIN_CONFIRMAR)


def test_R3_SAL_1_constantes_de_fuente():
    assert (salidas.NETA_SIN_CONFIRMAR, salidas.NETA_CERRADA_EN_DAS) == ("sin_confirmar", "cerrada_en_das")
    assert salidas.NETA_DAS_MANUAL == salidas.NETA_DAS == "das", "el nombre anterior sigue existiendo"
    assert salidas.das_confirmada(_pos(neta_das=None, das_en=DESPUES)) is False, "sin cifra de DAS no hay nada que confirmar"


@pytest.mark.parametrize("fase, intento", [
    (None, 0), (salidas.FASE_CANCELAR, 0), (salidas.FASE_ENVIAR, 0), (salidas.FASE_CANCELAR, 1),
    (salidas.FASE_ENVIAR, 2),
], ids=["R3-SAL-1-a-fase_none", "R3-SAL-1-a-primera_mirada", "R3-SAL-1-a-enviar", "R3-SAL-1-a-reintento",
        "R3-SAL-1-a-ultimo_reintento"])
def test_R3_SAL_1_verificador_a_pos_atrasado_tras_el_cierre_no_compra(fase, intento):
    """R3-SAL-1, caso (a) del verificador: el bot acaba de cerrar su lote (fills 0, último fill en 100) y el %POS
    sigue en −100 (llegó en 90). Sin órdenes vivas, TAMBIÉN en la primera mirada: 0 compras, GET POSITIONS y reintento."""
    pos = _pos("X", neta_fills=0, neta_das=-100, lotes=[_cerrado(ticker="X")], das_en=ANTES, fill_en=FILL)
    acciones = cerrar_todo({"X": pos}, _cot_de({"X": _cot("10", "10.1", ticker="X")}), CFG, _tokens(), HORA,
                           intento=intento, vivas_de=_vivas_de({}), fase=fase)
    assert not any(isinstance(a, EnviarOrden) for a in acciones), "nunca comprar el %POS atrasado (cuenta larga)"
    assert [a.comando for a in acciones if isinstance(a, Consultar)] == ["GET POSITIONS"]
    assert [(p.clave, p.datos["intento"], p.datos["fase"]) for p in acciones if isinstance(p, Programar)] == [
        ("cerrar_todo:X", intento + 1, "cancelar")]
    nota = [a.datos for a in acciones if isinstance(a, Anotar) and a.tipo == "cerrar_todo_das_sin_confirmar"]
    assert len(nota) == 1 and nota[0]["neta_das_en"] == ANTES and nota[0]["ultimo_fill_en"] == FILL
    assert not any(isinstance(a, Avisar) for a in acciones)


def test_R3_SAL_1_verificador_a_el_pos_posterior_cierra_el_ciclo_sin_comprar():
    """R3-SAL-1: tras el GET POSITIONS llega el %POS de después del fill (0): fills y DAS coinciden, nada que cerrar."""
    atrasado = _pos("X", neta_fills=0, neta_das=-100, lotes=[_cerrado(ticker="X")], das_en=ANTES, fill_en=FILL)
    cots = _cot_de({"X": _cot("10", "10.1", ticker="X")})
    primero = cerrar_todo({"X": atrasado}, cots, CFG, _tokens(), HORA, vivas_de=_vivas_de({}),
                          fase=salidas.FASE_CANCELAR)
    assert not any(isinstance(a, EnviarOrden) for a in primero)
    al_dia = _pos("X", neta_fills=0, neta_das=0, lotes=[_cerrado(ticker="X")], das_en=DESPUES, fill_en=FILL)
    segundo = cerrar_todo({"X": al_dia}, cots, CFG, _tokens(), HORA, intento=1, vivas_de=_vivas_de({}),
                          fase=salidas.FASE_CANCELAR)
    assert [type(a) for a in segundo] == [Anotar], "plano en las dos fuentes: ni orden, ni consulta, ni reintento"


@pytest.mark.parametrize("intento", [0, 1, 2], ids=["R3-SAL-1-b-intento_0", "R3-SAL-1-b-intento_1",
                                                     "R3-SAL-1-b-intento_2"])
def test_R3_SAL_1_verificador_b_manual_con_lote_cerrado_y_orden_viva_se_cierra(intento):
    """R3-SAL-1, caso (b) del verificador: posición manual (DAS −50 confirmada) en un ticker con un lote del bot
    CERRADO hoy y una orden viva: el paso «cancelar» espera el Canceled y el paso «enviar» compra 50, en CUALQUIER
    intento (antes quedaba sin cerrar para siempre)."""
    pos = _pos("X", neta_fills=0, neta_das=-50, lotes=[_cerrado(ticker="X")], das_en=DESPUES, fill_en=FILL)
    cots = _cot_de({"X": _cot("10", "10.1", ticker="X")})
    paso1 = cerrar_todo({"X": pos}, cots, CFG, _tokens(), HORA, intento=intento,
                        vivas_de=_vivas_de({"X": [_viva(7, 50, proposito=Proposito.STOP_PROTECCION)]}),
                        fase=salidas.FASE_CANCELAR)
    assert any(isinstance(a, CancelarTicker) for a in paso1) and not any(isinstance(a, EnviarOrden) for a in paso1)
    assert [p.datos["fase"] for p in paso1 if isinstance(p, Programar)] == ["enviar"]
    paso2 = cerrar_todo({"X": pos}, cots, CFG, _tokens(), HORA, intento=intento, vivas_de=_vivas_de({}),
                        fase=salidas.FASE_ENVIAR)
    assert [(a.orden.lado, a.orden.qty) for a in paso2 if isinstance(a, EnviarOrden)] == [(Lado.COMPRA, 50)]
    disc = [a.datos for a in paso2 if isinstance(a, Anotar) and a.tipo == "discrepancia"]
    assert disc and disc[0]["usada"] == -50 and disc[0]["fuente"] == "das"


def test_R3_SAL_1_verificador_b_orden_viva_en_el_paso_enviar_se_descuenta():
    """R3-SAL-1: si en «enviar» aún vive una compra de 50 (el Canceled no llegó), no se compra otra (riesgo 6)."""
    pos = _pos("X", neta_fills=0, neta_das=-50, lotes=[_cerrado(ticker="X")], das_en=DESPUES, fill_en=FILL)
    acciones = cerrar_todo({"X": pos}, _cot_de({"X": _cot("10", "10.1", ticker="X")}), CFG, _tokens(), HORA,
                           vivas_de=_vivas_de({"X": [_viva(7, 50, proposito=Proposito.STOP_PROTECCION)]}),
                           fase=salidas.FASE_ENVIAR)
    assert not any(isinstance(a, EnviarOrden) for a in acciones)
    assert any(isinstance(a, Anotar) and a.tipo == "cerrar_todo_en_vuelo" for a in acciones)


@pytest.mark.parametrize("fase", [None, salidas.FASE_CANCELAR], ids=["R3-SAL-1-ronda1-fase_none",
                                                                     "R3-SAL-1-ronda1-fase_cancelar"])
def test_R3_SAL_1_ronda1_lote_cerrado_con_100_llenas_cierra_la_manual(fase):
    """R3-SAL-1 (caso de la ronda 1, R-D-06 «incluidas las manuales»): lote CERRADO con 100 llenas, fills 0 y DAS −50
    CONFIRMADA → compra 50 y consulta."""
    pos = _pos("X", neta_fills=0, neta_das=-50, lotes=[_cerrado(ticker="X")], das_en=DESPUES, fill_en=FILL)
    acciones = cerrar_todo({"X": pos}, _cot_de({"X": _cot("10", "10.1", ticker="X")}), CFG, _tokens(), HORA,
                           intento=0, vivas_de=_vivas_de({}), fase=fase)
    assert [(a.orden.lado, a.orden.qty) for a in acciones if isinstance(a, EnviarOrden)] == [(Lado.COMPRA, 50)]
    assert [a.comando for a in acciones if isinstance(a, Consultar)] == ["GET POSITIONS"]
    assert not any(isinstance(a, Anotar) and a.tipo == "cerrar_todo_das_sin_confirmar" for a in acciones)


@pytest.mark.parametrize("fase, cancela", [(None, True), (salidas.FASE_CANCELAR, True), (salidas.FASE_ENVIAR, False)],
                         ids=["R3-SAL-1-cerrada-fase_none", "R3-SAL-1-cerrada-cancelar", "R3-SAL-1-cerrada-enviar"])
def test_R3_SAL_1_das_plana_confirmada_se_trata_como_cerrada(fase, cancela):
    """R3-SAL-1: fills −100 y DAS 0 CONFIRMADA (Jaume la cerró a mano) → sin orden ni reintento; se anota; lo vivo se
    cancela en el paso 1 (una compra viva sobre una cuenta plana la dejaría larga)."""
    pos = _pos("X", neta_fills=-100, neta_das=0, lotes=[_lote("L1", ticker="X")], das_en=DESPUES, fill_en=FILL)
    acciones = cerrar_todo({"X": pos}, _cot_de({"X": _cot("10", "10.1", ticker="X")}), CFG, _tokens(), HORA,
                           vivas_de=_vivas_de({"X": [_viva(5, 100, proposito=Proposito.STOP)]}), fase=fase)
    assert not any(isinstance(a, (EnviarOrden, Programar, Avisar)) for a in acciones)
    assert any(isinstance(a, CancelarTicker) for a in acciones) is cancela
    nota = [a.datos for a in acciones if isinstance(a, Anotar) and a.tipo == "cerrar_todo_cerrada_en_das"]
    assert len(nota) == 1 and nota[0]["neta_fills"] == -100 and nota[0]["neta_das"] == 0


def test_R3_SAL_1_das_plana_confirmada_sin_aviso_de_agotado():
    """R3-SAL-1: al agotar, una cerrada en DAS no avisa «sigue abierta»; solo retira la orden de cierre y se anota."""
    pos = _pos("X", neta_fills=-100, neta_das=0, das_en=DESPUES, fill_en=FILL)
    acciones = cerrar_todo({"X": pos}, _cot_de({}), CFG, _tokens(), HORA, intento=3,
                           vivas_de=_vivas_de({"X": [_viva(5, 100, id_das=901)]}))
    assert not any(isinstance(a, Avisar) for a in acciones)
    assert [(a.id_das, a.token) for a in acciones if isinstance(a, Cancelar)] == [(901, 5)]
    assert any(isinstance(a, Anotar) and a.tipo == "cerrar_todo_cerrada_en_das" for a in acciones)


def test_D2_02_primer_cierre_lleno_y_pos_atrasado_no_vuelve_a_comprar():
    """D2-02 / R3-SAL-1: tras llenar el cierre (fills 0, lote CERRADO, sin hora de fill) DAS aún dice −100: no se
    compra; consulta y reintenta."""
    pos = _pos("X", neta_fills=0, neta_das=-100, lotes=[_lote("L1", ticker="X", estado=EstadoLote.CERRADO, llenas=0)])
    acciones = cerrar_todo({"X": pos}, _cot_de({"X": _cot("10", "10.1", ticker="X")}), CFG, _tokens(), HORA, intento=1)
    assert not any(isinstance(a, EnviarOrden) for a in acciones)
    assert [a.comando for a in acciones if isinstance(a, Consultar)] == ["GET POSITIONS"]
    assert [a.clave for a in acciones if isinstance(a, Programar)] == ["cerrar_todo:X"]
    assert [a.datos["ticker"] for a in acciones if isinstance(a, Anotar)
            and a.tipo == "cerrar_todo_das_sin_confirmar"] == ["X"]


def test_D2_02_un_solo_get_positions_por_llamada():
    posiciones = {t: _pos(t, neta_fills=-100, neta_das=-150, das_en=DESPUES, fill_en=FILL) for t in ("A", "B")}
    acciones = cerrar_todo(posiciones, _cot_de({t: _cot("10", "10.1", ticker=t) for t in ("A", "B")}), CFG,
                           _tokens(), HORA)
    assert len([a for a in acciones if isinstance(a, Consultar)]) == 1
    assert [a.orden.qty for a in acciones if isinstance(a, EnviarOrden)] == [100, 100]


# ── D2-01: un temporizador por ticker ────────────────────────────────────
def test_D2_01_cerrar_x_y_luego_y_no_se_pisan():
    posiciones = {"X": _pos("X", neta_fills=-100), "Y": _pos("Y", neta_fills=-50)}
    cots = _cot_de({"X": _cot("10", "10.1", ticker="X"), "Y": _cot("5", "5.05", ticker="Y")})
    px = [a for a in cerrar_todo(posiciones, cots, CFG, _tokens(), HORA, tickers=["X"]) if isinstance(a, Programar)]
    py = [a for a in cerrar_todo(posiciones, cots, CFG, _tokens(), HORA, tickers=["Y"]) if isinstance(a, Programar)]
    assert [p.clave for p in px] == ["cerrar_todo:X"] and [p.clave for p in py] == ["cerrar_todo:Y"]
    assert px[0].datos["tickers"] == ["X"] and py[0].datos["tickers"] == ["Y"]
    assert salidas.clave_cerrar_todo("X") == "cerrar_todo:X"


def test_D2_01_aviso_de_agotado_por_ticker():
    posiciones = {"X": _pos("X", neta_fills=-100), "Y": _pos("Y", neta_fills=-50)}
    acciones = cerrar_todo(posiciones, _cot_de({}), CFG, _tokens(), HORA, intento=3)
    assert [a.clave for a in acciones if isinstance(a, Avisar)] == ["cerrar_todo:X:agotado", "cerrar_todo:Y:agotado"]


# ── D2-03 / G1B-15: primero cancelar, después la orden por la neta de ese momento ──
def _viva(token: int, qty: int, *, proposito: Proposito = Proposito.CIERRE_HUMANO, ticker: str = "X",
          lado: Lado = Lado.COMPRA, id_das: Optional[int] = 900, lvqty: int = 0, llenas: int = 0,
          estado: EstadoOrden = EstadoOrden.ACCEPTED) -> Orden:
    return Orden(token=token, ticker=ticker, lado=lado, tipo=TipoOrden.LIMITE, qty=qty, precio=D("10.61"), stop=None,
                 ruta="SAGEPRO", proposito=proposito, lote_id=None, nivel=None, origen=Origen.EJECUTOR, id_das=id_das,
                 estado=estado, lvqty=lvqty, llenas=llenas)


def _vivas_de(tabla: dict[str, list[Orden]]):
    return lambda t: tabla.get(t, [])


def test_D2_03_con_algo_vivo_cancela_y_espera_el_canceled():
    pos = {"X": _pos("X", neta_fills=-100)}
    vivas = _vivas_de({"X": [_viva(5, 100, proposito=Proposito.STOP)]})
    acciones = cerrar_todo(pos, _cot_de({"X": _cot("10", "10.1", ticker="X")}), CFG, _tokens(), HORA,
                           vivas_de=vivas, fase=salidas.FASE_CANCELAR)
    assert [type(a) for a in acciones if not isinstance(a, Anotar)] == [CancelarTicker, Programar]
    prog = next(a for a in acciones if isinstance(a, Programar))
    assert prog.clave == "cerrar_todo:X" and prog.en_s == 1.0
    assert prog.datos["fase"] == "enviar" and prog.datos["intento"] == 0
    assert not any(isinstance(a, EnviarOrden) for a in acciones), "la orden sale DESPUÉS del Canceled"


def test_D2_03_sin_nada_vivo_envia_en_la_misma_llamada():
    acciones = cerrar_todo({"X": _pos("X", neta_fills=-100)}, _cot_de({"X": _cot("10", "10.1", ticker="X")}), CFG,
                           _tokens(), HORA, vivas_de=_vivas_de({}), fase=salidas.FASE_CANCELAR)
    tipos_ = [type(a) for a in acciones if not isinstance(a, Anotar)]
    assert tipos_ == [CancelarTicker, EnviarOrden, Programar]
    prog = acciones[-1]
    assert prog.datos == {"intento": 1, "tickers": ["X"], "ticker": "X", "proposito": "cierre_humano",
                          "fase": "cancelar"}


def test_D2_03_reintento_con_la_orden_anterior_viva_no_compra_hasta_el_canceled():
    """G1B-15: neta −100 y la orden de cierre anterior (100) viva: el paso «enviar» no compra otra vez."""
    pos = {"X": _pos("X", neta_fills=-100)}
    vivas = _vivas_de({"X": [_viva(5, 100)]})
    acciones = cerrar_todo(pos, _cot_de({"X": _cot("10", "10.1", ticker="X")}), CFG, _tokens(), HORA, intento=1,
                           vivas_de=vivas, fase=salidas.FASE_ENVIAR)
    assert not any(isinstance(a, (EnviarOrden, CancelarTicker)) for a in acciones)
    assert any(isinstance(a, Consultar) and a.comando == "GET ORDERS" for a in acciones)
    assert any(isinstance(a, Anotar) and a.tipo == "cerrar_todo_en_vuelo" for a in acciones)
    prog = [a for a in acciones if isinstance(a, Programar)]
    assert prog[0].clave == "cerrar_todo:X" and prog[0].datos["intento"] == 2 and prog[0].datos["fase"] == "cancelar"


@pytest.mark.parametrize("vivas, esperado", [
    ([], 100),
    ([_viva(5, 100, lvqty=40, llenas=60)], 60),
    ([_viva(5, 30, proposito=Proposito.STOP)], 70),
    ([_viva(5, 100, lado=Lado.CORTO)], 100),                     # una venta no compra: no descuenta
    ([_viva(5, 100, estado=EstadoOrden.CANCELED)], 100),         # terminada: no cuenta
    ([_viva(5, 100, ticker="OTRO")], 100),
], ids=["D2-03-nada", "D2-03-parcial", "D2-03-stop-en-vuelo", "D2-03-venta", "D2-03-cancelada", "D2-03-otro-ticker"])
def test_D2_03_enviar_descuenta_las_compras_en_vuelo(vivas, esperado):
    acciones = cerrar_todo({"X": _pos("X", neta_fills=-100)}, _cot_de({"X": _cot("10", "10.1", ticker="X")}), CFG,
                           _tokens(), HORA, vivas_de=_vivas_de({"X": vivas}), fase=salidas.FASE_ENVIAR)
    assert [a.orden.qty for a in acciones if isinstance(a, EnviarOrden)] == [esperado]


def test_D2_03_sin_fase_descuenta_lo_vivo_en_la_misma_llamada():
    """Contrato anterior (fase None): cancelar y enviar juntos, pero sin comprar lo que los stops vivos aún pueden comprar."""
    vivas = _vivas_de({"X": [_viva(5, 100, proposito=Proposito.STOP),
                             _viva(6, 100, proposito=Proposito.STOP)]})
    acciones = cerrar_todo({"X": _pos("X", neta_fills=-100)}, _cot_de({"X": _cot("10", "10.1", ticker="X")}), CFG,
                           _tokens(), HORA, vivas_de=vivas)
    assert isinstance(acciones[1], CancelarTicker) and not any(isinstance(a, EnviarOrden) for a in acciones)
    assert [a.clave for a in acciones if isinstance(a, Programar)] == ["cerrar_todo:X"]


def test_D2_03_fase_desconocida_lanza():
    with pytest.raises(ValueError):
        cerrar_todo({"X": _pos("X")}, _cot_de({}), CFG, _tokens(), HORA, fase="ya")


# ── D2-04: al agotar se retira la orden de cierre viva antes de avisar ───
def test_D2_04_agotado_cancela_la_orden_de_cierre_por_id_antes_de_avisar():
    vivas = _vivas_de({"X": [_viva(5, 100, id_das=901), _viva(6, 100, proposito=Proposito.STOP,
                                                                id_das=902)]})
    acciones = cerrar_todo({"X": _pos("X", neta_fills=-100)}, _cot_de({"X": _cot("10", "10.1", last="10", ticker="X")}),
                           CFG, _tokens(), HORA, intento=3, vivas_de=vivas)
    cancelaciones = [a for a in acciones if isinstance(a, Cancelar)]
    assert [(c.id_das, c.token) for c in cancelaciones] == [(901, 5)], "solo la orden de cierre, no el stop"
    aviso = next(a for a in acciones if isinstance(a, Avisar))
    assert acciones.index(cancelaciones[0]) < acciones.index(aviso)
    assert aviso.nivel is Nivel.MAXIMO and "RETIRADO" in aviso.texto and "stops" in aviso.texto
    assert not any(isinstance(a, (EnviarOrden, Programar)) for a in acciones)


@pytest.mark.parametrize("vivas_de, esperado", [
    (None, [CancelarTicker]),
    (_vivas_de({"X": [_viva(5, 100, id_das=None)]}), [CancelarTicker]),
    (_vivas_de({"X": []}), []),
], ids=["D2-04-sin-vivas-conocidas", "D2-04-orden-sin-id", "D2-04-nada-que-retirar"])
def test_D2_04_agotado_sin_ids_cancela_el_ticker(vivas_de, esperado):
    acciones = cerrar_todo({"X": _pos("X", neta_fills=-100)}, _cot_de({}), CFG, _tokens(), HORA, intento=3,
                           vivas_de=vivas_de)
    assert [type(a) for a in acciones if isinstance(a, (Cancelar, CancelarTicker))] == esperado


# ── A-02: el share del REPLACE sale de tipos.share_de_replace ────────────
def test_A_02_perseguir_ask_usa_share_de_replace():
    orden = _orden(qty=100, lvqty=60, llenas=40, precio="10.00")
    assert perseguir_ask(orden, _cot("10.05", "10.10"), 0).qty == 60
    assert perseguir_ask(orden, _cot("10.05", "10.10"), 0, share_es_abierta=True).qty == 60
    assert perseguir_ask(orden, _cot("10.05", "10.10"), 0, share_es_abierta=False).qty == 100


# ── A-06: los GET por protocolo.cmd_get ──────────────────────────────────
def test_A_06_consultas_por_protocolo():
    from app.bot_das.protocolo import cmd_get
    assert salidas.COMANDO_POSICIONES == cmd_get("POSITIONS") == "GET POSITIONS"
    assert salidas.COMANDO_ORDENES == cmd_get("ORDERS") == "GET ORDERS"


# ── R2-SAL-3: la fase «enviar» usa neta_para_cerrar y el agotado da la cantidad real ──
@pytest.mark.parametrize("fills, das, das_en, fill_en, lotes, esperado", [
    (-100, -150, DESPUES, FILL, [], 100),
    (0, -80, None, None, [], 80),
    (0, -80, None, None, [_lote("K", ticker="X", estado=EstadoLote.CANCELADO, llenas=0)], 80),
    (-100, None, None, FILL, [], 100),
], ids=["R2-SAL-3-minimo_confirmado", "R2-SAL-3-manual_pura", "R2-SAL-3-manual_con_cancelado", "R2-SAL-3-fills"])
def test_R2_SAL_3_fase_enviar_usa_neta_para_cerrar(fills, das, das_en, fill_en, lotes, esperado):
    """R2-SAL-3: en el paso «enviar» (tras el Canceled) la cantidad es la de neta_para_cerrar de ESE momento."""
    pos = _pos("X", neta_fills=fills, neta_das=das, lotes=lotes, das_en=das_en, fill_en=fill_en)
    acciones = cerrar_todo({"X": pos}, _cot_de({"X": _cot("10", "10.1", ticker="X")}), CFG, _tokens(), HORA,
                           intento=0, vivas_de=_vivas_de({}), fase=salidas.FASE_ENVIAR)
    assert [a.orden.qty for a in acciones if isinstance(a, EnviarOrden)] == [esperado]
    assert not any(isinstance(a, CancelarTicker) for a in acciones), "el paso «enviar» no vuelve a cancelar"


@pytest.mark.parametrize("intento", [0, 1, 2], ids=["R2-SAL-3-enviar_intento_0", "R2-SAL-3-enviar_intento_1",
                                                     "R2-SAL-3-enviar_intento_2"])
def test_R2_SAL_3_fase_enviar_no_compra_la_cifra_de_das_sin_confirmar(intento):
    """R2-SAL-3 / D2-02: en «enviar» el stop del bot pudo llenar mientras se cancelaba: fills 0 y DAS −100 atrasado
    con el lote CERRADO → sin orden; GET POSITIONS y el reintento en fase «cancelar»."""
    pos = _pos("X", neta_fills=0, neta_das=-100, lotes=[_lote("L1", ticker="X", estado=EstadoLote.CERRADO, llenas=0)])
    acciones = cerrar_todo({"X": pos}, _cot_de({"X": _cot("10", "10.1", ticker="X")}), CFG, _tokens(), HORA,
                           intento=intento, vivas_de=_vivas_de({}), fase=salidas.FASE_ENVIAR)
    assert not any(isinstance(a, EnviarOrden) for a in acciones)
    assert [a.comando for a in acciones if isinstance(a, Consultar)] == ["GET POSITIONS"]
    prog = [a for a in acciones if isinstance(a, Programar)]
    assert [(p.clave, p.datos["intento"], p.datos["fase"]) for p in prog] == [("cerrar_todo:X", intento + 1, "cancelar")]


def test_R2_SAL_3_agotado_dice_la_cantidad_real_de_una_manual_tras_lotes():
    """R2-SAL-3 / R3-SAL-1: agotado con fills 0, DAS −50 SIN CONFIRMAR (el %POS es anterior al último fill) y lote
    CERRADO → «neta -50», no «neta 0», marcada como sin confirmar."""
    pos = _pos("X", neta_fills=0, neta_das=-50, lotes=[_lote("L1", ticker="X", estado=EstadoLote.CERRADO, llenas=100)],
               das_en=ANTES, fill_en=FILL)
    acciones = cerrar_todo({"X": pos}, _cot_de({"X": _cot("10", "10.1", ticker="X")}), CFG, _tokens(), HORA,
                           intento=3, vivas_de=_vivas_de({}))
    avisos_ = [a for a in acciones if isinstance(a, Avisar)]
    assert [a.clave for a in avisos_] == ["cerrar_todo:X:agotado"]
    texto = avisos_[0].texto
    assert "neta -50 (fills 0, DAS -50)" in texto and "neta 0" not in texto
    assert "SIN CONFIRMAR" in texto
    assert not any(isinstance(a, EnviarOrden) for a in acciones)


@pytest.mark.parametrize("fills, das, das_en, fill_en, mostrada", [
    (0, -30, None, None, "neta -30 (fills 0, DAS -30)"),
    (-100, -150, DESPUES, FILL, "neta -100 (fills -100, DAS -150)"),
    (-100, None, None, FILL, "neta -100 (fills -100, DAS ?)"),
    (-100, 50, DESPUES, FILL, "neta -100 (fills -100, DAS 50)"),
], ids=["R2-SAL-3-agotado_manual_pura", "R2-SAL-3-agotado_minimo", "R2-SAL-3-agotado_sin_das",
        "R2-SAL-3-agotado_signos_distintos"])
def test_R2_SAL_3_agotado_neta_real(fills, das, das_en, fill_en, mostrada):
    """R2-SAL-3: el aviso de agotado da la neta de neta_para_cerrar (o la de fills si esa es 0) y las dos fuentes."""
    pos = _pos("X", neta_fills=fills, neta_das=das, das_en=das_en, fill_en=fill_en)
    texto = next(a.texto for a in cerrar_todo({"X": pos}, _cot_de({}), CFG, _tokens(), HORA, intento=3)
                 if isinstance(a, Avisar))
    assert mostrada in texto and "SIN CONFIRMAR" not in texto


@pytest.mark.parametrize("fills, das, mostrada", [
    (-100, -150, "neta -100 (fills -100, DAS -150)"),
    (-100, 50, "neta -100 (fills -100, DAS 50)"),
], ids=["R3-SAL-1-agotado_mismo_signo_sin_confirmar", "R3-SAL-1-agotado_signos_distintos_sin_confirmar"])
def test_R3_SAL_1_agotado_con_das_sin_confirmar_lo_marca(fills, das, mostrada):
    """R3-SAL-1: al agotar con la cifra de DAS sin confirmar, el aviso la marca y da la neta de fills."""
    pos = _pos("X", neta_fills=fills, neta_das=das, das_en=ANTES, fill_en=FILL)
    texto = next(a.texto for a in cerrar_todo({"X": pos}, _cot_de({}), CFG, _tokens(), HORA, intento=3)
                 if isinstance(a, Avisar))
    assert mostrada in texto and "SIN CONFIRMAR" in texto
