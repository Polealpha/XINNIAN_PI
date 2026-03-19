import React, { useEffect, useMemo, useState } from "react";
import { ArrowRight, CheckCircle2, Info, RefreshCw, Router, Wifi } from "lucide-react";
import {
  configureDeviceWifiLocal,
  getDeviceOnboardingState,
  listDeviceOnboardingNetworks,
} from "../services/deviceService";

interface ProvisioningProps {
  onComplete: () => void;
  isEmbedded?: boolean;
}

type Step = "idle" | "configuring" | "success";

const DEFAULT_DEVICE_HOST = "192.168.4.1:8090";

export const Provisioning: React.FC<ProvisioningProps> = ({ onComplete, isEmbedded = false }) => {
  const [step, setStep] = useState<Step>("idle");
  const [deviceHost, setDeviceHost] = useState(() => localStorage.getItem("device_runtime_host") || DEFAULT_DEVICE_HOST);
  const [ssid, setSsid] = useState("");
  const [password, setPassword] = useState("");
  const [deviceState, setDeviceState] = useState<Record<string, any> | null>(null);
  const [networks, setNetworks] = useState<Array<{ ssid: string; signal?: number }>>([]);
  const [loadingNetworks, setLoadingNetworks] = useState(false);
  const [progressText, setProgressText] = useState("等待开始");
  const [error, setError] = useState("");

  useEffect(() => {
    if (step !== "success") return;
    const timer = window.setTimeout(onComplete, 1200);
    return () => window.clearTimeout(timer);
  }, [step, onComplete]);

  const normalizedHost = useMemo(() => String(deviceHost || "").trim(), [deviceHost]);

  const refreshState = async () => {
    if (!normalizedHost) {
      setError("请先输入树莓派本地地址");
      return;
    }
    setError("");
    try {
      const state = await getDeviceOnboardingState(normalizedHost);
      setDeviceState(state);
      if (!ssid && state?.connected_ssid) {
        setSsid(String(state.connected_ssid));
      }
      localStorage.setItem("device_runtime_host", normalizedHost);
    } catch (err) {
      console.error(err);
      setError("无法读取树莓派本地配网状态，请确认电脑已连上机器人热点。");
    }
  };

  const refreshNetworks = async () => {
    if (!normalizedHost) {
      setError("请先输入树莓派本地地址");
      return;
    }
    setLoadingNetworks(true);
    setError("");
    try {
      const result = await listDeviceOnboardingNetworks(normalizedHost);
      setNetworks(Array.isArray(result?.networks) ? result.networks : []);
      localStorage.setItem("device_runtime_host", normalizedHost);
    } catch (err) {
      console.error(err);
      setError("扫描 Wi-Fi 失败，请确认树莓派热点和本地运行时接口可访问。");
    } finally {
      setLoadingNetworks(false);
    }
  };

  const startProvisioning = async () => {
    if (!normalizedHost) {
      setError("请先输入树莓派本地地址");
      return;
    }
    if (!ssid.trim()) {
      setError("请输入要连接的家庭 Wi-Fi 名称");
      return;
    }
    setError("");
    setStep("configuring");
    setProgressText("正在把家庭 Wi‑Fi 写入树莓派");
    try {
      const result = await configureDeviceWifiLocal(normalizedHost, ssid.trim(), password);
      localStorage.setItem("device_runtime_host", normalizedHost);
      setDeviceState(result?.state || null);
      setProgressText("树莓派已收到新网络配置，正在切换网络");
      setStep("success");
    } catch (err) {
      console.error(err);
      setStep("idle");
      setProgressText("等待开始");
      setError("配网失败，请检查热点连接、IP 地址和 Wi‑Fi 密码。");
    }
  };

  const containerClass = isEmbedded
    ? "w-full h-full flex flex-col justify-center px-4"
    : "min-h-screen flex items-center justify-center p-6 bg-slate-950 relative overflow-hidden";

  const cardClass = isEmbedded
    ? "w-full text-left space-y-6"
    : "w-full max-w-2xl bg-slate-900/50 backdrop-blur-3xl border border-white/5 rounded-[2rem] p-8 shadow-2xl relative z-10 space-y-6";

  return (
    <div className={containerClass}>
      {!isEmbedded && (
        <div className="absolute inset-0 pointer-events-none bg-[radial-gradient(circle_at_top,rgba(59,130,246,0.18),transparent_38%),radial-gradient(circle_at_bottom_right,rgba(16,185,129,0.14),transparent_30%)]" />
      )}

      <div className={cardClass}>
        <div className="flex items-center gap-4">
          <div className="w-16 h-16 rounded-3xl bg-indigo-500/15 text-indigo-300 flex items-center justify-center shadow-inner">
            {step === "success" ? <CheckCircle2 size={34} /> : <Router size={34} />}
          </div>
          <div className="space-y-1">
            <h2 className="text-2xl font-black text-white tracking-tight">树莓派本地配网</h2>
            <p className="text-sm text-slate-400">
              这一步已经迁移到 Pi 本地热点接口，不再使用旧 BLE / SoftAP 固件配网链。
            </p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-[11px] font-black text-slate-500 uppercase tracking-[0.18em]">Pi Runtime Host</label>
              <input
                value={deviceHost}
                onChange={(event) => setDeviceHost(event.target.value)}
                className="w-full bg-slate-800/60 border border-white/5 rounded-2xl py-3 px-4 text-white font-bold outline-none focus:ring-2 focus:ring-indigo-500/30"
                placeholder="192.168.4.1:8090"
              />
            </div>
            <div className="space-y-2">
              <label className="text-[11px] font-black text-slate-500 uppercase tracking-[0.18em]">家庭 Wi‑Fi</label>
              <input
                value={ssid}
                onChange={(event) => setSsid(event.target.value)}
                className="w-full bg-slate-800/60 border border-white/5 rounded-2xl py-3 px-4 text-white font-bold outline-none focus:ring-2 focus:ring-indigo-500/30"
                placeholder="例如：POLEALPHA"
              />
            </div>
            <div className="space-y-2">
              <label className="text-[11px] font-black text-slate-500 uppercase tracking-[0.18em]">Wi‑Fi Password</label>
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="w-full bg-slate-800/60 border border-white/5 rounded-2xl py-3 px-4 text-white font-bold outline-none focus:ring-2 focus:ring-indigo-500/30"
                placeholder="留空表示开放网络"
              />
            </div>
            <div className="flex flex-wrap gap-3">
              <button
                onClick={refreshState}
                className="px-4 py-3 rounded-2xl bg-slate-800 text-slate-100 font-bold inline-flex items-center gap-2"
              >
                <Info size={16} />
                读取状态
              </button>
              <button
                onClick={refreshNetworks}
                className="px-4 py-3 rounded-2xl bg-slate-800 text-slate-100 font-bold inline-flex items-center gap-2"
                disabled={loadingNetworks}
              >
                <RefreshCw size={16} className={loadingNetworks ? "animate-spin" : ""} />
                扫描网络
              </button>
              <button
                onClick={startProvisioning}
                className="px-5 py-3 rounded-2xl bg-white text-slate-950 font-black inline-flex items-center gap-2 shadow-lg"
              >
                开始配网
                <ArrowRight size={16} />
              </button>
            </div>
            {error ? <p className="text-sm text-rose-400 font-bold">{error}</p> : null}
            {step === "configuring" ? <p className="text-sm text-indigo-300 font-bold">{progressText}</p> : null}
            {step === "success" ? (
              <p className="text-sm text-emerald-300 font-bold">Wi‑Fi 已写入树莓派，本地运行时正在切换到新网络。</p>
            ) : null}
          </div>

          <div className="space-y-4">
            <div className="rounded-3xl border border-white/5 bg-slate-950/40 p-4 space-y-3">
              <h3 className="text-sm font-black text-white uppercase tracking-[0.18em]">运行状态</h3>
              <div className="text-sm text-slate-300 space-y-2">
                <div>当前模式：{String(deviceState?.mode || deviceState?.state || "unknown")}</div>
                <div>已连接 Wi‑Fi：{String(deviceState?.connected_ssid || "未连接")}</div>
                <div>热点 SSID：{String(deviceState?.hotspot_ssid || "EmotionPi-Setup")}</div>
              </div>
            </div>

            <div className="rounded-3xl border border-white/5 bg-slate-950/40 p-4 space-y-3">
              <h3 className="text-sm font-black text-white uppercase tracking-[0.18em]">附近网络</h3>
              {networks.length ? (
                <div className="space-y-2 max-h-52 overflow-auto pr-1">
                  {networks.map((item) => (
                    <button
                      key={`${item.ssid}-${item.signal ?? "na"}`}
                      onClick={() => setSsid(String(item.ssid || ""))}
                      className="w-full rounded-2xl border border-white/5 bg-slate-800/60 px-3 py-3 text-left hover:border-indigo-400/40"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-sm font-bold text-white">{item.ssid || "隐藏网络"}</span>
                        <span className="text-xs text-slate-400 inline-flex items-center gap-1">
                          <Wifi size={12} />
                          {item.signal ?? "--"}
                        </span>
                      </div>
                    </button>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-slate-400">还没扫描到网络。电脑连上机器人热点后，点“扫描网络”。</p>
              )}
            </div>

            <div className="rounded-3xl border border-indigo-400/10 bg-indigo-500/5 p-4 flex items-start gap-3">
              <Info size={18} className="text-indigo-300 mt-0.5 shrink-0" />
              <p className="text-sm text-indigo-200/90 leading-relaxed">
                这一步只负责把树莓派接入家庭网络。设备认领、主人绑定和首次人格测评，会在登录后的激活流程里继续完成。
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
