"""Explicit case-scoped field names, never semantic guesses or authorization aliases."""

from collections.abc import Mapping


def field_binding_map(aliases):
    if not isinstance(aliases, Mapping):
        raise ValueError("interaction_field_bindings_invalid")
    result = {}
    for canonical, names in aliases.items():
        if not isinstance(canonical, str) or not canonical or not isinstance(names, list):
            raise ValueError("interaction_field_bindings_invalid")
        for name in [canonical, *names]:
            if not isinstance(name, str) or not name:
                raise ValueError("interaction_field_bindings_invalid")
            if name in result:
                raise ValueError("interaction_field_binding_ambiguous")
            result[name] = canonical
    return result


def canonical_fields(fields, aliases):
    mapping = field_binding_map(aliases)
    if not isinstance(fields, list) or any(not isinstance(name, str) for name in fields):
        raise ValueError("interaction_fields_invalid")
    result = [mapping.get(name, name) for name in fields]
    if len(set(result)) != len(result):
        raise ValueError("interaction_field_binding_ambiguous")
    return result


def canonical_values(values, aliases):
    if not isinstance(values, Mapping):
        raise ValueError("interaction_values_invalid")
    fields = canonical_fields(list(values), aliases)
    return dict(zip(fields, values.values()))


def response_for_pending(response, fields, aliases):
    """Keep raw requested names on the resume wire; never add an unrequested answer."""
    canonical = canonical_fields(fields, aliases)
    wrapper = next((name for name in ("values", "fields") if isinstance(response.get(name), Mapping)), None)
    values = canonical_values(response[wrapper] if wrapper else response, aliases)
    if set(values) != set(canonical):
        raise ValueError("interaction_fields_mismatch")
    mapped = {raw: values[name] for raw, name in zip(fields, canonical)}
    return {**response, wrapper: mapped} if wrapper else mapped
