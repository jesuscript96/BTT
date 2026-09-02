"""Modelos avanzados (2026-08-31): las propiedades que los hacen honestos.

El riesgo de este bloque no es que se caiga: es que funcione, dé unos numeros
preciosos y sean mentira. Todo lo que se prueba aqui va contra esa posibilidad.

  1. CAUSALIDAD DEL HMM. La propiedad clave y la que se rompe sola: la
     probabilidad de estado en la vela t no puede depender de la vela t+1. Se
     comprueba de la unica forma que vale — recalculando con el dia cortado — y
     ademas se comprueba que la funcion de la LIBRERIA sí falla ese test, para
     que quede claro por que hay codigo propio.
  2. Que los niveles de precio se normalizan a distancia en %. Sin esto el
     modelo memoriza "18,40 dolares" y no generaliza a otro ticker.
  3. Que las features salen del MISMO `compute_indicator` que las condiciones.
  4. Que el veto solo QUITA entradas, nunca inventa.
"""
import numpy as np
import pandas as pd
import pytest

from app.services.advanced_model import (
    FeatureCollector, TrainedModel, build_feature_matrix, build_feature_names,
    describe_hmm_states, feature_label, fit_hmm, hmm_filtered_proba,
    hmm_observations, train_booster,
)
from app.services.indicators import compute_indicator


def _dia(n=240, semilla=0, inicio="2024-11-12 09:30") -> pd.DataFrame:
    rng = np.random.default_rng(semilla)
    close = 20.0 + np.cumsum(rng.normal(0, 0.08, n))
    return pd.DataFrame({
        "timestamp": pd.date_range(inicio, periods=n, freq="1min"),
        "ticker": "TEST",
        "open": close, "high": close + 0.06, "low": close - 0.06,
        "close": close, "volume": rng.uniform(500, 9000, n),
    })


# ── 1. La causalidad del HMM ──────────────────────────────────────────────

@pytest.fixture(scope="module")
def hmm_entrenado():
    dias = [hmm_observations(_dia(semilla=s)) for s in range(12)]
    modelo = fit_hmm(dias, n_states=3, seed=0)
    assert modelo is not None
    return modelo


def test_el_filtrado_causal_no_mira_el_futuro(hmm_entrenado):
    """LA prueba de este modulo.

    Si el valor de la vela 100 cambia cuando le doy velas posteriores, el
    indicador esta usando informacion futura y el backtest es irreproducible.
    """
    df = _dia(semilla=99)
    obs = hmm_observations(df)

    completo = hmm_filtered_proba(hmm_entrenado, obs)
    for corte in (30, 100, 180):
        parcial = hmm_filtered_proba(hmm_entrenado, obs[:corte])
        assert np.allclose(completo[:corte], parcial, atol=1e-10), (
            f"la probabilidad de las primeras {corte} velas CAMBIA al añadir "
            f"velas posteriores: hay look-ahead")


def test_la_funcion_de_la_libreria_SI_mira_el_futuro(hmm_entrenado):
    """El contraste que justifica tener codigo propio.

    `predict_proba` de hmmlearn es forward-BACKWARD (suavizado). Si algun dia
    alguien lo sustituye por comodidad, este test lo caza.
    """
    df = _dia(semilla=99)
    obs = hmm_observations(df)
    corte = 100

    completo = hmm_entrenado.predict_proba(obs)[:corte]
    parcial = hmm_entrenado.predict_proba(obs[:corte])
    assert not np.allclose(completo, parcial, atol=1e-6), (
        "predict_proba parece causal, lo que contradice la documentacion de "
        "hmmlearn — revisar antes de fiarse")


def test_las_probabilidades_suman_uno(hmm_entrenado):
    obs = hmm_observations(_dia(semilla=7))
    p = hmm_filtered_proba(hmm_entrenado, obs)
    assert p.shape == (len(obs), 3)
    assert np.allclose(p.sum(axis=1), 1.0, atol=1e-9)
    assert (p >= 0).all()


def test_los_estados_se_traducen_a_algo_legible(hmm_entrenado):
    estados = describe_hmm_states(hmm_entrenado)
    assert len(estados) == 3
    etiquetas = {e["etiqueta"] for e in estados}
    assert etiquetas == {"caída", "ruido", "subida"}, (
        "los tres estados deben quedar ordenados por retorno medio")


