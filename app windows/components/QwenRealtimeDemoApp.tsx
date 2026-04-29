import React, { useEffect, useMemo, useRef, useState } from "react";
import { Camera, Mic, Square, Radio, Send, RotateCcw, Settings2 } from "lucide-react";

import {
  QwenRealtimeState,
  QwenRealtimeVideoService,
} from "../services/qwenRealtimeVideoService";

type DemoMessage = {
  id: string;
  role: "system" | "user" | "assistant";
  text: string;
  time: string;
};

const DEFAULT_WS_URL = "ws://127.0.0.1:8091/v1/video/chat/stream";
const DEFAULT_SYSTEM_PROMPT =
  "你是部署在本地桌面端的中文实时多模态助手。请同时参考用户的实时语音和连续摄像头画面，优先给出简洁自然的中文回复。";
const DEFAULT_AUTO_QUERY =
  "请结合当前连续画面和我刚刚说的话，直接用中文回复；必要时先说你看到了什么，再回答用户。";

const stateColor: Record<QwenRealtimeState, string> = {
  idle: "bg-slate-500/20 text-slate-200 border-slate-400/30",
  connecting: "bg-cyan-500/20 text-cyan-200 border-cyan-400/30",
  listening: "bg-emerald-500/20 text-emerald-200 border-emerald-400/30",
  "user-speaking": "bg-amber-500/20 text-amber-100 border-amber-400/30",
  thinking: "bg-indigo-500/20 text-indigo-100 border-indigo-400/30",
  speaking: "bg-fuchsia-500/20 text-fuchsia-100 border-fuchsia-400/30",
  interrupted: "bg-orange-500/20 text-orange-100 border-orange-400/30",
  error: "bg-rose-500/20 text-rose-100 border-rose-400/30",
};

const stateLabel: Record<QwenRealtimeState, string> = {
  idle: "未启动",
  connecting: "连接中",
  listening: "监听中",
  "user-speaking": "用户说话中",
  thinking: "思考中",
  speaking: "回复中",
  interrupted: "已打断重连",
  error: "错误",
};

const timeLabel = () =>
  new Date().toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

