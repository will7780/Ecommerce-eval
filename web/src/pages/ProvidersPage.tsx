import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Pencil, Plus, RefreshCw, Save, ShieldAlert, Unplug, X } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useApp } from "../app-context";
import { formatDate, formatDuration } from "../api";
import { EmptyState, ErrorState, LoadingState, PageHeader } from "../components/UiStates";
import { listProviders, postProvider, type CentralEnv, type Provider, type ProviderCheck, type ProviderConfigInput, type ProviderPreset } from "../provider-api";

export function ProvidersPage() {
  const { language, t } = useApp();
  const text = (en: string, cn: string) => language === "zh" ? cn : en;
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["providers"], queryFn: listProviders, retry: false });
  const [edit, setEdit] = useState<Provider | "new" | null>(null);
  const [credential, setCredential] = useState<Provider | null>(null);
  const [check, setCheck] = useState<Provider | null>(null);
  const [notice, setNotice] = useState("");
  const refresh = async () => { await client.invalidateQueries({ queryKey: ["providers"] }); };
  const sourceLabel = (source: string) => source === "process_env" ? text("Process environment override", "进程环境覆盖") : source === "central_env" ? text("Central .env", "中央 .env") : text("Not configured", "未配置");
  return <div className="page-stack providers-page">
    <PageHeader title={text("AI Providers", "AI 服务商")} actions={<><button className="icon-button" title={t("refresh")} onClick={() => query.refetch()}><RefreshCw size={16} /></button><button className="button primary" disabled={!query.data} onClick={() => { setNotice(""); setEdit("new"); }}><Plus size={15} />{text("New provider", "新增服务商")}</button></>} />
    <div className="settings-breadcrumb">{t("settings")} / {text("AI Providers", "AI 服务商")}</div>
    {notice ? <div className="inline-notice" role="status">{notice}</div> : null}
    {query.isLoading ? <LoadingState /> : query.error ? <ErrorState error={query.error} /> : !query.data?.items.length ? <EmptyState /> : <section className="provider-table-section"><div className="table-scroll"><table className="provider-table"><thead><tr><th>{text("Provider", "服务商")}</th><th>{text("Endpoint / model", "地址 / 模型")}</th><th>{text("Credential reference", "凭据变量名")}</th><th>{text("Configuration", "配置")}</th><th>{text("Last connection test", "上次连接测试")}</th><th>{t("actions")}</th></tr></thead><tbody>
      {query.data.items.map(provider => <tr key={provider.provider_id} data-testid={`provider-${provider.provider_id}`}>
        <td><strong>{provider.name}</strong><small>{provider.kind} · {provider.version == null ? text("Not saved", "未保存") : `v${provider.version}`}</small></td>
        <td><span className="provider-url">{provider.base_url || "-"}</span><small>{provider.model || text("Model not set", "未设置模型")}</small></td>
        <td><code>{provider.credential_env}</code><small>{sourceLabel(provider.credential_source)}</small></td>
        <td><span className={`status-badge ${!provider.enabled ? "neutral" : provider.configured ? "success" : "warning"}`}>{!provider.enabled ? text("Disabled", "已禁用") : provider.configured ? text("Configured", "已配置") : text("Not configured", "未配置")}</span></td>
        <td>{provider.last_check ? <><span className={`status-badge ${provider.last_check.status === "connected" ? "success" : "danger"}`}>{provider.last_check.status === "connected" ? text("Connected", "连接成功") : text("Failed", "连接失败")}</span><small>{formatDate(provider.last_check.checked_at)} · {formatDuration(provider.last_check.latency_ms)}</small></> : <span className="muted-text">{text("Not tested", "未测试")}</span>}</td>
        <td><div className="row-actions"><button className="icon-button" title={`${text("Edit", "编辑")} ${provider.name}`} onClick={() => { setNotice(""); setEdit(provider); }}><Pencil size={15} /></button><button className="icon-button" title={`${text("Set API key", "设置 API Key")} ${provider.name}`} disabled={provider.version == null || !query.data?.central_env.writable} onClick={() => { setNotice(""); setCredential(provider); }}><KeyRound size={15} /></button><button className="icon-button" title={`${text("Test connection", "测试连接")} ${provider.name}`} disabled={provider.version == null || !provider.enabled || !provider.configured || !provider.model} onClick={() => { setNotice(""); setCheck(provider); }}><Unplug size={15} /></button></div></td>
      </tr>)}
    </tbody></table></div></section>}
    {query.data ? <dl className="kv-list provider-source"><div><dt>{text("Credential store", "凭据存储")}</dt><dd>{query.data.central_env.source === "pointer" ? "AGENT_API_ENV_FILE" : text("Central environment file", "中央环境文件")}</dd></div><div><dt>{text("Access", "访问")}</dt><dd>{query.data.central_env.writable ? text("Local credential editing available", "可在本机编辑凭据") : text("Read-only; configure credentials on the server", "只读；请在服务端配置凭据")}</dd></div></dl> : null}
    {edit ? <ProviderEditor key={edit === "new" ? "new" : edit.provider_id} provider={edit === "new" ? null : edit} presets={query.data?.presets || []} onClose={() => setEdit(null)} onSaved={async () => { setEdit(null); setNotice(text("Configuration saved. No model request was made.", "配置已保存，未调用模型。")); await refresh(); }} /> : null}
    {credential && query.data ? <CredentialEditor provider={credential} central={query.data.central_env} onClose={() => setCredential(null)} onSaved={async () => { setCredential(null); setNotice(text("Central credential saved. Shared references use this value unless overridden by the process environment.", "中央凭据已保存。共享引用将使用此值；进程环境变量仍可覆盖。")); await refresh(); }} /> : null}
    {check ? <ConnectionCheck provider={check} onClose={() => setCheck(null)} onChecked={refresh} /> : null}
  </div>;
}

