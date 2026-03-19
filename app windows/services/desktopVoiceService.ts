import { apiGet, apiPostForm } from "./apiClient";

export interface DesktopVoiceStatus {
  ok: boolean;
  ready: boolean;
  provider_preference: string;
  fallback_provider: string;
  active_provider: string;
  primary_ready: boolean;
  primary_engine: string;
  primary_error?: string | null;
  fallback_ready: boolean;
  fallback_engine: string;
  fallback_error?: string | null;
  language: string;
  max_sec: number;
  model_name: string;
  beam_size: number;
  best_of: number;
  preprocess_enabled: boolean;
  trim_silence_enabled: boolean;
  initial_prompt_enabled: boolean;
  hotwords_enabled: boolean;
}

export interface DesktopVoiceTranscribeResult {
  ok: boolean;
  transcript: string;
  provider: string;
  used_fallback: boolean;
  duration_ms: number;
  latency_ms: number;
  context: string;
  ready: boolean;
}

type RecorderSession = {
  stop: () => Promise<Blob>;
};

const WAV_MIME = "audio/wav";

const mergeBuffers = (buffers: Float32Array[]): Float32Array => {
  const totalLength = buffers.reduce((sum, item) => sum + item.length, 0);
  const merged = new Float32Array(totalLength);
  let offset = 0;
  for (const chunk of buffers) {
    merged.set(chunk, offset);
    offset += chunk.length;
  }
  return merged;
};

const encodeWav = (samples: Float32Array, sampleRate: number): Blob => {
  const bytesPerSample = 2;
  const blockAlign = bytesPerSample;
  const buffer = new ArrayBuffer(44 + samples.length * bytesPerSample);
  const view = new DataView(buffer);

  const writeString = (offset: number, value: string) => {
    for (let i = 0; i < value.length; i += 1) {
      view.setUint8(offset + i, value.charCodeAt(i));
    }
  };

  writeString(0, "RIFF");
  view.setUint32(4, 36 + samples.length * bytesPerSample, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * blockAlign, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, 16, true);
  writeString(36, "data");
  view.setUint32(40, samples.length * bytesPerSample, true);

  let offset = 44;
  for (let i = 0; i < samples.length; i += 1) {
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
    offset += 2;
  }

  return new Blob([buffer], { type: WAV_MIME });
};

const buildRecorderSession = async (): Promise<RecorderSession> => {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
    video: false,
  });
  const audioContext = new AudioContext();
  const source = audioContext.createMediaStreamSource(stream);
  const processor = audioContext.createScriptProcessor(4096, 1, 1);
  const mute = audioContext.createGain();
  mute.gain.value = 0;
  const chunks: Float32Array[] = [];

  processor.onaudioprocess = (event) => {
    const input = event.inputBuffer.getChannelData(0);
    chunks.push(new Float32Array(input));
  };

  source.connect(processor);
  processor.connect(mute);
  mute.connect(audioContext.destination);

  return {
    stop: async () => {
      processor.disconnect();
      source.disconnect();
      mute.disconnect();
      stream.getTracks().forEach((track) => track.stop());
      await audioContext.close();
      const merged = mergeBuffers(chunks);
      return encodeWav(merged, audioContext.sampleRate || 16000);
    },
  };
};

export const getDesktopVoiceStatus = async (): Promise<DesktopVoiceStatus> => {
  return apiGet("/api/desktop/voice/status", true);
};

export const transcribeDesktopAudio = async (audioBlob: Blob, context = "chat"): Promise<DesktopVoiceTranscribeResult> => {
  const form = new FormData();
  form.append("file", audioBlob, `desktop-${Date.now()}.wav`);
  form.append("context", context);
  return apiPostForm("/api/desktop/voice/transcribe", form, true);
};

export const createDesktopVoiceRecorder = async () => {
  const session = await buildRecorderSession();
  return {
    stop: async () => {
      return session.stop();
    },
  };
};
