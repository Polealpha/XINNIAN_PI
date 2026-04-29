import React, { useEffect, useMemo, useState } from "react";

import { CameraPanel } from "./CameraPanel";
import { getLocalApiBase } from "../services/apiClient";
import { getVisualfocusDemoHealth, VisualfocusDemoHealth } from "../services/demoService";

const cardCls =
  "rounded-[1.6rem] border border-white/10 bg-white/6 px-5 py-4 shadow-[0_16px_40px_rgba(10,20,40,0.22)] backdrop-blur";

const formatCheckpointName = (health: VisualfocusDemoHealth | null) => {
  if (!health?.checkpoint) return "unknown";
  const value = String(health.checkpoint);
  const parts = value.replace(/\\/g, "/").split("/");
  return parts[parts.length - 1] || value;
};

export const VisualfocusDemoApp: React.FC = () => {
  const [health, setHealth] = useState<VisualfocusDemoHealth | null>(null);
  const [healthError, setHealthError] = useState("");
  const [loading, setLoading] = useState(true);
  const localApiBase = getLocalApiBase();

  const refreshHealth = async () => {
    try {
      setHealthError("");
      const next = await getVisualfocusDemoHealth();
      setHealth(next);
    } catch (err) {
      setHealthError(err instanceof Error ? err.message : String(err || "health unavailable"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refreshHealth();
    const timer = window.setInterval(() => {
      void refreshHealth();
    }, 15000);
    return () => window.clearInterval(timer);
  }, []);

  const modelLabel = useMemo(() => {
    if (!health) return "loading";
    return health.model_name || formatCheckpointName(health);
  }, [health]);

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,rgba(80,160,255,0.18),transparent_28%),radial-gradient(circle_at_top_right,rgba(255,150,180,0.12),transparent_24%),linear-gradient(180deg,#09101b_0%,#0b111d_42%,#080d17_100%)] text-white">
      <div className="mx-auto flex min-h-screen max-w-[1560px] flex-col gap-4 px-5 py-5">
        <section className="rounded-[2rem] border border-white/10 bg-white/6 px-6 py-5 shadow-[0_20px_60px_rgba(8,15,30,0.35)] backdrop-blur">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="text-[11px] font-black tracking-[0.28em] text-sky-200/80">
                VISUALFOCUS DEMO
              </div>
              <h1 className="mt-2 text-[2rem] font-black tracking-[-0.05em] text-white">
                主动式判别网页测试页
              </h1>
              <p className="mt-2 max-w-[980px] text-sm leading-7 text-slate-300">
                这个页面直接调用本机摄像头和麦克风，再通过本地后端桥接到远端最佳模型（best checkpoint，当前最优检查点）做推理（inference，模型预测）。
              </p>
            </div>
            <button
              type="button"
              onClick={() => void refreshHealth()}
              className="rounded-full border border-sky-300/30 bg-sky-400/10 px-4 py-2 text-xs font-black tracking-[0.2em] text-sky-100 transition hover:bg-sky-400/20"
            >
              刷新状态
            </button>
          </div>

          <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <div className={cardCls}>
              <div className="text-[10px] font-black tracking-[0.2em] text-slate-400">本地网页</div>
              <div className="mt-2 text-sm font-bold text-white">/visualfocus-demo.html</div>
              <div className="mt-1 break-all text-xs text-slate-400">http://127.0.0.1:3001/visualfocus-demo.html</div>
            </div>
            <div className={cardCls}>
              <div className="text-[10px] font-black tracking-[0.2em] text-slate-400">本地后端</div>
              <div className="mt-2 text-sm font-bold text-white">{localApiBase}</div>
              <div className="mt-1 text-xs text-slate-400">
                {loading ? "检测中" : healthError ? "状态读取失败" : "本地桥接可用"}
              </div>
            </div>
            <div className={cardCls}>
              <div className="text-[10px] font-black tracking-[0.2em] text-slate-400">当前模型</div>
              <div className="mt-2 text-sm font-bold text-emerald-200">{modelLabel}</div>
              <div className="mt-1 text-xs text-slate-400">
                {health?.runtime_device ? `device（设备）: ${health.runtime_device}` : "等待远端 health（健康检查）"}
              </div>
            </div>
            <div className={cardCls}>
              <div className="text-[10px] font-black tracking-[0.2em] text-slate-400">桥接方式</div>
              <div className="mt-2 text-sm font-bold text-white">{health?.bridge_mode || "ssh_curl"}</div>
              <div className="mt-1 text-xs text-slate-400">
                {health?.remote_ok ? "远端最佳模型在线" : healthError || health?.remote_error || "等待状态"}
              </div>
            </div>
          </div>

          {health?.checkpoint ? (
            <div className="mt-4 rounded-[1.35rem] border border-emerald-300/20 bg-emerald-400/8 px-4 py-3 text-xs text-emerald-50">
              checkpoint（检查点）: <span className="font-bold">{health.checkpoint}</span>
            </div>
          ) : null}
          <div className="mt-3 rounded-[1.35rem] border border-sky-300/15 bg-sky-400/8 px-4 py-3 text-xs leading-6 text-sky-50">
            这页现在只保留本机摄像头，不再显示机器人 / 移动端相机。首次测试时，请在浏览器里允许 camera / microphone（摄像头 / 麦克风）权限；如果没弹权限框，就点地址栏左侧的小相机图标手动允许。当前网页的真实链路是：
            本机摄像头 {"->"} 本地人脸定位与特征提取 {"->"} 本地后端桥接 {"->"} 远端最佳模型{" "}
            <code>epoch_004</code> 推理（模型预测） {"->"} 网页展示结果。
            FER+ / MediaPipe 在这里主要负责本地前端的人脸框与兜底（fallback，远端不可用时的回退）。
          </div>
        </section>

        <section className="flex-1 min-h-0">
          <CameraPanel
            status={null}
            active
            videoEnabled
            showRobotCamera={false}
            analysisIntervalMs={1200}
          />
        </section>
      </div>
    </div>
  );
};
