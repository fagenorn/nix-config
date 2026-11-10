---
area: Delivery
budget: 200 lines
---

# Delivery

Delivery turns one tracker issue into a merged change through the agent skills, the Workflow programs that drive them, the plan and the test suite. It owns the choice of lane and the bookkeeping a delivery leaves behind.

## Language

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

**Suite member**:
One test file or script named in the project's declared agent-workflow test recipe. The suite runner schedules the members by recorded duration, and the last member is pinned.
_Avoid_: test target

**Triage record**:
The owner's structured input to lane triage, read from standard input. Lane triage turns it into a verdict of hits, lane and mode without writing anything.
