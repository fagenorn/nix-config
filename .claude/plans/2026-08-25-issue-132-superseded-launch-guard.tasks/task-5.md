# Task 5: from-issue's pre-`finish` guard

Closes the other side of the trust boundary and its share of AC6. Rests on spec
rows D8 and D9.

from-issue reaches its terminal `finish` by two routes and both must be guarded.
`SKILL.md`'s Phase 7 is the generic one. The direct-autonomous route in
`AUTO.md` — the route a `/from-issue <num> --auto` run actually takes, and so
the one the issue's own scenario runs on — instead delegates the terminal write
to a ledger-only bookkeeper that today is told it "executes only that command".
Guarding only the generic paragraph would leave the exposed route unguarded.

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/from-issue/AUTO.md`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes (Task 1): the verb
  `~/.agents/bin/workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <issue:attempt:launch>`.
- Consumes (Task 2): from-issue's own adopted `action_id`, threaded through the
  lifecycle identity.
- Consumes (Task 3): the refusal shape — write nothing, print the canonical
  re-entry line, stop.
- Produces: nothing later tasks depend on.

**Invariants:**
- The guard runs immediately before the terminal `workflow-state finish` that
  from-issue's Phase 7 performs for a ship report, and uses **this owner's own**
  `action_id` — the ship owner and its parent share one launch identity, so a
  ship report from a superseded launch means this parent is superseded too.
- On `current: false` or any helper failure: write nothing, print the canonical
  re-entry line, stop. No `finish`, no `suspend`.
- Phase 7's existing anchor order is preserved: `ledger_repo_root` → "receiving
  the ship report" → `workflow-state finish` → "send the exact JSON".
- The bookkeeper — not its dispatching parent — runs the check, immediately
  before the `finish` it performs. A parent-side check would put an agent
  dispatch between the check and the write, which is the window the guard
  exists to close.
- Scope stays at these two terminal calls. Do not guard from-issue's other
  `workflow-state` writes — that is #125's, and it would add a failure mode at
  all eight phase gates (per D9).

---

- [ ] **Step 1: Write the failing test**

Add to `WorkflowSkillContractsTest` in
`home/common/agent-skills/tests/test_workflow_skill_contracts.py`, immediately
after `test_owner_lifecycle_is_optional_for_direct_use_and_covers_all_stops`:

```python
    def test_from_issue_revalidates_its_launch_before_the_terminal_finish(self):
        # Without this the design refuses the forge write and then performs the
        # ledger write from the very launch it just proved stale, because the
        # ship owner and this parent share one identity (per D9).
        phase_seven = self.section(self.from_issue, "## Phase 7", "## Notes")
        self.assert_ordered(
            phase_seven,
            "receiving the ship report",
            "check-launch",
            "workflow-state finish",
        )
        collapsed = normalized(phase_seven)
        self.assertIn(
            "~/.agents/bin/workflow-state check-launch --repo-root "
            "<ledger_repo_root> --run-id <run-id> --action-id "
            "<issue:attempt:launch>",
            collapsed,
        )
        self.assertIn("this owner's own `action_id`", collapsed)
        self.assertIn("write nothing", collapsed)
        # The refusal is a stop, never a suspension: in the resume shape a
        # suspend would park the successor's live attempt (per D8).
        self.assertNotIn("workflow-state suspend", phase_seven)

    def test_direct_autonomous_bookkeeper_checks_before_the_terminal_finish(self):
        # The delegated ledger-only remainder is how a --auto run reaches its
        # terminal write, so the guard has to live inside the bookkeeper's own
        # command sequence, not in the parent that dispatches it (per D9).
        collapsed = normalized(self.auto)
        self.assert_ordered(
            collapsed,
            "ledger-only bookkeeper route",
            "check-launch",
            "workflow-state finish",
        )
        self.assertIn("executes exactly that sequence", collapsed)
        self.assertNotIn("It executes only that command", collapsed)
        self.assertIn("only after a `current: true` answer", collapsed)
        self.assertIn("write nothing", collapsed)
        self.assertNotIn("workflow-state suspend", self.auto)
```

- [ ] **Step 2: Run the test and watch it fail**

`unittest`'s `-k` takes one name pattern per flag and ORs repeated flags; it
does **not** parse `a or b` inside a single pattern.

```sh
python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py -v \
  -k revalidates_its_launch_before_the_terminal_finish \
  -k bookkeeper_checks_before_the_terminal_finish
