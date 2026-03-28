import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  DeviceStatus,
  FaceTrackEngineState,
  FaceTrackState,
  RiskDetail,
  RiskScores,
  SystemEvent,
  WakeEngineState,
} from "../types";
import { sendDevicePanTiltLocal } from "../services/deviceService";
import {
  Camera,
  Wifi,
  Globe,
  Mic2,
  Activity,
  Play,
  Pause,
  RotateCw,
  Database,
  Circle,
  Laptop,
  Crosshair,
} from "lucide-react";

interface DeviceMonitorProps {
  status: DeviceStatus | null;
  scores: RiskScores;
  riskDetail?: RiskDetail | null;
  logs: SystemEvent[];
  onRefreshStatus: () => void;
  refreshing?: boolean;
  statusError?: string;
  videoEnabled?: boolean;
  audioEnabled?: boolean;
  faceTrack?: FaceTrackState | null;
  faceTrackEngine?: FaceTrackEngineState | null;
  wakeEngine?: WakeEngineState | null;
  faceTrackOverlayEnabled?: boolean;
  onToggleFaceTrackOverlay?: (enabled: boolean) => void;
  wsConnected?: boolean;
  riskUpdatedAt?: number | null;
  riskSource?: "ws" | "poll" | null;
  active?: boolean;
}

type OverlayBBox = { left: number; top: number; width: number; height: number } | null;
type DesktopTrackingBBox = { x: number; y: number; width: number; height: number } | null;

export const computeOverlayBBoxPercent = (
  faceTrack: FaceTrackState | null,
  faceTrackOverlayEnabled: boolean,
  overlayStale: boolean
): OverlayBBox => {
  if (!faceTrack || !faceTrack.bbox || !faceTrackOverlayEnabled || overlayStale) return null;
  const [x, y, w, h] = faceTrack.bbox;
  const frameW = Number(faceTrack.frame_w || 0);
  const frameH = Number(faceTrack.frame_h || 0);
  if (frameW <= 0 || frameH <= 0 || w <= 0 || h <= 0) return null;

  const left = (x / frameW) * 100;
  const top = (y / frameH) * 100;
  const width = (w / frameW) * 100;
  const height = (h / frameH) * 100;
  if (![left, top, width, height].every((v) => Number.isFinite(v))) return null;

  return {
    left: Math.max(0, Math.min(100, left)),
    top: Math.max(0, Math.min(100, top)),
    width: Math.max(0, Math.min(100, width)),
    height: Math.max(0, Math.min(100, height)),
  };
};

