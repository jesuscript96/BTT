"""Orquesta un backtest con modelo avanzado: entrenar en una ventana, probar
en otra, y devolver SOLO la ventana de prueba.

La idea de fondo, y es lo que hace que esto sea barato de mantener:

    entrenar y probar son LA MISMA función de siempre (`run_backtest`), llamada
    dos veces con universos distintos.

De ahí salen tres propiedades gratis:

  · Lo que se devuelve —equity, trades, métricas, gráfico— es el periodo de
    PRUEBA y nada más. No hay que filtrar métricas a posteriori ni tocar cómo
    se calculan: al motor simplemente no se le dan los días de entrenamiento.
  · El entrenamiento no puede "contaminarse" del periodo de prueba, porque
    literalmente no ha visto esos días.
  · Si alguien cambia el motor, las dos pasadas cambian igual. No hay una
    segunda implementación que pueda divergir.

Por eso este bloque tiene sus propias fechas y NO usa el deslizador IS/OOS del
panel: ese reparte UN backtest en dos trozos y las métricas que enseña son las
del tramo IS. Aquí hacen falta dos backtests distintos y enseñar el segundo.
"""
from __future__ import annotations

import logging
import time

import numpy as np
import pandas as pd

from app.services.advanced_model import (
    FeatureCollector, TrainedModel, build_feature_names, describe_hmm_states,
    fit_hmm, importances_of, train_booster,
)

logger = logging.getLogger("backtester.advanced_model")

# Por debajo de esto, cualquier modelo memoriza el periodo de entrenamiento y
# no significa nada fuera. No se aborta —Jaume manda— pero se avisa fuerte.
MIN_FILAS_FIABLE = 200


class AdvancedModelError(ValueError):
    """Configuración que no puede producir un resultado honesto."""


def parse_config(raw: dict | None) -> dict | None:
    """Valida y normaliza el bloque `advanced_model` de la definición.

    Devuelve None si está ausente o apagado, que es el camino de siempre.
    """
    if not raw or not isinstance(raw, dict) or not raw.get("enabled"):
        return None

    modo = raw.get("mode", "filter")
    if modo not in ("filter", "standalone"):
        raise AdvancedModelError(f"Modo de modelo desconocido: {modo!r}")

    cfg = {
        "mode": modo,
        "train_from": (raw.get("train_from") or "").strip(),
        "train_to": (raw.get("train_to") or "").strip(),
        "test_from": (raw.get("test_from") or "").strip(),
        "test_to": (raw.get("test_to") or "").strip(),
        "threshold": float(raw.get("threshold", 0.5)),
        "features": [f for f in (raw.get("features") or []) if f.get("name")],
        "hmm_enabled": bool(raw.get("hmm_enabled")),
        "hmm_states": int(raw.get("hmm_states") or 3),
        "seed": int(raw.get("seed") or 0),
        # Correr ademas la prueba SIN modelo para comparar metricas.
        # Cuesta un backtest entero mas, por eso va apagado.
        "compare_without_model": bool(raw.get("compare_without_model")),
    }

    for campo in ("train_from", "train_to", "test_from", "test_to"):
        if not cfg[campo]:
            raise AdvancedModelError(
                "Faltan fechas: hay que fijar el periodo de entrenamiento y el "
                "de prueba.")
    if cfg["train_to"] >= cfg["test_from"]:
        raise AdvancedModelError(
            f"El entrenamiento (hasta {cfg['train_to']}) se solapa con la "
            f"prueba (desde {cfg['test_from']}). Si el modelo entrena con días "
            f"que luego se le miden, el resultado no significa nada.")
    if not cfg["features"] and not cfg["hmm_enabled"]:
        raise AdvancedModelError(
            "Hay que elegir al menos un indicador (o activar el HMM): sin "
            "features el modelo no tiene nada que mirar.")
    if not (0.0 <= cfg["threshold"] <= 1.0):
        raise AdvancedModelError("El umbral tiene que estar entre 0 y 1.")
    return cfg


def _rebanada(qualifying_df: pd.DataFrame, desde: str, hasta: str) -> pd.DataFrame:
    """Los ticker-días de una ventana. Es todo el 'reparto' que hace falta."""
    if qualifying_df is None or qualifying_df.empty:
        return qualifying_df
    fechas = pd.to_datetime(qualifying_df["date"]).dt.strftime("%Y-%m-%d")
    return qualifying_df[(fechas >= desde) & (fechas <= hasta)].copy()


