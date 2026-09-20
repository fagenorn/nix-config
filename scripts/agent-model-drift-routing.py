"""Pure routing comparison logic for agent-model-drift."""
from __future__ import annotations

import json


DRIFT_CODES = {
    "REQUEST_DECLARATION_MISMATCH",
    "OBSERVED_HOST_PROHIBITED",
    "OBSERVED_MODEL_PROHIBITED",
    "OBSERVED_EFFORT_PROHIBITED",
    "ESCALATION_INVALID",
}


def _finding(code, run_id, dispatch, role, count):
    return {"code": code, "run_id": run_id, "dispatch": dispatch,
            "role": role, "count": count}


def _indexes(matrix):
    dispatches = {item["id"]: item for item in matrix["dispatch_sites"]}
    by_role = {}
    for item in matrix["dispatch_sites"]:
        by_role.setdefault(item["role"], []).append(item)
    return dispatches, by_role


def classify_concrete(catalog: dict, host: str, kind: str, tier: str,
                      concrete: str) -> str:
    values = catalog.get(host, {}).get(kind, {}).get(tier, {})
    allowed = values.get("allowed", [])
    prohibited = values.get("prohibited", [])
    if concrete in allowed and concrete in prohibited:
        raise AssertionError("concrete value is both allowed and prohibited")
    if concrete in allowed:
        return "allowed"
    if concrete in prohibited:
        return "prohibited"
    return "unclassified"


def declaration_for(observation: dict, matrix: dict) -> tuple[dict | None, list[dict]]:
    """Resolve carried dispatches first, then unambiguous role-only declarations."""
    dispatches, by_role = _indexes(matrix)
    declaration = observation["declaration"]
    dispatch_id, role = declaration["dispatch_id"], declaration["role"]
    hosts = matrix.get("_routing_dispatch_hosts", {})
    findings = []
    if dispatch_id is not None:
        site = dispatches.get(dispatch_id)
        if site is None or role != site["role"]:
            # A carried dispatch is authoritative request evidence.  An unknown
            # ID or disagreement with its carried role proves declaration drift.
            findings.append("REQUEST_DECLARATION_MISMATCH")
            return None, findings
        host = hosts.get(dispatch_id)
        if host is None:
            findings.append("ROLE_AMBIGUOUS")
            return None, findings
        return {"dispatch_id": dispatch_id, "role": site["role"],
                "host": host, "model": site["model"], "effort": site["effort"],
                "authority": declaration["authority"]}, findings
    if observation["escalation"] is not None:
        findings.append("DISPATCH_REQUIRED")
        return None, findings
    if role is None or role not in matrix["roles"]:
        findings.append("ROLE_AMBIGUOUS")
        return None, findings
    sites = by_role.get(role, [])
    role_hosts = {hosts.get(site["id"]) for site in sites}
    if not sites or None in role_hosts or len(role_hosts) != 1:
        findings.append("ROLE_AMBIGUOUS")
        return None, findings
    if role == "reviewer-lite":
        findings.append("DISPATCH_REQUIRED")
        return None, findings
    spec = matrix["roles"][role]
    return {"dispatch_id": None, "role": role, "host": next(iter(role_hosts)),
            "model": spec["model"], "effort": spec["effort"],
            "authority": declaration["authority"]}, findings


def _valid_escalation_lineage(observation: dict, matrix: dict) -> bool:
    escalation = observation["escalation"]
    target = observation["declaration"]["dispatch_id"]
    source = None if escalation is None else escalation["source_dispatch_id"]
    dispatches, _ = _indexes(matrix)
    return target in dispatches and source in dispatches and source != target


def validate_escalation(observation: dict, matrix: dict, baseline: dict) -> bool:
    escalation = observation["escalation"]
    return (_valid_escalation_lineage(observation, matrix)
            and escalation is not None
            and escalation["reason_code"] in baseline["escalation_reason_codes"])


