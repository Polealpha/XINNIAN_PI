from __future__ import annotations

import json
import sqlite3
import time

from fastapi.testclient import TestClient

import backend.auth as auth
import backend.db as db
import backend.main as main
from backend.assistant_store import AssistantWorkspaceStore


def _setup_user(tmp_path, monkeypatch, *, configured: bool = False):
    db_path = tmp_path / "auth.db"
    workspace_dir = tmp_path / "workspace"
    monkeypatch.setattr(db, "DB_PATH", str(db_path))
    monkeypatch.setattr(main.assistant_service, "store", AssistantWorkspaceStore(str(workspace_dir)))
    db.init_db()

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO users (id, username, password_hash, created_at, is_configured) VALUES (?, ?, ?, ?, ?)",
            (1, "owner@example.com", auth.hash_password("secret123"), int(time.time()), 1 if configured else 0),
        )
        conn.commit()
    finally:
        conn.close()
    token = auth.create_access_token(1, "owner@example.com")["token"]
    return {"Authorization": f"Bearer {token}"}, workspace_dir


def test_activation_runtime_status_requires_gateway_and_provider(tmp_path, monkeypatch):
    headers, _workspace_dir = _setup_user(tmp_path, monkeypatch, configured=True)
    monkeypatch.setattr(
        main.assistant_service,
        "runtime_status",
        lambda: {
            "gateway_ready": False,
            "gateway_error": "gateway down",
            "provider_network_ok": True,
            "provider_network_detail": "",
        },
    )

    with TestClient(main.app) as client:
        response = client.get("/api/activation/runtime/status", headers=headers)
        assert response.status_code == 200
        payload = response.json()
        assert payload["ai_ready"] is False
        assert payload["gateway_ready"] is False
        assert payload["provider_network_ok"] is True
        assert payload["blocking_reason"] == "gateway down"


def test_activation_identity_infer_blocks_when_ai_unavailable(tmp_path, monkeypatch):
    headers, _workspace_dir = _setup_user(tmp_path, monkeypatch, configured=False)
    monkeypatch.setattr(
        main.assistant_service,
        "runtime_status",
        lambda: {
            "gateway_ready": False,
            "gateway_error": "OpenClaw gateway unavailable",
            "provider_network_ok": False,
            "provider_network_detail": "network blocked",
        },
    )

    with TestClient(main.app) as client:
        response = client.post(
            "/api/activation/identity/infer",
            headers=headers,
            json={"transcript": "我叫京亮，是这个机器人的主人。", "surface": "desktop"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is False
        assert payload["inference_source"] == "blocked"
        assert "AI" in payload["onboarding_notes"]


def test_activation_identity_infer_uses_ai_result(tmp_path, monkeypatch):
    headers, _workspace_dir = _setup_user(tmp_path, monkeypatch, configured=False)
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

    async def fake_send_message(session_key: str, text: str) -> str:
        assert session_key.startswith("activation:1:infer:")
        assert "京亮" in text
        return json.dumps(
            {
                "preferred_name": "京亮",
                "role_label": "owner",
                "relation_to_robot": "primary_user",
                "identity_summary": "京亮是机器人的主人，后续应优先按主人身份服务。",
                "onboarding_notes": "无需额外人工修正。",
                "voice_intro_summary": "我叫京亮，是机器人的主人。",
                "confidence": 0.96,
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(main.assistant_service.gateway, "send_message", fake_send_message)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/activation/identity/infer",
            headers=headers,
            json={"transcript": "我叫京亮，是这个机器人的主人。", "surface": "desktop"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["preferred_name"] == "京亮"
        assert payload["inference_source"] == "ai"
