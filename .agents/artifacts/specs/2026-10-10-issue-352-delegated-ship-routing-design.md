# Issue 352 — ship in a fresh context after an orchestrated rollover

Issue: https://github.com/fagenorn/nix-config/issues/352

## Problem

An orchestrated issue owner whose phase gate hands the remainder to a fresh issue owner ends up shipping inline, in the context that just ran the whole implementation. The chain is orchestrator → issue owner → delegated owner → ship owner, and the ship owner at the end of it has no subagent-launch tool: ship-issue's Phase-0 probe returns `capability_gap: agent_dispatch`, and the delegated owner takes the dispatch-gap fallback. On the consumer project this happened on 3 of 3 rolled-over issues; each inline ship turn re-read 330–380k tokens, against 115–170k in a dedicated ship agent.

Measured depth (D4): counting the user's session as depth 0, an agent at depth 2 can launch subagents and an agent at depth 3 cannot. The ship owner must therefore sit at depth 2 or above, so that its reviewers sit at depth 3.

| Route | Ship owner depth | Reviewers launch |
|---|---|---|
| Orchestrated, no delegation (0 → issue owner 1 → ship owner 2) | 2 | yes |
| Direct autonomous rollover (controller 0 → fresh owner 1 → ship owner 2) | 2 | yes |
| Orchestrated, generic `delegate` (0 → issue owner 1 → delegated owner 2 → ship owner 3) | 3 | no |

Only the third route is broken.

## Solution

On the generic `delegate` route, the delegated owner stops at the end of Phase 6 and returns the validated ship handoff to the owner that delegated to it. That owner, still holding the same launch identity, registers and launches the ship owner, handles its report and makes the terminal write, exactly as an owner that never delegated does in Phase 7. The ship owner is then at depth 2 on the orchestrated route.

Nothing in the ledger changes: a `delegate` action creates no attempt and no launch, so both owners act under one `action_id` throughout.

## Decisions

### The delegate prompt names the return

Outside the direct-autonomous route, the prompt an owner composes for the `from-issue-phase-delegate` dispatch carries one closed line, on a line of its own:

```text
Delegated owner: return the ship handoff
```

The receiving owner matches it byte for byte. With the line, it reads `delegated-owner.md` and follows that file's new generic-delegate section; `SKILL.md`'s index entry for `delegated-owner.md` names both delegated owners. The rule binds the dispatch site, not the gate action that led to it, so it holds for any path on which a non-direct owner dispatches a fresh issue owner there. The direct-autonomous rollover prompt (the continuation of `rollover.md`) never carries the line.

### The delegated owner (generic route)

It adopts the envelope as `acquire-dispatcher.md` says and runs every remaining phase through Phase 6 under the generic rules, with three departures:

1. **No second delegation.** A `delegate` action at any of its own phase gates is taken as `continue`; it never dispatches another issue owner, whose children could launch nothing.
2. **Phase 6 ends in a return, not a dispatch.** After Phase 6's own gates pass, it rechecks the spec and plan roots and builds and validates the ship handoff exactly as `ship-handoff.md` says for the ship-owner prompt (`ship-handoff/v2` with lifecycle identity, the legacy shape without). It then releases every worker it registered with `--event returned`, and returns only the canonical stdout of `artifact-budget validate-report --boundary ship-handoff`. It makes no Phase-6 `workflow-state progress` call, registers and dispatches no ship owner, never invokes `ship-issue`, never takes the dispatch-gap fallback, runs no `launch-scope reap` and writes no `finish`.
3. **Every other exit is still its own.** While it runs it is the launch's only acting owner, so the `handoff` action, the suspension procedure, a rejected `progress` and a terminal failure (a Phase-6 execution failure included) run as `SKILL.md` says, self-reap first, and it returns what that exit prints: the re-entry line, the `Suspended (…)` line, or the validated `finish` reply. The `handoff` action prints none of these; its return falls to the delegating owner's case 4, where the fence finds the attempt handed off.

### The delegating owner

After the dispatch it waits for the return (the Interim child results rule applies) and takes the first case that matches:

1. Only the canonical re-entry line, or only a canonical `Suspended (blocked_on=<value>). Resume: …` line, matched byte for byte: relay it unchanged, write nothing, stop.
2. Bytes that validate at `--boundary workflow-response`: the delegated owner's own `finish` reply. Relay the canonical bytes unchanged, write nothing, stop.
3. Bytes that validate at `--boundary ship-handoff` with `state: complete` and whose identity equals this owner's (`ledger_repo_root`, `run_id`, `owner`, `issue_number` and `custody.action_id` in `ship-handoff/v2`; `issue_number`, `branch` and `worktree_path` in the legacy shape): the Phase-6 result. Call `workflow-state progress` for completed Phase 6 with this owner's own truthful usage, then run Phase 7 from the ship-owner registration and dispatch, passing those validated bytes unchanged as the handoff. It never rebuilds or edits the handoff.
4. Anything else, a dispatch failure included: a contract failure through the terminal return procedure, whose `check-launch` fence writes nothing and prints the re-entry line when the delegated owner already ended the launch.

