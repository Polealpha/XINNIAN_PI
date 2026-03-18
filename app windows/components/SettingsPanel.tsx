import React, { useEffect, useState } from "react";
import { CareDeliveryStrategy, EngineMode } from "../types";
import { PlayCircle, Shield, Volume2, Eye, Timer, BellRing, Video, Mic } from "lucide-react";
import { sendEngineSignal } from "../services/engineService";

interface SettingsPanelProps {
  mode: EngineMode;
  onModeChange: (m: EngineMode) => void;
  isGuest?: boolean;
  careDeliveryStrategy: CareDeliveryStrategy;
  onCareDeliveryStrategyChange: (strategy: CareDeliveryStrategy) => Promise<void>;
  mediaState: {
    videoEnabled: boolean;
    audioEnabled: boolean;
  };
  onMediaToggle: (type: "video" | "audio", enabled: boolean) => Promise<void>;
}

const COOLDOWN_OPTIONS = [15, 30, 60, 120];

export const SettingsPanel: React.FC<SettingsPanelProps> = ({
  mode,
  onModeChange,
  isGuest,
  careDeliveryStrategy,
  onCareDeliveryStrategyChange,
  mediaState,
  onMediaToggle,
}) => {
  const [cooldownMin, setCooldownMin] = useState(30);
  const [dailyLimit, setDailyLimit] = useState(5);
  const [statusMessage, setStatusMessage] = useState("");

  useEffect(() => {
    if (!statusMessage) return;
    const timer = setTimeout(() => setStatusMessage(""), 2500);
    return () => clearTimeout(timer);
  }, [statusMessage]);

  const pushModeSignal = async (nextMode: EngineMode) => {
    if (isGuest) {
      setStatusMessage("访客模式不可操作");
      return;
    }
    if (nextMode === "privacy") {
      await sendEngineSignal("privacy_on");
      return;
    }
    if (nextMode === "dnd") {
      await sendEngineSignal("do_not_disturb_on");
      return;
    }
    if (mode === "privacy") {
      await sendEngineSignal("privacy_off");
      return;
    }
    if (mode === "dnd") {
      await sendEngineSignal("do_not_disturb_off");
    }
  };

  const handleModeClick = async (nextMode: EngineMode) => {
    if (nextMode === mode) return;
    if (isGuest) {
      setStatusMessage("访客模式不可操作");
      return;
    }
    try {
      await pushModeSignal(nextMode);
      onModeChange(nextMode);
      setStatusMessage("模式已更新");
    } catch (err) {
      console.error("Mode update failed:", err);
      setStatusMessage("模式更新失败");
    }
  };

  const handleManualCare = async () => {
    if (isGuest) {
      setStatusMessage("访客模式不可操作");
      return;
    }
    try {
      await sendEngineSignal("manual_care");
      setStatusMessage("主动关怀已触发");
    } catch (err) {
      console.error("Manual care failed:", err);
      setStatusMessage("主动关怀触发失败");
    }
  };

  const handleCooldownUpdate = async (value: number) => {
    setCooldownMin(value);
    if (isGuest) {
      setStatusMessage("访客模式不可操作");
      return;
    }
    try {
      await sendEngineSignal("config_update", { cooldown_min: value });
      setStatusMessage("冷却周期已更新");
    } catch (err) {
      console.error("Cooldown update failed:", err);
      setStatusMessage("冷却周期更新失败");
    }
  };

  const applyDailyLimit = async (value: number) => {
    const safeValue = Math.max(1, Math.min(20, Number.isFinite(value) ? value : 5));
    setDailyLimit(safeValue);
    if (isGuest) {
      setStatusMessage("访客模式不可操作");
      return;
    }
    try {
      await sendEngineSignal("config_update", { daily_trigger_limit: safeValue });
      setStatusMessage("每日上限已更新");
    } catch (err) {
      console.error("Daily limit update failed:", err);
      setStatusMessage("每日上限更新失败");
    }
  };

  const handleMediaChange = async (type: "video" | "audio", enabled: boolean) => {
    if (isGuest) {
      setStatusMessage("访客模式不可操作");
      return;
    }
    try {
      await onMediaToggle(type, enabled);
      setStatusMessage("采集状态已更新");
    } catch (err) {
      console.error("Media toggle failed:", err);
      setStatusMessage("采集状态更新失败");
    }
  };

  const handleCareDeliveryStrategyChange = async (next: CareDeliveryStrategy) => {
    if (next === careDeliveryStrategy) return;
    if (isGuest) {
      setStatusMessage("访客模式不可操作");
      return;
    }
    try {
      await onCareDeliveryStrategyChange(next);
      setStatusMessage("关怀投递策略已更新");
    } catch (err) {
      console.error("Care delivery strategy update failed:", err);
      setStatusMessage("关怀投递策略更新失败");
    }
  };

  return (
    <div className="grid grid-cols-12 gap-6 h-full animate-pop-in">
      <div className="col-span-4 bg-[#0c1222]/50 backdrop-blur-3xl rounded-[2.5rem] border border-white/[0.05] p-8 shadow-2xl flex flex-col gap-6">
        <div>
          <h3 className="text-[10px] font-black text-slate-500 uppercase tracking-widest mb-6">引擎模式</h3>
          <div className="space-y-3">
            {[
              { id: "normal", label: "标准感知", icon: Eye },
              { id: "privacy", label: "隐私加密", icon: Shield },
              { id: "dnd", label: "免打扰", icon: Volume2 },
            ].map((item) => (
              <button
                key={item.id}
                onClick={() => handleModeClick(item.id as EngineMode)}
                className={`w-full p-4 rounded-2xl flex items-center gap-4 border transition-all ${
                  mode === item.id
                    ? "bg-indigo-500/10 border-indigo-500/30 text-white"
                    : "bg-white/5 border-transparent text-slate-500 hover:text-slate-300"
                }`}
              >
                <item.icon size={18} />
                <span className="text-xs font-black">{item.label}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="mt-auto">
          <h3 className="text-[10px] font-black text-slate-500 uppercase tracking-widest mb-4">快捷操作</h3>
          <button
            onClick={handleManualCare}
            className="w-full py-4 bg-indigo-500 text-white rounded-2xl flex items-center justify-center gap-3 font-black text-[10px] uppercase tracking-widest shadow-xl shadow-indigo-500/20 q-bounce"
          >
            <BellRing size={16} /> 手动触发主动关怀
          </button>
        </div>
      </div>

      <div className="col-span-8 bg-[#0c1222]/50 backdrop-blur-3xl rounded-[2.5rem] border border-white/[0.05] p-10 shadow-2xl overflow-y-auto no-scrollbar">
        <div className="space-y-10">
          <div>
            <div className="flex items-center gap-3 mb-6">
              <Video size={18} className="text-indigo-400" />
              <h3 className="text-[11px] font-black text-slate-200 uppercase tracking-[0.3em]">采集控制</h3>
            </div>
            <div className="grid grid-cols-2 gap-6">
              <MediaToggle
                title="摄像头"
                desc="实时控制是否接入视频流"
                enabled={mediaState.videoEnabled}
                icon={Video}
                onToggle={(next) => handleMediaChange("video", next)}
              />
              <MediaToggle
                title="麦克风"
                desc="实时控制是否接入音频流"
                enabled={mediaState.audioEnabled}
                icon={Mic}
                onToggle={(next) => handleMediaChange("audio", next)}
              />
            </div>
          </div>

          <div className="pt-8 border-t border-white/5 grid grid-cols-2 gap-8">
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <Timer size={14} className="text-indigo-400" />
                <span className="text-[10px] font-black text-slate-300 uppercase tracking-widest">
                  触发冷却周期
                </span>
              </div>
              <div className="flex gap-2">
                {COOLDOWN_OPTIONS.map((t) => (
                  <button
                    key={t}
                    onClick={() => handleCooldownUpdate(t)}
                    aria-pressed={cooldownMin === t}
                    className={`flex-1 py-2 rounded-lg text-[9px] font-black border transition-all ${
                      cooldownMin === t
                        ? "bg-indigo-500 border-indigo-500 text-white"
                        : "bg-white/5 border-white/5 text-slate-500 hover:text-slate-300"
                    }`}
                  >
                    {t}m
                  </button>
                ))}
              </div>
            </div>
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <PlayCircle size={14} className="text-indigo-400" />
                <span className="text-[10px] font-black text-slate-300 uppercase tracking-widest">
                  每日触发上限
                </span>
              </div>
              <input
                type="number"
                value={dailyLimit}
                min={1}
                max={20}
                onChange={(e) => setDailyLimit(Number(e.target.value))}
                onBlur={() => applyDailyLimit(dailyLimit)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    applyDailyLimit(dailyLimit);
                  }
                }}
                className="w-full bg-white/5 border border-white/10 rounded-xl p-2 text-xs font-mono font-bold text-indigo-300 outline-none focus:border-indigo-500"
              />
            </div>
          </div>

          <div className="pt-8 border-t border-white/5">
            <div className="flex items-center gap-2 mb-4">
              <Volume2 size={14} className="text-indigo-400" />
              <span className="text-[10px] font-black text-slate-300 uppercase tracking-widest">
                主动关怀投递策略
              </span>
            </div>
            <div className="grid grid-cols-3 gap-2">
              {[
                { id: "policy", label: "遵循昼夜策略" },
                { id: "voice_all_day", label: "全天语音" },
                { id: "popup_all_day", label: "全天弹窗" },
              ].map((item) => (
                <button
                  key={item.id}
                  onClick={() => handleCareDeliveryStrategyChange(item.id as CareDeliveryStrategy)}
                  aria-pressed={careDeliveryStrategy === item.id}
                  className={`px-2 py-3 rounded-lg text-[9px] font-black border transition-all ${
                    careDeliveryStrategy === item.id
                      ? "bg-indigo-500 border-indigo-500 text-white"
                      : "bg-white/5 border-white/10 text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
        </div>
        {statusMessage && (
          <div className="mt-6 text-[10px] font-black text-indigo-300 uppercase tracking-[0.3em]">
            {statusMessage}
          </div>
        )}
      </div>
    </div>
  );
};

const MediaToggle = ({
  title,
  desc,
  enabled,
  icon: Icon,
  onToggle,
}: {
  title: string;
  desc: string;
  enabled: boolean;
  icon: React.ComponentType<{ size?: number }>;
  onToggle: (next: boolean) => void;
}) => (
  <div className="bg-white/5 border border-white/10 rounded-2xl p-5 flex flex-col gap-4">
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-3">
        <div
          className={`w-10 h-10 rounded-full flex items-center justify-center ${
            enabled ? "bg-indigo-500/15 text-indigo-300" : "bg-white/5 text-slate-500"
          }`}
        >
          <Icon size={18} />
        </div>
        <div>
          <div className="text-sm font-black text-white">{title}</div>
          <div className="text-[10px] text-slate-500 font-bold mt-1">{desc}</div>
        </div>
      </div>
      <button
        onClick={() => onToggle(!enabled)}
        className={`px-4 py-2 rounded-full text-[10px] font-black uppercase tracking-widest border transition-all ${
          enabled
            ? "bg-indigo-500 text-white border-indigo-500"
            : "bg-white/5 text-slate-400 border-white/10"
        }`}
      >
        {enabled ? "On" : "Off"}
      </button>
    </div>
    <div className="text-[9px] font-bold text-slate-500 uppercase tracking-widest">
      当前状态：{enabled ? "开启" : "关闭"}
    </div>
  </div>
);
