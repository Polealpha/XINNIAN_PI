from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .local_tools import (
    classify_query,
    datetime_reply,
    extract_music_song,
    fx_reply,
    news_headline_reply,
    open_music_reply,
    stock_reply,
    weather_reply,
)
from .system_tool_executor import SystemToolExecutor
from .tool_intent_router import ToolIntent, ToolIntentRouter


@dataclass
class ToolReply:
    handled: bool
    text: str = ""
    tool: str = ""
    meta: Dict[str, object] = field(default_factory=dict)


class LocalToolRouter:
    def __init__(
        self,
        enabled: bool = True,
        allowlist: Optional[List[str]] = None,
        weather_provider: str = "open_meteo",
        fx_provider: str = "frankfurter",
        stock_provider: str = "alphavantage",
        alphavantage_api_key: str = "",
        system_tooling_enabled: bool = True,
        system_tool_mode: str = "allowlist_direct",
        system_tool_allowlist_apps: Optional[List[str]] = None,
        system_tool_allowlist_actions: Optional[List[str]] = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.allowlist = [str(x).strip().lower() for x in (allowlist or []) if str(x).strip()]
        self.weather_provider = str(weather_provider or "open_meteo").strip().lower()
        self.fx_provider = str(fx_provider or "frankfurter").strip().lower()
        self.stock_provider = str(stock_provider or "alphavantage").strip().lower()
        self.alphavantage_api_key = str(alphavantage_api_key or "").strip()
        if not self.allowlist:
            self.allowlist = [
                "datetime",
                "weather",
                "open_music",
                "music_search_play",
                "news_headline",
                "exchange_rate",
                "stock_quote",
                "system_tool",
            ]

        self._tool_intent_router = ToolIntentRouter()
        self._system_tool_executor = SystemToolExecutor(
            enabled=bool(system_tooling_enabled),
            mode=str(system_tool_mode or "allowlist_direct"),
            allowlist_apps=list(system_tool_allowlist_apps or []),
            allowlist_actions=list(system_tool_allowlist_actions or []),
        )

    def route(self, query: str) -> ToolReply:
        if not self.enabled:
            return ToolReply(handled=False)

        system_intent = self._tool_intent_router.route(query)
        if system_intent and "system_tool" in self.allowlist:
            return self._run_system_tool(system_intent)

        query_lc = str(query or "").strip().lower()
        if re.search(r"(冷不冷|热不热|穿什么|天气怎么样|weather now)", query_lc):
            intent = "weather"
        else:
            intent = classify_query(query)
        if not intent:
            return ToolReply(handled=False)
        if intent not in self.allowlist:
            return ToolReply(handled=False)

        if intent == "datetime":
            res = datetime_reply()
            return ToolReply(handled=res.ok, text=res.text, tool="datetime", meta={"reason": res.reason})

        if intent == "weather":
            res = weather_reply(query)
            if not res.ok:
                return ToolReply(handled=True, text=res.text, tool="weather", meta={"reason": res.reason, "ok": False})
            text = self._append_weather_advice(res.text)
            return ToolReply(handled=True, text=text, tool="weather", meta={"reason": res.reason, "ok": True})

        if intent == "exchange_rate":
            res = fx_reply(query)
            return ToolReply(handled=True, text=res.text, tool="exchange_rate", meta={"reason": res.reason, "ok": res.ok})

        if intent == "stock_quote":
            res = stock_reply(query, api_key=self.alphavantage_api_key)
            return ToolReply(handled=True, text=res.text, tool="stock_quote", meta={"reason": res.reason, "ok": res.ok})

        if intent == "open_music":
            res = open_music_reply("")
            return ToolReply(handled=True, text=res.text, tool="open_music", meta={"reason": res.reason, "ok": res.ok})

        if intent == "music_search_play":
            song = extract_music_song(query)
            intent_payload = ToolIntent(action="music_search_play", args={"song": song})
            return self._run_system_tool(intent_payload)

        if intent == "news_headline":
            res = news_headline_reply(query)
            return ToolReply(
                handled=True,
                text=res.text,
                tool="news_headline",
                meta={"reason": res.reason, "ok": res.ok},
            )

        return ToolReply(handled=False)

    def _append_weather_advice(self, text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return raw
        m = re.search(r"(-?\d+(?:\.\d+)?)\s*℃", raw)
        if not m:
            return raw
        temp = float(m.group(1))
        if temp <= 5:
            advice = "建议穿厚外套，注意保暖。"
        elif temp <= 14:
            advice = "建议加一件外套，早晚注意保暖。"
        elif temp <= 26:
            advice = "体感较舒适，按常规穿着即可。"
        else:
            advice = "天气偏热，建议补水并减少暴晒。"
        if "建议" in raw:
            return raw
        suffix = "。" if not raw.endswith(("。", "！", "？")) else ""
        return f"{raw}{suffix}建议：{advice}"

    def _run_system_tool(self, intent: ToolIntent) -> ToolReply:
        res = self._system_tool_executor.execute(intent)
        return ToolReply(
            handled=True,
            text=res.text,
            tool="system_tool",
            meta={
                "reason": res.reason,
                "ok": res.ok,
                "action": intent.action,
                "args": dict(intent.args),
            },
        )
