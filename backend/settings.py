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
_DEFAULT_OPENCLAW_WORKSPACE = _REPO_ROOT / "assistant_data" / "openclaw_workspace"
_DEFAULT_OPENCLAW_STATE = _REPO_ROOT / "assistant_data" / "openclaw_state"

OPENCLAW_REPO_PATH = _env("OPENCLAW_REPO_PATH", str(_DEFAULT_OPENCLAW_REPO))
OPENCLAW_WORKSPACE_DIR = _env("OPENCLAW_WORKSPACE_DIR", str(_DEFAULT_OPENCLAW_WORKSPACE))
OPENCLAW_STATE_DIR = _env("OPENCLAW_STATE_DIR", str(_DEFAULT_OPENCLAW_STATE))
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
DESKTOP_STT_PROVIDER = _env("DESKTOP_STT_PROVIDER", "faster_whisper")
DESKTOP_STT_FALLBACK_PROVIDER = _env("DESKTOP_STT_FALLBACK_PROVIDER", "sherpa_onnx")
DESKTOP_STT_MODEL_NAME = _env("DESKTOP_STT_MODEL_NAME", "small")
DESKTOP_STT_LANGUAGE = _env("DESKTOP_STT_LANGUAGE", "zh")
DESKTOP_STT_DEVICE = _env("DESKTOP_STT_DEVICE", "cpu")
DESKTOP_STT_COMPUTE_TYPE = _env("DESKTOP_STT_COMPUTE_TYPE", "int8")
DESKTOP_STT_BEAM_SIZE = int(_env("DESKTOP_STT_BEAM_SIZE", "5"))
DESKTOP_STT_VAD_FILTER = _env("DESKTOP_STT_VAD_FILTER", "1").strip().lower() not in {"0", "false", "no"}
DESKTOP_STT_MAX_SEC = int(_env("DESKTOP_STT_MAX_SEC", "45"))
DESKTOP_STT_NUM_THREADS = int(_env("DESKTOP_STT_NUM_THREADS", "4"))
DEFAULT_ROBOT_DEVICE_IP = _env("DEFAULT_ROBOT_DEVICE_IP", "192.168.137.50")
