"""Scripted reference actor for offline protocol demonstrations, not a model."""

from __future__ import annotations

import base64
import json
import re
import sys
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

from commerce_eval.core.evidence import snapshot_hash


def _event(sequence, kind, name, attributes, status="ok", **extra):
    return {
        "contract_version": "1.1", "event_id": f"event-{sequence}",
        "sequence": sequence, "kind": kind, "name": name, "status": status,
        "attributes": {"simulated": True, **attributes}, **extra,
    }


def _decision(events, message):
    identifier = f"model-{len(events)}"
    events.append(_event(len(events), "model.input", "Public model input", {
        "model_call_id": identifier,
        "messages": [{"role": "user", "content": message}],
        "capture_source": "reference_actor", "completeness": "partial",
        "omitted_fields": ["system"], "simulated": True,
    }))
    events.append(_event(len(events), "model.call", "Scripted decision", {"round": len(events)}, event_id=identifier))


def _call(events, identifier, arguments, *, call_id=None, failed=False, **binding):
    call_id = call_id or f"call-{len(events)}"
    events.append(_event(len(events), "tool.call", identifier, {
        "tool_id": identifier, "arguments": arguments, **binding,
    }, event_id=call_id))
    events.append(_event(len(events), "tool.execute", identifier, {
        "tool_call_id": call_id, "execution_mode": "dry_run",
    }, "error" if failed else "ok", parent_event_id=call_id))
    receipt_id = f"receipt-{len(events)}"
    events.append(_event(len(events), "observation", "Simulated receipt", {
        "tool_call_id": call_id, "receipt_id": receipt_id,
        "status": "failed" if failed else "success",
        **({"error_type": "template_missing", "retryable": True} if failed else {}),
    }, "error" if failed else "ok", parent_event_id=call_id))
    return events[-1]["event_id"]


def _response(state, events, *, status="completed", pending=None, completed=True):
    now = datetime.now(timezone.utc).isoformat()
    return {
        "contract_version": "1.1", "external_run_id": state["external_run_id"],
        "status": status, "pending_interaction": pending, "error_type": None,
        "trace": {
            "contract_version": "1.1", "trace_id": f"trace_{uuid4().hex}",
            "project_id": "commerce-demo", "target_id": "fixture-agent", "target_version": "1.0.0",
            "case_id": state["case_id"], "started_at": now, "ended_at": now,
            "status": status, "input": state.get("input", {}),
            "output": {"task_completed": completed, "summary": "Scripted simulated reference execution."},
            "tags": {"source": "reference_actor", "execution": "simulated", "actor": "scripted"},
            "metadata": {"reference_actor": True, "scripted": True, "simulated": True, "live_side_effect": False, "runtime_path": "python_target"},
            "resource_usage": {
                "agent_llm_calls": 0, "judge_llm_calls": 0,
                "tool_calls": sum(row["kind"] == "tool.call" for row in events),
                "cost_status": "simulated_no_model_calls",
            },
            "events": events,
        },
    }


def _finish(state, events, refs, *, completed=True):
    events.append(_event(len(events), "final_answer", "Reference result", {
        "text": "Simulation completed." if completed else "Declined; publication was not executed.",
        "outcome": "completed" if completed else "blocked",
    }, evidence_refs=refs))
    return _response(state, events, completed=completed)


def _encode_state(state):
    return "reference:" + base64.urlsafe_b64encode(json.dumps(state).encode("utf-8")).decode("ascii")


def _start(payload: Mapping[str, Any]) -> dict[str, Any]:
    case = payload.get("case") if isinstance(payload.get("case"), Mapping) else {}
    public = case.get("input") if isinstance(case.get("input"), Mapping) else {}
    message = str(public.get("message") or "")
    market_match = re.search(r"\b([A-Z]{2})\b", message)
    market = public.get("market") or (market_match.group(1) if market_match else None)
    scene = public.get("scene_kind")
    if not scene:
        scene = "publish" if "publish" in message.lower() else "recover" if "template" in message.lower() else "listing"
    threshold = re.search(r"(-?\d+(?:\.\d+)?)\s*percent", message)
    state = {
        "case_id": str(case.get("case_id") or "demo-case"), "input": dict(public),
        "scene": scene, "market": market, "source": public.get("source", "fixture_catalog"),
        "threshold": float(threshold.group(1)) if threshold else None,
        "nonce": uuid4().hex,
    }
    # Empty input is the legacy demonstration's fixed, harmless fixture action.
    if not message and not any(public.get(key) for key in public if key not in {"message", "assets"}):
        state["market"] = "DE"
    state["external_run_id"] = _encode_state(state)
    events = []
    _decision(events, message)
    if not state["market"]:
        pending = {
            "interaction_id": "demo-market-question", "type": "clarification",
            "prompt": "Which two-letter market should be used?", "required_fields": ["market"],
        }
        events.append(_event(len(events), "interaction.request", "Market required", pending, "pending"))
        return _response(state, events, status="awaiting_input", pending=pending, completed=False)
    args = {"source": state["source"], "market": state["market"]}
    refs = []
    if scene == "recover":
        refs.append(_call(events, "catalog.generate_listing", {**args, "template": "primary"}, failed=True))
        _decision(events, "Observed fixture template_missing; use fallback.")
        args["template"] = "fallback"
    refs.append(_call(events, "catalog.generate_listing", args))
    if scene == "publish":
        return _publication_pending(state, events)
    return _finish(state, events, refs)


