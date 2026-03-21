from fastapi.testclient import TestClient

from pi_runtime.server import build_app


def test_expression_endpoints_return_state_and_svg():
    app = build_app("config/pi_zero2w.headless.json", "config/engine_config.json")

    with TestClient(app) as client:
        state_resp = client.get("/expression/state")
        frame_resp = client.get("/expression/frame.svg")
        select_resp = client.post("/expression/select", json={"expression_id": "开心_1"})

    assert state_resp.status_code == 200
    assert state_resp.json()["ok"] is True
    assert state_resp.json()["expression"]["expression_id"]

    assert frame_resp.status_code == 200
    assert frame_resp.headers["content-type"].startswith("image/svg+xml")
    assert "svg" in frame_resp.text

    assert select_resp.status_code == 200
    assert select_resp.json()["expression"]["expression_id"] == "开心_1"
