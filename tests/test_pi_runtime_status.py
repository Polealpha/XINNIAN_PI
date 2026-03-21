from pi_runtime.runtime import PiEmotionRuntime


def test_status_reports_pi_local_health():
    runtime = PiEmotionRuntime("config/pi_zero2w.json", "config/engine_config.json")
    status = runtime.get_status()
    payload = runtime.get_status_payload()

    assert "esp_connected" not in status.health
    assert status.health["hardware_ok"] is True
    assert status.health["control_local"] is True
    assert payload["pan_angle"] == 0.0
    assert payload["tilt_angle"] == 0.0
    assert "identity_state" in payload
    assert "onboarding_state" in payload
    assert "expression_state" in payload
    assert "camera_state" in payload
    assert "display_state" in payload
    assert payload["expression_state"]["expression_id"]
    assert payload["camera_state"]["configured_backend"] in {"picamera2", "opencv"}
    assert "driver" in payload["display_state"]
