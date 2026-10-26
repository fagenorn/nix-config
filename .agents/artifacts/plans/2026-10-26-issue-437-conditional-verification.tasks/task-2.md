# Task 2: `verified-tree` resolves its own plan and records only what ran

Spec § The change and the matching rule and § `verified-tree` interface, per D3, D4, D5, D6, D12, D13 and D14. Both verbs drop `--verification` and resolve the worktree's own contract. `check` prints the plan beside `status` and `tree`, and `record` writes the plan's `run` ids only. The record schema is unchanged.

**Files:**
- Modify: `python/agent_tools/verified_tree.py` (module docstring, `_git`, new functions after `read_record`, `check`, `record`, `_parser`, `main`; delete `_require_ids`)
- Modify: `python/README.md` (the body of its `verified-tree` section)
- Test: `tests/test_verified_tree.py` (rewritten onto the fixture harness)

**Interfaces:**
- Consumes: `resolve_project.resolve(repo_root: str, required: list[str]) -> dict`, `resolve_project.ContractError` (`.code`, `.repair_id`) and Task 1's `resolve_project.any_path_matches(paths, globs) -> bool`. It also consumes the snapshot members `bindings.workflow.verification`, `bindings.workflow.verification_conditions` (absent, `None` or a dict) and `bindings.vcs.integration_branch`.
- Produces, for Task 3 and the skills:
  - `verified-tree check`: exit 0 and one canonical JSON line `{"run": [str, ...], "skipped": [{"id": str, "reason": str}, ...], "status": "verified" | "unverified", "tree": str}`.
  - `verified-tree record --tree <id>`: exit 0 `{"recorded":true,"tree":"<id>"}`, or exit 3 `{"reason":"tree_changed","recorded":false,"tree":"<current>"}`.
  - Exit 2 on a refusal or a git failure.
- Module functions (agent-helpers rule 2: policy importable, the command a thin shell):
  - `verification_policy(root: Path) -> dict` returns `{"verification": list[str], "conditions": dict, "integration_branch": str}`, where `conditions` is `{}` for an absent or `null` member.
  - `changed_paths(root: Path, integration_branch: str, tree: str) -> list[str]`.
  - `plan(verification: Sequence[str], conditions: Mapping[str, Mapping], changed: Sequence[str]) -> dict`, which is pure.
  - `current_plan(root: Path, tree: str) -> dict`, `check() -> dict` and `record(tree: str) -> tuple[int, dict]`.

**Invariants:**
- `verification_policy` calls `resolve_project.resolve(str(root), ["verification"])` with `root` the worktree top level. A `ContractError`, including a non-`available` verification capability, becomes `VerifiedTreeError(f"resolve-project refused: {error.code} {error.repair_id}")`, so `main` prints exactly `verified-tree: resolve-project refused: <code> <repair_id>` and exits 2 with empty stdout (D5).
- `plan` keeps declared order in both lists. An id with no key in `conditions` runs. A conditional id runs when `resolve_project.any_path_matches(list(changed), condition["when_changed"])` holds, and is otherwise skipped as `{"id": id, "reason": condition["skip_reason"]}`. An empty `changed` runs no conditional id (D3).
- `current_plan` calls `changed_paths` only when some declared id is a key of `conditions`; otherwise `changed` is `[]` and no `merge-base` or `origin` ref is read (D14).
- `changed_paths` runs `git merge-base HEAD refs/remotes/origin/<integration_branch>`, then `git diff-tree -r --no-renames --name-only -z <base> <tree>`. It reads that stdout as bytes, never stripped, split on NUL with empty pieces dropped, each name decoded with `os.fsdecode`. A name is therefore never trimmed, and a non-UTF-8 name never raises. Any git failure, a missing ref or merge base included, raises `VerifiedTreeError` naming the subcommand: exit 2, never a skip (D4). Split `_git` into `_git_bytes` (raw stdout, the same `OSError` and non-zero-exit mapping) and `_git` (`os.fsdecode(_git_bytes(…)).strip()`), so the error mapping exists once.
- `check()`: `worktree_root()`, `current_tree(root)`, `current_plan(root, tree)`, then `read_record`. `status` is `verified` iff the record exists, its `tree` equals the tree and its `verification` equals `run` (D6). The output is `{**plan, "status": …, "tree": tree}`, printed by the existing `_canonical`, so the keys come out sorted.
- `record(tree)`: the tree comparison comes first, so a mismatch returns `(3, refusal)` before any resolution. Otherwise it writes `verification = current_plan(root, tree)["run"]` through the existing atomic write. `run` is non-empty because a resolvable contract with an available verification capability declares a non-empty list with an unconditional id (D2).
- The record schema, `read_record`, `current_tree`, `record_path`, the atomic write and every #263 invariant are unchanged. The parser has `check` with no options and `record` with `--tree` only, so `--verification` is an argparse usage error, exit 2 (D13).

