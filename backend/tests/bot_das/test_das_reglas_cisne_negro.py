"""Tests de reglas/cisne_negro.py (documento §3.19, flujo F7 y fila de §10; R-G-01, R-G-03, R-D-06).

QUÉ DEMUESTRA. Que `se_activa` solo arranca el protocolo pasado el límite de
la emergencia con un corto vivo (y no con fills en vuelo ni si ya está
activo); la cadencia 60 s × 5 y luego 300 s con un reloj simulado de 40
minutos (y el silencio de `/parar_avisos`); que `informe` lleva los 16
campos de R-G-01 (2) con sus valores; que `acciones_durante_bs` NUNCA envía
ni cancela (solo baja la cantidad de la emergencia); `al_cerrar`;
`fogonazo_visto`; y que `cierre_humano` cancela la emergencia ANTES de
comprar, con techo del 5 % sobre el ask, sus reintentos y sus guardas.

POR QUÉ ESTÁ AQUÍ. Las reglas son puras: se prueban con tablas sin DAS, sin
red y con el reloj simulado del conftest. La config sale de
`fixtures/config_ejemplo.json` como dict (sin `config.py`, que es de otro
lote); `reglas.stops` y `reglas.salidas` están en disco y en verde.

LAS TRAMPAS. Nada de floats en precios. Los asertos del informe buscan cada
ETIQUETA y los números en formato español («1.540,00 $», «+122,2 %»).
"""
from __future__ import annotations

import copy
import itertools
import json
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pytest

from app.bot_das.reglas import cisne_negro
from app.bot_das.reglas.cisne_negro import (
    CLAVE_CIERRE_REINTENTO,
    ETIQUETAS_INFORME,
    FRASE_EXITO,
    TITULO_INFORME,
    acciones_durante_bs,
    activar,
    actualizar_maximo,
    al_cerrar,
    cierre_humano,
    clave_aviso_informe,
    fogonazo_visto,
    informe,
    registrar_informe,
    se_activa,
    segundos_hasta_informe,
    toca_informe,
)
from app.bot_das.reglas.stops import CLAVE_VERIFICAR_REPLACE, niveles
from app.bot_das.reloj import ET
from app.bot_das.tipos import (
    BS_CADENCIA_DESPUES_S,
    BS_CADENCIA_INICIAL_S,
    BS_PRIMEROS_INFORMES,
    Anotar,
    Avisar,
    Cancelar,
    Consultar,
    Cotizacion,
    Cuenta,
    EnviarOrden,
    EstadoBS,
    EstadoLote,
    EstadoOrden,
    EstadoSimbolo,
    EstadoTicker,
    Fill,
    Grupo,
    Lado,
    Lote,
    Nivel,
    Orden,
    Origen,
    PosicionTicker,
    Programar,
    Proposito,
    Reemplazar,
    TipoOrden,
)

D = Decimal
BACKEND = Path(__file__).resolve().parents[2]
MODULO = BACKEND / "app" / "bot_das" / "reglas" / "cisne_negro.py"
CONFIG_EJEMPLO = Path(__file__).parent / "fixtures" / "config_ejemplo.json"
CFG = json.loads(CONFIG_EJEMPLO.read_text(encoding="utf-8"))
HORA = datetime(2026, 9, 25, 9, 45, tzinfo=ET)
EOD = datetime(2026, 9, 25, 11, 30, tzinfo=ET)
T = "XYZ"
L = D("2.00")
NIV = niveles(L, CFG["stops"])          # principal 2,00 / 2,06 · emergencia 2,26 / 3,26 (R-C-01 v3)


# ── fábricas ─────────────────────────────────────────────────────────────
def _lote(llenas: int = 1000, lote_id: str = "L1", nivel: Decimal = L, medio: Decimal = D("1.80")) -> Lote:
    return Lote(id=lote_id, strategy_id="s1", estrategia="E1", ticker=T, direccion="Short", pedidas=llenas,
                llenas=llenas, precio_medio=medio, nivel_stop=nivel, estado=EstadoLote.ABIERTO)


def _pos(neta: int = -700, neta_das: Optional[int] = None, estado: EstadoTicker = EstadoTicker.NORMAL,
         bs: Optional[EstadoBS] = None, version: int = 4, lotes: Optional[dict] = None) -> PosicionTicker:
    return PosicionTicker(ticker=T, lotes={"L1": _lote()} if lotes is None else lotes, neta_fills=neta,
                          neta_das=neta_das, estado=estado, bs=bs, version_stops=version)


def _orden(token: int, proposito: Proposito, qty: int, *, tipo: TipoOrden = TipoOrden.STOP_LIMITE_PP,
           lado: Lado = Lado.COMPRA, precio: Optional[Decimal] = None, stop: Optional[Decimal] = None,
           id_das: Optional[int] = None, estado: EstadoOrden = EstadoOrden.ACCEPTED, llenas: int = 0, lvqty: int = 0,
           ticker: str = T, origen: Origen = Origen.EJECUTOR) -> Orden:
    return Orden(token=token, ticker=ticker, lado=lado, tipo=tipo, qty=qty, precio=precio, stop=stop, ruta="STOP",
                 proposito=proposito, lote_id=None, nivel=L, origen=origen, id_das=id_das, estado=estado,
                 llenas=llenas, lvqty=lvqty)


def _emergencia(qty: int = 1000, **kw) -> Orden:
    kw.setdefault("id_das", 5001)
    return _orden(100200010, Proposito.STOP_EMERGENCIA, qty, precio=NIV.emergencia_limite,
                  stop=NIV.emergencia_disparo, **kw)


