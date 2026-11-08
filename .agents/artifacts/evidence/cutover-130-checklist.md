# Stage-4 cutover checklist — issue 130

Purpose: pre-activation predicates for the issue 130 strict cutover with fresh read-only evidence, red-row dispositions and the owner's gate; preparation only, per spec D1.
Run: rel_01a1a1d8-7220-72a2-841e-df2806f78396
Revisions: delivery worktree cfd3ad5b7e64f999b372bae34b14e4b8a80c03d8; origin/main 36284d437b88f5cb80d0d793585c739f86706bd6, as last fetched (D15)
Hosts: eleven-m5, mbp, anis-desktop
Evidence window: 2026-11-03T15:55:33Z to 2026-11-03T16:20:04Z
Activation readiness: activation not permitted — 6 red, 6 human-pending, 0 green of 12 pre-activation items.

## Summary

| ID | Predicate | Source | Phase | Verdict | Disposition |
|----|-----------|--------|-------|---------|-------------|
| C1 | The roster is derived from current registry truth, with the Arcwave decision recorded | refresh | pre | human-pending | owner: host online |
| C2 | Every roster project is registered and compatible, and its adoption evidence is still current | issue; #71 | pre | red | #583, #586; anis-desktop: owner: host online |
| C3 | A fresh `approved` #70 bundle covers the strict-cutover candidate as a whole | issue; #71; #128 AC5 | pre | red | owner: paired live trials (#128 D11), tracked in the C3 issue that #579's ship files |
| C4 | Candidate and retained-bridge fleet preflight are green for every registered project | #71 | pre | red | C4.b: the fleet-migration follow-up |
| C5 | No legacy release is in flight | #90 | pre | human-pending | owner: host online |
| C6 | No legacy attempt is left without a resumable strict-path mapping | issue; refresh | pre | human-pending | JarBird on mbp: owner: gate step 1; anis-desktop: owner: host online |
| C7 | No retained legacy worktree is left without a resumable mapping | refresh | pre | red | #585; anis-desktop: owner: host online |
| C8 | The Codex ship handoff is in place | issue; #119 | pre | human-pending | owner: host online |
| C9 | Claude and Codex paths answer as their declared host capabilities say, including bounded admission | refresh | pre | human-pending | owner: host online |
| C10 | `doctor` is clean on every adopted host | issue | pre | red | #583; anis-desktop: owner: host online |
| C11 | Deprecation notices shipped in a bridge minor, and the fleet has zero users of the deprecated paths | issue; #66 | pre | red | #555, #580, #581, #582; anis-desktop: owner: host online |
| C12 | The bridge generation is identified per host and can be retained | issue; #66 | pre | human-pending | owner: host online |
| P1 | No static fallback ladder remains in the resolver, conformance or workflow-entry paths of any adopted project, and a missing contract fails closed with a closed error code | AC2; #69 | post | human-pending | post-activation |
| P2 | The bridge generation is retained, and rollback to it is exercised once before retirement | AC3; refresh | post | human-pending | post-activation |
| P3 | A Claude-driven and a Codex-driven ship complete on the strict path, against declared host capabilities with bounded admission | AC4; refresh | post | human-pending | post-activation |
| P4 | The #71 retirement predicates: the active generation's identity matches its manifest; active and bridge fleet conformance are green; `workflow_entry` passes through both adapters; post-activation smoke is green; doctor reports no residue; traces show zero removed-fallback executions | #71 | post | human-pending | post-activation |
| P5 | Implementation delivered, PR merged, tracker closed and cleanup postconditions reconciled before retirement | refresh | post | human-pending | post-activation |
| P6 | Retirement is recorded with the evidence that satisfied each strict predicate | AC5 | post | human-pending | post-activation |

