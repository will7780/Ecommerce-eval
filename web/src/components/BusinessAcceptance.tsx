import { useApp } from "../app-context";
import type { MetricResult, TraceDetail } from "../types";

export interface BusinessRequirement {
  requirement_id: string;
  verifier_id: string;
  verifier_version?: string;
  subject: unknown;
  turn?: number | null;
  expected: Record<string, unknown>;
  required_evidence: string[];
  applicable?: boolean;
}

export function businessRequirements(value: unknown): BusinessRequirement[] {
  return Array.isArray(value) ? value.filter((v): v is BusinessRequirement => Boolean(v && typeof v === "object" && typeof v.requirement_id === "string")) : [];
}

function content(value: unknown): string {
  if (value == null || value === "") return "-";
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

export function BusinessRequirements({ requirements }: { requirements: BusinessRequirement[] }) {
  const { language } = useApp();
  const zh = language === "zh";
  return <section className="business-requirements" aria-label={zh ? "业务条件" : "Business conditions"}>
    <h3>{zh ? "业务条件" : "Business conditions"}</h3>
    {requirements.map(requirement => <details className="data-disclosure" key={requirement.requirement_id}>
      <summary><code>{requirement.requirement_id}</code><strong>{content(requirement.subject)}</strong>{requirement.applicable === false ? <span className="status-badge neutral">N/A</span> : null}</summary>
      <dl className="kv-list horizontal"><div><dt>{zh ? "验证器" : "Verifier"}</dt><dd>{requirement.verifier_id} / {requirement.verifier_version || "1.0"}</dd></div>{requirement.turn != null ? <div><dt>{zh ? "轮次" : "Turn"}</dt><dd>{requirement.turn}</dd></div> : null}</dl>
      <h4>{zh ? "预期结果与约束" : "Expected outcome & constraints"}</h4><pre className="json-view">{content(requirement.expected)}</pre>
      <h4>{zh ? "所需证据" : "Required evidence"}</h4><div className="evidence-tags">{(requirement.required_evidence || []).map(ref => <code key={ref}>{ref}</code>)}</div>
    </details>)}
  </section>;
}

export function cannotVerify(metric: Pick<MetricResult, "status" | "reason_code">): boolean {
  return metric.status === "error" || metric.reason_code === "evidence_missing" || metric.reason_code?.includes("evidence_missing");
}

export function BusinessVerdict({ status, reasonCode }: { status: string; reasonCode?: string }) {
  const { language } = useApp();
  const zh = language === "zh";
  const missing = status === "error" || reasonCode?.includes("evidence_missing");
  const tone = missing ? "warning" : status === "pass" ? "success" : status === "fail" ? "danger" : "neutral";
  const label = missing ? (zh ? "无法核验" : "Cannot verify") : status === "pass" ? (zh ? "已核验 · 通过" : "Verified / pass") : status === "fail" ? (zh ? "不通过" : "Fail") : "N/A";
  return <span className={`status-badge ${tone}`}>{label}</span>;
}

export function BusinessAcceptance({ metric, evidence }: { metric?: MetricResult; evidence?: TraceDetail["business_evidence"] }) {
  const { language } = useApp();
  if (!metric) return null;
  const zh = language === "zh";
  const results = Array.isArray(metric.details?.requirement_results) ? metric.details.requirement_results as Array<Record<string, unknown>> : [];
  return <section className="subpanel business-acceptance" aria-label={zh ? "业务验收" : "Business acceptance"}>
    <div className="detail-title"><h2>{zh ? "业务验收" : "Business acceptance"}</h2><BusinessVerdict status={metric.status} reasonCode={metric.reason_code} /></div>
    {results.length ? results.map((result, i) => {
      const details = result.details && typeof result.details === "object" ? result.details as Record<string, unknown> : {};
      const id = String(result.requirement_id || details.requirement_id || result.metric_id || i);
      const refs = Array.isArray(result.evidence_refs) ? result.evidence_refs as string[] : [];
      const source = result.evidence_source || result.source || details.evidence_source || details.source || details.collector_id || evidence?.collector_id;
      return <details className="data-disclosure requirement-result" key={id} open={cannotVerify({ status: String(result.status) as MetricResult["status"], reason_code: String(result.reason_code || "") })}>
        <summary><BusinessVerdict status={String(result.status || "error")} reasonCode={String(result.reason_code || "")} /><code>{id}</code><span>{content(result.subject || details.subject || result.reason_code)}</span></summary>
        <dl className="kv-list"><div><dt>{zh ? "原因" : "Reason"}</dt><dd>{content(result.na_reason || result.reason_code)}</dd></div><div><dt>{zh ? "证据来源" : "Evidence source"}</dt><dd>{source ? content(source) : (zh ? "未提供" : "Not supplied")}</dd></div><div><dt>{zh ? "证据引用" : "Evidence references"}</dt><dd>{refs.length ? refs.join(", ") : (zh ? "缺少证据引用" : "No evidence references")}</dd></div></dl>
        <pre className="json-view">{JSON.stringify(details, null, 2)}</pre>
      </details>;
    }) : <p className="muted-text">{zh ? "未提供逐条件证据" : "Per-condition evidence not supplied"}</p>}
  </section>;
}

export function BusinessEvidenceSource({ evidence }: { evidence: TraceDetail["business_evidence"] }) {
  const { language } = useApp();
  const zh = language === "zh";
  return <section className="subpanel business-evidence-source"><h2>{zh ? "业务证据采集" : "Business evidence collection"}</h2>
    {!evidence ? <p className="warning-text">{zh ? "未采集独立业务证据" : "Independent business evidence not collected"}</p> : <>
      <dl className="kv-list horizontal"><div><dt>{zh ? "采集器" : "Collector"}</dt><dd>{evidence.collector_id}</dd></div><div><dt>{zh ? "覆盖完整" : "Complete coverage"}</dt><dd>{evidence.complete ? (zh ? "是" : "Yes") : (zh ? "否" : "No")}</dd></div><div><dt>{zh ? "运行范围" : "Run scope"}</dt><dd>{evidence.run_id}</dd></div><div><dt>{zh ? "公司范围" : "Company scope"}</dt><dd>{evidence.company_id}</dd></div><div><dt>{zh ? "时间范围" : "Time range"}</dt><dd>{evidence.started_at} / {evidence.ended_at || (zh ? "未结束" : "Not ended")}</dd></div></dl>
      {evidence.omission_reasons?.length ? <p className="warning-text">{evidence.omission_reasons.join(", ")}</p> : null}
      <details className="data-disclosure"><summary>{zh ? "查看采集证据" : "Inspect collected evidence"}</summary><pre className="json-view">{JSON.stringify(evidence, null, 2)}</pre></details>
    </>}
  </section>;
}
