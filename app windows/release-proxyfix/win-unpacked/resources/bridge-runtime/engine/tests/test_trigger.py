import unittest

from engine.core.config import TriggerConfig, VideoConfig
from engine.trigger.trigger_manager import TriggerManager


class TestTriggerManager(unittest.TestCase):
    def test_visual_sustain_trigger(self):
        config = TriggerConfig()
        video_config = VideoConfig()
        trigger = TriggerManager(config, video_config)

        ts = 0
        fired = False
        for _ in range(config.V_sustain_sec + 1):
            decision = trigger.update(
                timestamp_ms=ts,
                v_raw=0.8,
                a_raw=0.0,
                vad_active=False,
                face_present=True,
            )
            if decision.should_trigger:
                fired = True
                break
            ts += 1000

        self.assertTrue(fired)


if __name__ == "__main__":
    unittest.main()
