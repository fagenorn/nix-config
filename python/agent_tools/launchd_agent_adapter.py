"""The launchd-agent adapter (issue 547 D1, D4-D8, D12, D13, D15, D17-D19, D21): `describe`, `inspect`, `invoke`.

`describe()` returns a fresh descriptor with one operation, `activate`: `local_apply` mode,
`in_place` mutability, `supported` for `inspect`. `agent_running` and `running_subject_identity`
are supported and `publication_visible` is not (`no_publication_mode`). The target kind is
`launchd_gui_agent` with a `label`, the credential class is `gui_session`, and the closed config
is `program`, `keep_alive`, `arguments`, `background`, `stdout_path` and `stderr_path`. The domain
is always `gui/<os.getuid()>` and the plist is always `~/Library/LaunchAgents/<label>.plist`
(issue 547 D7).

This module imports only the standard library: the registry in `release_adapter` imports
adapters, never the reverse, so its inner checks are its own.

`inspect(request)` never raises and never mutates. A request outside the closed shape is
`unknown`/`parameters_invalid` for an effect and for `agent_running`, and
`unknown`/`identity_unobservable` for `running_subject_identity` (issue 547 D19); any other
predicate is `unknown`/`predicate_unsupported`. The shape rules, first failing one reported in
`facts.detail` (issue 547 D17):

- An effect request is exactly `{kind, operation, parameters}` and a predicate request exactly
  `{kind, predicate, operation, parameters}`; the operation is `activate`.
- `parameters` holds `target`, `config` and `candidate`, and may hold `action` and `operation`.
  `candidate` is required for an effect and for `running_subject_identity`, optional for
  `agent_running`, and exactly a `vMAJOR.MINOR.PATCH` version and a 40 lowercase hex commit.
- `target` is `launchd_gui_agent` with a label matching `[A-Za-z0-9][A-Za-z0-9._-]{0,127}` and an
  optional handle. Strings are non-empty and free of control characters.
- `config` requires `program` (a bare name) and `keep_alive`; `arguments` is a non-empty list of
  unique strings; `background` is a boolean; the two log paths are relative with non-empty
  segments other than `.` and `..`.

A valid request runs `launchctl print gui/<uid>/<label>` and parses it by the grammar of issue
547 D21: a field is a line with exactly one leading tab, `key = value`; the stamp
(`AGENT_RELEASE_VERSION` and `AGENT_RELEASE_COMMIT`) is read only inside the block opened by the
one-tab line `environment = {` and closed by the next one-tab `}`; `path`, `state` and an integer
`runs` are required (else `payload_invalid`), `pid` and `working directory` are optional. An effect
request also `lstat`s the plist and, when the stamp names the candidate, reads the working
directory with `git --no-optional-locks` (`rev-parse HEAD` and `status --porcelain
--untracked-files=no`). The effect rows follow the `inspect` table of the issue 547 spec;
`running_subject_identity` maps each row by that table's last column, and `agent_running` follows
its § Liveness table with `print` alone. Every child runs by name on `PATH` with the caller's
environment unchanged, under one `INSPECT_BUDGET_SECONDS` deadline per call.

`invoke(request)` never raises and returns a closed `InvokeResult`. Each step below refuses with
`<step>: <detail>` (at most 240 characters) and stops there, under one `INVOKE_BUDGET_SECONDS`
deadline for every child; a child started with no budget left is a timeout. It runs only `git`
and `launchctl`, by name, and never the lifecycle guard or `kickstart` (issue 547 D2, D12):

1. `shape`: the request is exactly an `activate` effect whose parameters pass the shape check of
   `inspect` (`invalid_input`; an undeclared operation is `unsupported_operation`).
2. `authority`: uid 0 is `authorization_denied`.
3. `checkout` (#124 D23): HEAD of the working directory's repository is the candidate commit and
   no tracked file is modified, else `precondition_failed`. A read that times out is
   `transient_transport` and one that fails otherwise is `provider_unavailable`.
4. `program`: `shutil.which` resolves the bare program name, else `precondition_failed`.
5. `plist path`: an existing plist path must be a regular file, not a symlink.
6. `print`: not loaded (exit 113) continues; loaded must come from the managed plist, else
   `precondition_failed`; any other outcome is `provider_unavailable`, a timeout
   `transient_transport`.

Steps 1 to 6 are `rejected`: nothing was written. The first host write is the `bootout` of a
loaded agent, or the plist write when nothing was loaded (issue 547 D15), so from there a failure
is `unknown`/`transient_transport` unless it provably left the host as it was:

7. `bootout`: a non-zero exit left the agent loaded (`rejected`), a timeout is `unknown`.
8. `plist write`: the rendered plist goes to a temporary file in `~/Library/LaunchAgents`,
   mode 0644, then `os.replace`s the plist path. A failure removes the temporary file and is
   `rejected`/`provider_unavailable` when nothing was booted out, else `unknown`.
9. `bootstrap`: exit 0 is `accepted` with the reference `gui/<uid>/<label>`; anything else is
   `unknown`.

The plist (issue 547 D8, D18) holds `Label`, `ProgramArguments` (the resolved program path and
`arguments`, with no `/bin/wait4path` wrapper), `WorkingDirectory` (the checkout root),
`RunAtLoad`, `KeepAlive`, `EnvironmentVariables` (exactly the two stamp variables),
`ProcessType` `Background` only when `background` is true, and the two log paths joined to the
checkout root only when configured.
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
INVOKE_BUDGET_SECONDS = 60
DETAIL_LIMIT = 240
NOT_LOADED_EXIT = 113
STAMP_VERSION = "AGENT_RELEASE_VERSION"
STAMP_COMMIT = "AGENT_RELEASE_COMMIT"
CONFIG_MEMBERS = {"arguments": "string_list", "background": "boolean", "keep_alive": "boolean",
                  "program": "string", "stderr_path": "string", "stdout_path": "string"}
REQUIRED_CONFIG = ("keep_alive", "program")
LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
VERSION = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+")
COMMIT = re.compile(r"[0-9a-f]{40}")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
FIELD = re.compile(r"^\t([^\t][^=]*?) = (.*)$")
VARIABLE = re.compile(r"^\t\t(\S+) => (.*)$")
INTEGER = re.compile(r"[0-9]{1,18}")
ENVIRONMENT_OPEN = "\tenvironment = {"
BLOCK_CLOSE = "\t}"
OPERATION = "activate"
EFFECT_SHAPE = frozenset(("kind", "operation", "parameters"))
PREDICATE_SHAPE = frozenset(("kind", "predicate", "operation", "parameters"))
PARAMETER_MEMBERS = frozenset(("target", "candidate", "config", "action", "operation"))
PREDICATES = ("agent_running", "running_subject_identity")
# The running_subject_identity column of the spec's table, by the effect row's reason (issue 547 D19).
IDENTITY = {"plist_unexpected": ("unsatisfied", "subject_mismatch"),
            "agent_not_loaded": ("unsatisfied", "subject_absent"),
            "agent_path_foreign": ("unsatisfied", "subject_mismatch"),
            "agent_unmanaged": ("unsatisfied", "unrelated_subject_running"),
            "agent_other_release": ("unsatisfied", "subject_mismatch"),
            "checkout_moved": ("unsatisfied", "subject_mismatch"),
            "agent_not_running": ("unsatisfied", "subject_absent"),
            "running": ("satisfied", "running")}


def describe() -> dict[str, Any]:
    """The `launchd-agent` descriptor (issue 547 D1, D2, D7, D8), a fresh plain dict."""
    return {
        "name": "launchd-agent",
        "adapter_contract_version": "1.0.0",
        "operations": {
            OPERATION: {"mode": "local_apply", "support": "supported", "inspect": "supported",
                        "reason": None, "mutability": "in_place", "config_schema_version": 1,
                        "config_schema": {"members": dict(CONFIG_MEMBERS),
                                          "required": list(REQUIRED_CONFIG)},
                        "effects": ["reversible_no_incremental_spend", "irreversible"],
                        "recovery_capable": False, "candidate_members": []},
        },
        "predicates": {
            "agent_running": {"support": "supported", "reason": None},
            "publication_visible": {"support": "unsupported", "reason": "no_publication_mode"},
            "running_subject_identity": {"support": "supported", "reason": None},
        },
        "collector": {"max_collection_latency_ms": 30000, "max_concurrent_collections": 1},
        "target_kinds": {"launchd_gui_agent": ["label"]},
        "credential_classes": ["gui_session"],
        "executables": ["git", "launchctl"],
        "host_capacity": "not_required",
    }


def _now_ms() -> int:
    return int(time.time() * 1000)


def _text(value: object) -> bool:
    return isinstance(value, str) and value != "" and CONTROL.search(value) is None


def _relative_path(value: object) -> bool:
    return (_text(value) and not value.startswith("/")
            and not any(part in ("", ".", "..") for part in value.split("/")))


def _candidate_problem(candidate: Any) -> str | None:
    if (not isinstance(candidate, dict) or set(candidate) != {"version", "commit"}
            or not isinstance(candidate["version"], str)
            or VERSION.fullmatch(candidate["version"]) is None
            or not isinstance(candidate["commit"], str)
            or COMMIT.fullmatch(candidate["commit"]) is None):
        return "candidate is not exactly a vMAJOR.MINOR.PATCH version and a 40 lowercase hex commit"
    return None


def _target_problem(target: Any) -> str | None:
    if (not isinstance(target, dict) or not {"kind", "label"} <= set(target)
            or set(target) - {"kind", "label", "handle"} or target["kind"] != "launchd_gui_agent"):
        return "target is not a launchd_gui_agent of exactly kind and label, and an optional handle"
    if "handle" in target and not _text(target["handle"]):
        return "target handle is not a non-empty string"
    if not isinstance(target["label"], str) or LABEL.fullmatch(target["label"]) is None:
        return "target label does not match [A-Za-z0-9][A-Za-z0-9._-]{0,127}"
    return None


def _config_problem(config: Any) -> str | None:
    if (not isinstance(config, dict) or set(config) - set(CONFIG_MEMBERS)
            or set(REQUIRED_CONFIG) - set(config)):
        return f"config is not the declared members {', '.join(CONFIG_MEMBERS)}"
    program = config["program"]
    if not _text(program) or "/" in program or program in (".", ".."):
        return "config program is not a bare command name"
    if "arguments" in config:
        arguments = config["arguments"]
        if (not isinstance(arguments, list) or not arguments
                or not all(_text(item) for item in arguments)
                or len(set(arguments)) != len(arguments)):
            return "config arguments is not a non-empty list of unique non-empty strings"
    for name in ("keep_alive", "background"):
        if name in config and not isinstance(config[name], bool):
            return f"config {name} is not a boolean"
    for name in ("stdout_path", "stderr_path"):
        if name in config and not _relative_path(config[name]):
            return f"config {name} is not a relative path of non-empty segments other than . and .."
    return None


def _parameters_problem(operation: Any, parameters: Any, *, candidate_required: bool) -> str | None:
    """The first way a request departs from the closed activate shape, or None (issue 547 D17)."""
    if operation != OPERATION:
        return f"operation is not {OPERATION}"
    if not isinstance(parameters, dict):
        return "parameters is not an object"
    undeclared = sorted(set(parameters) - PARAMETER_MEMBERS, key=str)
    if undeclared:
        return f"parameters has an undeclared member {undeclared[0]}"
    for name in ("target", "config") + (("candidate",) if candidate_required else ()):
        if name not in parameters:
            return f"parameters is missing {name}"
    if parameters.get("operation", OPERATION) != OPERATION:
        return f"parameters operation is not {OPERATION}"
    problem = _target_problem(parameters["target"])
    if problem is None and "candidate" in parameters:
        problem = _candidate_problem(parameters["candidate"])
    return problem or _config_problem(parameters["config"])


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _plist_path(label: str) -> str:
    return os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents", f"{label}.plist")


class _Unreadable(Exception):
    """A read that did not answer: the closed `unknown` reason and the bounded detail."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail[:DETAIL_LIMIT]


