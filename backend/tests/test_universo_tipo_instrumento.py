"""El universo del backtest solo admite accion comun (CS) y ADR (ADRC).

EL PROBLEMA (Jaume, 2026-09-06: «esto es importante, muy importante»).
`daily_metrics` no lleva columna de tipo de instrumento, asi que el universo se
tragaba todo lo que hiciera gap. Medido sobre una corrida real de 2.688 trades:

    CS      1.748  65,0 %   +426,79 $
    WARRANT   776  28,9 %    -62,14 $   <-- casi un tercio, y perdiendo
    ADRC      119   4,4 %      +6,04 $
    resto      45   1,7 %    -16,23 $

El screener en vivo y `bot_alerts_radar` ya filtraban con estos dos tipos; el
backtest no, asi que backtest y bot operaban universos distintos.

Dos decisiones de Jaume que estos tests fijan:
  - por defecto para todas las estrategias (con escotilla de env),
  - los tickers SIN fila en la referencia se QUEDAN (deslistados).
"""
import pandas as pd
import pytest

from app.services import data_service as ds


@pytest.fixture(autouse=True)
def _referencia_de_juguete(monkeypatch):
    """Sin tocar el lago: se inyecta el mapa de tipos ya resuelto."""
    monkeypatch.setattr(ds, "_tipos_instrumento_cache", {
        "AAPL": "CS", "SAN": "ADRC",
        "ONMDW": "WARRANT", "FOOR": "RIGHT", "SPY": "ETF",
        "BARU": "UNIT", "BANKP": "PFD",
    })
    monkeypatch.delenv("BACKTEST_ALLOW_ALL_INSTRUMENT_TYPES", raising=False)


def _df(*tickers):
    return pd.DataFrame({"ticker": list(tickers), "gap_pct": range(len(tickers))})


def test_fuera_warrants_rights_etfs_units_y_preferentes():
    out = ds._filtrar_tipo_instrumento(_df("AAPL", "ONMDW", "FOOR", "SPY", "BARU", "BANKP"))
    assert list(out["ticker"]) == ["AAPL"]


def test_los_adr_se_quedan():
    """ADRC entra: es la misma regla que el radar del bot (`TIPOS`)."""
    out = ds._filtrar_tipo_instrumento(_df("AAPL", "SAN", "ONMDW"))
    assert list(out["ticker"]) == ["AAPL", "SAN"]


def test_un_ticker_sin_referencia_se_queda():
    """Deslistados: la referencia es de HOY. Excluirlos seria sesgo de
    supervivencia al reves — se perderian acciones comunes que dejaron de
    cotizar. Decision de Jaume, 2026-09-06."""
    out = ds._filtrar_tipo_instrumento(_df("AAPL", "DESAPARECIDO2019", "ONMDW"))
    assert list(out["ticker"]) == ["AAPL", "DESAPARECIDO2019"]


def test_la_escotilla_de_env_devuelve_el_universo_de_antes():
    """Para reproducir una corrida anterior al 2026-09-06 tal cual era."""
    import os
    os.environ["BACKTEST_ALLOW_ALL_INSTRUMENT_TYPES"] = "1"
    try:
        out = ds._filtrar_tipo_instrumento(_df("AAPL", "ONMDW", "SPY"))
        assert list(out["ticker"]) == ["AAPL", "ONMDW", "SPY"]
    finally:
        del os.environ["BACKTEST_ALLOW_ALL_INSTRUMENT_TYPES"]


def test_sin_referencia_NO_se_vacia_el_universo(monkeypatch):
    """EL MODO DE FALLO QUE HAY QUE EVITAR.

    Si la referencia no se puede leer (el lago cerrado, la vista sin registrar),
    lo que NO puede pasar es que el backtest se quede sin universo en silencio.
    Se avisa fuerte y se deja pasar todo, como antes.
    """
    monkeypatch.setattr(ds, "_tipos_instrumento_cache", {})
    out = ds._filtrar_tipo_instrumento(_df("AAPL", "ONMDW"))
    assert list(out["ticker"]) == ["AAPL", "ONMDW"]


def test_un_frame_vacio_o_sin_columna_ticker_pasa_de_largo():
    vacio = pd.DataFrame()
    assert ds._filtrar_tipo_instrumento(vacio) is vacio
    sin_ticker = pd.DataFrame({"gap_pct": [1, 2]})
    assert len(ds._filtrar_tipo_instrumento(sin_ticker)) == 2


def test_el_indice_queda_limpio():
    """Aguas abajo se hacen `groupby` y `zip` por posicion: un indice con
    huecos ha mordido antes en este repo."""
    out = ds._filtrar_tipo_instrumento(_df("ONMDW", "AAPL", "SPY", "SAN"))
    assert list(out.index) == [0, 1]


