import { apiGet, apiPost } from "./apiClient";

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

export interface AssistantSendToolResult {
  name: string;
  ok: boolean;
  detail: string;
  data: Record<string, unknown>;
}

export interface AssistantSendArgs {
  text: string;
  surface?: string;
  session_key?: string;
  device_id?: string;
  sender_id?: string;
  attachments?: Record<string, unknown>[];
  metadata?: Record<string, unknown>;
}

export interface AssistantSendResult {
  ok: boolean;
  surface: string;
  session_key: string;
  text: string;
  tool_results: AssistantSendToolResult[];
  timestamp_ms: number;
}

export interface RealtimeTurnSyncArgs {
  surface?: string;
  session_key?: string;
  device_id?: string;
  sender_id?: string;
  user_text?: string;
  assistant_text?: string;
  tool_events?: AssistantSendToolResult[];
  source?: string;
}

export interface RealtimeTurnSyncResult {
  ok: boolean;
  surface: string;
  session_key: string;
  inserted_messages: number;
  mirrored_to_wechat: boolean;
  timestamp_ms: number;
}

export interface AssistantWechatStatus {
  ok: boolean;
  status: string;
  detail: string;
  qr_available: boolean;
  qr_path?: string | null;
  linked: boolean;
  account_id?: string | null;
  user_id?: string | null;
}

export const getDueAssistantTodos = async (limit = 10): Promise<AssistantTodoItem[]> => {
  const response = await apiGet(`/api/assistant/todos/due?limit=${Math.max(1, Math.min(limit, 20))}`, true);
  return Array.isArray(response?.items) ? response.items : [];
};

export const getAssistantRuntimeStatus = async (): Promise<AssistantRuntimeStatus> => {
  return apiGet("/api/assistant/runtime/status", true);
};

export const sendAssistantMessage = async (payload: AssistantSendArgs): Promise<AssistantSendResult> => {
  return apiPost("/api/assistant/send", payload, true);
};

export const syncRealtimeTurn = async (payload: RealtimeTurnSyncArgs): Promise<RealtimeTurnSyncResult> => {
  return apiPost("/api/assistant/realtime-turn-sync", payload, true);
};

export const getAssistantWechatStatus = async (): Promise<AssistantWechatStatus> => {
  return apiGet("/api/assistant/wechat/status", true);
};
