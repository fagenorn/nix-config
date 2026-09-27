# Ship reviewer dispatch at any nesting depth, issue 198

Issue: https://github.com/fagenorn/nix-config/issues/198

## Problem

A `from-issue --auto` run that reaches Phase 7 with finished, reviewed work can
still end `terminal_failed` (`owner_reported_failure`) because the ship owner it
launches cannot dispatch ship-issue's Phase-5 reviewers. The ship owner learns
this only at ship-Phase 5. By then it has already merged the integration branch
into the feature branch (ship-Phase 1), and on many runs it has also pushed,
opened the PR and checkpointed. It reports a generic stop, and the from-issue
owner records a terminal verdict that spends the attempt. Nothing about the work
was wrong. The context it ran in was.

Two runs hit it. On #148 (launch `148:1:1`) the ship owner stopped after a local
sync merge with nothing pushed. On #155 (launch `155:1:5`) all eight plan tasks
had passed review and `just build` plus both suites were green, but the ship
owner found no `Agent` tool ("ToolSearch select:Agent: none"). The attempt ended
`terminal_failed`, and the work sits unpushed.

The user wants three things. First, the flow finds out where reviewer dispatch
will run before it commits to anything. Second, Phase 7 still completes when a
nested ship owner cannot dispatch. Third, a genuinely missing dispatch
capability is a distinct outcome that can be resumed and does not spend the
attempt.

### Host evidence: this corrects the issue's diagnosis

The issue says a subagent's child gets no `Agent` tool. The host does not behave
that way. The orchestrator measured it on Claude Code 2.1.280 with a chain of
`general-purpose` subagents, each asked to launch the next:

| Depth (root session = 0) | `Agent` in the tool surface | Observed |
|---|---|---|
| 1 | yes | launched depth 2 |
| 2 | yes | launched depth 3 |
| 3 | **no** | its launch failed: "Agent tool not available in tool list" |

A subagent's child (depth 2) can dispatch. A subagent's grandchild (depth 3)
cannot. Reviewers are leaves and need no `Agent` of their own, but the ship
owner does. **A nested ship owner therefore works exactly when the from-issue
owner is at depth 0 or 1, and fails when the owner is at depth 2.** Both
failures fit that rule:

- **#155, a background direct controller.** `/from-issue N --auto` was itself
  dispatched as a background agent (depth 1). Its mandatory Phase-5 rollover
  owner ran at depth 2, so the ship owner ran at depth 3.
- **#148, most plausibly an orchestrated owner that delegated.** An
  orchestrated owner runs at depth 1. If it took a generic phase-gate
  `delegate`, the fresh owner ran at depth 2 and the ship owner at depth 3.
  The second launch on #148 merged after a review.

Most orchestrated ship owners run at depth 2 and do dispatch reviewers. #149's
two-axis review is an example. An owner cannot tell depth 1 from depth 2 by
looking at its own tool surface, because both have `Agent`. So the route cannot
be chosen from how the owner was launched. A probe has to decide it, at the
place where the dispatch will happen (D1). For run 2 the orchestrator re-ran the
probe on this host: depth 1 and depth 2 both still list `Agent`.

## Solution

There are three pieces, and each one follows an existing pattern.

1. **ship-issue probes before it changes anything.** The first step of
   ship-Phase 0 checks that the current context can launch subagents. That
   check comes before the Delivery loop's synchronizing checkpoint, before the
   Phase-1 sync, and before every other write. If the check fails, a handoff
   invocation returns exactly one closed line, `capability_gap: agent_dispatch`,
   and nothing has been launched or written (D3, D4).
2. **from-issue falls back to inline shipping.** The Phase-7 owner keeps
   launching the fresh ship owner as the default, since that works whenever the
   owner is at depth 0 or 1. The owner falls back when the ship owner returns
   the gap line, or when the owner cannot make the launch at all because it has
   no launch tool. It re-checks its launch with `check-launch` and then runs
   `ship-issue` inline through its own `Skill` tool. An owner that just
   launched a ship owner has `Agent` by definition, so the inline run can
   dispatch the reviewers, which run at the owner's depth + 1 as leaves (D2,
   D5).
3. **A real gap suspends instead of finishing.** The inline run can return the
   gap line too. That happens only when the owner itself has no launch tool. The
   owner then suspends the attempt on a new owner-reportable cause,
   `blocked_on=agent_dispatch`, and prints the canonical suspension line. Like
   every suspension, this spends no attempt. Only a human-directed re-entry
   resumes it. That is `/from-issue N --auto`, or an orchestrate run that names
   the issue. Both normally relaunch from the root session, which is shallow
   enough to dispatch (D6).

What each owner depth sees after the change:

