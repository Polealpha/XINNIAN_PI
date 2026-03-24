import json
from typing import Any, Dict, Optional

import requests


class SoftApProvisioner:
    def __init__(self, base_url: str = "http://192.168.4.1") -> None:
        self.base_url = base_url.rstrip("/")

    def info(self) -> Dict[str, Any]:
        return self._get("/prov/info")

    def scan(self) -> Dict[str, Any]:
        return self._post("/prov/scan", {})

    def configure(
        self,
        ssid: str,
        password: str,
        token: str = "",
        country: str = "CN",
    ) -> Dict[str, Any]:
        payload = {
            "ssid": ssid,
            "password": password,
            "token": token,
            "country": country,
        }
        return self._post("/prov/config", payload)

    def commit(self) -> Dict[str, Any]:
        return self._post("/prov/commit", {})

    def status(self) -> Dict[str, Any]:
        return self._get("/prov/status")

    def _get(self, path: str) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return self._parse_json(response.text)

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return self._parse_json(response.text)

    def _parse_json(self, text: str) -> Dict[str, Any]:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text}
