# Every lifecycle reply passes the workflow-response boundary, issue 191

## Problem

The lifecycle skills treat every `workflow-state` reply as untrusted transport.
They pipe the raw bytes through `artifact-budget validate-report --boundary
workflow-response --input -` and decode only what passes. Three replies can
never pass, so an owner or dispatcher that follows its contract is stopped by
its own helper:

1. **A reconciled merge poisons the run.** When control or direct-owner sees
   `forge: merged` for an attempt nobody holds, it closes the attempt as
   `merged` with `result_source: superseded` and `issue_closed: false`. Every
   later control summary for that issue carries that result, and so does a
   direct re-entry's `kind: terminal` replay. The boundary rejects all of them
   with `invalid ship summary state`. In run
   `run-20260923-147-153-154-150-148-149-126-155`, issue #154 (PR #187) failed
   every sweep after the reconcile. Run `run-20260926-126-190-193-194-195`
   holds the same record for #194.
2. **`progress` prints the raw attempt record.** It has no `kind` and no
   `interface_version`, so it is refused. It also puts ledger internals on the
   wire (`launches`, `phase_inputs`, `suspend_phase`, …), which callers must
   never read. Run `direct-191-000001` shows `progress` exiting 0 with a reply
   the boundary refuses.
3. **`suspend` prints an unversioned `{"kind": "suspended", …}`.** The
   validator has no branch for it. At the anti-zombie bound it prints the raw
   `stopped` attempt instead.

### Why the reconciled result fails

