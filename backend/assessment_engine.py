from __future__ import annotations

import json
import math
import re
from typing import Dict, List, Optional, Tuple


SCORE_KEYS = ("Se", "Si", "Ne", "Ni", "Te", "Ti", "Fe", "Fi")
PAIR_KEYS = SCORE_KEYS

FUNCTION_BANK: List[Dict[str, object]] = [
    {
        "id": "se_present_action",
        "pair": "Se",
        "prompt": "遇到新环境时，你会先直接上手试一试，还是先在脑子里想清楚再动？",
    },
    {
        "id": "si_repeat_pattern",
        "pair": "Si",
        "prompt": "做熟悉的事情时，你更依赖自己已经验证过的习惯和步骤吗？",
    },
    {
        "id": "ne_possibility_scan",
        "pair": "Ne",
        "prompt": "别人提一个想法时，你会自然联想到很多可能性和延伸路线吗？",
    },
    {
        "id": "ni_pattern_focus",
        "pair": "Ni",
        "prompt": "面对复杂信息时，你会先抓背后的主线和趋势，再决定怎么做吗？",
    },
    {
        "id": "te_external_structure",
        "pair": "Te",
        "prompt": "推进事情时，你会更想先定标准、排步骤、把结果落地吗？",
    },
    {
        "id": "ti_internal_logic",
        "pair": "Ti",
        "prompt": "你会因为一件事逻辑说不通而一直想把它推演明白吗？",
    },
    {
        "id": "fe_social_attunement",
        "pair": "Fe",
        "prompt": "沟通时，你会下意识先看气氛和别人能不能舒服接住这句话吗？",
    },
    {
        "id": "fi_inner_values",
        "pair": "Fi",
        "prompt": "做决定时，你会很在意这件事是不是符合你自己真正认同的价值吗？",
    },
]

QUESTION_MAP = {str(item["id"]): item for item in FUNCTION_BANK}


def empty_score_map() -> Dict[str, float]:
    return {key: 0.0 for key in SCORE_KEYS}


def empty_pair_confidence() -> Dict[str, float]:
    return {key: 0.0 for key in SCORE_KEYS}


def build_initial_session(now_ms: int) -> Dict[str, object]:
    return {
        "status": "active",
        "started_at_ms": int(now_ms),
        "updated_at_ms": int(now_ms),
        "turn_count": 0,
        "effective_turn_count": 0,
        "scores": empty_score_map(),
        "cognitive_scores": empty_score_map(),
        "dimension_confidence": empty_pair_confidence(),
        "function_confidence": empty_pair_confidence(),
        "asked_question_ids": [],
        "question_history": [],
        "transcript_history": [],
        "evidence_summary": [],
        "last_question_id": "",
        "latest_question": "",
        "latest_transcript": "",
        "question_pair": "",
        "question_source": "ai_required",
        "scoring_source": "pending",
        "type_code": "",
        "mapped_type_code": "",
        "dominant_stack": [],
        "profile_preview": {},
        "voice_mode": "idle",
        "voice_session_active": False,
        "assessment_ready": False,
        "ai_required": True,
        "blocking_reason": "",
        "finish_reason": "",
        "required_min_turns": 12,
        "max_turns": 28,
    }


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


def _score_totals(scores: Dict[str, float]) -> Dict[str, float]:
    sensing = float(scores.get("Se", 0.0)) + float(scores.get("Si", 0.0))
    intuition = float(scores.get("Ne", 0.0)) + float(scores.get("Ni", 0.0))
    thinking = float(scores.get("Te", 0.0)) + float(scores.get("Ti", 0.0))
    feeling = float(scores.get("Fe", 0.0)) + float(scores.get("Fi", 0.0))
    extraverted = float(scores.get("Se", 0.0)) + float(scores.get("Ne", 0.0)) + float(scores.get("Te", 0.0)) + float(scores.get("Fe", 0.0))
    introverted = float(scores.get("Si", 0.0)) + float(scores.get("Ni", 0.0)) + float(scores.get("Ti", 0.0)) + float(scores.get("Fi", 0.0))
    judging = float(scores.get("Te", 0.0)) + float(scores.get("Ti", 0.0)) + float(scores.get("Fe", 0.0)) + float(scores.get("Fi", 0.0))
    perceiving = float(scores.get("Se", 0.0)) + float(scores.get("Si", 0.0)) + float(scores.get("Ne", 0.0)) + float(scores.get("Ni", 0.0))
    return {
        "S": sensing,
        "N": intuition,
        "T": thinking,
        "F": feeling,
        "E": extraverted,
        "I": introverted,
        "J": judging,
        "P": perceiving,
    }


