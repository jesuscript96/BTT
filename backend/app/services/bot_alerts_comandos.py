"""Comandos que se le pueden preguntar al bot por Telegram.

HASTA HOY EL BOT SOLO EMITIA. Esto es la primera vez que acepta algo de fuera, y
por eso hay dos reglas que no son opcionales:

1. **Solo responde al chat configurado.** El filtro por `chat_id` lo hace quien
   llama, antes de llegar aqui. Un bot de Telegram contesta a cualquiera que le
   escriba si no se filtra.
2. **Nada de lo que llegue toca el estado del bot.** Estos comandos solo LEEN y
   calculan. Encender, apagar o cambiar riesgos se hace en el cuadro de mandos,
   donde hay una pantalla que lo explica; por un mensaje de movil no.

QUE RESUELVE `/evf`. Antes de alquilar los locates de una accion hay que saber
si la estrategia gana lo suficiente para pagarlos:

    fade necesario (%) = coste del locate por accion / precio x 100
    compensa           <=>  EV (%) > fade necesario (%)

El TAMANO no entra: ganancia esperada y coste escalan los dos con el numero de
acciones y se cancela. Si el fade no llega para un locate, tampoco para mil.

QUE RESUELVE `/estado`. Ver lo que el bot sabe sin abrir el ordenador: la ficha
de una accion, o la lista entera de lo que esta vigilando.
"""
from __future__ import annotations

import logging
import random
from typing import Callable, Optional

logger = logging.getLogger("btt.bot_alerts.comandos")

# El veredicto va SIEMPRE con estas palabras, por peticion de Jaume. La broma
# acompanya; no lo sustituye — es lo que se lee de un vistazo en el movil.
POSITIVA = "VENTAJA MATEMATICA POSITIVA"
NEGATIVA = "VENTAJA MATEMATICA NEGATIVA"

_FRASES_SI = [
    "compra a mansalva, ándale wei!!!",
    "luz verde, capitán.",
    "esos locates se pagan solos.",
    "adelante, que la cuenta sale.",
    "vía libre: el fade da de sobra.",
    "barato como el pan de ayer.",
    "el bróker te está regalando el alquiler.",
    "con ese precio, hasta mi abuela shortea.",
    "los números dicen que sí y los números no beben.",
    "alquila, alquila, que hay margen de sobra.",
    "esto es de manual: paga los locates y a dormir.",
    "el fade se los merienda sin despeinarse.",
    "más claro, agua. Al ataque.",
    "sale a cuenta hasta con resaca.",
    "el locate es calderilla al lado del recorrido.",
]
_FRASES_NO = [
    "quieto capitán, no te flipes que están muy caras.",
    "ni de broma: el alquiler se come la ventaja.",
    "deja pasar esta, que no compensa.",
    "guarda la cartera, aquí no hay negocio.",
    "el locate cuesta más de lo que la estrategia saca.",
    "eso no es un locate, es un secuestro.",
    "pagas por el privilegio de perder, qué ganga.",
    "el bróker se lleva tu edge y te dice gracias.",
    "trabajas gratis para el que te presta las acciones.",
    "por ese precio te compras la empresa entera.",
    "ni con el viento a favor sale la cuenta.",
    "el fade no llega ni para las cañas.",
    "más caro que aparcar en el centro.",
    "esa acción no te quiere, y el locate tampoco.",
    "aquí el único que gana es el que alquila.",
]


