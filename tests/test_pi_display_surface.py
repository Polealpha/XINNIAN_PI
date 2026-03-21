from pi_runtime.config import UiConfig
from pi_runtime.display_surface import build_display_surface


def test_build_web_display_surface_returns_null_driver():
    surface = build_display_surface(UiConfig(display_driver="web"))
    status = surface.get_status()

    assert status.ready is False
    assert status.driver == "web"


def test_st7789_surface_reports_driver_even_when_library_missing():
    surface = build_display_surface(
        UiConfig(
            display_driver="st7789",
            expression_width=320,
            expression_height=240,
            spi_dc_gpio=25,
        )
    )
    status = surface.get_status()

    assert status.driver == "st7789"


def test_st7789_surface_can_render_preview_png_without_device():
    surface = build_display_surface(
        UiConfig(
            display_driver="st7789",
            expression_width=320,
            expression_height=240,
            spi_dc_gpio=25,
        )
    )

    payload = {
        "timestamp_ms": 1234,
        "ui_state": {"page": "expression", "screen_awake": True},
        "expression_state": {
            "expression_id": "happy_1",
            "reason": "ambient",
            "blinking": False,
            "gaze_x": 4.0,
            "gaze_y": -2.0,
            "left": {"x": 104, "y": 112, "w": 52, "h": 52, "r": 20, "rot": 0, "color": "#7ee7ff"},
            "right": {"x": 216, "y": 112, "w": 52, "h": 52, "r": 20, "rot": 0, "color": "#7ee7ff"},
        },
        "settings": {},
        "voice_state": {},
        "display_state": {"driver": "st7789", "ready": False},
    }

    preview = surface.render_preview_png(payload)

    assert preview.startswith(b"\x89PNG")
