# Task 4: Corrected prose in three homes, then the whole-change gate

Discharges AC5's prose half and AC6. Rests on spec rows D8, D10, D11.

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md`
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (docstrings only)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes, from Tasks 1–3: expiry is reaped up front into `suspended(unknown)`;
  the suspension lane resumes the same attempt with a fresh full window; the
  fourth expiry at an unchanged phase escalates to `stopped(stalled)`; a
  `retried` or `retry_refused` delta is unreachable from a deadline.
- Produces: no code behaviour. Two skill-prose facts pinned by contract
  assertions, and three corrected docstrings.

**Invariants:**
- Every new contract assertion anchors on wording **absent at base**, so it can
  actually fail (per D10). Step 2 proves that before the prose is written.
- The prose states what the shipped code does. Write each sentence against the
  behaviour Tasks 1–3 actually implemented — read the code, do not paraphrase
  this plan.
- No delta kind, action kind or summary field is renamed anywhere (per D8).

---

- [ ] **Step 1: Write the failing assertions**

**1a.** Extend the existing
`test_expiry_prose_describes_the_wall_clock_the_reaper_actually_reads` in
`home/common/agent-skills/tests/test_workflow_skill_contracts.py` (base line
1050) — do not open a parallel test. Keep its comment, its `section(...)` call
and its three existing anchors, and replace its assertion block with:

```python
        self.assert_ordered(
            collapsed,
            "Persistence precedes notification",
            "wall-clock only",
            "never consults `last_progress_at`",
            "consumes no attempt",
            "resumes the same attempt",
            "never opens a second attempt",
        )
        self.assertIn("blocked on a CI watch", collapsed)
        self.assertIn(
            "bounds how long an owner may hold the issue", collapsed
        )
        self.assertIn(
            "the one fresh retry stays reserved for an attempt that reported "
            "a terminal",
            collapsed,
        )
```

**1b.** Add this test immediately after
`test_dispatcher_renders_finalize_from_bounded_summaries` (base line 384):

```python
    def test_final_report_reads_an_expiry_as_an_interruption(self):
        # The dispatcher renders what happened to a human. An `expired` delta
        # is an interruption, not a consumed attempt (per D8, D10).
        final_section = self.section(
            self.orchestrate, "## 5. Final report", "## Notes"
        )
        collapsed = normalized(final_section)
        self.assert_ordered(
            collapsed,
            "`expired` delta",
            "consumes no attempt",
            "`resumed` on the same attempt",
            "a later eligible sweep resumes",
        )
        self.assertIn("never `retried` and never `retry_refused`", collapsed)
```

- [ ] **Step 2: Run the assertions and watch them fail**

```sh
python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -20
```
Expected: two failures — `missing anchor: 'consumes no attempt'` from the
from-issue test and `missing anchor: '`expired` delta'` from the new
orchestrate-issues test.

Then prove every new anchor is genuinely absent at this commit, so none of them
is permanently green:

```sh
F=home/common/agent-skills/skills/from-issue/SKILL.md
O=home/common/claude-code/skills/orchestrate-issues/SKILL.md
# Scope the from-issue probe to the same section the contract test scopes to.
# The assertions live inside `## Dispatch, phase-budget and attempt-budget
# rules`, and "consumes no attempt" already appears *outside* it — in the
# suspension procedure at SKILL.md:296 — so a file-wide grep would report a
# false positive and stop the task before a line of prose is written.
section() {
  awk -v start="$2" -v end="$3" '
    $0 == start { inside = 1; next }
    $0 == end   { inside = 0 }
    inside' "$1"
}
for phrase in "consumes no attempt" "resumes the same attempt" \
              "never opens a second attempt" "one fresh retry stays reserved"; do
  if section "$F" "## Dispatch, phase-budget and attempt-budget rules" \
                  "## Terminal return procedure" | grep -q "$phrase"; then
    echo "already present in from-issue: $phrase"; exit 1
  fi
done
# The orchestrate anchors are absent file-wide, which is the stronger proof, so
# that probe stays unscoped.
for phrase in "expired" "retried" "retry_refused" "resumed"; do
  if grep -q "$phrase" "$O"; then echo "already present in orchestrate: $phrase"; exit 1; fi
done
```
Expected: no output, exit 0.

- [ ] **Step 3: Correct from-issue's deadline-rejected-`progress` paragraph**

In `home/common/agent-skills/skills/from-issue/SKILL.md`, inside
`## Dispatch, phase-budget and attempt-budget rules`, the paragraph that begins
`If \`workflow-state progress\` is rejected because the attempt budget's
deadline has passed` (base lines ~244-259) already routes the owner to the
suspension procedure and already states the wall-clock rule. **Append** the
accounting fact it is missing, after the existing sentence that ends
`it says nothing about whether that owner is still running.`

Write two or three sentences, hard-wrapped at ~80 columns, ordinary prose (no
blockquote), stating exactly these facts and containing the four anchor phrases
verbatim:

- the reaper's suspension **consumes no attempt**;
- re-entry **resumes the same attempt** in place, with a fresh full
  `attempt_budget_minutes` window and a new launch on the same worktree;
- a deadline therefore **never opens a second attempt**, and
  **the one fresh retry stays reserved for an attempt that reported a terminal**
  — an owner-reported `failed` or a legacy expiry-sourced `stopped`.

Before writing, read the shipped `_apply_one_issue_policy` and confirm each
clause against it; if a clause you were about to write is not literally what the
code does, write the code's behaviour and adjust the anchor phrasing in Step 1
to match, keeping it absent-at-base.

- [ ] **Step 4: Correct orchestrate-issues' final-report section**

In `home/common/claude-code/skills/orchestrate-issues/SKILL.md`, inside
`## 5. Final report`, append a short paragraph after the existing
`Do not perform a second ledger read or reconstruct omitted history.` sentence.
It must contain the four anchors in order and the closing literal, and state:

- an `expired` delta is an interruption that **consumes no attempt**;
- it is followed either by a `resumed` on the same attempt in the same sweep,
  or by a `suspended` summary that **a later eligible sweep resumes**;
- it is **never `retried` and never `retry_refused`**.

Use backticks around the delta kinds exactly as the anchors spell them
(`` `expired` delta ``, `` `resumed` on the same attempt ``).

**"a later eligible sweep", not "the next sweep"** — and the sentence must not
promise more than the policy delivers. A suspension arms no deadline
(`command_control` builds `deadlines` only from `active`/`handed_off` attempts),
so the sweep that parked the attempt renders `finalize` and there may be no next
sweep at all; and a sweep that does run resumes only once the tracker is neither
closed nor blocked (the suspended-plus-`tracker_halt_reason` branch returns a
`terminal` instead), a slot is free, and the recorded worktree has been
observed. Write the eligibility as a property of the resume, not a schedule:
name the conditions in prose if it reads better, but do not paste a source line
number into shipped skill prose.

- [ ] **Step 5: Correct the helper's docstrings**

In `home/common/agent-skills/scripts/workflow-state.py`, rewrite three
docstrings so each describes the shipped behaviour. Read the function bodies as
they now stand and write from them; each must state at least the fact named:

- `demote_expired_attempt` — it is the single reaper call site and runs on every
  touch of an expired attempt, not only when no dispatch slot is free.
- `_apply_one_issue_policy` — the reap-first ordering, and why the forge-merged
  reconciliation sits above it (per D3).
- `resume_attempt` — a reaped expiry is one of the suspensions that takes the
  fresh full window.

`stop_attempt`'s docstring already says *"No writer passes `expiry` any more"*
and is correct as it stands — **verify it, do not edit it.**

- [ ] **Step 6: Verify**

```sh
set -o pipefail
python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -5
```
Expected: `OK`, zero failures and zero errors. `set -o pipefail` is not
decoration: without it the pipeline exits with `tail`'s status and a red suite
reports success.

Then run the whole-change gates from the worktree root. The permission-guard
suite reads its settings artifact from `CLAUDE_SETTINGS_PATH` at import time
(`tests/test_claude_permission_guard.py:10`), so it must be produced first with
`just show-claude-settings` (`justfile:82`, which depends on `build`) and bound
through that variable; invoked bare it raises `KeyError: 'CLAUDE_SETTINGS_PATH'`
before collecting a case, which is a broken gate, not a green one.

```sh
set -o pipefail
just agent-workflow-tests 2>&1 | tail -5
just show-claude-settings > "$TMPDIR/claude-settings.json" \
  && CLAUDE_SETTINGS_PATH="$TMPDIR/claude-settings.json" \
     python3 tests/test_claude_permission_guard.py 2>&1 | tail -5
just build 2>&1 | tail -5
```
Expected: `just agent-workflow-tests` reports `OK` over 455 tests plus the ones
this change added (Task 1 added five, Task 2 two, Task 3 one, Task 4 one, and
Task 1 deleted one, so the count rises by eight to 463) with zero failures and
zero errors; the permission-guard suite reports `OK` unchanged, since
`workflow-state` is not on the allow surface and no verb was added; `just build`
completes with a store path and no evaluation error.

Finally, confirm the prose fixes did not resurrect a retired claim anywhere in
either skill tree:

```sh
if grep -rn "retry_refused" home/common/agent-skills/skills/ \
     home/common/claude-code/skills/ | grep -v "never \`retried\` and never"; then
  echo "an unqualified retry_refused claim is back in the prose"; exit 1
fi
```
Expected: no output, exit 0.

- [ ] **Step 7: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py \
        home/common/agent-skills/skills/from-issue/SKILL.md \
        home/common/claude-code/skills/orchestrate-issues/SKILL.md \
        home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "docs(issue-133): state what an expiry costs in all three prose homes"
```
Include the `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` trailer.
Never disable commit signing.