- [ ] **Step 1: Write the failing test**

Replace the whole of `tests/test_verified_tree.py` with:

```python
"""verified-tree: a verification pass recorded against the tree it saw (#263, issue 437).

Each test drives `python -m agent_tools.verified_tree` in a throwaway git
repository, the way test_launch_commit.py drives its command (#263 D6). The
repository is a copy of the eval fixture project whose contract gains a second,
conditional verification id, resolved under a temporary HOME holding the
committed platform manifest (the lane-triage harness), with
`refs/remotes/origin/main` at the base commit (issue 437 D12).
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "home/common/agent-skills/platform-manifest.json"
FIXTURE = REPO_ROOT / "home/common/agent-skills/evals/fixture-repo"
HERMETIC_GIT = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
SCRUBBED = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
            "GIT_COMMON_DIR", "GIT_CEILING_DIRECTORIES")
IDS = ["test", "suite"]
REASON = "no tinytask or docs paths changed"
CONDITIONS = {"suite": {"when_changed": ["tinytask/*", "docs/*"], "skip_reason": REASON}}
SKIPPED = [{"id": "suite", "reason": REASON}]
ABSENT = object()


class VerifiedTreeTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name).resolve()
        home = self.scratch / "home"
        (home / ".agents" / "share").mkdir(parents=True)
        shutil.copy(MANIFEST, home / ".agents" / "share" / "platform-manifest.json")
        self.repo = self.scratch / "repo"
        shutil.copytree(FIXTURE, self.repo)
        self.env = {k: v for k, v in os.environ.items() if k not in SCRUBBED}
        self.env.update(HERMETIC_GIT, HOME=str(home))
        self.set_conditions(CONDITIONS)
        self.git("init", "-q", "-b", "main")
        self.git("config", "commit.gpgsign", "false")  # throwaway fixture repo
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")

    def set_conditions(self, conditions):
        """Rewrite the working-tree contract: ids `test` and `suite`, with `conditions`."""
        path = self.repo / ".agents" / "project.json"
        contract = json.loads(path.read_text(encoding="utf-8"))
        bindings = contract["bindings"]
        bindings["commands"]["suite"] = {"argv": ["python3", "-m", "unittest"],
                                         "cwd": ".", "env": []}
        bindings["workflow"]["verification"] = list(IDS)
        bindings["workflow"].pop("verification_conditions", None)
        if conditions is not ABSENT:
            bindings["workflow"]["verification_conditions"] = conditions
        path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.repo, capture_output=True,
                              text=True, check=True, env=self.env).stdout.strip()

    def commit_all(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def run_tool(self, *args, cwd=None, env=None):
        return subprocess.run([sys.executable, "-m", "agent_tools.verified_tree", *args],
                              cwd=cwd or self.repo, capture_output=True, text=True,
                              check=False, env=env or self.env)

    def check(self, cwd=None):
        done = self.run_tool("check", cwd=cwd)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.count("\n"), 1, done.stdout)
        answer = json.loads(done.stdout)
        self.assertEqual(done.stdout, json.dumps(answer, sort_keys=True,
                                                 separators=(",", ":")) + "\n")
        self.assertEqual(sorted(answer), ["run", "skipped", "status", "tree"])
        return answer

    def record(self, tree, cwd=None):
        return self.run_tool("record", "--tree", tree, cwd=cwd)

    def record_path(self, cwd=None):
        return Path(self.git("rev-parse", "--absolute-git-dir", cwd=cwd)) / "verified-tree.json"

    def recorded_ids(self, cwd=None):
        return json.loads(self.record_path(cwd=cwd).read_text())["verification"]

    def verify_and_record(self, cwd=None):
        tree = self.check(cwd=cwd)["tree"]
        done = self.record(tree, cwd=cwd)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, '{"recorded":true,"tree":"%s"}\n' % tree)
        return tree

    def assert_exit_2(self, done):
        self.assertEqual(done.returncode, 2, done.stdout)
        self.assertEqual(done.stdout, "")
        self.assertEqual(len(done.stderr.strip().splitlines()), 1, done.stderr)

    # Issue 437 AC1: a change outside every listed path.

    def test_a_change_outside_every_listed_path_skips_the_conditional_id(self):
        (self.repo / "tests/test_cli.py").write_text("# edited\n")
        (self.repo / "issues/005-new.md").write_text("# new\n")
        self.git("add", "issues/005-new.md")
        answer = self.check()
        self.assertEqual((answer["run"], answer["skipped"], answer["status"]),
                         (["test"], SKIPPED, "unverified"))
        tree = self.verify_and_record()
        self.assertEqual(self.recorded_ids(), ["test"])
        self.assertEqual(self.check(), {"run": ["test"], "skipped": SKIPPED,
                                        "status": "verified", "tree": tree})

    def test_an_untracked_file_under_a_listed_path_changes_nothing(self):
        (self.repo / "tinytask/scratch.py").write_text("x = 1\n")
        answer = self.check()
        self.assertEqual((answer["run"], answer["skipped"]), (["test"], SKIPPED))
        self.assertEqual(answer["tree"], self.git("rev-parse", "HEAD^{tree}"))

    # Issue 437 AC2: a change to any listed path.

    def test_a_change_to_a_listed_path_runs_the_conditional_id(self):
        changes = {
            "committed edit": lambda: (
                (self.repo / "tinytask/cli.py").write_text("# edited\n"),
                self.commit_all("edit cli")),
            "staged new file": lambda: (
                (self.repo / "tinytask/extra.py").write_text("y = 1\n"),
                self.git("add", "tinytask/extra.py")),
            "tracked working-tree edit": lambda: (
                (self.repo / "tinytask/store.py").write_text("# edited\n")),
            "deletion": lambda: (self.repo / "tinytask/model.py").unlink(),
            "rename out of a listed directory": lambda: (
                self.git("mv", "tinytask/model.py", "model.py")),
            "nested path under a star glob": lambda: (
                (self.repo / "docs/areas/system/adr/001-standard-library-only.md")
                .write_text("# edited\n")),
        }
        for name, change in changes.items():
            with self.subTest(name):
                self.git("reset", "-q", "--hard", "refs/remotes/origin/main")
                self.git("clean", "-qfd")
                change()
                answer = self.check()
                self.assertEqual((answer["run"], answer["skipped"]), (IDS, []))
                self.verify_and_record()
                self.assertEqual(self.recorded_ids(), IDS)
                self.assertEqual(self.check()["status"], "verified")

    def test_a_pass_that_skipped_the_conditional_id_is_unverified_once_a_listed_path_changes(self):
        (self.repo / "README.md").write_text("# edited\n")
        self.verify_and_record()
        self.assertEqual(self.recorded_ids(), ["test"])
        (self.repo / "tinytask/cli.py").write_text("# edited\n")
        self.commit_all("touch a listed path")
        answer = self.check()
        self.assertEqual((answer["run"], answer["skipped"], answer["status"]),
                         (IDS, [], "unverified"))
        # A record of the right tree that lacks a run id is no pass either.
        self.record_path().write_text(json.dumps(
            {"schema": "verified-tree/v1", "tree": answer["tree"], "verification": ["test"]}))
        self.assertEqual(self.check()["status"], "unverified")

    def test_only_the_branchs_own_change_counts_against_the_merge_base(self):
        # Main advances with a listed change the branch has not merged: the
        # merge base stays at the fork, so the change is not the branch's.
        self.git("checkout", "-q", "-b", "upstream")
        (self.repo / "tinytask/cli.py").write_text("# upstream\n")
        self.commit_all("upstream edit")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.git("checkout", "-q", "main")
        self.assertEqual(self.check()["skipped"], SKIPPED)
        # Once merged, the merge base is main's tip and the change is still main's.
        self.git("merge", "-q", "--no-edit", "upstream")
        self.assertEqual(self.check()["skipped"], SKIPPED)

    def test_a_contract_without_conditions_runs_every_id_and_needs_no_origin_ref(self):
        for conditions in (ABSENT, None, {}):
            with self.subTest(conditions=conditions):
                self.git("reset", "-q", "--hard", "main")
                self.set_conditions(conditions)
                self.commit_all("no conditions")
                self.git("update-ref", "-d", "refs/remotes/origin/main")
                answer = self.check()
                self.assertEqual((answer["run"], answer["skipped"]), (IDS, []))
                self.verify_and_record()
                self.assertEqual(self.recorded_ids(), IDS)

    def test_a_resolver_refusal_exits_2_and_writes_nothing(self):
        self.set_conditions({"suite": {"when_changed": [], "skip_reason": REASON}})
        self.git("add", ".agents/project.json")
        current = self.git("write-tree")
        for argv in (("check",), ("record", "--tree", current)):
            with self.subTest(argv[0]):
                done = self.run_tool(*argv)
                self.assert_exit_2(done)
                self.assertEqual(done.stderr, "verified-tree: resolve-project refused: "
                                 "invalid_contract contract.workflow.empty_path_list\n")
                self.assertFalse(self.record_path().exists())

    def test_a_missing_origin_ref_exits_2_when_an_id_is_conditional(self):
        self.git("update-ref", "-d", "refs/remotes/origin/main")
        tree = self.git("rev-parse", "HEAD^{tree}")
        for argv in (("check",), ("record", "--tree", tree)):
            with self.subTest(argv[0]):
                self.assert_exit_2(self.run_tool(*argv))
                self.assertFalse(self.record_path().exists())

    # #263 invariants, carried onto the fixture harness.

    def test_no_record_is_unverified_and_names_the_head_tree(self):
        done = self.run_tool("check")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, '{"run":["test"],"skipped":[{"id":"suite","reason":"%s"}],'
                         '"status":"unverified","tree":"%s"}\n'
                         % (REASON, self.git("rev-parse", "HEAD^{tree}")))
        self.assertFalse(self.record_path().exists())

    def test_a_pass_is_recorded_and_then_verified(self):
        tree = self.verify_and_record()
        self.assertEqual(tree, self.git("rev-parse", "HEAD^{tree}"))
        self.assertEqual(json.loads(self.record_path().read_text()),
                         {"schema": "verified-tree/v1", "tree": tree, "verification": ["test"]})
        self.assertEqual(self.check()["status"], "verified")

    def test_any_change_after_the_pass_is_unverified(self):
        changes = {
            "source edit": lambda: (self.repo / "README.md").write_text("# edited\n"),
            "test edit": lambda: (self.repo / "tests/test_cli.py").write_text("# edited\n"),
            "staged new file": lambda: ((self.repo / "new.py").write_text("y = 1\n"),
                                        self.git("add", "new.py")),
            "deleted file": lambda: (self.repo / "README.md").unlink(),
        }
        for name, change in changes.items():
            with self.subTest(name):
                self.git("reset", "-q", "--hard")
                self.git("clean", "-qfd")
                tree = self.verify_and_record()
                change()
                answer = self.check()
                self.assertEqual(answer["status"], "unverified")
                self.assertNotEqual(answer["tree"], tree)

    def test_an_untracked_file_is_outside_the_tree_until_it_is_committed(self):
        # The tree is what a Git-backed build sees, and that build excludes
        # untracked files: one leaves the pass standing, and committing it
        # changes the tree, so the next check asks for verification again.
        tree = self.verify_and_record()
        (self.repo / "new.py").write_text("y = 1\n")
        self.assertEqual(self.check()["status"], "verified")
        self.git("add", "new.py")
        self.git("commit", "-q", "-m", "add new.py")
        answer = self.check()
        self.assertEqual(answer["status"], "unverified")
        self.assertEqual(answer["tree"], self.git("rev-parse", "HEAD^{tree}"))
        self.assertNotEqual(answer["tree"], tree)

    def test_a_staged_new_file_is_part_of_the_tree(self):
        (self.repo / "staged.py").write_text("s = 1\n")
        self.git("add", "staged.py")
        tree = self.check()["tree"]
        self.assertEqual(self.git("ls-tree", "--name-only", tree, "staged.py"), "staged.py")
        self.assertEqual(tree, self.git("write-tree"))

    def test_an_ignored_file_leaves_the_tree_verified(self):
        tree = self.verify_and_record()
        (self.repo / "tasks.json").write_text("[]\n")
        self.assertEqual(self.check(), {"run": ["test"], "skipped": SKIPPED,
                                        "status": "verified", "tree": tree})

    def test_a_mismatched_tree_is_refused_and_the_record_kept(self):
        tree = self.verify_and_record()
        before = self.record_path().read_bytes()
        (self.repo / "README.md").write_text("# edited again\n")
        current = self.check()["tree"]
        done = self.record(tree)
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertEqual(done.stdout,
                         '{"reason":"tree_changed","recorded":false,"tree":"%s"}\n' % current)
        self.assertEqual(self.record_path().read_bytes(), before)

    def test_a_refused_first_record_writes_no_file(self):
        stale = self.check()["tree"]
        (self.repo / "README.md").write_text("# edited\n")
        self.assertEqual(self.record(stale).returncode, 3)
        self.assertFalse(self.record_path().exists())

    def test_an_uncommitted_verified_edit_stays_verified_once_committed(self):
        (self.repo / "tinytask/cli.py").write_text("# edited\n")
        (self.repo / "added.py").write_text("z = 1\n")
        self.git("add", "added.py")
        tree = self.verify_and_record()
        self.assertNotEqual(tree, self.git("rev-parse", "HEAD^{tree}"))
        self.commit_all("fix")
        self.assertEqual(self.git("rev-parse", "HEAD^{tree}"), tree)
        self.assertEqual(self.check(), {"run": IDS, "skipped": [],
                                        "status": "verified", "tree": tree})

    def test_neither_verb_touches_the_real_index(self):
        (self.repo / "tinytask/cli.py").write_text("# edited\n")
        (self.repo / "new.py").write_text("n = 1\n")
        status = self.git("status", "--porcelain")
        index = Path(self.git("rev-parse", "--absolute-git-dir")) / "index"
        before = index.read_bytes()
        self.verify_and_record()
        self.assertEqual(index.read_bytes(), before)
        self.assertEqual(self.git("status", "--porcelain"), status)

    def test_the_record_lives_in_a_linked_worktrees_own_git_dir(self):
        linked = self.scratch / "linked"
        self.git("worktree", "add", "-q", "-b", "side", str(linked))
        tree = self.verify_and_record(cwd=linked)
        self.assertTrue(self.record_path(cwd=linked).is_file())
        self.assertFalse(self.record_path().exists())
        self.assertEqual(self.check()["status"], "unverified")
        self.assertEqual(self.check(cwd=linked), {"run": ["test"], "skipped": SKIPPED,
                                                  "status": "verified", "tree": tree})

    def test_a_malformed_record_makes_check_exit_2(self):
        tree = self.git("rev-parse", "HEAD^{tree}")
        good = {"schema": "verified-tree/v1", "tree": tree, "verification": ["test"]}
        cases = {
            "not json": "{",
            "duplicate key": '{"schema":"verified-tree/v1","schema":"verified-tree/v1",'
                             '"tree":"%s","verification":["test"]}' % tree,
            "non-finite literal": '{"schema":"verified-tree/v1","tree":"%s",'
                                  '"verification":["test"],"x":NaN}' % tree,
            "not an object": json.dumps([good]),
            "extra key": json.dumps({**good, "head": "x"}),
            "missing key": json.dumps({k: v for k, v in good.items() if k != "verification"}),
            "wrong schema": json.dumps({**good, "schema": "verified-tree/v2"}),
            "tree not a string": json.dumps({**good, "tree": 7}),
            "tree not hex": json.dumps({**good, "tree": "HEAD"}),
            "empty verification": json.dumps({**good, "verification": []}),
            "non-string id": json.dumps({**good, "verification": ["test", 1]}),
            "empty id": json.dumps({**good, "verification": [""]}),
        }
        for name, body in cases.items():
            with self.subTest(name):
                self.record_path().write_text(body)
                self.assert_exit_2(self.run_tool("check"))

    def test_outside_a_git_worktree_both_verbs_exit_2(self):
        outside = self.scratch / "outside"
        outside.mkdir()
        env = {**self.env, "GIT_CEILING_DIRECTORIES": str(self.scratch)}
        for argv in (("check",), ("record", "--tree", "0" * 40)):
            with self.subTest(argv[0]):
                done = self.run_tool(*argv, cwd=outside, env=env)
                self.assertEqual(done.returncode, 2)
                self.assertEqual(done.stdout, "")

    def test_usage_errors_exit_2(self):
        # Issue 437 D13: `--verification` is gone, with no compatibility handling.
        tree = self.git("rev-parse", "HEAD^{tree}")
        for argv in ((), ("record",), ("forget",), ("check", "--verification", "test"),
                     ("record", "--tree", tree, "--verification", "test")):
            with self.subTest(argv=argv):
                done = self.run_tool(*argv)
                self.assertEqual(done.returncode, 2)
                self.assertEqual(done.stdout, "")
                self.assertFalse(self.record_path().exists())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and watch it fail**

Run the focused form on `tests/test_verified_tree.py`.
Expected: `FAILED (failures=45)` at base, with 21 of the 22 tests failing, because `check` prints no `run` or `skipped` and the old parser requires `--verification`. `test_outside_a_git_worktree_both_verbs_exit_2` passes at base, which is expected.

- [ ] **Step 3: Write the minimal implementation**

In `python/agent_tools/verified_tree.py`:

1. Add `from agent_tools import resolve_project` beside the existing `agent_tools.canonical` import.
2. Split `_git` as the Invariants give. Delete `_require_ids`.
3. After `read_record`, add `verification_policy`, `changed_paths`, `plan` and `current_plan`, in that order, per the Invariants. Rewrite `check` and `record` to their new signatures.
4. In `_parser`, keep `prog`, `description=__doc__` and the formatter. Use `verbs.add_parser("check", help="print the plan; is the current tree verified?")` with no arguments, and give `record` only `--tree` (`required=True`). In `main`, call `check()` and `record(args.tree)`. The exit-code mapping is unchanged.
5. Replace the module docstring with exactly:

```python
"""Record a verification pass against the git tree it verified.

`verified-tree check` resolves the worktree's project, computes the current
tree and the verification plan, and exits 0 printing one line of canonical
JSON, {"run": ["<id>", ...], "skipped": [{"id": "<id>", "reason": "<text>"},
...], "status": "verified" | "unverified", "tree": "<tree id>"}. It answers
`verified` only when a record exists, its `tree` equals the current tree and
its `verification` list equals `run`, element for element.

The plan reads `bindings.workflow.verification`,
`bindings.workflow.verification_conditions` and `bindings.vcs.integration_branch`
from `resolve_project.resolve(<worktree top level>, ["verification"])`. `run`
holds the declared ids, in declared order, that have no condition or whose
`when_changed` globs match a changed path under
`resolve_project.any_path_matches`; `skipped` holds the rest, in declared order,
each with its authored `skip_reason`. The changed paths are the names
`git diff-tree -r --no-renames` prints between
`git merge-base HEAD refs/remotes/origin/<integration_branch>` and the current
tree, so a rename counts as both of its paths and a deletion counts. They are
computed only when some declared id has a condition, so a contract without
conditions needs no `origin` ref and runs every id.

`verified-tree record --tree <id>` recomputes the tree. When it differs from
`--tree` it writes nothing, leaves any previous record byte-identical and exits
3 printing {"reason": "tree_changed", "recorded": false, "tree": "<current
tree>"}. Otherwise it resolves, recomputes the plan, atomically replaces the
record with `verification` set to `run` and exits 0 printing
{"recorded": true, "tree": "<id>"}. A skipped id is never recorded, so a skip
never reads as a pass.

The tree is what a Git-backed build sees: the index's entries, staged new
files included, with tracked files' working-tree edits and deletions applied,
built by `git add -u` and `git write-tree` against a temporary copy of the
index, so on a clean worktree it equals `HEAD^{tree}`. An untracked file is not
in it, as such a build excludes it; committing one changes the tree, so the
next `check` answers `unverified`. Neither verb changes the real index, HEAD or
any working-tree file.

The record is one latest-pass file per worktree,
`<git rev-parse --absolute-git-dir>/verified-tree.json`, holding exactly
{"schema": "verified-tree/v1", "tree": "<id>", "verification": ["<id>", ...]}:
`tree` is 40 or 64 lowercase hex characters and `verification` is a non-empty
list of non-empty strings, the ids that ran and passed on that tree. It
carries no run, attempt or launch identity.

A resolver refusal (its line is `verified-tree: resolve-project refused:
<code> <repair_id>`), a git failure (a missing `origin/<integration_branch>`
ref or merge base included, when some id is conditional), or a record that
exists but fails strict parsing or that closed schema, prints one
`verified-tree: <message>` line on stderr and exits 2 with empty stdout,
writing nothing. argparse's usage errors also exit 2: neither verb takes a
verification id.
"""
```

In `python/README.md`, replace the paragraph under the `verified-tree` heading (it begins "`verified-tree` records a passing run") with these two paragraphs, leaving that heading and the `launch-scope` section untouched:

```markdown
`verified-tree` records a passing run of the declared verification against the git tree it verified (what a Git-backed build sees: the index's entries with tracked files' working-tree edits applied, built in a temporary index, so an untracked file is outside it until committed) as `verified-tree.json` in the worktree's own git directory (#263). Both verbs read the worktree's own `bindings.workflow.verification`, `bindings.workflow.verification_conditions` and `bindings.vcs.integration_branch` through `agent_tools.resolve_project.resolve` with `verification` required, and a refusal exits 2 as `verified-tree: resolve-project refused: <code> <repair_id>`. `verified-tree check` prints `{run, skipped, status, tree}`: `run` is the declared ids, in order, that have no condition or whose condition matches the change, and `skipped` is the rest as `{id, reason}`. It answers `verified` only for that same tree with a record whose ids equal `run`, which is how sdd's final gate lets ship skip a rerun. `verified-tree record --tree <id>` records `run`, so a skipped id never reads as passed.