def _principal(**kw) -> Orden:
    kw.setdefault("id_das", 5000)
    return _orden(100200009, Proposito.STOP_PRINCIPAL, 1000, precio=NIV.principal_limite, stop=NIV.principal_disparo,
                  **kw)


def _cierre(qty: int, precio: Decimal, **kw) -> Orden:
    return _orden(kw.pop("token", 100200050), Proposito.CIERRE_HUMANO, qty, tipo=TipoOrden.LIMITE, precio=precio,
                  **kw)


def _cot(bid="3.90", ask="4.10", last="4.00", actualizada_en: Optional[float] = 1000.0) -> Cotizacion:
    def d(x):
        return None if x is None else D(str(x))
    return Cotizacion(ticker=T, bid=d(bid), ask=d(ask), last=d(last), actualizada_en=actualizada_en)


def _fill(id_trade: int, lado: str, qty: int, precio: str, ticker: str = T) -> Fill:
    return Fill(id_trade=id_trade, token=None, id_orden=None, ticker=ticker, lado=lado, qty=qty, precio=D(precio),
                ruta="SAGEPRO", hora="09:40:00", liq=None, ecn_fee=None)


def _tokens():
    return itertools.count(100200100).__next__


FILLS = [_fill(1, "SS", 1000, "1.80"), _fill(2, "B", 300, "2.05")]   # corto 1.000 a 1,80; el principal cubrió 300 a 2,05


def _bs(activado: float = 1000.0, **kw) -> EstadoBS:
    base = dict(activado_en=activado, primer_stop=NIV.principal_disparo, emergencia_limite=NIV.emergencia_limite,
                max_visto=D("4.00"), ultimo_informe=activado)
    base.update(kw)
    return EstadoBS(**base)


def _tipos(acciones) -> list[str]:
    return [type(a).__name__ for a in acciones]


# ── se_activa (R-G-01, R-G-03 aclaración 24-sep) ─────────────────────────
@pytest.mark.parametrize("neta, last, ask, vivas, esperado", [
    pytest.param(-700, "3.25", "3.30", [], False, id="R-G-01-last-por-debajo-del-limite"),
    pytest.param(-700, "3.26", "3.30", [], False, id="R-G-01-last-igual-al-limite-no-lo-pasa"),
    pytest.param(-700, "3.27", "3.30", [], True, id="R-G-01-last-por-encima-con-corto"),
    pytest.param(0, "5.00", "5.10", [], False, id="R-G-03-plano-no-hay-protocolo"),
    pytest.param(300, "5.00", "5.10", [], False, id="R-G-03-largo-no-hay-protocolo"),
    pytest.param(-700, "5.00", "5.10", [_emergencia(700, estado=EstadoOrden.EXECUTED, llenas=700)], False,
                 id="R-G-03-emergencia-ejecutada-fills-en-vuelo"),
    pytest.param(-700, "5.00", "5.10", [_emergencia(1000, estado=EstadoOrden.PARTIAL, llenas=1000)], False,
                 id="riesgo8-emergencia-llena-antes-del-trade"),
    pytest.param(-700, "5.00", "5.10", [_emergencia(1000, estado=EstadoOrden.PARTIAL, llenas=200, lvqty=800)], True,
                 id="R-G-01-emergencia-a-medias-sigue-descubierto"),
    pytest.param(-700, "5.00", "5.10", [_emergencia(300, estado=EstadoOrden.EXECUTED, llenas=300)], True,
                 id="R-G-01-emergencia-vieja-llena-pero-queda-corto"),
    pytest.param(-700, "5.00", "5.10", [_emergencia(1000)], True, id="R-G-01-emergencia-viva-sin-llenar"),
    pytest.param(-700, None, "3.30", [], True, id="R-G-01-sin-last-manda-el-ask"),
    pytest.param(-700, None, None, [], False, id="R-G-01-sin-precio-no-activa"),
    pytest.param(-700, "5.00", "5.10",
                 [_emergencia(700, estado=EstadoOrden.EXECUTED, llenas=700, ticker="OTRO")], True,
                 id="R-G-01-emergencia-de-otro-ticker-no-cuenta"),
])
def test_se_activa(neta, last, ask, vivas, esperado):
    assert se_activa(_pos(neta=neta), NIV, vivas, _cot(last=last, ask=ask)) is esperado


def test_se_activa_emergencia_del_vigilante_sin_etiqueta_se_reconoce():
    """R-C-07 / corrección 3: una emergencia sin propósito (vigilante) llena del todo también son fills en vuelo."""
    o = _orden(200200001, Proposito.DESCONOCIDA, 700, precio=NIV.emergencia_limite, stop=NIV.emergencia_disparo,
               id_das=7001, estado=EstadoOrden.EXECUTED, llenas=700, origen=Origen.VIGILANTE)
    assert se_activa(_pos(), NIV, [o], _cot(last="5.00"), cfg_stops=CFG["stops"]) is False


@pytest.mark.parametrize("pos", [
    pytest.param(_pos(estado=EstadoTicker.BS), id="R-G-01-ya-en-protocolo-por-estado"),
    pytest.param(_pos(bs=_bs()), id="R-G-01-ya-en-protocolo-por-bs"),
])
def test_se_activa_no_rearranca_un_protocolo_activo(pos):
    assert se_activa(pos, NIV, [], _cot(last="5.00")) is False