| from-issue owner depth | Ship owner depth | Today | After |
|---|---|---|---|
| 0: interactive or top-level direct | 1 | ships | unchanged |
| 1: orchestrated owner, or the rollover owner of a top-level direct run | 2 | ships | unchanged; the probe passes |
| 2: rollover owner of a background direct run, or an orchestrated owner's delegate | 3 | fails at ship-Phase 5 after changes, `terminal_failed` | the ship owner returns the gap line from Phase 0 with nothing changed; the owner ships inline, and its reviewers run at depth 3 as leaves |
| 3: only reachable through a chain of delegations | no launch possible | launch failure, terminal | the inline run's probe finds the gap; the owner suspends `agent_dispatch` |

## Decisions

### The reviewer-dispatch probe (ship-issue, Phase 0)

- **Placement.** The probe is the first step of ship-Phase 0. Entry validation
  runs before it: the handoff boundary and the independent artifact checks,
  both read-only. Phase 0's four existing checks run after it. So do the
  Delivery loop's synchronizing null-scope checkpoint, the Phase-1 sync, and
  every forge, ledger or git write. Phase 0 says in so many words that the
  probe precedes the synchronizing checkpoint, because that checkpoint is a
  ledger write whose timing the loop itself does not pin down (D3).
- **What it checks.** It checks that the tool which carries out this skill's
  `Agent(...)` dispatch sites is in the tool surface. On a host that defers
  tool schemas, the probe also accepts the case where the tool search (Claude
  Code: `ToolSearch` `select:Agent`) returns that tool's schema. The check is
  about a capability and never tests for a host by name (D13). The probe
  launches nothing, writes nothing, and makes no trial dispatch. It proves the
  tool is present. It does not prove that a later launch will succeed. A
  Phase-5 launch that fails after a passing probe keeps today's failure
  handling (D12).
- **When it runs.** It runs in every review-bearing invocation: a v2 or legacy
  handoff, or a standalone `/ship-issue <num>`. It still runs when the merge
  delta would turn out empty and no reviewer would be needed, because the
  delta's size is not known until after the sync the probe has to precede.
  Remainder mode skips Phases 0–5, dispatches no reviewer, and is exempt.
