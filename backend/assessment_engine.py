from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple


SCORE_KEYS = ("Se", "Si", "Ne", "Ni", "Te", "Ti", "Fe", "Fi")
PAIR_KEYS = SCORE_KEYS
QUESTION_MAP: Dict[str, Dict[str, object]] = {}

PROFILE_LIST_KEYS = ("interaction_preferences", "comfort_preferences", "avoid_patterns")
PROFILE_TEXT_KEYS = ("summary", "decision_style", "stress_response", "care_guidance")


def empty_score_map() -> Dict[str, float]:
    return {key: 0.0 for key in SCORE_KEYS}


def empty_pair_confidence() -> Dict[str, float]:
    return {key: 0.0 for key in SCORE_KEYS}


def parse_json_dict(text: str) -> Dict[str, object]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(raw[start : end + 1])
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def normalize_scores(raw: Optional[Dict[str, object]]) -> Dict[str, float]:
    scores = empty_score_map()
    for key in SCORE_KEYS:
        try:
            scores[key] = round(float((raw or {}).get(key, 0.0) or 0.0), 4)
        except Exception:
            scores[key] = 0.0
    return scores


def normalize_confidence(raw: Optional[Dict[str, object]]) -> Dict[str, float]:
    confidence = empty_pair_confidence()
    for key in SCORE_KEYS:
        try:
            confidence[key] = max(0.0, min(1.0, float((raw or {}).get(key, 0.0) or 0.0)))
        except Exception:
            confidence[key] = 0.0
    return confidence


def compute_dimension_confidence(
    scores: Dict[str, float],
    pair_evidence_counts: Optional[Dict[str, object]],
    effective_turn_count: int,
) -> Dict[str, float]:
    del scores, pair_evidence_counts, effective_turn_count
    return empty_pair_confidence()


def derive_type_code(scores: Dict[str, float]) -> str:
    del scores
    return ""


def build_initial_session(now_ms: int) -> Dict[str, object]:
    return {
        "status": "active",
        "started_at_ms": int(now_ms),
        "updated_at_ms": int(now_ms),
        "completed_at_ms": None,
        "turn_count": 0,
        "effective_turn_count": 0,
        "conversation_count": 0,
        "scores": empty_score_map(),
        "cognitive_scores": empty_score_map(),
        "dimension_confidence": empty_pair_confidence(),
        "function_confidence": empty_pair_confidence(),
        "question_history": [],
        "transcript_history": [],
        "dialogue_turns": [],
        "latest_question": "",
        "latest_transcript": "",
        "last_question_id": "",
        "question_source": "ai_required",
        "scoring_source": "pending",
        "question_pair": "",
        "current_focus": "",
        "voice_mode": "idle",
        "voice_session_active": False,
        "assessment_ready": False,
        "ai_required": True,
        "blocking_reason": "",
        "finish_reason": "",
        "required_min_turns": 4,
        "max_turns": 12,
        "summary": "",
        "interaction_preferences": [],
        "decision_style": "",
        "stress_response": "",
        "comfort_preferences": [],
        "avoid_patterns": [],
        "care_guidance": "",
        "confidence": 0.0,
        "evidence_summary": {"highlights": [], "notes": ""},
        "profile_preview": {},
    }


def _listify(value: object) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    return []


def _merge_unique(left: List[str], right: List[str]) -> List[str]:
    merged: List[str] = []
    seen: set[str] = set()
    for item in [*left, *right]:
        normalized = str(item).strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        merged.append(normalized)
    return merged


def _normalize_profile_updates(raw: Optional[Dict[str, object]]) -> Dict[str, object]:
    data = dict(raw or {})
    normalized: Dict[str, object] = {}
    for key in PROFILE_LIST_KEYS:
        normalized[key] = _listify(data.get(key))
    for key in PROFILE_TEXT_KEYS:
        normalized[key] = str(data.get(key) or "").strip()
    return normalized


