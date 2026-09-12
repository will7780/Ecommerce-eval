"""Built-in metric packs."""

from .commerce import CAPABILITY_ONTOLOGY, WORKFLOW_CONSTRAINTS, commerce_pack_manifest
from .core import core_evaluators
from .core_evidence import core_evidence_evaluators
from .governance import governance_evaluators
from .governance_evidence import governance_evidence_evaluators


def all_evaluators():
    from .business import BusinessAcceptanceEvaluator
    from .artifacts import artifact_evaluators
    from commerce_eval.scenarios.reference import scenario_evaluators

    return [BusinessAcceptanceEvaluator(), *artifact_evaluators(), *scenario_evaluators(), *core_evaluators(), *core_evidence_evaluators(), *governance_evaluators(), *governance_evidence_evaluators()]

def available_evaluators():
    """Return built-ins plus third-party entry-point evaluators."""
    from commerce_eval.core import EvaluatorRegistry

    registry = EvaluatorRegistry(all_evaluators())
    registry.load_entry_points()
    return registry.list()


__all__ = [
    "CAPABILITY_ONTOLOGY",
    "WORKFLOW_CONSTRAINTS",
    "all_evaluators",
    "available_evaluators",
    "commerce_pack_manifest",
    "core_evidence_evaluators",
    "core_evaluators",
    "governance_evidence_evaluators",
    "governance_evaluators",
]

