export type QwenRealtimeState =
  | "idle"
  | "connecting"
  | "listening"
  | "user-speaking"
  | "thinking"
  | "speaking"
  | "interrupted"
  | "error";

export interface QwenRealtimeCallbacks {
  onStateChange?: (state: QwenRealtimeState, detail?: string) => void;
  onAssistantTextDelta?: (text: string) => void;
  onAssistantTextFinal?: (text: string) => void;
  onUserTranscriptDelta?: (text: string) => void;
  onUserTranscriptFinal?: (text: string) => void;
  onVoiceLevel?: (level: number) => void;
  onTurnCommitted?: (kind: "voice" | "manual", prompt: string) => void;
  onVoiceTurnReady?: (payload: { transcript: string; defaultPrompt: string }) => Promise<{ handled?: boolean; prompt?: string } | void> | { handled?: boolean; prompt?: string } | void;
  onEvent?: (message: string) => void;
  onError?: (message: string) => void;
}

export interface QwenRealtimeStartOptions {
  videoElement: HTMLVideoElement;
  wsUrl?: string;
  systemPrompt?: string;
  autoQueryTemplate?: string;
  frameIntervalMs?: number;
  numFrames?: number;
  maxFrames?: number;
  enableLocalVideo?: boolean;
  robotSnapshotUrl?: string;
  localVideoLabel?: string;
  robotVideoLabel?: string;
}

const INPUT_SAMPLE_RATE = 16000;
const AUDIO_CHUNK_MS = 200;
const AUDIO_CHUNK_SAMPLES = INPUT_SAMPLE_RATE * (AUDIO_CHUNK_MS / 1000);
const VAD_START_PEAK = 0.035;
const VAD_END_MS = 900;
const BARGE_IN_FRAMES = 2;

const DEFAULT_WS_URL = "ws://127.0.0.1:8091/v1/video/chat/stream";
const DEFAULT_SYSTEM_PROMPT =
  "你是部署在桌面端的中文实时多模态助手。请同时参考用户语音和当前摄像头画面，自然回答，优先简洁、直接、口语化。";
const DEFAULT_AUTO_QUERY =
  "请结合刚刚的语音内容和当前连续画面，用中文直接回答；默认 30 到 80 字，必要时先描述你看到的关键画面。";

const concatFloat32 = (parts: Float32Array[]): Float32Array => {
  const total = parts.reduce((sum, part) => sum + part.length, 0);
  const merged = new Float32Array(total);
  let offset = 0;
  for (const part of parts) {
    merged.set(part, offset);
    offset += part.length;
  }
  return merged;
};

const resampleAudio = (samples: Float32Array, fromRate: number, toRate: number): Float32Array => {
  if (fromRate === toRate) return samples;
  const ratio = fromRate / toRate;
  const nextLength = Math.round(samples.length / ratio);
  const result = new Float32Array(nextLength);
  for (let index = 0; index < nextLength; index += 1) {
    const srcIndex = index * ratio;
    const lower = Math.floor(srcIndex);
    const frac = srcIndex - lower;
    const upper = Math.min(lower + 1, samples.length - 1);
    result[index] = samples[lower] * (1 - frac) + samples[upper] * frac;
  }
  return result;
};

const float32ToPcm16 = (samples: Float32Array): ArrayBuffer => {
  const buffer = new ArrayBuffer(samples.length * 2);
  const view = new DataView(buffer);
  for (let index = 0; index < samples.length; index += 1) {
    const clamped = Math.max(-1, Math.min(1, samples[index]));
    view.setInt16(index * 2, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
  }
  return buffer;
};

const arrayBufferToBase64 = (buffer: ArrayBufferLike): string => {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunkSize = 0x8000;
  for (let index = 0; index < bytes.length; index += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize));
  }
  return btoa(binary);
};

const base64ToArrayBuffer = (value: string): ArrayBuffer => {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes.buffer;
};

const stripDataUrlPrefix = (value: string): string => value.replace(/^data:[^;]+;base64,/, "");

