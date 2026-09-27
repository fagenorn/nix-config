# Issue 195: the correctness axis routes on `capabilities.review.code`

## Problem

A project can author code review as unsupported: its `ResolvedProject` has
`bindings.workflow.review.code: null` and `capabilities["review.code"].state:
"unsupported"`. nodocom is in that state today, pending its #126. An unsupported
capability has no command entry, so nothing on that project should ever reach
Codex. Yet ship-issue's Phase-5 full two-axis review still reached Codex for its
correctness axis. When the Codex quota ran out, the ship owner read the refusal
as a binding capacity rejection ("no retry and no native fallback; blocked
stops"), and the from-issue owner suspended on `usage_limit`. Every resume before
the quota reset would have parked at the same step. In run `orch-1649-1655`,
#1649 was held by hand for about 9½ hours. Earlier in the same run, #1646–#1648
fell back to the native reviewer after other Codex failures. The route taken
depended on how Codex failed, not on the capability.

The rules disagree in three places:

- ship-issue picks the correctness transport with the words "when that capability
  is unavailable". `unavailable` is not a capability state; the states are
  `available | unsupported | blocked`. The word dates from when it meant "the
  `codex-collaboration` skill is absent". On a Claude host that skill is always
  installed, so this sentence always sends the axis to `diff-review`.
- `codex-collaboration` says `unsupported` "takes that operation's documented
  native route", and `diff-review` says it "takes the documented native route and
  never dispatches". Neither document names that route. The skill has been
  invoked, has no command to dereference and is pointed at a route it does not
  own, so it improvises. An improvised Codex call comes from outside the
  `available` route, through a plugin bridge or a default, which the skill already
  forbids.
- The capacity rule is written without a route, both in `codex-collaboration` and
  in the configured-review paragraph that ship-issue and sdd share. So it bound a
  refusal from a call that should never have been made.

sdd's final review has the same defect. It keys its correctness axis on "When
the `codex-collaboration` skill is available … Unavailable → native", and it
carries the same capacity sentence word for word.

## Solution

The caller routes the correctness axis on the retained capability state before it
dispatches anything. Codex is reached from one place only, the `available` rung.
The capacity rule applies only on that rung. A Codex call that happens anyway
under `unsupported` is a routing error: its outcome is discarded and the
documented native route runs.

The routing ladder, the same for ship-issue and for sdd's final review (per D4,
D5):

1. `blocked` stops with its capability reason and repair ID, and neither axis is
   dispatched.
2. `available`, with `codex-collaboration` installed → its `diff-review`
   operation. This is the only rung that reaches Codex. A capacity rejection here
   stops with no retry and no native fallback. A completed non-capacity failure
   takes that skill's one native fallback, as today.
3. `unsupported`, or `available` without `codex-collaboration` installed (a
   native Codex session) → the caller's native first-pass correctness dispatch,
   directly. `codex-collaboration` is never invoked on this rung.

`codex-collaboration` also enforces its side as defense in depth (per D6). Under
`unsupported` it makes no Codex call and returns the operation to the calling
controller's native route. It never dereferences a command, calls a bridge or
applies the capacity rule there.

### Options considered

1. **Route on capability state at the caller, and scope the capacity rule
   (chosen).** This matches the plan-review ladder in from-issue's
   standards-review, which already routes on `capabilities.review.plan` before it
   invokes `codex-collaboration`. It is a prose-contract change plus tests, with
   no helper change.
2. **Fix `codex-collaboration` only.** The skill would run the native reviewer
   itself under `unsupported`. The caller would still pick a transport by skill
   presence, and the conformance/correctness dispatch pairing would move into the
   Codex bridge skill. That skill is Claude-only, so a Codex host would lose the
   route. Rejected.
3. **Treat any Codex refusal as a non-capacity failure.** A quota refusal would
   take the one-time native fallback. That route-around is what issue 100's D7
   forbids on the `available` route, because the configured command shares the
   local app-server daemon. It also leaves the route depending on the failure
   kind. Rejected.

## Decisions

### 1. ship-issue Phase 5, full two-axis review (per D4, D5)

The paragraph that joins the native conformance dispatch to the correctness
fallback dispatch becomes the three-rung ladder above. It opens by saying the
correctness route is chosen from retained `capabilities.review.code` before
either axis is dispatched, never from how a Codex call failed. The phrase "when
that capability is unavailable" is removed. `diff-review` appears as a dispatch
target only in the `available` rung. The `unsupported` rung ends at the existing
`ship-issue-full-correctness-fallback` marker, and its text names neither
`diff-review` nor `bindings.commands`. The `available` rung calls itself the only
rung that reaches Codex and the only one where a capacity rejection binds. It
points to REVIEW.md for the rule's terms and does not restate them (per D9).

