from __future__ import annotations

import sqlite3
from typing import Iterator

from .settings import DB_PATH


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