def evaluate_observation(observation: dict, matrix: dict, baseline: dict,
                         run_id: str, coverage: dict, *,
                         baseline_usable: bool = True) -> tuple[dict, list[dict], int]:
    """Return one inspectable comparison, its findings, and evaluated events."""
    prepared = dict(matrix)
    prepared["_routing_dispatch_hosts"] = baseline["dispatch_hosts"]
    resolved, declaration_codes = declaration_for(observation, prepared)
    count = observation["count"]
    observed = observation["observed"]
    requested = observation["requested"]
    dispatch = observation["declaration"]["dispatch_id"]
    role = observation["declaration"]["role"]
    findings = [_finding(code, run_id, dispatch, role, count)
                for code in declaration_codes]

    escalation = observation["escalation"]
    public_escalation = None
    if escalation is not None:
        public_escalation = {"source_dispatch_id": escalation["source_dispatch_id"],
                             "target_dispatch_id": dispatch,
                             "reason_code": escalation["reason_code"]}
        if (not _valid_escalation_lineage(observation, matrix)
                or (baseline_usable
                    and not validate_escalation(observation, matrix, baseline))):
            findings.append(_finding("ESCALATION_INVALID", run_id, dispatch, role, count))

    if observed["model"] is None:
        findings.append(_finding("EXECUTION_MODEL_MISSING", run_id, dispatch,
                                 role, count))
    if observed["effort"] is None:
        findings.append(_finding("EXECUTION_EFFORT_MISSING", run_id, dispatch,
                                 role, count))

    if resolved is not None:
        for key in ("model", "effort"):
            if requested[key] is not None and requested[key] != resolved[key]:
                findings.append(_finding("REQUEST_DECLARATION_MISMATCH", run_id,
                                         dispatch, role, count))
                break
        if (baseline_usable and requested["host"] is not None
                and requested["host"] != resolved["host"]):
            findings.append(_finding("REQUEST_DECLARATION_MISMATCH", run_id,
                                     dispatch, role, count))

        if (baseline_usable and observed["host"] is not None
                and observed["host"] != resolved["host"]):
            findings.append(_finding("OBSERVED_HOST_PROHIBITED", run_id, dispatch,
                                     role, count))

        model_status = None
        effort_status = None
        if not baseline_usable:
            pass
        elif observed["model"] is None:
            pass
        elif observed["host"] is None:
            findings.append(_finding("MODEL_UNCLASSIFIED", run_id, dispatch, role, count))
        else:
            status = classify_concrete(baseline["catalog"], observed["host"],
                                       "models", resolved["model"], observed["model"])
            if status == "prohibited":
                findings.append(_finding("OBSERVED_MODEL_PROHIBITED", run_id, dispatch,
                                         role, count))
                model_status = status
            elif status == "unclassified":
                findings.append(_finding("MODEL_UNCLASSIFIED", run_id, dispatch,
                                         role, count))
            else:
                model_status = status

        if not baseline_usable:
            pass
        elif observed["effort"] is None:
            pass
        elif observed["host"] is None:
            findings.append(_finding("EFFORT_UNCLASSIFIED", run_id, dispatch, role, count))
        else:
            status = classify_concrete(baseline["catalog"], observed["host"],
                                       "efforts", resolved["effort"], observed["effort"])
            if status == "prohibited":
                findings.append(_finding("OBSERVED_EFFORT_PROHIBITED", run_id, dispatch,
                                         role, count))
                effort_status = status
            elif status == "unclassified":
                findings.append(_finding("EFFORT_UNCLASSIFIED", run_id, dispatch,
                                         role, count))
            else:
                effort_status = status
        evaluated = (count if observed["host"] is not None
                     and model_status in ("allowed", "prohibited")
                     and effort_status in ("allowed", "prohibited") else 0)
    else:
        evaluated = 0

    comparison = {"run_id": run_id, "dispatch": dispatch, "role": role,
                  "count": count, "declaration": resolved,
                  "requested": dict(requested),
                  "observed": {key: observed[key] for key in ("host", "model", "effort")},
                  "coverage": coverage, "escalation": public_escalation}
    return comparison, findings, evaluated


def aggregate_findings(findings):
    grouped = {}
    for item in findings:
        key = (item["code"], item["run_id"], item["dispatch"], item["role"])
        grouped[key] = grouped.get(key, 0) + item["count"]
    return [{"code": code, "run_id": run_id, "dispatch": dispatch,
             "role": role, "count": count}
            for (code, run_id, dispatch, role), count in sorted(
                grouped.items(), key=lambda item: (item[0][0], item[0][1] or "",
                                                    item[0][2] or "", item[0][3] or "",
                                                    item[1]))]


def comparison_key(item):
    return (item["run_id"], item["dispatch"] or "", item["role"] or "",
            json.dumps(item["requested"], sort_keys=True, separators=(",", ":")),
            json.dumps(item["observed"], sort_keys=True, separators=(",", ":")),
            json.dumps(item["escalation"], sort_keys=True, separators=(",", ":")))
