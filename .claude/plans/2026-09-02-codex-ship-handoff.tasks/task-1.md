# Task 1: The `HUMAN-GATE.md` consolidated operator gate

**Files:**
- Create: `home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md`
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: nothing from an earlier task. It reads the live `ship-issue/SKILL.md` at the base commit for Phase 4's `git push -u origin <branch>` / `gh pr create` shapes, Phase 7's merge rendering, Phase 8's cleanup chain, and `## Launch guard`'s `check-launch`.
- Produces: the file `skills/ship-issue/HUMAN-GATE.md`, linked from `SKILL.md` in Task 2 as the relative link `[`HUMAN-GATE.md`](./HUMAN-GATE.md)`. Produces the test-module constant `SHIP_ISSUE_HUMAN_GATE` and the `setUpClass` attribute `cls.ship_human_gate`, which Task 3 does not use but must not remove.

**Invariants:**
- The literal string `gh pr merge` never appears anywhere in `HUMAN-GATE.md` (per D6 — Phase 7 is the single home for that spelling, and a second home would drift silently because the pinned exact-list test only scans `SKILL.md`).
- The file defines no new `blocked_on` value and no new suspension shape: it defers to `from-issue/SKILL.md`'s existing procedure with `blocked_on: human_gate` (per D5).
- The gate is entered *instead of* attempting the verb, never after a denial (per D7).
- Every check the Claude path performs still runs; the grant adds to them and replaces none (per D8).

- [ ] **Step 1: Write the failing test**

Add the module-level constant beside the existing `SHIP_ISSUE_REVIEW` definition (currently line 38 of the test file):

```python
SHIP_ISSUE_HUMAN_GATE = (
    REPO_ROOT / "home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md"
)
```

Add to the same `setUpClass` that already sets `cls.ship_review` (currently line 201):

```python
        cls.ship_human_gate = SHIP_ISSUE_HUMAN_GATE.read_text(encoding="utf-8")
```

Add this test method immediately after `test_ship_issue_merge_is_bound_to_the_resolved_repository` in the same class:

```python
    def test_ship_issue_human_gate_consolidates_and_forbids_bypass(self):
        gate = self.ship_human_gate
        # D6: Phase 7 is the single home for the merge spelling. A second home
        # would drift silently — the pinned exact-list test only scans SKILL.md.
        self.assertNotIn("gh pr merge", gate)
        # D5: the gate reuses the one suspension mechanism, defining no new one.
        self.assertIn("blocked_on: human_gate", gate)
        self.assert_ordered(
            gate,
            "## Gate 1 — before the first push (Phase 4)",
            "## Gate 2 — after CI, before the merge (Phase 7)",
            "## Grant semantics",
            "## Never route around a denial",
        )
        # D7: entered instead of the attempt, never as a denial fallback.
        self.assertIn(
            "Enter the gate *instead of* attempting the verb — never attempt a "
            "shipping verb and then react to the denial.",
            gate,
        )
        # D2/#90: Gate 1 shows the whole remaining chain once.
        self.assertIn(
            "Gate 1 also names that a second and final gate follows after CI and "
            "what it will cover, so the operator sees the whole remaining chain "
            "once.",
            gate,
        )
        # D6: Gate 2 refers to the merge, never re-spells it.
        self.assertIn(
            "Present the merge command exactly as Phase 7 renders it.", gate
        )
        # AC2: the session resumes in place, through to issue closure.
        self.assertIn(
            "After this grant nothing further is asked: the same session resumes "
            "in place and runs the chain to issue closure and cleanup.",
            gate,
        )
        for clause in (
            "A grant covers exactly the literal command strings presented, each "
            "consumed by exactly one execution.",
            "A command that renders differently in any byte from the granted "
            "literal is not covered and needs a fresh gate.",
            "Silence is not a grant.",
            "A partial reply grants only the commands it names.",
            "A failed execution is not re-run under the same grant; re-entering "
            "the gate is the only path.",
            # D8: additional to, never a substitute for, the existing checks.
            "The grant is additional to every check the Claude path performs, "
            "never a substitute:",
            "`check-launch`",
            "Phase 6's tip check",
            "the base branch's required status check",
        ):
            with self.subTest(clause=clause):
                self.assertIn(clause, gate)
        # AC3: the closed no-bypass list, member by member.
        for forbidden in (
            "merge the feature branch into `<integrationBranch>` locally",
            "push to `<integrationBranch>`",
            "push to any remote other than `origin`",
            "pass `--admin`, `--force`, `--force-with-lease`, or any hook-bypass flag",
            "rewrite, reset or rebase any branch to change what a denied command "
            "would have done",
            "re-attempt a denied command in a re-worded or re-quoted spelling",
            "ask a subagent, another skill, or another host to run the command on "
            "its behalf",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertIn(forbidden, gate)
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py WorkflowSkillContractsTest.test_ship_issue_human_gate_consolidates_and_forbids_bypass -v`
Expected: `ERROR: setUpClass (…WorkflowSkillContractsTest)` … `FileNotFoundError` naming `home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md`, then `FAILED (errors=1)` — the whole class errors out in `setUpClass` because the file does not exist. Confirm the file's absence independently first:

