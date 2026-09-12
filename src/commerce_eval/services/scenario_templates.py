"""Compile an explicit selection into one immutable dataset, never a run."""

from commerce_eval.core import redact_recursive


def load_templates(template_version="0.2.0"):
    if template_version in {"0.3.0", "0.3.1"}:
        from commerce_eval.business.bank import load_business_templates

        return load_business_templates(template_version)
    if template_version != "0.2.0":
        raise ValueError("template_version_unavailable")
    from commerce_eval.scenarios import load_scenario_templates

    return load_scenario_templates()


def template_items(template_version="0.2.0"):
    return [redact_recursive(item.model_dump(mode="json"), max_depth=32, max_items=10000)
            for item in load_templates(template_version)]


def instantiate(repository, template_id, *, project_id, dataset_id, version, name=None,
                template_ids=None, bindings=None, assets=None, template_version="0.2.0"):
    from commerce_eval.scenarios import compile_scenario

    selected = template_ids if template_id == "bank" else [template_id]
    errors = []
    if not selected:
        errors.append({"field": "template_ids", "code": "template_selection_required"})
    if template_id != "bank" and template_ids is not None and template_ids != [template_id]:
        errors.append({"field": "template_ids", "code": "template_selection_mismatch"})
    if selected and len(selected) != len(set(selected)):
        errors.append({"field": "template_ids", "code": "template_selection_duplicate"})
    templates = {item.scenario_id: item for item in load_templates(template_version)}
    resolved_assets = None
    if assets is not None:
        resolved_assets = []
        for index, asset in enumerate(assets):
            try:
                if asset.get("project_id", project_id) != project_id:
                    raise ValueError("asset_project_mismatch")
                if "version" in asset:
                    saved = repository.get_asset(project_id, asset["kind"], asset["asset_id"], asset["version"])
                    resolved_assets.append({"asset_id": saved["asset_id"], "version": saved["version"],
                                            "checksum": saved["checksum"], "name": saved["name"],
                                            "media_type": "application/json", "permitted": True,
                                            "rows" if saved["kind"] == "products" else "content": saved["rows"]})
                else:
                    resolved_assets.append(redact_recursive(asset, max_depth=32, max_items=10000))
            except (ValueError, KeyError):
                errors.append({"field": f"assets.{index}", "code": "asset_reference_invalid"})
    cases = []
    for index, selected_id in enumerate(selected or []):
        if selected_id not in templates:
            errors.append({"field": f"template_ids.{index}", "code": "scenario_template_not_found"})
            continue
        try:
            cases.append(compile_scenario(templates[selected_id], bindings, resolved_assets))
        except (ValueError, KeyError, TypeError):
            errors.append({"field": f"template_ids.{index}", "code": "scenario_not_ready"})
    if errors:
        return {"status": "invalid", "readiness": {"ready": False, "errors": errors}, "errors": errors, "resources": []}
    with repository.transaction() as bound:
        bound.get_project(project_id)
        dataset = bound.save_dataset(project_id, dataset_id, version, name or "Commerce scenarios", cases)
    reference = {"project_id": project_id, "dataset_id": dataset_id, "version": version}
    return {**dataset, "status": "ready", "readiness": {"ready": True, "errors": []},
            "errors": [], "resources": [{"kind": "dataset", **reference}], "dataset": reference}
