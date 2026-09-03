"""La ventana de la prealerta: se mira CADA segundo del 50 al 59, no una vez.

Por que hay test. Mirar una sola vez, en el segundo 50, dejaba escapar las
senyales que se completan despues, y esas llegan al cierre de la vela con margen
CERO — justo cuando el backtest entra. Medido sobre tick data (12 dias, 14
entradas): del 86 % al 100 % de captura, con el margen bajando solo de 10 a
9,4 s de media.

Es una vuelta atras facil de hacer sin querer (basta con marcar `evaluada`
dentro de `aplicar`), y no la cazaria nadie: el bot seguiria avisando, solo que
menos veces.
"""
from app.services.bot_alerts_prealertas import (
    SEGUNDO_DECISION, SEGUNDO_LIMITE, ConstructorParcial,
)

# 09:00:00 ET de un dia cualquiera, en epoch de milisegundos y al minuto justo.
MINUTO = 1756645200000


def _ev(segundo: int, close: float = 1.0, av: float = 1000.0) -> dict:
    return {
        "sym": "TEST", "s": MINUTO + segundo * 1000,
        "o": 1.0, "h": close, "l": 1.0, "c": close, "v": 10, "av": av,
    }


def test_mira_cada_segundo_de_la_ventana():
    """Diez oportunidades por vela, no una."""
    c = ConstructorParcial()
    mira = [s for s in range(60) if c.aplicar(_ev(s)) is not None]
    assert mira == list(range(SEGUNDO_DECISION, SEGUNDO_LIMITE + 1))


def test_no_mira_antes_de_tiempo():
    """Antes del 50 la vela esta demasiado verde: la fiabilidad cae."""
    c = ConstructorParcial()
    assert all(c.aplicar(_ev(s)) is None for s in range(SEGUNDO_DECISION))


def test_una_vez_avisado_el_minuto_se_calla():
    """`evaluada` la marca quien avisa, y a partir de ahi ese minuto no vuelve.

    Sin esto una senyal que se cumple en el 52 se repetiria en el 53, 54… hasta
    el 59: ocho avisos de la misma entrada, y ocho mensajes de Telegram.
    """
    c = ConstructorParcial()
    listo = c.aplicar(_ev(SEGUNDO_DECISION))
    assert listo is not None
    _, vela, _, segundo = listo
    assert segundo == SEGUNDO_DECISION
    vela.evaluada = True          # esto es lo que hace el bot al publicar
    assert all(c.aplicar(_ev(s)) is None
               for s in range(SEGUNDO_DECISION + 1, 60))


def test_el_minuto_siguiente_empieza_de_cero():
    """Callarse dura un minuto, no el dia: la vela nueva vuelve a mirarse."""
    c = ConstructorParcial()
    listo = c.aplicar(_ev(SEGUNDO_DECISION))
    assert listo is not None
    listo[1].evaluada = True

    siguiente = dict(_ev(SEGUNDO_DECISION))
    siguiente["s"] = MINUTO + 60000 + SEGUNDO_DECISION * 1000
    assert c.aplicar(siguiente) is not None


def test_el_volumen_sale_del_acumulado_del_dia():
    """`av` menos el que habia al empezar, NO la suma de los `v` por segundo.

    Sumar los agregados por segundo deja fuera operaciones (medido: hasta un
    4,6 % menos) y 1B decide con dollar volume acumulado.
    """
    c = ConstructorParcial()
    c.aplicar(_ev(0, av=1000.0))          # empieza el minuto con av=1000, v=10
    listo = c.aplicar(_ev(SEGUNDO_DECISION, av=1500.0))
    assert listo is not None
    # av_inicio = 1000 - 10 = 990; volumen del minuto = 1500 - 990
    assert listo[1].volumen == 510.0


def test_sin_av_el_volumen_es_cero_no_una_suma_aproximada():
    """Un volumen corto haria cumplir el dollar volume tarde: peor que callarse."""
    c = ConstructorParcial()
    ev = _ev(SEGUNDO_DECISION)
    del ev["av"]
    listo = c.aplicar(ev)
    assert listo is not None
    assert listo[1].volumen == 0.0


def test_no_se_prealerta_una_vela_que_ya_cerro():
    """EL BUG DEL 2026-09-03: la prealerta que nace huérfana.

    Los agregados por segundo tardan ~3 s, así que el tick del segundo 59 se
    procesa DESPUÉS de que su vela haya cerrado. Sin esta comprobación nacía una
    prealerta de una vela muerta: nadie la confirmaba ni la descartaba (el
    bloque que lo hace ya había pasado), se quedaba en ámbar para siempre en la
    página, y encima no daba ni un segundo de margen. Visto en vivo con MIMI.
    """
    from datetime import datetime
    from app.services.bot_alerts_prealertas import ET

    c = ConstructorParcial()
    inicio = datetime.fromtimestamp(MINUTO / 1000, tz=ET)

    c.aplicar(_ev(30))                    # la vela se va formando
    c.marcar_cerrada("TEST", inicio)      # llega su `AM`: el minuto se cierra
    assert c.aplicar(_ev(59)) is None, "el tick tardío no puede prealertar"


def test_cerrar_un_minuto_no_calla_los_siguientes():
    """Callarse dura esa vela, no el resto del día."""
    from datetime import datetime
    from app.services.bot_alerts_prealertas import ET

    c = ConstructorParcial()
    c.marcar_cerrada("TEST", datetime.fromtimestamp(MINUTO / 1000, tz=ET))

    siguiente = dict(_ev(SEGUNDO_DECISION))
    siguiente["s"] = MINUTO + 60000 + SEGUNDO_DECISION * 1000
    assert c.aplicar(siguiente) is not None


def test_olvidar_un_ticker_borra_tambien_su_marca():
    """Si se suelta y vuelve, no puede arrastrar el minuto cerrado de antes."""
    from datetime import datetime
    from app.services.bot_alerts_prealertas import ET

    c = ConstructorParcial()
    c.marcar_cerrada("TEST", datetime.fromtimestamp(MINUTO / 1000, tz=ET))
    c.olvidar("TEST")
    assert c.aplicar(_ev(SEGUNDO_DECISION)) is not None
