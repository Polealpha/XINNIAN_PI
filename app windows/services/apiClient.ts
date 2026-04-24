const LOCAL_API_BASE = import.meta.env.VITE_LOCAL_API_BASE || "http://127.0.0.1:8012";
const API_BASE = import.meta.env.VITE_SERVER_API_BASE || import.meta.env.VITE_API_BASE || LOCAL_API_BASE;
const DEVICE_SYNC_API_BASE = import.meta.env.VITE_DEVICE_SYNC_API_BASE || API_BASE;
const REQUEST_TIMEOUT_MS = 8000;
const ASSISTANT_SEND_TIMEOUT_MS = 4 * 60 * 1000;
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
  "/api/vision/",
];

const REMOTE_PATH_PREFIXES = [
  "/api/auth/",
  "/api/user/",
  "/api/chat/",
  "/api/device/",
  "/api/client/",
  "/api/emotion/",
];

const LOCAL_BACKEND_TOKEN_KEY = "local_backend_token";

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

const isLocalPath = (path: string) => LOCAL_PATH_PREFIXES.some((prefix) => path.startsWith(prefix));

export const getAccessToken = (): string | null => {
  return localStorage.getItem("auth_token");
};

export const setAccessToken = (token: string) => {
  localStorage.setItem("auth_token", token);
};

export const setRefreshToken = (token: string) => {
  localStorage.setItem("refresh_token", token);
};

export const getLocalBackendToken = (): string | null => {
  return localStorage.getItem(LOCAL_BACKEND_TOKEN_KEY);
};

export const setLocalBackendToken = (token: string) => {
  localStorage.setItem(LOCAL_BACKEND_TOKEN_KEY, token);
};

const refreshRemoteAccessToken = async () => {
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

const bootstrapLocalBackendToken = async () => {
  const response = await fetch(`${LOCAL_API_BASE}/api/desktop/auth/bootstrap`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (!response.ok) {
    throw new Error(`Local bootstrap failed: ${response.status}`);
  }
  const data = await response.json();
  const token = String(data?.access_token || "").trim();
  if (!token) {
    throw new Error("Local bootstrap returned empty token");
  }
  setLocalBackendToken(token);
  return token;
};

const ensureLocalBackendToken = async () => {
  const existing = getLocalBackendToken();
  if (existing) return existing;
  return bootstrapLocalBackendToken();
};

const refreshAccessToken = async (path: string) => {
  if (isLocalPath(path)) {
    return bootstrapLocalBackendToken();
  }
  return refreshRemoteAccessToken();
};

const buildHeaders = async (path: string, withAuth: boolean) => {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (withAuth) {
    const token = isLocalPath(path) ? await ensureLocalBackendToken() : getAccessToken();
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
  }
  return headers;
};

const buildAuthHeadersOnly = async (path: string, withAuth: boolean) => {
  const headers: Record<string, string> = {};
  if (withAuth) {
    const token = isLocalPath(path) ? await ensureLocalBackendToken() : getAccessToken();
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
  }
  return headers;
};

const fetchWithTimeout = async (
  url: string,
  init: RequestInit,
  timeoutMs = REQUEST_TIMEOUT_MS,
  externalSignal?: AbortSignal,
) => {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (externalSignal?.aborted) {
    abort();
  }
  externalSignal?.addEventListener("abort", abort, { once: true });
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    window.clearTimeout(timer);
    externalSignal?.removeEventListener("abort", abort);
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
    headers: await buildHeaders(path, withAuth),
  }, resolveTimeoutForPath(path, timeoutMs));
  if (response.status === 401 && withAuth && !retried) {
    await refreshAccessToken(path);
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
    headers: await buildHeaders(path, withAuth),
    body: body === undefined ? undefined : JSON.stringify(body),
  }, resolveTimeoutForPath(path, timeoutMs));
  if (response.status === 401 && withAuth && !retried) {
    await refreshAccessToken(path);
    return apiPost(path, body, withAuth, true, timeoutMs);
  }
  if (!response.ok) {
    throw await buildHttpError(response, "POST", path);
  }
  return response.json();
};

export const apiPostStream = async (
  path: string,
  body: unknown,
  withAuth = true,
  retried = false,
  timeoutMs?: number,
  signal?: AbortSignal,
) => {
  const base = resolveBaseForPath(path);
  const response = await fetchWithTimeout(`${base}${path}`, {
    method: "POST",
    headers: await buildHeaders(path, withAuth),
    body: body === undefined ? undefined : JSON.stringify(body),
  }, resolveTimeoutForPath(path, timeoutMs), signal);
  if (response.status === 401 && withAuth && !retried) {
    await refreshAccessToken(path);
    return apiPostStream(path, body, withAuth, true, timeoutMs, signal);
  }
  if (!response.ok) {
    throw await buildHttpError(response, "POST", path);
  }
  return response;
};

export const apiPostForm = async (path: string, body: FormData, withAuth = true, retried = false, timeoutMs?: number) => {
  const base = resolveBaseForPath(path);
  const response = await fetchWithTimeout(`${base}${path}`, {
    method: "POST",
    headers: await buildAuthHeadersOnly(path, withAuth),
    body,
  }, resolveTimeoutForPath(path, timeoutMs));
  if (response.status === 401 && withAuth && !retried) {
    await refreshAccessToken(path);
    return apiPostForm(path, body, withAuth, true, timeoutMs);
  }
  if (!response.ok) {
    throw await buildHttpError(response, "POST", path);
  }
  return response.json();
};
