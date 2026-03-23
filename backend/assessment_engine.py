from __future__ import annotations

import json
import math
import random
import re
from typing import Dict, List, Optional, Tuple


SCORE_KEYS = ("E", "I", "S", "N", "T", "F", "J", "P")
PAIR_KEYS = ("EI", "SN", "TF", "JP")
PAIR_TO_POLES = {
    "EI": ("E", "I"),
    "SN": ("S", "N"),
    "TF": ("T", "F"),
    "JP": ("J", "P"),
}

QUESTION_BANK: List[Dict[str, object]] = [
    {
        "id": "ei_recharge",
        "pair": "EI",
        "prompt": "如果刚经历一整天高强度沟通，你一般会怎么给自己回血？",
        "dimension_targets": ["E", "I"],
        "difficulty": 1,
        "followup_rules": ["如果回答模糊，追问更偏独处恢复还是和熟人聊一聊恢复。"],
    },
    {
        "id": "ei_meeting",
        "pair": "EI",
        "prompt": "在一个新环境里，你通常会先主动和人聊起来，还是先观察一会儿再进入状态？",
        "dimension_targets": ["E", "I"],
        "difficulty": 1,
        "followup_rules": ["若回答两者都有，追问哪种更自然。"],
    },
    {
        "id": "ei_problem",
        "pair": "EI",
        "prompt": "遇到卡住的事情时，你更习惯边说边理清，还是先自己想透再开口？",
        "dimension_targets": ["E", "I"],
        "difficulty": 2,
        "followup_rules": ["如果说看情况，追问大多数时候的第一反应。"],
    },
    {
        "id": "sn_learn",
        "pair": "SN",
        "prompt": "学一个新东西时，你更喜欢先看具体例子和步骤，还是先抓整体思路和可能性？",
        "dimension_targets": ["S", "N"],
        "difficulty": 1,
        "followup_rules": ["如果回答都要，追问哪种更容易让自己进入状态。"],
    },
    {
        "id": "sn_change",
        "pair": "SN",
        "prompt": "当计划突然变化，你会先关注眼前要怎么落地，还是会先想到后面可能带来的连锁影响？",
        "dimension_targets": ["S", "N"],
        "difficulty": 2,
        "followup_rules": ["若回答混合，追问第一时间更自然的反应。"],
    },
    {
        "id": "sn_decision",
        "pair": "SN",
        "prompt": "做选择时，你更信任已经验证过的经验，还是更看重新方向和潜力？",
        "dimension_targets": ["S", "N"],
        "difficulty": 1,
        "followup_rules": ["必要时追问‘过去证明有效’和‘未来更有空间’哪个更打动你。"],
    },
    {
        "id": "tf_feedback",
        "pair": "TF",
        "prompt": "别人来找你拿建议时，你通常会先讲最合理的判断，还是先照顾对方的感受和接受度？",
        "dimension_targets": ["T", "F"],
        "difficulty": 1,
        "followup_rules": ["如果都重要，追问先后顺序。"],
    },
    {
        "id": "tf_conflict",
        "pair": "TF",
        "prompt": "出现分歧时，你更容易被‘逻辑站不住’触发，还是被‘关系被伤到’触发？",
        "dimension_targets": ["T", "F"],
        "difficulty": 2,
        "followup_rules": ["若回答都在意，追问哪个更让你难受。"],
    },
    {
        "id": "tf_standard",
        "pair": "TF",
        "prompt": "做决定时，你更依赖统一标准和原则，还是更看具体的人和情境？",
        "dimension_targets": ["T", "F"],
        "difficulty": 2,
        "followup_rules": ["如果回答一半一半，追问平时更默认哪边。"],
    },
    {
        "id": "jp_schedule",
        "pair": "JP",
        "prompt": "如果一周里有几件重要事，你更喜欢提前排好节奏，还是边走边调保持弹性？",
        "dimension_targets": ["J", "P"],
        "difficulty": 1,
        "followup_rules": ["如果都可以，追问哪种更让你安心。"],
    },
    {
        "id": "jp_deadline",
        "pair": "JP",
        "prompt": "面对截止日期，你通常会早早推进，还是常常最后阶段爆发效率？",
        "dimension_targets": ["J", "P"],
        "difficulty": 1,
        "followup_rules": ["若回答因任务而异，追问大多数私事和日常事务的习惯。"],
    },
    {
        "id": "jp_order",
        "pair": "JP",
        "prompt": "你会更喜欢很多事都先有个明确框架，还是保留开放选项到临近再定？",
        "dimension_targets": ["J", "P"],
        "difficulty": 2,
        "followup_rules": ["如果回答两种都好，追问默认倾向。"],
    },
]

