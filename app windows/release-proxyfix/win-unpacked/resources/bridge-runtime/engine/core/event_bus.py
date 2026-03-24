from __future__ import annotations

from typing import Callable, List

from .types import Event


class EventBus:
    def __init__(self) -> None:
        self._subscribers: List[Callable[[Event], None]] = []

    def subscribe(self, callback: Callable[[Event], None]) -> None:
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[Event], None]) -> None:
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def emit(self, event: Event) -> None:
        for callback in list(self._subscribers):
            try:
                callback(event)
            except Exception:
                # Intentionally swallow subscriber errors to avoid breaking the engine loop.
                continue
