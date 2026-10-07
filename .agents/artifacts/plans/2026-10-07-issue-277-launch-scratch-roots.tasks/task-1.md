# Task 1: `launch-scope scratch` and its record

Spec sections **Command surface** and **Scratch record** are normative; this task cites D1–D4, D8 and D9.

**Files:**
- Modify: `python/agent_tools/launch_scope.py`
- Test: `tests/test_launch_scope.py`

**Interfaces:**
- Consumes (existing, unchanged): `safe_segment`, `worker_action`, `registry_root`, `launch_directory`, `canonical_line`, `ask_launch`, `CURRENT`, `REFUSED_EXIT`, `USAGE_EXIT`, `LaunchScopeError`; `launch_commit.ask_worker`, `LIVE`, `LaunchCommitError`; `launch_processes.require_supported_platform`; `agent_tools.canonical.reject_duplicate_keys`, `reject_nonfinite_literal`.
- Produces (Task 2 relies on these exact names):
  - `SCRATCH_RECORD = "scratch.json"`
  - `SCRATCH_PREFIX = "launch-scope-"`
  - `SCRATCH_NAME = re.compile(r"launch-scope-[a-z0-9_]+")`
  - `def scratch_path(data: bytes) -> str | None` — the record's root path when `data` is a strict, canonical-key `{"path": <str>}` object whose path is absolute, equal to `os.path.realpath` of itself, and whose basename fullmatches `SCRATCH_NAME`; `None` for anything else. It never touches the filesystem beyond `realpath` and never reads `TMPDIR` (D4).
  - `def scratch(repo_root: str, run_id: str, *, action_id: str | None = None, worker_id: str | None = None) -> tuple[int, str | dict]` — `(0, <root real path>)` or `(3, {"action_id", "created": False, "reason"})`; raises `LaunchScopeError` (or `LaunchCommitError`, `UnsupportedPlatform`) for exit 2.
  - Test harness additions on `ScopeHarness`: `self.tmpdir` (a test-owned, unresolved `Path`), `TMPDIR` in `self.env`, `scratch_args(*, action_id="14:1:1", worker_id=None)`, `scratch_(**identity)`, `git(*args) -> str`, `add_worktree(path) -> str` (returns the real path), `worktrees() -> set[str]`, `record_path(action_id="14:1:1") -> Path`.

**Invariants:**
- Repeat calls for one launch print byte-identical output, and a worker (`--worker-id 14:1:1:w<n>`) prints its launch's root (D1).
- A refused call (superseded, released, failed or malformed check) creates no record and no directory under `TMPDIR` (D2).
- A record is written once, by an exclusive `os.link`; it is never overwritten. The loser of a creation race removes its own `mkdtemp` directory (D3).
- A record that `scratch_path` rejects, or a recorded path that exists but is not a real directory (`os.path.islink(p) or not os.path.isdir(p)`), exits 2 with empty stdout and leaves the record's bytes unchanged (D4).
- On an unsupported platform `scratch` exits 2 before creating anything (D9).
- `exec`'s behavior and its tests are unchanged.

- [ ] **Step 1: Write the failing tests**

Add `import stat` to the imports. In `ScopeHarness.setUp`, after `self.env` is built, add:

```python
        # D8: every scratch root a test creates lands in a directory the test owns.
        self.tmpdir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.env["TMPDIR"] = str(self.tmpdir)
```

Add these methods to `ScopeHarness`:

```python
    def scratch_args(self, *, action_id="14:1:1", worker_id=None):
        identity = ["--worker-id", worker_id] if worker_id else ["--action-id", action_id]
        return ["scratch", "--repo-root", str(self.root), "--run-id", self.run_id, *identity]

    def scratch_(self, **identity):
        return self.scope(*self.scratch_args(**identity))

    def record_path(self, action_id="14:1:1"):
        return self.registry / action_id / "scratch.json"

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], env=self.env, check=True,
                              capture_output=True, text=True).stdout

    def add_worktree(self, path):
        """Add a detached worktree at `path` (making the base commit once); its real path."""
        if subprocess.run(["git", "-C", str(self.root), "rev-parse", "--verify", "-q", "HEAD"],
                          env=self.env, capture_output=True).returncode != 0:
            self.git("-c", "user.name=t", "-c", "user.email=t@example.invalid",
                     "commit", "-q", "--allow-empty", "-m", "base")
        self.git("worktree", "add", "-q", "--detach", str(path))
        return os.path.realpath(path)

    def worktrees(self):
        listing = self.git("worktree", "list", "--porcelain", "-z")
        return {os.path.realpath(field[len("worktree "):])
                for field in listing.split("\0") if field.startswith("worktree ")}
```

