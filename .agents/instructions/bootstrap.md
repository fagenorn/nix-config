# Project invariants — nix-config

This file is the canonical instruction source for every agent working in this
repository. It is projected into the native entry surface each agent discovers
on its own; those projections are generated and must never be hand-edited.

- Project policy lives in `.agents/project.json`. Never read that file directly
  and never persist a snapshot of it. Resolve once at entry with
  `resolve-project resolve` and trust the returned `ResolvedProject`.
- No project policy is defaulted. When `resolve-project` refuses, fix the
  contract; never guess a value it declined to give you.
- Every `paths` member, every `paths.artifacts` member and every command
  `cwd` in the snapshot is absolute and rooted at `project.root`. No other
  binding is rewritten: a path-shaped value elsewhere is returned exactly as
  authored, so resolve it yourself before using it.
- Every executable invocation is a `commands` entry addressed by its id; the
  contract carries no environment variable values and no shell text.
- `AGENTS.md` and the `@.agents/instructions/bootstrap.md` import line in
  `CLAUDE.md` are generated from this file by
  `resolve-project write-projections`. Edit this file, then regenerate.
