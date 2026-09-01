"""Envio de los avisos del bot a Telegram.

CREDENCIALES POR ENTORNO, nunca en el codigo:
    TELEGRAM_BOT_TOKEN   token del bot (el de BotFather)
    TELEGRAM_CHAT_ID     id del grupo donde se avisa

INTERRUPTOR APARTE del resto del bot:
    BOT_ALERTS_TELEGRAM  'true' para enviar de verdad; apagado por defecto.

Sin el interruptor NO SE ENVIA NADA: se formatea el mensaje y se deja en el log.
Asi se puede probar el bot un dia entero sin llenarle el grupo a nadie, que es
justo lo que hace falta mientras se ajusta.

DOS COSAS DE TELEGRAM QUE SORPRENDEN:
  * un bot no puede escribir a quien no le haya dado a "Start" antes; en un
    grupo, hay que anyadirlo al grupo primero;
  * el `chat_id` de un grupo es NEGATIVO (empieza por -100 en los supergrupos).
    Si se copia sin el signo, la API responde "chat not found".
"""
from __future__ import annotations

import logging
import os
import ssl
from typing import TYPE_CHECKING, Iterable

import httpx

if TYPE_CHECKING:  # evita el import circular en tiempo de ejecucion
    from app.services.bot_alerts_engine import Evento

logger = logging.getLogger("btt.bot_alerts.telegram")

API = "https://api.telegram.org"
TIMEOUT = 10.0


def _verify():
    """Contexto SSL para hablar con Telegram.

    USA EL ALMACEN DE CERTIFICADOS DE WINDOWS, no `certifi`. En esta maquina
    Avast intercepta el trafico HTTPS y reemplaza el certificado del servidor
    por uno firmado por «Avast Web/Mail Shield Root». `certifi` no conoce esa
    autoridad y rechaza la conexion con CERTIFICATE_VERIFY_FAILED; el almacen de
    Windows si la conoce, porque el propio antivirus la instalo ahi.

    Funciona igual sin antivirus de por medio: el almacen del sistema trae
    tambien las autoridades publicas de siempre.
    """
    try:
        ctx = ssl.create_default_context()
        ctx.load_default_certs(ssl.Purpose.SERVER_AUTH)
        return ctx
    except Exception:  # noqa: BLE001
        try:
            import certifi
            return certifi.where()
        except Exception:  # noqa: BLE001
            return True


def _cfg() -> tuple[str, str]:
    return (
        os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        os.getenv("TELEGRAM_CHAT_ID", "").strip(),
    )


def envio_activo() -> bool:
    """Si los avisos salen de verdad hacia Telegram."""
    if os.getenv("BOT_ALERTS_TELEGRAM", "false").strip().lower() not in ("1", "true", "yes", "on"):
        return False
    token, chat = _cfg()
    return bool(token and chat)


def motivo_inactivo() -> str:
    """Por que no se esta enviando, para poder decirlo en pantalla."""
    if os.getenv("BOT_ALERTS_TELEGRAM", "false").strip().lower() not in ("1", "true", "yes", "on"):
        return "BOT_ALERTS_TELEGRAM no esta activado"
    token, chat = _cfg()
    if not token:
        return "falta TELEGRAM_BOT_TOKEN"
    if not chat:
        return "falta TELEGRAM_CHAT_ID"
    return ""


