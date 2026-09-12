import { useQuery } from "@tanstack/react-query";
import { Braces, Box, ChevronRight, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { api, projectQuery } from "../api";
import { useApp } from "../app-context";
import { StatusBadge } from "../components/StatusBadge";
import { EmptyState, ErrorState, LoadingState, PageHeader } from "../components/UiStates";
import type { TargetDefinition, ToolContractSet } from "../types";

export function ContractsPage() {
  const { t, projectId } = useApp();
  const [tab, setTab] = useState<"tools" | "targets">("tools");
  const [selected, setSelected] = useState<Record<string, unknown> | null>(null);
  const contracts = useQuery({ queryKey: ["contracts", projectId], queryFn: () => api<{ items: ToolContractSet[] }>(`/tool-contracts${projectQuery(projectId)}`), enabled: Boolean(projectId) });
  const targets = useQuery({ queryKey: ["targets", projectId], queryFn: () => api<{ items: TargetDefinition[] }>(`/targets${projectQuery(projectId)}`), enabled: Boolean(projectId) });
  const loading = tab === "tools" ? contracts.isLoading : targets.isLoading;
  const error = tab === "tools" ? contracts.error : targets.error;
  return <div className="page-stack"><PageHeader title={t("contracts")} subtitle="Versioned execution and evidence boundaries" /><div className="segmented"><button className={tab === "tools" ? "active" : ""} onClick={() => { setTab("tools"); setSelected(null); }}><Braces size={15} />{t("toolContracts")}</button><button className={tab === "targets" ? "active" : ""} onClick={() => { setTab("targets"); setSelected(null); }}><Box size={15} />{t("targets")}</button></div><section className="split-view contracts-view"><div className="panel list-panel">{loading ? <LoadingState /> : error ? <ErrorState error={error} /> : tab === "tools" ? contracts.data?.items.map((set) => <div key={`${set.set_id}:${set.version}`} className="contract-set"><div className="section-label">{set.set_id} · v{set.version}</div>{set.tools.map((tool) => <button className="selection-row" key={String(tool.tool_id)} onClick={() => setSelected(tool)}><ShieldCheck size={17} /><div><strong>{String(tool.title || tool.tool_id)}</strong><span>{String(tool.tool_id)} · {String(tool.risk_level)}</span></div><ChevronRight size={15} /></button>)}</div>) : targets.data?.items.map((target) => <button className="selection-row" key={`${target.target_id}:${target.version}`} onClick={() => setSelected(target as unknown as Record<string, unknown>)}><Box size={17} /><div><strong>{target.name}</strong><span>{target.target_id} · {target.adapter_type} · v{target.version}</span></div><StatusBadge value={target.safe_for_eval} /></button>)}</div><div className="panel detail-panel">{selected ? <><div className="detail-title"><div><h2>{String(selected.title || selected.name || selected.tool_id || selected.target_id)}</h2><span>{String(selected.tool_id || selected.target_id || "contract")}</span></div><Braces size={18} /></div><pre className="json-view">{JSON.stringify(selected, null, 2)}</pre></> : <EmptyState title="Select a contract" />}</div></section></div>;
}
