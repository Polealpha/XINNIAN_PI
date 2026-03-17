# Raspberry Pi Zero 2 W Migration Notes

## Old topology

- ESP32-S3 exposed camera stream, UDP audio, HTTP command channel and local expression output.
- STM32 received UART motion and balance commands from ESP32.
- Python engine and backend ran on a separate computer.

## New topology

- Raspberry Pi Zero 2 W becomes the only edge compute node.
- Audio capture is pulled locally from ALSA via `arecord`.
- Camera capture is pulled locally from `Picamera2` with OpenCV fallback.
- Care logic, TTS and hardware control run in one Python process.
- Optional FastAPI backend remains available for remote app access.

## What changed in this refactor

- The active runtime path no longer depends on ESP32 or STM32.
- Legacy BLE / SoftAP provisioning code was removed from the active backend path.
- Startup defaults now prefer a headless Pi config so the service can boot cleanly before hardware is attached.
- Systemd services now run as the deploy user instead of `root`, with lower thread and task limits for Zero 2 W.

## Deployment recommendation

- Use `config/pi_zero2w.headless.json` during bring-up and remote debugging.
- Switch to `config/pi_zero2w.json` after microphone and camera are confirmed.
- Switch to `config/pi_zero2w.pca9685.example.json` after I2C, PCA9685 and servo power are wired correctly.
- Keep LLM and ASR keys in `/etc/default/emotion-pi`, not in the repository.
