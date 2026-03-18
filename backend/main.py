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
import secrets
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, status, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from sqlite3 import Connection
import httpx
from cryptography.fernet import Fernet, InvalidToken

from . import auth
from .activation_prompts import ACTIVATION_SYSTEM_PROMPT, IDENTITY_EXTRACTION_PROMPT
from .assessment_engine import (
    PAIR_KEYS,
    QUESTION_MAP,
    build_final_profile,
    build_initial_session,
    build_memory_summary,
    compute_dimension_confidence,
    derive_type_code,
    empty_pair_confidence,
    empty_score_map,
    extract_next_question_from_model,
    extract_scoring_from_model,
    extract_termination_from_model,
    merge_scoring,
    normalize_confidence,
    normalize_scores,
    parse_json_dict,
    score_answer_heuristic,
    select_next_question,
)
from .assessment_prompts import (
    ASSESSMENT_CONDUCTOR_PROMPT,
    ASSESSMENT_MEMORY_WRITER_PROMPT,
    ASSESSMENT_SCORER_PROMPT,
    ASSESSMENT_TERMINATOR_PROMPT,
)
from .personality_prompts import PERSONALITY_EXTRACTION_PROMPT, PERSONALITY_SYSTEM_PROMPT
from .assistant_service import AssistantService, build_session_key, normalize_surface
from .db import get_db, init_db
from .openclaw_gateway import OpenClawGatewayError
from .schemas import (
    AssistantBridgeSendRequest,
    ActivationCompleteRequest,
    ActivationAssessmentFinishResponse,
    ActivationAssessmentStartRequest,
    ActivationAssessmentStateResponse,
    ActivationAssessmentTurnRequest,
    ActivationAssessmentTurnResponse,
    ActivationAssessmentVoiceRequest,
    ActivationIdentityInferRequest,
    ActivationIdentityInferResponse,
    ActivationPersonalityCompleteRequest,
    ActivationPersonalityInferRequest,
    ActivationPersonalityInferResponse,
    ActivationPersonalityStateResponse,
    ActivationProfileResponse,
    ActivationPromptPackResponse,
    AssistantMemorySearchResponse,
    AssistantSendRequest,
    AssistantSendResponse,
    AssistantSessionResetRequest,
    AssistantSessionStatusResponse,
    AssistantTodoCreateRequest,
    AssistantTodoItem,
    AssistantTodoListResponse,
    AssistantTodoUpdateRequest,
    CareRequest,
    CareResponse,
    DailySummaryRequest,
    DailySummaryResponse,
    DeviceInfoResponse,
    DeviceHeartbeatRequest,
    DeviceHeartbeatResponse,
    DeviceClaimRequest,
    DeviceClaimResponse,
    DeviceClaimStatusResponse,
    ClientSessionHeartbeatRequest,
    ClientSessionHeartbeatResponse,
    DeviceStatusResponse,
    EngineEventRequest,
    EngineSignalPullRequest,
    EngineSignalPullResponse,
    EngineSignalRequest,
    OwnerEnrollmentRequest,
    OwnerEnrollmentStartRequest,
    OwnerEnrollmentStartResponse,
    OwnerEnrollmentResponse,
    OwnerStatusResponse,
    EmotionEventRequest,
    EmotionEventResponse,
    LoginEmailRequest,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
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
from .settings import (
    ACCESS_TOKEN_EXPIRE_SEC,
    ALLOWED_ORIGINS,
    ASSISTANT_BRIDGE_TOKEN,
    ASSISTANT_BRIDGE_USER_ID,
    AUTH_SECRET_KEY,
    OPENCLAW_PREFERRED_CODE_MODEL,
    OPENCLAW_PREFERRED_MODE,
)

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
_llm_init_attempted = False
_llm_init_lock = threading.Lock()
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
assistant_service = AssistantService()


@app.on_event("startup")
def _startup() -> None:
    init_db()
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


def _ensure_llm_loaded():
    global _llm, _llm_config, _llm_init_attempted
    if _llm_init_attempted:
        return _llm
    with _llm_init_lock:
        if _llm_init_attempted:
            return _llm
        try:
            from engine.core.config import load_engine_config
            from engine.llm.llm_responder import LLMResponder

            config = load_engine_config("config/engine_config.json")
            _llm = LLMResponder(config.llm)
            _llm_config = config.llm
        except Exception:
            _llm = None
            _llm_config = None
        _llm_init_attempted = True
        return _llm


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


def _get_activation_profile(conn: Connection, user_id: int) -> Dict[str, object]:
    row = conn.execute(
        """
        SELECT *
        FROM user_activation_profiles
        WHERE user_id = ?
        """,
        (int(user_id),),
    ).fetchone()
    if not row:
        return {}
    payload = dict(row)
    try:
        profile_json = json.loads(str(payload.get("profile_json") or "{}"))
    except Exception:
        profile_json = {}
    if not isinstance(profile_json, dict):
        profile_json = {}
    merged = dict(profile_json)
    merged.update(
        {
            "preferred_name": str(payload.get("preferred_name") or "").strip() or None,
            "role_label": str(payload.get("role_label") or "").strip() or None,
            "relation_to_robot": str(payload.get("relation_to_robot") or "").strip() or None,
            "pronouns": str(payload.get("pronouns") or "").strip() or None,
            "identity_summary": str(payload.get("identity_summary") or "").strip() or None,
            "onboarding_notes": str(payload.get("onboarding_notes") or "").strip() or None,
            "voice_intro_summary": str(payload.get("voice_intro_summary") or "").strip() or None,
            "activation_version": str(payload.get("activation_version") or "v1"),
            "completed_at_ms": int(payload.get("completed_at_ms") or 0) or None,
        }
    )
    return merged


def _upsert_activation_profile(conn: Connection, user_id: int, payload: Dict[str, object]) -> Dict[str, object]:
    now_ms = int(time.time() * 1000)
    profile_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    preferred_name = str(payload.get("preferred_name") or "").strip()
    role_label = str(payload.get("role_label") or "owner").strip() or "owner"
    relation_to_robot = str(payload.get("relation_to_robot") or "primary_user").strip() or "primary_user"
    pronouns = str(payload.get("pronouns") or "").strip()
    identity_summary = str(payload.get("identity_summary") or "").strip()
    onboarding_notes = str(payload.get("onboarding_notes") or "").strip()
    voice_intro_summary = str(payload.get("voice_intro_summary") or "").strip()
    activation_version = str(payload.get("activation_version") or "v1").strip() or "v1"
    completed_at_ms = int(payload.get("completed_at_ms") or 0) or None
    conn.execute(
        """
        INSERT INTO user_activation_profiles (
            user_id,
            preferred_name,
            role_label,
            relation_to_robot,
            pronouns,
            identity_summary,
            onboarding_notes,
            voice_intro_summary,
            profile_json,
            activation_version,
            completed_at_ms,
            updated_at,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            preferred_name = excluded.preferred_name,
            role_label = excluded.role_label,
            relation_to_robot = excluded.relation_to_robot,
            pronouns = excluded.pronouns,
            identity_summary = excluded.identity_summary,
            onboarding_notes = excluded.onboarding_notes,
            voice_intro_summary = excluded.voice_intro_summary,
            profile_json = excluded.profile_json,
            activation_version = excluded.activation_version,
            completed_at_ms = excluded.completed_at_ms,
            updated_at = excluded.updated_at
        """,
        (
            int(user_id),
            preferred_name or None,
            role_label,
            relation_to_robot,
            pronouns or None,
            identity_summary or None,
            onboarding_notes or None,
            voice_intro_summary or None,
            profile_json,
            activation_version,
            completed_at_ms,
            now_ms,
            now_ms,
        ),
    )
    conn.commit()
    return _get_activation_profile(conn, user_id)


def _activation_response(conn: Connection, user: Dict[str, object], profile: Dict[str, object]) -> ActivationProfileResponse:
    is_configured = bool(user.get("is_configured", 0))
    psychometric_completed = bool(_get_psychometric_profile(conn, int(user["id"])))
    preferred_name = str(profile.get("preferred_name") or "").strip() or None
    role_label = str(profile.get("role_label") or "").strip() or None
    relation_to_robot = str(profile.get("relation_to_robot") or "").strip() or None
    pronouns = str(profile.get("pronouns") or "").strip() or None
    identity_summary = str(profile.get("identity_summary") or "").strip() or None
    onboarding_notes = str(profile.get("onboarding_notes") or "").strip() or None
    voice_intro_summary = str(profile.get("voice_intro_summary") or "").strip() or None
    return ActivationProfileResponse(
        ok=True,
        is_configured=is_configured,
        activation_required=not is_configured,
        assessment_required=is_configured and not psychometric_completed,
        psychometric_completed=psychometric_completed,
        preferred_name=preferred_name,
        role_label=role_label,
        relation_to_robot=relation_to_robot,
        pronouns=pronouns,
        identity_summary=identity_summary,
        onboarding_notes=onboarding_notes,
        voice_intro_summary=voice_intro_summary,
        activation_version=str(profile.get("activation_version") or "v1"),
        completed_at_ms=int(profile.get("completed_at_ms") or 0) or None,
        preferred_mode=OPENCLAW_PREFERRED_MODE,
        preferred_code_model=OPENCLAW_PREFERRED_CODE_MODEL,
    )


def _json_list(value: object) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    try:
        parsed = json.loads(str(value or "[]"))
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _get_personality_profile(conn: Connection, user_id: int) -> Dict[str, object]:
    row = conn.execute(
        """
        SELECT *
        FROM user_personality_profiles
        WHERE user_id = ?
        """,
        (int(user_id),),
    ).fetchone()
    if not row:
        return {}
    payload = dict(row)
    try:
        profile_json = json.loads(str(payload.get("profile_json") or "{}"))
    except Exception:
        profile_json = {}
    if not isinstance(profile_json, dict):
        profile_json = {}
    merged = dict(profile_json)
    merged.update(
        {
            "summary": str(payload.get("summary") or "").strip(),
            "response_style": str(payload.get("response_style") or "").strip(),
            "care_style": str(payload.get("care_style") or "").strip(),
            "traits": _json_list(payload.get("traits_json")),
            "topics": _json_list(payload.get("topics_json")),
            "boundaries": _json_list(payload.get("boundaries_json")),
            "signals": _json_list(payload.get("signals_json")),
            "confidence": float(payload.get("confidence") or 0.0),
            "sample_count": int(payload.get("sample_count") or 0),
            "inference_version": str(payload.get("inference_version") or "v1").strip() or "v1",
            "updated_at_ms": int(payload.get("updated_at") or 0) or None,
        }
    )
    return merged


def _personality_response(profile: Dict[str, object]) -> ActivationPersonalityStateResponse:
    return ActivationPersonalityStateResponse(
        ok=True,
        exists=bool(profile),
        summary=str(profile.get("summary") or "").strip(),
        response_style=str(profile.get("response_style") or "").strip(),
        care_style=str(profile.get("care_style") or "").strip(),
        traits=[str(item) for item in profile.get("traits") or [] if str(item).strip()],
        topics=[str(item) for item in profile.get("topics") or [] if str(item).strip()],
        boundaries=[str(item) for item in profile.get("boundaries") or [] if str(item).strip()],
        signals=[str(item) for item in profile.get("signals") or [] if str(item).strip()],
        confidence=max(0.0, min(1.0, float(profile.get("confidence") or 0.0))),
        sample_count=max(0, int(profile.get("sample_count") or 0)),
        inference_version=str(profile.get("inference_version") or "v1"),
        updated_at_ms=int(profile.get("updated_at_ms") or 0) or None,
    )


def _upsert_personality_profile(conn: Connection, user_id: int, payload: Dict[str, object]) -> Dict[str, object]:
    now_ms = int(time.time() * 1000)
    traits = [str(item).strip() for item in payload.get("traits") or [] if str(item).strip()]
    topics = [str(item).strip() for item in payload.get("topics") or [] if str(item).strip()]
    boundaries = [str(item).strip() for item in payload.get("boundaries") or [] if str(item).strip()]
    signals = [str(item).strip() for item in payload.get("signals") or [] if str(item).strip()]
    profile_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    conn.execute(
        """
        INSERT INTO user_personality_profiles (
            user_id,
            summary,
            response_style,
            care_style,
            traits_json,
            topics_json,
            boundaries_json,
            signals_json,
            profile_json,
            confidence,
            sample_count,
            inference_version,
            updated_at,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            summary = excluded.summary,
            response_style = excluded.response_style,
            care_style = excluded.care_style,
            traits_json = excluded.traits_json,
            topics_json = excluded.topics_json,
            boundaries_json = excluded.boundaries_json,
            signals_json = excluded.signals_json,
            profile_json = excluded.profile_json,
            confidence = excluded.confidence,
            sample_count = excluded.sample_count,
            inference_version = excluded.inference_version,
            updated_at = excluded.updated_at
        """,
        (
            int(user_id),
            str(payload.get("summary") or "").strip() or None,
            str(payload.get("response_style") or "").strip() or None,
            str(payload.get("care_style") or "").strip() or None,
            json.dumps(traits, ensure_ascii=False),
            json.dumps(topics, ensure_ascii=False),
            json.dumps(boundaries, ensure_ascii=False),
            json.dumps(signals, ensure_ascii=False),
            profile_json,
            max(0.0, min(1.0, float(payload.get("confidence") or 0.0))),
            max(0, int(payload.get("sample_count") or 0)),
            str(payload.get("inference_version") or "v1").strip() or "v1",
            now_ms,
            now_ms,
        ),
    )
    conn.commit()
    return _get_personality_profile(conn, user_id)


def _get_active_assessment_session_row(conn: Connection, user_id: int) -> Optional[Dict[str, object]]:
    row = conn.execute(
        """
        SELECT *
        FROM user_assessment_sessions
        WHERE user_id = ? AND status = 'active'
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (int(user_id),),
    ).fetchone()
    return dict(row) if row else None


def _get_latest_assessment_session_row(conn: Connection, user_id: int) -> Optional[Dict[str, object]]:
    row = conn.execute(
        """
        SELECT *
        FROM user_assessment_sessions
        WHERE user_id = ?
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (int(user_id),),
    ).fetchone()
    return dict(row) if row else None


def _load_assessment_session(conn: Connection, user_id: int, active_only: bool = False) -> tuple[Optional[int], Dict[str, object]]:
    row = _get_active_assessment_session_row(conn, user_id) if active_only else _get_latest_assessment_session_row(conn, user_id)
    if not row:
        return None, {}
    payload = parse_json_dict(str(row.get("session_json") or "{}"))
    if not payload:
        payload = {}
    payload.setdefault("status", str(row.get("status") or "idle"))
    payload.setdefault("started_at_ms", int(row.get("started_at_ms") or 0) or None)
    payload.setdefault("completed_at_ms", int(row.get("completed_at_ms") or 0) or None)
    payload.setdefault("updated_at_ms", int(row.get("updated_at") or 0) or None)
    payload["scores"] = normalize_scores(payload.get("scores"))
    payload["dimension_confidence"] = normalize_confidence(payload.get("dimension_confidence"))
    return int(row["id"]), payload


def _save_assessment_session(conn: Connection, user_id: int, session_payload: Dict[str, object], session_id: Optional[int] = None) -> int:
    now_ms = int(time.time() * 1000)
    payload = dict(session_payload)
    payload["scores"] = normalize_scores(payload.get("scores"))
    payload["dimension_confidence"] = normalize_confidence(payload.get("dimension_confidence"))
    session_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    status_value = str(payload.get("status") or "active").strip() or "active"
    started_at_ms = int(payload.get("started_at_ms") or now_ms)
    completed_at_ms = int(payload.get("completed_at_ms") or 0) or None
    if session_id is None:
        conn.execute("UPDATE user_assessment_sessions SET status = 'superseded', updated_at = ? WHERE user_id = ? AND status = 'active'", (now_ms, int(user_id)))
        cursor = conn.execute(
            """
            INSERT INTO user_assessment_sessions (
                user_id, status, session_json, started_at_ms, completed_at_ms, updated_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (int(user_id), status_value, session_json, started_at_ms, completed_at_ms, now_ms, now_ms),
        )
        conn.commit()
        return int(cursor.lastrowid)
    conn.execute(
        """
        UPDATE user_assessment_sessions
        SET status = ?, session_json = ?, started_at_ms = ?, completed_at_ms = ?, updated_at = ?
        WHERE id = ? AND user_id = ?
        """,
        (status_value, session_json, started_at_ms, completed_at_ms, now_ms, int(session_id), int(user_id)),
    )
    conn.commit()
    return int(session_id)


def _append_assessment_turn_event(
    conn: Connection,
    user_id: int,
    session_id: int,
    turn_index: int,
    question_id: str,
    question_text: str,
    answer_text: str,
    transcript_text: str,
    scoring: Dict[str, object],
) -> None:
    conn.execute(
        """
        INSERT INTO assessment_turn_events (
            user_id, session_id, turn_index, question_id, question_text,
            answer_text, transcript_text, scoring_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(user_id),
            int(session_id),
            int(turn_index),
            str(question_id or "").strip() or None,
            str(question_text or "").strip() or None,
            str(answer_text or "").strip() or None,
            str(transcript_text or "").strip() or None,
            json.dumps(scoring or {}, ensure_ascii=False, separators=(",", ":")),
            int(time.time() * 1000),
        ),
    )
    conn.commit()


def _get_psychometric_profile(conn: Connection, user_id: int) -> Dict[str, object]:
    row = conn.execute(
        """
        SELECT *
        FROM user_psychometric_profiles
        WHERE user_id = ?
        """,
        (int(user_id),),
    ).fetchone()
    if not row:
        return {}
    payload = dict(row)
    merged = parse_json_dict(str(payload.get("profile_json") or "{}"))
    merged.update(
        {
            "type_code": str(payload.get("type_code") or "").strip(),
            "scores": parse_json_dict(str(payload.get("scores_json") or "{}")),
            "dimension_confidence": parse_json_dict(str(payload.get("dimension_confidence_json") or "{}")),
            "evidence_summary": parse_json_dict(str(payload.get("evidence_summary_json") or "{}")),
            "summary": str(payload.get("summary") or "").strip(),
            "response_style": str(payload.get("response_style") or "").strip(),
            "care_style": str(payload.get("care_style") or "").strip(),
            "conversation_count": int(payload.get("conversation_count") or 0),
            "completed_at_ms": int(payload.get("completed_at_ms") or 0) or None,
            "updated_at_ms": int(payload.get("updated_at") or 0) or None,
            "inference_version": str(payload.get("inference_version") or "assessment-v1").strip() or "assessment-v1",
        }
    )
    merged["scores"] = normalize_scores(merged.get("scores"))
    merged["dimension_confidence"] = normalize_confidence(merged.get("dimension_confidence"))
    evidence = merged.get("evidence_summary")
    if not isinstance(evidence, dict):
        evidence = {}
    merged["evidence_summary"] = {
        "highlights": [str(item).strip() for item in evidence.get("highlights") or [] if str(item).strip()],
        "notes": str(evidence.get("notes") or "").strip(),
    }
    return merged


def _upsert_psychometric_profile(conn: Connection, user_id: int, profile: Dict[str, object]) -> Dict[str, object]:
    now_ms = int(time.time() * 1000)
    scores = normalize_scores(profile.get("scores"))
    confidence = normalize_confidence(profile.get("dimension_confidence"))
    evidence_summary = profile.get("evidence_summary") if isinstance(profile.get("evidence_summary"), dict) else {}
    payload = dict(profile)
    payload["scores"] = scores
    payload["dimension_confidence"] = confidence
    payload["evidence_summary"] = evidence_summary
    conn.execute(
        """
        INSERT INTO user_psychometric_profiles (
            user_id, type_code, scores_json, dimension_confidence_json, evidence_summary_json,
            summary, response_style, care_style, conversation_count, completed_at_ms,
            inference_version, profile_json, updated_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            type_code = excluded.type_code,
            scores_json = excluded.scores_json,
            dimension_confidence_json = excluded.dimension_confidence_json,
            evidence_summary_json = excluded.evidence_summary_json,
            summary = excluded.summary,
            response_style = excluded.response_style,
            care_style = excluded.care_style,
            conversation_count = excluded.conversation_count,
            completed_at_ms = excluded.completed_at_ms,
            inference_version = excluded.inference_version,
            profile_json = excluded.profile_json,
            updated_at = excluded.updated_at
        """,
        (
            int(user_id),
            str(profile.get("type_code") or derive_type_code(scores)).strip() or None,
            json.dumps(scores, ensure_ascii=False, separators=(",", ":")),
            json.dumps(confidence, ensure_ascii=False, separators=(",", ":")),
            json.dumps(evidence_summary, ensure_ascii=False, separators=(",", ":")),
            str(profile.get("summary") or "").strip() or None,
            str(profile.get("response_style") or "").strip() or None,
            str(profile.get("care_style") or "").strip() or None,
            int(profile.get("conversation_count") or 0),
            int(profile.get("completed_at_ms") or 0) or None,
            str(profile.get("inference_version") or "assessment-v1").strip() or "assessment-v1",
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            now_ms,
            now_ms,
        ),
    )
    conn.commit()
    return _get_psychometric_profile(conn, user_id)


def _assessment_response(session: Dict[str, object], device_online: bool = False, exists: bool = True) -> ActivationAssessmentStateResponse:
    final = session.get("final_result") if isinstance(session.get("final_result"), dict) else {}
    scores = normalize_scores((final or session).get("scores"))
    confidence = normalize_confidence((final or session).get("dimension_confidence"))
    evidence = (final or session).get("evidence_summary")
    if not isinstance(evidence, dict):
        evidence = {}
    return ActivationAssessmentStateResponse(
        ok=True,
        exists=bool(exists and session),
        status=str(session.get("status") or "idle"),
        started_at_ms=int(session.get("started_at_ms") or 0) or None,
        updated_at_ms=int(session.get("updated_at_ms") or 0) or None,
        completed_at_ms=int((final or session).get("completed_at_ms") or 0) or None,
        turn_count=max(0, int(session.get("turn_count") or 0)),
        effective_turn_count=max(0, int(session.get("effective_turn_count") or 0)),
        latest_question=str(session.get("latest_question") or ""),
        latest_transcript=str(session.get("latest_transcript") or ""),
        last_question_id=str(session.get("last_question_id") or ""),
        type_code=str((final or session).get("type_code") or ""),
        scores=scores,
        dimension_confidence=confidence,
        evidence_summary={
            "highlights": [str(item).strip() for item in evidence.get("highlights") or [] if str(item).strip()],
            "notes": str(evidence.get("notes") or "").strip(),
        },
        conversation_count=max(0, int((final or session).get("conversation_count") or session.get("effective_turn_count") or 0)),
        finish_reason=str(session.get("finish_reason") or ""),
        voice_mode=str(session.get("voice_mode") or "idle"),
        voice_session_active=bool(session.get("voice_session_active")),
        device_online=bool(device_online),
        summary=str((final or session).get("summary") or (session.get("profile_preview") or {}).get("summary") or ""),
        response_style=str((final or session).get("response_style") or (session.get("profile_preview") or {}).get("response_style") or ""),
        care_style=str((final or session).get("care_style") or (session.get("profile_preview") or {}).get("care_style") or ""),
        inference_version=str((final or session).get("inference_version") or "assessment-v1"),
    )


def _heuristic_personality_profile(text: str) -> Dict[str, object]:
    raw = str(text or "").strip()
    lowered = raw.lower()
    traits: List[str] = []
    topics: List[str] = []
    boundaries: List[str] = []
    signals: List[str] = []
    response_style = "先给结论，再补解释。"
    care_style = "以低打扰、可执行、短句陪伴为主。"
    if any(token in raw for token in ["直接", "别绕", "简洁", "效率"]):
        traits.append("偏直接")
        response_style = "先给结论，避免绕圈，必要时再补步骤。"
    if any(token in raw for token in ["理性", "逻辑", "分析"]):
        traits.append("偏理性")
    if any(token in raw for token in ["敏感", "容易想多", "内耗", "焦虑"]):
        traits.append("容易内耗")
        topics.append("压力与焦虑管理")
        care_style = "先安抚情绪，再给一个很小的下一步。"
    if any(token in raw for token in ["睡眠", "熬夜", "作息"]):
        topics.append("睡眠节律")
    if any(token in raw for token in ["工作", "任务", "效率", "项目"]):
        topics.append("工作压力")
    if any(token in raw for token in ["不要催", "别催", "不喜欢被催"]):
        boundaries.append("不要频繁催促")
    if any(token in raw for token in ["不要说教", "别说教"]):
        boundaries.append("不要说教")
    if any(token in raw for token in ["先自己扛", "先不说", "先沉默", "不想马上说"]):
        signals.append("压力大时可能先沉默")
    if "不是生气" in raw or "只是着急" in raw or "只是烦" in raw:
        signals.append("语气直接不等于敌意")
    if "幽默" in raw or "轻松" in raw:
        care_style = "允许轻松一点，但避免过度玩笑。"
    if not traits:
        traits = ["需要稳定感", "偏长期陪伴"]
    if not topics:
        topics = ["日常压力", "情绪节律"]
    if not boundaries:
        boundaries = ["避免一次问太多问题"]
    if not signals:
        signals = ["需要先被理解，再接受建议"]
    summary = "这个用户更适合稳定、低打扰、持续记忆式陪伴。"
    return {
        "summary": summary,
        "response_style": response_style,
        "care_style": care_style,
        "traits": traits[:5],
        "topics": topics[:5],
        "boundaries": boundaries[:5],
        "signals": signals[:5],
        "confidence": 0.42 if raw else 0.0,
        "sample_count": max(1, len([line for line in raw.splitlines() if line.strip()])) if raw else 0,
        "inference_version": "v1",
        "heuristic": True,
    }


def _build_assistant_identity_context(conn: Connection, user_id: int) -> Dict[str, object]:
    activation = _get_activation_profile(conn, user_id)
    personality = _get_personality_profile(conn, user_id)
    psychometric = _get_psychometric_profile(conn, user_id)
    return {
        "identity": {
            "preferred_name": str(activation.get("preferred_name") or "").strip(),
            "role_label": str(activation.get("role_label") or "").strip(),
            "relation_to_robot": str(activation.get("relation_to_robot") or "").strip(),
            "identity_summary": str(activation.get("identity_summary") or "").strip(),
            "voice_intro_summary": str(activation.get("voice_intro_summary") or "").strip(),
        },
        "personality": {
            "summary": str(personality.get("summary") or "").strip(),
            "response_style": str(personality.get("response_style") or "").strip(),
            "care_style": str(personality.get("care_style") or "").strip(),
            "traits": [str(item) for item in personality.get("traits") or [] if str(item).strip()],
            "topics": [str(item) for item in personality.get("topics") or [] if str(item).strip()],
            "boundaries": [str(item) for item in personality.get("boundaries") or [] if str(item).strip()],
            "signals": [str(item) for item in personality.get("signals") or [] if str(item).strip()],
        },
        "psychometric": {
            "type_code": str(psychometric.get("type_code") or "").strip(),
            "scores": psychometric.get("scores") or empty_score_map(),
            "dimension_confidence": psychometric.get("dimension_confidence") or empty_pair_confidence(),
            "summary": str(psychometric.get("summary") or "").strip(),
            "response_style": str(psychometric.get("response_style") or "").strip(),
            "care_style": str(psychometric.get("care_style") or "").strip(),
            "conversation_count": int(psychometric.get("conversation_count") or 0),
        },
        "runtime_preferences": {
            "preferred_mode": OPENCLAW_PREFERRED_MODE,
            "preferred_code_model": OPENCLAW_PREFERRED_CODE_MODEL,
        },
    }


def _extract_json_block(text: str) -> Dict[str, object]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    candidate = raw[start : end + 1]
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _assessment_device_online(conn: Connection, user_id: int, device_id: Optional[str] = None) -> tuple[bool, Optional[Dict[str, object]]]:
    selected = _get_device(conn, int(user_id), device_id) if device_id else {}
    if not selected:
        devices = _list_devices(conn, int(user_id))
        selected = devices[0] if devices else {}
    resolved_ip = str(selected.get("device_ip") or "").strip() if selected else ""
    return bool(selected and resolved_ip), (selected or None)


async def _assessment_pick_model_question(
    user_id: int,
    activation_profile: Dict[str, object],
    session_payload: Dict[str, object],
) -> Dict[str, object]:
    prompt = (
        f"{ASSESSMENT_CONDUCTOR_PROMPT}\n\n"
        f"输入数据：{json.dumps({'user_id': user_id, 'identity': activation_profile, 'session': session_payload}, ensure_ascii=False)}"
    )
    session_key = f"activation:{int(user_id)}:assessment:conductor:{int(time.time() * 1000)}"
    try:
        raw = await assistant_service.gateway.send_message(session_key, prompt)
    except OpenClawGatewayError:
        return {}
    return extract_next_question_from_model(raw)


async def _assessment_score_model(
    user_id: int,
    question: Dict[str, object],
    session_payload: Dict[str, object],
    answer: str,
) -> Dict[str, object]:
    prompt = (
        f"{ASSESSMENT_SCORER_PROMPT}\n\n"
        f"输入数据：{json.dumps({'question': question, 'session': session_payload, 'answer': answer}, ensure_ascii=False)}"
    )
    session_key = f"activation:{int(user_id)}:assessment:scorer:{int(time.time() * 1000)}"
    try:
        raw = await assistant_service.gateway.send_message(session_key, prompt)
    except OpenClawGatewayError:
        return {}
    return extract_scoring_from_model(raw)


async def _assessment_terminate_model(user_id: int, session_payload: Dict[str, object]) -> Dict[str, object]:
    prompt = (
        f"{ASSESSMENT_TERMINATOR_PROMPT}\n\n"
        f"输入数据：{json.dumps(session_payload, ensure_ascii=False)}"
    )
    session_key = f"activation:{int(user_id)}:assessment:terminator:{int(time.time() * 1000)}"
    try:
        raw = await assistant_service.gateway.send_message(session_key, prompt)
    except OpenClawGatewayError:
        return {}
    return extract_termination_from_model(raw)


def _assessment_sync_personality_profile(conn: Connection, user_id: int, psychometric: Dict[str, object]) -> None:
    type_code = str(psychometric.get("type_code") or "").strip()
    traits = [f"类型:{type_code}"] if type_code else []
    for pair in PAIR_KEYS:
        conf = psychometric.get("dimension_confidence") or {}
        score = float((conf or {}).get(pair, 0.0) or 0.0)
        if score >= 0.78:
            traits.append(f"{pair}稳定")
    summary = str(psychometric.get("summary") or "").strip()
    _upsert_personality_profile(
        conn,
        int(user_id),
        {
            "summary": summary,
            "response_style": str(psychometric.get("response_style") or "").strip(),
            "care_style": str(psychometric.get("care_style") or "").strip(),
            "traits": traits[:6],
            "topics": [],
            "boundaries": [],
            "signals": [str(item) for item in ((psychometric.get("evidence_summary") or {}).get("highlights") or [])[:4]],
            "confidence": min(0.99, max(normalize_confidence(psychometric.get("dimension_confidence")).values() or [0.0])),
            "sample_count": int(psychometric.get("conversation_count") or 0),
            "inference_version": str(psychometric.get("inference_version") or "assessment-v1"),
            "profile": {"source": "psychometric_assessment", "psychometric_profile": psychometric},
        },
    )


def _persist_assessment_completion(conn: Connection, user_id: int, session_payload: Dict[str, object]) -> Dict[str, object]:
    final_profile = build_final_profile(session_payload)
    psychometric = _upsert_psychometric_profile(conn, int(user_id), final_profile)
    _assessment_sync_personality_profile(conn, int(user_id), psychometric)
    activation = _get_activation_profile(conn, int(user_id))
    preferred_name = str(activation.get("preferred_name") or "").strip()
    assistant_service.store.append_memory(
        int(user_id),
        title="psychometric_profile",
        content=build_memory_summary(psychometric, preferred_name=preferred_name),
        tags=["activation", "assessment", "psychometric"],
    )
    return psychometric


def _heuristic_activation_identity(transcript: str, observed_name: str = "") -> Dict[str, object]:
    raw = str(transcript or "").strip()
    lowered = raw.lower()
    preferred_name = str(observed_name or "").strip()
    patterns = [
        r"我叫([^\s，。,.!！?？]{1,12})",
        r"我是([^\s，。,.!！?？]{1,12})",
        r"你可以叫我([^\s，。,.!！?？]{1,12})",
        r"叫我([^\s，。,.!！?？]{1,12})就行",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw)
        if match:
            preferred_name = str(match.group(1) or "").strip("，。,.!！?？ ")
            if preferred_name:
                break
    role_label = "unknown"
    relation = "unknown"
    if any(token in raw for token in ["主人", "owner"]):
        role_label = "owner"
        relation = "primary_user"
    elif any(token in raw for token in ["家人", "妈妈", "爸爸", "姐姐", "哥哥", "妹妹", "弟弟", "family"]):
        role_label = "family"
        relation = "family_member"
    elif any(token in raw for token in ["护工", "照护", "护理", "caregiver"]):
        role_label = "caregiver"
        relation = "caregiver"
    elif any(token in lowered for token in ["admin", "管理员", "调试", "维护", "operator"]):
        role_label = "operator" if "operator" in lowered or "调试" in raw else "admin"
        relation = "maintainer"
    elif any(token in raw for token in ["病人", "患者"]):
        role_label = "patient"
        relation = "primary_user"
    summary = ""
    if preferred_name:
        summary = f"{preferred_name} 是当前与机器人首次确认身份的用户。"
    if role_label == "owner":
        summary = f"{preferred_name or '该用户'} 是机器人的主人，后续应优先按主人身份服务。"
    elif role_label == "family":
        summary = f"{preferred_name or '该用户'} 是与机器人相关的家庭成员，后续应按家庭成员身份理解。"
    elif role_label == "caregiver":
        summary = f"{preferred_name or '该用户'} 是照护相关人员，后续应按照护者身份支持。"
    elif role_label in {"operator", "admin"}:
        summary = f"{preferred_name or '该用户'} 更像是设备操作或维护人员，不应默认视作主人。"
    notes = "待确认：本结果由本地规则保守推断，建议在激活页人工确认。"
    voice_intro = raw[:80]
    confidence = 0.28
    if preferred_name:
        confidence += 0.18
    if role_label != "unknown":
        confidence += 0.24
    return {
        "preferred_name": preferred_name,
        "role_label": role_label,
        "relation_to_robot": relation,
        "pronouns": "",
        "identity_summary": summary[:80],
        "onboarding_notes": notes[:120],
        "voice_intro_summary": voice_intro,
        "confidence": max(0.0, min(0.75, confidence)),
        "heuristic": True,
    }


def _activation_page_html() -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>首次激活</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f3efe7;
      --card: #fffaf1;
      --ink: #1c2a1f;
      --muted: #5c6b60;
      --line: #d7cdbb;
      --accent: #2e7d5b;
      --accent-2: #b85c38;
    }}
    body {{
      margin: 0;
      font-family: "Microsoft YaHei UI", "PingFang SC", sans-serif;
      background:
        radial-gradient(circle at top right, rgba(46,125,91,0.12), transparent 28%),
        radial-gradient(circle at bottom left, rgba(184,92,56,0.14), transparent 26%),
        var(--bg);
      color: var(--ink);
    }}
    main {{
      max-width: 980px;
      margin: 32px auto;
      padding: 0 20px 40px;
    }}
    h1 {{
      font-size: 32px;
      margin: 0 0 8px;
    }}
    p {{
      color: var(--muted);
      line-height: 1.6;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 18px;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 18px;
      box-shadow: 0 10px 30px rgba(20, 32, 24, 0.06);
    }}
    label {{
      display: block;
      font-size: 13px;
      color: var(--muted);
      margin: 10px 0 6px;
    }}
    input, textarea, select {{
      width: 100%;
      box-sizing: border-box;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px 12px;
      font: inherit;
      background: white;
      color: var(--ink);
    }}
    textarea {{
      min-height: 112px;
      resize: vertical;
    }}
    .row {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 14px;
    }}
    button {{
      border: 0;
      border-radius: 999px;
      padding: 11px 16px;
      font: inherit;
      cursor: pointer;
      background: var(--accent);
      color: white;
    }}
    button.secondary {{
      background: var(--accent-2);
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      background: #172018;
      color: #eaf5ee;
      padding: 14px;
      border-radius: 14px;
      min-height: 140px;
    }}
    .hint {{
      font-size: 12px;
      color: var(--muted);
      margin-top: 8px;
    }}
  </style>
