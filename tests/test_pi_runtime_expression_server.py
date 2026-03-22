from fastapi.testclient import TestClient

from pi_runtime.server import build_app


def test_expression_endpoints_return_state_svg_and_runtime_diagnostics():
    app = build_app("config/pi_zero2w.st7789.example.json", "config/engine_config.json")

    with TestClient(app) as client:
        state_resp = client.get("/expression/state")
        frame_resp = client.get("/expression/frame.svg")
        camera_state_resp = client.get("/camera/state")
        display_state_resp = client.get("/display/state")
        display_frame_resp = client.get("/display/frame.png")
        expression_id = state_resp.json()["expression"]["expression_id"]
        select_resp = client.post("/expression/select", json={"expression_id": expression_id})

    assert state_resp.status_code == 200
    assert state_resp.json()["ok"] is True
    assert state_resp.json()["expression"]["expression_id"]

    assert frame_resp.status_code == 200
    assert frame_resp.headers["content-type"].startswith("image/svg+xml")
    assert "svg" in frame_resp.text

    assert camera_state_resp.status_code == 200
    assert camera_state_resp.json()["ok"] is True
    assert "camera_state" in camera_state_resp.json()

    assert display_state_resp.status_code == 200
    assert display_state_resp.json()["ok"] is True
    assert "display_state" in display_state_resp.json()

    assert display_frame_resp.status_code == 200
    assert display_frame_resp.headers["content-type"].startswith("image/png")

    assert select_resp.status_code == 200
    assert select_resp.json()["expression"]["expression_id"] == expression_id
