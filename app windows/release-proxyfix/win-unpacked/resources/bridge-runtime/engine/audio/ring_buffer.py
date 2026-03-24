from __future__ import annotations

from collections import deque
from typing import Deque, Tuple

from ..core.types import AudioFrame


class AudioRingBuffer:
    def __init__(self, max_minutes: int) -> None:
        self._max_ms = int(max_minutes * 60 * 1000)
        self._frames: Deque[Tuple[int, bytes]] = deque()

    def clear(self) -> None:
        self._frames.clear()

    def add_frame(self, frame: AudioFrame) -> None:
        self._frames.append((frame.timestamp_ms, bytes(frame.pcm_s16le)))
        self._evict_old(frame.timestamp_ms)

    def _evict_old(self, now_ms: int) -> None:
        cutoff = now_ms - self._max_ms
        while self._frames and self._frames[0][0] < cutoff:
            self._frames.popleft()

    def get_last_ms(self, window_ms: int) -> Tuple[bytes, int, int]:
        if not self._frames:
            return b"", 0, 0
        end_ts = self._frames[-1][0]
        start_ts = end_ts - window_ms
        chunks = []
        for ts, pcm in reversed(self._frames):
            if ts < start_ts:
                break
            chunks.append(pcm)
        chunks.reverse()
        return b"".join(chunks), max(start_ts, self._frames[0][0]), end_ts

    def total_frames(self) -> int:
        return len(self._frames)
