"""AI Gateway for the Edgie assistant.

Proxies chat completions to the LLM provider (DeepSeek today) so the API key
lives server-side, supports native function calling (tools) and streams the
provider's SSE chunks straight through to the browser.

See docs/plan_asistente_edgie.md and docs/assistant/arquitectura.md.
"""

import json
import logging
import os
import re
import time
from datetime import date as _date
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/assistant", tags=["Assistant"])

logger = logging.getLogger("assistant")

PROVIDER_BASE = os.environ.get("ASSISTANT_PROVIDER_BASE", "https://api.deepseek.com")
DEFAULT_MODEL = os.environ.get("ASSISTANT_MODEL", "deepseek-chat")
# Hard caps so a runaway client can't blow up provider costs.
MAX_MESSAGES = 60
MAX_TOOLS = 40


class ChatRequest(BaseModel):
    messages: list[dict[str, Any]] = Field(..., description="OpenAI-format message list (system/user/assistant/tool)")
    tools: Optional[list[dict[str, Any]]] = Field(None, description="OpenAI-format tool definitions for function calling")
    temperature: float = 0.2
    stream: bool = True
    model: Optional[str] = None
    page: Optional[str] = Field(None, description="Frontend route that originated the request (telemetry)")


def _resolve_api_key(request: Request) -> str:
    """Server-side key first; transitional fallback to a client-supplied key.

    The fallback keeps dev environments working until DEEPSEEK_API_KEY is set
    on the server. Remove the header path once all environments are migrated.
    """
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        key = (request.headers.get("x-assistant-key") or "").strip()
    if not key:
        raise HTTPException(
            status_code=503,
            detail="NO_KEY: configura DEEPSEEK_API_KEY en el servidor o aporta una clave en los ajustes del asistente.",
        )
    return key


def _build_payload(req: ChatRequest) -> dict[str, Any]:
    if not req.messages:
        raise HTTPException(status_code=422, detail="messages no puede estar vacío")
    if len(req.messages) > MAX_MESSAGES:
        raise HTTPException(status_code=422, detail=f"demasiados mensajes (máx {MAX_MESSAGES})")
    if req.tools and len(req.tools) > MAX_TOOLS:
        raise HTTPException(status_code=422, detail=f"demasiadas tools (máx {MAX_TOOLS})")

    payload: dict[str, Any] = {
        "model": req.model or DEFAULT_MODEL,
        "messages": req.messages,
        "temperature": req.temperature,
        "stream": req.stream,
    }
    if req.tools:
        payload["tools"] = req.tools
        payload["tool_choice"] = "auto"
    return payload


def _log_usage(page: Optional[str], model: str, usage: Optional[dict], elapsed: float) -> None:
    if usage:
        logger.info(
            "[ASSISTANT] page=%s model=%s prompt_tokens=%s completion_tokens=%s elapsed=%.2fs",
            page, model, usage.get("prompt_tokens"), usage.get("completion_tokens"), elapsed,
        )
    else:
        logger.info("[ASSISTANT] page=%s model=%s (stream, usage no reportado) elapsed=%.2fs", page, model, elapsed)


@router.post("/chat")
async def chat(req: ChatRequest, request: Request):
    """Chat completion proxy. stream=true → SSE passthrough; stream=false → JSON."""
    api_key = _resolve_api_key(request)
    payload = _build_payload(req)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    url = f"{PROVIDER_BASE}/chat/completions"
    started = time.time()

    if not req.stream:
        async with httpx.AsyncClient(timeout=180.0) as client:
            try:
                resp = await client.post(url, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                raise HTTPException(status_code=502, detail=f"Error de red hacia el proveedor LLM: {exc}")
        if resp.status_code != 200:
            detail = resp.text[:500]
            try:
                detail = resp.json().get("error", {}).get("message", detail)
            except Exception:
                pass
            raise HTTPException(status_code=resp.status_code, detail=detail)
        data = resp.json()
        _log_usage(req.page, payload["model"], data.get("usage"), time.time() - started)
        return JSONResponse(data)

    async def event_stream():
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=15.0)) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    if resp.status_code != 200:
                        body = (await resp.aread()).decode("utf-8", errors="replace")
                        try:
                            msg = json.loads(body).get("error", {}).get("message", body[:300])
                        except Exception:
                            msg = body[:300]
                        yield f"data: {json.dumps({'error': {'status': resp.status_code, 'message': msg}})}\n\n"
                        yield "data: [DONE]\n\n"
                        return
                    # Passthrough: upstream is already OpenAI-format SSE
                    # ("data: {...}" lines separated by blank lines).
                    async for line in resp.aiter_lines():
                        yield line + "\n"
        except httpx.HTTPError as exc:
            yield f"data: {json.dumps({'error': {'status': 502, 'message': f'Error de red hacia el proveedor LLM: {exc}'}})}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            _log_usage(req.page, payload["model"], None, time.time() - started)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Registro de bancos dilusores ─────────────────────────────────────────────
