# Shared verification blocker: callers, procedures and docs — issue 546 (228 c4)

Issue: https://github.com/fagenorn/nix-config/issues/546, boundary `c4` of
https://github.com/fagenorn/nix-config/issues/228 (parent Tasks 6 and 7). Its blockers
https://github.com/fagenorn/nix-config/issues/543 (c1, the pure module and the adapter),
https://github.com/fagenorn/nix-config/issues/544 (c2, schema 11 and parking) and
https://github.com/fagenorn/nix-config/issues/545 (c3, resolution and resume) are merged. The
parent spec (D1–D25), plan and Tasks 6–7 at `0361d66c` are provenance only; every rule below
was re-decided against the code c1–c3 landed. Their rows are cited as "issue 543 D<n>", "issue
544 D<n>" and "issue 545 D<n>", the parent's as "parent D<n>". Designed autonomously
(`from-issue --auto`); every call made without the user is a row in the Decision ledger.

## Triage

Input: `{"signals": {"contract_change": {"value": "hit", "evidence": "orchestrate-control's ready object gains verification_refusals; from-issue/acquire-direct procedures gain the verification suspend and suspended-reply contracts"}, "concurrency_or_persistence": {"value": "hit", "evidence": "gathering fetches the integration branch and feeds observations that make workflow-state resolve blockers and resume parked attempts in the ledger"}, "open_design_questions": {"value": "doubt", "evidence": "parent Task 6 names verification_observe.observe_all, which c1 did not land; the batched-observe API and its home are open"}, "criteria_shape": {"value": "hit", "evidence": "AC6 is review evidence (projections, gate lines, distinct final reviews), not a deterministic code check"}}, "paths": ["python/agent_tools/orchestrate_control.py", "python/agent_tools/verification_observe.py", "tests/test_orchestrate_control.py", "tests/test_verification_observe.py", "python/README.md", "home/common/claude-code/default.nix", "home/common/agent-skills/skills/from-issue/SKILL.md", "home/common/agent-skills/skills/from-issue/acquire-direct.md", "home/common/agent-skills/skills/sdd/final-review.md", "home/common/agent-skills/instruction-load.json", "home/common/agent-skills/README.md", "home/common/agent-skills/tests/test_workflow_skill_contracts.py"]}`
Verdict: `{"hits":["contract_change","concurrency_or_persistence","open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}`
ran: full (shadow)

## Problem

c1–c3 built the whole helper side of a shared verification blocker, but no caller uses it:

- no owner procedure declares a blocker, so `suspend --blocked-on verification` is never
  called;
- `orchestrate-control` sends `"verification": []`, so an orchestrated attempt parked on a
  blocker never resumes, even after its selected integration-branch path changes;
- acquire-direct fails loudly on an `observe` reply asking for `verification` and on a
  `suspended` reply, so a direct run parked on a blocker cannot be re-entered;
