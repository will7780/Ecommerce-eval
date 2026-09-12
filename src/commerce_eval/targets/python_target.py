"""JSON-lines subprocess target for Python agents."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from typing import Any, Mapping
import sys

from commerce_eval.contracts import (
    TargetDefinitionV1,
    TargetResumeRequestV1,
    TargetRunRequestV1,
    TargetRunResponseV1,
)

from .base import candidate_request_payload, failed_target_response, target_protocol_version


class PythonAgentTarget:
    def __init__(self, definition: TargetDefinitionV1) -> None:
        self.definition = definition
        self.protocol_version = target_protocol_version(definition)
        command = definition.config.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command):
            raise ValueError("python_target_command_invalid")
        self.command = [sys.executable if item == "$PYTHON" else item for item in command]
        self.project_id = str(definition.config.get("project_id") or "default")

    async def capabilities(self) -> Mapping[str, Any]:
        return {
            "target_id": self.definition.target_id,
            "version": self.definition.version,
            "protocol_version": self.protocol_version,
            "supported_protocol_versions": ["1.0", "1.1"],
            "operations": ["start", "resume", "reset"],
        }

    async def start(self, request: TargetRunRequestV1) -> TargetRunResponseV1:
        return await self._invoke("start", candidate_request_payload(request), request.request_id, request.timeout_ms)

    async def resume(self, request: TargetResumeRequestV1) -> TargetRunResponseV1:
        return await self._invoke("resume", request.model_dump(mode="json"), request.request_id, request.timeout_ms)

    async def reset(self, session_id: str) -> None:
        await self._invoke("reset", {"session_id": session_id}, f"reset-{session_id}", 5000, expect_response=False)

    def _environment(self) -> dict[str, str]:
        safe_names = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PYTHONPATH", "HOME", "USERPROFILE"}
        configured = self.definition.config.get("env_allowlist")
        if isinstance(configured, list):
            safe_names.update(
                str(item)
                for item in configured
                if isinstance(item, str)
                and not any(marker in item.lower() for marker in ("key", "token", "secret", "password", "credential"))
            )
        return {name: value for name, value in os.environ.items() if name in safe_names}

    async def _invoke(
        self,
        operation: str,
        payload: Mapping[str, Any],
        request_id: str,
        timeout_ms: int,
        *,
        expect_response: bool = True,
    ) -> TargetRunResponseV1 | None:
        message = json.dumps({"protocol_version": self.protocol_version, "operation": operation, "payload": payload}, ensure_ascii=False).encode("utf-8")
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            process = await asyncio.create_subprocess_exec(
                *self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._environment(),
                creationflags=creationflags,
            )
            stdout, _stderr = await asyncio.wait_for(process.communicate(message), timeout=timeout_ms / 1000.0)
            if process.returncode != 0:
                return failed_target_response(request_id=request_id, project_id=self.project_id, target=self.definition, error_type="python_target_failed")
            if not expect_response:
                return None
            if len(stdout) > 1_000_000:
                return failed_target_response(request_id=request_id, project_id=self.project_id, target=self.definition, error_type="target_response_too_large")
            lines = [line for line in stdout.decode("utf-8", errors="replace").splitlines() if line.strip()]
            if not lines:
                raise ValueError("target_response_empty")
            return TargetRunResponseV1.model_validate(json.loads(lines[-1]))
        except asyncio.CancelledError:
            if "process" in locals() and process.returncode is None:
                process.kill()
                await process.wait()
            raise
        except asyncio.TimeoutError:
            if "process" in locals() and process.returncode is None:
                process.kill()
                await process.wait()
            return failed_target_response(request_id=request_id, project_id=self.project_id, target=self.definition, error_type="target_timeout")
        except Exception as exc:
            return failed_target_response(request_id=request_id, project_id=self.project_id, target=self.definition, error_type=f"target_invalid_response:{type(exc).__name__}")

