from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import tempfile
import wave
from typing import Optional

from ..core.config import AsrConfig


class AsrModule:
    def __init__(self, config: AsrConfig) -> None:
        self.config = config
        self._vosk_model = None
        self._vosk_ready = False
        self._whisper_model = None
        self._whisper_ready = False
        self._whisper_error: Optional[str] = None
        self._dashscope_ready = False
        self._dashscope_error: Optional[str] = None
        self._dashscope_recognition = None
        self._dashscope_callback = None
        self._dashscope_api_key: Optional[str] = None
        if self.config.enabled:
            if self.config.engine == "vosk":
                self._init_vosk()
            elif self.config.engine in ("whisper", "faster_whisper"):
                self._init_whisper()
            elif self.config.engine in ("dashscope", "dashscope_realtime", "aliyun"):
                self._init_dashscope()

    @property
    def ready(self) -> bool:
        if not self.config.enabled:
            return False
        engine = str(self.config.engine or "").strip().lower()
        if engine == "vosk":
            return bool(self._vosk_ready)
        if engine in {"whisper", "faster_whisper"}:
            return bool(self._whisper_ready)
        if engine in {"dashscope", "dashscope_realtime", "aliyun"}:
            return bool(self._dashscope_ready)
        return False

    @property
    def error(self) -> Optional[str]:
        if self._dashscope_error:
            return self._dashscope_error
        if self._whisper_error:
            return self._whisper_error
        return None

    def transcribe(self, pcm_s16le: bytes, sample_rate: int) -> str:
        if not self.config.enabled:
            return ""
        if self.config.engine == "vosk":
            return self._transcribe_vosk(pcm_s16le, sample_rate)
        if self.config.engine in ("whisper", "faster_whisper"):
            return self._transcribe_whisper(pcm_s16le, sample_rate)
        if self.config.engine in ("dashscope", "dashscope_realtime", "aliyun"):
            text = self._transcribe_dashscope(pcm_s16le, sample_rate)
            if text:
                return text
        return ""

    def _init_vosk(self) -> None:
        try:
            from vosk import Model  # type: ignore
        except Exception:
            self._vosk_ready = False
            return
        if not self.config.model_path:
            self._vosk_ready = False
            return
        model_path = Path(self.config.model_path)
        if not model_path.is_absolute():
            repo_root = Path(__file__).resolve().parents[2]
            model_path = (repo_root / model_path).resolve()
        if not model_path.exists():
            self._vosk_ready = False
            return
        if not (model_path / "am").exists() and not (model_path / "conf").exists():
            self._vosk_ready = False
            return
        try:
            if not str(model_path).isascii():
                short_path = self._to_short_path(model_path)
                if short_path and short_path.exists():
                    model_path = short_path
            self._vosk_model = Model(str(model_path))
            self._vosk_ready = True
        except Exception:
            self._vosk_ready = False

    def _init_whisper(self) -> None:
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except Exception as exc:
            self._whisper_error = str(exc)
            self._whisper_ready = False
            return
        model_id = self._resolve_whisper_model_id()
        if not model_id:
            self._whisper_ready = False
            return
        try:
            self._whisper_model = WhisperModel(
                model_id,
                device=self.config.device,
                compute_type=self.config.compute_type,
            )
            self._whisper_ready = True
        except Exception as exc:
            self._whisper_error = str(exc)
            self._whisper_ready = False

    def _resolve_whisper_model_id(self) -> str:
        if self.config.model_path:
            model_path = Path(self.config.model_path)
            if not model_path.is_absolute():
                repo_root = Path(__file__).resolve().parents[2]
                model_path = (repo_root / model_path).resolve()
            return str(model_path)
        return self.config.model_name or "small"

    def _transcribe_vosk(self, pcm_s16le: bytes, sample_rate: int) -> str:
        if not self._vosk_ready:
            return ""
        try:
            from vosk import KaldiRecognizer  # type: ignore
        except Exception:
            return ""

        pcm = self._trim_audio(pcm_s16le, sample_rate)
        recognizer = KaldiRecognizer(self._vosk_model, sample_rate)
        recognizer.SetWords(False)
        recognizer.AcceptWaveform(pcm)
        result = recognizer.FinalResult()
        try:
            data = json.loads(result)
            return str(data.get("text", ""))
        except json.JSONDecodeError:
            return ""

    def _transcribe_whisper(self, pcm_s16le: bytes, sample_rate: int) -> str:
        if not self._whisper_ready:
            return ""
        try:
            import numpy as np  # type: ignore
        except Exception:
            return ""

        pcm = self._trim_audio(pcm_s16le, sample_rate)
        if not pcm:
            return ""
        if sample_rate != 16000:
            return ""

        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = self._whisper_model.transcribe(
            samples,
            language=self.config.language,
            beam_size=self.config.beam_size,
            vad_filter=self.config.vad_filter,
            condition_on_previous_text=False,
        )
        texts = []
        for segment in segments:
            text = segment.text.strip()
            if text:
                texts.append(text)
        return " ".join(texts).strip()

    def _init_dashscope(self) -> None:
        try:
            import dashscope  # type: ignore
            from dashscope.audio.asr import Recognition  # type: ignore
            from dashscope.audio.asr.recognition import RecognitionCallback  # type: ignore
        except Exception as exc:
            self._dashscope_error = str(exc)
            self._dashscope_ready = False
            return
        api_key = self.config.api_key or os.environ.get(self.config.api_key_env)
        if not api_key:
            self._dashscope_error = "missing_api_key"
            self._dashscope_ready = False
            return
        try:
            dashscope.api_key = api_key
            # Optional endpoint override for private/region routing.
            if self.config.base_websocket_api_url:
                dashscope.base_websocket_api_url = self.config.base_websocket_api_url
            if not hasattr(Recognition, "_running"):
                setattr(Recognition, "_running", False)
        except Exception as exc:
            self._dashscope_error = str(exc)
            self._dashscope_ready = False
            return
        self._dashscope_recognition = Recognition
        try:
            class _NoopRecognitionCallback(RecognitionCallback):  # type: ignore[misc,valid-type]
                def on_open(self) -> None:
                    return
                def on_close(self) -> None:
                    return
                def on_complete(self) -> None:
                    return
                def on_error(self, result) -> None:
                    _ = result
                    return
                def on_event(self, result) -> None:
                    _ = result
                    return
            self._dashscope_callback = _NoopRecognitionCallback()
        except Exception:
            self._dashscope_callback = None
        self._dashscope_api_key = api_key
        self._dashscope_ready = True

    def _transcribe_dashscope(self, pcm_s16le: bytes, sample_rate: int) -> str:
        if not self._dashscope_ready or self._dashscope_recognition is None:
            return ""
        pcm = self._trim_audio(pcm_s16le, sample_rate)
        if not pcm:
            return ""
        if sample_rate != 16000:
            return ""
        wav_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(prefix="xinnian_asr_", suffix=".wav", delete=False) as tmp:
                wav_path = Path(tmp.name)
            with wave.open(str(wav_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(pcm)
            init_kwargs = dict(
                model=self.config.model or "paraformer-realtime-v2",
                format="wav",
                sample_rate=sample_rate,
                semantic_punctuation_enabled=bool(self.config.semantic_punctuation_enabled),
            )
            recognizer = None
            try:
                if self._dashscope_callback is not None:
                    recognizer = self._dashscope_recognition(
                        callback=self._dashscope_callback,
                        **init_kwargs,
                    )
            except TypeError:
                recognizer = None
            if recognizer is None:
                recognizer = self._dashscope_recognition(**init_kwargs)
            # Guard for SDK versions where __del__ assumes this member exists.
            if not hasattr(recognizer, "_running"):
                try:
                    setattr(recognizer, "_running", False)
                except Exception:
                    pass
            result = recognizer.call(str(wav_path))
            text = self._extract_dashscope_text(result)
            self._dashscope_error = None
            return text
        except Exception as exc:
            self._dashscope_error = str(exc)
            return ""
        finally:
            if wav_path is not None:
                try:
                    wav_path.unlink(missing_ok=True)
                except Exception:
                    pass

    def _extract_dashscope_text(self, result: object) -> str:
        # SDK objects vary across versions; parse defensively.
        if result is None:
            return ""
        for attr in ("text", "transcription", "sentence"):
            try:
                val = getattr(result, attr, None)
            except Exception:
                val = None
            if isinstance(val, str) and val.strip():
                return val.strip()
        try:
            getter = getattr(result, "get_sentence", None)
            if callable(getter):
                sentence = getter()
                if isinstance(sentence, str) and sentence.strip():
                    return sentence.strip()
                if isinstance(sentence, dict):
                    txt = sentence.get("text")
                    if isinstance(txt, str) and txt.strip():
                        return txt.strip()
        except Exception:
            pass
        try:
            to_dict = getattr(result, "to_dict", None)
        except Exception:
            to_dict = None
        if callable(to_dict):
            try:
                data = to_dict()
                parsed = self._extract_dashscope_text_from_dict(data)
                if parsed:
                    return parsed
            except Exception:
                pass
        if isinstance(result, dict):
            parsed = self._extract_dashscope_text_from_dict(result)
            if parsed:
                return parsed
        return ""

    def _extract_dashscope_text_from_dict(self, data: dict) -> str:
        if not isinstance(data, dict):
            return ""
        direct = data.get("text") or data.get("transcription") or data.get("sentence")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        output = data.get("output")
        if isinstance(output, dict):
            text = output.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
            sentence = output.get("sentence")
            if isinstance(sentence, str) and sentence.strip():
                return sentence.strip()
            if isinstance(sentence, list):
                parts = []
                for item in sentence:
                    if isinstance(item, dict):
                        t = item.get("text")
                        if isinstance(t, str) and t.strip():
                            parts.append(t.strip())
                if parts:
                    return "".join(parts)
            sentences = output.get("sentences")
            if isinstance(sentences, list):
                parts = []
                for item in sentences:
                    if isinstance(item, dict):
                        t = item.get("text")
                        if isinstance(t, str) and t.strip():
                            parts.append(t.strip())
                if parts:
                    return "".join(parts)
        return ""

    def _trim_audio(self, pcm_s16le: bytes, sample_rate: int) -> bytes:
        if self.config.max_sec <= 0:
            return pcm_s16le
        max_bytes = int(self.config.max_sec * sample_rate * 2)
        if max_bytes <= 0:
            return pcm_s16le
        if len(pcm_s16le) <= max_bytes:
            return pcm_s16le
        return pcm_s16le[-max_bytes:]

    def _to_short_path(self, path: Path) -> Optional[Path]:
        if os.name != "nt":
            return None
        try:
            get_short_path = ctypes.windll.kernel32.GetShortPathNameW
            get_short_path.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
            get_short_path.restype = wintypes.DWORD
            size = 260
            while True:
                buffer = ctypes.create_unicode_buffer(size)
                result = get_short_path(str(path), buffer, size)
                if result == 0:
                    return None
                if result < size:
                    return Path(buffer.value)
                size = result + 1
        except Exception:
            return None
