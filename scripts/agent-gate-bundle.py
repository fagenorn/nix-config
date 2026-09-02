#!/usr/bin/env python3
"""Adjudicate the issue #70 agent-efficiency gate over a trials manifest.

The manifest (`kind: agent-gate-trials`) declares an identity block, an
expansion declaration and a corpus of cases; every case cites, per stratum and
per side, the `agent-cost-record` documents produced by
`agent-costs.py --format json`. No measurement is read from the manifest: each
cited record file is loaded, its `record_id` recomputed, and the cited run
extracted by `run_id` (D10).

Two failure classes stay apart (D31). A manifest *document* fault — unreadable
file, invalid JSON, a duplicate or unknown key, a wrong type or a value outside
its enum — raises `ManifestError`: the tool never understood its input and emits
no bundle. An *evidence* fault — missing strata, unpaired, miscounted or
repeated trials, an unstable evaluator, a mismatched identity, an unreadable,
tampered or wrong-shaped record — is returned as a diagnostic and resolves the
bundle to `unmeasured`.
"""

import argparse
import copy
import hashlib
import json
import math
import statistics
import sys
from collections import namedtuple
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
TRIALS_KIND = "agent-gate-trials"
BUNDLE_KIND = "agent-gate-bundle"
RECORD_KIND = "agent-cost-record"
GATE_CONTRACT = "issue-70"
GATE_VERSION = 1

STRATA = ("claude", "codex")
SIDES = ("base", "candidate")
MIN_TRIALS = 3
EXPANDED_TRIALS = 10
CASE_CLASSES = (
    "cold-resolution",
    "routine-issue",
    "fuzzy-design",
    "review-ship",
    "repo-specific",
)
CORE_CASE_CLASSES = CASE_CLASSES[:4]
RUBRIC_MAX = 100.0
EVALUATOR_STABILITY = ("stable", "unstable")

# Manifest schema, level by level: every key a level allows, and of those the
# subset it requires. An unknown key is a document fault, so no `required` flag
# can be smuggled in beside them (D20, D31).
TOP_FIELDS = ("schema_version", "kind", "identity", "expansion", "cases")
IDENTITY_FIELDS = ("bound", "pinned")
BOUND_FIELDS = ("commit", "project_contract_version", "shared_platform_version")
PINNED_STRING_FIELDS = ("evaluator_version", "rubric_version",
                        "environment_fingerprint")
PINNED_FIELDS = PINNED_STRING_FIELDS + ("builds",)
BUILD_FIELDS = ("agent", "model")
EXPANSION_FIELDS = ("expanded", "checkpoint_ref")
CASE_FIELDS = ("case_id", "case_class", "strata")
STRATUM_REQUIRED_FIELDS = SIDES + ("quality",)
STRATUM_FIELDS = STRATUM_REQUIRED_FIELDS + ("checks", "maintenance")
TRIAL_FIELDS = ("record", "run_id", "record_id")
QUALITY_FIELDS = ("critical_all_pass", "evaluator_stability", "noncritical_median")
CHECKS_FIELDS = ("static_fallback_checks", "discovery_preflight_ops")
MAINTENANCE_FIELDS = ("manual_update_sites", "new_hand_authored_projections")


Diagnostic = namedtuple("Diagnostic", "code path message")


def render(diagnostics):
    """Contract: sorted 'CODE $.path: message' lines, the agent-evidence vocabulary."""
    return sorted(f"{d.code} {d.path}: {d.message}" for d in diagnostics)


class ManifestError(Exception):
    """A manifest document fault: the tool cannot proceed at all (D31)."""

    def __init__(self, diagnostics):
        super().__init__("; ".join(render(diagnostics)))
        self.diagnostics = list(diagnostics)


