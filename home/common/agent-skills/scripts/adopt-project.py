#!/usr/bin/env python3
"""Plan this repository's adoption into the shared agent platform.

`plan` inspects a target checkout inside a bounded, read-only boundary,
classifies every candidate it finds under one closed action set, routes the
repository to exactly one of five closed outcomes, and emits the seven-member
adoption plan document: `schema_version`, `plan`, `evidence`, `decisions`,
`changes`, `verification`, `handoff` (R4.3).

The document is content-addressed. `plan_id` is the SHA-256 of canonical JSON
over exactly `{adopt_schema_version, project_id, base_revision, platform,
evidence, decisions.answered}` (D15), so two checkouts of one revision on one
platform produce one identifier and any change to a source byte, the base
revision or a platform input produces another. The absolute checkout path is
deliberately outside that source and appears only in `handoff`.

Nothing here mutates the target. `plan` runs `git` and the resolver as child
processes, reads tracked object ids rather than tracked bytes, and writes only
under `~/.agents/state/` (R4.1, D14).

The resolver is consumed **only** as a subprocess at the absolute path
`$HOME/.agents/bin/resolve-project`, never imported (D26): contract validation
has one home, and a stale generation earlier on `PATH` cannot answer. The
shared platform library `agent_platform` is imported directly — it is the one
home for the manifest loader, the state root and the atomic writer (D37).

A structural refusal prints exactly one JSON object carrying an `error` member
on stdout and exits 2 (D12). An argparse usage error also exits 2 but prints no
JSON, which is how a caller tells the two apart (D16).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

# The shared platform library, bound by `bootstrap_platform_library` before any
# subcommand runs, exactly as `resolve-project.py` binds it. It is deliberately
# not imported at module scope: an absent library is a platform installation
# defect and has to reach the caller as the D12 error object on stdout, not as
# an import traceback on stderr.
agent_platform = None

PLATFORM_LIBRARY_MEMBERS = (
    "PlatformManifestError",
    "ensure_directory",
    "load_manifest",
    "parse_semver",
    "read_registry",
    "state_root",
    "write_atomically",
)
PLATFORM_LIBRARY_REPAIR_ID = "platform.library.missing"


def bootstrap_platform_library() -> bool:
    """Bind the shared library from its one installed path, or report failure."""
    global agent_platform
    home = os.environ.get("HOME")
    if not home:
        return False
    sys.path.insert(0, str(Path(home) / ".agents" / "lib" / "python"))
    try:
        import agent_platform as loaded
    except Exception:
        return False
    if (not getattr(loaded, "__file__", None)
            or any(not hasattr(loaded, name)
                   for name in PLATFORM_LIBRARY_MEMBERS)):
        return False
    agent_platform = loaded
    return True


# --------------------------------------------------------------------------
# Closed sets
#
# Every one of these is added exactly once and dispatched exhaustively: each
# `*_for` helper below raises on its default branch, so a member added to a
# tuple without a home is a crash rather than a plausible-looking blank.
# --------------------------------------------------------------------------

ADOPT_SCHEMA_VERSION = 1

ADOPT_ERROR_CODES = (
    "not_a_repository",
    "plan_not_found",
    "not_ready",
    "plan_stale",
    "dirty_worktree",
    "unacknowledged_deletion",
    "duplicate_project_id",
    "not_integrated",
    "verification_failed",
    "adopt_failure",
)

ACTIONS = (
    "move-canonical",
    "generate-projection",
    "retain-product",
    "archive-history",
    "delete-exact-duplicate",
    "needs-decision",
)
OUTCOMES = ("bootstrap", "reconcile", "no_change", "migration_required",
            "repair_required")
PLAN_STATES = ("draft", "ready", "not_applicable")
OPERATION_KINDS = ("git-mv", "write-file", "delete-file",
                   "regenerate-projection")
APPROVAL_CLASSES = ("normal", "destructive")
PROVENANCES = (
    "tracked",
    "targeted-ignored",
    "targeted-ignored-metadata-only",
    "git-worktree-metadata-only",
    "untracked-explicit-paths",
)
GATE_STATUSES = ("passed", "failed", "not_run")
LIFECYCLE_CLASSES = (
    "canonical-tracked",
    "durable-artifact",
    "legacy-native-store",
    "native-projection",
    "ignored-runtime",
    "product-source",
    "binding-evidence",
    "runtime-residue",
    "secret-shaped",
    "untracked-overlap",
    "unclassified",
)

# D35: the public question contract. An id is a literal, never formatted at
# emission, so a caller can dispatch over the set exhaustively.
QUESTION_IDS = ("project-id",)

READY_GATES = (
    "contract-valid-after-amendment",
    "no-needs-decision",
    "no-open-decisions",
    "no-untracked-overlap",
    "no-existing-destination",
    "move-sources-tracked",
    "no-secret-path-in-moves",
)

# The gates `apply` runs inside its isolated worktree before it commits. They
# are declared here because the plan document publishes them, and at plan time
# every one of them is `not_run` — nothing has been executed yet.
COMMIT_GATES = (
    "worktree-status-matches-operations",
    "projections-in-sync",
    "no-unclassified-agent-path",
    "cold-clone-resolves",
    "resolve-capabilities-available",
    "workflow-verification-commands",
)

CONTRACT_FILENAME = ".agents/project.json"
RUNTIME_SENTINEL = ".agents/runtime/.gitignore"
RUNTIME_SENTINEL_BYTES = b"*\n"
RUNTIME_IGNORE_PATTERN = ".agents/runtime/"
GITIGNORE = ".gitignore"
MIGRATION_MAP_DIR = ".agents/knowledge/archive/path-migrations"
EVIDENCE_RECORD_DIR = ".agents/artifacts/evidence"

# The one closed list of ignored paths the inspection may look at. A bare
# ignored-tree walk is never performed: the outer half of the defence in depth
# whose inner half is `SECRET_MARKERS` below.
TARGETED_IGNORED = (".agents", ".claude/skills", ".claude/hints",
                    ".claude/rules", ".claude/settings.local.json", ".codex",
                    "AGENTS.md", "CLAUDE.md", ".mcp.json")

# Inspected for path names and counts only; their contents are never read and
# their fingerprint is always null.
METADATA_ONLY_IGNORED = (".superpowers", ".worktrees")

# A path with any of these as a component is never read, never hashed, never a
# move source and never a move target. `.env` is a prefix marker (`.env*`); the
# rest match a whole component.
SECRET_MARKERS = ("credential", "credentials", "private", "secret", "secrets",
                  "token", "tokens")
SECRET_PREFIXES = (".env",)

# D30: the whole living-reference sweep. Nothing outside this tuple is ever a
# rewrite target — a repository-wide reference scan is not mechanically
# decidable and would risk re-pointing machine-global platform source.
LEGACY_BINDING_CONFIGS = (".claude/skills.config.json",)
LEGACY_BINDING_KEYS = (
    ("specDir", ("artifacts", "specs")),
    ("planDir", ("artifacts", "plans")),
    ("rejectionsDir", ("rejections", 0)),
)

# Paths whose presence makes a repository an agent-development surface even
# when no contract exists. Used by routing rules 1 and 2.
NATIVE_AGENT_PATHS = (".claude", ".codex", "AGENTS.md", "CLAUDE.md",
                      ".mcp.json")

# The closed classification table, first match wins. Each row is
# `(group, match, lifecycle_class, action, target)`: `match` is `exact` for one
# path and `prefix` for a directory tree, and `target` is the destination group
# a `move-canonical` row relocates into, or None.
CLASSIFICATION_RULES = (
    (CONTRACT_FILENAME, "exact", "canonical-tracked", "move-canonical",
     CONTRACT_FILENAME),
    (".agents/instructions", "prefix", "canonical-tracked", "retain-product",
     None),
    (".agents/runtime", "prefix", "ignored-runtime", "retain-product", None),
    (".agents", "prefix", "canonical-tracked", "retain-product", None),
    (".claude/specs", "prefix", "durable-artifact", "move-canonical",
     ".agents/artifacts/specs"),
    (".claude/plans", "prefix", "durable-artifact", "move-canonical",
     ".agents/artifacts/plans"),
    (".out-of-scope", "prefix", "canonical-tracked", "move-canonical",
     ".agents/knowledge/rejections"),
    (".claude/skills.config.json", "exact", "legacy-native-store",
     "retain-product", None),
    (".claude/settings.local.json", "exact", "legacy-native-store",
     "retain-product", None),
    (".claude/skills", "prefix", "legacy-native-store", "retain-product", None),
    (".claude/hints", "prefix", "legacy-native-store", "retain-product", None),
    (".claude/rules", "prefix", "legacy-native-store", "retain-product", None),
    (".codex", "prefix", "legacy-native-store", "retain-product", None),
    (".mcp.json", "exact", "legacy-native-store", "retain-product", None),
    ("CLAUDE.md", "exact", "native-projection", "generate-projection",
     "CLAUDE.md"),
    ("AGENTS.md", "exact", "native-projection", "generate-projection",
     "AGENTS.md"),
    ("home/common/agent-skills", "prefix", "product-source", "retain-product",
     None),
    ("home/common/agent-guidance", "prefix", "product-source",
     "retain-product", None),
    ("home/common/claude-code", "prefix", "product-source", "retain-product",
     None),
    ("patches/agent-plugins", "prefix", "product-source", "retain-product",
     None),
    ("lib/agent-plugins.nix", "exact", "product-source", "retain-product",
     None),
    ("justfile", "exact", "binding-evidence", "retain-product", None),
    (".github", "prefix", "binding-evidence", "retain-product", None),
    (".superpowers", "prefix", "runtime-residue", "retain-product", None),
    (".worktrees", "prefix", "runtime-residue", "retain-product", None),
)

# Fixed notes. Never formatted from variable data: `evidence` is inside the
# `plan_id` digest, so a note carrying a path or a count would make the
# identifier turn on prose.
NOTES = {
    "metadata-only": "inspected for path names and counts only; contents are "
                     "never read",
    "git-worktree": "registered worktrees, by name; no worktree content is "
                    "inspected",
    "secret-shaped": "secret-shaped path: recorded by name, never read, never "
                     "hashed, never moved",
    "untracked": "untracked file overlapping an inspected source or a planned "
                 "destination",
    "unclassified": "no lifecycle class covers this agent path; adoption "
                    "cannot proceed until it is classified",
    "escaping-symlink": "resolves outside the target root; contents are never "
                        "read",
}


class AdoptError(Exception):
    """One refusal: a closed code, a stable repair id, and ordered violations."""

    def __init__(self, code: str, repair_id: str, violations: list[dict]) -> None:
        super().__init__(f"{code}: {repair_id}")
        if code not in ADOPT_ERROR_CODES:
            raise ValueError(f"unknown adoption error code: {code!r}")
        self.code = code
        self.repair_id = repair_id
        self.violations = violations


def refuse(code: str, repair_id: str, pointer: str, message: str) -> AdoptError:
    return AdoptError(code, repair_id, [{"pointer": pointer,
                                         "message": message}])


def emit_json(value: object) -> int:
    json.dump(value, sys.stdout, sort_keys=True, separators=(",", ":"),
              allow_nan=False)
    sys.stdout.write("\n")
    return 0


def emit_error(code: str, repair_id: str, violations: list[dict]) -> int:
    """The one place an error object reaches stdout (D12)."""
    ordered = sorted(violations, key=lambda item: item["pointer"])
    emit_json({"error": {"code": code, "repair_id": repair_id,
                         "violations": ordered}})
    return 2


# --------------------------------------------------------------------------
# Exhaustive dispatch over the closed sets
# --------------------------------------------------------------------------


def approval_class_for(kind: str) -> str:
    """The approval a typed operation demands. Only deletion is destructive."""
    if kind in ("git-mv", "write-file", "regenerate-projection"):
        return "normal"
    if kind == "delete-file":
        return "destructive"
    raise ValueError(f"unknown operation kind: {kind!r}")


def action_relocates(action: str) -> bool:
    """Whether an action moves a candidate to a new canonical home."""
    if action == "move-canonical":
        return True
    if action in ("generate-projection", "retain-product", "archive-history",
                  "delete-exact-duplicate", "needs-decision"):
        return False
    raise ValueError(f"unknown adoption action: {action!r}")


def fingerprint_is_content_addressed(provenance: str) -> bool:
    """Whether a group with this provenance carries a content fingerprint."""
    if provenance in ("tracked", "targeted-ignored"):
        return True
    if provenance in ("targeted-ignored-metadata-only",
                      "git-worktree-metadata-only",
                      "untracked-explicit-paths"):
        return False
    raise ValueError(f"unknown provenance: {provenance!r}")


def outcome_is_appliable(outcome: str) -> bool:
    """Whether an outcome produces a plan `apply` could ever run (D27)."""
    if outcome in ("bootstrap", "reconcile"):
        return True
    if outcome in ("no_change", "migration_required", "repair_required"):
        return False
    raise ValueError(f"unknown adoption outcome: {outcome!r}")


def gate_entry(gate_id: str, status: str, repair_id: str | None) -> dict:
    if status not in GATE_STATUSES:
        raise ValueError(f"unknown gate status: {status!r}")
    return {"id": gate_id, "status": status, "repair_id": repair_id}


def question_impact(question_id: str) -> str:
    """The fixed impact prose of each open question (D35)."""
    if question_id == "project-id":
        return ("adoption cannot name the project it is adopting, so the "
                "contract, the fleet registry and the adoption evidence "
                "record would all disagree about its identity")
    raise ValueError(f"unknown question id: {question_id!r}")


def question_recommendation(question_id: str) -> str:
    """The fixed recommendation prose of each open question (D35)."""
    if question_id == "project-id":
        return ("declare exactly one remote naming the canonical repository, "
                "or author .agents/project.json with the intended project id "
                "before planning again")
    raise ValueError(f"unknown question id: {question_id!r}")


def plan_state_is_terminal(state: str) -> bool:
    """Whether a plan in this state can never become appliable (D27)."""
    if state == "not_applicable":
        return True
    if state in ("draft", "ready"):
        return False
    raise ValueError(f"unknown plan state: {state!r}")


# --------------------------------------------------------------------------
# Hashes
# --------------------------------------------------------------------------


def sha256_hash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def object_hash(object_id: str) -> str:
    """A tracked blob's content hash, taken from git's own object id.

    Named with its algorithm so the hash cannot be confused with a SHA-256 of
    the same bytes, and cheap: it needs no file read, which is what keeps the
    tracked half of the inspection off the filesystem entirely.
    """
    return "git-object:" + object_id


def group_fingerprint(members: list[tuple[str, str]]) -> str:
    """`sha256` over `Σ sorted(path \\0 object-id \\n)` for a tracked group."""
    digest = hashlib.sha256()
    for path, object_id in sorted(members):
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(object_id.encode("utf-8"))
        digest.update(b"\n")
    return "sha256:" + digest.hexdigest()


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def document_bytes(value: object) -> bytes:
    """A committed generated artifact: readable, sorted, newline-terminated."""
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False)
            + "\n").encode("utf-8")


def authored_bytes(value: object) -> bytes:
    """An amended authored file: key order preserved, newline-terminated."""
    return (json.dumps(value, indent=2, ensure_ascii=False)
            + "\n").encode("utf-8")


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------


def is_secret_path(relative: str) -> bool:
    for component in relative.split("/"):
        if component in SECRET_MARKERS:
            return True
        if any(component.startswith(prefix) for prefix in SECRET_PREFIXES):
            return True
    return False


def matches_group(relative: str, group: str, match: str) -> bool:
    if match == "exact":
        return relative == group
    if match == "prefix":
        return relative == group or relative.startswith(group + "/")
    raise ValueError(f"unknown match kind: {match!r}")


def classify(relative: str) -> tuple[str, str, str, str | None] | None:
    """The first matching rule as `(group, class, action, target)`, or None."""
    for group, match, lifecycle_class, action, target in CLASSIFICATION_RULES:
        if matches_group(relative, group, match):
            return (group, lifecycle_class, action, target)
    return None


def is_agent_path(relative: str) -> bool:
    """Whether an unclassified path still has to be classified before adoption.

    Only paths inside the platform's own tree and the native agent surfaces
    qualify; ordinary repository source is not a candidate at all.
    """
    if matches_group(relative, ".agents", "prefix"):
        return True
    return any(matches_group(relative, native, "prefix")
               for native in NATIVE_AGENT_PATHS)


def contained_path(root: Path, relative: str) -> Path | None:
    """The resolved path of `relative`, or None when it escapes `root`.

    Every discovered path is resolved and checked before it is opened, so a
    symlink out of the checkout — into a sibling repository or anywhere else —
    is recorded rather than followed.
    """
    try:
        resolved = (root / relative).resolve(strict=True)
        anchor = root.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if resolved == anchor or anchor in resolved.parents:
        return resolved
    return None


def read_bytes_bounded(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except (OSError, RuntimeError):
        return None


# --------------------------------------------------------------------------
# Child processes
# --------------------------------------------------------------------------


def run_git(root: Path, *args: str) -> tuple[int, bytes]:
    try:
        proc = subprocess.run(["git", "-C", str(root), *args],
                              capture_output=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        raise refuse("adopt_failure", "adopt.git.unavailable", "",
                     "git could not be started") from None
    return proc.returncode, proc.stdout


def git_or_fail(root: Path, *args: str) -> bytes:
    code, out = run_git(root, *args)
    if code != 0:
        raise refuse("adopt_failure", "adopt.git.failed", "",
                     "a git inspection command did not succeed")
    return out


def split_nul(data: bytes) -> list[str]:
    return [chunk.decode("utf-8", "surrogateescape")
            for chunk in data.split(b"\0") if chunk]


def resolver_path() -> Path:
    """The one absolute path the resolver is consumed at (D26).

    No `PATH` search: a stale generation earlier on `PATH` must never be able
    to answer a contract question on this platform's behalf.
    """
    return Path(os.environ["HOME"]) / ".agents" / "bin" / "resolve-project"


def run_resolver(root: Path, *args: str) -> tuple[int, object]:
    """The resolver's exit code and parsed JSON, or a refusal.

    Exit 0 carries the documented success document and exit 2 the documented
    D12 error object; any other exit, or output that will not parse, is an
    adoption failure rather than a guess.
    """
    binary = resolver_path()
    try:
        proc = subprocess.run([str(binary), *args, "--repo-root", str(root)],
                              capture_output=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        raise refuse("adopt_failure", "adopt.resolver.unavailable", "",
                     "the installed resolver could not be started") from None
    if proc.returncode not in (0, 2):
        raise refuse("adopt_failure", "adopt.resolver.unexpected_exit", "",
                     "the resolver exited outside its documented codes")
    try:
        payload = json.loads(proc.stdout)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise refuse("adopt_failure", "adopt.resolver.unparseable", "",
                     "the resolver did not print parseable JSON") from None
    return proc.returncode, payload


def resolver_error_code(payload: object) -> str | None:
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        code = payload["error"].get("code")
        return code if isinstance(code, str) else None
    return None


def resolver_repair_id(payload: object) -> str | None:
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        repair = payload["error"].get("repair_id")
        return repair if isinstance(repair, str) else None
    return None


def resolver_violation_pointers(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return []
    error = payload.get("error")
    if not isinstance(error, dict) or not isinstance(error.get("violations"),
                                                     list):
        return []
    return [v.get("pointer") for v in error["violations"]
            if isinstance(v, dict) and isinstance(v.get("pointer"), str)]


# --------------------------------------------------------------------------
# Inspection
#
# The whole boundary of R4.2, and nothing wider: tracked object ids, a closed
# list of targeted ignored paths, two metadata-only trees, registered worktree
# names, and untracked files overlapping an inspected source or a planned
# destination.
# --------------------------------------------------------------------------


def tracked_inventory(root: Path) -> list[tuple[str, str]]:
    """Every tracked path with its git object id, from `git ls-files -s -z`."""
    inventory = []
    for record in split_nul(git_or_fail(root, "ls-files", "-s", "-z")):
        head, _, path = record.partition("\t")
        fields = head.split()
        if len(fields) < 2 or not path:
            raise refuse("adopt_failure", "adopt.git.unparseable_index", "",
                         "a tracked index record could not be read")
        inventory.append((path, fields[1]))
    return sorted(inventory)


def targeted_ignored(root: Path, targets: tuple[str, ...]) -> list[str]:
    """Ignored paths under an explicit target list — never a bare tree walk."""
    if not targets:
        return []
    return sorted(split_nul(git_or_fail(
        root, "ls-files", "--others", "--ignored", "--exclude-standard", "-z",
        "--", *targets)))


def untracked_under(root: Path, targets: list[str]) -> list[str]:
    if not targets:
        return []
    return sorted(split_nul(git_or_fail(
        root, "ls-files", "--others", "--exclude-standard", "-z", "--",
        *targets)))


def registered_worktrees(root: Path) -> list[str]:
    """The names of every registered worktree other than the target itself.

    Names only (R4.2): no worktree is opened, and the absolute paths git
    reports are reduced to their final component so that the inspection stays
    a property of the repository rather than of the machine.
    """
    out = git_or_fail(root, "worktree", "list", "--porcelain")
    anchor = root.resolve()
    names = []
    for line in out.decode("utf-8", "surrogateescape").splitlines():
        if not line.startswith("worktree "):
            continue
        path = Path(line[len("worktree "):])
        try:
            if path.resolve() == anchor:
                continue
        except (OSError, RuntimeError):
            pass
        names.append(path.name)
    return sorted(names)


def head_revision(root: Path) -> str:
    code, out = run_git(root, "rev-parse", "HEAD")
    if code != 0:
        raise refuse("adopt_failure", "adopt.repository.unborn_head", "",
                     "the target repository has no commit to plan against")
    return out.decode("ascii", "strict").strip()


def require_repository(repo_root: str) -> Path:
    """The target root, or `not_a_repository`.

    The named directory must be the top level of a git working tree: a
    subdirectory of one is refused, so nothing outside the root a caller named
    can be inspected or planned against.
    """
    root = Path(repo_root)
    if not root.is_dir():
        raise refuse("not_a_repository", "adopt.repository.missing", "",
                     "the named repository root is not a directory")
    root = root.resolve()
    code, out = run_git(root, "rev-parse", "--show-toplevel")
    if code != 0:
        raise refuse("not_a_repository", "adopt.repository.not_git", "",
                     "the named directory is not a git repository")
    toplevel = Path(out.decode("utf-8", "surrogateescape").strip())
    try:
        same = toplevel.resolve() == root
    except (OSError, RuntimeError):
        same = False
    if not same:
        raise refuse("not_a_repository", "adopt.repository.not_toplevel", "",
                     "the named directory is not the top level of its "
                     "repository")
    return root


class Inventory:
    """Everything the bounded inspection saw, and nothing else."""

    def __init__(self, tracked: list[tuple[str, str]],
                 ignored: list[str], metadata: dict[str, int],
                 worktrees: list[str], base_revision: str) -> None:
        self.tracked = tracked
        self.ignored = ignored
        self.metadata = metadata
        self.worktrees = worktrees
        self.base_revision = base_revision


def inspect_repository(root: Path) -> Inventory:
    """The single inspection entry point (R4.2).

    Untracked overlap is deliberately not gathered here: its target list is a
    function of the classification this inventory feeds, so it is collected
    once the candidate groups and their destinations are known.
    """
    metadata: dict[str, int] = {}
    for target in METADATA_ONLY_IGNORED:
        found = targeted_ignored(root, (target,))
        if found:
            metadata[target] = len(found)
    return Inventory(
        tracked=tracked_inventory(root),
        ignored=targeted_ignored(root, TARGETED_IGNORED),
        metadata=metadata,
        worktrees=registered_worktrees(root),
        base_revision=head_revision(root),
    )


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------


def evidence_entry(path: str, provenance: str, lifecycle_class: str,
                   action: str, target: str | None, count: int,
                   fingerprint: str | None, note: str | None) -> dict:
    if provenance not in PROVENANCES:
        raise ValueError(f"unknown provenance: {provenance!r}")
    if lifecycle_class not in LIFECYCLE_CLASSES:
        raise ValueError(f"unknown lifecycle class: {lifecycle_class!r}")
    if action not in ACTIONS:
        raise ValueError(f"unknown adoption action: {action!r}")
    return {
        "path": path,
        "provenance": provenance,
        "lifecycle_class": lifecycle_class,
        "action": action,
        "target": target,
        "count": count,
        "fingerprint": fingerprint,
        "note": note,
    }


def destination_for(group: str, target: str, relative: str) -> str:
    """Where one member of a relocating group lands under `target`."""
    if relative == group:
        return target
    return target + relative[len(group):]


class Candidates:
    """The classified inspection: evidence entries plus the planned moves."""

    def __init__(self) -> None:
        self.entries: list[dict] = []
        self.moves: list[tuple[str, str]] = []
        self.tracked_paths: set[str] = set()
        self.groups: dict[str, dict] = {}


def classify_inventory(root: Path, inventory: Inventory) -> Candidates:
    found = Candidates()
    found.tracked_paths = {path for path, _ in inventory.tracked}

    # Tracked candidates group by classification rule; a secret-shaped one is
    # lifted out of its group and recorded by name alone.
    grouped: dict[str, list[tuple[str, str]]] = {}
    for path, object_id in inventory.tracked:
        rule = classify(path)
        if rule is None:
            if is_agent_path(path):
                found.entries.append(evidence_entry(
                    path, "tracked", "unclassified", "needs-decision", None, 1,
                    object_hash(object_id), NOTES["unclassified"]))
            continue
        if is_secret_path(path):
            found.entries.append(evidence_entry(
                path, "tracked", "secret-shaped", "retain-product", None, 1,
                None, NOTES["secret-shaped"]))
            continue
        grouped.setdefault(rule[0], []).append((path, object_id))

    for group, _, lifecycle_class, action, target in CLASSIFICATION_RULES:
        members = grouped.get(group)
        if not members:
            continue
        found.groups[group] = {"action": action, "target": target,
                               "members": members}
        found.entries.append(evidence_entry(
            group, "tracked", lifecycle_class, action, target, len(members),
            group_fingerprint(members), None))
        if action_relocates(action) and target is not None and target != group:
            for path, _ in members:
                found.moves.append((path, destination_for(group, target, path)))

    # Targeted ignored paths are recorded one file at a time, because their
    # fingerprint is over the file's own bytes.
    for path in inventory.ignored:
        rule = classify(path)
        lifecycle_class = rule[1] if rule else "unclassified"
        action = rule[2] if rule else "needs-decision"
        if rule is None and not is_agent_path(path):
            continue
        if is_secret_path(path):
            found.entries.append(evidence_entry(
                path, "targeted-ignored", "secret-shaped", "retain-product",
                None, 1, None, NOTES["secret-shaped"]))
            continue
        resolved = contained_path(root, path)
        if resolved is not None and resolved.is_dir():
            found.entries.append(evidence_entry(
                path, "targeted-ignored-metadata-only", "runtime-residue",
                "retain-product", None, 1, None, NOTES["metadata-only"]))
            continue
        data = read_bytes_bounded(resolved) if resolved is not None else None
        if data is None:
            found.entries.append(evidence_entry(
                path, "targeted-ignored", "unclassified", "needs-decision",
                None, 1, None, NOTES["escaping-symlink"]))
            continue
        found.entries.append(evidence_entry(
            path, "targeted-ignored", lifecycle_class,
            "retain-product" if action_relocates(action) else action,
            None, 1, sha256_hash(data),
            NOTES["unclassified"] if rule is None else None))

    for path, count in sorted(inventory.metadata.items()):
        found.entries.append(evidence_entry(
            path, "targeted-ignored-metadata-only", "runtime-residue",
            "retain-product", None, count, None, NOTES["metadata-only"]))

    if inventory.worktrees:
        found.entries.append(evidence_entry(
            ".git/worktrees", "git-worktree-metadata-only", "runtime-residue",
            "retain-product", None, len(inventory.worktrees), None,
            NOTES["git-worktree"]))
    return found


def overlap_targets(found: Candidates) -> list[str]:
    """The paths an untracked file must not sit inside.

    Exactly the inspected sources adoption would move or regenerate, plus every
    destination it would write into: the gate is about work colliding with
    uncommitted content, not about a checkout being pristine.
    """
    targets = {".agents"}
    for group, info in found.groups.items():
        if info["action"] in ("move-canonical", "generate-projection"):
            targets.add(group)
        if info["target"]:
            targets.add(info["target"])
    targets.update((MIGRATION_MAP_DIR, EVIDENCE_RECORD_DIR))
    return sorted(targets)


# --------------------------------------------------------------------------
# Project identity (D35)
# --------------------------------------------------------------------------


def normalize_remote_url(url: str) -> str | None:
    """`owner/repo` for the two documented remote spellings, else None.

    A URL matching neither form is deliberately not normalized: guessing an
    identity from an unrecognised spelling is exactly the inference the
    contract forbids, and the caller turns None into an open question.
    """
    value = url.strip()
    if not value:
        return None
    if value.endswith(".git"):
        value = value[:-len(".git")]
    if value.startswith("git@"):
        _, separator, suffix = value.partition(":")
        if not separator or not suffix:
            return None
        segments = [part for part in suffix.split("/") if part]
        return "/".join(segments[-2:]) if len(segments) >= 2 else None
    if "://" in value:
        _, _, rest = value.partition("://")
        segments = [part for part in rest.split("/") if part]
        # host plus owner plus repo at the very least.
        return "/".join(segments[-2:]) if len(segments) >= 3 else None
    return None


def remote_urls(root: Path) -> list[str]:
    """The distinct fetch URLs of every configured remote, by remote name."""
    out = git_or_fail(root, "remote", "-v")
    urls: dict[str, str] = {}
    for line in out.decode("utf-8", "surrogateescape").splitlines():
        fields = line.split()
        if len(fields) >= 2:
            urls.setdefault(fields[0], fields[1])
    return [urls[name] for name in sorted(urls)]


def registry_collision(project_id: str, root: Path) -> bool:
    """Whether the fleet already holds this id at a different root (D35)."""
    try:
        entries = agent_platform.read_registry()
    except agent_platform.PlatformManifestError as error:
        raise AdoptError("adopt_failure", "adopt.registry.invalid",
                         error.violations) from None
    for entry in entries:
        if (entry["project_id"] == project_id
                and Path(entry["root"]).resolve() != root):
            return True
    return False


def derive_identity(root: Path, contract_id: str | None) -> tuple[
        str | None, list[dict], list[dict]]:
    """`(project_id, recommended, open)` for this repository.

    The contract answers whenever it can; otherwise exactly one remote yields a
    recommendation ratified by approving the ready plan id (D16), and every
    other shape yields exactly one open question that keeps the plan `draft`.
    """
    if contract_id is not None:
        return contract_id, [], []
    question_id = QUESTION_IDS[0]
    urls = remote_urls(root)
    value = normalize_remote_url(urls[0]) if len(urls) == 1 else None
    basis = f"derived from {len(urls)} configured git remote(s)"
    if value is not None and not registry_collision(value, root):
        return value, [{"id": question_id, "value": value, "basis": basis}], []
    return None, [], [{
        "id": question_id,
        "value": value,
        "basis": basis,
        "impact": question_impact(question_id),
        "recommendation": question_recommendation(question_id),
    }]


# --------------------------------------------------------------------------
# The `.gitignore` amendment
# --------------------------------------------------------------------------


def amend_gitignore_text(text: str) -> str:
    """`text` without the `.agents/runtime/` pattern, and without a comment
    block the removal would orphan.

    The only heuristic in this module, and deliberately a narrow one: the
    pattern line is matched exactly, the comment block immediately above it is
    removed only when nothing between the removal point and the next blank line
    or the end of the file still needs it, and a blank line doubled by the
    removal is collapsed to one.
    """
    trailing_newline = text.endswith("\n")
    lines = text.split("\n")
    if trailing_newline:
        lines = lines[:-1]
    index = next((position for position, line in enumerate(lines)
                  if line.strip() == RUNTIME_IGNORE_PATTERN), None)
    if index is None:
        return text
    remaining = lines[:index] + lines[index + 1:]

    start = index
    block_start = index
    while block_start > 0 and remaining[block_start - 1].strip().startswith("#"):
        block_start -= 1
    if block_start < index:
        still_needed = False
        for line in remaining[index:]:
            if not line.strip():
                break
            if not line.strip().startswith("#"):
                still_needed = True
                break
        if not still_needed:
            remaining = remaining[:block_start] + remaining[index:]
            start = block_start

    if 0 < start < len(remaining) and not remaining[start - 1].strip() \
            and not remaining[start].strip():
        remaining = remaining[:start] + remaining[start + 1:]
    return "\n".join(remaining) + ("\n" if trailing_newline else "")


# --------------------------------------------------------------------------
# Typed operations
# --------------------------------------------------------------------------


def operation(kind: str, sources: list[str], targets: list[str],
              before: str | None, after: str | None) -> dict:
    if kind not in OPERATION_KINDS:
        raise ValueError(f"unknown operation kind: {kind!r}")
    approval = approval_class_for(kind)
    if approval not in APPROVAL_CLASSES:
        raise ValueError(f"unknown approval class: {approval!r}")
    return {"op": kind, "sources": sources, "targets": targets,
            "before": before, "after": after, "approval_class": approval}


def derived_interval(platform_version: str) -> dict:
    """The interval a freshly amended contract declares.

    The running platform is the floor and its next major the ceiling: the one
    interval that is legal under R2.2 (a strict, non-pin range) and that admits
    exactly the compatibility the current generation promises.
    """
    parsed = agent_platform.parse_semver(platform_version)
    if parsed is None:
        raise refuse("adopt_failure", "adopt.manifest.invalid",
                     "/platform_version",
                     "the manifest's platform version is not strict SemVer")
    return {"min_inclusive": platform_version,
            "max_exclusive": f"{parsed[0] + 1}.0.0"}


def amended_contract(source: dict, interval: dict,
                     found: Candidates) -> dict:
    """The contract this adoption would write: `platform` plus moved bindings.

    Nothing else is touched. The amendment is confined to the one member the
    platform requires and the path bindings whose authored values name a tree
    this plan relocates, so a contract cannot acquire policy it did not author.
    """
    amended = json.loads(json.dumps(source))
    if "platform" not in amended:
        amended["platform"] = interval
    relocations = {group: info["target"] for group, info in found.groups.items()
                   if info["action"] == "move-canonical" and info["target"]
                   and info["target"] != group}
    bindings = amended.get("bindings")
    if not isinstance(bindings, dict):
        return amended
    paths = bindings.get("paths")
    if not isinstance(paths, dict):
        return amended
    artifacts = paths.get("artifacts")
    if isinstance(artifacts, dict):
        for key in ("specs", "plans"):
            if artifacts.get(key) in relocations:
                artifacts[key] = relocations[artifacts[key]]
    rejections = paths.get("rejections")
    if isinstance(rejections, list):
        paths["rejections"] = [relocations.get(value, value)
                               if isinstance(value, str) else value
                               for value in rejections]
    return amended


def binding_value(contract: dict, route: tuple) -> object:
    paths = contract.get("bindings", {}).get("paths", {})
    if route[0] == "artifacts":
        artifacts = paths.get("artifacts")
        return artifacts.get(route[1]) if isinstance(artifacts, dict) else None
    values = paths.get(route[0])
    if isinstance(values, list) and len(values) > route[1]:
        return values[route[1]]
    return None


def legacy_binding_operations(root: Path, contract: dict) -> list[dict]:
    """The living-reference rewrites (D30) — one per member of the closed
    tuple, and never a path outside it.

    Each rewrite merges the three fixed keys into the existing JSON and leaves
    every other key exactly as authored; a file that is absent, unreadable, not
    a JSON object, or already in agreement produces no operation at all.
    """
    operations: list[dict] = []
    for target in LEGACY_BINDING_CONFIGS:
        resolved = contained_path(root, target)
        if resolved is None or not resolved.is_file():
            continue
        current = read_bytes_bounded(resolved)
        if current is None:
            continue
        try:
            config = json.loads(current)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(config, dict):
            continue
        for key, route in LEGACY_BINDING_KEYS:
            value = binding_value(contract, route)
            if isinstance(value, str):
                config[key] = value
        after = authored_bytes(config)
        if after == current:
            continue
        operations.append(operation("write-file", [target], [target],
                                    sha256_hash(current), sha256_hash(after)))
    return operations


def build_operations(root: Path, found: Candidates, manifest: dict,
                     contract_source: dict | None,
                     plan_id: str) -> tuple[list[dict], list[dict]]:
    """The typed operations either side of the adoption's own bookkeeping.

    Returned as `(head, tail)` rather than one list because
    the migration map and the evidence record sit between them and cannot be
    built until the outcome is known — and the outcome is decided by whether
    this list has anything in it. The apply order is the concatenation: the
    contract amendment, the relocations sorted by old path, the runtime
    sentinel and the `.gitignore` amendment, then the two records, then the
    living-reference rewrite and finally the projection regenerations.
    """
    operations: list[dict] = []

    interval = derived_interval(manifest["platform_version"])
    amended = (amended_contract(contract_source, interval, found)
               if contract_source is not None else None)
    if amended is not None:
        current = read_bytes_bounded(root / CONTRACT_FILENAME)
        after = authored_bytes(amended)
        if current is not None and after != current:
            operations.append(operation(
                "write-file", [CONTRACT_FILENAME], [CONTRACT_FILENAME],
                sha256_hash(current), sha256_hash(after)))

    object_ids = {path: object_id for path, object_id in
                  [(p, o) for info in found.groups.values()
                   for p, o in info["members"]]}
    for old_path, new_path in sorted(found.moves):
        content = object_hash(object_ids[old_path])
        operations.append(operation("git-mv", [old_path], [new_path],
                                    content, content))

    sentinel = read_bytes_bounded(root / RUNTIME_SENTINEL)
    if sentinel != RUNTIME_SENTINEL_BYTES:
        operations.append(operation(
            "write-file", [RUNTIME_SENTINEL], [RUNTIME_SENTINEL],
            None if sentinel is None else sha256_hash(sentinel),
            sha256_hash(RUNTIME_SENTINEL_BYTES)))

    ignore_bytes = read_bytes_bounded(root / GITIGNORE)
    if ignore_bytes is not None:
        try:
            amended_ignore = amend_gitignore_text(
                ignore_bytes.decode("utf-8")).encode("utf-8")
        except UnicodeDecodeError:
            amended_ignore = ignore_bytes
        if amended_ignore != ignore_bytes:
            operations.append(operation(
                "write-file", [GITIGNORE], [GITIGNORE],
                sha256_hash(ignore_bytes), sha256_hash(amended_ignore)))

    tail: list[dict] = []
    if amended is not None:
        tail.extend(legacy_binding_operations(root, amended))

    projections = (amended or {}).get("projections")
    if isinstance(projections, list):
        rows = [entry for entry in projections if isinstance(entry, dict)
                and isinstance(entry.get("target"), str)
                and isinstance(entry.get("source"), str)]
        for entry in sorted(rows, key=lambda row: row["target"]):
            current = read_bytes_bounded(root / entry["target"])
            tail.append(operation(
                "regenerate-projection", [entry["source"]], [entry["target"]],
                None if current is None else sha256_hash(current),
                # The rendered bytes are the resolver's to produce, so the
                # plan states the source it regenerates from rather than
                # predicting the output it has not asked for yet.
                None))
    return operations, tail


def adoption_records(plan_id: str) -> dict:
    """Where this adoption's own two committed records live."""
    digest = plan_id.split(":", 1)[1]
    return {"migration_map": f"{MIGRATION_MAP_DIR}/{digest}.json",
            "evidence_record": f"{EVIDENCE_RECORD_DIR}/{digest}.json"}


