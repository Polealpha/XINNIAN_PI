from engine.core.types import AudioFrame
from pi_runtime.runtime import PiEmotionRuntime


def test_voice_session_state_and_warmup_endpoint():
    runtime = PiEmotionRuntime("config/pi_zero2w.headless.json", "config/engine_config.json")

    started = runtime.start_voice_session("assessment")
    assert started["session_active"] is True
    assert started["mode"] == "assessment"

    warmed = runtime.warmup_tts("你好")
    assert warmed["device_id"] == "polealpha-zero2w"
    assert "tts_ready" in warmed

    stopped = runtime.stop_voice_session("assessment")
    assert stopped["session_active"] is False
    assert stopped["mode"] == "idle"


def test_wake_detector_arms_voice_session(monkeypatch):
    class FakeWakeDetector:
        ready = True
        error = ""
        unhealthy = False
        last_text = "小念"

        def __init__(self) -> None:
            self._triggered = False

        def update(self, _pcm: bytes) -> bool:
            if self._triggered:
                return False
            self._triggered = True
            return True

    monkeypatch.setattr(PiEmotionRuntime, "_build_wake_detector", lambda self: FakeWakeDetector())
    runtime = PiEmotionRuntime("config/pi_zero2w.json", "config/engine_config.json")
    monkeypatch.setattr(runtime._hardware, "speak", lambda _tts, _text: True)

    frame = AudioFrame(
        pcm_s16le=b"\x00\x00" * 320,
        sample_rate=16000,
        channels=1,
        timestamp_ms=runtime._now_ms(),
        seq=1,
        device_id="polealpha-zero2w",
    )
    runtime._push_audio(frame)

    voice_status = runtime.get_voice_status()
    wake_status = runtime.get_wake_status()
    assert voice_status["session_active"] is True
    assert voice_status["mode"] == "wake_listen"
    assert voice_status["last_prompt"] == runtime.engine_config.wake.ack_text
    assert wake_status["ready"] is True
    assert wake_status["provider"] == "sherpa"
    assert wake_status["last_text"] == "小念"
