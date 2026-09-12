import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Bot, Braces, CheckCircle2, CircleDot, FileCheck2, Gauge, GitBranch, Hand, KeyRound, MessageSquare, Search, ShieldCheck, Wrench } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, formatCost, formatDate, formatDuration } from "../api";
import { useApp } from "../app-context";
import { EvaluateTrace } from "../components/EvaluateTrace";
import { BusinessAcceptance, BusinessEvidenceSource, BusinessVerdict, cannotVerify } from "../components/BusinessAcceptance";
import { ModelInputs, ArtifactEvidence } from "../components/ModelInputs";
import { StatusBadge } from "../components/StatusBadge";
import { EmptyState, ErrorState, LoadingState } from "../components/UiStates";
import type { GateResult, MetricResult, TraceDetail, TraceEvent } from "../types";

const tabKeys = ["overview", "timeline", "tools", "parameters", "interactions", "context", "evidence", "metrics", "rawJson"] as const;
type Tab = typeof tabKeys[number];

function eventIcon(kind: string) {
  if (kind.startsWith("model")) return Bot;
  if (kind.startsWith("tool")) return Wrench;
  if (kind.startsWith("guard")) return ShieldCheck;
  if (kind.startsWith("parameter")) return KeyRound;
  if (kind.startsWith("interaction")) return Hand;
  if (kind.startsWith("retrieval") || kind.startsWith("memory") || kind.startsWith("context")) return Search;
  if (kind.startsWith("final")) return FileCheck2;
  return CircleDot;
}

function eventTone(status: string) { return status === "error" || status === "blocked" ? "danger" : status === "pending" ? "warning" : "success"; }

