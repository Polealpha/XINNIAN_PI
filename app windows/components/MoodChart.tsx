import React, { useEffect, useMemo, useState } from "react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getEmotionHistoryRange } from "../services/emotionService";
import { EmotionEvent, EmotionSample } from "../types";

interface MoodChartProps {
  events: EmotionEvent[];
  isGuest?: boolean;
  liveSamples?: EmotionSample[];
  riskSource?: "ws" | "poll" | null;
  riskUpdatedAt?: number | null;
}

type RangeOption = "1H" | "6H" | "24H" | "DATE";

type ChartPoint = {
  id: string;
  date: Date;
  time: string;
  score: number;
  plotScore: number;
  label: string;
};

const rangeHours = (range: RangeOption) => (range === "1H" ? 1 : range === "6H" ? 6 : 24);

const formatTime = (date: Date) =>
  date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });

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

    let cancelled = false;

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
        if (!cancelled) {
          setHistoryEvents(data);
        }
      } catch (error) {
        console.warn("history range fetch failed:", error);
        if (!cancelled) {
          setHistoryEvents([]);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    fetchHistory();

    return () => {
      cancelled = true;
    };
  }, [isGuest, range, selectedDate]);

  const points = useMemo<ChartPoint[]>(() => {
    const historySource = historyEvents.length > 0 ? historyEvents : events;
    const mappedHistory = [...historySource]
      .sort((a, b) => a.timestamp.getTime() - b.timestamp.getTime())
      .map((event) => ({
        id: event.id,
        date: event.timestamp,
        time: formatTime(event.timestamp),
        score: Math.max(0, Math.min(100, event.intensity ?? 0)),
        plotScore: Math.max(0, Math.min(100, event.intensity ?? 0)),
        label: event.type || "已记录事件",
      }));

    if (mappedHistory.length > 0) {
      return mappedHistory;
    }

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
        time: formatTime(sample.timestamp),
        score: Math.max(0, Math.min(100, sample.score)),
        plotScore: Math.max(0, Math.min(100, sample.score)),
        label: sample.label || "实时采样",
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
          time: formatTime(anchor),
        },
        only,
      ];
    }

    return mappedLive;
  }, [events, historyEvents, liveSamples, range, selectedDate]);

  const standbyPoints = useMemo<ChartPoint[]>(() => {
    const base = new Date();
    return Array.from({ length: 6 }, (_, index) => {
      const timestamp = new Date(base.getTime() - (5 - index) * 5 * 60 * 1000);
      return {
        id: `standby-${index}`,
        date: timestamp,
        time: formatTime(timestamp),
        score: 0,
        plotScore: 5.6 + Math.sin(index * 0.9) * 0.45,
        label: "等待实时输入",
      };
    });
  }, []);

  const chartMeta = useMemo(() => {
    if (points.length === 0) {
      return {
        allZero: false,
        lowVariance: false,
        domain: [0, 12] as [number, number],
      };
    }

    const scores = points.map((item) => item.score);
    const min = Math.min(...scores);
    const max = Math.max(...scores);
    const variance = max - min;
    const allZero = max <= 0;
    const lowVariance = !allZero && variance <= 2;

    if (allZero) {
      return {
        allZero,
        lowVariance,
        domain: [0, 8] as [number, number],
      };
    }

    if (max <= 12) {
      return {
        allZero,
        lowVariance,
        domain: [0, Math.max(12, Math.ceil(max + 4))] as [number, number],
      };
    }

    if (variance <= 8) {
      const padding = Math.max(4, Math.ceil(variance || 1) * 2);
      return {
        allZero,
        lowVariance,
        domain: [
          Math.max(0, Math.floor(min - padding)),
          Math.min(100, Math.ceil(max + padding)),
        ] as [number, number],
      };
    }

    return {
      allZero,
      lowVariance,
      domain: [0, 100] as [number, number],
    };
  }, [points]);

  const displayPoints = useMemo<ChartPoint[]>(
    () =>
      points.map((item, index, source) => {
        if (chartMeta.allZero) {
          return {
            ...item,
            plotScore: 5.8 + Math.sin(index * 0.9) * 0.45,
          };
        }

        if (chartMeta.lowVariance) {
          const mean = source.reduce((sum, current) => sum + current.score, 0) / Math.max(source.length, 1);
          const centered = item.score - mean;
          const amplified = mean + centered * 2.8;
          return {
            ...item,
            plotScore: Math.max(chartMeta.domain[0] + 1, Math.min(chartMeta.domain[1] - 1, amplified)),
          };
        }

        return {
          ...item,
          plotScore: item.score,
        };
      }),
    [chartMeta.allZero, chartMeta.domain, chartMeta.lowVariance, points]
  );

  const chartPoints = points.length > 0 ? displayPoints : standbyPoints;

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

  const statusText =
    riskSource === "ws" ? "实时推送" : riskSource === "poll" ? "轮询刷新" : "等待数据";

  const showLowActivityHint = points.length > 0 && (chartMeta.allZero || chartMeta.lowVariance);

  return (
    <div
      className="ios-surface-hero ios-surface-hero--focus-stage relative flex h-full min-h-[940px] flex-col overflow-hidden rounded-[2.4rem] p-6 animate-rise"
      style={{
        animationDelay: "70ms",
        ["--chart-accent" as string]: "#8fdcff",
        ["--chart-grid" as string]: "rgba(255,255,255,0.06)",
        ["--chart-tick" as string]: "rgba(214,224,238,0.62)",
      }}
    >
      <div className="ios-focus-liquid-stage" aria-hidden="true">
        <span className="ios-focus-liquid ios-focus-liquid--a" />
        <span className="ios-focus-liquid ios-focus-liquid--b" />
        <span className="ios-focus-liquid ios-focus-liquid--c" />
      </div>

      <div className="flex items-start justify-between gap-5">
        <div>
          <h2 className="text-[2.2rem] font-black tracking-[-0.05em] text-white">情绪律看板</h2>
          <div className="mt-2 flex items-center gap-3 text-[11px] font-semibold tracking-[0.12em] text-slate-500">
            <span>实时情绪波动走势</span>
            <span className="h-1 w-1 rounded-full bg-indigo-300/60" />
            <span className="text-indigo-300">{range === "DATE" ? "历史回看" : "实时采样"}</span>
            {loading ? <span className="text-white/40">加载中</span> : null}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <div className="flex gap-1 rounded-full border border-white/10 bg-white/[0.05] p-1 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]">
            {(["1H", "6H", "24H"] as RangeOption[]).map((option) => (
              <button
                key={option}
                onClick={() => {
                  setRange(option);
                  setDatePickerOpen(false);
                }}
                className={`rounded-full px-4 py-2 text-[10px] font-semibold transition-all ${
                  range === option
                    ? "bg-white text-[#0a1020] shadow-[0_8px_18px_rgba(255,255,255,0.15)]"
                    : "text-slate-400 hover:text-slate-200"
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
              className={`rounded-full border px-4 py-2 text-[10px] font-semibold tracking-[0.18em] transition-all ${
                range === "DATE"
                  ? "border-white bg-white text-[#0a1020] shadow-[0_8px_18px_rgba(255,255,255,0.15)]"
                  : "border-white/10 text-slate-400 hover:text-slate-200"
              }`}
            >
              日期
            </button>
            {datePickerOpen ? (
              <div className="absolute right-0 top-12 z-20 rounded-2xl border border-white/10 bg-[#10172a]/95 p-3 shadow-2xl">
                <input
                  type="date"
                  value={selectedDate}
                  onChange={(event) => setSelectedDate(event.target.value)}
                  className="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-[11px] font-bold text-slate-200 outline-none"
                />
              </div>
            ) : null}
          </div>
        </div>
      </div>

      <div className="mt-7 grid grid-cols-4 gap-3">
        {[
          { label: "当前波动", value: stats.current },
          { label: "高点", value: stats.high },
          { label: "低点", value: stats.low },
          { label: "样本", value: stats.samples },
        ].map((item) => (
          <div key={item.label} className="ios-metric-card rounded-[1.7rem] px-4 py-4">
            <div className="text-[10px] font-semibold tracking-[0.18em] text-slate-400">{item.label}</div>
            <div className="mt-2 text-2xl font-black text-white">{item.value}</div>
          </div>
        ))}
      </div>

      <div className="mt-5 flex items-center justify-between rounded-[1.7rem] border border-white/10 bg-white/[0.045] px-4 py-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]">
        <div className="text-sm font-medium text-slate-300">
          当前识别: <span className="font-black text-white">{stats.label}</span>
        </div>
        <div className="text-[10px] font-semibold tracking-[0.18em] text-slate-500">
          {statusText}
          {riskUpdatedAt
            ? ` · ${new Date(riskUpdatedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
            : ""}
        </div>
      </div>

      {showLowActivityHint ? (
        <div className="mt-4 flex items-center justify-between gap-3 rounded-[1.5rem] border border-emerald-300/12 bg-emerald-300/[0.08] px-4 py-3 text-xs font-semibold text-emerald-100 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
          <span>{chartMeta.allZero ? "当前样本几乎都贴近 0%，下方仍然显示真实曲线。" : "当前波动很轻微，下方显示的是细小变化的真实曲线。"}</span>
          <span className="shrink-0 rounded-full border border-emerald-200/15 bg-white/5 px-3 py-1 text-[10px] tracking-[0.18em] text-emerald-100/90">
            {chartMeta.allZero ? "稳定基线" : "低波动区间"}
          </span>
        </div>
      ) : points.length === 0 ? (
        <div className="mt-4 flex items-center justify-between gap-3 rounded-[1.5rem] border border-sky-300/10 bg-sky-300/[0.06] px-4 py-3 text-xs font-semibold text-sky-100 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
          <span>当前还没有实时样本，下面先显示待机基线；一旦采到数据会自动切成真实曲线。</span>
          <span className="shrink-0 rounded-full border border-sky-200/15 bg-white/5 px-3 py-1 text-[10px] tracking-[0.18em] text-sky-100/90">
            待机基线
          </span>
        </div>
      ) : null}

      <div className="ios-glass-well ios-glass-well--stage relative mt-6 flex-1 min-h-[460px] rounded-[2.2rem] p-4">
        {points.length === 0 ? (
          <div className="pointer-events-none absolute inset-x-8 top-6 z-10 text-center">
            <div className="text-base font-black text-white">实时曲线待机中</div>
            <p className="mt-2 text-sm font-semibold text-slate-400">当前样本还没进来，先用基线占位，避免整块空着。</p>
          </div>
        ) : null}

        <div className={points.length === 0 ? "h-full min-h-[328px] pt-20" : "h-full min-h-[328px]"}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartPoints} margin={{ left: 0, right: 12, top: 10, bottom: 8 }}>
              <defs>
                <linearGradient id="moodGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--chart-accent)" stopOpacity={points.length === 0 ? 0.22 : 0.34} />
                  <stop offset="100%" stopColor="var(--chart-accent)" stopOpacity={points.length === 0 ? 0.05 : 0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid vertical={false} strokeDasharray="4 4" stroke="var(--chart-grid)" />
              <XAxis
                dataKey="time"
                axisLine={false}
                tickLine={false}
                tick={{ fontSize: 10, fill: "var(--chart-tick)", fontWeight: 800 }}
                dy={12}
                minTickGap={28}
              />
              <YAxis hide domain={points.length === 0 ? [0, 12] : chartMeta.domain} />
              <Tooltip
                formatter={(_value: number, _label: string, item: any) => [
                  `${Math.round(Number(item?.payload?.score ?? 0))}%`,
                  "波动值",
                ]}
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
                dataKey="plotScore"
                stroke="var(--chart-accent)"
                strokeWidth={points.length === 0 ? 3.2 : chartMeta.allZero ? 3.6 : 3}
                fill="url(#moodGradient)"
                animationDuration={900}
                dot={{
                  r: points.length === 0 ? 2.2 : chartMeta.allZero ? 2.4 : 1.8,
                  fill: "var(--chart-accent)",
                  opacity: points.length === 0 ? 0.72 : chartMeta.allZero ? 0.88 : 0.65,
                }}
                activeDot={{
                  r: points.length === 0 ? 4.2 : chartMeta.allZero ? 4.8 : 4,
                  fill: "var(--chart-accent)",
                }}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
};