PAIR_LEXICONS = {
    "E": ["热闹", "聊天", "见人", "聚会", "一起", "当面", "说出来", "边聊边想", "分享", "社交"],
    "I": ["独处", "安静", "自己", "一个人", "先想", "消化", "观察", "不想说", "冷静", "独立"],
    "S": ["具体", "细节", "步骤", "经验", "实际", "眼前", "事实", "落地", "稳定", "验证"],
    "N": ["可能", "趋势", "未来", "灵感", "概念", "抽象", "脑洞", "模式", "方向", "潜力"],
    "T": ["逻辑", "理性", "客观", "标准", "分析", "效率", "结论", "对错", "判断", "数据"],
    "F": ["感受", "关系", "共情", "体谅", "照顾", "舒服", "温柔", "在意", "情绪", "被理解"],
    "J": ["计划", "提前", "安排", "清单", "可控", "按部就班", "准时", "明确", "框架", "确定"],
    "P": ["随性", "灵活", "看情况", "即兴", "边走边看", "临时", "自由", "最后", "弹性", "开放"],
}

AMBIVALENT_PATTERNS = ("都", "都行", "看情况", "不一定", "一半一半")


def empty_score_map() -> Dict[str, float]:
    return {key: 0.0 for key in SCORE_KEYS}


def empty_pair_confidence() -> Dict[str, float]:
    return {key: 0.0 for key in PAIR_KEYS}


def build_question_map() -> Dict[str, Dict[str, object]]:
    return {str(item["id"]): item for item in QUESTION_BANK}


QUESTION_MAP = build_question_map()


def build_initial_session(now_ms: int) -> Dict[str, object]:
    scores = empty_score_map()
    asked_ids: List[str] = []
    question = select_next_question(scores, asked_ids, {})
    return {
        "status": "active",
        "started_at_ms": int(now_ms),
        "updated_at_ms": int(now_ms),
        "turn_count": 0,
        "effective_turn_count": 0,
        "scores": scores,
        "dimension_confidence": empty_pair_confidence(),
        "asked_question_ids": asked_ids,
        "question_history": [],
        "transcript_history": [],
        "evidence_summary": [],
        "last_question_id": str(question["id"]),
        "latest_question": str(question["prompt"]),
        "latest_transcript": "",
        "question_pair": str(question.get("pair") or ""),
        "question_source": "question_bank",
        "scoring_source": "pending",
        "type_code": "",
        "profile_preview": {},
        "voice_mode": "idle",
        "voice_session_active": False,
    }


def normalize_scores(raw: Optional[Dict[str, object]]) -> Dict[str, float]:
    scores = empty_score_map()
    for key in SCORE_KEYS:
        try:
            scores[key] = float((raw or {}).get(key, 0.0) or 0.0)
        except Exception:
            scores[key] = 0.0
    return scores


def normalize_confidence(raw: Optional[Dict[str, object]]) -> Dict[str, float]:
    conf = empty_pair_confidence()
    for key in PAIR_KEYS:
        try:
            conf[key] = max(0.0, min(1.0, float((raw or {}).get(key, 0.0) or 0.0)))
        except Exception:
            conf[key] = 0.0
    return conf


def derive_type_code(scores: Dict[str, float]) -> str:
    letters = []
    for pair in PAIR_KEYS:
        left, right = PAIR_TO_POLES[pair]
        letters.append(left if float(scores.get(left, 0.0)) >= float(scores.get(right, 0.0)) else right)
    return "".join(letters)