export function RunDetailPage() {
  const { t, language } = useApp();
  const { traceId = "" } = useParams();
  const [tab, setTab] = useState<Tab>("overview");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const query = useQuery({ queryKey: ["trace", traceId], queryFn: () => api<TraceDetail>(`/traces/${encodeURIComponent(traceId)}`), enabled: Boolean(traceId) });
  const selected = useMemo(() => query.data?.trace.events.find((event) => event.event_id === selectedId) || null, [query.data, selectedId]);
  if (query.isLoading) return <LoadingState />;
  if (query.error) return <ErrorState error={query.error} />;
  const data = query.data!;
  const businessMetric = data.metrics.find(metric => metric.metric_id === "business_acceptance_pass");
  return (
    <div className="run-page">
      <header className="run-header">
        <Link className="back-link" to="/traces"><ArrowLeft size={16} />{t("traces")}</Link>
        <div className="run-title-row"><div><div className="eyebrow">{data.trace.case_id || "Ad hoc run"}</div><h1>{data.trace.trace_id}</h1></div><div className="run-statuses"><EvaluateTrace traceId={traceId} projectId={data.trace.project_id} />{businessMetric && cannotVerify(businessMetric) ? <BusinessVerdict status="error" reasonCode={businessMetric.reason_code} /> : <StatusBadge value={data.overall_pass} />}<StatusBadge value={data.trace.status} /></div></div>
        <div className="run-meta"><span><strong>{t("target")}</strong>{data.trace.target_id} · v{data.trace.target_version}</span><span><strong>{t("started")}</strong>{formatDate(data.trace.started_at)}</span><span><strong>Experiment</strong>{data.trace.experiment_id || "Imported"}</span></div>
      </header>
      <div className="run-workspace">
        <aside className="event-rail">
          <div className="rail-heading"><GitBranch size={16} /><strong>{t("timeline")}</strong><span>{data.trace.events.length}</span></div>
          <div className="event-tree">{data.trace.events.map((event) => { const Icon = eventIcon(event.kind); return <button key={event.event_id} className={`event-node ${selectedId === event.event_id ? "selected" : ""}`} onClick={() => setSelectedId(event.event_id)}><span className={`event-icon ${eventTone(event.status)}`}><Icon size={14} /></span><div><strong>{event.name || event.kind}</strong><small>#{event.sequence} · {event.kind}</small></div></button>; })}</div>
          <div className="event-inspector"><div className="rail-heading"><Braces size={15} /><strong>{t("eventInspector")}</strong></div>{selected ? <><dl className="kv-list"><div><dt>ID</dt><dd>{selected.event_id}</dd></div><div><dt>{t("type")}</dt><dd>{selected.kind}</dd></div><div><dt>{t("status")}</dt><dd><StatusBadge value={selected.status} /></dd></div></dl><pre className="json-view compact">{JSON.stringify(selected.attributes, null, 2)}</pre></> : <span className="muted-text">{t("selectEvent")}</span>}</div>
        </aside>
        <section className="run-body">
          <div className="tabs" role="tablist">{tabKeys.map((key) => <button role="tab" aria-selected={tab === key} className={tab === key ? "active" : ""} onClick={() => setTab(key)} key={key}>{t(key)}</button>)}</div>
          <div className="tab-content">
            {tab === "overview" ? <>{data.trace.metadata.reference_fixture ? <div className="reference-banner"><FileCheck2 size={18} />{t("referenceFixture") === "referenceFixture" ? "Reference fixture · not an Agent score" : t("referenceFixture")}</div> : data.trace.metadata.actor === "reference_policy" ? <div className="reference-banner"><Bot size={18} />{language === "zh" ? "独立策略基线 · 规则型考生 · 模拟工具 · 不调用 LLM · 不代表真实 Agent 的能力" : "Independent policy baseline · rule-based candidate · simulated tools · no LLM · not a production Agent"}</div> : null}<Overview data={data} /></> : null}
            {tab === "timeline" ? <Timeline events={data.trace.events} onSelect={(event) => setSelectedId(event.event_id)} /> : null}
            {tab === "tools" ? <Tools events={data.trace.events} /> : null}
            {tab === "parameters" ? <Parameters events={data.trace.events} /> : null}
            {tab === "interactions" ? <EventSubset events={data.trace.events.filter((event) => event.kind.startsWith("interaction"))} title={t("interactions")} /> : null}
            {tab === "context" ? <><ModelInputs data={data} context /><EventSubset events={data.trace.events.filter((event) => ["context", "retrieval", "memory"].some((prefix) => event.kind.startsWith(prefix)))} title={t("context")} /></> : null}
            {tab === "evidence" ? <>{businessMetric ? <BusinessEvidenceSource evidence={data.business_evidence} /> : null}<Evidence data={data} /></> : null}
            {tab === "metrics" ? <><BusinessAcceptance metric={businessMetric} evidence={data.business_evidence} /><EvaluationHistory data={data} /><Metrics metrics={data.metrics} gates={data.gates} /></> : null}
            {tab === "rawJson" ? <pre className="json-view raw">{JSON.stringify(data, null, 2)}</pre> : null}
          </div>
        </section>
      </div>
    </div>
  );
}

function Overview({ data }: { data: TraceDetail }) {
  const { t } = useApp();
  const usage = data.trace.resource_usage;
  const cards = [
    ["Agent LLM calls", display(usage.agent_llm_calls)],
    ["Tool calls", display(usage.tool_calls)],
    ["Total tokens", display(usage.total_tokens ?? usage.agent_total_tokens)],
    [t("duration"), formatDuration(usage.active_runtime_ms as number | null)],
    ["Wall runtime", formatDuration(usage.wall_runtime_ms as number | null)],
    ["Estimated cost", formatCost(usage.estimated_cost as number | null)],
  ];
  return <div className="overview-stack"><section className="overview-grid">{cards.map(([label, value]) => <div className="mini-stat" key={String(label)}><span>{label}</span><strong>{String(value)}</strong></div>)}</section><ModelInputs data={data} /><BusinessAcceptance metric={data.metrics.find(metric => metric.metric_id === "business_acceptance_pass")} evidence={data.business_evidence} /><section className="subpanel"><h2>Declared gates</h2><GateTable gates={data.gates} metrics={data.metrics} /></section></div>;
}

function Timeline({ events, onSelect }: { events: TraceEvent[]; onSelect: (event: TraceEvent) => void }) {
  return <div className="timeline-list">{events.map((event) => { const Icon = eventIcon(event.kind); return <button key={event.event_id} onClick={() => onSelect(event)}><span className={`event-icon ${eventTone(event.status)}`}><Icon size={14} /></span><span className="timeline-sequence">{String(event.sequence).padStart(2, "0")}</span><div><strong>{event.name || event.kind}</strong><small>{event.kind} · {event.status}</small></div><code>{event.event_id}</code></button>; })}</div>;
}

function Tools({ events }: { events: TraceEvent[] }) {
  const rows = events.filter((event) => event.kind === "tool.call" || event.kind === "tool_call");
  if (!rows.length) return <EmptyState title="No tool attempts" />;
  return <div className="table-scroll"><table><thead><tr><th>Step</th><th>Tool</th><th>Guard</th><th>Agent-reported schema</th><th>Observation</th><th>Arguments</th></tr></thead><tbody>{rows.map((event) => <tr key={event.event_id}><td>#{event.sequence}</td><td><strong>{String(event.attributes.tool_id || event.name)}</strong><small>{event.event_id}</small></td><td><StatusBadge value={event.attributes.guard_allowed === true ? "pass" : event.attributes.guard_allowed === false ? "blocked" : null} /></td><td><StatusBadge value={event.attributes.schema_pass as boolean | null} /></td><td><StatusBadge value={String(event.attributes.observation_status || event.status)} /></td><td><code className="code-wrap">{JSON.stringify(event.attributes.arguments || {})}</code></td></tr>)}</tbody></table></div>;
}

function Parameters({ events }: { events: TraceEvent[] }) {
  const rows = events.filter((event) => event.kind === "tool.call" || event.kind === "parameter.check");
  if (!rows.length) return <EmptyState title="No parameter evidence" />;
  return <div className="parameter-list">{rows.map((event) => <article className="subpanel" key={event.event_id}><div className="detail-title"><div><h2>{String(event.attributes.tool_id || event.name || "Parameter check")}</h2><span>{event.kind} · #{event.sequence}</span></div><StatusBadge value={event.attributes.schema_pass as boolean | null} /></div><dl className="kv-list horizontal"><div><dt>Intent score</dt><dd>{display(event.attributes.intent_score)}</dd></div><div><dt>Source conflicts</dt><dd>{display(event.attributes.source_conflict_count)}</dd></div><div><dt>Confirmation</dt><dd>{display(event.attributes.confirmation_kind)}</dd></div></dl><pre className="json-view">{JSON.stringify(event.attributes.arguments || event.attributes, null, 2)}</pre></article>)}</div>;
}

function EventSubset({ events, title }: { events: TraceEvent[]; title: string }) {
  if (!events.length) return <EmptyState title={`No ${title.toLowerCase()} evidence`} />;
  return <div className="event-subset">{events.map((event) => <article className="subpanel" key={event.event_id}><div className="detail-title"><div><h2>{event.name || event.kind}</h2><span>#{event.sequence} · {event.kind}</span></div><StatusBadge value={event.status} /></div><pre className="json-view">{JSON.stringify(event.attributes, null, 2)}</pre></article>)}</div>;
}

function Evidence({ data }: { data: TraceDetail }) {
  return <div className="overview-stack"><section className="subpanel"><h2>Gate evidence</h2><GateTable gates={data.gates} metrics={data.metrics} /></section><ArtifactEvidence events={data.trace.events} /><section className="subpanel"><h2>Evidence references</h2><div className="evidence-map">{data.trace.events.filter((event) => event.evidence_refs.length).map((event) => <div key={event.event_id}><code>{event.event_id}</code><span>→</span>{event.evidence_refs.map((ref) => <code key={ref}>{ref}</code>)}</div>)}</div></section><section className="subpanel"><h2>Annotations</h2>{data.annotations.length ? data.annotations.map((annotation) => <div className="annotation-row" key={annotation.annotation_id}><strong>{annotation.label}</strong><span>{formatDate(annotation.created_at)}</span><code>{JSON.stringify(annotation.value)}</code></div>) : <EmptyState />}</section></div>;
}

function GateTable({ gates, metrics = [] }: { gates: GateResult[]; metrics?: MetricResult[] }) {
  if (!gates.length) return <EmptyState title="No declared gates" />;
  return <div className="table-scroll"><table><thead><tr><th>Result</th><th>Metric</th><th>Rule</th><th>Actual</th><th>Reason</th></tr></thead><tbody>{gates.map((gate) => { const metric = metrics.find(m => m.metric_id === gate.metric_id); return <tr key={gate.metric_id}><td>{metric?.metric_id === "business_acceptance_pass" && cannotVerify(metric) ? <BusinessVerdict status="error" reasonCode={metric.reason_code} /> : <StatusBadge value={gate.passed} />}</td><td><code>{gate.metric_id}</code></td><td>{gate.operator} {display(gate.expected)}</td><td>{display(gate.actual)}</td><td>{gate.reason_code}</td></tr>; })}</tbody></table></div>;
}

function Metrics({ metrics, gates = [] }: { metrics: MetricResult[]; gates?: GateResult[] }) {
  const { t, language } = useApp();
  const groups = Array.from(new Set(metrics.map((metric) => metric.group)));
  return <div className="metric-groups">{groups.map((group) => <section className="subpanel" key={group}><h2>{group}</h2><div className="table-scroll"><table><thead><tr><th>{t("status")}</th><th>{t("metric")}</th><th>{language === "zh" ? "验收作用" : "Acceptance role"}</th><th>{t("value")}</th><th>{t("reason")}</th><th>Evidence</th></tr></thead><tbody>{metrics.filter((metric) => metric.group === group).map((metric) => <tr key={metric.metric_id}><td>{metric.metric_id === "business_acceptance_pass" ? <BusinessVerdict status={metric.status} reasonCode={metric.reason_code} /> : <StatusBadge value={metric.status} />}</td><td><code>{metric.metric_id}</code></td><td>{gates.some(g => g.metric_id === metric.metric_id) ? (language === "zh" ? "必过门禁" : "Declared gate") : (language === "zh" ? "诊断" : "Diagnostic")}</td><td>{metric.status === "na" ? "N/A" : display(metric.value)}</td><td>{metric.na_reason || metric.reason_code}</td><td>{metric.evidence_refs.length ? metric.evidence_refs.join(", ") : "—"}</td></tr>)}</tbody></table></div></section>)}</div>;
}

function display(value: unknown): string {
  if (value == null) return "N/A";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(3);
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
function EvaluationHistory({ data }: { data: TraceDetail }) {
  const { language } = useApp();
  return <section className="subpanel"><h2>{language === "zh" ? "评分历史" : "Evaluation history"}</h2>{data.evaluation_history?.length ? data.evaluation_history.map(e => <details className="data-disclosure" key={e.evaluation_id}><summary><StatusBadge value={e.overall_pass} /><code>{e.evaluation_id}</code><span>{formatDate(e.evaluated_at)}</span><span>{e.case_id}</span></summary><pre className="json-view">{JSON.stringify(e.binding || {}, null, 2)}</pre><GateTable gates={e.gate_results || []} metrics={e.metric_results || []} /><BusinessAcceptance metric={e.metric_results.find(m => m.metric_id === "business_acceptance_pass")} /><Metrics metrics={e.metric_results || []} gates={e.gate_results || []} /></details>) : <EmptyState title={language === "zh" ? "尚未评分" : "Not evaluated"} />}</section>;
}

