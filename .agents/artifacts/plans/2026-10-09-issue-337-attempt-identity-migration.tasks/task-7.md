# Task 7: Installed `workflow-state` under the agent_tools interpreter

**Files:**
- Modify: `lib/agent-tools.nix` (export a script launcher builder)
- Modify: `home/common/agent-skills/default.nix` (`.agents/bin/workflow-state` becomes that launcher)
- Modify: `tests/test_agent_tools_launchers.py`

**Interfaces:**
- Consumes: `workflow-state.py`'s plain `import agent_tools.attempt_identity` / `agent_tools.transaction_core` (Task 2) — installed, those must resolve to the store package, never to a caller's `PYTHONPATH`.
- Produces:
  - `lib/agent-tools.nix` returns `{ launchers; scriptLauncher; }` where `scriptLauncher = name: script: pkgs.writeShellScript "agent-tools-${name}" ''unset NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE\nexec ${env}/bin/python3 -I ${script} "$@"\n''` — the same environment and the same `unset` line as the `-m` launchers, running a store copy of `script` (D11, D16).
  - `home/common/agent-skills/default.nix`: `".agents/bin/workflow-state".source = agentTools.scriptLauncher "workflow-state" ./scripts/workflow-state.py;` (the `executable = true` attribute goes; `writeShellScript` output is executable). The `.agents/lib/python/workflow_delivery*.py`, `delivery_model` and `host_admission.py` entries stay: the script still path-loads them from `~/.agents/lib/python` (D16).
  - In `tests/test_agent_tools_launchers.py`: `SCRIPT_LAUNCHER` regex and a new test class `WorkflowStateLauncherTest`.

**Invariants:**
- Installed, `workflow-state` runs `python3 -I` from the agent_tools environment: `PYTHON*` variables, the working directory and the user site are ignored, and the launcher clears `NIX_PYTHON*` (D16).
- The script's installed-mode branches still hold: `Path(__file__).parent.name != "scripts"` for a store copy (`/nix/store/<hash>-workflow-state.py` has parent `store`), so `_delivery()` loads `~/.agents/lib/python/workflow_delivery.py`, `_host_admission()` loads `~/.agents/lib/python/host_admission.py`, and `resolve_project_argv()` falls back to `~/.agents/bin/resolve-project`. Confirm this by reading those three functions at the task's head; if the store copy's parent name could be `scripts`, stop and report BLOCKED.
- `NOT_LAUNCHERS = ("workflow-state",)` stays true: the new launcher is not an `-m agent_tools.<module>` launcher, so `LAUNCHER.fullmatch` must not match it; update the comment above `NOT_LAUNCHERS` to say `workflow-state` is a script launcher under the same interpreter, checked by `SCRIPT_LAUNCHER`.
- Its interpreter path equals the `-m` launchers' interpreter path (one environment).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_agent_tools_launchers.py`, beside `LAUNCHER`:

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

- [ ] **Step 2: Run the tests and watch them fail**

Run (≥ 3600 s timeout; it builds): `just agent-installed-skill-tests 2>&1 | tail -20`
Expected: FAIL in `test_workflow_state_runs_under_the_package_interpreter` (the installed entry is the raw script, so `SCRIPT_LAUNCHER` does not match) and `test_installed_workflow_state_mints_a_run_against_the_store_core` (the raw script under `/usr/bin/env python3` cannot import `agent_tools.attempt_identity`).

- [ ] **Step 3: Write the minimal implementation**

Edit the two Nix files per Interfaces. Keep the comment block in `lib/agent-tools.nix` truthful: the file now builds the `-m` launchers from the command table and one script launcher, `workflow-state`, which runs a flat script under the same isolated interpreter until #178 moves it into the package.

- [ ] **Step 4: Verify**

Run: `just build` (≥ 3600 s) — succeeds.
Run: `just agent-installed-skill-tests 2>&1 | tail -5` (≥ 3600 s) — ends with `OK`.

- [ ] **Step 5: Commit**

Stage the three files, then `launch-commit … -- -m "build: run installed workflow-state under the agent_tools interpreter (#337)"` with the session trailers.
