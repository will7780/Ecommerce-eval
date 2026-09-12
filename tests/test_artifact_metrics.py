from __future__ import annotations

from copy import deepcopy

import pytest

from commerce_eval.contracts.models import EvalCaseV1, TraceEnvelopeV1
from commerce_eval.contracts.scenarios import ArtifactEvidenceV1
from commerce_eval.core.engine import EvaluationEngine
from commerce_eval.packs.artifacts import METRIC_IDS, artifact_evaluators
from commerce_eval.scenarios import compile_scenario, get_scenario_template, product_rows, run_reference, select_review_sample, validate_artifact
from commerce_eval.scenarios.artifacts import DEFAULT_POLICY, artifact_evidence, canonical_json, digest, read_artifact, serialize_rows


ENGINE=EvaluationEngine(artifact_evaluators())


def fixture(code="A01"):
    case=compile_scenario(get_scenario_template(code))
    case.gates=[gate for gate in case.gates if gate.metric_id in METRIC_IDS]
    return case,run_reference(case)


def metrics(case,trace):
    return {m.metric_id:m for m in ENGINE.evaluate(case,trace).metric_results}


@pytest.mark.parametrize("code",["A01","A02","A03","A04","S01"])
def test_reference_artifact_events_roundtrip_and_pass(code):
    case,trace=fixture(code)
    for event in trace.events:
        if event.kind.startswith("artifact."):
            evidence=ArtifactEvidenceV1.model_validate(event.attributes)
            assert ArtifactEvidenceV1.model_validate_json(evidence.model_dump_json())==evidence
    result=ENGINE.evaluate(case,trace)
    assert result.overall_pass,result
    assert all(m.metric_version=="1.2" and m.evidence_refs for m in result.metric_results)


@pytest.mark.parametrize("format",["json","csv"])
def test_read_and_validate_all_twenty_rows_and_sample_all_defects(format):
    rows=read_artifact(serialize_rows(product_rows("corrupt"),format),format)
    checked=validate_artifact(rows,DEFAULT_POLICY)
    assert checked["available"] and not checked["valid"]
    assert checked["checked_row_ids"]==[f"row{i:02}" for i in range(1,21)]
    assert {(e["row_id"],e["field"],e["code"]) for e in checked["errors"]}=={("row17","currency","currency"),("row20","sku","required")}
    sample=select_review_sample(rows,checked["errors"],"bank-v2")
    assert len(sample)==7 and {"row17","row20"}<=set(sample)
    assert len(set(sample)-{"row17","row20"})==5
    assert sample==select_review_sample(list(reversed(rows)),checked["errors"],"bank-v2")
    assert sample==select_review_sample(rows,checked["errors"],"bank-v2")
    assert sample!=select_review_sample(rows,checked["errors"],"another-seed")


def test_row_required_types_unique_positive_and_currency_independently_computed():
    rows=product_rows()
    rows[1]["sku"]=rows[0]["sku"]
    rows[2]["price"]=-3
    rows[3]["price"]="9.5"
    rows[4]["title"]=""
    rows[5]["currency"]="USD"
    rows[6]["price"]=True
    rows[7]["price"]=float("inf")
    checked=validate_artifact(rows)
    errors={(e["row_id"],e["field"],e["code"]) for e in checked["errors"]}
    assert {("row01","sku","duplicate"),("row02","sku","duplicate"),("row03","price","positive"),("row04","price","type"),("row05","title","required"),("row06","currency","currency"),("row07","price","type"),("row08","price","type")}<=errors
    assert len(checked["checked_row_ids"])==20
    assert not validate_artifact(None)["available"]
    assert not validate_artifact([])["valid"]
    assert len(select_review_sample(product_rows()[:3],[],1))==3


@pytest.mark.parametrize("kind,metric",[("artifact.created",METRIC_IDS[0]),("artifact.check",METRIC_IDS[0]),("artifact.sample",METRIC_IDS[2]),("artifact.review",METRIC_IDS[3]),("artifact.consume",METRIC_IDS[4]),("interaction.response",METRIC_IDS[3]),("interaction.request",METRIC_IDS[3]),("observation",METRIC_IDS[4])])
def test_missing_mandatory_evidence_fails_gate(kind,metric):
    case,trace=fixture()
    trace.events=[e for e in trace.events if e.kind!=kind]
    result=ENGINE.evaluate(case,trace)
    assert not result.overall_pass
    assert metrics(case,trace)[metric].value<1


