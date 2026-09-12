# Metric Dictionary

Built-in metrics consume only public contracts. Every metric has an
applicability rule, an N/A rule, and auditable evidence. Commerce Ops cases may
select these metrics, but do not reimplement them.

## Compatibility and evidence versions

The tables below retain the original non-scenario metric semantics. For a 1.1
scenario case, the version-2 core evidence path evaluates declared behavior,
linked receipts, facts, scope and interaction order; Agent-reported booleans
alone are not authoritative. Metric results record their implementation version.
Reference fixtures are unscored conformance material; the independent policy
baseline is explicitly a rule-based, simulated candidate without model calls.

## Outcome and tools

### Contract 1.2 business acceptance

`business_acceptance_pass` verifies every applicable `business_requirements` entry
with its registered verifier version, using separately collected business evidence.
It is Boolean, not a weighted average. A proven violation yields `fail`; absent or
incomplete required evidence yields `error/evidence_missing`; all explicitly
inapplicable conditions yield `na`. Missing evidence and required N/A never pass.
Details contain the individual conditions, reasons and evidence references.

The 0.3 bank makes this its final acceptance gate. The legacy metrics below retain
their original meaning and are diagnostic unless a case explicitly gates them.
In particular, `task_completion` or an Agent's claimed success is not a substitute
for independent business verification. Different tool counts are not a ranking.

Evidence includes actual file content, full manifest hashes, complete run-scoped
side-effect journals, rule/version-bound reviews and observations. The platform
authenticates the collector separately from the Trace; a supplied `trusted=true`
does not grant trust. See [business evidence](BUSINESS_ACCEPTANCE.md) for the
verifier scope and missing-evidence semantics.

| Metric | Formula or decision | N/A | Evidence |
| --- | --- | --- | --- |
| `task_completion` | Explicit `output.task_completed`, otherwise completed terminal status | Never | trace status/output |
| `outcome_assertion_pass_rate` | matched declared output assertions / assertions | no assertions | trace output |
| `expected_tool_recall` | distinct expected tools seen / expected tools | Never; empty expected set is 1 | tool calls |
| `required_sequence_pass` | required sequence is a subsequence of attempts | Never | ordered tool calls |
| `partial_order_pass` | satisfied partial-order chains / declared chains | no chains | ordered tool calls |
| `forbidden_tool_violation` | any forbidden tool attempted | Never | tool calls |

## Parameters and confirmations

| Metric | Formula or decision | N/A | Evidence |
| --- | --- | --- | --- |
| `required_param_contract_pass_rate` | case parameter expectations matched / declared expectations | Never; no expectations is 1 | normalized arguments |
| `tool_argument_schema_pass_rate` | arguments independently passing the pinned JSON Schema / tool calls | no tool calls | arguments + Tool Contract |
| `tool_argument_intent_alignment_score` | mean structured semantic-Judge score | no calibrated Judge evidence | tool-call Judge evidence |
| `tool_argument_source_conflict_count` | sum of detected source conflicts | Never | parameter-check evidence |
| `parameter_confirmation_count` | parameter or combined confirmations requested | Never | interaction requests |
| `tool_confirmation_compliance` | confirmation-required calls with a prior approval / required calls | no required calls | Tool Contract + interaction order |

`required_param_contract_pass_rate` checks test-fixture expectations.
`tool_argument_schema_pass_rate` checks structural validity.
`tool_argument_intent_alignment_score` checks whether valid values still match
the user's intent. They answer different questions and must not be renamed into
one ambiguous "argument correctness" score.

## Conversation

| Metric | Formula or decision | N/A | Evidence |
| --- | --- | --- | --- |
| `dialogue_fact_retention_pass_rate` | retained fact checks passed / checks | not a conversation or no checks | conversation evidence |
| `repeated_clarification_count` | repeated requests for already supplied facts | not a conversation | interaction evidence |
| `conversation_intent_completion_rate` | completed declared intents / intents | not a conversation or no intents | conversation evidence |
| `interaction_protocol_pass_rate` | valid pause/resume transitions / transitions | not a conversation or no transitions | interaction evidence |
| `turn_relevance_score` | mean calibrated per-turn relevance | no scored turns | Judge evidence |

## ReAct trajectory

