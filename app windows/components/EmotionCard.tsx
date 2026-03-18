import React from "react";
import { EmotionEvent, EmotionType } from "../types";
import { Cloud, Moon, Sun, Wind, Zap } from "lucide-react";

interface EmotionCardProps {
  event: EmotionEvent;
  isLatest?: boolean;
  isLast?: boolean;
  index: number;
}

const getEmotionConfig = (type: EmotionType) => {
  switch (type) {
    case EmotionType.HAPPY:
      return { label: "喜悦场域", bg: "bg-indigo-500/10", accent: "text-yellow-400", Icon: Sun };
    case EmotionType.ANGRY:
      return { label: "能量激荡", bg: "bg-rose-500/10", accent: "text-rose-400", Icon: Zap };
    case EmotionType.TIRED:
      return { label: "低能时刻", bg: "bg-slate-500/10", accent: "text-indigo-300", Icon: Moon };
    case EmotionType.ANXIOUS:
      return { label: "频率波动", bg: "bg-cyan-500/10", accent: "text-cyan-400", Icon: Wind };
    default:
      return { label: "稳态感知", bg: "bg-slate-800/10", accent: "text-slate-400", Icon: Cloud };
  }
};

export const EmotionCard: React.FC<EmotionCardProps> = ({ event, isLatest, isLast, index }) => {
  const config = getEmotionConfig(event.type);
  const Icon = config.Icon;
  const intensity = Math.round(event.intensity ?? 0);

  return (
    <div className="flex gap-6 relative animate-pop-in group" style={{ animationDelay: `${index * 80}ms` }}>
      {!isLast && (
        <div className="absolute left-[1.95rem] top-10 bottom-[-1.5rem] w-px bg-gradient-to-b from-slate-700/50 to-transparent"></div>
      )}

      <div className="flex flex-col items-center pt-1 w-16 flex-shrink-0 z-10">
        <span className="text-[10px] font-black text-slate-600 group-hover:text-indigo-400 transition-colors">
          {event.timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
        </span>
        <div
          className={`mt-3 w-3 h-3 rounded-full border-2 border-slate-950 transition-all duration-500 ${
            isLatest ? "bg-indigo-400 scale-125 shadow-[0_0_15px_rgba(99,102,241,0.6)]" : "bg-slate-800 group-hover:bg-slate-600"
          }`}
        ></div>
      </div>

      <div
        className={`flex-1 mb-8 rounded-[2rem] ${config.bg} border border-white/5 p-5 hover:border-white/20 transition-all duration-500 backdrop-blur-sm relative overflow-hidden`}
      >
        {isLatest && (
          <div className="absolute top-0 right-0 p-2">
            <div className="w-1.5 h-1.5 bg-indigo-400 rounded-full animate-pulse"></div>
          </div>
        )}

        <div className="flex flex-col gap-3">
          <div className={`inline-flex items-center gap-2 ${config.accent}`}>
            <Icon size={14} strokeWidth={3} />
            <span className="text-[10px] font-black uppercase tracking-[0.2em]">{config.label}</span>
          </div>
          <p className="text-xs font-bold text-slate-400 leading-relaxed group-hover:text-slate-200 transition-colors">
            {event.description}
          </p>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5 text-[9px] text-slate-600 font-black uppercase tracking-tighter">
              <Zap size={10} className="text-fuchsia-500" />
              <span>强度: {intensity}%</span>
            </div>
            <div className="h-1 w-12 bg-slate-800 rounded-full overflow-hidden">
              <div className="h-full bg-indigo-500" style={{ width: `${intensity}%` }}></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
