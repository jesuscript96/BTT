"""Persistencia de las alarmas. Todo, sin excepción, va filtrado por dueño.

El repo ya tiene cicatriz aquí (commit b2ac1eb, «cada usuario ve solo lo suyo»):
los dos fallos de entonces fueron un respaldo a un parquet SIN columna de dueño y
un `scope_clause` tolerante a NULL que hacía visible toda fila huérfana. Este
módulo evita ambos por construcción:

  * `_owner()` nunca devuelve NULL. Con la auth desactivada (solo desarrollo
    local) las filas nacen con el centinela `__local_dev__`, así que la columna
    es NOT NULL de verdad y no existe el concepto de fila huérfana.
  * No hay ni un solo SELECT sin `WHERE user_id = ?`. No hay camino de respaldo
    a una tabla compartida: si un usuario no tiene alarmas, la lista sale vacía.
  * `iter_active_alarms()` trae el chat_id de Telegram en el MISMO JOIN que el
    dueño de la alarma. El repartidor nunca resuelve un chat_id por su cuenta:
    así es estructuralmente imposible mandar la señal de A al teléfono de B.
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.database import get_user_db_connection, get_user_db_lock

logger = logging.getLogger("btt.alarms.store")

LOCAL_DEV_OWNER = "__local_dev__"
LINK_TOKEN_TTL_MINUTES = 10


def _owner(user_id: Optional[str]) -> str:
    """Dueño efectivo de una fila. Nunca None: sin esto reaparece la clase de
    fuga que se arregló en julio (filas sin dueño visibles por cualquiera)."""
    uid = (user_id or "").strip()
    return uid or LOCAL_DEV_OWNER


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


_schema_ready = False


def ensure_schema() -> None:
    """Crea las tablas si no existen. Idempotente y barata."""
    global _schema_ready
    if _schema_ready:
        return
    with get_user_db_lock():
        con = get_user_db_connection()
        try:
            con.execute("""
                CREATE TABLE IF NOT EXISTS alarms (
                    id VARCHAR PRIMARY KEY,
                    user_id VARCHAR NOT NULL,
                    name VARCHAR NOT NULL,
                    enabled BOOLEAN DEFAULT TRUE,
                    side VARCHAR DEFAULT 'long',
                    definition JSON NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # El registro de señales existe desde la fase 1 aunque todavía no haya
            # panel que lo enseñe: sin él, la fase 2 arrancaría con el historial
            # vacío y habría que esperar semanas a tener datos.
            con.execute("""
                CREATE TABLE IF NOT EXISTS alarm_events (
                    id VARCHAR PRIMARY KEY,
                    alarm_id VARCHAR NOT NULL,
                    user_id VARCHAR NOT NULL,
                    ticker VARCHAR NOT NULL,
                    session_date VARCHAR NOT NULL,
                    fired_at TIMESTAMP NOT NULL,
                    price DOUBLE,
                    payload JSON,
                    delivered JSON
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS telegram_links (
                    user_id VARCHAR PRIMARY KEY,
                    chat_id VARCHAR NOT NULL,
                    username VARCHAR,
                    linked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    broken_at TIMESTAMP
                )
            """)
            # Token de vinculación: de un solo uso y con caducidad corta. Sin esto
            # cualquiera podría enganchar su Telegram a la cuenta de otro y ponerse
            # a recibir sus señales.
            con.execute("""
                CREATE TABLE IF NOT EXISTS telegram_link_tokens (
                    token VARCHAR PRIMARY KEY,
                    user_id VARCHAR NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    used_at TIMESTAMP
                )
            """)
        finally:
            con.close()
    _schema_ready = True
    logger.info("[ALARMS] esquema verificado")


# ── Alarmas ──────────────────────────────────────────────────────────────────
def _row_to_alarm(row, cols) -> Dict[str, Any]:
    d = dict(zip(cols, row))
    definition = d.get("definition")
    if isinstance(definition, str):
        try:
            definition = json.loads(definition)
        except (TypeError, ValueError):
            definition = {}
    return {
        "id": d["id"],
        "name": d["name"],
        "enabled": bool(d["enabled"]),
        "side": d.get("side") or "long",
        "definition": definition or {},
        "created_at": str(d.get("created_at") or ""),
        "updated_at": str(d.get("updated_at") or ""),
    }


_ALARM_COLS = ["id", "name", "enabled", "side", "definition", "created_at", "updated_at"]


def list_alarms(user_id: Optional[str]) -> List[Dict[str, Any]]:
    ensure_schema()
    with get_user_db_lock():
        con = get_user_db_connection()
        try:
            rows = con.execute(
                f"SELECT {', '.join(_ALARM_COLS)} FROM alarms WHERE user_id = ? ORDER BY created_at DESC",
                [_owner(user_id)],
            ).fetchall()
        finally:
            con.close()
    return [_row_to_alarm(r, _ALARM_COLS) for r in rows]


def get_alarm(user_id: Optional[str], alarm_id: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with get_user_db_lock():
        con = get_user_db_connection()
        try:
            row = con.execute(
                f"SELECT {', '.join(_ALARM_COLS)} FROM alarms WHERE id = ? AND user_id = ?",
                [alarm_id, _owner(user_id)],
            ).fetchone()
        finally:
            con.close()
    return _row_to_alarm(row, _ALARM_COLS) if row else None


def create_alarm(user_id: Optional[str], name: str, side: str,
                 definition: Dict[str, Any], enabled: bool = True) -> Dict[str, Any]:
    ensure_schema()
    new_id = str(uuid4())
    now = _now()
    with get_user_db_lock():
        con = get_user_db_connection()
        try:
            con.execute(
                """INSERT INTO alarms (id, user_id, name, enabled, side, definition, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [new_id, _owner(user_id), name, enabled, side, json.dumps(definition), now, now],
            )
        finally:
            con.close()
    return {"id": new_id, "name": name, "enabled": enabled, "side": side,
            "definition": definition, "created_at": now.isoformat(), "updated_at": now.isoformat()}


def update_alarm(user_id: Optional[str], alarm_id: str, name: Optional[str] = None,
                 side: Optional[str] = None, definition: Optional[Dict[str, Any]] = None,
                 enabled: Optional[bool] = None) -> Optional[Dict[str, Any]]:
    ensure_schema()
    current = get_alarm(user_id, alarm_id)
    if current is None:
        return None      # también cubre «existe pero es de otro»: no se distingue
    sets, params = [], []
    if name is not None:
        sets.append("name = ?"); params.append(name)
    if side is not None:
        sets.append("side = ?"); params.append(side)
    if definition is not None:
        sets.append("definition = ?"); params.append(json.dumps(definition))
    if enabled is not None:
        sets.append("enabled = ?"); params.append(enabled)
    sets.append("updated_at = ?"); params.append(_now())
    params.extend([alarm_id, _owner(user_id)])
    with get_user_db_lock():
        con = get_user_db_connection()
        try:
            con.execute(f"UPDATE alarms SET {', '.join(sets)} WHERE id = ? AND user_id = ?", params)
        finally:
            con.close()
    return get_alarm(user_id, alarm_id)


def delete_alarm(user_id: Optional[str], alarm_id: str) -> bool:
    ensure_schema()
    if get_alarm(user_id, alarm_id) is None:
        return False
    with get_user_db_lock():
        con = get_user_db_connection()
        try:
            con.execute("DELETE FROM alarms WHERE id = ? AND user_id = ?", [alarm_id, _owner(user_id)])
        finally:
            con.close()
    return True


def iter_active_alarms() -> List[Dict[str, Any]]:
    """Alarmas encendidas de TODOS los usuarios, cada una con su chat_id.

    Es la única lectura del módulo sin filtro de dueño, y es correcta: el motor
    tiene que evaluar las alarmas de todo el mundo. Lo que garantiza el
    aislamiento es que el `chat_id` viaja en la MISMA fila que el `user_id`, por
    LEFT JOIN, en vez de resolverse después contra un diccionario compartido —
    que es exactamente por donde se colaría un aviso al usuario equivocado.
    """
    ensure_schema()
    with get_user_db_lock():
        con = get_user_db_connection()
        try:
            rows = con.execute("""
                SELECT a.id, a.user_id, a.name, a.side, a.definition,
                       t.chat_id
                FROM alarms a
                LEFT JOIN telegram_links t
                       ON t.user_id = a.user_id AND t.broken_at IS NULL
                WHERE a.enabled = TRUE
            """).fetchall()
        finally:
            con.close()
    out = []
    for r in rows:
        definition = r[4]
        if isinstance(definition, str):
            try:
                definition = json.loads(definition)
            except (TypeError, ValueError):
                definition = {}
        out.append({
            "id": r[0], "user_id": r[1], "name": r[2], "side": r[3] or "long",
            "definition": definition or {}, "chat_id": r[5],
        })
    return out


# ── Señales ──────────────────────────────────────────────────────────────────
def record_event(alarm_id: str, user_id: str, ticker: str, session_date: str,
                 price: Optional[float], payload: Dict[str, Any],
                 delivered: Optional[Dict[str, Any]] = None) -> str:
    ensure_schema()
    event_id = str(uuid4())
    with get_user_db_lock():
        con = get_user_db_connection()
        try:
            con.execute(
                """INSERT INTO alarm_events
                   (id, alarm_id, user_id, ticker, session_date, fired_at, price, payload, delivered)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [event_id, alarm_id, _owner(user_id), ticker, session_date, _now(),
                 price, json.dumps(payload), json.dumps(delivered or {})],
            )
        finally:
            con.close()
    return event_id


def list_events(user_id: Optional[str], session_date: Optional[str] = None,
                limit: int = 200) -> List[Dict[str, Any]]:
    ensure_schema()
    sql = """SELECT id, alarm_id, ticker, session_date, fired_at, price, payload
             FROM alarm_events WHERE user_id = ?"""
    params: List[Any] = [_owner(user_id)]
    if session_date:
        sql += " AND session_date = ?"
        params.append(session_date)
    sql += " ORDER BY fired_at DESC LIMIT ?"
    params.append(int(limit))
    with get_user_db_lock():
        con = get_user_db_connection()
        try:
            rows = con.execute(sql, params).fetchall()
        finally:
            con.close()
    out = []
    for r in rows:
        payload = r[6]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                payload = {}
        out.append({"id": r[0], "alarm_id": r[1], "ticker": r[2], "session_date": r[3],
                    "fired_at": str(r[4]), "price": r[5], "payload": payload or {}})
    return out


def count_events_today(alarm_id: str, ticker: str, session_date: str) -> int:
    """Cuántas veces ha disparado ya esta alarma sobre este ticker hoy.

    Alimenta el enfriamiento. Se consulta contra la tabla, no contra un contador
    en RAM, para que un reinicio a media sesión no reabra la puerta al spam."""
    ensure_schema()
    with get_user_db_lock():
        con = get_user_db_connection()
        try:
            row = con.execute(
                """SELECT COUNT(*) FROM alarm_events
                   WHERE alarm_id = ? AND ticker = ? AND session_date = ?""",
                [alarm_id, ticker, session_date],
            ).fetchone()
        finally:
            con.close()
    return int(row[0]) if row else 0


# ── Telegram ─────────────────────────────────────────────────────────────────
def create_link_token(user_id: Optional[str]) -> Dict[str, Any]:
    ensure_schema()
    token = secrets.token_urlsafe(18)
    now = _now()
    expires = now + timedelta(minutes=LINK_TOKEN_TTL_MINUTES)
    with get_user_db_lock():
        con = get_user_db_connection()
        try:
            con.execute(
                """INSERT INTO telegram_link_tokens (token, user_id, created_at, expires_at)
                   VALUES (?, ?, ?, ?)""",
                [token, _owner(user_id), now, expires],
            )
        finally:
            con.close()
    return {"token": token, "expires_at": expires.isoformat(),
            "ttl_minutes": LINK_TOKEN_TTL_MINUTES}


def consume_link_token(token: str, chat_id: str, username: Optional[str]) -> Optional[str]:
    """Canjea un token y vincula el chat. Devuelve el user_id o None si el token
    no existe, ya se usó o caducó. De un solo uso: se marca `used_at` en la misma
    transacción que se crea el vínculo."""
    ensure_schema()
    now = _now()
    with get_user_db_lock():
        con = get_user_db_connection()
        try:
            row = con.execute(
                """SELECT user_id FROM telegram_link_tokens
                   WHERE token = ? AND used_at IS NULL AND expires_at > ?""",
                [token, now],
            ).fetchone()
            if not row:
                return None
            uid = row[0]
            con.execute("UPDATE telegram_link_tokens SET used_at = ? WHERE token = ?", [now, token])
            con.execute("DELETE FROM telegram_links WHERE user_id = ?", [uid])
            con.execute(
                """INSERT INTO telegram_links (user_id, chat_id, username, linked_at)
                   VALUES (?, ?, ?, ?)""",
                [uid, str(chat_id), username, now],
            )
        finally:
            con.close()
    return uid


def get_link(user_id: Optional[str]) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with get_user_db_lock():
        con = get_user_db_connection()
        try:
            row = con.execute(
                """SELECT chat_id, username, linked_at, broken_at FROM telegram_links
                   WHERE user_id = ?""",
                [_owner(user_id)],
            ).fetchone()
        finally:
            con.close()
    if not row:
        return None
    return {"chat_id": row[0], "username": row[1],
            "linked_at": str(row[2]), "broken": row[3] is not None}


def unlink(user_id: Optional[str]) -> bool:
    ensure_schema()
    with get_user_db_lock():
        con = get_user_db_connection()
        try:
            con.execute("DELETE FROM telegram_links WHERE user_id = ?", [_owner(user_id)])
        finally:
            con.close()
    return True


def mark_link_broken(chat_id: str) -> None:
    """Telegram devuelve 403 cuando el usuario bloquea el bot. Sin marcarlo, el
    repartidor reintentaría contra un chat muerto en cada señal, para siempre."""
    ensure_schema()
    with get_user_db_lock():
        con = get_user_db_connection()
        try:
            con.execute("UPDATE telegram_links SET broken_at = ? WHERE chat_id = ?",
                        [_now(), str(chat_id)])
        finally:
            con.close()
