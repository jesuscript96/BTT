"""Tests de `app.bot_das.reglas.rechazos` (R-B-07, R-C-03, EP-1, injerto A §8.7) y de `catalogo_rechazos.json`.

Fila de §10: cada entrada del catálogo casa su propio texto (y no los de las
demás); desconocido → cubierta pausa / no cubierta nivel 3 sin `EnviarOrden`;
2 reintentos y no 3, con token nuevo; `reintento_stop` 5 y para;
`tras_cancel_o_replace_rej` → barrido. Todo puro, en Decimal y sin red.

Ampliada tras la revisión (27-sep): «PostOnly would cross» pasa al cruce sin
reintento ni pausa (D2-09); el reenvío de una salida nunca supera la posición
(D2-10); los avisos escapan el HTML (D2-08); `reintento_stop` mide la subida
desde el primer intento (D2-15); los GET salen de protocolo.cmd_get (A-06).
Los tests de la MECÁNICA de «reintentar» (contador, tokens, qty pendiente,
PostOnly conservado) usan una entrada sintética `REINTENTAR`: el catálogo real
ya no tiene ninguna entrada con esa acción (el PostOnly era la única).
"""
from __future__ import annotations

import ast
import copy
import json
import math
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

import pytest

from app.bot_das.reglas import rechazos as R
from app.bot_das.reglas.rechazos import (
    ACCIONES_TRATAMIENTO,
    CLAVE_DESCONOCIDO,
    DESCONOCIDO,
    RUTA_CATALOGO,
    Tratamiento,
    cargar_catalogo,
    clasificar,
    decidir,
    reintento_stop,
    tras_cancel_o_replace_rej,
    validar_catalogo,
)
from app.bot_das.reloj import ET
from app.bot_das.tipos import (
    Accion,
    Anotar,
    Avisar,
    Cancelar,
    CancelarTicker,
    Consultar,
    Cotizacion,
    EnviarOrden,
    EstadoLote,
    EstadoOrden,
    EstadoTicker,
    Grupo,
    Lado,
    Lote,
    Nivel,
    Orden,
    Origen,
    PosicionTicker,
    Programar,
    Proposito,
    TipoOrden,
)

HORA = datetime(2026, 9, 25, 9, 31, 2, tzinfo=ET)
TICKER = "XYZ"
TOKEN_RECHAZADO = 126800005
D = Decimal

CFG: dict[str, Any] = {
    "entrada": {"post_only": True, "reintentos_rechazo_conocido": 2},
    "stops": {"principal_limite_pct": 3.0, "emergencia_disparo_pct": 13.0, "emergencia_limite_pct": 63.0,
              "reintentos": 5, "separacion_reintentos_s": 2, "ventana_min": 5},
    "rutas": {"agregar": {"ge_1": "SAGEREB", "lt_1": "MIAX"},
              "cruzar": {"ge_1": "SAGEPRO", "lt_1_desde_0700": "EDGA", "lt_1_antes_0700": "MIAX"},
              "stop": "STOP", "halt": "OPEN"},
    "salidas": {"tp_parcial": {"agregar_s": 60, "techo_ask_pct": 3.0}},
}

# Entrada sintética con la acción «reintentar» (la mecánica del reintento idéntico sigue existiendo para
# cualquier motivo futuro que la lleve; el PostOnly ya no: pasa al cruce, D2-09).
REINTENTAR = Tratamiento(conocido=True, clave="prueba_reintentar", accion="reintentar")
LOTE_ID = "XYZ|prueba-1|2026-09-25 09:30:00|entrada"


# ── fábricas ────────────────────────────────────────────────────────────────
class Tokens:
    """Generador de tokens de prueba que cuenta las llamadas (un reintento gasta UNO; sin reintento, ninguno)."""

    def __init__(self, inicio: int = 126800100) -> None:
        self.siguiente_valor = inicio
        self.dados: list[int] = []

    def __call__(self) -> int:
        self.siguiente_valor += 1
        self.dados.append(self.siguiente_valor)
        return self.siguiente_valor


@pytest.fixture(scope="module")
def catalogo() -> list[dict]:
    return cargar_catalogo(RUTA_CATALOGO)


def tratamiento(catalogo: list[dict], clave: str) -> Tratamiento:
    entrada = next(e for e in catalogo if e["clave"] == clave)
    t = clasificar(entrada["ejemplos"][0], catalogo)
    assert t.clave == clave
    return t


def orden(proposito: Proposito = Proposito.ENTRADA_AGREGAR, lado: Lado = Lado.CORTO,
          tipo: TipoOrden = TipoOrden.LIMITE, qty: int = 500, precio: Optional[Decimal] = D("3.45"),
          stop: Optional[Decimal] = None, ruta: str = "SAGEREB", token: int = TOKEN_RECHAZADO, intentos: int = 0,
          notas: str = "PostOnly would cross", llenas: int = 0, estado: EstadoOrden = EstadoOrden.REJECTED,
          ticker: str = TICKER, **extra: Any) -> Orden:
    return Orden(token=token, ticker=ticker, lado=lado, tipo=tipo, qty=qty, precio=precio, stop=stop, ruta=ruta,
                 proposito=proposito, lote_id=extra.pop("lote_id", "XYZ|prueba-1|2026-09-25 09:30:00|entrada"),
                 nivel=extra.pop("nivel", D("3.90")), origen=Origen.EJECUTOR, estado=estado, llenas=llenas,
                 notas=notas, intentos=intentos, **extra)


def stop_compra(proposito: Proposito, qty: int = 100, estado: EstadoOrden = EstadoOrden.ACCEPTED,
                token: int = 126800002, disparo: Decimal = D("11.30"), limite: Decimal = D("16.30"),
                **extra: Any) -> Orden:
    return Orden(token=token, ticker=TICKER, lado=Lado.COMPRA, tipo=TipoOrden.STOP_LIMITE_PP, qty=qty,
                 precio=limite, stop=disparo, ruta="STOP", proposito=proposito, lote_id="L1", nivel=D("10"),
                 origen=Origen.EJECUTOR, estado=estado, **extra)


def posicion(neta: int = 0, estado: EstadoTicker = EstadoTicker.NORMAL) -> PosicionTicker:
    lotes = {}
    if neta:
        lotes["L1"] = Lote(id="L1", strategy_id="prueba-1", estrategia="PM (A) prueba", ticker=TICKER,
                           direccion="Short", pedidas=-neta, llenas=-neta, precio_medio=D("9.50"),
                           nivel_stop=D("10"))
        lotes[LOTE_ID] = Lote(id=LOTE_ID, strategy_id="prueba-1", estrategia="PM (A) prueba", ticker=TICKER,
                              direccion="Short", pedidas=-neta, llenas=-neta, precio_medio=D("9.50"),
                              nivel_stop=D("10"), estado=EstadoLote.ABIERTO)
    return PosicionTicker(ticker=TICKER, lotes=lotes, neta_fills=neta, neta_das=neta, estado=estado)


def cot(bid: str = "3.44", ask: str = "3.46", last: str = "3.45") -> Cotizacion:
    return Cotizacion(ticker=TICKER, bid=D(bid), ask=D(ask), last=D(last))


def de_tipo(acciones: list[Accion], clase: type) -> list[Any]:
    return [a for a in acciones if isinstance(a, clase)]


def anotacion(acciones: list[Accion], tipo: str) -> Optional[dict]:
    encontradas = [a.datos for a in acciones if isinstance(a, Anotar) and a.tipo == tipo]
    assert len(encontradas) <= 1
    return encontradas[0] if encontradas else None


def aviso(acciones: list[Accion]) -> Avisar:
    avisos = de_tipo(acciones, Avisar)
    assert len(avisos) == 1, "R-B-07 (1): UN aviso por rechazo, siempre"
    return avisos[0]


# ── catálogo: fichero real ──────────────────────────────────────────────────
def _entradas_y_ejemplos() -> list[Any]:
    datos = json.loads(RUTA_CATALOGO.read_text(encoding="utf-8"))
    return [pytest.param(e["clave"], ej, id=f"R-B-07-{e['clave']}-{i}") for e in datos
            for i, ej in enumerate(e["ejemplos"])]


def test_catalogo_real_carga_y_esta_completo(catalogo: list[dict]) -> None:
    claves = [e["clave"] for e in catalogo]
    assert len(claves) == len(set(claves)) >= 10
    for e in catalogo:
        assert e["provisional"] is True, "todo PROVISIONAL hasta el canario (fase H)"
        assert e["fuente"].strip() and e["ejemplos"], e["clave"]
        assert e["accion"] in ACCIONES_TRATAMIENTO and e["nivel"] in (2, 3)


@pytest.mark.parametrize("clave, accion", [
    pytest.param("bp_insuficiente", "recalcular_bp", id="R-B-07-bp"),
    pytest.param("sin_locate", "recomprar_locate", id="R-B-07-locate-no-shortable"),
    pytest.param("ssr", "subir_tick_ssr", id="R-B-07-ssr"),
    pytest.param("ruta_cerrada", "ninguna", id="R-B-07-ruta-cerrada"),
    pytest.param("simbolo_en_halt", "ninguna", id="R-B-07-halt"),
    pytest.param("precio_fuera_de_tick", "ninguna", id="R-B-07-tick"),
    pytest.param("postonly_cruza", "pasar_a_cruce", id="R-B-07-postonly-D2-09"),
    pytest.param("cantidad_invalida", "ninguna", id="R-B-07-cantidad"),
    pytest.param("tif_invalido", "ninguna", id="R-B-07-tif"),
    pytest.param("sesion_cerrada", "ninguna", id="R-B-07-sesion"),
])
def test_catalogo_trae_las_entradas_pedidas(catalogo: list[dict], clave: str, accion: str) -> None:
    entrada = next(e for e in catalogo if e["clave"] == clave)
    assert entrada["accion"] == accion