def test_se_activa_sin_niveles_ni_cotizacion():
    assert se_activa(_pos(), None, [], _cot(last="5.00")) is False
    assert se_activa(_pos(), NIV, [], None) is False


# ── activar y máximo ─────────────────────────────────────────────────────
def test_activar_estado_inicial():
    pos = _pos()
    antes = copy.deepcopy(pos)
    bs = activar(pos, NIV, 1234.5, precio=D("4.40"))
    assert bs == EstadoBS(activado_en=1234.5, primer_stop=D("2.00"), emergencia_limite=D("3.26"), max_visto=D("4.40"),
                          informes=0, ultimo_informe=1234.5, silenciado=False, perdido_realizado=D("0"))
    assert pos == antes
    assert activar(pos, NIV, 1.0).max_visto == NIV.emergencia_limite          # sin precio: el límite ya pasado
    assert activar(pos, NIV, 1.0, precio=D("3.00")).max_visto == NIV.emergencia_limite


def test_actualizar_maximo_no_muta_y_solo_sube():
    bs = _bs(max_visto=D("4.00"))
    assert actualizar_maximo(bs, D("3.50")) is bs
    assert actualizar_maximo(bs, None) is bs
    nuevo = actualizar_maximo(bs, D("5.20"))
    assert nuevo.max_visto == D("5.20") and bs.max_visto == D("4.00")


# ── cadencia (R-G-01 v2: 60 s × 5, luego 300 s) ──────────────────────────
def _simular(reloj, cfg_tec, minutos: int = 40, silenciar_en: Optional[float] = None) -> list[float]:
    inicio = reloj.mono()
    bs = activar(_pos(), NIV, inicio)
    momentos = []
    for _ in range(minutos * 60):
        reloj.avanzar(1)
        ahora = reloj.mono()
        if silenciar_en is not None and ahora - inicio >= silenciar_en and not bs.silenciado:
            bs = EstadoBS(**{**bs.__dict__, "silenciado": True})
        if toca_informe(bs, ahora, cfg_tec):
            momentos.append(round(ahora - inicio, 6))
            bs = registrar_informe(bs, ahora)
    return momentos


ESPERADO_40_MIN = [60.0, 120.0, 180.0, 240.0, 300.0] + [300.0 + 300.0 * k for k in range(1, 8)]


@pytest.mark.parametrize("cfg_tec", [
    pytest.param(CFG["tecnicos"], id="R-G-01v2-bloque-tecnicos"),
    pytest.param(CFG["tecnicos"]["cisne_negro_informes"], id="R-G-01v2-subbloque"),
    pytest.param(CFG, id="R-G-01v2-config-entera-como-dict"),
    pytest.param({}, id="R-G-01v2-defaults-de-tipos"),
])
def test_cadencia_40_minutos_con_reloj_simulado(reloj, cfg_tec):
    assert _simular(reloj, cfg_tec) == ESPERADO_40_MIN
    assert (BS_PRIMEROS_INFORMES, BS_CADENCIA_INICIAL_S, BS_CADENCIA_DESPUES_S) == (5, 60, 300)


def test_cadencia_configurable(reloj):
    cfg_tec = {"cisne_negro_informes": {"primeros": 2, "cadencia_inicial_s": 30, "cadencia_despues_s": 120}}
    assert _simular(reloj, cfg_tec, minutos=10) == [30.0, 60.0, 180.0, 300.0, 420.0, 540.0]


def test_silenciado_no_manda_mas_informes(reloj):
    """R-G-01: /parar_avisos X BS deja de mandar SOLO el mensaje periódico de ese evento."""
    assert _simular(reloj, CFG["tecnicos"], silenciar_en=150.0) == [60.0, 120.0]


def test_toca_informe_sin_protocolo_y_holgura_de_float():
    assert toca_informe(None, 5000.0, CFG["tecnicos"]) is False
    bs = _bs(activado=0.1 + 0.2)          # 0.30000000000000004
    assert toca_informe(bs, 60.3, CFG["tecnicos"]) is True
    assert toca_informe(bs, 60.2, CFG["tecnicos"]) is False


def test_segundos_hasta_informe_para_reprogramar():
    bs = _bs(activado=1000.0)
    assert segundos_hasta_informe(bs, 1000.0, CFG["tecnicos"]) == 60.0
    assert segundos_hasta_informe(bs, 1045.0, CFG["tecnicos"]) == 15.0
    assert segundos_hasta_informe(bs, 2000.0, CFG["tecnicos"]) == 0.0
    tras5 = _bs(activado=1000.0, informes=5, ultimo_informe=1300.0)
    assert segundos_hasta_informe(tras5, 1300.0, CFG["tecnicos"]) == 300.0


def test_registrar_informe_no_muta():
    bs = _bs()
    nuevo = registrar_informe(bs, 1060.0)
    assert (nuevo.informes, nuevo.ultimo_informe) == (1, 1060.0)
    assert (bs.informes, bs.ultimo_informe) == (0, 1000.0)


def test_clave_de_cada_informe_es_distinta():
    """avisos.py deduplica por clave 60 s: un informe a los 60 s justos con la misma clave se perdería."""
    claves = [clave_aviso_informe(T, n) for n in range(0, 8)]
    assert claves[0] == "bs:XYZ" and len(set(claves)) == 8


