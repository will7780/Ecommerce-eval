import { Plus, X } from "lucide-react";
import { useState } from "react";

export interface CapabilityBinding {
  capability_id: string;
  tool_id: string;
  argument_mapping: Record<string, string>;
  unit_scale?: Record<string, number>;
  evidence_mapping?: Record<string, string>;
}
interface Field { source: string; destination: string; scale: string }
interface Draft { capability: string; tool: string; arguments: Field[]; evidence: Field[] }

function compile(drafts: Draft[]): { bindings: CapabilityBinding[]; valid: boolean } {
  const bindings: CapabilityBinding[] = [];
  let valid = true;
  for (const d of drafts) {
    if (!d.tool.trim()) { bindings.push({ capability_id: d.capability, tool_id: "", argument_mapping: {} }); continue; }
    const binding: CapabilityBinding = { capability_id: d.capability, tool_id: d.tool.trim(), argument_mapping: {}, evidence_mapping: {}, unit_scale: {} };
    for (const kind of ["arguments", "evidence"] as const) {
      const destinations = new Set<string>();
      const mapping = kind === "arguments" ? binding.argument_mapping : binding.evidence_mapping!;
      for (const f of d[kind]) {
        const source = f.source.trim(), destination = f.destination.trim();
        const scale = f.scale.trim() ? Number(f.scale) : null;
        if (!source || !destination || source in mapping || destinations.has(destination) || (scale !== null && (!Number.isFinite(scale) || scale <= 0))) valid = false;
        mapping[source] = destination;
        destinations.add(destination);
        if (kind === "arguments" && scale !== null) binding.unit_scale![source] = scale;
      }
    }
    bindings.push(binding);
  }
  return { bindings, valid };
}

export function CapabilityMappings({ bindings, onChange, onValidity, zh }: { bindings: CapabilityBinding[]; onChange: (next: CapabilityBinding[]) => void; onValidity: (valid: boolean) => void; zh: boolean }) {
  const [drafts, setDrafts] = useState<Draft[]>(() => bindings.map(b => ({ capability: b.capability_id, tool: b.tool_id, arguments: Object.entries(b.argument_mapping).map(([source, destination]) => ({ source, destination, scale: String(b.unit_scale?.[source] ?? "") })), evidence: Object.entries(b.evidence_mapping || {}).map(([source, destination]) => ({ source, destination, scale: "" })) })));
  const [valid, setValid] = useState(true);
  const text = (en: string, cn: string) => zh ? cn : en;
  const update = (next: Draft[]) => {
    setDrafts(next);
    const result = compile(next);
    setValid(result.valid); onValidity(result.valid);
    if (result.valid) onChange(result.bindings);
  };
  const fieldChange = (index: number, kind: "arguments" | "evidence", fieldIndex: number, key: keyof Field, value: string) => update(drafts.map((d, i) => i === index ? { ...d, [kind]: d[kind].map((f, j) => j === fieldIndex ? { ...f, [key]: value } : f) } : d));
  return <div className="capability-mappings">
    {drafts.map((d, index) => <details className="data-disclosure" key={d.capability}>
      <summary><code>{d.capability}</code><span>{d.tool || text("Not mapped", "未映射")}</span></summary>
      <div className="mapping-fields"><label><span>{text("Your tool ID", "你的工具 ID")}</span><input aria-label={`Tool ${index + 1}`} value={d.tool} onChange={e => update(drafts.map((item, i) => i === index ? { ...item, tool: e.target.value } : item))} /></label>
        {(["arguments", "evidence"] as const).map(kind => <section key={kind}>
          <h4>{kind === "arguments" ? text("Arguments & units", "参数与单位") : text("Output evidence", "输出证据")}</h4>
          {d[kind].map((f, fieldIndex) => <div className="mapping-field-row" key={fieldIndex}>
            <label><span>{text("Neutral field", "中立字段")}</span><input value={f.source} onChange={e => fieldChange(index, kind, fieldIndex, "source", e.target.value)} /></label>
            <label><span>{text("Tool field / pointer", "工具字段或指针")}</span><input value={f.destination} onChange={e => fieldChange(index, kind, fieldIndex, "destination", e.target.value)} /></label>
            {kind === "arguments" ? <label><span>{text("Unit multiplier", "单位倍率")}</span><input type="number" min="0" step="any" placeholder="1" value={f.scale} onChange={e => fieldChange(index, kind, fieldIndex, "scale", e.target.value)} /></label> : null}
            <button className="icon-button" title={text("Remove field", "移除字段")} onClick={() => update(drafts.map((item, i) => i === index ? { ...item, [kind]: item[kind].filter((_, j) => j !== fieldIndex) } : item))}><X size={14} /></button>
          </div>)}
          <button className="button secondary" onClick={() => update(drafts.map((item, i) => i === index ? { ...item, [kind]: [...item[kind], { source: "", destination: "", scale: "" }] } : item))}><Plus size={14} />{kind === "arguments" ? text("Add argument", "添加参数") : text("Add evidence field", "添加证据字段")}</button>
        </section>)}
      </div>
    </details>)}
    {!valid ? <p role="alert" className="error-text">{text("Complete unique field names and use positive unit multipliers.", "请补全字段，避免重复映射，单位倍率必须大于零。")}</p> : null}
  </div>;
}