# ---------------------------------------------------------------------------
# Las tres pantallas comparten UNA sola regla
# ---------------------------------------------------------------------------

def test_el_buscador_usa_la_misma_funcion_que_el_universo():
    """`/api/data/filter` filtra ANTES de calcular stats y serie agregada.

    Si se filtrara despues, la tabla ensenaria 1.000 filas y las metricas de
    arriba estarian calculadas sobre 1.400 — el tipo de desajuste que nadie
    mira dos veces.
    """
    import re
    src = open("app/routers/data.py", encoding="utf-8").read()
    cuerpo = src[src.index("def filter_daily_metrics"):src.index("@router.get(\"/tickers\")")]
    i_filtro = cuerpo.index("_filtrar_universo(df)")
    i_stats = cuerpo.index("get_dashboard_stats(df)")
    i_serie = cuerpo.index("get_aggregate_time_series(ticker_date_pairs)")
    assert i_filtro < i_stats < i_serie
    assert re.search(r"df = con\.execute\(query, params\)", cuerpo)


def test_los_pares_del_dataset_tambien_se_filtran():
    """La vista previa tiene que contar los dias que el backtest recorre."""
    src = open("app/routers/query.py", encoding="utf-8").read()
    cuerpo = src[src.index("def _compute_dataset_pairs"):src.index("def _insert_dataset_pairs")]
    assert "_filtrar_universo(pairs_df)" in cuerpo
    # Y despues del drop_duplicates, no antes: filtrar primero solo haria mas
    # trabajo sobre filas repetidas.
    assert cuerpo.index("drop_duplicates") < cuerpo.index("_filtrar_universo(pairs_df)")


# ---------------------------------------------------------------------------
# Suelo de precio: fuera lo que no vale practicamente nada
# ---------------------------------------------------------------------------
#
# El 2026-09-06 una operacion en OPPr a $0,0005 se convirtio en 636.873 acciones
# y 6.369 $ de locates sobre una posicion de 300 $: se llevo 7.000 $ de una
# cuenta de 10.000. Jaume pidio un suelo de 0,10 $.
#
# `universe_filters.min_price` existia en el esquema desde siempre pero
# `_build_where_clause` no lo leia: nunca filtro nada. Por eso el suelo va
# aparte y siempre activo, no como un campo que hay que acordarse de rellenar.


def _dfp(*pares):
    """(ticker, open) -> DataFrame del universo."""
    return pd.DataFrame({"ticker": [t for t, _ in pares],
                         "open": [o for _, o in pares]})


def test_fuera_lo_que_cotiza_por_debajo_del_suelo():
    out = ds._filtrar_precio_minimo(_dfp(("AAPL", 190.0), ("OPPr", 0.0005),
                                        ("PENNY", 0.09), ("JUSTO", 0.10)))
    assert list(out["ticker"]) == ["AAPL", "JUSTO"]  # 0,10 entra: es >=


def test_un_dia_sin_precio_se_queda():
    """Mismo criterio que los tickers sin ficha: ante la duda no se descarta."""
    out = ds._filtrar_precio_minimo(_dfp(("AAPL", 190.0), ("RARO", float("nan"))))
    assert list(out["ticker"]) == ["AAPL", "RARO"]


def test_el_suelo_se_puede_apagar_con_env():
    import os
    os.environ["BACKTEST_MIN_PRICE"] = "0"
    try:
        out = ds._filtrar_precio_minimo(_dfp(("OPPr", 0.0005)))
        assert list(out["ticker"]) == ["OPPr"]
    finally:
        del os.environ["BACKTEST_MIN_PRICE"]


def test_sin_columna_de_precio_no_se_filtra():
    """Un frame que no trae `open` (p. ej. pares ya recortados) pasa de largo."""
    sin_open = pd.DataFrame({"ticker": ["AAPL", "OPPr"]})
    assert len(ds._filtrar_precio_minimo(sin_open)) == 2


def test_el_universo_aplica_LAS_DOS_reglas():
    """`_filtrar_universo` es el unico sitio que deben llamar las pantallas."""
    df = pd.DataFrame({"ticker": ["AAPL", "ONMDW", "BARATA", "SAN"],
                       "open": [190.0, 5.0, 0.02, 12.0]})
    out = ds._filtrar_universo(df)
    # AAPL y SAN sobreviven; ONMDW cae por warrant, BARATA por precio.
    assert list(out["ticker"]) == ["AAPL", "SAN"]
    assert list(out.index) == [0, 1]


def test_el_suelo_por_defecto_es_diez_centimos():
    assert ds._precio_minimo() == 0.10