def canonical_digest(body):
    """Contract: 'sha256:' + sha256 over canonical JSON of `body` (D9, D25)."""
    payload = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def is_int(value):
    """A JSON integer. A Python bool *is* an int and is never a count (D34)."""
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value):
    """A finite JSON number, bool excluded (D34)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def _add(diagnostics, code, path, message):
    diagnostics.append(Diagnostic(code, path, message))


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_constant(name):
    raise ValueError(f"JSON constant {name} is not allowed")


def _parse(text):
    """Strict JSON: duplicate keys and the NaN/Infinity literals are both faults."""
    return json.loads(text, object_pairs_hook=_reject_duplicate_keys,
                      parse_constant=_reject_constant)


# --- Manifest document schema (D31) -----------------------------------------


def _object(value, path, allowed, required, diagnostics):
    """An object whose keys all lie in `allowed` and cover `required`."""
    if not isinstance(value, dict):
        _add(diagnostics, "FIELD_TYPE", path, "expected an object")
        return None
    for key in sorted(set(value) - set(allowed)):
        _add(diagnostics, "FIELD_UNKNOWN", f"{path}.{key}", "unknown field")
    for key in required:
        if key not in value:
            _add(diagnostics, "FIELD_REQUIRED", f"{path}.{key}", "field is required")
    return value


def _child(parent, key, path, allowed, required, diagnostics):
    """`parent[key]` as an object; absence is silent (the parent reports it)."""
    if key not in parent:
        return None
    return _object(parent[key], f"{path}.{key}", allowed, required, diagnostics)


def _string(value, path, diagnostics):
    if not isinstance(value, str):
        _add(diagnostics, "FIELD_TYPE", path, "expected a string")


def _count(value, path, diagnostics):
    if not is_int(value):
        _add(diagnostics, "FIELD_TYPE", path, "expected an integer")
    elif value < 0:
        _add(diagnostics, "FIELD_VALUE", path, "must not be negative")


def _rubric(value, path, diagnostics):
    if not is_number(value):
        _add(diagnostics, "FIELD_TYPE", path, "expected a finite number")
    elif not 0.0 <= value <= RUBRIC_MAX:
        _add(diagnostics, "FIELD_VALUE", path, f"must be within [0, {RUBRIC_MAX}]")


def _pair(parent, key, path, scalar, diagnostics):
    """A `base`/`candidate` object whose two leaves satisfy `scalar`."""
    pair = _child(parent, key, path, SIDES, SIDES, diagnostics)
    if pair is None:
        return
    for side in SIDES:
        if side in pair:
            scalar(pair[side], f"{path}.{key}.{side}", diagnostics)


def _validate_identity(root, diagnostics):
    identity = _child(root, "identity", "$", IDENTITY_FIELDS, IDENTITY_FIELDS,
                      diagnostics)
    if identity is None:
        return
    bound = _child(identity, "bound", "$.identity", BOUND_FIELDS, BOUND_FIELDS,
                   diagnostics)
    if bound is not None:
        for key in BOUND_FIELDS:
            _pair(bound, key, "$.identity.bound", _string, diagnostics)
    pinned = _child(identity, "pinned", "$.identity", PINNED_FIELDS, PINNED_FIELDS,
                    diagnostics)
    if pinned is None:
        return
    for key in PINNED_STRING_FIELDS:
        _pair(pinned, key, "$.identity.pinned", _string, diagnostics)
    builds = _child(pinned, "builds", "$.identity.pinned", STRATA, STRATA, diagnostics)
    if builds is None:
        return
    for stratum in STRATA:
        path = "$.identity.pinned.builds"
        build = _child(builds, stratum, path, BUILD_FIELDS, BUILD_FIELDS, diagnostics)
        if build is None:
            continue
        for key in BUILD_FIELDS:
            _pair(build, key, f"{path}.{stratum}", _string, diagnostics)


def _validate_expansion(root, diagnostics):
    expansion = _child(root, "expansion", "$", EXPANSION_FIELDS, EXPANSION_FIELDS,
                       diagnostics)
    if expansion is None:
        return
    if "expanded" in expansion and not isinstance(expansion["expanded"], bool):
        _add(diagnostics, "FIELD_TYPE", "$.expansion.expanded", "expected a boolean")
    if "checkpoint_ref" in expansion:
        reference = expansion["checkpoint_ref"]
        if reference is not None and not isinstance(reference, str):
            _add(diagnostics, "FIELD_TYPE", "$.expansion.checkpoint_ref",
                 "expected a string or null")


def _validate_quality(stratum, path, diagnostics):
    quality = _child(stratum, "quality", path, QUALITY_FIELDS, QUALITY_FIELDS,
                     diagnostics)
    if quality is None:
        return
    if "critical_all_pass" in quality and not isinstance(
            quality["critical_all_pass"], bool):
        _add(diagnostics, "FIELD_TYPE", f"{path}.quality.critical_all_pass",
             "expected a boolean")
    if ("evaluator_stability" in quality
            and quality["evaluator_stability"] not in EVALUATOR_STABILITY):
        _add(diagnostics, "FIELD_VALUE", f"{path}.quality.evaluator_stability",
             f"expected one of {list(EVALUATOR_STABILITY)}")
    _pair(quality, "noncritical_median", f"{path}.quality", _rubric, diagnostics)


def _validate_checks(stratum, path, diagnostics):
    checks = _child(stratum, "checks", path, CHECKS_FIELDS, CHECKS_FIELDS, diagnostics)
    if checks is None:
        return
    for key in CHECKS_FIELDS:
        _pair(checks, key, f"{path}.checks", _count, diagnostics)


def _validate_maintenance(stratum, path, diagnostics):
    maintenance = _child(stratum, "maintenance", path, MAINTENANCE_FIELDS,
                         MAINTENANCE_FIELDS, diagnostics)
    if maintenance is None:
        return
    _pair(maintenance, "manual_update_sites", f"{path}.maintenance", _count,
          diagnostics)
    if "new_hand_authored_projections" in maintenance:
        _count(maintenance["new_hand_authored_projections"],
               f"{path}.maintenance.new_hand_authored_projections", diagnostics)


def _validate_stratum(value, path, diagnostics):
    stratum = _object(value, path, STRATUM_FIELDS, STRATUM_REQUIRED_FIELDS,
                      diagnostics)
    if stratum is None:
        return
    for side in SIDES:
        if side not in stratum:
            continue
        if not isinstance(stratum[side], list):
            _add(diagnostics, "FIELD_TYPE", f"{path}.{side}", "expected an array")
            continue
        for index, cited in enumerate(stratum[side]):
            entry_path = f"{path}.{side}[{index}]"
            entry = _object(cited, entry_path, TRIAL_FIELDS, TRIAL_FIELDS, diagnostics)
            if entry is None:
                continue
            for key in TRIAL_FIELDS:
                if key in entry:
                    _string(entry[key], f"{entry_path}.{key}", diagnostics)
    _validate_quality(stratum, path, diagnostics)
    _validate_checks(stratum, path, diagnostics)
    _validate_maintenance(stratum, path, diagnostics)


def _validate_case(value, path, diagnostics):
    case = _object(value, path, CASE_FIELDS, CASE_FIELDS, diagnostics)
    if case is None:
        return
    if "case_id" in case:
        _string(case["case_id"], f"{path}.case_id", diagnostics)
    if "case_class" in case and case["case_class"] not in CASE_CLASSES:
        _add(diagnostics, "FIELD_VALUE", f"{path}.case_class",
             f"expected one of {list(CASE_CLASSES)}")
    # A stratum may be absent here: that is an evidence fault for
    # `resolve_trials`, not a document fault (D11, D31).
    strata = _child(case, "strata", path, STRATA, (), diagnostics)
    if strata is None:
        return
    for name in sorted(set(strata) & set(STRATA)):
        _validate_stratum(strata[name], f"{path}.strata.{name}", diagnostics)


def _validate_manifest(document):
    """Every violation in one pass, sorted — never the first one only."""
    diagnostics = []
    root = _object(document, "$", TOP_FIELDS, TOP_FIELDS, diagnostics)
    if root is None:
        return sorted(diagnostics)
    if "schema_version" in root and (not is_int(root["schema_version"])
                                     or root["schema_version"] != SCHEMA_VERSION):
        _add(diagnostics, "FIELD_VALUE", "$.schema_version",
             f"expected {SCHEMA_VERSION}")
    if "kind" in root and root["kind"] != TRIALS_KIND:
        _add(diagnostics, "FIELD_VALUE", "$.kind", f"expected {TRIALS_KIND!r}")
    _validate_identity(root, diagnostics)
    _validate_expansion(root, diagnostics)
    if "cases" in root:
        if isinstance(root["cases"], list):
            for index, case in enumerate(root["cases"]):
                _validate_case(case, f"$.cases[{index}]", diagnostics)
        else:
            _add(diagnostics, "FIELD_TYPE", "$.cases", "expected an array")
    return sorted(diagnostics)


def load_manifest(path):
    """Parse and structurally validate a trials manifest, or raise ManifestError."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ManifestError(
            [Diagnostic("MANIFEST_READ_ERROR", "$", str(error))]) from error
    try:
        document = _parse(text)
    except (json.JSONDecodeError, ValueError) as error:
        raise ManifestError(
            [Diagnostic("JSON_INVALID", "$", str(error))]) from error
    diagnostics = _validate_manifest(document)
    if diagnostics:
        raise ManifestError(diagnostics)
    return document


