"""The codesigned-artifact adapter (issue 547 D1, D4, D6-D8, D17, D19, D21): `describe`, `inspect`.

`describe()` returns a fresh descriptor with one operation, `install`: `materialize` mode,
`in_place` mutability, `supported` for `inspect`. `publication_visible` is supported and
`running_subject_identity` is not (`no_activation_mode`). The target kind is `installed_bundle`
with a `~/`-relative `path`, the credential class is `codesigning_identity`, and the closed
config is `source`, `identity_prefix`, `identity_env` and `adhoc_fallback`.

This module imports only the standard library and `agent_tools.canonical`: the registry in
`release_adapter` imports adapters, never the reverse, so its inner checks are its own.

`inspect(request)` never raises and never mutates. A request outside the closed shape is
`unknown`/`parameters_invalid` for an effect and `unknown`/`store_unreachable` for
`publication_visible`, and any other predicate is `unknown`/`predicate_unsupported` (issue 547 D19).
Otherwise it classifies the install path with `lstat`, the bundle's `Contents/Info.plist` stamp
(`AgentReleaseVersion` and `AgentReleaseCommit`) and two `codesign` reads, `--verify --deep
--strict` and `-d --verbose=2` (stderr), by the table in the issue 547 spec. Every child runs by
name on `PATH` with the caller's environment unchanged, under one `INSPECT_BUDGET_SECONDS`
deadline per call. `publication_visible` maps the effect row by the table's last column.
"""

import os
import plistlib
import re
import stat
import subprocess
import time
import xml.parsers.expat
from typing import Any

INSPECT_BUDGET_SECONDS = 30
DETAIL_LIMIT = 240
STAMP_VERSION = "AgentReleaseVersion"
STAMP_COMMIT = "AgentReleaseCommit"
CONFIG_MEMBERS = {"source": "string", "identity_prefix": "string", "identity_env": "string",
                  "adhoc_fallback": "boolean"}
REQUIRED_CONFIG = ("adhoc_fallback", "identity_prefix", "source")
VERSION = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+")
COMMIT = re.compile(r"[0-9a-f]{40}")
ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
EFFECT_SHAPE = frozenset(("kind", "operation", "parameters"))
PREDICATE_SHAPE = frozenset(("kind", "predicate", "operation", "parameters"))
PARAMETER_MEMBERS = frozenset(("target", "candidate", "config", "action", "operation"))
# The publication_visible column of the spec's table, by the effect row's reason (issue 547 D19).
VISIBLE = {"installed": ("satisfied", "installed"),
           "bundle_absent": ("unsatisfied", "ref_absent"),
           "target_unexpected": ("unsatisfied", "subject_mismatch"),
           "bundle_unmanaged": ("unsatisfied", "subject_mismatch"),
           "bundle_other_release": ("unsatisfied", "subject_mismatch"),
           "signature_invalid": ("unsatisfied", "digest_mismatch"),
           "signature_policy": ("unsatisfied", "subject_mismatch")}


def describe() -> dict[str, Any]:
    """The `codesigned-artifact` descriptor (issue 547 D1, D2, D7, D8), a fresh plain dict."""
    return {
        "name": "codesigned-artifact",
        "adapter_contract_version": "1.0.0",
        "operations": {
            "install": {"mode": "materialize", "support": "supported", "inspect": "supported",
                        "reason": None, "mutability": "in_place", "config_schema_version": 1,
                        "config_schema": {"members": dict(CONFIG_MEMBERS),
                                          "required": list(REQUIRED_CONFIG)},
                        "effects": ["reversible_no_incremental_spend", "irreversible"],
                        "recovery_capable": False, "candidate_members": []},
        },
        "predicates": {
            "publication_visible": {"support": "supported", "reason": None},
            "running_subject_identity": {"support": "unsupported", "reason": "no_activation_mode"},
        },
        "collector": {"max_collection_latency_ms": 30000, "max_concurrent_collections": 1},
        "target_kinds": {"installed_bundle": ["path"]},
        "credential_classes": ["codesigning_identity"],
        "executables": ["codesign", "git", "security"],
        "host_capacity": "not_required",
    }


def _now_ms() -> int:
    return int(time.time() * 1000)


def _segments_problem(remainder: str) -> bool:
    """Whether `remainder` splits on `/` into any empty, `.` or `..` segment."""
    return any(part in ("", ".", "..") for part in remainder.split("/"))


def _text(value: object) -> bool:
    return isinstance(value, str) and value != "" and CONTROL.search(value) is None