`verification_conditions` (issue 437) is an optional `resolve-project` member; absent or `null` means no id is conditional. It maps a `workflow.verification` id to `{"when_changed": [<glob>, ...], "skip_reason": "<text>"}`, with exactly those two members. `when_changed` is a non-empty list of globs under the `light_lane.risk_paths` rules: repository-relative, canonically spelled, and matched with `fnmatch.fnmatchcase`, so `*` crosses `/`. `skip_reason` is a non-empty string, reported verbatim. At least one declared id must stay unconditional. The change is every path `git diff-tree -r --no-renames` names between `git merge-base HEAD refs/remotes/origin/<integration_branch>` and the verified tree, so a rename counts as both of its paths and a deletion counts. It is computed only when some id is conditional, and then a missing ref or merge base is exit 2, never a skip.
```

- [ ] **Step 4: Verify**

Run the focused form (timeout 900 s; about 10 s) on `tests/test_verified_tree.py tests/test_lane_triage.py`.
Expected: `OK`, all 22 `VerifiedTreeTest` tests and every `lane-triage` test passing.

Run (timeout 60 s):

```bash
set -e
if grep -q -e '--verification' -e '_require_ids' python/agent_tools/verified_tree.py; then exit 1; fi
grep -q 'verification_conditions' python/README.md
git diff --quiet ca6ba1ae2b37e56c1361a8656c29af1f39b89348 -- lib/agent-tools.nix .agents/project.json
```

Expected: every command exits 0. At base the first check fails, because the parser and docstring carry `--verification`, and the second fails because the README never names the member.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/verified_tree.py python/README.md tests/test_verified_tree.py
launch-commit … -- -m "feat(verified-tree): resolve the plan, skip unmatched conditional ids (issue 437)" -m "<session trailers>"
```

Verify: `git status --short -- python tests` prints nothing.