def _merge_profile_preview(base: Dict[str, object], updates: Dict[str, object]) -> Dict[str, object]:
    merged = {
        "summary": str(base.get("summary") or "").strip(),
        "interaction_preferences": _listify(base.get("interaction_preferences")),
        "decision_style": str(base.get("decision_style") or "").strip(),
        "stress_response": str(base.get("stress_response") or "").strip(),
        "comfort_preferences": _listify(base.get("comfort_preferences")),
        "avoid_patterns": _listify(base.get("avoid_patterns")),
        "care_guidance": str(base.get("care_guidance") or "").strip(),
    }
    normalized = _normalize_profile_updates(updates)
    for key in PROFILE_LIST_KEYS:
        merged[key] = _merge_unique(list(merged[key]), list(normalized.get(key) or []))
    for key in PROFILE_TEXT_KEYS:
        if str(normalized.get(key) or "").strip():
            merged[key] = str(normalized.get(key) or "").strip()
    return merged


def _append_dialogue_turn(dialogue_turns: List[Dict[str, object]], role: str, text: str, timestamp_ms: int) -> List[Dict[str, object]]:
    clean = str(text or "").strip()
    if not clean:
        return dialogue_turns
    if dialogue_turns:
        last = dialogue_turns[-1]
        if str(last.get("role") or "") == role and str(last.get("text") or "").strip() == clean:
            return dialogue_turns
    next_turns = list(dialogue_turns)
    next_turns.append({"role": role, "text": clean, "timestamp_ms": int(timestamp_ms)})
    return next_turns[-40:]


def extract_next_question_from_model(text: str) -> Dict[str, object]:
    parsed = parse_json_dict(text)
    question = str(parsed.get("question") or parsed.get("next_question") or "").strip()
    focus = str(parsed.get("next_focus") or parsed.get("target_area") or parsed.get("target_function") or "").strip()
    question_id = str(parsed.get("question_id") or parsed.get("id") or f"dialogue-{abs(hash(question or text)) % 100000}").strip()
    if not question:
        return {}
    return {
        "id": question_id or "dialogue-next",
        "prompt": question,
        "pair": focus,
        "focus": focus,
        "rationale": str(parsed.get("rationale") or "").strip(),
    }


def extract_scoring_from_model(text: str) -> Dict[str, object]:
    parsed = parse_json_dict(text)
    updates = _normalize_profile_updates(parsed.get("profile_updates") if isinstance(parsed.get("profile_updates"), dict) else parsed)
    evidence = _listify(parsed.get("evidence_summary") or parsed.get("evidence"))
    try:
        confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.0) or 0.0)))
    except Exception:
        confidence = 0.0
    return {
        "effective": bool(parsed.get("effective", True)),
        "profile_updates": updates,
        "evidence_summary": evidence[:6],
        "reasoning": str(parsed.get("reasoning") or "").strip(),
        "next_focus": str(parsed.get("next_focus") or parsed.get("missing_area") or "").strip(),
        "stable_enough": bool(parsed.get("stable_enough", False)),
        "confidence": confidence,
        "summary_hint": str(parsed.get("summary_hint") or "").strip(),
    }


def extract_termination_from_model(text: str) -> Dict[str, object]:
    parsed = parse_json_dict(text)
    try:
        confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.0) or 0.0)))
    except Exception:
        confidence = 0.0
    return {
        "should_finish": bool(parsed.get("should_finish", False)),
        "reason": str(parsed.get("reason") or "").strip() or "need_more_signal",
        "missing_area": str(parsed.get("missing_area") or parsed.get("missing_function") or "").strip(),
        "confidence": confidence,
    }


def select_next_question(scores: Dict[str, float], asked_ids: List[str], confidence: Dict[str, float]) -> Dict[str, object]:
    del scores, asked_ids, confidence
    return {}


