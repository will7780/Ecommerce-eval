from __future__ import annotations

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from commerce_eval.contracts.models import EvalCaseV1, TraceEnvelopeV1
from commerce_eval.contracts.scenarios import CandidateInputV1, CapabilityBindingV1, ModelInputSnapshotV1, ScenarioTemplateV1
from commerce_eval.core.engine import EvaluationEngine
from commerce_eval.packs.artifacts import artifact_evaluators
from commerce_eval.scenarios import ScenarioEnvironment, build_tool_contracts, compile_scenario, get_scenario_template, load_scenario_templates, product_rows, project_candidate_input, run_reference, scenario_evaluators, scenario_summaries
from commerce_eval.scenarios.bindings import decode_arguments, encode_arguments


TEMPLATES = load_scenario_templates()
CASES = [(t.scenario_id,mutation) for t in TEMPLATES for mutation in [None]+[m["name"] for m in t.references["mutants"]]]
ENGINE = EvaluationEngine(scenario_evaluators()+artifact_evaluators())


def mappings(template, alternate=False):
    fields = {key for action in template.references["positive"] for key in action["arguments"]}
    fields |= {"artifact_id","version","content_hash","manifest_hash","rule_version","review_id"}
    return [CapabilityBindingV1(capability_id=capability,tool_id=("adapter_b."+capability.replace(".","_") if alternate else "adapter_a."+capability),
            argument_mapping={key:f"/payload/{key}_value" for key in sorted(fields)} if alternate else {},
            unit_scale={key:100 for key in fields & {"max_price","margin_percent","threshold_percent"}} if alternate else {},
            evidence_mapping={"status":"/receipt/state","receipt_id":"/receipt/id","successful_row_ids":"/receipt/completed_rows"} if alternate else {}) for capability in template.capabilities]


@pytest.mark.parametrize("scenario_id,mutation",CASES,ids=[f"{code}-{name or 'positive'}" for code,name in CASES])
def test_all_32_positive_and_96_specific_mutants_with_equivalent_tool_mappings(scenario_id,mutation):
    template = get_scenario_template(scenario_id)
    evaluations = []
    for alternate in (False,True):
        case = compile_scenario(template,mappings(template,alternate))
        trace = run_reference(case,mutation)
        assert trace.metadata["actor"] == trace.target_id == "reference_actor"
        assert trace.resource_usage.agent_llm_calls == trace.resource_usage.judge_llm_calls == 0
        assert trace.resource_usage.estimated_cost == (None if scenario_id=="S04" and mutation!="unknown_price_card_reported_as_zero_cost" else 0)
        assert TraceEnvelopeV1.model_validate_json(trace.model_dump_json()) == trace
        result = ENGINE.evaluate(case,trace)
        assert not any(metric.status.value=="error" for metric in result.metric_results), result
        assert result.overall_pass is (mutation is None), (scenario_id,mutation,result)
        evaluations.append([(metric.metric_id,metric.value,metric.status) for metric in result.metric_results])
    assert evaluations[0] == evaluations[1]


def test_full_public_material_and_bank_summary():
    assert {t.scenario_id for t in TEMPLATES} == {f"{prefix}{number:02}" for prefix in "ICTPAMRS" for number in range(1,5)}
    assert len({t.direction for t in TEMPLATES}) == 8
    for template in TEMPLATES:
        assert ScenarioTemplateV1.model_validate_json(template.model_dump_json()) == template
        assert len(template.public_task)>75
        assert template.environment["feedback"]
        assert template.behavior_criteria["allowed_paths"]
        assert template.behavior_criteria["gates"]
        assert len(template.references["mutants"])>=3
        assert template.provenance["kind"] in {"existing_test_extraction","business_rule_extraction","new_exam_point"}
        assert template.provenance["data_kind"]=="synthetic"
        assert len(template.initial_data["products"])==20
        for rule in template.rules:
            assert {"scope","version","priority","text"}<=rule.keys()
    assert all({"code","title","direction"}<=summary.keys() for summary in scenario_summaries())
    with pytest.raises(KeyError):
        get_scenario_template("A99")


def test_synthetic_rows_and_evaluator_side_defect_labels():
    clean, corrupt = product_rows(),product_rows("corrupt")
    assert len(clean)==20 and len({r["row_id"] for r in clean})==20
    assert [r["row_id"] for r in clean]==[r["row_id"] for r in corrupt]
    assert [(i,a,b) for i,(a,b) in enumerate(zip(clean,corrupt)) if a!=b][0][0]==16
    assert corrupt[16]["currency"]=="USD" and corrupt[19]["sku"]==""
    assert len([1 for a,b in zip(clean,corrupt) if a!=b])==2
    assert not any("expected" in key or "defect" in key or "label" in key for row in corrupt for key in row)
    clean[0]["title"]="modified"
    assert product_rows()[0]["title"]!="modified"


