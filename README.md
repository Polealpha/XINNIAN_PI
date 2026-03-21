# Emotion Companion for Raspberry Pi Zero 2 W

This repository is the Raspberry Pi Zero 2 W adaptation of the original "共感智能 / Emotion Engine" project. The active deployment target is now a single Pi-first runtime instead of the earlier ESP32 / STM32 split stack.

## Current layout

- `pi_runtime/`: on-device runtime for capture, risk scoring, care delivery, TTS playback and hardware control
- `engine/`: reusable emotion scoring, policy, LLM and summary modules
- `backend/`: optional FastAPI service for remote clients, chat history and device state
- `server_backend/`: backend launch wrapper
- `config/`: Pi-oriented runtime configs, including headless and PCA9685 reference files
- `app windows/`: Electron + React desktop app with native login, activation and assessment flow

## What was removed

- Old Android/Capacitor app
- ESP32 firmware as an active dependency
- STM32 firmware as an active dependency
- Old BLE / SoftAP provisioning path from the active backend runtime

## Quick start on Pi

1. Review the config files:
   - no external hardware yet: `config/pi_zero2w.headless.json`
   - default real-hardware bring-up on Haicoin's Pi rig: `config/pi_zero2w.json`
   - camera + microphone + PCA9685 servo: `config/pi_zero2w.pca9685.example.json`
   - ST7789 + GPIO servo reference: `config/pi_zero2w.st7789.example.json`

   Current defaults assume:
   - servo physical pin 32 → BCM 12 (pan)
   - servo physical pin 33 → BCM 13 (tilt)
   - ST7789 follows `st7789_test_luma.txt`: SPI0.0, DC=24, RST=25, 320x240, rotate=0
2. Run `scripts/install_pi.sh`
3. Start the runtime:

```bash
source .venv/bin/activate
python -m pi_runtime.server --config config/pi_zero2w.json --engine-config config/engine_config.json
```

4. Optional remote API:

```bash
source .venv/bin/activate
python scripts/bootstrap_server_backend.py
python server_backend/run_server.py
```

## Pi hardware diagnostics

For overnight bring-up or wiring checks, run:

```bash
python scripts/pi_runtime_diagnostics.py --disable-audio --disable-backend
```

It writes:

- `outputs/pi_runtime_diagnostics/status.json`
- `outputs/pi_runtime_diagnostics/camera_preview.jpg` when a video frame is captured
- `outputs/pi_runtime_diagnostics/display_preview.png` when the Pi display renderer is active

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
- `GET /voice/status`
- `POST /voice/session/start`
- `POST /voice/session/stop`
- `POST /voice/tts/warmup`
- `POST /voice/transcribe_recent`
- `GET /voice/recent.wav`
- `GET /expression/state`
- `GET /expression/frame.svg`
- `POST /expression/select`
- `POST /signal`
- `POST /care/manual`
- `POST /speak`
- `POST /pan_tilt`
- `GET /summary`

## Backend API additions

- `GET /activate`
- `GET /api/activation/state`
- `POST /api/activation/complete`
- `POST /api/activation/identity/infer`
- `GET /api/activation/prompt-pack`
- `POST /api/activation/assessment/start`
- `GET /api/activation/assessment/state`
- `POST /api/activation/assessment/turn`
- `POST /api/activation/assessment/finish`
- `POST /api/activation/assessment/voice/start`
- `POST /api/activation/assessment/voice/stop`
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
- First-time user activation is now native-client-led: after login, the desktop app first confirms identity, then runs a multi-turn 8-dimension assessment, and only after that unlocks owner face enrollment.

## Native assessment flow

- Login does not immediately enter ordinary chat.
- Step 1: confirm identity and relation to the robot.
- Step 2: run a conversational 8-dimension psychometric assessment until confidence is high enough or the hard cap is reached.
- Step 3: write the final type, scores and interaction preferences to backend storage and OpenClaw memory.
- Step 4: only after those two steps may the app start owner face enrollment.

The desktop app now uses the backend assessment APIs directly. It no longer falls back to the old fixed 4-question profile flow.

## Pi local voice stack

- TTS default path is now local-first:
  - preferred: Piper CLI + local ONNX voice
  - fallback: `pyttsx3` for dev and compatibility
- ASR default path is now local-first:
  - preferred: `sherpa-onnx`
  - fallback: bundled `vosk` small Chinese model
- The previous cloud TTS / realtime ASR path is no longer the default runtime contract for Pi deployment.

## Pi local expression surface

- The original ESP parametric eye-expression catalog has now been migrated into `pi_runtime/expression_catalog.json`.
- The Pi runtime renders those expressions locally through `pi_runtime/expression_surface.py`.
- Local surface endpoints:
  - `GET /expression/state`
  - `GET /expression/frame.svg`
  - `POST /expression/select`
- The default Pi display driver is currently `web`, which means the migrated expression system renders through the Pi-local UI surface at `/ui`.
- If you later connect a physical SPI/DSI/HDMI screen, keep the same expression engine and only swap the final display backend.

## Hardware bring-up

- Wiring and power guide: `docs/pi_hardware_wiring.md`
- Migration summary: `docs/raspberry_pi_zero2w_migration.md`
- Engine design: `docs/engine_design.md`
- OpenClaw software integration: `docs/openclaw_integration.md`
- Activation and identity prompting: `docs/activation_identity.md`

## Notes

- The default install now prefers a headless config so the service can boot cleanly before hardware is attached.
- `pi_runtime` degrades cleanly when camera, servo or TTS dependencies are partially unavailable.
- API keys are no longer stored in tracked config files. Provide them through `/etc/default/emotion-pi`.
- Remote backend users can bootstrap a fresh login database with `python scripts/bootstrap_server_backend.py`.
- If you want to ship a ready-to-demo repo, use `DEMO_USER_EMAIL` and `DEMO_USER_PASSWORD` in `server_backend/.env`, then run `python scripts/bootstrap_server_backend.py --create-demo-user`.
- This adaptation is a userland migration. It does not require reflashing or reinstalling Raspberry Pi OS.
