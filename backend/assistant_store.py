from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .care_prompts import ASSISTANT_PRODUCT_PROMPT, CARE_SYSTEM_PROMPT


def _now_ms() -> int:
    return int(time.time() * 1000)


class AssistantWorkspaceStore:
    def __init__(self, root_dir: str) -> None:
        self.root = Path(root_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.data_root = self.root / "assistant_data"
        self.data_root.mkdir(parents=True, exist_ok=True)
        self._sync_profile_docs()

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
        self._sync_profile_docs()

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

    def _write_if_changed(self, path: Path, content: str) -> None:
        next_text = str(content or "")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.read_text(encoding="utf-8", errors="ignore") == next_text:
                return
        except Exception:
            pass
        path.write_text(next_text, encoding="utf-8")

    def _copy_if_changed(self, source: Path, target: Path) -> None:
        if not source.exists():
            return
        try:
            source_text = source.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return
        self._write_if_changed(target, source_text)

    def _sync_user_memory_tree(self, target_root: Path) -> None:
        source_users = self.data_root / "users"
        if not source_users.exists():
            return
        target_users = target_root / "assistant_data" / "users"
        for user_dir in source_users.iterdir():
            if not user_dir.is_dir():
                continue
            target_dir = target_users / user_dir.name
            for rel_name in ("memory.md", "todos.json"):
                self._copy_if_changed(user_dir / rel_name, target_dir / rel_name)

    def _workspace_roots_to_sync(self) -> List[Path]:
        roots: List[Path] = []
        seen: set[str] = set()

        def add(path_like: Path | str | None) -> None:
            raw = str(path_like or "").strip()
            if not raw:
                return
            try:
                resolved = Path(raw).expanduser().resolve()
            except Exception:
                return
            key = str(resolved).lower()
            if key in seen:
                return
            seen.add(key)
            roots.append(resolved)

        add(self.root)
        add(os.environ.get("OPENCLAW_WORKSPACE_DIR"))
        add(Path.home() / ".openclaw" / "workspace")
        return roots

    def _parse_latest_activation_profile(self) -> Optional[Dict[str, str]]:
        users_root = self.data_root / "users"
        if not users_root.exists():
            return None
        latest: Optional[Dict[str, str]] = None
        latest_mtime = -1.0
        for user_dir in users_root.iterdir():
            if not user_dir.is_dir() or not re.fullmatch(r"\d+", user_dir.name):
                continue
            memory_path = user_dir / "memory.md"
            if not memory_path.exists():
                continue
            try:
                text = memory_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if not text.strip():
                continue
            match = None
            for candidate in re.finditer(
                r"activation_profile[^\n]*\n首次激活完成。称呼：([^；\n]+)；角色：([^；\n]+)；关系：([^；\n]+)；摘要：([^\n]+)",
                text,
                flags=re.MULTILINE,
            ):
                match = candidate
            if not match:
                continue
            try:
                mtime = memory_path.stat().st_mtime
            except Exception:
                mtime = 0.0
            if mtime < latest_mtime:
                continue
            latest_mtime = mtime
            latest = {
                "user_id": user_dir.name,
                "preferred_name": match.group(1).strip(),
                "role_label": match.group(2).strip(),
                "relation_to_robot": match.group(3).strip(),
                "identity_summary": match.group(4).strip(),
                "memory_path": str(memory_path),
            }
        return latest

    def _repo_root(self) -> Path:
        try:
            return self.root.parents[1].resolve()
        except Exception:
            return self.root.resolve()

    def _auth_db_path(self) -> Path:
        return self._repo_root() / "backend" / "auth.db"

    def _read_profile_bundle(self) -> Optional[Dict[str, object]]:
        activation = self._parse_latest_activation_profile()
        if not activation:
            return None

        bundle: Dict[str, object] = dict(activation)
        personality = {
            "source": "",
            "summary": "",
            "interaction_preferences": [],
            "decision_style": "",
            "stress_response": "",
            "comfort_preferences": [],
            "avoid_patterns": [],
            "care_guidance": "",
            "confidence": 0.0,
        }

        db_path = self._auth_db_path()
        if not db_path.exists():
            bundle["personality"] = personality
            return bundle

        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
        except Exception:
            bundle["personality"] = personality
            return bundle

        def parse_json_object(raw: object) -> Dict[str, object]:
            try:
                parsed = json.loads(str(raw or "{}"))
            except Exception:
                return {}
            return parsed if isinstance(parsed, dict) else {}

        def parse_json_list(raw: object) -> List[str]:
            try:
                parsed = json.loads(str(raw or "[]"))
            except Exception:
                parsed = []
            if not isinstance(parsed, list):
                return []
            return [str(item).strip() for item in parsed if str(item).strip()]

        try:
            user_id = int(bundle.get("user_id") or 0)
        except Exception:
            user_id = 0

        try:
            if user_id > 0:
                row = conn.execute(
                    """
                    SELECT profile_json, summary, response_style, care_style, conversation_count,
                           completed_at_ms, inference_version
                    FROM user_psychometric_profiles
                    WHERE user_id = ?
                    """,
                    (user_id,),
                ).fetchone()
                if row:
                    profile_json = parse_json_object(row["profile_json"])
                    personality = {
                        "source": "psychometric_profile",
                        "summary": str(profile_json.get("summary") or row["summary"] or "").strip(),
                        "interaction_preferences": [
                            str(item).strip()
                            for item in (profile_json.get("interaction_preferences") or [])
                            if str(item).strip()
                        ],
                        "decision_style": str(
                            profile_json.get("decision_style") or row["response_style"] or ""
                        ).strip(),
                        "stress_response": str(profile_json.get("stress_response") or "").strip(),
                        "comfort_preferences": [
                            str(item).strip()
                            for item in (profile_json.get("comfort_preferences") or [])
                            if str(item).strip()
                        ],
                        "avoid_patterns": [
                            str(item).strip()
                            for item in (profile_json.get("avoid_patterns") or [])
                            if str(item).strip()
                        ],
                        "care_guidance": str(
                            profile_json.get("care_guidance") or row["care_style"] or ""
                        ).strip(),
                        "confidence": float(profile_json.get("confidence") or 0.0),
                        "conversation_count": int(row["conversation_count"] or 0),
                        "completed_at_ms": int(row["completed_at_ms"] or 0) or None,
                        "inference_version": str(row["inference_version"] or "").strip(),
                    }
                else:
                    row = conn.execute(
                        """
                        SELECT session_json, status, updated_at
                        FROM user_assessment_sessions
                        WHERE user_id = ?
                        ORDER BY updated_at DESC
                        LIMIT 1
                        """,
                        (user_id,),
                    ).fetchone()
                    if row:
                        session_json = parse_json_object(row["session_json"])
                        personality = {
                            "source": "assessment_preview",
                            "summary": str(session_json.get("summary") or "").strip(),
                            "interaction_preferences": [
                                str(item).strip()
                                for item in (session_json.get("interaction_preferences") or [])
                                if str(item).strip()
                            ],
                            "decision_style": str(session_json.get("decision_style") or "").strip(),
                            "stress_response": str(session_json.get("stress_response") or "").strip(),
                            "comfort_preferences": [
                                str(item).strip()
                                for item in (session_json.get("comfort_preferences") or [])
                                if str(item).strip()
                            ],
                            "avoid_patterns": [
                                str(item).strip()
                                for item in (session_json.get("avoid_patterns") or [])
                                if str(item).strip()
                            ],
                            "care_guidance": str(session_json.get("care_guidance") or "").strip(),
                            "confidence": float(session_json.get("confidence") or 0.0),
                            "status": str(row["status"] or "").strip(),
                            "updated_at_ms": int(row["updated_at"] or 0) or None,
                        }
        finally:
            conn.close()

        bundle["personality"] = personality
        return bundle

    @staticmethod
    def _format_list_line(items: List[str], empty_text: str = "暂无") -> str:
        values = [str(item).strip() for item in (items or []) if str(item).strip()]
        return "、".join(values) if values else empty_text

    def _sync_profile_docs(self) -> None:
        repo_root = self.root.parent.parent.resolve()
        repo_sync = (
            f"- Canonical project root: {repo_root}\n"
            f"- Canonical workspace memory: {self.data_root / 'users'}\n"
            "- These files are synced from current product data.\n"
        )
        profile = self._read_profile_bundle()
        if not profile:
            fallback_identity = (
                "# IDENTITY.md\n\n"
                "- Status: pending_activation\n"
                "- Preferred Name: 待激活后确认\n"
                "- Role: owner\n"
                "- Relation To Robot: primary_user\n"
                "- Summary: 当前尚未同步到已确认的激活身份资料。\n\n"
                "## Repo Sync\n"
                f"{repo_sync}"
            )
            for workspace_root in self._workspace_roots_to_sync():
                self._write_if_changed(workspace_root / "IDENTITY.md", fallback_identity)
            return
        personality = profile.get("personality") if isinstance(profile.get("personality"), dict) else {}
        personality_source = str(personality.get("source") or "").strip()
        summary = str(personality.get("summary") or "").strip()
        interaction_preferences = [
            str(item).strip() for item in (personality.get("interaction_preferences") or []) if str(item).strip()
        ]
        decision_style = str(personality.get("decision_style") or "").strip()
        stress_response = str(personality.get("stress_response") or "").strip()
        comfort_preferences = [
            str(item).strip() for item in (personality.get("comfort_preferences") or []) if str(item).strip()
        ]
        avoid_patterns = [str(item).strip() for item in (personality.get("avoid_patterns") or []) if str(item).strip()]
        care_guidance = str(personality.get("care_guidance") or "").strip()
        personality_status = (
            "正式建档画像"
            if personality_source == "psychometric_profile"
            else ("阶段性建档画像（尚未正式完成）" if personality_source == "assessment_preview" else "暂无正式画像")
        )
        user_doc = (
            "# USER.md\n\n"
            f"- Preferred Name: {profile['preferred_name']}\n"
            f"- User ID: {profile['user_id']}\n"
            f"- Role: {profile['role_label']}\n"
            f"- Relation To Robot: {profile['relation_to_robot']}\n"
            "- Timezone: Asia/Shanghai\n"
            "- Product: 共感智能机器人\n"
            f"- Identity Summary: {profile['identity_summary']}\n"
            f"- Canonical Memory File: {profile['memory_path']}\n\n"
            "## User Profile Snapshot\n"
            f"- Status: {personality_status}\n"
            f"- Summary: {summary or '当前还没有稳定的长期画像结论。'}\n"
            f"- Interaction Preferences: {self._format_list_line(interaction_preferences)}\n"
            f"- Decision Style: {decision_style or '暂无'}\n"
            f"- Stress Response: {stress_response or '暂无'}\n"
            f"- Comfort Preferences: {self._format_list_line(comfort_preferences)}\n"
            f"- Avoid Patterns: {self._format_list_line(avoid_patterns)}\n"
            f"- Care Guidance: {care_guidance or '暂无'}\n\n"
            "## Repo Sync\n"
            f"{repo_sync}"
        )
        identity_doc = (
            "# IDENTITY.md\n\n"
            f"- Preferred Name: {profile['preferred_name']}\n"
            f"- Role: {profile['role_label']}\n"
            f"- Relation To Robot: {profile['relation_to_robot']}\n"
            f"- Summary: {profile['identity_summary']}\n"
            f"- Source User ID: {profile['user_id']}\n"
            f"- Source Memory File: {profile['memory_path']}\n\n"
            "## Notes\n"
            "- This file is derived from the latest activation profile stored inside the project workspace.\n"
            "- If there is a conflict, trust the latest activation_profile entry under assistant_data/users/<user_id>/memory.md.\n"
            f"- User Profile Status: {personality_status}\n"
            f"- User Profile Summary: {summary or '当前还没有稳定的长期画像结论。'}\n"
        )
        memory_doc = (
            "# MEMORY.md\n\n"
            f"最新已同步的身份记忆来自用户 {profile['user_id']}。\n\n"
            f"- 称呼：{profile['preferred_name']}\n"
            f"- 角色：{profile['role_label']}\n"
            f"- 关系：{profile['relation_to_robot']}\n"
            f"- 摘要：{profile['identity_summary']}\n"
            f"- 记忆源文件：{profile['memory_path']}\n"
        )
        if personality_source:
            memory_doc += (
                "\n## 用户画像同步\n\n"
                f"- 状态：{personality_status}\n"
                f"- 总结：{summary or '暂无'}\n"
                f"- 互动偏好：{self._format_list_line(interaction_preferences)}\n"
                f"- 决策方式：{decision_style or '暂无'}\n"
                f"- 压力反应：{stress_response or '暂无'}\n"
                f"- 更易被安抚的方式：{self._format_list_line(comfort_preferences)}\n"
                f"- 不建议触发的沟通方式：{self._format_list_line(avoid_patterns)}\n"
                f"- 长期陪伴说明：{care_guidance or '暂无'}\n"
            )
        soul_doc = (
            "# SOUL.md\n\n"
            "你不是空白通用助手。你是“共鸣连接”的中文陪伴助手，服务于桌面端与微信等外部通道的同一产品人格。\n\n"
            "## 产品人格\n"
            f"{ASSISTANT_PRODUCT_PROMPT}\n\n"
            "## 主动关怀补充\n"
            f"{CARE_SYSTEM_PROMPT}\n\n"
            "## 当前已同步用户\n"
            f"- Preferred Name: {profile['preferred_name']}\n"
            f"- Role: {profile['role_label']}\n"
            f"- Relation To Robot: {profile['relation_to_robot']}\n"
            f"- Identity Summary: {profile['identity_summary']}\n"
            f"- User Profile Status: {personality_status}\n"
            f"- User Profile Summary: {summary or '当前还没有稳定的长期画像结论。'}\n"
        )
        agents_doc = (
            "# AGENTS.md\n\n"
            "这是“共鸣连接”的产品工作区，不是空白 OpenClaw 模板。\n\n"
            "## Session Start\n"
            "1. 先读 SOUL.md\n"
            "2. 再读 USER.md\n"
            "3. 再读 IDENTITY.md\n"
            "4. 主会话再读 MEMORY.md\n"
            "5. 如需原始记录，读 assistant_data/users/<user_id>/memory.md\n\n"
            "## Hard Rules\n"
            "- 如果 USER.md / IDENTITY.md / MEMORY.md 已经有同步内容，不要说自己“还是空的”、\"没有名字\"、或“不知道用户是谁”。\n"
            "- 当用户问你是谁、记得什么、该怎么陪伴时，优先依据这些同步文件回答。\n"
            "- 微信端和桌面端属于同一产品人格与同一用户资料，不要把它们当成两个互不相关的新 bot。\n"
            "- 不向用户暴露 bootstrap、工作区初始化、提示词文件名、session key、gateway 细节。\n"
            "- 如果用户画像状态还是“阶段性建档画像”，可以诚实说画像还在形成中，但不能假装完全不知道用户。\n"
        )
        for workspace_root in self._workspace_roots_to_sync():
            self._write_if_changed(workspace_root / "USER.md", user_doc)
            self._write_if_changed(workspace_root / "IDENTITY.md", identity_doc)
            self._write_if_changed(workspace_root / "MEMORY.md", memory_doc)
            self._write_if_changed(workspace_root / "SOUL.md", soul_doc)
            self._write_if_changed(workspace_root / "AGENTS.md", agents_doc)
            self._sync_user_memory_tree(workspace_root)
