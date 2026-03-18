from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import tempfile
from typing import List, Optional, Tuple
import wave

from ..core.config import AsrConfig


class AsrModule:
    def __init__(self, config: AsrConfig) -> None:
        self.config = config
        self._sherpa_recognizer = None
        self._sherpa_ready = False
        self._sherpa_error: Optional[str] = None
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
            if self.config.engine in {"sherpa_onnx", "sherpa"}:
                self._init_sherpa_onnx()
            elif self.config.engine == "vosk":
                self._init_vosk()
            elif self.config.engine in ("whisper", "faster_whisper"):
                self._init_whisper()
            elif self.config.engine in ("dashscope", "dashscope_realtime", "aliyun"):
                self._init_dashscope()

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    @property
    def ready(self) -> bool:
        if not self.config.enabled:
            return False
        engine = str(self.config.engine or "").strip().lower()
        if engine in {"sherpa_onnx", "sherpa"}:
            return bool(self._sherpa_ready or self._vosk_ready)
        if engine == "vosk":
            return bool(self._vosk_ready)
        if engine in {"whisper", "faster_whisper"}:
            return bool(self._whisper_ready)
        if engine in {"dashscope", "dashscope_realtime", "aliyun"}:
            return bool(self._dashscope_ready)
        return False

    @property
    def error(self) -> Optional[str]:
        if self._sherpa_error and not self._vosk_ready:
            return self._sherpa_error
        if self._dashscope_error:
            return self._dashscope_error
        if self._whisper_error:
            return self._whisper_error
        return None

    @property
    def active_engine(self) -> str:
        if not self.config.enabled:
            return "disabled"
        engine = str(self.config.engine or "").strip().lower()
        if engine in {"sherpa_onnx", "sherpa"}:
            if self._sherpa_ready:
                return "sherpa_onnx"
            if self._vosk_ready:
                return "vosk_fallback"
            return "sherpa_unavailable"
        if engine == "vosk":
            return "vosk" if self._vosk_ready else "vosk_unavailable"
        if engine in {"whisper", "faster_whisper"}:
            return "faster_whisper" if self._whisper_ready else "faster_whisper_unavailable"
        if engine in {"dashscope", "dashscope_realtime", "aliyun"}:
            return "dashscope" if self._dashscope_ready else "dashscope_unavailable"
        return engine or "unknown"

    def transcribe(self, pcm_s16le: bytes, sample_rate: int) -> str:
        if not self.config.enabled:
            return ""
        if self.config.engine in {"sherpa_onnx", "sherpa"}:
            text = self._transcribe_sherpa_onnx(pcm_s16le, sample_rate)
            if text:
                return text
            if self._vosk_ready:
                return self._transcribe_vosk(pcm_s16le, sample_rate)
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

    def _resolve_path(self, value: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        path = Path(raw)
        if not path.is_absolute():
            path = (self._repo_root() / path).resolve()
        return str(path)

    def _resolve_existing_path(self, value: str) -> str:
        resolved = self._resolve_path(value)
        if resolved and Path(resolved).exists():
            return resolved
        return ""

    def _discover_sherpa_assets(self) -> Tuple[str, str, str, str]:
        repo_root = self._repo_root()
        search_roots: List[Path] = [
            repo_root / "models" / "asr" / "sherpa",
            repo_root / "models" / "asr",
        ]
        for root in search_roots:
            if not root.exists():
                continue
            for tokens_path in root.rglob("tokens.txt"):
                model_dir = tokens_path.parent
                paraformer_candidates = sorted(model_dir.glob("model*.onnx"))
                if paraformer_candidates:
                    return (
                        str(tokens_path),
                        str(paraformer_candidates[0]),
                        "",
                        "",
                    )
                encoder_candidates = sorted(model_dir.glob("encoder*.onnx"))
                decoder_candidates = sorted(model_dir.glob("decoder*.onnx"))
                joiner_candidates = sorted(model_dir.glob("joiner*.onnx"))
                if encoder_candidates and decoder_candidates and joiner_candidates:
                    return (
                        str(tokens_path),
                        str(encoder_candidates[0]),
                        str(decoder_candidates[0]),
                        str(joiner_candidates[0]),
                    )
        return "", "", "", ""

    def _init_sherpa_onnx(self) -> None:
        try:
            import sherpa_onnx  # type: ignore
        except Exception as exc:
            self._sherpa_error = str(exc)
            self._sherpa_ready = False
            if self.config.model_path:
                self._init_vosk()
            return
        tokens = self._resolve_existing_path(self.config.tokens_path)
        encoder = self._resolve_existing_path(self.config.encoder_path)
        decoder = self._resolve_existing_path(self.config.decoder_path)
        joiner = self._resolve_existing_path(self.config.joiner_path)
        if not tokens or not encoder:
            tokens, encoder, decoder, joiner = self._discover_sherpa_assets()
        if not tokens or not encoder:
            self._sherpa_error = "missing_sherpa_model_files"
            self._sherpa_ready = False
            if self.config.model_path:
                self._init_vosk()
            return
        paraformer_like = (
            "paraformer" in Path(encoder).name.lower()
            or "model" in Path(encoder).name.lower()
            or not decoder
            or not joiner
        )
        if paraformer_like:
            try:
                self._sherpa_recognizer = sherpa_onnx.OfflineRecognizer.from_paraformer(
                    tokens=tokens,
                    paraformer=encoder,
                    num_threads=max(1, int(self.config.num_threads or 2)),
                    sample_rate=16000,
                    feature_dim=80,
                    decoding_method="greedy_search",
                    debug=False,
                    provider="cpu",
                )
                self._sherpa_ready = True
                self._sherpa_error = None
                return
            except Exception as exc:
                self._sherpa_error = str(exc)
        if decoder and joiner:
            try:
                self._sherpa_recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
                    tokens=tokens,
                    encoder=encoder,
                    decoder=decoder,
                    joiner=joiner,
                    num_threads=max(1, int(self.config.num_threads or 2)),
                    sample_rate=16000,
                    feature_dim=80,
                    decoding_method="greedy_search",
                    debug=False,
                    provider="cpu",
                )
                self._sherpa_ready = True
                self._sherpa_error = None
                return
            except Exception as exc:
                self._sherpa_error = str(exc)
        self._sherpa_ready = False
        if self.config.model_path:
            self._init_vosk()

    def _transcribe_sherpa_onnx(self, pcm_s16le: bytes, sample_rate: int) -> str:
        if not self._sherpa_ready or self._sherpa_recognizer is None:
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
        samples = np.frombuffer(pcm, dtype=np.int16).astype("float32") / 32768.0
        try:
            stream = self._sherpa_recognizer.create_stream()
            stream.accept_waveform(16000, samples)
            self._sherpa_recognizer.decode_stream(stream)
            result = getattr(stream.result, "text", "") if hasattr(stream, "result") else ""
            return str(result or "").strip()
        except Exception as exc:
            self._sherpa_error = str(exc)
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
                model_path = (self._repo_root() / model_path).resolve()
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