# ── informe: los 16 campos de R-G-01 (2) ─────────────────────────────────
def _informe(**kw) -> str:
    base = dict(pos=_pos(), bs=_bs(max_visto=D("4.00")), stops=NIV, cot=_cot(), simb=EstadoSimbolo(
        ticker=T, ta=None, limit_up=D("4.80"), k_halts_up=2), cuenta=Cuenta(equity=D("50000")), ahora_et=HORA,
        eod=EOD, franja="RTH", fills=FILLS)
    extra = dict(ahora=1600.0, vivas=[_emergencia(1000), _principal(estado=EstadoOrden.PARTIAL, llenas=300,
                                                                     lvqty=700)],
                 historial=[(1100.0, D("3.50")), (1300.0, D("5.00")), (1500.0, D("4.20"))])
    for clave in list(kw):
        if clave in extra:
            extra[clave] = kw.pop(clave)
    base.update(kw)
    return informe(**base, **extra)


def _valor(texto: str, etiqueta: str) -> str:
    m = re.search(rf"<b>{re.escape(etiqueta)}:</b> (.*)", texto)
    assert m is not None, f"falta el campo {etiqueta!r}"
    return m.group(1)


def test_informe_contiene_los_16_campos_con_sus_valores():
    texto = _informe()
    assert len(ETIQUETAS_INFORME) == 16 and len(set(ETIQUETAS_INFORME)) == 16
    assert texto.splitlines()[0] == f"<b>{TITULO_INFORME} XYZ</b>"
    for etiqueta in ETIQUETAS_INFORME:
        assert f"<b>{etiqueta}:</b>" in texto
    assert len(texto.splitlines()) == 17
    assert _valor(texto, "Stop normal") == "2,00 (límite 2,06)"
    assert _valor(texto, "Stop de emergencia") == "2,26 (límite 3,26)"
    assert _valor(texto, "Precio") == "4,00 · bid 3,90 / ask 4,10"
    assert _valor(texto, "Minutos desde el evento") == "10,0 min"
    assert _valor(texto, "Al descubierto") == "700 acciones cortas"
    assert _valor(texto, "Pérdida latente del trade") == "+122,2 % (1.540,00 $) sobre el precio medio 1,80"
    assert _valor(texto, "Pérdida total sobre la cuenta").startswith("+3,2 % (1.615,00 $)")
    assert _valor(texto, "Máxima subida vs primer stop") == "+150,0 % (máximo 5,00)"
    assert _valor(texto, "Actual vs primer stop") == "+100,0 %"
    assert _valor(texto, "Pérdida ejecutada") == "75,00 $ · +13,9 % (300 acciones ya salieron)"
    assert _valor(texto, "Halts") == "parada: no · banda LULD 4,80 (a +20,0 %) · halts hoy k = 2"
    assert _valor(texto, "Minutos desde el máximo") == "5,0 min"
    assert _valor(texto, "Bajando") == "sí, desde hace 5,0 min (-20,0 % desde el máximo)"
    assert _valor(texto, "Minutos hasta EOD") == "105,0 min (EOD 11:30)"
    assert _valor(texto, "Orden de emergencia") == "viva (Accepted) · disparo 2,26 · límite 3,26 · 1.000 acciones"
    comandos = _valor(texto, "Comandos")
    for comando in ("/cerrar XYZ SI", "/cerrar XYZ N SI", "/estado XYZ", "/parar_avisos XYZ BS",
                    "/reanudar_avisos XYZ BS"):
        assert comando in comandos


def test_informe_halts_solo_en_sesion_de_mercado_y_parada():
    pm = _informe(franja="premercado")
    assert _valor(pm, "Halts").startswith("fuera de sesión de mercado (premercado)")
    parada = _informe(simb=EstadoSimbolo(ticker=T, ta="H", limit_up=None, k_halts_up=1))
    assert _valor(parada, "Halts") == "parada: sí · banda LULD s/d · halts hoy k = 1"


def test_informe_emergencia_cancelada_y_duplicada():
    sin = _informe(vivas=[])
    assert _valor(sin, "Orden de emergencia").startswith("NO está viva")
    dos = _informe(vivas=[_emergencia(1000), _emergencia(700, id_das=5009)])
    assert "¡2 emergencias vivas!" in _valor(dos, "Orden de emergencia")


def test_informe_nunca_lanza_con_datos_ausentes():
    texto = informe(_pos(lotes={}), _bs(), NIV, None, None, None, HORA, None, "RTH", [])
    for etiqueta in ETIQUETAS_INFORME:
        assert f"<b>{etiqueta}:</b>" in texto
    assert _valor(texto, "Precio") == "s/d · bid s/d / ask s/d"
    assert _valor(texto, "Minutos desde el evento") == "s/d"
    assert _valor(texto, "Pérdida total sobre la cuenta").startswith("s/d")
    assert _valor(texto, "Minutos hasta EOD") == "s/d"
    assert _valor(texto, "Orden de emergencia") == "s/d"


def test_informe_fallbacks_precio_medio_de_lotes_y_eod_pasado():
    """Sin fills el precio medio sale de los lotes; sin `ahora` se usa la hora de la cotización."""
    texto = informe(_pos(), _bs(), NIV, _cot(actualizada_en=1120.0), None, Cuenta(equity=None), HORA,
                    datetime(2026, 9, 25, 9, 30, tzinfo=ET), "RTH", [])
    assert _valor(texto, "Pérdida latente del trade").endswith("sobre el precio medio 1,80")
    assert _valor(texto, "Minutos desde el evento") == "2,0 min"
    assert _valor(texto, "Minutos hasta EOD") == "EOD pasado hace 15,0 min"
    assert _valor(texto, "Pérdida total sobre la cuenta").startswith("s/d (1.540,00 $)")


