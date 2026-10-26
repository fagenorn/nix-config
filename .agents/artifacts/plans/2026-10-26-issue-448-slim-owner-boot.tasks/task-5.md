# Task 5: Cut 2 — the resume entry

Spec § Cut 2; per D5, D7, D16, D20. A prompt that carries a resume pack names `<from-issue-dir>/resume-pack.md` as the owner's entry in place of the `from-issue` Skill invocation, keeping the arguments `from-issue <num> --auto`. The entry carries the exact `check-launch` argv, so the pack's checks run before any `SKILL.md` section is read.
- Verified pack: the owner reads `SKILL.md` through `## Files beside this one`, then only the sections that index names for its phase.
- Failed check, refused pack, `reorient`, or no pack: the owner loads the whole skill.

A prompt without a pack is unchanged. Sub-skills still load through the Skill tool. ship-issue gets no entry.

**Files:**
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md`: the owner-prompt template, and the envelope-filling paragraph above it.
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`: `### Resume pack`, the `resume-pack.md` line of `## Files beside this one`, and other repeated wording, for byte offsets only.
- Modify: `home/common/agent-skills/skills/from-issue/resume-pack.md`: the entry.
- Modify, for byte offsets only: `home/common/agent-skills/skills/from-issue/AUTO.md`. Its opening sentence, ``Read this file once, when you detect `--auto` in the invocation.``, repeats the index's read-once rule.
- Modify: `home/common/agent-skills/README.md`: the `### Resume pack` paragraph under `## Lifecycle helpers`.
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`: `SlimBootContractsTest` gains two tests, and one `ResumePackContractsTest` test is deleted.
- Modify: `.agents/artifacts/plans/2026-10-26-issue-448-slim-owner-boot.acceptance.md`: the Built cell of cut row 2.

**Interfaces:**
- Consumes: Task 4's `SlimBootContractsTest` with `read`/`section`; `ResumePackContractsTest.PACK`; the module constants `FROM_ISSUE`, `RESUME_PACK` and `ORCHESTRATE`. If Task 4 built nothing, first create the class exactly as Task 4 Step 1 shows, minus its test method.
- Produces: the placeholder `<from-issue-dir>`. orchestrate-issues fills it with the absolute path of the `from-issue` directory beside its own skill directory; from-issue's own composers fill it with this skill's base directory (D20).

**Invariants:**
- `ORCHESTRATE`, after `<!-- agent-dispatch: id=orchestration-issue-owner`, has the `Resume pack` paragraph, then `<from-issue-dir>/resume-pack.md` on one line, then `from-issue <num> --auto`. A line still begins `` > `from-issue <num> --auto` ``, which `WorkflowSkillContractsTest.test_dispatcher_passes_immutable_ledger_root_separately_from_worktree`'s field loop requires.
- `### Resume pack` (up to `## The flow`) names `<from-issue-dir>/resume-pack.md`.
- `resume-pack.md` names, in this order:
  - the `resume-pack` argv `ResumePackContractsTest.PACK`;
  - `workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`, piped through `artifact-budget validate-report --boundary workflow-response --input -`;
  - `` `git -C <worktree> rev-parse HEAD` ``, `` `worktree.head` ``, `` `git -C <worktree> status --porcelain` `` and `` `worktree.dirty_paths` ``;
  - `` `## Files beside this one` ``.

  It also names `` `action_id` `` and the fallback that loads the whole `from-issue` skill.
- The `delegate` bullet and `rollover.md` keep `ResumePackContractsTest.PACK` (two existing tests pin it).
- Over the edited skill documents, bytes fall (D5), and every profile stays within its ceiling. After Task 4 the controller's hot headroom is about 0, and the dispatcher's is 7 B.

- [ ] **Step 0: Read the verdict**

Run `bash -c 'grep -qE "^\| 2 \| .*\| keep \| " .agents/artifacts/plans/2026-10-26-issue-448-slim-owner-boot.acceptance.md'`. On a non-zero exit, change nothing, commit nothing, and report DONE with `cut 2 not built: Task 3 verdict` (D16).

- [ ] **Step 1: Write the failing tests**

Add to `SlimBootContractsTest`:

```python
    CHECK_LAUNCH = ("workflow-state check-launch --repo-root <ledger_repo_root> "
                    "--run-id <run-id> --action-id <action_id>")
    ENTRY = "<from-issue-dir>/resume-pack.md"

    def test_pack_carrying_prompts_name_the_resume_entry(self):
        resume = self.section(self.read(FROM_ISSUE), "### Resume pack", "## The flow")
        self.assertIn(self.ENTRY, resume)
        orchestrate = self.read(ORCHESTRATE)
        fresh = orchestrate[orchestrate.index("<!-- agent-dispatch: id=orchestration-issue-owner"):]
        self.assertLess(fresh.index("Resume pack"), fresh.index(self.ENTRY))
        self.assertIn("from-issue <num> --auto", fresh[fresh.index(self.ENTRY):])

    def test_the_entry_runs_its_checks_before_any_skill_section(self):
        entry = self.read(RESUME_PACK)
        position = -1
        for anchor in (ResumePackContractsTest.PACK, self.CHECK_LAUNCH,
                       "artifact-budget validate-report --boundary workflow-response --input -",
                       "`git -C <worktree> rev-parse HEAD`", "`worktree.head`",
                       "`git -C <worktree> status --porcelain`", "`worktree.dirty_paths`",
                       "`## Files beside this one`"):
            position = entry.find(anchor, position + 1)
            self.assertGreaterEqual(position, 0, anchor)
        self.assertIn("`action_id`", entry)
```

Delete `ResumePackContractsTest.test_from_issue_owner_verifies_the_pack_and_reads_only_the_phase`. Its identifiers move into the second test above, and its English anchors (`must equal`, `must list exactly`) go, as agent-helpers rule 6 asks of a slice that rewrites their text (D20).

- [ ] **Step 2: Run the tests and watch them fail**

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k SlimBootContractsTest 2>&1 | tail -4'` (timeout 300 s).
Expected: FAIL, 2 failures, because `<from-issue-dir>/resume-pack.md` and the `check-launch` argv are absent.

- [ ] **Step 3: Edit the documents**

Drafts that meet every Invariant, with byte deltas measured at `cf7232c1`. Compress further where a gate needs it, keeping every pinned identifier and every rule.

1. `resume-pack.md` becomes (−51 B):

```markdown
# Resume pack

A relaunched owner's prompt may carry a resume pack, the read-only stdout of `workflow-state resume-pack --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`. It is an accelerator, never a gate, and stays untrusted until the checks below pass. A prompt naming this file as its entry reads it before any skill.

Checks, in order:

1. Resolve the project once, validate the owner object and run `workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id> | artifact-budget validate-report --boundary workflow-response --input -`; obey a `current: false` answer exactly as without a pack.
2. An owner delegated at the Phase-5 rollover (its prompt carries `reviewed_head_sha`) passes every `delegated-owner.md` check first.
3. The pack's `action_id` must equal the envelope's, `git -C <worktree> rev-parse HEAD` must equal `worktree.head`, and `git -C <worktree> status --porcelain` must list exactly `worktree.dirty_paths` entries (the pack carries that count, not the paths).

A failed check, a `reorient` next action or no pack: load the whole `from-issue` skill through the Skill tool with the prompt's arguments and re-orient in full. A verified pack replaces only your own ad-hoc re-orientation: do not dump the ledger, re-read git history, re-validate the plan or read the SDD progress log yourself. Read `SKILL.md` through `## Files beside this one`, then only the sections that index names for your phase, and start from `next_action`. Everything the pack does not replace still runs unchanged, sdd's own `progress.md` check on entry included; where it disagrees with the pack's `resume_task`, sdd's ledger wins. `read_handoff` reads the handoff document at its `path`.
```

   The old closing line about a `resume-pack` refusal is dropped: the composers' own sentences already say it (the `delegate` bullet's "on exit 0", and `rollover.md`'s "A refusal sends none").

2. `SKILL.md`:
   - `### Resume pack` becomes ``A prompt composed with a pack names `<from-issue-dir>/resume-pack.md`, this directory's absolute path, as the owner's entry in place of the skill invocation, keeping its arguments.`` (+85 B).
   - In `## Files beside this one`, ``**`resume-pack.md`** — the prompt carries a resume pack. A verified pack reads, at every phase, the sections headed `Lifecycle identity` `` becomes ``**`resume-pack.md`** — any resume pack, and a pack-carrying prompt's entry. A verified pack reads, at every phase, `Lifecycle identity` `` (−1 B). The "any resume pack" keeps the direct re-entry route of `acquire-direct.md`, which runs `resume-pack` itself, on this file.
   - The composers' own `Resume pack` paragraph sentences, in the `delegate` bullet and `rollover.md`, stay as they are.
