from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import uvicorn


SERVER_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SERVER_DIR.parent


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


def _as_int(value: str, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _prepare_defaults() -> None:
    data_dir = SERVER_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("AUTH_DB_PATH", str(data_dir / "auth.db"))
    os.environ.setdefault("AUTH_CORS_ORIGINS", "*")
    os.environ.setdefault("SERVER_HOST", "0.0.0.0")
    os.environ.setdefault("SERVER_PORT", "8000")
    os.environ.setdefault("WEB_CONCURRENCY", "1")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run production-style backend for remote access.")
    parser.add_argument(
        "--env-file",
        default=str(SERVER_DIR / ".env"),
        help="Path to env file (default: server_backend/.env)",
    )
    parser.add_argument("--host", default="", help="Override bind host")
    parser.add_argument("--port", type=int, default=0, help="Override bind port")
    parser.add_argument("--workers", type=int, default=0, help="Override worker count")
    args = parser.parse_args()

    _load_env_file(Path(args.env_file))
    _prepare_defaults()

    host = args.host or os.environ.get("SERVER_HOST", "0.0.0.0")
    port = args.port or _as_int(os.environ.get("SERVER_PORT", "8000"), 8000)
    workers = args.workers or _as_int(os.environ.get("WEB_CONCURRENCY", "1"), 1)

    sys.path.insert(0, str(PROJECT_ROOT))
    os.chdir(PROJECT_ROOT)

    print(f"[server_backend] root={PROJECT_ROOT}")
    print(f"[server_backend] host={host} port={port} workers={workers}")
    print(f"[server_backend] db={os.environ.get('AUTH_DB_PATH')}")
    print(f"[server_backend] cors={os.environ.get('AUTH_CORS_ORIGINS')}")

    uvicorn.run(
        "backend.main:app",
        host=host,
        port=port,
        workers=max(1, workers),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()

