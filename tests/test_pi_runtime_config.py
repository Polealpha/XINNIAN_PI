from pi_runtime.config import load_pi_config


def test_load_pi_config_defaults():
    cfg = load_pi_config("config/pi_zero2w.json")
    assert cfg.service.port == 8090
    assert cfg.audio.frame_bytes == 640
    assert cfg.camera.backend == "picamera2"


def test_load_pi_config_headless_defaults():
    cfg = load_pi_config("config/pi_zero2w.headless.json")
    assert cfg.audio.enabled is False
    assert cfg.camera.enabled is False
    assert cfg.hardware.driver == "mock"
