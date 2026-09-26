# Task 2: Fold the PATH fallback and the direct-acquisition restatement (E2, E3)

**Files:**
- Modify: `SK/from-issue/SKILL.md`, `CL/orchestrate-issues/SKILL.md`,
  `SK/from-issue/AUTO.md`
- Test: `T/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: Task 1's edited openers, which sit in the same two SKILL.md files and
  are left as Task 1 wrote them. It also uses the test helpers `normalized(text)`
  and `WorkflowSkillContractsTest.section(text, heading, next_heading)`. That
  helper slices from `heading` to the next occurrence of `next_heading` and raises
  `ValueError` when either is missing.
- Produces: no new interface. Three tests change their end anchor, and one test
  normalizes the text it reads (D20, D28).

**Invariants:**
- The lifecycle-call rule in both files still starts with `STDIN_CLAUSE`
  ("lifecycle call is one command that reads its input from stdin through a
  quoted heredoc"). Each file still names `~/.agents/bin/workflow-state`, which
  `test_helper_binaries_resolve_from_bare_names` requires.
- The PATH fallback ends up stated once per file, in a sentence that covers
  every `workflow-state` command, including the calls that read no stdin
  (`host-route`, `init-run`, `suspend`, `progress`). It never lives only in the
  stdin rule, whose scope excludes those calls (D31).
- from-issue's lifecycle-call rule stays byte-identical. It spells the
  sanctioned call.
- `SK/from-issue/AUTO.md` keeps its line "resuming a `suspended` attempt requires
  neither `new_run` nor `owner_unavailable` — suspension is not a terminal replay,
  so re-entry clears it with both flags left `false`." on one physical line,
  byte-identical. The raw-text assertion in
  `test_direct_auto_authorizations_are_explicit_and_never_inferred` reads it.
- `SK/ship-issue/SKILL.md` is untouched. It states the fallback once already.
- Every assertion inside the four changed tests keeps its literal and its order.
  Only the sliced or normalized text changes.

- [ ] **Step 1: Make E2 and E3**

`SK/from-issue/SKILL.md`, in the `## Lifecycle identity` identity paragraph,
whose "Every `workflow-state` command" sentence covers every call (D31).
Replace these two lines:

```text
delegated remainder uses `--repo-root <ledger_repo_root>`; never substitute the
current checkout or owner worktree. `action_id` is the one identity field that
```

with these three. Keep "Every `workflow-state` command" and
"`--repo-root <ledger_repo_root>`" each on one physical line, since
`test_owner_lifecycle_is_optional_for_direct_use_and_covers_all_stops` asserts
both in the raw text:

```text
delegated remainder uses `--repo-root <ledger_repo_root>`, and the full
`~/.agents/bin/workflow-state` path when the bare name does not resolve on PATH;
never substitute the current checkout or owner worktree. `action_id` is the one identity field that
```

Also delete the standalone paragraph that closes the `### Explicit durable
interactive acquisition` subsection, just above `## The flow`. Delete its two
lines and the blank line after them:

```text
The `workflow-state` executable is `~/.agents/bin/workflow-state`; if the bare
name does not resolve on PATH, invoke it by that full path.
```

`CL/orchestrate-issues/SKILL.md`. Here the standalone paragraph after the intro
("Lifecycle commands run the helper at `~/.agents/bin/workflow-state`; if the
bare `workflow-state` name does not resolve on PATH, use that full path.") is
the scope-general statement, and it stays byte-identical. It is the only
statement that covers `host-route` and `init-run`, because the lifecycle-call
rule enumerates only `control` and `build-delivery` (D31). The restatement is
the rule's naming clause. In the lifecycle-call rule, replace these two lines:

```text
`build-delivery`, with the helper named bare or as `~/.agents/bin/workflow-state`,
and the call optionally piped into or out of `artifact-budget validate-report
```

with this one. The code span keeps its line break before `--input -`:

```text
`build-delivery`, and the call optionally piped into or out of `artifact-budget validate-report
```

`SK/from-issue/AUTO.md`. Replace the first seven lines of the paragraph after
the "The shift is *what you do at a decision point*" paragraph, from "Direct
autonomous acquisition always includes both" through "A resume is not a
takeover:", with the single line

```text
Under direct autonomous acquisition, a resume is not a takeover:
```

The paragraph's last line, starting "resuming a `suspended` attempt requires
neither", stays exactly as it is. `SK/from-issue/SKILL.md`'s `### Direct
autonomous acquisition` already holds the removed rule (D2).

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env WORKFLOW_POLICY_SURFACE=source python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py`
Expected: FAILED (failures=1, errors=3). The three errors are
`test_direct_and_control_requests_are_interface_two`,
`test_from_issue_standalone_modes_use_live_lifecycle_interfaces` and
`test_adjacent_from_issue_acquisition_modes_remain_unchanged`, each with
`ValueError: substring not found`, because the anchor sentence is gone. The one
failure is `test_direct_auto_authorizations_are_explicit_and_never_inferred`:
`'reopened tracker' not found`, because from-issue wraps that phrase.

- [ ] **Step 3: Re-anchor and normalize the tests (D20, D28)**

In `T/test_workflow_skill_contracts.py`:

1. `test_direct_and_control_requests_are_interface_two` — replace
   ```python
           durable = self.section(self.from_issue, "### Explicit durable interactive acquisition",
                                  "The `workflow-state` executable")
   ```
   with
   ```python
           durable = self.section(self.from_issue, "### Explicit durable interactive acquisition",
                                  "## The flow")
   ```
2. `test_from_issue_standalone_modes_use_live_lifecycle_interfaces` and
   `test_adjacent_from_issue_acquisition_modes_remain_unchanged` — in each,
   replace
   ```python
           durable = self.section(
               identity, "### Explicit durable interactive acquisition",
               "The `workflow-state` executable",
           )
   ```
   with the following. `identity` ends before `## The flow`, so the slice is taken
   from the whole skill.
   ```python
           durable = self.section(
               self.from_issue, "### Explicit durable interactive acquisition",
               "## The flow",
           )
   ```
3. `test_direct_auto_authorizations_are_explicit_and_never_inferred` — replace
   `combined = self.from_issue + "\n" + self.auto` with
   `combined = normalized(self.from_issue + "\n" + self.auto)`.

- [ ] **Step 4: Verify**

Run: `env WORKFLOW_POLICY_SURFACE=source python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py`
Expected: OK.

Run: `git grep -n -e "does not resolve on PATH" -- home/common/agent-skills/skills/from-issue/SKILL.md home/common/claude-code/skills/orchestrate-issues/SKILL.md`
Expected: exactly two lines, one per file: from-issue's identity paragraph
and orchestrate-issues' standalone paragraph. At the start commit it also
prints two lines, but from-issue's is its standalone paragraph, near the end
of `## Lifecycle identity`.

Run: `git grep -n -e "invoke it by that full path" -e "always includes both" -e "helper named bare or as" -- home/common/agent-skills/skills/from-issue home/common/claude-code/skills/orchestrate-issues`
Expected: exactly one line, from-issue's unchanged lifecycle-call rule
(`SKILL.md`, "with the helper named bare or as"). At the start commit it prints
four lines.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/from-issue/SKILL.md home/common/claude-code/skills/orchestrate-issues/SKILL.md home/common/agent-skills/skills/from-issue/AUTO.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "refactor(skills): fold the workflow-state PATH fallback and AUTO.md's flag restatement (#155 E2, E3)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

Decision IDs: D2, D20, D28, D31.
