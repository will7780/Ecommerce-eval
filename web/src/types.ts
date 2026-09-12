export type Language = "en" | "zh";
export type Theme = "dark" | "light";

export interface Project {
  project_id: string;
  name: string;
  description: string;
  created_at: string;
}

export interface TraceListItem {
  trace_id: string;
  project_id: string;
  experiment_id: string | null;
  case_id: string | null;
  target_id: string;
  target_version: string;
  status: string;
  overall_pass: boolean | null;
  started_at: string;
  active_runtime_ms: number | null;
  estimated_cost: number | null;
  tags: Record<string, string>;
}

export interface TraceEvent {
  contract_version: string;
  event_id: string;
  parent_event_id: string | null;
  sequence: number;
  kind: string;
  name: string | null;
  status: string;
  started_at: string | null;
  ended_at: string | null;
  attributes: Record<string, unknown>;
  evidence_refs: string[];
}

export interface MetricResult {
  metric_id: string;
  metric_version: string;
  group: string;
  status: "pass" | "fail" | "na" | "error";
  value: unknown;
  reason_code: string;
  evidence_refs: string[];
  na_reason: string | null;
  details: Record<string, unknown>;
}

export interface GateResult {
  metric_id: string;
  passed: boolean;
  operator: string;
  expected: unknown;
  actual: unknown;
  reason_code: string;
}

export interface TraceDetail {
  business_evidence?: {
    collector_id: string;
    run_id: string;
    project_id: string;
    company_id: string;
    started_at: string;
    ended_at: string | null;
    complete: boolean;
    omission_reasons: string[];
    [key: string]: unknown;
  } | null;
  trace: {
    trace_id: string;
    project_id: string;
    target_id: string;
    target_version: string;
    experiment_id: string | null;
    case_id: string | null;
    status: string;
    started_at: string;
    ended_at: string | null;
    input: Record<string, unknown>;
    output: Record<string, unknown>;
    resource_usage: Record<string, unknown>;
    tags: Record<string, string>;
    metadata: Record<string, unknown>;
    events: TraceEvent[];
    [key: string]: unknown;
  };
  metrics: MetricResult[];
  gates: GateResult[];
  overall_pass: boolean | null;
  evaluation_id?: string;
  evaluation_history?: Array<{ evaluation_id: string; evaluated_at?: string; overall_pass: boolean; case_id: string; binding?: Record<string, unknown>; metric_results: MetricResult[]; gate_results: GateResult[] }>;
  annotations: Array<{ annotation_id: string; label: string; value: Record<string, unknown>; created_at: string }>;
}

export interface Experiment {
  experiment_id: string;
  project_id: string;
  name: string;
  status: string;
  spec: Record<string, unknown>;
  completed_runs: number;
  total_runs: number;
  passed_runs: number;
  failed_runs: number;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
  error_type: string | null;
}

export interface Dataset {
  project_id: string;
  dataset_id: string;
  version: string;
  name: string;
  description: string;
  case_count: number;
  created_at: string;
  cases?: Array<Record<string, unknown>>;
}

export interface Evaluator {
  metric_id: string;
  metric_version: string;
  group: string;
  required_evidence: string[];
}

export interface ToolContractSet {
  project_id: string;
  set_id: string;
  version: string;
  tool_count: number;
  tools: Array<Record<string, unknown>>;
  created_at: string;
}

export interface TargetDefinition {
  project_id: string;
  target_id: string;
  version: string;
  name: string;
  adapter_type: string;
  safe_for_eval: boolean;
  config: Record<string, unknown>;
  tags: Record<string, string>;
  created_at: string;
}

export interface DashboardData {
  project_id: string | null;
  trace_count: number;
  overall_pass_rate: number | null;
  gate_failure_count: number;
  p95_active_runtime_ms: number | null;
  average_known_cost: number | null;
  trend: Array<{ date: string; runs: number; pass_rate: number | null }>;
  metric_health: Array<{ metric_id: string; group: string; applicable: number; passed: number; failed: number; pass_rate: number | null; average: number | null }>;
  failure_reasons: Array<{ metric_id: string; count: number }>;
  recent_traces: TraceListItem[];
  recent_experiments: Experiment[];
}
