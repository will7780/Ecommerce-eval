"""Evaluator-owned environment bridge for the independent public-input policy."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone

from commerce_eval.contracts import (
    EvalCaseV1, PendingInteractionV1, TargetRunResponseV1, TraceEnvelopeV1, TraceEventV1,
)
from commerce_eval.core.evidence import snapshot_hash
from commerce_eval.demo_policy import CatalogPolicy, PolicyOutcome
from .base import candidate_case


@dataclass
class _PolicySession:
    environment: object
    policy: CatalogPolicy
    external_run_id: str
    case_id: str
    env_cursor: int = 0
    pending: PendingInteractionV1 | None = None
    terminal: bool = False
    evidence: list[str] = field(default_factory=list)


class ReferencePolicyTarget:
    """Only this trusted harness sees cases. The policy sees no evaluator contract."""

    def __init__(self, definition):
        self.definition = definition
        self._cases = {}
        self._sessions = {}
        self.max_steps = max(1, min(64, int(definition.config.get("max_steps", 24))))

    def bind_environment_cases(self, cases):
        self._cases = {}
        for raw in cases:
            case = EvalCaseV1.model_validate(raw).model_copy(deep=True)
            if not case.scenario_id or not case.scenario_data:
                raise ValueError("reference_policy_environment_required")
            if case.case_id in self._cases:
                raise ValueError("reference_policy_duplicate_case")
            self._cases[case.case_id] = case

    async def capabilities(self):
        return {
            "protocol_version": "1.1", "supported_protocol_versions": ["1.0", "1.1"],
            "operations": ["start", "resume", "reset"], "safe_for_eval": True,
            "actor": "reference_policy", "simulation": True, "llm_calls": 0,
        }

    def _public_tools(self, case):
        from commerce_eval.scenarios import build_tool_contracts

        contracts = {tool.tool_id: tool for tool in build_tool_contracts(case)}
        # Availability is the installed schema, never the case's forbidden set.
        return [{
            "capability_id": binding["capability_id"], "tool_id": binding["tool_id"],
            "input_schema": deepcopy(contracts[binding["tool_id"]].input_schema),
            "argument_mapping": deepcopy(binding.get("argument_mapping", {})),
            "unit_scale": deepcopy(binding.get("unit_scale", {})),
        } for binding in case.capability_bindings]

    async def start(self, request):
        from commerce_eval.scenarios import ScenarioEnvironment, project_candidate_input

        old = self._sessions.get(request.session_id)
        if old and old.pending:
            return self._failure(request, old, "start_while_pending")
        case = self._cases.get(request.case.case_id)
        if case is None or case.version != request.case.version:
            return self._failure(request, None, "policy_case_not_bound")
        public = project_candidate_input(candidate_case(request.case))
        policy = CatalogPolicy(public, self._public_tools(case), call_prefix=request.request_id, max_steps=self.max_steps)
        if old:
            old.environment.close()
        session = _PolicySession(ScenarioEnvironment(case), policy, request.request_id, case.case_id)
        self._sessions[request.session_id] = session
        events = [TraceEventV1(
            event_id=request.request_id + "-input", sequence=0, kind="policy.input",
            attributes={"messages": [{"role": "user", "content": public.message}],
                        "assets": public.assets, "tools": list(policy.tools.values()), "source": "reference_policy"},
        )]
        return self._advance(request, session, events)

    def _collect(self, request, session, events):
        rows = session.environment.events(request.session_id)
        new = rows[session.env_cursor:]
        session.env_cursor = len(rows)
        artifact = {}
        for row in new:
            payload = row.model_copy(deep=True)
            payload.sequence = len(events)
            if payload.kind.startswith("artifact."):
                data = payload.attributes
                artifact.update({key: data[key] for key in ("artifact_id", "version", "content_hash", "manifest_hash", "rule_version", "review_id") if data.get(key) is not None})
            if payload.kind in {"observation", "artifact.review", "interaction.response"}:
                session.evidence.append(payload.event_id)
            events.append(payload)
        return artifact

    def _pending(self, request, session, events, action):
        row = next((row for row in reversed(events) if row.kind == "interaction.request"), None)
        if row is None:
            raise ValueError("pending_request_evidence_missing")
        attrs = row.attributes
        kind = "artifact" if action.stage == "review" else "risk" if action.stage == "risk" else None
        pending = {
            "interaction_id": attrs["interaction_id"],
            "type": "confirmation" if kind else "clarification",
            "prompt": "Review the observed artifact." if kind == "artifact" else "Approve this operation?" if kind else "Supply the requested current inputs.",
            "confirmation_kind": kind,
            "required_fields": list(attrs.get("required_fields") or attrs.get("fields") or []),
        }
        publication = session.policy.publication() if kind else None
        if publication:
            pending.update(
                tool_call_id=publication.tool_call_id, parameter_snapshot_hash=snapshot_hash(publication.arguments),
                artifact_id=session.policy.artifact.get("artifact_id"),
                artifact_version=session.policy.artifact.get("version"),
                artifact_manifest_hash=session.policy.artifact.get("manifest_hash"),
            )
        session.pending = PendingInteractionV1.model_validate(pending)
        row.attributes.update({key: value for key, value in pending.items() if value is not None})
        return self._response(
            request, session, events,
            "awaiting_confirmation" if kind else "awaiting_input",
            {"task_completed": False, "reason_code": "explicit_response_required"},
        )

    def _advance(self, request, session, events):
        for _ in range(self.max_steps):
            action = session.policy.next_action()
            if isinstance(action, PolicyOutcome):
                session.terminal = True
                outcome = {"task_completed": action.outcome == "completed" and not action.failed,
                           "outcome": action.outcome, "reason_code": action.reason}
                events.append(TraceEventV1(
                    event_id=request.request_id + "-final", sequence=len(events), kind="final_answer",
                    attributes={"outcome": action.outcome, "reason_code": action.reason, "text": action.reason},
                    evidence_refs=session.evidence[-128:],
                ))
                if action.failed:
                    events.append(TraceEventV1(
                        event_id=request.request_id + "-error", sequence=len(events), kind="error", status="error",
                        attributes={"error_type": action.reason, "source": "reference_policy"},
                    ))
                return self._response(request, session, events, "failed" if action.failed else "completed", outcome)
            events.append(TraceEventV1(
                event_id=action.tool_call_id + "-decision", sequence=len(events), kind="model.decision",
                attributes={"tool_id": action.tool_id, "arguments": action.arguments, "stage": action.stage,
                            "action": action.stage, "simulated": True, "source": "reference_policy",
                            "decision_type": "deterministic_policy",
                            "observation_id": session.evidence[-1] if session.evidence else None},
                evidence_refs=session.evidence[-1:],
            ))
            receipt = session.environment.execute(request.session_id, {
                "tool_id": action.tool_id, "arguments": action.arguments, "tool_call_id": action.tool_call_id,
            })
            artifact = self._collect(request, session, events)
            if action.capability == "catalog.publish":
                for row in events:
                    if row.event_id == action.tool_call_id:
                        row.attributes.update(
                            artifact_id=session.policy.artifact.get("artifact_id"),
                            artifact_version=session.policy.artifact.get("version"),
                            artifact_manifest_hash=session.policy.artifact.get("manifest_hash"),
                        )
            observed_rows = next((row.attributes.get("rows") for row in reversed(events)
                                  if row.kind == "artifact.created" and row.attributes.get("tool_call_id") == action.tool_call_id), None)
            if isinstance(observed_rows, list):
                receipt = {**receipt, "rows": observed_rows}
            session.policy.observe(action, {**receipt, "artifact": artifact})
            if receipt.get("status") == "pending":
                return self._pending(request, session, events, action)
        session.terminal = True
        return self._failure(request, session, "policy_step_limit", events)

    async def resume(self, request):
        session = self._sessions.get(request.session_id)
        if session is None or session.pending is None:
            return self._failure(request, session, "response_without_pending")
        if request.external_run_id != session.external_run_id or request.interaction_id != session.pending.interaction_id:
            return self._failure(request, session, "pending_interaction_mismatch")
        events = []
        try:
            session.environment.respond(request.session_id, request.interaction_id, deepcopy(request.response))
            artifact = self._collect(request, session, events)
            session.policy.artifact.update(artifact)
            session.policy.accept_response(request.response)
        except ValueError:
            return self._failure(request, session, "interaction_response_mismatch", events)
        session.pending = None
        return self._advance(request, session, events)

    def _response(self, request, session, events, status, output):
        now = datetime.now(timezone.utc)
        trace = TraceEnvelopeV1(
            contract_version="1.1", trace_id=request.request_id,
            project_id=str(self.definition.config.get("project_id") or "reference-policy"),
            target_id=self.definition.target_id, target_version=self.definition.version,
            case_id=session.case_id if session else None, started_at=now, ended_at=now, status=status,
            input={"message": session.policy.public.message} if session else {},
            output=output, events=events,
            metadata={"actor": "reference_policy", "reference_fixture": False, "reference_actor": False,
                      "candidate_evaluation": True, "candidate_execution": True, "simulation": True,
                      "execution_purpose": "deterministic_policy_baseline", "event_scope": "delta",
                      "usage_scope": "delta", "production_agent": False, "llm_calls": 0},
            tags={"actor": "reference_policy", "execution": "simulated", "model": "none"},
            resource_usage={"agent_llm_calls": 0, "judge_llm_calls": 0, "agent_total_tokens": 0,
                            "tool_calls": sum(row.kind == "tool.call" for row in events),
                            "cost_status": "no_model_calls"},
        )
        return TargetRunResponseV1(
            contract_version="1.1", external_run_id=session.external_run_id if session else request.request_id,
            status=status, trace=trace,
            pending_interaction=session.pending if session and status.startswith("awaiting_") else None,
            error_type=output.get("error_type"),
        )

    def _failure(self, request, session, reason, events=None):
        events = list(events or [])
        events.append(TraceEventV1(
            event_id=request.request_id + "-error", sequence=len(events), kind="error", status="error",
            attributes={"error_type": "interaction_protocol_error" if "pending" in reason or "interaction" in reason else reason, "reason_code": reason},
        ))
        return self._response(request, session, events, "failed", {"task_completed": False, "error_type": reason})

    async def reset(self, session_id):
        session = self._sessions.pop(session_id, None)
        if session:
            session.environment.close()