@pytest.mark.parametrize("template",TEMPLATES,ids=lambda t:t.scenario_id)
def test_candidate_projection_never_exports_answers_or_future_turns(template):
    case = compile_scenario(template)
    canary = "EVALUATOR_ONLY_CANARY"
    case.scenario_data["references"]["answer"] = canary
    case.input["expected_tools"] = [canary]
    case.input["context"] = {"answer":canary}
    case.conversation = [{"type":"user_message","content":canary}]
    for turn in (0,1,50):
        candidate = project_candidate_input(case,turn)
        assert candidate.message==template.public_task
        assert candidate.context=={}
        assert canary not in candidate.model_dump_json()
        assert "references" not in candidate.model_dump_json()
        assert len(candidate.assets)==(2 if template.scenario_id=="P02" else 3)
        assert CandidateInputV1.model_validate_json(candidate.model_dump_json())==candidate


def test_legacy_nested_assets_are_whitelisted_and_filtered():
    canary="DO_NOT_EXPOSE_THIS"
    case=EvalCaseV1(case_id="legacy",name="Legacy",input={"message":"Current task","expected_answer":canary,"conversation":[canary],"assets":[
        {"asset_id":"public","permitted":True,"content":{"products":product_rows(),"referenceTrajectory":canary,"nested":{"ExpectedAnswer":canary,"gates":canary,"futureDialogue":canary}},"script":canary},
        {"asset_id":"hidden","content":canary},
        {"asset_id":"not-permitted","permitted":False,"rows":[canary]},
    ]},expected_tools=[canary],outcome_assertions={"answer":canary})
    result=project_candidate_input(case)
    assert result.message=="Current task" and len(result.assets)==1
    assert canary not in result.model_dump_json()
    assert len(result.assets[0]["content"]["products"])==20
    with pytest.raises(ValueError):
        project_candidate_input(case,-1)


def test_compilation_is_detached_and_requires_unambiguous_bindings():
    template=get_scenario_template("P01")
    bindings=mappings(template,True)
    case=compile_scenario(template,bindings)
    assert EvalCaseV1.model_validate_json(case.model_dump_json())==case
    assert case.scenario_id=="P01" and case.scenario_version=="0.2.0"
    template.initial_data["products"][0]["title"]="changed"
    bindings[0].argument_mapping.clear()
    assert case.scenario_data["initial_data"]["products"][0]["title"]!="changed"
    assert case.capability_bindings[0]["argument_mapping"]
    with pytest.raises(ValueError,match="binding_missing"):
        compile_scenario(template,[])
    with pytest.raises(ValueError,match="binding_ambiguous"):
        compile_scenario(template,mappings(template)+mappings(template))
    with pytest.raises(ValidationError):
        CapabilityBindingV1(capability_id="read",tool_id="tool.read",code="execute")
    with pytest.raises(ValidationError):
        CapabilityBindingV1(capability_id="read",tool_id="tool.read",unit_scale={"price":0})


def test_json_pointer_and_unit_mapping_roundtrip():
    binding=CapabilityBindingV1(capability_id="catalog.read",tool_id="other.reader",argument_mapping={"max_price":"/request/price~1cents","store":"shop"},unit_scale={"max_price":100})
    actual=encode_arguments(binding,{"max_price":25.0,"store":"harbor","limit":6})
    assert actual=={"request":{"price/cents":2500.0},"shop":"harbor","limit":6}
    assert decode_arguments(binding,actual)=={"max_price":25.0,"store":"harbor","limit":6}


def test_model_input_capture_is_ordered_and_explicit_about_omissions():
    snapshot=ModelInputSnapshotV1(snapshot_id="s1",model_call_id="m1",round=0,source="adapter",captured=True,messages=[{"role":"system","content":"Public rules"},{"role":"user","content":"Task"}],tools=[{"name":"catalog.read"}])
    assert snapshot.contract_version=="1.1"
    assert ModelInputSnapshotV1.model_validate_json(snapshot.model_dump_json())==snapshot
    assert [m["role"] for m in snapshot.messages]==["system","user"]
    with pytest.raises(ValidationError):
        ModelInputSnapshotV1(snapshot_id="s1",model_call_id="m1",round=0,source="legacy",captured=False)
    legacy=ModelInputSnapshotV1(snapshot_id="s2",model_call_id="m1",round=0,source="legacy",omission_reason="historical_input_not_captured")
    assert legacy.messages==[] and not legacy.captured


def test_environment_uses_actual_calls_and_independent_sessions(tmp_path):
    template=get_scenario_template("M02")
    template.initial_data["facts"]["store"]=None
    template.interaction_script=[{"type":"clarification","fields":["store"],"response":{"store":"harbor"}}]
    case=compile_scenario(template)
    case.expected_tools=["irrelevant.expected"]
    with ScenarioEnvironment(case,root=tmp_path) as environment:
        ask=environment.execute("one",{"tool_id":"sandbox.interaction.ask","arguments":{"fields":["store"]}})
        assert ask["status"]=="pending"
        with pytest.raises(ValueError,match="mismatch"):
            environment.respond("one","wrong-id",{"store":"harbor"})
        environment.respond("one",ask["interaction_id"],{"store":"harbor"})
        assert environment.state("two")["facts"]["store"] is None
        assert environment.execute("two",{"tool_id":"sandbox.catalog.read","arguments":{"store":"harbor"}})["error_type"]=="scope_denied"
        receipt=environment.execute("one",{"tool_id":"sandbox.catalog.read","arguments":{"store":"harbor","limit":3},"tool_call_id":"read-once"})
        assert len(receipt["rows"])==3
        assert environment.execute("one",{"tool_id":"sandbox.catalog.read","arguments":{"store":"harbor","limit":3},"tool_call_id":"read-once"})==receipt
        assert len([e for e in environment.events("one") if e.kind=="tool.call" and e.event_id=="read-once"])==1
        environment.reset("one")
        assert environment.state("one")["facts"]["store"] is None
    assert list(tmp_path.iterdir())==[]


def test_actual_files_and_external_tamper_are_checked(tmp_path):
    case=compile_scenario(get_scenario_template("A01"))
    with ScenarioEnvironment(case,root=tmp_path) as environment:
        environment.execute("one",{"tool_id":"sandbox.artifact.prepare","arguments":{}})
        paths=environment.materialized_files("one")
        assert len(paths)==1 and len(json.loads(paths[0].read_text()))==20
        content=json.loads(paths[0].read_text())
        content[0]["price"]+=1
        paths[0].write_text(json.dumps(content),encoding="utf-8")
        receipt=environment.execute("one",{"tool_id":"sandbox.artifact.check","arguments":{}})
        assert receipt["error_type"]=="artifact_content_changed"
        assert str(tmp_path) not in json.dumps([e.model_dump(mode="json") for e in environment.events("one")])


def test_tool_contract_builder_preserves_actual_ids():
    case=compile_scenario(get_scenario_template("P01"),mappings(get_scenario_template("P01"),True))
    contracts=build_tool_contracts(case)
    assert {c.tool_id for c in contracts}=={b["tool_id"] for b in case.capability_bindings}
    assert all(c.version=="0.2.0" for c in contracts)


@pytest.mark.parametrize("scenario_id",[t.scenario_id for t in TEMPLATES])
def test_arbitrary_agent_final_answer_is_equivalent_without_report_tool(scenario_id):
    from commerce_eval.contracts.models import TraceEventV1
    template=get_scenario_template(scenario_id)
    fixture_case=compile_scenario(template)
    trace=run_reference(fixture_case)
    report_ids={e.event_id for e in trace.events if e.kind=="tool.call" and e.name=="sandbox.report.finish"}
    reports=[e for e in trace.events if e.event_id in report_ids]
    trace.events=[e for e in trace.events if e.event_id not in report_ids and e.attributes.get("tool_call_id") not in report_ids]
    for index,report in enumerate(reports):
        refs=[e.event_id for e in trace.events if e.sequence<report.sequence and e.kind in {"observation","interaction.response","artifact.review"}]
        trace.events.append(TraceEventV1(event_id=f"agent-final-{index}",sequence=report.sequence,kind="final_answer",attributes={"outcome":report.attributes["arguments"]["outcome"],"text":"Outcome supported by the linked observations."},evidence_refs=refs))
    trace.events.sort(key=lambda event:event.sequence)
    trace.target_id="independent-target"
    trace.metadata={}
    bindings=[b for b in fixture_case.capability_bindings if b["capability_id"]!="report.finish"]
    case=compile_scenario(template,bindings)
    assert case.contract_version=="1.1"
    result=ENGINE.evaluate(case,trace)
    assert result.overall_pass,result
    next(event for event in reversed(trace.events) if event.kind=="final_answer").evidence_refs=["nonexistent-receipt"]
    assert not ENGINE.evaluate(case,trace).overall_pass


def test_false_completed_final_cannot_cite_a_failed_observation():
    from commerce_eval.contracts.models import TraceEventV1
    case=compile_scenario(get_scenario_template("R04"))
    trace=run_reference(case)
    report_ids={e.event_id for e in trace.events if e.kind=="tool.call" and e.name=="sandbox.report.finish"}
    trace.events=[e for e in trace.events if e.event_id not in report_ids and e.attributes.get("tool_call_id") not in report_ids]
    failed=next(e for e in trace.events if e.kind=="observation" and e.status.value=="error")
    trace.events.append(TraceEventV1(event_id="false-final",sequence=100,kind="final_answer",attributes={"outcome":"completed"},evidence_refs=[failed.event_id]))
    result=ENGINE.evaluate(case,trace)
    assert not result.overall_pass
    assert "final_answer_evidence_unavailable_or_mismatched" in result.metric_results[0].details["failures"]


@pytest.mark.parametrize("alternate",[False,True])
def test_all_reference_positive_arguments_match_compiled_tool_schemas(alternate):
    from jsonschema import Draft202012Validator
    from commerce_eval.scenarios import capability_declarations
    for template in TEMPLATES:
        case=compile_scenario(template,mappings(template,alternate))
        contracts={contract.tool_id:contract for contract in build_tool_contracts(case)}
        for event in run_reference(case).events:
            if event.kind=="tool.call":
                Draft202012Validator(contracts[event.name].input_schema).validate(event.attributes["arguments"])
        declarations=capability_declarations(case)
        assert {row["capability_id"] for row in declarations}==set(template.capabilities)
        assert next(row for row in declarations if row["capability_id"]=="report.finish")["event_alternative"]=="final_answer"


def test_supplied_product_assets_drive_environment_and_do_not_change_policy(tmp_path):
    rows=product_rows()
    rows[0]["title"]="User supplied notebook"
    case=compile_scenario(get_scenario_template("A01"),assets=[{"asset_id":"products","media_type":"application/json","rows":rows}])
    assert next(asset for asset in project_candidate_input(case).assets if asset.get("asset_id")=="products")["rows"][0]["title"]=="User supplied notebook"
    with ScenarioEnvironment(case,root=tmp_path) as environment:
        environment.execute("assets",{"tool_id":"sandbox.artifact.prepare","arguments":{}})
        actual=json.loads(environment.materialized_files("assets")[0].read_text())
        assert actual[0]["title"]=="User supplied notebook"
    assert case.artifact_requirements["policy"]["currency"]=="EUR"


def test_consumer_arguments_not_rewritten_and_call_id_conflicts_are_rejected(tmp_path):
    case=compile_scenario(get_scenario_template("A01"))
    with ScenarioEnvironment(case,root=tmp_path) as environment:
        for cap,args in [("artifact.prepare",{}),("artifact.check",{}),("artifact.sample",{"seed":"bank-v2"})]:
            environment.execute("one",{"tool_id":"sandbox."+cap,"arguments":args})
        review=environment.execute("one",{"tool_id":"sandbox.artifact.review","arguments":{}})
        environment.respond("one",review["interaction_id"],{"decision":"approved"})
        bad=environment.execute("one",{"tool_id":"sandbox.catalog.publish","tool_call_id":"unbound-publish","arguments":{}})
        assert bad["error_type"]=="invalid_arguments"
        call=next(e for e in environment.events("one") if e.event_id=="unbound-publish")
        assert call.attributes["arguments"]=={}
        frozen=environment.state("one")["artifact_binding"]
        receipt=environment.execute("one",{"tool_id":"sandbox.catalog.publish","tool_call_id":"bound-publish","arguments":frozen})
        assert receipt["status"]=="ok"
        conflicting=environment.execute("one",{"tool_id":"sandbox.catalog.publish","tool_call_id":"bound-publish","arguments":{}})
        assert conflicting["error_type"]=="tool_call_id_reused_with_different_arguments"
        assert len(environment.state("one")["published"])==1


