# Product And Evidence Investigation

Use during product discovery, workflow confirmation and evidence auditing. The
goal is a grounded business acceptance specification, not a catalog of tool calls.

## Establish The Product Before Narrowing

Read permitted engineering/design documents first, then relevant source and
interfaces. Inventory the whole product's users, workflows, business objects,
company/tenant boundaries, inputs, outputs, irreversible effects and safe test
environments. Distinguish documented intent from implemented behavior and actual
runtime evidence. Cite repository-relative paths/symbols or supplied document
sections; label observations, user confirmations, proposals and unknowns.

For real interfaces, record actual tool IDs, argument types/units/defaults and
sources, output shapes, side effects, permissions, idempotency, timeout/failure
behavior and dependencies. Include file edits or browser operations if observed;
do not invent a tool per capability or demand a particular number of steps.
Inspecting browser-related code is not permission to operate a live website.

No repository or genuine trace is required to begin: use the permitted interface
material, state its limits, and prepare useful drafts. Do not fabricate missing
implementation, traces, approval records or numerical confidence estimates.

## Confirmation Checkpoint

After discovery, present the workflow map, recommend one main workflow, and pause
for explicit user confirmation of that workflow and answer-changing rules. Ask
only consequential unresolved questions, for example:

- Does success mean generating a preview, saving a draft, or publishing? Which
  company, objects and side effects are permitted, including rollback/retraction?
- Which versioned company source is authoritative? Can an authorized person
  override it, and whose approval is required? How do current instructions and
  personal defaults interact when both comply with mandatory policy?
- What do margin, currency, precision, thresholds and scope mean in this product?
  Does a correction change the artifact, its authorization, or both?
- Which artifact/version must be reviewed, who may approve it, and what counts as
  recovery from a partial or ambiguous operation? Are budgets explicit gates?

Do not re-ask facts already confirmed. Do not silently promote a proposed company
rule to policy. If a rule conflict changes the expected answer, preserve the
conflict in drafts until resolved. If the user declines to narrow or confirm,
deliver the assessment/questions, not importable questions for an assumed flow.

## Inspect All Eight Directions

Apply the same business conditions to the same task whether execution uses APIs,
files or another observable method. Names, counts and trajectory metrics remain
diagnostic unless a specifically justified extra gate is explicitly requested.
The following verifier IDs are candidates to inspect, not interchangeable proofs.
Check their actual `1.1` semantics in `src/commerce_eval/business/verifiers.py`.

| ID | Acceptance question | Candidate checks and evidence needs |
| --- | --- | --- |
| I | Correct intent, objects and boundary? | `artifact_scope`, `state_query`, `no_effects`; actual outputs/state and complete run-scoped effects, not absence of a tool name. |
| C | Correct permitted company rule and version? | `policy_selection`, `artifact_rules`, `company_isolation`; authoritative rule/version, company scope and actual compliant content. |
| T | Business prerequisites actually completed? | `business_dependencies`, `operation_outcome`; successful predecessor outcomes, not one mandatory tool trajectory. |
| P | Correct usable inputs and current facts? | `parameter_preconditions`, `latest_facts`; provenance, units, current corrections and resulting prices/content. Schema validity is a separate check. |
| A | Actual output checked, reviewed and consumed unchanged? | `preflight`, `artifact_review`; full bytes/manifests, review identity and consumption receipts, with independent authorization. |
| M | Facts, corrections, refusals and company boundaries retained? | `clarification`, `latest_facts`, `company_isolation`; genuine role-separated turns and matched pending interactions. |
| R | Related failure resolved and reported honestly? | `failure_recovery`, `operation_outcome`, `result_report`; linked failures/jobs, status checks, deduplicated effects and the supported report contract. |
| S | Authorization and explicit resource limits respected? | `authorization`, `no_effects`, `business_efficiency`, `resource_accounting`; scoped approvals, complete effects, known usage and unknown-value accounting. |

