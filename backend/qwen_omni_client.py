from __future__ import annotations

import os
from typing import Any, Dict, List

import httpx


QWEN_OMNI_BASE_URL = os.getenv("QWEN_OMNI_BASE_URL", "http://127.0.0.1:8091/v1").strip().rstrip("/")
QWEN_OMNI_MODEL_ID = os.getenv("QWEN_OMNI_MODEL_ID", "Qwen3-Omni-30B-A3B-Instruct").strip()
QWEN_OMNI_TIMEOUT_SEC = float(os.getenv("QWEN_OMNI_TIMEOUT_SEC", "90").strip() or "90")


class QwenOmniError(RuntimeError):
    pass


def flatten_response_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: List[str] = []
        for item in content:
            if isinstance(item, str):
                value = item.strip()
            elif isinstance(item, dict):
                value = str(item.get("text") or item.get("value") or item.get("content") or "").strip()
            else:
                value = str(item or "").strip()
            if value:
                chunks.append(value)
        return "\n".join(chunks).strip()
    if isinstance(content, dict):
        return str(content.get("text") or content.get("value") or content.get("content") or "").strip()
    return str(content or "").strip()


class QwenOmniClient:
    def __init__(self, base_url: str = QWEN_OMNI_BASE_URL, model_id: str = QWEN_OMNI_MODEL_ID) -> None:
        self.base_url = str(base_url or QWEN_OMNI_BASE_URL).rstrip("/")
        self.model_id = str(model_id or QWEN_OMNI_MODEL_ID).strip() or QWEN_OMNI_MODEL_ID

    async def models(self) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            response = await client.get(f"{self.base_url}/models")
            response.raise_for_status()
            return dict(response.json() or {})

    async def chat(self, messages: List[Dict[str, Any]], max_tokens: int = 700, temperature: float = 0.25) -> Dict[str, Any]:
        payload = {
            "model": self.model_id,
            "messages": messages,
            "max_tokens": int(max_tokens),
            "temperature": float(temperature),
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=QWEN_OMNI_TIMEOUT_SEC, trust_env=False) as client:
            response = await client.post(f"{self.base_url}/chat/completions", json=payload)
            if response.status_code >= 400:
                detail = response.text.strip()
                raise QwenOmniError(detail or f"Qwen Omni HTTP {response.status_code}")
            data = dict(response.json() or {})
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise QwenOmniError("Qwen Omni returned no choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            raise QwenOmniError("Qwen Omni returned malformed choice payload")
        text = flatten_response_content(message.get("content"))
        if not text:
            raise QwenOmniError("Qwen Omni returned empty content")
        return {
            "text": text,
            "raw": data,
        }
