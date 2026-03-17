from pi_runtime.runtime import PiEmotionRuntime


def test_manual_pan_tilt_updates_runtime_status():
    runtime = PiEmotionRuntime("config/pi_zero2w.json", "config/engine_config.json")
    result = runtime.set_manual_pan_tilt(0.25, -0.4)
    payload = runtime.get_status_payload()

    assert result["ok"] is True
    assert payload["pan_angle"] != 0.0
    assert payload["tilt_angle"] != 0.0