</head>
<body>
  <main>
    <h1>首次激活与身份确认</h1>
    <p>第一次登录后，先确认“这个人是谁、和机器人是什么关系、机器人应该如何理解与服务他/她”。这一步会沉淀成长期身份卡，不直接混进普通聊天上下文。</p>
    <div class="grid">
      <section class="card">
        <label>Bearer Token</label>
        <input id="token" placeholder="粘贴登录返回的 token，或使用 ?token=..." />
        <div class="hint" id="modeHint">默认模式：{OPENCLAW_PREFERRED_MODE}；默认模型偏好：{OPENCLAW_PREFERRED_CODE_MODEL}</div>

        <label>首段语音 / 首次对话记录</label>
        <textarea id="transcript" placeholder="例如：你好，我叫小北，是这个机器人的主人，你可以叫我小北。"></textarea>
        <label>观察到的名字（可选）</label>
        <input id="observed_name" placeholder="如 ASR 或联系人资料里已有名字" />
        <div class="row">
          <button id="loadBtn" type="button">读取当前状态</button>
          <button id="inferBtn" class="secondary" type="button">从首段语音推断身份</button>
        </div>
      </section>

      <section class="card">
        <label>称呼</label>
        <input id="preferred_name" />
        <label>角色</label>
        <select id="role_label">
          <option value="owner">owner</option>
          <option value="family">family</option>
          <option value="caregiver">caregiver</option>
          <option value="guest">guest</option>
          <option value="operator">operator</option>
          <option value="admin">admin</option>
          <option value="patient">patient</option>
          <option value="unknown">unknown</option>
        </select>
        <label>与机器人关系</label>
        <select id="relation_to_robot">
          <option value="primary_user">primary_user</option>
          <option value="family_member">family_member</option>
          <option value="caregiver">caregiver</option>
          <option value="visitor">visitor</option>
          <option value="maintainer">maintainer</option>
          <option value="observer">observer</option>
          <option value="unknown">unknown</option>
        </select>
        <label>代词 / 称谓偏好</label>
        <input id="pronouns" />
        <label>身份摘要</label>
        <textarea id="identity_summary"></textarea>
        <label>激活备注</label>
        <textarea id="onboarding_notes"></textarea>
        <label>首次语音摘要</label>
        <textarea id="voice_intro_summary"></textarea>
        <div class="row">
          <button id="saveBtn" type="button">完成激活</button>
        </div>
      </section>
    </div>

    <section class="card" style="margin-top:18px">
      <label>调试输出</label>
      <pre id="output">等待操作...</pre>
    </section>
  </main>
  <script>
    const q = (id) => document.getElementById(id);
    const output = q("output");
    const tokenInput = q("token");
    const qsToken = new URLSearchParams(window.location.search).get("token") || "";
    tokenInput.value = qsToken || localStorage.getItem("activationToken") || "";

    function headers() {{
      const token = (tokenInput.value || "").trim();
      if (!token) throw new Error("请先提供 Bearer token");
      localStorage.setItem("activationToken", token);
      return {{
        "Authorization": `Bearer ${{token}}`,
        "Content-Type": "application/json"
      }};
    }}

    function fillForm(data) {{
      q("preferred_name").value = data.preferred_name || "";
      q("role_label").value = data.role_label || "owner";
      q("relation_to_robot").value = data.relation_to_robot || "primary_user";
      q("pronouns").value = data.pronouns || "";
      q("identity_summary").value = data.identity_summary || "";
      q("onboarding_notes").value = data.onboarding_notes || "";
      q("voice_intro_summary").value = data.voice_intro_summary || "";
    }}

    async function fetchJson(url, options) {{
      const res = await fetch(url, options);
      const data = await res.json().catch(() => ({{ ok: false, detail: "invalid json" }}));
      if (!res.ok) {{
        throw new Error(data.detail || JSON.stringify(data));
      }}
      return data;
    }}

    async function loadState() {{
      const [state, prompts] = await Promise.all([
        fetchJson("/api/activation/state", {{ headers: headers() }}),
        fetchJson("/api/activation/prompt-pack", {{ headers: headers() }})
      ]);
      fillForm(state);
      q("modeHint").textContent = `默认模式：${{prompts.preferred_mode}}；默认模型偏好：${{prompts.preferred_code_model}}`;
      output.textContent = JSON.stringify(state, null, 2);
    }}

    async function inferIdentity() {{
      const payload = {{
        transcript: q("transcript").value,
        observed_name: q("observed_name").value,
        surface: "robot",
        context: {{
          entrypoint: "activation_page"
        }}
      }};
      const data = await fetchJson("/api/activation/identity/infer", {{
        method: "POST",
        headers: headers(),
        body: JSON.stringify(payload)
      }});
      fillForm(data);
      output.textContent = JSON.stringify(data, null, 2);
    }}

    async function completeActivation() {{
      const payload = {{
        preferred_name: q("preferred_name").value,
        role_label: q("role_label").value,
        relation_to_robot: q("relation_to_robot").value,
        pronouns: q("pronouns").value,
        identity_summary: q("identity_summary").value,
        onboarding_notes: q("onboarding_notes").value,
        voice_intro_summary: q("voice_intro_summary").value,
        profile: {{
          source: "activation_page"
        }},
        activation_version: "v1"
      }};
      const data = await fetchJson("/api/activation/complete", {{
        method: "POST",
        headers: headers(),
        body: JSON.stringify(payload)
      }});
      output.textContent = JSON.stringify(data, null, 2);
    }}

    q("loadBtn").addEventListener("click", () => loadState().catch((err) => output.textContent = String(err)));
    q("inferBtn").addEventListener("click", () => inferIdentity().catch((err) => output.textContent = String(err)));
    q("saveBtn").addEventListener("click", () => completeActivation().catch((err) => output.textContent = String(err)));

    loadState().catch((err) => output.textContent = `等待 token 或接口可用：${{err}}`);
  </script>
