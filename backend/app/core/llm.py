"""Minimal JSON chat client for any OpenAI-compatible endpoint (OpenAI, Gemini, Groq...)."""
from __future__ import annotations

import json
import re

import httpx

from app.core.config import settings


class LLMUnavailable(Exception):
    pass


def _parse(raw: str) -> dict:
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def chat_json(system: str, user: str | list, timeout: float = 45) -> dict:
    if not settings.llm_enabled:
        raise LLMUnavailable("No LLM is configured on the server (set LLM_API_KEY, LLM_BASE_URL, LLM_MODEL).")
    try:
        resp = httpx.post(
            f"{settings.llm_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={"model": settings.llm_model, "temperature": 0.1,
                  "response_format": {"type": "json_object"},
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
            timeout=timeout,
        )
        resp.raise_for_status()
        return _parse(resp.json()["choices"][0]["message"]["content"])
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise LLMUnavailable(f"LLM call failed: {type(exc).__name__}") from exc