export class QwenRealtimeVideoService {
  private callbacks: QwenRealtimeCallbacks;
  private state: QwenRealtimeState = "idle";
  private ws: WebSocket | null = null;
  private currentOptions: QwenRealtimeStartOptions | null = null;
  private videoElement: HTMLVideoElement | null = null;
  private captureStream: MediaStream | null = null;
  private inputCtx: AudioContext | null = null;
  private outputCtx: AudioContext | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private processor: ScriptProcessorNode | null = null;
  private frameTimer: number | null = null;
  private frameCanvas: HTMLCanvasElement | null = null;
  private robotImage: HTMLImageElement | null = null;
  private robotImageDirty = false;
  private chunkBuffer: Float32Array[] = [];
  private heardSpeechThisTurn = false;
  private lastSpeechAt = 0;
  private speechFrames = 0;
  private audioDirtySinceQuery = false;
  private responseInProgress = false;
  private ignoreCurrentResponse = false;
  private currentAssistantText = "";
  private currentUserTranscript = "";
  private activeSources = new Set<AudioBufferSourceNode>();
  private playbackCursor = 0;
  private isStopping = false;
  private reconnecting = false;

  constructor(callbacks: QwenRealtimeCallbacks = {}) {
    this.callbacks = callbacks;
  }

  get running() {
    return this.state !== "idle" && this.state !== "error";
  }

  async start(options: QwenRealtimeStartOptions) {
    await this.stop();
    this.currentOptions = options;
    this.videoElement = options.videoElement;
    this.emitState("connecting", "连接实时视频语音会话");
    await this.ensureMedia();
    await this.ensureOutputContext();
    await this.connectSocket();
    this.startFrameLoop();
  }

  async stop() {
    this.isStopping = true;
    this.stopPlayback();
    this.chunkBuffer = [];
    this.heardSpeechThisTurn = false;
    this.audioDirtySinceQuery = false;
    this.responseInProgress = false;
    this.ignoreCurrentResponse = false;
    this.currentAssistantText = "";
    this.currentUserTranscript = "";
    this.speechFrames = 0;
    this.playbackCursor = 0;

    if (this.frameTimer != null) {
      window.clearInterval(this.frameTimer);
      this.frameTimer = null;
    }
    if (this.processor) {
      this.processor.disconnect();
      this.processor.onaudioprocess = null;
      this.processor = null;
    }
    if (this.source) {
      this.source.disconnect();
      this.source = null;
    }
    if (this.inputCtx) {
      await this.inputCtx.close().catch(() => undefined);
      this.inputCtx = null;
    }
    if (this.outputCtx) {
      await this.outputCtx.close().catch(() => undefined);
      this.outputCtx = null;
    }
    if (this.captureStream) {
      this.captureStream.getTracks().forEach((track) => track.stop());
      this.captureStream = null;
    }
    if (this.videoElement) {
      this.videoElement.srcObject = null;
    }
    if (this.ws) {
      try {
        this.ws.send(JSON.stringify({ type: "video.done" }));
      } catch {
        // ignore
      }
      try {
        this.ws.close();
      } catch {
        // ignore
      }
      this.ws = null;
    }
    this.frameCanvas = null;
    this.robotImage = null;
    this.robotImageDirty = false;
    this.reconnecting = false;
    this.isStopping = false;
    this.emitState("idle", "实时会话已停止");
  }