def _run(argv: list[str], deadline: float) -> subprocess.CompletedProcess:
    """Run `argv` by name within what is left of `deadline`; any failure to finish is `_Unreadable`."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _Unreadable("lookup_timeout")
    try:
        return subprocess.run(argv, capture_output=True, text=True, errors="replace",
                              timeout=remaining, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise _Unreadable("lookup_timeout") from None
    except OSError as error:
        raise _Unreadable("executable_missing", str(error)) from error
    except ValueError as error:
        raise _Unreadable("lookup_failed", f"{argv[0]} could not be started: {error}") from error


def _parse_print(output: str) -> dict[str, Any]:
    """The job's `path`, `state`, `pid`, `runs`, `working_directory` and `stamp` from `print` stdout."""
    fields: dict[str, str] = {}
    variables: dict[str, str] = {}
    in_environment = False
    for line in output.splitlines():
        if in_environment:
            if line == BLOCK_CLOSE:
                in_environment = False
                continue
            match = VARIABLE.match(line)
            if match:
                variables[match.group(1)] = match.group(2)
        elif line == ENVIRONMENT_OPEN:
            in_environment = True
        else:
            match = FIELD.match(line)
            if match:
                fields.setdefault(match.group(1), match.group(2))
    runs, pid = fields.get("runs"), fields.get("pid")
    if ("path" not in fields or "state" not in fields or runs is None
            or INTEGER.fullmatch(runs) is None or (pid is not None and INTEGER.fullmatch(pid) is None)):
        raise _Unreadable("payload_invalid", "print output lacks path, state or an integer runs")
    stamp = None
    if STAMP_VERSION in variables and STAMP_COMMIT in variables:
        stamp = {"version": variables[STAMP_VERSION], "commit": variables[STAMP_COMMIT]}
    return {"path": fields["path"], "state": fields["state"], "pid": None if pid is None else int(pid),
            "runs": int(runs), "working_directory": fields.get("working directory"), "stamp": stamp}


