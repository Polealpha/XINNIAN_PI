import React from "react";
import { RiskScores, EngineMode } from "../types";
import { ShieldAlert, Wifi, Activity } from "lucide-react";

interface LiveViewProps {
  scores: RiskScores;
  mode: EngineMode;
  isSameNetwork: boolean;
}

export const LiveView: React.FC<LiveViewProps> = ({ scores, mode, isSameNetwork }) => {
  return (
    <div className="space-y-6 animate-pop-in">
      <div className="relative group overflow-hidden rounded-[2.5rem] bg-slate-900 border-4 border-slate-800 shadow-2xl aspect-video flex items-center justify-center">
        {mode === "privacy" ? (
          <div className="flex flex-col items-center gap-4 text-slate-500">
            <ShieldAlert size={64} className="animate-pulse" />
            <span className="font-black uppercase tracking-widest text-sm">隐私保护模式已开启</span>
          </div>
        ) : (
          <>
            <img
              src="https://images.unsplash.com/photo-1542744173-8e7e53415bb0?auto=format&fit=crop&q=80&w=640"
              alt="实时画面"
              className="w-full h-full object-cover opacity-60 grayscale-[0.5]"
            />
            <div className="absolute top-4 left-4 flex items-center gap-2 px-3 py-1.5 bg-red-500/80 rounded-full text-[10px] font-black uppercase text-white animate-pulse">
              <span className="w-1.5 h-1.5 bg-white rounded-full"></span> 实时监控
            </div>

            <div className="absolute bottom-4 right-4 flex gap-2">
              <div className="px-3 py-1 bg-black/60 backdrop-blur-md rounded-lg border border-white/10 text-[10px] font-bold text-white uppercase">
                帧率: 5.2
              </div>
              <div className="px-3 py-1 bg-black/60 backdrop-blur-md rounded-lg border border-white/10 text-[10px] font-bold text-white uppercase">
                320x240
              </div>
            </div>
          </>
        )}
      </div>

      <div className="grid grid-cols-2 gap-4">
        {[
          { label: "V - 视觉特征", val: scores.V, color: "from-blue-400 to-indigo-500" },
          { label: "A - 声学指标", val: scores.A, color: "from-purple-400 to-fuchsia-500" },
          { label: "T - 语义分析", val: scores.T, color: "from-emerald-400 to-teal-500" },
          { label: "S - 综合压力", val: scores.S, color: "from-orange-400 to-red-500", full: true },
        ].map((item, i) => (
          <div
            key={item.label}
            className={`${
              item.full ? "col-span-2" : ""
            } bg-slate-800/40 backdrop-blur-xl p-5 rounded-[2rem] border border-white/5 shadow-xl q-bounce`}
            style={{ animationDelay: `${i * 100}ms` }}
          >
            <div className="flex justify-between items-center mb-3">
              <span className="text-[10px] font-black uppercase tracking-widest text-slate-400">
                {item.label}
              </span>
              <span className={`text-lg font-black bg-clip-text text-transparent bg-gradient-to-r ${item.color}`}>
                {(item.val * 100).toFixed(0)}%
              </span>
            </div>
            <div className="h-2.5 w-full bg-slate-900 rounded-full overflow-hidden shadow-inner">
              <div
                className={`h-full rounded-full bg-gradient-to-r ${item.color} transition-all duration-500 ease-out shadow-[0_0_10px_rgba(255,255,255,0.2)]`}
                style={{ width: `${item.val * 100}%` }}
              ></div>
            </div>
          </div>
        ))}
      </div>

      <div className="bg-indigo-600/10 border border-indigo-500/20 rounded-[2rem] p-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div
            className={`p-2 rounded-full ${
              isSameNetwork ? "bg-green-500/20 text-green-400" : "bg-yellow-500/20 text-yellow-400"
            }`}
          >
            <Wifi size={18} />
          </div>
          <div>
            <p className="text-xs font-black text-white uppercase">本地引擎状态</p>
            <p className="text-[10px] text-slate-400 font-bold">
              {isSameNetwork ? "已连接：同一局域网" : "警告：网络环境不一致"}
            </p>
          </div>
        </div>
        <Activity size={20} className="text-indigo-400 animate-pulse" />
      </div>
    </div>
  );
};
