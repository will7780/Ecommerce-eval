import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Beaker, GitCompareArrows, Play, Plus, RefreshCw, RotateCcw, Square, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, formatDate, formatDuration, formatPercent, projectQuery } from "../api";
import { useApp } from "../app-context";
import { StatusBadge } from "../components/StatusBadge";
import { EmptyState, ErrorState, LoadingState, PageHeader } from "../components/UiStates";
import type { Dataset, Experiment, TargetDefinition, ToolContractSet } from "../types";
import { listProviders } from "../provider-api";

interface EvaluatorSet { project_id: string; set_id: string; version: string; metric_ids: string[] }

function useExperimentProgress(experimentId: string | null, active: boolean) {
  const client = useQueryClient();
  const [transport, setTransport] = useState<"sse" | "poll">("sse");
  useEffect(() => {
    if (!experimentId || !active) return;
    const source = new EventSource(`/api/v1/experiments/${encodeURIComponent(experimentId)}/events`);
    source.onmessage = () => client.invalidateQueries({ queryKey: ["experiments"] });
    source.onerror = () => { setTransport("poll"); source.close(); };
    return () => source.close();
  }, [client, experimentId, active]);
  return transport;
}

export function ExperimentsPage() {
  const { t, projectId } = useApp();
  const queryClient = useQueryClient();
  const [params] = useSearchParams();
  const [showCreate, setShowCreate] = useState(params.get("create") === "1");
  const [paidRetry, setPaidRetry] = useState<Experiment | null>(null);
  useEffect(() => { setPaidRetry(null); }, [projectId]);
  const [left, setLeft] = useState("");
  const [right, setRight] = useState("");
  const experiments = useQuery({ queryKey: ["experiments", projectId], queryFn: () => api<{ items: Experiment[] }>(`/experiments${projectQuery(projectId)}`), enabled: Boolean(projectId), refetchInterval: 3000 });
  const active = experiments.data?.items.find((item) => ["queued", "running"].includes(item.status)) || null;
  const transport = useExperimentProgress(active?.experiment_id || null, Boolean(active));
  useEffect(() => {
    const selected = params.get("selected");
    if (selected && !left) setLeft(selected);
  }, [params, left]);
  useEffect(() => {
    const rows = experiments.data?.items || [];
    if (!left && rows[0]) setLeft(rows[0].experiment_id);
    if (!right && rows[1]) setRight(rows[1].experiment_id);
  }, [experiments.data, left, right]);
  const compare = useQuery({ queryKey: ["experiment-compare", left, right], queryFn: () => api<{ left: ExperimentSummary; right: ExperimentSummary }>(`/experiments/compare?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`), enabled: Boolean(left && right && left !== right) });
  const action = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "cancel" | "retry" }) => api(`/experiments/${encodeURIComponent(id)}/${action}`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["experiments"] }),
  });
  return (
    <div className="page-stack">
      <PageHeader title={t("experiments")} subtitle={`Version-pinned runs · live via ${transport.toUpperCase()}`} actions={<><button className="button secondary" onClick={() => experiments.refetch()}><RefreshCw size={15} />{t("refresh")}</button><button className="button primary" onClick={() => setShowCreate(true)}><Plus size={15} />{t("createExperiment")}</button></>} />
      <section className="panel table-panel">
        {experiments.isLoading ? <LoadingState /> : experiments.error ? <ErrorState error={experiments.error} /> : !experiments.data?.items.length ? <EmptyState /> : (
          <div className="table-scroll"><table><thead><tr><th>{t("status")}</th><th>Experiment</th><th>{t("result")}</th><th>Progress</th><th>{t("started")}</th><th>{t("actions")}</th></tr></thead><tbody>
            {experiments.data.items.map((item) => { const progress = item.total_runs ? item.completed_runs / item.total_runs : 0; return <tr key={item.experiment_id}><td><StatusBadge value={item.status} /></td><td><strong>{item.name}</strong><small>{item.experiment_id}</small></td><td>{item.passed_runs} pass · {item.failed_runs} fail</td><td><div className="progress-cell"><span><i style={{ width: `${progress * 100}%` }} /></span><small>{item.completed_runs}/{item.total_runs}</small></div></td><td>{formatDate(item.started_at || item.created_at)}</td><td><div className="row-actions">{["queued", "running"].includes(item.status) ? <button className="icon-button" title={t("cancel")} onClick={() => action.mutate({ id: item.experiment_id, action: "cancel" })}><Square size={14} /></button> : <button className="icon-button" title={t("retry")} disabled={action.isPending} onClick={() => item.spec?.provider_id ? setPaidRetry(item) : action.mutate({ id: item.experiment_id, action: "retry" })}><RotateCcw size={14} /></button>}<Link className="icon-link" title="View traces" to={`/traces?experiment=${encodeURIComponent(item.experiment_id)}`}><Play size={14} /></Link></div></td></tr>; })}
          </tbody></table></div>
        )}
      </section>
      <section className="panel compare-panel">
        <div className="panel-heading"><div><h2>{t("compare")}</h2><span>Per-metric comparison with N/A preserved</span></div><GitCompareArrows size={17} /></div>
        <div className="compare-controls"><select value={left} onChange={(event) => setLeft(event.target.value)}>{experiments.data?.items.map((item) => <option value={item.experiment_id} key={item.experiment_id}>{item.name}</option>)}</select><span>vs</span><select value={right} onChange={(event) => setRight(event.target.value)}>{experiments.data?.items.map((item) => <option value={item.experiment_id} key={item.experiment_id}>{item.name}</option>)}</select></div>
        {compare.isFetching ? <LoadingState /> : compare.data ? <ComparisonTable data={compare.data} /> : <EmptyState title="Select two experiments" />}
      </section>
      {showCreate ? <CreateExperimentModal projectId={projectId} onClose={() => setShowCreate(false)} /> : null}
      {paidRetry ? <PaidRetryDialog experiment={paidRetry} onClose={() => setPaidRetry(null)} /> : null}
    </div>
  );
}

