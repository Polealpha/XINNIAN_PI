from __future__ import annotations

import datetime as _dt
import html
import json as _json
import os
import re
import subprocess
import webbrowser
from dataclasses import dataclass
from typing import Dict, Optional, Tuple
from urllib.parse import quote_plus
from xml.etree import ElementTree as ET

import httpx


WEATHER_CODE_TEXT: Dict[int, str] = {
    0: "晴",
    1: "基本晴",
    2: "少云",
    3: "阴",
    45: "雾",
    48: "冻雾",
    51: "小毛雨",
    53: "毛雨",
    55: "大毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    80: "阵雨",
    81: "强阵雨",
    82: "暴雨",
    95: "雷暴",
}

_CURRENCY_NAME_TO_CODE: Dict[str, str] = {
    "美元": "USD",
    "美金": "USD",
    "usd": "USD",
    "人民币": "CNY",
    "rmb": "CNY",
    "cny": "CNY",
    "欧元": "EUR",
    "eur": "EUR",
    "日元": "JPY",
    "jpy": "JPY",
    "港币": "HKD",
    "hkd": "HKD",
    "英镑": "GBP",
    "gbp": "GBP",
}

_STOCK_NAME_TO_SYMBOL: Dict[str, str] = {
    "苹果": "AAPL",
    "apple": "AAPL",
    "特斯拉": "TSLA",
    "tesla": "TSLA",
    "英伟达": "NVDA",
    "nvidia": "NVDA",
    "微软": "MSFT",
    "microsoft": "MSFT",
    "谷歌": "GOOGL",
    "google": "GOOGL",
    "亚马逊": "AMZN",
    "amazon": "AMZN",
}

_INDEX_QUERY_TO_SINA: Dict[str, str] = {
    "纳斯达克": "gb_ixic",
    "纳指": "gb_ixic",
    "nasdaq": "gb_ixic",
    "道琼斯": "gb_dji",
    "djia": "gb_dji",
    "标普500": "gb_inx",
    "标普": "gb_inx",
    "s&p": "gb_inx",
    "上证": "s_sh000001",
    "上证指数": "s_sh000001",
    "深证": "sz399001",
    "深证成指": "sz399001",
}


@dataclass
class ToolResult:
    ok: bool
    text: str
    reason: str = ""


def datetime_reply() -> ToolResult:
    now = _dt.datetime.now()
    week_map = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    week = week_map[now.weekday()]
    return ToolResult(ok=True, text=f"现在是 {now:%Y年%m月%d日} {week} {now:%H:%M}。", reason="datetime")


def extract_city(text: str) -> str:
    q = str(text or "").strip()
    q = re.sub(r"(今天|明天|后天|这会儿|现在)", "", q)
    blocked_tokens = {"帮我查", "查一下", "查下", "看看", "看下", "告诉我", "天气", "气温", "温度", "这里"}
    patterns = [
        r"([\u4e00-\u9fa5]{2,10})(?:天气|温度|气温)",
        r"(?:在|到)\s*([\u4e00-\u9fa5]{2,10})(?:天气|温度|气温)?",
    ]
    for pat in patterns:
        m = re.search(pat, q)
        if m:
            city = str(m.group(1) or "").strip()
            if city and city not in blocked_tokens and len(city) <= 6:
                return city
    return ""


def _reverse_geocode_city(lat: float, lon: float, timeout_sec: float = 5.0) -> str:
    with httpx.Client(timeout=timeout_sec) as client:
        geo = client.get(
            "https://geocoding-api.open-meteo.com/v1/reverse",
            params={
                "latitude": float(lat),
                "longitude": float(lon),
                "count": 1,
                "language": "zh",
                "format": "json",
            },
        )
        geo.raise_for_status()
        data = geo.json() if geo.text else {}
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list) or not results or not isinstance(results[0], dict):
            return ""
        return str(results[0].get("name") or "").strip()


