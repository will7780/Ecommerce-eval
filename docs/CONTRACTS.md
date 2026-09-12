# Public Contracts

Commerce Agent Eval accepts only versioned JSON contracts. An integration may
use any agent framework, model provider, programming language, or runtime as
long as it can produce these contracts.

## TraceEnvelopeV1

`TraceEnvelopeV1` is one observed run, which may be imported but not yet evaluated. It pins the project, target, dataset,
tool-contract set/version and evaluator versions and contains normalized events,
terminal output, tags, metadata and resource usage. Send both
`tool_contract_set_id` and `tool_contract_version` when the corresponding
contract set has been imported. This lets the persistence boundary reapply the
contract's `sensitive_fields`; adapter-side redaction remains mandatory.

`TraceEventV1.kind` is forward-compatible. Built-in evaluators understand these
common kinds:

| Kind | Meaning | Typical attributes |
| --- | --- | --- |
| `model.call` | One agent-model decision round | round, usage, latency |
| `tool.call` | A business-tool attempt | tool_id, arguments, guard status |
| `guard` | Permission or policy decision | allowed, reason_code |
| `parameter_check` | Schema or semantic parameter decision | aligned, score |
| `interaction.request` | Clarification or confirmation requested | type, confirmation_kind |
| `interaction.response` | User supplied data or approval | decision, supplied facts |
| `observation` | Tool or retrieval feedback | status, error_type, retryable |
| `retrieval` | Knowledge or memory retrieval | citations, authorization result |
| `final_answer` | User-facing terminal answer evidence | grounded, evidence_refs |
| `error` | Structured runtime failure | error_type |

Do not emit hidden chain-of-thought. Record decisions and evidence references,
not private reasoning. Unknown event kinds remain valid and are stored after
normalization so extensions can add their own evaluators.

## ToolContractV1

A tool contract is the evaluation boundary for a capability, not an executable
function. It declares:

- stable actual `tool_id` and immutable version; capability bindings provide the neutral evaluation view without renaming it;
- JSON Schema for input and output;
- risk level and side-effect class;
- whether explicit confirmation is required;
- success evidence, known failures and idempotency;
- sensitive fields and allowed parameter-source categories.

The platform independently validates tool arguments against `input_schema`.
An Agent-provided `schema_pass` field is diagnostic only and cannot override the
platform result.

## EvalCaseV1

An evaluation case declares expected behavior:

- a single input or an ordered conversation;
- expected, allowed and forbidden tools;
- a strict sequence and/or one or more partial-order chains;
- exact or subset parameter expectations;
- terminal output and retained-fact assertions;
- a reference minimum step count;
- token, call, active-time and known-cost budgets;
- explicit metric gates.

Only `user_message` and `interaction_response` are legal conversation events.
N/A never silently passes a gate unless that gate explicitly sets
`allow_na=true`.

## MetricResultV1

Every metric returns `pass`, `fail`, `na`, or `error`, plus a value, stable
reason code, evidence references and details. `na` always includes `na_reason`.
The platform has no weighted overall score. `overall_pass` is the conjunction
of the gates declared by the case, including automatically materialized budget
gates.

## ExperimentSpecV1

An experiment pins immutable Dataset, Target, Tool Contract, Evaluator Set and
optional model-configuration versions. `repetitions` measures run-to-run
stability and `concurrency` controls execution parallelism. Active execution is
accepted only for `safe_for_eval=true` dry-run or sandbox targets.

## AgentTarget

Targets implement four operations:

```python
class AgentTarget(Protocol):
    async def capabilities(self) -> Mapping[str, Any]: ...
    async def start(self, request: TargetRunRequestV1) -> TargetRunResponseV1: ...
    async def resume(self, request: TargetResumeRequestV1) -> TargetRunResponseV1: ...
    async def reset(self, session_id: str) -> None: ...
```

The bundled Python target uses one JSON request and one JSON response over a
child process. The HTTP target uses `POST /v1/runs`,
`POST /v1/runs/{external_run_id}/resume`, and
`POST /v1/sessions/{session_id}/reset`. A child process is lifecycle isolation,
not a security sandbox.

See the anonymous canonical payloads in [`../examples`](../examples).
## Contract 1.1 additions

Import accepts 1.0 and 1.1. Empty 1.1-only case fields are omitted when serializing
legacy 1.0 cases, preserving their original immutable checksums. New evaluations
are separate immutable records; they do not overwrite a Trace or older results.

- `model.input` carries `ModelInputSnapshotV1`: actual ordered messages and
  tool schemas, `snapshot_id`, `model_call_id`, round, source, captured/redacted/
  truncated flags and omission reason. Developer/assistant/tool messages keep
  their own roles. Do not reconstruct missing historical prompts.
- `ScenarioTemplateV1` separates public task/assets from environment, scripts,
  expected behavior and reference mutations.
- `CandidateInputV1` contains only the current task and explicitly permitted
  material. The Runner and both transports strip evaluation-only fields.
- `CapabilityBindingV1` maps neutral capabilities, argument fields, unit scales
  and output evidence to actual tool contracts. It does not replace tool backends.
- `ArtifactEvidenceV1` identifies artifact/version/content/manifest/rule, full
  check and sample evidence, review ID and consuming tool call. See
  [artifact source and review contracts](SCENARIOS.md) for complete source-byte
  requirements. Missing or unsupported source evidence cannot imply validation.
- Confirmation additionally binds its kind, tool call, frozen parameter hash and
  artifact revision. New user messages after completion start a new run in the
  same session; interaction responses resume an existing pending run.

Import/connection request examples, template downloads and the exact Target
protocol are in [Onboarding](ONBOARDING.md). Uploaded product data is an input
asset, not proof that an Agent used it correctly.

