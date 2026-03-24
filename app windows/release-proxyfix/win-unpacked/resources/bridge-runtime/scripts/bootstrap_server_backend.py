from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = PROJECT_ROOT / "server_backend"


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _prepare_defaults() -> Path:
    data_dir = SERVER_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = Path(os.environ.setdefault("AUTH_DB_PATH", str(data_dir / "auth.db")))
    os.environ.setdefault("AUTH_CORS_ORIGINS", "*")
    os.environ.setdefault("SERVER_HOST", "0.0.0.0")
    os.environ.setdefault("SERVER_PORT", "8000")
    os.environ.setdefault("WEB_CONCURRENCY", "1")
    return db_path


def _resolve_demo_args(args: argparse.Namespace) -> tuple[str, str, bool]:
    username = str(
        args.demo_username
        or os.environ.get("DEMO_USER_EMAIL")
        or os.environ.get("DEMO_USER_USERNAME")
        or ""
    ).strip()
    password = str(args.demo_password or os.environ.get("DEMO_USER_PASSWORD") or "").strip()
    enabled = bool(args.create_demo_user or (username and password))
    return username, password, enabled


def _create_demo_user(db_path: Path, username: str, password: str) -> None:
    sys.path.insert(0, str(PROJECT_ROOT))
    from backend import auth
    from backend.db import init_db

    init_db()
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    try:
        conn.row_factory = sqlite3.Row
        existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if existing:
            print(f"[bootstrap] demo user already exists: {username}")
            return
        now = int(time.time())
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at, is_configured) VALUES (?, ?, ?, ?)",
            (username, auth.hash_password(password), now, 0),
        )
        conn.commit()
        print(f"[bootstrap] created demo user: {username}")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap server backend data and optional demo account.")
    parser.add_argument(
        "--env-file",
        default=str(SERVER_DIR / ".env"),
        help="Path to env file (default: server_backend/.env)",
    )
    parser.add_argument(
        "--create-demo-user",
        action="store_true",
        help="Create demo user from flags or DEMO_USER_EMAIL/DEMO_USER_PASSWORD env vars.",
    )
    parser.add_argument("--demo-username", default="", help="Demo username/email.")
    parser.add_argument("--demo-password", default="", help="Demo password.")
    args = parser.parse_args()

    _load_env_file(Path(args.env_file))
    db_path = _prepare_defaults()

    sys.path.insert(0, str(PROJECT_ROOT))
    from backend.db import init_db

    init_db()
    print(f"[bootstrap] database ready: {db_path}")

    username, password, enabled = _resolve_demo_args(args)
    if enabled:
        if not username or not password:
            raise SystemExit("demo user requested but username/password missing")
        _create_demo_user(db_path, username, password)


if __name__ == "__main__":
    main()
