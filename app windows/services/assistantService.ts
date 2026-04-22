import { apiGet, apiPost, getWsBase } from "./apiClient";

export interface AssistantTodoItem {
  id: string;
  title: string;
  details: string;
  state: string;
  created_at_ms: number;
  updated_at_ms: number;
  due_at_ms?: number | null;
  notified_at_ms?: number | null;
  tags: string[];
  action?: Record<string, unknown>;
}

export interface AssistantRuntimeStatus {
  ok: boolean;
  gateway_ready: boolean;
  gateway_error: string;
  provider_network_ok: boolean;
  provider_network_detail: string;
  state_dir: string;
  workspace_dir: string;
  desktop_tools: string[];
  robot_bridge_ready: boolean;
  native_duplex_ws_base?: string;
  assistant_model?: string;
  provider_base_url?: string;
}

export interface AssistantDuplexConfig {
  ok: boolean;
  provider: string;
  mode: string;
  ws_base: string;
  audio_chunk_ms: number;
  sample_rate: number;
  transport: string;
}

export interface AssistantSessionStartRequest {
  surface?: string;
  session_key?: string;
  device_id?: string;
  sender_id?: string;
}

export interface AssistantSessionStartResponse {
  ok: boolean;
  surface: string;
  session_key: string;
  duplex_session_id: string;
  ws_url: string;
  provider: string;
  transport: string;
  audio_chunk_ms: number;
  sample_rate: number;
  prefix_system_prompt: string;
  prepare_payload: Record<string, unknown>;
  user_profile: Record<string, unknown>;
  memory_summary: string;
  recent_history: Array<Record<string, unknown>>;
}

export interface AssistantSessionStopRequest {
  surface?: string;
  session_key?: string;
  duplex_session_id?: string;
  device_id?: string;
  sender_id?: string;
}

export interface AssistantSessionInterruptRequest {
  surface?: string;
  session_key?: string;
  duplex_session_id?: string;
  device_id?: string;
  sender_id?: string;
}

export interface AssistantSendRequest {
  text: string;
  surface?: string;
  session_key?: string;
  device_id?: string;
  sender_id?: string;
  metadata?: Record<string, unknown>;
  attachments?: Array<Record<string, unknown>>;
}

export interface AssistantToolResult {
  name: string;
  ok: boolean;
  detail: string;
  data: Record<string, unknown>;
}

export interface AssistantSendResponse {
  ok: boolean;
  surface: string;
  session_key: string;
  text: string;
  tool_results: AssistantToolResult[];
  timestamp_ms: number;
}

export interface AssistantSessionEvent {
  type: string;
  timestamp_ms: number;
  payload: Record<string, any>;
}

export const getDueAssistantTodos = async (limit = 10): Promise<AssistantTodoItem[]> => {
  const response = await apiGet(`/api/assistant/todos/due?limit=${Math.max(1, Math.min(limit, 20))}`, true);
  return Array.isArray(response?.items) ? response.items : [];
};

export const getAssistantRuntimeStatus = async (): Promise<AssistantRuntimeStatus> => {
  return apiGet("/api/assistant/runtime/status", true);
};

export const getAssistantDuplexConfig = async (): Promise<AssistantDuplexConfig> => {
  return apiGet("/api/assistant/duplex/config", true);
};

export const startAssistantSession = async (
  payload: AssistantSessionStartRequest = {}
): Promise<AssistantSessionStartResponse> => {
  return apiPost("/api/assistant/session/start", payload, true);
};

export const stopAssistantSession = async (payload: AssistantSessionStopRequest = {}) => {
  return apiPost("/api/assistant/session/stop", payload, true);
};

export const interruptAssistantSession = async (payload: AssistantSessionInterruptRequest = {}) => {
  return apiPost("/api/assistant/session/interrupt", payload, true);
};

export const sendAssistantMessage = async (
  payload: AssistantSendRequest
): Promise<AssistantSendResponse> => {
  return apiPost("/api/assistant/send", payload, true);
};

export const connectAssistantSessionEvents = (
  sessionId: string,
  onEvent: (event: AssistantSessionEvent) => void,
  onError?: (err: Event) => void
) => {
  const normalized = encodeURIComponent(String(sessionId || "").trim());
  const ws = new WebSocket(`${getWsBase()}/api/assistant/session/${normalized}/events`);

  ws.onmessage = (msg) => {
    try {
      const data = JSON.parse(msg.data) as AssistantSessionEvent;
      onEvent(data);
    } catch (err) {
      console.error("assistant session WS parse error:", err);
    }
  };

  ws.onerror = (err) => {
    console.error("assistant session WS error:", err);
    onError?.(err);
  };

  return ws;
};