# Edgie devuelve `hired_banks` dentro del bloque <edgie_metrics>. Persistimos
# esos nombres en DuckDB para, en análisis futuros, elevar el rating de riesgo
# cuando un banco con historial dilusor reaparece. Ver docs/dilution-runner-assessment/.

# Sufijos corporativos redundantes que eliminamos para evitar duplicados del
# tipo "H.C. WAINWRIGHT & CO. LLC" vs "H.C. WAINWRIGHT".
_BANK_SUFFIXES = {"CO", "LLC", "INC", "LP", "LTD", "PLC", "LLP", "CORP"}


def normalize_bank_name(raw: str) -> str:
    """Normaliza el nombre de un banco para deduplicar en BD.

    Pasa a mayúsculas, elimina puntuación/símbolos y recorta sufijos
    corporativos redundantes del final. Devuelve "" si queda vacío.
    """
    if not raw or not isinstance(raw, str):
        return ""
    # Quitar puntuación y "&"; colapsar espacios.
    cleaned = re.sub(r"[.,&]", " ", raw.upper())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    tokens = cleaned.split(" ")
    # Recortar sufijos corporativos por el final (manteniendo al menos 1 token).
    while len(tokens) > 1 and tokens[-1] in _BANK_SUFFIXES:
        tokens.pop()
    return " ".join(tokens).strip()


def extract_edgie_metrics(content: str) -> Optional[dict]:
    """Extrae y parsea el JSON dentro de <edgie_metrics>...</edgie_metrics>."""
    if not content:
        return None
    match = re.search(r"<edgie_metrics>([\s\S]*?)</edgie_metrics>", content)
    if not match:
        return None
    try:
        return json.loads(match.group(1).strip())
    except Exception as exc:
        logger.warning("[ASSISTANT] no se pudo parsear edgie_metrics: %s", exc)
        return None


