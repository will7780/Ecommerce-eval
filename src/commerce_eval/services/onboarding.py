"""Non-executing target validation and bounded, pinned-address connectivity."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import re
import socket
from urllib.parse import urlsplit, urlunsplit

import httpx

from commerce_eval.contracts import TargetDefinitionV1

MAX_CAPABILITIES_BYTES = 64 * 1024


def validate_http_definition(definition: TargetDefinitionV1) -> TargetDefinitionV1:
    if definition.adapter_type != "http":
        raise ValueError("public_target_http_only")
    config = dict(definition.config)
    if "credential_env" in config:
        reference = config.pop("credential_env")
        if "token_env" in config and config["token_env"] != reference:
            raise ValueError("credential_reference_conflict")
        config["token_env"] = reference
    if set(config) - {"base_url", "token_env", "project_id"}:
        raise ValueError("target_config_not_allowed")
    token_env = config.get("token_env")
    if token_env is not None and (not isinstance(token_env, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", token_env)):
        raise ValueError("credential_reference_invalid")
    parsed = _url(config.get("base_url"))
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        if parsed.hostname.lower().rstrip(".") in {"metadata", "metadata.google.internal", "instance-data"}:
            raise ValueError("target_address_forbidden") from None
    else:
        _check_address(address, parsed.hostname)
    return definition.model_copy(update={"config": config})


def _url(value):
    if not isinstance(value, str) or any(char.isspace() or ord(char) < 32 for char in value):
        raise ValueError("target_url_invalid")
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError
        if parsed.query or parsed.fragment or "\\" in value or "%" in parsed.hostname:
            raise ValueError
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError
    except ValueError:
        raise ValueError("target_url_invalid") from None
    return parsed


def _check_address(address, host):
    intended_loopback = host.lower().rstrip(".") in {"localhost", "127.0.0.1", "::1"}
    try:
        intended_loopback = intended_loopback or ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass
    if address.is_loopback and intended_loopback:
        return
    if not address.is_global or address.is_multicast or address.is_unspecified:
        raise ValueError("target_address_forbidden")


class OnboardingService:
    def __init__(self, repository, *, timeout: float = 3.0, transport=None):
        self.repository = repository
        self.timeout = timeout
        self.transport = transport

    async def check(self, project_id, target_id=None, target_version=None, definition=None,
                    dataset_id=None, dataset_version=None, template_ids=None, template_version="0.3.0"):
        result = await self._check_target(project_id, target_id, target_version, definition)
        if dataset_id is None and dataset_version is None and template_ids is None:
            return result
        if template_ids is not None:
            if dataset_id or dataset_version:
                raise ValueError("dataset_or_template_reference_required")
            from commerce_eval.services.scenario_templates import load_templates
            templates = {item.scenario_id: item for item in load_templates(template_version)}
            if not template_ids or len(set(template_ids)) != len(template_ids) or set(template_ids) - templates.keys():
                raise ValueError("template_selection_invalid")
            requirements = [item.model_dump() for identifier in template_ids
                            for item in templates[identifier].business_requirements if item.applicable]
        else:
            if not dataset_id or not dataset_version:
                raise ValueError("dataset_version_required")
            dataset = self.repository.get_dataset(project_id, dataset_id, dataset_version)
            requirements = [item for case in dataset["cases"] for item in case.get("business_requirements", [])
                            if item.get("applicable", True)]
        if not requirements:
            return result
        target = (self.repository.get_target(project_id, target_id, target_version)
                  if target_id and target_version else None)
        registered = target is not None and target.adapter_type in {"business_interface", "file_editor"}
        required = sorted({name for item in requirements for name in item.get("required_evidence", [])})
        readiness = {
            "ready": registered and result["status"] == "ready",
            "required_evidence": required, "missing_evidence": [] if registered else required,
            "collector": "builtin-business-environment-v1" if registered else None,
            "reason_code": "registered_environment_collector" if registered else "external_evidence_collector_required",
            "tool_name_matching_required": False,
        }
        return {**result, "connection_ready": result["status"] == "ready", "business_readiness": readiness,
                "status": result["status"] if readiness["ready"] else "evidence_required"}

    async def _check_target(self, project_id, target_id=None, target_version=None, definition=None):
        self.repository.get_project(project_id)
        if definition is not None:
            if target_id is not None or target_version is not None:
                raise ValueError("target_reference_or_definition_required")
            definition = TargetDefinitionV1.model_validate(definition)
            definition = validate_http_definition(definition)
        else:
            if not target_id or not target_version:
                raise ValueError("target_reference_or_definition_required")
            definition = self.repository.get_target(project_id, target_id, target_version)
            if definition.config.get("project_id", project_id) != project_id:
                raise ValueError("target_project_mismatch")
            if definition.adapter_type != "http":
                safe = definition.safe_for_eval is True and definition.config.get("execution_mode", "dry_run") in {"dry_run", "sandbox"}
                return {"status": "ready" if safe else "invalid", "target_id": definition.target_id,
                        "target_version": definition.version, "executed": False,
                        "connection": "not_executed", "checks": [{"code": "existing_local_registration" if safe else "target_not_safe_for_eval",
                                                                   "status": "pass" if safe else "fail"}]}
            definition = validate_http_definition(definition)
        if definition.config.get("project_id", project_id) != project_id:
            raise ValueError("target_project_mismatch")
        if definition.safe_for_eval is not True:
            return {"status": "invalid", "target_id": definition.target_id, "target_version": definition.version,
                    "executed": False, "connection": "not_executed",
                    "checks": [{"code": "target_not_safe_for_eval", "status": "fail"}]}
        env_name = definition.config.get("token_env")
        if env_name and not os.environ.get(env_name):
            code = "credential_reference_unavailable"
        else:
            try:
                code = await asyncio.wait_for(self._probe(definition), timeout=self.timeout)
            except (TimeoutError, asyncio.TimeoutError, httpx.TimeoutException):
                code = "target_connection_timeout"
            except ValueError:
                code = "target_address_forbidden"
            except Exception:
                code = "target_connection_unavailable"
        ready = code == "target_connected"
        return {"status": "ready" if ready else "invalid", "executed": False,
                "target_id": definition.target_id, "target_version": definition.version,
                "connection": "connected" if ready else "unavailable",
                "checks": [{"code": code, "status": "pass" if ready else "fail"}]}

    async def _probe(self, definition):
        parsed = _url(definition.config["base_url"])
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        if not addresses:
            raise OSError("no_addresses")
        for address in addresses:
            _check_address(ipaddress.ip_address(address[4][0]), host)
        # Pin the validated IP so a second DNS lookup cannot bypass address checks.
        address = addresses[0][4][0]
        authority = f"[{host}]" if ":" in host else host
        ip_authority = f"[{address}]" if ":" in address else address
        url = urlunsplit((parsed.scheme, f"{ip_authority}:{port}", parsed.path.rstrip("/") + "/v1/capabilities", "", ""))
        headers = {"Host": f"{authority}:{port}", "Accept": "application/json", "Accept-Encoding": "identity"}
        env_name = definition.config.get("token_env")
        token = os.environ.get(env_name, "") if env_name else ""
        if token:
            if any(ord(char) < 32 or ord(char) > 126 for char in token):
                return "credential_reference_invalid"
            headers["Authorization"] = "Bearer " + token
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False, follow_redirects=False, transport=self.transport) as client:
            async with client.stream("GET", url, headers=headers, extensions={"sni_hostname": host}) as response:
                if 300 <= response.status_code < 400:
                    return "target_redirect_refused"
                if response.status_code in {401, 403}:
                    return "target_permission_denied"
                if response.status_code != 200:
                    return "target_protocol_unavailable"
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    return "target_capabilities_invalid"
                content_type = response.headers.get("content-type", "application/json").split(";", 1)[0].strip()
                if content_type != "application/json" and not content_type.endswith("+json"):
                    return "target_capabilities_invalid"
                try:
                    if int(response.headers.get("content-length", "0")) > MAX_CAPABILITIES_BYTES:
                        return "target_capabilities_too_large"
                except ValueError:
                    return "target_capabilities_invalid"
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    if len(body) + len(chunk) > MAX_CAPABILITIES_BYTES:
                        return "target_capabilities_too_large"
                    body.extend(chunk)
        try:
            def unique_object(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("duplicate_capability_key")
                    result[key] = value
                return result

            capabilities = json.loads(body, object_pairs_hook=unique_object)
        except (ValueError, RecursionError):
            return "target_capabilities_invalid"
        if not isinstance(capabilities, dict):
            return "target_capabilities_invalid"
        protocol = capabilities.get("protocol_version")
        operations = capabilities.get("operations")
        if isinstance(protocol, bool) or str(protocol) not in {"1", "1.0", "1.1", "1.2"}:
            return "target_protocol_unsupported"
        if not isinstance(operations, list) or not {"start", "resume"}.issubset(item for item in operations if isinstance(item, str)):
            return "target_operations_missing"
        if capabilities.get("safe_for_eval") is not True:
            return "target_not_safe_for_eval"
        return "target_connected"
