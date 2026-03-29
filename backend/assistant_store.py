from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


def _now_ms() -> int:
    return int(time.time() * 1000)


class AssistantWorkspaceStore:
    def __init__(self, root_dir: str) -> None:
        self.root = Path(root_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.data_root = self.root / "assistant_data"
        self.data_root.mkdir(parents=True, exist_ok=True)

    def _user_dir(self, user_id: int) -> Path:
        path = self.data_root / "users" / str(int(user_id))
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _todos_path(self, user_id: int) -> Path:
        return self._user_dir(user_id) / "todos.json"

    def _memory_path(self, user_id: int) -> Path:
        return self._user_dir(user_id) / "memory.md"

    def _notes_dir(self, user_id: int) -> Path:
        path = self._user_dir(user_id) / "notes"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def list_todos(self, user_id: int, state: Optional[str] = None) -> List[Dict[str, object]]:
        items = self._load_todos(user_id)
        if state:
            wanted = str(state).strip().lower()
            items = [item for item in items if str(item.get("state") or "").lower() == wanted]
        return items

    def create_todo(
        self,
        user_id: int,
        title: str,
        details: str = "",
        due_at_ms: Optional[int] = None,
        tags: Optional[List[str]] = None,
        action: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        now_ms = _now_ms()
        item = {
            "id": f"todo-{uuid.uuid4().hex[:10]}",
            "title": str(title).strip(),
            "details": str(details or "").strip(),
            "state": "open",
            "created_at_ms": now_ms,
            "updated_at_ms": now_ms,
            "due_at_ms": int(due_at_ms) if due_at_ms is not None else None,
            "tags": [str(tag).strip() for tag in (tags or []) if str(tag).strip()],
            "notified_at_ms": None,
            "action": dict(action or {}),
        }
        items = self._load_todos(user_id)
        items.append(item)
        self._save_todos(user_id, items)
        self.append_memory(
            user_id,
            title="todo_created",
            content=f"新增待办：{item['title']}" + (f"；说明：{item['details']}" if item["details"] else ""),
            tags=["todo", "assistant"],
        )
        return item

    def update_todo(self, user_id: int, todo_id: str, changes: Dict[str, object]) -> Dict[str, object]:
        items = self._load_todos(user_id)
        for item in items:
            if str(item.get("id") or "") != str(todo_id):
                continue
            if "title" in changes and changes["title"] is not None:
                item["title"] = str(changes["title"]).strip()
            if "details" in changes and changes["details"] is not None:
                item["details"] = str(changes["details"]).strip()
            if "state" in changes and changes["state"] is not None:
                item["state"] = str(changes["state"]).strip().lower() or "open"
            if "due_at_ms" in changes:
                item["due_at_ms"] = int(changes["due_at_ms"]) if changes["due_at_ms"] is not None else None
            if "tags" in changes and changes["tags"] is not None:
                item["tags"] = [str(tag).strip() for tag in list(changes["tags"]) if str(tag).strip()]
            if "notified_at_ms" in changes:
                item["notified_at_ms"] = (
                    int(changes["notified_at_ms"]) if changes["notified_at_ms"] is not None else None
                )
            if "action" in changes and changes["action"] is not None:
                item["action"] = dict(changes["action"])
            item["updated_at_ms"] = _now_ms()
            self._save_todos(user_id, items)
            self.append_memory(
                user_id,
                title="todo_updated",
                content=f"更新待办：{item['title']}；状态：{item['state']}",
                tags=["todo", "assistant"],
            )
            return item
        raise KeyError(f"todo not found: {todo_id}")

    def claim_due_todos(self, user_id: int, now_ms: Optional[int] = None, limit: int = 10) -> List[Dict[str, object]]:
        current_ms = int(now_ms or _now_ms())
        items = self._load_todos(user_id)
        due: List[Dict[str, object]] = []
        changed = False
        for item in items:
            if str(item.get("state") or "").lower() != "open":
                continue
            due_at = item.get("due_at_ms")
            if due_at is None:
                continue
            try:
                due_at_int = int(due_at)
            except Exception:
                continue
            if due_at_int > current_ms:
                continue
            if item.get("notified_at_ms") is not None:
                continue
            item["notified_at_ms"] = current_ms
            item["updated_at_ms"] = current_ms
            due.append(item.copy())
            changed = True
            if len(due) >= max(1, min(int(limit), 20)):
                break
        if changed:
            self._save_todos(user_id, items)
        return due

    def format_due_label(self, due_at_ms: Optional[int]) -> str:
        if due_at_ms is None:
            return ""
        try:
            dt = datetime.fromtimestamp(int(due_at_ms) / 1000.0)
        except Exception:
            return ""
        return dt.strftime("%Y-%m-%d %H:%M")

    def append_memory(self, user_id: int, title: str, content: str, tags: Optional[List[str]] = None) -> None:
        memory_path = self._memory_path(user_id)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(_now_ms() / 1000.0))
        tag_text = ""
        if tags:
            normalized = [str(tag).strip() for tag in tags if str(tag).strip()]
            if normalized:
                tag_text = f" [{', '.join(normalized)}]"
        chunk = f"## {stamp} {str(title).strip()}{tag_text}\n{str(content).strip()}\n\n"
        with memory_path.open("a", encoding="utf-8") as fh:
            fh.write(chunk)

    def get_profile_memory_summary(self, user_id: int, max_chars: int = 1200) -> str:
        memory_path = self._memory_path(user_id)
        if not memory_path.exists():
            return ""
        try:
            text = memory_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""
        if not text.strip():
            return ""

        marker_hits = (
            "activation_dialogue_profile",
            "dialogue_profile",
            "activation_profile",
            "personality_profile",
            "首次激活",
            "偏好",
            "陪伴",
        )
        sections = []
        for chunk in re.split(r"(?=^##\s)", text, flags=re.MULTILINE):
            cleaned = str(chunk or "").strip()
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if any(marker.lower() in lowered for marker in marker_hits):
                sections.append(cleaned)

        if not sections:
            sections = [text.strip()]

        summary = "\n\n".join(sections[-3:]).strip()
        if len(summary) > max_chars:
            summary = summary[-max_chars:]
        return summary

    def write_note(self, user_id: int, title: str, body: str) -> Dict[str, object]:
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(title or "note").strip()).strip("-").lower() or "note"
        path = self._notes_dir(user_id) / f"{slug}-{int(time.time())}.md"
        path.write_text(f"# {str(title).strip()}\n\n{str(body).strip()}\n", encoding="utf-8")
        self.append_memory(
            user_id,
            title="note_written",
            content=f"新笔记：{title}",
            tags=["note", "assistant"],
        )
        return {"title": str(title).strip(), "path": str(path)}

    def search_memory(self, user_id: int, query: str, limit: int = 10) -> List[Dict[str, object]]:
        needle = str(query or "").strip().lower()
        if not needle:
            return []
        results: List[Dict[str, object]] = []
        candidates = [self._memory_path(user_id), *sorted(self._notes_dir(user_id).glob("*.md")), self._todos_path(user_id)]
        for path in candidates:
            if not path.exists():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            haystack = text.lower()
            pos = haystack.find(needle)
            if pos < 0:
                continue
            start = max(0, pos - 80)
            end = min(len(text), pos + len(needle) + 120)
            snippet = " ".join(text[start:end].split())
            results.append(
                {
                    "path": str(path),
                    "snippet": snippet,
                    "score": haystack.count(needle),
                }
            )
        results.sort(key=lambda item: int(item.get("score") or 0), reverse=True)
        return results[: max(1, min(int(limit), 20))]

    def _load_todos(self, user_id: int) -> List[Dict[str, object]]:
        path = self._todos_path(user_id)
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        items = payload if isinstance(payload, list) else []
        normalized: List[Dict[str, object]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            merged = dict(item)
            merged.setdefault("notified_at_ms", None)
            merged.setdefault("action", {})
            normalized.append(merged)
        return normalized

    def _save_todos(self, user_id: int, items: List[Dict[str, object]]) -> None:
        path = self._todos_path(user_id)
        path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
