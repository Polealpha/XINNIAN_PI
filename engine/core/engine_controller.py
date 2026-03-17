from __future__ import annotations

from datetime import datetime, time as dt_time, timedelta
import threading
from collections import deque
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .clock import now_ms
from .config import EngineConfig
from .event_bus import EventBus
from .types import (
    AudioFrame,
    CarePlan,
    Context,
    EngineStatus,
    Event,
    RiskFrame,
    ScriptStep,
    UserSignal,
    VideoFrame,
)
from ..audio.acoustic_features import extract_features
from ..audio.acoustic_risk import AcousticRiskScorer
from ..audio.ring_buffer import AudioRingBuffer
from ..audio.vad import SimpleVAD
from ..ingest.audio_ingestor import AudioIngestor
from ..ingest.video_ingestor import VideoIngestor
from ..llm.llm_responder import LLMResponder
from ..nlp.asr_module import AsrModule
from ..nlp.text_risk import TextRiskScorer
from ..policy.care_policy import CarePolicy
from ..summary.daily_summarizer import DailySummarizer
from ..trigger.fusion_scorer import FusionScorer
from ..trigger.trigger_manager import TriggerDecision, TriggerManager
from ..vision.face_roi import FaceROI
from ..vision.vision_risk import VisionRiskScorer


