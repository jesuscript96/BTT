"""AI Gateway for the Edgie assistant.

Proxies chat completions to the LLM provider (DeepSeek today) so the API key
lives server-side, supports native function calling (tools) and streams the
provider's SSE chunks straight through to the browser.

See docs/plan_asistente_edgie.md and docs/assistant/arquitectura.md.
"""

import json
import logging
import os
import time
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


@router.get("/health")
async def health():
    """Reports whether the gateway has a server-side key configured."""
    return {
        "status": "ok",
        "server_key_configured": bool(os.environ.get("DEEPSEEK_API_KEY", "").strip()),
        "model": DEFAULT_MODEL,
    }
