from __future__ import annotations

import asyncio
import contextlib
import json
import shlex
import shutil
import subprocess
from typing import Any, Iterator

import httpx
from fastapi import HTTPException
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .settings import (
    GEMMA_PROVIDER_CONTEXT_WINDOW,
    GEMMA_PROVIDER_MODEL_ID,
    GEMMA_PROVIDER_OUTPUT_CAP,
    GEMMA_PROVIDER_PUBLIC_CONTEXT_WINDOW,
    GEMMA_PROVIDER_PUBLIC_MAX_TOKENS,
    GEMMA_PROVIDER_REMOTE_HTTP_BASE_URL,
    GEMMA_PROVIDER_REMOTE_SSH_HOST,
    GEMMA_PROVIDER_REMOTE_SSH_PASSWORD,
    GEMMA_PROVIDER_REMOTE_SSH_PORT,
    GEMMA_PROVIDER_REMOTE_SSH_USER,
    GEMMA_PROVIDER_REQUEST_TIMEOUT_SEC,
    GEMMA_PROVIDER_UPSTREAM_BASE_URL,
)


def _normalize_public_model_metadata(item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item or {})
    normalized["id"] = str(normalized.get("id") or GEMMA_PROVIDER_MODEL_ID)
    normalized["max_model_len"] = int(GEMMA_PROVIDER_PUBLIC_CONTEXT_WINDOW)
    normalized["context_window"] = int(GEMMA_PROVIDER_PUBLIC_CONTEXT_WINDOW)
    normalized["max_tokens"] = int(GEMMA_PROVIDER_PUBLIC_MAX_TOKENS)
    return normalized


def _upstream_models_url() -> str:
    return f"{GEMMA_PROVIDER_UPSTREAM_BASE_URL.rstrip('/')}/models"


def _upstream_chat_url() -> str:
    return f"{GEMMA_PROVIDER_UPSTREAM_BASE_URL.rstrip('/')}/chat/completions"


def _remote_upstream_url(path: str) -> str:
    return f"{GEMMA_PROVIDER_REMOTE_HTTP_BASE_URL.rstrip('/')}/{path.lstrip('/')}"


def _run_remote_json_request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    plink = shutil.which("plink.exe") or shutil.which("plink")
    if not plink:
        raise RuntimeError("plink_not_found")

    url = _remote_upstream_url(path)
    status_marker = "__GEMMA_STATUS__:"
    remote_command = "curl -sS {url} -w '\\n{marker}%{{http_code}}'".format(
        url=shlex.quote(url),
        marker=status_marker,
    )
    stdin_text = None
    if method.upper() != "GET":
        remote_command = (
            "curl -sS -X {method} {url} -H 'Content-Type: application/json' "
            "--data-binary @- -w '\\n{marker}%{{http_code}}'"
        ).format(
            method=shlex.quote(method.upper()),
            url=shlex.quote(url),
            marker=status_marker,
        )
        stdin_text = json.dumps(payload or {}, ensure_ascii=False)

    proc = subprocess.run(
        [
            plink,
            "-pw",
            GEMMA_PROVIDER_REMOTE_SSH_PASSWORD,
            "-batch",
            "-P",
            str(GEMMA_PROVIDER_REMOTE_SSH_PORT),
            f"{GEMMA_PROVIDER_REMOTE_SSH_USER}@{GEMMA_PROVIDER_REMOTE_SSH_HOST}",
            remote_command,
        ],
        capture_output=True,
        text=True,
        input=stdin_text,
        timeout=max(60, int(GEMMA_PROVIDER_REQUEST_TIMEOUT_SEC)),
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"remote_exec_failed:{stderr or proc.returncode}")

    raw = (proc.stdout or "").strip()
    if not raw:
        raise RuntimeError("remote_empty_response")
    if status_marker not in raw:
        raise RuntimeError("remote_missing_status_marker")
    body_text, status_text = raw.rsplit(status_marker, 1)
    body_text = body_text.rstrip()
    try:
        status = int(status_text.strip())
    except ValueError as exc:
        raise RuntimeError(f"remote_invalid_status:{status_text}") from exc
    try:
        body = json.loads(body_text)
    except json.JSONDecodeError:
        body = {"raw": body_text}
    if status >= 400:
        raise HTTPException(status_code=status, detail=body)
    if not isinstance(body, dict):
        raise RuntimeError("remote_non_dict_payload")
    return body


