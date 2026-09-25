# Harden the workflow lifecycle: late finishes, budget gate, budget config, retry worktrees

Issue: https://github.com/fagenorn/nix-config/issues/33

Amends (does not fork) `.claude/specs/2026-08-13-durable-workflow-lifecycle-design.md`.
The amended clauses and the verbatim inline markers are listed in
[Amendments to the 2026-08-13 design](#amendments-to-the-2026-08-13-design).

## Problem

The 2026-08-16/17 orchestration run `orchestrate-21-24-r2` hit four independent
defects in the durable workflow lifecycle. Each is reproducible at the base commit
and each destroys or blocks real work:

1. **A late finish erases a real result.** `command_finish` discards the reported
   terminal result whenever `now >= deadline_at` and writes a synthetic
   `stopped` / `"attempt deadline expired"` in its place. An owner whose PR
   *merged* and who reported one minute past its budget has that merge deleted
   from the durable record — and, because `from-issue`'s terminal return procedure
   relays the helper's stdout verbatim, the dispatcher is told the issue stopped.
   The synthetic result is meant for owners that never reported at all; today it
   overwrites owners that did.

2. **The phase gate short-circuits past the budget.** `select_phase_action`
   returns `delegate` on `remainder_self_contained=true` as its *first* rule,
   before any turn or context ceiling is consulted. Delegation spawns a
   cold-context agent, so the turn and context counters never approach their
   ceilings, so `handoff` is never selected — an honest owner can self-clone at
   every phase boundary until the wall clock reaps the whole attempt with nothing
   durable written. `delegate` can also be selected with `turn_count` and
   `context_tokens` absent, so the persisted `phase_inputs` cannot show that any
   budget was ever measured.

3. **The budget is hardcoded prose.** No `.claude/skills.config.json` exists.
   `orchestrate-issues` §3 passes `--budget-minutes <budget>` without ever saying
   where `<budget>` comes from; the 90-minute default lives only in §4's narrative
   and `orchestration.maxParallel`'s default only in §1's. Under nix-daemon
   contention from sibling worktrees, `just build` runs 3–13 minutes per task, so
   90 minutes reaped four attempts in one run and there was no configuration
   surface to raise it.

4. **A retry cannot reach the existing work.** The dispatcher reserves a *fresh,
   collision-free* worktree path per attempt (§3, §5.3). `from-issue` Phase 0
   *prefers resuming* the single existing worktree when it holds resume signals,
   and Phase 1 fails the attempt when the envelope path is "occupied or
   mismatched". Git refuses a second checkout of one branch, so on every retry the
   reserved envelope path is unreachable by construction: `git worktree add -b
   <branch> <fresh-path>` fails because the branch is already checked out at the
   prior attempt's path. Each retry owner burns turns discovering the
   contradiction, and one was denied the workaround move outright.

## Terminology

The word **budget** carries two unrelated meanings across this issue, the
2026-08-13 design and the two skills, and items 2 and 3 touch one each. This spec
uses these names throughout and the dictated prose must too (per D16):

- **Attempt budget** — the wall-clock allowance for one attempt.
  `agentBudgetMinutes` minutes, fixed at fresh launch as `deadline_at`, enforced
  by `reconcile` and by `launch`'s deadline check. Items 1 and 3 are about this
  one. `select_phase_action` never sees it.
- **Phase budget** — the turn and context ceilings (`turn_ceiling`,
  `context_ceiling`, and their headrooms) that `select_phase_action` evaluates at
  a phase boundary. Item 2 is about this one, and nothing in item 2 reads or
  changes the wall clock.

"Ceiling" always means a phase-budget limit; "deadline" and "wall clock" always
mean the attempt budget. This repo has no glossary or context map and the
2026-08-13 design's "Documentation home" decision keeps such records in the spec,
so these definitions live here rather than in a new docs tree.

## Solution

Four changes, each landing at the layer that owns the fact:

- **The ledger records who wrote a terminal result and when.** Two new attempt
  fields, `finished_at` and `result_source`, make the synthetic expiry
  distinguishable from an owner's report. `finish` no longer overwrites a
  reported result at the deadline; instead the deadline-synthesized result becomes
  *provisional* and a later owner report supersedes it. Lateness is derived
  (`finished_at >= deadline_at`), never stored twice.
- **The gate checks budget before it checks delegation.** `select_phase_action`
  reorders so that unknown usage and at-ceiling usage both return `handoff` before
  `remainder_self_contained` is consulted. `delegate` therefore implies measured
  usage below both ceilings, which is exactly the observability the issue asks for
  and is re-derivable from the persisted `phase_inputs` by `validate_attempt`.
- **The budget becomes a resolved binding.** `.claude/skills.config.json` is
  created carrying only an `orchestration` section; `resolve-bindings` gains
  `agentBudgetMinutes` and `maxParallel` with the documented defaults, so the
  dispatcher reads one `key=value` line instead of a narrated constant.
- **The retry contract hands back the prior worktree.** No helper change: the
  ledger already records and returns each attempt's worktree, and the helper
  already accepts a fresh attempt that reuses it. The dispatcher's §5.3 and
  `from-issue`'s Phase 1 are amended into a two-sided contract, anchored by one new
  CLI test that pins the helper behaviour the contract depends on.

## Decisions

### Modules and interfaces touched

| Unit | Change |
| --- | --- |
| `workflow-state.py` · `ATTEMPT_FIELDS` | add `finished_at`, `result_source` |
| `workflow-state.py` · `RESULT_SOURCES` (new module constant) | closed set `{"owner", "expiry", "superseded", "refused"}` |
| `workflow-state.py` · `validate_attempt` | validate both new fields and their cross-field invariants |
| `workflow-state.py` · `select_phase_action` | reorder the rule sequence |
| `workflow-state.py` · `stop_attempt` | take the recording time and a source; stamp both new fields |
| `workflow-state.py` · `command_finish` | supersede a provisional expiry; drop the deadline overwrite; reject backward time |
| `workflow-state.py` · `command_launch`, `command_reconcile` | pass the source/time through `stop_attempt`; stamp the refusal path |
| `resolve-bindings` | emit `agentBudgetMinutes`, `maxParallel` |
| `.claude/skills.config.json` (new) | `orchestration.agentBudgetMinutes`, `orchestration.maxParallel` |
| `orchestrate-issues/SKILL.md` | §3 budget provenance; §5.3 prior-worktree retry |
| `orchestrate-issues/evals/evals.json` | two `expected_output` passages that grade the retired behaviour |
| `from-issue/SKILL.md` | Phase 1 envelope adoption; phase-gate deadline-rejection route |
| `.claude/specs/2026-08-13-durable-workflow-lifecycle-design.md` | four inline amendment markers |

`PHASE_INPUT_FIELDS`, `validate_phase_inputs`, `RESULT_FIELDS`, `validate_result`,
`ATTEMPT_STATES`, `RESULT_STATES`, `PHASE_ACTIONS`, `SCHEMA_VERSION` and the
compact terminal-result schema are **unchanged**. The gate takes no new input and
the dispatcher-visible result object gains no field, so no consumer outside the
attempt record is affected.

### Item 1 — a late finish preserves the owner's result

**Two new attempt fields**, both `null` if and only if `result` is `null`:

- `finished_at` — RFC3339 UTC, the moment the terminal record was written.
- `result_source` — one of `owner | expiry | superseded | refused`.

`result_source` values, one producing site each:

| Value | Produced by | Meaning |
| --- | --- | --- |
| `owner` | `command_finish` | the owner reported this result |
| `expiry` | `command_reconcile`, and `command_launch`'s deadline check on a resume | the attempt crossed its fixed deadline with no owner report |
| `superseded` | `command_launch`, stopping the prior attempt before appending a fresh one | a fresh retry ended this attempt |
| `refused` | `command_launch`'s third-attempt refusal | the two-attempt cap ended this attempt |

**Lateness is derived, never stored:** an attempt is a late finish when
`result_source == "owner"` and `finished_at >= deadline_at`. This mirrors the
file's existing style, where `validate_attempt` re-derives `phase_action` from
`phase_inputs` rather than trusting a stored label (per D1).

**`command_finish`'s new rule order**, replacing the current conflict/deadline
block. `attempt` is `issue_state["attempts"][args.attempt - 1]`; `existing` is
`attempt["result"]`; `outcome` is `issue_state["outcome"]`:

1. `now` earlier than `attempt["last_progress_at"]` → raise
   `finish time must not move backward` (mirrors `command_progress`'s guard, and
   makes `finished_at` trustworthy enough to derive lateness from). Deliberately
   *before* rule 2: a byte-identical replay carrying a clock that moved backward
   is a lie about when the work ended, not an idempotent retry, and rule 2's
   equality check compares only the result object, which cannot see it.
2. **Idempotent** — `existing == result and outcome == result` → return `result`,
   no state change. `finished_at` keeps the first write's value. *(unchanged)*
3. **Supersede a provisional expiry** — when *all* hold:
   `args.attempt == len(issue_state["attempts"])` (the attempt is the issue's
   **latest**); `attempt["result_source"] == "expiry"`; `outcome == existing` —
   then overwrite `attempt["state"]`, `attempt["result"]`, `finished_at = now`,
   `result_source = "owner"`, and `issue_state["outcome"]`, and return the
   reported result. A repeat of the same call afterwards matches rule 2 and is
   idempotent, so `finished_at` records the supersession, not the retry.
4. `existing is not None or outcome is not None` → raise
   `conflicting terminal result …` *(unchanged)*
5. `attempt["state"] != "active"` → raise `finish requires an active attempt`
   *(unchanged — this is what rejects a `handed_off` finish)*
6. Record the reported result with `finished_at = now`, `result_source = "owner"`.
   **The `now >= deadline_at` branch is deleted**: a late finish records normally.

`retain_worktree` still appends the worktree to `stopped`/`failed` notes only;
a preserved late `merged` result's `notes`, `pr_url`, `merge_sha` and
`issue_closed` are stored byte-for-byte as reported.

**`command_progress` stays strict** at the deadline (per D3). The deadline keeps
its teeth — it still stops new work — it merely stops destroying finished work.
`from-issue` gains one sentence routing that rejection to the terminal return
procedure, so the owner writes its truthful result instead of reading the error as
a harness fault (per D8).

**`command_reconcile` stays destructive-free by construction** (per D4): it still
stamps the synthetic `stopped` on an overdue attempt, but that record is now
provisional (`result_source: "expiry"`) and rule 3 lets a later owner report win.
A `superseded` or `refused` record is never supersedable, and an *older* attempt's
expiry is never supersedable once a newer attempt exists — the 2026-08-13 design
already settled that a delayed report for an older attempt cannot replace a newer
authoritative record.

**New validation clauses in `validate_attempt`:**

- `finished_at` is `null` ⟺ `result` is `null` ⟺ `result_source` is `null`.
- `result_source`, when set, is in `RESULT_SOURCES` — else raise
  `invalid attempt result source`.
- `finished_at`, when set, parses as RFC3339 UTC and satisfies
  `started_at <= finished_at`. It is deliberately **not** bounded above by
  `deadline_at` — that unbounded upper end is the whole point of item 1.
- `result_source == "expiry"` ⟹ `finished_at >= deadline_at` (an expiry cannot
  exist before its deadline).

Cross-attempt clock consistency at `launch` (a dispatcher passing a `--now`
earlier than the superseded attempt's `last_progress_at`) is unguarded today and
stays unguarded; see Out of scope.

### Item 2 — the phase gate consults budget before delegation

`select_phase_action`'s new rule sequence (signature unchanged):

1. `artifacts_sufficient and not next_needs_context` → `fresh_start`
2. `turn_count is None or context_tokens is None` → `handoff`
3. `turn_count >= turn_ceiling - turn_headroom or context_tokens >=
   context_ceiling - context_headroom` → `handoff`
4. `remainder_self_contained` → `delegate`
5. `not next_needs_context` → `handoff`
6. → `continue`

> (**amended by issue 74's direct-autonomous-implementation-owner-rollover
> design, D1/D2** — issue 74 adds a reserved module-owned direct exception whose
> self-contained remainder delegates before usage, while the issue-33 order
> above remains the complete order for every non-direct run.)

Rationale for this exact order (per D5): `fresh_start` stays first because
`not next_needs_context and artifacts_sufficient` means the conversation is
*disposable* and a new session reconstructs from committed artifacts — the
cheapest possible transition, correct at any budget level, and it costs neither a
handoff document nor a nested agent. Everything below it keeps some tie to this
conversation, and an exhausted conversation must not keep any: `delegate` is a
foreground nested dispatch whose parent stays alive to relay the result, which an
owner at turn 119 of 120 cannot do. Unknown usage keeps its existing meaning —
"cannot prove room" — and the 2026-08-13 design already fixed it to `handoff`.

**Observability** (the issue's second half): `delegate` is now reachable only
*past* rules 2 and 3, so a persisted `phase_action == "delegate"` implies
non-null `turn_count` and `context_tokens` strictly below both thresholds, and
`validate_attempt`'s existing `select_phase_action(**phase_inputs) !=
phase_action` re-derivation already refuses any record that claims otherwise. No
new phase input and no new stored field are needed.

**`delegate` does not reset the attempt wall clock** (per D6) — an explicit
non-change. The 2026-08-13 design fixes the deadline at fresh launch precisely so
activity cannot extend an abandoned attempt; a reset would restore the unbounded
self-cloning that item 2 exists to end.

### Item 3 — the budget becomes a resolved binding

**`.claude/skills.config.json`** is created at the repository root carrying
exactly one section (per D9):

```json
{
  "orchestration": {
    "agentBudgetMinutes": 180,
    "maxParallel": 2
  }
}
```

180 minutes (per D10) is double the reaped default, sized against the observed
3–13 minutes per `just build` under nix-daemon contention across a 7-phase
from-issue run. Nothing else is pinned: every other binding this repo uses is
already derived correctly from git and the shared defaults, and pinning a fact git
owns creates a second home that can drift.

**`resolve-bindings`** gains two emitted keys so the *default* has one
authoritative home instead of living in dispatcher narrative:

- `DEFAULTS` gains `agentBudgetMinutes = "90"` and `maxParallel = "2"` — the two
  values `orchestrate-issues` narrates today, moved verbatim.
- A `positive_int_str(value, default)` helper mirrors the existing
  `as_bool_str(value, default)` precedent: a present-but-invalid value (non-int,
  bool, or `<= 0`) prints one `resolve-bindings: …` diagnostic to stderr and
  falls back to the documented default, keeping exit status 0 (per D11).
- Emitted lines join the existing sorted `key=value` output:
  `agentBudgetMinutes=180`, `maxParallel=2`.

**`orchestrate-issues/SKILL.md`** changes in two places:

- §1's `maxParallel` sentence resolves through `~/.agents/bin/resolve-bindings`
  rather than "read the config", keeping the same default.
- §3's `--budget-minutes <budget>` states its provenance: `<budget>` is
  `agentBudgetMinutes` from `~/.agents/bin/resolve-bindings`
  (`orchestration.agentBudgetMinutes` in `.claude/skills.config.json`, default
  90). §4's budget-guard parenthetical is rewritten to cite the resolver as the
  single source rather than restate the number as its own default.

**`workflow-state launch --budget-minutes` stays `required=True`** (per D12). The
helper is project-agnostic — its `--repo-root` is a *ledger* root, it has never
read `.claude/skills.config.json`, and giving it its own default would create a
second budget home that silently wins whenever a caller forgets the flag.

### Item 4 — a retry reaches the existing work

**No `workflow-state` code change** (per D13). Verified against the live helper at
the base commit: `launch` with a **new owner handle** and the **prior attempt's
recorded worktree** already creates attempt 2 with that worktree,
`prior_attempt: 1`, `state: active`; neither `validate_attempt` nor
`validate_state` constrains worktree uniqueness across attempts. `launch` with the
**same owner** and the same worktree instead returns attempt 1's stored terminal
outcome without launching, which is the design's resume-identity rule working as
intended. The retry must therefore carry a **fresh owner handle and the prior
worktree path** — the identity that decides fresh-vs-resume is the owner, not the
workspace.

The prior worktree is already returned to the dispatcher: `reconcile` (which §5 in
any case mandates before every retry) prints the full ledger including
`attempts[-1].worktree`, and the superseding stop already copies that path into
the result notes. So the fix is the two-sided prose contract, plus one CLI test
pinning the helper behaviour it rests on.

**`orchestrate-issues/SKILL.md` §5.3** — the fresh-retry bullet becomes:

- Read the prior attempt's recorded `worktree` from the reconciled ledger.
- Check whether that exact path is still a live git worktree checked out on this
  issue's branch — one `git worktree list --porcelain` scan. This is worktree
  metadata, not issue content, so the dispatcher's role boundary holds; the
  deeper resume-signal inspection stays the owner's Phase-0 job (per D14).
- Live → pass that exact path as `--worktree` with a **fresh owner identity**.
- Not live (removed, or on another branch) → reserve a fresh collision-free path
  exactly as §3 does for a first attempt.
- Either way, spawn only from the accepted attempt.

§3's first-attempt reservation wording ("reserve a collision-free exact absolute
worktree path", "does not create the worktree", "configured worktree root") is
unchanged.

**`from-issue/SKILL.md` Phase 1** — the lifecycle-envelope paragraph becomes a
three-way decision on the envelope's exact absolute path, keeping "never choose
another path":

- **Absent** from the filesystem and from `git worktree list` → create it from
  `origin/<integration-branch>`, as today.
- **Already a git worktree checked out on this issue's branch** → **adopt it**:
  `cd` in and continue. Do not re-create it, do not move it, do not reset it.
  Phase 0's resume-signal inspection governs what to do with its contents.
- **Anything else** — occupied by a non-worktree path, or a worktree on a
  different branch → fail the attempt through the terminal return procedure,
  naming both the envelope path and what was found, so the dispatcher can correct
  the reservation. Never remove unknown contents.

**`orchestrate-issues/evals/evals.json`** grades the retired behaviour in two
`expected_output` passages and must change in the same commit (per D17), because
an eval is the graded statement of what the skill should do:

- Eval 2 (failure-policy case (c)) says a retry "issues a fresh owner **AND fresh
  worktree** (attempt 2)". Rewrite to: a fresh owner identity, and the prior
  attempt's recorded worktree when it is still a live worktree on the issue's
  branch, else a freshly reserved path.
- Eval 1 says "read `orchestration.maxParallel` (default 2) **from config**" and
  eval 2 says "default 90 min, `orchestration.agentBudgetMinutes` overrides".
  Rewrite both to resolve through `~/.agents/bin/resolve-bindings`, keeping the
  same numbers.

Eval 1's "reserve a collision-free absolute worktree path" sentence stays: it
describes the first-attempt path, which is unchanged.

This removes the base-commit contradiction with Phase 0: on a retry the envelope
now names the same worktree Phase 0's inspection prefers to resume, so "prefer
resume" and "use the exact envelope path" agree instead of fighting. When they
still disagree — Phase 0 finds the issue's worktree at a path the envelope does
not name — the attempt fails as blocked rather than relocating, because the
envelope identity binds through shipping and cleanup.

### Amendments to the 2026-08-13 design

Applied to `.claude/specs/2026-08-13-durable-workflow-lifecycle-design.md` **in
the execute phase, not now** (per D15), following the inline-marker convention
that issue 32's alignment spec established (its D8/D9: specs are records amended
inline; cross-spec markers lead with the amending issue and spec name). Four
markers, appended to the sentences named below:

1. **"Attempt schema and identity"**, after the JSON block's paragraph:
   > (**amended by issue 33's workflow-lifecycle-hardening spec, D1/D2** — every
   > attempt also carries `finished_at` and `result_source`, and a fresh retry may
   > reuse the prior attempt's worktree path; the identity that distinguishes a
   > resume from a fresh retry is the owner handle, not the workspace.)

2. **"Lifecycle state machine"**, after "All terminal transitions preserve the
   worktree path":
   > (**amended by issue 33's workflow-lifecycle-hardening spec, D2/D4** — a
   > `finish` at or after the deadline records the owner's reported result rather
   > than a synthetic expiry; the expiry result written by `reconcile` is
   > provisional and is superseded by a later owner report on the same latest
   > attempt.)

3. **"Notification reconciliation"**, on the bullet beginning "An active or
   handed-off attempt at/after its deadline becomes `stopped`":
   > (**amended by issue 33's workflow-lifecycle-hardening spec, D4** — this
   > stopped result is provisional: it carries `result_source: "expiry"` and a
   > later `finish` from that attempt's owner replaces it.)

4. **"Executable phase-boundary budget decision"**, on the numbered action list:
   > (**amended by issue 33's workflow-lifecycle-hardening spec, D5** — this list
   > originally evaluated `delegate` first; the ceiling and unknown-usage checks
   > now precede it, so `delegate` is selected only with measured usage below both
   > ceilings. The fixed wall deadline is unchanged: `delegate` does not reset it.)

No other clause of that design changes, and nothing in it is deleted or rewritten.

## Test seams

The four seams the 2026-08-13 design established, unchanged; item 3 adds the
resolver seam because `resolve-bindings` is the only script under
`agent-skills/scripts/` without a test module.

- **Lifecycle CLI seam** — `home/common/agent-skills/tests/test_workflow_state.py`.
  Invoke the helper as a subprocess against a temp repo root with injected
  timestamps; assert exit code, stdout JSON, and the reopened `state.json`.
- **Skill contract seam** —
  `home/common/agent-skills/tests/test_workflow_skill_contracts.py`. Prose anchors
  and `assert_ordered` chains over the two SKILL.md files.
- **Binding resolver seam (new)** —
  `home/common/agent-skills/tests/test_resolve_bindings.py`. Subprocess the repo's
  `scripts/resolve-bindings` against a temp repo with and without a config, parse
  the `key=value` lines. Follows `test_diff_scope.py`'s subprocess-a-script shape.
  Wire it into the `agent-workflow-tests` recipe in `justfile`.
- **Build seam** — `just agent-workflow-tests`, then `just build`.

No new seam is introduced and no test may reach inside `workflow-state.py`; the
CLI plus the durable file remain the only boundary, because that is the boundary
the skills use.

### Tests to revise (not merely supplement)

| Test | Change |
| --- | --- |
| `test_workflow_state.py::test_late_merged_finish_persists_canonical_stopped_expiry` | **Reversed and renamed** to `test_late_merged_finish_preserves_the_owner_result`. Assert `state == "merged"`, `pr_url`/`merge_sha`/`issue_closed` preserved verbatim, `notes == ""` (no worktree suffix), `finished_at == "2026-08-13T20:10:00Z"`, `finished_at >= deadline_at`, `result_source == "owner"`, and outcome + attempt result all equal. |
| `test_workflow_state.py::test_progress_action_precedence_and_complete_inputs_are_persisted` | Case 1 (`remainder_self_contained: True, turn 119, ctx 149000`) flips from `delegate` to `handoff`. The other five cases are unchanged — verified against the new rule order. |
| `test_workflow_state.py::test_owner_death_expiry_stops_active_attempt_with_worktree` | Extend with `result_source == "expiry"` and `finished_at == "2026-08-13T20:10:00Z"`. |
| `test_workflow_state.py::test_cross_field_lifecycle_corruption_is_rejected_without_changes` | Add corruption labels: `terminal-without-finished-at`, `finished-at-before-start`, `unknown-result-source`, `expiry-finished-before-deadline`, `nonterminal-with-result-source`. |
| `test_workflow_skill_contracts.py::test_lifecycle_phase_one_uses_exact_reserved_attempt_worktree` | Revise the anchor chain for the three-way Phase-1 decision; keep `never choose another path` and `fail the attempt`, replace the `occupied or mismatched` anchor with the adopt/fail wording the new prose actually uses. |
| `test_workflow_skill_contracts.py::test_dispatcher_resumes_recorded_attempt_before_fresh_launch` | Extend the ordered chain through the prior-worktree retry step and the fresh-owner-identity requirement. |

`test_dispatcher_reserves_attempt_worktree_before_launch_and_envelope`,
`test_progress_rejects_threshold_continue_invalid_inputs_and_transitions` and
`test_combined_controller_demo_has_one_authoritative_outcome_per_issue` must keep
passing untouched — verified: none depends on the flipped ordering or on the
deleted deadline branch.

### Tests to add

- `test_delegate_requires_measured_usage_below_both_ceilings` — `delegate` with
  headroom (turn 10 / ctx 20000); `handoff` with `turn_count`/`context_tokens`
  absent; `handoff` at the context ceiling with `remainder_self_contained=true`.
- `test_expiry_result_is_provisional_until_the_owner_reports` — launch, reconcile
  past the deadline, assert `result_source == "expiry"`, then `finish` a merged
  result late and assert the attempt and issue outcome both become the owner's
  merged result with `result_source == "owner"`; a second, conflicting real
  `finish` then still fails loud with the state bytes unchanged.
- `test_expired_older_attempt_cannot_supersede_after_a_fresh_retry` — attempt 1
  expires, attempt 2 launches, a late `finish` on attempt 1 is rejected and the
  state bytes are unchanged.
- `test_refused_third_attempt_result_is_not_supersedable` — after the cap
  refusal, a late `finish` on attempt 2 is rejected.
- `test_finish_rejects_time_before_last_progress` — state bytes unchanged.
- `test_fresh_retry_may_reuse_the_prior_attempt_worktree` — after expiry, a launch
  with a **new owner** and the prior worktree records attempt 2 with that exact
  worktree and `prior_attempt: 1`; a launch with the **same owner** and the same
  worktree returns attempt 1's stored outcome and appends no attempt.
- `test_resolve_bindings.py` — three cases: no config file → `agentBudgetMinutes=90`,
  `maxParallel=2`; config with `orchestration.agentBudgetMinutes` → that value
  emitted; invalid value (`0`, `"90"`, `true`) → default emitted, a diagnostic on
  stderr, exit status 0. Plus one case run against the real repository root
  asserting the committed config's budget is what the resolver emits.
- Skill-contract additions: `orchestrate-issues` §3 names the resolver as the
  source of `--budget-minutes`; §5.3 orders reconcile → prior recorded worktree →
  live-worktree check → fresh owner identity → `workflow-state launch`;
  `from-issue`'s phase-gate section routes a deadline-rejected `progress` to the
  terminal return procedure.
- `test_orchestrate_eval_grades_the_prior_worktree_retry` — the eval's
  `expected_output` no longer contains `fresh worktree (attempt 2)` and does name
  the prior recorded worktree, following
  `test_ship_issue_eval_restates_the_gate_boundary_it_grades`'s precedent of
  pinning a skill and its grader together (per D17).

## Acceptance criteria and how each is verified

| # | Criterion (from the issue) | Verified by |
| --- | --- | --- |
| 1 | A result submitted at or after the deadline with a terminal state and PR reference is preserved in the durable attempt record | `test_late_merged_finish_preserves_the_owner_result` (the reversed base-commit test) and `test_expiry_result_is_provisional_until_the_owner_reports`, both under `just agent-workflow-tests` |
| 2 | With `remainder_self_contained=true` and turn or context usage past the ceiling, the selected phase action is not `delegate` | Case 1 of the revised `test_progress_action_precedence_and_complete_inputs_are_persisted` (now `handoff`), plus `test_delegate_requires_measured_usage_below_both_ceilings` for the ceiling, unknown-usage and headroom branches |
| 3 | The project skills config declares an orchestration budget and the dispatcher-visible default honors it | `test_resolve_bindings.py` (default, configured, invalid, and real-repo cases) plus the skill-contract assertion that `orchestrate-issues` §3 resolves `--budget-minutes` from the resolver |
| 4 | A second-attempt launch for an issue whose prior worktree holds resume signals records that existing worktree as the attempt's worktree, and from-issue's envelope handling accepts it without relocating | `test_fresh_retry_may_reuse_the_prior_attempt_worktree` for the ledger half; the revised `test_lifecycle_phase_one_uses_exact_reserved_attempt_worktree` and `test_dispatcher_resumes_recorded_attempt_before_fresh_launch` for the two-sided prose contract |

Whole-change gate: `just agent-workflow-tests` green (53 tests at the base commit,
green as of this spec) and `just build` succeeds.

**Deployment note for the executor.** `home/common/agent-skills/default.nix`
installs each script individually (`.agents/bin/workflow-state` ←
`scripts/workflow-state.py`, `.agents/bin/resolve-bindings` ←
`scripts/resolve-bindings`); `tests/` is not deployed, so a new test module needs
no Nix change — only the `agent-workflow-tests` recipe in `justfile`. Every test
runs the **repo source**, not `~/.agents/bin`, so the suite is green before any
rebuild; the deployed copies only change on `just switch`, which is not part of
this work's verification.

## Out of scope

- Redesigning the deadline-observer / reaper wake path in `orchestrate-issues` §4.
- Enforcing `orchestration.maxParallel` beyond reading and emitting the value.
- Changing the two-attempt cap, the retry-count policy, or the resume-identity
  rule (same owner + same worktree = resume).
- The nix-daemon contention that makes `just build` slow; only the budget that
  must accommodate it changes.
- Anything in `ship-issue`.
- Bumping `SCHEMA_VERSION` or migrating existing `state.json` files: run ledgers
  live under git-ignored `.superpowers/workflows/<run-id>/` and are per-run
  throwaway state, so an in-flight run predating the change is abandoned rather
  than migrated (per D7).
- Guarding a `launch --now` earlier than the superseded attempt's
  `last_progress_at`. It is unguarded at the base commit and stays so. Only
  `finish` gains a backward-time *check*; the other terminal writers reachable
  from `launch` — `stop_attempt`'s supersede path and the third-attempt refusal
  path — instead **clamp** the `finished_at` they stamp to at least the closed
  attempt's own `started_at`, so a backward launch clock cannot write a record
  the `finished_at >= started_at` invariant rejects (per D22). At the shipped
  commit the run-level `launch occurs after run update time` invariant already
  rejects such a launch wholesale, so the clamp is the second line of defence
  that keeps the unguarded clock from ever becoming a ledger-wide corruption.
- The latent overwrite in `command_launch`'s third-attempt refusal path, which
  replaces `attempts[-1]`'s existing terminal result with the refusal record. This
  work stamps `result_source: "refused"` there but does not change that
  behaviour; it is a separate defect with its own evidence requirement.
- Pinning any binding other than `orchestration` in `.claude/skills.config.json`.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Mark a late finish by storing `finished_at` and deriving lateness as `finished_at >= deadline_at`, rather than storing a `late` boolean or a new terminal state | `validate_attempt` already re-derives `phase_action` from `phase_inputs` and rejects a mismatch, so a stored label the validator cannot check is against the file's grain; the Bar's DRY gives each fact one home, and the 2026-08-13 design's "Ledger envelope" row already rejected redundant fields "that can diverge" | A `late_finish` boolean — duplicates knowledge two timestamps already carry and can contradict them; a `merged_late` terminal state — breaks `RESULT_STATES`, the dispatcher table, and every relay of the compact result |
| D2 | Add exactly two attempt fields, `finished_at` and `result_source` (closed set `owner \| expiry \| superseded \| refused`), both null iff `result` is null | `result_source` is genuinely new knowledge: an owner-reported `stopped` and a reaper-synthesized `stopped` are byte-identical today, and D4's supersession rule must tell them apart. The Bar's fail-loud rule wants a closed set at that dispatch, and each of the four values has exactly one producing site | Detect the synthetic expiry by regenerating `terminal_result(issue, "stopped", "attempt deadline expired; worktree: …")` and comparing for equality — no schema change, but it infers meaning from generated prose and would misclassify an owner who reports those exact notes; a single field encoding both lateness and source (`owner_late`) — makes the label unverifiable by the validator, losing D1 |
| D3 | `command_progress` keeps its hard error at or after the deadline; only `command_finish` becomes lenient | The 2026-08-13 "Fixed wall deadline" decision makes the deadline the thing that ends new work, and `validate_attempt`'s `started_at <= last_progress_at <= deadline_at` invariant would have to be relaxed too. The defect is that `finish` destroys truth, not that the deadline exists (the Bar's root-cause rule) | Relax both — the deadline would stop meaning anything and an abandoned owner could log progress forever, reversing the design's rejection of sliding inactivity expiry |
| D4 | `reconcile`'s synthetic expiry stays, but becomes provisional: a later `finish` from the owner of the **latest** attempt whose `result_source` is `expiry` supersedes it; `superseded`, `refused` and `owner` records are never supersedable, and an older attempt's record is never supersedable once a newer attempt exists | Without this, item 1 is defeated by timing alone — the deadline observer fires, `reconcile` stamps the expiry, and the owner's real merge hits `conflicting terminal result`. The narrow rule is the 2026-08-13 design's own: "the latest attempt together with the issue outcome is authoritative" and "a delayed notification for an older attempt cannot replace a newer authoritative terminal result" | Leave `reconcile` destructive and accept "reconcile ran first" as a race — reproduces exactly the failure the issue reports, only on a timer; allow any terminal record to be superseded — erases the cap-refusal record and turns the fail-loud conflict check into a last-writer-wins |
| D5 | Gate order: `fresh_start` → unknown usage `handoff` → at-ceiling `handoff` → `delegate` → `not next_needs_context` `handoff` → `continue` | `fresh_start` requires `not next_needs_context and artifacts_sufficient`, i.e. the conversation is disposable and artifacts suffice — correct at any budget and cheaper than both a handoff document and a nested agent, so it is right above the budget checks. `delegate` is a foreground nested dispatch whose parent must survive to relay, which an exhausted owner cannot, so it must sit below them. Only case 1 of the existing precedence test flips | Demote `delegate` but leave `fresh_start` below the ceiling checks — forces an exhausted owner with sufficient artifacts to write a handoff document it does not need; return `delegate` with the budget merely recorded — that is the self-cloning the issue names |
| D6 | `delegate` does not reset the attempt wall clock — recorded as an explicit non-change | The 2026-08-13 "Fixed wall deadline" decision fixes the deadline at fresh launch so activity cannot extend an abandoned attempt; the issue asks for ordering and observability, not a clock reset | Reset the deadline on delegation — restores unbounded self-cloning through a different door and reverses an accepted decision without evidence |
| D7 | Do not bump `SCHEMA_VERSION` or write a migration for the two new attempt fields | Run ledgers live under git-ignored `.superpowers/workflows/<run-id>/` and are per-run throwaway state; a stale in-flight run is abandoned, and `validate_state` already fails loud on an unreadable shape rather than silently accepting one | Bump the version and add a migration path — code for a caller that does not exist (YAGNI), and it would have to be maintained for state nothing reads twice |
| D8 | `from-issue`'s phase-gate section gains one sentence: a `progress` rejected at or after the deadline routes straight to the terminal return procedure with the owner's truthful state | D3 leaves the owner with a hard error at exactly the moment item 1 exists to serve; without this the owner reads it as a harness fault and may return without persisting, and `AUTO.md` already makes persistence precede notification unconditionally | Leave the prose alone — item 1's preservation path is reachable only by an owner that guesses it; make `progress` lenient instead — reverses D3 |
| D9 | `.claude/skills.config.json` carries **only** the `orchestration` section; nothing currently auto-detected is pinned | The Bar's DRY: git already authoritatively owns the remote slug, the branches and the tracker kind, and `resolve-bindings` derives all of them correctly inside a worktree (`.git` is a file there and `find_repo_root` accepts it). Absent keys fall through unchanged, so the file's blast radius across every other skill is nil | Pin `repoSlug`, branches and tracker for explicitness — creates a second home for facts git owns, which drifts silently on a rename or a fork |
| D10 | `agentBudgetMinutes: 180` in the committed config; the *default* stays 90 | The observed run reaped four attempts at 90 minutes with `just build` at 3–13 minutes per task across a 7-phase run; 180 doubles it with margin. Leaving the fallback at 90 keeps the documented contract unchanged and confines the change to one tunable value | Raise the default to 180 in `resolve-bindings` — changes behaviour for every project that has no config, on evidence from one machine's daemon contention |
| D11 | `resolve-bindings` emits `agentBudgetMinutes` and `maxParallel`, with the defaults living in its `DEFAULTS`; a present-but-invalid value logs one stderr diagnostic and falls back, keeping exit 0 | Item 3's actual defect is that the default is narrated prose; moving it into the resolver gives it one home and makes it testable, and every skill already runs the resolver. Graceful degradation on a bad optional key is the resolver's documented contract across all skills, and the diagnostic satisfies the Bar's log-stream rule | Keep the dispatcher parsing the JSON directly — leaves both defaults in prose, which is the defect; exit non-zero on an invalid value — breaks every skill's binding resolution over one optional orchestration key |
| D12 | `workflow-state launch --budget-minutes` stays required, with no helper-side default | The helper is project-agnostic and has never read the skills config; its `--repo-root` is a ledger root, not a project root. A helper-side default would silently win whenever a caller omitted the flag, giving 90 on a project configured for 180 | Default the flag to 90 — a second budget home that fails silently; teach the helper to read `.claude/skills.config.json` — couples a project-agnostic helper to a skills-config schema |
| D13 | Item 4 is a two-sided prose contract with no `workflow-state` code change, anchored by one new CLI test pinning the reuse behaviour | Verified against the live helper: a fresh owner plus the prior worktree already yields attempt 2 recording that worktree, and no uniqueness constraint exists. `reconcile` already returns the prior worktree before every retry, so the dispatcher has the value; the helper never observes worktrees, so it cannot validate the filesystem claim the contract rests on | A `--reuse-prior-worktree` flag — the dispatcher must choose the path *before* calling `launch`, so the flag adds a parameter without adding information; a `launch`-side validation — the helper cannot see the filesystem fact being asserted |
| D14 | The dispatcher's retry test is "the prior attempt's recorded worktree is still a live git worktree on this issue's branch" (one `git worktree list --porcelain` scan); the deeper resume-signal inspection stays `from-issue` Phase 0's job | `orchestrate-issues` opens by forbidding the dispatcher from reading code, specs, plans, diffs or review content; worktree metadata is not content, whereas counting unpushed commits or looking for spec artifacts starts down that road. Phase 0 already implements the four-signal inspection, so duplicating it would give one rule two homes | Have the dispatcher check all four of Phase 0's resume signals — breaks the dispatcher's role boundary and duplicates an existing implementation; hand back the prior worktree unconditionally — sends the owner at a path that may have been removed |
| D15 | The four amendment markers are dictated verbatim here and applied to the 2026-08-13 design in the execute phase, not now | Issue 32's alignment spec settled the convention (its D8/D9: specs are amended inline with a marker naming the amending issue and spec, never silently rewritten) and demonstrated dictating the replacement text in the amending spec. Applying at execute time keeps the marker atomic with the shipped field names, so an abandoned branch never leaves the old spec asserting behaviour that does not exist | Apply the markers now — the accepted record would claim semantics no code implements if this work is abandoned; write a new spec that forks the design — the issue explicitly requires amendment, not a fork |
| D16 | Name the two budgets distinctly — **attempt budget** (wall clock, `agentBudgetMinutes` → `deadline_at`) and **phase budget** (turn/context ceilings) — in the spec and in every line of prose this work dictates into the codebase | Grill pass: the issue title puts "budget gate" and "budget config" side by side, yet item 2 touches only turn/context and items 1 and 3 only the wall clock. `orchestrate-issues` §4 already calls the wall clock a "**Budget guard**" while `from-issue` calls the ceilings the "**budget** decision", so a reader who conflates them will look for a wall-clock input to `select_phase_action` that does not exist | Leave "budget" unqualified — the exact ambiguity that would make the next reader wire the deadline into the phase gate; create a glossary/context-map tree to hold the terms — the 2026-08-13 design's "Documentation home" decision already rejected bootstrapping docs for this workflow |
| D17 | Update `orchestrate-issues/evals/evals.json`'s two stale `expected_output` passages in the same commit as the skill prose | Grill pass, verified: eval 2 grades "fresh owner AND fresh worktree (attempt 2)", the precise behaviour item 4 retires, and both evals narrate the two defaults D11 moves into the resolver. An eval is the graded statement of correct behaviour, so leaving it is worse than leaving stale prose — it would actively fail a correct run. `test_ship_issue_eval_restates_the_gate_boundary_it_grades` is the repo's precedent for keeping an eval and its skill in lockstep | Leave the evals for a follow-up — the skill and its grader would disagree at the merge commit, exactly the drift issue 32 was opened to clean up |
| D18 | Split the helper work at the schema/behaviour boundary: Task 1 adds `finished_at`/`result_source` and stamps every existing terminal writer (leaving `command_finish`'s deadline branch intact but stamping `expiry`), Task 2 then rewrites `command_finish`'s rule order and deletes that branch | Task 1 is then green on its own with the base-commit test `test_late_merged_finish_persists_canonical_stopped_expiry` still passing, so a reviewer can reject the schema without rejecting the behaviour change and vice versa. `validate_attempt`'s exact-field-set check means the fields must land at every writer in one task or nothing validates | One task for all of item 1 — a reviewer cannot separate "are these the right two fields" from "is this the right supersession rule", and the diff spans the whole file; add the fields without stamping the writers — `validate_attempt` rejects every record the helper writes, so the suite is red mid-task with no way to tell a real defect from the split |
| D19 | Pin the five new `WorkflowError` message strings in the plan (`attempt result, finish time and result source must all be null or all be set`, `invalid attempt result source`, `invalid attempt finish time`, `invalid attempt finish time order`, `expiry finish time must not precede the attempt deadline`) rather than leaving wording to the implementer | The Bar's fail-loud rule wants the rejection to name the invariant it caught, and the corruption test asserts on message substrings — an implementer inventing wording independently of the test that greps for it produces a task that cannot go green. Matches the file's existing `invalid attempt <thing>` naming | Let the implementer choose and have the test match whatever it wrote — the test then grades the implementation against itself rather than against the spec's invariants |
| D20 | Assert explicitly that introducing `.claude/skills.config.json` leaves every previously-emitted binding byte-identical (`test_adding_the_config_does_not_disturb_the_other_bindings`) | D9 rests on "absent keys fall through unchanged, so the file's blast radius across every other skill is nil" — that is a claim about the resolver's behaviour, and this repo is the first project to gain the file, so nothing else would catch a regression in it. Cheap to pin, and it is the only guard on every skill's bindings at once | Trust the fall-through by inspection — the claim is load-bearing for four other skills and is exactly the kind of "obviously fine" change that silently reorders or drops a key |
| D21 | Run `just build` exactly once, in the final task, after `just agent-workflow-tests`; no per-task Nix gate | The change touches two Python scripts, three Markdown files, one JSON config and one `justfile` recipe — `home/common/agent-skills/default.nix` installs the scripts individually and does not deploy `tests/`, so no intermediate task can break Nix evaluation in a way the final build would miss. Under nix-daemon contention from the sibling worktrees a build costs 3–13 minutes, so a per-task gate would cost more wall clock than the whole implementation | A `just build` per task — buys no signal the final build does not, at up to 90 minutes of the attempt budget; skip `just build` entirely — the repo's stated verification step is a successful Nix evaluation, and the `justfile` recipe edit is inside its blast radius |
| D22 | The terminal writers reachable from `launch` clamp `finished_at` to `max(now, attempt.started_at)` (module helper `finish_time`, applied in `stop_attempt` and at the third-attempt refusal path) rather than `launch` gaining a backward-time guard | Out of scope keeps `launch`'s `--now` unguarded, so a dispatcher passing a `--now` earlier than the prior attempt's `started_at` would otherwise reach the new `finished_at >= started_at` invariant through the supersede and refusal writes (the run-level `launch occurs after run update time` check happens to reject that launch wholesale today, but nothing pins that coupling); a clamp is the smaller, more reversible fix and keeps the record truthful — the attempt ended no earlier than it began | Guard `launch --now` — reverses an accepted out-of-scope decision for a clock the design deliberately leaves to the dispatcher; leave it — one backward `--now` writes `finished_at < started_at` and every later `progress`, `finish` and `reconcile` for **every** issue in the run then fails validation, bricking the ledger |
