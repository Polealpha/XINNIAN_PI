# Emotion Engine API

This is a local in-process API used by the App/UI. It is not a network service.

## Lifecycle
- `engine.start(config: EngineConfig)`
- `engine.stop()`
- `engine.reset_session()`

## Stream Input
- `engine.push_audio(frame: AudioFrame)`
- `engine.push_video(frame: VideoFrame)`
- `engine.push_user_signal(signal: UserSignal)`

### UserSignal types
- `privacy_on` / `privacy_off`
- `do_not_disturb_on` / `do_not_disturb_off`
- `manual_care` (force a care response)
- `manual_mark` (user manual label / note)
- `daily_summary` (generate DailySummaryReady)
- `config_update` (runtime policy/config update)

## Status
- `engine.get_status() -> EngineStatus`

## Events
- `engine.on_event(callback(Event))`

## Event Types
- `RiskUpdate`
- `FaceTrackUpdate`
- `TriggerCandidate`
- `TriggerFired`
- `TranscriptReady`
- `CarePlanReady`
- `DailySummaryReady`
- `WakeState`
- `WakeWordDetected`
- `WakeAudioState`
- `WakeDiag`
- `VoiceChatUser`
- `VoiceChatBot`
- `ChatMessage`
- `Error`

## Data Structures

### AudioFrame
```
{
  "pcm_s16le": bytes,
  "sample_rate": 16000,
  "channels": 1,
  "timestamp_ms": int,
  "seq": int,
  "device_id": "aa:bb:cc:dd:ee:ff"
}
```

### VideoFrame
```
{
  "format": "jpeg",
  "data": bytes,
  "width": 320,
  "height": 240,
  "timestamp_ms": int,
  "seq": int,
  "device_id": "aa:bb:cc:dd:ee:ff"
}
```

### UserSignal
```
{
  "type": "privacy_on | privacy_off | do_not_disturb_on | do_not_disturb_off | manual_care | manual_mark | daily_summary | config_update",
  "timestamp_ms": int,
  "payload": {}
}
```

`config_update.payload` supports:
- `cooldown_min: number`
- `daily_trigger_limit: number`
- `care_delivery_strategy: "policy" | "voice_all_day" | "popup_all_day"`
- `audio_enabled` / `video_enabled` (bridge media control compatibility)
- `mic_enabled` / `camera_enabled` (alias fields)

LLM online search behavior:
- Controlled by `config/engine_config.json -> llm.web_search_*` (compat: `online_search_*`).
- Default routing is rules-first: local tools/API first, web search only for high-value complex queries.
- Daily quota is enforced by backend (`tool_usage_daily`), default `5` per user/day.
- News default uses free news API summary; only complex follow-up may escalate to web search.
- If web-search tool/model is unavailable, it transparently falls back to local/API/non-web reply.
- System tooling runs in allowlist-direct mode (`llm.system_tool_*`), only whitelisted apps/actions can execute.

### EngineStatus
```
{
  "mode": "normal | privacy | dnd",
  "V": 0.0,
  "A": 0.0,
  "T": 0.0,
  "S": 0.0,
  "cooldown_remaining_ms": 0,
  "daily_trigger_count": 0,
  "last_event_ts_ms": 0,
  "health": {"audio_ok": true, "video_ok": true, "esp_connected": true}
}
```

### CarePlan
```
{
  "text": "care text",
  "style": "warm | neutral | cheerful | serious",
  "motion": {"type": "nod", "intensity": 0.4, "duration_ms": 800},
  "emo": {"type": "soft", "level": 0.5},
  "followup_question": "",
  "reason": {"V": 0.7, "A": 0.6, "T": 0.5, "S": 0.72, "tags": ["fatigue"]},
  "policy": {
    "interrupt": true,
    "cooldown_ms": 900000,
    "content_source": "llm | template"
  }
}
```

## Event payloads (examples)

### RiskUpdate
```
{
  "V": 0.3,
  "A": 0.2,
  "T": 0.1,
  "S": 0.25,
  "mode": "normal",
  "detail": {
    "V_sub": {
      "fatigue": 0.22,
      "attention_drop": 0.31,
      "expression_class_id": 4,
      "expression_confidence": 0.81,
      "expression_risk": 0.88
    },
    "A_sub": {"rms": 24.1, "zcr": 0.08, "silence_sec": 1.2},
    "T_sub": {"tags": ["expr:anger"], "summary": "..." }
  }
}
```

