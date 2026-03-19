from __future__ import annotations

import os
from pathlib import Path


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value is not None and value != "" else default


AUTH_SECRET_KEY = _env("AUTH_SECRET_KEY", "change-this-secret")
AUTH_ALGORITHM = _env("AUTH_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_SEC = int(_env("ACCESS_TOKEN_EXPIRE_SEC", "900"))  # 15 min
REFRESH_TOKEN_EXPIRE_SEC = int(_env("REFRESH_TOKEN_EXPIRE_SEC", "1209600"))  # 14 days

DB_PATH = _env("AUTH_DB_PATH", "backend/auth.db")

ALLOWED_ORIGINS = _env("AUTH_CORS_ORIGINS", "*")

_BACKEND_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _BACKEND_DIR.parent
_DEFAULT_OPENCLAW_REPO = _REPO_ROOT.parent / "openclaw"
_DEFAULT_OPENCLAW_WORKSPACE = _DEFAULT_OPENCLAW_REPO / ".openclaw-workspace"

OPENCLAW_REPO_PATH = _env("OPENCLAW_REPO_PATH", str(_DEFAULT_OPENCLAW_REPO))
OPENCLAW_WORKSPACE_DIR = _env("OPENCLAW_WORKSPACE_DIR", str(_DEFAULT_OPENCLAW_WORKSPACE))
OPENCLAW_STATE_DIR = _env("OPENCLAW_STATE_DIR", str(Path.home() / ".openclaw"))
OPENCLAW_GATEWAY_URL = _env("OPENCLAW_GATEWAY_URL", "")
OPENCLAW_GATEWAY_ORIGIN = _env("OPENCLAW_GATEWAY_ORIGIN", "")
OPENCLAW_TIMEOUT_MS = int(_env("OPENCLAW_TIMEOUT_MS", "300000"))
OPENCLAW_CLIENT_ID = _env("OPENCLAW_CLIENT_ID", "gateway-client")
OPENCLAW_CLIENT_MODE = _env("OPENCLAW_CLIENT_MODE", "backend")
ASSISTANT_BRIDGE_TOKEN = _env("ASSISTANT_BRIDGE_TOKEN", "change-this-bridge-token")
ASSISTANT_BRIDGE_USER_ID = int(_env("ASSISTANT_BRIDGE_USER_ID", "1"))
DESKTOP_APP_ALLOWLIST_JSON = _env(
    "DESKTOP_APP_ALLOWLIST_JSON",
    '{"notepad":["notepad"],"calc":["calc"],"explorer":["explorer"],"vscode":["code"],"chrome":["cmd","/c","start","chrome"],"edge":["cmd","/c","start","msedge"]}',
)
OPENCLAW_PREFERRED_MODE = _env("OPENCLAW_PREFERRED_MODE", "cli")
OPENCLAW_PREFERRED_CODE_MODEL = _env("OPENCLAW_PREFERRED_CODE_MODEL", "gpt-5.4")
