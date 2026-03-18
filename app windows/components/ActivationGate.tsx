import React, { useEffect, useMemo, useState } from "react";
import {
  Bot,
  Brain,
  Camera,
  CheckCircle2,
  LoaderCircle,
  ScanFace,
  ShieldCheck,
  Sparkles,
  UserRound,
} from "lucide-react";

import { getActivationState } from "../services/authService";
import {
  completeActivation,
  completePersonalityProfile,
  getPersonalityState,
  inferActivationIdentity,
  inferPersonalityProfile,
  startOwnerEnrollment,
  type ActivationIdentityInference,
  type PersonalityProfile,
} from "../services/activationService";

interface ActivationGateProps {
  onActivated: () => Promise<void> | void;
}

const PERSONALITY_QUESTIONS = [
  "别人通常会怎么形容你的性格？",
  "当你压力很大时，你更希望机器人怎么陪你？",
  "你最不喜欢怎样的提醒或说话方式？",
  "如果你情绪不好，通常会先沉默、直接说出来，还是先自己消化？",
];

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

const emptyPersonality = (): PersonalityProfile => ({
  ok: true,
  exists: false,
  summary: "",
  response_style: "",
  care_style: "",
  traits: [],
  topics: [],
  boundaries: [],
  signals: [],
  confidence: 0,
  sample_count: 0,
  inference_version: "v1",
});

