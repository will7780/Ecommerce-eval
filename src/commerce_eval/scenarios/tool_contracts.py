"""Sandbox tool declarations compiled to actual field names and numeric units."""

from __future__ import annotations

from copy import deepcopy

from commerce_eval.contracts.models import EvalCaseV1, ToolContractV1
from commerce_eval.contracts.scenarios import CapabilityBindingV1


FIELDS = {
    "input_file":{"type":"string","minLength":1},
    "site":{"type":"string","enum":["DE","FR","ES"]},
    "quantity":{"type":"integer","minimum":1,"maximum":20},
    "margin_percent":{"type":"number","minimum":0,"exclusiveMaximum":100},
    "threshold_percent":{"type":"number","minimum":-100,"maximum":100},
    "minimum_margin_percent":{"type":"number","minimum":0,"maximum":100},
    "price":{"type":"number","exclusiveMinimum":0},
    "template":{"type":"string","enum":["primary","fallback"]},
    "capability":{"type":"string"}, "parameters":{"type":"object"},
    "store":{"type":"string","minLength":1},
    "limit":{"type":"integer","minimum":1,"maximum":100},
    "max_price":{"type":"number","exclusiveMinimum":0},
    "category":{"type":"string"},"source":{"type":"string"},
    "row_ids":{"type":"array","items":{"type":"string"},"minItems":1,"uniqueItems":True},
    "fields":{"type":"array","items":{"type":"string"},"minItems":1,"uniqueItems":True},
    "purpose":{"type":"string","enum":["risk","clarification"]},
    "action":{"type":"string"},"mode":{"type":"string"},"currency":{"type":"string","pattern":"^[A-Z]{3}$"},
    "format":{"type":"string","enum":["json","csv"]},
    "variant":{"type":"string","enum":["clean","corrupt"]},"tamper":{"type":"boolean"},
    "seed":{"type":"string"},"job_id":{"type":"string","minLength":1},
    "outcome":{"type":"string","enum":["completed","blocked","cancelled"]},
    **{key:{"type":"string","minLength":1} for key in ("artifact_id","version","content_hash","manifest_hash","rule_version","review_id")},
}
GENERATION_FIELDS=["input_file","store","site","category","limit","quantity","margin_percent","currency","format","template","rule_version"]

SPECS = {
    "catalog.generate_listing":(GENERATION_FIELDS,["input_file","store"]),
    "catalog.generate_alternative":(GENERATION_FIELDS,["input_file","store"]),
    "pricing.query":(["row_ids"],["row_ids"]),
    "pricing.update":(["row_ids","price"],["row_ids","price"]),
    "pricing.audit_margin":(["artifact_id","version","content_hash","manifest_hash","rule_version","review_id","threshold_percent"],["artifact_id","version","threshold_percent"]),
    "company.switch":(["store"],["store"]),
    "rules.override":(["minimum_margin_percent"],["minimum_margin_percent"]),
    "parameters.validate":(["capability","parameters"],["capability","parameters"]),
    "source.validate":(["input_file"],["input_file"]),
    "artifact.tamper":(["mode"],["mode"]),
    "artifact.inspect":([],[]),
    "rules.read":(["store"],["store"]),
    "workflow.plan":(["action"],["action"]),
    "catalog.read":(["store","site","source","limit","max_price","category"],["store"]),
    "catalog.search":(["store","source","limit","max_price","category"],["source"]),
    "catalog.preview":(["mode","site"],[]),
    "inventory.read":(["row_ids"],["row_ids"]),
    "artifact.prepare":(["currency","format","rule_version"],[]),
    "artifact.revise":(["variant","tamper"],["variant"]),
    "artifact.check":([],[]),"artifact.sample":(["seed"],["seed"]),"artifact.review":([],[]),
    "interaction.ask":(["fields","purpose"],["fields"]),
    "catalog.publish":(["artifact_id","version","content_hash","manifest_hash","rule_version","review_id"],["artifact_id","version","content_hash","manifest_hash","rule_version","review_id"]),
    "catalog.export":(["job_id"],["job_id"]),"job.status":(["job_id"],["job_id"]),
    "catalog.delete":(["row_ids"],[]),"inventory.write":(["row_ids"],[]),
    "report.finish":(["outcome"],["outcome"]),
}


def _insert_schema(root: dict, pointer: str, schema: dict, required: bool) -> None:
    parts = [part.replace("~1","/").replace("~0","~") for part in pointer[1:].split("/")] if pointer.startswith("/") else [pointer]
    current = root
    for index,part in enumerate(parts):
        current.setdefault("type","object")
        current.setdefault("properties",{})
        if required:
            required_fields=current.setdefault("required",[])
            if part not in required_fields:
                required_fields.append(part)
        if index==len(parts)-1:
            current["properties"][part]=schema
        else:
            current=current["properties"].setdefault(part,{"type":"object","properties":{},"additionalProperties":False})


def build_tool_contracts(case: EvalCaseV1) -> list[ToolContractV1]:
    contracts=[]
    for raw in case.capability_bindings:
        binding=CapabilityBindingV1.model_validate(raw)
        fields,required=SPECS.get(binding.capability_id,([],[]))
        input_schema={"type":"object","properties":{},"additionalProperties":False}
        for name in fields:
            schema=deepcopy(FIELDS[name])
            scale=binding.unit_scale.get(name,1)
            for constraint in ("minimum","maximum","exclusiveMinimum","exclusiveMaximum"):
                if constraint in schema:
                    schema[constraint]*=scale
            if schema.get("type")=="integer" and scale!=1:
                schema["type"]="number"
                schema["multipleOf"]=scale
            _insert_schema(input_schema,binding.argument_mapping.get(name,name),schema,name in required)
        write=binding.capability_id in {"catalog.publish","catalog.delete","inventory.write","pricing.update","rules.override"}
        contracts.append(ToolContractV1(tool_id=binding.tool_id,version="0.2.0",title=binding.capability_id,
            description="Synthetic sandbox capability: "+binding.capability_id,input_schema=input_schema,output_schema={"type":"object"},
            side_effect_class="local_write" if write or binding.capability_id.startswith(("artifact.","catalog.generate")) else "read",risk_level="L3" if write else "L1",
            confirmation_required=write,idempotent=not write,tags=["synthetic","reference_actor","capability:"+binding.capability_id]))
    return contracts


def capability_declarations(case: EvalCaseV1) -> list[dict]:
    """Frontend mappings come from the compiled declarations, never a fixed UI list."""
    contracts = {contract.tool_id:contract for contract in build_tool_contracts(case)}
    return [{"capability_id":raw["capability_id"],"tool_id":raw["tool_id"],
             "title":contracts[raw["tool_id"]].title,
             "input_schema":contracts[raw["tool_id"]].input_schema,
             "optional":raw["capability_id"]=="report.finish" or raw["tool_id"] in case.forbidden_tools,
             "event_alternative":"final_answer" if raw["capability_id"]=="report.finish" else None,
             "permitted":raw["tool_id"] not in case.forbidden_tools}
            for raw in case.capability_bindings]