def bookkeeping_operations(found: Candidates, plan_id: str, outcome: str,
                           base_revision: str, platform_block: dict,
                           decisions: dict,
                           ready_gates: list[dict]) -> list[dict]:
    """The path-migration map and the adoption evidence record.

    Both are named by the plan id and neither exists yet, so each is a
    `write-file` whose `before` is null; the record carries the outcome, which
    is why these two are built after routing rather than beside the moves.
    """
    records = adoption_records(plan_id)
    map_bytes = document_bytes({
        "schema_version": 1,
        "migration_id": plan_id,
        "moves": [{"old_path": old, "new_path": new}
                  for old, new in sorted(found.moves)],
    })
    record_bytes = document_bytes({
        "schema_version": 1,
        "plan_id": plan_id,
        "outcome": outcome,
        "base_revision": base_revision,
        "platform": platform_block,
        "decisions_accepted": decisions["recommended"] + decisions["answered"],
        # One row per inspected group: what it was fingerprinted as, and the
        # canonical home it ends up in (null when adoption leaves it alone).
        "sources": [{"path": entry["path"], "before": entry["fingerprint"],
                     "after": entry["target"]} for entry in found.entries],
        "checks": [{"id": gate["id"], "status": gate["status"]}
                   for gate in ready_gates],
        "path_migration_map": records["migration_map"],
    })
    return [
        operation("write-file", [records["migration_map"]],
                  [records["migration_map"]], None, sha256_hash(map_bytes)),
        operation("write-file", [records["evidence_record"]],
                  [records["evidence_record"]], None,
                  sha256_hash(record_bytes)),
    ]


