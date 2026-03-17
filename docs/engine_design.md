# Emotion Engine Design (MVP)

## Core Ideas
- Always-on lightweight risk scoring: V(t) and A(t).
- Triggered heavy work only: short ASR + text risk when risk persists.
- LLM only handles expression (optional); never responsible for detection.
- Privacy default: no raw audio/video uploads.
- Interface-first: UI/Robot integrate only through Engine API.

## Architecture
1. ESP32 Runtime: capture + actuation (audio/video/commands).
2. Emotion Engine (local): risk, trigger, care plan.
3. App/UI (Windows/Android): visualization + robot control.

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
- V(t) > 0.7 sustained 90s
- A(t) > 0.7 sustained 80s
- V & A > 0.65 sustained 30s
- Peak trigger: 5min window, >=3 peaks (threshold 0.85, min gap 30s)
- Cooldown 15min, daily limit 5

## Care Policy (MVP)
- L1 (0.70-0.80): gentle confirmation + one question
- L2 (0.80-0.90): add small action (breath/water)
- L3 (>0.90): stronger support, no diagnosis

## Config
- `config/engine_config.json` contains all tunables.
- Extra smoothing controls:
  - `video.face_missing_grace_sec`
  - `video.face_missing_decay_sec`
  - `trigger.a_decay_sec`
- LLM defaults use Baidu AI Studio OpenAI-compatible API.
- Set `AI_STUDIO_API_KEY` (or `llm.api_key`) and `llm.base_url` as needed.
- ASR supports Vosk and Whisper (faster-whisper).
- Whisper uses `asr.model_name`/`asr.model_path` with `device` + `compute_type`.

## Directory Layout
See `docs/engine_design.md` + `protocol/engine_api.md`.
