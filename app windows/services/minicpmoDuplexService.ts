import {
  interruptAssistantSession,
  sendAssistantMessage,
  startAssistantSession,
  stopAssistantSession,
  type AssistantSessionStartRequest,
  type AssistantSessionStartResponse,
} from "./assistantService";
import { DuplexSession } from "./minicpmo/native/duplex-session.js";
import { arrayBufferToBase64 } from "./minicpmo/native/duplex-utils.js";

type DuplexSessionLike = {
  running: boolean;
  paused: boolean;
  forceListenActive: boolean;
  currentSpeakText: string;
  audioPlayer: { turnActive: boolean; endTurn: () => void; stopAll: () => void };
  onSpeakStart: (text: string) => unknown;
  onSpeakUpdate: (handle: unknown, text: string) => void;
  onSpeakEnd: () => void;
  onListenResult: (result: { text?: string; [key: string]: unknown }) => void;
  onRunningChange: (running: boolean) => void;
  onPauseStateChange: (state: string) => void;
  onForceListenChange: (active: boolean) => void;
  onSystemLog: (text: string) => void;
  onMetrics: (data: Record<string, unknown>) => void;
  onPrepared: () => Promise<void> | void;
  start: (
    systemPrompt: string,
    preparePayload: Record<string, unknown>,
    startMediaFn?: () => Promise<void>
  ) => Promise<void>;
  sendChunk: (msg: Record<string, unknown>) => void;
  toggleForceListen: () => void;
  stop: () => void;
};

export interface DuplexUserTurn {
  text: string;
  committed: boolean;
}

export interface DuplexAssistantTurn {
  text: string;
  committed: boolean;
}

export interface MiniCpmDuplexCallbacks {
  onStatus?: (status: string) => void;
  onError?: (message: string) => void;
  onUserTurn?: (turn: DuplexUserTurn) => void;
  onAssistantTurn?: (turn: DuplexAssistantTurn) => void;
  onRunningChange?: (running: boolean) => void;
  onForceListenChange?: (active: boolean) => void;
  onMetrics?: (data: Record<string, unknown>) => void;
}

const DEFAULT_SURFACE = "desktop";
const DEFAULT_BARGE_RMS = 0.045;
const DEFAULT_BARGE_FRAMES = 3;
const USER_COMMIT_DEBOUNCE_MS = 1400;

const computeRms = (chunk: Float32Array) => {
  if (!chunk.length) return 0;
  let sum = 0;
  for (let i = 0; i < chunk.length; i += 1) {
    const value = chunk[i];
    sum += value * value;
  }
  return Math.sqrt(sum / chunk.length);
};

const nowMs = () => Date.now();

export class MiniCpmDuplexService {
  private callbacks: MiniCpmDuplexCallbacks;
  private session: DuplexSessionLike | null = null;
  private startInfo: AssistantSessionStartResponse | null = null;
  private audioContext: AudioContext | null = null;
  private audioStream: MediaStream | null = null;
  private audioSource: MediaStreamAudioSourceNode | null = null;
  private analyserNode: AnalyserNode | null = null;
  private captureNode: AudioWorkletNode | null = null;
  private userDraft = "";
  private assistantDraft = "";
  private userCommitTimer: number | null = null;
  private active = false;
  private bargeHotFrames = 0;
  private forceListenLatched = false;
  private sessionEpoch = 0;
  private turnPipeline: Promise<void> = Promise.resolve();
  private lastSpokenAssistantText = "";

  constructor(callbacks: MiniCpmDuplexCallbacks = {}) {
    this.callbacks = callbacks;
  }

  get running() {
    return Boolean(this.active && this.session?.running);
  }

  get sessionKey() {
    return this.startInfo?.session_key || "";
  }

  get duplexSessionId() {
    return this.startInfo?.duplex_session_id || "";
  }

