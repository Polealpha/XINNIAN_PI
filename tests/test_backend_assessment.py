from __future__ import annotations

import json
import sqlite3
import time

from fastapi.testclient import TestClient

import backend.auth as auth
import backend.db as db
import backend.main as main
from backend.assistant_store import AssistantWorkspaceStore


def test_activation_assessment_flow_persists_profile_and_memory(tmp_path, monkeypatch):
    db_path = tmp_path / "auth.db"
    workspace_dir = tmp_path / "workspace"
    monkeypatch.setattr(db, "DB_PATH", str(db_path))
    monkeypatch.setattr(main.assistant_service, "store", AssistantWorkspaceStore(str(workspace_dir)))
    db.init_db()

    password = "secret123"
    conn = sqlite3.connect(str(db_path))
    try:
        now_s = int(time.time())
        now_ms = int(time.time() * 1000)
        conn.execute(
            "INSERT INTO users (id, username, password_hash, created_at, is_configured) VALUES (?, ?, ?, ?, 1)",
            (1, "owner@example.com", auth.hash_password(password), now_s),
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
                "v3-native-assessment",
                now_ms,
                now_ms,
                now_ms,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    state = {"turns": 0}

    async def fake_send_message(session_key: str, text: str) -> str:
        if ":conductor:" in session_key:
            return json.dumps({"question_id": "ei_recharge", "pair": "EI", "question": "忙完一天后你更想自己待着还是找人聊聊？"}, ensure_ascii=False)
        if ":scorer:" in session_key:
            state["turns"] += 1
            if state["turns"] <= 3:
                pair = "EI"
                delta = {"I": 1.8}
            elif state["turns"] <= 6:
                pair = "SN"
                delta = {"N": 1.8}
            elif state["turns"] <= 9:
                pair = "TF"
                delta = {"T": 1.8}
            else:
                pair = "JP"
                delta = {"J": 1.8}
            payload = {key: 0.0 for key in ("E", "I", "S", "N", "T", "F", "J", "P")}
            payload.update(delta)
            return json.dumps(
                {
                    "pair": pair,
                    "scores_delta": payload,
                    "effective": True,
                    "evidence_tags": [f"{pair}:signal:{state['turns']}"],
                    "reasoning": "stable preference",
                },
                ensure_ascii=False,
            )
        if ":terminator:" in session_key:
            return json.dumps(
                {
                    "should_finish": state["turns"] >= 12,
                    "reason": "confidence_met" if state["turns"] >= 12 else "need_more_signal",
                    "missing_pair": "" if state["turns"] >= 12 else "JP",
                },
                ensure_ascii=False,
            )
        return "{}"

    monkeypatch.setattr(main.assistant_service.gateway, "send_message", fake_send_message)

    token = auth.create_access_token(1, "owner@example.com")["token"]
    headers = {"Authorization": f"Bearer {token}"}

    with TestClient(main.app) as client:
        started = client.post("/api/activation/assessment/start", headers=headers, json={"surface": "desktop", "voice_mode": "text"})
        assert started.status_code == 200
        assert started.json()["latest_question"]
        assert started.json()["question_source"] == "ai"
        assert started.json()["mode_hint"] == "device_offline_text_available"

        for _ in range(12):
            response = client.post(
                "/api/activation/assessment/turn",
                headers=headers,
                json={"answer": "我更喜欢自己安静想清楚，也会先抓整体方向，再按逻辑提前安排。", "surface": "desktop"},
            )
            assert response.status_code == 200

        final_payload = response.json()
        assert final_payload["status"] == "completed"
        assert final_payload["type_code"]
        assert final_payload["scores"]["I"] > final_payload["scores"]["E"]
        assert final_payload["scoring_source"] == "ai"

        activation_state = client.get("/api/activation/state", headers=headers)
        assert activation_state.status_code == 200
        assert activation_state.json()["assessment_required"] is False

        assessment_state = client.get("/api/activation/assessment/state", headers=headers)
        assert assessment_state.status_code == 200
        assert assessment_state.json()["status"] == "completed"

    memory_path = workspace_dir / "assistant_data" / "users" / "1" / "memory.md"
    assert memory_path.exists()
    memory_text = memory_path.read_text(encoding="utf-8")
    assert "psychometric_profile" in memory_text
    assert "类型" in memory_text