def _parameters_problem(parameters: Any) -> str | None:
    """The first way `parameters` departs from the closed install shape, or None (D17)."""
    if not isinstance(parameters, dict):
        return "parameters is not an object"
    undeclared = sorted(set(parameters) - PARAMETER_MEMBERS, key=str)
    if undeclared:
        return f"parameters has an undeclared member {undeclared[0]}"
    for name in ("target", "candidate", "config"):
        if name not in parameters:
            return f"parameters is missing {name}"
    if parameters.get("operation", "install") != "install":
        return "parameters operation is not install"
    target = parameters["target"]
    if (not isinstance(target, dict) or not {"kind", "path"} <= set(target)
            or set(target) - {"kind", "path", "handle"} or target["kind"] != "installed_bundle"):
        return "target is not an installed_bundle of exactly kind and path, and an optional handle"
    if "handle" in target and not (isinstance(target["handle"], str) and target["handle"]):
        return "target handle is not a non-empty string"
    path = target["path"]
    if (not isinstance(path, str) or not path.startswith("~/") or CONTROL.search(path)
            or _segments_problem(path[2:])):
        return "target path is not ~/ followed by non-empty segments other than . and .."
    candidate = parameters["candidate"]
    if (not isinstance(candidate, dict) or set(candidate) != {"version", "commit"}
            or not isinstance(candidate["version"], str)
            or VERSION.fullmatch(candidate["version"]) is None
            or not isinstance(candidate["commit"], str)
            or COMMIT.fullmatch(candidate["commit"]) is None):
        return "candidate is not exactly a vMAJOR.MINOR.PATCH version and a 40 lowercase hex commit"
    config = parameters["config"]
    if (not isinstance(config, dict) or set(config) - set(CONFIG_MEMBERS)
            or set(REQUIRED_CONFIG) - set(config)):
        return f"config is not the declared members {', '.join(CONFIG_MEMBERS)}"
    for name, kind in CONFIG_MEMBERS.items():
        if name not in config:
            continue
        value = config[name]
        if kind == "boolean" and not isinstance(value, bool):
            return f"config {name} is not a boolean"
        if kind == "string" and not _text(value):
            return f"config {name} is not a non-empty string without control characters"
    if config["source"].startswith("/") or _segments_problem(config["source"]):
        return "config source is not a relative path of non-empty segments other than . and .."
    if "identity_env" in config and ENV_NAME.fullmatch(config["identity_env"]) is None:
        return "config identity_env is not an environment variable name"
    return None


def _observation(outcome: str, reason: str, *, path: str | None = None,
                 stamp: dict[str, str] | None = None, signature: dict[str, Any] | None = None,
                 detail: str | None = None) -> dict[str, Any]:
    facts: dict[str, Any] = {"path": path, "stamp": stamp, "signature": signature}
    if detail is not None:
        facts["detail"] = detail[:DETAIL_LIMIT]
    return {"outcome": outcome, "reason": reason,
            "observed_subject": {"version": stamp["version"] if stamp else None,
                                 "commit": stamp["commit"] if stamp else None,
                                 "identifier": signature["identifier"] if signature else None,
                                 "authority": signature["authority"] if signature else None},
            "references": [] if path is None else [path], "observed_at": _now_ms(), "facts": facts}