def _load(label: str, deadline: float) -> dict[str, Any] | None:
    """The parsed job, or None when it is not loaded; any other outcome is `_Unreadable`."""
    done = _run(["launchctl", "print", f"{_domain()}/{label}"], deadline)
    if done.returncode == NOT_LOADED_EXIT:
        return None
    if done.returncode != 0:
        raise _Unreadable("lookup_failed", done.stderr.strip() or f"exit {done.returncode}")
    return _parse_print(done.stdout)


def _git(directory: str, deadline: float, *argv: str) -> str:
    done = _run(["git", "--no-optional-locks", "-C", directory, *argv], deadline)
    if done.returncode != 0:
        raise _Unreadable("lookup_failed", done.stderr.strip() or f"exit {done.returncode}")
    return done.stdout


def _checkout(directory: str, deadline: float) -> dict[str, Any]:
    head = _git(directory, deadline, "rev-parse", "HEAD").strip()
    status = _git(directory, deadline, "status", "--porcelain", "--untracked-files=no")
    return {"head": head, "clean": status == ""}


def _facts(label: str | None, **known: Any) -> dict[str, Any]:
    """The eleven fact keys: unread ones are None, and an unknown label has no plist."""
    facts: dict[str, Any] = {name: None for name in (
        "checkout", "loaded", "path", "pid", "runs", "stamp", "state", "working_directory")}
    facts.update(label=label, domain=_domain(),
                 plist=None if label is None else _plist_path(label))
    facts.update(known)
    return facts


