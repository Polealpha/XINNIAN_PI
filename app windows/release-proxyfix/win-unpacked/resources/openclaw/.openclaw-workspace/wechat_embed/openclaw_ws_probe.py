#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import pathlib
import time
import uuid

import websockets
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_private_key,
    load_pem_public_key,
)


def b64url_no_pad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def load_json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def make_sign_input(
    version: str,
    device_id: str,
    client_id: str,
    client_mode: str,
    role: str,
    scopes: list[str],
    signed_at_ms: int,
    token: str,
    nonce: str | None,
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


async def rpc_request(ws, method: str, params: dict) -> dict:
    req_id = str(uuid.uuid4())
    await ws.send(
        json.dumps(
            {
                "type": "req",
                "id": req_id,
                "method": method,
                "params": params,
            },
            ensure_ascii=False,
        )
    )
    while True:
        data = json.loads(await ws.recv())
        if data.get("type") == "res" and data.get("id") == req_id:
            return data


async def run_probe(message: str, session_key: str) -> int:
    state_dir = pathlib.Path.home() / ".openclaw"
    openclaw_json = load_json(state_dir / "openclaw.json")
    identity = load_json(state_dir / "identity" / "device.json")
    auth_state = load_json(state_dir / "identity" / "device-auth.json")

    url = f"ws://127.0.0.1:{int(openclaw_json.get('gateway', {}).get('port', 18789))}"
    # Priority: use gateway token first; fallback to device token.
    gateway_token = (
        openclaw_json.get("gateway", {}).get("auth", {}).get("token", "") or ""
    ).strip()
    device_token = (
        auth_state.get("tokens", {}).get("operator", {}).get("token", "") or ""
    ).strip()
    auth_token = gateway_token or device_token

    private_key = load_pem_private_key(identity["privateKeyPem"].encode("utf-8"), password=None)
    public_key = load_pem_public_key(identity["publicKeyPem"].encode("utf-8"))
    public_raw = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    public_b64 = b64url_no_pad(public_raw)
    device_id = identity["deviceId"]

    client_id = "openclaw-control-ui"
    client_mode = "webchat"
    role = "operator"
    scopes = [
        "operator.admin",
        "operator.approvals",
        "operator.pairing",
        "operator.read",
        "operator.write",
    ]

    async with websockets.connect(
        url,
        origin=f"http://127.0.0.1:{int(openclaw_json.get('gateway', {}).get('port', 18789))}",
        max_size=20_000_000,
    ) as ws:
        nonce = None
        try:
            first = json.loads(await asyncio.wait_for(ws.recv(), timeout=1.5))
            if first.get("type") == "event" and first.get("event") == "connect.challenge":
                nonce = (first.get("payload") or {}).get("nonce")
                print(f"challenge_nonce={nonce}")
        except Exception:
            pass

        signed_at = int(time.time() * 1000)
        version = "v2" if nonce else "v1"
        sign_input = make_sign_input(
            version=version,
            device_id=device_id,
            client_id=client_id,
            client_mode=client_mode,
            role=role,
            scopes=scopes,
            signed_at_ms=signed_at,
            token=auth_token,
            nonce=nonce,
        ).encode("utf-8")
        signature = b64url_no_pad(private_key.sign(sign_input))

        connect_res = await rpc_request(
            ws,
            "connect",
            {
                "minProtocol": 3,
                "maxProtocol": 3,
                "client": {
                    "id": client_id,
                    "version": "dev",
                    "platform": "Win32",
                    "mode": client_mode,
                },
                "role": role,
                "scopes": scopes,
                "caps": [],
                "auth": {"token": auth_token},
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
        )
        print("connect_res=", json.dumps(connect_res, ensure_ascii=False))
        connected = bool(connect_res.get("ok"))
        if not connected:
            return 2

        run_id = f"probe-{int(time.time() * 1000)}"
        send_res = await rpc_request(
            ws,
            "chat.send",
            {
                "sessionKey": session_key,
                "message": message,
                "deliver": False,
                "idempotencyKey": run_id,
            },
        )
        print("send_res=", json.dumps(send_res, ensure_ascii=False))
        sent_ok = bool(send_res.get("ok"))
        if not sent_ok:
            return 3

        wait_res = await rpc_request(
            ws,
            "agent.wait",
            {
                "runId": run_id,
                "timeoutMs": 90_000,
            },
        )
        print("wait_res=", json.dumps(wait_res, ensure_ascii=False))

        final_text = ""
        deadline = time.time() + 15
        while time.time() < deadline:
            history_res = await rpc_request(
                ws,
                "chat.history",
                {"sessionKey": session_key, "limit": 30},
            )
            payload = history_res.get("payload") or {}
            messages = payload.get("messages") or []
            for msg_obj in reversed(messages):
                if msg_obj.get("role") != "assistant":
                    continue
                parts = msg_obj.get("content") or []
                text_parts = []
                for part in parts:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text_parts.append(str(part.get("text") or ""))
                candidate = "".join(text_parts).strip()
                if candidate:
                    final_text = candidate
                    break

            if final_text:
                break
            await asyncio.sleep(2.0)

        print("final_text=", final_text)
        return 0 if final_text else 4


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--message", default="请只回复pong")
    parser.add_argument("--session", default="agent:main:main")
    args = parser.parse_args()
    return asyncio.run(run_probe(args.message, args.session))


if __name__ == "__main__":
    raise SystemExit(main())
