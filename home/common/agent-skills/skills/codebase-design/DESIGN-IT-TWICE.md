# Design It Twice

When the user wants alternative interfaces for a chosen deepening candidate, design it several ways in parallel (Ousterhout: the first idea is rarely the best). Uses the vocabulary in [SKILL.md](SKILL.md).

## 1. Frame the problem space

Write a user-facing explanation of the candidate: the constraints a new interface must satisfy, the dependencies it relies on and their category, and a rough code sketch that makes the constraints concrete (not a proposal). Show it, then start step 2 at once; the user reads while the sub-agents work.

## 2. Spawn sub-agents

Spawn 3 or more sub-agents in parallel at the `issue-owner` tier (each produces a design, not a bounded lookup), each with a **radically different** constraint:

- Agent 1: "Minimize the interface — aim for 1–3 entry points max. Maximise leverage per entry point."
- Agent 2: "Maximise flexibility — support many use cases and extension."
- Agent 3: "Optimise for the most common caller — make the default case trivial."
- Agent 4 (if applicable): "Design around ports & adapters for cross-seam dependencies."

Each brief is technical and separate from step 1's explanation: file paths, coupling details, the dependency category, what sits behind the seam, the SKILL.md vocabulary, and the project's domain language. Take that language the way `doc-grounded-questions` does: the context map and its area context files where the project has them; skip them silently where it does not.

Each sub-agent returns:

1. The interface: types, methods, parameters, invariants, ordering and error modes.
2. A usage example.
3. What the implementation hides behind the seam.
4. The dependency strategy and adapters.
5. Trade-offs: where leverage is high and where it is thin.

## 3. Present and compare

Present the designs one at a time, then compare them in prose by **depth**, **locality** and **seam placement**. Recommend the strongest, or a hybrid when parts combine well; be opinionated.

In an autonomous run there is no one to show step 1 to or to wait for: the recommendation is the answer, recorded as a decision-ledger row.
