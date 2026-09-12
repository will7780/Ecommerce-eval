# Evaluation Onboarding Skill

`ecommerce-eval-onboarding` v0.1.0 is distributed in this repository at
[`skills/ecommerce-eval-onboarding/`](../skills/ecommerce-eval-onboarding/SKILL.md).
It investigates an existing product and prepares evidence-backed evaluation
questions, contracts and an integration checklist. It does not modify or run your
Agent. Codex is the first validation target; compatibility with every assistant
host is not claimed.

## Start With The Product

Supply a repository or interface documentation, permitted company rules and a
description of success. A redacted genuine trace and sample outputs help but are
not required to begin. Never supply credentials, hidden reasoning or unauthorized
customer material. The Skill asks questions and writes narrative deliverables in
your language while preserving machine-readable IDs, fields, enums and versions.

After installation, an example request is:

```text
Use $ecommerce-eval-onboarding to inspect this product and its permitted rules.
First map the whole product, then pause for my confirmation of one main workflow
and rules that change the correct answer. Prepare an evaluation handoff under
./eval-onboarding in my language. Do not change or run the Agent, import into a
real project, register anything, read credentials, or make paid calls.
```

The investigation covers all eight directions: intent/boundaries, company
information, dependencies, parameters, artifacts/review, continuity, recovery,
and safety/efficiency/cost. Relevant memory, RAG/citation, provider, ACL/tenant and
semantic-Judge considerations are optional additions, not mandatory metric packs.
The same business standard applies to API and file execution. Tool names/counts
remain diagnostics unless an extra gate is explicitly justified and requested.

The Skill reads the whole product before narrowing. It then waits for confirmation
of **one main workflow and answer-changing rules** before creating its importable
questions. Missing documentation, unresolved policy, unsupported checks and absent
evidence remain visible in drafts. Every applicable critical constraint/failure
branch needs a question or explicit gap; blocked cases stay in the denominator,
and missing evidence never becomes N/A.

## One-command Installation

With Node.js 22.20 or later available, run this from your product workspace:

```bash
npx skills add will7780/Ecommerce-eval --skill ecommerce-eval-onboarding --agent codex --copy
```