- the instruction ceilings and the lifecycle README still describe the pre-c4 state ("no caller
  gathers observations yet").

The user needs:

- an sdd owner whose declared verification command fails for a reason outside its change to
  park on a shared blocker, and to keep its repair route when the adapter refuses;
- every orchestration step to observe each awaited blocker once, after at most one fetch, and
  to send what it observed, so a changed selected path resumes the attempt in place;
- a failed observation to be reported as a refusal, never sent and never read as a change;
- a direct re-entry to answer the helper's `verification` requirement and to stop truthfully
  on `suspended`;
- the docs and ceilings to state what the landed code does, including how a run upgraded by a
  reviewed source helper is driven until activation.

## Solution

1. **Batched observing.** `agent_tools.verification_observe` gains `observe_all`: one
   resolution, at most one fetch and one commit for every requirement it is given, each
   requirement observed or refused on its own (D2).
2. **Gathering.** `orchestrate-control step`'s `bootstrap` step observes the bootstrap's
   `verification` requirements, the first `control` call carries the observations, the chained
   second carries `[]`, and the ready object reports every refused requirement in
   `verification_refusals` (D3, D4).
3. **Declaring.** sdd's Final verification classifies a failing declared command before its
   repair and runs `verification-observe failure`. A printed failure goes to from-issue's
   suspension procedure, which gains the `verification` cause and its `--verification-input -`
   template. A refusal keeps the repair (D5).
4. **Direct re-entry.** acquire-direct answers a `verification` requirement through its
   `expects.build` and relays a `suspended` reply with the canonical line (D6).
5. **Ceilings and docs.** The three grown skill documents' profiles and the corpus get exactly
   their new measure. The lifecycle README's `### Verification blockers` subsection states the
   caller protocol, the known limitations and the source-helper rule. `python/README.md`, the
   module docstring and the allow-list comment state the new write (D4, D8–D10).

No ledger schema step and no interface version moves: the step's input, the control request
and reply, the bootstrap and every direct-owner reply keep their landed shapes (issue 545 D3).

**Demo** (temporary roots, a local bare `origin`, no network):

1. Issue 61 is spawned and parked on blocker X (`flake.lock`). A step sends one observation
   of X, equal to the record. Nothing resumes, `verification_refusals` is `[]`, and the step
   fetched once.
2. A publisher commit that changes only `README.md`: the next step's observation is still
   equal, and nothing resumes.
3. A commit that changes `flake.lock`: the next step's first request carries the changed
   observation, and the ready object dispatches `resume` for 61, attempt 1.
4. With `origin` unreachable, the step exits 0, sends `verification: []` and reports one
   `{blocker_id: X, detail}` refusal. 61 stays parked.
5. A run with no parked attempt never fetches, and the chained second call of a
   contract-requesting step sends `[]`.

### This delivery's own gates

- **Fixed base.** `763d8d48570c747ad368d0849939328ad12b49ed`. Integration advances never
  move it.
- **Forecast and reviews.** The plan commits a complete review-feasibility forecast. Each
  task gets a fresh independent review, then distinct conformance and correctness reviews
  follow. Parent and c1–c3 reviews do not count. The SDD workspace records every `sdd-gate
  next` projection's exit 0 and every `Delivery gate:` line (AC2).
- **Verification.**
  - The focused tests;
  - `just agent-instruction-budget --raise-label`, which proves the raise is complete and
    tight;
  - `just agent-workflow-tests` and `just build` at the final head.

  Tests use temporary ledgers, repositories and `HOME`s. No live ledger or retained attempt
  is read or written, and `just switch` never runs. Source integration (the merge) and host
  activation (the user's `just switch`) are reported separately.
- **The raise label.** CI's required `Instruction Budget` check stays red until the user
  applies `instruction-budget-raise`. No agent applies it, and the merge waits for it (D8).

## Decisions

### Batched observing (D2)

In `agent_tools.verification_observe`, beside `observe` and `build_failure`:

`observe_all(repo_root, requirements) -> (observations, refused)`

1. **Check first.** `requirements` must be a list whose every element passes
   `validate_requirement`. Otherwise `BlockerRefused` names `requirements[<i>]` before any
   process starts.
2. **Nothing to observe.** An empty list returns `([], [])`. It resolves nothing and fetches
   nothing.
3. **One fetch.** Otherwise the project is resolved once with no capability required (issue
   543 D11). The integration branch name is checked, `origin`'s branch is fetched once, and the
   tracking ref is read once as a commit id (issue 543 D12, D18). A refusal at any of these
   refuses every requirement with that reason.
4. **Reads.** Each requirement's paths are read at that one commit, each by its own `ls-tree`
   (issue 543 D14). A read refusal refuses that requirement only.
5. **Build.** Each observation is built and validated exactly as `observe` builds one, its
   `repository` resolved now (issue 543 D8).

It returns:

- `observations`: the observations, in input order;
- `refused`: one `(blocker_id, reason)` pair per refused requirement, in input order. `reason`
  is the one-line text that `verification-observe` would print after its prefix.

Every requirement lands in exactly one of the two lists. A refusal is never an observation,
never a `null` and never a stale ref's value (issue 543 D6).

`observe` and `observe_all` share one path, so the Git children, their environment, the
timeout and the `ls-tree` parsing keep one home. `observe` stays the one-requirement form that
raises its refusal. The CLI keeps exactly `failure` and `observe`; no `observe-all` mode is
added, because the only batch caller imports the function.

### Gathering in `orchestrate-control step` (D3)

- **Where.** In the existing `bootstrap` step, after `init-run`'s reply is checked to be the
  session's run, `observe_all(repo_root, boot["verification"])` runs once. Then `bootstrap`
  completes. The step count stays eight, and `completed_steps` keeps its names.
- **A malformed list.** A `verification` member that is not a list, or an element the
  adapter's validator refuses although the workflow-response boundary accepted it, refuses at
  `bootstrap` with the `BlockerRefused` line. Both sides of the boundary check, and a
  disagreement fails loud.
- **What is sent.**
  - The first `control` request's `verification` is the observations, in bootstrap order
    (sorted by `blocker_id`, issue 545 D6).
  - The chained second request sends `[]`, as it sends `owners` empty. The first call has
    already committed any resolution (issue 545 D6), so a resend would name a resolved record
    and be refused.
- **What is reported.** The ready object gains `verification_refusals`:
  - one `{blocker_id, detail}` per refused requirement, in bootstrap order, `[]` when none;
  - `detail` is the reason with its whitespace collapsed and cut to 300 characters, like a
    step refusal's `detail`.
- **What stays parked.** A refused requirement is left out of the request. Its attempt stays
  parked, its summary keeps the requirement, and the next step observes it anew. An
  unobservable requirement never refuses the step, and the refused output object is
  unchanged.
- **When.** Every step gathers, not only a first sweep, and every requirement the bootstrap
  lists is observed. A requirement whose issue is outside the session is observed too: the
  blocker map belongs to the run, and control accepts any open record of it (issue 545 D4).
- **Unchanged.** The step input, the request's other members, the control interface (4) and
  the `orchestrate-issues` adapter's duties. `start` makes no control call, so it never
  gathers. The ready object carries no version member, and its readers take members by name,
  so the new member moves no version. A `detail` is output only and is never persisted (D15).

### Writes and their docs (D4)

`orchestrate-control` still writes no file of its own. Besides `workflow-state`'s ledger
writes, it now makes one write: when the bootstrap lists a requirement, the fetch updates
`refs/remotes/origin/<integration_branch>` in the ledger repository, with that commit's
objects. That is `verification-observe`'s only write (issue 543 D6), and any `git fetch` makes
it.

These state it from the landed code:

- the module docstring: `bootstrap` gathers, the first call carries the observations, the
  ready member, the writes sentence;
- `python/README.md` § `orchestrate-control`: the same facts;
- `python/README.md` § verification-observe: `observe_all`'s contract;
- the allow-list comment in `home/common/claude-code/default.nix`: orchestrate-control's
  writes include that fetch.

The allow list itself, its entry count, `lifecycle_guard.py` and the command table do not
change. `orchestrate-control` and `verification-observe` are already allowed whole, and
gathering runs in process.

### Declaring a shared blocker (D5)

**sdd Final verification, step 4.** Under a lifecycle identity, and before the repair, the
controller classifies a failing declared command (not a `record` exit 3 or a helper exit 2).
It is a shared blocker only when:

- its cause lies outside the change;
- integration-branch paths decide that cause: a pinned dependency (`dependency`), the
  declared environment (`environment`), an external service (`external_service`), or the
  command's declared input (`command_input`).

A product, test or build failure of the change never qualifies. For a qualifying failure it
runs, in the foreground and before any worker release or reap:

```text
verification-observe failure --repo-root <ledger_repo_root> --input - <<'EOF'
{"command_id": "<id>", "failure_class": "<class>", "worktree": "<absolute worktree>", "facts": [{"name": "<name>", "paths": ["<path>"]}]}
EOF
```

- **Exit 0.** Follow from-issue's suspension procedure with `blocked_on=verification` and the
  printed failure, as sdd's deadline route follows it with `blocked_on=deadline`.
- **A refusal.** The failure is not a shared blocker, and the repair runs as written. The
  adapter's guard judges whether the attempt changed its own input (issue 543 D7), so the
  owner does not retry with other facts until one is accepted.
- **When.** The classification runs once, before the repair, and only when every failing
  command qualifies. It then declares the first failing command in run order. A mix that holds
  any change-caused failure takes the repair as written, and a failure after the repair keeps
  today's Residuals route (D14).

The adapter runs before the suspension procedure because that procedure's reap kills the
launch's processes and deletes its scratch root. A refusal after a reap would leave the repair
without its log path.

**from-issue suspension procedure.**

- **The cause list.** `verification` joins sdd's `deadline`, in order before the reaper's
  `unknown` parenthesis.
- **The template.** A second literal template follows the first, for that cause only:

  ```text
  workflow-state suspend --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id> --blocked-on verification --verification-input - <<'EOF' | artifact-budget validate-report --boundary workflow-response --input -
  <the failure verification-observe printed, unchanged>
  EOF
  ```

  The reply handling (`kind: terminal` at the stall bound, else `kind: suspended` and the
  canonical `Suspended (blocked_on=<value>)` line) is shared and unchanged.
- **The lifecycle-call rule.** Its list of stdin flags gains `--verification-input -`.

The procedure keeps the one home of the `suspend` verb, so the release, reap and reply rules
are not restated in sdd.

### Direct re-entry (D6)

In acquire-direct:

- **`kind: observe`.** A `verification` requirement is answered by running its
  `expects.build`, with `<ledger_repo_root>` filled, on the requirement less `expects`,
  through a quoted heredoc. The printed observation is appended to `verification`. The
  existing builder-refusal sentence (exit 2, empty stdout: fail loudly, report the stderr
  line) is widened to name the adapter's refusal too. The retain-and-resend rule is unchanged, and so is the
  resent observation's validity: a resolution commits only with the resume (issue 545 D7).
- **Item 5, `kind: suspended`.** It requires exactly `interface_version`, `kind`, `run_id`,
  `issue`, `custody`, `blocked_on` and `reentry`. It prints `Suspended
  (blocked_on=<blocked_on>). Resume: <reentry>` as the final output and stops before Phase 1,
  installing no waiter. It sits after item 4 (`kind: terminal`).
- **The clearing rule** names `suspended` beside `owner`, `delivery_remainder` and `terminal`.

The adapter's command line is not restated, because the `expects` catalogue is its one home
(issue 545 D10).

### Callers that do not change (D7)

- **`orchestrate-issues`** (both trees). Its step input and duties are unchanged. A
  verification-parked issue already reports as paused from its finalize summary, and
  `verification_refusals` is diagnostic in the ready JSON the conversation holds.
- **acquire-durable.** It sends `verification: []` and keeps its exactly-one-dispatch rule,
  so a run parked on `verification` fails loudly there (issue 545 D11).
- **AUTO.md, `rollover.md` and `delegated-owner.md`.** They relay any `Suspended (…)` line
  generically.
- **sdd `SKILL.md`.** Final verification lives in `final-review.md`.

### Instruction ceilings (D8)

Instruction text grows only in from-issue `SKILL.md`, `acquire-direct.md` and sdd
`final-review.md`. These grow measurably:

| Profile | Hosts | Grown documents | Headroom at the base |
|---|---|---|---|
| `from-issue-controller` | claude, codex | `SKILL.md`, `acquire-direct.md` | 94 bytes |
| `implementation-owner` | claude, codex | `SKILL.md`, `final-review.md` | 140 bytes |
| `orchestrated-issue-owner` | claude | `SKILL.md`, `final-review.md` | 588 bytes |
| corpus | — | all three | 5 bytes |

- **The raise.** Each breached hot ceiling, and the corpus ceiling, is raised to exactly its
  measure at the final head. Each raised profile's `note` gains one sentence naming #228
  (issue 546) and what grew in it. The corpus ceiling has no note. A ceiling that is not
  breached does not move, and the description ceiling does not move.
- **Who applies the label.** `just agent-instruction-budget --raise-label` must pass. Applying
  the label is the user's alone (CLAUDE.md), so the merge waits for it.
- **What this child adds.** The added text is procedure that a model must emit reliably: two
  literal templates, a closed cause value, a closed reply key set and one clearing word.
  Explanation stays in the README.

### Lifecycle README (D9)

`home/common/agent-skills/README.md` § Lifecycle helpers already has `### Verification
blockers` (issues 544 and 545). It is extended, not duplicated by a new `### Shared
verification blockers` sibling.

The issue-545 sentence "Known limitation: no caller gathers observations yet …" is replaced by
the caller protocol, stated from the landed code:

- sdd's Final verification declares and routes (D5);
- `orchestrate-control` gathers once per step, sends on the first call only and reports
  `verification_refusals` (D3);
- acquire-direct answers through `expects.build` and relays `suspended` (D6);
- acquire-durable fails loudly (D7).

It then states the known limitations:

- **Paths only.** Repository paths are the only fact kind, so an outage no path decides keeps
  `transport`.
- **Observed per step.** An orchestration observes once per step. A run whose only remaining
  work is parked ends in `finalize`, and re-invoking the orchestration observes again.
- **No sync on resume.** A resumed attempt's worktree does not take in the change that
  resolved its record. If the command fails again, the adapter's guard refuses, because the
  worktree's `HEAD` differs from `origin`, so the owner repairs instead of parking again.
- **A changed repository strands the step.** A contract whose `project.id` or integration
  branch changed while a record is open makes every observation of that record refused by
  control. Every later step then refuses at `control` (D12).

### Source helper until activation (D10)

A ledger that a reviewed source helper has migrated to schema 11 is refused by every older
installed helper (`unknown_schema`, nothing written; issue 544 D9). Until `just switch`
installs that source, every call for that run comes from that same checkout:

- `workflow-state` runs as `PYTHONPATH=<checkout>/python python3
  <checkout>/home/common/agent-skills/scripts/workflow-state.py`;
- a `workflow-state` shim for it is first on `PATH`, because `orchestrate-control`,
  `launch-scope`, `launch-commit`, `sdd-gate` and other `agent_tools` commands run it by name;
- those commands themselves, `verification-observe` included, run from that checkout's
  `python/`.

The README states this rule in the subsection. No ledger marker records which helper wrote a
run (parent D12). The installed helper's `unknown_schema` refusal is the signal that a call
came from the wrong place.

### Concurrency (D12)

- **The fetch.** It updates a ref shared with every owner's `verification-observe failure`
  and every other fetch, under Git's ref lock. A losing fetch is a refusal: that step reports
  every requirement in `verification_refusals`, and the next step retries. A losing owner's
  `failure` is an adapter refusal, so it keeps the repair route. No value is read from a ref
  the call did not just update.
- **Between `bootstrap` and `control`.** One adapter process calls `step` serially per run,
  and only `control` and `direct-owner` resolve records. A direct run never shares a run with
  an orchestration. So a record listed `open` is still `open` when the first call arrives. A
  concurrent `suspend` may join it or reopen another record, ordered by the run lock (issue 545
  D15), and control compares against the stored facts at that moment.
- **A refused observation.** Control refuses the whole request (issue 545 D4), so the step
  refuses at `control`, naming the observation. Two causes reach it. The contract's repository
  changed under an open record. Or two adapters stepped one run at once, so the first resolved
  a record the second still sends, which the serial-step contract excludes (D15). Either way
  it fails loud rather than being retried without the observation.

## Test seams

Assertions read exit codes, stdout objects, the `control` requests the world logs, refs and
persisted ledgers, and the argv of logged external effects, as the world already logs `gh` and
`workflow-state`. They never count calls to internal helpers (D11).

- **`observe_all`**, by import, in `tests/test_verification_observe.py` over `ObserveCase`
  (the bare `origin`, the publisher, the eval fixture project), with the test's `HOME`,
  hermetic Git and `PATH` patched into `os.environ` (the in-process precedent of
  `actions_world` and `host_world`):
  - an empty list leaves the tracking ref unmoved;
  - two requirements give two observations, equal to what `observe` prints for each;
  - an unreachable `origin` refuses both with the `git fetch` reason, and returns no
    observation;
  - a `git` shim like c1's, failing `ls-tree` for one path only, refuses only that path's
    requirement;
  - a malformed element raises `BlockerRefused` before the fetch, with the ref unmoved.
- **Gathering**, through `orchestrate-control step`, in a new class of
  `tests/test_orchestrate_control.py`:
  - **The world.** `OrchestrateWorld` gains a local bare `origin` cloned from its project, a
    publisher clone and a `git` shim that logs `fetch` argv and runs the real Git. Only the
    gathering tests install them.
  - **Parking.** Through the source `workflow-state suspend --verification-input -` after
    `seed_spawn`, with a failure whose entries are read from the bare `origin` independently
    of the tool.
  - **Cases.** The Demo's five cases, each with the logged fetches, the logged requests'
    `verification` and the ready object. Two blockers in one step give one fetch and two
    observations in bootstrap order. A bootstrap whose `verification` element is malformed
    reaches the command through the world's fault and passthrough rules and refuses at
    `bootstrap`.
  - **Existing tests.** They keep passing without an `origin`, because a step with no
    requirement fetches nothing.
- **Skill contracts** (agent-helpers rule 6), in `test_workflow_skill_contracts.py`:
  - from-issue's two `suspend` templates' flags, and the second's `--blocked-on
    verification`. The existing verb-keyed template map keeps the first line;
  - the cause-list order with `verification` before the reaper's parenthesis;
  - the lifecycle-call rule's `--verification-input -`;
  - acquire-direct's item-5 key set, behaviourally: a `suspended` reply with exactly those
    members validates through the source wire validator in process (issue 544 D16). Item 5
    is ordered after `kind: terminal`;
  - final-review's declaration, behaviourally: its JSON, with each placeholder filled by a
    valid value, passes `normalize_declaration`.
- **Shell examples.** `COMMAND_VOCABULARY` in `test_shell_example_contracts.py` gains
  `verification-observe`. A `text`-fence line counts as an example only with a vocabulary
  head, so this makes final-review's call vetted as a sanctioned lifecycle call: allowed whole,
  quoted heredoc (parent D18).
- **Integration.** The focused modules, `test_instruction_load`, `test_skill_lint`, the
  `test_verification_*` modules, `test_control_cutover` and `test_attempt_migration` (AC1's
  migration, helper-generation and stale-version cases), then `just agent-workflow-tests` and
  `just build`.

## Out of scope

- Any ledger schema step and any interface version, including the control request and reply,
  the bootstrap, direct-owner and the step input.
- Any change to the failure, observation or requirement shapes, the identity, the secret-shape
  rule, the adapter's guard or its CLI modes.
- `lifecycle_guard.py`, the permission allow list's entries and the command table.
- `orchestrate-issues` (both trees), acquire-durable, AUTO.md, `rollover.md`,
  `delegated-owner.md` and sdd `SKILL.md`.
- Syncing a resumed worktree with the change that resolved its record. That would be a
  mid-delivery sync under sdd's fixed base, and the resumed owner runs its existing flow.
- Classifying failures outside sdd's Final verification, such as ship-issue's verification
  reuse, and verification blockers on delivery remainders.
- An abandonment route or human override for a parked attempt, and a ledger marker naming the
  helper that wrote a run.
- Live ledgers, retained attempts, host activation (`just switch`) and applying the
  `instruction-budget-raise` label.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Scope: parent Tasks 6–7, re-grounded. In: batched observing in the adapter module; `orchestrate-control` gathering and `verification_refusals`; sdd's classification and the from-issue suspension template; acquire-direct's answer and `suspended` relay; the ceilings; both READMEs, the docstring and the allow-list comment; the skill-contract and shell-vocabulary tests. No schema, interface or shape change. | Issue 546 "What to build" and AC; issue 543 D1 (batched observing is c4's); issue 544 and 545 Out of scope lists. | Parent Task 6–7 text verbatim, which calls APIs that do not exist (D13). Folding in acquire-durable gathering (parent D16 rejects it). |
| D2 | `observe_all(repo_root, requirements) -> (observations, refused)` lives in `verification_observe` and shares `observe`'s path. It validates all first and raises with no I/O; an empty list does no I/O; one resolution, one fetch and one commit serve all; a fetch or resolution refusal refuses all; a read refusal refuses one. Refusals are `(blocker_id, reason)`. No CLI mode. | Issue 543 D6, D8 (the adapter is the only I/O home; "c4's step owns batching and its one-fetch bound"), D12; agent-helpers rules 2–3; The Bar DRY. | `observe` per requirement, which fetches once per blocker. Running the CLI per requirement. Batching in `orchestrate_control` over the adapter's private functions. An `observe-all` CLI mode no caller needs (YAGNI). |
| D3 | Gathering runs inside the `bootstrap` step on every step: every bootstrap requirement, the first call only, `[]` on the chained second. `verification_refusals: [{blocker_id, detail}]` follows bootstrap order, with `detail` collapsed and cut to 300 characters. A malformed list refuses at `bootstrap`; an unobservable requirement never refuses. | Issue body; issue 545 D6 (the bootstrap is the one read before control; resolution commits in the first call's write); parent D10, D22; The Bar "Truthful terminal states", "Defense in depth". | A ninth step name, which moves every `completed_steps` pin for a step that never refuses. Gathering from control summaries, which needs a second round that a dispatching reply skips. Filtering by session issues, which strands a run-level record. Resending on the second call, which names a resolved record and is refused. |
| D4 | `orchestrate-control`'s only new write is the fetch's update of `refs/remotes/origin/<branch>` and its objects, made only when the bootstrap lists a requirement. The docstring, `python/README.md` (both sections) and the `default.nix` allow-list comment say so. No allow entry, guard or command-table change. | Issue 546 (default.nix comment); issue 543 D6, D9 (the adapter's only write; `git fetch` already allowed); The Bar: re-point living docs. | A new permission entry for an in-process fetch, which the allow list never sees. Leaving "writes no file" and "only ledger writes" text, which the fetch makes false. |
| D5 | sdd's Final verification classifies before its repair, under a lifecycle identity. It runs `verification-observe failure` before any release or reap: exit 0 goes to from-issue's suspension procedure with `blocked_on=verification`, a refusal repairs, and a product, test or build failure never qualifies. The procedure gains the cause and a second literal `suspend … --verification-input -` heredoc template, and the lifecycle rule lists that flag. | Parent D13; issue 543 D7 (the adapter's guard decides an attempt's own input change); `launch-scope reap` deletes the scratch root; issue 432 (gate and suspension are literal templates); sdd's `blocked_on=deadline` routing precedent; The Bar token economy (reliably emitted forms). | The adapter call inside the suspension procedure (parent Task 7), which runs after the reap and loads into the Phase 0–5 controller that never verifies. A prose instruction to splice the flag into the first template, which saves bytes but is easier to emit wrongly. |
| D6 | acquire-direct answers `verification` by running `expects.build` (`<ledger_repo_root>` filled) on the requirement less `expects` and appending the output. The builder-refusal sentence is widened to the adapter. Item 5 checks `suspended`'s seven members and prints `Suspended (blocked_on=<blocked_on>). Resume: <reentry>`, then stops. The clearing rule names `suspended`. | Issue 545 D7, D10 (`expects.build` and its catalogue); issue 544 D7 (the envelope); `_wire.py`'s `suspended` members; parent D9, D21. | A literal `verification-observe observe` line, a second copy of the catalogue constant. Hard-coding `blocked_on=verification`, which is false for any other cause the validator admits. |
| D7 | `orchestrate-issues` (both trees), acquire-durable, AUTO.md, `rollover.md`, `delegated-owner.md` and sdd `SKILL.md` do not change. | Parent D10 (adapter duties unchanged), D16; issue 545 D11; orchestrate-issues §5 already reports a parked issue as paused; the generic `Suspended (…)` relays. | A §5 duty for `verification_refusals`, which grows a Claude-only hot document outside the issue's list for a diagnostic the transcript already holds. |
| D8 | Text grows only in from-issue `SKILL.md`, `acquire-direct.md` and sdd `final-review.md`. Every breached hot ceiling (`from-issue-controller` and `implementation-owner` on both hosts, `orchestrated-issue-owner` if breached) and the corpus ceiling rise to exactly their final-head measure, with a note sentence per raised profile naming #228 (issue 546). The user applies the label. | Measured `instruction_load report` and `measure_corpus` at the base (94, 140, 588 and 5 bytes of headroom); CLAUDE.md (only the user labels a raise); issue 546 ("only this child raises instruction ceilings"); the `#155 D10` note precedent. | Trimming unrelated text to fit, outside scope. Moving procedure into unmeasured docs, which owners never read. A ceiling above its measure, which the issue rules out ("exactly") and the gate refuses past 5%. |
| D9 | The existing `### Verification blockers` README subsection is extended. Its c3 known-limitation sentence becomes the caller protocol, then four known limitations: paths only (an outage keeps `transport`), observed per step (`finalize` when only parked work remains), no sync on resume, and a changed repository strands the step. | The Bar DRY (one home per contract) and "known limitations belong in docs"; issue 545 D11 left that sentence for c4; parent's out-of-scope sync. | A new `### Shared verification blockers` sibling (parent Task 7), which splits one protocol across two subsections. Leaving the limitations unstated. |
| D10 | AC1's source-helper rule is documented in that subsection. Until `just switch`, a run migrated by a reviewed source helper is driven only from that checkout: the source `workflow-state` with its shim first on `PATH`, and the `agent_tools` commands that run it by name from the same `python/`. No ledger marker. AC1's evidence is that rule, c2's older-helper refusal tests and the gathering tests, which drive source `orchestrate-control` with the source `workflow-state` shim first on `PATH`. | Parent AC4 and D12; issue 544 D9 (`unknown_schema`, nothing written); `launch_commit`, `launch_scope`, `sdd_gate` and `orchestrate_control` run `workflow-state` by name. | A writer marker in the ledger, new state the version refusal already covers (parent D12). An automated check of operator behaviour, which no test can observe. |
| D11 | Test seams: `observe_all` by import in `test_verification_observe` with the environment patched in. Gathering through `orchestrate-control step` in `test_orchestrate_control`, over `OrchestrateWorld` plus a local `origin`, a publisher and a fetch-logging `git` shim that only those tests install. Behavioural skill-contract pins: the two templates' argv, the cause order, item 5's key set validated by the wire, and the declaration through `normalize_declaration`. `verification-observe` joins the shell vocabulary. | Agent-helpers rules 5–6; The Bar "Tests that can fail"; the world's `gh` and `workflow-state` effect logs; issue 543 D16's delegating `git` shim; issue 544 D16's in-process validator pin; parent D18 (adapter examples vetted, not argv-pinned). | Parent Task 6's `ObserveWorld` (it does not exist). A new test module for one class. Pinning `verification-observe` argv in skill contracts, which rule 6 does not admit. English-phrase pins. |
| D12 | Concurrency: a fetch lost to Git's ref lock is a refusal, retried next step, and a lost owner `failure` repairs. A record listed `open` at `bootstrap` stays `open` until this run's `control`, because one adapter calls `step` serially and direct runs are separate. A refused observation refuses the step at `control`, which happens only under a changed contract repository, and is never retried without it. | Triage `concurrency_or_persistence`; issue 545 D4, D15; issue 543 D6, D12; `orchestrate-control`'s serial-step contract; The Bar "Root causes". | Retrying `control` without observations after a refusal, which parses stderr prose and hides a contract change. Reading the tracking ref after a failed fetch (issue 543 D6). |
| D13 | Re-grounding against main: there is no `observe_all` (D2) and no `ObserveWorld` (D11); objects carry `mode` (issue 543 D17); the README subsection exists (D9); the adapter call moved out of the suspension procedure (D5); parent Task 7's `verification-observe` argv pin is replaced by vocabulary vetting (D11); `control_request` already sends interface 4 with `verification` (issue 545 D11). | Live `verification_observe.py`, `orchestrate_control.py`, `tests/orchestrate_world.py`, README § Lifecycle helpers and `test_shell_example_contracts.py` at the base. | Following parent Tasks 6–7 verbatim, which calls missing helpers and pins text rule 6 forbids. |
| D14 | Grill: sdd declares a blocker only when every failing declared command qualifies, and then the first failing command in run order. A mix holding any change-caused failure takes today's repair, whose second failure is Residuals. A resumed attempt that fails on another command parks on that failure's own identity. | Parent D13 (a change's failure is never relabelled); one `suspend` names one failure; issue 544 D3 (one record per identity); the stall bound counts every park (issue 544 D6). | Parking on the qualifying failure while a change-caused one is pending, which defers a repair the attempt must make anyway and spends the stall bound. Classifying again after the repair, more hot text for a rare case (YAGNI). |
| D15 | Grill: `start` never gathers, because it makes no control call. `verification_refusals` is additive to an unversioned output that its readers take by member name, and its `detail` is output only, never persisted. D12's refused-observation case also covers two adapters stepping one run at once, which the serial-step contract excludes. | `start` runs `init-run` only; no validator pins the ready key set (orchestrate-issues and the tests read named members); python/README "one adapter process calls `step` serially per run". | Versioning the ready object for an additive member, which every reader would have to thread. Gathering at `start`, which has no request to carry the observations. |
| D16 | Plan: the issue-227 growth pin (`assert_no_larger_than_base`, base `8d0bbc25`) drops `from-issue/SKILL.md` from both of its lists, because D5's second template and cause grow it about 414 bytes against 98 bytes of pinned headroom; every other pinned document keeps its pin. | Issue 227 D14 (the pin stood in for a raise that delivery could not get); #155 D10 (the ceilings are the standing growth gate, raised here under the user's label per D8); measured at the base: 30513 bytes against the pinned 30611. | Funding the growth by cutting unrelated `SKILL.md` text, which D8 rules out and many pins read. Moving the second template into `final-review.md`, which splits the `suspend` verb's one home (reverses D5). Re-pinning a byte count, a second home for one budget. |
| D17 | Plan, refines D11: the two behavioural skill-contract pins run their source validators in a child with `PYTHONPATH=python/`: item 5's reply through the source `artifact-budget validate-report --boundary workflow-response` under a temporary `HOME` holding the source policy, the declaration through `verification_blocker.normalize_declaration`; each also shows a near miss refused. | `agent-installed-skill-tests` runs `test_workflow_skill_contracts.py` with no package on its path (issue 505 D8, its `skill_sections` helper); `test_workflow_state` and `_delivery_model_fixtures` import `agent_tools` when loaded. | An in-process import, which breaks that module's import in the installed tier. Reading `_wire.py`'s member set by AST, which pins a constant rather than the validator's verdict. |
| D18 | Phase-5 review (Codex B1, S1): AC2 becomes `code (classified)` and is graded in the order its records exist. Its final-head clause rides the Declared verification line, which Final verification runs after the acceptance record's commit; its process clauses are cited from the SDD workspace `progress.md` (each task's `Task N: complete` and `Delivery gate:` lines, which `sdd-gate next` writes only after its projection exits 0) and the separately ledgered final verdicts, which the controller confirms before writing the `Verdict`. D5's step-4 block also names every repair case: no lifecycle identity, no failing command (a `record` exit 3 or helper exit 2 alone), a change-caused failure, or a refusal; it declares only when at least one command failed and all failing ones qualify. | final-review.md commits the acceptance record before Final verification, and an `evidence` `met` needs an existing measured row (conformance-reviewer-prompt.md, `evidence`); the `code` rule grades a Declared-verification check `in final verification`. D5's spec text excludes `record` exit 3 and helper exit 2 from classification, which the inserted block left implicit. | Keeping AC2 `evidence` with a fixer filling its row after a forced first-pass `unverified`, a fix wave by construction. Moving Final verification before the record, which changes sdd's procedure outside this child's scope. |
