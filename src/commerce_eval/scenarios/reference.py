"""Evaluator-only conformance fixtures and mutants; never a scored candidate."""

from __future__ import annotations

from copy import deepcopy

from commerce_eval.contracts.models import EvalCaseV1, TraceEnvelopeV1, TraceEventV1
from commerce_eval.contracts.scenarios import CapabilityBindingV1

from .bindings import encode_arguments
from .behavior import scenario_behavior_compliance, scenario_evaluators
from .tool_contracts import build_tool_contracts
from .environment import ScenarioEnvironment


def reference_steps(case: EvalCaseV1, mutant: str | None = None) -> list[dict]:
    references = case.scenario_data["references"]
    steps = deepcopy(references["positive"])
    if mutant is None:
        return steps
    mutation = next((m for m in references["mutants"] if m["name"]==mutant),None)
    if mutation is None:
        raise KeyError(mutant)
    index = mutation["index"]
    if mutation["operation"]=="remove":
        steps.pop(index)
    elif mutation["operation"]=="insert":
        for _ in range(mutation.get("count",1)):
            steps.insert(index,deepcopy(mutation["step"]))
    elif mutation["operation"]=="arguments":
        steps[index]["arguments"].update(deepcopy(mutation["arguments"]))
    elif mutation["operation"] in {"resource","resume"}:
        pass
    else:
        raise ValueError("reference_mutation_unsupported")
    return steps


def run_reference(case: EvalCaseV1, mutant: str | None = None, *, session_id: str = "reference") -> TraceEnvelopeV1:
    """Execute pinned fixture steps for conformance testing, not candidate scoring."""
    bindings = {b.capability_id:b for b in (CapabilityBindingV1.model_validate(row) for row in case.capability_bindings)}
    mutation=next((m for m in case.scenario_data["references"]["mutants"] if m["name"]==mutant),None)
    with ScenarioEnvironment(case) as environment:
        for index, action in enumerate(reference_steps(case,mutant)):
            state=environment.state(session_id)
            scripts=case.scenario_data["interaction_script"]
            if state["script_index"]<len(scripts) and scripts[state["script_index"]].get("type")=="user_message":
                try:
                    environment.deliver_user_message(session_id,scripts[state["script_index"]]["content"])
                except ValueError:
                    pass
            prior=environment.events(session_id)
            if prior and prior[-1].kind=="observation" and prior[-1].status.value=="error" and action["capability"]!="report.finish":
                environment.record_decision(session_id,prior[-1].event_id,"Use observed feedback for "+action["capability"])
            binding = bindings[action["capability"]]
            arguments = deepcopy(action["arguments"])
            if action["capability"] in {"catalog.publish","pricing.audit_margin"}:
                arguments = {**environment.state(session_id)["artifact_binding"],**arguments}
            receipt = environment.execute(session_id,{"tool_call_id":f"call-{index}","tool_id":binding.tool_id,"arguments":encode_arguments(binding,arguments)})
            if receipt.get("status")=="pending":
                state = environment.state(session_id)
                scripts = case.scenario_data["interaction_script"]
                if state["script_index"]<len(scripts):
                    try:
                        environment.respond(session_id,receipt["interaction_id"],mutation["response"] if mutation and mutation["operation"]=="resume" and index==mutation["index"] else scripts[state["script_index"]]["response"])
                    except ValueError:
                        pass
        state = environment.state(session_id)
        events=environment.events(session_id)
        usage={"agent_llm_calls":0,"judge_llm_calls":0,"tool_calls":len(reference_steps(case,mutant)),"estimated_cost":0.0,"currency":"EUR"}
        measured=case.scenario_data["environment"].get("resource_fixture")
        if measured:
            events.append(TraceEventV1(event_id="resource-measurement",sequence=len(events),kind="resource.usage",attributes={"source":"synthetic_clock_and_usage_fixture",**measured}))
            usage.update(measured)
        if mutant:
            mutation=next(m for m in case.scenario_data["references"]["mutants"] if m["name"]==mutant)
            if mutation["operation"]=="resource":
                usage.update(mutation["values"])
        return TraceEnvelopeV1(
            trace_id=f"reference-{case.scenario_id}-{mutant or 'positive'}",project_id="public-bank",target_id="reference_actor",target_version="0.2.0",case_id=case.case_id,
            input={"message":case.input.get("message","")},output=state["final"],events=events,
            metadata={"actor":"reference_actor","reference_actor":True,"synthetic":True,"mutation":mutant,"scenario_id":case.scenario_id,"scripted":True,"execution_purpose":"conformance_fixture","candidate_execution":False},
            resource_usage=usage,
        )
