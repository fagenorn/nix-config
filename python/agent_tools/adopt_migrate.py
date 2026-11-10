"""`adopt-project migrate`: execute one manifest migration on a checkout.

A manifest `migrations` entry names a single schema step. This module holds
the executors, keyed by the entry's id, and the transaction that applies one:
write the transformed contract, have the resolver child regenerate the
projections, have the resolver child judge the result, and restore every byte
if either refuses. The resolver is never imported (D26): `adopt_project` hands
in `run_resolver`, so validation and the projection writer both run in the
resolver of this process's own store environment.

`adopt-project migrate --migration ID [--repo-root R]` executes one manifest
`migrations` entry (issue 579). `MIGRATIONS` maps an id to a pure executor, and
an id the manifest lists without an executor, or an executor the manifest does
not list, refuses `adopt.migration.unknown`. The contract's `schema_version`
must equal the entry's `from_schema` (`adopt.migration.not_applicable`
otherwise, which is also what a second run over a migrated tree gets).
`bindings-deploy.retire` returns a deep copy of the contract with
`schema_version` 2, no `bindings.deploy`, no `capabilities.deploy` and
the platform interval `[max(min_inclusive, 1.2.0), 3.0.0)`, every other member
keeping its authored order, and refuses `adopt.migration.deploy_in_use` at the
first of `/bindings/deploy/adapter`, `/bindings/deploy/command` and
`/capabilities/deploy/support` that keeps the watch alive.

Before any write it refuses `adopt.migration.path_outside_checkout` for a
touched path that resolves outside the checkout (a symlinked directory
included, checked with `adopt_inspection.contained_relative`),
`adopt.migration.symlink_target` for a touched file that is itself a symbolic
link (the projection writer would replace it with a regular file and the byte
restore would not bring the link back), and `adopt.migration.unreadable` for a
touched file that exists but cannot be read, since no backup of it could be
restored. It then reads the bytes of `.agents/project.json`, `AGENTS.md` and
`CLAUDE.md`, writes the contract with the serialiser `apply` uses for an
amended authored file, runs the resolver children `write-projections` and
`resolve` through `run_resolver`, and prints `{"migration": ID, "written":
[...]}` with the sorted repository-relative paths whose bytes changed. Both
children run in the resolver of this process's store environment, so a host
whose installed manifest does not admit the target schema refuses
`adopt.migration.result_invalid`, carrying the child's `error.code` and
`repair_id` in `violations[0].message`. This is the one place `adopt-project`
rewrites a file it already wrote: on a refusal after the write, every byte is
restored (and each file's timestamps), so the tree is as before. Every refusal
exits 2 with the adopt error envelope.

It never stages, commits or fetches and touches only the contract and the
`target` of each projection the source contract declares; the operator commits.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Callable

from agent_tools import adopt_inspection, agent_platform

PLATFORM_FLOOR = "1.2.0"
PLATFORM_CEILING = "3.0.0"

Resolver = Callable[..., tuple[int, object]]


def retire_bindings_deploy(source: dict) -> dict:
    """The schema-2 form of a schema-1 contract: a deep copy with no deploy
    members, `schema_version` 2 and a platform interval that admits 1.2.0 and
    stops before 3.0.0. Every other member keeps its authored order and value."""
    out = copy.deepcopy(source)
    out["schema_version"] = 2
    out["bindings"].pop("deploy", None)
    out["capabilities"].pop("deploy", None)
    minimum = source["platform"]["min_inclusive"]
    if agent_platform.compare_semver(minimum, PLATFORM_FLOOR) < 0:
        minimum = PLATFORM_FLOOR
    out["platform"] = {"min_inclusive": minimum,
                       "max_exclusive": PLATFORM_CEILING}
    return out


MIGRATIONS: dict[str, Callable[[dict], dict]] = {
    "bindings-deploy.retire": retire_bindings_deploy,
}


def _refuse(repair_id: str, pointer: str, message: str,
            code: str = "adopt_failure") -> adopt_inspection.AdoptError:
    return adopt_inspection.refuse(code, repair_id, pointer, message)


def deploy_in_use(source: dict) -> str | None:
    """The pointer of the first member that keeps the deploy watch alive."""
    deploy = (source.get("bindings") or {}).get("deploy", {})
    if not isinstance(deploy, dict):
        return "/bindings/deploy"
    if deploy.get("adapter", "none") != "none":
        return "/bindings/deploy/adapter"
    if deploy.get("command") is not None:
        return "/bindings/deploy/command"
    support = (source.get("capabilities") or {}).get("deploy", {})
    if not isinstance(support, dict) or support.get("support", "unsupported") != "unsupported":
        return "/capabilities/deploy/support"
    return None


def _inside_root(name: str) -> bool:
    """A relative path with no `..` part: one the resolver would accept, and
    the only kind this module may read, restore or remove."""
    path = Path(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts


def touched_paths(source: dict) -> tuple[str, ...]:
    """The repository-relative files a migration may write: the contract and
    the `target` of every projection the source contract declares. A target is
    any safe relative path, so the set comes from the contract, not a list."""
    entries = source.get("projections")
    targets = [entry["target"] for entry in entries
               if isinstance(entry, dict) and isinstance(entry.get("target"), str)
               and _inside_root(entry["target"])
               ] if isinstance(entries, list) else []
    return tuple(dict.fromkeys([adopt_inspection.CONTRACT_FILENAME, *targets]))


def _missing_parents(root: Path, name: str) -> list[Path]:
    """The directories between `root` and `name` that do not exist yet,
    outermost first: the projection writer creates them for a nested target."""
    missing = []
    for parent in reversed((root / name).parents):
        if parent != root and root in parent.parents and not parent.exists():
            missing.append(parent)
    return missing


def _restore(root: Path, kept: dict[str, tuple[bytes, os.stat_result] | None],
             created: list[Path]) -> None:
    for name, state in kept.items():
        target = root / name
        if state is None:
            target.unlink(missing_ok=True)
            continue
        data, stat = state
        if target.read_bytes() != data:
            agent_platform.write_atomically(target, data)
        os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    for directory in reversed(created):
        try:
            directory.rmdir()
        except OSError:
            pass


def _result_invalid(code: object, repair_id: object) -> adopt_inspection.AdoptError:
    return _refuse("adopt.migration.result_invalid", "",
                   f"the resolver refused the migrated contract: {code} ({repair_id})",
                   "verification_failed")


def _child_refusal(exit_code: int, payload: object) -> adopt_inspection.AdoptError | None:
    if exit_code != 0:
        error = payload.get("error") if isinstance(payload, dict) else None
        error = error if isinstance(error, dict) else {}
        return _result_invalid(error.get("code"), error.get("repair_id"))
    if not isinstance(payload, dict):
        return _result_invalid(None, "the resolver printed no document")
    return None


def migrate(root: Path, migration_id: str, manifest: dict,
            source: dict | None, run_resolver: Resolver) -> dict:
    """Apply `migration_id` to the checkout at `root` and report what changed."""
    entry = next((item for item in manifest.get("migrations", ())
                  if item.get("id") == migration_id), None)
    executor = MIGRATIONS.get(migration_id)
    if entry is None or executor is None:
        raise _refuse("adopt.migration.unknown", "/migration",
                      "the manifest names no executable migration of that id")
    if source is None or source.get("schema_version") != entry["from_schema"]:
        raise _refuse("adopt.migration.not_applicable", "/schema_version",
                      "the contract is not at the schema this migration starts from")
    pointer = deploy_in_use(source)
    if pointer is not None:
        raise _refuse("adopt.migration.deploy_in_use", pointer,
                      "the deploy watch is in use and cannot be retired")
    try:
        migrated = executor(source)
    except (KeyError, TypeError, ValueError, AttributeError):
        raise _refuse("adopt.migration.result_invalid", "/platform",
                      "the contract cannot be migrated: its platform interval "
                      "is not a pair of strict SemVer strings",
                      "verification_failed") from None

    touched = touched_paths(source)
    kept: dict[str, tuple[bytes, os.stat_result] | None] = {}
    created: list[Path] = []
    for name in touched:
        if not adopt_inspection.contained_relative(root, name):
            raise _refuse("adopt.migration.path_outside_checkout", f"/{name}",
                          "the path resolves outside the checkout, so it is "
                          "neither read nor written")
    for name in touched:
        if (root / name).is_symlink():
            raise _refuse("adopt.migration.symlink_target", f"/{name}",
                          "the file is a symbolic link, which the projection "
                          "writer would replace with a regular file and a "
                          "restore could not put back")
    for name in touched:
        created.extend(path for path in _missing_parents(root, name)
                       if path not in created)
        target = root / name
        data = adopt_inspection.read_bytes_bounded(target)
        if data is None and os.path.lexists(target):
            raise _refuse("adopt.migration.unreadable", f"/{name}",
                          "the file exists but cannot be read, so it cannot be "
                          "backed up and restored")
        kept[name] = None if data is None else (data, target.stat())
    try:
        agent_platform.write_atomically(
            root / adopt_inspection.CONTRACT_FILENAME,
            adopt_inspection.authored_bytes(migrated))
        for command in ("write-projections", "resolve"):
            exit_code, payload = run_resolver(root, command)
            refusal = _child_refusal(exit_code, payload)
            if refusal is not None:
                raise refusal
    except BaseException:
        _restore(root, kept, created)
        raise

    written = sorted(
        name for name in touched
        if adopt_inspection.read_bytes_bounded(root / name)
        != (None if kept[name] is None else kept[name][0]))
    return {"migration": migration_id, "written": written}
