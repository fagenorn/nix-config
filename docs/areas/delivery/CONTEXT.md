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

**Lane**:
The route an issue takes to merge: the direct lane for a small concrete change, the standard lane for a specced and planned one, the live-fault lane for a declared live fault. A live-fault declaration selects the third.
_Avoid_: track, tier

**Live-fault lane**:
The route of an issue with a standing live-fault declaration (ADR-console-099), selected by that declaration and with no plan. One implementer gives a failing-then-passing test, and the lane refuses a diff over 80 changed lines outside tests or over 3 files, or one touching authentication, secrets or a guard. One diff review follows, where only a critical finding blocks and the rest become follow-up issues. Everything is bound to one commit, and the time from declaration to a green pull request is recorded (ADR-delivery-013).
_Avoid_: hotfix lane

**Look approval**:
The owner's answer to a look, an `agent:look` marker by an OWNER or MEMBER naming the issue, the pull request, the head commit, `approved`, `fix` (approved with one worded fix) or `changes`, and the console message it came from (issue 1138). It covers its head and every later head of that pull request that keeps it (issue 1211): the approved head is an ancestor, and no later commit of the pull request changed a look file other than by a clean merge of the integration branch, except one commit under a `fix` answer. The latest answer for a head decides. A delivery that lands under it ticks the look marker's box (`look-approval tick`, issue 1186). The console records an approval the owner gives on a look card; a delivery reads it (ADR-console-074).

**Look file set**:
The path globs, declared per area in `.github/look-files.json` on the integration branch, whose change a look approval covers (issue 1211); a pull request is judged by the set at its base commit, never its own. An area with none keeps one approval per head.

**Look marker**:
An acceptance criterion of kind human written exactly `- [ ] [human] before merge: <what the owner looks at> — measured: <who judges, where>`; it makes the issue need the owner's look at its pull request head before merge (issue 1138). Read only by `agent_tools.delivery.look_marker`. `look-lint` refuses a body with a criterion line that is a near miss of it (issue 1141). An ordinary `[human]` criterion or a hold in prose is not one.

**Suite member**:
One test file or script named in the project's declared agent-workflow test recipe. The suite runner schedules the members by recorded duration, and the last member is pinned.
_Avoid_: test target
