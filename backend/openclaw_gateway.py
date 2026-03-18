from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, load_pem_private_key, load_pem_public_key

try:
    import websockets
except Exception:  # pragma: no cover - dependency handled at runtime
    websockets = None


class OpenClawGatewayError(RuntimeError):
    pass


@dataclass
class OpenClawGatewayConfig:
    state_dir: str
    workspace_dir: str
    url: str
    origin: str
    timeout_ms: int
    client_id: str
    client_mode: str


def discover_openclaw_state_dir(configured: str, workspace_dir: str) -> Path:
    candidates: List[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend(
        [
            Path.home() / ".openclaw",
            Path(os.environ.get("APPDATA", "")) / "Antigravity" / "openclaw",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Antigravity" / "openclaw",
            Path(os.environ.get("LOCALAPPDATA", "")) / "com.lbjlaq.antigravity-tools" / "openclaw",
            Path(workspace_dir).expanduser().resolve() / ".openclaw",
            Path(workspace_dir).expanduser().resolve() / ".." / ".openclaw",
        ]
    )
    for candidate in candidates:
        candidate = candidate.resolve()
        if (candidate / "openclaw.json").exists() and (candidate / "identity" / "device.json").exists():
            return candidate
    raise OpenClawGatewayError("OpenClaw state dir not found; set OPENCLAW_STATE_DIR")


class OpenClawGatewayClient:
    def __init__(self, config: OpenClawGatewayConfig) -> None:
        self.config = config

    async def send_message(self, session_key: str, text: str) -> str:
        runtime = self._load_runtime()
        timeout_ms = max(5000, int(self.config.timeout_ms))
        async with self._connect(runtime) as ws:
            await self._connect_session(ws, runtime)
            run_id = f"assistant-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
            response = await self._rpc_request(
                ws,
                "chat.send",
                {
                    "sessionKey": str(session_key),
                    "message": str(text),
                    "deliver": False,
                    "timeoutMs": timeout_ms,
                    "idempotencyKey": run_id,
                },
                timeout_ms=max(timeout_ms, 15000),
            )
            if not response.get("ok"):
                raise OpenClawGatewayError(f"OpenClaw chat.send failed: {response.get('error')}")
            return await self._wait_for_final(ws, str(session_key), run_id, timeout_ms)

    async def reset_session(self, session_key: str) -> None:
        runtime = self._load_runtime()
        async with self._connect(runtime) as ws:
            await self._connect_session(ws, runtime)
            response = await self._rpc_request(ws, "sessions.reset", {"key": str(session_key)}, timeout_ms=10000)
            if not response.get("ok"):
                raise OpenClawGatewayError(f"OpenClaw sessions.reset failed: {response.get('error')}")

    def _load_runtime(self) -> Dict[str, str]:
        state_dir = discover_openclaw_state_dir(self.config.state_dir, self.config.workspace_dir)
        openclaw_json = json.loads((state_dir / "openclaw.json").read_text(encoding="utf-8"))
        device_json = json.loads((state_dir / "identity" / "device.json").read_text(encoding="utf-8"))
        auth_json = json.loads((state_dir / "identity" / "device-auth.json").read_text(encoding="utf-8"))
        gateway_port = int(openclaw_json.get("gateway", {}).get("port", 18789))
        url = self.config.url.strip() or f"ws://127.0.0.1:{gateway_port}"
        origin = self.config.origin.strip() or f"http://127.0.0.1:{gateway_port}"
        gateway_token = str(openclaw_json.get("gateway", {}).get("auth", {}).get("token", "") or "").strip()
        device_token = str(auth_json.get("tokens", {}).get("operator", {}).get("token", "") or "").strip()
        token = gateway_token or device_token
        if not token:
            raise OpenClawGatewayError("OpenClaw token missing")
        return {
            "url": url,
            "origin": origin,
            "token": token,
            "device_id": str(device_json.get("deviceId", "") or "").strip(),
            "private_key_pem": str(device_json.get("privateKeyPem", "") or ""),
            "public_key_pem": str(device_json.get("publicKeyPem", "") or ""),
        }

    def _connect(self, runtime: Dict[str, str]):
        if websockets is None:
            raise OpenClawGatewayError("websockets dependency missing")
        return websockets.connect(runtime["url"], origin=runtime["origin"], max_size=20_000_000)

    async def _connect_session(self, ws, runtime: Dict[str, str]) -> None:
        private_key = load_pem_private_key(runtime["private_key_pem"].encode("utf-8"), password=None)
        public_key = load_pem_public_key(runtime["public_key_pem"].encode("utf-8"))
        public_raw = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
        public_b64 = self._b64url_no_pad(public_raw)
        if not runtime["device_id"]:
            raise OpenClawGatewayError("OpenClaw device id missing")
        nonce: Optional[str] = None
        try:
            first = json.loads(await asyncio.wait_for(ws.recv(), timeout=1.2))
            if first.get("type") == "event" and first.get("event") == "connect.challenge":
                nonce = str((first.get("payload") or {}).get("nonce") or "") or None
        except Exception:
            nonce = None
        scopes = ["operator.admin", "operator.approvals", "operator.pairing", "operator.read", "operator.write"]
        signed_at = int(time.time() * 1000)
        version = "v2" if nonce else "v1"
        sign_input = self._make_sign_input(
            version=version,
            device_id=runtime["device_id"],
            client_id=self.config.client_id,
            client_mode=self.config.client_mode,
            role="operator",
            scopes=scopes,
            signed_at_ms=signed_at,
            token=runtime["token"],
            nonce=nonce,
        ).encode("utf-8")
        signature = self._b64url_no_pad(private_key.sign(sign_input))
        response = await self._rpc_request(
            ws,
            "connect",
            {
                "minProtocol": 3,
                "maxProtocol": 3,
                "client": {
                    "id": self.config.client_id,
                    "version": "dev",
                    "platform": "Win32",
                    "mode": self.config.client_mode,
                },
                "role": "operator",
                "scopes": scopes,
                "caps": [],
                "auth": {"token": runtime["token"]},
                "device": {
                    "id": runtime["device_id"],
                    "publicKey": public_b64,
                    "signature": signature,
                    "signedAt": signed_at,
                    **({"nonce": nonce} if nonce else {}),
                },
                "userAgent": "chonggou-backend",
                "locale": "zh-CN",
            },
            timeout_ms=10000,
        )
        if not response.get("ok"):
            raise OpenClawGatewayError(f"OpenClaw connect failed: {response.get('error')}")

    async def _wait_for_final(self, ws, session_key: str, run_id: str, timeout_ms: int) -> str:
        deadline = time.monotonic() + timeout_ms / 1000.0
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 2.0))
            except asyncio.TimeoutError:
                continue
            msg = json.loads(raw)
            if msg.get("type") != "event" or msg.get("event") != "chat":
                continue
            payload = msg.get("payload") or {}
            if payload.get("runId") != run_id:
                continue
            state = str(payload.get("state") or "")
            if state == "final":
                return self._extract_text_from_message(payload.get("message") or {})
            if state in {"error", "aborted"}:
                raise OpenClawGatewayError(f"OpenClaw chat {state}: {payload.get('errorMessage')}")
        try:
            await self._rpc_request(ws, "chat.abort", {"sessionKey": session_key, "runId": run_id}, timeout_ms=3000)
        except Exception:
            pass
        raise OpenClawGatewayError("OpenClaw chat timed out")

    async def _rpc_request(self, ws, method: str, params: Dict[str, object], timeout_ms: int) -> Dict[str, object]:
        req_id = str(uuid.uuid4())
        await ws.send(json.dumps({"type": "req", "id": req_id, "method": method, "params": params}, ensure_ascii=False))
        deadline = time.monotonic() + max(1.0, timeout_ms / 1000.0)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OpenClawGatewayError(f"OpenClaw rpc timeout: {method}")
            raw = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 2.0))
            msg = json.loads(raw)
            if msg.get("type") == "res" and msg.get("id") == req_id:
                return msg

    @staticmethod
    def _extract_text_from_message(message_obj: Dict[str, object]) -> str:
        parts = message_obj.get("content") if isinstance(message_obj, dict) else None
        if not isinstance(parts, list):
            return ""
        chunks: List[str] = []
        for part in parts:
            if isinstance(part, dict) and part.get("type") == "text":
                chunks.append(str(part.get("text") or ""))
        return "".join(chunks).strip()

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
        parts = [version, device_id, client_id, client_mode, role, ",".join(scopes), str(signed_at_ms), token or ""]
        if version == "v2":
            parts.append(nonce or "")
        return "|".join(parts)
