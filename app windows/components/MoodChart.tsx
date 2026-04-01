import React, { useEffect, useMemo, useState } from "react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { EmotionEvent, EmotionSample } from "../types";
import { getEmotionHistoryRange } from "../services/emotionService";

interface MoodChartProps {
  events: EmotionEvent[];
  isGuest?: boolean;
  liveSamples?: EmotionSample[];
  riskSource?: "ws" | "poll" | null;
  riskUpdatedAt?: number | null;
}

type RangeOption = "1H" | "6H" | "24H" | "DATE";

const rangeHours = (range: RangeOption) => (range === "1H" ? 1 : range === "6H" ? 6 : 24);

export const MoodChart: React.FC<MoodChartProps> = ({
  events,
  isGuest,
  liveSamples = [],
  riskSource,
  riskUpdatedAt,
}) => {
  const [range, setRange] = useState<RangeOption>("24H");
  const [historyEvents, setHistoryEvents] = useState<EmotionEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [datePickerOpen, setDatePickerOpen] = useState(false);
  const [selectedDate, setSelectedDate] = useState(() => new Date().toISOString().slice(0, 10));

  useEffect(() => {
    if (isGuest) {
      setHistoryEvents([]);
      return;
    }
    const fetchHistory = async () => {
      setLoading(true);
      try {
        const now = Date.now();
        let startMs: number | undefined;
        let endMs: number | undefined;
        let limit = 500;
        if (range === "DATE") {
          const start = new Date(selectedDate);
          start.setHours(0, 0, 0, 0);
          const end = new Date(selectedDate);
          end.setHours(23, 59, 59, 999);
          startMs = start.getTime();
          endMs = end.getTime();
          limit = 1200;
        } else {
          const hours = rangeHours(range);
          startMs = now - hours * 60 * 60 * 1000;
          endMs = now;
          limit = 600;
        }
        const data = await getEmotionHistoryRange({ startMs, endMs, limit });
        setHistoryEvents(data);
      } catch (err) {
        console.warn("history range fetch failed:", err);
        setHistoryEvents([]);
      } finally {
        setLoading(false);
      }
    };
    fetchHistory();
  }, [isGuest, range, selectedDate]);

  const points = useMemo(() => {
    const historySource = historyEvents.length > 0 ? historyEvents : events;
    const mappedHistory = [...historySource]
      .sort((a, b) => a.timestamp.getTime() - b.timestamp.getTime())
      .map((event) => ({
        id: event.id,
        date: event.timestamp,
        time: event.timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        score: event.intensity || 50,
        label: event.type,
      }));
    if (mappedHistory.length > 0) return mappedHistory;

    const now = Date.now();
    const mappedLive = liveSamples
      .filter((sample) =>
        range === "DATE"
          ? sample.timestamp.toISOString().slice(0, 10) === selectedDate
          : sample.timestamp.getTime() >= now - rangeHours(range) * 60 * 60 * 1000
      )
      .map((sample) => ({
        id: sample.id,
        date: sample.timestamp,
        time: sample.timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        score: sample.score,
        label: sample.label,
      }))
      .sort((a, b) => a.date.getTime() - b.date.getTime());

    if (mappedLive.length === 1) {
      const only = mappedLive[0];
      const anchor = new Date(only.date.getTime() - 5 * 60 * 1000);
      return [
        {
          ...only,
          id: `${only.id}-anchor`,
          date: anchor,
          time: anchor.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        },
        only,
      ];
    }
    return mappedLive;
  }, [events, historyEvents, liveSamples, range, selectedDate]);

  const stats = useMemo(() => {
    if (points.length === 0) {
      return { current: "--", high: "--", low: "--", samples: "0", label: "等待实时输入" };
    }
    const scores = points.map((item) => item.score);
    const latest = points[points.length - 1];
    return {
      current: `${Math.round(latest.score)}%`,
      high: `${Math.round(Math.max(...scores))}%`,
      low: `${Math.round(Math.min(...scores))}%`,
      samples: String(points.length),
      label: latest.label || "实时波动",
    };
  }, [points]);

  return (
    <div className="h-full min-h-[760px] rounded-[2.35rem] border border-white/5 bg-[linear-gradient(180deg,rgba(12,18,34,0.86),rgba(10,14,28,0.78))] backdrop-blur-3xl p-7 shadow-2xl flex flex-col overflow-hidden">
      <div className="flex items-start justify-between gap-5">
        <div>
          <h2 className="text-[2rem] font-black tracking-tight text-white">情绪韵律看板</h2>
          <div className="mt-2 flex items-center gap-3 text-[10px] font-black uppercase tracking-[0.28em] text-slate-500">
            <span>Temporal Emotional Dynamics</span>
            <span className="h-1 w-1 rounded-full bg-indigo-300/60" />
            <span className="text-indigo-300">{range === "DATE" ? "History" : "Real-time"}</span>
            {loading && <span className="text-white/40">加载中</span>}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex gap-1 rounded-full border border-white/6 bg-white/[0.03] p-1">
            {(["1H", "6H", "24H"] as RangeOption[]).map((option) => (
              <button
                key={option}
                onClick={() => {
                  setRange(option);
                  setDatePickerOpen(false);
                }}
                className={`rounded-full px-4 py-2 text-[10px] font-black transition-all ${
                  range === option ? "bg-white text-[#0a1020]" : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {option}
              </button>
            ))}
          </div>
          <div className="relative">
            <button
              onClick={() => {
                setDatePickerOpen((prev) => !prev);
                setRange("DATE");
              }}
              className={`rounded-full border px-4 py-2 text-[10px] font-black uppercase tracking-[0.22em] transition-all ${
                range === "DATE" ? "border-white bg-white text-[#0a1020]" : "border-white/10 text-slate-400 hover:text-slate-200"
              }`}
            >
              日期
            </button>
            {datePickerOpen && (
              <div className="absolute right-0 top-12 z-20 rounded-2xl border border-white/10 bg-[#10172a]/95 p-3 shadow-2xl">
                <input
                  type="date"
                  value={selectedDate}
                  onChange={(e) => setSelectedDate(e.target.value)}
                  className="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-[11px] font-bold text-slate-200 outline-none"
                />
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="mt-7 grid grid-cols-4 gap-3">
        {[
          { label: "当前波动", value: stats.current },
          { label: "最高点", value: stats.high },
          { label: "最低点", value: stats.low },
          { label: "样本数", value: stats.samples },
        ].map((item) => (
          <div key={item.label} className="rounded-[1.45rem] border border-white/6 bg-white/[0.03] px-4 py-4">
            <div className="text-[10px] font-black uppercase tracking-[0.24em] text-slate-500">{item.label}</div>
            <div className="mt-2 text-2xl font-black text-white">{item.value}</div>
          </div>
        ))}
      </div>

      <div className="mt-5 flex items-center justify-between rounded-[1.5rem] border border-white/6 bg-white/[0.025] px-4 py-3">
        <div className="text-sm font-semibold text-slate-300">
          当前识别：<span className="font-black text-white">{stats.label}</span>
        </div>
        <div className="text-[10px] font-black uppercase tracking-[0.24em] text-slate-500">
          {riskSource === "ws" ? "WS LIVE" : riskSource === "poll" ? "POLLING" : "STANDBY"}
          {riskUpdatedAt
            ? ` · ${new Date(riskUpdatedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
            : ""}
        </div>
      </div>

      <div className="mt-6 flex-1 min-h-[360px] rounded-[2rem] border border-white/6 bg-[linear-gradient(180deg,rgba(255,255,255,0.03),rgba(255,255,255,0.01))] p-4">
        {points.length === 0 ? (
          <div className="flex h-full items-center justify-center text-center">
            <div>
              <div className="text-lg font-black text-white">实时曲线等待中</div>
              <p className="mt-3 max-w-md text-sm font-semibold leading-7 text-slate-400">
                没有历史数据时，这里会自动使用实时采样补图，不再整块空着。
              </p>
            </div>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={points} margin={{ left: 0, right: 12, top: 10, bottom: 8 }}>
              <defs>
                <linearGradient id="moodGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--chart-accent)" stopOpacity={0.34} />
                  <stop offset="100%" stopColor="var(--chart-accent)" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid vertical={false} strokeDasharray="4 4" stroke="var(--chart-grid)" />
              <XAxis
                dataKey="time"
                axisLine={false}
                tickLine={false}
                tick={{ fontSize: 10, fill: "var(--chart-tick)", fontWeight: 800 }}
                dy={12}
              />
              <YAxis hide domain={[0, 100]} />
              <Tooltip
                formatter={(value: number) => [`${Math.round(Number(value))}%`, "波动值"]}
                labelFormatter={(value) => `时间 ${value}`}
                cursor={{ stroke: "var(--chart-accent)", strokeWidth: 1, strokeDasharray: "4 4" }}
                contentStyle={{
                  borderRadius: "18px",
                  border: "1px solid rgba(255,255,255,0.08)",
                  backgroundColor: "rgba(8,12,23,0.94)",
                  backdropFilter: "blur(20px)",
                  fontSize: "10px",
                  fontWeight: "900",
                }}
              />
              <Area
                type="monotone"
                dataKey="score"
                stroke="var(--chart-accent)"
                strokeWidth={3}
                fill="url(#moodGradient)"
                animationDuration={900}
                dot={{ r: 1.8, fill: "var(--chart-accent)", opacity: 0.65 }}
                activeDot={{ r: 4, fill: "var(--chart-accent)" }}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
};
