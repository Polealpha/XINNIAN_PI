# OpenClaw Integration

## Current architecture

- `OpenClaw` is now the only conversational runtime for desktop, mobile contract, and WeCom bridge traffic.
- `backend` is the product-facing API and orchestration layer.
- `pi_runtime` stays the robot-side execution layer.
- Robot actions never go directly from OpenClaw to Pi. They go through `backend`, which calls the Pi HTTP runtime.

## Why the previous OpenClaw felt "dumb"

The earlier WeCom bridge had three structural problems:

1. It was not a thin bridge. It silently fell back from `OpenClaw` to `codex_cli`, then to `OpenAI`, then to a local echo fallback.
2. It forced all WeCom messages into a single fixed session key, `agent:main:wecom`, so unrelated contacts shared one conversation context.
3. It used a stale `OPENCLAW_STATE_DIR` and a very short `OPENCLAW_TIMEOUT_MS=3000`, so `chat.send` often never reached `final` before timing out.

That combination caused persona drift, memory drift, tool drift, and mixed chat histories.

## What changed

### Backend

- Added `POST /api/assistant/send` as the main assistant entry.
- Added `POST /api/assistant/bridge/send` for trusted local bridges such as WeCom.
- Added first-login activation endpoints and a minimal activation page:
  - `GET /activate`
  - `GET /api/activation/state`
  - `POST /api/activation/identity/infer`
  - `POST /api/activation/complete`
  - `GET /api/activation/prompt-pack`
- Added session-aware chat mirroring via `surface` and `session_key`.
- Added workspace-backed todos and searchable memory under the OpenClaw workspace.
- Added explicit desktop and robot actions:
  - desktop: launch allowlisted apps, open URLs, write notes, create todos
  - robot: get status, speak, pan/tilt, owner enrollment, preview URL

### Pi runtime

- Added `POST /pan_tilt` for explicit dual-axis head control.
- Existing `GET /status`, `POST /speak`, `GET /camera/preview.jpg`, and owner enrollment endpoints remain compatible.

### WeCom bridge

- The formal reply chain is now `WeCom -> backend assistant -> OpenClaw`.
- `codex_cli`, `OpenAI`, and local echo are no longer part of the production reply path.
- Session routing is per contact through `sender_id`, which becomes `wecom:<sender_id>`.

## Session strategy

- Desktop: `desktop:<user_id>`
- Mobile: `mobile:<user_id>`
- WeCom: `wecom:<sender_id>`
- Robot: `robot:<device_id>`
- Activation inference: `activation:<user_id>:infer:<timestamp>`

The backend mirrors recent messages for UI use, but OpenClaw remains the live conversation engine.

## Activation and identity strategy

- First login no longer drops directly into unconstrained chat.
- The system now asks the user to confirm a durable identity card before treating onboarding facts as long-term memory.
- Voice or transcript-based identity inference uses a dedicated strict-JSON extraction prompt, separate from the user's normal chat session.
- The activation profile is persisted in backend storage and mirrored into the OpenClaw workspace memory so later conversations can recall it without mixing it into unrelated session histories.

## Preferred runtime defaults

- Preferred operating mode: `cli`
- Preferred high-tier model hint: `gpt-5.4`

This is a product-side preference used by prompts and activation flows. The actual OpenClaw runtime model is still controlled by OpenClaw's provider/model configuration and auth state.

## Memory and todos

Todos and assistant notes are stored in the OpenClaw workspace under:

- `.openclaw-workspace/assistant_data/users/<user_id>/todos.json`
- `.openclaw-workspace/assistant_data/users/<user_id>/memory.md`
- `.openclaw-workspace/assistant_data/users/<user_id>/notes/*.md`

This keeps the structured data in the same workspace OpenClaw can search and reason over.

## Desktop control policy

Desktop control is explicit and allowlisted. It is not built on unrestricted UI automation.

Current actions:

- open allowlisted applications
- open web URLs
- create notes
- create and update todos

If broader Windows automation is needed later, add it as an explicit adapter instead of re-enabling arbitrary exec by default.

## Required bridge environment

For `openclaw/.openclaw-workspace/wechat_embed/.env.wecom`:

- `ASSISTANT_BACKEND_URL=http://127.0.0.1:8000`
- `ASSISTANT_BRIDGE_TOKEN=<same value as backend ASSISTANT_BRIDGE_TOKEN>`
- `ASSISTANT_TIMEOUT_MS=45000`
- `CODEX_CLI_ENABLED=false`
- `OPENAI_FALLBACK_WHEN_NO_KEY=false`

For backend environment:

- `ASSISTANT_BRIDGE_TOKEN=<shared secret>`
- `ASSISTANT_BRIDGE_USER_ID=<trusted local user id>`
- optional `OPENCLAW_STATE_DIR=<actual OpenClaw runtime state dir>`

## Current limitations

- The repository still does not contain the final desktop/mobile UI source code, so the desktop/mobile part is delivered as backend API contract.
- The backend can trigger explicit robot and desktop actions, but OpenClaw-native tool registration inside its own source tree was not reworked in this pass.
- If the OpenClaw runtime state directory is missing, backend assistant endpoints will return an explicit availability error instead of silently falling back.
