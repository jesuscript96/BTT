"""
Edgie chat proxy.

Forwards chat-completion requests to DeepSeek using a server-side API key, so the
key is NEVER exposed to the browser. The frontend posts the same body it used to
send to DeepSeek directly ({model, messages, temperature, ...}); we just attach
the Authorization header and relay the response.
"""

import logging
import os

import httpx
from fastapi import APIRouter, Request

logger = logging.getLogger("btt.edgie")

router = APIRouter()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"


@router.post("/chat")
async def edgie_chat(request: Request):
    body = await request.json()

    if not DEEPSEEK_API_KEY:
        logger.warning("Edgie chat called but DEEPSEEK_API_KEY is not configured.")
        return {"error": "DeepSeek API key not configured on the server."}

    async with httpx.AsyncClient() as client:
        response = await client.post(
            DEEPSEEK_URL,
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=60.0,
        )
        return response.json()