def _publication_binding(state):
    args = {"artifact_ref": "artifact://listing/demo-001", "market": state["market"]}
    return args, {
        "tool_call_id": "publication-call", "parameter_snapshot_hash": snapshot_hash(args),
        "artifact_id": "demo-001", "artifact_version": "1",
        "artifact_manifest_hash": snapshot_hash({"fixture": "demo-001", "version": "1"}),
    }


def _publication_pending(state, events):
    args, binding = _publication_binding(state)
    pending = {
        "interaction_id": "demo-publication-confirm", "type": "confirmation",
        "confirmation_kind": "risk", "choices": ["approve", "reject"],
        "prompt": "Approve the simulated publication step?", **binding,
    }
    _decision(events, "Publication requires an explicit decision.")
    events.append(_event(len(events), "interaction.request", "Publication confirmation", {
        **pending, "tool_id": "catalog.upload_listing", "arguments": args,
    }, "pending"))
    return _response(state, events, status="awaiting_confirmation", pending=pending, completed=False)


def _resume(payload: Mapping[str, Any]) -> dict[str, Any]:
    external = str(payload.get("external_run_id") or "")
    state = json.loads(base64.urlsafe_b64decode(external.removeprefix("reference:")))
    state["external_run_id"] = external
    response = payload.get("response") if isinstance(payload.get("response"), Mapping) else {}
    identifier = payload.get("interaction_id")
    events = [_event(0, "interaction.response", "Explicit user response", {
        **response, "interaction_id": identifier,
    })]
    if identifier == "demo-market-question":
        fields = response.get("fields", {})
        market = fields.get("market") or response.get("market") or response.get("answer") or response.get("value")
        if not isinstance(market, str) or not re.fullmatch(r"[A-Za-z]{2}", market):
            return _response(state, events, status="failed", completed=False)
        state["market"] = market.upper()
        state["external_run_id"] = _encode_state({key: value for key, value in state.items() if key != "external_run_id"})
        _decision(events, market)
        ref = _call(events, "catalog.generate_listing", {"source": state["source"], "market": state["market"]})
        if state["scene"] == "publish":
            return _publication_pending(state, events)
        return _finish(state, events, [ref])
    decision = response.get("decision", response.get("answer"))
    if identifier != "demo-publication-confirm" or decision not in {"approve", "reject"}:
        return _response(state, events, status="failed", completed=False)
    if decision == "reject":
        return _finish(state, events, [], completed=False)
    args, binding = _publication_binding(state)
    _decision(events, "approve")
    refs = [_call(events, "catalog.upload_listing", args, call_id="publication-call", **binding)]
    if state["threshold"] is not None:
        _decision(events, "Observe simulated publication receipt.")
        refs.append(_call(events, "pricing.audit_margin", {
            "artifact_ref": args["artifact_ref"], "threshold_percent": state["threshold"],
        }))
    return _finish(state, events, refs)


def run_bank_fixture(case, *, mutant=None, session_id="reference"):
    """Static fixture validation only; never used to score a candidate."""
    from commerce_eval.scenarios import run_reference

    return run_reference(case, mutant=mutant, session_id=session_id)


class ReferenceFixtureTarget:
    """Static fixture validator, excluded from candidate evaluation; never an HTTP/Python candidate adapter."""

    def __init__(self, definition):
        self.definition = definition
        self._cases = {}

    def bind_fixture_cases(self, cases):
        from commerce_eval.contracts import EvalCaseV1

        self._cases = {}
        for raw in cases:
            case = EvalCaseV1.model_validate(raw).model_copy(deep=True)
            if not case.scenario_id:
                raise ValueError("reference_fixture_requires_scenario")
            if case.case_id in self._cases:
                raise ValueError("reference_fixture_duplicate_case")
            self._cases[case.case_id] = case

    async def capabilities(self):
        return {
            "protocol_version": "1.1", "supported_protocol_versions": ["1.0", "1.1"],
            "operations": ["start", "reset"], "actor": "reference_fixture",
            "scripted": True, "simulated": True, "candidate_evaluation": False,
        }

    async def start(self, request):
        from commerce_eval.contracts import TargetRunResponseV1
        from commerce_eval.targets.base import failed_target_response

        case = self._cases.get(request.case.case_id)
        if case is None or case.version != request.case.version:
            return failed_target_response(
                request_id=request.request_id, project_id="reference",
                target=self.definition, error_type="reference_case_not_bound",
            )
        trace = run_bank_fixture(case.model_copy(deep=True), session_id=request.session_id)
        trace = trace.model_copy(update={
            "trace_id": request.request_id,
            "target_id": self.definition.target_id, "target_version": self.definition.version,
            "tags": {**trace.tags, "actor": "reference_fixture", "execution": "simulated"},
            "metadata": {**trace.metadata, "fixture_trace_id": trace.trace_id, "reference_actor": False, "reference_fixture": True, "scripted": True, "simulated": True, "candidate_evaluation": False, "actor": "reference_fixture"},
        })
        return TargetRunResponseV1(
            contract_version="1.1", external_run_id=request.request_id, status=trace.status, trace=trace,
        )

    async def resume(self, request):
        from commerce_eval.targets.base import failed_target_response

        return failed_target_response(
            request_id=request.request_id, project_id="reference",
            target=self.definition, error_type="reference_fixture_resume_not_supported",
        )

    async def reset(self, session_id):
        return None


def main() -> int:
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    operation = request.get("operation")
    payload = request.get("payload") if isinstance(request.get("payload"), Mapping) else {}
    if operation == "reset":
        return 0
    result = _resume(payload) if operation == "resume" else _start(payload)
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
