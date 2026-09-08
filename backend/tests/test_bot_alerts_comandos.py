"""Los comandos de Telegram: la primera vez que el bot ESCUCHA algo de fuera.

Hasta el 2026-09-03 el bot solo emitía, y eso lo hacía inofensivo: nadie podía
hacerle nada desde fuera. Al abrir esa puerta, lo que hay que fijar con tests no
es tanto que el cálculo salga bien —eso es aritmética— sino que **un mensaje
raro no pueda tumbar el bucle que procesa velas**. Una excepción ahí cuesta una
vela, y una vela puede ser una entrada.
"""
from app.services.bot_alerts_comandos import (
    AYUDA, NEGATIVA, POSITIVA, panel_radar, panel_ticker, responder,
    veredicto_locates,
)

PRECIOS = {"MIMI": 0.8422, "GELS": 1.0498}
precio_de = PRECIOS.get


# ── El cálculo ───────────────────────────────────────────────────────────

def test_compensa_cuando_el_ev_supera_al_fade():
    # El coste es el de 100 ACCIONES, como en el backtester.
    # fade = (1,00/100) / 0,8422 × 100 = 1,19 % < EV 2,4 %
    r = veredicto_locates("MIMI", 0.8422, 0.010, 2.4)
    assert POSITIVA in r
    assert "1.187" in r         # el fade se enseña, no solo el veredicto


def test_no_se_redondea_el_veredicto_al_filo():
    """CUATRO decimales. Con dos, este caso salía «margen +0,00 pp» y no había
    forma de saber de qué lado caía — en una decisión de comprar o no comprar,
    el signo no se puede perder en el formato (Jaume, 2026-09-03)."""
    justo = veredicto_locates("MIMI", 0.8422, 0.0202, 2.4)     # +0,0015 pp
    apenas = veredicto_locates("MIMI", 0.8422, 0.0203, 2.4)    # −0,0104 pp
    assert POSITIVA in justo and NEGATIVA in apenas
    # …y el margen se lee, no sale como 0,00 en los dos.
    assert "+0.0015" in justo
    assert "-0.0104" in apenas


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


def test_sin_ev_dice_donde_ponerlo():
    """Sin EV no hay veredicto posible, y hay que decir dónde se pone."""
    r = responder("/evf MIMI 0.010", precio_de)          # sin EV guardado
    assert r is not None and "cuadro de mandos" in r


def test_sin_coste_pide_los_datos():
    """Con EV guardado pero sin coste, falta la otra mitad."""
    r = responder("/evf MIMI", precio_de, 2.4)
    assert r is not None and "Uso:" in r


def test_el_ev_del_cuadro_de_mandos_se_usa_sin_repetirlo():
    """Es lo que pidió Jaume: `/evf TICKER coste` a secas."""
    r = responder("/evf MIMI 0.010", precio_de, 2.4)
    assert r is not None and POSITIVA in r and "2.4000" in r


def test_el_ev_escrito_pisa_al_guardado():
    """Para probar otro valor sin tocar la configuración."""
    r = responder("/evf MIMI 0.010 5.0", precio_de, 2.4)
    assert r is not None and "5.0000" in r


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
    # La línea del veredicto se busca por su CONTENIDO, no por su posición: el
    # formato del mensaje cambia y el test no debe romperse por eso.
    def linea_veredicto(t: str) -> str:
        return next(l for l in t.split("\n") if POSITIVA in l or NEGATIVA in l)

    vistos = {linea_veredicto(veredicto_locates("MIMI", 0.8422, 0.010, 2.4))
              for _ in range(40)}
    assert vistos == {f"<b>{POSITIVA}</b>"}


def test_el_coste_va_POR_ACCION_como_lo_da_el_broker():
    """LA UNIDAD, que es la que se confunde y sale 100 veces mal.

    El bróker enseña el precio POR ACCIÓN, y este comando se usa con el bróker
    delante en el momento de decidir. El campo del backtester pide el del
    PAQUETE de 100 porque allí el dato se rellena una vez y viene de otro sitio:
    un locate de 1 $ el paquete son 0,01 $ la acción.
    """
    # 0,01 $/acción sobre 0,8422 -> fade 1,19 %
    assert "1.187" in veredicto_locates("MIMI", 0.8422, 0.010, 2.4)
    # Tres veces más caro: 0,03 $/acción -> 3,56 %, y deja de compensar.
    r = veredicto_locates("MIMI", 0.8422, 0.030, 2.4)
    assert "3.56" in r and NEGATIVA in r