def test_recompute_defect_recall_instead_of_trusting_success_flags():
    case,trace=fixture("A02")
    check=next(e for e in trace.events if e.kind=="artifact.check")
    check.attributes.update(valid=True,available=True,errors=[check.attributes["errors"][0]])
    values=metrics(case,trace)
    assert values[METRIC_IDS[0]].value==1
    assert values[METRIC_IDS[1]].value==0.5
    check.attributes["errors"]=[]
    assert metrics(case,trace)[METRIC_IDS[1]].value==0


def test_five_row_check_cannot_substitute_for_full_validation():
    case,trace=fixture("A02")
    check=next(e for e in trace.events if e.kind=="artifact.check")
    check.attributes["checked_row_ids"]=check.attributes["checked_row_ids"][:5]
    values=metrics(case,trace)
    assert values[METRIC_IDS[0]].value==0
    assert values[METRIC_IDS[1]].value==0
    assert values[METRIC_IDS[2]].value==0


@pytest.mark.parametrize("change",["missing_defect","wrong_seed","duplicate_normal","only_defects"])
def test_sampling_requires_five_deterministic_normals_and_all_errors(change):
    case,trace=fixture("A02")
    sample=next(e for e in trace.events if e.kind=="artifact.sample")
    if change=="missing_defect":
        sample.attributes["sample_row_ids"].remove("row20")
    elif change=="wrong_seed":
        sample.attributes["seed"]="different"
    elif change=="duplicate_normal":
        sample.attributes["sample_row_ids"][1]=sample.attributes["sample_row_ids"][0]
    else:
        sample.attributes["sample_row_ids"]=["row17","row20"]
    assert metrics(case,trace)[METRIC_IDS[2]].value==0


@pytest.mark.parametrize("field",["artifact_id","version","content_hash","manifest_hash","rule_version","review_id","tool_call_id"])
def test_every_execution_binding_component_is_enforced(field):
    case,trace=fixture()
    consume=next(e for e in trace.events if e.kind=="artifact.consume")
    consume.attributes[field]="different"
    assert metrics(case,trace)[METRIC_IDS[4]].value==0


@pytest.mark.parametrize("field",["artifact_id","version","content_hash","manifest_hash","rule_version","review_id"])
def test_actual_consuming_call_must_match_frozen_binding(field):
    case,trace=fixture()
    call=next(e for e in trace.events if e.kind=="tool.call" and e.name=="sandbox.catalog.publish")
    call.attributes["arguments"][field]="tampered"
    assert metrics(case,trace)[METRIC_IDS[4]].value==0


def test_revision_reuse_cannot_borrow_a_previous_approval():
    case,trace=fixture("A03")
    consume=next(e for e in trace.events if e.kind=="artifact.consume")
    previous=next(e for e in trace.events if e.kind=="artifact.review")
    consume.attributes["review_id"]=previous.attributes["review_id"]
    assert metrics(case,trace)[METRIC_IDS[4]].value==0


def test_successful_review_flags_do_not_override_defective_rows():
    case,trace=fixture("A02")
    for event in trace.events:
        if event.kind in {"artifact.review","interaction.response"}:
            event.attributes["decision"]="approved"
            if "response" in event.attributes:
                event.attributes["response"]["decision"]="approved"
    assert metrics(case,trace)[METRIC_IDS[3]].value==0


@pytest.mark.parametrize("format",["xlsx","unknown","html"])
def test_unknown_formats_are_unavailable_and_fail_mandatory_gates(format):
    case,trace=fixture()
    for event in trace.events:
        if event.kind.startswith("artifact."):
            event.attributes.update(format=format,available=True,valid=True)
    result=ENGINE.evaluate(case,trace)
    assert not result.overall_pass
    assert all(metric.status.value=="fail" and metric.value==0 for metric in result.metric_results)
    with pytest.raises(ValueError,match="unavailable"):
        read_artifact("unreadable",format)


def test_unavailable_interactive_review_and_stale_policy_cannot_pass():
    case,trace=fixture()
    review=next(e for e in trace.events if e.kind=="artifact.review")
    review.attributes.update(decision="unavailable",available=False,omission_reason="interactive_runtime_unavailable")
    assert metrics(case,trace)[METRIC_IDS[3]].value==0
    case.artifact_requirements["policy"]["rule_version"]="catalog-policy-3"
    assert all(metric.value==0 for metric in metrics(case,trace).values())


