import { EmotionEvent, RiskScores } from "../types";
import { apiGet, apiPost } from "./apiClient";

export const getRealtimeScores = async (): Promise<RiskScores> => {
  return apiGet("/api/emotion/realtime", true);
};

export interface RealtimeRiskDetailResponse {
  V: number;
  A: number;
  T: number;
  S: number;
  timestamp_ms: number;
  mode?: string;
  detail?: {
    V_sub?: Record<string, number>;
    A_sub?: Record<string, number>;
    T_sub?: Record<string, any>;
  };
}

export const getRealtimeRiskDetail = async (): Promise<RealtimeRiskDetailResponse> => {
  return apiGet("/api/emotion/realtime/detail", true);
};

export const getEmotionHistory = async (): Promise<EmotionEvent[]> => {
  const data = await apiGet("/api/emotion/history?limit=50", true);
  const allowed = new Set(["HAPPY", "SAD", "ANGRY", "CALM", "TIRED", "ANXIOUS"]);
  return data
    .filter((item: any) => allowed.has(String(item.type || "").toUpperCase()))
    .map((item: any) => ({
      id: String(item.id),
      timestamp: new Date(item.timestamp_ms),
      type: item.type,
      scores: { V: item.V, A: item.A, T: item.T, S: item.S },
      description: item.description,
      intensity: item.intensity,
      source: item.source,
    }));
};

export const getEmotionHistoryRange = async (params: {
  startMs?: number;
  endMs?: number;
  limit?: number;
}): Promise<EmotionEvent[]> => {
  const query = new URLSearchParams();
  query.set("limit", String(params.limit ?? 300));
  if (typeof params.startMs === "number") {
    query.set("start_ms", String(Math.floor(params.startMs)));
  }
  if (typeof params.endMs === "number") {
    query.set("end_ms", String(Math.floor(params.endMs)));
  }
  const data = await apiGet(`/api/emotion/history?${query.toString()}`, true);
  const allowed = new Set(["HAPPY", "SAD", "ANGRY", "CALM", "TIRED", "ANXIOUS"]);
  return data
    .filter((item: any) => allowed.has(String(item.type || "").toUpperCase()))
    .map((item: any) => ({
      id: String(item.id),
      timestamp: new Date(item.timestamp_ms),
      type: item.type,
      scores: { V: item.V, A: item.A, T: item.T, S: item.S },
      description: item.description,
      intensity: item.intensity,
      source: item.source,
    }));
};

export const addEmotionEvent = async (event: EmotionEvent): Promise<void> => {
  await apiPost(
    "/api/emotion/history",
    {
      timestamp_ms: event.timestamp.getTime(),
      type: event.type,
      description: event.description,
      V: event.scores.V,
      A: event.scores.A,
      T: event.scores.T,
      S: event.scores.S,
      intensity: event.intensity ?? null,
      source: event.source ?? null,
    },
    true
  );
};
