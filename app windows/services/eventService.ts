import { getWsBase } from "./apiClient";

export interface EngineEvent {
  type: string;
  timestamp_ms: number;
  payload: Record<string, any>;
}

export const connectEventStream = (
  onEvent: (event: EngineEvent) => void,
  onError?: (err: Event) => void
) => {
  const ws = new WebSocket(`${getWsBase()}/ws/events`);

  ws.onmessage = (msg) => {
    try {
      const data = JSON.parse(msg.data) as EngineEvent;
      onEvent(data);
    } catch (err) {
      console.error("WS parse error:", err);
    }
  };

  ws.onerror = (err) => {
    console.error("WS error:", err);
    if (onError) onError(err);
  };

  return ws;
};
