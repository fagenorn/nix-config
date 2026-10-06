# Task 5: Phase 6 waits on required checks only

**Files:**
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md` (flow line 6 and `## Phase 6 — Wait for CI` only)
- Modify: `home/common/agent-skills/skills/ship-issue/CI-MERGE.md` (`## Why the blocking watch is shaped that way`, `## Exit codes`, and a new `## Advisory states`)
- Modify: `home/common/agent-skills/skills/ship-issue/evals/evals.json` (eval 1's CI clause only)
- Modify: `home/common/agent-skills/skills/from-issue/ship-handoff.md` (task step 3 only)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`
- Modify (ceilings only): `home/common/agent-skills/instruction-load.json`

**Interfaces:**
- Consumes: the closed ship-summary `notes` field (bounded by `phase_reports.notes_max_characters`, 500). No schema changes (per D7).
- Produces: the exact command strings `timeout 300 gh pr checks <pr-num> --required --watch --fail-fast --interval 30` (blocking), `timeout 300 gh pr checks <pr-num> --watch --fail-fast --interval 30` (fallback), and `gh pr checks <pr-num> --json name,bucket` (advisory listing). Also the notes spellings `advisory CI: <name>=<bucket>, …`, `+<n> more`, and `CI: no required checks reported; waited on all` (per D6, D7, D8).

**Invariants:**
- The wait stays foreground. It is one blocking call, and exit 124 gets one narration turn and then the identical command, up to 8 times. The tip check before blocking, the docs-only skip, and the ban on improvised polling are unchanged (per D6).
- A required-only wait never gates on fewer checks than the all-checks wait it replaces. gh's `no required checks reported` refusal switches the rest of the phase to the all-checks watch (per D8).
- The required set is never written down. No check name (for example `Nix Eval`) appears in ship-issue prose (per D6).
- `ship-release/SKILL.md`, the guard and branch protection are untouched (per D9). CI-MERGE.md's `## Post-selection sync` step 5 keeps "Run Phase 6's CI wait" and inherits this wait by reference (per D11).
- Each breached instruction-load ceiling is raised per the root's Global Constraints.

- [ ] **Step 1: Write the failing tests**

Add these module-level constants right after `GATE_FILE_BOUNDARY` in `test_workflow_skill_contracts.py`:

```python
REQUIRED_WATCH = "timeout 300 gh pr checks <pr-num> --required --watch --fail-fast --interval 30"
ALL_CHECKS_WATCH = "timeout 300 gh pr checks <pr-num> --watch --fail-fast --interval 30"
ADVISORY_CALL = "gh pr checks <pr-num> --json name,bucket"
```

Add these methods to `WorkflowSkillContractsTest`:

```python
    def test_phase_six_waits_on_required_checks_and_lists_advisory_states(self):
        # #264 D6-D8: block on the forge's required set, fall back to every
        # check when none is reported, and report the rest in notes.
        phase_six = self.section(self.ship_issue, "## Phase 6 — Wait for CI",
                                 "## Phase 7 — Merge")
        self.assertIn(REQUIRED_WATCH, re.findall(r"```\n(.*?)\n```", phase_six, re.S))
        collapsed = normalized(phase_six)
        self.assert_ordered(collapsed, REQUIRED_WATCH, "Exit `124`",
                            "`no required checks reported`", ALL_CHECKS_WATCH,
                            "`CI: no required checks reported; waited on all`",
                            "a gating check failed", ADVISORY_CALL,
                            "`advisory CI: <name>=<bucket>, …`")
        self.assertNotIn("Nix Eval", phase_six)
        flow = normalized(self.section(self.ship_issue, "## The flow", "## Standing authorization"))
        self.assertIn("6. Wait for CI → gh pr checks --required --watch (one blocking call;"
                      " all checks when none is required)", flow)
        self.assertIn("block on `<tracker-cli> pr checks --required --watch`",
                      normalized(self.ship_handoff))

    def test_ci_merge_explains_the_required_watch_and_its_fallback(self):
        why = self.section(self.ship_ci_merge, "## Why the blocking watch is shaped that way",
                           "## Exit codes")
        self.assertIn(REQUIRED_WATCH, why)
        self.assertIn("branch protection's own", normalized(why))
        exits = normalized(self.section(self.ship_ci_merge, "## Exit codes", "## Advisory states"))
        self.assert_ordered(exits, "**`0`**", "**`124`**", "`no required checks reported`",
                            ALL_CHECKS_WATCH, "same exit codes and retry budget",
                            "**any other non-zero**")
        advisory = normalized(self.section(self.ship_ci_merge, "## Advisory states",
                                           "## Merge quirks (Phase 7)"))
        for fragment in (ADVISORY_CALL, "is not `pass`", "`advisory CI: <name>=<bucket>, …`",
                         "`+<n> more`", "`historical_owner_result`",
                         "does not block the merge"):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, advisory)

    def test_ship_issue_eval_restates_the_required_ci_wait(self):
        expected = next(case for case in self.ship_issue_evals["evals"]
                        if case["id"] == 1)["expected_output"]
        for fragment in (f"CI is exactly foreground `{REQUIRED_WATCH}`",
                         f"falling back to `{ALL_CHECKS_WATCH}` when gh reports no required checks",
                         f"`{ADVISORY_CALL}`"):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, expected)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k required 2>&1 | tail -3`
Expected: `FAILED (failures=3)`. Today the command has no `--required`.

- [ ] **Step 3: Write the prose**

`ship-issue/SKILL.md`:
1. Flow line 6: `6. Wait for CI             → gh pr checks --required --watch (one blocking call; all checks when none is required)`.
2. In Phase 6, change the fenced command to `timeout 300 gh pr checks <pr-num> --required --watch --fail-fast --interval 30`. Change the lead-in ``Then block with `gh`'s built-in watch — one Bash call, **300s timeout**:`` to ``Then block on the required checks with `gh`'s built-in watch — one Bash call, **300s timeout**:``.
3. Replace the paragraph after the fence with: ``**Foreground only — never backgrounded, and the blocking watch is the only sanctioned wait shape: no bare re-polls, no no-op keep-alive commands.** Exit `0` → list advisory states, then Phase 7. Exit `124` → one short narration turn, re-run the identical command, up to 8 times (~40 min), then escalate. Exit `1` with gh's `no required checks reported` error → the base marks no check required, or the required check is not reported yet: run `timeout 300 gh pr checks <pr-num> --watch --fail-fast --interval 30` for the rest of the phase under the same exit codes and retry budget, list no advisory states, and note `CI: no required checks reported; waited on all`. Other non-zero → a gating check failed; pull `gh run view <run-id> --log-failed`, ground, surface. After the required watch exits `0`, run `gh pr checks <pr-num> --json name,bucket` once and append each non-`pass` row to the ship summary's notes as `advisory CI: <name>=<bucket>, …`. An advisory failure does not block the merge. Rationale, escalation script, advisory format and JSON-field notes: [`CI-MERGE.md`](./CI-MERGE.md).``

`ship-issue/CI-MERGE.md`:
1. `## Why the blocking watch is shaped that way`: change the fenced command to `REQUIRED_WATCH`'s string. After the paragraph about the 5-minute ceiling, insert: ``**Why `--required`.** gh keeps only the checks the forge reports as required for this PR's base, so the rule set is branch protection's own and ship never keeps a copy of a check list. A check that is not required cannot block the merge, so ship does not wait on it; the guard and branch protection still refuse a merge whose required checks have not passed.``
2. `## Exit codes`: make the `0` bullet `` **`0`** → every required check passed; list advisory states (below), then continue to Phase 7. `` After the `124` bullet, insert a bullet: `` **`1` with `no required checks reported`** → gh refuses a `--required` watch at once, without waiting, when no required check has been reported: either the base marks none required (a declared integration branch the guard exempts from the protection demand) or the required check run does not exist yet on a just-pushed head. The two cannot be told apart, and both take today's all-checks watch, `timeout 300 gh pr checks <pr-num> --watch --fail-fast --interval 30`, for the rest of the phase with the same exit codes and retry budget. Every check gated, so no advisory states are listed, and notes say `CI: no required checks reported; waited on all`. A required-only wait never merges with fewer gates than the all-checks wait it replaced. `` Change the last bullet's lead to `` **any other non-zero** → a gating check failed (or `gh` errored). `` and keep the rest of that bullet.
3. Insert `## Advisory states` between `## Exit codes`'s JSON-field note and `## Merge quirks (Phase 7)`: ``After the required watch exits `0`, run `gh pr checks <pr-num> --json name,bucket` once. That is this phase's one non-watching call, and it exits 0 whether or not checks are pending. Every row whose `bucket` is not `pass` (`pending`, `fail`, `cancel`, `skipping`) is a check that was not required, because every required one has passed. Append them to the ship summary's `notes` as `advisory CI: <name>=<bucket>, …`. When they do not fit the shared notes bound, end the list with `+<n> more`, and keep a non-null `report_path` named first. Under lifecycle identity the line goes in the legacy row's `notes`, which `ship-summary/v2` carries as `historical_owner_result`. An advisory `fail` does not block the merge; report it as it is.``

`ship-issue/evals/evals.json` eval 1: replace ``CI is exactly foreground `timeout 300 gh pr checks <pr-num> --watch --fail-fast --interval 30`, re-run after exit 124 up to 8 times`` with ``CI is exactly foreground `timeout 300 gh pr checks <pr-num> --required --watch --fail-fast --interval 30`, falling back to `timeout 300 gh pr checks <pr-num> --watch --fail-fast --interval 30` when gh reports no required checks, re-run after exit 124 up to 8 times``. After ``never backgrounded or replaced by polling/no-op commands.``, insert `` Advisory check states come from one `gh pr checks <pr-num> --json name,bucket` call and go into the ship summary's notes.`` Keep the JSON valid.

`from-issue/ship-handoff.md` task step 3: ``block on `<tracker-cli> pr checks --watch` per ship-issue's instructions.`` → ``block on `<tracker-cli> pr checks --required --watch` per ship-issue's instructions, which fall back to the all-checks watch when no required check is reported.`` Leave the inline-fallback paragraph (`Then wait for CI (`<tracker-cli> pr checks --watch`)…`) unchanged.

Then run the root's ceiling snippet and raise each breached pair with the note `Ceiling raised for #264: ship-issue Phase 6 waits on required checks and lists advisory states (#155 D10).`

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python timeout 900 python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_ship_release_contracts.py 2>&1 | tail -3`
Expected: `OK`.

Run: `git diff --name-only 40fa9c7 -- home/common/agent-skills/skills/ship-release home/common/claude-code .github`
Expected: empty output.

Run: `if rg -n 'Nix Eval' home/common/agent-skills/skills/ship-issue; then exit 1; fi; echo NO-CHECK-NAMES`
Expected: `NO-CHECK-NAMES`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/skills/ship-issue/CI-MERGE.md home/common/agent-skills/skills/ship-issue/evals/evals.json home/common/agent-skills/skills/from-issue/ship-handoff.md home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/instruction-load.json
launch-commit --repo-root /Users/anis/tmp/nix-config --run-id run-20261006-261-262-263-264-265 --worker-id <your worker id> -- -m "feat(ship-issue): wait only on required CI checks (#264)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QpGEgn23dNP1QXn2of1cto"
```

After this commit, run the whole suite once as the plan's acceptance gate (AC3):

Run: `timeout 3000 just agent-workflow-tests > "${TMPDIR:-/tmp}/issue264-awt.log" 2>&1; echo "exit $?"; tail -3 "${TMPDIR:-/tmp}/issue264-awt.log"`
Expected: `exit 0` and `OK`.

Run: `timeout 1800 just build 2>&1 | tail -3`
Expected: exit 0.