def dominant_stack(scores: Dict[str, float], count: int = 4) -> List[str]:
    ranked = sorted(SCORE_KEYS, key=lambda key: (float(scores.get(key, 0.0)), key), reverse=True)
    return ranked[:count]


def derive_type_code(scores: Dict[str, float]) -> str:
    totals = _score_totals(scores)
    letters = [
        "E" if totals["E"] >= totals["I"] else "I",
        "N" if totals["N"] >= totals["S"] else "S",
        "T" if totals["T"] >= totals["F"] else "F",
        "J" if totals["J"] >= totals["P"] else "P",
    ]
    return "".join(letters)


def summarize_profile(scores: Dict[str, float]) -> Dict[str, object]:
    stack = dominant_stack(scores)
    mapped_type = derive_type_code(scores)
    dominant = stack[0] if stack else ""
    auxiliary = stack[1] if len(stack) > 1 else ""
    dominant_labels = {
        "Ni": "更擅长先抓主线、趋势和长期含义",
        "Ne": "更容易从一个点发散出多条可能路线",
        "Si": "更依赖亲身验证过的经验、节奏和稳定感",
        "Se": "更容易直接感知当下并迅速进入行动",
        "Ti": "更在意逻辑是否严密、自洽和说得通",
        "Te": "更重视标准、效率、步骤和结果落地",
        "Fi": "更在意是否符合自己真实认同的价值",
        "Fe": "更关注关系气氛和对方是否能被好好接住",
    }
    auxiliary_labels = {
        "Ni": "解释时先给主线，再落到执行。",
        "Ne": "适合保留一点探索空间，不要一上来就封死选项。",
        "Si": "先给稳定参照和可复用做法，会更容易进入状态。",
        "Se": "多用具体例子和直接反馈，比抽象空谈更有效。",
        "Ti": "结论后面最好补一层逻辑依据。",
        "Te": "给到明确步骤、时点和可执行动作会更顺手。",
        "Fi": "先确认个人感受和边界，再谈建议更容易被接受。",
        "Fe": "先接住情绪和关系氛围，再推进问题更合适。",
    }
    summary_parts = []
    if dominant:
        summary_parts.append(f"主导功能偏 {dominant}，{dominant_labels.get(dominant, '')}".strip("，"))
    if auxiliary:
        summary_parts.append(auxiliary_labels.get(auxiliary, f"辅助功能偏 {auxiliary}。"))
    summary_parts.append(f"兼容映射类型为 {mapped_type}。")
    return {
        "mapped_type_code": mapped_type,
        "type_code": mapped_type,
        "dominant_stack": stack,
        "summary": " ".join(part for part in summary_parts if part).strip(),
        "response_style": "先给主线判断，再补最小可执行步骤；避免一次灌太多信息。",
        "care_style": "先承接情绪，再给一个轻量建议；最多追问一个关键问题。",
    }


def compute_dimension_confidence(
    scores: Dict[str, float],
    pair_evidence_counts: Optional[Dict[str, object]],
    effective_turn_count: int,
) -> Dict[str, float]:
    evidence_counts = pair_evidence_counts or {}
    confidence = empty_pair_confidence()
    peak = max(max(abs(float(scores.get(key, 0.0))) for key in SCORE_KEYS), 1.0)
    for key in SCORE_KEYS:
        evidence = max(0, int(evidence_counts.get(key, 0) or 0))
        score_strength = abs(float(scores.get(key, 0.0))) / peak
        evidence_term = min(0.55, evidence * 0.12)
        turn_term = min(0.18, max(0, effective_turn_count - 2) * 0.012)
        confidence[key] = max(0.0, min(0.98, 0.08 + evidence_term + turn_term + score_strength * 0.25))
    return confidence


