# Task 2: Scope the standing-authorization claim per host enforcement model

**Files:**
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md`
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: the file `home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md` created in Task 1, referenced from three places as the relative link ``[`HUMAN-GATE.md`](./HUMAN-GATE.md)``, and its section headings `## Gate 1 — before the first push (Phase 4)` and `## Gate 2 — after CI, before the merge (Phase 7)`, cited in prose as "Gate 1" and "Gate 2".
- Produces: the amended `## Standing authorization` section, cited by Task 3's README verification and by `HUMAN-GATE.md`'s opener. Produces no new test constants; it edits `test_ship_issue_merge_is_bound_to_the_resolved_repository` in place and adds one test method.

**Invariants:**
- The section's **first** sentence is byte-unchanged. `test_authorization_truth_is_single_and_shared` requires it verbatim in both `ship-issue/SKILL.md` and `from-issue/SKILL.md`; this task edits only `ship-issue/SKILL.md` and must not touch that sentence.
- The merge spelling inside the first host row is byte-identical to today's: `` `gh pr merge <pr-num> --repo <repoSlug> --merge [--subject "<rendered mergeSubjectTemplate>"] --delete-branch` ``.
- After the edit, exactly three lines in `SKILL.md` contain the substring `gh pr merge`, in the same order as today — the flow line, the standing-authorization first row, and Phase 7's rendered form (per D6, D10). The second host row and both new phase pointers must contain none.
- The predicate is the enforcement model, never a host-name or environment test. No detection instruction is added (per D3). This is pinned by an equality over the whole normalized `## Standing authorization` section, not by a single spelling-specific `assertNotIn` (per D15).
- On the review-adjudicated path the order in `## Phase 7 — Merge` is **Gate 2 → `check-launch` → merge** (per D12). The gate waits for a human, so it must not open a window between `check-launch` and the merge: `check-launch` is re-validated *after* the grant, immediately before the write, exactly as the existing paragraph already requires. That paragraph stays byte-unchanged, and the new pointer reinforces rather than relaxes it.

- [ ] **Step 1: Write the failing test**

First, change **one entry** of the ordered `expected_occurrences` list inside `test_ship_issue_merge_is_bound_to_the_resolved_repository` (currently line 2023). The list keeps three entries in the same order; only the middle one gains its host-model prefix. Replace:

```python
            "In a qualifying repository this skill IS that chain: `git push`, "
            "`gh pr create`, "
            f"`{optional_subject}`, branch delete, and worktree remove need no "
            "re-prompt; pause only where a phase says to.",
```

with:

```python
            "In a qualifying repository, on a host whose permission layer "
            "adjudicates each command deterministically against validated "
            "spellings — the Claude host's `PreToolUse` guard — this skill IS "
            "that chain: `git push`, `gh pr create`, "
            f"`{optional_subject}`, branch delete, and worktree remove need no "
            "re-prompt; pause only where a phase says to.",
```

Nothing else in that test changes: `optional_subject`, `rendered_subject`, the first and third entries, the `assertEqual` shape, and the Phase 7 `guard_and_fallback` line assertion all stay exactly as they are.

Then add this new test method immediately after it:

