from __future__ import annotations

from typing import Optional, Union

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=128)


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginEmailRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class LoginResponse(BaseModel):
    token: str
    refresh_token: str
    user_id: int
    is_configured: bool


class UserResponse(BaseModel):
    id: int
    username: str
    created_at: int


class ProfileResponse(BaseModel):
    id: int
    username: str
    display_name: str
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    location: Optional[str] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None


class ProfileUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    location: Optional[str] = None


class RealtimeScoresResponse(BaseModel):
    V: float
    A: float
    T: float
    S: float


class RealtimeRiskDetailResponse(BaseModel):
    V: float
    A: float
    T: float
    S: float
    timestamp_ms: int
    mode: Optional[str] = None
    detail: dict = Field(default_factory=dict)


class EmotionEventRequest(BaseModel):
    timestamp_ms: int
    type: str
    description: str
    V: float
    A: float
    T: float
    S: float
    intensity: Optional[int] = None
    source: Optional[str] = None


class EmotionEventResponse(BaseModel):
    id: int
    timestamp_ms: int
    type: str
    description: str
    V: float
    A: float
    T: float
    S: float
    intensity: Optional[int] = None
    source: Optional[str] = None


class DeviceInfoResponse(BaseModel):
    device_id: str
    device_ip: Optional[str] = None
    device_mac: Optional[str] = None
    ssid: Optional[str] = None
    last_seen_ms: Optional[int] = None


class DeviceStatusResponse(BaseModel):
    device_id: str
    device_ip: Optional[str] = None
    device_mac: Optional[str] = None
    online: bool
    last_seen_ms: Optional[int] = None
    ssid: Optional[str] = None
    desired_ssid: Optional[str] = None
    network_mismatch: bool = False
    missing_profile: bool = False
    last_switch_reason: Optional[str] = None
    status: Optional[dict] = None
    error: Optional[str] = None


class DeviceHeartbeatRequest(BaseModel):
    device_id: str
    device_ip: Optional[str] = None
    device_mac: Optional[str] = None
    ssid: Optional[str] = None
    rssi: Optional[int] = None
    last_seen_ms: Optional[int] = None
    status: Optional[dict] = None


class DeviceHeartbeatResponse(BaseModel):
    ok: bool
    updated: int
    desired_ssid: Optional[str] = None
    network_mismatch: bool = False
    missing_profile: bool = False
    last_switch_reason: Optional[str] = None
    profiles: list[dict] = Field(default_factory=list)


class ClientSessionHeartbeatRequest(BaseModel):
    client_type: str
    client_id: str
    current_ssid: Optional[str] = None
    client_ip: Optional[str] = None
    device_id: Optional[str] = None
    is_active: bool = True


class ClientSessionHeartbeatResponse(BaseModel):
    ok: bool
    desired_ssid: Optional[str] = None
    network_mismatch: bool = False
    missing_profile: bool = False
    last_switch_reason: Optional[str] = None


class ChatMessageRequest(BaseModel):
    sender: str
    text: str
    content_type: str = "text"
    attachments: list[dict] = Field(default_factory=list)
    timestamp_ms: int


class ChatMessageResponse(BaseModel):
    id: int
    sender: str
    text: str
    content_type: str = "text"
    attachments: list[dict] = Field(default_factory=list)
    timestamp_ms: int


class CareHistoryItem(BaseModel):
    sender: str
    text: str
    timestamp_ms: int


class CareRequest(BaseModel):
    current_emotion: str
    context: str
    current_ts_ms: Optional[int] = None
    history: list[Union[CareHistoryItem, str]] = []
    memory_summary: Optional[str] = None
    expression_label: Optional[str] = None
    expression_confidence: Optional[float] = None
    attachments: list[dict] = Field(default_factory=list)


class CareResponse(BaseModel):
    text: str
    followup_question: str = ""
    style: str = "warm"


class DailySummaryRequest(BaseModel):
    events: list[dict]


class DailySummaryResponse(BaseModel):
    summary: str
    highlights: list[str]


class EngineEventRequest(BaseModel):
    type: str
    timestamp_ms: int
    payload: dict


class EngineSignalRequest(BaseModel):
    type: str
    payload: Optional[dict] = None


class EngineSignal(BaseModel):
    type: str
    timestamp_ms: int
    payload: dict = {}


class EngineSignalPullRequest(BaseModel):
    limit: int = 10


class EngineSignalPullResponse(BaseModel):
    signals: list[EngineSignal]
