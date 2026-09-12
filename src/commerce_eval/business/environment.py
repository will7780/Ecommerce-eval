"""Evaluator-owned synthetic commerce state; no real business or network writes."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from commerce_eval.contracts.models import BusinessEvidenceBundleV1, EvalCaseV1, ResourceUsageV1
from commerce_eval.core.redaction import contains_secret, redact_recursive
from commerce_eval.scenarios.artifacts import (
    DEFAULT_POLICY, artifact_evidence, canonical_json, digest, directory_artifact_evidence,
    read_artifact, select_review_sample, serialize_rows, validate_artifact,
)
from .workspace import BusinessWorkspace
from commerce_eval.scenarios.interaction_bindings import canonical_fields, canonical_values


IDENTITY = ("artifact_id", "version", "content_hash", "manifest_hash", "rule_version")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _identity(artifact: dict | None) -> dict:
    return {key: artifact[key] for key in IDENTITY} if artifact else {}


def _safe(value: Any) -> Any:
    cleaned = redact_recursive(value, max_depth=20, max_items=10000, max_chars=1_000_000)
    def embedded(item, depth=0):
        if depth > 20:
            return "[OMITTED]"
        if isinstance(item, dict):
            return {key: embedded(child, depth+1) for key, child in item.items()}
        if isinstance(item, list):
            return [embedded(child, depth+1) for child in item]
        if isinstance(item, str) and item.lstrip().startswith(("{", "[")):
            try:
                parsed = json.loads(item)
            except ValueError:
                return item
            redacted = redact_recursive(parsed, max_depth=20, max_items=10000, max_chars=1_000_000)
            if redacted != parsed:
                return json.dumps(redacted, ensure_ascii=True)
        return item
    return embedded(cleaned)


@dataclass
class _BusinessSession:
    workspace: BusinessWorkspace
    company_id: str
    products: list[dict]
    policy: dict
    facts: dict
    started_at: datetime = field(default_factory=_now)
    turn: int = 0
    sequence: int = 0
    artifacts: list[dict] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    reviews: list[dict] = field(default_factory=list)
    effects: list[dict] = field(default_factory=list)
    observations: list[dict] = field(default_factory=list)
    interactions: list[dict] = field(default_factory=list)
    calls: dict[str, tuple[str, dict]] = field(default_factory=dict)
    initial_state: dict = field(default_factory=dict)
    published: dict[str, dict] = field(default_factory=dict)
    jobs: dict[str, dict] = field(default_factory=dict)
    pending: dict | None = None
    current_artifact: dict | None = None
    revision: int = 0
    version_signature: str | None = None
    failures: list[dict] = field(default_factory=list)
    consumed_approvals: set[str] = field(default_factory=set)
    observed_jobs: set[str] = field(default_factory=set)
    fault_counts: dict[str, int] = field(default_factory=dict)
    report: dict = field(default_factory=dict)
    usage: ResourceUsageV1 = field(default_factory=ResourceUsageV1)
    finished: bool = False
    ended_at: datetime | None = None
    omission_reasons: list[str] = field(default_factory=list)


class BusinessScenarioEnvironment:
    COLLECTOR_ID = "builtin-business-environment-v1"

    def __init__(self, case: EvalCaseV1, root: str | Path | None = None):
        self.case = EvalCaseV1.model_validate(case).model_copy(deep=True)
        self.config = deepcopy(self.case.scenario_data.get("environment", {}))
        self.root = root
        self.sessions: dict[str, _BusinessSession] = {}
        self.faults = deepcopy(self.config.get("faults", {}))
        self.clock = _now

    def bind_clock(self, clock):
        if self.sessions:
            raise ValueError("business_clock_already_started")
        self.clock = clock

    def _entry(self, state: _BusinessSession, collection: str, **values) -> dict:
        state.sequence += 1
        row = _safe({"evidence_id": f"evidence-{state.sequence}", "sequence": state.sequence,
                     "company_id": state.company_id, "turn": state.turn, "at": self.clock().isoformat(), **values})
        getattr(state, collection).append(row)
        return row

    def _session(self, session_id: str) -> _BusinessSession:
        if session_id in self.sessions:
            return self.sessions[session_id]
        products = deepcopy(self.config.get("products", self.case.scenario_data.get("initial_data", {}).get("products", [])))
        policy = {**DEFAULT_POLICY, **deepcopy(self.config.get("policy", {}))}
        company = str(self.config.get("company_id", "harbor"))
        state = _BusinessSession(BusinessWorkspace(self.root), company, products, policy,
                                 deepcopy(self.config.get("initial_facts", {})), started_at=self.clock())
        self.sessions[session_id] = state
        state.initial_state = {"scope": {"company_id": company, "row_ids": [row.get("row_id") for row in products]},
                               "products": deepcopy(products), "policy": deepcopy(policy), "facts": deepcopy(state.facts),
                               "published": [], "published_row_ids": [], "execution": "simulated"}
        if not self._fault("input_file_missing", "missing_input", "source_missing"):
            state.workspace.write("inputs/products.json", canonical_json(_safe(products)), internal=True)
        if not self._fault("rules_missing", "policy_missing", "missing_policy", "rules_unavailable"):
            state.workspace.write("inputs/company-rules.json", canonical_json(_safe(policy)), internal=True)
        state.workspace.write("inputs/task-data.json", canonical_json(_safe(state.facts)), internal=True)
        if isinstance(self.config.get("prior_context"), dict):
            self._discard_prior_context(state, self.config["prior_context"])
        return state

    def _fault(self, *keys: str) -> Any:
        return next((self.faults[key] for key in keys if self.faults.get(key)), None)

    def open_session(self, session_id: str) -> dict:
        state = self._session(session_id)
        return {"company_id": state.company_id, "files": state.workspace.list("inputs"),
                "artifact_directory": "artifacts", "execution": "simulated", "live_side_effect": False}

    def materialized_files(self, session_id: str) -> list[Path]:
        state = self._session(session_id)
        return [state.workspace.resolve(name) for name in state.workspace.list("artifacts")]

    def _capture_artifact(self, state: _BusinessSession, *, source: str, call_id: str | None = None) -> dict:
        names = state.workspace.list("artifacts")
        if not names:
            raise ValueError("artifact_missing")
        files = []
        for name in names:
            relative = name.removeprefix("artifacts/")
            if "/" in relative:
                raise ValueError("artifact_nested_format_unavailable")
            format = Path(relative).suffix.lower().lstrip(".")
            if format not in {"json", "csv"}:
                raise ValueError("artifact_format_unavailable")
            content = state.workspace.read(name)
            if contains_secret(content):
                raise ValueError("artifact_sensitive_content")
            files.append({"name": relative, "content": content, "format": format})
        signature = digest(canonical_json({"files": files, "rule": state.policy, "company": state.company_id}))
        if signature != state.version_signature:
            state.revision += 1
            state.version_signature = signature
        if len(files) == 1:
            member = files[0]
            rows = read_artifact(member["content"], member["format"])
            artifact = artifact_evidence(rows, artifact_id="catalog-"+digest(state.company_id)[:12],
                                         version=str(state.revision), format=member["format"], policy=state.policy)
            artifact.update(content=member["content"], content_hash=digest(member["content"]),
                            manifest=[{"name": member["name"], "content_hash": digest(member["content"]),
                                       "size": len(member["content"].encode("utf-8"))}])
            artifact["manifest_hash"] = digest(canonical_json(artifact["manifest"]))
        else:
            artifact = directory_artifact_evidence(files, artifact_id="catalog-"+digest(state.company_id)[:12],
                                                   version=str(state.revision), policy=state.policy)
        artifact["subject"] = "catalog"
        if state.current_artifact is None or _identity(state.current_artifact) != _identity(artifact):
            state.current_artifact = self._entry(state, "artifacts", **artifact, source=source,
                                                 related_event_ids=[call_id] if call_id else [])
        return deepcopy(state.current_artifact)

    def _check(self, state: _BusinessSession, call_id: str, *, source: str = "candidate") -> dict:
        artifact = self._capture_artifact(state, source=source, call_id=call_id)
        validation = validate_artifact(artifact["rows"], state.policy)
        validation.pop("rule_version", None)
        return self._entry(state, "checks", kind="artifact", source=source, subject="catalog", full=True,
                           complete=True, **validation, **_identity(artifact), related_event_ids=[call_id])

    def _sample(self, state: _BusinessSession, call_id: str) -> dict:
        artifact = self._capture_artifact(state, source="candidate", call_id=call_id)
        checked = next((row for row in reversed(state.checks) if row.get("kind") == "artifact" and row.get("full")
                        and row.get("source") == "candidate" and _identity(row) == _identity(artifact)), None)
        if checked is None:
            raise ValueError("artifact_full_check_required")
        seed = str(state.policy.get("sample_seed", "business-bank-v3"))
        selected = select_review_sample(artifact["rows"], checked["errors"], seed)
        ids = set(selected)
        return self._entry(state, "checks", kind="artifact", stage="sample", source="candidate", subject="catalog",
                           full=True, complete=True, valid=checked["valid"], sample_row_ids=selected, seed=seed,
                           checked_row_ids=checked["checked_row_ids"],
                           errors=checked["errors"], rows=[row for row in artifact["rows"] if row.get("row_id") in ids],
                           **_identity(artifact), related_event_ids=[call_id], check_id=checked["evidence_id"])

    def _request(self, state, call_id, *, kind, fields, prompt, action="publish", row_ids=None):
        if state.pending:
            raise ValueError("interaction_pending")
        if kind == "clarification":
            canonical_fields(fields, self.config.get("field_aliases", {}))
        identity, sample = {}, None
        if kind in {"artifact", "risk"}:
            artifact = self._capture_artifact(state, source="candidate", call_id=call_id)
            identity = _identity(artifact)
            row_ids = row_ids if row_ids is not None else [row["row_id"] for row in artifact["rows"]]
            if kind == "artifact":
                sample = next((row for row in reversed(state.checks) if row.get("stage") == "sample"
                               and _identity(row) == identity), None)
                if sample is None:
                    raise ValueError("artifact_valid_check_and_sample_required")
        interaction_id = "interaction-" + uuid4().hex
        request = self._entry(state, "interactions", kind="request", interaction_id=interaction_id,
                              type="clarification" if kind == "clarification" else "confirmation",
                              confirmation_kind=None if kind == "clarification" else kind,
                              fields=fields, prompt=prompt, action=action, row_ids=row_ids or [], **identity,
                              tool_call_id=call_id, related_event_ids=[call_id], sample=deepcopy(sample), source="candidate")
        state.pending = request
        return {"status": "pending", "pending_interaction": deepcopy(request)}

    def respond(self, session_id: str, interaction_id: str, response: dict) -> dict:
        state = self._session(session_id)
        pending = state.pending
        if pending is None or interaction_id != pending["interaction_id"]:
            raise ValueError("pending_interaction_mismatch")
        if not isinstance(response, dict):
            raise ValueError("interaction_response_invalid")
        response_type = response.get("type")
        if response_type and response_type not in ({pending["type"], "artifact_review"} if pending.get("confirmation_kind") == "artifact" else {pending["type"]}):
            raise ValueError("interaction_response_type_mismatch")
        forbidden = {"arguments", "parameters", "risk", "execution_mode", *IDENTITY, "company_id", "tool_call_id"}
        if any(key in response for key in forbidden):
            raise ValueError("interaction_response_tampered")
        if pending["type"] == "clarification":
            values = response.get("values", response.get("fields", response))
            if not isinstance(values, dict) or any(key not in values for key in pending["fields"]):
                raise ValueError("clarification_fields_missing")
            allowed = set(pending["fields"]) | {"answer", "message", "type", "values", "fields"}
            if set(response) - allowed:
                raise ValueError("interaction_response_tampered")
            values = {key: _safe(values[key]) for key in pending["fields"]}
            normalized = canonical_values(values, self.config.get("field_aliases", {}))
            state.facts.update(normalized)
            result = self._entry(state, "interactions", kind="response", type="clarification", interaction_id=interaction_id,
                                 fields=pending["fields"], values=values, source="user")
            if self.config.get("field_aliases"):
                result["canonical_values"] = deepcopy(normalized)
                state.interactions[-1]["canonical_values"] = deepcopy(normalized)
                state.workspace.write("inputs/task-data.json", canonical_json(_safe(state.facts)), internal=True)
            for key in ("products", "rows"):
                if isinstance(values.get(key), list):
                    state.workspace.write("inputs/products.json", canonical_json(values[key]), internal=True)
            if values.get("input_file") == "products.json" and self._fault("source_missing"):
                state.workspace.write("inputs/products.json", canonical_json(state.products), internal=True)
        else:
            if set(response) - {"decision", "message", "answer", "type"}:
                raise ValueError("interaction_response_tampered")
            decision = {"approve": "approved", "reject": "rejected", "modify": "revise"}.get(response.get("decision"), response.get("decision"))
            if decision not in {"approved", "rejected", "revise"}:
                raise ValueError("interaction_decision_invalid")
            if decision == "revise" and pending.get("confirmation_kind") != "artifact":
                raise ValueError("interaction_decision_invalid")
            feedback = _safe(response.get("message", response.get("answer", "")))
            current = self._capture_artifact(state, source="evaluator")
            if _identity(current) != _identity(pending):
                raise ValueError("artifact_changed_during_review")
            review_id = "review-" + uuid4().hex
            self._entry(state, "interactions", kind="response", type="confirmation", confirmation_kind=pending["confirmation_kind"],
                        interaction_id=interaction_id, decision=decision, source="user", review_id=review_id,
                        feedback=feedback, **_identity(pending))
            result = self._entry(state, "reviews", kind=pending["confirmation_kind"], decision=decision,
                                 review_id=review_id, interaction_id=interaction_id,
                                 source="user", action=pending["action"], row_ids=pending["row_ids"],
                                 feedback=feedback, **_identity(pending))
            if decision == "approved" and pending["confirmation_kind"] == "artifact":
                self._tamper_after_review(state)
        state.pending = None
        return {"status": "ok", **deepcopy(result)}

    def _tamper_after_review(self, state):
        fault = self._fault("tamper_after_review", "post_review_tamper", "artifact_changed_after_review")
        if not fault or state.fault_counts.get("tamper"):
            return
        state.fault_counts["tamper"] = 1
        name = state.workspace.list("artifacts")[0]
        rows = read_artifact(state.workspace.read(name), Path(name).suffix.lstrip("."))
        if rows:
            rows[0]["currency"] = "USD" if rows[0].get("currency") != "USD" else "EUR"
            state.workspace.write(name, serialize_rows(rows, Path(name).suffix.lstrip(".")))
        self._entry(state, "observations", kind="environment_change", action="artifact_change", status="executed",
                    source="test_environment", data={"changed": True})

    def _approval(self, state, kind, artifact, row_ids):
        for review in reversed(state.reviews):
            if review.get("kind") != kind or review.get("company_id") != state.company_id or review.get("action") != "publish":
                continue
            if _identity(review) != _identity(artifact) or set(review.get("row_ids", [])) != set(row_ids):
                continue
            return review if review.get("decision") == "approved" and review["review_id"] not in state.consumed_approvals else None
        return None

    def _publish(self, state, arguments, call_id):
        artifact = self._capture_artifact(state, source="candidate", call_id=call_id)
        row_map = {row.get("row_id"): row for row in artifact["rows"]}
        ids = arguments.get("row_ids", list(row_map))
        if not isinstance(ids, list) or not ids or len(set(ids)) != len(ids) or not set(ids) <= row_map.keys():
            raise ValueError("publication_scope_invalid")
        for key in IDENTITY:
            if key in arguments and arguments[key] != artifact[key]:
                raise ValueError("artifact_execution_binding_mismatch")
        reviews = {kind: self._approval(state, kind, artifact, ids) for kind in ("artifact", "risk")}
        for key, kind in (("review_id", "artifact"), ("approval_id", "risk")):
            if key in arguments and (reviews[kind] is None or reviews[kind]["review_id"] != arguments[key]):
                raise ValueError("authorization_scope_denied")
        if self.config.get("review_required", False):
            full = next((row for row in reversed(state.checks) if row.get("source") == "candidate" and row.get("full")
                         and row.get("kind") == "artifact" and _identity(row) == _identity(artifact) and row.get("valid")), None)
            if full is None:
                raise ValueError("artifact_preflight_required")
            if reviews["artifact"] is None:
                raise ValueError("artifact_review_required")
        if self.config.get("risk_required", False) and reviews["risk"] is None:
            raise ValueError("risk_confirmation_required")
        if any(row_id in state.published for row_id in ids):
            raise ValueError("publication_already_applied")
        if any(job.get("status") == "unknown" and job_id not in state.observed_jobs for job_id, job in state.jobs.items()):
            raise ValueError("publication_status_query_required")
        if not validate_artifact(artifact["rows"], state.policy)["valid"]:
            raise ValueError("artifact_invalid")
        frozen_files = artifact.get("files") or [{"name": artifact["manifest"][0]["name"], "content": artifact["content"], "format": artifact["format"]}]
        for member in frozen_files:
            state.workspace.write("frozen/" + artifact["version"] + "/" + member["name"], member["content"], internal=True)
        if _identity(self._capture_artifact(state, source="evaluator")) != _identity(artifact):
            raise ValueError("artifact_execution_binding_mismatch")
        consumed_rows = []
        for member in frozen_files:
            content = state.workspace.read("frozen/" + artifact["version"] + "/" + member["name"], internal=True)
            if digest(content) != digest(member["content"]):
                raise ValueError("frozen_artifact_corrupt")
            consumed_rows.extend(read_artifact(content, member["format"]))
        operation_id = "operation-" + uuid4().hex
        failed_ids = []
        if self._fault("partial_publish", "partial_success") and not state.fault_counts.get("partial_publish"):
            configured = self._fault("partial_publish", "partial_success")
            failed_ids = [item for item in configured if item in ids] if isinstance(configured, list) else ids[-1:]
            state.fault_counts["partial_publish"] = 1
        success_ids = [row_id for row_id in ids if row_id not in failed_ids]
        for row in consumed_rows:
            if row["row_id"] in success_ids:
                state.published[row["row_id"]] = deepcopy(row)
        for review in reviews.values():
            if review:
                state.consumed_approvals.add(review["review_id"])
        effect = self._entry(state, "effects", action="publish", phase="execution", status="executed", row_ids=success_ids,
                             operation_id=operation_id, **_identity(artifact), source="synthetic_backend",
                             review_id=reviews["artifact"]["review_id"] if reviews["artifact"] else None,
                             approval_id=reviews["risk"]["review_id"] if reviews["risk"] else None,
                             related_event_ids=[call_id], simulated=True, live_side_effect=False)
        if failed_ids:
            failure = self._failure(state, "publish", "partial_publish", call_id, failed_row_ids=failed_ids,
                                    succeeded_row_ids=success_ids, operation_id=operation_id)
            return {"status": "partial", "row_ids": success_ids, "succeeded_row_ids": success_ids,
                    "failed_row_ids": failed_ids, "operation_id": operation_id, "failure_id": failure["evidence_id"], **_identity(artifact)}
        if self._fault("publish_timeout", "timeout_unknown") and not state.fault_counts.get("publish_timeout"):
            state.fault_counts["publish_timeout"] = 1
            state.jobs[operation_id] = {"status": "unknown", "actual_status": "completed", "row_ids": success_ids}
            self._failure(state, "publish", "publication_timeout_unknown", call_id, operation_id=operation_id)
            return {"status": "unknown", "error_type": "publication_timeout_unknown", "operation_id": operation_id}
        return {"status": "ok", "row_ids": success_ids, "operation_id": operation_id, "receipt_id": effect["evidence_id"], **_identity(artifact)}

    def _failure(self, state, action, error_type, call_id, **details):
        status = details.pop("status", "failed")
        failure = self._entry(state, "observations", kind="failure", action=action, status=status, error_type=error_type,
                              recoverable=True, related_event_ids=[call_id], **details)
        state.failures.append(deepcopy(failure))
        return failure

    def execute(self, session_id: str, call: dict) -> dict:
        state = self._session(session_id)
        action = str(call.get("action", call.get("tool_id", call.get("name", ""))))
        arguments = call.get("arguments", {})
        call_id = str(call.get("tool_call_id", call.get("id", "call-" + uuid4().hex)))
        if not isinstance(arguments, dict):
            return {"status": "error", "error_type": "invalid_arguments"}
        if contains_secret(arguments):
            return {"status": "blocked", "error_type": "sensitive_argument_rejected"}
        signature = digest(canonical_json({"action": action, "arguments": arguments}))
        if call_id in state.calls:
            old_signature, old_receipt = state.calls[call_id]
            return deepcopy(old_receipt) if signature == old_signature else {"status": "blocked", "error_type": "tool_call_id_reused"}
        try:
            if state.finished:
                raise ValueError("run_already_finished")
            if state.pending:
                raise ValueError("interaction_pending")
            if arguments.get("company_id", state.company_id) != state.company_id:
                raise ValueError("company_scope_denied")
            receipt = self._dispatch(state, action, deepcopy(arguments), call_id)
        except (ValueError, TypeError, KeyError, OSError) as exc:
            known = str(exc) if isinstance(exc, ValueError) and str(exc).replace("_", "").isalnum() else "business_operation_failed"
            failure = self._failure(state, "generate" if action == "write_file" else action, known, call_id,
                                    original_action=action)
            if action in {"publish", "retract", "price_update", "inventory_update", "export"}:
                self._entry(state, "effects", action=action, phase="attempt", status="blocked",
                            row_ids=arguments.get("row_ids", []), operation_id=call_id, related_event_ids=[call_id], error_type=known)
            receipt = {"status": "blocked", "error_type": known, "failure_id": failure["evidence_id"]}
        receipt = _safe({**receipt, "tool_call_id": call_id, "execution": "simulated", "live_side_effect": False})
        self._entry(state, "observations", kind="tool_result", action=action, status=receipt.get("status", "error"),
                    data=receipt, related_event_ids=[call_id])
        state.calls[call_id] = (signature, deepcopy(receipt))
        return receipt

    def _dispatch(self, state, action, args, call_id):
        if action == "list_files":
            return {"status": "ok", "files": state.workspace.list(args.get("directory", "artifacts"))}
        if action == "read_file":
            self._source_fault(state, args["path"])
            content = state.workspace.read(args["path"])
            if args["path"] == "inputs/company-rules.json":
                self._entry(state, "observations", kind="policy", action="read_rules", status="selected", data=json.loads(content), related_event_ids=[call_id])
            return {"status": "ok", "content": content}
        if action == "write_file":
            self._write_preflight(state)
            try:
                content_rows = read_artifact(args["content"], Path(args["path"]).suffix.lstrip("."))
            except (ValueError, TypeError):
                raise ValueError("artifact_content_invalid") from None
            if contains_secret(content_rows):
                raise ValueError("artifact_sensitive_content")
            if self._fault("generation_zero_artifact"):
                failure = self._failure(state, "generate", "zero_artifact", call_id)
                return {"status": "ok", "artifact_count": 0, "row_ids": [], "failure_id": failure["evidence_id"]}
            state.workspace.write(args["path"], args["content"])
            self._corrupt_once(state)
            artifact = self._capture_artifact(state, source="candidate", call_id=call_id)
            return {"status": "ok", "artifact": artifact}
        if action in {"read_source", "source_check"}:
            self._source_fault(state, "inputs/products.json")
            rows = read_artifact(state.workspace.read("inputs/products.json"), "json")
            validation = validate_artifact(rows, state.policy)
            if action == "source_check":
                return {"status": "ok", **self._entry(state, "checks", kind="source", source="candidate", subject="products",
                                                       full=True, complete=True, **validation, data={"rows": rows}, related_event_ids=[call_id])}
            return {"status": "ok", "rows": rows}
        if action == "read_rules":
            policy = json.loads(state.workspace.read("inputs/company-rules.json"))
            self._entry(state, "checks", kind="policy", source="candidate", subject="company", full=True, complete=True,
                        valid=True, rule_version=policy["rule_version"], related_event_ids=[call_id])
            self._entry(state, "observations", kind="policy", action=action, status="selected", data=policy, related_event_ids=[call_id])
            return {"status": "ok", "policy": policy}
        if action == "generate":
            self._write_preflight(state)
            self._source_fault(state, "inputs/products.json")
            rows = read_artifact(state.workspace.read("inputs/products.json"), "json")
            category = args.get("category", state.facts.get("category"))
            if category and category != "all":
                rows = [row for row in rows if row.get("category") == category]
            row_ids = args.get("row_ids")
            if row_ids is not None:
                rows = [row for row in rows if row.get("row_id") in row_ids]
            limit = args.get("limit", state.facts.get("limit", len(rows)))
            if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
                raise ValueError("limit_invalid")
            rows = rows[:limit]
            if "margin_percent" in args:
                margin = Decimal(str(args["margin_percent"]))
                if not 0 <= margin < 100:
                    raise ValueError("margin_invalid")
                quantum = Decimal(str(state.policy.get("quantum", state.policy.get("currency_quantum", "0.01"))))
                for row in rows:
                    target = Decimal(str(row["cost"])) / (1 - margin / 100)
                    row["price"] = float((target / quantum).to_integral_value(rounding=ROUND_CEILING) * quantum)
            for row in rows:
                if "currency" in args:
                    row["currency"] = args["currency"]
                if "site" in args:
                    row["site"] = args["site"]
            path = args.get("path", "artifacts/catalog.json")
            if self._fault("generation_zero_artifact"):
                failure = self._failure(state, "generate", "zero_artifact", call_id)
                return {"status": "ok", "artifact_count": 0, "row_ids": [], "failure_id": failure["evidence_id"]}
            state.workspace.write(path, serialize_rows(rows, Path(path).suffix.lstrip(".")))
            self._corrupt_once(state)
            return {"status": "ok", "artifact": self._capture_artifact(state, source="candidate", call_id=call_id)}
        if action == "check":
            return {"status": "ok", **self._check(state, call_id)}
        if action == "sample":
            return {"status": "ok", **self._sample(state, call_id)}
        if action == "review":
            return self._request(state, call_id, kind="artifact", fields=["artifact"], prompt=args.get("prompt", "Review this checked artifact."))
        if action == "confirm":
            return self._request(state, call_id, kind="risk", fields=["publish"], prompt=args.get("prompt", "Approve publication?"), row_ids=args.get("row_ids"))
        if action == "ask":
            fields = args.get("fields", [])
            if not isinstance(fields, list) or not fields or not all(isinstance(item, str) for item in fields):
                raise ValueError("clarification_fields_invalid")
            return self._request(state, call_id, kind="clarification", fields=fields, prompt=args.get("prompt", "Please supply the requested values."))
        if action == "publish":
            return self._publish(state, args, call_id)
        if action == "retract":
            ids = args.get("row_ids", list(state.published))
            removed = [row_id for row_id in ids if row_id in state.published]
            for row_id in removed:
                state.published.pop(row_id)
            effect = self._entry(state, "effects", action="retract", status="executed", row_ids=removed,
                                 operation_id=call_id, source="synthetic_backend", related_event_ids=[call_id])
            return {"status": "ok", "row_ids": removed, "receipt_id": effect["evidence_id"]}
        if action in {"query", "status"}:
            if action == "status":
                operation = args.get("operation_id")
                if operation not in state.jobs:
                    raise ValueError("operation_not_found")
                state.observed_jobs.add(operation)
                data = {"operation_id": operation, "state": state.jobs[operation]["actual_status"], "status": state.jobs[operation]["actual_status"], "row_ids": state.jobs[operation]["row_ids"]}
                self._entry(state, "observations", kind="job_status", action=action, status="success", data=data, operation_id=operation, related_event_ids=[call_id])
            else:
                rows = deepcopy(list(state.published.values()) or state.products)
                if args.get("row_ids"):
                    rows = [row for row in rows if row["row_id"] in args["row_ids"]]
                data = {"published_row_ids": list(state.published), "rows": rows}
                self._entry(state, "observations", kind="query", action="prices", status="success", data=data, related_event_ids=[call_id])
            return {"status": "ok", **data}
        if action == "audit":
            if not state.published:
                raise ValueError("publication_required_before_audit")
            data = [{"row_id": row["row_id"], "margin_percent": float((Decimal(str(row["price"])) - Decimal(str(row["cost"])))
                     / Decimal(str(row["price"])) * 100)} for row in state.published.values()]
            threshold = args.get("threshold_percent", 0)
            for row in data:
                row["accepted"] = row["margin_percent"] >= threshold
            published = next(row for row in reversed(state.effects) if row["action"] == "publish" and row["status"] == "executed")
            self._entry(state, "observations", kind="audit", action=action, status="success", data={"rows": data, "threshold_percent": threshold},
                        operation_id=published["operation_id"], row_ids=list(state.published), related_event_ids=[call_id])
            return {"status": "ok", "rows": data}
        if action in {"inventory_update", "export", "price_update"}:
            return self._backend_effect(state, action, args, call_id)
        if action == "inventory_query":
            return self._inventory_query(state, args, call_id)
        if action == "validate_parameters":
            from jsonschema import Draft202012Validator
            schema = {"type": "object", "additionalProperties": False, "required": ["site", "margin_percent"],
                      "properties": {"site": {"enum": ["DE", "NL", "FR"]}, "margin_percent": {"type": "number", "minimum": 0, "exclusiveMaximum": 100}}}
            data = args.get("request", {})
            attempt = self._entry(state, "observations", kind="parameter_attempt", action="draft", status="attempted", data=data, operation_id=call_id)
            valid = not list(Draft202012Validator(schema).iter_errors(data))
            check = self._entry(state, "checks", kind="parameters", source="candidate", subject="draft", full=True, valid=valid,
                                attempt_id=attempt["evidence_id"], related_event_ids=[call_id])
            return {"status": "ok", "valid": valid, "evidence_id": check["evidence_id"]}
        raise ValueError("unsupported_business_action")

    def _source_fault(self, state, path):
        if path == "inputs/products.json" and self._fault("source_failure") and not state.fault_counts.get("source_failure"):
            state.fault_counts["source_failure"] = 1
            raise ValueError("source_temporarily_unavailable")

    def _write_preflight(self, state):
        if self._fault("generation_failure", "generation_failed", "source_unhealthy", "source_invalid", "all_products_invalid"):
            raise ValueError("source_unhealthy")

    def _corrupt_once(self, state):
        if not self._fault("corrupt_artifact") or state.fault_counts.get("corrupt_artifact"):
            return
        names = state.workspace.list("artifacts")
        if not names:
            return
        name = names[0]
        rows = read_artifact(state.workspace.read(name), Path(name).suffix.lstrip("."))
        if len(rows) >= 20:
            rows[16]["currency"], rows[19]["sku"] = "USD", ""
            state.workspace.write(name, serialize_rows(rows, Path(name).suffix.lstrip(".")))
            state.fault_counts["corrupt_artifact"] = 1

    def _backend_effect(self, state, action, args, call_id):
        ids = args.get("row_ids", [row["row_id"] for row in state.products])
        if not isinstance(ids, list) or not set(ids) <= {row["row_id"] for row in state.products}:
            raise ValueError("business_scope_invalid")
        if action == "export" and any(job_id not in state.observed_jobs for job_id in state.jobs):
            raise ValueError("operation_status_query_required")
        failed = []
        if action == "inventory_update" and self._fault("partial_inventory_failure") and not state.fault_counts.get(action):
            state.fault_counts[action] = 1
            failed = ids[-1:]
        succeeded = [item for item in ids if item not in failed]
        operation_id = "operation-" + uuid4().hex
        self._entry(state, "effects", action=action, status="executed", row_ids=succeeded, operation_id=operation_id,
                    source="synthetic_backend", related_event_ids=[call_id])
        if failed:
            failure = self._failure(state, action, "partial_failure", call_id, failed_row_ids=failed,
                                    succeeded_row_ids=succeeded, operation_id=operation_id)
            return {"status": "partial", "failed_row_ids": failed, "succeeded_row_ids": succeeded, "failure_id": failure["evidence_id"]}
        if action == "export" and self._fault("export_timeout") and not state.fault_counts.get(action):
            state.fault_counts[action] = 1
            state.jobs[operation_id] = {"status": "unknown", "actual_status": "completed", "row_ids": succeeded}
            failure = self._failure(state, action, "export_timeout", call_id, operation_id=operation_id, status="unknown")
            return {"status": "unknown", "error_type": "export_timeout", "operation_id": operation_id, "failure_id": failure["evidence_id"]}
        return {"status": "ok", "row_ids": succeeded, "operation_id": operation_id}

    def record_decision(self, session_id: str, *, action: str, related_event_ids: list[str] | None = None) -> None:
        state = self._session(session_id)
        self._entry(state, "observations", kind="decision", action=action, source="candidate", status="ok", related_event_ids=related_event_ids or [])

    def _inventory_query(self, state, args, call_id):
        ids = args.get("row_ids", [row["row_id"] for row in state.products])
        source = args.get("source", "primary")
        if source not in {"primary", "alternate"} or not set(ids) <= {row["row_id"] for row in state.products}:
            raise ValueError("inventory_request_invalid")
        prior = next((row for row in reversed(state.failures) if row.get("action") == "inventory_query"), None)
        if self._fault("source_failure") and source == "primary":
            failure = self._failure(state, "inventory_query", "primary_source_unavailable", call_id,
                                    failed_row_ids=ids, succeeded_row_ids=[], parameters=args)
            return {"status": "failed", "failure_id": failure["evidence_id"], "error_type": "primary_source_unavailable",
                    "failed_row_ids": ids, "available_sources": ["alternate"]}
        rows = [deepcopy(row) for row in state.products if row["row_id"] in ids]
        if self._fault("partial_inventory_failure") and not state.fault_counts.get("inventory_query"):
            state.fault_counts["inventory_query"] = 1
            failed = ids[-1:]
            succeeded = [item for item in ids if item not in failed]
            failure = self._failure(state, "inventory_query", "partial_inventory_failure", call_id,
                                    failed_row_ids=failed, succeeded_row_ids=succeeded, parameters=args)
            return {"status": "partial", "failure_id": failure["evidence_id"], "error_type": "partial_inventory_failure",
                    "failed_row_ids": failed, "succeeded_row_ids": succeeded, "rows": [row for row in rows if row["row_id"] in succeeded]}
        evidence = self._entry(state, "observations", kind="recovery" if prior else "query", action="inventory_query", status="success",
                               failure_id=prior["evidence_id"] if prior else None, row_ids=ids, parameters=args,
                               data={"rows": rows}, related_event_ids=[call_id])
        return {"status": "ok", "rows": rows, "row_ids": ids, "receipt_id": evidence["evidence_id"],
                "failure_id": prior["evidence_id"] if prior else None}

    def record_model_usage(self, session_id, usage, latency_ms):
        state = self._session(session_id)
        self._entry(state, "observations", kind="llm_usage", role="agent", data=usage, latency_ms=latency_ms, source="collector")

    def record_model_failure(self, session_id, model_call_id, *, error_type, latency_ms, provider_error_type=None):
        state = self._session(session_id)
        details = {"model_call_id": model_call_id, "error_type": error_type, "latency_ms": latency_ms}
        if provider_error_type is not None:
            details["provider_error_type"] = provider_error_type
        self._entry(state, "observations", kind="model_failure", role="agent", status="failed",
                    source="collector", data=details, related_event_ids=[model_call_id])

    def record_wait_interval(self, session_id, started_at, ended_at):
        state = self._session(session_id)
        self._entry(state, "observations", kind="wait_interval", source="collector",
                    data={"started_at": started_at.isoformat(), "ended_at": ended_at.isoformat()})

    def record_user_message(self, session_id: str, message: str, *, facts: dict | None = None) -> None:
        state = self._session(session_id)
        if state.pending:
            raise ValueError("start_while_pending")
        if state.finished:
            state.turn += 1
            state.finished, state.ended_at = False, None
        if facts:
            state.facts.update(_safe(facts))
        self._entry(state, "interactions", kind="user_message", source="user", message=message, values=facts or {})

    def record_prior_context(self, session_id, previous):
        state = self._session(session_id)
        self._discard_prior_context(state, {"company_id": previous.company_id,
            "snapshot_hash": digest(previous.model_dump_json()), "artifacts": previous.artifacts,
            "artifact_ids": [artifact["artifact_id"] for artifact in previous.artifacts],
            "approval_ids": [review["review_id"] for review in previous.reviews]})

    def _discard_prior_context(self, state, prior):
        old_company = prior["company_id"]
        if old_company == state.company_id:
            raise ValueError("prior_company_scope_invalid")
        artifact_ids = prior.get("artifact_ids", [artifact["artifact_id"] for artifact in prior.get("artifacts", [])])
        approvals = prior.get("approval_ids", [])
        state.initial_state["prior_context"] = {"company_id": old_company,
            "snapshot_hash": prior.get("snapshot_hash", digest(canonical_json(prior))),
            "artifact_ids": list(artifact_ids), "approval_ids": list(approvals), "retained_messages": 0,
            "artifact_count": len(artifact_ids), "authorization_count": len(approvals)}
        self._entry(state, "observations", kind="context_switch", action="company_switch", status="success",
                    source="collector", data={"from_company_id": old_company, "to_company_id": state.company_id,
                        "discarded_artifact_ids": list(artifact_ids), "invalidated_approval_ids": list(approvals),
                        "retained_messages": 0, "retained_authorizations": 0})

    def finish(self, session_id: str, content: str, usage: ResourceUsageV1 | dict | None = None) -> None:
        state = self._session(session_id)
        if state.pending:
            raise ValueError("finish_while_pending")
        safe_content = _safe(content)
        try:
            structured = json.loads(safe_content)
        except (ValueError, TypeError):
            structured = None
        state.report = {"format": "structured" if isinstance(structured, dict) else "prose", "content": safe_content}
        if usage is not None:
            state.usage = ResourceUsageV1.model_validate(usage)
        state.finished = True
        state.ended_at = self.clock()

    def collect_business_evidence(self, session_id: str) -> BusinessEvidenceBundleV1:
        state = self._session(session_id)
        omissions = list(state.omission_reasons)
        try:
            if state.workspace.list("artifacts"):
                artifact = self._capture_artifact(state, source="evaluator")
                if not any(row.get("source") == "evaluator" and _identity(row) == _identity(artifact) for row in state.checks):
                    self._check(state, "evaluator-final-read", source="evaluator")
        except (ValueError, OSError):
            omissions.append("artifact_capture_unavailable")
        ended = self.clock()
        row_ids = [row.get("row_id") for row in state.products]
        final = {"scope": {"company_id": state.company_id, "row_ids": row_ids}, "facts": deepcopy(state.facts),
                 "published": deepcopy(list(state.published.values())), "published_rows": deepcopy(list(state.published.values())),
                 "published_row_ids": list(state.published),
                 "active_context_artifact_ids": [state.current_artifact["artifact_id"]] if state.current_artifact else [],
                 "active_approval_ids": [review["review_id"] for review in state.reviews if review.get("decision") == "approved"
                     and review["review_id"] not in state.consumed_approvals and _identity(review) == _identity(state.current_artifact)],
                 "jobs": deepcopy(state.jobs), "pending": deepcopy(state.pending),
                 "journal": {"complete": True, "company_id": state.company_id, "row_ids": row_ids,
                             "started_at": state.started_at.isoformat(), "ended_at": ended.isoformat()}}
        return BusinessEvidenceBundleV1(run_id=session_id, project_id="business-sandbox", company_id=state.company_id,
            collector_id=self.COLLECTOR_ID, started_at=state.started_at, ended_at=ended, complete=state.finished and not state.pending,
            initial_state=_safe(state.initial_state), final_state=_safe(final), artifacts=deepcopy(state.artifacts),
            effects=deepcopy(state.effects), checks=deepcopy(state.checks), reviews=deepcopy(state.reviews),
            interactions=deepcopy(state.interactions), observations=deepcopy(state.observations), report=deepcopy(state.report),
            resource_usage=state.usage, omission_reasons=sorted(set(omissions)))

    def state(self, session_id: str) -> dict:
        state = self._session(session_id)
        return {"company_id": state.company_id, "facts": deepcopy(state.facts), "pending": deepcopy(state.pending),
                "published_row_ids": list(state.published), "artifact": deepcopy(state.current_artifact)}

    def reset(self, session_id: str) -> None:
        state = self.sessions.pop(session_id, None)
        if state:
            state.workspace.close()

    def close(self) -> None:
        for session_id in list(self.sessions):
            self.reset(session_id)
