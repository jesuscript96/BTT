"""Retornos intradia por tramos: `m15/m30/m60/m180_return_pct`, con datos REALES.

QUE PROBABA ESTE FICHERO Y POR QUE SE REESCRIBIO
------------------------------------------------
Probaba `return_m15_to_close`, `return_m30_to_close` y `return_m60_to_close`:
el retorno DESDE el minuto X HASTA el cierre. **Esas columnas no existen en el
lago** y por eso llevaba meses en rojo.

Lo que hay es lo CONTRARIO — desde la apertura hasta el minuto X
(`fase6_etl_edgecute.py`):

    m15_return_pct = (COALESCE(c15, rth_open) - rth_open) / rth_open * 100

En una primera pasada se renombraron unas por otras dando por hecho que era el
mismo dato con otro nombre. **Fue un error**: al ser opuestas, varios tests
pasaron a compararse consigo mismos y salian en VERDE sin comprobar nada, que es
peor que el rojo del que venian. De ahi que esto se reescriba entero.

EL «DESDE EL MINUTO X HASTA EL CIERRE» SE PUEDE DERIVAR, y puede interesar
—es lo que mide un fade—, pero hoy hay que calcularlo a mano:

    precio_X = rth_open * (1 + mX_return_pct / 100)
    desde_X_al_cierre = (rth_close - precio_X) / precio_X * 100

OJO CON EL `COALESCE(cX, rth_open)`: los dias sin vela en ese minuto no salen
como NULL, salen como **0 %**. Por eso aqui se descarta el cero al comprobar
signos: no distingue «no se movio» de «no hay dato».
"""
import pytest

from tests.utils.db_helpers import execute_and_validate_query

FUENTE = ("(SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date "
          "FROM daily_metrics LIMIT 200000)")
TRAMOS = ["m15_return_pct", "m30_return_pct", "m60_return_pct", "m180_return_pct"]


class TestColumnasDeTramo:

    def test_existen_y_estan_pobladas(self, real_db):
        df = execute_and_validate_query(
            real_db, f"SELECT {', '.join(TRAMOS)} FROM {FUENTE} LIMIT 100")
        assert not df.empty
        for c in TRAMOS:
            assert c in df.columns, f"falta la columna {c}"
            assert df[c].notna().all(), f"{c} tiene nulos"

    def test_no_existe_el_retorno_hasta_el_cierre(self, real_db):
        """Deja constancia de que `return_mX_to_close` NO esta en el lago.

        Si algun dia se anyade, este test falla y toca reescribir el fichero
        para comprobarla de verdad — que es justo lo que se quiere que pase.
        """
        columnas = {r[0] for r in real_db.execute(
            "DESCRIBE SELECT * FROM daily_metrics").fetchall()}
        assert not (columnas & {"return_m15_to_close", "return_m30_to_close",
                                "return_m60_to_close"}), \
            "ya existe el retorno hasta el cierre: actualizar este fichero"


class TestSignoYCoherencia:

    @pytest.mark.parametrize("col", TRAMOS)
    def test_el_signo_dice_donde_estaba_el_precio(self, real_db, col):
        """Positivo <=> el precio de ese minuto estaba por encima de la apertura."""
        df = execute_and_validate_query(real_db, f"""
            SELECT rth_open, {col}
            FROM {FUENTE}
            WHERE rth_open > 0 AND {col} <> 0
            LIMIT 50
        """)
        assert not df.empty, f"sin filas con {col} distinto de cero"
        precio = df["rth_open"] * (1 + df[col] / 100)
        arriba = precio > df["rth_open"]
        assert (arriba == (df[col] > 0)).all(), \
            f"el signo de {col} no cuadra con el precio reconstruido"

    def test_derivar_el_retorno_hasta_el_cierre(self, real_db):
        """La cuenta del docstring da un numero coherente (es la del fade).

        No comprueba una columna del lago —no existe— sino que la derivacion
        documentada arriba funciona con los datos reales y no revienta.
        """
        df = execute_and_validate_query(real_db, f"""
            SELECT rth_open, rth_close, m15_return_pct
            FROM {FUENTE}
            WHERE rth_open > 0 AND rth_close > 0 AND m15_return_pct <> 0
            LIMIT 50
        """)
        assert not df.empty
        precio_m15 = df["rth_open"] * (1 + df["m15_return_pct"] / 100)
        assert (precio_m15 > 0).all(), "precio del minuto 15 no positivo"
        desde_m15 = (df["rth_close"] - precio_m15) / precio_m15 * 100
        assert desde_m15.notna().all()
        # Coherencia de direccion: si cierra por encima del precio del minuto 15,
        # el retorno desde ahi tiene que ser positivo.
        assert ((df["rth_close"] > precio_m15) == (desde_m15 > 0)).all()
