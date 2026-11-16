"""A manager's permission mode, chosen per project from its production rules (#1151).

`read(project_id, root)` returns a `Permission(mode, reason)`: `BYPASS` only when nothing the
manager runs could reach production unguarded, else `AUTO`. The rule (ADR-project-contract-007
declares the three production statuses, ADR-guard-011 D3 says a loaded row's `production` member
is enforced without the row check):

- the project's resolved contract declares `production.status == "none"`: BYPASS, "no production";
  the policy file is not read;
- status `"declared"` and the guard's compiled policy, loaded whole, holds a row whose
  `evidence.project_id` is the project's and which carries a `production` member: BYPASS,
  "production rules in place";
- status `"declared"` and the policy loads but holds no such row: AUTO, "production rules
  declared but not in the guard's policy";
- status `"declared"` and the policy cannot be loaded: AUTO, "the guard's policy cannot be read";
  the guard drops a whole file for any malformed row, the matching row or an unrelated one, so
  such a file never yields bypass;
- any other status (`"not_declared"` included): AUTO, "no production rules declared", the policy
  file unread;
- a contract that does not resolve, or a snapshot without a production status: AUTO, "the
  project's contract does not resolve".

The policy file is validated exactly as the guard's loader (`load_compiled_policy` in
`lifecycle_guard.py`) validates it: `policy_rows` mirrors it step for step and returns the rows
where the guard loads the file, else None. The console cannot import the standalone guard, so
`tests/test_console_permission.py` pins the parity (constants and a table of documents). Any
other exception from `resolve` propagates; the service wraps it.

`Permission.text` is the one-line `"<bypass|auto>: <reason>"` the page shows and `payload()` /
`from_payload` carry the mode through the event log. `FALLBACK` is the mode logged when it could
not be read at all.
"""
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from agent_tools.project_contract import agent_platform, resolve_project

BYPASS = "bypassPermissions"
AUTO = "auto"

NO_PRODUCTION = "no production"
RULES_IN_PLACE = "production rules in place"
NOT_DECLARED = "no production rules declared"
NOT_ENFORCED = "production rules declared but not in the guard's policy"
POLICY_UNREADABLE = "the guard's policy cannot be read"
UNRESOLVED = "the project's contract does not resolve"
UNREADABLE = "the production rules could not be read"

# The guard's loader constants (`lifecycle_guard.py`), same names and values; the parity test
# pins them.
COMPILED_POLICY_KEYS = frozenset({"derived_repositories", "derivation"})
DERIVED_ROW_KEYS = frozenset(
    {"default_branch", "integration_branch", "required_checks", "evidence"}
)
DERIVED_ROW_OPTIONAL_KEYS = frozenset({"production"})
PRODUCTION_KEYS = frozenset({"changes", "read_only", "release_profile"})
PRODUCTION_OPTIONAL_KEYS = frozenset({"key_files", "mcp_tools"})
MCP_TOOL_NAME = re.compile(r"mcp__[A-Za-z0-9_-]+__[A-Za-z0-9_-]+")
PRODUCTION_COMMAND_KEYS = frozenset({"id", "argv"})
POLICY_MAX_BYTES = 1 << 20
SLUG_PATTERN = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+")
REF_NAME_PATTERN = re.compile(r"[A-Za-z0-9._/-]+")


@dataclass(frozen=True)
class Permission:
    mode: str
    reason: str

    @property
    def text(self) -> str:
        return f"{'bypass' if self.mode == BYPASS else 'auto'}: {self.reason}"

    def payload(self) -> dict:
        return {"mode": self.mode, "reason": self.reason}


FALLBACK = Permission(AUTO, UNREADABLE)


def from_payload(value: object) -> Permission | None:
    """The `Permission` a logged payload carries, or None for anything malformed."""
    if (
        isinstance(value, dict)
        and set(value) == {"mode", "reason"}
        and value["mode"] in (BYPASS, AUTO)
        and isinstance(value["reason"], str)
        and value["reason"]
    ):
        return Permission(value["mode"], value["reason"])
    return None


def policy_file() -> Path:
    return agent_platform.state_root() / "guard" / "policy.json"


