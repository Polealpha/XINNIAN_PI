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
        self.dead_zone_y = float(cfg.get("dead_zone_y", cfg.get("dead_zone", 0.08)))
        self.ema_alpha = float(cfg.get("ema_alpha", 0.30))
        self.ema_alpha_y = float(cfg.get("ema_alpha_y", cfg.get("ema_alpha", 0.30)))
        self.kp = float(cfg.get("kp", 0.60))
        self.kp_y = float(cfg.get("kp_y", cfg.get("kp", 0.60)))
        self.turn_max = float(cfg.get("turn_max", 0.60))
        self.tilt_max = float(cfg.get("tilt_max", cfg.get("turn_max", 0.45)))
        self.send_hz = float(cfg.get("send_hz", 4.0))
        self.lost_frames_stop = int(cfg.get("lost_frames_stop", 5))
        self.return_start_frames = int(cfg.get("return_start_frames", max(1, self.lost_frames_stop // 2)))
        self.return_alpha = float(cfg.get("return_alpha", 0.35))
        self.return_deadband = float(cfg.get("return_deadband", 0.015))
        self.preferred_face_area_ratio = float(cfg.get("preferred_face_area_ratio", 0.12))
        self.area_gain_floor = float(cfg.get("area_gain_floor", 0.35))
        self.min_turn_delta = float(cfg.get("min_turn_delta", 0.02))

        self._min_interval_ms = int(1000.0 / max(1e-6, self.send_hz))

    def reset(self) -> None:
        self.state = TrackState()

    def update(
        self,
        det: FaceDet,
        frame_w: int,
        frame_h: int,
        now_ms: int,
    ) -> Tuple[Optional[float], Optional[float], Dict[str, Any]]:
        dbg = {
            "found": bool(det.found),
            "ex": 0.0,
            "ey": 0.0,
            "ex_smooth": float(self.state.ex_smooth),
            "ey_smooth": float(self.state.ey_smooth),
            "dead_zone": float(self.dead_zone),
            "dead_zone_y": float(self.dead_zone_y),
            "turn": None,
            "tilt": None,
            "lost": int(self.state.lost_count),
            "bbox": det.bbox,
            "returning": bool(self.state.returning),
            "area_ratio": float(det.area_ratio or self.state.last_area_ratio),
        }

        if frame_w <= 0 or frame_h <= 0:
            return None, None, dbg

        if not det.found:
            self.state.lost_count += 1
            self.state.returning = self.state.lost_count >= self.return_start_frames
            dbg["lost"] = int(self.state.lost_count)
            dbg["returning"] = bool(self.state.returning)
            if self.state.lost_count >= self.return_start_frames:
                return self._return_to_center(now_ms, dbg)
            return None, None, dbg

        self.state.lost_count = 0
        self.state.returning = False
        ex = (float(det.cx) - (frame_w * 0.5)) / max(1e-6, frame_w * 0.5)
        ey = ((frame_h * 0.5) - float(det.cy)) / max(1e-6, frame_h * 0.5)
        ex = clamp(ex, -1.0, 1.0)
        ey = clamp(ey, -1.0, 1.0)
        self.state.ex_smooth = (1.0 - self.ema_alpha) * self.state.ex_smooth + self.ema_alpha * ex
        self.state.ey_smooth = (1.0 - self.ema_alpha_y) * self.state.ey_smooth + self.ema_alpha_y * ey
        self.state.target_bbox = det.bbox
        self.state.last_area_ratio = float(det.area_ratio or 0.0)
        self.state.last_seen_ms = int(now_ms)

        dbg["ex"] = float(ex)
        dbg["ey"] = float(ey)
        dbg["ex_smooth"] = float(self.state.ex_smooth)
        dbg["ey_smooth"] = float(self.state.ey_smooth)
        dbg["lost"] = 0
        dbg["area_ratio"] = float(self.state.last_area_ratio)

        pan_turn = 0.0
        tilt_turn = 0.0
        gain = self._area_gain(float(det.area_ratio or 0.0))
        if abs(self.state.ex_smooth) >= self.dead_zone:
            pan_turn = clamp(self.kp * self.state.ex_smooth * gain, -self.turn_max, self.turn_max)
        if abs(self.state.ey_smooth) >= self.dead_zone_y:
            tilt_turn = clamp(self.kp_y * self.state.ey_smooth * gain, -self.tilt_max, self.tilt_max)

        return self._send_if_due(pan_turn, tilt_turn, now_ms, dbg)

    def _area_gain(self, area_ratio: float) -> float:
        preferred = max(0.01, float(self.preferred_face_area_ratio))
        ratio = max(0.0, min(1.0, float(area_ratio) / preferred))
        return clamp(1.0 - (ratio * 0.55), self.area_gain_floor, 1.0)

    def _return_to_center(
        self,
        now_ms: int,
        dbg: Dict[str, Any],
    ) -> Tuple[Optional[float], Optional[float], Dict[str, Any]]:
        self.state.ex_smooth *= max(0.0, 1.0 - self.return_alpha)
        self.state.ey_smooth *= max(0.0, 1.0 - self.return_alpha)
        if abs(self.state.ex_smooth) <= self.return_deadband:
            self.state.ex_smooth = 0.0
        if abs(self.state.ey_smooth) <= self.return_deadband:
            self.state.ey_smooth = 0.0
        pan_turn = clamp(self.kp * self.state.ex_smooth, -self.turn_max, self.turn_max)
        tilt_turn = clamp(self.kp_y * self.state.ey_smooth, -self.tilt_max, self.tilt_max)
        if self.state.lost_count >= self.lost_frames_stop and abs(pan_turn) < self.min_turn_delta:
            pan_turn = 0.0
        if self.state.lost_count >= self.lost_frames_stop and abs(tilt_turn) < self.min_turn_delta:
            tilt_turn = 0.0
        return self._send_if_due(pan_turn, tilt_turn, now_ms, dbg)

    def _send_if_due(
        self,
        turn: float,
        tilt: float,
        now_ms: int,
        dbg: Dict[str, Any],
    ) -> Tuple[Optional[float], Optional[float], Dict[str, Any]]:
        due = (now_ms - self.state.last_send_ms) >= self._min_interval_ms
        if not due:
            dbg["turn"] = None
            dbg["tilt"] = None
            return None, None, dbg

        if (
            abs(turn) < 1e-6
            and abs(tilt) < 1e-6
            and abs(self.state.last_turn_sent) < 1e-3
            and abs(self.state.last_tilt_sent) < 1e-3
        ):
            dbg["turn"] = None
            dbg["tilt"] = None
            return None, None, dbg
        if (
            abs(turn - self.state.last_turn_sent) < self.min_turn_delta
            and abs(tilt - self.state.last_tilt_sent) < self.min_turn_delta
            and (abs(turn) > 1e-6 or abs(tilt) > 1e-6)
        ):
            dbg["turn"] = None
            dbg["tilt"] = None
            return None, None, dbg

        self.state.last_send_ms = now_ms
        self.state.last_turn_sent = float(turn)
        self.state.last_tilt_sent = float(tilt)
        dbg["turn"] = float(turn)
        dbg["tilt"] = float(tilt)
        return float(turn), float(tilt), dbg
