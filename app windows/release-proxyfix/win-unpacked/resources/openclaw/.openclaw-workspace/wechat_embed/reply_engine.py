#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Thin reply bridge:
WeCom transport -> backend assistant -> OpenClaw.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Dict, Optional


def normalize_text(text: str, max_len: int = 1200) -> str:
    value = (text or "").replace("\r\n", "\n").strip()
    return value[:max_len] if len(value) > max_len else value


@dataclass
class ModelConfig:
    backend_base_url: str
    bridge_token: str
    timeout_ms: int


class ReplyEngine:
    def __init__(self, cfg: ModelConfig, logger: logging.Logger) -> None:
        self.cfg = cfg
        self.logger = logger

    def _post_json(self, path: str, payload: Dict[str, object]) -> Dict[str, object]:
        base_url = str(self.cfg.backend_base_url or "").rstrip("/")
        if not base_url:
            raise RuntimeError("ASSISTANT_BACKEND_URL missing")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url=f"{base_url}{path}",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Assistant-Bridge-Token": str(self.cfg.bridge_token or "").strip(),
            },
            method="POST",
        )
        timeout = max(5.0, float(self.cfg.timeout_ms) / 1000.0)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
                data = json.loads(raw or "{}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"assistant bridge http error: {exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"assistant bridge unavailable: {exc}") from exc
        if not isinstance(data, dict):
            raise RuntimeError("assistant bridge returned invalid payload")
        return data

    def generate(self, sender: str, user_text: str) -> str:
        text = normalize_text(user_text)
        if not text:
            return ""
        data = self._post_json(
            "/api/assistant/bridge/send",
            {
                "sender_id": str(sender or "unknown"),
                "surface": "wecom",
                "text": text,
                "metadata": {"channel": "wecom"},
            },
        )
        reply = normalize_text(str(data.get("text") or ""), 1200)
        if not reply:
            raise RuntimeError("assistant bridge returned empty text")
        return reply


def load_model_config_from_env() -> ModelConfig:
    return ModelConfig(
        backend_base_url=os.getenv("ASSISTANT_BACKEND_URL", "http://127.0.0.1:8000").strip(),
        bridge_token=os.getenv("ASSISTANT_BRIDGE_TOKEN", "").strip(),
        timeout_ms=int(os.getenv("ASSISTANT_TIMEOUT_MS", "45000")),
    )