  async start(payload: AssistantSessionStartRequest = {}) {
    if (this.running) {
      return this.startInfo;
    }
    this.sessionEpoch += 1;
    this.emitStatus("正在启动 MiniCPM-o 官方全双工语音…");
    const startInfo = await startAssistantSession({
      surface: payload.surface || DEFAULT_SURFACE,
      session_key: payload.session_key,
      device_id: payload.device_id,
      sender_id: payload.sender_id,
    });
    this.startInfo = startInfo;
    this.userDraft = "";
    this.assistantDraft = "";
    this.forceListenLatched = false;
    this.bargeHotFrames = 0;
    this.lastSpokenAssistantText = "";

    const DuplexSessionCtor = DuplexSession as new (
      prefix: string,
      config?: Record<string, unknown>
    ) => DuplexSessionLike;
    const session = new DuplexSessionCtor("desktop", {
      outputSampleRate: 24000,
      getPlaybackDelayMs: () => 180,
      getWsUrl: () => startInfo.ws_url,
    });
    this.session = session;

    session.onSystemLog = (text: string) => {
      if (text) {
        this.emitStatus(text);
      }
    };
    session.onRunningChange = (running: boolean) => {
      this.active = running;
      this.callbacks.onRunningChange?.(running);
      this.emitStatus(running ? "全双工语音会话已连接" : "全双工语音会话已结束");
    };
    session.onForceListenChange = (active: boolean) => {
      this.forceListenLatched = active;
      this.callbacks.onForceListenChange?.(active);
    };
    session.onPauseStateChange = (state: string) => {
      this.emitStatus(`会话状态：${state}`);
    };
    session.onPrepared = async () => {
      this.emitStatus("已连接官方 MiniCPM-o duplex，会话已就绪");
    };
    session.onMetrics = (data: Record<string, unknown>) => {
      this.callbacks.onMetrics?.(data);
    };
    session.onListenResult = (result: { text?: string; [key: string]: unknown }) => {
      const text = String(result.text || "").trim();
      if (!text) {
        return;
      }
      this.userDraft = text;
      this.callbacks.onUserTurn?.({ text, committed: false });
      this.scheduleUserCommit();
      if (this.forceListenLatched && text.length >= 2) {
        session.toggleForceListen();
      }
    };
    session.onSpeakStart = (text: string) => {
      if (this.userDraft) {
        this.commitUserDraft();
      }
      this.assistantDraft = text;
      this.lastSpokenAssistantText = text;
      this.callbacks.onAssistantTurn?.({ text, committed: false });
      return { startedAt: nowMs() };
    };
    session.onSpeakUpdate = (_handle: unknown, text: string) => {
      this.assistantDraft = text;
      this.lastSpokenAssistantText = text;
      this.callbacks.onAssistantTurn?.({ text, committed: false });
    };
    session.onSpeakEnd = () => {
      this.assistantDraft = "";
    };

    await session.start(
      startInfo.prefix_system_prompt,
      startInfo.prepare_payload || {},
      async () => this.startMicrophoneCapture(startInfo)
    );
    return startInfo;
  }

  async stop() {
    this.sessionEpoch += 1;
    this.clearUserCommitTimer();
    const session = this.session;
    const startInfo = this.startInfo;
    this.active = false;
    if (session) {
      try {
        session.stop();
      } catch {
        // ignore
      }
    }
    await this.stopMicrophoneCapture();
    if (startInfo?.session_key) {
      try {
        await stopAssistantSession({
          surface: startInfo.surface,
          session_key: startInfo.session_key,
          duplex_session_id: startInfo.duplex_session_id,
        });
      } catch {
        // ignore
      }
    }
    this.session = null;
    this.startInfo = null;
    this.forceListenLatched = false;
    this.bargeHotFrames = 0;
    this.userDraft = "";
    this.assistantDraft = "";
    this.lastSpokenAssistantText = "";
    this.callbacks.onRunningChange?.(false);
    this.emitStatus("全双工语音已停止");
  }

  async interrupt() {
    if (!this.session || !this.startInfo) {
      return;
    }
    if (!this.session.forceListenActive) {
      this.session.toggleForceListen();
    }
    try {
      await interruptAssistantSession({
        surface: this.startInfo.surface,
        session_key: this.startInfo.session_key,
        duplex_session_id: this.startInfo.duplex_session_id,
      });
    } catch {
      // ignore backend bookkeeping failures
    }
  }

