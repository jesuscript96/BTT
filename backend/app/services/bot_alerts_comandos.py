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
    "compra a mansalva, andale wei!!!",
    "luz verde, capitan.",
    "esos locates se pagan solos.",
    "adelante, que la cuenta sale.",
    "vía libre: el fade da de sobra.",
]
_FRASES_NO = [
    "quieto capitan, no te flipes que estan muy caras.",
    "ni de broma: el alquiler se come la ventaja.",
    "deja pasar esta, que no compensa.",
    "guarda la cartera, aqui no hay negocio.",
    "el locate cuesta mas de lo que la estrategia saca.",
]


def veredicto_locates(ticker: str, precio: Optional[float], coste: float,
                      ev_pct: float, acciones: Optional[float] = None) -> str:
    """El mensaje de `/evf`, listo para mandar.

    `acciones` es opcional y solo sirve para el redondeo a paquetes de 100: se
    cobran hacia ARRIBA, asi que 150 acciones pagan 2 paquetes y el coste real
    por accion sube un 33 %. Con posiciones grandes es ruido.
    """
    if not precio or precio <= 0:
        return f"<b>{ticker}</b>: no tengo precio en vivo. ¿Esta en el radar?"
    if coste <= 0 or ev_pct <= 0:
        return ("Faltan datos. Uso: <code>/evf TICKER COSTE_LOCATE EV%</code>\n"
                "Ejemplo: <code>/evf MIMI 0.010 2.4</code>")

    coste_real = coste
    nota = ""
    if acciones and acciones > 0:
        paquetes = -(-int(acciones) // 100)          # techo
        coste_real = (paquetes * 100 * coste) / acciones
        if coste_real > coste * 1.02:
            nota = (f"\n<i>({paquetes} paquetes para {int(acciones)} acciones: "
                    f"el locate real sale a {coste_real:.4f} $)</i>")

    fade = coste_real / precio * 100.0
    margen = ev_pct - fade
    bien = margen > 0
    frase = random.choice(_FRASES_SI if bien else _FRASES_NO)

    return (
        f"<b>{ticker}</b> a {precio:.4f} $\n"
        f"fade necesario: <b>{fade:.2f} %</b>\n"
        f"tu EV: <b>{ev_pct:.2f} %</b>\n\n"
        f"<b>{POSITIVA if bien else NEGATIVA}</b>\n"
        f"{frase}\n"
        f"<i>margen {margen:+.2f} pp</i>{nota}"
    )


AYUDA = (
    "<b>Comandos</b>\n"
    "<code>/evf TICKER COSTE EV%</code> — ¿compensan los locates?\n"
    "   ej. <code>/evf MIMI 0.010 2.4</code>\n"
    "<code>/ayuda</code> — esto"
)


def responder(texto: str, precio_de: Callable[[str], Optional[float]]) -> Optional[str]:
    """Interpreta un mensaje y devuelve la respuesta, o None si no es para mi.

    `precio_de(ticker)` la pone el bot: es su estado de mercado en vivo. Asi
    este modulo no sabe nada del feed y se puede probar con una funcion falsa.

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
            ev = float(partes[3].replace(",", ".")) if len(partes) > 3 else 0.0
            acciones = float(partes[4]) if len(partes) > 4 else None
            return veredicto_locates(ticker, precio_de(ticker), coste, ev, acciones)

        return None      # comando desconocido: mejor callarse que dar la lata
    except (ValueError, IndexError):
        return AYUDA
    except Exception as e:                                   # noqa: BLE001
        logger.warning("[COMANDOS] mensaje no procesado: %s", e)
        return None