def test_informe_escapa_el_html():
    pos = PosicionTicker(ticker="A<B", neta_fills=-100)
    texto = informe(pos, _bs(), NIV, _cot(), None, None, HORA, None, "RTH", [])
    assert "A&lt;B" in texto and "A<B" not in texto and "&amp;lt;" not in texto


def test_informe_contabilidad_reinicia_en_cada_trade():
    """Un trade anterior del día (cerrado con ganancia) no cuenta en la pérdida ejecutada del actual."""
    fills = [_fill(1, "SS", 500, "3.00"), _fill(2, "B", 500, "2.50"), _fill(3, "SS", 1000, "1.80"),
             _fill(4, "B", 300, "2.05"), _fill(5, "B", 999, "9.99", ticker="OTRO")]
    texto = _informe(fills=fills)
    assert _valor(texto, "Pérdida ejecutada") == "75,00 $ · +13,9 % (300 acciones ya salieron)"


# ── acciones_durante_bs (R-G-03 (1)): solo bajar la cantidad ─────────────
CASOS_DURANTE_BS = [
    pytest.param(_pos(neta=-700, estado=EstadoTicker.BS), [_emergencia(1000)], "reduce", id="R-G-03-baja-a-700"),
    pytest.param(_pos(neta=-700, estado=EstadoTicker.BS), [_emergencia(700)], "nada", id="R-G-03-ya-ajustada"),
    pytest.param(_pos(neta=-700, estado=EstadoTicker.BS), [_emergencia(500)], "nada", id="R-G-03-nunca-sube"),
    pytest.param(_pos(neta=-700, estado=EstadoTicker.BS), [], "nada", id="R-G-03-2-no-repone-si-das-la-cancela"),
    pytest.param(_pos(neta=-700, estado=EstadoTicker.BS), [_emergencia(1000, estado=EstadoOrden.CANCELED)], "nada",
                 id="R-G-03-2-cancelada-no-se-toca"),
    pytest.param(_pos(neta=-700, estado=EstadoTicker.BS), [_emergencia(1000, id_das=None)], "nada",
                 id="R-G-03-sin-id-das-no-se-puede-reemplazar"),
    pytest.param(_pos(neta=0, estado=EstadoTicker.BS), [_emergencia(1000)], "nada", id="R-G-03-sin-corto-nada"),
    pytest.param(_pos(neta=-700, neta_das=-1000, estado=EstadoTicker.BS), [_emergencia(1000)], "consultar",
                 id="riesgo8-discrepancia-solo-get-positions"),
    pytest.param(_pos(neta=-700, estado=EstadoTicker.BS), [_emergencia(1000), _principal()], "reduce",
                 id="R-G-03-el-principal-no-se-toca"),
]


@pytest.mark.parametrize("pos, vivas, esperado", CASOS_DURANTE_BS)
def test_acciones_durante_bs_nunca_envia_ni_cancela(pos, vivas, esperado):
    antes = (copy.deepcopy(pos), copy.deepcopy(vivas))
    acciones = acciones_durante_bs(pos, vivas, CFG, version=7)
    assert not any(isinstance(a, (EnviarOrden, Cancelar)) for a in acciones)
    assert (pos, vivas) == antes
    if esperado == "nada":
        assert acciones == []
    elif esperado == "consultar":
        assert acciones == [Consultar("GET POSITIONS")]
    else:
        r, p = acciones
        assert isinstance(r, Reemplazar) and isinstance(p, Programar)
        assert (r.id_das, r.token, r.qty, r.stop, r.precio) == (5001, 100200010, 700, D("2.26"), D("3.26"))
        assert (r.version, r.serie) == (7, "stops:XYZ")
        assert p.clave == CLAVE_VERIFICAR_REPLACE and p.datos["qty_objetivo"] == 700


def test_acciones_durante_bs_descuenta_el_cierre_humano_en_curso():
    """Con /cerrar X 300 SI comprando, la emergencia cubre lo que va a quedar (400), no las 700."""
    vivas = [_emergencia(1000), _cierre(300, D("4.31"), id_das=6001)]
    r = acciones_durante_bs(_pos(neta=-700, estado=EstadoTicker.BS), vivas, CFG, version=7)[0]
    assert isinstance(r, Reemplazar) and r.qty == 400
    todo = [_emergencia(1000), _cierre(700, D("4.31"), id_das=6001)]
    assert acciones_durante_bs(_pos(neta=-700, estado=EstadoTicker.BS), todo, CFG, version=7) == []


def test_acciones_durante_bs_ajusta_la_mas_antigua_y_la_del_vigilante():
    vieja = _emergencia(1000, id_das=5001)
    nueva = _emergencia(1000, id_das=5002)
    acciones = acciones_durante_bs(_pos(neta=-700, estado=EstadoTicker.BS), [nueva, vieja], CFG, version=1)
    assert acciones[0].id_das == 5001
    del_vigilante = _orden(200200001, Proposito.DESCONOCIDA, 1000, precio=NIV.emergencia_limite,
                           stop=NIV.emergencia_disparo, id_das=7001, origen=Origen.VIGILANTE)
    acciones = acciones_durante_bs(_pos(neta=-700, estado=EstadoTicker.BS), [del_vigilante], CFG, version=1)
    assert isinstance(acciones[0], Reemplazar) and acciones[0].id_das == 7001


