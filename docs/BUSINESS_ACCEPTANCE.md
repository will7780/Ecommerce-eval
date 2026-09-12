# Business acceptance and execution methods

The 0.3 bank has one acceptance result: all applicable declared business conditions
must be verified. It does not rank an API candidate above a file-editing candidate
because the former makes fewer calls.

## Three distinct inputs

- Candidate input: the current user task, permitted materials and current feedback.
- Evaluator input: required outcomes, fault scripts, future responses and test oracles.
- Business evidence: bytes, state, effect journal, checks and reviews collected by
  the registered environment before its workspace is reset.

Only the first goes to the model. Company rules are candidate-visible; hidden answer
labels and future replies are not. A connection mapping never rewrites the answer.

## Reading a result

Open Run Detail -> Metrics -> Business acceptance. Each requirement has a verifier
version, status, reason and evidence references:

| Status | Meaning |
| --- | --- |
| Pass | The applicable condition has sufficient supporting evidence. |
| Fail | Evidence proves a violation or incorrect result. |
| Error / evidence missing | The platform cannot finish verification. |
| N/A | The requirement explicitly does not apply. |

Missing evidence is not success. Required N/A does not silently pass a gate.
Tool schema checks, attempts, rounds and costs remain useful diagnostics. Only the
constraints the case explicitly declares become acceptance gates.

For example, a preview-only task needs the requested artifact AND a complete
run-scoped side-effect journal with no publication. A trace containing no
"publish" tool does not prove that a browser, request or other tool did not publish.
Publishing and retracting is still a violation of preview-only scope.

## Revision-bound review

Parameter validation checks the proposed operation. Artifact validation checks
the actual output. Risk confirmation authorizes a side effect. They are not
interchangeable approvals.

Full artifact validation covers all rows; five seeded normal samples and every
exception support human review. Approval binds company, scope, rule, content and
the entire file manifest. Editing or adding a file invalidates that approval.
Publication receipts identify the bytes actually consumed.

## Default bank

The current I01-S04 starter bank is dataset revision 0.3.1.
The 0.2.0 and 0.3.0 banks and their historical results remain unchanged. Eight directions cover
intent, company rules, dependencies, parameters, artifacts, conversation, recovery
and authorization/efficiency/cost. This is a starter bank, not universal coverage.

Price verification uses (price - cost) / price. The required price is rounded
up to the company's currency quantum, using decimal arithmetic.

## Candidate access

Business interface candidates use higher-level operations. File-editing candidates
read and write real isolated JSON/CSV files and use a restricted simulated backend.
Both share the same rules, files, approvals and journal. Neither has arbitrary shell
access or production-store access. A local subprocess alone is not a sandbox.

Imported traces remain useful diagnostics, but an imported "trusted" flag cannot
register a collector. Without independently collected side-effect evidence, negative
claims about external effects remain unverified.

## Explicit real-model smoke

Configure a provider in Settings first. The smoke runner pins its configuration
version and uses one model for both toolsets, sequentially. The default cases are
I01, C03, T01, P01, A03, M02, R03 and S02. The two experiments share a hard cap of
128 model requests; reaching it records unfinished runs, not invented answers.

```bash
python -m commerce_eval.business.smoke --database ./platform.db --project my-project \
  --provider deepseek --provider-version 1 --model YOUR_MODEL --allow-paid
```

The result reports pass, fail, evidence error and unfinished counts separately.
Model mistakes are valid experimental results. The offline reference traces test
the graders and are never presented as real model performance. Unknown usage and
cost stay unknown. No production writes or arbitrary code execution are enabled.
