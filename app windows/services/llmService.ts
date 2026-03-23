import { ChatAttachment, EmotionEvent, EmotionType } from "../types";
import { apiPost } from "./apiClient";

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

const CARE_FALLBACK_TEXT = "我在这里陪着你。如果你愿意，可以继续告诉我现在最卡的是哪一点。";
const CARE_ERROR_FALLBACK_TEXT = "我在，先慢一点。你可以先说一句最想解决的事，我们一步一步来。";

const buildAssistantPayload = (
  currentEmotion: EmotionType,
  context: string,
  history: CareHistoryItem[],
  currentTsMs?: number,
  memorySummary?: string,
  expressionLabel?: string,
  expressionConfidence?: number,
  attachments: ChatAttachment[] = []
) => ({
  text: context,
  surface: "desktop",
  attachments,
  metadata: {
    entrypoint: "llm_care",
    care_channel: "proactive_care",
    assistant_mode: "product",
    assistant_native_control: false,
    current_emotion: currentEmotion,
    current_ts_ms: currentTsMs,
    history: history.slice(-6),
    memory_summary: memorySummary || "",
    expression_label: expressionLabel || "unknown",
    expression_confidence:
      typeof expressionConfidence === "number" && Number.isFinite(expressionConfidence)
        ? expressionConfidence
        : 0,
  },
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
    const response = await apiPost(
      "/api/assistant/send",
      buildAssistantPayload(
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
    );
    return response.text || CARE_FALLBACK_TEXT;
  } catch (error) {
    console.error("Care assistant error:", error);
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
    const fullText = await generateCareMessage(
      currentEmotion,
      context,
      history,
      currentTsMs,
      memorySummary,
      expressionLabel,
      expressionConfidence,
      attachments
    );
    let streamedText = "";
    for (const char of fullText) {
      if (signal?.aborted) return "";
      streamedText += char;
      handlers.onDelta?.(char, streamedText);
      await new Promise((resolve) => window.setTimeout(resolve, 10));
    }
    handlers.onDone?.(streamedText);
    return streamedText;
  } catch (error) {
    console.error("Care stream emulation failed:", error);
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
