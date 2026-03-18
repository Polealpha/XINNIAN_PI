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
    activation_required: bool = False
    activation_path: str = "/activate"


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


class DeviceClaimRequest(BaseModel):
    device_id: str
    device_ip: Optional[str] = None
    device_mac: Optional[str] = None
    ssid: Optional[str] = None


class DeviceClaimResponse(BaseModel):
    ok: bool
    device_id: str
    claim_token: str
    expires_at_ms: int
    onboarding_state: Optional[str] = None
    identity_state: Optional[str] = None


class DeviceClaimStatusResponse(BaseModel):
    ok: bool
    device_id: str
    claimed: bool
    claimed_user_id: Optional[int] = None
    onboarding_state: Optional[str] = None
    identity_state: Optional[str] = None
    claim_active: bool = False
    expires_at_ms: Optional[int] = None


class OwnerEnrollmentRequest(BaseModel):
    device_id: str
    claim_token: str = ""
    owner_label: str = "owner"
    embedding_version: str
    sample_count: int = 0
    similarity_threshold: float = 0.0
    enrolled_at_ms: int
    embedding_backend: str = "face-hist-v1"


class OwnerEnrollmentResponse(BaseModel):
    ok: bool
    device_id: str
    embedding_version: str
    identity_state: str


class OwnerStatusResponse(BaseModel):
    ok: bool
    device_id: str
    enrolled: bool
    owner_label: Optional[str] = None
    embedding_version: Optional[str] = None
    recognition_enabled: bool = True
    last_sync_ms: Optional[int] = None
    enrolled_at_ms: Optional[int] = None


class OwnerEnrollmentStartRequest(BaseModel):
    device_id: Optional[str] = None
    owner_label: str = "owner"


class OwnerEnrollmentStartResponse(BaseModel):
    ok: bool
    device_id: str
    started: bool = True
    detail: str = ""
    state: dict = Field(default_factory=dict)


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
    surface: str = "desktop"
    session_key: Optional[str] = None


class ChatMessageResponse(BaseModel):
    id: int
    sender: str
    text: str
    content_type: str = "text"
    attachments: list[dict] = Field(default_factory=list)
    timestamp_ms: int
    surface: str = "desktop"
    session_key: Optional[str] = None


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


class AssistantSendRequest(BaseModel):
    text: str
    surface: str = "desktop"
    session_key: Optional[str] = None
    device_id: Optional[str] = None
    sender_id: Optional[str] = None
    attachments: list[dict] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class AssistantToolResult(BaseModel):
    name: str
    ok: bool = True
    detail: str = ""
    data: dict = Field(default_factory=dict)


class AssistantSendResponse(BaseModel):
    ok: bool
    surface: str
    session_key: str
    text: str
    tool_results: list[AssistantToolResult] = Field(default_factory=list)
    timestamp_ms: int


class AssistantSessionStatusResponse(BaseModel):
    ok: bool
    surface: str
    session_key: str
    last_message_ts_ms: Optional[int] = None
    message_count: int = 0
    history: list[ChatMessageResponse] = Field(default_factory=list)


class AssistantSessionResetRequest(BaseModel):
    surface: str = "desktop"
    session_key: Optional[str] = None
    device_id: Optional[str] = None
    sender_id: Optional[str] = None


class AssistantTodoItem(BaseModel):
    id: str
    title: str
    details: str = ""
    state: str = "open"
    created_at_ms: int
    updated_at_ms: int
    due_at_ms: Optional[int] = None
    tags: list[str] = Field(default_factory=list)


class AssistantTodoCreateRequest(BaseModel):
    title: str
    details: str = ""
    due_at_ms: Optional[int] = None
    tags: list[str] = Field(default_factory=list)


class AssistantTodoUpdateRequest(BaseModel):
    title: Optional[str] = None
    details: Optional[str] = None
    state: Optional[str] = None
    due_at_ms: Optional[int] = None
    tags: Optional[list[str]] = None


class AssistantTodoListResponse(BaseModel):
    ok: bool
    items: list[AssistantTodoItem] = Field(default_factory=list)


class AssistantMemorySearchResponse(BaseModel):
    ok: bool
    query: str
    results: list[dict] = Field(default_factory=list)


class AssistantBridgeSendRequest(BaseModel):
    sender_id: str
    text: str
    surface: str = "wecom"
    session_key: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class ActivationProfileResponse(BaseModel):
    ok: bool
    is_configured: bool
    activation_required: bool
    preferred_name: Optional[str] = None
    role_label: Optional[str] = None
    relation_to_robot: Optional[str] = None
    pronouns: Optional[str] = None
    identity_summary: Optional[str] = None
    onboarding_notes: Optional[str] = None
    voice_intro_summary: Optional[str] = None
    activation_version: str = "v1"
    completed_at_ms: Optional[int] = None
    preferred_mode: str = "cli"
    preferred_code_model: str = ""


class ActivationCompleteRequest(BaseModel):
    preferred_name: str
    role_label: str = "owner"
    relation_to_robot: str = "primary_user"
    pronouns: str = ""
    identity_summary: str = ""
    onboarding_notes: str = ""
    voice_intro_summary: str = ""
    profile: dict = Field(default_factory=dict)
    activation_version: str = "v1"


class ActivationIdentityInferRequest(BaseModel):
    transcript: str
    surface: str = "robot"
    observed_name: str = ""
    context: dict = Field(default_factory=dict)


class ActivationIdentityInferResponse(BaseModel):
    ok: bool
    preferred_name: str = ""
    role_label: str = "owner"
    relation_to_robot: str = "unknown"
    pronouns: str = ""
    identity_summary: str = ""
    onboarding_notes: str = ""
    voice_intro_summary: str = ""
    confidence: float = 0.0
    raw_json: dict = Field(default_factory=dict)


class ActivationPromptPackResponse(BaseModel):
    ok: bool
    system_prompt: str
    extraction_prompt: str
    preferred_mode: str = "cli"
    preferred_code_model: str = ""


class ActivationPersonalityStateResponse(BaseModel):
    ok: bool
    exists: bool = False
    summary: str = ""
    response_style: str = ""
    care_style: str = ""
    traits: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    boundaries: list[str] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    sample_count: int = 0
    inference_version: str = "v1"
    updated_at_ms: Optional[int] = None


class ActivationPersonalityInferRequest(BaseModel):
    transcript: str = ""
    answers: list[str] = Field(default_factory=list)
    surface: str = "desktop"
    context: dict = Field(default_factory=dict)


class ActivationPersonalityInferResponse(BaseModel):
    ok: bool
    summary: str = ""
    response_style: str = ""
    care_style: str = ""
    traits: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    boundaries: list[str] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    sample_count: int = 0
    inference_version: str = "v1"
    raw_json: dict = Field(default_factory=dict)


class ActivationPersonalityCompleteRequest(BaseModel):
    summary: str
    response_style: str = ""
    care_style: str = ""
    traits: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    boundaries: list[str] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    sample_count: int = 0
    inference_version: str = "v1"
    profile: dict = Field(default_factory=dict)
