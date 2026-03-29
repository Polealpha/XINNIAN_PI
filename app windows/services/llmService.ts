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
  assistantMode?: "product" | "agent";
  nativeControlEnabled?: boolean;
}

const readAssistantRuntimePrefs = (options: AssistantRequestOptions = {}) => {
  const assistantMode =
    options.assistantMode ||
    ((localStorage.getItem("assistant_mode") as "product" | "agent" | null) || "agent");
  const nativeControlEnabled =
    typeof options.nativeControlEnabled === "boolean"
      ? options.nativeControlEnabled
      : localStorage.getItem("assistant_native_control") !== "false";
  return {
    assistantMode: assistantMode === "product" ? "product" : "agent",
    nativeControlEnabled,
  };
};

const ASSISTANT_FALLBACK_TEXT = "OpenClaw 当前没有返回有效内容。";
const ASSISTANT_ERROR_FALLBACK_TEXT = "OpenClaw 当前未连接，暂时无法生成真实回答。";
const CARE_FALLBACK_TEXT = "OpenClaw 当前没有返回有效的主动关怀内容。";
const CARE_ERROR_FALLBACK_TEXT = "OpenClaw 当前未连接，暂时无法生成真实主动关怀回答。";

const buildAssistantUnavailableText = (error: unknown, mode: "chat" | "proactive_care") => {
  const detail = String((error as Error)?.message || "").trim();
  const core = detail || "本地 OpenClaw / 助手运行时未就绪";
  if (mode === "proactive_care") {
    return `OpenClaw 当前未连接，这不是 AI 的真实主动关怀回复。详情：${core}`;
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
) => {
  const prefs = readAssistantRuntimePrefs(options);
  return ({
  text: context,
  surface: "desktop",
  attachments,
  metadata: {
    entrypoint: options.mode === "proactive_care" ? "llm_care" : "desktop_chat",
    care_channel: options.mode === "proactive_care" ? "proactive_care" : "",
    assistant_mode: prefs.assistantMode,
    assistant_native_control: prefs.nativeControlEnabled,
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
};

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
    return String(response?.text || "").trim() || fallbackText;
  } catch (error) {
    console.error("Assistant request error:", error);
    const message = String((error as Error)?.message || "");
    if (
      message.includes("/api/assistant/send") ||
      message.includes("OpenClaw") ||
      message.includes("Failed to fetch") ||
      message.includes("NetworkError") ||
      message.includes("fetch")
    ) {
      return buildAssistantUnavailableText(error, mode);
    }
    return buildAssistantUnavailableText(error, mode) || errorFallbackText;
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
    return response.summary || "今天的数据摘要暂时还没生成出来。";
  } catch (error) {
    console.error("LLM API Error:", error);
    return "今日摘要暂时不可用，稍后可以再试一次。";
  }
};