# ── al_cerrar (R-G-01 (3), R-G-03 reentrada) ─────────────────────────────
@pytest.mark.parametrize("pos, dentro, hay_aviso, veto", [
    pytest.param(_pos(neta=0), True, False, False, id="R-G-03-sin-protocolo-el-ticker-sigue-operable"),
    pytest.param(_pos(neta=-200, estado=EstadoTicker.BS, bs=_bs()), True, False, True, id="R-G-03-sigue-corto"),
    pytest.param(_pos(neta=0, estado=EstadoTicker.BS, bs=_bs()), True, True, True, id="R-G-01-3-sacada-con-exito"),
    pytest.param(_pos(neta=0, estado=EstadoTicker.BS, bs=_bs()), False, False, True, id="R-G-03-cerro-el-humano"),
    pytest.param(_pos(neta=0, bs=_bs()), True, True, True, id="R-G-01-3-protocolo-por-bs"),
])
def test_al_cerrar(pos, dentro, hay_aviso, veto):
    aviso, sin_reentrada = al_cerrar(pos, dentro)
    assert sin_reentrada is veto
    assert (aviso is not None) is hay_aviso
    if aviso is not None:
        assert (aviso.nivel, aviso.grupo, aviso.clave) == (Nivel.MAXIMO, Grupo.B, "bs_fin:XYZ")
        assert FRASE_EXITO in aviso.texto and "/sigue XYZ" in aviso.texto


def test_al_cerrar_manda_el_mismo_informe_con_la_frase():
    aviso, _ = al_cerrar(_pos(neta=0, estado=EstadoTicker.BS), True, texto_informe="<b>Posible BS XYZ</b>")
    assert aviso.texto.index(FRASE_EXITO) < aviso.texto.index("Posible BS XYZ")


# ── fogonazo_visto (R-G-01 (4)) ──────────────────────────────────────────
def test_fogonazo_visto_mide_maximo_duracion_y_devolucion():
    hist = [(0.0, "2.00"), (1.0, "2.10"), (2.0, "5.00"), (3.0, "8.00"), (5.0, "6.00"), (9.0, "3.50"), (12.0, "2.60")]
    r = fogonazo_visto([(t, D(p)) for t, p in hist], D("100"))
    assert (r["base"], r["maximo"], r["subida_pct"]) == (D("2.00"), D("8.00"), D("300"))
    assert (r["t_inicio"], r["t_maximo"], r["t_fin"], r["duracion_s"]) == (2.0, 3.0, 9.0, 7.0)
    assert r["devolucion_pct"] == D("90") and r["sigue_arriba"] is False and r["puntos"] == 7


def test_fogonazo_que_sigue_arriba_y_entrada_desordenada():
    hist = [(3.0, D("9.00")), (0.0, D("3.00")), (1.0, D("7.00")), (2.0, D("8.00"))]
    r = fogonazo_visto(hist, 100)
    assert r["base"] == D("3.00") and r["maximo"] == D("9.00") and r["t_fin"] is None
    assert r["sigue_arriba"] is True and r["duracion_s"] == 2.0 and r["devolucion_pct"] == D("0")


@pytest.mark.parametrize("hist, umbral", [
    pytest.param([(0.0, D("2.00")), (1.0, D("3.90"))], 100, id="R-G-01-4-por-debajo-del-umbral"),
    pytest.param([(0.0, D("2.00"))], 10, id="R-G-01-4-un-solo-punto"),
    pytest.param([], 10, id="R-G-01-4-vacio"),
    pytest.param([(0.0, None), (1.0, D("0")), (2.0, D("-1")), (3.0, "x"), ("mal", D("9"))], 10,
                 id="R-G-01-4-precios-no-validos"),
    pytest.param([(0.0, D("2.00")), (1.0, D("2.00"))], 0, id="R-G-01-4-sin-subida"),
])
def test_fogonazo_no_visto(hist, umbral):
    assert fogonazo_visto(hist, umbral) is None


def test_fogonazo_umbral_negativo_lanza():
    with pytest.raises(ValueError):
        fogonazo_visto([(0.0, D("1")), (1.0, D("3"))], -5)


# ── cierre_humano (R-G-03 (3) + R-D-06) ──────────────────────────────────
def _cierre_humano(pos=None, vivas=None, cot=None, n=None, **kw):
    return cierre_humano(pos if pos is not None else _pos(neta=-700, estado=EstadoTicker.BS),
                         [_emergencia(1000), _principal(estado=EstadoOrden.PARTIAL, llenas=300, lvqty=700)]
                         if vivas is None else vivas,
                         cot if cot is not None else _cot(), n, CFG, kw.pop("tokens", _tokens()), HORA, **kw)


def test_cierre_humano_cancela_la_emergencia_antes_de_comprar():
    acciones = _cierre_humano()
    assert _tipos(acciones) == ["Anotar", "Cancelar", "Cancelar", "EnviarOrden", "Programar"]
    assert acciones[1].id_das == 5001                     # la emergencia, PRIMERO (R-G-03 (3))
    assert acciones[2].id_das == 5000                     # luego el principal, para que no compre de más
    orden = acciones[3].orden
    assert (orden.lado, orden.qty, orden.tipo, orden.precio) == (Lado.COMPRA, 700, TipoOrden.LIMITE, D("4.31"))
    assert (orden.ruta, orden.proposito, orden.post_only) == ("SAGEPRO", Proposito.CIERRE_HUMANO, False)
    p = acciones[4]
    assert p.clave == f"{CLAVE_CIERRE_REINTENTO}:XYZ" and p.en_s == 2.0
    assert p.datos == {"ticker": T, "intento": 1, "objetivo": 0, "signo": -1, "n": None}


