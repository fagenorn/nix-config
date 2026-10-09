---
name: from-issue
description: Drives one tracker issue through investigate → spec → plan → review → execute in a worktree. Use for "work on issue #X"; --auto selects autonomous mode.
---

# From Issue

Run `resolve-project resolve --repo-root <checkout>`. Resolve once at phase entry, retain the returned `ResolvedProject` in memory, and treat every resolver error as fatal before mutation or external effects. On refusal, preserve and report the resolver's `error.code`, `repair_id`, and ordered `violations` exactly; never translate it into a partial snapshot or fallback. The only sanctioned exception is `workflow-state build-delivery`, which performs its own sealed, read-only resolution when it builds a delivery contract (and `lane-triage evaluate`, read-only, for `bindings.workflow.light_lane`); this skill still never resolves again itself. Use `bindings.tracker`, `bindings.vcs`, `bindings.paths.artifacts`, and `bindings.workflow`; required blocked capabilities stop and authored unsupported capabilities take only documented no-capability routes.

Take one tracker issue from triage to merged code by chaining the canonical skills, carrying the caller's scoped authorization across phase boundaries.

## Files beside this one
- `<tracker-cli>` is `bindings.tracker.cli`; before invoking it, unset only the names `bindings.tracker.credential_env.unset_before_invocation` lists.
- Phases 2–5 ground through `doc-grounded-questions` before their first question, option set or review pass; that skill owns the pass and its git-dir `GROUNDING.md` cache.
- **`AUTO.md`** — autonomous-mode rules. Read it *once*, now, only if the invocation contains the literal token `--auto`. With a resume pack, defer that read until the pack's checks pass: a failed pack restores the whole read, and a verified pack reads only the opening, `The self-answer pattern` and `When *not* to auto-resolve`, plus its phase's route section — `Phases 2–4 run as subagents` for Phases 2–4; for Phases 5–7, `Other Phase 5–7 routes` (the direct-autonomous controller at Phase 5 reads `rollover.md`, and the delegated owner `delegated-owner.md`, in its place) and `Interface_version 2 delivery relay`.
- **`acquire-dispatcher.md`** — a complete dispatcher envelope, or a generic `delegate` owner.
- **`acquire-direct.md`** — `--auto` with no dispatcher envelope.
- **`acquire-durable.md`** — an interactive user's explicit request for durable orchestration.
- **`acquire-interactive.md`** — any other invocation, and Phase 1's ledger-free flow.
- **`resume-pack.md`** — the prompt carries a resume pack. A verified pack reads, at every phase, the sections headed `Lifecycle identity`, `Decision ledger (artifact discipline)`, `Skill-tool invocations`, `Dispatch, phase-budget and attempt-budget rules`, `Terminal return procedure` and `Suspension procedure`, then this file's `## Phase <n>` section, the file this index names for that phase, and the phase's sub-skill (`sdd` for Phase 6, `ship-issue` for Phase 7).
- **`investigate.md`** — Phase 0.
- **`decision-ledger.md`** — before writing the first ledger row.
- **`standards-review.md`** — Phase 5.
- **`REVIEW-CONTRACT.md`** — Phase-5 reviewer contract: hand it over **by absolute path**, never read it in.
- **`rollover.md`** — the direct autonomous controller's Phase-5 transfer and its stop afterwards.
- **`delegated-owner.md`** — the rollover's delegated owner, Phases 6–7; read it first, before any resume pack.
- **`ship-handoff.md`** — Phase 7.

## Lifecycle identity
Select the acquisition route by the first condition that holds:

1. a complete dispatcher envelope → `acquire-dispatcher.md`;
2. otherwise literal `--auto` → `acquire-direct.md`;
3. otherwise an explicit request for durable orchestration → `acquire-durable.md`;
4. otherwise → `acquire-interactive.md`.

Once any route produces lifecycle identity, treat `ledger_repo_root`, `run_id`, `issue`, `attempt`, `owner`, `action_id`, and normalized `worktree` as one identity and never guess a missing field. Every `workflow-state` command of this owner or its delegated remainder takes `--repo-root <ledger_repo_root>` exactly as supplied (never the current checkout or owner worktree), by the full `~/.agents/bin/workflow-state` path when the bare name does not resolve. Pass `action_id`, which changes on each relaunch, through verbatim.