```
Expected: `Ran 2 tests`, 2 failures — a `Ran 0 tests` header means the selector
matched nothing and the red phase is void. Both fail with `assert_ordered`
reporting `missing anchor: 'check-launch'`: from-issue's Phase 7 has no ledger
contact between receiving the ship report and the terminal write, and AUTO.md's
bookkeeper is handed a bare `finish`.

- [ ] **Step 3: Insert the guard sentence**

In `home/common/agent-skills/skills/from-issue/SKILL.md`, `## Phase 7 — Ship`,
inside the paragraph that begins "After receiving the ship report, from-issue
owns the terminal durable write.", insert immediately **before** the existing
sentence "Then call `workflow-state finish` and send the exact JSON printed on
stdout unchanged." (hard-wrap at ~80 columns):

> Before that terminal write, run
> `~/.agents/bin/workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <issue:attempt:launch>`
> with this owner's own `action_id`: the ship owner and this parent share one
> launch identity, so a ship report from a superseded launch means this launch
> is superseded too. On `current: false` or any helper failure, write nothing,
> print the canonical re-entry line, and stop.

Keep the command on one line so the contract's collapsed-whitespace anchor
matches it. Change nothing else in Phase 7: the ship-summary validation, the
`unpublished` re-read, the "A fresh ship agent never writes the owner's final
ledger result" sentence and the `ship-Phase-N` narration rule all stay as they
are.

- [ ] **Step 4: Guard the direct-autonomous bookkeeper**

In `home/common/agent-skills/skills/from-issue/AUTO.md`, under
`#### Fresh delegated owner`, replace the two sentences

> Give the bookkeeper the exact `workflow-state finish` command. It executes
> only that command and relays its stdout; it decides nothing and edits nothing.

with (hard-wrapped at ~80 columns, each command on one line):

> Give the bookkeeper an exact two-command sequence and nothing else: first
> `~/.agents/bin/workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <issue:attempt:launch>`
> with this owner's own `action_id`, then the exact `workflow-state finish`
> command. It executes exactly that sequence and relays the `finish` stdout; it
> decides nothing and edits nothing. It runs `finish` only after a `current:
> true` answer from a well-formed `check-launch` on exit 0. On `current: false`,
> a non-zero exit, or output it cannot parse, it must write nothing, print the
> canonical re-entry line as its whole result, and stop — a superseded launch's
> ship report is not this run's terminal result to record.

The check belongs inside the bookkeeper because a check run by the dispatching
parent would put an agent dispatch between the check and the write. Change
nothing else in `AUTO.md`: the Phase-6 and Phase-7 gate values, the
`require the persisted action` sentences, the earlier-controller stop list and
the mechanical-only paragraph all stay as they are. In particular do not add
`workflow-state suspend` anywhere — the refusal is a stop (per D8).

- [ ] **Step 5: Verify**

```sh
python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py -v
```
Expected: OK, zero failures and zero errors. In particular
`test_owner_lifecycle_is_optional_for_direct_use_and_covers_all_stops` must
still pass — it pins the Phase-7 anchor order `ledger_repo_root` → "receiving
the ship report" → `workflow-state finish` → "send the exact JSON", and the new
sentence sits between the second and third anchors without displacing any.

Then confirm the retired verb name did not sneak in with the new one:
```sh
if grep -q 'workflow-state launch' home/common/agent-skills/skills/from-issue/SKILL.md; then
  echo "the retired verb name appears"; exit 1
fi
if ! grep -q 'workflow-state check-launch' home/common/agent-skills/skills/from-issue/SKILL.md; then
  echo "from-issue does not invoke check-launch"; exit 1
fi
if ! grep -q 'workflow-state check-launch' home/common/agent-skills/skills/from-issue/AUTO.md; then
  echo "the direct-autonomous bookkeeper does not invoke check-launch"; exit 1
fi
```
Expected: no output, exit 0. At the commit this task starts from the second and
third gates exit 1.

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/skills/from-issue/SKILL.md \
        home/common/agent-skills/skills/from-issue/AUTO.md \
        home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "feat(issue-132): re-validate the launch before from-issue's terminal finish"
```
Include the `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` trailer.
Never disable commit signing.
