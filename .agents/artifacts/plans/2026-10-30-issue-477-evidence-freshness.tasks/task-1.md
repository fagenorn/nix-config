# Task 1: `verified-tree fresh` verb and its contract

Spec § The `fresh` verb and § Documentation of the verb. Rests on D1, D2, D3, D4, D7, D8 and D9. After this task, `verified-tree fresh --since <commit> --record <path>` prints whether the build-visible tree has changed since a commit, ignoring only the acceptance record's own path, and its contract lives in the module docstring (`--help`) and `python/README.md`.

**Files:**
- Modify: `python/agent_tools/verified_tree.py`
- Modify: `python/README.md`
- Test: `tests/test_verified_tree.py`

**Interfaces:**
- Consumes: `worktree_root() -> Path`, `current_tree(root: Path) -> str`, `_git`, `_git_bytes`, `VerifiedTreeError`, `_canonical`, `ERROR_EXIT`, all already in `verified_tree.py`.
- Produces:
  - `_tree_diff(root: Path, left: str, right: str) -> list[str]`: the paths whose entries differ between tree-ish `left` and `right`, from `git diff-tree -r --no-renames --name-only -z <left> <right>`, decoded with `os.fsdecode`, empty names dropped, in git's order. `changed_paths` keeps its signature and returns `_tree_diff(root, base, tree)`.
  - `_record_relative(root: Path, record: str) -> str`: the record's repository-relative POSIX path.
  - `fresh(since: str, record: str) -> dict`: `{"changed": list[str], "since": <full commit sha>, "status": "fresh" | "stale", "tree": <current tree id>}`.
  - CLI: `verified-tree fresh --since <commit> --record <path>`, both options required, no positional argument; exit 0 with one canonical JSON line; Task 2's guidance calls it.

**Invariants:**
- `status` is `fresh` exactly when `changed` is empty; `changed` is the tree diff minus the one record path, nothing else excluded (D2, D8).
- `fresh` never calls `resolve_project`, takes no lock and writes nothing: the real index, `git status --porcelain`, `verified-tree.json` and `verified-tree-plan.json` are byte-identical after it.
- Every refusal exits 2 with empty stdout and exactly one `verified-tree: <message>` stderr line, in the order of D9.
- `check` and `record` behave exactly as at base; the 31 existing tests still pass.

- [ ] **Step 1: Write the failing tests**

In `tests/test_verified_tree.py`, add the constant `RECORD = ".agents/artifacts/plans/p.acceptance.md"` on the line after `ABSENT = object()`.

Rename `test_outside_a_git_worktree_both_verbs_exit_2` to `test_outside_a_git_worktree_every_verb_exits_2` and make its loop header:

```python
        for argv in (("check",), ("record", "--tree", "0" * 40),
                     ("fresh", "--since", "HEAD", "--record", RECORD)):
```

In `test_usage_errors_exit_2`, extend the argv tuple so it ends:

```python
                     ("record", "--tree", tree, "--verification", "test"),
                     ("fresh",), ("fresh", "--since", "HEAD"), ("fresh", "--record", RECORD),
                     ("fresh", "--since", "HEAD", "--record", RECORD, "extra")):
```

Append these methods at the end of `VerifiedTreeTest`, after `test_usage_errors_exit_2`, one blank line between methods:

```python
    # Issue 477: `fresh` judges evidence measured at a commit against the content it measured.

    def fresh(self, since, record=RECORD, cwd=None):
        done = self.run_tool("fresh", "--since", since, "--record", record, cwd=cwd)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stderr, "")
        answer = json.loads(done.stdout)
        self.assertEqual(done.stdout, json.dumps(answer, sort_keys=True,
                                                 separators=(",", ":")) + "\n")
        self.assertEqual(sorted(answer), ["changed", "since", "status", "tree"])
        return answer

    def write_record(self, text):
        path = self.repo / RECORD
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def answer(self, changed, since):
        """The `fresh` output for a clean worktree at HEAD."""
        return {"changed": changed, "since": since,
                "status": "stale" if changed else "fresh",
                "tree": self.git("rev-parse", "HEAD^{tree}")}

    def test_a_commit_that_changes_only_the_record_stays_fresh(self):
        # Issue 477 AC1: today there is no `fresh` verb, so this exits 2.
        since = self.git("rev-parse", "HEAD")
        self.write_record("| AC1 | met |\n")
        self.commit_all("acceptance record")
        self.assertEqual(self.fresh(since), self.answer([], since))
        self.write_record("| AC1 | met |\n| AC2 | met |\n")
        self.commit_all("acceptance record again")
        self.assertEqual(self.fresh(since), self.answer([], since))

    def test_a_commit_that_changes_a_measured_file_is_stale(self):
        # Issue 477 AC2.
        since = self.git("rev-parse", "HEAD")
        self.write_record("| AC1 | met |\n")
        (self.repo / "tinytask/cli.py").write_text("# edited\n")
        self.commit_all("edit cli")
        self.assertEqual(self.fresh(since), self.answer(["tinytask/cli.py"], since))

    def test_a_tracked_edit_is_measured_and_an_untracked_file_is_not(self):
        since = self.git("rev-parse", "HEAD")
        (self.repo / "tinytask/scratch.py").write_text("x = 1\n")
        self.assertEqual(self.fresh(since), self.answer([], since))
        (self.repo / "tinytask/cli.py").write_text("# edited\n")
        answer = self.fresh(since)
        self.assertEqual((answer["changed"], answer["status"]), (["tinytask/cli.py"], "stale"))
        self.assertNotEqual(answer["tree"], self.git("rev-parse", "HEAD^{tree}"))

    def test_a_reverted_change_is_fresh_again(self):
        since = self.git("rev-parse", "HEAD")
        (self.repo / "tinytask/cli.py").write_text("# edited\n")
        self.commit_all("edit cli")
        self.git("revert", "--no-edit", "HEAD")
        self.assertEqual(self.fresh(since[:12]), self.answer([], since))

    def test_a_merge_that_changes_a_measured_path_is_stale(self):
        since = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "-b", "side")
        (self.repo / "tinytask/store.py").write_text("# edited\n")
        self.commit_all("edit store")
        self.git("checkout", "-q", "main")
        self.write_record("| AC1 | met |\n")
        self.commit_all("acceptance record")
        self.git("merge", "-q", "--no-ff", "-m", "merge side", "side")
        self.assertEqual(self.fresh(since), self.answer(["tinytask/store.py"], since))

    def test_a_rename_lists_both_paths_and_a_deletion_counts(self):
        since = self.git("rev-parse", "HEAD")
        self.git("mv", "tinytask/model.py", "tinytask/models.py")
        self.git("rm", "-q", "docs/README.md")
        self.git("commit", "-q", "-m", "rename and delete")
        self.assertEqual(self.fresh(since), self.answer(
            ["docs/README.md", "tinytask/model.py", "tinytask/models.py"], since))

    def test_the_record_path_resolves_against_the_current_directory(self):
        since = self.git("rev-parse", "HEAD")
        self.write_record("| AC1 | met |\n")
        self.commit_all("acceptance record")
        subdir = self.repo / "tinytask"
        self.assertEqual(self.fresh(since, record="../" + RECORD, cwd=subdir),
                         self.answer([], since))
        self.assertEqual(self.fresh(since, record=str(self.repo / RECORD), cwd=subdir),
                         self.answer([], since))
        self.assertEqual(self.fresh(since, record="p.acceptance.md", cwd=subdir),
                         self.answer([RECORD], since))

    def test_fresh_reads_no_project_contract(self):
        since = self.git("rev-parse", "HEAD")
        (self.repo / ".agents/project.json").unlink()
        answer = self.fresh(since)
        self.assertEqual((answer["changed"], answer["status"]),
                         ([".agents/project.json"], "stale"))

    def test_fresh_writes_nothing(self):
        self.verify_and_record()
        self.check()
        (self.repo / "tinytask/cli.py").write_text("# edited\n")
        (self.repo / "new.py").write_text("n = 1\n")
        status = self.git("status", "--porcelain")
        index = Path(self.git("rev-parse", "--absolute-git-dir")) / "index"
        files = [index, self.record_path(), self.plan_path()]
        before = [path.read_bytes() for path in files]
        self.fresh(self.git("rev-parse", "HEAD"))
        self.assertEqual([path.read_bytes() for path in files], before)
        self.assertEqual(self.git("status", "--porcelain"), status)

    def test_fresh_refuses_a_non_commit_or_a_record_outside_the_worktree(self):
        (self.repo / "link").symlink_to(self.scratch)
        head = self.git("rev-parse", "HEAD")
        cases = {
            "unknown revision": ("--since", "no-such-ref", "--record", RECORD),
            "option-shaped revision": ("--since=--all", "--record", RECORD),
            "a tree, not a commit": ("--since", self.git("rev-parse", "HEAD^{tree}"),
                                     "--record", RECORD),
            "absolute path outside": ("--since", head, "--record",
                                      str(self.scratch / "elsewhere.md")),
            "relative path outside": ("--since", head, "--record", "../elsewhere.md"),
            "symlink out of the worktree": ("--since", head, "--record", "link/r.md"),
            "the top level itself": ("--since", head, "--record", "."),
        }
        for name, argv in cases.items():
            with self.subTest(name):
                self.assert_exit_2(self.run_tool("fresh", *argv))
                self.assertFalse(self.record_path().exists())
                self.assertFalse(self.plan_path().exists())
```

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_verified_tree.py 2>&1 | tail -3'`
Expected: `Ran 41 tests`, `FAILED (failures=16)`: the ten new tests fail (the refusal test in all seven subtests, because argparse rejects the unknown verb with a two-line stderr), and the renamed and extended usage tests still pass.

- [ ] **Step 3: Write the implementation**

In `python/agent_tools/verified_tree.py`:

1. Add `_tree_diff` just above `changed_paths`, moving `changed_paths`'s `diff-tree` call and decoding into it, so the module has one diff form. Its docstring: `"""Every path whose entry differs between tree-ish `left` and `right`, in git's order.` followed by a blank line and `` `--no-renames` lists both sides of a rename, and a deletion is listed.""" ``. `changed_paths` keeps its merge-base line and returns `_tree_diff(root, base, tree)`.

2. Add `_record_relative` and `fresh` just above `_parser`, exactly as follows (D9 fixes the order and the messages):

```python
def _record_relative(root: Path, record: str) -> str:
    """`record`, resolved against the current directory, as a repository-relative POSIX path."""
    top = root.resolve()
    resolved = (Path.cwd() / record).resolve()
    try:
        relative = resolved.relative_to(top)
    except ValueError:
        relative = None
    if relative is None or not relative.parts:
        raise VerifiedTreeError(f"--record {record} is not a path inside the worktree {top}")
    return relative.as_posix()


def fresh(since: str, record: str) -> dict:
    """{"changed", "since", "status", "tree"}: fresh when only `record` differs from `since`."""
    root = worktree_root()
    try:
        commit = _git(["rev-parse", "--verify", "--end-of-options", f"{since}^{{commit}}"], root)
    except VerifiedTreeError as error:
        raise VerifiedTreeError(f"--since {since} names no commit") from error
    excluded = _record_relative(root, record)
    tree = current_tree(root)
    changed = [path for path in _tree_diff(root, commit, tree) if path != excluded]
    return {"changed": changed, "since": commit,
            "status": "stale" if changed else "fresh", "tree": tree}
```

3. In `_parser`, after the `record` verb, add the `fresh` subparser with help `has the tree changed since a commit?` and two required options: `--since` (help `the commit the evidence measured`) and `--record` (help `the acceptance record's path`).

4. In `main`, add `elif args.verb == "fresh": status, result = 0, fresh(args.since, args.record)` between the `check` branch and the `else` that runs `record`.

5. Module docstring (it is `--help`). The two lines ending the `record` paragraph become these three:

```text
run are ever recorded, and a skip never reads as a pass. `check` and `record`
read and write the plan under an exclusive lock on `verified-tree-plan.lock`
beside it.
```

   Then add this paragraph after it, separated by blank lines:

```text
`verified-tree fresh --since <commit> --record <path>` answers whether evidence
measured at a commit still describes the current tree. `--since` must resolve
under `git rev-parse --verify --end-of-options <since>^{commit}`. `--record`,
resolved against the current directory with symlinks followed, must lie
strictly inside the worktree's top level; it need not exist. `fresh` lists the
paths that differ between that commit's tree and the current tree, in the same
`git diff-tree -r --no-renames` form as the changed paths above, drops the
record's repository-relative path, and exits 0 printing {"changed": ["<path>",
...], "since": "<commit sha>", "status": "fresh" | "stale", "tree": "<tree
id>"}, `fresh` exactly when `changed` is empty. It reads no project contract,
takes no lock and writes nothing.
```

   Change `Neither verb changes the real index, HEAD or` to `No verb changes the real index, HEAD or`. Replace the docstring's last two lines (`consumed). argparse's usage errors also exit 2:` / `neither verb takes a verification id.`) with:

```text
consumed). `fresh` exits 2 the same way for a `--since` that names no commit,
a `--record` outside the worktree or a git failure. argparse's usage errors
also exit 2: no verb takes a verification id.
```

   `plan_lock`'s docstring becomes `"""Hold the exclusive lock under which `check` and `record` read and write the plan."""`.

6. In `python/README.md` § `verified-tree`, change `(#263). Both verbs read the worktree's own` to `` (#263). `check` and `record` read the worktree's own ``, and `both verbs touch the plan under an exclusive lock` to `` `check` and `record` touch the plan under an exclusive lock ``. Append this sentence to the end of that paragraph, after one space:

```text
`verified-tree fresh --since <commit> --record <path>` (issue 477) judges evidence measured at a commit: it prints `{changed, since, status, tree}`, where `changed` lists the paths that differ between that commit's tree and the current tree, the acceptance record's own path excluded, and `status` is `fresh` only when `changed` is empty; it reads no contract and writes nothing, and sdd's final review and conformance reviewer run it instead of judging a measured surface by hand.
```

- [ ] **Step 4: Verify**

Run the Step 2 command.
Expected: `Ran 41 tests`, `OK`.

Run (timeout 120 s): `bash -c 'set -e; F=python/agent_tools/verified_tree.py; R=python/README.md; PYTHONPATH="$PWD/python" python3 -m agent_tools.verified_tree --help | grep -q "verified-tree fresh --since <commit> --record <path>"; grep -q "verified-tree fresh --since <commit> --record <path>" "$R"; if grep -n -i "both verbs\|neither verb" "$F" "$R"; then exit 1; fi; test "$(grep -c "diff-tree" "$F")" -le 3'`
Expected: exit 0. At the start commit it exits 1, because `--help` has no `fresh` paragraph.

Run the Build (Global Constraints).
Expected: no error line; the agent-tools package is rebuilt from the edited module.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/verified_tree.py python/README.md tests/test_verified_tree.py
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(verified-tree): add the fresh verb (issue 477)" -m "<trailers>"
```