def select_next_pair(scores: Dict[str, float], asked_ids: List[str], confidence: Dict[str, float]) -> str:
    asked = set(asked_ids)
    available = [item for item in FUNCTION_BANK if str(item["id"]) not in asked]
    if not available:
        return min(SCORE_KEYS, key=lambda key: (float(confidence.get(key, 0.0)), -abs(float(scores.get(key, 0.0)))))
    return min(
        [str(item["pair"]) for item in available],
        key=lambda key: (float(confidence.get(key, 0.0)), -abs(float(scores.get(key, 0.0)))),
    )


def select_next_question(scores: Dict[str, float], asked_ids: List[str], confidence: Dict[str, float]) -> Dict[str, object]:
    target = select_next_pair(scores, asked_ids, confidence)
    for item in FUNCTION_BANK:
        if str(item["pair"]) == target and str(item["id"]) not in set(asked_ids):
            return item
    for item in FUNCTION_BANK:
        if str(item["pair"]) == target:
            return item
    return FUNCTION_BANK[0]


def score_answer_heuristic(question: Dict[str, object], answer: str) -> Dict[str, object]:
    return {
        "scores_delta": empty_score_map(),
        "function_confidence_delta": empty_pair_confidence(),
        "pair": str(question.get("pair") or ""),
        "target_function": str(question.get("pair") or ""),
        "evidence_tags": [],
        "effective": False,
        "reasoning": "heuristic_disabled",
        "next_gap": str(question.get("pair") or ""),
    }


def should_finish(session: Dict[str, object]) -> Tuple[bool, str]:
    effective_turn_count = int(session.get("effective_turn_count", 0) or 0)
    max_turns = int(session.get("max_turns", 28) or 28)
    min_turns = int(session.get("required_min_turns", 12) or 12)
    confidence = normalize_confidence(session.get("function_confidence") or session.get("dimension_confidence"))
    if effective_turn_count < min_turns:
        return False, "min_turns"
    if min(confidence.values() or [0.0]) >= 0.72:
        return True, "function_confidence_met"
    if effective_turn_count >= max_turns:
        return False, "insufficient_signal_at_cap"
    return False, "need_more_signal"


