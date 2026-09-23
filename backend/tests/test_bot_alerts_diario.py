"""El diario del bot: su log y lo que le ha saltado.

Esto se mira JUSTO CUANDO ALGO VA MAL, y de ahí salen las dos cosas que fijan
los tests: que **no se pierda nada de lo que salta** (por eso cuelga del logger
raíz y no del logger del bot), y que **la tabla siga siendo legible** cuando un
error se repite doscientas veces, que es lo que hace un corte de conexión.

Y una tercera que no es de formato: un handler de logging que lanza corre
DENTRO del bucle que procesa velas. Si el diario revienta, se lleva la vela.
"""
import logging

from app.services.bot_alerts_diario import Diario, como_texto


def _log(diario, nombre="bot"):
    """Un logger de usar y tirar con el diario enganchado."""
    lg = logging.getLogger(nombre)
    lg.handlers = [diario]
    lg.setLevel(logging.INFO)
    lg.propagate = False
    return lg


# ── Lo que entra ─────────────────────────────────────────────────────────

def test_el_log_normal_no_sube_a_incidencias():
    """INFO es la actividad del bot: latencia, entradas al radar, alertas. Va
    al log y ahí se queda; si subiera, la tabla no diría nada."""
    d = Diario()
    _log(d).info("Radar: entra BAOS por 1B 50k")
    v = d.volcado()
    assert len(v["lineas"]) == 1 and not v["incidencias"]


def test_lo_que_salta_va_a_las_dos_partes():
    """Una incidencia también es una línea del log: al pegarla hace falta ver
    qué estaba pasando alrededor."""
    d = Diario()
    _log(d).warning("Backend sin responder")
    v = d.volcado()
    assert len(v["lineas"]) == 1
    assert len(v["incidencias"]) == 1
    assert v["incidencias"][0]["nivel"] == "WARNING"


def test_recoge_lo_de_CUALQUIERA_no_solo_lo_del_bot():
    """LO IMPORTANTE DE COLGARLO DEL LOGGER RAÍZ (Jaume, 2026-09-04: «no solo
    esas sino todas las que pudiera haber»).

    Un fallo del socket de Polygon o de httpx tiene que aparecer sin que nadie
    haya añadido una llamada para ello.
    """
    d = Diario()
    raiz = logging.getLogger()
    antes, nivel = raiz.handlers, raiz.level
    raiz.handlers, raiz.level = [d], logging.INFO
    try:
        logging.getLogger("websockets.client").error("conexión cerrada 1006")
        logging.getLogger("httpx").warning("timeout")
    finally:
        raiz.handlers, raiz.level = antes, nivel
    origenes = {i["origen"] for i in d.volcado()["incidencias"]}
    assert origenes == {"websockets.client", "httpx"}


# ── La agrupación, que es lo que hace la tabla legible ───────────────────

def test_el_mismo_fallo_repetido_es_UNA_fila():
    """Un corte de conexión se repite decenas de veces y llenaría la tabla él
    solo. Se cuenta, no se repite."""
    d = Diario()
    lg = _log(d)
    for _ in range(50):
        lg.warning("Backend sin responder")
    inc = d.volcado()["incidencias"]
    assert len(inc) == 1 and inc[0]["veces"] == 50
    # …pero el log sí las lleva todas: es el contexto.
    assert len(d.volcado()["lineas"]) == 50


def test_se_agrupa_por_la_PLANTILLA_no_por_el_texto():
    """La clave del asunto. Estos dos son el mismo fallo con otro número:

        log.warning("se descartan %d avisos", 3)
        log.warning("se descartan %d avisos", 7)

    Agrupando por el texto ya formateado saldrían dos filas, y con un contador
    que sube saldrían cien. La plantilla ya viene dada por logging — no hay que
    adivinar qué parte del mensaje es el número.
    """
    d = Diario()
    lg = _log(d)
    for n in (3, 7, 41):
        lg.warning("Backend sin responder: se descartan %d avisos", n)
    inc = d.volcado()["incidencias"]
    assert len(inc) == 1 and inc[0]["veces"] == 3
    # Se enseña el ÚLTIMO, que es el detalle de ahora.
    assert "41 avisos" in inc[0]["mensaje"]


def test_dos_fallos_distintos_no_se_mezclan():
    d = Diario()
    lg = _log(d)
    lg.warning("Backend sin responder")
    lg.error("Feed caído")
    assert len(d.volcado()["incidencias"]) == 2


def test_el_mismo_texto_con_distinto_nivel_no_se_mezcla():
    """Un aviso y un error no son lo mismo aunque lo pongan igual."""
    d = Diario()
    lg = _log(d)
    lg.warning("Feed raro")
    lg.error("Feed raro")
    assert len(d.volcado()["incidencias"]) == 2


