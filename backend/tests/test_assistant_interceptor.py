"""Tests del interceptor de bancos dilusores en routers/assistant.py.

Cubre las funciones puras (normalización y parseo de <edgie_metrics>) y el ciclo
de registro/consulta en DuckDB usando una base de datos temporal aislada.
"""
import sys
from pathlib import Path

import duckdb
import pytest

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.routers import assistant as A


# ── Normalización de nombres de bancos ───────────────────────────────────────
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("H.C. Wainwright & Co. LLC", "H C WAINWRIGHT"),
        ("Maxim Group LLC", "MAXIM GROUP"),
        ("Aegis Capital Corp.", "AEGIS CAPITAL"),
        ("Roth Capital Partners", "ROTH CAPITAL PARTNERS"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_bank_name(raw, expected):
    assert A.normalize_bank_name(raw) == expected


def test_normalize_dedupes_suffix_variants():
    """El mismo banco con/sin sufijo corporativo colapsa al mismo nombre."""
    assert A.normalize_bank_name("Maxim Group") == A.normalize_bank_name("Maxim Group LLC")


# ── Parseo de <edgie_metrics> ────────────────────────────────────────────────
def test_extract_edgie_metrics_valid():
    content = (
        '<edgie_metrics>{"dilution_rating":"HIGH","hired_banks":["Maxim Group","H.C. Wainwright"]}'
        "</edgie_metrics>\n# Reporte\nTexto."
    )
    metrics = A.extract_edgie_metrics(content)
    assert metrics is not None
    assert metrics["dilution_rating"] == "HIGH"
    assert metrics["hired_banks"] == ["Maxim Group", "H.C. Wainwright"]


def test_extract_edgie_metrics_missing_or_bad():
    assert A.extract_edgie_metrics("sin tags") is None
    assert A.extract_edgie_metrics("<edgie_metrics>no es json</edgie_metrics>") is None
    assert A.extract_edgie_metrics("") is None


# ── Registro y consulta en DuckDB ────────────────────────────────────────────
@pytest.fixture()
def temp_user_db(tmp_path, monkeypatch):
    """Redirige get_user_db_connection a una BD temporal con la tabla creada."""
    db_path = str(tmp_path / "users_test.duckdb")

    # Crear la tabla una vez con el mismo DDL que init_db.py.
    con0 = duckdb.connect(db_path)
    con0.execute(
        """
        CREATE TABLE IF NOT EXISTS dilution_banks_registry (
            ticker VARCHAR NOT NULL,
            bank_name VARCHAR NOT NULL,
            form_type VARCHAR,
            date_filed DATE,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    con0.close()

    def _fake_conn(read_only=False):
        return duckdb.connect(db_path)

    import app.database as db
    monkeypatch.setattr(db, "get_user_db_connection", _fake_conn)
    return db_path


def test_register_and_query_banks(temp_user_db):
    # Inserta dos bancos para MULN.
    n = A.register_dilution_banks("MULN", ["Maxim Group LLC", "H.C. Wainwright & Co."])
    assert n == 2

    # Re-procesar el mismo ticker NO debe duplicar (dedupe por ticker+bank).
    n2 = A.register_dilution_banks("MULN", ["Maxim Group", "Maxim Group LLC"])
    assert n2 == 0

    # El mismo banco en otro ticker sí cuenta como aparición nueva.
    A.register_dilution_banks("XYZ", ["Maxim Group"])

    known = A.get_known_dilution_banks("MULN")
    by_name = {b["bank_name"]: b for b in known}
    assert "MAXIM GROUP" in by_name
    # Maxim aparece en 2 tickers distintos (MULN, XYZ).
    assert by_name["MAXIM GROUP"]["ticker_count"] == 2
    assert by_name["MAXIM GROUP"]["seen_here"] is True


def test_register_ignores_empty(temp_user_db):
    assert A.register_dilution_banks("", ["Maxim Group"]) == 0
    assert A.register_dilution_banks("MULN", []) == 0
