from __future__ import annotations

from typing import Dict

import requests


class EspCommandSender:
    def __init__(self, device_ip: str, timeout_s: float = 0.8) -> None:
        self.device_ip = device_ip
        self.timeout_s = timeout_s
        self.url = f"http://{device_ip}/command"
        self._session = requests.Session()

    def send(self, payload: Dict[str, object]) -> bool:
        try:
            response = self._session.post(self.url, json=payload, timeout=self.timeout_s)
            return response.ok
        except Exception:
            return False

    def send_move_track_turn(self, turn: float, base: float = 0.0, duration_ms: int = 250) -> bool:
        payload: Dict[str, object] = {
            "cmd": "MOVE",
            "name": "track_turn",
            "turn": float(turn),
            "base": float(base),
            "duration_ms": int(duration_ms),
        }
        return self.send(payload)

    def send_move_stop(self) -> bool:
        payload: Dict[str, object] = {
            "cmd": "MOVE",
            "name": "stop",
            "duration_ms": 0,
        }
        return self.send(payload)

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass
