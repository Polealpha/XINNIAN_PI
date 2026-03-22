from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import math
import random
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class EyeDef:
    x: float
    y: float
    w: float
    h: float
    r: float
    rot: float
    color: int


@dataclass(frozen=True)
class ExpressionDef:
    id: str
    left: EyeDef
    right: EyeDef


@dataclass
class EyeAnim:
    x: float
    y: float
    w: float
    h: float
    r: float
    rot: float
    r_col: float
    g_col: float
    b_col: float


@dataclass(frozen=True)
class MoodProfile:
    blink_min_ms: int
    blink_max_ms: int
    breath_speed_ms: float
    breath_amp_y: float
    breath_amp_h: float
    gaze_amp_x: float
    gaze_amp_y: float
    gaze_period_ms: float


class ExpressionSurface:
    VARIANT_SWITCH_MIN_MS = 2200
    VARIANT_SWITCH_MAX_MS = 4200
    MOOD_SWITCH_MIN_MS = 8500
    MOOD_SWITCH_MAX_MS = 12500
    TRANSITION_MIN_MS = 500
    TRANSITION_MAX_MS = 900
    ANIM_SMOOTH = 0.15

    SETTINGS_PREFIX = "思考"
    ONBOARDING_PREFIX = "困惑"
    LISTENING_PREFIX = "思考"
    OWNER_PREFIX = "开心"
    GUARD_PREFIX = "难过"

    DEFAULT_PROFILE = MoodProfile(
        blink_min_ms=2600,
        blink_max_ms=5200,
        breath_speed_ms=900.0,
        breath_amp_y=3.0,
        breath_amp_h=2.2,
        gaze_amp_x=0.9,
        gaze_amp_y=0.5,
        gaze_period_ms=5200.0,
    )

    MOOD_PROFILES: Dict[str, MoodProfile] = {
        "常规": MoodProfile(3000, 5600, 950.0, 2.4, 2.0, 0.8, 0.4, 5400.0),
        "开心": MoodProfile(2200, 3800, 760.0, 3.8, 2.0, 1.2, 0.7, 4000.0),
        "难过": MoodProfile(2600, 4600, 1150.0, 1.8, 1.4, 0.5, 0.6, 6400.0),
        "愤怒": MoodProfile(2100, 3600, 700.0, 3.0, 1.7, 1.7, 0.9, 3300.0),
        "惊讶": MoodProfile(1800, 3200, 620.0, 4.0, 2.5, 1.5, 1.1, 3000.0),
        "思考": MoodProfile(3200, 5400, 980.0, 2.2, 1.8, 2.2, 1.2, 4200.0),
        "生病": MoodProfile(2400, 4200, 1200.0, 1.6, 1.1, 0.4, 0.6, 5600.0),
        "爱心": MoodProfile(2200, 3600, 720.0, 3.4, 2.0, 1.2, 0.8, 3600.0),
        "困倦": MoodProfile(1500, 2600, 1350.0, 1.4, 0.9, 0.2, 0.3, 7600.0),
        "兴奋": MoodProfile(1800, 3200, 640.0, 4.2, 2.3, 2.0, 1.0, 2800.0),
        "困惑": MoodProfile(2500, 4200, 900.0, 2.6, 1.8, 2.1, 1.1, 3600.0),
        "害羞": MoodProfile(2000, 3400, 780.0, 3.0, 1.7, 0.9, 0.8, 4400.0),
        "酷酷": MoodProfile(3100, 5200, 880.0, 2.5, 1.5, 1.1, 0.4, 5000.0),
    }

    def __init__(self, catalog_path: str | Path) -> None:
        raw = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
        self._expressions: List[ExpressionDef] = [
            ExpressionDef(
                id=str(item["id"]),
                left=EyeDef(**item["left"]),
                right=EyeDef(**item["right"]),
            )
            for item in raw
        ]
        if not self._expressions:
            raise ValueError("expression catalog is empty")

        self._mood_prefixes: List[str] = []
        self._prefix_to_indices: Dict[str, List[int]] = {}
        self._index_to_slot: Dict[int, tuple[int, int]] = {}
        for idx, item in enumerate(self._expressions):
            prefix = self._expression_prefix(item.id)
            if prefix not in self._prefix_to_indices:
                self._mood_prefixes.append(prefix)
                self._prefix_to_indices[prefix] = []
            slot_index = len(self._prefix_to_indices[prefix])
            self._prefix_to_indices[prefix].append(idx)
            self._index_to_slot[idx] = (self._mood_prefixes.index(prefix), slot_index)

        self._mood_count = len(self._mood_prefixes)
        self._current_mood = 0
        self._current_variant = 0
        self._target_mood = 0
        self._target_variant = 0
        self._transitioning = False
        self._transition_start_ms = 0
        self._transition_ms = self.TRANSITION_MIN_MS
        self._next_variant_ms = 0
        self._next_mood_ms = 0
        self._next_blink_ms = 0
        self._blink_end_ms = 0
        self._blinking = False
        self._manual_expression_index: Optional[int] = None
        self._last_reason = "idle"
        self._anim_left = self._init_eye_anim(self._expressions[0].left)
        self._anim_right = self._init_eye_anim(self._expressions[0].right)
        self._schedule(0)

    @property
    def expressions(self) -> List[ExpressionDef]:
        return list(self._expressions)

    def set_expression_index(self, index: Optional[int]) -> None:
        if index is None:
            self._manual_expression_index = None
            return
        index_i = int(index)
        if 0 <= index_i < len(self._expressions):
            mood, variant = self._index_to_slot.get(index_i, (0, 0))
            self._manual_expression_index = index_i
            self._target_mood = mood
            self._target_variant = variant
            self._current_mood = mood
            self._current_variant = variant
            self._transitioning = False
            self._schedule_blink(0, self._expressions[index_i].id)

    def set_expression_id(self, expression_id: str) -> bool:
        expression_id = str(expression_id or "").strip()
        if not expression_id:
            return False
        for idx, item in enumerate(self._expressions):
            if item.id == expression_id:
                self.set_expression_index(idx)
                return True
        return False

    def _expression_prefix(self, expression_id: str) -> str:
        return str(expression_id or "").split("_", 1)[0].strip()

    def _profile_for_expression(self, expression_id: str) -> MoodProfile:
        return self.MOOD_PROFILES.get(self._expression_prefix(expression_id), self.DEFAULT_PROFILE)

    def _init_eye_anim(self, eye: EyeDef) -> EyeAnim:
        return EyeAnim(
            x=float(eye.x),
            y=float(eye.y),
            w=float(eye.w),
            h=float(eye.h),
            r=float(eye.r),
            rot=float(eye.rot),
            r_col=float((eye.color >> 11) & 0x1F),
            g_col=float((eye.color >> 5) & 0x3F),
            b_col=float(eye.color & 0x1F),
        )

    def _schedule(self, now_ms: int) -> None:
        self._next_variant_ms = now_ms + random.randint(self.VARIANT_SWITCH_MIN_MS, self.VARIANT_SWITCH_MAX_MS)
        self._next_mood_ms = now_ms + random.randint(self.MOOD_SWITCH_MIN_MS, self.MOOD_SWITCH_MAX_MS)
        self._transition_ms = random.randint(self.TRANSITION_MIN_MS, self.TRANSITION_MAX_MS)
        self._schedule_blink(now_ms, self._expressions[self._get_expression_index(self._current_mood, self._current_variant)].id)

    def _schedule_blink(self, now_ms: int, expression_id: str) -> None:
        profile = self._profile_for_expression(expression_id)
        self._next_blink_ms = now_ms + random.randint(profile.blink_min_ms, profile.blink_max_ms)

    def _lerp(self, start: float, end: float, amount: float) -> float:
        return start + ((end - start) * amount)

    def _update_eye(self, current: EyeAnim, target: EyeDef) -> None:
        current.x = self._lerp(current.x, float(target.x), self.ANIM_SMOOTH)
        current.y = self._lerp(current.y, float(target.y), self.ANIM_SMOOTH)
        current.w = self._lerp(current.w, float(target.w), self.ANIM_SMOOTH)
        current.h = self._lerp(current.h, float(target.h), self.ANIM_SMOOTH)
        current.r = self._lerp(current.r, float(target.r), self.ANIM_SMOOTH)
        current.rot = self._lerp(current.rot, float(target.rot), self.ANIM_SMOOTH)
        current.r_col = self._lerp(current.r_col, float((target.color >> 11) & 0x1F), self.ANIM_SMOOTH)
        current.g_col = self._lerp(current.g_col, float((target.color >> 5) & 0x3F), self.ANIM_SMOOTH)
        current.b_col = self._lerp(current.b_col, float(target.color & 0x1F), self.ANIM_SMOOTH)

    def _color_hex(self, eye: EyeAnim) -> str:
        r = int(max(0, min(255, round((eye.r_col / 31.0) * 255.0))))
        g = int(max(0, min(255, round((eye.g_col / 63.0) * 255.0))))
        b = int(max(0, min(255, round((eye.b_col / 31.0) * 255.0))))
        return f"#{r:02x}{g:02x}{b:02x}"

    def _variant_count_for_mood(self, mood: int) -> int:
        if not self._mood_prefixes:
            return 1
        prefix = self._mood_prefixes[mood % self._mood_count]
        return max(1, len(self._prefix_to_indices.get(prefix) or []))

    def _get_expression_index(self, mood: int, variant: int) -> int:
        if not self._mood_prefixes:
            return 0
        prefix = self._mood_prefixes[mood % self._mood_count]
        indices = self._prefix_to_indices.get(prefix) or [0]
        return indices[max(0, min(len(indices) - 1, int(variant)))]

    def _find_prefix(self, prefix: str) -> int:
        normalized = str(prefix or "").rstrip("_").strip()
        indices = self._prefix_to_indices.get(normalized)
        if indices:
            return indices[0]
        return 0

    def _pick_context_expression(self, runtime_state: Dict[str, Any]) -> int:
        if self._manual_expression_index is not None:
            self._last_reason = "manual"
            return self._manual_expression_index
        ui_page = str(runtime_state.get("ui_page") or "expression")
        voice_mode = str(runtime_state.get("voice_mode") or "idle")
        owner_recognized = bool(runtime_state.get("owner_recognized"))
        onboarding_mode = str(runtime_state.get("onboarding_state") or "")
        risk_score = float(runtime_state.get("risk_score") or 0.0)
        if ui_page == "settings":
            self._last_reason = "settings"
            return self._find_prefix(self.SETTINGS_PREFIX)
        if onboarding_mode and onboarding_mode != "connected":
            self._last_reason = "onboarding"
            return self._find_prefix(self.ONBOARDING_PREFIX)
        if voice_mode in {"assessment", "wake_listen"}:
            self._last_reason = "listening"
            return self._find_prefix(self.LISTENING_PREFIX)
        if owner_recognized:
            self._last_reason = "owner"
            return self._find_prefix(self.OWNER_PREFIX)
        if risk_score >= 0.8:
            self._last_reason = "guard"
            return self._find_prefix(self.GUARD_PREFIX)
        self._last_reason = "ambient"
        return self._get_expression_index(self._current_mood, self._current_variant)

    def update(self, now_ms: int, runtime_state: Dict[str, Any]) -> None:
        desired_index = self._pick_context_expression(runtime_state)
        desired_mood, desired_variant = self._index_to_slot.get(desired_index, (0, 0))

        if self._manual_expression_index is None and desired_index == self._get_expression_index(self._current_mood, self._current_variant):
            if now_ms >= self._next_mood_ms:
                self._target_mood = (self._current_mood + 1) % max(1, self._mood_count)
                self._target_variant = 0
                self._transitioning = True
                self._transition_start_ms = now_ms
                self._next_mood_ms = now_ms + random.randint(self.MOOD_SWITCH_MIN_MS, self.MOOD_SWITCH_MAX_MS)
                self._next_variant_ms = now_ms + random.randint(self.VARIANT_SWITCH_MIN_MS, self.VARIANT_SWITCH_MAX_MS)
            elif now_ms >= self._next_variant_ms and not self._transitioning:
                self._target_mood = self._current_mood
                self._target_variant = (self._current_variant + 1) % self._variant_count_for_mood(self._current_mood)
                self._transitioning = True
                self._transition_start_ms = now_ms
                self._transition_ms = random.randint(self.TRANSITION_MIN_MS, self.TRANSITION_MAX_MS)
                self._next_variant_ms = now_ms + random.randint(self.VARIANT_SWITCH_MIN_MS, self.VARIANT_SWITCH_MAX_MS)
        elif desired_mood != self._current_mood or desired_variant != self._current_variant:
            if (
                not self._transitioning
                or desired_mood != self._target_mood
                or desired_variant != self._target_variant
            ):
                self._target_mood = desired_mood
                self._target_variant = desired_variant
                self._transitioning = True
                self._transition_start_ms = now_ms
                self._transition_ms = random.randint(self.TRANSITION_MIN_MS, self.TRANSITION_MAX_MS)

        if self._transitioning and (now_ms - self._transition_start_ms) >= self._transition_ms:
            self._current_mood = self._target_mood
            self._current_variant = self._target_variant
            self._transitioning = False

        if not self._blinking and now_ms >= self._next_blink_ms:
            self._blinking = True
            self._blink_end_ms = now_ms + 140
        elif self._blinking and now_ms >= self._blink_end_ms:
            self._blinking = False
            current_expr = self._expressions[self._get_expression_index(self._current_mood, self._current_variant)]
            self._schedule_blink(now_ms, current_expr.id)

        target_expr = self._expressions[self._get_expression_index(self._target_mood, self._target_variant)]
        self._update_eye(self._anim_left, target_expr.left)
        self._update_eye(self._anim_right, target_expr.right)

    def snapshot(self, now_ms: int, runtime_state: Dict[str, Any]) -> Dict[str, Any]:
        self.update(now_ms, runtime_state)
        current_index = self._get_expression_index(self._current_mood, self._current_variant)
        current_expr = self._expressions[current_index]
        prefix = self._expression_prefix(current_expr.id)
        profile = self._profile_for_expression(current_expr.id)

        tracking_gaze_x = float(runtime_state.get("gaze_x") or 0.0)
        tracking_gaze_y = float(runtime_state.get("gaze_y") or 0.0)
        phase = now_ms / max(1.0, profile.gaze_period_ms)
        idle_gaze_x = math.sin(phase) * profile.gaze_amp_x
        idle_gaze_y = math.cos(phase + 0.35) * profile.gaze_amp_y
        total_gaze_x = tracking_gaze_x + idle_gaze_x
        total_gaze_y = tracking_gaze_y + idle_gaze_y

        return {
            "expression_id": current_expr.id,
            "expression_index": current_index,
            "mood_prefix": prefix,
            "reason": self._last_reason,
            "blinking": self._blinking,
            "transitioning": self._transitioning,
            "gaze_x": round(total_gaze_x, 2),
            "gaze_y": round(total_gaze_y, 2),
            "tracking_gaze_x": round(tracking_gaze_x, 2),
            "tracking_gaze_y": round(tracking_gaze_y, 2),
            "idle_gaze_x": round(idle_gaze_x, 2),
            "idle_gaze_y": round(idle_gaze_y, 2),
            "breath_speed_ms": round(profile.breath_speed_ms, 2),
            "breath_amp_y": round(profile.breath_amp_y, 2),
            "breath_amp_h": round(profile.breath_amp_h, 2),
            "left": {
                "x": round(self._anim_left.x, 2),
                "y": round(self._anim_left.y, 2),
                "w": round(self._anim_left.w, 2),
                "h": round(self._anim_left.h, 2),
                "r": round(self._anim_left.r, 2),
                "rot": round(self._anim_left.rot, 2),
                "color": self._color_hex(self._anim_left),
            },
            "right": {
                "x": round(self._anim_right.x, 2),
                "y": round(self._anim_right.y, 2),
                "w": round(self._anim_right.w, 2),
                "h": round(self._anim_right.h, 2),
                "r": round(self._anim_right.r, 2),
                "rot": round(self._anim_right.rot, 2),
                "color": self._color_hex(self._anim_right),
            },
        }

    def render_svg(self, now_ms: int, runtime_state: Dict[str, Any], width: int = 320, height: int = 240) -> str:
        state = self.snapshot(now_ms, runtime_state)
        breath_speed = float(state.get("breath_speed_ms") or self.DEFAULT_PROFILE.breath_speed_ms)
        breath_y = math.sin(now_ms / max(1.0, breath_speed)) * float(state.get("breath_amp_y") or self.DEFAULT_PROFILE.breath_amp_y)
        breath_h = math.sin((now_ms / max(1.0, breath_speed)) + 1.5) * float(
            state.get("breath_amp_h") or self.DEFAULT_PROFILE.breath_amp_h
        )
        gaze_x = float(state.get("gaze_x") or 0.0)
        gaze_y = float(state.get("gaze_y") or 0.0)

        def rect_svg(eye: Dict[str, Any]) -> str:
            draw_h = 2.0 if state["blinking"] else (float(eye["h"]) + breath_h)
            x = float(eye["x"]) - (float(eye["w"]) / 2.0) + gaze_x
            y = float(eye["y"]) - (draw_h / 2.0) + breath_y + gaze_y
            w = float(eye["w"])
            h = max(2.0, draw_h)
            rx = max(1.0, min(float(eye["r"]), h / 2.0, w / 2.0))
            cx = x + (w / 2.0)
            cy = y + (h / 2.0)
            transform = ""
            if abs(float(eye["rot"])) >= 0.1:
                transform = f' transform="rotate({eye["rot"]} {cx:.2f} {cy:.2f})"'
            return (
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" '
                f'rx="{rx:.2f}" ry="{rx:.2f}" fill="{eye["color"]}"{transform}/>'
            )

        reason = str(state["reason"])
        expression_id = str(state["expression_id"])
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">'
            "<defs>"
            '<radialGradient id="bgGlow" cx="50%" cy="20%" r="65%">'
            '<stop offset="0%" stop-color="#0f2740"/>'
            '<stop offset="55%" stop-color="#07111f"/>'
            '<stop offset="100%" stop-color="#030711"/>'
            "</radialGradient>"
            "</defs>"
            f'<rect width="{width}" height="{height}" fill="url(#bgGlow)"/>'
            '<circle cx="160" cy="120" r="98" fill="rgba(103,232,249,0.06)"/>'
            f'{rect_svg(state["left"])}'
            f'{rect_svg(state["right"])}'
            '<rect x="24" y="196" width="272" height="24" rx="12" ry="12" fill="#0b1322" opacity="0.9"/>'
            f'<text x="160" y="212" text-anchor="middle" fill="#9fb5d9" font-size="12" font-family="Microsoft YaHei, PingFang SC, sans-serif">{expression_id} | {reason}</text>'
            "</svg>"
        )