```bash
if [ -e home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md ]; then echo 'already present'; exit 1; fi
echo absent
```
Expected at the base commit: `absent`.

- [ ] **Step 3: Write `HUMAN-GATE.md`**

Create the file with this exact structure. Every sentence quoted in Step 1 must appear byte-identically; the surrounding prose is the implementer's to write within the shapes below. Follow the sidecar house style of `SYNC.md`/`REVIEW.md`: an H1 title, a short "read this when" opener, then H2 sections. Keep it under roughly 90 lines — a Claude session never walks this path and should not pay for it (D4).

```markdown
# Consolidated operator gate
```

Opening paragraph (before the first H2): state that this is the review-adjudicated path named in `SKILL.md`'s `## Standing authorization` — a host whose permission layer adjudicates intent by review rather than by validating spellings. State that on this path `git push`, PR creation and the merge are denied by default and that no wording in a skill can change that, because the reviewer honours literal human messages and repository guidance only. Then the pinned sentence, verbatim:

> Enter the gate *instead of* attempting the verb — never attempt a shipping verb and then react to the denial.

Close the opener by stating that the gate is entered exactly twice, and that in `--auto` the gate presents its block and then follows `from-issue/SKILL.md`'s suspension procedure, suspending `blocked_on: human_gate` and printing the canonical re-entry line — it defines no new suspension shape and no new `blocked_on` value.

`## Gate 1 — before the first push (Phase 4)` — presents, as literal text the human can read and repeat in their own message: the exact `git push -u origin <branch>` with `<branch>` substituted, and the exact `gh pr create` invocation including the fully rendered body (heredoc expanded, `Closes #<num>` present). Both are fully determined at that moment. Then, verbatim:

> Gate 1 also names that a second and final gate follows after CI and what it will cover, so the operator sees the whole remaining chain once.

`## Gate 2 — after CI, before the merge (Phase 7)` — opens with, verbatim:

> Present the merge command exactly as Phase 7 renders it.

Then list the remaining Phase-8 chain that the same grant covers: `gh issue close <num>`, the remote-branch delete when `git ls-remote --heads origin <branch>` is non-empty, `git worktree remove <worktree-path>`, and `git branch -d <branch>`. Close the section with, verbatim:

> After this grant nothing further is asked: the same session resumes in place and runs the chain to issue closure and cleanup.

`## Grant semantics` — a bullet list applying to both gates. Each of these five sentences appears verbatim as (or as the head of) its own bullet:

> - A grant covers exactly the literal command strings presented, each consumed by exactly one execution.
> - A command that renders differently in any byte from the granted literal is not covered and needs a fresh gate.
> - Silence is not a grant. No reply → keep waiting (interactive) or stay suspended (`--auto`). A partial reply grants only the commands it names.
> - A failed execution is not re-run under the same grant; re-entering the gate is the only path.
> - The grant is additional to every check the Claude path performs, never a substitute: `check-launch` still runs before every pre-merge forge write, Phase 6's tip check and the CI wait still bind, and the merge still requires the base branch's required status check. Nothing here weakens `.out-of-scope/ungated-agent-merges.md`.

`## Never route around a denial` — one sentence explaining that a denial creates exactly the pressure to be creative, so the ban is stated as a closed list, and that it restates for this path the ban Phase 1 already places on rewriting the integration branch. Then a bullet list opened by "On this path the session must not:" whose seven members read verbatim:

> - merge the feature branch into `<integrationBranch>` locally;
> - push to `<integrationBranch>`;
> - push to any remote other than `origin`;
> - pass `--admin`, `--force`, `--force-with-lease`, or any hook-bypass flag;
> - rewrite, reset or rebase any branch to change what a denied command would have done;
> - re-attempt a denied command in a re-worded or re-quoted spelling;
> - ask a subagent, another skill, or another host to run the command on its behalf.

- [ ] **Step 4: Verify**

```bash
python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py WorkflowSkillContractsTest.test_ship_issue_human_gate_consolidates_and_forbids_bypass -v
```
Expected: `Ran 1 test` … `OK`.

Then the D6 invariant as a gate that can actually fail (a bare `! grep` is exempted by `set -e`):

```bash
if grep -q 'gh pr merge' home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md; then
  echo 'D6 violated: HUMAN-GATE.md re-spells the merge'; exit 1
fi
echo 'D6 ok'
```
Expected: `D6 ok`.

Then the whole suite, to prove nothing else moved:

```bash
python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py
```
Expected: `Ran 126 tests` … `OK` — 0 failures, 0 errors.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md \
        home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "$(cat <<'EOF'
feat(ship-issue): add the consolidated operator gate sidecar

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0128oBTKhwUFwSefRhxX2PAy
EOF
)"
```
