"""Version 1.2 artifact metrics derived from content and linked event evidence."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from commerce_eval.contracts.models import MetricResultV1, MetricStatus
from commerce_eval.contracts.protocols import EvaluationContext
from commerce_eval.contracts.scenarios import ArtifactEvidenceV1, CapabilityBindingV1
from commerce_eval.scenarios.artifacts import DEFAULT_POLICY, read_artifact_evidence, select_review_sample, validate_artifact
from commerce_eval.scenarios.bindings import decode_arguments
from commerce_eval.scenarios.evidence import CALL_KINDS, latest_receipt, receipt_succeeded

from .base import FunctionalMetricEvaluator


METRIC_IDS = (
    "artifact_preflight_compliance", "artifact_defect_detection_recall",
    "artifact_sampling_compliance", "artifact_review_compliance", "artifact_execution_binding_pass",
)
IDENTITY = ("artifact_id", "version", "content_hash", "manifest_hash", "rule_version")


def _identity(data: dict) -> tuple:
    return tuple(data.get(key) for key in IDENTITY)


def _errors(errors: Any) -> set[tuple]:
    if not isinstance(errors,list) or not all(isinstance(error,dict) for error in errors):
        return set()
    return {(e.get("row_id"),e.get("field"),e.get("code")) for e in errors}


def _content(data: dict, policy: dict, required_ids: list[str] | None) -> tuple[list[dict], dict]:
    ArtifactEvidenceV1.model_validate(data)
    if data.get("available") is False or data.get("captured") is False or data.get("omission_reason"):
        raise ValueError("artifact_evidence_unavailable")
    rows = read_artifact_evidence(data)
    if data["rule_version"] != policy["rule_version"]:
        raise ValueError("rule_version_mismatch")
    if required_ids is not None and sorted(str(row.get("row_id")) for row in rows) != sorted(required_ids):
        raise ValueError("required_rows_missing_or_duplicated")
    return rows, validate_artifact(rows,policy)


def _audit(context: EvaluationContext) -> dict:
    requirements = context.case.artifact_requirements
    policy = {**DEFAULT_POLICY,**requirements.get("policy",{})}
    seed = str(requirements.get("seed","bank-v2"))
    events = sorted(context.trace.events,key=lambda event:event.sequence)
    created = [event for event in events if event.kind=="artifact.created"]
    bindings = {b.tool_id:b for b in (CapabilityBindingV1.model_validate(row) for row in context.case.capability_bindings)}
    actual_calls = {event.event_id:event for event in events if event.kind in CALL_KINDS}
    producer_caps = set(requirements.get("producer_capabilities",["artifact.prepare","artifact.revise","catalog.generate_listing","catalog.generate_alternative"]))
    producers = [call for call in actual_calls.values() if bindings.get(call.attributes.get("tool_id") or call.name) and bindings[call.attributes.get("tool_id") or call.name].capability_id in producer_caps]

    def operation(event, *, pending=False):
        call = actual_calls.get(event.attributes.get("tool_call_id"))
        if not call or call.sequence>=event.sequence or event.status.value!="ok":
            return None
        binding = bindings.get(call.attributes.get("tool_id") or call.name)
        if not binding:
            return None
        receipt = latest_receipt(events,call,binding,success=False)
        if not receipt or not (receipt_succeeded(*receipt) or pending and receipt[1].get("status")=="pending" and receipt[0].status.value=="ok"):
            return None
        return receipt

    outcomes: dict[str,list[float]] = {metric:[] for metric in METRIC_IDS}
    failures: list[dict] = []
    refs: list[str] = []
    checked_reviews: dict[str,tuple] = {}
    created_data: dict[tuple,dict] = {}

    def linked(kind: str, identity: tuple, start: int, end: int):
        return [event for event in events if event.kind==kind and start < event.sequence < end and _identity(event.attributes)==identity]

    if not created:
        return {"values":{metric:0.0 for metric in METRIC_IDS},"failures":[{"reason":"artifact_evidence_unavailable"}],"refs":[]}
    for index, creation in enumerate(created):
        data = creation.attributes
        identity = _identity(data)
        next_creation = next((event.sequence for event in created[index+1:] if event.attributes.get("artifact_id")==data.get("artifact_id")),10**12)
        refs.append(creation.event_id)
        try:
            rows, validation = _content(data,policy,requirements.get("expected_row_ids"))
            generation = operation(creation)
            if not generation or generation[0].sequence<=creation.sequence or not all(generation[1].get(key)==data[key] for key in IDENTITY):
                raise ValueError("generation_receipt_unavailable")
        except (ValueError,TypeError,KeyError,ValidationError,OverflowError):
            for metric in METRIC_IDS[:-1]:
                outcomes[metric].append(0.0)
            failures.append({"event_id":creation.event_id,"reason":"content_binding_or_format_unavailable"})
            continue
        created_data[identity] = {"creation":creation,"end":next_creation,"data":data,"validation":validation}
        checks = linked("artifact.check",identity,creation.sequence,next_creation)
        expected_errors = _errors(validation["errors"])
        complete_checks = []
        for check in checks:
            attrs = check.attributes
            try:
                check_rows, _ = _content(attrs,policy,requirements.get("expected_row_ids"))
                complete = bool(operation(check) and check.sequence>generation[0].sequence and check_rows==rows and attrs.get("checked_row_ids")==validation["checked_row_ids"])
            except (ValueError,TypeError,KeyError,ValidationError,OverflowError):
                complete = False
            if complete:
                complete_checks.append(check)
        preflight = bool(complete_checks)
        outcomes[METRIC_IDS[0]].append(float(preflight))
        detected = set().union(*(_errors(check.attributes.get("errors")) for check in complete_checks)) if complete_checks else set()
        recall = len(expected_errors & detected)/len(expected_errors) if expected_errors else float(preflight)
        outcomes[METRIC_IDS[1]].append(recall)
        samples = linked("artifact.sample",identity,creation.sequence,next_creation)
        expected_sample = select_review_sample(rows,validation["errors"],seed)
        good_samples = [sample for sample in samples if operation(sample) and sample.attributes.get("sample_row_ids")==expected_sample and str(sample.attributes.get("seed"))==seed and any(operation(check)[0].sequence<sample.sequence for check in complete_checks)]
        outcomes[METRIC_IDS[2]].append(float(bool(good_samples)))
        reviews = linked("artifact.review",identity,creation.sequence,next_creation)
        good_reviews = []
        for review in reviews:
            attrs = review.attributes
            review_id = attrs.get("review_id")
            expected_decision = "approved" if validation["valid"] else "rejected"
            responses = linked("interaction.response",identity,creation.sequence,review.sequence)
            response = next((r for r in responses if r.attributes.get("review_id")==review_id and r.attributes.get("decision")==expected_decision and r.attributes.get("response",{}).get("decision")==expected_decision),None)
            request = next((r for r in linked("interaction.request",identity,creation.sequence,review.sequence) if response and r.sequence<response.sequence and r.attributes.get("interaction_id")==response.attributes.get("interaction_id") and r.attributes.get("review_id")==review_id),None)
            review_operation = operation(review,pending=True)
            ordered = bool(request and response and response.status.value=="ok" and request.status.value=="ok" and review_operation
                           and review_operation[1].get("interaction_id")==request.attributes.get("interaction_id")
                           and review_operation[0].sequence<response.sequence
                           and any(operation(s)[0].sequence<request.sequence for s in good_samples))
            if review_id and attrs.get("decision")==expected_decision and ordered and attrs.get("sample_row_ids")==expected_sample:
                if review_id in checked_reviews:
                    failures.append({"event_id":review.event_id,"reason":"review_id_reused"})
                    continue
                good_reviews.append(review)
                checked_reviews[review_id] = (identity,review.sequence,expected_decision,next_creation)
        outcomes[METRIC_IDS[3]].append(float(bool(good_reviews) and len(good_reviews)==len(reviews)))
        for key, value in (("preflight",preflight),("defect_recall",recall==1),("sample",bool(good_samples)),("review",bool(good_reviews))):
            if not value:
                failures.append({"event_id":creation.event_id,"reason":key+"_incomplete"})
        refs.extend(event.event_id for event in checks+samples+reviews)

    bindings = {b.tool_id:b for b in (CapabilityBindingV1.model_validate(row) for row in context.case.capability_bindings)}
    consumer_caps = requirements.get("consumer_capabilities",["catalog.publish"])
    consumer_ids = set(requirements.get("consumer_tool_ids",[])) | {b.tool_id for b in bindings.values() if b.capability_id in consumer_caps}
    calls = [event for event in events if event.kind in CALL_KINDS and (event.attributes.get("tool_id") or event.name) in consumer_ids]
    consumptions = [event for event in events if event.kind=="artifact.consume"]
    consumed_calls: set[str] = set()
    for consume in consumptions:
        data = consume.attributes
        refs.append(consume.event_id)
        identity = _identity(data)
        review = checked_reviews.get(data.get("review_id"))
        call = next((c for c in calls if c.event_id==data.get("tool_call_id")),None)
        valid = False
        try:
            _, validation = _content(data,policy,requirements.get("expected_row_ids"))
            info = created_data.get(identity)
            valid = bool(validation["valid"] and info and review and review[0]==identity and review[2]=="approved" and call and review[1]<call.sequence<consume.sequence<review[3])
            if valid:
                binding = bindings.get(call.attributes.get("tool_id") or call.name)
                args = decode_arguments(binding,call.attributes.get("arguments",{})) if binding else call.attributes.get("arguments",{})
                valid = all(args.get(key)==data[key] for key in (*IDENTITY,"review_id"))
                receipt = latest_receipt(events,call,binding)
                receipt_ok = bool(receipt and receipt[0].sequence>consume.sequence and receipt[1].get("receipt_id")==data.get("receipt_id") and all(receipt[1].get(key)==data[key] for key in (*IDENTITY,"review_id")))
                intervening = any(info["creation"].sequence<producer.sequence<call.sequence for producer in producers)
                changed = any(event.kind in {"artifact.changed","company.changed"} and info["creation"].sequence<event.sequence<call.sequence for event in events)
                later_reviews = any(event.kind=="artifact.review" and review[1]<event.sequence<call.sequence for event in events)
                valid = valid and consume.status.value=="ok" and receipt_ok and not intervening and not changed and not later_reviews and call.event_id not in consumed_calls
                consumed_calls.add(call.event_id)
        except (ValueError,TypeError,KeyError,ValidationError,OverflowError):
            valid = False
        outcomes[METRIC_IDS[4]].append(float(valid))
        if not valid:
            failures.append({"event_id":consume.event_id,"reason":"execution_binding_mismatch"})
    if not consumptions:
        outcomes[METRIC_IDS[4]].append(float(not requirements.get("require_consumption",True) and not calls and bool(checked_reviews)))
    if any(call.event_id not in consumed_calls for call in calls):
        outcomes[METRIC_IDS[4]].append(0.0)
        failures.append({"reason":"consumer_call_without_bound_receipt"})
    if failures and any(f["reason"]=="content_binding_or_format_unavailable" for f in failures):
        outcomes[METRIC_IDS[4]].append(0.0)
    return {"values":{key:sum(values)/len(values) if values else 0.0 for key,values in outcomes.items()},"failures":failures,"refs":list(dict.fromkeys(refs))}


def _evaluate(context: EvaluationContext, metric_id: str) -> MetricResultV1:
    declared = bool(context.case.artifact_requirements) or any(g.metric_id==metric_id for g in context.case.gates)
    if not declared:
        return MetricResultV1(metric_id=metric_id,metric_version="1.2",group="artifacts",status=MetricStatus.NA,na_reason="artifact_requirements_not_declared")
    audit = _audit(context)
    value = audit["values"][metric_id]
    return MetricResultV1(metric_id=metric_id,metric_version="1.2",group="artifacts",status=MetricStatus.PASS if value==1 else MetricStatus.FAIL,value=value,reason_code="artifact_evidence_recomputed" if value==1 else "artifact_evidence_incomplete_or_invalid",evidence_refs=audit["refs"],details={"failures":audit["failures"]})


def artifact_preflight_compliance(context: EvaluationContext) -> MetricResultV1:
    return _evaluate(context,METRIC_IDS[0])


def artifact_defect_detection_recall(context: EvaluationContext) -> MetricResultV1:
    return _evaluate(context,METRIC_IDS[1])


def artifact_sampling_compliance(context: EvaluationContext) -> MetricResultV1:
    return _evaluate(context,METRIC_IDS[2])


def artifact_review_compliance(context: EvaluationContext) -> MetricResultV1:
    return _evaluate(context,METRIC_IDS[3])


def artifact_execution_binding_pass(context: EvaluationContext) -> MetricResultV1:
    return _evaluate(context,METRIC_IDS[4])


def artifact_evaluators() -> list[FunctionalMetricEvaluator]:
    functions = [artifact_preflight_compliance,artifact_defect_detection_recall,artifact_sampling_compliance,artifact_review_compliance,artifact_execution_binding_pass]
    return [FunctionalMetricEvaluator(function.__name__,"artifacts",function,metric_version="1.2",required_evidence=("artifact.created","artifact.check","artifact.sample","artifact.review","artifact.consume")) for function in functions]
