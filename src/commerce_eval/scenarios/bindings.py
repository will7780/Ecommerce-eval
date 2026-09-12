"""Declarative, reversible field/unit mappings; never executable expressions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from commerce_eval.contracts.scenarios import CapabilityBindingV1


def _parts(pointer: str) -> list[str]:
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")] if pointer.startswith("/") else [pointer]


def get_pointer(value: dict, pointer: str) -> Any:
    current: Any = value
    for part in _parts(pointer):
        if isinstance(current, list) and part.isdecimal():
            current = current[int(part)]
        elif isinstance(current, dict):
            current = current[part]
        else:
            raise KeyError(pointer)
    return current


def set_pointer(value: dict, pointer: str, item: Any) -> None:
    parts = _parts(pointer)
    current = value
    for part in parts[:-1]:
        current = current.setdefault(part, {})
        if not isinstance(current, dict):
            raise ValueError("binding_destination_conflict")
    if parts[-1] in current:
        raise ValueError("binding_destination_conflict")
    current[parts[-1]] = deepcopy(item)


def encode_arguments(binding: CapabilityBindingV1, neutral: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in neutral.items():
        scale = binding.unit_scale.get(key, 1)
        if scale != 1:
            if not isinstance(value, (float, int)) or isinstance(value, bool):
                raise ValueError("binding_scale_requires_number")
            value *= scale
        set_pointer(result, binding.argument_mapping.get(key, key), value)
    return result


def decode_arguments(binding: CapabilityBindingV1, actual: dict[str, Any]) -> dict[str, Any]:
    if not binding.argument_mapping:
        return deepcopy(actual)
    result = {key: deepcopy(value) for key, value in actual.items() if key not in {p.split("/")[1] if p.startswith("/") else p for p in binding.argument_mapping.values()}}
    for key, pointer in binding.argument_mapping.items():
        try:
            value = get_pointer(actual, pointer)
        except (KeyError, IndexError):
            continue
        scale = binding.unit_scale.get(key, 1)
        if scale != 1:
            if not isinstance(value, (float, int)) or isinstance(value, bool):
                raise ValueError("binding_scale_requires_number")
            value /= scale
        result[key] = value
    return result


def encode_evidence(binding: CapabilityBindingV1, neutral: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in neutral.items():
        set_pointer(result, binding.evidence_mapping.get(key, key), value)
    return result


def decode_evidence(binding: CapabilityBindingV1, actual: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(actual)
    for key, pointer in binding.evidence_mapping.items():
        try:
            result[key] = get_pointer(actual, pointer)
        except (KeyError, IndexError):
            continue
    return result
