"""Offline artifact readers, full validation and deterministic review selection."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from collections import Counter
from typing import Any


DEFAULT_POLICY = {
    "rule_version": "catalog-policy-2",
    "required": ["row_id", "sku", "title", "price", "currency"],
    "types": {"row_id": "string", "sku": "string", "title": "string", "price": "number", "currency": "string"},
    "unique": ["row_id", "sku"],
    "positive": ["price"],
    "currency": "EUR",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value: bytes | str) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def read_artifact(content: str, format: str) -> list[dict[str, Any]]:
    if format == "json":
        rows = json.loads(content)
    elif format == "csv":
        reader = csv.DictReader(io.StringIO(content))
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError("csv_header_invalid")
        rows = list(reader)
        for row in rows:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("csv_width_invalid")
            try:
                row["price"] = float(row["price"])
            except (ValueError, KeyError):
                pass
    else:
        raise ValueError("artifact_format_unavailable")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("artifact_rows_invalid")
    return rows


def serialize_rows(rows: list[dict[str, Any]], format: str = "json") -> str:
    if format == "json":
        return canonical_json(rows)
    if format != "csv":
        raise ValueError("artifact_format_unavailable")
    buffer = io.StringIO(newline="")
    fields = list(dict.fromkeys(key for row in rows for key in row))
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def validate_artifact(rows: Any, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Inspect every row. Availability and validity are deliberately separate."""
    policy = {**DEFAULT_POLICY, **(policy or {})}
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        return {"available": False, "valid": False, "errors": [], "checked_row_ids": [], "omission_reason": "rows_unavailable"}
    errors: list[dict[str, Any]] = []
    counts = {field: Counter(canonical_json(row.get(field)) for row in rows) for field in policy["unique"]}
    checked: list[str] = []
    for index, row in enumerate(rows):
        row_id = row.get("row_id")
        identity = row_id if isinstance(row_id, str) and row_id else f"@index:{index}"
        checked.append(identity)
        def error(field: str, code: str) -> None:
            errors.append({"row_id": identity, "row_index": index, "field": field, "code": code})
        for field in policy["required"]:
            if row.get(field) is None or (isinstance(row.get(field), str) and not row[field].strip()):
                error(field, "required")
        for field, type_name in policy["types"].items():
            value = row.get(field)
            if value is None or value == "":
                continue
            valid = ((type_name == "string" and isinstance(value, str)) or
                     (type_name == "number" and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)) or
                     (type_name == "integer" and isinstance(value, int) and not isinstance(value, bool)))
            if not valid:
                error(field, "type")
        for field in policy["unique"]:
            if row.get(field) not in (None, "") and counts[field][canonical_json(row[field])] > 1:
                error(field, "duplicate")
        for field in policy["positive"]:
            value = row.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and (not math.isfinite(value) or value <= 0):
                error(field, "positive")
        if row.get("currency") != policy["currency"]:
            error("currency", "currency")
    if not rows:
        errors.append({"row_id": "@empty", "field": "rows", "code": "empty"})
    return {"available": True, "valid": not errors, "errors": errors, "checked_row_ids": checked, "row_count": len(rows), "rule_version": policy["rule_version"]}


def select_review_sample(rows: list[dict[str, Any]], errors: list[dict[str, Any]], seed: str | int) -> list[str]:
    """Five valid rows (or all if fewer) plus every defective row, stably ordered."""
    ids = list(dict.fromkeys(str(row.get("row_id") or f"@index:{i}") for i, row in enumerate(rows)))
    defective = {str(error["row_id"]) for error in errors}
    normal = sorted((rid for rid in ids if rid not in defective), key=lambda rid: (digest(f"{seed}:{rid}"), rid))[:5]
    return normal + sorted(defective & set(ids))


def artifact_evidence(rows: list[dict[str, Any]], *, artifact_id: str = "catalog", version: str = "1", format: str = "json", policy: dict[str, Any] | None = None) -> dict[str, Any]:
    content = serialize_rows(rows, format)
    manifest = [{"name": f"catalog.{format}", "content_hash": digest(content), "size": len(content.encode("utf-8"))}]
    return {"artifact_id": artifact_id, "version": version, "format": format, "content": content,
            "content_hash": digest(content), "manifest": manifest, "manifest_hash": digest(canonical_json(manifest)),
            "rule_version": (policy or DEFAULT_POLICY)["rule_version"], "rows": read_artifact(content, format)}

