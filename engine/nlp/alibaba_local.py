from __future__ import annotations

import json
import re
import time
import difflib
from typing import Any, Optional


def _pick_device(prefer_gpu: bool = False) -> str:
    if prefer_gpu:
        try:
            import torch  # type: ignore

            if bool(torch.cuda.is_available()):
                return "cuda:0"
        except Exception:
            pass
    return "cpu"


def _normalize_text(s: str) -> str:
    text = str(s or "").strip().lower()
    for ch in (
        " ",
        "\t",
        "\n",
        "\r",
        ",",
        ".",
        "!",
        "?",
        "，",
        "。",
        "！",
        "？",
        "、",
        "\"",
        "'",
        "“",
        "”",
        "‘",
        "’",
    ):
        text = text.replace(ch, "")
    return text


def _match_wake(text: str, wake_phrase: str) -> bool:
    t = _normalize_text(text)
    w = _normalize_text(wake_phrase)
    if not t or not w:
        return False
    if w in t:
        return True

    aliases = {
        "小念",
        "小念小念",
        "心念",
        "心念心念",
        "小云",
        "小云小云",
        "晓念",
        "晓念晓念",
        "小年",
        "小年小年",
        "想念",
        "想念想念",
        "两念",
        "两念两念",
        "xiaonian",
        "xiaonianxiaonian",
        "xinnian",
        "xinnianxinnian",
    }
    if w in aliases and any(a in t for a in aliases):
        return True
    roman = re.sub(r"[^a-z]", "", t)
    if roman:
        targets = ("xiaonian", "xinnian")
        if any(tt in roman for tt in targets):
            return True
        for tt in targets:
            if len(roman) >= len(tt) - 1:
                ratio = difflib.SequenceMatcher(None, roman[: min(len(roman), len(tt) + 1)], tt).ratio()
                if ratio >= 0.92:
                    return True
    return False


def _extract_text(result: Any) -> str:
    def _clean_candidate(text: str) -> str:
        t = str(text or "").strip()
        if not t:
            return ""
        if t.startswith("rand_key_"):
            return ""
        low = t.lower()
        if low in {"rejected", "reject", "silence", "unknown", "none", "null"}:
            return ""
        if t in {"拒识", "未识别", "无"}:
            return ""
        if re.fullmatch(r"[A-Za-z0-9_-]{18,}", t):
            return ""
        return t

    if result is None:
        return ""
    if isinstance(result, str):
        return _clean_candidate(result)
    if isinstance(result, list):
        parts: list[str] = []
        for item in result:
            txt = _extract_text(item)
            if txt:
                parts.append(txt)
        return "".join(parts).strip()
    if isinstance(result, dict):
        for key in (
            "text",
            "sentence",
            "result",
            "value",
            "key",
            "keyword",
            "label",
            "name",
            "transcript",
            "transcription",
            "asr_result",
        ):
            val = result.get(key)
            if isinstance(val, str) and val.strip():
                cleaned = _clean_candidate(val)
                if cleaned:
                    return cleaned
        for key in ("output", "data", "preds", "pred", "results", "sentence_info", "sentences", "segments"):
            val = result.get(key)
            txt = _extract_text(val)
            if txt:
                return txt
        # Generic deep scan for nested structures not covered by known keys.
        for val in result.values():
            txt = _extract_text(val)
            if txt:
                return txt
        return ""
    # modelscope/funasr object fallback
    for attr in ("text", "sentence"):
        val = getattr(result, attr, None)
        if isinstance(val, str) and val.strip():
            return val.strip()
    to_dict = getattr(result, "to_dict", None)
    if callable(to_dict):
        try:
            return _extract_text(to_dict())
        except Exception:
            return ""
    return ""


