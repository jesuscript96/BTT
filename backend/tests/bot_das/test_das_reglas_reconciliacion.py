"""reglas/reconciliacion.py: los 6 casos (R-C-10, R-K-02, R-M-03, M7), barrido adaptativo (R-K-01), caducidad (R-K-03) y AcumuladorVolcado (§5.11)."""
from __future__ import annotations

import ast
import itertools
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pytest

from app.bot_das import tokens as mod_tokens
from app.bot_das.protocolo import Parser
from app.bot_das.reglas import reconciliacion as rc
from app.bot_das.reglas.reconciliacion import (
    CASO_AJENA, CASO_CERRADA_EN_DAS, CASO_COINCIDE, CASO_NETA_DISTINTA, CASO_SIN_STOP, CASO_STOP_DIFIERE,
    AcumuladorVolcado, Discrepancia, acciones, barrido_caducado, cadencia_barrido, cobertura, comandos_barrido, comparar,
    es_ajena, huerfanas, orden_de_msg,
)
from app.bot_das.reloj import ET
from app.bot_das.tipos import (
    BARRIDO_CON_POSICIONES_S, BARRIDO_SIN_NADA_S, BARRIDO_TRAS_FILL_S, RECONCILIACION_CADUCA_S, Anotar, Avisar, Cancelar,
    CancelarTicker, Config, Consultar, Cotizacion, EnviarOrden, EstadoBot, EstadoLote, EstadoOrden, EstadoTicker, Fase,
    FaseIntento, Grupo, IntentoEntrada, InvalidarSerie, Lado, Lote, MsgBP, MsgMarcador, MsgOrden, MsgPos, MsgTrade, Nivel,
    Orden, Origen, PosicionTicker, Proposito, Reemplazar, TipoOrden, en_tick,
)

D = Decimal
RUTA_CONFIG = Path(__file__).parent / "fixtures" / "config_ejemplo.json"
HOY = date(2026, 9, 25)
AYER = HOY - timedelta(days=1)
HORA = datetime(2026, 9, 25, 9, 45, tzinfo=ET)
X = "XYZ"
RUTA_STOP = "STOP"


# ── construcción ─────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def cfg() -> Config:
    """`Config` de tipos construida desde el fichero de ejemplo (sin depender de config.py)."""
    crudo = json.loads(RUTA_CONFIG.read_text(encoding="utf-8"))
    claves = ("schema_version", "config_version", "sha256", "motor_hash", "estrategias_hash", "generado_at", "vigilando",
              "horario", "modo_seguridad", "lista_negra", "pausar_entradas", "locates", "entrada", "salidas", "stops",
              "halts", "exclusiones", "rutas", "tecnicos", "alertas_grupo_a")
    return Config(fase=Fase(crudo["fase"]), estrategias={}, cuenta_das="CUENTA_PRUEBA", **{c: crudo[c] for c in claves})


def tok(seq: int, origen: Origen = Origen.EJECUTOR, dia: date = HOY) -> int:
    return mod_tokens.componer(origen, dia.timetuple().tm_yday, seq)


class Contador:
    """Generador de tokens del EJECUTOR para las acciones (cuenta cuántos se gastan)."""

    def __init__(self, origen: Origen = Origen.EJECUTOR, desde: int = 500) -> None:
        self.origen, self.seq, self.usados = origen, desde, 0

    def __call__(self) -> int:
        self.seq += 1
        self.usados += 1
        return tok(self.seq, self.origen)


def lote(id_: str = "L1", nivel: str = "10", llenas: int = 100, estado: EstadoLote = EstadoLote.ABIERTO,
         ticker: str = X) -> Lote:
    return Lote(id=id_, strategy_id=f"s-{id_}", estrategia=f"E {id_}", ticker=ticker, direccion="Short", pedidas=llenas,
                llenas=llenas, nivel_stop=D(nivel), estado=estado)


def estado_con(*posiciones: PosicionTicker, ordenes: tuple[Orden, ...] = ()) -> EstadoBot:
    e = EstadoBot(fase=Fase.SOMBRA, dia=HOY)
    for p in posiciones:
        e.posiciones[p.ticker] = p
    for o in ordenes:
        e.ordenes[o.token] = o
        if o.id_das is not None:
            e.id_a_token[o.id_das] = o.token
    return e


def posicion(neta: int, lotes: tuple[Lote, ...] = (), ticker: str = X, estado: EstadoTicker = EstadoTicker.NORMAL,
             neta_das: Optional[int] = None) -> PosicionTicker:
    return PosicionTicker(ticker=ticker, lotes={l.id: l for l in lotes}, neta_fills=neta, neta_das=neta_das, estado=estado)


def orden(token: int, proposito: Proposito, stop: Optional[str], limite: Optional[str], qty: int, id_das: Optional[int],
          estado: EstadoOrden = EstadoOrden.ACCEPTED, lado: Lado = Lado.COMPRA, tipo: TipoOrden = TipoOrden.STOP_LIMITE_PP,
          nivel: Optional[str] = "10", origen: Origen = Origen.EJECUTOR, lote_id: Optional[str] = "L1",
          enviada_en: float = 1000.0, ticker: str = X) -> Orden:
    return Orden(token=token, ticker=ticker, lado=lado, tipo=tipo, qty=qty, precio=None if limite is None else D(limite),
                 stop=None if stop is None else D(stop), ruta=RUTA_STOP, proposito=proposito, lote_id=lote_id,
                 nivel=None if nivel is None else D(nivel), origen=origen, id_das=id_das, estado=estado,
                 lvqty=qty if estado is not EstadoOrden.SENDING else 0, enviada_en=enviada_en)


def principal(qty: int = 100, id_das: Optional[int] = 11, token: int = tok(1), **kw) -> Orden:
    return orden(token, Proposito.STOP_PRINCIPAL, "10.00", "10.30", qty, id_das, **kw)


def emergencia(qty: int = 100, id_das: Optional[int] = 12, token: int = tok(2), **kw) -> Orden:
    return orden(token, Proposito.STOP_EMERGENCIA, "11.30", "16.30", qty, id_das, **kw)


def msg(o: Orden, estado: Optional[EstadoOrden] = None, qty: Optional[int] = None, order_src: Optional[str] = "CMDAPI",
        token: Optional[int] = None, id_das: Optional[int] = None) -> MsgOrden:
    """El %ORDER que DAS devolvería para una orden nuestra (qty/estado pueden diferir de lo que cree el bot)."""
    q = o.qty if qty is None else qty
    est = o.estado if estado is None else estado
    tipo = f"SLP: {o.stop} {o.precio}" if o.tipo is TipoOrden.STOP_LIMITE_PP else "L"
    return MsgOrden(cruda="%ORDER …", id=o.id_das if id_das is None else id_das, token=o.token if token is None else token,
                    ticker=o.ticker, lado=o.lado.value, tipo=tipo, qty=q, lvqty=q if est in (EstadoOrden.ACCEPTED,) else 0,
                    cxlqty=q if est is EstadoOrden.CANCELED else 0, precio=o.precio or D("0"), ruta=o.ruta, estado=est,
                    hora="09:45:00", origoid=0, cuenta="CUENTA_PRUEBA", trader="T", order_src=order_src, tif="DAY+",
                    pref="N/A", watch=False)


def msg_crudo(id_das: int, token: Optional[int], lado: str = "B", tipo: str = "L", qty: int = 100, precio: str = "10.5",
              estado: EstadoOrden = EstadoOrden.ACCEPTED, order_src: Optional[str] = "CMDAPI", ticker: str = X,
              lvqty: Optional[int] = None, cxlqty: int = 0) -> MsgOrden:
    return MsgOrden(cruda="%ORDER …", id=id_das, token=token, ticker=ticker, lado=lado, tipo=tipo, qty=qty,
                    lvqty=qty if lvqty is None else lvqty, cxlqty=cxlqty, precio=D(precio), ruta="SMAT", estado=estado,
                    hora="09:45:00", origoid=0, cuenta="CUENTA_PRUEBA", trader="T", order_src=order_src, tif="DAY+",
                    pref="N/A", watch=False)


def pos_das(neta: int, ticker: str = X, avg: str = "9.50") -> MsgPos:
    return MsgPos(cruda="%POS …", ticker=ticker, tipo=3 if neta < 0 else 2, qty_cruda=abs(neta), neta=neta, avg=D(avg),
                  init_qty=0, init_precio=D("0"), realizado=D("0"), creada="2026/09/25-09:31:00", no_realizado=None,
                  watch=False)


