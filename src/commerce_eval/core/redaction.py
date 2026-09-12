"""Fail-closed redaction for every persistence and presentation boundary."""

from __future__ import annotations

import re
from typing import Any, Mapping

REDACTED = "[REDACTED]"
OMITTED = "[OMITTED]"
LOCAL_PATH = "[LOCAL_PATH]"

_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "credentials",
    "password",
    "secret",
    "token",
    "access_token",
    "refresh_token",
}
_REASONING_KEYS = {
    "chain_of_thought",
    "cot",
    "hidden_reasoning",
    "reasoning_content",
    "scratchpad",
    "thoughts",
}
_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{10,}=*"),
)
_WINDOWS_USER_PATH = re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s]+\\[^\s\"']+")
_POSIX_HOME_PATH = re.compile(r"(?<!\w)/(?:home|Users)/[^/\s]+/[^\s\"']+")


def _key_is_sensitive(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return lowered in _SENSITIVE_KEYS or lowered.endswith("_secret") or lowered.endswith("_token")


def _key_is_reasoning(key: str) -> bool:
    return key.lower().replace("-", "_") in _REASONING_KEYS


def redact_text(value: str, *, max_chars: int = 12000) -> str:
    text = str(value)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    text = _WINDOWS_USER_PATH.sub(LOCAL_PATH, text)
    text = _POSIX_HOME_PATH.sub(LOCAL_PATH, text)
    if len(text) > max_chars:
        text = text[:max_chars] + "...[TRUNCATED]"
    return text


def redact_recursive(
    value: Any,
    *,
    max_depth: int = 8,
    max_items: int = 256,
    max_chars: int = 12000,
    _depth: int = 0,
) -> Any:
    if _depth >= max_depth:
        return OMITTED
    if isinstance(value, Mapping):
        cleaned = {}
        for index, (raw_key, raw_value) in enumerate(value.items()):
            if index >= max_items:
                cleaned["_truncated"] = True
                break
            key = redact_text(str(raw_key), max_chars=160)
            if _key_is_reasoning(key):
                cleaned[key] = OMITTED
            elif _key_is_sensitive(key):
                cleaned[key] = REDACTED
            else:
                cleaned[key] = redact_recursive(
                    raw_value,
                    max_depth=max_depth,
                    max_items=max_items,
                    max_chars=max_chars,
                    _depth=_depth + 1,
                )
        return cleaned
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        cleaned = [
            redact_recursive(
                item,
                max_depth=max_depth,
                max_items=max_items,
                max_chars=max_chars,
                _depth=_depth + 1,
            )
            for item in items[:max_items]
        ]
        if len(items) > max_items:
            cleaned.append(OMITTED)
        return cleaned
    if isinstance(value, str):
        return redact_text(value, max_chars=max_chars)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_text(str(value), max_chars=max_chars)


def contains_secret(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _key_is_sensitive(str(key)) and not (item is None or isinstance(item, str) and item in {"", REDACTED, OMITTED}):
                return True
            if contains_secret(item):
                return True
        return False
    if isinstance(value, (list, tuple, set)):
        return any(contains_secret(item) for item in value)
    if isinstance(value, str):
        text = value.replace(REDACTED, "").replace(OMITTED, "")
        return any(pattern.search(text) for pattern in _SECRET_PATTERNS)
    return False


def redact_declared_fields(value: Any, sensitive_fields: Any, *, _depth: int = 0) -> Any:
    """Redact contract-declared field names from trace payload sections."""
    if _depth >= 16:
        return OMITTED
    names = {
        str(field).strip().replace("/", ".").split(".")[-1].lower()
        for field in (sensitive_fields or [])
        if str(field).strip()
    }
    if not names:
        return value
    if isinstance(value, Mapping):
        cleaned = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if key.lower() in names:
                cleaned[key] = REDACTED
            else:
                cleaned[key] = redact_declared_fields(raw_value, names, _depth=_depth + 1)
        return cleaned
    if isinstance(value, list):
        return [redact_declared_fields(item, names, _depth=_depth + 1) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_declared_fields(item, names, _depth=_depth + 1) for item in value)
    return value

