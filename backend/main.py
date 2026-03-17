from __future__ import annotations

import json
import asyncio
import time
import threading
import shutil
import re
import subprocess
import base64
import hashlib
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, status, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from sqlite3 import Connection
import httpx
from cryptography.fernet import Fernet, InvalidToken

from . import auth
from .db import get_db, init_db
from .schemas import (
    CareRequest,
    CareResponse,
    DailySummaryRequest,
    DailySummaryResponse,
    DeviceInfoResponse,
    DeviceHeartbeatRequest,
    DeviceHeartbeatResponse,
    ClientSessionHeartbeatRequest,
    ClientSessionHeartbeatResponse,
    DeviceStatusResponse,
    EngineEventRequest,
    EngineSignalPullRequest,
    EngineSignalPullResponse,
    EngineSignalRequest,
    EmotionEventRequest,
    EmotionEventResponse,
    LoginEmailRequest,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    ProvisionRequest,
    ProvisionResponse,
    ProvisionExecuteRequest,
    ProvisionExecuteResponse,
    ProfileResponse,
    ProfileUpdateRequest,
    RealtimeScoresResponse,
    RealtimeRiskDetailResponse,
    RefreshRequest,
    RegisterRequest,
    ChatMessageRequest,
    ChatMessageResponse,
    TokenResponse,
    UserResponse,
)
from .settings import ACCESS_TOKEN_EXPIRE_SEC, ALLOWED_ORIGINS, AUTH_SECRET_KEY
from .provisioning import run_provisioning

app = FastAPI(title="Auth Backend", version="0.1.0")
UPLOAD_ROOT = Path(__file__).resolve().parent / "uploads"
CHAT_UPLOAD_ROOT = UPLOAD_ROOT / "chat"
CHAT_UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_ROOT)), name="uploads")

cors_origins = [origin.strip() for origin in ALLOWED_ORIGINS.split(",") if origin.strip()]
if not cors_origins:
    cors_origins = ["*"]
allow_all_origins = len(cors_origins) == 1 and cors_origins[0] == "*"

