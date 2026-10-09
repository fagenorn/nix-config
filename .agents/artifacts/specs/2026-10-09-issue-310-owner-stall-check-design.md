# Owner stall check (#310)

orchestrate-issues frees the slot of an owner that went silent after an interim
notification, well before the attempt deadline. Every observer it arms sleeps
for a number of seconds the helper computed.

## Problem

An owner can end its turn while background work of its own is still running.
The host then sends an interim notification, and rule (a) of orchestrate-issues
says to do nothing: the same handle will notify again with the real return. In
one run the owner's background work was an `until` loop that could never exit
(zsh read `\>` inside `[ … ]` as a redirection). The second notification never
came. The owner held a dispatch slot for about 2.5 hours, and only the attempt
deadline would have freed it.

The adapter's wait observer has a second fault. Control returns only an absolute
`deadline_at`, so the adapter worked out the sleep with hand-written `date`
arithmetic. That arithmetic differs between BSD and GNU `date`, so the observer
can fire at once or fail to arm.

## Solution

1. **A stall bound in policy.** `bindings.workflow.orchestration.stall_minutes`
   is an optional positive integer. This repo sets it to 90 (D1).
2. **One read-only verb.** `workflow-state owner-liveness` answers whether one
   owner launch has recorded ledger progress within the bound, measured from a
   base time. When it has, the reply gives the whole seconds left until the
   owner would be stalled (D2–D5).
3. **Rule (a) arms a liveness check.** After an interim notification the adapter
   calls the verb and arms one one-shot liveness observer for that owner. When
   it wakes it asks once more. A `stalled` answer stops the owner's task and
   sends exactly one `unavailable` owner observation for its custody. A `live`
   answer re-arms the observer for the seconds the reply gives (D6–D8).
4. **Control computes the wait.** The `wait` action gains `wait_seconds`. The
   adapter's observer is one background `sleep <wait_seconds>`. No skill text
   does date arithmetic (D9).

## Decisions

### The setting

- `workflow.orchestration` accepts `stall_minutes` as an optional member, next
  to the two required ones. Present, it is a positive integer or `null`. Absent
  or `null` means the project has no stall check. In that case rule (a) behaves
  exactly as it does today, and the adapter never calls `owner-liveness`. No
  value is defaulted. This follows the `light_lane` precedent for an optional
  member (D1).
- `.agents/project.json` and the eval fixture repo's project file both set
  `stall_minutes: 90`.
- orchestrate-issues §1 maps the member next to `attempt_budget_minutes`. This
  paragraph is where the AC says the setting is documented. The adapter passes
  the setting only to `owner-liveness`. It is not added to the control request,
  because control's retry, resume and deadline policy does not change.

### `workflow-state owner-liveness`

Arguments: `--repo-root`, `--run-id`, `--action-id`, `--stall-minutes N`
(a positive integer, required), and `--since <UTC>` (optional).

- It is read-only: it takes no lock and makes no write. It reads the clock once,
  through `ledger_clock()`, the seam from #309. This is the one read-only verb
  that reads the clock. Its help text says so, the same way `build-delivery`
  states its contract-stamp exception (D2).
- **Base.** An omitted `--since` makes the base the clock's value. A supplied
  `--since` must be a UTC timestamp no more than 60 seconds ahead of the clock.
  Otherwise the verb refuses with exit 2. This is the same skew rule and
  refusal text as #309, labelled `--since`. The adapter never writes a time
  itself. It passes back, unchanged, the `since` value from an earlier reply
  (D4).
- **Launch.** The verb takes the launch verdict from `launch_verdict`, the same
  function `check-launch` uses, so it serves implementation launches and
  delivery-remainder launches alike. Any verdict other than `current` gives
  `verdict: not_current`.
- **Progress evidence.** For a current launch, `progress_at` is the latest of
  these ledger times (D3):
  - the record's `last_progress_at`, when the record has one;
  - this launch's own `at`;
  - `registered_at` and `released_at` of every worker whose `launch` is this
    action id.

  Times on other launches, the run's `updated_at`, and other owners' activity
  never count.
