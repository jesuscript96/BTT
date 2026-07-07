"""AI Gateway for the Edgie assistant.

Proxies chat completions to the LLM provider (DeepSeek today) so the API key
lives server-side, supports native function calling (tools) and streams the
provider's SSE chunks straight through to the browser.

See docs/plan_asistente_edgie.md and docs/assistant/arquitectura.md.
"""

import asyncio
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

from app.services import edgar_service

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
        if inserted:
            from app.gcs_sync import mark_user_db_dirty
            mark_user_db_dirty()
    except Exception as exc:
        logger.warning("[ASSISTANT] no se pudo registrar bancos dilusores: %s", exc)
    return inserted


def _pre_extract_for_report(ticker: str) -> Optional[str]:
    """Pre-extracción determinista para el informe: baja documentos SEC reales y
    devuelve las secciones de directivos y de oferta/dilución, para que Edgie
    rellene ownership_list / dilución con DATOS, no con invención. Tolerante."""
    parts = []
    # Directivos: 20-F Item 6 (emisor extranjero) o 10-K Item 10 (doméstico).
    try:
        for forms, item in ((["20-F"], 6), (["10-K"], 10)):
            r = edgar_service.get_filing_item(ticker, forms=forms, item_no=item, max_chars=3500)
            if r and r.get("section"):
                parts.append(f"DIRECTIVOS / JUNTA (de {r['form']} {r['date']}, Item {item}):\n{r['section']}")
                break
    except Exception as e:
        logger.warning("[REPORT] pre-extract directivos falló %s: %s", ticker, e)
    # Oferta / dilución: 424B o S-1/S-3 — sección Plan of Distribution / Underwriting.
    try:
        cik = edgar_service.resolve_cik(ticker)
        if cik:
            fl = edgar_service.list_filings(cik, forms=["424B", "S-1", "S-3", "F-1", "F-3"], limit=3)
            if fl:
                f = fl[0]
                text = edgar_service.fetch_document_text(cik, f["accession"], f["primary_document"])
                if text:
                    seg = edgar_service.read_relevant(
                        text,
                        "plan of distribution underwriting placement agent warrants exercise price at-the-market offering",
                        max_chars=3500,
                    )
                    if seg:
                        parts.append(f"OFERTA / DILUCIÓN (de {f['form']} {f['date']}):\n{seg}")
    except Exception as e:
        logger.warning("[REPORT] pre-extract oferta falló %s: %s", ticker, e)
    return "\n\n".join(parts) if parts else None


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

    # 1b. Pre-extracción de documentos SEC reales (directivos + oferta/dilución).
    extracted = await asyncio.to_thread(_pre_extract_for_report, ticker)
    if extracted:
        insert_at = 1 if req.messages and req.messages[0].get("role") == "system" else 0
        req.messages.insert(insert_at, {
            "role": "system",
            "content": (
                "DATOS REALES EXTRAÍDOS DE DOCUMENTOS SEC PARA ESTE TICKER. "
                "Úsalos como fuente para ownership_list/directivos y para la dilución; "
                "NO inventes nombres ni cifras y cita el formulario:\n\n" + extracted[:8000]
            ),
        })

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


# ── Chat agentic con tools sobre SEC EDGAR ───────────────────────────────────
# Edgie deja de responder "de memoria" (y de alucinar): se le dan herramientas
# para LEER de verdad los documentos de EDGAR y razonar sobre su contenido.
# Bucle de tool-calling no-streaming: el modelo pide tools -> las ejecutamos ->
# le devolvemos el resultado -> repite hasta dar respuesta final.

AGENTIC_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_filings",
            "description": "Lista los filings recientes de SEC EDGAR de una empresa (tipo, fecha, descripción). Úsalo para saber QUÉ documentos existen antes de leerlos.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Símbolo (ej: SPCB). Si se omite, usa el ticker activo."},
                    "form_type": {"type": "string", "description": "Filtro opcional por prefijo de formulario (ej: '20-F', '424B', '8-K', 'S-1', 'DEF 14A')."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_filing",
            "description": "Abre y LEE el contenido real del filing más reciente de un tipo dado y devuelve la parte relevante. Para 20-F/10-K usa 'item' (ej. directivos de un 20-F = item 6; de un 10-K = item 10). Para prospectos (424B/S-1) usa 'query' (ej. 'plan of distribution', 'warrant exercise price'). Úsalo SIEMPRE antes de afirmar datos de un documento.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "form_type": {"type": "string", "description": "Formulario a abrir (ej: '20-F', '424B5', 'S-1', '8-K')."},
                    "query": {"type": "string", "description": "Qué buscas dentro del documento (texto libre)."},
                    "item": {"type": "integer", "description": "Nº de ITEM a extraer en filings estructurados (20-F/10-K/10-Q)."},
                },
                "required": ["form_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_insiders",
            "description": "Transacciones de insiders (compras/ventas de directivos) desde SEC Forms 3/4/5. Útil para small caps US; los emisores extranjeros (20-F) suelen estar exentos.",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
            },
        },
    },
]


