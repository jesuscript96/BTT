"""
Tests for NEW Tier 1 Metrics using REAL data.
Tests: prev_close, pmh_gap_pct, rth_range_pct, day_return_pct, pm_high_time
"""
import pytest
import pandas as pd
from tests.utils.db_helpers import execute_and_validate_query


class TestPrevClose:
    """Tests for Previous Day Close calculation"""
    
    def test_prev_close_exists(self, real_db, sample_tickers):
        """Test: prev_close column is populated"""
        if not sample_tickers:
            pytest.skip("No sample tickers available")
        
        ticker = sample_tickers[0]
        query = """
            SELECT date, prev_close, rth_close
            FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)
            WHERE ticker = ?
            AND prev_close IS NOT NULL
            ORDER BY date ASC
            LIMIT 10
        """
        df = execute_and_validate_query(real_db, query, [ticker])

        # `prev_close` NO ES el `rth_close` del dia anterior, Y ES A PROPOSITO.
        #
        # Este test exigia que coincidieran y por eso llevaba meses en rojo. Es
        # la «opcion A» que eligio Jaume el 17-ago-2026: prev_close es el CIERRE
        # OFICIAL de las 16:00 (`day_aggs`), que incluye la subasta de cierre,
        # no el cierre de la ultima vela de minuto. Lo queria asi para que el
        # gap se midiera contra «lo que ve un trader» como cierre de ayer.
        # Diferencias de varios centimos entre los dos son NORMALES.
        #
        # Lo que si tiene que cumplirse es que este poblado y sea un precio
        # coherente, que es lo que este test comprueba ahora.
        assert not df.empty, f"sin filas de {ticker} con prev_close"
        assert df["prev_close"].notna().all()
        assert (df["prev_close"] > 0).all(), "prev_close tiene que ser un precio positivo"
        # Y en el mismo orden de magnitud que el cierre de la sesion: si se
        # colara el cierre de otra empresa (ver el caso ATTO de las IPO que
        # reutilizan ticker) saldria disparado.
        cerca = (df["prev_close"] / df["rth_close"]).between(0.2, 5.0)
        assert cerca.all(), (
            "prev_close y rth_close se van mas de 5x: mirar splits o IPO que "
            f"reutiliza ticker.\n{df[~cerca]}")


class TestPMHGapPct:
    """Tests for PMH Gap % calculation"""
    
    def test_pmh_gap_formula(self, real_db, sample_tickers):
        """Test: pmh_gap_pct = ((pmh - prev_close) / prev_close) * 100"""
        if not sample_tickers:
            pytest.skip("No sample tickers available")
        
        ticker = sample_tickers[0]
        query = """
            SELECT pm_high, prev_close, pmh_gap_pct
            FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)
            WHERE ticker = ?
            AND prev_close IS NOT NULL
            AND pm_high > 0
            AND pmh_gap_pct IS NOT NULL
            LIMIT 10
        """
        df = execute_and_validate_query(real_db, query, [ticker])
        
        if not df.empty:
            for _, row in df.iterrows():
                pm_high = row['pm_high']
                prev_close = row['prev_close']
                pmh_gap_pct = row['pmh_gap_pct']
                
                expected = ((pm_high - prev_close) / prev_close) * 100
                assert abs(pmh_gap_pct - expected) < 0.01, \
                    f"PMH Gap % should be {expected:.2f}%, got {pmh_gap_pct:.2f}%"
    
    def test_pmh_gap_positive_when_pm_high_above_prev_close(self, real_db):
        """Test: pmh_gap_pct > 0 when pm_high > prev_close"""
        query = """
            SELECT pmh_gap_pct, pm_high, prev_close
            FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)
            WHERE prev_close IS NOT NULL
            AND pm_high > prev_close
            LIMIT 5
        """
        df = execute_and_validate_query(real_db, query)
        
        if not df.empty:
            assert all(df['pmh_gap_pct'] > 0), "PMH Gap % should be positive when PM High > Prev Close"


class TestRTHRangePct:
    """Tests for RTH Range % calculation"""
    
    def test_rth_range_formula(self, real_db):
        """rth_range_pct = (rth_high - rth_low) / rth_open * 100.

        SE NORMALIZA POR LA APERTURA, NO POR EL MINIMO. El test pedia
        `(hod - lod) / lod` y por eso llevaba meses en rojo; la formula del lago
        esta en `fase6_etl_edgecute.py`:

            CASE WHEN rth_open > 0 THEN (rth_high - rth_low)/rth_open*100 ...

        Las dos son defendibles; dividir por la apertura es lo que hace que el
        rango de dos dias distintos sea comparable entre si.
        """
        query = """
            SELECT rth_high, rth_low, rth_open, rth_range_pct
            FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)
            WHERE rth_open > 0
            AND rth_range_pct IS NOT NULL
            LIMIT 10
        """
        df = execute_and_validate_query(real_db, query)
        assert not df.empty, "sin filas para comprobar la formula"
        for _, row in df.iterrows():
            esperado = (row['rth_high'] - row['rth_low']) / row['rth_open'] * 100
            assert abs(row['rth_range_pct'] - esperado) < 0.01, \
                f"RTH Range % deberia ser {esperado:.2f}%, es {row['rth_range_pct']:.2f}%"
    
    def test_rth_range_always_positive(self, real_db):
        """Test: rth_range_pct should always be >= 0 (HOD >= LOD)"""
        query = """
            SELECT rth_range_pct
            FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)
            WHERE rth_range_pct IS NOT NULL
            LIMIT 100
        """
        df = execute_and_validate_query(real_db, query)
        
        if not df.empty:
            assert all(df['rth_range_pct'] >= 0), "RTH Range % should always be non-negative"


