"""Las tres capas del buscador de tickers tienen que decir lo mismo.

QUE PASO. El 5-sep-2026 se midio contra el backend en marcha: de las 67 metricas
que ofrecia el desplegable, **22 funcionaban**. Las otras 45 no tenian columna
detras, y lo grave no era que fallaran — es que NO fallaban:

    col = METRIC_MAP.get(rule.metric)
    if not col:
        continue            # la regla se descarta y la busqueda sigue

Una etiqueta que no casaba se tiraba en silencio y la consulta salia SIN ESE
FILTRO. Comprobado con datos reales: «Pre-Market High Price > 999.999 $»
devolvia las mismas 5 filas que no filtrar nada. Un caso se caia por UNA LETRA
— la pagina decia «RTH Fade to Close %» y el backend «RTH Fade To Close %».

LAS TRES CAPAS, y las tres tienen que casar:

    1. FilterBuilder.tsx  METRICS            lo que el usuario ve y puede elegir
    2. page.tsx           metricToParamMap   lo que la pagina traduce
    3. data.py            METRIC_MAP         lo que el backend sabe consultar
    (+ la columna tiene que existir de verdad en `daily_metrics`)

Este fichero es el unico sitio donde eso se comprueba solo. Es el mismo patron
que las listas blancas de la definicion de estrategia: [[btt-listas-blancas-tres-capas]].
"""
import os
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
FILTER_BUILDER = RAIZ / "frontend" / "src" / "components" / "FilterBuilder.tsx"
PAGE = RAIZ / "frontend" / "src" / "app" / "page.tsx"


def _metric_map() -> dict:
    from app.routers.data import METRIC_MAP
    return METRIC_MAP


def _desplegable() -> dict:
    """{etiqueta: categoria} de lo que el usuario puede elegir."""
    txt = FILTER_BUILDER.read_text(encoding="utf-8")
    bloque = re.search(r"const METRICS[^=]*=\s*\{(.*?)\n\};", txt, re.S).group(1)
    fuera = {}
    for cat, cuerpo in re.findall(r"(\w+):\s*\[(.*?)\]", bloque, re.S):
        for etiqueta in re.findall(r'"([^"]+)"', cuerpo):
            fuera[etiqueta] = cat
    return fuera


def _pagina() -> dict:
    """{etiqueta: columna} de lo que la pagina traduce."""
    txt = PAGE.read_text(encoding="utf-8")
    bloque = re.search(r"const metricToParamMap[^=]*=\s*\{(.*?)\n\s*\};", txt, re.S).group(1)
    return dict(re.findall(r'"([^"]+)":\s*\{\s*column:\s*"([^"]+)"', bloque))


# ── Coherencia entre capas: corre siempre, no necesita datos ────────────────

@pytest.mark.skipif(not FILTER_BUILDER.exists(), reason="sin frontend en este arbol")
def test_todo_lo_que_se_ofrece_lo_entiende_el_backend():
    """Lo mas caro de todo: una etiqueta del desplegable que el backend no sabe
    traducir. Hoy da 400; antes devolvia resultados sin filtrar."""
    huerfanas = sorted(set(_desplegable()) - set(_metric_map()))
    assert not huerfanas, (
        "Estas metricas se ofrecen en el desplegable y METRIC_MAP no las conoce, "
        "asi que no se pueden aplicar: " + ", ".join(huerfanas))


@pytest.mark.skipif(not PAGE.exists(), reason="sin frontend en este arbol")
def test_las_etiquetas_de_la_pagina_casan_con_el_backend():
    """Aqui es donde mordio la «T» de «RTH Fade To Close %»."""
    descolgadas = sorted(set(_pagina()) - set(_metric_map()))
    assert not descolgadas, (
        "La pagina manda estas etiquetas y el backend no las reconoce (¿una "
        "mayuscula de diferencia?): " + ", ".join(descolgadas))


@pytest.mark.skipif(not FILTER_BUILDER.exists() or not PAGE.exists(),
                    reason="sin frontend en este arbol")
def test_lo_que_se_ofrece_lo_traduce_la_pagina():
    faltan = sorted(set(_desplegable()) - set(_pagina()))
    assert not faltan, (
        "Se ofrecen en el desplegable pero metricToParamMap no las traduce: "
        + ", ".join(faltan))


# ── Que las columnas existan de verdad: necesita el lago ────────────────────

def test_todas_las_columnas_del_mapa_existen(real_db):
    """`real_db` se salta solo si el backend tiene la base abierta (ver conftest)."""
    reales = {r[0] for r in real_db.execute("DESCRIBE SELECT * FROM daily_metrics").fetchall()}
    fantasmas = sorted({c for c in _metric_map().values() if c not in reales})
    assert not fantasmas, (
        "METRIC_MAP apunta a columnas que no existen en daily_metrics; cualquier "
        "filtro que las use revienta la consulta: " + ", ".join(fantasmas))
