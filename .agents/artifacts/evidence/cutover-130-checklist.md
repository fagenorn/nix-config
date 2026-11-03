# Stage-4 cutover checklist — issue 130

Purpose: pre-activation predicates for the issue 130 strict cutover with fresh read-only evidence, red-row dispositions and the owner's gate; preparation only, per spec D1.
Run: rel_01a1a1d8-7220-72a2-841e-df2806f78396
Revisions: delivery worktree cfd3ad5b7e64f999b372bae34b14e4b8a80c03d8; origin/main 36284d437b88f5cb80d0d793585c739f86706bd6, as last fetched (D15)
Hosts: eleven-m5, mbp, anis-desktop

## Roster

### Hosts

| Host | Reachable | Generation | Store path | platform_version | manifest_path | K_H | Other clones | Registry sha256 before |
|------|-----------|------------|------------|------------------|---------------|-----|--------------|------------------------|
| eleven-m5 | yes | system-28 | /nix/store/b2zxn3q6g0w1bsbmc3xag91yy927h8nf-darwin-system-25.11.ebec37a | 1.0.0 | /nix/store/9bgy678k3kj7y28wy8s00n7mmd7kdvks-hm_platformmanifest.json | /Users/anis/Projects/nix-config | /Users/anis/tmp/nix-config | 0e3643016a781e74c21eada5322e060b742ff87cc9b19214465b0caa61f404f5 |
| mbp | yes | system-309 | /nix/store/3kawdvvw0zcndvg3261xsa5drw4qjgaq-darwin-system-25.11.ebec37a | 1.0.0 | /nix/store/9bgy678k3kj7y28wy8s00n7mmd7kdvks-hm_platformmanifest.json | /Users/anis/tmp/nix-config | — | 819bbd8487305b83cf5fcd987f559847a03f8d51d4df155f70b5e2fb30905e75 |
| anis-desktop | no (C1.c exit 255) | — | — | — | — | — | — | — |

### Projects

| Host | project_id | Root | branch_override | HEAD before |
|------|------------|------|-----------------|-------------|
| mbp | arcwave | /Users/anis/Projects/arcwave | dev (default_contract_unresolved) | 1f4ab4731c8bc2f7a7919cd4bec78462aa7480f3 |
| mbp | fagenorn/argus | /Users/anis/Projects/argus | — | 21338cae51ea396f6c3f9664642e06463c25d97c |
| mbp | fagenorn/nix-config | /Users/anis/tmp/nix-config | — | f6a48dcf66fbb2171f66920c32afd4f9e5056a93 |
| mbp | jarbird | /Users/anis/Projects/jarbird | — | 987c9415c512bf6a78f2d18377f66540fe306c5b |
| mbp | nodocom | /Users/anis/Projects/nodocom | dev (default_contract_unresolved) | ef9eb5e8d25e7fb703c346d27a2c69522582b981 |
| eleven-m5 | jarbird | /Users/anis/Projects/jarbird | — | 81c45be0afa78f946e00ab445a28ceab84814cdd |

Every registered project on every reachable host is in (D2). Arcwave is in, by the repository owner's 2026-11-03 comment on issue 130. The observed `branch_override` of Arcwave and of `nodocom` (Nodo) is `dev` (`default_contract_unresolved`): that is the designed #363 registration path, recorded as a fact and not a red item. `anis-desktop` was unreachable at C1.c (ssh: connect to host anis-desktop.mink-fort.ts.net port 48521: Operation timed out); it is never probed again in this run, every one of its rows is `human-pending`, and it is never dropped from the roster.

## Evidence

### C1 — Roster from registry truth

> Derive the cutover roster from the fleet registry at execution time rather than freezing “all three,” and explicitly decide whether Arcwave belongs in this cutover. (issue 130 refresh)

```text
C1.a nix eval --json .#darwinConfigurations --apply builtins.attrNames
C1.b nix eval --json .#nixosConfigurations --apply builtins.attrNames
C1.c hostname
C1.d cat .agents/state/fleet/registry.json
```

| Host | Subject | Revision | Command | UTC | Exit | Observed | Verdict |
|------|---------|----------|---------|-----|------|----------|---------|
| mbp | flake.nix | cfd3ad5b7e64 | C1.a; C1.b | 2026-11-03T15:55:49Z | 0; 0 | darwin ["eleven-m5","mbp"]; nixos ["anis-desktop"] | green |
| eleven-m5 | host | system-28 | C1.c; C1.d | 2026-11-03T15:55:33Z | 0; 0 | hostname eleven-m5; 1 project: jarbird | green |
| mbp | host | system-309 | C1.c; C1.d | 2026-11-03T15:56:02Z | 0; 0 | hostname mbp; 5 projects: arcwave, fagenorn/argus, fagenorn/nix-config, jarbird, nodocom | green |
| anis-desktop | host | — | C1.c | 2026-11-03T15:55:33Z | 255 | unreachable in Task 1 (C1.c exit 255) | human-pending |

