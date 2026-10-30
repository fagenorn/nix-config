# Takeover refuses a launch with live workers; a direct acquisition of an orchestrated issue names its resume command — issue 475

Design for https://github.com/fagenorn/nix-config/issues/475. Base: `9cb00414`
(`origin/main`). Approval source: autonomous (`--auto`), decision ledger. A bare
"Dn" cites this spec's ledger.

## Triage

Input: {"signals": {"contract_change": {"value": "hit", "evidence": "direct-owner refusal details and owner_unavailable takeover semantics are part of the workflow-state CLI contract"}, "concurrency_or_persistence": {"value": "hit", "evidence": "takeover decides custody of a live attempt in the persisted ledger; live workers and progress markers are persisted state"}, "open_design_questions": {"value": "hit", "evidence": "workers carry no heartbeat today (mark-progress marks the attempt), and direct-owner does not enumerate orchestrated runs; how to detect both is open"}, "criteria_shape": {"value": "no", "evidence": "four acceptance criteria, each verified by a named test file or just agent-workflow-tests"}}, "paths": ["home/common/agent-skills/scripts/workflow-state.py", "home/common/agent-skills/scripts/workflow_delivery.py", "python/agent_tools/attempt_store.py", "home/common/agent-skills/tests/test_workflow_state.py", "home/common/agent-skills/tests/test_workflow_skill_contracts.py", "home/common/agent-skills/skills/from-issue/acquire-direct.md", "home/common/claude-code/skills/orchestrate-issues/SKILL.md", "home/common/agent-skills/README.md"]}
Verdict: {"hits":["contract_change","concurrency_or_persistence","open_design_questions","risk_path"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

Two failures from the October 21–30 retro, both on the direct `/from-issue N --auto` route.

1. **A takeover clobbered a live nested owner.** A top-level owner died on a 502 and
   stayed live in the ledger. The user authorized a takeover (`owner_unavailable: true`
   on `workflow-state direct-owner`), and the helper started a new launch. A nested
   implementation owner, registered as a worker of the old launch and still running,
   was fenced out mid-work. `direct-owner` judges a takeover on the top launch alone.
   It is exempt from the live-worker fence by design, because it is the recovery path
   for a run whose owner died with live workers (#222 D4).
2. **A suspended orchestrated issue was resumed the wrong way.** An issue suspended
   inside an orchestrated run was relaunched with a standalone `/from-issue N --auto`.
   The relaunch did not resume the orchestrated attempt, and nothing said how to.
   `direct-owner` finds only direct runs, through the `direct:<issue>:<sequence>`
   index entries. No index key leads from an issue to an orchestrated run. The
   orchestrate-issues final report makes this worse: for an issue suspended on
   `human_gate`, `external` or `agent_dispatch`, its re-entry line is that same
   `/from-issue <issue> --auto`.

The user wants both refusals to explain themselves. A takeover that would fence a live
worker names that worker. A direct acquisition of an orchestrated issue prints the exact
`orchestrate-control start … --run-id <id>` command that resumes it.

## Solution

- **Takeover refusal.** `direct-owner` with `owner_unavailable: true` refuses before
  its policy runs when the run has a live worker whose launch's record is still inside
  its deadline. "Live" is the existing worker verdict: registered, not released, and
  its launch current. The refusal lists every such worker. Two existing routes still
  recover a run whose workers died: once the deadline passes, the expiry reap
  supersedes the takeover, and a user who confirms a worker is gone can release it
  with `release-worker --event stopped` (per D1, D2, D4).
- **Orchestrated-hold refusal.** When an orchestrated run holds an issue,
  `direct-owner` refuses before it writes anything. The refusal names the run and the
  `orchestrate-control start` command that re-enters that run for that issue. An
  orchestrated run is found through new *issue hold pointers* in the core's
  creation-key index, never by listing `workflows` (per D5–D8).
- **Re-entry lines.** The orchestrate-issues final report's per-issue re-entry line
  becomes that same `orchestrate-control start … --run-id` command. The from-issue
  direct-acquisition guidance tells the owner to relay either refusal verbatim and
  stop (per D9, D10).

## Decisions

### Live worker for takeover (per D1, D2)

A worker blocks a takeover when all of these hold at the request's `now`:

- `worker_verdict` reads it as `live`: registered, `released_at` null, and its launch
  the current launch of its record;
- that record (the attempt or delivery remainder its launch belongs to) has
  `deadline_at` strictly after `now`.

`mark-progress` is not consulted and gets no new field. A worker is live from
registration to release, and a heartbeat inside the deadline adds no evidence beyond
that. `mark-progress` names a launch, not a worker, and stores no time (#310 D3). The
issue's "a `mark-progress` heartbeat within its bound" is read in `mark-progress`'s own
vocabulary, where a launch's bound is its deadline ("a remainder launch keeps its own
bound").

One pure predicate, taking the ledger, the runtime and `now`, returns the blocking
worker ids in ledger order. `command_direct_owner` calls it once, in this order:

1. after the existing `owner_unavailable is not applicable` checks;
2. on the selected nonterminal run's current state;
3. only when `owner_unavailable` is true;
4. before `_apply_one_issue_policy` runs.

The predicate covers attempt and remainder launches alike, because a direct run holds
one issue and every live worker of it belongs to that issue's current launch. Past the
deadline the predicate is empty. The existing #310 D18 path then supersedes
`owner_unavailable` with the expiry reap, and that reap ends the launch and fences its
workers.

`fence_owner_exit`'s docstring and the README's launch-fenced-writers paragraph are
corrected. Within the deadline, `direct-owner` is no longer an unconditional recovery
path. `control` and the deadline reaper stay exempt (out of scope).

### Refusal R1: takeover with live workers (per D3)

```text
workflow-state: owner_unavailable refused: live workers: <worker_id>[, <worker_id>…]
```

The refusal exits 2 with empty stdout. The ledger's attempts, launches, workers and
custody stay unchanged. As with every other `direct-owner` refusal, a pending legacy
bind of the retained ledgers may already have committed. Worker ids are joined by `, `,
the separator `fence_owner_exit`'s `live workers:` refusal already uses.

### Dead-worker recovery (per D4)

R1 leaves exactly two routes. Neither is new:

- **Wait for the deadline.** A plain re-entry (`owner_unavailable: false`) reaps the
  expired attempt, then resumes it.
- **Release a worker the user confirms is gone.** Run `workflow-state release-worker
  --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> --event
  stopped`, then retry the takeover.

The guidance states that only the user's explicit statement that the named worker is
gone authorizes the release. The self-answer pattern cannot grant it, the same rule
that already governs `owner_unavailable`.

### Issue hold pointers (per D5, D6)

A pointer is an inert core transaction, created the way run transactions are (same
creation arguments, under `store_lock`):

- creation key `issue-hold/v1:<issue>:<k>` for `k` from 1;
- closed subject `{"schema": "issue-hold/v1", "issue": <int>, "run": "<run transaction id>"}`.

The grammar, subject validator and key builder live beside the run grammar in
`agent_tools.attempt_identity`. The probe and the mint live in
`agent_tools.attempt_store`.

- **Write.** The settle step that every locked ledger write already runs ensures the
  pointers, inside the store lock it takes for custody. For a run whose identity is
  `orchestrated`, each issue whose latest attempt or latest delivery remainder is
  `active`, `handed_off` or `suspended` must have a pointer naming the run's
  `transaction_id`. The ensure probes `k` from 1 to the first miss. It creates at the
  miss unless an earlier `k` already names this run. Its lock-free read phase plans
  nothing when every pointer exists, so a settle with nothing else to do still
  creates no store. Direct runs get no pointer, because the direct index already finds
  them. Pointers are never removed. Whether a run still holds an issue is judged from
  its ledger at read time (D7).
- **Existing runs** gain their pointers on their next locked write. That can be any
  `workflow-state` write, such as a control sweep from `orchestrate-control start
  --run-id`. There is no schema bump and no new `migrate` row. An older helper never
  reads or writes pointers, so on a mixed host a run it writes may go unfound. That is
  today's behavior, and the README documents it.
- **Read.** A lock-free probe yields, for one issue, the run handle each pointer names,
  in `k` order. The handle is `run_handle` of the subject's `run`. A pointer whose
  subject violates the grammar is a `StoreRefused`, as a non-run direct index entry is.

### Orchestrated hold and refusal R2 (per D7, D8)

`command_direct_owner` runs the hold check right after the first
`refuse_unmigrated_direct`. That is before `ensure_workflows_directory`, the issue
lock, any bind or mint, and regardless of `new_run`, `owner_unavailable` or the state
of any direct run. The check works through the pointers in order:

1. Read the named run's `workflows/<handle>/state.json` by its id, unlocked and
   validated in its upgraded shape, as `read_state_unlocked(..., upgraded=True)` does:
   a migration cut before its publish can leave a pointer naming a ledger still stored
   at its legacy schema. An absent ledger, or a ledger without the
   issue, does not hold it.
2. A validation failure fails loudly with the reader's own error. An unknown hold is
   not assumed free.
3. The first run whose issue entry's latest attempt or latest remainder is `active`,
   `handed_off` or `suspended`, and whose delivery of the issue is not complete, holds
   the issue. The check then refuses:

```text
workflow-state: issue <N> is held by orchestrated run <run-id>; resume it through orchestrate-issues: orchestrate-control start --repo-root <ledger_repo_root> <N> --run-id <run-id>
```

`<ledger_repo_root>` is the resolved repository root that `direct-owner` already
derives from its absolute `--repo-root`. `<run-id>` is the run's handle. The refusal
exits 2 with empty stdout and writes nothing: no workflows directory, no direct run
mint, no issue lock file. The `orchestrate-control start … <N> --run-id <run-id>` text
has one home, a function in `workflow-state`. R2 calls it, and the skill-contract test
renders it with placeholders (D10).

Re-entering with only `<N>` is the minimal resume. Because the issue is named
explicitly, the sweep is `human_directed`, so the first sweep clears a `human_gate`,
`external` or `agent_dispatch` suspension (issue 458 D4). The run's other issues are
untouched.

R2 has no bypass. `new_run` and `owner_unavailable` do not lift it. A user who wants to
leave an orchestrated run does so from inside it: re-enter the run, and its owner or
control ends the attempt. After that the issue is free for a direct run.

Pointers are safe for older helpers. No store-wide reader enumerates transactions:
the core lists only receipt directories, and `launch-scope` lists only its own launch
directories. An older helper therefore never meets a pointer subject.

### Guidance text (per D9)

- **`from-issue/acquire-direct.md`.** A new paragraph covers the two refusals. On a
  `direct-owner` stderr line that starts `workflow-state: owner_unavailable refused:
  live workers:` or contains ` is held by orchestrated run `, the owner relays the
  line verbatim as its final report and stops. It never retries with
  `owner_unavailable` or `new_run`, and it never releases a worker unless the user
  explicitly says that worker is gone (D4). The existing loud-failure rule stays the
  default for every other helper error.
- **`orchestrate-issues/SKILL.md`, final report.** For an issue suspended on
  `human_gate`, `external` or `agent_dispatch`, the re-entry line becomes
  `orchestrate-control start --repo-root <ledger_repo_root> <issue> --run-id <run-id>`,
  the §1 re-entry form narrowed to that issue. One sentence states that a standalone
  `/from-issue` for an issue the run still holds is refused with that same command.
  The orchestrate re-invocation for the whole run is unchanged.
- **`home/common/agent-skills/README.md`.** The launch-fenced-writers paragraph gets
  the R1 rule and the narrowed exemption. "Run identity and migrate" gets the hold
  pointers, R2 and the next-write binding. `python/README.md` is touched only where it
  already documents `attempt_store` index keys.

## Test seams

- **CLI seam: `workflow-state direct-owner` in a subprocess.** This is the existing
  pattern in `test_workflow_state.py` and `test_control_cutover.py`. Assertions cover
  stdout and stderr bytes, the exit code, and ledger and store state before and after.
- **R1 cases in `test_workflow_state.py`:**
  - Positive: an active direct attempt, `register-worker` under its launch,
    `mark-progress` (baseline), then `owner_unavailable: true` before the deadline.
    The result is exit 2, the exact R1 line naming the worker, and unchanged ledger
    bytes. This fails today, because the takeover proceeds.
  - The same with the worker released (`returned`): the takeover proceeds with a new
    launch.
  - The same past the deadline: the expiry path proceeds, as today.
- **R1 predicate unit test.** A state with a live worker under a current remainder
  launch is blocking. A worker under a superseded launch is not.
- **R2 cases in `test_workflow_state.py`:**
  - Positive: the existing orchestrated fixtures (`init-run --issue-set`, a `control`
    sweep that spawns the issue, then suspension), then `direct-owner` for that issue.
    The result is exit 2 and the exact R2 line with the run's handle and the resolved
    root. No `direct:<N>:1` index entry exists, and the workflows tree is unchanged.
  - The same issue after the orchestrated attempt is terminal: `direct-owner` proceeds.
- **Pointer seam in `agent_tools.attempt_store`.** Two locked writes of one
  orchestrated run leave exactly one pointer for the issue. A second orchestrated run
  holding the same issue takes `k = 2`. A direct run writes none. A no-op settle
  creates no store.
- **Regression.** `test_control_cutover.py`'s AC1 tests stay green unmodified: the
  unlistable-`workflows` script and the stray and copied directories. This proves the
  hold check never lists `workflows`.
- **Skill-contract seam in `test_workflow_skill_contracts.py`.** This follows the
  existing machine-text tables (#291 D6):
  - `ORCHESTRATE_MACHINE_TEXT[ORCHESTRATE]` gains the re-entry argv. A test asserts
    that argv equals the `workflow-state` resume function rendered with the
    placeholders `<ledger_repo_root>`, `<issue>` and `<run-id>`.
  - `ACQUIRE_DIRECT` must carry the two refusal markers that the owner branches on.
  - `ORCHESTRATE` must no longer carry `/from-issue <issue> --auto`.

| Acceptance criterion | Falsifiable check |
|---|---|
| owner_unavailable takeover with a live child worker refused, naming it | R1 positive case: exit 2, stderr equals the R1 line with the registered worker id, ledger bytes unchanged |
| direct acquisition of an orchestrated-held issue refused with run id and `orchestrate-control start --run-id` | R2 positive case: exit 2, stderr equals the R2 line with the handle and resolved root; no direct mint |
| from-issue acquisition guidance and orchestrate-issues re-entry describe both | skill-contract cases above |
| `just agent-workflow-tests` passes | the recipe, run under `launch-scope exec` |

## Out of scope

- Dead-owner detection without a terminal write (https://github.com/fagenorn/nix-config/issues/468).
- `control`'s `owner_unavailable` handling and the deadline reaper. They keep
  bypassing the worker fence, so an orchestrated takeover can still fence a live
  worker. That is a follow-up candidate, not this issue.
- A per-worker heartbeat field, a stall window for direct runs, and any ledger schema
  change.
- `control` refusing an issue held by a direct run, which is the reverse direction.
- Closing the race where `direct-owner`'s lock-free hold check runs concurrently with
  an orchestrator's first spawn of the same issue.
- Changing the `suspend` reply's `reentry` or `reentry_command`, and the host-route
  `alternative` line.
- A `migrate` row for pointers, and any new CLI verb or flag.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | A worker blocks a takeover when `worker_verdict` reads it `live` and its launch's record is before `deadline_at`. The deadline is the "bound". `mark-progress` is not consulted. | `mark-progress` names a launch, not a worker, and stores no time (#310 D3). Its own text calls a launch's deadline its bound. Registration liveness is the #222 worker model. | A per-worker heartbeat stamped by `mark-progress --worker-id`: a ledger schema bump and a new flag on every caller. A stall window: no bound is configured for direct runs (`stall_minutes` is orchestration-only and optional). |
| D2 | R1 is checked only in `direct-owner`, after applicability and before policy, over every live worker of the run (attempt or remainder launches). This narrows #222 D4's exemption for direct-owner takeover within the deadline. `control` and the reaper stay exempt. | Issue scope ("the two refusals in workflow-state direct-owner"). #222 D4 feared a deadlock, but the expiry reap still recovers once the deadline passes (#310 D18). A direct run holds one issue. | A check inside the shared `_apply_one_issue_policy`: it would change control's takeover path, which is out of scope. An attempt-only check: a special case for no gain, since the ship owner is a registered worker too. |
| D3 | R1 text is `owner_unavailable refused: live workers: <ids>`, joined by `, `, exit 2, no ledger change. | The `fence_owner_exit` refusal `live workers: <ids>`. WorkflowError's `workflow-state: ` prefix. | A JSON refusal reply: `direct-owner`'s closed response kinds would grow. Naming only the first worker: hides the others the user must check. |
| D4 | A dead worker is recovered by waiting for the deadline or by a user-confirmed `release-worker --event stopped`. The self-answer pattern cannot grant the release. | Existing verbs. The acquire-direct rule that only explicit user instruction grants `owner_unavailable`. | A `--force` takeover flag: a new authorization surface. Auto-releasing silent workers: dead-worker detection is https://github.com/fagenorn/nix-config/issues/468's domain. |
| D5 | An orchestrated holder is found through issue hold pointers: inert core transactions under `issue-hold/v1:<issue>:<k>` whose closed subject names the run transaction. | Lookup goes through the core creation-key index and never lists `workflows` (#117, #337 D2, #339 D9–D11). #339's AC1 test runs `direct-owner` over an unlistable `workflows`. | Listing `workflows` (breaks #339 AC1, reverses #337 D2). Lease records (cleared on release, so a suspended attempt has no holder). Delivery keys (need a contract digest `direct-owner` cannot know). Directory-name inference (#117). A pointer is issue→run membership, not the second run identity #339 D11 rejected. |
| D6 | The settle step ensures the pointers, state-based, for orchestrated runs whose issue's latest record is nonterminal. Existing runs are bound at their next write. No schema bump, no `migrate` row, never removed. | #339 D7: the bind is "the ordinary settle step", state-based and repeatable. Settle already holds the store lock for custody. | Writing only at `control` spawn: misses runs written by other verbs and never repairs. Minting at `init-run`: misses legacy and creation-key runs and the issues added later. A schema bump: pointers are not ledger fields, and an older helper ignoring them only reproduces today's behavior. |
| D7 | Held means the latest attempt or latest remainder is `active`, `handed_off` or `suspended`, read from the named run's validated ledger. For R2, an issue whose delivery is complete is not held, whatever state the record that finished it keeps: nothing is left to resume. The first holder in `k` order is named. An invalid ledger fails loudly. | The live clause of `issue_set_reusable`. The bar: fail loud, truthful states. | Any ledger entry counts (an issue the run never started holds no worktree or custody). Skipping invalid ledgers (a muted error that fails open). |
| D8 | R2 runs before anything is created, regardless of flags or direct-run state, and has no bypass. Its text names the run and `orchestrate-control start --repo-root <root> <N> --run-id <run-id>`. | The `unmigrated direct run: run workflow-state migrate --apply` precedent of a remedy inside the refusal. The issue's demo. §1 of orchestrate-issues re-enters with `<numbers> --run-id`. An orchestrated attempt is ended only from its own run. | Naming the run's whole issue set (re-sweeps issues the user did not ask for). `/orchestrate-issues …` text in place of the argv (the AC names the `orchestrate-control start --run-id` command). Letting `new_run` or `owner_unavailable` bypass R2 (that recreates the duplicate-run failure this issue fixes). |
| D9 | The orchestrate-issues final report's human-gated re-entry line becomes the R2 command form. The `suspend` reply's `reentry` stays `/from-issue N --auto`. | After R2, `/from-issue` for a held issue is a dead end. A named re-entry is `human_directed` (issue 458 D4). The dispatcher, not a human, classifies `suspend`'s owner return line. | Changing `reentry_command` for orchestrated runs: alters the owner-return contract the dispatcher classifies, for no user-facing gain now that R2 teaches the command. |
| D10 | Skill-contract tests pin the re-entry argv, derived from the helper's single resume function, and the two refusal markers in acquire-direct, which the owner branches on. | docs/standards/agent-helpers.md rule 6 (pin only machine-consumed text). The #291 D6 machine-text tables. The-bar DRY. | Pinning guidance sentences (rule 6 forbids). A literal argv in both test and helper with no derivation (two homes). |
| D11 | Pointers are ensured by their own `attempt_store.settle_holds`, which `commit_state` calls after `settle_custody` and `settle_delivery` and before the ledger is published. It has its own lock-free probe and takes the store lock only when a pointer is missing, then probes again under it. Its store seam is tested in `tests/test_attempt_identity.py`. Refines D6's "inside the store lock it takes for custody". | The `settle_delivery` precedent (#339): its own read phase and store lock, and a write cut before the publish leaves entries no reader consults. A custody refusal must stay write-free, as the existing refused-write tests require. A same-key create with another subject is a `CreationConflict`, so the slot is decided again under the lock. `tests/test_attempt_identity.py` already runs in the recipe. | Folding the pointers into `settle_custody`: it couples them to the custody plans and the seal-only shortcut. A new test file: it needs a new `justfile` recipe row for no gain. |
| D12 | "Held" has one home, `attempt_custody.holds_issue`: the latest attempt or the latest remainder is in `LIVE_STATES`. `settle_holds`, the R2 check and `issue_set_reusable`'s live clause all call it. The R2 check alone also requires that the issue's delivery is not complete (D7); the other two callers keep the bare rule. | The-bar DRY. D7 cites `issue_set_reusable`'s live clause as the same rule. `LIVE_STATES` already lives in `attempt_custody`. | A copy in each caller: three homes for one rule. |
| D13 | The resume argv and the two refusal texts are module-level string literals in `workflow-state`: `ORCHESTRATED_RESUME`, `TAKEOVER_REFUSAL` and `HOLD_REFUSAL`. The code formats them. The skill-contract test reads them by AST through `module_constants`, and checks that the acquire-direct markers are substrings of them. Refines D10's "function". | Issue 473 D11: `test_workflow_skill_contracts.py` imports nothing from `agent_tools`, because the installed tier runs it with no `PYTHONPATH`. Its `module_constants` AST reader is the precedent. | Loading `workflow-state.py` in the contract test (needs `agent_tools` on the path). Literal markers in the test with no link to the helper (two homes). |
| D14 | The skill-text edits fit the current instruction-budget ceilings by cutting bytes in the same document: at most +174 bytes in `acquire-direct.md` (from-issue-controller) and +41 bytes in `orchestrate-issues/SKILL.md` (orchestration-dispatcher). The acquire-direct rule is one sentence that names the markers without the `workflow-state: ` prefix and does not repeat the `release-worker` argv. | Only the user applies `instruction-budget-raise`, and `Instruction Budget` is a required check on `main`. Those two ceilings had 174 and 41 bytes of headroom at base `9cb00414`. | Raising either ceiling: that needs the user's label, which an `--auto` run cannot get. Spelling out the full refusal prefix and the release argv: that exceeds the headroom. |
| D15 | Standards review: `orchestrated_resume_command` shell-quotes each value (`shlex.quote`) while `ORCHESTRATED_RESUME` stays the unquoted template; the R1 predicate test uses distinct attempt and remainder deadlines on a realistic remainder; R2 tests pin traversal past a stale or absent first pointer and the first of two live holders. | Codex plan review PR475-01 to 03: an unquoted `--repo-root` splits a path with spaces, which `resolve_repo_root` accepts; a shared deadline and one-pointer cases let a wrong deadline or an early return pass. | Leaving the argv unquoted (the printed resume command breaks for supported roots); keeping one-pointer tests (D7's first-holder rule would be untested). |
