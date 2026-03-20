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
class BackendSyncConfig:
    enabled: bool = False
    base_url: str = ""
    heartbeat_interval_sec: int = 15
    timeout_sec: int = 5
    signal_poll_interval_sec: float = 1.0


@dataclass
class OnboardingConfig:
    enabled: bool = True
    hotspot_ssid: str = "EmotionPi-Setup"
    hotspot_password: str = "emotionpi123"
    hotspot_connection_name: str = "emotion-pi-onboarding"
    wifi_interface: str = "wlan0"
    state_file: str = "/var/lib/emotion-pi/onboarding_state.json"


@dataclass
class IdentityConfig:
    enabled: bool = True
    storage_dir: str = "/var/lib/emotion-pi/identity"
    models_dir: str = "models/identity"
    detector_model_path: str = "models/identity/face_detection_yunet_2023mar.onnx"
    recognizer_model_path: str = "models/identity/face_recognition_sface_2021dec.onnx"
    recognition_interval_ms: int = 750
    enrollment_min_samples: int = 8
    enrollment_target_samples: int = 10
    enrollment_max_samples: int = 12
    enrollment_sample_interval_ms: int = 700
    similarity_threshold: float = 0.36


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
    release_after_move_sec: float = 0.35


@dataclass
class TiltServoConfig:
    enabled: bool = False
    driver: str = "mock"
    gpio_pin: Optional[int] = None
    min_angle: int = -35
    max_angle: int = 35
    center_angle: int = 0
    pca9685_channel: Optional[int] = None
    pulse_min_us: int = 500
    pulse_max_us: int = 2500
    release_after_move_sec: float = 0.35


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
    tilt_servo: TiltServoConfig = field(default_factory=TiltServoConfig)
    pca9685: Pca9685Config = field(default_factory=Pca9685Config)


@dataclass
class ButtonInputConfig:
    enabled: bool = False
    gpio_pin: Optional[int] = None
    pull_up: bool = True
    hold_sec: float = 0.0
    bounce_time: float = 0.08


@dataclass
class ButtonsConfig:
    enabled: bool = False
    allow_system_power_commands: bool = False
    power_toggle: ButtonInputConfig = field(default_factory=ButtonInputConfig)
    shutdown: ButtonInputConfig = field(default_factory=ButtonInputConfig)
    settings: ButtonInputConfig = field(default_factory=ButtonInputConfig)


@dataclass
class UiConfig:
    default_page: str = "expression"
    settings_auto_return_sec: int = 0


@dataclass
class PiRuntimeConfig:
    service: ServiceConfig = field(default_factory=ServiceConfig)
    device: DeviceConfig = field(default_factory=DeviceConfig)
    backend: BackendSyncConfig = field(default_factory=BackendSyncConfig)
    onboarding: OnboardingConfig = field(default_factory=OnboardingConfig)
    identity: IdentityConfig = field(default_factory=IdentityConfig)
    audio: AudioCaptureConfig = field(default_factory=AudioCaptureConfig)
    camera: CameraCaptureConfig = field(default_factory=CameraCaptureConfig)
    hardware: HardwareConfig = field(default_factory=HardwareConfig)
    buttons: ButtonsConfig = field(default_factory=ButtonsConfig)
    ui: UiConfig = field(default_factory=UiConfig)

    @classmethod
    def from_dict(cls, data: dict) -> "PiRuntimeConfig":
        service = ServiceConfig(**(data.get("service") or {}))
        device = DeviceConfig(**(data.get("device") or {}))
        backend = BackendSyncConfig(**(data.get("backend") or {}))
        onboarding = OnboardingConfig(**(data.get("onboarding") or {}))
        identity = IdentityConfig(**(data.get("identity") or {}))
        audio = AudioCaptureConfig(**(data.get("audio") or {}))
        camera = CameraCaptureConfig(**(data.get("camera") or {}))

        hardware_raw = data.get("hardware") or {}
        pan_servo = PanServoConfig(**(hardware_raw.get("pan_servo") or {}))
        tilt_servo = TiltServoConfig(**(hardware_raw.get("tilt_servo") or {}))
        pca9685 = Pca9685Config(**(hardware_raw.get("pca9685") or {}))
        hardware = HardwareConfig(
            driver=str(hardware_raw.get("driver", "mock") or "mock"),
            speaker_command=list(hardware_raw.get("speaker_command") or ["aplay", "-q"]),
            status_led_gpio=hardware_raw.get("status_led_gpio"),
            pan_servo=pan_servo,
            tilt_servo=tilt_servo,
            pca9685=pca9685,
        )
        buttons_raw = data.get("buttons") or {}
        buttons = ButtonsConfig(
            enabled=bool(buttons_raw.get("enabled", False)),
            allow_system_power_commands=bool(buttons_raw.get("allow_system_power_commands", False)),
            power_toggle=ButtonInputConfig(**(buttons_raw.get("power_toggle") or {})),
            shutdown=ButtonInputConfig(**(buttons_raw.get("shutdown") or {})),
            settings=ButtonInputConfig(**(buttons_raw.get("settings") or {})),
        )
        ui = UiConfig(**(data.get("ui") or {}))
        return cls(
            service=service,
            device=device,
            backend=backend,
            onboarding=onboarding,
            identity=identity,
            audio=audio,
            camera=camera,
            hardware=hardware,
            buttons=buttons,
            ui=ui,
        )


def load_pi_config(path: str) -> PiRuntimeConfig:
    raw_path = Path(path)
    data = json.loads(raw_path.read_text(encoding="utf-8"))
    return PiRuntimeConfig.from_dict(data)