def _observation(outcome: str, reason: str, facts: dict[str, Any] | None = None,
                 detail: str | None = None) -> dict[str, Any]:
    """An effect observation; `facts` None is a request that never reached the host."""
    reached = facts is not None
    facts = _facts(None) if facts is None else facts
    stamp = facts["stamp"]
    observed = {"outcome": outcome, "reason": reason,
                "observed_subject": {"version": stamp["version"] if stamp else None,
                                     "commit": stamp["commit"] if stamp else None,
                                     "pid": facts["pid"]},
                "references": [f"{facts['domain']}/{facts['label']}", facts["plist"]] if reached else [],
                "observed_at": _now_ms(), "facts": dict(facts)}
    if detail is not None:
        observed["facts"]["detail"] = detail[:DETAIL_LIMIT]
    return observed


def _classify(parameters: dict[str, Any], deadline: float) -> dict[str, Any]:
    """The effect observation of one valid request: the spec's `inspect` table."""
    label, candidate = parameters["target"]["label"], parameters["candidate"]
    plist = _plist_path(label)

    def seen(outcome: str, reason: str, detail: str | None = None, **known: Any) -> dict[str, Any]:
        return _observation(outcome, reason, _facts(label, **known), detail)

    try:
        mode = os.lstat(plist).st_mode
    except FileNotFoundError:
        pass
    except OSError as error:
        return seen("unknown", "lookup_failed", str(error))
    else:
        if not stat.S_ISREG(mode):
            return seen("diverged", "plist_unexpected")
    try:
        job = _load(label, deadline)
    except _Unreadable as error:
        return seen("unknown", error.reason, error.detail)
    if job is None:
        return seen("absent", "agent_not_loaded", loaded=False)
    known = {**job, "loaded": True}
    if job["path"] != plist:
        return seen("diverged", "agent_path_foreign", **known)
    if job["stamp"] is None:
        return seen("absent", "agent_unmanaged", **known)
    if job["stamp"] != candidate:
        return seen("absent", "agent_other_release", **known)
    if job["working_directory"] is None:
        return seen("diverged", "checkout_moved", **known)
    try:
        checkout = _checkout(job["working_directory"], deadline)
    except _Unreadable as error:
        return seen("unknown", error.reason, error.detail, **known)
    known["checkout"] = checkout
    if checkout["head"] != candidate["commit"] or not checkout["clean"]:
        return seen("diverged", "checkout_moved", **known)
    if job["state"] != "running" or job["pid"] is None:
        return seen("in_progress", "agent_not_running", **known)
    return seen("satisfied", "running", **known)


