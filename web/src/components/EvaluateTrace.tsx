import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Play, X } from "lucide-react";
import { useState } from "react";
import { api, projectQuery } from "../api";
import { useApp } from "../app-context";
import type { Dataset, ToolContractSet } from "../types";

export function EvaluateTrace({ traceId, projectId }: { traceId: string; projectId: string }) {
  const { language } = useApp();
  const [open, setOpen] = useState(false);
  return <><button className="button secondary" onClick={() => setOpen(true)}><Play size={14} />{language === "zh" ? "评分 / 重评" : "Evaluate / re-evaluate"}</button>{open ? <EvaluationDialog traceId={traceId} projectId={projectId} close={() => setOpen(false)} /> : null}</>;
}

function EvaluationDialog({ traceId, projectId, close }: { traceId: string; projectId: string; close: () => void }) {
  const { language } = useApp();
  const zh = language === "zh";
  const client = useQueryClient();
  const [datasetIndex, setDatasetIndex] = useState(0);
  const [caseId, setCaseId] = useState("");
  const [contractIndex, setContractIndex] = useState(0);
  const [evaluatorIndex, setEvaluatorIndex] = useState(0);
  const datasets = useQuery({ queryKey: ["datasets", projectId], queryFn: () => api<{ items: Dataset[] }>(`/datasets${projectQuery(projectId)}`) });
  const selected = datasets.data?.items[datasetIndex];
  const detail = useQuery({ queryKey: ["dataset", projectId, selected?.dataset_id, selected?.version], queryFn: () => api<Dataset>(`/datasets/${encodeURIComponent(projectId)}/${encodeURIComponent(selected!.dataset_id)}/${encodeURIComponent(selected!.version)}`), enabled: Boolean(selected) });
  const contracts = useQuery({ queryKey: ["contracts", projectId], queryFn: () => api<{ items: ToolContractSet[] }>(`/tool-contracts${projectQuery(projectId)}`) });
  const evaluators = useQuery({ queryKey: ["evaluators", projectId], queryFn: () => api<{ sets: Array<{ set_id: string; version: string }> }>(`/evaluators${projectQuery(projectId)}`) });
  const mutation = useMutation({ mutationFn: async () => {
    const contract = contracts.data!.items[contractIndex]; const evaluator = evaluators.data!.sets[evaluatorIndex];
    return api("/evaluations", { method: "POST", body: JSON.stringify({ project_id: projectId, trace_id: traceId, dataset_id: selected!.dataset_id, dataset_version: selected!.version, case_id: caseId, tool_contract_set_id: contract.set_id, tool_contract_version: contract.version, evaluator_set_id: evaluator.set_id, evaluator_set_version: evaluator.version }) });
  }, onSuccess: async () => { await client.invalidateQueries(); close(); } });
  const ready = selected && detail.data?.cases?.some(c => c.case_id === caseId) && contracts.data?.items[contractIndex] && evaluators.data?.sets[evaluatorIndex];
  return <div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-label={zh ? "评分运行记录" : "Evaluate trace"}><header className="modal-header"><div><CheckCircle2 size={18} /><h2>{zh ? "评分运行记录" : "Evaluate trace"}</h2></div><button className="icon-button" title={zh ? "关闭" : "Close"} onClick={close}><X size={15} /></button></header><div className="form-grid"><label><span>{zh ? "数据集版本" : "Dataset version"}</span><select value={datasetIndex} onChange={e => { setDatasetIndex(Number(e.target.value)); setCaseId(""); }}>{datasets.data?.items.map((d, i) => <option key={`${d.dataset_id}:${d.version}`} value={i}>{d.name} · {d.version}</option>)}</select></label><label><span>{zh ? "考题" : "Case"}</span><select value={caseId} onChange={e => setCaseId(e.target.value)}><option value="">{zh ? "选择考题" : "Select case"}</option>{detail.data?.cases?.map(c => <option key={String(c.case_id)} value={String(c.case_id)}>{String(c.case_id)} · {String(c.name)}</option>)}</select></label><label><span>{zh ? "工具合同" : "Tool contract"}</span><select value={contractIndex} onChange={e => setContractIndex(Number(e.target.value))}>{contracts.data?.items.map((c, i) => <option key={`${c.set_id}:${c.version}`} value={i}>{c.set_id} · {c.version}</option>)}</select></label><label><span>{zh ? "评测器集合" : "Evaluator set"}</span><select value={evaluatorIndex} onChange={e => setEvaluatorIndex(Number(e.target.value))}>{evaluators.data?.sets.map((v, i) => <option key={`${v.set_id}:${v.version}`} value={i}>{v.set_id} · {v.version}</option>)}</select></label></div><p className="detail-copy" style={{ padding: "0 16px" }}>{zh ? "创建新评分记录，保留历史成绩。不会重新调用 Agent。" : "Creates a new evaluation. Previous scores are retained. The Agent is not re-run."}</p>{mutation.error ? <p className="inline-error">{mutation.error.message}</p> : null}<footer className="modal-actions"><button className="button secondary" onClick={close}>{zh ? "取消" : "Cancel"}</button><button className="button primary" disabled={!ready || mutation.isPending} onClick={() => mutation.mutate()}><Play size={15} />{zh ? "评分" : "Evaluate"}</button></footer></section></div>;
}
