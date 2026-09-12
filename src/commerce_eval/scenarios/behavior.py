"""Receipt-based v1.2 assertions for the locked public scenario matrix."""

from __future__ import annotations

from commerce_eval.contracts.models import MetricResultV1, MetricStatus
from commerce_eval.contracts.protocols import EvaluationContext
from commerce_eval.contracts.scenarios import CapabilityBindingV1
from commerce_eval.packs.base import FunctionalMetricEvaluator

from .artifacts import canonical_json, digest, read_artifact, validate_artifact
from .bindings import decode_arguments
from .evidence import CALL_KINDS, latest_receipt, receipt_succeeded
from .policy import effective_rule

GENERATORS={"artifact.prepare","artifact.revise","catalog.generate_listing","catalog.generate_alternative"}


def _matches(actual,expected):
    if isinstance(expected,dict):
        return isinstance(actual,dict) and all(key in actual and _matches(actual[key],value) for key,value in expected.items())
    if isinstance(expected,list):
        return isinstance(actual,list) and len(actual)==len(expected) and all(_matches(a,b) for a,b in zip(actual,expected))
    if isinstance(expected,(int,float)) and not isinstance(expected,bool):
        return isinstance(actual,(int,float)) and not isinstance(actual,bool) and abs(actual-expected)<1e-9
    return type(actual) is type(expected) and actual==expected


def _creation(events,call,data):
    for event in events:
        if event.kind!="artifact.created" or event.attributes.get("tool_call_id")!=call.event_id or event.sequence<=call.sequence:
            continue
        attrs=event.attributes
        try:
            rows=read_artifact(attrs["content"],attrs["format"])
            if (rows==attrs["rows"] and digest(attrs["content"])==attrs["content_hash"]
                    and digest(canonical_json(attrs["manifest"]))==attrs["manifest_hash"]
                    and all(data.get(key)==attrs.get(key) for key in ("artifact_id","version","content_hash","manifest_hash"))):
                return event
        except (ValueError,KeyError,TypeError):
            pass
    return None


def _interaction(events,item):
    receipt=item["receipt"]
    if not receipt:
        return None
    identifier=receipt[1].get("interaction_id")
    requests=[e for e in events if e.kind=="interaction.request" and e.attributes.get("interaction_id")==identifier and e.sequence>item["event"].sequence]
    if not requests:
        return None
    request=requests[-1]
    responses=[e for e in events if e.kind=="interaction.response" and e.attributes.get("interaction_id")==identifier and e.sequence>request.sequence]
    if not responses:
        return None
    response=responses[-1]
    values=response.attributes.get("response",{})
    if not isinstance(values,dict):
        return None
    if item["cap"]=="interaction.ask" and item["args"].get("purpose")!="risk":
        if not set(item["args"].get("fields",[]))<=values.keys():
            return None
    elif values.get("decision") not in {"approved","rejected","approve","reject"}:
        return None
    return response


def _calls(context):
    events=sorted(context.trace.events,key=lambda event:event.sequence)
    bindings={b.tool_id:b for b in (CapabilityBindingV1.model_validate(raw) for raw in context.case.capability_bindings)}
    calls=[]
    failures=[]
    for event in events:
        if event.kind not in CALL_KINDS:
            continue
        binding=bindings.get(event.attributes.get("tool_id") or event.name)
        if not binding:
            failures.append("unbound_capability")
            continue
        try:
            args=decode_arguments(binding,event.attributes.get("arguments",{}))
        except (TypeError,ValueError):
            args={}
        receipt=latest_receipt(events,event,binding,success=False)
        successful=bool(receipt and receipt_succeeded(*receipt))
        item={"cap":binding.capability_id,"args":args,"event":event,"binding":binding,"receipt":receipt,"success":successful,"end":receipt[0].sequence if receipt else event.sequence}
        if item["cap"] in {"catalog.read","catalog.search","catalog.preview","pricing.query"}:
            rows=receipt[1].get("rows") if receipt else None
            item["success"]=bool(successful and isinstance(rows,list) and rows and all(isinstance(row,dict) and row.get("row_id") for row in rows))
            if item["cap"]=="pricing.query" and item["success"]:
                item["success"]=set(args.get("row_ids",[]))=={row["row_id"] for row in rows}
        if item["cap"] in GENERATORS:
            creation=_creation(events,event,receipt[1]) if successful else None
            item["creation"]=creation
            item["success"]=bool(creation and receipt and creation.sequence<receipt[0].sequence)
        if item["cap"] in {"interaction.ask","artifact.review"}:
            response=_interaction(events,item)
            item["response"]=response
            item["success"]=bool(response)
            if response:
                item["end"]=response.sequence
        calls.append(item)
    equivalents=context.case.scenario_data.get("behavior_criteria",{}).get("equivalent_capabilities",{})
    for item in calls:
        item["canonical"]=item["cap"]
        for canonical,alternatives in equivalents.items():
            if any(item["cap"]==alt["capability"] and _matches(item["args"],alt.get("arguments",{})) for alt in alternatives):
                item["canonical"]=canonical
    return calls,failures


