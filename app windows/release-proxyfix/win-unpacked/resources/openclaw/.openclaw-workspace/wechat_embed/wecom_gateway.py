#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
WeCom callback gateway:
- verify callback URL
- auto-reply for incoming app messages
- proactive send to a target user
"""

from __future__ import annotations

import asyncio
import argparse
import base64
import json
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, Dict, List, Optional, Set, Tuple

from dotenv import load_dotenv
from flask import Flask, Response, request
from openai import OpenAI
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_private_key,
    load_pem_public_key,
)
from wechatpy.enterprise import WeChatClient
from wechatpy.enterprise.crypto import WeChatCrypto
from wechatpy.enterprise.parser import parse_message
from wechatpy.enterprise.replies import TextReply
from reply_engine import ReplyEngine as BackendReplyEngine, load_model_config_from_env

try:
    import websockets
except Exception:
    websockets = None

APP_DIR = Path(__file__).resolve().parent
DEFAULT_ENV_PATH = APP_DIR / ".env.wecom"
STATE_PATH = APP_DIR / "wecom_state.json"


@dataclass
class GatewayConfig:
    corp_id: str
    agent_id: int
    secret: str
    token: str
    aes_key: str
    allowlist: Set[str]
    welcome_text: str
    openai_model: str
    system_prompt: str
    temperature: float
    max_tokens: int
    reply_prefix: str
    fallback_when_no_key: bool
    openclaw_enabled: bool
    openclaw_state_dir: str
    openclaw_url: str
    openclaw_origin: str
    openclaw_session_key: str
    openclaw_timeout_ms: int
    openclaw_client_id: str
    openclaw_client_mode: str
    codex_cli_enabled: bool
    codex_cli_timeout_ms: int
    codex_cli_command: str
    codex_cli_workdir: str


def _to_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _to_int(value: str, default: int) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def _to_float(value: str, default: float) -> float:
    try:
        return float(str(value).strip())
    except Exception:
        return default


def _split_csv(value: str) -> Set[str]:
    items = [x.strip() for x in (value or "").split(",") if x.strip()]
    return set(items)


def normalize_text(text: str, max_len: int = 1200) -> str:
    text = (text or "").replace("\r\n", "\n").strip()
    if len(text) > max_len:
        text = text[:max_len]
    return text


def fallback_reply(user_text: str) -> str:
    user_text = normalize_text(user_text, 180)
    if not user_text:
        return "在的。"
    return f"收到：{user_text}"


def load_config(env_file: Path) -> GatewayConfig:
    load_dotenv(env_file, override=False)

    return GatewayConfig(
        corp_id=os.getenv("WECOM_CORP_ID", "").strip(),
        agent_id=_to_int(os.getenv("WECOM_AGENT_ID", "0"), 0),
        secret=os.getenv("WECOM_SECRET", "").strip(),
        token=os.getenv("WECOM_TOKEN", "").strip(),
        aes_key=os.getenv("WECOM_AES_KEY", "").strip(),
        allowlist=_split_csv(os.getenv("WECOM_ALLOWLIST", "")),
        welcome_text=normalize_text(os.getenv("WECOM_WELCOME_TEXT", ""), 300),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
        system_prompt=(
            os.getenv(
                "OPENAI_SYSTEM_PROMPT",
                "你是微信里的私人AI助手。用中文回复，简洁自然，聚焦可执行建议。",
            ).strip()
        ),
        temperature=_to_float(os.getenv("OPENAI_TEMPERATURE", "0.6"), 0.6),
        max_tokens=_to_int(os.getenv("OPENAI_MAX_TOKENS", "300"), 300),
        reply_prefix=os.getenv("OPENAI_REPLY_PREFIX", "").strip(),
        fallback_when_no_key=_to_bool(os.getenv("OPENAI_FALLBACK_WHEN_NO_KEY", "true"), True),
        openclaw_enabled=_to_bool(os.getenv("OPENCLAW_ENABLED", "true"), True),
        openclaw_state_dir=os.getenv(
            "OPENCLAW_STATE_DIR", str(Path.home() / ".openclaw")
        ).strip(),
        openclaw_url=os.getenv("OPENCLAW_URL", "").strip(),
        openclaw_origin=os.getenv("OPENCLAW_ORIGIN", "").strip(),
        openclaw_session_key=(
            os.getenv("OPENCLAW_SESSION_KEY", "agent:main:wecom").strip() or "agent:main:wecom"
        ),
        openclaw_timeout_ms=_to_int(os.getenv("OPENCLAW_TIMEOUT_MS", "15000"), 15000),
        openclaw_client_id=(
            os.getenv("OPENCLAW_CLIENT_ID", "openclaw-control-ui").strip()
            or "openclaw-control-ui"
        ),
        openclaw_client_mode=os.getenv("OPENCLAW_CLIENT_MODE", "webchat").strip() or "webchat",
        codex_cli_enabled=_to_bool(os.getenv("CODEX_CLI_ENABLED", "true"), True),
        codex_cli_timeout_ms=_to_int(os.getenv("CODEX_CLI_TIMEOUT_MS", "90000"), 90000),
        codex_cli_command=os.getenv("CODEX_CLI_COMMAND", "codex").strip() or "codex",
        codex_cli_workdir=os.getenv("CODEX_CLI_WORKDIR", "").strip(),
    )


def validate_for_run(cfg: GatewayConfig) -> Tuple[bool, List[str]]:
    missing: List[str] = []
    if not cfg.corp_id:
        missing.append("WECOM_CORP_ID")
    if not cfg.token:
        missing.append("WECOM_TOKEN")
    if not cfg.aes_key:
        missing.append("WECOM_AES_KEY")
    if not os.getenv("ASSISTANT_BACKEND_URL", "").strip():
        missing.append("ASSISTANT_BACKEND_URL")
    if not os.getenv("ASSISTANT_BRIDGE_TOKEN", "").strip():
        missing.append("ASSISTANT_BRIDGE_TOKEN")
    return (len(missing) == 0, missing)


def validate_for_send(cfg: GatewayConfig) -> Tuple[bool, List[str]]:
    missing: List[str] = []
    if not cfg.corp_id:
        missing.append("WECOM_CORP_ID")
    if not cfg.secret:
        missing.append("WECOM_SECRET")
    if not cfg.agent_id:
        missing.append("WECOM_AGENT_ID")
    return (len(missing) == 0, missing)


def load_state() -> Dict[str, str]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_last_sender(sender: str) -> None:
    sender = sender.strip()
    if not sender:
        return
    state = load_state()
    state["last_sender"] = sender
    state["updated_at"] = int(time.time())
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


class OpenClawBridge:
    def __init__(self, cfg: GatewayConfig, logger: logging.Logger) -> None:
        self.cfg = cfg
        self.logger = logger
        self._enabled = bool(cfg.openclaw_enabled and websockets is not None)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @staticmethod
    def _b64url_no_pad(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")

    @staticmethod
    def _make_sign_input(
        version: str,
        device_id: str,
        client_id: str,
        client_mode: str,
        role: str,
        scopes: List[str],
        signed_at_ms: int,
        token: str,
        nonce: Optional[str],
    ) -> str:
        parts = [
            version,
            device_id,
            client_id,
            client_mode,
            role,
            ",".join(scopes),
            str(signed_at_ms),
            token or "",
        ]
        if version == "v2":
            parts.append(nonce or "")
        return "|".join(parts)

    def _load_runtime(self) -> Dict[str, str]:
        state_dir = Path(self.cfg.openclaw_state_dir).expanduser()
        openclaw_json = json.loads((state_dir / "openclaw.json").read_text(encoding="utf-8"))
        device_json = json.loads((state_dir / "identity" / "device.json").read_text(encoding="utf-8"))
        auth_json = json.loads(
            (state_dir / "identity" / "device-auth.json").read_text(encoding="utf-8")
        )

        gateway_port = int(openclaw_json.get("gateway", {}).get("port", 18789))
        url = self.cfg.openclaw_url or f"ws://127.0.0.1:{gateway_port}"
        origin = self.cfg.openclaw_origin or f"http://127.0.0.1:{gateway_port}"

        gateway_token = (
            openclaw_json.get("gateway", {}).get("auth", {}).get("token", "") or ""
        ).strip()
        device_token = (
            auth_json.get("tokens", {}).get("operator", {}).get("token", "") or ""
        ).strip()
        token = gateway_token or device_token
        if not token:
            raise RuntimeError("OpenClaw token missing (gateway.auth.token / device-auth operator)")

        return {
            "url": url,
            "origin": origin,
            "token": token,
            "device_id": str(device_json.get("deviceId", "")),
            "private_key_pem": str(device_json.get("privateKeyPem", "")),
            "public_key_pem": str(device_json.get("publicKeyPem", "")),
        }

    async def _rpc_request(self, ws, method: str, params: Dict[str, object], timeout_ms: int = 15000) -> Dict[str, object]:
        req_id = str(uuid.uuid4())
        await ws.send(
            json.dumps(
                {"type": "req", "id": req_id, "method": method, "params": params},
                ensure_ascii=False,
            )
        )

        deadline = time.monotonic() + max(1.0, timeout_ms / 1000.0)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"OpenClaw rpc timeout: {method}")
            raw = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 2.0))
            msg = json.loads(raw)
            if msg.get("type") == "res" and msg.get("id") == req_id:
                return msg

    @staticmethod
    def _extract_text_from_message(message_obj: Dict[str, object]) -> str:
        parts = message_obj.get("content") if isinstance(message_obj, dict) else None
        if not isinstance(parts, list):
            return ""
        out: List[str] = []
        for part in parts:
            if isinstance(part, dict) and part.get("type") == "text":
                out.append(str(part.get("text") or ""))
        return normalize_text("".join(out), 1200)

    async def _ask_async(self, user_text: str) -> str:
        runtime = self._load_runtime()
        private_key = load_pem_private_key(runtime["private_key_pem"].encode("utf-8"), password=None)
        public_key = load_pem_public_key(runtime["public_key_pem"].encode("utf-8"))
        public_raw = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
        public_b64 = self._b64url_no_pad(public_raw)
        device_id = runtime["device_id"].strip()
        if not device_id:
            raise RuntimeError("OpenClaw device id missing")

        scopes = [
            "operator.admin",
            "operator.approvals",
            "operator.pairing",
            "operator.read",
            "operator.write",
        ]
        role = "operator"
        timeout_ms = max(3000, int(self.cfg.openclaw_timeout_ms))

        async with websockets.connect(
            runtime["url"],
            origin=runtime["origin"],
            max_size=20_000_000,
        ) as ws:
            nonce: Optional[str] = None
            try:
                first = json.loads(await asyncio.wait_for(ws.recv(), timeout=1.2))
                if first.get("type") == "event" and first.get("event") == "connect.challenge":
                    nonce = (first.get("payload") or {}).get("nonce")
            except Exception:
                nonce = None

            signed_at = int(time.time() * 1000)
            version = "v2" if nonce else "v1"
            sign_input = self._make_sign_input(
                version=version,
                device_id=device_id,
                client_id=self.cfg.openclaw_client_id,
                client_mode=self.cfg.openclaw_client_mode,
                role=role,
                scopes=scopes,
                signed_at_ms=signed_at,
                token=runtime["token"],
                nonce=nonce,
            ).encode("utf-8")
            signature = self._b64url_no_pad(private_key.sign(sign_input))

            connect_res = await self._rpc_request(
                ws,
                "connect",
                {
                    "minProtocol": 3,
                    "maxProtocol": 3,
                    "client": {
                        "id": self.cfg.openclaw_client_id,
                        "version": "dev",
                        "platform": "Win32",
                        "mode": self.cfg.openclaw_client_mode,
                    },
                    "role": role,
                    "scopes": scopes,
                    "caps": [],
                    "auth": {"token": runtime["token"]},
                    "device": {
                        "id": device_id,
                        "publicKey": public_b64,
                        "signature": signature,
                        "signedAt": signed_at,
                        **({"nonce": nonce} if nonce else {}),
                    },
                    "userAgent": "wecom-openclaw-bridge",
                    "locale": "zh-CN",
                },
                timeout_ms=10000,
            )
            if not connect_res.get("ok"):
                raise RuntimeError(f"OpenClaw connect failed: {connect_res.get('error')}")

            run_id = f"wecom-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
            send_res = await self._rpc_request(
                ws,
                "chat.send",
                {
                    "sessionKey": self.cfg.openclaw_session_key,
                    "message": user_text,
                    "deliver": False,
                    "timeoutMs": timeout_ms,
                    "idempotencyKey": run_id,
                },
                timeout_ms=15000,
            )
            if not send_res.get("ok"):
                raise RuntimeError(f"OpenClaw chat.send failed: {send_res.get('error')}")

            deadline = time.monotonic() + timeout_ms / 1000.0
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 2.0))
                except asyncio.TimeoutError:
                    continue
                msg = json.loads(raw)
                if msg.get("type") != "event":
                    continue
                if msg.get("event") != "chat":
                    continue
                payload = msg.get("payload") or {}
                if payload.get("runId") != run_id:
                    continue

                state = str(payload.get("state") or "")
                if state == "final":
                    text = self._extract_text_from_message(payload.get("message") or {})
                    if text:
                        return text
                    return ""
                if state in {"error", "aborted"}:
                    raise RuntimeError(f"OpenClaw chat {state}: {payload.get('errorMessage')}")

            try:
                await self._rpc_request(
                    ws,
                    "chat.abort",
                    {"sessionKey": self.cfg.openclaw_session_key, "runId": run_id},
                    timeout_ms=3000,
                )
            except Exception:
                pass
            raise TimeoutError("OpenClaw chat timed out")

    def generate(self, user_text: str) -> str:
        return asyncio.run(self._ask_async(user_text))


class ReplyEngine:
    def __init__(self, cfg: GatewayConfig, logger: logging.Logger) -> None:
        self.cfg = cfg
        self.logger = logger
        self.client: Optional[OpenAI] = None
        self.openclaw: Optional[OpenClawBridge] = None
        self.history: Dict[str, Deque[Tuple[str, str]]] = defaultdict(lambda: deque(maxlen=12))

        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        base_url = os.getenv("OPENAI_BASE_URL", "").strip()
        if api_key:
            self.client = OpenAI(api_key=api_key, base_url=base_url or None)
        if cfg.openclaw_enabled:
            bridge = OpenClawBridge(cfg, logger)
            if bridge.enabled:
                self.openclaw = bridge
            else:
                self.logger.warning("OPENCLAW_ENABLED=true but websockets import failed")

    def _build_codex_prompt(self, sender: str, user_text: str) -> str:
        lines: List[str] = [
            self.cfg.system_prompt,
            "",
            "请用中文、简洁自然地回复用户，除非用户明确要求别的语言。",
            "如果用户明确要求“只回复某个词”，严格只输出那个词。",
            "",
            "最近对话：",
        ]
        for role, content in self.history[sender]:
            role_cn = "用户" if role == "user" else "助手"
            lines.append(f"{role_cn}：{content}")
        lines.append(f"用户：{user_text}")
        lines.append("助手：")
        return "\n".join(lines).strip()

    def _generate_via_codex_cli(self, sender: str, user_text: str) -> str:
        prompt = self._build_codex_prompt(sender, user_text)
        cmd = [
            self.cfg.codex_cli_command,
            "exec",
            "--json",
            "--color",
            "never",
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check",
            prompt,
        ]
        workdir = self.cfg.codex_cli_workdir or str(APP_DIR.parent)
        proc = subprocess.run(
            cmd,
            cwd=workdir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=max(5.0, self.cfg.codex_cli_timeout_ms / 1000.0),
        )
        agent_text = ""
        for line in (proc.stdout or "").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("type") != "item.completed":
                continue
            item = obj.get("item") or {}
            if isinstance(item, dict) and item.get("type") == "agent_message":
                candidate = normalize_text(str(item.get("text") or ""), 1200)
                if candidate:
                    agent_text = candidate

        if not agent_text:
            err_tail = normalize_text((proc.stderr or "")[-400:], 400)
            raise RuntimeError(f"codex-cli returned no agent_message (rc={proc.returncode}, err={err_tail})")
        return agent_text

    def _build_messages(self, sender: str, user_text: str) -> List[Dict[str, str]]:
        messages: List[Dict[str, str]] = [{"role": "system", "content": self.cfg.system_prompt}]
        for role, content in self.history[sender]:
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_text})
        return messages

    def _add_history(self, sender: str, role: str, content: str) -> None:
        self.history[sender].append((role, normalize_text(content)))

    def generate(self, sender: str, user_text: str) -> str:
        user_text = normalize_text(user_text)
        if not user_text:
            return ""

        if self.openclaw is not None:
            try:
                reply = normalize_text(self.openclaw.generate(user_text), 1200)
                if reply:
                    self._add_history(sender, "user", user_text)
                    self._add_history(sender, "assistant", reply)
                    return reply
            except Exception as exc:
                self.logger.warning("openclaw reply failed: %s", exc)

        if self.cfg.codex_cli_enabled:
            try:
                reply = normalize_text(self._generate_via_codex_cli(sender, user_text), 1200)
                if reply:
                    self._add_history(sender, "user", user_text)
                    self._add_history(sender, "assistant", reply)
                    return reply
            except Exception as exc:
                self.logger.warning("codex-cli reply failed: %s", exc)

        if self.client is None:
            if not self.cfg.fallback_when_no_key:
                raise RuntimeError("OPENAI_API_KEY missing and fallback disabled")
            reply = fallback_reply(user_text)
            self._add_history(sender, "user", user_text)
            self._add_history(sender, "assistant", reply)
            return reply

        resp = self.client.chat.completions.create(
            model=self.cfg.openai_model,
            messages=self._build_messages(sender, user_text),
            temperature=self.cfg.temperature,
            max_tokens=self.cfg.max_tokens,
        )
        reply = normalize_text((resp.choices[0].message.content or "").strip(), 1200)
        if self.cfg.reply_prefix:
            reply = f"{self.cfg.reply_prefix}{reply}"
        self._add_history(sender, "user", user_text)
        self._add_history(sender, "assistant", reply)
        return reply


def _query_signature() -> str:
    return (request.args.get("msg_signature") or request.args.get("signature") or "").strip()


def _query_timestamp_nonce() -> Tuple[str, str]:
    timestamp = (request.args.get("timestamp") or "").strip()
    nonce = (request.args.get("nonce") or "").strip()
    return timestamp, nonce


def create_app(cfg: GatewayConfig, logger: logging.Logger) -> Flask:
    app = Flask(__name__)
    crypto = WeChatCrypto(cfg.token, cfg.aes_key, cfg.corp_id)
    engine = BackendReplyEngine(load_model_config_from_env(), logger)
    seen_lock = threading.Lock()
    seen_ids: Deque[str] = deque(maxlen=512)
    seen_set: Set[str] = set()

    def mark_seen(msg_id: str) -> bool:
        msg_id = msg_id.strip()
        if not msg_id:
            return True
        with seen_lock:
            if msg_id in seen_set:
                return False
            seen_ids.append(msg_id)
            seen_set.add(msg_id)
            while len(seen_ids) > seen_ids.maxlen:
                old = seen_ids.popleft()
                seen_set.discard(old)
        return True

    def send_text_active(to_user: str, content: str) -> None:
        if not cfg.secret or not cfg.agent_id:
            logger.error("cannot active-send reply: WECOM_SECRET/WECOM_AGENT_ID missing")
            return
        payload = normalize_text(content, 1500)
        if not payload:
            return
        try:
            client = WeChatClient(cfg.corp_id, cfg.secret)
            result = client.message.send_text(cfg.agent_id, to_user, payload)
            if int(result.get("errcode", 1)) != 0:
                logger.error("active-send failed sender=%s result=%s", to_user, result)
        except Exception:
            logger.exception("active-send exception sender=%s", to_user)

    def spawn_async_reply(sender: str, incoming: str) -> None:
        def _runner() -> None:
            try:
                reply_text = engine.generate(sender or "unknown", incoming)
            except Exception:
                logger.exception("reply generation failed sender=%s", sender)
                reply_text = "系统繁忙，请稍后再试。"
            reply_text = normalize_text(reply_text, 1200)
            if reply_text:
                send_text_active(sender, reply_text)

        t = threading.Thread(target=_runner, name=f"wecom-reply-{int(time.time()*1000)}", daemon=True)
        t.start()

    @app.get("/healthz")
    def healthz() -> Response:
        return Response("ok", mimetype="text/plain")

    @app.get("/wecom/agent")
    def verify_url() -> Response:
        signature = _query_signature()
        timestamp, nonce = _query_timestamp_nonce()
        echo_str = (request.args.get("echostr") or "").strip()
        if not signature or not timestamp or not nonce or not echo_str:
            return Response("missing signature params", status=400, mimetype="text/plain")

        try:
            plain_echo = crypto.check_signature(signature, timestamp, nonce, echo_str)
            return Response(plain_echo, mimetype="text/plain")
        except Exception:
            logger.exception("callback verification failed")
            return Response("invalid signature", status=401, mimetype="text/plain")

    @app.post("/wecom/agent")
    def handle_message() -> Response:
        signature = _query_signature()
        timestamp, nonce = _query_timestamp_nonce()
        if not timestamp or not nonce:
            return Response("missing timestamp/nonce", status=400, mimetype="text/plain")

        raw = request.get_data() or b""
        if not raw:
            return Response("success", mimetype="text/plain")

        encrypted = b"<Encrypt>" in raw

        try:
            if encrypted:
                if not signature:
                    return Response("missing signature", status=400, mimetype="text/plain")
                xml_text = crypto.decrypt_message(raw, signature, timestamp, nonce)
            else:
                xml_text = raw.decode("utf-8", errors="ignore")

            msg = parse_message(xml_text)
        except Exception:
            logger.exception("failed to parse incoming message")
            return Response("success", mimetype="text/plain")

        sender = normalize_text(getattr(msg, "source", ""), 128)
        msg_type = normalize_text(getattr(msg, "type", "unknown"), 32).lower()
        event_type = normalize_text(getattr(msg, "event", ""), 64).lower()
        msg_id = normalize_text(
            str(getattr(msg, "id", "") or getattr(msg, "msg_id", "") or ""),
            128,
        )

        if sender:
            save_last_sender(sender)

        if cfg.allowlist and sender not in cfg.allowlist:
            logger.info("ignored sender outside allowlist: %s", sender)
            return Response("success", mimetype="text/plain")

        if msg_type == "text":
            incoming = normalize_text(getattr(msg, "content", ""), 1200)
            logger.info("recv text sender=%s len=%s", sender, len(incoming))
            if not incoming:
                return Response("success", mimetype="text/plain")
            if msg_id and not mark_seen(msg_id):
                logger.info("dedupe skip sender=%s msg_id=%s", sender, msg_id)
                return Response("success", mimetype="text/plain")
            # Important: return quickly to avoid WeCom callback timeout, then active-send reply.
            spawn_async_reply(sender, incoming)
            return Response("success", mimetype="text/plain")

        elif msg_type == "event" and event_type in {"enter_agent", "subscribe"}:
            reply_text = cfg.welcome_text
        else:
            return Response("success", mimetype="text/plain")

        # Keep event welcome on sync reply (usually fast and infrequent).
        reply_text = normalize_text(reply_text, 1200)
        if not reply_text:
            return Response("success", mimetype="text/plain")

        reply = TextReply(content=reply_text, message=msg)
        xml_reply = reply.render()

        if encrypted:
            encrypted_reply = crypto.encrypt_message(xml_reply, nonce, timestamp)
            return Response(encrypted_reply, mimetype="application/xml")
        return Response(xml_reply, mimetype="application/xml")

    return app


def resolve_to_user(raw_to: str, cfg: GatewayConfig) -> str:
    raw_to = (raw_to or "").strip()
    if raw_to and raw_to != "@last":
        return raw_to

    state = load_state()
    if state.get("last_sender"):
        return str(state["last_sender"]).strip()

    if len(cfg.allowlist) == 1:
        return next(iter(cfg.allowlist))

    raise ValueError("No target user available. Pass --to USERID or receive one message first.")


def cmd_doctor(cfg: GatewayConfig, host: str, port: int) -> int:
    run_ok, run_missing = validate_for_run(cfg)
    send_ok, send_missing = validate_for_send(cfg)
    has_key = bool(os.getenv("OPENAI_API_KEY", "").strip())

    print("doctor.start")
    print(f"run_ready={run_ok}, run_missing={run_missing}")
    print(f"send_ready={send_ok}, send_missing={send_missing}")
    print(f"openai_key={'set' if has_key else 'missing'}")
    print(
        "openclaw_enabled="
        f"{cfg.openclaw_enabled}, session={cfg.openclaw_session_key}, timeout_ms={cfg.openclaw_timeout_ms}"
    )
    print(
        "codex_cli_enabled="
        f"{cfg.codex_cli_enabled}, timeout_ms={cfg.codex_cli_timeout_ms}, cmd={cfg.codex_cli_command}"
    )
    print(f"callback_url=http://<your-public-host>:{port}/wecom/agent")
    print(f"local_health=http://{host}:{port}/healthz")
    print(f"allowlist={sorted(cfg.allowlist)}")
    print("doctor.done")
    return 0


def cmd_send(cfg: GatewayConfig, to_user: str, text: str) -> int:
    ok, missing = validate_for_send(cfg)
    if not ok:
        raise RuntimeError(f"Missing env for send: {', '.join(missing)}")

    target = resolve_to_user(to_user, cfg)
    payload = normalize_text(text, 1500)
    if not payload:
        raise ValueError("Empty text is not allowed")

    client = WeChatClient(cfg.corp_id, cfg.secret)
    result = client.message.send_text(cfg.agent_id, target, payload)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if int(result.get("errcode", 1)) == 0 else 1


def parse_args() -> argparse.Namespace:
    raw_args = sys.argv[1:]
    env_file = str(DEFAULT_ENV_PATH)
    if "--env-file" in raw_args:
        idx = raw_args.index("--env-file")
        if idx + 1 >= len(raw_args):
            raise ValueError("Missing value for --env-file")
        env_file = raw_args[idx + 1]
        del raw_args[idx: idx + 2]

    # Load selected env file before building argparse defaults.
    load_dotenv(env_file, override=False)

    p = argparse.ArgumentParser(description="WeCom callback auto-reply gateway")

    sub = p.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Start callback server")
    p_run.add_argument("--host", default=os.getenv("WECOM_BIND_HOST", "0.0.0.0"))
    p_run.add_argument("--port", type=int, default=_to_int(os.getenv("WECOM_BIND_PORT", "28789"), 28789))
    p_run.add_argument("--debug", action="store_true")

    p_doc = sub.add_parser("doctor", help="Validate environment")
    p_doc.add_argument("--host", default=os.getenv("WECOM_BIND_HOST", "0.0.0.0"))
    p_doc.add_argument("--port", type=int, default=_to_int(os.getenv("WECOM_BIND_PORT", "28789"), 28789))

    p_send = sub.add_parser("send", help="Proactively send one message")
    p_send.add_argument("--to", default="@last", help="Userid, or @last")
    p_send.add_argument("--text", required=True, help="Message content")

    args = p.parse_args(raw_args)
    args.env_file = env_file
    return args


def setup_logger() -> logging.Logger:
    logger = logging.getLogger("wecom_gateway")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


def main() -> int:
    args = parse_args()
    cfg = load_config(Path(args.env_file))

    if args.command == "doctor":
        return cmd_doctor(cfg, args.host, args.port)

    if args.command == "send":
        return cmd_send(cfg, args.to, args.text)

    if args.command == "run":
        ok, missing = validate_for_run(cfg)
        if not ok:
            raise RuntimeError(f"Missing env for run: {', '.join(missing)}")
        logger = setup_logger()
        app = create_app(cfg, logger)
        app.run(host=args.host, port=args.port, debug=args.debug)
        return 0

    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
