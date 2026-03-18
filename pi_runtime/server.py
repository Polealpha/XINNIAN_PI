from __future__ import annotations

import argparse
import logging
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Response
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
