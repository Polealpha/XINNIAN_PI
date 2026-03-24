from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Dict, List, Optional

from ..llm.llm_responder import LLMResponder


class DailySummarizer:
    def __init__(self, llm: Optional[LLMResponder] = None) -> None:
        self._llm = llm

    def summarize(self, events: List[Dict[str, object]]) -> Dict[str, object]:
        fallback = self._fallback_summary(events)
        if not self._llm or not self._llm.enabled:
            return fallback
        compact_events = self._compact_events(events)
        context = {
            "event_count": len(events),
            "compact_event_count": len(compact_events),
            "events": compact_events[:30],
            "risk_stats": self._build_risk_stats(compact_events),
            "emotion_stats": self._build_emotion_stats(compact_events),
            "timeline_highlights": self._build_timeline_highlights(compact_events),
        }
        reply = self._llm.generate_daily_summary(context)
        if reply:
            return reply
        return fallback

    def _compact_events(self, events: List[Dict[str, object]]) -> List[Dict[str, object]]:
        compact: List[Dict[str, object]] = []
        for event in events:
            summary = str(event.get("summary", "")).strip()
            expr_label = str(event.get("expression_modality", "")).strip().lower()
            expr_conf = float(event.get("expression_confidence", 0.0) or 0.0)
            risk = event.get("risk")
            risk_map = risk if isinstance(risk, dict) else {}
            risk_score = float(risk_map.get("S", 0.0) or 0.0)
            if not summary:
                if expr_label:
                    summary = f"{expr_label}（{expr_conf:.2f}）"
                else:
                    summary = f"状态采样（S={risk_score:.2f}）"

            item: Dict[str, object] = {
                "summary": summary,
                "timestamp_ms": int(event.get("timestamp_ms", 0) or 0),
                "event_type": str(event.get("event_type", "state") or "state"),
                "mode": str(event.get("mode", "normal") or "normal"),
            }
            if expr_label:
                item["expression_modality"] = expr_label
                item["expression_confidence"] = round(expr_conf, 3)
            if risk_map:
                item["risk"] = {
                    "V": float(risk_map.get("V", 0.0) or 0.0),
                    "A": float(risk_map.get("A", 0.0) or 0.0),
                    "T": risk_map.get("T"),
                    "S": float(risk_map.get("S", 0.0) or 0.0),
                }
            tags = event.get("tags")
            if isinstance(tags, list):
                clean_tags = [str(tag).strip() for tag in tags if str(tag).strip()]
                if clean_tags:
                    item["tags"] = clean_tags[:3]
            compact.append(item)

        compact.sort(key=lambda x: int(x.get("timestamp_ms", 0) or 0))
        return compact

    def _build_risk_stats(self, events: List[Dict[str, object]]) -> Dict[str, object]:
        if not events:
            return {"avg_S": 0.0, "max_S": 0.0, "high_risk_count": 0, "sample_count": 0}

        s_values: List[float] = []
        v_values: List[float] = []
        a_values: List[float] = []
        high_risk_count = 0
        for event in events:
            risk = event.get("risk")
            if not isinstance(risk, dict):
                continue
            v = float(risk.get("V", 0.0) or 0.0)
            a = float(risk.get("A", 0.0) or 0.0)
            s = float(risk.get("S", 0.0) or 0.0)
            v_values.append(v)
            a_values.append(a)
            s_values.append(s)
            if s >= 0.70:
                high_risk_count += 1

        if not s_values:
            return {"avg_S": 0.0, "max_S": 0.0, "high_risk_count": 0, "sample_count": 0}

        return {
            "avg_V": round(sum(v_values) / len(v_values), 3),
            "avg_A": round(sum(a_values) / len(a_values), 3),
            "avg_S": round(sum(s_values) / len(s_values), 3),
            "max_S": round(max(s_values), 3),
            "high_risk_count": high_risk_count,
            "sample_count": len(s_values),
        }

    def _build_emotion_stats(self, events: List[Dict[str, object]]) -> Dict[str, object]:
        if not events:
            return {"modality_counts": {}, "dominant_modality": "unknown", "non_neutral_ratio": 0.0}

        counter: Counter[str] = Counter()
        conf_sum = 0.0
        conf_count = 0
        non_neutral_count = 0
        for event in events:
            label = str(event.get("expression_modality", "")).strip().lower()
            if not label:
                continue
            counter[label] += 1
            conf = float(event.get("expression_confidence", 0.0) or 0.0)
            conf_sum += conf
            conf_count += 1
            if label not in {"neutral", "unknown"}:
                non_neutral_count += 1

        if not counter:
            return {"modality_counts": {}, "dominant_modality": "unknown", "non_neutral_ratio": 0.0}

        dominant = counter.most_common(1)[0][0]
        total = sum(counter.values())
        return {
            "modality_counts": dict(counter),
            "dominant_modality": dominant,
            "non_neutral_ratio": round(non_neutral_count / max(total, 1), 3),
            "avg_confidence": round(conf_sum / max(conf_count, 1), 3),
        }

    def _build_timeline_highlights(self, events: List[Dict[str, object]]) -> List[str]:
        if not events:
            return []

        by_risk = sorted(
            events,
            key=lambda e: float(((e.get("risk") if isinstance(e.get("risk"), dict) else {}) or {}).get("S", 0.0) or 0.0),
            reverse=True,
        )
        selected: List[Dict[str, object]] = []
        for event in by_risk:
            risk = event.get("risk") if isinstance(event.get("risk"), dict) else {}
            if float(risk.get("S", 0.0) or 0.0) < 0.55:
                continue
            selected.append(event)
            if len(selected) >= 3:
                break

        if len(selected) < 6:
            for event in reversed(events):
                selected.append(event)
                if len(selected) >= 6:
                    break

        highlights: List[str] = []
        seen = set()
        for event in sorted(selected, key=lambda e: int(e.get("timestamp_ms", 0) or 0)):
            ts = int(event.get("timestamp_ms", 0) or 0)
            summary = str(event.get("summary", "")).strip()
            if not summary:
                continue
            key = (ts, summary)
            if key in seen:
                continue
            seen.add(key)
            highlights.append(f"{self._to_hhmm(ts)} {summary}")
            if len(highlights) >= 6:
                break
        return highlights

    @staticmethod
    def _to_hhmm(timestamp_ms: int) -> str:
        if timestamp_ms <= 0:
            return "--:--"
        return datetime.fromtimestamp(timestamp_ms / 1000.0).strftime("%H:%M")

    def _fallback_summary(self, events: List[Dict[str, object]]) -> Dict[str, object]:
        if not events:
            return {
                "summary": "今天没有记录到明显的情绪事件。如果你愿意，随时可以跟我说说。",
                "highlights": ["暂无明显触发事件", "整体状态较平稳", "需要时可以随时记录感受"],
            }

        tag_counter = Counter()
        for event in events:
            tags = event.get("tags", [])
            if isinstance(tags, list):
                for tag in tags:
                    tag_text = str(tag).strip()
                    if tag_text:
                        tag_counter[tag_text] += 1

        compact_events = self._compact_events(events)
        emotion_stats = self._build_emotion_stats(compact_events)
        risk_stats = self._build_risk_stats(compact_events)

        top_tags = [tag for tag, _count in tag_counter.most_common(2)]
        if top_tags:
            tag_text = "、".join(top_tags)
            summary = (
                f"今天记录了{len(events)}次需要关注的时刻，主要集中在{tag_text}。"
                "如果需要，我们可以慢慢梳理。"
            )
        else:
            dominant = str(emotion_stats.get("dominant_modality", "unknown"))
            avg_s = float(risk_stats.get("avg_S", 0.0) or 0.0)
            summary = (
                f"今天记录了{len(events)}次状态采样，主导情绪倾向是{dominant}，"
                f"整体风险均值约{avg_s:.2f}。如果需要，我们可以慢慢梳理。"
            )

        highlights: List[str] = []
        for event in events:
            item = str(event.get("summary", "")).strip()
            if item and item not in highlights:
                highlights.append(item)
            if len(highlights) >= 5:
                break

        while len(highlights) < 3:
            if top_tags:
                highlights.append(f"主要情绪集中在{top_tags[0]}")
            else:
                highlights.append("保持节奏，注意休息")
            if len(highlights) >= 3:
                break

        return {"summary": summary, "highlights": highlights[:5]}
