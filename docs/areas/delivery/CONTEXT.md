---
area: Delivery
budget: 200 lines
---

# Delivery

Delivery turns one tracker issue into a merged change through the agent skills, the Workflow programs that drive them, the plan and the test suite. It owns the choice of lane and the bookkeeping a delivery leaves behind.

## Language

**Attempt**:
One try at delivering an issue, from the claim that starts it to the end of that claim. A delivered attempt ended with its change merged into the integration branch, and its duration runs from the claim's creation to that merge, both read on the tracker; an attempt that stopped or still runs is not delivered. A schema-3 project's attempt budget is 1.5 times the 90th percentile of its last 20 delivered attempts' durations, or 240 minutes until it has 20 (ADR-project-contract-016).
_Avoid_: run (a run is the engine's)

**Awaiting look**:
The stage a delivery of a marked issue stops at after verify, with its branch up to date with the integration branch, pushed, its pull request open and every required check at that head green (a red one fixed first, within the delivery's one red-check fix; issue 1373), holding no land lock and merging nothing; the owner's approve or changes answer resumes it (issue 1139).
_Avoid_: hold (a hold is the post-merge verification hold)

**Cleanup issue**:
An issue the `cleanup-issue` command files from the integration branch's never-rise counts: one open per project, the rule with the smallest count above zero first, listing the whole files one delivery clears. Its body carries the marker `<!-- agent:cleanup v1 rule=<id> -->`, which alone identifies it when a trusted author wrote it (ADR-delivery-017). The one open slot is shared with a fix change.

**Code map**:
A navigation hint a design or planning agent leaves for the next agent: the modules, seams and contracts a task touches, each with its code and tests. It is a lead to check against the tree, never an authority, and it lives outside the working tree so it is never committed.
_Avoid_: context file, index

**Delivery**:
The work of carrying one issue from claim to merge on its own branch and worktree. A delivery ends when the integration branch holds the change and its evidence criteria are met or handed to a Verify block.

**Enforcer**:
A test or lint that fails when a standard is broken (issue 1412).
_Avoid_: check (a check is the Verification area's)

**Fix change**:
A pull request the `cleanup-issue` command opens on the integration branch for the picked rule when its enforcer's autofix changes files: only what the autofix wrote to the listed files, the marker `<!-- agent:cleanup-fix v1 rule=<id> -->`, the count before and after; it takes the one cleanup slot (ADR-delivery-021).
_Avoid_: autofix PR

**Engine**:
The deterministic program in the platform package that runs a delivery as a procedure, with no model choosing the next step. `engine check` validates every procedure before any run. A run is recorded as a directory under `~/.agents/state/engine/runs/` whose append-only `events.jsonl` is the single source of truth, and `engine status <issue>` prints the state one fold derives from it (issue 1511), and `engine deliver <issue>` runs a procedure of command, agent and decide steps to `done` or a stop and prints one result line (issue 1512); an `agent` step runs as one headless session through the account launcher and is graded by its structured reply (issue 1514) unless a bound fires. Every step runs within platform-held bounds, its role's wall time, turns and spend for an agent step and its command's wall time for a command step, and a fired bound is the outcome `out-of-bounds`, which an agent step outside a group must map (issue 1520). Before every command it runs, `engine deliver` calls the lifecycle guard the host's settings name as the Bash hook, and a refusal, a timeout or an unrunnable guard is the outcome `refused`. A command runs marked as an agent session, so the pre-push hook judges a push inside a wrapper as it does in a session; like a session, the guard does not see another lifecycle verb inside a wrapper script (ADR-guard-004, ADR-guard-009) (issue 1515). An agent step with no valid structured answer is resumed once on the same session, then ends as `no-reply`; reply schemas keep to one subset; and `engine deliver` starts no run on a host whose settings load no lifecycle guard hook (issue 1525). `engine stop <issue>` asks the running run to end its current step's process group and stop at `stopped-by-request`, which needs a retry (issue 1524). A run that ends in `done` or a stop appends one summary line to `~/.agents/state/engine/history.jsonl`, kept 180 days, and the engine's start deletes a run directory 14 days after its issue closed (issue 1519). A second `engine deliver` on an open run continues it on the run's own procedure copy, re-entering at the earliest stale result, else at the interrupted step or the stop's re-entry step (issue 1516). A session holds one of the engine route's agent slots of its root run and waits for a free one (issue 1522, ADR-delivery-018). A continued run whose procedure copy has a format the engine does not read ends at the stop `superseded` and the same call starts a new run; otherwise the continue first ends the interrupted step's leftover process group, matched by pid and start time, and an interrupted agent step resumes the session recorded for its visit (issue 1523). A `group` step runs its members beside each other and a `call` step runs a child procedure as runs of their own (issue 1517); a continue of a `call` interrupted inside a child run walks that child run again in place, with its interrupted session resumed and no new child run (issue 1886), and the shipped `deliver` procedure's calls hold their results (`run`), so a continue after the merge goes on from close-out and a stop of the landing is re-entered at the verification. The shipped `deliver` procedure runs `setup` (the contract, the review capability, the preflight gates, the claim named for the run, the worktree and the look marker) and then a lane step, a `decide` step on the `lane-rule` grader that answers direct or standard by the lane rule over the issue the `issue` step read (issue 1675), and a continue from its stops reads the issue again; the direct lane then runs `direct` (implement, a review beside the independent review, one fix round) and `verify` (each declared verification id once in the worktree, or the contract's pre-pull-request commands when it declares them, with each command's selection and slot wait and hold in its stored result, and none after a clean sync that changed none of the branch's files since its last pass; on a failure, one rerun at the same head of ids failing outside the diff (a pass kept as flaky), then up to two reviewed fixes counted over the delivery's verify runs, a rerun of the failed ids only after an attested whitespace-only fix of the failing paths, and a retest of a fix that recorded no test, stopping `verify`, `verify-unrelated`, `verify-fix` or `verify-fix-review` (issue 1536)) to a verified branch (issue 1529, issue 1682). The direct lane then runs `land` (claim renewal, push, pull request, land lock, check poll, lock re-check, merge pinned to the verified head, each lifecycle command judged by the guard and graded by the reading after it, the lock released on every exit after it was taken) and `close-out` (worktree, fast-forward, branch, claim, issue) to a merged pull request and a closed issue (issue 1530); when a criterion is evidence or human, `close-out` first holds the issue as the program does (the look check, the drafted checks and their gates, the regrade of the code criteria (the stop `code-unmet`), the lint, the split issues, one hold comment, the `needs-verification` label and one verification run) and the run ends `done` with the issue open (issue 1541). The `land` procedure calls `land-attempt` and frees the land lock once for every end; the attempt recovers as the standard program does (a merge probe and conflict resolution before the lock, a sync under it, one sync-review fix and one red-check fix per delivery counted over the delivery's runs, three pending waits, lock waits within 3 retries and 6 hours, three merge refusals for being behind and one more poll after a policy refusal) (issue 1542). A review finding carries a kind from a closed list and, for a breach of a standard, a rule id, which the engine blanks when it stores the reply if no standards layer defines it; a fix reply names the findings it declines with a reason, and neither changes what blocks or how many rounds run (issue 1535). Conformance's CI purpose gives every procedure file the platform ships, found by listing, the verdict of `engine check` (the procedure check and the size caps) against the judged project's commands, and `engine deliver` refuses a new run whose procedure set that verdict refuses before it creates a run directory, printing `engine check`'s refused line; a continued run is not judged again (issue 1527).

**Fixture project**:
A small project adopted with the adoption command like any other and used only for proof runs of the engine. Until the forge holds one (issue 1538), the tests build and adopt it locally (issue 1526).

**Grader**:
A pure function in the engine that turns stored results into an outcome for a `decide` step.

**Judged rule**:
A standard no enforcer cites, applied by a reviewer (issue 1412).

**Lane**:
The route an issue takes to merge: the direct lane for a small concrete change, the standard lane for a specced and planned one, the live-fault lane for a declared live fault. A live-fault declaration selects the third. A lane-less fresh run outside plan mode, given no spec and no decisions, takes the direct lane by the lane rule of issue 1675 (`issue-setup lane` prints it): the issue's body names at most 3 files and has 1 to 3 acceptance criteria, carries no look marker and names no lane path, a lane path being one a repository declares in `.github/lane-paths.json` (its guard, release and secrets areas; with none declared, every issue goes standard). A lane the caller gives wins, and a live-fault declaration keeps the live lane.
_Avoid_: track, tier

**Lint-time issue**:
An issue the `lint-time` command files when the median total lint time of the last 20 completed Conformance runs on the integration branch is over 60 seconds, naming the slowest lint by its own median: at most one open per project, counted apart from the cleanup issue. Its body carries the marker `<!-- agent:lint-time v1 -->`, which alone identifies it when a trusted author wrote it (ADR-delivery-020).

**Live-fault lane**:
The route of an issue with a standing live-fault declaration (ADR-console-099), selected by that declaration and with no plan. One implementer gives a failing-then-passing test, and the lane refuses a diff over 80 changed lines outside tests or over 3 files, or one touching authentication, secrets or a guard. One diff review follows, where only a critical finding blocks and the rest become follow-up issues. Everything is bound to one commit, and the time from declaration to a green pull request is recorded (ADR-delivery-013).
_Avoid_: hotfix lane

**Look approval**:
The owner's answer to a look, an `agent:look` marker by an OWNER or MEMBER naming the issue, the pull request, the head commit, `approved`, `fix` (approved with one worded fix) or `changes`, and the console message it came from (issue 1138). It covers its head and every later head of that pull request that keeps it (issue 1211): the approved head is an ancestor, and no later commit of the pull request changed a look file other than by a clean merge of the integration branch, except one commit under a `fix` answer. The latest answer for a head decides. A delivery that lands under it ticks the look marker's box (`look-approval tick`, issue 1186). The console records an approval the owner gives on a look card; a delivery reads it (ADR-console-074). An `approved` approval that records the digest of its pictures also carries across a head that only merges the integration branch in, when a look carry names it (issue 1566). A look carry is an `agent:look-carry` line naming the approved head and a later head of the same pull request, written by `look-approval carry` when only merges of the integration branch came in and the re-rendered picture ids equal the approved ones; it is never an approval, and such an approval is kept across later heads by a look carry alone, never by the look file rule. An `approved` approval with no pictures carries across merges of the integration branch the same way when its look carry names the look-files rule and the pull request's look-file diff is unchanged (issue 1597).

**Look file set**:
The path globs, declared per area in `.github/look-files.json` on the integration branch, whose change a look approval covers (issue 1211); a pull request is judged by the set at its base commit, never its own. An area with none keeps one approval per head, except where a look carry carries it across merges of the integration branch (issue 1566); the look-files carry restricts the pull request's diff to every set's globs (issue 1597).

**Look marker**:
An acceptance criterion of kind human written exactly `- [ ] [human] before merge: <what the owner looks at> — measured: <who judges, where>`; it makes the issue need the owner's look at its pull request head before merge (issue 1138). Read only by `agent_tools.delivery.look_marker`. `look-lint` refuses a body with a criterion line that is a near miss of it (issue 1141). An ordinary `[human]` criterion or a hold in prose is not one.

**Outcome**:
The one named result a step's grade produces; the only thing a transition reads.

**Procedure**:
One JSON file in the platform package that describes a delivery as a finite state machine: a header (its `format`, an optional keep-alive command, its stops) and a flat list of steps, with no expression and no code. Its prompts are sibling Markdown files.

**Router**:
The platform command `router` that computes, with no model and no network, the routed set one change is given at one stage: from the change's paths at plan stage and from its diff from implementation on (issue 1509).
_Avoid_: loader

**Routed set**:
The router's answer for one change at one stage: the bar, the stack shards its file extensions choose, the project shards whose `governs` globs match its paths, the stage's hint file, the decision records its changed files cite, a one-line index (id and title) of the records of each context-map area its paths match, each routed shard's rule ids, the platform revision and the total size in bytes. It names files and pastes none, and a wide change is never cut (issue 1509).

**Standard**:
One rule under one heading in a layer file, with a stable id, applied to every change within its layer file's scope: the bar to every change, a stack or project shard to the changes its globs match (issue 1412). The disposition of a review finding is what became of it, computed by a pure function from a run's stored results and never set by hand or asked of a model: fixed (a re-review closed it), declined (the implementer declined it and the re-reviewer accepted), filed (it became a follow-up issue, whose body carries the finding's rule and kind), dropped (a minor finding not acted on) or open (still open when the run stopped). A finding is named by its review step and its place in that step's list, as lite-review:2, unique within one review round (issue 1535).

**Step**:
One entry of a procedure: an id, a stage, a kind (`command`, `agent`, `decide`, `group` or `call`), what it reads, a map from each outcome to the next step, a stop or `done`, a visit bound, whether it changes something, how long its result holds (`run`, `head`, `live` or `read`, a `live` command that changes nothing and whose answer, run again, keeps an interrupted session of a later step in place) and, on a command step that changes something, the `check` command that reads whether its effect already happened (issue 1516).

**Stop**:
A named end state of a run that is not `done`, with what it needs (an owner decision, an owner look, a retry or nothing) and the step a resumed run re-enters.

**Suite member**:
One test file or script named in the project's declared agent-workflow test recipe. The suite runner schedules the members by recorded duration, and the last member is pinned.
_Avoid_: test target

**Suppression**:
The marker that names a rule id and a reason and leaves its line's finding out of that rule's count; without either it is itself a violation (ADR-project-contract-019).