def test_absent_forbidden_tools_need_no_mapping_and_json_asset_answers_are_removed():
    template=get_scenario_template("I01")
    optional=set(template.behavior_criteria["forbidden"])|{"report.finish"}
    required=[binding for binding in mappings(template) if binding.capability_id not in optional]
    case=compile_scenario(template,required)
    assert case.forbidden_tools==[]
    case.input["assets"]=[{"permitted":True,"asset_id":"json","content":json.dumps({"title":"public","ExpectedAnswer":"PRIVATE_CANARY","nested":{"reference":"PRIVATE_CANARY"}})}]
    candidate=project_candidate_input(case)
    assert "PRIVATE_CANARY" not in candidate.model_dump_json()
    assert json.loads(candidate.assets[0]["content"])=={"title":"public","nested":{}}

@pytest.mark.parametrize("code,capability",[("I01","catalog.preview"),("C01","rules.read"),("T01","catalog.generate_listing"),("T01","catalog.publish"),("T01","pricing.audit_margin")])
def test_attempt_without_required_receipt_never_counts_as_success(code,capability):
    case=compile_scenario(get_scenario_template(code))
    trace=run_reference(case)
    ids={event.event_id for event in trace.events if event.kind=="tool.call" and event.name=="sandbox."+capability}
    trace.events=[event for event in trace.events if not (event.kind=="observation" and event.attributes.get("tool_call_id") in ids)]
    assert not ENGINE.evaluate(case,trace).overall_pass


def test_unlinked_plausible_final_receipt_is_not_business_evidence():
    from commerce_eval.contracts.models import TraceEventV1
    case=compile_scenario(get_scenario_template("I01"))
    trace=run_reference(case)
    ids={event.event_id for event in trace.events if event.name=="sandbox.report.finish"}
    trace.events=[event for event in trace.events if event.event_id not in ids and event.attributes.get("tool_call_id") not in ids]
    sequence=max(event.sequence for event in trace.events)+1
    trace.events.extend([
        TraceEventV1(event_id="fake-receipt",sequence=sequence,kind="observation",attributes={"tool_call_id":"nonexistent-call","result":{"status":"ok","receipt_id":"invented","rows":product_rows()}}),
        TraceEventV1(event_id="fake-final",sequence=sequence+1,kind="final_answer",attributes={"outcome":"completed"},evidence_refs=["fake-receipt"]),
    ])
    assert not ENGINE.evaluate(case,trace).overall_pass


@pytest.mark.parametrize("code",["T03","R04"])
@pytest.mark.parametrize("outcome",["failed","empty","simulated"])
def test_no_artifact_variants_cannot_publish_or_claim_real_success(code,outcome):
    template=get_scenario_template(code)
    template.environment["generation_failure"]=outcome=="failed"
    template.environment["generation_outcome"]=outcome
    case=compile_scenario(template)
    trace=run_reference(case)
    assert ENGINE.evaluate(case,trace).overall_pass
    assert not any(event.kind=="artifact.created" for event in trace.events)
    from commerce_eval.contracts.models import TraceEventV1
    receipt=next(event for event in trace.events if event.kind=="observation")
    trace.events.append(TraceEventV1(event_id="false-real",sequence=max(event.sequence for event in trace.events)+1,kind="final_answer",attributes={"outcome":"completed"},evidence_refs=[receipt.event_id]))
    assert not ENGINE.evaluate(case,trace).overall_pass


@pytest.mark.parametrize("mode",["content","add","remove"])
def test_a04_reviewed_directory_changes_stop_publication(mode):
    template=get_scenario_template("A04")
    template.references["positive"][4]["arguments"]["mode"]=mode
    case=compile_scenario(template)
    trace=run_reference(case)
    assert ENGINE.evaluate(case,trace).overall_pass
    assert not any(event.kind=="artifact.consume" for event in trace.events)
    inspect=next(event for event in trace.events if event.kind=="observation" and event.attributes.get("tool_id")=="sandbox.artifact.inspect")
    assert inspect.attributes["result"]["error_type"]==("artifact_content_changed" if mode=="content" else "artifact_manifest_changed")
    assert not ENGINE.evaluate(case,run_reference(case,"publish_after_reviewed_file_changed")).overall_pass


def test_i03_has_old_and_current_scope_and_rejects_extra_broad_read():
    from commerce_eval.scenarios.bank import inserted
    template=get_scenario_template("I03")
    case=compile_scenario(template)
    trace=run_reference(case)
    scopes=[event.attributes["scope"] for event in trace.events if event.kind=="user.message"]
    assert scopes==[{"category":"all","limit":20},{"category":"stationery","limit":4}]
    template.references["mutants"].append(inserted("replay_old_scope",0,"catalog.read",store="harbor",limit=20))
    assert not ENGINE.evaluate(compile_scenario(template),run_reference(compile_scenario(template),"replay_old_scope")).overall_pass
    trace.events=[event for event in trace.events if not (event.kind=="user.message" and event.attributes.get("phase")=="previous")]
    assert not ENGINE.evaluate(case,trace).overall_pass


