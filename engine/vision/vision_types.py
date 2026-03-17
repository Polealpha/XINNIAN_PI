from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class FaceDet:
    found: bool
    bbox: Optional[Tuple[int, int, int, int]] = None
    score: float = 0.0
    cx: float = 0.0
    cy: float = 0.0
    area_ratio: float = 0.0


@dataclass
class TrackState:
    ex_smooth: float = 0.0
    lost_count: int = 0
    last_send_ms: int = 0
    target_bbox: Optional[Tuple[int, int, int, int]] = None
    last_turn_sent: float = 0.0