# --------------------------------------------------------------------------
# Outcome routing (D10)
# --------------------------------------------------------------------------


def select_forward_step(manifest: dict, schema_version: object) -> dict | None:
    """The unique `migrations` record stepping forward from `schema_version`.

    Never a nearest match and never a guess (D36): more than one candidate is a
    refusal, and the absent case is returned as None for the caller to route.
    """
    matches = [entry for entry in manifest["migrations"]
               if isinstance(entry, dict)
               and entry.get("from_schema") == schema_version]
    if len(matches) > 1:
        raise refuse("adopt_failure", "adopt.manifest.forward_step_ambiguous",
                     "/migrations",
                     "more than one migration steps forward from the "
                     "project's declared schema")
    return matches[0] if matches else None


def route_outcome(manifest: dict, contract_source: dict | None,
                  contract_resolves: bool, agent_surface: bool,
                  pending_work: bool) -> tuple[str, str | None]:
    """The first matching routing rule, as `(outcome, forward_migration_id)`.

    Written as an ordered evaluation rather than a lookup so that the ordering
    is the thing a reader checks.
    """
    # 1. Nothing to adopt from and nothing declared.
    if contract_source is None and not agent_surface:
        return "bootstrap", None
    # 2. Legacy surface without a contract.
    if contract_source is None:
        return "reconcile", None
    versions = manifest["project_schema_versions"]
    declared = contract_source.get("schema_version")
    # 3. A supported schema that is not the highest supported one.
    if declared in versions and declared != versions[-1]:
        forward = select_forward_step(manifest, declared)
        if forward is None:
            raise refuse("adopt_failure",
                         "adopt.manifest.forward_step_missing", "/migrations",
                         "no migration steps forward from the project's "
                         "declared schema")
        return "migration_required", forward["id"]
    # 4. A schema this platform does not support at all.
    if declared not in versions:
        forward = select_forward_step(manifest, declared)
        if forward is not None:
            return "migration_required", forward["id"]
        return "repair_required", None
    # 5. The current schema with adoption work outstanding.
    if pending_work:
        return "reconcile", None
    # 6. The current schema, valid, conformant, nothing left.
    if contract_resolves:
        return "no_change", None
    # 7. The current schema, invalid or drifted, with no legacy surface.
    return "repair_required", None


