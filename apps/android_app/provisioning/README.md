# Android Provisioning Integration

This project supports two provisioning modes:
- BLE provisioning (ESP-IDF provisioning, recommended)
- SoftAP HTTP provisioning (fallback)

## BLE Provisioning (recommended)
Use Espressif's Android provisioning SDK.
You only need the service name (WIFI_PROV_SERVICE) and POP (WIFI_PROV_POP)
that are configured in the firmware build flags.

Suggested flow:
1) Scan BLE for devices advertising the service name.
2) Connect and start provisioning.
3) Send SSID/password.
4) Wait for success.

Notes for hotspot:
- Auto-reading hotspot SSID/PSK can be restricted on some Android versions.
- Always allow manual entry for hotspot SSID/password.

## SoftAP Provisioning (fallback)
When BLE is not available, connect the phone to the device SoftAP
and call the HTTP endpoints described in `protocol/provisioning.md`.

You can use OkHttp to call:
- `GET /prov/info`
- `POST /prov/config`
- `POST /prov/commit`
- `GET /prov/status`