def safe_artifact_name(name: Any) -> str:
    """Opaque manifest key only. Never resolve a host filesystem path."""
    if (not isinstance(name,str) or not name or len(name)>255 or name in {".",".."}
            or name!=name.strip() or name.endswith(".")
            or any(not character.isprintable() or character in '<>:"/\\|?*' for character in name)):
        raise ValueError("artifact_member_name_invalid")
    reserved={"CON","PRN","AUX","NUL",*(f"COM{i}" for i in range(1,10)),*(f"LPT{i}" for i in range(1,10))}
    if name.split(".")[0].upper() in reserved:
        raise ValueError("artifact_member_name_invalid")
    return name


def directory_artifact_evidence(files: list[dict], *, artifact_id: str = "catalog", version: str = "1", policy: dict | None = None) -> dict:
    """Build complete UTF-8 bundle evidence from explicit in-memory source text."""
    members=[]
    for source in files:
        name=safe_artifact_name(source["name"])
        format=source["format"]
        content=source["content"]
        if not isinstance(content,str):
            raise ValueError("artifact_member_content_unavailable")
        read_artifact(content,format)
        members.append({"name":name,"format":format,"content":content,"content_hash":digest(content),"size":len(content.encode("utf-8"))})
    members.sort(key=lambda item:item["name"])
    manifest=[{key:member[key] for key in ("name","format","content_hash","size")} for member in members]
    result={"artifact_id":artifact_id,"version":version,"format":"directory","files":members,
            "manifest":manifest,"manifest_hash":digest(canonical_json(manifest)),
            "content_hash":digest("directory-v1\n"+canonical_json(manifest)),
            "rule_version":(policy or DEFAULT_POLICY)["rule_version"]}
    result["rows"]=[row for member in members for row in read_artifact(member["content"],member["format"])]
    read_artifact_evidence(result)
    return result


def read_artifact_evidence(data: dict) -> list[dict]:
    """Recompute complete bytes, metadata and aggregate rows, without disk access."""
    format=data.get("format")
    manifest=data.get("manifest")
    if not isinstance(manifest,list) or not manifest:
        raise ValueError("artifact_manifest_unavailable")
    if format in {"json","csv"}:
        content=data.get("content")
        if not isinstance(content,str) or data.get("files") is not None:
            raise ValueError("artifact_content_unavailable")
        if len(manifest)!=1 or not isinstance(manifest[0],dict):
            raise ValueError("artifact_manifest_invalid")
        entry=manifest[0]
        safe_artifact_name(entry.get("name"))
        expected={"name":entry["name"],"content_hash":digest(content),"size":len(content.encode("utf-8"))}
        if "format" in entry:
            expected["format"]=format
        if type(entry.get("size")) is not int or entry!=expected or digest(content)!=data.get("content_hash"):
            raise ValueError("artifact_content_binding_mismatch")
        rows=read_artifact(content,format)
    elif format=="directory":
        members=data.get("files")
        if not isinstance(members,list) or not members or data.get("content") is not None:
            raise ValueError("artifact_members_unavailable")
        names=set()
        expected=[]
        rows=[]
        for member in members:
            if not isinstance(member,dict) or set(member)!={"name","format","content","content_hash","size"}:
                raise ValueError("artifact_member_evidence_incomplete")
            name=safe_artifact_name(member["name"])
            if name.casefold() in names:
                raise ValueError("artifact_member_duplicate")
            names.add(name.casefold())
            content=member["content"]
            if not isinstance(content,str) or member["format"] not in {"json","csv"}:
                raise ValueError("artifact_member_format_or_bytes_unavailable")
            if type(member["size"]) is not int or member["size"]!=len(content.encode("utf-8")) or member["content_hash"]!=digest(content):
                raise ValueError("artifact_member_content_binding_mismatch")
        for member in sorted(members,key=lambda item:item["name"]):
            expected.append({key:member[key] for key in ("name","format","content_hash","size")})
            rows.extend(read_artifact(member["content"],member["format"]))
        if manifest!=expected or data.get("content_hash")!=digest("directory-v1\n"+canonical_json(expected)):
            raise ValueError("artifact_bundle_binding_mismatch")
    else:
        raise ValueError("artifact_format_unavailable")
    if digest(canonical_json(manifest))!=data.get("manifest_hash"):
        raise ValueError("artifact_manifest_hash_mismatch")
    if rows!=data.get("rows"):
        raise ValueError("declared_rows_disagree_with_content")
    return rows
