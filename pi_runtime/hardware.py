from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
import logging
import math
import subprocess
import tempfile
import wave

from engine.tts.tts_engine import TtsEngine

from .config import HardwareConfig

logger = logging.getLogger(__name__)


class BaseHardware(ABC):
    def __init__(self, config: HardwareConfig) -> None:
        self.config = config

    @abstractmethod
    def set_pan_turn(self, turn: float) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_tilt_turn(self, turn: float) -> None:
        raise NotImplementedError

    def set_pan_tilt(self, pan: float, tilt: float) -> None:
        self.set_pan_turn(pan)
        self.set_tilt_turn(tilt)

    def set_status_active(self, active: bool) -> None:
        _ = active

    def speak(self, tts: TtsEngine, text: str) -> bool:
        if not text.strip():
            return False
        audio = tts.synthesize(text, target_rate=16000)
        if not audio:
            logger.warning("tts synthesize failed or disabled")
            return False
        pcm, sample_rate = audio
        return self.play_pcm(pcm, sample_rate)

    def play_pcm(self, pcm: bytes, sample_rate: int) -> bool:
        if not pcm:
            return False
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = Path(tmp.name)
        try:
            with wave.open(str(wav_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(pcm)
            cmd = list(self.config.speaker_command or ["aplay", "-q"])
            subprocess.run(cmd + [str(wav_path)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception as exc:
            logger.warning("speaker playback failed: %s", exc)
            return False
        finally:
            try:
                wav_path.unlink(missing_ok=True)
            except Exception:
                pass

    def close(self) -> None:
        return


class MockHardware(BaseHardware):
    def set_pan_turn(self, turn: float) -> None:
        logger.debug("mock pan turn=%.3f", turn)

    def set_tilt_turn(self, turn: float) -> None:
        logger.debug("mock tilt turn=%.3f", turn)


class GpioServoHardware(BaseHardware):
    def __init__(self, config: HardwareConfig) -> None:
        super().__init__(config)
        self._pan_servo = None
        self._tilt_servo = None
        self._led = None
        self._current_pan_angle = float(config.pan_servo.center_angle)
        self._current_tilt_angle = float(config.tilt_servo.center_angle)
        try:
            from gpiozero import AngularServo, LED  # type: ignore
        except Exception as exc:
            logger.warning("gpiozero unavailable, falling back to mock hardware: %s", exc)
            return

        try:
            if config.pan_servo.enabled and config.pan_servo.gpio_pin is not None:
                self._pan_servo = AngularServo(
                    config.pan_servo.gpio_pin,
                    min_angle=config.pan_servo.min_angle,
                    max_angle=config.pan_servo.max_angle,
                    initial_angle=config.pan_servo.center_angle,
                    min_pulse_width=config.pan_servo.pulse_min_us / 1_000_000.0,
                    max_pulse_width=config.pan_servo.pulse_max_us / 1_000_000.0,
                )
            if config.tilt_servo.enabled and config.tilt_servo.gpio_pin is not None:
                self._tilt_servo = AngularServo(
                    config.tilt_servo.gpio_pin,
                    min_angle=config.tilt_servo.min_angle,
                    max_angle=config.tilt_servo.max_angle,
                    initial_angle=config.tilt_servo.center_angle,
                    min_pulse_width=config.tilt_servo.pulse_min_us / 1_000_000.0,
                    max_pulse_width=config.tilt_servo.pulse_max_us / 1_000_000.0,
                )
            if config.status_led_gpio is not None:
                self._led = LED(config.status_led_gpio)
        except Exception as exc:
            logger.warning("gpio hardware init failed: %s", exc)
            self._pan_servo = None
            self._tilt_servo = None
            self._led = None

    def set_pan_turn(self, turn: float) -> None:
        if self._pan_servo is None:
            return
        span = max(abs(self.config.pan_servo.min_angle), abs(self.config.pan_servo.max_angle))
        angle = self.config.pan_servo.center_angle + (float(turn) * span)
        angle = max(self.config.pan_servo.min_angle, min(self.config.pan_servo.max_angle, angle))
        if math.isclose(angle, self._current_pan_angle, abs_tol=1.0):
            return
        self._current_pan_angle = angle
        try:
            self._pan_servo.angle = angle
        except Exception as exc:
            logger.warning("gpio servo move failed: %s", exc)

    def set_tilt_turn(self, turn: float) -> None:
        if self._tilt_servo is None:
            return
        span = max(abs(self.config.tilt_servo.min_angle), abs(self.config.tilt_servo.max_angle))
        angle = self.config.tilt_servo.center_angle + (float(turn) * span)
        angle = max(self.config.tilt_servo.min_angle, min(self.config.tilt_servo.max_angle, angle))
        if math.isclose(angle, self._current_tilt_angle, abs_tol=1.0):
            return
        self._current_tilt_angle = angle
        try:
            self._tilt_servo.angle = angle
        except Exception as exc:
            logger.warning("gpio tilt servo move failed: %s", exc)

    def set_status_active(self, active: bool) -> None:
        if self._led is None:
            return
        try:
            if active:
                self._led.on()
            else:
                self._led.off()
        except Exception:
            pass

    def close(self) -> None:
        try:
            if self._pan_servo is not None:
                self._pan_servo.close()
        except Exception:
            pass
        try:
            if self._tilt_servo is not None:
                self._tilt_servo.close()
        except Exception:
            pass
        try:
            if self._led is not None:
                self._led.close()
        except Exception:
            pass


class Pca9685Hardware(BaseHardware):
    def __init__(self, config: HardwareConfig) -> None:
        super().__init__(config)
        self._kit = None
        self._current_pan_angle = float(config.pan_servo.center_angle)
        self._current_tilt_angle = float(config.tilt_servo.center_angle)
        try:
            from adafruit_servokit import ServoKit  # type: ignore
        except Exception as exc:
            logger.warning("ServoKit unavailable, falling back to mock hardware: %s", exc)
            return

        try:
            self._kit = ServoKit(channels=16, address=int(config.pca9685.address), frequency=int(config.pca9685.frequency))
            if config.pan_servo.pca9685_channel is not None:
                pan = self._kit.servo[config.pan_servo.pca9685_channel]
                pan.set_pulse_width_range(
                    int(config.pan_servo.pulse_min_us),
                    int(config.pan_servo.pulse_max_us),
                )
                pan.angle = self._map_signed_angle(
                    config.pan_servo.center_angle,
                    config.pan_servo.min_angle,
                    config.pan_servo.max_angle,
                )
            if config.tilt_servo.pca9685_channel is not None:
                tilt = self._kit.servo[config.tilt_servo.pca9685_channel]
                tilt.set_pulse_width_range(
                    int(config.tilt_servo.pulse_min_us),
                    int(config.tilt_servo.pulse_max_us),
                )
                tilt.angle = self._map_signed_angle(
                    config.tilt_servo.center_angle,
                    config.tilt_servo.min_angle,
                    config.tilt_servo.max_angle,
                )
        except Exception as exc:
            logger.warning("pca9685 init failed: %s", exc)
            self._kit = None

    def _map_signed_angle(self, angle: float, min_angle: float, max_angle: float) -> float:
        clamped = max(min_angle, min(max_angle, angle))
        signed_span = max_angle - min_angle
        if signed_span <= 0:
            return 90.0
        ratio = (clamped - min_angle) / float(signed_span)
        return max(0.0, min(180.0, ratio * 180.0))

    def set_pan_turn(self, turn: float) -> None:
        if self._kit is None or self.config.pan_servo.pca9685_channel is None:
            return
        span = max(abs(self.config.pan_servo.min_angle), abs(self.config.pan_servo.max_angle))
        angle = self.config.pan_servo.center_angle + (float(turn) * span)
        angle = max(self.config.pan_servo.min_angle, min(self.config.pan_servo.max_angle, angle))
        if math.isclose(angle, self._current_pan_angle, abs_tol=1.0):
            return
        self._current_pan_angle = angle
        try:
            self._kit.servo[self.config.pan_servo.pca9685_channel].angle = self._map_signed_angle(
                angle,
                self.config.pan_servo.min_angle,
                self.config.pan_servo.max_angle,
            )
        except Exception as exc:
            logger.warning("pca9685 move failed: %s", exc)

    def set_tilt_turn(self, turn: float) -> None:
        if self._kit is None or self.config.tilt_servo.pca9685_channel is None:
            return
        span = max(abs(self.config.tilt_servo.min_angle), abs(self.config.tilt_servo.max_angle))
        angle = self.config.tilt_servo.center_angle + (float(turn) * span)
        angle = max(self.config.tilt_servo.min_angle, min(self.config.tilt_servo.max_angle, angle))
        if math.isclose(angle, self._current_tilt_angle, abs_tol=1.0):
            return
        self._current_tilt_angle = angle
        try:
            self._kit.servo[self.config.tilt_servo.pca9685_channel].angle = self._map_signed_angle(
                angle,
                self.config.tilt_servo.min_angle,
                self.config.tilt_servo.max_angle,
            )
        except Exception as exc:
            logger.warning("pca9685 tilt move failed: %s", exc)


def build_hardware(config: HardwareConfig) -> BaseHardware:
    driver = str(config.driver or "mock").strip().lower()
    if driver == "gpio":
        return GpioServoHardware(config)
    if driver == "pca9685":
        return Pca9685Hardware(config)
    return MockHardware(config)
