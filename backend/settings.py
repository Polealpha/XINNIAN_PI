from __future__ import annotations

import os


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value is not None and value != "" else default


AUTH_SECRET_KEY = _env("AUTH_SECRET_KEY", "change-this-secret")
AUTH_ALGORITHM = _env("AUTH_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_SEC = int(_env("ACCESS_TOKEN_EXPIRE_SEC", "900"))  # 15 min
REFRESH_TOKEN_EXPIRE_SEC = int(_env("REFRESH_TOKEN_EXPIRE_SEC", "1209600"))  # 14 days

DB_PATH = _env("AUTH_DB_PATH", "backend/auth.db")

ALLOWED_ORIGINS = _env("AUTH_CORS_ORIGINS", "*")
