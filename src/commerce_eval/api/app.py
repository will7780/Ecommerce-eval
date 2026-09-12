"""FastAPI application for ingestion, experiments, and the bundled UI."""

from __future__ import annotations

import hmac
import json
import os
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, Response
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from fastapi.staticfiles import StaticFiles

from commerce_eval import __version__
from commerce_eval.contracts import ExperimentSpecV1, TargetDefinitionV1, TraceEnvelopeV1
from commerce_eval.core import TraceNormalizer
from commerce_eval.experiments import ExperimentEventBus, ExperimentManager, ExperimentRunner
from commerce_eval.packs import available_evaluators, commerce_pack_manifest
from commerce_eval.storage import Database, Repository, VersionConflictError
from commerce_eval.services.imports import ImportService, ImportValidationError, import_template
from commerce_eval.services.onboarding import OnboardingService, validate_http_definition
from commerce_eval.services.evaluations import EvaluationService
from commerce_eval.services.scenario_templates import instantiate, template_items
from commerce_eval.providers import build_provider_router, ProviderError
from commerce_eval.storage.business_evidence import load_business_evidence

from .schemas import (
    ExperimentRetryCreate,
    ImportPreviewCreate, OnboardingCheckCreate, EvaluationCreate,
    ScenarioInstantiateCreate, OnboardingDemoCreate,
    AnnotationCreate,
    DatasetCreate,
    EvaluatorSetCreate,
    ProjectCreate,
    ToolContractSetCreate,
    TraceBatchCreate,
)


