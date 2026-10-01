"""Avisos del bot: cola en hilo aparte, canales (Telegram A/B, correo, SMS), textos del grupo B y filtro de secretos.

QUÉ HACE. `ColaAvisos.poner` deja un `Aviso` en una cola en memoria y vuelve
en microsegundos (`put_nowait`); el hilo `avisos-envio` (un `HiloVigilado`)
lo reparte a cada canal cuyo `niveles` contenga el nivel del aviso y cuyo
`grupos` contenga su grupo, con reintentos y espera entre ellos (R-M-01,
R-M-02, R-J-08). `CanalTelegram` habla con la API por `urllib.request`;
`CanalCorreo` por `smtplib` con STARTTLS; `CanalSMS` delega en un proveedor
(`ProveedorSMSNulo` mientras Jaume elige uno, R-M-02). `canales_desde_env`
construye los canales con las credenciales del `.env` (R-Q-01).
`texto_grupo_a` reutiliza el formato de hoy del bot de alertas (R-M-05);
`texto_fill` es el texto de fill del grupo B (R-O-03); el aviso de un
rechazo que sale a Telegram lo redacta `reglas.rechazos` (C-04), y
`texto_rechazo` queda solo como formato de consulta. `escapar` es el helper
único para escapar todo texto variable de un aviso (D2-08).
`FiltroSecretos` tapa los VALORES literales de los secretos (y la forma URL
del token de Telegram) en `msg`, `args` y trazas de cada `LogRecord`
(corrección 8, riesgo 20); `instalar_logging` monta el log por proceso y día
con ese filtro en todos los handlers.

POR QUÉ ESTÁ AQUÍ. R-M-05 exige que el bot sea EXACTAMENTE igual de rápido
con alarmas que sin ellas: el hilo que decide solo encola; nadie hace HTTP
en su camino. Y R-Q-01 exige arreglar la fuga del token de Telegram en los
logs antes del dinero real: la memoria del proyecto («httpx filtra tokens»)
dice que `httpx` registra la URL entera, con el token dentro. Por eso aquí
no hay `httpx`: `urllib` no loguea nada y los mensajes de error se escriben
sin la URL (injerto A §8.20).

LAS TRAMPAS.
  * `poner` NUNCA bloquea ni lanza por la cola: tope superado → `perdidos`
    += 1 y el bot sigue (R-J-08). Lo único que lanza es un `TypeError` /
    `ValueError` si no le dan un `Aviso` con nivel y grupo válidos (error de
    programación, no de red).
  * La clave de dedupe solo se registra si el aviso ENTRÓ en la cola: si se
    perdió por el tope, el siguiente con la misma clave no se calla.
  * El dedupe por `clave` usa `reloj.mono()` INYECTADO (tests con reloj
    simulado); las esperas del hilo de envío son de reloj real
    (`Event.wait`), porque un canal caído tarda segundos reales.
  * Un solo hilo de envío: un canal lento (SMTP caído, 15 s de timeout)
    retrasa lo que viene detrás. Por eso Telegram va el primero en la lista
    y, cuando el bot se está parando, cada aviso recibe UN intento por canal
    y ninguna espera: se vacía lo que se pueda (§6.2 paso 5).
  * Los filtros de un `Logger` NO se aplican a los registros que suben por
    propagación desde loggers hijos: el `FiltroSecretos` va en los HANDLERS
    (fichero, consola y memoria), nunca solo en el logger raíz.
  * `FiltroSecretos` sustituye en `record.msg` y en cada `record.args` sin
    cambiar su forma (tupla sigue tupla, dict sigue dict): el `%` del
    formateo posterior no se rompe. Si el secreto va dentro de un arg que NO
    es str (un número para `%d`, un objeto), taparlo cambiaría su tipo y el
    `%d` lanzaría: entonces se formatea primero y se tapa el texto ya
    formateado (C-03). La traza de una excepción se formatea y limpia en el
    propio filtro (`exc_text`), porque el `Formatter` la generaría después,
    ya sin filtro. Los secretos de menos de `SECRETO_LONGITUD_MIN` (4)
    caracteres no se pueden tapar sin destrozar el log: `instalar_logging`
    avisa de cuántos hay (SEG-04), nunca de su valor.
  * Telegram limita a 4.096 unidades UTF-16 (un emoji cuenta 2, así que
    `len()` no sirve) y con HTML mal cerrado devuelve 400
    para siempre: un texto que no cabe se recorta SIN etiquetas HTML y se
    manda sin `parse_mode`, para que no se pierda el aviso entero. Y un 400
    «can't parse entities» (un «<» del bróker sin escapar) se reenvía UNA vez
    sin `parse_mode` (D2-08).
  * `CanalTelegram`, `CanalCorreo` y `CanalSMS` NUNCA lanzan y nunca
    escriben su token/clave: lo que llega al log de un error pasa antes por
    `_sin_secreto` del propio canal (además del `FiltroSecretos` global).
  * Importar este módulo no abre red, no arranca hilos y NO carga `httpx`:
    `bot_alerts_telegram` (que importa `httpx`) se importa de forma perezosa
    dentro de `texto_grupo_a` (SEG-05); las variables de entorno se leen en
    `canales_desde_env` y `secretos_desde_env`, nunca al importar.
"""
from __future__ import annotations

import html
import json
import logging
import os
import queue
import re
import smtplib
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import replace
from datetime import date
from decimal import Decimal
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Iterable, Optional, Protocol, runtime_checkable

from app.bot_das.cerrojo import HiloVigilado
from app.bot_das.reloj import Reloj
from app.bot_das.tipos import (
    COLA_AVISOS_TOPE,
    Aviso,
    Avisar,
    Config,
    EstadoLote,
    Fase,
    Fill,
    Grupo,
    Lote,
    Nivel,
    Orden,
    PosicionTicker,
    TipoOrden,
)

logger = logging.getLogger("btt.bot_das.avisos")