def _esc(t: Any) -> str:
    """Escapa lo que va dentro del HTML de Telegram."""
    return (str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _num(v: float | None, dec: int = 4) -> str:
    """Numero en formato espanyol: miles con punto, decimales con coma."""
    if v is None:
        return "—"
    s = f"{v:,.{dec}f}"
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def formatear(ev: "Evento") -> str:
    """El texto del aviso, en HTML de Telegram.

    SOBRE EL COLOR: Telegram no permite colorear texto — solo negrita, cursiva,
    subrayado, tachado, monoespaciado y enlaces. Para que el stop y el riesgo
    canten a simple vista se usan emojis de color como marca de linea, que es lo
    mas parecido que existe.

    Lleva SIEMPRE stop y riesgo, no solo las acciones: si el precio se ha movido
    desde el aviso, con esos dos numeros se rehace la cuenta. El numero al precio
    del momento vive en el cuadro de mandos, que lo recalcula solo.
    """
    hora = str(ev.momento)[11:16]
    largo = (ev.direccion or "").lower().startswith("long")
    lado = "LONG" if largo else "SHORT"
    tk = _esc(ev.ticker)
    est = _esc(ev.estrategia or "")

    if ev.tipo == "entrada":
        icono = "🔺" if largo else "🔻"
        lineas = [
            f"{icono} <b>Ticker:</b> {tk}  ({lado})",
            "",
            f"Precio: <b>{_num(ev.precio)}</b>",
            f"Acciones: <b>{_num(ev.acciones, 0)}</b>",
        ]
        if ev.stop is not None:
            lineas.append(f"🔴 Stop: {_num(ev.stop)}")
        if ev.riesgo_usd is not None:
            lineas.append(f"🟠 Riesgo: {_num(ev.riesgo_usd, 0)}")
        lineas += ["", f"<i>— {est} · {hora} —</i>"]
        return "\n".join(lineas)

    if ev.tipo == "piramide":
        reduce = ev.accion_piramide == "reduce"
        icono = "➖" if reduce else "➕"
        verbo = "REDUCIR" if reduce else "AÑADIR"
        lineas = [
            f"{icono} <b>Ticker:</b> {tk}  ({verbo})",
            "",
            f"Precio: <b>{_num(ev.precio)}</b>",
            f"Acciones: <b>{_num(ev.acciones, 0)}</b>",
        ]
        if ev.posicion_total is not None:
            # Entre parentesis y debajo de las acciones: lo que se teclea en el
            # broker es el anyadido, no el total. El total es contexto — sirve
            # para comprobar que la posicion cuadra, no para operar con el.
            lineas.append(f"<i>(posición total: {_num(ev.posicion_total, 0)})</i>")
        lineas += ["", f"<i>— {est} · {hora} —</i>"]
        return "\n".join(lineas)

    # Salida: el MISMO icono para todos los cierres, salte el stop o llegue el
    # objetivo. Distinguirlos con iconos de alarma (🛑) hacia parecer un problema
    # lo que es una orden mas que meter; el motivo ya lo dice la linea de abajo.
    return "\n".join([
        f"✅ <b>Ticker:</b> {tk}  (CIERRE POS.)",
        "",
        f"Precio: <b>{_num(ev.precio)}</b>",
        f"⚫ Motivo: {_esc(ev.motivo or '?')}",
        "",
        f"<i>— {est} · {hora} —</i>",
    ])


def enviar_texto(texto: str) -> bool:
    """Manda un mensaje. Devuelve si salio de verdad.

    Nunca lanza: un fallo de red no puede tumbar el bot ni hacerle perder la
    vela siguiente. Si falla, queda en el log y el aviso sigue estando en el
    cuadro de mandos.
    """
    if not envio_activo():
        logger.info("[TELEGRAM] (no enviado: %s)\n%s", motivo_inactivo(), texto)
        return False
    token, chat = _cfg()
    try:
        r = httpx.post(
            f"{API}/bot{token}/sendMessage",
            json={
                "chat_id": chat, "text": texto,
                # HTML y no Markdown: en Markdown un ticker con guion bajo
                # (o un guion suelto) rompe el mensaje entero.
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=TIMEOUT, verify=_verify(),
        )
        if r.status_code != 200:
            logger.warning("[TELEGRAM] rechazado (%s): %s", r.status_code, r.text[:300])
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("[TELEGRAM] fallo de envio: %s", exc)
        return False


def enviar_eventos(eventos: Iterable["Evento"]) -> int:
    """Manda una tanda de avisos. Devuelve cuantos salieron."""
    return sum(1 for ev in eventos if enviar_texto(formatear(ev)))


def probar() -> dict:
    """Comprueba la configuracion sin mandar nada al grupo.

    Usa getMe, que solo valida el token. Para saber si el bot puede escribir en
    el grupo hace falta un envio real — eso lo decide el usuario.
    """
    token, chat = _cfg()
    if not token:
        return {"ok": False, "detalle": "falta TELEGRAM_BOT_TOKEN"}
    try:
        r = httpx.get(f"{API}/bot{token}/getMe", timeout=TIMEOUT, verify=_verify())
        if r.status_code != 200:
            return {"ok": False, "detalle": f"token rechazado ({r.status_code})"}
        nombre = (r.json().get("result") or {}).get("username")
        return {
            "ok": True,
            "bot": nombre,
            "chat_id": chat or "(sin configurar)",
            "enviando": envio_activo(),
            "detalle": motivo_inactivo() or "listo",
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detalle": f"error de red: {exc}"}