def _predicate(outcome: str, reason: str, references: list[str] | None = None) -> dict[str, Any]:
    return {"outcome": outcome, "reason": reason, "references": references or [],
            "observed_at": _now_ms()}


def _liveness(parameters: dict[str, Any], deadline: float) -> dict[str, Any]:
    """The `agent_running` answer: `print` alone, by the spec's § Liveness table."""
    label = parameters["target"]["label"]
    references = [f"{_domain()}/{label}", _plist_path(label)]
    try:
        job = _load(label, deadline)
    except _Unreadable as error:
        return _predicate("unknown", error.reason, references)
    if job is None:
        return _predicate("unsatisfied", "agent_not_loaded", references)
    if job["path"] != _plist_path(label):
        return _predicate("unsatisfied", "agent_path_foreign", references)
    if job["state"] != "running" or job["pid"] is None:
        return _predicate("unsatisfied", "agent_not_running", references)
    if job["runs"] > 1:
        return _predicate("unsatisfied", "agent_restarted", references)
    return _predicate("satisfied", "running", references)


def _identity(parameters: dict[str, Any], deadline: float) -> dict[str, Any]:
    """The `running_subject_identity` answer: the effect row's last column (issue 547 D19)."""
    observed = _classify(parameters, deadline)
    if observed["outcome"] == "unknown":
        return _predicate("unknown", "identity_unobservable", observed["references"])
    outcome, reason = IDENTITY[observed["reason"]]
    return _predicate(outcome, reason, observed["references"])


def _answer_predicate(request: dict[str, Any], deadline: float) -> dict[str, Any]:
    name = request.get("predicate")
    if name not in PREDICATES:
        return _predicate("unknown", "predicate_unsupported")
    derived = name == "running_subject_identity"
    if (set(request) != PREDICATE_SHAPE
            or _parameters_problem(request["operation"], request["parameters"],
                                   candidate_required=derived) is not None):
        return _predicate("unknown", "identity_unobservable" if derived else "parameters_invalid")
    return (_identity if derived else _liveness)(request["parameters"], deadline)


def inspect(request: Any) -> dict[str, Any]:
    """The effect or predicate observation of one request. Never raises, never mutates."""
    deadline = time.monotonic() + INSPECT_BUDGET_SECONDS
    if isinstance(request, dict) and request.get("kind") == "predicate":
        return _answer_predicate(request, deadline)
    if isinstance(request, dict) and request.get("kind") == "effect" and set(request) == EFFECT_SHAPE:
        problem = _parameters_problem(request["operation"], request["parameters"],
                                      candidate_required=True)
        if problem is None:
            return _classify(request["parameters"], deadline)
        return _observation("unknown", "parameters_invalid", detail=problem)
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


def _unread(error: _Unreadable, step: str) -> _Refusal:
    """A read before any host write that did not answer: always `rejected` (issue 547 D15)."""
    if error.reason == "lookup_timeout":
        return _rejected("transient_transport", step, "timed out")
    return _rejected("provider_unavailable", step, error.detail or error.reason)


def _read(argv: list[str], step: str, deadline: float) -> str:
    try:
        done = _run(argv, deadline)
    except _Unreadable as error:
        raise _unread(error, step) from error
    if done.returncode != 0:
        raise _rejected("provider_unavailable", step, done.stderr.strip() or f"exit {done.returncode}")
    return done.stdout


def _invoke_shape(request: Any) -> dict[str, Any]:
    """The parameters of a request that is a declared, valid `activate` effect."""
    if not (isinstance(request, dict) and set(request) == EFFECT_SHAPE
            and request["kind"] == "effect" and isinstance(request["operation"], str)):
        raise _rejected("invalid_input", "shape", "request is not a closed effect request")
    operation = request["operation"]
    if operation not in describe()["operations"]:
        raise _rejected("unsupported_operation", "shape", f"{operation}: unknown_operation")
    problem = _parameters_problem(operation, request["parameters"], candidate_required=True)
    if problem is not None:
        raise _rejected("invalid_input", "shape", problem)
    return request["parameters"]


def _checkout_root(commit: str, deadline: float) -> str:
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


