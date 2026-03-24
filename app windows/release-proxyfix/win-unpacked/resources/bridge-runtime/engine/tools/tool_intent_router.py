from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Optional

from .local_tools import extract_music_song


@dataclass
class ToolIntent:
    action: str
    args: Dict[str, str] = field(default_factory=dict)


class ToolIntentRouter:
    def route(self, query: str) -> Optional[ToolIntent]:
        q = str(query or "").strip()
        if not q:
            return None
        q_lc = q.lower()

        # Bilibili web intent: open site, or search and open a specific video page.
        if re.search(r"(b站|哔哩哔哩|bilibili)", q_lc):
            if re.search(r"(播放|放|看|搜索|搜|查找|找)", q_lc):
                video_query = self._extract_bilibili_query(q)
                if video_query:
                    return ToolIntent(action="bilibili_search_play", args={"query": video_query})
            if re.search(r"(打开|启动|进入|去|上)", q_lc):
                return ToolIntent(action="open_url", args={"url": "https://www.bilibili.com"})

        # Explicit NetEase music app intent.
        if re.search(r"(打开|启动).*(网易云|云音乐|netease)", q_lc):
            song = self._extract_song(q)
            if song:
                return ToolIntent(action="music_search_play", args={"song": song})
            return ToolIntent(action="open_app", args={"app": "netease_music"})

        # Generic play-music intent: default to NetEase even when app name is omitted.
        if re.search(r"(播放音乐|放歌|来点音乐|听音乐|打开音乐|来首歌|放一首|放首|听首)", q_lc):
            song = self._extract_song(q)
            if song:
                return ToolIntent(action="music_search_play", args={"song": song})
            return ToolIntent(action="open_app", args={"app": "netease_music"})

        # "我要听xxx" should prefer play route.
        if re.search(r"(我要听|想听)", q_lc):
            song = self._extract_song(q)
            if song:
                return ToolIntent(action="music_search_play", args={"song": song})
            return ToolIntent(action="open_app", args={"app": "netease_music"})

        if re.search(r"(打开|启动).*(记事本|notepad)", q_lc):
            return ToolIntent(action="open_app", args={"app": "notepad"})

        if re.search(r"(打开|启动).*(计算器|calculator|calc)", q_lc):
            return ToolIntent(action="open_app", args={"app": "calculator"})

        url_match = re.search(r"https?://[^\s]+", q)
        if url_match and re.search(r"(打开|访问|跳转)", q_lc):
            return ToolIntent(action="open_url", args={"url": url_match.group(0)})

        if re.search(r"(打开|启动).*(浏览器|browser)", q_lc):
            return ToolIntent(action="open_app", args={"app": "browser"})

        return None

    def _extract_song(self, query: str) -> str:
        song = str(extract_music_song(query) or "").strip()
        if song:
            return song
        q = str(query or "").strip()
        patterns = [
            r"(?:播放|放|来一首|来首|听)\s*[《\"“]?([^》\"”\n，。！？]{1,28})[》\"”]?",
            r"(?:我要听|想听)\s*[《\"“]?([^》\"”\n，。！？]{1,28})[》\"”]?",
        ]
        for pat in patterns:
            m = re.search(pat, q, flags=re.IGNORECASE)
            if not m:
                continue
            candidate = str(m.group(1) or "").strip()
            candidate = re.sub(r"(在网易云|网易云音乐|歌曲|歌)$", "", candidate).strip()
            if candidate and candidate not in {"音乐", "歌曲", "歌"}:
                return candidate
        return ""

    def _extract_bilibili_query(self, query: str) -> str:
        q = str(query or "").strip()
        if not q:
            return ""
        q = re.sub(r"(请|帮我|麻烦你|给我|一下|一下子)", " ", q, flags=re.IGNORECASE)
        q = re.sub(r"(打开|启动|进入|去|上)\s*(b站|哔哩哔哩|bilibili)", " ", q, flags=re.IGNORECASE)
        q = re.sub(r"(在)?\s*(b站|哔哩哔哩|bilibili)(上)?", " ", q, flags=re.IGNORECASE)
        q = re.sub(r"(搜索|搜|查找|找|播放|放|看一下|看看|看)\s*", " ", q, flags=re.IGNORECASE)
        q = re.sub(r"\s+", " ", q).strip()
        q = q.strip("：:，,。！？!?\"'“”《》[]()（）")
        if len(q) > 80:
            q = q[:80].strip()
        return q
