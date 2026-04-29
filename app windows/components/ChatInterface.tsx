import React, { useEffect, useMemo, useRef, useState } from "react";
import { ChatAttachment, ChatMessage, DeviceStatus, EmotionType } from "../types";
import { Send, Sparkles, User, Bot, Activity, Paperclip, X, Mic, Square, LoaderCircle } from "lucide-react";
import { uploadChatAttachment } from "../services/chatService";
import { AssistantRuntimeStatus, AssistantSendResult, sendAssistantMessage, syncRealtimeTurn } from "../services/assistantService";
import { getLocalApiBase } from "../services/apiClient";
import { probeQwenReady } from "../services/qwenOmniService";
import { QwenRealtimeState, QwenRealtimeVideoService } from "../services/qwenRealtimeVideoService";


interface ChatInterfaceProps {
  currentEmotion: EmotionType;
  initialMessages?: ChatMessage[];
  onSendMessage?: (msg: ChatMessage) => void;
  isGuest?: boolean;
  variant?: "default" | "compact";
  voiceState?: "idle" | "detecting" | "listening" | "thinking" | "speaking";
  expressionLabel?: string;
  expressionConfidence?: number;
  assistantRuntime?: AssistantRuntimeStatus | null;
  assistantRuntimeError?: string;
  audioEnabled?: boolean;
  videoEnabled?: boolean;
  deviceStatus?: DeviceStatus | null;
}

const DEFAULT_WELCOME: ChatMessage = {
  id: "welcome",
  sender: "bot",
  text: "你好！我是你的关怀伙伴。工位传感器已同步，我随时都在。你现在感觉怎么样？",
  timestamp: new Date(),
  contentType: "text",
  attachments: [],
};

const hasRenderableText = (text: unknown): boolean => typeof text === "string" && text.trim().length > 0;
const ROBOT_PROXY_BASE = `${getLocalApiBase().replace(/\/+$/, "")}/api/device`;
const DEFAULT_DEVICE_RUNTIME_PORT = 8090;
const DEFAULT_ASSISTANT_SESSION_KEY = "agent:main:main";
const REALTIME_PLACEHOLDER_USER_TEXT = "【实时语音 + 实时画面】";
const TOOL_COMMAND_PATTERNS = [
  /打开.*网易云/,
  /网易云/,
  /打开.*b站/,
  /打开.*哔哩哔哩/,
  /播放.*音乐/,
  /放点歌/,
  /听歌/,
  /下一首/,
  /暂停/,
  /继续播放/,
  /搜一下/,
  /搜索/,
];

const looksLikeToolCommand = (raw: string): boolean => {
  const text = String(raw || "").trim();
  if (!text) return false;
  return TOOL_COMMAND_PATTERNS.some((pattern) => pattern.test(text));
};

const buildRealtimeToolFollowupPrompt = (spokenText: string): string => {
  const safe = String(spokenText || "").trim();
  if (!safe) return "请用中文简短说明刚刚的工具执行结果。";
  return [
    "请用中文自然口语化地把刚刚的工具执行结果说给用户听。",
    "不要重复系统术语，不要提及 JSON 或结构化字段。",
    `工具结果：${safe}`,
  ].join("\n");
};

