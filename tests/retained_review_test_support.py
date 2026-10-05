"""Shared portable fixtures for the retained review suites (issue 234 D8, D12, D17).

Everything here runs real Git in temporary directories: repositories with a
hermetic identity and fixed dates, optional SSH-signed commits from an
ephemeral key, a hostile Git configuration, a read-only preservation snapshot
and the source-tree budget authority. It declares no TestCase, so it is
support rather than a suite and is not listed as one.
"""

import hashlib
import json
import os
import re
import subprocess
from dataclasses import replace
from pathlib import Path

from agent_tools.canonical import telemetry_digest
from agent_tools.review_actual import RECORD_POLICY
from agent_tools.review_issue100 import ISSUE_100_PINS, Domain
from agent_tools.review_issue121 import Issue121Pins
from agent_tools.review_task7 import MODEL_VERSION, TARGETS, TASK7_PINS, RendererSpec, Task7Pins, derive_task7

SOURCE = Path(__file__).resolve().parents[1]

_IDENTITY = {
    "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.test",
    "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.test",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000",
    # The user's global and system configuration (signing keys, hooks, rename
    # settings) never reaches a fixture; tests add hostility explicitly.
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
}

_HOSTILE = (("diff.renames", "copies"), ("diff.renameLimit", "1"), ("core.quotePath", "false"),
            ("diff.noprefix", "true"), ("diff.mnemonicPrefix", "true"), ("color.ui", "always"),
            ("diff.external", "false"))
HOSTILE_GIT_ENV = {"GIT_CONFIG_COUNT": str(len(_HOSTILE))}
for _n, (_key, _value) in enumerate(_HOSTILE):
    HOSTILE_GIT_ENV[f"GIT_CONFIG_KEY_{_n}"] = _key
    HOSTILE_GIT_ENV[f"GIT_CONFIG_VALUE_{_n}"] = _value


def git(repo, *args, env=None, input=None) -> str:
    """Run `git -C repo args` hermetically and return stripped stdout text."""
    merged = dict(os.environ, **_IDENTITY, **(env or {}))
    return subprocess.run(["git", "-C", str(repo), *args], env=merged, input=input,
                          check=True, capture_output=True, text=True).stdout.strip()


def init_repo(tmp) -> Path:
    """A fresh repository at `tmp/repo` that never signs unless asked to."""
    repo = Path(tmp) / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "commit.gpgsign", "false")
    return repo


def commit_files(repo, files, message, *, sign_key=None) -> str:
    """Write (bytes) or delete (None) each path, commit all of them, return the commit.

    With `sign_key`, the commit is SSH-signed by that private key file.
    """
    repo = Path(repo)
    for path, data in files.items():
        target = repo / path
        if data is None:
            git(repo, "rm", "-q", "--", path)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        git(repo, "add", "-f", "--", path)
    signing = [] if sign_key is None else [
        "-c", "gpg.format=ssh", "-c", f"user.signingkey={sign_key}", "-c", "commit.gpgsign=true"]
    git(repo, *signing, "commit", "-q", "--allow-empty", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def ssh_signer(tmp) -> tuple[Path, bytes]:
    """An ephemeral ed25519 key under `tmp` and its allowed-signers line."""
    key = Path(tmp) / "signer"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "fixture",
                    "-f", str(key)], check=True, capture_output=True)
    public = key.with_suffix(".pub").read_bytes().split()
    return key, b"fixture@example.test " + public[0] + b" " + public[1] + b"\n"


def snapshot(repo) -> tuple:
    """Refs, index, status and every file's content digest, `.git` included.

    Git reads run with optional locks disabled, so collecting it writes nothing.
    """
    repo = Path(repo)
    env = {"GIT_OPTIONAL_LOCKS": "0"}
    refs = git(repo, "for-each-ref", "--format=%(objectname) %(refname)", env=env)
    index = hashlib.sha256(git(repo, "ls-files", "--stage", "-z", env=env).encode()).hexdigest()
    status = git(repo, "status", "--porcelain=v2", "-z", "--untracked-files=all", env=env)
    files = []
    for root, dirs, names in os.walk(repo):
        dirs.sort()
        for name in names:
            path = Path(root) / name
            data = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
            files.append((path.relative_to(repo).as_posix(), hashlib.sha256(data).hexdigest()))
    return refs, index, status, tuple(sorted(files))


