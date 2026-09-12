"""Select declared company policy by scope, priority and natural version order."""

from __future__ import annotations

import re
from copy import deepcopy


def effective_rule(rules: list[dict], store: str | None, operation: str = "artifact") -> dict | None:
    applicable=[]
    for rule in rules:
        if rule.get("status")=="expired":
            continue
        scope=rule.get("scope",{})
        if scope.get("store") not in {None,store} or operation not in scope.get("operations",[operation]):
            continue
        if not isinstance(rule.get("policy"),dict):
            continue
        version=tuple((1,int(part)) if part.isdigit() else (0,part) for part in re.split(r"(\d+)",str(rule.get("version",""))))
        applicable.append(((rule.get("priority",0),version),rule))
    if not applicable:
        return None
    highest=max(key for key,_ in applicable)
    selected=[rule for key,rule in applicable if key==highest]
    if any(rule["policy"]!=selected[0]["policy"] for rule in selected[1:]):
        raise ValueError("company_policy_ambiguous")
    return deepcopy(selected[0])
