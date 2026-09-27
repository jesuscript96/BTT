"""reglas/exclusiones.py: lista negra, sin ficha (A12), SPAC siempre, IPO solo RTH con casilla, split del día, banda de OPA (R-A-03 v2, R-A-04)."""
from __future__ import annotations

import ast
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pytest

from app.bot_das.reglas import exclusiones
from app.bot_das.reglas.exclusiones import MOTIVOS, banda_opa, excluida, simbolo_das
from app.bot_das.tipos import EstrategiaConfig, Ficha

D = Decimal
HOY = date(2026, 9, 25)
RUTA_CONFIG = Path(__file__).parent / "fixtures" / "config_ejemplo.json"


@pytest.fixture(scope="module")
def cfg_ex() -> dict:
    """El bloque `exclusiones` tal cual sale del JSON de ejemplo."""
    return json.loads(RUTA_CONFIG.read_text(encoding="utf-8"))["exclusiones"]


def estrategia(es_rth: bool, excluir_ipo: bool) -> EstrategiaConfig:
    return EstrategiaConfig(
        strategy_id="s-1", name="prueba", origen="portfolio", ejecutar=True, avisar_grupo_a=False,
        riesgo_usd=D("300"), riesgos_piramide=[], riesgo_piramide_usd=None, ev_pct=D("4"), ev_rangos=[],
        excluir_ipo=excluir_ipo, al_desactivar="esperar_fin_dia", hora_fin_sesion=None, ventana_entradas=[],
        hora_salida=None, accept_reentries=True, max_reentries=-1, niveles_piramide=[], es_rth=es_rth,
        definition_hash="sha256:" + "0" * 64, definition={})


def ficha(sic: Optional[str] = "2834", dias: Optional[int] = 400, ticker: str = "XYZ") -> Ficha:
    return Ficha(ticker=ticker, list_date=None if dias is None else HOY - timedelta(days=dias), sic_code=sic,
                 tipo="CS", market_cap=D("25000000"), nombre="Prueba Inc.")


RTH_CASILLA = estrategia(es_rth=True, excluir_ipo=True)
RTH_SIN_CASILLA = estrategia(es_rth=True, excluir_ipo=False)
PM_CASILLA = estrategia(es_rth=False, excluir_ipo=True)
PM_SIN_CASILLA = estrategia(es_rth=False, excluir_ipo=False)


# ── excluida ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("ticker, e, f, splits, negra, esperado", [
    ("XYZ", RTH_CASILLA, ficha(), set(), [], None),
    ("XYZ", PM_SIN_CASILLA, ficha(), set(), ["XYZ"], "lista_negra"),
    ("xyz ", PM_SIN_CASILLA, ficha(), set(), [" Xyz"], "lista_negra"),
    ("XYZ", PM_SIN_CASILLA, None, set(), ["XYZ"], "lista_negra"),
    ("XYZ", PM_SIN_CASILLA, None, set(), [], "sin_ficha"),
    ("XYZ", PM_SIN_CASILLA, None, None, [], "sin_ficha"),
    ("XYZ", PM_SIN_CASILLA, ficha(sic="6770"), set(), [], "spac"),
    ("XYZ", PM_CASILLA, ficha(sic="6770"), set(), [], "spac"),
    ("XYZ", RTH_SIN_CASILLA, ficha(sic="6770"), set(), [], "spac"),
    ("XYZ", RTH_CASILLA, ficha(sic="6770", dias=1), {"XYZ"}, [], "spac"),
    ("XYZ", RTH_CASILLA, ficha(sic=" 6770 "), set(), [], "spac"),
    ("XYZ", RTH_CASILLA, ficha(sic=None), set(), [], None),
    ("XYZ", RTH_CASILLA, ficha(dias=29), set(), [], "ipo"),
    ("XYZ", RTH_CASILLA, ficha(dias=30), set(), [], None),
    ("XYZ", RTH_CASILLA, ficha(dias=31), set(), [], None),
    ("XYZ", RTH_CASILLA, ficha(dias=0), set(), [], "ipo"),
    ("XYZ", RTH_CASILLA, ficha(dias=None), set(), [], "ipo"),
    ("XYZ", RTH_SIN_CASILLA, ficha(dias=1), set(), [], None),
    ("XYZ", PM_CASILLA, ficha(dias=1), set(), [], None),
    ("XYZ", PM_SIN_CASILLA, ficha(dias=1), set(), [], None),
    ("XYZ", RTH_CASILLA, ficha(dias=29), {"XYZ"}, [], "ipo"),
    ("XYZ", PM_SIN_CASILLA, ficha(), {"XYZ", "ABC"}, [], "split"),
    ("XYZ", PM_SIN_CASILLA, ficha(), {"xyz"}, [], "split"),
    ("XYZ", PM_SIN_CASILLA, ficha(), {"ABC"}, [], None),
    ("XYZ", PM_SIN_CASILLA, ficha(), None, [], None),
    ("XYZ", RTH_CASILLA, ficha(), None, [], None),
    ("XYZ", PM_SIN_CASILLA, ficha(), set(), None, None),
], ids=["opera", "R-A-03-lista-negra", "lista-negra-mayusculas-espacios", "lista-negra-antes-que-sin-ficha",
        "R-A-04-A12-sin-ficha", "sin-ficha-aunque-splits-None", "R-A-03-spac-pm", "R-A-03-spac-pm-casilla",
        "R-A-03-spac-rth-sin-casilla", "spac-antes-que-ipo-y-split", "spac-con-espacios", "sin-sic-opera",
        "R-A-03-ipo-29-dias", "R-A-03-ipo-30-dias-limite", "ipo-31-dias", "ipo-hoy", "ipo-sin-list_date-no-se-sabe",
        "R-A-03-ipo-rth-sin-casilla", "R-A-03-ipo-pm-con-casilla", "R-A-03-ipo-pm", "ipo-antes-que-split",
        "R-A-03-split-del-dia", "split-mayusculas", "split-de-otro", "correccion17-splits-None-no-excluye",
        "correccion17-rth", "lista-negra-None"])
