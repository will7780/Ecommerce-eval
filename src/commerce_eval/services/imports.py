"""One normalized, atomic import workflow shared by HTTP and the local CLI."""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from commerce_eval.contracts import EvalCaseV1, TargetDefinitionV1, ToolContractV1, TraceEnvelopeV1
from commerce_eval.core import ContractNormalizer, TraceNormalizer, redact_recursive
from commerce_eval.packs import all_evaluators
from commerce_eval.storage import VersionConflictError
from commerce_eval.storage.models import ImportDraftRow

from .onboarding import validate_http_definition

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_IMPORT_BYTES = 50 * 1024 * 1024
MAX_TRACES = 1000
KINDS = {"trace", "dataset", "tool-contracts", "products", "rules", "target", "evaluator-set"}
EXTENSIONS = {kind: {".json", ".jsonl"} for kind in KINDS}
EXTENSIONS.update(products={".csv", ".json"}, rules={".md", ".txt"})


class ProductRow(BaseModel):
    model_config = ConfigDict(extra="allow", allow_inf_nan=False, str_strip_whitespace=True)
    sku: str = Field(min_length=1, max_length=160)
    price: float = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class ImportValidationError(ValueError):
    def __init__(self, errors):
        super().__init__("import_validation_failed")
        self.errors = errors


def _error(file="", line=None, field="", code="schema_invalid"):
    return {"file": redact_recursive(file), "line": line,
            "field": redact_recursive(str(field)), "code": code}


def _validation_errors(exc, file, line):
    return [_error(file, line, ".".join(str(part) for part in row["loc"]), row["type"])
            for row in exc.errors(include_url=False, include_context=False, include_input=False)]


def _identifier(value, field, maximum=160):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "::" in value:
        raise ImportValidationError([_error(field=field, code="identifier_invalid")])
    if redact_recursive(value) != value:
        raise ImportValidationError([_error(field=field, code="identifier_sensitive")])
    return value


def _json(text):
    def reject_constant(_value):
        raise ValueError("non_finite_number")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    return json.loads(text, parse_constant=reject_constant, object_pairs_hook=unique_object)