def _extract_vad_segments(result: Any) -> list[list[float]]:
    if result is None:
        return []
    if isinstance(result, list):
        # Typical format: [[start_ms, end_ms], ...] or list of objects.
        if result and isinstance(result[0], (list, tuple)) and len(result[0]) >= 2:
            out = []
            for seg in result:
                try:
                    out.append([float(seg[0]), float(seg[1])])
                except Exception:
                    continue
            return out
        merged: list[list[float]] = []
        for item in result:
            merged.extend(_extract_vad_segments(item))
        return merged
    if isinstance(result, dict):
        for key in ("segments", "segment", "vad", "value", "result"):
            if key in result:
                segs = _extract_vad_segments(result.get(key))
                if segs:
                    return segs
    return []


class _FunAsrRunner:
    def __init__(self, model_id: str, init_kwargs: Optional[dict[str, Any]] = None) -> None:
        self.model_id = model_id
        self._init_kwargs = dict(init_kwargs or {})
        self._model = None
        self._ready = False
        self._error: Optional[str] = None
        self._init_model()

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def error(self) -> Optional[str]:
        return self._error

    def _init_model(self) -> None:
        try:
            from funasr import AutoModel  # type: ignore
        except Exception as exc:
            self._error = f"funasr_import_error:{exc}"
            self._ready = False
            return
        try:
            self._model = AutoModel(
                model=self.model_id,
                disable_pbar=True,
                disable_update=True,
                **self._init_kwargs,
            )
            self._ready = True
        except Exception as exc:
            self._error = f"automodel_init_error:{exc}"
            self._ready = False

    def generate(self, input_data: Any, **kwargs: Any) -> Any:
        if not self._ready or self._model is None:
            return None
        # FunASR model kwargs differ by model type, try progressively.
        tries = [
            kwargs,
            {k: v for k, v in kwargs.items() if k in {"hotword", "keywords", "batch_size_s", "chunk_size"}},
            {},
        ]
        last_exc: Optional[Exception] = None
        for kw in tries:
            try:
                out = self._model.generate(input=input_data, **kw)
                self._error = None
                return out
            except Exception as exc:
                last_exc = exc
                continue
        if last_exc:
            self._error = f"generate_error:{last_exc}"
        return None