def summarize_profile(scores: Dict[str, float]) -> Dict[str, object]:
    type_code = derive_type_code(scores)
    style_bits: List[str] = []
    if type_code.startswith("I"):
        style_bits.append("更适合给留白和缓冲，不要高密度追问")
    else:
        style_bits.append("可以接受更即时的互动和来回确认")
    if type_code[1:2] == "N":
        style_bits.append("解释时先给整体方向和意义感")
    else:
        style_bits.append("解释时先给具体步骤和确定落点")
    if type_code[2:3] == "T":
        style_bits.append("沟通优先给逻辑与结论")
    else:
        style_bits.append("沟通优先承接感受与关系氛围")
    if type_code[3:4] == "J":
        style_bits.append("提醒与任务尽量提前、明确")
    else:
        style_bits.append("提醒与任务保留弹性空间")
    return {
        "type_code": type_code,
        "summary": "；".join(style_bits[:3]) + "。",
        "response_style": "先贴合这个人的节奏，再给结论和一个最小下一步。",
        "care_style": "保持轻松、稳定、低压的陪伴口吻，不一次问太多。",
    }


def pair_margin(scores: Dict[str, float], pair: str) -> float:
    left, right = PAIR_TO_POLES[pair]
    return float(scores.get(left, 0.0)) - float(scores.get(right, 0.0))


def compute_dimension_confidence(
    scores: Dict[str, float],
    pair_evidence_counts: Optional[Dict[str, object]],
    effective_turn_count: int,
) -> Dict[str, float]:
    output: Dict[str, float] = {}
    evidence_counts = pair_evidence_counts or {}
    for pair in PAIR_KEYS:
        left, right = PAIR_TO_POLES[pair]
        left_score = abs(float(scores.get(left, 0.0)))
        right_score = abs(float(scores.get(right, 0.0)))
        total = left_score + right_score
        evidence = max(0, int(evidence_counts.get(pair, 0) or 0))
        margin = abs(pair_margin(scores, pair))
        base = 0.22 + min(0.32, evidence * 0.08)
        turn_bonus = min(0.22, max(0, effective_turn_count - 2) * 0.015)
        margin_bonus = 0.0 if total <= 0 else min(0.28, (margin / max(1.0, total)) * 0.28)
        saturation = min(0.16, total * 0.018)
        output[pair] = max(0.0, min(0.96, base + turn_bonus + margin_bonus + saturation))
    return output


def should_finish(session: Dict[str, object]) -> Tuple[bool, str]:
    effective_turn_count = int(session.get("effective_turn_count", 0) or 0)
    if effective_turn_count >= 28:
        return True, "hard_cap"
    if effective_turn_count < 12:
        return False, "min_turns"
    confidence = normalize_confidence(session.get("dimension_confidence"))
    if all(confidence.get(pair, 0.0) >= 0.78 for pair in PAIR_KEYS):
        return True, "confidence_met"
    return False, "need_more_signal"


def select_next_pair(scores: Dict[str, float], asked_ids: List[str], confidence: Dict[str, float]) -> str:
    available_pairs = {str(item["pair"]) for item in QUESTION_BANK if str(item["id"]) not in set(asked_ids)}
    if not available_pairs:
        return min(PAIR_KEYS, key=lambda item: confidence.get(item, 0.0))
    return min(available_pairs, key=lambda item: (confidence.get(item, 0.0), abs(pair_margin(scores, item))))


def select_next_question(scores: Dict[str, float], asked_ids: List[str], confidence: Dict[str, float]) -> Dict[str, object]:
    available = [item for item in QUESTION_BANK if str(item["id"]) not in set(asked_ids)]
    if not available:
        asked_ids.clear()
        available = list(QUESTION_BANK)
    pair = select_next_pair(scores, asked_ids, confidence)
    pair_candidates = [item for item in available if str(item["pair"]) == pair]
    if not pair_candidates:
        pair_candidates = available
    pair_candidates = sorted(pair_candidates, key=lambda item: int(item.get("difficulty", 1) or 1))
    return pair_candidates[0]


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


