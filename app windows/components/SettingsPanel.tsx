import React, { useEffect, useMemo, useState } from "react";
import {
  BellRing,
  Eye,
  Mic,
  ScanFace,
  Settings2,
  Sparkles,
  Timer,
  Video,
  Volume2,
  Wand2,
  X,
} from "lucide-react";
import { DeviceSettings } from "../types";

interface SettingsPanelProps {
  settings: DeviceSettings;
  isGuest?: boolean;
  onSave: (next: DeviceSettings) => Promise<void>;
  onClose: () => Promise<void> | void;
}

const COOLDOWN_OPTIONS = [15, 30, 60, 120];

const MODE_OPTIONS: Array<{ id: DeviceSettings["mode"]; label: string; desc: string }> = [
  { id: "normal", label: "标准陪伴", desc: "保留主动关怀、语音互动和轻度感知。" },
  { id: "privacy", label: "隐私优先", desc: "降低采集频率，尽量少打扰。" },
  { id: "dnd", label: "免打扰", desc: "暂停主动提醒，只保留必要响应。" },
];

const CARE_OPTIONS: Array<{ id: DeviceSettings["care_delivery_strategy"]; label: string; desc: string }> = [
  { id: "policy", label: "智能策略", desc: "由风险和场景自动决定弹窗或语音。" },
  { id: "voice_all_day", label: "语音优先", desc: "更偏向机器人直接语音关怀。" },
  { id: "popup_all_day", label: "弹窗优先", desc: "更多在电脑端显示提示和建议。" },
];

const STT_OPTIONS = [
  { id: "faster_whisper", label: "faster-whisper", desc: "电脑端优先，准确率更高。" },
  { id: "sherpa_onnx", label: "sherpa-onnx", desc: "全本地链路，延迟更稳。" },
];