def cot(last: Optional[str] = "9.80", bid: Optional[str] = "9.79", ask: Optional[str] = "9.81") -> Cotizacion:
    return Cotizacion(ticker=X, bid=None if bid is None else D(bid), ask=None if ask is None else D(ask),
                      last=None if last is None else D(last))


def cot_de(c: Optional[Cotizacion]):
    return lambda ticker: c


def ids(ordenes: list[Orden]) -> dict[int, MsgOrden]:
    return {o.id_das: msg(o) for o in ordenes}


def de_tipo(lista, clase) -> list:
    return [a for a in lista if isinstance(a, clase)]


def casos(ds: list[Discrepancia]) -> list[tuple[str, int]]:
    return [(d.ticker, d.caso) for d in ds]


def corto_conocido(neta: int = -100) -> PosicionTicker:
    return posicion(neta, (lote(llenas=-neta),))


# ── los 6 casos (R-C-10 + R-K-02 + M7), uno por fila ─────────────────────
def test_caso_1_coincide_no_hace_nada(cfg):
    """R-C-10 (1): posición conocida con el principal y la emergencia que calcula el bot → nada."""
    p, e = principal(), emergencia()
    estado = estado_con(corto_conocido(), ordenes=(p, e))
    ds = comparar(estado, {X: pos_das(-100)}, ids([p, e]), HOY, cfg)
    assert casos(ds) == [(X, CASO_COINCIDE)]
    tokens = Contador()
    assert acciones(ds, estado, cot_de(cot()), cfg, tokens, HORA, RUTA_STOP) == []
    assert tokens.usados == 0


def test_caso_2_stop_difiere_se_ajusta_con_plan(cfg):
    """R-C-10 (2): la emergencia en DAS lleva 150 (se quedó vieja) → manda el cálculo de AHORA: Reemplazar a 100."""
    p, e = principal(), emergencia(qty=150)
    estado = estado_con(corto_conocido(), ordenes=(p, e))
    ds = comparar(estado, {X: pos_das(-100)}, ids([p, e]), HOY, cfg)
    assert casos(ds) == [(X, CASO_STOP_DIFIERE)]
    acc = acciones(ds, estado, cot_de(cot()), cfg, Contador(), HORA, RUTA_STOP)
    reemplazos = de_tipo(acc, Reemplazar)
    assert [(r.id_das, r.qty, r.stop, r.precio) for r in reemplazos] == [(12, 100, D("11.30"), D("16.30"))]
    assert reemplazos[0].serie == "stops:X".replace("X", X)
    assert not de_tipo(acc, EnviarOrden)


def test_caso_3_sin_stop_repone_el_par_y_avisa(cfg):
    """R-C-10 (3): posición conocida SIN stop en DAS (halt que cruzó días, 2f.4) → principal + emergencia nuevos + aviso."""
    estado = estado_con(corto_conocido())
    ds = comparar(estado, {X: pos_das(-100)}, {}, HOY, cfg)
    assert casos(ds) == [(X, CASO_SIN_STOP)]
    acc = acciones(ds, estado, cot_de(cot()), cfg, Contador(), HORA, RUTA_STOP)
    nuevas = [a.orden for a in de_tipo(acc, EnviarOrden)]
    assert [(o.proposito, o.stop, o.precio, o.qty, o.lado) for o in nuevas] == [
        (Proposito.STOP_PRINCIPAL, D("10.00"), D("10.30"), 100, Lado.COMPRA),
        (Proposito.STOP_EMERGENCIA, D("11.30"), D("16.30"), 100, Lado.COMPRA)]
    avisos = de_tipo(acc, Avisar)
    assert [(a.nivel, a.grupo) for a in avisos] == [(Nivel.AVISO, Grupo.B)] and "R-C-10 (3)" in avisos[0].texto


def test_caso_4_posicion_desconocida_proteccion_aviso3_y_pausa_global(cfg):
    """R-C-10 (4) + R-M-03: posición que no está en ningún diario → protección al 25 %, aviso 3 y pausa global hasta /sigue."""
    estado = estado_con()
    ds = comparar(estado, {X: pos_das(-200)}, {}, HOY, cfg)
    assert casos(ds) == [(X, CASO_AJENA)] and ds[0].descubiertas == 200 and ds[0].neta_das == -200
    acc = acciones(ds, estado, cot_de(cot(last="8.00")), cfg, Contador(), HORA, RUTA_STOP)
    pausa = de_tipo(acc, Anotar)
    assert len(pausa) == 1 and pausa[0].tipo == "pausa" and "ticker" not in pausa[0].datos   # sin ticker = pausa GLOBAL
    assert pausa[0].datos["pausa_global"] is True and pausa[0].datos["regla"] == "R-M-03"
    assert estado.pausa_global is True
    proteccion = [a.orden for a in de_tipo(acc, EnviarOrden)]
    assert len(proteccion) == 1
    o = proteccion[0]
    assert (o.lado, o.tipo, o.qty, o.proposito, o.lote_id) == (Lado.COMPRA, TipoOrden.STOP_LIMITE_PP, 200,
                                                               Proposito.STOP_PROTECCION, None)
    assert o.stop == D("10.00") and o.precio == D("10.30") and en_tick(o.stop) and en_tick(o.precio)   # 8 · 1,25 y +3 %
    assert de_tipo(acc, EnviarOrden)[0].serie is None   # un InvalidarSerie de un fill no la descarta
    avisos = de_tipo(acc, Avisar)
    assert [a.nivel for a in avisos] == [Nivel.MAXIMO] and "/sigue" in avisos[0].texto
    assert acc.index(pausa[0]) < acc.index(de_tipo(acc, EnviarOrden)[0]) < acc.index(avisos[0])


def test_caso_5_diario_abierta_das_plana_cierra_lotes(cfg):
    """R-C-10 (5): el diario tiene XYZ abierta y DAS la da plana → lotes CERRADO, neta 0, stops cancelados, aviso 2."""
    p, e = principal(), emergencia()
    pos = corto_conocido()
    estado = estado_con(pos, ordenes=(p, e))
    ds = comparar(estado, {X: pos_das(0)}, ids([p, e]), HOY, cfg)
    assert casos(ds) == [(X, CASO_CERRADA_EN_DAS)]
    acc = acciones(ds, estado, cot_de(cot()), cfg, Contador(), HORA, RUTA_STOP)
    assert acc[0] == Anotar("lote", {"lote_id": "L1", "ticker": X, "estado": "cerrado", "regla": "R-C-10 (5)"})
    assert acc[1].tipo == "discrepancia" and acc[1].datos["neta_das"] == 0 and acc[1].datos["neta_fills"] == -100
    assert sorted(c.id_das for c in de_tipo(acc, Cancelar)) == [11, 12]   # R-C-11 (2): ningún stop de compra con la cuenta plana
    assert [a.nivel for a in de_tipo(acc, Avisar)] == [Nivel.AVISO]
    assert pos.lotes["L1"].estado is EstadoLote.CERRADO and pos.neta_fills == 0 and pos.neta_das == 0


def test_caso_6_das_manda_y_se_recalculan_los_stops(cfg):
    """M7 / corrección 2: neta de fills −100 y DAS −60 → neta_fills := −60, anotado, aviso 2 y stops a 60."""
    p, e = principal(), emergencia()
    pos = corto_conocido()
    estado = estado_con(pos, ordenes=(p, e))
    ds = comparar(estado, {X: pos_das(-60)}, ids([p, e]), HOY, cfg)
    assert casos(ds) == [(X, CASO_NETA_DISTINTA)] and (ds[0].neta_fills, ds[0].neta_das) == (-100, -60)
    acc = acciones(ds, estado, cot_de(cot()), cfg, Contador(), HORA, RUTA_STOP)
    assert acc[0] == Anotar("discrepancia", {"ticker": X, "caso": 6, "neta_fills": -100, "neta_das": -60,
                                             "detalle": ds[0].detalle, "regla": "M7 / corrección 2: manda DAS"})
    assert isinstance(acc[1], Avisar) and acc[1].nivel is Nivel.AVISO
    assert sorted((r.id_das, r.qty) for r in de_tipo(acc, Reemplazar)) == [(11, 60), (12, 60)]
    assert pos.neta_fills == -60 and pos.neta_das == -60
    assert not de_tipo(acc, Consultar)   # la precondición de plan ya cuadra: no se pide GET POSITIONS


