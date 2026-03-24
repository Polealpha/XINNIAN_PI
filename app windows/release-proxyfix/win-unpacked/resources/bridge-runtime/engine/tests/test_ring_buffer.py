import unittest

from engine.audio.ring_buffer import AudioRingBuffer
from engine.core.types import AudioFrame


class TestAudioRingBuffer(unittest.TestCase):
    def test_eviction_and_fetch(self):
        buf = AudioRingBuffer(0.001)  # ~60ms
        pcm = b"\x00\x00" * 320

        buf.add_frame(AudioFrame(pcm, 16000, 1, 1000, 1, "dev"))
        buf.add_frame(AudioFrame(pcm, 16000, 1, 1020, 2, "dev"))
        buf.add_frame(AudioFrame(pcm, 16000, 1, 1040, 3, "dev"))
        self.assertEqual(buf.total_frames(), 3)

        buf.add_frame(AudioFrame(pcm, 16000, 1, 2000, 4, "dev"))
        self.assertEqual(buf.total_frames(), 1)

        pcm_out, start_ts, end_ts = buf.get_last_ms(40)
        self.assertTrue(pcm_out)
        self.assertEqual(end_ts, 2000)


if __name__ == "__main__":
    unittest.main()