def test_el_hmm_no_cruza_dias():
    """Se entrena con `lengths`: el ultimo minuto de un dia y el primero del
    siguiente NO son consecutivos. Sin eso aprenderia transiciones inventadas."""
    dias = [hmm_observations(_dia(n=60, semilla=s)) for s in range(6)]
    modelo = fit_hmm(dias, n_states=2, seed=1)
    assert modelo is not None and modelo.transmat_.shape == (2, 2)


def test_hmm_sin_datos_suficientes_devuelve_none():
    assert fit_hmm([], n_states=3) is None
    assert fit_hmm([np.empty((0, 3)), np.zeros((1, 3))], n_states=3) is None


# ── 2 y 3. Las features ───────────────────────────────────────────────────

def test_los_niveles_de_precio_se_vuelven_distancia_en_pct():
    """Un VWAP crudo valdria "20,3" y el modelo memorizaria ese precio. Como
    distancia en % es comparable entre una accion de 2 $ y una de 200 $."""
    df = _dia(semilla=3)
    X = build_feature_matrix(df, None, [{"name": "VWAP"}])

    vwap = np.asarray(compute_indicator("VWAP", df), dtype=np.float64)
    close = np.asarray(df["close"], dtype=np.float64)
    esperado = (close - vwap) / vwap * 100.0

    assert np.allclose(X[:, 0], esperado, equal_nan=True)
    # Y el rango tiene que ser de "porcentaje", no de "precio".
    assert np.nanmax(np.abs(X[:, 0])) < 50.0


def test_los_porcentajes_van_crudos():
    """El RSI ya es una cifra sin unidades: tocarlo seria estropearlo."""
    df = _dia(semilla=4)
    X = build_feature_matrix(df, None, [{"name": "RSI", "period": 14}])
    esperado = np.asarray(compute_indicator("RSI", df, period=14), dtype=np.float64)
    assert np.allclose(X[:, 0], esperado, equal_nan=True)


def test_las_features_salen_del_mismo_motor_que_las_condiciones():
    """Si esto se rompe, el modelo estaria aprendiendo de unos numeros y la
    estrategia disparando con otros."""
    df = _dia(semilla=5)
    defs = [
        {"name": "RSI", "period": 14},
        {"name": "ATR", "period": 14},
        {"name": "% Fade", "fade_ref": "previous_max", "ap_session": "ap.RTH"},
        {"name": "Volume"},
    ]
    X = build_feature_matrix(df, None, defs)
    assert X.shape == (len(df), 4)
    for i, cfg in enumerate(defs):
        kw = {k: v for k, v in cfg.items() if k != "name"}
        esperado = np.asarray(compute_indicator(cfg["name"], df, **kw), dtype=np.float64)
        assert np.allclose(X[:, i], esperado, equal_nan=True), cfg["name"]


def test_las_etiquetas_distinguen_configuraciones():
    """Dos SMA de periodos distintos son dos columnas distintas y tienen que
    leerse distinto en la importancia de features."""
    a = feature_label({"name": "SMA", "period": 20})
    b = feature_label({"name": "SMA", "period": 200})
    assert a != b and "20" in a and "200" in b
    assert feature_label({"name": "Volume"}) == "Volume"


def test_nombres_incluyen_los_estados_del_hmm():
    nombres = build_feature_names([{"name": "RSI", "period": 14}], hmm_states=3)
    assert len(nombres) == 4
    assert nombres[-3:] == ["HMM p(estado 0)", "HMM p(estado 1)", "HMM p(estado 2)"]


def test_sin_features_no_revienta():
    df = _dia()
    assert build_feature_matrix(df, None, []).shape == (len(df), 0)


# ── 4. El veto ────────────────────────────────────────────────────────────

def _modelo_de_juguete(df, defs, threshold):
    X = build_feature_matrix(df, None, defs)
    X = np.nan_to_num(X, nan=0.0)
    y = (np.arange(len(df)) % 2 == 0).astype(int)      # etiqueta arbitraria
    booster = train_booster(X, y, seed=0)
    return TrainedModel(booster=booster, feature_defs=defs, threshold=threshold,
                        feature_names=build_feature_names(defs, 0))


