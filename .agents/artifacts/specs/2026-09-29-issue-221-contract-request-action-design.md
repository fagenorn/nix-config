# Control asks for a missing delivery contract instead of finalizing, issue 221

## Problem

In a chained `orchestrate-issues` run (each issue blocked by the one before),
every time a blocker closed, `workflow-state control` answered `finalize` while
the newly unblocked issue's summary carried `delivery_contract_required`. The
skill tells the adapter both to send a contract "while its latest summary
carries `delivery_contract_required`" and to execute the returned actions, and
`finalize` ends the run. In run `run-20260927-204-205-206-207-208-209` the
adapter had to override `finalize` four times and send the contract in an extra
control call, which then spawned the issue. A run that needs judgment at every
link is not an automated run.

## Current behavior (verified at base 93bf5fd)

All citations are to `home/common/agent-skills/scripts/workflow-state.py`
unless named otherwise.

- A would-be spawn or retry with no effective contract plans the operation
  `"contract"` (:2253), and so does a would-be resume (:2116). `admit` queues
  nothing for an operation outside the dispatch kinds, so the sweep creates no
  custody for that issue.
- The spawn, retry and resume lanes plan with dispatch permitted only while
  `max_parallel` capacity and a whole role set remain. An issue skipped for
  lack of a role set joins `waiting` instead (`slot_withheld`).
- A summary asks for a contract when the issue's planned operation is
  `"contract"`, or when it is in `waiting` with no installed contract (:2774-2789).
- The terminal action depends only on `next_deadline` (:2797-2804). With no
  active or handed-off custody the deadline is null and the sweep returns
  `finalize`, whatever the summaries ask for. The controller claim is released
  `finalized` under the same condition (:2754-2766).
- `direct-owner` handles the same operation by returning an `observe` response
  with a `delivery_contract` requirement (:3094-3111). That response carries no
  terminal action, so it asks and waits for the answer.
- The workflow-response validator accepts a closed action-kind set: `spawn`,
  `resume`, `retry`, `wait`, `finalize`, `delivery_remainder`. It also rejects
  any action whose `issue` summary lacks a contract
  (`home/common/agent-skills/scripts/delivery_model/_wire.py`:207-216).
- `orchestrate-issues` §3 has the adapter send a contract while the summary
  asks. §4 then says to execute the closed kinds in order, and to finalize "when
  nothing can proceed without a human" (`SKILL.md`:175-215, 240, 340-345).

When A closes and B is unblocked, B's sweep plans `"contract"`. Nothing is live,
so control returns `finalize` alongside B's `delivery_contract_required`. A test
that replaces only the terminal choice in a scratch copy leaves every lifecycle
suite green, so no existing test pins `finalize` over such an issue.

## Solution

Control gains one terminal action, `delivery_contract`. It is returned in place
of `finalize` when no deadline is armed and at least one requested issue planned
`"contract"` in this sweep:

```json
{"id": "delivery_contract", "kind": "delivery_contract", "issues": [15]}
```

`issues` lists, in request order, every issue that planned `"contract"`. Each
listed issue's summary carries `delivery_contract_required`. The action tells
the adapter that a contract is the only thing stopping these issues, and that
nothing else will wake the run. The adapter supplies each listed issue's
contract, as §3 already requires while the summary asks, and makes the next
control call at once. That response takes over from this one. When none of the
listed issues can get a contract, because the builder refused each of them
earlier in this invocation, the action ends the run just as `finalize` does.

`finalize` is unchanged whenever no requested issue waits only on its contract.
A sweep that still has a deadline armed still returns `wait`. A contract a
summary asks for then goes out on the next wake, as it does today.

## Decisions

- **Control.** The terminal choice becomes three-way: `wait` when a deadline is
  armed, else `delivery_contract` when any issue planned `"contract"`, else
  `finalize` (per D1, D2). Admission-waiting issues are never listed (per D3).
  A `delivery_contract` sweep takes the admission path of any sweep with no
  deadline (per D4). Nothing else in the sweep changes: planning, persistence,
  deltas, summaries and `next_deadline` (null). A follow-up call that supplies
  a listed issue's contract makes that issue's contract effective, so it can
  never plan `"contract"` again. Each `delivery_contract` round therefore either
  installs at least one contract or ends the run, and the exchange cannot loop.
- **Wire boundary.** The workflow-response validator accepts the new kind and
  checks it against the rest of the response (per D6). There is no interface
  version bump (per D8).
