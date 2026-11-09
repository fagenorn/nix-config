# Stage-4 cutover checklist — issue 130

Purpose: pre-activation predicates for the issue 130 strict cutover with fresh read-only evidence, red-row dispositions and the owner's gate; preparation only, per spec D1 and the owner's 2026-11-08 overnight decision.
Run: rel_01a1a1d8-7220-72a2-841e-df2806f78396; refreshed by the issue 130 overnight preparation, 2026-11-09
Revisions: origin/main 6e2f9dde45cb76f363813801fb3b3b42b430545d (frozen for the cutover); candidate origin/cutover-130-candidate 953f9b4b29253720e9868ab71b456b0ed3a62f63
Hosts: eleven-m5, mbp, anis-desktop
Evidence window: 2026-11-09T01:30:03Z to @@WINDOW_END@@
Activation readiness: activation not permitted — @@COUNTS@@ of 11 pre-activation items. C8 is retired, not counted.

Owner decisions applied (issue 130, 2026-11-08T13:20:31Z): C8 (the Codex ship handoff) is no longer a cutover predicate. C3's live trials are Claude-only. AC4 and AC9 (P3) need a Claude-driven ship on the strict path only.

## Summary

| ID | Predicate | Source | Phase | Verdict | Disposition |
|----|-----------|--------|-------|---------|-------------|
| C1 | The roster is derived from current registry truth, with the Arcwave decision recorded | refresh | pre | human-pending | anis-desktop: owner: host online |
| C2 | Every roster project is registered and compatible, and its adoption evidence is still current | issue; #71 | pre | human-pending | anis-desktop: owner: host online |
| C3 | A fresh `approved` #70 bundle covers the strict-cutover candidate as a whole | issue; #71; #128 AC5 | pre | red | #725: Claude-only gate mode, trial corpus and paid trial; lands after the main freeze |
| C4 | Candidate and retained-bridge fleet preflight are green for every registered project | #71 | pre | red | C4.b: #724 |
| C5 | No legacy release is in flight | #90 | pre | human-pending | anis-desktop: owner: host online |
| C6 | No legacy attempt is left without a resumable strict-path mapping | issue; refresh | pre | human-pending | JarBird on mbp and eleven-m5: owner: gate step 1; anis-desktop: owner: host online |
| C7 | No retained legacy worktree is left without a resumable mapping | refresh | pre | red | mbp JarBird: #700; JarBird on eleven-m5: owner: gate step 1; anis-desktop: owner: host online |
| C8 | The Codex ship handoff is in place | issue; #119 | — | retired | owner decision 2026-11-08: not a cutover predicate |
| C9 | The Claude path answers as its declared host capabilities say, including bounded admission; Codex answers its declared `unsupported` | refresh | pre | human-pending | anis-desktop: owner: host online |
| C10 | `doctor` is clean on every adopted host | issue | pre | human-pending | anis-desktop: owner: host online |
| C11 | Deprecation notices shipped in a bridge minor, and the fleet has zero users of the deprecated paths | issue; #66 | pre | red | #724; anis-desktop: owner: host online |
| C12 | The bridge generation is identified per host and can be retained | issue; #66 | pre | human-pending | anis-desktop: owner: host online |
| P1 | No static fallback ladder remains in the resolver, conformance or workflow-entry paths of any adopted project, and a missing contract fails closed with a closed error code | AC2; #69 | post | human-pending | post-activation |
| P2 | The bridge generation is retained, and rollback to it is exercised once before retirement | AC3; refresh | post | human-pending | post-activation |
| P3 | A Claude-driven ship completes on the strict path, against declared host capabilities with bounded admission | AC4; refresh | post | human-pending | post-activation |
| P4 | The #71 retirement predicates: the active generation's identity matches its manifest; active and bridge fleet conformance are green; `workflow_entry` passes through both adapters; post-activation smoke is green; doctor reports no residue; traces show zero removed-fallback executions | #71 | post | human-pending | post-activation |
| P5 | Implementation delivered, PR merged, tracker closed and cleanup postconditions reconciled before retirement | refresh | post | human-pending | post-activation |
| P6 | Retirement is recorded with the evidence that satisfied each strict predicate | AC5 | post | human-pending | post-activation |

Writes this refresh made, all outside the evidence commands and all recoverable:
- eleven-m5 was fast-forwarded from 4444bc2340d3 to 6e2f9dde45cb and switched headless with `just switch`, from system-34 to system-35 (bridge 1.2.0). The launchd user agents did not bootstrap over ssh, because nobody is logged in at the console. eleven-m5 is the bridge, not the candidate.
- eleven-m5: `adopt-project verify --repo-root /Users/anis/Projects/nix-config --register` at 2026-11-09T01:00:50Z registered fagenorn/nix-config. A copy of the previous registry is at `~/.agents/state/fleet/registry.json.pre-130-20261109T010050Z`.
- eleven-m5: an empty ledger store, `/Users/anis/Projects/nix-config/.superpowers/workflows` (gitignored), was created at 2026-11-09T01:34:39Z. Without it, `workflow-state migrate` and the C7 check refused the newly registered root with `workflows must be an existing non-symlink directory`. `rmdir` undoes it.
- mbp: the closed issue 705's worktree `/Users/anis/tmp/nix-config/.worktrees/worktree-issue-705-eleven-m5-switch-aborts-reloading-verify-pending-user-agent` was removed. It was clean, its HEAD 4be38ee587a6 is in origin/main (PR 719), and its branch is kept.