- **Verdict.** `stall_at = max(progress_at, since) + stall_minutes`. If the
  clock has reached the record's `deadline_at`, the verdict is `past_deadline`:
  the attempt deadline already governs the launch. Control's own wait wakes at
  that deadline and reaps it. An `unavailable` observation for an expired
  record is refused by control with `owner_unavailable is not applicable`
  (D10). Otherwise, if the clock is earlier than `stall_at`, the verdict is
  `live` and `wait_seconds = ceil(stall_at − clock)`, which is at least 1.
  Otherwise the verdict is `stalled`.
- **Reply.** One JSON line, exit 0:

  ```json
  {"interface_version": 1, "kind": "owner_liveness", "action_id": "<id>",
   "reason": "<launch_verdict reason>", "verdict": "live|stalled|past_deadline|not_current",
   "since": "<UTC>", "progress_at": "<UTC>|null", "stall_at": "<UTC>|null",
   "wait_seconds": <int ≥ 1>|null}
  ```

  `progress_at` and `stall_at` are null exactly when the verdict is
  `not_current`. `wait_seconds` is non-null exactly when the verdict is `live`.
  `reason` is `current` exactly when the verdict is not `not_current`.
- **Errors.** A malformed `--action-id`, run id, `--stall-minutes` or `--since`,
  or an unreadable ledger, exits 2 with one stderr line. A missing ledger is
  the `unknown_run` verdict, as in `check-launch`.
- **Validator.** The workflow-response boundary in the delivery model accepts
  this kind with its closed member set and the invariants above. It also
  checks that `stall_at` is later than both `progress_at` and `since` by the
  same whole number of minutes from whichever is later. It cannot check
  `wait_seconds` against the clock, so it checks only the range.

### Adapter behavior (rule (a) and the liveness observer)

- The adapter keeps, per owner handle, a `liveness_since` and a
  `liveness_handle`. Like the wait fields, these are process-local and never
  persisted. An adapter restart drops them, and the host reaps inherited
  observers as it does wait observers. The next interim notification arms the
  check afresh.
- **Interim notification** for an owner handle with no final return, when
  `stall_minutes` is set: run `owner-liveness` without `--since`, validate the
  reply at the workflow-response boundary, and store its `since` as
  `liveness_since`. A later interim notification for the same handle replaces
  `liveness_since` in the same way. If no liveness observer is installed for
  that handle and the verdict is `live`, arm one background
  `sleep <wait_seconds>` and record its handle. If an observer is already
  installed, keep it. Its wake uses the new base and re-arms (D7). Rule (a)
  still sends no observation, writes nothing to the ledger and relaunches
  nothing.
- **Liveness wake.** A completed liveness observer is classified by its handle.
  It is a fourth class of host notification, next to (a)–(c). If its owner
  handle already has a final return, or has been stopped, ignore the wake.
  Otherwise run `owner-liveness --since <liveness_since>` and act on the
  verdict:
  - `live`: arm a new observer for `wait_seconds`.
  - `not_current` or `past_deadline`: do nothing.
  - `stalled`: stop the owner's task through the host's task-stop and mark the
    handle stopped. Then send exactly one `unavailable` owner observation for
    that launch's custody in the next control call, and execute that response.
    A failed stop leaves the handle a candidate for the stop pass and §5, and
    the observation is still sent. Control's resume appends a new launch, so a
    surviving old owner reads as superseded, and its writes are already
    launch-fenced (D8).
- On an owner handle's final return, or when the stop pass stops it, cancel its
  liveness observer. A missing or already exited observer counts as cancelled.
- A wake that returns `stalled` replaces rule (b)'s `check-launch` for that
  owner. The verb's `current` verdict is that check. A later return from the
  stopped handle still falls under rule (b) and finds `current: false`, so no
  second observation is sent.

### The control wait

