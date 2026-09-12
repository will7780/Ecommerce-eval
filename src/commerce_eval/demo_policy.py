"""Bounded deterministic catalog policy over public input and observed receipts only."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from commerce_eval.contracts.scenarios import CandidateInputV1
from commerce_eval.core.evidence import snapshot_hash


@dataclass(frozen=True)
class PolicyAction:
    tool_id: str
    arguments: dict[str, Any]
    tool_call_id: str
    capability: str
    stage: str


@dataclass(frozen=True)
class PolicyOutcome:
    outcome: str
    reason: str
    failed: bool = False


class CatalogPolicy:
    """No environment object, case contract, fixture plan or evaluator data."""

    def __init__(self, public: CandidateInputV1, capabilities: list[dict], *, call_prefix: str, max_steps: int = 24):
        self.public = public.model_copy(deep=True)
        self.tools = {item["capability_id"]: deepcopy(item) for item in capabilities}
        self.prefix = call_prefix
        self.max_steps = max(1, min(64, max_steps))
        self.text = self.public.message.lower()
        self.done = set()
        self.rows = []
        self.artifact = {}
        self.facts = {}
        self.rules = []
        self.pending = None
        self.terminal = None
        self.calls = 0
        self.read_failed = False
        self.retry_rows = []
        self.inventory_retried = False
        self.validation = None
        self.active_rule = None
        self.generation_retry = False
        self.source_file = None
        for asset in self.public.assets:
            data = asset.get("content")
            if isinstance(asset.get("rows"), list):
                if self.source_file is not None:
                    self.terminal = PolicyOutcome("blocked", "ambiguous_input_file", True)
                self.source_file = asset.get("asset_id")
            if isinstance(data, Mapping) and isinstance(data.get("facts"), Mapping):
                self.facts.update(deepcopy(data["facts"]))
            if isinstance(data, list):
                self.rules.extend(row for row in data if isinstance(row, Mapping) and "scope" in row and "text" in row)
        stores = {str(row.get("scope", {}).get("store")) for row in self.rules if row.get("scope", {}).get("store")}
        mentioned = [store for store in stores if re.search(r"\b" + re.escape(store.lower()) + r"\b", self.text)]
        if len(mentioned) == 1 and not re.search(r"\b\w+ and \w+ stores\b", self.text):
            self.facts["store"] = mentioned[0]
        self.want_review = bool(re.search(r"\breview\b|\bvalidate\b", self.text))
        no_publish = bool(re.search(r"do not publish|no publication|without publish|don't publish|preview.only authorization", self.text))
        self.want_publish = not no_publish and bool(re.search(r"\bpublish\b|\bpublication\b", self.text))
        self.want_draft = self.want_publish or bool(re.search(r"\bdraft\b|\bgenerate\b|\bprepare\b|\bcreate.*catalog|\bvalidate\b|\breview\b", self.text))
        self.want_preview = bool(re.search(r"\bpreview\b|\bshow\b|\bcompare\b", self.text))
        self.want_inventory = bool(re.search(r"\binventory\b|\bstock\b|\bavailability\b", self.text)) and not bool(re.search(r"do not .*inventory|without .*inventory|optional inventory", self.text))
        self.want_comparison = bool(re.search(r"\bcompare\b|\bcomparison\b", self.text))
        self.want_export = bool(re.search(r"\bexport\b", self.text))
        self.export_pending = False
        self.want_audit = bool(re.search(r"\baudit\b", self.text))
        self.want_prices = bool(re.search(r"\b(?:query|check|show|read)\b.*\bprices?\b", self.text))
        self.want_rules = "company" in self.text or "policy" in self.text or "rules" in self.text
        self.want_preflight = "health" in self.text or "preflight" in self.text
        self.want_risk = "risk" in self.text
        self.followup_stock = bool(re.search(r"ask whether.*stock|after the preview.*stock", self.text))
        self.cancel_only = self.want_publish and bool(re.search(r"ask whether to publish", self.text))
        self.query = {}
        number_words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "ten": 10, "twenty": 20}
        limit = re.search(r"(?:at most|row limit of|limit of) (\d+|one|two|three|four|five|six|ten|twenty)(?:\s|[.,])", self.text)
        if limit:
            self.query["limit"] = int(limit[1]) if limit[1].isdigit() else number_words[limit[1]]
        elif re.search(r"\b20[- ]row|\b20\b.*\bproducts|\b20\b.*\brows", self.text):
            self.query["limit"] = 20
        price = re.search(r"(?:below|at most|maximum price of|priced at most)\s*(?:[a-z]{3}\s*)?(\d+(?:\.\d+)?)", self.text)
        if price:
            self.query["max_price"] = float(price[1])
        category = re.search(r"(?:only|preview.*?'s)\s+([a-z]+) products", self.text)
        if category:
            self.query["category"] = category[1]
        for key in ("limit", "max_price", "category", "site"):
            if key not in self.query and self.facts.get(key) is not None:
                self.query[key] = self.facts[key]
        site = re.search(r"\b(?:site|marketplace)\s*[:=]?\s*([a-z]{2})\b", self.text)
        if site:
            self.query["site"] = site[1].upper()
        self.generation_capability = next((capability for capability in
            ("catalog.generate_listing", "catalog.generate_alternative", "artifact.prepare")
            if capability in self.tools), "catalog.generate_listing")
        self.clarify = []
        if re.search(r"ask.*(?:which store|session's store)|ask which one", self.text) or not self.facts.get("store"):
            self.clarify.append("store")
        if re.search(r"ask.*(?:maximum price|price limit|limit first)|ask for final parameters|ask me for the limit", self.text):
            self.clarify.append("max_price")
        if self.want_draft and self._requires(self.generation_capability, "input_file") and not self.source_file:
            self.clarify.append("input_file")
        if re.search(r"\b(?:switch|change) (?:the )?company\b|\bnew task\b", self.text):
            self.terminal = PolicyOutcome("blocked", "unsupported_context_transition", True)
        self.seed = snapshot_hash({"message": self.public.message, "assets": [a.get("asset_id") for a in self.public.assets]})[:16]
        if not re.search(r"catalog|listing|preview|products|stock|inventory|margin|audit|export", self.text):
            self.terminal = PolicyOutcome("blocked", "unsupported_public_intent", True)
        elif re.search(r"tamper|without increasing its version|replace a rejected revision|corrected version|replace.*(?:file|artifact)|after approval.*(?:modify|add|remove)", self.text):
            self.terminal = PolicyOutcome("blocked", "unsupported_revision_workflow", True)

    def _requires(self, capability, field):
        tool = self.tools.get(capability, {})
        pointer = tool.get("argument_mapping", {}).get(field, field)
        parts = pointer[1:].split("/") if pointer.startswith("/") else [pointer]
        schema = tool.get("input_schema", {})
        for part in parts:
            part = part.replace("~1", "/").replace("~0", "~")
            if part not in schema.get("required", []):
                return False
            schema = schema.get("properties", {}).get(part, {})
        return True

    def _rule(self):
        if self.active_rule is not None:
            return self.active_rule
        scoped = [rule for rule in self.rules if rule.get("status") != "expired"
                  and rule.get("scope", {}).get("store") in {None, self.facts.get("store")}
                  and "artifact" in rule.get("scope", {}).get("operations", ["artifact"])
                  and isinstance(rule.get("policy"), Mapping)]
        def rank(rule):
            version = tuple((1, int(part)) if part.isdigit() else (0, part)
                            for part in re.split(r"(\d+)", str(rule.get("version", ""))))
            return rule.get("priority", 0), version
        if not scoped:
            return {}
        active = max(scoped, key=rank)
        if any(rank(row) == rank(active) and row["policy"] != active["policy"] for row in scoped):
            self.terminal = PolicyOutcome("blocked", "ambiguous_company_rules", True)
            return {}
        return active

    def _generation_arguments(self):
        args = {}
        if self.generation_capability != "artifact.prepare":
            args.update({**self.query, "input_file": self.source_file, "store": self.facts.get("store")})
            # Query-only fields are not generation parameters.
            args.pop("max_price", None)
        currency = re.search(r"\b(?:USD|EUR|GBP|JPY|CAD|AUD)\b", self.public.message)
        if currency:
            args["currency"] = currency[0]
        if "csv" in self.text:
            args["format"] = "csv"
        rule = self._rule().get("policy", {})
        if rule.get("rule_version"):
            args["rule_version"] = rule["rule_version"]
        percent = re.search(r"(\d+(?:\.\d+)?)\s*(?:percent|%)\s*margin", self.text.split("audit", 1)[0])
        if percent and self.generation_capability != "artifact.prepare" and "margin" in self.text:
            args["margin_percent"] = float(percent[1])
            if args["margin_percent"] < rule.get("minimum_margin_percent", 0):
                self.terminal = PolicyOutcome("blocked", "mandatory_company_margin_conflict")
        if "primary template" in self.text:
            args["template"] = "fallback" if self.generation_retry else "primary"
        return args

    def _action(self, capability, arguments, stage):
        tool = self.tools.get(capability)
        if tool is None:
            self.terminal = PolicyOutcome("blocked", "capability_unavailable:" + capability, True)
            return self.terminal
        self.calls += 1
        call_id = self.prefix + ("-publish" if capability == "catalog.publish" else f"-call-{self.calls}")
        encoded = {}
        mapping = tool.get("argument_mapping", {})
        scales = tool.get("unit_scale", {})
        for key, value in arguments.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                value *= scales.get(key, 1)
            path = mapping.get(key, key)
            parts = [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")] if path.startswith("/") else [path]
            parent = encoded
            for part in parts[:-1]:
                parent = parent.setdefault(part, {})
            parent[parts[-1]] = deepcopy(value)
        if list(Draft202012Validator(tool.get("input_schema", {})).iter_errors(encoded)):
            self.terminal = PolicyOutcome("blocked", "public_parameter_schema_invalid", True)
            return self.terminal
        return PolicyAction(tool["tool_id"], encoded, call_id, capability, stage)

    def publication(self):
        tool = self.tools.get("catalog.publish")
        if not tool:
            return None
        fields = ("artifact_id", "version", "content_hash", "manifest_hash", "rule_version", "review_id")
        if not all(self.artifact.get(key) for key in fields):
            return None
        count = self.calls
        action = self._action("catalog.publish", {key: self.artifact[key] for key in fields}, "publish")
        self.calls = count
        return action if isinstance(action, PolicyAction) else None

    def next_action(self):
        if self.terminal:
            return self.terminal
        if self.pending:
            raise ValueError("policy_waiting_for_explicit_response")
        if self.calls >= self.max_steps:
            return PolicyOutcome("blocked", "policy_step_limit", True)
        if self.clarify and "clarify" not in self.done:
            return self._action("interaction.ask", {"fields": self.clarify}, "clarify")
        if self.cancel_only and "risk" not in self.done:
            return self._action("interaction.ask", {"fields": ["publish"], "purpose": "risk"}, "risk")
        if self.want_preflight and "preflight" not in self.done:
            if "source.validate" in self.tools and self.source_file:
                return self._action("source.validate", {"input_file": self.source_file}, "preflight")
            return self._action("workflow.plan", {"action": "preflight"}, "preflight")
        if self.want_rules and "rules" not in self.done:
            return self._action("rules.read", {"store": self.facts.get("store")}, "rules")
        if self.want_draft and "prepare" not in self.done:
            args = self._generation_arguments()
            if self.terminal:
                return self.terminal
            return self._action(self.generation_capability, args, "prepare")
        if "read" not in self.done and not self.want_draft and (self.want_preview or self.want_inventory or self.want_comparison or self.want_prices or self.want_export):
            if self.read_failed:
                if "catalog.search" not in self.tools or "unapproved source" in self.text:
                    return PolicyOutcome("blocked", "source_unavailable")
                return self._action("catalog.search", {**self.query, "source": "mirror"}, "read")
            if "indexed" in self.text or "bulk reader is unavailable" in self.text:
                return self._action("catalog.search", {**self.query, "source": "index"}, "read")
            return self._action("catalog.read", {**self.query, "store": self.facts.get("store")}, "read")
        if self.want_prices and "prices" not in self.done:
            ids = re.findall(r"\brow\d+\b", self.text) or [row["row_id"] for row in self.rows if row.get("row_id")]
            return self._action("pricing.query", {"row_ids": ids}, "prices")
        if self.want_comparison and "compare" not in self.done:
            return self._action("catalog.search", {"source": "suggestions"}, "compare")
        if self.followup_stock and "preview" not in self.done:
            return self._action("catalog.preview", {}, "preview")
        if self.followup_stock and "followup" not in self.done:
            return self._action("interaction.ask", {"fields": ["include_stock"]}, "followup")
        if self.want_inventory and "inventory" not in self.done:
            row_ids = self.retry_rows or re.findall(r"\brow\d+\b", self.text) or [row["row_id"] for row in self.rows if row.get("row_id")]
            return self._action("inventory.read", {"row_ids": row_ids}, "inventory")
        if self.want_preview and "preview" not in self.done:
            mode = "price_comparison" if self.want_comparison else "availability" if self.want_inventory else "list"
            return self._action("catalog.preview", {"mode": mode}, "preview")
        if self.want_review or self.want_publish:
            for stage, capability, args in (
                ("check", "artifact.check", {}), ("sample", "artifact.sample", {"seed": self.seed}), ("review", "artifact.review", {}),
            ):
                if stage not in self.done:
                    return self._action(capability, args, stage)
        if self.want_publish and self.validation and not self.validation.get("valid"):
            return PolicyOutcome("blocked", "artifact_validation_failed")
        if self.want_publish and self.want_risk and "risk" not in self.done:
            return self._action("interaction.ask", {"fields": ["publish"], "purpose": "risk"}, "risk")
        if self.want_publish and "publish" not in self.done:
            action = self.publication()
            if action is None:
                return PolicyOutcome("blocked", "artifact_binding_unavailable", True)
            self.calls += 1
            return action
        if self.want_export and "export" not in self.done:
            return self._action("job.status" if self.export_pending else "catalog.export",
                                {"job_id": self.prefix + "-export"}, "export_status" if self.export_pending else "export")
        if self.want_audit and "audit" not in self.done:
            match = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:percent|%)", self.text)
            if not match:
                return PolicyOutcome("blocked", "audit_threshold_missing", True)
            return self._action("pricing.audit_margin", {**self.artifact, "threshold_percent": float(match[1])}, "audit")
        if not self.done - {"clarify", "rules", "preflight"}:
            return PolicyOutcome("blocked", "unsupported_public_workflow", True)
        return PolicyOutcome("completed", "observed_workflow_completed")

    def observe(self, action: PolicyAction, receipt: Mapping[str, Any]):
        data = deepcopy(dict(receipt))
        self.artifact.update(data.get("artifact", {}))
        for key in ("artifact_id", "version", "content_hash", "manifest_hash", "rule_version", "review_id"):
            if data.get(key) is not None:
                self.artifact[key] = data[key]
        status = data.get("status")
        if action.stage == "export" and status == "timeout":
            self.export_pending = True
            return
        if action.stage == "export_status":
            if status != "ok" or data.get("job", {}).get("status") != "completed":
                self.terminal = PolicyOutcome("blocked", "export_status_unresolved")
            else:
                self.done.add("export")
            return
        if status == "pending":
            self.pending = action.stage
            return
        if action.stage == "prepare" and status in {"ok", "success", "completed"} and not self.artifact.get("artifact_id"):
            self.terminal = PolicyOutcome("blocked", "generation_artifact_missing")
            return
        if status not in {"ok", "success", "completed", "partial"}:
            if action.stage == "prepare" and data.get("error_type") == "generation_failed" and not self.generation_retry:
                if "fallback template" in self.text:
                    self.generation_retry = True
                    return
                if action.capability == "catalog.generate_listing" and "catalog.generate_alternative" in self.tools:
                    self.generation_capability = "catalog.generate_alternative"
                    self.generation_retry = True
                    return
            if action.stage == "read" and action.capability == "catalog.read" and data.get("error_type") == "source_unavailable":
                self.read_failed = True
                return
            self.terminal = PolicyOutcome("blocked", str(data.get("error_type") or "tool_execution_failed"))
            return
        if action.stage == "preflight" and (data.get("healthy") is False or data.get("validation", {}).get("valid") is False):
            self.terminal = PolicyOutcome("blocked", "source_unhealthy")
        if isinstance(data.get("rows"), list):
            self.rows = deepcopy(data["rows"])
        if isinstance(data.get("effective_rule"), Mapping):
            self.active_rule = deepcopy(data["effective_rule"])
        if isinstance(data.get("rules"), list):
            self.rules = deepcopy(data["rules"])
        if isinstance(data.get("validation"), Mapping):
            self.validation = deepcopy(data["validation"])
        if action.stage == "inventory" and data.get("failed_row_ids"):
            if self.inventory_retried:
                self.terminal = PolicyOutcome("blocked", "inventory_retry_exhausted")
            else:
                self.inventory_retried = True
                self.retry_rows = list(data["failed_row_ids"])
            return
        self.done.add(action.stage)

    def accept_response(self, response: Mapping[str, Any]):
        stage = self.pending
        if stage is None:
            raise ValueError("policy_response_without_pending")
        data = dict(response.get("fields", response))
        decision = data.get("decision", data.get("answer"))
        if stage in {"review", "risk"}:
            if decision in {"reject", "rejected", "decline", "declined", "deny", "denied", "no", "cancel", "cancelled"}:
                self.terminal = PolicyOutcome("cancelled" if stage == "risk" else "blocked", "user_declined")
            elif decision not in {"approve", "approved", "yes", "continue"}:
                raise ValueError("policy_explicit_decision_required")
        elif stage == "clarify":
            if any(data.get(key) is None for key in self.clarify):
                self.terminal = PolicyOutcome("blocked", "required_input_unavailable")
            self.facts.update(data)
            if "input_file" in data:
                self.source_file = data["input_file"]
            self.query.update({key: data[key] for key in ("max_price", "limit", "category", "site") if key in data})
        elif stage == "followup":
            self.want_inventory = data.get("include_stock") is True
        self.pending = None
        self.done.add(stage)
