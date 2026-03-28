import { apiGet } from "./apiClient";

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

export const getDueAssistantTodos = async (limit = 10): Promise<AssistantTodoItem[]> => {
  const response = await apiGet(`/api/assistant/todos/due?limit=${Math.max(1, Math.min(limit, 20))}`, true);
  return Array.isArray(response?.items) ? response.items : [];
};

export const getAssistantRuntimeStatus = async (): Promise<AssistantRuntimeStatus> => {
  return apiGet("/api/assistant/runtime/status", true);
};
