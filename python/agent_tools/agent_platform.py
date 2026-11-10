"""Shared platform facts for the agent binaries: the installed manifest,
the user-scope state root, the fleet registry, and the atomic writer.

This module is imported, never run: it has no `main`, no argparse, and no
adoption or resolver logic. It exists so that every binary reads one manifest
through one loader and writes through one atomic writer (D37) — `adopt-project`
must not import `agent_tools.resolve_project` (D26), and a second copy of either helper
is the duplication the plan forbids.

A `deprecations` entry of `platform-manifest.json` is closed on exactly `id`,
`kind`, `subject`, `since`, `successor` and `migration` (issue 580). `id`,
`subject`, `successor` and `migration` are non-empty strings and `id` is
distinct across entries; `kind` is `project_file` (the `subject` is a
repository-relative POSIX path a project may hold: not absolute, no backslash,
no empty, `.` or `..` segment), `platform_behavior` (the `subject` names shipped
platform behaviour; nothing per project) or `project_schema` (the `subject` is
a decimal project schema version: digits only, no sign, no leading zero;
anything else is `subject_not_schema_version`); `since` is strict SemVer
`MAJOR.MINOR.0` with `MINOR >= 1`, because deprecation begins only in a minor.
A violation refuses the manifest as `resolver_failure` with the repair id
`platform.manifest.deprecations.<not_array|not_object|member_missing|member_unexpected|not_string|duplicate_id|kind_unknown|since_not_minor|subject_not_relative_path|subject_not_schema_version>`.
That each `since` is at most `platform_version` and shares its major is pinned
on the committed file by `CommittedManifestTest`, not by the validator. A
`removals` entry is closed on the same six members under the same member rules,
with the repair ids `platform.manifest.removals.<...>` of the list above, and a
removal `id` that is also a deprecation `id` is
`platform.manifest.removals.still_deprecated` at `/removals/<n>/id`. A manifest
that removes nothing keeps `removals: []`.

The manifest is authored data installed at exactly `$HOME/.agents/share/
platform-manifest.json` (R1.1, D1). There is no default, no fallback path and
no discovery ladder: a missing, unreadable, malformed or schema-invalid
manifest is a platform installation defect and is refused loudly, never
replaced by an assumed version (R1.3).
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Iterator

from agent_tools.system import semver


# R1.2: the manifest's members, exactly. An absent or unexpected member is a
# refusal, not an implied value.
MANIFEST_MEMBERS = (
    "schema_version",
    "platform_version",
    "project_schema_versions",
    "resolved_schema_version",
    "migrations",
    "deprecations",
    "removals",
)

# D36: a `migrations` entry is closed on exactly these three members.
MIGRATION_MEMBERS = ("id", "from_schema", "to_schema")

# Issue 580 D1: a `deprecations` entry is closed on exactly these six members,
# and its `kind` is one of three. A `project_file` subject is a path a project
# may hold, so a warning can look for it; a `platform_behavior` subject is
# free text naming shipped behaviour. A `removals` entry has the same six
# members and the same member rules (issue 579 P2).
DEPRECATION_MEMBERS = ("id", "kind", "subject", "since", "successor",
                       "migration")
DEPRECATION_KINDS = ("project_file", "platform_behavior", "project_schema")

# The fleet registry's members, and D18's closed entry: a stable identity and
# a location, plus one optional record of how a registration reached its
# branch (`branch_override`, issue 363 D3). No version stamp and no cached
# verdict — the preflight re-reads each project's live contract, so a stored
# one would be stale by construction — and no reader decides anything from
# the optional member.
REGISTRY_MEMBERS = ("schema_version", "projects")
REGISTRY_ENTRY_MEMBERS = ("project_id", "root")
REGISTRY_ENTRY_OPTIONAL_MEMBERS = ("branch_override",)
# The optional record is closed on these members; `reason` is one of the
# reasons below, and the validator's membership test is the only place its
# value is read.
BRANCH_OVERRIDE_MEMBERS = ("branch", "default_branch", "reason")
BRANCH_OVERRIDE_REASONS = ("default_contract_unresolved",)
REGISTRY_SCHEMA_VERSION = 1

# The closed set of compatibility reasons, kept separate from the resolver's
# capability `REASON_CODES` (D7). `interval_verdict` names the first two;
# `project_schema_unsupported` belongs to the contract's schema check; and
# `project_identity_mismatch` belongs to the fleet view alone — a registry
# entry names an identity and a location, plus at most the optional record of
# how its registration reached its branch, and carries no version fact or
# verdict (D18), so the preflight has to say when the live contract at that
# location no longer declares the identity the registry recorded, rather than
# reporting the stale one as compatible.
SCHEMA_REASON_CODES = (
    "platform_too_old",
    "platform_too_new",
    "project_schema_unsupported",
    "project_identity_mismatch",
)


class PlatformManifestError(Exception):
    """One refusal from a platform data-file loader — the manifest or the fleet
    registry: a stable repair id and an ordered, non-empty violation list, each
    violation `{pointer, message}` (R1.3)."""

    def __init__(self, repair_id: str, violations: list[dict]) -> None:
        super().__init__(repair_id)
        self.repair_id = repair_id
        self.violations = violations


def interval_verdict(platform_version: str, min_inclusive: str,
                     max_exclusive: str) -> str | None:
    """None when `min <= version < max`, else the failing `SCHEMA_REASON_CODES`.

    Shape checking is the caller's job: all three arguments are assumed to
    parse, so this answers the range question and nothing else.
    """
    if semver.compare_semver(platform_version, min_inclusive) < 0:
        return "platform_too_old"
    if semver.compare_semver(platform_version, max_exclusive) >= 0:
        return "platform_too_new"
    return None


# --------------------------------------------------------------------------
# Manifest loading and validation
#
# Violations are collected in one pass and published together, ordered
# byte-wise ascending by pointer; the refusal's repair id is the one belonging
# to the first violation in that order. A collected violation carries a third
# `repair_id` key that the published list never shows.
# --------------------------------------------------------------------------


def _violation(pointer: str, message: str, repair_id: str) -> dict:
    return {"pointer": pointer, "message": message, "repair_id": repair_id}


def _refuse(violations: list[dict]) -> PlatformManifestError:
    ordered = sorted(violations, key=lambda item: item["pointer"])
    return PlatformManifestError(
        ordered[0]["repair_id"],
        [{"pointer": v["pointer"], "message": v["message"]} for v in ordered],
    )


def _is_positive_int(value: object) -> bool:
    # `bool` is a subclass of `int`, so `True` would otherwise pass as 1.
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _check_positive_int(value: object, pointer: str, section: str,
                        violations: list[dict]) -> bool:
    if _is_positive_int(value):
        return True
    violations.append(_violation(
        pointer, "must be a positive integer",
        f"platform.manifest.{section}.not_positive_int"))
    return False


def _check_list(value: object, pointer: str, section: str,
                violations: list[dict]) -> bool:
    if isinstance(value, list):
        return True
    violations.append(_violation(
        pointer, "must be an array", f"platform.manifest.{section}.not_array"))
    return False


def _check_exact_members(value: dict, pointer: str, expected: tuple[str, ...],
                         section: str, violations: list[dict]) -> None:
    for name in expected:
        if name not in value:
            violations.append(_violation(
                f"{pointer}/{name}", "required member is absent",
                f"platform.manifest.{section}.member_missing"))
    for name in sorted(value):
        if name not in expected:
            violations.append(_violation(
                f"{pointer}/{name}", "member is not part of this schema",
                f"platform.manifest.{section}.member_unexpected"))


def _validate_project_schema_versions(source: dict,
                                      violations: list[dict]) -> None:
    if "project_schema_versions" not in source:
        return
    values = source["project_schema_versions"]
    if not _check_list(values, "/project_schema_versions",
                       "project_schema_versions", violations):
        return
    if not values:
        violations.append(_violation(
            "/project_schema_versions", "must declare at least one version",
            "platform.manifest.project_schema_versions.empty"))
        return
    well_typed = True
    for index, value in enumerate(values):
        if not _check_positive_int(
                value, f"/project_schema_versions/{index}",
                "project_schema_versions", violations):
            well_typed = False
    if not well_typed:
        return
    if len(set(values)) != len(values):
        violations.append(_violation(
            "/project_schema_versions", "must not repeat a version",
            "platform.manifest.project_schema_versions.duplicate"))
    elif values != sorted(values):
        violations.append(_violation(
            "/project_schema_versions", "must be in ascending order",
            "platform.manifest.project_schema_versions.not_ascending"))


def _validate_migration_entry(entry: object, pointer: str,
                              violations: list[dict]) -> tuple[object, object]:
    """Validate one closed `{id, from_schema, to_schema}` record (D36).

    Returns the entry's `id` and `from_schema` when each is well typed and
    None in its place otherwise, so the caller can check cross-entry
    uniqueness and ordering without re-deriving what was already rejected.
    """
    if not isinstance(entry, dict):
        violations.append(_violation(
            pointer, "must be an object",
            "platform.manifest.migrations.not_object"))
        return (None, None)
    _check_exact_members(entry, pointer, MIGRATION_MEMBERS, "migrations",
                         violations)
    identifier: object = None
    if "id" in entry:
        if isinstance(entry["id"], str) and entry["id"]:
            identifier = entry["id"]
        else:
            violations.append(_violation(
                f"{pointer}/id", "must be a non-empty string",
                "platform.manifest.migrations.not_string"))
    from_schema: object = None
    if "from_schema" in entry and _check_positive_int(
            entry["from_schema"], f"{pointer}/from_schema", "migrations",
            violations):
        from_schema = entry["from_schema"]
    to_schema: object = None
    if "to_schema" in entry and _check_positive_int(
            entry["to_schema"], f"{pointer}/to_schema", "migrations",
            violations):
        to_schema = entry["to_schema"]
    if (from_schema is not None and to_schema is not None
            and to_schema != from_schema + 1):
        violations.append(_violation(
            f"{pointer}/to_schema", "must be from_schema plus one",
            "platform.manifest.migrations.not_single_step"))
    return (identifier, from_schema)


def _validate_migrations(source: dict, violations: list[dict]) -> None:
    if "migrations" not in source:
        return
    entries = source["migrations"]
    if not _check_list(entries, "/migrations", "migrations", violations):
        return
    identifiers: list[object] = []
    from_schemas: list[object] = []
    for index, entry in enumerate(entries):
        identifier, from_schema = _validate_migration_entry(
            entry, f"/migrations/{index}", violations)
        if identifier is not None:
            identifiers.append(identifier)
        if from_schema is not None:
            from_schemas.append(from_schema)
    if len(identifiers) == len(entries) and len(set(identifiers)) != len(identifiers):
        violations.append(_violation(
            "/migrations", "each entry must carry a distinct id",
            "platform.manifest.migrations.duplicate_id"))
    if len(from_schemas) != len(entries):
        return
    if len(set(from_schemas)) != len(from_schemas):
        violations.append(_violation(
            "/migrations", "each entry must carry a distinct from_schema",
            "platform.manifest.migrations.duplicate_from_schema"))
    elif from_schemas != sorted(from_schemas):
        violations.append(_violation(
            "/migrations", "entries must be in ascending from_schema order",
            "platform.manifest.migrations.not_ascending"))


def _validate_deprecation_entry(entry: object, pointer: str,
                                violations: list[dict],
                                section: str = "deprecations") -> object:
    """Validate one closed deprecation record (issue 580 D1).

    A `removals` entry is the same record (issue 579 P2): `section` names the
    manifest member the entry came from and prefixes its repair ids.

    Returns the entry's `id` when it is a non-empty string, else None, so the
    caller can check uniqueness only over well-typed ids.
    """
    if not isinstance(entry, dict):
        violations.append(_violation(
            pointer, "must be an object",
            f"platform.manifest.{section}.not_object"))
        return None
    _check_exact_members(entry, pointer, DEPRECATION_MEMBERS, section,
                         violations)
    for name in ("id", "subject", "successor", "migration"):
        if (name == "subject" and entry.get("kind") == "project_schema"
                and entry.get(name) == ""):
            continue  # judged below as a schema version, not as a string
        if name in entry and not (isinstance(entry[name], str) and entry[name]):
            violations.append(_violation(
                f"{pointer}/{name}", "must be a non-empty string",
                f"platform.manifest.{section}.not_string"))
    kind = entry.get("kind")
    if "kind" in entry and not (isinstance(kind, str)
                                and kind in DEPRECATION_KINDS):
        violations.append(_violation(
            f"{pointer}/kind",
            "must be one of: " + ", ".join(DEPRECATION_KINDS),
            f"platform.manifest.{section}.kind_unknown"))
    if "since" in entry:
        parsed = semver.parse_semver(entry["since"])
        if parsed is None or parsed[2] != 0 or parsed[1] < 1:
            violations.append(_violation(
                f"{pointer}/since",
                "must be a minor release: MAJOR.MINOR.0 with MINOR at least 1",
                f"platform.manifest.{section}.since_not_minor"))
    subject = entry.get("subject")
    if kind == "project_file" and isinstance(subject, str) and subject:
        if (subject.startswith("/") or "\\" in subject or "\0" in subject
                or any(segment in ("", ".", "..")
                       for segment in subject.split("/"))):
            violations.append(_violation(
                f"{pointer}/subject",
                "must be a repository-relative POSIX path without empty, "
                "'.' or '..' segments",
                f"platform.manifest.{section}.subject_not_relative_path"))
    if kind == "project_schema" and isinstance(subject, str):
        if not re.fullmatch(r"(?:0|[1-9][0-9]*)", subject):
            violations.append(_violation(
                f"{pointer}/subject",
                "must be a decimal project schema version: digits only, "
                "no sign and no leading zero",
                f"platform.manifest.{section}.subject_not_schema_version"))
    identifier = entry.get("id")
    return identifier if isinstance(identifier, str) and identifier else None


def _validate_entries(source: dict, section: str,
                      violations: list[dict]) -> None:
    """Validate the `section` array of closed deprecation records."""
    if section not in source:
        return
    entries = source[section]
    if not _check_list(entries, f"/{section}", section, violations):
        return
    identifiers: list[object] = []
    for index, entry in enumerate(entries):
        identifier = _validate_deprecation_entry(
            entry, f"/{section}/{index}", violations, section)
        if identifier is not None:
            identifiers.append(identifier)
    if (len(identifiers) == len(entries)
            and len(set(identifiers)) != len(identifiers)):
        violations.append(_violation(
            f"/{section}", "each entry must carry a distinct id",
            f"platform.manifest.{section}.duplicate_id"))


def _validate_removals(source: dict, violations: list[dict]) -> None:
    """A removal has a deprecation's shape and is never also a deprecation."""
    _validate_entries(source, "removals", violations)
    removals = source.get("removals")
    deprecations = source.get("deprecations")
    if not isinstance(removals, list) or not isinstance(deprecations, list):
        return
    deprecated = {entry["id"] for entry in deprecations
                  if isinstance(entry, dict) and isinstance(entry.get("id"), str)}
    for index, entry in enumerate(removals):
        identifier = entry.get("id") if isinstance(entry, dict) else None
        if isinstance(identifier, str) and identifier in deprecated:
            violations.append(_violation(
                f"/removals/{index}/id",
                "a removed id must not also be a deprecation id",
                "platform.manifest.removals.still_deprecated"))


