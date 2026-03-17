from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.types import CarePlan, Context, RiskFrame, ScriptStep


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def zscore(x: float, mean: float, std: float) -> float:
    return (x - mean) / max(1e-6, std)


def zscore_inverse(x: float, mean: float, std: float) -> float:
    return clamp01((mean - x) / (3 * max(1e-6, std)))


class CarePolicy:
    def __init__(self, templates_path: str) -> None:
        self.templates = self._load_templates(Path(templates_path))

    def decide(self, ctx: Context, frame: RiskFrame, history: List[RiskFrame]) -> CarePlan:
        cfg = ctx.cfg
        cooldown_min = int(cfg.get("cooldown_min", 15))
        thresholds = cfg.get("thresholds", {})

        if ctx.mode == "privacy_on":
            return CarePlan(
                text="",
                style="warm",
                motion={},
                emo={},
                followup_question="",
                reason={"rule": "privacy_on"},
                policy={"interrupt": False},
                decision="IGNORE",
                level=0,
                steps=[],
                cooldown_min=cooldown_min,
                record_event=False,
                event_type="NONE",
            )

        if ctx.now_ms < ctx.cooldown_until_ms:
            return CarePlan(
                text="",
                style="warm",
                motion={},
                emo={},
                followup_question="",
                reason={"rule": "cooldown"},
                policy={"interrupt": False},
                decision="RECORD_ONLY",
                level=0,
                steps=[],
                cooldown_min=cooldown_min,
                record_event=True,
                event_type="COOLDOWN_BLOCK",
            )

        if ctx.daily_count >= ctx.daily_limit:
            return CarePlan(
                text="",
                style="warm",
                motion={},
                emo={},
                followup_question="",
                reason={"rule": "daily_limit"},
                policy={"interrupt": False},
                decision="RECORD_ONLY",
                level=0,
                steps=[],
                cooldown_min=cooldown_min,
                record_event=True,
                event_type="DAILY_LIMIT_BLOCK",
            )

        if ctx.mode == "quiet":
            return CarePlan(
                text="",
                style="warm",
                motion={},
                emo={},
                followup_question="",
                reason={"rule": "quiet_mode"},
                policy={"interrupt": False},
                decision="RECORD_ONLY",
                level=0,
                steps=[],
                cooldown_min=cooldown_min,
                record_event=True,
                event_type="QUIET_RECORD",
            )

        pB = detect_peak_to_silence(history, cfg.get("peak_to_silence", {}), ctx.baseline)
        if pB is not None:
            return build_guard_plan(ctx, frame, pB, cooldown_min)

        pA = detect_sustained_low_activity(history, cfg.get("sustained_low_activity", {}))
        if pA is not None:
            if frame.T is None:
                return build_nudge_plan(ctx, frame, pA, cooldown_min)
            S = fuse_score(frame.V, frame.A, frame.T, cfg.get("fusion", {}))
            payload = {"pattern": pA["pattern"], "S": S, **pA}
            if S >= thresholds.get("care", 0.7):
                return build_care_plan(ctx, frame, payload, cooldown_min)
            return build_nudge_plan(ctx, frame, payload, cooldown_min)

        pE = detect_expression_distress(frame, cfg.get("expression_distress", {}))
        if pE is not None:
            payload = {"pattern": pE["pattern"], **pE}
            if pE.get("level") == "care":
                return build_care_plan(ctx, frame, payload, cooldown_min)
            return build_nudge_plan(ctx, frame, payload, cooldown_min)

        if frame.T is None:
            if ctx.scene == "desk" and (
                frame.V >= thresholds.get("nudge_V", 0.7)
                or frame.A >= thresholds.get("nudge_A", 0.7)
            ):
                return build_nudge_plan(ctx, frame, {"pattern": "score_only_no_text"}, cooldown_min)
            return CarePlan(
                text="",
                style="warm",
                motion={},
                emo={},
                followup_question="",
                reason={"rule": "no_text"},
                policy={"interrupt": False},
                decision="RECORD_ONLY",
                level=0,
                steps=[],
                cooldown_min=cooldown_min,
                record_event=True,
                event_type="TREND_ONLY",
            )

        S = fuse_score(frame.V, frame.A, frame.T, cfg.get("fusion", {}))
        if S >= thresholds.get("guard", 0.9):
            return build_guard_plan(ctx, frame, {"pattern": "score_guard", "S": S}, cooldown_min)
        if S >= thresholds.get("care", 0.7):
            return build_care_plan(ctx, frame, {"pattern": "score_care", "S": S}, cooldown_min)
        if S >= thresholds.get("nudge", 0.6):
            return build_nudge_plan(ctx, frame, {"pattern": "score_nudge", "S": S}, cooldown_min)

        return CarePlan(
            text="",
            style="warm",
            motion={},
            emo={},
            followup_question="",
            reason={"S": S, "rule": "below_threshold"},
            policy={"interrupt": False},
            decision="RECORD_ONLY",
            level=0,
            steps=[],
            cooldown_min=cooldown_min,
            record_event=True,
            event_type="LOW_RISK",
        )

    def _load_templates(self, path: Path) -> Dict[str, List[str]]:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8-sig"))