3. `AUTO.md`: delete its opening sentence ``Read this file once, when you detect `--auto` in the invocation.`` (−65 B); the index's `AUTO.md` line keeps that rule. `SKILL.md` and `AUTO.md` together are then still about 19 B over, in the three profiles that hold both as hot members. Shorten repeated wording elsewhere in those two documents by at least that much.
4. `orchestrate-issues/SKILL.md` (+18 B):
   - In the template, the two `Resume pack` lines become ``> Resume pack (only for a `resume` action whose `resume-pack` call exited 0):``.
   - The `Invoke the from-issue skill …` sentence becomes three lines:

     ```
     > With a pack, read `<from-issue-dir>/resume-pack.md` first, else invoke the
     > `from-issue` skill via the Skill tool, with the literal arguments
     > `from-issue <num> --auto`. Preserve the lifecycle identity and exact worktree.
     ```
   - The envelope-filling paragraph (`Fill the envelope from the entry's members …`) adds that `<from-issue-dir>` is the `from-issue` directory beside this skill's own, as an absolute path (about +75 B).
   - The dispatcher profile has 7 B of headroom, so cut about 90 B of repeated wording elsewhere in this file. Never cut a rule, an argv, an `agent-dispatch` line, the leaf-agent clauses, or text a `WorkflowSkillContractsTest.test_dispatcher_*` test reads.

README: in `home/common/agent-skills/README.md`'s `### Resume pack` paragraph, replace "the relaunched owner still runs `check-launch`, checks the pack's HEAD and dirtiness, and then reads only the skill sections every owner obeys plus the current phase's". The new text says, from the edited documents: a pack-carrying prompt names from-issue's `resume-pack.md` by absolute path as the owner's entry in place of the Skill-tool invocation; the owner runs `check-launch` and the HEAD and dirtiness checks before reading any of `SKILL.md`, then its index and the current phase's sections; a failed check, a refused pack or `reorient` loads the whole skill (issue 448).

- [ ] **Step 4: Verify**

Run: the Step 2 command. Expected: PASS, 3 tests (Task 4's and these two; 2 when cut 1 was not built).
Run: **Skill contract tests**. Expected: PASS.
Run: **Budget**. Expected: `check: pass`. On a `tightness:` line only, run `just agent-instruction-load tighten`, add `home/common/agent-skills/instruction-load.json` to the commit, and rerun.
Run the net-bytes check:

```bash
bash -c 'set -e; net=0; for f in home/common/claude-code/skills/orchestrate-issues/SKILL.md home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/from-issue/resume-pack.md home/common/agent-skills/skills/from-issue/AUTO.md; do net=$((net + $(wc -c < "$f") - $(git show "HEAD:$f" | wc -c))); done; echo "net $net"; test "$net" -lt 0'
```

If the Budget or net-bytes check cannot pass with the offsets this task allows, without dropping a rule or an Invariants identifier, the cut fails D5's rule 2. Then revert every file but the record, set row 2's Verdict to `reject (instruction load)` and its Built to `not built`, and commit only the record.

- [ ] **Step 5: Record and commit**

Set cut row 2's Built cell to `built; net <n> bytes`. Then:

```bash
git add home/common/claude-code/skills/orchestrate-issues/SKILL.md \
  home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/from-issue/resume-pack.md \
  home/common/agent-skills/skills/from-issue/AUTO.md \
  home/common/agent-skills/README.md home/common/agent-skills/tests/test_workflow_skill_contracts.py \
  .agents/artifacts/plans/2026-10-26-issue-448-slim-owner-boot.acceptance.md
git commit -m "feat(from-issue): a relaunch with a resume pack enters through resume-pack.md (issue 448)"
```
