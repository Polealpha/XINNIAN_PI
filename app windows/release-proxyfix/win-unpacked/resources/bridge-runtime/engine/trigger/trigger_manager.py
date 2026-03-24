from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
from typing import Deque, Optional

from ..core.config import TriggerConfig, VideoConfig


@dataclass
class TriggerDecision:
    should_trigger: bool
    reason: str
    v: float
    a: float
    v_raw: float
    a_raw: float
    peak_v_count: int
    peak_a_count: int


class TriggerManager:
    def __init__(self, config: TriggerConfig, video_config: VideoConfig) -> None:
        self.config = config
        self.video_config = video_config
        self._v_ema: Optional[float] = None
        self._a_ema: Optional[float] = None
        self._last_ts_ms: Optional[int] = None
        self._v_above_ms = 0
        self._a_above_ms = 0
        self._conj_above_ms = 0
        self._face_missing_ms = 0
        self._v_peaks: Deque[int] = deque()
        self._a_peaks: Deque[int] = deque()
        self._last_v_peak_ts: Optional[int] = None
        self._last_a_peak_ts: Optional[int] = None

    def reset(self) -> None:
        self._v_ema = None
        self._a_ema = None
        self._last_ts_ms = None
        self._v_above_ms = 0
        self._a_above_ms = 0
        self._conj_above_ms = 0
        self._face_missing_ms = 0
        self._v_peaks.clear()
        self._a_peaks.clear()
        self._last_v_peak_ts = None
        self._last_a_peak_ts = None

    def update(
        self,
        timestamp_ms: int,
        v_raw: float,
        a_raw: float,
        vad_active: bool,
        face_present: bool,
    ) -> TriggerDecision:
        dt_ms = 0
        if self._last_ts_ms is not None:
            dt_ms = max(0, timestamp_ms - self._last_ts_ms)
        self._last_ts_ms = timestamp_ms

        if self._v_ema is None:
            self._v_ema = v_raw
        else:
            self._v_ema = (1.0 - self.config.alpha_v) * self._v_ema + self.config.alpha_v * v_raw

        if self._a_ema is None:
            self._a_ema = a_raw
        if vad_active:
            self._a_ema = (1.0 - self.config.alpha_a) * self._a_ema + self.config.alpha_a * a_raw
        else:
            decay = math.exp(-dt_ms / max(1, self.config.a_decay_sec * 1000))
            self._a_ema *= decay

        if face_present:
            self._face_missing_ms = 0
        else:
            self._face_missing_ms += dt_ms
            if self._face_missing_ms >= self.video_config.face_missing_grace_sec * 1000:
                decay = math.exp(-dt_ms / max(1, self.video_config.face_missing_decay_sec * 1000))
                self._v_ema *= decay

        if self._v_ema > self.config.V_threshold:
            self._v_above_ms += dt_ms
        else:
            self._v_above_ms = 0

        if vad_active and self._a_ema > self.config.A_threshold:
            self._a_above_ms += dt_ms
        else:
            self._a_above_ms = 0

        if self._v_ema > self.config.conj_threshold and self._a_ema > self.config.conj_threshold:
            self._conj_above_ms += dt_ms
        else:
            self._conj_above_ms = 0

        self._update_peaks(timestamp_ms, v_raw, a_raw, vad_active)

        reason = ""
        should_trigger = False
        if self._v_above_ms >= self.config.V_sustain_sec * 1000:
            should_trigger = True
            reason = "V_sustain"
        elif self._a_above_ms >= self.config.A_sustain_sec * 1000:
            should_trigger = True
            reason = "A_sustain"
        elif self._conj_above_ms >= self.config.conj_sustain_sec * 1000:
            should_trigger = True
            reason = "VA_conj"
        elif len(self._v_peaks) >= self.config.peak_count:
            should_trigger = True
            reason = "V_peak"
        elif len(self._a_peaks) >= self.config.peak_count:
            should_trigger = True
            reason = "A_peak"

        return TriggerDecision(
            should_trigger=should_trigger,
            reason=reason,
            v=self._v_ema,
            a=self._a_ema,
            v_raw=v_raw,
            a_raw=a_raw,
            peak_v_count=len(self._v_peaks),
            peak_a_count=len(self._a_peaks),
        )

    def _update_peaks(self, timestamp_ms: int, v_raw: float, a_raw: float, vad_active: bool) -> None:
        if v_raw > self.config.peak_threshold:
            if self._last_v_peak_ts is None or (
                timestamp_ms - self._last_v_peak_ts >= self.config.peak_min_gap_sec * 1000
            ):
                self._v_peaks.append(timestamp_ms)
                self._last_v_peak_ts = timestamp_ms
        if vad_active and a_raw > self.config.peak_threshold:
            if self._last_a_peak_ts is None or (
                timestamp_ms - self._last_a_peak_ts >= self.config.peak_min_gap_sec * 1000
            ):
                self._a_peaks.append(timestamp_ms)
                self._last_a_peak_ts = timestamp_ms

        window_ms = self.config.peak_window_sec * 1000
        while self._v_peaks and timestamp_ms - self._v_peaks[0] > window_ms:
            self._v_peaks.popleft()
        while self._a_peaks and timestamp_ms - self._a_peaks[0] > window_ms:
            self._a_peaks.popleft()
