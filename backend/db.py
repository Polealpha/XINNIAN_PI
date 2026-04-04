from __future__ import annotations

import sqlite3
from typing import Iterator

from .settings import DB_PATH
from .settings import DESKTOP_SHARED_LOGIN_EMAIL, DESKTOP_SHARED_LOGIN_PASSWORD


def get_db() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                is_configured INTEGER NOT NULL DEFAULT 0,
                display_name TEXT,
                avatar_url TEXT,
                bio TEXT,
                location TEXT,
                updated_at INTEGER
            )
            """
        )
        _ensure_column(conn, "users", "is_configured", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "users", "display_name", "TEXT")
        _ensure_column(conn, "users", "avatar_url", "TEXT")
        _ensure_column(conn, "users", "bio", "TEXT")
        _ensure_column(conn, "users", "location", "TEXT")
        _ensure_column(conn, "users", "updated_at", "INTEGER")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token_hash TEXT UNIQUE NOT NULL,
                expires_at INTEGER NOT NULL,
                revoked_at INTEGER,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS emotion_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                timestamp_ms INTEGER NOT NULL,
                type TEXT NOT NULL,
                description TEXT NOT NULL,
                v REAL NOT NULL,
                a REAL NOT NULL,
                t REAL NOT NULL,
                s REAL NOT NULL,
                intensity INTEGER,
                source TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                sender TEXT NOT NULL,
                text TEXT NOT NULL,
                content_type TEXT NOT NULL DEFAULT 'text',
                attachments_json TEXT NOT NULL DEFAULT '[]',
                timestamp_ms INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        _ensure_column(conn, "chat_messages", "content_type", "TEXT NOT NULL DEFAULT 'text'")
        _ensure_column(conn, "chat_messages", "attachments_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "chat_messages", "surface", "TEXT NOT NULL DEFAULT 'desktop'")
        _ensure_column(conn, "chat_messages", "session_key", "TEXT")
        _dedupe_chat_messages(conn)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_usage_daily (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                date_key TEXT NOT NULL,
                web_search_count INTEGER NOT NULL DEFAULT 0,
                emotion_auto_search_count INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL DEFAULT 0,
                UNIQUE(user_id, date_key),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        _ensure_column(conn, "tool_usage_daily", "web_search_count", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "tool_usage_daily", "emotion_auto_search_count", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "tool_usage_daily", "updated_at", "INTEGER NOT NULL DEFAULT 0")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                device_id TEXT NOT NULL,
                device_ip TEXT,
                device_mac TEXT,
                ssid TEXT,
                desired_ssid TEXT,
                network_mismatch INTEGER NOT NULL DEFAULT 0,
                missing_profile INTEGER NOT NULL DEFAULT 0,
                last_switch_reason TEXT,
                last_seen_ms INTEGER,
                status_json TEXT,
                updated_at INTEGER NOT NULL,
                UNIQUE(user_id, device_id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        _ensure_column(conn, "devices", "device_ip", "TEXT")
        _ensure_column(conn, "devices", "device_mac", "TEXT")
        _ensure_column(conn, "devices", "ssid", "TEXT")
        _ensure_column(conn, "devices", "desired_ssid", "TEXT")
        _ensure_column(conn, "devices", "network_mismatch", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "devices", "missing_profile", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "devices", "last_switch_reason", "TEXT")
        _ensure_column(conn, "devices", "last_seen_ms", "INTEGER")
        _ensure_column(conn, "devices", "status_json", "TEXT")
        _ensure_column(conn, "devices", "updated_at", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "devices", "onboarding_state", "TEXT")
        _ensure_column(conn, "devices", "identity_state", "TEXT")
        _ensure_column(conn, "devices", "identity_version", "TEXT")
        _ensure_column(conn, "devices", "owner_last_seen_ms", "INTEGER")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS device_settings_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                device_id TEXT NOT NULL,
                settings_json TEXT NOT NULL DEFAULT '{}',
                updated_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(user_id, device_id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        _ensure_column(conn, "device_settings_profiles", "settings_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(conn, "device_settings_profiles", "updated_at", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "device_settings_profiles", "created_at", "INTEGER NOT NULL DEFAULT 0")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS wifi_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                device_id TEXT NOT NULL,
                ssid TEXT NOT NULL,
                encrypted_password TEXT NOT NULL,
                last_success_at INTEGER,
                last_seen_client_type TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                UNIQUE(user_id, device_id, ssid),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        _ensure_column(conn, "wifi_profiles", "last_success_at", "INTEGER")
        _ensure_column(conn, "wifi_profiles", "last_seen_client_type", "TEXT")
        _ensure_column(conn, "wifi_profiles", "created_at", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "wifi_profiles", "updated_at", "INTEGER NOT NULL DEFAULT 0")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS client_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                client_type TEXT NOT NULL,
                client_id TEXT NOT NULL,
                current_ssid TEXT,
                client_ip TEXT,
                last_seen_ms INTEGER NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                updated_at INTEGER NOT NULL,
                UNIQUE(user_id, client_type, client_id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        _ensure_column(conn, "client_sessions", "current_ssid", "TEXT")
        _ensure_column(conn, "client_sessions", "client_ip", "TEXT")
        _ensure_column(conn, "client_sessions", "last_seen_ms", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "client_sessions", "is_active", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "client_sessions", "updated_at", "INTEGER NOT NULL DEFAULT 0")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS device_claim_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                device_id TEXT NOT NULL,
                claim_token TEXT UNIQUE NOT NULL,
                expires_at_ms INTEGER NOT NULL,
                claimed_at_ms INTEGER NOT NULL,
                claimed_user_id INTEGER NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        _ensure_column(conn, "device_claim_sessions", "is_active", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "device_claim_sessions", "updated_at", "INTEGER NOT NULL DEFAULT 0")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS device_owner_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                device_id TEXT NOT NULL,
                owner_label TEXT NOT NULL,
                embedding_version TEXT NOT NULL,
                enrolled_at_ms INTEGER NOT NULL,
                last_sync_ms INTEGER NOT NULL,
                recognition_enabled INTEGER NOT NULL DEFAULT 1,
                sample_count INTEGER NOT NULL DEFAULT 0,
                similarity_threshold REAL NOT NULL DEFAULT 0,
                embedding_backend TEXT NOT NULL DEFAULT 'face-hist-v1',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                UNIQUE(user_id, device_id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        _ensure_column(conn, "device_owner_profiles", "recognition_enabled", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "device_owner_profiles", "sample_count", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "device_owner_profiles", "similarity_threshold", "REAL NOT NULL DEFAULT 0")
        _ensure_column(conn, "device_owner_profiles", "embedding_backend", "TEXT NOT NULL DEFAULT 'face-hist-v1'")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_activation_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                preferred_name TEXT,
                role_label TEXT,
                relation_to_robot TEXT,
                pronouns TEXT,
                identity_summary TEXT,
                onboarding_notes TEXT,
                voice_intro_summary TEXT,
                profile_json TEXT NOT NULL DEFAULT '{}',
                activation_version TEXT NOT NULL DEFAULT 'v1',
                completed_at_ms INTEGER,
                updated_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        _ensure_column(conn, "user_activation_profiles", "voice_intro_summary", "TEXT")
        _ensure_column(conn, "user_activation_profiles", "profile_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(conn, "user_activation_profiles", "activation_version", "TEXT NOT NULL DEFAULT 'v1'")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_personality_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                summary TEXT,
                response_style TEXT,
                care_style TEXT,
                traits_json TEXT NOT NULL DEFAULT '[]',
                topics_json TEXT NOT NULL DEFAULT '[]',
                boundaries_json TEXT NOT NULL DEFAULT '[]',
                signals_json TEXT NOT NULL DEFAULT '[]',
                profile_json TEXT NOT NULL DEFAULT '{}',
                confidence REAL NOT NULL DEFAULT 0,
                sample_count INTEGER NOT NULL DEFAULT 0,
                inference_version TEXT NOT NULL DEFAULT 'v1',
                updated_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        _ensure_column(conn, "user_personality_profiles", "summary", "TEXT")
        _ensure_column(conn, "user_personality_profiles", "response_style", "TEXT")
        _ensure_column(conn, "user_personality_profiles", "care_style", "TEXT")
        _ensure_column(conn, "user_personality_profiles", "traits_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "user_personality_profiles", "topics_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "user_personality_profiles", "boundaries_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "user_personality_profiles", "signals_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "user_personality_profiles", "profile_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(conn, "user_personality_profiles", "confidence", "REAL NOT NULL DEFAULT 0")
        _ensure_column(conn, "user_personality_profiles", "sample_count", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "user_personality_profiles", "inference_version", "TEXT NOT NULL DEFAULT 'v1'")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_assessment_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                session_json TEXT NOT NULL DEFAULT '{}',
                started_at_ms INTEGER NOT NULL,
                completed_at_ms INTEGER,
                updated_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        _ensure_column(conn, "user_assessment_sessions", "status", "TEXT NOT NULL DEFAULT 'active'")
        _ensure_column(conn, "user_assessment_sessions", "session_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(conn, "user_assessment_sessions", "started_at_ms", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "user_assessment_sessions", "completed_at_ms", "INTEGER")
        _ensure_column(conn, "user_assessment_sessions", "updated_at", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "user_assessment_sessions", "created_at", "INTEGER NOT NULL DEFAULT 0")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_psychometric_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                type_code TEXT,
                scores_json TEXT NOT NULL DEFAULT '{}',
                dimension_confidence_json TEXT NOT NULL DEFAULT '{}',
                evidence_summary_json TEXT NOT NULL DEFAULT '{}',
                summary TEXT,
                response_style TEXT,
                care_style TEXT,
                conversation_count INTEGER NOT NULL DEFAULT 0,
                completed_at_ms INTEGER,
                inference_version TEXT NOT NULL DEFAULT 'assessment-v1',
                profile_json TEXT NOT NULL DEFAULT '{}',
                updated_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        _ensure_column(conn, "user_psychometric_profiles", "type_code", "TEXT")
        _ensure_column(conn, "user_psychometric_profiles", "scores_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(conn, "user_psychometric_profiles", "dimension_confidence_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(conn, "user_psychometric_profiles", "evidence_summary_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(conn, "user_psychometric_profiles", "summary", "TEXT")
        _ensure_column(conn, "user_psychometric_profiles", "response_style", "TEXT")
        _ensure_column(conn, "user_psychometric_profiles", "care_style", "TEXT")
        _ensure_column(conn, "user_psychometric_profiles", "conversation_count", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "user_psychometric_profiles", "completed_at_ms", "INTEGER")
        _ensure_column(conn, "user_psychometric_profiles", "inference_version", "TEXT NOT NULL DEFAULT 'assessment-v1'")
        _ensure_column(conn, "user_psychometric_profiles", "profile_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(conn, "user_psychometric_profiles", "updated_at", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "user_psychometric_profiles", "created_at", "INTEGER NOT NULL DEFAULT 0")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS assessment_turn_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                session_id INTEGER NOT NULL,
                turn_index INTEGER NOT NULL,
                question_id TEXT,
                question_text TEXT,
                answer_text TEXT,
                transcript_text TEXT,
                scoring_json TEXT NOT NULL DEFAULT '{}',
                created_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(session_id) REFERENCES user_assessment_sessions(id)
            )
            """
        )
        _ensure_column(conn, "assessment_turn_events", "question_id", "TEXT")
        _ensure_column(conn, "assessment_turn_events", "question_text", "TEXT")
        _ensure_column(conn, "assessment_turn_events", "answer_text", "TEXT")
        _ensure_column(conn, "assessment_turn_events", "transcript_text", "TEXT")
        _ensure_column(conn, "assessment_turn_events", "scoring_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(conn, "assessment_turn_events", "created_at", "INTEGER NOT NULL DEFAULT 0")
        _ensure_seed_users(conn)
        conn.commit()
    finally:
        conn.close()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cursor = conn.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cursor.fetchall()}
    if column in existing:
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _dedupe_chat_messages(conn: sqlite3.Connection) -> None:
    # Keep the earliest row for identical user/sender/text/timestamp tuples.
    conn.execute(
        """
        DELETE FROM chat_messages
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM chat_messages
            GROUP BY user_id, sender, text, timestamp_ms
        )
        """
    )


def _ensure_seed_users(conn: sqlite3.Connection) -> None:
    from . import auth

    seed_users = [
        {
            "username": str(DESKTOP_SHARED_LOGIN_EMAIL or "").strip() or "desktop-team@example.com",
            "password": str(DESKTOP_SHARED_LOGIN_PASSWORD or "").strip() or "Team123456!",
            "is_configured": 0,
            "display_name": "Desktop Team",
        }
    ]
    now = int(__import__("time").time())
    for seed in seed_users:
        username = str(seed.get("username") or "").strip()
        password = str(seed.get("password") or "").strip()
        if not username or not password:
            continue
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if existing:
            continue
        conn.execute(
            """
            INSERT INTO users (username, password_hash, created_at, is_configured, display_name, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                username,
                auth.hash_password(password),
                now,
                int(seed.get("is_configured", 0) or 0),
                str(seed.get("display_name") or "").strip() or None,
                now,
            ),
        )
