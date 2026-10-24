# orchestrate-issues drives every run through `orchestrate-control`

Origin: retro of nodocom session `bacdf125` (2026-10-16 → 21), finding #3. Tracker: #404, blocked
by #403 (merged in PR #416). The helper's design is
`.agents/artifacts/specs/2026-10-21-orchestrate-control-facts-design.md`, cited below as "#403 Dn".

## Triage

Input: {"signals": {"contract_change": {"value": "hit", "evidence": "The orchestrate-issues adapter protocol changes: control requests, contract building and owner projection move behind orchestrate-control start/step."}, "concurrency_or_persistence": {"value": "no", "evidence": "Skill text, evals and a test adapter change; orchestrate-control and workflow-state persistence are untouched."}, "open_design_questions": {"value": "doubt", "evidence": "Issue settles D2/D4/D6, but which pinned skill-contract phrases move and how the replay adapter drives step under test stay open."}, "criteria_shape": {"value": "hit", "evidence": "Five acceptance criteria, one of them post-merge transcript evidence no deterministic check verifies."}}, "paths": ["home/common/claude-code/skills/orchestrate-issues/SKILL.md", "home/common/claude-code/skills/orchestrate-issues/evals/evals.json", "home/common/agent-skills/tests/test_admission_replay.py", "home/common/agent-skills/tests/test_workflow_skill_contracts.py", "home/common/agent-skills/tests/test_shell_example_contracts.py", "home/common/agent-skills/tests/test_dispatch_contracts.py", "home/common/agent-skills/tests/test_eval_cases.py", "python/README.md"]}
Verdict: {"hits":["contract_change","open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

#403 shipped `orchestrate-control`, a helper that does the whole control round for the adapter, but
the Claude `orchestrate-issues` skill still tells the orchestrator to do it by hand. §1–§4 have it
ask `host-route`, run `init-run`, resolve a label or milestone, read the tracker, the forge and
`git worktree list`, reserve candidate worktrees, build delivery contracts, assemble the 17-key
interface_version 3 request, call `control` (twice on a contract round), project owner objects and
fetch resume packs. An orchestrator that follows the skill to the letter writes the same glue the
retro found: a `facts.py`, a `step.sh` called 75 times, a `build.py` and 957 scratch files. That
glue persisted contracts and requests, hard-coded the budget and the slug, and lost reserved
dispatches by calling `control` twice.

Three other surfaces still describe the hand-built protocol:

- The admission replay's simulated adapter still builds the requests the skill no longer sends.
  So the suite tests a protocol no real orchestrator runs.
- The evals grade a hand-built request.
- `python/README.md` still calls the skill change a follow-up.

## Solution

The adapter keeps the host-bound duties, which need task handles: launches, notification
classification, liveness, the stop pass, wait observers and the final report. It hands every
lifecycle fact and every control round to `orchestrate-control`:

1. **Enter.** It resolves the project once, as today, for the two values it still uses: `stall_minutes`
   and the immutable `ledger_repo_root`. It then makes one `orchestrate-control start` call, with
   the caller's numbers, `--label` or `--milestone`, or `--run-id` for a run minted by creation key.
   It keeps the printed `session` unchanged for the rest of the run.
2. **Step per event.** At start or resume, and on each current owner notification, tracker change
   or current wait wake, it makes exactly one `orchestrate-control step --repo-root
   <ledger_repo_root> --input -` call. The call is fed through a quoted heredoc with
   `{session, first_sweep, owners, contracts_due, refused_contracts}`.
3. **Execute.** From a ready report it does four things:
   - It runs the stop pass when `dispatches` is non-empty.
   - It launches each dispatch in order with the existing owner prompt, putting the entry's
     `owner_object` and its `resume_pack`, when that is non-null, in the prompt.
   - It executes the response's `wait`, `finalize` and `delivery_contract` actions as today.
   - It ends the run on `ends_run`.

   A refused report ends the run loudly (D3).

The section that leaves the skill holds every rule `orchestrate-control` now carries:

- the binding-to-request mapping
- `host-route` and its validation
- the `init-run` calls and the bootstrap-requirement reading
- the recorded-worktree and candidate normalization
- the tracker and forge normalization
- the 17-key request template
- the per-issue contract rule and `build-delivery`
- the second control call of a contract round
- the owner-object projection paragraph and the `resume-pack` call
- the instruction that the adapter reads the tracker, the forge and git

The helper's contract lives in `python/README.md` § `orchestrate-control`. These stay
verbatim or near-verbatim:

- notification rules (a)–(d)
- `owner-liveness`
- `check-launch`
- the stop pass and its `launch-scope reap --sweep`
- wait and liveness observer arming
- the restart reaping sentence
- the owner dispatch envelope, prompt and `agent-dispatch` marker
- the §5 final report

The Codex stub is unchanged. The skill shrinks.

Supporting changes ride the same slice:

- **Replay.** The admission replay drives the real command through a hermetic world (D6).
- **Pins.** The skill-text pins follow the new argv (D4).
- **Allow list.** `orchestrate-control` joins the permission allow list, so the heredoc-fed `step`
  example is a vetted lifecycle call (D5).
- **Evals.** The evals expect `start`/`step` (D10).
- **Living documents.** Each document that cites removed skill text is re-pointed (D8).
- **Budget.** Every ceiling the shrink leaves loose is lowered (D9).

## Decisions

### Adapter state and the step protocol

Per D1, the resolve paragraph stays as the skill's one policy entry. It now names only
`bindings.workflow.orchestration.stall_minutes`, which is passed only to `owner-liveness`.
`ledger_repo_root` is the checkout's absolute root, resolved once and passed as every `--repo-root`.
`orchestrate-control` resolves the project itself on every call, and this dispatcher never
resolves again.

Between steps, per D2 and #403 D4, the adapter carries only these values:

| Value | Rule |
|---|---|
| `session` | Verbatim from `start`. |
| `first_sweep` | `true` on the first `step` after `start` in this adapter process, `false` after. |
| `owners` | The observations for this event: one `unavailable` from rule (b) or (d), or one `launch_refused` after a host refusal. They ride this call only (#403 D18) and are cleared after it. |
| `contracts_due`, `refused_contracts` | The previous ready report's members, passed back verbatim. They are `[]` on the first step. |

Its process-local host state is unchanged from today: the owner handles, the wait pair and the
liveness observers. One addition: beside each launched handle it records the dispatch's
`action_id` and the `custody` of the action in that step's `response.actions` whose
`custody.action_id` equals it. That match works for every dispatch kind, because a
`delivery_remainder` action has no `id`. An observation for that handle carries that `custody`. The adapter never decodes `owner_object`
(#403 D17) and never reads the ledger.

It keeps each report's `contract_refusals` entries only to render §5.

### Reading `start` and `step`

Each report is parsed by `outcome`, as an sdd owner parses `sdd-gate` (#403 D2). The helper has
already validated every `workflow-state` reply. The skill never pipes `start` or `step` output
through `validate-report`, and owners still validate their `owner_object` on receipt.

**`start`**

| Outcome | What the adapter does |
|---|---|
| `ready` | Keeps the `session`. |
| `unsupported` | Renders the validated `route`, with its `alternative`, as the final report. It dispatches nothing. |
| `refused`, or `orchestrate-control: invalid invocation` | Reports `step` and `detail` (or the stderr line) and stops. Nothing has been armed yet. |

**`step`**, per D3

| Outcome | What the adapter does |
|---|---|
| `ready` | Executed as below. |
| `refused`, an invalid invocation, or any other exit or stdout | Ends the run as `finalize` does: the stop pass, then clearing the wait state. Its report is the refusal's `step` and `detail` verbatim, plus the `action_id` of every owner handle still running, so it never reads as a finished run. It executes no action of the `response` the refusal carries. A dispatch `control` reserved before the refusal is left to the ledger's deadline expiry (#403 D22). A re-invocation re-enters the run. |

### Executing a ready report

The closed kinds stay named. `step` already refuses an unknown kind at `project` (#403 D23). The
adapter's own switch still fails loudly on any other kind (the bar: defense in depth, fail loud).
Actions are handled in returned order:

| Action | Handling |
|---|---|
| Dispatch | Each of `spawn`, `resume`, `retry` and `delivery_remainder` arrives as a `dispatches[]` entry, in the same order. The envelope lines are filled from the entry's members of the same names: `action_id`, `issue`, `attempt`, `owner`, `worktree` and `handoff_path` (included only when non-null). `ledger_repo_root` and `run_id` come from the adapter and the `session`. The prompt carries `owner_object` verbatim as its canonical JSON. A `resume` with a non-null `resume_pack` adds the pack paragraph. A host-refused launch is never retried, and it never stops the report's later launches or actions. Once the report has executed, one `step` carries every `launch_refused` observation from that report in `owners`, and the adapter executes the resulting report (D12). |
| `wait` | Unchanged. |
| `finalize` | Unchanged. |
| `delivery_contract` | With `ends_run` true it ends the run as `finalize` does, and §5 renders from that response. Otherwise the next `step` answers it at once and passes `contracts_due` back; `step` builds those contracts and makes the control call. The adapter never builds a contract or calls `control` itself (#403 D6). |

The stop pass runs before the first action of any ready report whose `dispatches` is non-empty;
its body is unchanged. Rules (b) and (d) and the host-refusal rule send their one observation "in
the next `step`" rather than "in the next control call".

§5 renders from the `response` of the report that carries `finalize` or `ends_run`. Its builder
refusal reference becomes that issue's retained `contract_refusals` detail, and the rest of §5 is
unchanged.

### What the skill keeps byte-identical

Per D7, the owner dispatch envelope block, the `agent-dispatch` marker, the `Agent(...)` line and
the whole blockquote prompt stay byte-identical. That includes its "Resume pack (only for a
`resume` action whose `resume-pack` call exited 0 …)" line, which stays true: `resume_pack` is that
call's stdout on exit 0. Leaving the block byte-identical leaves alone the `test_dispatch_contracts`
carrier region, the model-matrix site and the orchestrated owner's prompt measure. The `wait`
bullets and the §2 rules (a)–(d) keep their text except for the observation's destination.

### Skill-text pins

Per D4, the pins move as follows.

**`ORCHESTRATE_MACHINE_TEXT` drops** the items whose text leaves the skill:

- the `host-route` argv and `` `host_route: "claude-code"` ``
- `workflow_bootstrap` and both `init-run` argv
- `workflow-state control`, `workflow-state build-delivery` and `--request-file -`
- `matching_issue_branch | absent | mismatch`
- the `resume-pack` argv
- the four projection phrases

`tests/test_orchestrate_control.py` already pins each of these behaviours at the command seam: the
accepted request, host-route, bootstrap, worktree states, projection and resume pack. They are
therefore deleted, not moved (agent-helpers rule 6).

**`ORCHESTRATE_MACHINE_TEXT` adds:**

- the `orchestrate-control start --repo-root <ledger_repo_root>` and `orchestrate-control step
  --repo-root <ledger_repo_root> --input -` argv
- the five step-input member names
- the ready-report members the adapter reads: `dispatches`, `owner_object`, `resume_pack`,
  `contracts_due`, `refused_contracts`, `contract_refusals` and `ends_run`

These are the JSON key sets of a lifecycle contract that rule 6 allows.

**Other test changes:**

- `test_dispatcher_calls_no_retired_lifecycle_command` gains `workflow-state host-route`,
  `workflow-state init-run`, `workflow-state control`, `workflow-state build-delivery`,
  `workflow-state resume-pack` and `--request-file`. These are AC1's absence assertions, as argv
  pins.
- `test_direct_and_control_requests_are_interface_two` loses its orchestrate half: there is no
  request block left to parse.
- The `build-delivery` resolution-exception caller list drops `orchestrate-issues`.
- `CLAUDE_POLICY_ENTRIES["orchestrate-issues/SKILL.md"]` shrinks to `stall_minutes`.
- A section anchor that only a test reads may be renamed with that test.

**Kept:**

- the `check-launch`, `owner-liveness` and `launch-scope reap` argv
- `run_in_background=true`, `launch_refused`, `unavailable`, the liveness tokens and
  `--boundary workflow-response`
- the `worktree_fact` reason codes of §5
- the literal `~/.agents/bin/workflow-state` fallback

### Permission surface and the shell-example contract

Per D5:

- **Allow list.** `"Bash(orchestrate-control:*)"` and `"Bash(~/.agents/bin/orchestrate-control:*)"`
  join the allow list in `home/common/claude-code/default.nix`. The allow-list comment names four
  lifecycle helpers.
- **Command vocabulary.** `orchestrate-control` joins `COMMAND_VOCABULARY`.
- **Guard test.** `tests/test_claude_permission_guard.py` adds both entries to its allow tuple, plus
  one allowed row for the heredoc-fed `step` call.
- **README.** `home/common/claude-code/README.md`'s allow-surface sentence becomes 26 entries and
  names the helper. This is the ship-delivery precedent (b89c6dbb).
- **Skill examples.** The skill shows each `start` form as a plain call on its own example line:
  explicit numbers, `--label <label>`, `--milestone <milestone>`, and `--run-id <run-id>`
  re-entry. Alternatives are never joined with `|`, which the scanner reads as a pipe. It shows
  `step` as one `text`-fence example: the argv line, a quoted `<<'EOF'` heredoc carrying the
  five-member object, and `EOF`. All of them are vetted examples.

### Evals

Per D10:

- **Eval 1** expects `start` once and then one `step` per event, with the five-member input. It
  expects dispatch from `dispatches[]` with `owner_object`/`resume_pack`, `ends_run` as `finalize`,
  and a refused step that is reported and ends the run. It lists as failures:
  - a raw `host-route`, `init-run`, `control`, `build-delivery` or `resume-pack` call
  - a hand-built request
  - decoding `owner_object`
  - a request or contract file
- **Eval 2**'s restart becomes reaping the inherited observers, then `start` (the same numbers
  re-enter the same run, or `--run-id`), then `step` with `first_sweep` true.
- **Eval 3**'s route check becomes `start`'s `unsupported` outcome, and its refusal becomes one
  `step` carrying `launch_refused`.
- **Evals 4–6** are unchanged.
- **Corpus pins.** Evals 1 and 7 keep "Resolve once into a retained ResolvedProject", a phrase the
  eval-corpus test requires. New eval text avoids the corpus's forbidden phrases, such as
  "default GitHub".
- **Eval 7** keeps id 7, mode `pipeline` and its three sandbox asserts (ledger with no attempt, no
  worktree, `main` unmoved). The ledger assert is pinned by `test_eval_cases`. Its prompt drops the
  supplied tracker facts. In its expected output, `start` prints a ready `explicit_user` session
  and the first `step` refuses at `tracker`, because the fixture's tracker kind is `none` (#403 D7).
  The adapter reports `tracker` and its detail verbatim and stops. One assert replaces the builder
  and `delivery_contract` asserts: the output names the refused step `tracker` and
  `tracker kind none is not supported`.

### Living documents and the instruction budget

Per D8, each living document that cites removed text is re-pointed in the same change:

- **`from-issue/acquire-durable.md`.** Its four `orchestrate-issues` citations become
  self-contained, with no net byte growth:
  - The per-issue-rule citation is deleted, because the rule is stated inline right after it.
  - The §4 citation is deleted, because the re-call is stated inline.
  - "as orchestrate-issues does" becomes the rename rule written out: rename `id` to `action_id`
    and `kind` to `launch_kind`; add `kind: owner`, `interface_version: 2`, `ledger_repo_root` and
    `run_id`.
  - "(orchestrate-issues' 17-key shape)" is deleted.
  
  Its pinned order (`init-run`, `max_parallel: 1`, `workflow-state control`, first `spawn`
  envelope) stays.
- **`home/common/agent-skills/README.md` § Lifecycle helpers.** The resume-pack sentence's
  "orchestrate-issues §4 adds it to `resume` prompts" names `orchestrate-control step` as the source
  of that pack.
- **`python/README.md`.** The closing D11 sentence states that the `orchestrate-issues` skill drives
  every run through `start` and `step` (#404).

Per D9, the plan runs `instruction_load tighten` after the skill text is final, so that no ceiling
stays loose. It lowers whatever ceilings `tighten` reports loose:

- The `orchestration-dispatcher` ceiling is expected to be loose.
- So is `orchestrated-issue-owner`, because its `prompt` member is the whole skill file.
- The corpus ceiling probably is not: a shrink of about 10 KB is under 5% of it.

Each lowered profile note gains "Ceiling lowered for #404". No ceiling rises, so
`instruction-budget-raise` is never needed.

### The admission replay

Per D6, the replay keeps its fixture host, its per-minute agent budget, `complete_delivery`'s
checkpoint/finish sequence, `baseline.json` byte-identical and every admission assertion.

**World and binary.** The replay is built on `tests/orchestrate_world.py`'s `OrchestrateWorld`
(#403 D26), imported as `tests.orchestrate_world`, which is the precedent of
`tests/test_review_history.py`. The fixture contract's
`bindings.workflow.orchestration.attempt_budget_minutes` is mutated to 180. Its `max_parallel` is
already 2. The replay runs the real `python -m agent_tools.orchestrate_control` through the
world's fake `gh` and its source `workflow-state`/`artifact-budget` shims.

**Simulated adapter.** It follows the new skill:

- It makes one `start`.
- It makes one `step` per event: start, each fixture-host exit or refusal, and each stall
  observation.
- It passes `contracts_due`/`refused_contracts` back.
- It launches `dispatches[]` with `action_id`.
- It takes custody from `response.actions`.
- It sends `launch_refused` and `unavailable` observations in `owners`.

`controller_turns` counts `step` calls.

**Clock.** `WORKFLOW_STATE_TEST_CLOCK=at(minute)` is set in the world's environment before every
`step` and every direct `workflow-state` call. `step` sends no `now`, so this pinned clock replaces
the request `now` that #403 D11 named as the obstacle.

**Fixture host and owners.**

- At launch, the fixture host runs `git worktree add -b issue-<n>-orchestrated <dispatch worktree>`
  in the world.
- When the owner's delivery completes, the host removes that worktree and its branch. The real
  facts therefore track today's injected `candidate → matching_issue_branch → absent`.
- A simulated owner reads its contract from its `owner_object`, which is owner-side decoding.
- `owner-liveness`, `register-worker`, `check-launch`, `checkpoint-delivery`, `finish` and
  `build-delivery` for observations stay direct `workflow-state` calls, as the skill and the owner
  make them.

**Three-slot test.**

1. `start` answers `unsupported` with `reason_code` `declaration_invalid` and leaves no run.
2. A run is opened by `start` under a valid declaration, and the declaration is switched to 3.
3. One `step` then refuses at `control` with exit 2. Its `detail` carries `declaration_invalid` and
   the run's `state.json` bytes are unchanged (`init-run --run-id` writes nothing).
4. With 4 slots declared again, `step` returns `[spawn, wait]`.

**Added assertion.** The replay adds one assertion: the world's logged `workflow-state control`
calls equal the summed `control_calls` of the replay's steps, so every control round went through
`step`.

**Helper defects.** A defect in `orchestrate_control.py` that blocks the replay is fixed minimally
and logged as a new ledger row. Otherwise the helper is untouched.

### Acceptance criterion 5

Per D11, AC5 ([evidence], no glue in a real run) is graded `human_pending` at final review. Its
measurement needs the merged skill installed by `just switch` and a live run of three or more
issues. Ship therefore holds #404 open with `needs-verification` until a human reads the next such
run's transcript: 0 `Write` calls creating `.py`/`.sh` helpers, and at least one `step` per control
round. The pre-merge proxies are eval 1 and the replay's control-call assertion.

## Test seams

The seams are few and existing, highest first.

1. **The command seam (unchanged).** `tests/test_orchestrate_control.py` already pins every behaviour
   the skill stops describing. This slice adds nothing there.
2. **The replay seam (AC2).** `home/common/agent-skills/tests/test_admission_replay.py` drives the
   real command as a subprocess in `OrchestrateWorld`, as above. Prior art: #403 D26's world and the
   replay's own baseline.
3. **The skill-text seam (AC1).** This seam covers:
   - `test_shell_example_contracts.py`: both examples vetted, the heredoc sanctioned through the
     allow list
   - `test_dispatch_contracts.py`: carrier and marker unchanged
   - `test_workflow_skill_contracts.py`: per D4
   - `test_eval_cases.py`: the case-7 ledger assert kept
   - `skill_lint`

   They run under `just agent-workflow-tests`, with `tests/test_claude_permission_guard.py` for the
   allow tuple.
4. **The budget gate (AC3).** `just agent-instruction-budget` against `origin/main`, without
   `--raise-label`.
5. **The eval suite (AC4).** `home/common/agent-skills/evals/run-eval.sh` on `orchestrate-issues`
   (plan-only cases 1–3 and pipeline case 7), run once in final verification. It runs with
   `EVAL_TREE` set to the worktree, so the tree's `agent_tools` shims put `orchestrate-control` on
   `PATH`. The deployed `~/.agents/bin` lacks the helper until `just switch`. `EVAL_SETTINGS`
   points at the built settings, so the new allow entries apply.
6. **Post-merge evidence (AC5).** Per D11.

`just build` stays the Nix verification, because the allow list is a settings change.

## Out of scope

- **Helper behaviour.** `orchestrate_control.py` behaviour changes, except a replay-blocking defect,
  which is logged.
- **Session-carried policy.** A `stall_minutes` member in the session that would let the adapter
  skip resolution. That is a helper change, and #403 D5 keeps policy out of the session.
- **The durable route's template.** The durable interactive route's 17-key request template gets
  no new home. Giving it one costs about 1.6 KB on `from-issue-controller`'s conditional ceilings,
  which have 128 B headroom, and that needs the user's raise label. A follow-up should give that
  route a helper rather than a template.
- **Sibling retro findings.** The stray `GITHUB_TOKEN` export and the lifecycle guard's env-prefix
  and grammar messages.
- **Other deferrals.**
  - rendering the owner prompt to a file
  - the Codex stub and Codex orchestration
  - automating notification classification, liveness, the stop pass or wait arming

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The skill keeps its one `resolve-project resolve` entry, now consuming only `stall_minutes`, while `ledger_repo_root` stays the checkout root. `orchestrate-control` resolves the rest on each call, and the adapter never resolves again. | Session carries no bindings (#403 D5); rules (a)/(d) stay and need `stall_minutes`; `assert_policy_entries` wants one resolve statement per entry. | Dropping resolution: there is no other source for `stall_minutes` without a helper change. Keeping the tracker/vcs/budget mapping: dead text the helper owns. |
| D2 | Carried state is `session`, `first_sweep` (true only on the first `step` after `start` in this process), `owners` (this event's observations, cleared after the call), `contracts_due` and `refused_contracts` passed back verbatim. An observation's `custody` comes from the `response.actions` entry whose `custody.action_id` is the dispatch's `action_id`, recorded beside the launch handle, and `contract_refusals` are kept only for §5. | #403 D4, D17, D18; the issue's step input; rules (b)/(d) and the host-refusal rule need a custody. | Decoding `owner_object` for custody: the glue D17 removed. A bootstrap read: the adapter no longer bootstraps. |
| D3 | A refused, invalid or unparsable `step` ends the run as `finalize` does and reports `step` and `detail` verbatim, plus the still-running owner handles' `action_id`s, executing nothing from the attached `response`. `ends_run` is `finalize`, and a `delivery_contract` reply without `ends_run` is answered by the next `step` at once. A refused or invalid `start` reports and stops, and `unsupported` renders `route`. | Issue: "surfaces a `refused` step … fails loudly", "treats `ends_run` as `finalize`"; the bar's fail-loud and truthful terminal states; #403 D6, D22; README's `ends_run` definition. | Retrying a refused step: it repeats the refusal and re-sends observations. Executing the attached response: it was refused before projection. Treating an unchained `delivery_contract` as a contract error: the README says a later build can answer it. |
| D4 | Pins whose skill text leaves are deleted, not moved, because `tests/test_orchestrate_control.py` already pins that behaviour. New pins are `orchestrate-control` argv, the five step-input members and the report members the adapter reads. Raw `workflow-state` lifecycle argv and `--request-file` become absence pins. The `orchestrate-issues` policy entry shrinks to `stall_minutes`. | agent-helpers rule 6 (argv and lifecycle key sets only; phrase pins die with their text); AC1's absence clause. | Moving phrase pins onto `python/README.md`: new English-phrase pins, which rule 6 forbids, guarding behaviour already pinned at the command seam. |
| D5 | Whole-allow `orchestrate-control` (bare and `~/.agents/bin/`) and add it to `COMMAND_VOCABULARY`, the guard test's allow tuple and an allowed row, and the claude-code README count. The `step` example is then a sanctioned heredoc lifecycle call. | The shell-example contract sanctions a heredoc only under a whole-allowed head; precedent b89c6dbb (ship-delivery); the helper's only writes are `workflow-state` ledger writes, and its `gh`/`git` children read. | A heredoc-free inline example: the heredoc form goes unvetted, and every `step` waits on the auto-mode classifier, where a denial stalls an autonomous run. Multi-word allow entries: the checker reads only single-word entries. |
| D6 | The replay runs real `orchestrate-control` in `tests.orchestrate_world.OrchestrateWorld` with `attempt_budget_minutes` mutated to 180. It pins `WORKFLOW_STATE_TEST_CLOCK` per simulated minute, the fixture host adds and removes real worktrees, and `baseline.json` and its assertions stay. It adds one assertion: logged `control` calls equal the summed `control_calls`. | agent-helpers rule 5 (commands from source via `-m`); #403 D26's world with its fake `gh`; `ledger_clock` honours the test clock, answering #403 D11's `now` obstacle. | In-process patching of `run_child`/fact functions: it breaks rule 5 and ties the test to private code. A second fake `gh` in the agent-skills tree: it duplicates D26's world. Moving the replay into `tests/`: history and recipe churn. |
| D7 | The owner envelope, marker, `Agent(...)` line and blockquote prompt stay byte-identical. The envelope is filled from the dispatch entry's same-named members. | Issue: owner prompt and marker unchanged; `resume_pack` is the `resume-pack` stdout on exit 0, so the prompt's wording stays true; dispatch carrier region and owner profile prompt measure. | Rewording the pack line to name `resume_pack`: it churns a carrier region and the owner measure for no behavioural gain. |
| D8 | Re-point living documents in the same change: `acquire-durable.md` drops its contract-rule, §4 and "17-key shape" citations and inlines the projection rename rule (no net growth); the agent-skills README resume-pack sentence and the `python/README.md` D11 sentence follow. The durable route's request template gets no new home here. | The bar: re-point every living document; `from-issue-controller` conditional headroom is 128 B on both hosts; `instruction-load.json` lists no `orchestrate-issues` member in that profile, so the route never loaded the template it cites. | Moving the 17-key template into `acquire-durable.md`: about 1.6 KB, which needs `instruction-budget-raise`, and only the user applies it. Keeping the template in the skill: it contradicts AC1. |
| D9 | After the skill is final, `instruction_load tighten` lowers every ceiling it reports loose. That is expected to be the dispatcher and the orchestrated owner (its `prompt` is the whole skill file); the corpus only if it crosses 5%. Each lowered note gains "Ceiling lowered for #404", and nothing rises. | AC3; the gate fails a ceiling above 105% of its measure; `tighten` is the gate's own repair verb. | Hand-editing ceilings: it restates numbers the tool measures. |
| D10 | Evals 1–3 expect `start`/`step`. They name raw `workflow-state` lifecycle calls, a hand-built request and `owner_object` decoding as failures. Eval 7 becomes a tracker-free run whose first `step` refuses at `tracker`, keeping its sandbox asserts and replacing the builder and `delivery_contract` asserts with a refusal-report assert. Evals 4–6 stay. | #403 D7 (`step` is GitHub only); the eval fixture binds tracker kind `none`; `test_eval_cases` pins case 7's ledger assert. | Switching the fixture to GitHub: the sandbox has no forge. Dropping eval 7: it loses the skill's only pipeline case. |
| D11 | AC5 is graded `human_pending` at final review, so ship holds #404 open with `needs-verification` until a human reads the next run of three or more issues. Eval 1 and the replay are the pre-merge proxies. | AC5 needs the merged skill installed and a live run; sdd grading tokens; ship-issue holds on `human_pending`. | Grading it `met` from the replay: a replay is not a transcript. Making it a merge gate: it cannot run before merge. |
| D12 | Grill: a host-refused launch never stops the report's later launches or actions. Once the report has executed, one `step` carries all of its `launch_refused` observations, and each observation still rides exactly one call. | A dispatch left unlaunched stays reserved until its deadline (#403 D22), so stopping at the first refusal strands the rest for hours; `owners` is a list, and observations ride one call (#403 D18). | One immediate `step` per refusal, mid-report: it strands the report's remaining dispatches and multiplies control rounds. |
