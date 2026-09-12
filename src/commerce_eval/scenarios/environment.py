"""Isolated deterministic tool environment. No target runtime or network calls."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from jsonschema import Draft202012Validator

from commerce_eval.contracts.models import EvalCaseV1, TraceEventV1
from commerce_eval.contracts.scenarios import CapabilityBindingV1

from .artifacts import DEFAULT_POLICY, artifact_evidence, canonical_json, digest, read_artifact, select_review_sample, validate_artifact
from .bindings import decode_arguments, encode_evidence
from .policy import effective_rule
from .tool_contracts import build_tool_contracts, FIELDS, GENERATION_FIELDS


@dataclass
class _Session:
    directory: TemporaryDirectory
    rows: list[dict]
    facts: dict
    events: list[TraceEventV1] = field(default_factory=list)
    receipts: dict[str, dict] = field(default_factory=dict)
    call_signatures: dict[str, str] = field(default_factory=dict)
    input_available: bool = True
    generation_valid: bool = False
    active_rule: dict | None = None
    loaded: list[dict] | None = None
    artifact: dict | None = None
    checked: dict | None = None
    sample: list[str] | None = None
    review: dict | None = None
    pending: dict | None = None
    script_index: int = 0
    approval: str | None = None
    published: list[dict] = field(default_factory=list)
    inventory_done: set[str] = field(default_factory=set)
    inventory_failed: bool = False
    jobs: dict[str, dict] = field(default_factory=dict)
    observed_jobs: set[str] = field(default_factory=set)
    attempts: int = 0
    final: dict = field(default_factory=dict)


class ScenarioEnvironment:
    def __init__(self, case: EvalCaseV1, *, root: str | Path | None = None):
        self.case = case.model_copy(deep=True)
        self.template = deepcopy(case.scenario_data)
        self.config = self.template["environment"]
        self.policy = {**DEFAULT_POLICY, **case.artifact_requirements.get("policy", {})}
        self.bindings = {b.tool_id:b for b in (CapabilityBindingV1.model_validate(row) for row in case.capability_bindings)}
        self.contracts = {tool.tool_id:tool for tool in build_tool_contracts(case)}
        self.root = root
        self.sessions: dict[str, _Session] = {}

    def _session(self, session_id: str) -> _Session:
        if session_id not in self.sessions:
            self.sessions[session_id] = _Session(TemporaryDirectory(prefix="commerce-scenario-",dir=self.root),deepcopy(self.template["initial_data"]["products"]),deepcopy(self.template["initial_data"]["facts"]))
            state = self.sessions[session_id]
            state.input_available = not self.config.get("input_file_missing",False)
            (Path(state.directory.name)/"inputs").mkdir()
            (Path(state.directory.name)/"artifacts").mkdir()
            if state.facts.get("previous_scope"):
                self._event(state,"user.message",{"scope":state.facts["previous_scope"],"phase":"previous","source":"scenario_harness"})
                self._event(state,"user.message",{"scope":state.facts["current_scope"],"phase":"current","source":"scenario_harness"})
            if state.input_available:
                (Path(state.directory.name)/"inputs"/"products.json").write_text(canonical_json(state.rows),encoding="utf-8")
        return self.sessions[session_id]

    def _event(self, state: _Session, kind: str, attributes: dict, *, status: str = "ok", name: str | None = None, event_id: str | None = None) -> TraceEventV1:
        sequence = len(state.events)
        event = TraceEventV1(event_id=event_id or f"event-{sequence}",sequence=sequence,kind=kind,name=name,status=status,attributes=deepcopy(attributes))
        state.events.append(event)
        return event

    def record_decision(self, session_id: str, observation_id: str, action: str) -> None:
        state=self._session(session_id)
        if not any(event.event_id==observation_id and event.kind=="observation" for event in state.events):
            raise ValueError("decision_observation_missing")
        self._event(state,"model.decision",{"action":action,"observation_id":observation_id,"source":"observable_action_summary"})

    def events(self, session_id: str) -> list[TraceEventV1]:
        return deepcopy(self._session(session_id).events)

    def state(self, session_id: str) -> dict:
        state = self._session(session_id)
        binding = {k:state.artifact[k] for k in ("artifact_id","version","content_hash","manifest_hash","rule_version")} if state.artifact else {}
        if state.review:
            binding["review_id"] = state.review["review_id"]
        return {"facts":deepcopy(state.facts),"published":deepcopy(state.published),"jobs":deepcopy(state.jobs),"final":deepcopy(state.final),"pending":deepcopy(state.pending),"artifact_binding":binding,"script_index":state.script_index}

    def materialized_files(self, session_id: str) -> list[Path]:
        """Local inspection only; paths are never emitted in public traces."""
        return sorted((Path(self._session(session_id).directory.name)/"artifacts").iterdir())

    def close(self) -> None:
        for state in self.sessions.values():
            state.directory.cleanup()
        self.sessions.clear()

    def __enter__(self) -> "ScenarioEnvironment":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def reset(self, session_id: str) -> None:
        state = self.sessions.pop(session_id, None)
        if state:
            state.directory.cleanup()

    def execute(self, session_id: str, call: dict) -> dict:
        state = self._session(session_id)
        call_id = str(call.get("tool_call_id") or f"call-{state.attempts}")
        signature = canonical_json({"tool_id":call.get("tool_id",call.get("name","")),"arguments":call.get("arguments",{})})
        if call_id in state.receipts:
            if signature != state.call_signatures[call_id]:
                return {"status":"error","error_type":"tool_call_id_reused_with_different_arguments","tool_call_id":call_id}
            return deepcopy(state.receipts[call_id])
        state.call_signatures[call_id] = signature
        state.attempts += 1
        tool_id = str(call.get("tool_id", call.get("name", "")))
        actual = call.get("arguments", {})
        self._event(state,"tool.call",{"tool_id":tool_id,"arguments":actual},name=tool_id,event_id=call_id)
        binding = self.bindings.get(tool_id)
        try:
            if not isinstance(actual, dict):
                raise ValueError("invalid_arguments")
            if state.pending:
                raise ValueError("interaction_pending")
            if not binding:
                raise ValueError("unsupported_capability")
            if state.attempts > self.config.get("max_calls", 1000):
                raise ValueError("call_budget_exceeded")
            if binding.capability_id in {"artifact.prepare","artifact.revise","catalog.generate_listing","catalog.generate_alternative"}:
                state.generation_valid = False
                state.review = None
                state.approval = None
            if list(Draft202012Validator(self.contracts[tool_id].input_schema).iter_errors(actual)):
                raise ValueError("invalid_arguments")
            arguments = decode_arguments(binding, actual)
            if arguments.get("site") and state.facts.get("site") and arguments["site"]!=state.facts["site"]:
                raise ValueError("corrected_site_conflict")
            receipt = self._dispatch(state,binding.capability_id,arguments,call_id)
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            receipt = {"status":"error","error_type":str(exc) if isinstance(exc, ValueError) else "invalid_arguments"}
        if receipt.get("actual_execution",True) and (receipt["status"] in {"ok","partial","timeout"} or receipt.get("error_type") in {"generation_failed","source_unavailable"}):
            self._event(state,"tool.execute",{"tool_call_id":call_id,"execution_mode":"sandbox"},status="ok" if receipt["status"]=="ok" else "error")
        receipt = {**receipt,"tool_call_id":call_id,"receipt_id":f"receipt-{state.attempts}"}
        self._event(state,"observation",{"tool_call_id":call_id,"tool_id":tool_id,"result":encode_evidence(binding,receipt) if binding else receipt},status="ok" if receipt["status"] in {"ok","pending"} else "error")
        state.receipts[call_id] = deepcopy(receipt)
        return deepcopy(receipt)

    def _source_rows(self, state: _Session) -> list[dict]:
        path=Path(state.directory.name)/"inputs"/"products.json"
        if not state.input_available or not path.is_file() or path.is_symlink():
            raise ValueError("input_file_missing")
        return read_artifact(path.read_text(encoding="utf-8"),"json")

    def _current_artifact(self, state: _Session) -> dict:
        if not state.artifact:
            raise ValueError("artifact_missing")
        data = deepcopy(state.artifact)
        artifact_dir = Path(state.directory.name)/"artifacts"
        if sorted(path.name for path in artifact_dir.iterdir())!=sorted(item["name"] for item in data["manifest"]):
            raise ValueError("artifact_manifest_changed")
        path = artifact_dir / f"catalog.{data['format']}"
        content = path.read_bytes().decode("utf-8")
        if digest(content) != data["content_hash"]:
            raise ValueError("artifact_content_changed")
        data["rows"] = read_artifact(content,data["format"])
        return data

    def _write_artifact(self, state: _Session, rows: list[dict], version: str, format: str, call_id: str) -> dict:
        data = artifact_evidence(rows,version=version,format=format,policy=self._policy(state))
        data["source"] = str(state.facts.get("store"))+":products"
        if state.artifact and state.artifact["format"]!=format:
            (Path(state.directory.name)/"artifacts"/f"catalog.{state.artifact['format']}").unlink(missing_ok=True)
        (Path(state.directory.name) / "artifacts" / f"catalog.{format}").write_bytes(data["content"].encode("utf-8"))
        state.artifact = data
        state.generation_valid = True
        state.checked = state.sample = state.review = None
        state.approval = None
        self._event(state,"artifact.created",{**data,"tool_call_id":call_id})
        return {"status":"ok","artifact_id":data["artifact_id"],"version":version,"content_hash":data["content_hash"],"manifest_hash":data["manifest_hash"],"rule_version":data["rule_version"]}

    def materialized_files_for_state(self,state):
        return list((Path(state.directory.name)/"artifacts").iterdir())

    def _policy(self,state):
        rule=effective_rule(self.template["rules"],state.facts.get("store"))
        return {**self.policy,**(rule["policy"] if rule else {})}

    def _dispatch(self, state: _Session, capability: str, args: dict, call_id: str) -> dict:
        if capability == "rules.read":
            if args.get("store") != state.facts.get("store"):
                raise ValueError("scope_denied")
            if not self.config.get("rules_available",True):
                raise ValueError("applicable_policy_missing")
            state.active_rule=effective_rule(self.template["rules"],state.facts.get("store"))
            if not state.active_rule:
                raise ValueError("applicable_policy_missing")
            return {"status":"ok","rules":deepcopy(self.template["rules"]),"effective_rule":state.active_rule}
        if capability == "workflow.plan":
            return {"status":"ok","action":args.get("action"),"healthy":self.config.get("healthy",True),"primary_available":not self.config.get("primary_failure",False),"mirror_available":not self.config.get("mirror_failure",False)}
        if capability in {"catalog.read","catalog.search"}:
            if capability == "catalog.read":
                if args.get("store") != state.facts.get("store"):
                    raise ValueError("scope_denied")
                if (self.config.get("primary_failure") and args.get("source","primary")!="mirror") or not self.config.get("healthy",True) or args.get("source")=="mirror" and self.config.get("mirror_failure"):
                    raise ValueError("source_unavailable")
            elif args.get("source") not in {"mirror","index","suggestions"} or (args.get("source") == "mirror" and self.config.get("mirror_failure")):
                raise ValueError("source_unavailable")
            limit = args.get("limit",20)
            if not isinstance(limit,int) or isinstance(limit,bool) or not 1 <= limit <= 100:
                raise ValueError("invalid_arguments")
            ceiling = args.get("max_price",float("inf"))
            if not isinstance(ceiling,(int,float)) or isinstance(ceiling,bool) or ceiling <= 0:
                raise ValueError("invalid_arguments")
            state.rows=self._source_rows(state)
            rows = [r for r in state.rows if r["price"] <= ceiling and (not args.get("category") or r["category"]==args["category"])]
            state.loaded = deepcopy(rows[:limit])
            return {"status":"ok","rows":state.loaded,"store":state.facts.get("store"),"source":args.get("source","primary"),"suggested_prices":self.template["initial_data"]["suggested_prices"] if args.get("source")=="suggestions" else {}}
        if capability == "catalog.preview":
            if state.loaded is None:
                raise ValueError("dependency_missing")
            return {"status":"ok","rows":state.loaded,"mode":args.get("mode","list"),"inventory":sorted(state.inventory_done)}
        if capability == "inventory.read":
            if state.loaded is None:
                raise ValueError("dependency_missing")
            ids = args.get("row_ids")
            if not isinstance(ids,list) or not ids or any(rid not in {r["row_id"] for r in state.loaded} for rid in ids):
                raise ValueError("invalid_arguments")
            failed = ["row20"] if self.config.get("partial_inventory_failure") and not state.inventory_failed and "row20" in ids else []
            state.inventory_failed |= bool(failed)
            succeeded = [rid for rid in ids if rid not in failed]
            state.inventory_done.update(succeeded)
            return {"status":"partial" if failed else "ok","successful_row_ids":succeeded,"failed_row_ids":failed,"stock":{r["row_id"]:r["stock"] for r in state.rows if r["row_id"] in succeeded}}
        if capability in {"artifact.prepare","catalog.generate_listing","catalog.generate_alternative"}:
            if not self.config.get("healthy",True) or not self.config.get("rules_available",True):
                raise ValueError("preflight_unavailable")
            if args.get("store",state.facts.get("store"))!=state.facts.get("store"):
                raise ValueError("scope_denied")
            if self.config.get("policy_read_required") and not state.active_rule:
                raise ValueError("company_policy_not_loaded")
            source=args.get("input_file","products")
            if source!="products" or not state.input_available:
                raise ValueError("input_file_missing")
            if self.config.get("generation_failure") or (self.config.get("primary_template_failure") and args.get("template")=="primary"):
                raise ValueError("generation_failed")
            if self.config.get("generation_outcome") in {"simulated","empty"}:
                return {"status":"simulated" if self.config["generation_outcome"]=="simulated" else "ok","artifact_id":None,"actual_execution":False}
            rows=self._source_rows(state)
            if state.loaded is not None:
                selected={row["row_id"] for row in state.loaded}
                rows=[row for row in rows if row.get("row_id") in selected]
            rows=[row for row in rows if not args.get("category") or row["category"]==args["category"]]
            rows=rows[:args.get("quantity",args.get("limit",20))]
            if self.config.get("all_rows_anomalous") or not validate_artifact(rows,self._policy(state))["valid"]:
                if not self.config.get("variant")=="corrupt":
                    raise ValueError("source_validation_failed")
            policy=self._policy(state)
            margin=args.get("margin_percent",max(15,policy.get("minimum_margin_percent",15)))
            if margin<policy.get("minimum_margin_percent",15) or args.get("currency",policy["currency"])!=policy["currency"] or args.get("rule_version",policy["rule_version"])!=policy["rule_version"]:
                raise ValueError("company_mandatory_rule_conflict")
            state.loaded=deepcopy(rows)
            version = str(int(state.artifact["version"])+1) if state.artifact else "1"
            return {**self._write_artifact(state,rows,version,args.get("format","json"),call_id),"margin_percent":margin,"site":args.get("site"),"source_file":source}
        if capability == "artifact.revise":
            current = self._current_artifact(state)
            rows = deepcopy(current["rows"])
            if args.get("variant","clean")=="clean":
                for row in rows:
                    row["currency"]=self._policy(state)["currency"]
                    if not row.get("sku"):
                        row["sku"]="REPAIRED-"+row["row_id"].upper()
            elif args["variant"]=="corrupt":
                for row in rows:
                    if row["row_id"]=="row17":
                        row["currency"]="USD"
                    if row["row_id"]=="row20":
                        row["sku"]=""
            if args.get("tamper"):
                rows[0]["price"] += 1
            version = current["version"] if args.get("tamper") else str(int(current["version"])+1)
            return self._write_artifact(state,rows,version,current["format"],call_id)
        if capability in {"artifact.check","artifact.sample","artifact.review"}:
            data = self._current_artifact(state)
            validation = validate_artifact(data["rows"],self._policy(state))
            if capability == "artifact.check":
                state.checked = validation
                self._event(state,"artifact.check",{**data,**{k:v for k,v in validation.items() if k != "row_count"},"tool_call_id":call_id})
                return {"status":"ok","validation":validation}
            if not state.checked:
                raise ValueError("full_check_required")
            if capability == "artifact.sample":
                seed = str(args.get("seed","bank-v2"))
                state.sample = select_review_sample(data["rows"],validation["errors"],seed)
                self._event(state,"artifact.sample",{**data,"sample_row_ids":state.sample,"errors":validation["errors"],"seed":seed,"tool_call_id":call_id})
                return {"status":"ok","sample_row_ids":state.sample}
            if state.sample is None:
                raise ValueError("review_sample_required")
            review_id = f"review-{state.script_index+1}"
            state.pending = {"type":"artifact_review","interaction_id":f"interaction-{len(state.events)}","review_id":review_id,"artifact":data,"tool_call_id":call_id}
            self._event(state,"interaction.request",{"type":"confirmation","confirmation_kind":"artifact","interaction_id":state.pending["interaction_id"],"review_id":review_id,**{k:data[k] for k in ("artifact_id","version","content_hash","manifest_hash","rule_version")}})
            return {"status":"pending","interaction_id":state.pending["interaction_id"],"review_id":review_id}
        if capability == "interaction.ask":
            fields = args.get("fields")
            if not isinstance(fields,list) or not fields:
                raise ValueError("clarification_fields_required")
            kind = "confirmation" if args.get("purpose")=="risk" else "clarification"
            state.pending = {"type":kind,"fields":fields,"interaction_id":f"interaction-{len(state.events)}"}
            self._event(state,"interaction.request",deepcopy(state.pending))
            return {"status":"pending","interaction_id":state.pending["interaction_id"]}
        if capability == "catalog.publish":
            data = self._current_artifact(state)
            if not state.generation_valid:
                raise ValueError("latest_generation_not_successful")
            if not state.review or state.review.get("decision") != "approved" or state.review["content_hash"] != data["content_hash"]:
                raise ValueError("approved_revision_required")
            if not validate_artifact(data["rows"],self._policy(state))["valid"]:
                raise ValueError("artifact_invalid")
            if self.config.get("risk_required") and state.approval != "approved":
                raise ValueError("risk_approval_required")
            if state.published:
                raise ValueError("publication_already_completed")
            # Bind the physical bytes at the actual consuming call, not a flag.
            binding = {k:data[k] for k in ("artifact_id","version","content_hash","manifest_hash","rule_version")}
            binding["review_id"] = state.review["review_id"]
            for key, value in binding.items():
                if args.get(key) != value:
                    raise ValueError("execution_binding_mismatch")
            state.published.append(binding)
            self._event(state,"artifact.consume",{**data,"review_id":state.review["review_id"],"tool_call_id":call_id,"receipt_id":f"receipt-{state.attempts}"})
            return {"status":"ok","published_rows":len(data["rows"]),**binding}
        if capability=="source.validate":
            if args["input_file"]!="products" or not state.input_available:
                raise ValueError("input_file_missing")
            rows=self._source_rows(state)
            validation=validate_artifact(rows,self._policy(state))
            return {"status":"ok","validation":validation,"rows":rows}
        if capability=="parameters.validate":
            schema={"type":"object","properties":{key:FIELDS[key] for key in GENERATION_FIELDS},"required":["input_file","store"],"additionalProperties":False}
            errors=[{"path":list(error.path),"validator":error.validator} for error in Draft202012Validator(schema).iter_errors(args["parameters"])]
            return {"status":"ok","errors":errors,"parameters":args["parameters"],"executed":False}
        if capability=="pricing.query":
            selected=[row for row in state.rows if row["row_id"] in args["row_ids"]]
            return {"status":"ok","rows":selected,"suggested_prices":self.template["initial_data"]["suggested_prices"]}
        if capability=="pricing.audit_margin":
            if not state.published or not state.generation_valid:
                raise ValueError("successful_publication_required")
            published=state.published[-1]
            if any(args.get(key)!=published[key] for key in ("artifact_id","version")):
                raise ValueError("publication_binding_mismatch")
            rows=self._current_artifact(state)["rows"]
            costs=self.template["initial_data"]["unit_costs"]
            margins=[{"row_id":row["row_id"],"price":row["price"],"unit_cost":costs[row["row_id"]],"margin_percent":round(100*(row["price"]-costs[row["row_id"]])/row["price"],6)} for row in rows]
            return {"status":"ok","artifact_id":published["artifact_id"],"version":published["version"],"audited_row_ids":[row["row_id"] for row in rows],"margins":margins,"below_threshold_row_ids":[row["row_id"] for row in margins if row["margin_percent"]<args["threshold_percent"]],"threshold_percent":args["threshold_percent"],"publication_receipt":published["content_hash"]}
        if capability=="company.switch":
            if args["store"] not in self.config.get("companies",[]):
                raise ValueError("company_not_authorized")
            if state.facts.get("next_company")!=args["store"]:
                raise ValueError("company_switch_not_requested")
            previous=state.facts.get("store")
            state.rows=deepcopy(self.template["initial_data"]["company_products"][args["store"]])
            (Path(state.directory.name)/"inputs"/"products.json").write_text(canonical_json(state.rows),encoding="utf-8")
            for path in self.materialized_files_for_state(state):
                path.unlink()
            state.facts={"store":args["store"]}
            state.loaded=state.artifact=state.checked=state.sample=state.review=state.active_rule=None
            state.approval=None
            state.generation_valid=False
            state.inventory_done.clear()
            state.published=[]
            self._event(state,"company.changed",{"previous_company":previous,"company":args["store"],"authorization":"cleared","active_artifact":None})
            return {"status":"ok","company":args["store"],"previous_company":previous}
        if capability=="artifact.tamper":
            current=self._current_artifact(state)
            directory=Path(state.directory.name)/"artifacts"
            if args["mode"]=="content":
                rows=deepcopy(current["rows"])
                rows[0]["price"]+=1
                changed=artifact_evidence(rows,version=current["version"],format=current["format"],policy=self._policy(state))
                (directory/f"catalog.{current['format']}").write_text(changed["content"],encoding="utf-8")
            elif args["mode"]=="add":
                (directory/"added.json").write_text("[]",encoding="utf-8")
            elif args["mode"]=="remove":
                (directory/f"catalog.{current['format']}").unlink()
            else:
                raise ValueError("invalid_tamper_mode")
            state.generation_valid=False
            state.review=None
            state.approval=None
            self._event(state,"artifact.changed",{**current,"source":"post_review_integrity_change"})
            return {"status":"ok","changed":True,"mode":args["mode"]}
        if capability=="artifact.inspect":
            data=self._current_artifact(state)
            return {"status":"ok","content_hash":data["content_hash"],"manifest_hash":data["manifest_hash"]}
        if capability == "catalog.export":
            if state.loaded is None:
                raise ValueError("dependency_missing")
            job_id = args["job_id"]
            state.jobs.setdefault(job_id,{"status":"completed","row_count":len(state.loaded)})
            return {"status":"timeout" if self.config.get("export_timeout") else "ok","job_id":job_id}
        if capability == "job.status":
            job_id = args["job_id"]
            if job_id not in state.jobs:
                raise ValueError("job_not_found")
            state.observed_jobs.add(job_id)
            return {"status":"ok","job_id":job_id,"job":state.jobs[job_id]}
        if capability == "report.finish":
            outcome = args.get("outcome")
            if outcome not in {"completed","blocked","cancelled"}:
                raise ValueError("invalid_outcome")
            if outcome=="completed" and (state.loaded is None and state.artifact is None or state.jobs and not state.observed_jobs):
                raise ValueError("completion_evidence_missing")
            state.final = {"outcome":outcome,"published_count":len(state.published),"job_count":len(state.jobs)}
            return {"status":"ok",**state.final}
        if capability in {"catalog.delete","inventory.write","pricing.update","rules.override"}:
            raise ValueError("write_not_authorized")
        raise ValueError("unsupported_capability")

    def deliver_user_message(self, session_id: str, content: str) -> dict:
        """Trusted harness turn delivery, distinct from a pending interaction."""
        state=self._session(session_id)
        scripts=self.template.get("interaction_script",[])
        if state.pending or state.final.get("outcome")!="completed" or state.script_index>=len(scripts):
            raise ValueError("user_message_not_ready")
        script=scripts[state.script_index]
        if script.get("type")!="user_message" or content!=script.get("content"):
            raise ValueError("user_message_mismatch")
        self._event(state,"user.message",{key:deepcopy(value) for key,value in script.items() if key!="type"})
        state.script_index+=1
        state.final={}
        return {"status":"ok","task":script.get("task")}

    def respond(self, session_id: str, interaction_id: str, response: dict) -> dict:
        """Trusted harness input; never called implicitly by execute()."""
        state = self._session(session_id)
        pending = state.pending
        if not pending or pending["interaction_id"] != interaction_id:
            raise ValueError("pending_interaction_mismatch")
        scripts = self.template.get("interaction_script",[])
        if state.script_index >= len(scripts):
            raise ValueError("script_exhausted")
        script = scripts[state.script_index]
        if script["type"] != pending["type"] or set(script.get("fields",[])) != set(pending.get("fields",[])) or response != script["response"]:
            self._event(state,"interaction.resume_rejected",{"interaction_id":interaction_id,"reason":"resume_payload_mismatch","executed":False},status="blocked")
            raise ValueError("script_response_mismatch")
        event_data = {"interaction_id":interaction_id,"type":pending["type"],"response":deepcopy(response),"source":"scenario_harness"}
        if pending["type"]=="artifact_review":
            data = self._current_artifact(state)
            if data["content_hash"] != pending["artifact"]["content_hash"]:
                raise ValueError("review_revision_changed")
            event_data.update({k:data[k] for k in ("artifact_id","version","content_hash","manifest_hash","rule_version")})
            event_data.update(review_id=pending["review_id"],decision=response["decision"])
            self._event(state,"interaction.response",event_data)
            review = {**data,"review_id":pending["review_id"],"decision":response["decision"],"tool_call_id":pending["tool_call_id"],"sample_row_ids":state.sample}
            state.review = review
            self._event(state,"artifact.review",review)
        else:
            event_data.update(response)
            self._event(state,"interaction.response",event_data)
            if pending["type"]=="confirmation":
                state.approval = response["decision"]
            else:
                state.facts.update(deepcopy(response))
                if response.get("input_file")=="products":
                    state.input_available=True
                    (Path(state.directory.name)/"inputs"/"products.json").write_text(canonical_json(state.rows),encoding="utf-8")
                if response.get("next_company"):
                    self._event(state,"user.message",{"content":"Switch company to "+response["next_company"],"company":response["next_company"],"source":"scenario_harness"})
                if response.get("next_task"):
                    self._event(state,"user.message",{"content":"New task: "+response["next_task"],"task":response["next_task"],"threshold_percent":response.get("threshold_percent")})
        state.script_index += 1
        state.pending = None
        return {"status":"ok","interaction_id":interaction_id}
