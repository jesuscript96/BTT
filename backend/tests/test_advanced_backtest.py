"""El orquestador de dos pasadas (2026-08-31).

Lo que se protege aqui es la honestidad del resultado, no que "funcione":

  1. Que el ENTRENAMIENTO y la PRUEBA no comparten ni un dia. Si se solapan, el
     numero del OOS esta inflado y no se nota mirandolo.
  2. Que lo que se devuelve es el periodo de PRUEBA. Es lo que pidio Jaume:
     ver equity y metricas del OOS como si fuera una estrategia normal.
  3. Que las señales que NO llegaron a operarse se DESCARTAN en vez de
     etiquetarse como perdedoras. "No se ejecuto" no es "salio mal".
  4. Que una configuracion imposible falla con un mensaje que se entiende, en
     vez de devolver un backtest silenciosamente vacio.

Se usa un `run_fn` de mentira que respeta el contrato de `run_backtest`: asi se
prueba la orquestacion sin depender del lago.
"""
import numpy as np
import pandas as pd
import pytest

from app.services.advanced_backtest import (
    AdvancedModelError, parse_config, run_with_model,
)
from app.services.advanced_model import FeatureCollector


def _universo(desde="2024-01-01", dias=400) -> pd.DataFrame:
    fechas = pd.date_range(desde, periods=dias, freq="D").strftime("%Y-%m-%d")
    return pd.DataFrame({"ticker": ["AAA"] * dias, "date": list(fechas)})


def _dia_df(n=120, semilla=0) -> pd.DataFrame:
    rng = np.random.default_rng(semilla)
    close = 15.0 + np.cumsum(rng.normal(0, 0.1, n))
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-05-01 09:30", periods=n, freq="1min"),
        "ticker": "AAA",
        "open": close, "high": close + 0.05, "low": close - 0.05,
        "close": close, "volume": rng.uniform(1000, 8000, n),
    })


class _Motor:
    """Imita `run_backtest`: recorre los dias del universo que se le pasan,
    genera dos señales por dia y llama a los hooks igual que el motor real."""

    def __init__(self):
        self.llamadas: list[dict] = []

    def __call__(self, qualifying_df=None, entry_model=None,
                 feature_collector=None, **kw):
        dias = list(qualifying_df["date"]) if qualifying_df is not None else []
        self.llamadas.append({"dias": dias, "con_modelo": entry_model is not None,
                              "recolectando": feature_collector is not None})
        trades = []
        for i, fecha in enumerate(dias):
            df = _dia_df(semilla=i)
            entradas = np.zeros(len(df), dtype=bool)
            entradas[[30, 70]] = True

            if feature_collector is not None:
                feature_collector.collect("AAA", fecha, entradas, df, None)
            if entry_model is not None:
                entradas = entry_model.mask(entradas, df, None)

            # El relleno va en la vela SIGUIENTE a la señal, como el motor real.
            for idx in np.flatnonzero(entradas):
                trades.append({
                    "ticker": "AAA", "date": fecha, "entry_idx": int(idx) + 1,
                    "pnl": 10.0 if (i + idx) % 3 else -8.0,
                })
        return {"trades": trades,
                "aggregate_metrics": {"total_trades": len(trades)},
                "equity_curves": [], "day_results": []}


_CFG = {
    "enabled": True, "mode": "filter",
    "train_from": "2024-01-01", "train_to": "2024-06-30",
    "test_from": "2024-07-01", "test_to": "2024-12-31",
    "threshold": 0.5,
    "features": [{"name": "RSI", "period": 14}, {"name": "Volume"}],
}


# ── 1. Las ventanas ───────────────────────────────────────────────────────

def test_entrenamiento_y_prueba_no_comparten_ni_un_dia():
    """La propiedad que hace honesto al numero del OOS."""
    motor = _Motor()
    run_with_model(parse_config(_CFG), _universo(), motor, {})

    entren = set(motor.llamadas[0]["dias"])
    prueba = set(motor.llamadas[1]["dias"])
    assert entren and prueba
    assert not (entren & prueba), "el modelo se esta midiendo con dias que ya vio"
    assert max(entren) <= "2024-06-30" and min(prueba) >= "2024-07-01"


