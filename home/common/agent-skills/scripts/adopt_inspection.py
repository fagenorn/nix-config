"""The bounded, read-only inspection of an adoption target, and its closed
lifecycle vocabulary.

`adopt-project` owns adoption end to end; this module is the lower half it is
built from — the closed sets every adoption verb dispatches over, the error
contract they refuse through, the content hashes, the path predicates that keep
the inspection inside the target root and away from secret-shaped paths, and
the four bounded git queries that are the whole of R4.2.

It is imported, never run: no `main`, no argparse, and nothing that writes. It
does not import `resolve-project.py` and never will (D26) — the resolver is
reached only as a subprocess, by the entry point.

Installed beside `agent_platform.py` at `$HOME/.agents/lib/python/`, and bound
by the entry point's guarded bootstrap, so an installation missing this module
or one of its members refuses through the same D12 error object as a missing
platform library rather than as an import traceback.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

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

# The closed set of answers `verify` publishes, and the ordered conformance
# checks it publishes them over (R6.4). Every one of the three is a reported
# state on exit 0: `not_conformant` is the answer the operator asked for, not
# a refusal, and exit 2 belongs to `ADOPT_ERROR_CODES` alone.
VERIFY_RESULTS = ("adopted", "adopted_with_blockers", "not_conformant")
VERIFY_CHECKS = (
    "contract-resolves",
    "projections-in-sync",
    "no-unclassified-agent-path",
    "adoption-evidence-record",
    "adoption-commit-derived",
    "path-migration-map",
)

# The adoption evidence record's members, per the spec. A committed file under
# the evidence directory is the adoption record only if it carries all of them
# (D34): the record is discovered rather than named, so its shape is the only
# thing that identifies it.
EVIDENCE_RECORD_MEMBERS = ("schema_version", "plan_id", "outcome",
                           "base_revision", "platform", "decisions_accepted",
                           "sources", "checks", "path_migration_map")

# The path-migration record's members, per #72 and D36. The record the
# evidence names has to be one of these, not merely a file that parses.
MIGRATION_MAP_MEMBERS = ("schema_version", "migration_id", "moves")
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


def verify_check_entry(check_id: str, status: str,
                       detail: str | None) -> dict:
    """One conformance check's outcome, with the reason when it is not passed.

    Both closed sets are asserted here rather than trusted, so a check id or a
    status invented at a call site crashes instead of reaching the operator as
    a plausible row.
    """
    if check_id not in VERIFY_CHECKS:
        raise ValueError(f"unknown verify check: {check_id!r}")
    if status not in GATE_STATUSES:
        raise ValueError(f"unknown gate status: {status!r}")
    return {"id": check_id, "status": status, "detail": detail}


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
# The resolver's answer, read
#
# Pure readers over an already-parsed resolver payload: no subprocess, no
# import of `resolve-project.py` (D26), nothing written. They live here rather
# than beside either caller because `plan` and `verify` read the same refusal
# and this module is the one layer both are built on.
# --------------------------------------------------------------------------


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
# Git, as a child process
#
# The only process this module starts. Every query below is read-only; the
# resolver is not among them, because it is reached by the entry point alone
# and only ever as a subprocess at its absolute installed path (D26).
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


def blob_at_head(root: Path, relative: str) -> bytes | None:
    """The tracked bytes of `relative` at `HEAD`, or None when it is not there.

    Read out of the commit rather than off disk, because every question
    `verify` asks is about the committed state: an untracked working-tree file
    must not be able to answer for a record the history does not carry (D34).
    """
    code, out = run_git(root, "show", f"HEAD:{relative}")
    return out if code == 0 else None


def tracked_evidence_records(root: Path) -> list[str]:
    """Every `.agents/artifacts/evidence/*.json` path in the tree at `HEAD`.

    Listed from the commit, not walked on disk, and one level deep exactly as
    the glob reads: a nested file is not one of the candidates D34 counts.
    """
    out = git_or_fail(root, "ls-tree", "-r", "--name-only", "-z", "HEAD",
                      "--", EVIDENCE_RECORD_DIR)
    prefix = EVIDENCE_RECORD_DIR + "/"
    return sorted(
        path for path in split_nul(out)
        if path.startswith(prefix) and path.endswith(".json")
        and "/" not in path[len(prefix):])


def parses_as_evidence_record(data: bytes | None) -> dict | None:
    """The record `data` holds, or None when it is not one.

    Membership is the whole test: an adoption record is identified by carrying
    every member the spec fixes, because nothing else in the repository names
    it.
    """
    if data is None:
        return None
    try:
        source = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(source, dict) or any(
            member not in source for member in EVIDENCE_RECORD_MEMBERS):
        return None
    return source


def parses_as_migration_map(data: bytes | None) -> dict | None:
    """The path-migration map `data` holds, or None when it is not one."""
    if data is None:
        return None
    try:
        source = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(source, dict) or any(
            member not in source for member in MIGRATION_MAP_MEMBERS):
        return None
    return source


def introducing_commit(root: Path, relative: str) -> str | None:
    """The commit that added `relative`, or None when git names none.

    The adoption record carries no commit identity and cannot — it is created
    *by* the commit that would name it — so the introducing commit is the only
    identity git already holds (D34).
    """
    code, out = run_git(root, "log", "--diff-filter=A", "--format=%H", "-1",
                        "--", relative)
    if code != 0:
        return None
    text = out.decode("utf-8", "surrogateescape").strip()
    return text.splitlines()[0] if text else None


def commit_is_ancestor(root: Path, commit: str, branch: str) -> bool:
    """Whether `commit` is reachable from `branch` (D19)."""
    code, _ = run_git(root, "merge-base", "--is-ancestor", commit, branch)
    return code == 0


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
