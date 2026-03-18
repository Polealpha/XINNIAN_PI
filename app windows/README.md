# Windows 前端（EmoResonance）

本目录是 Windows 端控制台 UI（Vite + React + TS），用于展示情绪引擎实时状态、事件日志、设备状态与主动关怀聊天。

## 运行方式

1. 安装依赖
   ```bash
   npm install
   ```
2. 配置后端地址
   - 修改 `.env.local` 的 `VITE_API_BASE`（默认 `http://localhost:8000`）。
3. 启动开发服务器
   ```bash
   npm run dev
   ```
   默认端口 `3001`。

## 依赖后端

请先启动后端（`backend`）并确保以下接口可用：

- `POST /api/auth/login`
- `POST /api/auth/register`
- `GET /api/emotion/history`
- `GET /api/emotion/realtime`
- `GET /api/device/status`
- `GET /api/chat/history`
- `POST /api/chat/history`
- `POST /api/llm/care`
- `POST /api/llm/daily_summary`
- WebSocket `ws://<host>:8000/ws/events`

## 设备流接入（可选）

如果需要让引擎接入 ESP32-S3 的视频/音频流并推送事件：

```bash
py scripts/bridge_device_to_backend.py --device-ip <ESP_IP> --backend-url http://localhost:8000
```
