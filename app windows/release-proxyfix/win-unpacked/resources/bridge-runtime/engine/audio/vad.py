from __future__ import annotations

from typing import Optional


class SimpleVAD:
    def __init__(self, energy_ratio: float = 3.0, min_energy: float = 200.0) -> None:
        self.energy_ratio = energy_ratio
        self.min_energy = min_energy
        self._noise_floor: Optional[float] = None

    def update(self, rms: float) -> bool:
        if self._noise_floor is None:
            self._noise_floor = rms
        else:
            if rms < self._noise_floor:
                self._noise_floor = 0.95 * self._noise_floor + 0.05 * rms
        threshold = max(self._noise_floor * self.energy_ratio, self.min_energy)
        return rms >= threshold

    def reset(self) -> None:
        self._noise_floor = None