def source_budget_env(tmp, source=SOURCE) -> dict:
    """An environment whose `artifact-budget` and `agent_tools` are those of the source tree `source`, this
    checkout unless another is named.

    Tests call `describe("review-package")` under
    `patch.dict(os.environ, env, clear=True)`: the installed helper lacks
    `describe` until a switch.
    """
    home = Path(tmp) / "budget-home"
    (home / ".agents/lib/python").mkdir(parents=True)
    (home / ".agents/share").mkdir(parents=True)
    legacy = Path(source) / "home/common/agent-skills"
    (home / ".agents/lib/python/artifact_budget.py").symlink_to(legacy / "scripts/artifact_budget.py")
    (home / ".agents/share/artifact-budget-policy.json").symlink_to(legacy / "artifact-budget-policy.json")
    return dict(os.environ, HOME=str(home), PYTHONPATH=str(Path(source) / "python"),
                PATH=str(legacy / "scripts") + os.pathsep + os.environ["PATH"])


PLAN_PREFIX = ".claude/plans/fixture-adoption"
# The Task-7 inventory beside the plan: one file under each other move root,
# every rewrite target (named only through `TARGETS`) and the renderer source the fixture pins name.
_TASK7_SEED = {
    ".claude/specs/fixture-design.md": b"fixture spec\n", ".out-of-scope/fixture.md": b"fixture decision\n",
    **{target: f"fixture {target}\n".encode() for target, operation, _ in TARGETS if operation == "write"},
    "tools/render.py": b"# fixture renderer\n"}


def linear_fixture(tmp, owners=(1, 1, 2, 3, 3, 4, 5, 6), touches=None) -> tuple:
    """A linear repository and its `Issue121Pins`.

    The SSH-signed first commit (the base) writes the plan root, its eight task
    members and the Task-7 seed. Commit `k` then writes `src/c<k>.txt` for owner
    `owners[k]` (owner 0 is process) and, with `touches={k: j}`, also edits
    commit `j`'s file.
    """
    key, signer = ssh_signer(tmp)
    repo = init_repo(tmp)
    plan = {f"{PLAN_PREFIX}.md": b"fixture plan root\n",
            **{f"{PLAN_PREFIX}.tasks/task-{n}.md": f"fixture task {n}\n".encode() for n in range(1, 9)}}
    base = commit_files(repo, {**plan, **_TASK7_SEED}, "seed", sign_key=key)
    assignments = []
    for k, owner in enumerate(owners):
        files = {f"src/c{k}.txt": f"commit {k}\n".encode()}
        if touches and k in touches:
            other = f"src/c{touches[k]}.txt"
            files[other] = (repo / other).read_bytes() + f"touched by {k}\n".encode()
        assignments.append((commit_files(repo, files, f"commit {k}"), owner, None if owner else "process"))
    blobs = tuple((path, git(repo, "rev-parse", f"{base}:{path}"))
                  for path in (f"{PLAN_PREFIX}.md", f"{PLAN_PREFIX}.tasks/task-7.md"))
    return repo, Issue121Pins(base, assignments[-1][0], tuple(assignments), PLAN_PREFIX, blobs, signer, 8)


def task7_fixture(repo, pins) -> tuple:
    """Task-7 pins at the linear fixture's head (the seed renderer, the plan blobs) and their table."""
    head = pins.head
    tree = git(repo, "rev-parse", head + "^{tree}")
    renderer = git(repo, "rev-parse", f"{head}:tools/render.py")
    roots = TASK7_PINS.move_roots
    moves = sum(1 for path in git(repo, "ls-tree", "-r", "--name-only", tree).splitlines()
                if any(path.startswith(old + "/") for old, _, _ in roots))
    book = "bookkeeping_operations:"
    fields = {"project_id": ("amended_contract:project_id", 1, 40), "migration_id": (book + "migration_id", 1, 64),
              "moves.old_path": (book + "moves.old_path", moves, 120),
              "moves.new_path": (book + "moves.new_path", moves, 120),
              "plan_id": (book + "plan_id", 1, 64), "path_migration_map": (book + "path_migration_map", 1, 64),
              "base_revision": (book + "base_revision", 1, 40), "sources.before": (book + "sources.before", 3, 64)}
    renderers = tuple(RendererSpec(target, "tools/render.py", renderer, 60, 3,
                                   tuple(fields[name] for name in members))
                      for target, _, members in TARGETS)
    blobs = dict(pins.plan_blobs)
    task7_pins = Task7Pins(head, tree, blobs[f"{pins.plan_prefix}.md"],
                           blobs[f"{pins.plan_prefix}.tasks/task-7.md"], MODEL_VERSION,
                           TASK7_PINS.subject_template, roots, renderers, 40)
    return task7_pins, derive_task7(repo, task7_pins)


