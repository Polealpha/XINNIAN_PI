from __future__ import annotations

import json
import sqlite3
import time

from fastapi.testclient import TestClient

import backend.auth as auth
import backend.db as db
import backend.main as main


def test_device_settings_routes_persist_and_enqueue_signals(tmp_path, monkeypatch):
    db_path = tmp_path / "auth.db"
    monkeypatch.setattr(db, "DB_PATH", str(db_path))
    db.init_db()

    password = "secret123"
    now_ms = int(time.time() * 1000)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at, is_configured) VALUES (?, ?, ?, 1)",
            ("owner@example.com", auth.hash_password(password), int(time.time())),
        )
        conn.execute(
            """
            INSERT INTO devices (
                user_id, device_id, device_ip, ssid, desired_ssid, network_mismatch, missing_profile,
                last_switch_reason, last_seen_ms, status_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?)
            """,
            (
                1,
                "pi-zero",
                "127.0.0.1:8090",
                "POLEALPHA",
                "POLEALPHA",
                "initial",
                now_ms,
                json.dumps({"ui_state": {"page": "expression", "screen_awake": True}}, ensure_ascii=False),
                now_ms,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    main._ensure_signal_state()
    while main._drain_signals(50):
        pass

    token = auth.create_access_token(1, "owner@example.com")["token"]
    headers = {"Authorization": f"Bearer {token}"}

    with TestClient(main.app) as client:
        fetched = client.get("/api/device/settings", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["device_id"] == "pi-zero"
        assert fetched.json()["settings"]["wake"]["wake_phrase"] == "小念"

        updated = client.post(
            "/api/device/settings",
            headers=headers,
            json={
                "device_id": "pi-zero",
                "settings": {
                    "behavior": {"settings_auto_return_sec": 18, "daily_trigger_limit": 9},
                    "wake": {"wake_phrase": "小暖"},
                    "media": {"camera_enabled": False},
                },
            },
        )
        assert updated.status_code == 200
        payload = updated.json()
        assert payload["settings"]["behavior"]["settings_auto_return_sec"] == 18
        assert payload["settings"]["behavior"]["daily_trigger_limit"] == 9
        assert payload["settings"]["wake"]["wake_phrase"] == "小暖"
        assert payload["settings"]["media"]["camera_enabled"] is False

        opened = client.post("/api/device/settings/open", headers=headers, json={"device_id": "pi-zero", "source": "button"})
        assert opened.status_code == 200
        assert opened.json()["ui_state"]["page"] == "settings"

        closed = client.post("/api/device/settings/close", headers=headers, json={"device_id": "pi-zero", "source": "desktop"})
        assert closed.status_code == 200
        assert closed.json()["ui_state"]["page"] == "expression"

    signals = main._drain_signals(10)
    signal_types = [item.get("type") for item in signals]
    assert "settings_apply" in signal_types
    assert "settings_page_open" in signal_types
    assert "settings_page_close" in signal_types
