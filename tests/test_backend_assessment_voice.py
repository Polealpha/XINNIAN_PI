from __future__ import annotations

import json
import sqlite3
import time

from fastapi.testclient import TestClient

import backend.auth as auth
import backend.db as db
import backend.main as main
from backend.assistant_store import AssistantWorkspaceStore


def test_activation_assessment_voice_poll_drives_device_and_completion(tmp_path, monkeypatch):
    db_path = tmp_path / "auth.db"
    workspace_dir = tmp_path / "workspace"
    monkeypatch.setattr(db, "DB_PATH", str(db_path))
    monkeypatch.setattr(main.assistant_service, "store", AssistantWorkspaceStore(str(workspace_dir)))
    db.init_db()

    password = "secret123"
    now_s = int(time.time())
    now_ms = int(time.time() * 1000)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO users (id, username, password_hash, created_at, is_configured) VALUES (?, ?, ?, ?, 1)",
            (1, "voice@example.com", auth.hash_password(password), now_s),
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
        conn.execute(
            """
            INSERT INTO devices (
                user_id, device_id, device_ip, ssid, last_seen_ms, status_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "polealpha-zero2w",
                "192.168.137.50",
                "POLEALPHA",
                now_ms,
                json.dumps({"voice_state": {"session_active": False}}, ensure_ascii=False),
                now_ms,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    state = {"turns": 0}
    device_calls: list[tuple[str, dict]] = []

    async def fake_send_message(session_key: str, text: str) -> str:
        if ":conductor:" in session_key:
            return json.dumps(
                {"question_id": "ei_recharge", "pair": "EI", "question": "忙完一天后你更想自己待着还是找人聊聊？"},
                ensure_ascii=False,
            )
        if ":scorer:" in session_key:
            state["turns"] += 1
            payload = {key: 0.0 for key in ("E", "I", "S", "N", "T", "F", "J", "P")}
            payload.update({"I": 2.0, "N": 2.0, "T": 2.0, "J": 2.0})
            return json.dumps(
                {
                    "pair": "EI",
                    "scores_delta": payload,
                    "effective": True,
                    "evidence_tags": ["EI:I:quiet", "SN:N:big_picture"],
                    "reasoning": "clear signal",
                },
                ensure_ascii=False,
            )
        if ":terminator:" in session_key:
            return json.dumps(
                {
                    "should_finish": True,
                    "reason": "confidence_met",
                    "missing_pair": "",
                },
                ensure_ascii=False,
            )
        return "{}"

    def fake_post_device_json(device_ip: str, path: str, payload: dict, timeout_sec: float = 4.0) -> dict:
        _ = timeout_sec
        assert device_ip == "192.168.137.50"
        device_calls.append((path, payload))
        if path == "/voice/session/start":
            return {"ok": True}
        if path == "/voice/transcribe_recent":
            return {"ok": True, "transcript": "我更喜欢自己安静待一会，再慢慢整理想法"}
        if path == "/voice/session/stop":
            return {"ok": True}
        if path == "/speak":
            return {"ok": True}
        raise AssertionError(path)

    def fake_get_device_json(device_ip: str, path: str, timeout_sec: float = 4.0) -> dict:
        _ = timeout_sec
        assert device_ip == "192.168.137.50"
        assert path == "/voice/status"
        return {"session_active": True, "asr_ready": True, "tts_ready": True, "wake_state": {"ready": True}}

    monkeypatch.setattr(main.assistant_service.gateway, "send_message", fake_send_message)
    monkeypatch.setattr(main, "_post_device_json", fake_post_device_json)
    monkeypatch.setattr(main, "_get_device_json", fake_get_device_json)

    token = auth.create_access_token(1, "voice@example.com")["token"]
    headers = {"Authorization": f"Bearer {token}"}

    with TestClient(main.app) as client:
        started = client.post("/api/activation/assessment/start", headers=headers, json={"surface": "desktop", "voice_mode": "robot"})
        assert started.status_code == 200
        assert started.json()["latest_question"]

        voice_start = client.post("/api/activation/assessment/voice/start", headers=headers, json={"device_id": "polealpha-zero2w"})
        assert voice_start.status_code == 200
        assert voice_start.json()["device_online"] is True
        assert voice_start.json()["prompt_spoken"] is True

        polled = client.post(
            "/api/activation/assessment/voice/poll",
            headers=headers,
            json={"device_id": "polealpha-zero2w", "window_ms": 5000, "speak_question": True},
        )
        assert polled.status_code == 200
        payload = polled.json()
        assert payload["transcript_processed"] is True
        assert payload["state"]["status"] == "completed"
        assert payload["state"]["type_code"]

    spoken_texts = [payload.get("text", "") for path, payload in device_calls if path == "/speak"]
    assert any("忙完一天后" in text for text in spoken_texts)
    assert any("测评完成" in text for text in spoken_texts)
