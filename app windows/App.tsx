import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  CareDeliveryStrategy,
  CarePlan,
  ChatMessage,
  DeviceStatus,
  EmotionEvent,
  EmotionType,
  EngineMode,
  FaceTrackEngineState,
  FaceTrackState,
  RiskDetail,
  RiskScores,
  SystemEvent,
  WakeEngineState,
} from "./types";
import { AtmosphereView } from "./components/AtmosphereView";
import { ActivationGate } from "./components/ActivationGate";
import { ChatInterface } from "./components/ChatInterface";
import { MoodChart } from "./components/MoodChart";
import { Login } from "./components/Login";
import { DeviceMonitor } from "./components/DeviceMonitor";
import { SettingsPanel } from "./components/SettingsPanel";
import {
  Bell,
  LayoutDashboard,
  MessageSquareHeart,
  Settings,
  Terminal,
  Activity,
  Palette,
  X,
  UserRound,
  ListChecks,
  CheckCircle2,
  Circle,
  Trash2,
  Play,
  Pause,
  RotateCcw,
  Minus,
  Plus,
} from "lucide-react";
import {
  LoginResult,
  getActivationState,
  validateSession,
  logout as logoutSession,
} from "./services/authService";
import { getApiBase, getDeviceSyncApiBase } from "./services/apiClient";
import {
  getRealtimeScores,
  getRealtimeRiskDetail,
  getEmotionHistory,
  getEmotionHistoryRange,
} from "./services/emotionService";
import { getChatHistory, addChatMessage } from "./services/chatService";
import { getDeviceStatus } from "./services/deviceService";
import { connectEventStream, EngineEvent } from "./services/eventService";
import { getUserProfile, updateUserProfile } from "./services/profileService";
import { sendEngineSignal } from "./services/engineService";
import { generateDailySummary } from "./services/llmService";

enum Tab {
  DASHBOARD = "DASHBOARD",
  CHAT = "CHAT",
  PERSONA = "PERSONA",
  FOCUS = "FOCUS",
  DEVICE = "DEVICE",
  CONTROL = "CONTROL",
  PROFILE = "PROFILE",
}

type TaskItem = {
  id: string;
  title: string;
  done: boolean;
  minutes: number;
};

type ThemeOption = {
  id: string;
  label: string;
  swatch: string[];
  titleBarColor: string;
  symbolColor: string;
};

type ThemeToken = {
  id: string;
  isDark: boolean;
  bg: string;
  panel: string;
  panelStrong: string;
  text: string;
  muted: string;
  accent: string;
  accent2?: string;
  accent3?: string;
};

type PersonaProfile = {
  id: string;
  name: string;
  title: string;
  vibe: string;
  voiceStyle: string;
  traits: string[];
  intro: string;
  image: string;
};

const APP_ICON_URL = new URL("./assets/app-icon.png", import.meta.url).href;
const PERSONA_BEIDOU_IMAGE_URL = new URL("./assets/personas/beidou.jpg", import.meta.url).href;
const PERSONA_MOLING_IMAGE_URL = new URL("./assets/personas/moling.jpg", import.meta.url).href;
const PERSONA_XIAOGUANG_IMAGE_URL = new URL("./assets/personas/xiaoguang.jpg", import.meta.url).href;

const THEME_OPTIONS: ThemeOption[] = [
  {
    id: "midnight",
    label: "午夜蓝",
    swatch: ["#0F172A", "#6366f1", "#94A3B8"],
    titleBarColor: "#0F172A",
    symbolColor: "#E2E8F0",
  },
  {
    id: "cream",
    label: "奶白豆沙",
    swatch: ["#F7F1E8", "#C48A8A", "#8B5C5C"],
    titleBarColor: "#F7F1E8",
    symbolColor: "#2B1F1F",
  },
  {
    id: "mono",
    label: "极简黑白灰",
    swatch: ["#FFFFFF", "#F2F2F2", "#000000"],
    titleBarColor: "#FFFFFF",
    symbolColor: "#000000",
  },
  {
    id: "tech",
    label: "科技蓝冷灰",
    swatch: ["#F5F7FA", "#2F5DA9", "#A9C4F5"],
    titleBarColor: "#F5F7FA",
    symbolColor: "#2B2E34",
  },
  {
    id: "teal",
    label: "青绿白",
    swatch: ["#FAFAFA", "#3CBFAE", "#BFEDE6"],
    titleBarColor: "#FAFAFA",
    symbolColor: "#2E4A46",
  },
  {
    id: "orange",
    label: "活力橙深蓝",
    swatch: ["#FFF6F0", "#FF7A45", "#1F2A44"],
    titleBarColor: "#FFF6F0",
    symbolColor: "#1F2A44",
  },
  {
    id: "purple",
    label: "紫色渐变",
    swatch: ["#F8F8FF", "#6A5ACD", "#C77DFF"],
    titleBarColor: "#F8F8FF",
    symbolColor: "#222222",
  },
  {
    id: "vintage",
    label: "复古棕米色",
    swatch: ["#F5E6D3", "#B47A3C", "#4F9A94"],
    titleBarColor: "#F5E6D3",
    symbolColor: "#3B2A1F",
  },
  {
    id: "gold",
    label: "高端黑金",
    swatch: ["#111111", "#D8BFA3", "#F8F5F0"],
    titleBarColor: "#111111",
    symbolColor: "#D8BFA3",
  },
  {
    id: "dark",
    label: "深色经典",
    swatch: ["#121212", "#4A90E2", "#EAEAEA"],
    titleBarColor: "#121212",
    symbolColor: "#EAEAEA",
  },
  {
    id: "morandi",
    label: "莫兰迪柔和",
    swatch: ["#F6F6F4", "#7A9EB1", "#D8A7A7"],
    titleBarColor: "#F6F6F4",
    symbolColor: "#2E2E2E",
  },
  {
    id: "red",
    label: "红色强调",
    swatch: ["#FFFFFF", "#E53935", "#F2F2F2"],
    titleBarColor: "#FFFFFF",
    symbolColor: "#333333",
  },
  {
    id: "aqua",
    label: "蓝绿渐变",
    swatch: ["#F9FBFC", "#00C6FF", "#00FFB0"],
    titleBarColor: "#F9FBFC",
    symbolColor: "#1E2A2F",
  },
  {
    id: "neon",
    label: "霓虹电竞",
    swatch: ["#0B0B0F", "#B026FF", "#00E5FF"],
    titleBarColor: "#0B0B0F",
    symbolColor: "#F0E9FF",
  },
];

const THEME_CLASSNAMES = THEME_OPTIONS.filter((theme) => theme.id !== "midnight").map(
  (theme) => `theme-${theme.id}`
);

const THEME_TOKENS: Record<string, ThemeToken> = {
  midnight: {
    id: "midnight",
    isDark: true,
    bg: "#0F172A",
    panel: "#0C1222",
    panelStrong: "#0A0F1D",
    text: "#F8FAFC",
    muted: "#94A3B8",
    accent: "#6366f1",
    accent2: "#c026d3",
    accent3: "#0ea5e9",
  },
  cream: {
    id: "cream",
    isDark: false,
    bg: "#F7F1E8",
    panel: "#F0E4D8",
    panelStrong: "#E8DACE",
    text: "#2B1F1F",
    muted: "#8B5C5C",
    accent: "#C48A8A",
    accent2: "#8B5C5C",
    accent3: "#D8BFA3",
  },
  mono: {
    id: "mono",
    isDark: false,
    bg: "#FFFFFF",
    panel: "#F2F2F2",
    panelStrong: "#E9E9E9",
    text: "#333333",
    muted: "#666666",
    accent: "#000000",
    accent2: "#333333",
    accent3: "#999999",
  },
  tech: {
    id: "tech",
    isDark: false,
    bg: "#F5F7FA",
    panel: "#EEF1F6",
    panelStrong: "#E5ECF6",
    text: "#2B2E34",
    muted: "#5A6472",
    accent: "#2F5DA9",
    accent2: "#A9C4F5",
    accent3: "#4A90E2",
  },
  teal: {
    id: "teal",
    isDark: false,
    bg: "#FAFAFA",
    panel: "#F0F7F6",
    panelStrong: "#E6F2EF",
    text: "#2E4A46",
    muted: "#5A7C75",
    accent: "#3CBFAE",
    accent2: "#BFEDE6",
    accent3: "#2E4A46",
  },
  orange: {
    id: "orange",
    isDark: false,
    bg: "#FFF6F0",
    panel: "#FCEDE1",
    panelStrong: "#F6E2D4",
    text: "#1F2A44",
    muted: "#6A6F7A",
    accent: "#FF7A45",
    accent2: "#1F2A44",
    accent3: "#CFCFCF",
  },
  purple: {
    id: "purple",
    isDark: false,
    bg: "#F8F8FF",
    panel: "#EFEFFB",
    panelStrong: "#E6E6F6",
    text: "#222222",
    muted: "#6B6B7A",
    accent: "#6A5ACD",
    accent2: "#C77DFF",
    accent3: "#7C3AED",
  },
  vintage: {
    id: "vintage",
    isDark: false,
    bg: "#F5E6D3",
    panel: "#EED9C2",
    panelStrong: "#E5CEB4",
    text: "#3B2A1F",
    muted: "#7A5C4B",
    accent: "#B47A3C",
    accent2: "#4F9A94",
    accent3: "#8B5C5C",
  },
  gold: {
    id: "gold",
    isDark: true,
    bg: "#111111",
    panel: "#1A1A1A",
    panelStrong: "#131313",
    text: "#F8F5F0",
    muted: "#D8BFA3",
    accent: "#D8BFA3",
    accent2: "#F8F5F0",
    accent3: "#444444",
  },
  dark: {
    id: "dark",
    isDark: true,
    bg: "#121212",
    panel: "#1E1E1E",
    panelStrong: "#191919",
    text: "#EAEAEA",
    muted: "#9CA3AF",
    accent: "#4A90E2",
    accent2: "#2F5DA9",
    accent3: "#00C6FF",
  },
  morandi: {
    id: "morandi",
    isDark: false,
    bg: "#F6F6F4",
    panel: "#ECEBE7",
    panelStrong: "#E2E1DC",
    text: "#2E2E2E",
    muted: "#6E7A7F",
    accent: "#7A9EB1",
    accent2: "#D8A7A7",
    accent3: "#A8C3A0",
  },
  red: {
    id: "red",
    isDark: false,
    bg: "#FFFFFF",
    panel: "#F2F2F2",
    panelStrong: "#EDEDED",
    text: "#333333",
    muted: "#666666",
    accent: "#E53935",
    accent2: "#F2F2F2",
    accent3: "#333333",
  },
  aqua: {
    id: "aqua",
    isDark: false,
    bg: "#F9FBFC",
    panel: "#EEF6F8",
    panelStrong: "#E5F1F5",
    text: "#1E2A2F",
    muted: "#5B6B72",
    accent: "#00C6FF",
    accent2: "#00FFB0",
    accent3: "#3CBFAE",
  },
  neon: {
    id: "neon",
    isDark: true,
    bg: "#0B0B0F",
    panel: "#12121A",
    panelStrong: "#0F0F16",
    text: "#F5F2FF",
    muted: "#9D8CC9",
    accent: "#B026FF",
    accent2: "#00E5FF",
    accent3: "#FF4FD8",
  },
};

const PERSONA_PROFILES: PersonaProfile[] = [
  {
    id: "qing-lan",
    name: "晴岚",
    title: "温柔共情型",
    vibe: "先接住情绪，再慢慢引导",
    voiceStyle: "轻柔、细腻、低打扰",
    traits: ["情绪安抚", "稳定陪伴", "共情表达"],
    intro: "适合压力大、容易内耗的时段。她不会追问，只会先说“我在”，再给你一个很小但可执行的下一步。",
    image: "https://images.unsplash.com/photo-1745434159123-5b99b94206ca?auto=format&fit=crop&w=1200&q=80",
  },
  {
    id: "bei-dou",
    name: "北斗",
    title: "冷静策略型",
    vibe: "快速梳理重点，降低混乱感",
    voiceStyle: "克制、清晰、结构化",
    traits: ["任务拆解", "优先级判断", "节奏控制"],
    intro: "适合工作高压和信息过载。先把问题分层，再给你可落地的顺序，不灌鸡汤、只给抓手。",
    image: PERSONA_BEIDOU_IMAGE_URL,
  },
  {
    id: "a-che",
    name: "阿澈",
    title: "行动搭子型",
    vibe: "少想一点，先做一点",
    voiceStyle: "直接、轻快、推进感强",
    traits: ["执行推进", "反拖延", "结果导向"],
    intro: "适合“知道该做但起不来”的状态。他会把任务切成超小步骤，陪你把第一步迈出去。",
    image: "https://images.unsplash.com/photo-1754476151319-bc8cf50a1807?auto=format&fit=crop&w=1200&q=80",
  },
  {
    id: "ni-xia",
    name: "霓夏",
    title: "轻松幽默型",
    vibe: "把紧绷情绪松开一点",
    voiceStyle: "俏皮、活泼、带一点玩笑",
    traits: ["情绪解压", "气氛调节", "社交感陪伴"],
    intro: "适合长时间沉默和情绪低落。她会用不冒犯的小幽默把你拉回当下，再温柔提醒休息。",
    image: "https://images.unsplash.com/photo-1740858606672-18ae1a96deeb?auto=format&fit=crop&w=1200&q=80",
  },
  {
    id: "cheng-yin",
    name: "澄音",
    title: "夜间治愈型",
    vibe: "适合睡前复盘与情绪沉淀",
    voiceStyle: "慢速、安静、陪伴感强",
    traits: ["夜间总结", "缓和焦虑", "稳定收尾"],
    intro: "适合晚上聊天和总结。她会把一天的情绪脉络说清楚，帮你把情绪放下，而不是继续拉扯。",
    image: "https://images.unsplash.com/photo-1687360440741-f5df549b352d?auto=format&fit=crop&w=1200&q=80",
  },
  {
    id: "hu-po",
    name: "琥珀",
    title: "边界守护型",
    vibe: "尊重空间，不强行介入",
    voiceStyle: "沉稳、克制、礼貌",
    traits: ["不打扰模式", "边界感强", "安全表达"],
    intro: "适合需要独处但又希望被看见的时段。你说停，他就停；你想聊，他再出现。",
    image: "https://images.unsplash.com/photo-1749224445782-297c6fe4f4ec?auto=format&fit=crop&w=1200&q=80",
  },
  {
    id: "mo-ling",
    name: "墨零",
    title: "专注协作型",
    vibe: "降低外部噪声，进入深度工作",
    voiceStyle: "短句、明确、节律感强",
    traits: ["番茄协作", "专注提醒", "中断恢复"],
    intro: "适合工位深度工作。他不会频繁说话，只在关键时点提醒你呼吸、喝水、拉回专注。",
    image: PERSONA_MOLING_IMAGE_URL,
  },
  {
    id: "xiao-guang",
    name: "小光",
    title: "鼓励成长型",
    vibe: "看到微小进步并及时反馈",
    voiceStyle: "明亮、积极、鼓舞感",
    traits: ["正向反馈", "习惯养成", "目标对齐"],
    intro: "适合长期计划和习惯养成。每一点进展都会被记录并反馈，帮你保持“持续前进”的心态。",
    image: PERSONA_XIAOGUANG_IMAGE_URL,
  },
];

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

