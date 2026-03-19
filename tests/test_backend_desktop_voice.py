from __future__ import annotations

import io
import sqlite3
import time
import wave

from fastapi.testclient import TestClient

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

    monkeypatch.setattr(
        main.desktop_speech_service,
        "status",
        lambda: {
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
        },
    )
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