Origin note: the header's origin/main `36284d437b88` is the value last fetched at Task 1. A fetch outside this run (2026-11-03T16:00:59Z, shared nix-config clone) fast-forwarded origin/main to `eb5bdd256bcc` before Task 3, so the C3 and C4 rows cite it. Neither `eb5bdd256bcc` nor the current origin/main differs from `36284d437b88` in `.agents/artifacts/evidence/` or in the platform manifest (version 1.0.0, no deprecations or removals), so no verdict depends on which. At Task 6 `git rev-parse origin/main` returns `8776ef5458cee419517e333825211ce66b5d4afc`: it moved again, by the clone's `pull -q --ff-only origin main` at 16:26:43Z (PR #576). This run fetched nothing.

## Roster

### Hosts

| Host | Reachable | Generation | Store path | platform_version | manifest_path | K_H | Other clones | Registry sha256 before | Registry sha256 after |
|------|-----------|------------|------------|------------------|---------------|-----|--------------|------------------------|------------------------|
| eleven-m5 | yes | system-28 | /nix/store/b2zxn3q6g0w1bsbmc3xag91yy927h8nf-darwin-system-25.11.ebec37a | 1.0.0 | /nix/store/9bgy678k3kj7y28wy8s00n7mmd7kdvks-hm_platformmanifest.json | /Users/anis/Projects/nix-config | /Users/anis/tmp/nix-config | 0e3643016a781e74c21eada5322e060b742ff87cc9b19214465b0caa61f404f5 | 0e3643016a781e74c21eada5322e060b742ff87cc9b19214465b0caa61f404f5 |
| mbp | yes | system-309 | /nix/store/3kawdvvw0zcndvg3261xsa5drw4qjgaq-darwin-system-25.11.ebec37a | 1.0.0 | /nix/store/9bgy678k3kj7y28wy8s00n7mmd7kdvks-hm_platformmanifest.json | /Users/anis/tmp/nix-config | — | 819bbd8487305b83cf5fcd987f559847a03f8d51d4df155f70b5e2fb30905e75 | 819bbd8487305b83cf5fcd987f559847a03f8d51d4df155f70b5e2fb30905e75 |
| anis-desktop | no (C1.c exit 255) | — | — | — | — | — | — | — | — |

### Projects

| Host | project_id | Root | branch_override | HEAD before | HEAD after |
|------|------------|------|-----------------|-------------|------------|
| mbp | arcwave | /Users/anis/Projects/arcwave | dev (default_contract_unresolved) | 1f4ab4731c8bc2f7a7919cd4bec78462aa7480f3 | 1f4ab4731c8bc2f7a7919cd4bec78462aa7480f3 |
| mbp | fagenorn/argus | /Users/anis/Projects/argus | — | 21338cae51ea396f6c3f9664642e06463c25d97c | 21338cae51ea396f6c3f9664642e06463c25d97c |
| mbp | fagenorn/nix-config | /Users/anis/tmp/nix-config | — | f6a48dcf66fbb2171f66920c32afd4f9e5056a93 | 8776ef5458cee419517e333825211ce66b5d4afc |
| mbp | jarbird | /Users/anis/Projects/jarbird | — | 987c9415c512bf6a78f2d18377f66540fe306c5b | dd3964e3b2a7c590681add1495c75ae23786551a |
| mbp | nodocom | /Users/anis/Projects/nodocom | dev (default_contract_unresolved) | ef9eb5e8d25e7fb703c346d27a2c69522582b981 | ef9eb5e8d25e7fb703c346d27a2c69522582b981 |
| eleven-m5 | jarbird | /Users/anis/Projects/jarbird | — | 81c45be0afa78f946e00ab445a28ceab84814cdd | 81c45be0afa78f946e00ab445a28ceab84814cdd |

Every registered project on every reachable host is in (D2). Arcwave is in, by the repository owner's 2026-11-03 comment on issue 130. The observed `branch_override` of Arcwave and of `nodocom` (Nodo) is `dev` (`default_contract_unresolved`): that is the designed #363 registration path, recorded as a fact and not a red item. `anis-desktop` was unreachable at C1.c (ssh: connect to host anis-desktop.mink-fort.ts.net port 48521: Operation timed out); it is never probed again in this run, every one of its rows is `human-pending`, and it is never dropped from the roster.

Snapshot: the after-snapshot was taken on `mbp` at 2026-11-03T16:33:22Z (registries and the five local roots) and 16:33:24Z (`eleven-m5`'s root), after the evidence window. Both registries are byte-identical to the before-snapshot (same sha256). Four of the six roots equal their before values: Arcwave, Argus, Nodo and `eleven-m5`'s JarBird, with the dirty counts the rows record. Two moved, both by other runs and neither by this attempt:
- `mbp` JarBird `987c9415c512` to `dd3964e3b2a7`: a fast-forward of 95 commits (`merge origin/dev` in its reflog, 2026-11-03T15:57:13Z), after Task 1 read it and before Task 2's first JarBird row; it carries elevenyellow/jarbird PRs #349, #355, #348, #354, #353, #352 and #351. Every JarBird row on `mbp` cites `dd3964e3b2a7`.
- nix-config clone `/Users/anis/tmp/nix-config` `f6a48dcf66fb` to `8776ef5458ce`: a fast-forward of 69 commits (`pull -q --ff-only origin main`, reflog 2026-11-03T16:26:44Z), after the rows of C2 to C11 were taken at `f6a48dcf66fb`; it carries PRs #568, #570, #571, #577 and #576. Gate step 2 re-reads those rows.

This attempt committed only on the delivery branch and wrote no roster root or registry (§6 item 4).

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

Re-read after #583 (read-only, 2026-11-08T13:33:54Z): mbp /Users/anis/Projects/nodocom at de844daee933 dev 0 dirty, after https://github.com/elevenyellow/nodocom/pull/2603 merged as de844daee9339d3e99fa496908fd7354a0fa3255: C2.a exit 0, row compatible, platform 1.1.0; C2.b exit 0, fleet passed, no warning checks; C2.c exit 0, verify adopted, blockers 0. Root row green under the rule above; the row in the table is the 2026-11-03 reading.

Item verdict: **red**

### C3 — Approved bundle binds the candidate

> a fresh `approved` evidence bundle from the token-gate instrument covers the strict-cutover candidate as a whole (issue 130; #71)

```text
C3.a git ls-tree --name-only origin/main -- .agents/artifacts/evidence/
C3.b git show origin/main:<path>
C3.c home/common/verify-pending/checks/cutover-bundle
```

C3.c reads `<candidate>`, the head of `origin/cutover-130-candidate` (6b98674402994180a2a1f1852cf71f18fd1aa0ca at this pass), and every `*-bundle.json` at `origin/main`. It passes each through `agent_gate_bundle.verify_bundle`, which recomputes the id over the body and re-decides the state from the bundle's own evidence. It is green only when some bundle verifies `approved` and binds `<candidate>`. A bundle the verifier refuses is unreadable and never counts, and the document's own `state` field is never read. The item takes its worst row.

| Host | Subject | Revision | Command | UTC | Exit | Observed | Verdict |
|------|---------|----------|---------|-----|------|----------|---------|
| mbp | .agents/artifacts/evidence/ | eb5bdd256bcc | C3.a; C3.b | 2026-11-03T16:13:31Z | 0; 0; 0 | approved and binding the candidate: 0 of 2 bundles; C4 names no candidate | red |
| mbp | origin/main .agents/artifacts/evidence/ against 6b9867440299 | f70a164245b4 | C3.c | 2026-11-08T14:17:22Z | 75 | approved and binding the candidate: 0 of 2 bundles at origin/main, both unmeasured and bound to other commits; the issue branch's cutover-579-bundle.json is unmeasured and binds the candidate, so only an unmeasured bundle binds it | red |

Informational bundles (no verdict, outside the worst-row rule):
- .agents/artifacts/evidence/promotion-127-bundle.json: state unmeasured; candidate 66ccba5844ea
- .agents/artifacts/evidence/release-128-bundle.json: state unmeasured; candidate 33149faddfc0
- .agents/artifacts/evidence/cutover-579-bundle.json (issue 579, on the issue branch): state unmeasured; candidate 6b9867440299, the output of `just agent-gate-bundle --trials .agents/artifacts/evidence/cutover-579-trials.json`, never hand-authored

Item verdict: **red**

### C4 — Candidate and bridge fleet preflight

> candidate and retained-bridge fleet preflight green for every registered project (#71)

```text
C4.a git show origin/main:home/common/agent-skills/platform-manifest.json
C4.b home/common/verify-pending/checks/cutover-preflight
```

C4.a is `PYTHONPATH=python python3 -m agent_tools.verify_checks cutover-manifest`: `origin/main`'s manifest has major 1 and a deprecation equal to every `removals` entry of `<candidate>`'s manifest. C4.b is `home/common/verify-pending/checks/cutover-preflight`, green only on `verdict: green` on every reachable host, and it includes C4.a. The item takes its worst row.

| Host | Subject | Revision | Command | UTC | Exit | Observed | Verdict |
|------|---------|----------|---------|-----|------|----------|---------|
| mbp | home/common/agent-skills/platform-manifest.json | eb5bdd256bcc | C4.a | 2026-11-03T16:13:31Z | 0 | platform_version 1.0.0; 0 deprecations, 0 removals; every C2.a interval [1.0.0,2.0.0) | red |

No candidate exists: the strict major #66 requires is `2.0.0` or above, and the C2.a intervals on `mbp` and `eleven-m5` both exclude it (D1, D11).

The paragraph above is the evidence-time reading. A candidate now exists (issue 579): `origin/cutover-130-candidate`, 6b98674402994180a2a1f1852cf71f18fd1aa0ca.

| Host | Subject | Revision | Command | UTC | Exit | Observed | Verdict |
|------|---------|----------|---------|-----|------|----------|---------|
| mbp | home/common/agent-skills/platform-manifest.json | f70a164245b4 | C4.a (`--main-ref` the issue branch HEAD) | 2026-11-08T14:17:22Z | 0 | main_version 1.2.0; candidate_version 2.0.0; 5 removals, 0 undeclared; verdict green; read at the issue branch; origin/main reads the same after merge (#579 AC2); C4.b waits on the fleet-migration follow-up | green |

Item verdict: **red**

### C5 — No legacy release in flight

> no legacy release is in flight (#90)

```text
C5.a ls -la R/.superpowers/workflows/ship-release/state.json
C5.b release transaction status --repo-root R
```

| Host | Subject | Revision | Command | UTC | Exit | Observed | Verdict |
|------|---------|----------|---------|-----|------|----------|---------|
| anis-desktop | host | — | C1.c | 2026-11-03T15:55:33Z | 255 | unreachable in Task 1 (C1.c exit 255) | human-pending |
| mbp | /Users/anis/Projects/arcwave | 1f4ab4731c8b dev 0 dirty | C5.a | 2026-11-03T16:19:45Z | 2 | absent | green |
| mbp | /Users/anis/Projects/argus | 21338cae51ea main 1 dirty | C5.a | 2026-11-03T16:19:51Z | 2 | absent | green |
| mbp | /Users/anis/tmp/nix-config | f6a48dcf66fb main 0 dirty | C5.a | 2026-11-03T16:19:36Z | 2 | absent | green |
| mbp | /Users/anis/Projects/jarbird | dd3964e3b2a7 dev 8 dirty | C5.a | 2026-11-03T16:19:52Z | 2 | absent | green |
| mbp | /Users/anis/Projects/nodocom | ef9eb5e8d25e dev 0 dirty | C5.a | 2026-11-03T16:19:55Z | 2 | absent | green |
| eleven-m5 | /Users/anis/Projects/jarbird | 81c45be0afa7 main 0 dirty | C5.a | 2026-11-03T16:20:03Z | 2 | absent | green |

No root holds a legacy `ship-release/state.json`, so C5.b did not run (and `legacy.class` was never read).

Item verdict: **human-pending**

### C6 — Legacy ledgers have a strict-path mapping

> Do not activate while any legacy attempt or worktree lacks a resumable strict-path mapping (issue 130 refresh)

```text
C6.a workflow-state migrate --repo-root R
```

| Host | Subject | Revision | Command | UTC | Exit | Observed | Verdict |
|------|---------|----------|---------|-----|------|----------|---------|
| anis-desktop | host | — | C1.c | 2026-11-03T15:55:33Z | 255 | unreachable in Task 1 (C1.c exit 255) | human-pending |
| mbp | /Users/anis/Projects/arcwave | 1f4ab4731c8b dev 0 dirty | C6.a | 2026-11-03T16:19:45Z | 0 | current 0, migrate 11, migrated 0, refused 4 (unknown_dialect 4) | red |
| mbp | /Users/anis/Projects/argus | 21338cae51ea main 1 dirty | C6.a | 2026-11-03T16:19:51Z | 0 | current 0, migrate 8, migrated 0, refused 3 (invalid_state 3) | red |
| mbp | /Users/anis/tmp/nix-config | f6a48dcf66fb main 0 dirty | C6.a | 2026-11-03T16:19:36Z | 0 | current 15, migrate 108, migrated 0, refused 6 (invalid_state 6) | red |
| mbp | /Users/anis/Projects/jarbird | dd3964e3b2a7 dev 8 dirty | C6.a | 2026-11-03T16:19:52Z | 0 | current 6, migrate 19, migrated 0, refused 0 | human-pending |
| mbp | /Users/anis/Projects/nodocom | ef9eb5e8d25e dev 0 dirty | C6.a | 2026-11-03T16:19:55Z | 0 | current 5, migrate 146, migrated 0, refused 49 (invalid_state 8, unknown_dialect 41) | red |
| eleven-m5 | /Users/anis/Projects/jarbird | 81c45be0afa7 main 0 dirty | C6.a | 2026-11-03T16:20:03Z | 0 | current 5, migrate 0, migrated 0, refused 0 | green |

`workflow-state migrate` ran without `--apply` on every root. Planning's refusals reappear on nix-config, Argus, Arcwave and Nodo, with Arcwave's four `unknown_dialect`; `human-pending` rows are cleared by the owner's gate step 1.

Re-read after #584 (2026-11-08, mbp): /Users/anis/Projects/arcwave at 2adb089868c5 dev 0 dirty: C6.a exit 0, current 11, migrate 0, migrated 0, refused 0. Root row green under the rule above; the row in the table is the 2026-11-03 reading.
Re-read after #584 (2026-11-08, mbp): /Users/anis/Projects/argus at 21338cae51ea main 1 dirty: C6.a exit 0, current 8, migrate 0, migrated 0, refused 0. Root row green under the rule above; the row in the table is the 2026-11-03 reading.
Re-read after #584 (2026-11-08, mbp): /Users/anis/tmp/nix-config at 8c255848677b main 0 dirty: C6.a exit 0, current 123, migrate 0, migrated 0, refused 0. Root row green under the rule above; the row in the table is the 2026-11-03 reading.
Re-read after #584 (2026-11-08, mbp): /Users/anis/Projects/nodocom at de844daee933 dev 0 dirty: C6.a exit 0, current 154, migrate 0, migrated 0, refused 0. Root row green under the rule above; the row in the table is the 2026-11-03 reading.

#### #584 disposition

Archive home: `R/.superpowers/archive/workflows/<ledger>`, with a sidecar `<ledger>.archived.json` in record schema ledger-archive-record/v1, which carries each ledger's disposition label (archived, abandoned or unresolved) and its re-delivery issues. Nothing was deleted. Every snapshot was taken behind the D9 fence: ledger-snapshot take holds every ledger state.lock, every workflows dot-lock and the transaction store locks, all non-blocking, and refuses busy or changed instead of waiting. All four takes exited 0.

Restore, only before this delivery's ship step starts: (1) run ledger-snapshot restore --repo-root R `--snapshot <tarball>` as a dry run, read moved, restored and newer, and stop if any newer path lies outside the ledgers this run archived or migrated, archive/workflows or attempt-transactions, or if another session ran workflow-state on R since the snapshot; (2) run the same command with --apply, which moves the live workflows, attempt-transactions and archive/workflows aside into a new `pre-584-<UTC>.restore-<UTC>` directory under R/.superpowers/archive and then extracts the snapshot (a store absent at snapshot time stays absent; busy means a writer is active, so stop); (3) check that workflow-state migrate --repo-root R reports the pre-change counts. After ship, restore one ledger at a time by the ledger-archive README procedure (mv the archived directory back, then move its record aside).

Pre-change readings (workflow-state migrate --repo-root R, dry run): Arcwave current 0, migrate 11, refused 4; Argus current 0, migrate 8, refused 3; nix-config current 15, migrate 108, refused 6; Nodo current 8, migrate 146, refused 49. JarBird on mbp is outside this delivery and still awaits gate step 1.

##### Arcwave (mbp /Users/anis/Projects/arcwave)

- Snapshot: /Users/anis/Projects/arcwave/.superpowers/archive/pre-584-20261108T135200Z.tar.gz, sha256:059b1cc752bf45a0cbb4cee75ea2e2c092478c7bd55456a9b9df97ab9921be9a, taken_at 2026-11-08T13:52:00Z, 786 members over 15 ledgers; attempt-transactions was in it (the store exists).
- Labels file: /Users/anis/Projects/arcwave/.superpowers/archive/pre-584-labels-20261108T135200Z.json
- Liveness proof: 2026-11-08T13:52:49Z, no hit (local: no file in the ledger directory has an mtime within 24 hours; forge: no in-progress label and no live claim on any re-delivery issue the forge knows).
- Gate step 1 for this root and the C6.a re-read: 2026-11-08T13:53:03Z, exit 0, current 11, migrate 0, migrated 0, refused 0.

| Ledger | Reason | Issues | Disposition | Liveness | Re-deliver |
|--------|--------|--------|-------------|----------|------------|
| orchestrate-agent-ready-20260914T185053Z | unknown_dialect | 145, 147, 148, 149, 150, 151, 153, 159 | abandoned | local_quiet; forge_quiet | fagenorn/arcwave#147 |
| orchestrate-explicit-20260924T113035Z | unknown_dialect | none | archived | local_quiet; not_applicable | none |
| orchestrate-explicit-20260924T114510Z | unknown_dialect | 146, 152, 154, 155 | archived | local_quiet; not_applicable | none |
| orchestrate-explicit-20260927T070159Z | unknown_dialect | none | archived | local_quiet; not_applicable | none |

##### Argus (mbp /Users/anis/Projects/argus)

- Snapshot: /Users/anis/Projects/argus/.superpowers/archive/pre-584-20261108T135308Z.tar.gz, sha256:ca72c15eb106fd5a0a81b100325acc245d87764754fa9eab738961dccd014e6d, taken_at 2026-11-08T13:53:08Z, 47 members over 11 ledgers; attempt-transactions was not in it (the store is absent).
- Labels file: /Users/anis/Projects/argus/.superpowers/archive/pre-584-labels-20261108T135308Z.json
- Liveness proof: 2026-11-08T13:53:21Z, no hit (local: no file in the ledger directory has an mtime within 24 hours; forge: no in-progress label and no live claim on any re-delivery issue the forge knows).
- Gate step 1 for this root and the C6.a re-read: 2026-11-08T13:53:30Z, exit 0, current 8, migrate 0, migrated 0, refused 0.

| Ledger | Reason | Issues | Disposition | Liveness | Re-deliver |
|--------|--------|--------|-------------|----------|------------|
| issues-48-53 | invalid_state | 48, 49, 50, 51, 52, 53 | archived | local_quiet; not_applicable | none |
| issues-99-105 | invalid_state | 99, 100, 101, 102 | abandoned | local_quiet; forge_quiet | fagenorn/argus#102 |
| orch-78-94-20260821 | invalid_state | 78, 79, 80, 81 | abandoned | local_quiet; forge_quiet | fagenorn/argus#78, fagenorn/argus#79, fagenorn/argus#80, fagenorn/argus#81 |

##### nix-config (mbp /Users/anis/tmp/nix-config)

- Snapshot: /Users/anis/tmp/nix-config/.superpowers/archive/pre-584-20261108T135335Z.tar.gz, sha256:941efed6a9a7cf7c18f6305feea8dd208a567df0d31508df72431b007d1069b8, taken_at 2026-11-08T13:53:35Z, 1870 members over 130 ledgers; attempt-transactions was in it (the store exists).
- Labels file: /Users/anis/tmp/nix-config/.superpowers/archive/pre-584-labels-20261108T135335Z.json
- Liveness proof: 2026-11-08T13:53:44Z, no hit (local: no file in the ledger directory has an mtime within 24 hours; forge: no in-progress label and no live claim on any re-delivery issue the forge knows).
- Gate step 1 for this root and the C6.a re-read: 2026-11-08T13:54:00Z, exit 0, current 123, migrate 0, migrated 0, refused 0.

| Ledger | Reason | Issues | Disposition | Liveness | Re-deliver |
|--------|--------|--------|-------------|----------|------------|
| direct-74-000001 | invalid_state | 74 | archived | local_quiet; not_applicable | none |
| issues-29-30-20260817-r2 | invalid_state | 29, 30 | archived | local_quiet; not_applicable | none |
| issues-29-33-20260817 | invalid_state | 29, 31, 32, 33 | archived | local_quiet; not_applicable | none |
| issues-42-43 | invalid_state | 42, 43 | archived | local_quiet; not_applicable | none |
| orchestrate-21-24 | invalid_state | 21, 24 | archived | local_quiet; not_applicable | none |
| orchestrate-21-24-r2 | invalid_state | 21, 22, 23, 24 | archived | local_quiet; not_applicable | none |

##### Nodo (mbp /Users/anis/Projects/nodocom)

- Snapshot: /Users/anis/Projects/nodocom/.superpowers/archive/pre-584-20261108T135405Z.tar.gz, sha256:15ba17c86e881934d9a31e48dfd964cd201abbae8d0548ca15281aa40e1741b6, taken_at 2026-11-08T13:54:06Z, 3571 members over 203 ledgers; attempt-transactions was in it (the store exists).
- Labels file: /Users/anis/Projects/nodocom/.superpowers/archive/pre-584-labels-20261108T135405Z.json
- Liveness proof: 2026-11-08T13:54:32Z, no hit (local: no file in the ledger directory has an mtime within 24 hours; forge: no in-progress label and no live claim on any re-delivery issue the forge knows).
- Gate step 1 for this root and the C6.a re-read: 2026-11-08T13:54:49Z, exit 0, current 154, migrate 0, migrated 0, refused 0.

| Ledger | Reason | Issues | Disposition | Liveness | Re-deliver |
|--------|--------|--------|-------------|----------|------------|
| direct-1093-000001 | invalid_state | 1093 | archived | local_quiet; not_applicable | none |
| direct-1282-000001 | invalid_state | 1282 | archived | local_quiet; not_applicable | none |
| issues-1247-1248-1249 | invalid_state | 1247 | archived | local_quiet; not_applicable | none |
| issues-1261-1262-1263 | invalid_state | 1261 | archived | local_quiet; not_applicable | none |
| issues-1285-1287 | invalid_state | 1285, 1286, 1287 | archived | local_quiet; not_applicable | none |
| orch-1293-1295-1296 | unknown_dialect | 1293, 1295, 1296 | abandoned | local_quiet; forge_quiet | elevenyellow/nodocom#1296 |
| orch-1293-r2 | unknown_dialect | 1293 | archived | local_quiet; not_applicable | none |
| orch-1295-1296 | unknown_dialect | 1295 | archived | local_quiet; not_applicable | none |
| orch-1314-1318 | unknown_dialect | 1314, 1315, 1316, 1317 | archived | local_quiet; not_applicable | none |
| orch-1320-1321 | unknown_dialect | 1320, 1321 | archived | local_quiet; not_applicable | none |
| orch-1323-1324 | unknown_dialect | 1323 | archived | local_quiet; not_applicable | none |
| orch-1323-1324-r2 | unknown_dialect | none | archived | local_quiet; not_applicable | none |
| orch-1324-1326 | unknown_dialect | 1324, 1326 | archived | local_quiet; not_applicable | none |
| orch-1337-1339-1353-1354 | unknown_dialect | 1337, 1339 | archived | local_quiet; not_applicable | none |
| orch-1382-1388 | unknown_dialect | 1382, 1383, 1384, 1385, 1386, 1387, 1388 | archived | local_quiet; not_applicable | none |
| orch-1404-1416 | unknown_dialect | 1404, 1405, 1406, 1407, 1408, 1409, 1410, 1411, 1412, 1413, 1414, 1415, 1416 | archived | local_quiet; not_applicable | none |
| orch-1432-1437 | unknown_dialect | 1432, 1433, 1434, 1435, 1436, 1437 | archived | local_quiet; not_applicable | none |
| orch-1444-1446 | unknown_dialect | 1444, 1445, 1446 | archived | local_quiet; not_applicable | none |
| orch-1445-1446-1480 | unknown_dialect | 1445, 1446, 1480 | abandoned | local_quiet; forge_quiet | elevenyellow/nodocom#1480 |
| orch-1459-1460-1462 | unknown_dialect | 1459, 1460, 1462 | archived | local_quiet; not_applicable | none |
| orch-1501-1503 | unknown_dialect | 1501, 1502, 1503 | archived | local_quiet; not_applicable | none |
| orch-1518-1519 | unknown_dialect | 1518, 1519 | archived | local_quiet; not_applicable | none |
| orch-1524-1525-1526 | unknown_dialect | 1524, 1525, 1526 | archived | local_quiet; not_applicable | none |
| orch-1564-1572-1580 | unknown_dialect | 1564, 1572, 1580 | archived | local_quiet; not_applicable | none |
| orch-1603-1889-1895 | unknown_dialect | 1889, 1890 | archived | local_quiet; not_applicable | none |
| orch-1622-1623 | unknown_dialect | 1622, 1623 | archived | local_quiet; not_applicable | none |
| orch-1630-1631-1633 | unknown_dialect | 1630, 1631, 1633 | archived | local_quiet; not_applicable | none |
| orch-1635-1642 | unknown_dialect | 1635, 1636, 1637, 1638, 1639, 1640, 1641, 1642 | archived | local_quiet; not_applicable | none |
| orch-1643-1655 | unknown_dialect | 1643, 1644, 1645, 1646, 1647, 1648 | archived | local_quiet; not_applicable | none |
| orch-1649-1655 | unknown_dialect | 1649, 1650, 1651, 1652, 1653, 1654 | archived | local_quiet; not_applicable | none |
| orch-1649-1655-r2 | unknown_dialect | 1651, 1655 | archived | local_quiet; not_applicable | none |
| orch-1670-1673-1674 | unknown_dialect | 1670, 1673 | archived | local_quiet; not_applicable | none |
| orch-1674-1677-1678-1679-1681-1683 | unknown_dialect | 1674, 1677, 1678, 1679, 1681, 1683 | archived | local_quiet; not_applicable | none |
| orch-1692-1663-1666 | unknown_dialect | 1663, 1664, 1665, 1666, 1692 | archived | local_quiet; not_applicable | none |
| orch-1702-1707 | unknown_dialect | 1702, 1703, 1704, 1705, 1706, 1707 | archived | local_quiet; not_applicable | none |
| orch-1781-1782-1783 | unknown_dialect | 1781, 1782, 1783 | archived | local_quiet; not_applicable | none |
| orch-1789-1790-1793 | unknown_dialect | 1789, 1790, 1793 | archived | local_quiet; not_applicable | none |
| orch-1833-1834 | unknown_dialect | 1833, 1834 | archived | local_quiet; not_applicable | none |
| orch-1838-1840-1841-1850-1851-1857 | unknown_dialect | 1838, 1840, 1841, 1850, 1851, 1857 | archived | local_quiet; not_applicable | none |
| orch-1842-1843-1844-1845-1846 | unknown_dialect | 1842, 1843, 1844, 1845, 1846 | archived | local_quiet; not_applicable | none |
| orch-1869-1870-1871-1872-1873 | unknown_dialect | 1869, 1870, 1871, 1872 | abandoned | local_quiet; forge_quiet | elevenyellow/nodocom#1871, elevenyellow/nodocom#1872 |
| orch-1898-1899-1906 | unknown_dialect | 1898, 1899, 1906 | archived | local_quiet; not_applicable | none |
| orch-1912-1915 | unknown_dialect | 1912, 1913, 1914, 1915 | archived | local_quiet; not_applicable | none |
| orch-1938-1939-1891-1895 | unknown_dialect | 1891, 1892, 1893, 1894, 1938, 1939 | archived | local_quiet; not_applicable | none |
| orch-cost-control-1799-1827 | unknown_dialect | 1799, 1800, 1801, 1812, 1813, 1816 | archived | local_quiet; not_applicable | none |
| orch-retire-stage-mode | unknown_dialect | 1759, 1760, 1761, 1762, 1763, 1764, 1765, 1766, 1767, 1768, 1769, 1770, 1771, 1772 | archived | local_quiet; not_applicable | none |
| orchestrate-1231-1237 | invalid_state | 1234 | archived | local_quiet; not_applicable | none |
| orchestrate-1261-1262-1263 | invalid_state | 1261, 1262, 1263 | archived | local_quiet; not_applicable | none |
| run-1248-1249 | invalid_state | 1248, 1249 | archived | local_quiet; not_applicable | none |

Each issue below is re-delivered fresh on the strict path, and no archived ledger is resumed. nix-config has no abandoned or unresolved ledger, and no ledger is unresolved on any root.

##### #584 re-delivery

- /Users/anis/Projects/arcwave orchestrate-agent-ready-20260914T185053Z (abandoned): fagenorn/arcwave#147 open
- /Users/anis/Projects/argus issues-99-105 (abandoned): fagenorn/argus#102 open
- /Users/anis/Projects/argus orch-78-94-20260821 (abandoned): fagenorn/argus#78 open, fagenorn/argus#79 open, fagenorn/argus#80 open, fagenorn/argus#81 open
- /Users/anis/Projects/nodocom orch-1293-1295-1296 (abandoned): elevenyellow/nodocom#1296 open
- /Users/anis/Projects/nodocom orch-1445-1446-1480 (abandoned): elevenyellow/nodocom#1480 open
- /Users/anis/Projects/nodocom orch-1869-1870-1871-1872-1873 (abandoned): elevenyellow/nodocom#1871 open, elevenyellow/nodocom#1872 open

Item verdict: **human-pending** (mbp JarBird `migrate 19` awaits gate step 1, and anis-desktop was unreachable; the four refused-ledger roots are green)

### C7 — Retained worktrees have a strict-path mapping

> Do not activate while any legacy attempt or worktree lacks a resumable strict-path mapping (issue 130 refresh)

```text
C7.a git --no-optional-locks -C R worktree list --porcelain
C7.b grep -l -F -e '"<path>"' -e '"<realpath>"' R/.superpowers/workflows/*/state.json
```

| Host | Subject | Revision | Command | UTC | Exit | Observed | Verdict |
|------|---------|----------|---------|-----|------|----------|---------|
| anis-desktop | host | — | C1.c | 2026-11-03T15:55:33Z | 255 | unreachable in Task 1 (C1.c exit 255) | human-pending |
| mbp | /Users/anis/Projects/arcwave | 1f4ab4731c8b dev 0 dirty | C7.a; C7.b | 2026-11-03T16:19:45Z | 0; 0 | worktrees 137: current 0, migrate 10, refused-only 2, unmapped 125 | red |
| mbp | /Users/anis/Projects/argus | 21338cae51ea main 1 dirty | C7.a; C7.b | 2026-11-03T16:19:52Z | 0; 0 | worktrees 13: current 0, migrate 8, refused-only 1, unmapped 4 | red |
| mbp | /Users/anis/tmp/nix-config | f6a48dcf66fb main 0 dirty | C7.a; C7.b | 2026-11-03T16:19:37Z | 0; 0 | worktrees 22: current 6, migrate 5, refused-only 0, unmapped 11 | red |
| mbp | /Users/anis/Projects/jarbird | dd3964e3b2a7 dev 8 dirty | C7.a; C7.b | 2026-11-03T16:19:53Z | 0; 0 | worktrees 17: current 4, migrate 4, refused-only 0, unmapped 9 | red |
| mbp | /Users/anis/Projects/nodocom | ef9eb5e8d25e dev 0 dirty | C7.a; C7.b | 2026-11-03T16:19:56Z | 0; 0 | worktrees 26: current 3, migrate 2, refused-only 6, unmapped 15 | red |
| eleven-m5 | /Users/anis/Projects/jarbird | 81c45be0afa7 main 0 dirty | C7.a; C7.b | 2026-11-03T16:20:04Z | 0; 0 | worktrees 8: current 8, migrate 0, refused-only 0, unmapped 0 | green |

Exit is the inventory script's, then the classifier's; both ran on every root. Counts include every linked worktree of the root, this run's included. Task 5 re-runs the script and classifier for the per-path list.

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
| mbp | home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md | 075934a7152d | C8.c | 2026-11-03T16:08:28Z | 0 | 3fe58ec0f191 (latest; added 5825027f02a4 by PR 141, issue 119) | green |

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

Re-read after #583 (read-only, 2026-11-08T13:33:54Z): mbp /Users/anis/Projects/nodocom at de844daee933 dev 0 dirty, after https://github.com/elevenyellow/nodocom/pull/2603 merged as de844daee9339d3e99fa496908fd7354a0fa3255: C10.a exit 0, doctor passed, no warning checks, 0 suppressed or not_run, admission passed. Root row green under the rule above; the row in the table is the 2026-11-03 reading.

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

Re-read after #581 (read-only, 2026-11-08T09:23:11Z): mbp /Users/anis/Projects/arcwave at 2adb089868c5 dev 0 dirty, after https://github.com/fagenorn/arcwave/pull/227 merged as 2adb089868c59c7139bd6591d70ece716d937a31: C11.a exit 0, platform 1.1.0, 2 deprecations, deprecated_uses []; C11.b exit 0, no output; C11.c exit 0, deploy.adapter none; C11.d exit 1, no output. Root row green under the rule above; the row in the table is the 2026-11-03 reading.

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
| anis-desktop | host | — | C1.c | 2026-11-03T15:55:33Z | 255 | unreachable in Task 1 (C1.c exit 255) | human-pending |

The two reachable hosts run different bridge builds (distinct store paths); per D2 and #66 that is recorded and is not red.

Item verdict: **human-pending**

### P1–P6 — Post-activation items

These six items are `post` and `human-pending`: this attempt does not evaluate them, and the owner judges them at gate step 5 with the evidence in the spec's §3 post-activation table.

| ID | Predicate |
|----|-----------|
| P1 | No static fallback ladder remains in the resolver, conformance or workflow-entry paths of any adopted project, and a missing contract fails closed with a closed error code (AC2; #69) |
| P2 | The bridge generation is retained, and rollback to it is exercised once before retirement (AC3; refresh) |
| P3 | A Claude-driven and a Codex-driven ship complete on the strict path, against declared host capabilities with bounded admission (AC4; refresh) |
| P4 | The #71 retirement predicates: the active generation's identity matches its manifest; active and bridge fleet conformance are green; `workflow_entry` passes through both adapters; post-activation smoke is green; doctor reports no residue; traces show zero removed-fallback executions (#71) |
| P5 | Implementation delivered, PR merged, tracker closed and cleanup postconditions reconciled before retirement (refresh) |
| P6 | Retirement is recorded with the evidence that satisfied each strict predicate (AC5) |

## Dispositions

| Rows | Repair route | Disposition |
|------|--------------|-------------|
| C3 mbp .agents/artifacts/evidence/; C4 mbp home/common/agent-skills/platform-manifest.json | Build the strict-cutover candidate (platform 2.0.0, no bridge paths) | #579 built the candidate at origin/cutover-130-candidate; C3: owner: paired live trials (#128 D11), tracked in the C3 issue that #579's ship files; C4.b: the fleet-migration follow-up |
| C11 mbp host; C11 eleven-m5 host | Bridge minor declaring the deprecations | #580 filed |
| C11 mbp /Users/anis/Projects/arcwave | Arcwave: retire the tracked legacy skills config and its reader | #581 delivered (fagenorn/arcwave#227) |
| C11 mbp /Users/anis/Projects/nodocom | Nodo: move the railway deploy off bindings.deploy | #582 filed |
| C11 mbp /Users/anis/Projects/jarbird | JarBird github-actions-health deploy watch (release core) | #555 cited |
| C2 mbp /Users/anis/Projects/nodocom; C10 mbp /Users/anis/Projects/nodocom | Nodo: repair the overbroad runtime-sentinel ignore rule | #583 delivered (elevenyellow/nodocom#2603) |
| C6 mbp /Users/anis/Projects/arcwave; C6 mbp /Users/anis/Projects/argus; C6 mbp /Users/anis/tmp/nix-config; C6 mbp /Users/anis/Projects/nodocom | Dispose of the refused legacy ledgers | #584 delivered |
| C7 mbp /Users/anis/Projects/arcwave; C7 mbp /Users/anis/Projects/argus; C7 mbp /Users/anis/tmp/nix-config; C7 mbp /Users/anis/Projects/jarbird; C7 mbp /Users/anis/Projects/nodocom | Reconcile worktrees without a resumable mapping | #585 filed |
| C2 mbp /Users/anis/tmp/nix-config | Keep bundle and trials JSON out of the adoption-evidence candidate set (D16) | #586 filed |

Owner-run, not filed: the #70 live paired Claude and Codex trials (#128 D11), on issue 130's gate once F1's candidate exists.

## Human gate

This section is the owner's activation and rollback procedure. This attempt does not run it. The owner runs every step, in order: steps 1 and 2 first, and step 3 onward only when step 2 reads every pre-activation verdict green. `K_H`, `N_H` and the roots below are the values the evidence observed. `<candidate>` is the one parameter: the 40-hex commit of the strict-cutover candidate (built under #579) that C3's approved bundle binds. Read it from the head of `origin/cutover-130-candidate` (`git ls-remote origin refs/heads/cutover-130-candidate`). A regenerated candidate is force-free: a new commit on that branch. `N_H` must be re-read in step 2, because any switch before the activation moves it: the observed values are eleven-m5 28 and mbp 309, and a different reading in step 2 replaces them in step 6.

Observed at evidence time: eleven-m5 has `K_H` /Users/anis/Projects/nix-config and `N_H` 28. mbp has `K_H` /Users/anis/tmp/nix-config and `N_H` 309. anis-desktop was unreachable at evidence time: read K_H and N_H for it in step 2.

### 1. Migrate the ledgers

Under the bridge generation, for every roster root, on its host. The first line must report "refused": 0, and the bridge's helper already reads and writes the migrated schema (schema 11), so a later rollback to the bridge generation needs no reverse migration. A refused ledger stops the gate here: C6 is red.

On mbp:

```
workflow-state migrate --repo-root /Users/anis/Projects/arcwave           # must report "refused": 0
workflow-state migrate --repo-root /Users/anis/Projects/arcwave --apply
```

```
workflow-state migrate --repo-root /Users/anis/Projects/argus           # must report "refused": 0
workflow-state migrate --repo-root /Users/anis/Projects/argus --apply
```

```
workflow-state migrate --repo-root /Users/anis/tmp/nix-config           # must report "refused": 0
workflow-state migrate --repo-root /Users/anis/tmp/nix-config --apply
```

```
workflow-state migrate --repo-root /Users/anis/Projects/jarbird           # must report "refused": 0
workflow-state migrate --repo-root /Users/anis/Projects/jarbird --apply
```

```
workflow-state migrate --repo-root /Users/anis/Projects/nodocom           # must report "refused": 0
workflow-state migrate --repo-root /Users/anis/Projects/nodocom --apply
```

On eleven-m5:

```
workflow-state migrate --repo-root /Users/anis/Projects/jarbird           # must report "refused": 0
workflow-state migrate --repo-root /Users/anis/Projects/jarbird --apply
```

On anis-desktop, read its registry first (`cat ~/.agents/state/fleet/registry.json`) and run the same pair of lines for each root in it.

### 2. Re-run the checklist

On every host, re-run every pre-activation item's commands. Every verdict must be green. Any changed or red verdict rewinds the stage (#71): the candidate is regenerated, never patched around. Record `N_H` from `readlink /nix/var/nix/profiles/system`.

### 3. Freeze

From step 2 until retirement is recorded, on every host, run no `just gc`, no `nix-collect-garbage`, no system-generation deletion and no `just switch` other than step 4's.

### 4. Activation

Every host in one session, host by host. The approved bundle must bind `<candidate>`. `just switch` is the contract's `nix-activate` command, run from the candidate checkout's root. The new system generation roots the build, so the worktree is removed and leaves no residue for C7. If any host fails to activate, roll back every host already activated, because #71 forbids a mixed live fleet.

Each host block runs in a subshell under `set -e`, so any failing line stops the block before `just switch`: a `.worktrees/cutover-130` left by an earlier attempt makes `worktree add` fail, and the `test` line refuses a checkout whose HEAD is not `<candidate>`. Remove such a leftover worktree and run the block again. `just switch` runs in its own inner subshell, so the operator's shell never stands in the worktree the last line removes.

On eleven-m5:

```
(
  set -e
  git -C /Users/anis/Projects/nix-config fetch origin
  git -C /Users/anis/Projects/nix-config worktree add --detach /Users/anis/Projects/nix-config/.worktrees/cutover-130 <candidate>
  test "$(git -C /Users/anis/Projects/nix-config/.worktrees/cutover-130 rev-parse HEAD)" = <candidate>
  ( cd /Users/anis/Projects/nix-config/.worktrees/cutover-130 && just switch )
  git -C /Users/anis/Projects/nix-config worktree remove /Users/anis/Projects/nix-config/.worktrees/cutover-130
)
```

On mbp:

```
(
  set -e
  git -C /Users/anis/tmp/nix-config fetch origin
  git -C /Users/anis/tmp/nix-config worktree add --detach /Users/anis/tmp/nix-config/.worktrees/cutover-130 <candidate>
  test "$(git -C /Users/anis/tmp/nix-config/.worktrees/cutover-130 rev-parse HEAD)" = <candidate>
  ( cd /Users/anis/tmp/nix-config/.worktrees/cutover-130 && just switch )
  git -C /Users/anis/tmp/nix-config worktree remove /Users/anis/tmp/nix-config/.worktrees/cutover-130
)
```

anis-desktop was unreachable at evidence time: read K_H and N_H for it in step 2. The same block applies with its `K_H`:

```
(
  set -e
  git -C K_H fetch origin
  git -C K_H worktree add --detach K_H/.worktrees/cutover-130 <candidate>
  test "$(git -C K_H/.worktrees/cutover-130 rev-parse HEAD)" = <candidate>
  ( cd K_H/.worktrees/cutover-130 && just switch )
  git -C K_H worktree remove K_H/.worktrees/cutover-130
)
```

### 5. Post-activation verification

On each host, run `resolve-project platform-status --fleet` (`platform_version` is the candidate's, every row compatible). Per root, run `conformance run --purpose fleet --repo-root R` and `conformance run --purpose doctor --repo-root R` as below; each names its root, so neither depends on the shell's current directory. Then evaluate P1–P5.

On mbp:

```
conformance run --purpose fleet --repo-root /Users/anis/Projects/arcwave
conformance run --purpose fleet --repo-root /Users/anis/Projects/argus
conformance run --purpose fleet --repo-root /Users/anis/tmp/nix-config
conformance run --purpose fleet --repo-root /Users/anis/Projects/jarbird
conformance run --purpose fleet --repo-root /Users/anis/Projects/nodocom
conformance run --purpose doctor --repo-root /Users/anis/Projects/arcwave
conformance run --purpose doctor --repo-root /Users/anis/Projects/argus
conformance run --purpose doctor --repo-root /Users/anis/tmp/nix-config
conformance run --purpose doctor --repo-root /Users/anis/Projects/jarbird
conformance run --purpose doctor --repo-root /Users/anis/Projects/nodocom
```

On eleven-m5:

```
conformance run --purpose fleet --repo-root /Users/anis/Projects/jarbird
conformance run --purpose doctor --repo-root /Users/anis/Projects/jarbird
```

On anis-desktop, run the same fleet and doctor lines for each root in its registry.

### 6. Rollback

Per host, to the bridge generation, with `N_H` as step 2 read it (the observed values are shown). Rollback is also how P2 is exercised once before retirement. If activation failed on any host, roll back every host already activated.

```
# darwin hosts
sudo /nix/var/nix/profiles/system-28-link/sw/bin/darwin-rebuild --switch-generation 28    # eleven-m5
sudo /nix/var/nix/profiles/system-309-link/sw/bin/darwin-rebuild --switch-generation 309  # mbp
```

anis-desktop was unreachable at evidence time: read K_H and N_H for it in step 2. It is a NixOS host, so rollback is:

```
sudo nix-env --profile /nix/var/nix/profiles/system --switch-generation N_H
sudo /nix/var/nix/profiles/system/bin/switch-to-configuration switch
```

After rollback, re-run C12 to show the bridge generation is running again.

When step 6 runs as P2's exercise, re-activation follows: under step 3's freeze, run step 4's host block again on every host at the same `<candidate>`, then repeat step 5's post-activation verification on every host. P4–P6 are evaluated, and retirement is recorded, only after that renewed step 5 is green. When step 6 runs because activation failed, the gate stops on the bridge generation.

## Criteria map

AC1 to AC5 are the issue's `## Acceptance criteria`, AC6 to AC10 its `### Additional acceptance criteria`. A criterion is `met` only when every mapped item is green, `human_pending` when the rest wait on the owner or the activation, and `unmet` otherwise.

| AC | Criterion | Items | Verdict |
|----|-----------|-------|---------|
| AC1 | A committed cutover checklist cites registration for all three projects, an `approved` bundle for the cutover candidate, no in-flight legacy release or unresumable legacy attempt, a clean `doctor` on every host, and the Codex handoff — each with fresh evidence. (False at base: none of the inputs exist.) | C2, C3, C5, C6, C8, C10 | unmet |
| AC2 | After activation, no static fallback ladder remains in the resolver, conformance or workflow-entry paths of any adopted project; a missing contract fails closed with a closed error code everywhere. (False at base: the ladders are the current behaviour.) | P1 | human_pending |
| AC3 | The bridge generation is retained and rollback to it is exercised once before retirement is recorded. (False at base: no bridge exists.) | P2, C12 | human_pending |
| AC4 | Both a Claude-driven and a Codex-driven ship complete on the strict path after cutover. (False at base: the Codex path cannot complete a ship without manual intervention.) | P3 | human_pending |
| AC5 | Retirement is recorded with the evidence that satisfied each strict predicate. | P6 | human_pending |
| AC6 | The checklist derives the fleet roster from current registry truth and records the explicit Arcwave inclusion/exclusion decision. | C1 | human_pending |
| AC7 | There are zero active legacy attempts and zero retained legacy worktrees that cannot resume on a declared path. | C6, C7 | unmet |
| AC8 | Rollback to the retained bridge generation is exercised before retirement. | P2 | human_pending |
| AC9 | Claude and Codex paths complete against declared host capabilities, including bounded capacity admission. | C9, P3 | human_pending |
| AC10 | Implementation delivered, PR merged, tracker closed, and cleanup postconditions are reconciled before bridge retirement. | P5 | human_pending |
