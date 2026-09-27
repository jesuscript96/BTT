"""reglas/halts.py: k, banda, decisión de reapertura (R-F-01/05/06), OPEN un minuto antes con guardia (injerto A §8.23), B18 y R-G-02."""
from __future__ import annotations

import ast
import itertools
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pytest

from app.bot_das.reglas import halts
from app.bot_das.reglas.halts import (
    DECISIONES, al_entrar_en_halt, cerca_de_banda, debe_enviar_open, decidir_reapertura, es_halt, es_luld, fin_previsto,
    momento_envio_open, orden_reapertura, primera_vela_pct, puede_reentrar_tras_halt, senal_guardada_valida, tipo_halt,
)
from app.bot_das.reloj import ET
from app.bot_das.tipos import (
    HALT_ENVIAR_ANTES_FIN_S, Anotar, Avisar, Cancelar, Config, Cotizacion, EstadoLote, EstadoOrden, EstadoSimbolo, Fase,
    Grupo, Lado, Lote, Nivel, NivelesStop, Orden, OrdenNueva, Origen, PosicionTicker, Programar, Proposito, Reemplazar,
    Senal, TipoOrden,
)

D = Decimal
X = "XYZ"
RUTA_CONFIG = Path(__file__).parent / "fixtures" / "config_ejemplo.json"
DIA = datetime(2026, 9, 25, tzinfo=ET).date()
HORA_RTH = datetime(2026, 9, 25, 10, 16, 0, tzinfo=ET)
HORA_PM = datetime(2026, 9, 25, 6, 30, 0, tzinfo=ET)


