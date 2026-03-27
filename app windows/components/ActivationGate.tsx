import React, { useEffect, useMemo, useRef, useState } from "react";
import { Brain, Camera, CheckCircle2, ChevronRight, LoaderCircle, Mic, PauseCircle, PlayCircle, ScanFace, ShieldCheck, Sparkles, UserRound } from "lucide-react";

import { getActivationState } from "../services/authService";
import {
  completeActivation,
  finishAssessment,
  getAssessmentState,
  getActivationRuntimeStatus,
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
  type ActivationRuntimeStatus,
} from "../services/activationService";
import { createDesktopVoiceRecorder, getDesktopVoiceStatus, transcribeDesktopAudio, type DesktopVoiceStatus } from "../services/desktopVoiceService";

interface ActivationGateProps { onActivated: () => Promise<void> | void; }
const ROLE_OPTIONS = [{ value: "owner", label: "主人" }, { value: "family", label: "家人" }, { value: "caregiver", label: "照护者" }];
const RELATION_OPTIONS = [{ value: "primary_user", label: "主要使用者" }, { value: "family_member", label: "家庭成员" }, { value: "caregiver", label: "照护关系" }];
const FUNCTION_LABELS: Record<string, string> = { Se: "外倾感觉", Si: "内倾感觉", Ne: "外倾直觉", Ni: "内倾直觉", Te: "外倾思考", Ti: "内倾思考", Fe: "外倾情感", Fi: "内倾情感" };

const emptyIdentity = (): ActivationIdentityInference => ({ ok: false, preferred_name: "", role_label: "owner", relation_to_robot: "primary_user", pronouns: "", identity_summary: "", onboarding_notes: "", voice_intro_summary: "", confidence: 0, inference_source: "blocked", inference_detail: "", raw_json: {} });
const emptyAssessment = (): ActivationAssessmentState => ({
  ok: true, exists: false, status: "idle", turn_count: 0, effective_turn_count: 0, latest_question: "", latest_transcript: "", last_question_id: "",
  type_code: "", mapped_type_code: "", cognitive_scores: { Se: 0, Si: 0, Ne: 0, Ni: 0, Te: 0, Ti: 0, Fe: 0, Fi: 0 }, function_confidence: { Se: 0, Si: 0, Ne: 0, Ni: 0, Te: 0, Ti: 0, Fe: 0, Fi: 0 },
  evidence_summary: { highlights: [], notes: "" }, dominant_stack: [], conversation_count: 0, finish_reason: "", voice_mode: "idle", voice_session_active: false, device_online: false,
  summary: "", response_style: "", care_style: "", inference_version: "assessment-v2-jung8", required_min_turns: 12, max_turns: 28, question_source: "ai_required", scoring_source: "pending",
  question_pair: "", mode_hint: "ai_blocked", can_submit_text: false, assessment_ready: false, ai_required: true, blocking_reason: "",
});
const emptyRuntime = (): ActivationRuntimeStatus => ({ ok: true, ai_ready: false, ai_detail: "", gateway_ready: false, provider_network_ok: false, blocking_reason: "", text_assessment_ready: false, desktop_voice_ready: false, desktop_voice_detail: "", device_online: false, robot_voice_ready: false, preferred_device_id: "" });
const emptyDesktopVoice = (): DesktopVoiceStatus => ({ ok: false, ready: false, provider_preference: "faster_whisper", fallback_provider: "sherpa_onnx", active_provider: "", primary_ready: false, primary_engine: "", primary_error: "", fallback_ready: false, fallback_engine: "", fallback_error: "", language: "zh", max_sec: 45, model_name: "small", beam_size: 5, best_of: 5, preprocess_enabled: true, trim_silence_enabled: true, initial_prompt_enabled: false, hotwords_enabled: false });
const sortedFunctions = (scores: ActivationAssessmentState["cognitive_scores"]) => Object.entries(scores).sort((a, b) => b[1] - a[1]);