class EmotionEngine:
    def __init__(self) -> None:
        self._event_bus = EventBus()
        self._config = EngineConfig()
        self._running = False

        self._audio_ingestor: Optional[AudioIngestor] = None
        self._video_ingestor: Optional[VideoIngestor] = None
        self._ring_buffer: Optional[AudioRingBuffer] = None
        self._vad: Optional[SimpleVAD] = None
        self._acoustic_risk: Optional[AcousticRiskScorer] = None
        self._vision_risk: Optional[VisionRiskScorer] = None
        self._face_roi: Optional[FaceROI] = None
        self._trigger_manager: Optional[TriggerManager] = None
        self._fusion_scorer: Optional[FusionScorer] = None
        self._asr_module: Optional[AsrModule] = None
        self._text_risk: Optional[TextRiskScorer] = None
        self._care_policy: Optional[CarePolicy] = None
        self._llm: Optional[LLMResponder] = None
        self._summarizer: Optional[DailySummarizer] = None
        self._summary_events: List[Dict[str, object]] = []
        self._summary_state_min_interval_ms = 5 * 60 * 1000
        self._summary_last_state_sample_ms: int = 0
        self._summary_last_state_score: Optional[float] = None
        self._summary_last_state_expr: str = "unknown"
        self._summary_thread: Optional[threading.Thread] = None
        self._summary_stop = threading.Event()
        self._last_summary_date: Optional[str] = None

        self._mode = "normal"
        self._V = 0.0
        self._A = 0.0
        self._T: Optional[float] = None
        self._S = 0.0
        self._last_event_ts_ms = 0
        self._cooldown_until_ms = 0
        self._daily_trigger_count = 0
        self._daily_date: Optional[str] = None
        self._last_risk_emit_ms = 0
        self._last_audio_ts = 0
        self._last_video_ts = 0
        self._last_v_raw = 0.0
        self._last_a_raw = 0.0
        self._last_vad_active = False
        self._last_face_present = True
        self._health_timeout_ms = 5000
        self._history = deque()
        self._history_window_ms = 20 * 60 * 1000
        self._last_history_ts = 0
        self._silence_ms = 0
        self._last_a_sub: Dict[str, float] = {}
        self._last_v_sub: Dict[str, float] = {}
        self._last_t_sub: Dict[str, object] = {}
        self._rms_mean = 0.0
        self._rms_m2 = 0.0
        self._rms_count = 0
        self._device_id = ""
        self._policy_cfg: Dict[str, object] = {}
        self._care_delivery_strategy = "policy"
        self._expr_distress_since_ms: Optional[int] = None
        self._expr_non_neutral_since_ms: Optional[int] = None
        self._expr_non_neutral_last_fire_ms: int = 0

    def start(self, config: EngineConfig) -> None:
        self._config = config
        self._audio_ingestor = AudioIngestor(config.audio.sample_rate, 1)
        self._video_ingestor = VideoIngestor()
        self._ring_buffer = AudioRingBuffer(config.audio.ring_buffer_minutes)
        self._vad = SimpleVAD()
        self._acoustic_risk = AcousticRiskScorer()
        self._vision_risk = VisionRiskScorer(config.video)
        self._face_roi = FaceROI()
        self._trigger_manager = TriggerManager(config.trigger, config.video)
        self._fusion_scorer = FusionScorer(config.fusion)
        self._asr_module = AsrModule(config.asr)
        engine_root = Path(__file__).resolve().parents[1]
        self._text_risk = TextRiskScorer(str(engine_root / "nlp" / "lexicon_zh.txt"))
        self._care_policy = CarePolicy(str(engine_root / "policy" / "templates_zh.json"))
        self._llm = LLMResponder(config.llm)
        self._summarizer = DailySummarizer(self._llm)

        self._mode = "privacy" if config.modes.privacy_default else "normal"
        if config.modes.dnd_default:
            self._mode = "dnd"
        self._running = True
        self._history_window_ms = int(config.policy.history_window_sec * 1000)
        self._policy_cfg = {
            "scene": config.policy.scene,
            "cooldown_min": config.trigger.cooldown_min,
            "legacy_multimodal_trigger_enabled": config.policy.legacy_multimodal_trigger_enabled,
            "care_delivery_strategy": str(getattr(config.policy, "care_delivery_strategy", "policy") or "policy"),
            "thresholds": config.policy.thresholds,
            "sustained_low_activity": config.policy.sustained_low_activity,
            "peak_to_silence": config.policy.peak_to_silence,
            "expression_distress": config.policy.expression_distress,
            "expression_non_neutral_trigger": config.policy.expression_non_neutral_trigger,
            "fusion": {"wV": config.fusion.wV, "wA": config.fusion.wA, "wT": config.fusion.wT},
            "templates": self._care_policy.templates if self._care_policy else {},
        }
        self._care_delivery_strategy = str(
            self._policy_cfg.get("care_delivery_strategy", "policy") or "policy"
        ).lower()
        self._start_summary_scheduler()

    def stop(self) -> None:
        self._running = False
        self._summary_stop.set()
        if self._summary_thread and self._summary_thread.is_alive():
            self._summary_thread.join(timeout=1.0)

    def reset_session(self) -> None:
        if self._ring_buffer:
            self._ring_buffer.clear()
        if self._vad:
            self._vad.reset()
        if self._acoustic_risk:
            self._acoustic_risk.reset()
        if self._vision_risk:
            self._vision_risk.reset()
        if self._trigger_manager:
            self._trigger_manager.reset()
        if self._llm:
            self._llm.reset()
        self._summary_events = []
        self._summary_last_state_sample_ms = 0
        self._summary_last_state_score = None
        self._summary_last_state_expr = "unknown"
        self._V = 0.0
        self._A = 0.0
        self._T = None
        self._S = 0.0
        self._history.clear()
        self._silence_ms = 0
        self._last_a_sub = {}
        self._last_v_sub = {}
        self._last_t_sub = {}
        self._rms_mean = 0.0
        self._rms_m2 = 0.0
        self._rms_count = 0
        self._expr_distress_since_ms = None
        self._expr_non_neutral_since_ms = None
        self._expr_non_neutral_last_fire_ms = 0

    def push_audio(self, frame: AudioFrame) -> None:
        if not self._running:
            return
        if not self._audio_ingestor:
            return
        self._audio_ingestor.validate(frame)
        if frame.device_id:
            self._device_id = frame.device_id
        self._last_audio_ts = frame.timestamp_ms
        if self._mode == "privacy":
            return

        if self._ring_buffer:
            self._ring_buffer.add_frame(frame)
        features = extract_features(frame.pcm_s16le)
        vad_active = True
        if self._config.audio.vad_enabled and self._vad:
            vad_active = self._vad.update(features["rms"])
        self._last_vad_active = vad_active

        frame_ms = self._config.audio.frame_ms
        if vad_active:
            self._silence_ms = 0
        else:
            self._silence_ms += frame_ms

        a_raw = 0.0
        if self._acoustic_risk:
            a_raw = self._acoustic_risk.score(features["rms"], features["zcr"], vad_active)
        self._last_a_raw = a_raw
        self._last_a_sub = {
            "rms": float(features.get("rms", 0.0)),
            "zcr": float(features.get("zcr", 0.0)),
            "peak": float(features.get("peak", 0.0)),
            "silence_sec": float(self._silence_ms / 1000.0),
        }
        if vad_active:
            self._update_rms_baseline(float(features.get("rms", 0.0)))

        self._update_risk(frame.timestamp_ms, self._last_v_raw, a_raw, vad_active, self._last_face_present)

    def push_video(self, frame: VideoFrame) -> None:
        if not self._running:
            return
        if not self._video_ingestor:
            return
        self._video_ingestor.validate(frame)
        self._last_video_ts = frame.timestamp_ms
        if self._mode == "privacy":
            return

        face_present = True
        if self._face_roi:
            face_present = self._face_roi.process(frame).get("face_present", True)

        v_raw = 0.0
        if self._vision_risk:
            # Do not let Haar ROI gate FER/FaceMesh inference; it is noisy on low-light MJPEG.
            # Always run vision model, then reconcile with ROI hint.
            v_raw, v_sub = self._vision_risk.score(frame, True)
            merged_v_sub = dict(v_sub or {})
            merged_v_sub["roi_face_present"] = 1.0 if face_present else 0.0
            model_face_ok = float(merged_v_sub.get("face_ok", 0.0))
            self._last_face_present = bool(face_present or model_face_ok > 0.5)
            self._last_v_sub = merged_v_sub
        else:
            self._last_face_present = face_present
        self._last_v_raw = v_raw

        self._update_risk(
            frame.timestamp_ms,
            v_raw,
            self._last_a_raw,
            self._last_vad_active,
            self._last_face_present,
        )

    def push_user_signal(self, signal: UserSignal) -> None:
        if not self._running:
            return
        if signal.type == "privacy_on":
            self._mode = "privacy"
            self.reset_session()
            return
        if signal.type == "privacy_off":
            self._mode = "normal"
            return
        if signal.type == "do_not_disturb_on":
            self._mode = "dnd"
            return
        if signal.type == "do_not_disturb_off":
            self._mode = "normal"
            return
        if signal.type == "manual_care":
            self._manual_care(signal.timestamp_ms)
            return
        if signal.type == "config_update":
            payload = signal.payload if isinstance(signal.payload, dict) else {}
            if "cooldown_min" in payload:
                try:
                    cooldown_min = int(payload.get("cooldown_min", self._config.trigger.cooldown_min))
                    if cooldown_min > 0:
                        self._config.trigger.cooldown_min = cooldown_min
                        self._policy_cfg["cooldown_min"] = cooldown_min
                except Exception:
                    pass
            if "daily_trigger_limit" in payload:
                try:
                    daily_limit = int(
                        payload.get("daily_trigger_limit", self._config.trigger.daily_trigger_limit)
                    )
                    if daily_limit > 0:
                        self._config.trigger.daily_trigger_limit = daily_limit
                except Exception:
                    pass
            if "care_delivery_strategy" in payload:
                strategy = str(payload.get("care_delivery_strategy", "policy") or "policy").strip().lower()
                if strategy in {"policy", "voice_all_day", "popup_all_day"}:
                    self._care_delivery_strategy = strategy
                    self._policy_cfg["care_delivery_strategy"] = strategy
            return
        if signal.type == "daily_summary":
            events = signal.payload.get("events") if isinstance(signal.payload, dict) else None
            if not isinstance(events, list):
                events = None
            self._emit_daily_summary(signal.timestamp_ms, events)
            return
        if signal.type == "manual_mark":
            self._emit("UserMark", signal.timestamp_ms, signal.payload)

    def get_status(self) -> EngineStatus:
        now = now_ms()
        cooldown_remaining = max(0, self._cooldown_until_ms - now)
        health = {
            "audio_ok": now - self._last_audio_ts < self._health_timeout_ms,
            "video_ok": now - self._last_video_ts < self._health_timeout_ms,
            "esp_connected": True,
        }
        return EngineStatus(
            mode=self._mode,
            V=self._V,
            A=self._A,
            T=self._T,
            S=self._S,
            cooldown_remaining_ms=cooldown_remaining,
            daily_trigger_count=self._daily_trigger_count,
            last_event_ts_ms=self._last_event_ts_ms,
            health=health,
        )

    def get_emotion_snapshot(self) -> Dict[str, object]:
        expr_id = int(self._last_v_sub.get("expression_class_id", -1))
        expr_conf = float(self._last_v_sub.get("expression_confidence", 0.0))
        return {
            "mode": self._mode,
            "V": self._V,
            "A": self._A,
            "T": self._T,
            "S": self._S,
            "expression_id": expr_id,
            "expression_modality": self._expression_label_from_id(expr_id),
            "expression_confidence": expr_conf,
            "V_sub": dict(self._last_v_sub),
            "A_sub": dict(self._last_a_sub),
            "T_sub": dict(self._last_t_sub),
        }

    def on_event(self, callback: Callable[[Event], None]) -> None:
        self._event_bus.subscribe(callback)

    def _update_risk(
        self,
        timestamp_ms: int,
        v_raw: float,
        a_raw: float,
        vad_active: bool,
        face_present: bool,
    ) -> None:
        if not self._trigger_manager or not self._fusion_scorer:
            return
        self._refresh_daily_counter(timestamp_ms)

        decision = self._trigger_manager.update(
            timestamp_ms=timestamp_ms,
            v_raw=v_raw,
            a_raw=a_raw,
            vad_active=vad_active,
            face_present=face_present,
        )
        self._V = decision.v
        self._A = decision.a
        self._T = None
        self._last_t_sub = {}
        self._S = self._fusion_scorer.score(self._V, self._A, None)

        if timestamp_ms - self._last_risk_emit_ms >= self._config.runtime.risk_update_interval_ms:
            self._last_risk_emit_ms = timestamp_ms
            self._emit(
                "RiskUpdate",
                timestamp_ms,
                {
                    "V": self._V,
                    "A": self._A,
                    "T": self._T,
                    "S": self._S,
                    "mode": self._mode,
                    "detail": {
                        "V_sub": self._last_v_sub,
                        "A_sub": self._last_a_sub,
                        "T_sub": self._last_t_sub,
                    },
                },
            )
            self._append_history(timestamp_ms)

        self._record_state_checkpoint(timestamp_ms)

        legacy_enabled = bool(self._policy_cfg.get("legacy_multimodal_trigger_enabled", False))
        if decision.should_trigger and legacy_enabled:
            if self._allow_trigger(timestamp_ms):
                self._handle_trigger(timestamp_ms, decision)
            else:
                self._emit(
                    "TriggerCandidate",
                    timestamp_ms,
                    {"reason": decision.reason, "V": self._V, "A": self._A},
                )
            return

        expr_reason = self._expression_trigger_reason(timestamp_ms)
        if expr_reason:
            expr_decision = TriggerDecision(
                should_trigger=True,
                reason=expr_reason,
                v=self._V,
                a=self._A,
                v_raw=v_raw,
                a_raw=a_raw,
                peak_v_count=decision.peak_v_count,
                peak_a_count=decision.peak_a_count,
            )
            if self._allow_trigger(timestamp_ms):
                self._handle_trigger(timestamp_ms, expr_decision)
            else:
                self._emit(
                    "TriggerCandidate",
                    timestamp_ms,
                    {"reason": expr_reason, "V": self._V, "A": self._A},
                )

    def _expression_trigger_reason(self, timestamp_ms: int) -> Optional[str]:
        # Preferred trigger: any non-neutral expression (id != 0) with enough confidence.
        cfg_any = dict(self._policy_cfg.get("expression_non_neutral_trigger", {}) or {})
        if bool(cfg_any.get("enabled", False)):
            conf = float(self._last_v_sub.get("expression_confidence", 0.0))
            expr_id = int(self._last_v_sub.get("expression_class_id", -1))
            min_conf = float(cfg_any.get("min_confidence", 0.35))
            hold_ms = int(float(cfg_any.get("hold_sec", 0.8)) * 1000)
            cooldown_ms = int(float(cfg_any.get("cooldown_sec", 5.0)) * 1000)
            ok = expr_id > 0 and conf >= min_conf
            if not ok:
                self._expr_non_neutral_since_ms = None
            else:
                if self._expr_non_neutral_since_ms is None:
                    self._expr_non_neutral_since_ms = timestamp_ms
                    return None
                if timestamp_ms - self._expr_non_neutral_since_ms >= hold_ms:
                    if timestamp_ms - self._expr_non_neutral_last_fire_ms >= cooldown_ms:
                        self._expr_non_neutral_last_fire_ms = timestamp_ms
                        self._expr_non_neutral_since_ms = timestamp_ms
                        return "ExpressionNonNeutral"
            # New policy enabled: skip legacy expression distress path.
            return None

        # Legacy trigger path (kept for compatibility).
        cfg = dict(self._policy_cfg.get("expression_distress", {}) or {})
        if not bool(cfg.get("enabled", True)):
            self._expr_distress_since_ms = None
            return None

        conf = float(self._last_v_sub.get("expression_confidence", 0.0))
        expr_id = int(self._last_v_sub.get("expression_class_id", -1))
        expr_risk = float(self._last_v_sub.get("expression_risk", 0.0))
        min_conf = float(cfg.get("min_confidence", 0.45))
        negative_ids = {int(v) for v in (cfg.get("negative_ids", [3, 4, 5, 6, 7]) or [])}
        nudge_thr = float(cfg.get("nudge_thr", 0.40))
        hold_ms = int(float(cfg.get("hold_sec", 2.0)) * 1000)

        ok = conf >= min_conf and expr_id in negative_ids and expr_risk >= nudge_thr
        if not ok:
            self._expr_distress_since_ms = None
            return None

        if self._expr_distress_since_ms is None:
            self._expr_distress_since_ms = timestamp_ms
            return None
        if timestamp_ms - self._expr_distress_since_ms < hold_ms:
            return None
        self._expr_distress_since_ms = timestamp_ms
        return "ExpressionDistress"

    def _handle_trigger(self, timestamp_ms: int, decision) -> None:
        self._cooldown_until_ms = timestamp_ms + self._config.trigger.cooldown_min * 60 * 1000
        self._daily_trigger_count += 1
        self._emit(
            "TriggerFired",
            timestamp_ms,
            {"reason": decision.reason, "V": decision.v, "A": decision.a},
        )

        transcript = ""
        if self._asr_module and self._ring_buffer:
            rollback_sec = int(self._config.trigger.rollback_sec)
            if str(decision.reason) == "ExpressionNonNeutral":
                rollback_sec = 30
            if rollback_sec > 0:
                pcm, start_ts, end_ts = self._ring_buffer.get_last_ms(rollback_sec * 1000)
                if pcm:
                    transcript = self._asr_module.transcribe(pcm, self._config.audio.sample_rate)
                    self._emit(
                        "TranscriptReady",
                        timestamp_ms,
                        {"transcript": transcript, "start_ts": start_ts, "end_ts": end_ts},
                    )

        t_score = None
        tags = []
        summary = ""
        expr_id = int(self._last_v_sub.get("expression_class_id", -1))
        expr_conf = float(self._last_v_sub.get("expression_confidence", 0.0))
        expr_labels = [
            "neutral",
            "happiness",
            "surprise",
            "sadness",
            "anger",
            "disgust",
            "fear",
            "contempt",
        ]
        expr_trigger_cfg = dict(self._policy_cfg.get("expression_non_neutral_trigger", {}) or {})
        expr_tag_min_conf = float(expr_trigger_cfg.get("min_confidence", 0.22))
        if 0 <= expr_id < len(expr_labels) and expr_conf >= expr_tag_min_conf:
            tags.append(f"expr:{expr_labels[expr_id]}")
        if self._text_risk:
            t_score, text_tags, summary = self._text_risk.score(transcript)
            tags.extend(text_tags)

        s_final = self._fusion_scorer.score(decision.v, decision.a, t_score)
        self._T = t_score
        self._S = s_final
        self._last_t_sub = {"tags": tags, "summary": summary, "transcript": transcript}

        care_plan = None
        frame = RiskFrame(
            ts_ms=timestamp_ms,
            V=decision.v,
            A=decision.a,
            T=t_score,
            V_sub=self._last_v_sub,
            A_sub=self._last_a_sub,
            T_sub=self._last_t_sub,
        )
        if self._care_policy:
            baseline = {
                "rms_mean": self._rms_mean,
                "rms_std": self._rms_std(),
            }
            if self._vision_risk and hasattr(self._vision_risk, "baseline"):
                baseline.update(self._vision_risk.baseline())
            ctx = Context(
                device_id=self._device_id or "unknown",
                scene=self._config.policy.scene,
                mode="privacy_on" if self._mode == "privacy" else ("quiet" if self._mode == "dnd" else "normal"),
                now_ms=timestamp_ms,
                cooldown_until_ms=self._cooldown_until_ms,
                daily_count=self._daily_trigger_count,
                daily_limit=self._config.trigger.daily_trigger_limit,
                baseline=baseline,
                cfg=self._policy_cfg,
            )
            care_plan = self._care_policy.decide(ctx, frame, list(self._history))
        care_plan = self._maybe_llm_rewrite(care_plan, tags, transcript, summary, frame)
        if (
            str(decision.reason) == "ExpressionNonNeutral"
            and (not care_plan or care_plan.decision not in {"NUDGE", "CARE", "GUARD"})
        ):
            care_plan = self._build_expression_non_neutral_plan(
                timestamp_ms=timestamp_ms,
                frame=frame,
                transcript=transcript,
                summary=summary,
                tags=tags,
                t_score=t_score,
                s_final=s_final,
                decision=decision,
            )
        if care_plan and care_plan.decision in {"NUDGE", "CARE", "GUARD"}:
            if not self._is_llm_sourced(care_plan):
                self._emit(
                    "CarePlanSkipped",
                    timestamp_ms,
                    {"reason": "llm_required_unavailable", "decision": care_plan.decision},
                )
                self._append_history(timestamp_ms)
                self._record_summary_event(timestamp_ms, tags, summary, transcript, decision, t_score, s_final)
                return
            self._last_event_ts_ms = timestamp_ms
            delivery_mode = self._care_delivery_mode(timestamp_ms)
            self._emit(
                "CarePlanReady",
                timestamp_ms,
                {
                    "care_plan": care_plan.to_dict(),
                    "delivery_mode": delivery_mode,
                    "reason": {
                        "V": decision.v,
                        "A": decision.a,
                        "T": t_score,
                        "S": s_final,
                        "pattern": care_plan.reason.get("pattern") if care_plan.reason else None,
                        "tags": tags,
                    },
                    "detail": {
                        "V_sub": frame.V_sub,
                        "A_sub": frame.A_sub,
                        "T_sub": frame.T_sub,
                    },
                },
            )
        self._append_history(timestamp_ms)
        self._record_summary_event(timestamp_ms, tags, summary, transcript, decision, t_score, s_final)

    def _manual_care(self, timestamp_ms: int) -> None:
        expr_id = int(self._last_v_sub.get("expression_class_id", -1))
        expr_conf = float(self._last_v_sub.get("expression_confidence", 0.0))
        expr_label = self._expression_label_from_id(expr_id)
        transcript_summary = str(self._last_t_sub.get("summary", "") or "").strip()
        if not transcript_summary:
            transcript_summary = str(self._last_t_sub.get("transcript", "") or "").strip()[:120]
        recent_events = []
        for event in self._summary_events[-6:]:
            summary_text = str(event.get("summary", "")).strip()
            if not summary_text:
                continue
            recent_events.append(summary_text)
        default_text = "我在这儿，想先从今天最让你挂心的一件事聊起吗？"
        followup = ""
        style = "warm"
        content_source = "manual_fallback"

        if self._llm and self._llm.enabled:
            context = {
                "scene": self._config.policy.scene,
                "decision": "CARE",
                "level": 2,
                "input_type": "manual_trigger",
                "trigger": {"source": "manual_care_button"},
                "expression_modality": {
                    "label": expr_label,
                    "confidence": expr_conf,
                    "note": "这是算法观测到的情绪信号，不是用户原话",
                },
                "risk": {"V": self._V, "A": self._A, "T": self._T, "S": self._S, "pattern": "manual"},
                "risk_detail": {
                    "V_sub": dict(self._last_v_sub),
                    "A_sub": dict(self._last_a_sub),
                    "T_sub": dict(self._last_t_sub),
                },
                "tags": [f"expr:{expr_label}"] if expr_label not in {"unknown"} else [],
                "transcript_summary": transcript_summary,
                "day_snapshot": {
                    "event_count": len(self._summary_events),
                    "recent_events": recent_events,
                },
                "constraints": "这是手动触发主动关怀；回复≤100字；先共情再给一个轻建议，最多一个问题。",
            }
            reply = self._llm.generate_care_reply(context) or {}
            llm_text = str(reply.get("text", "")).strip()
            if llm_text:
                default_text = llm_text
                content_source = "llm"
            followup = str(reply.get("followup_question", "")).strip()
            style = str(reply.get("style", "warm")).strip() or "warm"

        steps = [ScriptStep("SAY", {"text": default_text, "voice": "warm", "priority": 2})]
        if followup:
            steps.append(ScriptStep("WAIT", {"duration_ms": 700}))
            steps.append(ScriptStep("SAY", {"text": followup, "voice": "warm", "priority": 1}))
        care_plan = CarePlan(
            text=default_text,
            style=style,
            motion={},
            emo={},
            followup_question=followup,
            reason={"pattern": "manual", "V": self._V, "A": self._A, "T": self._T, "S": self._S},
            policy={"source": "manual", "content_source": content_source},
            decision="CARE",
            level=2,
            steps=steps,
            cooldown_min=self._config.trigger.cooldown_min,
            record_event=True,
            event_type="MANUAL_CARE",
        )
        self._emit(
            "CarePlanReady",
            timestamp_ms,
            {
                "care_plan": care_plan.to_dict(),
                "delivery_mode": self._care_delivery_mode(timestamp_ms),
                "reason": {"pattern": "manual"},
                "detail": {
                    "V_sub": dict(self._last_v_sub),
                    "A_sub": dict(self._last_a_sub),
                    "T_sub": dict(self._last_t_sub),
                },
            },
        )

    def _care_delivery_mode(self, timestamp_ms: int) -> str:
        strategy = str(self._care_delivery_strategy or "policy").lower()
        if strategy == "voice_all_day":
            return "voice"
        if strategy == "popup_all_day":
            return "text"
        dt = datetime.fromtimestamp(timestamp_ms / 1000.0)
        # Night mode: 21:00-07:59, prefer voice delivery.
        if dt.hour >= 21 or dt.hour < 8:
            return "voice"
        return "text"

    def _expression_label_from_id(self, expr_id: int) -> str:
        labels = [
            "neutral",
            "happiness",
            "surprise",
            "sadness",
            "anger",
            "disgust",
            "fear",
            "contempt",
        ]
        if 0 <= int(expr_id) < len(labels):
            return labels[int(expr_id)]
        return "unknown"

    def _build_expression_non_neutral_plan(
        self,
        timestamp_ms: int,
        frame: RiskFrame,
        transcript: str,
        summary: str,
        tags: List[str],
        t_score: Optional[float],
        s_final: float,
        decision,
    ) -> CarePlan:
        expr_id = int(frame.V_sub.get("expression_class_id", -1))
        expr_conf = float(frame.V_sub.get("expression_confidence", 0.0))
        expr_label = self._expression_label_from_id(expr_id)
        expr_label_zh = {
            "happiness": "开心",
            "surprise": "惊讶",
            "sadness": "低落",
            "anger": "烦躁",
            "disgust": "不适",
            "fear": "紧张",
            "contempt": "不耐烦",
            "neutral": "平静",
            "unknown": "起伏",
        }.get(expr_label, "起伏")
        default_text = f"我看到你现在有些{expr_label_zh}，我在。要不要先放慢一下，喝口水再继续？"
        followup = ""
        style = "warm"
        llm_sourced = False
        if self._llm and self._llm.enabled:
            context = {
                "input_type": "emotion_signal",
                "scene": self._config.policy.scene,
                "decision": "CARE",
                "level": 2,
                "expression_modality": {
                    "label": expr_label,
                    "confidence": expr_conf,
                    "note": "这是算法观测到的情绪信号，不是用户原话",
                },
                "risk": {
                    "V": decision.v,
                    "A": decision.a,
                    "T": t_score,
                    "S": s_final,
                    "pattern": "expression_non_neutral",
                },
                "risk_detail": {
                    "expression_modality": expr_label,
                    "expression_confidence": expr_conf,
                    "V_sub": frame.V_sub,
                    "A_sub": frame.A_sub,
                    "T_sub": frame.T_sub,
                },
                "tags": tags + [f"expr:{expr_label}"],
                "transcript_summary": summary or transcript[:120],
                "constraints": "这是情绪信号不是用户原话；回复≤100字；先接住再轻建议，低打扰。",
            }
            reply = self._llm.generate_care_reply(context) or {}
            llm_text = str(reply.get("text", "")).strip()
            if llm_text:
                default_text = llm_text
                llm_sourced = True
            followup = str(reply.get("followup_question", "")).strip()
            style = str(reply.get("style", "warm")).strip() or "warm"
        steps = [ScriptStep("SAY", {"text": default_text, "voice": "warm", "priority": 2})]
        if followup:
            steps.append(ScriptStep("WAIT", {"duration_ms": 700}))
            steps.append(ScriptStep("SAY", {"text": followup, "voice": "warm", "priority": 1}))
        return CarePlan(
            text=default_text,
            style=style,
            motion={},
            emo={},
            followup_question=followup,
            reason={
                "pattern": "expression_non_neutral",
                "expression_class_id": expr_id,
                "expression_modality": expr_label,
                "expression_confidence": expr_conf,
                "V": decision.v,
                "A": decision.a,
                "T": t_score,
                "S": s_final,
            },
            policy={"source": "expression_non_neutral", "content_source": "llm" if llm_sourced else "template"},
            decision="CARE",
            level=2,
            steps=steps,
            cooldown_min=self._config.trigger.cooldown_min,
            record_event=True,
            event_type="EXPRESSION_NON_NEUTRAL",
        )

    def _maybe_llm_rewrite(
        self,
        care_plan: Optional[CarePlan],
        tags: List[str],
        transcript: str,
        summary: str,
        frame: RiskFrame,
    ) -> Optional[CarePlan]:
        if not care_plan or not self._llm or not self._llm.enabled:
            return care_plan
        expr_label = self._expression_label_from_id(int(frame.V_sub.get("expression_class_id", -1)))
        expr_conf = float(frame.V_sub.get("expression_confidence", 0.0))
        context = {
            "scene": self._config.policy.scene,
            "decision": care_plan.decision,
            "level": care_plan.level,
            "input_type": "emotion_signal",
            "expression_modality": {
                "label": expr_label,
                "confidence": expr_conf,
                "note": "这是算法观测到的情绪信号，不是用户原话",
            },
            "expression_confidence": expr_conf,
            "risk": {
                "V": care_plan.reason.get("V") if care_plan.reason else None,
                "A": care_plan.reason.get("A") if care_plan.reason else None,
                "T": care_plan.reason.get("T") if care_plan.reason else None,
                "S": care_plan.reason.get("S") if care_plan.reason else None,
                "pattern": care_plan.reason.get("pattern") if care_plan.reason else None,
            },
            "risk_detail": {
                "V_sub": frame.V_sub,
                "A_sub": frame.A_sub,
                "T_sub": frame.T_sub,
            },
            "tags": tags,
            "transcript_summary": summary or transcript[:120],
            "constraints": "回复≤100字；这是情绪信号而非用户原话；先回应内容，最多一个低压力问题，不诊断不说教，避免模板化。",
        }
        reply = self._llm.generate_care_reply(context)
        if not reply:
            return care_plan
        text = str(reply.get("text", care_plan.text))
        followup_question = str(reply.get("followup_question", ""))
        style = str(reply.get("style", care_plan.style))
        updated_steps = list(care_plan.steps)
        say_index = None
        for idx, step in enumerate(updated_steps):
            if step.type == "SAY":
                step.payload = {**step.payload, "text": text}
                say_index = idx
                break
        if followup_question:
            insert_at = say_index + 1 if say_index is not None else len(updated_steps)
            updated_steps.insert(insert_at, ScriptStep("WAIT", {"duration_ms": 800}))
            updated_steps.insert(
                insert_at + 1,
                ScriptStep("SAY", {"text": followup_question, "voice": "warm", "priority": 1}),
            )
        return CarePlan(
            text=text,
            style=style,
            motion=care_plan.motion,
            emo=care_plan.emo,
            followup_question=followup_question,
            reason=care_plan.reason,
            policy={**(care_plan.policy or {}), "content_source": "llm"},
            decision=care_plan.decision,
            level=care_plan.level,
            steps=updated_steps,
            cooldown_min=care_plan.cooldown_min,
            record_event=care_plan.record_event,
            event_type=care_plan.event_type,
        )

    def _is_llm_sourced(self, care_plan: Optional[CarePlan]) -> bool:
        if not care_plan:
            return False
        policy = care_plan.policy if isinstance(care_plan.policy, dict) else {}
        return str(policy.get("content_source", "")).strip().lower() == "llm"

    def _allow_trigger(self, timestamp_ms: int) -> bool:
        if self._mode != "normal":
            return False
        if timestamp_ms < self._cooldown_until_ms:
            return False
        if self._daily_trigger_count >= self._config.trigger.daily_trigger_limit:
            return False
        return True

    def _refresh_daily_counter(self, timestamp_ms: int) -> None:
        date_str = datetime.fromtimestamp(timestamp_ms / 1000).strftime("%Y-%m-%d")
        if self._daily_date is None:
            self._daily_date = date_str
        if date_str != self._daily_date:
            self._daily_date = date_str
            self._daily_trigger_count = 0
            self._summary_events = []
            self._summary_last_state_sample_ms = 0
            self._summary_last_state_score = None
            self._summary_last_state_expr = "unknown"

    def _update_rms_baseline(self, rms: float) -> None:
        self._rms_count += 1
        delta = rms - self._rms_mean
        self._rms_mean += delta / self._rms_count
        delta2 = rms - self._rms_mean
        self._rms_m2 += delta * delta2

    def _rms_std(self) -> float:
        if self._rms_count < 2:
            return max(1.0, abs(self._rms_mean))
        return (self._rms_m2 / (self._rms_count - 1)) ** 0.5

    def _append_history(self, timestamp_ms: int) -> None:
        if self._last_history_ts and timestamp_ms - self._last_history_ts < self._config.runtime.risk_update_interval_ms:
            return
        self._last_history_ts = timestamp_ms
        frame = RiskFrame(
            ts_ms=timestamp_ms,
            V=self._V,
            A=self._A,
            T=self._T,
            V_sub=self._last_v_sub,
            A_sub=self._last_a_sub,
            T_sub=self._last_t_sub,
        )
        self._history.append(frame)
        cutoff = timestamp_ms - self._history_window_ms
        while self._history and self._history[0].ts_ms < cutoff:
            self._history.popleft()

    def _start_summary_scheduler(self) -> None:
        if not getattr(self._config, "summary", None):
            return
        if not self._config.summary.enabled:
            return
        self._summary_stop.clear()
        if self._summary_thread and self._summary_thread.is_alive():
            return
        self._summary_thread = threading.Thread(target=self._summary_loop, daemon=True)
        self._summary_thread.start()

    def _summary_loop(self) -> None:
        run_at = self._parse_daily_time(self._config.summary.daily_time)
        while not self._summary_stop.is_set():
            now = datetime.now()
            today_key = now.strftime("%Y-%m-%d")
            target = datetime.combine(now.date(), run_at)
            if now >= target:
                if self._last_summary_date != today_key:
                    self._last_summary_date = today_key
                    self._emit_daily_summary(now_ms())
                next_run = target + timedelta(days=1)
            else:
                next_run = target
            wait_sec = max(5.0, (next_run - now).total_seconds())
            self._summary_stop.wait(timeout=min(wait_sec, 60.0))

    def _parse_daily_time(self, value: str) -> dt_time:
        try:
            parts = value.split(":")
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
            return dt_time(hour=hour, minute=minute)
        except Exception:
            return dt_time(hour=22, minute=30)

    def _emit(self, event_type: str, timestamp_ms: int, payload: dict) -> None:
        self._event_bus.emit(Event(type=event_type, timestamp_ms=timestamp_ms, payload=payload))

    def _record_summary_event(
        self,
        timestamp_ms: int,
        tags: List[str],
        summary: str,
        transcript: str,
        decision,
        t_score: Optional[float],
        s_final: float,
    ) -> None:
        expr_id = int(self._last_v_sub.get("expression_class_id", -1))
        expr_conf = float(self._last_v_sub.get("expression_confidence", 0.0))
        expr_label = self._expression_label_from_id(expr_id)
        summary_text = summary.strip()
        if not summary_text:
            summary_text = transcript.strip()[:120]
        if not summary_text:
            if expr_label not in {"neutral", "unknown"}:
                summary_text = f"检测到{expr_label}情绪（置信度{expr_conf:.2f}）"
            elif tags:
                summary_text = f"主要情绪：{tags[0]}"
            else:
                summary_text = f"状态波动：V={decision.v:.2f} A={decision.a:.2f} S={s_final:.2f}"
        event = {
            "timestamp_ms": timestamp_ms,
            "event_type": "trigger",
            "summary": summary_text,
            "tags": tags,
            "expression_class_id": expr_id,
            "expression_modality": expr_label,
            "expression_confidence": expr_conf,
            "risk": {"V": decision.v, "A": decision.a, "T": t_score, "S": s_final},
            "mode": self._mode,
        }
        self._append_summary_event(event)

    def _append_summary_event(self, event: Dict[str, object]) -> None:
        self._summary_events.append(event)
        max_events = 1200
        if len(self._summary_events) > max_events:
            self._summary_events = self._summary_events[-max_events:]

    def _record_state_checkpoint(self, timestamp_ms: int) -> None:
        expr_id = int(self._last_v_sub.get("expression_class_id", -1))
        expr_conf = float(self._last_v_sub.get("expression_confidence", 0.0))
        expr_label = self._expression_label_from_id(expr_id)

        interval_ready = (
            self._summary_last_state_sample_ms == 0
            or timestamp_ms - self._summary_last_state_sample_ms >= self._summary_state_min_interval_ms
        )
        expr_changed = (
            self._summary_last_state_expr != "unknown"
            and expr_label != self._summary_last_state_expr
            and expr_conf >= 0.08
        )
        risk_jump = (
            self._summary_last_state_score is not None
            and abs(self._S - self._summary_last_state_score) >= 0.12
        )
        if not (interval_ready or expr_changed or risk_jump):
            return

        summary_text = f"状态采样：{expr_label}（{expr_conf:.2f}），风险S={self._S:.2f}"
        event = {
            "timestamp_ms": timestamp_ms,
            "event_type": "state",
            "summary": summary_text,
            "tags": [f"expr:{expr_label}"] if expr_label not in {"unknown"} else [],
            "expression_class_id": expr_id,
            "expression_modality": expr_label,
            "expression_confidence": expr_conf,
            "risk": {"V": self._V, "A": self._A, "T": self._T, "S": self._S},
            "mode": self._mode,
        }
        self._append_summary_event(event)
        self._summary_last_state_sample_ms = timestamp_ms
        self._summary_last_state_score = self._S
        self._summary_last_state_expr = expr_label

    def _emit_daily_summary(
        self, timestamp_ms: int, events_override: Optional[List[Dict[str, object]]] = None
    ) -> None:
        if not self._summarizer:
            return
        events = events_override if events_override is not None else list(self._summary_events)
        result = self._summarizer.summarize(events)
        payload = {
            "summary": result.get("summary", ""),
            "highlights": result.get("highlights", []),
            "count": len(events),
        }
        self._emit("DailySummaryReady", timestamp_ms, payload)