@pytest.mark.parametrize("clave, ejemplo", _entradas_y_ejemplos())
def test_cada_entrada_casa_su_texto_y_no_los_de_las_demas(catalogo: list[dict], clave: str, ejemplo: str) -> None:
    import re
    t = clasificar(ejemplo, catalogo)
    assert t.conocido and t.clave == clave
    for otra in catalogo:
        if otra["clave"] != clave:
            assert not re.search(otra["regex"], ejemplo, re.IGNORECASE), (otra["clave"], ejemplo)
    # tolerante a mayúsculas (R-B-07: regex insensible)
    assert clasificar(ejemplo.upper(), catalogo).clave == clave
    assert clasificar(ejemplo.lower(), catalogo).clave == clave


@pytest.mark.parametrize("texto, clave", [
    pytest.param("PostOnly would cross", "postonly_cruza", id="§3.3-literal-del-simulador"),
    pytest.param("Rejected: 0 shares available", "sin_locate", id="R-B-07-locate-consumido-diario-ejemplo"),
    pytest.param("post-only order would cross", "postonly_cruza", id="R-B-07-tolerante-guion"),
    pytest.param("NOT  ENOUGH   BUYING POWER", "bp_insuficiente", id="R-B-07-tolerante-espacios"),
    pytest.param("Rejected: Security not shortable (HTB)", "sin_locate", id="R-B-07-tolerante-prefijo"),
    pytest.param("Order rejected - SSR in effect, price must be above bid", "ssr", id="R-B-07-ssr-libre"),
])
def test_textos_tolerantes(catalogo: list[dict], texto: str, clave: str) -> None:
    assert clasificar(texto, catalogo).clave == clave


def test_ejemplo_de_simulador_si_existe(catalogo: list[dict]) -> None:
    simulador = pytest.importorskip("app.bot_das.simulador_das")
    assert clasificar(simulador.NOTA_POSTONLY, catalogo).clave == "postonly_cruza"


@pytest.mark.parametrize("notas", [
    pytest.param("Something weird happened", id="R-B-07-texto-nuevo"),
    pytest.param("", id="R-B-07-vacio"),
    pytest.param("   ", id="R-B-07-blancos"),
    pytest.param(None, id="R-B-07-none"),
])
def test_desconocido(catalogo: list[dict], notas: Optional[str]) -> None:
    t = clasificar(notas, catalogo)
    assert t == DESCONOCIDO
    assert (t.conocido, t.clave, t.accion, t.nivel) == (False, CLAVE_DESCONOCIDO, "ninguna", Nivel.AVISO)


def test_clasificar_primera_que_casa_y_nunca_lanza() -> None:
    malo: list[Any] = [None, 5, {"regex": "("}, {"clave": "vacia", "regex": "", "accion": "ninguna", "nivel": 2},
                       {"clave": "todo", "regex": "a*", "accion": "ninguna", "nivel": 2},
                       {"clave": "accion_mala", "regex": "boom", "accion": "cerrar", "nivel": 2},
                       {"clave": "nivel_malo", "regex": "boom", "accion": "ninguna", "nivel": 1},
                       {"clave": "sin_nivel", "regex": "boom", "accion": "ninguna"},
                       {"regex": "boom", "accion": "ninguna", "nivel": 2},
                       {"clave": "primera", "regex": "boom", "accion": "reintentar", "nivel": 2},
                       {"clave": "segunda", "regex": "boom", "accion": "ninguna", "nivel": 3}]
    t = clasificar("BOOM!", malo)
    assert (t.conocido, t.clave, t.accion, t.nivel) == (True, "primera", "reintentar", Nivel.AVISO)
    assert clasificar("nada", malo) == DESCONOCIDO
    assert clasificar("boom", None) == DESCONOCIDO   # type: ignore[arg-type]
    assert clasificar("boom", 7) == DESCONOCIDO      # type: ignore[arg-type]
    assert clasificar(12345, []) == DESCONOCIDO       # type: ignore[arg-type]


# ── catálogo: validación ────────────────────────────────────────────────────
def _entrada(**cambios: Any) -> dict:
    base = {"clave": "prueba", "regex": r"boom", "accion": "reintentar", "nivel": 2, "fuente": "test",
            "provisional": True, "ejemplos": ["boom"]}
    base.update(cambios)
    return {k: v for k, v in base.items() if v is not _QUITAR}


_QUITAR = object()


@pytest.mark.parametrize("datos, trozo", [
    pytest.param({"a": 1}, "lista no vacía", id="R-B-07-no-lista"),
    pytest.param([], "lista no vacía", id="R-B-07-lista-vacia"),
    pytest.param(["texto"], "objeto", id="R-B-07-entrada-no-objeto"),
    pytest.param([_entrada(clave=_QUITAR)], "faltan", id="R-B-07-sin-clave"),
    pytest.param([_entrada(fuente=_QUITAR)], "faltan", id="R-B-07-sin-fuente"),
    pytest.param([_entrada(acion="reintentar")], "no admitidas", id="R-B-07-errata"),
    pytest.param([_entrada(clave="Mayus")], "clave inválida", id="R-B-07-clave-mayusculas"),
    pytest.param([_entrada(), _entrada(regex="otro", ejemplos=["otro"])], "repetida", id="R-B-07-clave-repetida"),
    pytest.param([_entrada(clave="desconocido")], "reservada", id="R-B-07-clave-reservada"),
    pytest.param([_entrada(regex="(")], "no compila", id="R-B-07-regex-rota"),
    pytest.param([_entrada(regex="  ")], "vacía", id="R-B-07-regex-vacia"),
    pytest.param([_entrada(regex="x*", ejemplos=[])], "texto vacío", id="R-B-07-regex-casa-todo"),
    pytest.param([_entrada(accion="cerrar")], "acción", id="R-B-07-accion-invalida"),
    pytest.param([_entrada(nivel=1)], "nivel", id="R-B-07-nivel-1"),
    pytest.param([_entrada(nivel=True)], "nivel", id="R-B-07-nivel-bool"),
    pytest.param([_entrada(nivel="2")], "nivel", id="R-B-07-nivel-texto"),
    pytest.param([_entrada(fuente=" ")], "fuente", id="R-B-07-fuente-vacia"),
    pytest.param([_entrada(provisional="si")], "provisional", id="R-B-07-provisional-no-bool"),
    pytest.param([_entrada(ejemplos="boom")], "ejemplos", id="R-B-07-ejemplos-no-lista"),
    pytest.param([_entrada(ejemplos=[""])], "ejemplos", id="R-B-07-ejemplo-vacio"),
    pytest.param([_entrada(ejemplos=["nada que ver"])], "no casa", id="R-B-07-ejemplo-no-casa"),
    pytest.param([_entrada(descripcion=3)], "descripcion", id="R-B-07-descripcion-no-texto"),
    pytest.param([_entrada(clave="general", regex="bo", ejemplos=["bo"]), _entrada(ejemplos=["boom"])],
                 "clasifica", id="R-B-07-entrada-tapada"),
])
def test_validar_catalogo_rechaza(datos: Any, trozo: str) -> None:
    with pytest.raises(ValueError, match=trozo):
        validar_catalogo(datos)


def test_validar_normaliza_y_no_toca_la_entrada() -> None:
    datos = [{"clave": "a", "regex": "boom", "accion": "ninguna", "nivel": 3, "fuente": "f"}]
    antes = copy.deepcopy(datos)
    r = validar_catalogo(datos)
    assert datos == antes
    assert r == [{"clave": "a", "regex": "boom", "accion": "ninguna", "nivel": 3, "fuente": "f",
                  "provisional": True, "ejemplos": [], "descripcion": ""}]
    r[0]["ejemplos"].append("x")
    assert "ejemplos" not in datos[0]


