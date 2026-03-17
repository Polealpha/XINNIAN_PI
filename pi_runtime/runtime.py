from __future__ import annotations

from collections import deque
from dataclasses import asdict
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
import logging
import subprocess
import threading
import time
from typing import Deque, Dict, List, Optional

from engine.audio.acoustic_features import extract_features
from engine.audio.acoustic_risk import AcousticRiskScorer
from engine.audio.ring_buffer import AudioRingBuffer
from engine.audio.vad import SimpleVAD
from engine.core.config import EngineConfig, load_engine_config
from engine.core.event_bus import EventBus
from engine.core.types import AudioFrame, Context, EngineStatus, Event, RiskFrame, ScriptStep, UserSignal, VideoFrame
from engine.llm.llm_responder import LLMResponder
from engine.nlp.asr_module import AsrModule
from engine.nlp.text_risk import TextRiskScorer
from engine.policy.care_policy import CarePolicy
from engine.summary.daily_summarizer import DailySummarizer
from engine.trigger.fusion_scorer import FusionScorer
from engine.trigger.trigger_manager import TriggerDecision, TriggerManager
from engine.tts.tts_engine import TtsEngine
from engine.vision.face_detector import FaceDetector
from engine.vision.face_tracker import FaceTracker
from engine.vision.vision_types import FaceDet

from .backend_sync import BackendSyncClient
from .config import PiRuntimeConfig, load_pi_config
from .hardware import BaseHardware, build_hardware
from .identity import OwnerIdentityManager
from .onboarding import OnboardingManager

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None
    np = None

logger = logging.getLogger(__name__)