The degraded path (the merge-delta check) is unchanged. Every agent-dispatch
marker and its call line stay byte for byte as they are, and so do their ids,
roles, models and efforts. Only the prose around them moves. The ids keep their
historical names: under `unsupported`, `ship-issue-full-correctness-fallback` is
the documented primary route, even though its id says "fallback" (per D8). The existing
sentence that records the correctness scope when the axis came through
`diff-review` stays.

### 2. Routing error (per D2, D8, D9)

A Codex call made under `unsupported`, whether through `codex-collaboration`, a
plugin bridge or anything else, is a routing error. The rule has two halves, and
each half is written once per document family.

The classification is "a routing error, never a capacity rejection". It sits
next to each capacity rule it scopes: the shared configured-review paragraph
(§3) and `codex-collaboration`'s capacity paragraph.

The action sits at each caller's dispatch site, right after the ladder: in
ship-issue's Phase 5 and in sdd's correctness bullet. The caller discards the
call's outcome, whether a verdict, a refusal or a failure; none of it is the
axis's verdict. It records the routing error beside the correctness verdict and
runs rung 3's native dispatch. It does not retry, stop or suspend. The record
goes where each caller already keeps correctness provenance: the PR body for
ship-issue, the SDD ledger for sdd. In sdd the axis identity is still `native`,
and the routing error is noted beside it, not added as a failure class. The
routing error is not reviewer identity, so ship-issue's "records no reviewer
identity" rule stands.

### 3. Capacity rule scoped to the `available` route (per D7)

ship-issue's REVIEW.md and sdd's final-review.md share the configured-review
paragraph, and the two copies stay identical. In it, the capacity sentence
becomes "`blocked` stops. On the `available` route, a capacity rejection has no
retry and no native fallback." `blocked` comes first so that it cannot be read
as limited to the `available` route. The paragraph then adds the classification
from §2. The existing "Authored unsupported or a completed non-capacity
runtime/output failure uses the existing single native fallback and records why"
stays.

In `codex-collaboration`'s direct-review section, the capacity paragraph gets the
same opening, "On the `available` route, a daemon, slot, or capacity rejection is
a binding capacity rejection …". It also gets the classification from §2.

### 4. `codex-collaboration` under `unsupported` (per D6)

The phase-entry selection sentence changes from "`unsupported` takes that
operation's documented native route" to "`unsupported` makes no Codex call and
returns the operation to its calling controller's documented native route". It
returns no result and no fallback verdict, so the caller's rung 3 always runs.
It still comes before the `bindings.commands[review_id]` dereference. The existing
ban on a default, a plugin bridge or a second resolver stays. DIFF-REVIEW's
size-pre-flight sentence gets the same clarification: an unsupported capability
never dispatches Codex, because the calling controller runs its own native
correctness route. The plan-review callers already route before they invoke the
skill, so for them this changes nothing.

### 5. sdd sibling (per D1, D4, D5)

sdd's final-review correctness-axis bullet adopts the ladder. Its rung 3 target
is the Opus/high native reviewer selected in `correctness-reviewer-prompt.md`,
whose `sdd-final-correctness-review` marker does not change. The sdd
agent-tiers bullet and the header of `correctness-reviewer-prompt.md` say the
same thing: the native form is dispatched when `capabilities.review.code` is
`unsupported` or `codex-collaboration` is not installed. When the capability is
`available` and the skill is installed, `diff-review` carries the prompt as its
rubric. sdd's closed reviewer-identity set (`Codex` | `native` | `fallback` +
failure class) and its scope sentences are kept.

### Acceptance criteria

- **AC1 (unsupported never reaches Codex):** ship-issue's Phase-5 correctness
  route names `capabilities.review.code`, then the rungs `blocked`, `available`
  and `unsupported` in that order. The `unsupported` rung reaches the
  `ship-issue-full-correctness-fallback` marker and contains neither `diff-review`
  nor `bindings.commands`. The phrase "when that capability is unavailable" is
  gone. `codex-collaboration`'s selection clause says `unsupported` "makes no
  Codex call", ahead of its `bindings.commands[review_id]` dereference. A test
  that checks these points fails when the pre-fix sentence is put back.
- **AC2 (available capacity still stops):** ship-issue's `available` rung names
  `diff-review` and then "capacity rejection". The shared configured-review
  paragraph (ship-issue REVIEW.md and sdd final-review.md) and
  `codex-collaboration`'s capacity paragraph each put "`available` route" before
  "capacity rejection … no retry … no native fallback".
