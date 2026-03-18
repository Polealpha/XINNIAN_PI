import React from "react";
import { RiskScores, EngineMode } from "../types";
import { Sparkle, Waves } from "lucide-react";

interface AtmosphereViewProps {
  scores: RiskScores;
  mode: EngineMode;
}

export const AtmosphereView: React.FC<AtmosphereViewProps> = ({ scores, mode }) => {
  const isAnxious = scores.S > 0.6;
  const label = mode === "privacy" ? "隐私守护" : isAnxious ? "能量激活" : "心境共鸣";

  return (
    <div className="h-full bg-[#0c1222]/40 backdrop-blur-3xl rounded-[2.5rem] border border-white/[0.05] p-10 flex flex-col items-center justify-center text-center shadow-2xl relative overflow-hidden group animate-pop-in">
      <div className="relative z-10 mb-8 flex flex-col items-center">
        <div className="relative w-40 h-40 flex items-center justify-center">
          <div className="absolute inset-0 bg-indigo-500/10 blur-[60px] rounded-full animate-pulse"></div>

          <div
            className={`relative w-32 h-32 rounded-full border border-white/[0.03] flex items-center justify-center ${
              isAnxious ? "text-orange-400" : "text-indigo-400/80"
            }`}
          >
            <Sparkle size={64} className="animate-[pulse_3s_infinite]" strokeWidth={1.5} />
          </div>

          <div className="absolute inset-0 border border-white/[0.02] rounded-full animate-[spin_20s_linear_infinite]"></div>
          <div className="absolute w-2 h-2 bg-indigo-400/30 rounded-full top-0 left-1/2 -translate-x-1/2 -translate-y-1 shadow-[0_0_8px_rgba(99,102,241,0.5)]"></div>
        </div>
      </div>

      <div className="space-y-4 relative z-10">
        <div className="inline-flex items-center gap-2 px-4 py-1.5 bg-white/[0.03] rounded-full border border-white/[0.05]">
          <Waves size={10} className="text-slate-500" />
          <span className="text-[9px] font-black text-slate-500 uppercase tracking-widest">{label}</span>
        </div>
        <p className="text-slate-400 text-xs font-bold max-w-[180px] leading-relaxed tracking-tight">
          正在同步您的生物识别反馈，当前场域处于{isAnxious ? "活跃" : "深度稳定"}状态。
        </p>
      </div>

      <div className="absolute bottom-6 left-0 right-0 flex justify-center gap-1 opacity-20">
        {[1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="w-1 h-1 bg-white rounded-full"></div>
        ))}
      </div>
    </div>
  );
};
