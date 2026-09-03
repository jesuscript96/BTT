"""Cliente del bot de Telegram: vinculación de cuentas y reparto de avisos.

Por qué la vinculación va por deep-link y no por «déjame tu @usuario»: un bot de
Telegram SOLO puede escribir a quien le haya escrito primero. Es su diseño
anti-spam, no una limitación rodeable. Hace falta el `chat_id` numérico, y ese
número solo existe después de que la persona pulse START. Guardar un @usuario no
sirve absolutamente de nada.

Flujo: el usuario abre `t.me/<bot>?start=<token>`, Telegram nos manda el update
con el `chat_id` y ese token, y canjeamos. El token es de un solo uso y caduca en
minutos (ver store.consume_link_token).

Se usa long-polling en vez de webhook a propósito: el webhook exige una URL
pública con TLS, que en local no existe. El polling funciona igual en desarrollo
y en producción, y el volumen de updates de este bot es ridículo.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional

import httpx

from . import store

logger = logging.getLogger("btt.alarms.telegram")

API_BASE = "https://api.telegram.org"
# Límite documentado de Telegram: ~30 mensajes/segundo en total y ~1/segundo por
# chat. Con un puñado de avisos por usuario y día no nos acercamos, pero un bug
# de bucle sí lo haría, así que el throttle está puesto como cinturón.
MIN_SECONDS_BETWEEN_MESSAGES_PER_CHAT = 1.0

_last_sent: Dict[str, float] = {}


def bot_token() -> str:
    return (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()


def is_configured() -> bool:
    return bool(bot_token())


def _url(method: str) -> str:
    return f"{API_BASE}/bot{bot_token()}/{method}"


async def get_me() -> Optional[Dict[str, Any]]:
    if not is_configured():
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(_url("getMe"))
            data = r.json()
        return data.get("result") if data.get("ok") else None
    except Exception as e:  # noqa: BLE001
        logger.warning("[TG] getMe falló: %s", e)
        return None


_bot_username_cache: Optional[str] = None


async def bot_username() -> Optional[str]:
    global _bot_username_cache
    if _bot_username_cache:
        return _bot_username_cache
    me = await get_me()
    if me:
        _bot_username_cache = me.get("username")
    return _bot_username_cache


async def send_message(chat_id: str, text: str,
                       buttons: Optional[list] = None) -> bool:
    """Envía un mensaje. Devuelve True si Telegram lo aceptó.

    Un 403 significa que el usuario bloqueó el bot: se marca el vínculo como roto
    para no reintentar en cada señal contra un chat muerto."""
    if not is_configured() or not chat_id:
        return False
    chat_id = str(chat_id)

    # Throttle por chat.
    last = _last_sent.get(chat_id, 0.0)
    wait = MIN_SECONDS_BETWEEN_MESSAGES_PER_CHAT - (time.monotonic() - last)
    if wait > 0:
        await asyncio.sleep(wait)
    _last_sent[chat_id] = time.monotonic()

    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(_url("sendMessage"), json=payload)
        if r.status_code == 403:
            logger.info("[TG] chat %s bloqueó el bot; vínculo marcado como roto", chat_id)
            await asyncio.to_thread(store.mark_link_broken, chat_id)
            return False
        if r.status_code >= 400:
            logger.warning("[TG] sendMessage %s: %s", r.status_code, r.text[:200])
            return False
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("[TG] sendMessage falló: %s", e)
        return False


async def deep_link(token: str) -> Optional[str]:
    user = await bot_username()
    if not user:
        return None
    return f"https://t.me/{user}?start={token}"


# ── Long-polling de updates (solo para /start <token>) ───────────────────────
class UpdatePoller:
    """Escucha updates del bot. Lo único que le interesa es `/start <token>`
    para cerrar la vinculación; el resto se ignora."""

    def __init__(self) -> None:
        self._offset: Optional[int] = None
        self._stop = False

    async def run(self) -> None:
        if not is_configured():
            logger.info("[TG] sin TELEGRAM_BOT_TOKEN; el poller no arranca")
            return
        me = await get_me()
        if not me:
            logger.warning("[TG] token presente pero getMe falla; el poller no arranca")
            return
        logger.info("[TG] poller arrancado como @%s", me.get("username"))
        backoff = 1.0
        while not self._stop:
            try:
                updates = await self._get_updates()
                backoff = 1.0
                for u in updates:
                    await self._handle(u)
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                logger.warning("[TG] poller error (%s); reintento en %.0fs", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def stop(self) -> None:
        self._stop = True

    async def _get_updates(self) -> list:
        params: Dict[str, Any] = {"timeout": 25, "allowed_updates": '["message"]'}
        if self._offset is not None:
            params["offset"] = self._offset
        async with httpx.AsyncClient(timeout=40.0) as client:
            r = await client.get(_url("getUpdates"), params=params)
            data = r.json()
        if not data.get("ok"):
            return []
        results = data.get("result") or []
        if results:
            self._offset = results[-1]["update_id"] + 1
        return results

    async def _handle(self, update: Dict[str, Any]) -> None:
        msg = update.get("message") or {}
        text = (msg.get("text") or "").strip()
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        if not chat_id or not text.startswith("/start"):
            return
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await send_message(str(chat_id),
                               "Para conectar tu cuenta, abre el enlace desde "
                               "<b>Alarmas → Conectar Telegram</b> en Edgecute.")
            return
        token = parts[1].strip()
        username = (chat.get("username") or msg.get("from", {}).get("username"))
        uid = await asyncio.to_thread(store.consume_link_token, token, str(chat_id), username)
        if uid:
            # Vincular es raro y caro de rehacer (el usuario tendría que volver a
            # pulsar Start), así que se sube ya, sin esperar al throttle.
            await asyncio.to_thread(store.sync_to_gcs, True)
            await send_message(str(chat_id),
                               "✅ <b>Telegram conectado.</b>\n"
                               "A partir de ahora recibirás aquí los avisos de tus alarmas.")
            logger.info("[TG] chat vinculado para user_id=%s", uid)
        else:
            await send_message(str(chat_id),
                               "❌ Ese enlace ya se usó o ha caducado. "
                               "Genera uno nuevo desde <b>Alarmas → Conectar Telegram</b>.")


poller = UpdatePoller()
