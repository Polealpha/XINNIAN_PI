# Auth Backend (FastAPI)

Minimal auth service for the Emotion Engine apps.

## Run (dev)
```
py -m venv .venv
.\.venv\Scripts\activate
py -m pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

## Endpoints
- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/refresh`
- `POST /auth/logout`
- `GET /auth/me`

## App API
- `POST /api/auth/login` (email + password)
- `POST /api/auth/register`
- `GET /api/auth/me`
- `GET /api/emotion/realtime`
- `POST /api/emotion/realtime`
- `GET /api/emotion/history`
- `POST /api/emotion/history`
- `POST /api/device/provision`
- `POST /api/device/provision/execute`
- `GET /api/device/list`
- `GET /api/device/status`
- `GET /api/chat/history`
- `POST /api/chat/history`
- `POST /api/llm/care`
- `POST /api/llm/daily_summary`
- `POST /api/engine/event`

## Realtime
- WebSocket: `ws://<host>:8000/ws/events`

## Notes
- Tokens are JWT (access + refresh).
- Refresh tokens are stored in SQLite (hashed) so logout can revoke.
- Change `AUTH_SECRET_KEY` in production.
- Raspberry Pi deployment disables legacy BLE / ESP provisioning by default.
- To re-enable the old provisioning path deliberately, set `DEVICE_PROVISIONING_ENABLED=1` and install any extra deps you still need, such as `bleak`.