def create_app(*, database_path: Path | str | None = None, static_dir: Path | str | None = None) -> FastAPI:
    database = Database(database_path)
    database.initialize()
    repository = Repository(database)
    event_bus = ExperimentEventBus()
    runner = ExperimentRunner(repository, event_bus=event_bus)
    manager = ExperimentManager(runner)

    app = FastAPI(
        title="Commerce Agent Eval",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.state.database = database
    app.state.repository = repository
    app.state.event_bus = event_bus
    app.state.experiment_manager = manager
    app.include_router(build_provider_router(database))

    @app.middleware("http")
    async def api_token_boundary(request: Request, call_next):
        token = os.environ.get("COMMERCE_EVAL_API_TOKEN")
        if token and request.url.path.startswith("/api/") and request.url.path not in {"/api/v1/health", "/api/docs", "/api/openapi.json"}:
            supplied = request.headers.get("Authorization", "")
            expected = f"Bearer {token}"
            if not hmac.compare_digest(supplied, expected):
                return JSONResponse(status_code=401, content={"detail": "api_token_required"})
        try:
            return await call_next(request)
        except Exception:
            return JSONResponse(status_code=500, content={"detail": "internal_error"})

    @app.exception_handler(KeyError)
    async def handle_not_found(_request: Request, exc: KeyError):
        return JSONResponse(status_code=404, content={"detail": "resource_not_found"})

    @app.exception_handler(ProviderError)
    async def handle_provider_error(_request: Request, exc: ProviderError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.code},
                            headers={"Cache-Control": "no-store"})

    @app.exception_handler(VersionConflictError)
    async def handle_conflict(_request: Request, exc: VersionConflictError):
        return JSONResponse(status_code=409, content={"detail": "version_immutable_conflict"})

    @app.exception_handler(ImportValidationError)
    async def handle_import_error(_request: Request, exc: ImportValidationError):
        conflict = any(error["code"] == "version_immutable_conflict" for error in exc.errors)
        return JSONResponse(status_code=409 if conflict else 400,
                            content={"detail": "import_validation_failed", "errors": exc.errors})

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(_request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"detail": "request_schema_invalid"})

    @app.exception_handler(ValidationError)
    async def handle_contract_validation(_request: Request, exc: ValidationError):
        return JSONResponse(status_code=400, content={"detail": "contract_schema_invalid"})

    @app.exception_handler(IntegrityError)
    async def handle_integrity(_request: Request, exc: IntegrityError):
        return JSONResponse(status_code=409, content={"detail": "resource_integrity_conflict"})

    @app.exception_handler(ValueError)
    async def handle_value_error(_request: Request, exc: ValueError):
        code = str(exc) if str(exc) in {"reference_fixture_not_candidate", "import_expired"} else "request_invalid"
        return JSONResponse(status_code=400, content={"detail": code})

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_request: Request, exc: Exception):
        return JSONResponse(status_code=500, content={"detail": "internal_error"})

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok", "version": __version__, "contract_version": "1.2", "supported_contract_versions": ["1.0", "1.1", "1.2"], "storage": "sqlite"}

    @app.get("/api/v1/dashboard")
    def dashboard(project_id: Optional[str] = None):
        return repository.dashboard(project_id)

    @app.post("/api/v1/projects", status_code=201)
    def create_project(request: ProjectCreate):
        return repository.create_project(request.project_id, request.name, request.description)

    @app.get("/api/v1/projects")
    def list_projects():
        return {"items": repository.list_projects()}

    @app.post("/api/v1/traces", status_code=201)
    def ingest_trace(trace: TraceEnvelopeV1):
        try:
            repository.get_project(trace.project_id)
        except KeyError:
            repository.create_project(trace.project_id, trace.project_id.replace("-", " ").title(), "Imported traces")
        normalized = repository.save_trace(TraceNormalizer.normalize(trace))
        return {"trace_id": normalized.trace_id, "status": normalized.status.value}

    @app.post("/api/v1/traces/batch", status_code=201)
    def ingest_trace_batch(request: TraceBatchCreate):
        trace_ids = []
        with repository.transaction() as bound:
            for trace in request.traces:
                try:
                    bound.get_project(trace.project_id)
                except KeyError:
                    bound.create_project(trace.project_id, trace.project_id.replace("-", " ").title(), "Imported traces")
                trace_ids.append(bound.save_trace(trace).trace_id)
        return {"trace_ids": trace_ids, "count": len(trace_ids)}

    @app.get("/api/v1/traces")
    def list_traces(
        project_id: Optional[str] = None,
        experiment_id: Optional[str] = None,
        status: Optional[str] = None,
        overall_pass: Optional[bool] = None,
        limit: int = Query(default=100, ge=1, le=500),
    ):
        return {"items": repository.list_traces(project_id=project_id, experiment_id=experiment_id, status=status, overall_pass=overall_pass, limit=limit)}

    @app.get("/api/v1/traces/{trace_id}")
    def get_trace(trace_id: str):
        result = repository.get_trace(trace_id)
        bundle = load_business_evidence(repository, trace_id, project_id=result["trace"]["project_id"])
        return {**result, "business_evidence": bundle.model_dump(mode="json") if bundle else None}

    @app.post("/api/v1/traces/{trace_id}/annotations", status_code=201)
    def annotate_trace(trace_id: str, request: AnnotationCreate):
        return repository.add_annotation(trace_id, request.label, request.value)

    @app.post("/api/v1/datasets", status_code=201)
    def create_dataset(request: DatasetCreate):
        return repository.save_dataset(request.project_id, request.dataset_id, request.version, request.name, request.cases, request.description)

    @app.get("/api/v1/datasets")
    def list_datasets(project_id: Optional[str] = None):
        return {"items": repository.list_datasets(project_id)}

    @app.get("/api/v1/datasets/{project_id}/{dataset_id}/{version}")
    def get_dataset(project_id: str, dataset_id: str, version: str):
        return repository.get_dataset(project_id, dataset_id, version)

    @app.post("/api/v1/tool-contracts", status_code=201)
    def create_tool_contract_set(request: ToolContractSetCreate):
        return repository.save_tool_contract_set(request.project_id, request.set_id, request.version, request.tools)

    @app.get("/api/v1/tool-contracts")
    def list_tool_contracts(project_id: Optional[str] = None):
        return {"items": repository.list_tool_contract_sets(project_id)}

    @app.post("/api/v1/evaluator-sets", status_code=201)
    def create_evaluator_set(request: EvaluatorSetCreate):
        return repository.save_evaluator_set(request.project_id, request.set_id, request.version, request.metric_ids)

    @app.get("/api/v1/evaluators")
    def list_evaluators(project_id: Optional[str] = None):
        return {
            "items": [
                {
                    "metric_id": evaluator.metric_id,
                    "metric_version": evaluator.metric_version,
                    "group": evaluator.group,
                    "required_evidence": list(evaluator.required_evidence),
                }
                for evaluator in available_evaluators()
            ],
            "packs": [
                {"pack_id": "core", "version": "1.0.0"},
                {"pack_id": "governance", "version": "1.0.0"},
                commerce_pack_manifest(),
            ],
            "sets": repository.list_evaluator_sets(project_id),
        }

    @app.post("/api/v1/targets", status_code=201)
    def create_target(project_id: str, definition: TargetDefinitionV1):
        definition = validate_http_definition(definition)
        return repository.save_target(project_id, definition)

    @app.get("/api/v1/targets")
    def list_targets(project_id: Optional[str] = None):
        return {"items": repository.list_targets(project_id)}

    @app.post("/api/v1/experiments", status_code=202)
    async def create_experiment(spec: ExperimentSpecV1, request: Request):
        if spec.provider_id:
            from commerce_eval.providers.api import ProviderCSRF
            ProviderCSRF().local_origin(request, mutation=True)
        definition = repository.get_target(spec.project_id, spec.target_id, spec.target_version)
        if spec.provider_id or definition.adapter_type in {"business_interface", "file_editor"}:
            runner.prepare_target(spec, definition)
        repository.create_experiment(spec)
        manager.start(spec)
        return repository.get_experiment(spec.experiment_id)

    @app.get("/api/v1/experiments")
    def list_experiments(project_id: Optional[str] = None):
        return {"items": repository.list_experiments(project_id)}

    @app.get("/api/v1/experiments/compare")
    def compare_experiments(left: str, right: str):
        return repository.compare_experiments(left, right)

    @app.get("/api/v1/experiments/{experiment_id}")
    def get_experiment(experiment_id: str):
        return repository.get_experiment(experiment_id)

    @app.post("/api/v1/experiments/{experiment_id}/cancel")
    def cancel_experiment(experiment_id: str):
        manager.cancel(experiment_id)
        repository.update_experiment(experiment_id, status="cancelled")
        return repository.get_experiment(experiment_id)

    @app.post("/api/v1/experiments/{experiment_id}/retry", status_code=202)
    async def retry_experiment(experiment_id: str, request: Request,
                               approval: ExperimentRetryCreate | None = None):
        current = repository.get_experiment(experiment_id)
        if manager.is_running(experiment_id):
            raise HTTPException(status_code=409, detail="experiment_already_running")
        spec = ExperimentSpecV1.model_validate(current["spec"])
        if spec.provider_id:
            from commerce_eval.providers.api import ProviderCSRF
            ProviderCSRF().local_origin(request, mutation=True)
            if approval is None or approval.allow_paid is not True:
                raise HTTPException(status_code=400, detail="paid_call_confirmation_required")
            definition = repository.get_target(spec.project_id, spec.target_id, spec.target_version)
            runner.prepare_target(spec, definition)
        retry_id = f"{experiment_id}-retry-{uuid4().hex[:8]}"
        retry_spec = spec.model_copy(
            update={"experiment_id": retry_id, "name": f"{current['name']} retry"}
        )
        repository.create_experiment(retry_spec)
        manager.start(retry_spec)
        return repository.get_experiment(retry_id)

    @app.get("/api/v1/experiments/{experiment_id}/events")
    async def experiment_events(experiment_id: str):
        repository.get_experiment(experiment_id)

        async def encode():
            async for event in event_bus.stream(experiment_id):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        return StreamingResponse(encode(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/v1/imports/preview")
    def preview_import(request: ImportPreviewCreate):
        return ImportService(repository).preview(**request.model_dump())

    @app.post("/api/v1/imports/{import_id}/commit")
    def commit_import(import_id: str):
        return ImportService(repository).commit(import_id)

    @app.get("/api/v1/imports/templates")
    def download_import_template(kind: str, download: bool = False):
        name, content = import_template(kind)
        if not download:
            return {"filename": name, "content": content}
        media_type = "application/json" if name.endswith(".json") else "text/csv" if name.endswith(".csv") else "text/plain"
        return Response(content, media_type=media_type,
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.post("/api/v1/onboarding/check")
    async def check_onboarding(request: OnboardingCheckCreate):
        return await OnboardingService(repository).check(**request.model_dump())

    @app.post("/api/v1/onboarding/demo")
    def onboarding_demo(request: OnboardingDemoCreate):
        from commerce_eval.demo import seed_onboarding_demo
        from commerce_eval.business.bootstrap import seed_business_bank

        with repository.transaction() as bound:
            if request.bank_version in {"0.3.0", "0.3.1"}:
                result = seed_business_bank(bound, request.project_id, request.template_ids, version=request.bank_version)
            else:
                result = seed_onboarding_demo(bound, request.project_id, request.template_ids)
            return {"status": "ready", "readiness": {"ready": True, "errors": []}, **result}

    @app.post("/api/v1/evaluations", status_code=201)
    def evaluate_trace(request: EvaluationCreate):
        return EvaluationService(repository).evaluate(**request.model_dump())

    @app.get("/api/v1/evaluations/{evaluation_id}")
    def get_evaluation(evaluation_id: str):
        return repository.get_evaluation(evaluation_id)

    @app.get("/api/v1/scenario-templates")
    def list_scenario_templates(template_version: str = "0.2.0"):
        return {"items": template_items(template_version)}

    @app.post("/api/v1/scenario-templates/{template_id}/instantiate")
    def instantiate_scenario(template_id: str, request: ScenarioInstantiateCreate):
        return instantiate(repository, template_id, **request.model_dump())

    @app.get("/api/v1/assets/{project_id}/{kind}/{asset_id}/{version}")
    def get_asset(project_id: str, kind: str, asset_id: str, version: str):
        return repository.get_asset(project_id, kind, asset_id, version)

    frontend = Path(static_dir) if static_dir else Path(__file__).resolve().parents[1] / "static"
    assets = frontend / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        index = frontend / "index.html"
        if index.exists():
            return FileResponse(index)
        return JSONResponse(
            status_code=503,
            content={"detail": "frontend_not_built", "hint": "Run npm --prefix web run build"},
        )

    return app