export const DeviceMonitor: React.FC<DeviceMonitorProps> = ({
  status,
  scores,
  riskDetail = null,
  onRefreshStatus,
  refreshing,
  statusError,
  videoEnabled = true,
  audioEnabled = true,
  faceTrack = null,
  faceTrackEngine = null,
  wakeEngine = null,
  faceTrackOverlayEnabled = true,
  onToggleFaceTrackOverlay,
  wsConnected = false,
  riskUpdatedAt = null,
  riskSource = null,
  active = true,
}) => {
  const deviceId = status?.device_id || "unknown";
  const deviceIp = status?.device_ip || status?.status?.ip || "";
  const deviceMac = status?.device_mac || status?.status?.device_mac || "";
  const ssid = status?.status?.ssid || "未知";
  const rssi = status?.status?.rssi;
  const cameraReady = status?.status?.camera_ready;
  const online = status?.online ?? false;
  const [streamEnabled, setStreamEnabled] = useState(true);
  const [streamError, setStreamError] = useState("");
  const [streamNonce, setStreamNonce] = useState(0);
  const [streamRenderToken, setStreamRenderToken] = useState(0);
  const [snapshotMode] = useState(true);
  const [overlayNowMs, setOverlayNowMs] = useState(() => Date.now());
  const [desktopCamEnabled, setDesktopCamEnabled] = useState(false);
  const [desktopCamError, setDesktopCamError] = useState("");
  const [desktopTrackStatus, setDesktopTrackStatus] = useState("idle");
  const [desktopTrackBox, setDesktopTrackBox] = useState<DesktopTrackingBBox>(null);
  const [desktopTrackTurns, setDesktopTrackTurns] = useState({ pan: 0, tilt: 0 });
  const streamSource: "proxy" = "proxy";
  const reconnectTimer = useRef<number | null>(null);
  const metaStaleCountRef = useRef(0);
  const lastMetaUpdatedRef = useRef(0);
  const desktopVideoRef = useRef<HTMLVideoElement | null>(null);
  const desktopTrackTimerRef = useRef<number | null>(null);
  const desktopStreamRef = useRef<MediaStream | null>(null);
  const desktopLastSendRef = useRef(0);
  const desktopLastPanTiltRef = useRef({ pan: 0, tilt: 0 });
  const desktopLostCountRef = useRef(0);
  const proxyBase = "http://127.0.0.1:18080";
  const baseStreamUrl = snapshotMode ? `${proxyBase}/snapshot` : `${proxyBase}/stream`;
  const streamUrl =
    streamEnabled && videoEnabled && baseStreamUrl
      ? `${baseStreamUrl}${streamNonce ? `?t=${streamNonce}` : ""}`
      : "";
  const lastSeen = status?.last_seen_ms ? new Date(status.last_seen_ms) : null;

  useEffect(() => {
    setStreamError("");
    setStreamEnabled(true);
    setStreamNonce(Date.now());
    setStreamRenderToken((v) => v + 1);
  }, [deviceIp]);

  useEffect(() => {
    const hardReconnect = () => {
      setStreamEnabled(false);
      window.setTimeout(() => {
        setStreamEnabled(true);
        setStreamNonce(Date.now());
        setStreamRenderToken((v) => v + 1);
      }, 80);
    };

    if (active) {
      hardReconnect();
    }

    const onVisibility = () => {
      if (active && document.visibilityState === "visible") {
        hardReconnect();
      }
    };
    const onFocus = () => {
      if (active) hardReconnect();
    };
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("focus", onFocus);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("focus", onFocus);
    };
  }, [active]);

  useEffect(() => {
    const timer = window.setInterval(() => setOverlayNowMs(Date.now()), 500);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!snapshotMode || !active || !streamEnabled || !videoEnabled) return;
    const timer = window.setInterval(() => {
      setStreamNonce(Date.now());
    }, 180);
    return () => window.clearInterval(timer);
  }, [snapshotMode, active, streamEnabled, videoEnabled]);

  useEffect(() => {
    return () => {
      if (reconnectTimer.current !== null) {
        window.clearTimeout(reconnectTimer.current);
      }
      if (desktopTrackTimerRef.current !== null) {
        window.clearInterval(desktopTrackTimerRef.current);
      }
      if (desktopStreamRef.current) {
        desktopStreamRef.current.getTracks().forEach((track) => track.stop());
      }
    };
  }, []);

  const overlayAgeMs =
    faceTrack && Number.isFinite(faceTrack.ts_ms) ? Math.max(0, overlayNowMs - faceTrack.ts_ms) : Infinity;
  const overlayStale = overlayAgeMs > 2000;

  const overlayBbox = useMemo(() => {
    return computeOverlayBBoxPercent(faceTrack, faceTrackOverlayEnabled, overlayStale);
  }, [faceTrack, faceTrackOverlayEnabled, overlayStale]);

  const overlayFaceVisible = Boolean(
    faceTrackOverlayEnabled && faceTrack?.found && !overlayStale && overlayBbox
  );
  const overlayStateText = !faceTrack ? "未检测到人脸" : overlayStale ? "追踪数据超时" : "未检测到人脸";

  const scheduleReconnect = () => {
    if (!streamEnabled || reconnectTimer.current !== null) return;
    reconnectTimer.current = window.setTimeout(() => {
      reconnectTimer.current = null;
      setStreamNonce(Date.now());
      setStreamRenderToken((v) => v + 1);
    }, 1500);
  };

  const handleStreamError = () => {
    setStreamError("stream unavailable");
    scheduleReconnect();
  };

  const handleStreamLoad = () => {
    if (streamError) setStreamError("");
  };

  const toggleStream = () => {
    if (streamEnabled) {
      setStreamEnabled(false);
      return;
    }
    setStreamEnabled(true);
    setStreamError("");
    setStreamNonce(Date.now());
    setStreamRenderToken((v) => v + 1);
  };

  const forceReconnect = useCallback(() => {
    setStreamEnabled(false);
    setStreamError("");
    metaStaleCountRef.current = 0;
    lastMetaUpdatedRef.current = 0;
    window.setTimeout(() => {
      setStreamEnabled(true);
      setStreamNonce(Date.now());
      setStreamRenderToken((v) => v + 1);
    }, 80);
  }, []);

  const stopDesktopTracking = useCallback(() => {
    if (desktopTrackTimerRef.current !== null) {
      window.clearInterval(desktopTrackTimerRef.current);
      desktopTrackTimerRef.current = null;
    }
    if (desktopStreamRef.current) {
      desktopStreamRef.current.getTracks().forEach((track) => track.stop());
      desktopStreamRef.current = null;
    }
    if (desktopVideoRef.current) {
      desktopVideoRef.current.srcObject = null;
    }
    setDesktopCamEnabled(false);
    setDesktopTrackStatus("idle");
    setDesktopTrackBox(null);
    setDesktopCamError("");
    desktopLostCountRef.current = 0;
  }, []);

  const startDesktopTracking = useCallback(async () => {
    if (!deviceIp) {
      setDesktopCamError("设备 IP 不可用，无法把笔记本摄像头测试结果发送到机器人。");
      return;
    }
    const DetectorCtor = (window as any).FaceDetector;
    if (typeof DetectorCtor !== "function") {
      setDesktopCamError("当前 Electron 运行时不支持 FaceDetector。");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" },
        audio: false,
      });
      desktopStreamRef.current = stream;
      setDesktopCamEnabled(true);
      setDesktopCamError("");
      setDesktopTrackStatus("camera_ready");
      const video = desktopVideoRef.current;
      if (video) {
        video.srcObject = stream;
        await video.play();
      }
      const detector = new DetectorCtor({
        fastMode: true,
        maxDetectedFaces: 1,
      });
      if (desktopTrackTimerRef.current !== null) {
        window.clearInterval(desktopTrackTimerRef.current);
      }
      desktopTrackTimerRef.current = window.setInterval(async () => {
        const currentVideo = desktopVideoRef.current;
        if (!currentVideo || currentVideo.readyState < 2) return;
        try {
          const faces = await detector.detect(currentVideo);
          const face = faces?.[0];
          if (!face?.boundingBox) {
            desktopLostCountRef.current += 1;
            setDesktopTrackStatus("no_face");
            setDesktopTrackBox(null);
            if (desktopLostCountRef.current >= 6 && Date.now() - desktopLastSendRef.current > 400) {
              desktopLastSendRef.current = Date.now();
              desktopLastPanTiltRef.current = { pan: 0, tilt: 0 };
              setDesktopTrackTurns({ pan: 0, tilt: 0 });
              await sendDevicePanTiltLocal(`${deviceIp}:8090`, { pan: 0, tilt: 0 });
            }
            return;
          }

          desktopLostCountRef.current = 0;
          const box = face.boundingBox;
          const frameW = currentVideo.videoWidth || 1;
          const frameH = currentVideo.videoHeight || 1;
          const centerX = box.x + box.width / 2;
          const centerY = box.y + box.height / 2;
          const ex = (centerX - frameW / 2) / (frameW / 2);
          const ey = (frameH / 2 - centerY) / (frameH / 2);
          const deadZone = 0.11;
          const pan = Math.abs(ex) < deadZone ? 0 : Math.max(-1, Math.min(1, ex * 0.55));
          const tilt = Math.abs(ey) < deadZone ? 0 : Math.max(-1, Math.min(1, ey * 0.48));

          setDesktopTrackStatus("tracking");
          setDesktopTrackBox({ x: box.x, y: box.y, width: box.width, height: box.height });

          if (
            Date.now() - desktopLastSendRef.current > 280 &&
            (Math.abs(pan - desktopLastPanTiltRef.current.pan) > 0.035 ||
              Math.abs(tilt - desktopLastPanTiltRef.current.tilt) > 0.035)
          ) {
            desktopLastSendRef.current = Date.now();
            desktopLastPanTiltRef.current = { pan, tilt };
            setDesktopTrackTurns({ pan, tilt });
            await sendDevicePanTiltLocal(`${deviceIp}:8090`, { pan, tilt });
          }
        } catch (error) {
          setDesktopTrackStatus("error");
          setDesktopCamError(error instanceof Error ? error.message : "desktop_face_track_failed");
        }
      }, 260);
    } catch (error) {
      setDesktopCamError(error instanceof Error ? error.message : "desktop_camera_start_failed");
      stopDesktopTracking();
    }
  }, [deviceIp, stopDesktopTracking]);

  useEffect(() => {
    if (!active || !streamEnabled || !videoEnabled) return;
    let disposed = false;
    const STALE_MS = 3500;
    const MAX_STALE_COUNT = 3;
    const checkMeta = async () => {
      try {
        const response = await fetch(`${proxyBase}/meta?t=${Date.now()}`, { cache: "no-store" });
        if (!response.ok) {
          metaStaleCountRef.current += 1;
          if (metaStaleCountRef.current >= MAX_STALE_COUNT) {
            if (!disposed) forceReconnect();
          }
          return;
        }
        const data = (await response.json()) as { updated_ms?: number; has_frame?: boolean };
        const updatedMs = Number(data?.updated_ms ?? 0);
        const hasFrame = Boolean(data?.has_frame);
        if (!hasFrame || !Number.isFinite(updatedMs) || updatedMs <= 0) {
          metaStaleCountRef.current += 1;
        } else if (updatedMs > lastMetaUpdatedRef.current) {
          lastMetaUpdatedRef.current = updatedMs;
          metaStaleCountRef.current = 0;
        } else {
          const silentMs = Date.now() - updatedMs;
          if (silentMs >= STALE_MS) {
            metaStaleCountRef.current += 1;
          } else {
            metaStaleCountRef.current = 0;
          }
        }
        if (metaStaleCountRef.current >= MAX_STALE_COUNT) {
          if (!disposed) forceReconnect();
        }
      } catch {
        metaStaleCountRef.current += 1;
        if (metaStaleCountRef.current >= MAX_STALE_COUNT) {
          if (!disposed) forceReconnect();
        }
      }
    };
    const timer = window.setInterval(checkMeta, 1200);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [active, streamEnabled, videoEnabled, forceReconnect, proxyBase]);

  const formatNum = (value: number | null | undefined, digits = 3) => {
    if (value == null || !Number.isFinite(value)) return "-";
    return Number(value).toFixed(digits);
  };
  const fatigue = Number(riskDetail?.V_sub?.fatigue ?? 0);
  const attentionDrop = Number(riskDetail?.V_sub?.attention_drop ?? 0);
  const silenceSec = Number(riskDetail?.A_sub?.silence_sec ?? 0);
  const rms = Number(riskDetail?.A_sub?.rms ?? 0);
  const expressionId = Number(riskDetail?.V_sub?.expression_class_id);
  const expressionConfidence = Number(riskDetail?.V_sub?.expression_confidence);
  const expressionValidSignal = Number(riskDetail?.V_sub?.expression_valid);
  const expressionReason = String(riskDetail?.V_sub?.expr_reason ?? "");
  const expressionSource = String(riskDetail?.V_sub?.expr_source ?? "");
  const frameDecodeOk = Number(riskDetail?.V_sub?.frame_decode_ok);
  const ferInvoked = Number(riskDetail?.V_sub?.fer_invoked);
  const exprModelReady = Number(riskDetail?.V_sub?.expr_model_ready);
  const expressionLabels = [
    "neutral",
    "happiness",
    "surprise",
    "sadness",
    "anger",
    "disgust",
    "fear",
    "contempt",
  ];
  const expressionLabel =
    Number.isFinite(expressionId) && expressionId >= 0 && expressionId < expressionLabels.length
      ? expressionLabels[Math.floor(expressionId)]
      : "unknown";
  const expressionLabelsZh = [
    "中性",
    "高兴",
    "惊讶",
    "悲伤",
    "愤怒",
    "厌恶",
    "恐惧",
    "轻蔑",
  ];
  const expressionLabelZh =
    Number.isFinite(expressionId) && expressionId >= 0 && expressionId < expressionLabelsZh.length
      ? expressionLabelsZh[Math.floor(expressionId)]
      : "未识别";
  const expressionUiRecognized =
    Number.isFinite(expressionId) &&
    expressionId >= 0 &&
    Number.isFinite(expressionConfidence) &&
    (expressionConfidence >= 0.08 ||
      (expressionLabel === "neutral" && expressionConfidence >= 0.07));
  const expressionValid =
    Number.isFinite(expressionValidSignal) && expressionValidSignal >= 0
      ? expressionValidSignal > 0.5
      : Number.isFinite(expressionId) && expressionId >= 0 && Number.isFinite(expressionConfidence) && expressionConfidence > 0;
  const hasRiskDetail = Boolean(
    riskDetail &&
      ((riskDetail.V_sub && Object.keys(riskDetail.V_sub).length > 0) ||
        (riskDetail.A_sub && Object.keys(riskDetail.A_sub).length > 0) ||
        (riskDetail.T_sub && Object.keys(riskDetail.T_sub).length > 0))
  );
  const riskAgeMs = riskUpdatedAt ? Math.max(0, Date.now() - riskUpdatedAt) : Infinity;
  const riskStale = !Number.isFinite(riskAgeMs) || riskAgeMs > 5000;
  const expressionConfText = expressionUiRecognized && Number.isFinite(expressionConfidence)
    ? `${(expressionConfidence * 100).toFixed(1)}%`
    : "--";
  const expressionOverlayLabel =
    hasRiskDetail && !riskStale && expressionUiRecognized ? expressionLabelZh : "未识别";
  const expressionOverlayConf =
    hasRiskDetail && !riskStale && expressionUiRecognized ? expressionConfText : "--";
  const formatMetric = (value: number | null | undefined, digits = 2) => {
    if (value == null || !Number.isFinite(value)) return "--";
    return Number(value).toFixed(digits);
  };

  return (
    <div className="grid grid-cols-12 gap-6 min-h-full animate-pop-in">
      <div className="col-span-8 bg-[#0c1222]/50 backdrop-blur-3xl rounded-[2.5rem] border border-white/[0.05] overflow-hidden flex flex-col shadow-2xl">
        <div className="px-6 py-4 border-b border-white/[0.03] flex justify-between items-center bg-white/[0.01]">
          <div className="flex items-center gap-3">
            <Camera size={14} className="text-indigo-400" />
            <span className="text-[10px] font-black uppercase tracking-widest text-slate-400">
              工位端视频实时流 (MJPEG)
            </span>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5 px-2 py-0.5 bg-red-500/10 rounded text-[8px] font-black text-red-400">
              <Circle size={6} fill="currentColor" className="animate-pulse" /> REC
            </div>
            <span className="text-[9px] font-bold text-slate-600 uppercase">
              {online ? "ONLINE" : "OFFLINE"}
            </span>
          </div>
        </div>
        <div className="flex-1 bg-black relative group overflow-hidden">
          {streamUrl ? (
            <img
              key={`${streamSource}-${streamRenderToken}-${streamNonce}`}
              src={streamUrl}
              className="w-full h-full object-contain"
              alt="camera stream"
              onError={handleStreamError}
              onLoad={handleStreamLoad}
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center text-slate-600 text-xs">
              暂无视频流
            </div>
          )}
          {!videoEnabled && (
            <div className="absolute inset-0 bg-black/80 flex items-center justify-center text-slate-300 text-xs">
              摄像头已关闭
            </div>
          )}
          <div className="absolute top-4 left-4 z-20 pointer-events-none">
            <div className="bg-black/45 border border-white/20 rounded-lg px-3 py-2 text-[10px] font-mono text-emerald-100 space-y-0.5">
              <p className="text-[9px] text-emerald-300/90 uppercase tracking-widest font-black">
                表情识别
              </p>
              <p>emotion: {expressionOverlayLabel}</p>
              <p>conf: {expressionOverlayConf}</p>
              <p>model: {Number.isFinite(exprModelReady) ? (exprModelReady > 0.5 ? "ready" : "off") : "--"}</p>
              <p className="text-[10px] text-slate-400">reason: {expressionReason || "--"}</p>
              <p className="text-[10px] text-slate-500">source: {expressionSource || "--"}</p>
              <p className="text-[10px] text-slate-500">
                decode: {Number.isFinite(frameDecodeOk) ? (frameDecodeOk > 0.5 ? "ok" : "fail") : "--"} / fer:{" "}
                {Number.isFinite(ferInvoked) ? (ferInvoked > 0.5 ? "run" : "skip") : "--"}
              </p>
            </div>
          </div>
          {streamError && (
            <div className="absolute top-20 left-4 text-[10px] font-mono text-rose-300 bg-black/40 px-2 py-1 rounded z-20">
              {streamError}
            </div>
          )}

          {faceTrackOverlayEnabled && (
            <div className="absolute inset-0 pointer-events-none z-20">
              <div className="absolute left-1/2 top-0 bottom-0 w-px bg-emerald-300/40 -translate-x-1/2" />
              <div className="absolute top-1/2 left-0 right-0 h-px bg-emerald-300/40 -translate-y-1/2" />

              {overlayFaceVisible && overlayBbox && (
                <div
                  className="absolute border-2 border-cyan-300 shadow-[0_0_0_1px_rgba(0,0,0,0.25)]"
                  style={{
                    left: `${overlayBbox.left}%`,
                    top: `${overlayBbox.top}%`,
                    width: `${overlayBbox.width}%`,
                    height: `${overlayBbox.height}%`,
                  }}
                />
              )}

              <div className="absolute top-4 right-4 bg-black/45 border border-white/20 rounded-lg px-2 py-1 text-[10px] font-mono text-cyan-100 space-y-0.5">
                <p>turn: {formatNum(faceTrack?.turn, 3)}</p>
                <p>ex_smooth: {formatNum(faceTrack?.ex_smooth, 3)}</p>
                <p>lost: {faceTrack ? faceTrack.lost : "-"}</p>
                <p>mode: {faceTrack?.mode || "-"}</p>
                <p>sent: {faceTrack ? String(Boolean(faceTrack.sent)) : "-"}</p>
                <p>age_ms: {Number.isFinite(overlayAgeMs) ? Math.round(overlayAgeMs) : "-"}</p>
                {!overlayFaceVisible && (
                  <p className="text-amber-200">{overlayStateText}</p>
                )}
              </div>
            </div>
          )}

          <div className="absolute bottom-6 left-6 right-6 flex justify-between items-end">
            <div className="space-y-1">
              <p className="text-[8px] font-mono text-white/30">STREAM_URI: {streamUrl || "-"}</p>
              <p className="text-[8px] font-mono text-white/30">STREAM_SRC: {streamSource}</p>
              <p className="text-[8px] font-mono text-white/30">CODEC: MJPEG STREAM</p>
              {faceTrack && (
                <p className="text-[8px] font-mono text-white/30">
                  TRACK: {faceTrack.found ? "FACE" : "NONE"} / turn {formatNum(faceTrack.turn, 2)}
                </p>
              )}
            </div>
            <div className="flex gap-2">
              {onToggleFaceTrackOverlay && (
                <button
                  onClick={() => onToggleFaceTrackOverlay(!faceTrackOverlayEnabled)}
                  className={`p-2 rounded-full border ${
                    faceTrackOverlayEnabled
                      ? "bg-cyan-500/20 border-cyan-300/50 text-cyan-100"
                      : "bg-white/5 border-white/10 text-white/50 hover:bg-white/10"
                  }`}
                  title="FaceTrack Overlay"
                >
                  <Activity size={12} />
                </button>
              )}
              <button
                onClick={toggleStream}
                className="p-2 bg-white/5 rounded-full text-white/50 hover:bg-white/10"
              >
                {streamEnabled ? <Pause size={12} /> : <Play size={12} />}
              </button>
              <button
                onClick={forceReconnect}
                className="p-2 bg-white/5 rounded-full text-white/50 hover:bg-white/10"
              >
                <RotateCw size={12} />
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="col-span-4 flex flex-col gap-6">
        <div className="bg-[#0c1222]/50 backdrop-blur-3xl rounded-[2rem] border border-white/[0.05] p-6 shadow-xl">
          <h3 className="text-[9px] font-black text-slate-500 uppercase tracking-widest mb-3">设备连接</h3>
          <div className="space-y-2">
            <StatusItem icon={Globe} label="设备 ID" value={deviceId} />
            <StatusItem icon={Globe} label="设备 IP" value={deviceIp || "未知"} active={online} />
            <StatusItem icon={Globe} label="设备 MAC" value={deviceMac || "未知"} />
            <p className="text-[9px] text-slate-500">IP 来自后端心跳接口</p>
            <button
              onClick={onRefreshStatus}
              className="mt-2 w-full px-3 py-2 bg-indigo-500/10 border border-indigo-500/30 rounded-xl text-[10px] font-black text-indigo-300 hover:bg-indigo-500/20 transition-all flex items-center justify-center gap-2"
            >
              <RotateCw size={12} className={refreshing ? "animate-spin" : ""} />
              刷新
            </button>
            {statusError && <p className="text-[9px] text-rose-400">{statusError}</p>}
          </div>
        </div>

        <div className="bg-[#0c1222]/50 backdrop-blur-3xl rounded-[2rem] border border-white/[0.05] p-6 shadow-xl">
          <h3 className="text-[9px] font-black text-slate-500 uppercase tracking-widest mb-4 flex items-center gap-2">
            <Camera size={12} className="text-cyan-400" /> 树莓派摄像头链路
          </h3>
          <div className="space-y-3">
            <div className="rounded-2xl border border-white/10 bg-black/30 p-4">
              <div className="grid grid-cols-2 gap-2 text-[10px]">
                <div className="rounded-xl bg-white/[0.03] border border-white/[0.05] px-3 py-2 text-slate-300">
                  视频链路:{" "}
                  <span className={`font-mono ${streamEnabled && videoEnabled ? "text-cyan-300" : "text-slate-500"}`}>
                    {streamEnabled && videoEnabled ? "树莓派代理流" : "关闭"}
                  </span>
                </div>
                <div className="rounded-xl bg-white/[0.03] border border-white/[0.05] px-3 py-2 text-slate-300">
                  摄像头状态:{" "}
                  <span className={`font-mono ${cameraReady === false ? "text-rose-300" : "text-cyan-300"}`}>
                    {cameraReady === false ? "未就绪" : "已就绪"}
                  </span>
                </div>
              </div>
              <p className="mt-3 text-[10px] text-slate-400 leading-5">
                这里现在只看树莓派摄像头和云台链路，不再提供笔记本摄像头代跑测试。视频窗口、追踪框和云台状态都以树莓派回传为准。
              </p>
              {streamError ? <p className="mt-2 text-[10px] text-rose-400">{streamError}</p> : null}
            </div>
          </div>
        </div>

        <div className="bg-[#0c1222]/50 backdrop-blur-3xl rounded-[2rem] border border-white/[0.05] p-6 shadow-xl">
          <h3 className="text-[9px] font-black text-slate-500 uppercase tracking-widest mb-4 flex items-center gap-2">
            <Activity size={12} className="text-indigo-400" /> 情感推理指标 (V/A/T/S)
          </h3>
          <div className="space-y-4">
            {[
              { label: "Visual (视觉)", val: scores.V, color: "bg-blue-400" },
              { label: "Acoustic (声学)", val: scores.A, color: "bg-purple-400" },
              { label: "Synthesis (综合)", val: scores.S, color: "bg-indigo-500" },
            ].map((item) => (
              <div key={item.label} className="space-y-1.5">
                <div className="flex justify-between text-[9px] font-black uppercase tracking-tighter">
                  <span className="text-slate-500">{item.label}</span>
                  <span className="text-slate-300">{Math.floor(item.val * 100)}%</span>
                </div>
                <div className="h-1 w-full bg-white/5 rounded-full overflow-hidden">
                  <div
                    className={`h-full ${item.color} transition-all duration-500`}
                    style={{ width: `${item.val * 100}%` }}
                  ></div>
                </div>
              </div>
            ))}
            <div className="grid grid-cols-2 gap-2 text-[9px] font-mono text-slate-400 pt-2 border-t border-white/5">
              <div>fatigue: {hasRiskDetail ? formatMetric(fatigue, 2) : "--"}</div>
              <div>attention: {hasRiskDetail ? formatMetric(attentionDrop, 2) : "--"}</div>
              <div>silence_s: {hasRiskDetail ? formatMetric(silenceSec, 1) : "--"}</div>
              <div>rms: {hasRiskDetail ? formatMetric(rms, 4) : "--"}</div>
              <div>
                expr: {expressionUiRecognized ? expressionLabel : "unknown"}
                {expressionUiRecognized && Number.isFinite(expressionConfidence) && expressionConfidence < 0.28 ? " (low)" : ""}
              </div>
              <div>
                conf: {Number.isFinite(expressionConfidence) ? `${(expressionConfidence * 100).toFixed(1)}%` : "--"}
              </div>
              <div>expr_model: {Number.isFinite(exprModelReady) ? (exprModelReady > 0.5 ? "ready" : "off") : "--"}</div>
            </div>
          </div>
        </div>

        <div className="bg-[#0c1222]/50 backdrop-blur-3xl rounded-[2rem] border border-white/[0.05] p-6 shadow-xl flex-1 flex flex-col">
          <h3 className="text-[9px] font-black text-slate-500 uppercase tracking-widest mb-4">Device Link</h3>
          <div className="space-y-3">
            <StatusItem icon={Globe} label="Device ID" value={deviceId} />
            <StatusItem icon={Globe} label="Device MAC" value={deviceMac || "UNKNOWN"} />
            <StatusItem icon={Globe} label="Device IP" value={deviceIp || "UNKNOWN"} />
            <StatusItem icon={Wifi} label="Wi-Fi" value={ssid || "UNKNOWN"} />
            <StatusItem icon={Wifi} label="RSSI" value={rssi != null ? `${rssi} dBm` : "UNKNOWN"} />
            <StatusItem
              icon={Mic2}
              label="Audio Stream"
              value={audioEnabled ? (online ? "ACTIVE" : "OFFLINE") : "OFF"}
              active={audioEnabled && online}
            />
            <StatusItem
              icon={Database}
              label="Heartbeat"
              value={
                lastSeen
                  ? lastSeen.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
                  : "UNKNOWN"
              }
            />
            <StatusItem
              icon={Camera}
              label="Camera"
              value={cameraReady === false ? "NOT_READY" : "READY"}
              active={cameraReady !== false}
            />
            <StatusItem
              icon={Activity}
              label="Face Engine"
              value={
                faceTrackEngine
                  ? faceTrackEngine.detector_ready
                    ? `READY (${faceTrackEngine.detector})`
                    : `NOT_READY (${faceTrackEngine.detector})`
                  : "UNKNOWN"
              }
              active={Boolean(faceTrackEngine?.detector_ready)}
            />
            <StatusItem
              icon={Mic2}
              label="Wake Engine"
              value={
                wakeEngine
                  ? wakeEngine.enabled
                    ? wakeEngine.last_wake_ms
                      ? `ON / ${new Date(wakeEngine.last_wake_ms).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                          second: "2-digit",
                        })}`
                      : "ON"
                    : `OFF${wakeEngine.error ? ` (${wakeEngine.error})` : ""}`
                  : "UNKNOWN"
              }
              active={Boolean(wakeEngine?.enabled)}
            />
            <StatusItem
              icon={Activity}
              label="Risk Channel"
              value={wsConnected ? "WS ONLINE" : "WS OFFLINE"}
              active={wsConnected}
            />
            <StatusItem
              icon={Activity}
              label="Risk Freshness"
              value={
                Number.isFinite(riskAgeMs)
                  ? `${Math.round(riskAgeMs)}ms${riskSource ? ` (${riskSource})` : ""}${riskStale ? " STALE" : ""}`
                  : "UNKNOWN"
              }
              active={!riskStale}
            />
          </div>
          <div className="mt-auto pt-4 border-t border-white/5">
            <button
              onClick={onRefreshStatus}
              className="w-full py-2.5 bg-indigo-500/10 border border-indigo-500/30 rounded-xl text-[9px] font-black uppercase text-indigo-400 hover:bg-indigo-500/20 transition-all tracking-widest flex items-center justify-center gap-2"
            >
              <RotateCw size={12} className={refreshing ? "animate-spin" : ""} />
              刷新链路
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

const StatusItem = ({ icon: Icon, label, value, active }: any) => (
  <div className="flex items-center justify-between p-2 rounded-lg hover:bg-white/[0.02]">
    <div className="flex items-center gap-3">
      <Icon size={14} className="text-slate-600" />
      <span className="text-[10px] font-bold text-slate-400">{label}</span>
    </div>
    <span className={`text-[10px] font-mono font-black ${active ? "text-green-400" : "text-slate-300"}`}>
      {value}
    </span>
  </div>
);


