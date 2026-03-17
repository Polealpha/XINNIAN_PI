from __future__ import annotations

import json
import sqlite3
import time

from fastapi.testclient import TestClient

import backend.auth as auth
import backend.db as db
import backend.main as main
from backend.assistant_store import AssistantWorkspaceStore


def test_activation_endpoints_and_login_state(tmp_path, monkeypatch):
    db_path = tmp_path / "auth.db"
    workspace_dir = tmp_path / "workspace"
    monkeypatch.setattr(db, "DB_PATH", str(db_path))
    monkeypatch.setattr(main.assistant_service, "store", AssistantWorkspaceStore(str(workspace_dir)))

    async def fake_send_message(session_key: str, text: str) -> str:
        assert session_key.startswith("activation:1:infer:")
        assert "首次激活引导助手" in text
        return json.dumps(
            {
                "preferred_name": "小北",
                "role_label": "owner",
                "relation_to_robot": "primary_user",
                "pronouns": "她",
                "identity_summary": "小北是机器人的主人，后续应优先按主人身份服务。",
                "onboarding_notes": "待确认：是否有固定作息提醒。",
                "voice_intro_summary": "她自称小北，是机器人主人。",
                "confidence": 0.91,
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(main.assistant_service.gateway, "send_message", fake_send_message)
    db.init_db()

    password = "secret123"
    password_hash = auth.hash_password(password)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at, is_configured) VALUES (?, ?, ?, 0)",
            ("owner@example.com", password_hash, int(time.time())),
        )
        conn.commit()
    finally:
        conn.close()

    token = auth.create_access_token(1, "owner@example.com")["token"]
    headers = {"Authorization": f"Bearer {token}"}

    with TestClient(main.app) as client:
        login_before = client.post("/api/auth/login", json={"email": "owner@example.com", "password": password})
        assert login_before.status_code == 200
        assert login_before.json()["activation_required"] is True

        activation_page = client.get("/activate")
        assert activation_page.status_code == 200
        assert "首次激活与身份确认" in activation_page.text

        state_before = client.get("/api/activation/state", headers=headers)
        assert state_before.status_code == 200
        assert state_before.json()["activation_required"] is True

        inferred = client.post(
            "/api/activation/identity/infer",
            headers=headers,
            json={"transcript": "你好，我叫小北，是这个机器人的主人。", "surface": "robot"},
        )
        assert inferred.status_code == 200
        inferred_json = inferred.json()
        assert inferred_json["preferred_name"] == "小北"
        assert inferred_json["role_label"] == "owner"
        assert inferred_json["confidence"] > 0.8

        completed = client.post(
            "/api/activation/complete",
            headers=headers,
            json={
                "preferred_name": inferred_json["preferred_name"],
                "role_label": inferred_json["role_label"],
                "relation_to_robot": inferred_json["relation_to_robot"],
                "pronouns": inferred_json["pronouns"],
                "identity_summary": inferred_json["identity_summary"],
                "onboarding_notes": inferred_json["onboarding_notes"],
                "voice_intro_summary": inferred_json["voice_intro_summary"],
                "profile": {"source": "test"},
                "activation_version": "v1",
            },
        )
        assert completed.status_code == 200
        completed_json = completed.json()
        assert completed_json["activation_required"] is False
        assert completed_json["preferred_code_model"] == "gpt-5.4"

        state_after = client.get("/api/activation/state", headers=headers)
        assert state_after.status_code == 200
        assert state_after.json()["is_configured"] is True

        prompt_pack = client.get("/api/activation/prompt-pack", headers=headers)
        assert prompt_pack.status_code == 200
        assert prompt_pack.json()["preferred_mode"] == "cli"

        login_after = client.post("/api/auth/login", json={"email": "owner@example.com", "password": password})
        assert login_after.status_code == 200
        assert login_after.json()["activation_required"] is False

    memory_path = workspace_dir / "assistant_data" / "users" / "1" / "memory.md"
    assert memory_path.exists()
    assert "首次激活完成" in memory_path.read_text(encoding="utf-8")