class PiEmotionRuntime:
    def __init__(self, pi_config_path: str, engine_config_path: str) -> None:
        self.pi_config: PiRuntimeConfig = load_pi_config(pi_config_path)
        self.engine_config: EngineConfig = load_engine_config(engine_config_path)

        self._event_bus = EventBus()
        self._running = False
        self._threads: List[threading.Thread] = []
        self._stop = threading.Event()

        self._ring_buffer = AudioRingBuffer(self.engine_config.audio.ring_buffer_minutes)
        self._vad = SimpleVAD()
        self._acoustic_risk = AcousticRiskScorer()
        self._trigger_manager = TriggerManager(self.engine_config.trigger, self.engine_config.video)
        self._fusion = FusionScorer(self.engine_config.fusion)
        self._asr = AsrModule(self.engine_config.asr) if self.pi_config.audio.enabled else None
        engine_root = Path(__file__).resolve().parents[1] / "engine"
        self._text_risk = TextRiskScorer(str(engine_root / "nlp" / "lexicon_zh.txt"))
        self._care_policy = CarePolicy(str(engine_root / "policy" / "templates_zh.json"))
        self._llm: Optional[LLMResponder] = None
        self._tts = TtsEngine()
        self._hardware: BaseHardware = build_hardware(self.pi_config.hardware)
        self._onboarding = OnboardingManager(self.pi_config.onboarding)

        self._face_detector = FaceDetector(asdict(self.engine_config.face_tracking)) if self.pi_config.camera.enabled else None
        self._face_tracker = FaceTracker(asdict(self.engine_config.face_tracking)) if self.pi_config.camera.enabled else None
        self._identity = OwnerIdentityManager(self.pi_config.identity) if self.pi_config.identity.enabled else None
        self._backend_sync = BackendSyncClient(
            self.pi_config.backend,
            self.pi_config.device.device_id,
            self.get_status_payload,
            self._get_pending_owner_sync,
            self._mark_owner_sync_complete,
        )

        self._audio_seq = 0
        self._video_seq = 0
        self._mode = "normal"
        self._cooldown_until_ms = 0
        self._daily_trigger_count = 0
        self._daily_date: Optional[str] = None
        self._last_event_ts_ms = 0
        self._last_audio_ts = 0
        self._last_video_ts = 0
        self._last_risk_emit_ms = 0
        self._last_face_present = False
        self._last_vad_active = False
        self._last_v_raw = 0.0
        self._last_a_raw = 0.0
        self._last_t_score: Optional[float] = None
        self._last_transcript = ""
        self._last_summary = ""
        self._last_tags: List[str] = []
        self._V = 0.0
        self._A = 0.0
        self._T: Optional[float] = None
        self._S = 0.0
        self._silence_ms = 0
        self._face_missing_ms = 0
        self._last_v_sub: Dict[str, float] = {}
        self._last_a_sub: Dict[str, float] = {}
        self._last_t_sub: Dict[str, object] = {}
        self._history: Deque[RiskFrame] = deque()
        self._history_window_ms = int(self.engine_config.policy.history_window_sec * 1000)
        self._summary_events: List[Dict[str, object]] = []
        self._last_summary_payload: Dict[str, object] = {"summary": "", "highlights": [], "count": 0}
        self._summary_last_date: Optional[str] = None
        self._last_pan_turn = 0.0
        self._last_tilt_turn = 0.0
        self._last_pan_angle = float(self.pi_config.hardware.pan_servo.center_angle)
        self._last_tilt_angle = float(self.pi_config.hardware.tilt_servo.center_angle)
        self._preview_lock = threading.Lock()
        self._latest_preview_jpeg: bytes = b""
        self._latest_preview_ts_ms = 0
        self._identity_state: Dict[str, object] = self._identity.get_status() if self._identity else {
            "identity_state": "disabled",
            "owner_recognized": False,
            "owner_confidence": 0.0,
            "recognition_label": "disabled",
            "enrollment_active": False,
        }
        self._tracking_target = "none"
        self._last_status_ts_ms = 0

        self._rms_mean = 0.0
        self._rms_m2 = 0.0
        self._rms_count = 0

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop.clear()
        self._onboarding.ensure_bootstrap_mode()
        if self._backend_sync.enabled:
            self.on_event(self._backend_sync.enqueue_event)
            self._backend_sync.start()
        if self.pi_config.audio.enabled:
            self._threads.append(threading.Thread(target=self._audio_loop, name="pi-audio", daemon=True))
        if self.pi_config.camera.enabled:
            self._threads.append(threading.Thread(target=self._camera_loop, name="pi-camera", daemon=True))
        self._threads.append(threading.Thread(target=self._summary_loop, name="pi-summary", daemon=True))
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._running = False
        for thread in list(self._threads):
            thread.join(timeout=2.0)
        self._threads.clear()
        self._backend_sync.stop()
        self._hardware.close()

    def _ensure_llm(self) -> Optional[LLMResponder]:
        if self._llm is not None:
            return self._llm
        try:
            self._llm = LLMResponder(self.engine_config.llm)
        except Exception as exc:
            logger.warning("llm init failed: %s", exc)
            self._llm = None
        return self._llm

    def get_status(self) -> EngineStatus:
        now_ms = self._now_ms()
        return EngineStatus(
            mode=self._mode,
            V=self._V,
            A=self._A,
            T=self._T,
            S=self._S,
            cooldown_remaining_ms=max(0, self._cooldown_until_ms - now_ms),
            daily_trigger_count=self._daily_trigger_count,
            last_event_ts_ms=self._last_event_ts_ms,
            health={
                "audio_ok": now_ms - self._last_audio_ts < 5000,
                "video_ok": now_ms - self._last_video_ts < 5000 if self.pi_config.camera.enabled else False,
                "hardware_ok": True,
                "control_local": True,
            },
        )

    def get_status_payload(self) -> Dict[str, object]:
        status = self.get_status()
        onboarding = self._onboarding.get_state()
        identity_state = dict(self._identity_state)
        payload = {
            **status.__dict__,
            "timestamp_ms": self._now_ms(),
            "device_id": self.pi_config.device.device_id,
            "scene": self.pi_config.device.scene,
            "ssid": onboarding.get("connected_ssid"),
            "onboarding_state": onboarding.get("mode"),
            "identity_state": identity_state.get("identity_state"),
            "owner_recognized": bool(identity_state.get("owner_recognized")),
            "owner_confidence": float(identity_state.get("owner_confidence", 0.0) or 0.0),
            "tracking_target": self._tracking_target,
            "pan_angle": round(float(self._last_pan_angle), 2),
            "tilt_angle": round(float(self._last_tilt_angle), 2),
            "recognition_label": identity_state.get("recognition_label"),
            "embedding_version": identity_state.get("embedding_version"),
            "enrollment_active": bool(identity_state.get("enrollment_active")),
        }
        self._last_status_ts_ms = int(payload["timestamp_ms"])
        return payload

    def get_preview_jpeg(self) -> bytes:
        with self._preview_lock:
            return bytes(self._latest_preview_jpeg)

    def get_onboarding_state(self) -> Dict[str, object]:
        state = self._onboarding.get_state()
        state["identity_state"] = self._identity_state.get("identity_state")
        return state

    def scan_networks(self) -> List[Dict[str, object]]:
        return self._onboarding.scan_networks()

    def configure_wifi(self, ssid: str, password: str) -> Dict[str, object]:
        return self._onboarding.configure_wifi(ssid, password)

    def reset_onboarding(self) -> Dict[str, object]:
        return self._onboarding.reset()

    def start_owner_enrollment(self, owner_label: str = "owner", claim_token: str = "") -> Dict[str, object]:
        if self._identity is None:
            raise RuntimeError("identity disabled")
        status = self._identity.start_enrollment(owner_label, claim_token)
        self._identity_state = dict(status)
        return status

    def get_owner_status(self) -> Dict[str, object]:
        if self._identity is None:
            return dict(self._identity_state)
        self._identity_state = self._identity.get_status()
        return dict(self._identity_state)

    def reset_owner_profile(self) -> Dict[str, object]:
        if self._identity is None:
            raise RuntimeError("identity disabled")
        status = self._identity.reset_owner()
        self._identity_state = dict(status)
        return status

    def get_risk_snapshot(self) -> Dict[str, object]:
        return {
            "mode": self._mode,
            "V": self._V,
            "A": self._A,
            "T": self._T,
            "S": self._S,
            "detail": {
                "V_sub": dict(self._last_v_sub),
                "A_sub": dict(self._last_a_sub),
                "T_sub": dict(self._last_t_sub),
            },
        }

    def get_recent_events(self, limit: int = 50) -> List[Dict[str, object]]:
        return self._summary_events[-max(1, int(limit)) :]

    def get_last_summary(self) -> Dict[str, object]:
        return dict(self._last_summary_payload)

    def on_event(self, callback) -> None:
        self._event_bus.subscribe(callback)

    def handle_signal(self, signal: UserSignal) -> None:
        if signal.type == "privacy_on":
            self._mode = "privacy"
            self._emit("ModeChanged", signal.timestamp_ms, {"mode": self._mode})
            return
        if signal.type == "privacy_off":
            self._mode = "normal"
            self._emit("ModeChanged", signal.timestamp_ms, {"mode": self._mode})
            return
        if signal.type == "manual_care":
            payload = signal.payload if isinstance(signal.payload, dict) else {}
            self.manual_care(str(payload.get("text", "") or ""))
            return
        if signal.type == "speak":
            payload = signal.payload if isinstance(signal.payload, dict) else {}
            text = str(payload.get("text", "") or "")
            if text:
                self._hardware.speak(self._tts, text)

    def manual_care(self, context_text: str = "") -> Dict[str, object]:
        timestamp_ms = self._now_ms()
        payload = {
            "input_type": "manual_trigger",
            "scene": self.engine_config.policy.scene,
            "decision": "CARE",
            "level": 2,
            "risk": {"V": self._V, "A": self._A, "T": self._T, "S": self._S, "pattern": "manual"},
            "transcript_summary": str(context_text or self._last_summary or self._last_transcript)[:120],
            "constraints": "回复≤100字；先接住感受，再给一个轻建议，最多一个问题。",
        }
        text = "我在。要不要先慢一点，和我说说现在最卡住你的那件事？"
        followup = ""
        style = "warm"
        llm = self._ensure_llm()
        if llm and llm.enabled:
            reply = llm.generate_care_reply(payload) or {}
            text = str(reply.get("text", text) or text).strip()
            followup = str(reply.get("followup_question", "") or "").strip()
            style = str(reply.get("style", "warm") or "warm").strip()

        steps = [ScriptStep("SAY", {"text": text, "voice": "warm", "priority": 2})]
        if followup:
            steps.append(ScriptStep("WAIT", {"duration_ms": 800}))
            steps.append(ScriptStep("SAY", {"text": followup, "voice": "warm", "priority": 1}))
        event_payload = {
            "care_plan": {
                "text": text,
                "style": style,
                "followup_question": followup,
                "decision": "CARE",
                "level": 2,
                "steps": [step.to_dict() for step in steps],
            }
        }
        self._emit("CarePlanReady", timestamp_ms, event_payload)
        self._append_summary_event(
            {
                "timestamp_ms": timestamp_ms,
                "event_type": "manual",
                "summary": text,
                "tags": ["manual"],
                "risk": {"V": self._V, "A": self._A, "T": self._T, "S": self._S},
                "mode": self._mode,
            }
        )
        self._hardware.speak(self._tts, text)
        if followup:
            time.sleep(0.8)
            self._hardware.speak(self._tts, followup)
        return event_payload

    def _audio_loop(self) -> None:
        cfg = self.pi_config.audio
        frame_bytes = cfg.frame_bytes
        while not self._stop.is_set():
            proc = None
            try:
                proc = subprocess.Popen(
                    list(cfg.command),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    bufsize=frame_bytes,
                )
                while not self._stop.is_set():
                    if proc.stdout is None:
                        break
                    chunk = proc.stdout.read(frame_bytes)
                    if not chunk or len(chunk) < frame_bytes:
                        break
                    ts = self._now_ms()
                    self._push_audio(
                        AudioFrame(
                            pcm_s16le=chunk,
                            sample_rate=cfg.sample_rate,
                            channels=cfg.channels,
                            timestamp_ms=ts,
                            seq=self._audio_seq,
                            device_id=self.pi_config.device.device_id,
                        )
                    )
                    self._audio_seq += 1
            except FileNotFoundError:
                logger.warning("audio capture command not found: %s", cfg.command[0] if cfg.command else "arecord")
                return
            except Exception as exc:
                logger.warning("audio loop failed: %s", exc)
            finally:
                try:
                    if proc is not None:
                        proc.terminate()
                except Exception:
                    pass
            if not self._stop.is_set():
                time.sleep(max(0.5, float(cfg.restart_backoff_sec)))

    def _camera_loop(self) -> None:
        backend = str(self.pi_config.camera.backend or "picamera2").strip().lower()
        if backend == "picamera2" and self._camera_loop_picamera2():
            return
        self._camera_loop_opencv()

    def _camera_loop_picamera2(self) -> bool:
        try:
            from picamera2 import Picamera2  # type: ignore
            import cv2  # type: ignore
        except Exception as exc:
            logger.info("picamera2 unavailable, falling back to opencv: %s", exc)
            return False

        picam = None
        try:
            picam = Picamera2()
            video_config = picam.create_video_configuration(
                main={"size": (self.pi_config.camera.width, self.pi_config.camera.height), "format": "RGB888"}
            )
            picam.configure(video_config)
            picam.start()
            frame_interval = 1.0 / max(1, int(self.pi_config.camera.fps))
            while not self._stop.is_set():
                rgb = picam.capture_array()
                if rgb is None:
                    time.sleep(frame_interval)
                    continue
                bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                self._push_video(
                    VideoFrame(
                        format="bgr",
                        data=bgr.tobytes(),
                        width=bgr.shape[1],
                        height=bgr.shape[0],
                        timestamp_ms=self._now_ms(),
                        seq=self._video_seq,
                        device_id=self.pi_config.device.device_id,
                    )
                )
                self._video_seq += 1
                time.sleep(frame_interval)
            return True
        except Exception as exc:
            logger.warning("picamera2 loop failed: %s", exc)
            return False
        finally:
            try:
                if picam is not None:
                    picam.stop()
            except Exception:
                pass

    def _camera_loop_opencv(self) -> None:
        try:
            import cv2  # type: ignore
        except Exception as exc:
            logger.warning("opencv camera capture unavailable: %s", exc)
            return
        cap = cv2.VideoCapture(int(self.pi_config.camera.device_index))
        if not cap.isOpened():
            logger.warning("opencv camera device %s not available", self.pi_config.camera.device_index)
            return
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.pi_config.camera.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.pi_config.camera.height)
        frame_interval = 1.0 / max(1, int(self.pi_config.camera.fps))
        try:
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    time.sleep(frame_interval)
                    continue
                self._push_video(
                    VideoFrame(
                        format="bgr",
                        data=frame.tobytes(),
                        width=frame.shape[1],
                        height=frame.shape[0],
                        timestamp_ms=self._now_ms(),
                        seq=self._video_seq,
                        device_id=self.pi_config.device.device_id,
                    )
                )
                self._video_seq += 1
                time.sleep(frame_interval)
        finally:
            cap.release()

    def _push_audio(self, frame: AudioFrame) -> None:
        if self._mode == "privacy":
            return
        self._last_audio_ts = frame.timestamp_ms
        self._ring_buffer.add_frame(frame)
        features = extract_features(frame.pcm_s16le)
        vad_active = self._vad.update(features["rms"]) if self.engine_config.audio.vad_enabled else True
        self._last_vad_active = vad_active
        if vad_active:
            self._silence_ms = 0
            self._update_rms_baseline(float(features.get("rms", 0.0)))
        else:
            self._silence_ms += self.engine_config.audio.frame_ms

        self._last_a_raw = self._acoustic_risk.score(features["rms"], features["zcr"], vad_active)
        self._last_a_sub = {
            "rms": float(features.get("rms", 0.0)),
            "zcr": float(features.get("zcr", 0.0)),
            "peak": float(features.get("peak", 0.0)),
            "silence_sec": round(self._silence_ms / 1000.0, 3),
        }
        self._recompute_risk(frame.timestamp_ms)

    def _push_video(self, frame: VideoFrame) -> None:
        if self._mode == "privacy":
            return
        self._last_video_ts = frame.timestamp_ms
        frame_bgr = self._frame_to_bgr(frame)
        self._update_preview(frame_bgr, frame.timestamp_ms)
        det = self._face_detector.detect(frame) if self._face_detector and self._face_detector.ready else None
        target_det = det if det and det.found else None

        if self._identity is not None and frame_bgr is not None:
            identity_result = self._identity.process_frame(frame_bgr, frame.timestamp_ms)
            self._identity_state = {k: v for k, v in identity_result.items() if k != "tracking_bbox"}
            tracking_bbox = identity_result.get("tracking_bbox")
            if isinstance(tracking_bbox, tuple) and len(tracking_bbox) == 4:
                target_det = self._target_det_from_bbox(tracking_bbox, frame.width, frame.height)
                self._tracking_target = "owner" if bool(self._identity_state.get("owner_recognized")) else "largest_face"
            else:
                self._tracking_target = "none"
            for event in self._identity.pop_events():
                self._emit(str(event.get("type") or "OwnerState"), frame.timestamp_ms, dict(event.get("payload") or {}))

        if target_det and target_det.found:
            self._face_missing_ms = 0
            self._last_face_present = True
            pan_turn, tilt_turn, dbg = (
                self._face_tracker.update(target_det, frame.width, frame.height, frame.timestamp_ms)
                if self._face_tracker
                else (None, None, {})
            )
            if pan_turn is not None or tilt_turn is not None:
                self._apply_pan_tilt(
                    self._last_pan_turn if pan_turn is None else pan_turn,
                    self._last_tilt_turn if tilt_turn is None else tilt_turn,
                )
            ex_smooth = abs(float(dbg.get("ex_smooth", 0.0)))
            dead_zone = float(dbg.get("dead_zone", 0.08))
            attention_drop = max(0.0, min(1.0, (ex_smooth - dead_zone) / max(0.01, 1.0 - dead_zone)))
            face_area = float(target_det.area_ratio or 0.0)
            face_size_penalty = 0.0 if face_area >= 0.06 else max(0.0, min(1.0, (0.06 - face_area) / 0.06))
            self._last_v_raw = max(0.0, min(1.0, 0.65 * attention_drop + 0.35 * face_size_penalty))
            self._last_v_sub = {
                "face_ok": 1.0,
                "attention_drop": round(attention_drop, 3),
                "face_area_ratio": round(face_area, 4),
                "tracking_target": self._tracking_target,
                "expression_class_id": 0,
                "expression_confidence": 0.0,
            }
        else:
            self._face_missing_ms += int(1000 / max(1, self.pi_config.camera.fps))
            self._last_face_present = False
            self._tracking_target = "none"
            grace_ms = int(self.engine_config.video.face_missing_grace_sec * 1000)
            self._last_v_raw = max(0.0, min(1.0, self._face_missing_ms / max(grace_ms * 2, 1)))
            self._last_v_sub = {
                "face_ok": 0.0,
                "attention_drop": round(self._last_v_raw, 3),
                "face_area_ratio": 0.0,
                "expression_class_id": -1,
                "expression_confidence": 0.0,
            }
        self._recompute_risk(frame.timestamp_ms)

    def _recompute_risk(self, timestamp_ms: int) -> None:
        self._refresh_daily_counter(timestamp_ms)
        decision = self._trigger_manager.update(
            timestamp_ms=timestamp_ms,
            v_raw=self._last_v_raw,
            a_raw=self._last_a_raw,
            vad_active=self._last_vad_active,
            face_present=self._last_face_present,
        )
        self._V = float(decision.v)
        self._A = float(decision.a)
        self._T = self._last_t_score
        self._S = float(self._fusion.score(self._V, self._A, self._T))

        if timestamp_ms - self._last_risk_emit_ms >= self.engine_config.runtime.risk_update_interval_ms:
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
                    "detail": {"V_sub": dict(self._last_v_sub), "A_sub": dict(self._last_a_sub), "T_sub": dict(self._last_t_sub)},
                },
            )
            self._append_history(timestamp_ms)

        if decision.should_trigger and self._allow_trigger(timestamp_ms):
            self._handle_trigger(timestamp_ms, decision)

    def _handle_trigger(self, timestamp_ms: int, decision: TriggerDecision) -> None:
        transcript = ""
        t_score: Optional[float] = None
        tags: List[str] = []
        summary = ""
        audio_window_ms = min(max(8, int(self.engine_config.asr.max_sec or 12)), 20) * 1000
        if self._asr and self._asr.ready:
            pcm, _start, _end = self._ring_buffer.get_last_ms(audio_window_ms)
            if pcm:
                transcript = self._asr.transcribe(pcm, self.engine_config.audio.sample_rate).strip()
        if transcript:
            t_score, tags, summary = self._text_risk.score(transcript)
            self._last_t_score = t_score
            self._last_transcript = transcript
            self._last_summary = summary
            self._last_tags = list(tags)
            self._last_t_sub = {"transcript": transcript, "summary": summary, "tags": tags}
            self._emit("TranscriptReady", timestamp_ms, {"transcript": transcript, "summary": summary, "tags": tags, "T": t_score})
        else:
            self._last_t_sub = {}

        frame = RiskFrame(
            ts_ms=timestamp_ms,
            V=self._V,
            A=self._A,
            T=t_score,
            V_sub=dict(self._last_v_sub),
            A_sub=dict(self._last_a_sub),
            T_sub=dict(self._last_t_sub),
        )
        ctx = Context(
            device_id=self.pi_config.device.device_id,
            scene=self.engine_config.policy.scene,
            mode=self._mode,
            now_ms=timestamp_ms,
            cooldown_until_ms=self._cooldown_until_ms,
            daily_count=self._daily_trigger_count,
            daily_limit=self.engine_config.trigger.daily_trigger_limit,
            baseline={"rms_mean": self._rms_mean, "rms_std": self._rms_std()},
            cfg={
                "scene": self.engine_config.policy.scene,
                "cooldown_min": self.engine_config.trigger.cooldown_min,
                "fusion": {"wV": self.engine_config.fusion.wV, "wA": self.engine_config.fusion.wA, "wT": self.engine_config.fusion.wT},
                "thresholds": self.engine_config.policy.thresholds,
                "sustained_low_activity": self.engine_config.policy.sustained_low_activity,
                "peak_to_silence": self.engine_config.policy.peak_to_silence,
                "expression_distress": self.engine_config.policy.expression_distress,
                "templates": self._care_policy.templates,
            },
        )
        care_plan = self._care_policy.decide(ctx, frame, list(self._history))
        care_plan = self._maybe_rewrite_care_plan(care_plan, frame, transcript, summary, tags, t_score)
        self._emit(
            "TriggerFired",
            timestamp_ms,
            {"reason": decision.reason, "V": self._V, "A": self._A, "T": t_score, "S": self._S, "care_decision": care_plan.decision},
        )
        self._append_summary_event(
            {
                "timestamp_ms": timestamp_ms,
                "event_type": "trigger",
                "summary": summary or transcript[:120] or care_plan.text,
                "tags": tags or [str(decision.reason or "trigger")],
                "risk": {"V": self._V, "A": self._A, "T": t_score, "S": self._S},
                "mode": self._mode,
                "expression_modality": "unknown",
                "expression_confidence": 0.0,
            }
        )
        if care_plan.decision in {"NUDGE", "CARE", "GUARD"} and care_plan.text:
            self._daily_trigger_count += 1
            self._cooldown_until_ms = timestamp_ms + int(care_plan.cooldown_min * 60 * 1000)
            self._last_event_ts_ms = timestamp_ms
            self._emit(
                "CarePlanReady",
                timestamp_ms,
                {
                    "care_plan": care_plan.to_dict(),
                    "delivery_mode": "voice",
                    "reason": {"pattern": decision.reason, "V": self._V, "A": self._A, "T": t_score, "S": self._S},
                },
            )
            self._hardware.set_status_active(True)
            self._hardware.speak(self._tts, care_plan.text)
            if care_plan.followup_question:
                time.sleep(0.8)
                self._hardware.speak(self._tts, care_plan.followup_question)
            self._hardware.set_status_active(False)

    def _maybe_rewrite_care_plan(self, care_plan, frame: RiskFrame, transcript: str, summary: str, tags: List[str], t_score: Optional[float]):
        llm = self._ensure_llm()
        if not llm or not llm.enabled:
            return care_plan
        if care_plan.decision not in {"NUDGE", "CARE", "GUARD"}:
            return care_plan
        context = {
            "input_type": "emotion_signal",
            "scene": self.engine_config.policy.scene,
            "decision": care_plan.decision,
            "level": care_plan.level,
            "risk": {"V": frame.V, "A": frame.A, "T": t_score, "S": self._S, "pattern": str((care_plan.reason or {}).get("pattern", "pi_runtime"))},
            "risk_detail": {"V_sub": frame.V_sub, "A_sub": frame.A_sub, "T_sub": frame.T_sub},
            "tags": tags,
            "transcript_summary": summary or transcript[:120],
            "constraints": "回复≤100字；先共情，再给一个轻建议，最多一个问题，不说教。",
        }
        reply = llm.generate_care_reply(context) or {}
        text = str(reply.get("text", "") or "").strip()
        if not text:
            return care_plan
        followup = str(reply.get("followup_question", "") or "").strip()
        style = str(reply.get("style", care_plan.style) or care_plan.style).strip()
        steps = [ScriptStep("SAY", {"text": text, "voice": "warm", "priority": 2})]
        if followup:
            steps.append(ScriptStep("WAIT", {"duration_ms": 800}))
            steps.append(ScriptStep("SAY", {"text": followup, "voice": "warm", "priority": 1}))
        care_plan.text = text
        care_plan.followup_question = followup
        care_plan.style = style or "warm"
        care_plan.steps = steps
        care_plan.policy = {**(care_plan.policy or {}), "content_source": "llm"}
        return care_plan

    def _append_history(self, timestamp_ms: int) -> None:
        self._history.append(RiskFrame(ts_ms=timestamp_ms, V=self._V, A=self._A, T=self._T, V_sub=dict(self._last_v_sub), A_sub=dict(self._last_a_sub), T_sub=dict(self._last_t_sub)))
        cutoff = timestamp_ms - self._history_window_ms
        while self._history and self._history[0].ts_ms < cutoff:
            self._history.popleft()

    def _append_summary_event(self, event: Dict[str, object]) -> None:
        self._summary_events.append(event)
        if len(self._summary_events) > 1000:
            self._summary_events = self._summary_events[-1000:]

    def _summary_loop(self) -> None:
        run_at = self._parse_daily_time(self.engine_config.summary.daily_time)
        while not self._stop.is_set():
            now = datetime.now()
            today_key = now.strftime("%Y-%m-%d")
            target = datetime.combine(now.date(), run_at)
            if now >= target:
                if self._summary_last_date != today_key:
                    self._summary_last_date = today_key
                    self._generate_daily_summary()
                next_run = target + timedelta(days=1)
            else:
                next_run = target
            wait_sec = max(5.0, (next_run - now).total_seconds())
            self._stop.wait(timeout=min(wait_sec, 60.0))

    def _generate_daily_summary(self) -> None:
        payload = DailySummarizer(self._ensure_llm()).summarize(list(self._summary_events))
        payload["count"] = len(self._summary_events)
        self._last_summary_payload = payload
        self._emit("DailySummaryReady", self._now_ms(), payload)

    def _parse_daily_time(self, value: str) -> dt_time:
        try:
            hour, minute = value.split(":", 1)
            return dt_time(hour=int(hour), minute=int(minute))
        except Exception:
            return dt_time(hour=22, minute=30)

    def _allow_trigger(self, timestamp_ms: int) -> bool:
        if self._mode != "normal":
            return False
        if timestamp_ms < self._cooldown_until_ms:
            return False
        if self._daily_trigger_count >= self.engine_config.trigger.daily_trigger_limit:
            return False
        return True

    def _refresh_daily_counter(self, timestamp_ms: int) -> None:
        date_str = datetime.fromtimestamp(timestamp_ms / 1000.0).strftime("%Y-%m-%d")
        if self._daily_date is None:
            self._daily_date = date_str
            return
        if date_str != self._daily_date:
            self._daily_date = date_str
            self._daily_trigger_count = 0
            self._summary_events = []

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

    def _emit(self, event_type: str, timestamp_ms: int, payload: dict) -> None:
        self._event_bus.emit(Event(type=event_type, timestamp_ms=timestamp_ms, payload=payload))

    def _frame_to_bgr(self, frame: VideoFrame):
        if np is None or frame.format.lower() != "bgr":
            return None
        try:
            return np.frombuffer(frame.data, dtype=np.uint8).reshape((frame.height, frame.width, 3))
        except Exception:
            return None

    def _update_preview(self, frame_bgr, timestamp_ms: int) -> None:
        if frame_bgr is None or cv2 is None:
            return
        try:
            ok, encoded = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if not ok:
                return
            with self._preview_lock:
                self._latest_preview_jpeg = encoded.tobytes()
                self._latest_preview_ts_ms = int(timestamp_ms)
        except Exception:
            return

    def _target_det_from_bbox(self, bbox, frame_w: int, frame_h: int) -> FaceDet:
        x, y, w, h = [int(v) for v in bbox]
        area_ratio = (max(1, w) * max(1, h)) / float(max(1, frame_w * frame_h))
        return FaceDet(
            found=True,
            bbox=(x, y, w, h),
            score=1.0,
            cx=float(x + (w * 0.5)),
            cy=float(y + (h * 0.5)),
            area_ratio=float(area_ratio),
        )

    def _apply_pan_tilt(self, pan_turn: float, tilt_turn: float) -> None:
        self._hardware.set_pan_tilt(float(pan_turn), float(tilt_turn))
        self._last_pan_turn = float(pan_turn)
        self._last_tilt_turn = float(tilt_turn)
        self._last_pan_angle = self._servo_angle_from_turn(
            float(pan_turn),
            self.pi_config.hardware.pan_servo.center_angle,
            self.pi_config.hardware.pan_servo.min_angle,
            self.pi_config.hardware.pan_servo.max_angle,
        )
        self._last_tilt_angle = self._servo_angle_from_turn(
            float(tilt_turn),
            self.pi_config.hardware.tilt_servo.center_angle,
            self.pi_config.hardware.tilt_servo.min_angle,
            self.pi_config.hardware.tilt_servo.max_angle,
        )

    def _servo_angle_from_turn(self, turn: float, center: float, min_angle: float, max_angle: float) -> float:
        span = max(abs(float(min_angle)), abs(float(max_angle)))
        angle = float(center) + (float(turn) * span)
        return max(float(min_angle), min(float(max_angle), angle))

    def _get_pending_owner_sync(self) -> Optional[Dict[str, object]]:
        if self._identity is None:
            return None
        return self._identity.get_pending_sync()

    def _mark_owner_sync_complete(self, embedding_version: str) -> None:
        if self._identity is None:
            return
        self._identity.mark_sync_complete(embedding_version)
        self._identity_state = self._identity.get_status()

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)