def test_se_rechaza_el_solape_antes_de_calcular_nada():
    malo = {**_CFG, "train_to": "2024-08-01"}      # invade la prueba
    with pytest.raises(AdvancedModelError, match="solapa"):
        parse_config(malo)


def test_el_resultado_es_el_periodo_de_prueba():
    """Jaume quiere ver el OOS «como si fuera una estrategia mas»."""
    motor = _Motor()
    res = run_with_model(parse_config(_CFG), _universo(), motor, {})
    fechas = {t["date"] for t in res["trades"]}
    assert fechas, "no hay operaciones que enseñar"
    assert all(f >= "2024-07-01" for f in fechas), \
        "se han colado operaciones del periodo de entrenamiento"


def test_la_primera_pasada_recolecta_y_la_segunda_veta():
    motor = _Motor()
    run_with_model(parse_config(_CFG), _universo(), motor, {})
    assert motor.llamadas[0] == {**motor.llamadas[0], "recolectando": True, "con_modelo": False}
    assert motor.llamadas[1]["con_modelo"] and not motor.llamadas[1]["recolectando"]


def test_por_defecto_son_DOS_pasadas_y_el_recuento_sale_gratis():
    """Saber cuantas señales veto el modelo NO puede costar otro backtest: el
    contador lo lleva el propio modelo mientras filtra."""
    motor = _Motor()
    res = run_with_model(parse_config(_CFG), _universo(), motor, {})

    assert len(motor.llamadas) == 2, "por defecto no debe correr la comparacion"
    inf = res["advanced_model"]["test"]
    assert inf["señales_vistas"] > 0
    assert inf["señales_aceptadas"] <= inf["señales_vistas"]
    assert inf["señales_vetadas"] == inf["señales_vistas"] - inf["señales_aceptadas"]
    assert res["advanced_model"]["metricas_sin_modelo"] is None


def test_la_comparacion_sin_modelo_se_pide_y_cuesta_una_pasada_mas():
    motor = _Motor()
    cfg = parse_config({**_CFG, "compare_without_model": True})
    res = run_with_model(cfg, _universo(), motor, {})

    assert len(motor.llamadas) == 3
    assert not motor.llamadas[2]["con_modelo"], "la tercera va SIN modelo"
    assert res["advanced_model"]["metricas_sin_modelo"] is not None
    assert res["advanced_model"]["tiempos_s"]["backtest_comparacion_sin_modelo"] >= 0


# ── 3. El etiquetado ──────────────────────────────────────────────────────

def test_las_señales_no_operadas_se_descartan_no_se_marcan_perdedoras():
    """Una señal que no llego a operarse (ya habia posicion) no es una
    señal mala. Meterla como perdedora envenenaria el aprendizaje."""
    df = _dia_df(semilla=1)
    entradas = np.zeros(len(df), dtype=bool)
    entradas[[10, 40, 80]] = True

    col = FeatureCollector(feature_defs=[{"name": "RSI", "period": 14}])
    col.collect("AAA", "2024-05-01", entradas, df, None)

    # Solo DOS de las tres señales acabaron en operacion.
    trades = [
        {"ticker": "AAA", "date": "2024-05-01", "entry_idx": 11, "pnl": 5.0},
        {"ticker": "AAA", "date": "2024-05-01", "entry_idx": 81, "pnl": -3.0},
    ]
    X, y, descartadas = col.dataset(trades)

    assert len(X) == 2 and len(y) == 2, "solo deben entrenar las señales operadas"
    assert descartadas == 1
    assert sorted(y.tolist()) == [0, 1]


def test_la_etiqueta_es_el_signo_del_pnl():
    df = _dia_df(semilla=2)
    entradas = np.zeros(len(df), dtype=bool)
    entradas[[20, 50]] = True
    col = FeatureCollector(feature_defs=[{"name": "Volume"}])
    col.collect("AAA", "d", entradas, df, None)

    X, y, _ = col.dataset([
        {"ticker": "AAA", "date": "d", "entry_idx": 21, "pnl": 0.01},
        {"ticker": "AAA", "date": "d", "entry_idx": 51, "pnl": -0.01},
    ])
    assert y.tolist() == [1, 0]


# ── 4. Los errores se explican ────────────────────────────────────────────

def test_apagado_o_ausente_devuelve_none():
    """El camino de siempre: sin bloque, `parse_config` no hace nada."""
    assert parse_config(None) is None
    assert parse_config({}) is None
    assert parse_config({"enabled": False, "mode": "filter"}) is None


