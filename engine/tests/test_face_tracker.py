import unittest

from engine.vision.face_tracker import FaceTracker
from engine.vision.vision_types import FaceDet


class TestFaceTracker(unittest.TestCase):
    def _tracker(self) -> FaceTracker:
        return FaceTracker(
            {
                "dead_zone": 0.08,
                "ema_alpha": 0.30,
                "kp": 0.60,
                "turn_max": 0.60,
                "send_hz": 4,
                "lost_frames_stop": 5,
            }
        )

    def test_dead_zone_no_turn(self):
        tracker = self._tracker()
        det = FaceDet(found=True, cx=162.0)  # near center for W=320
        turn, _dbg = tracker.update(det, frame_w=320, now_ms=1000)
        self.assertIsNone(turn)

    def test_left_turn_negative(self):
        tracker = self._tracker()
        det = FaceDet(found=True, cx=80.0)
        turn, _dbg = tracker.update(det, frame_w=320, now_ms=1000)
        self.assertIsNotNone(turn)
        assert turn is not None
        self.assertLess(turn, 0.0)

    def test_right_turn_positive(self):
        tracker = self._tracker()
        det = FaceDet(found=True, cx=240.0)
        turn, _dbg = tracker.update(det, frame_w=320, now_ms=1000)
        self.assertIsNotNone(turn)
        assert turn is not None
        self.assertGreater(turn, 0.0)

    def test_turn_clamped(self):
        tracker = self._tracker()
        # Extreme error right side.
        det = FaceDet(found=True, cx=320.0)
        turn, _dbg = tracker.update(det, frame_w=320, now_ms=1000)
        self.assertIsNotNone(turn)
        assert turn is not None
        self.assertLessEqual(abs(turn), 0.60 + 1e-6)

    def test_lost_face_stop_after_n(self):
        tracker = self._tracker()
        # First create a moving state.
        moving, _ = tracker.update(FaceDet(found=True, cx=240.0), frame_w=320, now_ms=1000)
        self.assertIsNotNone(moving)

        turn = None
        now = 1300
        for _ in range(4):
            turn, _dbg = tracker.update(FaceDet(found=False), frame_w=320, now_ms=now)
            now += 300
        self.assertIsNone(turn)

        # 5th lost frame should stop.
        turn, _dbg = tracker.update(FaceDet(found=False), frame_w=320, now_ms=now)
        self.assertEqual(turn, 0.0)

    def test_rate_limit(self):
        tracker = self._tracker()
        det = FaceDet(found=True, cx=240.0)
        first, _ = tracker.update(det, frame_w=320, now_ms=1000)
        second, _ = tracker.update(det, frame_w=320, now_ms=1100)
        self.assertIsNotNone(first)
        self.assertIsNone(second)


if __name__ == "__main__":
    unittest.main()