const hexToRgb = (hex: string) => {
  const cleaned = hex.replace("#", "");
  if (![3, 6].includes(cleaned.length)) return null;
  const normalized =
    cleaned.length === 3
      ? cleaned
          .split("")
          .map((c) => c + c)
          .join("")
      : cleaned;
  const num = parseInt(normalized, 16);
  if (Number.isNaN(num)) return null;
  return {
    r: (num >> 16) & 255,
    g: (num >> 8) & 255,
    b: num & 255,
  };
};

const withAlpha = (hex: string, alpha: number) => {
  const rgb = hexToRgb(hex);
  if (!rgb) return `rgba(0,0,0,${alpha})`;
  return `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${alpha})`;
};

const mapTagsToEmotion = (tags: string[], score: number): EmotionType => {
  const normalized = tags.map((tag) => String(tag).toLowerCase());
  if (normalized.some((tag) => ["anger", "angry"].includes(tag))) {
    return EmotionType.ANGRY;
  }
  if (normalized.some((tag) => ["fatigue", "tired"].includes(tag))) {
    return EmotionType.TIRED;
  }
  if (normalized.some((tag) => ["lonely", "sad"].includes(tag))) {
    return EmotionType.SAD;
  }
  if (score >= 0.7) {
    return EmotionType.ANXIOUS;
  }
  return EmotionType.CALM;
};

const normalizeMode = (mode: string): EngineMode => {
  const raw = String(mode || "").toLowerCase();
  if (raw.includes("privacy")) return "privacy";
  if (raw.includes("dnd") || raw.includes("quiet")) return "dnd";
  return "normal";
};

const normalizeCareDeliveryStrategy = (value: unknown): CareDeliveryStrategy => {
  const raw = String(value || "").trim().toLowerCase();
  if (raw === "voice_all_day") return "voice_all_day";
  if (raw === "popup_all_day") return "popup_all_day";
  return "policy";
};