def _iter_remote_stream_request(path: str, payload: dict[str, Any]) -> Iterator[bytes]:
    plink = shutil.which("plink.exe") or shutil.which("plink")
    if not plink:
        raise RuntimeError("plink_not_found")
    url = _remote_upstream_url(path)
    remote_command = (
        "curl -sS -N -X POST {url} -H 'Content-Type: application/json' --data-binary @-"
    ).format(url=shlex.quote(url))
    proc = subprocess.Popen(
        [
            plink,
            "-pw",
            GEMMA_PROVIDER_REMOTE_SSH_PASSWORD,
            "-batch",
            "-P",
            str(GEMMA_PROVIDER_REMOTE_SSH_PORT),
            f"{GEMMA_PROVIDER_REMOTE_SSH_USER}@{GEMMA_PROVIDER_REMOTE_SSH_HOST}",
            remote_command,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )
    try:
        stdin_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if proc.stdin is not None:
            proc.stdin.write(stdin_bytes)
            proc.stdin.close()
        if proc.stdout is None:
            raise RuntimeError("remote_stream_stdout_unavailable")
        while True:
            chunk = proc.stdout.read(4096)
            if not chunk:
                break
            yield chunk
        returncode = proc.wait(timeout=max(60, int(GEMMA_PROVIDER_REQUEST_TIMEOUT_SEC)))
        if returncode != 0:
            stderr = b""
            if proc.stderr is not None:
                stderr = proc.stderr.read() or b""
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"remote_stream_failed:{detail or returncode}")
    finally:
        if proc.poll() is None:
            proc.kill()
        with contextlib.suppress(Exception):
            proc.wait(timeout=1)