```python
    def test_ship_issue_authorization_is_scoped_to_the_host_enforcement_model(self):
        auth = self.section(
            self.ship_issue, "## Standing authorization", "## Launch guard"
        )
        # AC1: the bare unconditional opener is gone.
        self.assertNotIn(
            "In a qualifying repository this skill IS that chain:", auth
        )
        # D15/D3: pin the section's *complete* normalized shape. Selection is
        # then provably by these two enforcement-model rows and nothing else —
        # no probe, no env-var sniff and no capability handshake can hide in a
        # sentence the assertions below do not name.
        self.assertEqual(
            normalized(auth).strip(),
            normalized(
                "## Standing authorization "
                "Standing authorization exists exactly where the lifecycle "
                "guard grants it: pushing a non-default branch, opening a PR "
                "to the default branch, and the guarded merge, in "
                "fagenorn-owned repositories; everywhere else these commands "
                "stay per-action gated — suspend with blocked_on=human_gate "
                "and print the re-entry line instead of dying at the prompt. "
                "In a qualifying repository, on a host whose permission layer "
                "adjudicates each command deterministically against validated "
                "spellings — the Claude host's `PreToolUse` guard — this skill "
                "IS that chain: `git push`, `gh pr create`, "
                '`gh pr merge <pr-num> --repo <repoSlug> --merge '
                '[--subject "<rendered mergeSubjectTemplate>"] '
                "--delete-branch`, branch delete, and worktree remove need no "
                "re-prompt; pause only where a phase says to. "
                "On a host whose permission layer adjudicates intent by review "
                "rather than by validating spellings — the Codex host, whose "
                "risk reviewer honours literal human messages and repository "
                "guidance but not this skill's prose — no wording here makes "
                "that chain executable: it is denied by default. Take the "
                "consolidated operator gate of "
                "[`HUMAN-GATE.md`](./HUMAN-GATE.md) instead, and never route "
                "around a denial."
            ).strip(),
        )
        self.assert_ordered(
            auth,
            "adjudicates each command deterministically",
            "adjudicates intent by review",
        )
        # D3, kept as a named guard on top of the equality above.
        self.assertNotIn("CLAUDECODE", auth)
        # Both phase pointers, entered instead of the attempt (D7).
        phase4 = self.section(
            self.ship_issue, "## Phase 4 — Open PR", "## Phase 5 — Review the PR"
        )
        self.assertIn(
            "On the review-adjudicated path of `## Standing authorization`, "
            "enter Gate 1 of [`HUMAN-GATE.md`](./HUMAN-GATE.md) before running "
            "anything below — instead of the push, never after a denial.",
            phase4,
        )
        phase7 = self.section(
            self.ship_issue, "## Phase 7 — Merge", "## Phase 8 — Cleanup"
        )
        self.assertIn(
            "On the review-adjudicated path of `## Standing authorization`, "
            "enter Gate 2 of [`HUMAN-GATE.md`](./HUMAN-GATE.md) before "
            "anything below — present the command rendered below, never "
            "attempt it first. The gate comes first on this path because it "
            "waits for the operator's own message; `check-launch` is then "
            "re-validated after the grant arrives, immediately before the "
            "merge, exactly as the next paragraph requires, so the launch "
            "identity is fresh at the moment of the write.",
            phase7,
        )
        # D12: the gate waits for a human, so it must not sit between
        # `check-launch` and the merge. Order on this path is
        # Gate 2 → check-launch → merge.
        self.assert_ordered(
            phase7,
            "enter Gate 2 of [`HUMAN-GATE.md`](./HUMAN-GATE.md)",
            "Run `check-launch` (see `## Launch guard`) immediately before the merge",
            "gh pr merge <pr-num> --repo <repoSlug> --merge",
        )
        # D6/D10: the new Phase-4 pointer introduces no merge spelling, so
        # Phase 4 stays free of `gh pr merge` exactly as it is today.
        self.assertNotIn("gh pr merge", phase4)
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py WorkflowSkillContractsTest.test_ship_issue_authorization_is_scoped_to_the_host_enforcement_model WorkflowSkillContractsTest.test_ship_issue_merge_is_bound_to_the_resolved_repository -v`
Expected: `Ran 2 tests` … `FAILED (failures=2)`.
- `test_ship_issue_authorization_is_scoped_to_the_host_enforcement_model` — `AssertionError` on the first check: `'In a qualifying repository this skill IS that chain:' unexpectedly found`.
- `test_ship_issue_merge_is_bound_to_the_resolved_repository` — `assertEqual` list mismatch on the second element (the file still carries the unprefixed line).

Confirm the base state independently: `grep -c 'gh pr merge' home/common/agent-skills/skills/ship-issue/SKILL.md` → `3`, and `grep -c 'HUMAN-GATE' home/common/agent-skills/skills/ship-issue/SKILL.md` → `0` (exit 1).

- [ ] **Step 3: Amend `SKILL.md`**

**3a — `## Standing authorization`.** Leave the first paragraph untouched. Replace the single second paragraph (currently line 58) with two paragraphs, each one line, separated by a blank line, reading exactly:

```
In a qualifying repository, on a host whose permission layer adjudicates each command deterministically against validated spellings — the Claude host's `PreToolUse` guard — this skill IS that chain: `git push`, `gh pr create`, `gh pr merge <pr-num> --repo <repoSlug> --merge [--subject "<rendered mergeSubjectTemplate>"] --delete-branch`, branch delete, and worktree remove need no re-prompt; pause only where a phase says to.

On a host whose permission layer adjudicates intent by review rather than by validating spellings — the Codex host, whose risk reviewer honours literal human messages and repository guidance but not this skill's prose — no wording here makes that chain executable: it is denied by default. Take the consolidated operator gate of [`HUMAN-GATE.md`](./HUMAN-GATE.md) instead, and never route around a denial.
```

Each row must stay on **one** physical line: `test_ship_issue_merge_is_bound_to_the_resolved_repository` collects whole lines containing `gh pr merge` and compares them to an exact list, so wrapping the first row across two lines breaks it.

**3b — Phase 4 pointer.** In `## Phase 4 — Open PR`, immediately after the existing `Skip entirely when \`issueTracker.kind=none\`…` paragraph and before the `Run \`check-launch\`…` paragraph, insert as its own paragraph, exactly:

```
On the review-adjudicated path of `## Standing authorization`, enter Gate 1 of [`HUMAN-GATE.md`](./HUMAN-GATE.md) before running anything below — instead of the push, never after a denial.
```

**3c — Phase 7 pointer.** Per D12 the pointer goes **before** the launch-guard paragraph, not after it. Gate 2 waits for a human grant — and in `--auto` suspends — so inserting it after `check-launch` would open an unbounded window between that check and the merge and destroy the existing paragraph's "immediately before the merge" guarantee. The order on this path must be **Gate 2 → `check-launch` → merge**.

So: in `## Phase 7 — Merge`, immediately after the existing `(When \`issueTracker.kind=none\`, merge the branch into the integration branch locally per the user's instruction instead.)` paragraph and **before** the `Run \`check-launch\` (see \`## Launch guard\`) immediately before the merge…` paragraph, insert as its own paragraph, exactly:

```
On the review-adjudicated path of `## Standing authorization`, enter Gate 2 of [`HUMAN-GATE.md`](./HUMAN-GATE.md) before anything below — present the command rendered below, never attempt it first. The gate comes first on this path because it waits for the operator's own message; `check-launch` is then re-validated after the grant arrives, immediately before the merge, exactly as the next paragraph requires, so the launch identity is fresh at the moment of the write.
```

Keep it on **one** physical line: the assertion matches this paragraph as an unnormalized substring of the Phase-7 section.

The `Run \`check-launch\` (see \`## Launch guard\`) immediately before the merge, and run it regardless of how Phase 6's tip check came out.…` paragraph stays **byte-unchanged**. The pointer above only tells the review-adjudicated path when it reaches that paragraph; it removes nothing and relaxes nothing. Do not add a second `check-launch` instruction — the existing one is the one that runs after the grant.

Do not reflow, rewrap or reword the `Use the \`repoSlug\` binding…` paragraph: `test_ship_issue_merge_is_bound_to_the_resolved_repository` asserts that whole paragraph as one exact stripped line.

- [ ] **Step 4: Verify**

```bash
python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py WorkflowSkillContractsTest.test_ship_issue_authorization_is_scoped_to_the_host_enforcement_model WorkflowSkillContractsTest.test_ship_issue_merge_is_bound_to_the_resolved_repository -v
```
Expected: `Ran 2 tests` … `OK`.

Then the D10 invariant, written so it can actually fail:

```bash
count=$(grep -c 'gh pr merge' home/common/agent-skills/skills/ship-issue/SKILL.md)
if [ "$count" != "3" ]; then echo "D10 violated: $count merge lines, want 3"; exit 1; fi
if ! grep -q 'HUMAN-GATE.md' home/common/agent-skills/skills/ship-issue/SKILL.md; then
  echo 'gate not linked'; exit 1
fi
echo 'D10 ok'
```
Expected: `D10 ok`. At the base commit this same block exits 1 at the second check (`gate not linked`).

Then the whole suite:

```bash
python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py
```
Expected: `Ran 127 tests` … `OK` — 0 failures, 0 errors. In particular `test_authorization_truth_is_single_and_shared` still passes, proving the shared first sentence was not disturbed.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/ship-issue/SKILL.md \
        home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "$(cat <<'EOF'
fix(ship-issue): state the no-re-prompt claim per host enforcement model

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0128oBTKhwUFwSefRhxX2PAy
EOF
)"
```
