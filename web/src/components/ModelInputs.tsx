import { useState } from "react";
import { useApp } from "../app-context";
import type { TraceDetail, TraceEvent } from "../types";

type Message = { role: string; content?: unknown; tool_calls?: unknown; tool_call_id?: string; name?: string; truncated?: boolean };
type Snapshot = { snapshot_id?: string; model_call_id?: string; round?: number; messages?: Message[]; tools?: unknown; captured?: boolean; truncated?: boolean; redacted?: boolean; omission_reason?: string; source?: string };

export function modelSnapshots(events: TraceEvent[]): Snapshot[] {
  return [...events].sort((a, b) => a.sequence - b.sequence).filter(e => e.kind === "model.input").map(e => {
    const value = e.attributes.snapshot || e.attributes;
    return value as Snapshot;
  });
}

function MessageText({ message }: { message: Message }) {
  return <pre className="json-view input-message">{typeof message.content === "string" ? message.content : JSON.stringify(message.content ?? "", null, 2)}{message.tool_calls ? `\n${JSON.stringify(message.tool_calls, null, 2)}` : ""}</pre>;
}

export function ModelInputs({ data, context = false }: { data: TraceDetail; context?: boolean }) {
  const { language } = useApp();
  const zh = language === "zh";
  const snapshots = modelSnapshots(data.trace.events);
  const [index, setIndex] = useState(0);
  const snapshot = snapshots[Math.min(index, Math.max(0, snapshots.length - 1))];
  const messages = Array.isArray(snapshot?.messages) ? snapshot.messages : [];
  const missing = zh ? "未采集" : "Not captured";
  const latestUser = messages.filter(m => m.role === "user").slice(-1);
  const request = data.trace.input;
  return <section className="model-inputs">
    <div className="input-toolbar"><label>{zh ? "模型调用" : "Model call"}<select aria-label={zh ? "模型调用" : "Model call"} value={index} onChange={e => setIndex(Number(e.target.value))} disabled={!snapshots.length}>{snapshots.length ? snapshots.map((s, i) => <option key={i} value={i}>#{i + 1} · {s.model_call_id || s.snapshot_id || `Round ${s.round ?? i}`}</option>) : <option value={0}>{missing}</option>}</select></label><div className="tag-list">{snapshot?.source ? <code>{snapshot.source}</code> : null}{snapshot && snapshot.captured !== true ? <span className="warning-text">{missing}</span> : null}{snapshot?.truncated ? <span className="warning-text">{zh ? "已截断" : "Truncated"}</span> : null}{snapshot?.redacted ? <span>{zh ? "已脱敏" : "Redacted"}</span> : null}{snapshot?.omission_reason ? <code>{snapshot.omission_reason}</code> : null}</div></div>
    {context ? <div className="ordered-messages">{messages.length ? messages.map((m, i) => <article className="subpanel" key={i}><h2>#{i + 1} · {m.role}{m.name ? ` · ${m.name}` : ""}</h2>{m.tool_call_id ? <code>{m.tool_call_id}</code> : null}<MessageText message={m} /></article>) : <p className="muted-text">{missing}</p>}<details className="data-disclosure"><summary>Tool Schemas</summary><pre className="json-view">{snapshot?.tools ? JSON.stringify(snapshot.tools, null, 2) : missing}</pre></details></div> : <div className="input-columns">
      <article className="subpanel"><h2>System Input</h2>{messages.some(m => m.role === "system") ? messages.filter(m => m.role === "system").map((m, i) => <MessageText key={i} message={m} />) : <p className="capture-missing">{missing}</p>}</article>
      <article className="subpanel"><h2>User Input</h2>{latestUser.length ? latestUser.map((m, i) => <MessageText key={i} message={m} />) : <><small className="muted-text">{zh ? "运行请求；未采集模型消息" : "Run request; model message not captured"}</small><pre className="json-view input-message">{typeof request.message === "string" ? request.message : JSON.stringify(request, null, 2)}</pre></>}</article>
      <article className="subpanel"><h2>Output</h2><pre className="json-view input-message">{JSON.stringify(data.trace.output, null, 2)}</pre></article>
    </div>}
  </section>;
}

export function ArtifactEvidence({ events }: { events: TraceEvent[] }) {
  const { language } = useApp();
  const rows = events.filter(e => e.kind.startsWith("artifact."));
  if (!rows.length) return null;
  return <section className="subpanel"><h2>{language === "zh" ? "产物检查与审核" : "Artifact checks & review"}</h2>{rows.map(event => <details key={event.event_id} className="data-disclosure"><summary><strong>#{event.sequence} {event.name || event.kind}</strong><code>{String(event.attributes.artifact_id || "")}</code><span>{event.status}</span></summary><dl className="kv-list horizontal">{["version", "content_hash", "manifest_hash", "rule_version", "review_id", "tool_call_id"].filter(k => event.attributes[k] != null).map(k => <div key={k}><dt>{k}</dt><dd><code>{String(event.attributes[k])}</code></dd></div>)}</dl><pre className="json-view">{JSON.stringify(event.attributes, null, 2)}</pre></details>)}</section>;
}