class AlibabaKwsDetector:
    """Low-overhead local wake detector using Alibaba/FunASR KWS model."""

    def __init__(
        self,
        wake_phrase: str = "\u5c0f\u5ff5",
        model_id: str = "iic/speech_sanm_kws_phone-xiaoyun-commands-offline",
        sample_rate: int = 16000,
    ) -> None:
        self.wake_phrase = str(wake_phrase or "\u5c0f\u5ff5")
        self.sample_rate = int(sample_rate)
        self._model_id = str(model_id or "").strip() or "iic/speech_sanm_kws_phone-xiaoyun-commands-offline"
        self._fallback_model_id = "iic/speech_sanm_kws_phone-xiaoyun-commands-offline"
        self._keywords = [
            self.wake_phrase,
            f"{self.wake_phrase}{self.wake_phrase}",
            "\u5c0f\u5ff5",
            "\u5c0f\u5ff5\u5c0f\u5ff5",
            "\u5fc3\u5ff5",
            "\u5fc3\u5ff5\u5fc3\u5ff5",
            "\u5c0f\u4e91",
            "\u5c0f\u4e91\u5c0f\u4e91",
            "\u5c0f\u5e74",
            "\u5c0f\u5e74\u5c0f\u5e74",
            "\u6653\u5ff5",
            "\u6653\u5ff5\u6653\u5ff5",
            "xiaonian",
            "xiaonianxiaonian",
            "xiaoyun",
            "xiaoyunxiaoyun",
        ]
        model_id_lc = self._model_id.lower()
        self._alt_probe_mode = "sanm" if "sanm_kws" in model_id_lc else ("charctc" if "charctc_kws" in model_id_lc else "")
        if "sanm_kws" in model_id_lc:
            self._init_kwargs = {
                "keywords": ",".join(self._keywords),
                "chunk_size": [4, 8, 4],
                "encoder_chunk_look_back": 0,
                "decoder_chunk_look_back": 0,
                "device": "cpu",
                # Some FunASR SANM KWS builds require writer/output_dir to be initialized.
                "output_dir": "./outputs/kws_debug",
            }
        else:
            # charctc kws models are less strict on chunk args; keep init minimal.
            self._init_kwargs = {
                "keywords": ",".join(self._keywords),
                "device": "cpu",
                "output_dir": "./outputs/kws_debug",
            }
        self._runner = _FunAsrRunner(model_id=self._model_id, init_kwargs=self._init_kwargs)
        self._switched_to_fallback = False
        self._buffer = bytearray()
        # Keep local KWS light enough for real-time loops on CPU.
        self._window_sec = 3.2
        self._step_sec = 0.18
        self._min_eval_sec = 0.7
        self._last_eval_ms = 0
        self._last_trigger_ms = 0
        self._cooldown_ms = 900
        self._last_text = ""
        self._min_eval_energy = 3.0
        self._last_raw_debug_ms = 0
        self._runtime_disabled = False
        self._consecutive_failures = 0
        self._unhealthy = False
        self._failure_unhealthy_threshold = 50 if "charctc_kws" in model_id_lc else 12
        self._rejected_streak = 0
        self._last_rejected_log_ms = 0
        self._last_alt_probe_ms = 0

        if "xiaoyun" in self._model_id.lower():
            normalized_wake = _normalize_text(self.wake_phrase)
            if "xiaoyun" not in normalized_wake and "\u5c0f\u4e91" not in normalized_wake:
                try:
                    print(
                        "[ali-kws] warning: xiaoyun kws model may have weak custom wake recall "
                        f"for {self.wake_phrase!r}; say '小云小云' once to verify mic/model chain."
                    )
                except Exception:
                    pass

    @property
    def ready(self) -> bool:
        return self._runner.ready

    @property
    def last_text(self) -> str:
        return self._last_text

    @property
    def error(self) -> Optional[str]:
        return self._runner.error

    @property
    def unhealthy(self) -> bool:
        return bool(self._unhealthy or self._runtime_disabled)

    def reset(self) -> None:
        self._buffer = bytearray()

    def update(self, pcm_s16le: bytes) -> bool:
        if self._runtime_disabled:
            return False
        if not self.ready:
            return False
        if not pcm_s16le:
            return False
        self._buffer.extend(pcm_s16le)
        max_bytes = int(self.sample_rate * 2 * self._window_sec * 2)
        if len(self._buffer) > max_bytes:
            self._buffer = self._buffer[-max_bytes:]

        now = int(time.time() * 1000)
        if now - self._last_eval_ms < int(self._step_sec * 1000):
            return False
        self._last_eval_ms = now
        min_eval_bytes = int(self.sample_rate * 2 * self._min_eval_sec)
        if len(self._buffer) < min_eval_bytes:
            return False
        recent = bytes(self._buffer[-int(self.sample_rate * 2 * 0.8) :])
        if self._pcm_energy(recent) < self._min_eval_energy:
            self._last_text = ""
            return False

        boosted = bytes(self._buffer)
        audio_input = self._pcm_to_input(boosted)
        if audio_input is None:
            return False
        result = self._runner.generate(
            audio_input,
            sample_rate=self.sample_rate,
            keywords=",".join(self._keywords),
        )
        if result is None:
            err = str(self._runner.error or "").lower()
            # Short-window probe should not poison KWS health.
            if "audio is too short" in err:
                self._last_text = ""
                return False
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._failure_unhealthy_threshold:
                self._unhealthy = True
            now_ms = int(time.time() * 1000)
            if now_ms - self._last_raw_debug_ms >= 1200:
                self._last_raw_debug_ms = now_ms
                try:
                    print(f"[ali-kws] empty_result err={self._runner.error}")
                except Exception:
                    pass
            err = str(self._runner.error or "")
            if "NoneType" in err and ("strip" in err or "iterable" in err):
                if (not self._switched_to_fallback) and (self._model_id != self._fallback_model_id):
                    try:
                        print(
                            f"[ali-kws] online model unstable, switching to offline model: {self._fallback_model_id}"
                        )
                    except Exception:
                        pass
                    self._switched_to_fallback = True
                    self._model_id = self._fallback_model_id
                    self._runner = _FunAsrRunner(model_id=self._model_id, init_kwargs=self._init_kwargs)
                    self._runtime_disabled = not self._runner.ready
                    self._unhealthy = not self._runner.ready
                    self._consecutive_failures = 0
                    return False
                self._runtime_disabled = True
                try:
                    print("[ali-kws] runtime disabled due to model/runtime incompatibility; use wake-asr path")
                except Exception:
                    pass
            return False
        self._consecutive_failures = 0
        self._unhealthy = False
        text = _extract_text(result)
        raw_json = self._safe_json(result)
        if "rejected" in raw_json.lower():
            self._rejected_streak += 1
            now_ms = int(time.time() * 1000)
            if self._rejected_streak >= 12 and (now_ms - self._last_rejected_log_ms) >= 2500:
                self._last_rejected_log_ms = now_ms
                try:
                    print(
                        f"[ali-kws] rejected_streak={self._rejected_streak} "
                        f"wake_phrase={self.wake_phrase!r} model={self._model_id}"
                    )
                except Exception:
                    pass
            # Root-cause probe: some KWS models are sensitive to input format/rate.
            # When we observe sustained rejected results, try alternative input paths.
            if self._rejected_streak >= 8 and (now_ms - self._last_alt_probe_ms) >= 1400:
                self._last_alt_probe_ms = now_ms
                if self._alt_probe_mode == "sanm":
                    alt_text, alt_raw = self._probe_alt_inputs(boosted)
                else:
                    alt_text, alt_raw = self._probe_charctc_wav(boosted)
                if alt_text:
                    text = alt_text
                    raw_json = alt_raw or raw_json
                    self._rejected_streak = 0
        else:
            self._rejected_streak = 0
        if str(text).strip().lower() in {"rejected", "reject"}:
            text = ""
        if not text and result is not None:
            # Some KWS models return structured keyword fields.
            raw = raw_json
            now_ms = int(time.time() * 1000)
            if now_ms - self._last_raw_debug_ms >= 2000:
                self._last_raw_debug_ms = now_ms
                try:
                    print(f"[ali-kws] raw={raw[:240]}")
                except Exception:
                    pass
            for kw in self._keywords:
                if kw and kw in raw:
                    text = kw
                    break
        self._last_text = text
        # Some FunASR KWS outputs return "detected ???? 1.0" without a usable
        # keyword token. Treat explicit detected events as a wake hit.
        compact_text = _normalize_text(text)
        detected_event = False
        if compact_text.startswith("detected") and "reject" not in compact_text:
            detected_event = True
        if (not detected_event) and ("detected" in raw_json.lower()) and ("rejected" not in raw_json.lower()):
            detected_event = True
        if detected_event and not _match_wake(text, self.wake_phrase):
            text = self.wake_phrase
            self._last_text = text
        if not _match_wake(text, self.wake_phrase):
            return False
        if now - self._last_trigger_ms < self._cooldown_ms:
            return False
        self._last_trigger_ms = now
        self.reset()
        return True

    def _pcm_energy(self, pcm_s16le: bytes) -> float:
        if not pcm_s16le:
            return 0.0
        try:
            import array

            arr = array.array("h")
            arr.frombytes(pcm_s16le)
            if not arr:
                return 0.0
            total = 0.0
            for s in arr:
                total += abs(float(s))
            return total / max(1, len(arr))
        except Exception:
            return 0.0

    def _safe_json(self, obj: Any) -> str:
        try:
            return json.dumps(obj, ensure_ascii=False)
        except Exception:
            return str(obj)

    def _probe_alt_inputs(self, pcm_s16le: bytes) -> tuple[str, str]:
        def _run(inp: Any, sr: int, tag: str) -> tuple[str, str]:
            try:
                res = self._runner.generate(
                    inp,
                    sample_rate=sr,
                    keywords=",".join(self._keywords),
                )
            except Exception:
                return "", ""
            if res is None:
                return "", ""
            raw = self._safe_json(res)
            txt = _extract_text(res)
            if txt and str(txt).strip().lower() not in {"rejected", "reject"}:
                try:
                    print(f"[ali-kws] alt_input_hit={tag} text={txt!r}")
                except Exception:
                    pass
                return txt, raw
            return "", raw

        # 1) int16 ndarray @ 16k
        int16_arr = self._pcm_to_input_int16(pcm_s16le)
        if int16_arr is not None:
            txt, raw = _run(int16_arr, self.sample_rate, "int16_16k")
            if txt:
                return txt, raw

        # 2) downsample to 8k float/int16 (some phone KWS models prefer this path)
        ds = self._downsample_by_2(pcm_s16le)
        if ds:
            float8k = self._pcm_to_input(ds)
            if float8k is not None:
                txt, raw = _run(float8k, self.sample_rate // 2, "float_8k")
                if txt:
                    return txt, raw
            int16_8k = self._pcm_to_input_int16(ds)
            if int16_8k is not None:
                txt, raw = _run(int16_8k, self.sample_rate // 2, "int16_8k")
                if txt:
                    return txt, raw
        return "", ""

    def _probe_charctc_wav(self, pcm_s16le: bytes) -> tuple[str, str]:
        wav_bytes = self._pcm_to_wav_bytes(pcm_s16le, self.sample_rate)
        if not wav_bytes:
            return "", ""
        try:
            res = self._runner.generate(
                wav_bytes,
                sample_rate=self.sample_rate,
                keywords=",".join(self._keywords),
            )
        except Exception:
            return "", ""
        if res is None:
            return "", ""
        raw = self._safe_json(res)
        txt = _extract_text(res)
        low = raw.lower()
        if ("detected" in low) and ("rejected" not in low):
            if not txt:
                txt = self.wake_phrase
            try:
                print(f"[ali-kws] alt_input_hit=wav_bytes text={txt!r}")
            except Exception:
                pass
            return txt, raw
        if txt and str(txt).strip().lower() not in {"rejected", "reject"}:
            try:
                print(f"[ali-kws] alt_input_hit=wav_bytes text={txt!r}")
            except Exception:
                pass
            return txt, raw
        return "", raw

    def _pcm_to_input(self, pcm_s16le: bytes):
        if not pcm_s16le:
            return None
        try:
            import numpy as np  # type: ignore

            arr = np.frombuffer(pcm_s16le, dtype=np.int16).astype(np.float32) / 32768.0
            return arr
        except Exception:
            return None

    def _pcm_to_input_int16(self, pcm_s16le: bytes):
        if not pcm_s16le:
            return None
        try:
            import numpy as np  # type: ignore

            return np.frombuffer(pcm_s16le, dtype=np.int16)
        except Exception:
            return None

    def _downsample_by_2(self, pcm_s16le: bytes) -> bytes:
        if not pcm_s16le:
            return b""
        try:
            import numpy as np  # type: ignore

            arr = np.frombuffer(pcm_s16le, dtype=np.int16)
            if arr.size < 4:
                return b""
            return arr[::2].astype(np.int16).tobytes()
        except Exception:
            return b""

    def _pcm_to_wav_bytes(self, pcm_s16le: bytes, sample_rate: int) -> bytes:
        if not pcm_s16le:
            return b""
        try:
            import io
            import wave

            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(int(sample_rate))
                wf.writeframes(pcm_s16le)
            return buf.getvalue()
        except Exception:
            return b""

    def _boost_pcm(self, pcm_s16le: bytes, gain: float = 2.4) -> bytes:
        if not pcm_s16le:
            return pcm_s16le
        try:
            import array

            arr = array.array("h")
            arr.frombytes(pcm_s16le)
            if not arr:
                return pcm_s16le
            abs_sum = 0.0
            for s in arr:
                abs_sum += abs(float(s))
            avg_abs = abs_sum / max(1, len(arr))
            target_abs = 2200.0
            auto_gain = target_abs / max(1.0, avg_abs)
            effective_gain = max(float(gain), auto_gain)
            effective_gain = max(1.0, min(8.0, effective_gain))
            for i, s in enumerate(arr):
                v = int(float(s) * effective_gain)
                if v > 32767:
                    v = 32767
                elif v < -32768:
                    v = -32768
                arr[i] = v
            return arr.tobytes()
        except Exception:
            return pcm_s16le


class AlibabaAsrWakeDetector:
    """Wake detector powered by local Alibaba ASR models (e.g. SenseVoiceSmall)."""

    def __init__(
        self,
        wake_phrase: str = "\u5c0f\u5ff5",
        model_id: str = "iic/SenseVoiceSmall",
        sample_rate: int = 16000,
        prefer_gpu: bool = True,
    ) -> None:
        self.wake_phrase = str(wake_phrase or "\u5c0f\u5ff5")
        self.sample_rate = int(sample_rate)
        self._model_id = str(model_id or "").strip() or "iic/SenseVoiceSmall"
        self.device = _pick_device(prefer_gpu=bool(prefer_gpu))
        self._runner = _FunAsrRunner(
            model_id=self._model_id,
            init_kwargs={
                "device": self.device,
            },
        )
        self._buffer = bytearray()
        self._window_sec = 2.8
        self._step_sec = 0.20
        self._min_eval_sec = 0.65
        self._last_eval_ms = 0
        self._last_trigger_ms = 0
        self._cooldown_ms = 1200
        self._last_text = ""
        self._min_eval_energy = 8.0
        self._consecutive_failures = 0
        self._unhealthy = False
        self._last_raw_debug_ms = 0
        self._bad_text_streak = 0
        self._noise_floor = 28.0

    @property
    def ready(self) -> bool:
        return self._runner.ready

    @property
    def last_text(self) -> str:
        return self._last_text

    @property
    def error(self) -> Optional[str]:
        return self._runner.error

    @property
    def unhealthy(self) -> bool:
        return bool(self._unhealthy)

    def reset(self) -> None:
        self._buffer = bytearray()

    def update(self, pcm_s16le: bytes) -> bool:
        if not self.ready:
            return False
        if not pcm_s16le:
            return False
        self._buffer.extend(pcm_s16le)
        max_bytes = int(self.sample_rate * 2 * self._window_sec * 2)
        if len(self._buffer) > max_bytes:
            self._buffer = self._buffer[-max_bytes:]

        now = int(time.time() * 1000)
        if now - self._last_eval_ms < int(self._step_sec * 1000):
            return False
        self._last_eval_ms = now
        min_eval_bytes = int(self.sample_rate * 2 * self._min_eval_sec)
        if len(self._buffer) < min_eval_bytes:
            return False

        recent = bytes(self._buffer[-int(self.sample_rate * 2 * 0.85) :])
        recent_energy = self._pcm_energy(recent)
        self._update_noise_floor(recent_energy)
        # Root fix: avoid running ASR wake inference on ambient noise windows.
        energy_gate = max(
            float(self._min_eval_energy),
            self._noise_floor * 1.35,
            self._noise_floor + 6.0,
        )
        if recent_energy < energy_gate:
            self._last_text = ""
            return False

        boosted = self._boost_pcm(bytes(self._buffer), gain=1.8)
        audio_input = self._pcm_to_input(boosted)
        if audio_input is None:
            return False

        hotword = (
            f"{self.wake_phrase} {self.wake_phrase}{self.wake_phrase} "
            "小念 小念小念 心念 心念心念 晓念 晓念晓念 小年 小年小年 "
            "想念 想念想念 两念 两念两念 xiaonian xiaonianxiaonian xinnian xinnianxinnian"
        )
        result = self._runner.generate(
            audio_input,
            batch_size_s=4,
            hotword=hotword,
            language="zh",
            use_itn=True,
        )
        if result is None:
            self._consecutive_failures += 1
            if self._consecutive_failures >= 8:
                self._unhealthy = True
            return False
        self._consecutive_failures = 0
        self._unhealthy = False

        raw_text = str(_extract_text(result) or "")
        text = self._clean_asr_text(raw_text)
        if not text:
            if self._looks_like_garbled(raw_text):
                self._bad_text_streak += 1
                if self._bad_text_streak >= 10:
                    self._unhealthy = True
            else:
                self._bad_text_streak = max(0, self._bad_text_streak - 1)
            # Some SenseVoice outputs keep text in raw payload fields.
            now_ms = int(time.time() * 1000)
            if now_ms - self._last_raw_debug_ms >= 1800:
                self._last_raw_debug_ms = now_ms
                try:
                    print(f"[ali-asr-kws] raw={json.dumps(result, ensure_ascii=False)[:260]}")
                except Exception:
                    pass
            self._last_text = ""
            return False

        self._bad_text_streak = 0
        self._last_text = text
        if not _match_wake(text, self.wake_phrase):
            return False
        if now - self._last_trigger_ms < self._cooldown_ms:
            return False

        self._last_trigger_ms = now
        self.reset()
        return True

    def _clean_asr_text(self, text: str) -> str:
        t = str(text or "").strip()
        if not t:
            return ""
        # SenseVoice style tags: <|zh|><|NEUTRAL|><|Speech|><|woitn|>
        t = re.sub(r"<\|[^|>]+\|>", "", t)
        # Strip invalid replacement characters frequently seen in broken outputs.
        t = t.replace("\ufffd", "")
        t = t.replace(" ", "").strip()
        t = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", t)
        if len(t) <= 1:
            return ""
        return t

    def _looks_like_garbled(self, text: str) -> bool:
        t = str(text or "").strip()
        if not t:
            return False
        if "\ufffd" in t:
            return True
        no_tags = re.sub(r"<\|[^|>]+\|>", "", t).strip()
        if not no_tags:
            return True
        compact = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", no_tags)
        if not compact:
            return True
        if compact.lower() in {"withitn", "woitn", "witn", "itn"}:
            return True
        return False

    def _pcm_to_input(self, pcm_s16le: bytes):
        if not pcm_s16le:
            return None
        try:
            import numpy as np  # type: ignore

            arr = np.frombuffer(pcm_s16le, dtype=np.int16).astype(np.float32) / 32768.0
            return arr
        except Exception:
            return None

    def _pcm_energy(self, pcm_s16le: bytes) -> float:
        if not pcm_s16le:
            return 0.0
        try:
            import array

            arr = array.array("h")
            arr.frombytes(pcm_s16le)
            if not arr:
                return 0.0
            total = 0.0
            for s in arr:
                total += abs(float(s))
            return total / max(1, len(arr))
        except Exception:
            return 0.0

    def _boost_pcm(self, pcm_s16le: bytes, gain: float = 2.8) -> bytes:
        if not pcm_s16le:
            return pcm_s16le
        try:
            import array

            arr = array.array("h")
            arr.frombytes(pcm_s16le)
            if not arr:
                return pcm_s16le
            abs_sum = 0.0
            for s in arr:
                abs_sum += abs(float(s))
            avg_abs = abs_sum / max(1, len(arr))
            target_abs = 2200.0
            auto_gain = target_abs / max(1.0, avg_abs)
            effective_gain = max(float(gain), auto_gain)
            effective_gain = max(1.0, min(6.0, effective_gain))
            for i, s in enumerate(arr):
                v = int(float(s) * effective_gain)
                if v > 32767:
                    v = 32767
                elif v < -32768:
                    v = -32768
                arr[i] = v
            return arr.tobytes()
        except Exception:
            return pcm_s16le

    def _update_noise_floor(self, energy: float) -> None:
        if energy <= 0:
            return
        if energy < (self._noise_floor * 0.70):
            alpha = 0.20
        elif energy < self._noise_floor:
            alpha = 0.10
        else:
            alpha = 0.004
        self._noise_floor = (1.0 - alpha) * self._noise_floor + alpha * energy
        self._noise_floor = max(4.0, min(self._noise_floor, 2600.0))


class AlibabaAsrTranscriber:
    """Alibaba local VAD + Paraformer ASR transcriber."""

    def __init__(
        self,
        sample_rate: int = 16000,
        asr_model_id: str = "damo/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online",
        vad_model_id: str = "damo/speech_fsmn_vad_zh-cn-16k-common-pytorch",
    ) -> None:
        self.sample_rate = int(sample_rate)
        asr_device = _pick_device(prefer_gpu=True)
        self._asr = _FunAsrRunner(asr_model_id, init_kwargs={"device": asr_device})
        self._vad = _FunAsrRunner(vad_model_id, init_kwargs={"device": "cpu"})
        self.device = asr_device
        self._last_empty_debug_ms = 0

    @property
    def ready(self) -> bool:
        return self._asr.ready

    @property
    def error(self) -> Optional[str]:
        return self._asr.error or self._vad.error

    def transcribe(self, pcm_s16le: bytes, sample_rate: int) -> str:
        if not self.ready:
            return ""
        if sample_rate != self.sample_rate:
            return ""
        duration_sec = float(len(pcm_s16le)) / float(max(1, self.sample_rate * 2))
        audio_input = self._pcm_to_input(pcm_s16le)
        if audio_input is None:
            return ""
        if self._vad.ready:
            vad_res = self._vad.generate(audio_input)
            _extract_vad_segments(vad_res)

        hotword = "小念 小念小念 小年 小年小年 晓念 晓念晓念 xiaonian"
        result = self._asr.generate(
            audio_input,
            batch_size_s=20,
            merge_vad=True,
            hotword=hotword,
        )
        text = _extract_text(result)
        # Retry with lighter kwargs when first pass is empty on short/noisy clips.
        if not text:
            retry_result = self._asr.generate(
                audio_input,
                batch_size_s=8,
                merge_vad=True,
                hotword=hotword,
            )
            retry_text = _extract_text(retry_result)
            if retry_text:
                result = retry_result
                text = retry_text
        # Last resort: no kwargs
        if not text:
            retry_result = self._asr.generate(audio_input)
            retry_text = _extract_text(retry_result)
            if retry_text:
                result = retry_result
                text = retry_text

        if result is None:
            now_ms = int(time.time() * 1000)
            if now_ms - self._last_empty_debug_ms >= 1400:
                self._last_empty_debug_ms = now_ms
                try:
                    print(f"[ali-asr] empty_result err={self._asr.error}")
                except Exception:
                    pass
            return ""
        if not text and result is not None:
            now_ms = int(time.time() * 1000)
            if now_ms - self._last_empty_debug_ms >= 1800:
                self._last_empty_debug_ms = now_ms
                try:
                    raw = json.dumps(result, ensure_ascii=False)
                except Exception:
                    raw = str(result)
                try:
                    print(f"[ali-asr] empty_result raw={raw[:280]}")
                except Exception:
                    pass
        return str(text).strip()

    def _pcm_to_input(self, pcm_s16le: bytes):
        if not pcm_s16le:
            return None
        try:
            import numpy as np  # type: ignore

            arr = np.frombuffer(pcm_s16le, dtype=np.int16).astype(np.float32) / 32768.0
            return arr
        except Exception:
            return None