def _tool_list_filings(ticker=None, form_type=None, _default_ticker=None):
    ticker = (ticker or _default_ticker or "").upper().strip()
    if not ticker:
        return {"error": "no ticker"}
    cik = edgar_service.resolve_cik(ticker)
    if not cik:
        return {"error": f"No se encontró CIK para {ticker} (¿no cotiza en SEC?)."}
    forms = [form_type] if form_type else None
    fl = edgar_service.list_filings(cik, forms=forms, limit=15)
    return {"ticker": ticker, "filings": [
        {"form": x["form"], "date": x["date"], "description": x["description"]} for x in fl
    ]}


def _tool_read_filing(form_type, ticker=None, query="", item=None, _default_ticker=None):
    ticker = (ticker or _default_ticker or "").upper().strip()
    if not ticker:
        return {"error": "no ticker"}
    cik = edgar_service.resolve_cik(ticker)
    if not cik:
        return {"error": f"No se encontró CIK para {ticker}."}
    fl = edgar_service.list_filings(cik, forms=[form_type], limit=5)
    if not fl:
        return {"error": f"No hay filings tipo {form_type} para {ticker}."}
    f = fl[0]
    text = edgar_service.fetch_document_text(cik, f["accession"], f["primary_document"])
    if not text:
        return {"error": "No se pudo descargar el documento."}
    if item is not None:
        seg = edgar_service.extract_item(text, int(item)) or edgar_service.read_relevant(text, query or str(item))
    else:
        seg = edgar_service.read_relevant(text, query)
    return {
        "form": f["form"], "date": f["date"],
        "url": edgar_service._doc_url(cik, f["accession"], f["primary_document"]),
        "content": (seg or "")[:9000],
        "note": "Responde SOLO con lo que aparezca en 'content'. Si el dato no está, di que no está; no inventes.",
    }


def _tool_get_insiders(ticker=None, _default_ticker=None):
    ticker = (ticker or _default_ticker or "").upper().strip()
    if not ticker:
        return {"error": "no ticker"}
    from app.routers.ticker_analysis import get_insider_activity
    return {"ticker": ticker, "insiders": get_insider_activity(ticker)[:25]}


_TOOL_IMPL = {
    "list_filings": _tool_list_filings,
    "read_filing": _tool_read_filing,
    "get_insiders": _tool_get_insiders,
}

_AGENTIC_PREAMBLE = (
    "Tienes herramientas para consultar SEC EDGAR EN VIVO: list_filings, read_filing y get_insiders. "
    "Cuando te pregunten por datos concretos de la empresa (directivos/junta, ofertas, dilución, warrants, "
    "beneficial owners, insiders, etc.), DEBES usarlas para leer el documento real en vez de responder de memoria. "
    "REGLA CRÍTICA: nunca afirmes haber leído un documento ni des datos 'según el Form X' si no lo has abierto con "
    "read_filing en esta conversación. Si la herramienta no devuelve el dato, di 'no disponible en los filings' y "
    "NO inventes nombres ni cifras. Cita siempre la fuente (formulario + fecha). "
    "Pista de estructura: en un 20-F los directivos están en el Item 6; en un 10-K en el Item 10; "
    "los agentes colocadores/ofertas en 424B y S-1/S-3 ('Plan of Distribution'/'Underwriting')."
)


def _sanitize_agentic_content(content: Optional[str]) -> str:
    """Quita plantillas de tool-call que el modelo a veces filtra como TEXTO
    (sobre todo al forzar respuesta sin tools): los marcadores DSML/invoke de
    DeepSeek. Corta en el primer marcador; lo de antes es la respuesta legible."""
    if not content:
        return ""
    for marker in ("<｜", "｜＞", "DSML", "<tool_call", "invoke name=", "<function"):
        idx = content.find(marker)
        if idx != -1:
            content = content[:idx]
    return content.strip()


class AgenticChatRequest(ChatRequest):
    ticker: Optional[str] = Field(None, description="Ticker activo para resolver las tools sin pedirlo.")
    max_iterations: int = 8


