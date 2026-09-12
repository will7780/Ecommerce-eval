# Platform Compatibility And Handoff

Use when choosing resource versions, preparing a bundle or interpreting offline
validation. The helper/example maintain the local handoff schema; platform
contracts and import services remain authoritative for importable resources.

## Compatibility Pins

| Component | v0.1.0 baseline |
| --- | --- |
| Platform | `0.3.0rc2` |
| Selected business wire contract | `1.2` |
| Business bank / canonical conformance profiles | `0.3.1` |
| Business verifiers and result-report contract | `1.1` |
| Skill / local bundle format | `0.1.0` |

Do not confuse legacy model defaults or accepted historical wire versions with
the selected business contract. Inspect actual availability; unknown, unavailable
or unverified revisions stay draft-only. Preserve historical datasets/results.
Inspect both runtime and distribution metadata: an editable install can have
stale package metadata, which the capability report flags. This is not proof
that a different wheel version is compatible; the pinned wheel remains
`0.3.0rc2`. Do not silently install, upgrade or relabel the environment.
Source anchors under `src/commerce_eval/` in the matching platform checkout are
`contracts/models.py`, `contracts/scenarios.py`, `business/bank.py`,
`business/verifiers.py`, `business/reporting.py`, `services/imports.py`,
`services/evaluations.py`, `experiments/runner.py`, `storage/business_evidence.py`.

## Helper Interface

Use an existing Python environment with the compatible platform available. From
the platform checkout, or using the installed Skill's equivalent script path:

```bash
python skills/ecommerce-eval-onboarding/scripts/validate_bundle.py --inspect
python skills/ecommerce-eval-onboarding/scripts/validate_bundle.py ./eval-onboarding
```

The Python entry points are `inspect_platform_capabilities()` and
`validate_bundle(bundle_dir)` in that script. The CLI accepts either `--inspect`
or `BUNDLE_DIR`; stdout is JSON with redacted diagnostic codes, not raw source,
credentials or exception payloads. Explain codes in the user's language without
reintroducing sensitive inputs. No implicit install or upgrade occurs; missing
dependencies produce a limitation to report, not permission to install packages.

`--inspect` includes current schemas and can return a large JSON catalog; summarize
relevant capabilities rather than pasting it into the conversation. There is no
`--output` flag. For bundle validation, exit `0` means valid import with no
invalid rule check, **not business readiness**; `1` indicates an invalid import
or rule check; `2` means import was not checked. Inspection returns `0` for a
verified catalog and `2` otherwise. Read the JSON's separate statuses in all cases.

Inspection discovers available built-ins only. Validation checks bounded text,
path confinement, hashes, resource/dependency references, versions and private-data
separation. It reuses platform models and real `ImportService.preview/commit` in
a **new temporary database**, disposes it and removes it afterward. This is not
an import in the user's real project. Do not supply a live database, enable
evaluation on import, or call frontend, registration or check/connect/run routes.

Canonical conformance uses real offline platform fixtures on both surfaces;
see [question design](question-design.md) for its semantic-match limit. Model
validation alone cannot verify `expected`. The normal
`commerce-eval validate --kind case` validates cases, not a full Dataset wrapper;
it is not a replacement for bundle validation.

## Bundle And Schema Authority

Use [the helper](../scripts/validate_bundle.py) and
[the shipped example](../assets/bundle-example/) for exact fields. Do not define
a second schema or rename enum values. These are local handoff files, not new
platform import kinds:

| File | Purpose |
| --- | --- |
| `assessment.md` | Whole-product map, sources, confirmed main workflow/rules and unresolved decisions. |
| `applicability.json` | Eight directions and conditions with applicability, support, evidence, use, case references and proof needs. |
| `evidence-gaps.md` | Blocked conclusions, collection/integration work, ownership and impact. |
| `cases-draft.md` | Proposed questions, custom/unverified rules and uncovered critical branches. |
| `manifest.json` | Versions, confirmed workflow, hashes, import order/dependencies and conformance profile bindings. |
| `validation-report.json` | Helper results and redacted reasons for checks performed or not performed. |
| `next-steps.md` | Later import order, remaining evidence/runtime work and separate approvals. |
| `importable/` | Relevant supported platform files; this directory name is not a readiness claim. |

Produce only relevant files. `manifest.json` uses `bundle_version: "0.1.0"`,
`project_id`, `main_workflow` with `id`, `confirmed`, `source_refs`, plus
`resources` and `rule_checks`. Resources record `path`, `kind`, `id`, `version`,
`sha256`, `order`, `depends_on`, and supported `options` when needed. Paths and
dependencies are bundle-relative; resources belong under `importable/`. Never
escape the bundle or import arbitrary local files. The optional `safety_review`
is only for the reviewed HTTP Target exception below.

