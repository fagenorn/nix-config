# ADR-guard-008 — Both merge arms keep the required-check floor

- **Status:** accepted
- **Decided in:** issue 116 (guard/core decision), issues 476, 552, 554

## Context

A merge is the verb that puts unreviewed code on the default branch, so the guard demands protection with required status checks before it admits one. Two cases pressed on that demand: a repository whose plan cannot protect its default branch (the forge answers 403 for the protection read), and the release core, which merges through the forge adapter rather than the guard's own arms. The [guard/core design](../../../../.agents/artifacts/specs/2026-09-20-issue-116-permission-guard-core-design.md) settles how the guard and the core relate.

## Decision

The required-check floor holds for both merge arms, and core grants cannot override the final guard, host or provider verdict. Two exceptions are recorded as such.

The plan-gated floor of issue 552 replaces the protection demand for one forge answer only, a 403 whose message says the plan cannot enable the feature, and only for a repository whose confirmed derived row declares required checks. The merge is then judged by the checks declared in the row against the pull request's own check rollup. The owner accepted this as a native-guard exception of the kind issue 116 D6 lists as a gap; it is not core-admission evidence.

The release core's forge `pr_merge` is admitted under issue 554: the adapter refuses it unless protection holds strict required checks with admin enforcement, and `.agents/artifacts/evidence/release-554-native-certification.json` is its native certification. Any other core admission still waits for the named enforcement and conformance work.

The mergeability check of issue 476 sits before both arms' first gate: a pull request behind its base, or a `--match-head-commit` that is not the pull request's head, is refused, and GitHub stays the authority that compares the head atomically with the merge.

## Consequences

- The floor is weaker than forge protection, because nothing stops a merge made outside the guard. A forge that later protects the branch answers the read with exit 0, and the protection demand governs again with no contract change.
- The permanent-head deletion check (`--delete-branch` when the head is the default or integration branch) is closed in the guard, and the remaining protection exceptions stay recorded as gaps in the design.
- A repository that cannot protect its branch and declares no required checks cannot be merged through the guard.
