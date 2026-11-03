# Task 2: The closure pin in the installed tier

Spec § The pin check and § Documentation; per D3, D4, D6, D8 and D10. Replace the interpreter check confined to `~/.agents/bin` with three tests of the built system closure. Task 1 supplies the shared `agentTools` argument. This task adds no package API and changes no guard code.

**Files:**
- Modify: `tests/test_agent_tools_launchers.py`
- Modify: `justfile`
- Modify: `python/README.md` (§ Package and launchers)
- Modify: `home/common/claude-code/README.md` (after the § Guard policy residual list)

**Interfaces:**
- Consumes: `AGENT_SKILLS_INSTALLED_HOME`, the existing installed-home input, and new `AGENT_TOOLS_SYSTEM_RESULT`, an absolute path to the built system result. Both recipes that run this module pass it. When the installed home is unset, the existing class skip remains; a set installed home without the system result is an assertion failure.
- Produces: three tests in `AgentToolsLauncherTest`, with the exact names below. They read package `name` and `version` from `python/pyproject.toml` using standard-library `tomllib`; the builder owns those values.
- Private test helpers: `system_closure() -> list[Path]`, `package_builds() -> set[Path]`, `closure_launchers() -> list[tuple[Path, str]]`. The latter's string is the launcher's absolute environment `bin/python3` path. No helper imports `agent_tools` into the test runner.

**Invariants:**
- The built system closure contains exactly one package whose store basename matches `<hash>-python<interpreter>-<project.name>-<project.version>`.
- Every closure store file named `<hash>-agent-tools-<command>` matches existing `LAUNCHER` or `SCRIPT_LAUNCHER` in full and execs the same environment. Every installed `.agents/bin` entry that names `agent_tools`, and `workflow-state`, resolves to one of those files. Unknown family members fail with their paths.
- Every environment named by these launchers imports `agent_tools` from the unique package build, under the same isolation as the launchers.
- Both installed and retained recipes pass the same absolute `system_result`; no input is inferred from the installed home and no missing input skips a test (D4, D8).
- The new documentation promises generation consistency and describes the installed check. Its limits paragraph covers only the two system limits in D10.

- [ ] **Step 1: Add the pin tests**

Add `tomllib` to imports and `SYSTEM_RESULT_ENV = "AGENT_TOOLS_SYSTEM_RESULT"` beside `INSTALLED_HOME_ENV`. Replace `test_workflow_state_runs_under_the_package_interpreter` with these three tests, written in full here:

```python
    def test_the_system_closure_holds_one_agent_tools_build(self):
        builds = self.package_builds()
        self.assertEqual(len(builds), 1, f"agent_tools builds: {sorted(map(str, builds))}")

    def test_every_launcher_in_the_system_closure_execs_one_environment(self):
        launchers = self.closure_launchers()
        self.assertTrue(launchers, "the system closure has no agent-tools launchers")
        pythons = {python for _path, python in launchers}
        self.assertEqual(len(pythons), 1,
                         f"launcher environments: {sorted(pythons)}; "
                         f"launchers: {[str(path) for path, _python in launchers]}")
        paths = {path.resolve() for path, _python in launchers}
        for entry in sorted((self.root / ".agents/bin").iterdir()):
            if PACKAGE_BYTES in entry.read_bytes() or entry.name == "workflow-state":
                with self.subTest(entry=str(entry)):
                    self.assertIn(entry.resolve(), paths,
                                  f"{entry} -> {entry.resolve()} is outside closure launchers")

    def test_each_system_closure_environment_imports_agent_tools_from_the_closure_build(self):
        builds = self.package_builds()
        self.assertEqual(len(builds), 1, f"agent_tools builds: {sorted(map(str, builds))}")
        build, = builds
        pythons = {python for _path, python in self.closure_launchers()}
        self.assertTrue(pythons, "the system closure has no agent-tools environments")
        clean = {key: value for key, value in os.environ.items() if key not in
                 ("NIX_PYTHONPATH", "NIX_PYTHONPREFIX", "NIX_PYTHONEXECUTABLE")}
        for python in sorted(pythons):
            with self.subTest(python=python):
                done = self.run_child(
                    [python, "-I", "-c", "import agent_tools; print(agent_tools.__file__)"],
                    clean, self.hostile)
                self.assertEqual(done.returncode, 0, done.stderr)
                imported = Path(done.stdout.strip()).resolve()
                self.assertIn(build, imported.parents,
                              f"{python} imports {imported}, outside {build}")
```

Implement the three private test helpers in this same class:

- `system_closure`: assert the new variable is present, absolute and exists, naming the variable and value on failure. Run `nix-store --query --requisites <result>` with `capture_output=True`, `text=True`, `timeout=TIMEOUT_SECONDS`, `check=False`; assert exit 0 with stderr. Return sorted `Path` objects for the nonempty output lines. Assert the list is nonempty. Query errors propagate as test failures, never empty success. It is acceptable to query once per test helper call; no cache or production abstraction is needed.
- `package_builds`: load the TOML's `project` table with `tomllib`; use `re.escape` on `name` and `version`. Return the closure members whose basename fully matches `[0-9a-z]{32}-python[^-]+-<escaped name>-<escaped version>`. This excludes source directories, dist metadata and environment outputs.
- `closure_launchers`: select closure basenames matching `[0-9a-z]{32}-agent-tools-.+`. Require each to be a file, read its bytes, and match `LAUNCHER.fullmatch(data)` or `SCRIPT_LAUNCHER.fullmatch(data)`. Assert a match, naming the path; return each path and decoded `python` group. Keep `workflow_state_launcher`, which other existing tests still use. Keep the existing `launchers` grammar check and adversarial isolation tests.

