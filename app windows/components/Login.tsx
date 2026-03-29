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
    <div className="min-h-screen flex items-center justify-center p-6 relative overflow-hidden">
      <div className="w-full max-w-md bg-slate-900/60 backdrop-blur-3xl border border-white/10 rounded-[3rem] p-10 shadow-2xl animate-pop-in relative z-10">
        <div className="flex flex-col items-center mb-10">
          <div className="w-20 h-20 rounded-3xl flex items-center justify-center text-white mb-6 shadow-xl shadow-black/10 rotate-12 animate-float overflow-hidden">
            <img src={appIcon} alt="app icon" className="w-full h-full object-cover" />
          </div>
          <h1 className="text-3xl font-black text-white tracking-tight">共鸣连接</h1>
          <p className="text-slate-400 font-bold text-sm mt-2 uppercase tracking-widest">
            感知情绪 · 连接伙伴
          </p>
        </div>

        <div className="flex items-center gap-2 bg-white/5 p-2 rounded-full border border-white/10 mb-6">
          <button
            type="button"
            onClick={() => setMode("login")}
            className={`flex-1 py-2 rounded-full text-xs font-black uppercase tracking-[0.2em] transition-all ${
              mode === "login" ? "bg-white text-slate-950" : "text-slate-400"
            }`}
          >
            登录
          </button>
          <button
            type="button"
            onClick={() => setMode("register")}
            className={`flex-1 py-2 rounded-full text-xs font-black uppercase tracking-[0.2em] transition-all ${
              mode === "register" ? "bg-white text-slate-950" : "text-slate-400"
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
                className="w-full bg-slate-800/50 border border-white/5 rounded-2xl py-4 pl-14 pr-6 text-white font-bold outline-none focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500/50 transition-all placeholder:text-slate-600"
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
                className="w-full bg-slate-800/50 border border-white/5 rounded-2xl py-4 pl-14 pr-6 text-white font-bold outline-none focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500/50 transition-all placeholder:text-slate-600"
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
                  className="w-full bg-slate-800/50 border border-white/5 rounded-2xl py-4 pl-14 pr-6 text-white font-bold outline-none focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500/50 transition-all placeholder:text-slate-600"
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
            className="w-full bg-white text-slate-950 font-black py-4 rounded-2xl mt-8 q-bounce flex items-center justify-center gap-3 shadow-xl hover:shadow-white/10 disabled:opacity-50"
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
              className="p-4 bg-white/5 rounded-2xl border border-white/5 text-slate-400 hover:text-white hover:bg-white/10 transition-all q-bounce"
            >
              <Github size={20} />
            </button>
          </div>
        </div>
      </div>

      <div className="absolute top-1/4 -left-20 w-80 h-80 bg-indigo-600/20 blur-[120px] rounded-full"></div>
      <div className="absolute bottom-1/4 -right-20 w-80 h-80 bg-fuchsia-600/20 blur-[120px] rounded-full"></div>
    </div>
  );
};
