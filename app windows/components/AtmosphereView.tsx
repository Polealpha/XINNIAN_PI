import React, { useMemo } from "react";
import { EngineMode, RiskDetail, RiskScores } from "../types";
import { Activity, Clock3, ShieldHalf, Waves } from "lucide-react";

interface AtmosphereViewProps {
  scores: RiskScores;
  mode: EngineMode;
  riskDetail?: RiskDetail | null;
  riskUpdatedAt?: number | null;
  riskSource?: "ws" | "poll" | null;
  todayRecordCount?: number;
}

const pct = (value: number) => `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
const emotionLabels = ["平静", "愉悦", "惊讶", "低落", "愤怒", "厌恶", "紧张", "疲惫"];

export const AtmosphereView: React.FC<AtmosphereViewProps> = ({
  scores,
  mode,
  riskDetail,
  riskUpdatedAt,
  riskSource,
  todayRecordCount = 0,
}) => {
  const summary = useMemo(() => {
    const exprId = Number(riskDetail?.V_sub?.expression_class_id);
    const label =
      Number.isFinite(exprId) && exprId >= 0 && exprId < emotionLabels.length
        ? emotionLabels[Math.floor(exprId)]
        : scores.S > 0.62
        ? "紧绷"
        : scores.T > 0.45
        ? "疲惫"
        : "平静";

    const confidence = Number(riskDetail?.V_sub?.expression_confidence ?? 0);
    const primary = [
      { key: "S", label: "整体压力", value: scores.S },
      { key: "T", label: "疲惫负荷", value: scores.T },
      { key: "A", label: "唤醒波动", value: scores.A },
    ].sort((a, b) => b.value - a.value)[0];

    const level =
      scores.S >= 0.72 ? "建议放缓节奏" : scores.S >= 0.45 ? "轻度起伏中" : "整体较平稳";

    return { label, confidence, primary, level };
  }, [riskDetail, scores]);

  const updated = riskUpdatedAt
    ? new Date(riskUpdatedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : "等待数据";

  const sourceLabel =
    riskSource === "ws" ? "实时推送" : riskSource === "poll" ? "轮询刷新" : "等待接入";

  const riskItems = [
    { key: "S", label: "压力", value: scores.S, tone: "from-[#88a8ff] to-[#62d4ff]" },
    { key: "T", label: "疲惫", value: scores.T, tone: "from-[#7dd3fc] to-[#8ce7c2]" },
    { key: "A", label: "唤醒", value: scores.A, tone: "from-[#c4b5fd] to-[#7dd3fc]" },
  ];

  return (
    <div className="ios-surface-hero relative h-full min-h-[940px] overflow-hidden rounded-[2.6rem] p-6 animate-rise">
      <div className="ios-liquid-blob" />
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(255,204,224,0.14),transparent_26%),radial-gradient(circle_at_bottom_right,rgba(132,223,255,0.08),transparent_18%),linear-gradient(180deg,rgba(255,255,255,0.04),transparent_24%)]" />

      <div className="relative flex h-full flex-col">
        <div className="flex items-center justify-between gap-3">
          <span className="ios-chip-soft inline-flex items-center gap-2 rounded-full px-3.5 py-2 text-[10px] font-black tracking-[0.24em] text-slate-200">
            <Waves size={11} className="text-sky-300" />
            实时概览
          </span>
          <span className="ios-chip-soft rounded-full px-3 py-1.5 text-[10px] font-semibold text-slate-300/90">
            {todayRecordCount} 条记录
          </span>
        </div>

        <div className="ios-surface-subtle mt-5 min-h-[11.6rem] rounded-[2.1rem] p-5">
          <div className="flex items-stretch justify-between gap-4">
            <div className="min-w-0">
              <div className="text-[11px] font-bold uppercase tracking-[0.24em] text-slate-500">当前状态</div>
              <div className="mt-3 text-[2.2rem] font-black leading-[1.02] tracking-[-0.06em] text-white">{summary.label}</div>
              <div className="mt-2 text-sm font-semibold text-slate-300">{summary.level}</div>
            </div>
            <div className="ios-surface-panel w-[6.2rem] shrink-0 rounded-[1.7rem] px-3 py-3 text-right">
              <div className="text-[10px] font-bold tracking-[0.2em] text-slate-500">压力指数</div>
              <div className="mt-2 text-[1.7rem] font-black tracking-[-0.05em] text-white">{pct(scores.S)}</div>
              <div className="mt-1 text-[10px] font-medium leading-4 text-slate-400">当前摘要分数</div>
            </div>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-3">
          <div className="ios-surface-panel rounded-[1.6rem] px-4 py-4">
            <div className="text-[10px] font-bold tracking-[0.18em] text-slate-500">主导维度</div>
            <div className="mt-2 text-base font-black text-white">{summary.primary.label}</div>
          </div>
          <div className="ios-surface-panel rounded-[1.6rem] px-4 py-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[10px] font-bold tracking-[0.18em] text-slate-500">识别置信</div>
                <div className="mt-2 text-base font-black text-white">
                  {summary.confidence > 0 ? `${Math.round(summary.confidence * 100)}%` : "--"}
                </div>
              </div>
              <Activity size={18} className="text-sky-300" />
            </div>
          </div>
          <div className="ios-surface-panel rounded-[1.6rem] px-4 py-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[10px] font-bold tracking-[0.18em] text-slate-500">最近更新</div>
                <div className="mt-2 text-base font-black text-white">{updated}</div>
              </div>
              {mode === "privacy" ? (
                <ShieldHalf size={18} className="text-emerald-300" />
              ) : (
                <Clock3 size={18} className="text-slate-300" />
              )}
            </div>
          </div>
          <div className="ios-surface-panel rounded-[1.6rem] px-4 py-4">
            <div className="text-[10px] font-bold tracking-[0.18em] text-slate-500">数据来源</div>
            <div className="mt-2 text-base font-black text-white">{sourceLabel}</div>
          </div>
        </div>

        <div className="ios-glass-well mt-4 rounded-[2rem] p-4">
          <div className="text-[11px] font-bold tracking-[0.24em] text-slate-500">风险维度</div>
          <div className="mt-3 space-y-3">
            {riskItems.map((item) => (
              <div key={item.key}>
                <div className="mb-2 flex items-center justify-between text-sm font-semibold text-slate-300">
                  <span>{item.label}</span>
                  <span className="text-slate-500">{pct(item.value)}</span>
                </div>
                <div className="h-2.5 overflow-hidden rounded-full bg-white/[0.05]">
                  <div className={`h-full rounded-full bg-gradient-to-r ${item.tone}`} style={{ width: pct(item.value) }} />
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="ios-glass-well ios-glass-well--soft mt-4 rounded-[1.8rem] px-4 py-3">
          <div className="text-[10px] font-bold tracking-[0.18em] text-slate-500">陪伴建议</div>
          <div className="mt-2 text-[13px] font-semibold leading-5 text-slate-300">
            {summary.level}，当前更适合用简短反馈和轻提醒，不需要堆太多说明文字。
          </div>
        </div>
      </div>
    </div>
  );
};