# --------------------------------------------------------------------------
# Ready gates
# --------------------------------------------------------------------------


def evaluate_ready_gates(root: Path, found: Candidates,
                         contract_source: dict | None,
                         contract_resolves: bool,
                         unfixable_pointers: list[str],
                         untracked: list[str],
                         decisions: dict) -> list[dict]:
    """One entry per gate, in declaration order. All must pass for `ready`."""
    gates: list[dict] = []

    if contract_source is None:
        gates.append(gate_entry(READY_GATES[0], "failed",
                                "adopt.contract.absent"))
    elif contract_resolves or not unfixable_pointers:
        gates.append(gate_entry(READY_GATES[0], "passed", None))
    else:
        gates.append(gate_entry(READY_GATES[0], "failed",
                                "adopt.contract.unfixable_violations"))

    undecided = [entry for entry in found.entries
                 if entry["action"] == "needs-decision"]
    gates.append(gate_entry(
        READY_GATES[1], "failed" if undecided else "passed",
        "adopt.candidate.unclassified" if undecided else None))

    gates.append(gate_entry(
        READY_GATES[2], "failed" if decisions["open"] else "passed",
        "adopt.decisions.open" if decisions["open"] else None))

    gates.append(gate_entry(
        READY_GATES[3], "failed" if untracked else "passed",
        "adopt.worktree.untracked_overlap" if untracked else None))

    occupied = [new for _, new in found.moves
                if (root / new).exists()]
    gates.append(gate_entry(
        READY_GATES[4], "failed" if occupied else "passed",
        "adopt.destination.occupied" if occupied else None))

    untracked_sources = [old for old, _ in found.moves
                         if old not in found.tracked_paths]
    gates.append(gate_entry(
        READY_GATES[5], "failed" if untracked_sources else "passed",
        "adopt.move.source_untracked" if untracked_sources else None))

    secret_moves = [path for pair in found.moves for path in pair
                    if is_secret_path(path)]
    gates.append(gate_entry(
        READY_GATES[6], "failed" if secret_moves else "passed",
        "adopt.move.secret_shaped" if secret_moves else None))
    return gates


