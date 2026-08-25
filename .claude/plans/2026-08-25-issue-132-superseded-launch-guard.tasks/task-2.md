# Task 2: Launch identity in the ship handoff

Discharges AC3's handoff half and part of AC6. Rests on spec rows D2 and D6, and
on the new D18.

**Files:**
- Modify: `home/common/agent-skills/scripts/artifact_budget.py`
- Modify: `home/common/agent-skills/skills/from-issue/ship-handoff.md`
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Test: `home/common/agent-skills/tests/test_artifact_budget.py`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes (Task 1): the CLI verb
  `workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <issue:attempt:launch>`
  and the fact that `action_id` is one opaque `issue:attempt:launch` string.
- Produces, for Tasks 3 and 5: a ship handoff whose 17-key set includes
  `action_id`, non-null exactly when the rest of the lifecycle group is; and
  from-issue prose that adopts and threads `action_id` through, verbatim.

**Invariants:**
- `validate_ship_handoff_report` accepts exactly 17 keys — unknown and missing
  keys both fail (`_exact_keys` is set equality; there is no expressible
  "optional" key).
- `action_id` is null exactly when `ledger_repo_root`, `run_id`, `attempt`,
  `owner` and `owner_worktree` are all null: the lifecycle group stays
  all-or-nothing, never partially present.
- The validator checks `action_id` as a **string only**. The
  `issue:attempt:launch` grammar keeps its single home in `workflow-state.py`;
  do not add a second regex here (per D6).
- `action_id` is passed through verbatim by from-issue, never recomputed and
  never derived from `attempt`.

---

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_artifact_budget.py`, extend the
`lifecycle()` fixture (around line 289) — every ship-handoff payload in the file
spreads it, so one edit carries them all:

```python
    def lifecycle(self):
        return {"ledger_repo_root": None, "run_id": None, "attempt": None,
                "owner": None, "owner_worktree": None, "action_id": None,
                "issue_number": 49, "branch": "issue-49",
                "worktree_path": "/tmp/issue-49", "auto": True}
```

Then add this test immediately after
`test_ship_handoff_residuals_requires_durable_report_path`:

```python
    def test_ship_handoff_lifecycle_group_is_all_or_nothing_with_the_launch(self):
        present = {"ledger_repo_root": "/repo", "run_id": "issue-49-run",
                   "attempt": 1, "owner": "49:1", "owner_worktree": "/repo/wt-49",
                   "action_id": "49:1:1"}
        base = {**self.lifecycle(), **present, "state": "complete",
                "spec_artifact": self.full("design-spec"),
                "plan_artifact": self.full("implementation-plan"),
                "head_sha": "b" * 40, "review_state": "clean",
                "report_path": None, "notes": "ok"}
        self.assertEqual(self.run_validate("ship-handoff", base, True).returncode, 0)
        rejected = (
            # The launch alone, with the rest of the group absent.
            {**base, **{name: None for name in present if name != "action_id"}},
            # The rest of the group, with the launch absent — the shape the
            # guard could not answer for.
            {**base, "action_id": None},
            # A non-string launch identity.
            {**base, "action_id": 1},
            # The key removed outright: the boundary is closed, not optional.
            {key: value for key, value in base.items() if key != "action_id"},
        )
        for index, value in enumerate(rejected):
            with self.subTest(row=index):
                result = self.run_validate("ship-handoff", value, index % 2 == 1)
                self.assertEqual((result.returncode, result.stdout), (2, b""))
```

In `home/common/agent-skills/tests/test_workflow_skill_contracts.py`:

1. In `test_autonomous_reports_and_ship_handoff_are_root_plus_metrics`, after
   `self.assertIn("plan_artifact", self.ship_handoff)`, add:

```python
        self.assertIn('"action_id"', self.ship_handoff)
        self.assertIn(
            "`action_id` is the `issue:attempt:launch` string the acquisition "
            "envelope issued",
            normalized(self.ship_handoff),
        )
        self.assertIn("passed through verbatim", normalized(self.ship_handoff))
```

2. In `test_owner_lifecycle_is_optional_for_direct_use_and_covers_all_stops`,
   add these to the `dispatcher` assertions — **anchor them on the dispatcher
   subsection, not on `identity`**: `action_id` already appears in the
   direct-autonomous subsection, so a section-wide `assertIn` is green at base
   and cannot fail (per D18):

```python
        self.assertIn("all six dispatcher fields", dispatcher)
        self.assertIn("action_id", dispatcher)
```

   and extend the existing identity-field loop to
   `("run_id", "attempt", "owner", "worktree", "ledger_repo_root", "action_id")`.

- [ ] **Step 2: Run the tests and watch them fail**

`unittest`'s `-k` takes one name pattern per flag and ORs repeated flags; it
does **not** parse `a or b` inside a single pattern, so pass each name its own
flag or the selector silently matches nothing and the red phase proves nothing.

```sh
python3 home/common/agent-skills/tests/test_artifact_budget.py -v -k ship_handoff
python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py -v \
  -k root_plus_metrics -k owner_lifecycle_is_optional