@router.post("/agentic-chat")
async def agentic_chat(req: AgenticChatRequest, request: Request):
    """Chat con bucle de tool-calling sobre EDGAR (no-streaming). Devuelve el
    mismo formato que /chat (choices[0].message.content) para el frontend."""
    api_key = _resolve_api_key(request)
    default_ticker = (req.ticker or "").upper().strip() or None

    messages: list[dict] = [{"role": "system", "content": _AGENTIC_PREAMBLE}]
    if default_ticker:
        messages.append({"role": "system", "content": f"Ticker activo: {default_ticker}."})
    messages.extend(req.messages)

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    url = f"{PROVIDER_BASE}/chat/completions"
    model = req.model or DEFAULT_MODEL
    started = time.time()
    last_data = None
    converged = False

    async with httpx.AsyncClient(timeout=180.0) as client:
        for _ in range(max(1, min(req.max_iterations, 8))):
            payload = {
                "model": model, "messages": messages,
                "tools": AGENTIC_TOOLS, "tool_choice": "auto",
                "temperature": req.temperature, "stream": False,
            }
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

            last_data = resp.json()
            choice = (last_data.get("choices") or [{}])[0]
            msg = choice.get("message", {}) or {}
            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                converged = True
                break

            # Reproduce el turno del asistente con sus tool_calls y resuelve cada uno.
            messages.append({
                "role": "assistant",
                "content": msg.get("content") or "",
                "tool_calls": tool_calls,
            })
            for tc in tool_calls:
                fn = (tc.get("function") or {})
                name = fn.get("name")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except Exception:
                    args = {}
                impl = _TOOL_IMPL.get(name)
                if impl is None:
                    result = {"error": f"herramienta desconocida: {name}"}
                else:
                    try:
                        result = await asyncio.to_thread(impl, _default_ticker=default_ticker, **args)
                    except Exception as exc:
                        logger.warning("[AGENTIC] tool %s falló: %s", name, exc)
                        result = {"error": f"fallo ejecutando {name}: {exc}"}
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id"),
                    "content": json.dumps(result, ensure_ascii=False)[:9000],
                })

        # Si agotó iteraciones sin converger, fuerza una respuesta final SIN tools
        # (el modelo redacta con lo que ya leyó) para no devolver content vacío.
        if not converged:
            try:
                messages.append({
                    "role": "system",
                    "content": "Has alcanzado el límite de consultas. Da la respuesta FINAL ahora mismo con lo que ya leíste en los resultados de las herramientas. Si no encontraste el dato, di exactamente que no está disponible en los filings consultados y sugiere qué documento mirar. PROHIBIDO decir que vas a buscar más o usar sintaxis de herramientas.",
                })
                resp = await client.post(url, json={
                    "model": model, "messages": messages,
                    "tool_choice": "none",
                    "temperature": req.temperature, "stream": False,
                }, headers=headers)
                if resp.status_code == 200:
                    last_data = resp.json()
            except httpx.HTTPError as exc:
                logger.warning("[AGENTIC] cierre forzado falló: %s", exc)

    # Limpia plantillas de tool-call filtradas como texto; si no queda nada útil,
    # responde con un aviso en vez de basura o vacío.
    try:
        ch = (last_data or {}).get("choices") or [{}]
        m = ch[0].get("message", {}) or {}
        cleaned = _sanitize_agentic_content(m.get("content"))
        # A veces el modelo deja una promesa incumplida ("voy a buscar…") como texto
        # en vez de emitir un tool-call real → no es respuesta, da el fallback.
        low = cleaned.lower()
        unfulfilled = any(p in low for p in (
            "voy a buscar", "voy a revisar", "buscaré", "déjame buscar",
            "let me search", "let me look", "i'll search", "i will search",
        ))
        if not cleaned or unfulfilled:
            cleaned = ("No he podido extraer ese dato de los filings disponibles. "
                       "¿Quieres que revise otro documento (p. ej. el DEF 14A o el 10-K)?")
        m["content"] = cleaned
        ch[0]["message"] = m
        last_data["choices"] = ch
    except Exception:
        pass

    _log_usage(req.page, model, (last_data or {}).get("usage"), time.time() - started)
    return JSONResponse(last_data or {"choices": [{"message": {"content": "No hubo respuesta del modelo."}}]})


@router.get("/health")
async def health():
    """Reports whether the gateway has a server-side key configured."""
    return {
        "status": "ok",
        "server_key_configured": bool(os.environ.get("DEEPSEEK_API_KEY", "").strip()),
        "model": DEFAULT_MODEL,
    }
