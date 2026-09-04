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

    `coste` son los DOLARES QUE CUESTAN 100 ACCIONES, la misma unidad que el
    campo «$ Locate / 100 acc.» del backtester.

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
        return ("Faltan datos. Uso: <code>/evf TICKER COSTE_100 EV%</code>\n"
                "El coste es el de 100 acciones, igual que en el backtester.\n"
                "Ejemplo: <code>/evf MIMI 1.00 2.4</code>")

    # `coste` son los DOLARES QUE CUESTAN 100 ACCIONES — la misma unidad que el
    # campo «$ Locate / 100 acc.» del backtester. Se pide asi a proposito: si
    # aqui fuera por accion y alli por paquete, el mismo numero en los dos
    # sitios daria resultados CIEN VECES distintos.
    coste_real = coste / 100.0
    nota = ""
    if acciones and acciones > 0:
        paquetes = -(-int(acciones) // 100)          # techo
        coste_real = (paquetes * coste) / acciones
        if coste_real > (coste / 100.0) * 1.02:
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
        f"locate {coste:.2f} $/100 acc  →  fade necesario <b>{fade:.4f} %</b>\n\n"
        f"<b>{POSITIVA if bien else NEGATIVA}</b>\n"
        f"{frase}\n"
        f"<i>margen {margen:+.4f} pp · basado en un EV del "
        f"{ev_pct:.4f} % ({origen})</i>{nota}"
    )


AYUDA = (
    "<b>COMANDOS</b>\n\n"

    "<code>/evf TICKER COSTE [EV%]</code>\n"
    "¿Compensa alquilar los locates de esa acción?\n\n"
    "· <b>COSTE</b> = precio del locate por <b>cada 100 acciones</b>, en $.\n"
    "  El mismo número del campo «$ Locate / 100 acc.» del backtester.\n"
    "  Si te cobran 3 $ por cada 100 acciones, escribes <code>3</code>.\n"
    "· <b>EV%</b> = opcional. Sin él uso el de la columna EV del cuadro de\n"
    "  mandos. Ponlo solo para probar otro valor.\n\n"
    "  <code>/evf MIMI 3</code>   ·   <code>/evf MIMI 3 6.4</code>\n\n"

    "<code>/ayuda</code> — esto"
)


def responder(texto: str, precio_de: Callable[[str], Optional[float]],
              ev_guardado: Optional[float] = None) -> Optional[str]:
    """Interpreta un mensaje y devuelve la respuesta, o None si no es para mi.

    `precio_de(ticker)` la pone el bot: es su estado de mercado en vivo. Asi
    este modulo no sabe nada del feed y se puede probar con una funcion falsa.

    `ev_guardado` es el EV que Jaume tiene puesto en el cuadro de mandos, para
    no tener que repetirlo en cada mensaje. Escribirlo en el comando lo pisa —
    sirve para probar otro valor sin tocar la configuracion.

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

        return None      # comando desconocido: mejor callarse que dar la lata
    except (ValueError, IndexError):
        return AYUDA
    except Exception as e:                                   # noqa: BLE001
        logger.warning("[COMANDOS] mensaje no procesado: %s", e)
        return None