# --- Cited records (D10, D34) -----------------------------------------------


def load_record(path):
    """Parse one cited record file. Shape checking belongs to validate_record."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError(str(error)) from error
    try:
        document = _parse(text)
    except (json.JSONDecodeError, ValueError) as error:
        raise ValueError(str(error)) from error
    if not isinstance(document, dict):
        raise ValueError("record document is not a JSON object")
    return document


def validate_record(document, stratum, run_id):
    """Type-check a cited record and return the cited run, or diagnostics (D34).

    A recomputed digest proves a document is self-consistent, never that it is a
    cost record of the right kind or shape, so every check below runs on its own
    evidence and every nested access is `.get()`-guarded. Paths are suffixes: the
    caller anchors them at the manifest position that cited the record.
    """
    def fault(code, path, message):
        return None, [Diagnostic(code, path, message)]

    absent = f"run {run_id!r} is not in stratum {stratum!r} of the cited record"

    version = document.get("schema_version")
    if not is_int(version) or version != SCHEMA_VERSION:
        return fault("RECORD_INVALID", ".schema_version",
                     f"expected schema_version {SCHEMA_VERSION}")
    if document.get("kind") != RECORD_KIND:
        return fault("RECORD_INVALID", ".kind", f"expected kind {RECORD_KIND!r}")
    generated_at = document.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at.strip():
        return fault("RECORD_INVALID", ".generated_at",
                     "generated_at is required and must be non-empty")
    strata = document.get("strata")
    if not isinstance(strata, dict):
        return fault("RECORD_INVALID", ".strata", "expected an object")
    if stratum not in strata:
        return fault("RUN_NOT_FOUND", f".strata.{stratum}", absent)
    block = strata[stratum]
    if not isinstance(block, dict):
        return fault("RECORD_INVALID", f".strata.{stratum}", "expected an object")
    runs = block.get("runs")
    if not isinstance(runs, list) or not all(isinstance(r, dict) for r in runs):
        return fault("RECORD_INVALID", f".strata.{stratum}.runs",
                     "expected an array of objects")
    found = [(index, run) for index, run in enumerate(runs)
             if run.get("run_id") == run_id]
    if not found:
        return fault("RUN_NOT_FOUND", f".strata.{stratum}.runs", absent)
    index, run = found[0]
    path = f".strata.{stratum}.runs[{index}]"

    tokens = run.get("tokens")
    if not isinstance(tokens, dict):
        return fault("RECORD_INVALID", f"{path}.tokens", "expected an object")
    input_total = tokens.get("input_total")
    if not is_int(input_total) or input_total < 0:
        return fault("RECORD_INVALID", f"{path}.tokens.input_total",
                     "expected a non-negative integer")
    peak_ctx = run.get("peak_ctx")
    if not is_int(peak_ctx) or peak_ctx < 0:
        return fault("RECORD_INVALID", f"{path}.peak_ctx",
                     "expected a non-negative integer")
    outcome = run.get("outcome")
    if outcome is not None and not isinstance(outcome, str):
        return fault("RECORD_INVALID", f"{path}.outcome", "expected a string or null")
    return run, []


# --- Evidence resolution (D14, D31) -----------------------------------------


def _identity_leaves(manifest):
    """(path, pair, pinned) for every identity leaf, `builds` walked two deeper."""
    identity = manifest.get("identity")
    identity = identity if isinstance(identity, dict) else {}
    leaves = []
    bound = identity.get("bound")
    if isinstance(bound, dict):
        for key in BOUND_FIELDS:
            leaves.append((f"$.identity.bound.{key}", bound.get(key), False))
    pinned = identity.get("pinned")
    if isinstance(pinned, dict):
        for key in PINNED_STRING_FIELDS:
            leaves.append((f"$.identity.pinned.{key}", pinned.get(key), True))
        builds = pinned.get("builds")
        if isinstance(builds, dict):
            for stratum in STRATA:
                build = builds.get(stratum)
                if not isinstance(build, dict):
                    continue
                for key in BUILD_FIELDS:
                    leaves.append((f"$.identity.pinned.builds.{stratum}.{key}",
                                   build.get(key), True))
    return leaves


def _check_identity(manifest, diagnostics):
    """Bound leaves must be present; pinned leaves must also be equal (D19)."""
    for path, pair, pinned in _identity_leaves(manifest):
        if not isinstance(pair, dict):
            _add(diagnostics, "IDENTITY_INCOMPLETE", path,
                 "field is required and must be non-empty")
            continue
        values = {}
        for side in SIDES:
            value = pair.get(side)
            if isinstance(value, str) and value.strip():
                values[side] = value
            else:
                _add(diagnostics, "IDENTITY_INCOMPLETE", f"{path}.{side}",
                     "field is required and must be non-empty")
        if pinned and len(values) == len(SIDES) and values["base"] != values["candidate"]:
            _add(diagnostics, "IDENTITY_MISMATCH", path,
                 f"base {values['base']!r} != candidate {values['candidate']!r}")


def _expanded(manifest):
    expansion = manifest.get("expansion")
    return isinstance(expansion, dict) and expansion.get("expanded") is True


def _check_expansion(manifest, diagnostics):
    """An expansion and its human checkpoint each imply the other (D36)."""
    expansion = manifest.get("expansion")
    expansion = expansion if isinstance(expansion, dict) else {}
    reference = expansion.get("checkpoint_ref")
    declared = isinstance(reference, str) and bool(reference.strip())
    if _expanded(manifest) and not declared:
        _add(diagnostics, "EXPANSION_INCONSISTENT", "$.expansion",
             "an expansion must record its human checkpoint")
    elif not _expanded(manifest) and declared:
        _add(diagnostics, "EXPANSION_INCONSISTENT", "$.expansion",
             "a checkpoint is recorded but no expansion is declared")


def _resolve_trial(entry, stratum, path, loader, diagnostics):
    """One cited record, verified and reduced to the measurements it vouches for."""
    citation = entry.get("record") if isinstance(entry, dict) else None
    record_path = f"{path}.record"
    if not isinstance(citation, str):
        _add(diagnostics, "RECORD_UNREADABLE", record_path, "expected a string path")
        return None
    try:
        document = loader(Path(citation))
    except ValueError as error:
        _add(diagnostics, "RECORD_UNREADABLE", record_path, str(error))
        return None
    if not isinstance(document, dict):
        _add(diagnostics, "RECORD_UNREADABLE", record_path,
             "record document is not a JSON object")
        return None
    digest = canonical_digest({key: value for key, value in document.items()
                               if key not in ("record_id", "generated_at")})
    if digest != document.get("record_id") or digest != entry.get("record_id"):
        _add(diagnostics, "RECORD_DIGEST_MISMATCH", record_path,
             f"recomputed {digest} does not match the cited digest")
        return None
    run_id = entry.get("run_id")
    run, faults = validate_record(document, stratum, run_id)
    if faults:
        diagnostics.extend(fault._replace(path=record_path + fault.path)
                           for fault in faults)
        return None
    return {"run_id": run_id, "record_id": document["record_id"],
            "generated_at": document["generated_at"], "outcome": run.get("outcome"),
            "input_total": run["tokens"]["input_total"], "peak_ctx": run["peak_ctx"]}


def _resolve_stratum(block, stratum, path, allowed, loader, diagnostics):
    """One case/stratum: its declarations checked, its cited trials resolved."""
    quality = block.get("quality")
    if not isinstance(quality, dict):
        _add(diagnostics, "QUALITY_MISSING", f"{path}.quality",
             "quality is required evidence")
    elif quality.get("evaluator_stability") == "unstable":
        _add(diagnostics, "EVALUATOR_UNSTABLE",
             f"{path}.quality.evaluator_stability",
             "the evaluator is declared unstable")

    cited = {}
    for side in SIDES:
        entries = block.get(side)
        cited[side] = entries if isinstance(entries, list) else []
    count = len(cited["base"])
    if count != len(cited["candidate"]):
        _add(diagnostics, "TRIALS_UNPAIRED", path,
             f"base {count} trials, candidate {len(cited['candidate'])} trials")
        return None
    if count < MIN_TRIALS:
        _add(diagnostics, "TRIALS_INSUFFICIENT", path,
             f"{count} paired trials, {MIN_TRIALS} required")
    elif count not in allowed:
        _add(diagnostics, "TRIALS_CARDINALITY", path,
             f"{count} paired trials; allowed here: {sorted(allowed)}")

    # A trial is identified by its cited (record_id, run_id): the same
    # measurement cited twice is one measurement, and a median over copies of it
    # buys the approval the exact cardinality of D36 exists to deny. Checked per
    # side only — a run cited on both sides yields delta 0 and buys nothing.
    # `repr` keys the pair without assuming the cited values are hashable.
    for side in SIDES:
        identities = [repr((entry.get("record_id"), entry.get("run_id")))
                      for entry in cited[side] if isinstance(entry, dict)]
        distinct = len(set(identities))
        if distinct != len(identities):
            _add(diagnostics, "TRIALS_DUPLICATE", f"{path}.{side}",
                 f"{len(identities)} cited trials, "
                 f"{distinct} distinct (record_id, run_id)")

    trials = {}
    for side in SIDES:
        resolved = (_resolve_trial(entry, stratum, f"{path}.{side}[{index}]",
                                   loader, diagnostics)
                    for index, entry in enumerate(cited[side]))
        trials[side] = [trial for trial in resolved if trial is not None]
    return {"trials": trials, "quality": copy.deepcopy(quality),
            "checks": copy.deepcopy(block.get("checks")),
            "maintenance": copy.deepcopy(block.get("maintenance"))}


def _assemble(cases):
    """Fold each stratum's resolved trials into the context block decide reads (D30)."""
    assembled = []
    for case in cases:
        strata = {}
        for stratum, block in case["strata"].items():
            trials = block["trials"]
            base_median = statistics.median(
                trial["input_total"] for trial in trials["base"])
            candidate_median = statistics.median(
                trial["input_total"] for trial in trials["candidate"])
            delta_tokens = candidate_median - base_median
            strata[stratum] = {
                "context": {
                    "base_median": base_median,
                    "candidate_median": candidate_median,
                    "delta_tokens": delta_tokens,
                    "delta_pct": (100 * delta_tokens / base_median
                                  if base_median > 0 else None),
                    "trials": trials,
                },
                "quality": block["quality"],
                "checks": block["checks"],
                "maintenance": block["maintenance"],
            }
        assembled.append({"case_id": case["case_id"],
                          "case_class": case["case_class"], "strata": strata})
    return assembled


