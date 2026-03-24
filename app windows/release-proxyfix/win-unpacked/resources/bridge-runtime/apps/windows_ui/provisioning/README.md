# Windows Provisioning Integration

Windows uses SoftAP provisioning as the default fallback.
This is simple to integrate and works even without BLE.

## CLI usage
From repo root:

```
py scripts/provision_softap.py --ssid "YourWiFi" --password "YourPass"
```

## App integration
Reuse `SoftApProvisioner` from `apps/windows_ui/provisioning/softap_client.py`
to call the HTTP endpoints defined in `protocol/provisioning.md`.
