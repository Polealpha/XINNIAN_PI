const LOCAL_API_BASE = import.meta.env.VITE_LOCAL_API_BASE || "http://127.0.0.1:8000";
const API_BASE = import.meta.env.VITE_SERVER_API_BASE || import.meta.env.VITE_API_BASE || LOCAL_API_BASE;
const DEVICE_SYNC_API_BASE = import.meta.env.VITE_DEVICE_SYNC_API_BASE || API_BASE;
const REQUEST_TIMEOUT_MS = 8000;
const ASSISTANT_SEND_TIMEOUT_MS = 4 * 60 * 1000;
const DESKTOP_AUDIO_TIMEOUT_MS = 2 * 60 * 1000;
const LOCAL_LLM_TIMEOUT_MS = 90 * 1000;
const ACTIVATION_ASSESSMENT_TIMEOUT_MS = 75 * 1000;

export const getApiBase = () => API_BASE;
export const getDeviceSyncApiBase = () => DEVICE_SYNC_API_BASE;
export const getLocalApiBase = () => LOCAL_API_BASE;

export const getWsBase = () => {
  if (LOCAL_API_BASE.startsWith("https://")) return LOCAL_API_BASE.replace("https://", "wss://");
  if (LOCAL_API_BASE.startsWith("http://")) return LOCAL_API_BASE.replace("http://", "ws://");
  return `ws://${LOCAL_API_BASE}`;
};

const LOCAL_PATH_PREFIXES = [
  "/api/assistant/",
  "/api/desktop/",
  "/api/llm/",
  "/api/activation/",
  "/api/device/owner/",
];

const REMOTE_PATH_PREFIXES = [
  "/api/auth/",
  "/api/user/",
  "/api/chat/",
  "/api/device/",
  "/api/client/",
  "/api/emotion/",
];

const resolveBaseForPath = (path: string) => {
  if (LOCAL_PATH_PREFIXES.some((prefix) => path.startsWith(prefix))) {
    return LOCAL_API_BASE;
  }
  if (REMOTE_PATH_PREFIXES.some((prefix) => path.startsWith(prefix))) {
    return DEVICE_SYNC_API_BASE;
  }
  return API_BASE;
};

const resolveTimeoutForPath = (path: string, overrideTimeoutMs?: number) => {
  if (typeof overrideTimeoutMs === "number" && Number.isFinite(overrideTimeoutMs) && overrideTimeoutMs > 0) {
    return overrideTimeoutMs;
  }
  if (path === "/api/assistant/send") {
    return ASSISTANT_SEND_TIMEOUT_MS;
  }
  if (path.startsWith("/api/llm/care")) {
    return ASSISTANT_SEND_TIMEOUT_MS;
  }
  if (path === "/api/desktop/voice/transcribe") {
    return DESKTOP_AUDIO_TIMEOUT_MS;
  }
  if (
    path === "/api/activation/assessment/start" ||
    path === "/api/activation/assessment/turn" ||
    path === "/api/activation/assessment/finish"
  ) {
    return ACTIVATION_ASSESSMENT_TIMEOUT_MS;
  }
  if (path.startsWith("/api/llm/")) {
    return LOCAL_LLM_TIMEOUT_MS;
  }
  return REQUEST_TIMEOUT_MS;
};

export const getAccessToken = (): string | null => {
  return localStorage.getItem("auth_token");
};

export const setAccessToken = (token: string) => {
  localStorage.setItem("auth_token", token);
};

export const setRefreshToken = (token: string) => {
  localStorage.setItem("refresh_token", token);
};

const refreshAccessToken = async () => {
  const refreshToken = localStorage.getItem("refresh_token");
  if (!refreshToken) {
    throw new Error("No refresh token");
  }
  const response = await fetch(`${DEVICE_SYNC_API_BASE}/api/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!response.ok) {
    throw new Error(`Refresh failed: ${response.status}`);
  }
  const data = await response.json();
  if (data?.access_token) {
    setAccessToken(data.access_token);
  }
  if (data?.refresh_token) {
    setRefreshToken(data.refresh_token);
  }
  return data;
};

const buildHeaders = (withAuth: boolean) => {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (withAuth) {
    const token = getAccessToken();
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
  }
  return headers;
};

const buildAuthHeadersOnly = (withAuth: boolean) => {
  const headers: Record<string, string> = {};
  if (withAuth) {
    const token = getAccessToken();
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
  }
  return headers;
};

const fetchWithTimeout = async (url: string, init: RequestInit, timeoutMs = REQUEST_TIMEOUT_MS) => {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    window.clearTimeout(timer);
  }
};

const buildHttpError = async (response: Response, method: string, path: string) => {
  let detail = "";
  try {
    const text = await response.text();
    if (text) {
      try {
        const parsed = JSON.parse(text);
        detail = String(parsed?.detail || parsed?.message || text).trim();
      } catch {
        detail = text.trim();
      }
    }
  } catch {
    detail = "";
  }
  const suffix = detail ? `: ${detail}` : "";
  return new Error(`${method} ${path} failed: ${response.status}${suffix}`);
};

export const apiGet = async (path: string, withAuth = true, retried = false, timeoutMs?: number) => {
  const base = resolveBaseForPath(path);
  const response = await fetchWithTimeout(`${base}${path}`, {
    method: "GET",
    headers: buildHeaders(withAuth),
  }, resolveTimeoutForPath(path, timeoutMs));
  if (response.status === 401 && withAuth && !retried) {
    await refreshAccessToken();
    return apiGet(path, withAuth, true, timeoutMs);
  }
  if (!response.ok) {
    throw await buildHttpError(response, "GET", path);
  }
  return response.json();
};

export const apiPost = async (path: string, body: unknown, withAuth = true, retried = false, timeoutMs?: number) => {
  const base = resolveBaseForPath(path);
  const response = await fetchWithTimeout(`${base}${path}`, {
    method: "POST",
    headers: buildHeaders(withAuth),
    body: body === undefined ? undefined : JSON.stringify(body),
  }, resolveTimeoutForPath(path, timeoutMs));
  if (response.status === 401 && withAuth && !retried) {
    await refreshAccessToken();
    return apiPost(path, body, withAuth, true, timeoutMs);
  }
  if (!response.ok) {
    throw await buildHttpError(response, "POST", path);
  }
  return response.json();
};

export const apiPostForm = async (path: string, body: FormData, withAuth = true, retried = false, timeoutMs?: number) => {
  const base = resolveBaseForPath(path);
  const response = await fetchWithTimeout(`${base}${path}`, {
    method: "POST",
    headers: buildAuthHeadersOnly(withAuth),
    body,
  }, resolveTimeoutForPath(path, timeoutMs));
  if (response.status === 401 && withAuth && !retried) {
    await refreshAccessToken();
    return apiPostForm(path, body, withAuth, true, timeoutMs);
  }
  if (!response.ok) {
    throw await buildHttpError(response, "POST", path);
  }
  return response.json();
};
