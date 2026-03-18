from __future__ import annotations

import json
import sqlite3
import time

from fastapi.testclient import TestClient

import backend.auth as auth
import backend.db as db
import backend.main as main
from backend.assistant_store import AssistantWorkspaceStore


def test_personality_profile_endpoints_and_memory(tmp_path, monkeypatch):
    db_path = tmp_path / "auth.db"
    workspace_dir = tmp_path / "workspace"
    monkeypatch.setattr(db, "DB_PATH", str(db_path))
    monkeypatch.setattr(main.assistant_service, "store", AssistantWorkspaceStore(str(workspace_dir)))

    async def fake_send_message(session_key: str, text: str) -> str:
        assert session_key.startswith("activation:1:personality:")
        return json.dumps(
            {
                "summary": "这个用户偏理性，压力大时不喜欢被催，更适合先给结论再给建议。",
                "response_style": "短句、直接、先给结论。",
                "care_style": "低打扰、先接住情绪，再给一个很小的动作。",
                "traits": ["偏理性", "需要确定感"],
                "topics": ["工作压力", "睡眠节律"],
                "boundaries": ["不要频繁催促", "不要说教"],
                "signals": ["压力大时可能先沉默"],
                "confidence": 0.86,
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(main.assistant_service.gateway, "send_message", fake_send_message)
    db.init_db()

    password = "secret123"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at, is_configured) VALUES (?, ?, ?, 1)",
            ("owner@example.com", auth.hash_password(password), int(time.time())),
        )
        conn.commit()
    finally:
        conn.close()

    token = auth.create_access_token(1, "owner@example.com")["token"]
    headers = {"Authorization": f"Bearer {token}"}

    with TestClient(main.app) as client:
        inferred = client.post(
            "/api/activation/personality/infer",
            headers=headers,
            json={
                "answers": [
                    "别人会说我比较理性，但压力大时会先自己扛一下。",
                    "我不喜欢被催，也不喜欢说教，最好先给结论。",
                ],
                "surface": "desktop",
            },
        )
        assert inferred.status_code == 200
        payload = inferred.json()
        assert payload["summary"]
        assert "偏理性" in payload["traits"]
        assert payload["confidence"] > 0.8

        saved = client.post(
            "/api/activation/personality/complete",
            headers=headers,
            json={
                "summary": payload["summary"],
                "response_style": payload["response_style"],
                "care_style": payload["care_style"],
                "traits": payload["traits"],
                "topics": payload["topics"],
                "boundaries": payload["boundaries"],
                "signals": payload["signals"],
                "confidence": payload["confidence"],
                "sample_count": 2,
                "inference_version": "v1",
                "profile": {"source": "test"},
            },
        )
        assert saved.status_code == 200
        saved_payload = saved.json()
        assert saved_payload["exists"] is True
        assert saved_payload["sample_count"] == 2

        state = client.get("/api/activation/personality/state", headers=headers)
        assert state.status_code == 200
        state_payload = state.json()
        assert state_payload["exists"] is True
        assert state_payload["response_style"] == "短句、直接、先给结论。"

    memory_path = workspace_dir / "assistant_data" / "users" / "1" / "memory.md"
    assert memory_path.exists()
    assert "personality_profile" in memory_path.read_text(encoding="utf-8")


def test_owner_enrollment_start_requires_activation(tmp_path, monkeypatch):
    db_path = tmp_path / "auth.db"
    monkeypatch.setattr(db, "DB_PATH", str(db_path))
    db.init_db()

    password = "secret123"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at, is_configured) VALUES (?, ?, ?, 0)",
            ("owner@example.com", auth.hash_password(password), int(time.time())),
        )
        conn.commit()
    finally:
        conn.close()

    token = auth.create_access_token(1, "owner@example.com")["token"]
    headers = {"Authorization": f"Bearer {token}"}

    with TestClient(main.app) as client:
        response = client.post("/api/device/owner/enrollment/start", headers=headers, json={})
        assert response.status_code == 403


def test_assistant_send_injects_identity_and_personality_metadata(tmp_path, monkeypatch):
    db_path = tmp_path / "auth.db"
    workspace_dir = tmp_path / "workspace"
    monkeypatch.setattr(db, "DB_PATH", str(db_path))
    monkeypatch.setattr(main.assistant_service, "store", AssistantWorkspaceStore(str(workspace_dir)))
    db.init_db()

    password = "secret123"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO users (id, username, password_hash, created_at, is_configured) VALUES (?, ?, ?, ?, 1)",
            (1, "owner@example.com", auth.hash_password(password), int(time.time())),
        )
        conn.execute(
            """
            INSERT INTO user_activation_profiles (
                user_id, preferred_name, role_label, relation_to_robot, pronouns,
                identity_summary, onboarding_notes, voice_intro_summary, profile_json,
                activation_version, completed_at_ms, updated_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "小北",
                "owner",
                "primary_user",
                "",
                "小北是机器人的主人。",
                "",
                "我叫小北。",
                "{}",
                "v2-native",
                int(time.time() * 1000),
                int(time.time() * 1000),
                int(time.time() * 1000),
            ),
        )
        conn.execute(
            """
            INSERT INTO user_personality_profiles (
                user_id, summary, response_style, care_style, traits_json, topics_json,
                boundaries_json, signals_json, profile_json, confidence, sample_count,
                inference_version, updated_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "偏理性，喜欢先结论后解释。",
                "直接、短句。",
                "低打扰。",
                json.dumps(["偏理性"], ensure_ascii=False),
                json.dumps(["工作压力"], ensure_ascii=False),
                json.dumps(["不要催促"], ensure_ascii=False),
                json.dumps(["压力大时先沉默"], ensure_ascii=False),
                "{}",
                0.9,
                3,
                "v1",
                int(time.time() * 1000),
                int(time.time() * 1000),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    captured = {}

    async def fake_send_message(conn, user_id, text, surface, session_key=None, device_id=None, sender_id=None, attachments=None, metadata=None):
        captured["metadata"] = metadata
        return {
            "surface": surface,
            "session_key": session_key or "desktop:1",
            "text": "好的，我记住了。",
            "tool_results": [],
            "timestamp_ms": int(time.time() * 1000),
        }

    monkeypatch.setattr(main.assistant_service, "send_message", fake_send_message)

    token = auth.create_access_token(1, "owner@example.com")["token"]
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(main.app) as client:
        response = client.post("/api/assistant/send", headers=headers, json={"text": "你好", "surface": "desktop"})
        assert response.status_code == 200
        assert response.json()["text"] == "好的，我记住了。"

    metadata = captured["metadata"]
    assert metadata["user_profile"]["identity"]["preferred_name"] == "小北"
    assert metadata["user_profile"]["personality"]["summary"] == "偏理性，喜欢先结论后解释。"
