from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple


class TextRiskScorer:
    def __init__(self, lexicon_path: str) -> None:
        self.lexicon = self._load_lexicon(Path(lexicon_path))

    def score(self, transcript: str) -> Tuple[Optional[float], List[str], str]:
        if not transcript:
            return None, [], ""
        text = transcript.strip()
        tags: List[str] = []
        for tag, keywords in self.lexicon.items():
            if any(keyword in text for keyword in keywords):
                tags.append(tag)
        if tags:
            t_score = min(1.0, 0.6 + 0.1 * len(tags))
        else:
            t_score = 0.2
        summary = text[:120]
        return t_score, tags, summary

    def _load_lexicon(self, path: Path) -> Dict[str, List[str]]:
        lexicon: Dict[str, List[str]] = {}
        if not path.exists():
            return lexicon
        for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            tag, keywords_raw = line.split(":", 1)
            keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
            if keywords:
                lexicon[tag.strip()] = keywords
        return lexicon
