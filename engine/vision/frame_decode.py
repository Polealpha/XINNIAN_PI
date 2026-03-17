from __future__ import annotations

from typing import Optional

from ..core.types import VideoFrame

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    cv2 = None
    np = None


def decode_gray(frame: VideoFrame) -> Optional["np.ndarray"]:
    if cv2 is None or np is None:
        return None
    try:
        if frame.format == "jpeg":
            buffer = np.frombuffer(frame.data, dtype=np.uint8)
            return cv2.imdecode(buffer, cv2.IMREAD_GRAYSCALE)
        if frame.format == "bgr":
            buffer = np.frombuffer(frame.data, dtype=np.uint8)
            img = buffer.reshape((frame.height, frame.width, 3))
            return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if frame.format == "rgba":
            buffer = np.frombuffer(frame.data, dtype=np.uint8)
            img = buffer.reshape((frame.height, frame.width, 4))
            return cv2.cvtColor(img, cv2.COLOR_RGBA2GRAY)
    except Exception:
        return None
    return None


def decode_rgb(frame: VideoFrame) -> Optional["np.ndarray"]:
    if cv2 is None or np is None:
        return None
    try:
        if frame.format == "jpeg":
            buffer = np.frombuffer(frame.data, dtype=np.uint8)
            bgr = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
            if bgr is None:
                return None
            return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        if frame.format == "bgr":
            buffer = np.frombuffer(frame.data, dtype=np.uint8)
            img = buffer.reshape((frame.height, frame.width, 3))
            return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        if frame.format == "rgba":
            buffer = np.frombuffer(frame.data, dtype=np.uint8)
            img = buffer.reshape((frame.height, frame.width, 4))
            return cv2.cvtColor(img, cv2.COLOR_RGBA2RGB)
    except Exception:
        return None
    return None


def opencv_available() -> bool:
    return cv2 is not None and np is not None