# DDL idempotente: garantiza la tabla exista en users.duckdb antes de leer/escribir.
# init_db la crea al arrancar, pero con DB_PROVIDER=gcs la init solo afecta a la
# conexión en memoria; esto la asegura también en el fichero que aquí usamos.
_DILUTION_BANKS_DDL = """
CREATE TABLE IF NOT EXISTS dilution_banks_registry (
    ticker VARCHAR NOT NULL,
    bank_name VARCHAR NOT NULL,
    form_type VARCHAR,
    date_filed DATE,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""


def get_known_dilution_banks(ticker: str, limit: int = 10) -> list[dict]:
    """Devuelve los bancos dilusores más frecuentes (conteo de tickers distintos),
    marcando si ya aparecieron antes para este ticker. Tolerante a fallos: si la
    BD no está disponible devuelve [] sin romper el análisis."""
    try:
        from app.database import get_user_db_connection, get_user_db_lock
        with get_user_db_lock():
            con = get_user_db_connection()
            con.execute(_DILUTION_BANKS_DDL)
            rows = con.execute(
                """
                SELECT bank_name,
                       COUNT(DISTINCT ticker) AS ticker_count,
                       MAX(CASE WHEN ticker = ? THEN 1 ELSE 0 END) AS seen_here
                FROM dilution_banks_registry
                GROUP BY bank_name
                ORDER BY ticker_count DESC
                LIMIT ?
                """,
                [ticker.upper(), limit],
            ).fetchall()
        return [
            {"bank_name": r[0], "ticker_count": int(r[1]), "seen_here": bool(r[2])}
            for r in rows
        ]
    except Exception as exc:
        logger.warning("[ASSISTANT] no se pudo leer dilution_banks_registry: %s", exc)
        return []


def register_dilution_banks(ticker: str, banks: list[str]) -> int:
    """Inserta bancos nuevos para el ticker (dedupe por ticker+bank_name).
    Devuelve cuántas filas nuevas se insertaron. Tolerante a fallos."""
    ticker = (ticker or "").upper().strip()
    if not ticker or not banks:
        return 0
    inserted = 0
    try:
        from app.database import get_user_db_connection, get_user_db_lock
        with get_user_db_lock():
            con = get_user_db_connection()
            con.execute(_DILUTION_BANKS_DDL)
            for raw in banks:
                name = normalize_bank_name(raw)
                if not name:
                    continue
                exists = con.execute(
                    "SELECT 1 FROM dilution_banks_registry WHERE ticker = ? AND bank_name = ? LIMIT 1",
                    [ticker, name],
                ).fetchone()
                if exists:
                    continue
                con.execute(
                    "INSERT INTO dilution_banks_registry (ticker, bank_name, form_type, date_filed) "
                    "VALUES (?, ?, ?, ?)",
                    [ticker, name, None, _date.today()],
                )
                inserted += 1
    except Exception as exc:
        logger.warning("[ASSISTANT] no se pudo registrar bancos dilusores: %s", exc)
    return inserted


class DilutionReportRequest(ChatRequest):
    ticker: str = Field(..., description="Símbolo del ticker analizado (ej: MULN)")


@router.post("/dilution-report")
async def dilution_report(req: DilutionReportRequest, request: Request):
    """Reporte de dilución (no-streaming) con memoria de bancos dilusores.

    Antes de llamar al LLM inyecta el histórico de bancos dilusores conocidos.
    Tras recibir la respuesta, extrae `hired_banks` de <edgie_metrics> y los
    registra en DuckDB. Devuelve el mismo formato que /chat para que el frontend
    parsee igual.
    """
    ticker = (req.ticker or "").upper().strip()
    api_key = _resolve_api_key(request)

    # 1. Inyectar contexto histórico de bancos dilusores en el prompt.
    known = get_known_dilution_banks(ticker)
    if known:
        lines = [
            f"- {b['bank_name']}: visto en {b['ticker_count']} ticker(s)"
            + (" (YA APARECIÓ EN ESTE TICKER)" if b["seen_here"] else "")
            for b in known
        ]
        context_msg = {
            "role": "system",
            "content": (
                "CONTEXTO HISTÓRICO DE BANCOS DILUSORES (de análisis previos en la plataforma).\n"
                "Si detectas alguno de estos agentes colocadores en los filings actuales, "
                "considéralo señal de mayor riesgo y refléjalo al alza en dilution_score/dilution_rating:\n"
                + "\n".join(lines)
            ),
        }
        # Insertar tras el system prompt principal (índice 1) si existe.
        insert_at = 1 if req.messages and req.messages[0].get("role") == "system" else 0
        req.messages.insert(insert_at, context_msg)

    # 2. Llamada no-streaming al proveedor LLM.
    req.stream = False
    payload = _build_payload(req)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    url = f"{PROVIDER_BASE}/chat/completions"
    started = time.time()

    async with httpx.AsyncClient(timeout=180.0) as client:
        try:
            resp = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Error de red hacia el proveedor LLM: {exc}")
    if resp.status_code != 200:
        detail = resp.text[:500]
        try:
            detail = resp.json().get("error", {}).get("message", detail)
        except Exception:
            pass
        raise HTTPException(status_code=resp.status_code, detail=detail)

    data = resp.json()
    _log_usage(req.page, payload["model"], data.get("usage"), time.time() - started)

    # 3. Interceptar respuesta: registrar bancos dilusores detectados.
    try:
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        metrics = extract_edgie_metrics(content)
        if metrics and isinstance(metrics.get("hired_banks"), list):
            n = register_dilution_banks(ticker, metrics["hired_banks"])
            if n:
                logger.info("[ASSISTANT] %s: %d banco(s) dilusor(es) nuevo(s) registrado(s)", ticker, n)
    except Exception as exc:
        logger.warning("[ASSISTANT] interceptor de bancos falló: %s", exc)

    return JSONResponse(data)


@router.get("/health")
async def health():
    """Reports whether the gateway has a server-side key configured."""
    return {
        "status": "ok",
        "server_key_configured": bool(os.environ.get("DEEPSEEK_API_KEY", "").strip()),
        "model": DEFAULT_MODEL,
    }