class ImportService:
    def __init__(self, repository, *, allow_local_registration=False, draft_ttl=timedelta(hours=1)):
        self.repository = repository
        self.allow_local_registration = allow_local_registration
        self.draft_ttl = draft_ttl

    def preview(self, project_id, kind, files, options=None):
        import_id = f"imp_{uuid4().hex}"
        expires = datetime.now(timezone.utc) + self.draft_ttl
        errors, normalized = [], []
        counts = {"files": len(files), "rows": 0, "resources": 0, "traces": 0}
        try:
            _identifier(project_id, "project_id", 120)
            if kind not in KINDS:
                raise ImportValidationError([_error(field="kind", code="import_kind_invalid")])
            normalized, counts, errors = self._normalize(project_id, kind, files, options or {})
            if not errors:
                with self.repository.transaction(dry_run=True) as repository:
                    self._apply(repository, project_id, kind, normalized)
        except ImportValidationError as exc:
            errors.extend(exc.errors)
        except (ValueError, TypeError, KeyError, IntegrityError):
            errors.append(_error(code="import_validation_failed"))
        with self.repository.database.sessions.begin() as session:
            session.execute(delete(ImportDraftRow).where(ImportDraftRow.expires_at <= datetime.now(timezone.utc)))
            if not errors:
                session.add(ImportDraftRow(
                    import_id=import_id, project_id=project_id, kind=kind,
                    payload_json={"resources": normalized, "local_registration": self.allow_local_registration},
                    expires_at=expires,
                ))
        return {"import_id": import_id, "status": "invalid" if errors else "ready", "counts": counts,
                "errors": errors, "preview": normalized[:20] if not errors else [], "expires_at": expires.isoformat()}

    def commit(self, import_id):
        with self.repository.transaction() as repository:
            with repository.database.sessions() as session:
                draft = session.get(ImportDraftRow, import_id)
                if draft is None:
                    raise KeyError("import_not_found")
                if draft.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
                    raise ValueError("import_expired")
                if draft.payload_json.get("local_registration") and not self.allow_local_registration:
                    raise ValueError("public_target_http_only")
                if draft.result_json is not None:
                    return draft.result_json
                refs = self._apply(repository, draft.project_id, draft.kind, draft.payload_json["resources"])
                result = {"import_id": import_id, "status": "committed", "project_id": draft.project_id,
                          "kind": draft.kind, "resources": refs, "count": len(refs)}
                draft.result_json = result
                return result

    def _normalize(self, project_id, kind, files, options):
        errors, rows = [], []
        metadata = {}
        counts = {"files": len(files), "rows": 0, "resources": 0, "traces": 0}
        if not files:
            return [], counts, [_error(code="files_required")]
        sizes = [len(item["content"].encode("utf-8")) for item in files]
        if sum(sizes) > MAX_IMPORT_BYTES:
            return [], counts, [_error(code="import_size_limit")]
        for item, size in zip(files, sizes):
            filename = PurePosixPath(item["name"].replace("\\", "/")).name
            safe_name = redact_recursive(filename)
            suffix = PurePosixPath(filename).suffix.lower()
            if size > MAX_FILE_BYTES:
                errors.append(_error(safe_name, code="file_size_limit"))
                continue
            if suffix not in EXTENSIONS[kind]:
                errors.append(_error(safe_name, code="file_type_not_allowed"))
                continue
            content = item["content"].lstrip("\ufeff")
            if "\x00" in content or content.startswith(("PK\x03\x04", "MZ", "\x7fELF", "#!")):
                errors.append(_error(safe_name, code="executable_or_binary_not_allowed"))
                continue
            try:
                if kind == "rules":
                    if not content.strip():
                        errors.append(_error(safe_name, 1, "content", "rules_empty"))
                    else:
                        rows.append((safe_name, 1, {"name": safe_name, "content": content}))
                    continue
                if suffix == ".csv":
                    reader = csv.DictReader(io.StringIO(content), strict=True)
                    if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
                        raise ValueError("csv_headers_invalid")
                    for row in reader:
                        if None in row or any(value is None for value in row.values()):
                            errors.append(_error(safe_name, reader.line_num, code="csv_columns_invalid"))
                        else:
                            rows.append((safe_name, reader.line_num, row))
                    continue
                if suffix == ".jsonl":
                    for line, value in enumerate(content.splitlines(), 1):
                        if not value.strip():
                            continue
                        try:
                            rows.append((safe_name, line, _json(value)))
                        except (ValueError, RecursionError):
                            errors.append(_error(safe_name, line, code="json_invalid"))
                    continue
                payload = _json(content)
                wrapper = {"dataset": "cases", "tool-contracts": "tools", "evaluator-set": "metric_ids", "products": "products"}.get(kind)
                if isinstance(payload, dict) and wrapper in payload:
                    for key in ("set_id", "dataset_id", "asset_id", "version", "name", "description"):
                        if key in payload:
                            if key in metadata and metadata[key] != payload[key]:
                                errors.append(_error(safe_name, 1, key, "wrapper_metadata_conflict"))
                            metadata[key] = payload[key]
                    payload = payload[wrapper]
                for index, row in enumerate(payload if isinstance(payload, list) else [payload], 1):
                    rows.append((safe_name, index, row))
            except (ValueError, RecursionError, csv.Error):
                errors.append(_error(safe_name, code="file_parse_invalid"))
        counts["rows"] = len(rows)
        counts["traces"] = len(rows) if kind == "trace" else 0
        if kind == "trace" and len(rows) > MAX_TRACES:
            return [], counts, errors + [_error(code="trace_count_limit")]
        if not rows:
            return [], counts, errors + [_error(code="rows_required")]
        clean = []
        seen = set()
        for file, line, row in rows:
            try:
                item = self._normalize_row(project_id, kind, row, options)
                key_name = {"trace": "trace_id", "dataset": "case_id", "tool-contracts": "tool_id", "products": "sku"}.get(kind)
                key = item.get(key_name) if key_name else None
                if key is not None and key in seen:
                    errors.append(_error(file, line, key_name, "duplicate_identifier"))
                seen.add(key)
                clean.append({"file": file, "line": line, "data": item})
            except ValidationError as exc:
                errors.extend(_validation_errors(exc, file, line))
            except (ValueError, TypeError, KeyError, RecursionError):
                errors.append(_error(file, line, code="row_schema_or_reference_invalid"))
        if errors:
            return [], counts, errors
        if kind in {"trace", "target"}:
            resources = clean
        else:
            identifier = _identifier(options.get("id") or metadata.get("set_id") or metadata.get("dataset_id") or metadata.get("asset_id"), "options.id")
            version = _identifier(options.get("version") or metadata.get("version"), "options.version", 80)
            resources = [{"file": clean[0]["file"], "line": 1, "data": {
                "id": identifier, "version": version, "name": redact_recursive(options.get("name") or metadata.get("name") or identifier),
                "description": redact_recursive(metadata.get("description", "")), "rows": [item["data"] for item in clean],
            }}]
        counts["resources"] = len(resources)
        return resources, counts, []

    def _normalize_row(self, project_id, kind, row, options):
        if kind == "trace":
            if not isinstance(row, dict):
                raise ValueError("trace_invalid")
            row = {**row, "project_id": project_id}
            if not row.get("started_at") and row.get("trace_id"):
                try:
                    row["started_at"] = self.repository.get_trace(row["trace_id"])["trace"]["started_at"]
                except KeyError:
                    pass
            TraceEnvelopeV1.model_validate(row)
            contracts = {}
            if row.get("tool_contract_set_id") or row.get("tool_contract_version"):
                if not row.get("tool_contract_set_id") or not row.get("tool_contract_version"):
                    raise ValueError("tool_contract_reference_incomplete")
                contracts = self.repository.get_tool_contracts(project_id, row["tool_contract_set_id"], row["tool_contract_version"])
                if not any(item["set_id"] == row["tool_contract_set_id"] and item["version"] == row["tool_contract_version"]
                           for item in self.repository.list_tool_contract_sets(project_id)):
                    raise ValueError("tool_contract_reference_missing")
            fields = {field for tool in contracts.values() for field in tool.sensitive_fields}
            result = TraceNormalizer.normalize(row, sensitive_fields=fields)
            ids = {event.event_id for event in result.events}
            if any(event.parent_event_id and event.parent_event_id not in ids for event in result.events):
                raise ValueError("event_parent_reference_missing")
            return result.model_dump(mode="json")
        if kind == "dataset":
            EvalCaseV1.model_validate(row)
            case = ContractNormalizer.case(row)
            metrics = {item.metric_id for item in all_evaluators()}
            if any(gate.metric_id not in metrics for gate in case.gates):
                raise ValueError("gate_metric_reference_missing")
            return case.model_dump(mode="json")
        if kind == "tool-contracts":
            ToolContractV1.model_validate(row)
            return ContractNormalizer.tool(row).model_dump(mode="json")
        if kind == "target":
            target = TargetDefinitionV1.model_validate(row)
            if not self.allow_local_registration or target.adapter_type == "http":
                target = validate_http_definition(target)
            elif target.adapter_type != "python" or set(target.config) - {"command", "cwd", "project_id", "env_allowlist", "execution_mode", "protocol_version"}:
                raise ValueError("local_registration_invalid")
            else:
                command = target.config.get("command")
                if not isinstance(command, list) or not command or any(not isinstance(arg, str) or not arg.strip() for arg in command):
                    raise ValueError("local_command_reference_required")
                if any(arg.lower() in {"-c", "-e", "--eval", "-command", "-encodedcommand", "/c"}
                       or "\n" in arg or "\r" in arg for arg in command):
                    raise ValueError("inline_code_registration_forbidden")
                if any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
                       for name in target.config.get("env_allowlist", [])):
                    raise ValueError("credential_reference_invalid")
            if target.config.get("project_id", project_id) != project_id:
                raise ValueError("target_project_mismatch")
            return redact_recursive(target.model_dump(mode="json"))
        if kind == "products":
            if not isinstance(row, dict):
                raise ValueError("product_invalid")
            mapping = options.get("column_mapping") or {}
            if not isinstance(mapping, dict) or len(set(mapping.values())) != len(mapping):
                raise ValueError("column_mapping_invalid")
            # Mapping is destination field -> source column, shared with templates/UI.
            result = {key: value for key, value in row.items() if key not in mapping.values()}
            for destination, source in mapping.items():
                if source not in row or destination in result:
                    raise ValueError("column_mapping_source_missing_or_conflicting")
                result[destination] = row[source]
            return redact_recursive(ProductRow.model_validate(result).model_dump(mode="json"))
        if kind == "rules":
            if not isinstance(row, dict) or not isinstance(row.get("content"), str) or not row["content"].strip():
                raise ValueError("rules_invalid")
            return redact_recursive(row, max_chars=MAX_FILE_BYTES)
        if kind == "evaluator-set":
            if not isinstance(row, str) or row not in {item.metric_id for item in all_evaluators()}:
                raise ValueError("metric_reference_missing")
            return row
        raise ValueError("kind_invalid")

    def _apply(self, repository, project_id, kind, resources):
        try:
            repository.get_project(project_id)
        except KeyError:
            repository.create_project(project_id, project_id.replace("-", " ").title(), "Imported resources")
        errors, refs = [], []
        for resource in resources:
            data = resource["data"]
            try:
                with repository.database.sessions() as session, session.begin_nested():
                    if kind in {"trace", "target"}:
                        value = self._normalize_row(project_id, kind, data, {})
                        if kind == "trace":
                            saved = repository.save_trace(value)
                            refs.append({"kind": kind, "project_id": project_id, "trace_id": saved.trace_id})
                        else:
                            target = TargetDefinitionV1.model_validate(value)
                            repository.save_target(project_id, target)
                            refs.append({"kind": kind, "project_id": project_id, "target_id": target.target_id, "version": target.version})
                    else:
                        identifier, version = _identifier(data["id"], "id"), _identifier(data["version"], "version", 80)
                        rows = [self._normalize_row(project_id, kind, row, {}) for row in data["rows"]]
                        if kind == "dataset":
                            repository.save_dataset(project_id, identifier, version, data["name"], rows, data.get("description", ""))
                            ref_key = "dataset_id"
                        elif kind == "tool-contracts":
                            if len({row["tool_id"] for row in rows}) != len(rows):
                                raise ValueError("tool_id_duplicate")
                            repository.save_tool_contract_set(project_id, identifier, version, rows)
                            ref_key = "set_id"
                        elif kind == "evaluator-set":
                            repository.save_evaluator_set(project_id, identifier, version, rows)
                            ref_key = "set_id"
                        else:
                            if kind == "products" and len({row["sku"] for row in rows}) != len(rows):
                                raise ValueError("product_sku_duplicate")
                            refs.append(repository.save_asset(project_id, kind, identifier, version, data["name"], rows))
                            continue
                        refs.append({"kind": kind, "project_id": project_id, ref_key: identifier, "version": version})
            except VersionConflictError:
                errors.append(_error(resource["file"], resource["line"], code="version_immutable_conflict"))
            except ValidationError as exc:
                errors.extend(_validation_errors(exc, resource["file"], resource["line"]))
            except (ValueError, TypeError, KeyError, IntegrityError):
                errors.append(_error(resource["file"], resource["line"], code="resource_schema_or_reference_invalid"))
        if errors:
            raise ImportValidationError(errors)
        return refs


