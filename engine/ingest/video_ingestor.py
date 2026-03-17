from __future__ import annotations

from ..core.types import VideoFrame


class VideoIngestor:
    def __init__(self) -> None:
        pass

    def validate(self, frame: VideoFrame) -> None:
        if frame.width <= 0 or frame.height <= 0:
            raise ValueError("VideoFrame width/height must be positive")
        if frame.format not in ("jpeg", "bgr", "rgba"):
            raise ValueError(f"Unsupported video format {frame.format}")
        if not isinstance(frame.data, (bytes, bytearray)):
            raise ValueError("VideoFrame data must be bytes")