With lifecycle identity, run each long command, every verification command included, as `launch-scope exec --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id> -- <argv>`, still in the foreground; a forge verb never goes through it. Create every scratch directory or scratch worktree under the path that `launch-scope scratch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>` prints.

Every lifecycle call is one command that reads its input from stdin through a quoted heredoc (`<<'EOF'`): `--request-file -`, `--checkpoint-file -`, `--summary-file -` or `--input -`, with the helper named bare or as `~/.agents/bin/workflow-state`, optionally piped into or out of `artifact-budget validate-report --input -`; no request or summary file is written. Pipe each `workflow-state` reply's raw bytes through `artifact-budget validate-report --boundary workflow-response --input -` before decoding it; `resume-pack` stdout is no workflow response, is never piped through `validate-report`, and stays untrusted until the resume pack's checks pass.

The ledger, not tracker or intent data, selects the next delivery stage: follow the returned `owner`, `delivery_remainder`, requirement, or terminal variant without manufacturing authority, a retry, or another permission ritual. Every delivery effect runs through ship-issue's `## Delivery loop`.

### Resume pack
A relaunched owner whose prompt carries a resume pack follows `resume-pack.md` before using it.

## The flow

```
0. Investigate        → summary + open questions (no files yet)
1. Worktree (skill)   → isolated workspace off origin/<integration-branch>
2. Brainstorm (skill) → <specification-directory>/<date>-<topic>-design.md
3. Grill (skill)      → spec refinements + context-doc / ADR updates
4. Plan (skill)       → <plan-directory>/<date>-<feature>.md
5. Standards review   → Codex plan review, native fallback, or self-grade
6. Execute (skill)    → subagent-driven-development
7. Ship (skill)       → ship-issue: PR, review, CI, merge, cleanup
```

**Checkpoints.** At every phase boundary, state the artifact produced and the next action. Continue when the user's existing explicit authorization covers that action and its target; a phase transition or fresh session neither erases that authorization nor implies literal `--auto`. Ask only for a concrete missing decision when scope or authority changes. An actual permission denial stops the denied action and is never routed around. With literal `--auto`, also apply `AUTO.md`'s lifecycle and decision-ledger rules.

## Decision ledger (artifact discipline)
Non-obvious decisions this flow makes instead of the user live in **one issue-level ledger table** in the spec, under a section named exactly `## Decision ledger` — format and rules in `decision-ledger.md` beside this file. Mandatory under `--auto`; expected interactively too.

## Risk lanes
Assigned per task at planning time (Phase 4), recorded in the plan's `## Task index`, and applied by `sdd` during execution:

- **mechanical** — deletion/renaming with **no** behavioral, configuration, interface, generated-output, or semantic-documentation effect; file and line counts never qualify a change on their own.
- **low-risk** — small semantic changes: bounded, locally-verifiable behavior changes, **excluding** anything touching concurrency, lifecycle, destructive operations, security, release, migration, or public contracts.
- **full** — everything else.

Mechanical and low-risk tasks get scoped (inline or reviewer-lite) verification; full-lane tasks get a full per-task review. The independent final two-axis review is mandatory for **every** lane.

## Skill-tool invocations
Sub-skills named here — `worktrees`, `design`, `grill-with-docs`, `writing-plans`, `doc-grounded-questions`, `codex-collaboration`, `sdd`, `ship-issue` — go through the `Skill` tool, never paraphrased from memory. `codex-collaboration` is Claude-only, so native Codex sessions take the Phase-5 native-reviewer path.

**Never hard-fail on a missing sibling** — run the phase inline: brainstorm as intent + requirements + ≥2 options; grill against the map's areas and `adr/` dirs; plan as numbered tasks with a verification gate each; execute task-by-task with the verify commands; ship per the Phase-7 fallback.

## Dispatch, phase-budget and attempt-budget rules
**Structured report-backs.** Every `Agent` dispatch states the applicable fixed JSON return schema; details live in budgeted worktree files. Prefer the tiered agent types over `general-purpose`.

**Leaf-agent clauses.** Every prompt this skill or a file beside it composes for an `Agent` dispatch carries these four clauses verbatim, as a paragraph of their own; a prompt built from `ship-handoff.md` already carries them:

> Launch any subagent by type only, never by name: a subagent cannot spawn a named teammate, and a named launch returns an error instead of work. Read an existing file before writing to it: overwriting content you have not read destroys work you cannot see. Run each long command, every verification command included, in the foreground with an explicit timeout above its expected duration. If the host moves one to the background anyway, wait for it in the same turn: never end your turn while a command or agent you started still runs. Never write an `until` or `while` loop around `sleep` to wait for something: if a wait is truly needed, run one bounded foreground `sleep N`, then check once.

