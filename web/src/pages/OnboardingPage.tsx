import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Check, CheckCircle2, Download, FileUp, FlaskConical, Link2, Play, Plus, ShieldCheck, Upload, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, projectQuery } from "../api";
import { useApp } from "../app-context";
import { EmptyState, ErrorState, LoadingState, PageHeader } from "../components/UiStates";
import { CapabilityMappings, type CapabilityBinding } from "../components/CapabilityMappings";
import { BusinessRequirements, businessRequirements } from "../components/BusinessAcceptance";
import type { Project, TargetDefinition } from "../types";

type Mode = "demo" | "import" | "connect";
interface UploadFile { name: string; content: string }
interface Preview { import_id: string; status: string; counts: Record<string, number>; errors: Array<{ file?: string; line?: number; field?: string; code: string }>; preview: unknown; expires_at?: string }
interface Template { template_id?: string; scenario_id?: string; case_id?: string; id?: string; name?: string; title?: string; direction?: string; version?: string; [key: string]: unknown }
type Binding = CapabilityBinding;
const directions = [
  ["I", "Intent & boundaries", "意图与边界"], ["C", "Company rules", "公司资料与规则"], ["T", "Tools & dependencies", "工具与依赖"], ["P", "Parameters & preconditions", "参数与前置检查"],
  ["A", "Artifacts & review", "产物质量与审核"], ["M", "Conversation", "多轮连续性"], ["R", "Recovery & honesty", "恢复与结果诚实"], ["S", "Safety, efficiency & cost", "权限、效率与成本"],
];
const templateId = (v: Template) => String(v.template_id || v.scenario_id || v.case_id || v.id || "");
const uid = () => Date.now().toString(36);
const post = <T,>(path: string, body: unknown) => api<T>(path, { method: "POST", body: JSON.stringify(body) });