function ProviderDialog({ title, children, onClose, busy = false }: { title: string; children: ReactNode; onClose: () => void; busy?: boolean }) {
  const { t } = useApp();
  const element = useRef<HTMLElement>(null);
  const close = useRef(onClose);
  const working = useRef(busy);
  close.current = onClose; working.current = busy;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    element.current?.querySelector<HTMLElement>("input, button")?.focus();
    const handle = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !working.current) close.current();
      if (event.key !== "Tab") return;
      const focusable = [...(element.current?.querySelectorAll<HTMLElement>('input:not(:disabled), button:not(:disabled), select:not(:disabled), a[href]') || [])];
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener("keydown", handle);
    return () => { document.removeEventListener("keydown", handle); previous?.focus(); };
  }, []);
  return <div className="modal-backdrop"><section className="modal provider-modal" ref={element} role="dialog" aria-modal="true" aria-label={title}><div className="modal-header"><h2>{title}</h2><button type="button" className="icon-button" title={t("close")} disabled={busy} onClick={onClose}><X size={16} /></button></div>{children}</section></div>;
}

function ProviderEditor({ provider, presets, onClose, onSaved }: { provider: Provider | null; presets: ProviderPreset[]; onClose: () => void; onSaved: () => Promise<void> }) {
  const { language, t } = useApp();
  const text = (en: string, cn: string) => language === "zh" ? cn : en;
  const [form, setForm] = useState<ProviderConfigInput>(() => ({ provider_id: provider?.provider_id || "", kind: provider?.kind || "custom", name: provider?.name || "", base_url: provider?.base_url || "", model: provider?.model || "", credential_env: provider?.credential_env || "", enabled: provider?.enabled ?? true, allow_localhost: provider?.allow_localhost ?? false, endpoint_confirmed: false, expected_version: provider?.version ?? null }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const change = (values: Partial<ProviderConfigInput>) => { setError(""); setForm(old => ({ ...old, ...values })); };
  const submit = async (event: FormEvent) => {
    event.preventDefault(); if (busy || !form.endpoint_confirmed) return;
    setBusy(true); setError("");
    try { await postProvider<Provider>("", form); await onSaved(); } catch (e) { setError(e instanceof Error ? e.message : "provider_save_failed"); } finally { setBusy(false); }
  };
  return <ProviderDialog title={provider ? `${text("Edit provider", "编辑服务商")} / ${provider.name}` : text("New provider", "新增服务商")} onClose={onClose} busy={busy}><form onSubmit={submit}><div className="form-grid">
    {!provider ? <label className="full"><span>{text("Preset", "预设")}</span><select aria-label={text("Preset", "预设")} value={form.kind} onChange={event => { const preset = presets.find(p => p.kind === event.target.value); change(preset ? { ...preset, endpoint_confirmed: false } : { provider_id: "", kind: "custom", name: "", base_url: "", model: "", credential_env: "", endpoint_confirmed: false }); }}><option value="custom">{text("Custom compatible provider", "自定义兼容服务商")}</option>{presets.filter(p => p.kind !== "custom").map(p => <option key={p.kind} value={p.kind}>{p.name}</option>)}</select></label> : null}
    <label><span>{text("Provider ID", "服务商 ID")}</span><input aria-label={text("Provider ID", "服务商 ID")} required pattern="[a-z][a-z0-9_-]*" value={form.provider_id} disabled={Boolean(provider) || busy} onChange={e => change({ provider_id: e.target.value })} /></label>
    <label><span>{text("Name", "名称")}</span><input required value={form.name} disabled={busy} onChange={e => change({ name: e.target.value })} /></label>
    <label className="full"><span>Base URL</span><input type="url" required value={form.base_url} disabled={busy} autoComplete="off" placeholder="https://api.example.com/v1" onChange={e => change({ base_url: e.target.value, endpoint_confirmed: false })} /></label>
    <label><span>{text("Default model", "默认模型")}</span><input required value={form.model} disabled={busy} onChange={e => change({ model: e.target.value })} /></label>
    <label><span>{text("Credential environment variable", "凭据环境变量名")}</span><input required pattern="[A-Z][A-Z0-9_]*" value={form.credential_env} disabled={busy} autoComplete="off" onChange={e => change({ credential_env: e.target.value })} /></label>
    <label className="checkbox-label"><input type="checkbox" checked={form.enabled} disabled={busy} onChange={e => change({ enabled: e.target.checked })} /><span>{text("Enabled", "启用")}</span></label>
    {form.kind === "custom" ? <label className="checkbox-label"><input type="checkbox" checked={form.allow_localhost} disabled={busy} onChange={e => change({ allow_localhost: e.target.checked, endpoint_confirmed: false })} /><span>{text("Allow a local endpoint", "允许本地服务地址")}</span></label> : null}
    <label className="checkbox-label full"><input type="checkbox" checked={form.endpoint_confirmed} disabled={busy} onChange={e => change({ endpoint_confirmed: e.target.checked })} /><span>{text("I trust this endpoint to receive the referenced credential when a model request is explicitly started.", "我信任此地址在明确发起模型请求时接收所引用的凭据。")}</span></label>
  </div>{error ? <div className="form-feedback inline-error" role="alert">{error}</div> : null}<div className="modal-actions"><button type="button" className="button secondary" disabled={busy} onClick={onClose}>{t("cancel")}</button><button className="button primary" type="submit" disabled={busy || !form.endpoint_confirmed}><Save size={15} />{text("Save configuration", "保存配置")}</button></div></form></ProviderDialog>;
}

function CredentialEditor({ provider, central, onClose, onSaved }: { provider: Provider; central: CentralEnv; onClose: () => void; onSaved: () => Promise<void> }) {
  const { language, t } = useApp();
  const text = (en: string, cn: string) => language === "zh" ? cn : en;
  // The key lives only in the password input and request, never a query or mutation cache.
  const input = useRef<HTMLInputElement>(null);
  const expectedEnvVersion = useRef(central.version);
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { const field = input.current; return () => { if (field) field.value = ""; }; }, []);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!acknowledged || busy || !input.current?.value || expectedEnvVersion.current == null) return;
    let secret = input.current.value; input.current.value = "";
    setBusy(true); setError("");
    try { const request = postProvider(`/${encodeURIComponent(provider.provider_id)}/credential`, { version: provider.version, secret, expected_env_version: expectedEnvVersion.current, acknowledge_shared: true }); secret = ""; await request; await onSaved(); }
    catch (e) { setError(e instanceof Error ? e.message : "provider_credential_failed"); } finally { secret = ""; setBusy(false); }
  };
  return <ProviderDialog title={`${text("Set API key", "设置 API Key")} / ${provider.name}`} onClose={onClose} busy={busy}><form onSubmit={submit} autoComplete="off"><div className="form-grid"><div className="full provider-warning"><ShieldAlert size={18} /><p>{text("Replacing this central variable affects every agent that references it. Existing keys are never displayed.", "替换此中央变量会影响所有引用它的 Agent。不会显示现有密钥。")}</p></div><label className="full"><span>{provider.credential_env}</span><input aria-label="API Key" type="password" ref={input} required disabled={busy} autoComplete="new-password" spellCheck={false} autoCapitalize="none" /></label>{provider.credential_source === "process_env" ? <p className="full warning-text">{text("A process environment value currently overrides this central file. Saving here does not remove that override.", "当前进程环境变量覆盖中央文件。在此保存不会移除该覆盖。")}</p> : null}<label className="checkbox-label full"><input type="checkbox" checked={acknowledged} disabled={busy} onChange={e => setAcknowledged(e.target.checked)} /><span>{text("I understand this updates a shared central credential.", "我理解这会更新共享的中央凭据。")}</span></label></div>{error ? <div className="form-feedback inline-error" role="alert">{error}</div> : null}<div className="modal-actions"><button type="button" className="button secondary" disabled={busy} onClick={onClose}>{t("cancel")}</button><button className="button primary" disabled={busy || !acknowledged || central.version == null}><Save size={15} />{text("Save API key", "保存 API Key")}</button></div></form></ProviderDialog>;
}