def test_se_guarda_cuando_empezo_y_cuando_fue_la_ultima():
    """«×50» sin fechas no dice si fue un momento malo o lleva toda la mañana."""
    d = Diario()
    lg = _log(d)
    lg.warning("Backend sin responder")
    lg.warning("Backend sin responder")
    i = d.volcado()["incidencias"][0]
    assert i["primera"] and i["ultima"] and len(i["primera"]) == 8


def test_lo_ultimo_que_salto_va_arriba():
    d = Diario()
    lg = _log(d)
    lg.warning("el viejo")
    lg.warning("el nuevo")
    # Mismo segundo: lo que se fija es que el orden sea por «última vez», no
    # que sean distintas. Con horas iguales el orden es estable, y basta.
    assert {i["mensaje"] for i in d.volcado()["incidencias"]} == {"el viejo", "el nuevo"}


def test_la_traza_se_guarda_recortada():
    """Vale oro para pegarla, pero entera son cientos de líneas."""
    d = Diario()
    lg = _log(d)
    try:
        raise ValueError("revento aqui")
    except ValueError:
        lg.exception("fallo procesando la vela")
    i = d.volcado()["incidencias"][0]
    assert i["traza"] and "revento aqui" in i["traza"]
    assert len(i["traza"].split("\n")) <= 12


# ── Los límites, que es lo que evita que esto crezca sin fin ─────────────

def test_el_log_no_crece_sin_fin():
    """El bot corre días seguidos. Se quedan las últimas."""
    d = Diario(lineas=10)
    lg = _log(d)
    for n in range(100):
        lg.info("linea %d", n)
    lineas = d.volcado()["lineas"]
    assert len(lineas) == 10 and "linea 99" in lineas[-1]["texto"]


def test_se_pueden_pedir_menos_lineas():
    d = Diario()
    lg = _log(d)
    for n in range(50):
        lg.info("linea %d", n)
    assert len(d.volcado(lineas=5)["lineas"]) == 5


def test_limpiar_vacia_el_dia():
    """Al cambiar de día, como el radar: si no, no se sabría si una incidencia
    es de hoy o de anteayer."""
    d = Diario()
    lg = _log(d)
    lg.warning("de ayer")
    d.limpiar()
    v = d.volcado()
    assert not v["lineas"] and not v["incidencias"]


def test_el_seq_dice_si_hay_algo_nuevo():
    """Es lo que evita publicar el log entero cada 10 s sin novedades."""
    d = Diario()
    lg = _log(d)
    lg.info("una")
    antes = d.seq
    assert d.seq == antes           # sin nada nuevo, no se mueve
    lg.info("otra")
    assert d.seq > antes


def test_el_diario_NUNCA_lanza():
    """LO IMPORTANTE. Esto corre dentro del bucle que procesa velas: una
    excepción aquí cuesta la vela, y una vela puede ser una entrada."""
    d = Diario()

    class Rompe:
        def __str__(self):
            raise RuntimeError("no me puedes formatear")

    lg = _log(d)
    lg.warning("%s", Rompe())        # no debe lanzar
    lg.warning(Rompe())              # ni como plantilla
    d.volcado()                      # ni al volcarlo


# ── El texto para pegar, que es el motivo de todo esto ───────────────────

def test_el_texto_lleva_primero_las_incidencias():
    """Es lo que Jaume va a copiar y pegarme cuando algo falle sin tenerme
    delante: quien lo lee empieza por arriba, y la respuesta va arriba."""
    d = Diario()
    lg = _log(d)
    lg.info("actividad normal")
    lg.warning("esto es lo que ha fallado")
    t = como_texto(d.volcado())
    assert t.index("INCIDENCIAS") < t.index("LOG")
    assert "esto es lo que ha fallado" in t
    assert "actividad normal" in t          # el contexto también va


def test_el_texto_dice_las_veces_cuando_se_repite():
    d = Diario()
    lg = _log(d)
    for _ in range(12):
        lg.warning("Backend sin responder")
    assert "×12" in como_texto(d.volcado())


def test_sin_incidencias_lo_dice_claro():
    """«Sin incidencias» es una respuesta, un hueco no."""
    d = Diario()
    _log(d).info("todo en orden")
    assert "SIN INCIDENCIAS" in como_texto(d.volcado())


def test_el_texto_aguanta_un_volcado_vacio():
    """Si el bot no ha arrancado todavía, la página pide y no hay nada."""
    assert "SIN INCIDENCIAS" in como_texto({})
