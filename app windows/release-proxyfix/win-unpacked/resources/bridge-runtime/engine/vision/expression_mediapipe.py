from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple
from urllib.request import urlretrieve

try:
    import mediapipe as mp  # type: ignore
except Exception:  # pragma: no cover
    mp = None


_LABELS = [
    "neutral",
    "happiness",
    "surprise",
    "sadness",
    "anger",
    "disgust",
    "fear",
    "contempt",
]


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _avg(values) -> float:
    vals = [float(v) for v in values]
    if not vals:
        return 0.0
    return float(sum(vals) / len(vals))


class MediaPipeExpressionClassifier:
    """
    Emotion estimation from MediaPipe Face Landmarker blendshapes.
    Output interface matches the ONNX FER classifier.
    """

    LABELS = _LABELS

    def __init__(self, model_path: str, model_url: str = "", enabled: bool = True) -> None:
        self.enabled = bool(enabled)
        self.ready = False
        self.model_path = Path(model_path)
        self.model_url = str(model_url or "").strip()
        self._landmarker = None
        self._vision = None

        if not self.enabled or mp is None:
            return
        self._ensure_model()
        self._load()

    def _ensure_model(self) -> None:
        if self.model_path.exists() or not self.model_url:
            return
        try:
            self.model_path.parent.mkdir(parents=True, exist_ok=True)
            urlretrieve(self.model_url, str(self.model_path))
        except Exception:
            return

    def _load(self) -> None:
        if mp is None or not self.model_path.exists():
            return
        try:
            from mediapipe.tasks import python  # type: ignore
            from mediapipe.tasks.python import vision  # type: ignore

            opts = vision.FaceLandmarkerOptions(
                base_options=python.BaseOptions(model_asset_path=str(self.model_path)),
                output_face_blendshapes=True,
                output_facial_transformation_matrixes=False,
                num_faces=1,
                min_face_detection_confidence=0.25,
                min_face_presence_confidence=0.25,
                min_tracking_confidence=0.25,
            )
            self._landmarker = vision.FaceLandmarker.create_from_options(opts)
            self._vision = vision
            self.ready = True
        except Exception:
            self._landmarker = None
            self._vision = None
            self.ready = False

    def predict(self, frame_rgb) -> Tuple[str, float, Dict[str, float]]:
        if not self.ready or self._landmarker is None or mp is None:
            return "unknown", 0.0, {}
        try:
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
            result = self._landmarker.detect(mp_image)
            blend = (result.face_blendshapes or [])
            if not blend:
                return "unknown", 0.0, {"mp_expr_reason": "no_face"}
            categories = blend[0]
            b = {c.category_name: float(c.score) for c in categories}
            scores = self._emotion_scores_from_blendshapes(b)
            if not scores:
                return "unknown", 0.0, {"mp_expr_reason": "no_scores"}

            # Keep temperature moderate; over-sharpening makes "neutral" sticky.
            import math

            logits = {k: math.exp(v * 2.8) for k, v in scores.items()}
            denom = sum(logits.values()) or 1.0
            probs = {k: float(v / denom) for k, v in logits.items()}
            best_label = max(probs, key=probs.get)
            best_conf = float(probs[best_label])
            neutral_conf = float(probs.get("neutral", 0.0))
            sorted_probs = sorted(probs.values(), reverse=True)
            second = float(sorted_probs[1]) if len(sorted_probs) > 1 else 0.0
            top2_gap = best_conf - second
            non_neutral_items = [(k, float(v)) for k, v in probs.items() if k != "neutral"]
            non_neutral_label = max(non_neutral_items, key=lambda x: x[1])[0] if non_neutral_items else "neutral"
            non_neutral_max = max((v for _, v in non_neutral_items), default=0.0)

            detail = {
                "mp_expr_reason": "ok",
                "mp_non_neutral_label": non_neutral_label,
                "mp_non_neutral_max": float(non_neutral_max),
                "mp_top2_gap": float(top2_gap),
                **{f"mp_expr_prob_{k}": float(v) for k, v in probs.items()},
            }

            # Very low-confidence frames should not force an emotion class.
            # Keep neutral if neutral itself is sufficiently strong; otherwise unknown.
            if best_conf < 0.10:
                if neutral_conf >= 0.16:
                    detail["mp_expr_reason"] = "low_conf_neutral"
                    return "neutral", neutral_conf, detail
                detail["mp_expr_reason"] = "low_conf"
                return "unknown", 0.0, detail
            # If a weak non-neutral barely beats neutral, keep neutral to reduce flicker.
            if best_label != "neutral" and best_conf < 0.16 and (neutral_conf + 0.02) >= best_conf:
                detail["mp_expr_reason"] = "weak_non_neutral"
                return "neutral", neutral_conf, detail
            if best_conf < 0.12 and non_neutral_max < 0.10:
                detail["mp_expr_reason"] = "low_conf"
                return "unknown", 0.0, detail
            # If neutral barely leads with high non-neutral competitor, allow a switch.
            if best_label == "neutral" and non_neutral_max >= 0.16 and top2_gap < 0.18:
                detail["mp_expr_reason"] = "neutral_override"
                return non_neutral_label, min(0.99, non_neutral_max * 1.12), detail
            return best_label, best_conf, detail
        except Exception:
            return "unknown", 0.0, {"mp_expr_reason": "exception"}

    def _emotion_scores_from_blendshapes(self, b: Dict[str, float]) -> Dict[str, float]:
        def g(name: str) -> float:
            return float(b.get(name, 0.0))

        smile = _avg([g("mouthSmileLeft"), g("mouthSmileRight")])
        frown = _avg([g("mouthFrownLeft"), g("mouthFrownRight")])
        brow_down = _avg([g("browDownLeft"), g("browDownRight")])
        brow_up = _avg([g("browInnerUp"), g("browOuterUpLeft"), g("browOuterUpRight")])
        eye_wide = _avg([g("eyeWideLeft"), g("eyeWideRight")])
        eye_squint = _avg([g("eyeSquintLeft"), g("eyeSquintRight")])
        nose_sneer = _avg([g("noseSneerLeft"), g("noseSneerRight")])
        mouth_press = _avg([g("mouthPressLeft"), g("mouthPressRight")])
        mouth_open = max(g("jawOpen"), g("mouthFunnel"), g("mouthPucker"))
        mouth_stretch = _avg([g("mouthStretchLeft"), g("mouthStretchRight")])
        mouth_upper = _avg([g("mouthUpperUpLeft"), g("mouthUpperUpRight"), g("mouthShrugUpper")])

        happiness = _clamp01(0.74 * smile + 0.18 * _avg([g("cheekSquintLeft"), g("cheekSquintRight")]) + 0.08 * _avg([g("mouthDimpleLeft"), g("mouthDimpleRight")]))
        surprise = _clamp01(0.50 * mouth_open + 0.27 * eye_wide + 0.20 * brow_up + 0.03 * (1.0 - eye_squint))
        anger = _clamp01(0.46 * brow_down + 0.21 * eye_squint + 0.16 * mouth_press + 0.17 * nose_sneer)
        sadness = _clamp01(0.52 * frown + 0.26 * brow_up + 0.10 * (1.0 - eye_wide) + 0.12 * mouth_press)
        disgust = _clamp01(0.56 * nose_sneer + 0.28 * mouth_upper + 0.16 * mouth_press)
        fear = _clamp01(0.38 * eye_wide + 0.28 * mouth_open + 0.20 * brow_up + 0.14 * mouth_stretch)
        contempt = _clamp01(0.60 * abs(g("mouthSmileLeft") - g("mouthSmileRight")) + 0.40 * abs(g("mouthPressLeft") - g("mouthPressRight")))

        expressive = max(happiness, surprise, anger, sadness, disgust, fear, contempt)
        neutral = _clamp01(0.06 + 0.42 * (1.0 - expressive) - 0.08 * (brow_down + frown))

        return {
            "neutral": neutral,
            "happiness": happiness,
            "surprise": surprise,
            "sadness": sadness,
            "anger": anger,
            "disgust": disgust,
            "fear": fear,
            "contempt": contempt,
        }