def test_la_respuesta_dice_de_donde_sale_el_ev():
    """El veredicto depende POR COMPLETO de ese número, así que hay que poder
    ver cuál se ha usado sin abrir la aplicación."""
    del_cuadro = responder("/evf MIMI 0.010", precio_de, 2.4)
    escrito = responder("/evf MIMI 0.010 5.0", precio_de, 2.4)
    assert "del cuadro de mandos" in del_cuadro and "2.4000" in del_cuadro
    assert "el que has escrito" in escrito and "5.0000" in escrito


def test_la_ayuda_explica_la_unidad_del_locate():
    """Es la que se confunde: por ACCIÓN aquí, por paquete en el backtester."""
    assert "POR ACCIÓN" in AYUDA
    # …y avisa de la otra unidad, que es donde está la trampa.
    assert "paquete de 100" in AYUDA


# ── /estado ──────────────────────────────────────────────────────────────
# Aquí no hay aritmética que fijar: lo que se fija es que NO SE INVENTE NADA.
# Un panel que enseña un precio de hace media hora, o que llama «vigilada» a una
# acción que el bot no está evaluando, es peor que no contestar — se decide con
# él delante.

FICHA = {
    "ticker": "BAOS", "precio": 0.3722, "prev_close": 0.2389,
    "pre_high": 0.3722, "pre_volume": 840_000, "day_volume": 1_240_000,
    "visto_hace": 2.4, "estrategias": ["1B 50k"],
    "metricas": {"PM High Gap %": 55.75, "Current Gap %": 48.10,
                 "Open Gap %": None},
}
RADAR = [
    {"ticker": "BAOS", "estrategia": "1B 50k", "metrica": "PM High Gap %",
     "valor": 55.75, "precio": 0.3722, "volumen": 1_240_000, "seguido": True},
    {"ticker": "MIMI", "estrategia": "1B 50k", "metrica": "PM High Gap %",
     "valor": 52.10, "precio": 0.8422, "volumen": 3_400_000, "seguido": True},
]


def _estado(texto, ficha=FICHA, radar=RADAR):
    return responder(texto, precio_de, None,
                     estado_de=lambda _t: ficha, radar=lambda: radar)


def test_la_ficha_lleva_lo_que_se_mira_al_decidir():
    r = panel_ticker(FICHA)
    # «AHORA a», no «a» a secas: el precio es el último tick, no el de la
    # entrada ni el del barrido del radar (Jaume, 2026-09-04).
    assert "BAOS</b> ahora a 0.3722" in r
    assert "+55.75" in r            # el gap que la metió
    assert "+48.10" in r            # y dónde está AHORA, que es otra cosa
    assert "1.2 M" in r             # volumen legible, no 1240000
    assert "1B 50k" in r            # por qué la vigilo


def test_el_gap_de_apertura_no_sale_si_no_ha_abierto():
    """None NO se pinta como 0. «Abrió plano» y «aún no ha abierto» deciden
    distinto, y una fila con una raya invita a leerla como un cero."""
    assert "Gap apertura" not in panel_ticker(FICHA)
    abierta = {**FICHA, "metricas": {**FICHA["metricas"], "Open Gap %": 12.5}}
    assert "Gap apertura" in panel_ticker(abierta) and "+12.50" in panel_ticker(abierta)


def test_sin_datos_no_se_inventa_una_ficha():
    """Mismo criterio que `/evf` sin precio: decirlo, no enseñar algo viejo."""
    r = panel_ticker(None)
    assert "no lo estoy vigilando" in r.lower() and "0.3" not in r


def test_el_ticker_que_no_sigo_no_saca_la_ficha_de_otro():
    r = responder("/estado ZZZZ", precio_de, None,
                  estado_de=lambda _t: None, radar=lambda: RADAR)
    assert r is not None and "BAOS" not in r


