from __future__ import annotations

from typing import Dict

from ..core.types import VideoFrame
from .frame_decode import decode_gray, opencv_available

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None


class FaceROI:
    def __init__(self) -> None:
        self._detector = None
        if opencv_available() and cv2 is not None:
            try:
                self._detector = cv2.CascadeClassifier(
                    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
                )
            except Exception:
                self._detector = None

    def process(self, frame: VideoFrame) -> Dict[str, bool]:
        if not self._detector:
            # Placeholder: assumes a face is present if a frame arrives.
            return {"face_present": True}
        gray = decode_gray(frame)
        if gray is None:
            return {"face_present": False}
        faces = self._detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
        return {"face_present": len(faces) > 0}
