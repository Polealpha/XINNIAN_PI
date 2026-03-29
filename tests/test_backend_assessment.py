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
                "京亮是当前机器人的主人。",
                "",
                "我是京亮。",
                "{}",
                "activation-dialogue-v4",
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
        assert payload["question_source"] == "ai_required"
        assert "gateway" in payload["blocking_reason"]


def test_assessment_ai_flow_persists_dialogue_profile_and_memory(tmp_path, monkeypatch):
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

    state = {"count": 0}
    questions = [
        "你在被提醒做事时，更喜欢对方直接一点还是先给你缓冲？",
        "当你压力上来时，你通常会先沉默、先整理，还是想立刻说出来？",
        "别人安抚你时，什么方式最容易让你真正放松下来？",
        "如果有人连续打断你，你更容易烦躁、退开，还是继续配合？",
    ]

    async def fake_send_message(session_key: str, text: str) -> str:
        if ":assessment:conductor:" in session_key:
            index = min(state["count"], len(questions) - 1)
            return json.dumps(
                {
                    "question_id": f"care-q-{index + 1}",
                    "target_area": "care_style",
                    "question": questions[index],
                    "rationale": "补足被关怀和被提醒场景下的稳定反应。",
                },
                ensure_ascii=False,
            )
        if ":assessment:scorer:" in session_key:
            state["count"] += 1
            return json.dumps(
                {
                    "effective": True,
                    "profile_updates": {
                        "summary": "对提醒和安抚方式较敏感，更偏好先被理解、再给具体建议。",
                        "interaction_preferences": ["先共情再建议", "提醒前给缓冲"],
                        "decision_style": "遇事先判断主次，再决定是否马上执行。",
                        "stress_response": "压力上来时会先收一收，不喜欢被连续追问。",
                        "comfort_preferences": ["语气放缓", "先确认感受", "建议要具体"],
                        "avoid_patterns": ["连续催促", "高压命令式提醒"],
                        "care_guidance": "主动关怀时先确认状态，再给一条最小可执行建议。",
                    },
                    "evidence_summary": [f"evidence-{state['count']}"],
                    "reasoning": "已获得一条稳定偏好信号。",
                    "next_focus": "stress_response",
                    "stable_enough": state["count"] >= 4,
                    "confidence": 0.88 if state["count"] >= 4 else 0.45,
                    "summary_hint": "倾向先被理解，再接受具体建议。",
                },
                ensure_ascii=False,
            )
        if ":assessment:terminator:" in session_key:
            return json.dumps(
                {
                    "should_finish": state["count"] >= 4,
                    "reason": "stable_dialogue_profile" if state["count"] >= 4 else "need_more_signal",
                    "missing_area": "" if state["count"] >= 4 else "comfort_preferences",
                    "confidence": 0.9 if state["count"] >= 4 else 0.52,
                },
                ensure_ascii=False,
            )
        if ":assessment:memory:" in session_key:
            return json.dumps(
                {
                    "memory_title": "activation_dialogue_profile",
                    "machine_readable": "name=京亮 | preference_profile=先共情再建议,提醒前给缓冲 | response_profile=压力时先收一收 | source=activation_dialogue",
                    "ai_readable": "后续陪伴时先缓和接住情绪，再给一条可执行建议，避免连续催促。",
                },
                ensure_ascii=False,
            )
        raise AssertionError(f"unexpected session key: {session_key}")

    monkeypatch.setattr(main.assistant_service.gateway, "send_message", fake_send_message)

    with TestClient(main.app) as client:
        started = client.post(
            "/api/activation/assessment/start",
            headers=headers,
            json={"surface": "desktop", "voice_mode": "text", "reset": True},
        )
        assert started.status_code == 200
        start_payload = started.json()
        assert start_payload["status"] == "active"
        assert start_payload["question_source"] == "ai"
        assert start_payload["latest_question"] == questions[0]
        assert start_payload["dialogue_turns"] == []

        latest = start_payload
        for index in range(4):
            response = client.post(
                "/api/activation/assessment/turn",
                headers=headers,
                json={
                    "answer": f"第 {index + 1} 轮回答：我更喜欢先被理解，再听具体建议。",
                    "surface": "desktop",
                    "voice_mode": "text",
                },
            )
            assert response.status_code == 200
            latest = response.json()
            if index == 0:
                roles = [item["role"] for item in latest["dialogue_turns"]]
                assert roles == ["assistant", "user"]
                assert latest["latest_question"] == questions[1]

        assert latest["status"] == "completed"
        assert latest["assessment_ready"] is True
        assert latest["summary"]
        assert latest["interaction_preferences"] == ["先共情再建议", "提醒前给缓冲"]
        assert latest["decision_style"] == "遇事先判断主次，再决定是否马上执行。"
        assert latest["stress_response"] == "压力上来时会先收一收，不喜欢被连续追问。"
        assert latest["comfort_preferences"] == ["语气放缓", "先确认感受", "建议要具体"]
        assert latest["avoid_patterns"] == ["连续催促", "高压命令式提醒"]
        assert latest["care_guidance"] == "主动关怀时先确认状态，再给一条最小可执行建议。"
        assert latest["conversation_count"] == 4
        assert latest["latest_question"] == ""
        assert latest["dialogue_turns"][-1]["role"] == "user"

        state_response = client.get("/api/activation/assessment/state", headers=headers)
        assert state_response.status_code == 200
        state_payload = state_response.json()
        assert state_payload["assessment_ready"] is True
        assert state_payload["summary"] == latest["summary"]

    memory_path = workspace_dir / "assistant_data" / "users" / "1" / "memory.md"
    text = memory_path.read_text(encoding="utf-8")
    assert "source=activation_dialogue" in text
    assert "后续陪伴时先缓和接住情绪" in text
    assert "第 1 轮回答" not in text
