import React, { useEffect, useMemo, useState } from "react";
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

export const ActivationGate: React.FC<ActivationGateProps> = ({ onActivated }) => {
  const [booting, setBooting] = useState(true);
  const [busy, setBusy] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [voiceBusy, setVoiceBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [identityReady, setIdentityReady] = useState(false);
  const [psychometricCompleted, setPsychometricCompleted] = useState(false);
  const [identityState, setIdentityState] = useState(emptyIdentity);
  const [assessmentState, setAssessmentState] = useState<ActivationAssessmentState>(emptyAssessment);
  const [introTranscript, setIntroTranscript] = useState("");
  const [observedName, setObservedName] = useState("");
  const [answerDraft, setAnswerDraft] = useState("");
  const [scanState, setScanState] = useState("");

  const loadState = async () => {
    const [activation, assessment] = await Promise.all([getActivationState(), getAssessmentState()]);
    const identityDone = !activation.activation_required;
    const assessmentDone =
      activation.psychometric_completed || assessment.status === "completed" || Boolean(assessment.completed_at_ms);

    setIdentityReady(identityDone);
    setPsychometricCompleted(Boolean(assessmentDone));
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
      raw_json: {},
    });
    setAssessmentState(assessment);

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

  const canFinish = identityReady && psychometricCompleted;
  const scorePreview = useMemo(() => scoreItems(assessmentState.scores), [assessmentState.scores]);
  const confidencePreview = useMemo(
    () => confidenceItems(assessmentState.dimension_confidence),
    [assessmentState.dimension_confidence]
  );

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

  const handleSubmitAnswer = async () => {
    if (!answerDraft.trim()) {
      setError("先输入这一轮回答。");
      return;
    }
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const nextState = await submitAssessmentTurn({
        answer: answerDraft.trim(),
        transcript: answerDraft.trim(),
        surface: "desktop",
        voice_mode: assessmentState.voice_session_active ? "robot" : "text",
      });
      setAssessmentState(nextState);
      setAnswerDraft("");
      if (nextState.just_completed || nextState.status === "completed") {
        setPsychometricCompleted(true);
        setSuccess("测评完成，八维分值和类型已经写入长期记忆。现在可以做扫脸建档。");
      } else {
        setSuccess("已记录这轮回答，继续下一题。");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
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
      const response = await startOwnerEnrollment();
      setScanState(response?.detail || "已向机器人发送主人建档请求。");
      setSuccess("扫脸建档请求已经发到开发板。");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const handleFinish = async () => {
    if (!canFinish) {
      setError("请先完成身份确认和人格测评。");
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
    <div className="min-h-screen bg-[#070b14] text-slate-100 px-8 py-7">
      <div className="max-w-7xl mx-auto flex flex-col gap-6">
        <div className="rounded-[2rem] border border-white/10 bg-slate-950/60 backdrop-blur-2xl px-8 py-6 flex items-center justify-between gap-6">
          <div className="flex items-center gap-4">
            <div className="w-14 h-14 rounded-3xl bg-emerald-500/15 text-emerald-300 border border-emerald-500/20 flex items-center justify-center">
              <ShieldCheck size={26} />
            </div>
            <div>
              <h1 className="text-2xl font-black tracking-tight">首次激活</h1>
              <p className="text-sm text-slate-400 font-semibold">
                先确认这个人是谁，再通过多轮轻松对话拿到完整的 8 维人格信号，最后再做扫脸主人建档。
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
            <p className="text-xs text-slate-400 font-semibold leading-6">
              这一段只做“这个人是谁”的确认。先让对方做一句自我介绍，例如“我叫小北，是这个机器人的主人”。
            </p>
            <textarea
              value={introTranscript}
              onChange={(e) => setIntroTranscript(e.target.value)}
              placeholder="输入第一次自我介绍，或者把机器人语音转写贴进来。"
              className="min-h-[132px] rounded-3xl bg-slate-900/70 border border-white/10 px-4 py-4 text-sm font-semibold text-slate-100 outline-none resize-none"
            />
            <input
              value={observedName}
              onChange={(e) => setObservedName(e.target.value)}
              placeholder="如果已经知道称呼，可以先填在这里"
              className="rounded-2xl bg-slate-900/70 border border-white/10 px-4 py-3 text-sm font-semibold text-slate-100 outline-none"
            />
            <button
              onClick={handleInferIdentity}
              disabled={busy}
              className="rounded-2xl bg-indigo-500/15 border border-indigo-400/20 text-indigo-200 py-3 font-black text-sm flex items-center justify-center gap-2 disabled:opacity-50"
            >
              {busy ? <LoaderCircle className="animate-spin" size={16} /> : <Sparkles size={16} />}
              生成身份草稿
            </button>
            <div className="grid grid-cols-2 gap-3">
              <input
                value={identityState.preferred_name}
                onChange={(e) => setIdentityState((prev) => ({ ...prev, preferred_name: e.target.value }))}
                placeholder="称呼"
                className="rounded-2xl bg-slate-900/70 border border-white/10 px-4 py-3 text-sm font-semibold outline-none"
              />
              <input
                value={identityState.role_label}
                onChange={(e) => setIdentityState((prev) => ({ ...prev, role_label: e.target.value }))}
                placeholder="角色"
                className="rounded-2xl bg-slate-900/70 border border-white/10 px-4 py-3 text-sm font-semibold outline-none"
              />
            </div>
            <input
              value={identityState.relation_to_robot}
              onChange={(e) => setIdentityState((prev) => ({ ...prev, relation_to_robot: e.target.value }))}
              placeholder="与机器人的关系"
              className="rounded-2xl bg-slate-900/70 border border-white/10 px-4 py-3 text-sm font-semibold outline-none"
            />
            <textarea
              value={identityState.identity_summary}
              onChange={(e) => setIdentityState((prev) => ({ ...prev, identity_summary: e.target.value }))}
              placeholder="身份摘要"
              className="min-h-[90px] rounded-3xl bg-slate-900/70 border border-white/10 px-4 py-4 text-sm font-semibold text-slate-100 outline-none resize-none"
            />
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
            </div>

            <textarea
              value={answerDraft}
              onChange={(e) => setAnswerDraft(e.target.value)}
              placeholder="把这一轮回答输入这里；如果走机器人语音模式，也可以把转写内容贴进来。"
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
                disabled={!identityReady || voiceBusy || psychometricCompleted}
                className="rounded-2xl border border-cyan-400/25 bg-cyan-500/10 text-cyan-200 px-5 py-3 text-sm font-black flex items-center gap-2 disabled:opacity-50"
              >
                {voiceBusy ? (
                  <LoaderCircle className="animate-spin" size={16} />
                ) : assessmentState.voice_session_active ? (
                  <PauseCircle size={16} />
                ) : (
                  <PlayCircle size={16} />
                )}
                {assessmentState.voice_session_active ? "停止机器人语音测评" : "开启机器人语音测评"}
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
                语音测评走开发板本地半双工：开发板本地播报问题、录音、转写，再由后端编排下一轮。
              </p>
              <div className="text-sm font-bold text-slate-200">
                {assessmentState.device_online
                  ? assessmentState.voice_session_active
                    ? "设备在线，机器人语音模式已开启"
                    : "设备在线，但当前使用文本模式"
                  : "设备离线，当前只能文本模式"}
              </div>
              <div className="text-xs leading-6 font-semibold text-slate-400">
                最近转写：{assessmentState.latest_transcript || "暂无"}
              </div>
            </div>

            <button
              onClick={handleStartFaceScan}
              disabled={busy || !psychometricCompleted}
              className="rounded-2xl bg-emerald-500/15 border border-emerald-400/20 text-emerald-200 py-3 font-black text-sm flex items-center justify-center gap-2 disabled:opacity-50"
            >
              {busy ? <LoaderCircle className="animate-spin" size={16} /> : <ScanFace size={16} />}
              启动主人扫脸建档
            </button>

            <div className="rounded-3xl border border-white/10 bg-slate-900/70 p-4 text-xs leading-6 text-slate-400 font-semibold">
              {scanState || "扫脸只能在登录且完成人格测评后启动。"}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
};