# ── fixtures y constructores ────────────────────────────────────────────
@pytest.fixture(scope="module")
def cfg_json() -> dict:
    return json.loads(RUTA_CONFIG.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def cfg_halts(cfg_json) -> dict:
    """El bloque `halts` tal cual sale del JSON (floats e ints): el módulo lo convierte con de_float."""
    return cfg_json["halts"]


@pytest.fixture(scope="module")
def config(cfg_json) -> Config:
    """`Config` real de tipos desde el fichero de ejemplo (sin depender de config.py, otro lote)."""
    claves = ("schema_version", "config_version", "sha256", "motor_hash", "estrategias_hash", "generado_at", "vigilando",
              "horario", "modo_seguridad", "lista_negra", "pausar_entradas", "locates", "entrada", "salidas", "stops",
              "halts", "exclusiones", "rutas", "tecnicos", "alertas_grupo_a")
    return Config(fase=Fase(cfg_json["fase"]), estrategias={}, cuenta_das="CUENTA_PRUEBA",
                  **{clave: cfg_json[clave] for clave in claves})


def posicion(neta: int, niveles_lotes: tuple = (D("11"),), ticker: str = X) -> PosicionTicker:
    pos = PosicionTicker(ticker=ticker, neta_fills=neta)
    restante = abs(neta)
    for i, nivel in enumerate(niveles_lotes):
        llenas = restante if i == len(niveles_lotes) - 1 else restante // 2
        restante -= llenas
        lid = f"{ticker}|s{i}|2026-09-25T10:00:00|entrada"
        pos.lotes[lid] = Lote(id=lid, strategy_id=f"s{i}", estrategia=f"E{i}", ticker=ticker,
                              direccion="Short" if neta < 0 else "Long", pedidas=llenas, llenas=llenas,
                              precio_medio=D("10"), nivel_stop=nivel, estado=EstadoLote.ABIERTO)
    return pos


def simbolo(ta: Optional[str] = "P", tat: Optional[str] = "10:15:30", k: int = 1, parada: Optional[Decimal] = D("10"),
            limit_up: Optional[Decimal] = D("10.50"), limit_down: Optional[Decimal] = D("9.50"),
            enviada: bool = False, desde: Optional[datetime] = None) -> EstadoSimbolo:
    return EstadoSimbolo(ticker=X, ta=ta, tat=tat, k_halts_up=k, precio_parada=parada, limit_up=limit_up,
                         limit_down=limit_down, orden_open_enviada=enviada, halt_desde=desde)


def cot(last=None, bid=None, ask=None) -> Cotizacion:
    conv = (lambda v: None if v is None else D(str(v)))
    return Cotizacion(ticker=X, bid=conv(bid), ask=conv(ask), last=conv(last), actualizada_en=1000.0)


def niveles(principal: str) -> NivelesStop:
    p = D(principal)
    return NivelesStop(principal_disparo=p, principal_limite=p * D("1.03"), emergencia_disparo=p * D("1.13"),
                       emergencia_limite=p * D("1.63"), bajo_banda=False)


def orden_viva(token: int, proposito: Proposito, id_das: Optional[int] = 500, estado: EstadoOrden = EstadoOrden.ACCEPTED,
               ticker: str = X, lado: Lado = Lado.CORTO) -> Orden:
    return Orden(token=token, ticker=ticker, lado=lado, tipo=TipoOrden.LIMITE, qty=100, precio=D("10"), stop=None,
                 ruta="SAGEREB", proposito=proposito, lote_id=None, nivel=None, origen=Origen.EJECUTOR,
                 id_das=id_das, estado=estado)


# ── es_halt / es_luld / tipo_halt / fin_previsto ─────────────────────────
@pytest.mark.parametrize("ta, esperado_halt, esperado_luld", [
    ("H", True, False), ("P", True, True), ("h", True, False), (" P ", True, True),
    ("T", False, False), ("Q", True, False), (" q ", True, False), (None, False, False), ("", False, False),
], ids=["L1113-H", "L1128-P", "H-minuscula", "P-espacios", "T-reabre", "E1-05-Q-sigue-parado", "E1-05-q-normalizado",
        "sin-TA-normal", "TA-vacio"])
def test_es_halt_y_es_luld(ta, esperado_halt, esperado_luld):
    s = simbolo(ta=ta)
    assert es_halt(s) is esperado_halt
    assert es_luld(s) is esperado_luld


@pytest.mark.parametrize("ta, franja, contiene", [
    ("P", "RTH", "LULD"), ("H", "RTH", "T1/T12"), ("H", "premercado", "premercado"), (None, "RTH", "desconocido"),
    ("Q", "RTH", "cotización"),
], ids=["R-G-02-luld", "R-G-02-h-rth", "R-G-02-h-pm", "R-G-02-sin-ta", "E1-05-Q"])
def test_tipo_halt(ta, franja, contiene):
    assert contiene in tipo_halt(simbolo(ta=ta), franja)


@pytest.mark.parametrize("ta, tat, ahora, esperado", [
    ("P", "10:15:30", HORA_RTH, datetime(2026, 9, 25, 10, 20, 30, tzinfo=ET)),
    ("P", "10:15:30", HORA_RTH.replace(tzinfo=None), datetime(2026, 9, 25, 10, 20, 30, tzinfo=ET)),
    ("P", "10:15:30", HORA_RTH.astimezone(timezone.utc), datetime(2026, 9, 25, 10, 20, 30, tzinfo=ET)),
    ("H", "10:15:30", HORA_RTH, None),
    ("P", None, HORA_RTH, None),
    ("P", "10:15", HORA_RTH, None),
    ("P", "25:00:00", HORA_RTH, None),
], ids=["L1128-P-TAT+5min", "P-ahora-naive-es-ET", "P-ahora-UTC", "H-sin-hora", "P-sin-TAT", "TAT-mal-formado",
        "TAT-fuera-de-rango"])
def test_fin_previsto(ta, tat, ahora, esperado):
    fin = fin_previsto(simbolo(ta=ta, tat=tat), ahora)
    assert fin == esperado
    if fin is not None:
        assert fin.tzinfo is not None


# ── momento_envio_open (injerto A §8.23, riesgo 27) ──────────────────────
@pytest.mark.parametrize("fin, ahora, antes_s, esperado", [
    (datetime(2026, 9, 25, 10, 20, 30, tzinfo=ET), HORA_RTH, HALT_ENVIAR_ANTES_FIN_S, 210.0),
    (None, HORA_RTH, HALT_ENVIAR_ANTES_FIN_S, 0.0),
    (HORA_RTH - timedelta(seconds=5), HORA_RTH, HALT_ENVIAR_ANTES_FIN_S, 0.0),
    (HORA_RTH + timedelta(seconds=59), HORA_RTH, HALT_ENVIAR_ANTES_FIN_S, 0.0),
    (HORA_RTH + timedelta(seconds=60), HORA_RTH, HALT_ENVIAR_ANTES_FIN_S, 0.0),
    (HORA_RTH + timedelta(seconds=61), HORA_RTH, HALT_ENVIAR_ANTES_FIN_S, 1.0),
    (HORA_RTH + timedelta(minutes=5), HORA_RTH, 90, 210.0),
    (HORA_RTH + timedelta(minutes=5), HORA_RTH.replace(tzinfo=None), HALT_ENVIAR_ANTES_FIN_S, 240.0),
], ids=["R-F-01-P-con-TAT-fin-menos-60s", "R-F-01-H-sin-hora-ahora", "riesgo27-fin-pasado-ahora",
        "R-F-01-menos-de-1-min-ahora", "R-F-01-justo-1-min-ahora", "R-F-01-61s-espera-1s", "antes_s-de-la-config",
        "ahora-naive-es-ET"])
def test_momento_envio_open(fin, ahora, antes_s, esperado):
    assert momento_envio_open(fin, ahora, antes_s) == pytest.approx(esperado)


def test_momento_envio_open_encadenado_con_fin_previsto():
    """F6.1: `Programar("halt_decidir", momento_envio_open(fin_previsto(simb, ahora), ahora))` con P y TAT."""
    s = simbolo(ta="P", tat="10:15:30")
    assert momento_envio_open(fin_previsto(s, HORA_RTH), HORA_RTH) == pytest.approx(210.0)
    assert momento_envio_open(fin_previsto(simbolo(ta="H", tat=None), HORA_RTH), HORA_RTH) == 0.0


# ── debe_enviar_open: una sola MKT por halt ─────────────────────────────
@pytest.mark.parametrize("ta, enviada, esperado", [
    ("P", False, True), ("H", False, True), ("P", True, False), ("H", True, False), ("T", False, False), (None, False, False),
], ids=["§8.23-P-primera", "§8.23-H-primera", "§8.23-P-ya-enviada", "§8.23-H-ya-enviada", "reabierto-T-no-MKT",
        "sin-halt-no-MKT"])
def test_debe_enviar_open(ta, enviada, esperado):
    assert debe_enviar_open(simbolo(ta=ta, enviada=enviada)) is esperado


def test_issuestatus_repetido_no_manda_segunda_mkt(config):
    """Riesgo 27: tres `$IssueStatus TA:H` seguidos reprograman `halt_decidir` pero sale UNA sola MKT por OPEN."""
    pos = posicion(-300, (D("9"),))
    s = simbolo(ta="H", tat=None, k=1, parada=D("10"))
    enviadas: list[OrdenNueva] = []
    for token in (101, 102, 103):                      # cada $IssueStatus repetido → halt_decidir otra vez
        decision = decidir_reapertura(pos, s, niveles("9"), cot(last="10"), config.halts, "RTH", 3)
        assert decision == "cerrar_mercado"
        if debe_enviar_open(s):
            enviadas.append(orden_reapertura(pos, 300, cot(last="10"), decision, config, token, HORA_RTH))
            s.orden_open_enviada = True                # lo hace el decisor al enviar
    assert len(enviadas) == 1
    assert enviadas[0].tipo is TipoOrden.MERCADO and enviadas[0].ruta == "OPEN"


# ── matriz de R-F-01: k × stop × franja × primera vela ───────────────────
MATRIZ = list(itertools.product((1, 2, 3), ("encima", "debajo"), ("RTH", "premercado"), ("lt6", "ge6")))


@pytest.mark.parametrize("k, stop, franja, vela", MATRIZ,
                         ids=[f"R-F-01-k{k}-stop-{s}-{f}-vela-{v}" for k, s, f, v in MATRIZ])
def test_matriz_reapertura(k, stop, franja, vela, cfg_halts):
    pos = posicion(-200, (D("11") if stop == "encima" else D("9"),))
    ta = "P" if franja == "RTH" else "H"            # en PM no hay LULD (R-F-06)
    s = simbolo(ta=ta, k=k, parada=D("10"))
    stops = niveles("11" if stop == "encima" else "9")
    decision = decidir_reapertura(pos, s, stops, cot(last="10"), cfg_halts, franja, 5)
    cerrar = "cerrar_mercado" if franja == "RTH" else "cerrar_limite_pm"
    if stop == "encima" and k < 3:
        assert decision == "mantener"                  # esc. 1 con k < 3
    else:
        assert decision == cerrar                      # esc. 1 con k = 3, o esc. 2 sí o sí
    pct = D("5.99") if vela == "lt6" else D("6")
    assert puede_reentrar_tras_halt(pct, k, cfg_halts) is (vela == "lt6" and k < 3)
    assert decision in DECISIONES


@pytest.mark.parametrize("franja, esperado", [
    ("RTH", "cerrar_mercado"), ("RTH (media sesion)", "cerrar_mercado"), ("premercado", "cerrar_limite_pm"),
    ("premercado (media sesion)", "cerrar_limite_pm"), ("postmercado", "cerrar_limite_pm"), ("cerrado", "cerrar_limite_pm"),
], ids=["R-F-01-rth", "rth-media-sesion", "R-F-06-pm", "R-F-06-pm-media", "sin-mkt-post", "sin-mkt-cerrado"])
def test_franja_decide_mercado_o_limite(franja, esperado, cfg_halts):
    pos = posicion(-100, (D("9"),))
    assert decidir_reapertura(pos, simbolo(ta="H"), niveles("9"), cot(last="10"), cfg_halts, franja, 1) == esperado


def test_stop_igual_al_precio_es_escenario_2(cfg_halts):
    """R-F-01 esc. 2 «stop por debajo… o por cualquier otra causa»: igual al precio ya no protege → cerrar."""
    pos = posicion(-100, (D("10"),))
    assert decidir_reapertura(pos, simbolo(k=1), niveles("10"), cot(last="10"), cfg_halts, "RTH", 1) == "cerrar_mercado"


@pytest.mark.parametrize("stop, k, esperado", [
    ("9", 1, "mantener"), ("11", 1, "cerrar_mercado"), ("9", 3, "cerrar_mercado"), ("10", 1, "cerrar_mercado"),
], ids=["largo-stop-debajo-mantener", "largo-stop-encima-cerrar", "largo-k3-cerrar", "largo-stop-igual-cerrar"])
def test_largo_se_refleja(stop, k, esperado, cfg_halts):
    pos = posicion(100, (D(stop),))
    assert decidir_reapertura(pos, simbolo(k=k), niveles(stop), cot(last="10"), cfg_halts, "RTH", 1) == esperado


def test_k_max_de_la_config(cfg_halts):
    cfg = dict(cfg_halts, k_max=2)
    pos = posicion(-100, (D("11"),))
    assert decidir_reapertura(pos, simbolo(k=1), niveles("11"), cot(last="10"), cfg, "RTH", 1) == "mantener"
    assert decidir_reapertura(pos, simbolo(k=2), niveles("11"), cot(last="10"), cfg, "RTH", 1) == "cerrar_mercado"


def test_precio_de_referencia_last_y_luego_parada(cfg_halts):
    pos = posicion(-100, (D("10.5"),))
    # last 11 > stop 10.5 → esc. 2; sin last, la parada 10 < stop → esc. 1
    assert decidir_reapertura(pos, simbolo(k=1), niveles("10.5"), cot(last="11"), cfg_halts, "RTH", 1) == "cerrar_mercado"
    assert decidir_reapertura(pos, simbolo(k=1), niveles("10.5"), cot(), cfg_halts, "RTH", 1) == "mantener"
    assert decidir_reapertura(pos, simbolo(k=1), niveles("10.5"), None, cfg_halts, "RTH", 1) == "mantener"


@pytest.mark.parametrize("cotizacion, parada, stops", [
    (None, None, "9"), (cot(), None, "9"), (cot(last="0"), D("0"), "9"), (cot(last="10"), D("10"), None),
], ids=["sin-cot-sin-parada", "cot-vacia-sin-parada", "precios-cero", "sin-niveles-de-stop"])
def test_sin_datos_control_humano(cotizacion, parada, stops, cfg_halts):
    pos = posicion(-100, (D("9"),))
    st = niveles(stops) if stops else None
    assert decidir_reapertura(pos, simbolo(parada=parada), st, cotizacion, cfg_halts, "RTH", 1) == "control_humano"


def test_sin_posicion_mantener_aunque_sea_t12(cfg_halts):
    pos = PosicionTicker(ticker=X)
    assert decidir_reapertura(pos, simbolo(ta="H"), None, None, cfg_halts, "RTH", 10_000) == "mantener"


# ── T1 (> 250 %) y T12 (duración) ─────────────────────────────────────────
@pytest.mark.parametrize("ta, parada, last, stop, franja, esperado", [
    ("H", D("1"), "3.51", "2", "RTH", "control_humano"),
    ("H", D("1"), "3.50", "2", "RTH", "cerrar_mercado"),
    ("H", D("1"), "3.51", "2", "premercado", "control_humano"),
    ("H", D("1"), "3.50", "2", "premercado", "cerrar_limite_pm"),
    ("P", D("1"), "4.00", "2", "RTH", "cerrar_mercado"),
    ("H", None, "4.00", "2", "RTH", "cerrar_mercado"),
    ("T", D("1"), "3.51", "2", "RTH", "control_humano"),
    ("H", D("1"), "3.51", "5", "RTH", "mantener"),
], ids=["R-F-05-T1-mas-250-humano", "R-F-05-T1-250-exacto-cierra", "R-F-06-T1-pm-mas-250-humano",
        "R-F-06-T1-pm-250-limite", "R-F-05-LULD-sin-tope", "T1-sin-parada-prima-cerrar", "ya-reabierto-aplica-tope",
        "T1-stop-encima-mantener"])
def test_t1_tope_250(ta, parada, last, stop, franja, esperado, cfg_halts):
    """La función en aislado con un `last` YA de reapertura (así la llama el decisor al reabrir, E1-02).

    E1-09: durante un halt H el `last` es el de antes de parar; ese flujo real
    lo prueban `test_E1_09_flujo_real_*` (la orden nunca paga más de parada · 3,5).
    """
    pos = posicion(-100, (D(stop),))
    s = simbolo(ta=ta, k=1, parada=parada)
    assert decidir_reapertura(pos, s, niveles(stop), cot(last=last), cfg_halts, franja, 30) == esperado


@pytest.mark.parametrize("duracion, t12_min, esperado", [
    (240.0, None, "cerrar_mercado"), (240.01, None, "control_humano"), (61, 60, "control_humano"), (60, 60, "cerrar_mercado"),
], ids=["R-F-05-T12-240-exacto-no", "R-F-05-T12-presunto", "t12-config-60", "t12-config-60-exacto"])
def test_t12_por_duracion(duracion, t12_min, esperado, cfg_halts):
    cfg = dict(cfg_halts) if t12_min is None else dict(cfg_halts, t12_min=t12_min)
    pos = posicion(-100, (D("9"),))
    assert decidir_reapertura(pos, simbolo(ta="H", k=1), niveles("9"), cot(last="10"), cfg, "RTH", duracion) == esperado


def test_config_vacia_usa_defectos_del_libro():
    pos = posicion(-100, (D("11"),))
    assert decidir_reapertura(pos, simbolo(k=2), niveles("11"), cot(last="10"), {}, "RTH", 1) == "mantener"
    assert decidir_reapertura(pos, simbolo(k=3), niveles("11"), cot(last="10"), {}, "RTH", 1) == "cerrar_mercado"
    assert decidir_reapertura(pos, simbolo(ta="H", k=1), niveles("9"), cot(last="10"), {}, "RTH", 241) == "control_humano"


@pytest.mark.parametrize("cfg", [{"k_max": 2.5}, {"k_max": True}, {"t12_min": True}],
                         ids=["k_max-no-entero", "k_max-bool", "t12-bool"])
def test_config_mal_formada_lanza(cfg):
    with pytest.raises(ValueError):
        decidir_reapertura(posicion(-100, (D("11"),)), simbolo(k=1), niveles("11"), cot(last="10"), cfg, "RTH", 1)


# ── cerca_de_banda (R-F-01: k = 2 y a ≤ 4 % del limit up) ─────────────────
@pytest.mark.parametrize("ask, k, ta, limit_up, cfg_extra, esperado", [
    ("9.60", 2, None, D("10"), {}, True),
    ("9.59", 2, None, D("10"), {}, False),
    ("10.20", 2, None, D("10"), {}, True),
    ("9.60", 1, None, D("10"), {}, False),
    ("9.60", 3, None, D("10"), {}, False),
    ("9.60", 2, "P", D("10"), {}, False),
    (None, 2, None, D("10"), {}, False),
    ("9.60", 2, None, None, {}, False),
    ("9.80", 2, None, D("10"), {"distancia_banda_k2_pct": 2.0}, True),
    ("9.79", 2, None, D("10"), {"distancia_banda_k2_pct": 2.0}, False),
    ("9.60", 1, None, D("10"), {"k_max": 2}, True),
], ids=["R-F-01-k2-a-4pct-exacto", "R-F-01-k2-fuera", "R-F-01-ask-sobre-banda", "k1-no", "k3-no", "ya-parado-no",
        "sin-ask", "sin-banda", "distancia-config", "distancia-config-fuera", "k_max-2-avisa-en-k1"])
def test_cerca_de_banda(ask, k, ta, limit_up, cfg_extra, esperado, cfg_halts):
    s = simbolo(ta=ta, limit_up=limit_up)
    assert cerca_de_banda(cot(ask=ask, bid="9"), s, k, dict(cfg_halts, **cfg_extra)) is esperado


def test_cerca_de_banda_sin_cotizacion(cfg_halts):
    assert cerca_de_banda(None, simbolo(ta=None), 2, cfg_halts) is False


# ── orden_reapertura (EP-2, R-F-06) ──────────────────────────────────────
def test_cerrar_mercado_corto_compra_por_open(config):
    o = orden_reapertura(posicion(-300, (D("9"),)), 300, cot(last="10"), "cerrar_mercado", config, 42, HORA_RTH)
    assert (o.lado, o.ticker, o.ruta, o.qty, o.tipo, o.precio, o.proposito, o.token) == \
        (Lado.COMPRA, X, "OPEN", 300, TipoOrden.MERCADO, None, Proposito.HALT_OPEN, 42)


def test_cerrar_mercado_largo_vende(config):
    o = orden_reapertura(posicion(200, (D("9"),)), 150, cot(last="10"), "cerrar_mercado", config, 43, HORA_RTH)
    assert (o.lado, o.qty, o.tipo, o.ruta) == (Lado.VENTA, 150, TipoOrden.MERCADO, "OPEN")


@pytest.mark.parametrize("neta, cotizacion, hora, precio, ruta", [
    (-100, cot(bid="1.90", ask="2.00"), HORA_PM, D("2.10"), "SAGEPRO"),
    (-100, cot(bid="2.00", ask="2.03"), HORA_PM, D("2.14"), "SAGEPRO"),
    (-100, cot(bid="0.49", ask="0.50"), HORA_PM, D("0.525"), "MIAX"),
    (-100, cot(bid="0.49", ask="0.50"), datetime(2026, 9, 25, 7, 30, tzinfo=ET), D("0.525"), "EDGA"),
    (-100, cot(last="2.00"), HORA_PM, D("2.10"), "SAGEPRO"),
    (100, cot(bid="2.00", ask="2.05"), HORA_PM, D("1.90"), "SAGEPRO"),
    (100, cot(bid="2.03", ask="2.05"), HORA_PM, D("1.92"), "SAGEPRO"),
], ids=["R-F-06-corto-ask+5pct", "R-F-06-redondeo-arriba", "R-F-06-lt1-antes-0700-MIAX", "R-F-06-lt1-desde-0700-EDGA",
        "R-F-06-sin-ask-usa-last", "R-F-06-largo-bid-5pct", "R-F-06-largo-redondeo-abajo"])
def test_cerrar_limite_pm(neta, cotizacion, hora, precio, ruta, config):
    o = orden_reapertura(posicion(neta, (D("9"),)), abs(neta), cotizacion, "cerrar_limite_pm", config, 7, hora)
    assert o.tipo is TipoOrden.LIMITE and o.proposito is Proposito.HALT_PM_LIMITE and o.tif == "DAY+"
    assert o.precio == precio and o.ruta == ruta
    assert o.lado is (Lado.COMPRA if neta < 0 else Lado.VENTA)


def test_cerrar_limite_pm_margen_de_la_config(cfg_json):
    cfg = {"rutas": cfg_json["rutas"], "halts": dict(cfg_json["halts"], margen_limite_pm_pct=10.0)}
    o = orden_reapertura(posicion(-100, (D("9"),)), 100, cot(ask="2.00"), "cerrar_limite_pm", cfg, 7, HORA_PM)
    assert o.precio == D("2.20")


@pytest.mark.parametrize("neta, qty, cotizacion, decision", [
    (-100, 100, cot(last="10"), "mantener"),
    (-100, 100, cot(last="10"), "control_humano"),
    (0, 100, cot(last="10"), "cerrar_mercado"),
    (-100, 101, cot(last="10"), "cerrar_mercado"),
    (-100, 100, cot(), "cerrar_limite_pm"),
    (-100, 100, None, "cerrar_limite_pm"),
    (-100, 0, cot(last="10"), "cerrar_mercado"),
], ids=["mantener-no-hay-orden", "humano-no-hay-orden", "sin-posicion", "riesgo6-qty-mayor-que-posicion",
        "pm-sin-precios", "pm-sin-cotizacion", "qty-cero"])
def test_orden_reapertura_errores(neta, qty, cotizacion, decision, config):
    pos = posicion(neta, (D("9"),)) if neta else PosicionTicker(ticker=X)
    with pytest.raises(ValueError):
        orden_reapertura(pos, qty, cotizacion, decision, config, 1, HORA_RTH)


def test_orden_reapertura_config_sin_rutas():
    with pytest.raises(ValueError):
        orden_reapertura(posicion(-100, (D("9"),)), 100, cot(last="10"), "cerrar_mercado", {"halts": {}}, 1, HORA_RTH)


# ── E1-01 / E1-02 / E1-09: el tope del 250 % en un halt H (T1/T12) ─────────
@pytest.mark.parametrize("ta, parada, esperado", [
    ("H", D("1"), D("3.50")), ("Q", D("1"), D("3.50")), ("T", D("1"), D("3.50")), (None, D("1"), D("3.50")),
    ("H", D("0.4567"), D("1.59")), ("H", D("2.97"), D("10.39")), ("P", D("1"), None), ("H", None, None),
    ("H", D("0"), None),
], ids=["E1-01-H", "E1-01-Q", "E1-01-reabierto", "E1-01-sin-TA", "E1-01-redondeo-abajo-sub-dolar",
        "E1-01-redondeo-abajo", "E1-01-LULD-sin-tope", "sin-parada", "parada-cero"])
def test_E1_01_precio_tope_t1(ta, parada, esperado, cfg_halts, config):
    """E1-01: parada · (1 + 250/100) redondeado ABAJO al tick; en LULD no hay tope; sin parada, None."""
    s = simbolo(ta=ta, parada=parada)
    assert halts.precio_tope_t1(s, cfg_halts) == esperado
    assert halts.precio_tope_t1(s, config) == esperado             # también con la Config entera


def test_E1_01_precio_tope_t1_de_la_config(cfg_halts):
    assert halts.precio_tope_t1(simbolo(ta="H", parada=D("1")), dict(cfg_halts, t1_subida_max_cierre_pct=100.0)) == D("2")


def test_E1_09_flujo_real_halt_H_last_igual_a_parada_no_sale_a_mercado(cfg_halts, config):
    """E1-01 / E1-09: halt H, corto con el stop por DEBAJO, `last` = el print de antes de parar (lo único que hay).

    La decisión sale «cerrar_mercado» (la subida medida es 0 %), pero la orden
    ya NO es una MKT sin tope: es un LÍMITE por OPEN a parada · 3,5. Si el T1
    reabre a +300 % no llena y el decisor pasa a control humano.
    """
    pos = posicion(-300, (D("1.50"),))
    s = simbolo(ta="H", tat=None, k=0, parada=D("2.00"), limit_up=None, limit_down=None)
    decision = decidir_reapertura(pos, s, niveles("1.50"), cot(last="2.00"), cfg_halts, "RTH", 0.0)
    assert decision == "cerrar_mercado"
    o = orden_reapertura(pos, 300, cot(last="2.00"), decision, config, 11, HORA_RTH, simb=s)
    assert (o.tipo, o.precio, o.ruta, o.proposito, o.lado, o.qty) == \
        (TipoOrden.LIMITE, D("7.00"), "OPEN", Proposito.HALT_OPEN, Lado.COMPRA, 300)
    assert o.tipo is not TipoOrden.MERCADO and o.precio <= s.precio_parada * D("3.5")
    # al reabrir a +300 % (8,00) la función única manda control humano (E1-02)
    assert halts.tope_t1_superado(s, D("8.00"), cfg_halts) is True
    assert halts.tope_t1_superado(s, D("7.00"), cfg_halts) is False


def test_E1_01_luld_sigue_a_mercado(config):
    """En una pausa LULD (P) manda k y no hay tope: la salida por OPEN sigue siendo a MERCADO."""
    pos = posicion(-300, (D("9"),))
    o = orden_reapertura(pos, 300, cot(last="10"), "cerrar_mercado", config, 42, HORA_RTH,
                         simb=simbolo(ta="P", parada=D("10")))
    assert o.tipo is TipoOrden.MERCADO and o.precio is None


def test_E1_01_sin_simb_comportamiento_anterior(config):
    """Sin `simb` (llamador sin actualizar) la orden es la de antes: MKT por OPEN (compatibilidad aditiva)."""
    o = orden_reapertura(posicion(-300, (D("9"),)), 300, cot(last="10"), "cerrar_mercado", config, 42, HORA_RTH)
    assert o.tipo is TipoOrden.MERCADO


def test_E1_01_largo_no_se_capa(config):
    """El tope del 250 % es de SUBIDA (cubrir un corto): una neta larga vende a mercado igual."""
    o = orden_reapertura(posicion(200, (D("9"),)), 200, cot(last="10"), "cerrar_mercado", config, 43, HORA_RTH,
                         simb=simbolo(ta="H", parada=D("10")))
    assert o.tipo is TipoOrden.MERCADO and o.lado is Lado.VENTA


def test_E1_01_limite_pm_capado_al_tope_t1(config):
    """El límite de premercado / reintento (ask + 5 %) tampoco paga más de parada · 3,5 en un halt no LULD."""
    pos = posicion(-100, (D("1"),))
    s = simbolo(ta="H", parada=D("1"))
    o = orden_reapertura(pos, 100, cot(bid="3.90", ask="4.00"), "cerrar_limite_pm", config, 7, HORA_PM, simb=s)
    assert o.precio == D("3.50") and o.tipo is TipoOrden.LIMITE and o.proposito is Proposito.HALT_PM_LIMITE
    # por debajo del tope, el límite normal
    o2 = orden_reapertura(pos, 100, cot(bid="1.90", ask="2.00"), "cerrar_limite_pm", config, 8, HORA_PM, simb=s)
    assert o2.precio == D("2.10")


@pytest.mark.parametrize("ta, parada, precio, luld, esperado", [
    ("H", D("1"), D("3.51"), None, True), ("H", D("1"), D("3.50"), None, False), ("T", D("1"), D("3.51"), None, True),
    ("T", D("1"), D("3.51"), True, False), ("P", D("1"), D("9"), None, False), ("T", D("1"), D("9"), False, True),
    ("H", None, D("9"), None, False), ("H", D("1"), None, None, False), ("H", D("1"), D("0"), None, False),
], ids=["E1-02-supera", "E1-02-250-exacto-no", "E1-02-reabierto-sin-saber-aplica", "E1-02-paro-en-LULD",
        "E1-02-LULD-sin-tope", "E1-02-luld-false-explicito", "sin-parada", "sin-precio", "precio-cero"])
def test_E1_02_tope_t1_superado(ta, parada, precio, luld, esperado, cfg_halts):
    """E1-02: la función ÚNICA que el decisor usa al reabrir con el precio real (y decidir_reapertura por dentro)."""
    assert halts.tope_t1_superado(simbolo(ta=ta, parada=parada), precio, cfg_halts, luld=luld) is esperado


# ── E1-04: R-F-06 2.ª parte, ensanchar el stop límite en un halt H de premercado ─
def stop_vivo(token: int, proposito: Proposito, stop: str, limite: str, qty: int = 100, llenas: int = 0,
              id_das: Optional[int] = 700, estado: EstadoOrden = EstadoOrden.ACCEPTED, ticker: str = X,
              lvqty: int = 0) -> Orden:
    return Orden(token=token, ticker=ticker, lado=Lado.COMPRA, tipo=TipoOrden.STOP_LIMITE_PP, qty=qty, precio=D(limite),
                 stop=D(stop), ruta="STOP", proposito=proposito, lote_id=None, nivel=None, origen=Origen.EJECUTOR,
                 id_das=id_das, estado=estado, llenas=llenas, lvqty=lvqty)


def test_E1_04_ensancha_solo_el_limite_del_principal(config):
    """E1-04: halt H en premercado + «mantener» → REPLACE del límite a disparo · 1,05; mismo disparo y cantidad."""
    pos = posicion(-300, (D("2"),))
    pos.version_stops = 7
    vivas = [stop_vivo(1, Proposito.STOP_PRINCIPAL, "2.00", "2.06", qty=300, id_das=701),
             stop_vivo(2, Proposito.STOP_EMERGENCIA, "2.26", "3.26", qty=300, id_das=702)]
    acciones = halts.ensanchar_stops_pm(pos, vivas, simbolo(ta="H", parada=D("1.9")), "premercado", config)
    assert [type(a) for a in acciones] == [Anotar, Reemplazar, Programar]
    r = acciones[1]
    assert (r.id_das, r.token, r.qty, r.stop, r.precio, r.version, r.serie) == (701, 1, 300, D("2.00"), D("2.10"), 7,
                                                                                 "stops:XYZ")
    assert acciones[2].clave == "replace_verificar" and acciones[2].datos["qty_objetivo"] == 300
    assert acciones[0].tipo == halts.ANOTACION_STOPS_PM and acciones[0].datos["stops"][0]["limite_nuevo"] == "2.10"
    json.dumps(acciones[0].datos)


@pytest.mark.parametrize("ta, franja, neta", [
    ("P", "premercado", -300), ("H", "RTH", -300), ("H", "postmercado", -300), (None, "premercado", -300),
    ("T", "premercado", -300), ("H", "premercado", 300), ("H", "premercado", 0),
], ids=["LULD-no", "RTH-no", "post-no", "sin-halt-no", "reabierto-no", "largo-no", "plano-no"])
def test_E1_04_no_aplica(ta, franja, neta, config):
    pos = posicion(neta, (D("2"),)) if neta else PosicionTicker(ticker=X)
    vivas = [stop_vivo(1, Proposito.STOP_PRINCIPAL, "2.00", "2.06", qty=300)]
    assert halts.ensanchar_stops_pm(pos, vivas, simbolo(ta=ta), franja, config) == []


def test_E1_04_q_en_premercado_tambien(config):
    pos = posicion(-300, (D("2"),))
    vivas = [stop_vivo(1, Proposito.STOP_PRINCIPAL, "2.00", "2.06", qty=300)]
    assert any(isinstance(a, Reemplazar) for a in halts.ensanchar_stops_pm(pos, vivas, simbolo(ta="Q"), "premercado",
                                                                           config))


def test_E1_04_ignora_lo_que_no_es_stop_de_compra_vivo(config):
    pos = posicion(-300, (D("2"),))
    vivas = [stop_vivo(1, Proposito.STOP_PRINCIPAL, "2.00", "2.06", id_das=None),
             stop_vivo(2, Proposito.STOP_PRINCIPAL, "2.00", "2.06", estado=EstadoOrden.CANCELED),
             stop_vivo(3, Proposito.STOP_PRINCIPAL, "2.00", "2.06", ticker="OTRO"),
             orden_viva(4, Proposito.TP_AGREGAR, lado=Lado.COMPRA),
             stop_vivo(5, Proposito.STOP_PRINCIPAL, "2.00", "2.10")]          # ya tiene el margen: no se toca
    assert halts.ensanchar_stops_pm(pos, vivas, simbolo(ta="H"), "premercado", config) == []


@pytest.mark.parametrize("share_es_abierta, esperado", [(True, 60), (False, 100), (None, 60)],
                         ids=["A-02-abierta", "A-02-total", "A-02-defecto"])
def test_E1_04_share_parcial(share_es_abierta, esperado, cfg_json):
    """A-02: el `share` del REPLACE sale de tipos.share_de_replace según stops.replace_share_es_abierta."""
    stops_cfg = dict(cfg_json["stops"])
    if share_es_abierta is not None:
        stops_cfg["replace_share_es_abierta"] = share_es_abierta
    else:
        stops_cfg.pop("replace_share_es_abierta", None)
    cfg = {"halts": cfg_json["halts"], "stops": stops_cfg, "rutas": cfg_json["rutas"]}
    pos = posicion(-60, (D("2"),))
    vivas = [stop_vivo(1, Proposito.STOP_PRINCIPAL, "2.00", "2.06", qty=100, llenas=40, lvqty=60,
                       estado=EstadoOrden.PARTIAL)]
    r = [a for a in halts.ensanchar_stops_pm(pos, vivas, simbolo(ta="H"), "premercado", cfg) if isinstance(a, Reemplazar)]
    assert r[0].qty == esperado and r[0].precio == D("2.10")


def test_E1_04_cadenas_iguales_que_el_modulo_de_stops():
    """halts no importa el módulo de stops (ajuste (a)): la serie, la clave y el interruptor deben coincidir."""
    from app.bot_das.reglas import stops as mod_stops
    assert halts._SERIE_STOPS.format(X) == mod_stops.serie_stops(X)
    assert halts._CLAVE_VERIFICAR_REPLACE == mod_stops.CLAVE_VERIFICAR_REPLACE
    assert halts._VERIFICAR_REPLACE_EN_S == mod_stops.VERIFICAR_REPLACE_EN_S
    assert halts._CLAVE_SHARE_ES_ABIERTA == mod_stops.CLAVE_SHARE_ES_ABIERTA
    assert set(halts._ESTADOS_VIVOS) == set(mod_stops.ESTADOS_VIVOS)


# ── al_entrar_en_halt (B18, R-F-04 a, R-G-02) ────────────────────────────
def test_al_entrar_en_halt_cancela_solo_entradas_vivas_y_avisa():
    pos = posicion(-300, (D("11"), D("11.5")))
    vivas = [
        orden_viva(1, Proposito.ENTRADA_AGREGAR, id_das=501),
        orden_viva(2, Proposito.ENTRADA_CRUCE, id_das=502, estado=EstadoOrden.PARTIAL),
        orden_viva(3, Proposito.ENTRADA_AGREGAR, id_das=None, estado=EstadoOrden.SENDING),
        orden_viva(4, Proposito.STOP_PRINCIPAL, id_das=504, lado=Lado.COMPRA),
        orden_viva(5, Proposito.STOP_EMERGENCIA, id_das=505, lado=Lado.COMPRA),
        orden_viva(6, Proposito.ENTRADA_AGREGAR, id_das=506, estado=EstadoOrden.CANCELED),
        orden_viva(7, Proposito.ENTRADA_AGREGAR, id_das=507, estado=EstadoOrden.EXECUTED),
        orden_viva(8, Proposito.ENTRADA_AGREGAR, id_das=508, ticker="OTRO"),
        orden_viva(9, Proposito.TP_AGREGAR, id_das=509, lado=Lado.COMPRA),
    ]
    s = simbolo(ta="P", tat="10:15:30", k=2, parada=D("10.40"), desde=datetime(2026, 9, 25, 10, 15, 31, tzinfo=ET))
    acciones = al_entrar_en_halt(pos, vivas, s, cot(last="10.45"), "RTH")
    cancelar = [a for a in acciones if isinstance(a, Cancelar)]
    assert [(a.id_das, a.token) for a in cancelar] == [(501, 1), (502, 2)]
    assert all("B18" in a.motivo for a in cancelar)
    # orden: Cancelar… → Anotar → Avisar
    assert [type(a) for a in acciones] == [Cancelar, Cancelar, Anotar, Avisar]
    anotar, avisar = acciones[2], acciones[3]
    assert anotar.tipo == "halt"
    d = anotar.datos
    assert d["ta"] == "P" and d["tat"] == "10:15:30" and d["k"] == 2 and d["precio_parada"] == "10.40"
    assert d["decision"] is None and d["fin_previsto"] == datetime(2026, 9, 25, 10, 20, 30, tzinfo=ET).isoformat()
    assert d["entradas_canceladas"] == [1, 2] and d["entradas_sin_id"] == [3]
    assert d["niveles_stop"] == ["11", "11.5"] and d["neta"] == -300
    assert d["limit_up"] == "10.50" and d["limit_down"] == "9.50"
    json.dumps(d)                                      # el diario lo serializa tal cual
    assert avisar.nivel is Nivel.AVISO and avisar.grupo is Grupo.B
    for trozo in ("HALT XYZ", "LULD", "10:15:30", "10.40", "-300", "11/11.5", "k=2", "bandas LULD 9.50-10.50",
                  "entradas canceladas: 2"):
        assert trozo in avisar.texto, trozo
    assert avisar.clave and X in avisar.clave


def test_al_entrar_en_halt_en_premercado_sin_bandas_y_parada_del_last():
    pos = posicion(-100, (D("3"),))
    s = simbolo(ta="H", tat=None, k=0, parada=None, limit_up=None, limit_down=None)
    acciones = al_entrar_en_halt(pos, [], s, cot(last="2.50"), "premercado")
    assert [type(a) for a in acciones] == [Anotar, Avisar]
    texto = acciones[1].texto
    assert "bandas" not in texto and "premercado" in texto and "parada 2.50" in texto and "hora ?" in texto
    assert acciones[0].datos["fin_previsto"] is None and acciones[0].datos["precio_parada"] == "2.50"


def test_al_entrar_en_halt_sin_posicion_con_entrada_viva():
    """R-G-02 «o con orden de entrada viva»: sin lotes, cancela la entrada y el texto dice «sin lotes»."""
    pos = PosicionTicker(ticker=X)
    acciones = al_entrar_en_halt(pos, [orden_viva(1, Proposito.ENTRADA_AGREGAR, id_das=9)], simbolo(), None, "RTH")
    assert isinstance(acciones[0], Cancelar)
    assert "sin lotes" in acciones[-1].texto and "parada 10" in acciones[-1].texto


def test_D2_08_aviso_de_halt_escapado():
    """D2-08: el TAT y el ticker vienen de DAS; un «<» o «&» no puede perder el aviso (Telegram con parse_mode HTML)."""
    pos = posicion(-100, (D("11"),), ticker="A&B")
    s = EstadoSimbolo(ticker="A&B", ta="H", tat="<10:00>", k_halts_up=0, precio_parada=D("10"))
    texto = al_entrar_en_halt(pos, [], s, None, "RTH")[-1].texto
    assert "A&amp;B" in texto and "&lt;10:00&gt;" in texto and "<10:00>" not in texto


def test_claves_de_aviso_distintas_por_halt():
    pos = posicion(-100, (D("11"),))
    a1 = al_entrar_en_halt(pos, [], simbolo(desde=datetime(2026, 9, 25, 10, 0, tzinfo=ET)), None, "RTH")[-1]
    a2 = al_entrar_en_halt(pos, [], simbolo(desde=datetime(2026, 9, 25, 10, 30, tzinfo=ET)), None, "RTH")[-1]
    assert a1.clave != a2.clave


# ── reentradas y señal guardada (R-F-01 esc. 2, R-F-03, R-F-04 b) ────────
@pytest.mark.parametrize("pct, k, cfg_extra, esperado", [
    (D("5.99"), 2, {}, True), (D("6"), 2, {}, False), (D("6.01"), 1, {}, False), (D("-3"), 1, {}, True),
    (D("1"), 3, {}, False), (None, 1, {}, False), (D("7"), 1, {"primera_vela_max_reentrada_pct": 8.0}, True),
], ids=["R-F-03-vela-5.99", "R-F-03-vela-6-exacto-no", "R-F-01-vela-mayor", "vela-bajista", "R-F-03-k3-no",
        "sin-vela-no", "umbral-config"])
def test_puede_reentrar_tras_halt(pct, k, cfg_extra, esperado, cfg_halts):
    assert puede_reentrar_tras_halt(pct, k, dict(cfg_halts, **cfg_extra)) is esperado


def senal(clase: str = "evento", tipo: Optional[str] = "entrada") -> Senal:
    return Senal(clase=clase, ticker=X, id="XYZ|s|2026-09-25T10:14:00|entrada",
                 evento=SimpleNamespace(tipo=tipo) if tipo is not None else None)


@pytest.mark.parametrize("s, pct, k, cfg_extra, esperado", [
    (senal(), D("5"), 1, {}, True),
    (senal(), D("6"), 1, {}, False),
    (senal(), D("5"), 3, {}, False),
    (None, D("5"), 1, {}, False),
    (senal(clase="radar"), D("5"), 1, {}, False),
    (senal(tipo="salida"), D("5"), 1, {}, False),
    (senal(tipo=None), D("5"), 1, {}, False),
    (senal(), None, 1, {}, False),
    (senal(), D("7"), 1, {"primera_vela_max_senal_guardada_pct": 8.0}, True),
    (senal(), D("5"), 1, {"primera_vela_max_senal_guardada_pct": 4.0}, False),
], ids=["R-F-04b-valida", "R-F-04b-vela-6-no", "R-F-04b-k3-no", "sin-senal", "no-es-evento", "evento-de-salida",
        "sin-evento", "sin-vela", "X-de-la-config", "X-de-la-config-estricto"])
def test_senal_guardada_valida(s, pct, k, cfg_extra, esperado, cfg_halts):
    assert senal_guardada_valida(s, pct, dict(cfg_halts, **cfg_extra), k) is esperado


def test_senal_guardada_valida_exige_k(cfg_halts):
    """Sin `k` no hay llamada posible: el decisor no puede saltarse el «k < 3» de F6.3."""
    with pytest.raises(TypeError):
        senal_guardada_valida(senal(), D("1"), cfg_halts)  # type: ignore[call-arg]


@pytest.mark.parametrize("reapertura, cierre, esperado", [
    (D("10"), D("10.60"), D("6")), (D("10"), D("9.50"), D("-5")), (D("0.5"), D("0.53"), D("6")),
], ids=["R-F-01-sube-6", "baja-5", "sub-dolar"])
def test_primera_vela_pct(reapertura, cierre, esperado):
    assert primera_vela_pct(reapertura, cierre) == esperado


@pytest.mark.parametrize("reapertura, cierre", [
    (D("0"), D("1")), (D("-1"), D("1")), (D("1"), D("0")), (D("NaN"), D("1")), (D("1"), D("Infinity")),
], ids=["reapertura-0", "reapertura-negativa", "cierre-0", "nan", "inf"])
def test_primera_vela_pct_rechaza_precios_imposibles(reapertura, cierre):
    with pytest.raises(ValueError):
        primera_vela_pct(reapertura, cierre)


# ── pureza (§3: reglas/ sin I/O, sin reloj, sin logging, sin entorno) ─────
def test_modulo_puro():
    fuente = Path(halts.__file__).read_text(encoding="utf-8")
    arbol = ast.parse(fuente)
    importados = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            importados.update(a.name.split(".")[0] for a in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module:
            importados.add(nodo.module.split(".")[0])
    assert not importados & {"time", "logging", "os", "socket", "urllib", "httpx", "threading", "random"}
    assert "app.bot_das.reglas.stops" not in fuente           # ajuste (a): recibe NivelesStop ya calculadas
    llamadas = {n.func.id for n in ast.walk(arbol) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    atributos = {n.attr for n in ast.walk(arbol) if isinstance(n, ast.Attribute)}
    assert not llamadas & {"open", "print", "input", "eval", "exec"}
    assert not atributos & {"now", "today", "utcnow", "environ", "getenv", "monotonic"}
    assert isinstance(halts.MARGEN_LIMITE_PM_PCT_DEFECTO, Decimal)