def test_el_ultimo_tick_se_dice_pero_no_se_llama_dato_viejo():
    """Un agregado solo llega si HA HABIDO OPERACIONES: 40 s sin tick no es el
    feed caído, es una acción parada — y eso es información, no un fallo."""
    assert "hace 2 s" in panel_ticker(FICHA)
    assert "hace 4 min" in panel_ticker({**FICHA, "visto_hace": 260})


# ── el radar ─────────────────────────────────────────────────────────────

def test_el_radar_lista_lo_vigilado():
    r = panel_radar(RADAR)
    assert "BAOS" in r and "MIMI" in r
    assert "2 vigiladas" in r
    assert "PM High Gap %" in r      # sin esto la columna del % no dice nada


def test_la_lista_es_lo_vigilado_AHORA_y_nada_mas():
    """LO IMPORTANTE DE ESTE PANEL (Jaume, 2026-09-04: «solo quiero que
    aparezca lo del radar en este momento»).

    La que no cabe en el cupo del socket NO se evalúa y NO va a dar avisos, así
    que no puede salir en la lista como si se vigilara — pero tampoco merece
    una tabla aparte: harían falta 25 gappers del 50 % la misma mañana. Una
    línea al pie, y solo si pasa.
    """
    fuera = {**RADAR[1], "ticker": "GELS", "seguido": False}
    r = panel_radar([*RADAR, fuera])
    assert "2 vigiladas" in r            # las de dentro; GELS no cuenta
    assert "GELS" not in r.split("</pre>")[0]     # …ni sale en la tabla
    assert "+1 más" in r and "NO aviso" in r      # pero se avisa en una línea


def test_sin_nada_fuera_de_cupo_no_se_menciona_el_cupo():
    """El caso normal: 2 en el radar y hueco de sobra. Ni una palabra de más."""
    r = panel_radar(RADAR)
    assert "cupo" not in r


def test_sin_la_marca_se_dan_por_seguidas():
    """Un radar que no ponga `seguido` sigue leyéndose igual."""
    sin_marca = [{k: v for k, v in c.items() if k != "seguido"} for c in RADAR]
    r = panel_radar(sin_marca)
    assert "2 vigiladas" in r and "cupo" not in r


def test_se_cuentan_acciones_no_filas():
    """Un ticker en dos estrategias son dos filas y UNA acción."""
    dos_veces = [RADAR[0], {**RADAR[0], "estrategia": "2B", "metrica": "Current Gap %"}]
    assert "1 vigilada" in panel_radar(dos_veces)


def test_radar_vacio_lo_dice():
    r = panel_radar([])
    assert "vacío" in r and "vigilada" not in r


def test_sin_radar_se_explica_por_que():
    """Arrancar con tickers a mano es una opción del bot, no un fallo."""
    assert "a mano" in panel_radar(None)


def test_estado_a_secas_es_el_radar():
    """Se teclea en el móvil: `/estado` sin más es lo que se quiere el 90 %."""
    assert _estado("/estado") == _estado("/estado radar")
    assert "RADAR" in _estado("/estado")


def test_estado_admite_el_sufijo_del_bot_y_las_mayusculas():
    assert "RADAR" in _estado("/estado@Alertas_btt_bot Radar")
    assert "BAOS" in _estado("/Estado baos")


def test_estado_sin_proveedores_no_revienta():
    """El bot puede no tener mercado todavía al arrancar."""
    assert responder("/estado radar", precio_de) is not None
    assert responder("/estado BAOS", precio_de) is not None


def test_el_html_del_ticker_se_escapa():
    """Va en modo HTML: un `<` sin escapar rompe el mensaje entero y Telegram
    lo rechaza con un 400 — el bot se quedaría mudo, no medio mudo."""
    r = panel_radar([{**RADAR[0], "ticker": "<b>X", "estrategia": "a & b"}])
    assert "&lt;b&gt;" in r and "a &amp; b" in r


def test_una_basura_en_estado_tampoco_revienta():
    for basura in ("/estado " + "x" * 5000, "/estado ../../etc/passwd",
                   "/estado radar radar", "/estado\n\n/estado"):
        _estado(basura)          # no debe lanzar
