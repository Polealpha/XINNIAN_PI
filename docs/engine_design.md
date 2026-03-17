# Emotion Engine Design (Pi-first)

## Core Ideas
- Always-on lightweight risk scoring: `V(t)` and `A(t)`.
- Trigger heavy work only when needed: short ASR + text risk after a sustained signal.
- LLM handles expression and care wording, not raw detection.
- Privacy default: no raw audio/video uploads.
- Pi Zero 2 W is the primary edge runtime, not a bridge MCU.

## Architecture
1. Raspberry Pi Zero 2 W runtime: capture, scoring, TTS and local actuation.
2. Optional backend: auth, chat history, dashboards and remote API.
3. Optional remote LLM / ASR providers: only when keys are configured.

## Engine API
- `start(config)` / `stop()` / `reset_session()`
- `push_audio(AudioFrame)` / `push_video(VideoFrame)` / `push_user_signal(UserSignal)`
- `get_status() -> EngineStatus`
- `on_event(callback)`

## Core Events
- `RiskUpdate`
- `TriggerCandidate`
- `TriggerFired`
- `TranscriptReady`
- `CarePlanReady`
- `DailySummaryReady`
- `Error`

## Trigger Logic (default)
- `V(t) > 0.7` sustained 90s
- `A(t) > 0.7` sustained 80s
- `V & A > 0.65` sustained 30s
- Peak trigger: 5min window, >=3 peaks (threshold 0.85, min gap 30s)
- Cooldown 15min, daily limit 5

## Design Constraints on Zero 2 W
- No heavy local FER stack by default.
- No mandatory local Whisper/Torch requirement.
- Missing camera, microphone, servo or PCA9685 must not crash the core runtime.
- Default deployment should be able to run in headless mode before hardware is connected.

## Config
- `config/engine_config.json` contains engine tunables.
- `config/pi_zero2w.headless.json` is the safest default for bring-up without external hardware.
- `config/pi_zero2w.json` enables the common local audio + camera path.
- `config/pi_zero2w.pca9685.example.json` is the reference for servo expansion via I2C.
