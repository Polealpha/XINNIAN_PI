from __future__ import annotations

import argparse
import logging
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, Field

from engine.core.types import UserSignal

from .runtime import PiEmotionRuntime

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(name)s: %(message)s")

runtime: Optional[PiEmotionRuntime] = None


class SignalRequest(BaseModel):
    type: str
    payload: dict = Field(default_factory=dict)


class SpeakRequest(BaseModel):
    text: str


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
        return runtime.get_status().__dict__

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

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Raspberry Pi Zero 2 W runtime server.")
    parser.add_argument("--config", default="config/pi_zero2w.json", help="Pi runtime config path")
    parser.add_argument("--engine-config", default="config/engine_config.json", help="Engine config path")
    args = parser.parse_args()

    temp_runtime = PiEmotionRuntime(args.config, args.engine_config)
    app = build_app(args.config, args.engine_config)
    uvicorn.run(app, host=temp_runtime.pi_config.service.host, port=temp_runtime.pi_config.service.port)


if __name__ == "__main__":
    main()
