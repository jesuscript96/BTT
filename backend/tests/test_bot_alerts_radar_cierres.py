"""`cierres_de_ayer()`: contra qué precio se mide todo gap del bot.

POR QUE IMPORTA TANTO ESTO. Si el cierre de ayer está mal, los gaps salen mal y
**no hay ningún error en ninguna parte**: el bot da alertas que no tocan y se
calla las que sí. Pasó el 9-sep-2026 (ver `btt-bot-tres-fallos-9-sep`).

Ni una llamada de red: se sustituye `httpx.Client` por un doble que devuelve lo
que cada prueba quiera. También se anula el calendario oficial, para que las
fechas dependan solo de las reglas y no de lo que Massive conteste hoy.
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.services import bot_alerts_calendario as cal
from app.services import bot_alerts_radar as mod

NY = ZoneInfo("America/New_York")

# Una sesión completa ronda las 12.500 filas; el radar exige 8.000 para
# aceptarla. Los dobles generan tantas filas como haga falta.
COMPLETA = 12_500
MEDIA_SESION = 11_600
INCOMPLETA = 4_000


def _filas(n, precio=10.0):
    return [{"T": f"TK{i}", "c": precio + i * 0.01} for i in range(n)]


class _ClienteFalso:
    """Devuelve, para cada fecha, las filas que diga `por_dia`."""

    def __init__(self, por_dia):
        self.por_dia = por_dia
        self.pedidos = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, params=None):
        dia = url.rsplit("/", 1)[-1]
        self.pedidos.append(dia)
        import httpx
        return httpx.Response(
            200, json={"results": self.por_dia.get(dia, [])},
            request=httpx.Request("GET", url))


@pytest.fixture
def radar(monkeypatch):
    """Un Radar sin red y con el calendario resuelto solo por reglas."""
    monkeypatch.setattr(mod, "clave_bot", lambda: "PRUEBA")
    monkeypatch.setattr(mod, "_ssl_ctx", lambda: False)
    monkeypatch.setattr(cal, "_de_massive", lambda: {})
    monkeypatch.setattr(cal, "_refrescar_al_fondo", lambda dia: None)
    monkeypatch.setattr(cal, "_cache", {})
    monkeypatch.setattr(cal, "_extra", {})
    return mod.Radar()


def _con(monkeypatch, por_dia, hoy):
    """Engancha el doble y congela «hoy» en hora de Nueva York."""
    falso = _ClienteFalso(por_dia)
    monkeypatch.setattr(mod.httpx, "Client", lambda **kw: falso)

    class _FechaFija(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(hoy.year, hoy.month, hoy.day, 6, 0, tzinfo=NY)

    monkeypatch.setattr(mod, "datetime", _FechaFija)
    return falso


def test_pide_la_ultima_sesion_saltando_finde_y_festivo(radar, monkeypatch):
    """El 8-sep-2026 era martes y el lunes 7 fue Labor Day: la sesión anterior
    es el VIERNES 4. Antes se tanteaba día a día gastando una llamada en cada
    uno; ahora se va directo."""
    falso = _con(monkeypatch, {"2026-09-04": _filas(COMPLETA)}, date(2026, 9, 8))
    out = radar.cierres_de_ayer()
    assert falso.pedidos == ["2026-09-04"]      # una sola llamada, la buena
    assert radar.dia_de_los_cierres == "2026-09-04"
    assert len(out) == COMPLETA


def test_una_media_sesion_vale_como_cierre_de_ayer(radar, monkeypatch):
    """Es el cierre oficial, solo que a las 13:00. El 26-dic-2025 fue viernes,
    el 25 Navidad y el 24 media sesión: el cierre bueno es el del 24. Medido de
    verdad: Nochebuena de 2025 trae 11.628 filas, contra ~12.500 de un día
    entero, así que pasa el mínimo de sobra."""
    falso = _con(monkeypatch, {"2025-12-24": _filas(MEDIA_SESION)}, date(2025, 12, 26))
    out = radar.cierres_de_ayer()
    assert falso.pedidos == ["2025-12-24"]
    assert radar.dia_de_los_cierres == "2025-12-24"
    assert len(out) == MEDIA_SESION
    assert radar.ultimo_error is None


def test_una_sesion_a_medias_se_rechaza_y_se_retrocede(radar, monkeypatch):
    """`aggs/grouped` responde TAMBIÉN con la sesión en curso, y entonces la «c»
    no es el cierre sino el precio del instante. El 9-sep-2026 a las 11:53 de
    Nueva York devolvía 11.149 filas con YQ a 4,20. Si se colara, los gaps
    saldrían contra un precio intradía y nadie se enteraría."""
    falso = _con(monkeypatch, {
        "2026-09-08": _filas(INCOMPLETA),        # a medias: no vale
        "2026-09-04": _filas(COMPLETA),
    }, date(2026, 9, 9))
    out = radar.cierres_de_ayer()
    assert falso.pedidos == ["2026-09-08", "2026-09-04"]
    assert radar.dia_de_los_cierres == "2026-09-04"
    assert len(out) == COMPLETA


def test_si_el_dia_usado_no_es_la_ultima_sesion_lo_dice(radar, monkeypatch):
    """El caso que preocupaba a Jaume: encender de madrugada, que la sesión de
    ayer no esté publicada todavía y calcular los gaps contra una vieja."""
    _con(monkeypatch, {
        "2026-09-08": [],                        # aún no publicada
        "2026-09-04": _filas(COMPLETA),
    }, date(2026, 9, 9))
    radar.cierres_de_ayer()
    assert radar.dia_de_los_cierres == "2026-09-04"
    assert radar.ultimo_error is not None
    assert "2026-09-08" in radar.ultimo_error


def test_un_puente_NO_dispara_el_aviso(radar, monkeypatch):
    """Antes el aviso saltaba por número de días: con Labor Day el salto era de
    4 y se pintaba un error rojo sin que pasara nada. Ahora se compara con la
    sesión que TOCABA."""
    _con(monkeypatch, {"2026-09-04": _filas(COMPLETA)}, date(2026, 9, 8))
    radar.cierres_de_ayer()
    assert radar.ultimo_error is None


def test_un_error_viejo_no_se_cuela_como_si_fuera_de_los_cierres(radar, monkeypatch):
    """`ultimo_error` lo comparten el universo y esto, y el bot lo imprime como
    «OJO con los cierres» justo después de esta llamada. Sin limpiarlo, un aviso
    del universo salía etiquetado como problema de los cierres."""
    radar.ultimo_error = "universo corto: 1.457 acciones (se esperan ~5.700)"
    _con(monkeypatch, {"2026-09-04": _filas(COMPLETA)}, date(2026, 9, 8))
    radar.cierres_de_ayer()
    assert radar.ultimo_error is None


def test_sin_ninguna_sesion_completa_se_rinde_avisando(radar, monkeypatch):
    _con(monkeypatch, {}, date(2026, 9, 8))
    assert radar.cierres_de_ayer() == {}
    assert radar.ultimo_error is not None
    assert "ninguna sesion completa" in radar.ultimo_error


def test_el_ticker_es_T_y_el_cierre_es_c(radar, monkeypatch):
    """En `grouped` los campos se llaman distinto que en el snapshot. Leerlos
    mal devolvería un diccionario vacío sin un solo error."""
    _con(monkeypatch, {"2026-09-04": _filas(COMPLETA)}, date(2026, 9, 8))
    out = radar.cierres_de_ayer()
    assert out["TK0"] == pytest.approx(10.0)
    assert out["TK1"] == pytest.approx(10.01)


def test_los_precios_a_cero_o_sin_ticker_se_caen(radar, monkeypatch):
    filas = _filas(COMPLETA) + [
        {"T": "MALO", "c": 0.0},
        {"T": "", "c": 5.0},
        {"c": 7.0},
    ]
    _con(monkeypatch, {"2026-09-04": filas}, date(2026, 9, 8))
    out = radar.cierres_de_ayer()
    assert "MALO" not in out
    assert "" not in out
    assert len(out) == COMPLETA


def test_sin_clave_no_se_pide_nada(radar, monkeypatch):
    monkeypatch.setattr(mod, "clave_bot", lambda: "")
    assert radar.cierres_de_ayer() == {}