def retained_fixture(tmp, **shape) -> tuple:
    """`(issue_121_repo, issue_100_repo, archive_dir, (task7_pins, issue121_pins, issue100_pins))` under `tmp/repos`.

    The issue-121 side is `linear_fixture` with `task7_fixture` on that repository; the issue-100 repository
    also holds the live commit. The default shape measures every outcome, and
    `owners=(1, 2, 3, 6, 3), touches={4: 3}` leaves `tasks-1-3` and `tasks-4-6` unavailable.
    """
    root = Path(tmp) / "repos"
    (root / "121").mkdir(parents=True)
    repo121, pins121 = linear_fixture(root / "121", **shape)
    repo100, _, archive, pins100 = issue100_fixture(root / "100")
    return repo121, repo100, archive, (task7_fixture(repo121, pins121)[0], pins121, pins100)


def tool_fixture(tmp) -> tuple:
    """A repository under `tmp/repos/tool` and its one commit: this source tree's `python/agent_tools` files
    at that path, without `__pycache__` directories."""
    package = SOURCE / "python/agent_tools"
    files = {path.relative_to(SOURCE).as_posix(): path.read_bytes() for path in sorted(package.rglob("*"))
             if path.is_file() and "__pycache__" not in path.relative_to(package).parts}
    repo = init_repo(Path(tmp) / "repos/tool")
    return repo, commit_files(repo, files, "tool")


def rehash_edges(edges) -> list:
    """Copies of `edges`, each with its `id` recomputed over every other member."""
    return [{**edge, "id": telemetry_digest({k: v for k, v in edge.items() if k != "id"})} for edge in edges]


def _raw(repo, *args) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], env=dict(os.environ, **_IDENTITY),
                          check=True, capture_output=True).stdout


def _domain(pinned, raw) -> Domain:
    records = len(re.findall(rb"(?m)^diff --git ", raw))
    return Domain(pinned.name, pinned.policy_sha256, len(raw), records, hashlib.sha256(raw).hexdigest())


