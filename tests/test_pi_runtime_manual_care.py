from pi_runtime.runtime import PiEmotionRuntime


def test_manual_care_returns_plan():
    runtime = PiEmotionRuntime("config/pi_zero2w.json", "config/engine_config.json")
    payload = runtime.manual_care("测试一下手动关怀")
    care_plan = payload["care_plan"]
    assert care_plan["decision"] == "CARE"
    assert isinstance(care_plan["text"], str)
    assert care_plan["text"]