@pytest.mark.parametrize("neta_das,esperado", [
    pytest.param(-100, CASO_COINCIDE, id="R-C-10-1"),
    pytest.param(0, CASO_CERRADA_EN_DAS, id="R-C-10-5"),
    pytest.param(-60, CASO_NETA_DISTINTA, id="M7-caso-6"),
    pytest.param(-140, CASO_NETA_DISTINTA, id="M7-caso-6-DAS-mas-corta"),
])
def test_tabla_de_casos_por_neta(cfg, neta_das, esperado):
    p, e = principal(), emergencia()
    ds = comparar(estado_con(corto_conocido(), ordenes=(p, e)), {X: pos_das(neta_das)}, ids([p, e]), HOY, cfg)
    assert casos(ds) == [(X, esperado)]


# ── R-K-02: órdenes ajenas (orderSrc ≠ CMDAPI o token no nuestro HOY) ────
@pytest.mark.parametrize("order_src,token", [
    pytest.param("Montage", tok(7), id="R-K-02-orderSrc-Montage-con-token-nuestro"),
    pytest.param("Hotkey", None, id="R-K-02-orderSrc-Hotkey"),
    pytest.param("CMDAPI", tok(7, dia=AYER), id="R-K-02-token-de-AYER-2f5"),
    pytest.param(None, tok(7, dia=AYER), id="R-K-02-token-de-AYER-sin-orderSrc-15-campos"),
    pytest.param("CMDAPI", 123, id="R-K-02-token-de-otro-esquema"),
    pytest.param(None, None, id="R-K-02-sin-token-ni-orderSrc"),
])
def test_orden_ajena_es_caso_4_pausa_y_aviso(cfg, order_src, token):
    p, e = principal(), emergencia()
    ajena = msg_crudo(90, token, lado="B", tipo="L", qty=50, precio="9.90", order_src=order_src)
    assert es_ajena(ajena, HOY)
    estado = estado_con(corto_conocido(), ordenes=(p, e))
    ord_das = {**ids([p, e]), 90: ajena}
    ds = comparar(estado, {X: pos_das(-100)}, ord_das, HOY, cfg)
    assert casos(ds) == [(X, CASO_AJENA), (X, CASO_COINCIDE)]
    assert ds[0].descubiertas == 0 and [m.id for m in ds[0].ajenas] == [90]
    acc = acciones(ds, estado, cot_de(cot()), cfg, Contador(), HORA, RUTA_STOP)
    assert not de_tipo(acc, EnviarOrden)   # la posición es nuestra y está cubierta: no se protege, no se deshace (R-K-02)
    assert [a.nivel for a in de_tipo(acc, Avisar)] == [Nivel.MAXIMO] and estado.pausa_global is True
    assert 90 in estado.ordenes_ajenas
    # la misma ajena en el barrido siguiente ya no es nueva: ni otro aviso ni otra pausa
    assert casos(comparar(estado, {X: pos_das(-100)}, ord_das, HOY, cfg)) == [(X, CASO_COINCIDE)]


def test_E2c_01_ajenas_tratadas_se_anotan_siempre_y_un_reinicio_no_vuelve_a_pausar(cfg):
    """E2c-01: el caso 4 anota SIEMPRE «ajenas_tratadas» {ticker, ids}, también con la pausa ya puesta.

    Con esos ids repuestos en `estado.ordenes_ajenas` (lo que hará `diario.reconstruir`) y un /sigue, el mismo
    volcado del LOGIN tras un reinicio ya no da caso 4 ni vuelve a pausar.
    """
    p, e = principal(), emergencia()
    ajena = msg_crudo(90, None, lado="B", tipo="L", qty=50, precio="9.90", order_src="Montage",
                      estado=EstadoOrden.EXECUTED, lvqty=0)
    otra = msg_crudo(93, None, lado="B", tipo="L", qty=10, precio="9.90", order_src="Hotkey", ticker="ABC")
    ord_das = {**ids([p, e]), 90: ajena}
    estado = estado_con(corto_conocido(), ordenes=(p, e))
    acc = acciones(comparar(estado, {X: pos_das(-100)}, ord_das, HOY, cfg), estado, cot_de(cot()), cfg, Contador(),
                   HORA, RUTA_STOP)
    tratadas = [a for a in de_tipo(acc, Anotar) if a.tipo == rc.ANOTACION_AJENAS]
    assert [a.datos for a in tratadas] == [{"ticker": X, "ids": [90], "regla": "R-K-02 / E2c-01"}]
    assert estado.pausa_global is True
    # otra ajena nueva con la pausa YA puesta: se anota igual (antes solo iba dentro del registro «pausa»)
    acc2 = acciones(comparar(estado, {X: pos_das(-100), "ABC": pos_das(0, ticker="ABC")}, {**ord_das, 93: otra}, HOY,
                             cfg), estado, cot_de(cot()), cfg, Contador(), HORA, RUTA_STOP)
    assert [a.datos["ids"] for a in de_tipo(acc2, Anotar) if a.tipo == rc.ANOTACION_AJENAS] == [[93]]
    assert not [a for a in de_tipo(acc2, Anotar) if a.tipo == "pausa"]
    json.dumps([a.datos for a in de_tipo(acc + acc2, Anotar) if a.tipo == rc.ANOTACION_AJENAS])
    # reinicio: el diario repone los ids tratados y Jaume ya dio /sigue
    reiniciado = estado_con(corto_conocido(), ordenes=(p, e))
    for a in de_tipo(acc + acc2, Anotar):
        if a.tipo == rc.ANOTACION_AJENAS:
            for i in a.datos["ids"]:
                reiniciado.ordenes_ajenas[i] = None   # type: ignore[assignment]  # la clave es lo que cuenta
    ds = comparar(reiniciado, {X: pos_das(-100)}, ord_das, HOY, cfg)
    assert CASO_AJENA not in [d.caso for d in ds]
    acciones(ds, reiniciado, cot_de(cot()), cfg, Contador(), HORA, RUTA_STOP)
    assert reiniciado.pausa_global is False


def test_E2c_03_desconocida_larga_avisa_vender_a_mano(cfg):
    """E2c-03: posición DESCONOCIDA LARGA (p. ej. saltaron el stop manual y nuestra protección) → aviso 3 «VENDER A MANO».

    La limpieza R-C-11 solo corre en posiciones conocidas: sin este aviso el exceso largo no lo vendería nadie. Se sigue
    poniendo la protección de VENTA (no se deshace lo humano).
    """
    estado = estado_con()
    ds = comparar(estado, {X: pos_das(150)}, {}, HOY, cfg)
    assert casos(ds) == [(X, CASO_AJENA)]
    acc = acciones(ds, estado, cot_de(cot(last="8.00")), cfg, Contador(), HORA, RUTA_STOP)
    assert [(a.orden.lado, a.orden.qty) for a in de_tipo(acc, EnviarOrden)] == [(Lado.VENTA, 150)]
    vender = [a for a in de_tipo(acc, Avisar) if a.clave == f"desconocida_larga:{X}"]
    assert len(vender) == 1 and vender[0].nivel is Nivel.MAXIMO and "VENDER A MANO" in vender[0].texto
    # una desconocida CORTA no lleva ese aviso
    corta = estado_con()
    acc_c = acciones(comparar(corta, {X: pos_das(-150)}, {}, HOY, cfg), corta, cot_de(cot()), cfg, Contador(), HORA,
                     RUTA_STOP)
    assert not [a for a in de_tipo(acc_c, Avisar) if (a.clave or "").startswith("desconocida_larga")]


def test_D2_08_aviso_de_ajena_escapa_el_texto_de_das(cfg):
    """D2-08: el detalle lleva el tipo y el orderSrc que manda DAS: un «<» no puede romper el HTML de Telegram."""
    p, e = principal(), emergencia()
    ajena = msg_crudo(90, None, tipo="<L&>", order_src="Mont<age>")
    estado = estado_con(corto_conocido(), ordenes=(p, e))
    acc = acciones(comparar(estado, {X: pos_das(-100)}, {**ids([p, e]), 90: ajena}, HOY, cfg), estado, cot_de(cot()),
                   cfg, Contador(), HORA, RUTA_STOP)
    texto = next(a for a in de_tipo(acc, Avisar) if a.clave == f"ajena:{X}").texto
    assert "&lt;L&amp;&gt;" in texto and "Mont&lt;age&gt;" in texto and "<L&>" not in texto


