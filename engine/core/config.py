from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import json
import os


@dataclass
class ModesConfig:
    privacy_default: bool = False
    dnd_default: bool = False

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ModesConfig":
        data = data or {}
        return cls(
            privacy_default=bool(data.get("privacy_default", False)),
            dnd_default=bool(data.get("dnd_default", False)),
        )


@dataclass
class VideoConfig:
    fps_target: int = 3
    roi_size: int = 160
    risk_smoothing_sec: int = 10
    face_missing_grace_sec: int = 10
    face_missing_decay_sec: int = 5
    pitch_down_thr: float = 10.0
    pitch_span: float = 20.0
    gaze_thr: float = 0.45
    gaze_span: float = 0.35
    w_fatigue: float = 0.6
    w_attention: float = 0.4
    expression_enabled: bool = True
    expression_backend: str = "hybrid"
    expression_model_path: str = "models/ferplus/emotion-ferplus-8.onnx"
    expression_model_url: str = (
        "https://github.com/onnx/models/raw/main/validated/vision/body_analysis/emotion_ferplus/model/emotion-ferplus-8.onnx"
    )
    expression_mp_model_path: str = "models/mediapipe/face_landmarker.task"
    expression_mp_model_url: str = (
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
    )
    expression_allow_center_fallback: bool = False
    expression_min_confidence: float = 0.45
    w_expression: float = 0.25

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "VideoConfig":
        data = data or {}
        return cls(
            fps_target=int(data.get("fps_target", 3)),
            roi_size=int(data.get("roi_size", 160)),
            risk_smoothing_sec=int(data.get("risk_smoothing_sec", 10)),
            face_missing_grace_sec=int(data.get("face_missing_grace_sec", 10)),
            face_missing_decay_sec=int(data.get("face_missing_decay_sec", 5)),
            pitch_down_thr=float(data.get("pitch_down_thr", 10.0)),
            pitch_span=float(data.get("pitch_span", 20.0)),
            gaze_thr=float(data.get("gaze_thr", 0.45)),
            gaze_span=float(data.get("gaze_span", 0.35)),
            w_fatigue=float(data.get("w_fatigue", 0.6)),
            w_attention=float(data.get("w_attention", 0.4)),
            expression_enabled=bool(data.get("expression_enabled", True)),
            expression_backend=str(data.get("expression_backend", "hybrid")),
            expression_model_path=str(data.get("expression_model_path", "models/ferplus/emotion-ferplus-8.onnx")),
            expression_model_url=str(
                data.get(
                    "expression_model_url",
                    "https://github.com/onnx/models/raw/main/validated/vision/body_analysis/emotion_ferplus/model/emotion-ferplus-8.onnx",
                )
            ),
            expression_mp_model_path=str(
                data.get("expression_mp_model_path", "models/mediapipe/face_landmarker.task")
            ),
            expression_mp_model_url=str(
                data.get(
                    "expression_mp_model_url",
                    "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
                )
            ),
            expression_allow_center_fallback=bool(data.get("expression_allow_center_fallback", False)),
            expression_min_confidence=float(data.get("expression_min_confidence", 0.45)),
            w_expression=float(data.get("w_expression", 0.25)),
        )


@dataclass
class AudioConfig:
    sample_rate: int = 16000
    frame_ms: int = 20
    ring_buffer_minutes: int = 20
    vad_enabled: bool = True

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "AudioConfig":
        data = data or {}
        return cls(
            sample_rate=int(data.get("sample_rate", 16000)),
            frame_ms=int(data.get("frame_ms", 20)),
            ring_buffer_minutes=int(data.get("ring_buffer_minutes", 20)),
            vad_enabled=bool(data.get("vad_enabled", True)),
        )


