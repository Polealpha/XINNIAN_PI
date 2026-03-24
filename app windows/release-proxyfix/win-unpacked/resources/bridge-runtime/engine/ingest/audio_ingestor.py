from __future__ import annotations

from ..core.types import AudioFrame


class AudioIngestor:
    def __init__(self, sample_rate: int, channels: int) -> None:
        self.sample_rate = sample_rate
        self.channels = channels

    def validate(self, frame: AudioFrame) -> None:
        if frame.sample_rate != self.sample_rate:
            raise ValueError(f"Unexpected sample_rate {frame.sample_rate}")
        if frame.channels != self.channels:
            raise ValueError(f"Unexpected channels {frame.channels}")
        if not isinstance(frame.pcm_s16le, (bytes, bytearray)):
            raise ValueError("pcm_s16le must be bytes")