def merge_scoring(
    session: Dict[str, object],
    question: Dict[str, object],
    answer: str,
    scoring: Dict[str, object],
    now_ms: int,
) -> Dict[str, object]:
    scores = normalize_scores(session.get("scores") or session.get("cognitive_scores"))
    delta_scores = normalize_scores(scoring.get("scores_delta") or scoring.get("cognitive_scores"))
    for key in SCORE_KEYS:
        scores[key] = round(scores[key] + float(delta_scores.get(key, 0.0)), 4)

    evidence_counts = dict(session.get("pair_evidence_counts") or {})
    target_function = str(scoring.get("target_function") or scoring.get("pair") or question.get("pair") or "")
    if scoring.get("effective") and target_function in SCORE_KEYS:
        evidence_counts[target_function] = int(evidence_counts.get(target_function, 0) or 0) + 1

    function_confidence = compute_dimension_confidence(
        scores,
        evidence_counts,
        int(session.get("effective_turn_count", 0) or 0) + (1 if scoring.get("effective") else 0),
    )
    previous_confidence = normalize_confidence(session.get("function_confidence") or session.get("dimension_confidence"))
    manual_confidence = normalize_confidence(scoring.get("function_confidence_delta"))
    for key in SCORE_KEYS:
        if float(manual_confidence.get(key, 0.0)) > 0:
            function_confidence[key] = min(
                0.98,
                max(function_confidence[key], float(previous_confidence.get(key, 0.0)) + float(manual_confidence[key])),
            )
        else:
            function_confidence[key] = max(function_confidence[key], float(previous_confidence.get(key, 0.0)))

    evidence_summary = [str(item) for item in session.get("evidence_summary") or [] if str(item).strip()]
    for item in scoring.get("evidence_tags") or []:
        text = str(item).strip()
        if text and text not in evidence_summary:
            evidence_summary.append(text)

    asked_ids = [str(item) for item in session.get("asked_question_ids") or [] if str(item).strip()]
    question_id = str(question.get("id") or "")
    if question_id and question_id not in asked_ids:
        asked_ids.append(question_id)

    question_history = [dict(item) for item in session.get("question_history") or [] if isinstance(item, dict)]
    question_history.append(
        {
            "question_id": question_id,
            "question": str(question.get("prompt") or ""),
            "answer": str(answer or "").strip(),
            "target_function": target_function,
            "timestamp_ms": int(now_ms),
        }
    )
    transcript_history = [dict(item) for item in session.get("transcript_history") or [] if isinstance(item, dict)]
    transcript_history.append({"role": "user", "text": str(answer or "").strip(), "timestamp_ms": int(now_ms)})

    preview = summarize_profile(scores)
    done, reason = should_finish(
        {
            **session,
            "scores": scores,
            "function_confidence": function_confidence,
            "effective_turn_count": int(session.get("effective_turn_count", 0) or 0) + (1 if scoring.get("effective") else 0),
            "required_min_turns": int(session.get("required_min_turns", 12) or 12),
            "max_turns": int(session.get("max_turns", 28) or 28),
        }
    )
    merged = dict(session)
    merged.update(
        {
            "updated_at_ms": int(now_ms),
            "turn_count": int(session.get("turn_count", 0) or 0) + 1,
            "effective_turn_count": int(session.get("effective_turn_count", 0) or 0) + (1 if scoring.get("effective") else 0),
            "scores": scores,
            "cognitive_scores": scores,
            "dimension_confidence": function_confidence,
            "function_confidence": function_confidence,
            "pair_evidence_counts": evidence_counts,
            "asked_question_ids": asked_ids,
            "question_history": question_history[-40:],
            "transcript_history": transcript_history[-40:],
            "evidence_summary": evidence_summary[-24:],
            "latest_transcript": str(answer or "").strip(),
            "type_code": str(preview.get("mapped_type_code") or ""),
            "mapped_type_code": str(preview.get("mapped_type_code") or ""),
            "dominant_stack": list(preview.get("dominant_stack") or []),
            "profile_preview": preview,
            "assessment_ready": done and reason == "function_confidence_met",
            "finish_reason": reason,
            "blocking_reason": "",
        }
    )
    return merged


def build_final_profile(session: Dict[str, object]) -> Dict[str, object]:
    scores = normalize_scores(session.get("scores") or session.get("cognitive_scores"))
    function_confidence = normalize_confidence(session.get("function_confidence") or session.get("dimension_confidence"))
    preview = summarize_profile(scores)
    evidence_items = [str(item) for item in session.get("evidence_summary") or [] if str(item).strip()]
    completion_reason = str(session.get("finish_reason") or "")
    ready, computed_reason = should_finish(session)
    min_turns = int(session.get("required_min_turns", 12) or 12)
    effective_turn_count = int(session.get("effective_turn_count", 0) or 0)
    assessment_ready = bool(session.get("assessment_ready")) or ready
    if not completion_reason:
        completion_reason = computed_reason
    if not assessment_ready and completion_reason == "function_confidence_met" and effective_turn_count >= min_turns:
        assessment_ready = True
    return {
        "cognitive_scores": {key: round(float(scores.get(key, 0.0)), 3) for key in SCORE_KEYS},
        "scores": {key: round(float(scores.get(key, 0.0)), 3) for key in SCORE_KEYS},
        "function_confidence": {key: round(float(function_confidence.get(key, 0.0)), 3) for key in SCORE_KEYS},
        "dimension_confidence": {key: round(float(function_confidence.get(key, 0.0)), 3) for key in SCORE_KEYS},
        "dominant_stack": list(preview.get("dominant_stack") or []),
        "mapped_type_code": str(preview.get("mapped_type_code") or derive_type_code(scores)),
        "type_code": str(preview.get("mapped_type_code") or derive_type_code(scores)),
        "evidence_summary": {
            "highlights": evidence_items[:8],
            "notes": str(preview.get("summary") or ""),
        },
        "conversation_count": int(session.get("effective_turn_count", 0) or 0),
        "completed_at_ms": int(session.get("completed_at_ms", 0) or 0),
        "response_style": str(preview.get("response_style") or ""),
        "care_style": str(preview.get("care_style") or ""),
        "summary": str(preview.get("summary") or ""),
        "completion_reason": completion_reason,
        "assessment_ready": bool(assessment_ready and completion_reason != "insufficient_signal_at_cap"),
        "ai_required": True,
        "inference_version": "assessment-v2-jung8",
    }