const VOICE_STYLES = [
  { id: "sweet", label: "甜妹", desc: "更柔和，更适合陪伴与测评。" },
  { id: "warm", label: "温柔", desc: "偏稳重，适合日常陪伴。" },
  { id: "bright", label: "明快", desc: "更轻快，适合提醒与问候。" },
];

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

  const summary = useMemo(
    () => [
      draft.wake.enabled ? "本地唤醒已开启" : "本地唤醒已关闭",
      draft.media.audio_enabled ? "麦克风采集开启" : "麦克风采集关闭",
      draft.media.camera_enabled ? "摄像头采集开启" : "摄像头采集关闭",
      `设置页自动返回 ${draft.behavior.settings_auto_return_sec || 0} 秒`,
    ],
    [draft]
  );

  const patchDraft = (patch: Partial<DeviceSettings>) => {
    setDraft((prev) => ({ ...prev, ...patch }));
  };

  const updateNested = <K extends keyof DeviceSettings>(key: K, patch: Partial<DeviceSettings[K]>) => {
    setDraft((prev) => ({
      ...prev,
      [key]: {
        ...(prev[key] as Record<string, unknown>),
        ...(patch as Record<string, unknown>),
      },
    }));
  };

  const handleSave = async () => {
    if (isGuest) {
      setStatusMessage("游客模式不能修改设备设置。");
      return;
    }
    setSaving(true);
    try {
      await onSave(draft);
      setStatusMessage("设置已经同步到机器人。");
    } catch (err) {
      console.error("Save settings failed:", err);
      setStatusMessage("保存失败，请稍后重试。");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="h-full w-full overflow-y-auto no-scrollbar animate-pop-in">
      <div className="mx-auto grid max-w-7xl grid-cols-12 gap-6">
        <aside className="col-span-12 xl:col-span-4 rounded-[2rem] border border-white/10 bg-[radial-gradient(circle_at_top,#1d4ed820,transparent_50%),linear-gradient(180deg,#0f172acc,#0b1020f2)] p-8 shadow-[0_30px_120px_rgba(2,6,23,0.4)]">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="text-[11px] font-black uppercase tracking-[0.35em] text-cyan-300/70">Device Settings</div>
              <h2 className="mt-4 text-3xl font-black text-white">机器人设置中心</h2>
              <p className="mt-3 text-sm leading-7 text-slate-300">
                电脑端是主设置入口，保存后会同步到树莓派，并驱动本地屏幕切换回表情页。
              </p>
            </div>
            <div className="rounded-2xl border border-cyan-400/20 bg-cyan-400/10 p-3 text-cyan-200">
              <Settings2 size={22} />
            </div>
          </div>

          <div className="mt-8 space-y-3">
            {MODE_OPTIONS.map((item) => (
              <ModeCard
                key={item.id}
                active={draft.mode === item.id}
                label={item.label}
                desc={item.desc}
                onClick={() => patchDraft({ mode: item.id })}
              />
            ))}
          </div>

          <div className="mt-8 rounded-[1.5rem] border border-white/10 bg-white/[0.04] p-5">
            <div className="text-[11px] font-black uppercase tracking-[0.28em] text-slate-400">当前摘要</div>
            <div className="mt-4 space-y-3">
              {summary.map((item) => (
                <div key={item} className="rounded-2xl bg-black/20 px-4 py-3 text-sm font-semibold text-slate-200">
                  {item}
                </div>
              ))}
            </div>
          </div>

          <div className="mt-8 grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
            <button
              onClick={handleSave}
              disabled={saving}
              className="inline-flex items-center justify-center gap-3 rounded-2xl bg-cyan-400 px-5 py-4 text-sm font-black text-slate-950 shadow-[0_12px_50px_rgba(34,211,238,0.28)] transition hover:translate-y-[-1px] disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Settings2 size={18} />
              {saving ? "正在保存..." : "保存并同步"}
            </button>
            <button
              onClick={() => void onClose()}
              className="inline-flex items-center justify-center gap-3 rounded-2xl border border-white/10 bg-white/5 px-5 py-4 text-sm font-black text-slate-100 transition hover:bg-white/10"
            >
              <X size={18} />
              关闭设置
            </button>
          </div>

          {statusMessage ? (
            <div className="mt-4 rounded-2xl border border-cyan-400/20 bg-cyan-400/10 px-4 py-3 text-sm font-bold text-cyan-100">
              {statusMessage}
            </div>
          ) : null}
        </aside>

        <section className="col-span-12 xl:col-span-8 space-y-6">
          <Panel
            icon={Sparkles}
            title="主动关怀"
            subtitle="决定机器人在电脑端和本体上如何陪伴、何时提醒、提醒得多主动。"
          >
            <div className="grid gap-4 lg:grid-cols-3">
              {CARE_OPTIONS.map((item) => (
                <SelectableCard
                  key={item.id}
                  active={draft.care_delivery_strategy === item.id}
                  title={item.label}
                  desc={item.desc}
                  onClick={() => patchDraft({ care_delivery_strategy: item.id })}
                />
              ))}
            </div>
          </Panel>

          <Panel
            icon={Video}
            title="感知与采集"
            subtitle="控制麦克风和摄像头采集。当前你没接摄像头，所以建议先保持关闭。"
          >
            <div className="grid gap-4 lg:grid-cols-2">
              <ToggleCard
                icon={Mic}
                title="麦克风采集"
                desc="本地语音问答、唤醒后识别、人格测评语音都依赖它。"
                enabled={draft.media.audio_enabled}
                onToggle={(next) => updateNested("media", { audio_enabled: next })}
              />
              <ToggleCard
                icon={Video}
                title="摄像头采集"
                desc="接上相机后再打开，避免板子不断探测报错。"
                enabled={draft.media.camera_enabled}
                onToggle={(next) => updateNested("media", { camera_enabled: next })}
              />
            </div>
          </Panel>

          <div className="grid gap-6 lg:grid-cols-2">
            <Panel
              icon={Volume2}
              title="语音与唤醒"
              subtitle="保留树莓派本地唤醒，同时把高质量语音转写主链放到电脑端。"
            >
              <div className="space-y-4">
                <ToggleRow
                  title="启用本地唤醒"
                  desc="树莓派可离线待命，唤醒后进入本地问答或测评会话。"
                  enabled={draft.wake.enabled}
                  onToggle={() => updateNested("wake", { enabled: !draft.wake.enabled })}
                />
                <Field
                  label="唤醒词"
                  value={draft.wake.wake_phrase}
                  onChange={(value) => updateNested("wake", { wake_phrase: value })}
                  placeholder="例如：小念"
                />
                <Field
                  label="唤醒应答"
                  value={draft.wake.ack_text}
                  onChange={(value) => updateNested("wake", { ack_text: value })}
                  placeholder="例如：我在"
                />
                <div className="grid gap-3 md:grid-cols-2">
                  <OptionGroup
                    label="电脑端转写主链"
                    options={STT_OPTIONS}
                    value={draft.voice.desktop_stt_provider}
                    onChange={(value) => updateNested("voice", { desktop_stt_provider: value })}
                  />
                  <OptionGroup
                    label="机器人音色"
                    options={VOICE_STYLES}
                    value={draft.voice.robot_voice_style}
                    onChange={(value) => updateNested("voice", { robot_voice_style: value })}
                  />
                </div>
              </div>
            </Panel>

            <Panel
              icon={ScanFace}
              title="云台与回屏"
              subtitle="给双轴云台、设置页自动返回、后续扫脸建档留接口。"
            >
              <div className="space-y-4">
                <ToggleRow
                  title="左右追踪"
                  desc="控制 pan 舵机，适合左右跟随。"
                  enabled={draft.tracking.pan_enabled}
                  onToggle={() => updateNested("tracking", { pan_enabled: !draft.tracking.pan_enabled })}
                />
                <ToggleRow
                  title="上下追踪"
                  desc="控制 tilt 舵机，适合抬头低头。"
                  enabled={draft.tracking.tilt_enabled}
                  onToggle={() => updateNested("tracking", { tilt_enabled: !draft.tracking.tilt_enabled })}
                />
                <NumberField
                  label="设置页自动返回（秒）"
                  value={draft.behavior.settings_auto_return_sec}
                  min={0}
                  max={600}
                  onChange={(value) => updateNested("behavior", { settings_auto_return_sec: value })}
                />
              </div>
            </Panel>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <Panel icon={Timer} title="节奏控制" subtitle="控制机器人的主动频率，避免过于频繁打扰。">
              <div className="space-y-5">
                <div>
                  <div className="mb-3 text-xs font-black uppercase tracking-[0.28em] text-slate-400">触发冷却</div>
                  <div className="grid grid-cols-4 gap-3">
                    {COOLDOWN_OPTIONS.map((value) => (
                      <button
                        key={value}
                        onClick={() => updateNested("behavior", { cooldown_min: value })}
                        className={`rounded-2xl px-3 py-3 text-sm font-black transition ${
                          draft.behavior.cooldown_min === value
                            ? "bg-cyan-400 text-slate-950"
                            : "border border-white/10 bg-white/5 text-slate-200 hover:bg-white/10"
                        }`}
                      >
                        {value} 分钟
                      </button>
                    ))}
                  </div>
                </div>
                <NumberField
                  label="每日主动触发上限"
                  value={draft.behavior.daily_trigger_limit}
                  min={1}
                  max={20}
                  onChange={(value) => updateNested("behavior", { daily_trigger_limit: value })}
                />
              </div>
            </Panel>

            <Panel icon={BellRing} title="实际结果" subtitle="这些设置会同时影响电脑端、Pi 本体和 OpenClaw 的产品行为。">
              <div className="grid gap-3">
                <ResultCard title="电脑端">
                  修改后会影响设置页显示、桌面端语音转写策略、提醒和待办交互。
                </ResultCard>
                <ResultCard title="机器人本体">
                  会影响树莓派本地 UI、唤醒词、TTS 风格、音频采集和云台跟随。
                </ResultCard>
                <ResultCard title="后端与 OpenClaw">
                  会影响机器人动作桥、主动关怀策略、人格测评语音入口和后续提示词上下文。
                </ResultCard>
              </div>
            </Panel>
          </div>
        </section>
      </div>
    </div>
  );
};