Update this module's opening docstring to describe the system-result input and the closure pin accurately. Do not change the other test classes' skip behavior.

- [ ] **Step 2: Observe missing-input refusal**

With Task 1's built `./result`, discover the home output by the recipe's existing `nix-store --query --requisites ./result | grep -- '-home-manager-files$'` method; require exactly one. Run the Unit run for `tests/test_agent_tools_launchers.py -k system_closure` with `AGENT_SKILLS_INSTALLED_HOME` set and `AGENT_TOOLS_SYSTEM_RESULT` explicitly removed using `env -u`.

Expected: all three new tests fail, naming `AGENT_TOOLS_SYSTEM_RESULT`; none is skipped. This is a negative test of the newly required input, not a source regression. At the task's starting commit those three names are absent, so a successful zero-test run is not evidence. Confirm the run reports three tests.

- [ ] **Step 3: Pass the system result from both recipes**

In `justfile`, next to `agent_tools_path`, define `system_result := justfile_directory() / "result"`. Add `AGENT_TOOLS_SYSTEM_RESULT="{{system_result}}"` to the Python invocation environment in both `agent-installed-skill-tests` and `agent-retained-tests`. Leave each recipe's build dependency, existing artifact discovery, retained log handling and skipped-test refusal unchanged. This variable is new; the current justfile does not already define it.

Focused gate: `just --dry-run agent-installed-skill-tests` and `just --dry-run agent-retained-tests /not-used-for-dry-run` must both render the new variable with an absolute `/result` path. Before this edit neither expansion includes the variable. Then run the three tests with both inputs set to the base build: expected three tests, green.

- [ ] **Step 4: Prove the pin rejects a second build**

Use an uncommitted expression under `$SCRATCH` to link Task 1's real NixOS system and one launcher from a second application of `lib/agent-tools.nix` using `pkgs // { python3 = pkgs.python312; }`. Get `pkgs` from the current flake's `nixosConfigurations.anis-desktop.pkgs`, and the original system from its `config.system.build.toplevel`. Use `pkgs.linkFarm` with entries `system` and `extra`, the latter pointing to the second application's `launchers.guard-policy`. Use the absolute worktree path with `builtins.getFlake`, under `nix build --impure --file <expression> --out-link "$SCRATCH/two-agent-tools"` (timeout 1800 s). No source or module edit is necessary and no second application is committed.

Run the three new tests with the original installed home and `AGENT_TOOLS_SYSTEM_RESULT="$SCRATCH/two-agent-tools"`. Expected: the package-count test names the Python 3.13 and Python 3.12 builds, and the environment test names both environment paths; the import test also rejects the nonsingleton build set. The 2026-10-27 planning trial already demonstrated the first two reds. Record those paths in the execution report, not a source fixture. This deliberately mixed closure is the falsifiable behavioral gate; the normal base closure is already green.

Restore `AGENT_TOOLS_SYSTEM_RESULT` to the absolute `./result` and run the installed-launcher module by the Unit run: expected all its tests pass. Run the Installed tier via the updated recipe: expected no failures or skips. This checks its argument plumbing without needing a retained evidence corpus.

- [ ] **Step 5: Document the guarantee and limits**

In `python/README.md` § Package and launchers, explain that `home/common/agent-tools/default.nix` applies the builder once per home configuration as `agentTools`, consumed by agent-skills and claude-code. Describe the closure pin's three invariants and say both `just agent-installed-skill-tests` and `just agent-retained-tests <root>` pass `AGENT_TOOLS_SYSTEM_RESULT` to it. Keep the current isolation claim and its test reference.

After the existing five-item residual list in `home/common/claude-code/README.md` § Guard policy, add one paragraph describing: (1) a process started before a switch can keep old store paths, so start a new Claude Code session after switching an agent_tools change; `/hooks` shows that session's loaded hook command and `just show-claude-settings` shows the generation's registered path; (2) a host without a switched generation containing the adapter still runs the previous code throughout. Do not claim an observed reporter-host cause or guaranteed automatic reload. No issue acceptance instructions go in that README (D10).

Review gates: the package README describes the actual three tests and both recipes; the limits paragraph is after the residual list and before `## Context meter`. The starting files have neither the closure guarantee nor that paragraph. Inspect the scoped diff; it must not change guard behavior, policy or hook wiring.

- [ ] **Step 6: Commit**

```bash
git add tests/test_agent_tools_launchers.py justfile python/README.md home/common/claude-code/README.md
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- \
  -m "test(agent-tools): pin one build across the system closure (issue 467)" \
  -m "<session trailer lines>"
```

Scope check: `git diff --stat HEAD~1 -- tests/test_agent_tools_launchers.py justfile python/README.md home/common/claude-code/README.md` lists those four files. Final workflow verification belongs to sdd's final gate.
