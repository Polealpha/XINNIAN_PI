from __future__ import annotations

import sqlite3
import time

from fastapi.testclient import TestClient

import backend.auth as auth
import backend.db as db
import backend.main as main
from backend.assistant_store import AssistantWorkspaceStore


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


def test_llm_care_uses_project_prompt_and_returns_ai_source(tmp_path, monkeypatch):
    db_path = tmp_path / "auth.db"
    workspace_dir = tmp_path / "workspace"
    monkeypatch.setattr(db, "DB_PATH", str(db_path))
    monkeypatch.setattr(main.assistant_service, "store", AssistantWorkspaceStore(str(workspace_dir)))
    db.init_db()
    token = _seed_user(db_path, "care@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    captured = {}

    monkeypatch.setattr(
        main.assistant_service,
        "runtime_status",
        lambda: {"gateway_ready": True, "gateway_error": ""},
    )

    async def fake_send_message(conn, user_id, text, surface, session_key=None, metadata=None, **kwargs):
        captured["text"] = text
        captured["metadata"] = metadata or {}
        return {"text": "我接住你这一下了。我们先只处理现在最卡的那一点，好吗？"}

    monkeypatch.setattr(main.assistant_service, "send_message", fake_send_message)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/llm/care",
            headers=headers,
            json={
                "current_emotion": "stress",
                "context": "今天一堆事压在一起，我有点乱。",
                "history": [{"sender": "user", "text": "我今天状态一般", "timestamp_ms": int(time.time() * 1000)}],
                "expression_label": "sadness",
                "expression_confidence": 0.72,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["source"] == "ai"
        assert payload["ai_ready"] is True
        assert "最卡的那一点" in payload["text"]

    assert "共鸣连接" in captured["text"]
    assert "主动关怀助手" in captured["text"]
    assert captured["metadata"]["entrypoint"] == "llm_care"
    assert captured["metadata"]["care_channel"] == "proactive_care"
    assert captured["metadata"]["assistant_native_control"] is False


def test_llm_care_returns_project_fallback_when_openclaw_not_ready(tmp_path, monkeypatch):
    db_path = tmp_path / "auth.db"
    workspace_dir = tmp_path / "workspace"
    monkeypatch.setattr(db, "DB_PATH", str(db_path))
    monkeypatch.setattr(main.assistant_service, "store", AssistantWorkspaceStore(str(workspace_dir)))
    db.init_db()
    token = _seed_user(db_path, "care-fallback@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    monkeypatch.setattr(
        main.assistant_service,
        "runtime_status",
        lambda: {"gateway_ready": False, "gateway_error": "OpenClaw state dir not found; set OPENCLAW_STATE_DIR"},
    )

    with TestClient(main.app) as client:
        response = client.post(
            "/api/llm/care",
            headers=headers,
            json={
                "current_emotion": "sadness",
                "context": "我今天有点提不起劲。",
                "history": [],
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["source"] == "fallback"
        assert payload["ai_ready"] is False
        assert "OPENCLAW_STATE_DIR" in payload["detail"]
        assert "低落" in payload["text"] or "先别急" in payload["text"]
