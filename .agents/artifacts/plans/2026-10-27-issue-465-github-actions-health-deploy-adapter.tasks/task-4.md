# Task 4: ship-release Phase 5 polls the command

Spec § ship-release Phase 5, § Instruction budget and § Docs (the CHANGELOG line); per D11, D13, D17. After this task, §5d tells an owner that a registered deploy adapter is polled only through `release deploy inspect`. That path applies when `capabilities.deploy` is available and `deploy.command` is null, so Nodo's unsupported `railway`/`null` binding keeps the Railway prose path. The paragraph maps the observation onto §5c and names the build-log line. The two hot documents stay within the 29,507-byte ceiling through the measured trims of D17.

**Files:**
- Modify: `home/common/agent-skills/skills/ship-release/SKILL.md` (§5 context sentence, §5d)
- Modify: `home/common/agent-skills/skills/ship-release/CHANGELOG.md` (the `## Verification (post-merge)` lines and the rule below the template)
- Test: `home/common/agent-skills/tests/test_ship_release_contracts.py` (new R9 test)
- Modify: `home/common/agent-skills/tests/test_shell_example_contracts.py` (`COMMAND_VOCABULARY` gains `release`)

**Interfaces:**
- Consumes: the `release deploy inspect --repo-root <checkout> --commit <MERGE_SHA>` command line (Task 3) and the observation outcomes and reasons (Task 1).
- Produces: the two machine-consumed §5d lines that the R9 test pins:
  - `release deploy inspect --repo-root <checkout> --commit <MERGE_SHA>`;
  - `${GH_PREFIX}gh run view <facts.run.id> --repo <repo-slug> --log-failed`.

**Invariants:**
- §5's skip rule (`deploy.adapter == none`), its state transitions, §5a–§5c, §5e, Phase 0 and Phase 6 are unchanged. "Any other adapter follows 5a–5c…" still governs command-bearing adapters (D11).
- No Phase 5 example reads runs or health by hand: no `gh run list`, no `curl`, and no `${GH_PREFIX}` on the `release` line (D10, D11).
- `SKILL.md` + `CHANGELOG.md` total at most 29,507 bytes (29,498 measured in the planning trial). `instruction-load.json` is not edited, and no raise label is added (D13).

- [ ] **Step 1: Write the failing test**

In `home/common/agent-skills/tests/test_ship_release_contracts.py`, insert this directly before the line `    # -- R8: evals match the fixture repo and stay non-destructive -------------`:

```python
    # -- R9: Phase 5 polls a registered deploy adapter through one command -------

    def test_phase_five_polls_the_registered_adapter_command(self):
        """Issue 465 D11: the registered-adapter verdict is the command's observation; no
        Phase 5 example reads runs or health by hand."""
        block = self.section(self.skill, "### 5d. Adapter commands", "### 5e. Wakeup prompt")
        self.assertIn("\nrelease deploy inspect --repo-root <checkout> --commit <MERGE_SHA>\n",
                      block)
        self.assertIn("\n${GH_PREFIX}gh run view <facts.run.id> --repo <repo-slug> --log-failed\n",
                      block)
        phase = self.section(self.skill, "## Phase 5 — Watch deploy", "## Phase 6 — Report")
        for forbidden in ("gh run list", "curl", "${GH_PREFIX}release"):
            self.assertNotIn(forbidden, phase)
```

- [ ] **Step 2: Run the test and watch it fail**

Run the Unit run on `home/common/agent-skills/tests/test_ship_release_contracts.py -k test_phase_five_polls_the_registered_adapter_command`.

Expected: `FAILED (failures=1)`: `'\nrelease deploy inspect --repo-root <checkout> --commit <MERGE_SHA>\n' not found in '### 5d. Adapter commands…`.

- [ ] **Step 3: Write the minimal implementation**

Make exactly these replacements. Each old text occurs once.

1. `SKILL.md` §5. Replace

~~~text
Before polling, read the retained snapshot's deploy-related context and hint paths; the adapter contract below is generic, the declared documents carry the specifics.
~~~

with

~~~text
Before polling, read the retained deploy-related context and hint paths: they carry the platform specifics.
~~~

