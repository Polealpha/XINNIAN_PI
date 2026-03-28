from __future__ import annotations

import io
import sqlite3
import time
import wave

from fastapi.testclient import TestClient
from jose import jwt

import backend.auth as auth
import backend.db as db
import backend.main as main


def _silent_wav_bytes(duration_ms: int = 300) -> bytes:
    buffer = io.BytesIO()
    frames = int(16000 * (duration_ms / 1000.0))
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * frames)
    return buffer.getvalue()


def _mock_voice_status() -> dict:
    return {
        "ok": True,
        "ready": True,
        "provider_preference": "faster_whisper",
        "fallback_provider": "sherpa_onnx",
        "active_provider": "sherpa_onnx",
        "primary_ready": False,
        "primary_engine": "faster_whisper_unavailable",
        "primary_error": "missing_model",
        "fallback_ready": True,
        "fallback_engine": "sherpa_onnx",
        "fallback_error": None,
        "language": "zh",
        "max_sec": 45,
        "model_name": "distil-large-v3",
        "beam_size": 8,
        "best_of": 5,
        "preprocess_enabled": True,
        "trim_silence_enabled": True,
        "initial_prompt_enabled": True,
        "hotwords_enabled": True,
    }


def test_desktop_voice_status_and_transcribe_route(tmp_path, monkeypatch):
    db_path = tmp_path / "auth.db"
    monkeypatch.setattr(db, "DB_PATH", str(db_path))
    db.init_db()

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO users (id, username, password_hash, created_at, is_configured) VALUES (?, ?, ?, ?, 1)",
            (1, "owner@example.com", auth.hash_password("secret123"), int(time.time())),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(main.desktop_speech_service, "status", _mock_voice_status)
    monkeypatch.setattr(
        main.desktop_speech_service,
        "transcribe_upload",
        lambda **kwargs: {
            "ok": True,
            "transcript": "测试语音输入",
            "provider": "sherpa_onnx",
            "used_fallback": True,
            "duration_ms": 300,
            "latency_ms": 42,
            "context": kwargs.get("context", "chat"),
            "ready": True,
        },
    )
    monkeypatch.setattr(
        main.assistant_service,
        "runtime_status",
        lambda: {
            "gateway_ready": True,
            "gateway_error": "",
            "provider_network_ok": True,
            "provider_network_detail": "",
            "state_dir": "C:\\Users\\jingk\\.openclaw",
            "workspace_dir": "E:\\Desktop\\chonggou\\assistant_data\\openclaw_workspace",
            "robot_bridge_ready": True,
            "desktop_tools": ["desktop.open_url", "robot.pan_tilt"],
        },
    )

    token = auth.create_access_token(1, "owner@example.com")["token"]
    headers = {"Authorization": f"Bearer {token}"}

    with TestClient(main.app) as client:
        status_response = client.get("/api/desktop/voice/status", headers=headers)
        assert status_response.status_code == 200
        assert status_response.json()["ready"] is True
        assert status_response.json()["model_name"] == "distil-large-v3"
        assert status_response.json()["preprocess_enabled"] is True

        runtime_response = client.get("/api/desktop/runtime/status", headers=headers)
        assert runtime_response.status_code == 200
        runtime_payload = runtime_response.json()
        assert runtime_payload["emotion_chain_ready"] is True
        assert runtime_payload["proactive_care_ready"] is True
        assert runtime_payload["voice_chain"]["ready"] is True
        assert runtime_payload["components"]["care_policy_ready"] is True

        transcribe_response = client.post(
            "/api/desktop/voice/transcribe",
            headers=headers,
            files={"file": ("sample.wav", _silent_wav_bytes(), "audio/wav")},
            data={"context": "activation_assessment"},
        )
        assert transcribe_response.status_code == 200
        payload = transcribe_response.json()
        assert payload["ok"] is True
        assert payload["transcript"] == "测试语音输入"
        assert payload["context"] == "activation_assessment"


def test_local_desktop_routes_accept_remote_style_token_on_loopback(tmp_path, monkeypatch):
    db_path = tmp_path / "auth.db"
    monkeypatch.setattr(db, "DB_PATH", str(db_path))
    db.init_db()
    monkeypatch.setattr(main, "ALLOW_UNVERIFIED_LOCAL_DESKTOP_TOKENS", True)
    monkeypatch.setattr(main.desktop_speech_service, "status", _mock_voice_status)
    monkeypatch.setattr(
        main.assistant_service,
        "runtime_status",
        lambda: {
            "gateway_ready": False,
            "gateway_error": "probe timeout",
            "state_dir": "",
            "workspace_dir": "",
            "robot_bridge_ready": False,
            "desktop_tools": [],
        },
    )

    now = int(time.time())
    remote_style_token = jwt.encode(
        {
            "sub": "42",
            "username": "remote-owner@example.com",
            "type": "access",
            "iat": now,
            "exp": now + 900,
            "jti": "remote-jti-1",
        },
        "remote-server-secret",
        algorithm="HS256",
    )
    headers = {"Authorization": f"Bearer {remote_style_token}"}

    with TestClient(main.app) as client:
        voice_response = client.get("/api/desktop/voice/status", headers=headers)
        assert voice_response.status_code == 200

        assistant_response = client.get("/api/assistant/runtime/status", headers=headers)
        assert assistant_response.status_code == 200
        assert assistant_response.json()["gateway_ready"] is False

    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("SELECT id, username FROM users WHERE id = 42").fetchone()
        assert row is not None
        assert row[1] == "remote-owner@example.com"
    finally:
        conn.close()
