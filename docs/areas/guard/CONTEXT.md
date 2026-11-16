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
A project's entry in the compiled policy, earned only when every derivation step holds. The guard relies on its branches and checks only after the row check confirms it; its production rules only refuse and are read unconfirmed (ADR-guard-011).
_Avoid_: generated row

**Approved release path**:
The one declared way to change production: the release profile a project contract's production section names, run through the release command. A production refusal names it. See ADR-guard-009 and ADR-guard-011.

**Detaching word**:
A word such as `nohup`, `setsid` or `disown` that the guard refuses in every repository, pointing at the Bash tool's background option instead.

**Lifecycle verb**:
One of the five commands the guard adjudicates instead of the allow list: a push, a pull request creation, a branch deletion, a merge and a release creation.
_Avoid_: git command

**Plan-gated floor**:
The rule that relaxes the protection demand for one answer only: a repository whose plan cannot report branch protection at all. The guard accepts that answer and nothing looser.

**Production rule**:
A rule of the project contract that names a command id, key file glob or MCP tool that changes production. The guard refuses the command in the project's checkout, a write to the key file in that checkout and a call to the MCP tool anywhere, in every permission mode, read from the project's derived row. It names the id, never the binary inside a script, alias or `just` recipe. A project that declares none declares no production. See ADR-guard-009, ADR-guard-011 and ADR-guard-012.

**Raise label**:
The label that raises a repository's instruction budget for one change. Only the owner applies it, and the guard refuses an agent adding it.

**Read-only route**:
A declared way to reach production that only reads, such as a project's documented read-only check. The guard admits it in every permission mode. See ADR-guard-009 and ADR-guard-011.

**Row check**:
The live confirmation that a derived row still matches the repository it names, made once per invocation by reading the remote and the contract on its registered branch.
