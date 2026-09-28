# -*- coding: utf-8 -*-
"""Tests del indicador «Gappers activos (+X %)» (7.2b, 2026-09-28).

Sin lago real: tabla mini en tmp + flag por monkeypatch. Se valida:
  1. Sin GAPPERS_ACTIVE_ENABLED el indicador NO calcula (NaN, sin excepción).
  2. Con flag + tabla: contador causal por vela (cruces <= minuto de la vela).
  3. Nivel no admitido / fecha ausente → NaN ruidoso, nunca 0 silencioso.
  4. Las velas >= 09:30 ven el contador FINAL del premarket.
  5. El parámetro gap_pct viaja por compute_indicator (cache distinto por nivel).
"""
import os

import numpy as np
import pandas as pd
import pytest

from app.services import gappers_active as ga
from app.services.indicators import compute_indicator


def _tabla_mini(tmp_path):
    # 2024-01-02: 3 acciones cruzan +50 % — A a t=720 (04:00), B a t=780
    # (05:00), C a t=900 (07:00). Y a +20 %: A,B,C,D (D solo llega a +20).
    filas = [
        ("2024-01-02", 50, 720), ("2024-01-02", 50, 780), ("2024-01-02", 50, 900),
        ("2024-01-02", 20, 721), ("2024-01-02", 20, 781), ("2024-01-02", 20, 901),
        ("2024-01-02", 20, 960),
    ]
    df = pd.DataFrame(filas, columns=["fecha", "nivel", "t"])
    ruta = str(tmp_path / "gappers_mini.parquet")
    df.to_parquet(ruta, index=False)
    return ruta


def _frame():
    velas = pd.DataFrame({
        "timestamp": ["2024-01-02 04:00", "2024-01-02 04:30",
                      "2024-01-02 05:00", "2024-01-02 07:00",
                      "2024-01-02 09:31", "2024-01-02 10:00"],
        "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1,
    })
    return velas


@pytest.fixture()
def entorno(tmp_path, monkeypatch):
    ruta = _tabla_mini(tmp_path)
    monkeypatch.setenv("GAPPERS_ACTIVE_ENABLED", "true")
    monkeypatch.setenv("GAPPERS_ACTIVE_TABLE", ruta)
    ga._TABLA = None  # reset del cache de proceso
    yield ruta
    ga._TABLA = None


def test_sin_flag_devuelve_nan(tmp_path, monkeypatch):
    monkeypatch.delenv("GAPPERS_ACTIVE_ENABLED", raising=False)
    ga._TABLA = None
    df = _frame()
    ds = {"date": "2024-01-02", "ticker": "X"}
    s = compute_indicator("Gappers activos", df, daily_stats=ds, gap_pct=50)
    assert s.isna().all()
    ga._TABLA = None


def test_contador_causal_por_vela(entorno):
    df = _frame()
    ds = {"date": "2024-01-02", "ticker": "X"}
    s = compute_indicator("Gappers activos", df, daily_stats=ds, gap_pct=50)
    # 04:00 (t=720): 1 cruce <= 720 → 1 · 04:30 (750): 1 · 05:00 (780): 2
    # (cruce EN 780 cuenta: side=right) · 07:00 (900): 3 · >=09:30: 3 final
    assert list(s.astype(int)) == [1, 1, 2, 3, 3, 3]


def test_nivel_no_admitido_es_nan_ruidoso(entorno):
    df = _frame()
    ds = {"date": "2024-01-02", "ticker": "X"}
    s = compute_indicator("Gappers activos", df, daily_stats=ds, gap_pct=55)
    assert s.isna().all()


def test_fecha_ausente_es_nan_no_cero(entorno):
    df = _frame()
    ds = {"date": "2020-01-01", "ticker": "X"}
    s = compute_indicator("Gappers activos", df, daily_stats=ds, gap_pct=50)
    assert s.isna().all()


def test_nivel_20_y_cache_por_nivel(entorno):
    df = _frame()
    ds = {"date": "2024-01-02", "ticker": "X"}
    cache = {}
    s20 = compute_indicator("Gappers activos", df, daily_stats=ds, gap_pct=20,
                            cache=cache)
    s50 = compute_indicator("Gappers activos", df, daily_stats=ds, gap_pct=50,
                            cache=cache)
    assert list(s20.astype(int)) == [0, 1, 1, 2, 4, 4]
    # cruces +20: t=721 (04:01) no cuenta en la vela 04:00 (causal);
    # D cruza a t=960 (08:00) y solo entra al contador desde el final
    assert list(s50.astype(int)) == [1, 1, 2, 3, 3, 3]
    assert len(cache) == 2  # gap_pct va en la clave: dos series distintas


def test_sin_fecha_sin_nan_tampoco(entorno):
    df = _frame()
    s = compute_indicator("Gappers activos", df, daily_stats={}, gap_pct=50)
    assert s.isna().all()