def issue100_fixture(tmp) -> tuple:
    """An issue repository, a clone of it as the live repository, an archive directory and their pins.

    From the base, c1 adds the process path `docs/plan.md` and `tmp/scratch.txt`; c2 adds `src/a.txt`,
    edits `ci.yaml` and replaces the directory `tmp` with a file; c3 edits `justfile` and replaces the
    base file `legacy` with the directory holding `legacy/note.txt`; s1, branched at c1, adds `src/b.txt`;
    m merges s1 into c3; c4 renames `src/b.txt` to `src/c.txt` and edits `legacy/note.txt`, so the head's
    `legacy` is no longer the tree c3 left. Both swaps happen within one commit, so that edge's record of
    the file names the directory on its other side. The `live` branch from
    the base writes head's `src/a.txt` and its own `ci.yaml`. The archive's two `shard-NNN.diff` shards,
    manifest and producer come from running the pinned recipe over the base and head trees. The pinned
    digest of the raw parent edges is taken from plain `git rev-list --parents`, apart from the module.
    """
    repo = init_repo(tmp)
    base = commit_files(repo, {"README": b"fixture\n", "ci.yaml": b"ci: base\n", "justfile": b"base:\n",
                               "legacy": b"legacy\n"}, "base")
    commit_files(repo, {"docs/plan.md": b"plan\n", "tmp/scratch.txt": b"scratch\n"}, "c1")
    git(repo, "branch", "side")
    commit_files(repo, {"src/a.txt": b"a\n", "ci.yaml": b"ci: head\n", "tmp/scratch.txt": None,
                        "tmp": b"file\n"}, "c2")
    commit_files(repo, {"justfile": b"head:\n", "legacy": None, "legacy/note.txt": b"note\n"}, "c3")
    git(repo, "checkout", "-q", "side")
    commit_files(repo, {"src/b.txt": b"b\n"}, "s1")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge side", "side")
    head = commit_files(repo, {"src/b.txt": None, "src/c.txt": b"b\n", "legacy/note.txt": b"note 2\n"}, "c4")
    git(repo, "checkout", "-q", "-b", "live", base)
    live = commit_files(repo, {"src/a.txt": b"a\n", "ci.yaml": b"ci: live\n"}, "live")
    git(repo, "checkout", "-q", "main")
    live_repo = Path(tmp) / "live"
    git(tmp, "clone", "-q", str(repo), str(live_repo))
    trees = [git(repo, "rev-parse", f"{oid}^{{tree}}") for oid in (base, head)]
    raw = _raw(repo, *ISSUE_100_PINS.recipe, *trees)
    fresh = _raw(repo, *RECORD_POLICY["git_config"], "diff", *RECORD_POLICY["diff_args"], "--binary", "-U10", *trees)
    historical = _domain(ISSUE_100_PINS.historical, raw)
    starts = [m.start() for m in re.finditer(rb"(?m)^diff --git ", raw)]
    shards = [raw[:starts[2]], raw[starts[2]:]]
    archive, stem = Path(tmp) / "archive", "review-fixture"
    (archive / f"{stem}.shards").mkdir(parents=True)
    for n, shard in enumerate(shards, 1):
        (archive / f"{stem}.shards/shard-{n:03d}.diff").write_bytes(shard)
    numstat = [row.split("\t")[:2] for row in git(repo, "diff", "--numstat", base, head).splitlines()]
    commits = git(repo, "rev-list", "--reverse", f"{base}..{head}").split()
    manifest = json.dumps({
        "commits": [{"sha": sha, "subject": git(repo, "show", "-s", "--format=%s", sha)} for sha in commits],
        "coverage": {"complete": True, "file_diff_count": historical.records}, "interface_version": 1,
        "kind": "review-package", "purpose": "diff-review", "range": {"base": base, "head": head},
        "shards": [{"path": f"{stem}.shards/shard-{n:03d}.diff", "bytes": len(s)} for n, s in enumerate(shards, 1)],
        "stat": {"deletions": sum(int(d) for _, d in numstat), "files_changed": historical.records,
                 "insertions": sum(int(i) for i, _ in numstat)},
        "total_diff_bytes": len(raw)}, sort_keys=True, separators=(",", ":")).encode()
    # The producer's metrics are the package it reports: the manifest as root plus every shard.
    producer = json.dumps({"artifact": {
        "budget_status": "over_budget", "kind": "review-package",
        "metrics": {"file_count": len(shards) + 1, "largest_member_bytes": max(len(manifest), *map(len, shards)),
                    "root_bytes": len(manifest), "total_bytes": len(manifest) + len(raw)},
        "path": str(archive / f"{stem}.json"), "violations": ["member_count", "aggregate_bytes"]},
        "notes": "validated review package", "state": "decompose_required"}, sort_keys=True).encode()
    (archive / f"{stem}.json").write_bytes(manifest)
    (archive / "producer.raw").write_bytes(producer)
    # Counts by construction: commits c1 c2 c3 s1 m c4; edge records 2+4+3+1 for c1 c2 c3 s1 (c2:
    # ci.yaml src/a.txt tmp tmp/scratch.txt; c3: justfile legacy legacy/note.txt), 1+7 for m's two
    # parents (c3: src/b.txt; s1: ci.yaml justfile legacy legacy/note.txt src/a.txt tmp tmp/scratch.txt),
    # 2 for c4; final paths: docs/plan.md (process), src/a.txt (integrated), ci.yaml and justfile
    # (pending), and the ordinary candidates src/c.txt, legacy, legacy/note.txt and tmp.
    counts = {"commits": 6, "parent_edges": 7, "merge_edges": 1, "edge_records": 20, "contributions": 8,
              "historical_process": 1, "integrated": 1, "candidate": 6, "candidate_ordinary": 4,
              "candidate_reconciliation": 2, "pending_overlaps": 2, "reconciled": 0}
    # Git's own raw parents in range order: one `{parent, commit, parent_ordinal}` row per parent.
    listed = git(repo, "rev-list", "--parents", "--reverse", "--topo-order", f"{base}..{head}").splitlines()
    parent_edges = [{"parent": parent, "commit": row.split()[0], "parent_ordinal": ordinal}
                    for row in listed for ordinal, parent in enumerate(row.split()[1:], 1)]
    pins = replace(ISSUE_100_PINS, base=base, head=head, live=live, producer_name="producer.raw",
                   manifest_name=f"{stem}.json", producer_bytes=len(producer), manifest_bytes=len(manifest),
                   producer_sha256=hashlib.sha256(producer).hexdigest(),
                   manifest_sha256=hashlib.sha256(manifest).hexdigest(),
                   process_paths=frozenset({"docs/plan.md"}), pending_paths=("ci.yaml", "justfile"),
                   historical=historical, fresh=_domain(ISSUE_100_PINS.fresh, fresh), expected_counts=counts,
                   parent_edges_sha256=telemetry_digest(parent_edges))
    return repo, live_repo, archive, pins
