import React, { useEffect, useMemo, useRef, useState } from "react";
import { Brain, CheckCircle2, LoaderCircle, Mic, PauseCircle, ShieldCheck, UserRound } from "lucide-react";

import { getActivationState } from "../services/authService";
import {
  completeActivation,
  getActivationRuntimeStatus,
  getAssessmentState,
  startAssessment,
  submitAssessmentTurn,
  type ActivationAssessmentState,
  type ActivationRuntimeStatus,
} from "../services/activationService";
import {
  createDesktopVoiceRecorder,
  getDesktopVoiceStatus,
  transcribeDesktopAudio,
  type DesktopVoiceStatus,
} from "../services/desktopVoiceService";

interface ActivationGateProps {
  onActivated: () => Promise<void> | void;
}

const emptyAssessment = (): ActivationAssessmentState => ({
  ok: true,
  exists: false,
  status: "idle",
  turn_count: 0,
  effective_turn_count: 0,
  conversation_count: 0,
  latest_question: "",
  latest_transcript: "",
  last_question_id: "",
  finish_reason: "",
  voice_mode: "idle",
  voice_session_active: false,
  device_online: false,
  summary: "",
  interaction_preferences: [],
  decision_style: "",
  stress_response: "",
  comfort_preferences: [],
  avoid_patterns: [],
  care_guidance: "",
  confidence: 0,
  inference_version: "activation-dialogue-v5",
  required_min_turns: 4,
  max_turns: 12,
  question_source: "ai_required",
  scoring_source: "pending",
  question_pair: "",
  current_focus: "",
  mode_hint: "ai_blocked",
  can_submit_text: false,
  assessment_ready: false,
  ai_required: true,
  blocking_reason: "",
  dialogue_turns: [],
});

const emptyRuntime = (): ActivationRuntimeStatus => ({
  ok: true,
  ai_ready: false,
  ai_detail: "",
  gateway_ready: false,
  provider_network_ok: false,
  blocking_reason: "",
  text_assessment_ready: false,
  desktop_voice_ready: false,
  desktop_voice_detail: "",
  device_online: false,
  robot_voice_ready: false,
  preferred_device_id: "",
});

const emptyDesktopVoice = (): DesktopVoiceStatus => ({
  ok: false,
  ready: false,
  provider_preference: "faster_whisper",
  fallback_provider: "sherpa_onnx",
  active_provider: "",
  primary_ready: false,
  primary_engine: "",
  primary_error: "",
  fallback_ready: false,
  fallback_engine: "",
  fallback_error: "",
  language: "zh",
  max_sec: 45,
  model_name: "small",
  beam_size: 5,
  best_of: 5,
  preprocess_enabled: true,
  trim_silence_enabled: true,
  initial_prompt_enabled: false,
  hotwords_enabled: false,
});

const normalizeUiError = (value: unknown) => {
  const message = value instanceof Error ? value.message : String(value || "");
  const lowered = message.toLowerCase();
  if (
    lowered.includes("signal is aborted without reason") ||
    lowered.includes("aborterror") ||
    lowered.includes("aborted")
  ) {
    return "";
  }
  return message;
};

