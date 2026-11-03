# Owner relaunches carry a compact resume pack, issue 265

## Problem

An issue owner is relaunched often: the mandatory direct-autonomous Phase-5
rollover hands implementation to a fresh owner, a deadline or usage-limit
suspension is resumed by `control` or by `/from-issue <num> --auto`, and a
transport failure is resumed the same way. Every relaunched owner starts with
nothing but its lifecycle envelope, so it re-orients by hand: it re-reads the
from-issue and AUTO skills and their companion files, dumps the ledger, runs
`git log`/`git show --stat`, finds and reads the SDD progress log, re-reads the
SDD skill and re-validates the plan. A relaunch spends a median of about 20
tool calls and 3M tokens before it does any new work, and it repeats that cost
on every relaunch of a long Phase 6.

Everything it reconstructs is already durable: the ledger holds the attempt,
the worktree holds the commits, and SDD's workspace holds the task ledger. What
is missing is one bounded, helper-derived summary of it.

## Solution

A new read-only lifecycle verb, `workflow-state resume-pack`, emits a **resume
pack** for one launch of one attempt: one canonical JSON object derived only
from the ledger, the attempt's recorded worktree and that worktree's SDD
workspace. Nobody composes it by hand.

Whoever relaunches an owner calls the verb with the relaunched launch's
`action_id` and puts its stdout in the relaunch prompt, beside the existing
envelope and owner object. The relaunched owner still resolves the project
once and still validates its launch identity with `check-launch`; it then
trusts the pack, re-reads only the shared owner sections and the skill
sections for the pack's current phase (per D17), and starts from the pack's `next_action`. The pack is an accelerator, never a
gate: when the verb refuses, or the pack disagrees with what the owner can see,
the owner falls back to today's full re-orientation.

## Decisions

### The verb

`workflow-state resume-pack --repo-root <ledger_repo_root> --run-id <run-id> --action-id <issue:attempt:launch>`

It is read-only in the same sense as `check-launch`: no clock, no lock, no
`transact`, nothing created under `.superpowers/`. It reads the ledger with the
unlocked reader, then reads git in the recorded worktree with read-only
commands (no optional index locks), then reads files in the SDD workspace. It
prints the pack on stdout and exits 0, or prints one `workflow-state:` stderr
line and exits 2.

**Which launches get a pack** (per D3). The action id must name the latest
launch of the issue's latest attempt, and that attempt must be resumable work:

| Latest attempt state | Requirement | `current` in the pack |
|---|---|---|
| `active` | `launch_verdict` answers `current` | `true` |
| `suspended`, `handed_off` | the id's launch ordinal is the attempt's last launch | `false` |

Everything else is refused: a malformed id, a remainder id (`:r`), an unknown
run, issue or attempt, a superseded attempt or launch, an attempt in a terminal
state (`stopped`, `failed`, `merged`) and an active attempt whose delivery is
complete. A refusal names the `launch_verdict` reason when one applies. A
suspended or handed-off pack is a preview keyed by the last launch the attempt
had; a relaunch prompt always carries the pack minted for the launch that
`control` or `direct-owner` has just appended, which is `active` and current.

A recorded worktree git cannot read (missing, not a worktree top level, no
branch checked out) is refused with the same reason clauses `mark-progress`
uses: a relaunch into it cannot proceed anyway.

### The pack (closed shape, `resume-pack/v1`)

```json
{
  "kind": "resume_pack", "version": 1,
  "run_id": "run-…", "issue": 265, "attempt": 1, "action_id": "265:1:3",
  "current": true,
  "ledger": {"state": "active", "phase": 5, "launch_kind": "resume",
              "launches": 3, "deadline_at": "…Z", "blocked_on": null,
              "handoff_path": null, "progress_marker": "<40-hex>|null"},
  "worktree": {"path": "/abs/.worktrees/…", "branch": "worktree-issue-265-…",
               "head": "<40-hex>", "dirty_paths": 0},
  "commits_since_marker": {"base": "<40-hex>|null", "relation": "none|same|ahead|diverged",
                           "count": 2, "commits": [{"sha": "<12-hex>", "subject": "…"}],
                           "truncated": false},
  "sdd": null,
  "next_action": {"kind": "start_phase", "phase": 6}
}
```

- `attempt.phase` is the last phase whose gate `progress` recorded, as the
  ledger stores it; the pack does not reinterpret it.