- **AC3 (routing error):** the shared configured-review paragraph and
  `codex-collaboration`'s capacity paragraph each state "routing error, never a
  capacity rejection". Both callers' dispatch sites, ship-issue Phase 5 and
  sdd's correctness bullet, name "routing error" and then the discard, the record
  beside the correctness verdict, and the native dispatch.
- **AC4 (sdd):** the sdd final-review correctness bullet satisfies AC1's ladder
  shape with `correctness-reviewer-prompt.md` as its rung-3 target. "When the
  `codex-collaboration` skill is available" is gone.
- **AC5 (no collateral):** the agent-dispatch markers and call lines are
  unchanged, and the existing pinned phrases still hold. `just
  agent-workflow-tests` and `just build` pass.

## Test seams

There is one seam: the text-level skill-contract tests in the agent-skills
workflow contract suite. They read normalized skill text and use the suite's
ordered-anchor assertion (per D3). The prior art is the capability-before-lookup
test, the configured-review and Codex-operation pair helpers, and the
refusal-reporting self-check that proves a helper fails on a missing clause.

- AC2 and the paragraph half of AC3 extend the two existing pair helpers with
  the `available`-route and routing-error anchors. Every owner/support pair
  already checked by them inherits the change.
- AC1, AC4 and the caller half of AC3 get one new ladder helper. It takes a
  document's correctness-route text and the rung-3 target anchor, and ship-issue
  and sdd each apply it once. A self-check puts the pre-fix wording back and
  asserts that the helper raises.
- AC1's `codex-collaboration` half extends the capability-before-lookup test with
  the "makes no Codex call" anchor.
- The dispatch-contract and model-matrix tests guard AC5's markers, unchanged.
  No eval file changes.

## Out of scope

- Plan-review routing: from-issue's standards-review already routes on
  `capabilities.review.plan`. Its "`codex-collaboration` available" wording is
  left as it is.
- from-issue's suspension procedure and its `usage_limit` value. Once the
  routing error no longer stops ship, nothing suspends for it.
- The degradation gate's clause "the retained `capabilities.review.code` state
  permits the documented review route".
- resolve-project, workflow-state, `diff-scope`, review-package and every Python
  helper. The Codex transport tail, model and effort flags. The duplication of
  the configured-review transport paragraph between ship-issue and
  `codex-collaboration`.
