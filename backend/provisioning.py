from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import asyncio
import json
import os
import subprocess
import sys
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

DEFAULT_BLE_SERVICE = os.environ.get("WIFI_PROV_SERVICE", "PROV_XINNIAN")
DEFAULT_POP = os.environ.get("WIFI_PROV_POP", "1234")
DEFAULT_SOFTAP_HOST = os.environ.get("WIFI_PROV_SOFTAP_HOST", "192.168.4.1:80")


@dataclass
class ProvisionResult:
    ok: bool
    message: Optional[str]
    logs: str


def _find_esp_prov_path() -> Optional[Path]:
    candidates = []
    home = Path.home()
    candidates.append(
        home
        / ".platformio"
        / "packages"
        / "framework-espidf"
        / "tools"
        / "esp_prov"
        / "esp_prov.py"
    )
    idf_path = os.environ.get("IDF_PATH")
    if idf_path:
        candidates.append(Path(idf_path) / "tools" / "esp_prov" / "esp_prov.py")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _default_service_for_transport(transport: str) -> str:
    if transport == "softap":
        return DEFAULT_SOFTAP_HOST
    return DEFAULT_BLE_SERVICE


def _looks_like_host(value: str) -> bool:
    if not value:
        return False
    if ":" in value:
        return True
    return "." in value


def _resolve_ble_service(service: str) -> str:
    service = (service or "").strip()
    if not service:
        return service
    try:
        from bleak import BleakScanner  # type: ignore

        async def _scan() -> list[str]:
            devices = await BleakScanner.discover(timeout=5.0)
            names = [d.name for d in devices if d.name]
            return list(dict.fromkeys(names))

        names = asyncio.run(_scan())
        if service in names:
            return service
        base = "_".join(service.split("_")[:-1]).strip()
        if base:
            matches = [name for name in names if name.startswith(base)]
            if len(matches) == 1:
                return matches[0]
    except Exception:
        return service
    return service


def _parse_qr_payload(qr_payload: Optional[str]) -> Optional[dict]:
    payload = (qr_payload or "").strip()
    if not payload:
        return None

    def _load_json(text: str) -> Optional[dict]:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        return data

    if payload.startswith("{"):
        direct = _load_json(payload)
        if direct:
            return direct

    try:
        parsed = urlparse(payload)
        query = parse_qs(parsed.query)
        data_param = query.get("data", [None])[0]
        if data_param:
            decoded = unquote(data_param)
            nested = _load_json(decoded)
            if nested:
                return nested
    except Exception:
        return None

    return None


def _trim_logs(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


def _derive_message(output: str) -> Optional[str]:
    lower = output.lower()
    if "modulenotfounderror" in lower and "google" in lower:
        return "Missing dependency: protobuf (pip install protobuf)."
    if "modulenotfounderror" in lower and "bleak" in lower:
        return "Missing dependency: bleak (pip install bleak)."
    if "modulenotfounderror" in lower and "cryptography" in lower:
        return "Missing dependency: cryptography (pip install cryptography)."
    if "device not found" in lower:
        return "BLE device not found."
    if "failed to initialize transport" in lower:
        return "Failed to initialize BLE transport."
    if "failed to establish connection" in lower:
        return "Failed to connect to the provisioning service."
    if "auth failed" in lower:
        return "Wi-Fi auth failed."
    if "ap not found" in lower:
        return "Wi-Fi AP not found."
    if "provisioning was successful" in lower:
        return None
    if "provisioning failed" in lower:
        return "Provisioning failed."
    return None


def run_provisioning(
    transport: str,
    ssid: str,
    password: str,
    service_name: Optional[str] = None,
    pop: Optional[str] = None,
    qr_payload: Optional[str] = None,
    timeout_sec: int = 120,
) -> ProvisionResult:
    transport = transport.lower().strip()
    if transport not in {"ble", "softap"}:
        return ProvisionResult(ok=False, message="Unsupported transport.", logs="")

    esp_prov_path = _find_esp_prov_path()
    if not esp_prov_path:
        return ProvisionResult(
            ok=False,
            message="esp_prov.py not found (install ESP-IDF or PlatformIO).",
            logs="",
        )

    qr_info = _parse_qr_payload(qr_payload)
    if qr_payload and not qr_info:
        return ProvisionResult(ok=False, message="Invalid provisioning QR payload.", logs="")

    qr_transport = str(qr_info.get("transport", "")).lower().strip() if qr_info else ""
    if qr_transport in {"ble", "softap"}:
        transport = qr_transport

    qr_service = str(qr_info.get("name", "")).strip() if qr_info else ""
    qr_pop = str(qr_info.get("pop", "")).strip() if qr_info else ""

    service = ""
    if transport == "softap":
        explicit = (service_name or "").strip()
        if _looks_like_host(explicit):
            service = explicit
        else:
            service = _default_service_for_transport(transport)
    else:
        service = (service_name or "").strip() or qr_service or _default_service_for_transport(transport)
    pop_value = (pop or "").strip() or qr_pop or DEFAULT_POP

    if transport == "ble":
        service = _resolve_ble_service(service)

    cmd = [
        sys.executable,
        str(esp_prov_path),
        "--transport",
        transport,
        "--service_name",
        service,
        "--sec_ver",
        "1",
        "--pop",
        pop_value,
        "--ssid",
        ssid,
        "--passphrase",
        password or "",
    ]

    env = os.environ.copy()
    env.setdefault("IDF_PATH", str(esp_prov_path.parents[2]))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return ProvisionResult(ok=False, message="Provisioning timed out.", logs="")

    output = "\n".join(filter(None, [result.stdout, result.stderr]))
    ok = "Provisioning was successful" in output
    message = _derive_message(output)
    if not ok and message is None:
        message = "Provisioning failed."
    return ProvisionResult(ok=ok, message=message, logs=_trim_logs(output))