def veredicto_locates(ticker: str, precio: Optional[float], coste: float,
                      ev_pct: float, acciones: Optional[float] = None,
                      ev_del_cuadro: bool = False) -> str:
    """El mensaje de `/evf`, listo para mandar.

    `coste` es el precio del locate POR ACCION — el que enseña el broker, que
    es lo que tienes delante cuando decides. El campo del backtester pide el del
    PAQUETE de 100 porque alli el dato se rellena una vez y viene de otro sitio:
    un locate de 1 $ el paquete son 0,01 $ la accion.

    `acciones` es opcional y solo sirve para el redondeo a paquetes de 100: se
    cobran hacia ARRIBA, asi que 150 acciones pagan 2 paquetes y el coste real
    por accion sube un 33 %. Con posiciones grandes es ruido.

    `ev_del_cuadro` dice si el EV venia del cuadro de mandos o lo escribio
    Jaume en el mensaje. Se ENSENYA en la respuesta a proposito: el veredicto
    depende por completo de ese numero, y hay que poder ver cual se ha usado
    sin abrir la aplicacion.
    """
    if not precio or precio <= 0:
        return f"<b>{ticker}</b>: no tengo precio en vivo. ¿Esta en el radar?"
    if coste <= 0 or ev_pct <= 0:
        return ("Faltan datos. Uso: <code>/evf TICKER COSTE EV%</code>\n"
                "COSTE = precio del locate POR ACCIÓN, el que da el bróker.\n"
                "Ejemplo: <code>/evf MIMI 0.01 6.4</code>")

    # `coste` es el precio del locate POR ACCIÓN — lo que enseña el broker en el
    # momento de decidir, que es cuando se usa este comando. (El campo del
    # backtester pide el del PAQUETE de 100: alli el dato viene de otra parte y
    # se rellena una vez. Un locate de 1 $ el paquete son 0,01 $ la accion.)
    coste_real = coste
    nota = ""
    if acciones and acciones > 0:
        # Los paquetes se cobran enteros: 150 acciones pagan 2 paquetes, asi que
        # el coste REAL por accion sube. Con posiciones grandes es ruido.
        paquetes = -(-int(acciones) // 100)          # techo
        coste_real = (paquetes * 100 * coste) / acciones
        if coste_real > coste * 1.02:
            nota = (f"\n<i>({paquetes} paquetes para {int(acciones)} acciones: "
                    f"el locate real sale a {coste_real:.4f} $/acción)</i>")

    fade = coste_real / precio * 100.0
    margen = ev_pct - fade
    bien = margen > 0
    frase = random.choice(_FRASES_SI if bien else _FRASES_NO)

    # CUATRO DECIMALES A PROPOSITO (Jaume, 2026-09-03: «mejor que no redondees,
    # porque lo ideal es que intentemos no sobreestimar o infraestimar»). Con
    # dos, un caso al filo salia asi:
    #
    #     fade necesario: 2,40 %   tu EV: 2,40 %   margen +0,00 pp
    #     VENTAJA MATEMATICA POSITIVA
    #
    # …y no habia forma de saber de que lado caia. En una decision de comprar o
    # no comprar, el signo no se puede perder en el formato.
    #
    # OJO, esto NO afecta al redondeo de los paquetes de 100 de mas arriba: ese
    # no es formato, es el coste real que cobra el broker. Quitarlo si seria
    # infraestimar.
    origen = ("del cuadro de mandos" if ev_del_cuadro else "el que has escrito")
    return (
        f"<b>{ticker}</b> a {precio:.4f} $\n"
        f"locate {coste:.4f} $/acción  →  fade necesario <b>{fade:.4f} %</b>\n\n"
        f"<b>{POSITIVA if bien else NEGATIVA}</b>\n"
        f"{frase}\n"
        f"<i>margen {margen:+.4f} pp · basado en un EV del "
        f"{ev_pct:.4f} % ({origen})</i>{nota}"
    )


# ── /estado ──────────────────────────────────────────────────────────────
# Lo que el bot SABE ahora mismo, sin abrir el ordenador. De solo lectura, como
# todo lo de aqui: contesta con su estado, no lo cambia.

def _esc(t: str) -> str:
    """Telegram en modo HTML: los tres de siempre."""
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _vol(v: Optional[float]) -> str:
    """Volumen legible en el movil. 1234567 -> «1.2 M»."""
    if v is None:
        return "—"
    if v >= 1e6:
        return f"{v / 1e6:.1f} M"
    if v >= 1e3:
        return f"{v / 1e3:.0f} K"
    return f"{v:.0f}"


def _n(v: Optional[float], dec: int = 2, signo: bool = False) -> str:
    """Un numero, o una raya si no se sabe.

    None NO se pinta como 0: la diferencia entre «el gap de apertura es 0 %» y
    «aun no ha abierto» decidiria distinto, y es la misma regla que sigue
    `EstadoTicker.metricas()`.
    """
    if v is None:
        return "—"
    return f"{v:+.{dec}f}" if signo else f"{v:.{dec}f}"


def _hace(seg: Optional[float]) -> str:
    """Cuanto hace del ultimo tick, en palabras.

    NO se llama «dato viejo» a proposito. Un agregado solo llega si HA HABIDO
    OPERACIONES: 40 s sin tick no es el feed caido, es una accion parada. Y eso
    es informacion util por si sola — la liquidez secandose se ve aqui antes que
    en el grafico. Se da el numero y que lo lea Jaume.
    """
    if seg is None:
        return "—"
    if seg < 90:
        return f"hace {int(seg)} s"
    return f"hace {int(seg // 60)} min"


def panel_ticker(est: Optional[dict]) -> str:
    """`/estado TICKER`: la ficha de una accion.

    `est` lo arma el bot desde su mercado en vivo; este modulo no sabe nada del
    feed. None = no se esta vigilando, y entonces NO HAY DATO: mejor decirlo que
    ensenyar un precio de hace media hora como si fuera de ahora. Es la misma
    regla que ya sigue `/evf` al no tener precio.
    """
    if not est:
        return ("No lo estoy vigilando, así que no tengo datos suyos.\n"
                "Solo sigo lo que entra en el radar — mira "
                "<code>/estado radar</code>.")

    tk = _esc(str(est.get("ticker", "?")))
    m = est.get("metricas") or {}
    filas = [
        ("PM High Gap", f"{_n(m.get('PM High Gap %'), 2, True)} %"),
        ("Gap ahora", f"{_n(m.get('Current Gap %'), 2, True)} %"),
        ("Máx. premkt", f"{_n(est.get('pre_high'), 4)} $"),
        ("Cierre ayer", f"{_n(est.get('prev_close'), 4)} $"),
        ("Volumen", _vol(est.get("day_volume"))),
        ("Vol. premkt", _vol(est.get("pre_volume"))),
        ("Último tick", _hace(est.get("visto_hace"))),
    ]
    # El gap de apertura NO EXISTE antes de las 09:30, y por eso solo aparece
    # cuando lo hay: una fila con una raya invita a leerla como un cero.
    if m.get("Open Gap %") is not None:
        filas.insert(2, ("Gap apertura", f"{_n(m['Open Gap %'], 2, True)} %"))

    tabla = "\n".join(f"{k:<13}{v:>12}" for k, v in filas)
    porque = est.get("estrategias") or []
    cola = ("\n\n<i>vigilada por " + _esc(", ".join(porque)) + "</i>" if porque
            else "\n\n<i>tengo sus datos pero no está en ningún radar</i>")
    # «AHORA a», no «a» a secas: el precio es el ultimo tick, no el de la
    # entrada ni el del barrido del radar, y la ficha se lee con el broker
    # delante. La fila de «Último tick» dice de cuando es ese «ahora».
    return (f"<b>{tk}</b> ahora a {_n(est.get('precio'), 4)} $\n"
            f"<pre>{tabla}</pre>{cola}")


def _fila_radar(c: dict) -> str:
    # CORTAR Y RELLENAR ANTES DE ESCAPAR, no al reves. Escapando primero, un
    # ticker raro como `<b>X` se convierte en `&lt;b&gt;X` y el corte a 6 lo
    # parte por la mitad de la entidad (`&lt;b&`): Telegram rechaza el mensaje
    # ENTERO con un 400 y el bot se queda mudo, no medio mudo. Y de paso la
    # columna cuadra, que se rellena por caracteres visibles.
    return "{}{:>9}{:>10}{:>8}  {}".format(
        _esc(f"{str(c.get('ticker', '?'))[:6]:<6}"),
        f"{_n(c.get('valor'), 2, True)}%",
        f"{_n(c.get('precio'), 4)}$",
        _vol(c.get("volumen")),
        _esc(str(c.get("estrategia", ""))),
    )


def _cuantos(cands: list) -> int:
    """Tickers distintos, no filas.

    Un ticker puede estar por VARIAS estrategias, con una fila cada una: «3
    vigiladas» con 5 filas no es un error.
    """
    return len({str(c.get("ticker")) for c in cands})


def panel_radar(cands: Optional[list]) -> str:
    """`/estado radar`: todo lo vigilado, de un vistazo.

    Llega ya ordenado por la metrica que las trajo — que es el orden en el que
    interesan — asi que aqui no se reordena.
    """
    if cands is None:
        return "No tengo radar: el bot arrancó con una lista de tickers a mano."
    if not cands:
        return ("<b>RADAR</b> — vacío ahora mismo.\n"
                "<i>Nada ha cumplido todavía el filtro de ninguna estrategia.</i>")

    # LA LISTA ES LO QUE SE ESTA VIGILANDO AHORA, y nada mas (Jaume, 2026-09-04:
    # «solo quiero que aparezca lo del radar en este momento»). Las de ayer no
    # pueden colarse: el radar se vacia al cambiar de dia.
    #
    # Queda un caso raro: un ticker que HOY cumple el filtro pero no cabe en el
    # cupo del socket (25 a la vez). Ese NO se evalua y NO va a dar avisos, asi
    # que no puede ir en la lista como si se vigilara — pero tampoco merece una
    # tabla aparte: harian falta 25 gappers del 50 % la misma manyana. Una linea
    # al pie, y solo si pasa. Sin la marca se dan por seguidas, para que un
    # radar que no la ponga se siga leyendo igual.
    seguidas = [c for c in cands if c.get("seguido", True)]
    esperando = [c for c in cands if not c.get("seguido", True)]

    n = _cuantos(seguidas)
    cab = f"<b>RADAR</b> — {n} vigilada{'s' if n != 1 else ''}"
    cuerpo = ("\n<pre>" + "\n".join(_fila_radar(c) for c in seguidas) + "</pre>"
              if seguidas else "\n<i>ninguna cabe en el cupo ahora mismo.</i>")

    # La metrica se dice UNA VEZ al pie en vez de repetirla en cada fila: en el
    # movil no cabe, y sin ella la columna del % no significa nada.
    metricas = sorted({str(c.get("metrica")) for c in cands if c.get("metrica")})
    pie = ("\n<i>la columna del % es " + _esc(" / ".join(metricas)) + "</i>"
           if metricas else "")
    if esperando:
        cuantas = _cuantos(esperando)
        pie += (f"\n<i>(+{cuantas} más ha entrado hoy pero no cabe en el cupo: "
                f"de {'esas' if cuantas != 1 else 'esa'} NO aviso)</i>")
    return cab + cuerpo + pie


AYUDA = (
    "<b>COMANDOS</b>\n\n"

    "<code>/evf TICKER COSTE [EV%]</code>\n"
    "¿Compensa alquilar los locates de esa acción?\n\n"
    "· <b>COSTE</b> = precio del locate <b>POR ACCIÓN</b>, tal cual te lo da\n"
    "  el bróker. Si el locate entero (100 acciones) vale 1 $, escribes\n"
    "  <code>0.01</code>.\n"
    "  <i>Ojo: el campo del backtester pide el del paquete de 100 — allí\n"
    "  ese mismo locate se mete como 1.</i>\n"
    "· <b>EV%</b> = opcional. Sin él uso el de la columna EV del cuadro de\n"
    "  mandos. Ponlo solo para probar otro valor.\n\n"
    "  <code>/evf MIMI 0.01</code>   ·   <code>/evf MIMI 0.01 6.4</code>\n\n"

    "<code>/estado radar</code>\n"
    "Las que estoy vigilando ahora, con la métrica que las metió.\n"
    "<i>(<code>/estado</code> a secas hace lo mismo)</i>\n\n"

    "<code>/estado TICKER</code>\n"
    "Su ficha: gap, máximo de premercado, volumen y hace cuánto fue su\n"
    "última operación.\n\n"

    "<code>/ayuda</code> — esto"
)


def responder(texto: str, precio_de: Callable[[str], Optional[float]],
              ev_guardado: Optional[float] = None,
              estado_de: Optional[Callable[[str], Optional[dict]]] = None,
              radar: Optional[Callable[[], Optional[list]]] = None
              ) -> Optional[str]:
    """Interpreta un mensaje y devuelve la respuesta, o None si no es para mi.

    `precio_de(ticker)` la pone el bot: es su estado de mercado en vivo. Asi
    este modulo no sabe nada del feed y se puede probar con una funcion falsa.

    `ev_guardado` es el EV que Jaume tiene puesto en el cuadro de mandos, para
    no tener que repetirlo en cada mensaje. Escribirlo en el comando lo pisa —
    sirve para probar otro valor sin tocar la configuracion.

    `estado_de(ticker)` y `radar()` son lo mismo para `/estado`: las pone el bot
    con su mercado en vivo, en forma de diccionarios sueltos. Sin ellas el
    comando dice que no hay datos en vez de fallar — el bot puede arrancar con
    una lista de tickers a mano, sin radar, y entonces `/estado radar` lo dice.

    NUNCA lanza. Un mensaje raro no puede tumbar el bucle que procesa velas.
    """
    try:
        t = (texto or "").strip()
        if not t.startswith("/"):
            return None
        partes = t.split()
        cmd = partes[0].lower().lstrip("/").split("@")[0]   # /evf@MiBot -> evf

        if cmd in ("ayuda", "help", "start"):
            return AYUDA

        if cmd == "evf":
            if len(partes) < 2:
                return AYUDA
            ticker = partes[1].upper()
            coste = float(partes[2].replace(",", ".")) if len(partes) > 2 else 0.0
            # El EV se puede omitir: se coge el del cuadro de mandos. Ponerlo en
            # el mensaje lo pisa, para probar otro sin tocar la configuración.
            ev = (float(partes[3].replace(",", ".")) if len(partes) > 3
                  else (ev_guardado or 0.0))
            acciones = float(partes[4]) if len(partes) > 4 else None
            if not ev:
                return ("No tengo EV. Ponlo en el cuadro de mandos (columna "
                        "<b>EV %</b> de la estrategia) o escríbelo aquí:\n"
                        "<code>/evf TICKER COSTE_100 EV%</code>")
            return veredicto_locates(ticker, precio_de(ticker), coste, ev,
                                     acciones, ev_del_cuadro=len(partes) <= 3)

        if cmd == "estado":
            # `/estado` a secas enseña el radar: es lo que se quiere ver casi
            # siempre, y ahorra teclear en el móvil.
            que = partes[1].lower() if len(partes) > 1 else "radar"
            if que in ("radar", "todas", "todo"):
                return panel_radar(radar() if radar else None)
            return panel_ticker(estado_de(que.upper()) if estado_de else None)

        return None      # comando desconocido: mejor callarse que dar la lata
    except (ValueError, IndexError):
        return AYUDA
    except Exception as e:                                   # noqa: BLE001
        logger.warning("[COMANDOS] mensaje no procesado: %s", e)
        return None