def test_truncated_creation_cannot_hide_tail_defects_with_new_hashes():
    case,trace=fixture("A02")
    replacement=artifact_evidence(product_rows()[:5],format="csv")
    for event in trace.events:
        if event.kind.startswith("artifact."):
            event.attributes.update(replacement)
    assert metrics(case,trace)[METRIC_IDS[0]].value==0


def test_manifest_rows_and_content_are_recomputed_not_flags():
    case,trace=fixture()
    created=next(e for e in trace.events if e.kind=="artifact.created")
    created.attributes["manifest"][0]["size"]+=1
    created.attributes["manifest_hash"]=digest(canonical_json(created.attributes["manifest"]))
    assert metrics(case,trace)[METRIC_IDS[0]].value==0


def test_non_artifact_cases_are_na_but_explicit_missing_gate_fails():
    case=EvalCaseV1(case_id="none",name="No artifact")
    trace=TraceEnvelopeV1(trace_id="none",project_id="synthetic",target_id="reference_actor",target_version="1")
    assert all(m.status.value=="na" for m in metrics(case,trace).values())
    data=case.model_dump()
    data["gates"]=[{"metric_id":METRIC_IDS[0],"operator":"equals","expected":1.0}]
    case=EvalCaseV1.model_validate(data)
    assert not ENGINE.evaluate(case,trace).overall_pass

@pytest.mark.parametrize("capability,metric",[("artifact.prepare",METRIC_IDS[0]),("artifact.check",METRIC_IDS[0]),("artifact.sample",METRIC_IDS[2]),("artifact.review",METRIC_IDS[3]),("catalog.publish",METRIC_IDS[4])])
def test_artifact_operations_require_linked_successful_receipts(capability,metric):
    case,trace=fixture()
    ids={event.event_id for event in trace.events if event.kind=="tool.call" and event.name=="sandbox."+capability}
    trace.events=[event for event in trace.events if not (event.kind=="observation" and event.attributes.get("tool_call_id") in ids)]
    assert metrics(case,trace)[metric].value==0


@pytest.mark.parametrize("kind",["artifact.created","artifact.check","artifact.sample","artifact.review","artifact.consume"])
def test_error_status_cannot_be_overridden_by_successful_artifact_flags(kind):
    from commerce_eval.contracts.models import EventStatus
    case,trace=fixture()
    event=next(event for event in trace.events if event.kind==kind)
    event.status=EventStatus.ERROR
    assert not ENGINE.evaluate(case,trace).overall_pass


def test_failed_latest_generation_invalidates_old_review_even_with_forged_publish_receipt():
    from commerce_eval.contracts.models import TraceEventV1
    case,trace=fixture()
    publish=next(event for event in trace.events if event.kind=="tool.call" and event.name=="sandbox.catalog.publish")
    sequence=publish.sequence
    for event in trace.events:
        if event.sequence>=sequence:
            event.sequence+=2
    trace.events.extend([
        TraceEventV1(event_id="failed-regeneration",sequence=sequence,kind="tool.call",name="sandbox.artifact.prepare",attributes={"tool_id":"sandbox.artifact.prepare","arguments":{}}),
        TraceEventV1(event_id="failed-regeneration-receipt",sequence=sequence+1,kind="observation",status="error",attributes={"tool_call_id":"failed-regeneration","result":{"status":"error","error_type":"generation_failed","receipt_id":"failed-generation"}}),
    ])
    assert metrics(case,trace)[METRIC_IDS[4]].value==0


def test_actual_failed_regeneration_cannot_publish_previously_approved_bytes(tmp_path):
    from commerce_eval.scenarios import ScenarioEnvironment
    case=compile_scenario(get_scenario_template("A01"))
    with ScenarioEnvironment(case,root=tmp_path) as environment:
        for cap,args in [("artifact.prepare",{}),("artifact.check",{}),("artifact.sample",{"seed":"bank-v2"}),("artifact.review",{})]:
            receipt=environment.execute("one",{"tool_id":"sandbox."+cap,"arguments":args})
            if receipt["status"]=="pending":
                environment.respond("one",receipt["interaction_id"],{"decision":"approved"})
        approved=environment.state("one")["artifact_binding"]
        environment.config["generation_failure"]=True
        failed=environment.execute("one",{"tool_id":"sandbox.artifact.prepare","arguments":{}})
        assert failed["error_type"]=="generation_failed"
        result=environment.execute("one",{"tool_id":"sandbox.catalog.publish","arguments":approved})
        assert result["error_type"]=="latest_generation_not_successful"
        assert not environment.state("one")["published"]
        assert not any(event.kind=="artifact.consume" for event in environment.events("one"))


@pytest.mark.parametrize("mode",["add","remove"])
def test_real_directory_member_changes_fail_integrity_before_consumption(mode,tmp_path):
    from commerce_eval.scenarios import ScenarioEnvironment
    case=compile_scenario(get_scenario_template("A01"))
    with ScenarioEnvironment(case,root=tmp_path) as environment:
        for cap,args in [("artifact.prepare",{}),("artifact.check",{}),("artifact.sample",{"seed":"bank-v2"}),("artifact.review",{})]:
            receipt=environment.execute("one",{"tool_id":"sandbox."+cap,"arguments":args})
            if receipt["status"]=="pending":
                environment.respond("one",receipt["interaction_id"],{"decision":"approved"})
        binding=environment.state("one")["artifact_binding"]
        path=environment.materialized_files("one")[0]
        if mode=="add":
            path.with_name("additional.csv").write_text("row_id,sku\n",encoding="utf-8")
        else:
            path.unlink()
        result=environment.execute("one",{"tool_id":"sandbox.catalog.publish","arguments":binding})
        assert result["error_type"]=="artifact_manifest_changed"
        assert not environment.state("one")["published"]
        assert not any(event.kind=="artifact.consume" for event in environment.events("one"))


def test_changed_event_cannot_be_hidden_behind_old_valid_receipt():
    from commerce_eval.contracts.models import TraceEventV1
    case,trace=fixture()
    call=next(event for event in trace.events if event.kind=="tool.call" and event.name=="sandbox.catalog.publish")
    sequence=call.sequence
    for event in trace.events:
        if event.sequence>=sequence:
            event.sequence+=1
    trace.events.append(TraceEventV1(event_id="changed",sequence=sequence,kind="artifact.changed",attributes={"source":"directory_member_added"}))
    assert metrics(case,trace)[METRIC_IDS[4]].value==0


def test_generation_receipt_error_status_beats_embedded_ok():
    from commerce_eval.contracts.models import EventStatus
    case,trace=fixture()
    receipt=next(event for event in trace.events if event.kind=="observation")
    receipt.status=EventStatus.ERROR
    assert all(value.value==0 for value in metrics(case,trace).values())

def with_artifact_payload(trace,payload):
    from commerce_eval.packs.artifacts import IDENTITY
    for event in trace.events:
        if event.kind.startswith("artifact."):
            for key in ("content","files"):
                event.attributes.pop(key,None)
            event.attributes.update(deepcopy(payload))
        elif event.kind in {"interaction.request","interaction.response"} and "artifact_id" in event.attributes:
            event.attributes.update({key:payload[key] for key in IDENTITY})
        elif event.kind=="observation":
            result=event.attributes.get("result",{})
            if "artifact_id" in result:
                result.update({key:payload[key] for key in IDENTITY})
        elif event.kind=="tool.call" and event.name=="sandbox.catalog.publish":
            event.attributes["arguments"].update({key:payload[key] for key in IDENTITY})
    return trace


def bundle_payload(rows=None):
    from commerce_eval.scenarios.artifacts import directory_artifact_evidence
    rows=product_rows() if rows is None else rows
    return directory_artifact_evidence([
        {"name":"part-a.json","format":"json","content":serialize_rows(rows[:10],"json")},
        {"name":"part-b.csv","format":"csv","content":serialize_rows(rows[10:],"csv")},
    ])


@pytest.mark.parametrize("name",["merchant-preview.json","review copy.data","opaque-feed"])
def test_neutral_single_file_names_pass_all_five_metrics(name):
    case,trace=fixture()
    payload=artifact_evidence(product_rows())
    payload["manifest"][0]["name"]=name
    payload["manifest_hash"]=digest(canonical_json(payload["manifest"]))
    values=metrics(case,with_artifact_payload(trace,payload))
    assert all(metric.value==1 for metric in values.values()),values


