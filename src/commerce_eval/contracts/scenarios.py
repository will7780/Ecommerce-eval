"""Public scenario and observable artifact contracts, independent of runtimes."""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import Field, model_serializer, model_validator

from .models import BusinessRequirementV1, ContractModel


class ModelInputSnapshotV1(ContractModel):
    contract_version: Literal["1.0", "1.1", "1.2"] = "1.1"
    snapshot_id: str = Field(min_length=1)
    model_call_id: str = Field(min_length=1)
    round: int = Field(ge=0)
    messages: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    source: str = Field(min_length=1)
    captured: bool = False
    truncated: bool = False
    redacted: bool = True
    omission_reason: str | None = None

    @model_validator(mode="after")
    def completeness(self) -> "ModelInputSnapshotV1":
        if (not self.captured or self.truncated) and not self.omission_reason:
            raise ValueError("snapshot_omission_reason_required")
        if any(not isinstance(m.get("role"), str) or "content" not in m for m in self.messages):
            raise ValueError("snapshot_role_and_content_required")
        return self


class CandidateInputV1(ContractModel):
    contract_version: Literal["1.0", "1.1", "1.2"] = "1.1"
    message: str
    assets: list[dict[str, Any]] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)


class CapabilityBindingV1(ContractModel):
    contract_version: Literal["1.0", "1.1", "1.2"] = "1.1"
    capability_id: str = Field(min_length=1)
    tool_id: str = Field(min_length=1)
    argument_mapping: dict[str, str] = Field(default_factory=dict)
    unit_scale: dict[str, float] = Field(default_factory=dict)
    evidence_mapping: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def mappings(self) -> "CapabilityBindingV1":
        for mapping in (self.argument_mapping, self.evidence_mapping):
            if any(not key or not value or value.startswith("//") for key, value in mapping.items()):
                raise ValueError("binding_invalid_pointer")
            paths = list(mapping.values())
            if len(set(paths)) != len(paths):
                raise ValueError("binding_duplicate_destination")
            if any(a.startswith(b + "/") for a in paths for b in paths if a != b):
                raise ValueError("binding_overlapping_destination")
        if any(not math.isfinite(v) or v <= 0 for v in self.unit_scale.values()):
            raise ValueError("binding_scale_must_be_positive_finite")
        if not set(self.unit_scale) <= set(self.argument_mapping):
            raise ValueError("binding_scale_requires_argument_mapping")
        return self


class ScenarioTemplateV1(ContractModel):
    contract_version: Literal["1.0", "1.1", "1.2"] = "1.1"
    scenario_id: str = Field(pattern=r"^[ICTPAMRS]0[1-4]$")
    scenario_version: str = "0.2.0"
    name: str = Field(min_length=1)
    direction: Literal["intention", "company_rules", "tool_workflow", "parameters", "artifacts", "multi_turn", "recovery", "safety"]
    public_task: str = Field(min_length=1)
    rules: list[dict[str, Any]]
    initial_data: dict[str, Any]
    environment: dict[str, Any]
    interaction_script: list[dict[str, Any]] = Field(default_factory=list)
    behavior_criteria: dict[str, Any]
    capabilities: list[str] = Field(min_length=1)
    references: dict[str, Any]
    provenance: dict[str, Any]
    artifact_requirements: dict[str, Any] = Field(default_factory=dict)
    business_requirements: list[BusinessRequirementV1] = Field(default_factory=list)

    @model_serializer(mode="wrap")
    def preserve_legacy_payload(self, handler):
        data = handler(self)
        if self.contract_version != "1.2":
            data.pop("business_requirements", None)
        return data

    @model_validator(mode="after")
    def public_material(self) -> "ScenarioTemplateV1":
        if self.provenance.get("kind") not in {"synthetic","existing_test_extraction","business_rule_extraction","new_exam_point"}:
            raise ValueError("public_bank_requires_declared_provenance")
        if not all({"scope", "version", "priority", "text"} <= r.keys() for r in self.rules):
            raise ValueError("rule_scope_version_priority_required")
        if not {"allowed_paths", "forbidden", "gates", "assertions"} <= self.behavior_criteria.keys():
            raise ValueError("behavior_criteria_incomplete")
        if self.references.get("actor") != "reference_actor":
            raise ValueError("reference_actor_label_required")
        if len(self.references.get("mutants", [])) < 3:
            raise ValueError("three_specific_mutants_required")
        return self


class ArtifactEvidenceV1(ContractModel):
    """Attributes of artifact.* events; omitted measurements are unavailable."""

    contract_version: Literal["1.0", "1.1", "1.2"] = "1.1"

    artifact_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    manifest_hash: str = Field(min_length=1)
    rule_version: str = Field(min_length=1)
    format: str | None = None
    rows: list[dict[str, Any]] | None = None
    errors: list[dict[str, Any]] | None = None
    sample_row_ids: list[str] | None = None
    checked_row_ids: list[str] | None = None
    review_id: str | None = None
    tool_call_id: str | None = None
    seed: str | None = None
    decision: Literal["approved", "rejected", "unavailable"] | None = None
    source: str | None = None
    captured: bool | None = None
    available: bool | None = None
    valid: bool | None = None
    omission_reason: str | None = None
    content: str | None = None
    manifest: list[dict[str, Any]] | None = None
    files: list[dict[str, Any]] | None = None
    receipt_id: str | None = None