def score_answer_heuristic(question: Dict[str, object], answer: str) -> Dict[str, object]:
    del question, answer
    return {
        "effective": False,
        "profile_updates": {},
        "evidence_summary": [],
        "reasoning": "heuristic_disabled",
        "next_focus": "",
        "stable_enough": False,
        "confidence": 0.0,
        "summary_hint": "",
    }


def should_finish(session: Dict[str, object]) -> Tuple[bool, str]:
    effective_turn_count = int(session.get("effective_turn_count", 0) or 0)
    min_turns = int(session.get("required_min_turns", 4) or 4)
    max_turns = int(session.get("max_turns", 12) or 12)
    confidence = float(session.get("confidence") or 0.0)
    if effective_turn_count < min_turns:
        return False, "min_turns"
    if bool(session.get("assessment_ready")) or confidence >= 0.82:
        return True, "stable_enough"
    if effective_turn_count >= max_turns:
        return False, "needs_follow_up"
    return False, "need_more_signal"


def merge_scoring(
    session: Dict[str, object],
    question: Dict[str, object],
    answer: str,
    scoring: Dict[str, object],
    now_ms: int,
) -> Dict[str, object]:
    merged = dict(session)
    merged["updated_at_ms"] = int(now_ms)
    merged["turn_count"] = int(session.get("turn_count", 0) or 0) + 1
    merged["effective_turn_count"] = int(session.get("effective_turn_count", 0) or 0) + (1 if scoring.get("effective") else 0)
    merged["conversation_count"] = int(merged["effective_turn_count"])
    merged["latest_transcript"] = str(answer or "").strip()
    merged["transcript_history"] = [
        *[dict(item) for item in session.get("transcript_history") or [] if isinstance(item, dict)],
        {"role": "user", "text": str(answer or "").strip(), "timestamp_ms": int(now_ms)},
    ][-40:]
    merged["question_history"] = [
        *[dict(item) for item in session.get("question_history") or [] if isinstance(item, dict)],
        {
            "question_id": str(question.get("id") or "").strip(),
            "question": str(question.get("prompt") or "").strip(),
            "answer": str(answer or "").strip(),
            "timestamp_ms": int(now_ms),
        },
    ][-40:]
    dialogue_turns = [dict(item) for item in session.get("dialogue_turns") or [] if isinstance(item, dict)]
    dialogue_turns = _append_dialogue_turn(
        dialogue_turns,
        "assistant",
        str(question.get("prompt") or "").strip(),
        int(now_ms),
    )
    dialogue_turns = _append_dialogue_turn(
        dialogue_turns,
        "user",
        str(answer or "").strip(),
        int(now_ms),
    )
    merged["dialogue_turns"] = dialogue_turns
    preview = _merge_profile_preview(
        dict(session.get("profile_preview") or {}),
        dict(scoring.get("profile_updates") or {}),
    )
    if not str(preview.get("summary") or "").strip():
        preview["summary"] = str(scoring.get("summary_hint") or "").strip()
    merged["profile_preview"] = preview
    merged["summary"] = str(preview.get("summary") or "").strip()
    merged["interaction_preferences"] = _listify(preview.get("interaction_preferences"))
    merged["decision_style"] = str(preview.get("decision_style") or "").strip()
    merged["stress_response"] = str(preview.get("stress_response") or "").strip()
    merged["comfort_preferences"] = _listify(preview.get("comfort_preferences"))
    merged["avoid_patterns"] = _listify(preview.get("avoid_patterns"))
    merged["care_guidance"] = str(preview.get("care_guidance") or "").strip()
    merged["response_style"] = merged["decision_style"]
    merged["care_style"] = merged["care_guidance"]
    merged["confidence"] = max(float(session.get("confidence") or 0.0), float(scoring.get("confidence") or 0.0))
    highlights = _merge_unique(
        _listify((session.get("evidence_summary") or {}).get("highlights") if isinstance(session.get("evidence_summary"), dict) else session.get("evidence_summary")),
        _listify(scoring.get("evidence_summary")),
    )
    merged["evidence_summary"] = {
        "highlights": highlights[:8],
        "notes": str(scoring.get("reasoning") or "").strip() or str(preview.get("summary") or "").strip(),
    }
    merged["current_focus"] = str(scoring.get("next_focus") or session.get("current_focus") or "").strip()
    merged["assessment_ready"] = bool(scoring.get("stable_enough")) and int(merged["effective_turn_count"]) >= int(
        session.get("required_min_turns", 4) or 4
    )
    merged["finish_reason"] = "stable_enough" if merged["assessment_ready"] else ""
    merged["blocking_reason"] = ""
    merged["question_source"] = "ai"
    merged["scoring_source"] = "ai"
    merged["ai_required"] = True
    merged["type_code"] = ""
    merged["mapped_type_code"] = ""
    merged["dominant_stack"] = []
    return merged


