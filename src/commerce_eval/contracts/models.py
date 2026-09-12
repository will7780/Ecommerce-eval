"""Versioned, framework-neutral wire contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, Dict, List, Literal, Optional

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

CONTRACT_VERSION = "1.0"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    AWAITING_INPUT = "awaiting_input"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class EventStatus(str, Enum):
    OK = "ok"
    ERROR = "error"
    BLOCKED = "blocked"
    PENDING = "pending"
    SKIPPED = "skipped"


class MetricStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NA = "na"
    ERROR = "error"


class ExecutionMode(str, Enum):
    DRY_RUN = "dry_run"
    SANDBOX = "sandbox"


class RiskLevel(str, Enum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"
    L5 = "L5"


class SideEffectClass(str, Enum):
    NONE = "none"
    READ = "read"
    LOCAL_WRITE = "local_write"
    EXTERNAL_WRITE = "external_write"


class ResourceUsageV1(ContractModel):
    agent_llm_calls: Optional[int] = Field(default=None, ge=0)
    judge_llm_calls: Optional[int] = Field(default=None, ge=0)
    tool_calls: Optional[int] = Field(default=None, ge=0)
    agent_prompt_tokens: Optional[int] = Field(default=None, ge=0)
    agent_completion_tokens: Optional[int] = Field(default=None, ge=0)
    agent_total_tokens: Optional[int] = Field(default=None, ge=0)
    agent_reasoning_tokens: Optional[int] = Field(default=None, ge=0)
    agent_cache_hit_tokens: Optional[int] = Field(default=None, ge=0)
    agent_cache_miss_tokens: Optional[int] = Field(default=None, ge=0)
    judge_prompt_tokens: Optional[int] = Field(default=None, ge=0)
    judge_completion_tokens: Optional[int] = Field(default=None, ge=0)
    judge_total_tokens: Optional[int] = Field(default=None, ge=0)
    judge_reasoning_tokens: Optional[int] = Field(default=None, ge=0)
    judge_cache_hit_tokens: Optional[int] = Field(default=None, ge=0)
    judge_cache_miss_tokens: Optional[int] = Field(default=None, ge=0)
    prompt_tokens: Optional[int] = Field(default=None, ge=0)
    completion_tokens: Optional[int] = Field(default=None, ge=0)
    total_tokens: Optional[int] = Field(default=None, ge=0)
    reasoning_tokens: Optional[int] = Field(default=None, ge=0)
    cache_hit_tokens: Optional[int] = Field(default=None, ge=0)
    cache_miss_tokens: Optional[int] = Field(default=None, ge=0)
    agent_llm_latency_ms: Optional[float] = Field(default=None, ge=0)
    judge_llm_latency_ms: Optional[float] = Field(default=None, ge=0)
    tool_latency_ms: Optional[float] = Field(default=None, ge=0)
    active_runtime_ms: Optional[float] = Field(default=None, ge=0)
    wall_runtime_ms: Optional[float] = Field(default=None, ge=0)
    user_wait_ms: Optional[float] = Field(default=None, ge=0)
    estimated_cost: Optional[float] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, max_length=8)
    price_card_version: Optional[str] = Field(default=None, max_length=80)
    cost_status: Optional[str] = Field(default=None, max_length=120)


class TraceEventV1(ContractModel):
    contract_version: Literal["1.0", "1.1", "1.2"] = CONTRACT_VERSION
    event_id: str = Field(min_length=1, max_length=160)
    parent_event_id: Optional[str] = Field(default=None, max_length=160)
    sequence: int = Field(ge=0)
    kind: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    name: Optional[str] = Field(default=None, max_length=240)
    status: EventStatus = EventStatus.OK
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)
    evidence_refs: List[str] = Field(default_factory=list, max_length=128)

    @model_validator(mode="after")
    def validate_times(self) -> "TraceEventV1":
        if self.started_at and self.ended_at and self.ended_at < self.started_at:
            raise ValueError("event_ended_before_started")
        return self


class TraceEnvelopeV1(ContractModel):
    contract_version: Literal["1.0", "1.1", "1.2"] = CONTRACT_VERSION
    tool_contract_set_id: Optional[str] = Field(default=None, max_length=160)
    trace_id: str = Field(min_length=1, max_length=160)
    project_id: str = Field(min_length=1, max_length=120)
    target_id: str = Field(min_length=1, max_length=120)
    target_version: str = Field(min_length=1, max_length=80)
    tool_contract_version: Optional[str] = Field(default=None, max_length=80)
    dataset_version: Optional[str] = Field(default=None, max_length=80)
    evaluator_set_version: Optional[str] = Field(default=None, max_length=80)
    model_config_hash: Optional[str] = Field(default=None, max_length=128)
    experiment_id: Optional[str] = Field(default=None, max_length=160)
    case_id: Optional[str] = Field(default=None, max_length=160)
    repetition: int = Field(default=1, ge=1)
    started_at: datetime = Field(default_factory=utc_now)
    ended_at: Optional[datetime] = None
    status: RunStatus = RunStatus.COMPLETED
    input: Dict[str, Any] = Field(default_factory=dict)
    output: Dict[str, Any] = Field(default_factory=dict)
    resource_usage: ResourceUsageV1 = Field(default_factory=ResourceUsageV1)
    tags: Dict[str, str] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    events: List[TraceEventV1] = Field(default_factory=list, max_length=10000)

    @model_validator(mode="after")
    def validate_envelope(self) -> "TraceEnvelopeV1":
        if self.ended_at and self.ended_at < self.started_at:
            raise ValueError("trace_ended_before_started")
        sequences = [event.sequence for event in self.events]
        if len(sequences) != len(set(sequences)):
            raise ValueError("trace_event_sequence_duplicate")
        event_ids = [event.event_id for event in self.events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("trace_event_id_duplicate")
        return self


class FailureContractV1(ContractModel):
    error_type: str = Field(min_length=1, max_length=100)
    retryable: bool = False
    description: Optional[str] = Field(default=None, max_length=500)


class ToolContractV1(ContractModel):
    contract_version: Literal["1.0", "1.1", "1.2"] = CONTRACT_VERSION
    tool_id: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    input_schema: Dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    output_schema: Dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    risk_level: RiskLevel = RiskLevel.L1
    side_effect_class: SideEffectClass = SideEffectClass.NONE
    confirmation_required: bool = False
    preconditions: List[str] = Field(default_factory=list)
    postconditions: List[str] = Field(default_factory=list)
    success_evidence: List[str] = Field(default_factory=list)
    failures: List[FailureContractV1] = Field(default_factory=list)
    idempotent: bool = False
    sensitive_fields: List[str] = Field(default_factory=list)
    allowed_parameter_sources: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_json_schemas(self) -> "ToolContractV1":
        pattern = r"^[A-Za-z][A-Za-z0-9_.:/-]*$" if self.contract_version == "1.2" else r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$"
        if not re.fullmatch(pattern, self.tool_id):
            raise ValueError("tool_id_invalid")
        Draft202012Validator.check_schema(self.input_schema)
        Draft202012Validator.check_schema(self.output_schema)
        return self


class ConversationEventV1(ContractModel):
    type: Literal["user_message", "interaction_response"]
    content: Optional[str] = Field(default=None, max_length=20000)
    interaction_id: Optional[str] = Field(default=None, max_length=160)
    response: Dict[str, Any] = Field(default_factory=dict)
    supplied_facts: Dict[str, Any] = Field(default_factory=dict)
    corrected_facts: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_event(self) -> "ConversationEventV1":
        if self.type == "user_message" and not (self.content or "").strip():
            raise ValueError("conversation_user_message_empty")
        if self.type == "interaction_response" and not self.interaction_id:
            raise ValueError("conversation_interaction_id_required")
        return self


class ParameterExpectationV1(ContractModel):
    tool_id: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    match: Literal["exact", "subset"] = "subset"


class BudgetV1(ContractModel):
    max_total_tokens: Optional[int] = Field(default=None, ge=0)
    max_agent_llm_calls: Optional[int] = Field(default=None, ge=0)
    max_active_runtime_ms: Optional[float] = Field(default=None, ge=0)
    max_estimated_cost: Optional[float] = Field(default=None, ge=0)


class MetricGateV1(ContractModel):
    metric_id: str = Field(min_length=1, max_length=160)
    operator: Literal["equals", "min", "max"]
    expected: Any
    allow_na: bool = False


class BusinessRequirementV1(ContractModel):
    requirement_id: str = Field(min_length=1, max_length=160)
    verifier_id: str = Field(min_length=1, max_length=120)
    verifier_version: str = '1.0'
    subject: str = Field(default='run', max_length=160)
    turn: Optional[int] = Field(default=None, ge=0)
    expected: Dict[str, Any] = Field(default_factory=dict)
    required_evidence: List[str] = Field(default_factory=list)
    applicable: bool = True


class BusinessEvidenceBundleV1(ContractModel):
    contract_version: Literal['1.2'] = '1.2'
    run_id: str = Field(min_length=1, max_length=160)
    project_id: str = Field(min_length=1, max_length=120)
    company_id: str = Field(min_length=1, max_length=160)
    collector_id: str = Field(min_length=1, max_length=160)
    started_at: datetime = Field(default_factory=utc_now)
    ended_at: Optional[datetime] = None
    complete: bool = False
    initial_state: Dict[str, Any] = Field(default_factory=dict)
    final_state: Dict[str, Any] = Field(default_factory=dict)
    effects: List[Dict[str, Any]] = Field(default_factory=list)
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    checks: List[Dict[str, Any]] = Field(default_factory=list)
    reviews: List[Dict[str, Any]] = Field(default_factory=list)
    interactions: List[Dict[str, Any]] = Field(default_factory=list)
    observations: List[Dict[str, Any]] = Field(default_factory=list)
    report: Dict[str, Any] = Field(default_factory=dict)
    resource_usage: ResourceUsageV1 = Field(default_factory=ResourceUsageV1)
    omission_reasons: List[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def validate_business_interval(self):
        if self.ended_at and self.ended_at < self.started_at:
            raise ValueError('business_evidence_invalid_interval')
        if self.complete and self.ended_at is None:
            raise ValueError('business_evidence_complete_requires_end')
        return self


class EvalCaseV1(ContractModel):
    contract_version: Literal["1.0", "1.1", "1.2"] = CONTRACT_VERSION
    case_id: str = Field(min_length=1, max_length=160)
    version: str = Field(default="1", min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=240)
    input: Dict[str, Any] = Field(default_factory=dict)
    conversation: List[ConversationEventV1] = Field(default_factory=list)
    expected_tools: List[str] = Field(default_factory=list)
    allowed_tools: List[str] = Field(default_factory=list)
    forbidden_tools: List[str] = Field(default_factory=list)
    required_sequence: List[str] = Field(default_factory=list)
    partial_order: List[List[str]] = Field(default_factory=list)
    parameter_expectations: List[ParameterExpectationV1] = Field(default_factory=list)
    outcome_assertions: Dict[str, Any] = Field(default_factory=dict)
    fact_assertions: List[Dict[str, Any]] = Field(default_factory=list)
    intents: List[Dict[str, Any]] = Field(default_factory=list)
    reference_min_steps: Optional[int] = Field(default=None, ge=0)
    budgets: BudgetV1 = Field(default_factory=BudgetV1)
    gates: List[MetricGateV1] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    pack_id: str = Field(default="core", max_length=120)
    scenario_id: Optional[str] = Field(default=None, max_length=160)
    scenario_version: Optional[str] = Field(default=None, max_length=80)
    direction: Optional[str] = Field(default=None, max_length=80)
    scenario_data: Dict[str, Any] = Field(default_factory=dict)
    behavior_assertions: List[Dict[str, Any]] = Field(default_factory=list)
    capability_bindings: List[Dict[str, Any]] = Field(default_factory=list)
    artifact_requirements: Dict[str, Any] = Field(default_factory=dict)
    business_requirements: List[BusinessRequirementV1] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_partial_order(self) -> "EvalCaseV1":
        identifiers = [row.requirement_id for row in self.business_requirements]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError('business_requirement_id_duplicate')
        if self.business_requirements and self.contract_version != '1.2':
            raise ValueError('business_requirements_need_contract_1_2')
        for chain in self.partial_order:
            if len(chain) < 2 or any(not str(tool).strip() for tool in chain):
                raise ValueError("partial_order_constraint_invalid")
        return self

    @model_serializer(mode="wrap")
    def serialize_compatible(self, handler):
        payload = handler(self)
        if self.contract_version != '1.2' and not self.business_requirements:
            payload.pop('business_requirements', None)
        if self.contract_version == "1.0":
            for key in ("scenario_id", "scenario_version", "direction", "scenario_data",
                        "behavior_assertions", "capability_bindings", "artifact_requirements"):
                if not payload.get(key):
                    payload.pop(key, None)
        return payload


class MetricResultV1(ContractModel):
    contract_version: Literal["1.0", "1.1", "1.2"] = CONTRACT_VERSION
    metric_id: str = Field(min_length=1, max_length=160)
    metric_version: str = Field(default="1.0", max_length=40)
    group: str = Field(default="core", max_length=80)
    status: MetricStatus
    value: Any = None
    reason_code: str = Field(default="", max_length=160)
    evidence_refs: List[str] = Field(default_factory=list)
    na_reason: Optional[str] = Field(default=None, max_length=240)
    details: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_na(self) -> "MetricResultV1":
        if self.status == MetricStatus.NA and not self.na_reason:
            raise ValueError("metric_na_reason_required")
        return self


class GateResultV1(ContractModel):
    metric_id: str
    passed: bool
    operator: str
    expected: Any
    actual: Any = None
    reason_code: str


class EvaluationResultV1(ContractModel):
    contract_version: Literal["1.0", "1.1", "1.2"] = CONTRACT_VERSION
    trace_id: str
    case_id: str
    metric_results: List[MetricResultV1]
    gate_results: List[GateResultV1]
    overall_pass: bool
    gate_failures: List[str] = Field(default_factory=list)
    evaluated_at: datetime = Field(default_factory=utc_now)


class ExperimentSpecV1(ContractModel):
    contract_version: Literal["1.0", "1.1", "1.2"] = CONTRACT_VERSION
    experiment_id: str = Field(min_length=1, max_length=160)
    project_id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=240)
    dataset_id: str = Field(min_length=1, max_length=160)
    dataset_version: str = Field(min_length=1, max_length=80)
    target_id: str = Field(min_length=1, max_length=160)
    target_version: str = Field(min_length=1, max_length=80)
    tool_contract_set_id: str = "default"
    tool_contract_version: Optional[str] = None
    evaluator_set_id: str = "default"
    evaluator_set_version: str = "1.0"
    model_config_version: Optional[str] = Field(default=None, max_length=120)
    provider_id: Optional[str] = Field(default=None, max_length=120)
    provider_version: Optional[str] = Field(default=None, max_length=120)
    model: Optional[str] = Field(default=None, max_length=160)
    allow_paid: bool = False
    repetitions: int = Field(default=1, ge=1, le=100)
    concurrency: int = Field(default=1, ge=1, le=16)
    execution_mode: ExecutionMode = ExecutionMode.DRY_RUN
    timeout_ms: int = Field(default=30000, ge=100, le=3600000)
    tags: Dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def pinned_provider(self):
        if any((self.provider_id, self.provider_version, self.model)):
            if not all((self.provider_id, self.provider_version, self.model)):
                raise ValueError("provider_version_and_model_required")
            if self.contract_version != "1.2":
                raise ValueError("provider_selection_requires_contract_1_2")
        return self

    @model_serializer(mode="wrap")
    def preserve_legacy_payload(self, handler):
        data = handler(self)
        if self.contract_version != "1.2":
            for key in ("provider_id", "provider_version", "model", "allow_paid"):
                data.pop(key, None)
        return data


class TargetRunRequestV1(ContractModel):
    contract_version: Literal["1.0", "1.1", "1.2"] = CONTRACT_VERSION
    request_id: str
    session_id: str
    case: EvalCaseV1
    execution_mode: ExecutionMode
    timeout_ms: int = Field(ge=100)


class TargetResumeRequestV1(ContractModel):
    contract_version: Literal["1.0", "1.1", "1.2"] = CONTRACT_VERSION
    request_id: str
    external_run_id: str
    session_id: str
    interaction_id: str
    response: Dict[str, Any]
    timeout_ms: int = Field(ge=100)


class PendingInteractionV1(ContractModel):
    interaction_id: str
    type: Literal["clarification", "confirmation"]
    prompt: str
    confirmation_kind: Optional[Literal["parameter", "risk", "combined", "artifact"]] = None
    choices: List[str] = Field(default_factory=list)
    required_fields: List[str] = Field(default_factory=list)
    tool_call_id: Optional[str] = None
    parameter_snapshot_hash: Optional[str] = None
    artifact_id: Optional[str] = None
    artifact_version: Optional[str] = None
    artifact_manifest_hash: Optional[str] = None


class TargetRunResponseV1(ContractModel):
    contract_version: Literal["1.0", "1.1", "1.2"] = CONTRACT_VERSION
    external_run_id: str
    status: RunStatus
    trace: TraceEnvelopeV1
    pending_interaction: Optional[PendingInteractionV1] = None
    error_type: Optional[str] = Field(default=None, max_length=160)


class TargetDefinitionV1(ContractModel):
    contract_version: Literal["1.0", "1.1", "1.2"] = CONTRACT_VERSION
    target_id: str
    version: str
    name: str
    adapter_type: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_.-]*$")
    safe_for_eval: bool = False
    config: Dict[str, Any] = Field(default_factory=dict)
    tags: Dict[str, str] = Field(default_factory=dict)