def test_sin_features_ni_hmm_se_queja():
    with pytest.raises(AdvancedModelError, match="al menos un indicador"):
        parse_config({**_CFG, "features": []})


def test_faltan_fechas_se_queja():
    with pytest.raises(AdvancedModelError, match="Faltan fechas"):
        parse_config({**_CFG, "test_to": ""})


def test_umbral_fuera_de_rango_se_queja():
    with pytest.raises(AdvancedModelError, match="entre 0 y 1"):
        parse_config({**_CFG, "threshold": 1.5})


def test_periodo_de_entrenamiento_vacio_se_explica():
    motor = _Motor()
    cfg = parse_config({**_CFG, "train_from": "2019-01-01", "train_to": "2019-06-30"})
    with pytest.raises(AdvancedModelError, match="ni un día en el periodo de entrenamiento"):
        run_with_model(cfg, _universo(), motor, {})


class _MotorSinReglas:
    """Motor de mentira para el modo «estrategia»: no hay señales propias, asi
    que recolecta muestreando el dia y luego deja que el modelo las genere."""

    def __init__(self):
        self.llamadas: list[dict] = []

    def __call__(self, qualifying_df=None, entry_model=None,
                 feature_collector=None, **kw):
        dias = list(qualifying_df["date"]) if qualifying_df is not None else []
        self.llamadas.append({"genera": bool(entry_model and entry_model.generates),
                              "recolecta_standalone": bool(
                                  feature_collector and feature_collector.standalone)})
        trades = []
        for i, fecha in enumerate(dias):
            df = _dia_df(semilla=i)
            if feature_collector is not None:
                feature_collector.collect_standalone(
                    "AAA", fecha, df, None, "long",
                    sl_stop=0.02, tp_stop=0.02, horizonte=0)
            if entry_model is not None:
                for idx in np.flatnonzero(entry_model.generate(df, None)):
                    trades.append({"ticker": "AAA", "date": fecha,
                                   "entry_idx": int(idx) + 1, "pnl": 1.0})
        return {"trades": trades, "aggregate_metrics": {"total_trades": len(trades)},
                "equity_curves": [], "day_results": []}


def test_el_modo_estrategia_entrena_y_genera_entradas():
    """De punta a punta: sin reglas de entrada, el modelo etiqueta con la triple
    barrera, entrena, y en la prueba PONE las entradas el."""
    motor = _MotorSinReglas()
    cfg = parse_config({**_CFG, "mode": "standalone", "threshold": 0.3})
    res = run_with_model(cfg, _universo(), motor, {})

    assert motor.llamadas[0]["recolecta_standalone"], "la 1a pasada debe muestrear"
    assert motor.llamadas[1]["genera"], "la 2a pasada la decide el modelo"
    assert res["advanced_model"]["test"]["señales_vistas"] > 0
    assert res["trades"], "el modelo no ha generado ni una entrada"
    assert all(t["date"] >= "2024-07-01" for t in res["trades"])


def test_informe_trae_lo_necesario_para_juzgar_el_modelo():
    """Sin importancias y sin la comparacion contra «sin modelo», un resultado
    bueno no se puede distinguir de una casualidad."""
    res = run_with_model(parse_config(_CFG), _universo(), _Motor(), {})
    inf = res["advanced_model"]
    assert inf["features"] == ["RSI(period=14)", "Volume"]
    assert inf["importancias"] and "peso_pct" in inf["importancias"][0]
    assert "metricas_sin_modelo" in inf
    assert inf["tiempos_s"]["entrenar_xgboost"] >= 0


# ── 5. Modo «estrategia»: que no se pise con lo que ya hay ────────────────
#
# Lo pidio Jaume el 31-ago: si el modelo pone las entradas, cualquier otro
# bloque que TAMBIEN las ponga es un choque, y hay que pararlo ANTES de correr
# el backtest. Lo que si se respeta es la gestion de riesgo entera.

from app.services.advanced_backtest import validate_strategy
from app.services.advanced_model import label_triple_barrier

_STANDALONE = {**_CFG, "mode": "standalone"}
_RM_CON_STOP = {"use_hard_stop": True, "hard_stop": {"type": "Percentage", "value": 20}}


