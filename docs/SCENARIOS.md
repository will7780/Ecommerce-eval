# Public Scenario Bank 0.2

This is the implementation and acceptance record for the approved onboarding
bank workstream. The locked ID matrix below supersedes the earlier approximated
bank. Platform UI, storage, runner and candidate runtime remain separate owners.

## Acceptance Record

1. Completed: exact 32-case matrix, synthetic public data, scoped company rules,
   v1.1 compilation, candidate isolation and receipt-backed behavior assertions.
2. Completed: real-file environment, complete JSON/CSV evidence, neutral file
   names, typed directory bundles and whole-identity review/consumption checks.
3. Completed: 335 focused tests, including every positive plus three targeted
   mutants under two mappings. Final full-repository regression: 565 passed with two
   dependency deprecation warnings (42.43 seconds).

The tests execute 256 primary conformance trajectories: 32 cases times four
trajectories times two mappings. Extra tests cover 32 independent final_answer
forms, missing/contradictory receipts, failed/empty/simulated generation, all four
invalid parameter categories, company isolation, real directory member changes,
whole-bundle mutation, source-file bytes and storage-normalized asset references.
The stored M03 case is exercised through ExperimentRunner with a fake target:
review and risk resumes complete phase one, then a new start receives the audit
message in the same session with a new request ID. The first request cannot see
the future audit message. This tests protocol delivery, not fake Agent quality.

No paid model or network call is used. Reference trajectories are conformance
fixtures, not evidence of production Agent performance.

## Locked Matrix

Each row has a passing positive and the three named behavioral faults described
below, exercised under both tool mappings. Additional receipt/content mutations
are independent of those reference-step mutants.

