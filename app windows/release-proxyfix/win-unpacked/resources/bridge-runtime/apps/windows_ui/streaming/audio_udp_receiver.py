import socket
import struct
import time
from typing import Optional

from engine.core.types import AudioFrame

MAGIC_AUD0 = 0x30445541
HEADER_STRUCT = struct.Struct("<IIIHH6s2s")


class AudioUdpReceiver:
    def __init__(self, listen_port: int = 3334) -> None:
        self.listen_port = listen_port
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.bind(("0.0.0.0", listen_port))
        self._socket.settimeout(1.0)
        self._device_ip: Optional[str] = None
        self._device_port: int = 3333
        self._last_recv_s: float = 0.0
        self._last_register_s: float = 0.0

    def register(self, device_ip: str, device_port: int = 3333) -> None:
        self._device_ip = device_ip
        self._device_port = device_port
        self._send_register()

    def ensure_streaming(self, timeout_s: float = 1.5) -> None:
        if not self._device_ip:
            return
        now = time.monotonic()
        if self._last_recv_s == 0.0 or (now - self._last_recv_s) > timeout_s:
            if now - self._last_register_s > 0.2:
                self._send_register()

    def _send_register(self) -> bool:
        if not self._device_ip:
            return False
        try:
            self._socket.sendto(b"\x00", (self._device_ip, self._device_port))
            self._last_register_s = time.monotonic()
            return True
        except OSError:
            # Keep receiver loop alive when device is temporarily unreachable.
            return False

    def recv_frame(self) -> Optional[AudioFrame]:
        try:
            data, _addr = self._socket.recvfrom(2048)
        except socket.timeout:
            return None

        if len(data) < HEADER_STRUCT.size:
            return None

        magic, seq, timestamp_ms, payload_len, _flags, mac_raw, _reserved = HEADER_STRUCT.unpack_from(
            data, 0
        )
        if magic != MAGIC_AUD0:
            return None

        payload = data[HEADER_STRUCT.size : HEADER_STRUCT.size + payload_len]
        if len(payload) != payload_len:
            return None

        device_id = ":".join(f"{b:02x}" for b in mac_raw)
        self._last_recv_s = time.monotonic()
        return AudioFrame(
            pcm_s16le=payload,
            sample_rate=16000,
            channels=1,
            timestamp_ms=timestamp_ms,
            seq=seq,
            device_id=device_id,
        )

    def close(self) -> None:
        self._socket.close()