**Writing workers.** With lifecycle identity, every agent this owner dispatches that may commit or write to the forge — a Phase 2–4 subagent that commits artifacts, sdd's writing agents (Phase 6) and the Phase-7 ship owner — is registered first:
`workflow-state register-worker --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`.
Its prompt carries the printed id as the single line
`Lifecycle worker: --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id>`,
followed by the sentences "Run each long command, every verification command included, as
`launch-scope exec --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- <argv>`,
still in the foreground." and "Create every scratch directory or scratch worktree under the path that
`launch-scope scratch --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id>` prints.", and it
creates every commit through `launch-commit`. Release it with `--event returned` when it returns. Never register the fresh delegated owner or the ledger-only bookkeeper. Stop a background worker you cannot wait for through the host's task-stop and release it with `--event stopped`; with no stop capability, wait for it to return. An owner that can neither wait nor stop returns without a terminal write and leaves recovery to the dispatcher.

**Self-reap.** With lifecycle identity, every exit that ends this owner's launch — the `handoff` action, the terminal return procedure and the suspension procedure — first releases every worker this owner registered, then runs `launch-scope reap --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>` with this owner's own `action_id`, and only then makes the exit write; when the ledger-only bookkeeper makes that write, the reap runs before the bookkeeper is dispatched. A reap that exits non-zero does not block the exit write: name its exit code and, when it printed a report, its `skipped` launches in this owner's result. A delegating owner does not reap: the fresh delegated owner reaps the adopted launch at its own exit.

**Interim child results.** A child's return that the host marks interim — it stopped with background work of its own still running, or its result may be interim — is not a completion: the child is still running. Re-engage that same child by its recorded agent identity: message it to wait for its own job inside its turn and then return its final report, and wait for that report within your turn. Never answer an interim result with a text-only reply, never suspend for it (it is not an `external` wait), and never dispatch a replacement or stop the child. A registered lifecycle worker stays registered under its existing worker id: an interim result is not its `returned` event, and re-engagement is not a resume, so it registers nothing new. If the message cannot be delivered or its reply cannot be awaited in your turn, the child is one you cannot wait for: follow from-issue's **Writing workers** route (task-stop, then release `--event stopped`), then this skill's ordinary handling of a lost child; that is the one case that may lead to a fresh dispatch. Only the child's final hand-back counts as its result.

**Artifact report boundary.** At every producer boundary, before the phase's `workflow-state progress` call, pipe the received stdout bytes unchanged through `artifact-budget validate-report --boundary producer --input -` before decoding JSON. For a non-null artifact, run `artifact-budget check --kind <reported-kind> --root <reported-path> --format json` yourself and compare the reported kind, path and all four metrics by integer value. Validator or checker exit 2, a missing or non-integer metric (booleans included), any mismatch, or `complete` with anything other than `within_budget` is a contract error and becomes `failed`; an accepted over-budget state follows only its producer's remediation and never advances. Retain only the root and compact metrics, never a member list or artifact contents.

**Executable phase gate.** With lifecycle identity, at every phase boundary from Phase 0 through Phase 7, call `workflow-state progress` with the completed phase, the observed turn count and context tokens when available (omit an unavailable `--turn-count` or `--context-tokens`; never fabricate usage), and truthful booleans for next-phase context need, artifact sufficiency and remainder self-containment. Use the defaults `--turn-ceiling 120 --context-ceiling 150000 --turn-headroom 2 --context-headroom 10000`, and obey the `action` of the validated `phase_gate` reply exactly, from the closed set `continue | fresh_start | handoff | delegate`:

