import React, { useState } from "react";
import { Mail, Lock, ArrowRight, Github, UserPlus } from "lucide-react";
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
    setError("忘记密码功能暂未开放，请联系管理员或重新注册账号。");
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      if (isRegister) {
        if (password.length < 6) {
          setError("密码至少 6 位，请重新输入。");
          setLoading(false);
          return;
        }
        if (password !== confirmPassword) {
          setError("两次密码不一致，请重新输入。");
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
        setError(isRegister ? "注册失败，请稍后重试。" : "登录失败，请检查账号或密码。");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden px-6 py-8 text-white">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_16%_18%,rgba(125,149,255,0.18),transparent_24%),radial-gradient(circle_at_82%_14%,rgba(103,232,249,0.12),transparent_18%),linear-gradient(180deg,#09111d_0%,#0a1220_48%,#090f19_100%)]" />
      <div className="pointer-events-none absolute inset-x-0 top-0 h-40 bg-[linear-gradient(180deg,rgba(255,255,255,0.04),transparent)]" />

      <div className="relative z-10 w-full max-w-[1080px] rounded-[2.6rem] border border-white/10 bg-[linear-gradient(180deg,rgba(17,24,40,0.78),rgba(8,13,24,0.92))] p-4 shadow-[0_30px_100px_rgba(3,8,20,0.38),inset_0_1px_0_rgba(255,255,255,0.06)] backdrop-blur-[22px]">
        <div className="grid gap-4 lg:grid-cols-[1.08fr_0.92fr]">
          <section className="relative overflow-hidden rounded-[2.2rem] border border-white/8 bg-[linear-gradient(180deg,rgba(255,255,255,0.06),rgba(255,255,255,0.025))] px-8 py-9">
            <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(129,140,248,0.18),transparent_28%),radial-gradient(circle_at_88%_18%,rgba(125,211,252,0.12),transparent_20%)]" />
            <div className="relative">
              <div className="inline-flex items-center rounded-full border border-white/10 bg-white/[0.04] px-4 py-2 text-[10px] font-black uppercase tracking-[0.34em] text-slate-300">
                Welcome Back
              </div>
              <div className="mt-8 flex items-center gap-5">
                <div className="ios-brand-mark h-20 w-20 rounded-[1.7rem]">
                  <img src={appIcon} alt="app icon" className="h-full w-full rounded-[1.5rem] object-cover" />
                </div>
                <div>
                  <h1 className="text-[2.5rem] font-black tracking-[-0.05em] text-white">共鸣连接</h1>
                  <p className="mt-2 text-sm font-semibold uppercase tracking-[0.28em] text-slate-400">
                    感知情绪 · 连接伙伴
                  </p>
                </div>
              </div>

              <p className="mt-8 max-w-[32rem] text-[1.05rem] leading-8 text-slate-300">
                入口页也改成和主桌面同一套语言了。现在会更像系统原生面板，层级更轻，文字更清楚，不再是厚重玻璃和大面积糊光。
              </p>

              <div className="mt-10 grid gap-3 sm:grid-cols-3">
                {[
                  { label: "Connect", value: "更轻的层次" },
                  { label: "Privacy", value: "本地优先" },
                  { label: "Clarity", value: "更锐的文字" },
                ].map((item) => (
                  <div
                    key={item.label}
                    className="rounded-[1.5rem] border border-white/8 bg-white/[0.035] px-4 py-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]"
                  >
                    <div className="text-[10px] font-black uppercase tracking-[0.28em] text-slate-500">{item.label}</div>
                    <div className="mt-2 text-sm font-bold text-white">{item.value}</div>
                  </div>
                ))}
              </div>
            </div>
          </section>

          <section className="rounded-[2.2rem] border border-white/8 bg-[linear-gradient(180deg,rgba(12,18,32,0.88),rgba(8,13,24,0.96))] px-8 py-8 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]">
            <div className="mb-8">
              <div className="text-[10px] font-black uppercase tracking-[0.32em] text-slate-500">Account Access</div>
              <div className="mt-3 text-[1.85rem] font-black tracking-[-0.04em] text-white">
                {isRegister ? "创建你的心境账号" : "进入你的心境空间"}
              </div>
            </div>

        <div className="flex items-center gap-2 bg-white/[0.035] p-2 rounded-full border border-white/10 mb-6">
          <button
            type="button"
            onClick={() => setMode("login")}
            className={`flex-1 py-2 rounded-full text-xs font-black uppercase tracking-[0.2em] transition-all ${
              mode === "login" ? "bg-white text-slate-950 shadow-[0_10px_20px_rgba(255,255,255,0.08)]" : "text-slate-400"
            }`}
          >
            登录
          </button>
          <button
            type="button"
            onClick={() => setMode("register")}
            className={`flex-1 py-2 rounded-full text-xs font-black uppercase tracking-[0.2em] transition-all ${
              mode === "register" ? "bg-white text-slate-950 shadow-[0_10px_20px_rgba(255,255,255,0.08)]" : "text-slate-400"
            }`}
          >
            注册
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="space-y-2">
            <label className="text-[10px] font-black text-slate-500 uppercase ml-4 tracking-[0.2em]">
              邮箱账号
            </label>
            <div className="relative group">
              <div className="absolute left-5 top-1/2 -translate-y-1/2 text-slate-500 group-focus-within:text-indigo-400 transition-colors">
                <Mail size={18} />
              </div>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="resonance@example.com"
                className="w-full rounded-[1.4rem] border border-white/8 bg-white/[0.04] py-4 pl-14 pr-6 text-white font-bold outline-none transition-all placeholder:text-slate-600 focus:border-sky-300/30 focus:ring-2 focus:ring-sky-300/15"
              />
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-[10px] font-black text-slate-500 uppercase ml-4 tracking-[0.2em]">
              登录密码
            </label>
            <div className="relative group">
              <div className="absolute left-5 top-1/2 -translate-y-1/2 text-slate-500 group-focus-within:text-indigo-400 transition-colors">
                <Lock size={18} />
              </div>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="请输入密码"
                className="w-full rounded-[1.4rem] border border-white/8 bg-white/[0.04] py-4 pl-14 pr-6 text-white font-bold outline-none transition-all placeholder:text-slate-600 focus:border-sky-300/30 focus:ring-2 focus:ring-sky-300/15"
              />
            </div>
          </div>

          {isRegister ? (
            <div className="space-y-2">
              <label className="text-[10px] font-black text-slate-500 uppercase ml-4 tracking-[0.2em]">
                确认密码
              </label>
              <div className="relative group">
                <div className="absolute left-5 top-1/2 -translate-y-1/2 text-slate-500 group-focus-within:text-indigo-400 transition-colors">
                  <UserPlus size={18} />
                </div>
                <input
                  type="password"
                  required
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="再次输入密码"
                  className="w-full rounded-[1.4rem] border border-white/8 bg-white/[0.04] py-4 pl-14 pr-6 text-white font-bold outline-none transition-all placeholder:text-slate-600 focus:border-sky-300/30 focus:ring-2 focus:ring-sky-300/15"
                />
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-between px-2 pt-2 text-[11px] font-black uppercase text-slate-500 tracking-tighter">
              <label className="flex items-center gap-2 cursor-pointer hover:text-slate-300 transition-colors">
                <input type="checkbox" className="accent-indigo-500 w-4 h-4 rounded-md" />
                <span>记住我的身份</span>
              </label>
              <button
                type="button"
                onClick={handleForgotPassword}
                className="hover:text-indigo-400 transition-colors"
              >
                忘记密码？
              </button>
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="mt-8 flex w-full items-center justify-center gap-3 rounded-[1.5rem] bg-white py-4 font-black text-slate-950 shadow-[0_18px_34px_rgba(255,255,255,0.12)] transition hover:brightness-[1.02] disabled:opacity-50"
          >
            {loading ? (
              <div className="w-5 h-5 border-2 border-slate-900 border-t-transparent rounded-full animate-spin"></div>
            ) : (
              <>
                <span>{isRegister ? "创建心境账号" : "进入心境空间"}</span>
                <ArrowRight size={20} />
              </>
            )}
          </button>
          {error ? <p className="text-center text-[10px] font-bold text-rose-400 mt-2">{error}</p> : null}
        </form>

        <div className="mt-10 flex flex-col items-center">
          <div className="flex items-center gap-4 w-full mb-8">
            <div className="h-px bg-white/5 flex-1"></div>
            <span className="text-[9px] font-black text-slate-600 uppercase tracking-[0.3em]">
              其他接入方式
            </span>
            <div className="h-px bg-white/5 flex-1"></div>
          </div>
          <div className="flex gap-4">
            <button
              type="button"
              className="rounded-[1.35rem] border border-white/8 bg-white/[0.04] p-4 text-slate-400 transition-all hover:bg-white/[0.08] hover:text-white"
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
