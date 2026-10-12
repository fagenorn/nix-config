# Task 3: Row check at use under an invocation deadline

Spec section 2 (`--derive-bin`, the row-check script), section 3 "Guard" steps 3–4, "Bound and cost", "Unreachable `origin` or provider" and "Environment and concurrency" (per D2, D3, D6, D7, D8, D10). After this task a compiled row authorizes nothing until the row check confirms it in the same invocation.

**Files:**
- Modify: `home/common/claude-code/lifecycle_guard.py`
- Modify: `home/common/claude-code/default.nix`
- Test: `tests/test_claude_permission_guard.py`
- Modify: `tests/guard_policy_world.py`

**Interfaces:**
- Consumes (Task 1): `python -m agent_tools.guard_policy derive --repository <slug>`, its report keys and exit statuses. (Task 2): `Context(args, base, cwd)`, `row_problem`, `derived_row`, `ownership_problem`, `write_policy`, `write_base`, `invoke_raw(..., timeout=5)`.
- Produces:
  - Guard: `INVOCATION_DEADLINE_SECONDS = 27`; argv `--derive-bin` (required) and `--derive-timeout-seconds` (float, default 15); `Context(args, base, cwd, deadline)` where `deadline` is `time.monotonic()` at the top of `main` plus 27; `Context.timeout` becomes a read-only property, `max(0.01, min(args.child_timeout_seconds, deadline - time.monotonic()))`; `row_check_problem(derive_bin, repository, row, timeout) -> str | None`.
  - Nix: `lifecycleGuardRowCheck`, a `pkgs.writeShellScript "claude-guard-row-check"` that exports `PATH="<store git, gh, openssh bin>:$PATH"` and runs `exec ${agentTools.launchers.guard-policy} derive "$@"`; that PATH string is one `let` binding shared with `claudeGuardPolicy`. Not added to `home.packages`.
  - Test support: `GuardPolicyWorld.row_check() -> Path`, an executable `/bin/sh` script in the world's temp dir that exports the world's `HOME`, `PATH`, `PYTHONPATH`, `GIT_CONFIG_GLOBAL` and `GIT_CONFIG_SYSTEM` (values `shlex.quote`d) and runs `exec <sys.executable> -m agent_tools.guard_policy derive "$@"`.
  - Guard suite: `FAKE_DERIVE_SCRIPT` stub, `cls.fake_derive`, `rows_env(rows) -> dict`, `run_guard(..., timeout=5)` passed through to `invoke_raw`.

**Invariants:**
- Context order for a repository `S` with a compiled row (spec section 3): (1) literal conflict, (2) `origin/HEAD` against the row's `default_branch`, (3) the row check, (4) the comparison. The first problem found is `row_problem`; later steps do not run. A repository with no row runs no row check and makes no network read.
- The row check runs at most once per invocation, when the context is built, as `[derive_bin, "--repository", S]` with stdin `/dev/null`, stdout and stderr captured, `start_new_session=True`, the guard's own environment, bounded by `min(--derive-timeout-seconds, deadline - now)` (floor 0.01). On the bound the guard sends `SIGKILL` to the child's whole process group (`os.killpg`, `ProcessLookupError` ignored) and reaps the direct child with `wait()`, never reading the pipes again.
- Every other child started once the context exists takes `Context.timeout`, so no verdict waits past the deadline by more than one child's teardown (R6).
- The report is confirmed only when: stdout parses as one JSON object; its `repository` is `S`; its `outcome` matches the exit status (`derived`/0, `refused`/1, `unavailable`/2); for `derived`, `row` is an object whose `default_branch` and `integration_branch` are strings equal to the compiled row's. `evidence` is never compared. A row that fails is never used and the owner literal is never consulted for `S`.
- Refusal text, verbatim: `repository {S}: the row check did not confirm its derived policy row: {why}; repair: run claude-guard-policy`, with `why` one of:
  - `could not start ({error})` — `OSError` from `Popen`
  - `timed out`
  - `unreadable report (exit {code})` — any shape failure above
  - `refused (no registered project derives it)` — `refused` with an empty list
  - `refused ({codes})` — the `reason_code` of each `refused` item, `, `-joined
  - `unavailable ({reason_code})` — the report's `cause.reason_code`
  - `it derives {default} and {integration}, the row names {row_default} and {row_integration}`
- The registered command stays one argument-free store path; only the wrapper names `--derive-bin`.

- [ ] **Step 1: Write the failing tests**

`tests/test_claude_permission_guard.py`:

(a) `import time` at the top. After `FAKE_GH_SCRIPT`, add the stub row check (the `@ROWS@` marker is replaced, not `str.format`ted, because the script holds braces):

