import { apiGet, apiPost, setAccessToken, setRefreshToken } from "./apiClient";

export interface LoginResult {
  token: string;
  refresh_token: string;
  user_id: number;
  is_configured: boolean;
  activation_required: boolean;
  assessment_required: boolean;
  owner_binding_required: boolean;
  owner_binding_completed: boolean;
  preferred_device_id?: string | null;
  activation_path: string;
}

export interface RegisterResult {
  id: number;
  username: string;
  created_at: number;
}

export const register = async (email: string, password: string): Promise<RegisterResult> => {
  return apiPost("/api/auth/register", { username: email, password }, false);
};

export const login = async (email: string, password: string): Promise<LoginResult> => {
  const response = await apiPost("/api/auth/login", { email, password }, false);
  const result: LoginResult = response;
  setAccessToken(result.token);
  setRefreshToken(result.refresh_token);
  return result;
};

export const validateSession = async (): Promise<void> => {
  await apiGet("/api/auth/me", true);
};

export interface ActivationStateResult {
  ok: boolean;
  is_configured: boolean;
  activation_required: boolean;
  assessment_required: boolean;
  psychometric_completed: boolean;
  owner_binding_required: boolean;
  owner_binding_completed: boolean;
  preferred_device_id?: string | null;
  preferred_name?: string | null;
  role_label?: string | null;
  relation_to_robot?: string | null;
  pronouns?: string | null;
  identity_summary?: string | null;
  onboarding_notes?: string | null;
  voice_intro_summary?: string | null;
  activation_version: string;
  completed_at_ms?: number | null;
  preferred_mode: string;
  preferred_code_model: string;
}

export const getActivationState = async (): Promise<ActivationStateResult> => {
  return apiGet("/api/activation/state", true);
};

export const logout = async (): Promise<void> => {
  const refreshToken = localStorage.getItem("refresh_token");
  if (refreshToken) {
    try {
      await apiPost("/api/auth/logout", { refresh_token: refreshToken }, true);
    } catch (err) {
      console.warn("Logout request failed:", err);
    }
  }
};