def test_A_06_comandos_del_barrido_salen_de_protocolo():
    from app.bot_das import protocolo
    assert rc.COMANDOS_BARRIDO == tuple(protocolo.cmd_get(n) for n in ("POSITIONS", "ORDERS", "BP", "LOCATES"))
    assert rc.COMANDO_TRADES == protocolo.cmd_get("TRADES")


@pytest.mark.parametrize("estado_ajena,cxl,lv,cuenta", [
    pytest.param(EstadoOrden.CANCELED, 50, 0, False, id="R-M-03-cancelada-sin-ejecutar-no-afecta"),
    pytest.param(EstadoOrden.REJECTED, 0, 0, False, id="R-M-03-rechazada-no-afecta"),
    pytest.param(EstadoOrden.CANCELED, 20, 0, True, id="R-M-03-cancelada-con-30-ejecutadas-si"),
    pytest.param(EstadoOrden.EXECUTED, 0, 0, True, id="R-M-03-ejecutada-si"),
    pytest.param(EstadoOrden.HOLD, 0, 50, True, id="R-M-03-viva-en-hold-si"),
])
def test_ajena_solo_cuenta_si_afecta_a_la_posicion(cfg, estado_ajena, cxl, lv, cuenta):
    p, e = principal(), emergencia()
    ajena = msg_crudo(91, None, qty=50, estado=estado_ajena, order_src="Montage", lvqty=lv, cxlqty=cxl)
    ds = comparar(estado_con(corto_conocido(), ordenes=(p, e)), {X: pos_das(-100)}, {**ids([p, e]), 91: ajena}, HOY, cfg)
    assert (CASO_AJENA in [d.caso for d in ds]) is cuenta


def test_manual_que_cubre_parte_es_caso_4_y_6(cfg):
    """R-K-02 + M7: el humano recompra 40 a mano → aviso 3 + pausa y DAS manda sobre la neta (stops a 60)."""
    p, e = principal(), emergencia()
    manual = msg_crudo(92, None, qty=40, estado=EstadoOrden.EXECUTED, order_src="Montage", lvqty=0)
    estado = estado_con(corto_conocido(), ordenes=(p, e))
    ds = comparar(estado, {X: pos_das(-60)}, {**ids([p, e]), 92: manual}, HOY, cfg)
    assert casos(ds) == [(X, CASO_AJENA), (X, CASO_NETA_DISTINTA)]
    acc = acciones(ds, estado, cot_de(cot()), cfg, Contador(), HORA, RUTA_STOP)
    assert estado.pausa_global and estado.posiciones[X].neta_fills == -60
    assert sorted((r.id_das, r.qty) for r in de_tipo(acc, Reemplazar)) == [(11, 60), (12, 60)]


# ── riesgo 8: gracia tras un fill y «sin información» ─────────────────────
@pytest.mark.parametrize("ahora,esperado", [
    pytest.param(1001.0, [], id="riesgo-8-1s-tras-el-fill-DAS-va-por-detras-no-se-toca"),
    pytest.param(1001.999, [], id="riesgo-8-justo-antes-de-la-gracia"),
    pytest.param(1002.0, [(X, CASO_NETA_DISTINTA)], id="riesgo-8-pasada-la-gracia-manda-DAS"),
    pytest.param(None, [(X, CASO_NETA_DISTINTA)], id="sin-ahora-no-hay-gracia-contrato-3-24"),
])
def test_gracia_tras_fill(cfg, ahora, esperado):
    p, e = principal(qty=100), emergencia(qty=100)
    estado = estado_con(corto_conocido(-150), ordenes=(p, e))
    estado.ultimo_fill_en = 1000.0
    assert casos(comparar(estado, {X: pos_das(-100)}, ids([p, e]), HOY, cfg, ahora=ahora)) == esperado


def test_ticker_ausente_del_volcado_es_sin_informacion(cfg):
    """Volcado a medias (BP empujado, §5.11): una posición conocida que DAS no lista NO es «plana» (nunca caso 5)."""
    p, e = principal(), emergencia()
    estado = estado_con(corto_conocido(), ordenes=(p, e))
    assert comparar(estado, {}, {}, HOY, cfg) == []


def test_volcado_sin_ordenes_no_duplica_stops(cfg):
    """Riesgo 11: si DAS no lista nuestras órdenes (volcado a medias), se dan por vivas: caso 1, cero órdenes nuevas."""
    p, e = principal(), emergencia()
    estado = estado_con(corto_conocido(), ordenes=(p, e))
    ds = comparar(estado, {X: pos_das(-100)}, {}, HOY, cfg)
    assert casos(ds) == [(X, CASO_COINCIDE)]


def test_das_contradice_nuestra_vista_el_stop_cancelado_se_repone(cfg):
    """R-C-04: el bot cree viva la emergencia pero DAS la lista CANCELADA (halt, rechazo tardío) → caso 3 y se repone."""
    p, e = principal(), emergencia()
    estado = estado_con(corto_conocido(), ordenes=(p, e))
    ord_das = {11: msg(p), 12: msg(e, estado=EstadoOrden.CANCELED)}
    ds = comparar(estado, {X: pos_das(-100)}, ord_das, HOY, cfg)
    assert casos(ds) == [(X, CASO_SIN_STOP)]
    nuevas = [a.orden for a in de_tipo(acciones(ds, estado, cot_de(cot()), cfg, Contador(), HORA, RUTA_STOP), EnviarOrden)]
    assert [(o.proposito, o.qty) for o in nuevas] == [(Proposito.STOP_EMERGENCIA, 100)]


@pytest.mark.parametrize("ahora,esperado", [
    pytest.param(1003.0, CASO_COINCIDE, id="riesgo-3-sending-reciente-sin-eco-se-da-por-viva"),
    pytest.param(1006.0, CASO_SIN_STOP, id="riesgo-3-sending-sin-eco-pasado-SIN_ECO_S-no-salio"),
    pytest.param(None, CASO_COINCIDE, id="riesgo-3-sin-ahora-se-da-por-viva"),
])
def test_orden_sending_sin_eco(cfg, ahora, esperado):
    p = principal(id_das=None, estado=EstadoOrden.SENDING, enviada_en=1000.0)
    e = emergencia(id_das=None, estado=EstadoOrden.SENDING, enviada_en=1000.0)
    estado = estado_con(corto_conocido(), ordenes=(p, e))
    assert casos(comparar(estado, {X: pos_das(-100)}, {}, HOY, cfg, ahora=ahora)) == [(X, esperado)]


# ── F13: adopción de las órdenes del vigilante ───────────────────────────
def test_adopta_las_ordenes_del_vigilante_sin_duplicar(cfg):
    """F13 / R-C-07 neteo: el vigilante repuso el par; el ejecutor lo ADOPTA (0 órdenes nuevas) y lo registra."""
    pv = principal(token=tok(1, Origen.VIGILANTE), id_das=31, origen=Origen.VIGILANTE)
    ev = emergencia(token=tok(2, Origen.VIGILANTE), id_das=32, origen=Origen.VIGILANTE)
    estado = estado_con(corto_conocido())
    ds = comparar(estado, {X: pos_das(-100)}, ids([pv, ev]), HOY, cfg)
    assert casos(ds) == [(X, CASO_COINCIDE)]
    tokens = Contador()
    assert acciones(ds, estado, cot_de(cot()), cfg, tokens, HORA, RUTA_STOP) == [] and tokens.usados == 0
    adoptadas = estado.ordenes[tok(2, Origen.VIGILANTE)]
    assert adoptadas.origen is Origen.VIGILANTE and adoptadas.id_das == 32 and estado.id_a_token[32] == tok(2, Origen.VIGILANTE)
    assert adoptadas.stop == D("11.30") and adoptadas.precio == D("16.30") and adoptadas.tipo is TipoOrden.STOP_LIMITE_PP
    # idempotente: el siguiente barrido sigue siendo caso 1 y no cambia nada
    assert casos(comparar(estado, {X: pos_das(-100)}, ids([pv, ev]), HOY, cfg)) == [(X, CASO_COINCIDE)]


def test_dos_emergencias_la_mas_nueva_sobra(cfg):
    """R-C-07 plan B: ejecutor y vigilante pusieron la emergencia a la vez → caso 2 y se cancela la MÁS NUEVA (id mayor)."""
    p, e = principal(), emergencia(id_das=12)
    ev = emergencia(token=tok(2, Origen.VIGILANTE), id_das=40, origen=Origen.VIGILANTE)
    estado = estado_con(corto_conocido(), ordenes=(p, e))
    ds = comparar(estado, {X: pos_das(-100)}, ids([p, e, ev]), HOY, cfg)
    assert casos(ds) == [(X, CASO_STOP_DIFIERE)]
    acc = acciones(ds, estado, cot_de(cot()), cfg, Contador(), HORA, RUTA_STOP)
    assert [c.id_das for c in de_tipo(acc, Cancelar)] == [40] and not de_tipo(acc, EnviarOrden)


