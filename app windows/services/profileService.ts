import { apiGet, apiPost } from "./apiClient";

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

export const getUserProfile = async () => {
  return apiGet("/api/user/profile", true) as Promise<UserProfile>;
};

export const updateUserProfile = async (payload: {
  display_name?: string;
  avatar_url?: string | null;
  bio?: string | null;
  location?: string | null;
}) => {
  return apiPost("/api/user/profile", payload, true) as Promise<UserProfile>;
};