## Roster

### Hosts

| Host | Reachable | Generation | Store path | configurationRevision | platform_version | manifest_path | K_H | Registry sha256 before | Registry sha256 after |
|------|-----------|------------|------------|-----------------------|------------------|---------------|-----|------------------------|------------------------|
| eleven-m5 | yes | system-35 | /nix/store/9p2z21bpjmyajmhbxx90p3f995r76r4q-darwin-system-25.11.ebec37a | 6e2f9dde45cb | 1.2.0 | /nix/store/yl4yfaps8kndji4qdnpy73vqk2cpcqmk-hm_platformmanifest.json | /Users/anis/Projects/nix-config | 0e3643016a781e74c21eada5322e060b742ff87cc9b19214465b0caa61f404f5 (before the nix-config registration) | ea8e1d478c53b8851f7c8237cec0f65bb99360ff92e4e6c95da34ec28f565c94 (fagenorn/nix-config added) |
| mbp | yes | system-324 | /nix/store/75gdn69a3licfa821db48pybbak70z24-darwin-system-25.11.ebec37a | 3604bd389567 | 1.2.0 | /nix/store/yl4yfaps8kndji4qdnpy73vqk2cpcqmk-hm_platformmanifest.json | /Users/anis/tmp/nix-config | 819bbd8487305b83cf5fcd987f559847a03f8d51d4df155f70b5e2fb30905e75 | 819bbd8487305b83cf5fcd987f559847a03f8d51d4df155f70b5e2fb30905e75 |
| anis-desktop | no (probed once, 2026-11-09T01:30:03Z, exit 255: connect to anis-desktop.mink-fort.ts.net port 48521 timed out) | — | — | — | — | — | — | — | — |

### Projects

| Host | project_id | Root | branch_override | HEAD before | Dirty | HEAD after |
|------|------------|------|-----------------|-------------|-------|------------|
| mbp | arcwave | /Users/anis/Projects/arcwave | dev (default_contract_unresolved) | 2adb089868c59c7139bd6591d70ece716d937a31 | 0 | 2adb089868c59c7139bd6591d70ece716d937a31 |
| mbp | fagenorn/argus | /Users/anis/Projects/argus | — | 21338cae51ea396f6c3f9664642e06463c25d97c | 1 | 21338cae51ea396f6c3f9664642e06463c25d97c |
| mbp | fagenorn/nix-config | /Users/anis/tmp/nix-config | — | 6e2f9dde45cb76f363813801fb3b3b42b430545d | 0 | 6e2f9dde45cb76f363813801fb3b3b42b430545d |
| mbp | jarbird | /Users/anis/Projects/jarbird | — | 75f28c1d98f36af3bd519bb50cc408f815081958 | 1 | 7837084d9845046d56abcca75e77cf302daae243 |
| mbp | nodocom | /Users/anis/Projects/nodocom | dev (default_contract_unresolved) | 6eb54814447be4dcc7462f4268fde2e0d58de0de | 0 | 6eb54814447be4dcc7462f4268fde2e0d58de0de |
| eleven-m5 | fagenorn/nix-config | /Users/anis/Projects/nix-config | — | 6e2f9dde45cb76f363813801fb3b3b42b430545d | 0 | 6e2f9dde45cb76f363813801fb3b3b42b430545d |
| eleven-m5 | jarbird | /Users/anis/Projects/jarbird | — | 81c45be0afa78f946e00ab445a28ceab84814cdd | 0 | 81c45be0afa78f946e00ab445a28ceab84814cdd |

Every registered project on every reachable host is in (D2). Arcwave is in, by the repository owner's 2026-11-03 comment on issue 130. fagenorn/nix-config on eleven-m5 is new to the roster since the last refresh: it was registered at 2026-11-09T01:00:50Z, as C1 and C2 expect. Arcwave's and Nodo's `branch_override` of `dev` (`default_contract_unresolved`) is the designed #363 registration path, recorded as a fact and not as a red item. anis-desktop was probed once and was unreachable, so each of its rows is `human-pending`. It is never dropped from the roster.