  async request(prompt: string) {
    const text = String(prompt || "").trim();
    if (!text) return;
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error("realtime_socket_not_ready");
    }
    this.callbacks.onTurnCommitted?.("manual", text);
    this.responseInProgress = true;
    this.ignoreCurrentResponse = false;
    this.currentAssistantText = "";
    this.currentUserTranscript = "";
    this.emitState("thinking", "正在结合当前画面与语音思考");
    this.ws.send(JSON.stringify({ type: "video.query", text }));
  }

  private emitState(state: QwenRealtimeState, detail = "") {
    this.state = state;
    this.callbacks.onStateChange?.(state, detail);
  }

  private emitEvent(message: string) {
    this.callbacks.onEvent?.(message);
  }

  private emitError(message: string) {
    this.emitState("error", message);
    this.callbacks.onError?.(message);
  }

  private async ensureMedia() {
    if (!this.videoElement) throw new Error("missing_video_element");
    this.captureStream = await navigator.mediaDevices.getUserMedia({
      video: {
        width: { ideal: 1280 },
        height: { ideal: 720 },
        facingMode: "user",
      },
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    this.videoElement.srcObject = this.captureStream;
    this.videoElement.muted = true;
    this.videoElement.playsInline = true;
    await this.videoElement.play();

    this.inputCtx = new AudioContext();
    this.source = this.inputCtx.createMediaStreamSource(this.captureStream);
    this.processor = this.inputCtx.createScriptProcessor(4096, 1, 1);
    this.source.connect(this.processor);
    this.processor.connect(this.inputCtx.destination);
    this.processor.onaudioprocess = (event) => this.handleAudioProcess(event.inputBuffer.getChannelData(0));
  }

  private async ensureOutputContext() {
    if (this.outputCtx) return;
    this.outputCtx = new AudioContext();
    if (this.outputCtx.state === "suspended") {
      await this.outputCtx.resume().catch(() => undefined);
    }
  }

  private buildSessionConfig() {
    const systemPrompt = this.currentOptions?.systemPrompt?.trim() || DEFAULT_SYSTEM_PROMPT;
    return {
      type: "session.config",
      modalities: ["text", "audio"],
      system_prompt: systemPrompt,
      max_frames: this.currentOptions?.maxFrames ?? 32,
      num_frames: this.currentOptions?.numFrames ?? 12,
      use_audio_in_video: true,
      enable_frame_filter: true,
    };
  }

  private async connectSocket() {
    const wsUrl = this.currentOptions?.wsUrl?.trim() || DEFAULT_WS_URL;
    await new Promise<void>((resolve, reject) => {
      const ws = new WebSocket(wsUrl);
      this.ws = ws;
      ws.onopen = () => {
        ws.send(JSON.stringify(this.buildSessionConfig()));
        this.emitState("listening", "实时视频语音已连接");
        this.emitEvent(`connected:${wsUrl}`);
        resolve();
      };
      ws.onmessage = (event) => this.handleSocketMessage(event.data);
      ws.onerror = () => {
        reject(new Error("realtime_socket_open_failed"));
      };
      ws.onclose = () => {
        const expected = this.isStopping || this.reconnecting;
        this.ws = null;
        if (!expected) {
          this.emitError("实时会话已断开");
        }
      };
    });
  }

  private async reconnectSocket() {
    if (this.reconnecting || this.isStopping) return;
    this.reconnecting = true;
    this.ignoreCurrentResponse = true;
    this.responseInProgress = false;
    this.stopPlayback();
    this.emitState("interrupted", "检测到插话，正在重建会话");
    try {
      if (this.ws) {
        try {
          this.ws.close();
        } catch {
          // ignore
        }
      }
      await this.connectSocket();
    } finally {
      this.reconnecting = false;
    }
  }

  private startFrameLoop() {
    if (!this.videoElement) return;
    if (!this.frameCanvas) {
      this.frameCanvas = document.createElement("canvas");
    }
    const interval = this.currentOptions?.frameIntervalMs ?? 800;
    const sendFrame = () => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN || !this.videoElement || !this.frameCanvas) return;
      this.refreshRobotSnapshot();
      const localWidth = this.currentOptions?.enableLocalVideo === false ? 0 : this.videoElement.videoWidth || 640;
      const localHeight = this.currentOptions?.enableLocalVideo === false ? 0 : this.videoElement.videoHeight || 360;
      const baseHeight = Math.max(localHeight || 360, this.robotImage?.naturalHeight || 360, 360);
      const localPaneWidth = localWidth ? Math.round((localWidth / Math.max(localHeight, 1)) * baseHeight) : 0;
      const robotPaneWidth = this.robotImage?.naturalWidth
        ? Math.round((this.robotImage.naturalWidth / Math.max(this.robotImage.naturalHeight, 1)) * baseHeight)
        : localPaneWidth || 640;
      const totalWidth = localPaneWidth && this.currentOptions?.robotSnapshotUrl ? localPaneWidth + robotPaneWidth : Math.max(localPaneWidth, robotPaneWidth);
      const width = Math.max(totalWidth, 640);
      const height = Math.max(baseHeight, 360);
      this.frameCanvas.width = width;
      this.frameCanvas.height = height;
      const ctx = this.frameCanvas.getContext("2d");
      if (!ctx) return;
      ctx.fillStyle = "#04070d";
      ctx.fillRect(0, 0, width, height);
      const useRobot = Boolean(this.currentOptions?.robotSnapshotUrl);
      if (localPaneWidth > 0) {
        const targetWidth = useRobot ? localPaneWidth : width;
        ctx.drawImage(this.videoElement, 0, 0, targetWidth, height);
        this.drawVideoLabel(ctx, this.currentOptions?.localVideoLabel || "Laptop Camera", 0, 0, targetWidth, height);
      }
      if (useRobot) {
        const robotX = localPaneWidth || 0;
        if (this.robotImage && this.robotImage.complete && this.robotImage.naturalWidth > 0) {
          ctx.drawImage(this.robotImage, robotX, 0, robotPaneWidth, height);
          this.robotImageDirty = false;
        } else {
          ctx.fillStyle = "#111827";
          ctx.fillRect(robotX, 0, robotPaneWidth, height);
          ctx.fillStyle = "#cbd5e1";
          ctx.font = "24px sans-serif";
          ctx.fillText("Robot camera loading...", robotX + 24, 44);
        }
        this.drawVideoLabel(
          ctx,
          this.currentOptions?.robotVideoLabel || "Robot Camera",
          robotX,
          0,
          robotPaneWidth,
          height,
        );
      }
      const dataUrl = this.frameCanvas.toDataURL("image/jpeg", 0.75);
      const base64 = stripDataUrlPrefix(dataUrl);
      this.ws.send(JSON.stringify({ type: "video.frame", data: base64 }));
    };
    sendFrame();
    this.frameTimer = window.setInterval(sendFrame, interval);
  }

  private refreshRobotSnapshot() {
    const baseUrl = String(this.currentOptions?.robotSnapshotUrl || "").trim();
    if (!baseUrl || this.robotImageDirty) return;
    const nextUrl = `${baseUrl}${baseUrl.includes("?") ? "&" : "?"}t=${Date.now()}`;
    if (!this.robotImage) {
      this.robotImage = new Image();
    }
    this.robotImageDirty = true;
    this.robotImage.onload = () => {
      this.robotImageDirty = false;
    };
    this.robotImage.onerror = () => {
      this.robotImageDirty = false;
    };
    this.robotImage.src = nextUrl;
  }

  private drawVideoLabel(
    ctx: CanvasRenderingContext2D,
    text: string,
    x: number,
    y: number,
    width: number,
    _height: number,
  ) {
    ctx.fillStyle = "rgba(3, 7, 18, 0.72)";
    ctx.fillRect(x + 12, y + 12, Math.max(140, Math.min(width - 24, 230)), 34);
    ctx.fillStyle = "#f8fafc";
    ctx.font = "bold 18px sans-serif";
    ctx.fillText(text, x + 24, y + 35);
  }

  private handleAudioProcess(inputSamples: Float32Array) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN || !this.inputCtx) return;
    const copied = new Float32Array(inputSamples.length);
    copied.set(inputSamples);
    const peak = copied.reduce((max, value) => Math.max(max, Math.abs(value)), 0);
    this.callbacks.onVoiceLevel?.(Math.min(1, peak / 0.14));
    const now = Date.now();

    if (peak >= VAD_START_PEAK) {
      this.heardSpeechThisTurn = true;
      this.lastSpeechAt = now;
      this.speechFrames += 1;
      if (this.state !== "speaking") {
        this.emitState("user-speaking", "正在听你说话");
      }
      if (this.responseInProgress && this.speechFrames >= BARGE_IN_FRAMES) {
        void this.reconnectSocket();
      }
    } else if (this.speechFrames > 0) {
      this.speechFrames = 0;
    }

    const resampled = resampleAudio(copied, this.inputCtx.sampleRate, INPUT_SAMPLE_RATE);
    this.chunkBuffer.push(resampled);
    const merged = concatFloat32(this.chunkBuffer);
    if (merged.length >= AUDIO_CHUNK_SAMPLES) {
      const sendChunk = merged.slice(0, AUDIO_CHUNK_SAMPLES);
      const remain = merged.slice(AUDIO_CHUNK_SAMPLES);
      this.chunkBuffer = remain.length ? [remain] : [];
      this.audioDirtySinceQuery = true;
      const pcmBuffer = float32ToPcm16(sendChunk);
      this.ws.send(
        JSON.stringify({
          type: "audio.chunk",
          data: arrayBufferToBase64(pcmBuffer),
        })
      );
    }

    if (
      this.heardSpeechThisTurn &&
      !this.responseInProgress &&
      now - this.lastSpeechAt > VAD_END_MS &&
      this.audioDirtySinceQuery
    ) {
      this.heardSpeechThisTurn = false;
      this.audioDirtySinceQuery = false;
      void this.finalizeVoiceTurn();
    }
  }

  private async finalizeVoiceTurn() {
    const defaultPrompt = this.currentOptions?.autoQueryTemplate?.trim() || DEFAULT_AUTO_QUERY;
    const transcript = this.currentUserTranscript.trim();
    const decision =
      (await this.callbacks.onVoiceTurnReady?.({
        transcript,
        defaultPrompt,
      })) || {};
    const prompt = String(decision.prompt || defaultPrompt).trim() || defaultPrompt;
    if (decision.handled && !decision.prompt) {
      this.currentUserTranscript = "";
      return;
    }
    this.callbacks.onTurnCommitted?.("voice", prompt);
    this.responseInProgress = true;
    this.ignoreCurrentResponse = false;
    this.currentAssistantText = "";
    this.emitState("thinking", "正在根据语音和画面生成回答");
    this.ws?.send(JSON.stringify({ type: "video.query", text: prompt }));
    this.currentUserTranscript = "";
  }

  private extractEventText(event: Record<string, unknown>): string {
    const direct = [event.text, event.delta, event.transcript, event.content];
    for (const value of direct) {
      if (typeof value === "string" && value.trim()) return value.trim();
    }
    const item = event.item;
    if (item && typeof item === "object") {
      const text = this.extractEventText(item as Record<string, unknown>);
      if (text) return text;
    }
    return "";
  }

  private handleSocketMessage(data: string) {
    try {
      const event = JSON.parse(String(data || "{}"));
      const type = String(event.type || "");
      switch (type) {
        case "transcription.text.delta":
        case "transcription.delta":
        case "input_audio_transcription.delta":
        case "conversation.item.input_audio_transcription.delta": {
          const delta = this.extractEventText(event);
          if (!delta) return;
          this.currentUserTranscript += delta;
          this.callbacks.onUserTranscriptDelta?.(this.currentUserTranscript);
          return;
        }
        case "transcription.text.done":
        case "transcription.completed":
        case "input_audio_transcription.completed":
        case "conversation.item.input_audio_transcription.completed": {
          const finalText = this.extractEventText(event) || this.currentUserTranscript;
          this.currentUserTranscript = String(finalText || "").trim();
          if (this.currentUserTranscript) {
            this.callbacks.onUserTranscriptFinal?.(this.currentUserTranscript);
          }
          return;
        }
        case "response.text.delta": {
          if (this.ignoreCurrentResponse) return;
          this.currentAssistantText += String(event.text || "");
          this.callbacks.onAssistantTextDelta?.(this.currentAssistantText);
          return;
        }
        case "response.text.done": {
          if (this.ignoreCurrentResponse) return;
          const finalText = String(event.text || this.currentAssistantText || "").trim();
          if (finalText) {
            this.callbacks.onAssistantTextFinal?.(finalText);
          }
          return;
        }
        case "response.audio.delta": {
          if (this.ignoreCurrentResponse) return;
          const audioBase64 = String(event.audio || "");
          if (!audioBase64) return;
          void this.playAudioChunk(audioBase64);
          this.emitState("speaking", "正在语音回复");
          return;
        }
        case "response.audio.done": {
          if (this.ignoreCurrentResponse) {
            this.ignoreCurrentResponse = false;
          }
          this.responseInProgress = false;
          if (this.state !== "user-speaking") {
            this.emitState("listening", "继续监听中");
          }
          return;
        }
        case "response.done": {
          this.responseInProgress = false;
          if (this.state !== "speaking" && this.state !== "user-speaking") {
            this.emitState("listening", "继续监听中");
          }
          return;
        }
        case "error": {
          this.emitError(String(event.message || "unknown_realtime_error"));
          return;
        }
        default: {
          this.emitEvent(type || "unknown_event");
        }
      }
    } catch (error) {
      this.emitEvent(`unparsed_message:${String(error)}`);
    }
  }

  private async playAudioChunk(audioBase64: string) {
    if (!this.outputCtx) return;
    const audioBuffer = await this.outputCtx.decodeAudioData(base64ToArrayBuffer(audioBase64).slice(0));
    const source = this.outputCtx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(this.outputCtx.destination);
    const startAt = Math.max(this.outputCtx.currentTime + 0.01, this.playbackCursor);
    this.playbackCursor = startAt + audioBuffer.duration;
    source.onended = () => {
      this.activeSources.delete(source);
      if (!this.activeSources.size && !this.responseInProgress && this.state === "speaking") {
        this.emitState("listening", "继续监听中");
      }
    };
    this.activeSources.add(source);
    source.start(startAt);
  }

  private stopPlayback() {
    for (const source of this.activeSources) {
      try {
        source.stop(0);
      } catch {
        // ignore
      }
    }
    this.activeSources.clear();
    this.playbackCursor = this.outputCtx?.currentTime || 0;
  }
}
