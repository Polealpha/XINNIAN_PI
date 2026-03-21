from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pi_runtime.runtime import PiEmotionRuntime


def _write_runtime_config(source_path: Path, disable_audio: bool, disable_backend: bool) -> Path:
    data = json.loads(source_path.read_text(encoding="utf-8"))
    if disable_audio:
        data.setdefault("audio", {})["enabled"] = False
    if disable_backend:
        data.setdefault("backend", {})["enabled"] = False

    temp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(data, temp, ensure_ascii=False, indent=2)
    temp.close()
    return Path(temp.name)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Pi runtime hardware diagnostics and save preview artifacts.")
    parser.add_argument("--config", default="config/pi_zero2w.st7789.example.json", help="Runtime config path")
    parser.add_argument("--engine-config", default="config/engine_config.json", help="Engine config path")
    parser.add_argument("--wait-sec", type=float, default=8.0, help="How long to wait for camera/display frames")
    parser.add_argument(
        "--output-dir",
        default="outputs/pi_runtime_diagnostics",
        help="Directory for status.json, camera_preview.jpg and display_preview.png",
    )
    parser.add_argument("--disable-audio", action="store_true", help="Disable audio while probing camera/display")
    parser.add_argument("--disable-backend", action="store_true", help="Disable backend sync while probing locally")
    args = parser.parse_args()

    config_path = (PROJECT_ROOT / args.config).resolve()
    engine_config_path = (PROJECT_ROOT / args.engine_config).resolve()
    output_dir = (PROJECT_ROOT / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    effective_config_path = _write_runtime_config(config_path, args.disable_audio, args.disable_backend)

    runtime = PiEmotionRuntime(str(effective_config_path), str(engine_config_path))
    deadline = time.time() + max(1.0, float(args.wait_sec))

    try:
        runtime.start()
        want_camera = bool(runtime.pi_config.camera.enabled)
        while time.time() < deadline:
            status = runtime.get_status_payload()
            display_preview = runtime.get_display_preview_png()
            preview_jpeg = runtime.get_preview_jpeg()
            if (want_camera and preview_jpeg) or (not want_camera and display_preview):
                break
            time.sleep(0.25)

        status = runtime.get_status_payload()
        (output_dir / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")

        preview_jpeg = runtime.get_preview_jpeg()
        if preview_jpeg:
            (output_dir / "camera_preview.jpg").write_bytes(preview_jpeg)

        display_preview = runtime.get_display_preview_png()
        if display_preview:
            (output_dir / "display_preview.png").write_bytes(display_preview)

        print(f"[diag] wrote {output_dir / 'status.json'}")
        print(f"[diag] camera preview: {'yes' if preview_jpeg else 'no'}")
        print(f"[diag] display preview: {'yes' if display_preview else 'no'}")
        print(f"[diag] camera_state={status.get('camera_state')}")
        print(f"[diag] display_state={status.get('display_state')}")
    finally:
        runtime.stop()
        try:
            effective_config_path.unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()
