# Emotion Companion for Raspberry Pi Zero 2 W

This repository is the Raspberry Pi Zero 2 W adaptation of the original "共感智能 / Emotion Engine" project. The active deployment target is now a single Pi-first runtime instead of the earlier multi-chip stack.

The current baseline is:

- `pi_runtime/`: on-device runtime for capture, risk scoring, care delivery, TTS playback and hardware control
- `engine/`: reusable emotion scoring, policy, LLM and summary modules retained from the original project
- `backend/`: optional FastAPI service for remote clients, chat history and device state
- `server_backend/`: deployment wrapper for the backend service
- `config/`: sanitized runtime configs with Pi-oriented defaults

## What Was Removed

The repo intentionally excludes the old Windows/Electron app, Android/Capacitor app, ESP32 firmware, STM32 firmware, APK artifacts and temporary build output. Those parts were specific to the previous deployment and are not part of the Pi Zero 2 W runtime.

Legacy BLE / ESP provisioning code may still exist in the backend for reference, but it is no longer enabled by default for Raspberry Pi deployment.

## Quick Start on Pi

1. Clone the repo onto the Raspberry Pi.
2. Review `config/pi_zero2w.json`.
3. Run `scripts/install_pi.sh`.
4. Start the on-device runtime:

```bash
source .venv/bin/activate
python -m pi_runtime.server --config config/pi_zero2w.json --engine-config config/engine_config.json
```

5. Optional remote API:

```bash
source .venv/bin/activate
python server_backend/run_server.py
```

## Default Runtime API

- `GET /healthz`
- `GET /status`
- `GET /risk`
- `GET /events?limit=50`
- `POST /signal`
- `POST /care/manual`
- `POST /speak`
- `GET /summary`

## Notes

- SSH on the target Pi still needs to be enabled separately if you want remote shell deployment.
- `pi_runtime` is designed to run even when camera, servo or TTS dependencies are partially unavailable. Missing hardware falls back to mock drivers instead of crashing the whole service.
- API keys are no longer stored in tracked config files. Provide them through environment variables such as `ARK_API_KEY` and `DASHSCOPE_API_KEY`.
- This adaptation is a userland migration. It does not require reflashing or reinstalling Raspberry Pi OS.
