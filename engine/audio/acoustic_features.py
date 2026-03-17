from __future__ import annotations

from array import array
import math
from typing import Dict


def extract_features(pcm_s16le: bytes) -> Dict[str, float]:
    samples = array("h")
    samples.frombytes(pcm_s16le)
    count = len(samples)
    if count == 0:
        return {"rms": 0.0, "peak": 0.0, "zcr": 0.0}
    energy = 0.0
    peak = 0.0
    zero_crossings = 0
    last_sign = 0
    for sample in samples:
        value = float(sample)
        energy += value * value
        abs_val = abs(value)
        if abs_val > peak:
            peak = abs_val
        sign = 1 if value >= 0 else -1
        if last_sign and sign != last_sign:
            zero_crossings += 1
        last_sign = sign
    rms = math.sqrt(energy / count)
    zcr = zero_crossings / float(count)
    return {"rms": rms, "peak": peak, "zcr": zcr}