</body>
</html>"""


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


def _list_chat_messages(
    conn: Connection,
    user_id: int,
    limit: int,
    session_key: Optional[str] = None,
    surface: Optional[str] = None,
) -> List[Dict]:
    query = [
        "SELECT * FROM chat_messages",
        "WHERE user_id = ?",
    ]
    params: List[Any] = [user_id]
    if session_key:
        query.append("AND session_key = ?")
        params.append(str(session_key))
    elif surface:
        query.append("AND surface = ?")
        params.append(str(surface))
    query.append("ORDER BY timestamp_ms ASC LIMIT ?")
    params.append(limit)
    cur = conn.execute("\n".join(query), params)
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
        row["surface"] = str(row.get("surface") or "desktop")
        row["session_key"] = str(row.get("session_key") or "").strip() or None
    return rows


def _insert_chat_message(conn: Connection, user_id: int, payload: ChatMessageRequest) -> int:
    attachments_json = "[]"
    try:
        attachments_json = json.dumps(payload.attachments or [], ensure_ascii=False, separators=(",", ":"))
    except Exception:
        attachments_json = "[]"
    cur = conn.execute(
        """
        INSERT INTO chat_messages (user_id, sender, text, content_type, attachments_json, timestamp_ms, surface, session_key)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            payload.sender,
            payload.text,
            str(payload.content_type or "text"),
            attachments_json,
            payload.timestamp_ms,
            str(payload.surface or "desktop"),
            str(payload.session_key or "").strip() or None,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def _chat_response_from_row(row: Dict[str, object]) -> ChatMessageResponse:
    return ChatMessageResponse(
        id=int(row["id"]),
        sender=str(row.get("sender") or ""),
        text=str(row.get("text") or ""),
        content_type=str(row.get("content_type") or "text"),
        attachments=row.get("attachments") if isinstance(row.get("attachments"), list) else [],
        timestamp_ms=int(row.get("timestamp_ms") or 0),
        surface=str(row.get("surface") or "desktop"),
        session_key=str(row.get("session_key") or "").strip() or None,
    )


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
            onboarding_state = COALESCE(?, onboarding_state),
            identity_state = COALESCE(?, identity_state),
            identity_version = COALESCE(?, identity_version),
            owner_last_seen_ms = COALESCE(?, owner_last_seen_ms),
            updated_at = ?
        WHERE user_id = ? AND device_id = ?
        """,
        (
            last_seen_ms,
            status_json,
            (status or {}).get("onboarding_state") if isinstance(status, dict) else None,
            (status or {}).get("identity_state") if isinstance(status, dict) else None,
            (status or {}).get("embedding_version") if isinstance(status, dict) else None,
            last_seen_ms if isinstance(status, dict) and bool(status.get("owner_recognized")) else None,
            now_ms,
            user_id,
            device_id,
        ),
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
            onboarding_state = COALESCE(?, onboarding_state),
            identity_state = COALESCE(?, identity_state),
            identity_version = COALESCE(?, identity_version),
            owner_last_seen_ms = COALESCE(?, owner_last_seen_ms),
            updated_at = ?
        WHERE device_id = ?
        """,
        (
            device_ip,
            device_mac,
            ssid,
            last_seen_ms,
            status_json,
            (status or {}).get("onboarding_state") if isinstance(status, dict) else None,
            (status or {}).get("identity_state") if isinstance(status, dict) else None,
            (status or {}).get("embedding_version") if isinstance(status, dict) else None,
            last_seen_ms if isinstance(status, dict) and bool(status.get("owner_recognized")) else None,
            now_ms,
            device_id,
        ),
    )
    conn.commit()
    return int(cur.rowcount or 0)


