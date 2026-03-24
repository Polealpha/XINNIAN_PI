from __future__ import annotations

import json
import sqlite3
import time

from fastapi.testclient import TestClient
from jose import jwt

import backend.auth as auth
import backend.db as db
import backend.main as main
from backend.assistant_store import AssistantWorkspaceStore
from backend.openclaw_gateway import OpenClawGatewayError


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
        assert inferred_json["inference_source"] == "ai"

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


def test_activation_identity_infer_falls_back_to_heuristics(tmp_path, monkeypatch):
    db_path = tmp_path / "auth.db"
    workspace_dir = tmp_path / "workspace"
    monkeypatch.setattr(db, "DB_PATH", str(db_path))
    monkeypatch.setattr(main.assistant_service, "store", AssistantWorkspaceStore(str(workspace_dir)))

    async def broken_send_message(session_key: str, text: str) -> str:
        raise OpenClawGatewayError("OpenClaw state dir not found; set OPENCLAW_STATE_DIR")

    monkeypatch.setattr(main.assistant_service.gateway, "send_message", broken_send_message)
    db.init_db()

    password = "secret123"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at, is_configured) VALUES (?, ?, ?, 0)",
            ("fallback@example.com", auth.hash_password(password), int(time.time())),
        )
        conn.commit()
    finally:
        conn.close()

    token = auth.create_access_token(1, "fallback@example.com")["token"]
    headers = {"Authorization": f"Bearer {token}"}

    with TestClient(main.app) as client:
        inferred = client.post(
            "/api/activation/identity/infer",
            headers=headers,
            json={"transcript": "你好，我叫小北，是这个机器人的主人。", "surface": "robot"},
        )
        assert inferred.status_code == 200
        payload = inferred.json()
        assert payload["preferred_name"] == "小北"
        assert payload["role_label"] == "owner"
        assert payload["relation_to_robot"] == "primary_user"
        assert payload["confidence"] > 0.3
        assert "待确认" in payload["onboarding_notes"]
        assert payload["inference_source"] == "heuristic"


def test_activation_identity_infer_falls_back_on_unexpected_runtime_error(tmp_path, monkeypatch):
    db_path = tmp_path / "auth.db"
    workspace_dir = tmp_path / "workspace"
    monkeypatch.setattr(db, "DB_PATH", str(db_path))
    monkeypatch.setattr(main.assistant_service, "store", AssistantWorkspaceStore(str(workspace_dir)))
    db.init_db()

    password = "secret123"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at, is_configured) VALUES (?, ?, ?, 0)",
            ("fallback-runtime@example.com", auth.hash_password(password), int(time.time())),
        )
        conn.commit()
    finally:
        conn.close()

    async def broken_send_message(session_key: str, text: str) -> str:
        raise RuntimeError("provider timeout")

    monkeypatch.setattr(main.assistant_service.gateway, "send_message", broken_send_message)

    token = auth.create_access_token(1, "fallback-runtime@example.com")["token"]
    headers = {"Authorization": f"Bearer {token}"}

    with TestClient(main.app) as client:
        inferred = client.post(
            "/api/activation/identity/infer",
            headers=headers,
            json={"transcript": "你好，我叫小北，是这个机器人的主人。", "surface": "desktop"},
        )
        assert inferred.status_code == 200
        payload = inferred.json()
        assert payload["preferred_name"] == "小北"
        assert payload["inference_source"] == "heuristic"
        assert "provider timeout" in payload["inference_detail"]