- nodocom's #126 configuration, and any eval-corpus change.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Fix sdd's final-review correctness routing in this change, together with ship-issue (Phase-0 Q1). | sdd's bullet has the same skill-presence defect, and its capacity sentence is a copy of ship-issue REVIEW.md's configured-review paragraph; the-bar DRY says to change together copies that must change together. sdd runs before ship, so it would suspend the run first. | A follow-up issue: that leaves the shared paragraph diverged, or knowingly broken one phase earlier. |
| D2 | Under `unsupported`, a Codex call is a routing error: discard its outcome (verdict, refusal or failure), record it beside the correctness verdict (ship PR body, sdd ledger), and run the native dispatch with no retry, stop or suspension (Phase-0 Q2). | The issue says it must not be a binding capacity rejection. codex-collaboration: only a validated configured-command success establishes Codex identity. the-bar "The log stream is the debugger" says to record the defect. | Stopping as a contract failure recreates the stall when a documented route exists. Keeping a successful off-route Codex verdict makes the route depend on the outcome again. |
| D3 | Test with text-level ordered-anchor contract tests: extend the two pair helpers and the capability-before-lookup test, and add one ladder helper with a pre-fix-wording self-check. Change no eval (Phase-0 Q3). | The issue asks for a skill-contract test. The suite's existing seam and the refusal-reporting self-check precedent. the-bar "Tests that can fail". | A new eval case: LLM-graded, not deterministic, and not what the acceptance names. |
| D4 | Order the ladder `blocked` → `available` with `codex-collaboration` installed → `unsupported` or skill not installed, and route before either axis is dispatched. `available` without the skill goes native. | Precedent: from-issue standards-review's plan-review ladder. the-bar "Fail loud": each state of the closed set gets named handling, with no `unavailable` catch-all. | Routing only on the capability state: a native Codex session with `available` would then call a skill it does not have. |
| D5 | Use "installed" for the skill's presence and keep "available" for the capability state only. | The defect was a skill-presence word read as a capability state. | Reuse standards-review's "`codex-collaboration` available": the same ambiguity would come back. |
| D6 | `codex-collaboration` under `unsupported` makes no Codex call and returns to the calling controller's native route. It does not run the native reviewer itself. | It never names the "documented native route" it defers to. Its ban on bridges and defaults. The caller-owned unsupported route in the plan-review precedent. | The skill runs the native reviewer itself: that moves caller-owned dispatch into a Claude-only bridge, and a Codex host loses the route. |
| D7 | Scope the capacity rule with "On the `available` route" in the shared configured-review paragraph, kept identical in ship-issue and sdd, and in `codex-collaboration`'s paragraph. | Issue 100 D7 grounds the rule in the configured command's shared app-server daemon, which only the `available` route uses. | Drop the rule for the non-`available` routes, or re-word it per caller: that splits the copies or weakens AC2. |
| D8 | Keep the native route's existing names. `ship-issue-full-correctness-fallback` stays the id of the documented primary route under `unsupported`. After a routing error, sdd records identity `native` with a note beside it and adds no new failure class. | model-matrix and the dispatch-contract tests pin marker ids and call lines. The issue's acceptance names that id. sdd's closed identity set, in which `fallback` means codex-collaboration's non-capacity fallback. | Rename the marker to drop "fallback", or record `fallback` + `routing error`: that churns the pinned matrix, or blurs which reviewer actually ran. |
| D9 | Give each rule one home per document family. The capacity terms, and the routing-error classification that scopes them, live in the shared configured-review paragraph and in codex-collaboration's capacity paragraph. The callers' dispatch sites carry the ladder and the routing-error action, and ship's `available` rung points to REVIEW.md for the capacity terms. | the-bar DRY: one authoritative home, derived copies link to it. ship-issue says to read REVIEW.md before dispatching. | Restate the full capacity and routing-error text at every site: five copies that must change together. |
| D10 | Plan: pin every reworded routing sentence at D3's seam. Both callers open with one shared sentence and number the rungs `1. \`blocked\``, `2. \`available\``, `3. \`unsupported\``, and the ladder helper anchors on those words. Its self-check puts sdd's pre-fix bullet back, and breaks the live ship text four ways (pre-fix sentence, `diff-review` in rung 3, capacity leaving rung 2, outcome kept). One `assertIn` each pins DIFF-REVIEW's pre-flight clause, the sdd agent-tiers bullet and the rubric header. A new test asserts the configured-review paragraph is byte-identical in both copies. | Spec §3 ("the two copies stay identical"), §4 and §5. The-bar "Tests that can fail" and DRY. standards-review's numbered plan-review ladder. | Pin only the anchors the spec lists: DIFF-REVIEW, the tiers bullet and the header would change untested, and the paragraph copies could drift apart unnoticed. |
| D11 | Plan: change no eval. sdd eval 2 ("has the codex-collaboration skill installed" → `diff-review`) still grades correctly as rung 2 with an available capability. codex-collaboration evals 1–2 ("unsupported takes the documented native route") still grade correctly, because the operation returns to its caller's documented native route. | Spec Out of scope ("any eval-corpus change") and D3. These evals are plan-only, and `run-eval.sh` prints them for hand grading. | Rewrite sdd eval 2 to name the capability: that is outside the spec's scope, and no deterministic test reads it. |
| D12 | Standards review: the ladder helper also asserts "`codex-collaboration` is never invoked on this rung" over the whole rung-3 text, through its dispatch, up to the routing-error paragraph. It gains one reversal mutant per caller (ship: a fifth mutant; sdd: a second check in its self-check). Extends D10. | Codex plan-review finding PR195-01. The rung-3 slice ended at the native target, so reversing the central no-invocation sentence passed, and sdd's clause sits after its target. The-bar "Tests that can fail". | Leave the clause unpinned: that reverses AC1's core promise with no failing test. |
| D13 | Standards review: ship-issue REVIEW.md's templates paragraph calls `correctness-reviewer-prompt.md` "the native correctness form", not "fallback". SKILL.md's "fallback rubrics" stays, because it names REVIEW.md's pasted rubrics for missing sdd templates. | Native reviewer finding S1. Under `unsupported` that template is the documented primary route (D8, spec §5). Task 3 makes the same rename in the sdd header. | Leave REVIEW.md as it is: ship's prose would then call the primary route a fallback, the drift the sdd header fix removes. |
| D14 | Task review: the ship ladder test pins every rung clause the ladder helper left unpinned — rung 1's "neither axis is dispatched", rung 2's "with `codex-collaboration` installed" lead and its non-capacity fallback sentence, and rung 3's "`available` without `codex-collaboration` installed" lead — with one mutant for the "without … installed" clause. | Global Constraint "Every quoted sentence is pinned by a test in the same task"; D3, D5. The Task-2 reviewer found that deleting any of these kept every test green. | Keep Task 2's planned test list: D5's skill-presence condition could then vanish silently. |