function PaidRetryDialog({ experiment, onClose }: { experiment: Experiment; onClose: () => void }) {
  const { t, language } = useApp();
  const text = (en: string, cn: string) => language === "zh" ? cn : en;
  const client = useQueryClient();
  const [allowed, setAllowed] = useState(false);
  const retry = useMutation({
    mutationFn: () => api(`/experiments/${encodeURIComponent(experiment.experiment_id)}/retry`, { method: "POST", body: JSON.stringify({ allow_paid: true }) }),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ["experiments"] }); onClose(); },
    onSettled: () => setAllowed(false),
  });
  return <div className="modal-backdrop"><section className="modal provider-modal" role="dialog" aria-modal="true" aria-label={text("Retry paid experiment", "重试付费实验")}><div className="modal-header"><h2>{text("Retry paid experiment", "重试付费实验")}</h2><button className="icon-button" title={t("close")} disabled={retry.isPending} onClick={onClose}><X size={16} /></button></div><div className="form-grid"><dl className="kv-list full"><div><dt>{text("Experiment", "实验")}</dt><dd>{experiment.name}</dd></div><div><dt>Provider</dt><dd>{String(experiment.spec.provider_id)} / v{String(experiment.spec.provider_version)}</dd></div><div><dt>{text("Model", "模型")}</dt><dd>{String(experiment.spec.model)}</dd></div></dl><label className="checkbox-label full"><input type="checkbox" disabled={retry.isPending} checked={allowed} onChange={event => setAllowed(event.target.checked)} /><span>{text("I authorize a new paid run with the pinned configuration.", "我授权使用固定配置重新执行一次付费实验。")}</span></label></div>{retry.error ? <ErrorState error={retry.error} /> : null}<div className="modal-actions"><button className="button secondary" disabled={retry.isPending} onClick={onClose}>{t("cancel")}</button><button className="button primary" disabled={!allowed || retry.isPending} onClick={() => { if (allowed) retry.mutate(); }}><RotateCcw size={15} />{t("retry")}</button></div></section></div>;
}

