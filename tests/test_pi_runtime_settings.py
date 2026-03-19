from pi_runtime.runtime import PiEmotionRuntime


def test_runtime_settings_apply_and_ui_page_flow():
    runtime = PiEmotionRuntime("config/pi_zero2w.headless.json", "config/engine_config.json")

    settings = runtime.apply_settings(
        {
            "media": {"camera_enabled": False, "audio_enabled": True},
            "wake": {"enabled": False, "wake_phrase": "小暖", "ack_text": "在呢"},
            "behavior": {"settings_auto_return_sec": 12, "daily_trigger_limit": 9},
            "tracking": {"pan_enabled": False, "tilt_enabled": True},
        },
        source="test",
    )
    assert settings["media"]["camera_enabled"] is False
    assert settings["wake"]["enabled"] is False
    assert settings["wake"]["wake_phrase"] == "小暖"
    assert settings["behavior"]["settings_auto_return_sec"] == 12
    assert settings["tracking"]["pan_enabled"] is False

    opened = runtime.open_settings_page("button")
    assert opened["page"] == "settings"
    assert opened["source"] == "button"

    closed = runtime.close_settings_page("desktop")
    assert closed["page"] == "expression"
    assert closed["source"] == "desktop"

    ui_state = runtime.toggle_power_state("button")
    assert "screen_awake" in ui_state

