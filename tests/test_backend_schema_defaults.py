from backend.schemas import ProvisionExecuteRequest, ProvisionRequest


def test_provision_defaults_are_not_ble():
    assert ProvisionRequest(device_id="pi-zero", ssid="wifi", password="secret").transport == "direct"
    assert ProvisionExecuteRequest(device_id="pi-zero", ssid="wifi", password="secret").transport == "direct"