def _create_claim_session(conn: Connection, user_id: int, device_id: str) -> Dict:
    now_ms = int(time.time() * 1000)
    expires_at_ms = now_ms + (10 * 60 * 1000)
    claim_token = secrets.token_urlsafe(24)
    conn.execute(
        """
        UPDATE device_claim_sessions
        SET is_active = 0, updated_at = ?
        WHERE device_id = ?
        """,
        (now_ms, device_id),
    )
    conn.execute(
        """
        INSERT INTO device_claim_sessions (
            user_id, device_id, claim_token, expires_at_ms,
            claimed_at_ms, claimed_user_id, is_active, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (user_id, device_id, claim_token, expires_at_ms, now_ms, user_id, now_ms, now_ms),
    )
    conn.commit()
    row = conn.execute(
        """
        SELECT * FROM device_claim_sessions
        WHERE claim_token = ?
        """,
        (claim_token,),
    ).fetchone()
    return dict(row) if row else {}


def _get_active_claim_session(conn: Connection, device_id: str) -> Dict:
    now_ms = int(time.time() * 1000)
    row = conn.execute(
        """
        SELECT * FROM device_claim_sessions
        WHERE device_id = ? AND is_active = 1 AND expires_at_ms > ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (device_id, now_ms),
    ).fetchone()
    return dict(row) if row else {}