const Panel = ({
  icon: Icon,
  title,
  subtitle,
  children,
}: {
  icon: React.ComponentType<{ size?: number; className?: string }>;
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) => (
  <section className="rounded-[2rem] border border-white/10 bg-[linear-gradient(180deg,rgba(15,23,42,0.88),rgba(8,15,28,0.96))] p-7 shadow-[0_25px_80px_rgba(2,6,23,0.35)]">
    <div className="flex items-start gap-4">
      <div className="rounded-2xl border border-cyan-400/20 bg-cyan-400/10 p-3 text-cyan-200">
        <Icon size={20} className="shrink-0" />
      </div>
      <div>
        <div className="text-xl font-black text-white">{title}</div>
        <p className="mt-2 text-sm leading-7 text-slate-300">{subtitle}</p>
      </div>
    </div>
    <div className="mt-6">{children}</div>
  </section>
);

const ModeCard = ({
  active,
  label,
  desc,
  onClick,
}: {
  active: boolean;
  label: string;
  desc: string;
  onClick: () => void;
}) => (
  <button
    onClick={onClick}
    className={`w-full rounded-[1.4rem] border px-5 py-4 text-left transition ${
      active
        ? "border-cyan-400/40 bg-cyan-400/10 shadow-[0_10px_40px_rgba(34,211,238,0.12)]"
        : "border-white/10 bg-white/[0.04] hover:bg-white/[0.08]"
    }`}
  >
    <div className="flex items-center justify-between gap-4">
      <div className="text-base font-black text-white">{label}</div>
      <div className={`h-3 w-3 rounded-full ${active ? "bg-cyan-300" : "bg-slate-600"}`} />
    </div>
    <div className="mt-2 text-sm leading-6 text-slate-300">{desc}</div>
  </button>
);

const SelectableCard = ({
  active,
  title,
  desc,
  onClick,
}: {
  active: boolean;
  title: string;
  desc: string;
  onClick: () => void;
}) => (
  <button
    onClick={onClick}
    className={`rounded-[1.4rem] border p-5 text-left transition ${
      active ? "border-cyan-400/40 bg-cyan-400/10" : "border-white/10 bg-white/[0.04] hover:bg-white/[0.08]"
    }`}
  >
    <div className="text-base font-black text-white">{title}</div>
    <div className="mt-2 text-sm leading-6 text-slate-300">{desc}</div>
  </button>
);

const ToggleCard = ({
  icon: Icon,
  title,
  desc,
  enabled,
  onToggle,
}: {
  icon: React.ComponentType<{ size?: number; className?: string }>;
  title: string;
  desc: string;
  enabled: boolean;
  onToggle: (next: boolean) => void;
}) => (
  <div className="rounded-[1.4rem] border border-white/10 bg-white/[0.04] p-5">
    <div className="flex items-start justify-between gap-4">
      <div className="flex items-start gap-4">
        <div className={`rounded-2xl p-3 ${enabled ? "bg-cyan-400/12 text-cyan-200" : "bg-white/5 text-slate-400"}`}>
          <Icon size={18} />
        </div>
        <div>
          <div className="text-base font-black text-white">{title}</div>
          <div className="mt-2 text-sm leading-6 text-slate-300">{desc}</div>
        </div>
      </div>
      <button
        onClick={() => onToggle(!enabled)}
        className={`rounded-full px-4 py-2 text-xs font-black uppercase tracking-[0.22em] transition ${
          enabled ? "bg-cyan-400 text-slate-950" : "border border-white/10 bg-white/5 text-slate-300"
        }`}
      >
        {enabled ? "ON" : "OFF"}
      </button>
    </div>
  </div>
);

const ToggleRow = ({
  title,
  desc,
  enabled,
  onToggle,
}: {
  title: string;
  desc: string;
  enabled: boolean;
  onToggle: () => void;
}) => (
  <div className="flex items-center justify-between gap-4 rounded-[1.4rem] border border-white/10 bg-white/[0.04] px-5 py-4">
    <div>
      <div className="text-sm font-black text-white">{title}</div>
      <div className="mt-1 text-sm leading-6 text-slate-300">{desc}</div>
    </div>
    <button
      onClick={onToggle}
      className={`rounded-full px-4 py-2 text-xs font-black uppercase tracking-[0.22em] transition ${
        enabled ? "bg-cyan-400 text-slate-950" : "border border-white/10 bg-white/5 text-slate-300"
      }`}
    >
      {enabled ? "ON" : "OFF"}
    </button>
  </div>
);

const Field = ({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
}) => (
  <label className="block">
    <div className="mb-2 text-xs font-black uppercase tracking-[0.28em] text-slate-400">{label}</div>
    <input
      type="text"
      value={value}
      onChange={(event) => onChange(event.target.value)}
      placeholder={placeholder}
      className="w-full rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-semibold text-white outline-none transition focus:border-cyan-300/40 focus:bg-white/[0.08]"
    />
  </label>
);

const NumberField = ({
  label,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (value: number) => void;
}) => (
  <label className="block">
    <div className="mb-2 text-xs font-black uppercase tracking-[0.28em] text-slate-400">{label}</div>
    <input
      type="number"
      value={value}
      min={min}
      max={max}
      onChange={(event) => onChange(Number(event.target.value) || min)}
      className="w-full rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-semibold text-white outline-none transition focus:border-cyan-300/40 focus:bg-white/[0.08]"
    />
  </label>
);

const OptionGroup = ({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: Array<{ id: string; label: string; desc: string }>;
  value: string;
  onChange: (value: string) => void;
}) => (
  <div>
    <div className="mb-3 text-xs font-black uppercase tracking-[0.28em] text-slate-400">{label}</div>
    <div className="grid gap-3">
      {options.map((item) => (
        <button
          key={item.id}
          onClick={() => onChange(item.id)}
          className={`rounded-[1.2rem] border p-4 text-left transition ${
            value === item.id ? "border-cyan-400/40 bg-cyan-400/10" : "border-white/10 bg-white/[0.04] hover:bg-white/[0.08]"
          }`}
        >
          <div className="text-sm font-black text-white">{item.label}</div>
          <div className="mt-1 text-xs leading-6 text-slate-300">{item.desc}</div>
        </button>
      ))}
    </div>
  </div>
);

const ResultCard = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <div className="rounded-[1.4rem] border border-white/10 bg-white/[0.04] px-5 py-4">
    <div className="text-xs font-black uppercase tracking-[0.28em] text-cyan-300/80">{title}</div>
    <div className="mt-2 text-sm leading-7 text-slate-200">{children}</div>
  </div>
);