export const QwenRealtimeDemoApp: React.FC = () => {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const serviceRef = useRef<QwenRealtimeVideoService | null>(null);
  const assistantDraftRef = useRef("");
  const [state, setState] = useState<QwenRealtimeState>("idle");
  const [stateDetail, setStateDetail] = useState("等待启动实时会话");
  const [wsUrl, setWsUrl] = useState(DEFAULT_WS_URL);
  const [systemPrompt, setSystemPrompt] = useState(DEFAULT_SYSTEM_PROMPT);
  const [autoQuery, setAutoQuery] = useState(DEFAULT_AUTO_QUERY);
  const [manualPrompt, setManualPrompt] = useState("");
  const [frameIntervalMs, setFrameIntervalMs] = useState(800);
  const [voiceLevel, setVoiceLevel] = useState(0);
  const [running, setRunning] = useState(false);
  const [messages, setMessages] = useState<DemoMessage[]>([
    {
      id: "boot",
      role: "system",
      text: "这是一版直接接 `ws://127.0.0.1:8091/v1/video/chat/stream` 的本地实时客户端。打开后会自动采集麦克风与摄像头，并在你说完一句后自动触发多模态回答。",
      time: timeLabel(),
    },
  ]);
  const [draftReply, setDraftReply] = useState("");
  const [eventLog, setEventLog] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  const pushMessage = (role: DemoMessage["role"], text: string) => {
    const trimmed = String(text || "").trim();
    if (!trimmed) return;
    setMessages((prev) => [
      ...prev,
      {
        id: `${role}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        role,
        text: trimmed,
        time: timeLabel(),
      },
    ]);
  };

  const pushEvent = (text: string) => {
    const label = `[${timeLabel()}] ${text}`;
    setEventLog((prev) => [label, ...prev].slice(0, 10));
  };

  const startClient = async () => {
    if (!videoRef.current || busy) return;
    setBusy(true);
    const service = new QwenRealtimeVideoService({
      onStateChange: (nextState, detail) => {
        setState(nextState);
        setStateDetail(detail || stateLabel[nextState]);
        if (nextState === "idle" || nextState === "error") {
          setRunning(false);
        }
        if (nextState === "listening" || nextState === "user-speaking" || nextState === "thinking" || nextState === "speaking") {
          setRunning(true);
        }
      },
      onAssistantTextDelta: (text) => {
        assistantDraftRef.current = text;
        setDraftReply(text);
      },
      onAssistantTextFinal: (text) => {
        assistantDraftRef.current = "";
        setDraftReply("");
        pushMessage("assistant", text);
      },
      onVoiceLevel: (level) => setVoiceLevel(level),
      onTurnCommitted: (kind, prompt) => {
        if (kind === "voice") {
          pushMessage("user", "【实时语音 + 实时画面】");
          pushEvent(`voice_query:${prompt.slice(0, 60)}`);
        } else {
          pushMessage("user", prompt);
          pushEvent(`manual_query:${prompt.slice(0, 60)}`);
        }
      },
      onEvent: (message) => pushEvent(message),
      onError: (message) => pushEvent(`error:${message}`),
    });

    try {
      await service.start({
        videoElement: videoRef.current,
        wsUrl,
        systemPrompt,
        autoQueryTemplate: autoQuery,
        frameIntervalMs,
      });
      serviceRef.current = service;
      setRunning(true);
    } catch (error) {
      setRunning(false);
      setState("error");
      setStateDetail(String(error));
      pushEvent(`start_failed:${String(error)}`);
    } finally {
      setBusy(false);
    }
  };

  const stopClient = async () => {
    setBusy(true);
    try {
      await serviceRef.current?.stop();
    } finally {
      serviceRef.current = null;
      setRunning(false);
      setDraftReply("");
      assistantDraftRef.current = "";
      setBusy(false);
    }
  };

  const sendManualQuery = async () => {
    const text = manualPrompt.trim();
    if (!text || !serviceRef.current) return;
    setManualPrompt("");
    assistantDraftRef.current = "";
    setDraftReply("");
    await serviceRef.current.request(text).catch((error) => {
      pushEvent(`manual_query_failed:${String(error)}`);
    });
  };

  useEffect(() => {
    return () => {
      void serviceRef.current?.stop();
    };
  }, []);

  const meterWidth = useMemo(() => `${Math.max(8, Math.round(voiceLevel * 100))}%`, [voiceLevel]);

  return (
    <div className="min-h-screen bg-[#08101b] text-slate-100">
      <div className="mx-auto flex min-h-screen max-w-[1600px] flex-col gap-5 px-6 py-6">
        <header className="flex flex-wrap items-center justify-between gap-4 rounded-3xl border border-white/10 bg-white/5 px-6 py-5 backdrop-blur">
          <div>
            <div className="text-xs uppercase tracking-[0.32em] text-cyan-200/70">Qwen3-Omni Realtime Client</div>
            <h1 className="mt-2 text-3xl font-semibold">视频 + 语音 实时客户端</h1>
            <p className="mt-2 max-w-3xl text-sm text-slate-300">
              这版直接接本机代理的 <code>ws://127.0.0.1:8091/v1/video/chat/stream</code>，优先把麦克风、摄像头、流式语音回复和客户端侧打断跑通。
            </p>
          </div>
          <div className={`rounded-full border px-4 py-2 text-sm ${stateColor[state]}`}>
            <div className="font-medium">{stateLabel[state]}</div>
            <div className="text-xs opacity-80">{stateDetail}</div>
          </div>
        </header>

        <div className="grid flex-1 grid-cols-1 gap-5 xl:grid-cols-[1.08fr_0.92fr]">
          <section className="rounded-3xl border border-white/10 bg-[#0d1627]/90 p-4 shadow-2xl shadow-black/20">
            <div className="grid gap-4 lg:grid-cols-[1.15fr_0.85fr]">
              <div className="overflow-hidden rounded-3xl border border-white/10 bg-black">
                <div className="flex items-center justify-between border-b border-white/10 px-4 py-3 text-sm text-slate-300">
                  <span className="inline-flex items-center gap-2"><Camera size={16} /> 本地摄像头预览</span>
                  <span className="text-xs text-slate-400">实时帧会持续送进 Qwen 视频流接口</span>
                </div>
                <div className="relative aspect-video bg-black">
                  <video ref={videoRef} className="h-full w-full object-cover" autoPlay muted playsInline />
                  {!running ? (
                    <div className="absolute inset-0 grid place-items-center bg-black/55 text-center text-sm text-slate-300">
                      <div>
                        <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full border border-white/10 bg-white/5">
                          <Radio size={22} />
                        </div>
                        启动后会请求摄像头和麦克风权限
                      </div>
                    </div>
                  ) : null}
                </div>
              </div>

              <div className="flex flex-col gap-4">
                <div className="rounded-3xl border border-white/10 bg-white/5 p-4">
                  <div className="mb-3 flex items-center gap-2 text-sm font-medium text-slate-200">
                    <Settings2 size={16} /> 会话配置
                  </div>
                  <div className="space-y-3 text-sm">
                    <label className="block">
                      <div className="mb-1 text-slate-400">WebSocket 地址</div>
                      <input
                        value={wsUrl}
                        onChange={(event) => setWsUrl(event.target.value)}
                        className="w-full rounded-2xl border border-white/10 bg-black/25 px-3 py-2 text-slate-100 outline-none"
                      />
                    </label>
                    <label className="block">
                      <div className="mb-1 text-slate-400">系统提示</div>
                      <textarea
                        value={systemPrompt}
                        onChange={(event) => setSystemPrompt(event.target.value)}
                        rows={4}
                        className="w-full rounded-2xl border border-white/10 bg-black/25 px-3 py-2 text-slate-100 outline-none"
                      />
                    </label>
                    <label className="block">
                      <div className="mb-1 text-slate-400">自动追问模板</div>
                      <textarea
                        value={autoQuery}
                        onChange={(event) => setAutoQuery(event.target.value)}
                        rows={4}
                        className="w-full rounded-2xl border border-white/10 bg-black/25 px-3 py-2 text-slate-100 outline-none"
                      />
                    </label>
                    <label className="block">
                      <div className="mb-1 text-slate-400">视频帧间隔 (ms)</div>
                      <input
                        type="number"
                        min={200}
                        step={100}
                        value={frameIntervalMs}
                        onChange={(event) => setFrameIntervalMs(Math.max(200, Number(event.target.value) || 800))}
                        className="w-full rounded-2xl border border-white/10 bg-black/25 px-3 py-2 text-slate-100 outline-none"
                      />
                    </label>
                  </div>
                </div>

                <div className="rounded-3xl border border-white/10 bg-white/5 p-4">
                  <div className="mb-3 flex items-center gap-2 text-sm font-medium text-slate-200">
                    <Mic size={16} /> 输入音量
                  </div>
                  <div className="h-3 rounded-full bg-white/10">
                    <div className="h-3 rounded-full bg-gradient-to-r from-cyan-400 via-emerald-400 to-fuchsia-400 transition-all" style={{ width: meterWidth }} />
                  </div>
                  <div className="mt-3 text-xs text-slate-400">
                    当前实现是客户端侧 VAD（语音起止检测）+ 客户端侧打断重连。先把你说话、模型回话、插话中断都跑起来。
                  </div>
                </div>

                <div className="grid gap-3 sm:grid-cols-2">
                  <button
                    onClick={() => void startClient()}
                    disabled={running || busy}
                    className="inline-flex items-center justify-center gap-2 rounded-2xl bg-cyan-500 px-4 py-3 text-sm font-medium text-slate-950 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <Radio size={16} />
                    启动实时客户端
                  </button>
                  <button
                    onClick={() => void stopClient()}
                    disabled={!running || busy}
                    className="inline-flex items-center justify-center gap-2 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-medium text-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <Square size={16} />
                    停止
                  </button>
                </div>
              </div>
            </div>
          </section>

          <section className="flex min-h-0 flex-col rounded-3xl border border-white/10 bg-[#0d1627]/90 p-4 shadow-2xl shadow-black/20">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium text-slate-100">对话面板</div>
                <div className="text-xs text-slate-400">语音自动触发后会用占位符标记一轮“实时语音 + 实时画面”输入。</div>
              </div>
              <button
                onClick={() => {
                  setMessages((prev) => prev.slice(0, 1));
                  setDraftReply("");
                  assistantDraftRef.current = "";
                  setEventLog([]);
                }}
                className="inline-flex items-center gap-2 rounded-2xl border border-white/10 bg-white/5 px-3 py-2 text-xs text-slate-200"
              >
                <RotateCcw size={14} />
                清空记录
              </button>
            </div>

            <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[1.08fr_0.92fr]">
              <div className="flex min-h-0 flex-col rounded-3xl border border-white/10 bg-black/15">
                <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
                  {messages.map((message) => (
                    <div
                      key={message.id}
                      className={`rounded-2xl border px-4 py-3 text-sm ${
                        message.role === "assistant"
                          ? "border-fuchsia-400/20 bg-fuchsia-500/10"
                          : message.role === "user"
                            ? "border-cyan-400/20 bg-cyan-500/10"
                            : "border-white/10 bg-white/5"
                      }`}
                    >
                      <div className="mb-2 flex items-center justify-between text-[11px] uppercase tracking-[0.2em] text-slate-400">
                        <span>{message.role}</span>
                        <span>{message.time}</span>
                      </div>
                      <div className="whitespace-pre-wrap leading-6 text-slate-100">{message.text}</div>
                    </div>
                  ))}
                  {draftReply ? (
                    <div className="rounded-2xl border border-fuchsia-400/20 bg-fuchsia-500/10 px-4 py-3 text-sm">
                      <div className="mb-2 text-[11px] uppercase tracking-[0.2em] text-slate-400">assistant / streaming</div>
                      <div className="whitespace-pre-wrap leading-6 text-slate-100">{draftReply}</div>
                    </div>
                  ) : null}
                </div>

                <div className="border-t border-white/10 px-4 py-4">
                  <div className="mb-2 text-xs text-slate-400">手动追问（会直接发一条 video.query，不等语音）</div>
                  <div className="flex gap-3">
                    <textarea
                      value={manualPrompt}
                      onChange={(event) => setManualPrompt(event.target.value)}
                      rows={3}
                      placeholder="例如：看看我现在桌上的东西，然后给我一句建议。"
                      className="flex-1 rounded-2xl border border-white/10 bg-black/25 px-3 py-2 text-sm text-slate-100 outline-none"
                    />
                    <button
                      onClick={() => void sendManualQuery()}
                      disabled={!running || !manualPrompt.trim()}
                      className="inline-flex min-w-[118px] items-center justify-center gap-2 rounded-2xl bg-fuchsia-500 px-4 py-3 text-sm font-medium text-slate-950 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      <Send size={16} />
                      发送
                    </button>
                  </div>
                </div>
              </div>

              <div className="flex min-h-0 flex-col gap-4">
                <div className="rounded-3xl border border-white/10 bg-white/5 p-4">
                  <div className="mb-3 text-sm font-medium text-slate-100">当前接线</div>
                  <ul className="space-y-2 text-sm text-slate-300">
                    <li>• 当前直接走 <code>/v1/video/chat/stream</code> WebSocket。</li>
                    <li>• 摄像头帧会按固定间隔发送到视频流接口。</li>
                    <li>• 麦克风 PCM16 音频会持续流式发送。</li>
                    <li>• 说完一句后客户端自动发出 <code>video.query</code>。</li>
                    <li>• 插话时客户端会停播并重建会话，优先保证“可打断”。</li>
                  </ul>
                </div>
                <div className="min-h-0 flex-1 rounded-3xl border border-white/10 bg-black/15 p-4">
                  <div className="mb-3 text-sm font-medium text-slate-100">事件日志</div>
                  <div className="space-y-2 overflow-y-auto text-xs text-slate-300">
                    {eventLog.length ? (
                      eventLog.map((event) => (
                        <div key={event} className="rounded-xl border border-white/5 bg-white/5 px-3 py-2">
                          {event}
                        </div>
                      ))
                    ) : (
                      <div className="rounded-xl border border-white/5 bg-white/5 px-3 py-2 text-slate-400">启动后会显示连接、查询和重连事件。</div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
};