def test_el_veto_solo_quita_entradas_nunca_las_inventa():
    """La propiedad de seguridad: pase lo que pase con el modelo, el resultado
    tiene que ser un SUBCONJUNTO de lo que decidieron las reglas."""
    df = _dia(semilla=11)
    defs = [{"name": "RSI", "period": 14}, {"name": "Volume"}]
    modelo = _modelo_de_juguete(df, defs, threshold=0.5)

    rng = np.random.default_rng(2)
    entradas = rng.random(len(df)) < 0.1
    filtradas = modelo.mask(entradas.copy(), df, None)

    assert filtradas.dtype == bool
    assert not (filtradas & ~entradas).any(), "el veto ha inventado una entrada"
    assert filtradas.sum() <= entradas.sum()


def test_umbral_uno_lo_corta_todo_y_cero_no_corta_nada():
    df = _dia(semilla=12)
    defs = [{"name": "RSI", "period": 14}]
    entradas = np.zeros(len(df), dtype=bool)
    entradas[::20] = True

    todo = _modelo_de_juguete(df, defs, threshold=0.0).mask(entradas.copy(), df, None)
    nada = _modelo_de_juguete(df, defs, threshold=1.01).mask(entradas.copy(), df, None)

    assert todo.sum() == entradas.sum(), "con umbral 0 no se filtra nada"
    assert nada.sum() == 0, "con umbral por encima de 1 no pasa ninguna"


def test_sin_entradas_el_veto_ni_calcula():
    """Optimizacion que ademas es correccion: un dia sin señales no debe pagar
    el coste de calcular features."""
    df = _dia(semilla=13)
    modelo = _modelo_de_juguete(df, [{"name": "RSI", "period": 14}], threshold=0.5)
    vacio = np.zeros(len(df), dtype=bool)
    assert not modelo.mask(vacio, df, None).any()


# ── 5. Las dos fugas de la auditoria del 31-ago (tarde) ───────────────────
#
# Jaume corrio un backtest con el modelo y los resultados eran "una locura".
# Tenia razon en desconfiar: la auditoria encontro DOS fallos, y estos tests
# los reproducen para que no vuelvan.

def _dia_con_spike(n=390, semilla=3, spike=False):
    r = np.random.default_rng(semilla)
    close = 20.0 + np.cumsum(r.normal(0, 0.08, n))
    vol = r.uniform(500, 5000, n)
    if spike:
        vol[-60:] *= 40.0            # volumen monstruo AL FINAL del dia
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-05-01 04:00", periods=n, freq="1min"),
        "ticker": "T", "open": close, "high": close + .05, "low": close - .05,
        "close": close, "volume": vol,
    })


def test_FUGA_1_las_observaciones_no_saben_el_volumen_del_futuro():
    """LA fuga que hizo mentir al backtest de Jaume.

    La primera version normalizaba el volumen por la media del DIA ENTERO:
    la vela de las 07:00 quedaba escalada por el volumen que llegaria por la
    tarde. En un universo de gaps y pumps, el volumen total del dia es ORO —
    el modelo lo explotaba y el resultado era espectacular e irreproducible.
    Dos dias identicos hasta la vela 330 deben dar observaciones IDENTICAS
    hasta ahi, tenga o no uno de ellos un spike posterior.
    """
    plano = hmm_observations(_dia_con_spike(spike=False))[:200]
    con_spike = hmm_observations(_dia_con_spike(spike=True))[:200]
    assert np.allclose(plano, con_spike), (
        "la observacion de la mañana cambia segun el volumen de la tarde: "
        "look-ahead — es la fuga que produjo el backtest 'increible'")


def test_FUGA_1b_el_prefijo_del_dia_da_lo_mismo_que_el_dia_cortado():
    """Version general: obs(dia)[:k] == obs(dia[:k]). Si esto falla, CUALQUIER
    cosa que salga del HMM lleva futuro dentro."""
    d = _dia_con_spike(spike=True)
    completo = hmm_observations(d)
    for k in (50, 200, 330):
        prefijo = hmm_observations(d.iloc[:k].reset_index(drop=True))
        assert np.allclose(completo[:k], prefijo, atol=1e-12), f"corte {k}"