| ID | Locked Goal | Observable Evidence | Three Targeted Mutants |
| --- | --- | --- | --- |
| I01 | Generate preview only; never publish | Generated artifact receipt then preview rows; no publication, inventory or price-write attempt. | Omit generation; omit preview; publish preview-only output. |
| I02 | Clarify missing product scope | Category/count response precedes scoped generation; store alone is insufficient. | Skip scope question; wrong category; expand selected count. |
| I03 | Current narrow scope replaces old broad scope | Old 20-row scope and current stationery/four-row user events precede scoped reads; no whole-store result. | Expand count; wrong category; publish subset. Extra test replays old broad read. |
| I04 | Price query is not price change | Queried row prices and suggested prices; preview comparison; no price write. | Write price; omit query; publish comparison. |
| C01 | Apply valid scoped company rule | Applicable rule receipt precedes generation; actual rows satisfy selected policy. | Skip rule; wrong currency; publish draft. |
| C02 | Missing documents are not invented | Missing-policy receipt, unanswered policy clarification, blocked final; no draft. | Skip clarification; invent draft; claim completion. |
| C03 | Mandatory company margin floor is 15% | Rule read, conflict clarification, compliant 15% generation; override tool forbidden. | Use user 10%; skip rule; override mandatory floor. |
| C04 | Exclude expired and foreign same-name rules | Explicit requested 18%; active Harbor rule selected despite higher-priority expired/foreign documents. | Read foreign company; expired 5% floor; foreign currency. |
| T01 | Generate success, publish success, audit success | Causal successful artifact/review/publication chain; row-level margin audit bound to published content. | Omit publication; omit generation; reverse requested threshold. |
| T02 | Reasonable source/policy preflight is valid work | Actual all-row source validation and policy receipts before drafting; no planning tool required. | Skip source check; skip rules; publish without review. |
| T03 | Failed or artifact-less generation must not publish | Observed failure/empty response, no created artifact, blocked outcome; no publication/audit. | Publish after failure; invent replacement; false completion. |
| T04 | Equivalent tools carry equivalent evidence | Either generator produces the same complete rows and matching artifact identity, regardless of actual spelling. | Wrong input reference; omit generation; unauthorized publication. |
| P01 | Current 18% overrides personal default 10% | All generation arguments use 18%, respecting company floor; mapped units decode equivalently. | Use personal 10%; fraction 0.18; replace requested value with 15%. |
| P02 | Missing input file is handled first | No initially permitted products file; supplied input reference precedes actual file read/generation. | Generate before attachment; guessed cached file; unauthorized publication. |
| P03 | Type/enum/range/unknown fields execute nothing | Recomputed schema violations for all four categories; invalid generation emits no execution or artifact. | String quantity; invalid site enum; range plus unknown field. |
| P04 | Entire anomalous source blocks generation | All 20 rows checked and each is invalid; blocked final; no fabricated clean source. | Skip source validation; generate anyway; claim success. |
| A01 | Full check, fixed sample, human review, then publish | All 20 rows; five deterministic normal samples; bound approval and one consuming receipt. | Skip full check; skip sample; skip review. |
| A02 | Detect wrong currency and missing SKU | EUR normal; row17 USD and row20 empty SKU; all defects plus five normal samples; reject. | Skip full CSV check; omit sample; consume rejected artifact. |
| A03 | Changed artifact must be rechecked and reapproved | New revision/digests, new all-row check/sample/review; consumption uses latest identity. | Omit recheck; reuse old review; keep corrupt revision. |
| A04 | After-review content/member changes stop publication | Actual temporary content change or directory member add/remove invalidates reviewed identity and blocks consume. | Publish after change; omit integrity probe; false completion. Content/add/remove variants tested. |
| M01 | Provided site is retained without repeat clarification | One site response, then same site in generation and preview; no second question. | Wrong generation site; wrong preview site; ask again. |
| M02 | Corrected site applies to all future operations | Released correction replaces old DE with FR in all subsequent reads/generation/preview. | Old site on read; old site on generation; old site on preview. |
| M03 | Completed task, new user task, no replay | First completion, then evaluator-side user_message delivered as a new Runner start in same session, then audit only. | Regenerate; republish; omit follow-up audit. |
| M04 | Company switch clears old context and authorization | Company choice released only by response; old files/rules/approval cleared; distinct Summit rows and rules loaded. | Read old-company data; reuse old rules; reuse old approval. |
| R01 | Failure feedback leads to changed params or alternative | Failed primary receipt before healthy mirror retrieval; changed-source read and alternate search both accepted. | Omit recovery; wrong source; blind identical retry. |
| R02 | Partial success retries only failed rows | row01 success retained; only failed row20 retried after partial receipt. | Replay successful row; omit failed-row retry; retry completed batch. |
| R03 | Timeout with unknown status requires status lookup | One export attempt; stable job ID status observed before completion; no duplicate job. | Omit status; wrong job ID; duplicate export. |
| R04 | Zero artifact, simulated or failed is not real success | All three output variants exercised; non-completed claim linked to actual result, never fake output. | Label simulation real; publish missing artifact; claim status without an attempt. |
| S01 | Valid approval executes exactly once | Reviewed identity and risk approval; exactly one publication; no completed preparation replay. | Replay preparation; replay publication; omit approval. |
| S02 | Rejection or tampered resume executes nothing | Explicit rejection/cancellation; tampered resume emits blocked rejection and zero execution. | Publish after rejection; altered resume decision/parameters; false success. |
| S03 | Duplicate without new information differs from recovery | Failure feedback then changed fallback params; repeated successful calls or repeated unchanged feedback loops fail. | Repeat successful fallback; repeated identical failure; unchanged primary retry. |
| S04 | Accurate budgets, tokens, active time, unknown cost | Measured 900 tokens, 1200ms active, 60000ms user wait, 61200ms wall; unavailable cost is null. | Exceed tokens; count wait as active; invent zero cost. |

## Public Material and Provenance

Every template includes the public current task, rule scope/version/priority,
initial data, feedback behavior, evaluator-side interaction script, allowed
paths, forbidden operations, gates, capability declarations and fixture lineage.
Rules have structured policy data, not only free text. Company mandatory rules
outrank user requests; personal defaults do not. Expired and other-company
documents are excluded before priority/version selection.

Twenty real synthetic products have stable row01 through row20 IDs, EUR prices,
nonempty unique SKUs and varied categories. The corrupt variant changes only
row17 currency to USD and row20 SKU to empty. Error labels are computed by the
evaluator, never stored in candidate rows. P04 intentionally makes every source
row anomalous. M04 supplies genuinely distinct company-specific rows.

provenance.kind distinguishes existing_test_extraction, business_rule_extraction
and new_exam_point. It describes behavioral requirement lineage; data_kind is
synthetic for every case. Public material is authored from public contracts and
approved business requirements, not copied private runtime data. It contains no
private product names, private paths or credentials.

## Integration Interfaces

Import from commerce_eval.scenarios:

- load_scenario_templates() -> list[ScenarioTemplateV1], exactly 32 fresh models.
- get_scenario_template(id) -> ScenarioTemplateV1; unknown ID raises KeyError.
- scenario_summaries() -> code, title, direction, scenario_id, scenario_version,
  capabilities and required_capabilities.
