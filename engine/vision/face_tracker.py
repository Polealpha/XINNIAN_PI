from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from .vision_types import FaceDet, TrackState


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class FaceTracker:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.state = TrackState()
        self.dead_zone = float(cfg.get("dead_zone", 0.08))
        self.ema_alpha = float(cfg.get("ema_alpha", 0.30))
        self.kp = float(cfg.get("kp", 0.60))
        self.turn_max = float(cfg.get("turn_max", 0.60))
        self.send_hz = float(cfg.get("send_hz", 4.0))
        self.lost_frames_stop = int(cfg.get("lost_frames_stop", 5))

        self._min_interval_ms = int(1000.0 / max(1e-6, self.send_hz))

    def reset(self) -> None:
        self.state = TrackState()

    def update(self, det: FaceDet, frame_w: int, now_ms: int) -> Tuple[Optional[float], Dict[str, Any]]:
        dbg = {
            "found": bool(det.found),
            "ex": 0.0,
            "ex_smooth": float(self.state.ex_smooth),
            "dead_zone": float(self.dead_zone),
            "turn": None,
            "lost": int(self.state.lost_count),
            "bbox": det.bbox,
        }

        if frame_w <= 0:
            return None, dbg

        if not det.found:
            self.state.lost_count += 1
            dbg["lost"] = int(self.state.lost_count)
            if self.state.lost_count >= self.lost_frames_stop:
                return self._send_if_due(0.0, now_ms, dbg)
            return None, dbg

        self.state.lost_count = 0
        ex = (float(det.cx) - (frame_w * 0.5)) / max(1e-6, frame_w * 0.5)
        ex = clamp(ex, -1.0, 1.0)
        self.state.ex_smooth = (1.0 - self.ema_alpha) * self.state.ex_smooth + self.ema_alpha * ex

        dbg["ex"] = float(ex)
        dbg["ex_smooth"] = float(self.state.ex_smooth)
        dbg["lost"] = 0

        if abs(self.state.ex_smooth) < self.dead_zone:
            return self._send_if_due(0.0, now_ms, dbg)

        turn = self.kp * self.state.ex_smooth
        turn = clamp(turn, -self.turn_max, self.turn_max)
        return self._send_if_due(turn, now_ms, dbg)

    def _send_if_due(self, turn: float, now_ms: int, dbg: Dict[str, Any]) -> Tuple[Optional[float], Dict[str, Any]]:
        due = (now_ms - self.state.last_send_ms) >= self._min_interval_ms
        if not due:
            dbg["turn"] = None
            return None, dbg

        # Avoid repeatedly sending stop if we are already stopped.
        if abs(turn) < 1e-6 and abs(self.state.last_turn_sent) < 1e-3:
            dbg["turn"] = None
            return None, dbg

        self.state.last_send_ms = now_ms
        self.state.last_turn_sent = float(turn)
        dbg["turn"] = float(turn)
        return float(turn), dbg