def _check_plist_path(plist: str) -> None:
    try:
        mode = os.lstat(plist).st_mode
    except FileNotFoundError:
        return
    except OSError as error:
        raise _rejected("provider_unavailable", "plist path", str(error)) from error
    if not stat.S_ISREG(mode):
        raise _rejected("precondition_failed", "plist path", f"{plist} is not a regular file")


def _loaded(label: str, plist: str, deadline: float) -> bool:
    """Whether the agent is loaded, which it may only be from the managed plist."""
    try:
        job = _load(label, deadline)
    except _Unreadable as error:
        raise _unread(error, "print") from error
    if job is not None and job["path"] != plist:
        raise _rejected("precondition_failed", "print", f"loaded from {job['path']}, not {plist}")
    return job is not None


def _render(label: str, program: str, root: str, config: dict[str, Any],
            candidate: dict[str, str]) -> dict[str, Any]:
    """The plist dictionary of one activation (issue 547 D8, D18)."""
    plist: dict[str, Any] = {
        "Label": label, "ProgramArguments": [program, *config.get("arguments", [])],
        "WorkingDirectory": root, "RunAtLoad": True, "KeepAlive": config["keep_alive"],
        "EnvironmentVariables": {STAMP_VERSION: candidate["version"], STAMP_COMMIT: candidate["commit"]}}
    if config.get("background"):
        plist["ProcessType"] = "Background"
    for key, member in (("StandardOutPath", "stdout_path"), ("StandardErrorPath", "stderr_path")):
        if member in config:
            plist[key] = os.path.join(root, config[member])
    return plist


def _write_plist(path: str, definition: dict[str, Any]) -> None:
    """Replace `path` with `definition`, mode 0644, through a temporary file beside it."""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".release-", suffix=".plist", dir=directory)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            plistlib.dump(definition, handle, fmt=plistlib.FMT_XML, sort_keys=True)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _bootout(service: str, deadline: float) -> None:
    """Boot the agent out. A command that failed or never started left it loaded; a timeout may not."""
    try:
        done = _run(["launchctl", "bootout", service], deadline)
    except _Unreadable as error:
        if error.reason == "lookup_timeout":
            raise _Refusal("unknown", "transient_transport", "bootout", "timed out") from error
        raise _rejected("provider_unavailable", "bootout", error.detail or error.reason) from error
    if done.returncode != 0:
        raise _rejected("transient_transport", "bootout",
                        done.stderr.strip() or f"exit {done.returncode}")


def _bootstrap(plist: str, deadline: float) -> None:
    """Bootstrap the agent from `plist`; after the first host write every failure is `unknown`."""
    try:
        done = _run(["launchctl", "bootstrap", _domain(), plist], deadline)
    except _Unreadable as error:
        raise _Refusal("unknown", "transient_transport", "bootstrap",
                       error.detail or error.reason) from error
    if done.returncode != 0:
        raise _Refusal("unknown", "transient_transport", "bootstrap",
                       done.stderr.strip() or f"exit {done.returncode}")


def _invoke(parameters: dict[str, Any], deadline: float) -> dict[str, Any]:
    if os.getuid() == 0:
        raise _rejected("authorization_denied", "authority", "refusing to activate as uid 0")
    candidate, config = parameters["candidate"], parameters["config"]
    label = parameters["target"]["label"]
    root = _checkout_root(candidate["commit"], deadline)
    program = shutil.which(config["program"])
    if program is None:
        raise _rejected("precondition_failed", "program", f"{config['program']} is not on PATH")
    plist, service = _plist_path(label), f"{_domain()}/{label}"
    _check_plist_path(plist)
    loaded = _loaded(label, plist, deadline)
    if loaded:
        _bootout(service, deadline)
    try:
        _write_plist(plist, _render(label, program, root, config, candidate))
    except (OSError, ValueError, TypeError, OverflowError) as error:
        if loaded:
            raise _Refusal("unknown", "transient_transport", "plist write", str(error)) from error
        raise _rejected("provider_unavailable", "plist write", str(error)) from error
    _bootstrap(plist, deadline)
    return {"result": "accepted", "error_class": None, "reference": service}


def invoke(request: Any) -> dict[str, Any]:
    """The `InvokeResult` of one `activate` request: `{result, error_class, reference}`.

    Never raises. A refusal before the bootout, or before the plist write when nothing was
    loaded, leaves the host as it was (issue 547 D15).
    """
    deadline = time.monotonic() + INVOKE_BUDGET_SECONDS
    try:
        return _invoke(_invoke_shape(request), deadline)
    except _Refusal as refusal:
        return refusal.answer
