from backend.assistant_service import build_session_key, normalize_surface


def test_build_session_key_separates_surfaces():
    assert normalize_surface("DESKTOP") == "desktop"
    assert build_session_key("desktop", user_id=7) == "desktop:7"
    assert build_session_key("mobile", user_id=7) == "mobile:7"
    assert build_session_key("wecom", user_id=7, sender_id="alice") == "wecom:alice"
    assert build_session_key("robot", user_id=7, device_id="pi-zero") == "robot:pi-zero"
    assert build_session_key("desktop", user_id=7, explicit="custom:session") == "custom:session"