GATE_MESSAGES = {
    "contract-valid-after-amendment":
        "the contract is absent, or carries violations the planned amendment "
        "does not address",
    "no-needs-decision": "a discovered candidate carries no lifecycle class",
    "no-open-decisions": "an open question has no answer",
    "no-untracked-overlap":
        "an untracked file sits inside an inspected source or a planned "
        "destination",
    "no-existing-destination": "a planned destination already exists",
    "move-sources-tracked": "a planned move source is not tracked",
    "no-secret-path-in-moves":
        "a secret-shaped path is a planned move source or target",
}


def blockers_for(gates: list[dict]) -> list[dict]:
    return sorted(
        ({"id": gate["id"], "message": GATE_MESSAGES[gate["id"]]}
         for gate in gates if gate["status"] == "failed"),
        key=lambda item: item["id"])


# --------------------------------------------------------------------------
# The plan document
# --------------------------------------------------------------------------


def compute_plan_id(project_id: str | None, base_revision: str,
                    platform_block: dict, evidence: list[dict],
                    answered: list[dict]) -> str:
    """D15's content address over exactly six inputs.

    The manifest's `migrations` array is deliberately *not* one of them (D36):
    it can only route toward `migration_required` or `repair_required`, and
    both produce `state: not_applicable` with `changes: []`, so no appliable
    plan's meaning can turn on it. Timestamps, prose, the absolute checkout
    path and the human view are outside it for the same reason — the id is a
    property of the repository, not of the machine that inspected it.
    """
    source = {
        "adopt_schema_version": ADOPT_SCHEMA_VERSION,
        "project_id": project_id,
        "base_revision": base_revision,
        "platform": platform_block,
        "evidence": evidence,
        "decisions_answered": answered,
    }
    return "sha256:" + hashlib.sha256(canonical_json(source)).hexdigest()


