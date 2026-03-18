from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from sqlite3 import Connection
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

import httpx

from .assistant_store import AssistantWorkspaceStore
from .openclaw_gateway import (
    OpenClawGatewayClient,
    OpenClawGatewayConfig,
    OpenClawGatewayError,
    discover_openclaw_state_dir,
)
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
        message = self._compose_openclaw_message(
            text,
            normalized_surface,
            resolved_session_key,
            tool_results,
            attachments,
            metadata,
        )
        reply = await self.gateway.send_message(resolved_session_key, message)
        return {
            "surface": normalized_surface,
            "session_key": resolved_session_key,
            "text": reply.strip(),
            "tool_results": [result.__dict__ for result in tool_results],
            "timestamp_ms": _now_ms(),
        }

    async def reset_session(
        self,
        user_id: int,
        surface: str,
        session_key: Optional[str],
        device_id: Optional[str],
        sender_id: Optional[str],
    ) -> Dict[str, object]:
        resolved_surface = normalize_surface(surface)
        resolved_key = build_session_key(
            resolved_surface,
            user_id=user_id,
            explicit=session_key,
            device_id=device_id,
            sender_id=sender_id,
        )
        await self.gateway.reset_session(resolved_key)
        return {"surface": resolved_surface, "session_key": resolved_key}

    def get_session_status(
        self,
        conn: Connection,
        user_id: int,
        surface: str,
        session_key: Optional[str],
        device_id: Optional[str],
        sender_id: Optional[str],
    ) -> Dict[str, object]:
        resolved_surface = normalize_surface(surface)
        resolved_key = build_session_key(
            resolved_surface,
            user_id=user_id,
            explicit=session_key,
            device_id=device_id,
            sender_id=sender_id,
        )
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
        action: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        return self.store.create_todo(
            user_id,
            title=title,
            details=details,
            due_at_ms=due_at_ms,
            tags=tags,
            action=action,
        )

    def update_todo(self, user_id: int, todo_id: str, changes: Dict[str, object]) -> Dict[str, object]:
        return self.store.update_todo(user_id, todo_id, changes)

    def claim_due_todos(self, user_id: int, now_ms: Optional[int] = None, limit: int = 10) -> List[Dict[str, object]]:
        return self.store.claim_due_todos(user_id, now_ms=now_ms, limit=limit)

    def search_memory(self, user_id: int, query: str, limit: int = 10) -> List[Dict[str, object]]:
        return self.store.search_memory(user_id, query, limit=limit)

    def runtime_status(self) -> Dict[str, object]:
        try:
            state_dir = discover_openclaw_state_dir(OPENCLAW_STATE_DIR, OPENCLAW_WORKSPACE_DIR)
            gateway_ready = True
            gateway_error = ""
            resolved_state_dir = str(state_dir)
        except OpenClawGatewayError as exc:
            gateway_ready = False
            gateway_error = str(exc)
            resolved_state_dir = str(OPENCLAW_STATE_DIR or "")
        return {
            "gateway_ready": gateway_ready,
            "gateway_error": gateway_error,
            "state_dir": resolved_state_dir,
            "workspace_dir": str(OPENCLAW_WORKSPACE_DIR),
            "desktop_tools": [
                "desktop.launch_app",
                "desktop.open_url",
                "desktop.web_search",
                "desktop.play_music",
                "desktop.todo_create",
                "desktop.write_note",
                "robot.get_status",
                "robot.speak",
                "robot.pan_tilt",
                "robot.start_owner_enrollment",
                "robot.get_preview",
            ],
            "robot_bridge_ready": True,
        }

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

        reminder = self._parse_reminder(raw)
        if reminder is not None:
            title, due_at_ms, action = reminder
            item = self.create_todo(
                user_id,
                title=title,
                due_at_ms=due_at_ms,
                tags=["reminder", "assistant"],
                action=action,
            )
            due_label = self.store.format_due_label(due_at_ms)
            results.append(
                ToolExecutionResult(
                    name="desktop.todo_create",
                    ok=True,
                    detail=f"Reminder scheduled for {due_label}" if due_label else "Reminder scheduled",
                    data=item,
                )
            )

        todo_match = re.search(r"^(?:添加待办|新增待办|记个待办)[:：]?\s*(.+)$", raw, flags=re.IGNORECASE)
        if todo_match:
            item = self.create_todo(user_id, title=todo_match.group(1).strip())
            results.append(
                ToolExecutionResult(
                    name="desktop.todo_create",
                    ok=True,
                    detail=f"Added todo: {item['title']}",
                    data=item,
                )
            )

        note_match = re.search(r"^(?:记一个|记个笔记|写个笔记|记笔记)[:：]?\s*(.+)$", raw, flags=re.IGNORECASE)
        if note_match:
            note = self.store.write_note(user_id, title="assistant-note", body=note_match.group(1).strip())
            results.append(
                ToolExecutionResult(name="desktop.write_note", ok=True, detail="Note written", data=note)
            )

        direct_url_match = re.search(r"(https?://\S+)", raw, flags=re.IGNORECASE)
        if direct_url_match:
            url = direct_url_match.group(1).strip()
            self._launch_url(url)
            results.append(
                ToolExecutionResult(name="desktop.open_url", ok=True, detail=f"Opened {url}", data={"url": url})
            )

        page_match = re.search(r"(?:打开网页|打开网站|打开页面|open website|open page)\s*[:：]?\s*(.+)$", raw, flags=re.IGNORECASE)
        if page_match:
            target = page_match.group(1).strip()
            url = self._normalize_web_target(target)
            self._launch_url(url)
            results.append(
                ToolExecutionResult(name="desktop.open_url", ok=True, detail=f"Opened {url}", data={"url": url})
            )

        search_match = re.search(r"(?:搜索|查一下|搜一下|search)\s*[:：]?\s*(.+)$", raw, flags=re.IGNORECASE)
        if search_match:
            query = search_match.group(1).strip()
            if query:
                url = f"https://www.baidu.com/s?wd={quote_plus(query)}"
                self._launch_url(url)
                results.append(
                    ToolExecutionResult(
                        name="desktop.web_search",
                        ok=True,
                        detail=f"Searched {query}",
                        data={"query": query, "url": url},
                    )
                )

        music_query = self._parse_music_request(raw)
        if music_query:
            url = f"https://music.163.com/#/search/m/?s={quote_plus(music_query)}&type=1"
            self._launch_url(url)
            results.append(
                ToolExecutionResult(
                    name="desktop.play_music",
                    ok=True,
                    detail=f"Opened music search for {music_query}",
                    data={"query": music_query, "url": url},
                )
            )

        app_match = re.search(
            r"(?:打开|启动|launch)\s*(记事本|计算器|资源管理器|vscode|chrome|edge|notepad|calc|explorer)\b",
            raw,
            flags=re.IGNORECASE,
        )
        if app_match:
            alias_map = {
                "记事本": "notepad",
                "notepad": "notepad",
                "计算器": "calc",
                "calc": "calc",
                "资源管理器": "explorer",
                "explorer": "explorer",
                "vscode": "vscode",
                "chrome": "chrome",
                "edge": "edge",
            }
            label = str(app_match.group(1) or "").strip()
            key = alias_map.get(label.lower(), alias_map.get(label, label.lower()))
            self._launch_app(key)
            results.append(
                ToolExecutionResult(
                    name="desktop.launch_app",
                    ok=True,
                    detail=f"Launched {label}",
                    data={"app": key},
                )
            )

        lowered = raw.lower()
        if any(keyword in raw for keyword in ["机器人状态", "机器人的状态", "robot status"]):
            status_payload = await self._robot_get_status(conn, user_id, device_id=device_id)
            results.append(
                ToolExecutionResult(
                    name="robot.get_status",
                    ok=True,
                    detail="Fetched robot status",
                    data=status_payload,
                )
            )

        speak_match = re.search(
            r"(?:让机器人|机器人)(?:说|播报|讲话)\s*(?:一句|一下)?[:：]?\s*(.+)$",
            raw,
            flags=re.IGNORECASE,
        )
        if speak_match:
            say_text = str(speak_match.group(1) or "").strip().strip("。.!！?？")
            if say_text:
                response = await self._robot_post(conn, user_id, "/speak", {"text": say_text}, device_id=device_id)
                results.append(
                    ToolExecutionResult(
                        name="robot.speak",
                        ok=True,
                        detail=f"Robot will say: {say_text}",
                        data=response or {"text": say_text},
                    )
                )

        pan, tilt = self._parse_robot_pan_tilt(raw)
        if pan is not None or tilt is not None:
            response = await self._robot_post(
                conn,
                user_id,
                "/pan_tilt",
                {"pan": pan or 0.0, "tilt": tilt or 0.0},
                device_id=device_id,
            )
            results.append(
                ToolExecutionResult(
                    name="robot.pan_tilt",
                    ok=True,
                    detail=f"Robot moved pan={pan or 0.0:.2f} tilt={tilt or 0.0:.2f}",
                    data=response or {"pan": pan or 0.0, "tilt": tilt or 0.0},
                )
            )

        if any(keyword in raw for keyword in ["开始主人建档", "开始建档", "录入主人", "start owner enrollment"]):
            response = await self._robot_post(
                conn,
                user_id,
                "/owner/enrollment/start",
                {"owner_label": "owner"},
                device_id=device_id,
            )
            results.append(
                ToolExecutionResult(
                    name="robot.start_owner_enrollment",
                    ok=True,
                    detail="Started owner enrollment",
                    data=response,
                )
            )

        if any(keyword in raw for keyword in ["预览", "查看画面", "看摄像头", "camera preview"]):
            preview = self._robot_preview(conn, user_id, device_id=device_id)
            results.append(
                ToolExecutionResult(
                    name="robot.get_preview",
                    ok=True,
                    detail="Prepared preview URL",
                    data=preview,
                )
            )

        return results

    def _parse_robot_pan_tilt(self, raw: str) -> Tuple[Optional[float], Optional[float]]:
        pan: Optional[float] = None
        tilt: Optional[float] = None
        if any(keyword in raw for keyword in ["左转", "向左看", "看左边", "turn left"]):
            pan = -0.35
        if any(keyword in raw for keyword in ["右转", "向右看", "看右边", "turn right"]):
            pan = 0.35
        if any(keyword in raw for keyword in ["抬头", "看上面", "look up"]):
            tilt = 0.35
        if any(keyword in raw for keyword in ["低头", "看下面", "look down"]):
            tilt = -0.35
        if "动一动" in raw or "move a bit" in raw.lower():
            pan = 0.25 if pan is None else pan
            tilt = 0.18 if tilt is None else tilt
        return pan, tilt

    def _normalize_web_target(self, target: str) -> str:
        value = str(target or "").strip()
        if re.match(r"^https?://", value, flags=re.IGNORECASE):
            return value
        if re.match(r"^[a-z0-9.-]+\.[a-z]{2,}$", value, flags=re.IGNORECASE):
            return f"https://{value}"
        return f"https://www.baidu.com/s?wd={quote_plus(value)}"

    def _parse_music_request(self, raw: str) -> Optional[str]:
        value = str(raw or "").strip()
        patterns = [
            r"(?:听歌|放首歌|播放音乐|播放歌曲|play music)\s*[:：]?\s*(.+)$",
            r"(?:想听|我想听)\s*(.+)$",
        ]
        for pattern in patterns:
            match = re.search(pattern, value, flags=re.IGNORECASE)
            if not match:
                continue
            query = str(match.group(1) or "").strip().strip("。.!！?？")
            if query:
                return query
        return None

    def _parse_reminder(self, raw: str) -> Optional[Tuple[str, int, Dict[str, object]]]:
        value = str(raw or "").strip()
        match = re.search(
            r"(?:提醒我)\s*(.+?)\s*(?:在)?\s*(\d+)\s*(秒|分钟|分|小时|时|天)后",
            value,
            flags=re.IGNORECASE,
        )
        if match:
            title = str(match.group(1) or "").strip()
            amount = int(match.group(2))
            unit = str(match.group(3) or "")
            return title, _now_ms() + (self._unit_to_seconds(amount, unit) * 1000), {"type": "reminder"}
        match = re.search(
            r"(?:remind me to)\s*(.+?)\s*(?:in)\s*(\d+)\s*(seconds?|minutes?|hours?|days?)",
            value,
            flags=re.IGNORECASE,
        )
        if match:
            title = str(match.group(1) or "").strip()
            amount = int(match.group(2))
            unit = str(match.group(3) or "")
            return title, _now_ms() + (self._unit_to_seconds(amount, unit) * 1000), {"type": "reminder"}
        match = re.search(
            r"(?:提醒我)\s*(.+?)\s*(今天|明天)?\s*(上午|下午|晚上)?\s*(\d{1,2})[:点时]?(\d{1,2})?",
            value,
            flags=re.IGNORECASE,
        )
        if match:
            title = str(match.group(1) or "").strip()
            if not title:
                return None
            day_hint = str(match.group(2) or "").strip()
            period = str(match.group(3) or "").strip()
            hour = int(match.group(4))
            minute = int(match.group(5) or 0)
            if period in {"下午", "晚上"} and hour < 12:
                hour += 12
            now = datetime.now()
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if day_hint == "明天":
                target = target + timedelta(days=1)
            elif target <= now:
                target = target + timedelta(days=1)
            return title, int(target.timestamp() * 1000), {"type": "reminder"}
        return None

    def _unit_to_seconds(self, amount: int, unit: str) -> int:
        normalized = str(unit or "").strip().lower()
        if normalized in {"秒", "second", "seconds"}:
            return max(1, amount)
        if normalized in {"小时", "时", "hour", "hours"}:
            return max(1, amount) * 3600
        if normalized in {"天", "day", "days"}:
            return max(1, amount) * 86400
        return max(1, amount) * 60

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