- **Skill.** `orchestrate-issues` §4 adds `delivery_contract` to the closed
  kinds. It holds the one rule for an issue whose only obstacle is a missing
  contract: supply the contracts per §3, call control again at once, and end as
  `finalize` only when every listed issue's build was refused (per D5). §3's
  summary-keyed send rule is unchanged and points to that rule. The sentence
  "when nothing can proceed without a human, control returns finalize" is
  narrowed to exclude a missing contract. §5 renders the final report of a
  refusal-ended `delivery_contract` from that response, as for `finalize`. The
  closed-set enumeration in `evals/evals.json` gains the kind.
- **Placement.** The fix stays in the flat script and in the delivery model's
  wire module (per D7).

## Acceptance criteria

| Issue criterion | Design coverage |
|---|---|
| 1. B blocked by A. A is delivered and closed; B's contract is not installed. The next reply has no `finalize` and names B; the test fails at base | Control test T1, `actions == [delivery_contract(issues=[B])]`, B's summary asks. It fails at base, where the actions are `[finalize]` |
| 2. Sending B's built contract next yields `spawn` for B | T2 continues T1 with B's contract, initial intent and a verified-absent candidate, and gets `spawn` for B |
| 3. Nothing can progress, so `finalize` stays | T3: every issue is blocked, closed or terminal. The actions are `[finalize]`, and the existing finalize assertions stay green |
| 4. The skill states the single rule, with no override | §4 `delivery_contract` entry, pinned by skill-contract anchors (T5) |
| 5. `just agent-workflow-tests` passes | The full recipe is run in verification |

## Test seams

- **`workflow-state control` CLI**, driven by the `ContractLifecycleTest`
  harness in `test_delivery_workflow.py` (`control_request`, `build`, real
  contracts). T1–T3 run there. T1 must fail at base. Also T4: a sweep with a
  live custody and a contract-requiring issue still returns `wait`, which pins D2.
  T6: replaying T1's request without B's contract returns the same reply and
  leaves the ledger bytes unchanged, which pins D4's no-new-claim rule.
- **`artifact-budget validate-report --boundary workflow-response`**, through
  the control-fixture tests in `test_delivery_model.py` (the `with_fact`
  pattern). They accept the T1 reply and reject each broken coupling in D6.
- **Skill text**, through the §4 anchors in `test_workflow_skill_contracts.py`:
  the closed-kind enumeration and the rule sentence (T5).

No new seam is introduced (per D9).

## Out of scope

- A sweep with an armed deadline that also has a contract-requiring issue. It
  keeps `wait`, and the contract goes out on the next wake (per D2).
- The #125 transaction-core migration, and moving `workflow-state` into
  `agent_tools`.
- `direct-owner` and `from-issue` direct autonomous acquisition, which already
  ask with `observe`. From-issue's explicit durable interactive route does call
  `control` and gets one sentence answering the action (D12).
- The Codex `orchestrate-issues` stub, which only relays `host-route` and never
  sees a control reply.
- Any change to the control request, the bootstrap, admission accounting or
  contract installation.

## Open questions

- **Q1, signal shape.** A new terminal action kind that lists the issues,
  following the `direct-owner` precedent of asking rather than ending (D1).
- **Q2, admission-waiting issues.** They are not listed and keep their D21
  summary requirement (D3).
- **Q3, validator, schema and Codex stub.** The validator changes (D6). There is
  no version bump (D8). The Codex stub is unchanged (D7).