const App: React.FC = () => {
  const [isGuest, setIsGuest] = useState(() => localStorage.getItem("guest_mode") === "true");
  const [isAuthenticated, setIsAuthenticated] = useState(
    () => localStorage.getItem("guest_mode") === "true"
  );
  const [authChecked, setAuthChecked] = useState(false);
  const [activationRequired, setActivationRequired] = useState(
    () => localStorage.getItem("activation_required") === "true"
  );
  const [activationPath, setActivationPath] = useState(
    () => localStorage.getItem("activation_path") || "/activate"
  );
  const [activeTab, setActiveTab] = useState<Tab>(Tab.DASHBOARD);
  const [selectedPersonaId, setSelectedPersonaId] = useState(
    () => localStorage.getItem("persona_profile_id") || PERSONA_PROFILES[0].id
  );
  const [mode, setMode] = useState<EngineMode>("normal");
  const [careDeliveryStrategy, setCareDeliveryStrategy] = useState<CareDeliveryStrategy>(() =>
    normalizeCareDeliveryStrategy(localStorage.getItem("care_delivery_strategy"))
  );
  const [scores, setScores] = useState<RiskScores>({ V: 0, A: 0, T: 0, S: 0 });
  const [riskDetail, setRiskDetail] = useState<RiskDetail | null>(null);
  const [events, setEvents] = useState<EmotionEvent[]>([]);
  const [sysLogs, setSysLogs] = useState<SystemEvent[]>([]);
  const [faceTrack, setFaceTrack] = useState<FaceTrackState | null>(null);
  const [faceTrackEngine, setFaceTrackEngine] = useState<FaceTrackEngineState | null>(null);
  const [wakeEngine, setWakeEngine] = useState<WakeEngineState | null>(null);
  const [wakeDebug, setWakeDebug] = useState<{
    text: string;
    reason: string;
    ts: number;
  } | null>(null);
  const [deviceStatus, setDeviceStatus] = useState<DeviceStatus | null>(null);
  const [deviceStatusError, setDeviceStatusError] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [voiceState, setVoiceState] = useState<
    "idle" | "detecting" | "listening" | "thinking" | "speaking"
  >("idle");
  const wakeActiveUntilRef = useRef<number>(0);

  const isLikelyWakeText = useCallback((raw: string): boolean => {
    const t = String(raw || "").trim().toLowerCase();
    if (!t) return false;
    const compact = t.replace(/[\s,.;:!?，。！？、“”"'\-_/|()[\]{}<>`~]+/g, "");
    if (!compact) return false;
    if (
      compact.includes("小念") ||
      compact.includes("心念") ||
      compact.includes("小面") ||
      compact.includes("小年") ||
      compact.includes("晓念") ||
      compact.includes("小云") ||
      compact.includes("信念") ||
      compact.includes("新年")
    ) {
      return true;
    }
    const roman = compact.replace(/[^a-z]/g, "");
    if (!roman) return false;
    return (
      roman.includes("xiaonian") ||
      roman.includes("xinnian") ||
      roman.includes("xiaoyun")
    );
  }, []);
  const [carePopup, setCarePopup] = useState<CarePlan | null>(null);
  const [weeklySummaryPopup, setWeeklySummaryPopup] = useState<string | null>(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [riskUpdatedAt, setRiskUpdatedAt] = useState<number | null>(null);
  const [riskSource, setRiskSource] = useState<"ws" | "poll" | null>(null);
  const [statusRefreshing, setStatusRefreshing] = useState(false);
  const [triggerToasts, setTriggerToasts] = useState<
    { id: string; title: string; detail: string }[]
  >([]);

  const showSystemNotification = useCallback((title: string, body: string) => {
    (window as any).desktop?.notifySystem?.({ title, body, silent: false });
  }, []);
  const [profileName, setProfileName] = useState(
    () => localStorage.getItem("profile_name") || "共鸣旅人"
  );
  const [profileAvatar, setProfileAvatar] = useState(
    () => localStorage.getItem("profile_avatar") || ""
  );
  const [profileBio, setProfileBio] = useState(() => localStorage.getItem("profile_bio") || "");
  const [profileLocation, setProfileLocation] = useState(
    () => localStorage.getItem("profile_location") || ""
  );
  const [profileUsername, setProfileUsername] = useState(() => localStorage.getItem("profile_username") || "");
  const [profileCreatedAt, setProfileCreatedAt] = useState<number | null>(() => {
    const raw = localStorage.getItem("profile_created_at");
    return raw ? Number(raw) || null : null;
  });
  const [profileUpdatedAt, setProfileUpdatedAt] = useState<number | null>(() => {
    const raw = localStorage.getItem("profile_updated_at");
    return raw ? Number(raw) || null : null;
  });
  const [profileDraftName, setProfileDraftName] = useState(profileName);
  const [profileDraftAvatar, setProfileDraftAvatar] = useState(profileAvatar);
  const [profileDraftBio, setProfileDraftBio] = useState(profileBio);
  const [profileDraftLocation, setProfileDraftLocation] = useState(profileLocation);
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileError, setProfileError] = useState("");
  const [uiTheme, setUiTheme] = useState(() => localStorage.getItem("ui_theme") || "midnight");
  const [themeMenuOpen, setThemeMenuOpen] = useState(false);
  const [themeOnboardingOpen, setThemeOnboardingOpen] = useState(
    () => !localStorage.getItem("ui_theme")
  );
  const [mediaState, setMediaState] = useState(() => ({
    videoEnabled: localStorage.getItem("media_video") !== "false",
    audioEnabled: localStorage.getItem("media_audio") !== "false",
  }));
  const [faceTrackOverlayEnabled, setFaceTrackOverlayEnabled] = useState(
    () => localStorage.getItem("face_track_overlay") !== "false"
  );
  const [deviceViewKey, setDeviceViewKey] = useState(0);
  const [tasks, setTasks] = useState<TaskItem[]>(() => {
    try {
      const raw = localStorage.getItem("focus_tasks");
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        return parsed
          .filter((item) => item && typeof item.title === "string")
          .map((item) => ({
            ...item,
            minutes: Number.isFinite(item?.minutes) ? Number(item.minutes) : 25,
          }));
      }
    } catch (err) {
      return [];
    }
    return [];
  });

  useEffect(() => {
    if (activeTab === Tab.DEVICE) {
      setDeviceViewKey((v) => v + 1);
    }
  }, [activeTab]);
  const [taskInput, setTaskInput] = useState("");
  const [taskMinutes, setTaskMinutes] = useState(25);
  const [pomodoroWorkMin, setPomodoroWorkMin] = useState(() => {
    const stored = Number(localStorage.getItem("pomo_work_min"));
    return Number.isFinite(stored) && stored > 0 ? stored : 25;
  });
  const [pomodoroBreakMin, setPomodoroBreakMin] = useState(() => {
    const stored = Number(localStorage.getItem("pomo_break_min"));
    return Number.isFinite(stored) && stored > 0 ? stored : 5;
  });
  const [pomodoroRounds, setPomodoroRounds] = useState(() => {
    const stored = Number(localStorage.getItem("pomo_rounds"));
    return Number.isFinite(stored) && stored > 0 ? stored : 4;
  });
  const [pomodoroRound, setPomodoroRound] = useState(1);
  const [pomodoroMode, setPomodoroMode] = useState<"work" | "break">("work");
  const [pomodoroRunning, setPomodoroRunning] = useState(false);
  const [pomodoroSeconds, setPomodoroSeconds] = useState(() => pomodoroWorkMin * 60);
  const [floatDragging, setFloatDragging] = useState(false);
  const selectedPersona =
    PERSONA_PROFILES.find((item) => item.id === selectedPersonaId) || PERSONA_PROFILES[0];

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const themeMenuRef = useRef<HTMLDivElement | null>(null);
  const lastRiskLogRef = useRef(0);
  const wsRef = useRef<WebSocket | null>(null);
  const floatDragRef = useRef({
    active: false,
    hasDragged: false,
  });
  const floatPointerRef = useRef({
    screenX: 0,
    screenY: 0,
    clientX: 0,
    clientY: 0,
  });
  const dragTimerRef = useRef<number | null>(null);
  const suppressClickRef = useRef(false);

  const floatMode =
    typeof window !== "undefined"
      ? new URLSearchParams(window.location.search).get("float")
      : null;
  const isFloatWidget = floatMode === "widget";
  const isFloatChat = floatMode === "chat";
  const voiceStateLabel =
    voiceState === "detecting"
      ? "待唤醒"
      : voiceState === "listening"
      ? "聆听中"
      : voiceState === "thinking"
      ? "思考中"
      : voiceState === "speaking"
      ? "播报中"
      : "空闲";
  const voiceStateActive = voiceState !== "idle";

  const getWeekKey = (date: Date) => {
    const tmp = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
    const day = tmp.getUTCDay() || 7;
    tmp.setUTCDate(tmp.getUTCDate() + 4 - day);
    const yearStart = new Date(Date.UTC(tmp.getUTCFullYear(), 0, 1));
    const weekNo = Math.ceil(((tmp.getTime() - yearStart.getTime()) / 86400000 + 1) / 7);
    return `${tmp.getUTCFullYear()}-W${String(weekNo).padStart(2, "0")}`;
  };

  const isSameLocalDay = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate();

  const getDayPartLabel = (date: Date) => {
    const hour = date.getHours();
    if (hour < 6) return "凌晨";
    if (hour < 9) return "早晨";
    if (hour < 12) return "上午";
    if (hour < 14) return "中午";
    if (hour < 18) return "下午";
    return "晚上";
  };

  const applyTheme = useCallback((themeId: string) => {
    if (typeof document === "undefined") return;
    const token = THEME_TOKENS[themeId] || THEME_TOKENS.midnight;
    const accentSoft = withAlpha(token.accent, token.isDark ? 0.18 : 0.14);
    const accentSoftStrong = withAlpha(token.accent, token.isDark ? 0.35 : 0.25);
    const panelBg = withAlpha(token.panel, token.isDark ? 0.6 : 0.85);
    const panelStrong = withAlpha(token.panelStrong, token.isDark ? 0.88 : 0.92);
    const faint = withAlpha(token.text, token.isDark ? 0.5 : 0.6);
    const border = withAlpha(token.text, token.isDark ? 0.08 : 0.12);
    const root = document.documentElement;

    root.style.setProperty("--bg-color", token.bg);
    root.style.setProperty("--theme-text", token.text);
    root.style.setProperty("--theme-muted", token.muted);
    root.style.setProperty("--theme-faint", faint);
    root.style.setProperty("--accent", token.accent);
    root.style.setProperty("--accent-soft", accentSoft);
    root.style.setProperty("--accent-soft-strong", accentSoftStrong);
    root.style.setProperty("--panel-bg", panelBg);
    root.style.setProperty("--panel-bg-strong", panelStrong);
    root.style.setProperty("--panel-border", border);
    root.style.setProperty("--chip-bg", withAlpha(token.accent, 0.1));
    root.style.setProperty("--chip-border", withAlpha(token.accent, 0.25));
    root.style.setProperty("--chip-text", token.muted);
    root.style.setProperty("--chart-accent", token.accent);
    root.style.setProperty("--chart-grid", withAlpha(token.text, token.isDark ? 0.08 : 0.12));
    root.style.setProperty("--chart-tick", token.muted);
    root.style.setProperty("--chart-tooltip-bg", withAlpha(token.panelStrong, 0.96));
    root.style.setProperty("--chart-tooltip-border", border);
    root.style.setProperty(
      "--aurora-bg",
      `radial-gradient(circle at 50% 50%, ${withAlpha(
        token.accent2 || token.accent,
        token.isDark ? 0.35 : 0.2
      )} 0%, ${token.bg} 70%)`
    );
    root.style.setProperty("--aurora-blob-1", token.accent2 || token.accent);
    root.style.setProperty("--aurora-blob-2", token.accent3 || token.accent);
    root.style.setProperty("--aurora-blob-3", token.accent);
    root.style.setProperty("--top-pill-bg", accentSoft);
    root.style.setProperty("--top-pill-border", accentSoftStrong);
    root.style.setProperty("--top-pill-text", token.muted);
    root.style.setProperty(
      "--top-pill-shadow",
      token.isDark ? "0 12px 30px rgba(15, 23, 42, 0.3)" : "0 12px 30px rgba(0, 0, 0, 0.08)"
    );
    root.style.setProperty("--top-btn-bg", withAlpha(token.text, token.isDark ? 0.08 : 0.06));
    root.style.setProperty(
      "--top-btn-bg-hover",
      withAlpha(token.text, token.isDark ? 0.16 : 0.12)
    );
    root.style.setProperty("--top-btn-border", withAlpha(token.text, token.isDark ? 0.12 : 0.1));
    root.style.setProperty("--top-btn-text", token.muted);
    root.style.setProperty("--top-btn-text-hover", token.text);
    root.style.setProperty("--top-icon", token.muted);
    root.style.setProperty("--top-icon-hover", token.text);
    root.style.setProperty("--status-online", token.accent);
    root.style.setProperty("--status-offline", token.isDark ? "#f59e0b" : "#d97706");

    const body = document.body;
    body.classList.add("theme-variant");
    THEME_CLASSNAMES.forEach((name) => body.classList.remove(name));
    if (themeId !== "midnight") {
      body.classList.add(`theme-${themeId}`);
    }
  }, []);

  const persistTheme = useCallback((themeId: string) => {
    localStorage.setItem("ui_theme", themeId);
  }, []);

  const pushToast = useCallback((title: string, detail: string) => {
    const id = `toast-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    setTriggerToasts((prev) => [...prev, { id, title, detail }]);
    window.setTimeout(() => {
      setTriggerToasts((prev) => prev.filter((toast) => toast.id !== id));
    }, 4200);
  }, []);

  const pushSystemLog = useCallback((type: string, payload: Record<string, any>, ts?: number) => {
    const timestamp = ts ? new Date(ts) : new Date();
    const id = `${type}-${timestamp.getTime()}-${Math.random().toString(16).slice(2)}`;
    setSysLogs((prev) => [{ id, type, payload, timestamp }, ...prev].slice(0, 40));
  }, []);

  const maybeTriggerWeeklySummary = useCallback(async () => {
    if (isFloatWidget || isFloatChat) return;
    if (!isAuthenticated || isGuest) return;
    const now = new Date();
    const weekKey = getWeekKey(now);
    const lastKey = localStorage.getItem("weekly_summary_week");
    if (lastKey === weekKey) return;
    // Sunday 21:00 local time
    if (now.getDay() !== 0 || now.getHours() < 21) return;

    try {
      const endMs = now.getTime();
      const startMs = endMs - 7 * 24 * 60 * 60 * 1000;
      const events = await getEmotionHistoryRange({ startMs, endMs, limit: 500 });
      const summary = await generateDailySummary(events);
      const title = "每周情绪总结";
      showSystemNotification(title, summary);
      pushToast(title, summary);
      setWeeklySummaryPopup(summary);
      localStorage.setItem("weekly_summary_week", weekKey);
    } catch (err) {
      console.warn("weekly summary failed:", err);
    }
  }, [isAuthenticated, isGuest, isFloatWidget, isFloatChat, pushToast, showSystemNotification]);

  const appendMessage = useCallback(
    (message: ChatMessage, persist = false) => {
      const hasText = Boolean(String(message.text || "").trim());
      const hasAttachments = Array.isArray(message.attachments) && message.attachments.length > 0;
      if (!hasText && !hasAttachments) return;
      setMessages((prev) => {
        if (prev.some((item) => item.id === message.id)) return prev;
        const ts = message.timestamp.getTime();
        const msgAttachKey = JSON.stringify(message.attachments || []);
        if (
          prev.some(
            (item) =>
              item.sender === message.sender &&
              item.text === message.text &&
              JSON.stringify(item.attachments || []) === msgAttachKey &&
              Math.abs(item.timestamp.getTime() - ts) <= 4000
          )
        ) {
          return prev;
        }
        return [...prev, message];
      });
      if (persist && !isGuest) {
        addChatMessage(message).catch((err) => console.warn("save chat failed:", err));
      }
    },
    [isGuest]
  );

  const handleChatUpdate = useCallback(
    (msg: ChatMessage) => {
      appendMessage(msg);
    },
    [appendMessage]
  );

  const expressionLabelForChat = (() => {
    const exprId = Number(riskDetail?.V_sub?.expression_class_id);
    const labels = ["neutral", "happiness", "surprise", "sadness", "anger", "disgust", "fear", "contempt"];
    if (Number.isFinite(exprId) && exprId >= 0 && exprId < labels.length) {
      return labels[Math.floor(exprId)];
    }
    return "unknown";
  })();
  const expressionConfidenceForChat = Number(riskDetail?.V_sub?.expression_confidence ?? 0);

  const toEmotionEvent = useCallback((event: EngineEvent): EmotionEvent | null => {
    const payload = (event.payload || {}) as Record<string, any>;
    const reason = (payload.reason && typeof payload.reason === "object" ? payload.reason : {}) as Record<
      string,
      any
    >;
    const tags = Array.isArray(reason.tags) ? reason.tags.map((t) => String(t)) : [];
    const v = Number(reason.V ?? payload.V ?? 0);
    const a = Number(reason.A ?? payload.A ?? 0);
    const t = Number(reason.T ?? payload.T ?? 0);
    const s = Number(reason.S ?? payload.S ?? Math.max(v, a, t, 0));
    const description =
      String(payload?.care_plan?.text || payload?.summary || payload?.transcript || "").trim() ||
      `event:${event.type}`;
    const carePlanPayload = payload?.care_plan;
    const carePlan =
      carePlanPayload && typeof carePlanPayload === "object" && carePlanPayload.text
        ? {
            text: String(carePlanPayload.text),
            style: (carePlanPayload.style as CarePlan["style"]) || "warm",
            motion: carePlanPayload.motion,
            emo: carePlanPayload.emo,
            followup_question: carePlanPayload.followup_question,
          }
        : undefined;

    return {
      id: `${event.type}-${event.timestamp_ms}`,
      timestamp: new Date(event.timestamp_ms),
      type: mapTagsToEmotion(tags, s),
      scores: { V: v, A: a, T: t, S: s },
      description,
      intensity: clamp(Math.round(s * 100), 0, 100),
      source: "engine",
      carePlan,
      transcript: payload?.transcript,
    };
  }, []);

  const handleEngineEvent = useCallback(
    (event: EngineEvent) => {
      const payload = (event.payload || {}) as Record<string, any>;
      if (event.type === "RiskUpdate") {
        setScores({
          V: Number(payload.V ?? 0),
          A: Number(payload.A ?? 0),
          T: Number(payload.T ?? 0),
          S: Number(payload.S ?? 0),
        });
        setRiskUpdatedAt(Number(event.timestamp_ms || Date.now()));
        setRiskSource("ws");
        if (payload.detail && typeof payload.detail === "object") {
          const detail = payload.detail as Record<string, any>;
          setRiskDetail({
            V_sub: (detail.V_sub as Record<string, number>) || {},
            A_sub: (detail.A_sub as Record<string, number>) || {},
            T_sub: (detail.T_sub as Record<string, any>) || {},
          });
        }
        if (payload.mode) {
          setMode(normalizeMode(payload.mode));
        }
        return;
      }
      if (event.type === "FaceTrackUpdate") {
        const toNum = (value: unknown, fallback = 0) => {
          const parsed = Number(value);
          return Number.isFinite(parsed) ? parsed : fallback;
        };
        const rawBox = Array.isArray(payload.bbox) ? payload.bbox.slice(0, 4).map(Number) : null;
        const bboxValid =
          !!rawBox &&
          rawBox.length === 4 &&
          rawBox.every((v) => Number.isFinite(v)) &&
          rawBox[2] > 0 &&
          rawBox[3] > 0;
        const bbox = bboxValid
          ? ([rawBox[0], rawBox[1], rawBox[2], rawBox[3]] as [number, number, number, number])
          : null;
        setFaceTrack({
          found: Boolean(payload.found),
          bbox,
          frame_w: toNum(payload.frame_w, 0),
          frame_h: toNum(payload.frame_h, 0),
          ex: toNum(payload.ex, 0),
          ex_smooth: toNum(payload.ex_smooth, 0),
          turn:
            payload.turn == null || Number.isNaN(Number(payload.turn))
              ? null
              : toNum(payload.turn, 0),
          lost: Math.max(0, Math.floor(toNum(payload.lost, 0))),
          sent: Boolean(payload.sent),
          mode: String(payload.mode ?? ""),
          scene: String(payload.scene ?? ""),
          ts_ms: toNum(payload.ts_ms ?? event.timestamp_ms ?? Date.now(), Date.now()),
        });
        return;
      }
      if (event.type === "FaceTrackState") {
        const payloadObj = payload || {};
        setFaceTrackEngine({
          enabled: Boolean(payloadObj.enabled),
          detector_ready: Boolean(payloadObj.detector_ready),
          detector: String(payloadObj.detector || "unknown"),
          ts_ms: Number(payloadObj.ts_ms ?? event.timestamp_ms ?? Date.now()),
        });
        return;
      }
      if (event.type === "WakeState") {
        const payloadObj = payload || {};
        setWakeEngine((prev) => ({
          enabled: Boolean(payloadObj.enabled),
          model: String(payloadObj.model || prev?.model || ""),
          error: payloadObj.error ? String(payloadObj.error) : undefined,
          last_wake_ms: prev?.last_wake_ms,
        }));
        return;
      }
      if (event.type === "WakeDiag") {
        const reason = String(payload?.reason || "wake_diag").trim();
        const message = String(payload?.message || "").trim();
        const selectedName = String(payload?.selected_name || "").trim();
        const selectedIndex = Number(payload?.selected_index);
        const detail = message
          ? message
          : selectedName
          ? `麦克风：${selectedName}${
              Number.isFinite(selectedIndex) && selectedIndex >= 0 ? ` (#${selectedIndex})` : ""
            }`
          : reason;
        setWakeDebug({
          text: detail || "wake diag",
          reason: `diag:${reason}`,
          ts: Date.now(),
        });
        return;
      }
      if (event.type === "WakeWordDetected") {
        const phrase = String(payload?.phrase || "小念").trim();
        const isEnergyFallbackWake = phrase.includes("能量兜底");
        setWakeEngine((prev) => ({
          enabled: prev?.enabled ?? true,
          model: prev?.model,
          error: prev?.error,
          last_wake_ms: Number(event.timestamp_ms || Date.now()),
        }));
        setWakeDebug({
          text: phrase || "唤醒命中",
          reason: "wake_detected",
          ts: Date.now(),
        });
        if (!isEnergyFallbackWake) {
          appendMessage(
            {
              id: `wake-${event.timestamp_ms}`,
              sender: "bot",
              text: "已进入语音对话模式，我在聆听。",
              timestamp: new Date(Number(event.timestamp_ms || Date.now())),
            },
            false
          );
          pushToast("语音已唤醒", "已进入对话模式");
        }
        return;
      }
      if (event.type === "WakeAudioState") {
        const state = String(payload?.state || "").toLowerCase();
        const reason = String(payload?.reason || "").trim();
        const partialText = String(payload?.text || payload?.phrase || "").trim();
        const partialLikelyWake = partialText ? isLikelyWakeText(partialText) : false;
        const now = Date.now();
        const wakeSessionActive = now <= wakeActiveUntilRef.current;
        if (state === "listening" || state === "thinking" || state === "speaking") {
          wakeActiveUntilRef.current = now + 8000;
        }
        if (
          partialText ||
          reason === "wake_partial" ||
          reason === "wake_meter" ||
          reason === "wake_listening" ||
          reason === "wake_first_utterance_filtered" ||
          reason === "wake_first_utterance_empty_retry" ||
          reason === "voice_session_auto_exit_silence" ||
          reason.startsWith("voice_empty_retry_") ||
          reason === "voice_empty_retry_exhausted" ||
          reason === "llm_timeout" ||
          reason === "llm_rate_limit" ||
          reason === "llm_empty" ||
          reason === "web_search_budget_exceeded" ||
          reason === "web_search_not_high_value" ||
          reason === "web_search_tool_unavailable" ||
          reason === "news_web_search_forced" ||
          reason === "high_value_news" ||
          reason === "news_fallback_used" ||
          reason === "news_api_used" ||
          reason === "news_api_failed_fallback_web" ||
          reason === "fx_api_used" ||
          reason === "stock_api_used" ||
          reason === "stock_api_limited" ||
          reason === "system_tool_exec_ok" ||
          reason === "system_tool_exec_failed" ||
          reason === "function_call_sanitized" ||
          reason === "function_call_blocked_and_rewritten" ||
          reason === "local_tool_music_start_ok" ||
          reason === "local_tool_music_start_failed" ||
          reason === "manual_wake_received" ||
          reason === "manual_wake_dispatched"
        ) {
          const meter = payload?.energy;
          const meterText =
            reason === "wake_meter"
              ? `mic:${typeof meter === "number" ? meter.toFixed(1) : String(meter ?? "--")}`
              : "";
          const showPartial = partialText && (reason !== "wake_partial" || partialLikelyWake);
          const shouldKeepSessionState =
            wakeSessionActive && (reason === "wake_meter" || reason === "wake_listening");
          const reasonText =
            reason === "wake_first_utterance_filtered"
              ? "已过滤唤醒词，请继续说内容"
              : reason === "wake_first_utterance_empty_retry"
              ? "未听清首句，请继续说"
              : reason.startsWith("voice_empty_retry_")
              ? "没听清，请继续说"
              : reason === "voice_empty_retry_exhausted"
              ? "连续未听清，已退出语音对话"
              : reason === "voice_session_auto_exit_silence"
              ? "长时间未说话，已退出语音对话"
              : reason === "llm_timeout"
              ? "大模型响应稍慢，已使用短句兜底"
              : reason === "llm_rate_limit"
              ? "大模型触发限流，已使用短句兜底"
              : reason === "llm_empty"
              ? "大模型未返回内容，已使用短句兜底"
              : reason === "web_search_budget_exceeded"
              ? "联网搜索今日额度已用完，已自动降级"
              : reason === "web_search_not_high_value"
              ? "该问题已走本地工具/API，不使用联网搜索"
              : reason === "web_search_tool_unavailable"
              ? "联网搜索暂不可用，已自动降级"
              : reason === "news_web_search_forced"
              ? "新闻问题已走联网搜索"
              : reason === "high_value_news"
              ? "复杂新闻问题已走联网搜索"
              : reason === "news_fallback_used"
              ? "新闻默认走免费摘要接口"
              : reason === "news_api_used"
              ? "已使用免费新闻接口"
              : reason === "news_api_failed_fallback_web"
              ? "新闻接口失败，已自动转联网搜索"
              : reason === "fx_api_used"
              ? "已使用汇率 API"
              : reason === "stock_api_used"
              ? "已使用股票 API"
              : reason === "stock_api_limited"
              ? "股票 API 限流，已降级"
              : reason === "system_tool_exec_ok"
              ? "系统工具执行成功"
              : reason === "system_tool_exec_failed"
              ? "系统工具执行失败"
              : reason === "function_call_sanitized"
              ? "已清洗工具调用草稿并返回最终答复"
              : reason === "function_call_blocked_and_rewritten"
              ? "已拦截工具草稿并重写最终答复"
              : reason === "local_tool_music_start_ok"
              ? "已触发本地音乐工具"
              : reason === "local_tool_music_start_failed"
              ? "本地音乐工具触发失败，已回退"
              : "";
          setWakeDebug({
            text:
              (showPartial ? partialText : reason === "wake_partial" ? "疑似唤醒中..." : "") ||
              reasonText ||
              meterText ||
              (shouldKeepSessionState ? voiceState : state ? `${state}` : reason || "listening"),
            reason: shouldKeepSessionState ? "wake_session" : reason || state || "wake_state",
            ts: now,
          });
        }
        if (reason !== "wake_meter" && reason !== "wake_listening" && (
          state === "detecting" ||
          state === "listening" ||
          state === "thinking" ||
          state === "speaking"
        )) {
          setVoiceState(state as "detecting" | "listening" | "thinking" | "speaking");
        } else if (!wakeSessionActive && reason !== "wake_meter") {
          setVoiceState("idle");
        }
        return;
      }
      if (event.type === "MediaState") {
        setMediaState((prev) => {
          const next = {
            videoEnabled:
              payload.video_enabled ?? payload.camera_enabled ?? payload.videoEnabled ?? prev.videoEnabled,
            audioEnabled:
              payload.audio_enabled ?? payload.mic_enabled ?? payload.audioEnabled ?? prev.audioEnabled,
          };
          return next;
        });
        return;
      }

      if (event.type === "UserProfileUpdated") {
        const displayName = String(payload.display_name || payload.username || profileName || "共鸣旅人");
        const avatarUrl = String(payload.avatar_url || "");
        const bio = String(payload.bio || "");
        const location = String(payload.location || "");
        setProfileName(displayName);
        setProfileAvatar(avatarUrl);
        setProfileBio(bio);
        setProfileLocation(location);
        setProfileDraftName(displayName);
        setProfileDraftAvatar(avatarUrl);
        setProfileDraftBio(bio);
        setProfileDraftLocation(location);
        if (payload.username) setProfileUsername(String(payload.username));
        if (payload.created_at != null) setProfileCreatedAt(Number(payload.created_at) || null);
        if (payload.updated_at != null) setProfileUpdatedAt(Number(payload.updated_at) || null);
        localStorage.setItem("profile_name", displayName);
        localStorage.setItem("profile_avatar", avatarUrl);
        localStorage.setItem("profile_bio", bio);
        localStorage.setItem("profile_location", location);
        if (payload.username) localStorage.setItem("profile_username", String(payload.username));
        if (payload.created_at != null) localStorage.setItem("profile_created_at", String(payload.created_at));
        if (payload.updated_at != null) localStorage.setItem("profile_updated_at", String(payload.updated_at));
        return;
      }

      if (event.type === "ChatMessage" && (payload?.text || (Array.isArray(payload?.attachments) && payload.attachments.length > 0))) {
        appendMessage(
          {
            id: `chat-${String(payload.id ?? event.timestamp_ms)}`,
            sender: payload.sender === "user" ? "user" : "bot",
            text: String(payload.text),
            contentType: String(payload.content_type || "text") as ChatMessage["contentType"],
            attachments: Array.isArray(payload.attachments) ? payload.attachments : [],
            timestamp: new Date(Number(payload.timestamp_ms ?? event.timestamp_ms ?? Date.now())),
          },
          false
        );
        return;
      }
      if ((event.type === "VoiceChatUser" || event.type === "VoiceChatBot") && payload?.text) {
        appendMessage(
          {
            id: `${event.type}-${String(event.timestamp_ms)}`,
            sender: event.type === "VoiceChatUser" ? "user" : "bot",
            text: String(payload.text),
            contentType: "text",
            attachments: [],
            timestamp: new Date(Number(event.timestamp_ms ?? Date.now())),
          },
          false
        );
        return;
      }

      if (["TriggerFired", "CarePlanReady", "DailySummaryReady"].includes(event.type)) {
        pushSystemLog(event.type, payload, event.timestamp_ms);
      }

      if (["TriggerFired", "CarePlanReady", "DailySummaryReady"].includes(event.type)) {
        const emotionEvent = toEmotionEvent(event);
        if (emotionEvent) {
          setEvents((prev) => [emotionEvent, ...prev].slice(0, 60));
        }
      }

      if (event.type === "TriggerFired") {
        pushToast("触发检测", payload?.reason?.pattern || "检测到触发条件");
      }

      if (event.type === "CarePlanReady" && payload?.care_plan?.text) {
        const contentSource = String(payload?.care_plan?.policy?.content_source || "")
          .trim()
          .toLowerCase();
        const reasonPattern = String(payload?.reason?.pattern || "").trim().toLowerCase();
        const allowManualFallback = contentSource === "manual_fallback" && reasonPattern === "manual";
        if (contentSource !== "llm" && !allowManualFallback) {
          return;
        }
        const plan: CarePlan = {
          text: String(payload.care_plan.text),
          style: (payload.care_plan.style as CarePlan["style"]) || "warm",
          motion: payload.care_plan.motion,
          emo: payload.care_plan.emo,
          followup_question: payload.care_plan.followup_question,
        };
        const deliveryMode = String(payload?.delivery_mode || "text").toLowerCase();
        if (deliveryMode === "text" || deliveryMode === "both") {
          showSystemNotification("主动关怀", plan.text);
          if (plan.followup_question) {
            showSystemNotification("轻问一句", plan.followup_question);
          }
        }
        appendMessage(
          {
            id: `care-${event.timestamp_ms}`,
            sender: "bot",
            text: plan.text,
            timestamp: new Date(event.timestamp_ms),
            isActiveCare: true,
          },
          true
        );
      }

      if (event.type === "DailySummaryReady") {
        const summaryText = String(payload?.summary || "已生成今日总结");
        showSystemNotification("日终总结", summaryText);
        pushToast("日终总结", summaryText);
      }
    },
    [
      appendMessage,
      isLikelyWakeText,
      profileName,
      pushSystemLog,
      pushToast,
      toEmotionEvent,
    ]
  );

  const fetchDeviceStatus = useCallback(async () => {
    if (isGuest) return;
    setStatusRefreshing(true);
    setDeviceStatusError("");
    try {
      const status = await getDeviceStatus();
      setDeviceStatus(status);
    } catch (err) {
      console.error("Device status fetch failed:", err);
      setDeviceStatusError("状态刷新失败");
    } finally {
      setStatusRefreshing(false);
    }
  }, [isGuest]);

  useEffect(() => {
    if (!wakeDebug) return;
    if (
      wakeDebug.reason === "wake_meter" ||
      wakeDebug.reason === "wake_listening"
    ) {
      return;
    }
    const timer = window.setTimeout(() => {
      setWakeDebug((prev) => {
        if (!prev) return null;
        return Date.now() - prev.ts >= 15000 ? null : prev;
      });
    }, 15200);
    return () => window.clearTimeout(timer);
  }, [wakeDebug]);

  const handleMediaToggle = useCallback(
    async (type: "video" | "audio", enabled: boolean) => {
      const prev = { ...mediaState };
      const next = {
        ...mediaState,
        videoEnabled: type === "video" ? enabled : mediaState.videoEnabled,
        audioEnabled: type === "audio" ? enabled : mediaState.audioEnabled,
      };
      setMediaState(next);
      localStorage.setItem("media_video", String(next.videoEnabled));
      localStorage.setItem("media_audio", String(next.audioEnabled));
      if (isGuest) return;
      try {
        await sendEngineSignal("config_update", {
          video_enabled: next.videoEnabled,
          audio_enabled: next.audioEnabled,
          camera_enabled: next.videoEnabled,
          mic_enabled: next.audioEnabled,
        });
      } catch (err) {
        console.error("Media update failed:", err);
        setMediaState(prev);
        localStorage.setItem("media_video", String(prev.videoEnabled));
        localStorage.setItem("media_audio", String(prev.audioEnabled));
        throw err;
      }
    },
    [mediaState, isGuest]
  );

  const handleCareDeliveryStrategyChange = useCallback(
    async (strategy: CareDeliveryStrategy) => {
      const next = normalizeCareDeliveryStrategy(strategy);
      const prev = careDeliveryStrategy;
      setCareDeliveryStrategy(next);
      localStorage.setItem("care_delivery_strategy", next);
      if (isGuest) return;
      try {
        await sendEngineSignal("config_update", { care_delivery_strategy: next });
      } catch (err) {
        console.error("Care delivery strategy update failed:", err);
        setCareDeliveryStrategy(prev);
        localStorage.setItem("care_delivery_strategy", prev);
        throw err;
      }
    },
    [careDeliveryStrategy, isGuest]
  );

  const handleLogin = useCallback(
    (result: LoginResult) => {
      setIsGuest(false);
      setIsAuthenticated(true);
      setAuthChecked(true);
      localStorage.removeItem("guest_mode");
      localStorage.setItem("activation_required", result.activation_required ? "true" : "false");
      localStorage.setItem("activation_path", result.activation_path || "/activate");
      setActivationRequired(Boolean(result.activation_required));
      setActivationPath(result.activation_path || "/activate");
      setActiveTab(Tab.DASHBOARD);
    },
    []
  );

  const handleGuest = useCallback(() => {
    localStorage.setItem("guest_mode", "true");
    localStorage.removeItem("activation_required");
    localStorage.removeItem("activation_path");
    setIsGuest(true);
    setIsAuthenticated(true);
    setActivationRequired(false);
    setActivationPath("/activate");
    setAuthChecked(true);
    setActiveTab(Tab.DASHBOARD);
  }, []);

  const handleLogout = useCallback(async () => {
    if (isGuest) {
      localStorage.removeItem("guest_mode");
      localStorage.removeItem("activation_required");
      localStorage.removeItem("activation_path");
      localStorage.removeItem("profile_name");
      localStorage.removeItem("profile_avatar");
      localStorage.removeItem("profile_bio");
      localStorage.removeItem("profile_location");
      localStorage.removeItem("profile_username");
      localStorage.removeItem("profile_created_at");
      localStorage.removeItem("profile_updated_at");
      setIsGuest(false);
      setIsAuthenticated(false);
      setActivationRequired(false);
      setActivationPath("/activate");
      setAuthChecked(true);
      return;
    }
    try {
      await logoutSession();
    } catch (err) {
      console.warn("logout failed:", err);
    } finally {
      localStorage.removeItem("auth_token");
      localStorage.removeItem("refresh_token");
      localStorage.removeItem("guest_mode");
      localStorage.removeItem("activation_required");
      localStorage.removeItem("activation_path");
      localStorage.removeItem("profile_name");
      localStorage.removeItem("profile_avatar");
      localStorage.removeItem("profile_bio");
      localStorage.removeItem("profile_location");
      localStorage.removeItem("profile_username");
      localStorage.removeItem("profile_created_at");
      localStorage.removeItem("profile_updated_at");
      setIsAuthenticated(false);
      setIsGuest(false);
      setActivationRequired(false);
      setActivationPath("/activate");
      setAuthChecked(true);
    }
  }, [isGuest]);

  const handleActivationCompleted = useCallback(async () => {
    const activation = await getActivationState();
    if (activation.activation_required) {
      throw new Error("激活尚未完成，请先在页面中确认身份信息。");
    }
    localStorage.setItem("activation_required", "false");
    setActivationRequired(false);
  }, []);

  const handlePickAvatar = () => {
    fileInputRef.current?.click();
  };

  const handleAvatarFile = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result ? String(reader.result) : "";
      setProfileDraftAvatar(result);
    };
    reader.readAsDataURL(file);
    event.target.value = "";
  };

  const handleAvatarAuto = () => {
    const seed = `${profileDraftName || "User"}-${Date.now()}`;
    setProfileDraftAvatar(
      `https://api.dicebear.com/7.x/thumbs/svg?seed=${encodeURIComponent(seed)}`
    );
  };

  const handleProfileReset = () => {
    setProfileDraftName("共鸣旅人");
    setProfileDraftAvatar("");
    setProfileDraftBio("");
    setProfileDraftLocation("");
  };

  const handleProfileSave = useCallback(async () => {
    setProfileSaving(true);
    setProfileError("");
    try {
      if (isGuest) {
        setProfileName(profileDraftName || "共鸣旅人");
        setProfileAvatar(profileDraftAvatar);
        setProfileBio(profileDraftBio || "");
        setProfileLocation(profileDraftLocation || "");
        localStorage.setItem("profile_name", profileDraftName || "共鸣旅人");
        localStorage.setItem("profile_avatar", profileDraftAvatar);
        localStorage.setItem("profile_bio", profileDraftBio || "");
        localStorage.setItem("profile_location", profileDraftLocation || "");
        return;
      }
      const updated = await updateUserProfile({
        display_name: profileDraftName,
        avatar_url: profileDraftAvatar || null,
        bio: profileDraftBio || null,
        location: profileDraftLocation || null,
      });
      setProfileName(updated.display_name || profileDraftName);
      setProfileAvatar(updated.avatar_url || profileDraftAvatar);
      setProfileBio(updated.bio || profileDraftBio || "");
      setProfileLocation(updated.location || profileDraftLocation || "");
      setProfileUsername(updated.username || profileUsername);
      setProfileCreatedAt(updated.created_at || profileCreatedAt);
      setProfileUpdatedAt(updated.updated_at || Math.floor(Date.now() / 1000));
      localStorage.setItem("profile_name", updated.display_name || profileDraftName);
      localStorage.setItem("profile_avatar", updated.avatar_url || profileDraftAvatar);
      localStorage.setItem("profile_bio", updated.bio || profileDraftBio || "");
      localStorage.setItem("profile_location", updated.location || profileDraftLocation || "");
      localStorage.setItem("profile_username", updated.username || profileUsername || "");
      if (updated.created_at) localStorage.setItem("profile_created_at", String(updated.created_at));
      if (updated.updated_at) localStorage.setItem("profile_updated_at", String(updated.updated_at));
    } catch (err) {
      console.error("Profile update failed:", err);
      setProfileError("保存失败，请稍后重试");
    } finally {
      setProfileSaving(false);
    }
  }, [
    isGuest,
    profileCreatedAt,
    profileDraftAvatar,
    profileDraftBio,
    profileDraftLocation,
    profileDraftName,
    profileUsername,
  ]);

  const addTask = () => {
    const value = taskInput.trim();
    if (!value) return;
    const newTask: TaskItem = {
      id: `task-${Date.now()}`,
      title: value,
      done: false,
      minutes: Number.isFinite(taskMinutes) && taskMinutes > 0 ? taskMinutes : 25,
    };
    setTasks((prev) => [newTask, ...prev]);
    setTaskInput("");
    setTaskMinutes(25);
    pushToast("新增任务", value);
  };

  const toggleTask = (id: string) => {
    setTasks((prev) =>
      prev.map((task) => {
        if (task.id !== id) return task;
        const next = { ...task, done: !task.done };
        pushToast(next.done ? "任务完成" : "任务恢复", next.title);
        return next;
      })
    );
  };

  const deleteTask = (id: string) => {
    setTasks((prev) => prev.filter((task) => task.id !== id));
  };

  const formatTime = (totalSeconds: number) => {
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  };

  const toggleThemeMenu = () => {
    setThemeMenuOpen((prev) => !prev);
  };

  const selectTheme = (themeId: string) => {
    setUiTheme(themeId);
    persistTheme(themeId);
    setThemeMenuOpen(false);
  };

  const previewTheme = (themeId: string) => {
    setUiTheme(themeId);
  };

  const finalizeThemeSelection = () => {
    persistTheme(uiTheme);
    setThemeOnboardingOpen(false);
  };

  const playPomodoroSound = () => {
    try {
      const AudioContextClass =
        (window as any).AudioContext || (window as any).webkitAudioContext;
      if (!AudioContextClass) return;
      const ctx = new AudioContextClass();
      const oscillator = ctx.createOscillator();
      const gain = ctx.createGain();
      oscillator.type = "sine";
      oscillator.frequency.value = 880;
      gain.gain.value = 0.08;
      oscillator.connect(gain);
      gain.connect(ctx.destination);
      oscillator.start();
      oscillator.stop(ctx.currentTime + 0.25);
      oscillator.onended = () => ctx.close();
    } catch (err) {
      console.warn("pomodoro sound failed:", err);
    }
  };

  useEffect(() => {
    let active = true;
    const guest = localStorage.getItem("guest_mode") === "true";
    if (guest) {
      setIsGuest(true);
      setIsAuthenticated(true);
      setAuthChecked(true);
      return () => {
        active = false;
      };
    }
    const token = localStorage.getItem("auth_token");
    if (!token) {
      setIsAuthenticated(false);
      setAuthChecked(true);
      return () => {
        active = false;
      };
    }
    validateSession()
      .then(async () => {
        if (!active) return;
        try {
          const activation = await getActivationState();
          if (!active) return;
          setActivationRequired(Boolean(activation.activation_required));
          setActivationPath(localStorage.getItem("activation_path") || "/activate");
          localStorage.setItem(
            "activation_required",
            activation.activation_required ? "true" : "false"
          );
        } catch (err) {
          console.warn("activation state load failed:", err);
        }
        setIsAuthenticated(true);
      })
      .catch((err) => {
        console.warn("Session invalid:", err);
        if (!active) return;
        localStorage.removeItem("auth_token");
        localStorage.removeItem("refresh_token");
        localStorage.removeItem("guest_mode");
        localStorage.removeItem("activation_required");
        localStorage.removeItem("activation_path");
        setIsAuthenticated(false);
        setIsGuest(false);
        setActivationRequired(false);
        setActivationPath("/activate");
      })
      .finally(() => {
        if (active) setAuthChecked(true);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    applyTheme(uiTheme);
    const option = THEME_OPTIONS.find((item) => item.id === uiTheme) || THEME_OPTIONS[0];
    const token = THEME_TOKENS[uiTheme] || THEME_TOKENS.midnight;
    (window as any)?.desktop?.setTitleBarTheme?.({
      color: option.titleBarColor,
      symbolColor: option.symbolColor,
      backgroundColor: token.bg,
    });
  }, [applyTheme, uiTheme]);

  useEffect(() => {
    if (typeof document === "undefined") return;
    const isFloat = isFloatWidget || isFloatChat;
    document.body.classList.toggle("float-mode", isFloat);
  }, [isFloatWidget, isFloatChat]);

  useEffect(() => {
    if (!themeMenuOpen) return;
    const handler = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!themeMenuRef.current?.contains(target)) {
        setThemeMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [themeMenuOpen]);

  useEffect(() => {
    if (!(window as any)?.desktop?.onNavigate) return;
    const dispose = (window as any).desktop.onNavigate((tab: string) => {
      if (Object.values(Tab).includes(tab as Tab)) {
        setActiveTab(tab as Tab);
      }
    });
    return () => {
      if (dispose) dispose();
    };
  }, []);

  useEffect(() => {
    const desktopApi = (window as any)?.desktop;
    if (!desktopApi?.setBackendSession || !desktopApi?.clearBackendSession) return;
    const token = localStorage.getItem("auth_token");
    if (!isAuthenticated || isGuest || !token) {
      desktopApi.clearBackendSession().catch(() => undefined);
      return;
    }
    desktopApi
      .setBackendSession({
        apiBase: getDeviceSyncApiBase(),
        token,
        deviceId: deviceStatus?.device_id || undefined,
      })
      .catch((err: unknown) => console.warn("desktop backend session sync failed:", err));
  }, [deviceStatus?.device_id, isAuthenticated, isGuest]);

  useEffect(() => {
    if (!isAuthenticated || isGuest) return;
    let active = true;
    getUserProfile()
      .then((profile) => {
        if (!active) return;
        const displayName = profile.display_name || profile.username || "共鸣旅人";
        const avatarUrl = profile.avatar_url || "";
        const bio = profile.bio || "";
        const location = profile.location || "";
        setProfileName(displayName);
        setProfileAvatar(avatarUrl);
        setProfileBio(bio);
        setProfileLocation(location);
        setProfileUsername(profile.username || "");
        setProfileCreatedAt(profile.created_at || null);
        setProfileUpdatedAt(profile.updated_at || null);
        setProfileDraftName(displayName);
        setProfileDraftAvatar(avatarUrl);
        setProfileDraftBio(bio);
        setProfileDraftLocation(location);
        localStorage.setItem("profile_name", displayName);
        localStorage.setItem("profile_avatar", avatarUrl);
        localStorage.setItem("profile_bio", bio);
        localStorage.setItem("profile_location", location);
        localStorage.setItem("profile_username", profile.username || "");
        if (profile.created_at) localStorage.setItem("profile_created_at", String(profile.created_at));
        if (profile.updated_at) localStorage.setItem("profile_updated_at", String(profile.updated_at));
      })
      .catch((err) => {
        console.warn("profile fetch failed:", err);
      });
    return () => {
      active = false;
    };
  }, [isAuthenticated, isGuest]);

  useEffect(() => {
    if (!isAuthenticated || isGuest) return;
    let active = true;
    getChatHistory()
      .then((history) => {
        if (!active) return;
        setMessages(history);
      })
      .catch((err) => console.warn("chat history fetch failed:", err));
    return () => {
      active = false;
    };
  }, [isAuthenticated, isGuest]);

  useEffect(() => {
    if (!isAuthenticated || isGuest) return;
    let active = true;
    const fetchScores = async () => {
      try {
        const detailData = await getRealtimeRiskDetail();
        if (!active) return;
        setScores({ V: Number(detailData.V || 0), A: Number(detailData.A || 0), T: Number(detailData.T || 0), S: Number(detailData.S || 0) });
        if (detailData.detail && typeof detailData.detail === "object") {
          setRiskDetail({
            V_sub: (detailData.detail.V_sub as Record<string, number>) || {},
            A_sub: (detailData.detail.A_sub as Record<string, number>) || {},
            T_sub: (detailData.detail.T_sub as Record<string, any>) || {},
          });
        }
        setRiskUpdatedAt(Number(detailData.timestamp_ms || Date.now()));
        setRiskSource("poll");
      } catch (err) {
        try {
          const data = await getRealtimeScores();
          if (!active) return;
          setScores(data);
          setRiskUpdatedAt(Date.now());
          setRiskSource("poll");
        } catch (innerErr) {
          console.warn("scores fetch failed:", innerErr);
        }
      }
    };
    fetchScores();
    const timer = window.setInterval(fetchScores, 4000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [isAuthenticated, isGuest]);

  useEffect(() => {
    if (!isAuthenticated || isGuest) return;
    let active = true;
    const fetchHistory = async () => {
      try {
        const data = await getEmotionHistory();
        if (!active) return;
        setEvents(data);
      } catch (err) {
        console.warn("history fetch failed:", err);
      }
    };
    fetchHistory();
    const timer = window.setInterval(fetchHistory, 30000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [isAuthenticated, isGuest]);

  useEffect(() => {
    if (!isAuthenticated || isGuest) return;
    fetchDeviceStatus();
    const timer = window.setInterval(fetchDeviceStatus, 8000);
    return () => window.clearInterval(timer);
  }, [fetchDeviceStatus, isAuthenticated, isGuest]);

  useEffect(() => {
    if (!isAuthenticated || isGuest) return;
    const ws = connectEventStream(
      (event) => {
        handleEngineEvent(event);
        if (event.type === "RiskUpdate") {
          const now = Date.now();
          if (now - lastRiskLogRef.current > 15000) {
            lastRiskLogRef.current = now;
          }
        }
      },
      () => setWsConnected(false)
    );
    wsRef.current = ws;
    ws.onopen = () => setWsConnected(true);
    ws.onclose = () => {
      setWsConnected(false);
      setVoiceState("idle");
    };
    return () => {
      ws.close();
      wsRef.current = null;
      setVoiceState("idle");
    };
  }, [handleEngineEvent, isAuthenticated, isGuest]);

  useEffect(() => {
    localStorage.setItem("focus_tasks", JSON.stringify(tasks));
  }, [tasks]);

  useEffect(() => {
    localStorage.setItem("pomo_work_min", String(pomodoroWorkMin));
    localStorage.setItem("pomo_break_min", String(pomodoroBreakMin));
    localStorage.setItem("pomo_rounds", String(pomodoroRounds));
  }, [pomodoroBreakMin, pomodoroWorkMin, pomodoroRounds]);

  useEffect(() => {
    localStorage.setItem("media_video", String(mediaState.videoEnabled));
    localStorage.setItem("media_audio", String(mediaState.audioEnabled));
  }, [mediaState.audioEnabled, mediaState.videoEnabled]);

  useEffect(() => {
    localStorage.setItem("face_track_overlay", String(faceTrackOverlayEnabled));
  }, [faceTrackOverlayEnabled]);

  useEffect(() => {
    localStorage.setItem("persona_profile_id", selectedPersonaId);
  }, [selectedPersonaId]);

  useEffect(() => {
    if (!isAuthenticated || isGuest) return;
    sendEngineSignal("config_update", { care_delivery_strategy: careDeliveryStrategy }).catch((err) => {
      console.error("Initial care delivery strategy sync failed:", err);
    });
  }, [isAuthenticated, isGuest]);

  useEffect(() => {
    if (!pomodoroRunning) return;
    const timer = window.setInterval(() => {
      setPomodoroSeconds((prev) => {
        if (prev <= 1) {
          if (pomodoroMode === "work") {
            const nextMode = "break";
            setPomodoroMode(nextMode);
            playPomodoroSound();
            pushToast("休息一下", "番茄钟已切换阶段");
            return pomodoroBreakMin * 60;
          }
          const nextRound = pomodoroRound + 1;
          if (nextRound > pomodoroRounds) {
            setPomodoroRunning(false);
            setPomodoroMode("work");
            setPomodoroRound(1);
            playPomodoroSound();
            pushToast("完成一轮", `已完成 ${pomodoroRounds} 轮专注`);
            return pomodoroWorkMin * 60;
          }
          setPomodoroRound(nextRound);
          setPomodoroMode("work");
          playPomodoroSound();
          pushToast("开始专注", `第 ${nextRound} 轮`);
          return pomodoroWorkMin * 60;
        }
        return prev - 1;
      });
    }, 1000);
    return () => window.clearInterval(timer);
  }, [
    pomodoroRunning,
    pomodoroMode,
    pomodoroWorkMin,
    pomodoroBreakMin,
    pomodoroRound,
    pomodoroRounds,
    pushToast,
  ]);

  useEffect(() => {
    if (pomodoroRunning) return;
    const seconds = (pomodoroMode === "work" ? pomodoroWorkMin : pomodoroBreakMin) * 60;
    setPomodoroSeconds(seconds);
  }, [pomodoroBreakMin, pomodoroMode, pomodoroRunning, pomodoroWorkMin]);

  useEffect(() => {
    if (!carePopup) return;
    const timer = window.setTimeout(() => setCarePopup(null), 10000);
    return () => window.clearTimeout(timer);
  }, [carePopup]);

  useEffect(() => {
    if (!weeklySummaryPopup) return;
    const timer = window.setTimeout(() => setWeeklySummaryPopup(null), 12000);
    return () => window.clearTimeout(timer);
  }, [weeklySummaryPopup]);

  useEffect(() => {
    if (!isAuthenticated || isGuest) return;
    if (isFloatWidget || isFloatChat) return;
    maybeTriggerWeeklySummary();
    const timer = window.setInterval(maybeTriggerWeeklySummary, 30 * 60 * 1000);
    return () => window.clearInterval(timer);
  }, [isAuthenticated, isGuest, isFloatWidget, isFloatChat, maybeTriggerWeeklySummary]);

  const handleFloatPointerDown = (event: React.PointerEvent<HTMLButtonElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    const rect = event.currentTarget.getBoundingClientRect();
    floatPointerRef.current = {
      screenX: event.screenX,
      screenY: event.screenY,
      clientX: event.clientX - rect.left,
      clientY: event.clientY - rect.top,
    };
    floatDragRef.current.hasDragged = false;
    if (dragTimerRef.current) {
      clearTimeout(dragTimerRef.current);
    }
    dragTimerRef.current = window.setTimeout(() => {
      floatDragRef.current.active = true;
      floatDragRef.current.hasDragged = true;
      suppressClickRef.current = true;
      const { screenX, screenY, clientX, clientY } = floatPointerRef.current;
      (window as any).desktop?.startFloatDrag?.({
        screenX,
        screenY,
        offsetX: clientX,
        offsetY: clientY,
      });
      setFloatDragging(true);
    }, 160);
  };

  const handleFloatPointerMove = (event: React.PointerEvent<HTMLButtonElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    floatPointerRef.current = {
      screenX: event.screenX,
      screenY: event.screenY,
      clientX: event.clientX - rect.left,
      clientY: event.clientY - rect.top,
    };
    if (!floatDragRef.current.active) return;
    (window as any).desktop?.updateFloatDrag?.({
      screenX: event.screenX,
      screenY: event.screenY,
    });
  };

  const handleFloatPointerUp = (event: React.PointerEvent<HTMLButtonElement>) => {
    if (dragTimerRef.current) {
      clearTimeout(dragTimerRef.current);
      dragTimerRef.current = null;
    }
    if (floatDragRef.current.active) {
      floatDragRef.current.active = false;
      (window as any).desktop?.endFloatDrag?.();
    }
    (window as any).desktop?.setFloatInteractive?.(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    setFloatDragging(false);
  };

  const handleFloatPointerCancel = (event: React.PointerEvent<HTMLButtonElement>) => {
    if (dragTimerRef.current) {
      clearTimeout(dragTimerRef.current);
      dragTimerRef.current = null;
    }
    floatDragRef.current.active = false;
    (window as any).desktop?.endFloatDrag?.();
    (window as any).desktop?.setFloatInteractive?.(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    setFloatDragging(false);
  };

  const handleFloatClick = () => {
    if (suppressClickRef.current) {
      suppressClickRef.current = false;
      return;
    }
    (window as any).desktop?.toggleFloatChat?.();
  };

  const todayEmotionRecords = events
    .filter((event) => isSameLocalDay(event.timestamp, new Date()))
    .filter((event) => {
      const text = String(event.description || "").trim().toLowerCase();
      if (!text) return false;
      if (text.startsWith("event:")) return false;
      if (text.includes("triggercandidate") || text.includes("a_peak")) return false;
      return true;
    })
    .sort((a, b) => b.timestamp.getTime() - a.timestamp.getTime());

  const resolvedAvatar = profileAvatar
    ? profileAvatar
    : `https://api.dicebear.com/7.x/thumbs/svg?seed=${encodeURIComponent(
        profileName || "User"
      )}`;

  if (isFloatWidget) {
    return (
      <div className="w-screen h-screen flex items-center justify-center">
        <div className="float-widget-shell">
          <button
            onPointerDown={handleFloatPointerDown}
            onPointerMove={handleFloatPointerMove}
            onPointerUp={handleFloatPointerUp}
            onPointerCancel={handleFloatPointerCancel}
            onClick={handleFloatClick}
            onPointerEnter={() => (window as any).desktop?.setFloatInteractive?.(true)}
            onPointerLeave={() => (window as any).desktop?.setFloatInteractive?.(false)}
            className={`float-widget-button ${floatDragging ? "float-widget-button--dragging" : ""}`}
          >
            <img src={APP_ICON_URL} alt="app icon" className="w-full h-full object-cover rounded-[16px]" />
          </button>
        </div>
      </div>
    );
  }

  if (isFloatChat) {
    return (
      <div className="w-screen h-screen flex items-end justify-center p-3">
        <div className="float-chat-panel">
          <div className="float-chat-header">
            <div className="flex items-center gap-2">
              <div className="float-chat-dot"></div>
              <span className="text-[11px] font-black tracking-[0.3em] uppercase">Care</span>
            </div>
            <button
              onClick={() => (window as any).desktop?.toggleFloatChat?.()}
              className="float-chat-close"
            >
              <X size={14} />
            </button>
          </div>
          {!authChecked ? (
            <div className="flex-1 flex items-center justify-center text-xs text-slate-300">
              正在连接引擎...
            </div>
          ) : !isAuthenticated ? (
            <div className="flex-1 flex flex-col items-center justify-center p-6 text-xs text-center text-slate-300">
              请先在主窗口登录，再开启悬浮对话。
              <div className="mt-4">
                <button
                  onClick={() => (window as any).desktop?.openMainTab?.(Tab.PROFILE)}
                  className="theme-button px-4 py-2 rounded-full text-[10px] font-black uppercase tracking-widest"
                >
                  打开主窗口
                </button>
              </div>
            </div>
          ) : (
            <div className="flex-1 min-h-0">
              <ChatInterface
                currentEmotion={scores.S > 0.5 ? EmotionType.ANXIOUS : EmotionType.CALM}
                initialMessages={messages}
                onSendMessage={handleChatUpdate}
                isGuest={isGuest}
                variant="compact"
                voiceState={voiceState}
                expressionLabel={expressionLabelForChat}
                expressionConfidence={expressionConfidenceForChat}
              />
            </div>
          )}
        </div>
      </div>
    );
  }

  if (!authChecked) {
    return (
      <div
        style={{
          width: "100vw",
          height: "100vh",
          background: "#070b14",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "#94A3B8",
          fontSize: "12px",
        }}
      >
        正在校验登录...
      </div>
    );
  }

  if (!isAuthenticated) return <Login onLogin={handleLogin} onGuest={handleGuest} />;

  if (activationRequired && !isGuest) {
    const token = localStorage.getItem("auth_token") || "";
    return (
      <ActivationGate
        activationPath={activationPath}
        backendBase={getDeviceSyncApiBase() || getApiBase()}
        token={token}
        onActivated={handleActivationCompleted}
      />
    );
  }

  return (
    <div className="w-screen h-screen bg-[#070b14] flex overflow-hidden font-sans text-slate-200">
      {triggerToasts.length > 0 && (
        <div className="absolute top-6 left-8 z-20 space-y-3">
          {triggerToasts.map((toast) => (
            <div
              key={toast.id}
              className="bg-slate-900/80 border border-white/10 rounded-2xl px-4 py-3 shadow-xl backdrop-blur-2xl max-w-xs"
            >
              <div className="text-[9px] font-black uppercase tracking-[0.3em] text-indigo-300">
                {toast.title}
              </div>
              <div className="text-[11px] text-slate-200 mt-1 line-clamp-2">{toast.detail}</div>
            </div>
          ))}
        </div>
      )}
      {themeOnboardingOpen && (
        <div className="absolute inset-0 z-30 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div
            className="w-[520px] max-w-[90vw] rounded-[2rem] p-6 border shadow-2xl"
            style={{ background: "var(--panel-bg-strong)", borderColor: "var(--panel-border)" }}
          >
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-sm font-black">选择你喜欢的配色</h3>
                <p className="text-[10px] mt-1" style={{ color: "var(--theme-muted)" }}>
                  点击即可实时预览
                </p>
              </div>
              <Palette size={18} />
            </div>
            <div className="grid grid-cols-2 gap-3 max-h-72 overflow-y-auto pr-1">
              {THEME_OPTIONS.map((theme) => (
                <button
                  key={theme.id}
                  onClick={() => previewTheme(theme.id)}
                  className={`flex items-center justify-between gap-2 px-3 py-3 rounded-xl text-xs font-bold transition-all ${
                    uiTheme === theme.id ? "bg-white/10" : "bg-white/5 hover:bg-white/10"
                  }`}
                  style={{ border: "1px solid var(--panel-border)", color: "var(--theme-text)" }}
                >
                  <span>{theme.label}</span>
                  <span className="flex items-center gap-1">
                    {theme.swatch.map((color) => (
                      <span
                        key={color}
                        className="w-3 h-3 rounded-full border"
                        style={{ background: color, borderColor: "var(--panel-border)" }}
                      />
                    ))}
                  </span>
                </button>
              ))}
            </div>
            <div className="mt-5 flex justify-end">
              <button
                onClick={finalizeThemeSelection}
                className="theme-button px-4 py-2 rounded-full text-[10px] font-black uppercase tracking-widest"
              >
                开始使用
              </button>
            </div>
          </div>
        </div>
      )}
      {carePopup && (
        <div className="absolute top-6 right-8 z-20 max-w-sm animate-pop-in">
          <div className="bg-white/90 text-slate-900 rounded-3xl shadow-2xl p-6 border border-white/40">
            <div className="text-xs font-black uppercase tracking-[0.3em] text-slate-500 mb-2">
              主动关怀
            </div>
            <div className="text-sm font-bold leading-relaxed">{carePopup.text}</div>
            {carePopup.followup_question && (
              <div className="text-sm font-semibold mt-3 text-slate-600">
                {carePopup.followup_question}
              </div>
            )}
            <div className="mt-4 flex justify-end">
              <button
                onClick={() => setCarePopup(null)}
                className="text-xs font-black text-slate-600 hover:text-slate-900 transition-colors"
              >
                关闭
              </button>
            </div>
          </div>
        </div>
          )}
      {weeklySummaryPopup && (
        <div className="absolute top-6 right-8 z-20 max-w-md animate-pop-in">
          <div className="bg-white/95 text-slate-900 rounded-3xl shadow-2xl p-6 border border-white/40">
            <div className="text-xs font-black uppercase tracking-[0.3em] text-slate-500 mb-2">
              每周总结
            </div>
            <div className="text-sm font-semibold leading-relaxed whitespace-pre-line">
              {weeklySummaryPopup}
            </div>
            <div className="mt-4 flex justify-end">
              <button
                onClick={() => setWeeklySummaryPopup(null)}
                className="text-xs font-black text-slate-600 hover:text-slate-900 transition-colors"
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}

      <nav className="w-20 bg-[#0a0f1d] border-r border-white/[0.03] flex flex-col items-center py-10 gap-8 z-20">
        <NavButton
          active={activeTab === Tab.DASHBOARD}
          onClick={() => setActiveTab(Tab.DASHBOARD)}
          icon={LayoutDashboard}
        />
        <NavButton
          active={activeTab === Tab.CHAT}
          onClick={() => setActiveTab(Tab.CHAT)}
          icon={MessageSquareHeart}
        />
        <NavButton
          active={activeTab === Tab.PERSONA}
          onClick={() => setActiveTab(Tab.PERSONA)}
          icon={UserRound}
        />
        <NavButton
          active={activeTab === Tab.FOCUS}
          onClick={() => setActiveTab(Tab.FOCUS)}
          icon={ListChecks}
        />
        <NavButton
          active={activeTab === Tab.DEVICE}
          onClick={() => setActiveTab(Tab.DEVICE)}
          icon={Activity}
        />
        <NavButton
          active={activeTab === Tab.CONTROL}
          onClick={() => setActiveTab(Tab.CONTROL)}
          icon={Settings}
        />
        <button onClick={() => setActiveTab(Tab.PROFILE)} className="mt-auto group">
          <div
            className={`w-10 h-10 rounded-full border overflow-hidden ring-2 transition ${
              activeTab === Tab.PROFILE
                ? "border-indigo-400 ring-indigo-400/30"
                : "border-indigo-500/30 ring-indigo-500/10"
            }`}
          >
            <img src={resolvedAvatar} alt="avatar" className="w-full h-full object-cover" />
          </div>
        </button>
      </nav>

      <section className="flex-1 flex flex-col px-10 pb-10 relative min-h-0">
        <header className="h-32 flex items-center justify-between" style={{ WebkitAppRegion: "drag" }}>
          <div className="flex items-center gap-3 animate-pop-in">
            <div className="text-indigo-400 relative">
              <img src={APP_ICON_URL} alt="app icon" className="w-6 h-6 object-cover rounded-md opacity-90" />
              <div className="absolute -top-1 -right-1 w-1.5 h-1.5 bg-indigo-400 rounded-full animate-pulse"></div>
            </div>
            <div className="flex flex-col">
              <h1 className="text-[12px] font-black uppercase tracking-[0.6em] text-white/50 leading-none">
                心念双灵
              </h1>
              <span className="text-[9px] font-bold tracking-[0.4em] text-white/20 mt-1">
                EMORESONANCE V2.5
              </span>
            </div>
          </div>

          <div className="flex items-center gap-6" style={{ WebkitAppRegion: "no-drag" }}>
            <div className="theme-pill flex items-center gap-3 px-4 py-2 backdrop-blur-xl rounded-full">
              <div className={`status-dot animate-pulse ${wsConnected ? "" : "status-dot--offline"}`}></div>
              <span className="text-[9px] font-black uppercase tracking-widest">
                {wsConnected ? "ENGINE ONLINE" : "ENGINE OFFLINE"}
              </span>
            </div>
            <div
              className={`theme-pill flex items-center gap-2 px-3 py-2 backdrop-blur-xl rounded-full border ${
                voiceStateActive ? "border-cyan-400/40 text-cyan-200" : "border-white/10 text-slate-400"
              }`}
            >
              <span
                className={`inline-block h-1.5 w-1.5 rounded-full ${
                  voiceStateActive ? "bg-cyan-300 animate-pulse" : "bg-slate-500"
                }`}
              />
              <span className="text-[9px] font-black uppercase tracking-widest">VOICE {voiceStateLabel}</span>
            </div>
            <div className="relative z-40" ref={themeMenuRef}>
              <button
                onClick={toggleThemeMenu}
                className="theme-button flex items-center gap-2 px-3 py-2 rounded-full text-[9px] font-black uppercase tracking-widest transition-all"
                style={{ WebkitAppRegion: "no-drag" }}
              >
                <Palette size={14} />
                <span>{THEME_OPTIONS.find((item) => item.id === uiTheme)?.label || "主题"}</span>
              </button>
              {themeMenuOpen && (
                <div
                  className="absolute right-0 mt-3 w-56 rounded-2xl p-3 backdrop-blur-2xl shadow-2xl border z-50"
                  style={{ background: "var(--panel-bg-strong)", borderColor: "var(--panel-border)" }}
                >
                  <div
                    className="text-[10px] font-black uppercase tracking-widest mb-2"
                    style={{ color: "var(--theme-muted)" }}
                  >
                    主题切换
                  </div>
                  <div className="max-h-64 overflow-y-auto space-y-2">
                    {THEME_OPTIONS.map((theme) => (
                      <button
                        key={theme.id}
                        onClick={() => selectTheme(theme.id)}
                        className={`w-full flex items-center justify-between gap-2 px-3 py-2 rounded-xl text-[10px] font-bold transition-all ${
                          uiTheme === theme.id ? "bg-white/10" : "bg-white/5 hover:bg-white/10"
                        }`}
                        style={{ border: "1px solid var(--panel-border)", color: "var(--theme-text)" }}
                      >
                        <span>{theme.label}</span>
                        <span className="flex items-center gap-1">
                          {theme.swatch.map((color) => (
                            <span
                              key={color}
                              className="w-3 h-3 rounded-full border"
                              style={{ background: color, borderColor: "var(--panel-border)" }}
                            />
                          ))}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
            <button className="p-2 theme-icon-button transition-all">
              <Bell size={18} />
            </button>
          </div>
        </header>

        {wakeDebug && (
          <div className="mb-3 px-4 py-2 rounded-2xl border border-cyan-400/30 bg-cyan-500/10 text-cyan-100 text-[11px] font-semibold flex items-center justify-between">
            <span>
              唤醒识别：{wakeDebug.text || "（无文本）"}
              <span className="ml-2 text-cyan-200/70">[{wakeDebug.reason}]</span>
            </span>
            <span className="text-[10px] text-cyan-200/70">just now</span>
          </div>
        )}

        <div className="flex-1 flex flex-col overflow-hidden min-h-0">
          {activeTab === Tab.DASHBOARD && (
            <div className="grid grid-cols-12 gap-6 h-full min-h-0 items-stretch">
              <div className="col-span-3 h-full">
                <AtmosphereView scores={scores} mode={mode} />
              </div>
              <div className="col-span-6 h-full">
                <MoodChart events={events} isGuest={isGuest} />
              </div>
              <div className="col-span-3 h-full bg-[#0c1222]/50 backdrop-blur-3xl rounded-[2.5rem] border border-white/[0.05] flex flex-col shadow-2xl overflow-hidden">
                <div className="p-6 border-b border-white/[0.03] flex justify-between items-center">
                  <div className="flex items-center gap-2">
                    <Terminal size={14} className="text-indigo-500" />
                    <h3 className="text-[10px] font-black text-slate-500 uppercase tracking-widest">
                      今日情绪记录
                    </h3>
                  </div>
                  <span className="text-[8px] font-black text-indigo-400/50">TODAY</span>
                </div>
                <div className="flex-1 overflow-y-auto p-4 no-scrollbar space-y-4">
                  {todayEmotionRecords.length === 0 && (
                    <div className="text-[11px] font-semibold text-slate-500 text-center py-8">
                      今天还没有情绪记录
                    </div>
                  )}
                  {todayEmotionRecords.map((event) => (
                    <div
                      key={event.id}
                      className="p-3 bg-white/[0.02] border border-white/[0.05] rounded-2xl group hover:bg-white/[0.04] transition-all"
                    >
                      <div className="flex justify-between items-start mb-1">
                        <div className="flex items-center gap-2">
                          <span className="text-[9px] font-black px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300">
                            {event.type}
                          </span>
                          <span className="text-[8px] font-bold text-slate-500">
                            {getDayPartLabel(event.timestamp)}
                          </span>
                        </div>
                        <span className="text-[8px] font-mono text-slate-600">
                          {event.timestamp.toLocaleTimeString([], {
                            hour: "2-digit",
                            minute: "2-digit",
                            second: "2-digit",
                          })}
                        </span>
                      </div>
                      <p className="text-[10px] text-slate-300 font-bold leading-tight line-clamp-2">
                        {event.description || "情绪已记录"}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {activeTab === Tab.CHAT && (
            <div className="h-full max-w-6xl mx-auto w-full">
              <ChatInterface
                currentEmotion={scores.S > 0.5 ? EmotionType.ANXIOUS : EmotionType.CALM}
                initialMessages={messages}
                onSendMessage={handleChatUpdate}
                isGuest={isGuest}
                voiceState={voiceState}
                expressionLabel={expressionLabelForChat}
                expressionConfidence={expressionConfidenceForChat}
              />
            </div>
          )}
          {activeTab === Tab.PERSONA && (
            <div className="h-full w-full overflow-y-auto pr-1 no-scrollbar">
              <div className="w-full max-w-6xl mx-auto animate-pop-in pb-6">
                <div className="bg-[#0c1222]/50 backdrop-blur-3xl rounded-[2.5rem] border border-white/[0.05] shadow-2xl p-8">
                  <div className="flex items-start justify-between gap-6">
                    <div>
                      <h3 className="text-2xl font-black text-white">人格与风格切换</h3>
                      <p className="mt-2 text-[12px] font-semibold text-slate-400">
                        为不同场景选择不同陪伴角色。当前版本先做软件端切换与展示。
                      </p>
                    </div>
                    <div className="min-w-[260px] bg-white/[0.03] border border-white/[0.08] rounded-2xl p-4">
                      <p className="text-[10px] uppercase tracking-widest text-slate-500 font-black">当前角色</p>
                      <p className="mt-2 text-lg font-black text-white">{selectedPersona.name}</p>
                      <p className="text-[11px] text-indigo-300 font-bold">{selectedPersona.title}</p>
                      <p className="mt-2 text-[11px] text-slate-400 font-semibold leading-relaxed">
                        {selectedPersona.vibe}
                      </p>
                    </div>
                  </div>

                  <div className="mt-6 grid grid-cols-1 lg:grid-cols-2 gap-6">
                    {PERSONA_PROFILES.map((persona) => {
                      const active = persona.id === selectedPersona.id;
                      return (
                        <button
                          key={persona.id}
                          onClick={() => setSelectedPersonaId(persona.id)}
                          className={`group text-left rounded-3xl overflow-hidden border transition-all ${
                            active
                              ? "border-indigo-400/60 shadow-[0_0_0_1px_rgba(129,140,248,0.35)]"
                              : "border-white/[0.08] hover:border-indigo-300/40"
                          }`}
                        >
                          <div className="relative h-52">
                            <img
                              src={persona.image}
                              alt={persona.name}
                              className="w-full h-full object-cover"
                              style={{ objectPosition: "center 24%" }}
                              loading="lazy"
                              referrerPolicy="no-referrer"
                            />
                            <div className="absolute inset-0 bg-gradient-to-t from-[#090c18]/95 via-[#090c18]/30 to-transparent" />
                            <div className="absolute left-4 right-4 bottom-4">
                              <div className="flex items-center justify-between gap-3">
                                <div>
                                  <p className="text-lg font-black text-white">{persona.name}</p>
                                  <p className="text-[11px] font-bold text-indigo-200">{persona.title}</p>
                                </div>
                                {active && <CheckCircle2 size={18} className="text-indigo-300 shrink-0" />}
                              </div>
                            </div>
                          </div>
                          <div className="p-4 bg-[#0b1020]/80">
                            <p className="text-[11px] text-slate-300 font-semibold leading-relaxed">
                              {persona.intro}
                            </p>
                            <div className="mt-3 flex flex-wrap gap-2">
                              <span className="px-2 py-1 rounded-full text-[10px] font-bold bg-indigo-500/15 text-indigo-200 border border-indigo-400/20">
                                {persona.voiceStyle}
                              </span>
                              {persona.traits.map((trait) => (
                                <span
                                  key={`${persona.id}-${trait}`}
                                  className="px-2 py-1 rounded-full text-[10px] font-bold bg-white/[0.04] text-slate-300 border border-white/[0.08]"
                                >
                                  {trait}
                                </span>
                              ))}
                            </div>
                          </div>
                        </button>
                      );
                    })}
                  </div>

                  <div className="mt-5 text-[11px] text-slate-500 font-bold">
                    软件端已支持角色预览与切换，后续可再联动话术/动作策略。
                  </div>
                </div>
              </div>
            </div>
          )}
          {activeTab === Tab.FOCUS && (
            <div className="h-full w-full grid grid-cols-12 gap-6">
              <div className="col-span-5 bg-[#0c1222]/50 backdrop-blur-3xl rounded-[2.5rem] border border-white/[0.05] p-8 shadow-2xl flex flex-col">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-lg font-black text-white">番茄钟</h3>
                    <p className="text-[11px] text-slate-500 font-bold mt-1">可编辑工作 / 休息时长</p>
                  </div>
                  <div className="text-[10px] font-black uppercase tracking-widest text-indigo-300 flex items-center gap-2">
                    <span>{pomodoroMode === "work" ? "WORK" : "BREAK"}</span>
                    <span className="text-white/40">•</span>
                    <span>
                      第 {pomodoroRound} / {pomodoroRounds} 轮
                    </span>
                  </div>
                </div>
                <div className="mt-10 text-center">
                  <div className="text-5xl font-black tracking-widest">{formatTime(pomodoroSeconds)}</div>
                  <div className="text-[10px] text-slate-500 font-bold mt-2">
                    {pomodoroMode === "work" ? "专注中" : "休息中"}
                  </div>
                </div>
                <div className="mt-8 grid grid-cols-3 gap-4">
                  <div className="space-y-2">
                    <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest">
                      工作时长 (min)
                    </label>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => setPomodoroWorkMin((prev) => Math.max(5, prev - 5))}
                        className="p-2 rounded-xl bg-white/5 border border-white/10"
                      >
                        <Minus size={14} />
                      </button>
                      <input
                        type="number"
                        value={pomodoroWorkMin}
                        min={5}
                        max={90}
                        onChange={(e) => setPomodoroWorkMin(Number(e.target.value))}
                        className="flex-1 bg-white/5 border border-white/10 rounded-xl p-2 text-xs font-mono font-bold text-indigo-300 outline-none text-center"
                      />
                      <button
                        onClick={() => setPomodoroWorkMin((prev) => Math.min(90, prev + 5))}
                        className="p-2 rounded-xl bg-white/5 border border-white/10"
                      >
                        <Plus size={14} />
                      </button>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest">
                      休息时长 (min)
                    </label>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => setPomodoroBreakMin((prev) => Math.max(3, prev - 1))}
                        className="p-2 rounded-xl bg-white/5 border border-white/10"
                      >
                        <Minus size={14} />
                      </button>
                      <input
                        type="number"
                        value={pomodoroBreakMin}
                        min={3}
                        max={30}
                        onChange={(e) => setPomodoroBreakMin(Number(e.target.value))}
                        className="flex-1 bg-white/5 border border-white/10 rounded-xl p-2 text-xs font-mono font-bold text-indigo-300 outline-none text-center"
                      />
                      <button
                        onClick={() => setPomodoroBreakMin((prev) => Math.min(30, prev + 1))}
                        className="p-2 rounded-xl bg-white/5 border border-white/10"
                      >
                        <Plus size={14} />
                      </button>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest">
                      轮数 (rounds)
                    </label>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => setPomodoroRounds((prev) => Math.max(1, prev - 1))}
                        className="p-2 rounded-xl bg-white/5 border border-white/10"
                      >
                        <Minus size={14} />
                      </button>
                      <input
                        type="number"
                        value={pomodoroRounds}
                        min={1}
                        max={12}
                        onChange={(e) => {
                          const value = Number(e.target.value);
                          setPomodoroRounds(Number.isFinite(value) ? Math.max(1, Math.min(12, value)) : 1);
                        }}
                        className="flex-1 bg-white/5 border border-white/10 rounded-xl p-2 text-xs font-mono font-bold text-indigo-300 outline-none text-center"
                      />
                      <button
                        onClick={() => setPomodoroRounds((prev) => Math.min(12, prev + 1))}
                        className="p-2 rounded-xl bg-white/5 border border-white/10"
                      >
                        <Plus size={14} />
                      </button>
                    </div>
                  </div>
                </div>
                <div className="mt-8 flex items-center gap-3">
                  <button
                    onClick={() => setPomodoroRunning((prev) => !prev)}
                    className="flex-1 py-3 rounded-2xl bg-indigo-500 text-white font-black text-[11px] uppercase tracking-[0.3em] flex items-center justify-center gap-2"
                  >
                    {pomodoroRunning ? <Pause size={16} /> : <Play size={16} />}
                    {pomodoroRunning ? "暂停" : "开始"}
                  </button>
                  <button
                    onClick={() => {
                      setPomodoroRunning(false);
                      setPomodoroMode("work");
                      setPomodoroRound(1);
                      setPomodoroSeconds(
                        pomodoroWorkMin * 60
                      );
                    }}
                    className="px-4 py-3 rounded-2xl border border-white/10 text-slate-300 font-black text-[11px] uppercase tracking-[0.2em]"
                  >
                    <RotateCcw size={16} />
                  </button>
                </div>
              </div>

              <div className="col-span-7 bg-[#0c1222]/50 backdrop-blur-3xl rounded-[2.5rem] border border-white/[0.05] p-8 shadow-2xl flex flex-col">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-lg font-black text-white">工作清单</h3>
                    <p className="text-[11px] text-slate-500 font-bold mt-1">
                      可编辑、完成与未完成提醒
                    </p>
                  </div>
                  <div className="text-[11px] font-bold text-indigo-300">
                    完成 {tasks.filter((t) => t.done).length} / 未完成 {tasks.filter((t) => !t.done).length}
                  </div>
                </div>

                <div className="mt-6 flex items-center gap-3">
                  <input
                    value={taskInput}
                    onChange={(e) => setTaskInput(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && addTask()}
                    placeholder="添加任务..."
                    className="flex-1 bg-white/5 border border-white/10 rounded-2xl px-4 py-3 text-sm font-bold text-slate-200 outline-none"
                  />
                  <div className="flex items-center gap-2 bg-white/5 border border-white/10 rounded-2xl px-3 py-2">
                    <span className="text-[10px] font-black text-slate-400 uppercase tracking-widest">分钟</span>
                    <input
                      type="number"
                      value={taskMinutes}
                      min={5}
                      max={240}
                      onChange={(e) => {
                        const value = Number(e.target.value);
                        setTaskMinutes(Number.isFinite(value) ? Math.max(5, Math.min(240, value)) : 25);
                      }}
                      className="w-16 bg-transparent text-xs font-mono font-bold text-indigo-300 outline-none text-center"
                    />
                  </div>
                  <button
                    onClick={addTask}
                    className="px-4 py-3 rounded-2xl bg-indigo-500 text-white font-black text-[10px] uppercase tracking-widest"
                  >
                    添加
                  </button>
                </div>

                <div className="mt-6 flex-1 overflow-y-auto space-y-3 pr-2 no-scrollbar">
                  {tasks.map((task) => (
                    <div
                      key={task.id}
                      className={`flex items-center justify-between gap-3 p-4 rounded-2xl border transition-all ${
                        task.done ? "bg-white/5 border-white/10" : "bg-white/10 border-white/20"
                      }`}
                    >
                      <button onClick={() => toggleTask(task.id)} className="flex items-center gap-3 text-left">
                        {task.done ? (
                          <CheckCircle2 size={18} className="text-green-400" />
                        ) : (
                          <Circle size={18} className="text-slate-400" />
                        )}
                        <div className="flex flex-col">
                          <span
                            className={`text-sm font-bold ${
                              task.done ? "line-through text-slate-500" : "text-slate-200"
                            }`}
                          >
                            {task.title}
                          </span>
                          <span className="text-[10px] font-bold text-slate-500">
                            预计 {task.minutes} min
                          </span>
                        </div>
                      </button>
                      <button
                        onClick={() => deleteTask(task.id)}
                        className="p-2 rounded-xl bg-white/5 border border-white/10 text-slate-400 hover:text-rose-300"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  ))}
                  {tasks.length === 0 && (
                    <div className="text-xs text-slate-500 font-bold mt-8 text-center">
                      暂无任务，先添加你的第一条工作清单
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
          <div
            className={`${activeTab === Tab.DEVICE ? "h-full w-full overflow-y-auto pr-1 no-scrollbar" : "hidden"} `}
            aria-hidden={activeTab !== Tab.DEVICE}
          >
            <div className="min-h-full">
              <DeviceMonitor
                key={`device-monitor-${deviceViewKey}`}
                status={deviceStatus}
                scores={scores}
                riskDetail={riskDetail}
                logs={sysLogs}
                onRefreshStatus={fetchDeviceStatus}
                refreshing={statusRefreshing}
                statusError={deviceStatusError}
                videoEnabled={mediaState.videoEnabled}
                audioEnabled={mediaState.audioEnabled}
                faceTrack={faceTrack}
                faceTrackEngine={faceTrackEngine}
                wakeEngine={wakeEngine}
                faceTrackOverlayEnabled={faceTrackOverlayEnabled}
                onToggleFaceTrackOverlay={setFaceTrackOverlayEnabled}
                wsConnected={wsConnected}
                riskUpdatedAt={riskUpdatedAt}
                riskSource={riskSource}
                active={activeTab === Tab.DEVICE}
              />
            </div>
          </div>
          {activeTab === Tab.CONTROL && (
            <div className="h-full w-full">
              <SettingsPanel
                mode={mode}
                onModeChange={setMode}
                isGuest={isGuest}
                careDeliveryStrategy={careDeliveryStrategy}
                onCareDeliveryStrategyChange={handleCareDeliveryStrategyChange}
                mediaState={mediaState}
                onMediaToggle={handleMediaToggle}
              />
            </div>
          )}
          {activeTab === Tab.PROFILE && (
            <div className="h-full w-full overflow-y-auto pr-1 no-scrollbar">
              <div className="w-full max-w-5xl mx-auto bg-[#0c1222]/50 backdrop-blur-3xl rounded-[2.5rem] border border-white/[0.05] shadow-2xl p-10 animate-pop-in">
                <div className="flex items-center gap-6">
                  <div className="w-20 h-20 rounded-full border border-white/10 overflow-hidden">
                    <img src={resolvedAvatar} alt="avatar" className="w-full h-full object-cover" />
                  </div>
                  <div>
                    <h2 className="text-xl font-black text-white">{profileName}</h2>
                    <p className="text-[11px] text-slate-500 font-semibold mt-1">
                      {isGuest ? "访客模式已开启" : "账户已登录"}
                    </p>
                    {!isGuest && (
                      <p className="text-[10px] text-slate-400 font-semibold mt-1">
                        {profileUsername ? `@${profileUsername}` : "账号信息同步中"}
                      </p>
                    )}
                  </div>
                </div>

                {!isGuest && (
                  <div className="mt-5 grid grid-cols-2 gap-4 text-[10px] font-semibold text-slate-400">
                    <div className="rounded-xl border border-white/10 bg-white/5 px-3 py-2">
                      创建时间：{profileCreatedAt ? new Date(profileCreatedAt * 1000).toLocaleString() : "-"}
                    </div>
                    <div className="rounded-xl border border-white/10 bg-white/5 px-3 py-2">
                      上次更新：{profileUpdatedAt ? new Date(profileUpdatedAt * 1000).toLocaleString() : "-"}
                    </div>
                  </div>
                )}

                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  onChange={handleAvatarFile}
                  className="hidden"
                />

                <div className="grid grid-cols-2 gap-6 mt-8">
                  <div className="space-y-2">
                    <label className="text-[10px] font-black text-slate-500 uppercase ml-2 tracking-[0.2em]">
                      昵称
                    </label>
                    <input
                      value={profileDraftName}
                      onChange={(e) => setProfileDraftName(e.target.value)}
                      className="w-full bg-slate-900/60 border border-white/5 rounded-2xl py-3 px-4 text-white font-bold outline-none focus:ring-2 focus:ring-indigo-500/30"
                      placeholder="输入你的昵称"
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-[10px] font-black text-slate-500 uppercase ml-2 tracking-[0.2em]">
                      头像 URL
                    </label>
                    <input
                      value={profileDraftAvatar}
                      onChange={(e) => setProfileDraftAvatar(e.target.value)}
                      className="w-full bg-slate-900/60 border border-white/5 rounded-2xl py-3 px-4 text-white font-bold outline-none focus:ring-2 focus:ring-indigo-500/30"
                      placeholder="https://..."
                    />
                  </div>
                  <div className="space-y-2 col-span-2">
                    <label className="text-[10px] font-black text-slate-500 uppercase ml-2 tracking-[0.2em]">
                      个性签名
                    </label>
                    <textarea
                      value={profileDraftBio}
                      onChange={(e) => setProfileDraftBio(e.target.value)}
                      className="w-full min-h-[84px] bg-slate-900/60 border border-white/5 rounded-2xl py-3 px-4 text-white font-semibold outline-none focus:ring-2 focus:ring-indigo-500/30 resize-none"
                      placeholder="一句话介绍你自己"
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-[10px] font-black text-slate-500 uppercase ml-2 tracking-[0.2em]">
                      地点
                    </label>
                    <input
                      value={profileDraftLocation}
                      onChange={(e) => setProfileDraftLocation(e.target.value)}
                      className="w-full bg-slate-900/60 border border-white/5 rounded-2xl py-3 px-4 text-white font-bold outline-none focus:ring-2 focus:ring-indigo-500/30"
                      placeholder="例如：上海 / 深圳 / Remote"
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-[10px] font-black text-slate-500 uppercase ml-2 tracking-[0.2em]">
                      账号
                    </label>
                    <input
                      value={profileUsername ? `@${profileUsername}` : ""}
                      readOnly
                      className="w-full bg-slate-900/40 border border-white/5 rounded-2xl py-3 px-4 text-slate-300 font-bold outline-none"
                      placeholder="登录后显示"
                    />
                  </div>
                </div>

                <div className="flex gap-4 mt-6">
                  <button
                    onClick={handlePickAvatar}
                    className="flex-1 py-3 rounded-2xl text-[10px] font-black uppercase tracking-widest bg-white/5 text-slate-200 border border-white/10"
                  >
                    选择本地头像
                  </button>
                  <button
                    onClick={handleAvatarAuto}
                    className="flex-1 py-3 rounded-2xl text-[10px] font-black uppercase tracking-widest bg-indigo-500/15 text-indigo-200 border border-indigo-400/20"
                  >
                    生成头像
                  </button>
                  <button
                    onClick={handleProfileReset}
                    className="flex-1 py-3 rounded-2xl text-[10px] font-black uppercase tracking-widest bg-white/5 text-slate-300 border border-white/10"
                  >
                    恢复默认
                  </button>
                </div>

                {profileError && <p className="text-[11px] font-bold text-rose-400 mt-4">{profileError}</p>}

                <div className="mt-6 flex justify-between items-center">
                  <button
                    onClick={handleLogout}
                    className="px-6 py-3 rounded-2xl font-black text-[10px] uppercase tracking-[0.3em] text-rose-300 border border-rose-400/30 bg-rose-500/10 hover:bg-rose-500/20 transition-colors"
                  >
                    {isGuest ? "退出访客" : "退出登录"}
                  </button>
                  <button
                    onClick={handleProfileSave}
                    disabled={profileSaving}
                    className="px-8 py-3 rounded-2xl font-black text-[11px] uppercase tracking-[0.3em] bg-white text-slate-950 disabled:opacity-60"
                  >
                    {profileSaving ? "保存中..." : "保存资料"}
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </section>

      <div className="fixed inset-0 pointer-events-none border border-white/[0.01] z-50"></div>
    </div>
  );
};

const NavButton = ({ active, onClick, icon: Icon }: any) => (
  <button
    onClick={onClick}
    className={`relative p-3.5 rounded-2xl transition-all duration-500 group ${
      active ? "bg-indigo-600/10 text-white" : "text-slate-600 hover:text-slate-300"
    }`}
  >
    <Icon size={22} strokeWidth={active ? 2.5 : 2} />
    {active && (
      <div className="absolute -left-1 top-1/2 -translate-y-1/2 w-1 h-5 bg-indigo-500 rounded-full shadow-[0_0_10px_#6366f1]"></div>
    )}
  </button>
);

export default App;
