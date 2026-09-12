"""Compile public templates; project only candidate-visible task material."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from commerce_eval.contracts.models import EvalCaseV1
from commerce_eval.contracts.scenarios import CandidateInputV1, CapabilityBindingV1, ScenarioTemplateV1

from .bindings import encode_arguments
from .artifacts import read_artifact


def compile_scenario(template: ScenarioTemplateV1 | dict, bindings: list[CapabilityBindingV1 | dict] | None = None, assets: list[dict] | None = None) -> EvalCaseV1:
    template = ScenarioTemplateV1.model_validate(template).model_copy(deep=True)
    if template.contract_version == "1.2":
        return _compile_business_scenario(template, assets)
    bound = [CapabilityBindingV1.model_validate(b) for b in bindings] if bindings is not None else [CapabilityBindingV1(capability_id=c,tool_id=f"sandbox.{c}") for c in template.capabilities]
    by_capability = {b.capability_id:b for b in bound}
    if len(by_capability) != len(bound) or len({b.tool_id for b in bound}) != len(bound):
        raise ValueError("scenario_binding_ambiguous")
    optional = {"report.finish", *template.behavior_criteria["forbidden"]}
    equivalents = template.behavior_criteria.get("equivalent_capabilities", {})
    alternative_caps = {item["capability"] for items in equivalents.values() for item in items}
    missing = set(template.capabilities) - by_capability.keys() - optional - alternative_caps
    missing = {cap for cap in missing if not any(item["capability"] in by_capability for item in equivalents.get(cap, []))}
    if missing:
        raise ValueError("scenario_binding_missing:" + ",".join(sorted(missing)))
    for action in template.references["positive"]:
        if action["capability"] in by_capability:
            encode_arguments(by_capability[action["capability"]], action["arguments"])
    public_assets = [
        {"asset_id":"products","name":"products.json","media_type":"application/json","permitted":not template.environment.get("input_file_missing",False),"rows":template.initial_data["products"]},
        {"asset_id":"company-rules","name":"company-rules.json","media_type":"application/json","permitted":True,"content":template.rules},
        {"asset_id":"task-data","name":"task-data.json","media_type":"application/json","permitted":True,"content":{k:v for k,v in template.initial_data.items() if k != "products"}},
    ]
    replacements = deepcopy(assets or [])
    product_assets=[]
    for asset in replacements:
        if not isinstance(asset,dict):
            raise ValueError("scenario_asset_must_be_object")
        asset.setdefault("permitted",True)
        product = asset.get("kind")=="products" or asset.get("asset_id")=="products" or "rows" in asset
        if product and asset["permitted"] is True:
            rows=asset.get("rows")
            if rows is None and isinstance(asset.get("content"),str):
                media_type=asset.get("media_type","application/json")
                if media_type not in {"text/csv","application/json"}:
                    raise ValueError("scenario_product_format_unavailable")
                rows=read_artifact(asset["content"],"csv" if media_type=="text/csv" else "json")
            if not isinstance(rows,list) or not rows or not all(isinstance(row,dict) and isinstance(row.get("row_id"),str) for row in rows):
                raise ValueError("scenario_product_asset_invalid")
            if len({row["row_id"] for row in rows})!=len(rows):
                raise ValueError("scenario_product_row_id_duplicate")
            asset["rows"]=deepcopy(rows)
            asset["kind"]="products"
            product_assets.append(asset)
    if len(product_assets)>1:
        raise ValueError("scenario_product_assets_ambiguous")
    if product_assets:
        template.initial_data["products"]=deepcopy(product_assets[0]["rows"])
        public_assets=[asset for asset in public_assets if asset["asset_id"]!="products"]
    replacement_ids={asset.get("asset_id") for asset in replacements}
    if "company-rules" in replacement_ids:
        raise ValueError("pinned_company_rules_cannot_be_replaced")
    public_assets=[asset for asset in public_assets if asset["asset_id"] not in replacement_ids]+replacements
    template.initial_data["effective_asset_refs"]=[
        {key:asset[key] for key in ("asset_id","kind","version","checksum") if key in asset}
        for asset in public_assets if asset.get("permitted") is True
    ]
    requirements = deepcopy(template.artifact_requirements)
    if requirements:
        requirements.setdefault("expected_row_ids", [row["row_id"] for row in template.initial_data["products"]])
    return EvalCaseV1(
        contract_version="1.1",case_id=f"public-{template.scenario_id}",version=template.scenario_version,name=template.name,
        scenario_id=template.scenario_id,scenario_version=template.scenario_version,direction=template.direction,
        input={"message":template.public_task,"assets":public_assets},
        scenario_data=template.model_dump(mode="json"),behavior_assertions=deepcopy(template.behavior_criteria["assertions"]),
        capability_bindings=[b.model_dump(mode="json") for b in bound],artifact_requirements=requirements,
        allowed_tools=[b.tool_id for b in bound if b.capability_id not in template.behavior_criteria["forbidden"]],
        forbidden_tools=[by_capability[c].tool_id for c in template.behavior_criteria["forbidden"] if c in by_capability],
        gates=deepcopy(template.behavior_criteria["gates"]),tags=["public-bank","synthetic",template.direction],pack_id="commerce",
    )


def _compile_business_scenario(template, assets):
    from commerce_eval.business.bank import compile_business_template

    # Target tool bindings do not alter the business answer or dataset checksum.
    return compile_business_template(template, assets=assets)


_PRIVATE_KEYS = {"businessrequirements","requiredevidence","verifierid","verifierversion","gates","gate","script","scripts","interactionscript","conversation","dialogue","futuredialogue","futureturns","behaviorassertions","behaviorcriteria","scenario_data","scenariodata","capabilitybindings","artifactrequirements","outcomeassertions","factassertions","parameterexpectations","intents","answer","answers","answerkey","labels","defectlabels","evaluation","evaluator","groundtruth"}


def _public_value(value: Any) -> Any:
    if isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return value
        if isinstance(parsed, (dict, list)):
            return json.dumps(_public_value(parsed), ensure_ascii=True)
    if isinstance(value, list):
        return [_public_value(item) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized = "".join(c.lower() for c in str(key) if c.isalnum())
            if normalized in _PRIVATE_KEYS or normalized.startswith(("expected","reference","future","script")):
                continue
            result[key] = _public_value(item)
        return result
    return deepcopy(value)


def project_candidate_input(case: EvalCaseV1 | dict, turn: int = 0) -> CandidateInputV1:
    """`turn` is informational: runner must put the *current* message in input.

    Never select a future conversation item, even when a legacy case contains a
    complete evaluator script. Context is intentionally empty, not copied.
    """
    if not isinstance(turn, int) or isinstance(turn, bool) or turn < 0:
        raise ValueError("candidate_turn_invalid")
    raw = case.get("input", {}) if isinstance(case, dict) else case.input
    message = raw.get("message", raw.get("task", raw.get("prompt", "")))
    if not isinstance(message, str):
        message = ""
    assets = []
    for asset in raw.get("assets", []) if isinstance(raw.get("assets", []), list) else []:
        if not isinstance(asset, dict) or asset.get("permitted") is not True:
            continue
        assets.append(_public_value({key:asset[key] for key in ("asset_id","kind","version","checksum","name","media_type","content","rows") if key in asset}))
    return CandidateInputV1(message=message,assets=assets,context={})
