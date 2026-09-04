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
    # El coste es el de 100 ACCIONES, como en el backtester.
    # fade = (1,00/100) / 0,8422 × 100 = 1,19 % < EV 2,4 %
    r = veredicto_locates("MIMI", 0.8422, 1.00, 2.4)
    assert POSITIVA in r
    assert "1.187" in r         # el fade se enseña, no solo el veredicto


def test_no_se_redondea_el_veredicto_al_filo():
    """CUATRO decimales. Con dos, este caso salía «margen +0,00 pp» y no había
    forma de saber de qué lado caía — en una decisión de comprar o no comprar,
    el signo no se puede perder en el formato (Jaume, 2026-09-03)."""
    justo = veredicto_locates("MIMI", 0.8422, 2.02, 2.4)     # +0,0015 pp
    apenas = veredicto_locates("MIMI", 0.8422, 2.03, 2.4)    # −0,0104 pp
    assert POSITIVA in justo and NEGATIVA in apenas
    # …y el margen se lee, no sale como 0,00 en los dos.
    assert "+0.0015" in justo
    assert "-0.0104" in apenas


def test_no_compensa_con_el_locate_caro():
    r = veredicto_locates("MIMI", 0.8422, 2.50, 2.4)
    assert NEGATIVA in r


def test_el_tamano_no_cambia_el_veredicto():
    """Ganancia y coste escalan los dos con las acciones: se cancela."""
    for n in (1_000, 10_000, 100_000):
        assert POSITIVA in veredicto_locates("MIMI", 0.8422, 1.00, 2.4, n)


def test_los_paquetes_de_100_encarecen_la_posicion_pequena():
    """150 acciones pagan 2 paquetes: el coste real por acción sube un 33 %."""
    r = veredicto_locates("MIMI", 0.8422, 1.00, 2.4, 150)
    assert "2 paquetes" in r     # se dice, no se esconde


def test_sin_precio_no_se_inventa_un_veredicto():
    """Un ticker que el radar no vigila no tiene precio, y punto."""
    r = veredicto_locates("ZZZZ", None, 1.00, 2.4)
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
    r = responder("/evf@Alertas_btt_bot MIMI 1.00 2.4", precio_de)
    assert r is not None and POSITIVA in r


def test_faltan_argumentos_devuelve_la_ayuda():
    assert responder("/evf", precio_de) == AYUDA


def test_sin_ev_dice_donde_ponerlo():
    """Sin EV no hay veredicto posible, y hay que decir dónde se pone."""
    r = responder("/evf MIMI 1.00", precio_de)          # sin EV guardado
    assert r is not None and "cuadro de mandos" in r


def test_sin_coste_pide_los_datos():
    """Con EV guardado pero sin coste, falta la otra mitad."""
    r = responder("/evf MIMI", precio_de, 2.4)
    assert r is not None and "Uso:" in r


def test_el_ev_del_cuadro_de_mandos_se_usa_sin_repetirlo():
    """Es lo que pidió Jaume: `/evf TICKER coste` a secas."""
    r = responder("/evf MIMI 1.00", precio_de, 2.4)
    assert r is not None and POSITIVA in r and "2.4000" in r


def test_el_ev_escrito_pisa_al_guardado():
    """Para probar otro valor sin tocar la configuración."""
    r = responder("/evf MIMI 1.00 5.0", precio_de, 2.4)
    assert r is not None and "5.0000" in r


def test_admite_coma_decimal():
    """Se teclea en el móvil y en español la coma sale sola."""
    r = responder("/evf MIMI 1,00 2,4", precio_de)
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
    # La línea del veredicto se busca por su CONTENIDO, no por su posición: el
    # formato del mensaje cambia y el test no debe romperse por eso.
    def linea_veredicto(t: str) -> str:
        return next(l for l in t.split("\n") if POSITIVA in l or NEGATIVA in l)

    vistos = {linea_veredicto(veredicto_locates("MIMI", 0.8422, 1.00, 2.4))
              for _ in range(40)}
    assert vistos == {f"<b>{POSITIVA}</b>"}


def test_el_coste_es_el_de_100_ACCIONES_como_en_el_backtester():
    """LA UNIDAD, que es fácil de confundir y sale 100 veces mal.

    El backtester pide «$ Locate / 100 acc.» — lo que cuestan 100 acciones. Si
    aquí se pidiera por acción, el mismo número en los dos sitios daría
    resultados cien veces distintos, y el veredicto cambiaría de signo sin que
    nada lo indicara.
    """
    # 1,00 $ por 100 acciones = 0,01 $/acción sobre 0,8422 -> fade 1,19 %
    assert "1.187" in veredicto_locates("MIMI", 0.8422, 1.00, 2.4)
    # El ejemplo del propio backtester: 3 $ el locate.
    r = veredicto_locates("MIMI", 0.8422, 3.00, 2.4)
    assert "3.56" in r and NEGATIVA in r


def test_la_respuesta_dice_de_donde_sale_el_ev():
    """El veredicto depende POR COMPLETO de ese número, así que hay que poder
    ver cuál se ha usado sin abrir la aplicación."""
    del_cuadro = responder("/evf MIMI 1.00", precio_de, 2.4)
    escrito = responder("/evf MIMI 1.00 5.0", precio_de, 2.4)
    assert "del cuadro de mandos" in del_cuadro and "2.4000" in del_cuadro
    assert "el que has escrito" in escrito and "5.0000" in escrito


def test_la_ayuda_explica_la_unidad_del_locate():
    """Es la que se confunde: 3 $ por CADA 100 acciones, no por acción."""
    assert "100 acciones" in AYUDA
    assert "Locate / 100 acc." in AYUDA      # el nombre del campo del backtester
