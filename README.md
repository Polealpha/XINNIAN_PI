# Emotion Companion for Raspberry Pi Zero 2 W

This repository is the Raspberry Pi Zero 2 W adaptation of the original "共感智能 / Emotion Engine" project. The active deployment target is now a single Pi-first runtime instead of the earlier ESP32 / STM32 split stack.

## Current layout

- `pi_runtime/`: on-device runtime for capture, risk scoring, care delivery, TTS playback and hardware control
- `engine/`: reusable emotion scoring, policy, LLM and summary modules
- `backend/`: optional FastAPI service for remote clients, chat history and device state
- `server_backend/`: backend launch wrapper
- `config/`: Pi-oriented runtime configs, including headless and PCA9685 reference files

## What was removed

- Old Windows/Electron app
- Old Android/Capacitor app
- ESP32 firmware as an active dependency
- STM32 firmware as an active dependency
- Old BLE / SoftAP provisioning path from the active backend runtime

## Quick start on Pi

1. Review the config files:
   - no external hardware yet: `config/pi_zero2w.headless.json`
   - camera + microphone: `config/pi_zero2w.json`
   - camera + microphone + PCA9685 servo: `config/pi_zero2w.pca9685.example.json`
2. Run `scripts/install_pi.sh`
3. Start the runtime:

```bash
source .venv/bin/activate
python -m pi_runtime.server --config config/pi_zero2w.headless.json --engine-config config/engine_config.json
```

4. Optional remote API:

```bash
source .venv/bin/activate
python server_backend/run_server.py
```

## Runtime API

- `GET /healthz`
- `GET /status`
- `GET /risk`
- `GET /events?limit=50`
- `GET /onboarding/state`
- `GET /onboarding/networks`
- `POST /onboarding/wifi`
- `POST /onboarding/reset`
- `GET /camera/preview.jpg`
- `GET /owner/status`
- `POST /owner/enrollment/start`
- `POST /owner/enrollment/reset`
- `POST /signal`
- `POST /care/manual`
- `POST /speak`
- `POST /pan_tilt`
- `GET /summary`

## Backend API additions

- `POST /api/device/claim`
- `GET /api/device/claim/status`
- `POST /api/device/owner/enrollment`
- `GET /api/device/owner/status`
- `POST /api/assistant/send`
- `POST /api/assistant/bridge/send`
- `GET /api/assistant/session/status`
- `POST /api/assistant/session/reset`
- `GET /api/assistant/todos`
- `POST /api/assistant/todos`
- `PATCH /api/assistant/todos/{id}`
- `GET /api/assistant/memory/search`

## Video and onboarding flow

- There is no backend video relay. The Pi captures frames locally through `picamera2` or OpenCV and only exposes a local JPEG preview endpoint.
- First-time Wi-Fi setup is now Pi-local: when `wlan0` has no working Wi-Fi, the Pi can start a temporary hotspot and accept Wi-Fi credentials through the local onboarding API.
- After the Pi joins the home network, the desktop or mobile client should authenticate against the backend, call `/api/device/claim`, then call the Pi-local owner enrollment API with the returned `claim_token`.
- The Pi stores the owner embedding locally under `/var/lib/emotion-pi/identity/`; the backend stores only claim and owner metadata.

## Hardware bring-up

- Wiring and power guide: `docs/pi_hardware_wiring.md`
- Migration summary: `docs/raspberry_pi_zero2w_migration.md`
- Engine design: `docs/engine_design.md`
- OpenClaw software integration: `docs/openclaw_integration.md`

## Notes

- The default install now prefers a headless config so the service can boot cleanly before hardware is attached.
- `pi_runtime` degrades cleanly when camera, servo or TTS dependencies are partially unavailable.
- API keys are no longer stored in tracked config files. Provide them through `/etc/default/emotion-pi`.
- This adaptation is a userland migration. It does not require reflashing or reinstalling Raspberry Pi OS.
