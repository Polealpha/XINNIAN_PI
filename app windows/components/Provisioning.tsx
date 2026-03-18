import React, { useEffect, useState } from "react";
import { Wifi, Sparkles, ArrowRight, CheckCircle2, Info, Smartphone } from "lucide-react";
import { provisionDevice } from "../services/deviceService";

interface ProvisioningProps {
  onComplete: () => void;
  isEmbedded?: boolean;
}

export const Provisioning: React.FC<ProvisioningProps> = ({ onComplete, isEmbedded = false }) => {
  const [step, setStep] = useState<"idle" | "pairing" | "success">("idle");
  const [progress, setProgress] = useState(0);
  const [ssid, setSsid] = useState("");
  const [password, setPassword] = useState("");
  const [deviceId, setDeviceId] = useState("xinian-001");
  const [deviceIp, setDeviceIp] = useState(() => localStorage.getItem("device_ip") || "");
  const [error, setError] = useState("");
  const defaultBleService = "PROV_XINNIAN";
  const defaultSoftapHost = "192.168.4.1:80";
  const [transport, setTransport] = useState<"ble" | "softap">("ble");
  const [serviceName, setServiceName] = useState(defaultBleService);
  const [pop, setPop] = useState("1234");

  useEffect(() => {
    setServiceName((prev) => {
      if (transport === "ble" && prev === defaultSoftapHost) return defaultBleService;
      if (transport === "softap" && prev === defaultBleService) return defaultSoftapHost;
      return prev;
    });
  }, [transport, defaultBleService, defaultSoftapHost]);

  const startPairing = async () => {
    if (!ssid.trim()) {
      setError("Wi-Fi SSID required");
      return;
    }
    if (!serviceName.trim()) {
      setError("Provisioning service required");
      return;
    }
    if (!pop.trim()) {
      setError("POP required");
      return;
    }
    setError("");
    setStep("pairing");
    setProgress(20);
    try {
      const result = await provisionDevice(
        deviceId.trim(),
        ssid.trim(),
        password,
        deviceIp.trim() || undefined,
        {
          transport,
          serviceName: serviceName.trim(),
          pop: pop.trim(),
          timeoutSec: 120,
        }
      );
      if (!result.ok) {
        setStep("idle");
        setProgress(0);
        setError(result.message || "Provisioning failed");
        return;
      }
      if (deviceIp.trim()) {
        localStorage.setItem("device_ip", deviceIp.trim());
      }
      setProgress(100);
      setStep("success");
    } catch (err) {
      console.error(err);
      setStep("idle");
      setProgress(0);
      setError("Provisioning failed");
    }
  };

  useEffect(() => {
    if (step === "success") {
      const timer = setTimeout(() => {
        onComplete();
      }, 1500);
      return () => clearTimeout(timer);
    }
  }, [step, onComplete]);

  const containerClass = isEmbedded
    ? "w-full h-full flex flex-col justify-center px-4"
    : "min-h-screen flex items-center justify-center p-6 bg-slate-950 relative overflow-hidden";

  const cardClass = isEmbedded
    ? "w-full text-center space-y-8"
    : "w-full max-w-md bg-slate-900/40 backdrop-blur-3xl border border-white/5 rounded-[3.5rem] p-10 shadow-2xl relative z-10 text-center space-y-8";

  return (
    <div className={containerClass}>
      {!isEmbedded && (
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[500px] bg-indigo-500/10 blur-[100px] rounded-full"></div>
      )}

      <div className={cardClass}>
        {step === "idle" && (
          <div className="animate-pop-in space-y-8">
            <div className="flex justify-center gap-4 items-center">
              <div className="w-16 h-16 bg-slate-800 rounded-2xl flex items-center justify-center text-slate-400 shadow-inner">
                <Smartphone size={32} />
              </div>
              <div className="w-8 h-px bg-indigo-500/30"></div>
              <div className="w-20 h-20 bg-indigo-500/20 rounded-full flex items-center justify-center text-indigo-400 relative">
                <Wifi size={40} className="animate-pulse" />
                <div className="absolute inset-0 border border-indigo-400/20 rounded-full animate-ping"></div>
              </div>
            </div>

            <div className="space-y-3">
              <h2 className="text-2xl font-black text-white tracking-tight">开启心念连接</h2>
              <p className="text-slate-400 font-medium text-sm leading-relaxed px-2">
                为确保机器人能与手机实时同步数据，请务必连接和手机相同的 Wi-Fi 网络。
              </p>
            </div>

            <div className="bg-indigo-500/5 border border-indigo-500/10 rounded-3xl p-5 flex items-start gap-4 text-left shadow-inner">
              <Info size={18} className="text-indigo-400 shrink-0 mt-0.5" />
              <p className="text-[12px] text-indigo-300/80 font-bold leading-relaxed">
                网络一致性是“心念双灵”共鸣的基础，不同网络可能导致 1-2 秒的感应延迟。
              </p>
            </div>

            <div className="space-y-4 text-left">
              <div className="space-y-2">
                <label className="text-[10px] font-black text-slate-500 uppercase ml-2 tracking-[0.2em]">
                  Device ID
                </label>
                <input
                  value={deviceId}
                  onChange={(e) => setDeviceId(e.target.value)}
                  className="w-full bg-slate-800/50 border border-white/5 rounded-2xl py-3 px-4 text-white font-bold outline-none focus:ring-2 focus:ring-indigo-500/30"
                  placeholder="xinian-001"
                />
              </div>
              <div className="space-y-2">
                <label className="text-[10px] font-black text-slate-500 uppercase ml-2 tracking-[0.2em]">
                  Provision Mode
                </label>
                <select
                  value={transport}
                  onChange={(e) => setTransport(e.target.value as "ble" | "softap")}
                  className="w-full bg-slate-800/50 border border-white/5 rounded-2xl py-3 px-4 text-white font-bold outline-none focus:ring-2 focus:ring-indigo-500/30"
                >
                  <option value="ble">BLE</option>
                  <option value="softap">SoftAP</option>
                </select>
              </div>
              <div className="space-y-2">
                <label className="text-[10px] font-black text-slate-500 uppercase ml-2 tracking-[0.2em]">
                  Service / Host
                </label>
                <input
                  value={serviceName}
                  onChange={(e) => setServiceName(e.target.value)}
                  className="w-full bg-slate-800/50 border border-white/5 rounded-2xl py-3 px-4 text-white font-bold outline-none focus:ring-2 focus:ring-indigo-500/30"
                  placeholder={transport === "ble" ? "PROV_XINNIAN" : "192.168.4.1:80"}
                />
              </div>
              <div className="space-y-2">
                <label className="text-[10px] font-black text-slate-500 uppercase ml-2 tracking-[0.2em]">
                  POP
                </label>
                <input
                  value={pop}
                  onChange={(e) => setPop(e.target.value)}
                  className="w-full bg-slate-800/50 border border-white/5 rounded-2xl py-3 px-4 text-white font-bold outline-none focus:ring-2 focus:ring-indigo-500/30"
                  placeholder="1234"
                />
              </div>
              <div className="space-y-2">
                <label className="text-[10px] font-black text-slate-500 uppercase ml-2 tracking-[0.2em]">
                  Wi-Fi SSID
                </label>
                <input
                  value={ssid}
                  onChange={(e) => setSsid(e.target.value)}
                  className="w-full bg-slate-800/50 border border-white/5 rounded-2xl py-3 px-4 text-white font-bold outline-none focus:ring-2 focus:ring-indigo-500/30"
                  placeholder="Your Wi-Fi / hotspot"
                />
              </div>
              <div className="space-y-2">
                <label className="text-[10px] font-black text-slate-500 uppercase ml-2 tracking-[0.2em]">
                  Device IP (optional)
                </label>
                <input
                  value={deviceIp}
                  onChange={(e) => setDeviceIp(e.target.value)}
                  className="w-full bg-slate-800/50 border border-white/5 rounded-2xl py-3 px-4 text-white font-bold outline-none focus:ring-2 focus:ring-indigo-500/30"
                  placeholder="192.168.1.100"
                />
              </div>
              <div className="space-y-2">
                <label className="text-[10px] font-black text-slate-500 uppercase ml-2 tracking-[0.2em]">
                  Wi-Fi Password
                </label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full bg-slate-800/50 border border-white/5 rounded-2xl py-3 px-4 text-white font-bold outline-none focus:ring-2 focus:ring-indigo-500/30"
                  placeholder="Leave empty for open Wi-Fi"
                />
              </div>
            </div>

            <button
              onClick={startPairing}
              className="w-full bg-white text-slate-950 font-black py-5 rounded-2xl q-bounce flex items-center justify-center gap-3 shadow-2xl shadow-white/5 active:scale-95"
            >
              <span>开始配网同步</span>
              <ArrowRight size={20} />
            </button>
            {error && <p className="text-[11px] font-bold text-rose-400">{error}</p>}
          </div>
        )}

        {step === "pairing" && (
          <div className="animate-pop-in space-y-10 py-4">
            <div className="relative w-36 h-36 mx-auto">
              <div className="absolute inset-0 border-[6px] border-slate-800 rounded-full"></div>
              <svg className="w-full h-full -rotate-90">
                <circle
                  cx="72"
                  cy="72"
                  r="66"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="10"
                  strokeDasharray={414}
                  strokeDashoffset={414 - (414 * progress) / 100}
                  className="text-indigo-500 transition-all duration-700 ease-out"
                />
              </svg>
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="text-center">
                  <span className="text-2xl font-black text-white">{Math.floor(progress)}%</span>
                  <p className="text-[8px] font-bold text-slate-500 uppercase tracking-widest mt-1">握手中</p>
                </div>
              </div>
            </div>

            <div className="space-y-2">
              <h3 className="text-xl font-bold text-white tracking-tight">正在寻找场域共鸣...</h3>
              <p className="text-slate-500 text-xs font-bold uppercase tracking-widest animate-pulse">SYNCING SENSORS</p>
            </div>
          </div>
        )}

        {step === "success" && (
          <div className="animate-pop-in space-y-8 py-4">
            <div className="w-24 h-24 bg-emerald-500/20 rounded-full mx-auto flex items-center justify-center text-emerald-400 shadow-xl shadow-emerald-500/10">
              <CheckCircle2 size={56} className="animate-bounce" />
            </div>

            <div className="space-y-2">
              <h2 className="text-2xl font-black text-white tracking-tight">连接成功</h2>
              <p className="text-slate-400 font-medium text-sm">已建立稳定的心念同步信道</p>
            </div>

            <div className="inline-flex items-center gap-2 px-5 py-2 bg-emerald-500/10 rounded-full border border-emerald-500/20">
              <Sparkles size={14} className="text-emerald-400" />
              <span className="text-[10px] font-bold text-emerald-400 uppercase tracking-widest">能量场已就绪</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