Item verdict: **human-pending**

### C2 — Registered, compatible and adoption current

> every fleet project … is registered and compatible (issue 130); per-project adoption evidence current (#71)

```text
C2.a resolve-project platform-status --fleet
C2.b conformance run --purpose fleet --repo-root R
C2.c adopt-project verify --repo-root R
```

| Host | Subject | Revision | Command | UTC | Exit | Observed | Verdict |
|------|---------|----------|---------|-----|------|----------|---------|
| mbp | host | system-309 | C2.a | 2026-11-03T16:07:05Z | 0 | platform 1.0.0; 5/5 fleet rows compatible; interval >=1.0.0 <2.0.0; every root has a row | green |
| eleven-m5 | host | system-28 | C2.a | 2026-11-03T16:07:06Z | 0 | platform 1.0.0; 1/1 fleet rows compatible; interval >=1.0.0 <2.0.0; every root has a row | green |
| anis-desktop | host | — | C1.c | 2026-11-03T15:55:33Z | 255 | unreachable in Task 1 (C1.c exit 255) | human-pending |
| mbp | /Users/anis/Projects/arcwave | 1f4ab4731c8b dev 0 dirty | C2.b; C2.c | 2026-11-03T16:07:22Z | 0; 0 | fleet passed; verify adopted, blockers 0 | green |
| mbp | /Users/anis/Projects/argus | 21338cae51ea main 1 dirty | C2.b; C2.c | 2026-11-03T16:07:45Z | 0; 0 | fleet passed; verify adopted, blockers 0 | green |
| mbp | /Users/anis/tmp/nix-config | f6a48dcf66fb main 0 dirty | C2.b; C2.c | 2026-11-03T16:07:49Z | 0; 0 | fleet passed; verify not_conformant: adoption-evidence-record, adoption-commit-derived, path-migration-map | red |
| mbp | /Users/anis/Projects/jarbird | dd3964e3b2a7 dev 8 dirty | C2.b; C2.c | 2026-11-03T16:07:54Z | 0; 0 | fleet passed; verify adopted, blockers 0 | green |
| mbp | /Users/anis/Projects/nodocom | ef9eb5e8d25e dev 0 dirty | C2.b; C2.c | 2026-11-03T16:08:00Z | 0; 0 | fleet failed repository.ignore.runtime_sentinel (overbroad_ignore), repair lifecycle.ignore.repair; verify adopted | red |
| eleven-m5 | /Users/anis/Projects/jarbird | 81c45be0afa7 main 0 dirty | C2.b; C2.c | 2026-11-03T16:08:05Z | 0; 0 | fleet passed; verify adopted, blockers 0 | green |

Registration is the C2.a fleet row: `verify` reports `registered` false unless it registered, and no `--register` ran. Planning's nix-config finding (D16, `adoption-evidence-record`) now reads three failed ids; Nodo's fleet failure is as planned.

Item verdict: **red**

### C3 — Approved bundle binds the candidate

> a fresh `approved` evidence bundle from the token-gate instrument covers the strict-cutover candidate as a whole (issue 130; #71)

```text
C3.a git ls-tree --name-only origin/main -- .agents/artifacts/evidence/
C3.b git show origin/main:<path>
```

| Host | Subject | Revision | Command | UTC | Exit | Observed | Verdict |
|------|---------|----------|---------|-----|------|----------|---------|
| mbp | .agents/artifacts/evidence/ | eb5bdd256bcc | C3.a; C3.b | 2026-11-03T16:13:31Z | 0; 0; 0 | approved and binding the candidate: 0 of 2 bundles; C4 names no candidate | red |

Informational bundles (no verdict, outside the worst-row rule):
- .agents/artifacts/evidence/promotion-127-bundle.json: state unmeasured; candidate 66ccba5844ea
- .agents/artifacts/evidence/release-128-bundle.json: state unmeasured; candidate 33149faddfc0

Item verdict: **red**

### C4 — Candidate and bridge fleet preflight

> candidate and retained-bridge fleet preflight green for every registered project (#71)

```text
C4.a git show origin/main:home/common/agent-skills/platform-manifest.json
```

| Host | Subject | Revision | Command | UTC | Exit | Observed | Verdict |
|------|---------|----------|---------|-----|------|----------|---------|
| mbp | home/common/agent-skills/platform-manifest.json | eb5bdd256bcc | C4.a | 2026-11-03T16:13:31Z | 0 | platform_version 1.0.0; 0 deprecations, 0 removals; every C2.a interval [1.0.0,2.0.0) | red |

No candidate exists: the strict major #66 requires is `2.0.0` or above, and the C2.a intervals on `mbp` and `eleven-m5` both exclude it (D1, D11).

Item verdict: **red**

### C8 — Codex ship handoff installed

> the Codex ship handoff is in place so that removing the fallback ladders does not strand a Codex session at the shipping step (issue 130)

```text
C8.a ls -lL .agents/skills/ship-issue/HUMAN-GATE.md
C8.b grep -n HUMAN-GATE.md .agents/skills/ship-issue/SKILL.md
C8.c git log -1 --format=%H -- home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md
```

| Host | Subject | Revision | Command | UTC | Exit | Observed | Verdict |
|------|---------|----------|---------|-----|------|----------|---------|
| mbp | host | system-309 | C8.a; C8.b | 2026-11-03T16:08:27Z | 0; 0 | regular file ~/.agents/skills/ship-issue/HUMAN-GATE.md; 4 SKILL.md lines (25, 47, 122, 227) | green |
| eleven-m5 | host | system-28 | C8.a; C8.b | 2026-11-03T16:08:27Z | 0; 0 | regular file 4782 B; 4 SKILL.md lines (25, 47, 122, 226) | green |
| anis-desktop | host | — | C1.c | 2026-11-03T15:55:33Z | 255 | unreachable in Task 1 (C1.c exit 255) | human-pending |
| mbp | home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md | 075934a7152d | C8.c | 2026-11-03T16:08:28Z | 0 | 3fe58ec0f191 (latest; added 5825027f0202 by PR 141, issue 119) | green |

Item verdict: **human-pending**

### C9 — Host routes answer as declared

> Claude and Codex paths complete against declared host capabilities, including bounded capacity admission (issue 130 refresh)

```text
C9.a workflow-state host-route --route claude-code
C9.b workflow-state host-route --route codex
```

| Host | Subject | Revision | Command | UTC | Exit | Observed | Verdict |
|------|---------|----------|---------|-----|------|----------|---------|
| mbp | host | system-309 | C9.a; C9.b | 2026-11-03T16:08:29Z | 0; 0 | claude-code supported 7; codex unsupported declared_unsupported, alternative /from-issue <issue> --auto; admission passed on 5/5 roots | green |
| eleven-m5 | host | system-28 | C9.a; C9.b | 2026-11-03T16:08:29Z | 0; 0 | claude-code supported 7; codex unsupported declared_unsupported, alternative /from-issue <issue> --auto; admission passed on 1/1 roots | green |
| anis-desktop | host | — | C1.c | 2026-11-03T15:55:33Z | 255 | unreachable in Task 1 (C1.c exit 255) | human-pending |

Codex `unsupported` is the declared answer, not a red (D10). Admission is each C10 row's `host.admission.declaration`.

Item verdict: **human-pending**

### C10 — Doctor clean on every adopted host

> `doctor` is clean on every adopted host (issue 130)

```text
C10.a conformance run --purpose doctor --repo-root R
```

| Host | Subject | Revision | Command | UTC | Exit | Observed | Verdict |
|------|---------|----------|---------|-----|------|----------|---------|
| mbp | /Users/anis/Projects/arcwave | 1f4ab4731c8b dev 0 dirty | C10.a | 2026-11-03T16:07:22Z | 0 | doctor passed; no warning checks; 0 suppressed or not_run; admission passed | green |
| mbp | /Users/anis/Projects/argus | 21338cae51ea main 1 dirty | C10.a | 2026-11-03T16:07:45Z | 0 | doctor passed; no warning checks; 0 suppressed or not_run; admission passed | green |
| mbp | /Users/anis/tmp/nix-config | f6a48dcf66fb main 0 dirty | C10.a | 2026-11-03T16:07:49Z | 0 | doctor passed; no warning checks; 0 suppressed or not_run; admission passed | green |
| mbp | /Users/anis/Projects/jarbird | dd3964e3b2a7 dev 8 dirty | C10.a | 2026-11-03T16:07:54Z | 0 | doctor passed; no warning checks; 0 suppressed or not_run; admission passed | green |
| mbp | /Users/anis/Projects/nodocom | ef9eb5e8d25e dev 0 dirty | C10.a | 2026-11-03T16:08:00Z | 0 | doctor failed repository.ignore.runtime_sentinel; repair lifecycle.ignore.repair; 0 suppressed or not_run; admission passed | red |
| eleven-m5 | /Users/anis/Projects/jarbird | 81c45be0afa7 main 0 dirty | C10.a | 2026-11-03T16:08:05Z | 0 | doctor passed; no warning checks; 0 suppressed or not_run; admission passed | green |
| anis-desktop | host | — | C1.c | 2026-11-03T15:55:33Z | 255 | unreachable in Task 1 (C1.c exit 255) | human-pending |

Item verdict: **red**

### C11 — Deprecations shipped, zero users

> Deprecation notices shipped in the bridge minor; removal happens only here, in the major, and only after zero fleet users of the deprecated paths. (issue 130 refresh)

```text
C11.a resolve-project platform-status
C11.b git --no-optional-locks -C R ls-files -- .claude/skills.config.json
C11.c resolve-project resolve --repo-root R
C11.d git --no-optional-locks -C R grep -n -F 'release deploy inspect' -- . ':!.agents/artifacts'
```

| Host | Subject | Revision | Command | UTC | Exit | Observed | Verdict |
|------|---------|----------|---------|-----|------|----------|---------|
| mbp | host | system-309 | C11.a | 2026-11-03T16:13:36Z | 0 | platform.deprecations empty (0 entries) | red |
| eleven-m5 | host | system-28 | C11.a | 2026-11-03T16:13:37Z | 0 | platform.deprecations empty (0 entries) | red |
| anis-desktop | host | — | C1.c | 2026-11-03T15:55:33Z | 255 | unreachable in Task 1 (C1.c exit 255) | human-pending |
| mbp | /Users/anis/Projects/arcwave | 1f4ab4731c8b dev 0 dirty | C11.b; C11.c; C11.d | 2026-11-03T16:13:49Z | 0; 0; 1 | legacy file tracked; deploy.adapter none; 0 hits | red |
| mbp | /Users/anis/Projects/argus | 21338cae51ea main 1 dirty | C11.b; C11.c; C11.d | 2026-11-03T16:13:50Z | 0; 0; 1 | legacy file not tracked; deploy.adapter none; 0 hits | green |
| mbp | /Users/anis/tmp/nix-config | f6a48dcf66fb main 0 dirty | C11.b; C11.c; C11.d | 2026-11-03T16:13:50Z | 0; 0; 1 | legacy file not tracked; deploy.adapter none; 0 hits (skills) | green |
| mbp | /Users/anis/Projects/jarbird | dd3964e3b2a7 dev 8 dirty | C11.b; C11.c; C11.d | 2026-11-03T16:13:51Z | 0; 0; 1 | legacy file not tracked; deploy.adapter github-actions-health; 0 hits | red |
| mbp | /Users/anis/Projects/nodocom | ef9eb5e8d25e dev 0 dirty | C11.b; C11.c; C11.d | 2026-11-03T16:13:51Z | 0; 0; 1 | legacy file tracked; deploy.adapter railway; 0 hits | red |
| eleven-m5 | /Users/anis/Projects/jarbird | 81c45be0afa7 main 0 dirty | C11.b; C11.c; C11.d | 2026-11-03T16:13:53Z | 0; 0; 1 | legacy file not tracked; deploy.adapter none; 0 hits | green |

C11.d exits 1 (no hit) on every root; for `fagenorn/nix-config` its pathspec is `home/common/agent-skills/skills`. Point-in-time records under `.agents/artifacts` are not users. The `jarbird` root resolves `github-actions-health` on `mbp` (branch dev) and `none` on `eleven-m5` (branch main).

Item verdict: **red**

### C12 — Bridge generation identified per host

> The bridge generation is retained until the strict predicates are verified green on the fleet, and rollback reactivates it. (issue 130)

```text
C12.a hostname
C12.b readlink /nix/var/nix/profiles/system
C12.c readlink /nix/var/nix/profiles/system-<N>-link
C12.d readlink /run/current-system
```

| Host | Subject | Revision | Command | UTC | Exit | Observed | Verdict |
|------|---------|----------|---------|-----|------|----------|---------|
| eleven-m5 | host | system-28 | C12.a; C12.b; C12.c; C12.d | 2026-11-03T15:56:43Z | 0; 0; 0; 0 | N=28; store paths equal; b2zxn3q6g0w1bsbmc3xag91yy927h8nf-darwin-system-25.11.ebec37a | green |
| mbp | host | system-309 | C12.a; C12.b; C12.c; C12.d | 2026-11-03T15:56:43Z | 0; 0; 0; 0 | N=309; store paths equal; 3kawdvvw0zcndvg3261xsa5drw4qjgaq-darwin-system-25.11.ebec37a | green |
| anis-desktop | host | — | C12.a | 2026-11-03T15:55:33Z | 255 | unreachable in Task 1 (C1.c exit 255) | human-pending |

The two reachable hosts run different bridge builds (distinct store paths); per D2 and #66 that is recorded and is not red.

Item verdict: **human-pending**
