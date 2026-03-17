from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
import json


@dataclass
class ServiceConfig:
    host: str = "0.0.0.0"
    port: int = 8090


@dataclass
class DeviceConfig:
    device_id: str = "emotion-pi-zero2w"
    scene: str = "desk"


@dataclass
class AudioCaptureConfig:
    enabled: bool = True
    sample_rate: int = 16000
    channels: int = 1
    frame_ms: int = 20
    command: List[str] = field(
        default_factory=lambda: [
            "arecord",
            "-q",
            "-D",
            "default",
            "-f",
            "S16_LE",
            "-r",
            "16000",
            "-c",
            "1",
            "-t",
            "raw",
        ]
    )
    restart_backoff_sec: float = 2.0

    @property
    def frame_bytes(self) -> int:
        samples = int(self.sample_rate * self.frame_ms / 1000)
        return samples * max(1, self.channels) * 2


@dataclass
class CameraCaptureConfig:
    enabled: bool = True
    backend: str = "picamera2"
    device_index: int = 0
    width: int = 320
    height: int = 240
    fps: int = 2


@dataclass
class PanServoConfig:
    enabled: bool = False
    driver: str = "mock"
    gpio_pin: Optional[int] = None
    min_angle: int = -65
    max_angle: int = 65
    center_angle: int = 0
    pca9685_channel: Optional[int] = None
    pulse_min_us: int = 500
    pulse_max_us: int = 2500


@dataclass
class Pca9685Config:
    enabled: bool = False
    address: int = 0x40
    frequency: int = 50


@dataclass
class HardwareConfig:
    driver: str = "mock"
    speaker_command: List[str] = field(default_factory=lambda: ["aplay", "-q"])
    status_led_gpio: Optional[int] = None
    pan_servo: PanServoConfig = field(default_factory=PanServoConfig)
    pca9685: Pca9685Config = field(default_factory=Pca9685Config)


@dataclass
class PiRuntimeConfig:
    service: ServiceConfig = field(default_factory=ServiceConfig)
    device: DeviceConfig = field(default_factory=DeviceConfig)
    audio: AudioCaptureConfig = field(default_factory=AudioCaptureConfig)
    camera: CameraCaptureConfig = field(default_factory=CameraCaptureConfig)
    hardware: HardwareConfig = field(default_factory=HardwareConfig)

    @classmethod
    def from_dict(cls, data: dict) -> "PiRuntimeConfig":
        service = ServiceConfig(**(data.get("service") or {}))
        device = DeviceConfig(**(data.get("device") or {}))
        audio = AudioCaptureConfig(**(data.get("audio") or {}))
        camera = CameraCaptureConfig(**(data.get("camera") or {}))

        hardware_raw = data.get("hardware") or {}
        pan_servo = PanServoConfig(**(hardware_raw.get("pan_servo") or {}))
        pca9685 = Pca9685Config(**(hardware_raw.get("pca9685") or {}))
        hardware = HardwareConfig(
            driver=str(hardware_raw.get("driver", "mock") or "mock"),
            speaker_command=list(hardware_raw.get("speaker_command") or ["aplay", "-q"]),
            status_led_gpio=hardware_raw.get("status_led_gpio"),
            pan_servo=pan_servo,
            pca9685=pca9685,
        )
        return cls(
            service=service,
            device=device,
            audio=audio,
            camera=camera,
            hardware=hardware,
        )


def load_pi_config(path: str) -> PiRuntimeConfig:
    raw_path = Path(path)
    data = json.loads(raw_path.read_text(encoding="utf-8"))
    return PiRuntimeConfig.from_dict(data)
