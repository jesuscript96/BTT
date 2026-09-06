"""
Pytest configuration and shared fixtures for automated testing.
Uses REAL data - no mocks. Los tests corren en LOCAL contra el lago de verdad.

EL .ENV SE CARGA AQUI, Y NO ES UN DETALLE. Sin esto `DB_PROVIDER` cae a su
valor por defecto (`motherduck`) en vez del `local` que usa la aplicacion, la
conexion se va a una base que no existe, y CIENTO DIEZ tests fallan con «Table
with name daily_metrics does not exist». Estuvieron asi meses, contados como
fallos del programa cuando el programa estaba bien: al arreglarlo, la suite
paso de 666 a 718 tests en verde (auditoria del 5-sep-2026).
"""
import os
import sys
from pathlib import Path

import duckdb
import pytest

# Add backend to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

# ANTES de importar nada de `app`: el proveedor se lee al abrir la conexion.
try:
    from dotenv import load_dotenv
    load_dotenv(backend_dir / ".env")
except ImportError:                                          # pragma: no cover
    pass
os.environ.setdefault("DB_PROVIDER", "local")

from app.database import get_db_connection

# Lo que los tests de datos dan por hecho que existe.
_TABLAS = ("daily_metrics", "intraday_1m")


def _falta(con, nombre: str) -> bool:
    """¿Ni tabla ni vista con ese nombre?"""
    for consulta in ("SELECT count(*) FROM duckdb_tables() WHERE table_name = ?",
                     "SELECT count(*) FROM duckdb_views() WHERE view_name = ?"):
        try:
            if con.execute(consulta, [nombre]).fetchone()[0]:
                return False
        except Exception:                                    # noqa: BLE001
            pass
    return True


@pytest.fixture(scope="session")
def real_db():
    """Conexion al lago real, en solo lectura, para los tests de validacion.

    SI EL BACKEND ESTA EN MARCHA, ESTOS TESTS SE SALTAN. DuckDB admite un solo
    escritor: con `local_data.duckdb` abierto por uvicorn no se puede abrir.

    DOS CAMINOS, y hay que cubrir los dos:

      * `get_db_connection` LANZA (comportamiento de hoy: se arreglo para que
        reviente en vez de devolver una base vacia y servir la aplicacion sin
        datos — ver el comentario largo en `app/database.py`).
      * o devuelve una conexion SIN LAS TABLAS, que es lo que hacia antes y lo
        que puede seguir pasando si la base existe pero esta a medias.

    Saltar con el motivo escrito es mucho mejor que fallar: un `skip` que dice
    «apaga el backend» se arregla en diez segundos, mientras que cien «Catalog
    Error» se quedan meses sin que nadie sepa si el roto es el motor.
    """
    aviso = (f"El lago no responde. Casi siempre es que el BACKEND ESTA EN "
             f"MARCHA y tiene local_data.duckdb abierto (DuckDB admite un solo "
             f"escritor): parar uvicorn y repetir. "
             f"DB_PROVIDER={os.getenv('DB_PROVIDER')}")
    try:
        con = get_db_connection(read_only=True)
    except Exception as e:                                   # noqa: BLE001
        pytest.skip(f"{aviso}\nMotivo: {e}")
    faltan = [t for t in _TABLAS if _falta(con, t)]
    if faltan:
        pytest.skip(f"{aviso}\nFaltan las tablas: {', '.join(faltan)}")
    yield con
    con.close()


@pytest.fixture(scope="session")
def test_db():
    """
    Connection to a SEPARATE local test database for write operations.
    Located at backend/test_backtester.duckdb
    This is used ONLY for tests that need to write data.
    """
    test_db_path = backend_dir / "test_backtester.duckdb"
    
    # Create fresh test database
    if test_db_path.exists():
        test_db_path.unlink()
    
    con = duckdb.connect(str(test_db_path))
    yield con
    con.close()


@pytest.fixture(scope="session")
def sample_tickers(real_db):
    """
    Get a small sample of real tickers from MotherDuck for testing.
    Returns list of ticker symbols that have data.
    """
    result = real_db.execute("""
        SELECT DISTINCT ticker 
        FROM daily_metrics 
        LIMIT 5
    """).fetchall()
    
    return [row[0] for row in result]


@pytest.fixture(scope="function")
def sample_daily_data(real_db, sample_tickers):
    """
    Get a sample of real daily_metrics data from MotherDuck.
    Returns a small but representative dataset for testing.
    """
    if not sample_tickers:
        return []
    
    placeholders = ",".join(["?" for _ in sample_tickers])
    query = f"""
        SELECT * FROM daily_metrics
        WHERE ticker IN ({placeholders})
        LIMIT 100
    """
    
    df = real_db.execute(query, sample_tickers).fetch_df()
    return df


@pytest.fixture(scope="function")
def sample_historical_data(real_db, sample_tickers):
    """
    Get a sample of real intraday historical data from MotherDuck.
    Returns 1-minute bars from real database.
    """
    if not sample_tickers:
        return []
    
    # Get one day of data for first ticker
    ticker = sample_tickers[0]
    query = """
        SELECT * FROM historical_data
        WHERE ticker = ?
        ORDER BY timestamp ASC
        LIMIT 390  -- One full RTH session
    """
    
    df = real_db.execute(query, [ticker]).fetch_df()
    return df