def test_excluida(ticker, e, f, splits, negra, esperado, cfg_ex):
    motivo = excluida(ticker, e, f, splits, negra, HOY, cfg_ex)
    assert motivo == esperado
    assert motivo is None or motivo in MOTIVOS


@pytest.mark.parametrize("cfg, f, splits, esperado", [
    ({"ipo_dias": 10}, ficha(dias=9), set(), "ipo"),
    ({"ipo_dias": 10}, ficha(dias=10), set(), None),
    ({"ipo_dias": 30.0}, ficha(dias=29), set(), "ipo"),
    ({"spac_sic": ["6770", "6798"]}, ficha(sic="6798"), set(), "spac"),
    ({"spac_sic": [6770]}, ficha(sic="6770"), set(), "spac"),
    ({"split_del_dia": False}, ficha(), {"XYZ"}, None),
    ({"split_del_dia": True}, ficha(), {"XYZ"}, "split"),
    ({}, ficha(dias=29), {"XYZ"}, "ipo"),
    ({}, ficha(sic="6770"), set(), "spac"),
], ids=["ipo_dias-config", "ipo_dias-config-limite", "ipo_dias-float-entero", "spac_sic-config",
        "spac_sic-numerico", "split_del_dia-false", "split_del_dia-true", "config-vacia-defectos-libro",
        "config-vacia-spac-6770"])
def test_excluida_config(cfg, f, splits, esperado):
    assert excluida("XYZ", RTH_CASILLA, f, splits, [], HOY, cfg) == esperado


@pytest.mark.parametrize("cfg", [{"ipo_dias": "30"}, {"ipo_dias": 29.5}, {"ipo_dias": True}, {"split_del_dia": "0"},
                                 {"split_del_dia": 0}],
                         ids=["ipo_dias-texto", "ipo_dias-fraccion", "ipo_dias-bool", "split-texto", "split-entero"])
def test_excluida_config_mal_formada_lanza(cfg):
    with pytest.raises(ValueError):
        excluida("XYZ", RTH_CASILLA, ficha(dias=400), {"XYZ"}, [], HOY, cfg)


def test_splits_none_nunca_excluye_a_nadie(cfg_ex):
    """Riesgo 35: con `splits_de_hoy` caído no se excluye todo; los demás motivos siguen funcionando."""
    tickers = [f"T{i}" for i in range(50)]
    motivos = [excluida(t, PM_SIN_CASILLA, ficha(ticker=t), None, [], HOY, cfg_ex) for t in tickers]
    assert motivos == [None] * 50
    assert excluida("T1", PM_SIN_CASILLA, ficha(sic="6770"), None, [], HOY, cfg_ex) == "spac"


# ── banda_opa ───────────────────────────────────────────────────────────
def velas(n: int, hi: str, lo: str, usd: str, inicio: int = 0, paso: int = 60) -> list[tuple[float, Decimal, Decimal, Decimal]]:
    return [(float(inicio + i * paso), D(hi), D(lo), D(usd)) for i in range(n)]


@pytest.mark.parametrize("muestras, max_pm, cfg_extra, esperado", [
    (velas(30, "9.99", "9.86", "5000"), D("10"), {}, True),
    (velas(30, "9.99", "9.85", "5000"), D("10"), {}, True),
    (velas(30, "9.99", "9.84", "5000"), D("10"), {}, False),
    (velas(30, "9.99", "9.90", "3333.33"), D("10"), {}, False),
    (velas(30, "9.99", "9.90", "3333.34"), D("10"), {}, True),
    (velas(29, "9.99", "9.90", "5000"), D("10"), {}, False),
    (velas(3, "9.99", "9.90", "50000", paso=870), D("10"), {}, True),
    (velas(3, "9.99", "9.90", "50000", paso=600), D("10"), {}, False),
    (velas(30, "9.50", "9.45", "5000"), D("10"), {}, False),
    (velas(30, "9.50", "9.45", "5000"), None, {}, True),
    (velas(30, "10.20", "10.10", "5000"), D("10"), {}, True),
    ([], D("10"), {}, False),
    (velas(10, "9.99", "9.90", "20000"), D("10"), {"opa_banda": {"minutos": 10, "rango_max_pct": 1.5,
                                                                 "dolares_min": 100000}}, True),
    (velas(30, "9.99", "9.70", "5000"), D("10"), {"opa_banda": {"minutos": 30, "rango_max_pct": 3.0,
                                                                "dolares_min": 100000}}, True),
    (velas(30, "9.99", "9.90", "5000"), D("10"), {"opa_banda": {"minutos": 0}}, False),
], ids=["R-A-03-banda-clavada", "rango-1.5-exacto", "rango-mayor", "dolares-bajo-100k", "dolares-justos",
        "ventana-29-min-no-cubre", "velas-dispersas-cubren", "velas-dispersas-no-cubren",
        "clavada-lejos-del-max-pm", "sin-max-pm-usa-highs", "high-sobre-max-pm-sube-el-tope", "sin-muestras",
        "minutos-config", "rango-config", "minutos-0"])
