from __future__ import annotations

import json
import tarfile
import time
from pathlib import Path
from typing import Optional


DEFAULT_SHERPA_KWS_ARCHIVE_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/"
    "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01.tar.bz2"
)


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


def _safe_extract_tar(archive_path: Path, target_dir: Path) -> None:
    target_dir = target_dir.resolve()
    with tarfile.open(str(archive_path), "r:*") as tar:
        members = tar.getmembers()
        for m in members:
            member_path = (target_dir / m.name).resolve()
            if not str(member_path).startswith(str(target_dir)):
                raise RuntimeError(f"unsafe_archive_member:{m.name}")
        tar.extractall(path=str(target_dir))


class SherpaKwsDetector:
    """Streaming KWS wrapper around sherpa-onnx KeywordSpotter."""

    def __init__(
        self,
        wake_phrase: str = "小念",
        model_dir: str = "models/kws/sherpa",
        sample_rate: int = 16000,
        alias_mode: str = "wide",
        auto_download: bool = True,
        archive_url: str = DEFAULT_SHERPA_KWS_ARCHIVE_URL,
        num_threads: int = 2,
        keywords_score: float = 1.65,
        keywords_threshold: float = 0.20,
    ) -> None:
        self.wake_phrase = str(wake_phrase or "小念").strip() or "小念"
        self.sample_rate = int(sample_rate)
        self.alias_mode = str(alias_mode or "wide").strip().lower()
        self.model_dir = Path(model_dir)
        self.auto_download = bool(auto_download)
        self.archive_url = str(archive_url or DEFAULT_SHERPA_KWS_ARCHIVE_URL).strip()
        self.num_threads = max(1, int(num_threads))
        self.keywords_score = max(0.1, float(keywords_score))
        self.keywords_threshold = max(0.01, float(keywords_threshold))

        self._ready = False
        self._error: Optional[str] = None
        self._last_text = ""
        self._unhealthy = False
        self._fail_streak = 0
        self._fail_unhealthy_threshold = 40
        self._last_trigger_ms = 0
        self._cooldown_ms = 850

        self._np = None
        self._sherpa = None
        self._text2token = None
        self._spotter = None
        self._stream = None
        self._keywords_file = None
        self._model_info: dict[str, str] = {}
        self._init()

    @property
    def ready(self) -> bool:
        return bool(self._ready)

    @property
    def error(self) -> Optional[str]:
        return self._error

    @property
    def last_text(self) -> str:
        return self._last_text

    @property
    def unhealthy(self) -> bool:
        return bool(self._unhealthy)

    @property
    def model_info(self) -> dict[str, str]:
        return dict(self._model_info)

    def reset(self) -> None:
        try:
            if self._spotter is not None and self._stream is not None:
                self._spotter.reset_stream(self._stream)
        except Exception:
            pass

    def update(self, pcm_s16le: bytes) -> bool:
        if not self._ready or self._spotter is None or self._stream is None:
            return False
        if not pcm_s16le:
            return False
        try:
            self._last_text = ""
            samples = self._np.frombuffer(pcm_s16le, dtype=self._np.int16).astype(self._np.float32) / 32768.0
            if samples.size <= 0:
                return False
            self._stream.accept_waveform(self.sample_rate, samples)
            while self._spotter.is_ready(self._stream):
                self._spotter.decode_stream(self._stream)
            keyword = str(self._spotter.get_result(self._stream) or "").strip()
            if not keyword:
                return False
            hit_text = self._normalize_hit_keyword(keyword)
            if not hit_text:
                return False
            now = int(time.time() * 1000)
            if now - self._last_trigger_ms < self._cooldown_ms:
                return False
            self._last_trigger_ms = now
            self._last_text = hit_text
            self.reset()
            self._fail_streak = 0
            self._unhealthy = False
            return True
        except Exception as exc:
            self._fail_streak += 1
            if self._fail_streak >= self._fail_unhealthy_threshold:
                self._unhealthy = True
            self._error = f"runtime_error:{exc}"
            return False

    def _init(self) -> None:
        try:
            import numpy as np  # type: ignore
            import sherpa_onnx  # type: ignore
            from sherpa_onnx import text2token  # type: ignore
        except Exception as exc:
            self._ready = False
            self._error = f"import_error:{exc}"
            return

        self._np = np
        self._sherpa = sherpa_onnx
        self._text2token = text2token

        try:
            assets = self._ensure_model_assets()
            keywords_file = self._build_keywords_file(Path(assets["tokens"]))
            self._keywords_file = str(keywords_file)

            self._spotter = sherpa_onnx.KeywordSpotter(
                tokens=assets["tokens"],
                encoder=assets["encoder"],
                decoder=assets["decoder"],
                joiner=assets["joiner"],
                keywords_file=self._keywords_file,
                num_threads=self.num_threads,
                sample_rate=self.sample_rate,
                feature_dim=80,
                max_active_paths=4,
                keywords_score=self.keywords_score,
                keywords_threshold=self.keywords_threshold,
                num_trailing_blanks=1,
                provider="cpu",
                device=0,
            )
            self._stream = self._spotter.create_stream()
            self._model_info = dict(assets)
            self._ready = True
            self._error = None
        except Exception as exc:
            self._ready = False
            self._error = f"init_error:{exc}"

    def _ensure_model_assets(self) -> dict[str, str]:
        model_root = self.model_dir
        model_root.mkdir(parents=True, exist_ok=True)
        assets = self._find_assets(model_root)
        if assets:
            return assets
        if not self.auto_download:
            raise RuntimeError("model_missing_no_download")
        self._download_and_extract(model_root)
        assets = self._find_assets(model_root)
        if not assets:
            raise RuntimeError("model_assets_not_found_after_download")
        return assets

    def _download_and_extract(self, model_root: Path) -> None:
        try:
            import requests
        except Exception as exc:
            raise RuntimeError(f"requests_import_error:{exc}") from exc

        archive_name = Path(self.archive_url).name or "sherpa_kws.tar.bz2"
        archive_path = model_root / archive_name
        with requests.get(self.archive_url, stream=True, timeout=30) as resp:
            resp.raise_for_status()
            with open(archive_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 128):
                    if not chunk:
                        continue
                    f.write(chunk)
        _safe_extract_tar(archive_path, model_root)

    def _find_assets(self, model_root: Path) -> dict[str, str]:
        candidates = [p for p in model_root.rglob("*") if p.is_file()]
        if not candidates:
            return {}

        def _pick(patterns: list[str]) -> Optional[Path]:
            for pattern in patterns:
                hits = [p for p in candidates if p.match(pattern)]
                if hits:
                    hits.sort(key=lambda x: len(str(x)))
                    return hits[0]
            return None

        tokens = _pick(["**/tokens.txt"])
        encoder = _pick(["**/*encoder*int8*.onnx", "**/*encoder*.onnx"])
        decoder = _pick(["**/*decoder*int8*.onnx", "**/*decoder*.onnx"])
        joiner = _pick(["**/*joiner*int8*.onnx", "**/*joiner*.onnx"])
        if not (tokens and encoder and decoder and joiner):
            return {}
        return {
            "tokens": str(tokens),
            "encoder": str(encoder),
            "decoder": str(decoder),
            "joiner": str(joiner),
        }

    def _build_keywords_file(self, tokens_path: Path) -> Path:
        raw_phrases = self._build_raw_keywords()
        out_path = self.model_dir / f"keywords.generated.{self.alias_mode}.txt"
        lines: list[str] = []
        text2token = self._text2token
        if text2token is None:
            raise RuntimeError("text2token_unavailable")

        converted = None
        convert_error: Optional[Exception] = None
        for token_type in ("ppinyin", "cjkchar"):
            try:
                converted = text2token(
                    raw_phrases,
                    tokens=str(tokens_path),
                    tokens_type=token_type,
                )
                break
            except Exception as exc:
                convert_error = exc
                converted = None
                continue
        if converted is None:
            raise RuntimeError(f"text2token_failed:{convert_error}")

        for idx, tok_list in enumerate(converted):
            phrase = raw_phrases[idx]
            words = [str(t) for t in list(tok_list) if str(t).strip()]
            if not words:
                continue
            words.append(f"@{phrase}")
            lines.append(" ".join(words))
        if not lines:
            raise RuntimeError("keywords_empty_after_conversion")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return out_path

    def _build_raw_keywords(self) -> list[str]:
        phrase = self.wake_phrase.strip() or "小念"
        base = [
            phrase,
            f"{phrase}{phrase}",
            "小念",
            "小念小念",
            "心念",
            "心念心念",
        ]
        near_balanced = [
            "晓念",
            "晓念晓念",
            "小年",
            "小年小年",
            "想念",
            "想念想念",
        ]
        near_wide = [
            "小面",
            "小面小面",
            "新念",
            "新念新念",
            "向念",
            "向念向念",
            "香念",
            "香念香念",
            "两念",
            "两念两念",
            "亮念",
            "亮念亮念",
        ]

        if self.alias_mode == "strict":
            phrases = base
        elif self.alias_mode == "balanced":
            phrases = [*base, *near_balanced]
        else:
            phrases = [*base, *near_balanced, *near_wide]
        seen = set()
        out: list[str] = []
        for p in phrases:
            key = _normalize_text(p)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(str(p).strip())
        return out

    def _normalize_hit_keyword(self, raw_keyword: str) -> str:
        text = str(raw_keyword or "").strip()
        if not text:
            return ""
        # Keep only the original phrase marker when present.
        if "@" in text:
            parts = [p for p in text.split() if p.startswith("@")]
            if parts:
                text = parts[-1].lstrip("@")
        text = text.strip().replace(" ", "")
        # Some builds may still return tokenized form; keep it as-is for upper-layer fuzzy matching.
        return text

    def dump_debug(self) -> str:
        data = {
            "ready": self.ready,
            "error": self.error,
            "unhealthy": self.unhealthy,
            "last_text": self.last_text,
            "model_info": self._model_info,
            "keywords_file": self._keywords_file,
        }
        return json.dumps(data, ensure_ascii=False)