export const ActivationGate: React.FC<ActivationGateProps> = ({ onActivated }) => {
  const [booting, setBooting] = useState(true);
  const [busy, setBusy] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [identityState, setIdentityState] = useState(emptyIdentity);
  const [identityReady, setIdentityReady] = useState(false);
  const [introTranscript, setIntroTranscript] = useState("");
  const [observedName, setObservedName] = useState("");
  const [personalityState, setPersonalityState] = useState<PersonalityProfile>(emptyPersonality);
  const [personalityAnswers, setPersonalityAnswers] = useState<string[]>(() => PERSONALITY_QUESTIONS.map(() => ""));
  const [scanState, setScanState] = useState("");

  useEffect(() => {
    let active = true;
    const bootstrap = async () => {
      setBooting(true);
      setError("");
      try {
        const [activation, personality] = await Promise.all([getActivationState(), getPersonalityState()]);
        if (!active) return;
        setIdentityReady(!activation.activation_required);
        setIdentityState({
          ok: true,
          preferred_name: activation.preferred_name || "",
          role_label: activation.role_label || "owner",
          relation_to_robot: activation.relation_to_robot || "primary_user",
          pronouns: activation.pronouns || "",
          identity_summary: activation.identity_summary || "",
          onboarding_notes: activation.onboarding_notes || "",
          voice_intro_summary: activation.voice_intro_summary || "",
          confidence: activation.activation_required ? 0 : 1,
          raw_json: {},
        });
        setPersonalityState(personality);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (active) setBooting(false);
      }
    };
    bootstrap();
    return () => {
      active = false;
    };
  }, []);

  const canInferPersonality = useMemo(
    () => personalityAnswers.filter((item) => item.trim().length >= 4).length >= 2,
    [personalityAnswers]
  );

  const handleInferIdentity = async () => {
    if (!introTranscript.trim()) {
      setError("先让这个人用一句话介绍自己，再做身份识别。");
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
        context: { source: "app_windows_native_activation" },
      });
      setIdentityState(inferred);
      if (inferred.preferred_name && !observedName.trim()) {
        setObservedName(inferred.preferred_name);
      }
      setSuccess("身份草稿已生成，请确认后保存。");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const handleCompleteIdentity = async () => {
    if (!identityState.preferred_name.trim()) {
      setError("请先确认称呼。");
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
          source: "app_windows_native_activation",
          intro_transcript: introTranscript.trim(),
        },
        activation_version: "v2-native",
      });
      setIdentityReady(true);
      setSuccess("身份已确认。接下来补充几轮画像，OpenClaw 会按这个人长期服务。");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const handleInferPersonality = async () => {
    if (!canInferPersonality) {
      setError("至少回答两条画像问题后再生成。");
      return;
    }
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const answers = personalityAnswers.map((item) => item.trim()).filter(Boolean);
      const inferred = await inferPersonalityProfile({
        answers,
        transcript: answers.join("\n"),
        surface: "desktop",
        context: {
          source: "app_windows_native_activation",
          preferred_name: identityState.preferred_name,
          role_label: identityState.role_label,
        },
      });
      setPersonalityState(inferred);
      setSuccess("人格画像已生成，请确认后保存。");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const handleSavePersonality = async () => {
    if (!personalityState.summary.trim()) {
      setError("请先生成人格画像。");
      return;
    }
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const saved = await completePersonalityProfile({
        summary: personalityState.summary,
        response_style: personalityState.response_style,
        care_style: personalityState.care_style,
        traits: personalityState.traits,
        topics: personalityState.topics,
        boundaries: personalityState.boundaries,
        signals: personalityState.signals,
        confidence: personalityState.confidence,
        sample_count: personalityState.sample_count,
        inference_version: personalityState.inference_version || "v1",
        profile: {
          source: "app_windows_native_activation",
          answers: personalityAnswers,
        },
      });
      setPersonalityState(saved);
      setSuccess("人格画像已保存。后续聊天和机器人动作都会参考这份画像。");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const handleStartFaceScan = async () => {
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const response = await startOwnerEnrollment();
      setScanState(response?.detail || "已经向机器人发起扫脸建档请求。");
      setSuccess("扫脸建档请求已发送到机器人端。");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const handleFinish = async () => {
    if (!identityReady) {
      setError("请先完成身份确认。");
      return;
    }
    if (!personalityState.summary.trim()) {
      setError("请先保存人格画像。");
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
          正在加载登录后的激活向导...
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#070b14] text-slate-100 px-8 py-7">
      <div className="max-w-7xl mx-auto h-full flex flex-col gap-6">
        <div className="rounded-[2rem] border border-white/10 bg-slate-950/60 backdrop-blur-2xl px-8 py-6 flex items-center justify-between gap-6">
          <div className="flex items-center gap-4">
            <div className="w-14 h-14 rounded-3xl bg-emerald-500/15 text-emerald-300 border border-emerald-500/20 flex items-center justify-center">
              <ShieldCheck size={26} />
            </div>
            <div>
              <h1 className="text-2xl font-black tracking-tight">首次激活</h1>
              <p className="text-sm text-slate-400 font-semibold">
                这一步只在登录后进行。先确认这个人是谁，再用几轮对话抽取稳定的人格画像，最后再开启扫脸主人建档。
              </p>
            </div>
          </div>
          <button
            onClick={handleFinish}
            disabled={busy || finishing || !identityReady || !personalityState.summary.trim()}
            className="px-5 py-3 rounded-2xl bg-white text-slate-950 font-black text-sm disabled:opacity-50 flex items-center gap-2"
          >
            {finishing ? <LoaderCircle className="animate-spin" size={16} /> : <CheckCircle2 size={16} />}
            完成激活并进入桌面
          </button>
        </div>

        <div className="grid grid-cols-12 gap-6 flex-1">
          <section className="col-span-4 rounded-[2rem] border border-white/10 bg-slate-950/45 p-6 flex flex-col gap-4">
            <div className="flex items-center gap-3">
              <UserRound size={18} className="text-indigo-300" />
              <h2 className="text-lg font-black">1. 身份确认</h2>
            </div>
            <p className="text-xs text-slate-400 font-semibold leading-6">
              让这个人在登录后先说一句自我介绍，例如“我叫小北，是这个机器人的主人”。这段内容会用于身份识别和后续扫脸绑定。
            </p>
            <textarea
              value={introTranscript}
              onChange={(e) => setIntroTranscript(e.target.value)}
              placeholder="输入首次自我介绍，或把机器人语音转写贴进来。"
              className="min-h-[132px] rounded-3xl bg-slate-900/70 border border-white/10 px-4 py-4 text-sm font-semibold text-slate-100 outline-none resize-none"
            />
            <input
              value={observedName}
              onChange={(e) => setObservedName(e.target.value)}
              placeholder="如果你已经知道称呼，可先填在这里"
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
              <label className="space-y-2 col-span-2">
                <span className="text-[11px] font-black text-slate-400 uppercase tracking-[0.2em]">称呼</span>
                <input
                  value={identityState.preferred_name}
                  onChange={(e) => setIdentityState((prev) => ({ ...prev, preferred_name: e.target.value }))}
                  className="w-full rounded-2xl bg-slate-900/70 border border-white/10 px-4 py-3 text-sm font-semibold outline-none"
                />
              </label>
              <label className="space-y-2">
                <span className="text-[11px] font-black text-slate-400 uppercase tracking-[0.2em]">角色</span>
                <select
                  value={identityState.role_label}
                  onChange={(e) => setIdentityState((prev) => ({ ...prev, role_label: e.target.value }))}
                  className="w-full rounded-2xl bg-slate-900/70 border border-white/10 px-4 py-3 text-sm font-semibold outline-none"
                >
                  {["owner", "family", "caregiver", "guest", "operator", "admin", "patient", "unknown"].map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-2">
                <span className="text-[11px] font-black text-slate-400 uppercase tracking-[0.2em]">关系</span>
                <select
                  value={identityState.relation_to_robot}
                  onChange={(e) => setIdentityState((prev) => ({ ...prev, relation_to_robot: e.target.value }))}
                  className="w-full rounded-2xl bg-slate-900/70 border border-white/10 px-4 py-3 text-sm font-semibold outline-none"
                >
                  {["primary_user", "family_member", "caregiver", "visitor", "maintainer", "observer", "unknown"].map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-2 col-span-2">
                <span className="text-[11px] font-black text-slate-400 uppercase tracking-[0.2em]">身份摘要</span>
                <textarea
                  value={identityState.identity_summary}
                  onChange={(e) => setIdentityState((prev) => ({ ...prev, identity_summary: e.target.value }))}
                  className="w-full min-h-[84px] rounded-2xl bg-slate-900/70 border border-white/10 px-4 py-3 text-sm font-semibold outline-none resize-none"
                />
              </label>
              <label className="space-y-2 col-span-2">
                <span className="text-[11px] font-black text-slate-400 uppercase tracking-[0.2em]">待确认事项</span>
                <textarea
                  value={identityState.onboarding_notes}
                  onChange={(e) => setIdentityState((prev) => ({ ...prev, onboarding_notes: e.target.value }))}
                  className="w-full min-h-[74px] rounded-2xl bg-slate-900/70 border border-white/10 px-4 py-3 text-sm font-semibold outline-none resize-none"
                />
              </label>
            </div>
            <div className="flex items-center justify-between text-xs text-slate-400 font-semibold">
              <span>识别置信度 {Math.round((identityState.confidence || 0) * 100)}%</span>
              {identityReady ? <span className="text-emerald-300">已确认</span> : <span>待保存</span>}
            </div>
            <button
              onClick={handleCompleteIdentity}
              disabled={busy}
              className="rounded-2xl bg-white text-slate-950 py-3 font-black text-sm disabled:opacity-50"
            >
              保存身份卡
            </button>
          </section>

          <section className="col-span-5 rounded-[2rem] border border-white/10 bg-slate-950/45 p-6 flex flex-col gap-4">
            <div className="flex items-center gap-3">
              <Brain size={18} className="text-fuchsia-300" />
              <h2 className="text-lg font-black">2. 登录后人格画像</h2>
            </div>
            <p className="text-xs text-slate-400 font-semibold leading-6">
              这几轮回答会直接影响 OpenClaw 的长期记忆、回复方式和机器人陪伴策略。默认偏好已经固定为
              <span className="text-white"> gpt-5.4 + cli/codex 风格</span>，这里只补充这个人的稳定特征。
            </p>
            <div className="space-y-3">
              {PERSONALITY_QUESTIONS.map((question, index) => (
                <label key={question} className="block space-y-2">
                  <span className="text-[12px] font-black text-slate-300">{index + 1}. {question}</span>
                  <textarea
                    value={personalityAnswers[index]}
                    onChange={(e) =>
                      setPersonalityAnswers((prev) => prev.map((item, i) => (i === index ? e.target.value : item)))
                    }
                    className="w-full min-h-[72px] rounded-2xl bg-slate-900/70 border border-white/10 px-4 py-3 text-sm font-semibold outline-none resize-none"
                  />
                </label>
              ))}
            </div>
            <div className="flex gap-3">
              <button
                onClick={handleInferPersonality}
                disabled={busy || !canInferPersonality}
                className="flex-1 rounded-2xl bg-fuchsia-500/15 border border-fuchsia-400/20 text-fuchsia-200 py-3 font-black text-sm disabled:opacity-50"
              >
                生成人格画像
              </button>
              <button
                onClick={handleSavePersonality}
                disabled={busy || !personalityState.summary.trim()}
                className="flex-1 rounded-2xl bg-white text-slate-950 py-3 font-black text-sm disabled:opacity-50"
              >
                保存到长期记忆
              </button>
            </div>
            <div className="rounded-[1.6rem] border border-white/10 bg-slate-900/55 p-5 space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="font-black text-white">当前画像</h3>
                <span className="text-xs text-slate-400 font-semibold">
                  样本 {personalityState.sample_count || 0} / 置信度 {Math.round((personalityState.confidence || 0) * 100)}%
                </span>
              </div>
              <textarea
                value={personalityState.summary}
                onChange={(e) => setPersonalityState((prev) => ({ ...prev, summary: e.target.value }))}
                placeholder="这里会生成长期人格摘要"
                className="w-full min-h-[90px] rounded-2xl bg-slate-950/80 border border-white/10 px-4 py-3 text-sm font-semibold outline-none resize-none"
              />
              <div className="grid grid-cols-2 gap-3">
                <label className="space-y-2">
                  <span className="text-[11px] font-black text-slate-400 uppercase tracking-[0.2em]">回复风格</span>
                  <textarea
                    value={personalityState.response_style}
                    onChange={(e) => setPersonalityState((prev) => ({ ...prev, response_style: e.target.value }))}
                    className="w-full min-h-[74px] rounded-2xl bg-slate-950/80 border border-white/10 px-4 py-3 text-sm font-semibold outline-none resize-none"
                  />
                </label>
                <label className="space-y-2">
                  <span className="text-[11px] font-black text-slate-400 uppercase tracking-[0.2em]">陪伴风格</span>
                  <textarea
                    value={personalityState.care_style}
                    onChange={(e) => setPersonalityState((prev) => ({ ...prev, care_style: e.target.value }))}
                    className="w-full min-h-[74px] rounded-2xl bg-slate-950/80 border border-white/10 px-4 py-3 text-sm font-semibold outline-none resize-none"
                  />
                </label>
              </div>
              <div className="grid grid-cols-2 gap-3 text-sm">
                {[
                  ["traits", "稳定特征"],
                  ["topics", "长期关注"],
                  ["boundaries", "互动边界"],
                  ["signals", "识别线索"],
                ].map(([key, label]) => (
                  <label key={key} className="space-y-2">
                    <span className="text-[11px] font-black text-slate-400 uppercase tracking-[0.2em]">{label}</span>
                    <input
                      value={(personalityState[key as keyof PersonalityProfile] as string[]).join(" / ")}
                      onChange={(e) =>
                        setPersonalityState((prev) => ({
                          ...prev,
                          [key]: e.target.value
                            .split(/[\/、,，]/)
                            .map((item) => item.trim())
                            .filter(Boolean),
                        }))
                      }
                      className="w-full rounded-2xl bg-slate-950/80 border border-white/10 px-4 py-3 font-semibold outline-none"
                    />
                  </label>
                ))}
              </div>
            </div>
          </section>

          <section className="col-span-3 rounded-[2rem] border border-white/10 bg-slate-950/45 p-6 flex flex-col gap-4">
            <div className="flex items-center gap-3">
              <ScanFace size={18} className="text-amber-300" />
              <h2 className="text-lg font-black">3. 扫脸与机器人绑定</h2>
            </div>
            <div className="rounded-[1.6rem] border border-white/10 bg-slate-900/55 p-4 space-y-3 text-sm font-semibold text-slate-300 leading-6">
              <p className="flex items-start gap-2">
                <Bot size={16} className="mt-1 text-slate-400" />
                扫脸只会在登录后、身份确认后触发。这样机器人先知道“你是谁”，再去绑定主人人脸。
              </p>
              <p className="flex items-start gap-2">
                <Camera size={16} className="mt-1 text-slate-400" />
                这一步会请求树莓派本地的 <code className="text-indigo-200">/owner/enrollment/start</code>，不会把原始视频长期上传服务器。
              </p>
              <p className="flex items-start gap-2">
                <ShieldCheck size={16} className="mt-1 text-slate-400" />
                服务器只保存元数据和版本号；真正的人脸模板仍在机器人本地。
              </p>
            </div>
            <button
              onClick={handleStartFaceScan}
              disabled={busy || !identityReady}
              className="rounded-2xl bg-amber-500/15 border border-amber-400/20 text-amber-200 py-3 font-black text-sm disabled:opacity-50"
            >
              启动主人扫脸建档
            </button>
            {scanState ? (
              <div className="rounded-2xl border border-emerald-400/20 bg-emerald-500/10 px-4 py-3 text-sm font-semibold text-emerald-200">
                {scanState}
              </div>
            ) : null}
            <div className="mt-auto rounded-[1.6rem] border border-white/10 bg-black/20 px-4 py-4">
              <p className="text-xs text-slate-400 font-semibold leading-6">
                你后续如果要把主人身份继续细化到“性格越来越准”，不需要重新登录。之后的正式聊天也会继续补充这份画像。
              </p>
            </div>
          </section>
        </div>

        {error ? <p className="text-sm font-bold text-rose-400">{error}</p> : null}
        {success ? <p className="text-sm font-bold text-emerald-300">{success}</p> : null}
      </div>
    </div>
  );
};