- **Last checkpoint is the progress marker** (per D4). `relation` is `none`
  when no marker is recorded (then `base` is null and no commits are listed),
  `same` when HEAD is the marker, `ahead` when HEAD strictly descends from it
  (commits listed newest first; `count` is the full range's length even
  when the list is cut) and `diverged` otherwise (no commits listed:
  the range is not a history of this attempt). Ancestry comes from the same
  probe `mark-progress` uses.
- `dirty_paths` counts `git status --porcelain` entries: an owner killed
  mid-task can leave uncommitted work, and the relaunched owner must see that
  before it trusts `head`.
- `sdd` is null or `{"workspace", "plan", "task_count", "completed",
  "last_entry", "last_entry_truncated"}` (below).
- **Size is capped, then enforced in bytes** (per D7, D15): at most 20
  commits, subjects cut to 100 characters, `last_entry` cut to 400
  characters, `completed` capped at 32 numbers. On top of those caps, the
  bytes the verb writes (the ASCII-escaped JSON plus newline, where one
  non-ASCII character can cost 6 bytes and every path counts in full) are
  always fewer than 4096. While they are not, the verb sheds the oldest listed
  commit, then the last character of `last_entry`, then the last ambiguous
  plan name, each marked (`truncated`, `last_entry_truncated`,
  `ambiguous_count`); if paths alone still exceed the bound it refuses with
  `the pack exceeds 4096 bytes`. No free text from the ledger beyond these
  fields is copied.

### SDD position

The pack reads the workspace SDD itself would use for this worktree (per D5):
`<primary-checkout>/.superpowers/sdd/<bucket>/`, with the primary checkout and
the `primary` / `wt-<worktree-name>` bucket derived from the worktree's git dir
and common dir by the rule `sdd-workspace` documents. It considers each
`<plan-basename>/progress.md` directly under that bucket whose first line is
`# SDD ledger — plan: <plan path>`.

- No such ledger: `sdd` is null.
- Exactly one: `plan` is the path from that line, verbatim; `task_count` is the
  number of `task-<N>.md` members in the plan's sibling `<stem>.tasks/`
  directory (a relative plan path resolves against the worktree, an absolute
  one is used as is), or null when that directory is absent or holds no
  member (a count of zero is unknown, per D17); `completed` is the sorted task numbers that have a
  `Task <N>: complete` line; `last_entry` is the file's last non-empty line.
- Several: the pack cannot say which plan is current, so `sdd` carries only
  `{"ambiguous": [<plan-basename>, …], "ambiguous_count": <n>}` and
  `next_action` is `reorient`.

### Next action (closed vocabulary)

`next_action.kind` is exactly one of the following, chosen in this order (per D6):

1. `read_handoff` `{path}` — the attempt carries a `handoff_path` and its last
   recorded gate is that handoff (`phase_action` is `handoff`; `handoff_path` is
   never cleared, so the path alone would keep pointing at a spent handoff).
   The handoff document is the authoritative continuation; the pack only
   points at it.
2. `reorient` `{reason}` — the pack cannot vouch for the position: an ambiguous
   SDD workspace, or a `diverged` marker relation. The owner does today's full
   re-orientation.
