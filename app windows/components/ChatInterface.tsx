import React, { useEffect, useRef, useState } from "react";
import { ChatAttachment, ChatMessage, EmotionType } from "../types";
import { Send, Sparkles, User, Bot, Activity, Paperclip, X } from "lucide-react";
import { generateCareMessage, generateCareMessageStream } from "../services/llmService";
import { uploadChatAttachment } from "../services/chatService";

interface ChatInterfaceProps {
  currentEmotion: EmotionType;
  initialMessages?: ChatMessage[];
  onSendMessage?: (msg: ChatMessage) => void;
  isGuest?: boolean;
  variant?: "default" | "compact";
  voiceState?: "idle" | "detecting" | "listening" | "thinking" | "speaking";
  expressionLabel?: string;
  expressionConfidence?: number;
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

const hasRenderableContent = (msg: ChatMessage): boolean => {
  if (hasRenderableText(msg.text)) return true;
  return Array.isArray(msg.attachments) && msg.attachments.length > 0;
};

const mergeChatMessages = (local: ChatMessage[], incoming: ChatMessage[]): ChatMessage[] => {
  const byId = new Map<string, ChatMessage>();
  for (const msg of local) byId.set(msg.id, msg);
  for (const msg of incoming) {
    const prev = byId.get(msg.id);
    if (!prev) {
      byId.set(msg.id, msg);
      continue;
    }
    const prevText = String(prev.text || "");
    const nextText = String(msg.text || "");
    byId.set(msg.id, nextText.length >= prevText.length ? msg : prev);
  }
  return Array.from(byId.values()).sort((a, b) => a.timestamp.getTime() - b.timestamp.getTime());
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
  const streamLastFlushMsRef = useRef(0);
  const historyHydratedRef = useRef(false);

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
      streamAbortRef.current?.abort();
      if (streamFlushTimerRef.current != null) {
        window.clearTimeout(streamFlushTimerRef.current);
      }
      streamPendingTextRef.current = "";
      window.cancelAnimationFrame(rafId);
      window.clearTimeout(timer);
    };
  }, []);

  const pickAttachments = () => {
    if (uploading) return;
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
    const files = Array.from(event.target.files || []);
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
    const files = Array.from(event.dataTransfer?.files || []);
    await addAttachmentsFromFiles(files);
  };

  const onInputPaste = async (event: React.ClipboardEvent<HTMLInputElement>) => {
    const files = Array.from(event.clipboardData?.files || []);
    if (!files.length) return;
    event.preventDefault();
    await addAttachmentsFromFiles(files);
  };

  const handleSend = async () => {
    const trimmed = input.trim();
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
    const hasImage = outgoingAttachments.some((a) => a.kind === "image" && String(a.image_data_url || "").startsWith("data:image/"));
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
    setInput("");
    setPendingAttachments([]);
    setAttachmentError("");
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
    const flushStreamText = (force = false) => {
      const pending = streamPendingTextRef.current;
      if (!hasRenderableText(pending)) return;
      const now = Date.now();
      if (!force && now - streamLastFlushMsRef.current < 28) return;
      streamLastFlushMsRef.current = now;
      upsertBotMessage(pending);
    };

    try {
      const requestMessages = [...messages, userMsg];
      const history = requestMessages
        .slice(-6)
        .map((m) => ({
          sender: m.sender,
          text: messageToHistoryText(m),
          timestamp_ms: m.timestamp.getTime(),
        }))
        .filter((item) => item.text.trim().length > 0);
      const memorySummary = buildMemorySummary(requestMessages, 6, 420);

      const llmAttachments = outgoingAttachments
        .filter((a) => a.kind === "image")
        .map((a) => ({
          kind: a.kind,
          url: a.url,
          mime: a.mime,
          name: a.name,
          size: a.size,
          image_data_url: a.image_data_url,
        }));

      let responseText = "";
      if (hasImage) {
        responseText = await generateCareMessage(
          currentEmotion,
          trimmed || messageToHistoryText(userMsg),
          history,
          userMsg.timestamp.getTime(),
          memorySummary,
          expressionLabel,
          expressionConfidence,
          llmAttachments
        );
      } else {
        responseText = await generateCareMessageStream(
          currentEmotion,
          trimmed || messageToHistoryText(userMsg),
          history,
          userMsg.timestamp.getTime(),
          {
            onStart: () => {
              setIsTyping(true);
              streamPendingTextRef.current = "";
              streamLastFlushMsRef.current = 0;
              upsertBotMessage("…");
            },
            onDelta: (_delta, fullText) => {
              setIsTyping(false);
              streamPendingTextRef.current = fullText;
              flushStreamText(false);
              if (streamFlushTimerRef.current == null) {
                streamFlushTimerRef.current = window.setTimeout(() => {
                  flushStreamText(true);
                  streamFlushTimerRef.current = null;
                }, 28);
              }
            },
            onDone: (fullText) => {
              streamPendingTextRef.current = fullText;
              if (streamFlushTimerRef.current != null) {
                window.clearTimeout(streamFlushTimerRef.current);
                streamFlushTimerRef.current = null;
              }
              flushStreamText(true);
            },
          },
          abortCtrl.signal,
          memorySummary,
          expressionLabel,
          expressionConfidence,
          llmAttachments
        );
      }

      if (!responseText.trim()) {
        responseText = await generateCareMessage(
          currentEmotion,
          trimmed || messageToHistoryText(userMsg),
          history,
          userMsg.timestamp.getTime(),
          memorySummary,
          expressionLabel,
          expressionConfidence,
          llmAttachments
        );
      }
      upsertBotMessage(responseText);

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

  return (
    <div
      className={`relative flex flex-col h-full backdrop-blur-3xl shadow-2xl border border-white/5 overflow-hidden animate-pop-in ${
        compact ? "rounded-2xl bg-slate-900/50" : "rounded-[2.5rem] bg-slate-900/40"
      }`}
      onDragOver={onRootDragOver}
      onDragLeave={onRootDragLeave}
      onDrop={onRootDrop}
    >
      {dragActive && (
        <div className="absolute inset-0 z-30 bg-indigo-500/10 border-2 border-dashed border-indigo-300/60 pointer-events-none flex items-center justify-center">
          <div className="px-4 py-2 rounded-xl bg-slate-900/80 text-indigo-200 text-xs font-bold">
            释放以上传图片或视频
          </div>
        </div>
      )}
      {!compact && (
        <div className="p-6 flex items-center justify-between border-b border-white/5 bg-slate-950/20">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-full bg-gradient-to-tr from-indigo-500 to-fuchsia-500 flex items-center justify-center text-white shadow-lg animate-pulse-glow">
              <Sparkles size={22} fill="white" />
            </div>
            <div>
              <h3 className="text-lg font-black text-white tracking-tight">关怀助手</h3>
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 bg-green-400 rounded-full animate-pulse"></span>
                <span className="text-[10px] font-bold text-indigo-300 uppercase tracking-tighter">音频与视频帧已同步</span>
              </div>
            </div>
          </div>
          <div className="hidden sm:flex items-center gap-2 px-3 py-1 bg-white/5 rounded-full border border-white/10">
            <Activity size={14} className="text-indigo-400" />
            <span className="text-[10px] font-bold text-slate-400 uppercase">
              状态：
              {voiceState === "detecting"
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

      <div ref={messageListRef} className={`flex-1 overflow-y-auto no-scrollbar ${compact ? "p-4 space-y-4" : "p-6 space-y-6"}`}>
        {messages.filter((msg) => hasRenderableContent(msg)).map((msg, index) => (
          <div
            key={msg.id}
            className={`flex gap-3 animate-pop-in ${msg.sender === "user" ? "flex-row-reverse" : "flex-row"}`}
            style={{ animationDelay: `${index * 50}ms` }}
          >
            <div
              className={`rounded-full flex items-center justify-center flex-shrink-0 shadow-xl ${
                compact ? "w-8 h-8" : "w-10 h-10"
              } ${msg.sender === "user" ? "bg-slate-700 text-slate-300" : "bg-indigo-600 text-white"}`}
            >
              {msg.sender === "user" ? <User size={compact ? 14 : 18} /> : <Bot size={compact ? 16 : 20} />}
            </div>

            <div className={`flex flex-col gap-1 max-w-[85%] ${msg.sender === "user" ? "items-end" : "items-start"}`}>
              {msg.isActiveCare && (
                <span className="text-[9px] font-black text-indigo-400 uppercase tracking-widest mb-1 px-2">主动关怀触发</span>
              )}
              <div
                className={`rounded-3xl font-bold leading-relaxed shadow-lg transition-transform duration-300 hover:scale-[1.01] ${
                  compact ? "p-3 text-[11px]" : "p-4 text-sm"
                } ${
                  msg.sender === "user"
                    ? "bg-indigo-500 text-white rounded-tr-none"
                    : "bg-slate-800 text-slate-100 rounded-tl-none border border-white/5"
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
                          className="max-h-52 rounded-xl border border-white/10 object-contain bg-black/20"
                        />
                      ) : (
                        <video
                          key={`${msg.id}-video-${i}`}
                          src={att.url}
                          controls
                          className="max-h-56 rounded-xl border border-white/10 bg-black/20"
                        />
                      )
                    )}
                  </div>
                )}
                {hasRenderableText(msg.text) ? msg.text : <span className="opacity-75">已发送附件</span>}
              </div>
              <span className="text-[9px] font-bold text-slate-600 px-2 mt-1">
                {msg.timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              </span>
            </div>
          </div>
        ))}
        {isTyping && (
          <div className="flex items-center gap-3 animate-pop-in">
            <div className="w-10 h-10 rounded-full bg-indigo-600 flex items-center justify-center shadow-lg">
              <Bot size={20} className="text-white" />
            </div>
            <div className="bg-slate-800 border border-white/5 px-4 py-3 rounded-3xl rounded-tl-none flex gap-1.5 items-center">
              <span className="w-2 h-2 bg-indigo-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }}></span>
              <span className="w-2 h-2 bg-indigo-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }}></span>
              <span className="w-2 h-2 bg-indigo-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }}></span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className={`${compact ? "p-4" : "p-6"} bg-slate-950/40 backdrop-blur-xl border-t border-white/5`}>
        <input ref={fileInputRef} type="file" accept="image/*,video/*" multiple className="hidden" onChange={onAttachmentPicked} />

        {pendingAttachments.length > 0 && (
          <div className="mb-3 flex flex-wrap gap-2">
            {pendingAttachments.map((att, idx) => (
              <div key={`pending-${idx}`} className="relative rounded-xl border border-white/10 bg-slate-900/80 p-1">
                {att.kind === "image" ? (
                  <img src={att.url} alt={att.name || "image"} className="h-16 w-16 object-cover rounded-lg" />
                ) : (
                  <video src={att.url} className="h-16 w-20 object-cover rounded-lg" />
                )}
                <button
                  type="button"
                  onClick={() => removePendingAttachment(idx)}
                  className="absolute -top-2 -right-2 rounded-full bg-black/70 text-white p-1"
                >
                  <X size={12} />
                </button>
              </div>
            ))}
          </div>
        )}

        <div
          className={`flex items-center gap-3 bg-slate-900/80 rounded-full border border-white/10 shadow-inner group transition-all focus-within:ring-2 focus-within:ring-indigo-500/30 ${
            compact ? "p-2 pl-4" : "p-2 pl-6"
          }`}
        >
          <button
            type="button"
            onClick={pickAttachments}
            disabled={uploading}
            className="text-slate-300 hover:text-white disabled:opacity-40"
            title="上传图片或视频"
          >
            <Paperclip size={compact ? 16 : 18} />
          </button>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSend()}
            onPaste={onInputPaste}
            placeholder="和你的伙伴聊聊…"
            className={`flex-1 bg-transparent border-none outline-none text-slate-200 font-bold placeholder-slate-500 ${
              compact ? "text-[12px]" : "text-sm"
            }`}
          />
          <button
            onClick={handleSend}
            disabled={(!input.trim() && pendingAttachments.length === 0) || isTyping || uploading}
            className={`bg-indigo-500 text-white rounded-full q-bounce disabled:opacity-30 shadow-lg shadow-indigo-500/20 ${
              compact ? "p-3" : "p-3.5"
            }`}
          >
            <Send size={compact ? 16 : 20} fill="currentColor" />
          </button>
        </div>
        {attachmentError && <p className="text-[10px] font-bold text-rose-400 mt-2">{attachmentError}</p>}
        {!compact && (
          <p className="text-[9px] text-center mt-3 text-slate-600 font-black uppercase tracking-tighter">
            机器人动作指令（语音/动作/表情）由本地引擎实时处理
          </p>
        )}
      </div>
    </div>
  );
};
