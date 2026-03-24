from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from ..core.config import LlmConfig
from ..tools.local_tool_router import LocalToolRouter, ToolReply


class LLMResponder:
    def __init__(self, config: LlmConfig) -> None:
        self.config = config
        self.enabled = config.enabled
        self._client = None
        self._client_mode = "chat_completions"
        self._max_history_messages = max(2, int(getattr(config, "chat_history_messages", 8)))
        self._messages_by_key: Dict[str, List[Dict[str, str]]] = {}
        self._prompts: Dict[str, str] = {}
        self.last_error: str = ""
        self.last_meta: Dict[str, object] = {}
        self._tool_router = LocalToolRouter(
            enabled=bool(getattr(config, "local_tools_enabled", True)),
            allowlist=list(
                getattr(
                    config,
                    "local_tools_allowlist",
                    [
                        "datetime",
                        "weather",
                        "open_music",
                        "music_search_play",
                        "news_headline",
                        "exchange_rate",
                        "stock_quote",
                        "system_tool",
                    ],
                )
            ),
            weather_provider=str(getattr(config, "weather_provider", "open_meteo")),
            fx_provider=str(getattr(config, "fx_provider", "frankfurter")),
            stock_provider=str(getattr(config, "stock_provider", "alphavantage")),
            alphavantage_api_key=str(getattr(config, "alphavantage_api_key", "")),
            system_tooling_enabled=bool(getattr(config, "system_tooling_enabled", True)),
            system_tool_mode=str(getattr(config, "system_tool_mode", "allowlist_direct")),
            system_tool_allowlist_apps=list(
                getattr(config, "system_tool_allowlist_apps", ["netease_music", "browser", "notepad", "calculator"])
            ),
            system_tool_allowlist_actions=list(
                getattr(
                    config,
                    "system_tool_allowlist_actions",
                    [
                        "open_app",
                        "open_url",
                        "music_search_play",
                        "datetime",
                        "weather",
                        "news",
                        "fx",
                        "stock",
                    ],
                )
            ),
        )
        self._load_prompts()
        self._init_client()

    def reset(self) -> None:
        self._messages_by_key = {}

    def generate_care_reply(self, context: Dict[str, object]) -> Optional[Dict[str, object]]:
        if not self.enabled or not self._client:
            return None
        return self._chat_json("care", context)

    def generate_daily_summary(self, context: Dict[str, object]) -> Optional[Dict[str, object]]:
        if not self.enabled or not self._client:
            return None
        return self._chat_json("summary", context)

    def stream_care_text(self, context: Dict[str, object]) -> Iterator[str]:
        if not self.enabled or not self._client:
            return iter(())
        return self._chat_stream_text("care", context)

    def _log_route(self, route: str, provider: str, result: str, reason: str) -> None:
        print(
            f"[llm-route] route={str(route)} provider={str(provider)} result={str(result)} reason={str(reason)}"
        )

    def _chat_json(self, channel: str, context: Dict[str, object]) -> Optional[Dict[str, object]]:
        messages = self._get_messages(channel)
        self._trim_history(messages)
        user_content = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
        messages.append({"role": "user", "content": user_content})

        self.last_meta = {
            "online_search_attempted": False,
            "online_search_used": False,
            "online_search_fallback": False,
            "online_search_reason": "not_applicable",
            "local_tool_used": False,
            "local_tool_name": "",
            "local_tool_reason": "",
        }

        local_tool_reply = self._try_local_tool(channel, context)
        force_online_search = False
        if local_tool_reply is not None:
            tool_text = self._sanitize_care_text(local_tool_reply.text)
            force_online_search = self._should_force_online_fallback(local_tool_reply, context)
            if tool_text and not force_online_search:
                messages.append({"role": "assistant", "content": tool_text})
                self._trim_history(messages)
                self.last_error = ""
                self.last_meta.update(
                    {
                        "local_tool_used": True,
                        "local_tool_name": local_tool_reply.tool,
                        "local_tool_reason": str(local_tool_reply.meta.get("reason", "")),
                        "online_search_reason": self._normalize_local_reason(local_tool_reply),
                    }
                )
                self._log_route(
                    "local_api",
                    str(local_tool_reply.tool or "local_tool"),
                    "ok",
                    str(self.last_meta.get("online_search_reason", "")),
                )
                return self._validate_care_reply({"text": tool_text, "followup_question": "", "style": "warm"})

        completion = None
        should_search, search_reason = self._should_use_online_search(channel, context)
        if force_online_search:
            should_search = True
            search_reason = "news_api_failed_fallback_web"
        self.last_meta["online_search_reason"] = search_reason
        if should_search:
            self.last_meta = {
                "online_search_attempted": True,
                "online_search_used": False,
                "online_search_fallback": False,
                "online_search_reason": "attempt",
                "local_tool_used": False,
            }
            try:
                completion = self._create_completion_with_web_search(messages)
                self.last_meta = {
                    "online_search_attempted": True,
                    "online_search_used": True,
                    "online_search_fallback": False,
                    "online_search_reason": "ok",
                    "local_tool_used": False,
                }
                self._log_route("web_search", "ark_web_search", "ok", "ok")
            except Exception as exc:
                self.last_error = str(exc)
                err_lc = str(exc or "").lower()
                fail_reason = "failed"
                if (
                    "toolnotopen" in err_lc
                    or "not activated web search" in err_lc
                    or "tool" in err_lc and "not" in err_lc and "open" in err_lc
                ):
                    fail_reason = "web_search_tool_unavailable"
                self.last_meta = {
                    "online_search_attempted": True,
                    "online_search_used": False,
                    "online_search_fallback": True,
                    "online_search_reason": fail_reason,
                    "online_search_error": str(exc),
                    "local_tool_used": False,
                }
                self._log_route("web_search", "ark_web_search", "fallback", fail_reason)
                # News fallback: use direct network-news API summarization.
                fallback_news_text = self._fallback_news_search_text(context)
                if fallback_news_text:
                    messages.append({"role": "assistant", "content": fallback_news_text})
                    self._trim_history(messages)
                    self.last_error = ""
                    self.last_meta["online_search_reason"] = "news_fallback_used"
                    return self._validate_care_reply(
                        {"text": fallback_news_text, "followup_question": "", "style": "warm"}
                    )

        try:
            if completion is None:
                image_data_urls = self._extract_image_data_urls(context)
                if image_data_urls:
                    try:
                        completion = self._create_completion_with_images(messages, image_data_urls)
                    except Exception:
                        completion = self._create_completion(messages, want_json=bool(self.config.response_format))
                else:
                    completion = self._create_completion(messages, want_json=bool(self.config.response_format))
        except Exception as exc:
            self.last_error = str(exc)
            messages.pop()
            return None

        content = self._extract_text_from_completion(completion)
        if self._looks_placeholder_reply(content):
            try:
                plain_completion = self._create_completion(messages, want_json=bool(self.config.response_format))
                plain_text = self._extract_text_from_completion(plain_completion)
                if plain_text.strip():
                    content = plain_text
                    self.last_meta["online_search_fallback"] = True
                    self.last_meta["online_search_reason"] = "placeholder_refallback"
            except Exception as exc:
                self.last_error = str(exc)
        content = self._ensure_final_user_answer(content, channel=channel, context=context, messages=messages)
        self.last_error = ""

        messages.append({"role": "assistant", "content": content})
        self._trim_history(messages)

        parsed = self._parse_json(content)
        validated = self._validate_response(channel, parsed)
        if validated is not None:
            if channel == "care":
                validated = self._apply_online_search_notice_to_reply(validated)
            return validated
        if channel == "care" and content.strip():
            out_text = content
            if self._should_announce_online_search():
                out_text = self._prefix_online_search_notice(out_text)
            return self._validate_care_reply({"text": out_text, "followup_question": "", "style": "warm"})
        if channel == "care":
            self.last_error = "llm_invalid_care_reply"
        return None

    def _should_use_online_search(self, channel: str, context: Dict[str, object]) -> Tuple[bool, str]:
        if channel != "care":
            return False, "channel_not_care"
        if not bool(getattr(self.config, "web_search_enabled", getattr(self.config, "online_search_enabled", True))):
            return False, "web_search_disabled"
        mode = str(getattr(self.config, "online_search_mode", "auto") or "auto").strip().lower()
        if mode != "auto":
            return False, "online_search_mode_not_auto"
        input_type = str(context.get("input_type", "") or "").strip().lower()
        tooling = context.get("tooling") if isinstance(context.get("tooling"), dict) else {}
        budget_remaining = int((tooling or {}).get("web_search_budget_remaining", 9999))
        if budget_remaining <= 0:
            return False, "web_search_budget_exceeded"

        query = self._online_search_query_text(context)
        if not query:
            return False, "query_empty"

        if input_type == "user_text":
            if self._is_news_query(query):
                if bool(getattr(self.config, "web_search_news_default", False)):
                    return True, "news_web_search_forced"
                high_value_news = self._is_high_value_complex_query(query)
                if not high_value_news:
                    return False, "news_fallback_used"
                return True, "high_value_news"
            if self._is_local_or_standard_api_query(query):
                return False, "api_or_local_first"
            high_value = self._is_high_value_complex_query(query)
            if bool(getattr(self.config, "web_search_high_value_only", True)) and not high_value:
                return False, "web_search_not_high_value"
            return True, "high_value_ok"

        # emotion_signal path: only allow in high-risk auto mode and with daily cap.
        if input_type == "emotion_signal":
            if not bool(getattr(self.config, "emotion_linked_search_enabled", True)):
                return False, "emotion_linked_search_disabled"
            risk_score = float(context.get("risk_score", 0.0) or 0.0)
            if risk_score < float(getattr(self.config, "emotion_linked_search_risk_threshold", 0.82)):
                return False, "emotion_linked_search_risk_low"
            emotion_remaining = int((tooling or {}).get("emotion_auto_search_remaining", 0))
            if emotion_remaining <= 0:
                return False, "emotion_linked_search_cap_exceeded"
            return True, "emotion_linked_search_enabled"

        return False, "input_type_not_supported"

    def _online_search_query_text(self, context: Dict[str, object]) -> str:
        current = context.get("current_message")
        if isinstance(current, dict):
            text = str(current.get("text", "")).strip()
            if text:
                return text
        return str(context.get("context", "")).strip()

    def _try_local_tool(self, channel: str, context: Dict[str, object]) -> Optional[ToolReply]:
        if channel != "care":
            return None
        if not bool(getattr(self.config, "tooling_enabled", True)):
            return None
        if not bool(getattr(self.config, "local_tools_enabled", True)):
            return None
        mode = str(getattr(self.config, "tool_routing_mode", "rules_first") or "rules_first").strip().lower()
        if mode != "rules_first":
            return None
        query = self._online_search_query_text(context)
        if not query:
            return None
        query = self._augment_query_with_profile_location(query, context)
        if self._is_news_query(query) and bool(getattr(self.config, "web_search_news_default", False)):
            return None
        routed = self._tool_router.route(query)
        if not routed.handled:
            return None
        return routed

    def _augment_query_with_profile_location(self, query: str, context: Dict[str, object]) -> str:
        text = str(query or "").strip()
        if not text:
            return text
        if not re.search(r"(天气|气温|温度|下雨|降雨|台风|空气质量|冷不冷|热不热|穿什么|weather)", text, flags=re.IGNORECASE):
            return text
        if re.search(r"([\u4e00-\u9fa5]{2,8})(天气|温度|气温)", text):
            return text
        profile = context.get("user_profile")
        if not isinstance(profile, dict):
            return text
        location = str(profile.get("location") or "").strip()
        if not location:
            return text
        return f"{location}天气 {text}"

    def _normalize_local_reason(self, routed: ToolReply) -> str:
        tool_name = str(getattr(routed, "tool", "") or "").strip().lower()
        reason = str((routed.meta or {}).get("reason", "") or "").strip().lower()
        if tool_name == "news_headline":
            if "web_search" in reason:
                return "news_web_search_used"
            return "news_api_used"
        if tool_name == "exchange_rate":
            return "fx_api_used"
        if tool_name == "stock_quote":
            return "stock_api_limited" if "limited" in reason else "stock_api_used"
        if tool_name == "system_tool":
            return "system_tool_exec_failed" if "failed" in reason else "system_tool_exec_ok"
        if tool_name == "open_music":
            return "system_tool_exec_ok" if "failed" not in reason and "error" not in reason else "system_tool_exec_failed"
        return "local_tool"

    def _should_announce_online_search(self) -> bool:
        return bool(self.last_meta.get("online_search_used"))

    def _prefix_online_search_notice(self, text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return raw
        prefix = "我帮你联网搜搜："
        if raw.startswith("我帮你联网搜搜"):
            return raw
        return f"{prefix}{raw}"

    def _apply_online_search_notice_to_reply(self, value: Optional[Dict[str, object]]) -> Optional[Dict[str, object]]:
        if not isinstance(value, dict):
            return value
        if not self._should_announce_online_search():
            return value
        merged = dict(value)
        merged["text"] = self._prefix_online_search_notice(str(merged.get("text", "")))
        return merged

    def _should_force_online_fallback(self, routed: ToolReply, context: Dict[str, object]) -> bool:
        tool_name = str(getattr(routed, "tool", "") or "").strip().lower()
        if tool_name != "news_headline":
            return False
        ok = bool((routed.meta or {}).get("ok"))
        if ok:
            return False
        if not bool(getattr(self.config, "web_search_enabled", getattr(self.config, "online_search_enabled", True))):
            return False
        tooling = context.get("tooling") if isinstance(context.get("tooling"), dict) else {}
        budget_remaining = int((tooling or {}).get("web_search_budget_remaining", 0))
        return budget_remaining > 0

    def _extract_image_data_urls(self, context: Dict[str, object]) -> List[str]:
        out: List[str] = []
        raw = context.get("attachments")
        if not isinstance(raw, list):
            return out
        for item in raw:
            if not isinstance(item, dict):
                continue
            if str(item.get("kind", "")).strip().lower() != "image":
                continue
            image_data_url = str(item.get("image_data_url", "")).strip()
            if image_data_url.startswith("data:image/"):
                out.append(image_data_url)
        return out[:3]

    def _looks_placeholder_reply(self, text: str) -> bool:
        raw = str(text or "").strip().lower()
        if not raw:
            return True
        patterns = [
            r"我(这就|马上).*(查询|查一下|看看)",
            r"稍等(一下)?(我|，我).*(查询|查找)",
            r"让我.*(先)?(查|查询)",
            r"正在.*(查询|搜索)",
        ]
        return any(re.search(p, raw) for p in patterns)

    def _fallback_news_search_text(self, context: Dict[str, object]) -> str:
        query = self._online_search_query_text(context)
        if not query or not self._is_news_query(query):
            return ""
        try:
            routed = self._tool_router.route(query)
        except Exception:
            return ""
        if not routed.handled:
            return ""
        return self._sanitize_care_text(str(routed.text or ""))

    def _chat_stream_text(self, channel: str, context: Dict[str, object]) -> Iterator[str]:
        messages = self._get_messages(channel)
        self._trim_history(messages)
        user_content = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
        messages.append({"role": "user", "content": user_content})

        local_tool_reply = self._try_local_tool(channel, context)
        force_online_search = False
        if local_tool_reply is not None:
            text = self._sanitize_care_text(local_tool_reply.text)
            force_online_search = self._should_force_online_fallback(local_tool_reply, context)
            if text and not force_online_search:
                messages.append({"role": "assistant", "content": text})
                self._trim_history(messages)
                self.last_error = ""
                self.last_meta = {
                    "online_search_attempted": False,
                    "online_search_used": False,
                    "online_search_fallback": False,
                    "online_search_reason": self._normalize_local_reason(local_tool_reply),
                    "local_tool_used": True,
                    "local_tool_name": local_tool_reply.tool,
                    "local_tool_reason": str(local_tool_reply.meta.get("reason", "")),
                }
                self._log_route(
                    "local_api",
                    str(local_tool_reply.tool or "local_tool"),
                    "ok",
                    str(self.last_meta.get("online_search_reason", "")),
                )
                return iter([text])

        should_search, search_reason = self._should_use_online_search(channel, context)
        if force_online_search:
            should_search = True
            search_reason = "news_api_failed_fallback_web"
        self.last_meta = {
            "online_search_attempted": False,
            "online_search_used": False,
            "online_search_fallback": False,
            "online_search_reason": search_reason,
            "local_tool_used": False,
            "local_tool_name": "",
            "local_tool_reason": "",
        }
        if should_search or self._extract_image_data_urls(context):
            try:
                completion = None
                image_data_urls = self._extract_image_data_urls(context)
                if should_search:
                    self.last_meta["online_search_attempted"] = True
                    completion = self._create_completion_with_web_search(messages)
                    self.last_meta["online_search_used"] = True
                    self.last_meta["online_search_reason"] = "ok"
                elif image_data_urls:
                    try:
                        completion = self._create_completion_with_images(messages, image_data_urls)
                    except Exception:
                        completion = self._create_completion(messages, want_json=False)
                if completion is None:
                    completion = self._create_completion(messages, want_json=False)
                text = self._extract_text_from_completion(completion)
                if self._looks_placeholder_reply(text):
                    plain_completion = self._create_completion(messages, want_json=False)
                    plain_text = self._extract_text_from_completion(plain_completion)
                    if plain_text.strip():
                        text = plain_text
                        self.last_meta["online_search_fallback"] = True
                        self.last_meta["online_search_reason"] = "placeholder_refallback"
                text = self._ensure_final_user_answer(text, channel=channel, context=context, messages=messages)
                text = self._sanitize_care_text(text)
                if self._should_announce_online_search():
                    text = self._prefix_online_search_notice(text)
                if text:
                    messages.append({"role": "assistant", "content": text})
                    self._trim_history(messages)
                    self.last_error = ""
                    return iter([text])
            except Exception as exc:
                self.last_error = str(exc)
                if should_search:
                    self.last_meta["online_search_fallback"] = True
                    self.last_meta["online_search_reason"] = "web_search_tool_unavailable"
                    fallback_news_text = self._fallback_news_search_text(context)
                    if fallback_news_text:
                        if self._should_announce_online_search():
                            fallback_news_text = self._prefix_online_search_notice(fallback_news_text)
                        messages.append({"role": "assistant", "content": fallback_news_text})
                        self._trim_history(messages)
                        self.last_error = ""
                        return iter([fallback_news_text])
                messages.pop()
                return iter(())

        stream_messages = list(messages[:-1])
        stream_hint = (
            "流式回复补充要求：你现在只输出给用户看的最终一句话纯文本，不要 JSON，不要 Markdown，"
            "不要代码块；中文自然简短，不超过100字。"
        )
        if stream_messages and stream_messages[0].get("role") == "system":
            stream_messages[0] = {
                "role": "system",
                "content": f"{stream_messages[0].get('content', '')}\n\n{stream_hint}",
            }
        else:
            stream_messages.insert(0, {"role": "system", "content": stream_hint})
        stream_messages.append(messages[-1])

        try:
            stream = self._create_stream(stream_messages)
        except Exception as exc:
            self.last_error = str(exc)
            messages.pop()
            return iter(())

        def iterator() -> Iterator[str]:
            accumulated = ""
            try:
                for chunk in stream:
                    piece = self._extract_stream_piece(chunk)

                    if piece:
                        accumulated += piece
                        yield piece
            finally:
                if accumulated.strip():
                    messages.append({"role": "assistant", "content": accumulated})
                    self._trim_history(messages)
                    self.last_error = ""
                else:
                    self.last_error = "llm_stream_empty"
                    messages.pop()

        return iterator()

    def _is_news_query(self, query: str) -> bool:
        q = str(query or "").strip().lower()
        if not q:
            return False
        return bool(
            re.search(
                r"(新闻|头条|热点|快讯|热搜|latest news|breaking news|news|headline)",
                q,
                flags=re.IGNORECASE,
            )
        )

    def _is_local_or_standard_api_query(self, query: str) -> bool:
        q = str(query or "").strip().lower()
        if not q:
            return False
        local_or_api_patterns = [
            r"(几号|星期|周几|几点|时间|日期|today|date|time)",
            r"(天气|气温|温度|下雨|降雨|台风|空气质量|weather|temperature|冷不冷|热不热|穿什么)",
            r"(汇率|美元|人民币|exchange rate|fx)",
            r"(股票|股价|指数|btc|eth|fund|price)",
            r"(网易云|听歌|播放音乐|打开音乐)",
        ]
        if any(re.search(p, q, flags=re.IGNORECASE) for p in local_or_api_patterns):
            return True
        if self._is_news_query(q):
            return not bool(getattr(self.config, "web_search_news_default", False))
        return False

    def _is_high_value_complex_query(self, query: str) -> bool:
        q = str(query or "").strip().lower()
        if not q:
            return False
        high_value_patterns = [
            r"(附近|本地|周边).*(心理|咨询|活动|线下|机构|援助)",
            r"(心理健康|焦虑|抑郁|压力).*(活动|资源|机构|政策|指南)",
            r"(政策|法规|新规|变化|调整|解读)",
            r"(行业|就业|裁员|趋势|前景|研判|分析)",
            r"(最近|最新).*(发生什么|怎么了|进展|变化|影响)",
            r"(深度|多角度|综合|归纳|对比).*(分析|解读|总结)",
        ]
        return any(re.search(p, q, flags=re.IGNORECASE) for p in high_value_patterns)

    def _looks_tool_call_leak(self, text: str) -> bool:
        raw = str(text or "").strip()
        if not raw:
            return False
        patterns = [
            r'"function_call"\s*:',
            r'"tool_call"\s*:',
            r"\bweb_search\b",
            r"^\s*\{[\s\S]*\}\s*$",
            r"^\s*\[[\s\S]*\]\s*$",
            r"^```(?:json)?",
        ]
        return any(re.search(p, raw, flags=re.IGNORECASE) for p in patterns)

    def _ensure_final_user_answer(
        self,
        text: str,
        channel: str,
        context: Dict[str, object],
        messages: List[Dict[str, str]],
    ) -> str:
        candidate = str(text or "").strip()
        if not candidate:
            return ""
        if not self._looks_tool_call_leak(candidate):
            return candidate

        self.last_meta["online_search_fallback"] = True
        self.last_meta["online_search_reason"] = "function_call_blocked_and_rewritten"

        query = self._online_search_query_text(context)
        if self._is_news_query(query):
            news_tool = self._tool_router.route(query)
            if news_tool.handled and str(news_tool.text or "").strip():
                return str(news_tool.text or "").strip()

        try:
            repair_messages = list(messages)
            repair_messages.append({"role": "assistant", "content": candidate[:800]})
            repair_messages.append(
                {
                    "role": "user",
                    "content": (
                        "上面是工具调用或JSON草稿。"
                        "请直接输出给用户的最终中文答复，不要函数调用、不要JSON、不要代码块。"
                    ),
                }
            )
            repaired = self._create_completion(repair_messages, want_json=False)
            repaired_text = self._extract_text_from_completion(repaired).strip()
            if repaired_text and not self._looks_tool_call_leak(repaired_text):
                return repaired_text
        except Exception as exc:
            self.last_error = str(exc)

        return "我已经查到信息，但工具返回格式异常。你可以再问一次，我会直接给你结论。"

    def _parse_json(self, content: str) -> Optional[Dict[str, object]]:
        if not content:
            return None
        try:
            value = json.loads(content)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass

        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            try:
                value = json.loads(content[start : end + 1])
                if isinstance(value, dict):
                    return value
            except json.JSONDecodeError:
                return None
        return None

    def _get_messages(self, channel: str) -> List[Dict[str, str]]:
        if channel not in self._messages_by_key:
            messages: List[Dict[str, str]] = []
            prompt = self._prompts.get(channel, "")
            if prompt:
                messages.append({"role": "system", "content": f"{prompt}\n\n{self._runtime_policy_addendum()}"})
            self._messages_by_key[channel] = messages
        return self._messages_by_key[channel]

    def _trim_history(self, messages: List[Dict[str, str]]) -> None:
        if not messages:
            return
        has_system = messages and messages[0].get("role") == "system"
        start = 1 if has_system else 0
        tail_len = len(messages) - start
        if tail_len <= self._max_history_messages:
            return
        drop = tail_len - self._max_history_messages
        del messages[start : start + drop]

    def _runtime_policy_addendum(self) -> str:
        return (
            "调用策略附加规则：\n"
            "1) 保持 system prompt 原意，不改角色设定。\n"
            "2) 关闭思考模式：不输出思考过程、推理草稿或中间步骤，只输出最终可读回答。\n"
            "3) 时间/日期/天气/汇率/股票/系统动作优先本地工具或标准API，给出最终结果，不要只说“我去查询”。\n"
            "4) 本轮新闻问题优先联网搜索；触发联网搜索时，回答开头明确写“我帮你联网搜搜：”。\n"
            "5) expression_modality 是算法信号，不是用户原话；回复时可参考其标签与置信度调整语气。\n"
            "6) 常识、稳定知识、闲聊问题直接回答，禁止误触发 web_search。\n"
            "7) 绝不把 function_call/tool_call/json 草稿直接展示给用户，必须输出最终自然语言答案。\n"
            "8) 涉及系统工具执行（如播放音乐）时，只能基于执行回执给结论，禁止臆测“已完成”。\n"
        )

    def _init_client(self) -> None:
        if not self.enabled or self.config.call_mode != "client_direct":
            return
        api_key = self.config.api_key or os.environ.get(self.config.api_key_env)
        if not api_key:
            self.enabled = False
            return
        timeout_sec = max(1, int(self.config.timeout_ms / 1000))
        provider = self._resolve_provider()
        if provider == "ark":
            try:
                from volcenginesdkarkruntime import Ark  # type: ignore

                ark_kwargs: Dict[str, Any] = {
                    "api_key": api_key,
                    "base_url": self.config.base_url,
                }
                try:
                    self._client = Ark(timeout=timeout_sec, **ark_kwargs)
                except TypeError:
                    self._client = Ark(**ark_kwargs)
                if hasattr(self._client, "chat") and hasattr(self._client.chat, "completions"):
                    self._client_mode = "chat_completions"
                else:
                    self._client_mode = "responses_api"
                return
            except Exception:
                # Fall through to OpenAI-compatible path.
                pass
        try:
            from openai import OpenAI  # type: ignore

            self._client = OpenAI(api_key=api_key, base_url=self.config.base_url, timeout=timeout_sec)
            self._client_mode = "chat_completions"
        except Exception:
            self.enabled = False
            return

    def _resolve_provider(self) -> str:
        raw = str(getattr(self.config, "provider", "auto") or "auto").strip().lower()
        if raw in {"ark", "openai"}:
            return raw
        base = str(self.config.base_url or "").lower()
        if "volces.com" in base:
            return "ark"
        return "openai"

    def _build_request_kwargs(
        self, messages: List[Dict[str, str]], stream: bool = False, want_json: bool = False
    ) -> Dict[str, Any]:
        request_kwargs: Dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
        }
        if stream:
            request_kwargs["stream"] = True
        if self.config.top_p > 0:
            request_kwargs["top_p"] = self.config.top_p
        if self.config.max_completion_tokens > 0:
            request_kwargs["max_tokens"] = self.config.max_completion_tokens
        if want_json and self.config.response_format:
            request_kwargs["response_format"] = {"type": self.config.response_format}
        return request_kwargs

    def _to_responses_input(self, messages: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for m in messages:
            role = str(m.get("role", "user"))
            text = str(m.get("content", ""))
            out.append(
                {
                    "role": role,
                    "content": [{"type": "input_text", "text": text}],
                }
            )
        return out

    def _create_completion(self, messages: List[Dict[str, str]], want_json: bool = False):
        if not self._client:
            raise RuntimeError("llm client unavailable")
        last_exc: Optional[Exception] = None
        for attempt in range(2):
            try:
                if self._client_mode == "chat_completions":
                    kwargs = self._build_request_kwargs(messages, stream=False, want_json=want_json)
                    try:
                        return self._client.chat.completions.create(**kwargs)
                    except Exception:
                        if "response_format" in kwargs:
                            kwargs.pop("response_format", None)
                            return self._client.chat.completions.create(**kwargs)
                        raise
                # Ark responses API fallback.
                kwargs = {
                    "model": self.config.model,
                    "input": self._to_responses_input(messages),
                    "temperature": self.config.temperature,
                }
                if self.config.top_p > 0:
                    kwargs["top_p"] = self.config.top_p
                if self.config.max_completion_tokens > 0:
                    kwargs["max_output_tokens"] = self.config.max_completion_tokens
                return self._client.responses.create(**kwargs)
            except Exception as exc:
                last_exc = exc
                if attempt == 0 and self._is_retryable_error(exc):
                    continue
                raise
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("llm_completion_failed_without_exception")

    def _create_completion_with_images(self, messages: List[Dict[str, str]], image_data_urls: List[str]):
        if not self._client:
            raise RuntimeError("llm client unavailable")
        responses_api = getattr(self._client, "responses", None)
        if responses_api is None or not hasattr(responses_api, "create"):
            raise RuntimeError("llm_multimodal_unsupported:responses_api_missing")
        input_items = self._to_responses_input(messages)
        if input_items and image_data_urls:
            content = input_items[-1].get("content")
            if isinstance(content, list):
                for img in image_data_urls[:3]:
                    if isinstance(img, str) and img.startswith("data:image/"):
                        content.append({"type": "input_image", "image_url": img})
        kwargs: Dict[str, Any] = {
            "model": self.config.model,
            "input": input_items,
            "temperature": self.config.temperature,
        }
        if self.config.top_p > 0:
            kwargs["top_p"] = self.config.top_p
        if self.config.max_completion_tokens > 0:
            kwargs["max_output_tokens"] = self.config.max_completion_tokens
        return responses_api.create(**kwargs)

    def _create_completion_with_web_search(self, messages: List[Dict[str, str]]):
        if not self._client:
            raise RuntimeError("llm client unavailable")
        responses_api = getattr(self._client, "responses", None)
        if responses_api is None or not hasattr(responses_api, "create"):
            raise RuntimeError("llm_web_search_unsupported:responses_api_missing")

        model_name = str(
            getattr(self.config, "web_search_model", "")
            or getattr(self.config, "online_search_model", "")
            or self.config.model
        )
        kwargs: Dict[str, Any] = {
            "model": model_name,
            "input": self._to_responses_input(messages),
            "tools": [{"type": "web_search"}],
            "temperature": self.config.temperature,
        }
        if self.config.top_p > 0:
            kwargs["top_p"] = self.config.top_p
        if self.config.max_completion_tokens > 0:
            kwargs["max_output_tokens"] = self.config.max_completion_tokens
        timeout_ms = int(
            getattr(self.config, "web_search_timeout_ms", getattr(self.config, "online_search_timeout_ms", 8000))
            or 0
        )
        if timeout_ms > 0:
            kwargs["timeout"] = max(1.0, float(timeout_ms) / 1000.0)

        try:
            return responses_api.create(**kwargs)
        except TypeError:
            kwargs.pop("timeout", None)
            return responses_api.create(**kwargs)
        except Exception as exc:
            msg = str(exc or "").lower()
            unsupported = (
                "web_search" in msg
                or "tool" in msg
                or "tools" in msg
                or "unsupported" in msg
                or "not support" in msg
            )
            if bool(getattr(self.config, "online_search_require_supported_tool", False)) and unsupported:
                raise RuntimeError(f"llm_web_search_required_but_unsupported:{exc}") from exc
            raise

    def _create_stream(self, messages: List[Dict[str, str]]):
        if not self._client:
            raise RuntimeError("llm client unavailable")
        if self._client_mode == "chat_completions":
            kwargs = self._build_request_kwargs(messages, stream=True, want_json=False)
            return self._client.chat.completions.create(**kwargs)
        kwargs: Dict[str, Any] = {
            "model": self.config.model,
            "input": self._to_responses_input(messages),
            "temperature": self.config.temperature,
            "stream": True,
        }
        if self.config.top_p > 0:
            kwargs["top_p"] = self.config.top_p
        if self.config.max_completion_tokens > 0:
            kwargs["max_output_tokens"] = self.config.max_completion_tokens
        return self._client.responses.create(**kwargs)

    def _extract_text_from_completion(self, completion: Any) -> str:
        try:
            content = completion.choices[0].message.content or ""
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts: List[str] = []
                for item in content:
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        parts.append(item["text"])
                return "".join(parts)
        except Exception:
            pass
        out_text = getattr(completion, "output_text", None)
        if isinstance(out_text, str):
            return out_text
        output = getattr(completion, "output", None)
        if isinstance(output, list):
            parts: List[str] = []
            for item in output:
                try:
                    content = getattr(item, "content", None) or item.get("content")
                except Exception:
                    content = None
                if isinstance(content, list):
                    for c in content:
                        text = None
                        if isinstance(c, dict):
                            text = c.get("text")
                        else:
                            text = getattr(c, "text", None)
                        if isinstance(text, str):
                            parts.append(text)
            if parts:
                return "".join(parts)
        return ""

    def _extract_stream_piece(self, chunk: Any) -> str:
        # OpenAI / Ark chat.completions style
        try:
            delta = chunk.choices[0].delta.content
            if isinstance(delta, str):
                return delta
            if isinstance(delta, list):
                parts: List[str] = []
                for item in delta:
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        parts.append(item["text"])
                    else:
                        text = getattr(item, "text", None)
                        if isinstance(text, str):
                            parts.append(text)
                return "".join(parts)
        except Exception:
            pass
        # Ark responses stream events style
        for key in ("delta", "output_text", "text"):
            try:
                val = getattr(chunk, key, None)
            except Exception:
                val = None
            if isinstance(val, str) and val:
                return val
        if isinstance(chunk, dict):
            if isinstance(chunk.get("delta"), str):
                return chunk["delta"]
            if isinstance(chunk.get("text"), str):
                return chunk["text"]
        return ""

    def _load_prompts(self) -> None:
        self._prompts["care"] = self._read_prompt(self.config.system_prompt_path)
        self._prompts["summary"] = self._read_prompt(self.config.summary_prompt_path)

    def _read_prompt(self, path: str) -> str:
        prompt_path = self._resolve_path(path)
        if not prompt_path:
            return ""
        try:
            return prompt_path.read_text(encoding="utf-8").strip()
        except Exception:
            return ""

    def _resolve_path(self, path: str) -> Optional[Path]:
        raw = Path(path)
        if raw.is_absolute() and raw.exists():
            return raw
        repo_root = Path(__file__).resolve().parents[2]
        engine_root = Path(__file__).resolve().parents[1]
        candidates = [raw, repo_root / raw, engine_root / raw]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return repo_root / raw

    def _validate_response(
        self, channel: str, value: Optional[Dict[str, object]]
    ) -> Optional[Dict[str, object]]:
        if not isinstance(value, dict):
            return None
        if channel == "care":
            return self._validate_care_reply(value)
        if channel == "summary":
            return self._validate_summary_reply(value)
        return value

    def _validate_care_reply(self, value: Dict[str, object]) -> Optional[Dict[str, object]]:
        text = self._sanitize_care_text(str(value.get("text", "")))
        if not text:
            return None
        followup = value.get("followup_question", "")
        followup_text = self._sanitize_care_text(str(followup) if followup is not None else "")
        style = str(value.get("style", "warm")).strip()
        if style not in {"warm", "neutral", "cheerful", "serious"}:
            style = "warm"
        text = self._trim_text(text, 100)
        followup_text = self._trim_text(followup_text, 40)
        return {
            "text": text,
            "followup_question": followup_text,
            "style": style,
        }

    def _validate_summary_reply(self, value: Dict[str, object]) -> Optional[Dict[str, object]]:
        summary = str(value.get("summary", "")).strip()
        if not summary:
            return None
        highlights_raw = value.get("highlights")
        if not isinstance(highlights_raw, list):
            return None
        highlights: List[str] = []
        for item in highlights_raw:
            item_text = str(item).strip()
            if item_text:
                highlights.append(item_text)
        if len(highlights) < 3:
            return None
        return {
            "summary": summary,
            "highlights": highlights[:5],
        }

    @staticmethod
    def _trim_text(value: str, max_len: int) -> str:
        if not value:
            return ""
        cleaned = value.replace("\n", " ").strip()
        if len(cleaned) <= max_len:
            return cleaned
        return cleaned[:max_len].rstrip()

    def _sanitize_care_text(self, value: str) -> str:
        text = str(value or "")
        if not text:
            return ""
        text = re.sub(r"(?is)<think>.*?</think>", " ", text)
        text = re.sub(r"(?im)^\s*(思考过程|推理过程|analysis|reasoning)\s*[:：].*$", " ", text)
        text = re.sub(r"(?im)^\s*(function_call|tool_call)\s*[:：].*$", " ", text)
        text = re.sub(r'(?is)\{\s*"function_call"\s*:\s*\{.*?\}\s*\}', " ", text)
        text = re.sub(r'(?is)\{\s*"tool_call"\s*:\s*\{.*?\}\s*\}', " ", text)
        # Fallback cleanup for common emoji-tag formats.
        text = re.sub(r"\[(?:[^\[\]\n]{1,12})\]", " ", text)
        text = re.sub(r"【(?:[^【】\n]{1,12})】", " ", text)
        text = re.sub(r"^```(?:json)?|```$", " ", text, flags=re.IGNORECASE)
        text = text.replace("\r", " ").replace("\n", " ").strip()
        return re.sub(r"\s{2,}", " ", text).strip()

    def _is_retryable_error(self, exc: Exception) -> bool:
        msg = str(exc or "").lower()
        name = exc.__class__.__name__.lower()
        if "timeout" in msg or "timed out" in msg:
            return True
        if "connection" in msg or "temporarily" in msg or "try again" in msg:
            return True
        if "apitimeouterror" in name or "apiconnectionerror" in name:
            return True
        # Retry once on transient 429/5xx.
        if ("429" in msg) or ("rate limit" in msg) or ("toomanyrequests" in msg):
            return True
        if ("500" in msg) or ("502" in msg) or ("503" in msg) or ("504" in msg):
            return True
        return False
