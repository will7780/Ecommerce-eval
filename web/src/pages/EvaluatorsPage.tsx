import { useQuery } from "@tanstack/react-query";
import { BookOpenCheck, Filter, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { api, projectQuery } from "../api";
import { useApp } from "../app-context";
import { EmptyState, ErrorState, LoadingState, PageHeader } from "../components/UiStates";
import type { Evaluator } from "../types";

export function EvaluatorsPage() {
  const { t, projectId } = useApp();
  const [search, setSearch] = useState("");
  const [group, setGroup] = useState("all");
  const query = useQuery({ queryKey: ["evaluators", projectId], queryFn: () => api<{ items: Evaluator[]; packs: Array<{ pack_id: string; version: string }>; sets: Array<{ set_id: string; version: string; metric_ids: string[] }> }>(`/evaluators${projectQuery(projectId)}`), enabled: Boolean(projectId) });
  const groups = useMemo(() => Array.from(new Set((query.data?.items || []).map((item) => item.group))).sort(), [query.data]);
  const rows = useMemo(() => (query.data?.items || []).filter((item) => (group === "all" || item.group === group) && item.metric_id.toLowerCase().includes(search.toLowerCase())), [query.data, group, search]);
  return <div className="page-stack"><PageHeader title={t("evaluators")} subtitle={`${query.data?.items.length || 0} deterministic and evidence-based metrics`} /><section className="pack-strip">{query.data?.packs.map((pack) => <div key={pack.pack_id}><BookOpenCheck size={16} /><strong>{pack.pack_id}</strong><span>v{pack.version}</span></div>)}</section><div className="toolbar"><label className="search-box"><Search size={15} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={`${t("search")} metric`} /></label><label className="filter-select"><Filter size={15} /><select value={group} onChange={(event) => setGroup(event.target.value)}><option value="all">All groups</option>{groups.map((item) => <option key={item}>{item}</option>)}</select></label></div><section className="panel table-panel">{query.isLoading ? <LoadingState /> : query.error ? <ErrorState error={query.error} /> : !rows.length ? <EmptyState /> : <div className="table-scroll"><table><thead><tr><th>{t("metric")}</th><th>{t("group")}</th><th>Version</th><th>{t("requiredEvidence")}</th></tr></thead><tbody>{rows.map((item) => <tr key={item.metric_id}><td><code>{item.metric_id}</code></td><td><span className="group-chip">{item.group}</span></td><td>{item.metric_version}</td><td><div className="tag-list">{item.required_evidence.length ? item.required_evidence.map((evidence) => <span key={evidence}>{evidence}</span>) : <span>N/A</span>}</div></td></tr>)}</tbody></table></div>}</section></div>;
}
