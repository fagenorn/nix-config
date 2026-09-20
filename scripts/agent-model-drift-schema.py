"""Strict wire-format validation for the model-drift reporter."""
from __future__ import annotations

import hashlib
import importlib.machinery
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_METRICS = ("spawn_attempts", "capacity_rejections", "waits", "follow_ups",
            "wait_input_tokens", "covered_input_tokens", "slot_capacity_seconds",
            "claimed_slot_seconds")
_REASONS = {"timestamp_missing", "request_missing", "request_host_missing",
            "request_host_conflict", "result_missing", "child_missing",
            "dispatch_missing", "role_ambiguous", "execution_model_missing",
            "execution_effort_missing", "runtime_version_missing",
            "source_unsupported", "cohort_incomplete"}


class InputError(ValueError):
    """An untrusted input does not meet the closed wire contract."""


def _duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError("duplicate JSON object key")
        result[key] = value
    return result


def load_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_duplicates)
    except (OSError, UnicodeError, json.JSONDecodeError, InputError) as error:
        raise InputError("cannot load JSON input") from error
    return value


def canonical_digest(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def canonical_time(value):
    if not isinstance(value, str):
        raise InputError("timestamp must be RFC3339 UTC")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise InputError("timestamp must be RFC3339 UTC") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise InputError("timestamp must be RFC3339 UTC")
    canonical = parsed.isoformat(timespec="seconds").replace("+00:00", "Z")
    if value != canonical:
        raise InputError("timestamp must be canonical RFC3339 UTC")
    return parsed


def _closed(value, fields, pointer):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise InputError(pointer + " has wrong members")


def _nonnegative(value, pointer):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InputError(pointer + " must be a non-negative integer")


def _coverage(value, pointer):
    _closed(value, ("state", "eligible_events", "paired_events", "reasons"), pointer)
    _nonnegative(value["eligible_events"], pointer)
    _nonnegative(value["paired_events"], pointer)
    if value["paired_events"] > value["eligible_events"] or value["state"] not in ("full", "partial", "none"):
        raise InputError(pointer + " is invalid")
    if not isinstance(value["reasons"], list):
        raise InputError(pointer + " reasons invalid")
    codes = []
    for item in value["reasons"]:
        _closed(item, ("code", "count"), pointer + "/reasons")
        if item["code"] not in _REASONS:
            raise InputError(pointer + " reason invalid")
        _nonnegative(item["count"], pointer)
        if item["count"] == 0:
            raise InputError(pointer + " reason invalid")
        codes.append(item["code"])
    if codes != sorted(set(codes)):
        raise InputError(pointer + " reasons must be sorted unique")
    expected = "full" if not codes else "partial" if value["paired_events"] else "none"
    if (value["state"] != expected or (value["state"] == "full" and
            value["paired_events"] != value["eligible_events"])):
        raise InputError(pointer + " state does not match coverage")


def _merged(values):
    reasons = {}
    for value in values:
        for item in value["reasons"]:
            reasons[item["code"]] = reasons.get(item["code"], 0) + item["count"]
    eligible = sum(value["eligible_events"] for value in values)
    paired = sum(value["paired_events"] for value in values)
    items = [{"code": code, "count": reasons[code]} for code in sorted(reasons)]
    return {"state": "full" if not items else "partial" if paired else "none",
            "eligible_events": eligible, "paired_events": paired, "reasons": items}


def _scheduling(value, pointer):
    _closed(value, _METRICS, pointer)
    for name in _METRICS:
        _coverage(value[name], pointer + "/" + name)


def _metric(value, pointer):
    _closed(value, ("value", "coverage", "cohort_digest"), pointer)
    _coverage(value["coverage"], pointer + "/coverage")
    if value["coverage"]["state"] == "full":
        if value["value"] is None:
            raise InputError(pointer + " full metric unavailable")
        _nonnegative(value["value"], pointer + "/value")
        if not isinstance(value["cohort_digest"], str) or not _DIGEST.fullmatch(value["cohort_digest"]):
            raise InputError(pointer + " metric identity invalid")
    elif value["value"] is not None or value["cohort_digest"] is not None:
        raise InputError(pointer + " unavailable metric has digest")


def _nullable_string(value, pointer):
    if value is not None and (not isinstance(value, str) or not value):
        raise InputError(pointer + " must be a non-empty string or null")


def _observation(value, pointer):
    _closed(value, ("declaration", "requested", "configured", "observed", "escalation",
                    "count", "first_event_at", "last_event_at"), pointer)
    _closed(value["declaration"], ("dispatch_id", "role", "authority"), pointer + "/declaration")
    if value["declaration"]["authority"] not in ("structured-dispatch", "runtime-agent-type", "unknown"):
        raise InputError(pointer + " declaration authority invalid")
    _nullable_string(value["declaration"]["dispatch_id"], pointer)
    _nullable_string(value["declaration"]["role"], pointer)
    for member in ("requested", "configured"):
        _closed(value[member], ("host", "model", "effort"), pointer + "/" + member)
        for key in value[member]: _nullable_string(value[member][key], pointer)
    _closed(value["observed"], ("host", "model", "effort", "authority"), pointer + "/observed")
    for key in ("host", "model", "effort"): _nullable_string(value["observed"][key], pointer)
    if value["observed"]["authority"] not in ("assistant-execution", "codex-rollout"):
        raise InputError(pointer + " observed authority invalid")
    if value["escalation"] is not None:
        _closed(value["escalation"], ("source_dispatch_id", "reason_code"), pointer + "/escalation")
        for key in value["escalation"]: _nullable_string(value["escalation"][key], pointer)
    _nonnegative(value["count"], pointer)
    if value["count"] == 0:
        raise InputError(pointer + " count invalid")
    first, last = canonical_time(value["first_event_at"]), canonical_time(value["last_event_at"])
    if first > last:
        raise InputError(pointer + " event order invalid")


def _telemetry(value, selected):
    _closed(value, ("schema_version", "producer", "event_window", "source_coverage", "runs"), "/execution_telemetry")
    if value["schema_version"] != 1:
        raise InputError("unsupported telemetry version")
    _closed(value["producer"], ("name", "version", "harness_versions"), "/execution_telemetry/producer")
    if value["producer"]["name"] != "agent-costs" or value["producer"]["version"] != 1:
        raise InputError("invalid telemetry producer")
    harness = value["producer"]["harness_versions"]
    if not isinstance(harness, dict) or set(harness) != set(selected):
        raise InputError("telemetry harness coverage invalid")
    for source, versions in harness.items():
        if versions is not None and (not isinstance(versions, list) or not all(isinstance(x, str) and x for x in versions) or versions != sorted(set(versions))):
            raise InputError("telemetry harness versions invalid")
    _closed(value["event_window"], ("start", "end"), "/execution_telemetry/event_window")
    for endpoint in ("start", "end"):
        if value["event_window"][endpoint] is not None:
            canonical_time(value["event_window"][endpoint])
    if ((value["event_window"]["start"] is None) != (value["event_window"]["end"] is None)):
        raise InputError("telemetry window must be bounded or absent")
    if value["event_window"]["start"] is not None and not (canonical_time(value["event_window"]["start"]) < canonical_time(value["event_window"]["end"])):
        raise InputError("telemetry window order invalid")
    source = value["source_coverage"]
    _closed(source, ("routing", "scheduling", "source_only"), "/execution_telemetry/source_coverage")
    _coverage(source["routing"], "/execution_telemetry/source_coverage/routing")
    _scheduling(source["scheduling"], "/execution_telemetry/source_coverage/scheduling")
    if not isinstance(source["source_only"], dict) or not set(source["source_only"]).issubset(set(selected)):
        raise InputError("source-only coverage invalid")
    if not isinstance(value["runs"], list):
        raise InputError("runs invalid")
    seen_sources = set()
    routing = []
    scheduling = {name: [] for name in _METRICS}
    for run in value["runs"]:
        _closed(run, ("run_id", "routing", "scheduling"), "/execution_telemetry/runs")
        if not isinstance(run["run_id"], str) or ":" not in run["run_id"]:
            raise InputError("run id invalid")
        run_source = run["run_id"].split(":", 1)[0]
        if run_source not in selected or run_source in source["source_only"]:
            raise InputError("run/source-only contribution invalid")
        seen_sources.add(run_source)
        _closed(run["routing"], ("coverage", "observations"), "/execution_telemetry/runs/routing")
        _coverage(run["routing"]["coverage"], "/execution_telemetry/runs/routing/coverage")
        if not isinstance(run["routing"]["observations"], list):
            raise InputError("routing observations invalid")
        observed = run["routing"]["observations"]
        for index, observation in enumerate(observed):
            _observation(observation, "/execution_telemetry/runs/routing/observations/" + str(index))
        if sum(item["count"] for item in observed) != run["routing"]["coverage"]["paired_events"]:
            raise InputError("routing observation counts do not match coverage")
        if observed != sorted(observed, key=lambda item: json.dumps({key: item[key] for key in ("declaration", "requested", "configured", "observed", "escalation")}, sort_keys=True, separators=(",", ":"))):
            raise InputError("routing observations must be canonical order")
        _closed(run["scheduling"], _METRICS, "/execution_telemetry/runs/scheduling")
        routing.append(run["routing"]["coverage"])
        for name in _METRICS:
            _metric(run["scheduling"][name], "/execution_telemetry/runs/scheduling/" + name)
            scheduling[name].append(run["scheduling"][name]["coverage"])
    for name, item in source["source_only"].items():
        _closed(item, ("routing", "scheduling"), "/execution_telemetry/source_coverage/source_only/" + name)
        _coverage(item["routing"], "source-only routing")
        if item["routing"]["paired_events"] != 0:
            raise InputError("source-only routing cannot have paired observations")
        _scheduling(item["scheduling"], "source-only scheduling")
        routing.append(item["routing"])
        for metric in _METRICS:
            scheduling[metric].append(item["scheduling"][metric])
    if set(selected) != seen_sources | set(source["source_only"]):
        raise InputError("selected source lacks a contribution")
    if source["routing"] != _merged(routing):
        raise InputError("routing aggregate does not match contributions")
    for name in _METRICS:
        if source["scheduling"][name] != _merged(scheduling[name]):
            raise InputError("scheduling aggregate does not match contributions")


def validate_record(value):
    current = ("schema_version", "kind", "window", "strata", "fleet", "notes", "execution_telemetry", "record_id", "generated_at")
    legacy = tuple(name for name in current if name != "execution_telemetry")
    if not isinstance(value, dict) or tuple(sorted(value)) not in (tuple(sorted(current)), tuple(sorted(legacy))):
        raise InputError("record has wrong members")
    if value.get("schema_version") != 1 or value.get("kind") != "agent-cost-record":
        raise InputError("unsupported record")
    if not isinstance(value.get("window"), dict) or not isinstance(value.get("window", {}).get("strata"), list):
        raise InputError("record window invalid")
    selected = value["window"]["strata"]
    if not all(isinstance(x, str) and x for x in selected) or selected != sorted(set(selected)):
        raise InputError("selected sources invalid")
    if not isinstance(value.get("strata"), dict) or set(value["strata"]) != set(selected) or not isinstance(value.get("fleet"), dict) or not isinstance(value.get("notes"), str):
        raise InputError("record projection invalid")
    canonical_time(value["generated_at"])
    if not isinstance(value.get("record_id"), str) or not _DIGEST.fullmatch(value["record_id"]):
        raise InputError("record digest invalid")
    body = {key: item for key, item in value.items() if key not in ("record_id", "generated_at")}
    if canonical_digest(body) != value["record_id"]:
        raise InputError("record digest mismatch")
    telemetry = None
    if "execution_telemetry" in value:
        telemetry = value["execution_telemetry"]
        _telemetry(telemetry, selected)
    return {"record": value, "telemetry": telemetry}


def load_validated_matrix(root):
    root = Path(root)
    module_path = root / "home/common/agent-skills/scripts/agent-model-matrix.py"
    previous = sys.modules.get("agent_model_matrix_for_drift")
    try:
        loader = importlib.machinery.SourceFileLoader("agent_model_matrix_for_drift", str(module_path))
        spec = __import__("importlib.util").util.spec_from_loader(loader.name, loader)
        module = __import__("importlib.util").util.module_from_spec(spec)
        sys.modules[spec.name] = module
        loader.exec_module(module)
        errors = module.validate(root)
        if errors:
            raise InputError("matrix validation failed")
        return module.load_matrix(root)
    except Exception as error:
        raise InputError("matrix validation failed") from error
    finally:
        if previous is None:
            sys.modules.pop("agent_model_matrix_for_drift", None)
        else:
            sys.modules["agent_model_matrix_for_drift"] = previous


def validate_baseline(value, matrix, matrix_digest):
    fields = ("schema_version", "kind", "baseline_id", "captured_at", "valid_from", "valid_before", "matrix_digest", "producer", "harness_versions", "model_catalog_version", "dispatch_hosts", "catalog", "escalation_reason_codes")
    _closed(value, fields, "/baseline")
    if value["schema_version"] != 1 or value["kind"] != "agent-model-baseline":
        raise InputError("unsupported baseline")
    captured, start, end = (canonical_time(value[key]) for key in ("captured_at", "valid_from", "valid_before"))
    if not start <= captured < end or not isinstance(value["baseline_id"], str) or not _DIGEST.fullmatch(value["baseline_id"]):
        raise InputError("baseline lifecycle invalid")
    body = {key: item for key, item in value.items() if key != "baseline_id"}
    if canonical_digest(body) != value["baseline_id"] or not isinstance(value["matrix_digest"], str) or not _DIGEST.fullmatch(value["matrix_digest"]):
        raise InputError("baseline digest invalid")
    _closed(value["producer"], ("name", "version", "telemetry_schema_version"), "/baseline/producer")
    producer = value["producer"]
    if (not isinstance(producer["name"], str) or not producer["name"]
            or isinstance(producer["version"], bool)
            or not isinstance(producer["version"], int) or producer["version"] <= 0
            or isinstance(producer["telemetry_schema_version"], bool)
            or not isinstance(producer["telemetry_schema_version"], int)
            or producer["telemetry_schema_version"] <= 0):
        raise InputError("baseline producer invalid")
    if (not isinstance(value["harness_versions"], dict) or not value["harness_versions"]
            or not isinstance(value["model_catalog_version"], str) or not value["model_catalog_version"]
            or not isinstance(value["escalation_reason_codes"], list)
            or any(not isinstance(code, str) or not code for code in value["escalation_reason_codes"])):
        raise InputError("baseline identity invalid")
    if value["escalation_reason_codes"] != sorted(set(value["escalation_reason_codes"])):
        raise InputError("baseline escalation codes invalid")
    for versions in value["harness_versions"].values():
        if (not isinstance(versions, list) or versions != sorted(set(versions))
                or any(not isinstance(item, str) or not item for item in versions)):
            raise InputError("baseline harness invalid")
    dispatches = {site["id"] for site in matrix["dispatch_sites"]}
    if (not isinstance(value["dispatch_hosts"], dict) or set(value["dispatch_hosts"]) != dispatches
            or any(not isinstance(host, str) or not host for host in value["dispatch_hosts"].values())):
        raise InputError("baseline dispatch coverage invalid")
    models = {role["model"] for role in matrix["roles"].values()}
    efforts = {role["effort"] for role in matrix["roles"].values()}
    if (not isinstance(value["catalog"], dict)
            or set(value["catalog"]) != set(value["harness_versions"])
            or set(value["catalog"]) != set(value["dispatch_hosts"].values())):
        raise InputError("baseline catalog coverage invalid")
    for host, catalog in value["catalog"].items():
        _closed(catalog, ("models", "efforts"), "/baseline/catalog/" + host)
        for key, tiers in (("models", models), ("efforts", efforts)):
            if not isinstance(catalog[key], dict) or set(catalog[key]) != tiers:
                raise InputError("baseline tier coverage invalid")
            for tier in tiers:
                item = catalog[key][tier]
                _closed(item, ("allowed", "prohibited"), "/baseline/catalog")
                allowed, prohibited = item["allowed"], item["prohibited"]
                if (not isinstance(allowed, list) or not isinstance(prohibited, list)
                        or any(not isinstance(x, str) or not x for x in allowed)
                        or any(not isinstance(x, str) or not x for x in prohibited)):
                    raise InputError("baseline classification invalid")
                if allowed != sorted(set(allowed)) or prohibited != sorted(set(prohibited)) or set(allowed) & set(prohibited):
                    raise InputError("baseline classification invalid")
    return value