def build_final_profile(session: Dict[str, object]) -> Dict[str, object]:
    preview = _merge_profile_preview(
        {
            "summary": str(session.get("summary") or "").strip(),
            "interaction_preferences": session.get("interaction_preferences") or [],
            "decision_style": str(session.get("decision_style") or "").strip(),
            "stress_response": str(session.get("stress_response") or "").strip(),
            "comfort_preferences": session.get("comfort_preferences") or [],
            "avoid_patterns": session.get("avoid_patterns") or [],
            "care_guidance": str(session.get("care_guidance") or "").strip(),
        },
        dict(session.get("profile_preview") or {}),
    )
    ready, reason = should_finish(session)
    confidence = max(float(session.get("confidence") or 0.0), 0.35 if ready else 0.0)
    return {
        "summary": str(preview.get("summary") or "").strip(),
        "interaction_preferences": _listify(preview.get("interaction_preferences")),
        "decision_style": str(preview.get("decision_style") or "").strip(),
        "stress_response": str(preview.get("stress_response") or "").strip(),
        "comfort_preferences": _listify(preview.get("comfort_preferences")),
        "avoid_patterns": _listify(preview.get("avoid_patterns")),
        "care_guidance": str(preview.get("care_guidance") or "").strip(),
        "confidence": round(confidence, 3),
        "conversation_count": int(session.get("effective_turn_count", 0) or 0),
        "completed_at_ms": int(session.get("completed_at_ms") or 0) or None,
        "response_style": str(preview.get("decision_style") or "").strip(),
        "care_style": str(preview.get("care_guidance") or "").strip(),
        "evidence_summary": session.get("evidence_summary") if isinstance(session.get("evidence_summary"), dict) else {"highlights": [], "notes": ""},
        "completion_reason": str(session.get("finish_reason") or reason or "").strip(),
        "assessment_ready": bool(ready or session.get("assessment_ready")),
        "ai_required": True,
        "inference_version": "activation-dialogue-v5",
        "type_code": "",
        "mapped_type_code": "",
        "cognitive_scores": empty_score_map(),
        "scores": empty_score_map(),
        "function_confidence": empty_pair_confidence(),
        "dimension_confidence": empty_pair_confidence(),
        "dominant_stack": [],
    }


def build_memory_summary(profile: Dict[str, object], preferred_name: str = "") -> str:
    lines = [
        f"name={str(preferred_name or '').strip()}",
        f"summary={str(profile.get('summary') or '').strip()}",
        f"interaction_preferences={json.dumps(_listify(profile.get('interaction_preferences')), ensure_ascii=False)}",
        f"decision_style={str(profile.get('decision_style') or '').strip()}",
        f"stress_response={str(profile.get('stress_response') or '').strip()}",
        f"comfort_preferences={json.dumps(_listify(profile.get('comfort_preferences')), ensure_ascii=False)}",
        f"avoid_patterns={json.dumps(_listify(profile.get('avoid_patterns')), ensure_ascii=False)}",
        f"care_guidance={str(profile.get('care_guidance') or '').strip()}",
        f"confidence={float(profile.get('confidence') or 0.0):.2f}",
        "source=activation_dialogue",
    ]
    return "\n".join(lines)
