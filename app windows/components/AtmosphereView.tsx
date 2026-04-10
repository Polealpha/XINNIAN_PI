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
    <div className="relative h-full min-h-[760px] overflow-hidden rounded-[2.4rem] border border-white/10 bg-[linear-gradient(180deg,rgba(18,25,41,0.94),rgba(9,14,24,0.98))] p-6 shadow-[0_26px_80px_rgba(3,8,20,0.34),inset_0_1px_0_rgba(255,255,255,0.06)] animate-rise">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(140,168,255,0.16),transparent_24%),linear-gradient(180deg,rgba(255,255,255,0.03),transparent_24%)]" />

      <div className="relative flex h-full flex-col">
        <div className="flex items-center justify-between gap-3">
          <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-3.5 py-2 text-[10px] font-black tracking-[0.24em] text-slate-300">
            <Waves size={11} className="text-sky-300" />
            实时概览
          </span>
          <span className="rounded-full border border-white/8 bg-white/[0.03] px-3 py-1.5 text-[10px] font-semibold text-slate-400">
            {todayRecordCount} 条记录
          </span>
        </div>

        <div className="mt-5 rounded-[2rem] border border-white/10 bg-[linear-gradient(180deg,rgba(255,255,255,0.06),rgba(255,255,255,0.02))] p-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="text-[11px] font-bold uppercase tracking-[0.24em] text-slate-500">当前状态</div>
              <div className="mt-3 text-[3rem] font-black tracking-[-0.06em] text-white">{summary.label}</div>
              <div className="mt-2 text-sm font-semibold text-slate-300">{summary.level}</div>
            </div>
            <div className="rounded-[1.6rem] border border-white/10 bg-[#0e1628]/80 px-4 py-4 text-right shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
              <div className="text-[10px] font-bold tracking-[0.2em] text-slate-500">压力指数</div>
              <div className="mt-2 text-[2rem] font-black tracking-[-0.05em] text-white">{pct(scores.S)}</div>
              <div className="mt-1 text-[11px] font-medium text-slate-400">当前摘要分数</div>
            </div>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-3">
          <div className="rounded-[1.5rem] border border-white/8 bg-white/[0.035] px-4 py-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
            <div className="text-[10px] font-bold tracking-[0.18em] text-slate-500">主导维度</div>
            <div className="mt-2 text-base font-black text-white">{summary.primary.label}</div>
          </div>
          <div className="rounded-[1.5rem] border border-white/8 bg-white/[0.035] px-4 py-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
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
          <div className="rounded-[1.5rem] border border-white/8 bg-white/[0.035] px-4 py-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
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
          <div className="rounded-[1.5rem] border border-white/8 bg-white/[0.035] px-4 py-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
            <div className="text-[10px] font-bold tracking-[0.18em] text-slate-500">数据来源</div>
            <div className="mt-2 text-base font-black text-white">{sourceLabel}</div>
          </div>
        </div>

        <div className="mt-4 rounded-[1.9rem] border border-white/10 bg-[linear-gradient(180deg,rgba(12,18,32,0.84),rgba(8,13,24,0.96))] p-5">
          <div className="text-[11px] font-bold tracking-[0.24em] text-slate-500">风险维度</div>
          <div className="mt-4 space-y-4">
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

        <div className="mt-auto rounded-[1.7rem] border border-white/8 bg-white/[0.03] px-4 py-4">
          <div className="text-[10px] font-bold tracking-[0.18em] text-slate-500">陪伴建议</div>
          <div className="mt-2 text-sm font-semibold leading-6 text-slate-300">
            {summary.level}，当前更适合用简短反馈和轻提醒，不需要堆太多说明文字。
          </div>
        </div>
      </div>
    </div>
  );
};