def _infer_city_from_windows_location(timeout_sec: float = 4.0) -> Tuple[str, Optional[float], Optional[float]]:
    if os.name != "nt":
        return "", None, None
    script = (
        "$ErrorActionPreference='Stop';"
        "Add-Type -AssemblyName System.Runtime.WindowsRuntime;"
        "$null=[Windows.Devices.Geolocation.Geolocator,Windows.Devices.Geolocation,ContentType=WindowsRuntime];"
        "$geo=New-Object Windows.Devices.Geolocation.Geolocator;"
        "$op=$geo.GetGeopositionAsync();"
        "$task=[System.WindowsRuntimeSystemExtensions]::AsTask($op);"
        "$task.Wait(2500) | Out-Null;"
        "if(-not $task.IsCompleted){exit 3};"
        "$p=$task.Result.Coordinate.Point.Position;"
        "Write-Output (ConvertTo-Json @{lat=$p.Latitude; lon=$p.Longitude} -Compress);"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=max(2, int(timeout_sec)),
            check=False,
        )
        if proc.returncode != 0:
            return "", None, None
        raw = str(proc.stdout or "").strip()
        if not raw:
            return "", None, None
        value = _json.loads(raw)
        lat = float(value.get("lat"))
        lon = float(value.get("lon"))
        return "windows_location", lat, lon
    except Exception:
        return "", None, None


def _fetch_weather_by_latlon(
    city_name: str,
    lat: float,
    lon: float,
    timeout_sec: float = 5.0,
) -> ToolResult:
    with httpx.Client(timeout=timeout_sec) as client:
        weather = client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": float(lat),
                "longitude": float(lon),
                "current": "temperature_2m,weather_code,wind_speed_10m",
                "timezone": "auto",
            },
        )
        weather.raise_for_status()
        weather_data = weather.json() if weather.text else {}
        current = weather_data.get("current") if isinstance(weather_data, dict) else None
        if not isinstance(current, dict):
            return ToolResult(ok=False, text=f"{city_name}天气服务暂时不可用。", reason="weather_current_empty")

        temp = current.get("temperature_2m")
        wind = current.get("wind_speed_10m")
        code = int(current.get("weather_code", -1))
        desc = WEATHER_CODE_TEXT.get(code, "天气未知")
        if temp is None:
            return ToolResult(ok=False, text=f"{city_name}天气服务暂时不可用。", reason="weather_temp_empty")
        temp_text = f"{float(temp):.1f}".rstrip("0").rstrip(".")
        wind_text = ""
        try:
            wind_text = f"，风速 {float(wind):.0f}km/h"
        except Exception:
            wind_text = ""
        return ToolResult(ok=True, text=f"{city_name}当前{desc}，气温 {temp_text}℃{wind_text}。", reason="weather")


def weather_reply(query_text: str, timeout_sec: float = 5.0) -> ToolResult:
    city = extract_city(query_text)
    try:
        if city:
            with httpx.Client(timeout=timeout_sec) as client:
                geo = client.get(
                    "https://geocoding-api.open-meteo.com/v1/search",
                    params={"name": city, "count": 1, "language": "zh", "format": "json"},
                )
                geo.raise_for_status()
                geo_data = geo.json() if geo.text else {}
                results = geo_data.get("results") if isinstance(geo_data, dict) else None
                if not isinstance(results, list) or not results:
                    return ToolResult(ok=False, text=f"暂时没定位到“{city}”，你可以换个城市名试试。", reason="weather_geo_empty")

                item = results[0] if isinstance(results[0], dict) else {}
                lat = float(item.get("latitude"))
                lon = float(item.get("longitude"))
                city_name = str(item.get("name") or city)
            return _fetch_weather_by_latlon(city_name, lat, lon, timeout_sec=timeout_sec)

        source, lat, lon = _infer_city_from_windows_location(timeout_sec=timeout_sec)
        city_name = ""
        if lat is not None and lon is not None:
            city_name = _reverse_geocode_city(lat, lon, timeout_sec=timeout_sec) or "当前位置"
            result = _fetch_weather_by_latlon(city_name, lat, lon, timeout_sec=timeout_sec)
            if result.ok:
                result.reason = f"weather_auto_{source}"
            return result

        return ToolResult(
            ok=False,
            text="我暂时拿不到你当前城市定位。你可以直接说“北京天气”或“上海天气”；如果希望自动定位，请打开 Windows 的“位置服务”。",
            reason="weather_geo_unknown",
        )
    except Exception as exc:
        hint_city = city or "当前地区"
        return ToolResult(ok=False, text=f"{hint_city}天气服务暂时不可用。", reason=f"weather_error:{exc}")