- **Q4, skill wording.** One rule, in §4's `delivery_contract` entry, which §3
  points to (D5).

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | New terminal action `{"id":"delivery_contract","kind":"delivery_contract","issues":[…]}` replaces `finalize` when no deadline is armed and at least one requested issue planned `"contract"`. `issues` is in request order | Issue 221 "typed signal … or a documented non-final action"; direct-owner asks through `observe` rather than ending; control-plane D4 (one terminal action); #171 D10 named "a premature `finalize` ends the run" as a hazard. The kind reuses the requirement's name, as `delivery_remainder` names both an action and a custody | Keep `finalize` plus summaries (the status quo, which needs the override). A `wait` due now (a fake timer, with an observer armed for nothing). A bare action with no `issues` (the adapter re-derives the list from summaries and picks up waiting issues) |
| D2 | Only `finalize` is replaced. A sweep with an armed deadline keeps `wait`, and the §3 summary-keyed rule sends the contract on the next wake | The issue scopes the defect to `finalize`; the-bar YAGNI; the wait handle state machine (control-plane D11) stays untouched | Also pre-empt `wait` (adds rules for superseding an uninstalled wait to the adapter's wait state for a latency the issue did not report) |
| D3 | Admission-waiting issues are never listed. They keep reporting `delivery_contract_required` (#150 D21) | #171 D10: a supplied contract installs only at a dispatch; the validator rejects actions on waiting issues | List them (a slot-withheld issue would be asked for its contract on every follow-up call, which loops) |
| D4 | A `delivery_contract` sweep is a no-deadline sweep for admission. As #150 D20 does for `finalize`, it persists no new controller claim and releases a held one `finalized`; the follow-up call claims again | #150 D20; the blast-radius run left the admission suites green; nothing is live when this action appears | Keep the controller claim (a new release condition, and a claim left held when the adapter ends on a refusal). Accepted consequence: refusal-gated custody reopens on the follow-up call, as it would on re-invocation (#150 D26/D31) |
| D5 | Adapter rule for `delivery_contract`: supply each listed issue's contract per §3 (reuse the pair built this invocation, else build now) and call control at once. An issue whose build was refused is not rebuilt in the same invocation, and it sends null and `[]`. If the builder refused every listed issue in this invocation, clear the wait state and render §5 from this response, as `finalize` does. This rule is written once, in §4 | Issue criterion 4; §3 already tracks refusals for the final report; control re-asks deterministically | A refusal marker in the request (widens the closed 18-key request for an edge case). Always calling again (it loops forever on a refused build) |
| D6 | The validator accepts `delivery_contract` only when all of these hold: its members are exactly `id`, `kind` and `issues`; `id` is `"delivery_contract"`; `issues` is non-empty, unique and in summary order; every listed summary carries `delivery_contract_required` and is not in `admission.waiting`; it is the last action; `next_deadline` is null; and the reply has no `wait` or `finalize` | the-bar *Defense in depth* and *Fail loud*; the existing coupling checks in `_control_response` | Check the shape only (a reply that asks for an already-installed contract, or that pairs the action with `finalize`, would pass the boundary the adapter trusts) |
| D7 | The code change stays in the flat `workflow-state.py` and in `delivery_model/_wire.py`. The Codex stub and direct acquisition are unchanged | `docs/standards/agent-helpers.md` binds a legacy script only when its cluster moves; the issue says "does not wait for the #125 migration" | Moving control into `agent_tools` first (an unrelated cluster move) |
| D8 | Control stays at `interface_version` 3. An adapter from before this change fails loud on the unknown kind, per its §4 rule | Validator, skill and helper ship in one Nix generation; the §4 unknown-kind rule; the-bar YAGNI | Bump to 4 (rewrites every interface-3 request, fixture and skill anchor for one added kind) |
| D9 | Test seams: the `control` CLI through the `ContractLifecycleTest` harness, the workflow-response fixture tests, and the skill-contract anchors. T1 must fail at base | the-bar *Tests that can fail*; existing harnesses | A new unit seam inside the `control` closure (it is not importable, so the test would need a patch-in seam) |
| D10 | Raise the `orchestration-dispatcher` profile's `ceiling_bytes.claude` in `instruction-load.json` to the grown `orchestrate-issues/SKILL.md` byte count, with a note naming #221 | `test_the_live_tree_breaches_no_ceiling` pins the ceiling at the current byte count (22559); earlier issues raised it with a note (#198, #155 D10) | Cut unrelated SKILL.md prose to offset the growth (rewording churn outside this issue's scope) |
| D11 | T1–T4 and T6 seed issue 171's delivery as a merged attempt written straight into the ledger, with a closed tracker, instead of driving 171 through spawn, finish and forge reconcile. The control change lands before the validator change, so T1 runs against the unchanged `workflow-state.py` and fails there | A scratch run at base showed that a merged forge leaves live custody untouched (the reply is `wait`), while the seeded ledger reproduces `[finalize]` with 172 asking; the harness already seeds ledgers with `write_run` | Drive 171 through the full owner lifecycle (dozens of fixture steps that do not exercise this change) |
| D12 | From-issue's explicit durable interactive acquisition, the one other interface-3 `control` consumer, answers a `delivery_contract` naming its issue by building the contract and calling control once more; one prose sentence, no code (narrows D7's "direct acquisition is unchanged") | Phase-5 review SF-1: that route requires exactly one dispatch action and fails loudly otherwise, so without a rule it would reopen the adapter-judgment gap #221 closes | Keep it out of scope (the route would fail loudly on its own documented reused-run path) |
| D13 | Every validator and admission guard this change adds has a test only it turns red: a non-numeric summary order, a `not_last` case rejected only by position, order equality replacing a separate duplicate clause, and T7 pinning a held controller claim's `finalized` release on a `delivery_contract` sweep | Phase-5 review SF-2/SF-3; the-bar *Tests that can fail* | Rely on the subtests as planned (deleting the last-position or numeric-order guard turned nothing red) |