def test_cargar_catalogo_errores(tmp_path: Path) -> None:
    roto = tmp_path / "roto.json"
    roto.write_text("[{", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON inválido"):
        cargar_catalogo(roto)
    latin = tmp_path / "latin.json"
    latin.write_bytes('[{"clave": "ñ"}]'.encode("latin-1"))
    with pytest.raises(ValueError, match="JSON inválido"):
        cargar_catalogo(latin)
    malo = tmp_path / "malo.json"
    malo.write_text(json.dumps([_entrada(accion="cerrar")]), encoding="utf-8")
    with pytest.raises(ValueError, match="malo.json"):
        cargar_catalogo(str(malo))
    with pytest.raises(FileNotFoundError):
        cargar_catalogo(tmp_path / "no_existe.json")
    bueno = tmp_path / "bueno.json"
    bueno.write_text(json.dumps([_entrada()]), encoding="utf-8")
    assert [e["clave"] for e in cargar_catalogo(bueno)] == ["prueba"]


@pytest.mark.parametrize("kwargs", [
    pytest.param({"accion": "cerrar_al_ask"}, id="R-B-07-accion-fuera"),
    pytest.param({"accion": "ninguna", "nivel": 1}, id="R-B-07-nivel-1"),
    pytest.param({"accion": "ninguna", "nivel": True}, id="R-B-07-nivel-bool"),
])
def test_tratamiento_valida(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        Tratamiento(conocido=True, clave="x", **kwargs)


def test_tratamiento_nivel_entero_pasa_a_nivel() -> None:
    t = Tratamiento(conocido=True, clave="x", accion="reintentar", nivel=3)   # type: ignore[arg-type]
    assert t.nivel is Nivel.MAXIMO
    assert Tratamiento(conocido=True, clave="x", accion="reintentar").nivel is Nivel.AVISO


# ── decidir: reintentos (R-B-07 (2)) ────────────────────────────────────────
@pytest.mark.parametrize("intentos, reintenta", [
    pytest.param(0, True, id="R-B-07-reintento-1"),
    pytest.param(1, True, id="R-B-07-reintento-2"),
    pytest.param(2, False, id="R-B-07-no-hay-tercero"),
    pytest.param(3, False, id="R-B-07-ni-cuarto"),
])
def test_dos_reintentos_y_no_tres_con_token_nuevo(catalogo: list[dict], intentos: int, reintenta: bool) -> None:
    """R-B-07 (2): la mecánica de «reintentar» (entrada sintética; el PostOnly ya no la usa, D2-09)."""
    tokens = Tokens()
    o = orden(intentos=intentos)
    acciones = decidir(o, REINTENTAR, posicion(), [], CFG, tokens, cot(), HORA)
    enviadas = de_tipo(acciones, EnviarOrden)
    rechazo = anotacion(acciones, "rechazo")
    assert rechazo is not None and rechazo["notas"] == "PostOnly would cross"
    if reintenta:
        assert len(enviadas) == 1 and tokens.dados == [enviadas[0].orden.token]
        nueva = enviadas[0].orden
        assert nueva.token != TOKEN_RECHAZADO
        assert (nueva.lado, nueva.qty, nueva.precio, nueva.ruta, nueva.tipo) == (
            Lado.CORTO, 500, D("3.45"), "SAGEREB", TipoOrden.LIMITE)
        assert nueva.post_only is True and nueva.proposito is Proposito.ENTRADA_AGREGAR
        assert nueva.lote_id == o.lote_id and enviadas[0].serie is None
        assert rechazo["decision"] == "reintento"
        assert rechazo["token_nuevo"] == nueva.token and rechazo["intentos_nuevo"] == intentos + 1
        assert anotacion(acciones, "pausa") is None
        assert [type(a) for a in acciones] == [Anotar, Avisar, EnviarOrden]
    else:
        assert enviadas == [] and tokens.dados == [], "sin reintento no se gasta token"
        assert rechazo["decision"] == "pausa" and rechazo["token_nuevo"] is None
        assert anotacion(acciones, "pausa")["estado"] == "pausado"
        assert [type(a) for a in acciones] == [Anotar, Anotar, Avisar]


def test_reintentos_en_cadena_dan_tokens_distintos(catalogo: list[dict]) -> None:
    tokens = Tokens()
    t = REINTENTAR
    primero = de_tipo(decidir(orden(intentos=0), t, posicion(), [], CFG, tokens, cot(), HORA), EnviarOrden)
    segundo = de_tipo(decidir(orden(intentos=1, token=primero[0].orden.token), t, posicion(), [], CFG, tokens,
                              cot(), HORA), EnviarOrden)
    assert len({TOKEN_RECHAZADO, primero[0].orden.token, segundo[0].orden.token}) == 3


@pytest.mark.parametrize("valor, reintenta", [
    pytest.param(0, False, id="R-B-07-config-0"),
    pytest.param(None, True, id="R-B-07-config-null-defecto-2"),
    pytest.param(1.0, True, id="R-B-07-config-float-entero"),
])
def test_reintentos_de_la_config(catalogo: list[dict], valor: Any, reintenta: bool) -> None:
    cfg = copy.deepcopy(CFG)
    cfg["entrada"]["reintentos_rechazo_conocido"] = valor
    acciones = decidir(orden(), REINTENTAR, posicion(), [], cfg, Tokens(), cot(), HORA)
    assert bool(de_tipo(acciones, EnviarOrden)) is reintenta


@pytest.mark.parametrize("valor", [
    pytest.param(-1, id="negativo"), pytest.param(1.5, id="fraccion"), pytest.param(True, id="bool"),
    pytest.param("2", id="texto"), pytest.param(float("nan"), id="nan"),
])
def test_reintentos_de_la_config_invalidos(catalogo: list[dict], valor: Any) -> None:
    cfg = copy.deepcopy(CFG)
    cfg["entrada"]["reintentos_rechazo_conocido"] = valor
    with pytest.raises(ValueError):
        decidir(orden(), tratamiento(catalogo, "postonly_cruza"), posicion(), [], cfg, Tokens(), cot(), HORA)


def test_reintentar_usa_la_cantidad_pendiente(catalogo: list[dict]) -> None:
    acciones = decidir(orden(qty=500, llenas=200), REINTENTAR, posicion(), [], CFG, Tokens(), cot(), HORA)
    assert de_tipo(acciones, EnviarOrden)[0].orden.qty == 300
    nada = decidir(orden(qty=500, llenas=500), REINTENTAR, posicion(), [], CFG, Tokens(), cot(), HORA)
    assert de_tipo(nada, EnviarOrden) == [] and anotacion(nada, "pausa") is not None


@pytest.mark.parametrize("proposito, post_only_cfg, esperado", [
    pytest.param(Proposito.ENTRADA_AGREGAR, True, True, id="R-B-01-agregar-postonly"),
    pytest.param(Proposito.ENTRADA_AGREGAR, False, False, id="R-B-01-agregar-sin-postonly-por-config"),
    pytest.param(Proposito.TP_AGREGAR, False, True, id="R-D-03-tp-agregar"),
    pytest.param(Proposito.ENTRADA_CRUCE, True, False, id="R-B-01-cruce-remueve"),
])
def test_reintentar_conserva_post_only(catalogo: list[dict], proposito: Proposito, post_only_cfg: bool,
                                       esperado: bool) -> None:
    cfg = copy.deepcopy(CFG)
    cfg["entrada"]["post_only"] = post_only_cfg
    lado = Lado.COMPRA if proposito is Proposito.TP_AGREGAR else Lado.CORTO
    # la cuenta corta 500: el reenvío de la salida cabe entero (D2-10 no lo recorta)
    acciones = decidir(orden(proposito=proposito, lado=lado), REINTENTAR, posicion(-500), [], cfg, Tokens(), cot(),
                       HORA)
    assert de_tipo(acciones, EnviarOrden)[0].orden.post_only is esperado


def test_reintentar_mercado_sin_precio(catalogo: list[dict]) -> None:
    o = orden(proposito=Proposito.TP_CRUCE, lado=Lado.COMPRA, tipo=TipoOrden.MERCADO, precio=None)
    acciones = decidir(o, tratamiento(catalogo, "postonly_cruza"), posicion(-100), [
        stop_compra(Proposito.STOP_EMERGENCIA)], CFG, Tokens(), cot(), HORA)
    nueva = de_tipo(acciones, EnviarOrden)[0].orden
    assert nueva.tipo is TipoOrden.MERCADO and nueva.precio is None and nueva.post_only is False


@pytest.mark.parametrize("precio, bid, esperado, ruta", [
    pytest.param("3.45", "3.44", "3.46", "SAGEREB", id="SSR-precio+1tick"),
    pytest.param("3.45", "3.50", "3.51", "SAGEREB", id="SSR-bid-por-encima-bid+1tick"),
    pytest.param("0.5000", None, "0.5001", "MIAX", id="SSR-penny-tick-0.0001-sin-bid"),
    pytest.param("0.9999", None, "1.00", "SAGEREB", id="SSR-cruza-1$-ruta-del-tramo-nuevo"),
])
def test_subir_tick_ssr(catalogo: list[dict], precio: str, bid: Optional[str], esperado: str, ruta: str) -> None:
    ruta_original = "SAGEREB" if D(precio) >= 1 else "MIAX"
    c = Cotizacion(ticker=TICKER, bid=D(bid) if bid else None, ask=None, last=None)
    acciones = decidir(orden(precio=D(precio), ruta=ruta_original, notas="SSR stocks are prohibited from shorting"),
                       tratamiento(catalogo, "ssr"), posicion(), [], CFG, Tokens(), c, HORA)
    nueva = de_tipo(acciones, EnviarOrden)[0].orden
    assert isinstance(nueva.precio, Decimal) and nueva.precio == D(esperado)
    assert nueva.ruta == ruta


@pytest.mark.parametrize("o", [
    pytest.param(orden(proposito=Proposito.TP_CRUCE, lado=Lado.COMPRA), id="SSR-compra-no-aplica"),
    pytest.param(orden(tipo=TipoOrden.MERCADO, precio=None), id="SSR-mercado-sin-precio"),
])
def test_subir_tick_ssr_no_aplicable_pausa(catalogo: list[dict], o: Orden) -> None:
    tokens = Tokens()
    acciones = decidir(o, tratamiento(catalogo, "ssr"), posicion(), [], CFG, tokens, cot(), HORA)
    assert de_tipo(acciones, EnviarOrden) == [] and tokens.dados == []
    assert anotacion(acciones, "pausa")["estado"] == "pausado"


def test_recalcular_bp(catalogo: list[dict]) -> None:
    tokens = Tokens()
    acciones = decidir(orden(notas="Not Enough Buying Power"), tratamiento(catalogo, "bp_insuficiente"),
                       posicion(), [], CFG, tokens, cot(), HORA)
    assert [type(a) for a in acciones] == [Anotar, Avisar, Consultar, Programar]
    assert acciones[2] == Consultar("GET BP")
    prog = acciones[3]
    assert prog.clave == "reintento_rechazo" and prog.en_s == R.ESPERA_RESPUESTA_BP_S
    assert prog.datos["token_nuevo"] == tokens.dados[0] != TOKEN_RECHAZADO
    assert prog.datos["token_original"] == TOKEN_RECHAZADO and prog.datos["intentos"] == 1
    assert prog.datos["qty"] == 500 and prog.datos["ticker"] == TICKER
    assert de_tipo(acciones, EnviarOrden) == []


def test_recomprar_locate(catalogo: list[dict]) -> None:
    tokens = Tokens()
    acciones = decidir(orden(notas="Rejected: 0 shares available", intentos=1), tratamiento(catalogo, "sin_locate"),
                       posicion(), [], CFG, tokens, cot(), HORA)
    prog = de_tipo(acciones, Programar)
    assert len(prog) == 1 and prog[0].clave == "locate_recomprar" and prog[0].en_s == 0.0
    assert prog[0].datos["token_nuevo"] == tokens.dados[0] and prog[0].datos["intentos"] == 2
    assert anotacion(acciones, "rechazo")["decision"] == "reintento"
    assert anotacion(acciones, "pausa") is None and de_tipo(acciones, EnviarOrden) == []


def test_recomprar_locate_solo_para_cortos(catalogo: list[dict]) -> None:
    o = orden(proposito=Proposito.TP_CRUCE, lado=Lado.COMPRA, notas="Locate required")
    acciones = decidir(o, tratamiento(catalogo, "sin_locate"), posicion(), [], CFG, Tokens(), cot(), HORA)
    assert de_tipo(acciones, Programar) == [] and anotacion(acciones, "pausa") is not None


def test_conocido_sin_tratamiento_pausa_a_la_primera(catalogo: list[dict]) -> None:
    tokens = Tokens()
    acciones = decidir(orden(notas="Invalid quantity"), tratamiento(catalogo, "cantidad_invalida"), posicion(), [],
                       CFG, tokens, cot(), HORA)
    assert tokens.dados == [] and de_tipo(acciones, EnviarOrden) == []
    assert anotacion(acciones, "pausa")["estado"] == "pausado" and aviso(acciones).nivel is Nivel.AVISO


# ── decidir: desconocido y persistente (R-B-07 (3), EP-1) ───────────────────
@pytest.mark.parametrize("neta, vivas", [
    pytest.param(0, [], id="R-B-07-plana-esta-cubierta"),
    pytest.param(-100, [stop_compra(Proposito.STOP_EMERGENCIA)], id="R-B-07-emergencia-aceptada"),
    pytest.param(-100, [stop_compra(Proposito.STOP_EMERGENCIA, estado=EstadoOrden.HOLD)], id="R-B-07-emergencia-hold"),
    pytest.param(-100, [stop_compra(Proposito.STOP_PROTECCION)], id="R-C-10.4-proteccion-cubre"),
])
def test_desconocido_cubierta_pausa_nivel_2(catalogo: list[dict], neta: int, vivas: list[Orden]) -> None:
    tokens = Tokens()
    o = orden(notas="Weird broker thing 42")
    acciones = decidir(o, clasificar(o.notas, catalogo), posicion(neta), vivas, CFG, tokens, cot(), HORA)
    assert [type(a) for a in acciones] == [Anotar, Anotar, Avisar]
    pausa = anotacion(acciones, "pausa")
    assert pausa["ticker"] == TICKER and pausa["estado"] == EstadoTicker.PAUSADO.value
    assert pausa["cubierta"] is True and pausa["notas"] == "Weird broker thing 42"
    assert "Weird broker thing 42" in pausa["motivo"]
    a = aviso(acciones)
    assert a.nivel is Nivel.AVISO and a.grupo is Grupo.B
    assert "«Weird broker thing 42»" in a.texto and "PAUSADO" in a.texto and "DESCONOCIDO" in a.texto
    assert tokens.dados == []


@pytest.mark.parametrize("vivas", [
    pytest.param([], id="EP-1-sin-stops"),
    pytest.param([stop_compra(Proposito.STOP_EMERGENCIA, estado=EstadoOrden.SENDING)], id="EP-1-emergencia-sending"),
    pytest.param([stop_compra(Proposito.STOP_PRINCIPAL, disparo=D("10"), limite=D("10.30"))],
                 id="EP-1-solo-principal-no-cubre"),
    pytest.param([stop_compra(Proposito.STOP_EMERGENCIA, qty=60)], id="EP-1-emergencia-corta"),
])
def test_desconocido_sin_cubrir_control_humano_nivel_3_sin_ordenes(catalogo: list[dict], vivas: list[Orden]) -> None:
    tokens = Tokens()
    o = orden(proposito=Proposito.TP_CRUCE, lado=Lado.COMPRA, notas="???")
    acciones = decidir(o, clasificar(o.notas, catalogo), posicion(-100), vivas, CFG, tokens, cot(), HORA)
    assert de_tipo(acciones, EnviarOrden) == [] and de_tipo(acciones, Cancelar) == []
    assert de_tipo(acciones, CancelarTicker) == [], "EP-1: el bot NO cierra por su cuenta"
    assert tokens.dados == []
    a = aviso(acciones)
    assert a.nivel is Nivel.MAXIMO and "CONTROL HUMANO" in a.texto and "SIN STOP" in a.texto
    pausa = anotacion(acciones, "pausa")
    assert pausa["estado"] == EstadoTicker.CONTROL_HUMANO.value and pausa["cubierta"] is False
    assert anotacion(acciones, "rechazo")["decision"] == "control_humano"


def test_conocido_agotado_sin_cubrir_control_humano(catalogo: list[dict]) -> None:
    o = orden(proposito=Proposito.TP_CRUCE, lado=Lado.COMPRA, intentos=2, notas="Not Enough Buying Power")
    acciones = decidir(o, tratamiento(catalogo, "bp_insuficiente"), posicion(-100), [], CFG, Tokens(), cot(), HORA)
    assert aviso(acciones).nivel is Nivel.MAXIMO
    assert anotacion(acciones, "pausa")["estado"] == "control_humano"
    assert de_tipo(acciones, Consultar) == [] and de_tipo(acciones, EnviarOrden) == []


def test_reintento_sin_cubrir_avisa_nivel_3(catalogo: list[dict]) -> None:
    o = orden(proposito=Proposito.TP_CRUCE, lado=Lado.COMPRA, notas="PostOnly would cross")
    acciones = decidir(o, tratamiento(catalogo, "postonly_cruza"), posicion(-100), [], CFG, Tokens(), cot(), HORA)
    assert len(de_tipo(acciones, EnviarOrden)) == 1 and aviso(acciones).nivel is Nivel.MAXIMO


def test_nivel_del_catalogo_manda_si_es_mayor(catalogo: list[dict]) -> None:
    o = orden(notas="MaxLoss reached: all new orders will be rejected")
    acciones = decidir(o, clasificar(o.notas, catalogo), posicion(), [], CFG, Tokens(), cot(), HORA)
    assert aviso(acciones).nivel is Nivel.MAXIMO
    assert anotacion(acciones, "pausa")["estado"] == "pausado", "cubierta: pausa, aunque el aviso sea 3"


@pytest.mark.parametrize("actual, neta, esperado", [
    pytest.param(EstadoTicker.NORMAL, 0, "pausado", id="R-B-07-normal-a-pausado"),
    pytest.param(EstadoTicker.NORMAL, -100, "control_humano", id="EP-1-normal-a-control"),
    pytest.param(EstadoTicker.PAUSADO, 0, None, id="R-B-07-ya-pausado"),
    pytest.param(EstadoTicker.PAUSADO, -100, "control_humano", id="EP-1-pausado-sube-a-control"),
    pytest.param(EstadoTicker.CONTROL_HUMANO, 0, None, id="EP-1-nunca-se-rebaja"),
    pytest.param(EstadoTicker.BS, -100, None, id="R-G-03-bs-manda"),
    pytest.param(EstadoTicker.HALT, 0, None, id="R-F-01-halt-manda"),
    pytest.param(EstadoTicker.SIN_SIMBOLO, 0, None, id="A7-sin-simbolo-manda"),
])
def test_estado_nunca_se_rebaja(catalogo: list[dict], actual: EstadoTicker, neta: int,
                                esperado: Optional[str]) -> None:
    o = orden(proposito=Proposito.TP_CRUCE, lado=Lado.COMPRA, notas="???")
    acciones = decidir(o, DESCONOCIDO, posicion(neta, actual), [], CFG, Tokens(), cot(), HORA)
    pausa = anotacion(acciones, "pausa")
    assert (pausa["estado"] if pausa else None) == esperado
    assert anotacion(acciones, "rechazo")["estado_nuevo"] == esperado
    assert len(de_tipo(acciones, Avisar)) == 1, "el aviso sale igual"


@pytest.mark.parametrize("estado, o, reintenta", [
    pytest.param(EstadoTicker.PAUSADO, orden(), False, id="R-B-07-pausado-no-reintenta-entrada"),
    pytest.param(EstadoTicker.PAUSADO, orden(proposito=Proposito.TP_AGREGAR, lado=Lado.COMPRA), True,
                 id="R-B-07-pausado-salidas-siguen"),
    pytest.param(EstadoTicker.HALT, orden(proposito=Proposito.DESCONOCIDA), False, id="R-F-01-halt-no-abre-corto"),
    pytest.param(EstadoTicker.HALT, orden(proposito=Proposito.HORA_AGREGAR, lado=Lado.COMPRA), True,
                 id="R-F-01-halt-salida-si"),
    pytest.param(EstadoTicker.BS, orden(proposito=Proposito.TP_AGREGAR, lado=Lado.COMPRA), False,
                 id="R-G-03-bs-nada"),
    pytest.param(EstadoTicker.CONTROL_HUMANO, orden(proposito=Proposito.TP_AGREGAR, lado=Lado.COMPRA), False,
                 id="EP-1-control-humano-nada"),
    pytest.param(EstadoTicker.SIN_SIMBOLO, orden(proposito=Proposito.TP_AGREGAR, lado=Lado.COMPRA), False,
                 id="A7-sin-simbolo-nada"),
])
def test_reintento_segun_estado_del_ticker(catalogo: list[dict], estado: EstadoTicker, o: Orden,
                                           reintenta: bool) -> None:
    """R-B-07 / R-F-01 / R-G-03: qué se reintenta según el estado (cuenta corta 500: las salidas caben, D2-10)."""
    tokens = Tokens()
    acciones = decidir(o, REINTENTAR, posicion(-500, estado), [], CFG, tokens, cot(), HORA)
    assert bool(de_tipo(acciones, EnviarOrden)) is reintenta
    assert bool(tokens.dados) is reintenta


# ── decidir: stops (R-C-03 dentro de R-B-07) ────────────────────────────────
@pytest.mark.parametrize("intentos", [0, 1, 2, 3, 4])
def test_stop_rechazado_reintenta_por_r_c_03(catalogo: list[dict], intentos: int) -> None:
    tokens = Tokens()
    o = stop_compra(Proposito.STOP_EMERGENCIA, estado=EstadoOrden.REJECTED, intentos=intentos,
                    notas="Not Enough Buying Power", primer_intento_en=1000.0)
    acciones = decidir(o, tratamiento(catalogo, "bp_insuficiente"), posicion(-100), [o], CFG, tokens, cot(),
                       HORA, ahora=1010.0)
    assert [type(a) for a in acciones] == [Anotar, Avisar, Programar]
    prog = acciones[-1]
    assert prog.clave == "stop_reintento" and prog.en_s == 2.0 and prog.datos["intento"] == intentos + 1
    assert tokens.dados == [] and de_tipo(acciones, EnviarOrden) == [] and de_tipo(acciones, Consultar) == []
    assert aviso(acciones).nivel is Nivel.MAXIMO, "stop rechazado = acciones sin cubrir"
    assert anotacion(acciones, "rechazo")["decision"] == "stop_reintento"


def test_stop_agotado_avisa_3_y_no_cierra(catalogo: list[dict]) -> None:
    o = stop_compra(Proposito.STOP_EMERGENCIA, estado=EstadoOrden.REJECTED, intentos=5, notas="???")
    acciones = decidir(o, DESCONOCIDO, posicion(-100), [o], CFG, Tokens(), cot(), HORA, ahora=1500.0)
    assert de_tipo(acciones, Programar) == [] and de_tipo(acciones, EnviarOrden) == []
    assert de_tipo(acciones, CancelarTicker) == []
    a = aviso(acciones)
    assert a.nivel is Nivel.MAXIMO and "STOP SIN PONER" in a.texto and "CONTROL HUMANO" in a.texto
    assert anotacion(acciones, "pausa")["estado"] == "control_humano"
    assert anotacion(acciones, "rechazo")["decision"] == "stop_agotado"


def test_principal_rechazado_con_emergencia_viva(catalogo: list[dict]) -> None:
    principal = stop_compra(Proposito.STOP_PRINCIPAL, estado=EstadoOrden.REJECTED, token=126800009,
                            disparo=D("10"), limite=D("10.30"), notas="Not Enough Buying Power")
    emergencia = stop_compra(Proposito.STOP_EMERGENCIA)
    acciones = decidir(principal, tratamiento(catalogo, "bp_insuficiente"), posicion(-100), [principal, emergencia],
                       CFG, Tokens(), cot(), HORA, ahora=1000.0)
    assert aviso(acciones).nivel is Nivel.AVISO and anotacion(acciones, "pausa") is None
    assert de_tipo(acciones, Programar)[0].clave == "stop_reintento"


def test_stop_desconocido_pausa_y_sigue_reintentando(catalogo: list[dict]) -> None:
    principal = stop_compra(Proposito.STOP_PRINCIPAL, estado=EstadoOrden.REJECTED, token=126800009,
                            disparo=D("10"), limite=D("10.30"), notas="???")
    emergencia = stop_compra(Proposito.STOP_EMERGENCIA)
    acciones = decidir(principal, DESCONOCIDO, posicion(-100), [principal, emergencia], CFG, Tokens(), cot(), HORA,
                       ahora=1000.0)
    assert anotacion(acciones, "pausa")["estado"] == "pausado"
    assert de_tipo(acciones, Programar)[0].clave == "stop_reintento", "R-B-07 (3): los stops siguen"


def test_stop_desconocida_por_tipo(catalogo: list[dict]) -> None:
    o = stop_compra(Proposito.DESCONOCIDA, estado=EstadoOrden.REJECTED, notas="???")
    acciones = decidir(o, DESCONOCIDO, posicion(-100), [], CFG, Tokens(), cot(), HORA, ahora=1000.0)
    assert de_tipo(acciones, Programar)[0].clave == "stop_reintento"


def test_stop_en_bs_no_se_repone(catalogo: list[dict]) -> None:
    o = stop_compra(Proposito.STOP_EMERGENCIA, estado=EstadoOrden.REJECTED, notas="???")
    acciones = decidir(o, DESCONOCIDO, posicion(-100, EstadoTicker.BS), [], CFG, Tokens(), cot(), HORA, ahora=1.0)
    assert de_tipo(acciones, Programar) == [] and anotacion(acciones, "pausa") is None
    assert anotacion(acciones, "rechazo")["decision"] == "sin_reintento_bs"


def test_stop_sin_ahora_usa_ultima_act(catalogo: list[dict]) -> None:
    o = stop_compra(Proposito.STOP_EMERGENCIA, estado=EstadoOrden.REJECTED, notas="???", primer_intento_en=1000.0,
                    ultima_act=1400.0)
    prog = de_tipo(decidir(o, DESCONOCIDO, posicion(-100), [], CFG, Tokens(), cot(), HORA), Programar)[0]
    assert prog.datos["segundos_desde_primero"] == 400.0 and prog.datos["fuera_de_ventana"] is True


# ── decidir: registro, aviso, pureza y errores ──────────────────────────────
def test_anotar_rechazo_completo_y_serializable(catalogo: list[dict]) -> None:
    o = orden(notas="Not Enough Buying Power", id_das=505)
    acciones = decidir(o, tratamiento(catalogo, "bp_insuficiente"), posicion(), [], CFG, Tokens(), cot(), HORA)
    datos = anotacion(acciones, "rechazo")
    json.dumps(datos)   # el diario escribe JSON: nada de Decimal ni enums sueltos
    assert datos["notas"] == "Not Enough Buying Power" and datos["tratamiento"] == "bp_insuficiente"
    assert datos["accion"] == "recalcular_bp" and datos["conocido"] is True and datos["intentos"] == 0
    assert datos["cubierta"] is True and datos["descubiertas"] == 0 and datos["ticker"] == TICKER
    assert datos["token"] == TOKEN_RECHAZADO and datos["id_das"] == 505 and datos["hora"] == HORA.isoformat()
    assert datos["orden"]["precio"] == "3.45" and datos["orden"]["lado"] == "SS" and datos["orden"]["qty"] == 500
    assert datos["cotizacion"] == {"bid": "3.44", "ask": "3.46", "last": "3.45"}
    assert acciones[0] is not None and isinstance(acciones[0], Anotar), "write-ahead: el registro va primero"


def test_aviso_texto_literal_orden_y_estado(catalogo: list[dict]) -> None:
    o = orden(notas="Rejected: Security Not Shortable  (code 17)")
    a = aviso(decidir(o, clasificar(o.notas, catalogo), posicion(), [], CFG, Tokens(), cot(), HORA))
    assert "«Rejected: Security Not Shortable  (code 17)»" in a.texto, "R-B-07 (1): el texto literal, sin tocar"
    assert "SS 500 XYZ LMT" in a.texto and "SAGEREB" in a.texto and str(TOKEN_RECHAZADO) in a.texto
    assert "Ticker: normal, neta 0" in a.texto
    assert a.clave == f"rechazo:{TICKER}:{TOKEN_RECHAZADO}" and a.grupo is Grupo.B


def test_decidir_no_muta_nada(catalogo: list[dict]) -> None:
    o = orden(notas="SSR stocks are prohibited from shorting on the BID or lower")
    pos = posicion(-100)
    vivas = [stop_compra(Proposito.STOP_EMERGENCIA)]
    c = cot()
    cfg = copy.deepcopy(CFG)
    antes = copy.deepcopy((o, pos, vivas, c, cfg))
    decidir(o, tratamiento(catalogo, "ssr"), pos, vivas, cfg, Tokens(), c, HORA)
    assert (o, pos, vivas, c, cfg) == antes


def test_decidir_con_la_config_real(cfg: Any, catalogo: list[dict]) -> None:
    acciones = decidir(orden(), REINTENTAR, posicion(), [], cfg, Tokens(), cot(), HORA)
    assert len(de_tipo(acciones, EnviarOrden)) == 1
    po = decidir(orden(), tratamiento(catalogo, "postonly_cruza"), posicion(), [], cfg, Tokens(), cot(), HORA)
    assert de_tipo(po, EnviarOrden) == [] and de_tipo(po, Programar)[0].clave.startswith("cruce_postonly:")
    tp = decidir(orden(proposito=Proposito.TP_AGREGAR, lado=Lado.COMPRA, qty=100, lote_id=LOTE_ID),
                 tratamiento(catalogo, "postonly_cruza"), posicion(-100), [], cfg, Tokens(), cot(), HORA)
    assert [e.orden.proposito for e in de_tipo(tp, EnviarOrden)] == [Proposito.TP_CRUCE]
    o = stop_compra(Proposito.STOP_EMERGENCIA, estado=EstadoOrden.REJECTED, notas="???")
    prog = de_tipo(decidir(o, DESCONOCIDO, posicion(-100), [], cfg, Tokens(), cot(), HORA, ahora=5.0), Programar)
    assert prog[0].en_s == 2.0 and prog[0].datos["reintentos"] == 5


@pytest.mark.parametrize("o, pos, cfg, error", [
    pytest.param(orden(ticker="ABC"), posicion(), CFG, ValueError, id="ticker-distinto"),
    pytest.param(orden(ticker=" "), PosicionTicker(ticker=" "), CFG, ValueError, id="sin-ticker-seria-global"),
    pytest.param(orden(), posicion(), {"stops": {}}, ValueError, id="sin-bloque-entrada"),
    pytest.param(orden(), posicion(), {"entrada": {}}, ValueError, id="sin-bloque-stops"),
])
def test_decidir_errores(o: Orden, pos: PosicionTicker, cfg: Any, error: type) -> None:
    with pytest.raises(error):
        decidir(o, DESCONOCIDO, pos, [], cfg, Tokens(), cot(), HORA)


def test_decidir_exige_tratamiento() -> None:
    with pytest.raises(TypeError):
        decidir(orden(), "desconocido", posicion(), [], CFG, Tokens(), cot(), HORA)   # type: ignore[arg-type]


# ── reintento_stop (R-C-03) ─────────────────────────────────────────────────
@pytest.mark.parametrize("intentos, hay", [
    pytest.param(0, True, id="R-C-03-1"), pytest.param(1, True, id="R-C-03-2"),
    pytest.param(2, True, id="R-C-03-3"), pytest.param(3, True, id="R-C-03-4"),
    pytest.param(4, True, id="R-C-03-5"), pytest.param(5, False, id="R-C-03-para-tras-5"),
    pytest.param(9, False, id="R-C-03-sigue-parado"),
])
def test_reintento_stop_5_y_para(intentos: int, hay: bool) -> None:
    o = stop_compra(Proposito.STOP_EMERGENCIA, intentos=intentos, primer_intento_en=1000.0)
    p = reintento_stop(o, CFG["stops"], 1010.0)
    if not hay:
        assert p is None
        return
    assert isinstance(p, Programar) and p.clave == "stop_reintento" and p.en_s == 2.0
    d = p.datos
    assert d["intento"] == intentos + 1 and d["reintentos"] == 5 and d["token_rechazado"] == o.token
    assert d["ticker"] == TICKER and d["proposito"] == "stop_emergencia" and d["nivel"] == "10"
    assert d["lote_id"] == "L1" and d["primer_intento_en"] == 1000.0 and d["segundos_desde_primero"] == 10.0
    assert d["fuera_de_ventana"] is False
    json.dumps(d)


def test_reintento_stop_cuenta_cinco_llamadas_seguidas() -> None:
    o = stop_compra(Proposito.STOP_EMERGENCIA, primer_intento_en=1.0)
    n = 0
    while (p := reintento_stop(o, CFG["stops"], 2.0)) is not None:
        n += 1
        o = stop_compra(Proposito.STOP_EMERGENCIA, intentos=p.datos["intento"], primer_intento_en=1.0)
        assert n <= 10
    assert n == 5


@pytest.mark.parametrize("cfg_stops, intentos, esperado", [
    pytest.param({}, 4, 2.0, id="R-C-03-defectos-5-y-2s"),
    pytest.param({}, 5, None, id="R-C-03-defecto-para-en-5"),
    pytest.param({"reintentos": 3, "separacion_reintentos_s": 0.5}, 2, 0.5, id="R-C-03-config-3"),
    pytest.param({"reintentos": 3, "separacion_reintentos_s": 0.5}, 3, None, id="R-C-03-config-para-en-3"),
    pytest.param({"reintentos": 0}, 0, None, id="R-C-03-cero-reintentos"),
    pytest.param({"reintentos": None, "separacion_reintentos_s": None}, 0, 2.0, id="R-C-03-null-defecto"),
])
def test_reintento_stop_config(cfg_stops: dict, intentos: int, esperado: Optional[float]) -> None:
    p = reintento_stop(stop_compra(Proposito.STOP_PRINCIPAL, intentos=intentos), cfg_stops, 10.0)
    assert (p.en_s if p else None) == esperado


@pytest.mark.parametrize("primero, enviada, ahora, segundos, fuera", [
    pytest.param(1000.0, 0.0, 1299.0, 299.0, False, id="R-C-03-dentro-de-5-min"),
    pytest.param(1000.0, 0.0, 1301.0, 301.0, True, id="R-C-03-fuera-de-5-min"),
    pytest.param(0.0, 900.0, 1000.0, 100.0, False, id="R-C-03-sin-primer-intento-usa-enviada"),
    pytest.param(0.0, 0.0, 1000.0, 0.0, False, id="R-C-03-sin-nada-cuenta-desde-ahora"),
    pytest.param(1000.0, 0.0, 900.0, 0.0, False, id="R-C-03-reloj-hacia-atras-no-negativo"),
])
def test_reintento_stop_ventana(primero: float, enviada: float, ahora: float, segundos: float, fuera: bool) -> None:
    o = stop_compra(Proposito.STOP_EMERGENCIA, primer_intento_en=primero, enviada_en=enviada)
    d = reintento_stop(o, CFG["stops"], ahora).datos
    assert d["segundos_desde_primero"] == segundos and d["fuera_de_ventana"] is fuera


@pytest.mark.parametrize("cfg_stops, ahora, error", [
    pytest.param(None, 1.0, TypeError, id="cfg-no-dict"),
    pytest.param({"reintentos": -1}, 1.0, ValueError, id="reintentos-negativos"),
    pytest.param({"reintentos": 2.5}, 1.0, ValueError, id="reintentos-fraccion"),
    pytest.param({"separacion_reintentos_s": "2"}, 1.0, ValueError, id="separacion-texto"),
    pytest.param({"separacion_reintentos_s": -1}, 1.0, ValueError, id="separacion-negativa"),
    pytest.param({"ventana_min": math.inf}, 1.0, ValueError, id="ventana-infinita"),
    pytest.param({}, math.nan, ValueError, id="ahora-nan"),
    pytest.param({}, None, ValueError, id="ahora-none"),
])
def test_reintento_stop_errores(cfg_stops: Any, ahora: Any, error: type) -> None:
    with pytest.raises(error):
        reintento_stop(stop_compra(Proposito.STOP_EMERGENCIA), cfg_stops, ahora)


def test_reintento_stop_no_muta() -> None:
    o = stop_compra(Proposito.STOP_EMERGENCIA, intentos=2)
    antes = copy.deepcopy(o)
    reintento_stop(o, CFG["stops"], 5.0)
    assert o == antes


# ── tras_cancel_o_replace_rej (injerto A §8.7) ──────────────────────────────
@pytest.mark.parametrize("accion, rotulo", [
    pytest.param("CancelRej", "[CancelRej]", id="§8.7-cancelrej"),
    pytest.param("ReplaceRej", "[ReplaceRej]", id="§8.7-replacerej"),
    pytest.param(None, "[CancelRej/ReplaceRej]", id="§8.7-sin-accion"),
])
def test_tras_cancel_o_replace_rej_barrido(accion: Optional[str], rotulo: str) -> None:
    o = stop_compra(Proposito.STOP_EMERGENCIA, id_das=502, notas="Order not found")
    acciones = tras_cancel_o_replace_rej(o, accion)
    assert [type(a) for a in acciones] == [Avisar, Consultar, Programar]
    a, consulta, prog = acciones
    assert a.nivel is Nivel.AVISO and a.grupo is Grupo.B and rotulo in a.texto and "«Order not found»" in a.texto
    assert a.clave == f"cancel_replace_rej:{TICKER}:{o.token}"
    assert consulta == Consultar("GET ORDERS")
    assert prog.clave == "barrido" and prog.en_s == 0.0
    assert prog.datos["ticker"] == TICKER and prog.datos["id_das"] == 502 and prog.datos["token"] == o.token
    assert de_tipo(acciones, EnviarOrden) == [] and de_tipo(acciones, Cancelar) == []


# ── pureza del módulo ───────────────────────────────────────────────────────
def test_modulo_puro() -> None:
    fuente = Path(R.__file__).read_text(encoding="utf-8")
    # html (D2-08: escapar los avisos), protocolo (A-06: cmd_get) y reglas.salidas (D2-09: el cruce del
    # PostOnly usa tp_al_vencer / orden_al_ask) son puros.
    permitidos = {"__future__", "html", "json", "math", "re", "collections.abc", "dataclasses", "datetime", "decimal",
                  "pathlib", "typing", "app.bot_das.tipos", "app.bot_das.protocolo", "app.bot_das.reglas",
                  "app.bot_das.reglas.precios", "app.bot_das.reglas.stops"}
    importados: set[str] = set()
    nombres: set[str] = set()
    atributos: set[str] = set()
    for nodo in ast.walk(ast.parse(fuente)):
        if isinstance(nodo, ast.Import):
            importados.update(a.name for a in nodo.names)
        elif isinstance(nodo, ast.ImportFrom):
            importados.add(nodo.module or "")
        elif isinstance(nodo, ast.Name):
            nombres.add(nodo.id)
        elif isinstance(nodo, ast.Attribute):
            atributos.add(nodo.attr)
    assert importados <= permitidos, importados - permitidos
    assert not nombres & {"open", "print", "time", "logging", "os"}, nombres & {"open", "print", "time", "os"}
    assert not atributos & {"now", "utcnow", "today", "monotonic", "getenv", "environ"}
    # la única lectura de fichero es la de cargar_catalogo (Path.read_bytes), fuera del camino por mensaje
    assert fuente.count("read_bytes") == 1 and "read_text" not in fuente
    assert isinstance(RUTA_CATALOGO, Path) and RUTA_CATALOGO.is_file()


# ── D2-09: «PostOnly would cross» pasa al cruce, sin reintento ni pausa ─────
@pytest.mark.parametrize("intentos", [0, 2, 5], ids=["D2-09-primero", "D2-09-agotados-igual", "D2-09-muchos"])
def test_D2_09_postonly_en_la_entrada_pasa_al_cruce_sin_pausa(catalogo: list[dict], intentos: int) -> None:
    """D2-09: la entrada PostOnly rechazada NO se reintenta al mismo precio: temporizador del cruce de R-B-01 v3."""
    tokens = Tokens()
    o = orden(intentos=intentos, qty=500, llenas=100)
    acciones = decidir(o, tratamiento(catalogo, "postonly_cruza"), posicion(), [], CFG, tokens, cot(), HORA)
    assert de_tipo(acciones, EnviarOrden) == [] and tokens.dados == [], "ni orden al mismo precio ni token"
    assert anotacion(acciones, "pausa") is None, "un PostOnly rechazado no es un error: sin pausa"
    prog = de_tipo(acciones, Programar)
    assert len(prog) == 1 and prog[0].clave == f"cruce_postonly:{TOKEN_RECHAZADO}" and prog[0].en_s == 0.0
    assert prog[0].datos["qty"] == 400 and prog[0].datos["token_rechazado"] == TOKEN_RECHAZADO
    assert prog[0].datos["proposito"] == "entrada_agregar" and prog[0].datos["ticker"] == TICKER
    rechazo = anotacion(acciones, "rechazo")
    assert rechazo["decision"] == "pasar_a_cruce" and rechazo["estado_nuevo"] is None
    assert aviso(acciones).nivel is Nivel.AVISO and "cruce" in aviso(acciones).texto


def test_D2_09_postonly_del_tp_cruza_al_ask_con_techo(catalogo: list[dict]) -> None:
    """D2-09: el TP que agregaba pasa YA al cruce de R-D-03 v2 (al ask con techo 3 %), con token nuevo y sin pausa."""
    tokens = Tokens()
    o = orden(proposito=Proposito.TP_AGREGAR, lado=Lado.COMPRA, qty=100, lote_id=LOTE_ID, intentos=1)
    acciones = decidir(o, tratamiento(catalogo, "postonly_cruza"), posicion(-100), [], CFG, tokens, cot(), HORA)
    enviadas = de_tipo(acciones, EnviarOrden)
    assert len(enviadas) == 1
    nueva = enviadas[0].orden
    assert (nueva.proposito, nueva.lado, nueva.qty, nueva.precio, nueva.post_only) == (
        Proposito.TP_CRUCE, Lado.COMPRA, 100, D("3.46"), False)
    assert nueva.ruta == "SAGEPRO" and nueva.lote_id == LOTE_ID and tokens.dados == [nueva.token]
    rechazo = anotacion(acciones, "rechazo")
    assert rechazo["decision"] == "pasar_a_cruce" and rechazo["token_nuevo"] == nueva.token
    assert rechazo["intentos_nuevo"] == 1, "el cruce no gasta un reintento"
    assert anotacion(acciones, "pausa") is None


def test_D2_09_postonly_del_tp_fuera_del_techo_es_limbo_sin_orden(catalogo: list[dict]) -> None:
    """D2-09 + R-D-03 v2 (3): con el ask fuera del techo no hay orden ni token: limbo en el aviso, sin pausa."""
    tokens = Tokens()
    o = orden(proposito=Proposito.TP_AGREGAR, lado=Lado.COMPRA, qty=100, lote_id=LOTE_ID)
    acciones = decidir(o, tratamiento(catalogo, "postonly_cruza"), posicion(-100), [], CFG, tokens,
                       cot("3.50", "3.70", "3.45"), HORA)
    assert de_tipo(acciones, EnviarOrden) == [] and tokens.dados == []
    assert anotacion(acciones, "rechazo")["decision"] == "pasar_a_cruce_limbo"
    assert anotacion(acciones, "pausa") is None and "LIMBO" in aviso(acciones).texto


@pytest.mark.parametrize("proposito, esperado", [
    pytest.param(Proposito.HORA_AGREGAR, Proposito.HORA_ASK, id="D2-09-hora-al-ask"),
    pytest.param(Proposito.CIERRE_REINICIO, Proposito.CIERRE_REINICIO, id="D2-09-reinicio-al-ask"),
])
def test_D2_09_postonly_de_la_hora_va_al_ask_sin_techo(catalogo: list[dict], proposito: Proposito,
                                                      esperado: Proposito) -> None:
    """D2-09 + R-D-08: la hora no se negocia: al ask SIN techo aunque esté un 20 % sobre el último."""
    o = orden(proposito=proposito, lado=Lado.COMPRA, qty=100, lote_id=LOTE_ID)
    acciones = decidir(o, tratamiento(catalogo, "postonly_cruza"), posicion(-100), [], CFG, Tokens(),
                       cot("4.10", "4.14", "3.45"), HORA)
    nueva = de_tipo(acciones, EnviarOrden)[0].orden
    assert (nueva.proposito, nueva.precio, nueva.qty, nueva.post_only) == (esperado, D("4.14"), 100, False)
    assert anotacion(acciones, "pausa") is None


def test_D2_09_postonly_de_la_salida_del_motor_cruza_como_salida_del_motor(catalogo: list[dict]) -> None:
    o = orden(proposito=Proposito.SALIDA_MOTOR_AGREGAR, lado=Lado.COMPRA, qty=100, lote_id=LOTE_ID)
    acciones = decidir(o, tratamiento(catalogo, "postonly_cruza"), posicion(-100), [], CFG, Tokens(), cot(), HORA)
    assert [e.orden.proposito for e in de_tipo(acciones, EnviarOrden)] == [Proposito.SALIDA_MOTOR_CRUCE]


@pytest.mark.parametrize("o, pos, decision", [
    pytest.param(orden(proposito=Proposito.TP_AGREGAR, lado=Lado.COMPRA, qty=100, lote_id="OTRO"), posicion(-100),
                 "sin_cruce", id="D2-09-sin-lote"),
    pytest.param(orden(), posicion(0, EstadoTicker.PAUSADO), "sin_cruce", id="D2-09-entrada-en-pausa"),
    pytest.param(orden(proposito=Proposito.TP_AGREGAR, lado=Lado.COMPRA, qty=100, lote_id=LOTE_ID),
                 posicion(-100, EstadoTicker.BS), "sin_cruce", id="D2-09-bs-nada"),
    pytest.param(orden(proposito=Proposito.TP_AGREGAR, lado=Lado.COMPRA, qty=100, lote_id=LOTE_ID), posicion(0),
                 "sin_cruce", id="D2-09-plana-sin-lote-vivo"),
])
def test_D2_09_postonly_sin_cruce_posible_no_pausa(catalogo: list[dict], o: Orden, pos: PosicionTicker,
                                                  decision: str) -> None:
    tokens = Tokens()
    acciones = decidir(o, tratamiento(catalogo, "postonly_cruza"), pos, [], CFG, tokens, cot(), HORA)
    assert de_tipo(acciones, EnviarOrden) == [] and tokens.dados == []
    assert anotacion(acciones, "rechazo")["decision"] == decision
    assert anotacion(acciones, "pausa") is None, "D2-09: nunca pausa por un PostOnly"
    assert len(de_tipo(acciones, Avisar)) == 1


def test_D2_09_postonly_en_una_orden_que_no_agregaba_se_reintenta_como_antes(catalogo: list[dict]) -> None:
    """D2-09: fuera de los propósitos que agregan (no debería llegar un PostOnly) se trata como «reintentar»."""
    o = orden(proposito=Proposito.TP_CRUCE, lado=Lado.COMPRA, qty=100, intentos=2)
    acciones = decidir(o, tratamiento(catalogo, "postonly_cruza"), posicion(0), [], CFG, Tokens(), cot(), HORA)
    assert anotacion(acciones, "rechazo")["decision"] == "pausa", "agotado como cualquier reintento"


# ── D2-10: el reenvío de una salida nunca supera la posición ───────────────
def _tp_vivo(qty: int, token: int = 126800077, **extra: Any) -> Orden:
    campos: dict[str, Any] = {"estado": EstadoOrden.ACCEPTED}
    campos.update(extra)
    return Orden(token=token, ticker=TICKER, lado=Lado.COMPRA, tipo=TipoOrden.LIMITE, qty=qty, precio=D("3.45"),
                 stop=None, ruta="SAGEREB", proposito=Proposito.TP_AGREGAR, lote_id="L1", nivel=None,
                 origen=Origen.EJECUTOR, **campos)


def test_D2_10_reintento_de_salida_con_la_posicion_plana_no_compra(catalogo: list[dict]) -> None:
    """D2-10: TP_AGREGAR BUY 500 rechazado con la posición ya plana → sin reintento, sin token, sin pausa."""
    tokens = Tokens()
    o = orden(proposito=Proposito.TP_AGREGAR, lado=Lado.COMPRA, qty=500)
    acciones = decidir(o, REINTENTAR, posicion(0), [], CFG, tokens, cot(), HORA)
    assert de_tipo(acciones, EnviarOrden) == [] and tokens.dados == []
    assert anotacion(acciones, "rechazo")["decision"] == "nada_que_reducir"
    assert anotacion(acciones, "pausa") is None


@pytest.mark.parametrize("neta, vivas, esperado", [
    pytest.param(-500, [], 500, id="D2-10-cabe-entera"),
    pytest.param(-500, [_tp_vivo(300)], 200, id="D2-10-otra-salida-viva"),
    pytest.param(-500, [_tp_vivo(300, lvqty=100, llenas=200)], 400, id="D2-10-cuenta-lo-vivo-de-la-otra"),
    pytest.param(-100, [stop_compra(Proposito.STOP_EMERGENCIA, qty=100)], 100, id="D2-10-los-stops-no-descuentan"),
    pytest.param(-100, [_tp_vivo(300, estado=EstadoOrden.CANCELED)], 100, id="D2-10-terminadas-no-cuentan"),
    pytest.param(-500, [_tp_vivo(300, token=TOKEN_RECHAZADO)], 500, id="D2-10-la-rechazada-no-cuenta"),
])
def test_D2_10_reintento_recortado_a_la_posicion(catalogo: list[dict], neta: int, vivas: list[Orden],
                                                 esperado: int) -> None:
    o = orden(proposito=Proposito.TP_AGREGAR, lado=Lado.COMPRA, qty=500)
    acciones = decidir(o, REINTENTAR, posicion(neta), vivas, CFG, Tokens(), cot(), HORA)
    assert [e.orden.qty for e in de_tipo(acciones, EnviarOrden)] == [esperado]


def test_D2_10_otras_salidas_cubren_toda_la_posicion(catalogo: list[dict]) -> None:
    acciones = decidir(orden(proposito=Proposito.HORA_ASK, lado=Lado.COMPRA, qty=100), REINTENTAR, posicion(-100),
                       [_tp_vivo(100)], CFG, Tokens(), cot(), HORA)
    assert de_tipo(acciones, EnviarOrden) == [] and anotacion(acciones, "rechazo")["decision"] == "nada_que_reducir"


def test_D2_10_recalcular_bp_de_una_salida_lleva_la_qty_recortada(catalogo: list[dict]) -> None:
    o = orden(proposito=Proposito.TP_CRUCE, lado=Lado.COMPRA, qty=500, notas="Not Enough Buying Power")
    acciones = decidir(o, tratamiento(catalogo, "bp_insuficiente"), posicion(-100), [], CFG, Tokens(), cot(), HORA)
    assert de_tipo(acciones, Programar)[0].datos["qty"] == 100


def test_D2_10_postonly_del_tp_cruza_solo_lo_que_queda(catalogo: list[dict]) -> None:
    o = orden(proposito=Proposito.TP_AGREGAR, lado=Lado.COMPRA, qty=100, lote_id=LOTE_ID)
    acciones = decidir(o, tratamiento(catalogo, "postonly_cruza"), posicion(-100), [_tp_vivo(60)], CFG, Tokens(),
                       cot(), HORA)
    assert [e.orden.qty for e in de_tipo(acciones, EnviarOrden)] == [40]


def test_D2_10_las_entradas_no_se_recortan(catalogo: list[dict]) -> None:
    acciones = decidir(orden(qty=500), REINTENTAR, posicion(0), [], CFG, Tokens(), cot(), HORA)
    assert [e.orden.qty for e in de_tipo(acciones, EnviarOrden)] == [500]


# ── D2-08: avisos con el HTML escapado (parse_mode HTML de Telegram) ───────
def test_D2_08_aviso_de_rechazo_escapa_el_html_y_el_diario_guarda_el_literal(catalogo: list[dict]) -> None:
    o = orden(notas="<b>x & y</b> Qty > MaxShare")
    acciones = decidir(o, clasificar(o.notas, catalogo), posicion(), [], CFG, Tokens(), cot(), HORA)
    texto = aviso(acciones).texto
    assert "«&lt;b&gt;x &amp; y&lt;/b&gt; Qty &gt; MaxShare»" in texto
    assert "<b>" not in texto and "& y" not in texto and "> MaxShare" not in texto
    assert anotacion(acciones, "rechazo")["notas"] == "<b>x & y</b> Qty > MaxShare", "el diario: literal crudo"


def test_D2_08_cancel_replace_rej_escapa_el_html() -> None:
    o = stop_compra(Proposito.STOP_EMERGENCIA, id_das=502, notas="Order <42> not found & gone")
    texto = de_tipo(tras_cancel_o_replace_rej(o, "Cancel<Rej>"), Avisar)[0].texto
    assert "«Order &lt;42&gt; not found &amp; gone»" in texto and "[Cancel&lt;Rej&gt;]" in texto
    assert "<42>" not in texto


# ── D2-15: R-C-03 (3) mide la subida desde el primer intento ───────────────
def test_D2_15_reintento_stop_anota_precio_del_primer_intento_y_subida() -> None:
    o = stop_compra(Proposito.STOP_EMERGENCIA, intentos=2, primer_intento_en=1000.0)
    d = reintento_stop(o, CFG["stops"], 1010.0, cot=cot(last="7.00"), precio_primer_intento=D("3.45")).datos
    assert (d["precio_primer_intento"], d["precio_actual"], d["subida_pct"], d["supera_subida_max"]) == (
        "3.45", "7.00", "102.90", True)
    json.dumps(d)
    sin_primero = reintento_stop(o, CFG["stops"], 1010.0, cot=cot(last="7.00")).datos
    assert (sin_primero["precio_primer_intento"], sin_primero["subida_pct"],
            sin_primero["supera_subida_max"]) == ("7.00", "0.00", False)
    sin_cot = reintento_stop(o, CFG["stops"], 1010.0).datos
    assert sin_cot["subida_pct"] is None and sin_cot["supera_subida_max"] is None


def test_D2_15_umbral_de_la_config_y_ask_si_no_hay_ultimo() -> None:
    o = stop_compra(Proposito.STOP_EMERGENCIA)
    c = Cotizacion(ticker=TICKER, bid=D("5.00"), ask=D("5.20"), last=None)
    d = reintento_stop(o, {"subida_max_cierre_pct": 50}, 1.0, cot=c, precio_primer_intento=D("4.00")).datos
    assert (d["precio_actual"], d["subida_pct"], d["supera_subida_max"]) == ("5.20", "30.00", False)
    d2 = reintento_stop(o, {"subida_max_cierre_pct": 20}, 1.0, cot=c, precio_primer_intento=D("4.00")).datos
    assert d2["supera_subida_max"] is True


def test_D2_15_decidir_anota_la_subida_del_stop_tambien_al_agotar(catalogo: list[dict]) -> None:
    o = stop_compra(Proposito.STOP_EMERGENCIA, estado=EstadoOrden.REJECTED, intentos=5, notas="???")
    acciones = decidir(o, DESCONOCIDO, posicion(-100), [o], CFG, Tokens(), cot(last="8.00"), HORA, ahora=1500.0,
                       precio_primer_intento=D("4.00"))
    rechazo = anotacion(acciones, "rechazo")
    assert rechazo["decision"] == "stop_agotado"
    assert (rechazo["subida_pct"], rechazo["supera_subida_max"]) == ("100.00", False)
    json.dumps(rechazo)
    assert de_tipo(acciones, EnviarOrden) == [] and de_tipo(acciones, CancelarTicker) == [], "no cierra (EP-1)"


# ── A-06: los GET salen de protocolo.cmd_get ───────────────────────────────
def test_A_06_comandos_por_protocolo() -> None:
    from app.bot_das.protocolo import cmd_get
    assert R.COMANDO_BP == cmd_get("BP") == "GET BP"
    assert R.COMANDO_ORDENES == cmd_get("ORDERS") == "GET ORDERS"