Without lifecycle identity the same four cases apply with the legacy handoff, and the `progress` call, the registration and the fence are skipped as everywhere else on the ledger-free route.

In cases 1 and 2 the delegating owner does not reap: the delegated owner already did, before its exit write. In cases 3 and 4 it reaps at its own exit, as every owner does. `SKILL.md`'s Self-reap rule is restated to say that: the launch is reaped by whichever of the two owners makes the exit that ends it.

### The Phase-6 gate

At the completed-Phase-6 gate, on every non-direct route, a `delegate` action is the Phase-7 ship-owner dispatch itself and never a second issue owner. The other actions keep their meaning. A `handoff` taken there discards the returned handoff bytes; the relaunched owner builds its own at Phase 7.

### The inline route

The dispatch-gap fallback stays as written for an owner whose own ship-owner launch is impossible or returns the gap line. `ship-handoff.md` states that a generic delegated owner never takes it. On a host with subagent launch the fallback is no longer reachable from the orchestrated delegation route.

### Invariants held

- **Launch identity.** One attempt, one launch, one `action_id` from acquisition to `finish`; the ship owner is a worker `<action_id>:w<n>` registered by the delegating owner after every worker of the delegated owner was released.
- **Fence.** The delegating owner's terminal write and the ship owner's forge writes pass the same `check-launch` and `check-worker` fences as today; no fence call is added, removed or reordered.
- **Reviewed tip.** `head_sha` in the handoff is copied from the sdd report by the owner that validated that report, and the handoff bytes travel unchanged from that validation to the ship owner.

### Unchanged

`scripts/workflow-state.py`, `rollover.md`, the direct-autonomous half of `delegated-owner.md`, `resume-pack.md`, `ship-issue`, `orchestrate-issues`, every dispatch marker line and `model-matrix.json`.

### Instruction budget (D7)

No ceiling is raised and no file is added. `instruction-load.json` changes at most the `implementation-owner` profile's `note`. Measured headroom at the base, in bytes: controller hot 258 and conditional 1; orchestrated issue owner hot 521 and conditional 28; implementation owner hot 522 and conditional 27; corpus 526. Consequences the plan must honour:

- `ship-handoff.md` and `resume-pack.md` do not grow; `acquire-dispatcher.md` grows by at most 27 bytes.
- `SKILL.md`, `AUTO.md` and `rollover.md` together grow by at most 258 bytes; the whole change grows the corpus by at most 526.
- The delegating owner's text goes into `SKILL.md`'s `delegate` action, the delegated owner's into `delegated-owner.md`.
- Unpinned text that may be cut to pay for it: `SKILL.md` Phase 7's rationale sentence after the dispatch line (151 bytes), Self-reap's last sentence, which is rewritten (102), `AUTO.md`'s sentence restating that the other routes keep their behaviour (307), and the opening sentence of `ship-handoff.md`'s dispatch-gap fallback (130).

`home/common/agent-skills/README.md` § Lifecycle helpers gains a short paragraph on the delegated return. The gate's corpus is the skill directories (their `evals/` and `scripts/` excluded), the agent definitions and the frame, so neither that paragraph nor the new evals count against it.

## Test seams

1. **Ledger, at the `workflow-state` command line** — `tests/test_workflow_state.py`, the `LifecycleHarness` used by `WorkerRegistryTest` and `OwnerExitFenceTest`. One scenario on a non-direct run: acquire an owner; record Phase 5 with a persisted `delegate`; register and release a worker as the delegated owner; record Phase 6; register the ship owner under the same `action_id`. Asserted: the attempt and launch counts stay 1; the ship worker's id is the launch's next ordinal with a null parent and is the only live worker; `check-launch` and `check-worker` answer current and live; `finish` is refused while the ship worker is live and accepted after its release; afterwards `check-launch` answers `inactive_attempt` and `register-worker` is refused. A second case: after a relaunch, `register-worker` under the earlier `action_id` is refused as `superseded_launch`.
2. **Skill text, machine-consumed strings only** (`docs/standards/agent-helpers.md` rule 6) — `tests/test_workflow_skill_contracts.py`: the closed prompt line is spelled identically in `SKILL.md` and `delegated-owner.md`; the generic-delegate section names `--boundary ship-handoff` and `release-worker`, and names neither `workflow-state finish` nor `--boundary ship-summary`; `SKILL.md`'s `delegate` action names `--boundary workflow-response` before `--boundary ship-handoff`. An existing English-phrase pin broken by a cut is deleted, not rewritten.
3. **Evals** — three `plan-only` cases appended to `skills/from-issue/evals/evals.json`, each with an `expected_output`: (a) orchestrated depth, the delegated owner at the end of Phase 6: it returns the validated handoff and neither launches a ship owner nor ships inline; (b) orchestrated depth, the delegating issue owner on each of the four returns; (c) an owner with no subagent-launch tool: the inline fallback, fenced by `check-launch`. A contract test asserts the file parses and the three case names are present.
4. **Instruction budget** — `just agent-instruction-budget` passes with no raise label.

