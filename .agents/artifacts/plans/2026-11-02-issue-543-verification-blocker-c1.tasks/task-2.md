# Task 2: `verification-observe` adapter command

**Files:**
- Create: `python/agent_tools/verification_observe.py`
- Create: `tests/test_verification_observe.py`
- Modify: `lib/agent-tools.nix` (the `commands` row `    "verification-observe"` between `"skill-lint"` and `"verified-tree"`)
- Modify: `python/README.md` (a new `## verification-observe` section between the `## verified-tree` section's last paragraph and `## acceptance-record`)
- Modify: `justfile` (one line, `    tests/test_verification_observe.py \`, right after Task 1's `    tests/test_verification_blocker.py \`)

**Interfaces:**
- Consumes: Task 1's `SCHEMA_VERSION`, `FAILURE_KIND`, `OBSERVATION_KIND`, `BlockerRefused`, `strict_load`, `canonical_bytes`, `normalize_declaration`, `validate_failure`, `validate_observation`, `validate_requirement` and (tests only) `blocker_id`; `agent_tools.resolve_project.resolve(repo_root: str | None, required: list[str] | None = None) -> dict` and `ContractError` (`.code`, `.repair_id`).
- Produces (c3 and c4 import these): `GIT_TIMEOUT_SECONDS = 60`; `class ObserveRefused(Exception)`; `observe(repo_root: str, requirement: object) -> dict`; `build_failure(repo_root: str, declaration: object) -> dict`; `main(argv: Sequence[str] | None = None) -> int`. Each of `observe` and `build_failure` returns an object its Task 1 validator accepted, or raises `ObserveRefused` and nothing else for every refusal (a `BlockerRefused`, a `ContractError`, a Git failure, a guard violation).

**Invariants:**
- A thin shell (agent-helpers rule 2): `main` parses, reads stdin's bytes, calls `strict_load`, calls one of the two functions and prints. Exit 0 writes exactly `canonical_bytes(result) + b"\n"` to stdout and nothing to stderr. Exit 2 writes nothing to stdout and one line, `verification-observe: <reason>` with the reason's whitespace collapsed to single spaces, to stderr (D8).
- An argparse error, a relative `--repo-root` or an `--input` other than `-` writes exactly `verification-observe: invalid invocation\n`, exit 2; `--help` prints argparse's help starting `usage: verification-observe `, exit 0 (D13).
- Reasons the tests read: Task 1's `BlockerRefused` text verbatim; `resolve-project refused: <code> <repair_id>`; `<command_id> is not a verification command`; `git <subcommand>: <Git's last non-empty stderr line>` (or `exit <n>` when it printed none, or `timed out after 60 s`); and the four guard reasons `guard: the worktree is not a checkout of --repo-root's repository`, `guard: the worktree's <command_id> entry differs from --repo-root's`, `guard: <path> at HEAD differs from origin/<branch>` and `guard: a selected path has a staged, unstaged or untracked change`.
- Order (D8, D11, D15). `observe`: `validate_requirement`, `resolve(repo_root)` with no capability, fetch, read, build, `validate_observation`. `failure`: `normalize_declaration`, `resolve(repo_root, ["verification"])`, `command_id` in `bindings.workflow.verification`, the common-directory check, the worktree's command entry, fetch, read, the `HEAD` comparison, the change check, build, `validate_failure`. A refusal before the fetch leaves `refs/remotes/origin/<branch>` unmoved.
- The only write is the fetched ref and its objects: no `FETCH_HEAD`, tag, other ref, index or working-tree change, and no declared command runs (D6, D14).
- No output carries the worktree path or the root path: `repository` is `project.id` and `bindings.vcs.integration_branch` resolved at `--repo-root` at call time, and `command` is the root's entry with `cwd` relative to `project.root` (D2, D3).

- [ ] **Step 1: Write the failing tests** in `tests/test_verification_observe.py`

```python
"""verification-observe from source over a local bare origin (issue 543 D6-D13).

Each test copies the eval fixture project into a throwaway repository, resolved
under a temporary HOME holding the committed platform manifest, in the hermetic
Git environment of test_verified_tree.py. The repository publishes to a local
bare `origin` that a second clone, the publisher, advances.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from agent_tools import verification_blocker as vb

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "home/common/agent-skills/platform-manifest.json"
FIXTURE = REPO_ROOT / "home/common/agent-skills/evals/fixture-repo"
HERMETIC_GIT = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
SCRUBBED = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
            "GIT_COMMON_DIR", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CEILING_DIRECTORIES")
COMMAND = [sys.executable, "-m", "agent_tools.verification_observe"]
REPOSITORY = {"project_id": "fixture/tinytask", "integration_branch": "main"}
SUITE = {"id": "suite", "argv": ["python3", "-m", "unittest"], "cwd": "tinytask",
         "env": ["GITHUB_TOKEN"]}
TRACKING = "refs/remotes/origin/main"
INVALID = "verification-observe: invalid invocation\n"


def base_bindings(bindings):
    """`suite` is a verification command with a nested cwd; `lint` is not one."""
    bindings["commands"]["suite"] = {k: SUITE[k] for k in ("argv", "cwd", "env")}
    bindings["commands"]["lint"] = {"argv": ["python3", "-c", "pass"], "cwd": ".", "env": []}
    bindings["workflow"]["verification"] = ["test", "suite"]


class ObserveCase(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name).resolve()
        home = self.scratch / "home"
        (home / ".agents" / "share").mkdir(parents=True)
        shutil.copy(MANIFEST, home / ".agents" / "share" / "platform-manifest.json")
        self.env = {k: v for k, v in os.environ.items() if k not in SCRUBBED}
        self.env.update(HERMETIC_GIT, HOME=str(home))
        self.root = self.scratch / "repo"
        shutil.copytree(FIXTURE, self.root)
        self.rewrite(self.root, base_bindings)
        (self.root / "flake.lock").write_text("lock 1\n", encoding="utf-8")
        (self.root / "pkgs" / "nested").mkdir(parents=True)
        (self.root / "pkgs" / "nested" / "default.nix").write_text("{ }\n", encoding="utf-8")
        self.git(self.root, "init", "-q", "-b", "main")
        self.git(self.root, "config", "commit.gpgsign", "false")  # throwaway fixture repo
        self.git(self.root, "add", "-A")
        self.git(self.root, "commit", "-q", "-m", "base")
        self.origin = self.scratch / "origin.git"
        self.git(None, "init", "-q", "--bare", "-b", "main", str(self.origin))
        for key, value in (("gc.auto", "0"), ("maintenance.auto", "false"),
                           ("receive.autogc", "false")):
            self.git(self.origin, "config", key, value)
        self.git(self.root, "remote", "add", "origin", str(self.origin))
        self.git(self.root, "push", "-q", "origin", "main")
        self.publisher = self.scratch / "publisher"
        self.git(None, "clone", "-q", str(self.origin), str(self.publisher))
        self.git(self.publisher, "config", "commit.gpgsign", "false")

    def rewrite(self, checkout, edit):
        path = checkout / ".agents" / "project.json"
        contract = json.loads(path.read_text(encoding="utf-8"))
        edit(contract["bindings"])
        path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")

    def git(self, where, *args):
        prefix = ["git"] if where is None else ["git", "-C", str(where)]
        return subprocess.run([*prefix, *args], capture_output=True, text=True, check=True,
                              env=self.env).stdout.strip()

    def publish(self, files=None, removed=()):
        """One commit on origin's main from the publisher."""
        for name, text in (files or {}).items():
            path = self.publisher / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        for name in removed:
            self.git(self.publisher, "rm", "-q", "-r", name)
        self.git(self.publisher, "add", "-A")
        self.git(self.publisher, "commit", "-q", "--allow-empty", "-m", "publish")
        self.git(self.publisher, "push", "-q", "origin", "main")

    def entry(self, path):
        """The id origin's main holds at `path`."""
        return self.git(self.origin, "rev-parse", f"main:{path}")

    def run_tool(self, *argv, stdin=""):
        return subprocess.run([*COMMAND, *argv], input=stdin, capture_output=True, text=True,
                              env=self.env, timeout=300, check=False)

    def call(self, mode, payload, repo_root=None):
        return self.run_tool(mode, "--repo-root", str(repo_root or self.root), "--input", "-",
                             stdin=json.dumps(payload))

    def ok(self, done):
        self.assertEqual((done.returncode, done.stderr), (0, ""), done.stderr)
        value = json.loads(done.stdout)
        self.assertEqual(done.stdout, vb.canonical_bytes(value).decode("ascii") + "\n")
        return value

    def refused(self, done, fragment):
        self.assertEqual((done.returncode, done.stdout), (2, ""), done.stderr)
        self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
        self.assertTrue(done.stderr.startswith("verification-observe: "), done.stderr)
        self.assertIn(fragment, done.stderr)

    def tracking(self):
        return self.git(self.root, "rev-parse", TRACKING)


class FailureTest(ObserveCase):
    def setUp(self):
        super().setUp()
        self.worktree = self.scratch / "wt"
        self.git(self.root, "worktree", "add", "-q", "-b", "issue-1", str(self.worktree),
                 "origin/main")
        self.declaration = {
            "command_id": "suite", "failure_class": "dependency", "worktree": str(self.worktree),
            "facts": [{"name": "packages", "paths": ["pkgs/nested"]},
                      {"name": "flake-lock", "paths": ["flake.lock", "README.md"]}]}

    def expected_facts(self):
        return [{"name": "flake-lock", "source": {"paths": ["README.md", "flake.lock"]},
                 "value": {"objects": [{"path": "README.md", "object": self.entry("README.md")},
                                       {"path": "flake.lock",
                                        "object": self.entry("flake.lock")}]}},
                {"name": "packages", "source": {"paths": ["pkgs/nested"]},
                 "value": {"objects": [{"path": "pkgs/nested",
                                        "object": self.entry("pkgs/nested")}]}}]

    def test_a_clean_failure_names_the_resolved_command_and_no_path_of_the_host(self):
        done = self.call("failure", self.declaration)
        value = self.ok(done)
        self.assertEqual(value, {"kind": "verification-failure", "schema_version": 1,
                                 "repository": REPOSITORY, "command": SUITE,
                                 "failure_class": "dependency",
                                 "facts": self.expected_facts()})
        self.assertNotIn(str(self.scratch), done.stdout)

    def test_declaration_order_changes_no_byte_and_observe_reads_the_same_values(self):
        first = self.call("failure", self.declaration)
        reordered = dict(reversed(list(self.declaration.items())))
        reordered["facts"] = [{"name": "flake-lock", "paths": ["README.md", "flake.lock"]},
                              {"name": "packages", "paths": ["pkgs/nested"]}]
        self.assertEqual(self.call("failure", reordered).stdout, first.stdout)
        value = self.ok(first)
        requirement = {"kind": "verification", "blocker_id": vb.blocker_id(value),
                       "sources": [{"name": fact["name"], "paths": fact["source"]["paths"]}
                                   for fact in value["facts"]]}
        observed = self.ok(self.call("observe", requirement))
        self.assertEqual((observed["blocker_id"], observed["repository"], observed["facts"]),
                         (requirement["blocker_id"], REPOSITORY, value["facts"]))

    def test_a_refused_declaration_never_fetches(self):
        self.publish({"flake.lock": "lock 2\n"})
        before = self.tracking()
        cases = (({"facts": [{"name": "env", "paths": [".env"]}]}, "secret-shaped"),
                 ({"failure_class": "flaky"}, "unclassified"),
                 ({"command_id": "lint"}, "lint is not a verification command"),
                 ({"note": "x"}, "unknown"),
                 ({"worktree": "wt"}, "worktree"))
        for change, fragment in cases:
            with self.subTest(change=change):
                self.refused(self.call("failure", {**self.declaration, **change}), fragment)
        self.assertEqual(self.run_tool("failure", "--repo-root", "repo", "--input", "-",
                                       stdin=json.dumps(self.declaration)).stderr, INVALID)
        self.assertEqual(self.tracking(), before)

    def test_a_change_to_a_selected_path_in_the_attempt_is_refused(self):
        lock = self.worktree / "flake.lock"
        lock.write_text("edited\n", encoding="utf-8")
        self.refused(self.call("failure", self.declaration), "guard: a selected path")
        self.git(self.worktree, "add", "flake.lock")
        self.refused(self.call("failure", self.declaration), "guard: a selected path")
        self.git(self.worktree, "reset", "-q", "--hard", "HEAD")
        extra = self.worktree / "pkgs" / "nested" / "extra.nix"
        extra.write_text("{ }\n", encoding="utf-8")
        self.refused(self.call("failure", self.declaration), "guard: a selected path")
        extra.unlink()
        self.ok(self.call("failure", self.declaration))
        lock.write_text("committed\n", encoding="utf-8")
        self.git(self.worktree, "commit", "-q", "-am", "own edit")
        self.refused(self.call("failure", self.declaration), "guard: flake.lock at HEAD differs")

    def test_an_attempt_behind_a_selected_change_is_refused_and_an_unrelated_one_is_not(self):
        self.publish({"other.txt": "unrelated\n"})
        self.ok(self.call("failure", self.declaration))
        self.publish({"pkgs/nested/default.nix": "{ x = 1; }\n"})
        self.refused(self.call("failure", self.declaration), "guard: pkgs/nested at HEAD differs")

    def test_a_diverged_command_entry_or_a_foreign_checkout_is_refused(self):
        self.rewrite(self.worktree, lambda b: b["commands"]["suite"].update(argv=["true"]))
        self.refused(self.call("failure", self.declaration), "guard: the worktree's suite entry")
        self.git(self.worktree, "checkout", "--", ".agents/project.json")
        foreign = self.scratch / "foreign"
        self.git(None, "clone", "-q", str(self.origin), str(foreign))
        self.refused(self.call("failure", {**self.declaration, "worktree": str(foreign)}),
                     "guard: the worktree is not a checkout")


class ObserveTest(ObserveCase):
    REQUIREMENT = {"kind": "verification", "blocker_id": "sha256:" + "1" * 64,
                   "sources": [{"name": "flake-lock", "paths": ["flake.lock"]},
                               {"name": "packages", "paths": ["pkgs/nested"]}]}

    def expected(self, lock, nested):
        return {"kind": "verification-observation", "schema_version": 1,
                "blocker_id": self.REQUIREMENT["blocker_id"], "repository": REPOSITORY,
                "facts": [{"name": "flake-lock", "source": {"paths": ["flake.lock"]},
                           "value": {"objects": [{"path": "flake.lock", "object": lock}]}},
                          {"name": "packages", "source": {"paths": ["pkgs/nested"]},
                           "value": {"objects": [{"path": "pkgs/nested", "object": nested}]}}]}

    def observe(self):
        return self.call("observe", self.REQUIREMENT)

    def test_an_unrelated_commit_is_equal_and_a_selected_change_is_not(self):
        first = self.observe()
        self.assertEqual(self.ok(first), self.expected(self.entry("flake.lock"),
                                                       self.entry("pkgs/nested")))
        self.publish({"README.md": "readme 2\n"})
        self.assertEqual(self.observe().stdout, first.stdout)
        self.publish({"flake.lock": "lock 2\n", "pkgs/nested/deeper/extra.nix": "{ }\n"})
        changed = self.ok(self.observe())
        self.assertEqual(changed, self.expected(self.entry("flake.lock"),
                                                self.entry("pkgs/nested")))
        self.assertNotEqual(changed, json.loads(first.stdout))
        self.publish(removed=("flake.lock",))
        self.assertEqual(self.ok(self.observe()), self.expected(None, self.entry("pkgs/nested")))

    def test_nested_selected_paths_are_each_read_as_their_own_entry(self):
        paths = ["pkgs", "pkgs/nested", "pkgs/nested/default.nix"]
        requirement = {**self.REQUIREMENT, "sources": [{"name": "packages", "paths": paths}]}
        value = self.ok(self.call("observe", requirement))
        self.assertEqual(value["facts"][0]["value"]["objects"],
                         [{"path": path, "object": self.entry(path)} for path in paths])

    def test_the_only_write_is_the_integration_tracking_ref(self):
        self.publish({"flake.lock": "lock 2\n"})
        refs = ("for-each-ref", "--format=%(refname) %(objectname)")
        before = dict(line.split(" ") for line in self.git(self.root, *refs).splitlines())
        status = self.git(self.root, "status", "--porcelain", "--untracked-files=all")
        self.ok(self.observe())
        after = dict(line.split(" ") for line in self.git(self.root, *refs).splitlines())
        self.assertEqual({ref for ref in before.keys() | after.keys()
                          if before.get(ref) != after.get(ref)}, {TRACKING})
        self.assertEqual(after[TRACKING], self.git(self.origin, "rev-parse", "main"))
        self.assertEqual(self.git(self.root, "status", "--porcelain", "--untracked-files=all"),
                         status)
        self.assertFalse((self.root / ".git" / "FETCH_HEAD").exists())

    def test_a_failed_fetch_prints_nothing_and_moves_nothing(self):
        before = self.tracking()
        self.publish({"flake.lock": "lock 2\n"})
        self.git(self.root, "remote", "set-url", "origin", str(self.scratch / "missing.git"))
        self.refused(self.observe(), "git fetch: ")
        self.git(self.root, "remote", "set-url", "origin", str(self.origin))
        self.git(self.origin, "branch", "-m", "main", "gone")
        self.refused(self.observe(), "git fetch: ")
        self.assertEqual(self.tracking(), before)

    def test_observe_needs_no_runnable_verification_command(self):
        def ghost(bindings):
            bindings["commands"]["ghost"] = {"argv": ["verification-observe-no-such-program"],
                                             "cwd": ".", "env": []}
            bindings["workflow"]["verification"].append("ghost")
        self.rewrite(self.root, ghost)
        self.ok(self.observe())
        declaration = {"command_id": "suite", "failure_class": "environment",
                       "worktree": str(self.root),
                       "facts": [{"name": "flake-lock", "paths": ["flake.lock"]}]}
        self.refused(self.call("failure", declaration),
                     "resolve-project refused: capability_unavailable "
                     "capability.verification.command_missing")

    def test_help_and_invalid_invocations(self):
        done = self.run_tool("--help")
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        self.assertTrue(done.stdout.startswith("usage: verification-observe "), done.stdout)
        root = str(self.root)
        for argv in ((), ("observe",), ("observe", "--repo-root", root),
                     ("observe", "--repo-root", root, "--input", "requirement.json"),
                     ("observe", "--repo-root", "repo", "--input", "-"),
                     ("probe", "--repo-root", root, "--input", "-"),
                     ("observe", "--repo-root", root, "--input", "-", "--extra")):
            with self.subTest(argv=argv):
                done = self.run_tool(*argv)
                self.assertEqual((done.returncode, done.stdout, done.stderr), (2, "", INVALID))
        for stdin, fragment in (("{", "input: "), ('{"kind": 1, "kind": 2}', "duplicate"),
                                ('{"x": NaN}', "NaN")):
            with self.subTest(stdin=stdin):
                self.refused(self.run_tool("observe", "--repo-root", root, "--input", "-",
                                           stdin=stdin), fragment)
        self.refused(self.call("observe", {**self.REQUIREMENT, "schema_version": 1}),
                     "unknown")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_verification_observe.py 2>&1 | tail -4'`
Expected: `Ran 12 tests` and `FAILED`; every child's stderr names `No module named agent_tools.verification_observe`.

- [ ] **Step 3: Write the adapter and its wiring**

`verification_observe.py`: the module docstring states the two invocations, what each prints and the exit codes, as the code does them. Decisions:

- **Git children.** One private runner executes `["git", "-C", <dir>, *args]` with `capture_output=True`, `timeout=GIT_TIMEOUT_SECONDS`, `check=False` and an environment that is `os.environ` less `GIT_DIR`, `GIT_WORK_TREE`, `GIT_COMMON_DIR`, `GIT_INDEX_FILE`, `GIT_OBJECT_DIRECTORY` and `GIT_ALTERNATE_OBJECT_DIRECTORIES`, plus `GIT_TERMINAL_PROMPT=0`, `GIT_LITERAL_PATHSPECS=1` and `GIT_OPTIONAL_LOCKS=0` (D8, D14). `subprocess.TimeoutExpired`, `OSError` and a non-zero exit become `ObserveRefused` with the reasons above.
- **Resolution.** `resolve_project.resolve`; a `ContractError` becomes `ObserveRefused(f"resolve-project refused: {error.code} {error.repair_id}")`. The command copy is `{"id", "argv", "env"}` from the entry plus `"cwd": os.path.relpath(entry["cwd"], snapshot["project"]["root"])`, which is `"."` at the root.
- **Fetch** (in `project.root`), the argv of `adopt_inspection.fetch_pinned` with `origin` fixed: `fetch --quiet --no-tags --no-write-fetch-head --no-auto-maintenance --no-recurse-submodules --refmap= origin +refs/heads/<B>:refs/remotes/origin/<B>`, then `rev-parse --verify --end-of-options refs/remotes/origin/<B>^{commit}` read once; every read of the call uses that id (D12).
- **Reads** (D14). One `ls-tree -z --full-tree <commit> -- <path>` per selected path. Empty stdout is `None`. Stdout that is exactly one record, `<mode> <type> <id>\t<path>\0` with the path bytes equal to `path.encode("utf-8")`, gives `<id>`. Any other stdout refuses `git ls-tree: unexpected output for <path>`. Each fact becomes `{"name", "source": {"paths"}, "value": {"objects": [{"path", "object"}]}}` in the selection's order.
- **Guard** (D7, D15). `rev-parse --path-format=absolute --git-common-dir` in the worktree and in the root, compared after `Path.resolve()`. The worktree's entry comes from `resolve(worktree)` with no capability required, through the same command copy, compared as a whole with the root's (an absent entry differs). After the reads, the worktree's `rev-parse --verify HEAD^{commit}` is read and each selected path's entry at `HEAD` (same read, in the worktree) must equal the entry at the fetched commit. Last, `status --porcelain=v1 -z --untracked-files=all -- <every selected path>` in the worktree must print nothing.
- **Parser.** An `argparse.ArgumentParser` subclass whose `error` raises a private exception; `prog="verification-observe"`; required subcommands `failure` and `observe`, each with required `--repo-root` and `--input`.

`lib/agent-tools.nix`: the one `commands` row named under **Files**; nothing else changes (agent-helpers rule 1).

`python/README.md`: one `## verification-observe` section, written from the code at this commit in the file's style (one paragraph per topic, no bullet lists). It states: the pure module `agent_tools.verification_blocker` and what it is the one home of (D1); both invocations, their stdin and the object each prints; the three closed shapes' members and bounds (D2); the secret-shape rule and that it never reads `command` (D4); the identity (D3); the order, the fetch, the per-path reads and `null` (D6, D12, D14); `failure`'s guard (D7, D15); the exits and the invalid-invocation line (D8, D13); the only write; and the known limitations: the class is the caller's declaration, repository paths are the only fact kind, and nothing calls the command yet (c2–c4). Every value it names is read from the code.

Add the `justfile` line named under **Files**.

- [ ] **Step 4: Verify**

Run (timeout 600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_verification_blocker.py tests/test_verification_observe.py 2>&1 | tail -4'`
Expected: `Ran 26 tests` and `OK`.

Run (timeout 3600 s): `bash -c 'set -o pipefail; just build 2>&1 | tail -3'`
Expected: exit 0 (the row's module check and the build-time import of every module pass).

Run: `grep -c '^    "verification-observe"$' lib/agent-tools.nix; grep -c '^    tests/test_verification_observe.py \\$' justfile; grep -c '^## verification-observe$' python/README.md`
Expected: `1`, `1` and `1`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/verification_observe.py tests/test_verification_observe.py \
  lib/agent-tools.nix python/README.md justfile
launch-commit … -- -m "feat(verification): add verification-observe (issue 543)" -m "<session trailers>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64],"id":2,"records":[{"bounds":[{"added_lines":330,"boundary":"all","deleted_lines":0,"record_bytes":16384,"support":{"covers":["r2a"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r2a","last_task":2,"owner":2,"path":"python/agent_tools/verification_observe.py"},{"bounds":[{"added_lines":440,"boundary":"all","deleted_lines":0,"record_bytes":24576,"support":{"covers":["r2b"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r2b","last_task":2,"owner":2,"path":"tests/test_verification_observe.py"},{"bounds":[{"added_lines":1,"boundary":"all","deleted_lines":0,"record_bytes":2048,"support":{"covers":["r2c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2c","last_task":2,"owner":2,"path":"lib/agent-tools.nix"},{"bounds":[{"added_lines":16,"boundary":"all","deleted_lines":0,"record_bytes":24576,"support":{"covers":["r2d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2d","last_task":2,"owner":2,"path":"python/README.md"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":0,"record_bytes":2048,"support":{"covers":["r1c","r2e"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2e","last_task":2,"owner":2,"path":"justfile"}]}}
```