export function OnboardingPage() {
  const { language, projectId, setProjectId } = useApp();
  const zh = language === "zh";
  const text = (en: string, cn: string) => zh ? cn : en;
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const client = useQueryClient();
  const [mode, setMode] = useState<Mode>(params.get("mode") === "import" ? "import" : params.get("mode") === "demo" ? "demo" : "connect");
  const [step, setStep] = useState(0);
  const [bankVersion, setBankVersion] = useState(["0.2.0", "0.3.0", "0.3.1"].includes(params.get("bank_version") || "") ? params.get("bank_version")! : "0.3.1");
  const [demoActor, setDemoActor] = useState("reference_policy");
  const [kind, setKind] = useState(params.get("kind") || "trace");
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [newProject, setNewProject] = useState("");
  const [resourceId, setResourceId] = useState(`import-${uid()}`);
  const [version, setVersion] = useState("1.0.0");
  const [columns, setColumns] = useState<Record<string, string>>({});
  const [targetIndex, setTargetIndex] = useState(-1);
  const [targetKind, setTargetKind] = useState("http");
  const [endpoint, setEndpoint] = useState("");
  const [credentialEnv, setCredentialEnv] = useState("");
  const [safe, setSafe] = useState(false);
  const [checkResult, setCheckResult] = useState<Record<string, unknown> | null>(null);
  const [bindings, setBindings] = useState<Binding[]>([]);
  const [mappingValid, setMappingValid] = useState(true);
  const [assetRefs, setAssetRefs] = useState<Array<{ kind: string; asset_id: string; version: string }>>([]);
  const [selection, setSelection] = useState<string[]>([]);
  const [selectedAll, setSelectedAll] = useState(true);
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => { setPreview(null); setCheckResult(null); setConfirmed(false); setResult(null); setTargetIndex(-1); }, [projectId]);
  const projects = useQuery({ queryKey: ["projects"], queryFn: () => api<{ items: Project[] }>("/projects") });
  const templates = useQuery({ queryKey: ["scenario-templates", bankVersion], queryFn: () => api<{ items: Template[] }>(`/scenario-templates?template_version=${bankVersion}`) });
  const targets = useQuery({ queryKey: ["targets", projectId], queryFn: () => api<{ items: TargetDefinition[] }>(`/targets${projectQuery(projectId)}`), enabled: Boolean(projectId) });
  const capabilityKey = Array.from(new Set((templates.data?.items || []).filter(item => item.contract_version !== "1.2" && !businessRequirements(item.business_requirements).length).flatMap(item => Array.isArray(item.capabilities) ? item.capabilities as string[] : []))).sort().join("|");
  // Defaults must exist in the same render that mounts the mapping editor.
  const resolvedBindings: Binding[] = capabilityKey ? capabilityKey.split("|").map(id => bindings.find(b => b.capability_id === id) || { capability_id: id, tool_id: id, argument_mapping: {} }) : [];
  const bankReady = templates.isSuccess && Boolean(templates.data?.items.length);
  useEffect(() => { setMappingValid(true); }, [bankVersion, capabilityKey]);
  const chosenIds = selectedAll ? (templates.data?.items || []).map(templateId) : selection;
  const chosenTemplates = (templates.data?.items || []).filter(item => chosenIds.includes(templateId(item)));
  const hasBusinessCases = chosenTemplates.some(item => item.contract_version === "1.2" || businessRequirements(item.business_requirements).length);
  const needsLegacyMapping = chosenTemplates.some(item => item.contract_version !== "1.2" && !businessRequirements(item.business_requirements).length);
  const requiredEvidence = [...new Set(chosenTemplates.flatMap(item => businessRequirements(item.business_requirements).flatMap(r => r.applicable === false ? [] : r.required_evidence)))];
  const steps = [text("Project & mode", "项目与模式"), text("Upload / connect", "上传或连接"), text("Validate & preview", "校验与预览"), hasBusinessCases ? text("Evidence & assets", "证据与资料") : text("Map capabilities", "能力与资料映射"), text("Cases & gates", "题目与门禁"), text("Connection check", "试接入"), text("Confirm", "确认")];
  const definition = { contract_version: "1.1", target_id: resourceId, version, name: resourceId, adapter_type: "http", safe_for_eval: safe, config: { base_url: endpoint, ...(credentialEnv ? { credential_env: credentialEnv } : {}) }, tags: { execution: "sandbox" } };
  const chosenTarget = targets.data?.items[targetIndex];
  const checkPayload = { project_id: projectId, ...(targetKind === "registered" && chosenTarget ? { target_id: chosenTarget.target_id, target_version: chosenTarget.version } : { definition }), ...(hasBusinessCases ? { template_ids: chosenIds, template_version: bankVersion } : {}) };
  const checkKey = JSON.stringify([checkPayload, mode, bankVersion, chosenIds, resolvedBindings, assetRefs]);
  const currentCheckKey = useRef(checkKey);
  currentCheckKey.current = checkKey;
  useEffect(() => { setCheckResult(null); setConfirmed(false); }, [checkKey]);
  const run = async (work: () => Promise<void>) => { setError(null); setBusy(true); try { await work(); } catch (e) { setError(e); } finally { setBusy(false); } };
  const invalidateDraft = () => { setPreview(null); setConfirmed(false); };
  const changeMode = (next: Mode) => { setMode(next); setStep(0); setPreview(null); setResult(null); setCheckResult(null); setConfirmed(false); };
  const readFiles = async (list: FileList | null) => {
    if (!list) return;
    await run(async () => {
      const items = Array.from(list);
      if (items.some(f => f.size > 10 * 1024 * 1024) || items.reduce((s, f) => s + f.size, 0) > 50 * 1024 * 1024) throw Error("upload_size_limit");
      if (items.some(f => !/\.(jsonl?|csv|md|txt)$/i.test(f.name))) throw Error("upload_extension_not_allowed");
      const loaded: UploadFile[] = [];
      for (const file of items) loaded.push({ name: file.name, content: await file.text() });
      setFiles(loaded); invalidateDraft();
    });
  };
  const previewFiles = () => run(async () => {
    const p = await post<Preview>("/imports/preview", { project_id: projectId, kind, files, options: { id: resourceId, name: resourceId, version, column_mapping: columns } });
    setPreview(p); setStep(2);
  });
  const downloadTemplate = () => run(async () => {
    const data = await api<{ filename: string; content: string }>(`/imports/templates?kind=${encodeURIComponent(kind)}`);
    const blob = new Blob([data.content], { type: "text/plain" });
    const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = data.filename; a.click(); URL.revokeObjectURL(url);
  });
  const createProject = () => run(async () => {
    const id = `project-${uid()}`;
    await post("/projects", { project_id: id, name: newProject });
    await client.invalidateQueries({ queryKey: ["projects"] }); setProjectId(id); setNewProject("");
  });
  const doCheck = () => run(async () => {
    const requestedKey = checkKey;
    const response = await post<Record<string, unknown>>("/onboarding/check", checkPayload);
    if (currentCheckKey.current === requestedKey) setCheckResult(response);
  });
  const commit = () => run(async () => {
    if (mode === "import") {
      if (!preview || preview.status !== "ready") throw Error("preview_not_ready");
      setResult(await post<Record<string, unknown>>(`/imports/${preview.import_id}/commit`, {}));
      setFiles([]);
    } else if (mode === "demo") {
      const refs = await post<Record<string, unknown>>("/onboarding/demo", { project_id: projectId, template_ids: chosenIds, bank_version: bankVersion });
      setResult(refs);
      if (refs.requires_explicit_model_configuration === true) {
        const specs = refs.candidate_experiment_specs;
        if (!Array.isArray(specs) || !specs.length) throw Error("candidate_configuration_missing");
        const spec = specs[0] as Record<string, unknown>;
        const selection = new URLSearchParams({ create: "1", target: String(spec.target_id), target_version: String(spec.target_version), dataset: String(spec.dataset_id), dataset_version: String(spec.dataset_version), evaluator: String(spec.evaluator_set_id), evaluator_version: String(spec.evaluator_set_version) });
        await client.invalidateQueries();
        navigate(`/experiments?${selection.toString()}`);
        return;
      }
      const selectedSpec = demoActor === "reference_policy" ? refs.policy_experiment_spec : refs.experiment_spec;
      if (!selectedSpec) throw Error("demo_target_unavailable");
      if (selectedSpec) {
        const spec = selectedSpec as Record<string, unknown>;
        const exp = await post<{ experiment_id: string }>("/experiments", { ...spec, experiment_id: `${demoActor === "reference_policy" ? "policy" : "reference"}-${uid()}`, project_id: projectId });
        navigate(`/experiments?selected=${encodeURIComponent(exp.experiment_id)}`);
      }
    } else {
      let target = chosenTarget;
      if (targetKind === "http") target = await post<TargetDefinition>(`/targets${projectQuery(projectId)}`, definition);
      const dataset = await post<Record<string, unknown>>("/scenario-templates/bank/instantiate", { project_id: projectId, dataset_id: `onboarding-${uid()}`, version, name: text("Commerce readiness", "电商能力测评"), template_ids: chosenIds, template_version: bankVersion, bindings: needsLegacyMapping ? resolvedBindings.filter(b => b.tool_id.trim()) : [], assets: assetRefs.length ? assetRefs : null });
      if (dataset.status === "invalid") throw Error(JSON.stringify(dataset.errors || "scenario_not_ready"));
      setResult({ ...dataset, target_id: target?.target_id, target_version: target?.version, status: "ready_to_configure_experiment" });
    }
    await client.invalidateQueries();
  });
  const connectionOK = checkResult?.connection_ready === true || checkResult?.ready === true || checkResult?.ok === true || checkResult?.status === "ready" || checkResult?.status === "ok";
  const readiness = checkResult?.business_readiness as { ready?: boolean } | undefined;
  const checkOK = connectionOK && (!hasBusinessCases || readiness?.ready === true);
  const canNext = Boolean(projectId) && !busy && (mode === "import" || bankReady) && (step !== 3 || mode !== "connect" || !needsLegacyMapping || mappingValid) && (step !== 1 || mode !== "import" || files.length > 0) && (step !== 2 || mode !== "import" || preview?.status === "ready") && (step !== 4 || mode === "import" || chosenIds.length > 0) && (step !== 5 || mode !== "connect" || checkOK);
  const next = () => { if (step === 1 && mode === "import") void previewFiles(); else setStep(v => Math.min(6, v + 1)); };
  return <div className="page-stack onboarding-page">
    <PageHeader title={text("Connect & import", "接入与导入")} actions={<Link to="/datasets" className="button secondary"><ArrowLeft size={15} />{text("Datasets", "数据集")}</Link>} />
    {mode !== "import" && !bankReady ? <div role="status">{templates.isError ? <ErrorState error={templates.error} /> : templates.isPending ? <LoadingState /> : <EmptyState title={text("No scenarios available for this version", "此版本暂无可用题目")} />}</div> : null}
    {step === 0 && mode !== "import" ? <label className="bank-version-picker"><span>{text("Bank version", "题库版本")}</span><select aria-label={text("Bank version", "题库版本")} value={bankVersion} onChange={event => { setBankVersion(event.target.value); setCheckResult(null); setConfirmed(false); setBindings([]); setSelectedAll(true); setSelection([]); }}><option value="0.3.1">0.3.1 · {text("Business acceptance", "业务验收")}</option><option value="0.3.0">0.3.0 · {text("Original business bank", "原版业务题库")}</option><option value="0.2.0">0.2.0 · {text("Legacy tool-mapped bank", "旧版工具映射题库")}</option></select></label> : null}
    <ol className="wizard-steps">{steps.map((s, i) => <li key={s} className={step === i ? "current" : i < step ? "complete" : ""}><span>{i < step ? <Check size={12} /> : i + 1}</span>{s}</li>)}</ol>
    {result ? <section className="wizard-section"><div className="completion-heading"><CheckCircle2 size={24} /><h2>{text("Saved", "已保存")}</h2></div><pre className="json-view">{JSON.stringify(result, null, 2)}</pre><div className="wizard-actions"><Link className="button primary" to={mode === "import" && kind === "trace" ? "/traces" : "/experiments"}><ArrowRight size={15} />{text("View results", "查看记录")}</Link><button className="button secondary" onClick={() => { setResult(null); setStep(0); invalidateDraft(); }}>{text("Start another", "继续接入")}</button></div></section> : <>
    {step === 0 ? <section className="wizard-section"><div className="form-grid"><label className="full"><span>{text("Project", "项目")}</span><select aria-label="Onboarding project" value={projectId} onChange={e => { setProjectId(e.target.value); invalidateDraft(); setCheckResult(null); }}><option value="">{text("Select project", "选择项目")}</option>{projects.data?.items.map(p => <option key={p.project_id} value={p.project_id}>{p.name}</option>)}</select></label><label><span>{text("New project name", "新项目名称")}</span><input value={newProject} onChange={e => setNewProject(e.target.value)} /></label><div className="form-command"><button className="button secondary" disabled={!newProject.trim() || busy} onClick={createProject}><Plus size={15} />{text("Create project", "创建项目")}</button></div></div><div className="mode-options" role="radiogroup" aria-label={text("Mode", "模式")}>{([ ["demo", FlaskConical, text("Try the standard bank", "体验内置题库"), text("32 scenarios · synthetic data · configure a model before running", "32 道场景题 · 虚构资料 · 开考前配置模型")], ["import", FileUp, text("Import existing records", "导入已有记录"), text("Traces, cases, contracts or business assets", "运行轨迹、考题、合同或业务资料")], ["connect", Link2, text("Connect your agent", "连接自己的 Agent"), text("HTTP target or registered Python target", "HTTP 服务或已登记的 Python Target")] ] as const).map(([value, Icon, label, note]) => <label className={`mode-option ${mode === value ? "selected" : ""}`} key={value}><input type="radio" name="onboarding-mode" checked={mode === value} onChange={() => changeMode(value)} /><Icon size={20} /><span><strong>{label}</strong><small>{note}</small></span></label>)}</div></section> : null}
    {step === 1 ? <section className="wizard-section"><h2>{steps[1]}</h2>{mode === "import" ? <><div className="form-grid"><label><span>{text("Data type", "数据类型")}</span><select value={kind} onChange={e => { setKind(e.target.value); invalidateDraft(); }}>{[["trace", "Agent traces", "Agent 运行轨迹"], ["dataset", "Evaluation cases", "考题数据集"], ["tool-contracts", "Tool contracts", "工具合同"], ["products", "Product data", "商品资料"], ["rules", "Company rules", "公司规则"], ["evaluator-set", "Evaluator set", "评测器集合"]].map(([v, en, cn]) => <option key={v} value={v}>{text(en, cn)}</option>)}</select></label><label><span>{text("Resource ID", "资源 ID")}</span><input value={resourceId} onChange={e => { setResourceId(e.target.value); invalidateDraft(); }} /></label><label><span>{text("Version", "版本")}</span><input value={version} onChange={e => { setVersion(e.target.value); invalidateDraft(); }} /></label><div className="form-command"><button className="button secondary" onClick={downloadTemplate}><Download size={15} />{text("Download template", "下载模板")}</button></div></div><label className="upload-zone"><Upload size={25} /><strong>{text("Choose files", "选择文件")}</strong><span>JSON / JSONL / CSV / Markdown / TXT · 10 MB / file · 50 MB total</span><input aria-label={text("Upload files", "上传文件")} type="file" accept=".json,.jsonl,.csv,.md,.txt" multiple onChange={e => void readFiles(e.target.files)} /></label><ul className="upload-list">{files.map(f => <li key={f.name}><FileUp size={16} /><span>{f.name}</span><small>{new Blob([f.content]).size.toLocaleString()} B</small><button className="icon-button" title={text("Remove", "移除")} onClick={() => { setFiles(files.filter(x => x !== f)); invalidateDraft(); }}><X size={14} /></button></li>)}</ul>{kind === "products" ? <div className="form-grid">{["row_id", "sku", "price", "currency"].map(field => <label key={field}><span>{field}</span><input placeholder={field} value={columns[field] || ""} onChange={e => { setColumns({ ...columns, [field]: e.target.value }); invalidateDraft(); }} /></label>)}</div> : null}</> : mode === "connect" ? <><div className="segmented"><button className={targetKind === "http" ? "active" : ""} onClick={() => { setTargetKind("http"); setCheckResult(null); }}>HTTP</button><button className={targetKind === "registered" ? "active" : ""} onClick={() => { setTargetKind("registered"); setCheckResult(null); }}>{text("Registered target", "已登记 Target")}</button></div><div className="form-grid">{targetKind === "registered" ? <label className="full"><span>Target</span><select aria-label="Target" value={targetIndex} onChange={e => { setTargetIndex(Number(e.target.value)); setCheckResult(null); }}><option value={-1}>{text("Select target", "选择 Target")}</option>{targets.data?.items.map((target, i) => <option key={`${target.target_id}:${target.version}`} value={i}>{target.name} · {target.version} · {target.adapter_type}</option>)}</select></label> : <><label className="full"><span>Endpoint</span><input value={endpoint} placeholder="http://127.0.0.1:9000" onChange={e => { setEndpoint(e.target.value); setCheckResult(null); }} /></label><label><span>Target ID</span><input value={resourceId} onChange={e => { setResourceId(e.target.value); setCheckResult(null); }} /></label><label><span>{text("Version", "版本")}</span><input value={version} onChange={e => { setVersion(e.target.value); setCheckResult(null); }} /></label><label className="full"><span>{text("Server credential reference (optional)", "服务端凭据变量名（可选）")}</span><input value={credentialEnv} placeholder="MY_AGENT_TOKEN" autoComplete="off" onChange={e => { setCredentialEnv(e.target.value); setCheckResult(null); }} /></label><label className="checkbox-label full"><input type="checkbox" checked={safe} onChange={e => { setSafe(e.target.checked); setCheckResult(null); }} /><span>{text("This target is safe for evaluation (dry-run / sandbox only)", "此 Target 可用于测评（仅 dry-run / sandbox）")}</span></label></>}</div></> : hasBusinessCases ? <div className="candidate-surfaces"><section><FileUp size={20} /><h3>{text("Business interface candidate", "业务接口型考生")}</h3></section><section><Link2 size={20} /><h3>{text("File editing candidate", "文件编辑型考生")}</h3></section></div> : <><div className="mode-options" role="radiogroup" aria-label="Demo execution"><label className="mode-option"><input type="radio" name="demo-actor" checked={demoActor === "reference_policy"} onChange={() => setDemoActor("reference_policy")} /><span><strong>{text("Independent policy baseline", "独立策略基线")}</strong><small>{text("Rule-based candidate · simulated tools · no LLM", "规则型考生 · 模拟工具 · 不调用 LLM")}</small></span></label><label className="mode-option"><input type="radio" name="demo-actor" checked={demoActor === "reference_fixture"} onChange={() => setDemoActor("reference_fixture")} /><span><strong>{text("Reference traces", "参考轨迹")}</strong><small>{text("Scoring conformance fixtures · not candidate scores", "评分器校验样例 · 不是考生成绩")}</small></span></label></div></>}</section> : null}
    {step === 2 ? <section className="wizard-section"><h2>{steps[2]}</h2>{mode === "import" ? preview ? <><div className="tag-list"><span>{preview.status}</span>{Object.entries(preview.counts || {}).map(([k, v]) => <span key={k}>{k}: {v}</span>)}</div>{preview.errors.length ? <div className="table-scroll"><table><thead><tr><th>{text("File", "文件")}</th><th>{text("Line", "行")}</th><th>{text("Field", "字段")}</th><th>{text("Error", "错误")}</th></tr></thead><tbody>{preview.errors.map((e, i) => <tr key={i}><td>{e.file}</td><td>{e.line}</td><td>{e.field}</td><td>{e.code}</td></tr>)}</tbody></table></div> : null}<pre className="json-view preview-json">{JSON.stringify(preview.preview, null, 2)}</pre></> : null : <><ShieldCheck size={24} /><dl className="kv-list"><div><dt>{text("Mode", "模式")}</dt><dd>{mode === "demo" ? hasBusinessCases ? text("Install only / no execution", "仅安装 / 不执行") : `${demoActor} / simulated` : "dry_run / sandbox"}</dd></div><div><dt>Protocol</dt><dd>1.0 / 1.1 / 1.2</dd></div><div><dt>{text("Target", "被测对象")}</dt><dd>{mode === "demo" ? hasBusinessCases ? text("Two real-model candidates", "两种真实模型考生") : demoActor : targetKind === "http" ? endpoint : chosenTarget?.name || "-"}</dd></div></dl></>}</section> : null}
    {step === 3 ? <section className="wizard-section"><h2>{steps[3]}</h2>{mode === "connect" ? <>{hasBusinessCases ? <EvidenceReadiness required={requiredEvidence} zh={zh} result={checkResult?.business_readiness} /> : null}{needsLegacyMapping ? <CapabilityMappings key={`${bankVersion}:${capabilityKey}`} bindings={resolvedBindings} onChange={setBindings} onValidity={setMappingValid} zh={zh} /> : null}<h3>{text("Business asset references", "业务资料引用")}</h3>{assetRefs.map((asset, i) => <div className="form-grid" key={i}><label><span>{text("Kind", "类型")}</span><select value={asset.kind} onChange={e => setAssetRefs(assetRefs.map((a,j) => i === j ? {...a, kind:e.target.value} : a))}><option value="products">Products</option><option value="rules">Company rules</option></select></label><label><span>Asset ID</span><input value={asset.asset_id} onChange={e => setAssetRefs(assetRefs.map((a,j) => i === j ? {...a, asset_id:e.target.value} : a))} /></label><label><span>Version</span><input value={asset.version} onChange={e => setAssetRefs(assetRefs.map((a,j) => i === j ? {...a, version:e.target.value} : a))} /></label><button className="icon-button" title={text("Remove asset", "移除资料")} onClick={() => setAssetRefs(assetRefs.filter((_,j) => i !== j))}><X size={15} /></button></div>)}<button className="button secondary" onClick={() => setAssetRefs([...assetRefs,{kind:"products",asset_id:"",version:"1.0.0"}])}><Plus size={15} />{text("Add asset reference", "添加资料引用")}</button></> : <dl className="kv-list"><div><dt>{text("Mapping", "映射")}</dt><dd>{mode === "demo" ? text("Standard capabilities / synthetic assets", "标准能力 / 虚构资料") : text("Canonical contract fields", "标准合同字段")}</dd></div><div><dt>{text("Data", "数据")}</dt><dd>{mode === "import" ? kind : "20 synthetic products"}</dd></div></dl>}</section> : null}
    {step === 4 ? <section className="wizard-section"><h2>{steps[4]}</h2>{mode === "import" ? <div className="reference-banner"><ShieldCheck size={20} /><span>{text("Imported traces remain unscored until a case, contracts and evaluators are bound.", "导入轨迹保留为未评分；绑定考题、工具合同和评测器后再评分。")}</span></div> : <><label className="checkbox-label"><input type="checkbox" checked={selectedAll} onChange={e => { setSelectedAll(e.target.checked); setSelection([]); }} />{text("All 32 scenarios", "全部 32 道题")}</label><div className="direction-grid">{directions.map(([code, en, cn]) => <section className="direction-group" key={code}><h3>{code} · {text(en, cn)}</h3>{(templates.data?.items || []).filter(v => templateId(v).startsWith(code)).map(v => { const id = templateId(v); return <div className="wizard-case" key={id}><label className="checkbox-label"><input type="checkbox" checked={chosenIds.includes(id)} onChange={e => { setSelectedAll(false); setSelection(e.target.checked ? [...chosenIds, id] : chosenIds.filter(x => x !== id)); }} /><span><code>{id}</code> {String(v.name || v.title || id)}</span></label><details className="case-gates"><summary>{text("Required gates", "必过门禁")}</summary>{v.contract_version === "1.2" || businessRequirements(v.business_requirements).length ? <BusinessRequirements requirements={businessRequirements(v.business_requirements)} /> : <pre className="json-view">{JSON.stringify(v.behavior_criteria || {}, null, 2)}</pre>}</details></div>; })}</section>)}</div>{templates.error ? <ErrorState error={templates.error} /> : null}<div className="selection-total">{chosenIds.length} / 32 {text("selected", "已选")}</div></>}</section> : null}
    {step === 5 ? <section className="wizard-section"><h2>{steps[5]}</h2>{mode === "connect" ? <><button className="button secondary" disabled={busy || (targetKind === "registered" ? !chosenTarget : !endpoint || !safe)} onClick={doCheck}><Link2 size={16} />{text("Check connection", "检查连接")}</button>{checkResult ? <pre className="json-view">{JSON.stringify(checkResult, null, 2)}</pre> : null}{hasBusinessCases ? <EvidenceReadiness required={requiredEvidence} zh={zh} result={checkResult?.business_readiness} /> : null}</> : <div className="reference-banner"><CheckCircle2 size={20} /><span>{mode === "demo" ? hasBusinessCases ? text("The bank and both candidates will be installed. No model request is made.", "将安装题库和两种考生，不会发送模型请求。") : text("Local reference actor. No external connection required.", "本地参考执行器，无需外部连接。") : text("Preview validated. No Agent execution requested.", "预览已校验，不会调用 Agent。")}</span></div>}</section> : null}
    {step === 6 ? <section className="wizard-section"><h2>{steps[6]}</h2><dl className="kv-list"><div><dt>{text("Project", "项目")}</dt><dd>{projectId}</dd></div><div><dt>{text("Action", "操作")}</dt><dd>{mode === "import" ? text("Commit import (not evaluated)", "确认导入（未评分）") : mode === "demo" ? hasBusinessCases ? text("Install bank and configure an experiment", "安装题库并配置实验") : demoActor === "reference_policy" ? text("Evaluate independent policy (no LLM)", "评测独立策略（不调用 LLM）") : text("Generate reference traces (unscored)", "生成参考轨迹（非考生成绩）") : text("Save target and mapped dataset", "保存 Target 和映射题库")}</dd></div><div><dt>{text("Scope", "范围")}</dt><dd>{mode === "import" ? `${files.length} files` : `${chosenIds.length} / 32 scenarios`}</dd></div></dl><label className="checkbox-label"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />{text("I confirm this configuration and sanitized data.", "我确认以上配置与脱敏数据。")}</label></section> : null}
    {error ? <ErrorState error={error} /> : null}
    <footer className="wizard-actions"><button className="button secondary" disabled={step === 0 || busy} onClick={() => { setStep(v => v - 1); setConfirmed(false); }}><ArrowLeft size={15} />{text("Back", "上一步")}</button>{step < 6 ? <button className="button primary" disabled={!canNext} onClick={next}>{text("Continue", "继续")}<ArrowRight size={15} /></button> : <button className="button primary" disabled={!confirmed || busy} onClick={commit}>{mode === "demo" ? <Play size={15} /> : <Check size={15} />}{busy ? text("Working...", "处理中…") : text("Confirm", "确认")}</button>}</footer>
    </>}
  </div>;
}