function ConnectionCheck({ provider, onClose, onChecked }: { provider: Provider; onClose: () => void; onChecked: () => Promise<void> }) {
  const { language, t } = useApp();
  const text = (en: string, cn: string) => language === "zh" ? cn : en;
  const [allowed, setAllowed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ProviderCheck | null>(null);
  const [error, setError] = useState("");
  const submit = async () => {
    if (!allowed || busy) return;
    setBusy(true); setError(""); setResult(null);
    try { setResult(await postProvider<ProviderCheck>(`/${encodeURIComponent(provider.provider_id)}/check`, { version: provider.version, allow_paid: true, model: provider.model })); await onChecked(); } catch (e) { setError(e instanceof Error ? e.message : "provider_check_failed"); } finally { setBusy(false); setAllowed(false); }
  };
  return <ProviderDialog title={`${text("Test connection", "测试连接")} / ${provider.name}`} onClose={onClose} busy={busy}><div className="form-grid"><dl className="kv-list full"><div><dt>Base URL</dt><dd>{provider.base_url}</dd></div><div><dt>{text("Model", "模型")}</dt><dd>{provider.model} / v{provider.version}</dd></div></dl><label className="checkbox-label full"><input type="checkbox" checked={allowed} disabled={busy} onChange={e => setAllowed(e.target.checked)} /><span>{text("I authorize one connection test. It sends a model request and may incur charges.", "我授权一次连接测试。它会发送模型请求，可能产生费用。")}</span></label>{result ? <div className="full" role="status"><span className={`status-badge ${result.status === "connected" ? "success" : "danger"}`}>{result.status === "connected" ? text("Connected", "连接成功") : text("Connection failed", "连接失败")}</span><p>{formatDuration(result.latency_ms)} · {formatDate(result.checked_at)}</p></div> : null}</div>{error ? <div className="form-feedback inline-error" role="alert">{error}</div> : null}<div className="modal-actions"><button className="button secondary" disabled={busy} onClick={onClose}>{t("close")}</button><button className="button primary" disabled={!allowed || busy} onClick={submit}><Unplug size={15} />{text("Run connection test", "执行连接测试")}</button></div></ProviderDialog>;
}