const normalizeRuntimeHost = (value?: string | null) => {
  const text = String(value || "").trim();
  if (!text) return "";
  const normalized = text.replace(/^https?:\/\//i, "").replace(/\/+$/, "");
  if (!normalized) return "";
  return normalized.includes(":") ? normalized : `${normalized}:${DEFAULT_DEVICE_RUNTIME_PORT}`;
};

const hasRenderableContent = (msg: ChatMessage): boolean => {
  if (hasRenderableText(msg.text)) return true;
  return Array.isArray(msg.attachments) && msg.attachments.length > 0;
};

const mergeChatMessages = (local: ChatMessage[], incoming: ChatMessage[]): ChatMessage[] => {
  const merged = [...local];
  for (const msg of incoming) {
    const existingIndex = merged.findIndex((item) => item.id === msg.id);
    if (existingIndex >= 0) {
      const prev = merged[existingIndex];
      const prevText = String(prev.text || "");
      const nextText = String(msg.text || "");
      merged[existingIndex] = nextText.length >= prevText.length ? msg : prev;
      continue;
    }

    const msgText = String(msg.text || "").trim();
    const msgAttachKey = JSON.stringify(msg.attachments || []);
    const msgTs = msg.timestamp.getTime();
    const dupIndex = merged.findIndex((item) => {
      const itemText = String(item.text || "").trim();
      const itemAttachKey = JSON.stringify(item.attachments || []);
      return (
        item.sender === msg.sender &&
        itemText === msgText &&
        itemAttachKey === msgAttachKey &&
        Math.abs(item.timestamp.getTime() - msgTs) <= 4000
      );
    });
    if (dupIndex >= 0) {
      const prev = merged[dupIndex];
      const prevText = String(prev.text || "");
      const nextText = String(msg.text || "");
      merged[dupIndex] = nextText.length >= prevText.length ? msg : prev;
      continue;
    }

    merged.push(msg);
  }
  return merged.sort((a, b) => a.timestamp.getTime() - b.timestamp.getTime());
};

const messageToHistoryText = (m: ChatMessage): string => {
  const text = String(m.text || "").trim();
  const attachments = Array.isArray(m.attachments) ? m.attachments : [];
  if (text) return text;
  if (!attachments.length) return "";
  const imageCount = attachments.filter((a) => a.kind === "image").length;
  const videoCount = attachments.filter((a) => a.kind === "video").length;
  if (imageCount && videoCount) return `发送了${imageCount}张图片和${videoCount}段视频`;
  if (imageCount) return `发送了${imageCount}张图片`;
  if (videoCount) return `发送了${videoCount}段视频`;
  return "发送了附件";
};

const buildMemorySummary = (items: ChatMessage[], keepTail = 6, maxChars = 420): string => {
  if (!items.length) return "";
  const older = items.slice(0, Math.max(0, items.length - keepTail));
  if (!older.length) return "";
  const compact = older
    .slice(-10)
    .map((m) => {
      const role = m.sender === "user" ? "U" : "A";
      const text = messageToHistoryText(m).replace(/\s+/g, " ").trim().slice(0, 48);
      return text ? `${role}:${text}` : "";
    })
    .filter(Boolean)
    .join(" | ");
  if (compact.length <= maxChars) return compact;
  return compact.slice(compact.length - maxChars);
};

const normalizeRuntimeError = (value: unknown): string => {
  const message = String(value || "").trim();
  if (!message) return "";
  const lowered = message.toLowerCase();
  if (
    lowered.includes("signal is aborted without reason") ||
    lowered.includes("aborterror") ||
    lowered.includes("aborted")
  ) {
    return "";
  }
  return message;
};

const compressImageToDataUrl = async (file: File, maxWidth = 1024, quality = 0.78): Promise<string> => {
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("read_file_failed"));
    reader.readAsDataURL(file);
  });
  if (!dataUrl.startsWith("data:image/")) return "";

  const img = await new Promise<HTMLImageElement>((resolve, reject) => {
    const node = new Image();
    node.onload = () => resolve(node);
    node.onerror = () => reject(new Error("decode_image_failed"));
    node.src = dataUrl;
  });

  const scale = Math.min(1, maxWidth / Math.max(1, img.width));
  const width = Math.max(1, Math.round(img.width * scale));
  const height = Math.max(1, Math.round(img.height * scale));
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return dataUrl;
  ctx.drawImage(img, 0, 0, width, height);
  return canvas.toDataURL("image/jpeg", quality);
};