app.add_middleware(
    CORSMiddleware,
    allow_origins=[] if allow_all_origins else cors_origins,
    allow_origin_regex=".*" if allow_all_origins else None,
    # With wildcard origins, credentials must be disabled to keep CORS valid in browsers.
    allow_credentials=not allow_all_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

bearer_scheme = HTTPBearer(auto_error=False)
_llm = None
_llm_config = None
HEARTBEAT_STALE_MS = 30000
CLIENT_SESSION_STALE_MS = 45000
_RUNTIME_BOOT_TS = int(time.time() * 1000)
_TOOL_LEAK_PATTERNS = [
    r'"function_call"\s*:',
    r'"tool_call"\s*:',
    r"\bweb_search\b",
    r"^\s*\{[\s\S]*\}\s*$",
]


def _safe_git(cmd: List[str]) -> str:
    try:
        out = subprocess.check_output(cmd, cwd=str(Path(__file__).resolve().parents[1]), stderr=subprocess.DEVNULL)
        return out.decode("utf-8", errors="ignore").strip()
    except Exception:
        return ""


def _runtime_version_payload() -> Dict[str, object]:
    return {
        "git_sha": _safe_git(["git", "rev-parse", "--short", "HEAD"]) or "unknown",
        "git_branch": _safe_git(["git", "rev-parse", "--abbrev-ref", "HEAD"]) or "unknown",
        "build_ts": _RUNTIME_BOOT_TS,
        "bridge_git_sha": _safe_git(["git", "rev-parse", "--short", "HEAD"]) or "unknown",
    }


def _looks_tool_call_leak_text(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    return any(re.search(p, raw, flags=re.IGNORECASE) for p in _TOOL_LEAK_PATTERNS)


def _sanitize_outbound_bot_text(text: str) -> tuple[str, bool]:
    raw = str(text or "").strip()
    if not raw:
        return "", False
    if not _looks_tool_call_leak_text(raw):
        return raw, False
    if re.search(r'"function_call"\s*:', raw, flags=re.IGNORECASE) or re.search(
        r'"tool_call"\s*:', raw, flags=re.IGNORECASE
    ):
        return "我已经拿到工具结果，但中间格式异常。你再问一次，我直接给你结论。", True
    cleaned = re.sub(r'(?is)\{\s*"function_call"\s*:\s*\{.*?\}\s*\}', " ", raw)
    cleaned = re.sub(r'(?is)\{\s*"tool_call"\s*:\s*\{.*?\}\s*\}', " ", cleaned)
    cleaned = re.sub(r"(?im)^\s*(function_call|tool_call)\s*[:：].*$", " ", cleaned)
    cleaned = re.sub(r"^```(?:json)?|```$", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    if cleaned:
        return cleaned, True
    return "我已经拿到工具结果，但中间格式异常。你再问一次，我直接给你结论。", True


class EventManager:
    def __init__(self) -> None:
        self._connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._connections:
            self._connections.remove(websocket)

    async def broadcast(self, message: Dict[str, object]) -> None:
        if not self._connections:
            return
        dead: List[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


event_manager = EventManager()


@app.on_event("startup")
def _startup() -> None:
    init_db()
    _init_llm()
    _ensure_signal_state()


@app.get("/api/runtime/version")
def runtime_version() -> Dict[str, object]:
    payload = _runtime_version_payload()
    payload["ok"] = True
    return payload


def _wifi_cipher() -> Fernet:
    secret = (AUTH_SECRET_KEY or "change-this-secret").encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


def _encrypt_wifi_password(password: str) -> str:
    raw = str(password or "")
    if not raw:
        return ""
    return _wifi_cipher().encrypt(raw.encode("utf-8")).decode("utf-8")


def _decrypt_wifi_password(token: str) -> str:
    raw = str(token or "").strip()
    if not raw:
        return ""
    try:
        return _wifi_cipher().decrypt(raw.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        return ""


def _ensure_signal_state() -> None:
    if not hasattr(app.state, "signal_queue"):
        app.state.signal_queue = deque()
    if not hasattr(app.state, "signal_lock"):
        app.state.signal_lock = threading.Lock()


def _enqueue_signal(signal: Dict[str, object]) -> None:
    _ensure_signal_state()
    lock = app.state.signal_lock
    with lock:
        app.state.signal_queue.append(signal)


def _drain_signals(limit: int) -> List[Dict[str, object]]:
    _ensure_signal_state()
    lock = app.state.signal_lock
    signals: List[Dict[str, object]] = []
    with lock:
        while app.state.signal_queue and len(signals) < limit:
            signals.append(app.state.signal_queue.popleft())
    return signals


def _is_local_request(request: Request) -> bool:
    if not request.client:
        return False
    host = str(request.client.host or "")
    return host in {"127.0.0.1", "::1", "localhost"}


def _init_llm() -> None:
    global _llm, _llm_config
    try:
        from engine.core.config import load_engine_config
        from engine.llm.llm_responder import LLMResponder

        config = load_engine_config("config/engine_config.json")
        _llm = LLMResponder(config.llm)
        _llm_config = config.llm
    except Exception:
        _llm = None
        _llm_config = None


def _get_user_by_username(conn: Connection, username: str) -> Dict:
    cur = conn.execute("SELECT * FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    return dict(row) if row else {}


def _get_user_by_id(conn: Connection, user_id: int) -> Dict:
    cur = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    return dict(row) if row else {}


def _profile_from_user(user: Dict) -> Dict:
    username = str(user.get("username") or "").strip()
    display_name = str(user.get("display_name") or "").strip()
    if not display_name:
        display_name = username or "鍏遍福鏃呬汉"
    avatar_url = user.get("avatar_url")
    if avatar_url is not None:
        avatar_url = str(avatar_url).strip() or None
    bio = user.get("bio")
    if bio is not None:
        bio = str(bio).strip() or None
    location = user.get("location")
    if location is not None:
        location = str(location).strip() or None
    return {
        "id": int(user.get("id", 0)),
        "username": username,
        "display_name": display_name,
        "avatar_url": avatar_url,
        "bio": bio,
        "location": location,
        "created_at": int(user.get("created_at") or 0),
        "updated_at": int(user.get("updated_at") or 0) or None,
    }


def _get_default_user_id(conn: Connection) -> Optional[int]:
    cur = conn.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1")
    row = cur.fetchone()
    return int(row["id"]) if row else None


def _set_user_configured(conn: Connection, user_id: int, value: bool) -> None:
    conn.execute("UPDATE users SET is_configured = ? WHERE id = ?", (1 if value else 0, user_id))
    conn.commit()


def _list_emotion_events(
    conn: Connection,
    user_id: int,
    limit: int,
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
) -> List[Dict]:
    query = (
        "SELECT * FROM emotion_events "
        "WHERE user_id = ? AND type IN ('HAPPY','SAD','ANGRY','CALM','TIRED','ANXIOUS')"
    )
    params: List[Any] = [user_id]
    if start_ms is not None:
        query += " AND timestamp_ms >= ?"
        params.append(int(start_ms))
    if end_ms is not None:
        query += " AND timestamp_ms <= ?"
        params.append(int(end_ms))
    query += " ORDER BY timestamp_ms DESC LIMIT ?"
    params.append(limit)
    cur = conn.execute(query, params)
    return [dict(row) for row in cur.fetchall()]


def _insert_emotion_event(conn: Connection, user_id: int, payload: EmotionEventRequest) -> int:
    cur = conn.execute(
        """
        INSERT INTO emotion_events (
            user_id, timestamp_ms, type, description, v, a, t, s, intensity, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            payload.timestamp_ms,
            payload.type,
            payload.description,
            payload.V,
            payload.A,
            payload.T,
            payload.S,
            payload.intensity,
            payload.source,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def _list_chat_messages(conn: Connection, user_id: int, limit: int) -> List[Dict]:
    cur = conn.execute(
        """
        SELECT * FROM chat_messages
        WHERE user_id = ?
        ORDER BY timestamp_ms ASC
        LIMIT ?
        """,
        (user_id, limit),
    )
    rows = [dict(row) for row in cur.fetchall()]
    for row in rows:
        attachments_raw = row.get("attachments_json", "[]")
        try:
            attachments = json.loads(str(attachments_raw or "[]"))
            if not isinstance(attachments, list):
                attachments = []
        except Exception:
            attachments = []
        row["attachments"] = attachments
        row["content_type"] = str(row.get("content_type") or "text")
    return rows


def _insert_chat_message(conn: Connection, user_id: int, payload: ChatMessageRequest) -> int:
    attachments_json = "[]"
    try:
        attachments_json = json.dumps(payload.attachments or [], ensure_ascii=False, separators=(",", ":"))
    except Exception:
        attachments_json = "[]"
    cur = conn.execute(
        """
        INSERT INTO chat_messages (user_id, sender, text, content_type, attachments_json, timestamp_ms)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            payload.sender,
            payload.text,
            str(payload.content_type or "text"),
            attachments_json,
            payload.timestamp_ms,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def _usage_date_key(ts_ms: Optional[int] = None) -> str:
    now_ms = int(ts_ms if ts_ms is not None else time.time() * 1000)
    return time.strftime("%Y-%m-%d", time.localtime(now_ms / 1000.0))


def _get_tool_usage_daily(conn: Connection, user_id: int, date_key: str) -> Dict[str, int]:
    cur = conn.execute(
        """
        SELECT web_search_count, emotion_auto_search_count
        FROM tool_usage_daily
        WHERE user_id = ? AND date_key = ?
        """,
        (int(user_id), str(date_key)),
    )
    row = cur.fetchone()
    if not row:
        return {"web_search_count": 0, "emotion_auto_search_count": 0}
    return {
        "web_search_count": int(row["web_search_count"] or 0),
        "emotion_auto_search_count": int(row["emotion_auto_search_count"] or 0),
    }


def _bump_tool_usage_daily(
    conn: Connection,
    user_id: int,
    date_key: str,
    web_search_delta: int = 0,
    emotion_auto_delta: int = 0,
) -> None:
    if web_search_delta == 0 and emotion_auto_delta == 0:
        return
    now_ms = int(time.time() * 1000)
    conn.execute(
        """
        INSERT INTO tool_usage_daily (
            user_id, date_key, web_search_count, emotion_auto_search_count, updated_at
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, date_key) DO UPDATE SET
            web_search_count = web_search_count + excluded.web_search_count,
            emotion_auto_search_count = emotion_auto_search_count + excluded.emotion_auto_search_count,
            updated_at = excluded.updated_at
        """,
        (int(user_id), str(date_key), int(web_search_delta), int(emotion_auto_delta), now_ms),
    )
    conn.commit()


def _list_devices(conn: Connection, user_id: int) -> List[Dict]:
    cur = conn.execute(
        """
        SELECT * FROM devices
        WHERE user_id = ?
        ORDER BY updated_at DESC
        """,
        (user_id,),
    )
    return [dict(row) for row in cur.fetchall()]


def _get_device(conn: Connection, user_id: int, device_id: str) -> Dict:
    cur = conn.execute(
        """
        SELECT * FROM devices
        WHERE user_id = ? AND device_id = ?
        """,
        (user_id, device_id),
    )
    row = cur.fetchone()
    return dict(row) if row else {}


def _get_device_owner(conn: Connection, device_id: str) -> Dict:
    cur = conn.execute(
        """
        SELECT * FROM devices
        WHERE device_id = ?
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (device_id,),
    )
    row = cur.fetchone()
    return dict(row) if row else {}


def _list_wifi_profiles(conn: Connection, user_id: int, device_id: str) -> List[Dict]:
    rows = conn.execute(
        """
        SELECT * FROM wifi_profiles
        WHERE user_id = ? AND device_id = ?
        ORDER BY COALESCE(last_success_at, 0) DESC, updated_at DESC
        """,
        (user_id, device_id),
    ).fetchall()
    return [dict(row) for row in rows]


def _upsert_wifi_profile(
    conn: Connection,
    user_id: int,
    device_id: str,
    ssid: str,
    password: str,
    client_type: str,
) -> Dict:
    now_ms = int(time.time() * 1000)
    existing = conn.execute(
        """
        SELECT * FROM wifi_profiles
        WHERE user_id = ? AND device_id = ? AND ssid = ?
        """,
        (user_id, device_id, ssid),
    ).fetchone()
    encrypted = _encrypt_wifi_password(password)
    if existing:
        conn.execute(
            """
            UPDATE wifi_profiles
            SET encrypted_password = ?,
                last_seen_client_type = ?,
                updated_at = ?
            WHERE user_id = ? AND device_id = ? AND ssid = ?
            """,
            (encrypted, client_type, now_ms, user_id, device_id, ssid),
        )
    else:
        conn.execute(
            """
            INSERT INTO wifi_profiles (
                user_id, device_id, ssid, encrypted_password,
                last_success_at, last_seen_client_type, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, NULL, ?, ?, ?)
            """,
            (user_id, device_id, ssid, encrypted, client_type, now_ms, now_ms),
        )
    conn.commit()
    row = conn.execute(
        """
        SELECT * FROM wifi_profiles
        WHERE user_id = ? AND device_id = ? AND ssid = ?
        """,
        (user_id, device_id, ssid),
    ).fetchone()
    return dict(row) if row else {}


def _mark_wifi_profile_success(conn: Connection, user_id: int, device_id: str, ssid: str) -> None:
    now_ms = int(time.time() * 1000)
    conn.execute(
        """
        UPDATE wifi_profiles
        SET last_success_at = ?, updated_at = ?
        WHERE user_id = ? AND device_id = ? AND ssid = ?
        """,
        (now_ms, now_ms, user_id, device_id, ssid),
    )
    conn.commit()


def _upsert_client_session(
    conn: Connection,
    user_id: int,
    client_type: str,
    client_id: str,
    current_ssid: Optional[str],
    client_ip: Optional[str],
    is_active: bool,
) -> Dict:
    now_ms = int(time.time() * 1000)
    row = conn.execute(
        """
        SELECT * FROM client_sessions
        WHERE user_id = ? AND client_type = ? AND client_id = ?
        """,
        (user_id, client_type, client_id),
    ).fetchone()
    if row:
        conn.execute(
            """
            UPDATE client_sessions
            SET current_ssid = ?,
                client_ip = ?,
                last_seen_ms = ?,
                is_active = ?,
                updated_at = ?
            WHERE user_id = ? AND client_type = ? AND client_id = ?
            """,
            (
                current_ssid,
                client_ip,
                now_ms,
                1 if is_active else 0,
                now_ms,
                user_id,
                client_type,
                client_id,
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO client_sessions (
                user_id, client_type, client_id, current_ssid, client_ip, last_seen_ms, is_active, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, client_type, client_id, current_ssid, client_ip, now_ms, 1 if is_active else 0, now_ms),
        )
    conn.commit()
    fresh = conn.execute(
        """
        SELECT * FROM client_sessions
        WHERE user_id = ? AND client_type = ? AND client_id = ?
        """,
        (user_id, client_type, client_id),
    ).fetchone()
    return dict(fresh) if fresh else {}


def _list_active_client_sessions(conn: Connection, user_id: int) -> List[Dict]:
    cutoff = int(time.time() * 1000) - CLIENT_SESSION_STALE_MS
    rows = conn.execute(
        """
        SELECT * FROM client_sessions
        WHERE user_id = ? AND is_active = 1 AND last_seen_ms >= ?
        ORDER BY
            CASE client_type WHEN 'desktop' THEN 0 ELSE 1 END ASC,
            last_seen_ms DESC
        """,
        (user_id, cutoff),
    ).fetchall()
    return [dict(row) for row in rows]


def _apply_device_network_state(
    conn: Connection,
    user_id: int,
    device_id: str,
    desired_ssid: Optional[str],
    network_mismatch: bool,
    missing_profile: bool,
    last_switch_reason: Optional[str],
) -> None:
    conn.execute(
        """
        UPDATE devices
        SET desired_ssid = ?,
            network_mismatch = ?,
            missing_profile = ?,
            last_switch_reason = ?,
            updated_at = ?
        WHERE user_id = ? AND device_id = ?
        """,
        (
            desired_ssid,
            1 if network_mismatch else 0,
            1 if missing_profile else 0,
            last_switch_reason,
            int(time.time() * 1000),
            user_id,
            device_id,
        ),
    )
    conn.commit()


def _compute_device_network_strategy(conn: Connection, user_id: int, device: Dict) -> Dict[str, Any]:
    device_id = str(device.get("device_id") or "").strip()
    current_ssid = str(device.get("ssid") or "").strip()
    sessions = _list_active_client_sessions(conn, user_id)
    preferred = next(
        (row for row in sessions if str(row.get("current_ssid") or "").strip()),
        None,
    )
    desired_ssid = str((preferred or {}).get("current_ssid") or "").strip() or None
    profiles = _list_wifi_profiles(conn, user_id, device_id)
    known_ssids = {str(item.get("ssid") or "").strip() for item in profiles if item.get("ssid")}
    network_mismatch = bool(desired_ssid and current_ssid and desired_ssid != current_ssid)
    missing_profile = bool(desired_ssid and desired_ssid not in known_ssids)
    last_switch_reason = None
    if desired_ssid:
        source = str((preferred or {}).get("client_type") or "mobile")
        if missing_profile:
            last_switch_reason = f"{source}_priority_missing_profile"
        elif network_mismatch:
            last_switch_reason = f"{source}_priority_network_sync"
        else:
            last_switch_reason = f"{source}_priority_aligned"
    return {
        "desired_ssid": desired_ssid,
        "network_mismatch": network_mismatch,
        "missing_profile": missing_profile,
        "last_switch_reason": last_switch_reason,
        "profiles": profiles,
    }


def _upsert_device(
    conn: Connection,
    user_id: int,
    device_id: str,
    device_ip: Optional[str] = None,
    ssid: Optional[str] = None,
    device_mac: Optional[str] = None,
) -> Dict:
    now_ms = int(time.time() * 1000)
    owner = _get_device_owner(conn, device_id)
    if owner and int(owner.get("user_id") or 0) != int(user_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Device already bound to another account")
    existing = _get_device(conn, user_id, device_id)
    if existing:
        conn.execute(
            """
            UPDATE devices
            SET device_ip = COALESCE(?, device_ip),
                device_mac = COALESCE(?, device_mac),
                ssid = COALESCE(?, ssid),
                updated_at = ?
            WHERE user_id = ? AND device_id = ?
            """,
            (device_ip, device_mac, ssid, now_ms, user_id, device_id),
        )
        conn.commit()
        return _get_device(conn, user_id, device_id)
    conn.execute(
        """
        INSERT INTO devices (user_id, device_id, device_ip, device_mac, ssid, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, device_id, device_ip, device_mac, ssid, now_ms),
    )
    conn.commit()
    return _get_device(conn, user_id, device_id)


def _update_device_status(
    conn: Connection,
    user_id: int,
    device_id: str,
    last_seen_ms: Optional[int],
    status: Optional[dict],
) -> None:
    status_json = json.dumps(status, ensure_ascii=False) if status else None
    now_ms = int(time.time() * 1000)
    conn.execute(
        """
        UPDATE devices
        SET last_seen_ms = COALESCE(?, last_seen_ms),
            status_json = COALESCE(?, status_json),
            updated_at = ?
        WHERE user_id = ? AND device_id = ?
        """,
        (last_seen_ms, status_json, now_ms, user_id, device_id),
    )
    conn.commit()


def _update_devices_by_device_id(
    conn: Connection,
    device_id: str,
    device_ip: Optional[str],
    device_mac: Optional[str],
    ssid: Optional[str],
    last_seen_ms: Optional[int],
    status: Optional[dict],
) -> int:
    status_json = json.dumps(status, ensure_ascii=False) if status else None
    now_ms = int(time.time() * 1000)
    cur = conn.execute(
        """
        UPDATE devices
        SET device_ip = COALESCE(?, device_ip),
            device_mac = COALESCE(?, device_mac),
            ssid = COALESCE(?, ssid),
            last_seen_ms = COALESCE(?, last_seen_ms),
            status_json = COALESCE(?, status_json),
            updated_at = ?
        WHERE device_id = ?
        """,
        (device_ip, device_mac, ssid, last_seen_ms, status_json, now_ms, device_id),
    )
    conn.commit()
    return int(cur.rowcount or 0)


def _fetch_device_status(device_ip: str, timeout_sec: float = 2.0) -> Dict:
    url = f"http://{device_ip}/status"
    response = httpx.get(url, timeout=timeout_sec)
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict):
        return data
    raise ValueError("Invalid status payload")


def _emotion_type_from_tags(tags: List[str], s_value: float) -> str:
    tags_lower = [str(tag).lower() for tag in tags]
    if any(tag in tags_lower for tag in ("anger", "angry")):
        return "ANGRY"
    if any(tag in tags_lower for tag in ("fatigue", "tired")):
        return "TIRED"
    if any(tag in tags_lower for tag in ("lonely", "sad")):
        return "SAD"
    if s_value >= 0.7:
        return "ANXIOUS"
    return "CALM"


def _event_to_emotion(event: EngineEventRequest) -> Optional[EmotionEventRequest]:
    # Runtime transport events should be broadcast only and not persisted
    # into emotion history.
    if event.type in {
        "FaceTrackUpdate",
        "FaceTrackState",
        "MediaState",
        "RiskUpdate",
        "TriggerCandidate",
        "WakeState",
        "WakeWordDetected",
        "WakeAudioState",
        "WakeDiag",
        "VoiceChatUser",
        "VoiceChatBot",
        "ChatMessage",
    }:
        return None

    payload = event.payload or {}
    reason = {}
    tags: List[str] = []
    if isinstance(payload, dict):
        reason = payload.get("reason") or {}
        if not reason and isinstance(payload.get("care_plan"), dict):
            reason = payload.get("care_plan", {}).get("reason", {}) or {}
        if isinstance(reason, dict):
            tags = reason.get("tags", []) if isinstance(reason.get("tags"), list) else []

    try:
        v = float(reason.get("V", 0.0))
        a = float(reason.get("A", 0.0))
        t = float(reason.get("T", 0.0)) if reason.get("T") is not None else 0.0
        s = float(reason.get("S", max(v, a, t)))
    except Exception:
        v = a = t = 0.0
        s = 0.0

    description = ""
    if isinstance(payload, dict):
        care_plan = payload.get("care_plan")
        if isinstance(care_plan, dict):
            description = str(care_plan.get("text", "")).strip()
        if not description:
            description = str(payload.get("summary", "") or payload.get("transcript", "")).strip()
    if not description:
        description = f"event:{event.type}"

    return EmotionEventRequest(
        timestamp_ms=event.timestamp_ms,
        type=_emotion_type_from_tags(tags, s),
        description=description,
        V=v,
        A=a,
        T=t,
        S=s,
        intensity=int(min(100, max(0, s * 100))),
        source="engine",
    )


def _insert_refresh_token(conn: Connection, user_id: int, refresh_token: str, expires_at: int) -> None:
    token_hash = auth.hash_token(refresh_token)
    conn.execute(
        """
        INSERT INTO refresh_tokens (user_id, token_hash, expires_at, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, token_hash, expires_at, int(time.time())),
    )
    conn.commit()


def _revoke_refresh_token(conn: Connection, refresh_token: str) -> None:
    token_hash = auth.hash_token(refresh_token)
    conn.execute(
        "UPDATE refresh_tokens SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
        (int(time.time()), token_hash),
    )
    conn.commit()


def _refresh_token_valid(conn: Connection, refresh_token: str) -> bool:
    token_hash = auth.hash_token(refresh_token)
    cur = conn.execute(
        """
        SELECT id FROM refresh_tokens
        WHERE token_hash = ? AND revoked_at IS NULL AND expires_at > ?
        """,
        (token_hash, int(time.time())),
    )
    return cur.fetchone() is not None


def _parse_access_token(
    credentials: HTTPAuthorizationCredentials,
    conn: Connection,
) -> Dict:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    payload = auth.decode_token(credentials.credentials)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user_id = int(payload.get("sub", 0))
    user = _get_user_by_id(conn, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


@app.post("/auth/register", response_model=UserResponse, status_code=201)
def register(payload: RegisterRequest, conn: Connection = Depends(get_db)) -> UserResponse:
    existing = _get_user_by_username(conn, payload.username)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
    password_hash = auth.hash_password(payload.password)
    now = int(time.time())
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
        (payload.username, password_hash, now),
    )
    conn.commit()
    user_id = cur.lastrowid
    return UserResponse(id=user_id, username=payload.username, created_at=now)


@app.post("/api/auth/register", response_model=UserResponse, status_code=201)
def register_api(payload: RegisterRequest, conn: Connection = Depends(get_db)) -> UserResponse:
    return register(payload, conn)


@app.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, conn: Connection = Depends(get_db)) -> TokenResponse:
    username = str(payload.username or "").strip()
    if not username:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Username is required")
    user = _get_user_by_username(conn, username)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not auth.verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    access = auth.create_access_token(user["id"], user["username"])
    refresh = auth.create_refresh_token(user["id"], user["username"])
    expires_at = int(time.time()) + refresh["expires_in"]
    _insert_refresh_token(conn, user["id"], refresh["token"], expires_at)
    return TokenResponse(
        access_token=access["token"],
        refresh_token=refresh["token"],
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_SEC,
    )


@app.post("/api/auth/login", response_model=LoginResponse)
def login_api(payload: LoginEmailRequest, conn: Connection = Depends(get_db)) -> LoginResponse:
    email = str(payload.email or "").strip()
    if not email:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Email is required")
    user = _get_user_by_username(conn, email)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not auth.verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    access = auth.create_access_token(user["id"], user["username"])
    refresh = auth.create_refresh_token(user["id"], user["username"])
    expires_at = int(time.time()) + refresh["expires_in"]
    _insert_refresh_token(conn, user["id"], refresh["token"], expires_at)

    return LoginResponse(
        token=access["token"],
        refresh_token=refresh["token"],
        user_id=int(user["id"]),
        is_configured=bool(user.get("is_configured", 0)),
    )


@app.get("/api/auth/me", response_model=UserResponse)
def me_api(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> UserResponse:
    user = _parse_access_token(credentials, conn)
    return UserResponse(id=user["id"], username=user["username"], created_at=user["created_at"])


@app.get("/api/user/profile", response_model=ProfileResponse)
def user_profile(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> ProfileResponse:
    user = _parse_access_token(credentials, conn)
    profile = _profile_from_user(user)
    return ProfileResponse(**profile)


@app.post("/api/user/profile", response_model=ProfileResponse)
async def update_user_profile(
    payload: ProfileUpdateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> ProfileResponse:
    user = _parse_access_token(credentials, conn)
    current = _profile_from_user(user)
    display_name = current["display_name"]
    avatar_url = current["avatar_url"]
    bio = current.get("bio")
    location = current.get("location")

    if payload.display_name is not None:
        candidate = str(payload.display_name).strip()
        display_name = candidate or current["username"] or "鍏遍福鏃呬汉"

    if payload.avatar_url is not None:
        candidate = str(payload.avatar_url).strip()
        avatar_url = candidate or None

    if payload.bio is not None:
        candidate = str(payload.bio).strip()
        bio = candidate or None

    if payload.location is not None:
        candidate = str(payload.location).strip()
        location = candidate or None

    updated_at = int(time.time())
    conn.execute(
        "UPDATE users SET display_name = ?, avatar_url = ?, bio = ?, location = ?, updated_at = ? WHERE id = ?",
        (display_name, avatar_url, bio, location, updated_at, int(user["id"])),
    )
    conn.commit()
    response = ProfileResponse(
        id=int(user["id"]),
        username=current["username"],
        display_name=display_name,
        avatar_url=avatar_url,
        bio=bio,
        location=location,
        created_at=current.get("created_at"),
        updated_at=updated_at,
    )
    await event_manager.broadcast(
        {
            "type": "UserProfileUpdated",
            "timestamp_ms": int(time.time() * 1000),
            "payload": response.model_dump(),
        }
    )
    return response


@app.post("/auth/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, conn: Connection = Depends(get_db)) -> TokenResponse:
    data = auth.decode_token(payload.refresh_token)
    if not data or data.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    if not _refresh_token_valid(conn, payload.refresh_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked")

    user_id = int(data.get("sub", 0))
    user = _get_user_by_id(conn, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    _revoke_refresh_token(conn, payload.refresh_token)
    access = auth.create_access_token(user["id"], user["username"])
    refresh = auth.create_refresh_token(user["id"], user["username"])
    expires_at = int(time.time()) + refresh["expires_in"]
    _insert_refresh_token(conn, user["id"], refresh["token"], expires_at)

    return TokenResponse(
        access_token=access["token"],
        refresh_token=refresh["token"],
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_SEC,
    )


@app.post("/api/auth/refresh", response_model=TokenResponse)
def refresh_api(payload: RefreshRequest, conn: Connection = Depends(get_db)) -> TokenResponse:
    return refresh(payload, conn)


@app.post("/auth/logout")
def logout(payload: LogoutRequest, conn: Connection = Depends(get_db)) -> Dict[str, str]:
    _revoke_refresh_token(conn, payload.refresh_token)
    return {"status": "ok"}


@app.post("/api/auth/logout")
def logout_api(payload: LogoutRequest, conn: Connection = Depends(get_db)) -> Dict[str, str]:
    return logout(payload, conn)


@app.get("/auth/me", response_model=UserResponse)
def me(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> UserResponse:
    user = _parse_access_token(credentials, conn)
    return UserResponse(id=user["id"], username=user["username"], created_at=user["created_at"])


@app.get("/api/emotion/realtime", response_model=RealtimeScoresResponse)
def emotion_realtime() -> RealtimeScoresResponse:
    scores = getattr(app.state, "scores", {"V": 0.0, "A": 0.0, "T": 0.0, "S": 0.0})
    return RealtimeScoresResponse(**scores)


@app.get("/api/emotion/realtime/detail", response_model=RealtimeRiskDetailResponse)
def emotion_realtime_detail() -> RealtimeRiskDetailResponse:
    scores = getattr(app.state, "scores", {"V": 0.0, "A": 0.0, "T": 0.0, "S": 0.0})
    detail = getattr(app.state, "risk_detail", {})
    if not isinstance(detail, dict):
        detail = {}
    v_sub = detail.get("V_sub")
    if not isinstance(v_sub, dict):
        v_sub = {}
    a_sub = detail.get("A_sub")
    if not isinstance(a_sub, dict):
        a_sub = {}
    t_sub = detail.get("T_sub")
    if not isinstance(t_sub, dict):
        t_sub = {}

    # Keep a stable contract for UI/CLI even when upstream engine is older or not ready.
    v_sub.setdefault("face_ok", 0.0)
    v_sub.setdefault("expression_class_id", -1.0)
    v_sub.setdefault("expression_confidence", 0.0)
    v_sub.setdefault("expression_risk", 0.0)
    v_sub.setdefault("expression_valid", 0.0)
    v_sub.setdefault("expr_reason", "unavailable")
    v_sub.setdefault("expr_source", "none")
    v_sub.setdefault("mp_expr_reason", "unavailable")
    v_sub.setdefault("frame_decode_ok", 0.0)
    v_sub.setdefault("fer_invoked", 0.0)
    v_sub.setdefault("expr_model_ready", 0.0)
    detail = {"V_sub": v_sub, "A_sub": a_sub, "T_sub": t_sub}
    ts_ms = int(getattr(app.state, "risk_timestamp_ms", int(time.time() * 1000)))
    mode = getattr(app.state, "risk_mode", None)
    return RealtimeRiskDetailResponse(
        V=float(scores.get("V", 0.0)),
        A=float(scores.get("A", 0.0)),
        T=float(scores.get("T", 0.0)),
        S=float(scores.get("S", 0.0)),
        timestamp_ms=ts_ms,
        mode=mode,
        detail=detail,
    )


@app.post("/api/emotion/realtime", response_model=RealtimeScoresResponse)
def emotion_realtime_update(payload: RealtimeScoresResponse) -> RealtimeScoresResponse:
    app.state.scores = payload.model_dump()
    app.state.risk_timestamp_ms = int(time.time() * 1000)
    return payload


@app.get("/api/emotion/history", response_model=List[EmotionEventResponse])
def emotion_history(
    limit: int = 50,
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> List[EmotionEventResponse]:
    user = _parse_access_token(credentials, conn)
    rows = _list_emotion_events(conn, int(user["id"]), limit, start_ms, end_ms)
    return [EmotionEventResponse(**_row_to_event(row)) for row in rows]


@app.post("/api/emotion/history", response_model=EmotionEventResponse)
def emotion_history_add(
    payload: EmotionEventRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> EmotionEventResponse:
    user = _parse_access_token(credentials, conn)
    event_id = _insert_emotion_event(conn, int(user["id"]), payload)
    data = _row_to_event(
        {
            "id": event_id,
            "timestamp_ms": payload.timestamp_ms,
            "type": payload.type,
            "description": payload.description,
            "v": payload.V,
            "a": payload.A,
            "t": payload.T,
            "s": payload.S,
            "intensity": payload.intensity,
            "source": payload.source,
        }
    )
    return EmotionEventResponse(**data)


@app.post("/api/device/provision", response_model=ProvisionResponse)
def device_provision(
    payload: ProvisionRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> ProvisionResponse:
    user = _parse_access_token(credentials, conn)
    _set_user_configured(conn, int(user["id"]), True)
    _upsert_device(
        conn,
        int(user["id"]),
        payload.device_id,
        device_ip=payload.device_ip,
        ssid=payload.ssid,
        device_mac=(payload.device_mac or "").strip() or None,
    )
    _upsert_wifi_profile(
        conn,
        int(user["id"]),
        payload.device_id,
        payload.ssid,
        payload.password,
        payload.transport or "mobile",
    )
    return ProvisionResponse(ok=True, is_configured=True)


@app.post("/api/device/provision/execute", response_model=ProvisionExecuteResponse)
def device_provision_execute(
    payload: ProvisionExecuteRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> ProvisionExecuteResponse:
    user = _parse_access_token(credentials, conn)
    result = run_provisioning(
        transport=payload.transport,
        ssid=payload.ssid,
        password=payload.password,
        service_name=payload.service_name,
        pop=payload.pop,
        qr_payload=payload.qr_payload,
        timeout_sec=payload.timeout_sec,
    )
    is_configured = False
    if result.ok:
        is_configured = True
        _set_user_configured(conn, int(user["id"]), True)
        _upsert_device(
            conn,
            int(user["id"]),
            payload.device_id,
            device_ip=payload.device_ip,
            ssid=payload.ssid,
        )
        _upsert_wifi_profile(
            conn,
            int(user["id"]),
            payload.device_id,
            payload.ssid,
            payload.password,
            payload.transport or "desktop",
        )
    return ProvisionExecuteResponse(
        ok=result.ok,
        is_configured=is_configured,
        device_ip=payload.device_ip,
        message=result.message,
        logs=None if result.ok else result.logs,
    )


@app.post("/api/client/session/heartbeat", response_model=ClientSessionHeartbeatResponse)
def client_session_heartbeat(
    payload: ClientSessionHeartbeatRequest,
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> ClientSessionHeartbeatResponse:
    user = _parse_access_token(credentials, conn)
    client_ip = (payload.client_ip or "").strip()
    if not client_ip and request.client:
        client_ip = str(request.client.host or "").strip()
    _upsert_client_session(
        conn,
        int(user["id"]),
        str(payload.client_type or "").strip() or "mobile",
        str(payload.client_id or "").strip() or "unknown",
        (payload.current_ssid or "").strip() or None,
        client_ip or None,
        bool(payload.is_active),
    )
    selected = {}
    if payload.device_id:
        selected = _get_device(conn, int(user["id"]), payload.device_id)
    else:
        devices = _list_devices(conn, int(user["id"]))
        if devices:
            selected = devices[0]
    strategy = _compute_device_network_strategy(conn, int(user["id"]), selected or {"device_id": payload.device_id or ""})
    if selected:
        _apply_device_network_state(
            conn,
            int(user["id"]),
            str(selected.get("device_id") or ""),
            strategy["desired_ssid"],
            bool(strategy["network_mismatch"]),
            bool(strategy["missing_profile"]),
            strategy["last_switch_reason"],
        )
    return ClientSessionHeartbeatResponse(
        ok=True,
        desired_ssid=strategy["desired_ssid"],
        network_mismatch=bool(strategy["network_mismatch"]),
        missing_profile=bool(strategy["missing_profile"]),
        last_switch_reason=strategy["last_switch_reason"],
    )


@app.post("/api/device/heartbeat", response_model=DeviceHeartbeatResponse)
def device_heartbeat(
    payload: DeviceHeartbeatRequest,
    request: Request,
    conn: Connection = Depends(get_db),
) -> DeviceHeartbeatResponse:
    device_ip = (payload.device_ip or "").strip()
    if not device_ip and request.client:
        device_ip = str(request.client.host or "").strip()

    now_ms = int(time.time() * 1000)
    last_seen_ms = payload.last_seen_ms
    if not last_seen_ms or last_seen_ms < 1_000_000_000_000:
        last_seen_ms = now_ms
    status_payload = dict(payload.status or {})
    if device_ip and not status_payload.get("ip"):
        status_payload["ip"] = device_ip
    if payload.ssid and not status_payload.get("ssid"):
        status_payload["ssid"] = payload.ssid
    if payload.rssi is not None and status_payload.get("rssi") is None:
        status_payload["rssi"] = int(payload.rssi)

    updated = _update_devices_by_device_id(
        conn,
        payload.device_id,
        device_ip or None,
        (payload.device_mac or "").strip() or None,
        (payload.ssid or "").strip() or None,
        last_seen_ms,
        status_payload or None,
    )
    owner = _get_device_owner(conn, payload.device_id)
    strategy = {
        "desired_ssid": None,
        "network_mismatch": False,
        "missing_profile": False,
        "last_switch_reason": None,
        "profiles": [],
    }
    if owner:
        if payload.ssid:
            _mark_wifi_profile_success(conn, int(owner["user_id"]), payload.device_id, payload.ssid)
            owner = _get_device(conn, int(owner["user_id"]), payload.device_id)
        strategy = _compute_device_network_strategy(conn, int(owner["user_id"]), owner)
        _apply_device_network_state(
            conn,
            int(owner["user_id"]),
            payload.device_id,
            strategy["desired_ssid"],
            bool(strategy["network_mismatch"]),
            bool(strategy["missing_profile"]),
            strategy["last_switch_reason"],
        )
    profile_payload = [
        {
            "ssid": str(item.get("ssid") or "").strip(),
            "password": _decrypt_wifi_password(str(item.get("encrypted_password") or "")),
            "last_success_at": item.get("last_success_at"),
        }
        for item in strategy.get("profiles", [])
        if str(item.get("ssid") or "").strip()
    ]
    return DeviceHeartbeatResponse(
        ok=True,
        updated=updated,
        desired_ssid=strategy["desired_ssid"],
        network_mismatch=bool(strategy["network_mismatch"]),
        missing_profile=bool(strategy["missing_profile"]),
        last_switch_reason=strategy["last_switch_reason"],
        profiles=profile_payload,
    )


@app.post("/api/engine/event")
async def engine_event(
    payload: EngineEventRequest,
    conn: Connection = Depends(get_db),
) -> Dict[str, bool]:
    payload_data = payload.payload if isinstance(payload.payload, dict) else {}
    if payload.type == "RiskUpdate":
        scores = {
            "V": float(payload_data.get("V", 0.0)),
            "A": float(payload_data.get("A", 0.0)),
            "T": float(payload_data.get("T", 0.0)) if payload_data.get("T") is not None else 0.0,
            "S": float(payload_data.get("S", 0.0)),
        }
        app.state.scores = scores
        app.state.risk_detail = payload_data.get("detail") if isinstance(payload_data.get("detail"), dict) else {}
        app.state.risk_mode = payload_data.get("mode")
        app.state.risk_timestamp_ms = int(payload.timestamp_ms)

    if payload.type in {"TriggerFired", "CarePlanReady", "DailySummaryReady"}:
        event_payload = _event_to_emotion(payload)
        if event_payload:
            user_id = _get_default_user_id(conn)
            if user_id is not None:
                _insert_emotion_event(conn, user_id, event_payload)

    if payload.type in {"VoiceChatUser", "VoiceChatBot"}:
        text = str(payload_data.get("text", "")).strip()
        sender = "user" if payload.type == "VoiceChatUser" else "bot"
        rewritten = False
        if sender == "bot":
            text, rewritten = _sanitize_outbound_bot_text(text)
            payload_data["text"] = text
            payload.payload = payload_data
        user_id = _get_default_user_id(conn)
        if user_id is not None and text:
            req = ChatMessageRequest(
                sender=sender,
                text=text,
                content_type="text",
                attachments=[],
                timestamp_ms=int(payload.timestamp_ms),
            )
            msg_id = _insert_chat_message(conn, user_id, req)
            await event_manager.broadcast(
                {
                    "type": "ChatMessage",
                    "timestamp_ms": int(payload.timestamp_ms),
                    "payload": {
                        "id": msg_id,
                        "sender": sender,
                        "text": text,
                        "content_type": "text",
                        "attachments": [],
                        "timestamp_ms": int(payload.timestamp_ms),
                    },
                }
            )
        if rewritten:
            await event_manager.broadcast(
                {
                    "type": "WakeAudioState",
                    "timestamp_ms": int(payload.timestamp_ms),
                    "payload": {
                        "ok": True,
                        "state": "thinking",
                        "reason": "function_call_blocked_and_rewritten",
                    },
                }
            )

    await event_manager.broadcast(payload.model_dump())
    return {"ok": True}


@app.post("/api/engine/signal")
def engine_signal(
    payload: EngineSignalRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> Dict[str, bool]:
    _ = _parse_access_token(credentials, conn)
    signal = {
        "type": payload.type,
        "timestamp_ms": int(time.time() * 1000),
        "payload": payload.payload or {},
    }
    _enqueue_signal(signal)
    return {"ok": True}


@app.post("/api/engine/signal/local")
def engine_signal_local(
    payload: EngineSignalRequest,
    request: Request,
) -> Dict[str, bool]:
    if not _is_local_request(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Local access only")
    signal = {
        "type": payload.type,
        "timestamp_ms": int(time.time() * 1000),
        "payload": payload.payload or {},
    }
    _enqueue_signal(signal)
    return {"ok": True}


@app.post("/api/engine/signal/pull", response_model=EngineSignalPullResponse)
def engine_signal_pull(
    request: Request,
    payload: Optional[EngineSignalPullRequest] = None,
) -> EngineSignalPullResponse:
    if not _is_local_request(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Local access only")
    limit = payload.limit if payload else 10
    limit = max(1, min(50, int(limit)))
    signals = _drain_signals(limit)
    return EngineSignalPullResponse(signals=signals)


@app.get("/api/device/list", response_model=List[DeviceInfoResponse])
def device_list(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> List[DeviceInfoResponse]:
    user = _parse_access_token(credentials, conn)
    devices = _list_devices(conn, int(user["id"]))
    return [
        DeviceInfoResponse(
            device_id=row.get("device_id", ""),
            device_ip=row.get("device_ip"),
            device_mac=row.get("device_mac"),
            ssid=row.get("ssid"),
            last_seen_ms=row.get("last_seen_ms"),
        )
        for row in devices
    ]


@app.get("/api/device/status", response_model=DeviceStatusResponse)
def device_status(
    device_id: Optional[str] = None,
    device_ip: Optional[str] = None,
    probe: bool = False,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> DeviceStatusResponse:
    user = _parse_access_token(credentials, conn)
    selected = {}
    if device_id:
        selected = _get_device(conn, int(user["id"]), device_id)
    else:
        devices = _list_devices(conn, int(user["id"]))
        if devices:
            selected = devices[0]
    if not selected and not device_ip:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    resolved_id = device_id or selected.get("device_id", "unknown")
    resolved_ip = device_ip or selected.get("device_ip")
    resolved_mac = selected.get("device_mac")
    cached_status = None
    if selected and selected.get("status_json"):
        try:
            cached_status = json.loads(selected.get("status_json") or "{}")
        except Exception:
            cached_status = None
    last_seen_ms = selected.get("last_seen_ms")
    heartbeat_fresh = False
    if last_seen_ms is not None:
        try:
            heartbeat_fresh = int(time.time() * 1000) - int(last_seen_ms) <= HEARTBEAT_STALE_MS
        except Exception:
            heartbeat_fresh = False
    strategy = _compute_device_network_strategy(conn, int(user["id"]), selected or {"device_id": resolved_id, "ssid": None})
    if selected:
        _apply_device_network_state(
            conn,
            int(user["id"]),
            resolved_id,
            strategy["desired_ssid"],
            bool(strategy["network_mismatch"]),
            bool(strategy["missing_profile"]),
            strategy["last_switch_reason"],
        )
    if not resolved_ip:
        return DeviceStatusResponse(
            device_id=resolved_id,
            device_ip=None,
            device_mac=resolved_mac,
            online=heartbeat_fresh,
            last_seen_ms=last_seen_ms,
            ssid=selected.get("ssid") if selected else None,
            desired_ssid=strategy["desired_ssid"],
            network_mismatch=bool(strategy["network_mismatch"]),
            missing_profile=bool(strategy["missing_profile"]),
            last_switch_reason=strategy["last_switch_reason"],
            status=cached_status if heartbeat_fresh else None,
            error=None if heartbeat_fresh else "Device IP missing",
        )

    if not probe:
        return DeviceStatusResponse(
            device_id=resolved_id,
            device_ip=resolved_ip,
            device_mac=resolved_mac,
            online=heartbeat_fresh,
            last_seen_ms=last_seen_ms,
            ssid=selected.get("ssid") if selected else None,
            desired_ssid=strategy["desired_ssid"],
            network_mismatch=bool(strategy["network_mismatch"]),
            missing_profile=bool(strategy["missing_profile"]),
            last_switch_reason=strategy["last_switch_reason"],
            status=cached_status if heartbeat_fresh else None,
            error=None if heartbeat_fresh else "Device heartbeat stale",
        )

    try:
        status_payload = _fetch_device_status(resolved_ip)
        last_seen_ms = int(time.time() * 1000)
        if selected:
            _update_device_status(conn, int(user["id"]), resolved_id, last_seen_ms, status_payload)
        return DeviceStatusResponse(
            device_id=resolved_id,
            device_ip=resolved_ip,
            device_mac=resolved_mac,
            online=True,
            last_seen_ms=last_seen_ms,
            ssid=selected.get("ssid") if selected else None,
            desired_ssid=strategy["desired_ssid"],
            network_mismatch=bool(strategy["network_mismatch"]),
            missing_profile=bool(strategy["missing_profile"]),
            last_switch_reason=strategy["last_switch_reason"],
            status=status_payload,
            error=None,
        )
    except Exception as exc:
        if heartbeat_fresh:
            return DeviceStatusResponse(
                device_id=resolved_id,
                device_ip=resolved_ip,
                device_mac=resolved_mac,
                online=True,
                last_seen_ms=last_seen_ms,
                ssid=selected.get("ssid") if selected else None,
                desired_ssid=strategy["desired_ssid"],
                network_mismatch=bool(strategy["network_mismatch"]),
                missing_profile=bool(strategy["missing_profile"]),
                last_switch_reason=strategy["last_switch_reason"],
                status=cached_status,
                error=None,
            )
        return DeviceStatusResponse(
            device_id=resolved_id,
            device_ip=resolved_ip,
            device_mac=resolved_mac,
            online=False,
            last_seen_ms=last_seen_ms,
            ssid=selected.get("ssid") if selected else None,
            desired_ssid=strategy["desired_ssid"],
            network_mismatch=bool(strategy["network_mismatch"]),
            missing_profile=bool(strategy["missing_profile"]),
            last_switch_reason=strategy["last_switch_reason"],
            status=None,
            error=str(exc),
        )


@app.get("/api/chat/history", response_model=List[ChatMessageResponse])
def chat_history(
    limit: int = 100,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> List[ChatMessageResponse]:
    user = _parse_access_token(credentials, conn)
    rows = _list_chat_messages(conn, int(user["id"]), limit)
    return [
        ChatMessageResponse(
            id=row["id"],
            sender=row["sender"],
            text=row["text"],
            content_type=str(row.get("content_type") or "text"),
            attachments=row.get("attachments") if isinstance(row.get("attachments"), list) else [],
            timestamp_ms=row["timestamp_ms"],
        )
        for row in rows
    ]


@app.post("/api/chat/history", response_model=ChatMessageResponse)
async def chat_history_add(
    payload: ChatMessageRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> ChatMessageResponse:
    user = _parse_access_token(credentials, conn)
    msg_id = _insert_chat_message(conn, int(user["id"]), payload)
    response = ChatMessageResponse(
        id=msg_id,
        sender=payload.sender,
        text=payload.text,
        content_type=str(payload.content_type or "text"),
        attachments=payload.attachments or [],
        timestamp_ms=payload.timestamp_ms,
    )
    await event_manager.broadcast(
        {
            "type": "ChatMessage",
            "timestamp_ms": payload.timestamp_ms,
            "payload": response.model_dump(),
        }
    )
    return response


def _safe_upload_name(name: str) -> str:
    raw = Path(str(name or "upload.bin")).name
    safe = "".join(ch for ch in raw if ch.isalnum() or ch in {".", "-", "_"})
    safe = safe.strip("._")
    return safe or "upload.bin"


@app.post("/api/chat/upload")
async def chat_upload(
    file: UploadFile = File(...),
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> Dict[str, object]:
    user = _parse_access_token(credentials, conn)
    content_type = str(file.content_type or "").lower()
    if not (content_type.startswith("image/") or content_type.startswith("video/")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only image/video uploads are supported")

    kind = "image" if content_type.startswith("image/") else "video"
    ts = int(time.time() * 1000)
    date_key = time.strftime("%Y%m%d", time.localtime(ts / 1000.0))
    target_dir = CHAT_UPLOAD_ROOT / str(int(user["id"])) / date_key
    target_dir.mkdir(parents=True, exist_ok=True)

    original_name = _safe_upload_name(file.filename or "upload.bin")
    stem = Path(original_name).stem or "upload"
    suffix = Path(original_name).suffix
    target_name = f"{stem}-{ts}{suffix}"
    target_path = target_dir / target_name

    with target_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    size = int(target_path.stat().st_size) if target_path.exists() else 0
    rel = target_path.relative_to(UPLOAD_ROOT).as_posix()
    return {
        "ok": True,
        "attachment": {
            "kind": kind,
            "url": f"/uploads/{rel}",
            "mime": content_type,
            "name": original_name,
            "size": size,
        },
    }


def _require_bearer(credentials: Optional[HTTPAuthorizationCredentials]) -> None:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    if not auth.decode_token(credentials.credentials):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def _build_care_context(payload: CareRequest) -> Dict[str, object]:
    expr_labels = ["neutral", "happiness", "surprise", "sadness", "anger", "disgust", "fear", "contempt"]
    runtime_detail = app.state.risk_detail if isinstance(getattr(app.state, "risk_detail", None), dict) else {}
    runtime_v_sub = runtime_detail.get("V_sub") if isinstance(runtime_detail.get("V_sub"), dict) else {}
    runtime_expr_id = int(runtime_v_sub.get("expression_class_id", -1) or -1)
    runtime_expr_label = (
        expr_labels[runtime_expr_id]
        if runtime_expr_id >= 0 and runtime_expr_id < len(expr_labels)
        else str(runtime_v_sub.get("expression_label", "unknown") or "unknown")
    )
    runtime_expr_conf = float(runtime_v_sub.get("expression_confidence", 0.0) or 0.0)
    payload_expr_label = str(payload.expression_label or "unknown").strip() or "unknown"
    payload_expr_conf = float(payload.expression_confidence or 0.0)
    expr_label = payload_expr_label
    expr_conf = payload_expr_conf
    expr_source = "payload"
    if (expr_label == "unknown" and runtime_expr_label != "unknown") or (expr_conf <= 0.0 and runtime_expr_conf > 0.0):
        expr_label = runtime_expr_label or expr_label
        expr_conf = runtime_expr_conf if runtime_expr_conf > 0.0 else expr_conf
        expr_source = "runtime_risk_detail"

    history_items = []
    current_ts_ms = payload.current_ts_ms or int(time.time() * 1000)
    for item in payload.history or []:
        if isinstance(item, dict):
            history_items.append(
                {
                    "sender": str(item.get("sender", "user")),
                    "text": str(item.get("text", "")),
                    "timestamp_ms": int(item.get("timestamp_ms", current_ts_ms)),
                }
            )
        else:
            history_items.append(
                {
                    "sender": str(item.sender),
                    "text": str(item.text),
                    "timestamp_ms": int(item.timestamp_ms),
                }
            )

    history_items = [item for item in history_items if item.get("text")]
    history_items.sort(key=lambda item: item["timestamp_ms"])
    history_gap_ms = None
    if history_items:
        last_ts = int(history_items[-1]["timestamp_ms"])
        history_gap_ms = int(current_ts_ms) - last_ts

    history_stale_ms = 10 * 60 * 1000
    history_usable = history_gap_ms is None or history_gap_ms <= history_stale_ms
    if history_usable:
        model_history = history_items[-4:]
    else:
        model_history = []
    history_summary = ""
    if model_history:
        recent = model_history[-3:]
        history_summary = " | ".join([f"{item['sender']}: {item['text']}" for item in recent])
    memory_summary = str(payload.memory_summary or "").strip()
    if len(memory_summary) > 600:
        memory_summary = memory_summary[-600:]
    attachment_items: List[Dict[str, object]] = []
    for item in payload.attachments or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", "")).strip().lower()
        if kind not in {"image", "video"}:
            continue
        entry: Dict[str, object] = {
            "kind": kind,
            "url": str(item.get("url", "")).strip(),
            "mime": str(item.get("mime", "")).strip(),
            "name": str(item.get("name", "")).strip(),
            "size": int(item.get("size", 0) or 0),
        }
        image_data_url = str(item.get("image_data_url", "")).strip()
        if kind == "image" and image_data_url.startswith("data:image/"):
            entry["image_data_url"] = image_data_url
        attachment_items.append(entry)

    return {
        "input_type": "user_text",
        "scene": "office",
        "current_emotion": payload.current_emotion,
        "current_message": {
            "text": payload.context,
            "timestamp_ms": int(current_ts_ms),
        },
        "history": [
            {
                "sender": item["sender"],
                "text": item["text"],
                "timestamp_ms": int(item["timestamp_ms"]),
            }
            for item in model_history
        ],
        "history_summary": history_summary,
        "memory_summary": memory_summary,
        "attachments": attachment_items,
        "history_gap_ms": history_gap_ms,
        "history_usable": history_usable,
        "expression_modality": {
            "label": expr_label,
            "confidence": expr_conf,
            "source": expr_source,
            "note": "这是算法观测到的情绪信号，不是用户原话。",
        },
        "expression_label": expr_label,
        "expression_confidence": expr_conf,
        "constraints": (
            "优先回答当前问题；仅在表达难受或求助时给关怀建议；避免重复追问，不诊断，不说教；"
            "避免输出emoji、颜文字或表情包标签；"
            "不输出思考过程；新闻问题优先联网搜索；"
            "若发生联网搜索，先明确说“我帮你联网搜搜”；"
            "回复时要参考 expression_modality（算法信号，非用户原话）；"
            "不要向用户展示function_call/tool_call/json草稿。"
        ),
    }


def _inject_tooling_budget(
    context: Dict[str, object],
    conn: Connection,
    user_id: int,
) -> Dict[str, object]:
    date_key = _usage_date_key()
    usage = _get_tool_usage_daily(conn, user_id, date_key)
    web_limit = int(getattr(_llm_config, "web_search_daily_limit", 5) if _llm_config else 5)
    web_limit = max(0, web_limit)
    web_used = int(usage.get("web_search_count", 0))
    web_remaining = max(0, web_limit - web_used)

    emotion_cap = int(getattr(_llm_config, "emotion_linked_search_daily_cap", 1) if _llm_config else 1)
    emotion_cap = max(0, emotion_cap)
    emotion_used = int(usage.get("emotion_auto_search_count", 0))
    emotion_remaining = max(0, emotion_cap - emotion_used)

    tooling = context.get("tooling") if isinstance(context.get("tooling"), dict) else {}
    tooling = dict(tooling)
    tooling.update(
        {
            "user_id": int(user_id),
            "date_key": date_key,
            "web_search_daily_limit": web_limit,
            "web_search_budget_remaining": web_remaining,
            "web_search_used": web_used,
            "emotion_auto_search_daily_cap": emotion_cap,
            "emotion_auto_search_remaining": emotion_remaining,
            "emotion_auto_search_used": emotion_used,
        }
    )
    context["tooling"] = tooling
    return context


def _sse(event: str, payload: Dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.post("/api/llm/care", response_model=CareResponse)
def llm_care(
    payload: CareRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> CareResponse:
    user = _parse_access_token(credentials, conn)

    if not _llm:
        return CareResponse(text="我在这里陪着你。", followup_question="", style="warm")

    context = _build_care_context(payload)
    context = _inject_tooling_budget(context, conn, int(user["id"]))
    reply = _llm.generate_care_reply(context)
    llm_meta = dict(getattr(_llm, "last_meta", {}) or {})
    if bool(llm_meta.get("online_search_used")):
        online_reason = str(llm_meta.get("online_search_reason", "") or "")
        emotion_delta = 1 if online_reason == "emotion_linked_search_enabled" else 0
        _bump_tool_usage_daily(
            conn,
            int(user["id"]),
            _usage_date_key(),
            web_search_delta=1,
            emotion_auto_delta=emotion_delta,
        )

    if not reply:
        return CareResponse(text="我在这里陪着你。", followup_question="", style="warm")
    safe_text, rewritten = _sanitize_outbound_bot_text(str(reply.get("text", "")))
    if rewritten and _llm and isinstance(getattr(_llm, "last_meta", None), dict):
        _llm.last_meta["online_search_reason"] = "function_call_blocked_and_rewritten"
    return CareResponse(
        text=safe_text or "我在这里陪着你。",
        followup_question=str(reply.get("followup_question", "")),
        style=str(reply.get("style", "warm")),
    )


@app.post("/api/llm/care/stream")
async def llm_care_stream(
    payload: CareRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
):
    user = _parse_access_token(credentials, conn)
    context = _build_care_context(payload)
    context = _inject_tooling_budget(context, conn, int(user["id"]))
    stream_iter = None
    if _llm:
        stream_iter = _llm.stream_care_text(context)
        llm_meta = dict(getattr(_llm, "last_meta", {}) or {})
        if bool(llm_meta.get("online_search_used")):
            online_reason = str(llm_meta.get("online_search_reason", "") or "")
            emotion_delta = 1 if online_reason == "emotion_linked_search_enabled" else 0
            _bump_tool_usage_daily(
                conn,
                int(user["id"]),
                _usage_date_key(),
                web_search_delta=1,
                emotion_auto_delta=emotion_delta,
            )

    async def event_stream():
        try:
            yield _sse("start", {"ok": True})
            full_text = ""
            sent_text = ""
            last_emit_ms = int(time.time() * 1000)

            if not _llm:
                fallback = "我在这里陪着你。"
                for char in fallback:
                    sent_text += char
                    yield _sse("delta", {"text": char})
                yield _sse(
                    "done",
                    {
                        "text": sent_text,
                        "followup_question": "",
                        "style": "warm",
                    },
                )
                return

            for piece in stream_iter or ():
                if not piece:
                    now_ms = int(time.time() * 1000)
                    if now_ms - last_emit_ms > 1800:
                        yield _sse("ping", {"ts_ms": now_ms})
                        await asyncio.sleep(0)
                    continue
                full_text += piece
                normalized = full_text.replace("\\n", " ")
                clipped = normalized[:100]
                if len(clipped) <= len(sent_text):
                    continue
                delta = clipped[len(sent_text) :]
                sent_text = clipped
                yield _sse("delta", {"text": delta})
                last_emit_ms = int(time.time() * 1000)
                await asyncio.sleep(0)
                if len(sent_text) >= 100:
                    break

            final_text = sent_text.strip()
            if not final_text:
                fallback_reply = _llm.generate_care_reply(context) if _llm else None
                final_text = str((fallback_reply or {}).get("text", "")).strip()[:100]
            if not final_text:
                final_text = "我在这里陪着你。"
            final_text, _rewritten = _sanitize_outbound_bot_text(final_text)
            if not final_text:
                final_text = "我在这里陪着你。"

            yield _sse(
                "done",
                {
                    "text": final_text,
                    "followup_question": "",
                    "style": "warm",
                },
            )
        except Exception as exc:
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/llm/daily_summary", response_model=DailySummaryResponse)
def llm_daily_summary(
    payload: DailySummaryRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> DailySummaryResponse:
    _require_bearer(credentials)

    fallback_summary = "今天没有记录到明显情绪事件。需要的话，随时可以和我聊聊。"
    fallback_highlights = [
        "暂无明显触发事件",
        "整体状态较平稳",
        "需要时可随时记录感受",
    ]

    if not _llm:
        return DailySummaryResponse(summary=fallback_summary, highlights=fallback_highlights)

    reply = _llm.generate_daily_summary({"events": payload.events})
    if not reply:
        return DailySummaryResponse(summary=fallback_summary, highlights=fallback_highlights)

    return DailySummaryResponse(
        summary=str(reply.get("summary", "")),
        highlights=list(reply.get("highlights", [])),
    )

def _row_to_event(row: Dict) -> Dict:
    return {
        "id": row.get("id"),
        "timestamp_ms": row.get("timestamp_ms"),
        "type": row.get("type"),
        "description": row.get("description"),
        "V": row.get("v"),
        "A": row.get("a"),
        "T": row.get("t"),
        "S": row.get("s"),
        "intensity": row.get("intensity"),
        "source": row.get("source"),
    }


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket) -> None:
    await event_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        event_manager.disconnect(websocket)

