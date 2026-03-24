from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from ..core.types import VideoFrame
from .frame_decode import decode_gray, decode_rgb, opencv_available
from .vision_types import FaceDet

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


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class FaceDetector:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.min_face_area_ratio = float(cfg.get("min_face_area_ratio", 0.02))
        self.max_face_area_ratio = float(cfg.get("max_face_area_ratio", 0.60))
        self.multi_face_policy = str(cfg.get("multi_face_policy", "largest")).lower()
        self.detector_name = str(cfg.get("detector", "mediapipe")).lower()
        self._mp_detector = None
        self._haar = None

        if self.detector_name == "mediapipe" and mp is not None:
            try:
                self._mp_detector = mp.solutions.face_detection.FaceDetection(
                    model_selection=0,
                    min_detection_confidence=float(cfg.get("min_detection_confidence", 0.5)),
                )
            except Exception:
                self._mp_detector = None

        # Fallback for environments where mediapipe is unavailable.
        if self._mp_detector is None and opencv_available() and cv2 is not None:
            try:
                self._haar = cv2.CascadeClassifier(
                    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
                )
            except Exception:
                self._haar = None

    @property
    def ready(self) -> bool:
        return self._mp_detector is not None or self._haar is not None

    def detect(self, frame: VideoFrame) -> FaceDet:
        if frame.width <= 0 or frame.height <= 0:
            return FaceDet(found=False)

        if self._mp_detector is not None:
            det = self._detect_mediapipe(frame)
            if det.found:
                return det

        if self._haar is not None:
            return self._detect_haar(frame)

        return FaceDet(found=False)

    def _detect_mediapipe(self, frame: VideoFrame) -> FaceDet:
        rgb = decode_rgb(frame)
        if rgb is None:
            return FaceDet(found=False)

        try:
            results = self._mp_detector.process(rgb)
        except Exception:
            return FaceDet(found=False)

        detections = getattr(results, "detections", None) or []
        if not detections:
            return FaceDet(found=False)

        best = self._pick_best_mp_detection(detections, frame.width, frame.height)
        if best is None:
            return FaceDet(found=False)

        x, y, w, h, score = best
        area_ratio = (w * h) / float(max(1, frame.width * frame.height))
        if area_ratio < self.min_face_area_ratio or area_ratio > self.max_face_area_ratio:
            return FaceDet(found=False)

        cx = x + w * 0.5
        cy = y + h * 0.5
        return FaceDet(
            found=True,
            bbox=(x, y, w, h),
            score=score,
            cx=float(cx),
            cy=float(cy),
            area_ratio=float(area_ratio),
        )

    def _pick_best_mp_detection(
        self, detections, width: int, height: int
    ) -> Optional[Tuple[int, int, int, int, float]]:
        best = None
        best_metric = -1.0

        for det in detections:
            rel = det.location_data.relative_bounding_box
            score = float(det.score[0]) if getattr(det, "score", None) else 0.0

            x = int(_clamp(rel.xmin, 0.0, 1.0) * width)
            y = int(_clamp(rel.ymin, 0.0, 1.0) * height)
            w = int(_clamp(rel.width, 0.0, 1.0) * width)
            h = int(_clamp(rel.height, 0.0, 1.0) * height)
            if w <= 0 or h <= 0:
                continue

            if x + w > width:
                w = max(1, width - x)
            if y + h > height:
                h = max(1, height - y)

            metric = float(w * h)
            if self.multi_face_policy == "highest_score":
                metric = score

            if metric > best_metric:
                best_metric = metric
                best = (x, y, w, h, score)

        return best

    def _detect_haar(self, frame: VideoFrame) -> FaceDet:
        gray = decode_gray(frame)
        if gray is None:
            return FaceDet(found=False)

        try:
            faces = self._haar.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(40, 40),
            )
        except Exception:
            return FaceDet(found=False)

        if faces is None or len(faces) == 0:
            return FaceDet(found=False)

        best = max(faces, key=lambda b: int(b[2]) * int(b[3]))
        x, y, w, h = [int(v) for v in best]
        area_ratio = (w * h) / float(max(1, frame.width * frame.height))
        if area_ratio < self.min_face_area_ratio or area_ratio > self.max_face_area_ratio:
            return FaceDet(found=False)

        cx = x + w * 0.5
        cy = y + h * 0.5
        return FaceDet(
            found=True,
            bbox=(x, y, w, h),
            score=1.0,
            cx=float(cx),
            cy=float(cy),
            area_ratio=float(area_ratio),
        )
