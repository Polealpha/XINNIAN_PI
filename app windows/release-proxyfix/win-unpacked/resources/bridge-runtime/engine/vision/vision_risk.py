from __future__ import annotations

from collections import deque
from typing import Dict, Tuple

from ..core.config import VideoConfig
from ..core.types import VideoFrame
from .expression_classifier import ExpressionClassifier, expression_risk_from_label
from .expression_mediapipe import MediaPipeExpressionClassifier
from .face_detector import FaceDetector
from .frame_decode import decode_gray, decode_rgb, opencv_available

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None
    np = None

try:
    import mediapipe as mp  # type: ignore
except Exception:  # pragma: no cover
    mp = None


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


class OnlineStats:
    def __init__(self) -> None:
        self.count = 0
        self.mean = 0.0
        self.m2 = 0.0

    def update(self, value: float) -> None:
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        delta2 = value - self.mean
        self.m2 += delta * delta2

    @property
    def std(self) -> float:
        if self.count < 2:
            return max(1e-6, abs(self.mean))
        return (self.m2 / (self.count - 1)) ** 0.5


class VisionRiskScorer:
    def __init__(self, config: VideoConfig) -> None:
        self.config = config
        self._last_risk = 0.0
        self._prev_gray = None
        self._ear_stats = OnlineStats()
        self._blink_times = deque()
        self._blink_closed = False
        self._last_expr_id = -1
        self._last_expr_conf = 0.0
        self._last_expr_ts = 0
        self._expr = ExpressionClassifier(
            model_path=self.config.expression_model_path,
            model_url=self.config.expression_model_url,
            enabled=self.config.expression_enabled,
        )
        self._expr_mp = MediaPipeExpressionClassifier(
            model_path=getattr(self.config, "expression_mp_model_path", "models/mediapipe/face_landmarker.task"),
            model_url=getattr(self.config, "expression_mp_model_url", ""),
            enabled=self.config.expression_enabled,
        )
        self._expr_backend = str(getattr(self.config, "expression_backend", "mediapipe_tasks")).lower().strip()
        # Fallback detector for cases where FaceMesh fails on low-quality MJPEG frames.
        self._expr_face_detector = FaceDetector(
            {
                "detector": "mediapipe",
                "min_detection_confidence": 0.20,
                "min_face_area_ratio": 0.001,
                "max_face_area_ratio": 0.95,
                "multi_face_policy": "largest",
            }
        )
        self._face_mesh = None
        if mp is not None:
            try:
                self._face_mesh = mp.solutions.face_mesh.FaceMesh(
                    max_num_faces=1,
                    refine_landmarks=True,
                    min_detection_confidence=0.35,
                    min_tracking_confidence=0.35,
                )
            except Exception:
                self._face_mesh = None
        # Default to enabling center-crop fallback for low-quality MJPEG streams where
        # face detector may intermittently miss, but quality gates below still block
        # black/stale frames.
        self._allow_center_expr_fallback = bool(
            getattr(self.config, "expression_allow_center_fallback", True)
        )

    def reset(self) -> None:
        self._last_risk = 0.0
        self._prev_gray = None
        self._ear_stats = OnlineStats()
        self._blink_times.clear()
        self._blink_closed = False
        self._last_expr_id = -1
        self._last_expr_conf = 0.0
        self._last_expr_ts = 0

    def baseline(self) -> Dict[str, float]:
        blink_rate = len(self._blink_times) * 1.0
        return {
            "ear_mean": float(self._ear_stats.mean),
            "ear_std": float(self._ear_stats.std),
            "blink_rate_1m": blink_rate,
            "expr_model_ready": 1.0 if (self._expr.ready or self._expr_mp.ready) else 0.0,
        }

    def score(self, frame: VideoFrame, face_present: bool) -> Tuple[float, Dict[str, float]]:
        base_meta = {
            "expression_class_id": -1.0,
            "expression_confidence": 0.0,
            "expression_risk": 0.0,
            "expression_valid": 0.0,
            "expr_model_ready": 1.0 if (self._expr.ready or self._expr_mp.ready) else 0.0,
            "expr_reason": "no_face",
            "frame_decode_ok": 0.0,
            "fer_invoked": 0.0,
        }
        if not face_present:
            self._prev_gray = None
            self._last_risk = 0.0
            return 0.0, {"face_ok": 0.0, "V_total": 0.0, **base_meta}

        rgb = decode_rgb(frame)
        if rgb is None or cv2 is None or np is None:
            return self._fallback_score(frame, "decode_rgb_failed")

        if not opencv_available() or self._face_mesh is None:
            return self._score_without_mesh(frame, rgb, "mesh_unavailable")

        results = self._face_mesh.process(rgb)
        if not results.multi_face_landmarks:
            return self._score_without_mesh(frame, rgb, "mesh_no_landmarks")

        landmarks = results.multi_face_landmarks[0].landmark
        ear = self._compute_ear(landmarks)
        if ear > 0:
            self._ear_stats.update(ear)

        now_ms = frame.timestamp_ms
        blink_rate = self._update_blink_rate(now_ms, ear)
        pitch, yaw = self._estimate_head_pose(landmarks, rgb.shape)
        gaze_score = self._estimate_gaze(landmarks)

        fatigue = clamp01((self._ear_stats.mean - ear) / (3 * max(1e-6, self._ear_stats.std)))
        attention_drop = clamp01(
            0.5 * clamp01((pitch - self.config.pitch_down_thr) / max(1e-6, self.config.pitch_span))
            + 0.5 * clamp01((self.config.gaze_thr - gaze_score) / max(1e-6, self.config.gaze_span))
        )
        base_v = clamp01(self.config.w_fatigue * fatigue + self.config.w_attention * attention_drop)

        expr_label = "unknown"
        expr_conf = 0.0
        expr_risk = 0.0
        expr_detail: Dict[str, float] = {}
        expr_source = "none"
        mp_label = "unknown"
        mp_conf = 0.0
        mp_detail: Dict[str, float] = {}
        fer_label = "unknown"
        fer_conf = 0.0
        fer_detail: Dict[str, float] = {}

        if self._expr_backend in {"mediapipe", "mediapipe_tasks", "hybrid"} and self._expr_mp.ready:
            mp_label, mp_conf, mp_detail = self._expr_mp.predict(rgb)
            expr_label, expr_conf, expr_detail = mp_label, mp_conf, mp_detail
            expr_risk = expression_risk_from_label(mp_label)
            expr_source = "mp_tasks"

        should_run_fer = (
            self._expr.ready
            and self._expr_backend in {"ferplus", "hybrid"}
            and (
                self._expr_backend == "hybrid"
                or self._should_try_fer_fallback(mp_label, mp_conf, mp_detail)
            )
        )
        if should_run_fer:
            face_crop = self._extract_face_crop(rgb, landmarks)
            if face_crop is None:
                face_crop = rgb
            fer_label, fer_conf, fer_detail = self._expr.predict(face_crop)
            if self._expr_backend == "hybrid":
                expr_label, expr_conf, expr_source = self._pick_hybrid_expression(
                    mp_label,
                    mp_conf,
                    fer_label,
                    fer_conf,
                )
                expr_detail = {**mp_detail, **fer_detail, "hybrid_pick": 1.0 if expr_source == "ferplus" else 0.0}
            else:
                expr_label, expr_conf, expr_detail = fer_label, fer_conf, fer_detail
                expr_source = "ferplus"
            expr_risk = expression_risk_from_label(expr_label)

        min_conf = float(self.config.expression_min_confidence)
        if expr_conf >= min_conf:
            v_total = clamp01((1.0 - self.config.w_expression) * base_v + self.config.w_expression * expr_risk)
        else:
            v_total = base_v

        self._last_risk = v_total
        result = {
            "face_ok": 1.0,
            "ear": float(ear),
            "blink_rate_1m": float(blink_rate),
            "head_pitch": float(pitch),
            "head_yaw": float(yaw),
            "gaze_score": float(gaze_score),
            "fatigue": float(fatigue),
            "attention_drop": float(attention_drop),
            "expression_class_id": float(ExpressionClassifier.label_to_id(expr_label)),
            "expression_confidence": float(expr_conf),
            "expression_risk": float(expr_risk),
            "expression_valid": 1.0
            if (ExpressionClassifier.label_to_id(expr_label) >= 0 and expr_conf >= min_conf)
            else 0.0,
            "expr_model_ready": 1.0 if (self._expr.ready or self._expr_mp.ready) else 0.0,
            "expr_reason": "ok"
            if (ExpressionClassifier.label_to_id(expr_label) >= 0 and expr_conf >= min_conf)
            else "low_conf_or_unknown",
            "expr_source": expr_source,
            "frame_decode_ok": 1.0,
            "fer_invoked": 1.0 if should_run_fer else 0.0,
            "V_total": float(v_total),
        }
        if expr_detail:
            result.update(expr_detail)
        result = self._stabilize_expression(result, frame.timestamp_ms)
        return v_total, result

    def _fallback_score(self, frame: VideoFrame, reason_prefix: str = "fallback") -> Tuple[float, Dict[str, float]]:
        base_meta = {
            "expression_class_id": -1.0,
            "expression_confidence": 0.0,
            "expression_risk": 0.0,
            "expression_valid": 0.0,
            "expr_model_ready": 1.0 if (self._expr.ready or self._expr_mp.ready) else 0.0,
            "expr_reason": f"{reason_prefix}_no_expr",
            "frame_decode_ok": 0.0,
            "fer_invoked": 0.0,
        }
        if not opencv_available():
            return self._last_risk, {"face_ok": 1.0, "V_total": float(self._last_risk), **base_meta}
        gray = decode_gray(frame)
        if gray is None or cv2 is None or np is None:
            return self._last_risk, {"face_ok": 1.0, "V_total": float(self._last_risk), **base_meta}

        motion = 0.0
        if self._prev_gray is not None:
            diff = cv2.absdiff(gray, self._prev_gray)
            motion = float(diff.mean() / 255.0)

        brightness = float(gray.mean() / 255.0)
        stillness = max(0.0, 0.02 - motion) * 10.0
        low_light = max(0.0, 0.25 - brightness) * 2.0
        risk = min(1.0, stillness + low_light)

        self._prev_gray = gray
        self._last_risk = risk
        merged = dict(base_meta)
        merged.update({"face_ok": 1.0, "V_total": float(risk), "frame_decode_ok": 1.0})
        return risk, merged

    def _score_without_mesh(
        self, frame: VideoFrame, rgb, reason_prefix: str = "mesh_unavailable"
    ) -> Tuple[float, Dict[str, float]]:
        # Keep baseline visual risk from motion/light fallback.
        base_risk, base_sub = self._fallback_score(frame)
        result = dict(base_sub or {})
        result["face_ok"] = 0.0
        result["expr_reason"] = f"{reason_prefix}_no_expr"
        result["frame_decode_ok"] = 1.0

        mp_label = "unknown"
        mp_conf = 0.0
        mp_detail: Dict[str, float] = {}
        fer_label = "unknown"
        fer_conf = 0.0
        fer_detail: Dict[str, float] = {}
        should_run_fer = False

        # Prefer mediapipe tasks blendshape emotion when available.
        if self._expr_mp.ready and self._expr_backend in {"mediapipe", "mediapipe_tasks", "hybrid"}:
            mp_label, mp_conf, mp_detail = self._expr_mp.predict(rgb)
            expr_id = ExpressionClassifier.label_to_id(mp_label)
            expr_risk = expression_risk_from_label(mp_label)
            result.update(
                {
                    "expression_class_id": float(expr_id),
                    "expression_confidence": float(mp_conf),
                    "expression_risk": float(expr_risk),
                    "expression_valid": 1.0 if (expr_id >= 0 and mp_conf >= float(self.config.expression_min_confidence)) else 0.0,
                    "expr_reason": "mp_tasks_ok" if (expr_id >= 0 and mp_conf >= float(self.config.expression_min_confidence)) else "mp_tasks_low_conf",
                    "expr_source": "mp_tasks",
                    "fer_invoked": 0.0,
                }
            )
            if mp_detail:
                result.update(mp_detail)
            if (
                mp_conf >= self.config.expression_min_confidence
                and expr_id >= 0
                and not self._should_try_fer_fallback(mp_label, mp_conf, mp_detail)
                and self._expr_backend != "hybrid"
            ):
                base_risk = clamp01((1.0 - self.config.w_expression) * base_risk + self.config.w_expression * expr_risk)
                result["V_total"] = float(base_risk)
                self._last_risk = base_risk
                return base_risk, result
            # If mediapipe could not detect a valid expression, fall through to FER+ fallback.

        if not self._expr.ready:
            result["expr_reason"] = f"{reason_prefix}_model_not_ready"
            result["V_total"] = float(base_risk)
            self._last_risk = base_risk
            return base_risk, result

        face_det = self._expr_face_detector.detect(frame) if self._expr_face_detector else None
        used_center_crop = False
        face_crop = None
        if face_det and face_det.found and face_det.bbox:
            result["face_ok"] = 1.0
            face_crop = self._crop_by_bbox(rgb, face_det.bbox)
        elif self._allow_center_expr_fallback:
            face_crop = self._center_face_crop(rgb)
            used_center_crop = face_crop is not None
            if used_center_crop:
                result["face_ok"] = max(float(result.get("face_ok", 0.0)), 0.5)

        if face_crop is not None:
            should_run_fer = (
                self._expr_backend in {"ferplus", "hybrid"}
                and (
                    self._expr_backend == "hybrid"
                    or self._should_try_fer_fallback(mp_label, mp_conf, mp_detail)
                )
            )
            if not should_run_fer:
                result["V_total"] = float(base_risk)
                self._last_risk = base_risk
                return base_risk, result
            q_ok, q_reason = self._is_face_crop_quality_ok(face_crop)
            if not q_ok:
                result["expr_reason"] = f"{reason_prefix}_low_quality_{q_reason}"
                result["expression_class_id"] = -1.0
                result["expression_confidence"] = 0.0
                result["expression_risk"] = 0.0
                result["expression_valid"] = 0.0
                result["fer_invoked"] = 0.0
                result["V_total"] = float(base_risk)
                self._last_risk = base_risk
                return base_risk, result
            fer_label, fer_conf, fer_detail = self._expr.predict(face_crop)
            if self._expr_backend == "hybrid":
                expr_label, expr_conf, expr_source = self._pick_hybrid_expression(
                    mp_label,
                    mp_conf,
                    fer_label,
                    fer_conf,
                )
                expr_detail = {**mp_detail, **fer_detail, "hybrid_pick": 1.0 if expr_source == "ferplus" else 0.0}
            else:
                expr_label, expr_conf, expr_source = fer_label, fer_conf, "ferplus"
                expr_detail = fer_detail
            expr_id = ExpressionClassifier.label_to_id(expr_label)
            expr_risk = expression_risk_from_label(expr_label)
            result.update(
                {
                    "expression_class_id": float(expr_id),
                    "expression_confidence": float(expr_conf),
                    "expression_risk": float(expr_risk),
                    "expression_valid": 1.0 if (expr_id >= 0 and expr_conf >= float(self.config.expression_min_confidence)) else 0.0,
                    "expr_reason": (
                        f"{reason_prefix}_{'center' if used_center_crop else 'det'}_ok"
                        if (expr_id >= 0 and expr_conf > 0.0)
                        else f"{reason_prefix}_{'center' if used_center_crop else 'det'}_low_conf"
                    ),
                    "expr_source": expr_source,
                    "fer_invoked": 1.0 if should_run_fer else 0.0,
                }
            )
            if expr_detail:
                result.update(expr_detail)
            if expr_conf >= self.config.expression_min_confidence:
                base_risk = clamp01((1.0 - self.config.w_expression) * base_risk + self.config.w_expression * expr_risk)
        else:
            result["expr_reason"] = (
                f"{reason_prefix}_no_face_for_expr"
                if not self._allow_center_expr_fallback
                else f"{reason_prefix}_no_crop"
            )
            result["expression_class_id"] = -1.0
            result["expression_confidence"] = 0.0
            result["expression_risk"] = 0.0
            result["expression_valid"] = 0.0
            result["fer_invoked"] = 0.0

        result["V_total"] = float(base_risk)
        result = self._stabilize_expression(result, frame.timestamp_ms)
        self._last_risk = base_risk
        return base_risk, result

    def _should_try_fer_fallback(self, expr_label: str, expr_conf: float, detail: Dict[str, float]) -> bool:
        expr_id = ExpressionClassifier.label_to_id(expr_label)
        if expr_id < 0 or expr_conf <= 0.0:
            return True
        if expr_conf < float(self.config.expression_min_confidence):
            return True
        if str(expr_label).lower() != "neutral":
            return False
        non_neutral_max = float(detail.get("mp_non_neutral_max", 0.0) or 0.0)
        top2_gap = float(detail.get("mp_top2_gap", 0.0) or 0.0)
        # Neutral from blendshapes is often sticky on low-quality MJPEG.
        # Re-run FER+ when neutral confidence structure looks flat.
        if non_neutral_max < 0.24:
            return True
        if top2_gap < 0.22:
            return True
        return False

    def _pick_hybrid_expression(
        self,
        mp_label: str,
        mp_conf: float,
        fer_label: str,
        fer_conf: float,
    ) -> Tuple[str, float, str]:
        mp_id = ExpressionClassifier.label_to_id(mp_label)
        fer_id = ExpressionClassifier.label_to_id(fer_label)
        mp_valid = mp_id >= 0 and mp_conf > 0.0
        fer_valid = fer_id >= 0 and fer_conf > 0.0

        if not mp_valid and not fer_valid:
            return "unknown", 0.0, "none"
        if fer_valid and not mp_valid:
            return fer_label, fer_conf, "ferplus"
        if mp_valid and not fer_valid:
            return mp_label, mp_conf, "mp_tasks"

        mp_non_neutral = str(mp_label).lower() != "neutral"
        fer_non_neutral = str(fer_label).lower() != "neutral"

        if fer_non_neutral and not mp_non_neutral:
            return fer_label, fer_conf, "ferplus"
        if mp_non_neutral and not fer_non_neutral:
            return mp_label, mp_conf, "mp_tasks"

        # Both same polarity: prefer higher confidence with slight FER bias in ties.
        if fer_conf >= (mp_conf * 0.95):
            return fer_label, fer_conf, "ferplus"
        return mp_label, mp_conf, "mp_tasks"

    def _is_face_crop_quality_ok(self, crop) -> Tuple[bool, str]:
        if cv2 is None or np is None or crop is None:
            return False, "invalid"
        try:
            gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
            mean_v = float(gray.mean())
            std_v = float(gray.std())
            # Too dark/bright or too flat => likely black frame / invalid crop.
            if mean_v < 18.0:
                return False, "dark"
            if mean_v > 245.0:
                return False, "bright"
            if std_v < 6.0:
                return False, "flat"
            h, w = gray.shape[:2]
            if h < 18 or w < 18:
                return False, "small"
            return True, "ok"
        except Exception:
            return False, "exception"

    def _crop_by_bbox(self, rgb, bbox):
        if np is None:
            return None
        try:
            h, w = rgb.shape[:2]
            x, y, bw, bh = [int(v) for v in bbox]
            if bw <= 0 or bh <= 0:
                return None
            cx = x + bw * 0.5
            cy = y + bh * 0.5
            bw2 = bw * 1.25
            bh2 = bh * 1.35
            x1 = int(max(0, cx - bw2 * 0.5))
            y1 = int(max(0, cy - bh2 * 0.5))
            x2 = int(min(w, cx + bw2 * 0.5))
            y2 = int(min(h, cy + bh2 * 0.5))
            if x2 - x1 < 8 or y2 - y1 < 8:
                return None
            return rgb[y1:y2, x1:x2]
        except Exception:
            return None

    def _stabilize_expression(self, result: Dict[str, float], ts_ms: int) -> Dict[str, float]:
        expr_id = int(result.get("expression_class_id", -1))
        expr_conf = float(result.get("expression_confidence", 0.0))
        if expr_id >= 0 and expr_conf > 0.0:
            self._last_expr_id = expr_id
            self._last_expr_conf = expr_conf
            self._last_expr_ts = int(ts_ms)
            return result

        # Keep last valid expression briefly to avoid 0.2~0.5s flicker to unknown.
        if self._last_expr_id >= 0 and (int(ts_ms) - int(self._last_expr_ts)) <= 1600:
            held_conf = max(0.0, min(0.99, self._last_expr_conf * 0.86))
            if held_conf >= float(self.config.expression_min_confidence):
                held_label = ExpressionClassifier.id_to_label(self._last_expr_id)
                held_risk = expression_risk_from_label(held_label)
                result["expression_class_id"] = float(self._last_expr_id)
                result["expression_confidence"] = float(held_conf)
                result["expression_risk"] = float(held_risk)
                result["expression_valid"] = 1.0
                prev_reason = str(result.get("expr_reason", "") or "unknown")
                result["expr_reason"] = f"{prev_reason}_hold"
                result["expr_source"] = str(result.get("expr_source", "hold") or "hold")
        return result

    def _center_face_crop(self, rgb):
        if np is None:
            return None
        try:
            h, w = rgb.shape[:2]
            if h < 16 or w < 16:
                return None
            # center crop tuned for desktop portrait framing (head near mid-lower area).
            crop_w = int(w * 0.62)
            crop_h = int(h * 0.72)
            cx = int(w * 0.5)
            cy = int(h * 0.58)
            x1 = max(0, cx - crop_w // 2)
            y1 = max(0, cy - crop_h // 2)
            x2 = min(w, x1 + crop_w)
            y2 = min(h, y1 + crop_h)
            if x2 - x1 < 8 or y2 - y1 < 8:
                return None
            return rgb[y1:y2, x1:x2]
        except Exception:
            return None

    def _compute_ear(self, landmarks) -> float:
        # Mediapipe face mesh indices for eyes
        left = [33, 160, 158, 133, 153, 144]
        right = [362, 385, 387, 263, 373, 380]
        def _dist(a, b):
            dx = landmarks[a].x - landmarks[b].x
            dy = landmarks[a].y - landmarks[b].y
            return (dx * dx + dy * dy) ** 0.5
        left_ear = (_dist(left[1], left[5]) + _dist(left[2], left[4])) / (2 * max(1e-6, _dist(left[0], left[3])))
        right_ear = (_dist(right[1], right[5]) + _dist(right[2], right[4])) / (2 * max(1e-6, _dist(right[0], right[3])))
        ear = (left_ear + right_ear) / 2.0
        return float(ear)

    def _update_blink_rate(self, now_ms: int, ear: float) -> float:
        threshold = max(0.12, self._ear_stats.mean - 0.5 * max(1e-6, self._ear_stats.std))
        if ear < threshold and not self._blink_closed:
            self._blink_closed = True
        elif ear >= threshold and self._blink_closed:
            self._blink_closed = False
            self._blink_times.append(now_ms)
        window_ms = 60_000
        while self._blink_times and now_ms - self._blink_times[0] > window_ms:
            self._blink_times.popleft()
        return len(self._blink_times)

    def _estimate_head_pose(self, landmarks, shape) -> Tuple[float, float]:
        if cv2 is None or np is None:
            return 0.0, 0.0
        height, width = shape[0], shape[1]
        image_points = np.array([
            (landmarks[1].x * width, landmarks[1].y * height),   # nose tip
            (landmarks[152].x * width, landmarks[152].y * height),  # chin
            (landmarks[33].x * width, landmarks[33].y * height),  # left eye
            (landmarks[263].x * width, landmarks[263].y * height),  # right eye
            (landmarks[61].x * width, landmarks[61].y * height),  # left mouth
            (landmarks[291].x * width, landmarks[291].y * height),  # right mouth
        ], dtype="double")
        model_points = np.array([
            (0.0, 0.0, 0.0),
            (0.0, -63.6, -12.5),
            (-43.3, 32.7, -26.0),
            (43.3, 32.7, -26.0),
            (-28.9, -28.9, -24.1),
            (28.9, -28.9, -24.1),
        ])
        focal_length = width
        center = (width / 2, height / 2)
        camera_matrix = np.array(
            [[focal_length, 0, center[0]], [0, focal_length, center[1]], [0, 0, 1]], dtype="double"
        )
        dist_coeffs = np.zeros((4, 1))
        success, rotation_vector, _ = cv2.solvePnP(model_points, image_points, camera_matrix, dist_coeffs, flags=cv2.SOLVEPNP_ITERATIVE)
        if not success:
            return 0.0, 0.0
        rotation_matrix, _ = cv2.Rodrigues(rotation_vector)
        sy = (rotation_matrix[0, 0] ** 2 + rotation_matrix[1, 0] ** 2) ** 0.5
        singular = sy < 1e-6
        if not singular:
            pitch = float(np.degrees(np.arctan2(rotation_matrix[2, 1], rotation_matrix[2, 2])))
            yaw = float(np.degrees(np.arctan2(-rotation_matrix[2, 0], sy)))
        else:
            pitch = float(np.degrees(np.arctan2(-rotation_matrix[1, 2], rotation_matrix[1, 1])))
            yaw = float(np.degrees(np.arctan2(-rotation_matrix[2, 0], sy)))
        return pitch, yaw

    def _estimate_gaze(self, landmarks) -> float:
        # Iris landmarks: left 468-472, right 473-477
        try:
            left_iris = [468, 469, 470, 471, 472]
            right_iris = [473, 474, 475, 476, 477]
            left_eye = [33, 133]
            right_eye = [362, 263]
            left_x = sum(landmarks[i].x for i in left_iris) / len(left_iris)
            right_x = sum(landmarks[i].x for i in right_iris) / len(right_iris)
            left_ratio = (left_x - landmarks[left_eye[0]].x) / max(1e-6, (landmarks[left_eye[1]].x - landmarks[left_eye[0]].x))
            right_ratio = (right_x - landmarks[right_eye[0]].x) / max(1e-6, (landmarks[right_eye[1]].x - landmarks[right_eye[0]].x))
            center_ratio = (left_ratio + right_ratio) / 2.0
            gaze_score = 1.0 - min(1.0, abs(center_ratio - 0.5) * 2.0)
            return float(clamp01(gaze_score))
        except Exception:
            return 0.5

    def _extract_face_crop(self, rgb, landmarks):
        if np is None:
            return None
        try:
            height, width = rgb.shape[:2]
            xs = [float(lm.x) for lm in landmarks]
            ys = [float(lm.y) for lm in landmarks]
            x1 = max(0.0, min(xs))
            y1 = max(0.0, min(ys))
            x2 = min(1.0, max(xs))
            y2 = min(1.0, max(ys))
            if x2 <= x1 or y2 <= y1:
                return None
            # add margin to include brows/jaw for expression cues
            cx = (x1 + x2) * 0.5
            cy = (y1 + y2) * 0.5
            bw = (x2 - x1) * 1.35
            bh = (y2 - y1) * 1.45
            x1p = int(max(0, (cx - bw * 0.5) * width))
            y1p = int(max(0, (cy - bh * 0.5) * height))
            x2p = int(min(width, (cx + bw * 0.5) * width))
            y2p = int(min(height, (cy + bh * 0.5) * height))
            if x2p - x1p < 8 or y2p - y1p < 8:
                return None
            return rgb[y1p:y2p, x1p:x2p]
        except Exception:
            return None