3. `resume_task` `{phase: 6, task, mid_fix_loop}` — `attempt.phase` is 5, the
   SDD ledger exists, and some task in `1..task_count` lacks a `complete` line;
   `task` is the first such number (SDD's own resume rule) and `mid_fix_loop`
   says whether that task's last line is a fix round.
4. `finish_phase` `{phase: 6}` — `attempt.phase` is 5 and every task in
   `1..task_count` is complete: SDD's final gate and the Phase-6 gate remain.
5. `start_phase` `{phase}` — otherwise, the phase after `attempt.phase`;
   phase 0 itself while no gate is recorded (`phase_action` null, as spawned),
   since an attempt at phase 0 has not yet finished Phase 0 (per D17).

An unknown `task_count` (null) never yields `finish_phase`: with the plan's
size unknown the pack answers `resume_task` at the first missing number, which
is still SDD's own rule.

### Who puts the pack in the prompt

`control`'s and `direct-owner`'s envelopes are unchanged; the relauncher calls
the verb after them (per D2). The pack is optional on every route: a refusal
or helper failure means the prompt carries no pack, never that the relaunch
stops. The pack is not a workflow response: `artifact-budget validate-report
--boundary workflow-response` has no route for it, so the orchestrate-issues
and from-issue rule that every `workflow-state` reply is validated there gains
one explicit exception for `resume-pack` stdout, which is carried as an
untrusted accelerator and cross-checked by the owner instead (per D16).

- **orchestrate-issues §4, `resume` actions.** After projecting the owner
  object, the controller runs `resume-pack` with the action's `id` and adds a
  `Resume pack` paragraph carrying its stdout verbatim to the owner prompt.
  `spawn` and `retry` carry none (per D8).
- **from-issue direct autonomous re-entry.** When `direct-owner` returns an
  owner object whose `launch_kind` is `resume`, the owner runs `resume-pack`
  for that `action_id` itself and uses it in place of re-orientation: the
  re-entered session is its own relauncher.
- **from-issue Phase-5 rollover and generic `delegate`.** After `progress`
  persists `delegate`, the earlier owner runs `resume-pack` for its own
  `action_id` (the fresh owner adopts the same launch) and passes the pack
  beside the continuation object, never inside it: the continuation stays the
  closed object AUTO.md defines. Only the Phase-5 rollover owner, which carries
  that continuation, still runs AUTO.md's `#### Fresh delegated owner`
  reviewed-head and artifact-budget checks unchanged; a generic `delegate` has
  no continuation and runs none of them (per D17).

### What the relaunched owner does with it

A pack-carrying relaunch keeps every identity rule: resolve the project once,
validate the owner object, run `check-launch`, and obey a non-current answer
exactly as today. Then it checks two things the pack asserts: the pack's
`action_id` equals the envelope's, and `git -C <worktree> rev-parse HEAD`
equals `worktree.head` with `dirty_paths` as stated. A mismatch makes the pack
stale: the owner ignores it and re-orients in full.

Otherwise it trusts the pack, which replaces exactly the owner's own ad-hoc
re-orientation (per D16): it does not dump the ledger, re-read git history,
re-validate the plan, read the SDD progress log itself, or read skills end to
end. It reads the shared owner sections every owner obeys and the skill
sections for the pack's phase (per D17): from-issue's `## Lifecycle identity`,
`## Decision ledger (artifact discipline)`, `## Skill-tool invocations`,
`## Dispatch, phase-budget and attempt-budget rules`,
`## Terminal return procedure` and `## Suspension procedure`; SKILL.md's
`## Phase <n>` section and the file beside SKILL.md that phase names; under
`--auto`, AUTO.md's opening, `## The self-answer pattern`,
`## When *not* to auto-resolve` and the section governing that phase (in place
of reading AUTO.md whole); and the phase's sub-skill (`sdd` for Phase 6,
`ship-issue` for Phase 7). Every mechanism the pack does not replace still
runs: resolving the project once, owner-object validation, `check-launch`,
AUTO.md's `#### Fresh delegated owner` checks for an owner delegated at the
Phase-5 rollover (only that owner, which reads that section first), and sdd's own `progress.md` entry check, which stays sdd's
resume mechanism and wins over the pack's `resume_task` if they disagree.
`read_handoff` reads the handoff document; `reorient` re-orients in full.

## Test seams

