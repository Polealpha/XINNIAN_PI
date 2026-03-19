import React, { useEffect, useState } from "react";
import { DeviceSettings } from "../types";
import { BellRing, Eye, Mic, Settings2, Timer, Video, Volume2, Wand2, X } from "lucide-react";

interface SettingsPanelProps {
  settings: DeviceSettings;
  isGuest?: boolean;
  onSave: (next: DeviceSettings) => Promise<void>;
  onClose: () => Promise<void> | void;
}

const COOLDOWN_OPTIONS = [15, 30, 60, 120];

export const SettingsPanel: React.FC<SettingsPanelProps> = ({ settings, isGuest, onSave, onClose }) => {
  const [draft, setDraft] = useState<DeviceSettings>(settings);
  const [statusMessage, setStatusMessage] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setDraft(settings);
  }, [settings]);

  useEffect(() => {
    if (!statusMessage) return;
    const timer = setTimeout(() => setStatusMessage(""), 2600);
    return () => clearTimeout(timer);
  }, [statusMessage]);

  const patchDraft = (patch: Partial<DeviceSettings>) => {
    setDraft((prev) => ({ ...prev, ...patch }));
  };

  const handleSave = async () => {
    if (isGuest) {
      setStatusMessage("游客模式不可操作");
      return;
    }
    setSaving(true);
    try {
      await onSave(draft);
      setStatusMessage("设置已同步到机器人");
    } catch (err) {
      console.error("Save settings failed:", err);
      setStatusMessage("设置保存失败");
    } finally {
      setSaving(false);
    }
  };

  const updateNested = <K extends keyof DeviceSettings>(
    key: K,
    patch: Partial<DeviceSettings[K]>
  ) => {
    setDraft((prev) => ({
      ...prev,
      [key]: {
        ...(prev[key] as Record<string, unknown>),
        ...(patch as Record<string, unknown>),
      },
    }));
  };

  return (
    <div className="grid grid-cols-12 gap-6 h-full animate-pop-in">
      <div className="col-span-4 bg-[#0c1222]/50 backdrop-blur-3xl rounded-[2.5rem] border border-white/[0.05] p-8 shadow-2xl flex flex-col gap-6">
        <div>
          <h3 className="text-[10px] font-black text-slate-500 uppercase tracking-widest mb-6">设置面板</h3>
          <div className="space-y-3">
            {[
              { id: "normal", label: "标准感知" },
              { id: "privacy", label: "隐私模式" },
              { id: "dnd", label: "免打扰" },
            ].map((item) => (
              <button
                key={item.id}
                onClick={() => patchDraft({ mode: item.id as DeviceSettings["mode"] })}
                className={`w-full p-4 rounded-2xl flex items-center gap-4 border transition-all ${
                  draft.mode === item.id
                    ? "bg-indigo-500/10 border-indigo-500/30 text-white"
                    : "bg-white/5 border-transparent text-slate-500 hover:text-slate-300"
                }`}
              >
                <Eye size={18} />
                <span className="text-xs font-black">{item.label}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="space-y-3">
          <button
            onClick={handleSave}
            disabled={saving}
            className="w-full py-4 bg-indigo-500 text-white rounded-2xl flex items-center justify-center gap-3 font-black text-[10px] uppercase tracking-widest shadow-xl shadow-indigo-500/20 disabled:opacity-60"
          >
            <Settings2 size={16} />
            {saving ? "保存中" : "保存设置"}
          </button>
          <button
            onClick={() => void onClose()}
            className="w-full py-4 bg-white/5 text-slate-200 rounded-2xl flex items-center justify-center gap-3 font-black text-[10px] uppercase tracking-widest border border-white/10"
          >
            <X size={16} />
            关闭设置
          </button>
        </div>

        <div className="mt-auto rounded-2xl border border-white/10 bg-white/[0.04] p-4">
          <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">当前概要</div>
          <div className="mt-3 text-[12px] text-slate-300 leading-6">
            唤醒：{draft.wake.enabled ? "开启" : "关闭"}
            <br />
            音频：{draft.media.audio_enabled ? "开启" : "关闭"}
            <br />
            视频：{draft.media.camera_enabled ? "开启" : "关闭"}
            <br />
            设置自动返回：{draft.behavior.settings_auto_return_sec || 0} 秒
          </div>
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
                desc="控制是否采集视频流"
                enabled={draft.media.camera_enabled}
                icon={Video}
                onToggle={(next) => updateNested("media", { camera_enabled: next })}
              />
              <MediaToggle
                title="麦克风"
                desc="控制是否采集音频流"
                enabled={draft.media.audio_enabled}
                icon={Mic}
                onToggle={(next) => updateNested("media", { audio_enabled: next })}
              />
            </div>
          </div>

          <div className="pt-8 border-t border-white/5 grid grid-cols-2 gap-8">
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <Timer size={14} className="text-indigo-400" />
                <span className="text-[10px] font-black text-slate-300 uppercase tracking-widest">触发冷却周期</span>
              </div>
              <div className="flex gap-2">
                {COOLDOWN_OPTIONS.map((t) => (
                  <button
                    key={t}
                    onClick={() => updateNested("behavior", { cooldown_min: t })}
                    aria-pressed={draft.behavior.cooldown_min === t}
                    className={`flex-1 py-2 rounded-lg text-[9px] font-black border transition-all ${
                      draft.behavior.cooldown_min === t
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
                <BellRing size={14} className="text-indigo-400" />
                <span className="text-[10px] font-black text-slate-300 uppercase tracking-widest">每日触发上限</span>
              </div>
              <input
                type="number"
                value={draft.behavior.daily_trigger_limit}
                min={1}
                max={20}
                onChange={(e) => updateNested("behavior", { daily_trigger_limit: Number(e.target.value) || 1 })}
                className="w-full bg-white/5 border border-white/10 rounded-xl p-2 text-xs font-mono font-bold text-indigo-300 outline-none focus:border-indigo-500"
              />
            </div>
          </div>

          <div className="pt-8 border-t border-white/5 grid grid-cols-2 gap-8">
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <Volume2 size={14} className="text-indigo-400" />
                <span className="text-[10px] font-black text-slate-300 uppercase tracking-widest">主动关怀策略</span>
              </div>
              <div className="grid grid-cols-3 gap-2">
                {[
                  { id: "policy", label: "策略决策" },
                  { id: "voice_all_day", label: "全天语音" },
                  { id: "popup_all_day", label: "全天弹窗" },
                ].map((item) => (
                  <button
                    key={item.id}
                    onClick={() => patchDraft({ care_delivery_strategy: item.id as DeviceSettings["care_delivery_strategy"] })}
                    aria-pressed={draft.care_delivery_strategy === item.id}
                    className={`px-2 py-3 rounded-lg text-[9px] font-black border transition-all ${
                      draft.care_delivery_strategy === item.id
                        ? "bg-indigo-500 border-indigo-500 text-white"
                        : "bg-white/5 border-white/10 text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <Wand2 size={14} className="text-indigo-400" />
                <span className="text-[10px] font-black text-slate-300 uppercase tracking-widest">设置页自动返回</span>
              </div>
              <input
                type="number"
                value={draft.behavior.settings_auto_return_sec}
                min={0}
                max={600}
                onChange={(e) => updateNested("behavior", { settings_auto_return_sec: Number(e.target.value) || 0 })}
                className="w-full bg-white/5 border border-white/10 rounded-xl p-2 text-xs font-mono font-bold text-indigo-300 outline-none focus:border-indigo-500"
              />
            </div>
          </div>

          <div className="pt-8 border-t border-white/5 grid grid-cols-2 gap-8">
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <Volume2 size={14} className="text-indigo-400" />
                <span className="text-[10px] font-black text-slate-300 uppercase tracking-widest">唤醒词设置</span>
              </div>
              <label className="flex items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                <span className="text-sm font-bold text-slate-100">启用本地唤醒</span>
                <button
                  onClick={() => updateNested("wake", { enabled: !draft.wake.enabled })}
                  className={`px-4 py-2 rounded-full text-[10px] font-black uppercase tracking-widest border transition-all ${
                    draft.wake.enabled
                      ? "bg-indigo-500 text-white border-indigo-500"
                      : "bg-white/5 text-slate-400 border-white/10"
                  }`}
                >
                  {draft.wake.enabled ? "On" : "Off"}
                </button>
              </label>
              <input
                type="text"
                value={draft.wake.wake_phrase}
                onChange={(e) => updateNested("wake", { wake_phrase: e.target.value })}
                placeholder="唤醒词"
                className="w-full bg-white/5 border border-white/10 rounded-xl p-3 text-sm font-bold text-slate-100 outline-none focus:border-indigo-500"
              />
              <input
                type="text"
                value={draft.wake.ack_text}
                onChange={(e) => updateNested("wake", { ack_text: e.target.value })}
                placeholder="唤醒应答"
                className="w-full bg-white/5 border border-white/10 rounded-xl p-3 text-sm font-bold text-slate-100 outline-none focus:border-indigo-500"
              />
            </div>

            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <Eye size={14} className="text-indigo-400" />
                <span className="text-[10px] font-black text-slate-300 uppercase tracking-widest">追踪与语音风格</span>
              </div>
              <label className="flex items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                <span className="text-sm font-bold text-slate-100">左右跟踪</span>
                <button
                  onClick={() => updateNested("tracking", { pan_enabled: !draft.tracking.pan_enabled })}
                  className={`px-4 py-2 rounded-full text-[10px] font-black uppercase tracking-widest border transition-all ${
                    draft.tracking.pan_enabled
                      ? "bg-indigo-500 text-white border-indigo-500"
                      : "bg-white/5 text-slate-400 border-white/10"
                  }`}
                >
                  {draft.tracking.pan_enabled ? "On" : "Off"}
                </button>
              </label>
              <label className="flex items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                <span className="text-sm font-bold text-slate-100">上下跟踪</span>
                <button
                  onClick={() => updateNested("tracking", { tilt_enabled: !draft.tracking.tilt_enabled })}
                  className={`px-4 py-2 rounded-full text-[10px] font-black uppercase tracking-widest border transition-all ${
                    draft.tracking.tilt_enabled
                      ? "bg-indigo-500 text-white border-indigo-500"
                      : "bg-white/5 text-slate-400 border-white/10"
                  }`}
                >
                  {draft.tracking.tilt_enabled ? "On" : "Off"}
                </button>
              </label>
              <input
                type="text"
                value={draft.voice.robot_voice_style}
                onChange={(e) => updateNested("voice", { robot_voice_style: e.target.value })}
                placeholder="机器人音色风格"
                className="w-full bg-white/5 border border-white/10 rounded-xl p-3 text-sm font-bold text-slate-100 outline-none focus:border-indigo-500"
              />
            </div>
          </div>
        </div>
        {statusMessage && (
          <div className="mt-6 text-[10px] font-black text-indigo-300 uppercase tracking-[0.3em]">{statusMessage}</div>
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
    <div className="flex items-center justify-between gap-4">
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
          enabled ? "bg-indigo-500 text-white border-indigo-500" : "bg-white/5 text-slate-400 border-white/10"
        }`}
      >
        {enabled ? "On" : "Off"}
      </button>
    </div>
    <div className="text-[9px] font-bold text-slate-500 uppercase tracking-widest">当前状态：{enabled ? "开启" : "关闭"}</div>
  </div>
);