def _run(argv: list[str], deadline: float) -> tuple[str, int, str, str]:
    """Run `argv` by name within what is left of `deadline`: `(status, code, stderr, detail)`.

    `status` is `"ok"` or one of `lookup_timeout`, `executable_missing` and `lookup_failed`,
    and then `code` is -1. `detail` is the bounded stderr, empty on `lookup_timeout`, the
    operating-system error on `executable_missing`, and `<name> could not be started: <error>`
    for an argument the operating system cannot pass.
    """
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return "lookup_timeout", -1, "", ""
    try:
        done = subprocess.run(argv, capture_output=True, text=True, errors="replace",
                              timeout=remaining, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return "lookup_timeout", -1, "", ""
    except OSError as error:
        return "executable_missing", -1, "", str(error)
    except ValueError as error:
        return "lookup_failed", -1, "", f"{argv[0]} could not be started: {error}"
    return "ok", done.returncode, done.stderr, done.stderr.strip()[:DETAIL_LIMIT]


def _stamp(info: dict[str, Any]) -> dict[str, str] | None:
    version, commit = info.get(STAMP_VERSION), info.get(STAMP_COMMIT)
    if isinstance(version, str) and isinstance(commit, str):
        return {"version": version, "commit": commit}
    return None


def _signature(stderr: str) -> dict[str, Any]:
    """`{identifier, authority, team_identifier, adhoc}` from `codesign -d --verbose=2` stderr."""
    identifier = authority = team = None
    adhoc = False
    for line in stderr.splitlines():
        key, separator, value = line.strip().partition("=")
        if not separator:
            continue
        if key == "Identifier":
            identifier = value
        elif key == "Authority" and authority is None:
            authority = value
        elif key == "TeamIdentifier":
            team = None if value == "not set" else value
        elif key == "Signature" and value == "adhoc":
            adhoc = True
    return {"identifier": identifier, "authority": authority, "team_identifier": team,
            "adhoc": adhoc}


def _classify(parameters: dict[str, Any], deadline: float) -> dict[str, Any]:
    """The effect observation of one valid install request: the spec's `inspect` table."""
    path = os.path.expanduser("~") + "/" + parameters["target"]["path"][2:]
    candidate = parameters["candidate"]

    def seen(outcome: str, reason: str, **facts: Any) -> dict[str, Any]:
        return _observation(outcome, reason, path=path, **facts)

    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        return seen("absent", "bundle_absent")
    except OSError as error:
        return seen("unknown", "lookup_failed", detail=str(error))
    if not stat.S_ISDIR(mode):
        return seen("diverged", "target_unexpected")
    try:
        with open(os.path.join(path, "Contents", "Info.plist"), "rb") as handle:
            info = plistlib.load(handle)
    except (OSError, ValueError, xml.parsers.expat.ExpatError):
        return seen("diverged", "target_unexpected")
    if not isinstance(info, dict):
        return seen("diverged", "target_unexpected")
    stamp = _stamp(info)
    if stamp is None:
        return seen("absent", "bundle_unmanaged")
    if stamp != candidate:
        return seen("absent", "bundle_other_release", stamp=stamp)
    status, code, _, detail = _run(["codesign", "--verify", "--deep", "--strict", path], deadline)
    if status != "ok":
        return seen("unknown", status, stamp=stamp, detail=detail)
    if code in (1, 3):
        return seen("diverged", "signature_invalid", stamp=stamp, detail=detail)
    if code != 0:
        return seen("unknown", "lookup_failed", stamp=stamp, detail=detail)
    status, code, stderr, detail = _run(["codesign", "-d", "--verbose=2", path], deadline)
    if status != "ok" or code != 0:
        return seen("unknown", status if status != "ok" else "lookup_failed", stamp=stamp,
                    detail=detail)
    signature = _signature(stderr)
    if signature["adhoc"] and not parameters["config"]["adhoc_fallback"]:
        return seen("diverged", "signature_policy", stamp=stamp, signature=signature)
    return seen("satisfied", "installed", stamp=stamp, signature=signature)


def _effect(operation: Any, parameters: Any, deadline: float) -> dict[str, Any]:
    if operation != "install":
        return _observation("unknown", "parameters_invalid",
                            detail=f"unknown operation {operation!r}")
    problem = _parameters_problem(parameters)
    if problem is not None:
        return _observation("unknown", "parameters_invalid", detail=problem)
    return _classify(parameters, deadline)


def _predicate(outcome: str, reason: str, references: list[str] | None = None) -> dict[str, Any]:
    return {"outcome": outcome, "reason": reason, "references": references or [],
            "observed_at": _now_ms()}


def _visible(request: dict[str, Any], deadline: float) -> dict[str, Any]:
    """The `publication_visible` answer for one request: the effect row's last column."""
    if set(request) != PREDICATE_SHAPE:
        return _predicate("unknown", "store_unreachable")
    observed = _effect(request["operation"], request["parameters"], deadline)
    if observed["outcome"] == "unknown":
        return _predicate("unknown", "store_unreachable", observed["references"])
    outcome, reason = VISIBLE[observed["reason"]]
    return _predicate(outcome, reason, observed["references"])


def inspect(request: Any) -> dict[str, Any]:
    """The effect or predicate observation of one request. Never raises, never mutates."""
    deadline = time.monotonic() + INSPECT_BUDGET_SECONDS
    if isinstance(request, dict) and request.get("kind") == "predicate":
        if "predicate" in request and request["predicate"] != "publication_visible":
            return _predicate("unknown", "predicate_unsupported")
        return _visible(request, deadline)
    if isinstance(request, dict) and request.get("kind") == "effect" and set(request) == EFFECT_SHAPE:
        return _effect(request["operation"], request["parameters"], deadline)
    return _observation("unknown", "parameters_invalid",
                        detail="request is not a closed effect or predicate request")