def _read_bytes(path):
    """The bytes of a regular file of at most POLICY_MAX_BYTES, else None (`_read_policy_bytes`)."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOCTTY)
    except OSError:
        return None
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode) or status.st_size > POLICY_MAX_BYTES:
            return None
        chunks = []
        size = 0
        while size <= POLICY_MAX_BYTES:
            chunk = os.read(descriptor, POLICY_MAX_BYTES + 1 - size)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        if size > POLICY_MAX_BYTES:
            return None
        return b"".join(chunks)
    except OSError:
        return None
    finally:
        os.close(descriptor)


def _load_object(path, keys):
    """The JSON object at `path` with exactly `keys`, else None (`_load_json_object`)."""
    data = _read_bytes(path)
    if data is None:
        return None
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return None
    if not isinstance(document, dict) or set(document) != keys:
        return None
    return document


def _production_ok(production) -> bool:
    """True for a well-formed row `production` value (`production_problem` is None)."""
    if not isinstance(production, dict) or not (
        PRODUCTION_KEYS <= set(production) <= PRODUCTION_KEYS | PRODUCTION_OPTIONAL_KEYS
    ):
        return False
    if "key_files" in production:
        globs = production["key_files"]
        if not isinstance(globs, list) or not all(isinstance(glob, str) and glob for glob in globs):
            return False
    if "mcp_tools" in production:
        names = production["mcp_tools"]
        if not isinstance(names, list) or not all(
            isinstance(name, str) and MCP_TOOL_NAME.fullmatch(name) for name in names
        ):
            return False
    for member in ("changes", "read_only"):
        commands = production[member]
        if not isinstance(commands, list):
            return False
        for command in commands:
            if not isinstance(command, dict) or set(command) != PRODUCTION_COMMAND_KEYS:
                return False
            if not isinstance(command["id"], str) or not command["id"]:
                return False
            argv = command["argv"]
            if (
                not isinstance(argv, list)
                or not argv
                or not all(isinstance(word, str) and word for word in argv)
            ):
                return False
    profile = production["release_profile"]
    return isinstance(profile, str) and bool(profile)


def policy_rows(path: Path) -> dict | None:
    """The `derived_repositories` mapping when the guard's `load_compiled_policy` loads `path`, else None."""
    document = _load_object(path, COMPILED_POLICY_KEYS)
    if document is None:
        return None
    derived = document["derived_repositories"]
    if not isinstance(derived, dict):
        return None
    for repository, value in derived.items():
        if not isinstance(repository, str) or SLUG_PATTERN.fullmatch(repository) is None:
            return None
        if (
            not isinstance(value, dict)
            or not DERIVED_ROW_KEYS <= set(value) <= DERIVED_ROW_KEYS | DERIVED_ROW_OPTIONAL_KEYS
        ):
            return None
        for key in ("default_branch", "integration_branch"):
            branch = value[key]
            if not isinstance(branch, str) or REF_NAME_PATTERN.fullmatch(branch) is None:
                return None
        checks = value["required_checks"]
        if (
            not isinstance(checks, list)
            or not all(isinstance(check, str) and check for check in checks)
            or len(set(checks)) != len(checks)
        ):
            return None
        if not isinstance(value["evidence"], dict):
            return None
        if "production" in value and not _production_ok(value["production"]):
            return None
    if document["derivation"] is not None and not isinstance(document["derivation"], dict):
        return None
    return dict(derived)


def read(project_id: str, root: str, *, resolve=resolve_project.resolve,
         policy_path: Path | None = None) -> Permission:
    """The permission mode a manager of `project_id`, whose checkout is `root`, runs under."""
    try:
        snapshot = resolve(root)
    except resolve_project.ContractError:
        return Permission(AUTO, UNRESOLVED)
    production = snapshot.get("production") if isinstance(snapshot, dict) else None
    status = production.get("status") if isinstance(production, dict) else None
    if not isinstance(status, str):
        return Permission(AUTO, UNRESOLVED)
    if status == "none":
        return Permission(BYPASS, NO_PRODUCTION)
    if status != "declared":
        return Permission(AUTO, NOT_DECLARED)
    rows = policy_rows(policy_path or policy_file())
    if rows is None:
        return Permission(AUTO, POLICY_UNREADABLE)
    for value in rows.values():
        if value["evidence"].get("project_id") == project_id and "production" in value:
            return Permission(BYPASS, RULES_IN_PLACE)
    return Permission(AUTO, NOT_ENFORCED)