# ── casos límite de las acciones ─────────────────────────────────────────
def test_caso_6_a_larga_vende_solo_el_exceso(cfg):
    """R-C-11 (b) por reconciliación: el diario cree −100 y DAS dice +20 → CancelarTicker y vende 20, JAMÁS 100.

    D2a-04 (decisión del director): la venta sale a bid · (1 − 1 %) redondeado abajo (vendible), no al bid exacto:
    9,79 · 0,99 = 9,6921 → 9,69.
    """
    p, e = principal(), emergencia()
    estado = estado_con(corto_conocido(), ordenes=(p, e))
    ds = comparar(estado, {X: pos_das(20)}, ids([p, e]), HOY, cfg)
    assert casos(ds) == [(X, CASO_NETA_DISTINTA)]
    acc = acciones(ds, estado, cot_de(cot(bid="9.79")), cfg, Contador(), HORA, RUTA_STOP)
    assert isinstance(acc[2], InvalidarSerie) and isinstance(acc[3], CancelarTicker)
    ventas = [a.orden for a in de_tipo(acc, EnviarOrden)]
    assert [(o.lado, o.qty, o.precio, o.proposito) for o in ventas] == [(Lado.VENTA, 20, D("9.69"), Proposito.VENTA_EXCESO)]


def test_larga_conocida_con_venta_en_marcha_no_repite(cfg):
    """R-C-11 (b): si la venta del exceso ya está viva, el barrido no manda otra."""
    venta = orden(tok(9), Proposito.VENTA_EXCESO, None, "9.79", 20, 50, lado=Lado.VENTA, tipo=TipoOrden.LIMITE, nivel=None)
    pos = posicion(20, (lote(llenas=100),), neta_das=20)
    estado = estado_con(pos, ordenes=(venta,))
    ds = comparar(estado, {X: pos_das(20)}, ids([venta]), HOY, cfg)
    assert casos(ds) == [(X, CASO_COINCIDE)]


def test_larga_conocida_sin_venta_pasa_por_la_limpieza(cfg):
    """Riesgo 6: el barrido es la red de control del evento de fill: larga sin venta en marcha → limpieza (vende 20)."""
    estado = estado_con(posicion(20, (lote(llenas=100),)))
    ds = comparar(estado, {X: pos_das(20)}, {}, HOY, cfg)
    assert casos(ds) == [(X, CASO_STOP_DIFIERE)]
    acc = acciones(ds, estado, cot_de(cot(bid="9.79")), cfg, Contador(), HORA, RUTA_STOP)
    assert [(a.orden.lado, a.orden.qty) for a in de_tipo(acc, EnviarOrden)] == [(Lado.VENTA, 20)]


@pytest.mark.parametrize("proposito, lado", [
    (Proposito.ENTRADA_AGREGAR, Lado.VENTA), (Proposito.ENTRADA_CRUCE, Lado.VENTA),
    (Proposito.ENTRADA_AGREGAR, Lado.CORTO), (Proposito.CIERRE_HUMANO, Lado.VENTA),
], ids=["R3-REC-1-entrada_agregar", "R3-REC-1-entrada_cruce", "R3-REC-1-entrada_corta", "R3-REC-1-otra_venta"])
def test_R3_REC_1_larga_con_solo_una_entrada_viva_pasa_por_la_limpieza(cfg, proposito, lado):
    """R3-REC-1: larga 20 y una entrada viva de 100 → la entrada NO es «la venta del exceso en marcha»: el barrido
    llama a la limpieza (stops.limpieza_tras_fill_stop) igual que sin nada vivo y vende 20 como VENTA_EXCESO."""
    entrada = orden(tok(9), proposito, None, "9.90", 100, 70, lado=lado, tipo=TipoOrden.LIMITE, nivel=None)
    assert rc._vendiendo([entrada], X) == 0
    estado = estado_con(posicion(20, (lote(llenas=100),)), ordenes=(entrada,))
    ds = comparar(estado, {X: pos_das(20)}, ids([entrada]), HOY, cfg)
    assert casos(ds) == [(X, CASO_STOP_DIFIERE)]
    acc = acciones(ds, estado, cot_de(cot(bid="9.79")), cfg, Contador(), HORA, RUTA_STOP)
    ventas = [a.orden for a in de_tipo(acc, EnviarOrden)]
    assert [(o.lado, o.qty, o.proposito) for o in ventas] == [(Lado.VENTA, 20, Proposito.VENTA_EXCESO)]
    estado_vacio = estado_con(posicion(20, (lote(llenas=100),)))
    sin_nada = acciones(comparar(estado_vacio, {X: pos_das(20)}, {}, HOY, cfg), estado_vacio,
                        cot_de(cot(bid="9.79")), cfg, Contador(), HORA, RUTA_STOP)
    assert ([(a.orden.lado, a.orden.qty, a.orden.precio) for a in de_tipo(acc, EnviarOrden)]
            == [(a.orden.lado, a.orden.qty, a.orden.precio) for a in de_tipo(sin_nada, EnviarOrden)])
    assert de_tipo(acc, CancelarTicker) or [c.id_das for c in de_tipo(acc, Cancelar)] == [70], \
        "la entrada viva se retira antes de vender el exceso"


def test_R3_REC_1_vendiendo_solo_cuenta_venta_exceso_viva():
    """R3-REC-1: _vendiendo suma SOLO las VENTA_EXCESO vivas (qty viva), nunca entradas ni otras ventas ni muertas."""
    exceso = orden(tok(9), Proposito.VENTA_EXCESO, None, "9.79", 20, 50, lado=Lado.VENTA, tipo=TipoOrden.LIMITE, nivel=None)
    muerta = orden(tok(10), Proposito.VENTA_EXCESO, None, "9.79", 30, 51, lado=Lado.VENTA, tipo=TipoOrden.LIMITE,
                   nivel=None, estado=EstadoOrden.CANCELED)
    entrada = orden(tok(11), Proposito.ENTRADA_CRUCE, None, "9.90", 100, 52, lado=Lado.VENTA, tipo=TipoOrden.LIMITE,
                    nivel=None)
    otra = orden(tok(12), Proposito.CIERRE_HUMANO, None, "9.70", 40, 53, lado=Lado.VENTA, tipo=TipoOrden.LIMITE, nivel=None)
    assert rc._vendiendo([exceso, muerta, entrada, otra], X) == 20
    assert rc._vendiendo([exceso], "OTRO") == 0


def test_ticker_plano_con_proteccion_huerfana_se_cancela(cfg):
    """R-C-11 (2): el humano cerró la posición desconocida y quedó viva nuestra protección → se cancela (compraría en largo)."""
    prot = orden(tok(5), Proposito.STOP_PROTECCION, "10.00", "10.30", 200, 60, nivel="10.00", lote_id=None)
    estado = estado_con(ordenes=(prot,))
    ds = comparar(estado, {X: pos_das(0)}, ids([prot]), HOY, cfg)
    assert casos(ds) == [(X, CASO_STOP_DIFIERE)]
    acc = acciones(ds, estado, cot_de(cot()), cfg, Contador(), HORA, RUTA_STOP)
    assert [(c.id_das, c.token) for c in acc] == [(60, tok(5))]


def test_desconocida_ya_protegida_es_idempotente(cfg):
    """Riesgo 11: la protección puesta (aún Sending) cubre la posición desconocida: el barrido siguiente no pone otra."""
    estado = estado_con()
    ds = comparar(estado, {X: pos_das(-200)}, {}, HOY, cfg)
    acc = acciones(ds, estado, cot_de(cot(last="8.00")), cfg, Contador(), HORA, RUTA_STOP)
    enviada = de_tipo(acc, EnviarOrden)[0].orden
    estado.ordenes[enviada.token] = Orden(token=enviada.token, ticker=X, lado=enviada.lado, tipo=enviada.tipo,
                                          qty=enviada.qty, precio=enviada.precio, stop=enviada.stop, ruta=enviada.ruta,
                                          proposito=enviada.proposito, lote_id=None, nivel=enviada.nivel,
                                          origen=Origen.EJECUTOR, estado=EstadoOrden.SENDING, enviada_en=2000.0)
    segunda = comparar(estado, {X: pos_das(-200)}, {}, HOY, cfg, ahora=2001.0)
    assert casos(segunda) == [(X, CASO_COINCIDE)]
    assert acciones(segunda, estado, cot_de(cot()), cfg, Contador(), HORA, RUTA_STOP) == []