This third-party [Skills CLI](https://github.com/vercel-labs/skills) downloads the
public GitHub Skill and installs its complete directory for the selected host.
The default scope is the current project; add `--global` only when you intend a
user-wide installation. `--copy` avoids requiring symlink privileges on Windows.
Review the confirmation and existing installations before replacing anything.

To inspect the available Skill without installation:

```bash
npx skills add will7780/Ecommerce-eval --list
```

After installation, use `$ecommerce-eval-onboarding` in your next Codex task/turn.
The CLI supports other hosts, but installation support does not establish that
this Skill's behavior has been validated in each host. The baseline remains
Codex. Installing this Skill does not install the Python platform, configure a
collector, invoke a model, or execute an exam. Offline platform validation still
requires an existing compatible Python installation; missing platform support
leaves the handoff draft-only, not passed. No separate npm package for this Skill
is required: the GitHub `skills/.../SKILL.md` directory is the distribution source.

## Distribution And Manual Installation

A checkout contains the Skill source; it does not automatically install it
globally. To use it without installing, ask Codex to read and follow
`skills/ecommerce-eval-onboarding/SKILL.md` in this checkout for the current task.
Do not assume that merely cloning the repository registers a Skill.

For a deliberate local Codex installation, review and copy the **entire** Skill
folder, including references, scripts and assets, into
`$CODEX_HOME/skills/ecommerce-eval-onboarding`. If `CODEX_HOME` is unset, the default
is `~/.codex/skills/ecommerce-eval-onboarding`. For example, run the following
yourself in PowerShell from the repository root only when installation is wanted:

```powershell
$source = (Resolve-Path -LiteralPath './skills/ecommerce-eval-onboarding').Path
$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME '.codex' }
$destination = Join-Path $codexHome 'skills/ecommerce-eval-onboarding'
if (Test-Path -LiteralPath $destination) { throw 'Skill already exists; review the installed copy before updating.' }
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
Copy-Item -LiteralPath $source -Destination $destination -Recurse
```

The installed Skill is available on the next turn. This manual copy is a snapshot;
repository edits do not update it automatically. Review an existing installation
before replacing it. The bundled `skill-installer` can alternatively install this
subdirectory from a user-selected GitHub repository/ref when available; that is a
separately requested network installation, not part of onboarding. Neither route
installs the Python platform or a collector bridge, and no particular external
reference project is a runtime dependency.

## Offline Validation

The v0.1.0 baseline is platform `0.3.0rc2`, selected business contract `1.2`, bank
`0.3.1`, and business verifiers/result-report `1.1`. Historical versions remain
immutable; unknown or unverified versions stay draft-only. Use an existing Python
environment where the compatible platform is already available:

```bash
python skills/ecommerce-eval-onboarding/scripts/validate_bundle.py --inspect
python skills/ecommerce-eval-onboarding/scripts/validate_bundle.py ./eval-onboarding
```

The helper exposes `inspect_platform_capabilities()` and
`validate_bundle(bundle_dir)`. Its CLI accepts `--inspect` or a bundle directory
and emits JSON with redacted diagnostic codes. It never installs dependencies
implicitly. It validates through actual platform models/import services in a new
temporary database that is disposed and removed, not your real project database.
There are no frontend, connection-check, Target, Agent, Judge or paid model calls.

`--inspect` returns a potentially large catalog including current schemas. There
is no `--output` flag. For bundle validation, exit `0` means valid import with no
invalid rule check, not business readiness; `1` indicates an invalid import/rule
check and `2` means import was not checked. Always read the separate JSON results.

See the [integration reference](../skills/ecommerce-eval-onboarding/references/platform-integration.md)
and [example bundle](../skills/ecommerce-eval-onboarding/assets/bundle-example/)
for the authoritative helper/schema entry points. The manifest and applicability
matrix are local handoff artifacts, not platform contracts or a bundle-upload API.
The Skill produces relevant assessment, gap, draft, manifest, validation and
next-step files, plus individual supported resources under `importable/`.

The checked-in synthetic example has three importable resources and valid
canonical conformance on both surfaces, but retains an unresolved recovery branch:
its business readiness is `not_checked`. To reproduce it in a new or empty
directory, the optional offline command is:

```bash
python skills/ecommerce-eval-onboarding/scripts/build_example.py ./synthetic-onboarding-example
```

This serializes immutable bank `I01` and validates it without running an Agent.
It does not confirm a real customer's workflow or verify tailored business rules.

## Read The Result Correctly

| Result | Meaning and limit |
| --- | --- |
| Import `valid` / `invalid` / `not_checked` | Whether the resources passed the temporary import route. Import validity is not actual integration or an Agent score. |
| Rule conformance | Unchanged canonical `0.3.1` scoring configurations can be checked with real positive/negative/missing-evidence fixtures on both surfaces. Schema validation alone does not verify `expected`. |
| Custom scoring | Original case input/environment/requirements/gates must match the canonical profile; only permitted metadata and diagnostic tool spelling may differ. Tailored rules may import legally but remain `not_checked` until fixtures/profile are separately reviewed. Unsupported verifiers are `unsupported`. |
| Business readiness | Reported separately as `ready`, `evidence_required`, `integration_required`, `unsupported` or `not_checked`, with reasons. v0.1.0 provides no registered external collectors, so applicable business conditions remain at best `integration_required`. |

A claimed `evidence: sufficient` flag cannot upgrade readiness. Canonical fixture
conformance also does not confirm your workflow or company policy. Reference
fixtures test graders, never the Agent; keep them separate from genuinely
recorded traces. Candidate projection excludes reference answers, private fault
scripts and future replies/answers while retaining permitted materials needed to
solve the current task.

The matrix ties each applicable business gate to `verifier_id`/`verifier_version`
and actual case `requirement_ids`. Conditions needing confirmation have empty
`case_refs` and stay in drafts. Inspection also flags stale editable-install
distribution metadata rather than confusing it with the runtime version; the
pinned wheel compatibility baseline remains `0.3.0rc2`.

CLI/API/web import and explicit offline evaluation use built-in offline evaluators
only. An evaluator-set does not install a plugin. Tool/field mappings do not
connect an external tool backend or authenticate evidence. There is no external
collector bridge or public business-evidence upload in this release.

Keep unreviewed Targets outside `importable/`. A user-reviewed HTTP Target may be
structurally imported into the helper's temporary database only with the manifest
resource's `safety_review.confirmed: true` and confirmation `source_refs`, an
explicit `safety_review.execution_mode` recording the reviewed `dry_run`/`sandbox`
runtime, `safe_for_eval: true`, and no command. Keep that mode in the manifest
review, not `config.execution_mode`, which the HTTP importer does not accept.
Missing review rejects that Target import. This is recorded review,
not independent isolation verification or readiness; no check/connect/run occurs.
Python Targets remain separate integration handoffs with no local registration.

## Next Approval Boundary

Use the handoff's resource order/dependencies and gap ownership to plan the next
task. Agent/runtime changes, instrumentation, trusted collector/adapter work,
registration, real-project import, Target execution and paid evaluation are
outside this Skill. Each requires separately requested scope; a successful
offline validation does not authorize any of them. The existing
[Connect and import guide](ONBOARDING.md) documents later platform operations,
not steps that this Skill performs automatically.