def next_command_for(state: str, outcome: str, root: Path, plan_id: str,
                     forward_migration: str | None,
                     repair_id: str | None) -> str | None:
    """What the caller does next, or None while the plan is still `draft`."""
    if outcome == "no_change":
        return f"adopt-project verify --register --repo-root {root}"
    if outcome == "migration_required":
        return f"migrate {forward_migration}"
    if outcome == "repair_required":
        return f"repair {repair_id or 'adopt.schema.no_forward_step'}"
    if plan_state_is_terminal(state):
        raise ValueError(f"appliable outcome in a terminal state: {outcome!r}")
    if state == "ready":
        return f"adopt-project apply --plan-id {plan_id}"
    return None


def command_plan(args: argparse.Namespace) -> int:
    manifest = require_manifest()
    root = require_repository(args.repo_root)

    inventory = inspect_repository(root)
    found = classify_inventory(root, inventory)
    untracked = untracked_under(root, overlap_targets(found))
    for path in untracked:
        found.entries.append(evidence_entry(
            path, "untracked-explicit-paths", "untracked-overlap",
            "retain-product", None, 1, None, NOTES["untracked"]))
    evidence = sorted(found.entries,
                      key=lambda entry: (entry["path"], entry["provenance"]))

    contract_source = load_contract_source(root)
    exit_code, payload = run_resolver(root, "resolve")
    contract_resolves = exit_code == 0
    repair_id = None if contract_resolves else resolver_repair_id(payload)
    projections_drift = (
        not contract_resolves
        and resolver_error_code(payload) == "invalid_projection")
    # What the planned amendment can still put right. The `platform` member is
    # the amendment's own reach; a drifted projection is separately repaired by
    # the regeneration operations this plan already carries, so neither is a
    # violation that keeps the plan out of `ready`.
    unfixable = [] if projections_drift else [
        pointer for pointer in resolver_violation_pointers(payload)
        if not pointer.startswith("/platform")]

    contract_id = None
    if contract_resolves and isinstance(payload, dict):
        project = payload.get("project")
        if isinstance(project, dict) and isinstance(project.get("id"), str):
            contract_id = project["id"]
    project_id, recommended, open_questions = derive_identity(root, contract_id)
    decisions = {"recommended": recommended, "answered": [],
                 "open": open_questions}

    platform_block = {
        "platform_version": manifest["platform_version"],
        "project_schema_versions": list(manifest["project_schema_versions"]),
        "resolved_schema_version": manifest["resolved_schema_version"],
    }
    plan_id = compute_plan_id(project_id, inventory.base_revision,
                              platform_block, evidence, decisions["answered"])

    ready_gates = evaluate_ready_gates(
        root, found, contract_source, contract_resolves, unfixable, untracked,
        decisions)
    head, tail = build_operations(root, found, manifest, contract_source,
                                  plan_id)

    agent_surface = any(
        entry["lifecycle_class"] != "runtime-residue"
        and entry["provenance"] != "untracked-explicit-paths"
        for entry in evidence)
    # What counts as work left to do (routing rules 5 and 6). A projection
    # regeneration is an idempotent safety re-run that a conformant checkout
    # would perform to no effect, so counting it as work would make `no_change`
    # unreachable; the two adoption records are excluded for the same reason,
    # by being built only after this decision.
    substantive = [op for op in head + tail
                   if op["op"] != "regenerate-projection"]
    pending_work = bool(substantive) or projections_drift or any(
        entry["action"] == "needs-decision" for entry in evidence)

    outcome, forward_migration = route_outcome(
        manifest, contract_source, contract_resolves, agent_surface,
        pending_work)

    if outcome_is_appliable(outcome):
        state = "ready" if all(gate["status"] == "passed"
                               for gate in ready_gates) else "draft"
        blockers = blockers_for(ready_gates)
        records = adoption_records(plan_id)
        changes = head + bookkeeping_operations(
            found, plan_id, outcome, inventory.base_revision, platform_block,
            decisions, ready_gates) + tail
        evidence_record = records["evidence_record"]
        migration_map = records["migration_map"]
    else:
        state = "not_applicable"
        blockers = []
        changes = []
        ready_gates = [gate_entry(gate, "not_run", None)
                       for gate in READY_GATES]
        evidence_record = None
        migration_map = None

    # Both values are produced by an exhaustive dispatch above, so this is
    # defence in depth: a member added to either closed tuple without a home
    # in the routing or state logic crashes here rather than reaching a caller.
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown adoption outcome: {outcome!r}")
    if state not in PLAN_STATES:
        raise ValueError(f"unknown plan state: {state!r}")

    plan_path = store_plan_path(plan_id)
    document = {
        "schema_version": ADOPT_SCHEMA_VERSION,
        "plan": {
            "state": state,
            "outcome": outcome,
            "project_id": project_id,
            "base_revision": inventory.base_revision,
            "platform": platform_block,
            "input_digest": plan_id,
            "plan_id": plan_id,
            "blockers": blockers,
        },
        "evidence": evidence,
        "decisions": decisions,
        "changes": changes,
        "verification": {
            "ready_gates": ready_gates,
            "commit_gates": [gate_entry(gate, "not_run", None)
                             for gate in COMMIT_GATES],
        },
        "handoff": {
            "state": state,
            "repo_root": str(root),
            "plan_path": str(plan_path),
            "next_command": next_command_for(state, outcome, root, plan_id,
                                             forward_migration, repair_id),
            "evidence_record": evidence_record,
            "migration_map": migration_map,
        },
    }

    agent_platform.ensure_directory(plan_path.parent)
    agent_platform.write_atomically(plan_path, canonical_json(document) + b"\n")
    if args.format == "human":
        return emit_human(document)
    return emit_json(document)


def store_plan_path(plan_id: str) -> Path:
    return (agent_platform.state_root() / "adopt" / "plans"
            / (plan_id.split(":", 1)[1] + ".json"))


def load_contract_source(root: Path) -> dict | None:
    """The authored contract as JSON, or None when there is none to amend.

    This is the one place `adopt-project` reads `.agents/project.json` itself,
    because amending that file is what adoption *is*; its validity remains the
    resolver's verdict alone (D26).
    """
    data = read_bytes_bounded(root / CONTRACT_FILENAME)
    if data is None:
        return None
    try:
        source = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return source if isinstance(source, dict) else None


def emit_human(document: dict) -> int:
    """A bounded semantic view. What is stored is unchanged (R4.8)."""
    plan = document["plan"]
    lines = [
        f"outcome: {plan['outcome']}",
        f"state:   {plan['state']}",
        f"project: {plan['project_id']}",
        f"base:    {plan['base_revision']}",
        f"plan id: {plan['plan_id']}",
        f"evidence: {len(document['evidence'])} entries",
        f"changes:  {len(document['changes'])} operations",
    ]
    for entry in document["decisions"]["recommended"]:
        lines.append(f"recommended {entry['id']}: {entry['value']}")
    for entry in document["decisions"]["open"]:
        lines.append(f"open {entry['id']}: {entry['recommendation']}")
    for blocker in plan["blockers"]:
        lines.append(f"blocked by {blocker['id']}: {blocker['message']}")
    lines.append(f"next: {document['handoff']['next_command'] or '(none)'}")
    lines.append(f"stored at {document['handoff']['plan_path']}")
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


