"""The codesigned-artifact adapter (issue 547 D1, D4, D6-D9, D12, D15, D17, D19-D23, D26): `describe`, `inspect`, `invoke`.

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
--strict` and `-d --verbose=2` (stderr), by the table in the issue 547 spec. An existing
component between `$HOME` and the install path's parent that is a symlink or not a directory
classifies as a symlinked install path does, `diverged`/`target_unexpected` (issue 547 D26). Every child runs by
name on `PATH` with the caller's environment unchanged, under one `INSPECT_BUDGET_SECONDS`
deadline per call. `publication_visible` maps the effect row by the table's last column.

`invoke(request)` never raises and returns the closed `InvokeResult`. Every refusal reference is
`<step>: <detail>`, cut to 240 characters, and one `INVOKE_BUDGET_SECONDS` deadline covers all its
children, which run by name on `PATH` with the caller's environment unchanged: `git`, `security`
and `codesign`, never the lifecycle guard (issue 547 D12) and never a build (issue 547 D9). It stops at the first
refusal, in this order:

1. Shape: not exactly an effect request is `invalid_input`, an operation `describe` does not
   declare is `unsupported_operation`, parameters that fail the shape check `inspect` applies are
   `invalid_input`. No child starts.
2. Authority: uid 0 is `authorization_denied`.
3. Checkout: the working directory's `git rev-parse --show-toplevel` must be absolute, HEAD must
   be the candidate commit and no tracked file may be modified, else `precondition_failed`. A
   read that times out is `transient_transport`, one that cannot start or exits non-zero is
   `provider_unavailable`; the same answers apply to the `security` read in step 5.
4. Source: `<root>/<source>` is a directory that is not a symlink, `Contents` is not a symlink and
   `Contents/Info.plist` is a regular file that loads as a dictionary, else `precondition_failed`
   (issue 547 D23).
5. Identity: the `identity_env` value when set and non-empty (a listed name, or a listed hash in
   any case), else the first listed name starting with `identity_prefix`, else `-` when
   `adhoc_fallback` is true. No match is `precondition_failed` with `no_signing_identity`, and an
   env value that matches nothing never falls back.
6. Install path: an existing one that is a symlink or not a directory, or an existing component
   between `$HOME` and its parent that is a symlink or not a directory (issue 547 D26), is
   `precondition_failed`, so no later step writes outside `$HOME`. Missing components are made
   in step 7.
7. Staging (issue 547 D20): the parent is made, stale `.<name>.release-staging` and `.<name>.release-previous`
   siblings are removed, the source is copied with its symlinks into the staging directory, the
   two stamp keys are written by replacing `Contents/Info.plist` with a temporary file in the
   same directory (issue 547 D23), and `codesign --force --sign` then `--verify --deep --strict` must pass.
   Any failure removes staging and is `rejected`: `provider_unavailable` for an operating-system
   error or a missing `codesign`, `transient_transport` for a timeout, `precondition_failed` for
   a non-zero exit.
8. Swap (issue 547 D15, D20): an existing bundle is renamed to the previous sibling, then the staged bundle
   to the install path. A failed rename did not happen: before any rename succeeded it is
   `rejected`/`provider_unavailable` with staging removed, after one it is
   `unknown`/`transient_transport` with the files left as they are. Then the previous sibling and
   the staging directory are removed and the result is `accepted` with the install path.

It is registered as `codesigned-artifact`. Its one operation, `install`, has both non-spend
effect classes and no recovery operation. It signs with the hash of the `identity_env` value
when set, else of the first listed identity starting with `identity_prefix`, else ad hoc only
when `adhoc_fallback` is true. It never builds: it installs what the checkout holds when HEAD
is the candidate and no tracked file changed, and cannot prove the bundle was built from that
commit (issue 547 D9). A failure before the first rename is `rejected` and leaves the install
path as it was, and a rename that fails after the old bundle moved is `unknown` (issue 547
D15). `tests/host_world.py` fakes `security` and `codesign` behind a fake-only `PATH`.
"""

import os
import plistlib
import re
import shutil
import stat
import subprocess
import tempfile
import time
from typing import Any

INSPECT_BUDGET_SECONDS = 30
INVOKE_BUDGET_SECONDS = 120
DETAIL_LIMIT = 240
STAMP_VERSION = "AgentReleaseVersion"
STAMP_COMMIT = "AgentReleaseCommit"
CONFIG_MEMBERS = {"source": "string", "identity_prefix": "string", "identity_env": "string",
                  "adhoc_fallback": "boolean"}
