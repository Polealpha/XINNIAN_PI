from __future__ import annotations

import argparse
import logging
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from engine.core.types import UserSignal

from .config import load_pi_config
from .runtime import PiEmotionRuntime

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(name)s: %(message)s")

runtime: Optional[PiEmotionRuntime] = None


class SignalRequest(BaseModel):
    type: str
    payload: dict = Field(default_factory=dict)


class SpeakRequest(BaseModel):
    text: str


class PanTiltRequest(BaseModel):
    pan: float = 0.0
    tilt: float = 0.0


class WifiRequest(BaseModel):
    ssid: str
    password: str = ""


class EnrollmentRequest(BaseModel):
    owner_label: str = "owner"
    claim_token: str = ""


class VoiceSessionRequest(BaseModel):
    mode: str = "assessment"


class TtsWarmupRequest(BaseModel):
    text: str = "你好，我已经准备好了。"


class VoiceTranscribeRequest(BaseModel):
    window_ms: int = 6000


class SettingsApplyRequest(BaseModel):
    settings: dict = Field(default_factory=dict)
    source: str = "local_ui"


class SettingsPageRequest(BaseModel):
    source: str = "desktop"


def build_app(pi_config_path: str, engine_config_path: str) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        global runtime
        runtime = PiEmotionRuntime(pi_config_path, engine_config_path)
        runtime.start()
        try:
            yield
        finally:
            if runtime is not None:
                runtime.stop()

    app = FastAPI(title="Emotion Pi Runtime", version="1.0.0", lifespan=lifespan)

    @app.get("/healthz")
    def healthz() -> dict:
        assert runtime is not None
        status = runtime.get_status()
        return {"ok": True, "mode": status.mode, "health": status.health}

    @app.get("/status")
    def status() -> dict:
        assert runtime is not None
        return runtime.get_status_payload()

    @app.get("/risk")
    def risk() -> dict:
        assert runtime is not None
        return runtime.get_risk_snapshot()

    @app.get("/events")
    def events(limit: int = 50) -> dict:
        assert runtime is not None
        return {"events": runtime.get_recent_events(limit)}

    @app.get("/summary")
    def summary() -> dict:
        assert runtime is not None
        return runtime.get_last_summary()

    @app.post("/signal")
    def signal(payload: SignalRequest) -> dict:
        assert runtime is not None
        runtime.handle_signal(
            UserSignal(
                type=payload.type,
                timestamp_ms=runtime._now_ms(),
                payload=payload.payload,
            )
        )
        return {"ok": True}

    @app.post("/care/manual")
    def manual_care(payload: SpeakRequest) -> dict:
        assert runtime is not None
        return runtime.manual_care(payload.text)

    @app.post("/speak")
    def speak(payload: SpeakRequest) -> dict:
        assert runtime is not None
        runtime.handle_signal(
            UserSignal(
                type="speak",
                timestamp_ms=runtime._now_ms(),
                payload={"text": payload.text},
            )
        )
        return {"ok": True}

    @app.post("/pan_tilt")
    def pan_tilt(payload: PanTiltRequest) -> dict:
        assert runtime is not None
        return runtime.set_manual_pan_tilt(payload.pan, payload.tilt)

    @app.get("/onboarding/state")
    def onboarding_state() -> dict:
        assert runtime is not None
        return runtime.get_onboarding_state()

    @app.get("/onboarding/networks")
    def onboarding_networks() -> dict:
        assert runtime is not None
        return {"networks": runtime.scan_networks()}

    @app.post("/onboarding/wifi")
    def onboarding_wifi(payload: WifiRequest) -> dict:
        assert runtime is not None
        try:
            return {"ok": True, "state": runtime.configure_wifi(payload.ssid, payload.password)}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/onboarding/reset")
    def onboarding_reset() -> dict:
        assert runtime is not None
        return {"ok": True, "state": runtime.reset_onboarding()}

    @app.get("/camera/preview.jpg")
    def preview() -> Response:
        assert runtime is not None
        content = runtime.get_preview_jpeg()
        if not content:
            raise HTTPException(status_code=503, detail="preview unavailable")
        return Response(content=content, media_type="image/jpeg")

    @app.get("/owner/status")
    def owner_status() -> dict:
        assert runtime is not None
        return runtime.get_owner_status()

    @app.post("/owner/enrollment/start")
    def owner_enrollment_start(payload: EnrollmentRequest) -> dict:
        assert runtime is not None
        try:
            return {"ok": True, "state": runtime.start_owner_enrollment(payload.owner_label, payload.claim_token)}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/owner/enrollment/reset")
    def owner_enrollment_reset() -> dict:
        assert runtime is not None
        try:
            return {"ok": True, "state": runtime.reset_owner_profile()}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/voice/status")
    def voice_status() -> dict:
        assert runtime is not None
        return runtime.get_voice_status()

    @app.post("/voice/session/start")
    def voice_session_start(payload: VoiceSessionRequest) -> dict:
        assert runtime is not None
        return {"ok": True, "state": runtime.start_voice_session(payload.mode)}

    @app.post("/voice/session/stop")
    def voice_session_stop(payload: VoiceSessionRequest) -> dict:
        assert runtime is not None
        return {"ok": True, "state": runtime.stop_voice_session(payload.mode)}

    @app.post("/voice/tts/warmup")
    def voice_tts_warmup(payload: TtsWarmupRequest) -> dict:
        assert runtime is not None
        return runtime.warmup_tts(payload.text)

    @app.post("/voice/transcribe_recent")
    def voice_transcribe_recent(payload: VoiceTranscribeRequest) -> dict:
        assert runtime is not None
        return runtime.transcribe_recent_audio(payload.window_ms)

    @app.get("/settings/live")
    def settings_live() -> dict:
        assert runtime is not None
        return {
            "ok": True,
            "device_id": runtime.pi_config.device.device_id,
            "settings": runtime.get_settings_state(),
            "ui_state": runtime.get_ui_state(),
        }

    @app.post("/settings/apply")
    def settings_apply(payload: SettingsApplyRequest) -> dict:
        assert runtime is not None
        settings = runtime.apply_settings(payload.settings, source=payload.source)
        return {"ok": True, "settings": settings, "ui_state": runtime.get_ui_state()}

    @app.post("/settings/open")
    def settings_open(payload: SettingsPageRequest) -> dict:
        assert runtime is not None
        return {"ok": True, "ui_state": runtime.open_settings_page(payload.source)}

    @app.post("/settings/close")
    def settings_close(payload: SettingsPageRequest) -> dict:
        assert runtime is not None
        return {"ok": True, "ui_state": runtime.close_settings_page(payload.source)}

    @app.get("/ui/state")
    def ui_state() -> dict:
        assert runtime is not None
        return {
            "ok": True,
            "device_id": runtime.pi_config.device.device_id,
            "ui_state": runtime.get_ui_state(),
            "settings": runtime.get_settings_state(),
            "voice_state": runtime.get_voice_status(),
        }

    @app.get("/ui", response_class=HTMLResponse)
    def ui_shell() -> str:
        return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Emotion Pi UI</title>
  <style>
    body { margin: 0; font-family: 'Microsoft YaHei', sans-serif; background: #080d18; color: #eef2ff; }
    .screen { min-height: 100vh; display: none; align-items: center; justify-content: center; padding: 32px; box-sizing: border-box; }
    .screen.active { display: flex; }
    .card { width: min(960px, 100%); border-radius: 28px; background: rgba(15, 23, 42, 0.82); border: 1px solid rgba(255,255,255,0.08); padding: 28px; box-shadow: 0 24px 80px rgba(0,0,0,0.25); }
    .expression-face { font-size: 120px; line-height: 1; text-align: center; }
    .muted { color: #94a3b8; font-size: 14px; }
    .grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; margin-top: 18px; }
    .item { background: rgba(255,255,255,0.04); border-radius: 18px; padding: 14px 16px; }
    .label { color: #a5b4fc; font-size: 12px; text-transform: uppercase; letter-spacing: .18em; }
    .value { margin-top: 8px; font-size: 20px; font-weight: 700; }
    pre { white-space: pre-wrap; word-break: break-word; font-size: 13px; color: #dbeafe; }
  </style>
</head>
<body>
  <div id="expression" class="screen active">
    <div class="card">
      <div class="expression-face">◕‿◕</div>
      <div style="text-align:center;font-size:32px;font-weight:700;">小念正在陪伴</div>
      <div id="expression-sub" class="muted" style="text-align:center;margin-top:10px;">等待设置或交互</div>
    </div>
  </div>
  <div id="settings" class="screen">
    <div class="card">
      <div style="font-size:28px;font-weight:800;">机器人设置</div>
      <div id="settings-sub" class="muted" style="margin-top:6px;">等待同步</div>
      <div class="grid" id="settings-grid"></div>
      <div class="item" style="margin-top:14px;">
        <div class="label">完整设置</div>
        <pre id="settings-json">{}</pre>
      </div>
    </div>
  </div>
  <script>
    const expression = document.getElementById('expression');
    const settings = document.getElementById('settings');
    const exprSub = document.getElementById('expression-sub');
    const settingsSub = document.getElementById('settings-sub');
    const settingsGrid = document.getElementById('settings-grid');
    const settingsJson = document.getElementById('settings-json');
    function card(label, value) {
      return `<div class="item"><div class="label">${label}</div><div class="value">${value}</div></div>`;
    }
    function render(state) {
      const ui = state.ui_state || {};
      const cfg = state.settings || {};
      const page = ui.page || 'expression';
      expression.classList.toggle('active', page !== 'settings');
      settings.classList.toggle('active', page === 'settings');
      exprSub.textContent = `当前页面：${page} ｜ 来源：${ui.source || 'runtime'}`;
      settingsSub.textContent = `来源：${ui.source || 'runtime'} ｜ 唤醒：${cfg.wake?.enabled ? '开' : '关'} ｜ 音频：${cfg.media?.audio_enabled ? '开' : '关'} ｜ 视频：${cfg.media?.camera_enabled ? '开' : '关'}`;
      settingsGrid.innerHTML =
        card('模式', cfg.mode || 'normal') +
        card('主动关怀', cfg.care_delivery_strategy || 'policy') +
        card('唤醒词', cfg.wake?.wake_phrase || '小念') +
        card('冷却', `${cfg.behavior?.cooldown_min || 30} 分钟`) +
        card('每日上限', `${cfg.behavior?.daily_trigger_limit || 5}`) +
        card('自动返回', `${cfg.behavior?.settings_auto_return_sec || 0} 秒`);
      settingsJson.textContent = JSON.stringify(cfg, null, 2);
    }
    async function poll() {
      try {
        const resp = await fetch('/ui/state', { cache: 'no-store' });
        const data = await resp.json();
        render(data);
      } catch (err) {}
    }
    poll();
    setInterval(poll, 1500);
  </script>
</body>
</html>"""

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Raspberry Pi Zero 2 W runtime server.")
    parser.add_argument("--config", default="config/pi_zero2w.json", help="Pi runtime config path")
    parser.add_argument("--engine-config", default="config/engine_config.json", help="Engine config path")
    args = parser.parse_args()

    app = build_app(args.config, args.engine_config)
    pi_config = load_pi_config(args.config)
    uvicorn.run(app, host=pi_config.service.host, port=pi_config.service.port)


if __name__ == "__main__":
    main()
