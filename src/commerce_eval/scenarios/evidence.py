"""Causal receipt helpers shared by the public scenario and artifact audits."""

from __future__ import annotations

from .bindings import decode_evidence


CALL_KINDS={"tool.call","tool.request","tool_call"}
OBSERVATIONS={"observation","tool.observation","tool.result","execution.receipt"}
SUCCESS={"ok","success","completed","dry_run"}


def receipt_data(event, binding=None) -> dict:
    value=event.attributes.get("result",event.attributes)
    if not isinstance(value,dict):
        return {}
    return decode_evidence(binding,value) if binding else value


def linked_receipts(events, call, binding=None, *, before=None):
    result=[]
    for event in events:
        if event.kind not in OBSERVATIONS or event.sequence<=call.sequence or (before is not None and event.sequence>=before):
            continue
        direct=event.attributes.get("tool_call_id")
        if direct and direct!=call.event_id:
            continue
        if not direct and event.parent_event_id!=call.event_id:
            continue
        if event.attributes.get("tool_id") not in {None,call.attributes.get("tool_id") or call.name}:
            continue
        data=receipt_data(event,binding)
        if data.get("tool_call_id") not in {None,call.event_id}:
            continue
        if not isinstance(data.get("receipt_id",data.get("execution_id")),str) or not data.get("receipt_id",data.get("execution_id")):
            continue
        result.append((event,data))
    return sorted(result,key=lambda pair:pair[0].sequence)


def receipt_succeeded(event, data) -> bool:
    return event.status.value=="ok" and data.get("status",data.get("observation_status")) in SUCCESS and not data.get("error_type")


def latest_receipt(events,call,binding=None,*,before=None,success=True):
    rows=linked_receipts(events,call,binding,before=before)
    if not rows:
        return None
    event,data=rows[-1]
    return (event,data) if not success or receipt_succeeded(event,data) else None
