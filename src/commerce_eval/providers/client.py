"""Opt-in compatible chat client, pinned to an immutable provider configuration."""

from __future__ import annotations

import asyncio
import json
import math
import re
import threading
import time

import httpx

from commerce_eval.core.redaction import redact_recursive

from .errors import ProviderError
from .network import post_completion
from .schemas import ProviderSave

USAGE_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens", "reasoning_tokens",
                "cache_hit_tokens", "cache_miss_tokens")
_HIDDEN = {"reasoning_content", "reasoning", "thinking", "chain_of_thought", "cot",
           "hidden_reasoning", "scratchpad", "thoughts"}


def parse_usage(usage) -> dict:
    usage = usage if isinstance(usage, dict) else {}
    prompt_details = usage.get("prompt_tokens_details")
    completion_details = usage.get("completion_tokens_details")
    prompt_details = prompt_details if isinstance(prompt_details, dict) else {}
    completion_details = completion_details if isinstance(completion_details, dict) else {}
    values = {
        "prompt_tokens": usage.get("prompt_tokens", usage.get("input_tokens")),
        "completion_tokens": usage.get("completion_tokens", usage.get("output_tokens")),
        "total_tokens": usage.get("total_tokens"),
        "reasoning_tokens": completion_details.get("reasoning_tokens", usage.get("reasoning_tokens")),
        "cache_hit_tokens": usage.get("prompt_cache_hit_tokens", prompt_details.get("cached_tokens")),
        "cache_miss_tokens": usage.get("prompt_cache_miss_tokens"),
    }
    return {key: value if type(value) is int and value >= 0 else None for key, value in values.items()}


def _remove_hidden(value, secret=""):
    if isinstance(value, dict):
        return {key: _remove_hidden(item, secret) for key, item in value.items()
                if str(key).lower() not in _HIDDEN}
    if isinstance(value, list):
        return [_remove_hidden(item, secret) for item in value]
    if isinstance(value, str):
        if secret:
            value = value.replace(secret, "[REDACTED]")
        return re.sub(r"(?is)<think(?:ing)?>.*?(?:</think(?:ing)?>|$)", "", value)
    return value


def _json_load(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    return json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))


