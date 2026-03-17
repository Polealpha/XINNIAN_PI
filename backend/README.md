# Auth Backend (FastAPI)

Minimal auth and remote API service for the Raspberry Pi deployment.

## Run (dev)
```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

## App API
- `POST /api/auth/login`
- `POST /api/auth/register`
- `GET /api/auth/me`
- `GET /api/emotion/realtime`
- `POST /api/emotion/realtime`
- `GET /api/emotion/history`
- `POST /api/emotion/history`
- `GET /api/device/list`
- `GET /api/device/status`
- `GET /api/chat/history`
- `POST /api/chat/history`
- `POST /api/chat/upload`
- `POST /api/llm/care`
- `POST /api/llm/care/stream`
- `POST /api/llm/daily_summary`
- `POST /api/engine/event`

## Realtime
- WebSocket: `ws://<host>:8000/ws/events`

## Notes
- Tokens are JWT (access + refresh).
- Refresh tokens are stored in SQLite (hashed) so logout can revoke.
- Change `AUTH_SECRET_KEY` in production.
- Legacy ESP BLE / SoftAP provisioning has been removed from the active Pi code path.
- The backend now loads its LLM stack lazily on first use, which reduces cold-start time on Zero 2 W.
