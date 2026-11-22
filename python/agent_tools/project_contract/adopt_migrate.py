"""`adopt-project migrate`: execute one manifest migration on a checkout.

A manifest `migrations` entry names a single schema step. This module holds
the executors, keyed by the entry's id, and the transaction that applies one:
write the transformed contract, have the resolver child regenerate the
projections, have the resolver child judge the result, and restore every byte
if either refuses. The resolver is never imported (D26): `adopt_project` hands
in `run_resolver`, so validation and the projection writer both run in the
resolver of this process's own store environment.

`adopt-project migrate --migration ID [--repo-root R]` executes one manifest
`migrations` entry (issue 579). `MIGRATIONS` maps an id to a `Migration`: a
pure rewrite plus what the transaction must do for it. An id the manifest lists
without an executor, or an executor the manifest does not list, refuses
`adopt.migration.unknown`. The contract's `schema_version` must equal the
entry's `from_schema` (`adopt.migration.not_applicable` otherwise, which is
also what a second run over a migrated tree gets).

`bindings-deploy.retire` returns a deep copy of the contract with
`schema_version` 2, no `bindings.deploy`, no `capabilities.deploy` and
the platform interval `[max(min_inclusive, 1.2.0), 3.0.0)`, every other member
keeping its authored order, and refuses `adopt.migration.deploy_in_use` at the
first of `/bindings/deploy/adapter`, `/bindings/deploy/command` and
`/capabilities/deploy/support` that keeps the watch alive. The deploy check
belongs to this migration alone.

`platform-constants.retire` (#1469, ADR-project-contract-013 D8) moves a
schema-2 contract to schema 3. It compares and refuses, and never drops a value
that would change. It raises the first non-empty class of refusal, with every
violation of that class: `adopt.migration.constant_differs`, then
`adopt.migration.not_derivable`, then `adopt.migration.derived_differs`. Two
values agree when their sorted-key JSON text is equal, so `1` is not `true` and
`2.0` is not `2`, and an absent value differs. The constants are every pointer
of `schema_three.CONSTANTS`; then every platform command, as schema 2 holds it
(the authored command, else the platform's own review commands, else absent,
so a missing `commit-environment` differs); then the `cwd` `.` and the `env`
`[]` of every other authored command. The repository's derived values must agree
with what `derived_values.derive` states: the project id, the repository slug
and the required checks (with no declared checks an absent or `null` member
agrees and `[]` does not), an authored platform interval agrees when it admits
the platform version the repository states (the derived interval replaces it),
and the attempt budget must equal the one the recorded history gives
(`attempt_history.derive_schema_three`) while an authored budget basis
disagrees. A value the repository cannot state is `not_derivable`. It also
refuses `adopt.migration.projection_in_retired_tree` for a projection target
inside `.agents/artifacts`, `adopt.migration.symlink_target` for a retired file
or any directory above it that is a symbolic link, and
`adopt.migration.artifact_modified` for a retired file with an unstaged edit
or one marked assume-unchanged or skip-worktree, whose edit git cannot see (a
staged change is recoverable from the index), and
`adopt.migration.pinned_platform_too_old` when the platform the repository pins
is older than the installed one that reads schema 3. A projection target counts
as inside the retired tree by normalised path, by resolved path and by file
identity of the target or a directory above it (another letter case on a
case-insensitive volume), and a retired file that exists again after the
resolver children ran is refused `adopt.migration.retired_file_recreated` and
restored. Only descendants
of `.agents/artifacts` are retired, never a file named exactly like it. It then removes every
retired, constant and derived member and each command's `cwd` and `env`, prunes
the objects those removals emptied, and sets `schema_version` 3. It deletes
every tracked file under `.agents/artifacts/` from the working tree (the index
is untouched), lists each in `written`, and restores each on a refusal. It is
the one migration that runs git (`ls-files`, `diff`).

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
import json
import os
import stat
from pathlib import Path
from typing import Callable, NamedTuple

from agent_tools.project_contract import (
    adopt_inspection, agent_platform, attempt_history, derived_values, schema_three)
from agent_tools.system import semver

PLATFORM_FLOOR = "1.2.0"
PLATFORM_CEILING = "3.0.0"
ARTIFACT_TREE = ".agents/artifacts"

Resolver = Callable[..., tuple[int, object]]


def retire_bindings_deploy(
        source: dict, derived: derived_values.Derived = derived_values.NONE) -> dict:
    """The schema-2 form of a schema-1 contract: a deep copy with no deploy
    members, `schema_version` 2 and a platform interval that admits 1.2.0 and
    stops before 3.0.0. Every other member keeps its authored order and value.
    `derived` is ignored: this migration reads no derivation input."""
    out = copy.deepcopy(source)
    out["schema_version"] = 2
    out["bindings"].pop("deploy", None)
    out["capabilities"].pop("deploy", None)
    minimum = source["platform"]["min_inclusive"]
    if semver.compare_semver(minimum, PLATFORM_FLOOR) < 0:
        minimum = PLATFORM_FLOOR
    out["platform"] = {"min_inclusive": minimum,
                       "max_exclusive": PLATFORM_CEILING}
    return out


def _refuse(repair_id: str, pointer: str, message: str,
            code: str = "adopt_failure") -> adopt_inspection.AdoptError:
    return adopt_inspection.refuse(code, repair_id, pointer, message)


def _refuse_all(repair_id: str,
                violations: list[dict]) -> adopt_inspection.AdoptError:
    return adopt_inspection.AdoptError("adopt_failure", repair_id, violations)


def _same(left: object, right: object) -> bool:
    """Two JSON values agree when their sorted-key texts are equal: `1` is not `true`, `2.0` is not `2`.

    `ABSENT` agrees only with `ABSENT`."""
    if left is schema_three.ABSENT or right is schema_three.ABSENT:
        return left is right
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def _token(name: str) -> str:
    """One reference token of an RFC 6901 JSON pointer."""
    return name.replace("~", "~0").replace("/", "~1")


def _differs(pointer: str, constant: object) -> dict:
    return {"pointer": pointer,
            "message": f"differs from the platform constant {json.dumps(constant)}"}


def _disagrees(pointer: str, stated: object) -> dict:
    return {"pointer": pointer,
            "message": "disagrees with the value the repository states: "
                       f"{json.dumps(None if stated is schema_three.ABSENT else stated)}"}


def _command_table(source: dict) -> dict:
    bindings = source.get("bindings")
    commands = bindings.get("commands") if isinstance(bindings, dict) else None
    return commands if isinstance(commands, dict) else {}


def _constant_violations(source: dict) -> list[dict]:
    found = []
    for pointer, constant in schema_three.CONSTANTS.items():
        authored = schema_three.authored_at(source, pointer)
        if not _same(authored, constant):
            found.append(_differs(pointer, constant))
    commands = _command_table(source)
    for command_id, constant in schema_three.COMMANDS.items():
        effective = commands.get(
            command_id, agent_platform.PLATFORM_COMMANDS.get(command_id, schema_three.ABSENT))
        if not _same(effective, constant):
            found.append(_differs(f"/bindings/commands/{command_id}", constant))
    for command_id, command in commands.items():
        if command_id in schema_three.COMMANDS or not isinstance(command, dict):
            continue
        for member, constant in schema_three.COMMAND_CONSTANTS.items():
            if member not in command or not _same(command[member], constant):
                found.append(_differs(
                    f"/bindings/commands/{_token(command_id)}/{member}", constant))
    return found


def _interval_agrees(authored: object, stated: object) -> bool:
    """Whether an authored platform interval admits the platform version the repository states."""
    if not isinstance(authored, dict) or not isinstance(stated, dict):
        return False
    version = stated.get("min_inclusive")
    low, high = authored.get("min_inclusive"), authored.get("max_exclusive")
    if any(semver.parse_semver(value) is None for value in (version, low, high)):
        return False
    return (semver.compare_semver(low, version) <= 0
            < semver.compare_semver(high, version))


def _derived_violations(source: dict, derived: derived_values.Derived) -> list[dict]:
    found = []
    values = derived.values
    for pointer in schema_three.DERIVED:
        authored = schema_three.authored_at(source, pointer)
        stated = values.get(pointer, schema_three.ABSENT)
        if pointer == derived_values.REQUIRED_CHECKS:
            agrees = (authored is schema_three.ABSENT or authored is None
                      if stated is schema_three.ABSENT else _same(authored, stated))
        elif pointer == derived_values.PLATFORM:
            agrees = _interval_agrees(authored, stated)
        elif pointer == schema_three.ATTEMPT_BUDGET_BASIS:
            agrees = authored is schema_three.ABSENT
        else:
            agrees = authored is not schema_three.ABSENT and _same(authored, stated)
        if not agrees:
            found.append(_disagrees(pointer, stated))
    return found


def _prune_emptied(document: dict, removed: list[str]) -> None:
    """Remove each object the removals emptied, from the removed pointer up, never the document root."""
    for pointer in removed:
        keys = pointer.split("/")[1:-1]
        while keys:
            node = schema_three.authored_at(document, "/" + "/".join(keys))
            if not isinstance(node, dict) or node:
                break
            schema_three.remove_at(document, "/" + "/".join(keys))
            keys.pop()


def retire_platform_constants(source: dict, derived: derived_values.Derived) -> dict:
    """The schema-3 form of a schema-2 contract, or a refusal when that would change a value.

    Pure. A refusal is an `AdoptError` listing every violation of the first
    non-empty class (the module docstring states the three), and nothing else
    is raised for any JSON object.
    """
    for repair_id, check in (
            ("adopt.migration.constant_differs", lambda: _constant_violations(source)),
            ("adopt.migration.not_derivable",
             lambda: [{"pointer": item["pointer"], "message": item["message"]}
                      for item in derived.violations]),
            ("adopt.migration.derived_differs", lambda: _derived_violations(source, derived))):
        violations = check()
        if violations:
            raise _refuse_all(repair_id, violations)
    out = copy.deepcopy(source)
    out["schema_version"] = schema_three.SCHEMA_VERSION
    removed = []
    for pointer in (*schema_three.RETIRED, *schema_three.CONSTANTS, *schema_three.DERIVED):
        if schema_three.authored_at(out, pointer) is not schema_three.ABSENT:
            schema_three.remove_at(out, pointer)
            removed.append(pointer)
    commands = _command_table(out)
    for command_id in list(commands):
        if command_id in schema_three.COMMANDS:
            del commands[command_id]
            removed.append(f"/bindings/commands/{_token(command_id)}")
        elif isinstance(commands[command_id], dict):
            for member in schema_three.COMMAND_CONSTANTS:
                if commands[command_id].pop(member, schema_three.ABSENT) is not schema_three.ABSENT:
                    removed.append(f"/bindings/commands/{_token(command_id)}/{member}")
    _prune_emptied(out, removed)
    return out


class Migration(NamedTuple):
    """One executor and what the transaction does for it besides the rewrite."""
    rewrite: Callable[[dict, derived_values.Derived], dict]
    derives: bool = False
    retired_trees: tuple[str, ...] = ()
    retires_deploy: bool = False


MIGRATIONS: dict[str, Migration] = {
    "bindings-deploy.retire": Migration(retire_bindings_deploy, retires_deploy=True),
    "platform-constants.retire": Migration(
        retire_platform_constants, derives=True, retired_trees=(ARTIFACT_TREE,)),
}


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


def _retired_files(root: Path,
                   trees: tuple[str, ...]) -> tuple[list[str], set[str]]:
    """The tracked files below `trees`, sorted, and those git is told not to watch.

    Only descendants of a tree count: a tracked file named exactly like the tree
    is outside the scope. A flagged file is one `ls-files -v` tags other than
    `H`: assume-unchanged (lowercase) or skip-worktree (`S`), both of which hide
    a working-copy edit from `git diff`. No git call when there is no tree.
    """
    found: set[str] = set()
    flagged: set[str] = set()
    for tree in trees:
        for entry in adopt_inspection.split_nul(adopt_inspection.git_or_fail(
                root, "ls-files", "-v", "-z", "--", tree)):
            tag, name = entry[:1], entry[2:]
            if not name.startswith(tree + "/"):
                continue
            found.add(name)
            if tag.islower() or tag == "S":
                flagged.add(name)
    return sorted(found), flagged


def _modified_files(root: Path, trees: tuple[str, ...]) -> set[str]:
    """The files under `trees` whose working copy differs from the index."""
    found: set[str] = set()
    for tree in trees:
        found.update(adopt_inspection.split_nul(adopt_inspection.git_or_fail(
            root, "diff", "--name-only", "-z", "--no-renames", "--", tree)))
    return found


def _inside_root(name: str) -> bool:
    """A relative path with no `..` part: one the resolver would accept, and
    the only kind this module may read, restore or remove."""
    path = Path(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts


def _within(root: Path, target: str, tree: str) -> bool:
    """Whether `target` is `tree` or below it, by normalised and by resolved path,
    so `./tree/x` and a path through a link into the tree both count."""
    normal = os.path.normpath(target)
    if normal == tree or normal.startswith(tree + "/"):
        return True
    resolved, base = os.path.realpath(root / target), os.path.realpath(root / tree)
    if resolved == base or resolved.startswith(base + os.sep):
        return True
    return _same_directory_above(root, target, root / tree)


def _same_directory_above(root: Path, target: str, tree: Path) -> bool:
    """Whether `target` or a directory above it is `tree` by file identity.

    A string comparison cannot see a spelling the filesystem folds to the same
    entry (another letter case on a case-insensitive volume), so the identity
    of each existing ancestor, the target included, is compared instead.
    """
    if not tree.exists():
        return False
    path = root / target
    for candidate in (path, *path.parents):
        if candidate == root or root not in candidate.parents:
            break
        try:
            if candidate.exists() and os.path.samefile(candidate, tree):
                return True
        except OSError:
            continue
    return False


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
        data, kept_stat = state
        try:
            current = target.read_bytes()
        except FileNotFoundError:
            current = None
        if current != data:
            agent_platform.write_atomically(target, data)
            if current is None:
                os.chmod(target, stat.S_IMODE(kept_stat.st_mode))
        os.utime(target, ns=(kept_stat.st_atime_ns, kept_stat.st_mtime_ns))
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


def _require_pinned_platform_reads(manifest: dict,
                                   derived: derived_values.Derived) -> None:
    """Refuse a checkout whose pinned platform predates the installed one.

    The installed platform is the one known to read the schema the migration
    writes. A repository that pins an older platform runs a resolver that reads
    only the schema it has, so rewriting it would leave the checkout unreadable
    to its own pin.
    """
    pinned = derived.values.get(derived_values.PLATFORM, {}).get("min_inclusive")
    installed = manifest.get("platform_version")
    if (semver.parse_semver(pinned) is not None
            and semver.parse_semver(installed) is not None
            and semver.compare_semver(pinned, installed) < 0):
        raise _refuse("adopt.migration.pinned_platform_too_old", "/platform",
                      f"the repository pins platform {pinned}, older than the "
                      f"installed {installed} that reads the target schema; "
                      "update the pin first")


def migrate(root: Path, migration_id: str, manifest: dict,
            source: dict | None, run_resolver: Resolver) -> dict:
    """Apply `migration_id` to the checkout at `root` and report what changed."""
    entry = next((item for item in manifest.get("migrations", ())
                  if item.get("id") == migration_id), None)
    migration = MIGRATIONS.get(migration_id)
    if entry is None or migration is None:
        raise _refuse("adopt.migration.unknown", "/migration",
                      "the manifest names no executable migration of that id")
    version = None if source is None else source.get("schema_version")
    if type(version) is not int or version != entry["from_schema"]:
        raise _refuse("adopt.migration.not_applicable", "/schema_version",
                      "the contract is not at the schema this migration starts from")
    if migration.retires_deploy:
        pointer = deploy_in_use(source)
        if pointer is not None:
            raise _refuse("adopt.migration.deploy_in_use", pointer,
                          "the deploy watch is in use and cannot be retired")
    derived = (attempt_history.derive_schema_three(root) if migration.derives
               else derived_values.NONE)
    try:
        migrated = migration.rewrite(source, derived)
    except (KeyError, TypeError, ValueError, AttributeError):
        raise _refuse("adopt.migration.result_invalid", "/platform",
                      "the contract cannot be migrated: its platform interval "
                      "is not a pair of strict SemVer strings",
                      "verification_failed") from None

    if migration.derives:
        _require_pinned_platform_reads(manifest, derived)
    projections = touched_paths(source)
    retired, flagged = (_retired_files(root, migration.retired_trees)
                        if migration.retired_trees else ([], set()))
    inside = [f"/{target}" for target in projections
              if any(_within(root, target, tree) for tree in migration.retired_trees)]
    if inside:
        raise _refuse_all("adopt.migration.projection_in_retired_tree", [
            {"pointer": pointer,
             "message": "a projection targets a tree this migration deletes, "
                        "so the projection writer would recreate the file"}
            for pointer in inside])
    touched = tuple(dict.fromkeys([*projections, *retired]))
    retired_set = set(retired)
    kept: dict[str, tuple[bytes, os.stat_result] | None] = {}
    created: list[Path] = []
    for name in touched:
        if not adopt_inspection.contained_relative(root, name):
            raise _refuse("adopt.migration.path_outside_checkout", f"/{name}",
                          "the path resolves outside the checkout, so it is "
                          "neither read nor written")
    for name in touched:
        linked = [(root / name)] + (
            [parent for parent in (root / name).parents
             if parent != root and root in parent.parents] if name in retired_set else [])
        if any(path.is_symlink() for path in linked):
            raise _refuse("adopt.migration.symlink_target", f"/{name}",
                          "the file, or a directory above a file this migration "
                          "deletes, is a symbolic link, which the projection "
                          "writer would replace with a regular file and a "
                          "restore could not put back")
    if retired:
        modified = _modified_files(root, migration.retired_trees) | flagged
        edited = [f"/{name}" for name in retired
                  if name in modified and os.path.lexists(root / name)]
        if edited:
            raise _refuse_all("adopt.migration.artifact_modified", [
                {"pointer": pointer,
                 "message": "the working copy differs from the index, or git is "
                            "told not to watch it (assume-unchanged or "
                            "skip-worktree), so deleting it could lose an edit"}
                for pointer in edited])
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
        for name in retired:
            (root / name).unlink(missing_ok=True)
        for command in ("write-projections", "resolve"):
            exit_code, payload = run_resolver(root, command)
            refusal = _child_refusal(exit_code, payload)
            if refusal is not None:
                raise refusal
        recreated = [f"/{name}" for name in retired
                     if os.path.lexists(root / name)]
        if recreated:
            raise _refuse_all("adopt.migration.retired_file_recreated", [
                {"pointer": pointer,
                 "message": "a retired file exists again after the resolver "
                            "wrote the projections, so the migration did not "
                            "retire it"}
                for pointer in recreated])
    except BaseException:
        _restore(root, kept, created)
        raise

    written = sorted(
        name for name in touched
        if adopt_inspection.read_bytes_bounded(root / name)
        != (None if kept[name] is None else kept[name][0]))
    return {"migration": migration_id, "written": written}
