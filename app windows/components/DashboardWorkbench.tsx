import React from "react";
import {
  Bell,
  Camera,
  CheckCircle2,
  Circle,
  ListChecks,
  MessageSquareHeart,
  Mic,
  RefreshCw,
  Settings,
  Sparkles,
} from "lucide-react";
import { AssistantRuntimeStatus, AssistantTodoItem } from "../services/assistantService";
import { CareDeliveryStrategy, DeviceStatus } from "../types";

type FocusTaskPreview = {
  id: string;
  title: string;
  done: boolean;
  minutes: number;
};

interface DashboardWorkbenchProps {
  currentEmotion: string;
  sampleCount: number;
  average: number;
  peak: number;
  assistantRuntime: AssistantRuntimeStatus | null;
  deviceStatus: DeviceStatus | null;
  statusRefreshing: boolean;
  cameraEnabled: boolean;
  audioEnabled: boolean;
  careDeliveryStrategy: CareDeliveryStrategy;
  latestCareText?: string | null;
  latestCareQuestion?: string | null;
  insightText?: string | null;
  summaryGenerating: boolean;
  focusTasks: FocusTaskPreview[];
  reminders: AssistantTodoItem[];
  onOpenChat: () => void;
  onOpenCamera: () => void;
  onOpenFocus: () => void;
  onOpenSettings: () => void;
  onRefreshStatus: () => void;
  onToggleCamera: () => void;
  onToggleAudio: () => void;
  onGenerateSummary: () => void;
}

const careModeLabel = (strategy: CareDeliveryStrategy) => {
  if (strategy === "voice_all_day") return "全天语音";
  if (strategy === "popup_all_day") return "全天弹窗";
  return "智能判断";
};

const statusTone = (active: boolean) =>
  active
    ? "border-emerald-400/25 bg-emerald-400/10 text-emerald-200"
    : "border-white/10 bg-white/[0.04] text-slate-300";