@dataclass
class TriggerConfig:
    V_threshold: float = 0.7
    V_sustain_sec: int = 90
    A_threshold: float = 0.7
    A_sustain_sec: int = 80
    conj_threshold: float = 0.65
    conj_sustain_sec: int = 30
    peak_threshold: float = 0.85
    peak_window_sec: int = 300
    peak_min_gap_sec: int = 30
    peak_count: int = 3
    cooldown_min: int = 15
    daily_trigger_limit: int = 5
    rollback_sec: int = 60
    alpha_v: float = 0.2
    alpha_a: float = 0.3
    a_decay_sec: int = 5

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "TriggerConfig":
        data = data or {}
        return cls(
            V_threshold=float(data.get("V_threshold", 0.7)),
            V_sustain_sec=int(data.get("V_sustain_sec", 90)),
            A_threshold=float(data.get("A_threshold", 0.7)),
            A_sustain_sec=int(data.get("A_sustain_sec", 80)),
            conj_threshold=float(data.get("conj_threshold", 0.65)),
            conj_sustain_sec=int(data.get("conj_sustain_sec", 30)),
            peak_threshold=float(data.get("peak_threshold", 0.85)),
            peak_window_sec=int(data.get("peak_window_sec", 300)),
            peak_min_gap_sec=int(data.get("peak_min_gap_sec", 30)),
            peak_count=int(data.get("peak_count", 3)),
            cooldown_min=int(data.get("cooldown_min", 15)),
            daily_trigger_limit=int(data.get("daily_trigger_limit", 5)),
            rollback_sec=int(data.get("rollback_sec", 60)),
            alpha_v=float(data.get("alpha_v", 0.2)),
            alpha_a=float(data.get("alpha_a", 0.3)),
            a_decay_sec=int(data.get("a_decay_sec", 5)),
        )


@dataclass
class FusionConfig:
    wV: float = 0.5
    wA: float = 0.3
    wT: float = 0.2
    care_threshold: float = 0.7

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "FusionConfig":
        data = data or {}
        return cls(
            wV=float(data.get("wV", 0.5)),
            wA=float(data.get("wA", 0.3)),
            wT=float(data.get("wT", 0.2)),
            care_threshold=float(data.get("care_threshold", 0.7)),
        )


@dataclass
class AsrConfig:
    enabled: bool = True
    engine: str = "vosk"
    language: str = "zh"
    max_sec: int = 60
    model_path: str = ""
    model_name: str = "small"
    device: str = "cpu"
    compute_type: str = "int8"
    beam_size: int = 5
    vad_filter: bool = True
    api_key: Optional[str] = None
    api_key_env: str = "DASHSCOPE_API_KEY"
    base_websocket_api_url: str = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
    model: str = "paraformer-realtime-v2"
    semantic_punctuation_enabled: bool = True

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "AsrConfig":
        data = data or {}
        return cls(
            enabled=bool(data.get("enabled", True)),
            engine=str(data.get("engine", "vosk")),
            language=str(data.get("language", "zh")),
            max_sec=int(data.get("max_sec", 60)),
            model_path=str(data.get("model_path", "")),
            model_name=str(data.get("model_name", "small")),
            device=str(data.get("device", "cpu")),
            compute_type=str(data.get("compute_type", "int8")),
            beam_size=int(data.get("beam_size", 5)),
            vad_filter=bool(data.get("vad_filter", True)),
            api_key=data.get("api_key"),
            api_key_env=str(data.get("api_key_env", "DASHSCOPE_API_KEY")),
            base_websocket_api_url=str(
                data.get("base_websocket_api_url", "wss://dashscope.aliyuncs.com/api-ws/v1/inference")
            ),
            model=str(data.get("model", "paraformer-realtime-v2")),
            semantic_punctuation_enabled=bool(data.get("semantic_punctuation_enabled", True)),
        )


