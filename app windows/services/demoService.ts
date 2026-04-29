import { apiGet } from "./apiClient";

export type VisualfocusDemoHealth = {
  ok: boolean;
  remote_ok: boolean;
  bridge_mode: string;
  remote_url: string;
  model_name?: string;
  checkpoint?: string;
  runtime_device?: string;
  remote_error?: string;
  remote_health?: Record<string, unknown>;
};

export const getVisualfocusDemoHealth = async (): Promise<VisualfocusDemoHealth> => {
  return apiGet("/api/vision/camera/health", true);
};