def resolve_trials(manifest, loader=load_record):
    """Resolve a manifest's cited records into the evidence `decide` consumes.

    Returns `(evidence, [])` or `(None, diagnostics)` — never a partial result,
    and never an exception for bad evidence (D14, D31).
    """
    diagnostics = []
    _check_identity(manifest, diagnostics)
    _check_expansion(manifest, diagnostics)
    allowed = ({MIN_TRIALS, EXPANDED_TRIALS} if _expanded(manifest)
               else {MIN_TRIALS})

    cases = manifest.get("cases")
    cases = cases if isinstance(cases, list) else []
    if not cases:
        _add(diagnostics, "CASES_EMPTY", "$.cases", "at least one case is required")
    declared = {case.get("case_class") for case in cases if isinstance(case, dict)}
    for case_class in CORE_CASE_CLASSES:
        if case_class not in declared:
            _add(diagnostics, "CASE_CLASS_MISSING", "$.cases",
                 f"required case class {case_class!r} is absent")

    resolved = []
    for index, case in enumerate(cases):
        case = case if isinstance(case, dict) else {}
        case_path = f"$.cases[{index}]"
        declared_strata = case.get("strata")
        declared_strata = declared_strata if isinstance(declared_strata, dict) else {}
        strata = {}
        for stratum in STRATA:
            path = f"{case_path}.strata.{stratum}"
            block = declared_strata.get(stratum)
            if not isinstance(block, dict):
                _add(diagnostics, "STRATUM_MISSING", path,
                     "both strata are required evidence")
                continue
            entry = _resolve_stratum(block, stratum, path, allowed, loader,
                                     diagnostics)
            if entry is not None:
                strata[stratum] = entry
        resolved.append({"case_id": case.get("case_id"),
                         "case_class": case.get("case_class"), "strata": strata})

    if diagnostics:
        return None, sorted(diagnostics)
    return {"cases": _assemble(resolved)}, []