API_TELEGRAM = "https://api.telegram.org"
TELEGRAM_MAX_UNIDADES = 4096        # Telegram limita `text` a 4.096 unidades UTF-16 (un emoji astral cuenta 2)
SMS_MAX_CARACTERES = 320            # dos SMS concatenados; el proveedor real podrá recortar más
CORREO_ASUNTO_MAX = 80
DEDUPE_VENTANA_S = 60.0             # §3.9: dedupe por `clave` en ventana de 60 s
DEDUPE_PODA_CADA = 512              # cada cuántas claves nuevas se limpian las caducadas (amortizado, `poner` sigue en µs)
NIVELES_TODOS = frozenset({Nivel.INFO, Nivel.AVISO, Nivel.MAXIMO})
NIVELES_CORREO = frozenset({Nivel.AVISO, Nivel.MAXIMO})     # R-M-02: correo → niveles 2 y 3
NIVELES_SMS = frozenset({Nivel.MAXIMO})                     # R-M-02: SMS → SOLO nivel 3
NIVELES_GRUPO_A = frozenset({Nivel.INFO})                   # R-M-05: el grupo A recibe alarmas, no incidentes del bot
VARIABLES_SECRETAS = ("TELEGRAM_BOT_TOKEN_A", "TELEGRAM_BOT_TOKEN_B", "DAS_CLAVE",
                      "BOT_DAS_AUTHKEY", "MASSIVE_BOT_API_KEY", "SMTP_PASS")   # corrección 8
SECRETO_LONGITUD_MIN = 4             # SEG-04: una DAS_CLAVE de 4-5 caracteres también se tapa; < 4 se avisa al arrancar
MASCARA = "*****"
PATRON_TOKEN_URL = re.compile(r"bot\d+:[A-Za-z0-9_-]+")     # forma URL del token: /bot123456:ABC-def/sendMessage
MEMORIA_LOG_LINEAS = 500
SMTP_PUERTO_DEFECTO = 587
_NIVEL_LOG = {Nivel.INFO: logging.INFO, Nivel.AVISO: logging.WARNING, Nivel.MAXIMO: logging.ERROR}
_LADO_LEGIBLE = {"B": "COMPRA", "S": "VENTA", "SS": "CORTO"}
_PATRON_HTML = re.compile(r"<[^<>]+>")
_PATRON_ETIQUETA_TELEGRAM = re.compile(
    r"</?(?:b|strong|i|em|u|ins|s|strike|del|code|pre|a|span|tg-spoiler|tg-emoji|blockquote)(?:\s[^<>]*)?>",
    re.IGNORECASE)


# ── utilidades de texto ─────────────────────────────────────────────────
def escapar(texto: Any) -> str:
    """`html.escape(str(texto), quote=False)`: EL helper para todo texto variable que va a Telegram (D2-08).

    Telegram manda con `parse_mode=HTML`: un «<», «>» o «&» sin escapar (el
    texto literal de DAS, el nombre de una estrategia) hace que rechace el
    mensaje entero con 400. Úsalo en cada valor dinámico de un `Avisar`.
    """
    return html.escape(str(texto), quote=False)


def escapar_html(texto: Any) -> str:
    """Escapa lo que va dentro del HTML de Telegram (un ticker con `<` rompería el mensaje entero). Igual que `escapar`."""
    return escapar(texto)


def sin_html(texto: str) -> str:
    """Quita las etiquetas HTML y deshace las entidades: para correo, SMS y recortes."""
    plano = _PATRON_HTML.sub("", texto)
    return plano.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def texto_plano_telegram(texto: str) -> str:
    """Quita SOLO las etiquetas de formato de Telegram y deshace las entidades (D2-08, reenvío sin `parse_mode`).

    A diferencia de `sin_html`, no se come un «< 5 y 7 >» del bróker: solo
    quita `<b>`, `<i>`, `<a href=…>`… (lo que el bot pone), así el texto que
    no se pudo mandar con formato llega entero.
    """
    return html.unescape(_PATRON_ETIQUETA_TELEGRAM.sub("", texto))


def recortar(texto: str, maximo: int) -> str:
    """Recorta a `maximo` caracteres dejando una elipsis; un texto que cabe vuelve tal cual."""
    if maximo < 1:
        raise ValueError(f"maximo debe ser ≥ 1: {maximo}")
    if len(texto) <= maximo:
        return texto
    return texto[: maximo - 1] + "…"


def unidades_utf16(texto: str) -> int:
    """Longitud tal como la cuenta Telegram (unidades UTF-16: un emoji fuera del plano básico cuenta 2)."""
    return len(texto.encode("utf-16-le")) // 2


def recortar_telegram(texto: str, maximo: int = TELEGRAM_MAX_UNIDADES) -> str:
    """Recorta a `maximo` unidades UTF-16 con elipsis (límite real de `sendMessage`); termina siempre."""
    if unidades_utf16(texto) <= maximo:
        return texto
    caracteres = maximo
    while True:
        corte = recortar(texto, caracteres)
        exceso = unidades_utf16(corte) - maximo
        if exceso <= 0:
            return corte
        caracteres -= exceso                # cada vuelta quita al menos un carácter


def formatear_numero(valor: Any, decimales: int = 4) -> str:
    """Número en formato español (miles con punto, decimales con coma); None → «—». Nunca notación científica."""
    if valor is None:
        return "—"
    if isinstance(valor, float):
        valor = Decimal(str(valor))
    texto = f"{valor:,.{decimales}f}"
    return texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def formatear_precio(precio: Optional[Decimal]) -> str:
    """Precio con los decimales de su tick (regla 612): 2 si ≥ 1 $, 4 si < 1 $; None → «—»."""
    if precio is None:
        return "—"
    valor = Decimal(str(precio)) if not isinstance(precio, Decimal) else precio
    return formatear_numero(valor, 2 if abs(valor) >= 1 else 4)


def prefijo_fase(fase: Fase) -> str:
    """«[SOMBRA]», «[CANARIO]» o «[REAL]» (R-O-03: la fase visible en cada aviso de Telegram)."""
    return f"[{Fase(fase).name}]"


def con_prefijo_fase(texto: str, fase: Fase) -> str:
    """Antepone el prefijo de fase si el texto no lo lleva ya (idempotente)."""
    prefijo = prefijo_fase(fase)
    return texto if texto.startswith(prefijo) else f"{prefijo} {texto}"


def contexto_ssl() -> ssl.SSLContext:
    """Contexto SSL con el ALMACÉN DE CERTIFICADOS DE WINDOWS (bot_alerts_telegram l.41-62).

    En la máquina de Jaume el antivirus intercepta el HTTPS y firma con su
    propia autoridad, que `certifi` no conoce y el almacén del sistema sí.
    Nunca se desactiva la verificación. Si el almacén no se puede cargar
    (mismo respaldo que `_verify` del bot de alertas), queda el contexto por
    defecto de Python, que en Windows también verifica.
    """
    contexto = ssl.create_default_context()
    try:
        contexto.load_default_certs(ssl.Purpose.SERVER_AUTH)
    except Exception:  # noqa: BLE001 — frontera del SO: sin almacén de Windows queda el contexto por defecto (verifica igual)
        logger.warning("[AVISOS] no se pudo cargar el almacén de certificados del sistema; se usa el contexto por defecto")
    return contexto


