from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from sqlite3 import Connection
from typing import Any, Dict, List, Optional

import httpx

from .assistant_store import AssistantWorkspaceStore
from .openclaw_gateway import OpenClawGatewayClient, OpenClawGatewayConfig
from .settings import (
    DESKTOP_APP_ALLOWLIST_JSON,
    OPENCLAW_CLIENT_ID,
    OPENCLAW_CLIENT_MODE,
    OPENCLAW_GATEWAY_ORIGIN,
    OPENCLAW_GATEWAY_URL,
    OPENCLAW_STATE_DIR,
    OPENCLAW_TIMEOUT_MS,
    OPENCLAW_WORKSPACE_DIR,
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def normalize_surface(surface: str) -> str:
    raw = str(surface or "desktop").strip().lower()
    return raw if raw in {"desktop", "mobile", "wecom", "robot"} else "desktop"


def build_session_key(
    surface: str,
    user_id: int,
    explicit: Optional[str] = None,
    device_id: Optional[str] = None,
    sender_id: Optional[str] = None,
) -> str:
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    normalized = normalize_surface(surface)
    if normalized == "wecom":
        return f"wecom:{str(sender_id or user_id).strip()}"
    if normalized == "robot":
        return f"robot:{str(device_id or user_id).strip()}"
    return f"{normalized}:{int(user_id)}"


@dataclass
class ToolExecutionResult:
    name: str
    ok: bool
    detail: str
    data: Dict[str, object]


class AssistantService:
    def __init__(self) -> None:
        self.store = AssistantWorkspaceStore(OPENCLAW_WORKSPACE_DIR)
        self.gateway = OpenClawGatewayClient(
            OpenClawGatewayConfig(
                state_dir=OPENCLAW_STATE_DIR,
                workspace_dir=OPENCLAW_WORKSPACE_DIR,
                url=OPENCLAW_GATEWAY_URL,
                origin=OPENCLAW_GATEWAY_ORIGIN,
                timeout_ms=OPENCLAW_TIMEOUT_MS,
                client_id=OPENCLAW_CLIENT_ID,
                client_mode=OPENCLAW_CLIENT_MODE,
            )
        )
        try:
            self.app_allowlist = json.loads(DESKTOP_APP_ALLOWLIST_JSON)
        except Exception:
            self.app_allowlist = {}

    async def send_message(
        self,
        conn: Connection,
        user_id: int,
        text: str,
        surface: str,
        session_key: Optional[str] = None,
        device_id: Optional[str] = None,
        sender_id: Optional[str] = None,
        attachments: Optional[List[dict]] = None,
        metadata: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        normalized_surface = normalize_surface(surface)
        resolved_session_key = build_session_key(
            normalized_surface,
            user_id=user_id,
            explicit=session_key,
            device_id=device_id,
            sender_id=sender_id,
        )
        tool_results = await self._run_explicit_tools(conn, user_id, text, device_id=device_id)
        message = self._compose_openclaw_message(text, normalized_surface, resolved_session_key, tool_results, attachments, metadata)
        reply = await self.gateway.send_message(resolved_session_key, message)
        return {
            "surface": normalized_surface,
            "session_key": resolved_session_key,
            "text": reply.strip(),
            "tool_results": [result.__dict__ for result in tool_results],
            "timestamp_ms": _now_ms(),
        }

    async def reset_session(self, user_id: int, surface: str, session_key: Optional[str], device_id: Optional[str], sender_id: Optional[str]) -> Dict[str, object]:
        resolved_surface = normalize_surface(surface)
        resolved_key = build_session_key(resolved_surface, user_id=user_id, explicit=session_key, device_id=device_id, sender_id=sender_id)
        await self.gateway.reset_session(resolved_key)
        return {"surface": resolved_surface, "session_key": resolved_key}

    def get_session_status(self, conn: Connection, user_id: int, surface: str, session_key: Optional[str], device_id: Optional[str], sender_id: Optional[str]) -> Dict[str, object]:
        resolved_surface = normalize_surface(surface)
        resolved_key = build_session_key(resolved_surface, user_id=user_id, explicit=session_key, device_id=device_id, sender_id=sender_id)
        row = conn.execute(
            """
            SELECT COUNT(*) AS count, MAX(timestamp_ms) AS last_message_ts_ms
            FROM chat_messages
            WHERE user_id = ? AND session_key = ?
            """,
            (int(user_id), resolved_key),
        ).fetchone()
        return {
            "surface": resolved_surface,
            "session_key": resolved_key,
            "message_count": int(row["count"] or 0) if row else 0,
            "last_message_ts_ms": int(row["last_message_ts_ms"] or 0) if row and row["last_message_ts_ms"] is not None else None,
        }

    def list_todos(self, user_id: int, state: Optional[str] = None) -> List[Dict[str, object]]:
        return self.store.list_todos(user_id, state=state)

    def create_todo(
        self,
        user_id: int,
        title: str,
        details: str = "",
        due_at_ms: Optional[int] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, object]:
        return self.store.create_todo(user_id, title=title, details=details, due_at_ms=due_at_ms, tags=tags)

    def update_todo(self, user_id: int, todo_id: str, changes: Dict[str, object]) -> Dict[str, object]:
        return self.store.update_todo(user_id, todo_id, changes)

    def search_memory(self, user_id: int, query: str, limit: int = 10) -> List[Dict[str, object]]:
        return self.store.search_memory(user_id, query, limit=limit)

    def _compose_openclaw_message(
        self,
        text: str,
        surface: str,
        session_key: str,
        tool_results: List[ToolExecutionResult],
        attachments: Optional[List[dict]],
        metadata: Optional[Dict[str, object]],
    ) -> str:
        lines = [f"[surface={surface} session={session_key}]"]
        for item in tool_results:
            lines.append(f"[tool:{item.name}] ok={str(item.ok).lower()} detail={item.detail}")
        if attachments:
            lines.append(f"[attachments] {json.dumps(attachments, ensure_ascii=False)}")
        if metadata:
            lines.append(f"[metadata] {json.dumps(metadata, ensure_ascii=False)}")
        lines.append("")
        lines.append(str(text).strip())
        return "\n".join(lines).strip()

    async def _run_explicit_tools(
        self,
        conn: Connection,
        user_id: int,
        text: str,
        device_id: Optional[str] = None,
    ) -> List[ToolExecutionResult]:
        results: List[ToolExecutionResult] = []
        raw = str(text or "").strip()
        if not raw:
            return results

        todo_match = re.search(r"^(?:添加待办|新增待办|记个待办)[:：]?\s*(.+)$", raw, flags=re.IGNORECASE)
        if todo_match:
            item = self.create_todo(user_id, title=todo_match.group(1).strip())
            results.append(ToolExecutionResult(name="desktop.todo_create", ok=True, detail=f"已新增待办：{item['title']}", data=item))

        note_match = re.search(r"^(?:记一下|记个笔记|写个笔记)[:：]?\s*(.+)$", raw, flags=re.IGNORECASE)
        if note_match:
            note = self.store.write_note(user_id, title="assistant-note", body=note_match.group(1).strip())
            results.append(ToolExecutionResult(name="desktop.write_note", ok=True, detail="已写入笔记", data=note))

        url_match = re.search(r"(https?://\S+)", raw, flags=re.IGNORECASE)
        if url_match:
            url = url_match.group(1).strip()
            self._launch_url(url)
            results.append(ToolExecutionResult(name="desktop.open_url", ok=True, detail=f"已打开 {url}", data={"url": url}))

        app_match = re.search(r"打开(记事本|计算器|资源管理器|VSCode|Chrome|Edge)", raw, flags=re.IGNORECASE)
        if app_match:
            alias_map = {
                "记事本": "notepad",
                "计算器": "calc",
                "资源管理器": "explorer",
                "vscode": "vscode",
                "chrome": "chrome",
                "edge": "edge",
            }
            label = app_match.group(1)
            key = alias_map.get(label, alias_map.get(label.lower(), label.lower()))
            self._launch_app(key)
            results.append(ToolExecutionResult(name="desktop.launch_app", ok=True, detail=f"已启动 {label}", data={"app": key}))

        if "机器人状态" in raw:
            status_payload = await self._robot_get_status(conn, user_id, device_id=device_id)
            results.append(ToolExecutionResult(name="robot.get_status", ok=True, detail="已读取机器人状态", data=status_payload))

        speak_match = re.search(r"(?:让机器人|机器人)(?:说|讲|播报)(?:一句)?(.+)$", raw)
        if speak_match:
            say_text = speak_match.group(1).strip(" ：:，,。")
            if say_text:
                await self._robot_post(conn, user_id, "/speak", {"text": say_text}, device_id=device_id)
                results.append(ToolExecutionResult(name="robot.speak", ok=True, detail=f"已让机器人说：{say_text}", data={"text": say_text}))

        if any(keyword in raw for keyword in ["抬头", "低头", "左转", "右转", "向左看", "向右看", "看左边", "看右边", "看上面", "看下面"]):
            pan = 0.0
            tilt = 0.0
            if any(keyword in raw for keyword in ["左转", "向左看", "看左边"]):
                pan = -0.35
            if any(keyword in raw for keyword in ["右转", "向右看", "看右边"]):
                pan = 0.35
            if any(keyword in raw for keyword in ["抬头", "看上面"]):
                tilt = 0.35
            if any(keyword in raw for keyword in ["低头", "看下面"]):
                tilt = -0.35
            await self._robot_post(conn, user_id, "/pan_tilt", {"pan": pan, "tilt": tilt}, device_id=device_id)
            results.append(ToolExecutionResult(name="robot.pan_tilt", ok=True, detail=f"已控制云台 pan={pan:.2f} tilt={tilt:.2f}", data={"pan": pan, "tilt": tilt}))

        if any(keyword in raw for keyword in ["开始主人建档", "开始建档", "录入主人"]):
            response = await self._robot_post(conn, user_id, "/owner/enrollment/start", {"owner_label": "owner"}, device_id=device_id)
            results.append(ToolExecutionResult(name="robot.start_owner_enrollment", ok=True, detail="已触发主人建档", data=response))

        if any(keyword in raw for keyword in ["预览", "查看画面", "看摄像头"]):
            preview = self._robot_preview(conn, user_id, device_id=device_id)
            results.append(ToolExecutionResult(name="robot.get_preview", ok=True, detail="已提供机器人预览地址", data=preview))

        return results

    async def _robot_get_status(self, conn: Connection, user_id: int, device_id: Optional[str] = None) -> Dict[str, object]:
        device = self._resolve_device(conn, user_id, device_id=device_id)
        url = f"http://{device['device_ip']}/status"
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else {}

    async def _robot_post(
        self,
        conn: Connection,
        user_id: int,
        path: str,
        payload: Dict[str, object],
        device_id: Optional[str] = None,
    ) -> Dict[str, object]:
        device = self._resolve_device(conn, user_id, device_id=device_id)
        url = f"http://{device['device_ip']}{path}"
        async with httpx.AsyncClient(timeout=4.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else {}

    def _robot_preview(self, conn: Connection, user_id: int, device_id: Optional[str] = None) -> Dict[str, object]:
        device = self._resolve_device(conn, user_id, device_id=device_id)
        return {"preview_url": f"http://{device['device_ip']}/camera/preview.jpg", "device_id": device["device_id"]}

    def _resolve_device(self, conn: Connection, user_id: int, device_id: Optional[str] = None) -> Dict[str, object]:
        params: List[Any] = [int(user_id)]
        query = "SELECT * FROM devices WHERE user_id = ?"
        if device_id:
            query += " AND device_id = ?"
            params.append(str(device_id))
        query += " ORDER BY updated_at DESC LIMIT 1"
        row = conn.execute(query, params).fetchone()
        if not row:
            raise RuntimeError("No bound robot device found")
        device = dict(row)
        if not str(device.get("device_ip") or "").strip():
            raise RuntimeError("Robot device IP missing")
        return device

    def _launch_url(self, url: str) -> None:
        subprocess.Popen(["cmd", "/c", "start", "", url], shell=False)

    def _launch_app(self, alias: str) -> None:
        candidate = self.app_allowlist.get(alias)
        if not candidate:
            raise RuntimeError(f"App not allowed: {alias}")
        if isinstance(candidate, str):
            command = [candidate]
        else:
            command = [str(part) for part in list(candidate)]
        subprocess.Popen(command, shell=False)
