from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path


MODELS = {
    "face_detection_yunet_2023mar.onnx": "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "face_recognition_sface_2021dec.onnx": "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    target_dir = root / "models" / "identity"
    target_dir.mkdir(parents=True, exist_ok=True)
    for name, url in MODELS.items():
        target = target_dir / name
        if target.exists() and target.stat().st_size > 0:
            print(f"[identity-models] keep {target.name} sha256={_sha256(target)}")
            continue
        print(f"[identity-models] downloading {target.name}")
        urllib.request.urlretrieve(url, target)
        print(f"[identity-models] saved {target} sha256={_sha256(target)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
