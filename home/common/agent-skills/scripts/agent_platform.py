"""Shared platform facts for the agent binaries: the installed manifest,
strict SemVer, the user-scope state root, the fleet registry, and the atomic
writer.

This module is imported, never run: it has no `main`, no argparse, and no
adoption or resolver logic. It exists so that every binary reads one manifest
through one loader and writes through one atomic writer (D37) — `adopt-project`
must not import `resolve-project.py` (D26), and a second copy of either helper
is the duplication the plan forbids.

The manifest is authored data installed at exactly `$HOME/.agents/share/
platform-manifest.json` (R1.1, D1). There is no default, no fallback path and
no discovery ladder: a missing, unreadable, malformed or schema-invalid
manifest is a platform installation defect and is refused loudly, never
replaced by an assumed version (R1.3).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile


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

# The fleet registry's members, and D18's closed entry: stable identity and
# location, and nothing else. No version stamp and no cached verdict — the
# preflight re-reads each project's live contract, so a stored one would be
# stale by construction.
REGISTRY_MEMBERS = ("schema_version", "projects")
REGISTRY_ENTRY_MEMBERS = ("project_id", "root")

# The closed set of schema-compatibility reasons, kept separate from the
# resolver's capability `REASON_CODES` (D7). `interval_verdict` names the first
# two; `project_schema_unsupported` belongs to the contract's schema check.
SCHEMA_REASON_CODES = (
    "platform_too_old",
    "platform_too_new",
    "project_schema_unsupported",
)

# D9: strict `MAJOR.MINOR.PATCH` only. No pre-release, no build metadata, no
# leading `v`, no leading zeros, no fourth component.
SEMVER_PATTERN = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


class PlatformManifestError(Exception):
    """One refusal from a platform data-file loader — the manifest or the fleet
    registry: a stable repair id and an ordered, non-empty violation list, each
    violation `{pointer, message}` (R1.3)."""

    def __init__(self, repair_id: str, violations: list[dict]) -> None:
        super().__init__(repair_id)
        self.repair_id = repair_id
        self.violations = violations


# --------------------------------------------------------------------------
# Strict SemVer
# --------------------------------------------------------------------------


def parse_semver(value: object) -> tuple[int, int, int] | None:
    """The `(major, minor, patch)` triple, or None when `value` is not strict.

    None is the whole vocabulary for "not a version" (D9): a pre-release or
    build-metadata suffix, a leading `v`, a fourth component and a leading zero
    all return it, so no caller can accept a looser spelling by accident.
    """
    if not isinstance(value, str):
        return None
    match = SEMVER_PATTERN.fullmatch(value)
    if match is None:
        return None
    major, minor, patch = match.groups()
    return (int(major), int(minor), int(patch))


def compare_semver(a: str, b: str) -> int:
    """-1, 0 or 1 by tuple comparison over the two parsed triples.

    Both arguments must already parse; an unparseable one is a programming
    error here, not an authored one, because shape validation is the caller's
    job and has already run.
    """
    left = parse_semver(a)
    right = parse_semver(b)
    if left is None or right is None:
        raise ValueError("compare_semver requires two strict SemVer strings")
    return (left > right) - (left < right)


def interval_verdict(platform_version: str, min_inclusive: str,
                     max_exclusive: str) -> str | None:
    """None when `min <= version < max`, else the failing `SCHEMA_REASON_CODES`.

    Shape checking is the caller's job: all three arguments are assumed to
    parse, so this answers the range question and nothing else.
    """
    if compare_semver(platform_version, min_inclusive) < 0:
        return "platform_too_old"
    if compare_semver(platform_version, max_exclusive) >= 0:
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
    if "platform_version" in source and parse_semver(
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
    # `deprecations` and `removals` are opaque at v1 (R1.2, D36): they are
    # validated as arrays and never read. Do not invent an entry shape for
    # them here — the manifest that declares one will declare it in the spec
    # first.
    for name in ("deprecations", "removals"):
        if name in source:
            _check_list(source[name], f"/{name}", name, violations)
    return violations


def manifest_path() -> Path:
    """The one installed location (R1.1). No fallback, no discovery ladder."""
    return Path(os.environ["HOME"]) / ".agents" / "share" / "platform-manifest.json"


def load_manifest() -> tuple[dict, Path]:
    """The installed manifest and the absolute resolved path it came from.

    The second member is `Path.resolve()` of the file actually loaded, which
    under Home Manager is the content-addressed store path — the deployment
    identity, observed rather than authored, so it cannot lie (D2, R1.4).
    """
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
        source = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
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
# Read here; written only by `adopt-project verify --register`. The registry
# is platform-written state, so every failure to read one that exists is an
# installation defect published as `resolver_failure` — an absent file is the
# one benign case, because nothing has been registered yet.
# --------------------------------------------------------------------------


def _registry_violation(pointer: str, message: str, code: str) -> dict:
    return _violation(pointer, message, f"platform.registry.{code}")


def registry_path() -> Path:
    """The one fleet registry location. No fallback, no discovery ladder."""
    return state_root() / "fleet" / "registry.json"


def validate_registry(source: object) -> list[dict]:
    """Every violation of the registry's shape, collected in one pass.

    The entry shape is closed on `REGISTRY_ENTRY_MEMBERS` in both directions
    (D18): an absent member and an extra one are equally violations, so a
    cached verdict smuggled into an entry is refused rather than ignored.
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
            if name not in REGISTRY_ENTRY_MEMBERS:
                violations.append(_registry_violation(
                    f"{pointer}/{name}", "member is not part of this schema",
                    "projects.member_unexpected"))
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


# --------------------------------------------------------------------------
# Atomic writing
#
# D37: this module is the single owner of both helpers below. `adopt-project`
# may not import `resolve-project.py` (D26) and both binaries must write
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
