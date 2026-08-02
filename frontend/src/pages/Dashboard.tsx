import { useEffect, useState } from "react";
import { getMetrics } from "../api/client";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import { Activity, AlertTriangle, MessageSquare, Zap } from "lucide-react";
import clsx from "clsx";

interface Metrics {
  total_questions: number;
  avg_latency_ms: number;
  total_tokens: number;
  pii_flagged_count: number;
  unsafe_flagged_count: number;
}

function StatCard({ label, value, icon: Icon, emphasis = false, tone = "stone", 'data-testid': testId }: {
  label: string;
  value: string | number;
  icon: React.ElementType;
  emphasis?: boolean;
  tone?: "stone" | "gold" | "amber";
  'data-testid'?: string;
}) {
  const iconTone = {
    stone: "bg-stone-900 text-white",
    gold: "bg-gold-50 text-gold-600",
    amber: "bg-amber-50 text-amber-600",
  }[tone];

  return (
    <div
      data-testid={testId}
      className={clsx(
        "rounded-2xl border border-stone-200/70 p-6 shadow-soft hover:shadow-elevated transition-shadow duration-300",
        emphasis ? "bg-stone-900" : "bg-white"
      )}
    >
      <div className={clsx("inline-flex p-2.5 rounded-xl mb-4", emphasis ? "bg-white/10 text-gold-300" : iconTone)}>
        <Icon size={18} strokeWidth={1.75} />
      </div>
      <p className={clsx(
        "font-display text-3xl font-semibold tracking-tight",
        emphasis ? "text-white" : "text-stone-900"
      )}>
        {value}
      </p>
      <p className={clsx("text-sm mt-1", emphasis ? "text-stone-400" : "text-stone-500")}>{label}</p>
    </div>
  );
}

export default function Dashboard() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getMetrics()
      .then((res) => setMetrics(res.data))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const chartData = metrics
    ? [
        { name: "Total Q&A", value: metrics.total_questions },
        { name: "PII Flagged", value: metrics.pii_flagged_count },
        { name: "Unsafe", value: metrics.unsafe_flagged_count },
      ]
    : [];

  return (
    <div className="p-8 max-w-6xl">
      <h2 className="font-display text-3xl font-semibold text-stone-900 tracking-tight mb-1">
        Monitoring Dashboard
      </h2>
      <p className="text-stone-500 text-sm mb-8">Real-time Q&A performance metrics</p>

      {loading ? (
        <p className="text-stone-400 text-sm">Loading metrics…</p>
      ) : metrics ? (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-5 mb-6">
            <StatCard
              label="Total Questions"
              value={metrics.total_questions.toLocaleString()}
              icon={MessageSquare}
              emphasis
              data-testid="stat-total-questions"
            />
            <StatCard
              label="Avg Latency (ms)"
              value={Math.round(metrics.avg_latency_ms).toLocaleString()}
              icon={Zap}
              tone="gold"
              data-testid="stat-avg-latency"
            />
            <StatCard
              label="PII Flags"
              value={metrics.pii_flagged_count}
              icon={AlertTriangle}
              tone="amber"
              data-testid="stat-pii-flags"
            />
            <StatCard
              label="Tokens Used"
              value={metrics.total_tokens.toLocaleString()}
              icon={Activity}
              tone="gold"
              data-testid="stat-tokens"
            />
          </div>

          <div className="bg-white rounded-2xl border border-stone-200/70 shadow-soft p-6">
            <h3 className="font-display text-lg font-semibold text-stone-900 mb-5">Activity Overview</h3>
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0eee9" vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 12, fill: "#78716c" }} axisLine={{ stroke: "#e7e5e4" }} tickLine={false} />
                <YAxis tick={{ fontSize: 12, fill: "#78716c" }} axisLine={false} tickLine={false} />
                <Tooltip
                  contentStyle={{ borderRadius: 10, border: "1px solid #e7e5e4", fontSize: 13 }}
                  cursor={{ fill: "#fafaf9" }}
                />
                <Bar dataKey="value" fill="#1c1917" radius={[6, 6, 0, 0]} maxBarSize={64} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </>
      ) : (
        <p data-testid="metrics-error" className="text-red-500 text-sm">Failed to load metrics.</p>
      )}
    </div>
  );
}