export const DashboardWorkbench: React.FC<DashboardWorkbenchProps> = ({
  currentEmotion,
  sampleCount,
  average,
  peak,
  assistantRuntime,
  deviceStatus,
  statusRefreshing,
  cameraEnabled,
  audioEnabled,
  careDeliveryStrategy,
  latestCareText,
  latestCareQuestion,
  insightText,
  summaryGenerating,
  focusTasks,
  reminders,
  onOpenChat,
  onOpenCamera,
  onOpenFocus,
  onOpenSettings,
  onRefreshStatus,
  onToggleCamera,
  onToggleAudio,
  onGenerateSummary,
}) => {
  const undoneTasks = focusTasks.filter((task) => !task.done).slice(0, 3);
  const reminderItems = reminders.slice(0, 3);
  const runtimeReady = Boolean(assistantRuntime?.gateway_ready && assistantRuntime?.provider_network_ok);
  const cameraReady = Boolean(deviceStatus?.status?.camera_ready);

  return (
    <div className="ios-surface-hero relative rounded-[2.35rem] p-5 animate-rise flex flex-col gap-4">
      <div className="ios-liquid-blob" />
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-[10px] font-black uppercase tracking-[0.24em] text-slate-500">首页工作台</div>
          <div className="mt-2 text-lg font-black text-white">现在可以直接操作，不只是看板</div>
          <div className="mt-2 text-sm font-semibold text-slate-400 leading-6">
            当前情绪 {currentEmotion}，今天已采样 {sampleCount} 次
            {average > 0 ? `，平均 ${average}%` : ""}
            {peak > 0 ? `，峰值 ${peak}%` : ""}
          </div>
        </div>
        <button
          onClick={onRefreshStatus}
          className="rounded-full border border-white/10 bg-white/[0.05] px-3.5 py-2 text-[11px] font-black text-slate-200 transition hover:bg-white/[0.09]"
        >
          <span className="inline-flex items-center gap-2">
            <RefreshCw size={13} className={statusRefreshing ? "animate-spin" : ""} />
            刷新
          </span>
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <button
          onClick={onOpenChat}
          className="rounded-[1.6rem] border border-white/10 bg-white/[0.04] px-4 py-4 text-left transition hover:bg-white/[0.08]"
        >
          <div className="flex items-center gap-2 text-slate-200">
            <MessageSquareHeart size={15} className="text-indigo-300" />
            <span className="text-sm font-black">开始对话</span>
          </div>
          <div className="mt-2 text-[11px] font-semibold text-slate-400">进入聊天页，继续陪伴或追问</div>
        </button>
        <button
          onClick={onOpenCamera}
          className="rounded-[1.6rem] border border-white/10 bg-white/[0.04] px-4 py-4 text-left transition hover:bg-white/[0.08]"
        >
          <div className="flex items-center gap-2 text-slate-200">
            <Camera size={15} className="text-cyan-300" />
            <span className="text-sm font-black">打开识别</span>
          </div>
          <div className="mt-2 text-[11px] font-semibold text-slate-400">查看相机与实时情绪识别</div>
        </button>
        <button
          onClick={onOpenFocus}
          className="rounded-[1.6rem] border border-white/10 bg-white/[0.04] px-4 py-4 text-left transition hover:bg-white/[0.08]"
        >
          <div className="flex items-center gap-2 text-slate-200">
            <ListChecks size={15} className="text-emerald-300" />
            <span className="text-sm font-black">专注任务</span>
          </div>
          <div className="mt-2 text-[11px] font-semibold text-slate-400">管理任务和番茄钟</div>
        </button>
        <button
          onClick={onOpenSettings}
          className="rounded-[1.6rem] border border-white/10 bg-white/[0.04] px-4 py-4 text-left transition hover:bg-white/[0.08]"
        >
          <div className="flex items-center gap-2 text-slate-200">
            <Settings size={15} className="text-slate-300" />
            <span className="text-sm font-black">设备设置</span>
          </div>
          <div className="mt-2 text-[11px] font-semibold text-slate-400">调整机器人与设备页状态</div>
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <button
          onClick={onToggleCamera}
          className={`rounded-[1.5rem] border px-4 py-3 text-left transition ${statusTone(cameraEnabled)}`}
        >
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Camera size={14} />
              <span className="text-sm font-black">摄像头</span>
            </div>
            <span className="text-[10px] font-black">{cameraEnabled ? "已开启" : "已关闭"}</span>
          </div>
          <div className="mt-2 text-[11px] font-semibold text-slate-400">
            {cameraReady ? "识别链路已就绪" : "可一键切换采集状态"}
          </div>
        </button>
        <button
          onClick={onToggleAudio}
          className={`rounded-[1.5rem] border px-4 py-3 text-left transition ${statusTone(audioEnabled)}`}
        >
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Mic size={14} />
              <span className="text-sm font-black">麦克风</span>
            </div>
            <span className="text-[10px] font-black">{audioEnabled ? "已开启" : "已关闭"}</span>
          </div>
          <div className="mt-2 text-[11px] font-semibold text-slate-400">影响唤醒、聆听与语音陪伴</div>
        </button>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div className="ios-metric-card rounded-[1.55rem] px-4 py-3.5">
          <div className="text-[10px] font-black uppercase tracking-[0.2em] text-slate-500">本地引擎</div>
          <div className="mt-2 text-sm font-black text-white">{runtimeReady ? "在线" : "待处理"}</div>
        </div>
        <div className="ios-metric-card rounded-[1.55rem] px-4 py-3.5">
          <div className="text-[10px] font-black uppercase tracking-[0.2em] text-slate-500">设备状态</div>
          <div className="mt-2 text-sm font-black text-white">{deviceStatus?.online ? "在线" : "离线"}</div>
        </div>
        <div className="ios-metric-card rounded-[1.55rem] px-4 py-3.5">
          <div className="text-[10px] font-black uppercase tracking-[0.2em] text-slate-500">关怀策略</div>
          <div className="mt-2 text-sm font-black text-white">{careModeLabel(careDeliveryStrategy)}</div>
        </div>
      </div>

      <div className="rounded-[1.7rem] border border-white/10 bg-white/[0.035] px-4 py-4">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Sparkles size={14} className="text-amber-300" />
            <span className="text-[11px] font-black uppercase tracking-[0.24em] text-slate-400">今日洞察</span>
          </div>
          <button
            onClick={onGenerateSummary}
            className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-[10px] font-black text-slate-200 transition hover:bg-white/[0.08]"
          >
            {summaryGenerating ? "生成中..." : "生成总结"}
          </button>
        </div>
        <div className="mt-3 text-sm font-semibold leading-6 text-slate-300">
          {insightText || latestCareText || "这里会显示今天的情绪总结、主动关怀结果，或者你刚刚生成的首页洞察。"}
        </div>
        {latestCareQuestion && (
          <div className="mt-3 rounded-[1.2rem] border border-white/10 bg-white/[0.03] px-3.5 py-3 text-[11px] font-semibold text-slate-300">
            追问：{latestCareQuestion}
          </div>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-[1.7rem] border border-white/10 bg-white/[0.03] px-4 py-4">
          <div className="flex items-center gap-2 text-[11px] font-black uppercase tracking-[0.2em] text-slate-400">
            <ListChecks size={13} className="text-emerald-300" />
            今日任务
          </div>
          <div className="mt-3 space-y-2.5">
            {undoneTasks.length === 0 && (
              <div className="text-[11px] font-semibold text-slate-500">还没有未完成任务，去专注页加一个就能在首页跟进。</div>
            )}
            {undoneTasks.map((task) => (
              <div key={task.id} className="flex items-start gap-2 text-sm text-slate-200">
                <Circle size={14} className="mt-0.5 text-slate-500" />
                <div>
                  <div className="font-semibold">{task.title}</div>
                  <div className="text-[11px] font-semibold text-slate-500">{task.minutes} 分钟</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-[1.7rem] border border-white/10 bg-white/[0.03] px-4 py-4">
          <div className="flex items-center gap-2 text-[11px] font-black uppercase tracking-[0.2em] text-slate-400">
            <Bell size={13} className="text-indigo-300" />
            到期提醒
          </div>
          <div className="mt-3 space-y-2.5">
            {reminderItems.length === 0 && (
              <div className="text-[11px] font-semibold text-slate-500">当前没有到期提醒，提醒出现后会直接在这里显示。</div>
            )}
            {reminderItems.map((item) => (
              <div key={item.id} className="flex items-start gap-2 text-sm text-slate-200">
                <CheckCircle2 size={14} className="mt-0.5 text-indigo-300" />
                <div>
                  <div className="font-semibold">{item.title || "新的提醒"}</div>
                  <div className="text-[11px] font-semibold text-slate-500">{item.details || "到点了，记得处理一下。"}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
