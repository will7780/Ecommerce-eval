"""Business acceptance is one condition gate, not a second weighted score."""

from commerce_eval.business.verifiers import evaluate_business_requirements


class BusinessAcceptanceEvaluator:
    metric_id = "business_acceptance_pass"
    metric_version = "1.0"
    group = "business"
    required_evidence = ("business_evidence",)

    def evaluate(self, context):
        return evaluate_business_requirements(context.case, context.business_evidence)
