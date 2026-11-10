---
area: Guard
budget: 200 lines
---

# Guard

Guard is the fail-closed pre-tool hook that judges the lifecycle verbs an agent may run. It decides from the live repository and a compiled policy rather than from how a command is spelled.

## Language

**Base policy**:
The store file of every member the guard trusts absolutely: the authorized owners, the literal integration bases and the store paths of the programs it runs. Every host gets it, and the compiled policy never carries a member of it.

**Compiled policy**:
The derived-only user file the policy compiler writes from the fleet registry: one derived row per registered project and a record of the derivation, and none of the base policy's members. A project the compiler cannot derive has no row, but a stored row the guard's loader refuses empties the whole file.
_Avoid_: policy file

**Derived row**:
A project's entry in the compiled policy, earned only when every derivation step holds. The guard uses it only after the row check confirms it.
_Avoid_: generated row

**Detaching word**:
A word such as `nohup`, `setsid` or `disown` that the guard refuses in every repository, pointing at the Bash tool's background option instead.

**Lifecycle verb**:
One of the five commands the guard adjudicates instead of the allow list: a push, a pull request creation, a branch deletion, a merge and a release creation.
_Avoid_: git command

**Plan-gated floor**:
The rule that relaxes the protection demand for one answer only: a repository whose plan cannot report branch protection at all. The guard accepts that answer and nothing looser.

**Raise label**:
The label that raises a repository's instruction budget for one change. Only the owner applies it, and the guard refuses an agent adding it.

**Row check**:
The live confirmation that a derived row still matches the repository it names, made once per invocation by reading the remote and the contract on its registered branch.
