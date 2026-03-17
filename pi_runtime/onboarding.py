from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, List

from .config import OnboardingConfig

logger = logging.getLogger(__name__)


class OnboardingManager:
    def __init__(self, config: OnboardingConfig) -> None:
        self._config = config
        self._state_path = Path(config.state_file)
        self._state = self._load_state()

    def ensure_bootstrap_mode(self) -> Dict[str, object]:
        if not self._config.enabled or not self._nmcli_available():
            return self.get_state()
        current_ssid = self.current_ssid()
        if current_ssid:
            if self._state.get("hotspot_active"):
                self._stop_hotspot()
            self._state.update(
                {
                    "mode": "connected",
                    "connected_ssid": current_ssid,
                    "hotspot_active": False,
                    "needs_onboarding": False,
                    "updated_at_ms": int(time.time() * 1000),
                }
            )
            self._save_state()
            return self.get_state()
        self._start_hotspot()
        return self.get_state()

    def get_state(self) -> Dict[str, object]:
        current_ssid = self.current_ssid()
        state = dict(self._state)
        state["connected_ssid"] = current_ssid
        state["needs_onboarding"] = not bool(current_ssid)
        state["wifi_interface"] = self._config.wifi_interface
        state["hotspot_ssid"] = self._config.hotspot_ssid
        return state

    def current_ssid(self) -> str:
        if not self._nmcli_available():
            return ""
        rows = self._run_nmcli(
            [
                "nmcli",
                "-t",
                "-f",
                "DEVICE,TYPE,STATE,CONNECTION",
                "device",
                "status",
            ]
        )
        for row in rows:
            parts = row.split(":")
            if len(parts) < 4:
                continue
            device, dev_type, state, connection = parts[0], parts[1], parts[2], parts[3]
            if device == self._config.wifi_interface and dev_type == "wifi" and state == "connected":
                if connection and connection != self._config.hotspot_connection_name:
                    return connection
        return ""

    def scan_networks(self) -> List[Dict[str, object]]:
        if not self._nmcli_available():
            return []
        rows = self._run_nmcli(
            [
                "nmcli",
                "-t",
                "-f",
                "SSID,SIGNAL,SECURITY",
                "device",
                "wifi",
                "list",
                "ifname",
                self._config.wifi_interface,
                "--rescan",
                "yes",
            ]
        )
        results: List[Dict[str, object]] = []
        seen = set()
        for row in rows:
            parts = row.split(":")
            if len(parts) < 3:
                continue
            ssid = str(parts[0] or "").strip()
            if not ssid or ssid in seen:
                continue
            seen.add(ssid)
            try:
                signal = int(parts[1] or 0)
            except Exception:
                signal = 0
            results.append(
                {
                    "ssid": ssid,
                    "signal": signal,
                    "security": str(parts[2] or "").strip(),
                }
            )
        results.sort(key=lambda item: int(item.get("signal") or 0), reverse=True)
        return results

    def configure_wifi(self, ssid: str, password: str) -> Dict[str, object]:
        ssid = str(ssid or "").strip()
        if not ssid:
            raise ValueError("ssid required")
        if not self._nmcli_available():
            raise RuntimeError("nmcli unavailable")
        connection_name = self._wifi_connection_name(ssid)
        self._stop_hotspot()
        if self._connection_exists(connection_name):
            self._run_nmcli(
                [
                    "nmcli",
                    "connection",
                    "modify",
                    connection_name,
                    "802-11-wireless.ssid",
                    ssid,
                    "connection.autoconnect",
                    "yes",
                ],
                check=True,
            )
        else:
            self._run_nmcli(
                [
                    "nmcli",
                    "connection",
                    "add",
                    "type",
                    "wifi",
                    "ifname",
                    self._config.wifi_interface,
                    "con-name",
                    connection_name,
                    "ssid",
                    ssid,
                ],
                check=True,
            )
        if password:
            self._run_nmcli(
                [
                    "nmcli",
                    "connection",
                    "modify",
                    connection_name,
                    "wifi-sec.key-mgmt",
                    "wpa-psk",
                    "wifi-sec.psk",
                    password,
                ],
                check=True,
            )
        else:
            self._run_nmcli(
                [
                    "nmcli",
                    "connection",
                    "modify",
                    connection_name,
                    "wifi-sec.key-mgmt",
                    "",
                ],
                check=True,
            )
        self._run_nmcli(["nmcli", "connection", "up", connection_name], check=True)
        self._state.update(
            {
                "mode": "wifi_configured",
                "connected_ssid": ssid,
                "hotspot_active": False,
                "needs_onboarding": False,
                "last_error": "",
                "updated_at_ms": int(time.time() * 1000),
            }
        )
        self._save_state()
        return self.get_state()

    def reset(self) -> Dict[str, object]:
        self._state = {
            "mode": "onboarding",
            "connected_ssid": "",
            "hotspot_active": False,
            "needs_onboarding": True,
            "last_error": "",
            "updated_at_ms": int(time.time() * 1000),
        }
        self._save_state()
        self._start_hotspot()
        return self.get_state()

    def _start_hotspot(self) -> None:
        if not self._nmcli_available():
            return
        try:
            if not self._connection_exists(self._config.hotspot_connection_name):
                self._run_nmcli(
                    [
                        "nmcli",
                        "device",
                        "wifi",
                        "hotspot",
                        "ifname",
                        self._config.wifi_interface,
                        "con-name",
                        self._config.hotspot_connection_name,
                        "ssid",
                        self._config.hotspot_ssid,
                        "password",
                        self._config.hotspot_password,
                    ],
                    check=True,
                )
            else:
                self._run_nmcli(["nmcli", "connection", "up", self._config.hotspot_connection_name], check=True)
            self._state.update(
                {
                    "mode": "onboarding",
                    "connected_ssid": "",
                    "hotspot_active": True,
                    "needs_onboarding": True,
                    "last_error": "",
                    "updated_at_ms": int(time.time() * 1000),
                }
            )
            self._save_state()
        except Exception as exc:
            self._state["last_error"] = str(exc)
            self._save_state()
            logger.warning("start hotspot failed: %s", exc)

    def _stop_hotspot(self) -> None:
        if not self._nmcli_available():
            return
        try:
            self._run_nmcli(["nmcli", "connection", "down", self._config.hotspot_connection_name], check=False)
        except Exception:
            pass
        self._state["hotspot_active"] = False
        self._state["updated_at_ms"] = int(time.time() * 1000)
        self._save_state()

    def _wifi_connection_name(self, ssid: str) -> str:
        safe = "".join(ch if ch.isalnum() else "-" for ch in ssid).strip("-")
        safe = safe or "wifi"
        return f"emotion-wifi-{safe}"

    def _connection_exists(self, connection_name: str) -> bool:
        rows = self._run_nmcli(["nmcli", "-t", "-f", "NAME", "connection", "show"])
        return connection_name in {str(row or "").strip() for row in rows}

    def _nmcli_available(self) -> bool:
        return bool(shutil.which("nmcli"))

    def _run_nmcli(self, cmd: List[str], check: bool = False) -> List[str]:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        if check and result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "nmcli failed").strip())
        output = result.stdout or ""
        return [line.strip() for line in output.splitlines() if line.strip()]

    def _load_state(self) -> Dict[str, object]:
        try:
            if self._state_path.exists():
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return {
            "mode": "idle",
            "connected_ssid": "",
            "hotspot_active": False,
            "needs_onboarding": True,
            "last_error": "",
            "updated_at_ms": 0,
        }

    def _save_state(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")
