# Task 2: Report a delivered issue's stale custody in its summary

Acceptance 3 of #220. Per D4, D7.

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow_delivery_wire.py` (`DeliveryProjection`)
- Modify: `home/common/agent-skills/tests/test_delivered_control.py` (append one test)
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md` (§5, one sentence)

**Interfaces:**
- Consumes: from Task 1's `DeliveredControlTest` — `delivered_shape() -> dict` (209's custody),
  `records(issue)`, `after_delivery(minute, live) -> CompletedProcess`, `validated(name, value)`,
  `self.cli`, `self.ledger`, `self.run_args`, and the constants `DELIVERED`, `LIVE`; from
  Task 1's `command_control`, the delivered-issue gate (a delivered issue gets no action or
  delta).
- Produces: `DeliveryProjection.nonterminal_custody(issue: int, issue_state: dict[str, Any])
  -> tuple[dict[str, Any] | None, dict[str, Any] | None]` — the issue's one record in
  `{"active", "handed_off", "suspended"}` (`_LIVE_STATES`) and its custody reference, with no
  delivery mask; `(None, None)` when none; `ValueError("multiple nonterminal custody
  records")` when more than one.

**Invariants:**
- `current_custody(issue, issue_state)` returns exactly what it returns at base: `(None, None)`
  when `delivery_complete(issue_state)`, else `nonterminal_custody(issue, issue_state)`. The
  "which record is nonterminal" rule and the more-than-one refusal live only in
  `nonterminal_custody` (per D4).
- `control_summary` changes only the `custody` field and only for a delivered issue
  (`delivery_complete(issue_state)` true): it is `nonterminal_custody(...)[0]`, so non-null
  exactly when one nonterminal record remains. `state`, `owner`, `worktree`, `deadline_at`,
  `blocked_on`, `blockers`, `result`, `contract_digest`, `pending_stage_ids` and
  `requirements` are unchanged (per D4).
- No other caller of `current_custody` changes behaviour: `check-launch`, `current-launch`,
  admission settlement, `live_launches`, `next_deadline` and `decorate_control` keep the
  masked view.
- No ledger record is rewritten (per D7).

- [ ] **Step 1: Write the failing test**

Append this method to `DeliveredControlTest` in
`home/common/agent-skills/tests/test_delivered_control.py`, after
`test_a_delivered_issue_is_never_relaunched`:

```python
    def test_a_stale_delivered_custody_is_reported_not_dispatched(self):
        """Acceptance 3: a pre-fix sweep's extra r1 launch is reported, never dispatched."""
        live = self.delivered_shape()
        pristine = self.ledger.read_bytes()
        stored = json.loads(pristine)
        remainder = stored["issues"][str(DELIVERED)]["delivery_remainders"][0]
        # The launch a pre-fix sweep committed: a resume at the ledger's last write.
        remainder["launches"].append({"kind": "resume", "owner": remainder["owner"],
                                      "worktree": remainder["worktree"],
                                      "at": stored["updated_at"]})
        self.ledger.write_text(json.dumps(stored), encoding="utf-8")
        loaded = json.loads(self.cli("current-launch", *self.run_args, "--action-id",
                                     f"{DELIVERED}:r1:2").stdout)
        self.assertFalse(loaded["current"])
        before = self.records(DELIVERED)
        stale = self.after_delivery(251, live)
        self.assertEqual(stale.returncode, 0, stale.stderr.decode())
        self.validated("workflow-response", stale.stdout)
        response = json.loads(stale.stdout)
        self.assertFalse([a for a in response["actions"] if a.get("issue") == DELIVERED])
        self.assertFalse([d for d in response["deltas"] if d["issue"] == DELIVERED])
        summary = next(s for s in response["summaries"] if s["issue"] == DELIVERED)
        self.assertEqual(summary["custody"], {"kind": "remainder", "remainder": 1,
                                              "launch": 2, "action_id": f"{DELIVERED}:r1:2"})
        self.assertEqual((summary["state"], summary["pending_stage_ids"]), ("closed", []))
        self.assertIsNotNone(summary["contract_digest"])
        self.assertEqual(self.records(DELIVERED), before)
        # The same sweep over the unamended ledger differs only in the named launch.
        self.ledger.write_bytes(pristine)
        clean = self.after_delivery(251, live)
        self.assertEqual(clean.returncode, 0, clean.stderr.decode())
        baseline = next(s for s in json.loads(clean.stdout)["summaries"]
                        if s["issue"] == DELIVERED)
        self.assertEqual(baseline["custody"]["action_id"], f"{DELIVERED}:r1:1")
        self.assertEqual({**baseline, "custody": summary["custody"]}, summary)
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `cd /Users/anis/tmp/nix-config/.worktrees/worktree-issue-220-orchestrated && PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_delivered_control.py -k stale 2>&1 | tail -6`
Expected: FAIL at the `summary["custody"]` assertion,
`None != {'kind': 'remainder', 'remainder': 1, 'launch': 2, 'action_id': '207:r1:2'}`.

- [ ] **Step 3: Write the minimal implementation**

In `DeliveryProjection` (`home/common/agent-skills/scripts/workflow_delivery_wire.py`):

1. Split `current_custody` into the masked view and the unmasked read. The body that builds
   `live`, raises on more than one, and returns `custody_for_record(...)` and the record moves
   verbatim into the new method; `current_custody` keeps only the mask:

```python
    def current_custody(self, issue: int, issue_state: dict[str, Any]
                        ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        if self.delivery_complete(issue_state):
            return None, None
        return self.nonterminal_custody(issue, issue_state)

    def nonterminal_custody(self, issue: int, issue_state: dict[str, Any]
                            ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """The issue's one nonterminal record and its custody, ignoring delivery (#220 D4)."""
        live = [(kind, record)
                for kind, records in (("implementation", issue_state["attempts"]),
                                      ("remainder", issue_state["delivery_remainders"]))
                for record in records if record["state"] in _LIVE_STATES]
        if len(live) > 1:
            raise ValueError("multiple nonterminal custody records")
        if not live:
            return None, None
        kind, record = live[0]
        return self.custody_for_record(issue, kind, record), record
```

2. In `control_summary`, directly after the line
   `custody = None if latest is None else self.custody_for_record(issue, latest_kind, latest)`,
   add:

```python
        if issue_state is not None and self.delivery_complete(issue_state):
            # A delivered issue holds no custody; a nonterminal record left behind
            # is stale custody control never dispatches, so name it (#220 D4).
            custody, _ = self.nonterminal_custody(issue, issue_state)
```

3. In `home/common/claude-code/skills/orchestrate-issues/SKILL.md` §5 ("Final report"),
   directly after the sentence ending `an issue that never received a contract.`, insert:

   > A summary with a non-null `contract_digest`, an empty `pending_stage_ids` and a non-null
   > `custody` is a delivered issue whose `custody` names a stale record that control will
   > never dispatch: report it as delivered with that stale custody, never as an active or
   > progressing owner.

   §4's per-object `workflow-response` validation is not touched (per D6).

- [ ] **Step 4: Verify**

Run: `cd /Users/anis/tmp/nix-config/.worktrees/worktree-issue-220-orchestrated && PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_delivered_control.py home/common/agent-skills/tests/test_workflow_delivery.py home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -3`
Expected: `OK`.

Run: `cd /Users/anis/tmp/nix-config/.worktrees/worktree-issue-220-orchestrated && if ! grep -q 'names a stale record that control will' home/common/claude-code/skills/orchestrate-issues/SKILL.md; then exit 1; fi && if [ "$(grep -c 'def nonterminal_custody' home/common/agent-skills/scripts/workflow_delivery_wire.py)" != 1 ]; then exit 1; fi && echo present`
Expected: `present` (both absent at the start of this task).

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow_delivery_wire.py \
  home/common/agent-skills/tests/test_delivered_control.py \
  home/common/claude-code/skills/orchestrate-issues/SKILL.md
git commit -m "fix(issue-220): report a delivered issue's stale custody in its summary"
```

The message ends with the two trailer lines from the plan's Global Constraints.
