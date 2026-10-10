# Task 8: Installed `workflow-state`, skill text, READMEs and the final gate

Two parts, one reviewer gate: A puts installed `workflow-state` under the agent_tools interpreter (D11, D16); B updates the skill text and READMEs. Both end on the same `just build` and installed-layout run, which the final gate repeats once (D30).

**Files:**
- Modify (A): `lib/agent-tools.nix` (export a script launcher builder)
- Modify (A): `home/common/agent-skills/default.nix` (`.agents/bin/workflow-state` becomes that launcher)
- Modify (A): `tests/test_agent_tools_launchers.py`
- Modify (A): `home/common/agent-skills/scripts/workflow-state.py` (`artifact_budget_paths`'s installed policy fallback only, D38)
- Modify (B): `home/common/claude-code/skills/orchestrate-issues/SKILL.md` (§2 "Bootstrap and observe", the mint sentence and the `init-run` code block only)
- Modify (B): `home/common/agent-skills/skills/from-issue/acquire-durable.md` (line 3's run-id clause only)
- Modify (B): `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (pin the new machine text)
- Modify (B): `python/README.md` (§ Transaction core)
- Modify (B): `home/common/agent-skills/README.md` (§ Lifecycle helpers: new `### Run identity and migrate` subsection)

**Interfaces (A):**
- Consumes: `workflow-state.py`'s plain imports of `agent_tools.attempt_identity` (Task 2) and `agent_tools.attempt_store` (Task 4, which imports `agent_tools.transaction_core`) — installed, those must resolve to the store package, never to a caller's `PYTHONPATH`. `lib/agent-tools.nix` builds every module under `python/agent_tools` into the environment and import-checks it, so `attempt_store` needs no Nix edit; the installed `init-run --creation-key` test below exercises it.
- Produces:
  - `lib/agent-tools.nix` returns `{ launchers; scriptLauncher; }` where `scriptLauncher = name: script: pkgs.writeShellScript "agent-tools-${name}" ''unset NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE\nexec ${env}/bin/python3 -I ${script} "$@"\n''` — the same environment and the same `unset` line as the `-m` launchers, running a store copy of `script` (D11, D16).
  - `home/common/agent-skills/default.nix`: `".agents/bin/workflow-state".source = agentTools.scriptLauncher "workflow-state" ./scripts/workflow-state.py;` (the `executable = true` attribute goes; `writeShellScript` output is executable). The `.agents/lib/python/workflow_delivery*.py`, `delivery_model` and `host_admission.py` entries stay: the script still path-loads them from `~/.agents/lib/python` (D16).
  - In `tests/test_agent_tools_launchers.py`: the `SCRIPT_LAUNCHER` regex and three tests in the class that defines `launchers()`.
  - In `workflow-state.py`'s `artifact_budget_paths`: when `Path(__file__).parent.parent / "share/artifact-budget-policy.json"` is not a file, fall back to `Path.home() / ".agents/share/artifact-budget-policy.json"`, as the CLI already falls back to `~/.agents/bin/artifact-budget`; the docstring names both installed locations. Nothing else in the script changes.

**Interfaces (B):**
- Consumes: the CLI as built by Tasks 2–6: `workflow-state init-run --repo-root <r> --creation-key <key>` (reply `run_id`), `init-run --run-id <id>` (re-bootstrap of an existing run only), `workflow-state migrate --repo-root <r> [--apply]`, the `attempt-migration-report/v1` report; `direct-owner` minting (Task 3); the installed launcher (part A).
- Produces: skill text and docs only; the pinned strings below.

**Invariants (A):**
- Installed, `workflow-state` runs `python3 -I` from the agent_tools environment: `PYTHON*` variables, the working directory and the user site are ignored, and the launcher clears `NIX_PYTHON*` (D16).
- The script's installed-mode branches still hold: `Path(__file__).parent.name != "scripts"` for a store copy (`/nix/store/<hash>-workflow-state.py` has parent `store`), so `_delivery()` loads `~/.agents/lib/python/workflow_delivery.py`, `_host_admission()` loads `~/.agents/lib/python/host_admission.py`, `resolve_project_argv()` falls back to `~/.agents/bin/resolve-project`, and `artifact_budget_paths()` falls back to `~/.agents/bin/artifact-budget` and, with this task's edit, `~/.agents/share/artifact-budget-policy.json`. Without that edit the store copy looks for `/nix/share/artifact-budget-policy.json`, `phase_notes_maximum()` raises "artifact-budget policy is unavailable", and every command that builds the delivery runtime, `init-run` included, exits 2 (D38). Confirm this by reading those four functions at the task's head; if the store copy's parent name could be `scripts`, stop and report BLOCKED.
- `NOT_LAUNCHERS = ("workflow-state",)` stays true: the new launcher is not an `-m agent_tools.<module>` launcher, so `LAUNCHER.fullmatch` must not match it; update the comment above `NOT_LAUNCHERS` to say `workflow-state` is a script launcher under the same interpreter, checked by `SCRIPT_LAUNCHER`.
- Its interpreter path equals the `-m` launchers' interpreter path (one environment).

**Invariants (B):**
- orchestrate-issues §2: the reuse rule is unchanged (list `<ledger_repo_root>/.superpowers/workflows/` for a run covering the same issue set with a non-final attempt or a missing outcome; reuse its id — #339 owns that listing). The sentence "Only when none matches do you mint a new one." becomes: only when none matches, call `init-run` with `--creation-key orchestrate-issues:<YYYYMMDD>:<issue numbers in caller order joined by ->` and take `run_id` from the validated bootstrap; a reused run is re-bootstrapped with `--run-id <run-id>`. The code block shows both forms, each piped through `artifact-budget validate-report --boundary workflow-response --input -` exactly as the current block is.
- acquire-durable.md line 3: "resolve an immutable `ledger_repo_root` and a stable run ID, call bounded `workflow-state init-run`" becomes "resolve an immutable `ledger_repo_root`, call bounded `workflow-state init-run --creation-key from-issue:<num>:<YYYYMMDD>` (or `--run-id <run-id>` to re-bootstrap the run it created) and take `run_id` from the validated `workflow_bootstrap`"; the rest of the line is unchanged, and the ordered strings `test_from_issue_standalone_modes_use_live_lifecycle_interfaces` pins (`workflow-state init-run` → `max_parallel: 1` → `workflow-state control` → first `spawn` envelope) still appear in that order.
- No ceiling in `home/common/agent-skills/instruction-load.json` changes and that file is not edited (D22). If `just agent-instruction-budget` reports a profile over its ceiling, condense the edited §2 paragraph (not other text) until it passes.
- `python/README.md` § Transaction core: replace "with no command-table row and no caller until #125's cutover" with a clause that names its first caller as it now is — `workflow-state` mints one created-only *run transaction* per attempt run in `<ledger root>/.superpowers/attempt-transactions/` through `agent_tools.attempt_identity` (pure rules) and `agent_tools.attempt_store` (store root, mint lock, binding and `migrate`'s rows), and finds it by the read-only `TransactionStore.lookup` — then cite #337. Keep the slice list unchanged.
- agent-skills README `### Run identity and migrate` (written from the code as built, one paragraph, cite #337 and the spec): every run's identity is a core `rel_` UUIDv7 run transaction; `init-run --creation-key` and `direct-owner` mint new runs named by that id, `init-run --run-id` only re-bootstraps; schema-8 ledgers carry `transaction_id`, and a schema ≤ 7 ledger in one of the four legacy dialects is bound on its next locked write or by `workflow-state migrate --apply` after a read-only dry run, keeping its legacy id as its handle; refusals (`unknown_schema`, `invalid_state`, `unknown_dialect`, `ambiguous_lineage`, `location_mismatch`) leave the ledger's bytes untouched and are reported with exit 0; a helper from before schema 8 refuses a migrated ledger and there is no reverse migration (D10); installed `workflow-state` runs under the agent_tools interpreter with `-I` (D16).
- `home/common/agent-skills/README.md`'s new subsection also names the two modules: `agent_tools.attempt_identity` for the grammar, plan and report, `agent_tools.attempt_store` for the store, binding and `migrate` rows (D27).

- [ ] **Step 1: Write the failing tests**

A — Add to `tests/test_agent_tools_launchers.py`, beside `LAUNCHER`:

```python
SCRIPT_LAUNCHER = re.compile(
    rb"#![^\n]+\n"
    rb"unset NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE\n"
    rb"exec (?P<python>/nix/store/[^/\s]+/bin/python3)"
    rb' -I (?P<script>/nix/store/[^/\s]+-workflow-state\.py) "\$@"\n*'
)
```

and, in the class that defines `launchers()` (so `self.root`, `self.hostile`, `hostile_env()`, `dependency_env()` and `run_child()` are available), these tests:

```python
    def workflow_state_launcher(self):
        data = (self.root / ".agents/bin/workflow-state").read_bytes()
        match = SCRIPT_LAUNCHER.fullmatch(data)
        self.assertIsNotNone(match, data[:300])
        return match

    def test_workflow_state_runs_under_the_package_interpreter(self):
        match = self.workflow_state_launcher()
        pythons = {python for python, _module in self.launchers().values()}
        self.assertEqual(pythons, {match["python"].decode()})

    def test_workflow_state_ignores_a_hostile_agent_tools(self):
        completed = self.run_child(
            [str(self.root / ".agents/bin/workflow-state"), "--help"],
            self.hostile_env(), self.hostile)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(completed.stdout.startswith("usage: workflow-state "))
        self.assertNotIn(MARKER, completed.stdout + completed.stderr)

    def test_installed_workflow_state_mints_a_run_against_the_store_core(self):
        with tempfile.TemporaryDirectory() as repo:
            completed = self.run_child(
                [str(self.root / ".agents/bin/workflow-state"), "init-run", "--repo-root",
                 repo, "--creation-key", "installed-check"],
                self.hostile_env(), self.hostile)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertRegex(json.loads(completed.stdout)["run_id"], r"^rel_[0-9a-f-]{36}$")
            self.assertNotIn(MARKER, completed.stdout + completed.stderr)
            self.assertTrue((Path(repo) / ".superpowers/attempt-transactions").is_dir())
```

`hostile_env()` sets `HOME` to a directory whose `.agents` links to the built tree, so the installed delivery runtime and host-admission library resolve from the build. If `init-run` needs `~/.agents/share/host-declaration.json` and the built tree lacks it, the test creates nothing there: `init-run` does not read the declaration (only `control` and `host-route` do); confirm by running it.

B — In `test_workflow_skill_contracts.py`, extend `ORCHESTRATE_MACHINE_TEXT[ORCHESTRATE]` with the exact argv fragment `"workflow-state init-run --repo-root <ledger_repo_root> --creation-key orchestrate-issues:<YYYYMMDD>:"`, and add to `test_from_issue_standalone_modes_use_live_lifecycle_interfaces`:

```python
        self.assertIn("workflow-state init-run --creation-key from-issue:<num>:<YYYYMMDD>",
                      durable)
```

Pin only the argv (`docs/standards/agent-helpers.md` rule 6): no assertion on the removed English phrase.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k carry_their_machine_text -k standalone_modes`
Expected: FAIL — the new fragments are absent.
Run (timeout 3600 s; it builds): `just agent-installed-skill-tests 2>&1 | tail -20`
Expected: FAIL in `test_workflow_state_runs_under_the_package_interpreter` (the installed entry is the raw script, so `SCRIPT_LAUNCHER` does not match) and `test_installed_workflow_state_mints_a_run_against_the_store_core` (the raw script under `/usr/bin/env python3` cannot import `agent_tools.attempt_identity`). If the mint test passes the import but fails on "artifact-budget policy is unavailable", the policy fallback is missing.

- [ ] **Step 3: Write the Nix change (A)**

Edit the two Nix files and `artifact_budget_paths` per Interfaces. Keep the comment block in `lib/agent-tools.nix` truthful: the file now builds the `-m` launchers from the command table and one script launcher, `workflow-state`, which runs a flat script under the same isolated interpreter until #178 moves it into the package.

- [ ] **Step 4: Edit the skill text and READMEs (B)**

Make the edits in Invariants. `orchestrate-issues/evals/evals.json` mentions `init-run` without its flags and stays unchanged.

- [ ] **Step 5: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_skill_lint.py home/common/agent-skills/tests/test_instruction_load.py` — OK.
Run: `just agent-instruction-budget 2>&1 | tail -5` — passes with no `--raise-label`.

- [ ] **Step 6: Commit**

Stage A's four files and commit with `launch-commit … -- -m "build: run installed workflow-state under the agent_tools interpreter (#337)"`; stage B's five files and commit with `launch-commit … -- -m "docs: run identity and migrate in the skills and READMEs (#337)"`; both with the session trailers. Then `git diff --quiet 907dba234933e1457c2883530bf5f1b83e07a0ec..HEAD -- home/common/agent-skills/instruction-load.json` — exit 0.

- [ ] **Step 7: Final gate (once, on the final head)**

Run: `just build` (timeout 3600 s) — succeeds.
Run: `just agent-workflow-tests > "$SCRATCH/final.log" 2>&1; tail -5 "$SCRATCH/final.log"` (timeout 3600 s) — ends `OK`; `grep -cE '^(FAIL|ERROR):' "$SCRATCH/final.log"` prints `0`.
Run: `just agent-installed-skill-tests 2>&1 | tail -5` (timeout 3600 s) — ends `OK`.
Run: `git diff --stat 907dba234933e1457c2883530bf5f1b83e07a0ec..HEAD -- home/common/agent-skills/tests/fixtures/admission-replay/baseline.json` — prints nothing (AC5: the replay keeps its committed baseline).
No step of this gate runs any `workflow-state` against `/Users/anis/tmp/nix-config/.superpowers` (Global Constraints).
Run: `git diff -U10 907dba234933e1457c2883530bf5f1b83e07a0ec..HEAD -- home/common/agent-skills/scripts/workflow-state.py | wc -c` — at most 60000 (D29, D33).
Run: `review-package .agents/artifacts/plans/2026-10-09-issue-337-attempt-identity-migration.md 907dba234933e1457c2883530bf5f1b83e07a0ec "$(git rev-parse HEAD)" "$SCRATCH/review-final.json" | artifact-budget validate-report --boundary producer --input -` — `"state":"complete"`.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[80,72],"id":8,"records":[{"bounds":[{"added_lines":12,"boundary":"attempt-identity","deleted_lines":2,"record_bytes":3500,"support":{"covers":["t8-1"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t8-1","last_task":8,"owner":8,"path":"lib/agent-tools.nix"},{"bounds":[{"added_lines":1,"boundary":"attempt-identity","deleted_lines":2,"record_bytes":3000,"support":{"covers":["t8-2"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t8-2","last_task":8,"owner":8,"path":"home/common/agent-skills/default.nix"},{"bounds":[{"added_lines":70,"boundary":"attempt-identity","deleted_lines":2,"record_bytes":7000,"support":{"covers":["t8-3"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t8-3","last_task":8,"owner":8,"path":"tests/test_agent_tools_launchers.py"},{"bounds":[{"added_lines":8,"boundary":"attempt-identity","deleted_lines":4,"record_bytes":4500,"support":{"covers":["t8-4"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t8-4","last_task":8,"owner":8,"path":"home/common/claude-code/skills/orchestrate-issues/SKILL.md"},{"bounds":[{"added_lines":1,"boundary":"attempt-identity","deleted_lines":1,"record_bytes":2500,"support":{"covers":["t8-5"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t8-5","last_task":8,"owner":8,"path":"home/common/agent-skills/skills/from-issue/acquire-durable.md"},{"bounds":[{"added_lines":20,"boundary":"attempt-identity","deleted_lines":2,"record_bytes":5000,"support":{"covers":["t8-6"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t8-6","last_task":8,"owner":8,"path":"home/common/agent-skills/tests/test_workflow_skill_contracts.py"},{"bounds":[{"added_lines":2,"boundary":"attempt-identity","deleted_lines":1,"record_bytes":10000,"support":{"covers":["t8-7"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t8-7","last_task":8,"owner":8,"path":"python/README.md"},{"bounds":[{"added_lines":4,"boundary":"attempt-identity","deleted_lines":0,"record_bytes":12000,"support":{"covers":["t8-8"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t8-8","last_task":8,"owner":8,"path":"home/common/agent-skills/README.md"},{"bounds":[{"added_lines":222,"boundary":"attempt-identity","deleted_lines":97,"record_bytes":59000,"support":{"covers":["t5-1","t6-2","t8-9"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t8-9","last_task":8,"owner":8,"path":"home/common/agent-skills/scripts/workflow-state.py"}]}}
```
