"""Neutral commerce capability ontology and reusable workflow constraints."""

from __future__ import annotations

from typing import Any


CAPABILITY_ONTOLOGY: dict[str, dict[str, Any]] = {
    "catalog.generate_listing": {"stage": "prepare", "default_risk": "L2"},
    "catalog.inspect_listing": {"stage": "verify", "default_risk": "L1"},
    "catalog.upload_listing": {"stage": "publish", "default_risk": "L4"},
    "pricing.audit_margin": {"stage": "verify", "default_risk": "L2"},
    "promotion.prepare_enrollment": {"stage": "prepare", "default_risk": "L2"},
    "promotion.enroll": {"stage": "publish", "default_risk": "L4"},
    "inventory.sync": {"stage": "operate", "default_risk": "L4"},
    "orders.export": {"stage": "observe", "default_risk": "L2"},
}

WORKFLOW_CONSTRAINTS: dict[str, list[str]] = {
    "listing_launch": [
        "catalog.generate_listing",
        "catalog.upload_listing",
        "pricing.audit_margin",
    ],
    "promotion_launch": ["promotion.prepare_enrollment", "promotion.enroll"],
}


def commerce_pack_manifest() -> dict[str, Any]:
    return {
        "pack_id": "commerce_ops",
        "version": "1.0.0",
        "capabilities": CAPABILITY_ONTOLOGY,
        "workflow_constraints": WORKFLOW_CONSTRAINTS,
        "metric_algorithms": [],
    }