def require_manifest() -> dict:
    """The installed manifest, before the target is touched.

    A broken platform installation is an adoption failure with a stable repair
    id: `adopt-project` has no `resolver_failure` code (D20), and a manifest
    that will not load is never replaced by an assumed version.
    """
    try:
        manifest, _ = agent_platform.load_manifest()
    except agent_platform.PlatformManifestError as error:
        raise AdoptError("adopt_failure", "adopt.manifest.invalid",
                         error.violations) from None
    return manifest


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="adopt-project",
        description="Plan a repository's adoption into the agent platform.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser(
        "plan", help="inspect a repository and emit its adoption plan")
    plan.add_argument("--repo-root", required=True,
                      help="the top level of the repository to inspect")
    plan.add_argument("--format", choices=("json", "human"), default="json",
                      help="the view printed on stdout; the stored document "
                           "is the same either way")
    return parser


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "plan":
        return command_plan(args)
    raise ValueError(f"unknown subcommand: {args.command!r}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not bootstrap_platform_library():
        return emit_error(
            "adopt_failure",
            PLATFORM_LIBRARY_REPAIR_ID,
            [{
                "pointer": "",
                "message": (
                    "the shared platform library was not found at "
                    "~/.agents/lib/python/agent_platform.py"
                ),
            }],
        )
    try:
        return dispatch(args)
    except AdoptError as error:
        return emit_error(error.code, error.repair_id, error.violations)
    except Exception:
        # One fixed sentence: refusal bytes stay deterministic and no internal
        # detail — no exception text, no traceback — reaches the caller.
        return emit_error(
            "adopt_failure",
            "adopt.internal",
            [{"pointer": "", "message": "adoption failed unexpectedly"}],
        )


if __name__ == "__main__":
    sys.exit(main())