## Acceptance mapping

| # | Criterion | Kind | Verified by |
|---|---|---|---|
| 1 | A rolled-over orchestrated issue ships through a dedicated ship agent, 0 gap hand-backs | evidence | Not verifiable here: stays `human_pending` until the next orchestrated nodocom run with ≥ 2 rolled-over issues. |
| 2 | Ship phase averages ≤ 200k tokens per turn | evidence | Not verifiable here: stays `human_pending`, measured on that same run. |
| 3 | Rollover and ship-handoff instructions route delivery through a level that can dispatch; inline only without subagent launch | code | Seam 2 and seam 3 under `just agent-workflow-tests`; each new eval graded once against the worktree's skill text during execution, the verdicts recorded with the acceptance evidence; seam 4. |
| 4 | Launch identity unchanged: one attempt, one ship owner, fenced forge writes | code | Seam 1 under `just agent-workflow-tests`. |

The issue is therefore held with `needs-verification` at ship, not closed.

## Out of scope

- The two `[evidence]` criteria's measurement.
- The direct-autonomous rollover and its controller's validate-relay-stop contract (D4).
- ship-issue's Phase-0 probe, and orchestrate-issues' dispatch and fan-out.
- The `fresh_start` and `handoff` gate actions, and which gate inputs an orchestrated owner reports.
- A ledger record of delegation or of worker roles: the ledger cannot tell a ship owner from any other worker, and this change does not teach it to.
- A direct-autonomous run started inside a subagent, where every depth above shifts by one; the dispatch-gap fallback still covers it.

## Triage

