import { useEffect, useState } from "react";
import { getMetrics } from "../api/client";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import { Activity, AlertTriangle, MessageSquare, Zap } from "lucide-react";

interface Metrics {
  total_questions: number;
  avg_latency_ms: number;
  total_tokens: number;
  pii_flagged_count: number;
  unsafe_flagged_count: number;
}

function StatCard({ label, value, icon: Icon, color }: {
  label: string; value: string | number; icon: React.ElementType; color: string;
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 flex items-center gap-4">
      <div className={`p-3 rounded-lg ${color}`}>
        <Icon size={20} className="text-white" />
      </div>
      <div>
        <p className="text-2xl font-bold text-gray-800">{value}</p>
        <p className="text-sm text-gray-500">{label}</p>
      </div>
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
    <div className="p-8">
      <h2 className="text-2xl font-bold text-gray-800 mb-1">Monitoring Dashboard</h2>
      <p className="text-gray-500 text-sm mb-6">Real-time Q&A performance metrics</p>

      {loading ? (
        <p className="text-gray-400">Loading metrics…</p>
      ) : metrics ? (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <StatCard
              label="Total Questions"
              value={metrics.total_questions.toLocaleString()}
              icon={MessageSquare}
              color="bg-blue-500"
            />
            <StatCard
              label="Avg Latency (ms)"
              value={Math.round(metrics.avg_latency_ms).toLocaleString()}
              icon={Zap}
              color="bg-green-500"
            />
            <StatCard
              label="PII Flags"
              value={metrics.pii_flagged_count}
              icon={AlertTriangle}
              color="bg-yellow-500"
            />
            <StatCard
              label="Tokens Used"
              value={metrics.total_tokens.toLocaleString()}
              icon={Activity}
              color="bg-purple-500"
            />
          </div>

          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <h3 className="text-base font-semibold text-gray-700 mb-4">Activity Overview</h3>
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip />
                <Bar dataKey="value" fill="#3b82f6" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </>
      ) : (
        <p className="text-red-400">Failed to load metrics.</p>
      )}
    </div>
  );
}