def build_memory_summary(profile: Dict[str, object], preferred_name: str = "") -> str:
    scores = normalize_scores(profile.get("cognitive_scores") or profile.get("scores"))
    confidence = normalize_confidence(profile.get("function_confidence") or profile.get("dimension_confidence"))
    stack = [str(item) for item in profile.get("dominant_stack") or [] if str(item).strip()]
    person = preferred_name or "该用户"
    machine_line = " | ".join(
        [
            f"mapped_type={str(profile.get('mapped_type_code') or profile.get('type_code') or '').strip()}",
            "functions=" + ",".join(f"{key}:{scores[key]:.2f}" for key in SCORE_KEYS),
            "confidence=" + ",".join(f"{key}:{confidence[key]:.2f}" for key in SCORE_KEYS),
            "stack=" + ",".join(stack),
        ]
    )
    ai_line = (
        f"{person} 的互动风格摘要：主导功能偏 {stack[0] if stack else 'unknown'}，"
        f"兼容类型 {str(profile.get('mapped_type_code') or '').strip()}；"
        f"后续陪伴时先给主线和一条可执行建议，再根据情绪承接程度继续追问。"
    )
    return f"[psychometric_index]\n{machine_line}\n[companion_hint]\n{ai_line}"


def extract_scoring_from_model(raw: str) -> Dict[str, object]:
    parsed = parse_json_dict(raw)
    if not parsed:
        return {}
    score_payload = parsed.get("cognitive_scores")
    if not isinstance(score_payload, dict):
        score_payload = parsed.get("scores_delta")
    confidence_payload = parsed.get("function_confidence")
    if not isinstance(confidence_payload, dict):
        confidence_payload = parsed.get("function_confidence_delta")
    target_function = str(parsed.get("target_function") or parsed.get("pair") or "").strip()
    if target_function not in SCORE_KEYS:
        target_function = ""
    evidence_tags = []
    for item in parsed.get("evidence_summary") or parsed.get("evidence_tags") or []:
        text = str(item).strip()
        if text:
            evidence_tags.append(text)
    return {
        "scores_delta": normalize_scores(score_payload),
        "function_confidence_delta": normalize_confidence(confidence_payload),
        "pair": target_function,
        "target_function": target_function,
        "evidence_tags": evidence_tags[:4],
        "effective": bool(parsed.get("effective", True)),
        "reasoning": str(parsed.get("reasoning") or "").strip(),
        "next_gap": str(parsed.get("next_gap") or "").strip(),
    }


def extract_next_question_from_model(raw: str) -> Dict[str, object]:
    parsed = parse_json_dict(raw)
    question = str(parsed.get("question") or "").strip()
    target_function = str(parsed.get("target_function") or parsed.get("pair") or "").strip()
    if target_function not in SCORE_KEYS or not question:
        return {}
    return {
        "id": str(parsed.get("question_id") or f"model-{target_function.lower()}-{abs(hash(question)) % 100000}"),
        "pair": target_function,
        "prompt": question,
    }


def extract_termination_from_model(raw: str) -> Dict[str, object]:
    parsed = parse_json_dict(raw)
    missing_function = str(parsed.get("missing_function") or parsed.get("missing_pair") or "").strip()
    if missing_function not in SCORE_KEYS:
        missing_function = ""
    return {
        "should_finish": bool(parsed.get("should_finish", False)),
        "reason": str(parsed.get("reason") or parsed.get("completion_reason") or "").strip(),
        "missing_pair": missing_function,
    }
