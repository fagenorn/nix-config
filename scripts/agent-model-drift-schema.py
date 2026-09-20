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
        if not isinstance(item["code"], str) or not item["code"]:
            raise InputError(pointer + " reason invalid")
        _nonnegative(item["count"], pointer)
        if item["count"] == 0:
            raise InputError(pointer + " reason invalid")
        codes.append(item["code"])
    if codes != sorted(set(codes)):
        raise InputError(pointer + " reasons must be sorted unique")
    expected = "full" if not codes else "partial" if value["paired_events"] else "none"
    if value["state"] != expected:
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
    if value["value"] is not None:
        _nonnegative(value["value"], pointer + "/value")
        if value["coverage"]["state"] != "full" or not isinstance(value["cohort_digest"], str) or not _DIGEST.fullmatch(value["cohort_digest"]):
            raise InputError(pointer + " metric identity invalid")
    elif value["cohort_digest"] is not None:
        raise InputError(pointer + " unavailable metric has digest")


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
        _closed(run["scheduling"], _METRICS, "/execution_telemetry/runs/scheduling")
        routing.append(run["routing"]["coverage"])
        for name in _METRICS:
            _metric(run["scheduling"][name], "/execution_telemetry/runs/scheduling/" + name)
            scheduling[name].append(run["scheduling"][name]["coverage"])
    for name, item in source["source_only"].items():
        _closed(item, ("routing", "scheduling"), "/execution_telemetry/source_coverage/source_only/" + name)
        _coverage(item["routing"], "source-only routing")
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
    telemetry = value.get("execution_telemetry")
    if telemetry is not None:
        _telemetry(telemetry, selected)
    return {"record": value, "telemetry": telemetry}


def load_validated_matrix(root):
    root = Path(root)
    module_path = root / "home/common/agent-skills/scripts/agent-model-matrix.py"
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
    except (OSError, ValueError, InputError) as error:
        raise InputError("matrix validation failed") from error


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
    if (not isinstance(value["harness_versions"], dict) or not value["harness_versions"]
            or not isinstance(value["model_catalog_version"], str) or not value["model_catalog_version"]
            or not isinstance(value["escalation_reason_codes"], list)
            or value["escalation_reason_codes"] != sorted(set(value["escalation_reason_codes"]))
            or any(not isinstance(code, str) or not code for code in value["escalation_reason_codes"])):
        raise InputError("baseline identity invalid")
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
                if any(not isinstance(x, str) or not x for x in allowed + prohibited) or allowed != sorted(set(allowed)) or prohibited != sorted(set(prohibited)) or set(allowed) & set(prohibited):
                    raise InputError("baseline classification invalid")
    return value
