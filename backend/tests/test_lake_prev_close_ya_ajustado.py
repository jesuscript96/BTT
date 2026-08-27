"""Interruptor LAKE_PREV_CLOSE_YA_AJUSTADO: el mismo backend para dos lagos.

Los dos lagos de este repo ajustan el split en CAPAS distintas (ver
docs/MEMORIA_MADRE.md, "Por que sus parches de splits NO se pueden adoptar
aqui"):

- lago de esta rama (cangrejo_data): `prev_close` CRUDO -> el backend ajusta
  por product(split_from/split_to) al recalcular `pmh_gap_pct` (default);
- lago de Sailor: el ETL hornea el factor DENTRO de `prev_close` -> si el
  backend volviera a aplicarlo seria un DOBLE ajuste (medido: NVDA 1,08%
  correcto pasaria a 910,77% falso).

La variable apaga el recalculo entero donde no hace falta (regla R7: apagada
por defecto). Cubre los DOS sitios que recalculan: la carga mensual
(`lake_db_loader._alinear_pmh_gap_pct`) y la migracion de arranque
(`init_db.init_db`).

Todo con DuckDB en memoria + lago de mentira en tmp_path: nada de la BD
remota, ni ficheros reales, ni RED.
"""

import duckdb
import pytest

from app.services.lake_db_loader import _alinear_pmh_gap_pct

# Mes de junio 2024 como literales [inicio, fin) — lo que le pasa a
# _alinear_pmh_gap_pct el cargador de meses.
MES = ("2024-06-01 00:00:00", "2024-07-01 00:00:00")

# Valor centinela imposible: si el test lo ve despues de la llamada, el
# recalculo NO ha tocado la fila (que es justo lo que se quiere probar con el
# flag encendido).
CENTINELA = -999.0


def _con_con_dias() -> duckdb.DuckDBPyConnection:
    """daily_metrics minima con un dia de split y un dia normal.

    Dia de split (NVDA 2024-06-10, 1->10): prev_close crudo 1000 -> ajustado
    100, pm_high 101 -> gap 1,0%. Sin el factor daria -89,9%, el gap falso
    clasico de los splits.
    Dia normal (2024-06-11): prev_close 100, pm_high 105 -> gap 5,0%.
    """
    con = duckdb.connect()
    con.execute(
        """
        CREATE TABLE daily_metrics (
            ticker VARCHAR,
            timestamp TIMESTAMP,
            pm_high DOUBLE,
            prev_close DOUBLE,
            pmh_gap_pct DOUBLE
        )
        """
    )
    con.execute(
        "INSERT INTO daily_metrics VALUES "
        f"('NVDA', TIMESTAMP '2024-06-10 21:00:00', 101.0, 1000.0, {CENTINELA}), "
        f"('NVDA', TIMESTAMP '2024-06-11 21:00:00', 105.0, 100.0, {CENTINELA})"
    )
    return con


def _crear_lago_con_splits(raiz) -> None:
    """Escribe <raiz>/splits/data.parquet con el split 1->10 de NVDA."""
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE splits (ticker VARCHAR, execution_date DATE, "
        "split_from DOUBLE, split_to DOUBLE)"
    )
    con.execute("INSERT INTO splits VALUES ('NVDA', DATE '2024-06-10', 1.0, 10.0)")
    destino = raiz / "splits"
    destino.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY splits TO '{(destino / 'data.parquet').as_posix()}' (FORMAT PARQUET)")
    con.close()


def _gaps(con) -> list[float]:
    return [f[0] for f in con.execute(
        "SELECT pmh_gap_pct FROM daily_metrics ORDER BY timestamp").fetchall()]


