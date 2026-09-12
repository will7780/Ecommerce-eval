# Integrating an Agent

The platform never imports your Agent runtime. Integration is an outward
conversion from your state/report/telemetry into Contract v1.

## Choose an integration mode

1. **Trace import** is safest for existing or production systems. Export
   redacted `TraceEnvelopeV1` JSONL and import it without allowing the platform
   to invoke the Agent.
2. **PythonAgentTarget** is convenient for local dry-run fixtures. It starts a
   fresh child process for every start/resume/reset operation.
3. **HTTPAgentTarget** is appropriate when the Agent already exposes an API.
   The target service owns authentication and translates its native state into
   the public response contract.
4. **Plugin Target** is installed separately through the
   `commerce_eval.targets` Python entry point.

## Integration checklist

- Map implementation-specific tool names to stable capability IDs.
- Export input and output JSON Schema, risk, side effects and confirmation
  requirements as `ToolContractV1`.
- Emit ordered model, guard, parameter, tool, observation, interaction,
  retrieval and final-answer evidence without chain-of-thought.
- Distinguish simulated execution from live execution in tags/metadata.
- Split Agent and Judge usage. Leave unavailable usage as `null`.
- Redact before sending. The server redacts again before persistence.
- Use immutable versions for every Dataset, Target, Contract and Evaluator Set.
- Mark a Target `safe_for_eval=true` only when its execution mode cannot perform
  production writes.

## Execution and policy boundaries

HTTP and Python start requests contain a fresh, sanitized case with only the
current public input, permitted assets and minimal case identity. Expectations,
gates, scenario scripts and future messages remain evaluator-side. Both protocol
1.0 and 1.1 are supported. A scripted reply requires an actual matching pending
interaction; completion never creates an implicit approval or clarification.

A later user message can start a new task in the same session after completion.
The Target owns any retained receipt/state; the Runner does not inject previous
answers into the new input. The stored M03 regression verifies this contract,
including fresh request IDs, no first-turn future-message leak and no replay.
Invalid replies without a pending interaction still fail the protocol.

The built-in `reference_policy` adapter is a bounded deterministic baseline,
not a production Agent. It receives public inputs, capability schemas and actual
observations; its environment is privately bound by the Runner. Traces identify
`actor=reference_policy`, `simulation=true`, `production_agent=false` and zero
LLM calls. Decision events are labeled deterministic policy decisions, not model
invocations. Ordinary evaluations measure its actual behavior; unsupported or
incorrect workflows can fail. The separate `reference_fixture` adapter is
script-driven conformance data and never receives candidate Evaluation history.

The policy keeps its environment across pending-interaction resumes, but a new
start currently rebuilds that environment. It does not implement completed-task
receipt reuse, company switches or artifact-revision workflows. The generic M03
Runner regression therefore does not establish policy success on M03. The
environment's later-message delivery also currently requires the completion state
set by `report.finish`; an equivalent environment completion entry point for a
receipt-backed `final_answer` is not yet wired into this policy.

Generic HTTP/Python Targets still need their own trusted tool backend. The
shipped protocol has no generic tool-execution callback/session API; mappings do
not connect remote tools to `ScenarioEnvironment`. See
[Onboarding](ONBOARDING.md) for the existing trusted Python harness building
blocks and their limits. Directory artifact readers extend evidence evaluation,
not this actor or the Target transport.

Final execution checkpoint: 95 focused offline tests passed across
`test_candidate_execution.py`, `test_behavior_evidence.py` and
`test_reference_policy.py`. Coverage includes fake HTTP/Python transports,
projector fallback, strict pending IDs/fields, operation-specific confirmations,
causal event merging, answer poisoning, unscored fixtures across two projects
with 32 cases and repetitions 1/2, and the parent-seeded policy target. This is
not a claim that the policy passes all scenarios or that an external Agent's
backend has been integrated.

## Python entry points

An evaluator distribution may register:

```toml
[project.entry-points."commerce_eval.metric_packs"]
my_pack = "my_package.metrics:build_evaluators"
```

`build_evaluators()` returns objects implementing `MetricEvaluator`.

A Target distribution may register:

```toml
[project.entry-points."commerce_eval.targets"]
my_runtime = "my_package.target:build_target"
```

The factory receives `TargetDefinitionV1` and optional keyword arguments. It
returns an object implementing `AgentTarget`.

## CLI import

```bash
commerce-eval import traces.jsonl --kind trace
commerce-eval import cases.jsonl --kind dataset --project acme --id checkout --version 1.0.0
commerce-eval import tool-contracts.json --kind tool-contracts --project acme
commerce-eval import target.json --kind target --project acme
commerce-eval import evaluators.json --kind evaluator-set --project acme --id release --version 1.0.0
```

Use the files in [`../examples`](../examples) as canonical, anonymous examples.
