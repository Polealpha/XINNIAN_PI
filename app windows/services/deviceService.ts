import { apiGet, apiPost } from "./apiClient";

const normalizeDeviceRuntimeBase = (hostOrUrl: string) => {
  const raw = String(hostOrUrl || "").trim();
  if (!raw) throw new Error("device_runtime_host_required");
  const withScheme = /^https?:\/\//i.test(raw) ? raw : `http://${raw}`;
  return withScheme.replace(/\/+$/, "");
};

const fetchDeviceRuntime = async (hostOrUrl: string, path: string, init?: RequestInit) => {
  const base = normalizeDeviceRuntimeBase(hostOrUrl);
  const response = await fetch(`${base}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `device_runtime_http_${response.status}`);
  }
  return response.json();
};

export const getDeviceOnboardingState = async (deviceHost: string) => {
  return fetchDeviceRuntime(deviceHost, "/onboarding/state", {
    method: "GET",
  });
};

export const listDeviceOnboardingNetworks = async (deviceHost: string) => {
  return fetchDeviceRuntime(deviceHost, "/onboarding/networks", {
    method: "GET",
  });
};

export const configureDeviceWifiLocal = async (deviceHost: string, ssid: string, password: string) => {
  return fetchDeviceRuntime(deviceHost, "/onboarding/wifi", {
    method: "POST",
    body: JSON.stringify({
      ssid,
      password,
    }),
  });
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

export const getDeviceSettings = async (deviceId?: string) => {
  const params = new URLSearchParams();
  if (deviceId) params.set("device_id", deviceId);
  const query = params.toString();
  const path = query ? `/api/device/settings?${query}` : "/api/device/settings";
  return apiGet(path, true);
};

export const updateDeviceSettings = async (payload: { device_id?: string; settings: Record<string, unknown> }) => {
  return apiPost("/api/device/settings", payload, true);
};

export const openDeviceSettingsPage = async (payload: { device_id?: string; source?: string } = {}) => {
  return apiPost("/api/device/settings/open", payload, true);
};

export const closeDeviceSettingsPage = async (payload: { device_id?: string; source?: string } = {}) => {
  return apiPost("/api/device/settings/close", payload, true);
};

export const sendDevicePanTiltLocal = async (
  deviceHost: string,
  payload: { pan: number; tilt: number }
) => {
  return fetchDeviceRuntime(deviceHost, "/pan_tilt", {
    method: "POST",
    body: JSON.stringify(payload),
  });
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
