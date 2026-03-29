import React, { useEffect, useMemo, useState } from "react";
import { BookHeart, Brain, RefreshCw, Sparkles, UserRound } from "lucide-react";

import { getActivationState, type ActivationStateResult } from "../services/authService";
import { getAssessmentState, type ActivationAssessmentState } from "../services/activationService";

const emptyActivation = (): ActivationStateResult => ({
  ok: true,
  is_configured: false,
  activation_required: true,
  assessment_required: true,
  psychometric_completed: false,
  owner_binding_required: false,
  owner_binding_completed: false,
  preferred_device_id: null,
  preferred_name: "",
  role_label: "",
  relation_to_robot: "",
  pronouns: "",
  identity_summary: "",
  onboarding_notes: "",
  voice_intro_summary: "",
  activation_version: "v1",
  completed_at_ms: null,
});

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
  mode_hint: "",
  can_submit_text: false,
  assessment_ready: false,
  ai_required: true,
  blocking_reason: "",
  dialogue_turns: [],
});

const formatDateTime = (value?: number | null) => {
  if (!value) return "尚未完成";
  try {
    return new Date(value).toLocaleString("zh-CN", { hour12: false });
  } catch {
    return "尚未完成";
  }
};

export function CompanionProfilePanel() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [activation, setActivation] = useState<ActivationStateResult>(emptyActivation);
  const [assessment, setAssessment] = useState<ActivationAssessmentState>(emptyAssessment);

  const refresh = async (silent = false) => {
    if (!silent) setRefreshing(true);
    setError("");
    try {
      const [activationState, assessmentState] = await Promise.all([
        getActivationState(),
        getAssessmentState(),
      ]);
      setActivation(activationState);
      setAssessment({ ...emptyAssessment(), ...assessmentState });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
      if (!silent) setRefreshing(false);
    }
  };

  useEffect(() => {
    void refresh(true);
    const timer = window.setInterval(() => void refresh(true), 15000);
    return () => window.clearInterval(timer);
  }, []);

  const cards = useMemo(
    () =>
      [
        { label: "互动偏好", value: assessment.interaction_preferences.join("、") },
        { label: "决策方式", value: assessment.decision_style },
        { label: "压力或不安时的反应", value: assessment.stress_response },
        { label: "更适合被安抚或提醒的方式", value: assessment.comfort_preferences.join("、") },
        { label: "不建议触发的沟通方式", value: assessment.avoid_patterns.join("、") },
        { label: "长期陪伴指引", value: assessment.care_guidance },
      ].filter((item) => item.value),
    [assessment]
  );

  return (
    <div className="h-full w-full overflow-y-auto pr-1 no-scrollbar">
      <div className="w-full max-w-6xl mx-auto animate-pop-in pb-6">
        <div className="bg-[#0c1222]/50 backdrop-blur-3xl rounded-[2.5rem] border border-white/[0.05] shadow-2xl p-8">
          <div className="flex items-start justify-between gap-6">
            <div>
              <h3 className="text-2xl font-black text-white">陪伴画像与长期记忆</h3>
              <p className="mt-2 text-[12px] font-semibold text-slate-400">
                这里显示首次激活后沉淀下来的名字、偏好、反应画像和陪伴指引。它会直接进入 OpenClaw
                的本地记忆，不再做预设人格切换。
              </p>
            </div>
            <button
              type="button"
              onClick={() => void refresh()}
              disabled={refreshing}
              className="inline-flex items-center gap-2 rounded-2xl border border-white/[0.08] bg-white/[0.03] px-4 py-3 text-sm font-semibold text-slate-200 transition hover:border-cyan-300/30 hover:text-white disabled:opacity-50"
            >
              <RefreshCw size={16} className={refreshing ? "animate-spin" : ""} />
              刷新画像
            </button>
          </div>

          {error ? (
            <div className="mt-6 rounded-2xl border border-rose-400/20 bg-rose-500/10 px-5 py-4 text-sm text-rose-100">
              {error}
            </div>
          ) : null}

          {loading ? (
            <div className="mt-8 rounded-3xl border border-white/[0.08] bg-white/[0.03] px-6 py-10 text-center text-sm text-slate-400">
              正在读取当前陪伴画像...
            </div>
          ) : (
            <>
              <div className="mt-6 grid grid-cols-1 lg:grid-cols-[1fr_1.2fr] gap-6">
                <div className="rounded-3xl border border-white/[0.08] bg-white/[0.03] p-6">
                  <div className="flex items-center gap-3">
                    <UserRound className="h-5 w-5 text-fuchsia-300" />
                    <div className="text-lg font-black text-white">身份确认</div>
                  </div>
                  <div className="mt-5 space-y-3 text-sm text-slate-300">
                    <div>
                      <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500">名字</div>
                      <div className="mt-1 text-xl font-black text-white">
                        {activation.preferred_name || "未确认"}
                      </div>
                    </div>
                    <div>
                      <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500">一句介绍</div>
                      <div className="mt-1 leading-7">
                        {activation.voice_intro_summary || "尚未补充"}
                      </div>
                    </div>
                    <div>
                      <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500">摘要</div>
                      <div className="mt-1 leading-7">
                        {activation.identity_summary || "尚未完成身份确认"}
                      </div>
                    </div>
                    <div className="pt-2 text-xs text-slate-500">
                      最近完成时间：{formatDateTime(activation.completed_at_ms)}
                    </div>
                  </div>
                </div>

                <div className="rounded-3xl border border-cyan-400/20 bg-cyan-500/10 p-6">
                  <div className="flex items-center gap-3">
                    <Brain className="h-5 w-5 text-cyan-200" />
                    <div className="text-lg font-black text-white">建档进度</div>
                  </div>
                  <div className="mt-5 grid grid-cols-1 sm:grid-cols-3 gap-4">
                    <div className="rounded-2xl border border-white/15 bg-white/5 px-4 py-4">
                      <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500">状态</div>
                      <div className="mt-2 text-lg font-black text-white">
                        {assessment.assessment_ready ? "已完成" : "待完成"}
                      </div>
                    </div>
                    <div className="rounded-2xl border border-white/15 bg-white/5 px-4 py-4">
                      <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500">有效回答</div>
                      <div className="mt-2 text-lg font-black text-white">
                        {assessment.conversation_count}
                      </div>
                    </div>
                    <div className="rounded-2xl border border-white/15 bg-white/5 px-4 py-4">
                      <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500">稳定度</div>
                      <div className="mt-2 text-lg font-black text-white">
                        {Math.round((assessment.confidence || 0) * 100)}%
                      </div>
                    </div>
                  </div>
                  <div className="mt-5 text-sm leading-7 text-slate-100">
                    {assessment.summary ||
                      "聊天式建档完成后，这里会显示压缩后的偏好画像与陪伴指引。"}
                  </div>
                </div>
              </div>

              <div className="mt-6 grid grid-cols-1 lg:grid-cols-2 gap-6">
                {cards.length > 0 ? (
                  cards.map((item) => (
                    <div key={item.label} className="rounded-3xl border border-white/[0.08] bg-white/[0.03] p-6">
                      <div className="flex items-center gap-3">
                        <Sparkles className="h-4 w-4 text-indigo-300" />
                        <div className="text-sm font-bold text-slate-300">{item.label}</div>
                      </div>
                      <div className="mt-4 text-base leading-8 text-white">{item.value}</div>
                    </div>
                  ))
                ) : (
                  <div className="rounded-3xl border border-white/[0.08] bg-white/[0.03] p-6 text-sm leading-7 text-slate-400 lg:col-span-2">
                    这位用户还没有完成正式建档。完成首次激活后，这里会显示“偏好 + 反应画像 +
                    陪伴指引”，并同步进入 OpenClaw 的本地长期记忆。
                  </div>
                )}
              </div>

              <div className="mt-6 rounded-3xl border border-emerald-400/20 bg-emerald-500/10 p-6">
                <div className="flex items-center gap-3">
                  <BookHeart className="h-5 w-5 text-emerald-200" />
                  <div className="text-lg font-black text-white">记忆说明</div>
                </div>
                <div className="mt-4 text-sm leading-8 text-emerald-50">
                  这里显示的是 OpenClaw 后续普通聊天与主动关怀会直接读取的陪伴画像，而不是旧版本那种预设角色卡。后面继续聊天时，AI 应该遵循这里沉淀下来的偏好和反应方式。
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