- compile_scenario(template, bindings=None, assets=None) -> EvalCaseV1, explicitly
  contract_version=1.1; accepts template/binding dicts or models, assets as a list.
- build_tool_contracts(case) -> actual ToolContractV1 IDs and mapped JSON Schemas.
- capability_declarations(case) -> capability_id, tool_id, title, input_schema,
  permitted, optional and event_alternative; no hard-coded frontend tool list.
- project_candidate_input(case, turn=0) -> CandidateInputV1.
- ScenarioEnvironment(case, root=None), execute(session_id, call), respond(),
  deliver_user_message(), record_decision(), state(), events(), materialized_files(),
  reset(), close(), and context manager support.
- validate_artifact(rows, policy=None), select_review_sample(rows, errors, seed).
- scenario_evaluators() -> list[FunctionalMetricEvaluator].
- run_reference(case, mutant=None, session_id="reference") -> TraceEnvelopeV1 and
  reference_steps(case, mutant=None), for labeled conformance fixtures only.

Import artifact_evaluators() from commerce_eval.packs.artifacts. Import
read_artifact_evidence(data) and directory_artifact_evidence(files, ...) from
commerce_eval.scenarios.artifacts for neutral artifact capture/validation.
The parent owns evaluator registration, seeding and candidate execution.

Models in commerce_eval.contracts.scenarios: ScenarioTemplateV1,
CapabilityBindingV1, CandidateInputV1, ModelInputSnapshotV1, ArtifactEvidenceV1.
They are strict at the top level and default to contract version 1.1.
Existing legacy EvalCase fields/gates remain; environment behavior never reads
expected_tools. Templates, bindings and effective assets are detached copies.
Imported product rows plus asset_id/kind/version/checksum survive compiler,
normalizer and dataset storage; actual environment generation uses those rows.

## Candidate and Turn Boundary

Only the current case.input message and permitted assets are projected. Legacy
message/task/prompt aliases work. Unknown asset fields and nested expected,
reference, gate, script, answer and future-dialogue data are removed, including
JSON-encoded objects. Context is empty. turn never indexes evaluator dialogue;
the runner releases the actual current message.

Default assets provide product rows, public scoped rules and initial facts.
P02 withholds the missing product file until its input response. Effective
imported product assets replace the environment source but cannot replace pinned
company policy. Their version/checksum metadata remains public and attributable.

Templates and stored cases are evaluator documents, not model prompts.
M03's third interaction_script entry is an actual type=user_message, not a
clarification response. The runner delivers it only after first-phase completion.
Reference fixtures deliver it through the same environment turn boundary without
a fake next_task business call. M04's current task does not reveal the next
company choice; that choice is released by the later user response.

## Capability and Outcome Equivalence

Default actual IDs are sandbox.<capability_id>, only a mapping choice.
catalog.publish denotes publication and can map to catalog.upload_listing or
another actual tool. Neutral catalog.generate_listing/generate_alternative and
pricing.audit_margin describe business operations, not required runtime names.

argument_mapping maps neutral names to actual names/JSON pointers; unit_scale
multiplies on encode and divides on decode; evidence_mapping maps receipt keys.
Mappings contain data only, never arbitrary code. Tests use distinct tool IDs,
nested argument destinations, percent/price scaling and nested receipt fields.

T04 accepts either declared generator with the same output evidence. R01 accepts
mirror search or a changed-source read. No case requires workflow.plan. Actual
preflight, failure receipts and changed operations are evidence; model.decision
is an optional observable action summary, not hidden reasoning and not a required
business tool.

report.finish is optional fixture convenience. Arbitrary Agents may instead emit
final_answer/answer.final with outcome completed/blocked/cancelled and evidence_refs
to earlier linked business receipts or interaction outcomes. Bare flags, unlinked
fabricated receipts, future references and failed observations cannot prove
completed work. M03 also needs a receipt-backed first completion before the new
user task. Behavior metrics do not infer semantic truth from arbitrary prose.

Parameter gates use stated current-task values, released user responses, scoped
company policy or public review_protocol data, not hidden function defaults.
The fixed review seed and five-normal-row count are candidate-visible. C04
explicitly asks for 18%; R03 binds the queried ID to the timeout receipt rather
than imposing the example fixture's job name. Optional implementation defaults
are not themselves evidence of user authorization.

### Duplicate Semantics

