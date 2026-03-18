
import React, { useEffect, useMemo, useState } from 'react';
import { AreaChart, Area, XAxis, Tooltip, ResponsiveContainer, CartesianGrid, YAxis } from 'recharts';
import { EmotionEvent } from '../types';
import { getEmotionHistoryRange } from '../services/emotionService';

interface MoodChartProps {
  events: EmotionEvent[];
  isGuest?: boolean;
}

type RangeOption = '1H' | '6H' | '24H' | 'DATE';

export const MoodChart: React.FC<MoodChartProps> = ({ events, isGuest }) => {
  const [range, setRange] = useState<RangeOption>('24H');
  const [historyEvents, setHistoryEvents] = useState<EmotionEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [datePickerOpen, setDatePickerOpen] = useState(false);
  const [selectedDate, setSelectedDate] = useState(() => {
    const today = new Date();
    return today.toISOString().slice(0, 10);
  });

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
        if (range === 'DATE') {
          const start = new Date(selectedDate);
          start.setHours(0, 0, 0, 0);
          const end = new Date(selectedDate);
          end.setHours(23, 59, 59, 999);
          startMs = start.getTime();
          endMs = end.getTime();
          limit = 1200;
        } else {
          const hours = range === '1H' ? 1 : range === '6H' ? 6 : 24;
          startMs = now - hours * 60 * 60 * 1000;
          endMs = now;
          limit = 600;
        }
        const data = await getEmotionHistoryRange({ startMs, endMs, limit });
        setHistoryEvents(data);
      } catch (err) {
        console.warn('history range fetch failed:', err);
        setHistoryEvents([]);
      } finally {
        setLoading(false);
      }
    };
    fetchHistory();
  }, [range, selectedDate, isGuest]);

  const data = useMemo(() => {
    const source = historyEvents.length > 0 ? historyEvents : events;
    const ordered = source.sort((a, b) => a.timestamp.getTime() - b.timestamp.getTime());
    return ordered.map(e => ({
      time: e.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      score: e.intensity || 50,
    }));
  }, [events, historyEvents]);

  return (
    <div className="w-full h-full bg-[#0c1222]/40 backdrop-blur-3xl rounded-[2.5rem] p-10 shadow-2xl border border-white/[0.05] relative overflow-hidden flex flex-col animate-pop-in" style={{animationDelay: '100ms'}}>
      <div className="flex justify-between items-center mb-10 relative z-10">
        <div>
            <h2 className="text-2xl font-black text-white tracking-tighter">{"\u60c5\u7eea\u97f5\u5f8b\u770b\u677f"}</h2>
            <div className="flex items-center gap-2 mt-1">
                <span className="text-slate-500 text-[9px] font-black uppercase tracking-[0.3em]">Temporal Emotional Dynamics</span>
                <span className="w-1 h-1 rounded-full" style={{ backgroundColor: "var(--chart-accent)", opacity: 0.5 }}></span>
                <span className="text-[9px] font-black uppercase tracking-widest" style={{ color: "var(--chart-accent)" }}>
                  {range === 'DATE' ? 'History' : 'Real-time'}
                </span>
                {loading && (
                  <span className="text-[9px] font-black uppercase tracking-widest text-white/40">加载中</span>
                )}
            </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex gap-2 bg-white/[0.03] p-1 rounded-full border border-white/[0.05]">
            {(['1H', '6H', '24H'] as RangeOption[]).map(option => (
                <button
                    key={option}
                    onClick={() => setRange(option)}
                    aria-pressed={range === option}
                    className={`px-5 py-2 rounded-full text-[9px] font-black transition-all ${
                      range === option ? 'bg-white text-[#070b14] shadow-lg' : 'text-slate-500 hover:text-slate-300'
                    }`}
                >
                    {option}
                </button>
            ))}
          </div>
          <div className="relative z-50">
            <button
              onClick={() => {
                setDatePickerOpen((prev) => !prev);
                setRange('DATE');
              }}
              className={`px-4 py-2 rounded-full text-[9px] font-black uppercase tracking-widest border transition-all ${
                range === 'DATE'
                  ? 'bg-white text-[#070b14] shadow-lg border-white'
                  : 'border-white/[0.1] text-slate-500 hover:text-slate-300'
              }`}
            >
              历史日期
            </button>
            {datePickerOpen && (
              <div className="absolute right-0 mt-2 z-50 bg-[#0c1222]/90 border border-white/[0.08] rounded-2xl p-3 shadow-2xl">
                <label className="text-[10px] font-black uppercase tracking-widest text-slate-400">
                  选择日期
                </label>
                <input
                  type="date"
                  value={selectedDate}
                  onChange={(e) => setSelectedDate(e.target.value)}
                  className="mt-2 w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-[11px] font-bold text-slate-200 outline-none"
                />
              </div>
            )}
          </div>
        </div>
      </div>
      
      <div className="flex-1 relative z-10 -ml-4">
        <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data}>
            <defs>
                <linearGradient id="colorMood" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--chart-accent)" stopOpacity={0.25}/>
                    <stop offset="95%" stopColor="var(--chart-accent)" stopOpacity={0}/>
                </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--chart-grid)" />
            <XAxis 
                dataKey="time" 
                axisLine={false} 
                tickLine={false} 
                tick={{fontSize: 9, fill: 'var(--chart-tick)', fontWeight: 900}} 
                dy={15}
            />
            <YAxis hide domain={[0, 100]} />
            <Tooltip 
                cursor={{ stroke: 'var(--chart-accent)', strokeWidth: 1, strokeDasharray: '4 4' }}
                contentStyle={{ 
                    borderRadius: '16px', 
                    border: '1px solid var(--chart-tooltip-border)', 
                    backgroundColor: 'var(--chart-tooltip-bg)',
                    backdropFilter: 'blur(20px)',
                    fontSize: '10px',
                    fontWeight: '900',
                    boxShadow: '0 20px 40px rgba(0,0,0,0.35)'
                }}
            />
            <Area 
                type="monotone" 
                dataKey="score" 
                stroke="var(--chart-accent)" 
                strokeWidth={3}
                fillOpacity={1} 
                fill="url(#colorMood)" 
                animationDuration={2000}
                dot={{ r: 2, fill: 'var(--chart-accent)', strokeWidth: 0, opacity: 0.5 }}
            />
            </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};
