import React, { useMemo } from "react";
import { EngineMode, RiskDetail, RiskScores } from "../types";
import { Activity, Clock3, ShieldHalf, Sparkle, Waves } from "lucide-react";

interface AtmosphereViewProps {
  scores: RiskScores;
  mode: EngineMode;
  riskDetail?: RiskDetail | null;
  riskUpdatedAt?: number | null;
  riskSource?: "ws" | "poll" | null;
  todayRecordCount?: number;
}

const pct = (value: number) => `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;

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
    const labels = ["平静", "喜悦", "惊讶", "低落", "愤怒", "厌恶", "紧张", "轻蔑"];
    const label =
      Number.isFinite(exprId) && exprId >= 0 && exprId < labels.length
        ? labels[Math.floor(exprId)]
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
    return { label, confidence, primary };
  }, [riskDetail, scores]);

  const updated = riskUpdatedAt
    ? new Date(riskUpdatedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : "等待数据";

  return (
    <div className="h-full min-h-[760px] rounded-[2.35rem] border border-white/5 bg-[radial-gradient(circle_at_top,rgba(99,102,241,0.18),transparent_38%),rgba(12,18,34,0.72)] backdrop-blur-3xl p-7 shadow-2xl flex flex-col overflow-hidden">
      <div className="flex items-center justify-between">
        <span className="inline-flex items-center gap-2 rounded-full border border-white/8 bg-white/[0.03] px-3 py-1.5 text-[10px] font-black uppercase tracking-[0.25em] text-slate-400">
          <Waves size={11} className="text-indigo-300" />
          {mode === "privacy" ? "隐私守护" : "情绪摘要"}
        </span>
        <span className="text-[10px] font-bold text-slate-500">{todayRecordCount} 条记录</span>
      </div>

      <div className="mt-8">
        <div className="text-[12px] font-black uppercase tracking-[0.35em] text-indigo-300/70">Current Mood</div>
        <div className="mt-3 flex items-end gap-3">
          <div className="text-5xl font-black tracking-tight text-white">{summary.label}</div>
          <div className="pb-1 text-sm font-semibold text-slate-400">{pct(scores.S)}</div>
        </div>
        <p className="mt-3 max-w-[220px] text-sm leading-7 font-semibold text-slate-400">
          当前主导维度是{summary.primary.label}，这一列只保留即时摘要，不再堆很多同层级卡片。
        </p>
      </div>

      <div className="mt-8 flex items-center justify-center">
        <div className="relative h-48 w-48">
          <div className="absolute inset-0 rounded-full bg-indigo-500/10 blur-[60px]" />
          <div className="absolute inset-[14px] rounded-full border border-indigo-400/12" />
          <div className="absolute inset-[32px] rounded-full border border-white/6" />
          <div className="absolute inset-[50px] rounded-full border border-white/5 flex items-center justify-center">
            <Sparkle size={54} className="text-indigo-300 animate-[pulse_3s_infinite]" strokeWidth={1.7} />
          </div>
          <div className="absolute left-1/2 top-2 h-2.5 w-2.5 -translate-x-1/2 rounded-full bg-indigo-300/70 shadow-[0_0_16px_rgba(129,140,248,0.65)]" />
        </div>
      </div>

      <div className="mt-8 space-y-3">
        <div className="rounded-[1.6rem] border border-white/6 bg-white/[0.03] p-4">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-[0.24em] text-slate-500">识别状态</div>
              <div className="mt-2 text-lg font-black text-white">
                {summary.confidence > 0 ? `${Math.round(summary.confidence * 100)}%` : "--"}
              </div>
            </div>
            <Activity size={18} className="text-cyan-300" />
          </div>
          <div className="mt-2 text-xs font-semibold text-slate-400">
            来源：{riskSource === "ws" ? "实时推送" : riskSource === "poll" ? "轮询刷新" : "等待接入"}
          </div>
        </div>

        <div className="rounded-[1.6rem] border border-white/6 bg-white/[0.03] p-4">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-[0.24em] text-slate-500">最近刷新</div>
              <div className="mt-2 text-lg font-black text-white">{updated}</div>
            </div>
            {mode === "privacy" ? (
              <ShieldHalf size={18} className="text-emerald-300" />
            ) : (
              <Clock3 size={18} className="text-slate-300" />
            )}
          </div>
          <div className="mt-2 text-xs font-semibold text-slate-400">
            {mode === "privacy" ? "当前处于隐私模式" : "当前处于正常采集模式"}
          </div>
        </div>
      </div>

      <div className="mt-8 rounded-[1.8rem] border border-white/6 bg-white/[0.02] p-5">
        <div className="text-[10px] font-black uppercase tracking-[0.24em] text-slate-500">风险维度</div>
        <div className="mt-4 space-y-4">
          {[
            { key: "S", label: "压力", value: scores.S },
            { key: "T", label: "疲惫", value: scores.T },
            { key: "A", label: "唤醒", value: scores.A },
          ].map((item) => (
            <div key={item.key}>
              <div className="mb-2 flex items-center justify-between text-sm font-semibold text-slate-300">
                <span>{item.label}</span>
                <span className="text-slate-500">{pct(item.value)}</span>
              </div>
              <div className="h-2 rounded-full bg-white/[0.04] overflow-hidden">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-indigo-400 via-cyan-300 to-fuchsia-400"
                  style={{ width: pct(item.value) }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