def _extract_news_topic(query_text: str) -> str:
    q = str(query_text or "").strip()
    q_lc = q.lower()
    if "中国" in q:
        if "财经" in q or "经济" in q:
            return "中国 财经 新闻"
        return "中国 新闻"
    if "美国" in q:
        if "科技" in q:
            return "美国 科技 新闻"
        return "美国 新闻"
    if "国际" in q:
        return "国际 新闻"
    if "热点" in q or "热搜" in q:
        return "今日 热点"
    if "财经" in q or "股市" in q:
        return "财经 新闻"
    if "体育" in q:
        return "体育 新闻"
    if "娱乐" in q:
        return "娱乐 新闻"

    q = re.sub(r"[，。！？、,.!?]+", " ", q)
    q = re.sub(
        r"(今天|最近|最新|请|帮我|给我|一下|看看|查询|查下|播报|说说|你能|可不可以|帮忙|我想|我想看|给我看)",
        " ",
        q,
        flags=re.IGNORECASE,
    )
    q = re.sub(r"(新闻|头条|热点|快讯|热搜|有啥|有什么|吗)", " ", q, flags=re.IGNORECASE)
    q = re.sub(r"\s{2,}", " ", q).strip()
    q = q.strip(" ?？")
    if not q:
        return "今日 热点"
    return f"{q} 新闻"


def news_headline_reply(query_text: str, timeout_sec: float = 6.0, max_items: int = 3) -> ToolResult:
    topic = _extract_news_topic(query_text)
    try:
        with httpx.Client(timeout=timeout_sec, follow_redirects=True) as client:
            resp = client.get(
                "https://www.bing.com/news/search",
                params={"q": topic, "format": "rss", "setlang": "zh-Hans"},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            resp.raise_for_status()
            xml_text = str(resp.text or "").strip()
        if not xml_text:
            return ToolResult(ok=False, text="新闻服务暂时不可用，请稍后再试。", reason="news_empty")

        root = ET.fromstring(xml_text)
        items = root.findall(".//item")
        headlines = []
        for item in items[: max(1, int(max_items))]:
            title = (item.findtext("title") or "").strip()
            if title:
                desc = (item.findtext("description") or "").strip()
                source = ""
                for child in list(item):
                    if str(child.tag).endswith("Source"):
                        source = str(child.text or "").strip()
                        break
                merged = title
                if source:
                    merged = f"{merged}（{source}）"
                if desc:
                    merged = f"{merged}：{desc}"
                headlines.append(html.unescape(merged))
        if not headlines:
            return ToolResult(ok=False, text="暂时没有抓到可用新闻，你可以换个关键词。", reason="news_no_items")
        numbered = "；".join([f"{i + 1}. {t}" for i, t in enumerate(headlines[:max_items])])
        return ToolResult(ok=True, text=f"我帮你联网搜搜：{numbered}", reason="news_web_search_used")
    except Exception as exc:
        return ToolResult(ok=False, text="新闻服务暂时不可用，请稍后再试。", reason=f"news_error:{exc}")


def _extract_currency_codes(query_text: str) -> Tuple[str, str]:
    q = str(query_text or "").strip()
    q_lc = q.lower()
    for name, code in _CURRENCY_NAME_TO_CODE.items():
        if name in q_lc:
            q_lc = q_lc.replace(name, f" {code.lower()} ")
    codes = re.findall(r"\b[A-Z]{3}\b", q_lc.upper())
    if len(codes) >= 2:
        return codes[0], codes[1]
    if "美元" in q or "USD" in q.upper():
        return "USD", "CNY"
    if "欧元" in q or "EUR" in q.upper():
        return "EUR", "CNY" if ("人民币" in q or "CNY" in q.upper()) else "USD"
    if "日元" in q or "JPY" in q.upper():
        return "JPY", "CNY" if ("人民币" in q or "CNY" in q.upper()) else "USD"
    return "USD", "CNY"


def fx_reply(query_text: str, timeout_sec: float = 5.0) -> ToolResult:
    base, quote = _extract_currency_codes(query_text)
    try:
        with httpx.Client(timeout=timeout_sec, follow_redirects=True) as client:
            resp = client.get("https://api.frankfurter.app/latest", params={"from": base, "to": quote})
            resp.raise_for_status()
            data = resp.json() if resp.text else {}
        rates = data.get("rates") if isinstance(data, dict) else None
        rate = rates.get(quote) if isinstance(rates, dict) else None
        if rate is None:
            return ToolResult(ok=False, text="汇率服务暂时不可用，请稍后再试。", reason="fx_api_empty")
        rate_val = float(rate)
        date_key = str(data.get("date", "")).strip()
        suffix = f"（{date_key}）" if date_key else ""
        return ToolResult(ok=True, text=f"当前 1 {base} 约等于 {rate_val:.4f} {quote}{suffix}。", reason="fx_api_used")
    except Exception as exc:
        return ToolResult(ok=False, text="汇率服务暂时不可用，请稍后再试。", reason=f"fx_api_error:{exc}")


def _resolve_stock_target(query_text: str) -> Tuple[str, str]:
    q = str(query_text or "").strip()
    q_lc = q.lower()
    for phrase, code in _INDEX_QUERY_TO_SINA.items():
        if phrase in q_lc:
            return code, phrase
    for name, symbol in _STOCK_NAME_TO_SYMBOL.items():
        if name in q_lc:
            return f"gb_{symbol.lower()}", symbol
    m = re.search(r"\b([A-Za-z]{1,6})\b", q)
    if m:
        symbol = str(m.group(1)).upper()
        return f"gb_{symbol.lower()}", symbol
    return "gb_aapl", "AAPL"


def _fetch_sina_quote(code: str, timeout_sec: float = 6.0) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://finance.sina.com.cn/",
        "Accept": "*/*",
    }
    with httpx.Client(timeout=timeout_sec, follow_redirects=True) as client:
        resp = client.get("https://hq.sinajs.cn/list=" + str(code), headers=headers)
        resp.raise_for_status()
        return str(resp.text or "").strip()


