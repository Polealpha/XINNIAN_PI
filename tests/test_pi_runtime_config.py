from pi_runtime.config import load_pi_config


def test_load_pi_config_defaults():
    cfg = load_pi_config("config/pi_zero2w.json")
    assert cfg.service.port == 8090
    assert cfg.audio.frame_bytes == 640
    assert cfg.camera.backend == "picamera2"