- **The command, from source.** `test_workflow_state.py` drives
  `workflow-state resume-pack` as a subprocess against real temporary git
  repositories with a linked worktree and ledgers built the way the existing
  `mark-progress` and `check-launch` tests build them. Cases: an active current
  launch (pack shape, `current: true`, `ahead` commits since a recorded
  marker, SDD position and `resume_task`); a suspended attempt keyed by its
  last launch (`current: false`, `blocked_on`, unchanged work position); a
  non-current launch (a superseded launch ordinal, a superseded attempt and a
  terminal attempt) refused with exit 2 and empty stdout; the read-only
  property (the ledger file's bytes and the run directory listing unchanged);
  each `next_action` kind; the bucket rule agreeing with `sdd-workspace` for
  the same worktree; the caps; and the byte bound at its boundary with
  non-ASCII commit subjects, last entry and plan names on long non-ASCII
  paths, including a refusal when the paths alone cannot fit.
- **The skill contract.** `test_workflow_skill_contracts.py` pins that
  orchestrate-issues §4 runs `resume-pack` for `resume` actions and puts its
  stdout in the owner prompt; that from-issue's direct re-entry, Phase-5
  rollover and `delegate` routes carry the pack; that both skills' validate-every-reply
  rule names the `resume-pack` exception; and that from-issue's owner
  guidance on a pack-carrying relaunch still runs `resolve-project`,
  `check-launch` and sdd's own `progress.md` check, reads only the shared
  owner sections and the current phase's skill sections, and that the AUTO.md read-once line yields to it.

## Out of scope

- Any change to launch identity, `check-launch`/`current-launch`, the ledger
  schema, or the `control`/`direct-owner` envelopes.
- Packs for delivery remainders (`:r` launches), `spawn` and `retry` launches.
- Routing the pack through `artifact-budget validate-report` (a new
  workflow-response kind).
- Moving `workflow-state` into the `agent_tools` package.
- Measuring the token savings on a live run.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The verb lands in the legacy `workflow-state` script as pure pack-derivation functions plus a thin read-only command | agent-helpers: a legacy script meets the package rules when its cluster moves; #250 D10 precedent; the ledger reader and `launch_verdict` live there | A new `agent_tools` module and command row: it would need the ledger reader and launch verdict, duplicated or reached through a new read verb |
| D2 | The relauncher calls `resume-pack` after `control`/`direct-owner`; their envelopes do not embed it, and a missing pack never blocks a relaunch | Issue scope keeps launch identity and envelopes unchanged; control is a write path that should not read SDD workspaces; the-bar Token economy (one optional paragraph) | Embedding the pack in `control`'s `resume` action: changes a closed, validated envelope and puts git and workspace reads inside the locked transaction |
| D3 | Keyed by `--action-id`; served for the current launch of an active attempt, and as a `current: false` preview for the last launch of a suspended or handed-off attempt; everything else refused | Issue acceptance (active, suspended, non-current refused); `check-launch` grammar and `launch_verdict` | Keying by issue/attempt only: lets a stale relaunch fetch a pack for a launch it does not hold |
| D4 | "Last checkpoint" is the attempt's `progress_marker`; commits since it are listed only when HEAD strictly descends from it | #250: the marker is the durable, helper-read record of the last checkpointed commit | Branch fork point from the integration branch: needs project policy at read time and repeats every commit the owner already checkpointed |
| D5 | SDD position comes from the worktree's SDD bucket by `sdd-workspace`'s rule, mirrored and pinned by a test that runs `sdd-workspace` against the same worktree; several plan ledgers yield `reorient` | sdd SKILL workspace and progress-ledger format; the-bar Fail loud | Calling `sdd-workspace`: it needs the plan file first and creates the directory, so the verb would no longer be read-only |
| D6 | `next_action` is a closed five-kind set (`read_handoff`, `reorient`, `resume_task`, `finish_phase`, `start_phase`) chosen in a fixed order | the-bar Fail loud and Token economy; SDD's first-incomplete-task resume rule | Free-text guidance: unpinnable by tests and unbounded |
| D7 | Size bounded by construction (20 commits, 100-char subjects, 400-char last entry), not by a budget check | Issue: bound pack size; the-bar YAGNI | A new artifact-budget kind and validator boundary: a policy surface for a read-only advisory object |
| D8 | Only `resume` relaunches, direct re-entry, Phase-5 rollover and `delegate` carry a pack; `spawn` and `retry` do not | A spawn has nothing to resume; a retry is a new attempt at phase 0 whose pack would misdescribe the predecessor's commits | Packing every dispatch: adds a paragraph that is empty or misleading on two of the routes |
| D9 | The relaunched owner verifies the pack's `action_id` and worktree HEAD/dirtiness before trusting it, and re-orients in full on mismatch | the-bar Defense in depth; the shared-worktree retry model in CLAUDE.md | Blind trust: a pack minted before another writer moved HEAD would misplace the owner |
| D10 | Grill: no glossary or ADR writes; the decision lives in this ledger | `bindings.paths.context` is empty, so no documentation write route exists; the choice is reversible (one read-only verb plus prose) | An ADR: the change is neither hard to reverse nor a cross-cutting architecture choice |
| D11 | The pack's ledger-state object is keyed `ledger` (the example's nested `attempt` object collided with the top-level `attempt` ordinal; the prose's `attempt.phase` means `ledger.phase`); `ledger.progress_marker` and `commits_since_marker.base` carry the stored marker as is, 40 or 64 hex | A JSON object cannot carry one key twice; `PROGRESS_MARKER_PATTERN` admits both widths | Renaming the top-level ordinal: `attempt` is the envelope's own field name |
| D12 | Refusals print `workflow-state: resume-pack refused: <clause>` and exit 2: `launch <id> is <reason>` with the `launch_verdict` reason, except that an earlier launch of a suspended or handed-off latest attempt reports `superseded_launch`; a remainder id is `a remainder launch has no resume pack`; an unreadable worktree uses `mark-progress`'s clause; a workspace identity git cannot resolve, or a symlinked workspace component, is `the SDD workspace cannot be resolved` | `mark-progress` refusal form; `sdd-workspace` refuses links and unresolvable identities; the-bar Fail loud | `sdd: null` for an unresolvable workspace: the pack would claim no SDD progress over work that exists |
| D13 | `reorient.reason` is closed: `ambiguous_sdd_workspace`, then `diverged_marker`, then `delivery_phases_complete` (recorded phase 7 or later, where no next phase exists); bounds beyond D7: `sdd.ambiguous` lists at most 8 sorted basenames cut to 100 characters, and `completed` keeps the 32 lowest numbers | D6 closed vocabulary; the flow has phases 0-7; D7 | `start_phase` with phase 8: names a phase that does not exist |
| D14 | Owner guidance is a `### Resume pack` subsection closing from-issue SKILL.md's `## Lifecycle identity`; orchestrate-issues §4's owner prompt gains an optional `Resume pack` paragraph; AUTO.md's transfer gate and fresh-owner sections carry the pack beside the continuation; CLAUDE.md gains one bullet; hot-path instruction-load ceilings rise to the measured bytes | #250 Task 3 precedent (CLAUDE.md bullet, contract test, ceilings); `test_instruction_load.py` | A new file beside SKILL.md: one more load on the path whose cost the issue cuts |
| D15 | The 4096-byte bound is enforced on `render_json`'s output (ASCII-escaped JSON plus newline): shed oldest commits, then `last_entry` characters (`last_entry_truncated`), then trailing ambiguous names (`ambiguous_count`), and refuse `the pack exceeds 4096 bytes` when paths alone breach it; amends D7 and D12 | Plan review: character caps do not bound bytes, since `\u00e9`-style escapes cost 6 bytes per character and paths are uncapped | Raising the stated bound or switching to `ensure_ascii=False`: the first leaves it unenforced, the second edits the shared `render_json` wire form |
| D16 | `resume-pack` stdout is an explicit exception to the validate-every-`workflow-state`-reply rule in orchestrate-issues and from-issue; a verified pack replaces only the owner's ad-hoc re-orientation (ledger dumps, git history, plan re-validation, whole-skill and whole-AUTO.md reads), while `resolve-project`, owner-object validation, `check-launch`, the fresh-owner rollover checks and sdd's own `progress.md` check stay, sdd's ledger winning on disagreement | Plan review: the closed workflow-response validator rejects the pack, and unconditional read instructions (AUTO.md once, sdd's ledger check) left the precedence undefined | A `resume_pack` validator route (excluded by Out of scope); letting the pack override sdd's ledger: two resume authorities for one task list |
| D17 | `start_phase` is phase 0 while the attempt has no recorded gate (`phase_action` null, the spawn state; `progress` always stores a non-null action) and the phase after `attempt.phase` once one is; a pack-carrying owner always reads from-issue's shared owner sections (`## Lifecycle identity`, `## Decision ledger (artifact discipline)`, `## Skill-tool invocations`, `## Dispatch, phase-budget and attempt-budget rules`, `## Terminal return procedure`, `## Suspension procedure`) and, under `--auto`, AUTO.md's opening, `## The self-answer pattern`, `## When *not* to auto-resolve` and its route section; only an owner delegated at AUTO.md's Phase-5 rollover (carrying its continuation) runs the `#### Fresh delegated owner` checks, and it reads that section before the deferred AUTO.md read; an empty `<stem>.tasks/` is an unknown `task_count` (null) | Final-review findings C-001, C-002, the shared-sections conformance finding and the zero-member finding: `phase + 1` skipped an interrupted Phase 0; generic `delegate` has no `reviewed_head_sha` or measured artifacts; dispatch, suspension and terminal rules live outside `## Phase` sections; zero members made `finish_phase` reachable with no task done | Keeping `phase + 1` and storing a synthetic phase −1: a ledger schema change for a fact `phase_action` already carries; applying the rollover checks to every delegated owner: unsatisfiable for a generic `delegate`; a count of zero: finishes Phase 6 on an empty task directory |
