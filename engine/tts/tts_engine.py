from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import wave
from pathlib import Path
from typing import Optional, Tuple


class TtsEngine:
    """
    Local-only TTS helper.

    Preferred runtime:
    - Piper CLI / local ONNX voice for Raspberry Pi deployment
    Fallback:
    - pyttsx3 for workstation compatibility and headless testing
    """

    def __init__(self, voice: Optional[str] = None, rate: Optional[int] = None) -> None:
        self.voice = voice
        self.rate = rate
        self._engine = None
        self._ready_local = False
        self._ready_piper = False
        self._lock = threading.Lock()
        self.provider = str(os.getenv("TTS_PROVIDER", "piper")).strip().lower()
        self.piper_bin = str(os.getenv("TTS_PIPER_BIN", "piper")).strip() or "piper"
        self.piper_model = str(os.getenv("TTS_PIPER_MODEL", "")).strip()
        self.piper_config = str(os.getenv("TTS_PIPER_CONFIG", "")).strip()
        self._init_engine()

    @property
    def ready(self) -> bool:
        return bool(self._ready_piper or self._ready_local)

    def synthesize(self, text: str, target_rate: int = 16000) -> Optional[Tuple[bytes, int]]:
        if not self.ready:
            return None
        clean = str(text or "").strip()
        if not clean:
            return None
        if self.provider in {"piper", "auto"} and self._ready_piper:
            try:
                pcm, rate = self._synthesize_piper(clean, target_rate)
            except Exception:
                pcm, rate = b"", target_rate
            if pcm:
                return pcm, rate
            if self.provider == "piper":
                return None
        try:
            pcm, rate = self._synthesize_pyttsx3(clean)
        except Exception:
            return None
        if not pcm:
            return None
        if rate != target_rate:
            pcm, rate = self._resample(pcm, rate, target_rate)
        return pcm, rate

    def warmup(self, sample_text: str = "你好，我已经准备好了。", target_rate: int = 16000) -> bool:
        return bool(self.synthesize(sample_text, target_rate=target_rate))

    def _init_engine(self) -> None:
        self._ready_piper = self._can_use_piper()
        try:
            import pyttsx3  # type: ignore
        except Exception:
            self._ready_local = False
            return
        try:
            engine = pyttsx3.init()
            if self.rate is not None:
                engine.setProperty("rate", int(self.rate))
            if self.voice:
                engine.setProperty("voice", self.voice)
            self._engine = engine
            self._ready_local = True
        except Exception:
            self._ready_local = False

    def _can_use_piper(self) -> bool:
        if not self.piper_model:
            return False
        model_path = Path(self.piper_model).expanduser()
        if not model_path.is_absolute():
            repo_root = Path(__file__).resolve().parents[2]
            model_path = (repo_root / model_path).resolve()
        if not model_path.exists():
            return False
        return shutil.which(self.piper_bin) is not None

    def _synthesize_piper(self, text: str, target_rate: int) -> Tuple[bytes, int]:
        model_path = Path(self.piper_model).expanduser()
        if not model_path.is_absolute():
            repo_root = Path(__file__).resolve().parents[2]
            model_path = (repo_root / model_path).resolve()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_wav:
            wav_path = Path(tmp_wav.name)
        try:
            cmd = [self.piper_bin, "--model", str(model_path), "--output_file", str(wav_path)]
            if self.piper_config:
                cmd.extend(["--config", self.piper_config])
            subprocess.run(
                cmd,
                input=text.encode("utf-8"),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            pcm, rate = self._read_wav_pcm(wav_path)
            if pcm and rate != target_rate:
                pcm, rate = self._resample(pcm, rate, target_rate)
            return pcm, rate
        finally:
            try:
                wav_path.unlink(missing_ok=True)
            except Exception:
                pass

    def _synthesize_pyttsx3(self, text: str) -> Tuple[bytes, int]:
        if not self._engine or not self._ready_local:
            raise RuntimeError("pyttsx3 unavailable")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            wav_path = Path(tmp.name)
        try:
            with self._lock:
                self._engine.save_to_file(text, str(wav_path))
                self._engine.runAndWait()
            return self._read_wav_pcm(wav_path)
        finally:
            try:
                wav_path.unlink(missing_ok=True)
            except Exception:
                pass

    def _read_wav_pcm(self, wav_path: Path) -> Tuple[bytes, int]:
        try:
            with wave.open(str(wav_path), "rb") as wf:
                rate = int(wf.getframerate() or 16000)
                frames = wf.readframes(wf.getnframes())
                return frames or b"", rate
        except Exception:
            return b"", 16000

    def _resample(self, pcm: bytes, src_rate: int, dst_rate: int) -> Tuple[bytes, int]:
        if src_rate == dst_rate:
            return pcm, src_rate
        try:
            import numpy as np  # type: ignore
        except Exception:
            return pcm, src_rate
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
        if samples.size == 0:
            return pcm, src_rate
        duration = samples.size / float(src_rate)
        target_len = max(1, int(duration * dst_rate))
        x_old = np.linspace(0, duration, num=samples.size, endpoint=False)
        x_new = np.linspace(0, duration, num=target_len, endpoint=False)
        resampled = np.interp(x_new, x_old, samples).astype(np.int16)
        return resampled.tobytes(), dst_rate