- **Against the correctness route (#195).** Since this spec was approved,
  ship-Phase 5 picks the correctness axis's route from `capabilities.review.code`
  before either axis is dispatched: `blocked` stops, `available` with
  `codex-collaboration` reaches Codex through a command, and otherwise the
  native reviewer runs. The conformance axis and the merge-delta reviewer are
  native dispatches on every route, so any review that runs still needs the
  launch tool. The probe reads no capability state and stays unconditional, and
  a `blocked` capability keeps its own Phase-5 stop (D17).
- **One home.** The probe is defined only in ship-issue's Phase 0. REVIEW.md,
  the ship-handoff prompt and from-issue all point to it and do not restate it
  (D9).

### The capability-gap line

- **Shape.** When the probe fails in a handoff invocation, ship-issue's whole
  return is exactly this line, and nothing else:

  ```text
  capability_gap: agent_dispatch
  ```

  The line is closed and has no placeholders. The receiver compares it byte for
  byte, never decodes it, and runs it past no validator. It is the same kind of
  exception as the existing return that is only the re-entry line. The line
  reuses the `blocked_on` token its genuine case suspends on, so one name
  covers both (D4).
- **Standalone.** In a standalone interactive `/ship-issue`, ship-issue tells
  the user that the probe found no subagent-launch tool, ends with the same
  line, and stops. It keeps the worktree and writes nothing.
- **Meaning.** The line says that this context cannot launch ship-issue's
  reviewers and that nothing was launched or written. It carries no delivery
  state, because none was created.

### from-issue Phase 7: fallback to inline ship-issue

The `from-issue-ship-owner` dispatch marker and its `Agent(...)` line stay
byte-identical, because the model matrix pins that line verbatim. The one
exception to "not inline via `Skill`" goes in a paragraph after it. The ordered
report handling becomes:

1. **Exact lines first.** If the report is only the re-entry line
   `/from-issue <num> --auto`, relay it and write nothing (unchanged). If it is
   only `capability_gap: agent_dispatch`, take the fallback below. A
   `from-issue-ship-owner` launch that cannot be made, because this context has
   no subagent-launch tool, counts as that same line. The inline run's probe
   then settles the question. If the tool was only deferred, the probe finds it
   and the inline run dispatches as normal.
2. **Then JSON (unchanged).** A validated `delivery_stalled` reply is relayed
   and nothing is written. Otherwise the report goes through ship-summary
   validation, then the `check-launch` fence, then `workflow-state finish`.

**The fallback (D5).** With lifecycle identity, the owner first runs
`check-launch` with its own `action_id`, the same fence the terminal write uses.
If the answer is `current: false`, or the helper fails, the owner writes nothing,
prints the canonical re-entry line `/from-issue <num> --auto` on its own line,
and stops. Ledger-free, there is no launch identity to check, so the owner
skips this fence. Otherwise it invokes `ship-issue` through its own `Skill` tool
with the same validated handoff bytes. It carries out the ship-owner prompt's task
list itself: every phase, the auto-mode rules, and the Delivery loop, writing
only `checkpoint-delivery` and never `finish`. Nothing was changed, so the
handoff is still accurate. ship-issue re-validates it on entry in any case. The
inline run's return goes back into the report handling above. The re-entry
line, a `delivery_stalled` reply and a `ship-summary/v2` are all handled exactly
as they are for a nested ship owner. So is HUMAN-GATE's case of an owner
running the gate itself, which suspends `human_gate` directly. There is one
exception. A gap line that comes back from the inline run is the genuine gap
(next section) and never triggers a second inline run.

**Scope of the fallback.** The fallback covers the review-bearing ship launch
only. A `delivery_remainder` launch uses remainder mode, which never probes and
never returns the gap line, so it stays unchanged (D12).

**Against a Phase-6 `delegate`.** On the mandatory direct rollover, a Phase-6
`delegate` is "fulfilled by the existing fresh Phase-7 ship owner". The inline
fallback is the one allowed departure from it. The fresh-context route cannot
dispatch at that depth, and failing costs more than a larger context. The
Phase-7 progress gate and the ledger-only finish bookkeeper that follow are
unchanged. The bookkeeper needs no `Agent`, so it works at any depth.

### The genuine gap: an `agent_dispatch` suspension

- **When it happens.** The inline run returns the gap line. That is possible
  only when the owner itself cannot launch agents.
- **With lifecycle identity**, the owner follows from-issue's existing
  suspension procedure with `<value>` = `agent_dispatch`. It calls
  `workflow-state suspend … --blocked-on agent_dispatch`, prints
  `Suspended (blocked_on=agent_dispatch). Resume: <reentry from the envelope>`
  as its last output, and makes no `finish` call. The procedure's list of
  owner causes gains `agent_dispatch`, and its opening list of interruptions
  gains "a context that cannot launch the agents a phase needs".
  **Ledger-free**, the owner reports the gap to the user and stops, keeping the
  worktree.
- **workflow-state.** `agent_dispatch` joins `BLOCKED_ON_VALUES`. It therefore
  also joins `OWNER_BLOCKED_ON_VALUES`, which is derived from it, and the
  `suspend --blocked-on` choices, which are derived from that. It does not join
  `AUTO_RESUMABLE_BLOCKED_ON` (D6). The anti-zombie `STALL_LIMIT` applies
  unchanged: a fourth consecutive suspension at the same phase still becomes
  `stopped(stalled)`. A comment beside the constants records what the value
  means, following the `host_capacity` comment.
- **Resuming.** A suspension is not a terminal, so re-entry resumes the same
  attempt in place, on the same worktree, with a fresh budget window. The
  existing `human_directed` rule decides who may resume it. A direct owner
  always carries that flag, and an orchestrate run carries it when the caller
  listed the issue numbers. A `--label` or `--milestone` sweep carries it for
  no issue, so it leaves the attempt parked and reports it, the way it treats
  `human_gate` and `external`.
- **Unchanged neighbours (D7).** Several nearby sets and derivations need no
  change:
  - The delivery-remainder blocker set and the checkpoint-response blocker set
    hold blockers the reducer and the remainder write, never an attempt
    `suspend` cause.
  - A control summary's `blocked_on` is an open string.
  - The admission settle derivation already maps every suspension other than
    `host_capacity` to `suspended`, which releases the claim.
  - No schema-version bump is needed. The new member only adds to the enum, and
    no existing ledger holds a value it would now refuse.
- **HUMAN-GATE.md is unchanged (D8).** Its sentence "This file defines no new
  suspension shape and no new `blocked_on` value" is about that file, and it
  stays true. `agent_dispatch` is defined in from-issue's suspension procedure
  and in workflow-state, not in the human gate.
- **The #117 core vocabulary (D18).** The #117 decision record, merged after
  this spec's approval, promotes the attempt suspension taxonomy to the
  transaction core and lists its blocked-on set without `agent_dispatch` (#117
  D4, D10). The new value fits that taxonomy's existing policy with no new rule:
  an owner supplies it, only a human-directed re-entry resumes it (like
  `human_gate` and `external`), it adds no terminal, and it keeps the stall
  bound. Detecting the gap stays with the skill, as host capabilities do in
  #117's adapter column. Until #125's cutover the shipped engine is the
  implementation, so this issue changes only workflow-state and leaves #117's
  record alone; that record reaches this branch only through ship-Phase 1's
  sync. #125 carries the value when it ports the taxonomy (Out of scope).

### Relays and reports

- **AUTO.md, earlier controller stop (D10).** Today, after delegating, the
  earlier direct controller validates what it receives as a workflow response.
  A delegated owner that suspended returns a suspension line instead, and the
  controller would mistake that line for a dispatch failure and try to write a
  terminal the helper refuses. The same happens with the re-entry line, for a
  superseded launch or a checkpointed denial. The stop therefore gains two
  closed line exceptions. Each is relayed unchanged, with no validation, and
  nothing is written:
  - a return that is only the canonical re-entry line `/from-issue <num> --auto`;
  - a return that is only a canonical
    `Suspended (blocked_on=<value>). Resume: /from-issue <num> --auto` line.

  The prohibitions stay as they are, including the one against calling
  `finish` after delegation.
- **AUTO.md, fresh delegated owner.** The sentence saying the Phase-6
  `delegate` is fulfilled by the existing fresh Phase-7 ship owner stays,
  unchanged and in its pinned order. A clause after it names from-issue's
  Phase-7 inline fallback. "After validating the ship owner's
  `ship-summary/v2` bytes" becomes "the ship report's", so that it also covers
  the summary an inline run produces. The section still spells no
  `workflow-state suspend`. It points to SKILL.md's suspension procedure
  instead.
- **orchestrate-issues, final report.** The per-issue re-entry line
  `/from-issue <issue> --auto` is today prescribed "for an issue suspended on a
  human gate". It will instead be prescribed for an issue suspended on a cause
  that a label sweep does not resume: `human_gate`, `external` or
  `agent_dispatch`. For such an issue, re-invoking the label sweep would leave
  it parked, so the per-issue line is the correct instruction.

### Prose corrections (D9)

- **ship-handoff prompt.** Task item 2 drops the claim "Nested Agent calls are
  supported." and says instead that ship-issue's Phase-0 probe first confirms
  that this context can launch the reviewers. The return contract gains a
  third exception, placed before the two that end the loop: when the probe
  reports the gap, return only `capability_gap: agent_dispatch`. The
  prompt remains the file's only unlabeled fence, and each of the two
  leaf-agent sentences still appears in it exactly once.
- **REVIEW.md.** The merge-delta paragraph's aside ("nested dispatch works even
  inside an `Agent` subagent; if `Agent` isn't in your tool surface, `ToolSearch`
  `select:Agent` first") becomes a pointer to the Phase-0 probe. That aside is
  false at depth 3, and its `ToolSearch` hint now lives in the probe.
- **from-issue Phase 7.** The paragraph after the untouched dispatch line
  names the fallback as the one exception to shipping through a fresh owner.

### What does not change

- The rest of ship-issue's phases and the Delivery loop are unchanged. That
  covers the launch guard, the gates, the reviewer tiers and every dispatch
  site.
- The model matrix gains no dispatch site. The inline fallback is a `Skill`
  invocation, so the shipping traces still show `from-issue-ship-owner` before
  ship-issue's review dispatches.
- The host declaration, `workflow-state control` actions, the validators, and
  the `ship-summary/v2` and `ship-handoff/v2` shapes are unchanged.

## Test seams

The existing seams are reused and no new one is introduced (D11).

**S1: the `workflow-state` CLI, driven from source** (`test_workflow_state.py`,
using its existing `suspend`, `control` and direct-owner helpers):

| Test | Asserts | Prior art |
|---|---|---|
| T1 | `suspend --blocked-on agent_dispatch` on an active attempt returns `kind: suspended`, `blocked_on: agent_dispatch`, `stalled_resumes: 0` and the re-entry line. The ledger attempt is `suspended` with no result, finish time or result source, and the attempt count is unchanged | `test_suspend_subcommand_records_blocked_on_and_reentry` |
| T2 | A `control` sweep with `human_directed: false` over that attempt emits no `resume`. Its summary is `suspended` / `agent_dispatch`, the last action is `finalize`, and the ledger bytes are unchanged | `test_human_gate_suspension_is_not_auto_resumed` |
| T3 | A human-directed re-entry (`direct-owner` acquisition) resumes the same attempt in place, clears `blocked_on`, and opens no second attempt | the direct-owner suspended-resume tests |

The existing refusal of the reserved causes (`unknown`, `host_capacity`) stays
green. `agent_dispatch` joins the owner set without admitting a reserved cause.

**S2: the prose-contract suite** (`test_workflow_skill_contracts.py`):

- ship-issue Phase 0 names the probe as its first step, ahead of the existing
  worktree check, and says that the probe precedes the Delivery loop's
  synchronizing checkpoint and the Phase-1 sync.
- ship-issue, ship-handoff and from-issue all spell
  `capability_gap: agent_dispatch` identically.
- In from-issue Phase 7, these appear in order: "receiving the ship report", the
  re-entry-line case, the gap line, `check-launch`, the `Skill` fallback, and
  `agent_dispatch`. The existing orders ("receiving the ship report" →
  `check-launch` → `workflow-state finish`) and existing phrases stay pinned.
- from-issue's suspension procedure lists `agent_dispatch`.
- The ship-handoff prompt no longer contains "Nested Agent calls are
  supported.", and REVIEW.md no longer contains "nested dispatch works even
  inside".
- In AUTO.md the "fresh Phase-7 ship owner" order holds, and the fallback is
  named after it. The fresh-delegated-owner section still has no
  `workflow-state suspend`. The earlier controller stop carries both line
  exceptions and keeps its validate → relay → stop order.
- The orchestrate report names `agent_dispatch` for the per-issue re-entry
  line.
- The HUMAN-GATE pins are unchanged.

**Unchanged and required green:** `test_dispatch_contracts.py` (ship-handoff
keeps one unlabeled fence with both clauses once) and `test_agent_model_matrix.py`
(the `from-issue-ship-owner` call line is byte-identical, and the shipping-trace
order holds). The verification commands are `just build` and
`just agent-workflow-tests`.

## Run-2 delivery

Run 1 (`direct-198-000001`) selected `765f598` as its reviewed output. Then
`origin/main` advanced to `6ab576e` with #195 and #117, and that head now
conflicts with main in one file, `home/common/agent-skills/instruction-load.json`.
The delivery model has no reselection path, so run 1's merge was refused as
`merge_conflict`. With the user's authorization, run 2 (`direct-198-000002`)
discards run 1's delivery and re-enters ship-issue on this design: ship-Phase 1
syncs main, Phase 5 reviews again, and the Delivery loop selects a fresh head
(D16).

The re-grill against `6ab576e` amends no D1–D15 decision; it adds D17 and D18
above. A trial `git merge-tree` of the two heads merges every other file
cleanly. On that merged tree the prose-contract, dispatch-contract,
model-matrix, shell-example and workflow-state suites all pass, so S1 and S2
hold after the sync.

**The ceilings conflict (D19).** #195 and #198 both raised the same three
profiles, `orchestrated-issue-owner`, `implementation-owner` and `ship-owner`,
and each appended a note clause. Neither side's ceilings hold on the merged
tree: the trial measured 151023, 142148 and 55347 hot bytes, above ours
(149820, 140866, 54302) and theirs (147826, 138951, 53916). The sync therefore
resolves the file by re-measuring, not by taking a side. Each conflicted
ceiling becomes its merged measurement. Each note keeps #195's clause, then
#198's, and records the re-measurement against the merged main commit. #198's
`conditional` ship-issue members stay. #155's instruction-load report is not
regenerated.

**Phase 6 (D20).** Run 2 re-executes no task, but `sdd` skips only the tasks its
ledger marks complete, and this checkout's `sdd` workspace is empty. Before
invoking `sdd`, the Phase-6 owner therefore recovers that ledger from `git log`
under sdd's own recovery rule. It writes `progress.md` in the workspace that
`sdd-workspace` prints for the plan, with the identity line and `Task 1:
complete` through `Task 4: complete` naming `37b829a`, `880e370`, `6674a5a` and
`6859d0e`. `sdd` then resumes past Task 4, so only its cumulative delivery gate
and final review run, and they produce Phase 7's `review_state` and
`report_path`.

**The open PR (D21).** PR #201 is this issue's own run-1 PR: head
`worktree-issue-198-nested-ship-owner`, base `main`, body `Closes #198`. Run 2
adopts it rather than opening another. ship-Phase 0's check 4 accepts it as this
delivery's own PR, not a competing one. Phase 4 pushes the synced head with
`git push origin <branch>` and runs no `gh pr create`. After the fresh review the
ship owner refreshes #201's review section with `gh pr edit`. The selection
gate's `pr_opened` observation names #201 at the selected head. The Phase-7
handoff's `notes` cite D19 and D21, so the ship owner applies both without
rediscovering them.

## Out of scope

- **Depth-aware dispatch in Phases 2–6.** A design, plan-review, sdd or
  mechanical dispatch from an owner at depth 3 gets no designed route: nothing
  probes for the gap there or recovers from it. Neither does the Phase-5
  rollover launch of a direct controller that is itself at depth 2. The
  suspension procedure's generic cause still lets such an owner suspend on
  `agent_dispatch` instead of failing (D22). This is a named follow-up issue:
  "phase dispatch from a depth-3 owner". It is not designed here.
  `agent_dispatch` is the value it would most likely reuse.
- **The remainder launch at depth 3.** A from-issue invocation with no launch
  tool cannot launch a remainder owner. Remainder mode needs no reviewers, so
  it could run inline, but that would move the remainder's own `finish` into a
  different context. It belongs with the follow-up above.
- **A dispatcher-launched ship owner.** Handing the ship owner back to
  orchestrate-issues, or to the root session, to launch at first level would
  need a new `control` action kind (D2).
- **Host changes**, and any attempt to measure or report agent depth.
- **Host-declaration schema changes**, and reporting the gap through the
  conformance engine.
- **HUMAN-GATE's `stopped` return from a fresh ship owner.** The grill found a
  gap here: HUMAN-GATE says that the parent suspends `human_gate`, but from-issue
  Phase 7 has no rule that recognizes that summary, and its "Phase-7
  stopped/failed report" rule would write it as a terminal instead. That return
  is a free-text `stopped` row, which is the shape D4 rejects. It is a named
  follow-up and is left unchanged here (D13).
- **Retrying a Phase-5 launch failure after a passing probe.** Today's failure
  handling stays (D12).
- **Carrying `agent_dispatch` into the core.** #125 ports the promoted
  suspension taxonomy and must include this value. Otherwise its migration,
  which refuses unexpected state, would refuse a ledger holding a suspended
  `agent_dispatch` attempt. Amending #117's record belongs to that port (D18).
- **`just switch`**, and refreshing the installed skill copies. They follow the
  normal rebuild.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The design rests on the measured host rule: depth 1 and depth 2 have `Agent`, depth 3 does not. That corrects the issue's claim that a subagent's child has no `Agent`. The failure needs a from-issue owner at depth 2, and the route is decided by a probe where the dispatch happens, not by the acquisition route | Orchestrator probe on Claude Code 2.1.280; #155 ledger (`155:1:5`, "ToolSearch select:Agent: none"); #149's depth-2 two-axis review; the-bar *Root causes* | Route by acquisition mode (for example "orchestrated → inline"): depth 1 and depth 2 owners look identical from inside, and most orchestrated ship owners dispatch fine |
| D2 | Keep the nested fresh ship owner as the default. When it reports the gap, the from-issue owner runs `ship-issue` inline through `Skill` with the same validated handoff | Issue Expected, option 1; from-issue Phase 7's fresh-context rationale; the owner provably has `Agent` because it just launched the ship owner | (b) Always inline when the owner is a subagent: every orchestrated owner would lose the fresh context on the common path. (c) A dispatcher-launched ship owner: needs a new `control` action kind, which is out of scope |
| D3 | The probe is ship-Phase 0's first step, before the synchronizing checkpoint, the Phase-1 sync and every write. It checks for the dispatch tool: present in the surface, or its schema returned by the tool search. It launches and writes nothing. It is unconditional in review-bearing flows, and remainder mode is exempt | Issue Expected ("before any sync or checkpoint"); ship-issue Phase 0 is read-only; every non-empty review path needs at least one `Agent` (conformance axis, merge-delta, native fallback, reviewer-lite) | Probe at Phase 5 after sizing: the sync, push, PR and checkpoint have already happened, which is the reported failure. A trial launch: it spends a subagent and is itself a launch |
| D4 | The gap is reported as one closed line, `capability_gap: agent_dispatch`, as the whole return. It is matched byte for byte, never decoded, and has no validator. It reuses the suspension token | The existing re-entry-line exception in ship-handoff and from-issue; the-bar *YAGNI* and *Token economy* | A new validated JSON boundary: validator machinery for a one-bit signal. A `stopped` ship summary with a reason: the Phase-7 handler writes it as a terminal verdict, which spends the attempt, and the reason sits in free-text notes |
| D5 | Phase-7 handling checks the exact lines first (re-entry line, then gap line), then JSON. A launch that cannot be made counts as the gap line. The fallback first runs `check-launch` with the owner's own `action_id`. The inline run's return re-enters the same handling, and a second gap line never triggers another inline run. The fallback is the one allowed departure from a rollover Phase-6 `delegate` | from-issue Phase 7's shared-launch-identity fence; HUMAN-GATE's "owner running this path itself" case; the-bar *Fail loud* | Falling back without the fence: a superseded launch would sync-merge in the shared worktree. Suspending directly on a launch that cannot be made: it would restate the probe outside its one home |
| D6 | New owner-reportable cause `agent_dispatch`, added to `BLOCKED_ON_VALUES` (and so to the owner set and the `suspend` choices) but not auto-resumable. Only a human-directed re-entry clears it. `STALL_LIMIT` applies unchanged | Issue Acceptance (distinct and resumable, and does not spend the attempt); the `human_directed` rule; the #133 suspension model; the `host_capacity` precedent for an added value | Auto-resumable: the ledger cannot see how deep the relaunch will be, and a blind resume can use up `STALL_LIMIT` into a `stopped(stalled)` terminal, which is the attempt-ending outcome the issue forbids. Reusing `external` or `human_gate`: the issue demands a distinct outcome, and no authority is missing |
| D7 | Only workflow-state's attempt-cause set changes. The remainder and checkpoint-response blocker sets, control summaries and the settle derivation stay as they are, and there is no schema bump | Code reading: those sets hold reducer or remainder blockers only; summaries are open strings; settle maps any non-`host_capacity` suspension to `suspended`; agent-helpers.md allows an in-place edit to a legacy script | Adding the value to every blocker set: it would admit a cause nothing writes there, and no test could fail for it |
| D8 | HUMAN-GATE.md stays unchanged. Its "no new `blocked_on` value" sentence is about that file and remains true, and the inline fallback composes with its owner-runs-the-gate case | The HUMAN-GATE text and its ordered pin | Rewording it: churns a pinned sentence with no change in behaviour |
| D9 | The probe has one home, ship-issue Phase 0. ship-handoff's "Nested Agent calls are supported." and REVIEW.md's nested-dispatch aside become pointers to it. The `from-issue-ship-owner` call line stays byte-identical, with the exception in a paragraph after it | the-bar *DRY* and *Truthful terminal states*; model-matrix.json pins the call line verbatim; test_dispatch_contracts requires exactly one unlabeled fence | Rewording the call line: breaks the matrix pin for no gain. Keeping the claims: they are false at depth 3 and caused #155's surprise |
| D10 | AUTO.md's earlier controller relays a return that is only the re-entry line, or only a canonical suspension line, unchanged and writing nothing. The orchestrate final report prescribes the per-issue re-entry line for `human_gate`, `external` and `agent_dispatch` | the-bar *Truthful terminal states*: the new outcome has to reach the caller as a suspension, not as a refused terminal write; label sweeps do not resume these causes | Leaving the relays alone: a delegated owner's suspension would surface as a failed dispatch and a refused `finish`, and a label-sweep report would name a re-invocation that cannot resume the issue |
| D11 | Test seams are S1 (the workflow-state CLI) and S2 (the prose-contract suite) only. The model-matrix and dispatch-contract suites stay unchanged and green | #150 and #190 test-seam precedent; the-bar *Tests that can fail* | A harness test that simulates host depth: no seam exposes host tool surfaces, and it would pin a model of the host rather than the contract |
| D12 | Out of scope: dispatch in Phases 2–6 from a depth-3 owner, and the remainder launch at depth 3 (one named follow-up); a dispatcher-launched ship owner; retrying a Phase-5 launch failure after a passing probe | Phase-0 scope boundary; the-bar *YAGNI*; the issue is scoped to reviewer dispatch | Folding the follow-up in: it touches sdd and every phase dispatch site, which is several subsystems |
| D13 | Grill: the probe's check is about the dispatch capability and never tests for a host by name, so on a host without a tool search, presence in the tool surface is the whole check. The HUMAN-GATE fresh-ship-owner `stopped` return, which from-issue Phase 7 has no rule for, is recorded as a follow-up and not fixed here | The #119 codex-ship-handoff decision ("never a host name test"); from-issue Phase 7's "Phase-7 stopped/failed report" rule set against HUMAN-GATE's parent-suspends sentence; the-bar *YAGNI* | Converting the human-gate return to a closed line in this issue: it changes a second ship exit that was never part of #198's acceptance, and needs a Codex-host trace to verify |
| D14 | Plan: the Phase-7 route is named the **dispatch-gap fallback** in from-issue Phase 7 and AUTO.md. Every sentence that calls the Phase-7 summary "the ship owner's" says "the ship report's" (or "the validated ship summary") instead: AUTO.md's three, and the terminal return procedure's one | ship-handoff.md's `## Inline fallback (no ship-issue skill)` and SKILL.md's missing-sibling "ship per the Phase-7 fallback" already own "inline fallback"; the spec's own AUTO.md rename rationale ("so that it also covers the summary an inline run produces"); the-bar *Truthful terminal states* | "Inline fallback" or "Phase-7 inline fallback", as this spec's prose says: those phrases already name the missing-skill route in the same two files, so an owner could run the wrong route. Renaming only the one AUTO.md sentence the spec names: leaves three sentences that are false after an inline run |
| D15 | Phase 5: D14's route-neutral wording also covers from-issue Phase 7's re-entry clause ("ship-issue run checkpointed a denial") and the rollover Phase-6 gate sentence, which names the dispatch-gap fallback beside the fresh ship owner; T2 also pins that the directed sweep keeps attempt 1 | Plan review SF-1 and DI-1 (Claude fallback): those two sentences would contradict the fallback paragraph; AC2 "does not consume the attempt" and the-bar's tests that can fail | Leave both sentences as they are and check only the attempt state: the prose would describe one route while the file allows two, and the orchestrated resume path would go unpinned on the attempt count |
| D16 | Run 2 (`direct-198-000002`) discards run 1's delivery of `765f598` and re-enters ship-issue on the unchanged D1–D15 design: ship-Phase 1 syncs `origin/main`, Phase 5 reviews again, and the Delivery loop selects a fresh head | The user's explicit authorization in this session to discard run 1's delivery and start a new run; run 1's merge refused as `merge_conflict` against `6ab576e`; the delivery model has no reselection path | Merging a conflict-resolved head outside the delivery loop: it would record a merge of a head other than the selected one. Redesigning from scratch: main's drift invalidates no D1–D15 decision |
| D17 | Grill (#195): the probe stays unconditional and reads no `review.code` state. The correctness axis may now reach Codex through a command, but the conformance axis and the merge-delta reviewer are native dispatches on every route; `blocked` keeps its own Phase-5 stop | ship-issue Phase 5 on `6ab576e` (correctness rung chosen before dispatch; the conformance and merge-delta dispatch sites unchanged); D3; the-bar *DRY* (the probe keeps one home) | Skip the probe when correctness routes to Codex: the conformance axis would still fail at Phase 5, after the sync. Order the probe after the `review.code` choice: that choice sits at Phase 5, after every write the probe must precede |
| D18 | Grill (#117): `agent_dispatch` joins the suspension taxonomy #117 promotes to the core as an owner-supplied, human-directed cause under its existing policy. This issue edits only workflow-state, leaves #117's record alone and names carrying the value as #125's follow-up | #117 record: its blocked-on set, "human-directed resume for other reasons", host capabilities in the adapter column, D4, D10 (#150 shipped `host_capacity` first; the record was amended at its own refresh) and D17; CLAUDE.md (the shipped engine governs until #125's cutover); #125's body; the-bar *Moves keep their history* | Editing #117's record here: it is not on this branch before ship-Phase 1's sync, and an accepted decision is amended by its own refresh. Silence: #125 would port a set without the value, and its migration would refuse such ledgers. Mapping the gap to `external`: loses the distinct outcome AC2 demands |
| D19 | Grill: the ship sync resolves `instruction-load.json` by re-measuring on the merged tree. Each conflicted ceiling becomes its merged measurement; each note keeps #195's clause, then #198's, plus a re-measurement clause; #198's `conditional` ship-issue members stay; #155's report is not regenerated | #155 D10 (a raised ceiling rewrites its note in the same commit) and D19 (a sync re-measures and resets to the merged values); the trial merge of `765f598` and `6ab576e`, where neither side's ceilings pass the live-tree test; #195 kept the earlier clauses and appended its own | Take ours or theirs (SYNC.md's A or T): both fail `test_the_live_tree_breaches_no_ceiling`. Keep one issue's clause: erases the other's reviewed explanation. Regenerate #155's report: it is #155's point-in-time record, and #195 left it as it was |
| D20 | Phase 5 (run 2): before `sdd`, the Phase-6 owner recovers the sdd ledger from `git log`. `progress.md` gets the plan identity line and `Task 1`–`Task 4: complete` at `37b829a`, `880e370`, `6674a5a` and `6859d0e`, so `sdd` resumes past Task 4 and runs only its cumulative gate and final review | Plan review B1 (Claude fallback): `sdd` skips only ledger-marked tasks, and this checkout's workspace is empty; sdd's "trust the ledger and `git log`… recover from `git log`"; the members' watch-it-fail steps no longer hold at HEAD | Re-execute the tasks: their red-state steps contradict HEAD, and following them would add duplicate test methods that shadow silently. Reuse run 1's SDD report: it reviewed a package without D16–D19, under a discarded delivery |
| D21 | Phase 5 (run 2): run 2 adopts open PR #201. ship-Phase 0 check 4 accepts it as this delivery's own PR; Phase 4 pushes with `git push origin <branch>` and skips `gh pr create`; the ship owner refreshes #201's review section with `gh pr edit`; `pr_opened` names #201 at the selected head. The Phase-7 handoff `notes` cite D19 and D21 | Plan review B2 and SF1 (Claude fallback; the unvalidated Codex pass raised the same PR gap); investigate.md's open-PR rule ("resume its worktree and shipping path; do not rebuild it"); run 1's resumed ship owner recorded `pr_opened` for #201; SYNC.md's auto-resolve allowlist omits `instruction-load.json` | Close #201 and let ship-Phase 4 open a fresh PR: an extra outward-facing effect that discards #201's history for no contract gain, since `open_pr` binds a PR number and head, not the run that opened it. Leave D19 to the ship owner's own grounding: SYNC's A and T choices both fail the live-tree test |
| D22 | Phase 5 (run 2): the suspension procedure keeps the generic cause "a context that cannot launch the agents a phase needs" as the Decisions section specifies. The Out-of-scope bullet now says Phases 2–6 get no designed route, which that cause does not contradict | Plan review DI1 (Claude fallback): the Decisions section requires that wording; a suspension is resumable and consumes no attempt (AC2) | Narrow the clause to Phase 7: a code change in run 2 for no behavioural gain, and a depth-3 owner in Phases 2–6 would fail where it could park |
