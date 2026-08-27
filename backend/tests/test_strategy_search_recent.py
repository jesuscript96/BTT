"""Tests de los endpoints de 'Últimas pruebas' (Portfolio).

Cubre GET /strategy-search/recent (listado LIGERO: sin results_json) y
GET /strategy-search/{backtest_id} (payload completo por id). DuckDB en un
archivo temporal + tabla sintética sembrada con el propio persist_backtest_row
— nada de la BD remota ni del lago.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.routers import strategy_search


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "users.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        """
        CREATE TABLE backtest_results (
            id VARCHAR PRIMARY KEY, strategy_ids VARCHAR, results_json VARCHAR,
            total_trades INTEGER, win_rate DOUBLE, profit_factor DOUBLE,
            avg_r_multiple DOUBLE, total_return_r DOUBLE, total_return_pct DOUBLE,
            max_drawdown_pct DOUBLE, sharpe_ratio DOUBLE, executed_at TIMESTAMP,
            search_mode VARCHAR, search_space VARCHAR, user_id VARCHAR
        )
        """
    )
    base = datetime(2026, 8, 27, 12, 0, 0)
    rows = [
        # (id, mode, desplazamiento de executed_at en minutos)
        ("job-auto-0", "auto", 0),
        ("job-auto-1", "auto", 5),
        ("job-manual-0", "manual", 10),
    ]
    for i, (rid, mode, mins) in enumerate(rows):
        payload = {
            "aggregate_metrics": {"win_rate_pct": 50.0 + i, "total_trades": i + 1},
            "trades": [],
            "global_equity": [100.0, 101.0],
            "backtest_params": {"dataset_id": "ds-1", "init_cash": 10000},
            "strategy_definition": {"name": "Borrador", "bias": "short"},
            "strategy_names": ["Borrador"],
            "label": f"[{mode}] Borrador · run {i}",
        }
        strategy_search.persist_backtest_row(
            con,
            id=rid,
            strategy_ids=[f"strat-{i}"],
            results_json=payload,
            search_mode=mode,
            search_space="auto_run" if mode == "auto" else "user_save",
            user_id=None,
        )
        # executed_at distincto y explícito: el INSERT usa datetime.now() y en
        # un bucle apretado pueden coincidir, dejando el ORDER BY indeterminado.
        con.execute(
            "UPDATE backtest_results SET executed_at = ? WHERE id = ?",
            [base + timedelta(minutes=mins), rid],
        )
    con.close()
    return str(path)


@pytest.fixture(autouse=True)
def patch_db(monkeypatch, db_path):
    """Cada llamada a get_user_db_connection abre su propia conexión al archivo
    temporal (los endpoints hacen con.close() al terminar)."""
    monkeypatch.setattr(
        strategy_search,
        "get_user_db_connection",
        lambda read_only=False: duckdb.connect(db_path),
    )


def test_recent_es_ligero_y_ordenado():
    res = strategy_search.list_recent_runs(limit=10, search_mode=None, user_id=None)
    runs = res["runs"]
    assert res["count"] == 3
    # Sin results_json: es justo lo que hace pesado a /list (decenas de MB).
    for r in runs:
        assert "results_json" not in r
    # ORDER BY executed_at DESC → el manual (último sembrado) primero.
    assert runs[0]["id"] == "job-manual-0"
    assert runs[0]["search_mode"] == "manual"
    # El label sale por json_extract, sin cargar el payload.
    assert runs[1]["label"] == "[auto] Borrador · run 1"
    assert runs[1]["strategy_ids"] == ["strat-1"]
    # Métricas tipadas mapeadas desde aggregate_metrics.
    assert runs[2]["win_rate"] == pytest.approx(50.0)
    assert runs[2]["total_trades"] == 1


def test_recent_filtra_por_modo():
    res = strategy_search.list_recent_runs(limit=10, search_mode="auto", user_id=None)
    assert res["count"] == 2
    assert all(r["search_mode"] == "auto" for r in res["runs"])


def test_recent_limit():
    res = strategy_search.list_recent_runs(limit=2, search_mode=None, user_id=None)
    assert res["count"] == 2
    assert [r["id"] for r in res["runs"]] == ["job-manual-0", "job-auto-1"]


def test_get_por_id_devuelve_payload_completo():
    res = strategy_search.get_backtest_by_id("job-auto-0", user_id=None)
    assert res["id"] == "job-auto-0"
    assert res["strategy_ids"] == ["strat-0"]
    payload = res["results_json"]
    # Lo que necesita la reapertura en el backtester:
    assert payload["backtest_params"]["dataset_id"] == "ds-1"
    assert payload["strategy_definition"]["name"] == "Borrador"
    assert payload["global_equity"] == [100.0, 101.0]
    assert payload["label"].startswith("[auto]")


def test_get_por_id_inexistente_404():
    with pytest.raises(HTTPException) as exc:
        strategy_search.get_backtest_by_id("no-existe", user_id=None)
    assert exc.value.status_code == 404