Snapshot: the after-snapshot was taken at 2026-11-09T01:41:48Z on mbp and at 01:41:49Z on eleven-m5. mbp's registry is byte-identical to its before value. eleven-m5's registry differs only by the fagenorn/nix-config registration this refresh made. Six of the seven roots equal their before values, with the dirty counts the rows record. One root moved, and not because of this run: mbp JarBird went from `75f28c1d98f3` to `7837084d9845`. That is a fast-forward of 9 commits (`merge origin/dev` in its reflog at 2026-11-09T01:37:22Z, elevenyellow/jarbird PR #541) made by another session after the JarBird rows were read, so every JarBird row on mbp cites `75f28c1d98f3`.

This refresh committed only on its evidence branch and on `cutover-130-candidate`. The only roster root or registry it wrote is the set of writes listed under the summary.

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
| mbp | flake.nix | 6e2f9dde45cb | C1.a; C1.b | 2026-11-09T01:36:45Z | 0; 0 | darwin ["eleven-m5","mbp"]; nixos ["anis-desktop"] | green |
| eleven-m5 | host | system-35 | C1.c; C1.d | 2026-11-09T01:31:28Z | 0; 0 | hostname eleven-m5; 2 projects: fagenorn/nix-config, jarbird | green |
| mbp | host | system-324 | C1.c; C1.d | 2026-11-09T01:30:47Z | 0; 0 | hostname mbp; 5 projects: arcwave, fagenorn/argus, fagenorn/nix-config, jarbird, nodocom | green |
| anis-desktop | host | — | C1.c | 2026-11-09T01:30:03Z | 255 | unreachable (probed once) | human-pending |

Earlier readings (2026-11-03 to 2026-11-08) and their re-read notes are in this file's history at origin/main 6e2f9dde45cb.

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
| mbp | host | system-324 | C2.a | 2026-11-09T01:30:47Z | 0 | platform 1.2.0, project schemas [1, 2]; 5/5 fleet rows compatible; every root has a row | green |
| eleven-m5 | host | system-35 | C2.a | 2026-11-09T01:31:29Z | 0 | platform 1.2.0, project schemas [1, 2]; 2/2 fleet rows compatible; every root has a row | green |
| anis-desktop | host | — | C1.c | 2026-11-09T01:30:03Z | 255 | unreachable (probed once) | human-pending |
| mbp | /Users/anis/Projects/arcwave | 2adb089868c5 dev 0 dirty | C2.b; C2.c | 2026-11-09T01:30:49Z | 0; 0 | fleet passed, 13/13; verify adopted, blockers 0 | green |
| mbp | /Users/anis/Projects/argus | 21338cae51ea main 1 dirty | C2.b; C2.c | 2026-11-09T01:30:53Z | 0; 0 | fleet passed, 13/13; verify adopted, blockers 0 | green |
| mbp | /Users/anis/tmp/nix-config | 6e2f9dde45cb main 0 dirty | C2.b; C2.c | 2026-11-09T01:30:55Z | 0; 0 | fleet passed, 13/13; verify adopted, blockers 0 (adoption-evidence-record, adoption-commit-derived and path-migration-map pass since #586) | green |
| mbp | /Users/anis/Projects/jarbird | 75f28c1d98f3 dev 1 dirty | C2.b; C2.c | 2026-11-09T01:30:57Z | 0; 0 | fleet passed, 13/13; verify adopted, blockers 0 | green |
| mbp | /Users/anis/Projects/nodocom | 6eb54814447b dev 0 dirty | C2.b; C2.c | 2026-11-09T01:31:00Z | 0; 0 | fleet passed, 13/13; verify adopted, blockers 0 | green |
| eleven-m5 | /Users/anis/Projects/nix-config | 6e2f9dde45cb main 0 dirty | C2.b; C2.c | 2026-11-09T01:31:29Z | 0; 0 | fleet passed, 13/13; verify adopted, blockers 0; registered 2026-11-09T01:00:50Z | green |
| eleven-m5 | /Users/anis/Projects/jarbird | 81c45be0afa7 main 0 dirty | C2.b; C2.c | 2026-11-09T01:31:31Z | 0; 0 | fleet passed, 13/13; verify adopted, blockers 0 | green |

Registration is the C2.a fleet row. `verify` reports `registered` false unless `--register` was given, and only the eleven-m5 nix-config registration above used it.

Earlier readings (2026-11-03 to 2026-11-08) and their re-read notes are in this file's history at origin/main 6e2f9dde45cb.

Item verdict: **human-pending** (every reachable row is green; anis-desktop was unreachable)

### C3 — Approved bundle binds the candidate

> a fresh `approved` evidence bundle from the token-gate instrument covers the strict-cutover candidate as a whole (issue 130; #71); after the owner's 2026-11-08 decision the live trials are Claude-only

```text
C3.a git ls-tree --name-only origin/main -- .agents/artifacts/evidence/
C3.b git show origin/main:<path>
C3.c home/common/verify-pending/checks/cutover-bundle
```

C3.c reads `<candidate>`, the head of `origin/cutover-130-candidate`, which is 953f9b4b29253720e9868ab71b456b0ed3a62f63 at this pass. It also reads every `*-bundle.json` at `origin/main` and passes each one through `agent_gate_bundle.verify_bundle`. That function recomputes the id over the body and re-decides the state from the bundle's own evidence. The row is green only when some bundle verifies `approved` and binds `<candidate>`. A bundle the verifier refuses is unreadable and never counts, and the document's own `state` field is never read. The item takes its worst row.

| Host | Subject | Revision | Command | UTC | Exit | Observed | Verdict |
|------|---------|----------|---------|-----|------|----------|---------|
| mbp | origin/main .agents/artifacts/evidence/ against 953f9b4b2925 | 6e2f9dde45cb | C3.c | 2026-11-09T01:31:24Z | 75 | 0 of 3 bundles at origin/main are approved and bind the candidate. All three are unmeasured and bound to other commits: cutover-579 to 720c67e53867, promotion-127 to 66ccba5844ea, release-128 to 33149faddfc0. | red |
| eleven-m5 | origin/main .agents/artifacts/evidence/ against 953f9b4b2925 | 6e2f9dde45cb | C3.c | 2026-11-09T01:31:45Z | 75 | same reading as mbp | red |

The Claude-only live trial did not run at this refresh, and this refresh produced no bundle for 953f9b4b2925. The current tools cannot produce an approved Claude-only bundle. `agent_gate_bundle` requires both strata (`STRATA = ("claude", "codex")`), so any case without a codex stratum is `STRATUM_MISSING` and the bundle is `unmeasured`. No trial corpus or runner exists yet. Because C3.c verifies bundles at origin/main, a gate change and a bundle can read green only after the main freeze lifts. This refresh took the reversible choice: it spent nothing on a protocol nobody had defined. #725 was filed (blocks #130) for the Claude-only gate mode, the trial corpus and the paid trial bound to the candidate. The owner's approval of the Claude-only paid trial (2026-11-08T23:04:09Z) stands for that issue.

The candidate 720c67e53867, which cutover-579-bundle.json binds, is superseded by 953f9b4b2925. That is a fast-forward of the branch: it merges origin/main 6e2f9dde45cb (commit 1a747e911a78), then retires the one deploy-binding gate that #582 pinned beside its railway activation unit, and exempts the #582 C11 zero-users detector in `verify_checks.py` from the ladder audit as detection, not a route (commit 953f9b4b2925).

Earlier readings (2026-11-03 to 2026-11-08) and their re-read notes are in this file's history at origin/main 6e2f9dde45cb.

Item verdict: **red**

### C4 — Candidate and bridge fleet preflight

> candidate and retained-bridge fleet preflight green for every registered project (#71)

```text
C4.a PYTHONPATH=python python3 -m agent_tools.verify_checks cutover-manifest
C4.b home/common/verify-pending/checks/cutover-preflight
```

C4.a passes only when `origin/main`'s manifest has major 1 and declares a deprecation equal to every `removals` entry of `<candidate>`'s manifest. C4.b passes only on `verdict: green` on every reachable host, and it includes C4.a. The item takes its worst row. Both commands ran from origin/main 6e2f9dde45cb, and `<candidate>` is 953f9b4b2925.

| Host | Subject | Revision | Command | UTC | Exit | Observed | Verdict |
|------|---------|----------|---------|-----|------|----------|---------|
| mbp | home/common/agent-skills/platform-manifest.json against 953f9b4b2925 | 6e2f9dde45cb | C4.a | 2026-11-09T01:31:15Z | 0 | main_version 1.2.0; candidate_version 2.0.0; 5 removals, 0 undeclared; verdict green | green |
| eleven-m5 | home/common/agent-skills/platform-manifest.json against 953f9b4b2925 | 6e2f9dde45cb | C4.a | 2026-11-09T01:31:33Z | 0 | main_version 1.2.0; candidate_version 2.0.0; 5 removals, 0 undeclared; verdict green | green |
| mbp | fleet against 953f9b4b2925 | 6e2f9dde45cb | C4.b | 2026-11-09T01:31:19Z | 75 | verdict not_yet; bridge 1.2.0; 5/5 rows bridge_compatible, 0/5 candidate_compatible, each `candidate_incompatible` with removed_uses ["bindings-deploy"] (every project is still on project schema 1) | red |
| eleven-m5 | fleet against 953f9b4b2925 | 6e2f9dde45cb | C4.b | 2026-11-09T01:31:40Z | 75 | verdict not_yet; bridge 1.2.0; 2/2 rows bridge_compatible, 0/2 candidate_compatible, each `candidate_incompatible` with removed_uses ["bindings-deploy"] | red |
| anis-desktop | host | — | C1.c | 2026-11-09T01:30:03Z | 255 | unreachable (probed once) | human-pending |

C4.b is the fleet-migration follow-up named at #579: each fleet project's schema-2 migration commit (`bindings-deploy.retire`) has not landed yet. It is filed as #724, which blocks #130. The nix-config commit waits for the main freeze to lift. The candidate itself already carries this repository's migration (b56b9a2d).

Earlier readings (2026-11-03 to 2026-11-08) and their re-read notes are in this file's history at origin/main 6e2f9dde45cb.

Item verdict: **red**

### C5 — No legacy release in flight

> no legacy release is in flight (#90)

```text
C5.a ls -la R/.superpowers/workflows/ship-release/state.json
C5.b release transaction status --repo-root R
```

| Host | Subject | Revision | Command | UTC | Exit | Observed | Verdict |
|------|---------|----------|---------|-----|------|----------|---------|
| anis-desktop | host | — | C1.c | 2026-11-09T01:30:03Z | 255 | unreachable (probed once) | human-pending |
| mbp | /Users/anis/Projects/arcwave | 2adb089868c5 dev 0 dirty | C5.a | 2026-11-09T01:30:53Z | 2 | absent | green |
| mbp | /Users/anis/Projects/argus | 21338cae51ea main 1 dirty | C5.a | 2026-11-09T01:30:54Z | 2 | absent | green |
| mbp | /Users/anis/tmp/nix-config | 6e2f9dde45cb main 0 dirty | C5.a | 2026-11-09T01:30:56Z | 2 | absent | green |
| mbp | /Users/anis/Projects/jarbird | 75f28c1d98f3 dev 1 dirty | C5.a | 2026-11-09T01:31:00Z | 2 | absent | green |
| mbp | /Users/anis/Projects/nodocom | 6eb54814447b dev 0 dirty | C5.a | 2026-11-09T01:31:02Z | 2 | absent | green |
| eleven-m5 | /Users/anis/Projects/nix-config | 6e2f9dde45cb main 0 dirty | C5.a | 2026-11-09T01:31:31Z | 2 | absent | green |
| eleven-m5 | /Users/anis/Projects/jarbird | 81c45be0afa7 main 0 dirty | C5.a | 2026-11-09T01:31:32Z | 2 | absent | green |

No root holds a legacy `ship-release/state.json`, so C5.b did not run.

Earlier readings (2026-11-03 to 2026-11-08) and their re-read notes are in this file's history at origin/main 6e2f9dde45cb.

Item verdict: **human-pending** (every reachable row is green; anis-desktop was unreachable)

### C6 — Legacy ledgers have a strict-path mapping

> Do not activate while any legacy attempt or worktree lacks a resumable strict-path mapping (issue 130 refresh)

```text
C6.a workflow-state migrate --repo-root R
```

| Host | Subject | Revision | Command | UTC | Exit | Observed | Verdict |
|------|---------|----------|---------|-----|------|----------|---------|
| anis-desktop | host | — | C1.c | 2026-11-09T01:30:03Z | 255 | unreachable (probed once) | human-pending |
| mbp | /Users/anis/Projects/arcwave | 2adb089868c5 dev 0 dirty | C6.a | 2026-11-09T01:30:53Z | 0 | current 11, migrate 0, migrated 0, refused 0 | green |
| mbp | /Users/anis/Projects/argus | 21338cae51ea main 1 dirty | C6.a | 2026-11-09T01:30:54Z | 0 | current 8, migrate 0, migrated 0, refused 0 | green |
| mbp | /Users/anis/tmp/nix-config | 6e2f9dde45cb main 0 dirty | C6.a | 2026-11-09T01:30:56Z | 0 | current 123, migrate 0, migrated 0, refused 0 | green |
| mbp | /Users/anis/Projects/jarbird | 75f28c1d98f3 dev 1 dirty | C6.a | 2026-11-09T01:31:00Z | 0 | current 38, migrate 15, migrated 0, refused 0 | human-pending |
| mbp | /Users/anis/Projects/nodocom | 6eb54814447b dev 0 dirty | C6.a | 2026-11-09T01:31:02Z | 0 | current 154, migrate 0, migrated 0, refused 0 | green |
| eleven-m5 | /Users/anis/Projects/nix-config | 6e2f9dde45cb main 0 dirty | C6.a | 2026-11-09T01:34:39Z | 0 | current 0, migrate 0, migrated 0, refused 0 (empty store; the 01:31:31Z read exited 2 before the store existed) | green |
| eleven-m5 | /Users/anis/Projects/jarbird | 81c45be0afa7 main 0 dirty | C6.a | 2026-11-09T01:31:32Z | 0 | current 0, migrate 5, migrated 0, refused 0 | human-pending |

`workflow-state migrate` ran without `--apply` on every root. No root refuses a ledger. The JarBird `migrate` counts are schema-10 ledgers that the bridge helper migrates to schema 11 at gate step 1 (owner-run). The 2026-11-03 eleven-m5 JarBird reading was `current 5, migrate 0`; the five ledgers now read `migrate` under the current schema. No JarBird ledger was written, and nothing held by another session was touched.

Earlier readings (2026-11-03 to 2026-11-08) and their re-read notes are in this file's history at origin/main 6e2f9dde45cb.

Item verdict: **human-pending** (JarBird on mbp and eleven-m5 awaits gate step 1, and anis-desktop was unreachable; every other root is green)

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
C7.r home/common/verify-pending/checks/worktree-mapping --repo-root R ...
```

C7.r (issue 585, with the forge class of #710) states this item's rule in one read-only command. A worktree is `current` when a current ledger names it. It is `migrate` when only ledgers that still need migration name it, and `refused-only` when only refused ones do. It is `forge` when no ledger names it but an open in-progress claim, an open same-repository pull request or the declared `cutover-130-candidate` branch maps its branch. Otherwise it is `unmapped`. A root is red on any `unmapped` or `refused-only` path and human-pending on `migrate`. It ran from origin/main 6e2f9dde45cb on each host, @@C7_MBP_UTC@@ on mbp, after this run's own scratch worktree was removed and the evidence branch's pull request was opened.

| Host | Subject | Revision | Command | UTC | Exit | Observed | Verdict |
|------|---------|----------|---------|-----|------|----------|---------|
| anis-desktop | host | — | C1.c | 2026-11-09T01:30:03Z | 255 | unreachable (probed once) | human-pending |
@@C7_ROWS@@

@@C7_NOTES@@

Earlier readings (2026-11-03 to 2026-11-08) and their re-read notes are in this file's history at origin/main 6e2f9dde45cb.

Item verdict: **red**

### C8 — Codex ship handoff installed (retired)

> the Codex ship handoff is in place so that removing the fallback ladders does not strand a Codex session at the shipping step (issue 130)

The owner retired this predicate on 2026-11-08 (issue 130, 13:20:31Z). Every workflow starts in Claude Code, and Codex is only a collaborator, so the Codex ship handoff is no longer a cutover predicate. It is not counted in activation readiness. For the record, `ls -lL ~/.agents/skills/ship-issue/HUMAN-GATE.md` still finds the regular file, 4782 B, on mbp (2026-11-09T01:31:28Z, exit 0) and on eleven-m5 (2026-11-09T01:31:49Z, exit 0). Codex-only entry surfaces are retired in the legacy cleanup (#687).

Item verdict: **retired**

### C9 — Host routes answer as declared

> Claude and Codex paths complete against declared host capabilities, including bounded capacity admission (issue 130 refresh); after the owner's 2026-11-08 decision only the Claude path must complete, and Codex must answer as declared

```text
C9.a workflow-state host-route --route claude-code
C9.b workflow-state host-route --route codex
```

| Host | Subject | Revision | Command | UTC | Exit | Observed | Verdict |
|------|---------|----------|---------|-----|------|----------|---------|
| mbp | host | system-324 | C9.a; C9.b | 2026-11-09T01:30:47Z | 0; 0 | claude-code supported, agent_slots 7; codex unsupported, declared_unsupported, alternative /from-issue <issue> --auto; admission passed on 5/5 roots | green |
| eleven-m5 | host | system-35 | C9.a; C9.b | 2026-11-09T01:31:29Z | 0; 0 | claude-code supported, agent_slots 7; codex unsupported, declared_unsupported, alternative /from-issue <issue> --auto; admission passed on 2/2 roots | green |
| anis-desktop | host | — | C1.c | 2026-11-09T01:30:03Z | 255 | unreachable (probed once) | human-pending |

Codex `unsupported` is the declared answer, not a red (D10). Admission is each C10 row's `host.admission.declaration`.

Earlier readings (2026-11-03 to 2026-11-08) and their re-read notes are in this file's history at origin/main 6e2f9dde45cb.

Item verdict: **human-pending**

### C10 — Doctor clean on every adopted host

> `doctor` is clean on every adopted host (issue 130)

```text
C10.a conformance run --purpose doctor --repo-root R
```

| Host | Subject | Revision | Command | UTC | Exit | Observed | Verdict |
|------|---------|----------|---------|-----|------|----------|---------|
| mbp | /Users/anis/Projects/arcwave | 2adb089868c5 dev 0 dirty | C10.a | 2026-11-09T01:30:52Z | 0 | doctor passed, 19/19; no warning checks; 0 suppressed or not_run; admission passed | green |
| mbp | /Users/anis/Projects/argus | 21338cae51ea main 1 dirty | C10.a | 2026-11-09T01:30:54Z | 0 | doctor passed, 19/19; no warning checks; 0 suppressed or not_run; admission passed | green |
| mbp | /Users/anis/tmp/nix-config | 6e2f9dde45cb main 0 dirty | C10.a | 2026-11-09T01:30:55Z | 0 | doctor passed, 19/19; no warning checks; 0 suppressed or not_run; admission passed | green |
| mbp | /Users/anis/Projects/jarbird | 75f28c1d98f3 dev 1 dirty | C10.a | 2026-11-09T01:30:58Z | 0 | doctor passed, 19/19; no warning checks; 0 suppressed or not_run; admission passed | green |
| mbp | /Users/anis/Projects/nodocom | 6eb54814447b dev 0 dirty | C10.a | 2026-11-09T01:31:01Z | 0 | doctor passed, 19/19; no warning checks; 0 suppressed or not_run; admission passed | green |
| eleven-m5 | /Users/anis/Projects/nix-config | 6e2f9dde45cb main 0 dirty | C10.a | 2026-11-09T01:31:30Z | 0 | doctor passed, 19/19; no warning checks; 0 suppressed or not_run; admission passed | green |
| eleven-m5 | /Users/anis/Projects/jarbird | 81c45be0afa7 main 0 dirty | C10.a | 2026-11-09T01:31:31Z | 0 | doctor passed, 19/19; no warning checks; 0 suppressed or not_run; admission passed | green |
| anis-desktop | host | — | C1.c | 2026-11-09T01:30:03Z | 255 | unreachable (probed once) | human-pending |

Earlier readings (2026-11-03 to 2026-11-08) and their re-read notes are in this file's history at origin/main 6e2f9dde45cb.

Item verdict: **human-pending** (every reachable row is green; anis-desktop was unreachable)

### C11 — Deprecations shipped, zero users

> Deprecation notices shipped in the bridge minor; removal happens only here, in the major, and only after zero fleet users of the deprecated paths. (issue 130 refresh)

```text
C11.a resolve-project platform-status
C11.r home/common/verify-pending/checks/deprecations-retired --repo-root R ...
```

C11.r (issue 582) states this item's per-root rule in one read-only command. Reading (a) is no `project.deprecated_uses`. Reading (b) is no tracked `.claude/skills.config.json`. Reading (c) is `resolve-project resolve` exiting 0 with `bindings.deploy.adapter` `none`. Reading (d) is no `release deploy inspect` outside `.agents/artifacts`, and for fagenorn/nix-config the pathspec is `home/common/agent-skills/skills`. It ran from origin/main 6e2f9dde45cb on each host.

| Host | Subject | Revision | Command | UTC | Exit | Observed | Verdict |
|------|---------|----------|---------|-----|------|----------|---------|
| mbp | host | system-324 | C11.a | 2026-11-09T01:30:47Z | 0 | platform 1.2.0; 5 deprecations (legacy-skills-config, legacy-skills-config-writer, bindings-deploy, release-deploy-inspect, release-bridge-planning) | green |
| eleven-m5 | host | system-35 | C11.a | 2026-11-09T01:31:29Z | 0 | platform 1.2.0; the same 5 deprecations | green |
| anis-desktop | host | — | C1.c | 2026-11-09T01:30:03Z | 255 | unreachable (probed once) | human-pending |
| mbp | /Users/anis/Projects/arcwave | 2adb089868c5 dev 0 dirty | C11.r | 2026-11-09T01:31:13Z | 1 | a red: deprecated_uses ["bindings-deploy"]; b, c (adapter none), d green | red |
| mbp | /Users/anis/Projects/argus | 21338cae51ea main 1 dirty | C11.r | 2026-11-09T01:31:13Z | 1 | a red: deprecated_uses ["bindings-deploy"]; b, c (adapter none), d green | red |
| mbp | /Users/anis/tmp/nix-config | 6e2f9dde45cb main 0 dirty | C11.r | 2026-11-09T01:31:13Z | 1 | a red: deprecated_uses ["bindings-deploy"]; b, c (adapter none), d green | red |
| mbp | /Users/anis/Projects/jarbird | 75f28c1d98f3 dev 1 dirty | C11.r | 2026-11-09T01:31:13Z | 1 | a red: deprecated_uses ["bindings-deploy"]; b, c (adapter none), d green | red |
| mbp | /Users/anis/Projects/nodocom | 6eb54814447b dev 0 dirty | C11.r | 2026-11-09T01:31:13Z | 1 | a red: deprecated_uses ["bindings-deploy"]; b, c (adapter none), d green | red |
| eleven-m5 | /Users/anis/Projects/nix-config | 6e2f9dde45cb main 0 dirty | C11.r | 2026-11-09T01:31:33Z | 1 | a red: deprecated_uses ["bindings-deploy"]; b, c (adapter none), d green | red |
| eleven-m5 | /Users/anis/Projects/jarbird | 81c45be0afa7 main 0 dirty | C11.r | 2026-11-09T01:31:33Z | 1 | a red: deprecated_uses ["bindings-deploy"]; b, c (adapter none), d green | red |

The bridge minor shipped (#580), and the legacy skills config, the deploy adapters and the retired command have no users (#581, #582, #555). One deprecated use is left on every root: project schema 1 itself, the subject of the `bindings-deploy` deprecation. It clears when C4.b clears, through the schema-2 migration commits of #724.

Earlier readings (2026-11-03 to 2026-11-08) and their re-read notes are in this file's history at origin/main 6e2f9dde45cb.

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
| eleven-m5 | host | system-35 | C12.a; C12.b; C12.c; C12.d | 2026-11-09T01:31:28Z | 0; 0; 0; 0 | N=35; store paths equal; 9p2z21bpjmyajmhbxx90p3f995r76r4q-darwin-system-25.11.ebec37a; configurationRevision 6e2f9dde45cb | green |
| mbp | host | system-324 | C12.a; C12.b; C12.c; C12.d | 2026-11-09T01:30:47Z | 0; 0; 0; 0 | N=324; store paths equal; 75gdn69a3licfa821db48pybbak70z24-darwin-system-25.11.ebec37a; configurationRevision 3604bd389567 | green |
| anis-desktop | host | — | C1.c | 2026-11-09T01:30:03Z | 255 | unreachable (probed once) | human-pending |

The two reachable hosts run different bridge builds. eleven-m5 is at 6e2f9dde45cb, and mbp is at 3604bd389567, an ancestor 27 commits behind it. Both are platform 1.2.0. Per D2 and #66 this is recorded and is not red. `N_H` is re-read at gate step 2.

Earlier readings (2026-11-03 to 2026-11-08) and their re-read notes are in this file's history at origin/main 6e2f9dde45cb.

Item verdict: **human-pending**

### P1–P6 — Post-activation items

These six items are `post` and `human-pending`: this attempt does not evaluate them, and the owner judges them at gate step 5 with the evidence in the spec's §3 post-activation table.

| ID | Predicate |
|----|-----------|
| P1 | No static fallback ladder remains in the resolver, conformance or workflow-entry paths of any adopted project, and a missing contract fails closed with a closed error code (AC2; #69) |
| P2 | The bridge generation is retained, and rollback to it is exercised once before retirement (AC3; refresh) |
| P3 | A Claude-driven ship completes on the strict path, against declared host capabilities with bounded admission (AC4; refresh; the Codex-driven ship was dropped by the owner's 2026-11-08 decision) |
| P4 | The #71 retirement predicates: the active generation's identity matches its manifest; active and bridge fleet conformance are green; `workflow_entry` passes through both adapters; post-activation smoke is green; doctor reports no residue; traces show zero removed-fallback executions (#71) |
| P5 | Implementation delivered, PR merged, tracker closed and cleanup postconditions reconciled before retirement (refresh) |
| P6 | Retirement is recorded with the evidence that satisfied each strict predicate (AC5) |

## Dispositions

Every row that is red at this refresh, and its route:

| Rows | Repair route | Disposition |
|------|--------------|-------------|
| C3 mbp and eleven-m5 origin/main .agents/artifacts/evidence/ | An `approved` Claude-only #70 bundle binding 953f9b4b2925, merged into origin/main | #725: Claude-only gate mode, trial corpus and paid trial; lands after the main freeze |
| C4.b mbp fleet; C4.b eleven-m5 fleet; C11 every root on mbp and eleven-m5 | Land each fleet project's `bindings-deploy.retire` schema-2 migration commit | #724 filed (blocks #130); the nix-config commit waits for the main freeze to lift |
| C7 mbp /Users/anis/Projects/jarbird | Reconcile the two kept JarBird worktrees (issue 487, issue 499) under the #585 procedure once their issues close or go quiet | #700; the issue 499 worktree belongs to a claim another session holds and was not touched |

Rows that are human-pending and their owner action: every anis-desktop row (owner: host online); C6 and C7 JarBird on mbp and eleven-m5 (gate step 1, run in the activation session).

Rows that were red at the 2026-11-03 to 2026-11-08 readings and read green now: C2 mbp /Users/anis/tmp/nix-config (#586), C2 and C10 mbp /Users/anis/Projects/nodocom (#583), C6 on the four refused-ledger roots (#584), C7 on arcwave, argus and nodocom (#585), C11 on the hosts' deprecation lists (#580), C11 readings b to d on every root (#581, #582, #555).

## Human gate

This section is the owner's activation and rollback procedure. This attempt does not run it. The owner runs every step, in order: steps 1 and 2 first, and step 3 onward only when step 2 reads every pre-activation verdict green. `K_H`, `N_H` and the roots below are the values the evidence observed. `<candidate>` is the one parameter: the 40-hex commit of the strict-cutover candidate (built under #579, rebuilt on origin/main 6e2f9dde45cb as 953f9b4b29253720e9868ab71b456b0ed3a62f63 at this refresh) that C3's approved bundle binds. Read it from the head of `origin/cutover-130-candidate` (`git ls-remote origin refs/heads/cutover-130-candidate`). A regenerated candidate is force-free: a new commit on that branch. `N_H` must be re-read in step 2, because any switch before the activation moves it: the observed values are eleven-m5 35 and mbp 324, and a different reading in step 2 replaces them in step 6.

Observed at evidence time (2026-11-09): eleven-m5 has `K_H` /Users/anis/Projects/nix-config and `N_H` 35. mbp has `K_H` /Users/anis/tmp/nix-config and `N_H` 324. The mbp switch at step 4 needs the owner's Touch ID; eleven-m5's sudo is passwordless. anis-desktop was unreachable at evidence time: read K_H and N_H for it in step 2.

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
workflow-state migrate --repo-root /Users/anis/Projects/nix-config           # must report "refused": 0
workflow-state migrate --repo-root /Users/anis/Projects/nix-config --apply
```

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
conformance run --purpose fleet --repo-root /Users/anis/Projects/nix-config
conformance run --purpose fleet --repo-root /Users/anis/Projects/jarbird
conformance run --purpose doctor --repo-root /Users/anis/Projects/nix-config
conformance run --purpose doctor --repo-root /Users/anis/Projects/jarbird
```

On anis-desktop, run the same fleet and doctor lines for each root in its registry.

### 6. Rollback

Per host, to the bridge generation, with `N_H` as step 2 read it (the observed values are shown). Rollback is also how P2 is exercised once before retirement. If activation failed on any host, roll back every host already activated.

```
# darwin hosts
sudo /nix/var/nix/profiles/system-35-link/sw/bin/darwin-rebuild --switch-generation 35    # eleven-m5
sudo /nix/var/nix/profiles/system-324-link/sw/bin/darwin-rebuild --switch-generation 324  # mbp
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
| AC1 | A committed cutover checklist cites registration for all three projects, an `approved` bundle for the cutover candidate, no in-flight legacy release or unresumable legacy attempt, a clean `doctor` on every host, and the Codex handoff — each with fresh evidence. (False at base: none of the inputs exist.) | C2, C3, C5, C6, C10 (C8 retired by the owner, 2026-11-08) | unmet |
| AC2 | After activation, no static fallback ladder remains in the resolver, conformance or workflow-entry paths of any adopted project; a missing contract fails closed with a closed error code everywhere. (False at base: the ladders are the current behaviour.) | P1 | human_pending |
| AC3 | The bridge generation is retained and rollback to it is exercised once before retirement is recorded. (False at base: no bridge exists.) | P2, C12 | human_pending |
| AC4 | Both a Claude-driven and a Codex-driven ship complete on the strict path after cutover. (False at base: the Codex path cannot complete a ship without manual intervention.) Narrowed by the owner on 2026-11-08 to a Claude-driven ship on the strict path. | P3 | human_pending |
| AC5 | Retirement is recorded with the evidence that satisfied each strict predicate. | P6 | human_pending |
| AC6 | The checklist derives the fleet roster from current registry truth and records the explicit Arcwave inclusion/exclusion decision. | C1 | human_pending |
| AC7 | There are zero active legacy attempts and zero retained legacy worktrees that cannot resume on a declared path. | C6, C7 | unmet |
| AC8 | Rollback to the retained bridge generation is exercised before retirement. | P2 | human_pending |
| AC9 | Claude and Codex paths complete against declared host capabilities, including bounded capacity admission. Narrowed by the owner on 2026-11-08 to a Claude-driven ship; Codex answers its declared `unsupported`. | C9, P3 | human_pending |
| AC10 | Implementation delivered, PR merged, tracker closed, and cleanup postconditions are reconciled before bridge retirement. | P5 | human_pending |
