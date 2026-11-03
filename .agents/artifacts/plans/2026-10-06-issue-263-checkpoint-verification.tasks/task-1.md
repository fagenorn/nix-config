# Task 1: The `verified-tree` command

**Files:**
- Create: `python/agent_tools/verified_tree.py`
- Create: `tests/test_verified_tree.py`
- Modify: `lib/agent-tools.nix` (the `commands` list)
- Modify: `justfile` (the `agent-workflow-tests` recipe's file list)
- Modify: `CLAUDE.md` (the **Agent helper package** paragraph)

**Interfaces:**
- Consumes: `agent_tools.canonical.reject_duplicate_keys`, `agent_tools.canonical.reject_nonfinite_literal` (strict JSON load hooks).
- Produces, used verbatim by the skill text of Tasks 2 and 4:
  - `verified-tree check --verification <id> [--verification <id> …]` — exit 0, stdout exactly one line of canonical JSON (`sort_keys`, separators `(",", ":")`) `{"status":"verified"|"unverified","tree":"<tree id>"}`. Exit 2 with empty stdout and one stderr line on a git failure or a record that exists but fails strict parsing or its closed schema.
  - `verified-tree record --tree <id> --verification <id> […]` — exit 0 printing `{"recorded":true,"tree":"<id>"}` after atomically replacing the record; exit 3 printing `{"reason":"tree_changed","recorded":false,"tree":"<current tree>"}` and writing nothing when the current tree differs from `--tree`; exit 2 on usage or git error.
  - Record file: `<git rev-parse --absolute-git-dir>/verified-tree.json` holding `{"schema":"verified-tree/v1","tree":"<id>","verification":["<id>",…]}`.
  - Launcher `~/.agents/bin/verified-tree` from the command-table row `"verified-tree"`.

**Invariants:**
- The tree is the git tree of the working tree as verification saw it: tracked files with uncommitted edits plus untracked non-ignored files, built by `git add -A` + `git write-tree` against a temporary copy of the index; on a clean worktree it equals `HEAD^{tree}` (per D7).
- Neither verb changes the real index, HEAD, or any working-tree file.
- `check` answers `verified` only when a record exists, its `tree` equals the current tree, and its `verification` list equals the given ids in order (per D9).
- `record` writes only when the recomputed tree equals `--tree`; a refusal leaves any previous record byte-identical (per D7, D10).
- One latest-pass file per worktree, in that worktree's own git dir; no run, attempt or launch identity, no `launch-commit` (per D8).
- The record's closed schema: exactly the keys `schema`, `tree`, `verification`; `schema == "verified-tree/v1"`; `tree` is 40 or 64 lowercase hex characters; `verification` is a non-empty list of non-empty strings.

- [ ] **Step 1: Write the failing test**

Create `tests/test_verified_tree.py`:

```python
"""verified-tree: a full verification pass recorded against the tree it saw (#263).

Each test drives `python -m agent_tools.verified_tree` in a throwaway git
repository, the way test_launch_commit.py drives its command (per D6).
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERMETIC_GIT = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
SCRUBBED = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
            "GIT_COMMON_DIR", "GIT_CEILING_DIRECTORIES")
IDS = ("nix-build", "agent-workflow-tests")


def verification_args(ids):
    return [arg for verification in ids for arg in ("--verification", verification)]


class VerifiedTreeTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name).resolve()
        self.repo = self.scratch / "repo"
        self.repo.mkdir()
        self.env = {k: v for k, v in os.environ.items() if k not in SCRUBBED}
        self.env.update(HERMETIC_GIT)
        self.git("init", "-q")
        self.git("config", "commit.gpgsign", "false")  # throwaway fixture repo
        (self.repo / ".gitignore").write_text("result\n")
        (self.repo / "src.py").write_text("x = 1\n")
        (self.repo / "tests").mkdir()
        (self.repo / "tests/test_src.py").write_text("assert True\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.repo, capture_output=True,
                              text=True, check=True, env=self.env).stdout.strip()

    def run_tool(self, *args, cwd=None, env=None):
        return subprocess.run([sys.executable, "-m", "agent_tools.verified_tree", *args],
                              cwd=cwd or self.repo, capture_output=True, text=True,
                              check=False, env=env or self.env)

    def check(self, ids=IDS, cwd=None):
        done = self.run_tool("check", *verification_args(ids), cwd=cwd)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.count("\n"), 1, done.stdout)
        return json.loads(done.stdout)

    def record(self, tree, ids=IDS, cwd=None):
        return self.run_tool("record", "--tree", tree, *verification_args(ids), cwd=cwd)

    def record_path(self, cwd=None):
        return Path(self.git("rev-parse", "--absolute-git-dir", cwd=cwd)) / "verified-tree.json"

    def verify_and_record(self, ids=IDS, cwd=None):
        tree = self.check(ids, cwd=cwd)["tree"]
        done = self.record(tree, ids, cwd=cwd)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, '{"recorded":true,"tree":"%s"}\n' % tree)
        return tree

    def test_no_record_is_unverified_and_names_the_head_tree(self):
        done = self.run_tool("check", *verification_args(IDS))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, '{"status":"unverified","tree":"%s"}\n'
                         % self.git("rev-parse", "HEAD^{tree}"))
        self.assertFalse(self.record_path().exists())

    def test_a_pass_is_recorded_and_then_verified(self):
        tree = self.verify_and_record()
        self.assertEqual(tree, self.git("rev-parse", "HEAD^{tree}"))
        self.assertEqual(json.loads(self.record_path().read_text()),
                         {"schema": "verified-tree/v1", "tree": tree, "verification": list(IDS)})
        self.assertEqual(self.check(), {"status": "verified", "tree": tree})

    def test_any_change_after_the_pass_is_unverified(self):
        changes = {
            "source edit": lambda: (self.repo / "src.py").write_text("x = 2\n"),
            "test edit": lambda: (self.repo / "tests/test_src.py").write_text("assert 1\n"),
            "new untracked file": lambda: (self.repo / "new.py").write_text("y = 1\n"),
            "deleted file": lambda: (self.repo / "src.py").unlink(),
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

    def test_an_ignored_file_leaves_the_tree_verified(self):
        tree = self.verify_and_record()
        (self.repo / "result").write_text("build output\n")
        self.assertEqual(self.check(), {"status": "verified", "tree": tree})

    def test_a_different_verification_list_is_unverified(self):
        tree = self.verify_and_record()
        for ids in (("nix-build",), ("agent-workflow-tests", "nix-build"), (*IDS, "lint")):
            with self.subTest(ids=ids):
                self.assertEqual(self.check(ids), {"status": "unverified", "tree": tree})

    def test_a_mismatched_tree_is_refused_and_the_record_kept(self):
        tree = self.verify_and_record()
        before = self.record_path().read_bytes()
        (self.repo / "src.py").write_text("x = 3\n")
        current = self.check()["tree"]
        done = self.record(tree)
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertEqual(done.stdout,
                         '{"reason":"tree_changed","recorded":false,"tree":"%s"}\n' % current)
        self.assertEqual(self.record_path().read_bytes(), before)

    def test_a_refused_first_record_writes_no_file(self):
        stale = self.check()["tree"]
        (self.repo / "src.py").write_text("x = 4\n")
        self.assertEqual(self.record(stale).returncode, 3)
        self.assertFalse(self.record_path().exists())

    def test_an_uncommitted_verified_edit_stays_verified_once_committed(self):
        (self.repo / "src.py").write_text("x = 5\n")
        (self.repo / "added.py").write_text("z = 1\n")
        tree = self.verify_and_record()
        self.assertNotEqual(tree, self.git("rev-parse", "HEAD^{tree}"))
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "fix")
        self.assertEqual(self.git("rev-parse", "HEAD^{tree}"), tree)
        self.assertEqual(self.check(), {"status": "verified", "tree": tree})

    def test_neither_verb_touches_the_real_index(self):
        (self.repo / "src.py").write_text("x = 6\n")
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
        self.assertEqual(self.check(), {"status": "unverified", "tree": tree})
        self.assertEqual(self.check(cwd=linked), {"status": "verified", "tree": tree})

    def test_a_malformed_record_makes_check_exit_2(self):
        tree = self.git("rev-parse", "HEAD^{tree}")
        good = {"schema": "verified-tree/v1", "tree": tree, "verification": list(IDS)}
        cases = {
            "not json": "{",
            "duplicate key": '{"schema":"verified-tree/v1","schema":"verified-tree/v1",'
                             '"tree":"%s","verification":["nix-build"]}' % tree,
            "non-finite literal": '{"schema":"verified-tree/v1","tree":"%s",'
                                  '"verification":["nix-build"],"x":NaN}' % tree,
            "not an object": json.dumps([good]),
            "extra key": json.dumps({**good, "head": "x"}),
            "missing key": json.dumps({k: v for k, v in good.items() if k != "verification"}),
            "wrong schema": json.dumps({**good, "schema": "verified-tree/v2"}),
            "tree not a string": json.dumps({**good, "tree": 7}),
            "tree not hex": json.dumps({**good, "tree": "HEAD"}),
            "empty verification": json.dumps({**good, "verification": []}),
            "non-string id": json.dumps({**good, "verification": ["nix-build", 1]}),
            "empty id": json.dumps({**good, "verification": [""]}),
        }
        for name, body in cases.items():
            with self.subTest(name):
                self.record_path().write_text(body)
                done = self.run_tool("check", *verification_args(IDS))
                self.assertEqual(done.returncode, 2, done.stdout)
                self.assertEqual(done.stdout, "")
                self.assertEqual(len(done.stderr.strip().splitlines()), 1, done.stderr)

    def test_outside_a_git_worktree_both_verbs_exit_2(self):
        outside = self.scratch / "outside"
        outside.mkdir()
        env = {**self.env, "GIT_CEILING_DIRECTORIES": str(self.scratch)}
        for argv in (("check", *verification_args(IDS)),
                     ("record", "--tree", "0" * 40, *verification_args(IDS))):
            with self.subTest(argv[0]):
                done = self.run_tool(*argv, cwd=outside, env=env)
                self.assertEqual(done.returncode, 2)
                self.assertEqual(done.stdout, "")

    def test_usage_errors_exit_2(self):
        for argv in ((), ("check",), ("record", *verification_args(IDS)),
                     ("record", "--tree", "0" * 40), ("forget",)):
            with self.subTest(argv=argv):
                self.assertEqual(self.run_tool(*argv).returncode, 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it and watch it fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest tests/test_verified_tree.py 2>&1 | tail -4`
Expected: FAILED — every test errors or fails with `No module named agent_tools.verified_tree`.

- [ ] **Step 3: Implement**

Create `python/agent_tools/verified_tree.py` as a thin argparse shell over importable functions, following `agent_tools/launch_commit.py`'s shape (module docstring that states the contract, constants, one exception class, `main(argv=None) -> int`, `if __name__ == "__main__": raise SystemExit(main())`). The module docstring describes exactly the Interfaces and Invariants above.

```python
SCHEMA = "verified-tree/v1"
RECORD_NAME = "verified-tree.json"
ERROR_EXIT = 2
REFUSED_EXIT = 3

class VerifiedTreeError(Exception):
    """A git failure or an unreadable or malformed record; main prints one stderr line and exits 2."""

def worktree_root() -> Path: ...          # `git rev-parse --show-toplevel` in the cwd
def record_path(root: Path) -> Path: ...  # `git rev-parse --absolute-git-dir` / RECORD_NAME
def current_tree(root: Path) -> str: ...
def read_record(path: Path) -> dict | None: ...   # None only when the file does not exist
def check(verification: list[str]) -> dict: ...   # {"status", "tree"}
def record(tree: str, verification: list[str]) -> tuple[int, dict]: ...
def main(argv: Sequence[str] | None = None) -> int: ...
```

Decisions the implementation must keep:

1. Every git call goes through one helper that runs `git <args>` with `cwd=root`, `capture_output=True, text=True, check=False`, and raises `VerifiedTreeError` naming the subcommand and git's last stderr line on a non-zero exit or `OSError`.
2. `current_tree(root)` (per D7):

   ```python
   index = root / git(["rev-parse", "--git-path", "index"], root)  # relative to root unless absolute
   with tempfile.TemporaryDirectory() as scratch:
       temporary = Path(scratch) / "index"
       if index.is_file():
           shutil.copyfile(index, temporary)
       env = {**os.environ, "GIT_INDEX_FILE": str(temporary)}
       git(["add", "-A"], root, env=env)
       return git(["write-tree"], root, env=env)
   ```

3. `read_record`: `FileNotFoundError` → `None`; any other `OSError` or `UnicodeDecodeError` → `VerifiedTreeError`. Parse with `json.loads(text, object_pairs_hook=reject_duplicate_keys, parse_constant=reject_nonfinite_literal)`; a `ValueError` or any closed-schema violation from the Invariants raises `VerifiedTreeError`. The tree pattern is `re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", tree)`.
4. `check`: compute the tree, then read the record; `verified` iff the record is not `None`, `record["tree"] == tree` and `record["verification"] == verification`.
5. `record`: recompute the tree; if it differs from `--tree` return `(3, {"recorded": False, "reason": "tree_changed", "tree": current})` without touching the file. Otherwise write `json.dumps({"schema": SCHEMA, "tree": tree, "verification": verification}, sort_keys=True, separators=(",", ":")) + "\n"` to a `tempfile.mkstemp(dir=<git dir>, prefix=".verified-tree-")` file, `fsync` it, and `os.replace` it onto the record path (unlink the temporary on any failure); return `(0, {"recorded": True, "tree": tree})`.
6. CLI: required subcommands `check` and `record`; `--verification` is `action="append", required=True`; `record` also requires `--tree`. argparse's own usage errors exit 2. `main` prints the result as one canonical JSON line (`json.dumps(result, sort_keys=True, separators=(",", ":"))`) only on exit 0 or 3, and on `VerifiedTreeError` prints `verified-tree: <message>` to stderr and returns 2 with empty stdout.

Then:

- `lib/agent-tools.nix`: add `"verified-tree"` to `commands`, directly after `"review-package"`.
- `justfile`: add `    tests/test_verified_tree.py \` on the line after `    tests/test_launch_commit.py \` in `agent-workflow-tests`.
- `CLAUDE.md`: insert this sentence in the **Agent helper package** paragraph, directly after the sentence ending `Actual production also calls external \`sdd-workspace\` by PATH.`:

  > `verified-tree` records a passing run of the declared verification against the git tree it verified (tracked edits plus untracked files that are not ignored, built in a temporary index) as `verified-tree.json` in the worktree's own git directory; `verified-tree check` answers `verified` only for that same tree under the same verification ids, which is how sdd's final gate lets ship skip a rerun (#263).

- [ ] **Step 4: Verify**

Focused tests (failed in Step 2, so a pass is not a no-op):

Run: `PYTHONPATH="$PWD/python" python3 -m unittest tests/test_verified_tree.py 2>&1 | tail -4`
Expected: `OK`, 13 tests.

Build check (this task changes `python/` and `lib/`), per Global Constraints' long-command rule. Stage the new files first: the flake is Git-backed and evaluates only tracked files, so an untracked `verified_tree.py` would trip `lib/agent-tools.nix`'s missing-module assertion:

```bash
git add python/agent_tools/verified_tree.py tests/test_verified_tree.py
log="${TMPDIR:-/tmp}/build-263-t1.log"
{ just build; echo "exit=$?"; } > "$log" 2>&1; tail -3 "$log"
hm=$(nix-store --query --requisites ./result | grep -- '-home-manager-files$')
test -x "$hm/.agents/bin/verified-tree" && echo launcher-ok
```

Expected: the log ends `exit=0`, and the last line prints `launcher-ok` (the launcher does not exist at the base commit). Then `rm -f "$log"`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/verified_tree.py tests/test_verified_tree.py lib/agent-tools.nix justfile CLAUDE.md
launch-commit <Lifecycle worker values> -- -m "feat(agent-tools): add verified-tree to record a verified tree (#263)" -m "<trailers>"
```