@pytest.mark.parametrize("cotizacion,avg,esperado_disparo", [
    pytest.param(cot(last=None, bid="7.90", ask="8.00"), "5.00", D("10.00"), id="R-C-10-4-sin-last-usa-el-ask-si-corta"),
    pytest.param(None, "8.00", D("10.00"), id="R-C-10-4-sin-cotizacion-usa-el-precio-medio-de-DAS"),
])
def test_proteccion_precio_de_referencia(cfg, cotizacion, avg, esperado_disparo):
    estado = estado_con()
    ds = comparar(estado, {X: pos_das(-100, avg=avg)}, {}, HOY, cfg)
    acc = acciones(ds, estado, cot_de(cotizacion), cfg, Contador(), HORA, RUTA_STOP)
    assert de_tipo(acc, EnviarOrden)[0].orden.stop == esperado_disparo


def test_proteccion_sin_ningun_precio_avisa_para_ponerla_a_mano(cfg):
    estado = estado_con()
    ds = comparar(estado, {X: pos_das(-100, avg="0")}, {}, HOY, cfg)
    acc = acciones(ds, estado, cot_de(None), cfg, Contador(), HORA, RUTA_STOP)
    assert not de_tipo(acc, EnviarOrden)
    assert any(a.nivel is Nivel.MAXIMO and "A MANO" in a.texto for a in de_tipo(acc, Avisar))


def test_desconocida_larga_proteccion_de_venta_por_debajo(cfg):
    """R-C-10 (4): posición LARGA desconocida → STOPLMTP de VENTA un 25 % por debajo."""
    estado = estado_con()
    ds = comparar(estado, {X: pos_das(100)}, {}, HOY, cfg)
    acc = acciones(ds, estado, cot_de(cot(last="8.00")), cfg, Contador(), HORA, RUTA_STOP)
    o = de_tipo(acc, EnviarOrden)[0].orden
    assert (o.lado, o.stop, o.precio, o.qty) == (Lado.VENTA, D("6.00"), D("5.82"), 100)


def test_pausa_global_se_anota_una_sola_vez(cfg):
    estado = estado_con()
    ds = comparar(estado, {X: pos_das(-100), "ABC": pos_das(-50, ticker="ABC")}, {}, HOY, cfg)
    acc = acciones(ds, estado, cot_de(cot()), cfg, Contador(), HORA, RUTA_STOP)
    assert len([a for a in de_tipo(acc, Anotar) if a.tipo == "pausa"]) == 1
    assert len(de_tipo(acc, EnviarOrden)) == 2


def test_cisne_negro_no_se_repone(cfg):
    """R-G-03: en BS no se repone lo que DAS cancele: caso 1 y cero acciones."""
    estado = estado_con(posicion(-100, (lote(),), estado=EstadoTicker.BS))
    ds = comparar(estado, {X: pos_das(-100)}, {}, HOY, cfg)
    assert casos(ds) == [(X, CASO_COINCIDE)] and "R-G-03" in ds[0].detalle
    assert acciones(ds, estado, cot_de(cot()), cfg, Contador(), HORA, RUTA_STOP) == []


def test_lotes_sin_nivel_protegen_y_avisan(cfg):
    """A12 + R-C-10: corto conocido cuyos lotes no tienen nivel válido → aviso 3 (stops) y protección para no quedar desnudo."""
    malo = Lote(id="L1", strategy_id="s", estrategia="E", ticker=X, direccion="Short", pedidas=100, llenas=100,
                nivel_stop=None, estado=EstadoLote.ABIERTO)
    estado = estado_con(posicion(-100, (malo,)))
    ds = comparar(estado, {X: pos_das(-100)}, {}, HOY, cfg)
    assert casos(ds) == [(X, CASO_SIN_STOP)]
    acc = acciones(ds, estado, cot_de(cot(last="8.00")), cfg, Contador(), HORA, RUTA_STOP)
    assert [a.orden.proposito for a in de_tipo(acc, EnviarOrden)] == [Proposito.STOP_PROTECCION]
    assert Nivel.MAXIMO in [a.nivel for a in de_tipo(acc, Avisar)]


def test_discrepancia_caso_invalido():
    with pytest.raises(ValueError):
        Discrepancia(X, 7, "no existe")


def test_comparar_no_muta_y_no_depende_del_orden(cfg):
    """`comparar` es PURA y el resultado no depende del orden en que llegan las órdenes (riesgo 8: orden no documentado)."""
    p, e = principal(), emergencia(qty=150)
    ev = emergencia(token=tok(2, Origen.VIGILANTE), id_das=40, origen=Origen.VIGILANTE)
    ajena = msg_crudo(90, None, order_src="Montage", ticker="ABC")
    estado = estado_con(corto_conocido(), ordenes=(p, e))
    base = [msg(p), msg(e), msg(ev), ajena]
    referencia = None
    for permutacion in itertools.permutations(base):
        antes = (dict(estado.ordenes), estado.pausa_global, dict(estado.ordenes_ajenas), estado.posiciones[X].neta_fills)
        ds = comparar(estado, {X: pos_das(-100), "ABC": pos_das(0, ticker="ABC")}, {m.id: m for m in permutacion}, HOY, cfg)
        assert (dict(estado.ordenes), estado.pausa_global, dict(estado.ordenes_ajenas),
                estado.posiciones[X].neta_fills) == antes
        referencia = referencia or ds
        assert ds == referencia


def test_acciones_nunca_float(cfg):
    estado = estado_con(corto_conocido())
    ds = comparar(estado, {X: pos_das(-100), "ABC": pos_das(-30, ticker="ABC")}, {}, HOY, cfg)
    for a in de_tipo(acciones(ds, estado, cot_de(cot()), cfg, Contador(), HORA, RUTA_STOP), EnviarOrden):
        o = a.orden
        assert type(o.qty) is int and all(v is None or type(v) is Decimal for v in (o.precio, o.stop, o.nivel))


# ── piezas compartidas ───────────────────────────────────────────────────
@pytest.mark.parametrize("order_src,token,ajena", [
    pytest.param("CMDAPI", tok(3), False, id="R-K-02-nuestra"),
    pytest.param(None, tok(3), False, id="R-K-02-nuestra-15-campos"),
    pytest.param("  ", tok(3), False, id="R-K-02-orderSrc-vacio-cuenta-como-ausente"),
    pytest.param("cmdapi", tok(3, Origen.VIGILANTE), False, id="R-K-02-del-vigilante-es-nuestra"),
    pytest.param("AutoStop", tok(3), True, id="R-K-02-AutoStop"),
    pytest.param("Basket", tok(3), True, id="R-K-02-Basket"),
    pytest.param("CMDAPI", tok(3, dia=AYER), True, id="R-K-02-token-de-ayer"),
])
def test_es_ajena(order_src, token, ajena):
    assert es_ajena(msg_crudo(1, token, order_src=order_src), HOY) is ajena


def test_orden_de_msg_stop_desconocido_por_el_ejecutor():
    """Corrección 3 / riesgo 1: un %ORDER «SLP: 2.97 2.99» nuestro sin diario → STOPLMTP 2.97/2.99, propósito a inferir."""
    m = msg_crudo(70, tok(4, Origen.VIGILANTE), lado="B", tipo="SLP: 2.97 2.99", precio="2.99", estado=EstadoOrden.HOLD)
    o = orden_de_msg(m, HOY)
    assert (o.tipo, o.stop, o.precio, o.lado, o.proposito, o.origen, o.id_das, o.estado, o.llenas) == (
        TipoOrden.STOP_LIMITE_PP, D("2.97"), D("2.99"), Lado.COMPRA, Proposito.DESCONOCIDA, Origen.VIGILANTE, 70,
        EstadoOrden.HOLD, 0)


@pytest.mark.parametrize("m", [
    pytest.param(msg_crudo(1, None), id="ajena-sin-token"),
    pytest.param(msg_crudo(1, tok(1), lado="X"), id="lado-desconocido"),
    pytest.param(msg_crudo(1, tok(1), order_src="Montage"), id="ajena-por-orderSrc"),
])
def test_orden_de_msg_devuelve_none(m):
    assert orden_de_msg(m, HOY) is None


