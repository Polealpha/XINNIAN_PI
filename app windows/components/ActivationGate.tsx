import React, { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, Brain, CheckCircle2, LoaderCircle, Mic, PauseCircle, ShieldCheck, UserRound } from "lucide-react";

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

interface PendingAssessmentTurn {
  clientTurnId: string;
  questionId: string;
  question: string;
  answer: string;
  submittedAtMs: number;
}

interface StoredAssessmentDraft {
  questionId: string;
  draft: string;
}

type ActivationStep = 1 | 2 | 3;

const ASSESSMENT_DRAFT_STORAGE_KEY = "activation-assessment-draft-v3";
const ASSESSMENT_PENDING_STORAGE_KEY = "activation-assessment-pending-v3";

const createClientTurnId = () => `desktop-turn-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

const readLocalJson = <T,>(key: string): T | null => {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
};

const writeLocalJson = (key: string, value: unknown) => {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // ignore desktop storage failures
  }
};

const removeLocalJson = (key: string) => {
  try {
    window.localStorage.removeItem(key);
  } catch {
    // ignore desktop storage failures
  }
};

const normalizeAnswerText = (value: string) => String(value || "").trim().replace(/\s+/g, " ");

const answerRecordedInState = (state: ActivationAssessmentState, answer: string) => {
  const normalizedAnswer = normalizeAnswerText(answer);
  if (!normalizedAnswer) return false;
  if (normalizeAnswerText(String(state.latest_transcript || "")) === normalizedAnswer) {
    return true;
  }
  return (state.dialogue_turns || []).some(
    (item) => item.role === "user" && normalizeAnswerText(String(item.text || "")) === normalizedAnswer
  );
};

const assessmentAdvancedPastPending = (state: ActivationAssessmentState, pending: PendingAssessmentTurn) => {
  const nextQuestionId = String(state.last_question_id || "").trim();
  if (nextQuestionId && pending.questionId && nextQuestionId !== pending.questionId) {
    return true;
  }
  return Boolean(state.updated_at_ms && Number(state.updated_at_ms) > Number(pending.submittedAtMs));
};

const suggestedAnswersForQuestion = (focus: string, question: string): string[] => {
  const focusKey = String(focus || "").trim();
  const prompt = String(question || "").trim();
  const lowered = prompt.toLowerCase();
  const byFocus: Record<string, string[]> = {
    interaction_preferences: ["先轻一点问我怎么了", "先陪我聊两句，不要连续追问", "先给我一点空间，等我愿意再说"],
    comfort_preferences: ["先安静陪着我就好", "先共情，再给一点建议", "先让我把情绪说出来"],
    decision_style: ["我一般会很快拍板", "我会先想一会儿再决定", "小事快，大事会纠结"],
    stress_response: ["我更容易先自己扛着", "我会想找人说一说", "一开始会沉默，过会儿才愿意聊"],
    avoid_patterns: ["别催我，也别逼我马上表态", "不要说教或者灌鸡汤", "别一下子追问太多细节"],
  };
  if (byFocus[focusKey]) {
    return byFocus[focusKey];
  }
  if (lowered.includes("怎么开口") || prompt.includes("怎么开口")) {
    return ["先轻一点问我还好吗", "先别追问细节，给我一点空间", "先说你在，我想说时再说"];
  }
  if (lowered.includes("更希望") || prompt.includes("更希望")) {
    return ["我更偏第一种", "我更偏第二种", "要看我当时状态"];
  }
  return ["更偏第一种", "更偏第二种", "得看具体情况"];
};

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
  const [pendingTurn, setPendingTurn] = useState<PendingAssessmentTurn | null>(null);
  const [lastSubmitDurationMs, setLastSubmitDurationMs] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [identityReady, setIdentityReady] = useState(false);
  const [profileReady, setProfileReady] = useState(false);
  const [activeStep, setActiveStep] = useState<ActivationStep>(1);
  const [preferredName, setPreferredName] = useState("");
  const [introTranscript, setIntroTranscript] = useState("");
  const [answerDraft, setAnswerDraft] = useState("");
  const [runtime, setRuntime] = useState<ActivationRuntimeStatus>(emptyRuntime);
  const [desktopVoiceStatus, setDesktopVoiceStatus] = useState<DesktopVoiceStatus>(emptyDesktopVoice);
  const [assessment, setAssessment] = useState<ActivationAssessmentState>(emptyAssessment);
  const recorderRef = useRef<{ stop: () => Promise<Blob> } | null>(null);
  const questionRecoveryRef = useRef(false);
  const hydratedDraftRef = useRef(false);
  const hydratedQuestionIdRef = useRef("");
  const previousQuestionIdRef = useRef("");
  const initializedStepRef = useRef(false);
  const mergeAssessmentFromPoll = (nextState: ActivationAssessmentState) => {
    const normalized = { ...emptyAssessment(), ...nextState };
    setAssessment((current) => {
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
  const currentQuestionId = String(assessment.last_question_id || "").trim();
  const canFinish = identityReady && profileReady;
  const canSubmitTurn = Boolean(runtime.ai_ready && !busy && !startingQuestion && !pendingTurn && answerDraft.trim() && currentQuestion);
  const quickOptions = useMemo(
    () => (pendingTurn ? [] : suggestedAnswersForQuestion(assessment.current_focus, currentQuestion)),
    [assessment.current_focus, currentQuestion, pendingTurn]
  );
  const summaryCards = [
    { label: "互动偏好", value: assessment.interaction_preferences.join("、") },
    { label: "决策方式", value: assessment.decision_style },
    { label: "压力或不安时的反应", value: assessment.stress_response },
    { label: "更容易被安抚的方式", value: assessment.comfort_preferences.join("、") },
    { label: "不建议触发的沟通方式", value: assessment.avoid_patterns.join("、") },
    { label: "长期陪伴说明", value: assessment.care_guidance },
  ].filter((item) => item.value);
  const canGoBack = activeStep > 1 && !busy && !startingQuestion && !finishing;
  const stepTitle =
    activeStep === 1 ? "1. 名字确认" : activeStep === 2 ? "2. 聊天式正式建档" : "3. 结果与记忆";
  const stepDescription =
    activeStep === 1
      ? "先确认名字和一句自然介绍。完成后再进入正式建档。"
      : activeStep === 2
        ? "当前页面只处理正式建档，一次一题。回答完再继续下一题。"
        : "这里集中看建档结果、记忆写入情况，以及是否可以进入桌面。";

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
    if (!initializedStepRef.current) {
      const nextStep: ActivationStep = activation.activation_required
        ? 1
        : activation.psychometric_completed || assessmentState.assessment_ready || assessmentState.status === "completed"
          ? 3
          : 2;
      setActiveStep(nextStep);
      initializedStepRef.current = true;
    }
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
    const storedPending = readLocalJson<PendingAssessmentTurn>(ASSESSMENT_PENDING_STORAGE_KEY);
    if (storedPending) {
      setPendingTurn(storedPending);
    }
  }, []);

  useEffect(() => {
    if (pendingTurn) {
      writeLocalJson(ASSESSMENT_PENDING_STORAGE_KEY, pendingTurn);
    } else {
      removeLocalJson(ASSESSMENT_PENDING_STORAGE_KEY);
    }
  }, [pendingTurn]);

  useEffect(() => {
    const previousQuestionId = previousQuestionIdRef.current;
    if (currentQuestionId && previousQuestionId && currentQuestionId !== previousQuestionId && !pendingTurn) {
      setAnswerDraft("");
      removeLocalJson(ASSESSMENT_DRAFT_STORAGE_KEY);
    }
    if (hydratedQuestionIdRef.current !== currentQuestionId) {
      hydratedDraftRef.current = false;
      hydratedQuestionIdRef.current = currentQuestionId;
    }
    previousQuestionIdRef.current = currentQuestionId;
    if (!currentQuestionId) {
      hydratedDraftRef.current = false;
      removeLocalJson(ASSESSMENT_DRAFT_STORAGE_KEY);
      return;
    }
    if (!hydratedDraftRef.current) {
      const storedDraft = readLocalJson<StoredAssessmentDraft>(ASSESSMENT_DRAFT_STORAGE_KEY);
      if (storedDraft && storedDraft.questionId === currentQuestionId && String(storedDraft.draft || "").trim()) {
        setAnswerDraft((current) => current || String(storedDraft.draft || ""));
      }
      hydratedDraftRef.current = true;
    }
    if (!pendingTurn && !answerDraft.trim()) {
      const storedDraft = readLocalJson<StoredAssessmentDraft>(ASSESSMENT_DRAFT_STORAGE_KEY);
      if (storedDraft && storedDraft.questionId !== currentQuestionId) {
        removeLocalJson(ASSESSMENT_DRAFT_STORAGE_KEY);
      }
    }
  }, [answerDraft, currentQuestionId, pendingTurn]);

  useEffect(() => {
    if (!currentQuestionId || pendingTurn) {
      return;
    }
    const cleanDraft = String(answerDraft || "").trim();
    if (!cleanDraft) {
      removeLocalJson(ASSESSMENT_DRAFT_STORAGE_KEY);
      return;
    }
    writeLocalJson(ASSESSMENT_DRAFT_STORAGE_KEY, {
      questionId: currentQuestionId,
      draft: cleanDraft,
    });
  }, [answerDraft, currentQuestionId, pendingTurn]);

  useEffect(() => {
    if (!pendingTurn) return;
    if (!answerRecordedInState(assessment, pendingTurn.answer) && !assessmentAdvancedPastPending(assessment, pendingTurn)) return;
    setPendingTurn(null);
    setBusy(false);
    removeLocalJson(ASSESSMENT_PENDING_STORAGE_KEY);
    removeLocalJson(ASSESSMENT_DRAFT_STORAGE_KEY);
    if (String(assessment.latest_question || "").trim()) {
      setSuccess("这一轮回答已经提交成功，已切到下一题。");
    }
  }, [assessment, pendingTurn]);

  useEffect(() => {
    if (!pendingTurn) return;
    const timer = window.setTimeout(() => {
      void applyState().catch(() => {});
    }, 4000);
    return () => window.clearTimeout(timer);
  }, [pendingTurn]);

  useEffect(() => {
    if (!pendingTurn) return;
    const ageMs = Date.now() - Number(pendingTurn.submittedAtMs || 0);
    if (ageMs < 18000) return;
    setPendingTurn(null);
    setBusy(false);
    setAnswerDraft((current) => current || pendingTurn.answer);
    removeLocalJson(ASSESSMENT_PENDING_STORAGE_KEY);
    writeLocalJson(ASSESSMENT_DRAFT_STORAGE_KEY, {
      questionId: pendingTurn.questionId || currentQuestionId,
      draft: pendingTurn.answer,
    });
    setError("这一轮回答同步超时，已恢复到输入框，你可以直接重试，不用重新输入。");
  }, [currentQuestionId, pendingTurn]);

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
    if (booting || busy || startingQuestion || questionRecoveryRef.current) {
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
      setActiveStep(2);
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
    if (!currentQuestion) {
      setError("请先等当前问题加载出来，再提交回答。");
      return;
    }
    if (busy || startingQuestion || pendingTurn) return;

    const clientTurnId = createClientTurnId();
    const submittedAtMs = Date.now();
    const pendingPayload: PendingAssessmentTurn = {
      clientTurnId,
      questionId: currentQuestionId || clientTurnId,
      question: currentQuestion,
      answer,
      submittedAtMs,
    };

    setBusy(true);
    setError("");
    setSuccess("");
    setPendingTurn(pendingPayload);
    setAnswerDraft("");
    removeLocalJson(ASSESSMENT_DRAFT_STORAGE_KEY);
    try {
      let result;
      const submitCurrentTurn = () =>
        submitAssessmentTurn({
          answer,
          transcript: answer,
          surface: "desktop",
          voice_mode: "text",
          client_turn_id: clientTurnId,
        });
      const startedAt = performance.now();
      try {
        result = await submitCurrentTurn();
      } catch (err) {
        const normalized = normalizeUiError(err);
        if (!normalized.includes("Assessment session not started")) {
          throw err;
        }
        const restarted = await startAssessment({ surface: "desktop", voice_mode: "text", reset: false });
        setAssessment({ ...emptyAssessment(), ...restarted });
        result = await submitCurrentTurn();
      }

      const elapsedMs = Math.max(0, performance.now() - startedAt);
      setLastSubmitDurationMs(elapsedMs);
      setAssessment({ ...emptyAssessment(), ...result });
      setPendingTurn(null);
      removeLocalJson(ASSESSMENT_PENDING_STORAGE_KEY);
      if (result.question_changed && String(result.latest_question || "").trim()) {
        removeLocalJson(ASSESSMENT_DRAFT_STORAGE_KEY);
      }

      if (result.blocking_reason) {
        setError(result.blocking_reason);
      } else if (result.just_completed || result.status === "completed" || result.assessment_ready) {
        setProfileReady(true);
        setActiveStep(3);
        setSuccess("正式建档已完成，偏好与反应画像已写入本地长期记忆。");
        await applyState();
      } else if (result.question_changed && String(result.latest_question || "").trim()) {
        setSuccess(
          `这一轮回答已记入正式建档。${elapsedMs >= 1000 ? ` 本轮耗时 ${(elapsedMs / 1000).toFixed(1)} 秒。` : ""}`
        );
      } else if (answerRecordedInState(result, answer)) {
        setSuccess(`这一轮回答已记入正式建档。${elapsedMs >= 1000 ? ` 本轮耗时 ${(elapsedMs / 1000).toFixed(1)} 秒。` : ""}`);
      } else {
        setSuccess("这一轮回答已经提交成功，记录正在刷新。");
        void applyState().catch(() => {});
      }
    } catch (err) {
      setPendingTurn(null);
      setAnswerDraft((current) => current || answer);
      const normalized = normalizeUiError(err);
      if (normalized) setError(normalized);
    } finally {
      setBusy(false);
    }
  };

  const handlePickQuickOption = (option: string) => {
    const clean = String(option || "").trim();
    if (!clean || busy || startingQuestion || pendingTurn) return;
    setAnswerDraft((current) => {
      const existing = String(current || "").trim();
      if (!existing) return clean;
      if (existing.includes(clean)) return existing;
      return `${existing}；${clean}`;
    });
  };

  const handleRestorePendingAnswer = () => {
    if (!pendingTurn) return;
    setPendingTurn(null);
    setBusy(false);
    setAnswerDraft((current) => current || pendingTurn.answer);
    removeLocalJson(ASSESSMENT_PENDING_STORAGE_KEY);
    writeLocalJson(ASSESSMENT_DRAFT_STORAGE_KEY, {
      questionId: pendingTurn.questionId || currentQuestionId,
      draft: pendingTurn.answer,
    });
    setError("已把这条回答恢复到输入框，你可以直接重试。");
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
        const text = String(transcript.transcript || "").trim();
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

  const handleStepBack = () => {
    if (!canGoBack) return;
    setError("");
    setSuccess("");
    setActiveStep((current) => (current === 3 ? 2 : 1));
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
        <section className="rounded-[36px] bg-[linear-gradient(180deg,rgba(27,24,39,0.98),rgba(20,18,30,0.96))] px-10 py-8 shadow-[0_22px_72px_rgba(5,5,12,0.28),inset_0_0_0_1px_rgba(167,139,250,0.12),inset_0_1px_0_rgba(255,255,255,0.03)]">
          <div className="flex items-start justify-between gap-6">
            <div className="flex items-start gap-5">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-500/10 text-emerald-300">
                <ShieldCheck className="h-7 w-7" />
              </div>
              <div>
                <h1 className="text-[42px] font-black leading-none tracking-tight">首次激活</h1>
                <div className="mt-3 text-[18px] font-semibold text-white">{stepTitle}</div>
                <p className="mt-2 max-w-[760px] text-[18px] leading-9 text-slate-200">{stepDescription}</p>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              {canGoBack ? (
                <button
                  type="button"
                  onClick={handleStepBack}
                  className="inline-flex rounded-[22px] border border-white/15 bg-white/5 px-5 py-3 text-[15px] font-semibold text-white transition hover:bg-white/10"
                >
                  <span className="inline-flex items-center gap-2">
                    <ArrowLeft className="h-4 w-4" />
                    返回上一步
                  </span>
                </button>
              ) : null}
              {activeStep === 3 ? (
                <button
                  type="button"
                  onClick={handleFinishActivation}
                  disabled={!canFinish || finishing}
                  className="rounded-[28px] bg-white/20 px-7 py-5 text-[16px] font-semibold text-white transition enabled:hover:bg-white/30 disabled:cursor-not-allowed disabled:opacity-45"
                >
                  {finishing ? "正在进入桌面..." : "完成激活并进入桌面"}
                </button>
              ) : null}
            </div>
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

        {activeStep === 1 ? (
          <section className="mx-auto w-full max-w-[760px] rounded-[32px] bg-[linear-gradient(180deg,rgba(24,21,35,0.98),rgba(18,16,28,0.96))] p-7 shadow-[0_18px_56px_rgba(5,5,12,0.24),inset_0_0_0_1px_rgba(167,139,250,0.1),inset_0_1px_0_rgba(255,255,255,0.025)]">
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
                className="w-full rounded-[22px] border border-white/6 bg-[#1b1828] px-5 py-4 text-[18px] font-semibold text-white outline-none placeholder:text-slate-500 ring-1 ring-inset ring-violet-400/6"
              />
              <textarea
                value={introTranscript}
                onChange={(event) => setIntroTranscript(event.target.value)}
                rows={5}
                placeholder="一句自然介绍，例如：我叫京亮，平时需要你提醒我休息，也希望你跟我聊聊天。"
                className="w-full rounded-[26px] border border-white/6 bg-[#1b1828] px-5 py-4 text-[16px] leading-8 text-white outline-none placeholder:text-slate-500 ring-1 ring-inset ring-violet-400/6"
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

            <div className="mt-6 rounded-[24px] border border-white/6 bg-white/[0.035] p-5 text-[15px] leading-8 text-slate-300 shadow-[inset_0_1px_0_rgba(255,255,255,0.025)]">
              <div className="font-semibold text-white">当前确认姓名：{preferredName.trim() || "未填写"}</div>
              <div className="mt-3">
                后续结果会直接写入 OpenClaw 本地记忆，普通聊天和主动关怀都会读取同一份画像，而不是再维护一套独立的人设切换。
              </div>
            </div>
          </section>
        ) : null}

        {activeStep === 2 ? (
          <section className="mx-auto w-full max-w-[1320px] rounded-[32px] bg-[linear-gradient(180deg,rgba(24,21,35,0.98),rgba(18,16,28,0.96))] p-7 shadow-[0_20px_64px_rgba(5,5,12,0.26),inset_0_0_0_1px_rgba(167,139,250,0.1),inset_0_1px_0_rgba(255,255,255,0.025)] xl:p-9">
            <div className="mb-6 flex items-center justify-between gap-4">
              <div className="flex items-center gap-3 text-[18px] font-bold">
                <Brain className="h-5 w-5 text-violet-300" />
                2. 聊天式正式建档
              </div>
              <div className="rounded-full border border-white/15 px-4 py-2 text-sm text-slate-300">
                {assessment.question_source === "ai"
                  ? "问题来源：AI"
                  : assessment.question_source === "fallback"
                    ? "问题来源：本地兜底"
                    : "问题来源：等待 AI"}
              </div>
            </div>

            <div className="rounded-[24px] border border-cyan-400/20 bg-cyan-500/10 p-5 text-cyan-50">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="font-semibold">当前建档状态</div>
                <div className="text-sm text-cyan-100/80">一问一答，慢一点也不用重复提交</div>
              </div>
              <div className="mt-3 text-[15px] leading-7 text-cyan-50/90">
                先看当前题，按你平时最自然的反应回答就行。提交后系统会继续分析，再决定下一题。
              </div>
              <div className="mt-4 flex flex-wrap gap-3 text-sm">
                <span className="rounded-full border border-white/30 px-4 py-1">当前评分：{assessment.scoring_source}</span>
                <span className="rounded-full border border-white/30 px-4 py-1">
                  当前缺口：{assessment.current_focus || "等待判断"}
                </span>
                <span className="rounded-full border border-white/30 px-4 py-1">
                  有效回答：{assessment.conversation_count}
                </span>
                {lastSubmitDurationMs ? (
                  <span className="rounded-full border border-white/30 px-4 py-1">
                    上一轮耗时：{(lastSubmitDurationMs / 1000).toFixed(1)}s
                  </span>
                ) : null}
              </div>
            </div>

            {startingQuestion && !currentQuestion ? (
              <div className="mt-6 rounded-[24px] border border-cyan-400/20 bg-cyan-500/10 p-6 text-[16px] leading-8 text-cyan-100">
                正在生成第一题，请不要重复点击。当前仍在等待 OpenClaw / GLM 返回首个正式建档问题。
              </div>
            ) : !currentQuestion ? (
              <div className="mt-6 rounded-[24px] border border-white/6 bg-white/[0.035] p-6 text-[16px] leading-8 text-slate-400 shadow-[inset_0_1px_0_rgba(255,255,255,0.025)]">
                确认名字后，这里会显示机器人正式建档的第一条问题。
              </div>
            ) : null}

            {currentQuestion ? (
              <div className="mt-6 rounded-[28px] border border-fuchsia-500/30 bg-[linear-gradient(180deg,rgba(168,85,247,0.14),rgba(91,33,182,0.08))] p-6 shadow-[0_18px_60px_rgba(76,29,149,0.18)]">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <div className="text-sm font-semibold text-fuchsia-100/80">当前问题</div>
                    <div className="mt-2 max-w-[760px] text-[28px] font-black leading-[1.5] text-white">{currentQuestion}</div>
                  </div>
                  <div className="rounded-2xl border border-white/6 bg-black/15 px-4 py-3 text-sm leading-7 text-slate-300 shadow-[inset_0_1px_0_rgba(255,255,255,0.025)]">
                    一次只答这一题
                    <br />
                    不用补很多背景
                  </div>
                </div>
                {quickOptions.length > 0 ? (
                  <div className="mt-6 border-t border-white/10 pt-5">
                    <div className="text-xs font-semibold uppercase tracking-[0.16em] text-fuchsia-100/60">可以先点一个，再按你的话改</div>
                    <div className="mt-3 flex flex-wrap gap-3">
                      {quickOptions.map((option) => (
                        <button
                          key={option}
                          type="button"
                          onClick={() => handlePickQuickOption(option)}
                          disabled={busy || startingQuestion || Boolean(pendingTurn)}
                          className="rounded-full border border-white/15 bg-white/8 px-4 py-2 text-sm text-slate-100 transition hover:border-fuchsia-300/40 hover:bg-fuchsia-400/12 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {option}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            ) : null}

            <div className="mt-6 rounded-[28px] border border-white/6 bg-[linear-gradient(180deg,rgba(18,16,26,0.98),rgba(15,14,22,0.98))] p-6 shadow-[0_14px_40px_rgba(4,4,10,0.2)] ring-1 ring-inset ring-white/4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="text-[18px] font-bold text-white">你的回答</div>
                <div className="text-sm text-slate-400">像平时聊天一样说就行，短一点也可以</div>
              </div>
              <div className="mt-4 rounded-[24px] border border-white/8 bg-white/[0.03] p-4">
                <textarea
                  value={answerDraft}
                  onChange={(event) => setAnswerDraft(event.target.value)}
                  rows={4}
                  placeholder={
                    startingQuestion
                      ? "第一题正在生成中，请稍候..."
                      : "直接像聊天一样回答这一题，越贴近日常反应越好。"
                  }
                  disabled={!runtime.ai_ready || busy || startingQuestion || Boolean(pendingTurn)}
                  className="w-full resize-none bg-transparent text-[18px] leading-8 text-white outline-none placeholder:text-slate-500 disabled:cursor-not-allowed disabled:opacity-60"
                />
              </div>

              {pendingTurn ? (
                <div className="mt-4 rounded-[22px] border border-cyan-300/14 bg-cyan-500/10 px-5 py-4 text-[15px] leading-8 text-cyan-50 shadow-[inset_0_1px_0_rgba(255,255,255,0.025)]">
                  <div className="font-semibold">已发送的回答</div>
                  <div className="mt-1">{pendingTurn.answer}</div>
                  <button
                    type="button"
                    onClick={handleRestorePendingAnswer}
                    className="mt-3 rounded-full border border-white/20 px-4 py-1.5 text-sm text-white transition hover:bg-white/10"
                  >
                    恢复这条回答
                  </button>
                </div>
              ) : null}

              <div className="mt-5 flex flex-wrap gap-4">
                <button
                  type="button"
                  onClick={handleSubmitTurn}
                  disabled={!canSubmitTurn}
                  className="rounded-[22px] bg-white px-6 py-4 text-[18px] font-bold text-slate-950 transition enabled:hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {pendingTurn ? "正在同步这一轮回答..." : busy ? "正在提交..." : "提交这一轮回答"}
                </button>
                <button
                  type="button"
                  onClick={handleDesktopVoiceToggle}
                  disabled={desktopVoiceBusy || startingQuestion || Boolean(pendingTurn)}
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
            </div>

            {dialogue.length > 0 ? (
              <details className="mt-6 overflow-hidden rounded-[24px] border border-white/6 bg-white/[0.028] shadow-[0_10px_28px_rgba(4,4,10,0.13)]">
                <summary className="cursor-pointer list-none px-5 py-4 text-[15px] font-semibold text-slate-200">
                  <div className="flex items-center justify-between gap-4">
                    <span>之前的问答记录</span>
                    <span className="text-sm font-normal text-slate-400">{dialogue.length} 条</span>
                  </div>
                </summary>
                <div className="border-t border-white/8 px-5 py-5">
                  <div className="max-h-[420px] space-y-4 overflow-y-auto pr-2">
                    {dialogue.map((item) => (
                      <div
                        key={item.key}
                        className={`max-w-[88%] rounded-[22px] border px-5 py-4 ${
                          item.role === "assistant"
                            ? "mr-auto border-violet-500/25 bg-violet-500/10"
                            : "ml-auto border-cyan-500/25 bg-cyan-500/10"
                        }`}
                      >
                        <div className="text-sm font-semibold text-slate-300">
                          {item.role === "assistant" ? "机器人提问" : "你的回答"}
                        </div>
                        <div className="mt-2 text-[17px] leading-8 text-white">{item.text}</div>
                      </div>
                    ))}
                  </div>
                </div>
              </details>
            ) : null}
          </section>
        ) : null}

        {activeStep === 3 ? (
          <section className="mx-auto w-full max-w-[1320px] rounded-[32px] bg-[linear-gradient(180deg,rgba(24,21,35,0.98),rgba(18,16,28,0.96))] p-7 shadow-[0_20px_64px_rgba(5,5,12,0.26),inset_0_0_0_1px_rgba(167,139,250,0.1),inset_0_1px_0_rgba(255,255,255,0.025)] xl:p-9">
            <div className="mb-6 flex items-center gap-3 text-[18px] font-bold">
              <CheckCircle2 className="h-5 w-5 text-emerald-300" />
              3. 结果与记忆
            </div>

            <div className="rounded-[24px] border border-white/6 bg-white/[0.035] p-6 shadow-[inset_0_1px_0_rgba(255,255,255,0.025)]">
              <div className="text-sm font-semibold text-slate-300">正式建档结论</div>
              <div className="mt-3 text-[36px] font-black leading-none text-white">{profileReady ? "已生成" : "待生成"}</div>
              <div className="mt-4 text-[16px] leading-8 text-slate-300">
                {assessment.summary || "AI 判断稳定后，这里会显示这个人的偏好、反应方式以及更合适的陪伴策略。"}
              </div>
            </div>

            <div className="mt-6 rounded-[24px] border border-white/6 bg-white/[0.035] p-6 shadow-[inset_0_1px_0_rgba(255,255,255,0.025)]">
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
                  <div key={item.label} className="rounded-[24px] border border-white/6 bg-white/[0.035] p-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.025)]">
                    <div className="text-sm font-semibold text-slate-300">{item.label}</div>
                    <div className="mt-2 text-[16px] leading-8 text-white">{item.value}</div>
                  </div>
                ))
              ) : (
                <div className="rounded-[24px] border border-white/6 bg-white/[0.035] p-5 text-[16px] leading-8 text-slate-400 shadow-[inset_0_1px_0_rgba(255,255,255,0.025)]">
                  这里会显示 AI 压缩后的长期陪伴画像，而不是八功能分数表。
                </div>
              )}
            </div>
          </section>
        ) : null}
      </div>
    </div>
  );
}