```
Expected: the artifact-budget suite fails because every payload now carries an
unknown 17th key (`invalid ship handoff`, exit 2 where 0 was expected), and the
contract suite fails on the missing `"action_id"` / `all six dispatcher fields`
anchors. Check each `Ran N tests` header is non-zero before reading the
failures; a `Ran 0 tests` line means the selector matched nothing.

- [ ] **Step 3: Open the boundary to the launch identity**

In `home/common/agent-skills/scripts/artifact_budget.py`,
`validate_ship_handoff_report` (line 620):

- add `"action_id"` to the `keys` set, making it 17;
- add `"action_id"` to the `lifecycle` tuple, after `"owner_worktree"`;
- extend the all-or-nothing check so the sixth member is validated as a string:
  the group is valid when every member is `None`, or when `ledger_repo_root`,
  `run_id`, `owner`, `owner_worktree` and `action_id` are all strings and
  `attempt` is an integer `>= 1`.

Keep `_string` as the only value check on `action_id`. The validator is the
outer check (fail fast, useful message); `check-launch` is the inner one
(correctness); neither is dropped because the other exists (per D6).

- [ ] **Step 4: Carry it in the handoff prose**

In `home/common/agent-skills/skills/from-issue/ship-handoff.md`, in the
candidate template (line 22), insert the field into the **lifecycle run**,
immediately after `"owner_worktree":"<owner worktree or null>"`:

```
"action_id":"<action id or null>",
```

The documented key order of the existing group must stay undisturbed; append,
never reorder.

Directly below the template's existing paragraph (the one beginning "Use
`state: failed` only according to…"), add one explaining sentence. Write it as
one paragraph, hard-wrapped at ~80 columns:

> `action_id` is the `issue:attempt:launch` string the acquisition envelope
> issued; it joins the all-or-nothing lifecycle group and is passed through
> verbatim — never recomputed, never derived from `attempt` — so ship-issue's
> launch guard can re-validate it before each forge write.

- [ ] **Step 5: Adopt and thread it in from-issue**

In `home/common/agent-skills/skills/from-issue/SKILL.md`:

1. `## Lifecycle identity`, second paragraph (line ~25): change the identity
   list to `ledger_repo_root`, `run_id`, `issue`, `attempt`, `owner`,
   `action_id`, and normalized `worktree`, and append one sentence to that
   paragraph:

   > `action_id` is the one identity field that changes when the attempt is
   > relaunched; pass it through verbatim and never recompute it.

2. `### Dispatcher-owned acquisition` (line ~35): change "require all five
   dispatcher fields: `ledger_repo_root`, `run_id`, `attempt`, `owner`, and
   normalized `worktree`" to "require all six dispatcher fields:
   `ledger_repo_root`, `run_id`, `attempt`, `owner`, `action_id`, and normalized
   `worktree`". Both acquisition routes already produce the value — the
   dispatcher envelope sends `action_id=<action-id>` and the `direct-owner`
   owner envelope returns `action_id` — so this names an existing value rather
   than inventing one.

3. `## Phase 7 — Ship` (line ~417): in the sentence "it carries the lifecycle
   envelope (`ledger_repo_root`, run, attempt, owner)", add `action_id` to that
   parenthesised list.

Do not touch `orchestrate-issues/SKILL.md`: its envelope already carries
`action_id=<action-id>`.

- [ ] **Step 6: Verify**

```sh
python3 home/common/agent-skills/tests/test_artifact_budget.py -v
python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py -v
```
Expected: both OK, zero failures and zero errors — including the pre-existing
`test_ship_handoff_and_summary_matrices` and
`test_ship_handoff_residuals_requires_durable_report_path`, which prove the
17-key set still accepts the all-null lifecycle group.

Then confirm the template really carries the field (this line is the handoff's
public shape):
```sh
if ! grep -q '"owner_worktree":"<owner worktree or null>","action_id":"<action id or null>"' \
     home/common/agent-skills/skills/from-issue/ship-handoff.md; then
  echo "the handoff template does not carry action_id beside the lifecycle group"; exit 1
fi
```
Expected: no output, exit 0. At the commit this task starts from the grep finds
nothing and the gate exits 1.

- [ ] **Step 7: Commit**

```bash
git add home/common/agent-skills/scripts/artifact_budget.py \
        home/common/agent-skills/skills/from-issue/ship-handoff.md \
        home/common/agent-skills/skills/from-issue/SKILL.md \
        home/common/agent-skills/tests/test_artifact_budget.py \
        home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "feat(issue-132): carry the launch identity in the ship handoff"
```
Include the `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` trailer.
Never disable commit signing.
