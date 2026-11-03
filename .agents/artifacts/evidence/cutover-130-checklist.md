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
