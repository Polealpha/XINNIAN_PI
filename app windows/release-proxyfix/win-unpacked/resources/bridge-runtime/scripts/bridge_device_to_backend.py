from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path
import sys
from typing import Any, Dict, Optional

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.core.config import load_engine_config
from engine.core.types import VideoFrame
from engine.vision.face_detector import FaceDetector
from engine.vision.face_tracker import FaceTracker
from engine.vision.vision_types import FaceDet

logger = logging.getLogger(__name__)


def post_event(backend_url: str, event_payload: Dict[str, object], timeout_sec: float = 5.0) -> Dict[str, object]:
    base = str(backend_url or "").rstrip("/")
    if not base:
        return {"ok": False, "detail": "backend_url_missing"}
    with httpx.Client(timeout=max(1.0, float(timeout_sec)), trust_env=False) as client:
        response = client.post(f"{base}/api/engine/event", json=event_payload)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {"ok": True}


class FaceTrackController:
    def __init__(
        self,
        device_ip: str,
        tracking_cfg: Dict[str, Any],
        scene: str,
        backend_url: str,
        event_timeout_sec: float = 5.0,
    ) -> None:
        self.device_ip = str(device_ip or "").strip()
        self.tracking_cfg = dict(tracking_cfg or {})
        self.scene = str(scene or "desk").strip() or "desk"
        self.backend_url = str(backend_url or "").strip()
        self.event_timeout_sec = float(event_timeout_sec)
        self.detector = FaceDetector(self.tracking_cfg)
        self.tracker = FaceTracker(self.tracking_cfg)
        self._last_emit_ms = 0
        self._ui_emit_interval_ms = int(1000.0 / max(1e-6, float(self.tracking_cfg.get("ui_emit_hz", 4.0) or 4.0)))

    def process(self, frame: VideoFrame, mode: str = "normal") -> Dict[str, object]:
        det = self.detector.detect(frame) if self.detector.ready else FaceDet(found=False)
        track_det = det if det and det.found else FaceDet(found=False)
        pan_turn, tilt_turn, dbg = self.tracker.update(track_det, frame.width, frame.height, frame.timestamp_ms)
        payload = self._build_payload(frame, det, dbg, pan_turn, tilt_turn, mode)
        self._emit_debug(frame.timestamp_ms, payload)
        return payload

    def _build_payload(
        self,
        frame: VideoFrame,
        det: FaceDet,
        dbg: Dict[str, Any],
        pan_turn: Optional[float],
        tilt_turn: Optional[float],
        mode: str,
    ) -> Dict[str, object]:
        payload = dict(dbg or {})
        bbox = payload.get("bbox", det.bbox)
        if isinstance(bbox, tuple):
            payload["bbox"] = [int(v) for v in bbox]
        elif bbox is None:
            payload["bbox"] = []
        payload.update(
            {
                "found": bool(det.found),
                "frame_w": int(frame.width),
                "frame_h": int(frame.height),
                "turn": None if pan_turn is None else float(pan_turn),
                "tilt": None if tilt_turn is None else float(tilt_turn),
                "sent": bool(pan_turn is not None or tilt_turn is not None),
                "mode": str(mode or "normal"),
                "scene": self.scene,
                "ts_ms": int(frame.timestamp_ms),
                "device_id": str(frame.device_id or ""),
                "device_ip": self.device_ip,
            }
        )
        return payload

    def _emit_debug(self, timestamp_ms: int, payload: Dict[str, object]) -> bool:
        if int(timestamp_ms) - self._last_emit_ms < self._ui_emit_interval_ms:
            return False
        self._last_emit_ms = int(timestamp_ms)
        event_payload = {
            "type": "FaceTrackUpdate",
            "timestamp_ms": int(timestamp_ms),
            "payload": dict(payload or {}),
        }
        try:
            post_event(self.backend_url, event_payload, timeout_sec=self.event_timeout_sec)
            return True
        except Exception as exc:
            logger.debug("face track debug emit failed: %s", exc)
            return False

    def close(self) -> None:
        return


