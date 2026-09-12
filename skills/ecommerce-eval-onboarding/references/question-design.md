# Evidence-Backed Question Design

Use only after product investigation; wait for confirmation of one main workflow
and its answer-changing rules before producing that workflow's importable cases.
Before confirmation, keep proposals in `cases-draft.md`.

## From Workflow To Questions

Use the `0.3.1` bank's 32 cases as a pattern library, not a quota. For the confirmed
workflow, cover every applicable critical constraint and failure branch across
all eight directions. Include normal input, missing information, company-rule
conflict, refusal, defective/revised artifacts and partial/ambiguous failure when
applicable. Preserve untestable conditions in the matrix and gap report.

For each draft, specify:

- Task, company/object scope, success and prohibited effects; authoritative rule
  version, provenance and confirmed interpretation.
- Public inputs/assets, initial environment and actual available interfaces;
  units/defaults, permitted alternatives and explicit budgets, if any.
- Evaluator-only fault conditions, scripted current-user responses, expected
  business postconditions, verifier/version, evidence needs and gates.
- Positive, targeted negative and missing-evidence examples; critical
  authorization/version requirements also need distinct bypass examples.

Give adapted datasets their own IDs/versions. A standard case ID used for lineage
does not make an adapted dataset an unchanged standard benchmark. Do not alter
historical bank versions/results or rename tool IDs to fit a reference trajectory.
Different methods can satisfy identical postconditions with different call counts.

Treat parameter validation, artifact validation/review and side-effect
authorization as separate requirements. Full artifact checks inspect all rows and
the complete manifest; human samples supplement rather than replace them. Approval
must bind the current company, scope, rule and complete content/manifest identity.
A changed or added file invalidates the previous version's approval.

If an intentionally invalid input is needed, preserve its defect. The normal
product importer rejects invalid SKU/price/currency rows, so use a supported
scenario asset route or record an integration gap. Do not silently repair the
fixture just to make upload succeed. Likewise, do not borrow the bank's margin
formula, currency quantum or sampling rule as the customer's policy without
confirmation.

## Candidate Projection And Interaction

Inspect `project_candidate_input()` in `src/commerce_eval/scenarios/compiler.py`
and the public request projection in `src/commerce_eval/targets/base.py`. Reuse
these boundaries when describing future integration; do not send a full Dataset
or private compiled case to a candidate.

The current projection reads the current message and explicitly permitted assets;
its context is empty. It never selects a future conversation item from the `turn`
argument. Do not widen it by copying private scenario context or future dialogue.

| Candidate-visible | Evaluator-only |
| --- | --- |
| Current user task; genuinely available public facts and permitted company rules/assets. | Reference answers, expected assertions, hidden labels and gates. |
| Actual public tool IDs/input schemas, not evaluation tags. | Positive/negative reference scripts, private environment/fault scripts. |
| Current observations and the response released for the matching pending interaction. | Future user replies/answers, correction/refusal scripts and future turns. |
| Defective input bytes the candidate must inspect, without answer labels. | Defect locations/labels supplied only to the grader. |

Do not derive visible tool availability from expected/forbidden actions or add
hidden answers to names, metadata, examples or tool descriptions. Public task
data can contain defects and rule conflicts; separating the oracle must not hide
the evidence needed to discover them. Captured past turns are distinct from
future scripted responses.

For corrected-bank semantics, publish the supported `1.1` result-report contract
from `src/commerce_eval/business/reporting.py` and declare clarification aliases
explicitly. A schema for the response is public; the required answer is not.
Use real pending interaction IDs/types and required fields. Optional review
responses are bounded and position/type/field matched, never blanket approval.
Do not consume required corrections or refusals as an optional branch, invent
consent, or replay completed effects on resume. No Target is run by this Skill.

## Oracle Verification Is More Than Import Validation

`expected` can be structurally valid while unsupported or meaningless. Reuse
platform models and actual verifiers; never implement an alternate scorer or
call an uploaded expression. Review source plus pinned bank examples rather than
guessing the accepted expected fields.

The v0.1.0 helper supports conformance for **unchanged canonical scoring
configuration** from bank `0.3.1`, including the original case input, environment,
requirements and gates. Only helper-permitted metadata and diagnostic tool
spelling may change. **Tailored business rules may import legally but remain
`not_checked` until separately reviewed fixtures/profile exist.** In
`manifest.json`, each `rule_checks` entry
binds `dataset_id`, `dataset_version`, `case_id`, `profile_case_id` (such as `I01`)
and `profile_bank_version` (`0.3.1`). This selects a reference profile; it does not
self-certify compatibility. Use the helper's actual comparison, not an assumed
allowance to change a semantic field under the same profile ID.

The helper uses real platform positive, targeted negative and missing-evidence
fixtures on **both** `business_interface` and `file_editor` surfaces. Critical
authorization/version rules need bypass discrimination too. These checks establish
only the supported reference scoring behavior, not that the customer's rules are
correct, the task is representative, evidence has been collected, or an Agent
passed. Normal human confirmation of workflow/policy remains separate.

Custom fields, requirements, environment or gates require a separately reviewed
conformance profile. Until one exists, report rule conformance as `not_checked`,
even when the platform accepts the import. Unknown verifiers are `unsupported`,
not an invitation to substitute a convenient metric. Do not claim that successful
schema validation, selecting `profile_case_id`, or editing a test's expected
answer verifies a custom oracle. Keep the unverified design and evidence gaps in
drafts even if configuration files are importable; do not make readiness claims.

Keep reference fixtures separate from supplied genuine traces. Synthetic fixture
results are verifier tests, never Agent test scores; do not export them as
`importable/traces.jsonl`, strip their provenance, or relabel them candidate runs.
Only transformed genuine user traces may be included there, with redaction and
evidence limitations preserved.

## Handoff Review

Check that every applicable critical branch has a question or explicit gap, that
private/future answers are absent from candidate projection, and that public
materials still support solving the task. State which configurations passed
canonical conformance and which remain unverified. Use
[platform integration](platform-integration.md) for separate import/readiness
statuses; neither conformance nor a claimed evidence flag establishes external
integration.
