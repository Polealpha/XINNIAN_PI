const QWEN_HTTP_BASE = (import.meta.env.VITE_QWEN_OMNI_BASE || "http://127.0.0.1:8091").replace(/\/+$/, "");

export interface QwenReadyStatus {
  ok: boolean;
  detail: string;
}

const withTimeout = async <T>(factory: (signal: AbortSignal) => Promise<T>, timeoutMs = 4000) => {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await factory(controller.signal);
  } finally {
    window.clearTimeout(timer);
  }
};

export const probeQwenReady = async (): Promise<QwenReadyStatus> => {
  try {
    const response = await withTimeout((signal) =>
      fetch(`${QWEN_HTTP_BASE}/v1/models`, {
        method: "GET",
        signal,
      })
    );
    if (!response.ok) {
      return { ok: false, detail: `HTTP ${response.status}` };
    }
    const payload = await response.json().catch(() => ({}));
    const firstModel = Array.isArray(payload?.data) ? payload.data[0] : null;
    const modelId = String(firstModel?.id || "").trim();
    return {
      ok: true,
      detail: modelId || "Qwen3-Omni ready",
    };
  } catch (error) {
    return {
      ok: false,
      detail: error instanceof Error ? error.message : String(error),
    };
  }
};