def test_m03_completion_precedes_new_user_task_and_no_replay():
    case=compile_scenario(get_scenario_template("M03"))
    trace=run_reference(case)
    transition=next(event for event in trace.events if event.kind=="user.message")
    finals=[event for event in trace.events if event.kind=="observation" and event.attributes.get("tool_id")=="sandbox.report.finish"]
    assert len(finals)==2 and finals[0].sequence<transition.sequence<finals[1].sequence
    first_call=finals[0].attributes["tool_call_id"]
    trace.events=[event for event in trace.events if event.event_id!=first_call and event.attributes.get("tool_call_id")!=first_call]
    assert not ENGINE.evaluate(case,trace).overall_pass


def test_m04_company_rows_policy_and_authorization_are_isolated():
    case=compile_scenario(get_scenario_template("M04"))
    trace=run_reference(case)
    switch=next(event for event in trace.events if event.kind=="company.changed")
    assert switch.attributes["authorization"]=="cleared" and switch.attributes["active_artifact"] is None
    read=next(event for event in trace.events if event.sequence>switch.sequence and event.kind=="observation" and event.attributes.get("tool_id")=="sandbox.catalog.read")
    rows=read.attributes["result"]["rows"]
    assert rows==case.scenario_data["initial_data"]["company_products"]["summit"]
    assert all(row["sku"].startswith("SUM-") for row in rows)
    read.attributes["result"]["rows"]=product_rows()
    assert not ENGINE.evaluate(case,trace).overall_pass


@pytest.mark.parametrize("code",["T02","R01","R02","S03"])
def test_react_does_not_require_artificial_plan_tool(code):
    template=get_scenario_template(code)
    assert "workflow.plan" not in template.capabilities
    case=compile_scenario(template)
    trace=run_reference(case)
    if code!="T02":
        assert any(event.kind=="model.decision" for event in trace.events)
    assert ENGINE.evaluate(case,trace).overall_pass
    trace.events=[event for event in trace.events if event.kind!="model.decision"]
    assert ENGINE.evaluate(case,trace).overall_pass


def test_r01_changed_parameters_are_equivalent_to_alternate_tool():
    template=get_scenario_template("R01")
    template.references["positive"][1]={"capability":"catalog.read","arguments":{"store":"harbor","source":"mirror","limit":20}}
    case=compile_scenario(template)
    assert ENGINE.evaluate(case,run_reference(case)).overall_pass


@pytest.mark.parametrize("capability",["catalog.generate_listing","catalog.generate_alternative"])
def test_t04_either_generator_has_same_actual_artifact(capability):
    template=get_scenario_template("T04")
    template.references["positive"][0]["capability"]=capability
    case=compile_scenario(template)
    trace=run_reference(case)
    created=next(event for event in trace.events if event.kind=="artifact.created")
    assert created.attributes["rows"]==product_rows()
    assert ENGINE.evaluate(case,trace).overall_pass
    created.attributes["rows"]=created.attributes["rows"][:1]
    assert not ENGINE.evaluate(case,trace).overall_pass


@pytest.mark.parametrize("parameters",[{"quantity":"twenty"},{"site":"XX"},{"margin_percent":120},{"unsafe_option":True}])
def test_p03_invalid_schema_each_category_has_zero_execution(parameters,tmp_path):
    case=compile_scenario(get_scenario_template("P03"))
    with ScenarioEnvironment(case,root=tmp_path) as environment:
        receipt=environment.execute("invalid",{"tool_id":"sandbox.catalog.generate_listing","arguments":{"input_file":"products","store":"harbor",**parameters}})
        assert receipt["error_type"]=="invalid_arguments"
        assert not any(event.kind in {"tool.execute","artifact.created","artifact.consume"} for event in environment.events("invalid"))
        assert not environment.materialized_files("invalid")


def test_s02_tampered_resume_has_explicit_rejection_and_zero_execution():
    case=compile_scenario(get_scenario_template("S02"))
    trace=run_reference(case,"tampered_resume_changes_rejection_to_approval")
    assert any(event.kind=="interaction.resume_rejected" and event.attributes["executed"] is False for event in trace.events)
    assert not any(event.kind in {"tool.execute","artifact.consume"} for event in trace.events)
    assert not ENGINE.evaluate(case,trace).overall_pass


