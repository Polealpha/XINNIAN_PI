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


def _ui_shell_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Emotion Pi Surface</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #07111f;
      --panel: rgba(9, 17, 31, 0.85);
      --panel-strong: rgba(7, 12, 24, 0.92);
      --line: rgba(255, 255, 255, 0.08);
      --text: #e6eefb;
      --muted: #8fa2c1;
      --accent: #67e8f9;
      --accent-soft: rgba(103, 232, 249, 0.14);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
      background:
        radial-gradient(circle at top, rgba(34, 211, 238, 0.16), transparent 32%),
        radial-gradient(circle at bottom right, rgba(14, 165, 233, 0.12), transparent 26%),
        linear-gradient(180deg, #07111f, #040913 72%);
      color: var(--text);
    }
    .screen { min-height: 100vh; display: none; align-items: center; justify-content: center; padding: 28px; }
    .screen.active { display: flex; }
    .card {
      width: min(1024px, 100%);
      border-radius: 32px;
      background: var(--panel);
      border: 1px solid var(--line);
      padding: 28px;
      box-shadow: 0 30px 120px rgba(0, 0, 0, 0.34);
      backdrop-filter: blur(24px);
    }
    .hero {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 28px;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      border-radius: 999px;
      padding: 10px 16px;
      background: var(--accent-soft);
      color: var(--accent);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.18em;
      text-transform: uppercase;
    }
    .face {
      width: 240px;
      height: 240px;
      border-radius: 36px;
      border: 1px solid var(--line);
      background: linear-gradient(180deg, rgba(103, 232, 249, 0.12), rgba(255, 255, 255, 0.03));
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 108px;
      line-height: 1;
    }
    .title { margin-top: 20px; font-size: 40px; font-weight: 900; letter-spacing: 0.04em; }
    .muted { color: var(--muted); font-size: 15px; line-height: 1.8; }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-top: 24px; }
    .item {
      background: rgba(255, 255, 255, 0.035);
      border-radius: 22px;
      padding: 16px 18px;
      border: 1px solid rgba(255, 255, 255, 0.05);
    }
    .label { color: var(--muted); font-size: 11px; font-weight: 800; letter-spacing: 0.22em; text-transform: uppercase; }
    .value { margin-top: 10px; font-size: 21px; font-weight: 800; }
    .settings-header { display: flex; align-items: center; justify-content: space-between; gap: 20px; }
    .pill {
      border-radius: 999px;
      padding: 8px 14px;
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.07);
      color: var(--text);
      font-size: 12px;
      font-weight: 700;
    }
    .footer-note {
      margin-top: 20px;
      padding: 16px 18px;
      border-radius: 20px;
      background: var(--panel-strong);
      border: 1px solid var(--line);
      color: var(--muted);
      font-size: 14px;
      line-height: 1.8;
    }
    pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-size: 12px;
      color: #d8e7ff;
      line-height: 1.7;
    }
    @media (max-width: 760px) {
      .hero { flex-direction: column; align-items: flex-start; }
      .face { width: 180px; height: 180px; font-size: 80px; }
      .title { font-size: 30px; }
      .grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div id="expression" class="screen active">
    <div class="card">
      <div class="hero">
        <div>
          <div class="badge">Emotion Pi</div>
          <div class="title">小念正在陪伴</div>
          <div id="expression-sub" class="muted" style="margin-top:14px;">等待设置指令、语音唤醒或桌面端联动。</div>
        </div>
        <div class="face">◕‿◕</div>
      </div>
      <div class="grid" id="expression-grid"></div>
    </div>
  </div>
  <div id="settings" class="screen">
    <div class="card">
      <div class="settings-header">
        <div>
          <div class="badge">Settings Surface</div>
          <div class="title" style="font-size:34px;">机器人设置已打开</div>
          <div id="settings-sub" class="muted" style="margin-top:10px;">等待电脑端同步详细设置。</div>
        </div>
        <div class="pill" id="settings-source">source: runtime</div>
      </div>
      <div class="grid" id="settings-grid"></div>
      <div class="footer-note">
        电脑端是主设置入口。你在电脑端保存后，这里会自动同步，并在关闭时回到表情页。
      </div>
      <div class="item" style="margin-top:14px;">
        <div class="label">完整设置 JSON</div>
        <pre id="settings-json">{}</pre>
      </div>
    </div>
  </div>
  <script>
    const expression = document.getElementById("expression");
    const settings = document.getElementById("settings");
    const exprSub = document.getElementById("expression-sub");
    const expressionGrid = document.getElementById("expression-grid");
    const settingsSub = document.getElementById("settings-sub");
    const settingsGrid = document.getElementById("settings-grid");
    const settingsJson = document.getElementById("settings-json");
    const settingsSource = document.getElementById("settings-source");

    function card(label, value) {
      return `<div class="item"><div class="label">${label}</div><div class="value">${value}</div></div>`;
    }

    function onOff(value) {
      return value ? "开启" : "关闭";
    }

    function render(state) {
      const ui = state.ui_state || {};
      const cfg = state.settings || {};
      const voice = state.voice_state || {};
      const page = ui.page || "expression";
      const source = ui.source || "runtime";

      expression.classList.toggle("active", page !== "settings");
      settings.classList.toggle("active", page === "settings");

      exprSub.textContent = `当前页面：${page} ｜ 来源：${source} ｜ 最后更新：${new Date().toLocaleTimeString()}`;
      expressionGrid.innerHTML =
        card("唤醒词", cfg.wake?.wake_phrase || "小念") +
        card("语音链", `${cfg.voice?.robot_tts_provider || "tts"} + ${cfg.voice?.desktop_stt_provider || "stt"}`) +
        card("音频采集", onOff(cfg.media?.audio_enabled)) +
        card("摄像头", onOff(cfg.media?.camera_enabled));

      settingsSub.textContent =
        `唤醒：${onOff(cfg.wake?.enabled)} ｜ 音频：${onOff(cfg.media?.audio_enabled)} ｜ 摄像头：${onOff(cfg.media?.camera_enabled)} ｜ 自动返回：${cfg.behavior?.settings_auto_return_sec || 0} 秒`;
      settingsSource.textContent = `source: ${source}`;
      settingsGrid.innerHTML =
        card("模式", cfg.mode || "normal") +
        card("主动关怀", cfg.care_delivery_strategy || "policy") +
        card("唤醒词", cfg.wake?.wake_phrase || "小念") +
        card("冷却时间", `${cfg.behavior?.cooldown_min || 30} 分钟`) +
        card("每日触发上限", `${cfg.behavior?.daily_trigger_limit || 5}`) +
        card("本地会话", voice.session_active ? (voice.mode || "active") : "idle");
      settingsJson.textContent = JSON.stringify(cfg, null, 2);
    }

    async function poll() {
      try {
        const resp = await fetch("/ui/state", { cache: "no-store" });
        const data = await resp.json();
        render(data);
      } catch (err) {
        console.error(err);
      }
    }

    poll();
    setInterval(poll, 1500);
  </script>
</body>
</html>"""


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
        return _ui_shell_html()

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
