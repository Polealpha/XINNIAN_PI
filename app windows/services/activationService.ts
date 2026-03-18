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
  raw_json: Record<string, unknown>;
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

export const inferActivationIdentity = async (payload: {
  transcript: string;
  surface?: string;
  observed_name?: string;
  context?: Record<string, unknown>;
}): Promise<ActivationIdentityInference> => {
  return apiPost("/api/activation/identity/infer", payload, true);
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
