from __future__ import annotations

import asyncio
import os
import re
import tempfile
import threading
import wave
from pathlib import Path
from typing import Optional, Tuple


_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


class TtsEngine:
    """
    Local TTS helper for bridge playback.

    Notes for this project:
    - We still use pyttsx3 for compatibility.
    - On some Windows setups, Chinese text -> WAV may produce header-only files.
      We detect that and fallback to pinyin text for reliable non-empty PCM output.
    """

    def __init__(self, voice: Optional[str] = None, rate: Optional[int] = None) -> None:
        self.voice = voice
        self.rate = rate
        self._engine = None
        self._ready_local = False
        self._ready_edge = False
        self._lock = threading.Lock()
        self.provider = str(os.getenv("TTS_PROVIDER", "auto")).strip().lower()
        edge_voices_raw = str(
            os.getenv(
                "TTS_EDGE_VOICES",
                "zh-CN-XiaoxiaoNeural,en-US-AvaMultilingualNeural,en-US-EmmaMultilingualNeural",
            )
        ).strip()
        self.edge_voices = [v.strip() for v in edge_voices_raw.split(",") if v.strip()]
        if not self.edge_voices:
            self.edge_voices = ["en-US-AvaMultilingualNeural", "en-US-EmmaMultilingualNeural"]
        self._edge_voice_selected: Optional[str] = None
        self.edge_rate = str(os.getenv("TTS_EDGE_RATE", "-6%")).strip()
        self.edge_pitch = str(os.getenv("TTS_EDGE_PITCH", "+2Hz")).strip()
        self._init_engine()

    @property
    def ready(self) -> bool:
        return bool(self._ready_edge or self._ready_local)

    def synthesize(self, text: str, target_rate: int = 16000) -> Optional[Tuple[bytes, int]]:
        if not self.ready:
            return None
        clean = str(text or "").strip()
        if not clean:
            return None
        # Prefer neural voice first when enabled.
        if self.provider in {"auto", "edge"} and self._ready_edge:
            try:
                pcm, rate = self._synthesize_edge(clean, target_rate)
            except Exception:
                pcm, rate = b"", target_rate
            if pcm:
                return pcm, rate
            if self.provider == "edge":
                return None
        try:
            pcm, rate = self._synthesize_to_pcm(clean)
        except Exception:
            return None
        if not pcm:
            return None
        if rate != target_rate:
            pcm, rate = self._resample(pcm, rate, target_rate)
        return pcm, rate

    def _init_engine(self) -> None:
        # Edge neural TTS path
        if self.provider in {"auto", "edge"}:
            try:
                import edge_tts  # type: ignore  # noqa: F401
                import miniaudio  # type: ignore  # noqa: F401

                self._ready_edge = True
            except Exception:
                self._ready_edge = False

        try:
            import pyttsx3  # type: ignore
        except Exception:
            self._ready_local = False
            return
        try:
            engine = pyttsx3.init()
            if self.rate is not None:
                engine.setProperty("rate", int(self.rate))
            selected_voice = self.voice or self._pick_preferred_voice(engine)
            if selected_voice:
                engine.setProperty("voice", selected_voice)
            self._engine = engine
            self._ready_local = True
        except Exception:
            self._ready_local = False

    def _pick_preferred_voice(self, engine) -> Optional[str]:
        try:
            voices = engine.getProperty("voices") or []
        except Exception:
            voices = []
        if not voices:
            return None

        def score(v) -> int:
            text = " ".join(
                [
                    str(getattr(v, "id", "")),
                    str(getattr(v, "name", "")),
                    str(getattr(v, "gender", "")),
                    " ".join(str(x) for x in (getattr(v, "languages", []) or [])),
                ]
            ).lower()
            s = 0
            if any(k in text for k in ["female", "woman", "girl", "huihui", "xiaoxiao"]):
                s += 6
            if any(k in text for k in ["zh", "chinese", "mandarin", "cn", "804"]):
                s += 4
            if any(k in text for k in ["male", "man"]):
                s -= 2
            return s

        best = max(voices, key=score)
        return str(getattr(best, "id", "")) or None

    def _synthesize_to_pcm(self, text: str) -> Tuple[bytes, int]:
        pcm, rate = self._synthesize_once(text)
        if pcm:
            return pcm, rate

        # Fallback for Chinese text that becomes empty WAV on some pyttsx3 setups.
        if _CJK_RE.search(text):
            pinyin_text = self._to_pinyin(text)
            if pinyin_text and pinyin_text != text:
                pcm2, rate2 = self._synthesize_once(pinyin_text)
                if pcm2:
                    return pcm2, rate2
        return b"", rate

    def _synthesize_once(self, text: str) -> Tuple[bytes, int]:
        if not self._engine or not self._ready_local:
            raise RuntimeError("TTS engine not ready")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            wav_path = Path(tmp.name)
        try:
            with self._lock:
                self._engine.save_to_file(text, str(wav_path))
                self._engine.runAndWait()
            return self._read_wav_pcm(wav_path)
        finally:
            try:
                os.remove(wav_path)
            except Exception:
                pass

    def _read_wav_pcm(self, wav_path: Path) -> Tuple[bytes, int]:
        try:
            with wave.open(str(wav_path), "rb") as wf:
                rate = int(wf.getframerate() or 0)
                frames = wf.readframes(wf.getnframes())
                if rate <= 0:
                    rate = 16000
                return frames or b"", rate
        except Exception:
            return b"", 16000

    def _to_pinyin(self, text: str) -> str:
        try:
            from pypinyin import lazy_pinyin  # type: ignore

            syllables = lazy_pinyin(text, errors="ignore")
            out = " ".join(s for s in syllables if s).strip()
            return out or text
        except Exception:
            # Last fallback: keep ASCII part only.
            ascii_text = "".join(ch if ord(ch) < 128 else " " for ch in text)
            ascii_text = " ".join(ascii_text.split())
            return ascii_text or text

    def _synthesize_edge(self, text: str, target_rate: int) -> Tuple[bytes, int]:
        try:
            import edge_tts  # type: ignore
            import miniaudio  # type: ignore
        except Exception:
            return b"", target_rate

        async def _collect_audio(voice_name: str) -> bytes:
            communicate = edge_tts.Communicate(
                text,
                voice_name,
                rate=self.edge_rate,
                pitch=self.edge_pitch,
            )
            data = bytearray()
            async for msg in communicate.stream():
                if msg.get("type") == "audio":
                    data.extend(msg.get("data", b""))
            return bytes(data)

        voices_to_try = []
        if self._edge_voice_selected:
            voices_to_try.append(self._edge_voice_selected)
        for one in self.edge_voices:
            if one not in voices_to_try:
                voices_to_try.append(one)

        for voice_name in voices_to_try:
            try:
                try:
                    mp3_bytes = asyncio.run(_collect_audio(voice_name))
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    try:
                        mp3_bytes = loop.run_until_complete(_collect_audio(voice_name))
                    finally:
                        loop.close()
                if not mp3_bytes:
                    continue
                decoded = miniaudio.decode(
                    mp3_bytes,
                    output_format=miniaudio.SampleFormat.SIGNED16,
                    nchannels=1,
                    sample_rate=int(target_rate),
                )
                pcm = bytes(decoded.samples or b"")
                if not pcm:
                    continue
                self._edge_voice_selected = voice_name
                return pcm, int(decoded.sample_rate or target_rate)
            except Exception:
                continue
        return b"", target_rate

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
