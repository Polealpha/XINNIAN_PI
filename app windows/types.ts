export enum EmotionType {
  HAPPY = "HAPPY",
  SAD = "SAD",
  ANGRY = "ANGRY",
  CALM = "CALM",
  TIRED = "TIRED",
  ANXIOUS = "ANXIOUS",
}

export type EngineMode = "normal" | "privacy" | "dnd";
export type CareDeliveryStrategy = "policy" | "voice_all_day" | "popup_all_day";
export type AssistantMode = "product" | "agent";

export interface RiskScores {
  V: number;
  A: number;
  T: number;
  S: number;
}

export interface RiskDetail {
  V_sub?: Record<string, any>;
  A_sub?: Record<string, any>;
  T_sub?: Record<string, any>;
}

export interface CarePlan {
  text: string;
  style: "warm" | "neutral" | "cheerful" | "serious";
  motion?: { type: string; intensity: number; duration_ms: number };
  emo?: { type: string; level: number };
  followup_question?: string;
}

export interface SystemEvent {
  id: string;
  timestamp: Date;
  type: string;
  payload: Record<string, any>;
}

export interface EmotionEvent {
  id: string;
  timestamp: Date;
  type: EmotionType;
  scores: RiskScores;
  description: string;
  intensity?: number;
  source?: string;
  carePlan?: CarePlan;
  transcript?: string;
}

export interface DeviceStatus {
  device_id: string;
  device_ip?: string;
  device_mac?: string;
  online: boolean;
  last_seen_ms?: number;
  ssid?: string;
  desired_ssid?: string;
  network_mismatch?: boolean;
  missing_profile?: boolean;
  last_switch_reason?: string;
  status?: {
    ip?: string;
    device_mac?: string;
    ssid?: string;
    rssi?: number;
    camera_ready?: boolean;
  };
  error?: string;
}

export interface DeviceSettings {
  mode: EngineMode;
  care_delivery_strategy: CareDeliveryStrategy;
  assistant: {
    mode: AssistantMode;
    native_control_enabled: boolean;
  };
  media: {
    camera_enabled: boolean;
    audio_enabled: boolean;
  };
  wake: {
    enabled: boolean;
    wake_phrase: string;
    ack_text: string;
  };
  behavior: {
    cooldown_min: number;
    daily_trigger_limit: number;
    settings_auto_return_sec: number;
  };
  tracking: {
    pan_enabled: boolean;
    tilt_enabled: boolean;
  };
  voice: {
    desktop_stt_provider: string;
    desktop_stt_model: string;
    robot_tts_provider: string;
    robot_voice_style: string;
  };
}

export interface DeviceUiState {
  page: "expression" | "settings" | string;
  screen_awake: boolean;
  source?: string;
  opened_at_ms?: number | null;
  last_closed_at_ms?: number | null;
}

export interface FaceTrackState {
  found: boolean;
  bbox: [number, number, number, number] | null;
  frame_w: number;
  frame_h: number;
  ex: number;
  ex_smooth: number;
  turn: number | null;
  lost: number;
  sent: boolean;
  mode: string;
  scene: string;
  ts_ms: number;
}

export interface FaceTrackEngineState {
  enabled: boolean;
  detector_ready: boolean;
  detector: string;
  ts_ms?: number;
}

export interface WakeEngineState {
  enabled: boolean;
  model?: string;
  error?: string;
  last_wake_ms?: number;
}

export interface ChatAttachment {
  kind: "image" | "video";
  url: string;
  mime?: string;
  name?: string;
  size?: number;
  image_data_url?: string;
}

export interface ChatMessage {
  id: string;
  sender: "user" | "bot";
  text: string;
  timestamp: Date;
  contentType?: "text" | "image" | "video" | "mixed" | "system";
  attachments?: ChatAttachment[];
  isActiveCare?: boolean;
}

export interface UserProfile {
  id: number;
  username: string;
  display_name: string;
  avatar_url?: string | null;
  bio?: string | null;
  location?: string | null;
  created_at?: number;
  updated_at?: number | null;
}
