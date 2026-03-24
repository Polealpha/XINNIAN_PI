from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.request import urlretrieve

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None
    np = None


def _softmax(values: "np.ndarray") -> "np.ndarray":
    shifted = values - values.max()
    exp_v = np.exp(shifted)
    denom = float(exp_v.sum()) if exp_v.size else 1.0
    if denom <= 0:
        return np.zeros_like(values, dtype=np.float32)
    return exp_v / denom


class ExpressionClassifier:
    """
    Emotion FER+ (8-class) ONNX classifier.
    Labels: neutral, happiness, surprise, sadness, anger, disgust, fear, contempt
    """

    LABELS = [
        "neutral",
        "happiness",
        "surprise",
        "sadness",
        "anger",
        "disgust",
        "fear",
        "contempt",
    ]

    def __init__(self, model_path: str, model_url: str = "", enabled: bool = True) -> None:
        self.enabled = bool(enabled)
        self.ready = False
        self.model_path = Path(model_path)
        self.model_url = str(model_url or "").strip()
        self._net = None
        if not self.enabled or cv2 is None or np is None:
            return
        self._ensure_model()
        self._load_model()

    def _ensure_model(self) -> None:
        if self.model_path.exists() or not self.model_url:
            return
        try:
            self.model_path.parent.mkdir(parents=True, exist_ok=True)
            urlretrieve(self.model_url, str(self.model_path))
        except Exception:
            return

    def _load_model(self) -> None:
        if cv2 is None:
            return
        if not self.model_path.exists():
            return
        try:
            self._net = cv2.dnn.readNetFromONNX(str(self.model_path))
            self.ready = True
        except Exception:
            self._net = None
            self.ready = False

    def predict(self, face_rgb: "np.ndarray") -> Tuple[str, float, Dict[str, float]]:
        if not self.ready or self._net is None or cv2 is None or np is None:
            return "unknown", 0.0, {}
        try:
            gray = cv2.cvtColor(face_rgb, cv2.COLOR_RGB2GRAY)
            gray = cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA)
            # FER+ ONNX model expects grayscale intensity scale close to original
            # 0..255 domain. Dividing to 0..1 collapses logits and yields near-constant
            # neutral ~0.74 on diverse inputs.
            inp = gray.astype(np.float32)
            blob = inp[np.newaxis, np.newaxis, :, :]
            self._net.setInput(blob)
            out = self._net.forward()
            logits = out.reshape(-1).astype(np.float32)
            if logits.size < len(self.LABELS):
                return "unknown", 0.0, {}
            logits = logits[: len(self.LABELS)]
            probs = _softmax(logits)
            idx = int(np.argmax(probs))
            conf = float(probs[idx])
            label = self.LABELS[idx]
            sorted_probs = np.sort(probs)[::-1]
            second = float(sorted_probs[1]) if sorted_probs.size > 1 else 0.0
            margin = conf - second
            detail = {f"expr_prob_{k}": float(v) for k, v in zip(self.LABELS, probs)}
            detail["expr_prob_margin"] = float(margin)
            if label == "neutral" and probs.size > 1:
                non_neutral_idx = int(np.argmax(probs[1:]) + 1)
                non_neutral_conf = float(probs[non_neutral_idx])
                detail["expr_non_neutral_candidate"] = float(non_neutral_idx)
                detail["expr_non_neutral_conf"] = float(non_neutral_conf)
                if non_neutral_conf >= 0.22 and margin < 0.35:
                    label = self.LABELS[non_neutral_idx]
                    conf = min(0.99, non_neutral_conf * 1.25)
                    detail["expr_override"] = 1.0
            return label, conf, detail
        except Exception:
            return "unknown", 0.0, {}

    @classmethod
    def label_to_id(cls, label: str) -> int:
        normalized = str(label or "").strip().lower()
        try:
            return cls.LABELS.index(normalized)
        except ValueError:
            return -1

    @classmethod
    def id_to_label(cls, class_id: float | int | None) -> str:
        try:
            idx = int(class_id)
        except Exception:
            return "unknown"
        if idx < 0 or idx >= len(cls.LABELS):
            return "unknown"
        return cls.LABELS[idx]


def expression_risk_from_label(label: str) -> float:
    risk_map = {
        "neutral": 0.30,
        "happiness": 0.12,
        "surprise": 0.45,
        "sadness": 0.75,
        "anger": 0.88,
        "disgust": 0.82,
        "fear": 0.92,
        "contempt": 0.70,
    }
    # Unknown label should be treated as unavailable expression data.
    return float(risk_map.get(str(label).lower(), 0.0))