def score_answer_heuristic(question: Dict[str, object], answer: str) -> Dict[str, object]:
    clean = re.sub(r"\s+", " ", str(answer or "").strip())
    lower = clean.lower()
    pair = str(question.get("pair") or "EI")
    left, right = PAIR_TO_POLES[pair]
    left_hits = sum(lower.count(token.lower()) for token in PAIR_LEXICONS[left])
    right_hits = sum(lower.count(token.lower()) for token in PAIR_LEXICONS[right])
    ambivalent = any(token in clean for token in AMBIVALENT_PATTERNS)
    if clean and not left_hits and not right_hits:
        if pair == "EI":
            right_hits = 1 if any(token in clean for token in ("自己", "安静", "缓一缓", "冷静")) else 0
            left_hits = 1 if any(token in clean for token in ("聊聊", "人多", "出去", "说出来")) else 0
        elif pair == "SN":
            left_hits = 1 if any(token in clean for token in ("步骤", "细节", "先做")) else 0
            right_hits = 1 if any(token in clean for token in ("方向", "意义", "可能性")) else 0
        elif pair == "TF":
            left_hits = 1 if any(token in clean for token in ("理性", "结论", "对错")) else 0
            right_hits = 1 if any(token in clean for token in ("感受", "关系", "照顾")) else 0
        elif pair == "JP":
            left_hits = 1 if any(token in clean for token in ("提前", "计划", "安排")) else 0
            right_hits = 1 if any(token in clean for token in ("随缘", "灵活", "临时")) else 0

    deltas = empty_score_map()
    if clean:
        if left_hits == right_hits == 0:
            deltas[left] += 0.35
            deltas[right] += 0.35
        else:
            weight = 1.2 if not ambivalent else 0.7
            deltas[left] += round(left_hits * weight, 2)
            deltas[right] += round(right_hits * weight, 2)
            if left_hits > right_hits:
                deltas[left] += 0.35
            elif right_hits > left_hits:
                deltas[right] += 0.35
    evidence = []
    if clean:
        lead = left if float(deltas[left]) >= float(deltas[right]) else right
        evidence.append(f"{pair}:{lead}:{clean[:48]}")
    return {
        "scores_delta": deltas,
        "pair": pair,
        "evidence_tags": evidence,
        "effective": bool(clean),
        "reasoning": "heuristic-fallback",
    }


def merge_scoring(
    session: Dict[str, object],
    question: Dict[str, object],
    answer: str,
    scoring: Dict[str, object],
    now_ms: int,
) -> Dict[str, object]:
    scores = normalize_scores(session.get("scores"))
    delta_scores = normalize_scores(scoring.get("scores_delta"))
    for key in SCORE_KEYS:
        scores[key] = round(scores[key] + float(delta_scores.get(key, 0.0)), 3)
    pair_counts = dict(session.get("pair_evidence_counts") or {})
    pair = str(scoring.get("pair") or question.get("pair") or "EI")
    if scoring.get("effective"):
        pair_counts[pair] = int(pair_counts.get(pair, 0) or 0) + 1
    evidence_summary = [str(item) for item in session.get("evidence_summary") or [] if str(item).strip()]
    for item in scoring.get("evidence_tags") or []:
        text = str(item).strip()
        if text and text not in evidence_summary:
            evidence_summary.append(text)
    confidence = compute_dimension_confidence(scores, pair_counts, int(session.get("effective_turn_count", 0) or 0) + (1 if scoring.get("effective") else 0))
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
            "pair": pair,
            "timestamp_ms": int(now_ms),
        }
    )
    transcript_history = [dict(item) for item in session.get("transcript_history") or [] if isinstance(item, dict)]
    transcript_history.append(
        {
            "role": "user",
            "text": str(answer or "").strip(),
            "timestamp_ms": int(now_ms),
        }
    )
    type_code = derive_type_code(scores)
    preview = summarize_profile(scores)
    merged = dict(session)
    merged.update(
        {
            "updated_at_ms": int(now_ms),
            "turn_count": int(session.get("turn_count", 0) or 0) + 1,
            "effective_turn_count": int(session.get("effective_turn_count", 0) or 0) + (1 if scoring.get("effective") else 0),
            "scores": scores,
            "dimension_confidence": confidence,
            "pair_evidence_counts": pair_counts,
            "asked_question_ids": asked_ids,
            "question_history": question_history[-32:],
            "transcript_history": transcript_history[-32:],
            "evidence_summary": evidence_summary[-24:],
            "latest_transcript": str(answer or "").strip(),
            "type_code": type_code,
            "profile_preview": preview,
        }
    )
    done, reason = should_finish(merged)
    merged["finish_reason"] = reason
    if done:
        merged["status"] = "completed"
        merged["completed_at_ms"] = int(now_ms)
        merged["latest_question"] = ""
        merged["last_question_id"] = ""
        merged["final_result"] = build_final_profile(merged)
    else:
        next_question = select_next_question(scores, asked_ids, confidence)
        merged["latest_question"] = str(next_question["prompt"])
        merged["last_question_id"] = str(next_question["id"])
        merged["question_pair"] = str(next_question.get("pair") or "")
        merged["question_source"] = "question_bank"
    return merged


