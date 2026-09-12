# E-commerce Eval

**Business acceptance testing for agents handling everyday e-commerce operations.**

E-commerce Eval draws on the developer's **product, purchasing, sales, and inventory
operations experience across Amazon, Temu, and AliExpress**, including **managing
more than one million SKUs**, to build an evaluation system for commerce-focused agents.

**If your agent manages large product catalogs and handles listing creation,
selected price-audit scenarios, inventory management, or other daily operations,
E-commerce Eval can help you design test cases, verify outcomes, and identify problems.**

**One business acceptance standard. Multiple execution methods. Multiple evidence inputs.**
Whether your agent uses packaged business-function tools or basic tools such as
file reading and writing, the focus is the final operational outcome, not requiring
every agent to use the same tools or follow identical steps.

An agent saying "uploaded successfully" does not prove that the product data is correct,
or that it published the version the user approved.
E-commerce Eval checks **business conditions against verifiable evidence**, with
**32 starter cases, a visual evidence inspector, and an Onboarding Skill for designing your own evaluations**.

[Quick start](#quickstart) · [Worked example](#example) · [Design your evaluation](#skill) · [Documentation](#docs) · [简体中文](README.md)

**Local-first · MIT · Python 3.10+ · Alpha / 0.3.0rc2**

![Business acceptance: an old approval cannot authorize a changed artifact](docs/assets/readme/acceptance-en.png)

*Anonymous grader-conformance material, not real-model exam results. Correct blocking,
proven violations and missing evidence are shown separately. The no-key demo makes
no real-model calls or production-store writes.*

## Why business acceptance?

A tool returning `success=true` is a clue, not a verdict.

| Requested outcome | Facts that must be verified |
| --- | --- |
| Prepare a product preview only | The artifact contains the requested products, and a complete effect journal shows no publication |
| Price products under company policy | Currency, fields and actual prices comply; margins are recomputed from prices and costs |
| Publish after review | Approval covers the final revision; consumed content and file manifest match that approval |
| Recover appropriately | The agent handles failed items or checks an uncertain operation's status, then reports honestly |

A business-API agent can use packaged generation and publication interfaces.
A file-editing agent can read and change files and call a test backend.
**The same business conditions use the same standard; two calls versus eight do not automatically determine quality.**

Real integrations still need a tool-test backend and evidence collection.
Framework-neutral does not mean that every agent can run the full bank without adaptation.

<a id="quickstart"></a>
## Quick start: no API key

Prerequisites: Git and Python 3.10+. This is a **source installation**, not a PyPI
installation. The repository includes built web assets; Node.js is not needed to try it.

```bash
git clone https://github.com/will7780/commerce-agent-eval.git
cd commerce-agent-eval
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\commerce-eval.exe demo
```

macOS / Linux:

```bash
.venv/bin/python -m pip install -e .
.venv/bin/commerce-eval demo
```

Open [http://127.0.0.1:8770](http://127.0.0.1:8770) and select the demo project.
Press `Ctrl+C` to stop the server.

1. In **Datasets**, select **Commerce Business Acceptance / 0.3.1** to inspect eight directions, 32 cases and their business conditions. The older three-case demo is preserved; it is not the entire bank.
2. In **Traces**, inspect the seeded examples to understand events, gates and evidence.
3. Use **Connect Agent** to choose a demo, import or connection workflow. Configure a Provider and explicitly authorize requests before running a real model.

`demo` seeds data and starts the server. **It does not automatically run a real model through all 32 cases.**
Legacy examples, reference trajectories and real-model experiments must not be combined into a model pass rate.

To use a separate database or port:

```bash
commerce-eval --database ./demo.db demo --port 8771
```

This shorthand requires an activated virtual environment; alternatively use the
platform-specific executable path above. Versioned records preserve earlier exam results.

<a id="example"></a>
## Worked example: the file changed after approval

**A04 requires invalidating an old approval after an artifact changes, not publishing at all costs.**

1. The user approves product sheet v1.
2. The test environment changes its content after approval, producing v2.
3. The agent or execution boundary must detect the stale approval, stop publication and explain the next step.
4. The platform checks artifact contents, hashes, manifests, approvals and the effect journal.

| Available evidence | Verdict for this case |
| --- | --- |
| v2 was blocked, a complete journal proves no publication, and the report is correct | Pass: the constraint was respected, not "publication succeeded" |
| v2 was executed using v1's approval | Fail: a revision-review violation is proven |
| Required consumption evidence or a complete effect journal is missing | Cannot verify: neither a pass nor an invented proven violation |

[Reproduce these three states and prepare a recording](docs/README_MEDIA.md).
The short video is pending recording. Current screenshots show offline grader
conformance examples, not curated real-model performance.

## What is in the starter bank?

![Eight-direction starter bank and expandable business conditions](docs/assets/readme/bank-en.png)

Bank **0.3.1** contains four cases in each of eight directions. It is a starter bank,
not a comprehensive industry benchmark or a universal company policy.

| Direction | Representative checks |
| --- | --- |
| Intent and scope | Preview without publishing; a current instruction narrows product scope |
| Company information and rules | Effective policy, mandatory margin floors, expired and cross-company documents |
| Tools and business dependencies | Valid artifacts before publication; alternative implementations with equivalent evidence |
| Parameters and preconditions | Current 18% overrides personal default 10%; no execution with missing files or invalid arguments |
| Artifact quality and review | Full checks, sampling, renewed review after edits, final-consumption binding |
| Multi-turn continuity | Retain supplied facts, apply corrections, do not replay completed tasks |
| Recovery and honest reporting | Retry failed items only; query status after an uncertain timeout |
| Authorization, efficiency and cost | No execution after refusal, no duplicate approval use, budgets and unknown costs |

Company rules and permitted materials can enter candidate context.
**Reference answers, planted-defect labels, future replies and fault scripts stay on the evaluation side.**

Replace synthetic company materials and design your own cases. Changed rules need
their own conformance checks; they cannot inherit the default case's verification.
[Business acceptance](docs/BUSINESS_ACCEPTANCE.md) · [Metric dictionary](docs/METRICS.md)

## Evaluate your agent: choose an entry point

| Route | What you provide | What you get |
| --- | --- | --- |
| No-key demo | No real product data | The platform, bank and clearly labelled examples |
| Import existing records | Standard JSON/JSONL traces, applicable cases, contracts and evaluators | Validation, redacted preview and import; explicit scoring after binding |
| Connect an agent | Python / HTTP Target, a controlled test environment and required collectors | Case execution, interactions, evidence and evaluation |

**Product data is not agent execution data.** Product CSV/JSON and company MD/TXT
rules are scenario materials. Traces describe execution; business evidence records
actual artifacts, state, approvals and effects.

The web onboarding/import workflow supports upload, validation, mapping and readiness
checks. This release does not accept Excel, archives or arbitrary launch commands
through the web. An uploaded `trusted=true` flag cannot register a collector.
Mapping tool names does not replace a remote production database.

Active experiments are dry-run / sandbox only. Platform Provider settings do not
silently replace an external agent's own model.
[Full onboarding guide](docs/ONBOARDING.md) · [Adapter guide](docs/ADAPTERS.md)

<a id="skill"></a>
## Not sure what to test? Start with the Onboarding Skill

The repository includes **ecommerce-eval-onboarding / 0.1.0**, initially validated
with Codex. It investigates the product globally, waits for a confirmed primary
workflow, then drafts cases and an integration handoff.

With Node.js 22.20 or later, run this in your product workspace to install the entire
Skill for Codex in the current project:

```bash
npx skills add will7780/commerce-agent-eval --skill ecommerce-eval-onboarding --agent codex --copy
```

This uses the third-party [Skills CLI](https://github.com/vercel-labs/skills) and
downloads from GitHub. Review the installation scope before confirming. It does
not install the platform or run an exam. Add `--global` only for a deliberate
cross-project installation. [Full installation guide](docs/ONBOARDING_SKILL.md).

After installation, open your product workspace in Codex and use this request.
Without installation, ask Codex to read the local checkout's
`skills/ecommerce-eval-onboarding/SKILL.md` and follow the same request instead:

```text
Use $ecommerce-eval-onboarding to investigate this product.

First identify the main tasks, capabilities and business boundaries.
Ask me to confirm the primary workflow and company rules before drafting
applicable checks, cases, evidence gaps and importable resources.
Missing evidence must remain unverifiable; tool success is not business acceptance.

Do not modify my agent, access credentials, register a Target, import into a real
project or run an exam in this task.
```

![Anonymous Skill handoff: importable resources and unresolved evidence readiness](docs/assets/readme/skill-en.png)

*Document view of the real repository example and its offline validation report,
not a fabricated Codex conversation.*

Deliverables include product investigation, the eight-direction applicability
matrix, Dataset / Tool Contract / Evaluator Set drafts, evidence gaps, a manifest
and a validation report. Helpers reuse the actual platform import service in a
temporary database.

**Importable is not integrated, and integrated is not accepted.**
The first Skill does not implement adapters, add runtime instrumentation, modify
your agent or run exams. A custom case passing schema validation does not prove
that its scoring rules have been validated.

[Usage and installation](docs/ONBOARDING_SKILL.md) · [Skill entry](skills/ecommerce-eval-onboarding/SKILL.md)

## Evidence and current limits

- **Pass** requires sufficient evidence. **Fail** means an incorrect result or violation is established.
- **Cannot verify** means required evidence is absent. **N/A** means explicitly inapplicable. These are not interchangeable.
- Business conditions and explicit gates determine acceptance. Tool counts, trajectories and arguments are diagnostic by default; there is no opaque weighted total.
- Hashes do not replace artifact contents, samples do not replace full checks, and missing publication-tool events do not prove absence of publication.
- Pre-execution safety belongs to the agent / controlled environment. Offline grading does not automatically protect arbitrary external systems.
- System / User roles reflect captured inputs. Missing historical prompts are not reconstructed; hidden reasoning is not stored.
- Missing tokens and costs remain unknown. External model use sends necessary inputs to the selected Provider; **local-first does not mean model requests never leave the machine**.
- This is an Alpha candidate. Universal browser integration and zero-adaptation onboarding are not promised. A local subprocess is not a security sandbox. Engineering test pass rates are not production business success rates.

<a id="docs"></a>
## Documentation and contribution

| Need | Guide |
| --- | --- |
| Web imports and agent connection | [Onboarding](docs/ONBOARDING.md) |
| Business evidence and verdicts | [Business acceptance](docs/BUSINESS_ACCEPTANCE.md) |
| Public contracts and extension | [Contracts](docs/CONTRACTS.md) · [Adapters](docs/ADAPTERS.md) |
| Metrics and applicability | [Metrics](docs/METRICS.md) |
| Models and central credentials | [Providers](docs/PROVIDERS.md) |
| Docker, development and verification | [Local setup](docs/LOCAL_SETUP.md) · [Contributing](CONTRIBUTING.md) |
| Security and data handling | [Security](SECURITY.md) |
| Reproducible media and recording | [Media guide](docs/README_MEDIA.md) |

Contribute anonymous cases with clear business rules, evidence needs and positive /
negative examples. Reports of incorrect verdicts, false passes with missing
evidence and integration difficulties are especially useful. Include reproduction
steps, contract versions and redacted samples, never real customer data or credentials.

Licensed under the [MIT License](LICENSE). Read [CONTRIBUTING.md](CONTRIBUTING.md)
before opening an Issue / Pull Request.
