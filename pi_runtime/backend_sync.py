from __future__ import annotations

import logging
import queue
import threading
from typing import Callable, Dict, Optional

import httpx

from .config import BackendSyncConfig

logger = logging.getLogger(__name__)


class BackendSyncClient:
    def __init__(
        self,
        config: BackendSyncConfig,
        device_id: str,
        status_provider: Callable[[], Dict[str, object]],
        pending_owner_provider: Callable[[], Optional[Dict[str, object]]],
        mark_owner_synced: Callable[[str], None],
        signal_handler: Optional[Callable[[Dict[str, object]], None]] = None,
    ) -> None:
        self._config = config
        self._device_id = device_id
        self._status_provider = status_provider
        self._pending_owner_provider = pending_owner_provider
        self._mark_owner_synced = mark_owner_synced
        self._signal_handler = signal_handler
        self._stop = threading.Event()
        self._event_queue: "queue.Queue[Optional[Dict[str, object]]]" = queue.Queue(maxsize=128)
        self._threads: list[threading.Thread] = []

    @property
    def enabled(self) -> bool:
        return bool(self._config.enabled and str(self._config.base_url or "").strip())

    def start(self) -> None:
        if not self.enabled or self._threads:
            return
        self._stop.clear()
        self._threads = [
            threading.Thread(target=self._heartbeat_loop, name="pi-backend-heartbeat", daemon=True),
            threading.Thread(target=self._event_loop, name="pi-backend-events", daemon=True),
        ]
        if self._signal_handler is not None:
            self._threads.append(threading.Thread(target=self._signal_loop, name="pi-backend-signals", daemon=True))
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._event_queue.put_nowait(None)
        except Exception:
            pass
        for thread in list(self._threads):
            thread.join(timeout=2.0)
        self._threads.clear()

    def enqueue_event(self, event) -> None:
        if not self.enabled:
            return
        payload = {
            "type": str(getattr(event, "type", "")),
            "timestamp_ms": int(getattr(event, "timestamp_ms", 0) or 0),
            "payload": dict(getattr(event, "payload", {}) or {}),
        }
        try:
            self._event_queue.put_nowait(payload)
        except queue.Full:
            try:
                self._event_queue.get_nowait()
            except Exception:
                pass
            try:
                self._event_queue.put_nowait(payload)
            except Exception:
                pass

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(max(2, int(self._config.heartbeat_interval_sec))):
            if not self.enabled:
                continue
            try:
                status_payload = dict(self._status_provider() or {})
                heartbeat_payload = {
                    "device_id": self._device_id,
                    "last_seen_ms": int(status_payload.get("timestamp_ms") or 0),
                    "ssid": status_payload.get("ssid"),
                    "status": status_payload,
                }
                self._post_json("/api/device/heartbeat", heartbeat_payload)
            except Exception as exc:
                logger.debug("backend heartbeat failed: %s", exc)
            try:
                pending = self._pending_owner_provider()
                if pending:
                    payload = dict(pending)
                    payload["device_id"] = self._device_id
                    response = self._post_json("/api/device/owner/enrollment", payload)
                    version = str((response or {}).get("embedding_version") or payload.get("embedding_version") or "")
                    if version:
                        self._mark_owner_synced(version)
            except Exception as exc:
                logger.debug("owner enrollment sync failed: %s", exc)

    def _event_loop(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._event_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if item is None:
                break
            try:
                self._post_json("/api/engine/event", item)
            except Exception as exc:
                logger.debug("backend event push failed: %s", exc)

    def _signal_loop(self) -> None:
        while not self._stop.is_set():
            try:
                signals = self._post_json("/api/engine/signal/pull", {"limit": 16}).get("signals") or []
                for signal in signals:
                    if self._stop.is_set():
                        break
                    if isinstance(signal, dict) and self._signal_handler is not None:
                        self._signal_handler(signal)
            except Exception as exc:
                logger.debug("backend signal pull failed: %s", exc)
            self._stop.wait(max(0.2, float(self._config.signal_poll_interval_sec)))

    def _post_json(self, path: str, payload: Dict[str, object]) -> Dict[str, object]:
        base = str(self._config.base_url or "").rstrip("/")
        if not base:
            return {}
        with httpx.Client(timeout=float(self._config.timeout_sec)) as client:
            response = client.post(f"{base}{path}", json=payload)
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else {}
