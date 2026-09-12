import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Clock3, Coins, ExternalLink, FlaskConical, Route } from "lucide-react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Link } from "react-router-dom";
import { api, formatCost, formatDate, formatDuration, formatPercent, projectQuery } from "../api";
import { useApp } from "../app-context";
import { StatusBadge } from "../components/StatusBadge";
import { EmptyState, ErrorState, LoadingState, PageHeader } from "../components/UiStates";
import type { DashboardData } from "../types";

export function DashboardPage() {
  const { t, projectId } = useApp();
  const query = useQuery({
    queryKey: ["dashboard", projectId],
    queryFn: () => api<DashboardData>(`/dashboard${projectQuery(projectId)}`),
    enabled: Boolean(projectId),
    refetchInterval: 10000,
  });
  if (!projectId || query.isLoading) return <LoadingState />;
  if (query.error) return <ErrorState error={query.error} />;
  const data = query.data!;
  const stats = [
    [t("passRate"), formatPercent(data.overall_pass_rate), CheckCircle2, "success"],
    [t("gateFailures"), String(data.gate_failure_count), AlertTriangle, data.gate_failure_count ? "danger" : "neutral"],
    [t("p95Latency"), formatDuration(data.p95_active_runtime_ms), Clock3, "cyan"],
    [t("averageCost"), formatCost(data.average_known_cost), Coins, "neutral"],
  ] as const;
  return (
    <div className="page-stack">
      <PageHeader title={t("dashboard")} subtitle={`${data.trace_count} normalized runs`} />
      <section className="stat-grid">
        {stats.map(([label, value, Icon, tone]) => <article className={`stat-card ${tone}`} key={label}><div><span>{label}</span><strong>{value}</strong></div><Icon size={20} /></article>)}
      </section>
      <section className="dashboard-grid">
        <article className="panel chart-panel">
          <div className="panel-heading"><div><h2>{t("runTrend")}</h2><span>Pass rate and run volume</span></div><Route size={17} /></div>
          {data.trend.length ? (
            <div className="chart-wrap">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={data.trend} margin={{ left: -18, right: 10, top: 10, bottom: 0 }}>
                  <CartesianGrid stroke="var(--line)" vertical={false} />
                  <XAxis dataKey="date" tick={{ fill: "var(--muted)", fontSize: 11 }} axisLine={false} tickLine={false} />
                  <YAxis domain={[0, 1]} tickFormatter={(value) => `${value * 100}%`} tick={{ fill: "var(--muted)", fontSize: 11 }} axisLine={false} tickLine={false} />
                  <Tooltip contentStyle={{ background: "var(--surface-raised)", border: "1px solid var(--line)", borderRadius: 4 }} formatter={(value) => formatPercent(Number(value))} />
                  <Area type="monotone" dataKey="pass_rate" stroke="var(--cyan)" fill="var(--cyan-soft)" strokeWidth={2} connectNulls />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          ) : <EmptyState />}
        </article>
        <article className="panel">
          <div className="panel-heading"><div><h2>{t("failureReasons")}</h2><span>Declared gate failures</span></div><AlertTriangle size={17} /></div>
          <div className="rank-list">
            {data.failure_reasons.length ? data.failure_reasons.slice(0, 8).map((row, index) => (
              <div className="rank-row" key={row.metric_id}><span className="rank-index">{index + 1}</span><code>{row.metric_id}</code><strong>{row.count}</strong></div>
            )) : <EmptyState />}
          </div>
        </article>
      </section>
      <section className="dashboard-grid lower">
        <article className="panel">
          <div className="panel-heading"><div><h2>{t("recentExperiments")}</h2><span>Version-pinned suites</span></div><FlaskConical size={17} /></div>
          <div className="compact-list">
            {data.recent_experiments.length ? data.recent_experiments.map((item) => (
              <Link to={`/experiments?selected=${encodeURIComponent(item.experiment_id)}`} key={item.experiment_id} className="compact-row">
                <div><strong>{item.name}</strong><span>{item.completed_runs}/{item.total_runs} runs</span></div><StatusBadge value={item.status} />
              </Link>
            )) : <EmptyState />}
          </div>
        </article>
        <article className="panel">
          <div className="panel-heading"><div><h2>{t("recentTraces")}</h2><span>Latest normalized evidence</span></div><ExternalLink size={17} /></div>
          <div className="compact-list">
            {data.recent_traces.length ? data.recent_traces.map((item) => (
              <Link to={`/traces/${encodeURIComponent(item.trace_id)}`} key={item.trace_id} className="compact-row">
                <div><strong>{item.case_id || item.trace_id}</strong><span>{formatDate(item.started_at)}</span></div><StatusBadge value={item.overall_pass} />
              </Link>
            )) : <EmptyState />}
          </div>
        </article>
      </section>
      <section className="panel">
        <div className="panel-heading"><div><h2>{t("metricHealth")}</h2><span>N/A excluded from applicable runs</span></div></div>
        <div className="table-scroll"><table><thead><tr><th>{t("metric")}</th><th>{t("group")}</th><th>Applicable</th><th>{t("passRate")}</th><th>Average</th></tr></thead><tbody>
          {data.metric_health.slice(0, 12).map((row) => <tr key={row.metric_id}><td><code>{row.metric_id}</code></td><td>{row.group}</td><td>{row.applicable}</td><td>{formatPercent(row.pass_rate)}</td><td>{row.average == null ? "N/A" : row.average.toFixed(3)}</td></tr>)}
        </tbody></table></div>
      </section>
    </div>
  );
}