def detect_sustained_low_activity(history: List[RiskFrame], cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not history:
        return None
    last = history[-1]
    silence_sec = last.A_sub.get("silence_sec", 0.0)
    fatigue = last.V_sub.get("fatigue", last.V)
    attention_drop = last.V_sub.get("attention_drop", 0.0)

    silence_min_sec = float(cfg.get("silence_min_sec", 900))
    v_thr = float(cfg.get("V_thr", 0.7))
    attention_thr = float(cfg.get("attention_thr", 0.6))

    if silence_sec >= silence_min_sec and (fatigue >= v_thr or attention_drop >= attention_thr):
        severity = min(1.0, 0.5 * fatigue + 0.5 * min(1.0, silence_sec / (silence_min_sec * 2)))
        return {
            "pattern": "sustained_low_activity",
            "severity": severity,
            "explain": {
                "silence_sec": silence_sec,
                "fatigue": fatigue,
                "attention_drop": attention_drop,
            },
        }
    return None


def detect_peak_to_silence(
    history: List[RiskFrame], cfg: Dict[str, Any], baseline: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    if len(history) < 5:
        return None
    rms_mean = float(baseline.get("rms_mean", 0.0))
    rms_std = max(1e-6, float(baseline.get("rms_std", 1.0)))
    now = history[-1].ts_ms
    silence_sec = history[-1].A_sub.get("silence_sec", 0.0)

    peak_z = float(cfg.get("peak_z", 3.0))
    peak_window_sec = float(cfg.get("peak_window_sec", 30))
    silence_after_peak_sec = float(cfg.get("silence_after_peak_sec", 45))
    max_gap_sec = float(cfg.get("max_gap_sec", 120))

    peak_found = False
    peak_ts = None
    for fr in reversed(history):
        dt = (now - fr.ts_ms) / 1000.0
        if dt > max_gap_sec:
            break
        if dt <= peak_window_sec:
            rms = fr.A_sub.get("rms", 0.0)
            if (rms - rms_mean) / rms_std >= peak_z:
                peak_found = True
                peak_ts = fr.ts_ms
                break

    if peak_found and silence_sec >= silence_after_peak_sec:
        severity = min(1.0, 0.6 + 0.4 * min(1.0, silence_sec / 120.0))
        return {
            "pattern": "peak_to_silence",
            "severity": severity,
            "explain": {"peak_ts_ms": peak_ts, "silence_sec": silence_sec, "peak_z": peak_z},
        }
    return None


def detect_expression_distress(frame: RiskFrame, cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not bool(cfg.get("enabled", True)):
        return None
    conf = float(frame.V_sub.get("expression_confidence", 0.0))
    expr_id = int(frame.V_sub.get("expression_class_id", -1))
    expr_risk = float(frame.V_sub.get("expression_risk", 0.0))
    min_conf = float(cfg.get("min_confidence", 0.45))
    negative_ids = {int(v) for v in (cfg.get("negative_ids", [3, 4, 5, 6, 7]) or [])}
    nudge_thr = float(cfg.get("nudge_thr", 0.40))
    care_thr = float(cfg.get("care_thr", 0.62))

    if conf < min_conf or expr_id < 0:
        return None
    if expr_id not in negative_ids:
        return None
    if expr_risk < nudge_thr:
        return None

    level = "nudge"
    if expr_risk >= care_thr:
        level = "care"
    return {
        "pattern": "expression_distress",
        "severity": clamp01(expr_risk),
        "level": level,
        "explain": {
            "expression_class_id": expr_id,
            "expression_confidence": conf,
            "expression_risk": expr_risk,
        },
    }


def fuse_score(V: float, A: float, T: float, cfg: Dict[str, Any]) -> float:
    wV = float(cfg.get("wV", 0.45))
    wA = float(cfg.get("wA", 0.25))
    wT = float(cfg.get("wT", 0.30))
    return clamp01(wV * V + wA * A + wT * T)


def pick_template(kind: str, templates: Dict[str, List[str]]) -> str:
    options = templates.get(kind, [])
    if options:
        return random.choice(options)
    return ""


def build_nudge_plan(ctx: Context, fr: RiskFrame, reason: Dict[str, Any], cooldown_min: int) -> CarePlan:
    text = pick_template("nudge", ctx.cfg.get("templates", {})) or "我注意到你刚刚比较安静。要不要先停30秒，喝口水？"
    steps = [
        ScriptStep("EMO", {"face": "soft", "level": 0.6, "duration_ms": 2200}),
        ScriptStep("MOVE", {"name": "turn_to_user", "intensity": 0.35, "duration_ms": 900}),
        ScriptStep("SAY", {"text": text, "voice": "warm", "priority": 1}),
    ]
    return CarePlan(
        text=text,
        style="warm",
        motion={"type": "micro", "intensity": 0.35},
        emo={"type": "soft", "level": 0.6},
        followup_question="",
        reason=reason,
        policy={"interrupt": True},
        decision="NUDGE",
        level=1,
        steps=steps,
        cooldown_min=cooldown_min,
        record_event=True,
        event_type="NUDGE",
    )


def build_care_plan(ctx: Context, fr: RiskFrame, reason: Dict[str, Any], cooldown_min: int) -> CarePlan:
    text1 = pick_template("care_ack", ctx.cfg.get("templates", {})) or "我感觉你可能有点紧绷。"
    text2 = pick_template("care_action", ctx.cfg.get("templates", {})) or "我们先做个30秒的小暂停：放松肩膀，深呼吸一下。"
    steps = [
        ScriptStep("EMO", {"face": "soft", "level": 0.7, "duration_ms": 2500}),
        ScriptStep("MOVE", {"name": "micro_nod", "intensity": 0.25, "duration_ms": 700}),
        ScriptStep("SAY", {"text": text1, "voice": "warm", "priority": 2}),
        ScriptStep("WAIT", {"duration_ms": 1200}),
        ScriptStep("SAY", {"text": text2, "voice": "warm", "priority": 2}),
        ScriptStep("WAIT", {"duration_ms": 2000}),
        ScriptStep("SAY", {"text": "如果你不想被打扰，我也可以安静一会儿。", "voice": "warm", "priority": 1}),
    ]
    return CarePlan(
        text=text1,
        style="warm",
        motion={"type": "micro_nod", "intensity": 0.25},
        emo={"type": "soft", "level": 0.7},
        followup_question="",
        reason=reason,
        policy={"interrupt": True},
        decision="CARE",
        level=2,
        steps=steps,
        cooldown_min=cooldown_min,
        record_event=True,
        event_type="CARE",
    )


def build_guard_plan(ctx: Context, fr: RiskFrame, reason: Dict[str, Any], cooldown_min: int) -> CarePlan:
    text1 = pick_template("guard", ctx.cfg.get("templates", {})) or "刚刚那一下可能挺难受的。我在。"
    text2 = "你不想说也没关系，晚上我可以帮你整理一下。"
    steps = [
        ScriptStep("MOVE", {"name": "freeze_guard"}),
        ScriptStep("EMO", {"face": "calm_low", "level": 0.5, "duration_ms": 4000}),
        ScriptStep("SAY", {"text": text1, "voice": "warm", "priority": 3}),
        ScriptStep("WAIT", {"duration_ms": 1000}),
        ScriptStep("SAY", {"text": text2, "voice": "warm", "priority": 2}),
    ]
    return CarePlan(
        text=text1,
        style="warm",
        motion={"type": "freeze_guard"},
        emo={"type": "calm_low", "level": 0.5},
        followup_question="",
        reason=reason,
        policy={"interrupt": True},
        decision="GUARD",
        level=3,
        steps=steps,
        cooldown_min=cooldown_min,
        record_event=True,
        event_type="GUARD",
    )
