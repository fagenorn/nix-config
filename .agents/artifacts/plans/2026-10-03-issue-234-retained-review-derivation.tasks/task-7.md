# Task 7: Publish both commands and verify installed parity

**Files:**
- Modify: `lib/agent-tools.nix` (two command-table rows)
- Modify: `tests/test_agent_tools_launchers.py` (floor plus portable source/built parity; first of two contributions)

**Interfaces:**
- Consumes: the Task-5 and Task-6 command modules `agent_tools.derive_review_feasibility_fixtures` and `agent_tools.replay_retained`, each exposing `main(argv=None) -> int`; the existing launcher class, its `LAUNCHER` regex, `LAUNCHER_FLOOR` and hostile-channel helpers. The controller supplies the reviewed source commit pinned after Task 6 (D13).
- Produces: managed `~/.agents/bin/derive-review-feasibility-fixtures` and `~/.agents/bin/replay-retained` from the command table. No `python/` byte changes (D13), and no CLAUDE.md edit (D16).

**Invariants:**
- Rows are inserted in the table's sorted order: `derive-review-feasibility-fixtures` after `context-map-lint`, and `replay-retained` after `promotion`. The generated isolated launcher is used unchanged, with no wrapper and no second mapping.
- The source and built commands produce identical exit codes, stdout bytes and stderr lines under a hostile `PYTHONPATH`, `NIX_PYTHONPATH` (`.pth`) and working-directory `agent_tools`. Each case owns disposable state. No skip is accepted inside the installed recipe.
- Portable bundles carry fixture pins, so the built replay must refuse them with the same `invalid:` line as the source command. Built derive must refuse an existing `--output-dir` with exit 2 and leave it untouched.
- No living-doc edit belongs to this task (D16). The command table and the module docstrings are the documentation, and each docstring describes the code as it behaves.

- [ ] **Step 1: Write the failing installed tests.** Extend `LAUNCHER_FLOOR` with `"derive-review-feasibility-fixtures"` and `"replay-retained"`. Then add this method to `AgentToolsLauncherTest`:

```python
    def test_retained_commands_source_built_parity_portable(self):
        def run(argv, env, cwd):
            done = subprocess.run(argv, env=env, cwd=cwd, capture_output=True, timeout=TIMEOUT_SECONDS)
            return done.returncode, done.stdout, done.stderr
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            existing = tmp / "exists"; existing.mkdir()
            cases = [
                ("replay-retained", "replay_retained",
                 ["--fixtures-dir", str(tmp / "missing"), "--expected-anchor-sha256", "sha256:" + "0" * 64]),
                ("derive-review-feasibility-fixtures", "derive_review_feasibility_fixtures",
                 ["--issue-121-repo", str(tmp), "--issue-100-repo", str(tmp), "--archive-dir", str(tmp),
                  "--tool-repo", str(tmp), "--tool-commit", "0" * 40, "--output-dir", str(existing)]),
            ]
            for command, module, args in cases:
                hostile = self.hostile_environment(tmp)    # existing helper: fake agent_tools on every channel
                built = run([str(self.bin / command), *args], hostile, tmp)
                source = run([sys.executable, "-m", f"agent_tools.{module}", *args],
                             dict(os.environ, PYTHONPATH=str(SOURCE_PYTHON)), tmp)
                self.assertEqual(built, source, command)
                self.assertEqual(built[0], 2); self.assertEqual(built[1], b"")
                self.assertRegex(built[2].decode(), rf"^{command}: invalid: [a-z_]+\n$")
                self.assertNotIn(MARKER.encode(), built[2])
            self.assertEqual(list(existing.iterdir()), [])
```

  `self.hostile_environment` and `SOURCE_PYTHON` name the module's existing hostile-channel setup and source root. If the current helper names differ, use those names and keep these assertions. Then add `test_replay_built_refuses_forged_bundle_like_source`. It writes a directory holding the five bundle names, with a canonical anchor `{}` and empty payloads, and passes the anchor's real `telemetry_digest`, so the refusal comes from validation and not from the digest. It then asserts that built and source replay give the identical `(2, b"", b"replay-retained: invalid: <code>\n")`. Real-bundle parity belongs to Task 8.
- [ ] **Step 2: Watch the tests fail.** Run `just agent-installed-skill-tests`. The floor and parity tests fail because there are no rows yet. An unset `AGENT_SKILLS_INSTALLED_HOME` is not a result.
- [ ] **Step 3: Publish.** Add the two rows to `lib/agent-tools.nix`. Changing nothing else is the whole step.
- [ ] **Step 4: Verify.** Run `just build` (the import check covers both modules), then `just agent-installed-skill-tests` with zero failures and no skip in the launcher class, then `just agent-workflow-tests`. To confirm the check can fail: before Step 3, `grep -c replay-retained lib/agent-tools.nix` prints `0`.
- [ ] **Step 5: Commit.** Stage only these two files and commit `feat(review): publish retained derive/replay commands (#234)`.

## Forecast basis

Estimates per D15; these are U10 modify records relative to base `93e6059`:
- `lib/agent-tools.nix`: two added lines in one hunk with 10-line context, 1,536 B / +2 / −0.
- Launcher test: 160 added lines (about 9,600 B) plus about 16 lines of floor and import edits; with context, prefixes and 512 header bytes, 14,336 B / +176 / −8. Task 8 adds the second contribution.
- CLAUDE.md is not forecast. Per D16, its U10 record would be about 13 KB, mostly context, and a measured G0 precheck put the forecast at nine payload members while that record was included.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64],"id":7,"records":[{"bounds":[{"added_lines":2,"boundary":"derive","deleted_lines":0,"record_bytes":1536,"support":{"covers":["t7-1"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t7-1","last_task":7,"owner":7,"path":"lib/agent-tools.nix"},{"bounds":[{"added_lines":176,"boundary":"derive","deleted_lines":8,"record_bytes":14336,"support":{"covers":["t7-2"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t7-2","last_task":8,"owner":7,"path":"tests/test_agent_tools_launchers.py"}]}}
```