async def stream_upstream_chat(payload: dict[str, Any]) -> StreamingResponse:
    return StreamingResponse(
        _iter_remote_stream_request("chat/completions", payload),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


async def anthropic_sse_response_from_openai_stream(openai_payload: dict[str, Any]) -> StreamingResponse:
    async def _iter() -> Any:
        message_id = "msg_stream"
        model_name = openai_payload.get("model", GEMMA_PROVIDER_MODEL_ID)
        started = False
        block_started = False
        usage_output_tokens = 0

        def _emit(event: str, data: dict[str, Any]) -> bytes:
            return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")

        yield _emit(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": message_id,
                    "type": "message",
                    "role": "assistant",
                    "model": model_name,
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                },
            },
        )

        async def _chunks() -> Any:
            for chunk in _iter_remote_stream_request("chat/completions", openai_payload):
                yield chunk

        buffer = ""
        async for raw_chunk in _chunks():
            buffer += raw_chunk.decode("utf-8", errors="replace")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line or not line.startswith("data:"):
                    continue
                data_text = line[5:].strip()
                if data_text == "[DONE]":
                    if block_started:
                        yield _emit("content_block_stop", {"index": 0})
                    yield _emit(
                        "message_delta",
                        {
                            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                            "usage": {"output_tokens": usage_output_tokens},
                        },
                    )
                    yield _emit("message_stop", {})
                    return
                try:
                    payload = json.loads(data_text)
                except json.JSONDecodeError:
                    continue
                if not started:
                    message_id = f"msg_{payload.get('id', 'stream')}"
                    started = True
                choices = payload.get("choices") or []
                if not choices:
                    continue
                choice = choices[0] or {}
                delta = choice.get("delta") or {}
                text = str(delta.get("content") or "")
                if text:
                    if not block_started:
                        yield _emit(
                            "content_block_start",
                            {"index": 0, "content_block": {"type": "text", "text": ""}},
                        )
                        block_started = True
                    usage_output_tokens += 1
                    yield _emit(
                        "content_block_delta",
                        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}},
                    )

    return StreamingResponse(
        _iter(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


async def _request_upstream_json(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(GEMMA_PROVIDER_REQUEST_TIMEOUT_SEC, connect=10.0)) as client:
            if method.upper() == "GET":
                response = await client.get(f"{GEMMA_PROVIDER_UPSTREAM_BASE_URL.rstrip('/')}/{path.lstrip('/')}")
            else:
                response = await client.post(
                    f"{GEMMA_PROVIDER_UPSTREAM_BASE_URL.rstrip('/')}/{path.lstrip('/')}",
                    json=payload,
                )
            response.raise_for_status()
            body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError("invalid_upstream_payload")
        return body
    except HTTPException:
        raise
    except Exception:
        return await asyncio.to_thread(_run_remote_json_request, method, path, payload)


async def fetch_upstream_models() -> dict[str, Any]:
    payload = await _request_upstream_json("GET", "models")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="invalid upstream models payload")
    data = payload.get("data")
    if isinstance(data, list):
        payload["data"] = [
            _normalize_public_model_metadata(item) if str((item or {}).get("id") or "").strip() == GEMMA_PROVIDER_MODEL_ID else item
            for item in data
        ]
    return payload


async def models_response() -> JSONResponse:
    payload = await fetch_upstream_models()
    return JSONResponse(payload)


async def model_detail_response(model_id: str) -> JSONResponse:
    payload = await fetch_upstream_models()
    candidates = [str(model_id or "").strip()]
    if "/" in candidates[0]:
        candidates.append(candidates[0].rsplit("/", 1)[-1])
    for item in payload.get("data", []):
        item_id = str(item.get("id") or "").strip()
        if item_id in candidates:
            return JSONResponse(item)
    raise HTTPException(status_code=404, detail="model_not_found")


def _anthropic_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        if content.get("type") == "text":
            return str(content.get("text", ""))
        return str(content.get("text", ""))
    if isinstance(content, list):
        return "".join(_anthropic_text(item) for item in content)
    return str(content)


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def _trim_text_for_budget(text: str, budget_tokens: int, *, keep_tail: bool) -> str:
    if not text or budget_tokens <= 0:
        return ""
    keep_chars = max(256, budget_tokens * 4)
    if len(text) <= keep_chars:
        return text
    return text[-keep_chars:] if keep_tail else text[:keep_chars]


def _budget_messages(messages: list[dict[str, str]], budget_tokens: int) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    remaining = max(64, int(budget_tokens))
    for item in reversed(messages):
        text = str(item.get("content") or "")
        cost = _estimate_tokens(text)
        if cost > remaining:
            text = _trim_text_for_budget(text, remaining, keep_tail=True)
            cost = _estimate_tokens(text)
        if not text or cost <= 0:
            continue
        selected.append({"role": str(item.get("role") or "user"), "content": text})
        remaining -= cost
        if remaining <= 0:
            break
    return list(reversed(selected))


def anthropic_request_to_openai(payload: dict[str, Any]) -> dict[str, Any]:
    system_text = _trim_text_for_budget(_anthropic_text(payload.get("system")), 900, keep_tail=False)
    messages: list[dict[str, str]] = []
    if system_text:
        messages.append({"role": "system", "content": system_text})

    non_system_messages: list[dict[str, str]] = []
    for item in payload.get("messages", []) or []:
        role = str(item.get("role") or "user")
        text = _anthropic_text(item.get("content"))
        if text:
            non_system_messages.append({"role": role, "content": text})

    remaining_budget = max(256, GEMMA_PROVIDER_CONTEXT_WINDOW - _estimate_tokens(system_text) - 512)
    messages.extend(_budget_messages(non_system_messages, remaining_budget))

    requested = int(payload.get("max_tokens", payload.get("max_completion_tokens", GEMMA_PROVIDER_OUTPUT_CAP)))
    input_tokens = sum(_estimate_tokens(item.get("content", "")) for item in messages)
    max_tokens = max(64, min(requested, GEMMA_PROVIDER_OUTPUT_CAP, GEMMA_PROVIDER_CONTEXT_WINDOW - input_tokens - 64))
    body: dict[str, Any] = {
        "model": str(payload.get("model") or GEMMA_PROVIDER_MODEL_ID),
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": bool(payload.get("stream", False)),
    }
    if "temperature" in payload:
        body["temperature"] = payload["temperature"]
    if payload.get("stop_sequences"):
        body["stop"] = payload["stop_sequences"]
    return body


def cap_openai_payload(payload: dict[str, Any]) -> dict[str, Any]:
    body = dict(payload)
    messages = []
    for item in body.get("messages") or []:
        text = _anthropic_text(item.get("content"))
        if text:
            messages.append({"role": str(item.get("role") or "user"), "content": text})
    body["messages"] = _budget_messages(messages, GEMMA_PROVIDER_CONTEXT_WINDOW - GEMMA_PROVIDER_OUTPUT_CAP - 64)
    requested = int(body.get("max_completion_tokens", body.get("max_tokens", GEMMA_PROVIDER_OUTPUT_CAP)))
    input_tokens = sum(_estimate_tokens(item.get("content", "")) for item in body["messages"])
    capped = max(64, min(requested, GEMMA_PROVIDER_OUTPUT_CAP, GEMMA_PROVIDER_CONTEXT_WINDOW - input_tokens - 64))
    body["max_tokens"] = capped
    body["max_completion_tokens"] = capped
    body["model"] = str(body.get("model") or GEMMA_PROVIDER_MODEL_ID)
    return body


def anthropic_message_response(openai_payload: dict[str, Any]) -> dict[str, Any]:
    choice = (openai_payload.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = str(message.get("content") or "")
    usage = openai_payload.get("usage") or {}
    finish_reason = choice.get("finish_reason")
    stop_reason = "max_tokens" if finish_reason in {"length", "max_tokens"} else "end_turn"
    return {
        "id": f"msg_{openai_payload.get('id', 'gemma')}",
        "type": "message",
        "role": "assistant",
        "model": openai_payload.get("model", GEMMA_PROVIDER_MODEL_ID),
        "content": [{"type": "text", "text": content}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }


def anthropic_sse_response(openai_payload: dict[str, Any], openai_response: dict[str, Any]) -> StreamingResponse:
    async def _iter() -> bytes:
        message_id = f"msg_{openai_response.get('id', 'stream')}"
        model_name = openai_payload.get("model", GEMMA_PROVIDER_MODEL_ID)
        header = {
            "type": "message_start",
            "message": {
                "id": message_id,
                "type": "message",
                "role": "assistant",
                "model": model_name,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        }
        yield f"event: message_start\ndata: {json.dumps(header, ensure_ascii=False)}\n\n".encode("utf-8")
        text = str((((openai_response.get("choices") or [{}])[0]).get("message") or {}).get("content") or "")
        yield b"event: content_block_start\ndata: {\"index\":0,\"content_block\":{\"type\":\"text\",\"text\":\"\"}}\n\n"
        if text:
            delta_event = {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}
            yield f"event: content_block_delta\ndata: {json.dumps(delta_event, ensure_ascii=False)}\n\n".encode("utf-8")
        yield b"event: content_block_stop\ndata: {\"index\":0}\n\n"
        usage = openai_response.get("usage") or {}
        message_delta = {
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": usage.get("completion_tokens", 0)},
        }
        yield f"event: message_delta\ndata: {json.dumps(message_delta, ensure_ascii=False)}\n\n".encode("utf-8")
        yield b"event: message_stop\ndata: {}\n\n"

    return StreamingResponse(
        _iter(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


async def proxy_request_to_upstream(payload: dict[str, Any]) -> Response:
    if bool(payload.get("stream", False)):
        return await stream_upstream_chat(payload)
    data = await _request_upstream_json("POST", "chat/completions", payload)
    return JSONResponse(data)
