from pi_runtime.config import load_pi_config


def test_load_pi_config_defaults():
    cfg = load_pi_config("config/pi_zero2w.json")
    assert cfg.service.port == 8090
    assert cfg.backend.enabled is True
    assert cfg.backend.base_url == "http://127.0.0.1:8000"
    assert cfg.onboarding.enabled is True
    assert cfg.identity.enabled is True
    assert cfg.audio.frame_bytes == 640
    assert cfg.camera.backend == "picamera2"
    assert cfg.hardware.tilt_servo.max_angle == 35
    assert cfg.ui.display_driver == "web"
    assert cfg.ui.expression_width == 320


def test_load_pi_config_headless_defaults():
    cfg = load_pi_config("config/pi_zero2w.headless.json")
    assert cfg.backend.enabled is True
    assert cfg.audio.enabled is False
    assert cfg.camera.enabled is False
    assert cfg.identity.enabled is False
    assert cfg.hardware.driver == "mock"


def test_load_pi_config_st7789_example():
    cfg = load_pi_config("config/pi_zero2w.st7789.example.json")

    assert cfg.ui.display_driver == "st7789"
    assert cfg.ui.spi_dc_gpio == 25
    assert cfg.ui.spi_reset_gpio == 27
    assert cfg.ui.spi_backlight_gpio == 24
