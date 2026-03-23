import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  Brain,
  Camera,
  CheckCircle2,
  ChevronRight,
  LoaderCircle,
  Mic,
  PauseCircle,
  PlayCircle,
  ScanFace,
  ShieldCheck,
  Sparkles,
  UserRound,
} from "lucide-react";

import { getActivationState } from "../services/authService";
import {
  completeActivation,
  finishAssessment,
  getAssessmentState,
  getOwnerBindingStatus,
  inferActivationIdentity,
  pollAssessmentVoice,
  startAssessment,
  startAssessmentVoice,
  startOwnerEnrollment,
  stopAssessmentVoice,
  submitAssessmentTurn,
  type ActivationAssessmentState,
  type ActivationIdentityInference,
} from "../services/activationService";
import { createDesktopVoiceRecorder, transcribeDesktopAudio } from "../services/desktopVoiceService";

interface ActivationGateProps {
  onActivated: () => Promise<void> | void;
}

const emptyIdentity = (): ActivationIdentityInference => ({
  ok: true,
  preferred_name: "",
  role_label: "owner",
  relation_to_robot: "primary_user",
  pronouns: "",
  identity_summary: "",
  onboarding_notes: "",
  voice_intro_summary: "",
  confidence: 0,
  inference_source: "heuristic",
  inference_detail: "",
  raw_json: {},
});

const emptyAssessment = (): ActivationAssessmentState => ({
  ok: true,
  exists: false,
  status: "idle",
  turn_count: 0,
  effective_turn_count: 0,
  latest_question: "",
  latest_transcript: "",
  last_question_id: "",
  type_code: "",
  scores: { E: 0, I: 0, S: 0, N: 0, T: 0, F: 0, J: 0, P: 0 },
  dimension_confidence: { EI: 0, SN: 0, TF: 0, JP: 0 },
  evidence_summary: { highlights: [], notes: "" },
  conversation_count: 0,
  finish_reason: "",
  voice_mode: "idle",
  voice_session_active: false,
  device_online: false,
  summary: "",
  response_style: "",
  care_style: "",
  inference_version: "assessment-v1",
  required_min_turns: 12,
  max_turns: 28,
  question_source: "question_bank",
  scoring_source: "pending",
  question_pair: "",
  mode_hint: "text_mode_ready",
  can_submit_text: true,
});

const scoreItems = (scores: ActivationAssessmentState["scores"]) => [
  ["E", scores.E],
  ["I", scores.I],
  ["S", scores.S],
  ["N", scores.N],
  ["T", scores.T],
  ["F", scores.F],
  ["J", scores.J],
  ["P", scores.P],
];

const confidenceItems = (confidence: ActivationAssessmentState["dimension_confidence"]) => [
  ["EI", confidence.EI],
  ["SN", confidence.SN],
  ["TF", confidence.TF],
  ["JP", confidence.JP],
];

const ROLE_OPTIONS = [
  { value: "owner", label: "主人" },
  { value: "family", label: "家人" },
  { value: "caregiver", label: "照护者" },
  { value: "patient", label: "被照护者" },
  { value: "operator", label: "设备操作员" },
  { value: "admin", label: "管理员" },
  { value: "unknown", label: "待确认" },
];

const RELATION_OPTIONS = [
  { value: "primary_user", label: "主要使用者" },
  { value: "family_member", label: "家庭成员" },
  { value: "caregiver", label: "照护关系" },
  { value: "maintainer", label: "维护/调试关系" },
  { value: "unknown", label: "待确认" },
];

const HUMAN_ROLE_LABELS: Record<string, string> = Object.fromEntries(
  ROLE_OPTIONS.map((item) => [item.value, item.label])
);

const HUMAN_RELATION_LABELS: Record<string, string> = Object.fromEntries(
  RELATION_OPTIONS.map((item) => [item.value, item.label])
);