2. `SKILL.md` §5d. Replace the first paragraph,

~~~text
An adapter supplies a service-enumeration command, a per-service **deployment-list** command returning at least `{id, status, commit, branch, createdAt}` for the most recent deployments (a list, not a status summary: the chronology tells a silent rollback from a stale notification), and a build-log command. For the bundled `railway` adapter:
~~~

with

~~~text
A command adapter supplies service enumeration, a per-service **deployment list** of at least `{id, status, commit, branch, createdAt}` (a list: its chronology tells a silent rollback from a stale notification) and a build log. The bundled `railway` adapter:
~~~

3. `SKILL.md` §5d. In the Railway fence, replace the comment line `# success: .meta.commitHash startswith MERGE_SHA, .meta.branch == "<default>", .status == "SUCCESS"` with `# newest 5 entries; success: .meta.commitHash startswith MERGE_SHA, .meta.branch == "<default>", .status == "SUCCESS"`.

4. `SKILL.md` §5d. Replace the paragraph

~~~text
Read the five most recent entries of that JSON and, for each, the fields `id`, `status`, `.meta.commitHash`, `.meta.branch`, and `createdAt`.
~~~

with this, which ends before the unchanged "Any other adapter follows 5a–5c…" paragraph:

~~~text
If `capabilities.deploy` is available and `deploy.command` null, only this read decides:

```bash
release deploy inspect --repo-root <checkout> --commit <MERGE_SHA>
${GH_PREFIX}gh run view <facts.run.id> --repo <repo-slug> --log-failed
```

`satisfied` → done; `in_progress`, or `absent` within 5c's 3 cycles → wake; `diverged` → failure path with the log line; `parameters_invalid` or exit 2 → stop, surface; other `unknown` → surface after 3 in a row. One run serves all `config.services`.
~~~

5. `CHANGELOG.md` `## Verification (post-merge)`. Replace the two lines

~~~text
- <when bindings.deploy.adapter != none: per-service running-commit check — the latest deployment's status is the platform's SUCCESS value AND its commit starts with the merge SHA. Use retained bindings.deploy command/config values.>
- A health probe returning 200 is *not* proof — verify the running commit equals the merge SHA at a SUCCESS status (SKILL.md Phase 5).
~~~

with the single line

~~~text
- <when bindings.deploy.adapter != none: per-service running-commit check (SKILL.md §5d) — SUCCESS status AND a commit starting with the merge SHA; a health 200 is *not* proof.>
~~~

6. `CHANGELOG.md`, the rule below the template. Replace `drop the Verification section's deploy lines and keep only` with `drop the Verification deploy line and keep only`.

7. `home/common/agent-skills/tests/test_shell_example_contracts.py`, `COMMAND_VOCABULARY`: replace `"python3", "railway", "resolve-project",` with `"python3", "railway", "release", "resolve-project",`. The new fence head `release` must be in the vocabulary, and without it `VocabularyGuardTest` is red (D17).

- [ ] **Step 4: Verify**

1. Run the Unit run on `home/common/agent-skills/tests/test_ship_release_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_skill_lint.py` (timeout 900 s).

   Expected: `OK`.

2. Run `bash -c 'test "$(cat home/common/agent-skills/skills/ship-release/SKILL.md home/common/agent-skills/skills/ship-release/CHANGELOG.md | wc -c)" -le 29507'`.

   Expected: exit 0.

3. Run the Budget.

   Expected: output ends `check: pass`.

4. Run `bash -c 'git diff --quiet 5ae1b9dc -- home/common/agent-skills/instruction-load.json'`.

   Expected: exit 0.

5. Run the Unit run on `tests/test_release_command.py -k test_satisfied_needs_a_successful_run_and_a_matching_health_commit`.

   Expected: `OK`. This is the command half of AC2, re-run at this head.

6. Run the Build.

   Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/ship-release/SKILL.md home/common/agent-skills/skills/ship-release/CHANGELOG.md home/common/agent-skills/tests/test_ship_release_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(ship-release): Phase 5 polls release deploy inspect for a registered adapter (issue 465)" -m "<trailers>"
```
