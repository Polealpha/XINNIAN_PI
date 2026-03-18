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