`expression_class_id` label map (FER+):
- `0 neutral`
- `1 happiness`
- `2 surprise`
- `3 sadness`
- `4 anger`
- `5 disgust`
- `6 fear`
- `7 contempt`

### FaceTrackUpdate
```
{
  "found": true,
  "bbox": [x, y, w, h],
  "frame_w": 320,
  "frame_h": 240,
  "ex": 0.22,
  "ex_smooth": 0.18,
  "turn": 0.11,
  "lost": 0,
  "sent": true,
  "mode": "normal",
  "scene": "desk",
  "ts_ms": 1730000000000
}
```

`FaceTrackUpdate` is a runtime visualization signal (for camera overlay/UI feedback).
It is broadcast over WebSocket but should not be persisted into emotion history.

### TriggerCandidate
```
{"reason": "A_sustain", "V": 0.6, "A": 0.75}
```

### TriggerFired
```
{"reason": "V_sustain", "V": 0.72, "A": 0.55}
```

### TranscriptReady
```
{"transcript": "text", "start_ts": 1710000000000, "end_ts": 1710000060000}
```

### CarePlanReady
```
{
  "care_plan": CarePlan,
  "delivery_mode": "text | voice | both",
  "reason": {"V": 0.72, "A": 0.55, "T": 0.4, "S": 0.7, "tags": ["fatigue"]},
  "detail": {"V_sub": {}, "A_sub": {}, "T_sub": {}}
}
```

`care_plan.policy.content_source`:
- `llm`: content generated/rewritten by LLM (required for active care delivery in current strategy)
- `template`: local template/fallback content (not delivered as active care)

### WakeAudioState (common reasons)
`WakeAudioState.payload.reason` may include:
- `wake_listening` / `wake_meter` / `wake_partial`
- `wake_first_utterance_filtered` (first post-wake ASR text looked like wake word, ignored and continue listening)
- `wake_first_utterance_empty_retry` (first post-wake capture returned empty ASR, session reopened automatically)
- `voice_session_auto_exit_silence` (no speech for a timeout window, voice session auto-exited)
- `llm_timeout` (dialogue LLM timed out; short fallback reply used)
- `llm_rate_limit` (dialogue LLM rate-limited; short fallback reply used)
- `llm_empty` (dialogue LLM returned empty/invalid content; short fallback reply used)
- `voice_empty_retry_1/2/3` (ASR empty, auto-reopen listening and ask user to continue)
- `voice_empty_retry_exhausted` (ASR stayed empty after retries, session exited)
- `web_search_budget_exceeded` (daily web-search quota exhausted)
- `web_search_not_high_value` (query is not complex enough for web-search escalation)
- `web_search_tool_unavailable` (provider account/model has no web-search tool)
- `news_web_search_forced` / `high_value_news` (news query routed to web search)
- `news_fallback_used` (news answered via free news API path)
- `news_api_used` (news answered by free news API)
- `news_api_failed_fallback_web` (news API failed, auto-fallback to web search)
- `fx_api_used` / `stock_api_used` (financial answer served by standard API)
- `stock_api_limited` (stock API rate-limited; returned degraded/fallback reply)
- `system_tool_exec_ok` / `system_tool_exec_failed` (allowlisted system tool execution result)
- `function_call_sanitized` (tool-call JSON draft sanitized into final answer)
- `function_call_blocked_and_rewritten` (tool-call draft was blocked and rewritten before user delivery)
- `local_tool_music_start_ok/failed` (local music tool execution status)

### DailySummaryReady
```
{"summary": "...", "highlights": ["...", "...", "..."], "count": 3}
```

### ChatMessage
```
{
  "id": 123,
  "sender": "user | bot",
  "text": "message text (can be empty when attachments exist)",
  "content_type": "text | image | video | mixed | system",
  "attachments": [
    {"kind": "image | video", "url": "/uploads/chat/.../file.ext", "mime": "image/jpeg", "name": "file.jpg", "size": 12345}
  ],
  "timestamp_ms": 1730000000000
}
```

Chat media upload endpoint:
- `POST /api/chat/upload` (multipart, single `file`) -> returns attachment metadata for chat messages.