export const ChatInterface: React.FC<ChatInterfaceProps> = ({
  currentEmotion,
  initialMessages = [],
  onSendMessage,
  isGuest = false,
  variant = "default",
  voiceState = "idle",
  expressionLabel = "unknown",
  expressionConfidence = 0,
  assistantRuntime = null,
  assistantRuntimeError = "",
  audioEnabled = true,
  videoEnabled = true,
  deviceStatus = null,
}) => {
  const compact = variant === "compact";
  const initialRenderable = initialMessages.filter((msg) => hasRenderableContent(msg));
  const [messages, setMessages] = useState<ChatMessage[]>(
    initialRenderable.length > 0 ? initialRenderable : [DEFAULT_WELCOME]
  );
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [pendingAttachments, setPendingAttachments] = useState<ChatAttachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const [attachmentError, setAttachmentError] = useState("");
  const [dragActive, setDragActive] = useState(false);
  const messageListRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const streamAbortRef = useRef<AbortController | null>(null);
  const streamFlushTimerRef = useRef<number | null>(null);
  const streamPendingTextRef = useRef("");
  const historyHydratedRef = useRef(false);
  const duplexServiceRef = useRef<QwenRealtimeVideoService | null>(null);
  const duplexAssistantDraftIdRef = useRef<string | null>(null);
  const duplexUserDraftIdRef = useRef<string | null>(null);
  const realtimeTranscriptRef = useRef("");
  const realtimeToolTurnRef = useRef<AssistantSendResult | null>(null);
  const realtimeSkipSyncRef = useRef(false);
  const duplexVideoRef = useRef<HTMLVideoElement | null>(null);
  const [voiceRecording, setVoiceRecording] = useState(false);
  const [voiceBusy, setVoiceBusy] = useState(false);
  const [voiceError, setVoiceError] = useState("");
  const [duplexState, setDuplexState] = useState<QwenRealtimeState>("idle");
  const [qwenReady, setQwenReady] = useState(false);
  const [qwenReadyDetail, setQwenReadyDetail] = useState("?????? Qwen3-Omni");

  const stopBrowserSpeech = () => {
    if (!("speechSynthesis" in window)) return;
    try {
      window.speechSynthesis.cancel();
    } catch {
      // ignore
    }
  };

  const pickPreferredZhFemaleVoice = () => {
    if (!("speechSynthesis" in window)) return null;
    const voices = window.speechSynthesis.getVoices();
    if (!voices.length) return null;
    const femaleHints = /(huihui|yaoyao|xiaoxiao|xiaoyi|xiaobei|xiaoni|female|zira)/i;
    const maleHints = /(kangkang|yunjian|yunxi|yunyang|yunxia|male|david|mark)/i;
    const zhVoices = voices.filter((voice) => /^zh/i.test(String(voice.lang || "")) || /zh[-_]?cn/i.test(String(voice.name || "")) || /zh[-_]?cn/i.test(String(voice.voiceURI || "")));
    return (
      zhVoices.find((voice) => femaleHints.test(String(voice.name || "")) || femaleHints.test(String(voice.voiceURI || ""))) ||
      zhVoices.find((voice) => !maleHints.test(String(voice.name || "")) && !maleHints.test(String(voice.voiceURI || ""))) ||
      zhVoices[0] ||
      voices[0] ||
      null
    );
  };

  const speakBrowserSpeech = (text: string) => {
    void text;
    // Disable browser TTS for text chat to avoid confusing it with duplex audio output.
  };

  useEffect(() => {
    const next = initialMessages.filter((msg) => hasRenderableContent(msg));
    if (next.length === 0) return;
    setMessages((prev) => {
      if (!historyHydratedRef.current) {
        historyHydratedRef.current = true;
        const base = prev.length === 1 && prev[0].id === DEFAULT_WELCOME.id ? [] : prev;
        return mergeChatMessages(base, next);
      }
      return mergeChatMessages(prev, next);
    });
  }, [initialMessages]);

  const scrollToBottom = (behavior: ScrollBehavior = "smooth") => {
    const container = messageListRef.current;
    if (container) {
      container.scrollTo({ top: container.scrollHeight, behavior });
      return;
    }
    messagesEndRef.current?.scrollIntoView({ behavior });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isTyping]);

  useEffect(() => {
    const rafId = window.requestAnimationFrame(() => scrollToBottom("auto"));
    const timer = window.setTimeout(() => scrollToBottom("auto"), 120);
    return () => {
      window.cancelAnimationFrame(rafId);
      window.clearTimeout(timer);
    };
  }, [assistantRuntime?.gateway_ready, assistantRuntime?.provider_network_ok]);

  useEffect(() => {
    return () => {
      streamAbortRef.current?.abort();
      if (streamFlushTimerRef.current != null) {
        window.clearTimeout(streamFlushTimerRef.current);
      }
      streamPendingTextRef.current = "";
      void duplexServiceRef.current?.stop();
      stopBrowserSpeech();
    };
  }, []);

  useEffect(() => {
    let disposed = false;
    let timer: number | null = null;
    const poll = async () => {
      const status = await probeQwenReady();
      if (disposed) return;
      setQwenReady(status.ok);
      setQwenReadyDetail(status.detail);
      timer = window.setTimeout(poll, status.ok ? 12000 : 4000);
    };
    void poll();
    return () => {
      disposed = true;
      if (timer != null) {
        window.clearTimeout(timer);
      }
    };
  }, []);

  const assistantReady = Boolean(qwenReady);
  const assistantBooting = Boolean(!isGuest && !qwenReady);
  const assistantDetail = normalizeRuntimeError(
    qwenReady
      ? ""
      : qwenReadyDetail || assistantRuntimeError || assistantRuntime?.provider_network_detail || assistantRuntime?.gateway_error || ""
  );
  const chatInputDisabled = Boolean(!isGuest && !assistantReady);
  const chatInputPlaceholder = assistantBooting
    ? "?? Qwen3-Omni ??????"
    : !isGuest && !assistantReady
    ? "Qwen3-Omni ????????????"
    : "????????";

  const robotSnapshotUrl = useMemo(() => {
    const statusRecord = deviceStatus?.status as Record<string, unknown> | undefined;
    const host =
      normalizeRuntimeHost(deviceStatus?.device_ip) ||
      normalizeRuntimeHost(statusRecord?.ip as string | undefined) ||
      normalizeRuntimeHost(window.localStorage.getItem("robot_runtime_host"));
    if (!host) return "";
    const params = new URLSearchParams({ device_ip: host });
    return `${ROBOT_PROXY_BASE}/snapshot?${params.toString()}`;
  }, [deviceStatus]);

  const pickAttachments = () => {
    if (uploading || chatInputDisabled) return;
    fileInputRef.current?.click();
  };

  const addAttachmentsFromFiles = async (files: File[]) => {
    if (!files.length) return;
    setAttachmentError("");
    setUploading(true);
    try {
      const added: ChatAttachment[] = [];
      for (const file of files) {
        if (!file.type.startsWith("image/") && !file.type.startsWith("video/")) {
          continue;
        }
        const uploaded = await uploadChatAttachment(file);
        if (uploaded.kind === "image") {
          try {
            uploaded.image_data_url = await compressImageToDataUrl(file);
          } catch {
            uploaded.image_data_url = "";
          }
        }
        added.push(uploaded);
      }
      if (added.length) {
        setPendingAttachments((prev) => [...prev, ...added].slice(0, 6));
      }
    } catch (err) {
      console.error("attachment upload failed", err);
      setAttachmentError("附件上传失败，请重试");
    } finally {
      setUploading(false);
    }
  };

  const onAttachmentPicked = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []) as File[];
    event.target.value = "";
    await addAttachmentsFromFiles(files);
  };

  const removePendingAttachment = (idx: number) => {
    setPendingAttachments((prev) => prev.filter((_, i) => i !== idx));
  };

  const onRootDragOver = (event: React.DragEvent<HTMLDivElement>) => {
    if (uploading) return;
    if (!event.dataTransfer?.files?.length) return;
    event.preventDefault();
    setDragActive(true);
  };

  const onRootDragLeave = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    if (event.currentTarget.contains(event.relatedTarget as Node)) return;
    setDragActive(false);
  };

  const onRootDrop = async (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragActive(false);
    const files = Array.from(event.dataTransfer?.files || []) as File[];
    await addAttachmentsFromFiles(files);
  };

  const onInputPaste = async (event: React.ClipboardEvent<HTMLInputElement>) => {
    const files = Array.from(event.clipboardData?.files || []) as File[];
    if (!files.length) return;
    event.preventDefault();
    await addAttachmentsFromFiles(files);
  };

  const handleSend = async (overrideText?: string) => {
    const trimmed = String(overrideText ?? input).trim();
    const outgoingAttachments = pendingAttachments.slice(0, 6);
    if (!trimmed && outgoingAttachments.length === 0) return;

    const attachmentsForStorage = outgoingAttachments.map((a) => ({
      kind: a.kind,
      url: a.url,
      mime: a.mime,
      name: a.name,
      size: a.size,
    }));

    const hasText = trimmed.length > 0;
    const contentType: ChatMessage["contentType"] = hasText
      ? attachmentsForStorage.length
        ? "mixed"
        : "text"
      : attachmentsForStorage.length
      ? attachmentsForStorage.every((a) => a.kind === "image")
        ? "image"
        : attachmentsForStorage.every((a) => a.kind === "video")
        ? "video"
        : "mixed"
      : "text";

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      sender: "user",
      text: trimmed,
      contentType,
      attachments: attachmentsForStorage,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMsg]);
    if (onSendMessage) onSendMessage(userMsg);
    if (!overrideText) {
      setInput("");
    }
    setPendingAttachments([]);
    setAttachmentError("");
    setVoiceError("");
    setIsTyping(true);
    streamAbortRef.current?.abort();
    const abortCtrl = new AbortController();
    streamAbortRef.current = abortCtrl;

    if (isGuest) {
      const botMsg: ChatMessage = {
        id: `bot-${Date.now()}`,
        sender: "bot",
        text: "访客模式已开启，你可以先体验界面。登录后即可连接真实关怀引擎。",
        timestamp: new Date(),
        contentType: "text",
        attachments: [],
      };
      setMessages((prev) => [...prev, botMsg]);
      if (onSendMessage) onSendMessage(botMsg);
      setIsTyping(false);
      return;
    }

    if (!assistantReady) {
      const botMsg: ChatMessage = {
        id: `bot-${Date.now()}`,
        sender: "bot",
        text: assistantBooting
          ? "?? Qwen3-Omni ??????????????"
          : `Qwen3-Omni ?????????????? AI ???${assistantDetail ? ` ???${assistantDetail}` : " ????????????"}`,
        timestamp: new Date(),
        contentType: "text",
        attachments: [],
      };
      setMessages((prev) => [...prev, botMsg]);
      if (onSendMessage) onSendMessage(botMsg);
      setIsTyping(false);
      return;
    }

    const botMsgId = `bot-${Date.now()}`;
    const botTimestamp = new Date();
    const upsertBotMessage = (text: string) => {
      if (!hasRenderableText(text)) return;
      setMessages((prev) => {
        const idx = prev.findIndex((msg) => msg.id === botMsgId);
        if (idx >= 0) {
          const cloned = [...prev];
          cloned[idx] = { ...cloned[idx], text, contentType: "text", attachments: [] };
          return cloned;
        }
        return [
          ...prev,
          {
            id: botMsgId,
            sender: "bot",
            text,
            timestamp: botTimestamp,
            contentType: "text",
            attachments: [],
          },
        ];
      });
    };
    try {
      const requestMessages = [...messages, userMsg];
      const memorySummary = buildMemorySummary(requestMessages, 6, 420);
      const response = await sendAssistantMessage({
        text: trimmed || messageToHistoryText(userMsg),
        surface: "desktop",
        session_key: DEFAULT_ASSISTANT_SESSION_KEY,
        attachments: outgoingAttachments.map((a) => ({ ...a, image_data_url: a.image_data_url })),
        metadata: {
          current_emotion: currentEmotion,
          expression_label: expressionLabel,
          expression_confidence: expressionConfidence,
          memory_summary: memorySummary,
          source: "chat_interface_text",
        },
      });
      const responseText = String(response?.text || "").trim();
      upsertBotMessage(responseText);
      speakBrowserSpeech(responseText);

      if (hasRenderableText(responseText)) {
        const botMsg: ChatMessage = {
          id: botMsgId,
          sender: "bot",
          text: responseText,
          timestamp: botTimestamp,
          contentType: "text",
          attachments: [],
        };
        if (onSendMessage) onSendMessage(botMsg);
      }
    } finally {
      if (streamFlushTimerRef.current != null) {
        window.clearTimeout(streamFlushTimerRef.current);
        streamFlushTimerRef.current = null;
      }
      streamPendingTextRef.current = "";
      if (streamAbortRef.current === abortCtrl) {
        streamAbortRef.current = null;
      }
      setIsTyping(false);
    }
  };

  const upsertDuplexMessage = (id: string, sender: "user" | "bot", text: string) => {
    const safe = String(text || "").trim();
    if (!safe) return;
    setMessages((prev) => {
      const idx = prev.findIndex((item) => item.id === id);
      if (idx >= 0) {
        const cloned = [...prev];
        cloned[idx] = { ...cloned[idx], text: safe, timestamp: new Date() };
        return cloned;
      }
      return [
        ...prev,
        {
          id,
          sender,
          text: safe,
          timestamp: new Date(),
          contentType: "text",
          attachments: [],
        },
      ];
    });
  };

  const commitDuplexMessage = (idRef: React.MutableRefObject<string | null>, sender: "user" | "bot", text: string) => {
    const safe = String(text || "").trim();
    if (!safe) return;
    const id = idRef.current || `${sender}-${Date.now()}`;
    idRef.current = id;
    upsertDuplexMessage(id, sender, safe);
    onSendMessage?.({
      id,
      sender,
      text: safe,
      timestamp: new Date(),
      contentType: "text",
      attachments: [],
    });
    idRef.current = null;
  };

  const resetRealtimeTurnState = () => {
    realtimeTranscriptRef.current = "";
    realtimeToolTurnRef.current = null;
    realtimeSkipSyncRef.current = false;
    duplexUserDraftIdRef.current = null;
  };

  const syncRealtimeConversation = async (assistantText: string) => {
    if (realtimeSkipSyncRef.current) {
      resetRealtimeTurnState();
      return;
    }
    const cleanAssistantText = String(assistantText || "").trim();
    const cleanUserText = String(realtimeTranscriptRef.current || "").trim();
    if (!cleanAssistantText && !cleanUserText) {
      resetRealtimeTurnState();
      return;
    }
    try {
      await syncRealtimeTurn({
        surface: "desktop",
        session_key: DEFAULT_ASSISTANT_SESSION_KEY,
        user_text: cleanUserText || REALTIME_PLACEHOLDER_USER_TEXT,
        assistant_text: cleanAssistantText,
        tool_events: realtimeToolTurnRef.current?.tool_results || [],
        source: realtimeToolTurnRef.current ? "desktop_realtime_tool_followup" : "desktop_realtime",
      });
    } catch (error) {
      console.error("realtime turn sync failed", error);
    } finally {
      resetRealtimeTurnState();
    }
  };

  const handleVoiceToggle = async () => {
    setVoiceError("");
    if (voiceRecording && duplexServiceRef.current) {
      setVoiceBusy(true);
      try {
        stopBrowserSpeech();
        await duplexServiceRef.current.stop();
        resetRealtimeTurnState();
        duplexServiceRef.current = null;
        setVoiceRecording(false);
        setDuplexState("idle");
      } catch (err) {
        setVoiceError(err instanceof Error ? err.message : String(err));
        resetRealtimeTurnState();
        setVoiceRecording(false);
        duplexServiceRef.current = null;
        setDuplexState("idle");
      } finally {
        setVoiceBusy(false);
      }
      return;
    }

    setVoiceBusy(true);
    try {
      if (!duplexVideoRef.current) {
        throw new Error("missing_duplex_video_element");
      }
      resetRealtimeTurnState();
      const service = new QwenRealtimeVideoService({
        onStateChange: (state, detail) => {
          setDuplexState(state);
          if (state === "error" && detail) {
            setVoiceError(detail);
            setVoiceRecording(false);
            duplexServiceRef.current = null;
          }
        },
        onTurnCommitted: (kind) => {
          if (kind === "voice") {
            const id = `duplex-user-${Date.now()}`;
            duplexUserDraftIdRef.current = id;
            upsertDuplexMessage(id, "user", REALTIME_PLACEHOLDER_USER_TEXT);
            onSendMessage?.({
              id,
              sender: "user",
              text: REALTIME_PLACEHOLDER_USER_TEXT,
              timestamp: new Date(),
              contentType: "text",
              attachments: [],
            });
          }
        },
        onUserTranscriptDelta: (text) => {
          const safe = String(text || "").trim();
          realtimeTranscriptRef.current = safe;
          if (!duplexUserDraftIdRef.current) {
            duplexUserDraftIdRef.current = `duplex-user-${Date.now()}`;
          }
          if (safe) {
            upsertDuplexMessage(duplexUserDraftIdRef.current, "user", safe);
          }
        },
        onUserTranscriptFinal: (text) => {
          const safe = String(text || "").trim();
          realtimeTranscriptRef.current = safe;
          if (!safe) return;
          commitDuplexMessage(duplexUserDraftIdRef, "user", safe);
        },
        onVoiceTurnReady: async ({ transcript, defaultPrompt }) => {
          const safeTranscript = String(transcript || "").trim();
          realtimeTranscriptRef.current = safeTranscript;
          if (!safeTranscript || !looksLikeToolCommand(safeTranscript)) {
            realtimeToolTurnRef.current = null;
            realtimeSkipSyncRef.current = false;
            return { prompt: defaultPrompt };
          }
          const toolResponse = await sendAssistantMessage({
            text: safeTranscript,
            surface: "desktop",
            session_key: DEFAULT_ASSISTANT_SESSION_KEY,
            metadata: {
              assistant_mode: "agent",
              assistant_native_control: true,
              current_emotion: currentEmotion,
              expression_label: expressionLabel,
              expression_confidence: expressionConfidence,
              memory_summary: voiceMemorySummary,
              source: "chat_interface_realtime_tool",
            },
          });
          realtimeToolTurnRef.current = toolResponse;
          realtimeSkipSyncRef.current = true;
          return {
            handled: true,
            prompt: buildRealtimeToolFollowupPrompt(toolResponse.text),
          };
        },
        onAssistantTextDelta: (text) => {
          const id = duplexAssistantDraftIdRef.current || `duplex-bot-${Date.now()}`;
          duplexAssistantDraftIdRef.current = id;
          upsertDuplexMessage(id, "bot", text);
        },
        onAssistantTextFinal: (text) => {
          commitDuplexMessage(duplexAssistantDraftIdRef, "bot", text);
          void syncRealtimeConversation(text);
        },
        onError: (message) => {
          setVoiceError(message);
        },
      });
      const voiceMemorySummary = buildMemorySummary(messages, 8, 720);
      await service.start({
        videoElement: duplexVideoRef.current,
        enableLocalVideo: videoEnabled,
        robotSnapshotUrl: robotSnapshotUrl || undefined,
        wsUrl: "ws://127.0.0.1:8091/v1/video/chat/stream",
        localVideoLabel: "Laptop Camera",
        robotVideoLabel: "Robot Camera",
        systemPrompt: [
          "You are the local Qwen3-Omni realtime assistant for the desktop prototype.",
          "The composite frame uses laptop camera on the left and robot camera on the right.",
          "Use both visual streams and the latest speech input to answer in concise Chinese.",
          `Current emotion: ${currentEmotion}`,
          `Expression label: ${expressionLabel}, confidence: ${Number(expressionConfidence || 0).toFixed(2)}`,
          voiceMemorySummary ? `Conversation summary: ${voiceMemorySummary}` : "",
        ].filter(Boolean).join("\n"),
        autoQueryTemplate: robotSnapshotUrl
          ? "Please answer in Chinese using the left laptop view, the right robot view, and the latest speech."
          : "Please answer in Chinese using the current camera view and the latest speech.",
      });
      duplexServiceRef.current = service;
      setVoiceRecording(true);
    } catch (err) {
      setVoiceError(err instanceof Error ? err.message : String(err));
      duplexServiceRef.current = null;
      setVoiceRecording(false);
      setDuplexState("error");
    } finally {
      setVoiceBusy(false);
    }
  };

  const duplexStatusLabel =
    duplexState === "connecting"
      ? "连接中"
      : duplexState === "preparing"
      ? "准备中"
      : duplexState === "listening"
      ? "聆听中"
      : duplexState === "thinking"
      ? "思考中"
      : duplexState === "speaking"
      ? "播报中"
      : duplexState === "interrupted"
      ? "已打断"
      : duplexState === "error"
      ? "异常"
      : "空闲";

  return (
    <div
      className={`ios-chat-shell animate-pop-in ${
        compact ? "rounded-[1.8rem]" : "rounded-[2.8rem]"
      }`}
      onDragOver={onRootDragOver}
      onDragLeave={onRootDragLeave}
      onDrop={onRootDrop}
    >
      {dragActive && (
        <div className="absolute inset-0 z-30 border-2 border-dashed border-indigo-300/60 bg-indigo-400/10 backdrop-blur-md pointer-events-none flex items-center justify-center">
          <div className="ios-float-card-soft px-4 py-2 rounded-[1.1rem] text-indigo-100 text-xs font-semibold">
            释放以上传图片或视频
          </div>
        </div>
      )}
      {!compact && (
        <div className="ios-chat-header p-6 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="ios-chat-avatar ios-chat-avatar--assistant w-12 h-12 rounded-full flex items-center justify-center">
              <Sparkles size={22} fill="white" />
            </div>
            <div>
              <h3 className="text-lg font-black text-white tracking-tight">关怀助手</h3>
              <div className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full ${assistantReady ? "bg-emerald-300 animate-pulse" : "bg-rose-300"}`}></span>
                <span className={`text-[10px] font-semibold tracking-[0.16em] ${assistantReady ? "text-indigo-200" : "text-rose-200"}`}>
                  {assistantReady ? "Qwen3-Omni ???" : "Qwen3-Omni ???"}
                </span>
              </div>
              {!assistantReady && (
                <p className="mt-1 text-[10px] font-semibold text-slate-400">
                  {assistantDetail || "????????????? Qwen3-Omni ??????"}
                </p>
              )}
            </div>
          </div>
          <div className="hidden sm:flex items-center gap-2 px-3 py-1 ios-ghost-chip rounded-full">
            <Activity size={14} className="text-indigo-400" />
            <span className="text-[10px] font-semibold text-slate-300 tracking-[0.16em]">
              状态：
              {voiceRecording
                ? duplexStatusLabel
                : voiceState === "detecting"
                ? "待唤醒"
                : voiceState === "listening"
                ? "聆听中"
                : voiceState === "thinking"
                ? "思考中"
                : voiceState === "speaking"
                ? "播报中"
                : "空闲"}
            </span>
          </div>
        </div>
      )}

      <div ref={messageListRef} className={`ios-chat-thread flex-1 overflow-y-auto no-scrollbar ${compact ? "p-4 space-y-4" : "p-6 space-y-6"}`}>
        {messages.filter((msg) => hasRenderableContent(msg)).map((msg, index) => (
          <div
            key={msg.id}
            className={`flex gap-3 animate-rise ${msg.sender === "user" ? "flex-row-reverse" : "flex-row"}`}
            style={{ animationDelay: `${index * 50}ms` }}
          >
            <div
              className={`ios-chat-avatar rounded-full flex items-center justify-center flex-shrink-0 ${
                compact ? "w-8 h-8" : "w-10 h-10"
              } ${msg.sender === "user" ? "ios-chat-avatar--user" : "ios-chat-avatar--assistant"}`}
            >
              {msg.sender === "user" ? <User size={compact ? 14 : 18} /> : <Bot size={compact ? 16 : 20} />}
            </div>

            <div className={`flex flex-col gap-1 max-w-[85%] ${msg.sender === "user" ? "items-end" : "items-start"}`}>
              {msg.isActiveCare && (
                <span className="text-[9px] font-semibold text-indigo-300 tracking-[0.18em] mb-1 px-2">主动关怀触发</span>
              )}
              <div
                className={`ios-chat-bubble transition-transform duration-300 ${
                  compact ? "p-3 text-[11px]" : "p-4 text-sm"
                } ${
                  msg.sender === "user"
                    ? "ios-chat-bubble--user"
                    : "ios-chat-bubble--assistant"
                }`}
              >
                {Array.isArray(msg.attachments) && msg.attachments.length > 0 && (
                  <div className="flex flex-col gap-2 mb-2">
                    {msg.attachments.map((att, i) =>
                      att.kind === "image" ? (
                        <img
                          key={`${msg.id}-img-${i}`}
                          src={att.url}
                          alt={att.name || "image"}
                          className="max-h-52 rounded-[1rem] border border-white/10 object-contain bg-black/20"
                        />
                      ) : (
                        <video
                          key={`${msg.id}-video-${i}`}
                          src={att.url}
                          controls
                          className="max-h-56 rounded-[1rem] border border-white/10 bg-black/20"
                        />
                      )
                    )}
                  </div>
                )}
                {hasRenderableText(msg.text) ? msg.text : <span className="opacity-75">已发送附件</span>}
              </div>
              <span className="text-[9px] font-semibold text-slate-500 px-2 mt-1">
                {msg.timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              </span>
            </div>
          </div>
        ))}
        {isTyping && (
          <div className="flex items-center gap-3 animate-rise">
            <div className="ios-chat-avatar ios-chat-avatar--assistant w-10 h-10 rounded-full flex items-center justify-center">
              <Bot size={20} className="text-white" />
            </div>
            <div className="ios-typing px-4 py-3 rounded-[1.8rem] rounded-tl-[0.7rem] flex gap-1.5 items-center">
              <span className="ios-typing-dot w-2 h-2 rounded-full"></span>
              <span className="ios-typing-dot w-2 h-2 rounded-full"></span>
              <span className="ios-typing-dot w-2 h-2 rounded-full"></span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className={`ios-chat-composer ${compact ? "p-4" : "p-6"}`}>
        <input ref={fileInputRef} type="file" accept="image/*,video/*" multiple className="hidden" onChange={onAttachmentPicked} />

        {pendingAttachments.length > 0 && (
          <div className="mb-3 flex flex-wrap gap-2">
            {pendingAttachments.map((att, idx) => (
              <div key={`pending-${idx}`} className="relative ios-list-card rounded-[1rem] p-1">
                {att.kind === "image" ? (
                  <img src={att.url} alt={att.name || "image"} className="h-16 w-16 object-cover rounded-[0.8rem]" />
                ) : (
                  <video src={att.url} className="h-16 w-20 object-cover rounded-[0.8rem]" />
                )}
                <button
                  type="button"
                  onClick={() => removePendingAttachment(idx)}
                  className="absolute -top-2 -right-2 rounded-full bg-black/70 text-white p-1 border border-white/10"
                >
                  <X size={12} />
                </button>
              </div>
            ))}
          </div>
        )}

        <div
          className={`ios-chat-composer-bar flex items-center gap-3 rounded-full group transition-all focus-within:ring-2 focus-within:ring-indigo-500/30 ${
            compact ? "p-2 pl-4" : "p-2 pl-6"
          }`}
        >
          <button
            type="button"
            onClick={pickAttachments}
            disabled={uploading || voiceBusy || chatInputDisabled}
            className="text-slate-300 hover:text-white disabled:opacity-40 transition-colors"
            title="上传图片或视频"
          >
            <Paperclip size={compact ? 16 : 18} />
          </button>
          <button
            type="button"
            onClick={handleVoiceToggle}
            disabled={voiceBusy || (!voiceRecording && (uploading || chatInputDisabled))}
            className={`inline-flex items-center gap-2 rounded-full border px-3 py-2 text-[11px] font-bold tracking-[0.12em] disabled:opacity-40 transition-colors ${
              voiceRecording
                ? "border-rose-300/40 bg-rose-400/10 text-rose-200 hover:bg-rose-400/15"
                : "border-cyan-300/30 bg-cyan-400/10 text-cyan-100 hover:bg-cyan-400/15"
            }`}
            title={voiceRecording ? "停止全双工聊天" : "启动全双工聊天"}
          >
            {voiceBusy ? (
              <LoaderCircle size={compact ? 16 : 18} className="animate-spin" />
            ) : voiceRecording ? (
              <Square size={compact ? 16 : 18} fill="currentColor" />
            ) : (
              <Mic size={compact ? 16 : 18} />
            )}
            <span>{voiceRecording ? "停止全双工聊天" : "启动全双工聊天"}</span>
          </button>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSend()}
            onPaste={onInputPaste}
            placeholder={chatInputPlaceholder}
            disabled={chatInputDisabled}
            className={`ios-chat-input flex-1 bg-transparent border-none outline-none text-slate-100 font-semibold placeholder-slate-500 ${
              compact ? "text-[12px]" : "text-sm"
            }`}
          />
          <button
            onClick={handleSend}
            disabled={chatInputDisabled || (!input.trim() && pendingAttachments.length === 0) || isTyping || uploading}
            className={`ios-send-button rounded-full q-bounce disabled:opacity-30 ${
              compact ? "p-3" : "p-3.5"
            }`}
          >
            <Send size={compact ? 16 : 20} fill="currentColor" />
          </button>
        </div>
        {attachmentError && <p className="text-[10px] font-bold text-rose-400 mt-2">{attachmentError}</p>}
        {voiceError && <p className="text-[10px] font-bold text-rose-400 mt-2">{voiceError}</p>}
        {voiceRecording && (
          <p className="text-[10px] font-bold text-amber-300 mt-2">
            全双工聊天已开启：直接说话即可，停顿后自动回应；系统播报时再次开口会尝试打断。当前状态：{duplexStatusLabel}。
          </p>
        )}
        {!compact && (
          <p className="text-[9px] text-center mt-3 text-slate-500 font-semibold tracking-[0.18em]">
            机器人动作指令（语音/动作/表情）由本地引擎实时处理
          </p>
        )}
        <video ref={duplexVideoRef} className="hidden" muted playsInline />
      </div>
    </div>
  );
};
