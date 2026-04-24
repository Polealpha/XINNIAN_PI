import {
  AssistantSessionEvent,
  AssistantSessionStartResponse,
  connectAssistantSessionEvents,
  interruptAssistantSession,
  startAssistantSession,
  streamAssistantSpeech,
  stopAssistantSession,
} from "./assistantService";

export type DuplexRuntimeState =
  | "idle"
  | "connecting"
  | "preparing"
  | "listening"
  | "thinking"
  | "speaking"
  | "interrupted"
  | "error";

export interface MiniCpmDuplexCallbacks {
  onStateChange?: (state: DuplexRuntimeState, detail?: string) => void;
  onUserPartial?: (text: string) => void;
  onUserFinal?: (text: string) => void;
  onAssistantPartial?: (text: string) => void;
  onAssistantFinal?: (text: string) => void;
  onError?: (message: string) => void;
}

type StartOptions = {
  surface?: string;
  sessionKey?: string;
  metadata?: Record<string, unknown>;
};

const INPUT_SAMPLE_RATE = 16000;
const CHUNK_MS = 1000;
const CHUNK_SAMPLES = INPUT_SAMPLE_RATE * (CHUNK_MS / 1000);
const VAD_PEAK = 0.045;
const VAD_RESET_PEAK = 0.02;
const BARGE_IN_FRAMES = 2;
const LISTEN_FINALIZE_IDLE_MS = 1400;
const BARGE_IN_COOLDOWN_MS = 900;
const OFFICIAL_DUPLEX_OWNS_REPLY = true;
const USE_MICROSOFT_EDGE_TTS_OUTPUT = true;
const MICROSOFT_EDGE_TTS_VOICE = "zh-CN-XiaoyiNeural";

const STATE_DETAIL: Record<DuplexRuntimeState, string> = {
  idle: "full duplex stopped",
  connecting: "starting full duplex session",
  preparing: "preparing duplex voice session",
  listening: "listening",
  thinking: "openclaw thinking",
  speaking: "assistant speaking",
  interrupted: "barge-in detected",
  error: "duplex error",
};

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
  for (let i = 0; i < nextLength; i += 1) {
    const srcIndex = i * ratio;
    const lower = Math.floor(srcIndex);
    const frac = srcIndex - lower;
    const upper = Math.min(lower + 1, samples.length - 1);
    result[i] = samples[lower] * (1 - frac) + samples[upper] * frac;
  }
  return result;
};

const arrayBufferToBase64 = (buffer: ArrayBufferLike): string => {
  const bytes = new Uint8Array(buffer);
  const chunks: string[] = [];
  for (let i = 0; i < bytes.length; i += 8192) {
    chunks.push(String.fromCharCode(...bytes.subarray(i, i + 8192)));
  }
  return btoa(chunks.join(""));
};