def _get_claim_session_by_token(conn: Connection, claim_token: str) -> Dict:
    now_ms = int(time.time() * 1000)
    row = conn.execute(
        """
        SELECT * FROM device_claim_sessions
        WHERE claim_token = ? AND is_active = 1 AND expires_at_ms > ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (claim_token, now_ms),
    ).fetchone()
    return dict(row) if row else {}


def _upsert_owner_profile(conn: Connection, user_id: int, payload: OwnerEnrollmentRequest) -> Dict:
    now_ms = int(time.time() * 1000)
    existing = conn.execute(
        """
        SELECT * FROM device_owner_profiles
        WHERE user_id = ? AND device_id = ?
        """,
        (user_id, payload.device_id),
    ).fetchone()
    params = (
        payload.owner_label,
        payload.embedding_version,
        int(payload.enrolled_at_ms),
        now_ms,
        1,
        int(payload.sample_count),
        float(payload.similarity_threshold),
        payload.embedding_backend,
        now_ms,
        user_id,
        payload.device_id,
    )
    if existing:
        conn.execute(
            """
            UPDATE device_owner_profiles
            SET owner_label = ?, embedding_version = ?, enrolled_at_ms = ?,
                last_sync_ms = ?, recognition_enabled = ?, sample_count = ?,
                similarity_threshold = ?, embedding_backend = ?, updated_at = ?
            WHERE user_id = ? AND device_id = ?
            """,
            params,
        )
    else:
        conn.execute(
            """
            INSERT INTO device_owner_profiles (
                owner_label, embedding_version, enrolled_at_ms, last_sync_ms,
                recognition_enabled, sample_count, similarity_threshold, embedding_backend,
                created_at, user_id, device_id, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.owner_label,
                payload.embedding_version,
                int(payload.enrolled_at_ms),
                now_ms,
                1,
                int(payload.sample_count),
                float(payload.similarity_threshold),
                payload.embedding_backend,
                now_ms,
                user_id,
                payload.device_id,
                now_ms,
            ),
        )
    conn.execute(
        """
        UPDATE devices
        SET identity_state = ?, identity_version = ?, owner_last_seen_ms = ?, updated_at = ?
        WHERE user_id = ? AND device_id = ?
        """,
        ("ready", payload.embedding_version, now_ms, now_ms, user_id, payload.device_id),
    )
    conn.commit()
    row = conn.execute(
        """
        SELECT * FROM device_owner_profiles
        WHERE user_id = ? AND device_id = ?
        """,
        (user_id, payload.device_id),
    ).fetchone()
    return dict(row) if row else {}


def _get_owner_profile(conn: Connection, user_id: int, device_id: str) -> Dict:
    row = conn.execute(
        """
        SELECT * FROM device_owner_profiles
        WHERE user_id = ? AND device_id = ?
        """,
        (user_id, device_id),
    ).fetchone()
    return dict(row) if row else {}


def _fetch_device_status(device_ip: str, timeout_sec: float = 2.0) -> Dict:
    url = f"http://{device_ip}/status"
    response = httpx.get(url, timeout=timeout_sec)
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict):
        return data
    raise ValueError("Invalid status payload")


def _post_device_json(device_ip: str, path: str, payload: Dict[str, object], timeout_sec: float = 4.0) -> Dict:
    url = f"http://{device_ip}{path}"
    response = httpx.post(url, json=payload, timeout=timeout_sec)
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict):
        return data
    raise ValueError("Invalid device payload")


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


def _bridge_user_from_request(request: Request, conn: Connection) -> Dict:
    token = str(request.headers.get("x-assistant-bridge-token") or "").strip()
    if not token or token != ASSISTANT_BRIDGE_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bridge token")
    user = _get_user_by_id(conn, int(ASSISTANT_BRIDGE_USER_ID))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bridge user not found")
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
        activation_required=not bool(user.get("is_configured", 0)),
        assessment_required=bool(user.get("is_configured", 0)) and not bool(_get_psychometric_profile(conn, int(user["id"]))),
        activation_path="/activate",
    )


@app.get("/activate", response_class=HTMLResponse)
def activation_page() -> HTMLResponse:
    return HTMLResponse(_activation_page_html())