def validate_manifest(source: object) -> list[dict]:
    """Every violation in `source`, collected in one pass, never just the first."""
    if not isinstance(source, dict):
        return [_violation("", "must be a JSON object",
                           "platform.manifest.not_object")]
    violations: list[dict] = []
    _check_exact_members(source, "", MANIFEST_MEMBERS, "root", violations)
    if "schema_version" in source:
        _check_positive_int(source["schema_version"], "/schema_version",
                            "schema_version", violations)
    if "platform_version" in source and semver.parse_semver(
            source["platform_version"]) is None:
        violations.append(_violation(
            "/platform_version",
            "must be a strict MAJOR.MINOR.PATCH SemVer string",
            "platform.manifest.platform_version.not_semver"))
    _validate_project_schema_versions(source, violations)
    if "resolved_schema_version" in source:
        _check_positive_int(source["resolved_schema_version"],
                            "/resolved_schema_version",
                            "resolved_schema_version", violations)
    _validate_migrations(source, violations)
    _validate_entries(source, "deprecations", violations)
    _validate_removals(source, violations)
    return violations


def manifest_path() -> Path:
    """The one installed location (R1.1). No fallback, no discovery ladder."""
    return Path(os.environ["HOME"]) / ".agents" / "share" / "platform-manifest.json"


