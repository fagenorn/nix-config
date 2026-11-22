---
area: Delivery
budget: 200 lines
---

# Delivery

Delivery turns one tracker issue into a merged change through the agent skills, the Workflow programs that drive them, the plan and the test suite. It owns the choice of lane and the bookkeeping a delivery leaves behind.

## Language

**Awaiting look**:
The stage a delivery of a marked issue stops at after verify, with its branch up to date with the integration branch, pushed, its pull request open and every required check at that head green (a red one fixed first, within the delivery's one red-check fix; issue 1373), holding no land lock and merging nothing; the owner's approve or changes answer resumes it (issue 1139).
_Avoid_: hold (a hold is the post-merge verification hold)

**Code map**:
A navigation hint a design or planning agent leaves for the next agent: the modules, seams and contracts a task touches, each with its code and tests. It is a lead to check against the tree, never an authority, and it lives outside the working tree so it is never committed.
_Avoid_: context file, index

**Delivery**:
The work of carrying one issue from claim to merge on its own branch and worktree. A delivery ends when the integration branch holds the change and its evidence criteria are met or handed to a Verify block.

**Enforcer**:
A test or lint that fails when a standard is broken (issue 1412).
_Avoid_: check (a check is the Verification area's)

**Engine**:
The deterministic program in the platform package that runs a delivery as a procedure, with no model choosing the next step. `engine check` validates every procedure before any run. A run is recorded as a directory under `~/.agents/state/engine/runs/` whose append-only `events.jsonl` is the single source of truth, and `engine status <issue>` prints the state one fold derives from it (issue 1511), and `engine deliver <issue>` runs a procedure of command, agent and decide steps to `done` or a stop and prints one result line (issue 1512); an `agent` step runs as one headless session through the account launcher and is graded only by its structured reply (issue 1514).

**Grader**:
A pure function in the engine that turns stored results into an outcome for a `decide` step.

**Judged rule**:
A standard no enforcer cites, applied by a reviewer (issue 1412).

**Lane**:
The route an issue takes to merge: the direct lane for a small concrete change, the standard lane for a specced and planned one, the live-fault lane for a declared live fault. A live-fault declaration selects the third.
_Avoid_: track, tier

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

**Standard**:
One rule under one heading in a layer file, with a stable id, applied to every change within its layer file's scope: the bar to every change, a stack or project shard to the changes its globs match (issue 1412).

**Step**:
One entry of a procedure: an id, a stage, a kind (`command`, `agent`, `decide`, `group` or `call`), what it reads, a map from each outcome to the next step, a stop or `done`, a visit bound and whether it changes something.

**Stop**:
A named end state of a run that is not `done`, with what it needs (an owner decision, an owner look, a retry or nothing) and the step a resumed run re-enters.

**Suite member**:
One test file or script named in the project's declared agent-workflow test recipe. The suite runner schedules the members by recorded duration, and the last member is pinned.
_Avoid_: test target