def test_orden_de_msg_con_conocida_copia_lo_de_das_sin_mutar():
    p = principal(qty=100)
    m = msg(p, qty=80)
    o = orden_de_msg(m, HOY, p)
    assert o is not p and (o.qty, o.proposito, o.lote_id, o.nivel) == (80, Proposito.STOP_PRINCIPAL, "L1", D("10"))
    assert p.qty == 100


def test_orden_de_msg_accepted_con_lvqty_cero_no_mata_el_stop():
    """Riesgo 11: un lvqty 0 no documentado en Accepted no convierte un stop vivo en lleno (duplicaría el stop)."""
    m = msg_crudo(70, tok(4), tipo="SLP: 10 10.3", lvqty=0)
    assert rc._qty_viva(orden_de_msg(m, HOY)) == 100


def test_cobertura_y_huerfanas():
    compra = principal(qty=100)
    sending = emergencia(qty=100, id_das=None, estado=EstadoOrden.SENDING)
    venta = orden(tok(8), Proposito.STOP_PROTECCION, "6.00", "5.82", 50, 80, lado=Lado.VENTA)
    corto = orden(tok(9), Proposito.ENTRADA_AGREGAR, None, "9.00", 70, 81, lado=Lado.CORTO, tipo=TipoOrden.LIMITE)
    vivas = [compra, sending, venta, corto]
    assert cobertura(vivas, X, -100) == 200 and cobertura(vivas, X, -100, solo_confirmadas=True) == 100
    assert cobertura(vivas, X, 50) == 50 and cobertura(vivas, X, 0) == 0 and cobertura(vivas, "OTRO", -100) == 0
    assert huerfanas(vivas, X, -100) == [venta]
    assert huerfanas(vivas, X, 0) == [compra, venta, sending]   # antigüedad: con id por id; sin id al final
    assert huerfanas(vivas, X, 50) == [compra, sending]


# ── R-K-01: cadencia y comandos del barrido ──────────────────────────────
def _intento() -> IntentoEntrada:
    return IntentoEntrada(ticker=X, lotes=["L1"], qty_total=100, bid_senal=D("9"), ask_senal=D("9.01"),
                          precio_senal=D("9"), t_cierre_vela=0.0, t_limite=60.0)


@pytest.mark.parametrize("preparar,ahora,esperado", [
    pytest.param(lambda e: setattr(e, "ultimo_fill_en", 100.0), 110.0, BARRIDO_TRAS_FILL_S, id="R-K-01-1s-tras-fill"),
    pytest.param(lambda e: setattr(e, "ultimo_fill_en", 100.0), 159.9, BARRIDO_TRAS_FILL_S, id="R-K-01-1s-hasta-los-60s"),
    pytest.param(lambda e: (setattr(e, "ultimo_fill_en", 100.0), e.posiciones.update({X: posicion(-100)})), 160.0,
                 BARRIDO_CON_POSICIONES_S, id="R-K-01-pasados-60s-con-posicion-2s"),
    pytest.param(lambda e: e.posiciones.update({X: PosicionTicker(ticker=X, intento=_intento())}), 500.0,
                 BARRIDO_TRAS_FILL_S, id="R-K-01-entrada-en-escalera-1s"),
    pytest.param(lambda e: e.posiciones.update({X: posicion(0, neta_das=-5)}), 500.0, BARRIDO_CON_POSICIONES_S,
                 id="R-K-01-DAS-ve-posicion-2s"),
    pytest.param(lambda e: e.ordenes.update({1: principal()}), 500.0, BARRIDO_CON_POSICIONES_S,
                 id="R-K-01-ordenes-vivas-2s"),
    pytest.param(lambda e: e.ordenes.update({1: principal(estado=EstadoOrden.CANCELED)}), 500.0, BARRIDO_SIN_NADA_S,
                 id="R-K-01-orden-muerta-no-cuenta-10s"),
    pytest.param(lambda e: None, 500.0, BARRIDO_SIN_NADA_S, id="R-K-01-sin-nada-10s"),
])
def test_cadencia_barrido(cfg, preparar, ahora, esperado):
    estado = EstadoBot(fase=Fase.SOMBRA, dia=HOY)
    preparar(estado)
    assert cadencia_barrido(estado, ahora, cfg.tecnicos) == esperado


def test_cadencia_barrido_intento_terminado_no_cuenta(cfg):
    intento = _intento()
    intento.fase = FaseIntento.TERMINADO
    estado = EstadoBot(fase=Fase.SOMBRA, dia=HOY, posiciones={X: PosicionTicker(ticker=X, intento=intento)})
    assert cadencia_barrido(estado, 0.0, cfg.tecnicos) == BARRIDO_SIN_NADA_S


def test_cadencia_barrido_lee_la_config_y_sus_defectos():
    estado = EstadoBot(fase=Fase.SOMBRA, dia=HOY, ultimo_fill_en=0.0)
    propio = {"barrido_s": {"tras_fill": 0.5, "ventana_tras_fill_s": 5, "con_posiciones": 3, "sin_nada": 20}}
    assert cadencia_barrido(estado, 4.0, propio) == 0.5
    assert cadencia_barrido(estado, 6.0, propio) == 20.0
    assert cadencia_barrido(estado, 6.0, None) == BARRIDO_TRAS_FILL_S   # sin config: ventana de 60 s
    malos = {"barrido_s": {"tras_fill": -1, "ventana_tras_fill_s": True, "con_posiciones": "x", "sin_nada": 0}}
    assert cadencia_barrido(estado, 100.0, malos) == BARRIDO_SIN_NADA_S


@pytest.mark.parametrize("tras_fill,esperado", [
    pytest.param(False, ["GET POSITIONS", "GET ORDERS", "GET BP", "GET LOCATES"], id="R-K-01-barrido"),
    pytest.param(True, ["GET POSITIONS", "GET ORDERS", "GET TRADES", "GET BP", "GET LOCATES"], id="R-K-01-tras-fill-con-trades"),
])
def test_comandos_barrido(tras_fill, esperado):
    comandos = comandos_barrido(tras_fill)
    assert all(isinstance(c, Consultar) for c in comandos) and [c.comando for c in comandos] == esperado


# ── R-K-03: caducidad ────────────────────────────────────────────────────
@pytest.mark.parametrize("ultima,ahora,tolerancia,esperado", [
    pytest.param(None, 0.0, RECONCILIACION_CADUCA_S, True, id="R-K-03-nunca-respondio-no-se-abre"),
    pytest.param(100.0, 129.9, RECONCILIACION_CADUCA_S, False, id="R-K-03-dentro-de-30s"),
    pytest.param(100.0, 130.0, RECONCILIACION_CADUCA_S, False, id="R-K-03-justo-30s-aun-no"),
    pytest.param(100.0, 130.01, RECONCILIACION_CADUCA_S, True, id="R-K-03-pasados-30s"),
    pytest.param(100.0, 106.0, 5.0, True, id="R-K-03-tolerancia-propia"),
])
def test_barrido_caducado(ultima, ahora, tolerancia, esperado):
    assert barrido_caducado(ultima, ahora, tolerancia) is esperado


def test_barrido_caducado_defecto_30s():
    assert barrido_caducado(0.0, 30.5) is True and barrido_caducado(0.0, 29.5) is False


# ── §5.11: AcumuladorVolcado ─────────────────────────────────────────────
def _parser() -> Parser:
    return Parser(lambda t: mod_tokens.es_nuestro(t, HOY))


LINEAS_CON_MARCADORES = [
    "#POS symb type qty avgcost initqty initprice Realized CreateTime Unrealized",
    "%POS XYZ 3 -300 2.45 0 0 0 2026/09/25-09:49:30 -12",
    "%POS ABC 2 0 5.1 0 0 0 2026/09/25-09:40:00 25",
    "#POSEND",
    "#Order id token symb b/s mkt/lmt qty lvqty cxlqty price route status time origoid account trader orderSrc TIF Pref",
    f"%ORDER 7001 {tok(1)} XYZ SS L 300 0 0 2.45 SAGEREB Executed 09:49:27 0 CUENTA_PRUEBA TRPRUEBA CMDAPI DAY+ N/A",
    f"%ORDER 7002 {tok(2)} XYZ B SLP: 2.97 3.06 300 300 0 3.06 STOP Accepted 09:49:28 0 CUENTA_PRUEBA TRPRUEBA CMDAPI DAY+ N/A",
    "#OrderEnd",
]