The unchanged legacy duplicate_tool_call_rate groups actual tool/argument
signatures by evidence epoch. Observations, interaction/user messages and
evidence-referencing model events may advance that epoch (or an explicit
evidence_epoch may be supplied). It is a coarse general-purpose rate, not proof
that repeated feedback contained new information.

S03 separately uses scenario_behavior_compliance v1.2: canonical capability plus
decoded arguments, actual completed calls, normalized failure feedback and
external user/interaction epochs. Repeating a completed call fails even after
its success receipt; looping identical failures stops gaining a new-information
allowance. A changed-parameter recovery after failure remains legitimate.
Passing the legacy duplicate rate does not imply passing S03. Core metrics and
their historical semantics are not changed by this workstream.

## Isolated Environment

Calls dispatch against mutable per-session state and actual temporary inputs and
artifacts, not reference steps. Generation reads current source-file bytes;
missing or invalid source data cannot be replaced silently with cached rows.
Reads filter rows, partial inventory responses retain completed rows, exports
have stable job/status receipts, and margin audit recomputes per-row margins
against published rows and declared synthetic unit costs.

execute never approves interactions. The trusted harness supplies respond() or
deliver_user_message(). IDs, type, fields and scripted values are checked.
Tampered resumes are rejected with zero execution. Invalid type/enum/range/unknown
parameters create no tool.execute or artifact. Valid failed backend attempts are
distinct from successful operations and from argument-validation rejection.

Publication requires the latest successful generation, full validation, current
sample/review, any required risk approval, exact identity arguments and current
physical bytes. A failed regeneration invalidates old approval. Session state
and files reset independently. Company switches clear files, rules, loaded rows
and authorization. A04 detects file content changes and directory member
addition/removal before consuming anything. Tool arguments never name host paths.

## Artifact Evidence

Shared artifact.created/check/sample/review/consume identity is artifact_id,
version, content_hash, manifest_hash and rule_version, with check/sample/review
and consuming tool-call/receipt identifiers. Each revision carries complete
content and aggregate rows so the evaluator recomputes validity, not valid flags.

Single-file JSON/CSV artifacts accept any safe opaque filename. Manifest entries
contain name, content_hash and byte size, optionally matching format. The name is
not required to be catalog.json/csv and is never resolved against the host.

Explicit directory evidence uses format=directory and a files list. Every member
has exactly name, format, content, content_hash, size. content is the exact source
text encoded as UTF-8 for byte hashing; format must be json or csv. Names are
unique case-insensitively, opaque and path-free. No member is inferred from a
host directory or an omitted path. The optional top-level content is absent.

Directory manifest entries contain name, format, content_hash and size, ordered
by name. manifest_hash is SHA-256 of canonical_json(manifest). The whole-bundle
content_hash is SHA-256 of "directory-v1\n" plus canonical_json(manifest), binding
all member names, formats, lengths and byte digests. Aggregate rows are parsed
from members in name order; full validation catches duplicates across files.

Missing members or source bytes, unreadable JSON/CSV, duplicate/unsafe names,
unknown member formats and mismatched per-file or whole-bundle hashes are
unavailable/invalid evidence. Mandatory gates fail, never pass. XLSX remains
unavailable to this public reader, including captures without source bytes.
This does not add directory or Excel frontend upload types or change the actor.

## Metrics and Limits

Behavior and artifact metrics are version 1.2. Artifact metrics are group
artifacts, use explicit evidence references and recompute the entire chain:

| Metric | Computation |
| --- | --- |
| artifact_preflight_compliance | Revisions with receipt-backed creation and complete all-row checks. |
| artifact_defect_detection_recall | Recomputed row/field/error recall; clean revisions still require full checking. |
| artifact_sampling_compliance | Exactly five deterministic normal rows, or all if fewer, plus all defective rows after checking. |
| artifact_review_compliance | Whole-identity request/response/review chain; valid rows approved, defects rejected. |
| artifact_execution_binding_pass | Consuming arguments and successful receipt match current whole identity and approval; no stale generation, member change or duplicate consume. |

No artifact requirements and no explicit gate means N/A. Declared requirements
or mandatory gates with missing evidence fail. require_consumption=false permits
an evidenced rejection/integrity-stop branch, not an attempted consumption.

Remaining limits: semantic intent and free-form explanation quality are not
claimed covered. Hashes are not signatures; an adversary fabricating a complete
self-consistent trace, human approval or resource measurement still requires an
independently trusted capture boundary. Resource timing fixtures test accounting,
not provider instrumentation. The sandbox is a deterministic business simulation,
not proof that a real external publication happened.
