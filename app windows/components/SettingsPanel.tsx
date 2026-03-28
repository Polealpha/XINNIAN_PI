import React, { useEffect, useMemo, useState } from "react";
import {
  BellRing,
  Bot,
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
  {
    id: "normal",
    label: "标准陪伴",
    desc: "保持主动关怀、语音互动和轻度感知，适合作为默认运行模式。",
  },
  {
    id: "privacy",
    label: "隐私优先",
    desc: "降低采集频率，减少打扰，更适合长时间安静办公。",
  },
  {
    id: "dnd",
    label: "免打扰",
    desc: "暂停主动提醒，只保留明确唤醒和必要响应。",
  },
];

const ASSISTANT_MODE_OPTIONS: Array<{
  id: DeviceSettings["assistant"]["mode"];
  label: string;
  desc: string;
}> = [
  {
    id: "product",
    label: "产品模式",
    desc: "优先走受控工具层，稳定、可回执，适合日常正式使用。",
  },
  {
    id: "agent",
    label: "代理模式",
    desc: "放开更多 OpenClaw 能力，动作更猛，但波动也更大。",
  },
];

const CARE_OPTIONS: Array<{ id: DeviceSettings["care_delivery_strategy"]; label: string; desc: string }> = [
  {
    id: "policy",
    label: "智能策略",
    desc: "由风险分数和当前场景决定走语音、弹窗还是安静观察。",
  },
  {
    id: "voice_all_day",
    label: "语音优先",
    desc: "更偏向机器人直接说话，适合更强陪伴感的体验。",
  },
  {
    id: "popup_all_day",
    label: "桌面优先",
    desc: "更多在电脑端设置、提醒和待办，而不是频繁语音打断。",
  },
];

const STT_OPTIONS = [
  { id: "faster_whisper", label: "faster-whisper", desc: "电脑端优先，准确率更高。" },
  { id: "sherpa_onnx", label: "sherpa-onnx", desc: "更贴近本地链路，延迟更稳。" },
];