def test_acumulador_con_marcadores_entrega_al_cerrar_posiciones_y_ordenes():
    """§5.13: volcado con #POS…#POSEND y #Order…#OrderEnd (formato del LOGIN) → una sola foto al cerrar el último bloque."""
    parser, acumulador = _parser(), AcumuladorVolcado()
    acumulador.iniciar(0.0)
    entregas = [acumulador.aplicar(parser.parsear(linea), 0.001 * i) for i, linea in enumerate(LINEAS_CON_MARCADORES)]
    assert entregas[:-1] == [None] * (len(LINEAS_CON_MARCADORES) - 1)
    posiciones, ordenes, trades = entregas[-1]
    assert sorted(posiciones) == ["ABC", "XYZ"] and posiciones["XYZ"].neta == -300 and posiciones["ABC"].neta == 0
    assert sorted(ordenes) == [7001, 7002] and trades == []
    assert acumulador.activo is False


def test_acumulador_con_trades_espera_el_bloque_trade():
    parser, acumulador = _parser(), AcumuladorVolcado()
    acumulador.iniciar(0.0, con_trades=True)
    for linea in LINEAS_CON_MARCADORES:
        assert acumulador.aplicar(parser.parsear(linea), 0.0) is None
    trade = MsgTrade(cruda="%TRADE …", id=55, ticker=X, lado="SS", qty=300, precio=D("2.45"), ruta="SAGEREB",
                     hora="09:49:27", id_orden=7001, liq=None, ecn_fee=None, pl=None, cuenta=None, trader=None, watch=False)
    assert acumulador.aplicar(MsgMarcador(cruda="#Trade", nombre="#Trade"), 0.0) is None
    assert acumulador.aplicar(trade, 0.0) is None
    assert acumulador.aplicar(trade, 0.0) is None   # repetido: un solo trade
    foto = acumulador.aplicar(MsgMarcador(cruda="#TradeEnd", nombre="#TradeEnd"), 0.0)
    assert foto is not None and [t.id for t in foto[2]] == [55]


def test_acumulador_sin_marcadores_entrega_tras_500ms_de_silencio():
    """§5.11: GET POSITIONS/ORDERS sin marcadores → la foto sale tras 500 ms sin líneas nuevas (y no antes)."""
    parser, acumulador = _parser(), AcumuladorVolcado()
    acumulador.iniciar(10.0)
    assert acumulador.aplicar(parser.parsear("%POS XYZ 3 -300 2.45 0 0 0 2026/09/25-09:49:30 -12"), 10.01) is None
    assert acumulador.aplicar(parser.parsear(LINEAS_CON_MARCADORES[6]), 10.02) is None
    assert acumulador.revisar(10.519) is None
    foto = acumulador.revisar(10.52)
    assert foto is not None and list(foto[0]) == ["XYZ"] and list(foto[1]) == [7002]
    assert acumulador.revisar(20.0) is None   # ya entregado


def test_acumulador_la_respuesta_de_bp_cierra_un_volcado_vacio():
    """§5.11: sin posiciones ni órdenes y sin marcadores, la respuesta a GET BP (pedida detrás) cierra la foto vacía."""
    parser, acumulador = _parser(), AcumuladorVolcado()
    acumulador.iniciar(0.0)
    assert acumulador.aplicar(parser.parsear("#buyingpower bp,nbp"), 0.01) is None
    foto = acumulador.aplicar(parser.parsear("BP 94339.5 100000"), 0.02)
    assert foto == ({}, {}, [])


def test_acumulador_bp_con_bloque_abierto_o_sin_pedir_no_entrega():
    parser, acumulador = _parser(), AcumuladorVolcado()
    bp = MsgBP(cruda="BP 1 2", bp=D("1"), bp_overnight=D("2"))
    assert acumulador.aplicar(bp, 0.0) is None   # un BP empujado sin volcado pedido: se ignora
    acumulador.iniciar(0.0)
    assert acumulador.aplicar(parser.parsear("#POS"), 0.0) is None
    assert acumulador.aplicar(bp, 0.0) is None   # bloque POS abierto: aún faltan líneas
    assert acumulador.activo


def test_acumulador_ignora_lineas_sueltas_fuera_de_un_volcado():
    parser, acumulador = _parser(), AcumuladorVolcado()
    assert acumulador.aplicar(parser.parsear("%POS XYZ 3 -300 2.45 0 0 0 2026/09/25-09:49:30 -12"), 0.0) is None
    assert acumulador.revisar(5.0) is None and acumulador.activo is False


def test_acumulador_volcado_espontaneo_del_login_y_la_ultima_linea_gana():
    """El LOGIN manda #POS… sin que nadie llame a iniciar; un %POS empujado a mitad sustituye al del volcado."""
    parser, acumulador = _parser(), AcumuladorVolcado()
    foto = None
    for linea in LINEAS_CON_MARCADORES[:3] + ["%POS XYZ 3 -200 2.45 0 0 0 2026/09/25-09:49:31 -12"] + LINEAS_CON_MARCADORES[3:]:
        foto = acumulador.aplicar(parser.parsear(linea), 0.0) or foto
    assert foto is not None and foto[0]["XYZ"].neta == -200


def test_acumulador_marcador_de_inicio_vacia_su_categoria_e_iniciar_descarta_lo_anterior():
    parser, acumulador = _parser(), AcumuladorVolcado()
    acumulador.iniciar(0.0)
    acumulador.aplicar(parser.parsear("%POS OLD 3 -1 2.45 0 0 0 2026/09/25-09:49:30 -12"), 0.0)
    acumulador.iniciar(1.0)
    acumulador.aplicar(parser.parsear("#POS"), 1.0)
    acumulador.aplicar(parser.parsear("#POSEND"), 1.0)
    acumulador.aplicar(parser.parsear("#Order"), 1.0)
    foto = acumulador.aplicar(parser.parsear("#OrderEnd"), 1.0)
    assert foto == ({}, {}, [])
    acumulador.iniciar(2.0)
    acumulador.descartar()
    assert acumulador.activo is False


def test_acumulador_espera_invalida():
    with pytest.raises(ValueError):
        AcumuladorVolcado(0)


# ── pureza del módulo ────────────────────────────────────────────────────
def test_modulo_puro_solo_importa_lo_permitido():
    """reglas/*: sin I/O, sin reloj, sin red; solo tipos, tokens, reglas.precios, reglas.stops y la biblioteca estándar (§12).

    A-06: también `protocolo` (puro: solo construye cadenas con `cmd_get`); D2-08: `html` (escapar avisos).
    """
    arbol = ast.parse(Path(rc.__file__).read_text(encoding="utf-8"))
    permitidos = {"__future__", "re", "html", "collections.abc", "dataclasses", "datetime", "decimal", "typing",
                  "app.bot_das", "app.bot_das.protocolo", "app.bot_das.reglas", "app.bot_das.reglas.precios",
                  "app.bot_das.tipos"}
    modulos = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.ImportFrom):
            modulos.add(nodo.module)
        elif isinstance(nodo, ast.Import):
            modulos.update(a.name for a in nodo.names)
    assert modulos <= permitidos, modulos - permitidos
    llamadas = {nodo.func.attr if isinstance(nodo.func, ast.Attribute) else getattr(nodo.func, "id", "")
                for nodo in ast.walk(arbol) if isinstance(nodo, ast.Call)}
    assert not llamadas & {"now", "today", "monotonic", "time", "open", "print", "getenv", "sleep"}


def test_caso_3_idempotente_tras_el_eco_de_das(cfg):
    """Riesgo 11: tras reponer (caso 3) y recibir los %ORDER Accepted, el barrido siguiente es caso 1 sin acciones."""
    estado = estado_con(corto_conocido())
    acc = acciones(comparar(estado, {X: pos_das(-100)}, {}, HOY, cfg), estado, cot_de(cot()), cfg, Contador(), HORA, RUTA_STOP)
    eco = {}
    for i, a in enumerate(de_tipo(acc, EnviarOrden)):
        o = a.orden
        eco[300 + i] = msg_crudo(300 + i, o.token, tipo=f"SLP: {o.stop} {o.precio}", qty=o.qty, precio=str(o.precio))
    segunda = comparar(estado, {X: pos_das(-100)}, eco, HOY, cfg)
    assert casos(segunda) == [(X, CASO_COINCIDE)]
    assert acciones(segunda, estado, cot_de(cot()), cfg, Contador(), HORA, RUTA_STOP) == []