The boundary composes one rule, the owner-report rule behind
`--boundary ship-summary`, into every nullable legacy result slot. Those slots
are control summaries' `result`, the terminal replay's `result`, and ship-summary
v2's `historical_owner_result`. The owner rule says a `merged` row also closed
the issue. That holds for an owner's report, and it is why the rule exists. It
is false for a record the lifecycle writes from a forge observation.
Reconciliation deliberately does not claim the close (quota-suspension D3/D11;
the #171 design keeps `issue_closed` false). So the defect is a contract
mismatch: an owner-report rule is applied to a ledger projection.

The same mismatch has two more forms. A reconciliation that supersedes an
owner's `failed` verdict carries that verdict's detail pointer forward, as
`present` or `unpublished`, and rewrites the notes without the path. The owner
rule refuses that too, because the path is missing from the notes and because
`unpublished` is not allowed on a `merged` row.

## Solution

1. **Ledger-projected result slots get a ledger-result rule (D2–D4).** The
   workflow-response boundary checks the terminal replay's `result` and each
   control summary's `result` against a new rule. It accepts exactly what the
   ledger's writers produce: any result the owner rule accepts, plus the one
   lifecycle reconciliation shape, `merged` with `issue_closed: false`. Owner
   reports stay strict everywhere they enter: both ship-summary boundaries,
   including v2's `historical_owner_result`, and therefore `finish`. Nothing is
   written, migrated or re-shaped in the ledger, and every reconciled record
   already persisted passes.
2. **`progress` returns a closed `phase_gate` reply (D5).** It carries the
   custody identity, the persisted action and the handoff path this call
   finalized, and nothing else.
3. **`suspend` returns a closed, versioned `suspended` reply (D6).** At the
   stall bound it returns the existing `kind: terminal` lifecycle replay of the
   `stopped(stalled)` attempt.
4. **The skills name what they read (D8).** The tests pipe real replies
   through the real boundary (D7).

## Decisions

### Ledger-result rule (artifact-budget)

`validate_ship_summary_report` keeps its meaning and its every caller. It is
the owner-report rule. A new `validate_ledger_result(value,
notes_max_characters)` accepts a value if and only if one of these holds:

- the owner rule accepts it, or
- it is the **lifecycle reconciliation record**:
  - the nine result keys exactly;
  - `issue` an integer ≥ 1 and `state: "merged"`;
  - `pr_url` a non-empty string and `merge_sha` 40 lowercase hex;
  - `issue_closed: false` and `discussion_items: []`;
  - `notes` a string within the shared policy's notes limit;
  - the detail pair is exactly one of:
    - `none`/`null`;
    - `present` with a durable `.superpowers/issue-delivery/…` path;
    - `unpublished` with a retained `.superpowers/…` path.

  The path need not appear in the notes (D4).

Anything else raises `ArtifactBudgetError`. That includes a `merged` row with
`issue_closed: false` and a null PR URL, a short SHA, discussion items, or a
detail pair that does not match.

`_validate_legacy_result_slot` takes the rule to apply as an explicit argument
and keeps its issue-match check. Callers pass the rule as follows:

| Boundary | Slot | Rule |
|---|---|---|
| `workflow-response` | `kind: terminal` → `result` | ledger-result |
| `workflow-response` | control (no `kind`) → each `summaries[].result` | ledger-result |
| `ship-summary` v2 | `historical_owner_result` | owner (unchanged) |
| `ship-summary` v1 | the whole object | owner (unchanged) |

No new `--boundary` value is added. The ledger-result rule has no caller outside
the workflow-response composition.

### Reconciliation (workflow-state)

`reconciled_result` and `reconcile_merged_attempt` behave exactly as today. The
record still asserts only what the forge observed, and `issue_closed` stays
`false` even when the same request observed the tracker closed (D2). Only the
`reconciled_result` docstring changes. Its sentence about the ledger's own
schema is replaced by one naming the ledger-result rule as the response
contract its record meets. No schema version changes, and there is no load-time
repair. Every record reconciliation has written validates under D4: bare, or
carrying a superseded pointer. Both records found in the local ledgers are bare.

### `progress` reply: `phase_gate`

`command_progress` persists exactly what it persists today. Its transaction then
returns, and it prints, this closed object instead of the attempt:

```json
{"interface_version": 2, "kind": "phase_gate", "run_id": "direct-191-000001",
 "issue": 191,
 "custody": {"kind": "implementation", "attempt": 1, "launch": 1,
             "action_id": "191:1:1"},
 "action": "delegate", "handoff_path": null}
```

- `run_id` and `issue` are the call's own; `custody` is the attempt's current
  launch identity, rendered by the delivery runtime's one custody renderer
  (`custody_for_record`), never recomposed in `workflow-state`.
- `action` is the phase action this call persisted: `continue | fresh_start |
  handoff | delegate`.
- `handoff_path` is the absolute path this call finalized with
  `--handoff-path`, after which the attempt is `handed_off`. Otherwise it is
  `null`. It is not the attempt's stored `handoff_path`, which survives a
  resume and would echo an earlier handoff.

The delivery model's `_workflow_response` gains a `phase_gate` branch. It checks
the exact member set, `interface_version` 2, a string `run_id`, an issue ≥ 1, an
implementation custody for that issue (`validate_custody_ref`), `action` in the
closed set, and a `handoff_path` that is null or a non-empty string, and
non-null only when `action` is `handoff`.

### `suspend` reply: `suspended`, or `terminal` at the stall bound

A granted suspension prints:

```json
{"interface_version": 2, "kind": "suspended", "run_id": "issue-14-test",
 "issue": 15,
 "custody": {"kind": "implementation", "attempt": 1, "launch": 1,
             "action_id": "15:1:1"},
 "blocked_on": "usage_limit", "reentry": "/from-issue 15 --auto"}
```

`attempt` is replaced by `custody`, and `stalled_resumes` leaves the wire (D6).
The `_workflow_response` branch checks the exact member set, `interface_version`
2, a string `run_id`, an issue ≥ 1, an implementation custody for that issue,
`blocked_on` in the owner-reachable set `usage_limit | transport | human_gate |
external`, and a non-empty string `reentry`. The literal set follows the
checkpoint-response branch's precedent.

At the stall bound (`suspend_attempt` returns `False`), the transaction records
the `stopped(stalled)` outcome as today. The reply is `direct_terminal(issue,
run_id, source="lifecycle", reason="stopped", blockers=[], result=<the issue
outcome>)`, the existing `kind: terminal` envelope. For a direct run it is
byte-equal to the replay the next `direct-owner` call returns for that issue.

Both new kinds carry `interface_version` 2, the owner-facing lifecycle wire of
the `owner`, `terminal`, checkpoint and finish replies. Adding a kind grows the
closed dispatch without renumbering. A validator that predates it refuses it
(fail closed), and producer and validator ship in one build.

### Skills

- In `from-issue/SKILL.md`, the executable phase gate says that the returned
  action is the validated `phase_gate` reply's `action`. The pinned sentence
  "Obey the returned action exactly" stays.
- The suspension procedure's command literal is piped through
  `artifact-budget validate-report --boundary workflow-response --input -`. One
  sentence covers a `kind: terminal` reply: the stall bound ended the attempt,
  so handle it as the terminal replay in the terminal return procedure: print
  its `reentry`, relay it, and write no `finish`.
- `AUTO.md`'s "persisted action `delegate`" already names the value the reply's
  `action` carries, so AUTO.md is unchanged.
- No architecture or standards document describes these replies, so none
  changes.
- The instruction-load ceilings of every profile that hot-loads
  `from-issue/SKILL.md` are raised to the measured values. Each profile's `note`
  names #191 in the same commit (#155 D10).

## Test seams

Five seams, all existing. No test calls a private helper to prove a reply
shape.

1. **Real lifecycle CLI → real boundary CLI** (`test_workflow_state.py`), after
   #194's `control_validated`. The harness's `progress()` and `suspend()`
   helpers pipe every successful reply through `artifact-budget validate-report
   --boundary workflow-response`. They assert exit 0 and that the canonical
   stdout equals the reply bytes, then return the decoded reply. Every existing
   progress and suspend test thereby becomes a boundary regression (D7).
   Assertions on ledger fields read the ledger. Named regressions:
   - A suspended, contractless attempt with `forge: merged` and `tracker:
     closed` gets a validated control response: summary `merged`, result
     `issue_closed: false`. A second sweep validates too. The same holds with
     the tracker `open` (acceptance 1).
   - A ledger written with the exact persisted shape from the #154 run is swept
     and validates. So does a direct re-entry's raw `kind: terminal` replay,
     read from unprojected stdout. Variants carrying a superseded `present` and
     `unpublished` pointer also validate (acceptance 2).
   - Each `phase_gate` action, including `--handoff-path` finalization, and a
     resumed attempt whose stale stored handoff path is not echoed.
   - The stall-bound `suspend` reply is a validated `kind: terminal` equal to
     the next `direct-owner` replay.
2. **artifact-budget CLI** (`test_artifact_budget.py`, extending
   `test_v2_boundaries_compose_legacy_result_validation`). The reconciliation
   record is accepted in the terminal and control-summary slots. It is refused
   as v2 `historical_owner_result` and as a v1 ship-summary. Each mutation
   listed under the ledger-result rule is refused in a response slot.
3. **Delivery-model validator** (`test_delivery_model.py`, over
   `_delivery_model_fixtures.workflow_responses`). The fixtures gain `phase_gate`
   and `suspended` specimens. Each must validate, and each closed-shape
   violation must be refused:
   - an extra or missing member;
   - `interface_version` 1;
   - a remainder custody, or a custody for another issue;
   - an unknown action, or a `handoff_path` on a non-`handoff` action;
   - `blocked_on` `unknown` or `host_capacity`.
4. **Skill contracts** (`test_workflow_skill_contracts.py`). These pin the
   suspend literal's validator pipe, the stall-bound terminal sentence, and the
   `phase_gate` wording. The existing pins stay.
5. **Instruction load** (`test_instruction_load.py`'s real-tree ceiling check).
   It stays green at the raised ceilings.

## Out of scope

- #192: delivery contracts for slugless legacy worktrees, and a post-review main
  sync stranding a remainder.
- Replies that already validate: `control` apart from its result slots,
  `direct-owner` apart from its terminal `result`, `init-run`, `finish
  --summary-file`, `checkpoint-delivery`, `check-launch`/`current-launch`,
  `host-route`. The legacy `finish --result-file` transport is historical input
  only, and its reply is not a workflow response.
- Any change to owner-report strictness at either ship-summary boundary, or to
  `finish`'s inner ship-summary check.
- Putting `result_source` on the wire (D3), and recording a tracker-observed
  close in the reconciled record (D2).
- Launch fencing of `progress` or `suspend`. #125 owns it (#133 D11). The
  replies' `custody` is identity, not a fence, and owners keep `check-launch`.
  A stale predecessor's reply names the current launch, and no skill acts on
  that.
- Closing a tracker issue that is still open after a reconciled merge. The
  record says the close was not observed, and nothing here closes it.
- Legacy rows from before the artifact-budget policy that the owner rule
  already refuses. This change widens the result slots only by the
  reconciliation record.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Scope: reconciled results must validate in every workflow-response slot, including records already persisted; `progress` and `suspend` get closed, versioned kinds; regression tests pipe real replies through the boundary; from-issue prose names the reply fields. #192 and owner-report strictness are out. | Orchestrator's Phase-0 scope decision; the owner's issue comment reports the `progress` defect on this issue; the skills' "validate every reply" rule covers `suspend` identically. | Splitting `progress`/`suspend` into a new issue: same symptom, same validator, same fix pattern, and the owner filed it here. |
| D2 | Fix the contract, not the record: the workflow-response boundary checks ledger-projected result slots with a ledger-result rule (owner rule ∪ the reconciliation record). Reconciliation keeps `issue_closed: false` even when the tracker is observed closed. | Reconcile fires on `forge: merged` whatever the tracker says, and direct-owner may send no tracker at all; the-bar *Root causes* (the owner rule is the wrong contract for a ledger projection); quota-suspension D3/D11 and #171 (reconcile asserts only the forge). | Deriving `issue_closed` from the request's tracker observation: misses every open or unobserved tracker. It would also give lifecycle records the owner-report shape, erasing the one visible difference. |
| D3 | No `result_source` on the wire. In a ledger projection, `merged` with `issue_closed: false` is itself the lifecycle signature. Both `finish` transports validate owner reports at a ship-summary boundary before persisting them, and every other ledger writer emits owner-rule-valid rows. | the-bar *Token economy* and *DRY* (a field restating what the shape already says); every result writer in `workflow-state`/`workflow_delivery` checked. | Adding `result_source` to control summaries and terminal replays: a closed-shape change on two interfaces, test and skill churn, and a second home for a fact the shape carries. |
| D4 | The reconciliation record's detail pair accepts `none`, `present` or `unpublished` with the matching path kind, without requiring the path in the notes. No producer change, no schema bump, no repair. | Every record reconcile has ever written validates, including a pointer carried from a superseded owner verdict. The pointer stays a structured field. Orchestrator: "a validator that accepts them needs no migration". | Rewriting reconcile's notes to cite the path, plus a schema-5 migration for persisted records: a ledger rewrite for a shape no local ledger holds. |
| D5 | `progress` returns `{interface_version: 2, kind: "phase_gate", run_id, issue, custody, action, handoff_path}`. `handoff_path` is only the path this call finalized. | Owner comment ("phase_action plus custody identity"); the-bar *Token economy*; the skills read only the action and handoff finalization. | Exempting `progress` in the skills: breaks "every reply is untrusted transport" and keeps ledger internals on the wire. Echoing the stored `handoff_path` would replay a stale handoff after a resume. |
| D6 | `suspend` returns closed v2 `{kind: "suspended", run_id, issue, custody, blocked_on, reentry}`, dropping `attempt` for `custody` and `stalled_resumes` as a ledger internal. At the stall bound it returns the existing `kind: terminal` lifecycle replay. | #133 D4 (a stall escalation is a `terminal` whose envelope equals the next replay); the-bar *Truthful terminal states*; the skills print only `blocked_on` and `reentry`. | A new `stalled` reply kind grows a closed set that validators, skills and tests all mirror. Keeping `stalled_resumes` exposes an anti-zombie counter nothing may act on. |
| D7 | Test seam: the lifecycle harness's `progress`/`suspend` helpers validate every real reply at the real boundary, as #194's `control_validated` does, and ledger assertions read the ledger. | the-bar *Tests that can fail*; #194 precedent; about 50 existing call sites become regressions at once. | Only dedicated regression tests: the other call sites would keep decoding bytes no caller may decode. |
| D8 | Skills: the phase gate names the `phase_gate` reply's `action`; the suspend literal pipes through the validator; a stall-bound `terminal` reply is handled as a terminal replay. AUTO.md stays unchanged. Ceilings are raised with notes. | from-issue's validate-before-decode rule; #155 D10 (a raised ceiling rewrites its note in the same commit); the existing pins stay. | Rewording AUTO.md's "persisted action": churn, since the reply's `action` is the persisted action. |
