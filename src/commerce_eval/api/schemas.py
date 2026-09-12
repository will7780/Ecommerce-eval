"""REST request envelopes kept separate from versioned public contracts."""

from __future__ import annotations

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field

from commerce_eval.contracts import EvalCaseV1, ToolContractV1, TraceEnvelopeV1


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExperimentRetryCreate(ApiModel):
    allow_paid: bool = Field(default=False, strict=True)


class ProjectCreate(ApiModel):
    project_id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=4000)


class DatasetCreate(ApiModel):
    project_id: str
    dataset_id: str
    version: str
    name: str
    description: str = ""
    cases: List[EvalCaseV1]


class ToolContractSetCreate(ApiModel):
    project_id: str
    set_id: str
    version: str
    tools: List[ToolContractV1]


class EvaluatorSetCreate(ApiModel):
    project_id: str
    set_id: str
    version: str
    metric_ids: List[str]


class TraceBatchCreate(ApiModel):
    traces: List[TraceEnvelopeV1]


class AnnotationCreate(ApiModel):
    label: str
    value: Dict[str, Any] = Field(default_factory=dict)


class ImportFile(ApiModel):
    name: str = Field(min_length=1, max_length=500)
    content: str


class ImportOptions(ApiModel):
    id: str | None = None
    version: str | None = None
    name: str | None = None
    column_mapping: Dict[str, str] = Field(default_factory=dict)


class ImportPreviewCreate(ApiModel):
    project_id: str = Field(min_length=1, max_length=120)
    kind: Literal["trace", "dataset", "tool-contracts", "products", "rules", "target", "evaluator-set"]
    files: List[ImportFile]
    options: ImportOptions = Field(default_factory=ImportOptions)


class OnboardingCheckCreate(ApiModel):
    project_id: str
    target_id: str | None = None
    target_version: str | None = None
    definition: Dict[str, Any] | None = None
    dataset_id: str | None = None
    dataset_version: str | None = None
    template_ids: List[str] | None = None
    template_version: Literal["0.2.0", "0.3.0", "0.3.1"] = "0.3.0"


class EvaluationCreate(ApiModel):
    trace_id: str
    project_id: str | None = None
    dataset_id: str
    dataset_version: str
    case_id: str
    tool_contract_set_id: str
    tool_contract_version: str
    evaluator_set_id: str
    evaluator_set_version: str


class ScenarioInstantiateCreate(ApiModel):
    template_version: Literal["0.2.0", "0.3.0", "0.3.1"] = "0.2.0"
    project_id: str
    dataset_id: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=1, max_length=80)
    name: str | None = None
    template_ids: List[str] | None = None
    bindings: List[Dict[str, Any]] | None = None
    assets: List[Dict[str, Any]] | None = None


class OnboardingDemoCreate(ApiModel):
    bank_version: Literal["0.2.0", "0.3.0", "0.3.1"] = "0.2.0"
    project_id: str
    template_ids: List[str] | None = None