function EvidenceReadiness({ required, zh, result }: { required: string[]; zh: boolean; result?: unknown }) {
  const readiness = result && typeof result === "object" ? result as Record<string, unknown> : null;
  const types = Array.isArray(readiness?.required_evidence) ? readiness.required_evidence as string[] : required;
  const missing = Array.isArray(readiness?.missing_evidence) ? readiness.missing_evidence as string[] : [];
  return <section className="evidence-readiness"><h3>{zh ? "所需业务证据" : "Required business evidence"}</h3><div className="table-scroll"><table><thead><tr><th>{zh ? "证据" : "Evidence"}</th><th>{zh ? "采集就绪状态" : "Collection readiness"}</th></tr></thead><tbody>{types.map(type => <tr key={type}><td><code>{type}</code></td><td><span className={`status-badge ${missing.includes(type) ? "warning" : readiness?.ready === true ? "success" : "neutral"}`}>{missing.includes(type) ? (zh ? "缺少采集能力" : "Collection unavailable") : readiness?.ready === true ? (zh ? "采集器已就绪" : "Collector ready") : (zh ? "尚未采集核验" : "Not yet collected / verified")}</span></td></tr>)}</tbody></table></div>{readiness ? <dl className="kv-list"><div><dt>{zh ? "采集器" : "Collector"}</dt><dd>{typeof readiness.collector === "string" ? readiness.collector : JSON.stringify(readiness.collector ?? null)}</dd></div><div><dt>{zh ? "原因" : "Reason"}</dt><dd>{String(readiness.reason_code || "-")}</dd></div></dl> : null}</section>;
}
