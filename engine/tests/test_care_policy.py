import json
import os
import tempfile
import unittest

from engine.policy.care_policy import CarePolicy, RiskFrame, Context


class CarePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "nudge": ["nudge"],
                    "care_ack": ["ack"],
                    "care_action": ["action"],
                    "guard": ["guard"],
                },
                handle,
                ensure_ascii=False,
            )
        self.templates_path = path
        self.policy = CarePolicy(self.templates_path)

    def tearDown(self) -> None:
        if os.path.exists(self.templates_path):
            os.remove(self.templates_path)

    def _ctx(self, now_ms: int, **kwargs):
        cfg = {
            "cooldown_min": 15,
            "scene": "desk",
            "thresholds": {"nudge": 0.6, "care": 0.7, "guard": 0.9, "nudge_V": 0.7, "nudge_A": 0.7},
            "sustained_low_activity": {"silence_min_sec": 900, "V_thr": 0.7, "attention_thr": 0.6},
            "peak_to_silence": {"peak_z": 2.0, "peak_window_sec": 30, "silence_after_peak_sec": 10, "max_gap_sec": 120},
            "expression_distress": {
                "enabled": True,
                "min_confidence": 0.55,
                "negative_ids": [3, 4, 5, 6, 7],
                "nudge_thr": 0.40,
                "care_thr": 0.62,
            },
            "fusion": {"wV": 0.45, "wA": 0.25, "wT": 0.30},
            "templates": self.policy.templates,
        }
        return Context(
            device_id="dev",
            scene="desk",
            mode="normal",
            now_ms=now_ms,
            cooldown_until_ms=0,
            daily_count=0,
            daily_limit=5,
            baseline={"rms_mean": 1.0, "rms_std": 0.1},
            cfg={**cfg, **kwargs.get("cfg", {})},
        )

    def test_no_text_records_only(self):
        now_ms = 1_000_000
        ctx = self._ctx(now_ms)
        frame = RiskFrame(ts_ms=now_ms, V=0.2, A=0.2, T=None)
        plan = self.policy.decide(ctx, frame, [])
        self.assertEqual(plan.decision, "RECORD_ONLY")

    def test_cooldown_blocks(self):
        now_ms = 1_000_000
        ctx = self._ctx(now_ms)
        ctx.cooldown_until_ms = now_ms + 60_000
        frame = RiskFrame(ts_ms=now_ms, V=0.9, A=0.9, T=0.9)
        plan = self.policy.decide(ctx, frame, [])
        self.assertEqual(plan.decision, "RECORD_ONLY")

    def test_daily_limit_blocks(self):
        now_ms = 1_000_000
        ctx = self._ctx(now_ms)
        ctx.daily_count = ctx.daily_limit
        frame = RiskFrame(ts_ms=now_ms, V=0.9, A=0.9, T=0.9)
        plan = self.policy.decide(ctx, frame, [])
        self.assertEqual(plan.decision, "RECORD_ONLY")

    def test_peak_to_silence_triggers_guard(self):
        now_ms = 1_000_000
        ctx = self._ctx(now_ms)
        history = [
            RiskFrame(ts_ms=now_ms - 25_000, V=0.3, A=0.3, T=None, A_sub={"rms": 0.2, "silence_sec": 0.0}),
            RiskFrame(ts_ms=now_ms - 20_000, V=0.3, A=0.3, T=None, A_sub={"rms": 2.0, "silence_sec": 0.0}),
            RiskFrame(ts_ms=now_ms - 15_000, V=0.3, A=0.3, T=None, A_sub={"rms": 0.3, "silence_sec": 0.0}),
            RiskFrame(ts_ms=now_ms - 10_000, V=0.3, A=0.3, T=None, A_sub={"rms": 0.1, "silence_sec": 8.0}),
            RiskFrame(ts_ms=now_ms - 5_000, V=0.3, A=0.3, T=None, A_sub={"rms": 0.1, "silence_sec": 12.0}),
        ]
        frame = history[-1]
        plan = self.policy.decide(ctx, frame, history)
        self.assertEqual(plan.decision, "GUARD")

    def test_expression_distress_triggers_nudge_without_text(self):
        now_ms = 1_000_000
        ctx = self._ctx(now_ms)
        frame = RiskFrame(
            ts_ms=now_ms,
            V=0.2,
            A=0.1,
            T=None,
            V_sub={"expression_class_id": 4.0, "expression_confidence": 0.8, "expression_risk": 0.55},
        )
        plan = self.policy.decide(ctx, frame, [])
        self.assertEqual(plan.decision, "NUDGE")

    def test_expression_distress_triggers_care_without_text(self):
        now_ms = 1_000_000
        ctx = self._ctx(now_ms)
        frame = RiskFrame(
            ts_ms=now_ms,
            V=0.3,
            A=0.1,
            T=None,
            V_sub={"expression_class_id": 6.0, "expression_confidence": 0.9, "expression_risk": 0.92},
        )
        plan = self.policy.decide(ctx, frame, [])
        self.assertEqual(plan.decision, "CARE")


if __name__ == "__main__":
    unittest.main()