```python
# Stand-in for the row check (`guard-policy derive`). Answers from a JSON object
# of slug -> row: FAKE_DERIVE_ROWS names one, else the class default (Nodo's row).
# FAKE_DERIVE_MODE: rows (default), refused_code, unavailable, garbage, hang.
# FAKE_DERIVE_LOG appends each slug asked; FAKE_DERIVE_PIDFILE receives the pid
# of the grandchild `hang` leaves behind.
FAKE_DERIVE_SCRIPT = '''
import json
import os
import subprocess
import sys
import time

argv = sys.argv[1:]
if len(argv) != 2 or argv[0] != "--repository":
    print("unexpected fake-derive argv: " + repr(argv), file=sys.stderr)
    raise SystemExit(64)
slug = argv[1]
log = os.environ.get("FAKE_DERIVE_LOG")
if log:
    with open(log, "a", encoding="utf-8") as stream:
        stream.write(slug + "\\n")
mode = os.environ.get("FAKE_DERIVE_MODE", "rows")
if mode == "hang":
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    with open(os.environ["FAKE_DERIVE_PIDFILE"], "w", encoding="utf-8") as stream:
        stream.write(str(sleeper.pid))
    time.sleep(600)
if mode == "garbage":
    print("{")
    raise SystemExit(0)
report = {"schema_version": 1, "repository": slug, "row": None, "refused": [], "cause": None}
if mode == "unavailable":
    report.update(outcome="unavailable", cause={"reason_code": "registry_invalid", "detail": "x"})
    print(json.dumps(report))
    raise SystemExit(2)
if mode == "refused_code":
    report.update(outcome="refused", refused=[
        {"project_id": "p", "root": "/p", "reason_code": "fetch_failed", "detail": "x"}])
    print(json.dumps(report))
    raise SystemExit(1)
with open(os.environ.get("FAKE_DERIVE_ROWS", @ROWS@), encoding="utf-8") as stream:
    rows = json.load(stream)
if slug in rows:
    report.update(outcome="derived", row=rows[slug])
    print(json.dumps(report))
    raise SystemExit(0)
report.update(outcome="refused")
print(json.dumps(report))
raise SystemExit(1)
'''
```

(b) In `setUpClass`: add `"--derive-timeout-seconds"` to `override_flags`; after the fake `gh`, write `derive-rows.json` (`{NODO: NODO_ROW}`) in the fixture dir and `cls.fake_derive` (mode 0o755) from `f"#!{sys.executable}\n" + FAKE_DERIVE_SCRIPT.replace("@ROWS@", repr(str(rows_path)))`. In `invoke_raw`, append `("--derive-bin", str(self.fake_derive))` when `--derive-bin` is absent. `run_guard` gains `timeout=5` and passes it on. Add:

```python
    def rows_env(self, rows):
        """Env making the stub row check answer from `rows` (slug -> row)."""
        handle, name = tempfile.mkstemp(dir=self.fixture_dir.name, suffix=".json")
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(rows, stream)
        return {"FAKE_DERIVE_ROWS": name}

    def assert_row_check_killed(self, pidfile):
        pid = int(pidfile.read_text(encoding="utf-8"))
        give_up = time.monotonic() + 5
        while True:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            if time.monotonic() > give_up:
                self.fail(f"row-check grandchild {pid} outlived the verdict")
            time.sleep(0.1)
```

(c) Existing tests keep every assertion. A test whose compiled row the default stub does not confirm passes `env=self.rows_env({...that row...})` (merged with any env it already passes) — at least `test_single_branch_derived_row_keeps_the_default_branch_only_rule` (`acme/tool`). `test_registered_hook_names_the_base_and_compiled_policies` becomes:

```python
    def test_registered_hook_names_the_base_policy_compiled_policy_and_row_check(self):
        wrapper = self.guard.read_text(encoding="utf-8")
        self.assertRegex(wrapper, r'--base-policy /nix/store/\S+-claude-bash-lifecycle-guard-'
                                  r'base-policy\.json --policy /\S+/\.agents/state/guard/'
                                  r'policy\.json --derive-bin /nix/store/\S+-claude-guard-'
                                  r'row-check "\$@"\n')
        self.assertIn(f"--base-policy {BASE_POLICY_PATH} ", wrapper)
        row_check = Path(wrapper.split("--derive-bin ", 1)[1].split(" ", 1)[0])
        script = row_check.read_text(encoding="utf-8")
        self.assertRegex(script, r'export PATH="/nix/store/\S+-git-[^:"]+/bin:')
        self.assertRegex(script, r'exec /nix/store/\S+-agent-tools-guard-policy derive "\$@"\n')
```

(d) The two round-trip tests use the real derivation. In `test_a_compiled_policy_round_trips_through_the_guard`, `args` becomes `("--gh-bin", str(self.fake_gh), "--policy", str(world.output), "--derive-bin", str(world.row_check()), "--derive-timeout-seconds", "25")`, each `run_guard` there passes `timeout=60`, and the test ends with the forged row:

```python
        forged = json.loads(world.output.read_text(encoding="utf-8"))
        forged["derived_repositories"]["acme/forged"] = {
            "default_branch": "main", "integration_branch": "main", "evidence": {}}
        forged_args = (*args, "--policy", str(self.write_policy(**forged)))
        forged_repo = self.make_repo("git@github.com:acme/forged.git")
        refused = self.run_guard("git push -u origin topic", cwd=forged_repo,
                                 guard_args=forged_args, timeout=60)
        self.assertEqual(2, refused.returncode)
        self.assertIn("repository acme/forged: the row check did not confirm its derived policy "
                      "row: refused (no registered project derives it); repair: run "
                      "claude-guard-policy", refused.stderr)
```

`test_a_compiled_policy_loads_whatever_branch_names_the_fleet_carries` takes the same `--derive-bin`/`--derive-timeout-seconds` arguments and `timeout=60` on the invocations that judge a repository with a row.

(e) New tests:

```python
    FOUR_VERBS = (
        ("push", "git push -u origin topic"),
        ("PR creation", 'gh pr create --repo {slug} --base {base} --head t '
                        '--title "x" --body "y"'),
        ("merge", "gh pr merge 7 --repo {slug} --merge --delete-branch"),
        ("release creation", 'gh release create v1.2.3 --repo {slug} --verify-tag '
                             '--title "v1.2.3" --notes-file notes.md'),
    )

    def assert_unconfirmed(self, slug, why, base="main", exact=True, **run):
        """Every repository-bound verb on `slug` is refused for `why`; `exact=False` checks
        only the text up to `why`, for a reason that ends in an OS message."""
        repo = self.make_repo(f"git@github.com:{slug}.git")
        for label, template in self.FOUR_VERBS:
            with self.subTest(slug=slug, verb=label):
                result = self.run_guard(template.format(slug=slug, base=base), cwd=repo, **run)
                self.assertEqual(2, result.returncode, result.stderr)
                expected = (f"lifecycle guard: unsafe {label}: repository {slug}: the row check "
                            f"did not confirm its derived policy row: {why}")
                if exact:
                    expected += "; repair: run claude-guard-policy"
                self.assertIn(expected, result.stderr)

    def test_a_row_for_an_unregistered_repository_is_refused_at_use(self):
        """Issue 377 criterion 3, R2, R3."""
        slug = "acme/forged"
        policy = self.write_policy(derivation={}, derived_repositories={
            NODO: NODO_ROW,
            slug: {"default_branch": "main", "integration_branch": "main", "evidence": {}}})
        args = ("--gh-bin", str(self.fake_gh), "--policy", str(policy))
        self.assert_unconfirmed(slug, "refused (no registered project derives it)",
                                guard_args=args)
        self.assert_unconfirmed(slug, "refused (fetch_failed)", guard_args=args,
                                env={"FAKE_DERIVE_MODE": "refused_code"})

    def test_a_row_whose_branches_differ_from_the_derivation_is_refused(self):
        """Issue 377 R3, D2: a forged integration branch never widens a target."""
        forged = self.write_policy(derivation={}, derived_repositories={
            NODO: {**NODO_ROW, "integration_branch": "evil"}})
        self.assert_unconfirmed(
            NODO, "it derives main and dev, the row names main and evil", base="evil",
            guard_args=("--gh-bin", str(self.fake_gh), "--policy", str(forged)))
        literal = "fagenorn/tool"
        widened = self.write_policy(derivation={}, derived_repositories={
            literal: {"default_branch": "main", "integration_branch": "dev", "evidence": {}}})
        self.assert_unconfirmed(
            literal, "it derives main and main, the row names main and dev", base="dev",
            guard_args=("--gh-bin", str(self.fake_gh), "--policy", str(widened)),
            env=self.rows_env({literal: {"default_branch": "main", "integration_branch": "main",
                                         "evidence": {}}}))

    def test_a_failing_row_check_refuses_with_no_fallback(self):
        """Issue 377 R2, D3."""
        for mode, why in (("unavailable", "unavailable (registry_invalid)"),
                          ("garbage", "unreadable report (exit 0)")):
            self.assert_unconfirmed(NODO, why, env={"FAKE_DERIVE_MODE": mode})
        absent = Path(self.fixture_dir.name) / "absent-row-check"
        self.assert_unconfirmed(NODO, "could not start (", exact=False, guard_args=(
            "--gh-bin", str(self.fake_gh), "--derive-bin", str(absent)))
```