class _NonFiniteNumber(ValueError):
    """A bare NaN, Infinity or -Infinity token met while decoding."""


def _reject_non_finite(token: str) -> object:
    """`parse_constant` for `json.loads`: the three bare tokens are refused.

    Python's decoder accepts them as an extension, RFC 8259 has none, and a
    caller that republishes a manifest member verbatim would otherwise hand
    one to an emit guard (`allow_nan=False`) only after part of its response
    was already written (#147 D12). It stays local rather than composing
    `agent_tools.canonical.reject_nonfinite_literal` because its typed error
    carries this module's refusal vocabulary (#177 D16).
    """
    raise _NonFiniteNumber(token)


def _finite_float(literal: str) -> float:
    """`parse_float` for `json.loads`: a literal that overflows is refused.

    A well-formed number such as `1e999` needs no bare token to decode to
    infinity, so `_reject_non_finite` alone would let it reach the same
    emit guard mid-response. Refusing it here keeps the loader's promise
    that nothing it returns is a float JSON cannot carry.
    """
    value = float(literal)
    if not math.isfinite(value):
        raise _NonFiniteNumber(literal)
    return value


def load_manifest(path: Path | None = None) -> tuple[dict, Path]:
    """The installed manifest and the absolute resolved path it came from.

    The second member is `Path.resolve()` of the file actually loaded, which
    under Home Manager is the content-addressed store path — the deployment
    identity, observed rather than authored, so it cannot lie (D2, R1.4).

    An unset or empty `HOME` names no installed manifest, so it refuses as
    `platform.manifest.missing` before any filesystem read (#177 D4).

    `path` names another manifest to load by the same rules (issue 579 P7):
    it replaces the installed location and needs no `HOME`, and a missing or
    invalid one refuses exactly as a broken installed manifest does.
    """
    if path is None:
        if not os.environ.get("HOME"):
            raise _refuse([_violation(
                "", "the installed platform manifest was not found",
                "platform.manifest.missing")])
        path = manifest_path()
    try:
        resolved = path.resolve(strict=True)
        raw = resolved.read_bytes()
    except FileNotFoundError:
        raise _refuse([_violation(
            "", "the installed platform manifest was not found",
            "platform.manifest.missing")]) from None
    except (OSError, RuntimeError):
        raise _refuse([_violation(
            "", "the installed platform manifest could not be read",
            "platform.manifest.unreadable")]) from None
    try:
        source = json.loads(raw, parse_constant=_reject_non_finite,
                            parse_float=_finite_float)
    except (json.JSONDecodeError, UnicodeDecodeError, _NonFiniteNumber):
        raise _refuse([_violation(
            "", "the installed platform manifest is not valid JSON",
            "platform.manifest.parse")]) from None
    violations = validate_manifest(source)
    if violations:
        raise _refuse(violations)
    return source, resolved


