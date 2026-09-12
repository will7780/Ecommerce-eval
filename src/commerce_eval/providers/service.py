"""Versioned provider configuration; only explicit checks perform model requests."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .credentials import CredentialResolver
from .errors import ProviderError
from .models import ProviderCheckRow, ProviderConfigVersionRow
from .network import normalize_base_url
from .schemas import PRESETS, CredentialSave, ProviderCheck, ProviderSave


class ProviderConfigService:
    def __init__(self, database, *, credential_resolver=None, transport=None, dns_resolver=None):
        self.database = getattr(database, "database", database)
        self.credentials = credential_resolver if credential_resolver is not None else CredentialResolver()
        self.transport = transport
        self.dns_resolver = dns_resolver

    def _latest(self, provider_id):
        with self.database.sessions() as session:
            row = session.scalar(select(ProviderConfigVersionRow).where(
                ProviderConfigVersionRow.provider_id == provider_id
            ).order_by(ProviderConfigVersionRow.version.desc()).limit(1))
            return self._row_dict(row) if row is not None else None

    @staticmethod
    def _row_dict(row):
        return {**row.payload_json, "version": row.version,
                "created_at": row.created_at.replace(tzinfo=timezone.utc).isoformat()}

    def get(self, provider_id: str, version: int) -> dict:
        if type(version) is not int or version < 1:
            raise ProviderError("provider_version_required")
        with self.database.sessions() as session:
            row = session.get(ProviderConfigVersionRow, (provider_id, version))
            if row is None:
                raise ProviderError("provider_version_not_found", 404)
            return self._row_dict(row)

    def require_active(self, provider_id: str, version: int) -> dict:
        config = self.get(provider_id, version)
        current = self._latest(provider_id)
        if not current or not config["enabled"] or not current["enabled"]:
            raise ProviderError("provider_disabled", 409)
        if not config["endpoint_confirmed"]:
            raise ProviderError("provider_endpoint_not_confirmed", 409)
        return config

    def _view(self, config: dict) -> dict:
        resolved = self.credentials.resolve(config["credential_env"])
        check = None
        if config.get("version") is not None:
            with self.database.sessions() as session:
                row = session.get(ProviderCheckRow, (config["provider_id"], config["version"]))
                check = dict(row.payload_json) if row else None
        status = "disabled" if not config["enabled"] else "configured" if resolved.configured else "not_configured"
        return {**config, "configured": resolved.configured, "credential_source": resolved.source,
                "configuration_status": status, "error_type": resolved.error_type, "last_check": check}

    def list(self) -> dict:
        with self.database.sessions() as session:
            rows = session.scalars(select(ProviderConfigVersionRow).order_by(
                ProviderConfigVersionRow.provider_id, ProviderConfigVersionRow.version.desc())).all()
            configs = {}
            for row in rows:
                configs.setdefault(row.provider_id, self._row_dict(row))
        for preset in PRESETS[:2]:
            if preset["provider_id"] not in configs:
                configs[preset["provider_id"]] = {**preset, "enabled": True, "allow_localhost": False,
                    "endpoint_confirmed": False, "endpoint_fingerprint": None, "version": None}
        return {"items": [self._view(value) for value in configs.values()],
                "presets": [dict(value) for value in PRESETS], "central_env": self.credentials.store.status()}

    def save(self, request: ProviderSave | dict) -> dict:
        try:
            request = request if isinstance(request, ProviderSave) else ProviderSave.model_validate(request)
        except ValidationError:
            raise ProviderError("provider_config_invalid", 422) from None
        payload = request.model_dump(exclude={"expected_version"})
        payload["base_url"] = normalize_base_url(request.base_url, allow_localhost=request.allow_localhost)
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=True)
        known = self.credentials.resolve(request.credential_env)
        if known.configured and known.value.get_secret_value() in serialized:
            raise ProviderError("provider_config_secret_rejected")
        payload["endpoint_fingerprint"] = hashlib.sha256(payload["base_url"].encode()).hexdigest()
        checksum = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        try:
            with self.database.sessions.begin() as session:
                previous = session.scalar(select(ProviderConfigVersionRow).where(
                    ProviderConfigVersionRow.provider_id == request.provider_id
                ).order_by(ProviderConfigVersionRow.version.desc()).limit(1))
                actual = previous.version if previous else None
                if request.expected_version != actual:
                    raise ProviderError("provider_version_conflict", 409)
                if previous is not None and previous.checksum == checksum:
                    result = self._row_dict(previous)
                else:
                    version = actual + 1 if actual is not None else 1
                    row = ProviderConfigVersionRow(provider_id=request.provider_id, version=version,
                                                   payload_json=payload, checksum=checksum)
                    session.add(row)
                    session.flush()
                    result = self._row_dict(row)
        except IntegrityError:
            raise ProviderError("provider_version_conflict", 409) from None
        return self._view(result)

    def set_credential(self, provider_id: str, request: CredentialSave | dict) -> dict:
        try:
            request = request if isinstance(request, CredentialSave) else CredentialSave.model_validate(request)
        except ValidationError:
            raise ProviderError("credential_request_invalid", 422) from None
        if not request.acknowledge_shared:
            raise ProviderError("shared_credential_acknowledgement_required")
        config = self.require_active(provider_id, request.version)
        current = self._latest(provider_id)
        if current["version"] != request.version:
            raise ProviderError("provider_version_conflict", 409)
        state = self.credentials.store.set_secret(config["credential_env"], request.secret,
                                                  expected_version=request.expected_env_version)
        resolved = self.credentials.resolve(config["credential_env"])
        return {"provider_id": provider_id, "version": request.version, "configured": resolved.configured,
                "credential_source": resolved.source, "central_env": state}

    async def check(self, provider_id: str, request: ProviderCheck | dict) -> dict:
        from .client import NativeCompatibleClient

        try:
            request = request if isinstance(request, ProviderCheck) else ProviderCheck.model_validate(request)
        except ValidationError:
            raise ProviderError("provider_check_invalid", 422) from None
        if not request.allow_paid:
            raise ProviderError("paid_call_not_authorized", 403)
        config = self.require_active(provider_id, request.version)
        model = request.model or config["model"]
        client = NativeCompatibleClient(self, provider_id=provider_id, version=request.version, model=model,
            allow_paid=True, transport=self.transport, dns_resolver=self.dns_resolver,
            timeout_seconds=10.0, max_calls=1, max_completion_tokens=8)
        error, latency = None, None
        try:
            result = await client.complete([{"role": "user", "content": "Reply OK."}], [])
            latency = result["latency_ms"]
        except ProviderError as exc:
            error = exc.code
            latency = exc.latency_ms
        checked = {"status": "failed" if error else "connected", "error_type": error,
                   "latency_ms": latency, "checked_at": datetime.now(timezone.utc).isoformat(), "model": model}
        with self.database.sessions.begin() as session:
            session.merge(ProviderCheckRow(provider_id=provider_id, version=request.version, payload_json=checked))
        return checked