- The control `wait` action gains `wait_seconds`, a required integer:
  `max(0, ceil(deadline_at − now))`, where `now` is the response's own `now`.
  The response validator recomputes it from those two members and refuses any
  other value. The action id stays `wait:<deadline_at>`, and the control
  interface version stays 3 (D9).
- §4 replaces "arm the one-shot observer … and its `deadline_at`" with: arm one
  background `sleep <wait_seconds>` as the observer. The skill tree carries no
  `date` invocation.

### Living docs and budget

- CLAUDE.md is not changed. It does not list the adapter's per-rule behavior or
  the `check-launch` family's members, and the spec and skill are where those
  live.
- The orchestrate-issues growth is measured by the Instruction Budget gate.
  Rule (a) grows. To offset that, the §4 sentence about the wait observer gets
  shorter. If the gate still fails, the PR asks for the raise label rather than
  editing the gate.

## Test seams

All of them drive the CLI from source, under agent-helpers rule 5, and pin the
clock with `WORKFLOW_STATE_TEST_CLOCK`.

1. **Verb unit tests** (`test_workflow_state.py`). These cover:
   - `live` with the exact `wait_seconds`, including that it rounds up;
   - `stalled` exactly at `stall_at`;
   - `not_current` for a superseded launch and for an unknown run;
   - `past_deadline` for a current launch whose clock has reached
     `deadline_at`, even when it is also past `stall_at`;
   - worker registration and release on this launch moving `progress_at`,
     while a worker on another launch does not;
   - `--since` later than `progress_at` moving `stall_at`;
   - a refused future `--since` and a refused `--stall-minutes 0`;
   - an unchanged ledger file after every call;
   - a remainder launch.

   Every reply also passes `artifact-budget validate-report --boundary
   workflow-response`, and the validator refuses a mutated reply (an
   inconsistent `stall_at`, or `wait_seconds` set on `stalled`).
2. **Control wait** (`test_workflow_state.py` or `test_delivered_control.py`,
   wherever the wait action is asserted today). These cover `wait_seconds`
   equal to the ceiling of `deadline_at − now`, and the validator refusing an
   off-by-one value. This is the helper unit test for the computed wait in
   AC 2.
3. **Replay** (`test_admission_replay.py`). The simulated adapter gains rule (a)
   and the liveness wake, over the real CLI. In one run, owner A sends an
   interim notification and records nothing. Its observer wakes at
   `stall_minutes`, the verb answers `stalled`, the adapter stops A and sends
   one `unavailable`, and the next control response resumes or retries A's
   issue and frees the slot. Owner B in the same run sends an interim
   notification and registers a worker within the bound. Its wake answers
   `live`, it is re-armed, and no observation is sent for it. The replay
   asserts exactly one `unavailable` across the run. It also asserts that A's
   slot is freed before A's `deadline_at` (AC 1).
4. **Skill pins** (`test_workflow_skill_contracts.py`). These are argv and
   key-set pins, under rule 6:
   - the orchestrate-issues `owner-liveness` argv, with and without `--since`
     (`workflow-state` argv);
   - in `test_shell_example_contracts`, the wait and liveness observers' shell
     example `sleep <wait_seconds>`, and a refusal of any `date` command in the
     skill's shell examples.
5. **Binding schema** (`test_resolve_project.py`). These cover:
   - `stall_minutes` absent, `null` or a positive integer, all accepted and
     returned verbatim;
   - `0`, a negative number, a boolean and a string, each refused with
     `contract.workflow.*`;
   - the real `.agents/project.json` resolving with `stall_minutes: 90`.

No new eval is added. The replay is the deterministic measure that AC 1 names
as an alternative to an eval, and the existing evals' expected outputs do not
mention rule (a).

## Out of scope

- Control's retry, resume and deadline policy. The `unavailable` observation
  already exists, and control handles it under its own rules.
- from-issue owner behavior, the Codex orchestrate-issues stub, and
  direct-owner runs (`/from-issue --auto` with no orchestrator).