# --------------------------------------------------------------------------
# User-scope state
# --------------------------------------------------------------------------


def state_root() -> Path:
    """The one user-scope state directory the agent binaries write beneath."""
    return Path(os.environ["HOME"]) / ".agents" / "state"


def ensure_directory(path: Path) -> Path:
    """Create `path` and its parents if absent, and return it."""
    path.mkdir(mode=0o755, parents=True, exist_ok=True)
    return path


# --------------------------------------------------------------------------
# The fleet registry
#
# Read by both binaries; written only from `adopt-project verify --register`,
# through the locked transaction below. The registry is platform-written
# state, so every failure to read one that exists is an installation defect
# published as `resolver_failure` — an absent file is the one benign case,
# because nothing has been registered yet.
# --------------------------------------------------------------------------


def _registry_violation(pointer: str, message: str, code: str) -> dict:
    return _violation(pointer, message, f"platform.registry.{code}")


def registry_path() -> Path:
    """The one fleet registry location. No fallback, no discovery ladder."""
    return state_root() / "fleet" / "registry.json"


def _branch_override_violations(pointer: str, override: object) -> list[dict]:
    """Every violation of one entry's `branch_override`, at `pointer`."""
    if not isinstance(override, dict):
        return [_registry_violation(
            pointer, "must be an object",
            "projects.branch_override.not_object")]
    violations: list[dict] = []
    for name in BRANCH_OVERRIDE_MEMBERS:
        if name not in override:
            violations.append(_registry_violation(
                f"{pointer}/{name}", "required member is absent",
                "projects.branch_override.member_missing"))
        elif not (isinstance(override[name], str) and override[name]):
            violations.append(_registry_violation(
                f"{pointer}/{name}", "must be a non-empty string",
                "projects.branch_override.not_string"))
        elif name == "reason" and override[name] not in BRANCH_OVERRIDE_REASONS:
            violations.append(_registry_violation(
                f"{pointer}/{name}", "is not a known override reason",
                "projects.branch_override.reason_unknown"))
    for name in sorted(override):
        if name not in BRANCH_OVERRIDE_MEMBERS:
            violations.append(_registry_violation(
                f"{pointer}/{name}", "member is not part of this schema",
                "projects.branch_override.member_unexpected"))
    return violations


