---
area: Project contract
budget: 200 lines
---

# Project contract

Project contract is how a repository tells the agent skills everything project-specific. A project authors one contract, every command reads it through one resolved snapshot, and adoption moves a repository onto a platform version.

## Language

**Adoption**:
Moving a repository onto a platform version by planning and then applying a set of file moves, rewritten links and generated projections. Adoption plans first and edits nothing without an answer.
_Avoid_: onboarding

**Deprecation**:
A platform-manifest entry naming a project file or key that a newer platform version no longer accepts, with its successor and the migration that converts it.

**Fleet registry**:
The per-host list of the projects the agent tooling manages. Verification passes and the guard's compiled policy both read it.
_Avoid_: project list

**Migration**:
One pure, named executor the platform manifest lists, which rewrites a checkout in place from one contract shape to the next.
_Avoid_: upgrade script

**Platform manifest**:
The versioned JSON file the platform ships, listing its deprecations and migrations. A project's contract schema version is checked against it.

**Project contract**:
The authored `.agents/project.json` of a repository: its tracker, branches, commands, paths and release profiles. Policy lives here and is never defaulted.
_Avoid_: project config, settings

**Projection**:
A file generated from the contract or its instruction source, such as an agent's entry file. A projection is regenerated, never hand-edited.
_Avoid_: generated file

**Removal**:
The step of a platform version that deletes a deprecated surface once its migration has run. A removal is announced as a deprecation first.

**ResolvedProject**:
The one retained snapshot that `resolve-project resolve` prints: the contract with every path made absolute and every command addressed by id. Every command and skill reads it and never the contract file.
_Avoid_: snapshot, config