```python
    def test_a_row_check_past_its_bound_is_killed_with_its_process_group(self):
        """Issue 377 D6: a grandchild of the row check never outlives the verdict."""
        pidfile = Path(tempfile.mkdtemp(dir=self.fixture_dir.name)) / "pid"
        repo = self.make_repo(f"git@github.com:{NODO}.git")
        result = self.run_guard(
            "git push -u origin topic", cwd=repo,
            guard_args=("--gh-bin", str(self.fake_gh), "--derive-timeout-seconds", "2"),
            env={"FAKE_DERIVE_MODE": "hang", "FAKE_DERIVE_PIDFILE": str(pidfile)})
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn("the row check did not confirm its derived policy row: timed out",
                      result.stderr)
        self.assert_row_check_killed(pidfile)

    def test_the_invocation_deadline_bounds_the_row_check(self):
        """Issue 377 R6, D10: a 60-second bound still answers inside 27 s (slow by design)."""
        pidfile = Path(tempfile.mkdtemp(dir=self.fixture_dir.name)) / "pid"
        repo = self.make_repo(f"git@github.com:{NODO}.git")
        started = time.monotonic()
        result = self.run_guard(
            "git push -u origin topic", cwd=repo, timeout=40,
            guard_args=("--gh-bin", str(self.fake_gh), "--derive-timeout-seconds", "60"),
            env={"FAKE_DERIVE_MODE": "hang", "FAKE_DERIVE_PIDFILE": str(pidfile)})
        elapsed = time.monotonic() - started
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn("timed out", result.stderr)
        self.assertGreater(elapsed, 20)
        self.assertLess(elapsed, 29)
        self.assert_row_check_killed(pidfile)

    def test_the_row_check_runs_once_and_only_for_a_repository_with_a_row(self):
        """Issue 377 section 3: no row, no check and no network read."""
        log = Path(tempfile.mkdtemp(dir=self.fixture_dir.name)) / "derive.log"
        env = {"FAKE_DERIVE_LOG": str(log)}
        literal = self.make_repo("git@github.com:fagenorn/tool.git")
        self.assertEqual(0, self.run_guard("git push -u origin topic", cwd=literal,
                                           env=env).returncode)
        self.assertFalse(log.exists())
        nodo = self.make_repo(f"git@github.com:{NODO}.git")
        result = self.run_guard("git push -u origin topic-a && git push -u origin topic-b",
                                cwd=nodo, env=env)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(f"{NODO}\n", log.read_text(encoding="utf-8"))
```

- [ ] **Step 2: Run the suite and watch it fail**

Run the guard-suite invocation (Global Constraints) with the test edits staged (`git add`).
Expected: FAIL — every invocation errors in argparse on `--derive-bin`, so the output ends in `FAILED` with most tests failing; `test_registered_hook_names_the_base_policy_compiled_policy_and_row_check` among them.

- [ ] **Step 3: Write the minimal implementation**

`home/common/claude-code/lifecycle_guard.py`, to the interfaces, invariants and messages above: `import signal` and `import time`; `INVOCATION_DEADLINE_SECONDS`; the two arguments; `started = time.monotonic()` as the first statement of `main` and `Context(args, base, payload.get("cwd"), started + INVOCATION_DEADLINE_SECONDS)`; the `timeout` property; `row_check_problem` called from `Context.__init__` as step 3 of the row order. Module docstring: the wrapper also passes `--derive-bin`, the row check it runs before relying on a compiled row; written from the code.

`home/common/claude-code/default.nix`: the shared PATH binding, `lifecycleGuardRowCheck`, and the wrapper line `… --policy ${lifecycleGuardPolicyPath} --derive-bin ${lifecycleGuardRowCheck} "$@"`. The comment above `lifecycleGuardRowCheck` says what it runs, that it pins the store `git`, `gh` and `ssh` first on `PATH` as `claude-guard-policy` does, and that it is not installed on `PATH`.

`tests/guard_policy_world.py`: `row_check()` as in Interfaces; the module docstring names it in one sentence.

- [ ] **Step 4: Verify**

Run the guard-suite invocation.
Expected: PASS — `OK`, exit 0; the run takes about 27 s longer than Task 2's.

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_guard_policy.py 2>&1 | tail -4`
Expected: PASS — `OK`.

Run:

```bash
set -e
f=home/common/claude-code/lifecycle_guard.py
grep -q 'start_new_session=True' "$f"
grep -q 'os.killpg(' "$f"
grep -q '^INVOCATION_DEADLINE_SECONDS = 27$' "$f"
if grep -q 'claude-guard-row-check' home/common/claude-code/default.nix; then echo WIRED; else exit 1; fi
```

Expected: `WIRED`.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/lifecycle_guard.py home/common/claude-code/default.nix \
  tests/test_claude_permission_guard.py tests/guard_policy_world.py
launch-commit … -- -m "feat(guard): recheck each derived row at use under an invocation deadline (#377)"
```