def test_c04_excludes_expired_and_foreign_rules_and_does_not_trust_receipt():
    case=compile_scenario(get_scenario_template("C04"))
    trace=run_reference(case)
    receipt=next(event for event in trace.events if event.kind=="observation")
    assert receipt.attributes["result"]["effective_rule"]["rule_id"]=="catalog-current"
    assert "18 percent" in case.input["message"]
    foreign=next(rule for rule in case.scenario_data["rules"] if rule["rule_id"]=="foreign-same-name")
    receipt.attributes["result"]["effective_rule"]=foreign
    assert not ENGINE.evaluate(case,trace).overall_pass


def test_s04_unknown_cost_is_null_and_wait_not_active_runtime():
    case=compile_scenario(get_scenario_template("S04"))
    trace=run_reference(case)
    usage=trace.resource_usage
    assert usage.total_tokens==900
    assert usage.active_runtime_ms==1200 and usage.user_wait_ms==60000
    assert usage.wall_runtime_ms==usage.active_runtime_ms+usage.user_wait_ms
    assert usage.estimated_cost is None and usage.cost_status=="price_card_unavailable"
    assert ENGINE.evaluate(case,trace).overall_pass


def test_normalized_bank_and_imported_effective_asset_refs_roundtrip(tmp_path):
    from commerce_eval.core.normalizer import ContractNormalizer
    from commerce_eval.storage.database import Database
    from commerce_eval.storage.repository import Repository
    from commerce_eval.services.scenario_templates import instantiate
    database=Database(tmp_path/"bank.db")
    database.initialize()
    repository=Repository(database)
    repository.create_project("bank-audit","Bank audit")
    cases=[ContractNormalizer.case(compile_scenario(template)) for template in TEMPLATES]
    saved=repository.save_dataset("bank-audit","locked","0.2.0","Locked bank",cases)
    assert len(saved["cases"])==32 and all(case["contract_version"]=="1.1" for case in saved["cases"])
    rows=product_rows()
    rows[0]["title"]="Imported effective product"
    asset=repository.save_asset("bank-audit","products","uploaded-products","7","Products",rows)
    result=instantiate(repository,"A01",project_id="bank-audit",dataset_id="imported",version="1",assets=[{"kind":"products","asset_id":"uploaded-products","version":"7"}])
    assert result["status"]=="ready"
    case=EvalCaseV1.model_validate(repository.get_dataset("bank-audit","imported","1")["cases"][0])
    assert case.contract_version=="1.1"
    assert case.scenario_data["initial_data"]["products"]==rows
    ref=next(ref for ref in case.scenario_data["initial_data"]["effective_asset_refs"] if ref["asset_id"]=="uploaded-products")
    assert ref=={"asset_id":"uploaded-products","kind":"products","version":"7","checksum":asset["checksum"]}
    projected=next(item for item in project_candidate_input(case).assets if item["asset_id"]=="uploaded-products")
    assert projected["rows"]==rows and projected["version"]=="7" and projected["checksum"]==asset["checksum"]
    created=next(event for event in run_reference(case).events if event.kind=="artifact.created")
    assert created.attributes["rows"]==rows

    database.dispose()

def test_bare_audit_ok_cannot_replace_actual_margin_evidence():
    case=compile_scenario(get_scenario_template("T01"))
    trace=run_reference(case)
    receipt=next(event for event in trace.events if event.kind=="observation" and event.attributes.get("tool_id")=="sandbox.pricing.audit_margin")
    assert len(receipt.attributes["result"]["margins"])==20
    receipt.attributes["result"]["margins"]=[]
    assert not ENGINE.evaluate(case,trace).overall_pass


@pytest.mark.parametrize("change",["missing","invalid"])
def test_generation_checks_actual_input_file_not_cached_rows(change,tmp_path):
    case=compile_scenario(get_scenario_template("I01"))
    with ScenarioEnvironment(case,root=tmp_path) as environment:
        environment.state("one")
        path=next(tmp_path.glob("commerce-scenario-*/inputs/products.json"))
        if change=="missing":
            path.unlink()
        else:
            rows=product_rows()
            rows[0]["price"]=-1
            path.write_text(json.dumps(rows),encoding="utf-8")
        result=environment.execute("one",{"tool_id":"sandbox.catalog.generate_listing","arguments":{"input_file":"products","store":"harbor"}})
        assert result["error_type"]==("input_file_missing" if change=="missing" else "source_validation_failed")
        assert not any(event.kind=="artifact.created" for event in environment.events("one"))

