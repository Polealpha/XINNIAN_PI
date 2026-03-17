from pi_runtime.runtime import PiEmotionRuntime


def test_status_reports_pi_local_health():
    runtime = PiEmotionRuntime("config/pi_zero2w.json", "config/engine_config.json")
    status = runtime.get_status()

    assert "esp_connected" not in status.health
    assert status.health["hardware_ok"] is True
    assert status.health["control_local"] is True