@app.get("/api/auth/me", response_model=UserResponse)
def me_api(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> UserResponse:
    user = _parse_access_token(credentials, conn)
    return UserResponse(id=user["id"], username=user["username"], created_at=user["created_at"])


@app.get("/api/activation/state", response_model=ActivationProfileResponse)
def activation_state(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> ActivationProfileResponse:
    user = _parse_access_token(credentials, conn)
    profile = _get_activation_profile(conn, int(user["id"]))
    return _activation_response(conn, user, profile)


@app.post("/api/activation/complete", response_model=ActivationProfileResponse)
def activation_complete(
    payload: ActivationCompleteRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> ActivationProfileResponse:
    user = _parse_access_token(credentials, conn)
    preferred_name = str(payload.preferred_name or "").strip()
    if not preferred_name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="preferred_name is required")
    now_ms = int(time.time() * 1000)
    summary = str(payload.identity_summary or "").strip()
    if not summary:
        summary = f"{preferred_name} 是当前机器人的主要使用者，后续应按已确认身份持续服务。"
    profile_payload = {
        "preferred_name": preferred_name,
        "role_label": str(payload.role_label or "owner").strip() or "owner",
        "relation_to_robot": str(payload.relation_to_robot or "primary_user").strip() or "primary_user",
        "pronouns": str(payload.pronouns or "").strip(),
        "identity_summary": summary,
        "onboarding_notes": str(payload.onboarding_notes or "").strip(),
        "voice_intro_summary": str(payload.voice_intro_summary or "").strip(),
        "activation_version": str(payload.activation_version or "v1").strip() or "v1",
        "completed_at_ms": now_ms,
        "profile": payload.profile or {},
    }
    profile = _upsert_activation_profile(conn, int(user["id"]), profile_payload)
    _set_user_configured(conn, int(user["id"]), True)
    assistant_service.store.append_memory(
        int(user["id"]),
        title="activation_profile",
        content=(
            f"首次激活完成。称呼：{preferred_name}；角色：{profile_payload['role_label']}；"
            f"关系：{profile_payload['relation_to_robot']}；摘要：{summary}"
        ),
        tags=["activation", "identity", "profile"],
    )
    updated_user = _get_user_by_id(conn, int(user["id"]))
    return _activation_response(conn, updated_user, profile)


@app.post("/api/activation/identity/infer", response_model=ActivationIdentityInferResponse)
async def activation_identity_infer(
    payload: ActivationIdentityInferRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> ActivationIdentityInferResponse:
    user = _parse_access_token(credentials, conn)
    transcript = str(payload.transcript or "").strip()
    if not transcript:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="transcript is required")
    inference_input = {
        "transcript": transcript,
        "surface": str(payload.surface or "robot").strip() or "robot",
        "observed_name": str(payload.observed_name or "").strip(),
        "context": payload.context or {},
    }
    session_key = f"activation:{int(user['id'])}:infer:{int(time.time() * 1000)}"
    prompt = (
        f"{ACTIVATION_SYSTEM_PROMPT}\n\n"
        f"{IDENTITY_EXTRACTION_PROMPT}\n\n"
        f"输入数据：{json.dumps(inference_input, ensure_ascii=False)}"
    )
    try:
        raw = await assistant_service.gateway.send_message(session_key, prompt)
        parsed = _extract_json_block(raw)
    except OpenClawGatewayError:
        raw = ""
        parsed = _heuristic_activation_identity(
            transcript=transcript,
            observed_name=str(inference_input["observed_name"]),
        )
    preferred_name = str(parsed.get("preferred_name") or "").strip()
    if not preferred_name and inference_input["observed_name"]:
        preferred_name = str(inference_input["observed_name"]).strip()
    role_label = str(parsed.get("role_label") or "unknown").strip() or "unknown"
    relation_to_robot = str(parsed.get("relation_to_robot") or "unknown").strip() or "unknown"
    pronouns = str(parsed.get("pronouns") or "").strip()
    identity_summary = str(parsed.get("identity_summary") or "").strip()
    onboarding_notes = str(parsed.get("onboarding_notes") or "").strip()
    voice_intro_summary = str(parsed.get("voice_intro_summary") or "").strip()
    confidence = float(parsed.get("confidence") or 0.0)
    if not onboarding_notes and not confidence:
        onboarding_notes = "待确认：请在首次激活页再次确认身份信息。"
    return ActivationIdentityInferResponse(
        ok=True,
        preferred_name=preferred_name,
        role_label=role_label,
        relation_to_robot=relation_to_robot,
        pronouns=pronouns,
        identity_summary=identity_summary,
        onboarding_notes=onboarding_notes,
        voice_intro_summary=voice_intro_summary,
        confidence=max(0.0, min(1.0, confidence)),
        raw_json=parsed or {"raw_text": raw},
    )


@app.get("/api/activation/prompt-pack", response_model=ActivationPromptPackResponse)
def activation_prompt_pack(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> ActivationPromptPackResponse:
    _parse_access_token(credentials, conn)
    return ActivationPromptPackResponse(
        ok=True,
        system_prompt=ACTIVATION_SYSTEM_PROMPT,
        extraction_prompt=IDENTITY_EXTRACTION_PROMPT,
        preferred_mode=OPENCLAW_PREFERRED_MODE,
        preferred_code_model=OPENCLAW_PREFERRED_CODE_MODEL,
    )


@app.post("/api/activation/assessment/start", response_model=ActivationAssessmentStateResponse)
async def activation_assessment_start(
    payload: ActivationAssessmentStartRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> ActivationAssessmentStateResponse:
    user = _parse_access_token(credentials, conn)
    if not bool(user.get("is_configured", 0)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Identity activation must complete first")
    session_id, existing = _load_assessment_session(conn, int(user["id"]), active_only=True)
    if payload.reset or not existing:
        now_ms = int(time.time() * 1000)
        session_payload = build_initial_session(now_ms)
        session_payload["voice_mode"] = str(payload.voice_mode or "text").strip() or "text"
        activation = _get_activation_profile(conn, int(user["id"]))
        model_question = await _assessment_pick_model_question(int(user["id"]), activation, session_payload)
        if model_question:
            session_payload["last_question_id"] = str(model_question.get("id") or "")
            session_payload["latest_question"] = str(model_question.get("prompt") or "")
        session_id = _save_assessment_session(conn, int(user["id"]), session_payload, session_id=None)
        existing = session_payload
    device_online, _selected = _assessment_device_online(conn, int(user["id"]), payload.device_id)
    return _assessment_response(existing, device_online=device_online, exists=True)


@app.get("/api/activation/assessment/state", response_model=ActivationAssessmentStateResponse)
def activation_assessment_state(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> ActivationAssessmentStateResponse:
    user = _parse_access_token(credentials, conn)
    _session_id, session_payload = _load_assessment_session(conn, int(user["id"]), active_only=False)
    device_online, _selected = _assessment_device_online(conn, int(user["id"]))
    if not session_payload:
        completed = _get_psychometric_profile(conn, int(user["id"]))
        if completed:
            session_payload = {
                "status": "completed",
                "completed_at_ms": completed.get("completed_at_ms"),
                "updated_at_ms": completed.get("updated_at_ms"),
                "effective_turn_count": completed.get("conversation_count"),
                "turn_count": completed.get("conversation_count"),
                "type_code": completed.get("type_code"),
                "voice_mode": "idle",
                "voice_session_active": False,
                "final_result": completed,
            }
            return _assessment_response(session_payload, device_online=device_online, exists=True)
        return _assessment_response({}, device_online=device_online, exists=False)
    return _assessment_response(session_payload, device_online=device_online, exists=True)


@app.post("/api/activation/assessment/turn", response_model=ActivationAssessmentTurnResponse)
async def activation_assessment_turn(
    payload: ActivationAssessmentTurnRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> ActivationAssessmentTurnResponse:
    user = _parse_access_token(credentials, conn)
    session_id, session_payload = _load_assessment_session(conn, int(user["id"]), active_only=True)
    if not session_payload or session_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Assessment session not started")
    if str(session_payload.get("status") or "") == "completed":
        response = _assessment_response(session_payload, device_online=_assessment_device_online(conn, int(user["id"]), payload.device_id)[0], exists=True)
        return ActivationAssessmentTurnResponse(**response.model_dump(), question_changed=False, just_completed=False)
    answer_text = str(payload.answer or payload.transcript or "").strip()
    if not answer_text:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="answer is required")
    question_id = str(session_payload.get("last_question_id") or "").strip()
    question = QUESTION_MAP.get(question_id) or {
        "id": question_id or "ad-hoc",
        "pair": "EI",
        "prompt": str(session_payload.get("latest_question") or ""),
        "dimension_targets": ["E", "I"],
        "difficulty": 2,
        "followup_rules": [],
    }
    scoring = await _assessment_score_model(int(user["id"]), question, session_payload, answer_text)
    if not scoring:
        scoring = score_answer_heuristic(question, answer_text)
    merged = merge_scoring(session_payload, question, answer_text, scoring, int(time.time() * 1000))
    terminator = await _assessment_terminate_model(int(user["id"]), merged)
    if terminator.get("should_finish") and merged.get("status") != "completed":
        merged["status"] = "completed"
        merged["completed_at_ms"] = int(time.time() * 1000)
        merged["finish_reason"] = str(terminator.get("reason") or "model_finish")
        merged["final_result"] = build_final_profile(merged)
        merged["latest_question"] = ""
        merged["last_question_id"] = ""
    elif merged.get("status") != "completed" and terminator.get("missing_pair"):
        # Keep local selection authoritative but allow model to steer next pair when it is specific.
        suggested = await _assessment_pick_model_question(int(user["id"]), _get_activation_profile(conn, int(user["id"])), merged)
        if suggested:
            merged["latest_question"] = str(suggested.get("prompt") or merged.get("latest_question") or "")
            merged["last_question_id"] = str(suggested.get("id") or merged.get("last_question_id") or "")
    _append_assessment_turn_event(
        conn,
        int(user["id"]),
        int(session_id),
        int(merged.get("turn_count") or 0),
        str(question.get("id") or ""),
        str(question.get("prompt") or ""),
        answer_text,
        str(payload.transcript or answer_text),
        scoring,
    )
    if merged.get("status") == "completed":
        merged["final_result"] = _persist_assessment_completion(conn, int(user["id"]), merged)
    _save_assessment_session(conn, int(user["id"]), merged, session_id=int(session_id))
    device_online, _selected = _assessment_device_online(conn, int(user["id"]), payload.device_id)
    response = _assessment_response(merged, device_online=device_online, exists=True)
    return ActivationAssessmentTurnResponse(
        **response.model_dump(),
        question_changed=bool(response.latest_question),
        just_completed=bool(merged.get("status") == "completed"),
    )


@app.post("/api/activation/assessment/finish", response_model=ActivationAssessmentFinishResponse)
def activation_assessment_finish(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> ActivationAssessmentFinishResponse:
    user = _parse_access_token(credentials, conn)
    session_id, session_payload = _load_assessment_session(conn, int(user["id"]), active_only=True)
    if not session_payload or session_id is None:
        profile = _get_psychometric_profile(conn, int(user["id"]))
        if profile:
            return ActivationAssessmentFinishResponse(
                **_assessment_response(
                    {"status": "completed", "final_result": profile, "completed_at_ms": profile.get("completed_at_ms")},
                    device_online=_assessment_device_online(conn, int(user["id"]))[0],
                    exists=True,
                ).model_dump(),
                persisted=True,
            )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Assessment session not started")
    if session_payload.get("status") != "completed":
        session_payload["status"] = "completed"
        session_payload["completed_at_ms"] = int(time.time() * 1000)
        session_payload["finish_reason"] = str(session_payload.get("finish_reason") or "manual_finish")
        session_payload["final_result"] = build_final_profile(session_payload)
    session_payload["final_result"] = _persist_assessment_completion(conn, int(user["id"]), session_payload)
    _save_assessment_session(conn, int(user["id"]), session_payload, session_id=int(session_id))
    device_online, _selected = _assessment_device_online(conn, int(user["id"]))
    return ActivationAssessmentFinishResponse(
        **_assessment_response(session_payload, device_online=device_online, exists=True).model_dump(),
        persisted=True,
    )


@app.post("/api/activation/assessment/voice/start")
def activation_assessment_voice_start(
    payload: ActivationAssessmentVoiceRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> Dict[str, object]:
    user = _parse_access_token(credentials, conn)
    device_online, selected = _assessment_device_online(conn, int(user["id"]), payload.device_id)
    if not selected or not device_online:
        return {"ok": True, "device_online": False, "state": "offline", "detail": "Device offline; voice mode unavailable"}
    resolved_ip = str(selected.get("device_ip") or "").strip()
    try:
        response = _post_device_json(resolved_ip, "/voice/session/start", {"mode": str(payload.session_mode or "assessment")})
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    session_id, session_payload = _load_assessment_session(conn, int(user["id"]), active_only=True)
    if session_payload and session_id is not None:
        session_payload["voice_mode"] = "robot"
        session_payload["voice_session_active"] = True
        _save_assessment_session(conn, int(user["id"]), session_payload, session_id=int(session_id))
    return {"ok": True, "device_online": True, "state": response}


@app.post("/api/activation/assessment/voice/stop")
def activation_assessment_voice_stop(
    payload: ActivationAssessmentVoiceRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> Dict[str, object]:
    user = _parse_access_token(credentials, conn)
    device_online, selected = _assessment_device_online(conn, int(user["id"]), payload.device_id)
    if not selected or not device_online:
        return {"ok": True, "device_online": False, "state": "offline"}
    resolved_ip = str(selected.get("device_ip") or "").strip()
    try:
        response = _post_device_json(resolved_ip, "/voice/session/stop", {"mode": str(payload.session_mode or "assessment")})
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    session_id, session_payload = _load_assessment_session(conn, int(user["id"]), active_only=True)
    if session_payload and session_id is not None:
        session_payload["voice_session_active"] = False
        session_payload["voice_mode"] = "text"
        _save_assessment_session(conn, int(user["id"]), session_payload, session_id=int(session_id))
    return {"ok": True, "device_online": True, "state": response}


@app.get("/api/activation/personality/state", response_model=ActivationPersonalityStateResponse)
def activation_personality_state(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> ActivationPersonalityStateResponse:
    user = _parse_access_token(credentials, conn)
    return _personality_response(_get_personality_profile(conn, int(user["id"])))


@app.post("/api/activation/personality/infer", response_model=ActivationPersonalityInferResponse)
async def activation_personality_infer(
    payload: ActivationPersonalityInferRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> ActivationPersonalityInferResponse:
    user = _parse_access_token(credentials, conn)
    answers = [str(item).strip() for item in payload.answers or [] if str(item).strip()]
    transcript = str(payload.transcript or "").strip()
    merged_lines = []
    if transcript:
        merged_lines.append(transcript)
    merged_lines.extend(answers)
    if not merged_lines:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="answers or transcript is required")
    recent_rows = _list_chat_messages(conn, int(user["id"]), 12, session_key=build_session_key("desktop", int(user["id"])))
    recent_history = [
        {
            "sender": str(row["sender"] or ""),
            "text": str(row["text"] or ""),
            "timestamp_ms": int(row["timestamp_ms"] or 0),
        }
        for row in recent_rows[-8:]
        if str(row["text"] or "").strip()
    ]
    inference_input = {
        "identity": _get_activation_profile(conn, int(user["id"])),
        "surface": str(payload.surface or "desktop").strip() or "desktop",
        "answers": answers,
        "transcript": transcript,
        "context": payload.context or {},
        "recent_history": recent_history,
    }
    session_key = f"activation:{int(user['id'])}:personality:{int(time.time() * 1000)}"
    prompt = (
        f"{PERSONALITY_SYSTEM_PROMPT}\n\n"
        f"{PERSONALITY_EXTRACTION_PROMPT}\n\n"
        f"输入数据：{json.dumps(inference_input, ensure_ascii=False)}"
    )
    try:
        raw = await assistant_service.gateway.send_message(session_key, prompt)
        parsed = _extract_json_block(raw)
    except OpenClawGatewayError:
        raw = ""
        parsed = _heuristic_personality_profile("\n".join(merged_lines))
    summary = str(parsed.get("summary") or "").strip()
    response_style = str(parsed.get("response_style") or "").strip()
    care_style = str(parsed.get("care_style") or "").strip()
    traits = [str(item).strip() for item in parsed.get("traits") or [] if str(item).strip()]
    topics = [str(item).strip() for item in parsed.get("topics") or [] if str(item).strip()]
    boundaries = [str(item).strip() for item in parsed.get("boundaries") or [] if str(item).strip()]
    signals = [str(item).strip() for item in parsed.get("signals") or [] if str(item).strip()]
    confidence = max(0.0, min(1.0, float(parsed.get("confidence") or 0.0)))
    sample_count = max(len(answers), 1 if transcript else 0, int(parsed.get("sample_count") or 0))
    return ActivationPersonalityInferResponse(
        ok=True,
        summary=summary,
        response_style=response_style,
        care_style=care_style,
        traits=traits,
        topics=topics,
        boundaries=boundaries,
        signals=signals,
        confidence=confidence,
        sample_count=sample_count,
        inference_version=str(parsed.get("inference_version") or "v1").strip() or "v1",
        raw_json=parsed or {"raw_text": raw},
    )


@app.post("/api/activation/personality/complete", response_model=ActivationPersonalityStateResponse)
def activation_personality_complete(
    payload: ActivationPersonalityCompleteRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> ActivationPersonalityStateResponse:
    user = _parse_access_token(credentials, conn)
    summary = str(payload.summary or "").strip()
    if not summary:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="summary is required")
    profile = _upsert_personality_profile(
        conn,
        int(user["id"]),
        {
            "summary": summary,
            "response_style": str(payload.response_style or "").strip(),
            "care_style": str(payload.care_style or "").strip(),
            "traits": payload.traits or [],
            "topics": payload.topics or [],
            "boundaries": payload.boundaries or [],
            "signals": payload.signals or [],
            "confidence": max(0.0, min(1.0, float(payload.confidence or 0.0))),
            "sample_count": max(0, int(payload.sample_count or 0)),
            "inference_version": str(payload.inference_version or "v1").strip() or "v1",
            "profile": payload.profile or {},
        },
    )
    assistant_service.store.append_memory(
        int(user["id"]),
        title="personality_profile",
        content=(
            f"人格画像已确认。摘要：{summary}；回复风格：{str(payload.response_style or '').strip()}；"
            f"陪伴风格：{str(payload.care_style or '').strip()}；特征：{', '.join(payload.traits or [])}"
        ),
        tags=["activation", "personality", "profile"],
    )
    return _personality_response(profile)


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


@app.post("/api/device/claim", response_model=DeviceClaimResponse)
def device_claim(
    payload: DeviceClaimRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> DeviceClaimResponse:
    user = _parse_access_token(credentials, conn)
    device = _upsert_device(
        conn,
        int(user["id"]),
        payload.device_id,
        (payload.device_ip or "").strip() or None,
        (payload.ssid or "").strip() or None,
        (payload.device_mac or "").strip() or None,
    )
    claim = _create_claim_session(conn, int(user["id"]), payload.device_id)
    return DeviceClaimResponse(
        ok=True,
        device_id=payload.device_id,
        claim_token=str(claim.get("claim_token") or ""),
        expires_at_ms=int(claim.get("expires_at_ms") or 0),
        onboarding_state=str(device.get("onboarding_state") or "") or None,
        identity_state=str(device.get("identity_state") or "") or None,
    )


@app.get("/api/device/claim/status", response_model=DeviceClaimStatusResponse)
def device_claim_status(
    device_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> DeviceClaimStatusResponse:
    user = _parse_access_token(credentials, conn)
    device = _get_device(conn, int(user["id"]), device_id)
    owner = _get_device_owner(conn, device_id)
    claim = _get_active_claim_session(conn, device_id)
    selected = device or owner
    return DeviceClaimStatusResponse(
        ok=True,
        device_id=device_id,
        claimed=bool(owner),
        claimed_user_id=int(owner.get("user_id") or 0) if owner else None,
        onboarding_state=(str(selected.get("onboarding_state") or "").strip() or None) if selected else None,
        identity_state=(str(selected.get("identity_state") or "").strip() or None) if selected else None,
        claim_active=bool(claim),
        expires_at_ms=int(claim.get("expires_at_ms") or 0) if claim else None,
    )


@app.post("/api/device/owner/enrollment", response_model=OwnerEnrollmentResponse)
def owner_enrollment(
    payload: OwnerEnrollmentRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> OwnerEnrollmentResponse:
    user_id: Optional[int] = None
    if credentials is not None:
        try:
            user = _parse_access_token(credentials, conn)
            user_id = int(user["id"])
        except HTTPException:
            user_id = None
    if user_id is None:
        claim = _get_claim_session_by_token(conn, payload.claim_token)
        if not claim:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid claim token")
        user_id = int(claim["claimed_user_id"])
    user_row = _get_user_by_id(conn, int(user_id))
    if not bool(user_row.get("is_configured", 0)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Activation must complete before owner enrollment")
    owner = _get_device_owner(conn, payload.device_id)
    if owner and int(owner.get("user_id") or 0) != int(user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Device owned by another user")
    _upsert_device(conn, int(user_id), payload.device_id)
    _upsert_owner_profile(conn, int(user_id), payload)
    return OwnerEnrollmentResponse(
        ok=True,
        device_id=payload.device_id,
        embedding_version=payload.embedding_version,
        identity_state="ready",
    )


@app.get("/api/device/owner/status", response_model=OwnerStatusResponse)
def owner_status(
    device_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> OwnerStatusResponse:
    user = _parse_access_token(credentials, conn)
    profile = _get_owner_profile(conn, int(user["id"]), device_id)
    return OwnerStatusResponse(
        ok=True,
        device_id=device_id,
        enrolled=bool(profile),
        owner_label=(str(profile.get("owner_label") or "").strip() or None) if profile else None,
        embedding_version=(str(profile.get("embedding_version") or "").strip() or None) if profile else None,
        recognition_enabled=bool(int(profile.get("recognition_enabled") or 0)) if profile else True,
        last_sync_ms=int(profile.get("last_sync_ms") or 0) if profile else None,
        enrolled_at_ms=int(profile.get("enrolled_at_ms") or 0) if profile else None,
    )


@app.post("/api/device/owner/enrollment/start", response_model=OwnerEnrollmentStartResponse)
def owner_enrollment_start(
    payload: OwnerEnrollmentStartRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> OwnerEnrollmentStartResponse:
    user = _parse_access_token(credentials, conn)
    if not bool(user.get("is_configured", 0)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Activation must complete before face enrollment")
    selected = {}
    if payload.device_id:
        selected = _get_device(conn, int(user["id"]), payload.device_id)
    else:
        devices = _list_devices(conn, int(user["id"]))
        if devices:
            selected = devices[0]
    if not selected:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    resolved_ip = str(selected.get("device_ip") or "").strip()
    if not resolved_ip:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Device IP missing")
    try:
        state = _post_device_json(
            resolved_ip,
            "/owner/enrollment/start",
            {"owner_label": str(payload.owner_label or "owner").strip() or "owner", "claim_token": ""},
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return OwnerEnrollmentStartResponse(
        ok=True,
        device_id=str(selected.get("device_id") or payload.device_id or "unknown"),
        started=True,
        detail="Face enrollment requested on robot",
        state=state,
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
        return DeviceStatusResponse(
            device_id=device_id or "unbound",
            device_ip=None,
            device_mac=None,
            online=False,
            last_seen_ms=None,
            ssid=None,
            desired_ssid=None,
            network_mismatch=False,
            missing_profile=False,
            last_switch_reason=None,
            status=None,
            error="Device not bound yet",
        )

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
    surface: str = "desktop",
    session_key: Optional[str] = None,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> List[ChatMessageResponse]:
    user = _parse_access_token(credentials, conn)
    resolved_surface = normalize_surface(surface)
    resolved_session_key = session_key or build_session_key(resolved_surface, int(user["id"]))
    rows = _list_chat_messages(conn, int(user["id"]), limit, session_key=resolved_session_key)
    return [_chat_response_from_row(row) for row in rows]


@app.post("/api/chat/history", response_model=ChatMessageResponse)
async def chat_history_add(
    payload: ChatMessageRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> ChatMessageResponse:
    user = _parse_access_token(credentials, conn)
    if not payload.session_key:
        payload.session_key = build_session_key(normalize_surface(payload.surface), int(user["id"]))
    payload.surface = normalize_surface(payload.surface)
    msg_id = _insert_chat_message(conn, int(user["id"]), payload)
    response = ChatMessageResponse(
        id=msg_id,
        sender=payload.sender,
        text=payload.text,
        content_type=str(payload.content_type or "text"),
        attachments=payload.attachments or [],
        timestamp_ms=payload.timestamp_ms,
        surface=payload.surface,
        session_key=payload.session_key,
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


async def _assistant_send_impl(
    conn: Connection,
    user_id: int,
    payload: AssistantSendRequest,
) -> AssistantSendResponse:
    raw_text = str(payload.text or "").strip()
    if not raw_text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="text is required")
    merged_metadata = dict(payload.metadata or {})
    merged_metadata["user_profile"] = _build_assistant_identity_context(conn, int(user_id))
    response_payload = await assistant_service.send_message(
        conn,
        user_id=int(user_id),
        text=raw_text,
        surface=payload.surface,
        session_key=payload.session_key,
        device_id=payload.device_id,
        sender_id=payload.sender_id,
        attachments=payload.attachments or [],
        metadata=merged_metadata,
    )
    user_message = ChatMessageRequest(
        sender="user",
        text=raw_text,
        content_type="text",
        attachments=payload.attachments or [],
        timestamp_ms=int(response_payload["timestamp_ms"]) - 1,
        surface=str(response_payload["surface"]),
        session_key=str(response_payload["session_key"]),
    )
    bot_text = _sanitize_outbound_bot_text(str(response_payload.get("text") or ""))[0] or "我在。"
    bot_message = ChatMessageRequest(
        sender="assistant",
        text=bot_text,
        content_type="text",
        attachments=[],
        timestamp_ms=int(response_payload["timestamp_ms"]),
        surface=str(response_payload["surface"]),
        session_key=str(response_payload["session_key"]),
    )
    user_id_int = int(user_id)
    user_msg_id = _insert_chat_message(conn, user_id_int, user_message)
    bot_msg_id = _insert_chat_message(conn, user_id_int, bot_message)
    await event_manager.broadcast(
        {
            "type": "ChatMessage",
            "timestamp_ms": user_message.timestamp_ms,
            "payload": {
                "id": user_msg_id,
                "sender": user_message.sender,
                "text": user_message.text,
                "content_type": user_message.content_type,
                "attachments": user_message.attachments,
                "timestamp_ms": user_message.timestamp_ms,
                "surface": user_message.surface,
                "session_key": user_message.session_key,
            },
        }
    )
    await event_manager.broadcast(
        {
            "type": "ChatMessage",
            "timestamp_ms": bot_message.timestamp_ms,
            "payload": {
                "id": bot_msg_id,
                "sender": bot_message.sender,
                "text": bot_message.text,
                "content_type": bot_message.content_type,
                "attachments": [],
                "timestamp_ms": bot_message.timestamp_ms,
                "surface": bot_message.surface,
                "session_key": bot_message.session_key,
            },
        }
    )
    return AssistantSendResponse(
        ok=True,
        surface=str(response_payload["surface"]),
        session_key=str(response_payload["session_key"]),
        text=bot_text,
        tool_results=response_payload.get("tool_results") or [],
        timestamp_ms=int(response_payload["timestamp_ms"]),
    )


@app.post("/api/assistant/send", response_model=AssistantSendResponse)
async def assistant_send(
    payload: AssistantSendRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> AssistantSendResponse:
    user = _parse_access_token(credentials, conn)
    try:
        return await _assistant_send_impl(conn, int(user["id"]), payload)
    except OpenClawGatewayError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.post("/api/assistant/bridge/send", response_model=AssistantSendResponse)
async def assistant_bridge_send(
    payload: AssistantBridgeSendRequest,
    request: Request,
    conn: Connection = Depends(get_db),
) -> AssistantSendResponse:
    user = _bridge_user_from_request(request, conn)
    bridge_payload = AssistantSendRequest(
        text=payload.text,
        surface=payload.surface,
        session_key=payload.session_key,
        sender_id=payload.sender_id,
        metadata=payload.metadata,
    )
    try:
        return await _assistant_send_impl(conn, int(user["id"]), bridge_payload)
    except OpenClawGatewayError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.get("/api/assistant/session/status", response_model=AssistantSessionStatusResponse)
def assistant_session_status(
    surface: str = "desktop",
    session_key: Optional[str] = None,
    device_id: Optional[str] = None,
    sender_id: Optional[str] = None,
    limit: int = 30,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> AssistantSessionStatusResponse:
    user = _parse_access_token(credentials, conn)
    status_payload = assistant_service.get_session_status(
        conn,
        user_id=int(user["id"]),
        surface=surface,
        session_key=session_key,
        device_id=device_id,
        sender_id=sender_id,
    )
    rows = _list_chat_messages(conn, int(user["id"]), max(1, min(int(limit), 100)), session_key=str(status_payload["session_key"]))
    history = [_chat_response_from_row(row) for row in rows]
    return AssistantSessionStatusResponse(
        ok=True,
        surface=str(status_payload["surface"]),
        session_key=str(status_payload["session_key"]),
        last_message_ts_ms=status_payload.get("last_message_ts_ms"),
        message_count=int(status_payload.get("message_count") or 0),
        history=history,
    )


@app.post("/api/assistant/session/reset")
async def assistant_session_reset(
    payload: AssistantSessionResetRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> Dict[str, object]:
    user = _parse_access_token(credentials, conn)
    try:
        data = await assistant_service.reset_session(
            int(user["id"]),
            surface=payload.surface,
            session_key=payload.session_key,
            device_id=payload.device_id,
            sender_id=payload.sender_id,
        )
    except OpenClawGatewayError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return {"ok": True, **data}


@app.get("/api/assistant/todos", response_model=AssistantTodoListResponse)
def assistant_todos(
    state: Optional[str] = None,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> AssistantTodoListResponse:
    user = _parse_access_token(credentials, conn)
    items = [AssistantTodoItem(**item) for item in assistant_service.list_todos(int(user["id"]), state=state)]
    return AssistantTodoListResponse(ok=True, items=items)


@app.post("/api/assistant/todos", response_model=AssistantTodoItem)
def assistant_todos_create(
    payload: AssistantTodoCreateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> AssistantTodoItem:
    user = _parse_access_token(credentials, conn)
    item = assistant_service.create_todo(
        int(user["id"]),
        title=payload.title,
        details=payload.details,
        due_at_ms=payload.due_at_ms,
        tags=payload.tags,
    )
    return AssistantTodoItem(**item)


@app.patch("/api/assistant/todos/{todo_id}", response_model=AssistantTodoItem)
def assistant_todos_patch(
    todo_id: str,
    payload: AssistantTodoUpdateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> AssistantTodoItem:
    user = _parse_access_token(credentials, conn)
    try:
        item = assistant_service.update_todo(int(user["id"]), todo_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return AssistantTodoItem(**item)


@app.get("/api/assistant/memory/search", response_model=AssistantMemorySearchResponse)
def assistant_memory_search(
    q: str,
    limit: int = 10,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> AssistantMemorySearchResponse:
    user = _parse_access_token(credentials, conn)
    return AssistantMemorySearchResponse(
        ok=True,
        query=q,
        results=assistant_service.search_memory(int(user["id"]), q, limit=max(1, min(int(limit), 20))),
    )


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
    _ensure_llm_loaded()
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
async def llm_care(
    payload: CareRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> CareResponse:
    user = _parse_access_token(credentials, conn)
    context = _build_care_context(payload)
    assistant_prompt = (
        "请基于以下情绪上下文，用中文给出一句温和、简洁、可执行的回应，"
        "优先接住情绪，再给一个轻建议，最多一个问题。\n"
        f"{json.dumps(context, ensure_ascii=False)}"
    )
    try:
        assistant_reply = await assistant_service.send_message(
            conn,
            user_id=int(user["id"]),
            text=assistant_prompt,
            surface="desktop",
            session_key=f"desktop:{int(user['id'])}:care",
            metadata={
                "entrypoint": "llm_care",
                "current_emotion": payload.current_emotion,
                "user_profile": _build_assistant_identity_context(conn, int(user["id"])),
            },
        )
    except Exception:
        assistant_reply = {"text": "我在这里陪着你。"}
    safe_text, _rewritten = _sanitize_outbound_bot_text(str(assistant_reply.get("text") or ""))
    return CareResponse(
        text=safe_text or "我在这里陪着你。",
        followup_question="",
        style="warm",
    )


@app.post("/api/llm/care/stream")
async def llm_care_stream(
    payload: CareRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
):
    user = _parse_access_token(credentials, conn)
    context = _build_care_context(payload)
    assistant_prompt = (
        "请基于以下情绪上下文，用中文给出一句温和、简洁、可执行的回应，"
        "优先接住情绪，再给一个轻建议，最多一个问题。\n"
        f"{json.dumps(context, ensure_ascii=False)}"
    )
    try:
        assistant_reply = await assistant_service.send_message(
            conn,
            user_id=int(user["id"]),
            text=assistant_prompt,
            surface="desktop",
            session_key=f"desktop:{int(user['id'])}:care",
            metadata={
                "entrypoint": "llm_care_stream",
                "current_emotion": payload.current_emotion,
                "user_profile": _build_assistant_identity_context(conn, int(user["id"])),
            },
        )
        final_text = _sanitize_outbound_bot_text(str(assistant_reply.get("text") or ""))[0] or "我在这里陪着你。"
    except Exception:
        final_text = "我在这里陪着你。"

    async def event_stream():
        try:
            yield _sse("start", {"ok": True})
            sent_text = ""
            for char in final_text[:100]:
                delta = char
                sent_text += delta
                yield _sse("delta", {"text": delta})
                await asyncio.sleep(0)

            yield _sse(
                "done",
                {
                    "text": sent_text or final_text,
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
async def llm_daily_summary(
    payload: DailySummaryRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: Connection = Depends(get_db),
) -> DailySummaryResponse:
    user = _parse_access_token(credentials, conn)
    fallback_summary = "今天没有记录到明显情绪事件。需要的话，随时可以和我聊聊。"
    fallback_highlights = [
        "暂无明显触发事件",
        "整体状态较平稳",
        "需要时可随时记录感受",
    ]
    try:
        summary_text = await assistant_service.gateway.send_message(
            f"desktop:{int(user['id'])}:daily-summary",
            "请根据以下事件生成今天的情绪总结。第一行给 summary，后面 3 行每行一个 highlight。\n"
            f"{json.dumps(payload.events, ensure_ascii=False)}",
        )
    except Exception:
        summary_text = ""
    if not summary_text.strip():
        return DailySummaryResponse(summary=fallback_summary, highlights=fallback_highlights)
    lines = [line.strip("- ").strip() for line in summary_text.splitlines() if line.strip()]
    summary = lines[0] if lines else fallback_summary
    highlights = lines[1:4] if len(lines) > 1 else fallback_highlights
    return DailySummaryResponse(
        summary=summary,
        highlights=highlights or fallback_highlights,
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

