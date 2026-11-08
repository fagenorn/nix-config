"""`adopt-project migrate`: execute one manifest migration on a checkout.

A manifest `migrations` entry names a single schema step. This module holds
the executors, keyed by the entry's id, and the transaction that applies one:
write the transformed contract, have the resolver child regenerate the
projections, have the resolver child judge the result, and restore every byte
if either refuses. The resolver is never imported (D26): `adopt_project` hands
in `run_resolver`, so validation and the projection writer both run in the
resolver of this process's own store environment.

It never stages, commits or fetches and touches only the contract and the two
projection targets; the operator commits.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Callable

from agent_tools import adopt_inspection, agent_platform

PLATFORM_FLOOR = "1.2.0"
PLATFORM_CEILING = "3.0.0"

# The only files a migration may write, repository-relative.
PROJECTION_FILENAMES = ("AGENTS.md", "CLAUDE.md")
TOUCHED = (adopt_inspection.CONTRACT_FILENAME, *PROJECTION_FILENAMES)

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


def _restore(root: Path, kept: dict[str, tuple[bytes, os.stat_result] | None]) -> None:
    for name, state in kept.items():
        target = root / name
        if state is None:
            target.unlink(missing_ok=True)
            continue
        data, stat = state
        if target.read_bytes() != data:
            agent_platform.write_atomically(target, data)
        os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))


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

    kept: dict[str, tuple[bytes, os.stat_result] | None] = {}
    for name in TOUCHED:
        target = root / name
        data = adopt_inspection.read_bytes_bounded(target)
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
        _restore(root, kept)
        raise

    written = sorted(
        name for name in TOUCHED
        if adopt_inspection.read_bytes_bounded(root / name)
        != (None if kept[name] is None else kept[name][0]))
    return {"migration": migration_id, "written": written}
