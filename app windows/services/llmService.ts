import { ChatAttachment, EmotionEvent, EmotionType } from "../types";
import { apiPost, getAccessToken, getApiBase } from "./apiClient";

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
    const payload = {
      current_emotion: currentEmotion,
      context,
      current_ts_ms: currentTsMs,
      history: history.slice(-4),
      memory_summary: memorySummary || "",
      expression_label: expressionLabel || "unknown",
      expression_confidence:
        typeof expressionConfidence === "number" && Number.isFinite(expressionConfidence)
          ? expressionConfidence
          : 0,
      attachments,
    };
    const response = await apiPost("/api/llm/care", payload, true);
    return response.text || "我在这里陪着你，如果愿意可以继续和我说。";
  } catch (error) {
    console.error("LLM API Error:", error);
    return "我在，先慢一点呼吸一下，我们再继续。";
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
  const payload = {
    current_emotion: currentEmotion,
    context,
    current_ts_ms: currentTsMs,
    history: history.slice(-4),
    memory_summary: memorySummary || "",
    expression_label: expressionLabel || "unknown",
    expression_confidence:
      typeof expressionConfidence === "number" && Number.isFinite(expressionConfidence)
        ? expressionConfidence
        : 0,
    attachments,
  };

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  };
  const token = getAccessToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(`${getApiBase()}/api/llm/care/stream`, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      cache: "no-store",
      signal,
    });
  } catch (error) {
    console.error("LLM stream API Error:", error);
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

  if (!response.ok || !response.body) {
    console.warn("LLM stream unavailable, fallback to sync");
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

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let fullText = "";

  const processBlock = (block: string) => {
    if (!block.trim()) return;
    const lines = block.split("\n");
    let eventType = "message";
    const dataLines: string[] = [];
    for (const line of lines) {
      if (line.startsWith("event:")) {
        eventType = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
      }
    }
    if (dataLines.length === 0) return;

    const dataRaw = dataLines.join("\n");
    let data: any = {};
    try {
      data = JSON.parse(dataRaw);
    } catch {
      data = { text: dataRaw };
    }

    if (eventType === "start") {
      handlers.onStart?.();
      return;
    }
    if (eventType === "delta") {
      const delta = typeof data.text === "string" ? data.text : "";
      if (!delta) return;
      fullText += delta;
      handlers.onDelta?.(delta, fullText);
      return;
    }
    if (eventType === "done") {
      if (typeof data.text === "string" && data.text.trim()) {
        fullText = data.text;
      }
      handlers.onDone?.(fullText);
      return;
    }
    if (eventType === "error") {
      throw new Error(String(data.message || "stream error"));
    }
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
      let sepIndex = buffer.indexOf("\n\n");
      while (sepIndex >= 0) {
        const block = buffer.slice(0, sepIndex);
        buffer = buffer.slice(sepIndex + 2);
        processBlock(block);
        sepIndex = buffer.indexOf("\n\n");
      }
    }
    if (buffer.trim()) {
      processBlock(buffer);
    }
  } catch (error) {
    console.error("LLM stream parse error:", error);
    if (!fullText.trim()) {
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
  } finally {
    reader.releaseLock();
  }

  if (!fullText.trim()) {
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
  return fullText;
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
