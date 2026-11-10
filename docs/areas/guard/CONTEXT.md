---
area: Guard
budget: 200 lines
---

# Guard

Guard is the fail-closed pre-tool hook that judges the lifecycle verbs an agent may run. It decides from the live repository and a compiled policy rather than from how a command is spelled.

## Language

**Base policy**:
The hand-authored part of the guard's policy that every host gets: the allowed verbs and repositories before any derived row is added.

**Compiled policy**:
The base policy plus one derived row per registered project, written by the policy compiler from the fleet registry. A missing or refused row leaves that project without one.
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