@pytest.mark.asyncio
async def test_stored_m03_runner_delivers_new_user_task_after_completed_phase(tmp_path):
    from commerce_eval.contracts.models import ExperimentSpecV1, TargetRunResponseV1
    from commerce_eval.experiments.runner import ExperimentRunner
    from commerce_eval.storage import Database, Repository
    database=Database(tmp_path/"m03-runner.db")
    database.initialize()
    repository=Repository(database)
    repository.create_project("turn-audit","Turn audit")
    stored=repository.save_dataset("turn-audit","turns","1","Turns",[compile_scenario(get_scenario_template("M03"))])
    case=EvalCaseV1.model_validate(stored["cases"][0])
    future=case.scenario_data["interaction_script"][2]
    assert future["type"]=="user_message"
    class Target:
        def __init__(self):
            self.starts=[]
            self.resumes=[]
        def response(self,index,pending=None):
            status="awaiting_confirmation" if pending else "completed"
            trace=TraceEnvelopeV1(trace_id=f"phase-{index}",project_id="turn-audit",target_id="independent",target_version="1",status=status,events=[{"event_id":f"phase-{index}-call","sequence":0,"kind":"model.call"}])
            return TargetRunResponseV1(external_run_id=f"external-{index}",status=status,pending_interaction=pending,trace=trace)
        async def start(self,request):
            self.starts.append(request)
            if len(self.starts)==1:
                assert future["content"] not in request.model_dump_json()
                assert "audit_margin" not in request.model_dump_json()
                return self.response(0,{"interaction_id":"review","type":"confirmation","confirmation_kind":"artifact","prompt":"Review?"})
            assert request.case.input["message"]==future["content"]
            assert request.session_id==self.starts[0].session_id
            assert request.request_id!=self.starts[0].request_id
            return self.response(3)
        async def resume(self,request):
            self.resumes.append(request)
            if len(self.resumes)==1:
                return self.response(1,{"interaction_id":"risk","type":"confirmation","confirmation_kind":"risk","required_fields":["publish"],"prompt":"Publish?"})
            return self.response(2)
    target=Target()
    spec=ExperimentSpecV1(experiment_id="turns",project_id="turn-audit",name="Turns",dataset_id="turns",dataset_version="1",target_id="independent",target_version="1")
    result=await ExperimentRunner(repository)._execute_case(target,spec,case,1,session_id="same-thread",request_id="first-request")
    assert result.status.value=="completed" and not result.error_type
    assert len(target.starts)==2 and len(target.resumes)==2
    assert [event.attributes["content"] for event in result.trace.events if event.kind=="user.message"]==[case.input["message"],future["content"]]
    database.dispose()


def test_m04_current_task_does_not_disclose_future_company_choice():
    case=compile_scenario(get_scenario_template("M04"))
    assert "Summit" not in case.input["message"] and "summit" not in case.input["message"]
    assert case.scenario_data["interaction_script"][-1]["response"]=={"next_company":"summit"}
    assert "next_company" not in project_candidate_input(case).model_dump_json()

def test_bank_template_reference_steps_are_detached_across_calls_and_cases():
    first=get_scenario_template("I01")
    first.references["positive"][-1]["arguments"]["outcome"]="changed-by-editor"
    assert get_scenario_template("I01").references["positive"][-1]["arguments"]["outcome"]=="completed"
    templates=load_scenario_templates()
    templates[0].references["positive"][-1]["arguments"]["outcome"]="changed-by-editor"
    assert templates[1].references["positive"][-1]["arguments"]["outcome"]=="completed"

    templates={template.scenario_id:template for template in load_scenario_templates()}
    templates["A01"].interaction_script[0]["response"]["decision"]="changed-by-editor"
    assert templates["A04"].interaction_script[0]["response"]["decision"]=="approved"

def test_review_seed_is_public_and_job_id_is_receipt_bound_not_hidden_default():
    case=compile_scenario(get_scenario_template("A01"))
    task_data=next(asset for asset in project_candidate_input(case).assets if asset["asset_id"]=="task-data")
    assert task_data["content"]["review_protocol"]=={"seed":"bank-v2","normal_sample_count":5}
    template=get_scenario_template("R03")
    template.references["positive"][1]["arguments"]["job_id"]="chosen-by-merchant"
    template.references["positive"][2]["arguments"]["job_id"]="chosen-by-merchant"
    case=compile_scenario(template)
    assert ENGINE.evaluate(case,run_reference(case)).overall_pass
