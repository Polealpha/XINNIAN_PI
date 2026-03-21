# Server Backend (Remote Login Ready)

This folder provides a deployment-oriented launcher for the existing backend so web/mobile clients can log in remotely.

## What is included
- `run_server.py`: production-style launcher (loads env, sets persistent DB path, binds public host/port).
- `.env.example`: server env template.
- `start_server.ps1` / `start_server.sh`: convenience scripts.
- `requirements.txt`: installs backend dependencies.

## Quick start
1. Create virtualenv and install dependencies:
   - `python -m venv .venv`
   - `.\.venv\Scripts\activate` (Windows) or `source .venv/bin/activate` (Linux)
   - `pip install -r server_backend/requirements.txt`
2. Create env file:
   - `copy server_backend\\.env.example server_backend\\.env` (Windows)
   - `cp server_backend/.env.example server_backend/.env` (Linux)
3. Edit `server_backend/.env`:
   - set `AUTH_SECRET_KEY`
   - set `AUTH_CORS_ORIGINS` to your real client origins
4. Initialize database:
   - `python scripts/bootstrap_server_backend.py`
   - Optional demo account:
     - set `DEMO_USER_EMAIL` and `DEMO_USER_PASSWORD` in `server_backend/.env`
     - then run `python scripts/bootstrap_server_backend.py --create-demo-user`
5. Start server:
   - `python server_backend/run_server.py`
   - or `.\server_backend\start_server.ps1`

## Public endpoints
- Login: `POST /api/auth/login`
- Realtime events: `GET ws://<host>:8000/ws/events`
- Health/version: `GET /api/runtime/version`

## Client settings
If backend server public IP/domain is `https://api.example.com`:
- Mobile/Web `api_base` should be `https://api.example.com`
- WS base should be `wss://api.example.com`

## Notes
- Default DB path is `server_backend/data/auth.db` (created automatically).
- Do not commit real API keys, real JWT secrets, or your personal auth database to GitHub.
- If you want a fresh repo that others can use immediately, commit the bootstrap script and env template, not your personal `auth.db`.
- For HTTPS + domain deployment, place this app behind Nginx/Caddy and keep websocket upgrade enabled.
- Ensure firewall/security-group allows your server port (default `8000`) or proxy port (`443`).