def aviso_de(accion: Avisar, creado_en: float) -> Aviso:
    """Convierte la acción `Avisar` del decisor en el `Aviso` que se encola (el ejecutor pone `ahora`)."""
    return Aviso(nivel=accion.nivel, grupo=accion.grupo, texto=accion.texto, clave=accion.clave, creado_en=float(creado_en))


# ── canales ─────────────────────────────────────────────────────────────
@runtime_checkable
class Canal(Protocol):
    """Lo que la cola necesita de un canal: a qué niveles y grupos atiende y un envío bloqueante de UN intento que NUNCA lanza."""

    nombre: str
    niveles: frozenset[Nivel]
    grupos: frozenset[Grupo]

    def enviar(self, texto: str) -> bool: ...


class CanalTelegram:
    """Telegram por `urllib.request` (R-M-02; injerto A §8.20: nada de httpx, que loguea la URL con el token).

    `api` es el origen de la API; los tests lo apuntan a un `http.server`
    local. El token solo vive en `_url` y en `_token` (para taparlo si un
    error lo trajera); ningún mensaje de log lo lleva (R-Q-01).
    """

    def __init__(self, token: str, chat_id: str, grupo: Grupo, niveles: frozenset[Nivel],
                 timeout_s: float = 10.0, api: str = API_TELEGRAM) -> None:
        token = str(token).strip()
        chat = str(chat_id).strip()
        if not token or not chat:
            raise ValueError("CanalTelegram necesita token y chat_id no vacíos")
        if timeout_s <= 0:
            raise ValueError(f"timeout_s debe ser > 0: {timeout_s}")
        self.nombre = f"telegram-{Grupo(grupo).value}"
        self.niveles = frozenset(Nivel(n) for n in niveles)
        self.grupos = frozenset({Grupo(grupo)})
        self._token = token
        self._chat_id = chat
        self._url = f"{api.rstrip('/')}/bot{token}/sendMessage"
        self._timeout_s = float(timeout_s)
        self._ssl = contexto_ssl()
        self.enviados = 0
        self.fallos = 0

    def _sin_secreto(self, texto: str) -> str:
        return PATRON_TOKEN_URL.sub(MASCARA, texto.replace(self._token, MASCARA))

    def _cuerpo(self, texto: str) -> dict:
        """JSON de `sendMessage`: HTML y sin vista previa; si no cabe, recortado sin etiquetas y sin `parse_mode`."""
        cuerpo: dict[str, Any] = {"chat_id": self._chat_id, "disable_web_page_preview": True}
        if unidades_utf16(texto) <= TELEGRAM_MAX_UNIDADES:
            cuerpo["text"] = texto
            cuerpo["parse_mode"] = "HTML"
        else:
            cuerpo["text"] = recortar_telegram(sin_html(texto))
        return cuerpo

    def enviar(self, texto: str) -> bool:
        """POST `{api}/bot{token}/sendMessage`; True solo con HTTP 200 y `ok: true`. Un intento; nunca lanza (R-J-08).

        D2-08: si Telegram contesta 400 «can't parse entities» (HTML mal
        formado: un «<» del bróker sin escapar), se reenvía UNA vez el mismo
        aviso sin `parse_mode` y con las etiquetas de formato quitadas: ningún
        aviso se pierde por un «<». Ese reenvío es parte del mismo intento.
        """
        cuerpo = self._cuerpo(texto)
        ok, error_400 = self._post(cuerpo)
        if not ok and error_400 is not None and "parse_mode" in cuerpo and _es_error_de_entidades(error_400):
            logger.warning("[%s] Telegram no entiende el HTML del aviso (HTTP 400): se reenvía sin formato (D2-08)",
                           self.nombre)
            ok, _ = self._post(self._cuerpo_sin_formato(texto))
        if ok:
            self.enviados += 1
        else:
            self.fallos += 1
        return ok

    def _cuerpo_sin_formato(self, texto: str) -> dict:
        """JSON de `sendMessage` SIN `parse_mode`: etiquetas de Telegram fuera y entidades deshechas (D2-08)."""
        return {"chat_id": self._chat_id, "disable_web_page_preview": True,
                "text": recortar_telegram(texto_plano_telegram(texto))}

    def _post(self, cuerpo_json: dict) -> tuple[bool, Optional[str]]:
        """Un POST. Devuelve (salió, detalle del error si fue un HTTP 400, sin secretos). Nunca lanza."""
        datos = json.dumps(cuerpo_json, ensure_ascii=False).encode("utf-8")
        peticion = urllib.request.Request(self._url, data=datos, method="POST",
                                          headers={"Content-Type": "application/json; charset=utf-8"})
        try:
            with urllib.request.urlopen(peticion, timeout=self._timeout_s, context=self._ssl) as respuesta:
                estado = int(respuesta.status)
                cuerpo = respuesta.read(4096)
        except urllib.error.HTTPError as exc:      # frontera de red (R-J-08): Telegram contestó 4xx/5xx; el detalle va sin URL (R-Q-01)
            detalle = self._sin_secreto(_leer_error(exc))
            logger.warning("[%s] rechazado (HTTP %s): %s", self.nombre, exc.code, detalle)
            return False, (detalle if exc.code == 400 else None)
        except Exception as exc:  # noqa: BLE001 — frontera de red (R-J-08): timeout, DNS, SSL o URL rota; nunca se loguea la URL (R-Q-01)
            logger.warning("[%s] fallo de envío: %s", self.nombre, self._sin_secreto(f"{type(exc).__name__}: {exc}"))
            return False, None
        if estado != 200 or not _respuesta_ok(cuerpo):
            detalle = self._sin_secreto(cuerpo[:300].decode("utf-8", "replace"))
            logger.warning("[%s] respuesta no válida (HTTP %s): %s", self.nombre, estado, detalle)
            return False, (detalle if estado == 400 else None)
        return True, None


