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
}

export interface AssistantDuplexConfig {
  ok: boolean;
  provider: string;
  ws_base: string;
  audio_chunk_ms: number;
  sample_rate: number;
  transport: string;
  preferred_voice: string;
}

export interface AssistantSessionStartPayload {
  surface?: string;
  session_key?: string;
  device_id?: string;
  sender_id?: string;
  metadata?: Record<string, unknown>;
}

export interface AssistantChatMessage {
  id?: string;
  sender: string;
  text: string;
  content_type?: string;
  timestamp_ms?: number | null;
  surface?: string;
  session_key?: string;
  attachments?: Array<Record<string, unknown>>;
}

export interface AssistantSessionStartResponse {
  ok: boolean;
  surface: string;
  session_key: string;
  duplex_session_id: string;
  ws_url: string;
  provider: string;
  prepare_payload: Record<string, unknown>;
  last_message_ts_ms?: number | null;
  message_count: number;
  history: AssistantChatMessage[];
  memory_summary: string;
}

export interface AssistantSessionControlPayload {
  surface?: string;
  session_key?: string;
  device_id?: string;
  sender_id?: string;
}

export interface AssistantSessionInterruptPayload extends AssistantSessionControlPayload {
  reason?: string;
}

export interface AssistantSessionControlResponse {
  ok: boolean;
  surface: string;
  session_key: string;
  status: string;
  duplex_session_id?: string | null;
  timestamp_ms: number;
}

export interface AssistantSessionStatus {
  ok: boolean;
  surface: string;
  session_key: string;
  last_message_ts_ms?: number | null;
  message_count: number;
  history: AssistantChatMessage[];
}

export interface AssistantSendPayload {
  text: string;
  surface?: string;
  session_key?: string;
  device_id?: string;
  sender_id?: string;
  attachments?: Array<Record<string, unknown>>;
  metadata?: Record<string, unknown>;
}

export interface AssistantSendResponse {
  ok: boolean;
  surface: string;
  session_key: string;
  text: string;
  tool_results: Array<Record<string, unknown>>;
  timestamp_ms: number;
}

export interface AssistantSessionEvent {
  type: string;
  timestamp_ms: number;
  payload: Record<string, unknown>;
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
  payload: AssistantSessionStartPayload = {},
): Promise<AssistantSessionStartResponse> => {
  return apiPost("/api/assistant/session/start", payload, true);
};

export const stopAssistantSession = async (
  payload: AssistantSessionControlPayload = {},
): Promise<AssistantSessionControlResponse> => {
  return apiPost("/api/assistant/session/stop", payload, true);
};

export const interruptAssistantSession = async (
  payload: AssistantSessionInterruptPayload = {},
): Promise<AssistantSessionControlResponse> => {
  return apiPost("/api/assistant/session/interrupt", payload, true);
};

export const getAssistantSessionStatus = async (
  sessionKey: string,
  surface = "desktop",
  limit = 30,
): Promise<AssistantSessionStatus> => {
  const query = new URLSearchParams({
    surface,
    session_key: sessionKey,
    limit: String(Math.max(1, Math.min(limit, 100))),
  });
  return apiGet(`/api/assistant/session/status?${query.toString()}`, true);
};

export const sendAssistantMessage = async (
  payload: AssistantSendPayload,
): Promise<AssistantSendResponse> => {
  return apiPost("/api/assistant/send", payload, true);
};

export const connectAssistantSessionEvents = (
  sessionKey: string,
  onEvent: (event: AssistantSessionEvent) => void,
): WebSocket => {
  const wsBase = getWsBase();
  const encodedSession = encodeURIComponent(sessionKey);
  const ws = new WebSocket(`${wsBase}/api/assistant/session/${encodedSession}/events`);
  ws.onmessage = (event) => {
    try {
      const parsed = JSON.parse(event.data) as AssistantSessionEvent;
      onEvent(parsed);
    } catch {
      // ignore malformed events from local bridge
    }
  };
  return ws;
};