def _parse_sina_fields(raw: str) -> Tuple[str, list]:
    m = re.search(r'="(.*)"', raw)
    if not m:
        return "", []
    body = str(m.group(1) or "").strip()
    if not body:
        return "", []
    parts = [str(x).strip() for x in body.split(",")]
    if not parts:
        return "", []
    return parts[0], parts


def _sina_stock_reply(query_text: str, timeout_sec: float = 6.0) -> ToolResult:
    code, label = _resolve_stock_target(query_text)
    try:
        raw = _fetch_sina_quote(code, timeout_sec=timeout_sec)
        name, parts = _parse_sina_fields(raw)
        if not parts:
            return ToolResult(ok=False, text=f"{label} 行情服务暂时不可用。", reason="stock_api_empty")
        display = name or label
        # US quote format: name,price,pct,date time,change,...
        if code.startswith("gb_"):
            if len(parts) < 5:
                return ToolResult(ok=False, text=f"{display} 暂时没拿到行情。", reason="stock_api_empty")
            try:
                price = float(parts[1])
            except Exception:
                return ToolResult(ok=False, text=f"{display} 暂时没拿到行情。", reason="stock_api_empty_price")
            pct = str(parts[2] or "").strip()
            dt = str(parts[3] or "").strip()
            delta = str(parts[4] or "").strip()
            pct_text = f"，涨跌 {pct}%" if pct not in {"", "--"} else ""
            delta_text = f"（{delta}）" if delta not in {"", "--"} else ""
            time_text = f"（{dt}）" if dt else ""
            return ToolResult(
                ok=True,
                text=f"{display} 当前约 {price:.2f}{pct_text}{delta_text}{time_text}。",
                reason="stock_api_used",
            )
        # CN index format: name,current,change,pct,...
        if len(parts) >= 4:
            try:
                current = float(parts[1])
            except Exception:
                current = None
            change = str(parts[2] or "").strip()
            pct = str(parts[3] or "").strip()
            if current is not None:
                pct_text = f"，涨跌 {pct}%" if pct else ""
                change_text = f"（{change}）" if change else ""
                return ToolResult(
                    ok=True,
                    text=f"{display} 当前约 {current:.2f}{pct_text}{change_text}。",
                    reason="stock_api_used",
                )
        return ToolResult(ok=False, text=f"{display} 暂时没拿到行情。", reason="stock_api_empty")
    except Exception as exc:
        return ToolResult(ok=False, text=f"{label} 行情服务暂时不可用。", reason=f"stock_api_error:{exc}")