def test_FUGA_1c_score_de_punta_a_punta_es_causal(hmm_entrenado):
    """El numero que decide el veto (features + HMM + XGBoost) no puede cambiar
    al añadir velas posteriores. Es la garantia completa, no la de una pieza."""
    defs = [{"name": "RSI", "period": 14}, {"name": "Volume"}]
    d = _dia_con_spike(semilla=9, spike=True)
    X = build_feature_matrix(d, None, defs)
    probas = hmm_filtered_proba(hmm_entrenado, hmm_observations(d))
    y = (np.arange(len(d)) % 3 == 0).astype(int)
    booster = train_booster(np.column_stack([np.nan_to_num(X), probas]), y, 0)
    modelo = TrainedModel(booster=booster, feature_defs=defs, threshold=0.5,
                          hmm=hmm_entrenado, hmm_states=3,
                          feature_names=build_feature_names(defs, 3))

    completo = modelo.score(d, None)
    for k in (100, 250):
        prefijo = modelo.score(d.iloc[:k].reset_index(drop=True), None)
        assert np.allclose(completo[:k], prefijo, atol=1e-9), (
            f"el score de las primeras {k} velas cambia al conocer el resto "
            f"del dia: hay look-ahead en la tuberia")


def test_FUGA_2_con_sesion_RTH_las_etiquetas_encuentran_su_trade():
    """El segundo fallo: con sesion RTH el simulador indexa sobre el frame
    RECORTADO y el recolector indexaba sobre el dia COMPLETO. La señal de la
    vela 331 (dia completo) y su trade en la vela 1 (recortado) no se
    encontraban: el modelo entrenaba con parejas rotas, sin error ni aviso."""
    d = _dia_con_spike(n=390)                      # 04:00 -> 10:29
    ts = pd.to_datetime(d["timestamp"])
    mask = ((ts.dt.hour * 60 + ts.dt.minute) >= 570).values
    assert (~mask).sum() == 330, "el dia debe tener 330 velas de premarket"

    # La señal, como la ve el motor tras el recorte: indice 0 del frame RTH.
    entries_rec = np.zeros(int(mask.sum()), dtype=bool)
    entries_rec[0] = True
    col = FeatureCollector(feature_defs=[{"name": "Volume"}])
    col.collect("T", "d", entries_rec, d, None, session_mask=mask)

    # El trade, como lo emite el simulador: entry en el indice 1 (recortado).
    X, y, descartadas = col.dataset([
        {"ticker": "T", "date": "d", "entry_idx": 1, "pnl": 25.0}])

    assert len(X) == 1 and descartadas == 0, (
        "señal y trade no se emparejan con el recorte de sesion activo")
    assert y.tolist() == [1]
    # Y la feature debe ser la de la vela 330 del dia completo (la primera RTH),
    # no la de la vela 0 del premarket.
    assert np.isclose(X[0][0], float(d["volume"].iloc[330]))


def test_FUGA_2b_el_veto_puntua_la_vela_correcta_con_recorte():
    """mask() recibe entradas en espacio recortado y el df completo: el listado
    de probabilidades tiene que recortarse igual, o vetaria por la vela
    equivocada."""
    defs = [{"name": "Volume"}]
    d = _dia_con_spike(n=390, semilla=4)
    ts = pd.to_datetime(d["timestamp"])
    mask = ((ts.dt.hour * 60 + ts.dt.minute) >= 570).values

    X = build_feature_matrix(d, None, defs)
    y = (np.arange(len(d)) % 2 == 0).astype(int)
    modelo = TrainedModel(booster=train_booster(np.nan_to_num(X), y, 0),
                          feature_defs=defs, threshold=0.0,
                          feature_names=build_feature_names(defs, 0))

    entries_rec = np.zeros(int(mask.sum()), dtype=bool)
    entries_rec[[0, 5]] = True
    out = modelo.mask(entries_rec.copy(), d, None, session_mask=mask)
    assert len(out) == len(entries_rec), "el veto debe devolver el espacio recortado"
    assert out.sum() == 2, "con umbral 0 no debe vetar nada"
