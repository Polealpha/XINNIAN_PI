import { ChatAttachment, EmotionEvent, EmotionType } from "../types";
import { apiPost, getAccessToken, getLocalApiBase } from "./apiClient";

export interface CareHistoryItem {
  sender: string;
  text: string;
  timestamp_ms: number;
}

interface CareStreamHandlers {
  onStart?: () => void;
  onDelta?: (delta: string, fullText: string) => void;
  onDone?: (fullText: string) => void;
}

interface CareApiResponse {
  text?: string;
  followup_question?: string;
  style?: string;
  source?: string;
  detail?: string;
  ai_ready?: boolean;
}

const CARE_FALLBACK_TEXT = "我在这里陪着你。如果你愿意，可以继续告诉我现在最卡的是哪一点。";
const CARE_ERROR_FALLBACK_TEXT = "我在，先慢一点。你可以先说一句最想解决的事，我们一步一步来。";

const buildCarePayload = (
  currentEmotion: EmotionType,
  context: string,
  history: CareHistoryItem[],
  currentTsMs?: number,
  memorySummary?: string,
  expressionLabel?: string,
  expressionConfidence?: number,
  attachments: ChatAttachment[] = []
) => ({
  current_emotion: currentEmotion,
  context,
  current_ts_ms: currentTsMs,
  history: history.slice(-6),
  memory_summary: memorySummary || "",
  expression_label: expressionLabel || "unknown",
  expression_confidence:
    typeof expressionConfidence === "number" && Number.isFinite(expressionConfidence)
      ? expressionConfidence
      : 0,
  attachments,
});

export const generateCareMessage = async (
  currentEmotion: EmotionType,
  context: string,
  history: CareHistoryItem[] = [],
  currentTsMs?: number,
  memorySummary?: string,
  expressionLabel?: string,
  expressionConfidence?: number,
  attachments: ChatAttachment[] = []
): Promise<string> => {
  try {
    const response = (await apiPost(
      "/api/llm/care",
      buildCarePayload(
        currentEmotion,
        context,
        history,
        currentTsMs,
        memorySummary,
        expressionLabel,
        expressionConfidence,
        attachments
      ),
      true
    )) as CareApiResponse;
    if (response.source && response.source !== "ai") {
      console.warn("Care response downgraded from AI:", response.detail || response.source);
    }
    return response.text || CARE_FALLBACK_TEXT;
  } catch (error) {
    console.error("Care API Error:", error);
    return CARE_ERROR_FALLBACK_TEXT;
  }
};

export const generateCareMessageStream = async (
  currentEmotion: EmotionType,
  context: string,
  history: CareHistoryItem[] = [],
  currentTsMs?: number,
  handlers: CareStreamHandlers = {},
  signal?: AbortSignal,
  memorySummary?: string,
  expressionLabel?: string,
  expressionConfidence?: number,
  attachments: ChatAttachment[] = []
): Promise<string> => {
  try {
    handlers.onStart?.();
    const token = getAccessToken();
    const response = await fetch(`${getLocalApiBase()}/api/llm/care/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(
        buildCarePayload(
          currentEmotion,
          context,
          history,
          currentTsMs,
          memorySummary,
          expressionLabel,
          expressionConfidence,
          attachments
        )
      ),
      signal,
    });
    if (!response.ok || !response.body) {
      throw new Error(`care_stream_failed:${response.status}`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let fullText = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      if (signal?.aborted) return "";
      buffer += decoder.decode(value, { stream: true });
      let boundary = buffer.indexOf("\n\n");
      while (boundary >= 0) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const lines = block.split(/\r?\n/);
        let event = "";
        const dataLines: string[] = [];
        for (const line of lines) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
        }
        if (event && dataLines.length > 0) {
          const payload = JSON.parse(dataLines.join("\n")) as CareApiResponse & { text?: string; message?: string };
          if (event === "delta" && payload.text) {
            fullText += payload.text;
            handlers.onDelta?.(payload.text, fullText);
          } else if (event === "done") {
            const finalText = payload.text || fullText || CARE_FALLBACK_TEXT;
            handlers.onDone?.(finalText);
            return finalText;
          } else if (event === "error") {
            throw new Error(payload.message || payload.detail || "care_stream_error");
          }
        }
        boundary = buffer.indexOf("\n\n");
      }
    }
    handlers.onDone?.(fullText);
    return fullText || CARE_FALLBACK_TEXT;
  } catch (error) {
    console.error("Care stream failed, falling back to non-stream care:", error);
    if (signal?.aborted) return "";
    return generateCareMessage(
      currentEmotion,
      context,
      history,
      currentTsMs,
      memorySummary,
      expressionLabel,
      expressionConfidence,
      attachments
    );
  }
};

export const generateDailySummary = async (events: EmotionEvent[]): Promise<string> => {
  try {
    const payload = {
      events: events.map((e) => ({
        timestamp: e.timestamp.toISOString(),
        type: e.type,
        description: e.description,
        scores: e.scores,
      })),
    };
    const response = await apiPost("/api/llm/daily_summary", payload, true);
    return response.summary || "今天辛苦了，记得给自己一点休息时间。";
  } catch (error) {
    console.error("LLM API Error:", error);
    return "今天的数据同步有波动，但我一直在。晚点也可以再一起复盘。";
  }
};