def test_cierre_humano_por_tramos_no_deja_el_resto_desnudo():
    """/cerrar X 300 SI: la emergencia NO se cancela; se baja a las 400 que quedan (G6, R-G-03 (1))."""
    acciones = _cierre_humano(n=300)
    assert not any(isinstance(a, Cancelar) for a in acciones)
    reemplazos = [a for a in acciones if isinstance(a, Reemplazar)]
    assert [(r.id_das, r.qty, r.stop, r.precio, r.version, r.serie) for r in reemplazos] == [
        (5001, 400, D("2.26"), D("3.26"), 4, "stops:XYZ"),
        (5000, 400, D("2.00"), D("2.06"), 4, "stops:XYZ"),
    ]
    envio = [a for a in acciones if isinstance(a, EnviarOrden)]
    assert len(envio) == 1 and envio[0].orden.qty == 300
    assert acciones.index(reemplazos[0]) < acciones.index(envio[0])
    assert acciones[-1].datos["objetivo"] == -400


def test_cierre_humano_n_mayor_que_la_posicion_cierra_todo():
    acciones = _cierre_humano(n=5000)
    assert [a.orden.qty for a in acciones if isinstance(a, EnviarOrden)] == [700]
    assert acciones[-1].datos["objetivo"] == 0


def test_cierre_humano_sin_cotizacion_no_toca_nada():
    """Cancelar la emergencia sin poder comprar dejaría la posición desnuda."""
    acciones = _cierre_humano(cot=_cot(ask=None, bid=None, last=None))
    assert not any(isinstance(a, (Cancelar, Reemplazar, EnviarOrden)) for a in acciones)
    aviso = next(a for a in acciones if isinstance(a, Avisar))
    assert aviso.nivel is Nivel.MAXIMO and "A MANO" in aviso.texto
    assert isinstance(acciones[-1], Programar) and acciones[-1].datos["intento"] == 1


def test_cierre_humano_reintento_reemplaza_el_precio_sin_orden_nueva():
    """R-D-06: en el reintento el cierre vivo sube al ask·1,05 del momento; nunca cancelar + nueva (riesgo 5)."""
    vivas = [_cierre(700, D("4.31"), id_das=6001)]
    acciones = _cierre_humano(vivas=vivas, cot=_cot(ask="4.60"), intento=1, objetivo=0, signo=-1)
    assert _tipos(acciones) == ["Anotar", "Reemplazar", "Programar"]
    r = acciones[1]
    assert (r.id_das, r.qty, r.precio, r.stop) == (6001, 700, D("4.83"), None)
    assert acciones[-1].datos["intento"] == 2


def test_cierre_humano_reintento_tras_llenado_parcial():
    """Llenó 400 de 700: la orden viva conserva sus 300 al precio nuevo y no se envía nada más."""
    vivas = [_cierre(700, D("4.31"), id_das=6001, estado=EstadoOrden.PARTIAL, llenas=400, lvqty=300)]
    acciones = _cierre_humano(pos=_pos(neta=-300, estado=EstadoTicker.BS), vivas=vivas, cot=_cot(ask="4.60"),
                              intento=1, objetivo=0, signo=-1)
    assert [(a.qty, a.precio) for a in acciones if isinstance(a, Reemplazar)] == [(300, D("4.83"))]
    assert not any(isinstance(a, EnviarOrden) for a in acciones)


def test_cierre_humano_reintento_con_la_orden_anterior_cancelada_envia_lo_que_falta():
    acciones = _cierre_humano(pos=_pos(neta=-300, estado=EstadoTicker.BS), vivas=[], intento=2, objetivo=0, signo=-1)
    assert [a.orden.qty for a in acciones if isinstance(a, EnviarOrden)] == [300]
    assert acciones[-1].datos["intento"] == 3


def test_cierre_humano_reintentos_agotados_solo_avisa():
    acciones = _cierre_humano(pos=_pos(neta=-300, estado=EstadoTicker.BS), vivas=[], intento=3, objetivo=0, signo=-1)
    assert not any(isinstance(a, (Cancelar, Reemplazar, EnviarOrden, Programar)) for a in acciones)
    aviso = acciones[-1]
    assert isinstance(aviso, Avisar) and aviso.nivel is Nivel.MAXIMO and "AGOTADO" in aviso.texto
    assert "300 acciones" in aviso.texto and "4,10" in aviso.texto


def test_cierre_humano_objetivo_alcanzado_cancela_el_cierre_sobrante():
    vivas = [_cierre(200, D("4.31"), id_das=6001)]
    acciones = _cierre_humano(pos=_pos(neta=0, estado=EstadoTicker.BS), vivas=vivas, intento=1, objetivo=0, signo=-1)
    assert _tipos(acciones) == ["Anotar", "Cancelar", "Anotar"]
    assert acciones[1].id_das == 6001 and acciones[2].tipo == "cierre_humano_fin"


def test_cierre_humano_reintento_nunca_cierra_en_sentido_contrario():
    """Si un fill cruzado dejó la cuenta LARGA, venderla es R-C-11 (VENTA_EXCESO), no el reintento del cierre."""
    acciones = _cierre_humano(pos=_pos(neta=150, estado=EstadoTicker.BS), vivas=[], intento=1, objetivo=0, signo=-1)
    assert not any(isinstance(a, (EnviarOrden, Reemplazar, Programar)) for a in acciones)