def _estrategia(**extra):
    base = {"entry_logic": {"root_condition": {"conditions": []}},
            "exit_logic": {"root_condition": {"conditions": []}},
            "risk_management": dict(_RM_CON_STOP)}
    base.update(extra)
    return base


def test_el_modo_filtro_no_exige_nada():
    """El filtro trabaja SOBRE las reglas, asi que no choca con ellas."""
    validate_strategy(parse_config(_CFG), _estrategia(
        entry_logic={"root_condition": {"conditions": [{"type": "x"}]}}))


def test_estrategia_choca_con_la_logica_de_entrada():
    cfg = parse_config(_STANDALONE)
    with pytest.raises(AdvancedModelError, match="lógica de ENTRADA"):
        validate_strategy(cfg, _estrategia(
            entry_logic={"root_condition": {"conditions": [{"type": "x"}]}}))


def test_estrategia_choca_con_la_logica_de_salida():
    cfg = parse_config(_STANDALONE)
    with pytest.raises(AdvancedModelError, match="lógica de SALIDA"):
        validate_strategy(cfg, _estrategia(
            exit_logic={"root_condition": {"conditions": [{"type": "x"}]}}))


def test_estrategia_choca_con_la_piramidacion():
    cfg = parse_config(_STANDALONE)
    with pytest.raises(AdvancedModelError, match="PIRAMIDACIÓN"):
        validate_strategy(cfg, _estrategia(pyramiding={"levels": [{"capital_pct": 50}]}))


def test_estrategia_choca_con_el_swing():
    cfg = parse_config(_STANDALONE)
    rm = {**_RM_CON_STOP, "swing_option": {"active": True, "target_day": "gap_1_day"}}
    with pytest.raises(AdvancedModelError, match="SWING"):
        validate_strategy(cfg, _estrategia(risk_management=rm))


def test_estrategia_exige_stop():
    """Sin stop la etiqueta seria deshonesta: una vela desde la que el precio
    se desploma y luego rebota contaria como acierto."""
    cfg = parse_config(_STANDALONE)
    with pytest.raises(AdvancedModelError, match="necesita un STOP"):
        validate_strategy(cfg, _estrategia(risk_management={}))
    # Con trailing tambien vale.
    validate_strategy(cfg, _estrategia(
        risk_management={"trailing_stop": {"active": True, "buffer_pct": 5}}))


def test_el_mensaje_de_choque_dice_QUE_apagar_y_la_alternativa():
    cfg = parse_config(_STANDALONE)
    with pytest.raises(AdvancedModelError) as e:
        validate_strategy(cfg, _estrategia(
            entry_logic={"root_condition": {"conditions": [{"type": "x"}]}},
            pyramiding={"levels": [{"capital_pct": 50}]}))
    msg = str(e.value)
    assert "ENTRADA" in msg and "PIRAMIDACIÓN" in msg
    assert "filtro" in msg, "hay que ofrecerle la salida, no solo decirle que no"


def test_la_gestion_de_riesgo_normal_NO_choca():
    """Take profit, parciales, limite diario y reentradas se respetan tal cual:
    los aplica el simulador de siempre."""
    rm = {**_RM_CON_STOP,
          "use_take_profit": True, "take_profit": {"type": "Percentage", "value": 30},
          "partial_take_profits": [{"pct": 50, "at": 10}],
          "daily_loss_limit": {"enabled": True, "value": 500},
          "accept_reentries": True, "max_reentries": 2}
    validate_strategy(parse_config(_STANDALONE), _estrategia(risk_management=rm))


# ── 6. La triple barrera: la etiqueta usa TU stop y TU take profit ────────

def _barras(precios):
    import numpy as _np
    c = _np.asarray(precios, dtype=float)
    return pd.DataFrame({"timestamp": pd.date_range("2024-05-01 09:30", periods=len(c), freq="1min"),
                         "open": c, "high": c, "low": c, "close": c,
                         "volume": _np.full(len(c), 1000.0)})


def test_gana_si_toca_el_objetivo_antes():
    # Entra en 100 (apertura de la vela 1) y sube a 130: objetivo del 20% tocado.
    df = _barras([100, 100, 110, 125, 130])
    y = label_triple_barrier(df, np.array([0]), "long", sl_stop=0.20, tp_stop=0.20, horizonte=0)
    assert y.tolist() == [1]


