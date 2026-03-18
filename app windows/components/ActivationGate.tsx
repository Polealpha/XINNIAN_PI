import React, { useMemo, useState } from "react";
import { CheckCircle2, RefreshCcw, ShieldCheck } from "lucide-react";

interface ActivationGateProps {
  activationPath: string;
  backendBase: string;
  token: string;
  onActivated: () => Promise<void> | void;
}

export const ActivationGate: React.FC<ActivationGateProps> = ({
  activationPath,
  backendBase,
  token,
  onActivated,
}) => {
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");

  const activationUrl = useMemo(() => {
    const base = String(backendBase || "").replace(/\/+$/, "");
    const path = String(activationPath || "/activate").startsWith("/")
      ? String(activationPath || "/activate")
      : `/${String(activationPath || "activate")}`;
    const url = new URL(`${base}${path}`);
    url.searchParams.set("token", token);
    return url.toString();
  }, [activationPath, backendBase, token]);

  const handleCheck = async () => {
    setChecking(true);
    setError("");
    try {
      await onActivated();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setChecking(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#070b14] text-slate-100 flex flex-col">
      <div className="px-8 py-6 border-b border-white/10 bg-slate-950/60 backdrop-blur-xl flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 rounded-2xl bg-emerald-500/15 text-emerald-300 flex items-center justify-center border border-emerald-500/20">
            <ShieldCheck size={24} />
          </div>
          <div>
            <h1 className="text-xl font-black tracking-tight">首次激活</h1>
            <p className="text-sm text-slate-400">
              先确认这个人是谁，再进入完整桌面端。身份卡确认后，聊天和机器人联动才会按正确身份运行。
            </p>
          </div>
        </div>
        <button
          onClick={handleCheck}
          disabled={checking}
          className="px-5 py-3 rounded-2xl bg-white text-slate-950 font-black text-sm flex items-center gap-2 disabled:opacity-60"
        >
          {checking ? <RefreshCcw size={16} className="animate-spin" /> : <CheckCircle2 size={16} />}
          我已完成激活
        </button>
      </div>

      <div className="flex-1 p-6">
        <div className="h-full rounded-[2rem] overflow-hidden border border-white/10 bg-slate-950/40 shadow-2xl">
          <iframe
            src={activationUrl}
            title="activation"
            className="w-full h-full border-0 bg-white"
            allow="clipboard-read; clipboard-write"
          />
        </div>
        {error ? <p className="mt-4 text-sm text-rose-400 font-bold">{error}</p> : null}
      </div>
    </div>
  );
};
