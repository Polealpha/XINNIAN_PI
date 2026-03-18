import { apiPost } from "./apiClient";

export type EngineSignalType =
  | "privacy_on"
  | "privacy_off"
  | "do_not_disturb_on"
  | "do_not_disturb_off"
  | "manual_care"
  | "config_update";

export const sendEngineSignal = async (
  type: EngineSignalType,
  payload: Record<string, unknown> = {}
) => {
  return apiPost("/api/engine/signal", { type, payload }, true);
};