# --- The #70 gate (D13, D21) -------------------------------------------------

CONTEXT_SAVE_PCT = 10.0        # a drop of at least this many percent saves
CONTEXT_SAVE_TOKENS = 500      # ... or a drop of at least this many tokens
CONTEXT_RISE_PCT = 2.0         # a rise must exceed both of these to breach
CONTEXT_RISE_TOKENS = 128
QUALITY_DROP_POINTS = 5.0      # a drop of more than this vetoes (one-sided, D13)
CHECKS_OPS_DROP_PCT = 20.0
MAINTENANCE_DROP_PCT = 50.0


def _rise_exceeds(delta_tokens, delta_pct, limit_pct):
    """The one place a zero base median is judged: any rise from nothing exceeds."""
    if delta_pct is None:
        return delta_tokens > 0
    return delta_pct > limit_pct


def _dropped_at_least(base, candidate, limit_pct):
    """A drop from `base` to `candidate` of at least `limit_pct` percent."""
    return base > 0 and 100 * (base - candidate) / base >= limit_pct


def context_saves(delta_tokens, delta_pct):
    """Contract: a three-trial median drop of >=500 tokens OR >=10 percent."""
    return (delta_tokens <= -CONTEXT_SAVE_TOKENS
            or (delta_pct is not None and delta_pct <= -CONTEXT_SAVE_PCT))


