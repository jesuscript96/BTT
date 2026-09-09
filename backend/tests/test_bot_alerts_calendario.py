"""El calendario del mercado: festivos de NYSE, medias sesiones y franjas.

TODO SE COMPRUEBA CONTRA LAS REGLAS, SIN RED. `_de_massive()` se anula en cada
prueba: el calendario tiene que ser correcto aunque la API no conteste, que es
justo la razon de que las reglas existan.

Las fechas de festivo y media sesion de 2025 y 2026 estan cotejadas una a una
contra los datos reales del mercado (`aggs/grouped`): los dias cerrados
devuelven 0 filas y las medias sesiones ~11.600.
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.services import bot_alerts_calendario as cal

NY = ZoneInfo("America/New_York")
ES = ZoneInfo("Europe/Madrid")

# La de verdad, guardada antes de que el fixture la sustituya por un doble.
_DE_MASSIVE_REAL = cal._de_massive
_REFRESCO_REAL = cal._refrescar_al_fondo


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    """Ni una llamada a Massive, y la cache limpia entre pruebas.

    El refresco se hace SIN hilo aqui: en produccion va al fondo para no
    congelar el bot, pero en las pruebas hace falta que sea determinista.
    """
    def sincrono():
        nuevos = cal._de_massive()
        if nuevos:
            cal._extra.update(nuevos)
            cal._cache.clear()

    monkeypatch.setattr(cal, "_de_massive", lambda: {})
    monkeypatch.setattr(cal, "_refrescar_al_fondo", sincrono)
    monkeypatch.setattr(cal, "_cache", {})
    monkeypatch.setattr(cal, "_extra", {})
    monkeypatch.setattr(cal, "_pedido_el", None)


# ── festivos ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("dia,nombre", [
    (date(2025, 1, 1), "Anyo Nuevo"),
    (date(2025, 1, 20), "Martin Luther King"),
    (date(2025, 2, 17), "Washington"),
    (date(2025, 4, 18), "Viernes Santo"),
    (date(2025, 5, 26), "Memorial Day"),
    (date(2025, 6, 19), "Juneteenth"),
    (date(2025, 7, 4), "4 de Julio"),
    (date(2025, 11, 27), "Accion de Gracias"),
    (date(2025, 12, 25), "Navidad"),
    (date(2026, 4, 3), "Viernes Santo"),
    (date(2026, 9, 7), "Labor Day"),
])
def test_festivos_conocidos(dia, nombre):
    assert cal.festivo(dia) == nombre
    assert cal.hay_sesion(dia) is False


def test_dias_normales_no_son_festivos():
    for dia in (date(2026, 9, 8), date(2026, 1, 2), date(2026, 7, 6)):
        assert cal.festivo(dia) is None
        assert cal.hay_sesion(dia) is True


def test_el_fin_de_semana_no_es_festivo():
    """Son cosas distintas: en el log conviene poder distinguirlas."""
    sabado = date(2026, 9, 5)
    assert cal.festivo(sabado) is None
    assert cal.hay_sesion(sabado) is False


# ── traslados de fin de semana ───────────────────────────────────────────
def test_cuatro_de_julio_en_sabado_se_traslada_al_viernes():
    """En 2026 el 4 cae en sabado, asi que cierra el viernes 3. Comprobado:
    `aggs/grouped` del 3-jul-2026 devuelve 0 filas."""
    assert cal.festivo(date(2026, 7, 3)) == "4 de Julio"
    assert cal.festivo(date(2026, 7, 4)) is None      # sabado, ni se pregunta
    # y por lo mismo NO es media sesion: manda el festivo entero
    assert cal.media_sesion(date(2026, 7, 3)) is None


def test_navidad_en_sabado_deja_el_24_cerrado_no_a_medias():
    """2027: Navidad cae en sabado y el festivo se va al viernes 24. Ese dia
    NO es media sesion aunque sea Nochebuena — el mercado no abre."""
    assert cal.festivo(date(2027, 12, 24)) == "Navidad"
    assert cal.media_sesion(date(2027, 12, 24)) is None


def test_anyo_nuevo_en_domingo_se_traslada_al_lunes():
    assert date(2023, 1, 1).weekday() == 6            # domingo
    assert cal.festivo(date(2023, 1, 2)) == "Anyo Nuevo"


def test_anyo_nuevo_en_sabado_NO_cierra_el_31_de_diciembre():
    """La excepcion de NYSE: el festivo se pasa al viernes anterior salvo que
    ese viernes sea el ultimo dia de negociacion del anyo.

    Y es justo el caso que importa, porque ese 31 es el cierre contra el que se
    miden los gaps del primer dia de enero. Comprobado con datos reales: el
    31-dic-2021 trae 11.151 cierres y el 31-dic-2010 otros 7.401."""
    assert date(2022, 1, 1).weekday() == 5            # sabado
    assert cal.festivo(date(2021, 12, 31)) is None
    assert cal.hay_sesion(date(2021, 12, 31)) is True
    assert cal.ultima_sesion(date(2022, 1, 3)) == date(2021, 12, 31)

    assert date(2011, 1, 1).weekday() == 5
    assert cal.festivo(date(2010, 12, 31)) is None


def test_juneteenth_no_existe_antes_de_2022():
    """Marcarlo antes descuadraria cualquier cotejo con el lago: el 19-jun-2019
    hubo sesion."""
    assert cal.festivo(date(2019, 6, 19)) is None
    assert cal.festivo(date(2022, 6, 20)) == "Juneteenth"   # 19 en domingo


# ── medias sesiones ──────────────────────────────────────────────────────
@pytest.mark.parametrize("dia,motivo", [
    (date(2025, 7, 3), "vispera del 4 de Julio"),
    (date(2025, 11, 28), "viernes de Accion de Gracias"),
    (date(2025, 12, 24), "Nochebuena"),
    (date(2026, 11, 27), "viernes de Accion de Gracias"),
    (date(2026, 12, 24), "Nochebuena"),
])
def test_medias_sesiones(dia, motivo):
    assert cal.media_sesion(dia) == motivo
    assert cal.hay_sesion(dia) is True      # hay mercado, solo que mas corto


def test_la_vispera_del_4_no_se_acorta_si_el_4_cae_en_fin_de_semana():
    """2027: el 4 es domingo, el festivo se va al lunes 5 y el viernes 2 es un
    dia normal y entero."""
    assert cal.media_sesion(date(2027, 7, 2)) is None
    assert cal.festivo(date(2027, 7, 5)) == "4 de Julio"


# ── la sesion anterior ───────────────────────────────────────────────────
def test_ultima_sesion_salta_el_fin_de_semana():
    assert cal.ultima_sesion(date(2026, 9, 8)) == date(2026, 9, 4)   # lunes 7 = Labor Day


def test_ultima_sesion_salta_navidad_y_el_fin_de_semana():
    """26-dic-2025 fue viernes; el 25 Navidad. La sesion anterior es el 24, que
    fue media sesion — y una media sesion SI vale como cierre de ayer."""
    assert cal.ultima_sesion(date(2025, 12, 26)) == date(2025, 12, 24)


def test_ultima_sesion_con_incluir_hoy():
    assert cal.ultima_sesion(date(2026, 9, 8), incluir_hoy=True) == date(2026, 9, 8)
    assert cal.ultima_sesion(date(2026, 9, 7), incluir_hoy=True) == date(2026, 9, 4)


# ── las franjas ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("hora,minuto,esperado", [
    (3, 30, "cerrado"),
    (4, 0, "premercado"),
    (9, 29, "premercado"),
    (9, 30, "RTH"),
    (15, 59, "RTH"),
    (16, 0, "postmercado"),
    (19, 59, "postmercado"),
    (20, 0, "cerrado"),
])
def test_franjas_de_un_dia_normal(hora, minuto, esperado):
    ahora = datetime(2026, 9, 8, hora, minuto, tzinfo=NY)   # martes normal
    assert cal.franja_de_mercado(ahora) == esperado


def test_franja_en_festivo_lo_dice_con_su_nombre():
    """Antes decia «RTH» un jueves de Accion de Gracias y el bot se quedaba
    esperando velas que no iban a llegar."""
    ahora = datetime(2026, 11, 26, 11, 0, tzinfo=NY)
    assert cal.franja_de_mercado(ahora) == "festivo: Accion de Gracias"


def test_franja_en_fin_de_semana():
    assert cal.franja_de_mercado(datetime(2026, 9, 5, 11, 0, tzinfo=NY)) == "fin de semana"


def test_media_sesion_cierra_a_las_trece():
    """El viernes de Accion de Gracias RTH acaba a las 13:00 y el postmercado a
    las 17:00. Sin esto, a las 14:00 el bot diria «RTH» y el silencio pareceria
    una averia."""
    dia = (2026, 11, 27)
    assert cal.franja_de_mercado(datetime(*dia, 12, 59, tzinfo=NY)) == "RTH (media sesion)"
    assert cal.franja_de_mercado(datetime(*dia, 13, 0, tzinfo=NY)) == "postmercado (media sesion)"
    assert cal.franja_de_mercado(datetime(*dia, 16, 59, tzinfo=NY)) == "postmercado (media sesion)"
    assert cal.franja_de_mercado(datetime(*dia, 17, 0, tzinfo=NY)) == "cerrado (media sesion)"
    assert cal.franja_de_mercado(datetime(*dia, 8, 0, tzinfo=NY)) == "premercado (media sesion)"


def test_sin_zona_horaria_se_asume_nueva_york():
    assert cal.franja_de_mercado(datetime(2026, 9, 8, 10, 0)) == "RTH"


# ── horario de verano ────────────────────────────────────────────────────
@pytest.mark.parametrize("dia", [
    date(2026, 3, 6),    # invierno en los dos
    date(2026, 3, 9),    # EEUU ya cambio, Espanya no
    date(2026, 3, 27),   # sigue el desfase
    date(2026, 3, 30),   # verano en los dos
    date(2026, 7, 15),
    date(2026, 10, 23),
    date(2026, 10, 26),  # Espanya ya volvio, EEUU no
    date(2026, 11, 2),   # invierno en los dos
    date(2026, 12, 15),
])
def test_la_apertura_son_las_0930_de_nueva_york_todo_el_anyo(dia):
    """Lo unico que de verdad importa del horario de verano: contando en hora de
    Nueva York, la apertura no se mueve nunca. `ZoneInfo` ya resuelve el cambio
    de hora solo, a los dos lados y en dias distintos."""
    assert cal.franja_de_mercado(datetime(dia.year, dia.month, dia.day, 9, 30, tzinfo=NY)).startswith("RTH")
    assert cal.franja_de_mercado(datetime(dia.year, dia.month, dia.day, 9, 29, tzinfo=NY)).startswith("premercado")


@pytest.mark.parametrize("dia,diferencia", [
    (date(2026, 3, 6), 6),
    (date(2026, 3, 9), 5),     # EEUU cambio el 8, Espanya el 29
    (date(2026, 3, 27), 5),
    (date(2026, 3, 30), 6),
    (date(2026, 10, 23), 6),
    (date(2026, 10, 26), 5),   # Espanya volvio el 25, EEUU el 1-nov
    (date(2026, 10, 30), 5),
    (date(2026, 11, 2), 6),
])
def test_el_desfase_con_espanya_es_de_cinco_horas_tres_semanas_al_anyo(dia, diferencia):
    """Los cambios de hora no caen el mismo dia a los dos lados, asi que hay dos
    ventanas al anyo en que el mercado abre a las 14:30 de Espanya y no a las
    15:30. Al bot no le afecta —cuenta en hora de Nueva York— pero a quien opera
    desde aqui si, y por eso queda escrito."""
    apertura = datetime(dia.year, dia.month, dia.day, 9, 30, tzinfo=NY)
    aqui = apertura.astimezone(ES)
    assert int((aqui.utcoffset() - apertura.utcoffset()).total_seconds() // 3600) == diferencia
    assert aqui.hour == (15 if diferencia == 6 else 14)
    assert aqui.minute == 30


# ── la lista oficial manda sobre las reglas ──────────────────────────────
def test_massive_puede_anyadir_un_cierre_que_ninguna_regla_predice(monkeypatch):
    """Un huracan, un dia de luto. Las reglas no pueden saberlo; la lista
    oficial si, y por eso se superpone."""
    imprevisto = date(2026, 10, 29)
    assert cal.festivo(imprevisto) is None
    monkeypatch.setattr(cal, "_de_massive", lambda: {imprevisto: ("cerrado", "Huracan")})
    monkeypatch.setattr(cal, "_pedido_el", None)
    monkeypatch.setattr(cal, "_cache", {})
    assert cal.festivo(imprevisto) == "Huracan"
    assert cal.hay_sesion(imprevisto) is False


def test_si_massive_falla_se_sigue_con_las_reglas(monkeypatch):
    """Un calendario que tumba el bot por un timeout seria peor que no tenerlo,
    asi que `_de_massive` se traga cualquier fallo y devuelve {}."""
    import httpx

    def revienta(*a, **kw):
        raise httpx.ConnectError("sin red")

    monkeypatch.setattr(httpx, "get", revienta)
    assert _DE_MASSIVE_REAL() == {}

    # y el calendario sigue funcionando con las reglas
    monkeypatch.setattr(cal, "_de_massive", _DE_MASSIVE_REAL)
    monkeypatch.setattr(cal, "_pedido_el", None)
    monkeypatch.setattr(cal, "_cache", {})
    assert cal.festivo(date(2026, 9, 7)) == "Labor Day"
    assert cal.media_sesion(date(2026, 11, 27)) == "viernes de Accion de Gracias"


def test_el_refresco_diario_no_congela_a_quien_pregunta(monkeypatch):
    """`franja_de_mercado()` se llama en cada latido, y ese latido se compone
    dentro del bucle de eventos del bot. Si la peticion a Massive se hiciera
    ahi, el proceso entero se quedaria parado hasta 20 segundos una vez al dia
    —feed incluido— y nadie lo relacionaria con el calendario."""
    import threading
    import time

    arrancado = threading.Event()
    suelta = threading.Event()

    def lenta():
        arrancado.set()
        suelta.wait(5)
        return {}

    monkeypatch.setattr(cal, "_de_massive", lenta)
    monkeypatch.setattr(cal, "_refrescar_al_fondo", _REFRESCO_REAL)
    monkeypatch.setattr(cal, "_pedido_el", None)
    monkeypatch.setattr(cal, "_cache", {})

    t0 = time.monotonic()
    assert cal.franja_de_mercado(datetime(2026, 9, 8, 10, 0, tzinfo=NY)) == "RTH"
    tardanza = time.monotonic() - t0
    suelta.set()

    assert arrancado.wait(2), "el refresco ni siquiera arranco"
    assert tardanza < 0.5, f"la respuesta tardo {tardanza:.1f}s: se esta bloqueando"
