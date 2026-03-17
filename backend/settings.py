from __future__ import annotations

import os


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value is not None and value != "" else default


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


AUTH_SECRET_KEY = _env("AUTH_SECRET_KEY", "change-this-secret")
AUTH_ALGORITHM = _env("AUTH_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_SEC = int(_env("ACCESS_TOKEN_EXPIRE_SEC", "900"))  # 15 min
REFRESH_TOKEN_EXPIRE_SEC = int(_env("REFRESH_TOKEN_EXPIRE_SEC", "1209600"))  # 14 days

DB_PATH = _env("AUTH_DB_PATH", "backend/auth.db")

ALLOWED_ORIGINS = _env("AUTH_CORS_ORIGINS", "*")
DEVICE_PROVISIONING_ENABLED = _env_flag("DEVICE_PROVISIONING_ENABLED", False)