Also inspect memory exclusion/review, RAG/citation, provider reliability, ACL/tenant
isolation and semantic-Judge needs where the product has those features. Record
each relevant condition under the appropriate existing direction with a reason;
do not invent a ninth direction or enable every metric. A truly absent feature
can be not applicable; an implemented feature with missing evidence cannot.
Keyword citation matching is not semantic faithfulness, parameter equality is
not intent understanding, and an uncalibrated semantic Judge is observational,
not a release gate. This Skill does not call a Judge.

## Keep The Axes Separate

Use the exact `applicability.json` schema in the helper/example:

- `directions` covers `I`, `C`, `T`, `P`, `A`, `M`, `R`, `S`, each with a reason.
- Conditions record `applicability` as `applies`, `not_applicable` or
  `needs_confirmation`, with `reason` and `source_refs`.
- `support` is `existing`, `configuration_needed` or `extension_needed`;
  `evidence` is `sufficient`, `partial`, `missing` or `untrusted`.
  Use `existing` when the verifier's documented semantics already match the
  condition. Use `configuration_needed` only when its supported fields can express
  the requirement without changing the algorithm. A hardcoded sampling rule,
  approval model or workflow dependency that changes the user's business rule
  needs `extension_needed`, not a convenient default or extra user obligation.
  Missing collector wiring belongs to the evidence/integration gap; it does not
  by itself mean the scoring algorithm needs an extension. Explain the specific
  mismatch and proposed owner. These are reviewed design judgments, not scores.
- `use` is `business_gate`, `explicit_gate` or `diagnostic`; `case_refs` bind
  dataset ID/version, case ID and a `requirement_ids` list matching the actual
  applicable case requirements. An `applies` + `business_gate` condition also
  needs `verifier_id` and `verifier_version` matching those requirements.
  Every applicable business requirement in an importable case must appear in
  these links. Omitting a condition cannot improve the declared coverage.
- `needs_confirmation` conditions must have empty `case_refs` and remain in
  drafts. Blocked applicable conditions stay visible even without importable
  cases; do not invent references to make the matrix look complete.

Every applicable critical constraint/failure branch needs a question or explicit
gap. Retain blocked applicable conditions in the coverage denominator and report
unresolved applicability separately. A small, separately approved partial
assessment must identify its omissions; it must not masquerade as full coverage.

At result time, proof of violation means fail; missing required proof means
error/unverifiable; true inapplicability alone means N/A. A legacy diagnostic may
return N/A without its evidence; do not translate that into business inapplicability
or a passing gate. A claimed `sufficient` flag does not establish collector trust
or upgrade helper readiness. See [platform integration](platform-integration.md).

## Evidence Map And Gaps

For each condition, fill `evidence_requirements` using the maintained schema:
`object_scope`, `company_scope`, `source`, `collector`, `locator`,
`version_or_hash`, `time_range`, `completeness`, `missing_impact`. Include run scope
in the scope/locator information. In `evidence-gaps.md`, add transformation and
redaction limits, minimum future collection work, its responsible owner, and
exactly which conclusion cannot be established. Do not invent extra JSON fields
to accommodate prose.

| Claim | Necessary basis | Insufficient substitute |
| --- | --- | --- |
| Requested catalog generated | Readable output rows compared with authorized source, scope and rules. | Successful tool response or candidate assertion without content. |
| No publication occurred | Complete trusted run/company/object effect journal, including publication followed by retraction. | No `publish` call in an incomplete trace. |
| Reviewed version was published | Full manifest/content identity, company/scope/rule-bound approval and actual consumer receipt in order. | File name, sample preview, or final success statement. |
| Corrected margin used | Current fact with units/provenance and independently checked output values. | Stored preference, selected parameter, or self-reported compliance alone. |
| Ambiguous failure recovered | Related stable failure/job IDs, actual status query and deduplicated receipts. | Unrelated retry or promise to retry. |

Preserve genuine System/User/Developer/Assistant/Tool roles, tool-call links,
ordering and truncation flags. Never reconstruct historical system input from
today's instructions or request hidden reasoning. Reference fixtures must remain
labelled synthetic and separate from genuine traces. Redaction may remove proof;
record that gap, since hashes cannot validate missing product content. Prefer
authorized minimized or synthetic assets; do not open credential stores or copy
private customer documents to demonstrate coverage.