interface ExperimentSummary { experiment_id: string; run_count: number; pass_rate: number | null; average_active_runtime_ms: number; metrics: Record<string, { average: number | null; pass_rate: number | null; applicable_runs: number }> }

function ComparisonTable({ data }: { data: { left: ExperimentSummary; right: ExperimentSummary } }) {
  const metricIds = Array.from(new Set([...Object.keys(data.left.metrics), ...Object.keys(data.right.metrics)])).sort();
  return <><div className="compare-summary"><div><span>Left pass rate</span><strong>{formatPercent(data.left.pass_rate)}</strong></div><div><span>Right pass rate</span><strong>{formatPercent(data.right.pass_rate)}</strong></div><div><span>Left latency</span><strong>{formatDuration(data.left.average_active_runtime_ms)}</strong></div><div><span>Right latency</span><strong>{formatDuration(data.right.average_active_runtime_ms)}</strong></div></div><div className="table-scroll"><table><thead><tr><th>Metric</th><th>Left</th><th>Right</th><th>Applicable</th></tr></thead><tbody>{metricIds.slice(0, 24).map((id) => <tr key={id}><td><code>{id}</code></td><td>{metricValue(data.left.metrics[id])}</td><td>{metricValue(data.right.metrics[id])}</td><td>{data.left.metrics[id]?.applicable_runs || 0} / {data.right.metrics[id]?.applicable_runs || 0}</td></tr>)}</tbody></table></div></>;
}

function metricValue(value?: { average: number | null; pass_rate: number | null }) { return value?.average != null ? value.average.toFixed(3) : formatPercent(value?.pass_rate); }