REQUIRED_CONFIG = ("adhoc_fallback", "identity_prefix", "source")
VERSION = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+")
COMMIT = re.compile(r"[0-9a-f]{40}")
IDENTITY_LINE = re.compile(r'^\s*\d+\)\s+([0-9A-Fa-f]{40})\s+"(.+)"\s*$')
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
    """The first way `parameters` departs from the closed install shape, or None (issue 547 D17)."""
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


def _spawn(argv: list[str], deadline: float) -> tuple[str, subprocess.CompletedProcess | None, str]:
    """Run `argv` by name within what is left of `deadline`: `(status, process, detail)`.

    `status` is `"ok"` (the process finished, whatever its exit) or one of `lookup_timeout`,
    `executable_missing` and `lookup_failed`, and then `process` is None. `detail` is empty on
    `lookup_timeout`, the operating-system error on `executable_missing`, and
    `<name> could not be started: <error>` for an argument the operating system cannot pass.
    """
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return "lookup_timeout", None, ""
    try:
        done = subprocess.run(argv, capture_output=True, text=True, errors="replace",
                              timeout=remaining, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return "lookup_timeout", None, ""
    except OSError as error:
        return "executable_missing", None, str(error)
    except ValueError as error:
        return "lookup_failed", None, f"{argv[0]} could not be started: {error}"
    return "ok", done, ""


def _run(argv: list[str], deadline: float) -> tuple[str, int, str, str]:
    """`_spawn` as `(status, code, stderr, detail)`: `code` is -1 unless `status` is `"ok"`.

    `detail` is the bounded stderr when the process finished, else `_spawn`'s detail.
    """
    status, done, detail = _spawn(argv, deadline)
    if done is None:
        return status, -1, "", detail
    return "ok", done.returncode, done.stderr, done.stderr.strip()[:DETAIL_LIMIT]


def _loads(data: bytes) -> Any:
    """`plistlib.loads` with every parse failure as one `ValueError`.

    The standard library raises more than `ValueError` and `ExpatError` for malformed input (a
    `<date>` that is not a date raises `AttributeError`), so the translation is wide on purpose.
    """
    try:
        return plistlib.loads(data)
    except Exception as error:
        raise ValueError("does not load as a plist") from error


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


def _install_path(parameters: dict[str, Any]) -> str:
    return os.path.expanduser("~") + "/" + parameters["target"]["path"][2:]


def _ancestor_problem(parameters: dict[str, Any]) -> str | None:
    """The first existing component between `$HOME` and the install path's parent that is a
    symlink or not a directory, or None (issue 547 D26).

    A missing component ends the walk, since every deeper one is missing too. Any other
    `lstat` failure propagates as `OSError`.
    """
    current = os.path.expanduser("~")
    for segment in parameters["target"]["path"][2:].split("/")[:-1]:
        current = current + "/" + segment
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            return None
        if not stat.S_ISDIR(mode):
            return f"{current} is a symlink or not a directory"
    return None


def _classify(parameters: dict[str, Any], deadline: float) -> dict[str, Any]:
    """The effect observation of one valid install request: the spec's `inspect` table."""
    path = _install_path(parameters)
    candidate = parameters["candidate"]

    def seen(outcome: str, reason: str, **facts: Any) -> dict[str, Any]:
        return _observation(outcome, reason, path=path, **facts)

    try:
        if _ancestor_problem(parameters) is not None:
            return seen("diverged", "target_unexpected")
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        return seen("absent", "bundle_absent")
    except OSError as error:
        return seen("unknown", "lookup_failed", detail=str(error))
    if not stat.S_ISDIR(mode):
        return seen("diverged", "target_unexpected")
    try:
        with open(os.path.join(path, "Contents", "Info.plist"), "rb") as handle:
            info = _loads(handle.read())
    except (OSError, ValueError):
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


class _Refusal(Exception):
    """An `invoke` that ends here: the closed `InvokeResult` to return."""

    def __init__(self, result: str, error_class: str, step: str, detail: str) -> None:
        reference = f"{step}: {detail}"[:DETAIL_LIMIT]
        super().__init__(reference)
        self.answer = {"result": result, "error_class": error_class, "reference": reference}


def _rejected(error_class: str, step: str, detail: str) -> _Refusal:
    return _Refusal("rejected", error_class, step, detail)


def _read(argv: list[str], step: str, deadline: float) -> str:
    """Stdout of one read before any write; a failed read is a refusal (issue 547 D15)."""
    status, done, detail = _spawn(argv, deadline)
    if status == "lookup_timeout":
        raise _rejected("transient_transport", step, "timed out")
    if done is None:
        raise _rejected("provider_unavailable", step, detail)
    if done.returncode != 0:
        raise _rejected("provider_unavailable", step,
                        done.stderr.strip() or f"exit {done.returncode}")
    return done.stdout


def _invoke_shape(request: Any) -> dict[str, Any]:
    """The parameters of a request that is a declared, valid install effect."""
    if not (isinstance(request, dict) and set(request) == EFFECT_SHAPE
            and request["kind"] == "effect" and isinstance(request["operation"], str)):
        raise _rejected("invalid_input", "shape", "request is not a closed effect request")
    operation = request["operation"]
    if operation not in describe()["operations"]:
        raise _rejected("unsupported_operation", "shape", f"{operation}: unknown_operation")
    problem = _parameters_problem(request["parameters"])
    if problem is not None:
        raise _rejected("invalid_input", "shape", problem)
    return request["parameters"]


def _checkout(commit: str, deadline: float) -> str:
    """The working checkout's root, when HEAD is `commit` and no tracked file is modified (#124 D23)."""
    root = _read(["git", "rev-parse", "--show-toplevel"], "checkout", deadline).strip()
    if not os.path.isabs(root):
        raise _rejected("provider_unavailable", "checkout", "rev-parse did not return a directory")
    head = _read(["git", "-C", root, "rev-parse", "HEAD"], "checkout", deadline).strip()
    if head != commit:
        raise _rejected("precondition_failed", "checkout", f"HEAD is {head}, not {commit}")
    modified = _read(["git", "-C", root, "status", "--porcelain", "--untracked-files=no"],
                     "checkout", deadline)
    if modified.strip():
        raise _rejected("precondition_failed", "checkout", "a tracked file is modified")
    return root


def _plist(path: str) -> tuple[dict[str, Any], bool]:
    """The dictionary of the regular file at `path`, and whether it is a binary plist."""
    if not stat.S_ISREG(os.lstat(path).st_mode):
        raise ValueError("not a regular file")
    with open(path, "rb") as handle:
        data = handle.read()
    info = _loads(data)
    if not isinstance(info, dict):
        raise ValueError("not a dictionary")
    return info, data.startswith(b"bplist00")


PLIST_ERRORS = (OSError, ValueError)


def _source(root: str, source: str) -> str:
    """The source bundle, when no link stands in for it, its `Contents` or its plist (issue 547 D23)."""
    bundle = os.path.join(root, source)
    contents = os.path.join(bundle, "Contents")
    try:
        if not stat.S_ISDIR(os.lstat(bundle).st_mode):
            raise ValueError(f"{source} is not a directory")
        if stat.S_ISLNK(os.lstat(contents).st_mode):
            raise ValueError(f"{source}/Contents is a symlink")
        _plist(os.path.join(contents, "Info.plist"))
    except PLIST_ERRORS as error:
        raise _rejected("precondition_failed", "source", str(error)) from error
    return bundle


def _identity(config: dict[str, Any], deadline: float) -> str:
    """The `codesign --sign` argument: a listed hash, or `-` when ad-hoc signing is allowed."""
    listing = _read(["security", "find-identity", "-v", "-p", "codesigning"], "identity", deadline)
    pairs = [match.groups() for match in map(IDENTITY_LINE.match, listing.splitlines()) if match]
    variable = config.get("identity_env")
    value = os.environ.get(variable, "") if variable else ""
    if value:
        for digest, name in pairs:
            if value == name or value.lower() == digest.lower():
                return digest
        raise _rejected("precondition_failed", "identity",
                        f"no_signing_identity: {variable} names no listed identity")
    for digest, name in pairs:
        if name.startswith(config["identity_prefix"]):
            return digest
    if config["adhoc_fallback"]:
        return "-"
    raise _rejected("precondition_failed", "identity",
                    f"no_signing_identity: none starts with {config['identity_prefix']}")


def _install_state(parameters: dict[str, Any], path: str) -> bool:
    """Whether a bundle directory stands at `path`; a symlink or non-directory there, or at an
    existing component between `$HOME` and its parent, is a refusal (issue 547 D26)."""
    try:
        problem = _ancestor_problem(parameters)
        if problem is not None:
            raise _rejected("precondition_failed", "install path", problem)
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        return False
    except OSError as error:
        raise _rejected("provider_unavailable", "install path", str(error)) from error
    if not stat.S_ISDIR(mode):
        raise _rejected("precondition_failed", "install path", f"{path} is not a directory")
    return True


def _remove(path: str) -> None:
    """Remove whatever stands at `path` without following a symlink."""
    if os.path.islink(path) or not os.path.isdir(path):
        if os.path.lexists(path):
            os.unlink(path)
    else:
        shutil.rmtree(path)


def _stamp_plist(staged: str, candidate: dict[str, str]) -> None:
    """Set the two stamp keys by replacing `Info.plist`, never writing through it (issue 547 D23).

    A failure leaves its temporary file inside the staging directory, which the caller removes.
    """
    contents = os.path.join(staged, "Contents")
    target = os.path.join(contents, "Info.plist")
    info, binary = _plist(target)
    info[STAMP_VERSION], info[STAMP_COMMIT] = candidate["version"], candidate["commit"]
    descriptor, temporary = tempfile.mkstemp(prefix=".Info.plist.", dir=contents)
    with os.fdopen(descriptor, "wb") as handle:
        os.fchmod(handle.fileno(), stat.S_IMODE(os.lstat(target).st_mode))
        try:
            plistlib.dump(info, handle, fmt=plistlib.FMT_BINARY if binary else plistlib.FMT_XML)
        except (TypeError, OverflowError) as error:
            raise ValueError("cannot be written back as a plist") from error
    os.replace(temporary, target)


def _codesign(argv: list[str], step: str, deadline: float) -> None:
    status, done, detail = _spawn(argv, deadline)
    if status == "lookup_timeout":
        raise _rejected("transient_transport", step, "timed out")
    if done is None:
        raise _rejected("provider_unavailable", step, detail)
    if done.returncode != 0:
        raise _rejected("precondition_failed", step, done.stderr.strip() or f"exit {done.returncode}")


def _stage(source: str, staging: str, staged: str, candidate: dict[str, str], identity: str,
           deadline: float) -> None:
    """Build and sign the staged bundle (issue 547 D20); every failure is a `rejected` refusal."""
    try:
        os.mkdir(staging)
        shutil.copytree(source, staged, symlinks=True)
        _stamp_plist(staged, candidate)
    except PLIST_ERRORS as error:
        error_class = "provider_unavailable" if isinstance(error, OSError) else "precondition_failed"
        raise _rejected(error_class, "stage", str(error)) from error
    _codesign(["codesign", "--force", "--sign", identity, staged], "sign", deadline)
    _codesign(["codesign", "--verify", "--deep", "--strict", staged], "verify", deadline)


def _swap(path: str, previous: str, staging: str, staged: str, exists: bool) -> None:
    """Move the staged bundle into place; the first rename is the first write to the install path."""
    renamed = False
    try:
        if exists:
            os.rename(path, previous)
            renamed = True
        os.rename(staged, path)
    except OSError as error:
        if renamed:
            raise _Refusal("unknown", "transient_transport", "swap", str(error)) from error
        shutil.rmtree(staging, ignore_errors=True)
        raise _rejected("provider_unavailable", "swap", str(error)) from error
    shutil.rmtree(previous, ignore_errors=True)
    try:
        os.rmdir(staging)
    except OSError:
        pass


def _invoke(parameters: dict[str, Any], deadline: float) -> dict[str, Any]:
    if os.getuid() == 0:
        raise _Refusal("rejected", "authorization_denied", "authority", "refusing to install as uid 0")
    candidate, config = parameters["candidate"], parameters["config"]
    source = _source(_checkout(candidate["commit"], deadline), config["source"])
    identity = _identity(config, deadline)
    path = _install_path(parameters)
    exists = _install_state(parameters, path)
    parent, name = os.path.split(path)
    staging = os.path.join(parent, f".{name}.release-staging")
    previous = os.path.join(parent, f".{name}.release-previous")
    staged = os.path.join(staging, name)
    try:
        os.makedirs(parent, exist_ok=True)
        _remove(staging)
        _remove(previous)
    except OSError as error:
        raise _rejected("provider_unavailable", "stage", str(error)) from error
    try:
        _stage(source, staging, staged, candidate, identity, deadline)
    except _Refusal:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    _swap(path, previous, staging, staged, exists)
    return {"result": "accepted", "error_class": None, "reference": path}


def invoke(request: Any) -> dict[str, Any]:
    """The `InvokeResult` of one install request: `{result, error_class, reference}`.

    A refusal before the first rename leaves the install path as it was (issue 547 D15, D20).
    """
    deadline = time.monotonic() + INVOKE_BUDGET_SECONDS
    try:
        return _invoke(_invoke_shape(request), deadline)
    except _Refusal as refusal:
        return refusal.answer
