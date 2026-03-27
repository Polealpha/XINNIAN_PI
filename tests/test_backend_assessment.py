from __future__ import annotations

import json
import sqlite3
import time

from fastapi.testclient import TestClient

import backend.auth as auth
import backend.db as db
import backend.main as main
from backend.assistant_store import AssistantWorkspaceStore


def _bootstrap_configured_user(tmp_path, monkeypatch):
    db_path = tmp_path / "auth.db"
    workspace_dir = tmp_path / "workspace"
    monkeypatch.setattr(db, "DB_PATH", str(db_path))
    monkeypatch.setattr(main.assistant_service, "store", AssistantWorkspaceStore(str(workspace_dir)))
    db.init_db()

    now_s = int(time.time())
    now_ms = int(time.time() * 1000)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO users (id, username, password_hash, created_at, is_configured) VALUES (?, ?, ?, ?, 1)",
            (1, "owner@example.com", auth.hash_password("secret123"), now_s),
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
                "京亮",
                "owner",
                "primary_user",
                "",
                "京亮是机器人的主人。",
                "",
                "我叫京亮。",
                "{}",
                "activation-ai-only-v2",
                now_ms,
                now_ms,
                now_ms,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    token = auth.create_access_token(1, "owner@example.com")["token"]
    return {"Authorization": f"Bearer {token}"}, workspace_dir


def test_assessment_blocks_when_ai_unavailable(tmp_path, monkeypatch):
    headers, _workspace_dir = _bootstrap_configured_user(tmp_path, monkeypatch)
    monkeypatch.setattr(
        main.assistant_service,
        "runtime_status",
        lambda: {
            "gateway_ready": False,
            "gateway_error": "gateway unavailable",
            "provider_network_ok": False,
            "provider_network_detail": "provider blocked",
        },
    )

    with TestClient(main.app) as client:
        response = client.post("/api/activation/assessment/start", headers=headers, json={"surface": "desktop"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "blocked"
        assert payload["assessment_ready"] is False
        assert "gateway" in payload["blocking_reason"]


def test_assessment_ai_flow_persists_jung8_profile_and_memory(tmp_path, monkeypatch):
    headers, workspace_dir = _bootstrap_configured_user(tmp_path, monkeypatch)
    monkeypatch.setattr(
        main.assistant_service,
        "runtime_status",
        lambda: {
            "gateway_ready": True,
            "gateway_error": "",
            "provider_network_ok": True,
            "provider_network_detail": "",
        },
    )

    turn_state = {"count": 0}

    async def fake_send_message(session_key: str, text: str) -> str:
        if ":assessment:conductor:" in session_key:
            return json.dumps(
                {
                    "question_id": f"ni-q-{turn_state['count']}",
                    "target_function": "Ni",
                    "question": "面对复杂事情时，你会先抓主线和长期趋势，还是先看眼前细节？",
                },
                ensure_ascii=False,
            )
        if ":assessment:scorer:" in session_key:
            turn_state["count"] += 1
            return json.dumps(
                {
                    "target_function": "Ni",
                    "cognitive_scores": {
                        "Se": 0.1,
                        "Si": 0.0,
                        "Ne": 0.6,
                        "Ni": 1.4,
                        "Te": 0.9,
                        "Ti": 0.8,
                        "Fe": 0.2,
                        "Fi": 0.4,
                    },
                    "function_confidence": {
                        "Se": 0.05,
                        "Si": 0.02,
                        "Ne": 0.18,
                        "Ni": 0.24,
                        "Te": 0.18,
                        "Ti": 0.16,
                        "Fe": 0.05,
                        "Fi": 0.08,
                    },
                    "effective": True,
                    "evidence_summary": [f"ni-evidence-{turn_state['count']}"],
                    "reasoning": "clear long-range and structured signal",
                    "next_gap": "Fi",
                },
                ensure_ascii=False,
            )
        if ":assessment:terminator:" in session_key:
            return json.dumps(
                {
                    "should_finish": turn_state["count"] >= 12,
                    "reason": "function_confidence_met" if turn_state["count"] >= 12 else "need_more_signal",
                    "missing_function": "" if turn_state["count"] >= 12 else "Fi",
                },
                ensure_ascii=False,
            )
        if ":assessment:memory:" in session_key:
            return json.dumps(
                {
                    "memory_title": "psychometric_profile",
                    "machine_readable": "mapped_type=INTJ | functions=Ni:16.8,Te:10.8,Ti:9.6,Ne:7.2,Fi:4.8,Se:1.2,Fe:2.4,Si:0.0 | stack=Ni,Te,Ti,Ne",
                    "ai_readable": "后续互动先给主线判断，再补一条可执行步骤；先讲逻辑，再轻量承接情绪。",
                },
                ensure_ascii=False,
            )
        return "{}"

    monkeypatch.setattr(main.assistant_service.gateway, "send_message", fake_send_message)

    with TestClient(main.app) as client:
        started = client.post("/api/activation/assessment/start", headers=headers, json={"surface": "desktop", "voice_mode": "text"})
        assert started.status_code == 200
        assert started.json()["question_source"] == "ai"

        for index in range(12):
            response = client.post(
                "/api/activation/assessment/turn",
                headers=headers,
                json={"answer": f"第 {index + 1} 轮回答：我会先抓主线，再按逻辑拆步骤。", "surface": "desktop"},
            )
            assert response.status_code == 200

        payload = response.json()
        assert payload["status"] == "completed"
        assert payload["assessment_ready"] is True
        assert payload["mapped_type_code"] == "INTJ"
        assert payload["dominant_stack"][:2] == ["Ni", "Te"]
        assert payload["cognitive_scores"]["Ni"] > payload["cognitive_scores"]["Se"]
        assert payload["function_confidence"]["Ni"] >= 0.72

        finish = client.post("/api/activation/assessment/finish", headers=headers, json={})
        assert finish.status_code == 200
        finish_payload = finish.json()
        assert finish_payload["assessment_ready"] is True
        assert finish_payload["mapped_type_code"] == "INTJ"

    memory_path = workspace_dir / "assistant_data" / "users" / "1" / "memory.md"
    text = memory_path.read_text(encoding="utf-8")
    assert "mapped_type=INTJ" in text
    assert "先给主线判断" in text
    assert "第 1 轮回答" not in text