@dataclass
class LlmConfig:
    enabled: bool = True
    call_mode: str = "client_direct"
    provider: str = "auto"
    timeout_ms: int = 4000
    fallback_templates: bool = True
    daily_limit: int = 5
    api_key: Optional[str] = None
    api_key_env: str = "ARK_API_KEY"
    base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    model: str = "doubao-seed-2-0-mini-260215"
    temperature: float = 0.6
    top_p: float = 0.9
    max_completion_tokens: int = 512
    chat_history_messages: int = 8
    response_format: str = "json_object"
    web_search_enabled: bool = True
    web_search_daily_limit: int = 5
    web_search_high_value_only: bool = True
    web_search_news_default: bool = True
    web_search_timeout_ms: int = 8000
    web_search_model: str = "doubao-seed-2-0-mini-260215"
    news_fallback_provider: str = "google_news_rss"
    emotion_linked_search_enabled: bool = True
    emotion_linked_search_risk_threshold: float = 0.82
    emotion_linked_search_daily_cap: int = 1
    online_search_enabled: bool = True
    online_search_mode: str = "auto"
    online_search_timeout_ms: int = 8000
    online_search_model: str = "doubao-seed-2-0-mini-260215"
    online_search_require_supported_tool: bool = False
    tooling_enabled: bool = True
    tool_routing_mode: str = "rules_first"
    local_tools_enabled: bool = True
    local_tools_allowlist: List[str] = field(
        default_factory=lambda: [
            "datetime",
            "weather",
            "open_music",
            "music_search_play",
            "news_headline",
            "exchange_rate",
            "stock_quote",
            "system_tool",
        ]
    )
    weather_provider: str = "open_meteo"
    fx_provider: str = "frankfurter"
    stock_provider: str = "sina"
    alphavantage_api_key: str = ""
    system_tooling_enabled: bool = True
    system_tool_mode: str = "allowlist_direct"
    system_tool_allowlist_apps: List[str] = field(
        default_factory=lambda: ["netease_music", "browser", "notepad", "calculator"]
    )
    system_tool_allowlist_actions: List[str] = field(
        default_factory=lambda: [
            "open_app",
            "open_url",
            "music_search_play",
            "bilibili_search_play",
            "datetime",
            "weather",
            "news",
            "fx",
            "stock",
        ]
    )
    system_prompt_path: str = "engine/llm/prompts/care_prompt.md"
    summary_prompt_path: str = "engine/llm/prompts/daily_summary_prompt.md"

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "LlmConfig":
        data = data or {}
        return cls(
            enabled=bool(data.get("enabled", True)),
            call_mode=str(data.get("call_mode", "client_direct")),
            provider=str(data.get("provider", "auto")),
            timeout_ms=int(data.get("timeout_ms", 4000)),
            fallback_templates=bool(data.get("fallback_templates", True)),
            daily_limit=int(data.get("daily_limit", 5)),
            api_key=data.get("api_key"),
            api_key_env=str(data.get("api_key_env", "ARK_API_KEY")),
            base_url=str(data.get("base_url", "https://ark.cn-beijing.volces.com/api/v3")),
            model=str(data.get("model", "doubao-seed-2-0-mini-260215")),
            temperature=float(data.get("temperature", 0.6)),
            top_p=float(data.get("top_p", 0.9)),
            max_completion_tokens=int(data.get("max_completion_tokens", 512)),
            chat_history_messages=int(data.get("chat_history_messages", 8)),
            response_format=str(data.get("response_format", "json_object")),
            web_search_enabled=bool(data.get("web_search_enabled", data.get("online_search_enabled", True))),
            web_search_daily_limit=int(data.get("web_search_daily_limit", 5)),
            web_search_high_value_only=bool(data.get("web_search_high_value_only", True)),
            web_search_news_default=bool(data.get("web_search_news_default", True)),
            web_search_timeout_ms=int(data.get("web_search_timeout_ms", data.get("online_search_timeout_ms", 8000))),
            web_search_model=str(
                data.get("web_search_model", data.get("online_search_model", data.get("model", "doubao-seed-2-0-mini-260215")))
            ),
            news_fallback_provider=str(data.get("news_fallback_provider", "google_news_rss") or "google_news_rss"),
            emotion_linked_search_enabled=bool(data.get("emotion_linked_search_enabled", True)),
            emotion_linked_search_risk_threshold=float(data.get("emotion_linked_search_risk_threshold", 0.82)),
            emotion_linked_search_daily_cap=int(data.get("emotion_linked_search_daily_cap", 1)),
            online_search_enabled=bool(data.get("online_search_enabled", True)),
            online_search_mode=str(data.get("online_search_mode", "auto") or "auto"),
            online_search_timeout_ms=int(data.get("online_search_timeout_ms", 8000)),
            online_search_model=str(
                data.get("online_search_model", data.get("model", "doubao-seed-2-0-mini-260215"))
            ),
            online_search_require_supported_tool=bool(data.get("online_search_require_supported_tool", False)),
            tooling_enabled=bool(data.get("tooling_enabled", True)),
            tool_routing_mode=str(data.get("tool_routing_mode", "rules_first") or "rules_first"),
            local_tools_enabled=bool(data.get("local_tools_enabled", True)),
            local_tools_allowlist=[
                str(x).strip().lower()
                for x in (
                    data.get("local_tools_allowlist")
                    if isinstance(data.get("local_tools_allowlist"), list)
                    else [
                        "datetime",
                        "weather",
                        "open_music",
                        "music_search_play",
                        "news_headline",
                        "exchange_rate",
                        "stock_quote",
                        "system_tool",
                    ]
                )
                if str(x).strip()
            ],
            weather_provider=str(data.get("weather_provider", "open_meteo") or "open_meteo"),
            fx_provider=str(data.get("fx_provider", "frankfurter") or "frankfurter"),
            stock_provider=str(data.get("stock_provider", "sina") or "sina"),
            alphavantage_api_key=str(data.get("alphavantage_api_key", "") or ""),
            system_tooling_enabled=bool(data.get("system_tooling_enabled", True)),
            system_tool_mode=str(data.get("system_tool_mode", "allowlist_direct") or "allowlist_direct"),
            system_tool_allowlist_apps=[
                str(x).strip().lower()
                for x in (
                    data.get("system_tool_allowlist_apps")
                    if isinstance(data.get("system_tool_allowlist_apps"), list)
                    else ["netease_music", "browser", "notepad", "calculator"]
                )
                if str(x).strip()
            ],
            system_tool_allowlist_actions=[
                str(x).strip().lower()
                for x in (
                    data.get("system_tool_allowlist_actions")
                    if isinstance(data.get("system_tool_allowlist_actions"), list)
                    else [
                        "open_app",
                        "open_url",
                        "music_search_play",
                        "bilibili_search_play",
                        "datetime",
                        "weather",
                        "news",
                        "fx",
                        "stock",
                    ]
                )
                if str(x).strip()
            ],
            system_prompt_path=str(data.get("system_prompt_path", "engine/llm/prompts/care_prompt.md")),
            summary_prompt_path=str(
                data.get("summary_prompt_path", "engine/llm/prompts/daily_summary_prompt.md")
            ),
        )