def context_breaches(delta_tokens, delta_pct):
    """Contract: the no-regression bound is conjunctive — >128 tokens AND >2 percent."""
    return (delta_tokens > CONTEXT_RISE_TOKENS
            and _rise_exceeds(delta_tokens, delta_pct, CONTEXT_RISE_PCT))


def quality_fails(quality):
    """Contract: the hard veto — every critical criterion, and a one-sided bound (D13).

    `evaluator_stability` is deliberately unread; instability resolves upstream (D37).
    """
    if not quality:
        return True
    if quality.get("critical_all_pass") is not True:
        return True
    median = quality["noncritical_median"]
    return median["base"] - median["candidate"] > QUALITY_DROP_POINTS


def checks_save(checks):
    """Contract: no static fallback check survives, and preflight ops drop >=20%.

    An absent declaration means the gate cannot fire, never that it passes (D11).
    """
    if not checks:
        return False
    static = checks["static_fallback_checks"]
    ops = checks["discovery_preflight_ops"]
    return (static["candidate"] == 0 and static["base"] > 0
            and _dropped_at_least(ops["base"], ops["candidate"], CHECKS_OPS_DROP_PCT))


def maintenance_saves(maintenance):
    """Contract: manual update sites drop >=50% and >=1, with no new hand-authored
    projection. An absent declaration means the gate cannot fire (D11).
    """
    if not maintenance:
        return False
    if maintenance["new_hand_authored_projections"] != 0:
        return False
    sites = maintenance["manual_update_sites"]
    return (sites["base"] - sites["candidate"] >= 1
            and _dropped_at_least(sites["base"], sites["candidate"],
                                  MAINTENANCE_DROP_PCT))


