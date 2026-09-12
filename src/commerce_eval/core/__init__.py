"""Framework-neutral evaluation core."""

from .engine import EvaluationEngine
from .gates import evaluate_gates
from .normalizer import ContractNormalizer, TraceNormalizer, canonical_json, content_checksum
from .redaction import contains_secret, redact_declared_fields, redact_recursive, redact_text
from .registry import EvaluatorRegistry

__all__ = [
    "ContractNormalizer",
    "EvaluationEngine",
    "EvaluatorRegistry",
    "TraceNormalizer",
    "canonical_json",
    "contains_secret",
    "redact_declared_fields",
    "content_checksum",
    "evaluate_gates",
    "redact_recursive",
    "redact_text",
]

