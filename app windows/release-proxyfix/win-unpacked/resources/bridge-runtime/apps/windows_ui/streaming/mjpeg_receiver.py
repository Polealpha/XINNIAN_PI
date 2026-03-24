from typing import Generator, Tuple

import requests

from engine.core.types import VideoFrame
from engine.core.clock import now_ms

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None
    np = None

SOF_MARKERS = {
    0xC0,
    0xC1,
    0xC2,
    0xC3,
    0xC5,
    0xC6,
    0xC7,
    0xC9,
    0xCA,
    0xCB,
    0xCD,
    0xCE,
    0xCF,
}


class MjpegReceiver:
    def __init__(self, url: str, timeout: float = 1.8) -> None:
        self.url = url
        self.timeout = timeout
        self._session = requests.Session()
        # Never route local device stream traffic through host proxy settings.
        self._session.trust_env = False

    def iter_frames(self) -> Generator[VideoFrame, None, None]:
        # Use short read timeout so stalled streams recover quickly.
        response = self._session.get(self.url, stream=True, timeout=(2.0, self.timeout))
        response.raise_for_status()

        buffer = b""
        seq = 0
        for chunk in response.iter_content(chunk_size=4096):
            if not chunk:
                continue
            buffer += chunk
            while True:
                start = buffer.find(b"\xff\xd8")
                if start == -1:
                    if len(buffer) > 1024 * 1024:
                        buffer = buffer[-2:]
                    break
                end = buffer.find(b"\xff\xd9", start + 2)
                if end == -1:
                    if len(buffer) > 1024 * 1024:
                        buffer = buffer[start:]
                    break
                jpeg = buffer[start : end + 2]
                buffer = buffer[end + 2 :]

                width, height = _jpeg_size(jpeg)
                if width <= 0 or height <= 0:
                    continue
                if cv2 is not None and np is not None:
                    try:
                        decoded = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
                        if decoded is None:
                            continue
                        height, width = decoded.shape[:2]
                    except Exception:
                        continue
                seq += 1
                yield VideoFrame(
                    format="jpeg",
                    data=jpeg,
                    width=width,
                    height=height,
                    timestamp_ms=now_ms(),
                    seq=seq,
                    device_id="",
                )

    def close(self) -> None:
        self._session.close()


def _jpeg_size(data: bytes) -> Tuple[int, int]:
    if len(data) < 4 or data[0:2] != b"\xff\xd8":
        return 0, 0
    idx = 2
    length = len(data)
    while idx + 3 < length:
        if data[idx] != 0xFF:
            idx += 1
            continue
        marker = data[idx + 1]
        if marker in SOF_MARKERS:
            if idx + 8 >= length:
                return 0, 0
            height = (data[idx + 5] << 8) | data[idx + 6]
            width = (data[idx + 7] << 8) | data[idx + 8]
            return width, height
        if marker == 0xDA or marker == 0xD9:
            break
        if idx + 4 >= length:
            break
        seg_len = (data[idx + 2] << 8) | data[idx + 3]
        if seg_len < 2:
            break
        idx += 2 + seg_len
    return 0, 0