Input: {"signals":{"contract_change":{"value":"hit","evidence":"The delegated implementation owner's return contract changes: it hands a validated Phase-6 result back to the issue owner instead of dispatching the ship owner and returning the finish reply."},"concurrency_or_persistence":{"value":"doubt","evidence":"Launch identity, worker registration and the check-launch fence must hold across a returned implementation owner; workflow-state tests are required and a helper change may follow."},"open_design_questions":{"value":"hit","evidence":"The issue leaves the routing to the implementer: which level launches the ship owner and what the implementation owner returns."},"criteria_shape":{"value":"hit","evidence":"Four criteria, two of them [evidence] measured on a later consumer-project run that no deterministic code check verifies."}},"paths":["home/common/agent-skills/skills/from-issue/SKILL.md","home/common/agent-skills/skills/from-issue/AUTO.md","home/common/agent-skills/skills/from-issue/rollover.md","home/common/agent-skills/skills/from-issue/delegated-owner.md","home/common/agent-skills/skills/from-issue/ship-handoff.md","home/common/agent-skills/skills/from-issue/resume-pack.md","home/common/agent-skills/skills/from-issue/evals/evals.json","home/common/agent-skills/instruction-load.json","home/common/agent-skills/README.md","home/common/agent-skills/tests/test_workflow_state.py","home/common/agent-skills/tests/test_workflow_skill_contracts.py","home/common/agent-skills/scripts/workflow-state.py"]}
Verdict: {"hits":["contract_change","concurrency_or_persistence","open_design_questions","criteria_shape","risk_path"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The generic delegated owner returns at the end of Phase 6 and the delegating owner launches the ship owner (carryover 1). | The issue's suggested shape; the delegating owner already holds the launch identity and Phase 7's text; the ship owner lands at depth 2. | The orchestrator relaunching a fresh owner instead of the in-owner delegation: changes orchestrate-issues and spends a launch ordinal. A depth-3 ship owner whose parent launches its reviewers: changes ship-issue's probe, which is out of scope. |
| D2 | The return is the validated ship handoff, checked at `--boundary ship-handoff` by both owners and passed on unchanged (carryover 2). | `the-bar.md` defense in depth; `AUTO.md`'s relay of validated objects unchanged; an existing boundary, so no schema or helper is added; a mechanical-only Phase 6 produces no sdd report but does produce a handoff. | Returning the sdd report: the delegating owner would rebuild the handoff over several turns in its largest context, and mechanical-only has none. A new return schema: new helper code and an instruction-budget raise for no added safety. |
| D3 | A Phase-6 return releases the delegated owner's workers and does not reap; an exit that ends the launch is reaped by the owner that makes it. The delegating owner makes the Phase-6 `progress` call (carryover 3). | Self-reap is defined on exits that end the launch, and a return does not end it. `launch-scope reap --action-id` never reads or writes the ledger, so a reap could not stop the later `register-worker`; it would only delete the scratch root the launch still shares. The gate judges the context that continues. | Reaping on return: harmless to the ledger but removes shared scratch mid-launch and adds a second reap site. The delegated owner calling Phase-6 `progress`: it would have to obey an action about a conversation that is ending. |
| D4 | The direct-autonomous rollover is unchanged (carryover 4). | Measured on this host on 2026-10-10: a child launched by this design owner, itself the child of an orchestrated issue owner, had no subagent-launch tool, while this owner had one; so launch ends at depth 3. The direct route's ship owner is at depth 2, the same depth as the six working ship agents in the issue's table. | Routing the direct rollover back through its controller too: breaks `rollover.md`'s validate-relay-stop contract and its tests to fix a route that works. |
| D5 | `workflow-state.py` is not changed; tests prove the existing ledger admits the sequence (carryover 5). | `progress` only records `delegate`; `register-worker` needs a current launch and nothing else; `fence_owner_exit` already refuses `finish` under a live worker. | A ledger field marking the attempt as delegated or the worker as ship owner: no reader exists for it (YAGNI), and the file is a declared risk path. |
| D6 | A closed prompt line selects the delegated route, and a delegated owner treats `delegate` as `continue`. | The delegated owner's envelope is identical to a dispatcher's (`acquire-dispatcher.md`), so nothing else tells the two apart; closed byte-matched lines are the precedent in `rollover.md` and `ship-handoff.md`. A second delegation would put sdd's agents at depth 4. | Inferring delegation from a resume pack or the recorded phase: both also occur on a dispatcher relaunch. |
| D7 | The change fits the existing instruction ceilings by cutting named unpinned sentences; no file is added and no ceiling raised. | Only the user applies `instruction-budget-raise`; the gate refuses any model change beyond a lowered ceiling or a note; a new skill file would need a model entry. | A new `delegate.md` read on demand: needs the label. |
| D8 | Criterion 3 is verified by contract tests on machine-consumed strings plus three plan-only evals, not a pipeline eval. | `agent-helpers.md` rule 6 forbids new English-phrase pins; the eval fixture's tracker kind is `none`, so a ledger-backed pipeline run stops at acquisition (the note on eval 2). | A pipeline eval of a delegated run: cannot reach Phase 6 on the fixture. |
| D9 | Amends D7's cut list after a prototype against the live gates: the Phase-7 rationale cut is mirrored in `model-matrix.json`'s `call` string, tiers untouched (reverses that file's entry under Unchanged); the `AUTO.md` cut keeps one clause naming `REVIEW-CONTRACT.md`; `ship-handoff.md` also loses its "Loaded from" line; `acquire-dispatcher.md` is not edited. | Measured at b6776289: the matrix mirrors the whole `Agent(...)` line; instruction-load validation requires the planning owner's prompt to name each of its members; with these the gate passes, the tightest ceiling (implementation owner, hot) keeping 11 bytes. | Keeping the rationale and finding 151 bytes elsewhere: the remaining candidates are pinned or load-bearing. Naming `REVIEW-CONTRACT.md` in the plan-subagent paragraph instead: edits Phase 2–4 text outside scope. |
| D10 | The skill text is compressed to fit: `SKILL.md` gives the delegated returns as three ordered alternatives (the two closed lines and the `finish` reply share one outcome) and says "this owner's identity" without the field list; `delegated-owner.md`'s section cites `SKILL.md` and Phase 7, not sibling files; the field list and the depth rationale go to the README. The orchestrated owner profile's `unread` reason for `delegated-owner.md` stays as written. | skill-lint L4b forbids a reference file naming a sibling reference file; the README is outside the gate's corpus; the gate freezes `unread` reasons without the label, and that profile still never reads the file. | Four cases with the field list in `SKILL.md`: over the implementation-owner and corpus ceilings. |
| D11 | Seam 1's ledger tests are characterization tests with no red step; each new eval is graded by a fresh subagent when the grading agent has a launch tool, inline otherwise, and the acceptance record says which. | D5: no helper changes, so nothing turns red first. An sdd implementer below a delegated owner may have no launch tool. | Mutating `workflow-state.py` to stage a red step: edits a risk path for ceremony. |
| D12 | The ledger test for finish after a delegated return drives `finish --summary-file` with a valid `ship-summary/v2` and keeps the installed contract. | Plan review PR-001: `--result-file` reaches a different implementation than the one a contracted owner runs, so it proves nothing about the production fence. | Keeping the legacy transport because an existing test uses it: that test covers a contractless issue. |