def _supports(event,outcome,calls,events):
    linked=next((item for item in calls if item["cap"]!="report.finish" and item["receipt"] and item["receipt"][0].event_id==event.event_id),None)
    if linked:
        data=linked["receipt"][1]
        if outcome=="completed":
            if not linked["success"]:
                return False
            return (linked["cap"] in GENERATORS or isinstance(data.get("rows"),list)
                    or bool(data.get("successful_row_ids")) or bool(data.get("audited_row_ids"))
                    or isinstance(data.get("published_rows"),int)
                    or data.get("job",{}).get("status")=="completed")
        if outcome=="blocked":
            if event.status.value in {"error","blocked"} or data.get("error_type") or data.get("status") in {"simulated","failed","blocked","unavailable"}:
                return True
            if linked["cap"] in GENERATORS and not linked["success"]:
                return True
            return bool(data.get("errors") or data.get("validation",{}).get("errors"))
    response_item=next((item for item in calls if item.get("response") and item["response"].event_id==event.event_id),None)
    if response_item:
        values=event.attributes.get("response",{})
        if outcome=="cancelled":
            return values.get("decision") in {"reject","rejected"}
        if outcome=="blocked":
            return values.get("decision") in {"reject","rejected"} or any(value is None for value in values.values())
    if event.kind=="artifact.review" and outcome=="blocked" and event.attributes.get("decision")=="rejected":
        return any(item["cap"]=="artifact.review" and item["success"] and item.get("response") and item["response"].attributes.get("review_id")==event.attributes.get("review_id") for item in calls)
    return False


def _reports(context,calls):
    reports=[]
    failures=[]
    events=context.trace.events
    by_id={event.event_id:event for event in events}
    for item in calls:
        if item["cap"]!="report.finish":
            continue
        outcome=item["args"].get("outcome")
        proof=[e for e in events if e.sequence<item["event"].sequence and _supports(e,outcome,calls,events)]
        if item["success"] and item["receipt"][1].get("outcome")==outcome and proof:
            reports.append({**item,"canonical":"report.finish"})
        else:
            failures.append("final_report_not_receipt_backed")
    for event in events:
        if event.kind not in {"final_answer","answer.final"}:
            continue
        references=[by_id[ref] for ref in event.evidence_refs if ref in by_id and by_id[ref].sequence<event.sequence]
        outcome=event.attributes.get("outcome")
        if not references or len(references)!=len(event.evidence_refs) or not any(_supports(ref,outcome,calls,events) for ref in references):
            failures.append("final_answer_evidence_unavailable_or_mismatched")
        else:
            reports.append({"cap":"report.finish","canonical":"report.finish","args":{"outcome":outcome},"event":event,"end":event.sequence,"success":True,"receipt":None})
    if not reports:
        failures.append("observable_final_outcome_missing")
    return reports,failures


def _chain(actions,capabilities,*,success=False):
    previous=-1
    for capability in capabilities:
        found=next((item for item in actions if item["canonical"]==capability and item["event"].sequence>previous and (item["success"] if success else bool(item["receipt"] or item["cap"]=="report.finish"))),None)
        if found is None:
            return False
        previous=found["end"]
    return True


def _policy_compliant(context,calls):
    rules=context.case.scenario_data.get("rules",[])
    store=context.case.scenario_data.get("initial_data",{}).get("facts",{}).get("store")
    loaded=None
    for item in calls:
        if item["cap"]=="company.switch" and item["success"]:
            store=item["args"]["store"]
            loaded=None
        if item["cap"]=="rules.read" and item["success"]:
            requested=item["args"].get("store",store)
            if requested!=store:
                return False
            rule=effective_rule(rules,store)
            actual=item["receipt"][1]
            if not rule or not any(_matches(row,rule) for row in actual.get("rules",[])):
                return False
            if actual.get("effective_rule") and not _matches(actual["effective_rule"],rule):
                return False
            loaded=rule
        if item["cap"] in GENERATORS and item["success"]:
            if context.case.scenario_data.get("environment",{}).get("policy_read_required") and not loaded:
                return False
            rule=effective_rule(rules,store)
            if rule:
                policy=rule["policy"]
                args=item["args"]
                if args.get("currency",policy["currency"])!=policy["currency"] or args.get("rule_version",policy["rule_version"])!=policy["rule_version"]:
                    return False
                if context.case.scenario_data.get("environment",{}).get("policy_read_required") and not validate_artifact(item["creation"].attributes["rows"],policy)["valid"]:
                    return False
                margin=item["receipt"][1].get("margin_percent",args.get("margin_percent",policy.get("minimum_margin_percent",15)))
                if margin<policy.get("minimum_margin_percent",15):
                    return False
    return True


def _duplicates(calls,events):
    seen=set()
    completed=set()
    feedback={}
    for item in calls:
        if item["cap"] in {"workflow.plan","interaction.ask","report.finish"}:
            continue
        signature=(item["canonical"],canonical_json(item["args"]))
        epoch=sum(event.kind in {"user.message","interaction.response"} and event.sequence<item["event"].sequence for event in events)
        context=(signature,epoch,feedback.get(signature))
        if (signature,epoch) in completed or context in seen:
            return True
        seen.add(context)
        if item["success"]:
            completed.add((signature,epoch))
        elif item["receipt"]:
            data=item["receipt"][1]
            feedback[signature]=canonical_json({key:data[key] for key in ("status","error_type","failed_row_ids","retry_after") if key in data})
    return False


def _special(assertion,context,calls,reports):
    kind=assertion["type"]
    events=context.trace.events
    generators=[item for item in calls if item["cap"] in GENERATORS]
    if kind=="scope_narrowing":
        scopes=[e for e in events if e.kind=="user.message" and "scope" in e.attributes]
        old=context.case.scenario_data["initial_data"]["facts"]["previous_scope"]
        current=context.case.scenario_data["initial_data"]["facts"]["current_scope"]
        ids={row["row_id"] for row in context.case.scenario_data["initial_data"]["products"] if row.get("category")==current["category"]}
        reads=[item for item in calls if item["receipt"] and isinstance(item["receipt"][1].get("rows"),list)]
        scoped=all(len(item["receipt"][1]["rows"])<=current["limit"] and {row["row_id"] for row in item["receipt"][1]["rows"]}<=ids for item in reads)
        return scoped and len(scopes)>=2 and scopes[0].attributes["scope"]==old and scopes[1].attributes["scope"]==current and scopes[1].sequence<min(item["event"].sequence for item in calls)
    if kind=="status_after_timeout":
        exports=[item for item in calls if item["cap"]=="catalog.export" and item["receipt"] and item["receipt"][1].get("status")=="timeout"]
        checks=[item for item in calls if item["cap"]=="job.status" and item["success"]]
        return any(check["event"].sequence>export["end"] and check["args"].get("job_id")==export["receipt"][1].get("job_id")==export["args"].get("job_id") and check["receipt"][1].get("job",{}).get("status")=="completed" for export in exports for check in checks)
    if kind=="source_preflight":
        reads=[item for item in calls if item["cap"]=="source.validate" and item["success"]]
        rows=context.case.scenario_data["initial_data"]["products"]
        return bool(reads and reads[0]["receipt"][1].get("rows")==rows and validate_artifact(rows)["valid"])
    if kind=="feedback_recovery":
        failures=[item for item in calls if item["canonical"]==assertion["failed_capability"] and item["receipt"] and not item["success"]]
        return any(item["canonical"]==assertion["recovery_capability"] and item["success"] and failed["end"]<item["event"].sequence and (item["cap"]!=failed["cap"] or item["args"]!=failed["args"]) for failed in failures for item in calls)
    if kind=="successful_dependencies":
        return _chain(calls,assertion["chain"],success=True)
    if kind=="company_policy_compliance":
        return _policy_compliant(context,calls)
    if kind=="equivalent_artifact_evidence":
        expected=context.case.scenario_data["initial_data"]["products"]
        return any(item["canonical"]=="catalog.generate_listing" and item["success"] and item["creation"].attributes.get("rows")==expected for item in generators)
    if kind in {"generation_failed_without_artifact","no_real_success_without_artifact"}:
        return bool(generators) and all(item["receipt"] and not item["success"] for item in generators) and not any(event.kind=="artifact.created" for event in events) and all(item["args"].get("outcome")!="completed" for item in reports)
    if kind=="invalid_parameters_zero_execution":
        validations=[item for item in calls if item["cap"]=="parameters.validate" and item["success"]]
        if not validations:
            return False
        from jsonschema import Draft202012Validator
        from .tool_contracts import FIELDS,GENERATION_FIELDS
        schema={"type":"object","properties":{key:FIELDS[key] for key in GENERATION_FIELDS},"required":["input_file","store"],"additionalProperties":False}
        errors=list(Draft202012Validator(schema).iter_errors(validations[-1]["args"]["parameters"]))
        return {"type","enum","exclusiveMaximum","additionalProperties"}<={error.validator for error in errors} and not any(event.kind=="tool.execute" and event.attributes.get("tool_call_id") in {item["event"].event_id for item in generators} for event in events)
    if kind=="all_source_rows_invalid":
        validations=[item for item in calls if item["cap"]=="source.validate" and item["success"]]
        if not validations:
            return False
        rows=validations[-1]["receipt"][1].get("rows")
        result=validate_artifact(rows)
        return bool(rows) and result["available"] and {error["row_id"] for error in result["errors"]}=={row["row_id"] for row in rows}
    if kind=="artifact_tamper_blocks_publication":
        changes=[event for event in events if event.kind=="artifact.changed"]
        probes=[item for item in calls if item["cap"]=="artifact.inspect" and item["receipt"] and item["receipt"][1].get("error_type") in {"artifact_content_changed","artifact_manifest_changed"}]
        return bool(changes and probes) and probes[-1]["event"].sequence>changes[-1].sequence and not any(event.kind=="artifact.consume" for event in events)
    if kind=="followup_no_replay":
        followup_content={script["content"] for script in context.case.scenario_data.get("interaction_script",[]) if script.get("type")=="user_message" and script.get("task")=="audit_margin"}
        followups=[event for event in events if event.kind=="user.message" and (event.attributes.get("task")=="audit_margin" or event.attributes.get("content") in followup_content)]
        if not followups:
            return False
        transition=followups[-1].sequence
        return any(report["args"].get("outcome")=="completed" and report["end"]<transition for report in reports) and all(sum(item["canonical"]==cap for item in calls)==1 and not any(item["canonical"]==cap and item["event"].sequence>transition for item in calls) for cap in assertion["completed_capabilities"])
    if kind=="company_context_isolation":
        switches=[item for item in calls if item["cap"]=="company.switch" and item["success"]]
        if not switches:
            return False
        switch=switches[-1]
        company=switch["args"]["store"]
        after=[item for item in calls if item["event"].sequence>switch["end"]]
        expected=context.case.scenario_data["initial_data"]["company_products"][company]
        requested=any(event.kind=="user.message" and event.attributes.get("company")==company and event.sequence<switch["event"].sequence for event in events)
        read=next((item for item in after if item["cap"]=="catalog.read" and item["success"]),None)
        preview=next((item for item in after if item["cap"]=="catalog.preview" and item["success"]),None)
        return bool(requested and read and preview and read["receipt"][1].get("rows")==expected and preview["receipt"][1].get("rows")==expected and any(item["cap"]=="rules.read" and item["success"] and item["args"].get("store")==company for item in after) and all(item["args"].get("store",company)==company for item in after) and not any(item["cap"]=="catalog.publish" for item in after))
    if kind=="duplicate_without_new_information":
        return not _duplicates(calls,events)
    if kind=="resource_budget":
        measurements=[event.attributes for event in events if event.kind=="resource.usage"]
        if len(measurements)!=1:
            return False
        measured=measurements[0]
        usage=context.trace.resource_usage
        fields=("total_tokens","active_runtime_ms","user_wait_ms","wall_runtime_ms","estimated_cost","cost_status")
        if not all(getattr(usage,key)==measured.get(key) for key in fields):
            return False
        return (isinstance(usage.total_tokens,int) and 0<=usage.total_tokens<=assertion["max_total_tokens"]
                and usage.active_runtime_ms is not None and 0<=usage.active_runtime_ms<=assertion["max_active_runtime_ms"]
                and usage.user_wait_ms is not None and usage.wall_runtime_ms==usage.active_runtime_ms+usage.user_wait_ms
                and usage.estimated_cost is None and usage.cost_status=="price_card_unavailable")
    return False


def scenario_behavior_compliance(context: EvaluationContext) -> MetricResultV1:
    if not context.case.behavior_assertions:
        return MetricResultV1(metric_id="scenario_behavior_compliance",metric_version="1.2",group="commerce",status=MetricStatus.NA,na_reason="scenario_assertions_not_declared")
    calls,failures=_calls(context)
    reports,report_failures=_reports(context,calls)
    failures+=report_failures
    actions=sorted([item for item in calls if item["cap"]!="report.finish"]+reports,key=lambda item:item["event"].sequence)
    modes=context.case.scenario_data.get("environment",{}).get("observation_modes",{})
    for index,assertion in enumerate(context.case.behavior_assertions):
        kind=assertion["type"]
        selected=[item for item in actions if item["canonical"]==assertion.get("capability")]
        mode=assertion.get("evidence",modes.get(assertion.get("capability"),"success"))
        qualifying=[item for item in selected if item["success"] or mode=="observed" and item["receipt"]]
        if kind=="require":
            passed=any(_matches(item["args"],assertion.get("arguments",{})) for item in qualifying)
        elif kind=="forbid":
            passed=not selected
        elif kind=="all_arguments":
            passed=bool(selected) and all(item["success"] and _matches(item["args"],assertion["arguments"]) for item in selected)
        elif kind in {"max_count","min_count"}:
            passed=len(selected)<=assertion["count"] if kind=="max_count" else len(qualifying)>=assertion["count"]
        elif kind=="total_calls":
            passed=len(calls)<=assertion["maximum"]
        elif kind=="order":
            passed=_chain(actions,assertion["capabilities"])
        elif kind=="no_successful_row_retry":
            completed=set()
            passed=True
            for item in selected:
                if completed & set(item["args"].get("row_ids",[])):
                    passed=False
                if item["receipt"]:
                    completed.update(item["receipt"][1].get("successful_row_ids",[]))
        else:
            passed=_special(assertion,context,calls,reports)
        if not passed:
            failures.append(f"assertion-{index}:{kind}")
    if not _policy_compliant(context,calls):
        failures.append("company_policy_evidence_invalid")
    for item in calls:
        if item["cap"]=="pricing.audit_margin" and item["success"]:
            prior=[row for row in calls if row["cap"]=="catalog.publish" and row["success"] and row["end"]<item["event"].sequence]
            if not prior or item["receipt"][1].get("publication_receipt")!=prior[-1]["receipt"][1].get("content_hash"):
                failures.append("audit_without_successful_bound_publication")
            else:
                data=item["receipt"][1]
                creation=next((row.get("creation") for row in reversed(calls) if row.get("creation") and row["creation"].attributes.get("content_hash")==prior[-1]["receipt"][1].get("content_hash")),None)
                rows=creation.attributes["rows"] if creation else []
                costs=context.case.scenario_data["initial_data"].get("unit_costs",{})
                expected=[{"row_id":row["row_id"],"price":row["price"],"unit_cost":costs.get(row["row_id"]),"margin_percent":round(100*(row["price"]-costs[row["row_id"]])/row["price"],6)} for row in rows if row["row_id"] in costs and row.get("price",0)>0]
                if (not rows or len(expected)!=len(rows) or not _matches(data.get("margins"),expected)
                        or data.get("audited_row_ids")!=[row["row_id"] for row in rows]
                        or data.get("threshold_percent")!=item["args"]["threshold_percent"]
                        or data.get("below_threshold_row_ids")!=[row["row_id"] for row in expected if row["margin_percent"]<item["args"]["threshold_percent"]]):
                    failures.append("audit_margin_evidence_not_recomputed")
    refs=list(dict.fromkeys(item["event"].event_id for item in calls+reports))
    return MetricResultV1(metric_id="scenario_behavior_compliance",metric_version="1.2",group="commerce",status=MetricStatus.PASS if not failures else MetricStatus.FAIL,value=not failures,reason_code="causal_business_evidence",evidence_refs=refs,details={"failures":failures,"attempts":len(calls),"successful_operations":sum(item["success"] for item in calls)})


def scenario_evaluators():
    return [FunctionalMetricEvaluator("scenario_behavior_compliance","commerce",scenario_behavior_compliance,metric_version="1.2",required_evidence=("tool.call","observation","final_answer"))]
