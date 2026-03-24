from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional


class WakeWordDetector:
    def __init__(
        self,
        model_path: str,
        sample_rate: int = 16000,
        phrases: Optional[list[str]] = None,
    ) -> None:
        self.sample_rate = int(sample_rate)
        self.phrases = phrases or [
            "\u5c0f\u5ff5",  # 小念
            "\u5c0f\u5ff5\u5c0f\u5ff5",
            "\u5fc3\u5ff5",  # 心念
            "\u5fc3\u5ff5\u5fc3\u5ff5",
            "\u60f3\u5ff5",  # 想念
            "\u60f3\u5ff5\u60f3\u5ff5",
            "\u5c0f\u5e74",  # 小年
            "\u5c0f\u5e74\u5c0f\u5e74",
            "\u6653\u5ff5",  # 晓念
            "\u6653\u5ff5\u6653\u5ff5",
            "\u5c0f\u4e91",  # 小云
            "\u5c0f\u4e91\u5c0f\u4e91",
            "xinnian",
            "xinnianxinnian",
            "xiaonian",
            "xiaonianxiaonian",
            "xiaoyun",
            "xiaoyunxiaoyun",
        ]
        self._model = None
        self._recognizer = None
        self._ready = False
        self._last_trigger_ms = 0
        self._cooldown_ms = 2200
        self._last_text = ""
        self._init_model(model_path)

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def last_text(self) -> str:
        return self._last_text

    def reset(self) -> None:
        if not self._ready:
            return
        try:
            from vosk import KaldiRecognizer  # type: ignore
        except Exception:
            self._ready = False
            return
        grammar_phrases = []
        for p in self.phrases:
            p = str(p or "").strip()
            if p:
                grammar_phrases.append(p)
        grammar_phrases.extend(
            [
                "\u5c0f\u5ff5",
                "\u5fc3\u5ff5",
                "\u5c0f\u5e74",
                "\u6653\u5ff5",
                "\u60f3\u5ff5",
                "\u5c0f\u4e91",
                "xinnian",
                "xiaonian",
                "xiaoyun",
            ]
        )
        # de-dup while keeping order
        seen = set()
        uniq = []
        for g in grammar_phrases:
            if g in seen:
                continue
            seen.add(g)
            uniq.append(g)
        grammar = json.dumps(uniq, ensure_ascii=False)
        try:
            self._recognizer = KaldiRecognizer(self._model, self.sample_rate, grammar)
        except Exception:
            self._recognizer = KaldiRecognizer(self._model, self.sample_rate)
        self._recognizer.SetWords(False)

    def update(self, pcm_s16le: bytes) -> bool:
        if not self._ready or not self._recognizer:
            return False
        try:
            if self._recognizer.AcceptWaveform(pcm_s16le):
                return self._contains_wake(self._recognizer.Result())
            return self._contains_wake(self._recognizer.PartialResult())
        except Exception:
            return False

    def _contains_wake(self, result: str) -> bool:
        try:
            data = json.loads(result)
        except Exception:
            return False
        text = str(data.get("text") or data.get("partial") or "").strip()
        if not text:
            return False
        self._last_text = text
        if not self._match_wake_text(text):
            return False
        now = int(time.time() * 1000)
        if now - self._last_trigger_ms < self._cooldown_ms:
            return False
        self._last_trigger_ms = now
        self.reset()
        return True

    def _match_wake_text(self, text: str) -> bool:
        norm = self._normalize_text(text)
        if not norm:
            return False

        alias_cn = {
            "\u5c0f\u5ff5",  # 小念
            "\u5c0f\u5ff5\u5c0f\u5ff5",
            "\u5fc3\u5ff5",  # 心念
            "\u5fc3\u5ff5\u5fc3\u5ff5",
            "\u60f3\u5ff5",  # 想念
            "\u60f3\u5ff5\u60f3\u5ff5",
            "\u5c0f\u5e74",  # 小年
            "\u5c0f\u5e74\u5c0f\u5e74",
            "\u6653\u5ff5",  # 晓念
            "\u6653\u5ff5\u6653\u5ff5",
            "\u5c0f\u4e91",  # 小云
            "\u5c0f\u4e91\u5c0f\u4e91",
            "\u4fe1\u5ff5",  # 信念
            "\u65b0\u5e74",  # 新年
            "\u65b0\u5e74\u65b0\u5e74",
        }
        if any(a in norm for a in alias_cn):
            return True

        roman = re.sub(r"[^a-z]", "", norm.lower())
        if (
            "xinnianxinnian" in roman
            or "xinnian" in roman
            or "xiaonianxiaonian" in roman
            or "xiaonian" in roman
            or "xiaoyunxiaoyun" in roman
            or "xiaoyun" in roman
        ):
            return True

        pinyin = self._to_pinyin_compact(norm)
        if (
            "xinnianxinnian" in pinyin
            or "xinnian" in pinyin
            or "xiaonianxiaonian" in pinyin
            or "xiaonian" in pinyin
            or "xiaoyunxiaoyun" in pinyin
            or "xiaoyun" in pinyin
        ):
            return True

        for phrase in self.phrases:
            p = self._normalize_text(str(phrase))
            if p and p in norm:
                return True
        return False

    def _normalize_text(self, s: str) -> str:
        s = (s or "").strip().lower()
        if not s:
            return ""
        return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", s)

    def _to_pinyin_compact(self, text: str) -> str:
        try:
            from pypinyin import lazy_pinyin  # type: ignore
        except Exception:
            return ""
        try:
            py = "".join(lazy_pinyin(text))
        except Exception:
            return ""
        return re.sub(r"[^a-z]", "", py.lower())

    def _init_model(self, model_path: str) -> None:
        try:
            from vosk import Model  # type: ignore
        except Exception:
            self._ready = False
            return
        path = Path(model_path)
        if not path.is_absolute():
            repo_root = Path(__file__).resolve().parents[2]
            path = (repo_root / path).resolve()
        if not path.exists():
            self._ready = False
            return
        try:
            self._model = Model(str(path))
            self._ready = True
            self.reset()
        except Exception:
            self._ready = False