export function ActivationGate({ onActivated }: ActivationGateProps) {
  const [booting, setBooting] = useState(true);
  const [busy, setBusy] = useState(false);
  const [voiceBusy, setVoiceBusy] = useState(false);
  const [desktopVoiceBusy, setDesktopVoiceBusy] = useState(false);
  const [desktopVoiceRecording, setDesktopVoiceRecording] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [identityReady, setIdentityReady] = useState(false);
  const [psychometricCompleted, setPsychometricCompleted] = useState(false);
  const [ownerBindingRequired, setOwnerBindingRequired] = useState(false);
  const [ownerBindingCompleted, setOwnerBindingCompleted] = useState(false);
  const [preferredDeviceId, setPreferredDeviceId] = useState("");
  const [runtime, setRuntime] = useState<ActivationRuntimeStatus>(emptyRuntime);
  const [desktopVoiceStatus, setDesktopVoiceStatus] = useState<DesktopVoiceStatus>(emptyDesktopVoice);
  const [identity, setIdentity] = useState<ActivationIdentityInference>(emptyIdentity);
  const [assessment, setAssessment] = useState<ActivationAssessmentState>(emptyAssessment);
  const [introTranscript, setIntroTranscript] = useState("");
  const [observedName, setObservedName] = useState("");
  const [answerDraft, setAnswerDraft] = useState("");
  const [scanState, setScanState] = useState("");
  const recorderRef = useRef<{ stop: () => Promise<Blob> } | null>(null);

  const fail = (value: unknown) => (value instanceof Error ? value.message : String(value));
  const canFinish = identityReady && psychometricCompleted && (!ownerBindingRequired || ownerBindingCompleted);
  const aiTone = runtime.ai_ready ? "border-emerald-400/20 bg-emerald-500/10 text-emerald-200" : "border-amber-400/20 bg-amber-500/10 text-amber-200";
  const functionCards = useMemo(() => sortedFunctions(assessment.cognitive_scores), [assessment.cognitive_scores]);
  const progress = assessment.max_turns > 0 ? Math.min(100, (assessment.effective_turn_count / assessment.max_turns) * 100) : 0;

  const loadState = async () => {
    const [activation, assessmentState, runtimeState, desktopVoice] = await Promise.all([
      getActivationState(),
      getAssessmentState(),
      getActivationRuntimeStatus().catch(() => emptyRuntime()),
      getDesktopVoiceStatus().catch(() => emptyDesktopVoice()),
    ]);
    const identityDone = !activation.activation_required;
    const assessmentDone = activation.psychometric_completed || assessmentState.status === "completed" || Boolean(assessmentState.completed_at_ms);
    const preferredDevice = String(activation.preferred_device_id || "").trim();
    setIdentityReady(identityDone);
    setPsychometricCompleted(Boolean(assessmentDone));
    setOwnerBindingRequired(Boolean(activation.owner_binding_required));
    setOwnerBindingCompleted(Boolean(activation.owner_binding_completed));
    setPreferredDeviceId(preferredDevice);
    setRuntime(runtimeState);
    setDesktopVoiceStatus(desktopVoice);
    setIdentity({ ok: identityDone, preferred_name: activation.preferred_name || "", role_label: activation.role_label || "owner", relation_to_robot: activation.relation_to_robot || "primary_user", pronouns: activation.pronouns || "", identity_summary: activation.identity_summary || "", onboarding_notes: activation.onboarding_notes || "", voice_intro_summary: activation.voice_intro_summary || "", confidence: identityDone ? 1 : 0, inference_source: identityDone ? "confirmed" : "blocked", inference_detail: identityDone ? "身份信息已确认。" : "", raw_json: {} });
    setAssessment({ ...assessmentState, device_online: Boolean(assessmentState.device_online || runtimeState.device_online) });
    setScanState(preferredDevice ? (activation.owner_binding_completed ? `主人档案已绑定到设备 ${preferredDevice}。` : `人格测评完成后，可在设备 ${preferredDevice} 上做人脸绑定。`) : "");
    if (identityDone && !assessmentDone && !assessmentState.exists && runtimeState.ai_ready) {
      setAssessment(await startAssessment({ surface: "desktop", voice_mode: "text", reset: false }));
    }
  };

  useEffect(() => {
    let active = true;
    (async () => {
      try { await loadState(); } catch (err) { if (active) setError(fail(err)); } finally { if (active) setBooting(false); }
    })();
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!assessment.voice_session_active || psychometricCompleted) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const result = await pollAssessmentVoice({ speakQuestion: true, windowMs: 5200 });
        if (cancelled) return;
        setAssessment(result.state);
        if (result.state.status === "completed") setPsychometricCompleted(true);
        if (result.state.blocking_reason) setError(result.state.blocking_reason);
      } catch (err) { if (!cancelled) setError(fail(err)); }
    };
    void tick();
    const timer = window.setInterval(() => void tick(), 2200);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [assessment.voice_session_active, psychometricCompleted]);

  useEffect(() => {
    if (!preferredDeviceId || !ownerBindingRequired || ownerBindingCompleted) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const status = await getOwnerBindingStatus(preferredDeviceId);
        if (cancelled) return;
        if (status.enrolled) {
          setOwnerBindingCompleted(true);
          setOwnerBindingRequired(false);
          setScanState(`主人绑定完成，设备 ${status.device_id} 已可用于本地识别。`);
          setSuccess("主人脸部绑定完成。");
        }
      } catch {}
    };
    void tick();
    const timer = window.setInterval(() => void tick(), 3200);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [preferredDeviceId, ownerBindingRequired, ownerBindingCompleted]);

  const handleInferIdentity = async () => {
    if (!introTranscript.trim()) return setError("先输入一句自然自我介绍。");
    setBusy(true); setError(""); setSuccess("");
    try {
      const result = await inferActivationIdentity({ transcript: introTranscript.trim(), observed_name: observedName.trim(), surface: "desktop", context: { entrypoint: "activation_gate" } });
      setIdentity(result);
      if (!result.ok) return setError(result.inference_detail || "AI 身份草稿暂不可用。");
      setSuccess("AI 身份草稿已生成，请确认后保存。");
    } catch (err) { setError(fail(err)); } finally { setBusy(false); }
  };

  const handleCompleteIdentity = async () => {
    if (!identity.preferred_name.trim() || !identity.identity_summary.trim()) return setError("请先补全称呼和身份摘要。");
    setBusy(true); setError(""); setSuccess("");
    try {
      await completeActivation({ preferred_name: identity.preferred_name.trim(), role_label: identity.role_label, relation_to_robot: identity.relation_to_robot, pronouns: identity.pronouns, identity_summary: identity.identity_summary.trim(), onboarding_notes: identity.onboarding_notes.trim(), voice_intro_summary: identity.voice_intro_summary.trim(), profile: { identity_source: identity.inference_source, raw_json: identity.raw_json }, activation_version: "activation-ai-only-v2" });
      setIdentityReady(true);
      setSuccess("身份确认已保存。");
      await loadState();
    } catch (err) { setError(fail(err)); } finally { setBusy(false); }
  };

  const handleStartAssessment = async (reset = false) => {
    setBusy(true); setError(""); setSuccess("");
    try {
      const result = await startAssessment({ surface: "desktop", voice_mode: "text", reset, device_id: preferredDeviceId || undefined });
      setAssessment(result);
      result.blocking_reason ? setError(result.blocking_reason) : setSuccess(reset ? "正式测评已重置。" : "正式测评已开始。");
    } catch (err) { setError(fail(err)); } finally { setBusy(false); }
  };

  const handleSubmitTurn = async () => {
    if (!answerDraft.trim()) return setError("请先输入这一轮回答。");
    setBusy(true); setError(""); setSuccess("");
    try {
      const result = await submitAssessmentTurn({ answer: answerDraft.trim(), transcript: answerDraft.trim(), surface: "desktop", device_id: preferredDeviceId || undefined, voice_mode: assessment.voice_session_active ? "robot" : "text" });
      setAssessment(result);
      setAnswerDraft("");
      if (result.blocking_reason) setError(result.blocking_reason);
      else if (result.just_completed) { setPsychometricCompleted(true); setSuccess("AI 测评结果已稳定。"); }
      else setSuccess("这一轮回答已计入正式测评。");
    } catch (err) { setError(fail(err)); } finally { setBusy(false); }
  };

  const handleDesktopVoiceToggle = async () => {
    if (!desktopVoiceStatus.ready) return setError(desktopVoiceStatus.primary_error || desktopVoiceStatus.fallback_error || "电脑麦克风不可用。");
    setDesktopVoiceBusy(true); setError(""); setSuccess("");
    try {
      if (!desktopVoiceRecording) {
        recorderRef.current = await createDesktopVoiceRecorder();
        setDesktopVoiceRecording(true);
        setSuccess("电脑麦克风录音已开始。");
      } else {
        const blob = await recorderRef.current!.stop();
        recorderRef.current = null;
        setDesktopVoiceRecording(false);
        const transcript = await transcribeDesktopAudio(blob);
        if (!transcript.text.trim()) throw new Error("没有识别到有效语音内容。");
        setAnswerDraft(transcript.text.trim());
        setSuccess("转写完成，已填入回答框。");
      }
    } catch (err) { recorderRef.current = null; setDesktopVoiceRecording(false); setError(fail(err)); } finally { setDesktopVoiceBusy(false); }
  };

  const handleRobotVoiceToggle = async () => {
    if (!preferredDeviceId || !runtime.robot_voice_ready) return;
    setVoiceBusy(true); setError(""); setSuccess("");
    try {
      if (assessment.voice_session_active) {
        await stopAssessmentVoice(preferredDeviceId);
        setAssessment((prev) => ({ ...prev, voice_session_active: false, voice_mode: "text" }));
        setSuccess("机器人语音测评已停止。");
      } else {
        await startAssessmentVoice(preferredDeviceId);
        setAssessment((prev) => ({ ...prev, voice_session_active: true, voice_mode: "robot", device_online: true }));
        setSuccess("机器人语音测评已启动。");
      }
    } catch (err) { setError(fail(err)); } finally { setVoiceBusy(false); }
  };

  const handleFinishAssessment = async () => {
    setBusy(true); setError(""); setSuccess("");
    try {
      const result = await finishAssessment();
      setAssessment(result);
      setPsychometricCompleted(true);
      setSuccess("正式人格结果已写入长期记忆。");
      await loadState();
    } catch (err) { setError(fail(err)); } finally { setBusy(false); }
  };

  const handleStartOwnerScan = async () => {
    if (!preferredDeviceId) return setError("还没有可用设备。");
    setBusy(true); setError(""); setSuccess("");
    try {
      const result = await startOwnerEnrollment(preferredDeviceId);
      setScanState(result.detail || `已向设备 ${preferredDeviceId} 发送主人扫描请求。`);
      setSuccess("主人扫描流程已启动。");
    } catch (err) { setError(fail(err)); } finally { setBusy(false); }
  };

  const handleFinishActivation = async () => {
    setFinishing(true); setError("");
    try { await onActivated(); } catch (err) { setError(fail(err)); } finally { setFinishing(false); }
  };

  if (booting) return <div className="flex min-h-screen items-center justify-center bg-[#0a0a10] text-white"><div className="flex items-center gap-3 rounded-2xl border border-white/10 bg-white/5 px-6 py-4"><LoaderCircle className="h-5 w-5 animate-spin" />正在加载首次激活状态…</div></div>;

  return (
    <div className="h-screen overflow-y-auto overflow-x-hidden bg-[#0a0a10] px-10 py-9 text-white">
      <div className="mx-auto flex max-w-[1240px] flex-col gap-8 pb-16">
        <section className="rounded-[36px] border border-violet-500/40 bg-[#171521] px-10 py-8">
          <div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-start gap-5"><div className="flex h-18 w-18 items-center justify-center rounded-[24px] bg-emerald-500/15 text-emerald-300"><ShieldCheck className="h-8 w-8" /></div><div className="space-y-2"><h1 className="text-4xl font-black tracking-tight">首次激活</h1><p className="max-w-[760px] text-lg text-violet-100/85">先确认身份，再由同一条 OpenClaw / 生产 AI 链完成正式八功能测评，最后把精炼人格索引写入长期记忆。</p></div></div>
            <button type="button" onClick={handleFinishActivation} disabled={!canFinish || finishing} className="inline-flex items-center justify-center gap-3 rounded-[20px] bg-white px-6 py-4 text-lg font-semibold text-[#171521] transition disabled:cursor-not-allowed disabled:bg-white/20 disabled:text-white/40">{finishing ? <LoaderCircle className="h-5 w-5 animate-spin" /> : <CheckCircle2 className="h-5 w-5" />}完成激活并进入桌面</button>
          </div>
        </section>

        <section className={`rounded-[28px] border px-6 py-5 ${aiTone}`}>
          <div className="flex flex-wrap items-center gap-3"><Brain className="h-5 w-5" /><span className="text-lg font-semibold">{runtime.ai_ready ? "AI 在线，可开始正式测评" : "AI 未就绪，正式测评已暂停"}</span><span className="rounded-full border border-current/20 px-3 py-1 text-sm">Gateway: {runtime.gateway_ready ? "ready" : "offline"}</span><span className="rounded-full border border-current/20 px-3 py-1 text-sm">Provider: {runtime.provider_network_ok ? "reachable" : "blocked"}</span></div>
          <p className="mt-3 text-sm opacity-90">{runtime.blocking_reason || runtime.ai_detail || "AI 正常时，身份草稿与人格测评都会进入正式链路。"}</p>
        </section>

        {(error || success) && <section className="grid gap-3">{error && <div className="rounded-2xl border border-rose-400/30 bg-rose-500/10 px-5 py-4 text-rose-200">{error}</div>}{success && <div className="rounded-2xl border border-emerald-400/30 bg-emerald-500/10 px-5 py-4 text-emerald-200">{success}</div>}</section>}

        <section className="grid gap-6 xl:grid-cols-[1.1fr_1.5fr_0.9fr]">
          <div className="rounded-[32px] border border-violet-500/35 bg-[#181622] p-6">
            <div className="mb-6 flex items-center gap-3"><UserRound className="h-5 w-5 text-fuchsia-300" /><h2 className="text-2xl font-black tracking-tight">1. 身份确认</h2></div>
            <p className="mb-5 text-sm leading-7 text-violet-100/75">AI 在线时可以生成正式身份草稿；AI 不在线时，你仍可手动填写，但不会再展示伪造的本地草稿结果。</p>
            <div className="space-y-4">
              <textarea value={introTranscript} onChange={(e) => setIntroTranscript(e.target.value)} placeholder="先输入一句自然自我介绍，例如：我叫京亮，是这个机器人的主人。" className="min-h-[160px] w-full rounded-[26px] border border-violet-500/35 bg-[#1b1927] px-5 py-4 text-lg text-white outline-none placeholder:text-violet-100/45" />
              <input value={observedName} onChange={(e) => setObservedName(e.target.value)} placeholder="如果你已经知道称呼，可以先补充在这里" className="w-full rounded-[20px] border border-violet-500/35 bg-[#1b1927] px-5 py-4 text-lg text-white outline-none placeholder:text-violet-100/45" />
              <button type="button" onClick={handleInferIdentity} disabled={busy || !introTranscript.trim()} className="flex w-full items-center justify-center gap-3 rounded-[20px] bg-[#56207f] px-5 py-4 text-lg font-semibold text-fuchsia-200 transition hover:bg-[#6c29a0] disabled:cursor-not-allowed disabled:opacity-50">{busy ? <LoaderCircle className="h-5 w-5 animate-spin" /> : <Sparkles className="h-5 w-5" />}生成 AI 身份草稿</button>
              <div className={`rounded-[24px] border px-5 py-4 text-sm leading-7 ${identity.ok && identity.inference_source === "ai" ? "border-emerald-400/25 bg-emerald-500/10 text-emerald-200" : "border-amber-400/25 bg-amber-500/10 text-amber-100"}`}><div className="mb-2 flex items-center justify-between"><span className="font-semibold">草稿状态</span><span>{identity.ok && identity.inference_source === "ai" ? `AI 草稿 · 可信度 ${Math.round(identity.confidence * 100)}%` : "AI 未就绪 / 草稿未生成"}</span></div><p>{identity.inference_detail || "只有 AI 真正返回结构化结果后，这里才会显示正式草稿。"}</p></div>
              <div className="grid gap-4 md:grid-cols-2"><input value={identity.preferred_name} onChange={(e) => setIdentity((prev) => ({ ...prev, preferred_name: e.target.value }))} placeholder="称呼" className="rounded-[22px] border border-violet-500/35 bg-[#1b1927] px-5 py-4 text-lg text-white outline-none" /><select value={identity.role_label} onChange={(e) => setIdentity((prev) => ({ ...prev, role_label: e.target.value }))} className="rounded-[22px] border border-violet-500/35 bg-[#1b1927] px-5 py-4 text-lg text-white outline-none">{ROLE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></div>
              <select value={identity.relation_to_robot} onChange={(e) => setIdentity((prev) => ({ ...prev, relation_to_robot: e.target.value }))} className="w-full rounded-[22px] border border-violet-500/35 bg-[#1b1927] px-5 py-4 text-lg text-white outline-none">{RELATION_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select>
              <textarea value={identity.identity_summary} onChange={(e) => setIdentity((prev) => ({ ...prev, identity_summary: e.target.value }))} placeholder="身份摘要：这个人和机器人是什么关系，后续应该如何称呼和服务。" className="min-h-[150px] w-full rounded-[26px] border border-violet-500/35 bg-[#1b1927] px-5 py-4 text-lg text-white outline-none placeholder:text-violet-100/45" />
              <textarea value={identity.onboarding_notes} onChange={(e) => setIdentity((prev) => ({ ...prev, onboarding_notes: e.target.value }))} placeholder="激活备注：还需要人工确认什么。" className="min-h-[120px] w-full rounded-[26px] border border-violet-500/35 bg-[#1b1927] px-5 py-4 text-lg text-white outline-none placeholder:text-violet-100/45" />
              <button type="button" onClick={handleCompleteIdentity} disabled={busy} className="flex w-full items-center justify-center gap-3 rounded-[20px] bg-emerald-500/15 px-5 py-4 text-lg font-semibold text-emerald-200 transition hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-50"><CheckCircle2 className="h-5 w-5" />身份已确认</button>
            </div>
          </div>

          <div className="rounded-[32px] border border-violet-500/35 bg-[#181622] p-6">
            <div className="mb-6 flex items-center justify-between gap-3"><div className="flex items-center gap-3"><Brain className="h-5 w-5 text-violet-300" /><h2 className="text-2xl font-black tracking-tight">2. 八功能正式测评</h2></div><button type="button" onClick={() => void handleStartAssessment(true)} disabled={busy || !identityReady} className="rounded-full border border-violet-400/25 px-4 py-2 text-sm text-violet-100/85 transition hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-40">重新测评</button></div>
            <div className={`mb-5 rounded-[24px] border px-5 py-4 ${aiTone}`}><div className="mb-3 flex flex-wrap items-center gap-3 text-sm"><span className="font-semibold">当前测评模式</span><span className="rounded-full border border-current/20 px-3 py-1">问题来源：{assessment.question_source}</span><span className="rounded-full border border-current/20 px-3 py-1">当前评分：{assessment.scoring_source}</span><span className="rounded-full border border-current/20 px-3 py-1">当前缺口：{assessment.question_pair || "待分配"}</span></div><p className="text-sm leading-7 opacity-90">{assessment.blocking_reason || (runtime.ai_ready ? "正式测评只会在真实 AI 评分的基础上继续推进。" : "AI 未就绪时，不会生成假题目，也不会累计假分数。")}</p></div>
            <div className="mb-5 rounded-[24px] border border-violet-500/30 bg-[#1b1927] p-5"><div className="mb-3 flex items-center justify-between text-sm text-violet-100/80"><span>当前进度</span><span>{assessment.effective_turn_count}/{assessment.required_min_turns} 起步，最多 {assessment.max_turns} 轮</span></div><div className="h-3 rounded-full bg-white/5"><div className="h-3 rounded-full bg-gradient-to-r from-fuchsia-500 via-violet-500 to-emerald-400" style={{ width: `${progress}%` }} /></div><div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">{functionCards.map(([key, value]) => <div key={key} className="rounded-[20px] border border-violet-500/30 bg-[#171521] px-4 py-4"><div className="text-sm font-semibold text-violet-200">{key}</div><div className="mt-2 text-3xl font-black">{Math.round(value * 100) / 100}</div><div className="mt-2 text-xs text-violet-100/60">{FUNCTION_LABELS[key] || key}</div></div>)}</div></div>
            <div className="mb-5 rounded-[28px] bg-[#3b234b] px-6 py-6"><div className="mb-3 flex items-center gap-3 text-violet-100"><Brain className="h-5 w-5" /><span className="font-semibold">当前问题</span></div><div className="text-3xl font-black leading-tight">{assessment.latest_question || "AI 在线后，这里会出现正式下一题。"}</div><p className="mt-4 text-sm leading-7 text-violet-100/80">至少 12 轮有效回答后，只有八功能信号稳定才允许写入正式人格结果。</p></div>
            <textarea value={answerDraft} onChange={(e) => setAnswerDraft(e.target.value)} placeholder="请用自然语言真实作答。越具体，越容易让 AI 得到稳定的八功能信号。" className="min-h-[170px] w-full rounded-[26px] border border-violet-500/35 bg-[#1b1927] px-5 py-4 text-lg text-white outline-none placeholder:text-violet-100/45" />
            <div className="mt-5 flex flex-wrap gap-4">
              <button type="button" onClick={handleSubmitTurn} disabled={busy || !identityReady || !answerDraft.trim() || !assessment.can_submit_text} className="inline-flex items-center gap-3 rounded-[20px] bg-white px-6 py-4 text-lg font-semibold text-[#171521] transition disabled:cursor-not-allowed disabled:bg-white/20 disabled:text-white/40"><ChevronRight className="h-5 w-5" />提交这一轮回答</button>
              <button type="button" onClick={handleDesktopVoiceToggle} disabled={desktopVoiceBusy || !identityReady} className="inline-flex items-center gap-3 rounded-[20px] border border-amber-400/30 bg-amber-500/10 px-6 py-4 text-lg font-semibold text-amber-200 transition disabled:cursor-not-allowed disabled:opacity-40">{desktopVoiceBusy ? <LoaderCircle className="h-5 w-5 animate-spin" /> : desktopVoiceRecording ? <PauseCircle className="h-5 w-5" /> : <Mic className="h-5 w-5" />}{desktopVoiceRecording ? "停止电脑麦克风" : "电脑麦克风作答"}</button>
              <button type="button" onClick={handleRobotVoiceToggle} disabled={voiceBusy || !identityReady || !runtime.robot_voice_ready} className="inline-flex items-center gap-3 rounded-[20px] border border-cyan-400/30 bg-cyan-500/10 px-6 py-4 text-lg font-semibold text-cyan-200 transition disabled:cursor-not-allowed disabled:opacity-40">{voiceBusy ? <LoaderCircle className="h-5 w-5 animate-spin" /> : assessment.voice_session_active ? <PauseCircle className="h-5 w-5" /> : <PlayCircle className="h-5 w-5" />}{assessment.voice_session_active ? "停止机器人语音测评" : "启用机器人语音测评"}</button>
              <button type="button" onClick={handleFinishAssessment} disabled={busy || !assessment.assessment_ready} className="inline-flex items-center gap-3 rounded-[20px] border border-violet-400/30 bg-violet-500/10 px-6 py-4 text-lg font-semibold text-violet-100 transition disabled:cursor-not-allowed disabled:opacity-40"><Brain className="h-5 w-5" />写入正式人格结果</button>
            </div>
            <div className="mt-6 rounded-[24px] border border-violet-500/30 bg-[#171521] p-5"><div className="mb-3 text-sm font-semibold text-violet-200">正式结果预览</div><div className="grid gap-4 md:grid-cols-2"><div><div className="text-sm text-violet-100/65">主辅功能堆栈</div><div className="mt-2 text-xl font-black">{assessment.dominant_stack.join(" / ") || "等待 AI 结果"}</div></div><div><div className="text-sm text-violet-100/65">兼容映射类型</div><div className="mt-2 text-xl font-black">{assessment.mapped_type_code || "等待 AI 结果"}</div></div></div><p className="mt-4 text-sm leading-7 text-violet-100/75">{assessment.summary || "正式人格摘要会在 AI 真正测出稳定八功能结果后显示。"}</p></div>
          </div>

          <div className="rounded-[32px] border border-violet-500/35 bg-[#181622] p-6">
            <div className="mb-6 flex items-center gap-3"><Camera className="h-5 w-5 text-emerald-300" /><h2 className="text-2xl font-black tracking-tight">3. 结果与扫脸</h2></div>
            <div className="space-y-5">
              <div className="rounded-[24px] border border-violet-500/35 bg-[#1b1927] p-5"><div className="mb-2 text-sm font-semibold text-violet-200">正式人格结论</div><div className="mb-3 text-4xl font-black">{assessment.mapped_type_code || "待生成"}</div><p className="text-sm leading-7 text-violet-100/75">{assessment.summary || "AI 真实测完后，这里会展示八功能摘要和兼容类型说明。"}</p></div>
              <div className="rounded-[24px] border border-violet-500/35 bg-[#1b1927] p-5"><div className="mb-3 flex items-center gap-3 text-violet-100"><Mic className="h-4 w-4" /><span className="font-semibold">语音链路状态</span></div><p className="text-sm leading-7 text-violet-100/70">电脑麦克风：{desktopVoiceStatus.ready ? "可用" : "未就绪"}。机器人语音：{runtime.robot_voice_ready ? "可用" : "设备离线或未绑定"}。</p><p className="mt-3 text-sm leading-7 text-violet-100/70">{desktopVoiceStatus.primary_error || desktopVoiceStatus.fallback_error || runtime.desktop_voice_detail}</p></div>
              <button type="button" onClick={handleStartOwnerScan} disabled={busy || !psychometricCompleted || !preferredDeviceId || ownerBindingCompleted} className="inline-flex w-full items-center justify-center gap-3 rounded-[20px] bg-emerald-500/10 px-6 py-4 text-lg font-semibold text-emerald-200 transition hover:bg-emerald-500/15 disabled:cursor-not-allowed disabled:opacity-40"><ScanFace className="h-5 w-5" />启动主人扫描建档</button>
              <div className="rounded-[24px] border border-violet-500/35 bg-[#1b1927] p-5 text-sm leading-7 text-violet-100/70">{scanState || "正式人格结果写入完成后，如有设备，可继续主人脸部绑定。"}</div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

export default ActivationGate;
