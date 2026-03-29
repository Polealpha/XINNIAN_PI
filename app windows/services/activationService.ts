import { apiGet, apiPost } from "./apiClient";

export interface ActivationIdentityInference {
  ok: boolean;
  preferred_name: string;
  role_label: string;
  relation_to_robot: string;
  pronouns: string;
  identity_summary: string;
  onboarding_notes: string;
  voice_intro_summary: string;
  confidence: number;
  inference_source: string;
  inference_detail: string;
  raw_json: Record<string, unknown>;
}

export interface ActivationRuntimeStatus {
  ok: boolean;
  ai_ready: boolean;
  ai_detail: string;
  gateway_ready: boolean;
  provider_network_ok: boolean;
  blocking_reason: string;
  text_assessment_ready: boolean;
  desktop_voice_ready: boolean;
  desktop_voice_detail: string;
  device_online: boolean;
  robot_voice_ready: boolean;
  preferred_device_id: string;
}

export interface PersonalityProfile {
  ok: boolean;
  exists?: boolean;
  summary: string;
  response_style: string;
  care_style: string;
  traits: string[];
  topics: string[];
  boundaries: string[];
  signals: string[];
  confidence: number;
  sample_count: number;
  inference_version: string;
  updated_at_ms?: number | null;
  raw_json?: Record<string, unknown>;
}

export interface ActivationDialogueTurn {
  role: "assistant" | "user";
  text: string;
  timestamp_ms?: number | null;
}

export interface ActivationAssessmentState {
  ok: boolean;
  exists: boolean;
  status: string;
  started_at_ms?: number | null;
  updated_at_ms?: number | null;
  completed_at_ms?: number | null;
  turn_count: number;
  effective_turn_count: number;
  conversation_count: number;
  latest_question: string;
  latest_transcript: string;
  last_question_id: string;
  finish_reason: string;
  voice_mode: string;
  voice_session_active: boolean;
  device_online: boolean;
  summary: string;
  interaction_preferences: string[];
  decision_style: string;
  stress_response: string;
  comfort_preferences: string[];
  avoid_patterns: string[];
  care_guidance: string;
  confidence: number;
  inference_version: string;
  required_min_turns: number;
  max_turns: number;
  question_source: string;
  scoring_source: string;
  question_pair: string;
  current_focus: string;
  mode_hint: string;
  can_submit_text: boolean;
  assessment_ready: boolean;
  ai_required: boolean;
  blocking_reason: string;
  dialogue_turns: ActivationDialogueTurn[];
}

export interface ActivationAssessmentTurnResponse extends ActivationAssessmentState {
  question_changed: boolean;
  just_completed: boolean;
}

export interface ActivationAssessmentVoicePollResponse {
  ok: boolean;
  device_online: boolean;
  transcript: string;
  transcript_processed: boolean;
  prompt_spoken: boolean;
  detail: string;
  state: ActivationAssessmentState;
}

export interface OwnerBindingStatus {
  ok: boolean;
  device_id: string;
  enrolled: boolean;
  owner_label?: string | null;
  embedding_version?: string | null;
  recognition_enabled: boolean;
  last_sync_ms?: number | null;
  enrolled_at_ms?: number | null;
}

export const inferActivationIdentity = async (payload: {
  transcript: string;
  surface?: string;
  observed_name?: string;
  context?: Record<string, unknown>;
}): Promise<ActivationIdentityInference> => {
  return apiPost("/api/activation/identity/infer", payload, true);
};

export const getActivationRuntimeStatus = async (): Promise<ActivationRuntimeStatus> => {
  return apiGet("/api/activation/runtime/status", true);
};

export const completeActivation = async (payload: {
  preferred_name: string;
  role_label: string;
  relation_to_robot: string;
  pronouns?: string;
  identity_summary?: string;
  onboarding_notes?: string;
  voice_intro_summary?: string;
  profile?: Record<string, unknown>;
  activation_version?: string;
}) => {
  return apiPost("/api/activation/complete", payload, true);
};

export const getPersonalityState = async (): Promise<PersonalityProfile> => {
  return apiGet("/api/activation/personality/state", true);
};

export const inferPersonalityProfile = async (payload: {
  transcript?: string;
  answers?: string[];
  surface?: string;
  context?: Record<string, unknown>;
}): Promise<PersonalityProfile> => {
  return apiPost("/api/activation/personality/infer", payload, true);
};

export const completePersonalityProfile = async (payload: {
  summary: string;
  response_style: string;
  care_style: string;
  traits: string[];
  topics: string[];
  boundaries: string[];
  signals: string[];
  confidence: number;
  sample_count: number;
  inference_version?: string;
  profile?: Record<string, unknown>;
}): Promise<PersonalityProfile> => {
  return apiPost("/api/activation/personality/complete", payload, true);
};

export const startAssessment = async (payload?: {
  surface?: string;
  voice_mode?: string;
  reset?: boolean;
  device_id?: string;
}): Promise<ActivationAssessmentState> => {
  return apiPost(
    "/api/activation/assessment/start",
    {
      surface: payload?.surface || "desktop",
      voice_mode: payload?.voice_mode || "text",
      reset: Boolean(payload?.reset),
      device_id: payload?.device_id,
    },
    true
  );
};

export const getAssessmentState = async (): Promise<ActivationAssessmentState> => {
  return apiGet("/api/activation/assessment/state", true);
};

export const submitAssessmentTurn = async (payload: {
  answer: string;
  transcript?: string;
  surface?: string;
  device_id?: string;
  voice_mode?: string;
}): Promise<ActivationAssessmentTurnResponse> => {
  return apiPost(
    "/api/activation/assessment/turn",
    {
      answer: payload.answer,
      transcript: payload.transcript || payload.answer,
      surface: payload.surface || "desktop",
      device_id: payload.device_id,
      voice_mode: payload.voice_mode || "text",
    },
    true
  );
};

export const finishAssessment = async (): Promise<ActivationAssessmentState> => {
  return apiPost("/api/activation/assessment/finish", {}, true);
};

export const startAssessmentVoice = async (deviceId?: string) => {
  return apiPost(
    "/api/activation/assessment/voice/start",
    {
      device_id: deviceId || undefined,
      session_mode: "assessment",
    },
    true
  );
};

export const stopAssessmentVoice = async (deviceId?: string) => {
  return apiPost(
    "/api/activation/assessment/voice/stop",
    {
      device_id: deviceId || undefined,
      session_mode: "assessment",
    },
    true
  );
};

export const pollAssessmentVoice = async (payload?: {
  deviceId?: string;
  windowMs?: number;
  speakQuestion?: boolean;
}): Promise<ActivationAssessmentVoicePollResponse> => {
  return apiPost(
    "/api/activation/assessment/voice/poll",
    {
      device_id: payload?.deviceId || undefined,
      window_ms: payload?.windowMs || 5000,
      speak_question: payload?.speakQuestion ?? true,
    },
    true
  );
};

export const startOwnerEnrollment = async (deviceId?: string) => {
  return apiPost(
    "/api/device/owner/enrollment/start",
    {
      device_id: deviceId || undefined,
      owner_label: "owner",
    },
    true
  );
};

export const getOwnerBindingStatus = async (deviceId: string): Promise<OwnerBindingStatus> => {
  const encoded = encodeURIComponent(deviceId);
  return apiGet(`/api/device/owner/status?device_id=${encoded}`, true);
};