def build_final_profile(session: Dict[str, object]) -> Dict[str, object]:
    scores = normalize_scores(session.get("scores"))
    confidence = normalize_confidence(session.get("dimension_confidence"))
    preview = summarize_profile(scores)
    evidence_items = [str(item) for item in session.get("evidence_summary") or [] if str(item).strip()]
    evidence_summary = {
        "highlights": evidence_items[:8],
        "notes": preview.get("summary", ""),
    }
    return {
        "scores": {key: round(float(scores.get(key, 0.0)), 2) for key in SCORE_KEYS},
        "type_code": str(preview.get("type_code") or derive_type_code(scores)),
        "dimension_confidence": {key: round(float(confidence.get(key, 0.0)), 3) for key in PAIR_KEYS},
        "evidence_summary": evidence_summary,
        "conversation_count": int(session.get("effective_turn_count", 0) or 0),
        "completed_at_ms": int(session.get("completed_at_ms", 0) or 0),
        "response_style": str(preview.get("response_style") or ""),
        "care_style": str(preview.get("care_style") or ""),
        "summary": str(preview.get("summary") or ""),
        "inference_version": "assessment-v1",
    }


def build_memory_summary(profile: Dict[str, object], preferred_name: str = "") -> str:
    scores = profile.get("scores") or {}
    parts = [
        f"{preferred_name or '该用户'} 的人格测评已完成",
        f"类型 {str(profile.get('type_code') or '')}",
        "八维分值 "
        + "/".join(f"{key}:{round(float(scores.get(key, 0.0) or 0.0), 1)}" for key in SCORE_KEYS),
        f"建议：{str(profile.get('summary') or '').strip()}",
    ]
    return "；".join(part for part in parts if part).strip("；") + "。"


def extract_scoring_from_model(raw: str) -> Dict[str, object]:
    parsed = parse_json_dict(raw)
    if not parsed:
        return {}
    scores_delta = normalize_scores(parsed.get("scores_delta"))
    return {
        "scores_delta": scores_delta,
        "pair": str(parsed.get("pair") or "").strip() or "",
        "evidence_tags": [str(item).strip() for item in parsed.get("evidence_tags") or [] if str(item).strip()],
        "effective": bool(parsed.get("effective", True)),
        "reasoning": str(parsed.get("reasoning") or "").strip(),
    }


def extract_next_question_from_model(raw: str) -> Dict[str, object]:
    parsed = parse_json_dict(raw)
    question = str(parsed.get("question") or "").strip()
    pair = str(parsed.get("pair") or "").strip()
    if question:
        return {
            "id": str(parsed.get("question_id") or f"model-{abs(hash(question)) % 100000}"),
            "pair": pair if pair in PAIR_KEYS else "EI",
            "prompt": question,
            "dimension_targets": list(PAIR_TO_POLES.get(pair if pair in PAIR_KEYS else "EI", ("E", "I"))),
            "difficulty": 2,
            "followup_rules": [],
        }
    return {}


def extract_termination_from_model(raw: str) -> Dict[str, object]:
    parsed = parse_json_dict(raw)
    return {
        "should_finish": bool(parsed.get("should_finish", False)),
        "reason": str(parsed.get("reason") or "").strip(),
        "missing_pair": str(parsed.get("missing_pair") or "").strip(),
    }