Add this class after `ExecTest`:

```python
class ScratchTest(ScopeHarness, unittest.TestCase):
    def root_of(self, completed):
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.count("\n"), 1)
        self.assertTrue(completed.stdout.endswith("\n"))
        return completed.stdout[:-1]

    def assert_scratch_refused(self, completed, action_id, reason):
        self.assertEqual(completed.returncode, 3, completed.stderr)
        self.assertEqual(completed.stdout.count("\n"), 1)
        self.assertEqual(json.loads(completed.stdout),
                         {"action_id": action_id, "created": False, "reason": reason})

    def test_repeat_calls_print_one_recorded_root(self):  # AC1
        first = self.scratch_()
        root = self.root_of(first)
        self.assertEqual(self.scratch_().stdout, first.stdout)
        self.assertEqual(self.record_path().read_bytes(),
                         (launch_scope.canonical_line({"path": root}) + "\n").encode())
        # The temp dir sits behind a symlink on darwin (/var -> /private/var): the root is real.
        self.assertEqual(root, os.path.realpath(root))
        self.assertEqual(os.path.dirname(root), os.path.realpath(self.tmpdir))
        self.assertRegex(os.path.basename(root), r"\Alaunch-scope-[a-z0-9_]+\Z")
        self.assertTrue(os.path.isdir(root))
        self.assertEqual([p.name for p in self.tmpdir.iterdir()], [os.path.basename(root)])

    def test_a_worker_gets_its_launchs_root_until_released(self):  # D1
        worker = self.register_worker(action_id="14:1:1",
                                      now="2026-08-13T20:01:00Z")["worker_id"]
        root = self.root_of(self.scratch_(worker_id=worker))
        self.assertEqual(self.root_of(self.scratch_()), root)
        self.release_worker(worker_id=worker, event="returned", now="2026-08-13T20:02:00Z")
        self.assert_scratch_refused(self.scratch_(worker_id=worker), "14:1:1", "released")

    def test_a_refused_launch_gets_no_root(self):  # D2
        self.write_shim("exit 2")
        self.assert_scratch_refused(self.scratch_(), "14:1:1", "check_launch_failed")
        self.write_shim(f"exec {shlex.quote(sys.executable)} {shlex.quote(str(WORKFLOW))} \"$@\"")
        self.assertEqual(self.resume(issue=14, worktree=str(self.root / "wt-14"), now=LATER,
                                     owner_unavailable=True)["id"], "14:1:2")
        self.assert_scratch_refused(self.scratch_(), "14:1:1", "superseded_launch")
        self.assertFalse(self.record_path().exists())
        self.assertEqual(list(self.tmpdir.iterdir()), [])

    def test_a_missing_root_is_recreated_at_its_recorded_path(self):  # D4
        root = self.root_of(self.scratch_())
        os.rmdir(root)
        self.assertEqual(self.root_of(self.scratch_()), root)
        self.assertEqual(stat.S_IMODE(os.stat(root).st_mode), 0o700)

    def test_a_malformed_record_or_a_root_that_is_not_a_directory_exits_two(self):  # D4
        root = self.root_of(self.scratch_())
        real_tmp = os.path.realpath(self.tmpdir)
        link = self.tmpdir / "link"
        link.symlink_to(real_tmp)
        plain = os.path.join(real_tmp, "launch-scope-plainfile")
        Path(plain).write_text("x\n")
        aliased = os.path.join(real_tmp, "launch-scope-aliased")
        os.symlink(root, aliased)

        def canonical(value):
            return (launch_scope.canonical_line(value) + "\n").encode()
        cases = {
            "not json": b"{\n",
            "duplicate key": ('{"path":%s,"path":%s}\n' % (json.dumps(root),
                                                          json.dumps(root))).encode(),
            "extra key": canonical({"path": root, "x": 1}),
            "not a string": canonical({"path": 7}),
            "relative": canonical({"path": os.path.basename(root)}),
            "not its real path": canonical({"path": os.path.join(str(link),
                                                                 os.path.basename(root))}),
            "bad basename": canonical({"path": os.path.join(real_tmp, "other-abc")}),
            "a regular file": canonical({"path": plain}),
            "a symlink": canonical({"path": aliased}),
        }
        good = self.record_path().read_bytes()
        for label, data in cases.items():
            with self.subTest(case=label):
                self.record_path().write_bytes(data)
                done = self.scratch_()
                self.assertEqual((done.returncode, done.stdout), (2, ""), done.stderr)
                self.assertEqual(self.record_path().read_bytes(), data)
        self.record_path().write_bytes(good)
        self.assertEqual(self.root_of(self.scratch_()), root)

    def test_a_caller_that_loses_the_creation_race_uses_the_winners_root(self):  # D3
        winner = os.path.realpath(tempfile.mkdtemp(prefix="launch-scope-", dir=self.tmpdir))
        real_mkdtemp = tempfile.mkdtemp
        mine = []

        def racing_mkdtemp(*args, **kwargs):
            made = real_mkdtemp(*args, **kwargs)
            mine.append(made)
            self.record_path().parent.mkdir(parents=True, exist_ok=True)
            self.record_path().write_text(launch_scope.canonical_line({"path": winner}) + "\n")
            return made
        with mock.patch.dict(os.environ, self.env, clear=True), \
                mock.patch.object(launch_scope.tempfile, "tempdir", str(self.tmpdir)), \
                mock.patch.object(launch_scope.tempfile, "mkdtemp", racing_mkdtemp):
            result = launch_scope.scratch(str(self.root), self.run_id, action_id="14:1:1")
        self.assertEqual(result, (0, winner))
        (made,) = mine
        self.assertFalse(os.path.lexists(made))
        self.assertEqual([p.name for p in self.record_path().parent.iterdir()],
                         ["scratch.json"])

    def test_usage_and_helper_errors_exit_two_and_create_nothing(self):
        not_git = Path(self.enterContext(tempfile.TemporaryDirectory()))
        base = ["scratch", "--repo-root", str(self.root), "--run-id", self.run_id]
        cases = [
            base,
            [*base, "--action-id", "14:1:1", "--worker-id", "14:1:1:w1"],
            [*base, "--action-id", ".."],
            [*base, "--worker-id", "w1"],
            [*base, "--action-id", "14:1:1", "--", "true"],
            ["scratch", "--repo-root", str(self.root), "--run-id", "../x",
             "--action-id", "14:1:1"],
            ["scratch", "--repo-root", str(not_git), "--run-id", self.run_id,
             "--action-id", "14:1:1"],
        ]
        for args in cases:
            with self.subTest(args=args):
                done = self.scope(*args)
                self.assertEqual((done.returncode, done.stdout), (2, ""), done.stderr)
        self.assertFalse(self.record_path().exists())
        self.assertEqual(list(self.tmpdir.iterdir()), [])

    def test_an_unsupported_platform_creates_nothing(self):  # D9
        with mock.patch.dict(os.environ, self.env, clear=True), \
                mock.patch.object(launch_processes.sys, "platform", "win32"), \
                self.assertRaises(UnsupportedPlatform):
            launch_scope.scratch(str(self.root), self.run_id, action_id="14:1:1")
        self.assertFalse(self.record_path().exists())
```

