from pathlib import Path

from pi_runtime.expression_surface import ExpressionSurface
from pi_runtime.runtime import PiEmotionRuntime


def test_expression_surface_loads_full_catalog_and_renders_svg():
    surface = ExpressionSurface(Path("pi_runtime/expression_catalog.json"))

    assert len(surface.expressions) == 100
    assert surface.expressions[0].id == "常规_1"
    assert surface.expressions[5].id == "开心_1"

    svg = surface.render_svg(
        now_ms=1234,
        runtime_state={
            "ui_page": "expression",
            "voice_mode": "idle",
            "owner_recognized": False,
            "onboarding_state": "connected",
            "risk_score": 0.1,
            "gaze_x": 0.0,
            "gaze_y": 0.0,
        },
        width=320,
        height=240,
    )

    assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg"')
    assert "ambient" in svg
    assert "常规_1" in svg


def test_expression_surface_context_mapping_uses_clean_utf8_prefixes():
    surface = ExpressionSurface(Path("pi_runtime/expression_catalog.json"))

    surface.snapshot(
        now_ms=2000,
        runtime_state={
            "ui_page": "expression",
            "voice_mode": "idle",
            "owner_recognized": True,
            "onboarding_state": "connected",
            "risk_score": 0.1,
            "gaze_x": 1.5,
            "gaze_y": -0.5,
        },
    )
    owner = surface.snapshot(
        now_ms=3200,
        runtime_state={
            "ui_page": "expression",
            "voice_mode": "idle",
            "owner_recognized": True,
            "onboarding_state": "connected",
            "risk_score": 0.1,
            "gaze_x": 1.5,
            "gaze_y": -0.5,
        },
    )
    surface.set_expression_index(None)
    surface.snapshot(
        now_ms=3600,
        runtime_state={
            "ui_page": "expression",
            "voice_mode": "wake_listen",
            "owner_recognized": False,
            "onboarding_state": "connected",
            "risk_score": 0.1,
            "gaze_x": 0.0,
            "gaze_y": 0.0,
        },
    )
    listening = surface.snapshot(
        now_ms=4600,
        runtime_state={
            "ui_page": "expression",
            "voice_mode": "wake_listen",
            "owner_recognized": False,
            "onboarding_state": "connected",
            "risk_score": 0.1,
            "gaze_x": 0.0,
            "gaze_y": 0.0,
        },
    )

    assert owner["expression_id"].startswith("开心_")
    assert listening["expression_id"].startswith("思考_")
    assert "gaze_x" in owner
    assert "breath_speed_ms" in owner


def test_runtime_can_select_expression_and_export_svg():
    runtime = PiEmotionRuntime("config/pi_zero2w.headless.json", "config/engine_config.json")

    state = runtime.select_expression(expression_id="开心_1")
    svg = runtime.get_expression_svg()

    assert state["expression_id"] == "开心_1"
    assert "开心_1" in svg