def validate_registry(source: object) -> list[dict]:
    """Every violation of the registry's shape, collected in one pass.

    The entry shape is closed on `REGISTRY_ENTRY_MEMBERS` plus the one
    optional `REGISTRY_ENTRY_OPTIONAL_MEMBERS` member in both directions
    (D18): an absent required member and an extra one are equally violations,
    so a cached verdict smuggled into an entry is refused rather than ignored.
    The optional `branch_override` is itself closed on
    `BRANCH_OVERRIDE_MEMBERS`.
    """
    if not isinstance(source, dict):
        return [_registry_violation("", "must be a JSON object", "not_object")]
    violations: list[dict] = []
    for name in REGISTRY_MEMBERS:
        if name not in source:
            violations.append(_registry_violation(
                f"/{name}", "required member is absent", "member_missing"))
    for name in sorted(source):
        if name not in REGISTRY_MEMBERS:
            violations.append(_registry_violation(
                f"/{name}", "member is not part of this schema",
                "member_unexpected"))
    if "schema_version" in source and not _is_positive_int(
            source["schema_version"]):
        violations.append(_registry_violation(
            "/schema_version", "must be a positive integer",
            "schema_version.not_positive_int"))
    if "projects" not in source:
        return violations
    entries = source["projects"]
    if not isinstance(entries, list):
        violations.append(_registry_violation(
            "/projects", "must be an array", "projects.not_array"))
        return violations
    for index, entry in enumerate(entries):
        pointer = f"/projects/{index}"
        if not isinstance(entry, dict):
            violations.append(_registry_violation(
                pointer, "must be an object", "projects.not_object"))
            continue
        for name in REGISTRY_ENTRY_MEMBERS:
            if name not in entry:
                violations.append(_registry_violation(
                    f"{pointer}/{name}", "required member is absent",
                    "projects.member_missing"))
            elif not (isinstance(entry[name], str) and entry[name]):
                violations.append(_registry_violation(
                    f"{pointer}/{name}", "must be a non-empty string",
                    "projects.not_string"))
        for name in sorted(entry):
            if name not in (REGISTRY_ENTRY_MEMBERS
                            + REGISTRY_ENTRY_OPTIONAL_MEMBERS):
                violations.append(_registry_violation(
                    f"{pointer}/{name}", "member is not part of this schema",
                    "projects.member_unexpected"))
        if "branch_override" in entry:
            violations.extend(_branch_override_violations(
                f"{pointer}/branch_override", entry["branch_override"]))
    return violations