const VOICE_STYLES = [
  { id: "sweet", label: "甜妹", desc: "更轻、更软，适合首次激活和陪伴对话。" },
  { id: "warm", label: "温柔", desc: "更稳、更克制，适合长时间陪伴。" },
  { id: "bright", label: "明快", desc: "更有精神，适合提醒和日常互动。" },
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
    const timer = window.setTimeout(() => setStatusMessage(""), 2600);
    return () => window.clearTimeout(timer);
  }, [statusMessage]);

  const summary = useMemo(
    () => [
      draft.assistant.mode === "agent" ? "OpenClaw 代理模式已开启" : "OpenClaw 产品模式已开启",
      draft.assistant.native_control_enabled ? "允许原生电脑控制" : "限制原生电脑控制",
      draft.wake.enabled ? "树莓派本地唤醒开启" : "树莓派本地唤醒关闭",
      draft.media.audio_enabled ? "音频采集开启" : "音频采集关闭",
      draft.media.camera_enabled ? "树莓派摄像头开启" : "树莓派摄像头关闭",
      `设置页自动回表情：${draft.behavior.settings_auto_return_sec || 0} 秒`,
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
      setStatusMessage("访客模式不能修改设备设置。");
      return;
    }
    setSaving(true);
    try {
      await onSave(draft);
      setStatusMessage("设置已同步到桌面端、OpenClaw 和树莓派。");
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
              <div className="text-[11px] font-black uppercase tracking-[0.35em] text-cyan-300/70">
                Runtime Preferences
              </div>
              <h2 className="mt-4 text-3xl font-black text-white">设备与运行偏好</h2>
              <p className="mt-3 text-sm leading-7 text-slate-300">
                这里是桌面端的高级偏好设置入口，用来同步 OpenClaw、桌面后端和树莓派运行层的行为。
                不是首次激活必经页，平时按需再打开即可。
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
            icon={Bot}
            title="助手控制层"
            subtitle="决定当前走稳定的产品模式，还是放开更强的 OpenClaw 代理模式。"
          >
            <div className="grid gap-4 lg:grid-cols-2">
              {ASSISTANT_MODE_OPTIONS.map((item) => (
                <SelectableCard
                  key={item.id}
                  active={draft.assistant.mode === item.id}
                  title={item.label}
                  desc={item.desc}
                  onClick={() => updateNested("assistant", { mode: item.id })}
                />
              ))}
            </div>
            <div className="mt-4">
              <ToggleRow
                title="允许 OpenClaw 原生本地控制"
                desc="开启后，代理模式可直接尝试操作本地应用、浏览器和窗口；关闭后仍走代理思考，但会尽量避免直接动你的桌面。"
                enabled={draft.assistant.native_control_enabled}
                onToggle={() =>
                  updateNested("assistant", {
                    native_control_enabled: !draft.assistant.native_control_enabled,
                  })
                }
              />
            </div>
          </Panel>

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
            subtitle="控制音频采集与树莓派摄像头链路；既然你已经接树莓派摄像头，这里不再讨论笔记本代跑。"
          >
            <div className="grid gap-4 lg:grid-cols-2">
              <ToggleCard
                icon={Mic}
                title="音频采集"
                desc="本地语音问答、人格测评语音和唤醒后的识别都依赖它。"
                enabled={draft.media.audio_enabled}
                onToggle={(next) => updateNested("media", { audio_enabled: next })}
              />
              <ToggleCard
                icon={Video}
                title="树莓派摄像头"
                desc="控制树莓派侧视频链路和后续人脸/云台跟踪，不再使用笔记本摄像头代跑。"
                enabled={draft.media.camera_enabled}
                onToggle={(next) => updateNested("media", { camera_enabled: next })}
              />
            </div>
          </Panel>

          <div className="grid gap-6 lg:grid-cols-2">
            <Panel
              icon={Volume2}
              title="语音与唤醒"
              subtitle="保留树莓派本地唤醒，同时把高质量转写主链放在电脑端。"
            >
              <div className="space-y-4">
                <ToggleRow
                  title="启用本地唤醒"
                  desc="树莓派可离线待命，唤醒后进入本地问答、设置控制或人格测评。"
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
                    label="电脑端语音转写"
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
              subtitle="给双轴云台、设置页自动返回和后续扫脸建档留好位置。"
            >
              <div className="space-y-4">
                <ToggleRow
                  title="左右跟随"
                  desc="控制 pan 舵机，用于左右转头和简单位移反馈。"
                  enabled={draft.tracking.pan_enabled}
                  onToggle={() => updateNested("tracking", { pan_enabled: !draft.tracking.pan_enabled })}
                />
                <ToggleRow
                  title="上下跟随"
                  desc="控制 tilt 舵机，用于抬头、低头和点头动作。"
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
            <Panel icon={Timer} title="节奏控制" subtitle="限制机器人主动频率，避免陪伴系统过度打扰。">
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

            <Panel
              icon={BellRing}
              title="实际影响"
              subtitle="这些设置会同时影响桌面端、Pi 本体、OpenClaw 和后端行为。"
            >
              <div className="grid gap-3">
                <ResultCard title="电脑端">
                  会影响设置页显示、桌面语音转写主链、提醒弹窗，以及 OpenClaw 是更稳地走工具层还是更猛地走代理模式。
                </ResultCard>
                <ResultCard title="机器人本体">
                  会影响树莓派本地唤醒、TTS 音色、音频采集、按钮切页、设置页回表情页的时机，以及双轴云台是否参与动作反馈。
                </ResultCard>
                <ResultCard title="OpenClaw / 后端">
                  会影响工具优先级、原生电脑控制权限、第一次激活与人格测评的语音入口，以及后续主动关怀的提示词与节奏。
                </ResultCard>
              </div>
            </Panel>
          </div>

          <Panel
            icon={Wand2}
            title="后续接线提醒"
            subtitle="实体设置键接好后，点设置键会让 Pi 屏幕切到设置页，同时电脑端自动打开这里。"
          >
            <div className="grid gap-4 lg:grid-cols-3">
              <ResultCard title="设置键">
                用于直接切到设置页。电脑端会收到事件，并自动弹出高级偏好面板。
              </ResultCard>
              <ResultCard title="开关键 / 关机键">
                用于板端上电、软关机和长按保护。真接线后再做实机去抖和长按逻辑联调。
              </ResultCard>
              <ResultCard title="屏幕镜像">
                Pi 屏幕只负责镜像页和状态页，完整配置仍由电脑端承担，避免你在小屏上做复杂操作。
              </ResultCard>
            </div>
          </Panel>
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
    type="button"
    onClick={onClick}
    className={`w-full rounded-[1.5rem] border p-5 text-left transition ${
      active
        ? "border-cyan-300/40 bg-cyan-400/10 text-white shadow-[0_18px_45px_rgba(34,211,238,0.12)]"
        : "border-white/10 bg-white/[0.03] text-slate-200 hover:bg-white/[0.07]"
    }`}
  >
    <div className="flex items-center justify-between gap-3">
      <div className="text-xl font-black">{label}</div>
      <span className={`h-4 w-4 rounded-full ${active ? "bg-cyan-300" : "bg-slate-500/40"}`} />
    </div>
    <p className="mt-3 text-sm leading-7 text-slate-300">{desc}</p>
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
    type="button"
    onClick={onClick}
    className={`rounded-[1.75rem] border p-5 text-left transition ${
      active
        ? "border-cyan-300/40 bg-cyan-400/10 text-white shadow-[0_18px_45px_rgba(34,211,238,0.12)]"
        : "border-white/10 bg-white/[0.03] text-slate-200 hover:bg-white/[0.07]"
    }`}
  >
    <div className="text-2xl font-black">{title}</div>
    <p className="mt-3 text-sm leading-7 text-slate-300">{desc}</p>
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
  <div className="rounded-[1.75rem] border border-white/10 bg-white/[0.03] p-5">
    <div className="flex items-start justify-between gap-4">
      <div className="flex gap-3">
        <div className="rounded-2xl border border-white/10 bg-black/20 p-3 text-cyan-200">
          <Icon size={18} />
        </div>
        <div>
          <div className="text-lg font-black text-white">{title}</div>
          <p className="mt-2 text-sm leading-7 text-slate-300">{desc}</p>
        </div>
      </div>
      <button
        type="button"
        onClick={() => onToggle(!enabled)}
        className={`rounded-full px-4 py-2 text-xs font-black uppercase tracking-[0.25em] ${
          enabled ? "bg-cyan-400 text-slate-950" : "bg-white/10 text-slate-300"
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
  <div className="rounded-[1.5rem] border border-white/10 bg-white/[0.03] px-5 py-4">
    <div className="flex items-start justify-between gap-4">
      <div>
        <div className="text-lg font-black text-white">{title}</div>
        <p className="mt-2 text-sm leading-7 text-slate-300">{desc}</p>
      </div>
      <button
        type="button"
        onClick={onToggle}
        className={`rounded-full px-4 py-2 text-xs font-black uppercase tracking-[0.25em] ${
          enabled ? "bg-cyan-400 text-slate-950" : "bg-white/10 text-slate-300"
        }`}
      >
        {enabled ? "ON" : "OFF"}
      </button>
    </div>
  </div>
);

const Field = ({
  label,
  value,
  placeholder,
  onChange,
}: {
  label: string;
  value: string;
  placeholder?: string;
  onChange: (value: string) => void;
}) => (
  <label className="block">
    <div className="mb-2 text-xs font-black uppercase tracking-[0.28em] text-slate-400">{label}</div>
    <input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-3 text-sm font-semibold text-white outline-none transition focus:border-cyan-300/40 focus:bg-white/[0.05]"
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
      onChange={(e) => {
        const next = Number(e.target.value);
        if (Number.isFinite(next)) onChange(Math.max(min, Math.min(max, next)));
      }}
      className="w-full rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-3 text-sm font-semibold text-white outline-none transition focus:border-cyan-300/40 focus:bg-white/[0.05]"
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
    <div className="space-y-3">
      {options.map((option) => (
        <button
          type="button"
          key={option.id}
          onClick={() => onChange(option.id)}
          className={`w-full rounded-2xl border p-4 text-left transition ${
            value === option.id
              ? "border-cyan-300/40 bg-cyan-400/10 text-white"
              : "border-white/10 bg-white/[0.03] text-slate-200 hover:bg-white/[0.07]"
          }`}
        >
          <div className="text-sm font-black">{option.label}</div>
          <div className="mt-1 text-xs leading-6 text-slate-300">{option.desc}</div>
        </button>
      ))}
    </div>
  </div>
);

const ResultCard = ({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) => (
  <div className="rounded-[1.5rem] border border-white/10 bg-white/[0.03] px-5 py-4">
    <div className="text-sm font-black text-white">{title}</div>
    <div className="mt-2 text-sm leading-7 text-slate-300">{children}</div>
  </div>
);
