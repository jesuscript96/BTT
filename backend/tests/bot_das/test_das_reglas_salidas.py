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
         sin_reentrada: bool = False) -> PosicionTicker:
    return PosicionTicker(ticker=ticker, lotes={lote.id: lote for lote in (lotes or [])}, neta_fills=neta_fills,
                          neta_das=neta_das, estado=estado, sin_reentrada_hasta_sigue=sin_reentrada)


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
    ("Partial TP (EOD)", ClaseSalida.EOD), ("Partial TP (Time)", ClaseSalida.EOD), ("EOD", ClaseSalida.EOD),
    ("SL", ClaseSalida.STOP), ("Pyramid Lot Stop", ClaseSalida.STOP_LOTE), ("Pyramid Reduce", ClaseSalida.REDUCE),
    ("Escalera", ClaseSalida.MOTOR), ("Signal", ClaseSalida.MOTOR), ("Trailing", ClaseSalida.MOTOR),
    ("Time Limit", ClaseSalida.MOTOR), ("?", ClaseSalida.MOTOR), ("Halt", ClaseSalida.HALT),
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
    (ClaseSalida.TP, TRATAR_TP), (ClaseSalida.HORA, TRATAR_ANOTAR), (ClaseSalida.EOD, TRATAR_ANOTAR),
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
    """Pregunta 3: Signal/Trailing/Time Limit → como TP (provisional) con aviso 1; salida_motor=ignorar → ignorar."""
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
    assert prog.clave == "tp_cruce:L1" and prog.en_s == 60.0
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
    assert len(prog) == 1 and prog[0].clave == CLAVE_CERRAR_TODO
    assert prog[0].datos["intento"] == 1 and prog[0].datos["tickers"] == ["BOT", "MANC", "MANL"]
    assert isinstance(acciones[0], Anotar) and acciones[0].tipo == "cerrar_todo"


def test_cerrar_todo_neta_das_manda_y_discrepancia_pide_posiciones():
    """M7: la neta de DAS incluye lo manual; si discrepa de los fills se pide GET POSITIONS y se anota."""
    acciones = cerrar_todo({"X": _pos("X", neta_fills=-100, neta_das=-150)}, _cot_de({"X": _cot("10", "10.1", ticker="X")}),
                           CFG, _tokens(), HORA)
    assert [a.orden.qty for a in acciones if isinstance(a, EnviarOrden)] == [150]
    assert any(isinstance(a, Consultar) and a.comando == "GET POSITIONS" for a in acciones)
    assert any(isinstance(a, Anotar) and a.tipo == "discrepancia" for a in acciones)


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