@dataclass
class RuntimeConfig:
    risk_update_interval_ms: int = 1000

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "RuntimeConfig":
        data = data or {}
        return cls(
            risk_update_interval_ms=int(data.get("risk_update_interval_ms", 1000)),
        )


@dataclass
class FaceTrackingConfig:
    enabled: bool = True
    target_fps: int = 3
    detector: str = "mediapipe"
    min_face_area_ratio: float = 0.02
    max_face_area_ratio: float = 0.60
    dead_zone: float = 0.08
    ema_alpha: float = 0.30
    kp: float = 0.60
    turn_max: float = 0.60
    send_hz: int = 4
    ui_emit_hz: float = 4.0
    cmd_duration_ms: int = 250
    lost_frames_stop: int = 5
    multi_face_policy: str = "largest"
    scene_behavior: Dict[str, Dict[str, float]] = field(
        default_factory=lambda: {"desk": {"base": 0.0}, "home": {"base": 0.0}}
    )

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "FaceTrackingConfig":
        data = data or {}
        scene_behavior = data.get("scene_behavior") or {}
        merged_scene_behavior = {
            **cls().scene_behavior,
            **{k: {**cls().scene_behavior.get(k, {}), **v} for k, v in scene_behavior.items()},
        }
        return cls(
            enabled=bool(data.get("enabled", True)),
            target_fps=int(data.get("target_fps", 3)),
            detector=str(data.get("detector", "mediapipe")),
            min_face_area_ratio=float(data.get("min_face_area_ratio", 0.02)),
            max_face_area_ratio=float(data.get("max_face_area_ratio", 0.60)),
            dead_zone=float(data.get("dead_zone", 0.08)),
            ema_alpha=float(data.get("ema_alpha", 0.30)),
            kp=float(data.get("kp", 0.60)),
            turn_max=float(data.get("turn_max", 0.60)),
            send_hz=int(data.get("send_hz", 4)),
            ui_emit_hz=float(data.get("ui_emit_hz", 4.0)),
            cmd_duration_ms=int(data.get("cmd_duration_ms", 250)),
            lost_frames_stop=int(data.get("lost_frames_stop", 5)),
            multi_face_policy=str(data.get("multi_face_policy", "largest")),
            scene_behavior=merged_scene_behavior,
        )


@dataclass
class SummaryConfig:
    enabled: bool = True
    daily_time: str = "22:30"

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "SummaryConfig":
        data = data or {}
        return cls(
            enabled=bool(data.get("enabled", True)),
            daily_time=str(data.get("daily_time", "22:30")),
        )


