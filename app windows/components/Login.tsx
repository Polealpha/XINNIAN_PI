import React, { useState } from "react";
import { ArrowRight, Github, Lock, Mail, Sparkles, UserPlus } from "lucide-react";
import { login, register, LoginResult } from "../services/authService";

interface LoginProps {
  onLogin: (result: LoginResult) => Promise<void> | void;
}

type AuthMode = "login" | "register";

export const Login: React.FC<LoginProps> = ({ onLogin }) => {
  const appIcon = new URL("../assets/app-icon.png", import.meta.url).href;
  const [mode, setMode] = useState<AuthMode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const isRegister = mode === "register";

  const handleForgotPassword = () => {
    setError("暂未开放找回密码，请联系管理员或重新注册。");
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError("");

    try {
      if (isRegister) {
        if (password.length < 6) {
          setError("密码至少需要 6 位，请重新输入。");
          setLoading(false);
          return;
        }

        if (password !== confirmPassword) {
          setError("两次输入的密码不一致，请重新确认。");
          setLoading(false);
          return;
        }

        await register(email, password);
      }

      const result = await login(email, password);
      await onLogin(result);
    } catch (err: any) {
      console.error(err);
      if (isRegister && String(err?.message || "").includes("409")) {
        setError("这个邮箱已经注册过了，请直接登录。");
      } else {
        setError(isRegister ? "注册失败，请稍后再试。" : "登录失败，请检查账号或密码。");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden px-6 py-8 text-white">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_12%_14%,rgba(255,205,227,0.22),transparent_20%),radial-gradient(circle_at_82%_10%,rgba(146,224,255,0.18),transparent_18%),radial-gradient(circle_at_60%_82%,rgba(198,222,255,0.14),transparent_20%),linear-gradient(180deg,#09101b_0%,#0b111d_42%,#080d17_100%)]" />
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(180deg,rgba(255,255,255,0.06),transparent_18%)]" />
      <div className="pointer-events-none absolute inset-0 opacity-80">
        <div className="absolute -left-24 top-12 h-72 w-72 rounded-full bg-pink-300/12 blur-[90px]" />
        <div className="absolute right-8 top-10 h-80 w-80 rounded-full bg-sky-300/10 blur-[100px]" />
        <div className="absolute bottom-0 left-1/2 h-80 w-80 -translate-x-1/2 rounded-full bg-indigo-300/8 blur-[110px]" />
      </div>

      <div className="relative z-10 w-full max-w-[1180px] ios-subpage-hero">
        <div className="ios-liquid-blob ios-liquid-blob--focus" />
        <div className="grid gap-5 lg:grid-cols-[1.06fr_0.94fr]">
          <section className="ios-stage-panel rounded-[2.35rem] px-9 py-9">
            <div className="flex min-h-[650px] flex-col">
              <div className="ios-chip-soft inline-flex w-fit items-center gap-2 rounded-full px-4 py-2 text-[10px] font-black tracking-[0.3em] text-slate-200">
                <Sparkles size={12} />
                欢迎来到
              </div>

              <div className="mt-7 flex items-center gap-5">
                <div className="ios-stage-well rounded-[1.75rem] p-4">
                  <img src={appIcon} alt="app icon" className="h-16 w-16 object-contain" />
                </div>
                <div>
                  <div className="text-[10px] font-black tracking-[0.28em] text-slate-400">
                    情绪陪伴桌面
                  </div>
                  <h1 className="mt-2 text-[2.8rem] font-black tracking-[-0.06em] text-white">
                    心念双灵
                  </h1>
                  <p className="mt-2 text-sm font-semibold tracking-[0.08em] text-slate-400">
                    陪你看见情绪起伏，也在需要的时候轻轻提醒
                  </p>
                </div>
              </div>

              <div className="mt-10 grid gap-4">
                <div className="ios-stage-panel ios-stage-panel--soft rounded-[1.8rem] px-5 py-5">
                  <div className="text-[10px] font-black tracking-[0.24em] text-sky-200/70">
                    今天的陪伴
                  </div>
                  <div className="mt-3 text-[1.55rem] font-black tracking-[-0.04em] text-white">
                    把状态慢慢找回来
                  </div>
                  <p className="mt-3 text-sm leading-7 text-slate-300">
                    登录后就能继续查看记录、和助手聊天，也能接收提醒与设备状态。
                  </p>
                </div>

                <div className="grid gap-4 sm:grid-cols-3">
                  <div className="ios-stage-tile rounded-[1.6rem] px-4 py-4">
                    <div className="text-[10px] font-black tracking-[0.22em] text-slate-500">
                      情绪
                    </div>
                    <div className="mt-2 text-lg font-black text-white">看见今天的状态</div>
                    <p className="mt-2 text-xs leading-6 text-slate-400">
                      把一天里的情绪变化安静记录下来。
                    </p>
                  </div>
                  <div className="ios-stage-tile rounded-[1.6rem] px-4 py-4">
                    <div className="text-[10px] font-black tracking-[0.22em] text-slate-500">
                      陪伴
                    </div>
                    <div className="mt-2 text-lg font-black text-white">随时和我聊聊</div>
                    <p className="mt-2 text-xs leading-6 text-slate-400">
                      想说什么都可以慢慢说，不用着急。
                    </p>
                  </div>
                  <div className="ios-stage-tile rounded-[1.6rem] px-4 py-4">
                    <div className="text-[10px] font-black tracking-[0.22em] text-slate-500">
                      提醒
                    </div>
                    <div className="mt-2 text-lg font-black text-white">不错过重要时刻</div>
                    <p className="mt-2 text-xs leading-6 text-slate-400">
                      让关心、任务和节奏更有秩序。
                    </p>
                  </div>
                </div>
              </div>

              <div className="mt-auto pt-10">
                <div className="ios-stage-well rounded-[1.8rem] px-5 py-4">
                  <div className="text-[10px] font-black tracking-[0.22em] text-slate-500">
                    一句轻提醒
                  </div>
                  <div className="mt-2 text-base font-black text-white">你不需要时刻完美</div>
                  <p className="mt-2 text-sm leading-7 text-slate-300">
                    先登录，再慢慢开始今天的节奏，我们会陪你把状态一点点找回来。
                  </p>
                </div>
              </div>
            </div>
          </section>

          <section className="ios-stage-panel ios-stage-panel--deep rounded-[2.35rem] px-8 py-8">
            <div className="ios-liquid-blob" />
            <div className="mb-7">
              <div className="text-[10px] font-black tracking-[0.3em] text-slate-500">欢迎回来</div>
              <div className="mt-3 text-[1.9rem] font-black tracking-[-0.05em] text-white">
                {isRegister ? "创建你的专属空间" : "进入你的陪伴空间"}
              </div>
              <p className="mt-2 text-sm leading-7 text-slate-400">
                {isRegister
                  ? "注册后，就能开始记录今天的情绪与陪伴时刻。"
                  : "用邮箱登录，继续今天的情绪与陪伴记录。"}
              </p>
            </div>

            <div className="ios-segmented mb-6 flex items-center gap-2 rounded-full p-2">
              <button
                type="button"
                onClick={() => setMode("login")}
                className={`flex-1 rounded-full py-2.5 text-xs font-black tracking-[0.18em] transition-all ${
                  mode === "login" ? "ios-segmented__item--active" : "text-slate-400"
                }`}
              >
                登录
              </button>
              <button
                type="button"
                onClick={() => setMode("register")}
                className={`flex-1 rounded-full py-2.5 text-xs font-black tracking-[0.18em] transition-all ${
                  mode === "register" ? "ios-segmented__item--active" : "text-slate-400"
                }`}
              >
                注册
              </button>
            </div>

            <form onSubmit={handleSubmit} className="space-y-5">
              <div className="space-y-2">
                <label className="ml-3 text-[10px] font-black tracking-[0.2em] text-slate-500">
                  邮箱账号
                </label>
                <div className="group relative">
                  <div className="absolute left-5 top-1/2 -translate-y-1/2 text-slate-500 transition-colors group-focus-within:text-sky-300">
                    <Mail size={18} />
                  </div>
                  <input
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="resonance@example.com"
                    className="ios-form-field w-full py-4 pl-14 pr-6 font-bold"
                  />
                </div>
              </div>

              <div className="space-y-2">
                <label className="ml-3 text-[10px] font-black tracking-[0.2em] text-slate-500">
                  登录密码
                </label>
                <div className="group relative">
                  <div className="absolute left-5 top-1/2 -translate-y-1/2 text-slate-500 transition-colors group-focus-within:text-sky-300">
                    <Lock size={18} />
                  </div>
                  <input
                    type="password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="请输入密码"
                    className="ios-form-field w-full py-4 pl-14 pr-6 font-bold"
                  />
                </div>
              </div>

              {isRegister ? (
                <div className="space-y-2">
                  <label className="ml-3 text-[10px] font-black tracking-[0.2em] text-slate-500">
                    确认密码
                  </label>
                  <div className="group relative">
                    <div className="absolute left-5 top-1/2 -translate-y-1/2 text-slate-500 transition-colors group-focus-within:text-sky-300">
                      <UserPlus size={18} />
                    </div>
                    <input
                      type="password"
                      required
                      value={confirmPassword}
                      onChange={(e) => setConfirmPassword(e.target.value)}
                      placeholder="再次输入密码"
                      className="ios-form-field w-full py-4 pl-14 pr-6 font-bold"
                    />
                  </div>
                </div>
              ) : (
                <div className="flex items-center justify-between px-2 pt-1 text-[11px] font-black tracking-tight text-slate-500">
                  <label className="flex cursor-pointer items-center gap-2 transition-colors hover:text-slate-300">
                    <input type="checkbox" className="h-4 w-4 rounded-md accent-indigo-500" />
                    <span>记住我的身份</span>
                  </label>
                  <button
                    type="button"
                    onClick={handleForgotPassword}
                    className="transition-colors hover:text-sky-300"
                  >
                    忘记密码？
                  </button>
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="ios-action-button ios-action-button--primary mt-7 flex w-full py-4 text-base"
              >
                {loading ? (
                  <div className="h-5 w-5 animate-spin rounded-full border-2 border-slate-900 border-t-transparent" />
                ) : (
                  <>
                    <span>{isRegister ? "创建我的空间" : "进入陪伴空间"}</span>
                    <ArrowRight size={20} />
                  </>
                )}
              </button>

              {error ? (
                <div className="ios-stage-tile rounded-[1.25rem] px-4 py-3 text-center text-[11px] font-bold text-rose-300">
                  {error}
                </div>
              ) : null}
            </form>

            <div className="mt-9">
              <div className="mb-6 flex items-center gap-4">
                <div className="h-px flex-1 bg-white/5" />
                <span className="text-[9px] font-black tracking-[0.28em] text-slate-600">
                  其他登录方式
                </span>
                <div className="h-px flex-1 bg-white/5" />
              </div>
              <div className="flex gap-4">
                <button
                  type="button"
                  className="ios-action-button ios-action-button--secondary h-14 w-14 rounded-[1.25rem] p-0 text-slate-300"
                  aria-label="GitHub login"
                >
                  <Github size={20} />
                </button>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
};
