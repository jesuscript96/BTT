"""El diario del bot: lo que ha hecho y lo que le ha saltado.

PARA QUE. Hasta ahora, si al bot le pasaba algo, el unico sitio donde se veia
era la ventana de la consola o `bot_hoy.log`. Jaume, 2026-09-04: «si pasa algo
y no te tengo conectado cuando te encienda te lo pongo directamente». Esto es
justo eso — un cuadro al final de la pagina con las incidencias y el log, y un
boton para copiarlo entero.

POR QUE UN HANDLER DE `logging` Y NO IR LLAMANDO A MANO. Porque el encargo era
«no solo esas sino TODAS las que pudiera haber». Enganchado al logger raiz cae
aqui cualquier cosa que registre el bot **y las librerias**: un corte del socket
de Polygon, un fallo de httpx, un error de asyncio que nadie penso en capturar.
Si en el futuro alguien anyade un `log.warning` en cualquier fichero, aparece
aqui solo, sin tocar nada.

COMO SE AGRUPAN. Un corte de conexion se repite decenas de veces y llenaria la
tabla el solo. Se agrupa por la PLANTILLA del mensaje (`record.msg`), no por el
texto ya formateado: asi

    log.warning("Backend sin responder: se descartan %d avisos", 3)
    log.warning("Backend sin responder: se descartan %d avisos", 7)

son la misma fila con «×2», y en cambio dos avisos de verdad distintos siguen
separados. No hay que adivinar nada ni normalizar numeros con expresiones
regulares — la plantilla ya viene dada.

NADA DE ESTO PUEDE TUMBAR EL BOT. Un handler que lanza se come el mensaje y
ensucia la salida, y esto corre dentro del bucle que procesa velas. Todo va en
try/except: si el diario falla, el bot sigue.
"""
from __future__ import annotations

import datetime
import logging
import threading
import traceback
from collections import deque
from typing import Optional

# Cuantas lineas del log se guardan. 300 es lo que cabe en un mensaje que se
# pega en un chat sin que se haga ilegible, y cubre de sobra los ultimos
# minutos — que es lo que hace falta para entender que acaba de pasar.
LINEAS = 300

# A partir de aqui una linea es una INCIDENCIA y sube a la tabla. INFO es la
# actividad normal del bot (latencia, entradas al radar, alertas) y se queda
# solo en el log.
UMBRAL = logging.WARNING


def _hora(t: float) -> str:
    return datetime.datetime.fromtimestamp(t).strftime("%H:%M:%S")


class Diario(logging.Handler):
    """Recoge el log del bot en memoria y separa lo que ha saltado."""

    def __init__(self, lineas: int = LINEAS, umbral: int = UMBRAL):
        super().__init__(level=logging.INFO)
        self._lineas: deque = deque(maxlen=lineas)
        self._incidencias: dict = {}
        self._umbral = umbral
        self._seq = 0
        self._desde = _hora(datetime.datetime.now().timestamp())
        self._lock = threading.Lock()

    # ── entrada ──────────────────────────────────────────────────────────

    def emit(self, record: logging.LogRecord) -> None:
        try:
            texto = record.getMessage()
            with self._lock:
                self._seq += 1
                self._lineas.append({
                    "hora": _hora(record.created),
                    "nivel": record.levelname,
                    "texto": texto,
                })
                if record.levelno < self._umbral:
                    return

                # La PLANTILLA, no el texto formateado: ver la nota de arriba.
                firma = (record.levelname, record.name, str(record.msg))
                inc = self._incidencias.get(firma)
                if inc is None:
                    inc = {
                        "nivel": record.levelname,
                        "origen": record.name,
                        "mensaje": texto,
                        "veces": 0,
                        "primera": _hora(record.created),
                        "ultima": "",
                        "traza": None,
                    }
                    self._incidencias[firma] = inc
                inc["veces"] += 1
                inc["ultima"] = _hora(record.created)
                # El ULTIMO texto, que es el que interesa al mirarlo: si el
                # error cambia de detalle, se ve el detalle de ahora.
                inc["mensaje"] = texto
                if record.exc_info:
                    # La traza vale oro para pegarla, pero entera son cientos
                    # de lineas: las ultimas son las que dicen donde revento.
                    t = "".join(traceback.format_exception(*record.exc_info))
                    inc["traza"] = "\n".join(t.strip().split("\n")[-12:])
        except Exception:                                    # noqa: BLE001
            pass      # un fallo aqui NO puede costar una vela

    # ── salida ───────────────────────────────────────────────────────────

    def volcado(self, lineas: Optional[int] = None) -> dict:
        """Lo que se publica al backend y acaba en la pagina.

        `seq` es el contador de mensajes vistos. La pagina lo compara para
        saber si hay algo nuevo sin tener que traerse el log entero.
        """
        with self._lock:
            todas = list(self._lineas)
            if lineas is not None and lineas > 0:
                todas = todas[-lineas:]
            # Lo ultimo que ha saltado, arriba: es lo que se esta mirando.
            incidencias = sorted(self._incidencias.values(),
                                 key=lambda i: i["ultima"], reverse=True)
            return {
                "seq": self._seq,
                "desde": self._desde,
                "lineas": todas,
                "incidencias": incidencias,
            }

    @property
    def seq(self) -> int:
        with self._lock:
            return self._seq

    def limpiar(self) -> None:
        """Vacia el diario. Lo usa el cambio de dia, como el radar."""
        with self._lock:
            self._lineas.clear()
            self._incidencias.clear()
            self._desde = _hora(datetime.datetime.now().timestamp())


def como_texto(d: dict) -> str:
    """El volcado en texto plano, listo para pegar en un chat.

    Este es EL FORMATO QUE IMPORTA: es lo que Jaume va a copiar del boton y
    pegarme cuando algo falle sin tenerme delante. Primero las incidencias
    —que es la respuesta— y despues el log —que es el contexto—, porque quien
    lo lea empieza por arriba.
    """
    incidencias = d.get("incidencias") or []
    lineas = d.get("lineas") or []
    out = [f"=== BOT · diario desde las {d.get('desde', '?')} ==="]

    if not incidencias:
        out.append("\nSIN INCIDENCIAS.")
    else:
        out.append(f"\n--- INCIDENCIAS ({len(incidencias)}) ---")
        for i in incidencias:
            veces = f" ×{i['veces']}" if i.get("veces", 1) > 1 else ""
            cuando = (f"{i.get('primera')}→{i.get('ultima')}"
                      if i.get("veces", 1) > 1 else i.get("ultima", ""))
            out.append(f"[{i.get('nivel')}] {cuando}{veces}  {i.get('mensaje')}")
            if i.get("traza"):
                out.append("    " + i["traza"].replace("\n", "\n    "))

    out.append(f"\n--- LOG (ultimas {len(lineas)}) ---")
    out += [f"{l.get('hora')}  {l.get('texto')}" for l in lineas]
    return "\n".join(out)