def _es_error_de_entidades(detalle: str) -> bool:
    """El 400 de Telegram por HTML mal formado: «Bad Request: can't parse entities: …» (D2-08)."""
    return "can't parse entities" in detalle.lower() or "can\\u0027t parse entities" in detalle.lower()


def _leer_error(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read(300).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 — frontera de red: el cuerpo del error puede no estar disponible
        return str(exc.reason)


def _respuesta_ok(cuerpo: bytes) -> bool:
    try:
        datos = json.loads(cuerpo.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return False
    return isinstance(datos, dict) and datos.get("ok") is True


class CanalCorreo:
    """Correo por `smtplib` con STARTTLS obligatorio (R-M-02: niveles 2 y 3; R-J-08: canal alternativo a Telegram)."""

    def __init__(self, smtp_host: str, smtp_puerto: int, usuario: str, clave: str, destino: str,
                 niveles: frozenset[Nivel] = NIVELES_CORREO, timeout_s: float = 15.0,
                 remitente: Optional[str] = None) -> None:
        if not smtp_host or not destino:
            raise ValueError("CanalCorreo necesita smtp_host y destino")
        if type(smtp_puerto) is not int or not (1 <= smtp_puerto <= 65535):
            raise ValueError(f"puerto SMTP inválido: {smtp_puerto!r}")
        self.nombre = "correo"
        self.niveles = frozenset(Nivel(n) for n in niveles)
        self.grupos = frozenset({Grupo.B})
        self._host = smtp_host
        self._puerto = smtp_puerto
        self._usuario = usuario
        self._clave = clave
        self._destino = destino
        self._remitente = remitente or usuario
        self._timeout_s = float(timeout_s)
        self._ssl = contexto_ssl()
        self.enviados = 0
        self.fallos = 0

    def _sin_secreto(self, texto: str) -> str:
        return texto.replace(self._clave, MASCARA) if self._clave else texto

    def enviar(self, texto: str) -> bool:
        """EHLO → STARTTLS → LOGIN → envío en texto plano (sin HTML). Un intento; nunca lanza; nunca loguea la clave."""
        plano = sin_html(texto)
        asunto = "[bot DAS] " + recortar(plano.strip().splitlines()[0] if plano.strip() else "aviso", CORREO_ASUNTO_MAX)
        mensaje = EmailMessage()
        mensaje["Subject"] = asunto
        mensaje["From"] = self._remitente
        mensaje["To"] = self._destino
        mensaje.set_content(plano)
        try:
            with smtplib.SMTP(self._host, self._puerto, timeout=self._timeout_s) as smtp:
                smtp.ehlo()
                smtp.starttls(context=self._ssl)     # sin STARTTLS no se manda la clave: prefiere fallar (R-Q-01)
                smtp.ehlo()
                smtp.login(self._usuario, self._clave)
                smtp.send_message(mensaje)
        except Exception as exc:  # noqa: BLE001 — frontera de red (R-J-08): SMTP caído, TLS no disponible, clave rechazada
            self.fallos += 1
            logger.warning("[correo] fallo de envío: %s", self._sin_secreto(f"{type(exc).__name__}: {exc}"))
            return False
        self.enviados += 1
        return True


@runtime_checkable
class ProveedorSMS(Protocol):
    """Proveedor de SMS (R-M-02: por elegir; Amazon SNS o Twilio). `enviar` bloqueante, nunca lanza."""

    nombre: str

    def enviar(self, texto: str) -> bool: ...


class ProveedorSMSNulo:
    """Proveedor «nulo»: deja el SMS en el log y devuelve True (R-M-02 proveedor [PENDIENTE]; mantiene el contrato)."""

    nombre = "nulo"

    def __init__(self) -> None:
        self.enviados = 0
        self.ultimo: Optional[str] = None

    def enviar(self, texto: str) -> bool:
        self.enviados += 1
        self.ultimo = texto
        logger.warning("[SMS nulo] proveedor sin elegir (R-M-02): %s", texto)
        return True


class CanalSMS:
    """SMS (R-M-02: SOLO nivel 3). Texto plano recortado; el proveedor es intercambiable."""

    def __init__(self, proveedor: ProveedorSMS, niveles: frozenset[Nivel] = NIVELES_SMS) -> None:
        self.nombre = f"sms-{getattr(proveedor, 'nombre', 'desconocido')}"
        self.niveles = frozenset(Nivel(n) for n in niveles)
        self.grupos = frozenset({Grupo.B})
        self._proveedor = proveedor
        self.enviados = 0
        self.fallos = 0

    def enviar(self, texto: str) -> bool:
        plano = recortar(sin_html(texto), SMS_MAX_CARACTERES)
        try:
            salio = bool(self._proveedor.enviar(plano))
        except Exception as exc:  # noqa: BLE001 — frontera de callback: un proveedor que lanza cuenta como fallo, nunca tumba el hilo
            self.fallos += 1
            logger.warning("[%s] el proveedor lanzó %s: %s", self.nombre, type(exc).__name__, exc)
            return False
        if salio:
            self.enviados += 1
        else:
            self.fallos += 1
        return salio


# ── la cola ─────────────────────────────────────────────────────────────
class ColaAvisos:
    """Cola en memoria + hilo `avisos-envio` (R-M-05: el ejecutor solo encola; R-J-08: reintentos y nada se pierde en silencio).

    `poner` es `put_nowait`; dedupe por `clave` en `ventana_dedupe_s` con el
    reloj inyectado; tope superado → `perdidos`. El hilo reparte cada aviso
    a los canales que atienden su nivel y su grupo, `1 + reintentos`
    intentos por canal con `espera_reintento_s` entre ellos. Todo aviso va
    también al log (R-M-01) al despacharlo.
    """

    def __init__(self, canales: list[Canal], reloj, tope: int = COLA_AVISOS_TOPE, reintentos: int = 3,
                 espera_reintento_s: float = 2.0, ventana_dedupe_s: float = DEDUPE_VENTANA_S) -> None:
        if type(tope) is not int or tope < 1:
            raise ValueError(f"tope debe ser un entero ≥ 1: {tope!r}")
        if type(reintentos) is not int or reintentos < 0:
            raise ValueError(f"reintentos debe ser un entero ≥ 0: {reintentos!r}")
        if espera_reintento_s < 0 or ventana_dedupe_s < 0:
            raise ValueError("espera_reintento_s y ventana_dedupe_s deben ser ≥ 0")
        for canal in canales:
            if not isinstance(canal, Canal):
                raise TypeError(f"{canal!r} no cumple el Protocol Canal (nombre, niveles, grupos, enviar)")
        self._canales: list[Canal] = list(canales)
        self._reloj = reloj
        self._cola: "queue.Queue[Aviso]" = queue.Queue(maxsize=tope)
        self._reintentos = reintentos
        self._espera_s = float(espera_reintento_s)
        self._ventana_s = float(ventana_dedupe_s)
        self._cerrojo = threading.Lock()
        self._ultimo_por_clave: dict[str, float] = {}
        self._claves_desde_poda = 0
        self._perdidos = 0
        self._deduplicados = 0
        self._enviados = 0
        self._fallidos = 0
        self._despachados = 0
        self._tope_avisado = False
        self._hilo = HiloVigilado("avisos-envio", self._bucle, self._al_caida, max_relanzos=5, espera_s=1.0)

    # ── lado del decisor: nunca bloquea ──
    def poner(self, aviso: Aviso) -> None:
        """`put_nowait` (R-M-05). Dedupe por `clave` dentro de la ventana; cola llena → `perdidos` += 1 (R-J-08).

        Lanza `TypeError`/`ValueError` solo con un objeto que no es un `Aviso`
        con nivel y grupo válidos (error de programación). Un `nivel` dado
        como entero o un `grupo` dado como letra se normalizan al enum.
        """
        if not isinstance(aviso, Aviso):
            raise TypeError(f"poner espera un Aviso, no {type(aviso).__name__}")
        nivel, grupo = Nivel(aviso.nivel), Grupo(aviso.grupo)    # ValueError si no existen
        if nivel is not aviso.nivel or grupo is not aviso.grupo:
            aviso = replace(aviso, nivel=nivel, grupo=grupo)
        ahora = self._reloj.mono() if aviso.clave is not None else 0.0
        with self._cerrojo:
            if aviso.clave is not None:
                ultimo = self._ultimo_por_clave.get(aviso.clave)
                if ultimo is not None and (ahora - ultimo) < self._ventana_s:
                    self._deduplicados += 1
                    return
            try:
                self._cola.put_nowait(aviso)
            except queue.Full:                      # frontera de cola (R-J-08): el tope protege la memoria; el bot sigue
                self._perdidos += 1
                avisar = not self._tope_avisado
                self._tope_avisado = True
            else:
                avisar = False
                if aviso.clave is not None:         # solo cuenta como «avisado» lo que entró en la cola
                    self._ultimo_por_clave[aviso.clave] = ahora
                    self._claves_desde_poda += 1
                    if self._claves_desde_poda >= DEDUPE_PODA_CADA:
                        self._podar_claves(ahora)
        if avisar:
            logger.error("[AVISOS] cola llena (%d): se pierden avisos hasta que baje", self._cola.maxsize)

    def _podar_claves(self, ahora: float) -> None:
        """Con el cerrojo tomado: olvida las claves fuera de la ventana (evita crecer sin límite)."""
        caducadas = [clave for clave, momento in self._ultimo_por_clave.items() if (ahora - momento) >= self._ventana_s]
        for clave in caducadas:
            del self._ultimo_por_clave[clave]
        self._claves_desde_poda = 0

    # ── ciclo de vida ──
    def arrancar(self) -> None:
        self._hilo.arrancar()

    def parar(self, espera_s: float = 30.0) -> None:
        """Pide parar y espera hasta `espera_s`: el hilo vacía lo que pueda con UN intento por canal y sin esperas."""
        self._hilo.parar(espera_s)
        sin_enviar = self.pendientes
        if sin_enviar:
            logger.warning("[AVISOS] cierro con %d aviso(s) sin enviar", sin_enviar)

    @property
    def pendientes(self) -> int:
        return self._cola.qsize()

    @property
    def perdidos(self) -> int:
        """Avisos descartados por tope de cola."""
        return self._perdidos

    @property
    def deduplicados(self) -> int:
        return self._deduplicados

    @property
    def enviados(self) -> int:
        """Envíos (aviso, canal) que salieron."""
        return self._enviados

    @property
    def fallidos(self) -> int:
        """Envíos (aviso, canal) que agotaron los reintentos (quedan en el log como PERDIDO)."""
        return self._fallidos

    @property
    def vivo(self) -> bool:
        return self._hilo.vivo

    @property
    def canales(self) -> tuple[Canal, ...]:
        return tuple(self._canales)

    def foto(self) -> dict:
        """Para `estado/foto.json` (panel 4.4): tamaño de la cola y contadores."""
        return {"pendientes": self.pendientes, "perdidos": self._perdidos, "deduplicados": self._deduplicados,
                "enviados": self._enviados, "fallidos": self._fallidos, "despachados": self._despachados,
                "vivo": self.vivo, "canales": [canal.nombre for canal in self._canales]}

    # ── lado del hilo de envío ──
    def _al_caida(self, nombre: str, error: str, relanzado: bool) -> None:
        logger.error("[AVISOS] el hilo %s cayó (%s); relanzado=%s", nombre, error, relanzado)

    def _bucle(self) -> None:
        parando = self._hilo.parando
        while True:
            if parando.is_set() and self._cola.empty():
                return
            try:
                aviso = self._cola.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._despachar(aviso)
            except Exception:  # noqa: BLE001 — frontera de callback: un canal roto no mata el hilo ni se traga los avisos siguientes (R-J-08)
                logger.exception("[AVISOS] error inesperado despachando un aviso")
            finally:
                self._cola.task_done()
            if self._tope_avisado and self._cola.qsize() < self._cola.maxsize // 2:
                with self._cerrojo:
                    self._tope_avisado = False

    def _despachar(self, aviso: Aviso) -> None:
        """R-M-01: al log siempre; R-M-02: a cada canal que atiende (nivel, grupo)."""
        logger.log(_NIVEL_LOG[aviso.nivel], "[AVISO %d/%s] %s", int(aviso.nivel), aviso.grupo.value, aviso.texto)
        self._despachados += 1
        for canal in self._canales:
            if aviso.nivel not in canal.niveles or aviso.grupo not in canal.grupos:
                continue
            if self._enviar_con_reintentos(canal, aviso.texto):
                self._enviados += 1
            else:
                self._fallidos += 1

    def _enviar_con_reintentos(self, canal: Canal, texto: str) -> bool:
        """`1 + reintentos` intentos con `espera_reintento_s` entre ellos (R-J-08); parando → un intento y sin esperas."""
        intentos = 1 + self._reintentos
        parando = self._hilo.parando
        hechos = 0
        for intento in range(1, intentos + 1):
            hechos = intento
            try:
                if canal.enviar(texto):
                    if intento > 1:
                        logger.warning("[AVISOS] %s: enviado al intento %d", canal.nombre, intento)
                    return True
            except Exception as exc:  # noqa: BLE001 — frontera de callback: `Canal.enviar` promete no lanzar; si lo hace cuenta como intento fallido
                logger.warning("[AVISOS] %s lanzó %s: %s", canal.nombre, type(exc).__name__, exc)
            if parando.is_set():
                break
            if intento < intentos:
                parando.wait(self._espera_s)
        logger.error("[AVISOS] PERDIDO en %s tras %d intento(s): %s", canal.nombre, hechos, texto)
        return False


# ── construcción desde el entorno (R-Q-01: credenciales solo en el .env) ─
def _env(nombre: str) -> str:
    return os.environ.get(nombre, "").strip()


def canales_desde_env(cfg: Config) -> list[Canal]:
    """Canales con las credenciales del `.env`, leídas en la llamada (R-Q-01).

    TELEGRAM_BOT_TOKEN_B/TELEGRAM_CHAT_ID_B → grupo B, niveles 1-3 (si
    faltan: aviso por log y sin canal, para que los tests corran y el bot
    siga con el log, R-J-08). TELEGRAM_BOT_TOKEN_A/TELEGRAM_CHAT_ID_A →
    grupo A, nivel 1, SOLO si `cfg.alertas_grupo_a["activo"]` (R-M-05).
    SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASS/SMTP_TO → correo, niveles 2-3.
    SMS_PROVEEDOR → SMS nivel 3; «nulo» por defecto y también si el nombre no
    se conoce (R-M-02 pendiente). Telegram va primero: es el canal principal.
    """
    canales: list[Canal] = []
    token_b, chat_b = _env("TELEGRAM_BOT_TOKEN_B"), _env("TELEGRAM_CHAT_ID_B")
    if token_b and chat_b:
        canales.append(CanalTelegram(token_b, chat_b, Grupo.B, NIVELES_TODOS))
    else:
        logger.warning("[AVISOS] sin TELEGRAM_BOT_TOKEN_B/TELEGRAM_CHAT_ID_B: el grupo B queda solo en el log (R-J-08)")

    grupo_a = getattr(cfg, "alertas_grupo_a", None) or {}
    if bool(grupo_a.get("activo", False)):
        token_a, chat_a = _env("TELEGRAM_BOT_TOKEN_A"), _env("TELEGRAM_CHAT_ID_A")
        if token_a and chat_a:
            canales.append(CanalTelegram(token_a, chat_a, Grupo.A, NIVELES_GRUPO_A))
        else:
            logger.warning("[AVISOS] alertas_grupo_a.activo pero sin TELEGRAM_BOT_TOKEN_A/TELEGRAM_CHAT_ID_A: sin canal A")

    smtp_host, smtp_to, smtp_user = _env("SMTP_HOST"), _env("SMTP_TO"), _env("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS", "")
    if smtp_host and smtp_to and smtp_user and smtp_pass:
        puerto_texto = _env("SMTP_PORT") or str(SMTP_PUERTO_DEFECTO)
        if puerto_texto.isdigit() and 1 <= int(puerto_texto) <= 65535:
            canales.append(CanalCorreo(smtp_host, int(puerto_texto), smtp_user, smtp_pass, smtp_to))
        else:
            logger.warning("[AVISOS] SMTP_PORT inválido (%r): sin canal de correo", puerto_texto)
    elif smtp_host or smtp_to or smtp_user or smtp_pass:
        logger.warning("[AVISOS] configuración SMTP incompleta (hacen falta SMTP_HOST, SMTP_USER, SMTP_PASS y SMTP_TO): sin correo")

    proveedor = (_env("SMS_PROVEEDOR") or "nulo").lower()
    if proveedor != "nulo":
        logger.warning("[AVISOS] proveedor de SMS %r no implementado (R-M-02 pendiente): se usa el nulo", proveedor)
    canales.append(CanalSMS(ProveedorSMSNulo()))
    return canales


# ── textos ──────────────────────────────────────────────────────────────
def texto_grupo_a(eventos: list) -> list[str]:
    """R-M-05: el mismo formato que hoy para el socio; reutiliza `agrupar`/`formatear_grupo` del bot de alertas.

    SEG-05: el import es PEREZOSO. `bot_alerts_telegram` carga `httpx` (que
    registra la URL con el token): importar `avisos` —y con él el ejecutor, el
    vigilante, el supervisor y comprobar_das— no debe meter `httpx` en el
    proceso. Solo lo carga la primera señal del grupo A (una vez).
    """
    from app.services.bot_alerts_telegram import agrupar, formatear_grupo   # SEG-05: perezoso a propósito

    return [formatear_grupo(g) for g in agrupar(eventos)]


def texto_fill(lote: Lote, fill: Fill, cfg: Config, fase: Fase) -> str:
    """Aviso de fill del grupo B, con la fase delante (R-O-03) y el estado del lote tras el fill (R-M-01 nivel 1)."""
    estrategias = getattr(cfg, "estrategias", None) or {}
    estrategia = estrategias.get(lote.strategy_id)
    nombre = estrategia.name if estrategia is not None else (lote.estrategia or lote.strategy_id)
    lado = _LADO_LEGIBLE.get(fill.lado, fill.lado)
    simulado = " · <i>SIMULADO</i>" if fill.simulado else ""
    # Decisión 52 (Jaume 1-oct): la entrada TERMINADA con menos de lo pedido se dice «ENTRADA PARCIAL», con las que faltan
    parcial = lote.estado is not EstadoLote.ABRIENDO and 0 < lote.llenas < lote.pedidas
    cabeza = (f"⚠️ <b>ENTRADA PARCIAL</b>: {formatear_numero(lote.llenas, 0)} de {formatear_numero(lote.pedidas, 0)} "
              f"(faltan {formatear_numero(lote.pedidas - lote.llenas, 0)})" if parcial
              else f"Lote: {formatear_numero(lote.llenas, 0)}/{formatear_numero(lote.pedidas, 0)}")
    lineas = [
        f"{prefijo_fase(fase)} ✅ <b>FILL</b> <b>{escapar_html(fill.ticker)}</b> · {escapar_html(lado)} "
        f"<b>{formatear_numero(fill.qty, 0)}</b> @ <b>{formatear_precio(fill.precio)}</b>{simulado}",
        f"{cabeza} · "
        f"medio {formatear_precio(lote.precio_medio)} · 🔴 stop {formatear_precio(lote.nivel_stop)} · {escapar_html(lote.estado.value)}",
        f"<i>— {escapar_html(nombre)} · {escapar_html(lote.direccion)} · {escapar_html(fill.ruta)} · {escapar_html(fill.hora)} —</i>",
    ]
    return "\n".join(lineas)


def texto_rechazo(orden: Orden, notas: str, pos: PosicionTicker, fase: Optional[Fase] = None) -> str:
    """R-B-07 (1): SIEMPRE el texto LITERAL de DAS (`notes`), la orden que se intentó y el estado del ticker.

    C-04: NO es el texto que sale a Telegram. El aviso de un rechazo lo
    redacta `reglas.rechazos` (`_texto_aviso` / `tras_cancel_o_replace_rej`,
    literal de DAS escapado con `html.escape`, D2-08) dentro de las acciones
    de `rechazos.decidir`, y el decisor le pone la fase. Ese es el ÚNICO
    contrato vivo; esta función queda como formato de consulta (p. ej. para
    `/detalle` o herramientas) y ningún módulo del camino de órdenes la usa.
    """
    lado = _LADO_LEGIBLE.get(orden.lado.value, orden.lado.value)
    if orden.tipo is TipoOrden.MERCADO:
        precio = "a mercado"
    else:
        precio = f"@ {formatear_precio(orden.precio)}"
        if orden.stop is not None:
            precio = f"stop {formatear_precio(orden.stop)} · límite {formatear_precio(orden.precio)}"
    identificacion = f"token {orden.token}"
    if orden.id_das is not None:
        identificacion += f" · id {orden.id_das}"
    if orden.intentos:
        identificacion += f" · intento {orden.intentos}"
    ticker = f"Ticker: {escapar_html(pos.estado.value)}"
    if pos.motivo_estado:
        ticker += f" ({escapar_html(pos.motivo_estado)})"
    ticker += f" · neta {formatear_numero(pos.neta, 0)} · lotes {len(pos.lotes)}"
    if pos.intento is not None:
        ticker += (f" · entrada {escapar_html(pos.intento.fase.value)} "
                   f"({formatear_numero(pos.intento.llenas, 0)}/{formatear_numero(pos.intento.qty_total, 0)})")
    texto_notas = notas.strip() if notas else ""
    lineas = [
        f"⛔ <b>RECHAZO</b> <b>{escapar_html(orden.ticker)}</b> · {escapar_html(orden.proposito.value)}",
        f"DAS: «{escapar_html(texto_notas) if texto_notas else '(sin texto)'}»",
        f"Orden: {escapar_html(lado)} {formatear_numero(orden.qty, 0)} {escapar_html(orden.tipo.value)} {precio}"
        f" · ruta {escapar_html(orden.ruta)} · {identificacion}",
        ticker,
    ]
    texto = "\n".join(lineas)
    return con_prefijo_fase(texto, fase) if fase is not None else texto


# ── secretos en el log (R-Q-01, corrección 8, riesgo 20) ────────────────
class FiltroSecretos(logging.Filter):
    """Sustituye los VALORES literales de los secretos (y la forma URL `bot\\d+:…`) por «*****» en cada LogRecord.

    Se construye con los valores (longitud ≥ `SECRETO_LONGITUD_MIN`, vacíos ignorados; los más cortos se cuentan
    en `cortos`, SEG-04); actúa
    sobre `msg`, cada elemento de `args` (tupla, dict o escalar), la traza
    de la excepción y `stack_info`, sin cambiar la forma de `args` para no
    romper el formateo `%`. `limpiar` es la misma sustitución para texto
    suelto (el diario la recibe por inyección, ajuste (h)).
    """

    def __init__(self, secretos: Iterable[str]) -> None:
        super().__init__()
        valores = {str(s).strip() for s in secretos if s is not None}
        valores.discard("")
        self._secretos = tuple(sorted((v for v in valores if len(v) >= SECRETO_LONGITUD_MIN), key=len, reverse=True))
        self._cortos = sum(1 for v in valores if len(v) < SECRETO_LONGITUD_MIN)

    @property
    def secretos(self) -> tuple[str, ...]:
        return self._secretos

    @property
    def cortos(self) -> int:
        """SEG-04: cuántos secretos NO se pueden tapar por ser más cortos que `SECRETO_LONGITUD_MIN` (se avisa al arrancar)."""
        return self._cortos

    def limpiar(self, texto: str) -> str:
        """Texto con cada secreto (más largo primero) y la forma URL del token sustituidos por «*****»."""
        limpio = texto
        for secreto in self._secretos:
            limpio = limpio.replace(secreto, MASCARA)
        return PATRON_TOKEN_URL.sub(MASCARA, limpio)

    def _limpiar_valor(self, valor: Any) -> Any:
        if isinstance(valor, str):
            return self.limpiar(valor)
        if isinstance(valor, tuple):
            return tuple(self._limpiar_valor(v) for v in valor)
        if isinstance(valor, list):
            return [self._limpiar_valor(v) for v in valor]
        if isinstance(valor, dict):
            return {self._limpiar_valor(k): self._limpiar_valor(v) for k, v in valor.items()}
        texto = str(valor)
        limpio = self.limpiar(texto)
        return valor if limpio == texto else limpio

    def _tapa_un_no_str(self, valor: Any) -> bool:
        """¿Algún valor NO str (int, float, objeto) lleva un secreto en su texto? (C-03: taparlo cambiaría su tipo)."""
        if isinstance(valor, str):
            return False
        if isinstance(valor, (tuple, list)):
            return any(self._tapa_un_no_str(v) for v in valor)
        if isinstance(valor, dict):
            return any(self._tapa_un_no_str(k) or self._tapa_un_no_str(v) for k, v in valor.items())
        try:
            texto = str(valor)
        except Exception:  # noqa: BLE001 — frontera de formateo: un __str__ roto no tumba el log
            return False
        return self.limpiar(texto) != texto

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args and self._tapa_un_no_str(record.args):
            # C-03: un %d/%.2f que recibiera «*****» rompería el formateo y la línea se perdería.
            # Se formatea PRIMERO con los valores reales y se tapa el texto ya formateado.
            try:
                formateado = record.getMessage()
            except Exception:  # noqa: BLE001 — frontera de formateo: si ni siquiera formatea, sigue el camino de siempre
                formateado = None
            if formateado is not None:
                record.msg = self.limpiar(formateado)
                record.args = None
        if isinstance(record.msg, str):
            record.msg = self.limpiar(record.msg)
        else:
            record.msg = self._limpiar_valor(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {self._limpiar_valor(k): self._limpiar_valor(v) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self._limpiar_valor(v) for v in record.args)
            else:
                record.args = self._limpiar_valor(record.args)
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:                         # también si otro handler (sin filtro) ya la había formateado
            record.exc_text = self.limpiar(record.exc_text)
        if record.stack_info:
            record.stack_info = self.limpiar(record.stack_info)
        return True


def secretos_desde_env() -> list[str]:
    """Los valores PRESENTES de `VARIABLES_SECRETAS` (corrección 8), leídos en la llamada."""
    return [valor for valor in (os.environ.get(nombre, "").strip() for nombre in VARIABLES_SECRETAS) if valor]


class MemoriaLog(logging.Handler):
    """Últimas líneas formateadas en memoria (para `/log n`, R-M-04), ya filtradas."""

    def __init__(self, capacidad: int = MEMORIA_LOG_LINEAS) -> None:
        super().__init__()
        self._lineas: deque[str] = deque(maxlen=capacidad)
        self._cerrojo = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            linea = self.format(record)
        except Exception:  # noqa: BLE001 — frontera de formateo: un record raro no puede tumbar el logging
            self.handleError(record)
            return
        with self._cerrojo:
            self._lineas.append(linea)

    def lineas(self, n: int) -> list[str]:
        with self._cerrojo:
            todas = list(self._lineas)
        return todas[-n:] if n > 0 else []


class HandlerFicheroDiario(logging.FileHandler):
    """`logs/bot_das_{proceso}_AAAA-MM-DD.log`: cambia de fichero solo cuando cambia el día (ET) del reloj."""

    def __init__(self, directorio: Path, proceso: str, reloj=None) -> None:
        self._directorio = Path(directorio)
        self._proceso = proceso
        self._reloj = reloj if reloj is not None else Reloj()
        self._dia = self._reloj.hoy()
        super().__init__(ruta_log(self._directorio, proceso, self._dia), encoding="utf-8")

    @property
    def dia(self) -> date:
        return self._dia

    def emit(self, record: logging.LogRecord) -> None:
        dia = self._reloj.hoy()
        if dia != self._dia:
            self.acquire()
            try:
                if self.stream is not None:
                    self.stream.flush()
                    self.stream.close()
                    self.stream = None
                self._dia = dia
                self.baseFilename = os.fspath(ruta_log(self._directorio, self._proceso, dia).absolute())
                self.stream = self._open()
            finally:
                self.release()
        super().emit(record)


def ruta_log(directorio: Path, proceso: str, dia: date) -> Path:
    """Nombre del fichero de log de un proceso y un día (§1: `logs/bot_das_{proceso}_AAAA-MM-DD.log`)."""
    return Path(directorio) / f"bot_das_{proceso}_{dia.isoformat()}.log"


_FORMATO_LOG = "%(asctime)s.%(msecs)03d %(levelname)-7s %(name)s %(message)s"
_FECHA_LOG = "%H:%M:%S"
_ATRIBUTO_HANDLER = "bot_das_proceso"
_nivel_raiz_anterior: Optional[int] = None


def instalar_logging(proceso: str, directorio_logs: Path, secretos: Iterable[str], nivel: int = logging.INFO,
                     consola: bool = True, reloj=None) -> None:
    """Log por proceso y día con `FiltroSecretos` en TODOS los handlers (fichero, consola, memoria); `httpx`/`urllib3` a WARNING.

    Idempotente: una segunda llamada sustituye los handlers propios (marcados
    con `bot_das_proceso`) y respeta los ajenos (los de pytest, por ejemplo).
    """
    global _nivel_raiz_anterior
    directorio = Path(directorio_logs)
    directorio.mkdir(parents=True, exist_ok=True)
    filtro = FiltroSecretos(secretos)
    formato = logging.Formatter(_FORMATO_LOG, datefmt=_FECHA_LOG)
    raiz = logging.getLogger()
    desinstalar_logging()                   # primero: restaura el nivel de una instalación anterior...
    _nivel_raiz_anterior = raiz.level       # ...y después se guarda el nivel ORIGINAL para el próximo desinstalar
    handlers: list[logging.Handler] = [HandlerFicheroDiario(directorio, proceso, reloj), MemoriaLog()]
    if consola:
        handlers.append(logging.StreamHandler())
    for handler in handlers:
        handler.setFormatter(formato)
        handler.addFilter(filtro)
        setattr(handler, _ATRIBUTO_HANDLER, proceso)
        raiz.addHandler(handler)
    raiz.setLevel(nivel)
    for ruidoso in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)
    logger.info("[LOG] %s escribe en %s (%d secreto(s) tapados)", proceso, handlers[0].baseFilename, len(filtro.secretos))
    if filtro.cortos:                       # SEG-04: nunca el valor, solo cuántos
        logger.warning("[LOG] %d secreto(s) de menos de %d caracteres NO se pueden tapar en el log: "
                       "usa claves más largas", filtro.cortos, SECRETO_LONGITUD_MIN)


def desinstalar_logging() -> None:
    """Quita los handlers puestos por `instalar_logging` y restaura el nivel raíz (cierre ordenado y tests)."""
    global _nivel_raiz_anterior
    raiz = logging.getLogger()
    for handler in list(raiz.handlers):
        if hasattr(handler, _ATRIBUTO_HANDLER):
            raiz.removeHandler(handler)
            handler.close()
    if _nivel_raiz_anterior is not None:
        raiz.setLevel(_nivel_raiz_anterior)
        _nivel_raiz_anterior = None


def ultimas_lineas_log(n: int = 20) -> list[str]:
    """Las últimas `n` líneas del log en memoria (vacío si `instalar_logging` no se ha llamado)."""
    for handler in logging.getLogger().handlers:
        if isinstance(handler, MemoriaLog) and hasattr(handler, _ATRIBUTO_HANDLER):
            return handler.lineas(n)
    return []