export function ActivationGate({ onActivated }: ActivationGateProps) {
  const [booting, setBooting] = useState(true);
  const [busy, setBusy] = useState(false);
  const [startingQuestion, setStartingQuestion] = useState(false);
  const [desktopVoiceBusy, setDesktopVoiceBusy] = useState(false);
  const [desktopVoiceRecording, setDesktopVoiceRecording] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [identityReady, setIdentityReady] = useState(false);
  const [profileReady, setProfileReady] = useState(false);
  const [preferredName, setPreferredName] = useState("");
  const [introTranscript, setIntroTranscript] = useState("");
  const [answerDraft, setAnswerDraft] = useState("");
  const [runtime, setRuntime] = useState<ActivationRuntimeStatus>(emptyRuntime);
  const [desktopVoiceStatus, setDesktopVoiceStatus] = useState<DesktopVoiceStatus>(emptyDesktopVoice);
  const [assessment, setAssessment] = useState<ActivationAssessmentState>(emptyAssessment);
  const recorderRef = useRef<{ stop: () => Promise<Blob> } | null>(null);
  const questionRecoveryRef = useRef(false);
  const typingAnswer = Boolean(answerDraft.trim());

  const mergeAssessmentFromPoll = (nextState: ActivationAssessmentState) => {
    const normalized = { ...emptyAssessment(), ...nextState };
    setAssessment((current) => {
      const hasCurrentQuestion = Boolean(String(current.latest_question || "").trim());
      const nextQuestionBlank = !String(normalized.latest_question || "").trim();
      const nextTurnNotAhead = Number(normalized.turn_count || 0) <= Number(current.turn_count || 0);

      if (hasCurrentQuestion && !normalized.assessment_ready && normalized.status !== "completed") {
        const preserveQuestion =
          typingAnswer ||
          busy ||
          startingQuestion ||
          questionRecoveryRef.current ||
          (nextQuestionBlank && nextTurnNotAhead);

        if (preserveQuestion) {
          normalized.latest_question = String(current.latest_question || normalized.latest_question || "");
          normalized.last_question_id = String(current.last_question_id || normalized.last_question_id || "");
          normalized.current_focus = String(current.current_focus || normalized.current_focus || "");
          normalized.question_source = String(current.question_source || normalized.question_source || "");
        }
      }

      if ((normalized.dialogue_turns || []).length < (current.dialogue_turns || []).length) {
        normalized.dialogue_turns = current.dialogue_turns;
      }

      return normalized;
    });
  };

  const dialogue = useMemo(
    () =>
      (assessment.dialogue_turns || [])
        .filter((item) => String(item.text || "").trim())
        .map((item, index) => ({
          ...item,
          key: `${item.role}-${item.timestamp_ms || index}-${index}`,
        })),
    [assessment.dialogue_turns]
  );

  const currentQuestion = String(assessment.latest_question || "").trim();
  const canFinish = identityReady && profileReady;
  const summaryCards = [
    { label: "互动偏好", value: assessment.interaction_preferences.join("、") },
    { label: "决策方式", value: assessment.decision_style },
    { label: "压力或不安时的反应", value: assessment.stress_response },
    { label: "更容易被安抚的方式", value: assessment.comfort_preferences.join("、") },
    { label: "不建议触发的沟通方式", value: assessment.avoid_patterns.join("、") },
    { label: "长期陪伴说明", value: assessment.care_guidance },
  ].filter((item) => item.value);

  const applyState = async () => {
    const [activation, assessmentState, runtimeState, desktopVoice] = await Promise.all([
      getActivationState(),
      getAssessmentState(),
      getActivationRuntimeStatus().catch(() => emptyRuntime()),
      getDesktopVoiceStatus().catch(() => emptyDesktopVoice()),
    ]);

    setIdentityReady(!activation.activation_required);
    setProfileReady(
      Boolean(activation.psychometric_completed || assessmentState.assessment_ready || assessmentState.status === "completed")
    );
    setPreferredName((current) => current || String(activation.preferred_name || "").trim());
    setIntroTranscript((current) => current || String(activation.voice_intro_summary || "").trim());
    setRuntime(runtimeState);
    setDesktopVoiceStatus(desktopVoice);
    mergeAssessmentFromPoll(assessmentState);
  };

  const waitForFirstQuestion = async (reset: boolean) => {
    const initial = await startAssessment({ surface: "desktop", voice_mode: "text", reset });
    if (String(initial.latest_question || "").trim() || String(initial.blocking_reason || "").trim()) {
      return initial;
    }

    let latest = initial;
    for (let attempt = 0; attempt < 12; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 500));
      latest = await getAssessmentState();
      if (String(latest.latest_question || "").trim() || String(latest.blocking_reason || "").trim()) {
        return latest;
      }
    }

    latest = await startAssessment({ surface: "desktop", voice_mode: "text", reset: false });
    return latest;
  };

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        await applyState();
      } catch (err) {
        if (!active) return;
        const normalized = normalizeUiError(err);
        if (normalized) setError(normalized);
      } finally {
        if (active) setBooting(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const timer = window.setInterval(() => {
      if (cancelled) return;
      if (busy || startingQuestion || questionRecoveryRef.current) return;
      void applyState().catch((err) => {
        if (cancelled) return;
        const normalized = normalizeUiError(err);
        if (normalized) setError(normalized);
      });
    }, 1800);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [busy, startingQuestion]);

  useEffect(() => {
    if (booting || busy || startingQuestion || typingAnswer || questionRecoveryRef.current) {
      return;
    }
    if (!identityReady || !runtime.ai_ready || profileReady) {
      return;
    }
    if (String(assessment.latest_question || "").trim() || String(assessment.blocking_reason || "").trim()) {
      return;
    }
    const status = String(assessment.status || "").trim();
    if (!["idle", "active", "blocked"].includes(status)) {
      return;
    }
    questionRecoveryRef.current = true;
    void (async () => {
      try {
        const recovered = await waitForFirstQuestion(false);
        setAssessment({ ...emptyAssessment(), ...recovered });
        if (String(recovered.blocking_reason || "").trim()) {
          setError(String(recovered.blocking_reason || ""));
        }
      } catch (err) {
        const normalized = normalizeUiError(err);
        if (normalized) setError(normalized);
      } finally {
        questionRecoveryRef.current = false;
      }
    })();
  }, [
    assessment.blocking_reason,
    assessment.latest_question,
    assessment.status,
    booting,
    busy,
    identityReady,
    profileReady,
    runtime.ai_ready,
    startingQuestion,
    typingAnswer,
  ]);

  const handleConfirmIdentity = async () => {
    const name = preferredName.trim();
    const intro = introTranscript.trim();
    if (!name) {
      setError("请先确认你的名字，再开始正式建档。");
      return;
    }
    if (busy || startingQuestion) return;

    setBusy(true);
    setStartingQuestion(true);
    setError("");
    setSuccess("");
    try {
      await completeActivation({
        preferred_name: name,
        role_label: "owner",
        relation_to_robot: "primary_user",
        voice_intro_summary: intro,
        identity_summary: `${name} 是当前机器人的主要使用者，后续服务应以这个身份为准。`,
        onboarding_notes: intro,
        profile: {
          identity_source: "manual_name_intro",
          intro_transcript: intro,
        },
        activation_version: "activation-dialogue-v5",
      });
      setIdentityReady(true);
      const started = await waitForFirstQuestion(true);
      setAssessment({ ...emptyAssessment(), ...started });
      if (started.blocking_reason) {
        setError(started.blocking_reason);
      } else if (!String(started.latest_question || "").trim()) {
        setSuccess("身份已确认，正在生成第一题，请不要重复点击。");
      } else {
        setSuccess("正式建档已开始，机器人会一次只问一个问题。");
      }
      await applyState();
    } catch (err) {
      const normalized = normalizeUiError(err);
      if (normalized) setError(normalized);
    } finally {
      setStartingQuestion(false);
      setBusy(false);
    }
  };

  const handleSubmitTurn = async () => {
    const answer = answerDraft.trim();
    if (!answer) {
      setError("请先输入这一轮回答。");
      return;
    }
    if (busy || startingQuestion) return;

    setBusy(true);
    setError("");
    setSuccess("");
    try {
      let result;
      try {
        result = await submitAssessmentTurn({
          answer,
          transcript: answer,
          surface: "desktop",
          voice_mode: "text",
        });
      } catch (err) {
        const normalized = normalizeUiError(err);
        if (!normalized.includes("Assessment session not started")) {
          throw err;
        }
        const restarted = await startAssessment({ surface: "desktop", voice_mode: "text", reset: false });
        setAssessment({ ...emptyAssessment(), ...restarted });
        result = await submitAssessmentTurn({
          answer,
          transcript: answer,
          surface: "desktop",
          voice_mode: "text",
        });
      }

      setAssessment({ ...emptyAssessment(), ...result });
      setAnswerDraft("");

      if (result.blocking_reason) {
        setError(result.blocking_reason);
      } else if (result.just_completed || result.status === "completed" || result.assessment_ready) {
        setProfileReady(true);
        setSuccess("正式建档已完成，偏好与反应画像已写入本地长期记忆。");
        await applyState();
      } else {
        setSuccess("这一轮回答已记入正式建档。");
      }
    } catch (err) {
      const normalized = normalizeUiError(err);
      if (normalized) setError(normalized);
    } finally {
      setBusy(false);
    }
  };

  const handleDesktopVoiceToggle = async () => {
    if (!desktopVoiceStatus.ready && !desktopVoiceStatus.primary_ready && !desktopVoiceStatus.fallback_ready) {
      setError(desktopVoiceStatus.primary_error || desktopVoiceStatus.fallback_error || "电脑麦克风当前不可用。");
      return;
    }
    setDesktopVoiceBusy(true);
    setError("");
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
        const text = String(transcript.text || "").trim();
        if (!text) {
          setError("没有识别到有效语音内容。");
          return;
        }
        setAnswerDraft(text);
        setSuccess("转写完成，已填入回答框。");
      }
    } catch (err) {
      recorderRef.current = null;
      setDesktopVoiceRecording(false);
      const normalized = normalizeUiError(err);
      if (normalized) setError(normalized);
    } finally {
      setDesktopVoiceBusy(false);
    }
  };

  const handleFinishActivation = async () => {
    if (!canFinish || finishing) return;
    setFinishing(true);
    setError("");
    try {
      await onActivated();
    } catch (err) {
      const normalized = normalizeUiError(err);
      if (normalized) setError(normalized);
    } finally {
      setFinishing(false);
    }
  };

  if (booting) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#0a0a10] text-white">
        <div className="flex items-center gap-3 rounded-2xl border border-white/10 bg-white/5 px-6 py-4">
          <LoaderCircle className="h-5 w-5 animate-spin" />
          正在加载首次激活状态...
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen overflow-y-auto overflow-x-hidden bg-[#0a0a10] px-10 py-9 text-white">
      <div className="mx-auto flex max-w-[1240px] flex-col gap-8 pb-16">
        <section className="rounded-[36px] border border-violet-500/40 bg-[#171521] px-10 py-8">
          <div className="flex items-start justify-between gap-6">
            <div className="flex items-start gap-5">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-500/10 text-emerald-300">
                <ShieldCheck className="h-7 w-7" />
              </div>
              <div>
                <h1 className="text-[42px] font-black leading-none tracking-tight">首次激活</h1>
                <p className="mt-3 max-w-[760px] text-[18px] leading-9 text-slate-200">
                  先确认名字，再由同一条 OpenClaw / 生产 AI 链完成正式建档。系统会在判断信息已经足够稳定后停止，并把偏好与反应画像写入本地长期记忆。
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={handleFinishActivation}
              disabled={!canFinish || finishing}
              className="rounded-[28px] bg-white/20 px-7 py-5 text-[16px] font-semibold text-white transition enabled:hover:bg-white/30 disabled:cursor-not-allowed disabled:opacity-45"
            >
              {finishing ? "正在进入桌面..." : "完成激活并进入桌面"}
            </button>
          </div>
        </section>

        <section
          className={`rounded-[28px] border px-8 py-6 ${
            runtime.ai_ready
              ? "border-emerald-400/20 bg-emerald-500/10 text-emerald-100"
              : "border-amber-400/20 bg-amber-500/10 text-amber-100"
          }`}
        >
          <div className="flex flex-wrap items-center gap-3">
            <Brain className="h-6 w-6" />
            <div className="text-[20px] font-bold">
              {runtime.ai_ready ? "AI 在线，可以开始正式建档" : "AI 未就绪，正式建档已暂停"}
            </div>
            <div className="rounded-full border border-white/60 px-4 py-1 text-sm">
              Gateway: {runtime.gateway_ready ? "ready" : "offline"}
            </div>
            <div className="rounded-full border border-white/60 px-4 py-1 text-sm">
              Provider: {runtime.provider_network_ok ? "reachable" : "blocked"}
            </div>
          </div>
          <div className="mt-4 text-[16px] leading-8 text-white/90">
            {runtime.blocking_reason || runtime.ai_detail || "OpenClaw 与 provider 已就绪，可以开始正式建档。"}
          </div>
        </section>

        {error ? (
          <section className="rounded-[24px] border border-rose-400/20 bg-rose-500/10 px-8 py-5 text-[16px] text-rose-100">
            {error}
          </section>
        ) : null}

        {success ? (
          <section className="rounded-[24px] border border-cyan-400/20 bg-cyan-500/10 px-8 py-5 text-[16px] text-cyan-100">
            {success}
          </section>
        ) : null}

        <div className="grid gap-8 xl:grid-cols-[0.85fr_1.35fr_0.8fr]">
          <section className="rounded-[32px] border border-violet-500/35 bg-[#161422] p-7">
            <div className="mb-6 flex items-center gap-3 text-[18px] font-bold">
              <UserRound className="h-5 w-5 text-fuchsia-300" />
              1. 名字确认
            </div>
            <p className="mb-6 text-[16px] leading-8 text-slate-300">
              这里只做最简身份确认：你的名字，以及一句自然介绍。保存后就直接进入聊天式正式建档，不再生成草稿，也不再做人脸建档。
            </p>
            <div className="space-y-4">
              <input
                value={preferredName}
                onChange={(event) => setPreferredName(event.target.value)}
                placeholder="你的名字"
                className="w-full rounded-[22px] border border-violet-500/35 bg-[#1b1828] px-5 py-4 text-[18px] font-semibold text-white outline-none placeholder:text-slate-500"
              />
              <textarea
                value={introTranscript}
                onChange={(event) => setIntroTranscript(event.target.value)}
                rows={5}
                placeholder="一句自然介绍，例如：我叫京亮，平时需要你提醒我休息，也希望你跟我聊聊天。"
                className="w-full rounded-[26px] border border-violet-500/35 bg-[#1b1828] px-5 py-4 text-[16px] leading-8 text-white outline-none placeholder:text-slate-500"
              />
              <button
                type="button"
                onClick={handleConfirmIdentity}
                disabled={busy || startingQuestion}
                className="w-full rounded-[24px] bg-fuchsia-600 px-6 py-4 text-[18px] font-bold text-white transition enabled:hover:bg-fuchsia-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {startingQuestion ? "正在生成第一题..." : "确认名字并开始正式建档"}
              </button>
            </div>

            <div className="mt-6 rounded-[24px] border border-white/10 bg-white/5 p-5 text-[15px] leading-8 text-slate-300">
              <div className="font-semibold text-white">当前确认姓名：{preferredName.trim() || "未填写"}</div>
              <div className="mt-3">
                后续结果会直接写入 OpenClaw 本地记忆，普通聊天和主动关怀都会读取同一份画像，而不是再维护一套独立的人设切换。
              </div>
            </div>
          </section>

          <section className="rounded-[32px] border border-violet-500/35 bg-[#161422] p-7">
            <div className="mb-6 flex items-center justify-between gap-4">
              <div className="flex items-center gap-3 text-[18px] font-bold">
                <Brain className="h-5 w-5 text-violet-300" />
                2. 聊天式正式建档
              </div>
              <div className="rounded-full border border-white/15 px-4 py-2 text-sm text-slate-300">
                {assessment.question_source === "ai" ? "问题来源：AI" : "问题来源：等待 AI"}
              </div>
            </div>

            <div className="rounded-[24px] border border-cyan-400/20 bg-cyan-500/10 p-5 text-[15px] leading-8 text-cyan-50">
              <div className="font-semibold">当前建档状态</div>
              <div className="mt-2">
                机器人会像正常聊天一样一次只问一个问题。你回答完这一题，才会生成下一题；当 AI 判断画像已经足够稳定时，会自动停止并产出最终结果。
              </div>
              <div className="mt-3 flex flex-wrap gap-3 text-sm">
                <span className="rounded-full border border-white/30 px-4 py-1">当前评分：{assessment.scoring_source}</span>
                <span className="rounded-full border border-white/30 px-4 py-1">
                  当前缺口：{assessment.current_focus || "等待判断"}
                </span>
                <span className="rounded-full border border-white/30 px-4 py-1">
                  有效回答：{assessment.conversation_count}
                </span>
              </div>
            </div>

            {dialogue.length > 0 ? (
              <div className="mt-6 space-y-4">
                {dialogue.map((item) => (
                  <div
                    key={item.key}
                    className={`rounded-[24px] border px-5 py-4 ${
                      item.role === "assistant"
                        ? "border-violet-500/30 bg-violet-500/10"
                        : "border-cyan-500/30 bg-cyan-500/10"
                    }`}
                  >
                    <div className="text-sm font-semibold text-slate-300">
                      {item.role === "assistant" ? "机器人提问" : "你的回答"}
                    </div>
                    <div className="mt-2 text-[18px] leading-9 text-white">{item.text}</div>
                  </div>
                ))}
              </div>
            ) : startingQuestion ? (
              <div className="mt-6 rounded-[24px] border border-cyan-400/20 bg-cyan-500/10 p-6 text-[16px] leading-8 text-cyan-100">
                正在生成第一题，请不要重复点击。当前仍在等待 OpenClaw / GLM 返回首个正式建档问题。
              </div>
            ) : (
              <div className="mt-6 rounded-[24px] border border-white/10 bg-white/5 p-6 text-[16px] leading-8 text-slate-400">
                确认名字后，这里会显示机器人正式建档的第一条问题。
              </div>
            )}

            {currentQuestion ? (
              <div className="mt-6 rounded-[26px] border border-fuchsia-500/30 bg-fuchsia-500/10 p-6">
                <div className="text-sm font-semibold text-slate-300">当前问题</div>
                <div className="mt-3 text-[24px] font-bold leading-10 text-white">{currentQuestion}</div>
              </div>
            ) : null}

            <div className="mt-6 rounded-[26px] border border-white/10 bg-white/5 p-5">
              <textarea
                value={answerDraft}
                onChange={(event) => setAnswerDraft(event.target.value)}
                rows={4}
                placeholder={
                  startingQuestion
                    ? "第一题正在生成中，请稍候..."
                    : "直接像聊天一样回答这一题，越贴近日常反应越好。"
                }
                disabled={!runtime.ai_ready || busy || startingQuestion}
                className="w-full resize-none bg-transparent text-[18px] leading-8 text-white outline-none placeholder:text-slate-500 disabled:cursor-not-allowed disabled:opacity-60"
              />
            </div>

            <div className="mt-5 flex flex-wrap gap-4">
              <button
                type="button"
                onClick={handleSubmitTurn}
                disabled={!runtime.ai_ready || busy || startingQuestion || !answerDraft.trim()}
                className="rounded-[22px] bg-white px-6 py-4 text-[18px] font-bold text-slate-950 transition enabled:hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-50"
              >
                提交这一轮回答
              </button>
              <button
                type="button"
                onClick={handleDesktopVoiceToggle}
                disabled={desktopVoiceBusy || startingQuestion}
                className="rounded-[22px] border border-cyan-400/35 bg-cyan-500/10 px-6 py-4 text-[17px] font-semibold text-cyan-100 transition enabled:hover:bg-cyan-500/15 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {desktopVoiceRecording ? (
                  <span className="inline-flex items-center gap-2">
                    <PauseCircle className="h-5 w-5" />
                    停止电脑麦克风录音
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-2">
                    <Mic className="h-5 w-5" />
                    用电脑麦克风回答
                  </span>
                )}
              </button>
            </div>
          </section>

          <section className="rounded-[32px] border border-violet-500/35 bg-[#161422] p-7">
            <div className="mb-6 flex items-center gap-3 text-[18px] font-bold">
              <CheckCircle2 className="h-5 w-5 text-emerald-300" />
              3. 结果与记忆
            </div>

            <div className="rounded-[24px] border border-white/10 bg-white/5 p-6">
              <div className="text-sm font-semibold text-slate-300">正式建档结论</div>
              <div className="mt-3 text-[36px] font-black leading-none text-white">{profileReady ? "已生成" : "待生成"}</div>
              <div className="mt-4 text-[16px] leading-8 text-slate-300">
                {assessment.summary || "AI 判断稳定后，这里会显示这个人的偏好、反应方式以及更合适的陪伴策略。"}
              </div>
            </div>

            <div className="mt-6 rounded-[24px] border border-white/10 bg-white/5 p-6">
              <div className="text-sm font-semibold text-slate-300">语音链路状态</div>
              <div className="mt-4 space-y-2 text-[15px] leading-8 text-slate-300">
                <div>电脑麦克风：{desktopVoiceStatus.ready || desktopVoiceStatus.primary_ready || desktopVoiceStatus.fallback_ready ? "可用" : "未就绪"}</div>
                <div>机器人语音：{runtime.robot_voice_ready ? "设备在线" : "设备离线或未绑定"}</div>
                <div className="text-slate-400">
                  {desktopVoiceStatus.primary_error || desktopVoiceStatus.fallback_error || runtime.desktop_voice_detail}
                </div>
              </div>
            </div>

            <div className="mt-6 space-y-4">
              {summaryCards.length > 0 ? (
                summaryCards.map((item) => (
                  <div key={item.label} className="rounded-[24px] border border-white/10 bg-white/5 p-5">
                    <div className="text-sm font-semibold text-slate-300">{item.label}</div>
                    <div className="mt-2 text-[16px] leading-8 text-white">{item.value}</div>
                  </div>
                ))
              ) : (
                <div className="rounded-[24px] border border-white/10 bg-white/5 p-5 text-[16px] leading-8 text-slate-400">
                  这里会显示 AI 压缩后的长期陪伴画像，而不是八功能分数表。
                </div>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
