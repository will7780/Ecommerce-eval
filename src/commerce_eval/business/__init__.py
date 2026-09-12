"""Business acceptance contract 1.2.

Runtime integration (all names below are business facts, never tool spellings):

* case.input = {message, assets: [reference dicts], context: {company_id}}.
* case.scenario_data.environment = {company_id, products, policy, faults,
  initial_facts, artifact_required, publish_required, review_required,
  risk_required}. ``faults`` are evaluator-only; do not project them to a model.
* case.scenario_data.interaction_script holds {type, fields, response}; new-turn
  user_message entries also have content. Future answers stay evaluator-side.
  case.business_requirements holds the answer rules.
* Every evidence entry has evidence_id, sequence (global increasing integer),
  company_id, turn (integer), at (ISO UTC). Artifacts additionally use the exact
  existing scenarios.artifacts.artifact_evidence/read_artifact_evidence format.
  Artifact subject is the logical business object (catalog); artifact_id is a
  separately company-scoped identity. Legacy artifacts may omit subject.
* initial_state.scope = {company_id, row_ids}; initial_state.products contains
  source rows. final_state.journal = {complete, company_id, row_ids, started_at,
  ended_at}. Its interval must cover the bundle and its row scope all requested
  rows. Empty complete effects proves absence; an omitted journal never does.
* effects: action (publish/retract/price_update/inventory_update/export), status
  (executed/blocked/failed/unknown/attempted/partial), row_ids, operation_id;
  partial effects include executed_row_ids. Artifact consumers
  also carry artifact_id/version/content_hash/manifest_hash/rule_version and
  review_id/approval_id when applicable. Retracting does not erase publication.
* checks: kind (artifact/source/parameters/policy), source (candidate/grader),
  subject, full, valid, checked_row_ids, errors, sample_row_ids, seed; artifact
  checks carry the full artifact identity. Grader checks cannot earn preflight.
* reviews: kind (artifact/risk/parameter), decision (approved/rejected/revise),
  review_id, interaction_id, source=user, action, row_ids, artifact identity.
  interactions: kind (request/response/user_message), interaction_id, type
  (clarification/confirmation/artifact_review), fields, values or decision.
* observations: kind (policy/query/failure/recovery/decision/audit/job_status),
  action, status, row_ids, data; recovery links failure_id. Failures expose
  failed_row_ids/succeeded_row_ids/recoverable/operation_id. Query and policy
  observations contain actual data, not a passed flag.
* A company switch includes initial_state.prior_context with company_id,
  artifact_ids, approval_ids and snapshot_hash, a context_switch observation
  with discarded_artifact_ids/invalidated_approval_ids and from/to_company_id,
  and final active_context_artifact_ids/active_approval_ids. Merely naming the
  previous company cannot prove an old context or approval was invalidated.
* Published contents are captured in final_state.published_rows. User waiting
  is measured by wait_interval observations; llm_usage records raw call usage.
* report: format=structured, content=<original JSON response string>. The JSON
  contains outcome, simulated, published_row_ids, failed_row_ids, failures,
  next_actions. Extra claims are not an oracle. Prose has no deterministic PASS.

Authenticating a collector is an outer service responsibility. These verifiers
validate completeness, scope, byte identities and predicates, not authenticity.
"""

from .verifiers import evaluate_business_requirements, verify_business_requirement

__all__ = ["evaluate_business_requirements", "verify_business_requirement"]
