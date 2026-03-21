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
