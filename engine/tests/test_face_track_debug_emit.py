import unittest
from unittest.mock import patch

from engine.core.types import VideoFrame
from engine.vision.vision_types import FaceDet
from scripts.bridge_device_to_backend import FaceTrackController


class TestFaceTrackDebugEmit(unittest.TestCase):
    def _controller(self, ui_emit_hz: float = 4.0) -> FaceTrackController:
        return FaceTrackController(
            device_ip="127.0.0.1",
            tracking_cfg={
                "enabled": True,
                "ui_emit_hz": ui_emit_hz,
                "scene_behavior": {"desk": {"base": 0.0}},
            },
            scene="desk",
            backend_url="http://127.0.0.1:8000",
        )

    def test_emit_rate_limited_by_ui_emit_hz(self):
        controller = self._controller(ui_emit_hz=4.0)
        try:
            with patch("scripts.bridge_device_to_backend.post_event") as mock_post:
                controller._emit_debug(1000, {"k": 1})
                controller._emit_debug(1200, {"k": 2})  # < 250ms, should be dropped
                controller._emit_debug(1251, {"k": 3})  # >= 250ms, should pass
                self.assertEqual(mock_post.call_count, 2)
        finally:
            controller.close()

    def test_process_payload_contains_frame_dimensions_and_timestamp(self):
        controller = self._controller(ui_emit_hz=4.0)
        try:
            controller.detector.detect = lambda _frame: FaceDet(
                found=True,
                bbox=(10, 20, 30, 40),
                cx=25.0,
                cy=40.0,
                area_ratio=0.05,
            )
            controller.tracker.update = lambda det, frame_w, now_ms: (
                None,
                {
                    "found": det.found,
                    "bbox": list(det.bbox or []),
                    "ex": 0.1,
                    "ex_smooth": 0.08,
                    "turn": None,
                    "lost": 0,
                },
            )

            frame = VideoFrame(
                format="jpeg",
                data=b"",
                width=320,
                height=240,
                timestamp_ms=2000,
                seq=1,
                device_id="dev",
            )

            with patch("scripts.bridge_device_to_backend.post_event") as mock_post:
                controller.process(frame, mode="normal")
                self.assertEqual(mock_post.call_count, 1)
                event_payload = mock_post.call_args.args[1]
                payload = event_payload["payload"]
                self.assertEqual(payload["frame_w"], 320)
                self.assertEqual(payload["frame_h"], 240)
                self.assertEqual(payload["ts_ms"], 2000)
        finally:
            controller.close()


if __name__ == "__main__":
    unittest.main()
