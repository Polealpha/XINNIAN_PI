import sqlite3
import time

from fastapi.testclient import TestClient

import backend.auth as auth
import backend.db as db
import backend.main as main
from backend.assistant_service import build_session_key, normalize_surface
from backend.assistant_store import AssistantWorkspaceStore


def test_build_session_key_separates_surfaces():
    assert normalize_surface("DESKTOP") == "desktop"
    assert build_session_key("desktop", user_id=7) == "desktop:7"
    assert build_session_key("mobile", user_id=7) == "mobile:7"
    assert build_session_key("wecom", user_id=7, sender_id="alice") == "wecom:alice"
    assert build_session_key("robot", user_id=7, device_id="pi-zero") == "robot:pi-zero"
    assert build_session_key("desktop", user_id=7, explicit="custom:session") == "custom:session"


def _seed_user(db_path, username: str, password: str = "secret123") -> str:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO users (id, username, password_hash, created_at, is_configured) VALUES (?, ?, ?, ?, 1)",
            (1, username, auth.hash_password(password), int(time.time())),
        )
        conn.commit()
    finally:
        conn.close()
    return auth.create_access_token(1, username)["token"]


def test_assistant_send_includes_activation_memory_summary(tmp_path, monkeypatch):
    db_path = tmp_path / "auth.db"
    workspace_dir = tmp_path / "workspace"
    monkeypatch.setattr(db, "DB_PATH", str(db_path))
    store = AssistantWorkspaceStore(str(workspace_dir))
    monkeypatch.setattr(main.assistant_service, "store", store)
    db.init_db()
    token = _seed_user(db_path, "memory@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    store.append_memory(
        1,
        title="activation_dialogue_profile",
        content=(
            "偏好画像：更喜欢先听清来龙去脉，再决定下一步；"
            "压力大时不喜欢连续追问，更接受先接住情绪再给一个小步骤。"
        ),
        tags=["activation", "dialogue_profile"],
    )

    captured = {}

    async def fake_send_message(conn, user_id, text, surface, session_key=None, device_id=None, sender_id=None, attachments=None, metadata=None):
        captured["metadata"] = metadata or {}
        return {
            "surface": surface,
            "session_key": session_key or f"{surface}:{user_id}",
            "text": "收到，你更适合先被接住，再给一个小步骤。",
            "tool_results": [],
            "timestamp_ms": int(time.time() * 1000),
        }

    monkeypatch.setattr(main.assistant_service, "send_message", fake_send_message)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/assistant/send",
            headers=headers,
            json={
                "text": "我今天有点乱，你先别给我很多建议。",
                "surface": "desktop",
                "metadata": {"entrypoint": "chat_main"},
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert "收到" in payload["text"]

    memory_summary = str(captured["metadata"].get("memory_summary") or "")
    assert "偏好画像" in memory_summary
    assert "先接住情绪" in memory_summary
