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

## Design constraints on Zero 2 W

- No heavy local vision stack by default. The old MediaPipe + FER path is too expensive for Zero 2 W.
- No local Whisper/Torch requirement. Default ASR path is network-based DashScope when configured.
- Hardware integrations must degrade cleanly. Missing PCA9685, GPIO or camera modules must not prevent the core service from starting.

## Runtime differences from the old project

- `pi_runtime.runtime.PiEmotionRuntime` replaces the old ESP32->host streaming path.
- Vision risk is now lightweight engagement/attention proxy scoring instead of the previous heavier FER-centric pipeline.
- Old BLE/SoftAP provisioning remains in the backend as legacy code, but it is not required for Pi deployment.
- Motion output is abstracted through `pi_runtime.hardware`, which supports mock mode, direct GPIO servo, and PCA9685.

## Suggested hardware wiring

- USB or I2S microphone to ALSA input
- I2S DAC or USB speaker output for `aplay`
- CSI or USB camera
- Optional PCA9685 on I2C for pan/tilt or expressive motion
- Optional status LED on a GPIO pin

## Deployment recommendation

- Run `pi_runtime` as the always-on local service.
- Run `backend` only if you need remote app login, chat history, or status dashboards.
- Keep LLM and ASR keys in `/etc/default/emotion-pi` or systemd environment files, not in the repository.