For a genuine `trace` resource, the helper additionally requires
`provenance: "user_recorded"` and nonempty `source_refs` in the resource entry.
These record the supplied trace's origin, not independent evidence trust. Never
apply that label to generated reference fixtures.

For `applicability.json`, preserve the axes in
[product and evidence](product-and-evidence.md). Keep blocked applicable
conditions even without an importable case. Do not fabricate
`main_workflow.confirmed` or an evidence flag to pass validation. Record actual
confirmation sources; profile conformance does not confirm policy for the user.

## Importable Is Not Integrated

Read structure, references, import, rule conformance and evidence/business
readiness separately. Import states are `valid`, `invalid`, `not_checked`.
Business readiness states are `ready`, `evidence_required`,
`integration_required`, `unsupported`, `not_checked`, each with reasons.
Do not collapse them into a single green check.

- A valid import proves the resource passed this temporary import route. It does
  not run a tool, collect evidence, establish collector trust, prove isolation,
  validate a custom oracle or assess an Agent.
- Canonical conformance establishes reference-fixture discrimination only.
  It requires unchanged original case input/environment/requirements/gates;
  only helper-permitted metadata and diagnostic tool spelling may differ.
  Tailored rules/custom fields need separately reviewed fixtures/profile and
  otherwise remain `not_checked`, even if import is `valid`.
- Unsupported verifiers are `unsupported`; missing proof stays an evidence gap,
  never N/A. The helper retains the blocked denominator.
- **v0.1.0 registers no external collectors.** Applicable business conditions
  remain at best `integration_required`, not `ready`, even when the matrix says
  `evidence: sufficient` and import/conformance pass. Partial, missing or untrusted
  evidence still needs its own gap explanation.

The platform imports individual kinds, not a bundle ZIP: `dataset`,
`tool-contracts`, `evaluator-set`, optionally `products`, `rules`, genuine `trace`
and reviewed HTTP `target`. Follow manifest `order` and `depends_on`: establish
references before dependents and pin all bindings for any later trace evaluation.
Trace import is unscored. Describe the sequence in `next-steps.md`; do not perform
a real-project import or evaluation during this Skill.

CLI/API/web imports and their explicit offline evaluation path use **built-in
offline evaluators only**. Active Runner entry-point discovery does not enable
plugins in these routes. An evaluator-set selects available IDs, not executable
code or new verifiers. A Tool Contract describes but does not connect a tool.

## Reviewed HTTP Target Exception

Normally keep a proposed Target outside `importable/` and explain
`integration_required` / `target_review_required`. A manifest resource may carry
`safety_review: {confirmed: true, source_refs: [...], execution_mode: "sandbox"}`
(or `"dry_run"`) only when the user actually confirmed the safety review and the
references record it. The helper may then
structurally import an **HTTP** Target into its temporary database if the
definition has `safe_for_eval: true`, contains no command, and passes platform
checks. Record the reviewed dry-run/sandbox mode in `safety_review.execution_mode`,
not as an extra HTTP Target `config.execution_mode` field: the public HTTP importer
does not allow that config field. The recorded mode must describe the runtime the
user reviewed. Missing review rejects that Target import.

This records user-confirmed review, not independent proof of isolation,
integration or readiness. No network probe, connection check, execution or real
registration is performed. Python Targets remain integration handoffs with no
automatic local command registration. A child process or a `safe_for_eval` flag
alone is not a security sandbox.

## Trusted Evidence Is Separate Work

`save_collected_business_evidence()` is an internal collector persistence path,
not an upload endpoint. Importing `trusted=true` or a self-certified report cannot
authenticate an external collector. Do not invent a `business-evidence` upload
kind, invoke internal persistence as a workaround, or give candidates database
credentials/private cases. A mapping or handshake does not connect a tool backend
to the bank's controlled environment.

No external collector bridge is shipped here. Document minimal separately
reviewed instrumentation/harness work and its owner; do not implement it. Genuine
traces may support diagnostics, but incomplete effect evidence cannot prove no
publication. Synthetic fixtures remain separate verifier-test assets, never
genuine Agent traces or scores.

## Optional Synthetic Example

The checked-in `assets/bundle-example/` contains three importable resources
(tool contracts, evaluator set, Dataset), an assessment, coverage and reports.
It adopts unchanged bank `I01`, not a customer's tailored policy. Its saved import
and canonical conformance results are `valid` on both surfaces, but an unresolved
recovery branch remains in the denominator and business readiness is
`not_checked`. It is deliberately not a ready-to-run Agent integration.

To serialize the example into a user-selected new or empty directory, use the
existing compatible platform interpreter:

```bash
python skills/ecommerce-eval-onboarding/scripts/build_example.py ./synthetic-onboarding-example
```

`build_example.py DESTINATION` deterministically serializes the immutable bank
case and performs offline validation; it never runs an Agent or installs anything.
Do not point it at a customer's handoff or nonempty directory. The example's
synthetic confirmations are not confirmations for a real onboarding task.
