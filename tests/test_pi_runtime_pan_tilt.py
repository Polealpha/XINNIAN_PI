from engine.vision.face_tracker import FaceTracker
from engine.vision.vision_types import FaceDet
from pi_runtime.runtime import PiEmotionRuntime


def test_manual_pan_tilt_updates_runtime_status():
    runtime = PiEmotionRuntime("config/pi_zero2w.json", "config/engine_config.json")
    result = runtime.set_manual_pan_tilt(0.25, -0.4)
    payload = runtime.get_status_payload()

    assert result["ok"] is True
    assert result["pan"] == 0.25
    assert result["tilt"] == -0.4
    assert payload["pan_angle"] != 0.0
    assert payload["tilt_angle"] != 0.0


def test_tracking_target_is_smoothed_instead_of_jumping_each_frame():
    runtime = PiEmotionRuntime("config/pi_zero2w.json", "config/engine_config.json")

    changed = runtime._apply_tracking_target(0.6, -0.42)

    assert changed is True
    assert 0.0 < runtime._last_pan_turn < 0.6
    assert -0.42 < runtime._last_tilt_turn < 0.0


def test_tracking_target_deadband_suppresses_small_servo_rewrites():
    runtime = PiEmotionRuntime("config/pi_zero2w.json", "config/engine_config.json")
    runtime.set_manual_pan_tilt(0.2, -0.1)

    changed = runtime._apply_tracking_target(0.205, -0.095)

    assert changed is False
    assert runtime._last_pan_turn == 0.2
    assert runtime._last_tilt_turn == -0.1


def test_runtime_tracking_return_to_center_is_delayed_and_gradual():
    runtime = PiEmotionRuntime("config/pi_zero2w.json", "config/engine_config.json")
    tracker = runtime._face_tracker

    assert tracker is not None

    det = FaceDet(found=True, bbox=(210, 60, 90, 90), cx=280, cy=110, area_ratio=0.05)
    pan_turn, tilt_turn, _ = tracker.update(det, 320, 240, 400)
    runtime._apply_tracking_target(pan_turn, tilt_turn)
    initial_pan = runtime._last_pan_turn

    first_return, first_tilt, _ = tracker.update(FaceDet(found=False), 320, 240, 400)
    if first_return is not None or first_tilt is not None:
        runtime._apply_tracking_target(first_return, first_tilt)
    second_return, second_tilt, _ = tracker.update(FaceDet(found=False), 320, 240, 700)
    if second_return is not None or second_tilt is not None:
        runtime._apply_tracking_target(second_return, second_tilt)

    assert initial_pan != 0.0
    assert runtime._last_pan_turn != 0.0
    assert abs(runtime._last_pan_turn) <= abs(initial_pan)


def test_face_tracker_damps_large_face_and_returns_to_center():
    tracker = FaceTracker(
        {
            "dead_zone": 0.02,
            "dead_zone_y": 0.02,
            "ema_alpha": 1.0,
            "ema_alpha_y": 1.0,
            "kp": 0.8,
            "kp_y": 0.8,
            "turn_max": 0.8,
            "tilt_max": 0.8,
            "send_hz": 20,
            "lost_frames_stop": 4,
            "return_start_frames": 2,
            "return_alpha": 0.5,
            "preferred_face_area_ratio": 0.12,
            "area_gain_floor": 0.3,
        }
    )

    near = FaceDet(found=True, bbox=(220, 80, 180, 180), cx=310, cy=170, area_ratio=0.18)
    far = FaceDet(found=True, bbox=(220, 80, 70, 70), cx=255, cy=115, area_ratio=0.03)
    near_turn, _, _ = tracker.update(near, 320, 240, 100)
    far_turn, _, _ = tracker.update(far, 320, 240, 180)

    assert near_turn is not None
    assert far_turn is not None
    assert abs(float(far_turn)) > abs(float(near_turn))

    missing = FaceDet(found=False)
    first_return, _, _ = tracker.update(missing, 320, 240, 260)
    second_return, _, _ = tracker.update(missing, 320, 240, 340)
    third_return, _, _ = tracker.update(missing, 320, 240, 420)

    assert first_return is None
    assert second_return is not None
    assert third_return is not None
    assert abs(float(third_return)) <= abs(float(second_return))
