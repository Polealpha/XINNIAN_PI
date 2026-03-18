const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";
const DEVICE_SYNC_API_BASE = import.meta.env.VITE_DEVICE_SYNC_API_BASE || API_BASE;
const REQUEST_TIMEOUT_MS = 8000;

export const getApiBase = () => API_BASE;
export const getDeviceSyncApiBase = () => DEVICE_SYNC_API_BASE;

export const getWsBase = () => {
  if (API_BASE.startsWith("https://")) return API_BASE.replace("https://", "wss://");
  if (API_BASE.startsWith("http://")) return API_BASE.replace("http://", "ws://");
  return `ws://${API_BASE}`;
};

const SERVER_PATH_PREFIXES = ["/api/auth/", "/api/user/", "/api/chat/"];

const resolveBaseForPath = (path: string) => {
  return SERVER_PATH_PREFIXES.some((prefix) => path.startsWith(prefix)) ? DEVICE_SYNC_API_BASE : API_BASE;
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

export const apiGet = async (path: string, withAuth = true, retried = false) => {
  const base = resolveBaseForPath(path);
  const response = await fetchWithTimeout(`${base}${path}`, {
    method: "GET",
    headers: buildHeaders(withAuth),
  });
  if (response.status === 401 && withAuth && !retried) {
    await refreshAccessToken();
    return apiGet(path, withAuth, true);
  }
  if (!response.ok) {
    throw new Error(`GET ${path} failed: ${response.status}`);
  }
  return response.json();
};

export const apiPost = async (path: string, body: unknown, withAuth = true, retried = false) => {
  const base = resolveBaseForPath(path);
  const response = await fetchWithTimeout(`${base}${path}`, {
    method: "POST",
    headers: buildHeaders(withAuth),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 401 && withAuth && !retried) {
    await refreshAccessToken();
    return apiPost(path, body, withAuth, true);
  }
  if (!response.ok) {
    throw new Error(`POST ${path} failed: ${response.status}`);
  }
  return response.json();
};

export const apiPostForm = async (path: string, body: FormData, withAuth = true, retried = false) => {
  const base = resolveBaseForPath(path);
  const response = await fetchWithTimeout(`${base}${path}`, {
    method: "POST",
    headers: buildAuthHeadersOnly(withAuth),
    body,
  });
  if (response.status === 401 && withAuth && !retried) {
    await refreshAccessToken();
    return apiPostForm(path, body, withAuth, true);
  }
  if (!response.ok) {
    throw new Error(`POST ${path} failed: ${response.status}`);
  }
  return response.json();
};
