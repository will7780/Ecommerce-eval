import { CircleCheck, CircleDashed, CircleX, Clock3, ShieldAlert } from "lucide-react";

export function StatusBadge({ value }: { value: string | boolean | null | undefined }) {
  const normalized = value === true ? "pass" : value === false ? "fail" : String(value ?? "na").toLowerCase();
  const good = new Set(["pass", "passed", "completed", "ok", "true"]);
  const bad = new Set(["fail", "failed", "error", "false"]);
  const waiting = new Set(["running", "queued", "awaiting_input", "awaiting_confirmation", "pending"]);
  const Icon = good.has(normalized) ? CircleCheck : bad.has(normalized) ? CircleX : waiting.has(normalized) ? Clock3 : normalized === "blocked" ? ShieldAlert : CircleDashed;
  const tone = good.has(normalized) ? "success" : bad.has(normalized) ? "danger" : waiting.has(normalized) ? "warning" : normalized === "blocked" ? "danger" : "neutral";
  return (
    <span className={`status-badge ${tone}`}>
      <Icon size={13} aria-hidden="true" />
      {normalized.replaceAll("_", " ")}
    </span>
  );
}