def test_cierre_humano_sin_posicion_avisa_y_no_envia():
    acciones = _cierre_humano(pos=_pos(neta=0, estado=EstadoTicker.BS), vivas=[_emergencia(1000)])
    assert not any(isinstance(a, (EnviarOrden, Cancelar)) for a in acciones)
    assert any(isinstance(a, Avisar) and a.nivel is Nivel.INFO for a in acciones)


@pytest.mark.parametrize("neta_das, qty, bloqueado", [
    pytest.param(-1000, 700, False, id="riesgo8-das-mayor-se-cierra-la-menor"),
    pytest.param(-500, 500, False, id="riesgo8-das-menor-se-cierra-la-menor"),
    pytest.param(0, None, True, id="riesgo8-das-plana-no-se-envia-nada"),
    pytest.param(400, None, True, id="riesgo8-das-otro-signo-no-se-envia-nada"),
])
def test_cierre_humano_con_discrepancia(neta_das, qty, bloqueado):
    acciones = _cierre_humano(pos=_pos(neta=-700, neta_das=neta_das, estado=EstadoTicker.BS))
    assert Consultar("GET POSITIONS") in acciones
    assert any(isinstance(a, Anotar) and a.tipo == "discrepancia" for a in acciones)
    envios = [a.orden.qty for a in acciones if isinstance(a, EnviarOrden)]
    if bloqueado:
        assert envios == [] and not any(isinstance(a, Cancelar) for a in acciones)
        assert any(isinstance(a, Avisar) and a.nivel is Nivel.MAXIMO for a in acciones)
        assert isinstance(acciones[-1], Programar)
    else:
        assert envios == [qty]


@pytest.mark.parametrize("n", [0, -3, True, 2.5, "300"])
def test_cierre_humano_n_invalido_lanza(n):
    with pytest.raises(ValueError):
        _cierre_humano(n=n)


@pytest.mark.parametrize("kw", [
    pytest.param({"intento": -1}, id="R-D-06-intento-negativo"),
    pytest.param({"intento": 1, "objetivo": "0", "signo": -1}, id="R-D-06-objetivo-no-entero"),
    pytest.param({"intento": 1, "objetivo": 0, "signo": 5}, id="R-D-06-signo-imposible"),
])
def test_cierre_humano_datos_de_reintento_invalidos_lanzan(kw):
    with pytest.raises(ValueError):
        _cierre_humano(**kw)


def test_informe_en_maximos():
    texto = _informe(cot=_cot(last="5.50", ask="5.60", bid="5.40"))
    assert _valor(texto, "Minutos desde el máximo") == "0,0 min (en máximos)"
    assert _valor(texto, "Bajando") == "no: en máximos"
    assert _valor(texto, "Máxima subida vs primer stop") == "+175,0 % (máximo 5,50)"


def test_cierre_humano_no_consume_token_si_no_envia():
    contador = itertools.count(100200100)
    _cierre_humano(cot=_cot(ask=None, bid=None, last=None), tokens=contador.__next__)
    assert next(contador) == 100200100


def test_cierre_humano_techo_y_reintentos_de_la_config():
    cfg = copy.deepcopy(CFG)
    cfg["salidas"]["cerrar_todo"] = {"techo_pct": 10.0, "reintentos": 0, "espera_s": 3}
    acciones = cierre_humano(_pos(neta=-700, estado=EstadoTicker.BS), [], _cot(), None, cfg, _tokens(), HORA)
    assert next(a for a in acciones if isinstance(a, EnviarOrden)).orden.precio == D("4.51")
    assert acciones[-1].en_s == 3.0
    agotado = cierre_humano(_pos(neta=-700, estado=EstadoTicker.BS), [], _cot(), None, cfg, _tokens(), HORA,
                            intento=1, objetivo=0, signo=-1)
    assert isinstance(agotado[-1], Avisar) and "AGOTADO" in agotado[-1].texto


# ── pureza del módulo ────────────────────────────────────────────────────
def test_ninguna_funcion_muta_sus_entradas():
    pos = _pos(neta=-700, estado=EstadoTicker.BS, bs=_bs())
    vivas = [_emergencia(1000), _principal(), _cierre(100, D("4.31"), id_das=6001)]
    cot, fills = _cot(), list(FILLS)
    antes = copy.deepcopy((pos, vivas, cot, fills, CFG))
    se_activa(pos, NIV, vivas, cot)
    activar(pos, NIV, 1.0, precio=D("5"))
    informe(pos, pos.bs, NIV, cot, None, Cuenta(equity=D("1000")), HORA, EOD, "RTH", fills, vivas=vivas)
    acciones_durante_bs(pos, vivas, CFG, 1)
    al_cerrar(pos, True)
    cierre_humano(pos, vivas, cot, 200, CFG, _tokens(), HORA)
    cierre_humano(pos, vivas, cot, None, CFG, _tokens(), HORA)
    assert (pos, vivas, cot, fills, CFG) == antes


def test_modulo_puro_sin_io_ni_reloj():
    """§3 reglas/*: sin I/O, sin time, sin datetime.now(), sin logging, sin variables de entorno."""
    fuente = MODULO.read_text(encoding="utf-8")
    for prohibido in (r"^import time", r"^import logging", r"datetime\.now\(", r"os\.environ", r"^import os",
                      r"open\(", r"httpx", r"socket"):
        assert re.search(prohibido, fuente, re.MULTILINE) is None, prohibido
    assert cisne_negro.__doc__ and "LAS TRAMPAS" in cisne_negro.__doc__