class NativeCompatibleClient:
    def __init__(self, service, *, provider_id: str, version: int, model: str | None = None,
                 allow_paid: bool = False, transport=None, dns_resolver=None,
                 timeout_seconds: float = 30.0, max_calls: int = 128,
                 max_completion_tokens: int = 4096, clock=time.monotonic):
        self.service = service
        self.provider_id = provider_id
        self.version = version
        self.config = service.get(provider_id, version)
        self.model = model or self.config["model"]
        try:
            self.model = ProviderSave.public_text(self.model)
        except (ValueError, TypeError):
            raise ProviderError("provider_model_invalid") from None
        if not self.model or len(self.model) > 160:
            raise ProviderError("provider_model_required")
        if type(max_calls) is not int or not 1 <= max_calls <= 10000:
            raise ProviderError("provider_call_budget_invalid")
        if (type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 300
                or not math.isfinite(timeout_seconds)
                or type(max_completion_tokens) is not int or not 1 <= max_completion_tokens <= 32768):
            raise ProviderError("provider_request_budget_invalid")
        self.allow_paid = allow_paid is True
        self.transport = transport
        self.dns_resolver = dns_resolver
        self.timeout_seconds = timeout_seconds
        self.max_calls = max_calls
        self.max_completion_tokens = max_completion_tokens
        self.clock = clock
        self.call_count = 0
        self._budget_lock = threading.Lock()

    async def complete(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        if not self.allow_paid:
            raise ProviderError("paid_call_not_authorized", 403)
        self.service.require_active(self.provider_id, self.version)
        if not isinstance(messages, list) or not messages or len(messages) > 1024:
            raise ProviderError("provider_messages_invalid")
        try:
            encoded_input = json.dumps({"messages": messages, "tools": tools}, allow_nan=False)
            if len(encoded_input.encode("utf-8")) > 2 * 1024 * 1024:
                raise ProviderError("provider_request_too_large")
            # Parse once to enforce JSON-shaped keys and reject cycles/nonfinite values.
            validated = _json_load(encoded_input)
            messages, tools = validated["messages"], validated["tools"]
        except (TypeError, ValueError, RecursionError):
            raise ProviderError("provider_messages_invalid") from None
        allowed = {"role", "content", "tool_calls", "tool_call_id", "name"}
        clean_messages = []
        for message in messages:
            if not isinstance(message, dict) or message.get("role") not in {"system", "developer", "user", "assistant", "tool"}:
                raise ProviderError("provider_messages_invalid")
            clean_messages.append(_remove_hidden({key: value for key, value in message.items() if key in allowed}))
        if tools is not None and (not isinstance(tools, list) or len(tools) > 128):
            raise ProviderError("provider_tools_invalid")
        resolved = self.service.credentials.resolve(self.config["credential_env"])
        if not resolved.configured:
            raise ProviderError("provider_credential_missing", 409)
        secret = resolved.value.get_secret_value()
        body = {"model": self.model, "messages": clean_messages, "stream": False,
                "max_tokens": self.max_completion_tokens}
        if tools:
            body["tools"] = _remove_hidden(tools)
            body["tool_choice"] = "auto"
        try:
            if len(json.dumps(body).encode("utf-8")) > 2 * 1024 * 1024:
                raise ProviderError("provider_request_too_large")
        except (ValueError, TypeError, RecursionError):
            raise ProviderError("provider_messages_invalid") from None
        with self._budget_lock:
            if self.call_count >= self.max_calls:
                raise ProviderError("provider_call_budget_exhausted", 409)
            self.call_count += 1
        started = self.clock()
        try:
            raw = await asyncio.wait_for(
                post_completion(self.config, body, secret, timeout_seconds=self.timeout_seconds,
                                transport=self.transport, dns_resolver=self.dns_resolver),
                timeout=self.timeout_seconds,
            )
            payload = _json_load(raw)
            message = payload["choices"][0]["message"]
            if not isinstance(message, dict):
                raise ValueError
            content = message.get("content")
            if content is not None and not isinstance(content, str):
                raise ValueError
            calls = message.get("tool_calls") or []
            if not isinstance(calls, list) or len(calls) > 128:
                raise ValueError
            normalized = []
            for call in calls:
                function = call["function"]
                name, arguments = function["name"], function["arguments"]
                arguments = _json_load(arguments) if isinstance(arguments, str) else arguments
                if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.:-]{0,159}", name)
                        or not isinstance(arguments, dict) or not isinstance(call.get("id"), str)
                        or not 1 <= len(call["id"]) <= 160):
                    raise ValueError
                normalized.append({"id": call["id"], "name": name, "arguments": arguments})
            if len({item["id"] for item in normalized}) != len(normalized):
                raise ValueError
            result = {"content": content, "tool_calls": normalized, "usage": parse_usage(payload.get("usage")),
                      "latency_ms": max(0.0, (self.clock() - started) * 1000)}
            return redact_recursive(_remove_hidden(result, secret), max_depth=24, max_chars=65536, max_items=4096)
        except asyncio.CancelledError:
            # An outer case deadline cancels this request without retrying it.
            raise
        except ProviderError as exc:
            exc.latency_ms = max(0.0, (self.clock() - started) * 1000)
            raise
        except (asyncio.TimeoutError, httpx.TimeoutException):
            error = ProviderError("provider_timeout", 504)
        except (ValueError, KeyError, IndexError, TypeError, RecursionError):
            error = ProviderError("provider_invalid_response", 502)
        except Exception:
            error = ProviderError("provider_disconnected", 502)
        error.latency_ms = max(0.0, (self.clock() - started) * 1000)
        raise error from None