def _pairs(context):
    """(delta_tokens, delta_pct) per index-aligned trial pair (D30)."""
    trials = context["trials"]
    pairs = []
    for base, candidate in zip(trials["base"], trials["candidate"]):
        delta = candidate["input_total"] - base["input_total"]
        pairs.append((delta, 100 * delta / base["input_total"]
                      if base["input_total"] else None))
    return pairs


def straddling_cases(evidence):
    """Contract: sorted (case_index, case_id, stratum) for every case whose pairs
    cross both sides of the context gate — at three pairs and at ten alike (D21).
    """
    straddling = []
    for index, case in enumerate(evidence["cases"]):
        for stratum, block in case["strata"].items():
            pairs = _pairs(block["context"])
            if (any(context_saves(*pair) for pair in pairs)
                    and any(context_breaches(*pair) for pair in pairs)):
                straddling.append((index, case["case_id"], stratum))
    return sorted(straddling)


def _declared_axis(blocks, key, saves):
    """One optional-declaration axis over a stratum's cases: which fire, and whether."""
    firing = [case_id for case_id, block in blocks if saves(block[key])]
    return {"fired": bool(firing), "cases": firing}


def gate_results(evidence):
    """Contract: the bundle's `gates` block — every axis reported per stratum."""
    cases = evidence["cases"]
    failing = sorted(f"{case['case_id']}/{stratum}"
                     for case in cases
                     for stratum, block in case["strata"].items()
                     if quality_fails(block["quality"]))

    context, checks, maintenance = {}, {}, {}
    for stratum in STRATA:
        blocks = [(case["case_id"], case["strata"][stratum]) for case in cases
                  if stratum in case["strata"]]
        saving = [case_id for case_id, block in blocks
                  if context_saves(block["context"]["delta_tokens"],
                                   block["context"]["delta_pct"])]
        breaching = [case_id for case_id, block in blocks
                     if context_breaches(block["context"]["delta_tokens"],
                                         block["context"]["delta_pct"])]
        context[stratum] = {"fired": bool(saving) and not breaching,
                            "saving_cases": saving, "breaching_cases": breaching}
        checks[stratum] = _declared_axis(blocks, "checks", checks_save)
        maintenance[stratum] = _declared_axis(blocks, "maintenance",
                                              maintenance_saves)

    cross = {}
    for stratum in STRATA:
        other = any(context[name]["breaching_cases"]
                    for name in STRATA if name != stratum)
        cross[stratum] = {"qualifies": not other, "other_breaches": other}

    return {"quality": {"passed": not failing, "failing": failing},
            "context": context, "checks": checks, "maintenance": maintenance,
            "cross_stratum": cross}


def decide(evidence):
    """Contract: the sole verdict authority. Takes the resolved evidence and
    nothing else — no authorization block, no manifest, no clock (D14)."""
    if not evidence or not evidence.get("cases"):
        return "unmeasured"
    if straddling_cases(evidence):
        return "unmeasured"
    gates = gate_results(evidence)
    if not gates["quality"]["passed"]:
        return "rejected"
    for stratum in STRATA:
        if not gates["cross_stratum"][stratum]["qualifies"]:
            continue
        if any(gates[axis][stratum]["fired"]
               for axis in ("context", "checks", "maintenance")):
            return "approved"
    return "rejected"