def read_registry() -> list[dict]:
    """The registered fleet entries, in the order the file declares them.

    An absent registry is the empty fleet, not an error: nothing has been
    registered yet, and creating the file to find that out would make a
    read-only caller a writer. A registry that exists but will not read, will
    not parse, or does not match the schema raises instead — reporting an
    empty fleet for a corrupt file would hide exactly the projects an operator
    registered.
    """
    try:
        raw = registry_path().read_bytes()
    except FileNotFoundError:
        return []
    except (OSError, RuntimeError):
        raise _refuse([_registry_violation(
            "", "the fleet registry could not be read", "unreadable")]) from None
    try:
        source = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise _refuse([_registry_violation(
            "", "the fleet registry is not valid JSON", "parse")]) from None
    violations = validate_registry(source)
    if violations:
        raise _refuse(violations)
    return list(source["projects"])


def write_registry(entries: list[dict]) -> None:
    """Replace the registry with `entries`, atomically and in one shape.

    The two cross-entry invariants the reader deliberately leaves alone are
    established here, because a writer is the only place they can be: an entry
    is reduced to `REGISTRY_ENTRY_MEMBERS` plus its `branch_override` when it
    has one (D18) and `projects` is sorted by `project_id`, so a caller cannot
    persist a stored order or any other extra member by handing one in. A repeated `project_id` refuses rather
    than being deduplicated — which of the two roots to drop is not this
    function's decision to make.
    """
    projects = sorted(
        ({**{name: entry[name] for name in REGISTRY_ENTRY_MEMBERS},
          **{name: entry[name] for name in REGISTRY_ENTRY_OPTIONAL_MEMBERS
             if name in entry}}
         for entry in entries),
        key=lambda entry: entry["project_id"])
    identifiers = [entry["project_id"] for entry in projects]
    if len(set(identifiers)) != len(identifiers):
        raise _refuse([_registry_violation(
            "/projects", "must not register one project id twice",
            "projects.duplicate_id")])
    document = {"schema_version": REGISTRY_SCHEMA_VERSION,
                "projects": projects}
    violations = validate_registry(document)
    if violations:
        raise _refuse(violations)
    ensure_directory(registry_path().parent)
    write_atomically(registry_path(), json.dumps(
        document, sort_keys=True, separators=(",", ":"),
        allow_nan=False).encode("utf-8") + b"\n")


