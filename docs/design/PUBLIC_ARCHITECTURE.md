# Public architecture and contribution boundary

Platform candidate: **0.3.0rc2**. Business contract: **1.2**, with historical
1.0/1.1 imports. Starter bank: **0.3.1**. Onboarding Skill: **0.1.0**.
This source snapshot is Alpha, not a production-readiness claim.

## Product contract

One business acceptance standard, multiple execution methods and evidence
sources. Business conditions and explicitly declared gates decide acceptance;
tool names/counts are diagnostic unless a case explicitly constrains them.
Missing necessary evidence cannot become a pass or silently become N/A.

```text
Agent -> external adapter -> versioned contracts -> normalize/redact -> SQLite
Dataset -> controlled experiment -> evidence collection -> business verification
Stored evaluations -> FastAPI -> React evidence inspector
```

The core never imports a customer's runtime or an Agent framework. A tool result
claiming success is not independent business evidence. Local controlled scenarios
collect actual test files, review records and simulated backend effects; imported
self-reported traces cannot establish the absence of outside side effects.

## Source map

| Directory | Responsibility |
| --- | --- |
| `src/commerce_eval/contracts` | Versioned input, trace, case, evidence and metric models. |
| `src/commerce_eval/core`, `packs`, `business` | Normalization, explicit gates, resource accounting and registered deterministic verifiers. |
| `src/commerce_eval/scenarios`, `targets`, `experiments` | Anonymous bank, controlled environments and candidate execution. |
| `src/commerce_eval/storage`, `services`, `api` | Immutable records, import preview/commit and local HTTP APIs. |
| `src/commerce_eval/providers` | Non-secret provider configuration and server-side credential references. |
| `web`, `src/commerce_eval/static` | Editable frontend and packaged built UI. |
| `skills/ecommerce-eval-onboarding` | Product investigation, question drafts and offline integration handoff. |
| `tests`, `examples` | Offline regression and anonymous contract examples. |

## Extension and security rules

- Reuse public contracts; product adapters remain with their owners.
- Version metric/validator semantics; document applicability, evidence and N/A.
- Preserve historical datasets and evaluations. Re-evaluation creates a record.
- Default tests disable central credentials. Real model calls require opt-in.
- No hidden reasoning, keys, unauthorized material or raw sensitive payloads in
  traces, storage, docs, logs or screenshots.
- Active experiments are dry-run/sandbox only. Subprocesses are not containers.
- The Skill does not implement adapters, install dependencies, run exams or
  authorize changes to a customer's runtime. Importability is not readiness.

Current interfaces and limitations: [contracts](../CONTRACTS.md),
[business acceptance](../BUSINESS_ACCEPTANCE.md), [metrics](../METRICS.md),
[adapters](../ADAPTERS.md), [providers](../PROVIDERS.md) and
[Skill guide](../ONBOARDING_SKILL.md).

Private operational history is intentionally not part of this public checkout.
The public tests and fixtures are reproducible grader checks, not production
Agent success-rate evidence.