@pytest.mark.parametrize("code",["A01","A02"])
def test_complete_json_csv_directory_passes_all_five_metrics(code):
    from commerce_eval.scenarios.artifacts import read_artifact_evidence
    case,trace=fixture(code)
    payload=bundle_payload(product_rows("corrupt" if code=="A02" else "clean"))
    assert len(payload["files"])==2 and len(read_artifact_evidence(payload))==20
    model=ArtifactEvidenceV1.model_validate(payload)
    assert ArtifactEvidenceV1.model_validate_json(model.model_dump_json())==model
    values=metrics(case,with_artifact_payload(trace,payload))
    assert all(metric.value==1 for metric in values.values()),values


@pytest.mark.parametrize("change",["add","remove","replace","duplicate","member_hash","member_size","manifest_hash","bundle_hash","missing_bytes","unknown_format","unreadable"])
def test_incomplete_or_tampered_bundle_never_passes_required_metrics(change):
    case,trace=fixture()
    payload=bundle_payload()
    if change=="add":
        payload["files"].append({"name":"extra.json","format":"json","content":"[]","content_hash":digest("[]"),"size":2})
    elif change=="remove":
        payload["files"].pop()
    elif change=="replace":
        payload["files"][0]["content"]="[]"
    elif change=="duplicate":
        payload["files"].append(deepcopy(payload["files"][0]))
    elif change=="member_hash":
        payload["files"][0]["content_hash"]="0"*64
    elif change=="member_size":
        payload["files"][0]["size"]+=1
    elif change=="manifest_hash":
        payload["manifest_hash"]="0"*64
    elif change=="bundle_hash":
        payload["content_hash"]="0"*64
    elif change=="missing_bytes":
        payload["files"][0].pop("content")
    elif change=="unknown_format":
        payload["files"][0]["format"]="xlsx"
    else:
        content="not JSON"
        payload["files"][0].update(content=content,content_hash=digest(content),size=len(content))
    values=metrics(case,with_artifact_payload(trace,payload))
    assert all(metric.status.value=="fail" and metric.value==0 for metric in values.values()),values


@pytest.mark.parametrize("change",["add","remove","replace"])
def test_recomputed_whole_bundle_change_cannot_reuse_prior_approval(change):
    from commerce_eval.scenarios.artifacts import directory_artifact_evidence
    case,trace=fixture()
    original=bundle_payload()
    with_artifact_payload(trace,original)
    files=[{key:member[key] for key in ("name","format","content")} for member in original["files"]]
    if change=="add":
        files.append({"name":"added.json","format":"json","content":"[]"})
    elif change=="remove":
        files.pop()
    else:
        rows=read_artifact(files[0]["content"],"json")
        rows[0]["title"]="Changed after approval"
        files[0]["content"]=serialize_rows(rows,"json")
    changed=directory_artifact_evidence(files)
    assert changed["content_hash"]!=original["content_hash"]
    assert changed["manifest_hash"]!=original["manifest_hash"]
    consume=next(event for event in trace.events if event.kind=="artifact.consume")
    consume.attributes.update(changed)
    assert metrics(case,trace)[METRIC_IDS[4]].value==0


@pytest.mark.parametrize("name",["../outside.json","folder/file.json","C:/outside.json","C:\\outside.json","part-a.json/..","NUL","trailing."])
def test_manifest_names_never_resolve_host_paths(name):
    from commerce_eval.scenarios.artifacts import read_artifact_evidence
    payload=artifact_evidence(product_rows())
    payload["manifest"][0]["name"]=name
    payload["manifest_hash"]=digest(canonical_json(payload["manifest"]))
    with pytest.raises(ValueError,match="name_invalid"):
        read_artifact_evidence(payload)


def test_bundle_order_is_canonical_and_cross_member_duplicates_are_checked():
    from commerce_eval.scenarios.artifacts import directory_artifact_evidence, read_artifact_evidence
    payload=bundle_payload()
    reversed_members=[{key:member[key] for key in ("name","format","content")} for member in reversed(payload["files"])]
    assert directory_artifact_evidence(reversed_members)==payload
    rows=product_rows()
    rows[10]["sku"]=rows[0]["sku"]
    duplicate=bundle_payload(rows)
    errors=validate_artifact(read_artifact_evidence(duplicate))["errors"]
    assert {("row01","sku","duplicate"),("row11","sku","duplicate")}<={(error["row_id"],error["field"],error["code"]) for error in errors}


def test_directory_without_complete_explicit_members_fails_not_na():
    case,trace=fixture()
    payload=bundle_payload()
    payload["files"]=None
    values=metrics(case,with_artifact_payload(trace,payload))
    assert all(metric.status.value=="fail" for metric in values.values())