def run_with_model(cfg: dict, qualifying_df: pd.DataFrame, run_fn, run_kwargs: dict) -> dict:
    """Las dos pasadas. Devuelve el resultado de la SEGUNDA (el periodo de
    prueba), con un informe del modelo colgado en `advanced_model`."""
    if cfg["mode"] != "filter":
        raise AdvancedModelError(
            "El modo «estrategia» (HMM + features decidiendo por su cuenta) "
            "todavía no está implementado. Por ahora solo el modo filtro.")

    train_qual = _rebanada(qualifying_df, cfg["train_from"], cfg["train_to"])
    test_qual = _rebanada(qualifying_df, cfg["test_from"], cfg["test_to"])

    if train_qual is None or train_qual.empty:
        raise AdvancedModelError(
            f"No hay ni un día en el periodo de entrenamiento "
            f"({cfg['train_from']} → {cfg['train_to']}). Revisa que el dataset "
            f"cubra esas fechas.")
    if test_qual is None or test_qual.empty:
        raise AdvancedModelError(
            f"No hay ni un día en el periodo de prueba "
            f"({cfg['test_from']} → {cfg['test_to']}).")

    avisos: list[str] = []

    # ── Pasada 1: entrenamiento ───────────────────────────────────────────
    t0 = time.time()
    collector = FeatureCollector(feature_defs=cfg["features"],
                                 con_hmm=cfg["hmm_enabled"])
    res_train = run_fn(qualifying_df=train_qual, feature_collector=collector,
                       **run_kwargs)
    t_train_run = time.time() - t0
    trades_train = res_train.get("trades", []) or []
    logger.info("[MODELO] pasada de entrenamiento: %d trades en %.1fs",
                len(trades_train), t_train_run)

    if not trades_train:
        raise AdvancedModelError(
            "La estrategia no hizo ni una operación en el periodo de "
            "entrenamiento, así que no hay nada de lo que aprender. Alarga el "
            "periodo o afloja las condiciones.")

    # ── El HMM, si toca ───────────────────────────────────────────────────
    t0 = time.time()
    hmm = None
    hmm_info: list[dict] = []
    if cfg["hmm_enabled"]:
        hmm = fit_hmm(collector.observaciones(), cfg["hmm_states"], cfg["seed"])
        if hmm is None:
            avisos.append("No hubo datos suficientes para entrenar el HMM; se "
                          "siguió solo con los indicadores.")
        else:
            hmm_info = describe_hmm_states(hmm)

    # ── Etiquetas y entrenamiento del clasificador ────────────────────────
    X, y, descartadas = collector.dataset(trades_train, hmm=hmm)
    t_fit_hmm = time.time() - t0

    if len(X) == 0:
        raise AdvancedModelError(
            "No se pudo emparejar ninguna señal con su operación. Es raro: "
            "revisa que la estrategia opere de verdad en ese periodo.")

    n_pos = int(y.sum())
    if n_pos == 0 or n_pos == len(y):
        raise AdvancedModelError(
            f"En el entrenamiento TODAS las operaciones salieron "
            f"{'bien' if n_pos else 'mal'} ({len(y)} de {len(y)}). Sin ejemplos "
            f"de los dos tipos no hay nada que aprender.")
    if len(y) < MIN_FILAS_FIABLE:
        avisos.append(
            f"Solo {len(y)} operaciones de entrenamiento. Con menos de "
            f"{MIN_FILAS_FIABLE} el modelo memoriza el periodo y el resultado "
            f"del OOS es poco fiable — alarga el entrenamiento.")
    if descartadas:
        avisos.append(
            f"{descartadas} señales no llegaron a operarse (ya había posición "
            f"abierta o se agotaron las reentradas) y se descartaron: «no se "
            f"ejecutó» no es «salió mal».")

    t0 = time.time()
    booster = train_booster(X, y, cfg["seed"])
    t_fit_xgb = time.time() - t0

    nombres = build_feature_names(cfg["features"], len(hmm_info))
    modelo = TrainedModel(
        booster=booster, feature_defs=cfg["features"],
        threshold=cfg["threshold"], hmm=hmm, hmm_states=len(hmm_info),
        feature_names=nombres, importances=importances_of(booster, nombres),
        n_train_rows=len(y), n_train_pos=n_pos,
    )

    # ── Pasada 2: prueba, con el veto puesto ──────────────────────────────
    t0 = time.time()
    res = run_fn(qualifying_df=test_qual, entry_model=modelo, **run_kwargs)
    t_test_run = time.time() - t0
    n_con = len(res.get("trades", []) or [])

    # ── Pasada 3, OPCIONAL: la misma prueba SIN modelo, para comparar ─────
    # Apagada por defecto a propósito: es un backtest entero más, o sea
    # multiplicar la espera por 1,5. La cifra de "cuántas señales vetó" ya la
    # lleva el propio modelo sin coste (`n_seen`/`n_kept`); esta pasada solo
    # hace falta cuando se quieren comparar las MÉTRICAS con y sin filtro.
    metricas_sin = None
    t_ref = 0.0
    if cfg.get("compare_without_model"):
        t0 = time.time()
        res_sin = run_fn(qualifying_df=test_qual, **run_kwargs)
        t_ref = time.time() - t0
        metricas_sin = res_sin.get("aggregate_metrics", {})

    res["advanced_model"] = {
        "mode": cfg["mode"],
        "train": {"from": cfg["train_from"], "to": cfg["train_to"],
                  "operaciones": len(y), "ganadoras": n_pos,
                  "señales_descartadas": descartadas},
        "test": {"from": cfg["test_from"], "to": cfg["test_to"],
                 "operaciones": n_con,
                 # Señales, no operaciones: el simulador puede descartar alguna
                 # (posición ya abierta, tope de reentradas).
                 "señales_vistas": modelo.n_seen,
                 "señales_aceptadas": modelo.n_kept,
                 "señales_vetadas": modelo.n_seen - modelo.n_kept,
                 "pct_vetadas": round((modelo.n_seen - modelo.n_kept) / modelo.n_seen * 100, 1)
                                if modelo.n_seen else 0.0},
        "threshold": cfg["threshold"],
        "features": modelo.feature_names,
        "importancias": modelo.importances,
        "hmm": hmm_info,
        "metricas_sin_modelo": metricas_sin,
        "avisos": avisos,
        "tiempos_s": {
            "backtest_entrenamiento": round(t_train_run, 1),
            "entrenar_hmm_y_etiquetas": round(t_fit_hmm, 1),
            "entrenar_xgboost": round(t_fit_xgb, 2),
            "backtest_prueba": round(t_test_run, 1),
            "backtest_comparacion_sin_modelo": round(t_ref, 1),
        },
    }
    logger.info("[MODELO] prueba: %d operaciones; el modelo vio %d señales y "
                "dejo pasar %d", n_con, modelo.n_seen, modelo.n_kept)
    return res