def test_pierde_si_toca_el_stop_antes():
    df = _barras([100, 100, 92, 78, 130])       # -22% antes de subir
    y = label_triple_barrier(df, np.array([0]), "long", sl_stop=0.20, tp_stop=0.20, horizonte=0)
    assert y.tolist() == [0]


def test_la_trampa_del_horizonte_fijo_queda_cazada():
    """EL caso que justifica la triple barrera: el precio primero se desploma
    (stop saltado, estas fuera) y LUEGO sube. Un «¿subio en N minutos?» diria
    que fue buena entrada; aqui sale perdedora, que es lo que pasa de verdad."""
    df = _barras([100, 100, 70, 75, 108])
    y = label_triple_barrier(df, np.array([0]), "long", sl_stop=0.20, tp_stop=0.05, horizonte=0)
    assert y.tolist() == [0], "el camino importa: el stop salto antes del rebote"


def test_empate_en_la_misma_vela_gana_el_stop():
    """Con velas de un minuto no se sabe cual llego antes: lo pesimista."""
    df = pd.DataFrame({"timestamp": pd.date_range("2024-05-01 09:30", periods=3, freq="1min"),
                       "open": [100, 100, 100], "high": [100, 100, 130],
                       "low": [100, 100, 70], "close": [100, 100, 100],
                       "volume": [1000.0] * 3})
    y = label_triple_barrier(df, np.array([0]), "long", sl_stop=0.20, tp_stop=0.20, horizonte=0)
    assert y.tolist() == [0]


def test_en_corto_las_barreras_se_dan_la_vuelta():
    df = _barras([100, 100, 90, 78])            # baja: en corto es ganar
    largo = label_triple_barrier(df, np.array([0]), "long", 0.20, 0.20, 0)
    corto = label_triple_barrier(df, np.array([0]), "short", 0.20, 0.20, 0)
    assert largo.tolist() == [0] and corto.tolist() == [1]


def test_sin_barrera_tocada_manda_el_signo_al_final():
    df = _barras([100, 100, 101, 102, 103])     # ni stop ni objetivo
    y = label_triple_barrier(df, np.array([0]), "long", 0.20, 0.20, 0)
    assert y.tolist() == [1]
    df2 = _barras([100, 100, 99, 98, 97])
    assert label_triple_barrier(df2, np.array([0]), "long", 0.20, 0.20, 0).tolist() == [0]


def test_una_vela_sin_futuro_no_se_etiqueta():
    """La ultima vela no puede abrir posicion: el relleno seria la siguiente."""
    df = _barras([100, 100, 100])
    y = label_triple_barrier(df, np.array([2]), "long", 0.20, 0.20, 0)
    assert y.tolist() == [-1], "-1 = no se sabe, y se descarta al entrenar"


# ── 7. Mensajes que se explican solos ─────────────────────────────────────

def test_un_rango_al_reves_se_caza_por_su_nombre():
    """Un «hasta» anterior al «desde» da cero dias SIEMPRE, y el mensaje de «no
    hay ni un dia» hacia pensar en el dataset en vez de en las fechas."""
    with pytest.raises(AdvancedModelError, match="al revés.*prueba|prueba.*al revés"):
        parse_config({**_CFG, "test_from": "2025-08-26", "test_to": "2025-08-25"})
    with pytest.raises(AdvancedModelError, match="al revés"):
        parse_config({**_CFG, "train_from": "2024-06-30", "train_to": "2024-01-01"})


def test_si_la_ventana_queda_fuera_el_mensaje_dice_QUE_hay_disponible():
    """La causa nº1 de una ventana vacia es que el «Rango de fechas global» de
    la estrategia recorta el universo antes de llegar aqui. Sin decirlo, no hay
    forma de adivinarlo desde el mensaje."""
    universo_corto = _universo(desde="2024-01-01", dias=100)   # hasta 2024-04-09
    cfg = parse_config(_CFG)                                    # prueba en julio+
    with pytest.raises(AdvancedModelError) as e:
        run_with_model(cfg, universo_corto, _Motor(), {})
    msg = str(e.value)
    assert "2024-01-01" in msg and "2024-04-09" in msg, "falta el rango disponible"
    assert "Rango de fechas global" in msg, "falta la causa mas probable"