class DevicePreviewBridge:
    def __init__(
        self,
        device_ip: str,
        backend_url: str,
        engine_config_path: str,
        poll_interval_sec: float = 0.35,
    ) -> None:
        self.device_ip = str(device_ip or "").strip()
        self.backend_url = str(backend_url or "").rstrip("/")
        self.poll_interval_sec = max(0.1, float(poll_interval_sec))
        self.device_endpoint = self._normalize_device_endpoint(self.device_ip)
        config = load_engine_config(engine_config_path)
        self._controller = FaceTrackController(
            device_ip=self.device_ip,
            tracking_cfg=dict(config.face_tracking.__dict__),
            scene=str(config.policy.scene or "desk"),
            backend_url=self.backend_url,
        )
        self._seq = 0

    @staticmethod
    def _normalize_device_endpoint(value: str) -> str:
        raw = str(value or "").strip()
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw.rstrip("/")
        if ":" in raw:
            return f"http://{raw}"
        return f"http://{raw}:8090"

    def step(self) -> bool:
        status = self._fetch_json("/status")
        device_id = str(status.get("device_id") or "robot-bridge").strip() or "robot-bridge"
        ui_state = status.get("ui_state") if isinstance(status.get("ui_state"), dict) else {}
        mode = str(status.get("mode") or ui_state.get("mode") or "normal").strip() or "normal"
        frame = self._fetch_preview_frame(device_id)
        if frame is None:
            return False
        self._controller.process(frame, mode=mode)
        return True

    def run_forever(self) -> None:
        while True:
            try:
                self.step()
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                logger.debug("bridge step failed: %s", exc)
            time.sleep(self.poll_interval_sec)

    def close(self) -> None:
        self._controller.close()

    def _fetch_json(self, path: str) -> Dict[str, object]:
        with httpx.Client(timeout=5.0, trust_env=False) as client:
            response = client.get(f"{self.device_endpoint}{path}")
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else {}

    def _fetch_preview_frame(self, device_id: str) -> Optional[VideoFrame]:
        with httpx.Client(timeout=5.0, trust_env=False) as client:
            response = client.get(f"{self.device_endpoint}/camera/preview.jpg")
            response.raise_for_status()
            raw = bytes(response.content or b"")
        if not raw:
            return None
        width, height = self._probe_jpeg_size(raw)
        if width <= 0 or height <= 0:
            return None
        frame = VideoFrame(
            format="jpeg",
            data=raw,
            width=width,
            height=height,
            timestamp_ms=int(time.time() * 1000),
            seq=self._seq,
            device_id=str(device_id or "robot-bridge"),
        )
        self._seq += 1
        return frame

    def _probe_jpeg_size(self, raw: bytes) -> tuple[int, int]:
        try:
            import cv2  # type: ignore
            import numpy as np  # type: ignore
        except Exception:
            return 0, 0
        try:
            buffer = np.frombuffer(raw, dtype=np.uint8)
            image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
            if image is None:
                return 0, 0
            height, width = image.shape[:2]
            return int(width), int(height)
        except Exception:
            return 0, 0


def _default_engine_config_path() -> str:
    return str((Path(__file__).resolve().parents[1] / "config" / "engine_config.json").resolve())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bridge device preview face tracking debug events to backend.")
    parser.add_argument("--device-ip", required=True)
    parser.add_argument("--backend-url", required=True)
    parser.add_argument("--engine-config", default=_default_engine_config_path())
    parser.add_argument("--poll-interval-sec", type=float, default=0.35)
    parser.add_argument("--once", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    bridge = DevicePreviewBridge(
        device_ip=args.device_ip,
        backend_url=args.backend_url,
        engine_config_path=args.engine_config,
        poll_interval_sec=float(args.poll_interval_sec),
    )
    try:
        if args.once:
            ok = bridge.step()
            return 0 if ok else 2
        bridge.run_forever()
        return 0
    finally:
        bridge.close()


if __name__ == "__main__":
    raise SystemExit(main())
