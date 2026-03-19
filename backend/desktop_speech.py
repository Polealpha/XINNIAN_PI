from __future__ import annotations

import audioop
import io
import time
import threading
import wave
from typing import Any, Dict, Optional

from engine.core.config import AsrConfig
from engine.nlp.asr_module import AsrModule

from .settings import (
    DESKTOP_STT_BEAM_SIZE,
    DESKTOP_STT_COMPUTE_TYPE,
    DESKTOP_STT_DEVICE,
    DESKTOP_STT_FALLBACK_PROVIDER,
    DESKTOP_STT_LANGUAGE,
    DESKTOP_STT_MAX_SEC,
    DESKTOP_STT_MODEL_NAME,
    DESKTOP_STT_NUM_THREADS,
    DESKTOP_STT_PROVIDER,
    DESKTOP_STT_VAD_FILTER,
)


class DesktopSpeechService:
    def __init__(self) -> None:
        self._primary_asr: Optional[AsrModule] = None
        self._fallback_asr: Optional[AsrModule] = None
        self._primary_provider = str(DESKTOP_STT_PROVIDER or "auto").strip().lower()
        self._fallback_provider = str(DESKTOP_STT_FALLBACK_PROVIDER or "sherpa_onnx").strip().lower()
        self._initialized = False
        self._init_lock = threading.Lock()

    def _init_modules(self) -> None:
        primary = self._build_module(self._primary_provider)
        fallback = None
        if self._fallback_provider and self._fallback_provider != self._primary_provider:
            fallback = self._build_module(self._fallback_provider)
        self._primary_asr = primary
        self._fallback_asr = fallback
        self._initialized = True

    def _ensure_modules(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            self._init_modules()

    def _build_module(self, provider: str) -> Optional[AsrModule]:
        if provider in {"", "none", "disabled"}:
            return None
        if provider == "auto":
            provider = "faster_whisper"
        if provider in {"whisper", "faster_whisper"}:
            return AsrModule(
                AsrConfig(
                    enabled=True,
                    engine="faster_whisper",
                    language=DESKTOP_STT_LANGUAGE,
                    max_sec=DESKTOP_STT_MAX_SEC,
                    model_name=DESKTOP_STT_MODEL_NAME,
                    device=DESKTOP_STT_DEVICE,
                    compute_type=DESKTOP_STT_COMPUTE_TYPE,
                    beam_size=DESKTOP_STT_BEAM_SIZE,
                    vad_filter=DESKTOP_STT_VAD_FILTER,
                )
            )
        if provider in {"sherpa", "sherpa_onnx"}:
            return AsrModule(
                AsrConfig(
                    enabled=True,
                    engine="sherpa_onnx",
                    language="zh",
                    max_sec=DESKTOP_STT_MAX_SEC,
                    num_threads=DESKTOP_STT_NUM_THREADS,
                )
            )
        if provider == "vosk":
            return AsrModule(
                AsrConfig(
                    enabled=True,
                    engine="vosk",
                    language="zh",
                    max_sec=DESKTOP_STT_MAX_SEC,
                )
            )
        return None

    def status(self) -> Dict[str, Any]:
        if not self._initialized:
            return {
                "ok": True,
                "ready": False,
                "provider_preference": self._primary_provider,
                "fallback_provider": self._fallback_provider,
                "active_provider": self._primary_provider or "disabled",
                "primary_ready": False,
                "primary_engine": self._primary_provider or "disabled",
                "primary_error": None,
                "fallback_ready": False,
                "fallback_engine": self._fallback_provider or "disabled",
                "fallback_error": None,
                "language": DESKTOP_STT_LANGUAGE,
                "max_sec": DESKTOP_STT_MAX_SEC,
                "model_name": DESKTOP_STT_MODEL_NAME,
            }
        primary = self._primary_asr
        fallback = self._fallback_asr
        ready = bool(primary and primary.ready) or bool(fallback and fallback.ready)
        return {
            "ok": True,
            "ready": ready,
            "provider_preference": self._primary_provider,
            "fallback_provider": self._fallback_provider,
            "active_provider": self._resolve_active_provider(),
            "primary_ready": bool(primary and primary.ready),
            "primary_engine": primary.active_engine if primary else "disabled",
            "primary_error": primary.error if primary else None,
            "fallback_ready": bool(fallback and fallback.ready),
            "fallback_engine": fallback.active_engine if fallback else "disabled",
            "fallback_error": fallback.error if fallback else None,
            "language": DESKTOP_STT_LANGUAGE,
            "max_sec": DESKTOP_STT_MAX_SEC,
            "model_name": DESKTOP_STT_MODEL_NAME,
        }

    def transcribe_upload(
        self,
        *,
        audio_bytes: bytes,
        filename: str = "",
        content_type: str = "",
        context: str = "chat",
    ) -> Dict[str, Any]:
        self._ensure_modules()
        started = time.perf_counter()
        pcm, sample_rate, duration_ms = self._decode_audio(audio_bytes, filename=filename, content_type=content_type)
        if not pcm:
            raise ValueError("empty_audio")
        provider = self._resolve_active_provider()
        transcript = ""
        used_fallback = False
        primary = self._primary_asr
        fallback = self._fallback_asr

        if primary and primary.ready:
            transcript = self._normalize_text(primary.transcribe(pcm, sample_rate))
            provider = primary.active_engine
        if not transcript and fallback and fallback.ready:
            transcript = self._normalize_text(fallback.transcribe(pcm, sample_rate))
            provider = fallback.active_engine
            used_fallback = True
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {
            "ok": bool(transcript),
            "transcript": transcript,
            "provider": provider,
            "used_fallback": used_fallback,
            "duration_ms": duration_ms,
            "latency_ms": latency_ms,
            "context": str(context or "chat"),
            "ready": bool(transcript) or self.status()["ready"],
        }

    def _resolve_active_provider(self) -> str:
        if self._primary_asr and self._primary_asr.ready:
            return self._primary_asr.active_engine
        if self._fallback_asr and self._fallback_asr.ready:
            return self._fallback_asr.active_engine
        if self._primary_asr:
            return self._primary_asr.active_engine
        if self._fallback_asr:
            return self._fallback_asr.active_engine
        return "disabled"

    def _decode_audio(self, audio_bytes: bytes, *, filename: str, content_type: str) -> tuple[bytes, int, int]:
        if not audio_bytes:
            return b"", 16000, 0
        lower_name = str(filename or "").lower()
        lower_type = str(content_type or "").lower()
        if lower_name.endswith(".wav") or "wav" in lower_type or audio_bytes[:4] == b"RIFF":
            return self._decode_wav(audio_bytes)
        raise ValueError("unsupported_audio_format")

    def _decode_wav(self, audio_bytes: bytes) -> tuple[bytes, int, int]:
        with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
            channels = int(wav_file.getnchannels() or 1)
            sample_width = int(wav_file.getsampwidth() or 2)
            sample_rate = int(wav_file.getframerate() or 16000)
            frame_count = int(wav_file.getnframes() or 0)
            pcm = wav_file.readframes(frame_count)

        if sample_width == 1:
            pcm = audioop.bias(pcm, 1, -128)
            pcm = audioop.lin2lin(pcm, 1, 2)
        elif sample_width == 2:
            pcm = pcm
        elif sample_width == 4:
            pcm = audioop.lin2lin(pcm, 4, 2)
        else:
            raise ValueError("unsupported_sample_width")

        if channels > 1:
            pcm = audioop.tomono(pcm, 2, 0.5, 0.5)
        if sample_rate != 16000:
            pcm, _state = audioop.ratecv(pcm, 2, 1, sample_rate, 16000, None)
            sample_rate = 16000

        max_frames = max(1, int(DESKTOP_STT_MAX_SEC) * sample_rate)
        max_bytes = max_frames * 2
        if len(pcm) > max_bytes:
            pcm = pcm[:max_bytes]

        duration_ms = int((len(pcm) / 2) / max(1, sample_rate) * 1000)
        return pcm, sample_rate, duration_ms

    def _normalize_text(self, text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        return " ".join(raw.split())
