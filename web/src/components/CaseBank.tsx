import { useState } from "react";
import { ChevronDown, FileCheck2, Search } from "lucide-react";
import { useApp } from "../app-context";
import { BusinessRequirements, businessRequirements } from "./BusinessAcceptance";

export const bankDirections = [
  ["I", "Intent & boundaries", "意图与边界"], ["C", "Company rules", "公司资料与规则"], ["T", "Tools & dependencies", "工具与依赖"], ["P", "Parameters & preconditions", "参数与前置检查"],
  ["A", "Artifacts & review", "产物质量与审核"], ["M", "Conversation", "多轮连续性"], ["R", "Recovery & honesty", "恢复与结果诚实"], ["S", "Safety, efficiency & cost", "权限、效率与成本"],
];

export function CaseBank({ cases }: { cases: Array<Record<string, unknown>> }) {
  const { language } = useApp();
  const zh = language === "zh";
  const [direction, setDirection] = useState("");
  const [search, setSearch] = useState("");
  const getDirection = (item: Record<string, unknown>) => String(item.scenario_id || item.case_id || "").slice(0, 1);
  const scenarioCases = cases.filter(c => c.scenario_id);
  const visible = cases.filter(c => (!direction || getDirection(c) === direction) && `${c.case_id} ${c.name}`.toLowerCase().includes(search.toLowerCase()));
  return <div className="bank-browser">{scenarioCases.length ? <div className="coverage-grid">{bankDirections.map(([id, en, cn]) => { const count = cases.filter(c => getDirection(c) === id).length; return <button aria-pressed={direction === id} className={direction === id ? "active" : ""} key={id} onClick={() => setDirection(direction === id ? "" : id)}><strong>{id} · {zh ? cn : en}</strong><span>{count} / 4</span></button>; })}</div> : null}<div className="toolbar"><label className="search-box"><Search size={15} /><input aria-label={zh ? "搜索考题" : "Search cases"} placeholder={zh ? "搜索考题" : "Search cases"} value={search} onChange={e => setSearch(e.target.value)} /></label><span className="muted-text">{visible.length} / {cases.length}</span></div><div className="case-list">{visible.map(item => <CaseDetail item={item} key={String(item.case_id)} />)}</div></div>;
}

function CaseDetail({ item }: { item: Record<string, unknown> }) {
  const { language } = useApp();
  const zh = language === "zh";
  const [tab, setTab] = useState("task");
  const scenario = (item.scenario_data || {}) as Record<string, unknown>;
  const input = item.input as Record<string, unknown> || {};
  const label = (en: string, cn: string) => zh ? cn : en;
  const requirements = businessRequirements(item.business_requirements);
  const businessCase = item.contract_version === "1.2" || requirements.length > 0;
  return <details className="case-disclosure"><summary><FileCheck2 size={16} /><code>{String(item.case_id)}</code><strong>{String(item.name)}</strong><ChevronDown size={15} /></summary><div className="tag-list">{(item.tags as string[] || []).map(tag => <span key={tag}>{tag}</span>)}</div><div className="tabs" role="tablist" aria-label={String(item.case_id)}>{[["task", "Task & assets", "题干与资料"], ["interaction", "Interactions", "交互条件"], ["grading", "Scoring evidence", "评分依据"]].map(([id, en, cn]) => <button role="tab" aria-selected={tab === id} key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}>{label(en, cn)}</button>)}</div>
    {tab === "task" ? <div className="case-sections"><section><h3>{label("User goal", "用户目标")}</h3><pre className="prose-data">{typeof input.message === "string" ? input.message : JSON.stringify(input, null, 2)}</pre></section>{businessCase ? <BusinessRequirements requirements={requirements} /> : null}{Object.entries(scenario).filter(([key]) => ["rules", "company_rules", "public_assets", "assets", "candidate_input", "initial_data", "initial_state", "provenance", "public_context"].includes(key)).map(([key, value]) => <section key={key}><h3>{key}</h3><pre className="json-view">{JSON.stringify(value, null, 2)}</pre></section>)}{!businessCase ? <section><h3>{label("Capabilities / tools", "能力与工具")}</h3><pre className="json-view">{JSON.stringify({ required: item.expected_tools, allowed: item.allowed_tools, bindings: item.capability_bindings }, null, 2)}</pre></section> : null}</div> : null}
    {tab === "interaction" ? <div className="case-sections"><section><h3>{label("Evaluator-side interaction script", "测评侧交互脚本")}</h3><pre className="json-view">{JSON.stringify(Array.isArray(item.conversation) && item.conversation.length ? item.conversation : scenario.interaction_script || [], null, 2)}</pre></section><section><h3>{label("Artifact review policy", "产物审核规则")}</h3><pre className="json-view">{JSON.stringify(item.artifact_requirements || {}, null, 2)}</pre></section></div> : null}
    {tab === "grading" ? <div className="case-sections">{businessCase ? <BusinessRequirements requirements={requirements} /> : null}<section><h3>{label(businessCase ? "Explicit constraints & diagnostics" : "Behavior & evidence", businessCase ? "显式约束与诊断" : "行为与证据")}</h3><pre className="json-view">{JSON.stringify({ assertions: item.behavior_assertions, outcomes: item.outcome_assertions, order: Array.isArray(item.partial_order) && item.partial_order.length ? item.partial_order : item.required_sequence, parameters: item.parameter_expectations, forbidden: item.forbidden_tools, reference_min_steps: item.reference_min_steps, budgets: item.budgets }, null, 2)}</pre></section><section><h3>{label("Required gates", "必过门禁")}</h3><div className="table-scroll"><table><thead><tr><th>Metric</th><th>{label("Rule", "规则")}</th><th>N/A</th></tr></thead><tbody>{((item.gates || []) as Array<Record<string, unknown>>).map((gate, i) => <tr key={i}><td><code>{String(gate.metric_id)}</code></td><td>{String(gate.operator)} {JSON.stringify(gate.expected)}</td><td>{gate.allow_na ? label("Allowed", "允许") : label("Fail", "不通过")}</td></tr>)}</tbody></table></div></section></div> : null}
  </details>;
}