export const ActivationGate: React.FC<ActivationGateProps> = ({ onActivated }) => {
  const [booting, setBooting] = useState(true);
  const [busy, setBusy] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [voiceBusy, setVoiceBusy] = useState(false);
  const [desktopVoiceBusy, setDesktopVoiceBusy] = useState(false);
  const [desktopVoiceRecording, setDesktopVoiceRecording] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [identityReady, setIdentityReady] = useState(false);
  const [psychometricCompleted, setPsychometricCompleted] = useState(false);
  const [ownerBindingRequired, setOwnerBindingRequired] = useState(false);
  const [ownerBindingCompleted, setOwnerBindingCompleted] = useState(false);
  const [preferredDeviceId, setPreferredDeviceId] = useState("");
  const [identityState, setIdentityState] = useState(emptyIdentity);
  const [assessmentState, setAssessmentState] = useState<ActivationAssessmentState>(emptyAssessment);
  const [introTranscript, setIntroTranscript] = useState("");
  const [observedName, setObservedName] = useState("");
  const [answerDraft, setAnswerDraft] = useState("");
  const [scanState, setScanState] = useState("");
  const desktopVoiceRecorderRef = useRef<{ stop: () => Promise<Blob> } | null>(null);

  const loadState = async () => {
    const [activation, assessment] = await Promise.all([getActivationState(), getAssessmentState()]);
    const identityDone = !activation.activation_required;
    const assessmentDone =
      activation.psychometric_completed || assessment.status === "completed" || Boolean(assessment.completed_at_ms);
    const preferredDevice = String(activation.preferred_device_id || "").trim();

    setIdentityReady(identityDone);
    setPsychometricCompleted(Boolean(assessmentDone));
    setOwnerBindingRequired(Boolean(activation.owner_binding_required));
    setOwnerBindingCompleted(Boolean(activation.owner_binding_completed));
    setPreferredDeviceId(preferredDevice);
    setIdentityState({
      ok: true,
      preferred_name: activation.preferred_name || "",
      role_label: activation.role_label || "owner",
      relation_to_robot: activation.relation_to_robot || "primary_user",
      pronouns: activation.pronouns || "",
      identity_summary: activation.identity_summary || "",
      onboarding_notes: activation.onboarding_notes || "",
      voice_intro_summary: activation.voice_intro_summary || "",
      confidence: identityDone ? 1 : 0,
      inference_source: identityDone ? "confirmed" : "heuristic",
      inference_detail: identityDone ? "当前身份信息已经保存，可继续微调。" : "",
      raw_json: {},
    });
    setAssessmentState(assessment);
    if (preferredDevice && activation.owner_binding_completed) {
      setScanState(`主人面部档案已绑定到设备 ${preferredDevice}。`);
    } else if (preferredDevice && activation.owner_binding_required) {
      setScanState(`当前设备 ${preferredDevice} 还没有主人面部档案，首次激活需要完成扫脸绑定。`);
    }

    if (identityDone && !assessmentDone && !assessment.exists) {
      const started = await startAssessment({ surface: "desktop", voice_mode: "text", reset: false });
      setAssessmentState(started);
    }
  };

  useEffect(() => {
    let active = true;
    const bootstrap = async () => {
      setBooting(true);
      setError("");
      try {
        await loadState();
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (active) {
          setBooting(false);
        }
      }
    };
    bootstrap();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!assessmentState.voice_session_active || psychometricCompleted) {
      return;
    }
    let cancelled = false;

    const tick = async () => {
      try {
        const result = await pollAssessmentVoice({ speakQuestion: true, windowMs: 5200 });
        if (cancelled) return;
        setAssessmentState(result.state);
        if (result.state.status === "completed") {
          setPsychometricCompleted(true);
        }
        if (!result.device_online) {
          setSuccess("设备离线，语音测评已自动退回文本模式。");
          setAssessmentState((prev) => ({
            ...prev,
            voice_session_active: false,
            voice_mode: "text",
            device_online: false,
          }));
          return;
        }
        if (result.transcript && result.transcript_processed) {
          setSuccess(`已收到语音回答：${result.transcript}`);
        }
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
        setAssessmentState((prev) => ({
          ...prev,
          voice_session_active: false,
          voice_mode: "text",
        }));
      }
    };

    tick();
    const timer = window.setInterval(tick, 2200);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [assessmentState.voice_session_active, psychometricCompleted]);

  useEffect(() => {
    if (!preferredDeviceId || !ownerBindingRequired || ownerBindingCompleted) {
      return;
    }
    let cancelled = false;
    const tick = async () => {
      try {
        const status = await getOwnerBindingStatus(preferredDeviceId);
        if (cancelled) {
          return;
        }
        if (status.enrolled) {
          setOwnerBindingCompleted(true);
          setOwnerBindingRequired(false);
          setScanState(`主人面部档案已绑定完成，设备 ${status.device_id} 已可进行本地识别。`);
          setSuccess("主人面部档案同步完成，首次绑定已完成。");
        }
      } catch (_err) {
        return;
      }
    };
    tick();
    const timer = window.setInterval(tick, 3200);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [preferredDeviceId, ownerBindingRequired, ownerBindingCompleted]);

  useEffect(() => {
    if (psychometricCompleted && preferredDeviceId && !ownerBindingCompleted) {
      setOwnerBindingRequired(true);
      if (!scanState) {
        setScanState(`人格测评已完成，下一步请在设备 ${preferredDeviceId} 上完成主人扫脸绑定。`);
      }
    }
  }, [preferredDeviceId, psychometricCompleted, ownerBindingCompleted, scanState]);

  const canFinish = identityReady && psychometricCompleted && (!ownerBindingRequired || ownerBindingCompleted);
  const scorePreview = useMemo(() => scoreItems(assessmentState.scores), [assessmentState.scores]);
  const confidencePreview = useMemo(
    () => confidenceItems(assessmentState.dimension_confidence),
    [assessmentState.dimension_confidence]
  );
  const canUseRobotVoice = identityReady && assessmentState.device_online && !psychometricCompleted;
  const identitySourceLabel =
    identityState.inference_source === "ai"
      ? "AI 草稿"
      : identityState.inference_source === "confirmed"
        ? "已确认"
        : "保守草稿";
  const identitySourceTone =
    identityState.inference_source === "ai"
      ? "border-emerald-400/20 bg-emerald-500/10 text-emerald-200"
      : identityState.inference_source === "confirmed"
        ? "border-cyan-400/20 bg-cyan-500/10 text-cyan-200"
        : "border-amber-400/20 bg-amber-500/10 text-amber-200";
  const assessmentQuestionSourceLabel =
    assessmentState.question_source === "ai" ? "AI 编排问题" : "题库保底问题";
  const assessmentScoringSourceLabel =
    assessmentState.scoring_source === "ai"
      ? "AI 评分中"
      : assessmentState.scoring_source === "heuristic"
        ? "规则保底评分"
        : "等待作答";
  const assessmentModeMessage =
    assessmentState.mode_hint === "robot_voice_active"
      ? "设备在线，当前由机器人本地播报、录音与转写。"
      : assessmentState.mode_hint === "robot_voice_ready"
        ? "设备在线，但你现在仍可直接用文本或电脑麦克风完成测评。"
        : "设备离线只会影响机器人语音链路，不影响文本测评继续完成。";

  const handleInferIdentity = async () => {
    if (!introTranscript.trim()) {
      setError("先让这个人做一句自我介绍，再生成身份草稿。");
      return;
    }
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const inferred = await inferActivationIdentity({
        transcript: introTranscript,
        observed_name: observedName,
        surface: "desktop",
        context: { source: "native_activation_gate" },
      });
      setIdentityState(inferred);
      if (!observedName.trim() && inferred.preferred_name) {
        setObservedName(inferred.preferred_name);
      }
      setSuccess("身份草稿已经生成，确认后会进入详细人格测评。");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const handleCompleteIdentity = async () => {
    if (!identityState.preferred_name.trim()) {
      setError("请先确认这个人的称呼。");
      return;
    }
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      await completeActivation({
        preferred_name: identityState.preferred_name,
        role_label: identityState.role_label || "owner",
        relation_to_robot: identityState.relation_to_robot || "primary_user",
        pronouns: identityState.pronouns || "",
        identity_summary: identityState.identity_summary || "",
        onboarding_notes: identityState.onboarding_notes || "",
        voice_intro_summary: identityState.voice_intro_summary || introTranscript.trim(),
        profile: {
          source: "native_activation_gate",
          intro_transcript: introTranscript.trim(),
        },
        activation_version: "v3-native-assessment",
      });
      setIdentityReady(true);
      const started = await startAssessment({ surface: "desktop", voice_mode: "text", reset: true });
      setAssessmentState(started);
      setSuccess("身份确认完成。现在开始 8 维人格测评，会一直聊到四组指标足够稳定。");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const handleRestartAssessment = async () => {
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const started = await startAssessment({ surface: "desktop", voice_mode: "text", reset: true });
      setAssessmentState(started);
      setPsychometricCompleted(false);
      setAnswerDraft("");
      setSuccess("测评已重开，会重新收集八维信号。");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const submitAssessmentAnswer = async (rawAnswer: string, voiceMode: "text" | "robot" | "desktop" = "text") => {
    const normalizedAnswer = String(rawAnswer || "").trim();
    if (!normalizedAnswer) {
      setError("先输入这一轮回答。");
      return;
    }
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const nextState = await submitAssessmentTurn({
        answer: normalizedAnswer,
        transcript: normalizedAnswer,
        surface: "desktop",
        voice_mode: voiceMode === "desktop" ? "text" : voiceMode,
      });
      setAssessmentState(nextState);
      setAnswerDraft("");
      if (nextState.just_completed || nextState.status === "completed") {
        setPsychometricCompleted(true);
        setSuccess("测评完成，八维分值和类型已经写入长期记忆。下一步请完成主人扫脸绑定。");
      } else {
        setSuccess("已记录这轮回答，继续下一题。");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const handleSubmitAnswer = async () =>
    submitAssessmentAnswer(answerDraft, assessmentState.voice_session_active ? "robot" : "text");

  const handleDesktopVoiceAnswer = async () => {
    if (!identityReady || psychometricCompleted) {
      return;
    }
    setError("");
    if (desktopVoiceRecording && desktopVoiceRecorderRef.current) {
      setDesktopVoiceBusy(true);
      try {
        const blob = await desktopVoiceRecorderRef.current.stop();
        desktopVoiceRecorderRef.current = null;
        setDesktopVoiceRecording(false);
        const result = await transcribeDesktopAudio(blob, "activation_assessment");
        const transcript = String(result.transcript || "").trim();
        if (!transcript) {
          setError("没有识别到有效语音，请重试");
          return;
        }
        setAnswerDraft(transcript);
        await submitAssessmentAnswer(transcript, "desktop");
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setDesktopVoiceRecording(false);
        desktopVoiceRecorderRef.current = null;
      } finally {
        setDesktopVoiceBusy(false);
      }
      return;
    }
    setDesktopVoiceBusy(true);
    try {
      desktopVoiceRecorderRef.current = await createDesktopVoiceRecorder();
      setDesktopVoiceRecording(true);
      setSuccess("电脑端本地录音已开始，说完后再按一次按钮结束并提交");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      desktopVoiceRecorderRef.current = null;
      setDesktopVoiceRecording(false);
    } finally {
      setDesktopVoiceBusy(false);
    }
  };

  const handleForceFinish = async () => {
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const done = await finishAssessment();
      setAssessmentState(done);
      setPsychometricCompleted(true);
      setSuccess("测评已收束，当前结果已经落库。");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const handleToggleVoice = async () => {
    setVoiceBusy(true);
    setError("");
    setSuccess("");
    try {
      if (assessmentState.voice_session_active) {
        await stopAssessmentVoice();
        setAssessmentState((prev) => ({
          ...prev,
          voice_session_active: false,
          voice_mode: "text",
        }));
        setSuccess("机器人语音测评已停止，回到文本模式。");
      } else {
        const result = await startAssessmentVoice();
        if (result?.assessment) {
          setAssessmentState(result.assessment);
        } else {
          setAssessmentState((prev) => ({
            ...prev,
            voice_session_active: Boolean(result?.device_online),
            voice_mode: result?.device_online ? "robot" : "text",
            device_online: Boolean(result?.device_online),
          }));
        }
        if (result?.device_online) {
          setSuccess("机器人语音测评已启动，问题会由开发板本地播报。");
        } else {
          setSuccess("设备当前离线，先使用文本模式继续。");
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setVoiceBusy(false);
    }
  };

  const handleStartFaceScan = async () => {
    if (!psychometricCompleted) {
      setError("先完成测评，再启动扫脸建档。");
      return;
    }
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const response = await startOwnerEnrollment(preferredDeviceId || undefined);
      setOwnerBindingRequired(true);
      setOwnerBindingCompleted(false);
      setScanState(response?.detail || "已向机器人发送主人建档请求。");
      setSuccess("扫脸建档请求已经发到开发板，完成采样后会自动同步绑定状态。");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const handleFinish = async () => {
    if (!canFinish) {
      setError(ownerBindingRequired ? "请先完成主人扫脸绑定，再结束首次激活。" : "请先完成身份确认和人格测评。");
      return;
    }
    setFinishing(true);
    setError("");
    try {
      await onActivated();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setFinishing(false);
    }
  };

  if (booting) {
    return (
      <div className="w-screen h-screen bg-[#070b14] flex items-center justify-center text-slate-200">
        <div className="flex items-center gap-3 text-sm font-bold">
          <LoaderCircle className="animate-spin" size={18} />
          正在加载首次激活与人格测评...
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen overflow-y-auto overflow-x-hidden bg-[#070b14] text-slate-100 px-8 py-7">
      <div className="max-w-7xl mx-auto flex flex-col gap-6 pb-8">
        <div className="rounded-[2rem] border border-white/10 bg-slate-950/60 backdrop-blur-2xl px-8 py-6 flex items-center justify-between gap-6">
          <div className="flex items-center gap-4">
            <div className="w-14 h-14 rounded-3xl bg-emerald-500/15 text-emerald-300 border border-emerald-500/20 flex items-center justify-center">
              <ShieldCheck size={26} />
            </div>
            <div>
              <h1 className="text-2xl font-black tracking-tight">首次激活</h1>
              <p className="text-sm text-slate-400 font-semibold">
                先确认这个人是谁，再通过多轮轻松对话拿到完整的 8 维人格信号，最后完成主人扫脸绑定。
              </p>
            </div>
          </div>
          <button
            onClick={handleFinish}
            disabled={!canFinish || busy || finishing}
            className="px-5 py-3 rounded-2xl bg-white text-slate-950 font-black text-sm disabled:opacity-50 flex items-center gap-2"
          >
            {finishing ? <LoaderCircle className="animate-spin" size={16} /> : <CheckCircle2 size={16} />}
            完成激活并进入桌面
          </button>
        </div>

        {(error || success) && (
          <div
            className={`rounded-3xl px-5 py-4 text-sm font-semibold ${
              error ? "bg-rose-500/12 border border-rose-400/20 text-rose-200" : "bg-emerald-500/12 border border-emerald-400/20 text-emerald-200"
            }`}
          >
            {error || success}
          </div>
        )}

        <div className="grid grid-cols-12 gap-6">
          <section className="col-span-4 rounded-[2rem] border border-white/10 bg-slate-950/45 p-6 flex flex-col gap-4">
            <div className="flex items-center gap-3">
              <UserRound size={18} className="text-indigo-300" />
              <h2 className="text-lg font-black">1. 身份确认</h2>
            </div>
            <div className="rounded-3xl border border-white/10 bg-slate-900/60 p-4 space-y-3">
              <p className="text-xs text-slate-300 font-semibold leading-6">
                先输入一句自然自我介绍。系统会先尝试用 AI 生成身份草稿；如果 AI 当前不可用，会退回到本地保守规则，但会明确告诉你不是 AI 结果。
              </p>
              <div className="grid grid-cols-2 gap-3 text-[11px] font-semibold text-slate-400">
                <div className="rounded-2xl border border-white/10 bg-slate-950/60 px-3 py-3">
                  必填 1：一句自我介绍
                </div>
                <div className="rounded-2xl border border-white/10 bg-slate-950/60 px-3 py-3">
                  选填 2：如果已知称呼，可提前补上
                </div>
              </div>
            </div>
            <textarea
              value={introTranscript}
              onChange={(e) => setIntroTranscript(e.target.value)}
              placeholder="例如：我叫赵京亮，是这个机器人的主人，平时更喜欢安静、讲逻辑一点的交流。"
              className="min-h-[132px] rounded-3xl bg-slate-900/70 border border-white/10 px-4 py-4 text-sm font-semibold text-slate-100 outline-none resize-none"
            />
            <input
              value={observedName}
              onChange={(e) => setObservedName(e.target.value)}
              placeholder="补充称呼，例如：赵京亮 / 京亮 / 爸爸"
              className="rounded-2xl bg-slate-900/70 border border-white/10 px-4 py-3 text-sm font-semibold text-slate-100 outline-none"
            />
            <button
              onClick={handleInferIdentity}
              disabled={busy}
              className="rounded-2xl bg-indigo-500/15 border border-indigo-400/20 text-indigo-200 py-3 font-black text-sm flex items-center justify-center gap-2 disabled:opacity-50"
            >
              {busy ? <LoaderCircle className="animate-spin" size={16} /> : <Sparkles size={16} />}
              生成 AI 身份草稿
            </button>
            <div className={`rounded-3xl border px-4 py-4 space-y-3 ${identitySourceTone}`}>
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs font-black uppercase tracking-[0.2em]">草稿状态</span>
                <span className="text-xs font-black">
                  {identitySourceLabel} · 可信度 {Math.round((identityState.confidence || 0) * 100)}%
                </span>
              </div>
              <p className="text-xs font-semibold leading-6">
                {identityState.inference_source === "ai"
                  ? "这份身份草稿来自 AI 提取，但仍建议你人工确认后再保存。"
                  : identityState.inference_source === "confirmed"
                    ? "当前身份信息已经保存，你仍然可以在下面继续手动修正。"
                    : "当前不是 AI 草稿，而是本地保守规则给出的兜底结果。请务必人工确认。"}
              </p>
              {identityState.inference_detail && (
                <p className="text-[11px] font-semibold leading-6 opacity-90">{identityState.inference_detail}</p>
              )}
              {identityState.onboarding_notes && (
                <p className="text-[11px] font-semibold leading-6 opacity-90">{identityState.onboarding_notes}</p>
              )}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <label className="rounded-2xl bg-slate-900/70 border border-white/10 px-4 py-3 text-sm font-semibold text-slate-100">
                <div className="mb-2 text-[10px] font-black uppercase tracking-[0.2em] text-slate-500">称呼</div>
                <input
                  value={identityState.preferred_name}
                  onChange={(e) => setIdentityState((prev) => ({ ...prev, preferred_name: e.target.value }))}
                  placeholder="例如：赵京亮"
                  className="w-full bg-transparent outline-none"
                />
              </label>
              <label className="rounded-2xl bg-slate-900/70 border border-white/10 px-4 py-3 text-sm font-semibold text-slate-100">
                <div className="mb-2 text-[10px] font-black uppercase tracking-[0.2em] text-slate-500">身份角色</div>
                <select
                  value={identityState.role_label || "unknown"}
                  onChange={(e) => setIdentityState((prev) => ({ ...prev, role_label: e.target.value }))}
                  className="w-full bg-transparent outline-none"
                >
                  {ROLE_OPTIONS.map((item) => (
                    <option key={item.value} value={item.value} className="bg-slate-950 text-slate-100">
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <label className="rounded-2xl bg-slate-900/70 border border-white/10 px-4 py-3 text-sm font-semibold text-slate-100">
              <div className="mb-2 text-[10px] font-black uppercase tracking-[0.2em] text-slate-500">与机器人的关系</div>
              <select
                value={identityState.relation_to_robot || "unknown"}
                onChange={(e) => setIdentityState((prev) => ({ ...prev, relation_to_robot: e.target.value }))}
                className="w-full bg-transparent outline-none"
              >
                {RELATION_OPTIONS.map((item) => (
                  <option key={item.value} value={item.value} className="bg-slate-950 text-slate-100">
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            <textarea
              value={identityState.identity_summary}
              onChange={(e) => setIdentityState((prev) => ({ ...prev, identity_summary: e.target.value }))}
              placeholder="一句话总结这个人是谁，以及机器人之后应该以什么身份对待他。"
              className="min-h-[90px] rounded-3xl bg-slate-900/70 border border-white/10 px-4 py-4 text-sm font-semibold text-slate-100 outline-none resize-none"
            />
            <div className="rounded-3xl border border-white/10 bg-slate-900/60 p-4 text-xs leading-6 text-slate-400 font-semibold">
              当前识别结果：
              <span className="ml-2 text-slate-200">
                {identityState.preferred_name || "未识别称呼"} / {HUMAN_ROLE_LABELS[identityState.role_label] || "待确认"} /{" "}
                {HUMAN_RELATION_LABELS[identityState.relation_to_robot] || "待确认"}
              </span>
            </div>
            <button
              onClick={handleCompleteIdentity}
              disabled={busy || identityReady}
              className="rounded-2xl bg-emerald-500/15 border border-emerald-400/20 text-emerald-200 py-3 font-black text-sm flex items-center justify-center gap-2 disabled:opacity-50"
            >
              <CheckCircle2 size={16} />
              {identityReady ? "身份已确认" : "确认身份并进入测评"}
            </button>
          </section>

          <section className="col-span-5 rounded-[2rem] border border-white/10 bg-slate-950/45 p-6 flex flex-col gap-4">
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <Brain size={18} className="text-fuchsia-300" />
                <h2 className="text-lg font-black">2. 8 维人格测评</h2>
              </div>
              <button
                onClick={handleRestartAssessment}
                disabled={!identityReady || busy}
                className="text-xs font-black px-3 py-2 rounded-2xl border border-white/10 text-slate-300 disabled:opacity-40"
              >
                重开测评
              </button>
            </div>

            <div className="rounded-3xl border border-cyan-400/15 bg-cyan-500/8 p-4 space-y-3">
              <div className="flex items-center justify-between gap-3 text-xs font-black">
                <span className="text-cyan-200">当前测评模式</span>
                <span className="text-cyan-100">
                  {assessmentState.device_online ? "设备在线" : "设备离线"} · 文本测评可用
                </span>
              </div>
              <p className="text-xs leading-6 font-semibold text-cyan-100/90">{assessmentModeMessage}</p>
              <div className="flex flex-wrap gap-2 text-[11px] font-bold">
                <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-slate-200">
                  问题来源：{assessmentQuestionSourceLabel}
                </span>
                <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-slate-200">
                  当前评分：{assessmentScoringSourceLabel}
                </span>
                <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-slate-200">
                  当前维度：{assessmentState.question_pair || "待分配"}
                </span>
              </div>
            </div>

            <div className="rounded-3xl border border-white/10 bg-slate-900/70 p-4 space-y-3">
              <div className="flex items-center justify-between text-xs font-bold text-slate-400">
                <span>当前进度</span>
                <span>
                  {assessmentState.effective_turn_count}/{assessmentState.required_min_turns} 起步，最多 {assessmentState.max_turns} 轮
                </span>
              </div>
              <div className="h-2 rounded-full bg-slate-800 overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-fuchsia-500 via-cyan-400 to-emerald-400 rounded-full"
                  style={{
                    width: `${Math.min(
                      100,
                      (assessmentState.effective_turn_count / Math.max(assessmentState.required_min_turns, 1)) * 100
                    )}%`,
                  }}
                />
              </div>
              <div className="grid grid-cols-4 gap-3">
                {confidencePreview.map(([label, value]) => (
                  <div key={label} className="rounded-2xl bg-slate-950/70 border border-white/5 px-3 py-3">
                    <div className="text-[11px] text-slate-400 font-bold">{label}</div>
                    <div className="text-lg font-black text-slate-100 mt-1">{Math.round(Number(value) * 100)}%</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-3xl border border-fuchsia-400/20 bg-fuchsia-500/10 p-5">
              <div className="flex items-center gap-2 text-sm font-black text-fuchsia-200 mb-2">
                <Bot size={16} />
                当前问题
              </div>
              <div className="text-base font-bold leading-7 text-white">
                {identityReady
                  ? assessmentState.latest_question || "点击“确认身份并进入测评”后会开始第一题。"
                  : "先完成左侧身份确认。"}
              </div>
              <p className="mt-3 text-xs leading-6 font-semibold text-fuchsia-100/80">
                这不是固定标准答案测试。至少认真回答 12 轮，系统才会开始形成稳定的人格特征判断；如果信号还不够，会继续追问到最多 28 轮。
              </p>
            </div>

            <textarea
              value={answerDraft}
              onChange={(e) => setAnswerDraft(e.target.value)}
              placeholder="请用自然语言真实作答。可以讲偏好、例子、习惯和原因，越具体越容易测出稳定人格特征。"
              disabled={!identityReady || psychometricCompleted}
              className="min-h-[132px] rounded-3xl bg-slate-900/70 border border-white/10 px-4 py-4 text-sm font-semibold text-slate-100 outline-none resize-none disabled:opacity-50"
            />

            <div className="flex items-center gap-3 flex-wrap">
              <button
                onClick={handleSubmitAnswer}
                disabled={!identityReady || busy || psychometricCompleted}
                className="rounded-2xl bg-white text-slate-950 px-5 py-3 text-sm font-black flex items-center gap-2 disabled:opacity-50"
              >
                {busy ? <LoaderCircle className="animate-spin" size={16} /> : <ChevronRight size={16} />}
                提交这一轮回答
              </button>
              <button
                onClick={handleToggleVoice}
                disabled={!canUseRobotVoice || voiceBusy || psychometricCompleted}
                className="rounded-2xl border border-cyan-400/25 bg-cyan-500/10 text-cyan-200 px-5 py-3 text-sm font-black flex items-center gap-2 disabled:opacity-50"
              >
                {voiceBusy ? (
                  <LoaderCircle className="animate-spin" size={16} />
                ) : assessmentState.voice_session_active ? (
                  <PauseCircle size={16} />
                ) : (
                  <PlayCircle size={16} />
                )}
                {assessmentState.voice_session_active
                  ? "停止机器人语音测评"
                  : assessmentState.device_online
                    ? "开启机器人语音测评"
                    : "设备离线，机器人语音不可用"}
              </button>
              <button
                onClick={handleDesktopVoiceAnswer}
                disabled={!identityReady || desktopVoiceBusy || busy || psychometricCompleted}
                className="rounded-2xl border border-amber-400/25 bg-amber-500/10 text-amber-200 px-5 py-3 text-sm font-black flex items-center gap-2 disabled:opacity-50"
              >
                {desktopVoiceBusy ? (
                  <LoaderCircle className="animate-spin" size={16} />
                ) : desktopVoiceRecording ? (
                  <PauseCircle size={16} />
                ) : (
                  <Mic size={16} />
                )}
                {desktopVoiceRecording ? "结束本地语音回答" : "本地语音回答"}
              </button>
              <button
                onClick={handleForceFinish}
                disabled={!identityReady || busy || psychometricCompleted}
                className="rounded-2xl border border-white/10 text-slate-300 px-5 py-3 text-sm font-black flex items-center gap-2 disabled:opacity-50"
              >
                <Brain size={16} />
                以当前结果收束
              </button>
            </div>

            <div className="grid grid-cols-4 gap-3">
              {scorePreview.map(([label, value]) => (
                <div key={label} className="rounded-2xl bg-slate-900/70 border border-white/10 px-3 py-3">
                  <div className="text-[11px] text-slate-400 font-bold">{label}</div>
                  <div className="text-lg font-black text-slate-100 mt-1">{Number(value).toFixed(1)}</div>
                </div>
              ))}
            </div>
            <div className="rounded-3xl border border-white/10 bg-slate-900/60 p-4 text-xs leading-6 text-slate-400 font-semibold">
              判定逻辑说明：每一轮回答会先尝试走 AI 编排与 AI 评分；如果当前模型不可用，系统会降级到题库问题和保守规则评分，保证测评可以继续，但页面会明确标出不是 AI 结果。
            </div>
          </section>

          <section className="col-span-3 rounded-[2rem] border border-white/10 bg-slate-950/45 p-6 flex flex-col gap-4">
            <div className="flex items-center gap-3">
              <Camera size={18} className="text-emerald-300" />
              <h2 className="text-lg font-black">3. 结果与扫脸</h2>
            </div>

            <div className="rounded-3xl bg-slate-900/70 border border-white/10 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-slate-400">测评类型</span>
                <span className="text-xl font-black text-white">{assessmentState.type_code || "--"}</span>
              </div>
              <p className="text-sm leading-6 font-semibold text-slate-200">
                {assessmentState.summary || "测评完成后，这里会出现类型摘要和后续陪伴建议。"}
              </p>
              <div className="text-xs text-slate-400 font-semibold">
                最近信号：{assessmentState.evidence_summary.highlights.join(" / ") || "暂无"}
              </div>
            </div>

            <div className="rounded-3xl bg-slate-900/70 border border-white/10 p-4 space-y-3">
              <div className="flex items-center gap-2 text-sm font-black text-slate-100">
                <Mic size={16} />
                机器人语音状态
              </div>
              <p className="text-xs leading-6 font-semibold text-slate-400">
                机器人语音只是“播报 + 录音 + 转写”的硬件链路；真正的人格测评核心仍然在后端文本/AI分析，不会因为设备离线就完全无法测。
              </p>
              <div className="text-sm font-bold text-slate-200">
                {assessmentState.device_online
                  ? assessmentState.voice_session_active
                    ? "设备在线，机器人语音模式已开启"
                    : "设备在线，但当前仍可直接用文本模式继续"
                  : "设备离线，当前自动退回文本测评"}
              </div>
              <div className="text-xs leading-6 font-semibold text-slate-400">
                最近转写：{assessmentState.latest_transcript || "暂无"}
              </div>
              <div className="text-xs leading-6 font-semibold text-slate-400">
                主人绑定：{ownerBindingCompleted ? "已完成" : ownerBindingRequired ? "待完成" : "未要求"}
                {preferredDeviceId ? ` · 设备 ${preferredDeviceId}` : ""}
              </div>
            </div>

            <button
              onClick={handleStartFaceScan}
              disabled={busy || !psychometricCompleted || ownerBindingCompleted}
              className="rounded-2xl bg-emerald-500/15 border border-emerald-400/20 text-emerald-200 py-3 font-black text-sm flex items-center justify-center gap-2 disabled:opacity-50"
            >
              {busy ? <LoaderCircle className="animate-spin" size={16} /> : <ScanFace size={16} />}
              {ownerBindingCompleted ? "主人已完成扫脸绑定" : "启动主人扫脸建档"}
            </button>

            <div className="rounded-3xl border border-white/10 bg-slate-900/70 p-4 text-xs leading-6 text-slate-400 font-semibold">
              {scanState || "扫脸只能在登录且完成人格测评后启动；有设备时，首次激活会要求完成主人绑定。"}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
};
