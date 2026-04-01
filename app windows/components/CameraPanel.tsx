import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Camera,
  CameraOff,
  Laptop,
  Maximize2,
  Minimize2,
  RefreshCw,
  ShieldCheck,
  Wifi,
  WifiOff,
} from "lucide-react";

import { analyzeCameraEmotion, CameraEmotionAnalyzeResponse } from "../services/emotionService";
import { DeviceStatus } from "../types";

interface CameraPanelProps {
  status: DeviceStatus | null;
  active?: boolean;
  videoEnabled?: boolean;
}

type CurvePoint = {
  ts: number;
  time: string;
  value: number;
  confidence: number;
  label: string;
};

type VideoLayoutBox = {
  left: number;
  top: number;
  width: number;
  height: number;
} | null;

const ROBOT_PROXY_BASE = "http://127.0.0.1:18080";

const formatPauseReason = (value: string) => {
  switch (String(value || "").toLowerCase()) {
    case "multiple_faces":
      return "画面里出现了多个人，已暂停识别";
    case "no_face":
      return "没有稳定检测到人脸";
    default:
      return value || "识别已暂停";
  }
};

export const CameraPanel: React.FC<CameraPanelProps> = ({
  status,
  active = false,
  videoEnabled = true,
}) => {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const localStageRef = useRef<HTMLDivElement | null>(null);
  const localStreamRef = useRef<MediaStream | null>(null);
  const captureCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const analysisTimerRef = useRef<number | null>(null);
  const analysisInFlightRef = useRef(false);

  const [localEnabled, setLocalEnabled] = useState(false);
  const [localReady, setLocalReady] = useState(false);
  const [localError, setLocalError] = useState("");
  const [snapshotNonce, setSnapshotNonce] = useState(() => Date.now());
  const [expandedCamera, setExpandedCamera] = useState<"local" | "robot" | null>(null);
  const [analysis, setAnalysis] = useState<CameraEmotionAnalyzeResponse | null>(null);
  const [analysisError, setAnalysisError] = useState("");
  const [curvePoints, setCurvePoints] = useState<CurvePoint[]>([]);
  const [videoBox, setVideoBox] = useState<VideoLayoutBox>(null);

  const robotOnline = Boolean(status?.online);
  const robotCameraReady = Boolean(status?.status?.camera_ready);
  const robotPreviewUrl = useMemo(
    () => `${ROBOT_PROXY_BASE}/snapshot?t=${snapshotNonce}`,
    [snapshotNonce]
  );

  const refreshVideoBox = () => {
    const stage = localStageRef.current;
    const video = videoRef.current;
    if (!stage || !video) {
      setVideoBox(null);
      return;
    }
    const stageRect = stage.getBoundingClientRect();
    const videoRect = video.getBoundingClientRect();
    if (!stageRect.width || !stageRect.height || !videoRect.width || !videoRect.height) {
      setVideoBox(null);
      return;
    }
    setVideoBox({
      left: videoRect.left - stageRect.left,
      top: videoRect.top - stageRect.top,
      width: videoRect.width,
      height: videoRect.height,
    });
  };

  useEffect(() => {
    if (!active || !localEnabled) return;
    let cancelled = false;

    const start = async () => {
      try {
        setLocalError("");
        setLocalReady(false);
        const stream = await navigator.mediaDevices.getUserMedia({
          video: {
            width: { ideal: 1280 },
            height: { ideal: 720 },
            facingMode: "user",
          },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        localStreamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play().catch(() => {});
          window.setTimeout(refreshVideoBox, 60);
        }
        if (!cancelled) {
          setLocalReady(true);
        }
      } catch (error) {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : String(error || "");
        setLocalError(message || "无法打开本机摄像头");
        setLocalEnabled(false);
      }
    };

    void start();

    return () => {
      cancelled = true;
      setLocalReady(false);
      if (localStreamRef.current) {
        localStreamRef.current.getTracks().forEach((track) => track.stop());
        localStreamRef.current = null;
      }
      if (videoRef.current) {
        videoRef.current.srcObject = null;
      }
    };
  }, [active, localEnabled]);

  useEffect(() => {
    if (!snapshotNonce) return;
    refreshVideoBox();
  }, [snapshotNonce, expandedCamera, localReady]);

  useEffect(() => {
    const onResize = () => refreshVideoBox();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    if (!active || !robotOnline || !robotCameraReady) return;
    const timer = window.setInterval(() => {
      setSnapshotNonce(Date.now());
    }, 350);
    return () => window.clearInterval(timer);
  }, [active, robotCameraReady, robotOnline]);

  useEffect(() => {
    if (active && videoEnabled && !localEnabled) {
      setLocalEnabled(true);
    }
  }, [active, localEnabled, videoEnabled]);

  const stopLocalCamera = () => {
    setLocalEnabled(false);
    setLocalReady(false);
    setAnalysis(null);
    setAnalysisError("");
    setCurvePoints([]);
    if (analysisTimerRef.current !== null) {
      window.clearInterval(analysisTimerRef.current);
      analysisTimerRef.current = null;
    }
    if (localStreamRef.current) {
      localStreamRef.current.getTracks().forEach((track) => track.stop());
      localStreamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
  };

  useEffect(() => {
    if (!active || !localEnabled || !localReady) return;
    let cancelled = false;

    const runAnalysis = async () => {
      if (cancelled || analysisInFlightRef.current) return;
      const video = videoRef.current;
      if (!video || video.readyState < 2) return;
      const width = video.videoWidth || 0;
      const height = video.videoHeight || 0;
      if (width <= 0 || height <= 0) return;
      let canvas = captureCanvasRef.current;
      if (!canvas) {
        canvas = document.createElement("canvas");
        captureCanvasRef.current = canvas;
      }
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.drawImage(video, 0, 0, width, height);
      const imageDataUrl = canvas.toDataURL("image/jpeg", 0.72);
      analysisInFlightRef.current = true;
      try {
        const result = await analyzeCameraEmotion({
          imageDataUrl,
          width,
          height,
          timestampMs: Date.now(),
          surface: "desktop",
        });
        if (cancelled) return;
        setAnalysis(result);
        setAnalysisError("");
        setCurvePoints((prev) => {
          const nextPoint: CurvePoint = {
            ts: result.timestamp_ms,
            time: new Date(result.timestamp_ms).toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit",
            }),
            value: Math.round((result.V || 0) * 100),
            confidence: Math.round((result.confidence || 0) * 100),
            label: result.emotion_label_zh || "未识别",
          };
          const merged = [...prev, nextPoint];
          return merged.slice(-60);
        });
      } catch (error) {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : String(error || "");
        setAnalysisError(message || "视觉识别调用失败");
      } finally {
        analysisInFlightRef.current = false;
      }
    };

    void runAnalysis();
    analysisTimerRef.current = window.setInterval(() => {
      void runAnalysis();
    }, 1200);

    return () => {
      cancelled = true;
      if (analysisTimerRef.current !== null) {
        window.clearInterval(analysisTimerRef.current);
        analysisTimerRef.current = null;
      }
    };
  }, [active, localEnabled, localReady]);

  const overlayBox = useMemo(() => {
    if (!analysis?.bbox || !videoBox) return null;
    return {
      left: videoBox.left + (analysis.bbox.left / 100) * videoBox.width,
      top: videoBox.top + (analysis.bbox.top / 100) * videoBox.height,
      width: (analysis.bbox.width / 100) * videoBox.width,
      height: (analysis.bbox.height / 100) * videoBox.height,
    };
  }, [analysis, videoBox]);

  const renderLocalCameraCard = (expanded = false) => (
    <div
      className={`flex flex-col overflow-hidden rounded-[2rem] border border-white/[0.06] bg-white/[0.03] ${
        expanded ? "min-h-[760px]" : "min-h-[640px]"
      }`}
    >
      <div className="flex items-center justify-between border-b border-white/[0.05] px-5 py-4">
        <div className="flex items-center gap-3">
          <Laptop size={16} className="text-cyan-300" />
          <div>
            <div className="text-[13px] font-black text-white">本机摄像头</div>
            <div className="text-[11px] font-semibold text-slate-500">FER+ / MediaPipe 实时识别</div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setExpandedCamera((current) => (current === "local" ? null : "local"))}
            className="inline-flex items-center gap-2 rounded-2xl border border-white/10 bg-white/5 px-3 py-2 text-[11px] font-bold text-slate-200 transition hover:bg-white/10"
          >
            {expanded ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
            {expanded ? "收起" : "放大"}
          </button>
          <span
            className={`rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest ${
              localReady ? "bg-emerald-500/15 text-emerald-200" : "bg-white/10 text-slate-400"
            }`}
          >
            {localReady ? "LIVE" : localEnabled ? "启动中" : "未开启"}
          </span>
        </div>
      </div>
      <div ref={localStageRef} className="relative flex flex-1 items-center justify-center bg-[#070b16] p-4">
        {localEnabled ? (
          <video
            ref={videoRef}
            autoPlay
            playsInline
            muted
            onLoadedMetadata={refreshVideoBox}
            onResize={refreshVideoBox}
            className="max-h-full max-w-full rounded-[1.5rem] object-contain shadow-[0_20px_80px_rgba(0,0,0,0.35)]"
          />
        ) : (
          <div className="flex flex-col items-center gap-4 text-slate-500">
            <CameraOff size={56} />
            <div className="text-[13px] font-bold">本机摄像头未开启</div>
          </div>
        )}

        {overlayBox ? (
          <div
            className={`pointer-events-none absolute rounded-[1.25rem] border-2 shadow-[0_0_0_1px_rgba(0,0,0,0.25)] ${
              analysis?.recognition_paused
                ? "border-amber-300"
                : "border-cyan-300 shadow-[0_0_32px_rgba(34,211,238,0.18)]"
            }`}
            style={{
              left: overlayBox.left,
              top: overlayBox.top,
              width: overlayBox.width,
              height: overlayBox.height,
            }}
          >
            <div
              className={`absolute -top-9 left-0 rounded-2xl border px-3 py-1.5 text-[11px] font-black ${
                analysis?.recognition_paused
                  ? "border-amber-300/30 bg-amber-500/15 text-amber-100"
                  : "border-cyan-300/30 bg-cyan-500/15 text-cyan-100"
              }`}
            >
              {analysis?.recognition_paused
                ? "识别暂停"
                : `${analysis?.emotion_label_zh || "未识别"} ${(analysis?.confidence || 0) * 100 > 0 ? `${((analysis?.confidence || 0) * 100).toFixed(1)}%` : ""}`}
            </div>
          </div>
        ) : null}

        {analysis?.recognition_paused ? (
          <div className="absolute bottom-6 left-6 rounded-2xl border border-amber-300/25 bg-black/45 px-4 py-2 text-[12px] font-semibold text-amber-100 backdrop-blur-md">
            {formatPauseReason(analysis.pause_reason)}
          </div>
        ) : null}

        {!localReady && localEnabled ? (
          <div className="absolute inset-0 flex items-center justify-center bg-black/35 backdrop-blur-[2px]">
            <div className="rounded-2xl border border-white/10 bg-black/50 px-5 py-3 text-sm font-semibold text-white">
              正在连接本机摄像头...
            </div>
          </div>
        ) : null}
      </div>
      <div className="border-t border-white/[0.05] px-5 py-4 text-[12px] leading-7 text-slate-400">
        {localError
          ? `本机相机错误：${localError}`
          : analysisError
            ? `视觉识别错误：${analysisError}`
            : "当前只在桌面端本地做实时视觉识别。若画面里出现多人，会自动暂停，避免把旁人也计入情绪曲线。"}
      </div>
    </div>
  );

  const renderRobotCameraCard = (expanded = false) => (
    <div
      className={`flex flex-col overflow-hidden rounded-[2rem] border border-white/[0.06] bg-white/[0.03] ${
        expanded ? "min-h-[760px]" : "min-h-[640px]"
      }`}
    >
      <div className="flex items-center justify-between border-b border-white/[0.05] px-5 py-4">
        <div className="flex items-center gap-3">
          {robotOnline ? <Wifi size={16} className="text-emerald-300" /> : <WifiOff size={16} className="text-slate-500" />}
          <div>
            <div className="text-[13px] font-black text-white">机器人相机</div>
            <div className="text-[11px] font-semibold text-slate-500">来自本地代理预览流</div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setExpandedCamera((current) => (current === "robot" ? null : "robot"))}
            className="inline-flex items-center gap-2 rounded-2xl border border-white/10 bg-white/5 px-3 py-2 text-[11px] font-bold text-slate-200 transition hover:bg-white/10"
          >
            {expanded ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
            {expanded ? "收起" : "放大"}
          </button>
          <span
            className={`rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest ${
              robotOnline && robotCameraReady ? "bg-emerald-500/15 text-emerald-200" : "bg-white/10 text-slate-400"
            }`}
          >
            {robotOnline && robotCameraReady ? "ONLINE" : "OFFLINE"}
          </span>
        </div>
      </div>
      <div className="relative flex flex-1 items-center justify-center bg-[#070b16] p-4">
        {robotOnline && robotCameraReady ? (
          <img src={robotPreviewUrl} alt="robot-preview" className="max-h-full max-w-full rounded-[1.5rem] object-contain" />
        ) : (
          <div className="flex flex-col items-center gap-4 px-8 text-center text-slate-500">
            <ShieldCheck size={56} />
            <div className="text-[13px] font-bold">机器人相机当前不可用</div>
            <div className="max-w-sm text-[12px] leading-6 text-slate-600">
              需要设备在线，并且相机模块处于可用状态后，这里才会显示机器人侧的预览流。
            </div>
          </div>
        )}
      </div>
      <div className="border-t border-white/[0.05] px-5 py-4 text-[12px] leading-7 text-slate-400">
        {robotOnline && robotCameraReady
          ? `设备在线，当前通过 ${ROBOT_PROXY_BASE}/snapshot 获取预览。`
          : `设备状态：${status?.error || "离线或 camera_ready=false"}`}
      </div>
    </div>
  );

  return (
    <div className="h-full w-full overflow-y-auto pr-1 no-scrollbar">
      <div className="mx-auto grid h-full w-full max-w-[1560px] grid-cols-12 gap-6 animate-pop-in">
        <section className="col-span-9 flex min-h-[780px] flex-col rounded-[2.5rem] border border-white/[0.05] bg-[#0c1222]/50 p-7 shadow-2xl backdrop-blur-3xl">
          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-3">
                <Camera className="text-cyan-300" size={20} />
                <h2 className="text-xl font-black text-white">相机情绪识别</h2>
              </div>
              <p className="mt-2 text-[12px] font-semibold text-slate-400">
                使用仓库里现成的 FER+ ONNX 与 MediaPipe 模型做实时识别，不走规则算法打分。
              </p>
            </div>
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => setSnapshotNonce(Date.now())}
                className="inline-flex items-center gap-2 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-[12px] font-bold text-slate-200 transition hover:bg-white/10"
              >
                <RefreshCw size={14} />
                刷新机器人画面
              </button>
              {localEnabled ? (
                <button
                  type="button"
                  onClick={stopLocalCamera}
                  className="inline-flex items-center gap-2 rounded-2xl border border-rose-400/20 bg-rose-500/10 px-4 py-3 text-[12px] font-bold text-rose-100 transition hover:bg-rose-500/15"
                >
                  <CameraOff size={14} />
                  关闭本机相机
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => setLocalEnabled(true)}
                  className="inline-flex items-center gap-2 rounded-2xl border border-cyan-400/20 bg-cyan-500/10 px-4 py-3 text-[12px] font-bold text-cyan-100 transition hover:bg-cyan-500/15"
                >
                  <Camera size={14} />
                  打开本机相机
                </button>
              )}
            </div>
          </div>

          <div className="mt-6 flex flex-1">
            {expandedCamera === "local" ? (
              <div className="w-full">{renderLocalCameraCard(true)}</div>
            ) : expandedCamera === "robot" ? (
              <div className="w-full">{renderRobotCameraCard(true)}</div>
            ) : (
              <div className="grid w-full flex-1 grid-cols-[minmax(0,1.55fr)_minmax(360px,0.95fr)] gap-6">
                {renderLocalCameraCard(false)}
                {renderRobotCameraCard(false)}
              </div>
            )}
          </div>
        </section>

        <aside className="col-span-3 flex min-h-[780px] flex-col gap-6">
          <section className="rounded-[2.5rem] border border-white/[0.05] bg-[#0c1222]/50 p-7 shadow-2xl backdrop-blur-3xl">
            <div className="flex items-center justify-between">
              <div className="text-[11px] font-black uppercase tracking-[0.28em] text-cyan-300">实时情绪曲线</div>
              <div className="text-[10px] font-bold text-slate-500">{curvePoints.length} 点</div>
            </div>
            <div className="mt-4 h-[220px]">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={curvePoints}>
                  <defs>
                    <linearGradient id="cameraEmotionCurve" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#22d3ee" stopOpacity={0.35} />
                      <stop offset="95%" stopColor="#22d3ee" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(148,163,184,0.12)" />
                  <XAxis dataKey="time" tick={{ fill: "#64748b", fontSize: 10, fontWeight: 800 }} axisLine={false} tickLine={false} />
                  <YAxis hide domain={[0, 100]} />
                  <Tooltip
                    contentStyle={{
                      borderRadius: "16px",
                      border: "1px solid rgba(255,255,255,0.08)",
                      backgroundColor: "rgba(15,23,42,0.92)",
                      color: "#e2e8f0",
                    }}
                    formatter={(value: number, name: string, entry: any) => {
                      if (name === "value") return [`${value}`, `强度 · ${entry?.payload?.label || "未识别"}`];
                      return [`${value}`, name];
                    }}
                  />
                  <Area
                    type="monotone"
                    dataKey="value"
                    stroke="#22d3ee"
                    strokeWidth={3}
                    fill="url(#cameraEmotionCurve)"
                    fillOpacity={1}
                    animationDuration={300}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3 text-[12px]">
              <div className="rounded-2xl border border-white/6 bg-white/[0.03] px-4 py-3">
                <div className="text-slate-500">当前情绪</div>
                <div className="mt-1 font-black text-white">{analysis?.emotion_label_zh || "未识别"}</div>
              </div>
              <div className="rounded-2xl border border-white/6 bg-white/[0.03] px-4 py-3">
                <div className="text-slate-500">置信度</div>
                <div className="mt-1 font-black text-white">
                  {analysis ? `${((analysis.confidence || 0) * 100).toFixed(1)}%` : "--"}
                </div>
              </div>
            </div>
          </section>

          <section className="rounded-[2.5rem] border border-white/[0.05] bg-[#0c1222]/50 p-7 shadow-2xl backdrop-blur-3xl">
            <div className="text-[11px] font-black uppercase tracking-[0.28em] text-slate-400">识别状态</div>
            <div className="mt-5 space-y-3 text-[13px] text-slate-300">
              <div className="flex items-center justify-between rounded-2xl border border-white/6 bg-white/[0.03] px-4 py-3">
                <span>本机相机预览</span>
                <span className={localReady ? "text-emerald-300" : "text-slate-400"}>{localReady ? "已开启" : "未开启"}</span>
              </div>
              <div className="flex items-center justify-between rounded-2xl border border-white/6 bg-white/[0.03] px-4 py-3">
                <span>模型状态</span>
                <span className={analysis?.model_ready ? "text-emerald-300" : "text-slate-400"}>
                  {analysis?.model_ready ? "FER+/MP ready" : "未就绪"}
                </span>
              </div>
              <div className="flex items-center justify-between rounded-2xl border border-white/6 bg-white/[0.03] px-4 py-3">
                <span>锁定主体</span>
                <span className={analysis?.focus_locked ? "text-emerald-300" : "text-slate-400"}>
                  {analysis?.focus_locked ? "已锁定" : "未锁定"}
                </span>
              </div>
              <div className="flex items-center justify-between rounded-2xl border border-white/6 bg-white/[0.03] px-4 py-3">
                <span>人脸数量</span>
                <span className={analysis && analysis.face_count === 1 ? "text-emerald-300" : "text-amber-300"}>
                  {analysis?.face_count ?? 0}
                </span>
              </div>
              <div className="flex items-center justify-between rounded-2xl border border-white/6 bg-white/[0.03] px-4 py-3">
                <span>识别暂停</span>
                <span className={analysis?.recognition_paused ? "text-amber-300" : "text-emerald-300"}>
                  {analysis?.recognition_paused ? "是" : "否"}
                </span>
              </div>
            </div>
            {analysis?.recognition_paused ? (
              <div className="mt-4 rounded-2xl border border-amber-300/20 bg-amber-500/10 px-4 py-3 text-[12px] leading-6 text-amber-100">
                {formatPauseReason(analysis.pause_reason)}
              </div>
            ) : null}
          </section>

          <section className="rounded-[2.5rem] border border-white/[0.05] bg-[#0c1222]/50 p-7 shadow-2xl backdrop-blur-3xl">
            <div className="text-[11px] font-black uppercase tracking-[0.28em] text-cyan-300">采集说明</div>
            <div className="mt-4 space-y-4 text-[13px] leading-7 text-slate-300">
              <p>当前会持续抓取本机摄像头画面做实时识别，并把识别到的人脸直接框出来，让你知道系统正在看谁。</p>
              <p>如果同一帧里出现多个人，系统会自动暂停这轮识别，避免把旁人的状态混进你的情绪曲线。</p>
              <p>后续主动情绪关怀可以直接复用这条模型链路，不需要再另外接一套视觉输入。</p>
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
};
