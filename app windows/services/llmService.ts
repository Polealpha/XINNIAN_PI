import { ChatAttachment, EmotionEvent, EmotionType } from "../types";
import { apiPost } from "./apiClient";

export interface CareHistoryItem {
  sender: string;
  text: string;
  timestamp_ms: number;
}

interface AssistantStreamHandlers {
  onStart?: () => void;
  onDelta?: (delta: string, fullText: string) => void;
  onDone?: (fullText: string) => void;
}

interface AssistantRequestOptions {
  mode?: "chat" | "proactive_care";
  fallbackText?: string;
  errorFallbackText?: string;
}

const ASSISTANT_FALLBACK_TEXT = "我在。你可以继续说下去，我会接着这一句往下帮你分析。";
const ASSISTANT_ERROR_FALLBACK_TEXT = "刚刚这一句没有顺利发出去。你可以再说一次，我继续接。";
const CARE_FALLBACK_TEXT = "我在这里陪着你。如果你愿意，可以继续告诉我现在最卡的是哪一点。";
const CARE_ERROR_FALLBACK_TEXT = "我在，先慢一点。你可以先说一句最想解决的事，我们一步一步来。";

const buildAssistantUnavailableText = (error: unknown, mode: "chat" | "proactive_care") => {
  const detail = String((error as Error)?.message || "").trim();
  const core = detail || "本地 OpenClaw / 助手运行时未就绪";
  if (mode === "proactive_care") {
    return `OpenClaw 当前未连接，这不是 AI 的真实回答。请先恢复本地助手运行时。详情：${core}`;
  }
  return `OpenClaw 当前未连接，无法生成真实回答。详情：${core}`;
};

const buildAssistantPayload = (
  currentEmotion: EmotionType,
  context: string,
  history: CareHistoryItem[],
  currentTsMs?: number,
  memorySummary?: string,
  expressionLabel?: string,
  expressionConfidence?: number,
  attachments: ChatAttachment[] = [],
  options: AssistantRequestOptions = {}
) => ({
  text: context,
  surface: "desktop",
  attachments,
  metadata: {
    entrypoint: options.mode === "proactive_care" ? "llm_care" : "desktop_chat",
    care_channel: options.mode === "proactive_care" ? "proactive_care" : "",
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

export const generateAssistantMessage = async (
  currentEmotion: EmotionType,
  context: string,
  history: CareHistoryItem[] = [],
  currentTsMs?: number,
  memorySummary?: string,
  expressionLabel?: string,
  expressionConfidence?: number,
  attachments: ChatAttachment[] = [],
  options: AssistantRequestOptions = {}
): Promise<string> => {
  const mode = options.mode || "chat";
  const fallbackText = options.fallbackText || ASSISTANT_FALLBACK_TEXT;
  const errorFallbackText = options.errorFallbackText || ASSISTANT_ERROR_FALLBACK_TEXT;
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
        attachments,
        options
      ),
      true
    );
    return response.text || fallbackText;
  } catch (error) {
    console.error("Assistant request error:", error);
    const message = String((error as Error)?.message || "");
    if (message.includes("/api/assistant/send") || message.includes("OpenClaw")) {
      return buildAssistantUnavailableText(error, mode);
    }
    return errorFallbackText;
  }
};

export const generateAssistantMessageStream = async (
  currentEmotion: EmotionType,
  context: string,
  history: CareHistoryItem[] = [],
  currentTsMs?: number,
  handlers: AssistantStreamHandlers = {},
  signal?: AbortSignal,
  memorySummary?: string,
  expressionLabel?: string,
  expressionConfidence?: number,
  attachments: ChatAttachment[] = [],
  options: AssistantRequestOptions = {}
): Promise<string> => {
  try {
    handlers.onStart?.();
    const fullText = await generateAssistantMessage(
      currentEmotion,
      context,
      history,
      currentTsMs,
      memorySummary,
      expressionLabel,
      expressionConfidence,
      attachments,
      options
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
    console.error("Assistant stream emulation failed:", error);
    if (signal?.aborted) return "";
    return generateAssistantMessage(
      currentEmotion,
      context,
      history,
      currentTsMs,
      memorySummary,
      expressionLabel,
      expressionConfidence,
      attachments,
      options
    );
  }
};

export const generateCareMessage = async (
  currentEmotion: EmotionType,
  context: string,
  history: CareHistoryItem[] = [],
  currentTsMs?: number,
  memorySummary?: string,
  expressionLabel?: string,
  expressionConfidence?: number,
  attachments: ChatAttachment[] = []
): Promise<string> =>
  generateAssistantMessage(
    currentEmotion,
    context,
    history,
    currentTsMs,
    memorySummary,
    expressionLabel,
    expressionConfidence,
    attachments,
    {
      mode: "proactive_care",
      fallbackText: CARE_FALLBACK_TEXT,
      errorFallbackText: CARE_ERROR_FALLBACK_TEXT,
    }
  );

export const generateCareMessageStream = async (
  currentEmotion: EmotionType,
  context: string,
  history: CareHistoryItem[] = [],
  currentTsMs?: number,
  handlers: AssistantStreamHandlers = {},
  signal?: AbortSignal,
  memorySummary?: string,
  expressionLabel?: string,
  expressionConfidence?: number,
  attachments: ChatAttachment[] = []
): Promise<string> =>
  generateAssistantMessageStream(
    currentEmotion,
    context,
    history,
    currentTsMs,
    handlers,
    signal,
    memorySummary,
    expressionLabel,
    expressionConfidence,
    attachments,
    {
      mode: "proactive_care",
      fallbackText: CARE_FALLBACK_TEXT,
      errorFallbackText: CARE_ERROR_FALLBACK_TEXT,
    }
  );

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