def import_template(kind):
    examples = {
        "trace": ("trace.json", {"trace_id": "example-trace", "project_id": "example", "target_id": "external",
                                 "target_version": "1", "started_at": "2026-01-01T00:00:00Z", "input": {"message": "Inspect the catalog."}, "events": []}),
        "dataset": ("dataset.json", {"dataset_id": "example-cases", "version": "1", "name": "Example cases",
                                     "cases": [{"case_id": "inspect", "name": "Inspect catalog", "input": {"message": "Inspect the catalog."}}]}),
        "tool-contracts": ("tool-contracts.json", {"set_id": "example-tools", "version": "1", "tools": [
            {"tool_id": "catalog.inspect", "version": "1", "title": "Inspect catalog", "input_schema": {"type": "object"}}]}),
        "products": ("products.csv", "sku,title,price,currency\nSKU-001,Example product,12.50,USD\n"),
        "rules": ("rules.md", "# Catalog policy\n\nValidate every row before publishing. Require explicit approval for external writes.\n"),
        "target": ("target.json", {"target_id": "local-http", "version": "1", "name": "Local HTTP target", "adapter_type": "http",
                                   "safe_for_eval": True, "config": {"base_url": "http://127.0.0.1:9000"}}),
        "evaluator-set": ("evaluator-set.json", {"set_id": "example-evaluators", "version": "1", "metric_ids": ["task_completion"]}),
    }
    if kind not in examples:
        raise ValueError("import_kind_invalid")
    name, content = examples[kind]
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False, indent=2) + "\n"
    return name, content