def test_banda_opa(muestras, max_pm, cfg_extra, esperado, cfg_ex):
    assert banda_opa(muestras, max_pm, dict(cfg_ex, **cfg_extra)) is esperado


def test_banda_opa_mira_solo_los_ultimos_30_min(cfg_ex):
    """Lo de antes de la ventana (el gap) no cuenta: 20 velas movidas y luego 30 clavadas → aviso."""
    antes = velas(20, "12", "8", "90000", inicio=0)
    clavadas = velas(30, "9.99", "9.90", "5000", inicio=20 * 60)
    assert banda_opa(antes + clavadas, D("12"), cfg_ex) is False          # el max_pm de 12 deja el rango lejos
    assert banda_opa(antes + clavadas, D("10"), cfg_ex) is True           # las velas movidas quedan FUERA de la ventana
    movida_dentro = clavadas[:-1] + [(float(49 * 60), D("9.99"), D("9.50"), D("5000"))]
    assert banda_opa(antes + movida_dentro, D("10"), cfg_ex) is False


def test_banda_opa_ordena_las_muestras(cfg_ex):
    muestras = velas(30, "9.99", "9.90", "5000")
    assert banda_opa(list(reversed(muestras)), D("10"), cfg_ex) is True


def test_banda_opa_acepta_floats_del_feed(cfg_ex):
    muestras = [(float(i * 60), 9.99, 9.9, 5000.0) for i in range(30)]
    assert banda_opa(muestras, 10.0, cfg_ex) is True


def test_banda_opa_config_sin_bloque_usa_defectos():
    assert banda_opa(velas(30, "9.99", "9.90", "5000"), D("10"), {}) is True


# ── E1-08: el aviso de OPA listo para el decisor ─────────────────────────
def test_E1_08_aviso_opa(cfg_ex):
    """E1-08: con la banda clavada → Avisar(2) al grupo B con clave «opa:X» (el decisor lo manda una vez por día)."""
    from app.bot_das.tipos import Avisar, Grupo, Nivel
    aviso = exclusiones.aviso_opa(" xyz ", velas(30, "9.99", "9.90", "5000"), D("10"), cfg_ex)
    assert isinstance(aviso, Avisar) and (aviso.nivel, aviso.grupo, aviso.clave) == (Nivel.AVISO, Grupo.B, "opa:XYZ")
    assert "OPA" in aviso.texto and "XYZ" in aviso.texto and "a mano" in aviso.texto
    assert exclusiones.aviso_opa("XYZ", velas(10, "9.99", "9.90", "5000"), D("10"), cfg_ex) is None   # sin cubrir
    assert exclusiones.aviso_opa("XYZ", [], None, cfg_ex) is None


def test_E1_08_aviso_opa_escapa_el_ticker(cfg_ex):
    aviso = exclusiones.aviso_opa("A<B", velas(30, "9.99", "9.90", "5000"), D("10"), cfg_ex)
    assert "A&lt;B" in aviso.texto and "A<B" not in aviso.texto


# ── simbolo_das (A7) ────────────────────────────────────────────────────
@pytest.mark.parametrize("entrada, esperado", [("XYZ", "XYZ"), (" abc ", "ABC"), ("BRK.B", "BRK.B")],
                         ids=["A7-identidad", "A7-mayusculas-espacios", "A7-sufijo-tal-cual"])
def test_simbolo_das(entrada, esperado):
    assert simbolo_das(entrada) == esperado


# ── pureza (§3) ─────────────────────────────────────────────────────────
def test_modulo_puro():
    fuente = Path(exclusiones.__file__).read_text(encoding="utf-8")
    arbol = ast.parse(fuente)
    importados = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            importados.update(a.name.split(".")[0] for a in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module:
            importados.add(nodo.module)
    assert not {m.split(".")[0] for m in importados} & {"time", "logging", "os", "socket", "urllib", "httpx", "threading"}
    assert "app.bot_das.referencia_massive" not in importados        # ajuste (a): Ficha viene de tipos
    llamadas = {n.func.id for n in ast.walk(arbol) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    atributos = {n.attr for n in ast.walk(arbol) if isinstance(n, ast.Attribute)}
    assert not llamadas & {"open", "print"}
    assert not atributos & {"now", "today", "utcnow", "environ", "getenv"}