@dataclass
class PolicyConfig:
    scene: str = "desk"
    history_window_sec: int = 1200
    legacy_multimodal_trigger_enabled: bool = False
    care_delivery_strategy: str = "policy"
    thresholds: Dict[str, float] = field(
        default_factory=lambda: {
            "nudge": 0.6,
            "care": 0.7,
            "guard": 0.9,
            "nudge_V": 0.7,
            "nudge_A": 0.7,
        }
    )
    sustained_low_activity: Dict[str, float] = field(
        default_factory=lambda: {
            "silence_min_sec": 900,
            "V_thr": 0.7,
            "attention_thr": 0.6,
        }
    )
    peak_to_silence: Dict[str, float] = field(
        default_factory=lambda: {
            "peak_z": 3.0,
            "peak_window_sec": 30,
            "silence_after_peak_sec": 45,
            "max_gap_sec": 120,
        }
    )
    expression_distress: Dict[str, Any] = field(
        default_factory=lambda: {
            "enabled": True,
            "min_confidence": 0.45,
            "negative_ids": [3, 4, 5, 6, 7],
            "nudge_thr": 0.40,
            "care_thr": 0.62,
            "hold_sec": 2.0,
        }
    )
    expression_non_neutral_trigger: Dict[str, Any] = field(
        default_factory=lambda: {
            "enabled": True,
            "min_confidence": 0.35,
            "hold_sec": 0.8,
            "cooldown_sec": 5.0,
        }
    )

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "PolicyConfig":
        data = data or {}
        thresholds = data.get("thresholds") or {}
        sustained = data.get("sustained_low_activity") or {}
        peak_to_silence = data.get("peak_to_silence") or {}
        expression_distress = data.get("expression_distress") or {}
        expression_non_neutral_trigger = data.get("expression_non_neutral_trigger") or {}
        return cls(
            scene=str(data.get("scene", "desk")),
            history_window_sec=int(data.get("history_window_sec", 1200)),
            legacy_multimodal_trigger_enabled=bool(data.get("legacy_multimodal_trigger_enabled", False)),
            care_delivery_strategy=str(data.get("care_delivery_strategy", "policy") or "policy"),
            thresholds={**cls().thresholds, **thresholds},
            sustained_low_activity={**cls().sustained_low_activity, **sustained},
            peak_to_silence={**cls().peak_to_silence, **peak_to_silence},
            expression_distress={**cls().expression_distress, **expression_distress},
            expression_non_neutral_trigger={
                **cls().expression_non_neutral_trigger,
                **expression_non_neutral_trigger,
            },
        )


@dataclass
class EngineConfig:
    modes: ModesConfig = field(default_factory=ModesConfig)
    video: VideoConfig = field(default_factory=VideoConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    trigger: TriggerConfig = field(default_factory=TriggerConfig)
    fusion: FusionConfig = field(default_factory=FusionConfig)
    asr: AsrConfig = field(default_factory=AsrConfig)
    llm: LlmConfig = field(default_factory=LlmConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    face_tracking: FaceTrackingConfig = field(default_factory=FaceTrackingConfig)
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    summary: SummaryConfig = field(default_factory=SummaryConfig)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "EngineConfig":
        data = data or {}
        return cls(
            modes=ModesConfig.from_dict(data.get("modes")),
            video=VideoConfig.from_dict(data.get("video")),
            audio=AudioConfig.from_dict(data.get("audio")),
            trigger=TriggerConfig.from_dict(data.get("trigger")),
            fusion=FusionConfig.from_dict(data.get("fusion")),
            asr=AsrConfig.from_dict(data.get("asr")),
            llm=LlmConfig.from_dict(data.get("llm")),
            runtime=RuntimeConfig.from_dict(data.get("runtime")),
            face_tracking=FaceTrackingConfig.from_dict(data.get("face_tracking")),
            policy=PolicyConfig.from_dict(data.get("policy")),
            summary=SummaryConfig.from_dict(data.get("summary")),
        )


def load_engine_config(path: str) -> EngineConfig:
    ext = os.path.splitext(path)[1].lower()
    with open(path, "r", encoding="utf-8-sig") as handle:
        if ext in (".yaml", ".yml"):
            try:
                import yaml  # type: ignore
            except ImportError as exc:
                raise RuntimeError("PyYAML is required to read YAML configs") from exc
            data = yaml.safe_load(handle) or {}
        else:
            data = json.load(handle)
    return EngineConfig.from_dict(data)