def test_activation_state_exposes_owner_binding_requirement(tmp_path, monkeypatch):
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
            (1, "owner@example.com", auth.hash_password(password), now_s),
        )
        conn.execute(
            """
            INSERT INTO devices (
                user_id, device_id, device_ip, updated_at, onboarding_state, identity_state
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (1, "pi-zero", "127.0.0.1:8090", now_ms, "online", "unenrolled"),
        )
        conn.execute(
            """
            INSERT INTO user_psychometric_profiles (
                user_id, type_code, scores_json, dimension_confidence_json, evidence_summary_json,
                summary, response_style, care_style, conversation_count, completed_at_ms,
                inference_version, profile_json, updated_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "INTJ",
                "{}",
                "{}",
                "{}",
                "stable profile",
                "direct",
                "calm",
                12,
                now_ms,
                "assessment-v1",
                "{}",
                now_ms,
                now_ms,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    token = auth.create_access_token(1, "owner@example.com")["token"]
    headers = {"Authorization": f"Bearer {token}"}

    with TestClient(main.app) as client:
        state = client.get("/api/activation/state", headers=headers)
        assert state.status_code == 200
        payload = state.json()
        assert payload["activation_required"] is False
        assert payload["psychometric_completed"] is True
        assert payload["owner_binding_required"] is True
        assert payload["owner_binding_completed"] is False
        assert payload["preferred_device_id"] == "pi-zero"


def test_activation_runtime_status_reports_ai_and_robot_availability(tmp_path, monkeypatch):
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
            (1, "runtime@example.com", auth.hash_password(password), now_s),
        )
        conn.execute(
            """
            INSERT INTO devices (
                user_id, device_id, device_ip, updated_at, onboarding_state, identity_state
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (1, "pi-zero", "127.0.0.1:8090", now_ms, "online", "unenrolled"),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(
        main.assistant_service,
        "runtime_status",
        lambda: {
            "gateway_ready": False,
            "gateway_error": "OpenClaw gateway unreachable",
        },
    )

    token = auth.create_access_token(1, "runtime@example.com")["token"]
    headers = {"Authorization": f"Bearer {token}"}

    with TestClient(main.app) as client:
        response = client.get("/api/activation/runtime/status", headers=headers)
        assert response.status_code == 200
        payload = response.json()
        assert payload["ai_ready"] is False
        assert payload["device_online"] is True
        assert payload["robot_voice_ready"] is True
        assert payload["preferred_device_id"] == "pi-zero"


def test_owner_enrollment_requires_completed_assessment(tmp_path, monkeypatch):
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
            (1, "owner@example.com", auth.hash_password(password), now_s),
        )
        conn.execute(
            "INSERT INTO devices (user_id, device_id, device_ip, updated_at) VALUES (?, ?, ?, ?)",
            (1, "pi-zero", "127.0.0.1:8090", now_ms),
        )
        conn.commit()
    finally:
        conn.close()

    token = auth.create_access_token(1, "owner@example.com")["token"]
    headers = {"Authorization": f"Bearer {token}"}

    with TestClient(main.app) as client:
        response = client.post(
            "/api/device/owner/enrollment/start",
            headers=headers,
            json={"device_id": "pi-zero", "owner_label": "owner"},
        )
        assert response.status_code == 403
        assert "assessment" in response.json()["detail"].lower()


def _foreign_access_token(user_id: int, username: str) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "username": username,
        "type": "access",
        "iat": now,
        "exp": now + 3600,
        "jti": f"foreign-{user_id}",
    }
    return jwt.encode(payload, "foreign-secret", algorithm=auth.AUTH_ALGORITHM)


def test_local_activation_state_accepts_remote_issued_token(tmp_path, monkeypatch):
    db_path = tmp_path / "auth.db"
    workspace_dir = tmp_path / "workspace"
    monkeypatch.setattr(db, "DB_PATH", str(db_path))
    monkeypatch.setattr(main.assistant_service, "store", AssistantWorkspaceStore(str(workspace_dir)))
    monkeypatch.setattr(main, "ALLOW_UNVERIFIED_LOCAL_DESKTOP_TOKENS", True)
    db.init_db()

    token = _foreign_access_token(7, "remote@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    with TestClient(main.app) as client:
        response = client.get("/api/activation/state", headers=headers)
        assert response.status_code == 200
        payload = response.json()
        assert payload["is_configured"] is False
        assert payload["activation_required"] is True

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        shadow_user = conn.execute("SELECT * FROM users WHERE id = ?", (7,)).fetchone()
        assert shadow_user is not None
        assert int(shadow_user["is_configured"] or 0) == 0
        assert str(shadow_user["username"]) == "remote@example.com"
    finally:
        conn.close()


def test_activation_runtime_status_requires_provider_network(tmp_path, monkeypatch):
    db_path = tmp_path / "auth.db"
    workspace_dir = tmp_path / "workspace"
    monkeypatch.setattr(db, "DB_PATH", str(db_path))
    monkeypatch.setattr(main.assistant_service, "store", AssistantWorkspaceStore(str(workspace_dir)))
    monkeypatch.setattr(main, "ALLOW_UNVERIFIED_LOCAL_DESKTOP_TOKENS", True)
    db.init_db()

    token = _foreign_access_token(11, "runtime-remote@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    monkeypatch.setattr(
        main.assistant_service,
        "runtime_status",
        lambda: {
            "gateway_ready": True,
            "gateway_error": "",
            "provider_network_ok": False,
            "provider_network_detail": "provider timeout",
        },
    )

    with TestClient(main.app) as client:
        response = client.get("/api/activation/runtime/status", headers=headers)
        assert response.status_code == 200
        payload = response.json()
        assert payload["ai_ready"] is False
        assert "provider timeout" in payload["ai_detail"]


def test_owner_binding_endpoints_accept_remote_issued_token(tmp_path, monkeypatch):
    db_path = tmp_path / "auth.db"
    workspace_dir = tmp_path / "workspace"
    monkeypatch.setattr(db, "DB_PATH", str(db_path))
    monkeypatch.setattr(main.assistant_service, "store", AssistantWorkspaceStore(str(workspace_dir)))
    monkeypatch.setattr(main, "ALLOW_UNVERIFIED_LOCAL_DESKTOP_TOKENS", True)
    db.init_db()

    now_s = int(time.time())
    now_ms = int(time.time() * 1000)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO users (id, username, password_hash, created_at, is_configured) VALUES (?, ?, ?, ?, 1)",
            (9, "owner-remote@example.com", auth.hash_password("unused-secret"), now_s),
        )
        conn.execute(
            "INSERT INTO devices (user_id, device_id, device_ip, updated_at, onboarding_state, identity_state) VALUES (?, ?, ?, ?, ?, ?)",
            (9, "pi-zero", "127.0.0.1:8090", now_ms, "online", "unenrolled"),
        )
        conn.execute(
            """
            INSERT INTO user_psychometric_profiles (
                user_id, type_code, scores_json, dimension_confidence_json, evidence_summary_json,
                summary, response_style, care_style, conversation_count, completed_at_ms,
                inference_version, profile_json, updated_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                9,
                "INTJ",
                "{}",
                "{}",
                "{}",
                "stable profile",
                "direct",
                "calm",
                12,
                now_ms,
                "assessment-v1",
                "{}",
                now_ms,
                now_ms,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(
        main,
        "_post_device_json",
        lambda device_ip, path, payload, timeout_sec=4.0: {"ok": True, "path": path, "owner_label": payload.get("owner_label")},
    )

    token = _foreign_access_token(9, "owner-remote@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    with TestClient(main.app) as client:
        status_response = client.get("/api/device/owner/status?device_id=pi-zero", headers=headers)
        assert status_response.status_code == 200
        assert status_response.json()["enrolled"] is False

        start_response = client.post(
            "/api/device/owner/enrollment/start",
            headers=headers,
            json={"device_id": "pi-zero", "owner_label": "owner"},
        )
        assert start_response.status_code == 200
        payload = start_response.json()
        assert payload["ok"] is True
        assert payload["started"] is True
        assert payload["device_id"] == "pi-zero"
