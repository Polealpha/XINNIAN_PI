from __future__ import annotations

from typing import Optional

from ..core.config import FusionConfig


class FusionScorer:
    def __init__(self, config: FusionConfig) -> None:
        self.config = config

    def score(self, v: float, a: float, t: Optional[float]) -> float:
        if t is None:
            denom = self.config.wV + self.config.wA
            if denom <= 0:
                return 0.0
            return (self.config.wV * v + self.config.wA * a) / denom
        return (
            self.config.wV * v
            + self.config.wA * a
            + self.config.wT * t
        )