1. **`continue`** — proceed in this conversation.
2. **`fresh_start`** — start a fresh conversation from committed artifacts; do not carry conversational state.
3. **`handoff`** — first release every worker this owner registered, then run `launch-scope reap --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`. Beneath `ledger_repo_root`, create only the run's non-symlink `handoffs/` directory if missing, never the destination leaf. Invoke `handoff` with a destination beneath `.superpowers/workflows/<run-id>/handoffs/`, repeat `workflow-state progress` with `--handoff-path <exact-path>` to finalize `handed_off` on the same attempt, persist the handoff, and stop. The relaunch comes only from the acquisition's own envelope (`control`'s returned `resume` envelope, or the persisted `direct-owner` owner envelope for a direct autonomous restart).
4. **`delegate`** —
<!-- agent-dispatch: id=from-issue-phase-delegate role=issue-owner model=opus effort=high -->
Agent(subagent_type="general-purpose", model="opus", effort="high") delegates the entire remainder to a fresh issue owner with the lifecycle envelope and artifact paths.
   Before dispatching it, run `workflow-state resume-pack --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>` with this owner's own `action_id` and, on exit 0, put its stdout in the prompt as a `Resume pack` paragraph.
   Exception — **ledger-only remainder**: when every content artifact is final and only `workflow-state` transitions plus verbatim result relay remain, delegate to the cheap bookkeeper instead:
<!-- agent-dispatch: id=from-issue-ledger-remainder role=bookkeeper model=haiku effort=low -->
Agent(subagent_type="mechanic", model="haiku", effort="low") executes the ledger-only remainder: the exact workflow-state commands and verbatim JSON relay, with no content judgment.
   Give it the exact commands, identities, and paths inline; it decides nothing and edits nothing.

On the direct-autonomous route, `rollover.md` replaces the generic Phase-5 delegation above and `delegated-owner.md` its Phase-6 and Phase-7 `delegate` gates; every other acquisition mode keeps the generic action semantics. Without lifecycle identity, apply the same action order locally with the 120-turn/150000-token ceilings and default interactive handoff behavior.

If `workflow-state progress` is rejected with `cannot record progress at or after attempt deadline` or `progress requires an active attempt`, do not retry it: release every worker this owner registered, run `launch-scope reap --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`, then print the canonical re-entry line `/from-issue <num> --auto` and stop, writing no `finish`, whether the rejection meant a suspension or the `stopped(stalled)` bound.

## Terminal return procedure
Use this one procedure for Phase-0 content stops, attempt budget stops, execution failure, and Phase-7 success whenever lifecycle identity exists. The terminal result is one `ship-summary/v2` bound to the exact current custody and contract digest: after Phase 7, the ship report's summary; for a stop before Phase 7, assemble `state: terminal_failed`, the owner object's `custody`, its `contract_digest` as `delivery_contract_digest`, the validated legacy `stopped` or `failed` row only as `historical_owner_result`, and empty delivery, authority, and reevaluation arrays. Validate the raw candidate with `artifact-budget validate-report --boundary ship-summary --input -` before decoding, and use only its canonical stdout as the summary bytes. Release every worker this owner registered, run `launch-scope reap --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`, and, after the `check-launch` fence of this owner's own `action_id`, feed those bytes on stdin to `workflow-state finish` in one command whose reply is validated before decoding:

```text
workflow-state finish --repo-root <ledger_repo_root> --run-id <run-id> --summary-file - <<'EOF' | artifact-budget validate-report --boundary workflow-response --input -
<canonical ship-summary/v2>
EOF
```

Only after that durable write succeeds, send those canonical bytes — the validated `finish` reply — unchanged to the caller. A `delivery_remainder` reply is relayed unchanged too; the next acquisition or control sweep launches it. A new run never uses the legacy `--issue/--attempt/--result-file` transport. The earlier direct-autonomous controller that delegated at the Phase-5 rollover does not run this procedure: its only terminal work is the validate-and-relay stop in `rollover.md`.

When acquisition returns a terminal replay (`kind: terminal`) rather than an owner, print that envelope's `reentry` field to the user verbatim on its own line before relaying the compact response unchanged; a replay writes no `finish`.

Failure to persist is a failure to finish: surface it and never report the issue as merged or completed. Without lifecycle identity, send the same compact schema directly.

## Suspension procedure
Suspend — do not finish — when an environmental interruption pauses the work rather than resolving it: an imminent quota or session limit, a repeated transport failure, a permission prompt only a human can approve, an external wait (never a child's interim result), or a context that cannot launch the agents a phase needs. A suspension consumes no attempt and needs no authorization phrase.

Release every worker this owner registered (the helper refuses with `live workers: <ids>` while one is live), run `launch-scope reap --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`, and then call:

```text
workflow-state suspend --repo-root <ledger_repo_root> --run-id <run-id> --issue <n> --attempt <k> --blocked-on <value> | artifact-budget validate-report --boundary workflow-response --input -
```

with `<value>` one of `usage_limit`, `transport`, `human_gate`, `external`, `agent_dispatch`, or sdd's `deadline` (the reaper alone owns `unknown`). A validated `kind: terminal` reply means the anti-zombie bound ended the attempt instead: handle it as the terminal replay in the terminal return procedure — print its `reentry`, relay it, and write no `finish` — and stop. Otherwise the reply is `kind: suspended`; print the canonical line as the final user-facing output:

```text
Suspended (blocked_on=<value>). Resume: <reentry from the envelope>
```

That line is the last thing you emit: make no `finish` call and emit no result JSON. Suspension is NOT a terminal return.

## Phase 0 — Investigate
Read `investigate.md` and follow it, running the lane triage below before posting the note (when the retained tracker capability is unsupported, skip the issue fetch and the PR pre-flight). With lifecycle identity, every Phase-0 early stop uses the terminal return procedure: a `terminal_failed` summary carrying the `stopped` or `failed` row through `workflow-state finish` before notifying the caller. **Mechanical-only shortcut:** declare `mechanical-only` only when the **entire** change fits the mechanical lane (§Risk lanes); Phase 5 then self-grades against `REVIEW-CONTRACT.md` and Phase 6 dispatches one mechanic+reviewer pair for the whole change. Every phase still runs; skip manufactured TDD framing.

**Lane triage.** Before the checkpoint, judge each light-lane signal `no`, `hit` or `doubt`, with one line of evidence: `contract_change` (a contract, schema or public interface changes), `concurrency_or_persistence` (concurrency, locking or persisted state), `open_design_questions` (a design question is open) and `criteria_shape` (`hit`: over four acceptance criteria, or one no deterministic code check verifies). Feed `{"signals": {<name>: {"value": ..., "evidence": ...}}, "paths": [<predicted repo-relative paths>]}` through a quoted heredoc to `lane-triage evaluate --repo-root <project.root> --input -`. Exit 0: record the input, its `{hits, lane, mode}` verdict and `ran: full (shadow)` (`ran: full (active route not yet available)` for `mode: active`) under the note's **Lane triage**; every attempt runs full. `light_lane_unsupported`: record "light lane unsupported". `invalid_input` or `resolver_refused`: fix the record and rerun, or stop; any other exit stops; every stop uses the terminal return procedure.

**CHECKPOINT** — Record the restatement and scope; every open question needs a disposition (an answer, "defer to brainstorm", or "agent-choose"). Apply the shared checkpoint rule; ask only for a disposition that existing authorization does not cover.

## Phase 1 — Worktree
Create the workspace before any spec/plan/grill commit lands; those commits go *in the worktree*, never on the integration branch. With a lifecycle envelope (dispatcher-owned, direct-autonomous or explicit durable), use its exact absolute `worktree`, never another path, and decide by what is there: **absent** from the filesystem and `git worktree list` → create it from `origin/<integration-branch>` at that exact path (through `worktrees` only if it accepts the exact path; otherwise `git worktree add -b <branch> <exact-envelope-path> origin/<integration-branch>`); **already a git worktree checked out on this issue's branch** → `cd` in and adopt it, never re-creating, moving or resetting it (Phase 0's inspection governs its contents); **anything else** → fail the attempt through the terminal return procedure, naming the envelope path and what was found, and remove nothing. A ledger-free interactive invocation follows `acquire-interactive.md`.

**CHECKPOINT** — Record the worktree path and base; in `--auto` log the base SHA in the investigation note. Apply the shared checkpoint rule.

## Phase 2 — Brainstorm
Invoke `design` for a design doc under the retained specifications directory, committed in the worktree. Resolve every Phase-0 carryover before opening a new question. A note's **Lane triage** record and verdict go verbatim into the spec's `## Triage` section.

**CHECKPOINT** — Record the spec path and approval source. Apply the shared checkpoint rule; existing authorization for autonomous design decisions suffices within its scope.

## Phase 3 — Grill
Invoke `grill-with-docs` on the spec; any ADRs and context-doc edits it produces commit in the worktree and ship when the PR merges.

**CHECKPOINT** — Record all doc updates and the refined spec. Apply the shared checkpoint rule.

## Phase 4 — Plan
Invoke `writing-plans` for a plan under the retained plans directory, committed in the worktree. The plan header carries a `## Task index` — one line per task: ID, title, files touched, and risk lane assigned here per §Risk lanes. The plan cites ledger rows by ID and appends new non-obvious plan-level decisions to the specification's ledger.

**Plan-prose ≠ code-prose.** Prose the plan dictates verbatim into the codebase (docstrings, comments, doc sentences, ADR clauses) must describe how the live code *will actually behave*; if you can't say precisely yet, write a TODO and let the execute phase rewrite it from the implemented code.

**CHECKPOINT** — Record the plan path and review state. Apply the shared checkpoint rule.

## Phase 5 — Standards review
Read `standards-review.md` and follow it, its caller input gate first on every route.

**CHECKPOINT** — Record that standards review is clean. Apply the shared checkpoint rule.

## Phase 6 — Execute
Invoke `sdd`: it reads the plan header, dispatches an implementer per task, and reviews each output by risk lane. With lifecycle identity, invoke it with this owner's `ledger_repo_root`, `run_id` and `action_id` as its lifecycle identity, so sdd's `### Lifecycle workers` registers each writing agent under this launch and records a progress marker after each completed task, and hand it the `deadline_at` this owner holds (a later `declare-lane` reply's value supersedes the acquired one).

If the plan is `mechanical-only`, use one mechanic plus one first-pass reviewer for the whole change. With lifecycle identity, register the mechanic the same way (`workflow-state register-worker` before dispatch, the `Lifecycle worker:` line in its prompt, release on return) and run `workflow-state mark-progress --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>` once before dispatching the mechanic and once after its change is committed; a refusal changes nothing and is not a suspension cause.

<!-- agent-dispatch: id=from-issue-mechanical-implementation role=mechanic model=sonnet effort=high -->
Agent(subagent_type="mechanic", model="sonnet", effort="high") executes the fully specified mechanical change.
<!-- agent-dispatch: id=from-issue-mechanical-review role=reviewer model=opus effort=high -->
Agent(subagent_type="reviewer", model="opus", effort="high") performs its first-pass review.

sdd returns only canonical JSON: pipe the received bytes through `artifact-budget validate-report --boundary sdd --input -` before decoding any field. Revalidate a `present` delivery-detail package with `artifact-budget check --kind review-package`; for `unpublished`, validate the named retained source with `artifact-budget validate-detail-input`, consume canonical stdout, keep the workspace and worktree, and fail without Phase 7. Only after these gates may sdd's `review_state` (`clean | residuals | unknown`), `head_sha`, `acceptance_state` and `report_path` construct the Phase-7 handoff; ship-issue's Phase-5 range selection takes `head_sha` as the final-review head only when `review_state` is `clean`.

**CHECKPOINT** — Record the implementation commit on the feature branch. Apply the shared checkpoint rule.

## Phase 7 — Ship

<!-- agent-dispatch: id=from-issue-ship-owner role=ship-owner model=opus effort=high -->
Agent(subagent_type="general-purpose", model="opus", effort="high") launches `ship-issue` as a fresh ship owner, not inline via `Skill`. By now this conversation carries every artifact of the flow; a fresh ~10k subagent returns one summary instead of ~100 turns over a 200–300k prefix.

Read `ship-handoff.md` for the exact subagent prompt (with lifecycle identity the `ship-handoff/v2` candidate; ledger-free the legacy handoff), the inline fallback when `ship-issue` is absent, and the `## Remainder owner prompt` this same site launches for a validated `delivery_remainder` object; the remainder owner writes its own `finish`, so relay its validated reply unchanged and skip the terminal write.

From-issue owns the terminal durable write: handle the ship report, and any Phase-6 execution failure or Phase-7 stopped/failed report, as `ship-handoff.md` § Ship report handling says.

## Notes
- Standing local-commit authorization covers spec, plan, doc, and fix commits where project policy or an explicit scoped user grant covers the concrete action, target, and effect; the same rule covers push, PR, merge, and cleanup. When neither source grants the action, suspend with `blocked_on=human_gate` and print the re-entry line. An actual permission or launch-guard denial stops the action and is never routed around.
- Append `Co-Authored-By` when retained `bindings.vcs.commit.co_authored_by` is true. **Never disable GPG signing defensively** — no `-c commit.gpgsign=false`, no `--no-gpg-sign`; surface signing failures.
- **PR bodies, comments, and subagent prompts use full URLs, not bare `#N`**; use retained `bindings.tracker.repo_slug`.
- If a phase reveals the previous one was wrong, back up to that phase and redo it.
