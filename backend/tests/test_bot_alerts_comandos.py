"""Los comandos de Telegram: la primera vez que el bot ESCUCHA algo de fuera.

Hasta el 2026-09-03 el bot solo emitía, y eso lo hacía inofensivo: nadie podía
hacerle nada desde fuera. Al abrir esa puerta, lo que hay que fijar con tests no
es tanto que el cálculo salga bien —eso es aritmética— sino que **un mensaje
raro no pueda tumbar el bucle que procesa velas**. Una excepción ahí cuesta una
vela, y una vela puede ser una entrada.
"""
from app.services.bot_alerts_comandos import (
    AYUDA, NEGATIVA, POSITIVA, responder, veredicto_locates,
)

PRECIOS = {"MIMI": 0.8422, "GELS": 1.0498}
precio_de = PRECIOS.get


# ── El cálculo ───────────────────────────────────────────────────────────

def test_compensa_cuando_el_ev_supera_al_fade():
    # fade = 0,010 / 0,8422 × 100 = 1,19 % < EV 2,4 %
    r = veredicto_locates("MIMI", 0.8422, 0.010, 2.4)
    assert POSITIVA in r
    assert "1.19" in r          # el fade se enseña, no solo el veredicto


def test_no_compensa_con_el_locate_caro():
    r = veredicto_locates("MIMI", 0.8422, 0.025, 2.4)
    assert NEGATIVA in r


def test_el_tamano_no_cambia_el_veredicto():
    """Ganancia y coste escalan los dos con las acciones: se cancela."""
    for n in (1_000, 10_000, 100_000):
        assert POSITIVA in veredicto_locates("MIMI", 0.8422, 0.010, 2.4, n)


def test_los_paquetes_de_100_encarecen_la_posicion_pequena():
    """150 acciones pagan 2 paquetes: el coste real por acción sube un 33 %."""
    r = veredicto_locates("MIMI", 0.8422, 0.010, 2.4, 150)
    assert "2 paquetes" in r     # se dice, no se esconde


def test_sin_precio_no_se_inventa_un_veredicto():
    """Un ticker que el radar no vigila no tiene precio, y punto."""
    r = veredicto_locates("ZZZZ", None, 0.010, 2.4)
    assert POSITIVA not in r and NEGATIVA not in r


# ── El despacho, que es lo que toca el bucle del bot ─────────────────────

def test_un_mensaje_normal_no_es_un_comando():
    assert responder("hola, que tal", precio_de) is None
    assert responder("", precio_de) is None


def test_comando_desconocido_se_calla():
    """Callarse es mejor que dar la lata en un grupo con otra persona."""
    assert responder("/loquesea", precio_de) is None


def test_el_comando_admite_el_sufijo_del_bot():
    """En un grupo, Telegram manda `/evf@MiBot`."""
    r = responder("/evf@Alertas_btt_bot MIMI 0.010 2.4", precio_de)
    assert r is not None and POSITIVA in r


def test_faltan_argumentos_devuelve_la_ayuda():
    assert responder("/evf", precio_de) == AYUDA
    r = responder("/evf MIMI", precio_de)
    assert r is not None and "Uso:" in r


def test_admite_coma_decimal():
    """Se teclea en el móvil y en español la coma sale sola."""
    r = responder("/evf MIMI 0,010 2,4", precio_de)
    assert r is not None and POSITIVA in r


def test_una_basura_no_revienta():
    """LO IMPORTANTE. Nada de lo que llegue puede lanzar: una excepción aquí
    costaría la vela que se estuviera procesando."""
    for basura in ("/evf MIMI abc def", "/evf " + "x" * 5000, "/evf MIMI 0.01 2.4 nope",
                   "/", "//", "/evf\n\n/evf", "/EVF ../../etc/passwd 1 1"):
        responder(basura, precio_de)      # no debe lanzar


def test_el_veredicto_siempre_con_las_mismas_palabras():
    """Jaume lo pidió así: la broma rota, el veredicto no.

    Es lo que se lee de un vistazo en el móvil; si cambiara de forma habría que
    leerse la frase entera para saber de qué lado cae.
    """
    vistos = {veredicto_locates("MIMI", 0.8422, 0.010, 2.4).split("\n")[4]
              for _ in range(40)}
    assert vistos == {f"<b>{POSITIVA}</b>"}
