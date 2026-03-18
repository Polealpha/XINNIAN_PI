import { apiGet, apiPost } from "./apiClient";

export const provisionDevice = async (
  deviceId: string,
  ssid: string,
  password: string,
  deviceIp?: string,
  options?: {
    transport?: "ble" | "softap";
    serviceName?: string;
    pop?: string;
    timeoutSec?: number;
  }
) => {
  return apiPost(
    "/api/device/provision/execute",
    {
      device_id: deviceId,
      ssid,
      password,
      device_ip: deviceIp || undefined,
      transport: options?.transport || "ble",
      service_name: options?.serviceName,
      pop: options?.pop,
      timeout_sec: options?.timeoutSec,
    },
    true
  );
};

export const getDeviceStatus = async (deviceId?: string, deviceIp?: string) => {
  const params = new URLSearchParams();
  if (deviceId) params.set("device_id", deviceId);
  if (deviceIp) params.set("device_ip", deviceIp);
  const query = params.toString();
  const path = query ? `/api/device/status?${query}` : "/api/device/status";
  return apiGet(path, true);
};

export const listDevices = async () => {
  return apiGet("/api/device/list", true);
};

export const heartbeatClientSession = async (payload: {
  client_type: "mobile" | "desktop";
  client_id: string;
  current_ssid?: string;
  client_ip?: string;
  device_id?: string;
  is_active?: boolean;
}) => {
  return apiPost("/api/client/session/heartbeat", payload, true);
};