`resume`, `register_worker` and `release_worker` are existing `LifecycleHarness` methods, used as `ExecTest` uses them.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" timeout 600 python3 -m unittest tests.test_launch_scope.ScratchTest 2>&1 | tail -4`
Expected: FAILED — every case errors or fails, because `scratch` is not a verb (argparse exits 2 on the subprocess cases) and `launch_scope.scratch` does not exist.

- [ ] **Step 3: Write the minimal implementation**

In `python/agent_tools/launch_scope.py`:

1. Add `import shutil` and `import tempfile` (Task 2 uses `shutil`; importing it here keeps the import block in one edit). Add the four constants named under **Produces**.
2. Extract `exec_scoped`'s liveness branch into `def _identity_reason(repo_root: str, run_id: str, action: str, worker_id: str | None) -> tuple[str, bool]`: for `worker_id is None` it returns `(ask_launch(...), reason == CURRENT)`; otherwise `(ask_worker(...), reason == LIVE)`, re-raising `LaunchCommitError` as `LaunchScopeError` exactly as `exec_scoped` does today. `exec_scoped` calls it inside its existing `try`, keeping the forwarder install and row deletion where they are.
3. `scratch_path(data)`: `json.loads` with both canonical hooks; `ValueError` → `None`. Require `isinstance(value, dict)`, `set(value) == {"path"}`, `isinstance(path, str)`, `os.path.isabs(path)`, `os.path.realpath(path) == path` and `SCRATCH_NAME.fullmatch(os.path.basename(path))`.
4. `scratch(...)`, in this order:
   1. `require_supported_platform()` (D9); derive `action` as `exec_scoped` does; `safe_segment` the run and action; `registry = registry_root(repo_root)`; `directory = launch_directory(registry, run_id, action)`.
   2. `reason, positive = _identity_reason(...)`; not positive → `return REFUSED_EXIT, {"action_id": action, "created": False, "reason": reason}`.
   3. `root = _read_record(directory / SCRATCH_RECORD)`, where `_read_record` returns `None` on `FileNotFoundError`, raises `LaunchScopeError` on any other `OSError` and on `scratch_path(...) is None` ("malformed scratch record").
   4. `root is None` → `root = _create_record(directory)`: `directory.mkdir(parents=True, exist_ok=True)`; `made = os.path.realpath(tempfile.mkdtemp(prefix=SCRATCH_PREFIX))` (call `tempfile.mkdtemp` through the module attribute, so the race test can patch it); write `canonical_line({"path": made}) + "\n"` to a `tempfile.NamedTemporaryFile(dir=directory, prefix=".scratch.", suffix=".tmp", delete=False)`; `os.link(temp, record)`; on `FileExistsError`, `os.rmdir(made)` and return `_read_record(record)` (a `None` there raises `LaunchScopeError`); always unlink the temp file in a `finally`. On every other failure before the link succeeds (writing the temp file, the link itself), remove `made` and the temp file before re-raising it wrapped as `LaunchScopeError`; once the link succeeds the root is published and is never removed here (D11). Add a test that patches `launch_scope.os.link` to raise `OSError` and asserts exit 2, no `scratch.json`, no `.scratch.*.tmp` file, and an empty `self.tmpdir`.
   5. Recreate or check (D4): if `not os.path.lexists(root)`, `os.mkdir(root, 0o700)`, treating `FileExistsError` as a concurrent recreate; an `OSError` otherwise is `LaunchScopeError`. Then `os.path.islink(root) or not os.path.isdir(root)` → `LaunchScopeError("scratch root ... is not a directory")`.
   6. `return 0, root`.