# ---------------------------------------------------------------------------
# Sitio 1: carga mensual (_alinear_pmh_gap_pct)
# ---------------------------------------------------------------------------
def test_por_defecto_aplica_el_factor_de_split(tmp_path, monkeypatch):
    _crear_lago_con_splits(tmp_path)
    monkeypatch.setenv("LOCAL_LAKE_DIR", str(tmp_path))
    monkeypatch.delenv("LAKE_PREV_CLOSE_YA_AJUSTADO", raising=False)

    con = _con_con_dias()
    _alinear_pmh_gap_pct(con, *MES)

    dia_split, dia_normal = _gaps(con)
    assert dia_split == pytest.approx(1.0)
    assert dia_normal == pytest.approx(5.0)


def test_flag_true_deja_el_valor_del_etl_y_no_exige_parquet(tmp_path, monkeypatch):
    vacio = tmp_path / "vacio"
    vacio.mkdir()
    monkeypatch.setenv("LOCAL_LAKE_DIR", str(vacio))
    monkeypatch.setenv("LAKE_PREV_CLOSE_YA_AJUSTADO", "true")

    con = _con_con_dias()
    mensajes: list[str] = []
    _alinear_pmh_gap_pct(con, *MES, log=mensajes.append)

    # Avisa, no lo hace en silencio (regla de esta casa).
    assert any("LAKE_PREV_CLOSE_YA_AJUSTADO" in m for m in mensajes)
    # Y no toca ninguna fila: el valor del ETL manda.
    assert _gaps(con) == [CENTINELA, CENTINELA]


def test_por_defecto_sin_parquet_de_splits_sigue_reventando(tmp_path, monkeypatch):
    vacio = tmp_path / "vacio"
    vacio.mkdir()
    monkeypatch.setenv("LOCAL_LAKE_DIR", str(vacio))
    monkeypatch.delenv("LAKE_PREV_CLOSE_YA_AJUSTADO", raising=False)

    con = _con_con_dias()
    with pytest.raises(RuntimeError):
        _alinear_pmh_gap_pct(con, *MES)


# ---------------------------------------------------------------------------
# Sitio 2: migracion de arranque (init_db)
# ---------------------------------------------------------------------------
def _arrancar_initdb(tmp_path, monkeypatch, flag: bool) -> duckdb.DuckDBPyConnection:
    """init_db() contra un DuckDB en memoria y el lago de mentira.

    La tabla daily_metrics se crea ANTES con los dias de prueba: el CREATE
    TABLE IF NOT EXISTS de init_db la respeta, y asi la migracion del arranque
    corre sobre datos conocidos.
    """
    if flag:
        monkeypatch.setenv("LAKE_PREV_CLOSE_YA_AJUSTADO", "true")
    else:
        monkeypatch.delenv("LAKE_PREV_CLOSE_YA_AJUSTADO", raising=False)
    monkeypatch.setenv("DB_PROVIDER", "local")
    monkeypatch.setenv("LOCAL_LAKE_DIR", str(tmp_path))

    con = _con_con_dias()
    monkeypatch.setattr("app.init_db.get_db_connection", lambda: con)
    monkeypatch.setattr("app.init_db.get_user_db_connection", lambda: con)

    from app import init_db as init_db_mod
    init_db_mod.init_db()
    return con


def test_initdb_arranque_aplica_factor_por_defecto(tmp_path, monkeypatch, capsys):
    _crear_lago_con_splits(tmp_path)

    con = _arrancar_initdb(tmp_path, monkeypatch, flag=False)

    assert "split-adjusted" in capsys.readouterr().out
    dia_split, dia_normal = _gaps(con)
    assert dia_split == pytest.approx(1.0)
    assert dia_normal == pytest.approx(5.0)


def test_initdb_arranque_con_flag_true_no_toca_nada(tmp_path, monkeypatch, capsys):
    # Sin parquet de splits a proposito: con el flag encendido ni hace falta.
    vacio = tmp_path / "vacio"
    vacio.mkdir()

    con = _arrancar_initdb(vacio, monkeypatch, flag=True)

    assert "LAKE_PREV_CLOSE_YA_AJUSTADO=true" in capsys.readouterr().out
    assert _gaps(con) == [CENTINELA, CENTINELA]