- A time stamp for `mark-progress`. A marker advance with no worker activity is
  not evidence. In Phase 6, sdd's commits go through registered workers, whose
  registration and release are evidence.
- Treating a live, unreleased worker as liveness. A hung worker would then keep
  a slot until the deadline, which is the defect this issue fixes.
- Reaping an owner's background shell processes. The stop pass's existing
  `launch-scope reap --sweep` reaps them once control supersedes the launch.
- Ledger schema changes, and any change to `check-launch`.

## Triage

Input: `{"signals": {"contract_change": {"value": "hit", "evidence": "adds a resolve-project orchestration binding member and a workflow-state helper surface the adapter consumes"}, "concurrency_or_persistence": {"value": "hit", "evidence": "stall detection reads the ledger's per-attempt progress and drives an unavailable owner observation that frees a slot"}, "open_design_questions": {"value": "hit", "evidence": "helper shape (new verb vs check-launch extension), progress signal and the bound's default are open"}, "criteria_shape": {"value": "no", "evidence": "three acceptance criteria, each with a named deterministic test"}}, "paths": ["home/common/claude-code/skills/orchestrate-issues/SKILL.md", "home/common/claude-code/skills/orchestrate-issues/evals/evals.json", "home/common/agent-skills/scripts/workflow-state.py", "python/agent_tools/resolve_project.py", ".agents/project.json", "home/common/agent-skills/tests/test_admission_replay.py", "home/common/agent-skills/tests/test_workflow_skill_contracts.py", "home/common/agent-skills/tests/test_resolve_project.py", "home/common/agent-skills/tests/test_workflow_state.py"]}`
Verdict: `{"hits":["contract_change","concurrency_or_persistence","open_design_questions","risk_path"],"lane":"full","mode":"shadow"}`
ran: full (shadow)

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | `workflow.orchestration.stall_minutes`, an optional positive integer or `null`. Absent or `null` means no stall check. This repo and the fixture set 90 | AC "single named setting … where `attempt_budget_minutes` is documented"; the `light_lane` precedent (absent or null means unsupported); bootstrap "no policy is defaulted". 90 is the light-lane budget, frees the incident owner about an hour into its 2.5-hour hold, and leaves long registered workers time to run | A required member would break every other onboarded repo's resolve until it is edited. A built-in default violates "never defaulted". A value of 30–60 risks stopping owners that wait on a long worker |
| D2 | A new read-only verb, `owner-liveness`, which reads the clock only through `ledger_clock()`. `check-launch` is unchanged | `check-launch` is read-only with no clock, and `launch-scope` and owners parse its closed four-key reply. #309's single clock seam. The issue asks for a helper-computed duration | Extending `check-launch` adds a clock and members to a reply that `launch-scope` closes over. An adapter-side computation puts the date arithmetic back |
| D3 | Progress evidence is the latest of the record's `last_progress_at`, this launch's `at`, and the registration and release times of this launch's workers | These are the only per-launch timestamped writes in the ledger. Workers that commit must be registered (#222), so Phase 6 tasks show up. The run's `updated_at` is shared by all owners | `progress_marker` has no time, and adding one is a schema change. Counting `updated_at` lets one owner's progress hide another's stall |
| D4 | The bound is measured from `max(progress_at, since)`. `since` is the clock at the latest interim notification, returned by the helper and passed back verbatim. A supplied `--since` gets #309's 60-second skew rule | Measuring from the last progress alone would stop an owner the moment it goes interim after a long legitimate phase. The adapter must not write times (#309) | Measuring from `progress_at` alone causes false stalls. An adapter-recorded time is the hand-typed clock again |
| D5 | The reply is a closed `owner_liveness` kind with `verdict` `live`, `stalled` or `not_current`, and `wait_seconds` is at least 1 exactly when the verdict is `live`. Validator support is in the delivery model's workflow-response boundary | The skill rule that every reply is validated before it is decoded; the-bar Fail loud at closed sets | A boolean `stalled` plus an adapter comparison means the adapter interprets policy |
| D6 | The adapter keeps one liveness observer per owner handle: a background `sleep <wait_seconds>`. Its wake asks once, re-arms on `live`, and acts on `stalled` | Issue: "a bounded liveness check … no polling"; the dispatch clause `no-wait-loops`. Each sleep ends at the computed instant, and it re-arms only when the evidence has moved | Folding the check into the single control wait observer mixes two clocks into one wait id. Re-checking at a fixed interval is polling |
| D7 | A later interim notification re-bases `liveness_since` and keeps the installed observer. Its wake re-arms against the new base | Open question 5. A second interim notification proves the owner ran a turn. Keeping the observer avoids the wait-style cancel-and-replace protocol | Not re-basing stops an owner that ran a turn minutes before. Cancelling and re-arming on every interim notification adds failure modes for no gain |
| D8 | `stalled` means: stop the task, then send exactly one `unavailable` for the custody, even if the stop failed. The `current` verdict stands in for rule (b)'s `check-launch` | Issue required behavior. Control's resume supersedes the launch, and launch-fenced writes plus the stop pass and reap contain a survivor (#222, #276) | Withholding the observation until the stop succeeds lets one stop failure keep the slot held, which is the bug |
| D9 | The control `wait` action gains `wait_seconds = max(0, ceil(deadline_at − now))`. The validator recomputes it from the response's `now`, and the interface stays version 3 | AC 2. The adapter is the only consumer, and its validator ships in the same tree. A deadline already passed yields 0, which wakes control to reap | Bumping to v4 churns every pin for one derived member. Letting the adapter compute the value is the BSD/GNU `date` bug |
| D10 | Grill: a current launch whose record is at or past its `deadline_at` answers `past_deadline`, and the adapter sends nothing for it | Control raises `owner_unavailable is not applicable` for an expired record, and its own deadline wait already reaps it | Answering `stalled` past the deadline makes the adapter's next control call fail |
| D11 | Plan: `owner-liveness` reads the clock exactly once. `supplied_time` gains a keyword-only `clock` argument, so the `--since` skew check reuses the verb's one reading. `--since` must be a whole-second `YYYY-MM-DDTHH:MM:SSZ`, and `--stall-minutes` is parsed in the handler (one to nine digits, no leading zero), so each refusal is one stderr line at exit 2. The verb does not run the boundary validator on its own reply | One reading keeps `since`, `wait_seconds` and the verdict on the same instant (#309 D11). The reply's times must pass the delivery model's whole-second `_utc`. Argparse type errors print a usage line too. Like `check-launch` and `resume-pack`, a read-only reply has no commit to protect, and its callers validate it | A second clock read can straddle a second boundary. A fractional `--since` would be echoed and then refused by the boundary. `type=positive_int` gives a two-line refusal |
| D12 | Plan: the AC 1 replay is its own test with its own driver: both owners admitted under seven slots, `stall_minutes` 90 (the committed value), and the `owner-liveness` clock pinned through `WORKFLOW_STATE_TEST_CLOCK` with `mock.patch.dict(os.environ, …)`, because `BuilderHarness.cli` copies `os.environ`. The remainder-launch verb case lives in `test_delivered_control.py`, whose harness already builds a real remainder | `replay()` feeds the committed `baseline.json` metrics, so extending it would churn that baseline. #309's plan used the same override route for `BuilderHarness` | Folding the stall scenario into `replay()` changes every baseline metric. Hand-building a remainder record in `test_workflow_state.py` duplicates the delivery runtime |
| D13 | Plan: the no-`date` pin is a regex over the whole orchestrate-issues `SKILL.md`, with positive and negative controls, in `test_shell_example_contracts.py`. The `sleep <wait_seconds>` pin is an example found through `_examples` | `date` is not in `COMMAND_VOCABULARY`, so `_examples` skips a prose or `text`-fence `date` call. An example-only scan could never fail (the-bar "Tests that can fail") | A head-based scan of examples alone misses the defect it exists to catch |
