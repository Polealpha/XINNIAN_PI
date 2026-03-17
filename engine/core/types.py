from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AudioFrame:
    pcm_s16le: bytes
    sample_rate: int
    channels: int
    timestamp_ms: int
    seq: int
    device_id: str


@dataclass
class VideoFrame:
    format: str
    data: bytes
    width: int
    height: int
    timestamp_ms: int
    seq: int
    device_id: str


@dataclass
class UserSignal:
    type: str
    timestamp_ms: int
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EngineStatus:
    mode: str
    V: float
    A: float
    T: Optional[float]
    S: float
    cooldown_remaining_ms: int
    daily_trigger_count: int
    last_event_ts_ms: int
    health: Dict[str, bool]


@dataclass
class Event:
    type: str
    timestamp_ms: int
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CarePlan:
    text: str
    style: str
    motion: Dict[str, Any]
    emo: Dict[str, Any]
    followup_question: str
    reason: Dict[str, Any]
    policy: Dict[str, Any]
    decision: str = ""
    level: int = 0
    steps: List["ScriptStep"] = field(default_factory=list)
    cooldown_min: int = 0
    record_event: bool = False
    event_type: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "style": self.style,
            "motion": self.motion,
            "emo": self.emo,
            "followup_question": self.followup_question,
            "reason": self.reason,
            "policy": self.policy,
            "decision": self.decision,
            "level": self.level,
            "steps": [step.to_dict() for step in self.steps],
            "cooldown_min": self.cooldown_min,
            "record_event": self.record_event,
            "event_type": self.event_type,
        }


@dataclass
class ScriptStep:
    type: str
    payload: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type, "payload": self.payload}


@dataclass
class RiskFrame:
    ts_ms: int
    V: float
    A: float
    T: Optional[float]
    V_sub: Dict[str, float] = field(default_factory=dict)
    A_sub: Dict[str, float] = field(default_factory=dict)
    T_sub: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Context:
    device_id: str
    scene: str
    mode: str
    now_ms: int
    cooldown_until_ms: int
    daily_count: int
    daily_limit: int
    baseline: Dict[str, Any] = field(default_factory=dict)
    cfg: Dict[str, Any] = field(default_factory=dict)
