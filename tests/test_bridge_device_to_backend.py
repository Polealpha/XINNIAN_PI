from __future__ import annotations

from engine.core.types import VideoFrame
from engine.vision.vision_types import FaceDet
from scripts.bridge_device_to_backend import DevicePreviewBridge, FaceTrackController


def test_face_track_controller_emits_rate_limited_debug_payload(monkeypatch):
    controller = FaceTrackController(
        device_ip="127.0.0.1:8090",
        tracking_cfg={"enabled": True, "ui_emit_hz": 4.0, "scene_behavior": {"desk": {"base": 0.0}}},
        scene="desk",
        backend_url="http://127.0.0.1:8000",
    )
    events = []

    monkeypatch.setattr(
        controller.detector,
        "detect",
        lambda _frame: FaceDet(found=True, bbox=(10, 20, 30, 40), cx=25.0, cy=40.0, area_ratio=0.05),
    )
    monkeypatch.setattr(
        controller.tracker,
        "update",
        lambda det, frame_w, frame_h, now_ms: (
            0.12,
            -0.08,
            {
                "found": det.found,
                "bbox": det.bbox,
                "ex": 0.1,
                "ey": -0.05,
                "ex_smooth": 0.08,
                "ey_smooth": -0.04,
                "lost": 0,
            },
        ),
    )
    monkeypatch.setattr(
        "scripts.bridge_device_to_backend.post_event",
        lambda backend_url, event_payload, timeout_sec=5.0: events.append((backend_url, event_payload)) or {"ok": True},
    )

    frame = VideoFrame(
        format="jpeg",
        data=b"frame",
        width=320,
        height=240,
        timestamp_ms=2000,
        seq=1,
        device_id="pi-zero",
    )

    payload = controller.process(frame, mode="normal")
    controller._emit_debug(2200, {"k": 2})
    controller._emit_debug(2251, {"k": 3})

    assert payload["frame_w"] == 320
    assert payload["frame_h"] == 240
    assert payload["ts_ms"] == 2000
    assert payload["bbox"] == [10, 20, 30, 40]
    assert payload["sent"] is True
    assert len(events) == 2
    assert events[0][0] == "http://127.0.0.1:8000"
    assert events[0][1]["type"] == "FaceTrackUpdate"


def test_device_preview_bridge_step_uses_status_mode_and_preview(monkeypatch):
    bridge = DevicePreviewBridge(
        device_ip="127.0.0.1:8090",
        backend_url="http://127.0.0.1:8000",
        engine_config_path="config/engine_config.json",
        poll_interval_sec=0.2,
    )
    processed = []

    monkeypatch.setattr(
        bridge,
        "_fetch_json",
        lambda path: {"device_id": "pi-zero", "mode": "normal"} if path == "/status" else {},
    )
    monkeypatch.setattr(
        bridge,
        "_fetch_preview_frame",
        lambda device_id: VideoFrame(
            format="jpeg",
            data=b"frame",
            width=320,
            height=240,
            timestamp_ms=1234,
            seq=0,
            device_id=device_id,
        ),
    )
    monkeypatch.setattr(
        bridge._controller,
        "process",
        lambda frame, mode="normal": processed.append((frame.device_id, mode)) or {"ok": True},
    )

    assert bridge.step() is True
    assert processed == [("pi-zero", "normal")]