function CreateExperimentModal({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const { t, language } = useApp();
  const text = (en: string, cn: string) => language === "zh" ? cn : en;
  const queryClient = useQueryClient();
  const [initialParams] = useSearchParams();
  const initialized = useRef({ dataset: false, target: false, evaluator: false });
  const datasets = useQuery({ queryKey: ["datasets", projectId], queryFn: () => api<{ items: Dataset[] }>(`/datasets${projectQuery(projectId)}`) });
  const targets = useQuery({ queryKey: ["targets", projectId], queryFn: () => api<{ items: TargetDefinition[] }>(`/targets${projectQuery(projectId)}`) });
  const contracts = useQuery({ queryKey: ["contracts", projectId], queryFn: () => api<{ items: ToolContractSet[] }>(`/tool-contracts${projectQuery(projectId)}`) });
  const evaluators = useQuery({ queryKey: ["evaluators", projectId], queryFn: () => api<{ sets: EvaluatorSet[] }>(`/evaluators${projectQuery(projectId)}`) });
  const [name, setName] = useState("Evaluation run");
  const [datasetIndex, setDatasetIndex] = useState(0);
  const [targetIndex, setTargetIndex] = useState(0);
  const [contractIndex, setContractIndex] = useState(0);
  const [evaluatorIndex, setEvaluatorIndex] = useState(0);
  const [repetitions, setRepetitions] = useState(1);
  const [concurrency, setConcurrency] = useState(1);
  const [providerKey, setProviderKey] = useState("");
  const [model, setModel] = useState("");
  const [allowPaid, setAllowPaid] = useState(false);
  const selectedTarget = targets.data?.items[targetIndex];
  const realModel = Boolean(selectedTarget && ["business_interface", "file_editor"].includes(selectedTarget.adapter_type));
  const boundContractIndex = realModel ? (contracts.data?.items.findIndex(item => item.set_id === selectedTarget?.config.tool_contract_set_id && item.version === selectedTarget?.config.tool_contract_version) ?? -1) : contractIndex;
  useEffect(() => {
    if (datasets.data && !initialized.current.dataset) { const index = datasets.data.items.findIndex(item => item.dataset_id === initialParams.get("dataset") && item.version === initialParams.get("dataset_version")); if (index >= 0) setDatasetIndex(index); initialized.current.dataset = true; }
    if (targets.data && !initialized.current.target) { const index = targets.data.items.findIndex(item => item.target_id === initialParams.get("target") && item.version === initialParams.get("target_version")); if (index >= 0) setTargetIndex(index); initialized.current.target = true; }
    if (evaluators.data && !initialized.current.evaluator) { const index = evaluators.data.sets.findIndex(item => item.set_id === initialParams.get("evaluator") && item.version === initialParams.get("evaluator_version")); if (index >= 0) setEvaluatorIndex(index); initialized.current.evaluator = true; }
  }, [datasets.data, targets.data, evaluators.data, initialParams]);
  const providers = useQuery({ queryKey: ["providers"], queryFn: listProviders, enabled: realModel, retry: false });
  const availableProviders = (providers.data?.items || []).filter(p => p.enabled && p.configured && p.version != null);
  const selectedProvider = availableProviders.find(p => `${p.provider_id}:${p.version}` === providerKey);
  useEffect(() => { setAllowPaid(false); }, [providerKey, model, targetIndex, datasetIndex, boundContractIndex, evaluatorIndex, repetitions, concurrency]);
  const mutation = useMutation({
    mutationFn: async () => {
      const dataset = datasets.data!.items[datasetIndex]; const target = targets.data!.items[targetIndex]; const contract = contracts.data!.items[boundContractIndex]; const evaluator = evaluators.data!.sets[evaluatorIndex];
      if (realModel && (!selectedProvider || !model.trim() || !allowPaid)) throw new Error("explicit_paid_model_configuration_required");
      return api("/experiments", { method: "POST", body: JSON.stringify({ contract_version: realModel ? "1.2" : "1.0", experiment_id: `exp-${Date.now()}`, project_id: projectId, name, dataset_id: dataset.dataset_id, dataset_version: dataset.version, target_id: target.target_id, target_version: target.version, tool_contract_set_id: contract.set_id, tool_contract_version: contract.version, evaluator_set_id: evaluator.set_id, evaluator_set_version: evaluator.version, repetitions, concurrency, execution_mode: realModel ? "sandbox" : "dry_run", timeout_ms: realModel ? 300000 : 30000, ...(realModel && selectedProvider ? { provider_id: selectedProvider.provider_id, provider_version: String(selectedProvider.version), model: model.trim(), allow_paid: true } : {}), tags: {} }) });
    },
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["experiments"] }); onClose(); },
  });
  const ready = Boolean(datasets.data?.items[datasetIndex] && selectedTarget?.safe_for_eval && contracts.data?.items[boundContractIndex] && evaluators.data?.sets[evaluatorIndex] && name.trim() && Number.isInteger(repetitions) && repetitions >= 1 && repetitions <= 100 && Number.isInteger(concurrency) && concurrency >= 1 && concurrency <= 16 && (!realModel || (selectedProvider && model.trim() && allowPaid)));
  return <div className="modal-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget && !mutation.isPending) onClose(); }}><section className="modal" role="dialog" aria-modal="true" aria-label={t("createExperiment")}><div className="modal-header"><div><Beaker size={18} /><h2>{t("createExperiment")}</h2></div><button className="icon-button" title={t("close")} disabled={mutation.isPending} onClick={onClose}><X size={17} /></button></div>
    <div className="form-grid"><label className="full"><span>{text("Name", "名称")}</span><input value={name} onChange={event => setName(event.target.value)} /></label>
      <label><span>{text("Dataset version", "数据集版本")}</span><select aria-label={text("Dataset version", "数据集版本")} value={datasetIndex} onChange={event => setDatasetIndex(Number(event.target.value))}>{datasets.data?.items.map((item, index) => <option value={index} key={`${item.dataset_id}:${item.version}`}>{item.name} · {item.version}</option>)}</select></label>
      <label><span>{text("Target version", "目标版本")}</span><select aria-label={text("Target version", "目标版本")} value={targetIndex} onChange={event => setTargetIndex(Number(event.target.value))}>{targets.data?.items.map((item, index) => <option value={index} key={`${item.target_id}:${item.version}`}>{item.name} · {item.version}</option>)}</select></label>
      <label><span>{text("Tool contract", "工具合同")}</span><select aria-label={text("Tool contract", "工具合同")} value={boundContractIndex} disabled={realModel} onChange={event => setContractIndex(Number(event.target.value))}>{boundContractIndex < 0 ? <option value={-1}>{text("Target contract unavailable", "目标合同不可用")}</option> : null}{contracts.data?.items.map((item, index) => <option value={index} key={`${item.set_id}:${item.version}`}>{item.set_id} · {item.version}</option>)}</select></label>
      <label><span>{text("Evaluator set", "评测器集合")}</span><select aria-label={text("Evaluator set", "评测器集合")} value={evaluatorIndex} onChange={event => setEvaluatorIndex(Number(event.target.value))}>{evaluators.data?.sets.map((item, index) => <option value={index} key={`${item.set_id}:${item.version}`}>{item.set_id} · {item.version}</option>)}</select></label>
      <label><span>{text("Repetitions", "重复次数")}</span><input type="number" min={1} max={100} value={repetitions} onChange={event => setRepetitions(Number(event.target.value))} /></label><label><span>{text("Concurrency", "并发数")}</span><input type="number" min={1} max={16} value={concurrency} onChange={event => setConcurrency(Number(event.target.value))} /></label>
      {realModel ? <><label><span>{text("Provider version", "服务商版本")}</span><select aria-label={text("Provider version", "服务商版本")} value={providerKey} onChange={event => { setProviderKey(event.target.value); const provider = availableProviders.find(p => `${p.provider_id}:${p.version}` === event.target.value); setModel(provider?.model || ""); }}><option value="">{text("Select configured provider", "选择已配置服务商")}</option>{availableProviders.map(provider => <option key={`${provider.provider_id}:${provider.version}`} value={`${provider.provider_id}:${provider.version}`}>{provider.name} · v{provider.version}</option>)}</select></label><label><span>{text("Model", "模型")}</span><input value={model} onChange={event => setModel(event.target.value)} /></label>
        {providers.error ? <div className="full"><ErrorState error={providers.error} /></div> : !providers.isLoading && !availableProviders.length ? <Link className="full inline-notice" to="/settings/providers">{text("Configure an AI provider", "配置 AI 服务商")}</Link> : null}
        {selectedProvider ? <div className="full model-pin"><code>{selectedProvider.provider_id} / v{selectedProvider.version}</code><span>{selectedProvider.base_url}</span></div> : null}
        <label className="checkbox-label full"><input type="checkbox" checked={allowPaid} onChange={event => setAllowPaid(event.target.checked)} /><span>{text("I authorize paid model requests for this experiment. Business effects remain simulated.", "我授权本次实验发起付费模型请求。业务副作用仍为模拟。")}</span></label>
      </> : selectedTarget && ["http", "python"].includes(selectedTarget.adapter_type) ? <p className="full muted-text">{text("This external target keeps its own model and credentials.", "此外部 Target 保留自己的模型和凭据。")}</p> : null}
    </div>{mutation.error ? <div className="form-feedback inline-error" role="alert">{mutation.error.message}</div> : null}<div className="modal-actions"><button className="button secondary" disabled={mutation.isPending} onClick={onClose}>{t("cancel")}</button><button className="button primary" disabled={!ready || mutation.isPending} onClick={() => mutation.mutate()}><Play size={15} />{t("run")}</button></div></section></div>;
}
