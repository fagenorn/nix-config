# Stage-4 cutover checklist — issue 130

Purpose: pre-activation predicates for the issue 130 strict cutover with fresh read-only evidence, red-row dispositions and the owner's gate; preparation only, per spec D1 and the owner's 2026-11-08 overnight decision.
Run: rel_01a1a1d8-7220-72a2-841e-df2806f78396; refreshed by the issue 130 overnight preparation, 2026-11-09. The issue 130 activation preparation re-read rows on the morning of 2026-11-09: every anis-desktop row, eleven-m5 C4, C6, C7 and C11, and mbp C6 and C7. It also took mbp C4 and C11 from #724's close. After #733 switched anis-desktop to the bridge, moved its nodocom root onto dev and ran gate step 1 there, every anis-desktop row was re-read (2026-11-09T08:39:12Z to 08:39:23Z). Gate step 1 then ran on the mbp JarBird root, and its C6 and C7 rows were re-read (2026-11-09T08:44:49Z to 08:48:25Z). After the owner waived C3 on evidence, the activation pass re-read C1, C2, C4, C6, C7, C11 and C12 on all three hosts (2026-11-09T16:26:38Z to 16:30:52Z).
Revisions: overnight rows read origin/main 6e2f9dde45cb76f363813801fb3b3b42b430545d. The morning rows read origin/main 76a3470a347dbbbb3332e22e7d49b877574adb0c on eleven-m5 and anis-desktop; anis-desktop ran that revision's checks exported to /tmp/c130-main-76a3470a. mbp C7 read e1d4db56718b9c4cdc330888de41fbed6d8a4c10, which is PR 723's merge and is now origin/main. The #733 re-read of anis-desktop ran from its K_H checkout, fast-forwarded to e1d4db56718b, and from the system-79 helpers built from that revision. The freeze is lifted. The activation pass read origin/main 474ae2ddd02c507b51e099ab6c9dd9e2798ce080 (PR 755's merge): each host ran that revision's `python`, checks and manifest exported to `/tmp/c130-main-474ae2dd` (on mbp, a scratch export), and C1.a ran in this branch's worktree with that revision merged in. The candidate, origin/cutover-130-candidate, is 06fb38b718e050742e607b9b0feefd873e90c404 (H2): 953f9b4b2925 merged origin/main e1d4db56 as 6543ed0b37c9, then b699d0afcbcf as 06fb38b718e0, both force-free.
Hosts: eleven-m5, mbp, anis-desktop
Evidence window: 2026-11-09T01:30:03Z to 2026-11-09T01:43:58Z (overnight); 2026-11-09T05:28:06Z to 2026-11-09T05:28:13Z (mbp C4 and C11, #724); 2026-11-09T08:21:54Z to 2026-11-09T08:30:42Z (this morning's pass); 2026-11-09T08:39:12Z to 2026-11-09T08:39:23Z (anis-desktop after #733); 2026-11-09T08:44:49Z to 2026-11-09T08:48:25Z (mbp JarBird gate step 1); 2026-11-09T16:26:38Z to 2026-11-09T16:30:52Z (activation pass)
Activation readiness: activation not permitted. Of the 11 pre-activation items, 1 is red (C7, one unmapped anis-desktop nodocom worktree of a live session), 0 are human-pending and 10 are green. C3 is green by the owner's waiver. C5, C9 and C10 were not re-read on the activation pass. C8 is retired and not counted.

Owner decisions applied (issue 130, 2026-11-08T13:20:31Z): C8 (the Codex ship handoff) is no longer a cutover predicate. C3's live trials are Claude-only. AC4 and AC9 (P3) need a Claude-driven ship on the strict path only. Owner decision (issue 130, 2026-11-09, https://github.com/fagenorn/nix-config/issues/130#issuecomment-6745240816): C3 is waived on evidence; the recorded Claude-only trial evidence replaces an approved bundle for this cutover.

## Summary

| ID | Predicate | Source | Phase | Verdict | Disposition |
|----|-----------|--------|-------|---------|-------------|
| C1 | The roster is derived from current registry truth, with the Arcwave decision recorded | refresh | pre | green | — |
| C2 | Every roster project is registered and compatible, and its adoption evidence is still current | issue; #71 | pre | green | — |
| C3 | A fresh `approved` #70 bundle covers the strict-cutover candidate as a whole | issue; #71; #128 AC5 | pre | green | waived on evidence by the owner (issue 130 comment 6745240816) |
| C4 | Candidate and retained-bridge fleet preflight are green for every registered project | #71 | pre | green | — |
| C5 | No legacy release is in flight | #90 | pre | green | — |
| C6 | No legacy attempt is left without a resumable strict-path mapping | issue; refresh | pre | green | — |
| C7 | No retained legacy worktree is left without a resumable mapping | refresh | pre | red | anis-desktop nodocom `issue-2632-cloak-156`, a live session's worktree: re-read at gate step 2 |
| C8 | The Codex ship handoff is in place | issue; #119 | — | retired | owner decision 2026-11-08: not a cutover predicate |
| C9 | The Claude path answers as its declared host capabilities say, including bounded admission; Codex answers its declared `unsupported` | refresh | pre | green | — |
| C10 | `doctor` is clean on every adopted host | issue | pre | green | — |
| C11 | Deprecation notices shipped in a bridge minor, and the fleet has zero users of the deprecated paths | issue; #66 | pre | green | — |
| C12 | The bridge generation is identified per host and can be retained | issue; #66 | pre | green | — |
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

Writes the 2026-11-09 morning pass made, all recoverable:
- eleven-m5 (#730): the clean JarBird checkout `/Users/anis/Projects/jarbird` was fast-forwarded on main with `git merge --ff-only` at 2026-11-09T08:21:45Z, from 81c45be0afa7 to 72e0c6d99053. That is origin/main after the JarBird v0.19.0 release, which carries the schema-2 migration e613ccc36494 (jarbird PR 545).
- eleven-m5 (#732): gate step 1 ran on `/Users/anis/Projects/jarbird` under the bridge generation (system-35). The dry run read refused 0, migrate 5. Then `workflow-state migrate --apply` at 2026-11-09T08:23:13Z migrated all five schema-10 ledgers to schema 11, including rel_01a15a4e and rel_01a16079. The recoverable copy was taken first, at `~/.agents/state/worktree-archive/issue-732-20261109T082305Z/` on eleven-m5. It holds tarballs of `.superpowers/workflows` and `.superpowers/attempt-transactions`, a verified git bundle per worktree branch (eight in all), SHA256SUMS and the migrate reports. No worktree was removed.
- anis-desktop: the SSH endpoint `anis-desktop` (anis-desktop.mink-fort.ts.net, port 48521) is the Windows host's OpenSSH. The NixOS WSL distro was `Stopped`, and `wsl -d NixOS` started it at 2026-11-09T08:24:33Z; every anis-desktop reading ran through `ssh anis-desktop 'wsl -d NixOS -- …'`. `wsl --terminate NixOS` undoes the start.
- anis-desktop: origin/main 76a3470a's `python`, `home/common/verify-pending/checks` and the platform manifest were exported to `/tmp/c130-main-76a3470a` so the checks could run without moving the K_H checkout, which is at 8a0cf87e6980. As designed, C4.a and C4.b made object-only fetches into `/home/anis/tmp/nix-config`, which update no ref.

Writes #733 made on anis-desktop, all recoverable (inside `wsl -d NixOS`; the distro had stopped again and was started at 2026-11-09T08:35:30Z):
- K_H `/home/anis/tmp/nix-config` was fast-forwarded on main with `git merge --ff-only origin/main` at 2026-11-09T08:35:46Z, from 8a0cf87e6980 to e1d4db56718b. `just switch` ran headless from 08:35:56Z to 08:37:31Z and exited 0, moving the host from system-78 to system-79 (platform 1.2.0, the bridge, not the candidate). The log is `/home/anis/.agents/state/issue-733-switch-20261109T083556Z.log`. system-78 is kept.
- The clean nodocom root `/home/anis/Projects/nodocom` was moved at 2026-11-09T08:37:58Z from main 49147a1840b3 to a new local branch dev, tracking origin/dev, at 40abc7d326d0 (nodocom PR 2606's merge, the mbp root's revision). Main is untouched. Nothing was pushed or deployed, and the registry is unchanged, with no `branch_override`. `git checkout main` undoes it.
- Gate step 1 ran on the nodocom root: dry run at 08:38:20Z (migrate 15, refused 0), then `workflow-state migrate --apply` at 2026-11-09T08:38:39Z (migrated 15, refused 0, schema 11). The recoverable copy was taken first, at `/home/anis/.agents/state/worktree-archive/issue-733-20261109T083820Z/`. It holds `ledgers-workflows.tar.gz` (sha256 d1dbf8306176180b4d29c236d5b4e1535fc4be2e2a4d98878d825ad3e8b5d4b9), `attempt-transactions.tar.gz` (sha256 66d68ad17d036d96a724f0197be5c13d7b0018c4d6d2a724dd201ee4728bc35e), verified bundles of `worktree-issue-2206-orchestrated` and of main at 49147a18, SHA256SUMS, the migrate reports and every re-read. No ledger file had an mtime within 24 hours (the newest was 2026-10-27). No worktree was removed.

Writes the mbp JarBird gate step 1 made, all recoverable (mbp, under the bridge generation: system-325, platform 1.2.0; mbp moved from system-324 to system-325 at 2026-11-09T08:17:43Z, not by this run):
- The fenced snapshot `/Users/anis/Projects/jarbird/.superpowers/archive/pre-130-c6-20261109T084753Z.tar.gz` and the labels file `pre-130-c6-labels-20261109T084753Z.json` beside it were written at 2026-11-09T08:47:55Z, with the reports in `pre-130-c6-20261109T084753Z/`.
- `workflow-state migrate --repo-root /Users/anis/Projects/jarbird --apply` at 2026-11-09T08:48:11Z migrated 15 schema-10 ledgers to schema 11. Nothing was archived or deleted, and no worktree was removed. The JarBird checkout (9ffd88a5b454, dev) was not moved.

## Roster

### Hosts

| Host | Reachable | Generation | Store path | configurationRevision | platform_version | manifest_path | K_H | Registry sha256 before | Registry sha256 after |
|------|-----------|------------|------------|-----------------------|------------------|---------------|-----|------------------------|------------------------|
| eleven-m5 | yes | system-35 | /nix/store/9p2z21bpjmyajmhbxx90p3f995r76r4q-darwin-system-25.11.ebec37a | 6e2f9dde45cb | 1.2.0 | /nix/store/yl4yfaps8kndji4qdnpy73vqk2cpcqmk-hm_platformmanifest.json | /Users/anis/Projects/nix-config | 0e3643016a781e74c21eada5322e060b742ff87cc9b19214465b0caa61f404f5 (before the nix-config registration) | ea8e1d478c53b8851f7c8237cec0f65bb99360ff92e4e6c95da34ec28f565c94 (fagenorn/nix-config added) |
| mbp | yes | system-325 (system-324 at the overnight read) | /nix/store/1azs22xpikbb0sfz1nazll6gkj6yqjkc-darwin-system-25.11.ebec37a | 76a3470a347d | 1.2.0 | /nix/store/yl4yfaps8kndji4qdnpy73vqk2cpcqmk-hm_platformmanifest.json | /Users/anis/tmp/nix-config | 819bbd8487305b83cf5fcd987f559847a03f8d51d4df155f70b5e2fb30905e75 | 819bbd8487305b83cf5fcd987f559847a03f8d51d4df155f70b5e2fb30905e75 |
| anis-desktop | yes (2026-11-09T08:24:33Z; unreachable at the overnight probe, 01:30:03Z, exit 255) | system-79 (system-78 before #733) | /nix/store/acblffazm911qvms3rxpwp4bwyghf4m5-nixos-system-nixos-25.11.20260630.b6018f8 (system-78: c8lf9xw40habayww5cwl6kk7d7qw6g4a) | e1d4db56718b (8a0cf87e6980 before #733) | 1.2.0 (1.1.0 before #733) | /nix/store/yl4yfaps8kndji4qdnpy73vqk2cpcqmk-hm_platformmanifest.json | /home/anis/tmp/nix-config | 18ae16af683d645741539b3860316b446690ded9f7829c80cb3d1fc202dc6a70 | 18ae16af683d645741539b3860316b446690ded9f7829c80cb3d1fc202dc6a70 (2026-11-09T08:30:42Z) |

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
| anis-desktop | nodocom | /home/anis/Projects/nodocom | — | 49147a1840b302f19ed403f65b5d930973d24d19 (main) | 0 | 40abc7d326d0ee0d9d6732d9016e115d21d85f0e (dev, #733) |

Every registered project on every reachable host is in (D2). Arcwave is in, by the repository owner's 2026-11-03 comment on issue 130. fagenorn/nix-config on eleven-m5 is new to the roster since the last refresh: it was registered at 2026-11-09T01:00:50Z, as C1 and C2 expect. Arcwave's and Nodo's `branch_override` of `dev` (`default_contract_unresolved`) is the designed #363 registration path, recorded as a fact and not as a red item. anis-desktop was unreachable at the overnight probe. It was read on the morning pass, and its one registered project, nodocom, is in. It is never dropped from the roster.

Snapshot: the after-snapshot was taken at 2026-11-09T01:41:48Z on mbp and at 01:41:49Z on eleven-m5. mbp's registry is byte-identical to its before value. eleven-m5's registry differs only by the fagenorn/nix-config registration this refresh made. Six of the seven roots equal their before values, with the dirty counts the rows record. One root moved, and not because of this run: mbp JarBird went from `75f28c1d98f3` to `7837084d9845`. That is a fast-forward of 9 commits (`merge origin/dev` in its reflog at 2026-11-09T01:37:22Z, elevenyellow/jarbird PR #541) made by another session after the JarBird rows were read, so every JarBird row on mbp cites `75f28c1d98f3`.

Morning pass: anis-desktop's registry lists one project, nodocom. Its root is on main at 49147a1840b3, which is elevenyellow/nodocom origin/main from 2026-11-03, with no `branch_override`. fagenorn/nix-config at its K_H is not registered there, although it is registered on mbp and on eleven-m5. #733 carries that decision. Since the overnight snapshot, some roots moved by fast-forward, and no host was switched. #724 moved mbp arcwave to 60767b69f581, argus to 65451b89de55, nix-config to 76a3470a347d (now e1d4db56718b, PR 723) and nodocom to 40abc7d326d0. mbp JarBird is at 9ffd88a5b454 (dev, 1 dirty), moved by another session. eleven-m5 nix-config is at 76a3470a347d (#724), and eleven-m5 JarBird is at 72e0c6d99053 (#730). The morning rows cite the revision each one read. eleven-m5's registry still hashes to ea8e1d478c53 (2026-11-09T08:30:42Z).

After #733 (2026-11-09T08:39:12Z): anis-desktop's nodocom root is on dev at 40abc7d326d0, the same revision as the mbp root, with 0 dirty. The registry is unchanged at 18ae16af683d and still lists nodocom only, with no `branch_override`. fagenorn/nix-config at K_H is still not registered there. #733 left that decision open.

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
| mbp | flake.nix | 0425bc65090f (this branch, origin/main 474ae2ddd02c merged) | C1.a; C1.b | 2026-11-09T16:30:09Z | 0; 0 | darwin ["eleven-m5","mbp"]; nixos ["anis-desktop"] | green |
| eleven-m5 | host | system-35 | C1.c; C1.d | 2026-11-09T16:28:04Z | 0; 0 | hostname eleven-m5; 2 projects: fagenorn/nix-config, jarbird; registry sha256 ea8e1d478c53 | green |
| mbp | host | system-325 | C1.c; C1.d | 2026-11-09T16:26:38Z | 0; 0 | hostname mbp; 5 projects: arcwave, fagenorn/argus, fagenorn/nix-config, jarbird, nodocom; registry sha256 819bbd848730 | green |
| anis-desktop | host | system-79 | C1.c; C1.d | 2026-11-09T16:28:14Z | 0; 0 | hostname anis-desktop (inside `wsl -d NixOS`); 1 project: nodocom; registry sha256 18ae16af683d | green |

Earlier readings (2026-11-03 to 2026-11-08) and their re-read notes are in this file's history at origin/main 6e2f9dde45cb.

Item verdict: **green**

### C2 — Registered, compatible and adoption current

> every fleet project … is registered and compatible (issue 130); per-project adoption evidence current (#71)

```text
C2.a resolve-project platform-status --fleet
C2.b conformance run --purpose fleet --repo-root R
C2.c adopt-project verify --repo-root R
```

| Host | Subject | Revision | Command | UTC | Exit | Observed | Verdict |
|------|---------|----------|---------|-----|------|----------|---------|
| mbp | host | system-325 | C2.a | 2026-11-09T16:26:38Z | 0 | platform 1.2.0, project schemas [1, 2]; 5/5 fleet rows compatible, deprecated_uses and removed_uses [] on each | green |
| eleven-m5 | host | system-35 | C2.a | 2026-11-09T16:28:04Z | 0 | platform 1.2.0, project schemas [1, 2]; 2/2 fleet rows compatible, deprecated_uses and removed_uses [] on each | green |
| anis-desktop | host | system-79 | C2.a | 2026-11-09T16:28:14Z | 0 | platform 1.2.0, project schemas [1, 2]; 1/1 fleet rows compatible (nodocom), deprecated_uses and removed_uses [] | green |
| mbp | /Users/anis/Projects/arcwave | 60767b69f581 dev 0 dirty | C2.b; C2.c | 2026-11-09T16:26:39Z | 0; 0 | fleet passed, 13/13; verify adopted, blockers 0 | green |
| mbp | /Users/anis/Projects/argus | 65451b89de55 main 1 dirty | C2.b; C2.c | 2026-11-09T16:26:44Z | 0; 0 | fleet passed, 13/13; verify adopted, blockers 0 | green |
| mbp | /Users/anis/tmp/nix-config | e1d4db56718b main 0 dirty | C2.b; C2.c | 2026-11-09T16:26:45Z | 0; 0 | fleet passed, 13/13; verify adopted, blockers 0 | green |
| mbp | /Users/anis/Projects/jarbird | bb2a992290b3 dev 1 dirty | C2.b; C2.c | 2026-11-09T16:26:46Z | 0; 0 | fleet passed, 13/13; verify adopted, blockers 0 | green |
| mbp | /Users/anis/Projects/nodocom | 40abc7d326d0 dev 0 dirty | C2.b; C2.c | 2026-11-09T16:26:49Z | 0; 0 | fleet passed, 13/13; verify adopted, blockers 0 | green |
| eleven-m5 | /Users/anis/Projects/nix-config | 76a3470a347d main 0 dirty | C2.b; C2.c | 2026-11-09T16:28:04Z | 0; 0 | fleet passed, 13/13; verify adopted, blockers 0 | green |
| eleven-m5 | /Users/anis/Projects/jarbird | 72e0c6d99053 main 0 dirty | C2.b; C2.c | 2026-11-09T16:28:04Z | 0; 0 | fleet passed, 13/13; verify adopted, blockers 0 | green |
| anis-desktop | /home/anis/Projects/nodocom | 6f4f02777582 dev 0 dirty | C2.b; C2.c | 2026-11-09T16:28:14Z | 0; 0 | fleet passed, 13/13; verify adopted, blockers 0 | green |

Registration is the C2.a fleet row. `verify` reports `registered` false unless `--register` was given, and only the eleven-m5 nix-config registration above used it.

Earlier readings (2026-11-03 to 2026-11-08) and their re-read notes are in this file's history at origin/main 6e2f9dde45cb.

Item verdict: **green**

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
| mbp | origin/main .agents/artifacts/evidence/ against 06fb38b718e0 | 474ae2ddd02c | C3.c | 2026-11-09T16:32:37Z | 75 | 0 of 6 bundles approved; cutover-130-x10-bundle.json (PR 754, connector-confounded) and cutover-130-x10r-bundle.json (PR 755) unmeasured and bind 06fb38b718e0; cutover-130-bundle.json (PR 749) unmeasured, binds 6543ed0b37c9 | red |
| owner | issue 130 comment 6745240816 | — | waiver | 2026-11-09 | — | C3 waived on evidence: 184 paid Claude-only runs, 46.28 USD of the 60 USD cap; quality held in every run set; connector-free medians routine-issue -2.1%, cold-resolution -3.1%, fuzzy-design +7.2%, review-ship +18.4% | green |

Activation pass: C3.c reads 75, because no bundle is `approved`: the gate's per-pair straddle rule cannot decide at the measured run-to-run variation. The owner waived C3 on evidence (https://github.com/fagenorn/nix-config/issues/130#issuecomment-6745240816), citing the three cutover-130 bundles, so the item is green by that waiver and the check itself still reads red. The paragraphs below are the overnight record. The Claude-only live trial did not run at the overnight refresh, and that refresh produced no bundle for 953f9b4b2925. The current tools cannot produce an approved Claude-only bundle. `agent_gate_bundle` requires both strata (`STRATA = ("claude", "codex")`), so any case without a codex stratum is `STRATUM_MISSING` and the bundle is `unmeasured`. No trial corpus or runner exists yet. Because C3.c verifies bundles at origin/main, a gate change and a bundle can read green only after the main freeze lifts. This refresh took the reversible choice: it spent nothing on a protocol nobody had defined. #725 was filed (blocks #130) for the Claude-only gate mode, the trial corpus and the paid trial bound to the candidate. The owner's approval of the Claude-only paid trial (2026-11-08T23:04:09Z) stands for that issue.

The candidate 720c67e53867, which cutover-579-bundle.json binds, is superseded by 953f9b4b2925. That is a fast-forward of the branch: it merges origin/main 6e2f9dde45cb (commit 1a747e911a78), then retires the one deploy-binding gate that #582 pinned beside its railway activation unit, and exempts the #582 C11 zero-users detector in `verify_checks.py` from the ladder audit as detection, not a route (commit 953f9b4b2925).

Earlier readings (2026-11-03 to 2026-11-08) and their re-read notes are in this file's history at origin/main 6e2f9dde45cb.

Disposition: waived on evidence by the owner (issue 130 comment 6745240816).

Item verdict: **green** (owner waiver)

### C4 — Candidate and bridge fleet preflight

> candidate and retained-bridge fleet preflight green for every registered project (#71)

```text
C4.a PYTHONPATH=python python3 -m agent_tools.verify_checks cutover-manifest
C4.b home/common/verify-pending/checks/cutover-preflight
```

C4.a passes only when `origin/main`'s manifest has major 1 and declares a deprecation equal to every `removals` entry of `<candidate>`'s manifest. C4.b passes only on `verdict: green` on every reachable host, and it includes C4.a. The item takes its worst row. On the activation pass both commands ran from origin/main 474ae2ddd02c, exported, with `--repo-root K_H` (object-only fetches, no ref written), and `<candidate>` is 06fb38b718e0.

| Host | Subject | Revision | Command | UTC | Exit | Observed | Verdict |
|------|---------|----------|---------|-----|------|----------|---------|
| mbp | home/common/agent-skills/platform-manifest.json against 06fb38b718e0 | 474ae2ddd02c | C4.a | 2026-11-09T16:27:04Z | 0 | main_version 1.2.0; candidate_version 2.0.0; 5 removals, 0 undeclared; verdict green | green |
| mbp | fleet against 06fb38b718e0 | 474ae2ddd02c | C4.b | 2026-11-09T16:27:08Z | 0 | verdict green; bridge 1.2.0, candidate 2.0.0; 5/5 rows bridge_compatible and candidate_compatible, removed_uses [] | green |
| eleven-m5 | home/common/agent-skills/platform-manifest.json against 06fb38b718e0 | 474ae2ddd02c | C4.a | 2026-11-09T16:29:27Z | 0 | main_version 1.2.0; candidate_version 2.0.0; 5 removals, 0 undeclared; verdict green (over `ssh -A`; at 16:28:06Z a non-forwarding ssh exited 2: no identity for `git ls-remote`) | green |
| eleven-m5 | fleet against 06fb38b718e0 | 474ae2ddd02c | C4.b | 2026-11-09T16:29:33Z | 0 | verdict green; bridge 1.2.0, candidate 2.0.0; 2/2 rows (fagenorn/nix-config, jarbird) bridge_compatible and candidate_compatible, removed_uses [] | green |
| anis-desktop | home/common/agent-skills/platform-manifest.json against 06fb38b718e0 | 474ae2ddd02c | C4.a | 2026-11-09T16:28:25Z | 0 | main_version 1.2.0; candidate_version 2.0.0; 5 removals, 0 undeclared; verdict green | green |
| anis-desktop | fleet against 06fb38b718e0 | 474ae2ddd02c | C4.b | 2026-11-09T16:28:29Z | 0 | verdict green; bridge 1.2.0, candidate 2.0.0; 1/1 rows (nodocom) bridge_compatible and candidate_compatible, removed_uses [] | green |

#724 landed each fleet project's `bindings-deploy.retire` schema-2 migration, and #730 carried the eleven-m5 JarBird row through the JarBird v0.19.0 release. C4.b is green on mbp and on eleven-m5. On anis-desktop it read red at 08:27:29Z (exit 75, not_yet: bridge 1.1.0, nodocom on Nodo's 2026-11-03 main candidate_incompatible). #733 switched the host to the 1.2.0 bridge and moved the nodocom root onto dev, and it now reads green.

Earlier readings (2026-11-03 to 2026-11-08) and their re-read notes are in this file's history at origin/main 6e2f9dde45cb.

Item verdict: **green**

### C5 — No legacy release in flight

> no legacy release is in flight (#90)

```text
C5.a ls -la R/.superpowers/workflows/ship-release/state.json
C5.b release transaction status --repo-root R
```

| Host | Subject | Revision | Command | UTC | Exit | Observed | Verdict |
|------|---------|----------|---------|-----|------|----------|---------|
| anis-desktop | /home/anis/Projects/nodocom | 40abc7d326d0 dev 0 dirty | C5.a | 2026-11-09T08:39:21Z | 2 | absent (after #733) | green |
| mbp | /Users/anis/Projects/arcwave | 2adb089868c5 dev 0 dirty | C5.a | 2026-11-09T01:30:53Z | 2 | absent | green |
| mbp | /Users/anis/Projects/argus | 21338cae51ea main 1 dirty | C5.a | 2026-11-09T01:30:54Z | 2 | absent | green |
| mbp | /Users/anis/tmp/nix-config | 6e2f9dde45cb main 0 dirty | C5.a | 2026-11-09T01:30:56Z | 2 | absent | green |
| mbp | /Users/anis/Projects/jarbird | 75f28c1d98f3 dev 1 dirty | C5.a | 2026-11-09T01:31:00Z | 2 | absent | green |
| mbp | /Users/anis/Projects/nodocom | 6eb54814447b dev 0 dirty | C5.a | 2026-11-09T01:31:02Z | 2 | absent | green |
| eleven-m5 | /Users/anis/Projects/nix-config | 6e2f9dde45cb main 0 dirty | C5.a | 2026-11-09T01:31:31Z | 2 | absent | green |
| eleven-m5 | /Users/anis/Projects/jarbird | 81c45be0afa7 main 0 dirty | C5.a | 2026-11-09T01:31:32Z | 2 | absent | green |

No root holds a legacy `ship-release/state.json`, so C5.b did not run.

Earlier readings (2026-11-03 to 2026-11-08) and their re-read notes are in this file's history at origin/main 6e2f9dde45cb.

Item verdict: **green**

### C6 — Legacy ledgers have a strict-path mapping

> Do not activate while any legacy attempt or worktree lacks a resumable strict-path mapping (issue 130 refresh)

```text
C6.a workflow-state migrate --repo-root R
```

| Host | Subject | Revision | Command | UTC | Exit | Observed | Verdict |
|------|---------|----------|---------|-----|------|----------|---------|
| anis-desktop | /home/anis/Projects/nodocom | 6f4f02777582 dev 0 dirty | C6.a | 2026-11-09T16:28:15Z | 0 | current 15, migrate 0, migrated 0, refused 0 | green |
| mbp | /Users/anis/Projects/arcwave | 60767b69f581 dev 0 dirty | C6.a | 2026-11-09T16:26:43Z | 0 | current 11, migrate 0, migrated 0, refused 0 | green |
| mbp | /Users/anis/Projects/argus | 65451b89de55 main 1 dirty | C6.a | 2026-11-09T16:26:44Z | 0 | current 8, migrate 0, migrated 0, refused 0 | green |
| mbp | /Users/anis/tmp/nix-config | e1d4db56718b main 0 dirty | C6.a | 2026-11-09T16:26:45Z | 0 | current 123, migrate 0, migrated 0, refused 0 | green |
| mbp | /Users/anis/Projects/jarbird | bb2a992290b3 dev 1 dirty | C6.a | 2026-11-09T16:26:48Z | 0 | current 53, migrate 0, migrated 0, refused 0 | green |
| mbp | /Users/anis/Projects/nodocom | 40abc7d326d0 dev 0 dirty | C6.a | 2026-11-09T16:26:50Z | 0 | current 154, migrate 0, migrated 0, refused 0 | green |
| eleven-m5 | /Users/anis/Projects/nix-config | 76a3470a347d main 0 dirty | C6.a | 2026-11-09T16:28:04Z | 0 | current 0, migrate 0, migrated 0, refused 0 | green |
| eleven-m5 | /Users/anis/Projects/jarbird | 72e0c6d99053 main 0 dirty | C6.a | 2026-11-09T16:28:05Z | 0 | current 5, migrate 0, migrated 0, refused 0 | green |

Every row in the table is a `workflow-state migrate` dry run. No root refuses a ledger. On mbp, gate step 1 ran on JarBird at 2026-11-09T08:48:11Z, with the recoverable copy taken first: its 15 schema-10 ledgers (`migrate 15` at the 08:29:44Z read) are now schema 11, and its record is below. On eleven-m5, gate step 1 ran on JarBird at 2026-11-09T08:23:13Z under #732, with the recoverable copy taken first; its record is below. On anis-desktop, #733 first put the host on the bridge generation (system-79, platform 1.2.0). Gate step 1 then ran on nodocom at 2026-11-09T08:38:39Z, with the recoverable copy taken first; its record is below. Nothing held by another session was touched.

#### JarBird (mbp /Users/anis/Projects/jarbird) gate step 1 record

- Snapshot: /Users/anis/Projects/jarbird/.superpowers/archive/pre-130-c6-20261109T084753Z.tar.gz, sha256:11b5916fa86b3d79b6926a8fedf9e8f39ea5e0ad8bdc5930299035c624e3c0c4, taken_at 2026-11-09T08:47:55Z by `ledger-snapshot take` (fenced, exit 0), 2306 members over 53 ledgers; attempt-transactions was in it (the store exists). Its digest is also in `pre-130-c6-20261109T084753Z.tar.gz.sha256` beside it, and the dry-run, apply and re-read reports are in `pre-130-c6-20261109T084753Z/` with SHA256SUMS.
- Labels file: /Users/anis/Projects/jarbird/.superpowers/archive/pre-130-c6-labels-20261109T084753Z.json. Every one of the 15 ledgers is labelled `migrate`, with its issues and no re-delivery. No ledger was archived.
- Liveness proof: 2026-11-09T08:46:25Z to 08:48:03Z, no hit. Local: no file in the ledger or transaction store has an mtime within 24 hours; the newest file write was 2026-11-07T20:30:51Z. The `workflows` directory's own mtime, 2026-11-08T20:15:34Z, is the archiving of four ledgers into `archive/workflows` recorded in their `.archived.json` sidecars, not a ledger write. Forge: the 54 issues the 15 ledgers name (elevenyellow/jarbird) are all closed, with no in-progress label and no claim. The claims of holder mbp/mbp-20261108-launch-1 on jarbird#238 and jarbird#344 are not live: each has its `agent:end` marker (reason done) at 2026-11-09T05:56:48Z and 06:52:20Z. Neither issue is named by a migrating ledger; jarbird#344 is in the current ledger rel_01a1a244.
- Dry run at 2026-11-09T08:44:49Z: current 38, migrate 15, refused 0. Gate step 1 for this root (`--apply`): 2026-11-09T08:48:11Z, exit 0, current 38, migrated 15, refused 0, schema 11. The C6.a re-read: 2026-11-09T08:48:17Z, exit 0, current 53, migrate 0, migrated 0, refused 0.
- Restore: `ledger-snapshot restore --repo-root /Users/anis/Projects/jarbird --snapshot <tarball>`, dry run first, by the #584 procedure below. The bridge reads schema 11, so a rollback needs no restore.

| Ledger | Reason | Issues | Disposition | Liveness | Re-deliver |
|--------|--------|--------|-------------|----------|------------|
| rel_01a16b2f-e1dd-73ac-b6e2-281c1b4b52ea | schema 10 | 32 | migrated | local_quiet; forge_quiet | none |
| rel_01a16caa-16af-738e-ad02-cb67fdb5fcc9 | schema 10 | 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45 | migrated | local_quiet; forge_quiet | none |
| rel_01a177d2-1f58-70ad-8a17-a4c5de3d96d8 | schema 10 | 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 103, 104, 106, 107 | migrated | local_quiet; forge_quiet | none |
| rel_01a17dcd-7c02-7cb3-bae1-fdd5984894f8 | schema 10 | 61, 121, 122 | migrated | local_quiet; forge_quiet | none |
| rel_01a17f35-32c1-75b8-bbbf-a949ac2b966b | schema 10 | 61 | migrated | local_quiet; forge_quiet | none |
| rel_01a1871a-8450-7c38-a55f-3af717f7c53b | schema 10 | 147 | migrated | local_quiet; forge_quiet | none |
| rel_01a187a9-66fa-7308-a8c0-98dce0af8cd4 | schema 10 | 192 | migrated | local_quiet; forge_quiet | none |
| rel_01a18833-64f3-7f3c-a009-a4c0e3c1c39e | schema 10 | 193 | migrated | local_quiet; forge_quiet | none |
| rel_01a18900-d2d6-78bd-8b71-b0a1cf586ed5 | schema 10 | 194 | migrated | local_quiet; forge_quiet | none |
| rel_01a18a18-df6c-7684-84aa-acf29c3fbdd6 | schema 10 | 201 | migrated | local_quiet; forge_quiet | none |
| rel_01a18b5c-8db2-7cd0-8e31-827fe86bc2f0 | schema 10 | 202 | migrated | local_quiet; forge_quiet | none |
| rel_01a18ec4-f714-7b86-bfca-fe7c1890059b | schema 10 | 227, 228, 229, 230, 231, 232, 233, 234, 246, 247, 248, 249, 250, 251 | migrated | local_quiet; forge_quiet | none |
| rel_01a1934d-b3a6-7ffc-9722-3c39d7adf2b3 | schema 10 | 260 | migrated | local_quiet; forge_quiet | none |
| rel_01a19643-d51b-7cc1-9ae4-75f99a2297b3 | schema 10 | 260 | migrated | local_quiet; forge_quiet | none |
| rel_01a19c3a-1885-7ead-938b-f6c73b528695 | schema 10 | 312, 313 | migrated | local_quiet; forge_quiet | none |

#### #733 gate step 1 record (anis-desktop /home/anis/Projects/nodocom)

- Recoverable copy: `/home/anis/.agents/state/worktree-archive/issue-733-20261109T083820Z/` on anis-desktop.
  - `ledgers-workflows.tar.gz` (sha256 d1dbf8306176180b4d29c236d5b4e1535fc4be2e2a4d98878d825ad3e8b5d4b9) holds all of `.superpowers/workflows`, 65 members.
  - `attempt-transactions.tar.gz` (sha256 66d68ad17d036d96a724f0197be5c13d7b0018c4d6d2a724dd201ee4728bc35e) holds the transaction store, 774 members.
  - `bundles/` holds `git bundle verify`-checked bundles of `worktree-issue-2206-orchestrated` (a clean worktree) and of main at 49147a18.
  - The directory also has SHA256SUMS, the worktree list, the list of ignored files, `nodocom-branch.txt`, the migrate reports and the re-reads.
- Liveness: no file in the ledger or transaction store had an mtime within 24 hours. The newest write was 2026-10-27.
- Dry run at 08:38:20Z: refused 0, migrate 15. Then `--apply` at 2026-11-09T08:38:39Z: migrated 15, refused 0, schema 11, rel_01a1700c included. The dry run after it, at 08:38:40Z, read current 15, migrate 0, refused 0.
- Restore: extract both tarballs over `/home/anis/Projects/nodocom/.superpowers`. The bridge reads schema 11, so a rollback needs no restore.

#### #732 gate step 1 record (eleven-m5 /Users/anis/Projects/jarbird)

- Recoverable copy: `/Users/anis/.agents/state/worktree-archive/issue-732-20261109T082305Z/` on eleven-m5. `ledgers-workflows.tar.gz` (sha256 d44c5ec6e37b9f8f12b944fea3852348fbe486b994aeb42ae84ebac312cd70e3) holds all five ledgers. `attempt-transactions.tar.gz` (sha256 3bacc70529378fec6b438e7fd97ab97e1353bb67979100100630b3219e653a24) holds the transaction store. `bundles/` holds one `git bundle verify`-checked bundle per worktree branch: issue 26, 27, 28, 29, 31, 32, 32-2 and 33. The directory also has SHA256SUMS, the worktree list, the list of ignored files and the migrate reports from before, during and after.
- Liveness: no ledger file had an mtime within 24 hours. The newest write was 2026-10-23, and all eight worktrees were clean.
- Dry run: refused 0, migrate 5. Then `--apply` at 2026-11-09T08:23:13Z: migrated 5, refused 0, schema 11. The ledgers were rel_01a15a4e, rel_01a15a5a, rel_01a15d8e, rel_01a15fe4 and rel_01a16079.
- Restore: extract both tarballs over `/Users/anis/Projects/jarbird/.superpowers`. The bridge reads schema 11, so a rollback needs no restore.

Earlier readings (2026-11-03 to 2026-11-08) and their re-read notes are in this file's history at origin/main 6e2f9dde45cb.

#### #584 disposition (2026-11-08 record, unchanged)

Archive home: `R/.superpowers/archive/workflows/<ledger>`, with a sidecar `<ledger>.archived.json` in record schema ledger-archive-record/v1, which carries each ledger's disposition label (archived, abandoned or unresolved) and its re-delivery issues. Nothing was deleted. Every snapshot was taken behind the D9 fence: ledger-snapshot take holds every ledger state.lock, every workflows dot-lock and the transaction store locks, all non-blocking, and refuses busy or changed instead of waiting. All four takes exited 0.

Restore, only before this delivery's ship step starts: (1) run ledger-snapshot restore --repo-root R `--snapshot <tarball>` as a dry run, read moved, restored and newer, and stop if any newer path lies outside the ledgers this run archived or migrated, archive/workflows or attempt-transactions, or if another session ran workflow-state on R since the snapshot; (2) run the same command with --apply, which moves the live workflows, attempt-transactions and archive/workflows aside into a new `pre-584-<UTC>.restore-<UTC>` directory under R/.superpowers/archive and then extracts the snapshot (a store absent at snapshot time stays absent; busy means a writer is active, so stop); (3) check that workflow-state migrate --repo-root R reports the pre-change counts. After ship, restore one ledger at a time by the ledger-archive README procedure (mv the archived directory back, then move its record aside).

Pre-change readings (workflow-state migrate --repo-root R, dry run): Arcwave current 0, migrate 11, refused 4; Argus current 0, migrate 8, refused 3; nix-config current 15, migrate 108, refused 6; Nodo current 8, migrate 146, refused 49. JarBird on mbp was outside this delivery; its gate step 1 ran on 2026-11-09 and is recorded above.

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

Item verdict: **green** (every root, mbp JarBird after its gate step 1 and anis-desktop nodocom after #733)

### C7 — Retained worktrees have a strict-path mapping

> Do not activate while any legacy attempt or worktree lacks a resumable strict-path mapping (issue 130 refresh)

```text
C7.r home/common/verify-pending/checks/worktree-mapping --repo-root R ...
```

C7.r (issue 585, with the forge class of #710) states this item's rule in one read-only command. A worktree is `current` when a current ledger names it. It is `migrate` when only ledgers that still need migration name it, and `refused-only` when only refused ones do. It is `forge` when no ledger names it but an open in-progress claim, an open same-repository pull request or the declared `cutover-130-candidate` branch maps its branch. Otherwise it is `unmapped`. A root is red on any `unmapped` or `refused-only` path and human-pending on `migrate`. It ran from origin/main 6e2f9dde45cb on each host, 2026-11-09T01:43:45Z on mbp, after this run's own scratch worktree was removed and the evidence branch's pull request was opened.

| Host | Subject | Revision | Command | UTC | Exit | Observed | Verdict |
|------|---------|----------|---------|-----|------|----------|---------|
| anis-desktop | /home/anis/Projects/nodocom | 6f4f02777582 dev 0 dirty | C7.r | 2026-11-09T16:30:52Z | 1 | worktrees 11: current 1, forge 9, migrate 0, refused-only 0, unmapped 1: `.worktrees/issue-2632-cloak-156` (branch issue-2632-cloak-156 at 1993673e4b50, clean, no PR); also red at 16:28:15Z | red |
| mbp | /Users/anis/Projects/arcwave | 60767b69f581 dev 0 dirty | C7.r | 2026-11-09T16:29:46Z | 0 | worktrees 10: current 10, unmapped 0 | green |
| mbp | /Users/anis/Projects/argus | 65451b89de55 main 1 dirty | C7.r | 2026-11-09T16:29:46Z | 0 | worktrees 8: current 8, unmapped 0 | green |
| mbp | /Users/anis/tmp/nix-config | e1d4db56718b main 0 dirty | C7.r | 2026-11-09T16:29:46Z | 0 | worktrees 11: current 6, forge 5 (`cutover-130-candidate` declared; open PRs of issues 130, 688, 734, 735), unmapped 0; red at 16:26:51Z on the closed #750's worktree, removed between the reads | green |
| mbp | /Users/anis/Projects/jarbird | bb2a992290b3 dev 1 dirty | C7.r | 2026-11-09T16:29:46Z | 0 | worktrees 19: current 15, forge 4 (other sessions' claims), unmapped 0 | green |
| mbp | /Users/anis/Projects/nodocom | 40abc7d326d0 dev 0 dirty | C7.r | 2026-11-09T16:29:46Z | 0 | worktrees 5: current 5, unmapped 0 | green |
| eleven-m5 | /Users/anis/Projects/nix-config | 76a3470a347d main 0 dirty | C7.r | 2026-11-09T16:28:05Z | 0 | worktrees 0 | green |
| eleven-m5 | /Users/anis/Projects/jarbird | 72e0c6d99053 main 0 dirty | C7.r | 2026-11-09T16:28:05Z | 0 | worktrees 8: current 8, unmapped 0 | green |

Activation pass (2026-11-09, from origin/main 474ae2ddd02c, exported): on mbp the first read (16:26:51Z) was red on one unmapped worktree, `/Users/anis/tmp/nix-config/.worktrees/worktree-issue-750-deliver-direct-eval-all-rejection-test`. #750 was closed, the worktree was clean and detached at b699d0afcbcf, which is in origin/main (PR 751), and nothing held it open, so it was removed with `git worktree remove` (not forced); the re-read at 16:29:46Z is green. On anis-desktop, `issue-2632-cloak-156` is a side worktree of the live session that claims elevenyellow/nodocom#2632 (holder anis-desktop/session-4e949033), committed at 2026-11-09T14:24:19Z. It is not this run's to remove, so the row stays red until that session maps it (a PR) or removes it; gate step 2 re-reads it. Morning pass (2026-11-09): mbp read from origin/main e1d4db56718b and eleven-m5 from 76a3470a347d. anis-desktop read from 76a3470a's checks, exported. On mbp, #700 settled the issue 487 and issue 499 JarBird worktrees: they are gone, and every root is green, as at #700's 05:40:33Z re-read. After mbp JarBird's gate step 1, its C7.r re-read at 08:48:25Z from e1d4db56718b is green: one more worktree than at 08:29:31Z, the issue 553 worktree, mapped by another session's claim, and none was removed. On eleven-m5, gate step 1 (#732) made the eight JarBird worktrees `current`, and none was removed. On anis-desktop, the one nodocom worktree read `migrate` at 08:27:34Z. After gate step 1 (#733), it reads `current` from K_H at e1d4db56718b, and none was removed. fagenorn/nix-config is still not registered on anis-desktop, so its K_H worktrees (`worktree-issue-468-orchestrated` and `/tmp/launch-scope-td48wcrk/trial`) are outside this reading. #733 closed with that registration decision left open.

The overnight note follows. Exit is the check's exit over all of that host's roots: 1 when a root is red and 75 when the worst root is human-pending. On mbp, JarBird's two unmapped worktrees are the issue 487 and issue 499 worktrees that #585 kept for `operator` and that #700 tracks. jarbird#499 is held by another session, so its worktree was not touched. The four JarBird `forge` paths are live claims of another session. On nix-config, `cutover-130-candidate` is the declared candidate branch, the issue 687 worktree has an open claim and PR #723, and this refresh's evidence worktree (`prep-130-main-baseline`, branch `issue-130-overnight-checklist-refresh`) is mapped by its open pull request. The closed issue 705's worktree, unmapped at the 01:31:03Z read, was removed as recorded under the summary. eleven-m5's JarBird worktrees read `migrate` (they read `current` on 2026-11-03), because their schema-10 ledgers migrate at gate step 1.

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
| anis-desktop | host | system-79 | C9.a; C9.b | 2026-11-09T08:39:21Z | 0; 0 | claude-code supported, agent_slots 7; codex unsupported, declared_unsupported, alternative /from-issue <issue> --auto; admission passed on 1/1 roots | green |

Codex `unsupported` is the declared answer, not a red (D10). Admission is each C10 row's `host.admission.declaration`.

Earlier readings (2026-11-03 to 2026-11-08) and their re-read notes are in this file's history at origin/main 6e2f9dde45cb.

Item verdict: **green**

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
| anis-desktop | /home/anis/Projects/nodocom | 40abc7d326d0 dev 0 dirty | C10.a | 2026-11-09T08:39:21Z | 0 | doctor passed, 19/19; no warning checks; 0 suppressed or not_run; admission passed (after #733; at 08:26:08Z on main 49147a1840b3 it failed 18/19 on repository.ignore.runtime_sentinel) | green |

Earlier readings (2026-11-03 to 2026-11-08) and their re-read notes are in this file's history at origin/main 6e2f9dde45cb.

Item verdict: **green**

### C11 — Deprecations shipped, zero users

> Deprecation notices shipped in the bridge minor; removal happens only here, in the major, and only after zero fleet users of the deprecated paths. (issue 130 refresh)

```text
C11.a resolve-project platform-status
C11.r home/common/verify-pending/checks/deprecations-retired --repo-root R ...
```

C11.r (issue 582) states this item's per-root rule in one read-only command. Reading (a) is no `project.deprecated_uses`. Reading (b) is no tracked `.claude/skills.config.json`. Reading (c) is `resolve-project resolve` exiting 0 with `bindings.deploy.adapter` `none`. Reading (d) is no `release deploy inspect` outside `.agents/artifacts`; for `fagenorn/nix-config` its pathspec is `home/common/agent-skills/skills`. On the activation pass it ran from origin/main 474ae2ddd02c, exported, on each host.

| Host | Subject | Revision | Command | UTC | Exit | Observed | Verdict |
|------|---------|----------|---------|-----|------|----------|---------|
| mbp | host | system-325 | C11.a | 2026-11-09T16:26:39Z | 0 | platform 1.2.0; 5 deprecations (legacy-skills-config, legacy-skills-config-writer, bindings-deploy, release-deploy-inspect, release-bridge-planning) | green |
| eleven-m5 | host | system-35 | C11.a | 2026-11-09T16:28:04Z | 0 | platform 1.2.0; the same 5 deprecations | green |
| anis-desktop | host | system-79 | C11.a | 2026-11-09T16:28:14Z | 0 | platform 1.2.0; the same 5 deprecations | green |
| mbp | /Users/anis/Projects/arcwave | 60767b69f581 dev 0 dirty | C11.r | 2026-11-09T16:27:03Z | 0 | a, b, c (adapter none), d green; one run over all 5 roots, met true | green |
| mbp | /Users/anis/Projects/argus | 65451b89de55 main 1 dirty | C11.r | 2026-11-09T16:27:03Z | 0 | a, b, c (adapter none), d green | green |
| mbp | /Users/anis/tmp/nix-config | e1d4db56718b main 0 dirty | C11.r | 2026-11-09T16:27:03Z | 0 | a, b, c (adapter none), d green | green |
| mbp | /Users/anis/Projects/jarbird | bb2a992290b3 dev 1 dirty | C11.r | 2026-11-09T16:27:03Z | 0 | a, b, c (adapter none), d green | green |
| mbp | /Users/anis/Projects/nodocom | 40abc7d326d0 dev 0 dirty | C11.r | 2026-11-09T16:27:03Z | 0 | a, b, c (adapter none), d green | green |
| eleven-m5 | /Users/anis/Projects/nix-config | 76a3470a347d main 0 dirty | C11.r | 2026-11-09T16:28:05Z | 0 | a, b, c (adapter none), d green; met true over both roots | green |
| eleven-m5 | /Users/anis/Projects/jarbird | 72e0c6d99053 main 0 dirty | C11.r | 2026-11-09T16:28:05Z | 0 | a, b, c (adapter none), d green | green |
| anis-desktop | /home/anis/Projects/nodocom | 6f4f02777582 dev 0 dirty | C11.r | 2026-11-09T16:28:24Z | 0 | a, b, c (adapter none), d green; met true | green |

The bridge minor shipped (#580), and the legacy skills config, the deploy adapters and the retired command have no users (#581, #582, #555). #724 and #730 cleared the deprecated use of project schema 1 on every mbp and eleven-m5 root. On anis-desktop, #733 switched the host to platform 1.2.0, which ships the bridge minor's notices, and moved the nodocom root onto Nodo's dev, which carries #582, #583 and the schema-2 migration. Every anis-desktop row now reads green.

Earlier readings (2026-11-03 to 2026-11-08) and their re-read notes are in this file's history at origin/main 6e2f9dde45cb.

Item verdict: **green**

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
| eleven-m5 | host | system-35 | C12.a; C12.b; C12.c; C12.d | 2026-11-09T16:28:04Z | 0; 0; 0; 0 | N=35; store paths equal; 9p2z21bpjmyajmhbxx90p3f995r76r4q-darwin-system-25.11.ebec37a; configurationRevision 6e2f9dde45cb | green |
| mbp | host | system-325 | C12.a; C12.b; C12.c; C12.d | 2026-11-09T16:26:38Z | 0; 0; 0; 0 | N=325; store paths equal; 1azs22xpikbb0sfz1nazll6gkj6yqjkc-darwin-system-25.11.ebec37a; configurationRevision 76a3470a347d | green |
| anis-desktop | host | system-79 | C12.a; C12.b; C12.c; C12.d | 2026-11-09T16:28:14Z | 0; 0; 0; 0 | N=79; store paths equal; acblffazm911qvms3rxpwp4bwyghf4m5-nixos-system-nixos-25.11.20260630.b6018f8; configurationRevision e1d4db56718b; platform 1.2.0 | green |

The three hosts run different bridge builds. eleven-m5 is at 6e2f9dde45cb, mbp at 76a3470a347d (system-325, switched at 2026-11-09T08:17:43Z, not by this run) and anis-desktop at e1d4db56718b (#733). All three are platform 1.2.0, with the same manifest store path. Per D2 and #66, a difference between bridge builds is recorded and is not red. `N_H` is re-read at gate step 2.

Earlier readings (2026-11-03 to 2026-11-08) and their re-read notes are in this file's history at origin/main 6e2f9dde45cb.

Item verdict: **green**

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
| C7 anis-desktop /home/anis/Projects/nodocom | The live session that claims elevenyellow/nodocom#2632 maps (opens a PR) or removes its side worktree `issue-2632-cloak-156`; not this run's to touch | re-read at gate step 2 |

Rows that are human-pending and their action: none. C3 is green by the owner's waiver (issue 130 comment 6745240816), not by a bundle.

Rows that were red or human-pending at the overnight refresh and read green now: C4.b and C11 on mbp (#724); C4.b, C11, C6 and C7 eleven-m5 JarBird (#730, #732); C7 mbp JarBird (#700); C6 mbp JarBird (gate step 1, 2026-11-09T08:48:11Z); C1, C2.a, C4.a, C5 and C9 on anis-desktop (first reading); C2.b, C4.b, C6, C7, C10, C11 and C12 on anis-desktop (#733, closed 2026-11-09T08:40:16Z: host switched to the bridge as system-79, nodocom root moved to dev 40abc7d326d0, gate step 1 run).

Rows that were red at the 2026-11-03 to 2026-11-08 readings and read green now: C2 mbp /Users/anis/tmp/nix-config (#586), C2 and C10 mbp /Users/anis/Projects/nodocom (#583), C6 on the four refused-ledger roots (#584), C7 on arcwave, argus and nodocom (#585), C11 on the hosts' deprecation lists (#580), C11 readings b to d on every root (#581, #582, #555).

## Human gate

This section is the owner's activation and rollback procedure. This attempt does not run it. The owner runs every step, in order: steps 1 and 2 first, and step 3 onward only when step 2 reads every pre-activation verdict green. `K_H`, `N_H` and the roots below are the values the evidence observed. `<candidate>` is the one parameter: the 40-hex commit of the strict-cutover candidate (built under #579; at the activation pass 06fb38b718e050742e607b9b0feefd873e90c404, which merges origin/main b699d0afcbcf). C3 is satisfied by the owner's waiver on evidence (issue 130 comment 6745240816), not by an approved bundle. Read it from the head of `origin/cutover-130-candidate` (`git ls-remote origin refs/heads/cutover-130-candidate`). A regenerated candidate is force-free: a new commit on that branch. `N_H` must be re-read in step 2, because any switch before the activation moves it: the observed values are eleven-m5 35, mbp 325 and anis-desktop 79, and a different reading in step 2 replaces them in step 6.

Observed at evidence time (2026-11-09): eleven-m5 has `K_H` /Users/anis/Projects/nix-config and `N_H` 35. mbp has `K_H` /Users/anis/tmp/nix-config and `N_H` 325. The mbp switch at step 4 needs the owner's Touch ID; eleven-m5's sudo is passwordless. anis-desktop has `K_H` /home/anis/tmp/nix-config and `N_H` 79, the bridge build #733 switched it to (generation 78 was a platform 1.1.0 build). Every anis-desktop command runs inside the NixOS WSL distro (`ssh anis-desktop` reaches the Windows host; then `wsl -d NixOS -- …`), and its sudo is passwordless.

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

On anis-desktop, read its registry first (`cat ~/.agents/state/fleet/registry.json`) and run the same pair of lines for each root in it. At evidence time its one root, /home/anis/Projects/nodocom, has already run this step (#733, 2026-11-09T08:38:39Z), and a repeat dry run must read migrate 0, refused 0.

### 2. Re-run the checklist

On every host, re-run every pre-activation item's commands. Every verdict must be green. Any changed or red verdict rewinds the stage (#71): the candidate is regenerated, never patched around. Record `N_H` from `readlink /nix/var/nix/profiles/system`.

### 3. Freeze

From step 2 until retirement is recorded, on every host, run no `just gc`, no `nix-collect-garbage`, no system-generation deletion and no `just switch` other than step 4's.

### 4. Activation

Every host in one session, host by host. `<candidate>` must be the head of origin/cutover-130-candidate that the activation pass and step 2 read. `just switch` is the contract's `nix-activate` command, run from the candidate checkout's root. The new system generation roots the build, so the worktree is removed and leaves no residue for C7. If any host fails to activate, roll back every host already activated, because #71 forbids a mixed live fleet.

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

On anis-desktop, inside `wsl -d NixOS`:

```
(
  set -e
  git -C /home/anis/tmp/nix-config fetch origin
  git -C /home/anis/tmp/nix-config worktree add --detach /home/anis/tmp/nix-config/.worktrees/cutover-130 <candidate>
  test "$(git -C /home/anis/tmp/nix-config/.worktrees/cutover-130 rev-parse HEAD)" = <candidate>
  ( cd /home/anis/tmp/nix-config/.worktrees/cutover-130 && just switch )
  git -C /home/anis/tmp/nix-config worktree remove /home/anis/tmp/nix-config/.worktrees/cutover-130
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
sudo /nix/var/nix/profiles/system-325-link/sw/bin/darwin-rebuild --switch-generation 325  # mbp
```

anis-desktop is a NixOS host, so rollback is the following, with `N_H` as step 2 reads it (observed 79):

```
sudo nix-env --profile /nix/var/nix/profiles/system --switch-generation 79
sudo /nix/var/nix/profiles/system/bin/switch-to-configuration switch
```

After rollback, re-run C12 to show the bridge generation is running again.

When step 6 runs as P2's exercise, re-activation follows: under step 3's freeze, run step 4's host block again on every host at the same `<candidate>`, then repeat step 5's post-activation verification on every host. P4–P6 are evaluated, and retirement is recorded, only after that renewed step 5 is green. When step 6 runs because activation failed, the gate stops on the bridge generation.

## Criteria map

AC1 to AC5 are the issue's `## Acceptance criteria`, AC6 to AC10 its `### Additional acceptance criteria`. A criterion is `met` only when every mapped item is green, `human_pending` when the rest wait on the owner or the activation, and `unmet` otherwise.

| AC | Criterion | Items | Verdict |
|----|-----------|-------|---------|
| AC1 | A committed cutover checklist cites registration for all three projects, an `approved` bundle for the cutover candidate, no in-flight legacy release or unresumable legacy attempt, a clean `doctor` on every host, and the Codex handoff — each with fresh evidence. (False at base: none of the inputs exist.) | C2, C3, C5, C6, C10 (C8 retired by the owner, 2026-11-08); C3 by the owner's waiver, 2026-11-09 | met |
| AC2 | After activation, no static fallback ladder remains in the resolver, conformance or workflow-entry paths of any adopted project; a missing contract fails closed with a closed error code everywhere. (False at base: the ladders are the current behaviour.) | P1 | human_pending |
| AC3 | The bridge generation is retained and rollback to it is exercised once before retirement is recorded. (False at base: no bridge exists.) | P2, C12 | human_pending |
| AC4 | Both a Claude-driven and a Codex-driven ship complete on the strict path after cutover. (False at base: the Codex path cannot complete a ship without manual intervention.) Narrowed by the owner on 2026-11-08 to a Claude-driven ship on the strict path. | P3 | human_pending |
| AC5 | Retirement is recorded with the evidence that satisfied each strict predicate. | P6 | human_pending |
| AC6 | The checklist derives the fleet roster from current registry truth and records the explicit Arcwave inclusion/exclusion decision. | C1 | met |
| AC7 | There are zero active legacy attempts and zero retained legacy worktrees that cannot resume on a declared path. | C6, C7 | unmet |
| AC8 | Rollback to the retained bridge generation is exercised before retirement. | P2 | human_pending |
| AC9 | Claude and Codex paths complete against declared host capabilities, including bounded capacity admission. Narrowed by the owner on 2026-11-08 to a Claude-driven ship; Codex answers its declared `unsupported`. | C9, P3 | human_pending |
| AC10 | Implementation delivered, PR merged, tracker closed, and cleanup postconditions are reconciled before bridge retirement. | P5 | human_pending |
