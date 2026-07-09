import json
import asyncio
from enum import Enum
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import aiohttp
import logging
import config
from services.http import get_session
from models.requests import LLMRequest, ConversationMessage

logger = logging.getLogger(__name__)


class TaskType(Enum):
    STRONG = "strong"
    FAST = "fast"


class LLMResponse(BaseModel):
    content: str
    model_used: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    input_tokens: int = 0
    output_tokens: int = 0


def _clean_gemini_schema(schema: dict, defs: dict = None) -> dict:
    if defs is None:
        defs = schema.get("$defs", {})

    if isinstance(schema, dict):
        if "$ref" in schema:
            ref_key = schema["$ref"].split("/")[-1]
            resolved = defs.get(ref_key, {}).copy()
            return _clean_gemini_schema(resolved, defs)

        cleaned = {}
        for k, v in schema.items():
            if k in ("$defs", "title", "default"):
                continue

            if k == "anyOf" and isinstance(v, list):
                types = [t.get("type") for t in v if isinstance(t, dict) and "type" in t]
                if "null" in types:
                    non_null = [t for t in types if t != "null"]
                    if non_null:
                        cleaned["type"] = non_null[0]
                        cleaned["nullable"] = True
                    continue
                if types:
                    cleaned["type"] = types[0]
                    continue

            cleaned[k] = _clean_gemini_schema(v, defs)

        if "type" in cleaned and isinstance(cleaned["type"], str):
            cleaned["type"] = cleaned["type"].upper()

        return cleaned
    elif isinstance(schema, list):
        return [_clean_gemini_schema(item, defs) for item in schema]
    else:
        return schema


async def route(request: LLMRequest) -> LLMResponse:
    local_endpoint = config.LLAMA_CPP_ENDPOINT or "http://127.0.0.1:8080"

    if request.multimodal_data and config.GEMINI_API_KEY:
        return await _call_gemini(request)

    try:
        return await _call_llama(request, local_endpoint)
    except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as e:
        logger.warning(f"Local AI Server unreachable/timeout ({e}). Falling back to Gemini API...")
        if config.GEMINI_API_KEY:
            return await _call_gemini(request)
        raise ValueError("Local LLM failed and GEMINI_API_KEY is not set.")
    except Exception as e:
        logger.warning(f"Local AI Server error: {e}. Falling back to Gemini API...")
        if config.GEMINI_API_KEY:
            return await _call_gemini(request)
        raise e


async def route_with_retry(request: LLMRequest, max_attempts: int = 4) -> LLMResponse:
    for attempt in range(max_attempts):
        try:
            return await route(request)
        except aiohttp.ClientResponseError as e:
            if e.status in (429, 500, 502, 503, 504) and attempt < max_attempts - 1:
                wait_time = 3 ** attempt
                logger.warning(
                    f"LLM API busy (Status {e.status}). Retrying in {wait_time}s (Attempt {attempt + 1}/{max_attempts})...")
                await asyncio.sleep(wait_time)
            else:
                raise e
        except Exception as e:
            if attempt == max_attempts - 1:
                raise e
            wait_time = 3 ** attempt
            logger.warning(f"LLM Error: {e}. Retrying in {wait_time}s...")
            await asyncio.sleep(wait_time)


async def _call_gemini(request: LLMRequest) -> LLMResponse:
    model = config.LLM_STRONG_MODEL if request.task_type == TaskType.STRONG.value else config.LLM_FAST_MODEL
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    contents = []
    if request.conversation:
        for msg in request.conversation:
            contents.append({"role": msg.role, "parts": [{"text": msg.content}]})

    parts = []

    if request.multimodal_data:
        for media in request.multimodal_data:
            parts.append({
                "inlineData": {
                    "mimeType": media["mime_type"],
                    "data": media["data"]
                }
            })

    parts.append({"text": request.prompt})
    contents.append({"role": "user", "parts": parts})

    payload = {"contents": contents}

    if request.system:
        payload["systemInstruction"] = {"parts": [{"text": request.system}]}

    generation_config = {}

    if request.response_schema:
        generation_config["responseMimeType"] = "application/json"
        generation_config["responseSchema"] = _clean_gemini_schema(request.response_schema)

    if request.thinking_level:
        generation_config["thinkingConfig"] = {"thinkingLevel": request.thinking_level.upper()}

    if generation_config:
        payload["generationConfig"] = generation_config

    headers = {}
    if config.GEMINI_API_KEY:
        headers["x-goog-api-key"] = config.GEMINI_API_KEY

    session = await get_session()
    async with session.post(url, json=payload, headers=headers) as resp:
        if resp.status != 200:
            err_text = await resp.text()
            logger.error(f"Gemini API Error: {err_text}")
        resp.raise_for_status()

        data = await resp.json()
        content = data["candidates"][0]["content"]["parts"][0]["text"]
        return LLMResponse(content=content, model_used=f"gemini ({model})")


async def _call_llama(request: LLMRequest, endpoint: str) -> LLMResponse:
    url = endpoint if "/chat/completions" in endpoint else f"{endpoint.rstrip('/')}/v1/chat/completions"
    messages = []
    if request.system:
        messages.append({"role": "system", "content": request.system})
    if request.conversation:
        messages.extend([msg.model_dump() for msg in request.conversation])
    messages.append({"role": "user", "content": request.prompt})

    payload = {"messages": messages, "temperature": 0.2, "max_tokens": request.max_tokens}

    if request.response_schema:
        payload["response_format"] = {
            "type": "json_object",
            "schema": request.response_schema
        }

    session = await get_session()
    timeout = aiohttp.ClientTimeout(total=1800)
    async with session.post(url, json=payload, timeout=timeout) as resp:
        if resp.status != 200:
            err_text = await resp.text()
            raise RuntimeError(f"Llama.cpp returned HTTP {resp.status}: {err_text}")
        data = await resp.json()
        content = data["choices"][0]["message"]["content"]
        return LLMResponse(content=content, model_used="llama.cpp (local)")