def stock_reply(query_text: str, api_key: str = "", timeout_sec: float = 6.0) -> ToolResult:
    # Prefer Sina quote API because it is stable in the current CN network environment.
    sina = _sina_stock_reply(query_text, timeout_sec=timeout_sec)
    if sina.ok:
        return sina

    symbol = _resolve_stock_target(query_text)[1]
    key = str(api_key or "").strip() or "demo"
    try:
        with httpx.Client(timeout=timeout_sec, follow_redirects=True) as client:
            resp = client.get(
                "https://www.alphavantage.co/query",
                params={"function": "GLOBAL_QUOTE", "symbol": symbol, "apikey": key},
            )
            resp.raise_for_status()
            data = resp.json() if resp.text else {}
        if not isinstance(data, dict):
            return ToolResult(ok=False, text="股票服务暂时不可用，请稍后再试。", reason="stock_api_invalid")
        note = str(data.get("Note", "") or data.get("Information", "")).strip()
        if note:
            return ToolResult(ok=False, text=f"{symbol} 行情服务当前限流，请稍后再试。", reason="stock_api_limited")
        quote = data.get("Global Quote")
        if not isinstance(quote, dict):
            return ToolResult(ok=False, text=f"暂时没拿到 {symbol} 的行情。", reason="stock_api_empty")
        price_raw = quote.get("05. price")
        change_pct_raw = quote.get("10. change percent")
        if price_raw in (None, ""):
            return ToolResult(ok=False, text=f"暂时没拿到 {symbol} 的行情。", reason="stock_api_empty_price")
        price = float(price_raw)
        change_pct = str(change_pct_raw or "").strip()
        pct_text = f"，涨跌 {change_pct}" if change_pct else ""
        return ToolResult(ok=True, text=f"{symbol} 当前价格约 {price:.2f} 美元{pct_text}。", reason="stock_api_used")
    except Exception:
        return sina


def open_music_reply(song: str = "") -> ToolResult:
    song = str(song or "").strip()
    try:
        opened_app = False
        if os.name == "nt":
            try:
                os.startfile("orpheus://")  # type: ignore[attr-defined]
                opened_app = True
            except Exception:
                opened_app = False
        if song:
            query_url = f"https://music.163.com/#/search/m/?s={quote_plus(song)}&type=1"
            webbrowser.open(query_url, new=2)
            if opened_app:
                return ToolResult(ok=True, text=f"已打开网易云并定位“{song}”搜索结果，请点第一条开始播放。", reason="local_tool_music_start_ok")
            return ToolResult(ok=True, text=f"我已打开网易云搜索页，你可以点“{song}”开始播放。", reason="local_tool_music_start_partial")
        if opened_app:
            return ToolResult(ok=True, text="已打开网易云音乐，你可以直接说想听的歌。", reason="local_tool_music_start_ok")
    except Exception:
        pass
    try:
        webbrowser.open("https://music.163.com/", new=2)
        return ToolResult(ok=True, text="已为你打开网易云音乐网页。", reason="local_tool_music_start_partial")
    except Exception as exc:
        return ToolResult(ok=False, text="我没能打开网易云，你可以手动打开试试。", reason=f"local_tool_music_start_failed:{exc}")


def extract_music_song(query: str) -> str:
    q = str(query or "").strip()
    if not q:
        return ""
    patterns = [
        r"(?:播放|放|听|来一首|搜)\s*[《\"]?([^《》\"，。！？\n]{1,28})[》\"]?",
        r"我要听\s*[《\"]?([^《》\"，。！？\n]{1,28})[》\"]?",
    ]
    for pat in patterns:
        m = re.search(pat, q, flags=re.IGNORECASE)
        if not m:
            continue
        song = str(m.group(1) or "").strip()
        song = re.sub(r"(在网易云|网易云音乐|歌曲|歌)$", "", song).strip()
        if song and song not in {"音乐", "歌曲", "歌"}:
            return song
    return ""


def classify_query(query: str) -> Optional[str]:
    q = str(query or "").strip().lower()
    if not q:
        return None
    if re.search(r"(几号|星期|周几|几点|时间|日期|今天几月几号|today|date|time)", q):
        return "datetime"
    if re.search(r"(天气|气温|温度|下雨|降雨|台风|空气质量|weather|temperature|冷不冷|热不热|穿什么)", q):
        return "weather"
    if re.search(r"(网易云|放一首|来一首|来首|播放音乐|听歌|我要听|打开音乐)", q):
        return "music_search_play" if extract_music_song(query) else "open_music"
    if re.search(r"(汇率|兑换|换算|美元兑|人民币兑|exchange rate|fx)", q):
        return "exchange_rate"
    if re.search(r"(股票|股价|美股|港股|a股|纳斯达克|道琼斯|标普|btc|eth|quote|ticker)", q):
        return "stock_quote"
    if re.search(r"\b[a-z]{1,6}\b.*(价格|价位|price|latest)", q):
        return "stock_quote"
    if re.search(r"(新闻|头条|热点|快讯|热搜|latest news|breaking news)", q):
        if re.search(r"(深度|分析|解读|影响|趋势|原因|怎么看|研判|预测|是否会)", q):
            return None
        return "news_headline"
    return None