const base64ToFloat32 = (audioBase64: string): Float32Array => {
  const binary = atob(audioBase64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new Float32Array(bytes.buffer);
};

const pickPreferredZhFemaleVoice = (): SpeechSynthesisVoice | null => {
  if (!("speechSynthesis" in window)) return null;
  const voices = window.speechSynthesis.getVoices();
  if (!voices.length) return null;
  const exactPreferred = [
    /yaoyao/i,
    /huihui/i,
    /xiaoyi/i,
    /xiaoxiao/i,
    /zira/i,
  ];
  const femaleHints = /(huihui|yaoyao|xiaoxiao|xiaoyi|xiaobei|xiaoni|female|zira)/i;
  const maleHints = /(kangkang|yunjian|yunxi|yunyang|yunxia|male|david|mark)/i;
  const zhVoices = voices.filter((voice) => /^zh/i.test(String(voice.lang || "")) || /zh[-_]?cn/i.test(String(voice.name || "")) || /zh[-_]?cn/i.test(String(voice.voiceURI || "")));
  for (const pattern of exactPreferred) {
    const hit = zhVoices.find((voice) => pattern.test(String(voice.name || "")) || pattern.test(String(voice.voiceURI || "")));
    if (hit) return hit;
  }
  const preferred = zhVoices.find((voice) => femaleHints.test(String(voice.name || "")) || femaleHints.test(String(voice.voiceURI || "")));
  if (preferred) return preferred;
  const safeZh = zhVoices.find((voice) => !maleHints.test(String(voice.name || "")) && !maleHints.test(String(voice.voiceURI || "")));
  return safeZh || zhVoices[0] || voices[0] || null;
};

export class MiniCpmDuplexService {
  private callbacks: MiniCpmDuplexCallbacks;
  private ws: WebSocket | null = null;
  private sessionEventsWs: WebSocket | null = null;
  private session: AssistantSessionStartResponse | null = null;
  private sessionMetadata: Record<string, unknown> = {};
  private stream: MediaStream | null = null;
  private inputCtx: AudioContext | null = null;
  private outputCtx: AudioContext | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private processor: ScriptProcessorNode | null = null;
  private captureBuffer: Float32Array[] = [];
  private activeSources = new Set<AudioBufferSourceNode>();
  private userText = "";
  private assistantText = "";
  private state: DuplexRuntimeState = "idle";
  private userSpeakingFrames = 0;
  private openClawPending = false;
  private lastForwardedUserText = "";
  private lastCommittedAssistantText = "";
  private lastCommittedUserText = "";
  private isStopping = false;
  private forceListenChunks = 0;
  private playbackCursor = 0;
  private assistantResultSeenForTurn = false;
  private listenFinalizeTimer: number | null = null;
  private ttsSequence = 0;
  private lastInterruptAtMs = 0;
  private cloudTtsAudio: HTMLAudioElement | null = null;
  private cloudTtsMediaSource: MediaSource | null = null;
  private cloudTtsSourceBuffer: SourceBuffer | null = null;
  private cloudTtsObjectUrl: string | null = null;
  private cloudTtsAbortController: AbortController | null = null;
  private cloudTtsChunkQueue: Uint8Array[] = [];
  private cloudTtsDrainPending = false;

  constructor(callbacks: MiniCpmDuplexCallbacks = {}) {
    this.callbacks = callbacks;
  }

  get running() {
    return this.state !== "idle" && this.state !== "error";
  }

  private emitState(state: DuplexRuntimeState, detail = "") {
    this.state = state;
    console.info("[duplex-state]", state, detail || STATE_DETAIL[state]);
    this.callbacks.onStateChange?.(state, detail || STATE_DETAIL[state]);
  }

  private emitError(message: string) {
    this.emitState("error", message);
    this.callbacks.onError?.(message);
  }

  async start(options: StartOptions = {}) {
    await this.stop();
    this.sessionMetadata = { ...(options.metadata || {}) };
    this.emitState("connecting");
    this.session = await startAssistantSession({
      surface: options.surface || "desktop",
      session_key: options.sessionKey,
      metadata: options.metadata,
    });
    this.connectSessionEvents(this.session.session_key);
    await this.connectWs(this.session.ws_url, this.session.prepare_payload || {});
    await this.startCapture();
  }

  async stop() {
    this.isStopping = true;
    this.userSpeakingFrames = 0;
    this.openClawPending = false;
    this.captureBuffer = [];
    this.lastForwardedUserText = "";
    this.lastCommittedAssistantText = "";
    this.lastCommittedUserText = "";
    this.assistantText = "";
    this.userText = "";
    this.assistantResultSeenForTurn = false;
    this.forceListenChunks = 0;
    this.lastInterruptAtMs = 0;
    this.clearListenFinalizeTimer();
    this.cancelFallbackSpeech();
    this.stopPlayback();

    if (this.processor) {
      this.processor.disconnect();
      this.processor.onaudioprocess = null;
      this.processor = null;
    }
    if (this.source) {
      this.source.disconnect();
      this.source = null;
    }
    if (this.stream) {
      this.stream.getTracks().forEach((track) => track.stop());
      this.stream = null;
    }
    if (this.inputCtx) {
      await this.inputCtx.close().catch(() => undefined);
      this.inputCtx = null;
    }
    if (this.outputCtx) {
      await this.outputCtx.close().catch(() => undefined);
      this.outputCtx = null;
      this.playbackCursor = 0;
    }
    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        // ignore
      }
      this.ws = null;
    }
    if (this.sessionEventsWs) {
      try {
        this.sessionEventsWs.close();
      } catch {
        // ignore
      }
      this.sessionEventsWs = null;
    }
    if (this.session?.session_key) {
      await stopAssistantSession({
        surface: this.session.surface,
        session_key: this.session.session_key,
      }).catch(() => undefined);
    }
    this.session = null;
    this.sessionMetadata = {};
    this.emitState("idle");
    this.isStopping = false;
  }

  async interrupt(reason = "barge_in") {
    const now = Date.now();
    if (now - this.lastInterruptAtMs < BARGE_IN_COOLDOWN_MS) {
      return;
    }
    this.lastInterruptAtMs = now;
    this.forceListenChunks = 3;
    this.clearListenFinalizeTimer();
    this.cancelFallbackSpeech();
    this.stopPlayback();
    if (this.session?.session_key) {
      await interruptAssistantSession({
        surface: this.session.surface,
        session_key: this.session.session_key,
        reason,
      }).catch(() => undefined);
    }
    this.emitState("interrupted");
  }

  private connectSessionEvents(sessionKey: string) {
    this.sessionEventsWs = connectAssistantSessionEvents(sessionKey, (event) => this.handleSessionEvent(event));
  }

  private clearListenFinalizeTimer() {
    if (this.listenFinalizeTimer != null) {
      window.clearTimeout(this.listenFinalizeTimer);
      this.listenFinalizeTimer = null;
    }
  }

  private commitUserTurn(finalText: string) {
    const trimmed = String(finalText || "").trim();
    if (!trimmed) return;
    console.info("[duplex-user-final]", trimmed);
    this.clearListenFinalizeTimer();
    this.lastCommittedUserText = trimmed;
    this.callbacks.onUserFinal?.(trimmed);
    if (!OFFICIAL_DUPLEX_OWNS_REPLY) {
      void this.forwardUserTurn(trimmed);
    }
    this.userText = "";
  }

  private scheduleListenFinalize() {
    this.clearListenFinalizeTimer();
    if (!this.userText.trim()) return;
    this.listenFinalizeTimer = window.setTimeout(() => {
      this.listenFinalizeTimer = null;
      const finalText = this.userText.trim();
      if (!finalText || finalText === this.lastForwardedUserText) return;
      this.commitUserTurn(finalText);
    }, LISTEN_FINALIZE_IDLE_MS);
  }

  private handleSessionEvent(event: AssistantSessionEvent) {
    const payload = event?.payload || {};
    const text = String(payload.text || "").trim();
    switch (event.type) {
      case "AssistantSessionThinking":
        this.openClawPending = true;
        this.emitState("thinking");
        break;
      case "AssistantSessionInterrupted":
        this.clearListenFinalizeTimer();
        this.cancelFallbackSpeech();
        this.stopPlayback();
        this.emitState("interrupted");
        break;
      case "AssistantSessionStopped":
        if (!this.isStopping) {
          this.clearListenFinalizeTimer();
          this.cancelFallbackSpeech();
          this.stopPlayback();
          this.emitState("idle");
        }
        break;
      case "AssistantSessionAssistantTurn":
        this.openClawPending = false;
        if (text && !this.assistantResultSeenForTurn && text !== this.lastCommittedAssistantText) {
          this.lastCommittedAssistantText = text;
          this.callbacks.onAssistantPartial?.(text);
          this.callbacks.onAssistantFinal?.(text);
          if (USE_MICROSOFT_EDGE_TTS_OUTPUT) {
            void this.speakFallbackText(text);
            break;
          }
        }
        if (this.state !== "speaking") {
          this.emitState("listening", "waiting for next user turn");
        }
        break;
      case "AssistantSessionUserTurn":
        if (text && text !== this.lastCommittedUserText) {
          this.lastCommittedUserText = text;
          this.callbacks.onUserFinal?.(text);
        }
        break;
      default:
        break;
    }
  }

  private async connectWs(wsUrl: string, preparePayload: Record<string, unknown>) {
    await new Promise<void>((resolve, reject) => {
      const ws = new WebSocket(wsUrl);
      this.ws = ws;
      let settled = false;

      ws.onopen = () => {
        this.emitState("preparing");
        const systemPrompt = String(preparePayload.prefix_system_prompt || "").trim();
        const payload = { ...preparePayload };
        delete (payload as { prefix_system_prompt?: unknown }).prefix_system_prompt;
        ws.send(
          JSON.stringify({
            type: "prepare",
            system_prompt: systemPrompt,
            ...payload,
          }),
        );
      };

      ws.onerror = () => {
        if (!settled) reject(new Error("duplex_websocket_failed"));
      };

      ws.onclose = () => {
        if (!this.isStopping && this.state !== "error") {
          this.stopPlayback();
          this.emitState("idle", "duplex websocket closed");
        }
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(String(event.data || "{}"));
          if (msg.type === "prepared") {
            settled = true;
            this.emitState("listening");
            resolve();
            return;
          }
          if (msg.type === "interrupted") {
            this.stopPlayback();
            this.emitState("interrupted");
            return;
          }
          if (msg.type === "interrupt_cleared") {
            this.emitState("listening", "interrupt cleared");
            return;
          }
          if (msg.type === "error") {
            const err = new Error(String(msg.error || "duplex_error"));
            if (!settled) {
              reject(err);
            } else {
              this.emitError(err.message);
            }
            return;
          }
          if (msg.type === "result") {
            this.handleResult(msg as Record<string, unknown>);
          }
        } catch (error) {
          if (!settled) reject(error instanceof Error ? error : new Error(String(error)));
        }
      };
    }).catch((error) => {
      this.emitError(error instanceof Error ? error.message : String(error));
      throw error;
    });
  }

  private async startCapture() {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
      video: false,
    });
    this.inputCtx = new AudioContext();
    this.source = this.inputCtx.createMediaStreamSource(this.stream);
    this.processor = this.inputCtx.createScriptProcessor(4096, 1, 1);
    this.processor.onaudioprocess = (event) => {
      const input = event.inputBuffer.getChannelData(0);
      const frame = new Float32Array(input);
      this.handleCaptureFrame(frame, this.inputCtx?.sampleRate || INPUT_SAMPLE_RATE);
    };
    const mute = this.inputCtx.createGain();
    mute.gain.value = 0;
    this.source.connect(this.processor);
    this.processor.connect(mute);
    mute.connect(this.inputCtx.destination);
  }

  private handleCaptureFrame(frame: Float32Array, sampleRate: number) {
    const peak = frame.reduce((max, value) => Math.max(max, Math.abs(value)), 0);
    if (this.state === "speaking" && peak > VAD_PEAK) {
      this.userSpeakingFrames += 1;
      if (this.userSpeakingFrames >= BARGE_IN_FRAMES) {
        this.userSpeakingFrames = 0;
        void this.interrupt("barge_in");
      }
    } else if (peak < VAD_RESET_PEAK) {
      this.userSpeakingFrames = 0;
    }

    const resampled = resampleAudio(frame, sampleRate, INPUT_SAMPLE_RATE);
    this.captureBuffer.push(resampled);
    let merged = concatFloat32(this.captureBuffer);
    while (merged.length >= CHUNK_SAMPLES) {
      const chunk = merged.slice(0, CHUNK_SAMPLES);
      merged = merged.slice(CHUNK_SAMPLES);
      this.sendAudioChunk(chunk);
    }
    this.captureBuffer = merged.length ? [merged] : [];
  }

  private sendAudioChunk(chunk: Float32Array) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    const forceListen = this.forceListenChunks > 0;
    if (forceListen) {
      this.forceListenChunks -= 1;
    }
    this.ws.send(
      JSON.stringify({
        type: "audio_chunk",
        audio_base64: arrayBufferToBase64(chunk.buffer),
        ...(forceListen ? { force_listen: true } : {}),
      }),
    );
  }

  private handleResult(msg: Record<string, unknown>) {
    const text = String(msg.text || "").trim();
    const isListen = Boolean(msg.is_listen);
    const endOfTurn = Boolean(msg.end_of_turn);

    if (isListen) {
      if (text) {
        console.info("[duplex-listen]", text, { endOfTurn });
        this.userText = text;
        this.callbacks.onUserPartial?.(this.userText);
        this.scheduleListenFinalize();
      }
      if (endOfTurn && this.userText) {
        this.commitUserTurn(this.userText);
      }
      if (!this.openClawPending) {
        this.emitState("listening");
      }
      return;
    }

    this.clearListenFinalizeTimer();
    this.assistantResultSeenForTurn = true;
    this.cancelFallbackSpeech();
    this.emitState("speaking");

    const audioData = String(msg.audio_data || "").trim();
    if (audioData && !USE_MICROSOFT_EDGE_TTS_OUTPUT) {
      void this.playAudioChunk(audioData);
    }

    if (text) {
      console.info("[duplex-assistant-result]", text, { endOfTurn });
      this.assistantText += text;
      this.callbacks.onAssistantPartial?.(this.assistantText);
    }

    if (endOfTurn) {
      const finalText = this.assistantText.trim();
      if (finalText) {
        this.lastCommittedAssistantText = finalText;
        this.callbacks.onAssistantFinal?.(finalText);
        if (USE_MICROSOFT_EDGE_TTS_OUTPUT) {
          void this.speakFallbackText(finalText);
          this.assistantText = "";
          return;
        }
      }
      this.assistantText = "";
      if (!this.openClawPending) {
        this.emitState("listening", "waiting for next user turn");
      }
    }
  }

  private async forwardUserTurn(text: string) {
    if (OFFICIAL_DUPLEX_OWNS_REPLY) {
      return;
    }
    if (!this.session?.session_key) return;
    const trimmed = String(text || "").trim();
    if (!trimmed) return;
    if (trimmed === this.lastForwardedUserText && this.openClawPending) return;

    this.lastForwardedUserText = trimmed;
    this.openClawPending = true;
    this.assistantResultSeenForTurn = false;
    this.emitState("thinking");
    console.info("[duplex-forward-user-turn]", trimmed);

    try {
      const response = await sendAssistantMessage({
        text: trimmed,
        surface: this.session.surface,
        session_key: this.session.session_key,
        metadata: {
          transport: "minicpmo_duplex",
          source: "voice",
          ...this.sessionMetadata,
        },
      });
      const reply = String(response.text || "").trim();
      console.info("[duplex-openclaw-reply]", reply);
      if (reply && !this.assistantResultSeenForTurn && reply !== this.lastCommittedAssistantText) {
        this.lastCommittedAssistantText = reply;
        this.callbacks.onAssistantPartial?.(reply);
        this.callbacks.onAssistantFinal?.(reply);
      }
    } catch (error) {
      this.emitError(error instanceof Error ? error.message : String(error));
    } finally {
      this.openClawPending = false;
      if (this.state !== "speaking") {
        this.emitState("listening", "waiting for next user turn");
      }
    }
  }

  private async ensureOutputCtx() {
    if (this.outputCtx && this.outputCtx.state !== "closed") {
      return this.outputCtx;
    }
    const ctx = new AudioContext({ sampleRate: INPUT_SAMPLE_RATE });
    if (ctx.state === "suspended") {
      await ctx.resume().catch(() => undefined);
    }
    this.outputCtx = ctx;
    this.playbackCursor = ctx.currentTime;
    return ctx;
  }

  private cancelFallbackSpeech() {
    this.ttsSequence += 1;
    this.cloudTtsDrainPending = false;
    this.cloudTtsChunkQueue = [];
    if (this.cloudTtsAbortController) {
      this.cloudTtsAbortController.abort();
      this.cloudTtsAbortController = null;
    }
    if (this.cloudTtsAudio) {
      try {
        this.cloudTtsAudio.pause();
        this.cloudTtsAudio.removeAttribute("src");
        this.cloudTtsAudio.load();
      } catch {
        // ignore
      }
      this.cloudTtsAudio = null;
    }
    this.cloudTtsSourceBuffer = null;
    this.cloudTtsMediaSource = null;
    if (this.cloudTtsObjectUrl) {
      try {
        URL.revokeObjectURL(this.cloudTtsObjectUrl);
      } catch {
        // ignore
      }
      this.cloudTtsObjectUrl = null;
    }
    if ("speechSynthesis" in window) {
      try {
        window.speechSynthesis.cancel();
      } catch {
        // ignore
      }
    }
  }

  private flushCloudTtsQueue() {
    const sourceBuffer = this.cloudTtsSourceBuffer;
    const mediaSource = this.cloudTtsMediaSource;
    if (!sourceBuffer || !mediaSource) return;
    if (sourceBuffer.updating) return;
    if (this.cloudTtsChunkQueue.length > 0) {
      const next = this.cloudTtsChunkQueue.shift();
      if (!next) return;
      try {
        sourceBuffer.appendBuffer(next);
      } catch (error) {
        console.warn("[duplex-cloud-tts-append-failed]", error);
        this.emitError("microsoft_tts_append_failed");
      }
      return;
    }
    if (this.cloudTtsDrainPending && mediaSource.readyState === "open") {
      try {
        mediaSource.endOfStream();
      } catch {
        // ignore
      }
    }
  }

  private async playCloudTtsBlob(blob: Blob, seq: number) {
    if (seq !== this.ttsSequence) return;
    const audio = new Audio();
    const objectUrl = URL.createObjectURL(blob);
    this.cloudTtsAudio = audio;
    this.cloudTtsObjectUrl = objectUrl;
    audio.src = objectUrl;
    audio.preload = "auto";
    audio.onended = () => {
      if (seq === this.ttsSequence && !this.openClawPending) {
        this.emitState("listening", "waiting for next user turn");
      }
    };
    await audio.play().catch((error) => {
      console.warn("[duplex-cloud-tts-play-failed]", error);
      throw error;
    });
  }

  private async speakFallbackText(text: string) {
    const trimmed = String(text || "").trim();
    if (!trimmed) return;
    if (!USE_MICROSOFT_EDGE_TTS_OUTPUT) {
      console.warn("[duplex-cloud-tts-disabled]", trimmed);
      return;
    }
    this.cancelFallbackSpeech();
    const seq = ++this.ttsSequence;
    const abortController = new AbortController();
    this.cloudTtsAbortController = abortController;
    try {
      const response = await streamAssistantSpeech({
        text: trimmed,
        voice: MICROSOFT_EDGE_TTS_VOICE,
      }, 2 * 60 * 1000, abortController.signal);
      if (seq !== this.ttsSequence) return;
      const blob = await response.blob();
      if (seq !== this.ttsSequence) return;
      await this.playCloudTtsBlob(blob, seq);
    } catch (error) {
      console.warn("[duplex-cloud-tts-failed]", error);
      if (seq === this.ttsSequence) {
        this.emitError(error instanceof Error ? error.message : "microsoft_tts_failed");
      }
    } finally {
      if (this.cloudTtsAbortController === abortController) {
        this.cloudTtsAbortController = null;
      }
    }
  }

  private stopPlayback() {
    for (const source of Array.from(this.activeSources)) {
      try {
        source.stop();
      } catch {
        // ignore
      }
      try {
        source.disconnect();
      } catch {
        // ignore
      }
    }
    this.activeSources.clear();
    if (this.outputCtx && this.outputCtx.state !== "closed") {
      this.playbackCursor = this.outputCtx.currentTime;
    } else {
      this.playbackCursor = 0;
    }
  }

  private async playAudioChunk(audioBase64: string) {
    try {
      const ctx = await this.ensureOutputCtx();
      const pcm = base64ToFloat32(audioBase64);
      if (!pcm.length) return;
      const buffer = ctx.createBuffer(1, pcm.length, INPUT_SAMPLE_RATE);
      buffer.getChannelData(0).set(pcm);
      const src = ctx.createBufferSource();
      src.buffer = buffer;
      src.connect(ctx.destination);
      this.activeSources.add(src);
      const startAt = Math.max(ctx.currentTime + 0.01, this.playbackCursor);
      src.start(startAt);
      this.playbackCursor = startAt + buffer.duration;
      src.onended = () => {
        this.activeSources.delete(src);
        try {
          src.disconnect();
        } catch {
          // ignore
        }
        if (this.outputCtx && this.playbackCursor < this.outputCtx.currentTime) {
          this.playbackCursor = this.outputCtx.currentTime;
        }
      };
    } catch {
      // ignore single chunk playback failures
    }
  }
}