# --- The bundle document (D9, D14, D16, D22) ---------------------------------


class BundleIntegrityError(Exception):
    """The emitter's refusal to write: the assembled body does not earn the
    state it was handed (D14). No document reaches stdout on this path."""


def build_override(reason, authorized_by, authorized_at):
    """Contract: the closed four-key authorization block, or None when unasked.

    Every field is a declared input. `authorized_at` is the caller's
    `--override-at` and never a clock read: the block sits inside `bundle_id`,
    so a sampled time would give identical inputs different bundle ids (D38).
    """
    if reason is None:
        return None
    return {"reason": reason, "authorized_by": authorized_by,
            "authorized_at": authorized_at, "scope": "further-experimentation"}


def _generated_at():
    """The one clock read in the document, and the one field outside the digest."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z")


def assemble_bundle(manifest, evidence, diagnostics, override, state):
    """Contract: the bundle document, or BundleIntegrityError and no document.

    `state` is `decide`'s and only `decide`'s; the body is re-decided against
    its own evidence before it is returned, so a state the evidence does not
    earn is refused rather than written (D14).
    """
    resolved = evidence if evidence else {"cases": []}

    reasons = list(diagnostics)
    if state == "unmeasured" and evidence:
        for index, case_id, stratum in straddling_cases(evidence):
            _add(reasons, "CASE_STRADDLES_GATE",
                 f"$.cases[{index}].strata.{stratum}",
                 f"case {case_id!r} has index-aligned pairs on both sides "
                 "of a gate")
    lines = render(reasons) if state == "unmeasured" else []

    body = {
        "schema_version": SCHEMA_VERSION,
        "kind": BUNDLE_KIND,
        "gate_contract": GATE_CONTRACT,
        "gate_version": GATE_VERSION,
        "state": state,
        "identity": manifest["identity"],
        "expansion": manifest["expansion"],
        "evidence": resolved,
        "gates": gate_results(resolved),
        "override": override,
        "diagnostics": lines,
    }
    earned = decide(body["evidence"])
    if earned != body["state"]:
        raise BundleIntegrityError(
            f"the bundle's own evidence earns {earned!r}, not {body['state']!r}")
    return dict(body, bundle_id=canonical_digest(body),
                generated_at=_generated_at())


def main(argv=None):
    """Contract: one bundle to stdout and an exit code — 0 approved, 3 rejected
    or unmeasured, 2 tool failure. A non-zero exit is never an approval (D16).
    """
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--trials", required=True, metavar="FILE",
                    help="agent-gate-trials manifest citing emitted cost records")
    ap.add_argument("--override", metavar="REASON",
                    help="record an authorization for further experimentation; "
                         "never changes the state or the exit code")
    ap.add_argument("--override-by", metavar="WHO", help="who authorized --override")
    ap.add_argument("--override-at", metavar="RFC3339",
                    help="when --override was authorized, e.g. 2026-09-02T12:00:00Z; "
                         "declared, not sampled, so the bundle id stays reproducible")
    args = ap.parse_args(argv)

    # Presence is `is not None`: absence is what waives the companions, and an
    # unexpanded shell variable is a present flag with no value, not an absent
    # one. Every field here is hashed into `bundle_id` as the record of who
    # authorized what, so a blank one is a usage error, not an empty record (D38).
    given = tuple(value is not None for value in
                  (args.override, args.override_by, args.override_at))
    if len(set(given)) != 1:
        ap.error("--override, --override-by and --override-at must be given together")
    if given[0]:
        for flag, value in (("--override", args.override),
                            ("--override-by", args.override_by)):
            if not value.strip():
                ap.error(f"{flag} must carry a value")
        try:
            datetime.strptime(args.override_at, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            ap.error("--override-at must be RFC3339 UTC, e.g. 2026-09-02T12:00:00Z")

    try:
        manifest = load_manifest(Path(args.trials))
    except ManifestError as error:
        for line in render(error.diagnostics):
            print(line, file=sys.stderr)
        return 2

    evidence, diagnostics = resolve_trials(manifest)
    state = decide(evidence)
    try:
        bundle = assemble_bundle(
            manifest, evidence, diagnostics,
            build_override(args.override, args.override_by, args.override_at),
            state)
    except BundleIntegrityError as error:
        print(str(error), file=sys.stderr)
        return 2

    json.dump(bundle, sys.stdout, sort_keys=True, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0 if state == "approved" else 3


if __name__ == "__main__":
    raise SystemExit(main())
