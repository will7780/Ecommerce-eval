"""HTTP target with explicit environment-only authentication."""

from __future__ import annotations

import os
from typing import Any, Mapping, Optional

import httpx

from commerce_eval.contracts import (
    TargetDefinitionV1,
    TargetResumeRequestV1,
    TargetRunRequestV1,
    TargetRunResponseV1,
)

from .base import candidate_request_payload, failed_target_response, target_protocol_version


class HTTPAgentTarget:
    def __init__(self, definition: TargetDefinitionV1, *, client: Optional[httpx.AsyncClient] = None) -> None:
        self.definition = definition
        self.protocol_version = target_protocol_version(definition)
        self.base_url = str(definition.config.get("base_url") or "").rstrip("/")
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("http_target_base_url_invalid")
        self.project_id = str(definition.config.get("project_id") or "default")
        self._client = client

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "X-Agent-Eval-Protocol": self.protocol_version, "X-Agent-Eval-Accept-Protocol": "1.0, 1.1, 1.2"}
        token_env = self.definition.config.get("token_env")
        if token_env:
            token = os.environ.get(str(token_env))
            if token:
                headers["Authorization"] = f"Bearer {token}"
        return headers

    async def capabilities(self) -> Mapping[str, Any]:
        return {"target_id": self.definition.target_id, "version": self.definition.version, "protocol_version": self.protocol_version, "supported_protocol_versions": ["1.0", "1.1"], "operations": ["start", "resume", "reset"]}

    async def start(self, request: TargetRunRequestV1) -> TargetRunResponseV1:
        return await self._post("/v1/runs", candidate_request_payload(request), request.request_id, request.timeout_ms)

    async def resume(self, request: TargetResumeRequestV1) -> TargetRunResponseV1:
        path = f"/v1/runs/{request.external_run_id}/resume"
        return await self._post(path, request.model_dump(mode="json"), request.request_id, request.timeout_ms)

    async def reset(self, session_id: str) -> None:
        await self._post(f"/v1/sessions/{session_id}/reset", {"protocol_version": self.protocol_version}, f"reset-{session_id}", 5000, expect_response=False)

    async def _post(
        self,
        path: str,
        payload: Mapping[str, Any],
        request_id: str,
        timeout_ms: int,
        *,
        expect_response: bool = True,
    ) -> TargetRunResponseV1 | None:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient()
        try:
            response = await client.post(
                f"{self.base_url}{path}",
                json=payload,
                headers=self._headers(),
                timeout=timeout_ms / 1000.0,
            )
            if response.status_code in {401, 403}:
                error_type = "target_permission_denied"
            elif response.status_code == 429:
                error_type = "target_rate_limited"
            elif response.status_code >= 500:
                error_type = "target_backend_error"
            elif response.status_code >= 400:
                error_type = "target_request_rejected"
            else:
                error_type = ""
            if error_type:
                return failed_target_response(request_id=request_id, project_id=self.project_id, target=self.definition, error_type=error_type)
            if not expect_response:
                return None
            version = response.headers.get("X-Agent-Eval-Protocol")
            if version is not None and version not in {"1.0", "1.1", "1.2"}:
                return failed_target_response(request_id=request_id, project_id=self.project_id, target=self.definition, error_type="target_protocol_version_unsupported")
            return TargetRunResponseV1.model_validate(response.json())
        except httpx.TimeoutException:
            return failed_target_response(request_id=request_id, project_id=self.project_id, target=self.definition, error_type="target_timeout")
        except Exception as exc:
            return failed_target_response(request_id=request_id, project_id=self.project_id, target=self.definition, error_type=f"target_disconnected:{type(exc).__name__}")
        finally:
            if owns_client:
                await client.aclose()