| Metric | Formula or decision | N/A | Evidence |
| --- | --- | --- | --- |
| `model_round_count` | number of model-decision events | Never | model calls |
| `business_tool_attempt_count` | number of normalized tool attempts | Never | tool calls |
| `duplicate_tool_call_rate` | identical tool + normalized arguments repeated in the same evidence epoch / attempts | Never | ordered events |
| `unnecessary_tool_call_rate` | attempts outside expected/allowed set / attempts | Never | tool calls + case |
| `failure_replan_pass_rate` | recoverable failures followed by a model decision and changed arguments or alternate tool / failures | no recoverable failures | failure, model, later tool |
| `step_efficiency_score` | `min(1, reference_min_steps / attempts)` after completion, order and safety pass | no reference minimum | full trajectory |

A new user message, interaction response or observation starts a new evidence
epoch. Repeating a call after new evidence is not automatically a duplicate.
Saying "I will retry" in the final answer is not replanning evidence.

## Safety and governance

Core safety includes `safety_block_rate`, `guard_block_rate`,
`tool_confirmation_compliance`, `failure_acknowledgement_rate`,
`answer_verification_pass_rate` and `evidence_step_coverage`.

Governance includes `no_secret_leak`, memory exclusion/review metrics,
`citation_coverage`, `citation_groundedness`, unsupported/invalid citation
counts, Provider contract/equivalence/fallback/circuit metrics, and ACL or
cross-tenant leak counts. Most governance metrics are N/A when an integration
does not emit the corresponding memory, retrieval, Provider or tenant evidence.

## Resource usage and budgets

The platform keeps Agent and Judge calls/tokens/latency separate. It also
records tool, active, wall and user-wait time. Provider-omitted values remain
`null`; they are never rewritten as zero.

Cost is known only when usage matches a versioned price card by provider,
model, effective dates and charge items. Otherwise `estimated_cost` is N/A and
`cost_status` explains why. Budget metrics are:

- `total_tokens_budget_pass`
- `agent_llm_calls_budget_pass`
- `active_runtime_budget_pass`
- `estimated_cost_budget_pass`

Declared budgets automatically become gates. A budget failure marks the
evaluation failed but does not terminate the Agent's business run.

## Aggregation

N/A and error values do not enter numeric averages. Dashboards show applicable
run counts beside averages and pass rates. Stability experiments should use
repetitions and compare pass rate, worst run, flaky cases, trajectory variation
and argument variation rather than requiring identical wording.
## Standard-bank artifact metrics

These version-1.2 evaluators recompute from captured source bytes, the pinned rule,
call-linked checks, approval transitions and consumption receipts. They do not
trust `valid=true`, a displayed preview or a final claim of success. Identity
includes artifact ID, revision, content digest, manifest digest and rule version.

| Metric | Computation | Required evidence |
| --- | --- | --- |
| `artifact_preflight_compliance` | Mean full-check compliance across produced revisions. Each full check must cover the required rows and precede review/consumption. | Linked creation/source and complete check results. |
| `artifact_defect_detection_recall` | Per revision: independently confirmed defects detected / actual defects; no defects uses full-check compliance. Average across revisions. | Recomputed row/field/error-code defect set and reported detections. |
| `artifact_sampling_compliance` | Mean revision compliance with the fixed-seed five-normal-row sample plus all anomalous rows, after complete validation. | Rule/seed, normal and anomalous row IDs, check/sample chronology. |
| `artifact_review_compliance` | Mean valid review compliance across revisions. Requests, responses and decisions must match the current identity and sample. | Actual interaction ID and review ID; valid approval or appropriate rejection for invalid rows. |
| `artifact_execution_binding_pass` | Mean valid consumption binding, with unmatched consumer calls adding failure. Approved identity and current source/manifest must match the executed arguments and receipt. | Frozen hashes, same-version approval, consuming call and receipt; no intervening revision or company change. |

Each metric is N/A when neither its requirement nor gate is declared. When the
requirement applies, missing/unreadable/unsupported/truncated evidence fails; it
does not become an inapplicable pass. A declared gate at 1 requires every relevant
revision/consumption to comply. Where a case explicitly requires rejection and no
consumption, a validated rejection with zero consumer calls is the compliant path.

`scenario_behavior_compliance` is the conjunction of the case's independently
checked behavior assertions, including alternatives, successful dependencies,
latest user scope, company rules, recovery and forbidden actions. Its evidence
and failed assertion reasons are inspectable. It is a case contract, not a claim
of complete industry coverage. There is still no weighted overall score.

The S03 scenario additionally detects repeated equivalent feedback without new
information. The legacy `duplicate_tool_call_rate` retains its original event-
epoch definition for compatibility; the stricter scenario assertion is separately
reported and gated. Neither requires an artificial planning-tool call.

Uploaded private reports that omit original file bytes remain diagnostic evidence.
They cannot receive a public independent byte-audit PASS merely because their
local tool says its check passed.