@contextlib.contextmanager
def registry_transaction() -> Iterator[list[dict]]:
    """Hold the registry lock, and yield the entries reread underneath it.

    Registration is a transaction rather than a read-then-write: the entries
    yielded here are read *inside* the exclusive lock and the lock is released
    only once the caller's `write_registry` has returned, so two concurrent
    registrations serialize instead of one overwriting the other's file. The
    lock file is beside the registry and is never deleted — unlinking it would
    let a second process create and lock a different inode.

    The caller does the duplicate check inside the `with` and nowhere else.
    """
    lock_path = ensure_directory(registry_path().parent) / "registry.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield read_registry()
    finally:
        os.close(descriptor)


# --------------------------------------------------------------------------
# Atomic writing
#
# D37: this module is the single owner of both helpers below. `adopt-project`
# may not import `agent_tools.resolve_project` (D26) and both binaries must write
# atomically, so a second copy anywhere is a defect.
# --------------------------------------------------------------------------


def destination_mode(target: Path) -> int:
    """The permission bits the replaced target must end up holding.

    `tempfile` creates at 0600 and `os.replace` carries the temporary file's
    mode onto the destination, so an unadjusted atomic write silently narrows
    a file other uids have to read — invisibly, since git records no bit but
    the executable one. An existing target therefore keeps exactly the bits it
    already had, and a new one gets what a plain `open()` would have given it:
    0666 with the process umask applied. Reading the umask means briefly
    setting it, which is safe here because the resolver is single-threaded and
    forks nothing.
    """
    try:
        return os.stat(target).st_mode & 0o7777
    except OSError:
        umask = os.umask(0)
        os.umask(umask)
        return 0o666 & ~umask


def write_atomically(target: Path, data: bytes) -> None:
    """Replace `target` with `data` in one step, never a partial file.

    The temporary file is named distinctively so an orphan left by a crashed
    process is recognizable and is caught by the repository's `.gitignore`
    rather than offered as an untracked file.

    A nested target is a safe path the validator accepts, so its parent may not
    exist yet; it is created here, because the temporary file is opened inside
    that directory and a missing one would surface as `resolver_failure`
    instead of a written projection.
    """
    mode = destination_mode(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    pending: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
                dir=str(target.parent),
                prefix=".resolve-project.",
                suffix=".tmp",
                delete=False) as handle:
            pending = Path(handle.name)
            handle.write(data)
            handle.flush()
        os.chmod(pending, mode)
        os.replace(pending, target)
        pending = None
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)