  private async startMicrophoneCapture(startInfo: AssistantSessionStartResponse) {
    this.audioContext = new AudioContext({ sampleRate: startInfo.sample_rate || 16000 });
    if (this.audioContext.state === "suspended") {
      await this.audioContext.resume();
    }
    await this.audioContext.audioWorklet.addModule(
      new URL("./minicpmo/native/capture-processor.js", import.meta.url)
    );
    this.audioStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
      video: false,
    });
    this.audioSource = this.audioContext.createMediaStreamSource(this.audioStream);
    this.analyserNode = this.audioContext.createAnalyser();
    this.analyserNode.fftSize = 2048;
    const chunkSize = Math.max(
      1,
      Math.round((startInfo.sample_rate || 16000) * ((startInfo.audio_chunk_ms || 1000) / 1000))
    );
    this.captureNode = new AudioWorkletNode(this.audioContext, "capture-processor", {
      processorOptions: { chunkSize },
    });
    this.audioSource.connect(this.analyserNode);
    this.analyserNode.connect(this.captureNode);
    this.captureNode.port.postMessage({ command: "start" });
    this.captureNode.port.onmessage = (
      event: MessageEvent<{ type?: string; audio?: Float32Array }>
    ) => {
      if (
        event.data?.type !== "chunk" ||
        !event.data.audio ||
        !this.session ||
        !this.session.running ||
        this.session.paused
      ) {
        return;
      }
      const chunk = event.data.audio;
      const rms = computeRms(chunk);
      const assistantSpeaking = Boolean(this.session.currentSpeakText);
      if (assistantSpeaking) {
        this.bargeHotFrames = rms >= DEFAULT_BARGE_RMS ? this.bargeHotFrames + 1 : 0;
        if (this.bargeHotFrames >= DEFAULT_BARGE_FRAMES && !this.session.forceListenActive) {
          void this.interrupt();
        }
      } else {
        this.bargeHotFrames = 0;
        if (this.session.forceListenActive && rms < DEFAULT_BARGE_RMS * 0.75) {
          this.session.toggleForceListen();
        }
      }
      this.session.sendChunk({
        type: "audio_chunk",
        audio_base64: arrayBufferToBase64(chunk.buffer),
      });
    };
  }

  private async stopMicrophoneCapture() {
    try {
      this.captureNode?.port.postMessage({ command: "stop" });
    } catch {
      // ignore
    }
    try {
      this.captureNode?.disconnect();
    } catch {
      // ignore
    }
    try {
      this.analyserNode?.disconnect();
    } catch {
      // ignore
    }
    try {
      this.audioSource?.disconnect();
    } catch {
      // ignore
    }
    if (this.audioStream) {
      this.audioStream.getTracks().forEach((track) => track.stop());
    }
    if (this.audioContext) {
      await this.audioContext.close().catch(() => undefined);
    }
    this.captureNode = null;
    this.analyserNode = null;
    this.audioSource = null;
    this.audioStream = null;
    this.audioContext = null;
  }

  private scheduleUserCommit() {
    this.clearUserCommitTimer();
    this.userCommitTimer = window.setTimeout(() => {
      this.commitUserDraft();
    }, USER_COMMIT_DEBOUNCE_MS);
  }

  private clearUserCommitTimer() {
    if (this.userCommitTimer != null) {
      window.clearTimeout(this.userCommitTimer);
      this.userCommitTimer = null;
    }
  }

  private commitUserDraft() {
    this.clearUserCommitTimer();
    const text = this.userDraft.trim();
    if (!text) {
      return;
    }
    this.userDraft = "";
    this.callbacks.onUserTurn?.({ text, committed: true });
    this.enqueueAssistantReply(text);
  }

  private enqueueAssistantReply(userText: string) {
    const epoch = this.sessionEpoch;
    this.turnPipeline = this.turnPipeline
      .then(async () => {
        await this.fetchAssistantReply(userText, epoch);
      })
      .catch((error) => {
        const message = error instanceof Error ? error.message : String(error);
        this.callbacks.onError?.(message);
      });
  }

  private async fetchAssistantReply(userText: string, epoch: number) {
    const normalized = String(userText || "").trim();
    const startInfo = this.startInfo;
    if (!normalized || !startInfo?.session_key) {
      return;
    }
    this.emitStatus("OpenClaw + Gemma4 正在生成回复…");
    try {
      const response = await sendAssistantMessage({
        text: normalized,
        surface: startInfo.surface || DEFAULT_SURFACE,
        session_key: startInfo.session_key,
        metadata: {
          source: "minicpmo_duplex",
          duplex_session_id: startInfo.duplex_session_id,
          duplex_provider: startInfo.provider,
          memory_summary: startInfo.memory_summary || "",
        },
      });
      if (epoch !== this.sessionEpoch || !this.active) {
        return;
      }
      const replyText = String(response.text || "").trim();
      if (!replyText) {
        return;
      }
      this.assistantDraft = "";
      this.lastSpokenAssistantText = replyText;
      this.callbacks.onAssistantTurn?.({ text: replyText, committed: true });
      this.emitStatus("OpenClaw + Gemma4 回复已同步到当前会话");
    } catch (error) {
      if (epoch !== this.sessionEpoch || !this.active) {
        return;
      }
      const fallbackText = this.lastSpokenAssistantText.trim();
      if (fallbackText) {
        this.callbacks.onAssistantTurn?.({ text: fallbackText, committed: true });
      }
      throw error;
    }
  }

  private emitStatus(status: string) {
    this.callbacks.onStatus?.(status);
  }
}