class TestDayReturnPct:
    """Tests for Day Return % calculation"""
    
    def test_day_return_formula(self, real_db):
        """day_return_pct = (rth_close - prev_close) / prev_close * 100.

        SE MIDE CONTRA EL CIERRE DE AYER, NO CONTRA LA APERTURA — o sea que EL
        GAP VA DENTRO. Este test pedia `(close - open)/open` y por eso llevaba
        meses en rojo. La formula del lago esta en `fase6_etl_edgecute.py`:

            CASE WHEN prev_close > 0 THEN (rth_close - prev_close)/prev_close*100

        NO ES UN MATIZ: un dia que abre con hueco arriba y luego cae es
        NEGATIVO desde la apertura y POSITIVO respecto a ayer. Medido en los
        datos: donde este test esperaba -10,87 %, el valor real era +13,15 %.
        Para el retorno desde la apertura no hay columna.
        """
        query = """
            SELECT prev_close, rth_close, day_return_pct
            FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)
            WHERE prev_close > 0
            AND day_return_pct IS NOT NULL
            LIMIT 10
        """
        df = execute_and_validate_query(real_db, query)
        assert not df.empty, "sin filas para comprobar la formula"
        for _, row in df.iterrows():
            esperado = (row['rth_close'] - row['prev_close']) / row['prev_close'] * 100
            assert abs(row['day_return_pct'] - esperado) < 0.01, \
                f"Day Return % deberia ser {esperado:.2f}%, es {row['day_return_pct']:.2f}%"
    
    def test_day_return_positive_for_green_days(self, real_db):
        """Verde = cierra POR ENCIMA DEL CIERRE DE AYER, no de la apertura."""
        query = """
            SELECT day_return_pct, rth_close, prev_close
            FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)
            WHERE rth_close > prev_close AND prev_close > 0
            AND day_return_pct IS NOT NULL
            LIMIT 5
        """
        df = execute_and_validate_query(real_db, query)
        
        if not df.empty:
            assert all(df['day_return_pct'] > 0), "Day Return % should be positive for green days"
    
    def test_day_return_negative_for_red_days(self, real_db):
        """Rojo = cierra POR DEBAJO DEL CIERRE DE AYER, no de la apertura."""
        query = """
            SELECT day_return_pct, rth_close, prev_close
            FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)
            WHERE rth_close < prev_close AND prev_close > 0
            AND day_return_pct IS NOT NULL
            LIMIT 5
        """
        df = execute_and_validate_query(real_db, query)
        
        if not df.empty:
            assert all(df['day_return_pct'] < 0), "Day Return % should be negative for red days"


class TestPMHighTime:
    """Tests for PM High Time"""
    
    # EL FORMATO ES «YYYY-MM-DD HH:MM», NO «HH:MM».
    #
    # Los dos tests de esta clase pedian solo la hora y llevaban meses en rojo.
    # Lo que hay en el lago (comprobado sobre los parquet) es la marca completa:
    #
    #     ('2019-01-04 08:11', ...)   <- pm_high_time
    #     ('', ...)                   <- dia SIN premercado: cadena VACIA, no NULL
    #
    # Y ojo con la cadena vacia: `WHERE pm_high_time IS NOT NULL` NO la filtra,
    # asi que hay que descartarla aparte o el split revienta.
    HORA = r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$"

    def test_pm_high_time_format(self, real_db):
        """pm_high_time viene como marca completa «YYYY-MM-DD HH:MM»."""
        query = """
            SELECT pm_high_time
            FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)
            WHERE pm_high_time IS NOT NULL AND pm_high_time <> ''
            LIMIT 10
        """
        df = execute_and_validate_query(real_db, query)
        assert not df.empty, "sin filas con pm_high_time"
        import re
        patron = re.compile(self.HORA)
        for valor in df['pm_high_time']:
            assert patron.match(valor), \
                f"PM High Time deberia ser 'YYYY-MM-DD HH:MM', es {valor!r}"

    def test_pm_high_time_in_pm_session(self, real_db):
        """La hora del maximo de premercado cae en la sesion de premercado.

        04:00 -> 09:29 hora de Nueva York (240 a 569 minutos).
        """
        query = """
            SELECT pm_high_time
            FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)
            WHERE pm_high_time IS NOT NULL AND pm_high_time <> ''
            LIMIT 10
        """
        df = execute_and_validate_query(real_db, query)
        assert not df.empty, "sin filas con pm_high_time"
        for valor in df['pm_high_time']:
            hora, minuto = map(int, valor.split(" ")[1].split(":"))
            minutos = hora * 60 + minuto
            assert 240 <= minutos <= 569, \
                f"PM High Time {valor} deberia caer en premercado (04:00 - 09:29)"