5. `_parser()`: add the `scratch` subparser with `help="print the launch's scratch root, creating it on first use"`, `usage="%(prog)s --repo-root R --run-id I (--action-id A | --worker-id W)"`, and the same `--repo-root`, `--run-id` and required mutually exclusive `--action-id`/`--worker-id` group as `exec`.
6. `main()`: `scratch` with `--` present is `parser.error(f"scratch takes no {SEPARATOR}")`. On success it writes `root + "\n"` to stdout; a refusal prints `canonical_line(refusal)`. Catch the same exception tuple as today and return `USAGE_EXIT`.
7. Module docstring: add the `scratch` usage line under the existing two, a paragraph stating what `scratch` does (liveness first, one root per launch shared with its workers, `scratch.json` record with `{"path"}`, recreate at the same path), and its exit codes (0 path, 3 refusal line `{"action_id", "created": false, "reason"}`, 2). Write it from the code as implemented in this step.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" timeout 600 python3 -m unittest tests.test_launch_scope 2>&1 | tail -4`
Expected: `OK` — `ScratchTest`'s eight cases pass, and `ExecTest`, `ReapTest` and the process-seam tests still pass.

Run: `PYTHONPATH="$PWD/python" python3 -m agent_tools.launch_scope scratch --help | grep -c -- "--worker-id"`
Expected: `1` or more (at the base commit this exits 2 with "invalid choice: 'scratch'").

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/launch_scope.py tests/test_launch_scope.py
git commit -m "feat(launch-scope): add scratch, one recorded scratch root per launch (#277)"
```
