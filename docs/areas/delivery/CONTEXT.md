---
area: Delivery
budget: 200 lines
---

# Delivery

Delivery turns one tracker issue into a merged change through the agent skills, the Workflow programs that drive them, the plan and the test suite. It owns the choice of lane and the bookkeeping a delivery leaves behind.

## Language

**Awaiting look**:
The stage a delivery of a marked issue stops at after verify, with its branch up to date with the integration branch, pushed and its pull request open, holding no land lock and merging nothing; the owner's approve or changes answer resumes it (issue 1139).
_Avoid_: hold (a hold is the post-merge verification hold)

**Code map**:
A navigation hint a design or planning agent leaves for the next agent: the modules, seams and contracts a task touches, each with its code and tests. It is a lead to check against the tree, never an authority, and it lives outside the working tree so it is never committed.
_Avoid_: context file, index

**Delivery**:
The work of carrying one issue from claim to merge on its own branch and worktree. A delivery ends when the integration branch holds the change and its evidence criteria are met or handed to a Verify block.

**Lane**:
The route an issue takes to merge: the direct lane for a small concrete change, the standard lane for a specced and planned one. The triage record decides which applies.
_Avoid_: track, tier

**Light lane**:
The project-declared reduced route for changes that a project's contract names as light. A project that declares none, or `null`, does not support it, and the verdict falls back to the standard route.

**Look approval**:
The owner's answer to a look, an `agent:look` marker by an OWNER or MEMBER naming the issue, the pull request, the head commit, `approved` or `changes`, and the console message it came from (issue 1138). It covers exactly that head; the latest one for a head decides.

**Look marker**:
An acceptance criterion of kind human written exactly `- [ ] [human] before merge: <what the owner looks at> — measured: <who judges, where>`; it makes the issue need the owner's look at its pull request head before merge (issue 1138). Read only by `agent_tools.delivery.look_marker`. `look-lint` refuses a body with a criterion line that is a near miss of it (issue 1141). An ordinary `[human]` criterion or a hold in prose is not one.

**Suite member**:
One test file or script named in the project's declared agent-workflow test recipe. The suite runner schedules the members by recorded duration, and the last member is pinned.
_Avoid_: test target

**Triage record**:
The owner's structured input to lane triage, read from standard input. Lane triage turns it into a verdict of hits, lane and mode without writing anything.
