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
        time: event.timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
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
        time: sample.timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
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
          time: anchor.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        },
        only,
      ];
    }

    return mappedLive;
  }, [events, historyEvents, liveSamples, range, selectedDate]);

  const chartMeta = useMemo(() => {
    if (points.length === 0) {
      return {
        allZero: false,
        lowVariance: false,
        domain: [0, 100] as [number, number],
      };
    }

    const scores = points.map((item) => item.score);
    const min = Math.min(...scores);
    const max = Math.max(...scores);
    const rangeValue = max - min;
    const allZero = max <= 0;
    const lowVariance = !allZero && rangeValue <= 2;

    if (allZero) {
      return {
        allZero,
        lowVariance,
        domain: [0, 12] as [number, number],
      };
    }

    if (max <= 12) {
      return {
        allZero,
        lowVariance,
        domain: [0, Math.max(12, Math.ceil(max + 4))] as [number, number],
      };
    }

    if (rangeValue <= 8) {
      const padding = Math.max(4, Math.ceil(rangeValue || 1) * 2);
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
      points.map((item) => ({
        ...item,
        plotScore: chartMeta.allZero ? 4 : item.score,
      })),
    [chartMeta.allZero, points]
  );

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

  const lowActivityItems = useMemo(
    () =>
      displayPoints.slice(-6).map((item, index, source) => {
        const ratio = source.length === 1 ? 1 : index / (source.length - 1);
        const normalized = Math.max(0, Math.min(1, item.plotScore / chartMeta.domain[1]));
        const top = Math.max(16, Math.min(74, 76 - normalized * 52));
        return {
          ...item,
          left: ratio * 100,
          top,
          height: Math.max(10, 18 + normalized * 56),
        };
      }),
    [chartMeta.domain, displayPoints]
  );

  const statusText =
    riskSource === "ws" ? "实时推送" : riskSource === "poll" ? "轮询刷新" : "等待数据";

  const isLowActivity = points.length > 0 && (chartMeta.allZero || chartMeta.lowVariance);

  return (
    <div
      className="ios-surface-hero ios-surface-hero--focus-stage relative flex h-full min-h-[760px] flex-col overflow-hidden rounded-[2.4rem] p-6 animate-rise"
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
            {loading && <span className="text-white/40">加载中</span>}
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
            {datePickerOpen && (
              <div className="absolute right-0 top-12 z-20 rounded-2xl border border-white/10 bg-[#10172a]/95 p-3 shadow-2xl">
                <input
                  type="date"
                  value={selectedDate}
                  onChange={(event) => setSelectedDate(event.target.value)}
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
          <div key={item.label} className="ios-metric-card rounded-[1.7rem] px-4 py-4">
            <div className="text-[10px] font-semibold tracking-[0.18em] text-slate-400">{item.label}</div>
            <div className="mt-2 text-2xl font-black text-white">{item.value}</div>
          </div>
        ))}
      </div>

      <div className="mt-5 flex items-center justify-between rounded-[1.7rem] border border-white/10 bg-white/[0.045] px-4 py-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]">
        <div className="text-sm font-medium text-slate-300">
          当前识别：<span className="font-black text-white">{stats.label}</span>
        </div>
        <div className="text-[10px] font-semibold tracking-[0.18em] text-slate-500">
          {statusText}
          {riskUpdatedAt
            ? ` · ${new Date(riskUpdatedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
            : ""}
        </div>
      </div>

      <div className="relative mt-6 flex-1 min-h-[360px] rounded-[2.2rem] border border-white/10 bg-[linear-gradient(180deg,rgba(255,255,255,0.045),rgba(255,255,255,0.015))] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]">
        {points.length === 0 ? (
          <div className="flex h-full items-center justify-center text-center">
            <div>
              <div className="text-lg font-black text-white">实时曲线等待中</div>
              <p className="mt-3 max-w-md text-sm font-semibold leading-7 text-slate-400">
                当还没有足够的历史数据时，这里会自动使用实时采样补齐，不会再整块空着。
              </p>
            </div>
          </div>
        ) : isLowActivity ? (
          <div className="flex h-full min-h-[328px] flex-col gap-4">
            <div className="relative flex-1 overflow-hidden rounded-[1.9rem] border border-white/10 bg-[linear-gradient(180deg,rgba(13,19,33,0.88),rgba(8,12,22,0.96))] px-5 py-5">
              <div className="absolute inset-0 opacity-70">
                {[18, 36, 54, 72].map((offset) => (
                  <div
                    key={offset}
                    className="absolute left-0 right-0 border-t border-dashed border-white/6"
                    style={{ top: `${offset}%` }}
                  />
                ))}
              </div>
              <div className="relative z-10 flex items-start justify-between gap-6">
                <div>
                  <div className="inline-flex items-center gap-2 rounded-full border border-emerald-400/15 bg-emerald-400/10 px-3 py-1 text-[10px] font-black tracking-[0.18em] text-emerald-200">
                    {chartMeta.allZero ? "稳定基线" : "低波动区间"}
                  </div>
                  <div className="mt-4 text-[1.7rem] font-black tracking-[-0.04em] text-white">
                    {chartMeta.allZero ? "当前情绪很稳定" : "当前波动很轻微"}
                  </div>
                  <p className="mt-3 max-w-[24rem] text-sm font-semibold leading-7 text-slate-300">
                    {chartMeta.allZero
                      ? "已经持续收到实时样本，只是这些样本几乎都贴近 0%。这里改成稳定态展示，不再让你看到一整块空白。"
                      : "最近这段时间有变化，但幅度很小。我们把这块切成低波动态，方便你直接看细微起伏。"}
                  </p>
                </div>
                <div className="rounded-[1.4rem] border border-white/10 bg-white/[0.04] px-4 py-3 text-right shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]">
                  <div className="text-[10px] font-semibold tracking-[0.18em] text-slate-400">最近刷新</div>
                  <div className="mt-2 text-lg font-black text-white">
                    {riskUpdatedAt
                      ? new Date(riskUpdatedAt).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                        })
                      : "--:--"}
                  </div>
                </div>
              </div>

              <div className="relative z-10 mt-8 h-[12.8rem] overflow-hidden rounded-[1.7rem] border border-white/10 bg-[linear-gradient(180deg,rgba(255,255,255,0.025),rgba(255,255,255,0.01))] px-4 py-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
                <div className="absolute left-4 right-4 top-[74%] h-[2px] rounded-full bg-[linear-gradient(90deg,rgba(96,165,250,0.16),rgba(96,165,250,0.8),rgba(56,189,248,0.22))]" />
                {lowActivityItems.map((item) => (
                  <React.Fragment key={item.id}>
                    <div
                      className="absolute bottom-[26%] w-[12px] -translate-x-1/2 rounded-full bg-[linear-gradient(180deg,rgba(125,211,252,0.95),rgba(99,102,241,0.88))] shadow-[0_0_0_4px_rgba(59,130,246,0.08),0_12px_26px_rgba(37,99,235,0.18)]"
                      style={{
                        left: `${item.left}%`,
                        height: `${item.height}px`,
                      }}
                    />
                    <div
                      className="absolute h-[10px] w-[10px] -translate-x-1/2 rounded-full border border-white/30 bg-[var(--chart-accent)] shadow-[0_0_0_6px_rgba(59,130,246,0.08),0_0_18px_rgba(96,165,250,0.24)]"
                      style={{
                        left: `${item.left}%`,
                        top: `${item.top}%`,
                      }}
                    />
                  </React.Fragment>
                ))}
                <div className="absolute inset-x-4 bottom-3 flex items-center justify-between text-[10px] font-semibold tracking-[0.1em] text-slate-500">
                  {lowActivityItems.map((item) => (
                    <span key={`${item.id}-time`}>{item.time}</span>
                  ))}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-3 gap-3">
              <div className="rounded-[1.5rem] border border-white/10 bg-white/[0.04] px-4 py-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
                <div className="text-[10px] font-semibold tracking-[0.18em] text-slate-400">样本同步</div>
                <div className="mt-2 text-[1.45rem] font-black text-white">{stats.samples}</div>
                <div className="mt-2 text-xs font-semibold leading-6 text-slate-400">最近一段时间的实时采样已经连上。</div>
              </div>
              <div className="rounded-[1.5rem] border border-white/10 bg-white/[0.04] px-4 py-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
                <div className="text-[10px] font-semibold tracking-[0.18em] text-slate-400">当前判断</div>
                <div className="mt-2 text-[1.45rem] font-black text-white">{stats.label}</div>
                <div className="mt-2 text-xs font-semibold leading-6 text-slate-400">当前波动值 {stats.current}，整体接近稳定区间。</div>
              </div>
              <div className="rounded-[1.5rem] border border-white/10 bg-white/[0.04] px-4 py-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
                <div className="text-[10px] font-semibold tracking-[0.18em] text-slate-400">当前建议</div>
                <div className="mt-2 text-[1.1rem] font-black text-white">保持观察</div>
                <div className="mt-2 text-xs font-semibold leading-6 text-slate-400">
                  {chartMeta.allZero ? "暂时不需要额外提醒，继续采样即可。" : "可以继续观察几分钟，等变化更明显时再判断。"}
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="h-full min-h-[328px]">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={displayPoints} margin={{ left: 0, right: 12, top: 10, bottom: 8 }}>
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
                  minTickGap={28}
                />
                <YAxis hide domain={chartMeta.domain} />
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
                  strokeWidth={3}
                  fill="url(#moodGradient)"
                  animationDuration={900}
                  dot={{ r: 1.8, fill: "var(--chart-accent)", opacity: 0.65 }}
                  activeDot={{ r: 4, fill: "var(--chart-accent)" }}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  );
};
