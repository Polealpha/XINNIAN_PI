from __future__ import annotations

from typing import Optional


class AcousticRiskScorer:
    def __init__(self) -> None:
        self._baseline_rms: Optional[float] = None

    def reset(self) -> None:
        self._baseline_rms = None

    def score(self, rms: float, zcr: float, vad_active: bool) -> float:
        if self._baseline_rms is None:
            self._baseline_rms = rms or 1.0
        if vad_active:
            self._baseline_rms = 0.99 * self._baseline_rms + 0.01 * rms
        if not vad_active:
            return 0.0
        ratio = rms / max(self._baseline_rms, 1.0)
        risk = max(0.0, min(1.0, (ratio - 1.0) / 1.0))
        if zcr > 0.15:
            risk = min(1.0, risk + 0.1)
        return risk
