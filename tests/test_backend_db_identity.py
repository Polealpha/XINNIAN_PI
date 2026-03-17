import sqlite3

import backend.db as db


def test_init_db_creates_identity_tables(tmp_path, monkeypatch):
    db_path = tmp_path / "auth.db"
    monkeypatch.setattr(db, "DB_PATH", str(db_path))
    db.init_db()

    conn = sqlite3.connect(str(db_path))
    try:
        device_columns = {row[1] for row in conn.execute("PRAGMA table_info(devices)").fetchall()}
        chat_columns = {row[1] for row in conn.execute("PRAGMA table_info(chat_messages)").fetchall()}
        assert "onboarding_state" in device_columns
        assert "identity_state" in device_columns
        assert "identity_version" in device_columns
        assert "owner_last_seen_ms" in device_columns
        assert "surface" in chat_columns
        assert "session_key" in chat_columns

        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "device_claim_sessions" in tables
        assert "device_owner_profiles" in tables
        assert "user_activation_profiles" in tables
    finally:
        conn.close()
