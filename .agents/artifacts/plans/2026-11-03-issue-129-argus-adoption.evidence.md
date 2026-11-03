# Evidence — issue 129, Argus adoption

One section per task of the plan; raw outputs stay in the launch scratch (spec D18).

## Task 1 — Fresh baseline

Host `mbp`; started 2026-11-03T01:57:52Z, ended 2026-11-03T01:58:36Z; worktree HEAD `7d8ddfa16cb420fa99a85e2ecc14c5e931f88ca3`. Read-only measurement; no check failed to run.

### Workflow outcomes

| Run | Issue | Outcome | Blocked on | Merge SHA | Run updated |
|---|---|---|---|---|---|
| direct-100-000001 | 100 | stopped | — | — | 2026-09-04T10:52:23Z |
| direct-100-000002 | 100 | merged | — | 131a0e6ca606bd7fc2607f3812e37df5a531b495 | 2026-09-04T12:53:48Z |
| direct-101-000001 | 101 | stopped | — | — | 2026-09-04T16:28:05Z |
| direct-101-000002 | 101 | merged | — | dc7564b3c8bbd6a5633dfcff78f80291175047fd | 2026-09-04T21:08:25Z |
| direct-112-000001 | 112 | merged | — | 858136731d57a7cc25edddf002988c5a88745514 | 2026-09-04T22:22:28Z |
| direct-94-000001 | 94 | suspended | human_gate | — | 2026-09-09T09:24:08Z |
| issues-48-53 | 48 | stopped | — | — | 2026-08-17T08:44:45Z |
| issues-48-53 | 49 | stopped | — | — | 2026-08-17T08:44:45Z |
| issues-48-53 | 50 | stopped | — | — | 2026-08-17T08:44:45Z |
| issues-48-53 | 51 | stopped | — | — | 2026-08-17T08:44:45Z |
| issues-48-53 | 52 | stopped | — | — | 2026-08-17T08:44:45Z |
| issues-48-53 | 53 | stopped | — | — | 2026-08-17T08:44:45Z |
| issues-78-94 | 78 | stopped | — | — | 2026-08-22T10:09:56Z |
| issues-78-94 | 79 | stopped | — | — | 2026-08-22T10:09:56Z |
| issues-78-94 | 80 | stopped | — | — | 2026-08-22T10:09:56Z |
| issues-78-94 | 81 | stopped | — | — | 2026-08-22T10:09:56Z |
| issues-78-94 | 82 | stopped | — | — | 2026-08-22T10:09:56Z |
| issues-78-94 | 83 | active | — | — | 2026-08-22T10:09:56Z |
| issues-78-94 | 84 | active | — | — | 2026-08-22T10:09:56Z |
| issues-99-105 | 99 | stopped | — | — | 2026-08-23T19:40:59Z |
| issues-99-105 | 100 | stopped | — | — | 2026-08-23T19:40:59Z |
| issues-99-105 | 101 | stopped | — | — | 2026-08-23T19:40:59Z |
| issues-99-105 | 102 | suspended | human_gate | — | 2026-08-23T19:40:59Z |
| orch-78-94-20260821 | 78 | stopped | — | — | 2026-08-21T15:22:49Z |
| orch-78-94-20260821 | 79 | stopped | — | — | 2026-08-21T15:22:49Z |
| orch-78-94-20260821 | 80 | handed_off | — | — | 2026-08-21T15:22:49Z |
| orch-78-94-20260821 | 81 | handed_off | — | — | 2026-08-21T15:22:49Z |
| orchestrate-99-105 | 99 | stopped | — | — | 2026-08-21T11:11:13Z |

Header as specified is `| Run | Issue | Outcome | Blocked on | Merge SHA | Run updated |`; `—` is a null field. 28 rows: 3 issues with outcome `merged` (runs direct-100-000002, direct-101-000002, direct-112-000001), 25 with any other outcome.

### Argus PRs since 2026-08-01

| PR | State | Merged or closed at | Merged by |
|---|---|---|---|
| 4 | MERGED | 2026-08-08T17:01:44Z | fagenorn |
| 6 | MERGED | 2026-08-08T19:14:23Z | fagenorn |
| 7 | MERGED | 2026-08-08T21:08:05Z | fagenorn |
| 8 | MERGED | 2026-08-08T21:41:06Z | fagenorn |
| 10 | MERGED | 2026-08-08T21:41:44Z | fagenorn |
| 11 | MERGED | 2026-08-09T06:45:53Z | fagenorn |
| 15 | MERGED | 2026-08-09T08:13:25Z | fagenorn |
| 47 | MERGED | 2026-08-14T14:22:17Z | fagenorn |
| 54 | MERGED | 2026-08-14T20:18:38Z | fagenorn |
| 55 | MERGED | 2026-08-14T22:46:02Z | fagenorn |
| 56 | MERGED | 2026-08-16T08:07:16Z | fagenorn |
| 57 | MERGED | 2026-08-16T07:50:01Z | fagenorn |
| 58 | MERGED | 2026-08-16T17:51:27Z | fagenorn |
| 59 | MERGED | 2026-08-17T07:23:51Z | fagenorn |
| 60 | MERGED | 2026-08-17T09:17:53Z | fagenorn |
| 61 | MERGED | 2026-08-17T09:22:14Z | fagenorn |
| 106 | MERGED | 2026-08-18T10:18:52Z | fagenorn |
| 107 | MERGED | 2026-08-22T20:15:15Z | fagenorn |
| 110 | MERGED | 2026-08-29T10:52:38Z | fagenorn |
| 111 | MERGED | 2026-09-04T12:51:17Z | fagenorn |
| 113 | MERGED | 2026-09-04T20:48:39Z | fagenorn |
| 114 | MERGED | 2026-09-04T21:05:54Z | fagenorn |

Merged 22, closed-unmerged 0; merger logins: {fagenorn}. (The PR list holds 24 PRs in all; the other 2, 108 and 115, are OPEN.)

### CI duration and bound

Workflow `ci.yml` on main: line 26 `name: memory foundation (unit + forced checks)`, line 31 `timeout-minutes: 15`.

| Run | Event | Branch | Status | Conclusion | Started | Minutes |
|---|---|---|---|---|---|---|
| 34291237489 | pull_request | worktree-issue-94-daemon-ops-hygiene | completed | success | 2026-09-08T23:34:14Z | 7.4 |
| 34290397688 | pull_request | worktree-issue-94-daemon-ops-hygiene | completed | failure | 2026-09-08T23:23:05Z | 9.2 |
| 33919481775 | push | main | completed | success | 2026-09-04T21:05:57Z | 6.3 |
| 33918788637 | pull_request | worktree-issue-101-junk-rescue-pull-forward | completed | success | 2026-09-04T20:57:29Z | 8.0 |
| 33918078313 | push | main | completed | success | 2026-09-04T20:48:42Z | 8.7 |
| 33917516736 | pull_request | worktree-issue-101-junk-rescue-pull-forward | completed | success | 2026-09-04T20:41:57Z | 8.4 |
| 33917298926 | pull_request | worktree-issue-112-persistent-webkit-session | completed | success | 2026-09-04T20:39:19Z | 8.4 |
| 33917053479 | pull_request | worktree-issue-101-junk-rescue-pull-forward | completed | cancelled | 2026-09-04T20:36:17Z | 6.0 |
| 33916650948 | pull_request | worktree-issue-112-persistent-webkit-session | completed | cancelled | 2026-09-04T20:31:32Z | 8.1 |
| 33892547058 | push | main | completed | success | 2026-09-04T15:58:48Z | 8.5 |
| 33874899059 | push | main | completed | success | 2026-09-04T12:51:20Z | 9.3 |
| 33874114139 | pull_request | worktree-issue-100-junk-bench-direct | completed | success | 2026-09-04T12:42:13Z | 8.6 |
| 33248818353 | push | main | completed | failure | 2026-08-29T10:52:40Z | 0.1 |
| 33245506761 | pull_request | worktree-issue-109-configurable-model-routing | completed | failure | 2026-08-29T09:33:54Z | 0.1 |
| 33244534794 | pull_request | worktree-issue-109-configurable-model-routing | completed | failure | 2026-08-29T09:02:18Z | 0.1 |
| 32661547487 | pull_request | worktree-issue-102-persist-every-park-stealth-junk-trends | completed | failure | 2026-08-23T19:32:18Z | 0.1 |
| 32596143543 | push | main | completed | failure | 2026-08-22T20:15:17Z | 0.1 |
| 32503157298 | pull_request | worktree-issue-99-measure-junk-per-query-voice-route | completed | failure | 2026-08-21T16:29:11Z | 0.1 |
| 32127247958 | push | main | completed | failure | 2026-08-18T10:32:21Z | 0.1 |
| 32126136755 | push | main | completed | failure | 2026-08-18T10:18:54Z | 0.1 |

Bound: last ten completed non-cancelled runs, max 9.3 min against timeout-minutes 15 — within bound

Argus issue 5 is OPEN, "CI: unit-test step hangs on GitHub runners (workflow has never completed)". Completed `success` runs that contradict "never completes": 34291237489, 33919481775, 33918788637, 33918078313, 33917516736, 33917298926, 33892547058, 33874899059, 33874114139. Nine `failure` runs: eight last 0.1 min (2026-08-18 to 2026-08-29), and run 34290397688 failed after 9.2 min (below the 15 min timeout).

### Daemon-to-child handoff

`launchctl print gui/501/dev.argus.daemon`: `state = running`, `pid = 3955`, `runs = 1`, `last exit code = (never exited)`. Argus issue 80, "Handoff seam: --no-session and full-stdout NOTIFY capture", is OPEN (closedAt null).

### Host

- Generation: `/run/current-system` -> `/nix/store/10vnka9gd69g301lzcpiyikhzf1pdjv0-darwin-system-25.11.ebec37a`; `/nix/var/nix/profiles/system` -> `system-307-link`, link time 2026-11-02T19:27:43+0000.
- Fleet registry projects:
  - `arcwave` at `/Users/anis/Projects/arcwave`, branch_override `dev` (default `main`), reason `default_contract_unresolved`
  - `fagenorn/nix-config` at `/Users/anis/tmp/nix-config`, no override
  - `jarbird` at `/Users/anis/Projects/jarbird`, no override
  - `nodocom` at `/Users/anis/Projects/nodocom`, branch_override `dev` (default `main`), reason `default_contract_unresolved`
- Compiled guard policy: derivation `{platform_version 1.0.0, registry_digest sha256:959f670a9ea7ad0890460588d1886b9926c4cda572fb580586335fef8da80739, schema_version 2}`; derived repositories `elevenyellow/jarbird`, `elevenyellow/nodocom`, `fagenorn/arcwave`, `fagenorn/nix-config` (no Argus).
- `~/Applications/ArgusPing.app`: absent (expected per spec § 2; nothing removed).

## Task 2 — Switch gate
Switch gate: commit ed33215598521ba745f6262233e0c2c98ef1479f
The switch needs owner presence for sudo (Touch ID). From a clean checkout of ed33215598521ba745f6262233e0c2c98ef1479f of
/Users/anis/tmp/nix-config on mbp, run `just switch`. The run then resumes at Task 2 Step 2,
which uses commit ed33215598521ba745f6262233e0c2c98ef1479f and skips the switch once /run/current-system is that build.

## Task 2 — Switch and installed/source conformance
Switch commit: 5dfe65efbae09024aaf259d5a013d5658eeec0a0
System: /nix/store/h6d51wj2r5x9wp52my07f3rdpia9rx72-darwin-system-25.11.ebec37a
Guard wrapper: /nix/store/6w6drg3l4z7k9ldk9hffmlm4cvnifynp-claude-bash-lifecycle-guard/bin/claude-bash-lifecycle-guard
Platform version: 1.0.0
Switch: already installed

The owner ran `just switch` (generation 308, issue 129 comment https://github.com/fagenorn/nix-config/issues/129#issuecomment-6599895106) from `main` at `5dfe65ef`, which contains `ed332155`. Per spec ledger row D22 (refines D20), `C` is that installed commit and not the gate block's `ed332155`; `merge-base --is-ancestor ed332155 C` exits 0, and the gate block above is kept as history. The scratch build of `C` is `R`, equal to `/run/current-system`, so no switch ran here.

| Check | Result | Time |
|---|---|---|
| clean tree at `C` (scratch checkout, HEAD = `C`) | pass | 2026-11-03T09:27:11Z |
| `/run/current-system` = `R` | pass | 2026-11-03T09:27:11Z |
| hook names `G` from `R`'s closure (one guard package, executable) | pass | 2026-11-03T09:27:11Z |
| `test_installed_policy_surface_matches_source_contract` | OK (1 test) | 2026-11-03T09:27:16Z |

Compiled guard policy derivation: `{"platform_version": "1.0.0", "registry_digest": "sha256:959f670a9ea7ad0890460588d1886b9926c4cda572fb580586335fef8da80739", "schema_version": 3}`

## Task 3 — Contract commit and doctor report 1

Argus base: dc7564b3c8bbd6a5633dfcff78f80291175047fd
Contract commit: 738a251bafefe9c3679cf7338cb45cd14ecc4932
Contract sha256: 4b5cb7bf87c50be759d0c9e5509356150b4b683c2525ad848ae5e70596c79093
Platform interval: 1.0.0 to 2.0.0

Clone `$SCR/argus-129` on local branch `project-contract` (contract committed 2026-11-03T09:31:42Z, worker w4; resumed and re-verified by w6 at 2026-11-03T09:41Z). The commit is signed and changes only `.agents/project.json`.

Resolve at `K` (2026-11-03T09:41:53Z, re-run once): `invalid_projection`, repair `projection.claude-instructions.stale`, nothing else (first taken 2026-11-03T09:31:50Z, same result).

Contract as a single compact line (Task 4 rebuilds the commit from it):

```json
{"schema_version":1,"platform":{"min_inclusive":"1.0.0","max_exclusive":"2.0.0"},"project":{"id":"fagenorn/argus","name":"argus"},"bindings":{"vcs":{"kind":"git","default_branch":"main","integration_branch":"main","branch_pattern":"issue-<num>-<slug>","worktree":{"root":".worktrees","prefix":"worktree-"},"commit":{"co_authored_by":true,"signed":true},"merge":{"strategy":"merge","delete_branch":true,"required_checks":["memory foundation (unit + forced checks)"]}},"tracker":{"kind":"github","cli":"gh","repo_slug":"fagenorn/argus","credential_env":{"unset_before_invocation":["GITHUB_TOKEN","GH_TOKEN"]}},"paths":{"artifacts":{"specs":".agents/artifacts/specs","plans":".agents/artifacts/plans"},"context":["docs/CONTEXT-MAP.md"],"standards":["docs/standards/README.md"],"architecture":["docs/guides/architecture.md"],"operations":[],"hints":[],"rejections":[]},"commands":{"install":{"argv":["npm","ci"],"cwd":".","env":[]},"coverage-guard":{"argv":["node","--test","--experimental-strip-types","--experimental-sqlite","--disable-warning=ExperimentalWarning","tests/docs/ci-covers-every-test.test.ts"],"cwd":".","env":[]},"unit-tests":{"argv":["node","--test","--experimental-strip-types","--experimental-sqlite","--disable-warning=ExperimentalWarning","tests/**/*.test.ts"],"cwd":".","env":[]},"forced-checks":{"argv":["node","--experimental-strip-types","--experimental-sqlite","--disable-warning=ExperimentalWarning","eval/suites/memory/checks/forced-checks.ts"],"cwd":".","env":[]},"recall-cap-checks":{"argv":["node","--experimental-strip-types","--experimental-sqlite","--disable-warning=ExperimentalWarning","eval/suites/memory/checks/recall-cap.ts"],"cwd":".","env":[]},"build-notifier":{"argv":["bash","daemon/notifyd/build.sh"],"cwd":".","env":[]}},"workflow":{"verification":["install","coverage-guard","unit-tests","forced-checks","recall-cap-checks"],"orchestration":{"max_parallel":2,"attempt_budget_minutes":240},"review":{"plan":null,"code":null}},"deploy":{"adapter":"none","command":null,"config":{}}},"capabilities":{"tracker":{"support":"supported"},"worktrees":{"support":"supported"},"knowledge.context":{"support":"supported"},"knowledge.standards":{"support":"supported"},"knowledge.architecture":{"support":"supported"},"knowledge.hints":{"support":"unsupported"},"verification":{"support":"supported"},"review.plan":{"support":"unsupported"},"review.code":{"support":"unsupported"},"deploy":{"support":"unsupported"}},"projections":[{"id":"claude-instructions","agent":"claude","kind":"managed_import","target":"CLAUDE.md","source":"AGENTS.md"}],"release":{"profiles":{"local-host":{"profile_version":1,"target":{"environment":"local-host","concurrency_keys":["release/fagenorn/argus"]},"requirements":{"adapters":{"bundle":{"min_inclusive":"1.0.0","max_exclusive":"2.0.0"},"launchd":{"min_inclusive":"1.0.0","max_exclusive":"2.0.0"}}},"bindings":{"adapters":{"bundle":{"adapter":"codesigned-artifact"},"launchd":{"adapter":"launchd-agent"}},"targets":{"notifier":{"adapter":"bundle","kind":"installed_bundle","path":"~/Library/Application Support/Argus/Argus.app"},"daemon":{"adapter":"launchd","kind":"launchd_gui_agent","label":"dev.argus.daemon"}},"principals":{"owner":{"class":"host_user"}},"credentials":{"keychain":{"adapter":"bundle","class":"codesigning_identity"},"session":{"adapter":"launchd","class":"gui_session"}}},"publication":{"actions":[{"id":"notifier","mode":"materialize","adapter":"bundle","operation":"install","target":"notifier","principal":"owner","credential":"keychain","effect":"reversible_no_incremental_spend","config_schema_version":1,"config":{"source":"daemon/notifyd/Argus.app","identity_prefix":"Apple Development","identity_env":"ARGUS_CODESIGN_IDENTITY","adhoc_fallback":false},"deps":[],"observation_deadline_ms":120000}]},"activation":{"units":[{"id":"daemon","mode":"local_apply","adapter":"launchd","operation":"activate","target":"daemon","principal":"owner","credential":"session","effect":"irreversible","config_schema_version":1,"config":{"program":"devenv","arguments":["shell","--","daemon","run"],"keep_alive":true,"background":true,"stdout_path":"home/daemon/logs/daemon.out.log","stderr_path":"home/daemon/logs/daemon.err.log"},"deps":[],"observation_deadline_ms":300000}]},"proof":{"convergence_window_ms":1800000,"obligations":[{"id":"daemon-live","semantic":"liveness","form":"snapshot","predicate":"agent_running","collector":"launchd","required":true,"deps":["derived:running_subject_identity:daemon"],"parameters":{"parameters":{"action":"daemon","operation":"activate","target":{"handle":"daemon","kind":"launchd_gui_agent","label":"dev.argus.daemon"},"config":{"program":"devenv","arguments":["shell","--","daemon","run"],"keep_alive":true,"background":true,"stdout_path":"home/daemon/logs/daemon.out.log","stderr_path":"home/daemon/logs/daemon.err.log"}}},"freshness_ms":600000}]},"recovery":{"units":{"notifier":{"posture":"supersedable_only","anchor":null,"compatibility":null,"edges":[]},"daemon":{"posture":"supersedable_only","anchor":null,"compatibility":null,"edges":[]}}},"limits":{}},"forge-main":{"profile_version":1,"target":{"environment":"github-main","concurrency_keys":["release/fagenorn/argus"]},"requirements":{"adapters":{"forge":{"min_inclusive":"1.0.0","max_exclusive":"2.0.0"}}},"bindings":{"adapters":{"forge":{"adapter":"github-forge"}},"targets":{"repository":{"adapter":"forge","kind":"github_repository","repository":"fagenorn/argus","branch":"main"}},"principals":{},"credentials":{}},"publication":"none","activation":"none","proof":{"convergence_window_ms":1800000,"obligations":[]},"recovery":{"units":{}},"limits":{}}}}}
```

Pre-flight (D4), argv as the CI step, run as `launch-scope exec … -- env -C <clone> TMPDIR=/tmp <argv>` per spec ledger row D23 (TMPDIR set on that command only; the contract is unchanged). Clone `status --porcelain` stayed empty. Runs 2026-11-03T09:42:05Z to 09:48:03Z.

| Id | Exit | Tail |
|---|---|---|
| install | 0 | npm audit notice only |
| coverage-guard | 0 | fail 0, skipped 0 |
| unit-tests | 0 | tests 3957, pass 3952, fail 0, skipped 5 (207 s) |
| forced-checks | 0 | 11 passed, 0 failed |
| recall-cap-checks | 0 | 10 passed, 0 failed |
| unit-tests, default TMPDIR (earlier run, finished 2026-11-03T09:38:03Z, superseded per D23) | 1 | fail 1, skipped 5: `tests/extensions/email/review-render.test.ts:100`, receipt was 504 chars (cap 500) under the macOS per-user TMPDIR |

Doctor report 1 (`conformance run --purpose doctor`, 2026-11-03T09:48:07Z, projection not yet written), outcome `failed`, primary check `repository.ignore.runtime_sentinel`.

| Check | Status | reason_code | repair_id |
|---|---|---|---|
| host.admission.declaration | passed | | |
| host.capability.required | suppressed (no finding, spec § 6) | | |
| host.executor.helper_on_path | passed | | |
| host.policy_path.no_follow_readable | passed | | |
| host.tracker.credential | passed | | |
| repository.ignore.runtime_sentinel | failed | runtime_ignore_missing | lifecycle.ignore.repair |
| repository.projection.fresh | failed | invalid_projection | projection.regenerate |

Repairs listed: `lifecycle.ignore.repair` (module conformance, safety_class worktree) and `projection.regenerate` (`resolve-project write-projections`, safety_class worktree). No host check failed; no repair was applied.

Known limitation (D23): on mbp under the default per-user TMPDIR the contract's `unit-tests` command fails `tests/extensions/email/review-render.test.ts` at the assertion on line 100 (receipt 504 > 500 chars; the receipt embeds an `os.tmpdir()` path). It passes with `TMPDIR=/tmp` and on Linux CI. The contract cannot express an env value, so any host run of the declared verification on mbp (Task 4's apply, later Argus workflows) needs `TMPDIR=/tmp` until Argus fixes the test. No Argus issue exists yet; the follow-up (an Argus issue for the host-path-dependent cap) is for the owner and is surfaced in Task 8's acceptance record.

## Task 4 — Adoption plan, apply and inspection

Plan id: sha256:e37b7e24779f1f713b53f9542e88bf832fd67961d3fe6e84d14b8cc898b2893f
Adoption branch: adopt-e37b7e24779f
Adoption commit: 553b2c59e1192f5bfad06073f00ca1dde2e127da
Pushed: 2026-11-03T09:59:23Z

Step 1 passed without a rebuild: the clone `$SCR/argus-129` (`SCR` = `/private/var/folders/t4/b5y8ggd92zb044029__7wr9w0000gp/T/launch-scope-6fr9cnfx`, worker w9) was on `project-contract` at `K` = `738a251bafefe9c3679cf7338cb45cd14ecc4932`, clean, with `origin/main` at `B`. No `Contract commit (rebuilt)`.

Plan (`adopt-project plan`, 2026-11-03T09:55:09Z to 09:55:10Z, run once with the default TMPDIR; no ready gate runs a verification command): state `ready`, outcome `reconcile`, `base_revision` = `K`, blockers `[]`, all eight ready gates `passed` (`contract-valid-after-amendment`, `no-needs-decision`, `no-open-decisions`, `no-untracked-overlap`, `no-existing-destination`, `move-sources-tracked`, `no-secret-path-in-moves`, `no-unrewritable-link`), open decisions `[]`, so no `Answered questions` table. Operations: `git-mv` 188, `write-file` 76, `regenerate-projection` 1; no `delete-file`. No evidence row is `needs-decision`.

Plan evidence rows for the three paths Task 4 names:

| Path | Class | Action | Count | Target |
|---|---|---|---|---|
| `.claude/skills` | legacy-native-store | retain-product | 3 | none |
| `AGENTS.md` | native-projection | generate-projection | 1 | `AGENTS.md` |
| `CLAUDE.md` | native-projection | generate-projection | 1 | `CLAUDE.md` |

The other rows: `.agents/project.json` move-canonical (1), `.claude/plans` to `.agents/artifacts/plans` move-canonical (117), `.claude/specs` to `.agents/artifacts/specs` move-canonical (71), `.github` retain-product (1).

Finding to operation (D10), doctor report 1:

| Finding | Repairing operation in the plan |
|---|---|
| `repository.projection.fresh` / `invalid_projection` / `projection.regenerate` | `regenerate-projection`: source `AGENTS.md`, target `CLAUDE.md` (before `sha256:f80bf3b7…`) |
| `repository.ignore.runtime_sentinel` / `runtime_ignore_missing` / `lifecycle.ignore.repair` | `write-file` creating `.agents/runtime/.gitignore` (the committed sentinel; `after` `sha256:cdbcae15…`) |

Deviation from the brief's expected pair: the plan holds no root `.gitignore` amendment and needs none. `check_ignore_runtime_sentinel` passes when either a root rule or the committed sentinel covers `.agents/runtime/`, and the base's root `.gitignore` has no `.agents` rule, so the sentinel write alone repairs the finding. Both findings have a repairing operation, so the stage did not stop.

Apply (2026-11-03T09:55:55Z to 09:58:55Z): `launch-scope exec … -- env TMPDIR=/tmp adopt-project apply --plan-id <plan id>`, exit 0, once, no `--acknowledge-deletions`. It ran with `TMPDIR=/tmp` per D23 (TMPDIR on that one command only). Output: branch `adopt-e37b7e24779f`, commit `553b2c59e1192f5bfad06073f00ca1dde2e127da`, the plan id above, evidence record `.agents/artifacts/evidence/e37b7e24779f1f713b53f9542e88bf832fd67961d3fe6e84d14b8cc898b2893f.json`, migration map `.agents/knowledge/archive/path-migrations/e37b7e24779f1f713b53f9542e88bf832fd67961d3fe6e84d14b8cc898b2893f.json`. Commit subject `chore(adopt): adopt fagenorn/argus at plan e37b7e24779f`.

Commit gates (plan file in `~/.agents/state/adopt/plans/`), all seven `passed`: `worktree-status-matches-operations`, `projections-in-sync`, `no-unclassified-agent-path`, `no-new-broken-link`, `cold-clone-resolves`, `resolve-capabilities-available`, `workflow-verification-commands`.

Inspection of the branch in the clone (clone status clean):
- `git log origin/main..HEAD`: exactly two commits, `553b2c59e1192f5bfad06073f00ca1dde2e127da` (parent `738a251bafefe9c3679cf7338cb45cd14ecc4932`, `chore(adopt): adopt fagenorn/argus at plan e37b7e24779f`) then `738a251bafefe9c3679cf7338cb45cd14ecc4932` (parent `dc7564b3c8bbd6a5633dfcff78f80291175047fd` = `B`, `chore: add the project contract`).
- `git diff --name-status origin/main...HEAD` by first letter: 4 A (`.agents/project.json`, `.agents/runtime/.gitignore`, the evidence record, the migration map), 44 M (`CLAUDE.md`, `docs/README.md`, `docs/guides/architecture.md` and 41 ADRs under `docs/areas/*/adr/`), 188 R (158 R100, 14 R099, 9 R098, 5 R097, 1 R096, 1 R091). No D.
- `resolve-project resolve`: `capabilities.release` is `{"reason_code":null,"repair_id":null,"state":"available"}`; targets `forge-main/github-forge/repository/[]`, `local-host/launchd-agent/daemon/["activate"]`, `local-host/codesigned-artifact/notifier/["install"]`.
- `release profile inspect` for `local-host` and `forge-main`: exit 0 for both; `repository.release_profile.observation_deadline`, `.restore_anchor` and `.rolled_back_reachable` all `passed` (`reason_code` null), findings `[]`.

Push: `git push -u origin adopt-e37b7e24779f` from the clone, run alone in its own Bash call; the guard allowed it. `git ls-remote origin refs/heads/adopt-e37b7e24779f` printed `553b2c59e1192f5bfad06073f00ca1dde2e127da` (2026-11-03T09:59:23Z), and it is the only `adopt-` ref on the remote. Nothing else was pushed, no PR was opened (D16), and no failed-apply worktree exists to retain.

The four bare helpers authd, ocr-helper, wa-bridge and wkfetch are signed in place inside the checkout, gitignored, and rebuilt by Argus's devenv shell entry only when absent. They are inputs of the daemon unit, not release units. The daemon unit's identity proves the checkout at the candidate commit with no tracked change, which an untracked stale helper binary passes, so a release does not prove that the helpers were rebuilt from the candidate commit.

## Task 5 — Pre-registration probes and owner gate

Recorded 2026-11-03T10:03Z. The guard was fed payload files only, using the wrapper that `~/.claude/settings.json` registers, which equals Task 2's `Guard wrapper`. No `gh pr create`, `gh pr merge` or `git push` ran. The probe clone `argus-129` had `origin` `git@github.com:fagenorn/argus.git` and `refs/remotes/origin/HEAD` `refs/remotes/origin/main`. It was clean, `origin` still listed `adopt-e37b7e24779f` at the adoption commit, and it was removed.

| Probe | Command | cwd | Exit | Guard output | Time |
| --- | --- | --- | --- | --- | --- |
| pr-create | `gh pr create --repo fagenorn/argus --base main --head adopt-e37b7e24779f --title "Adopt the project contract" --body "…"` | argus clone | 0 | none (allowed by the `fagenorn` owner literal) | 2026-11-03T10:03:00Z |
| merge-pre | `gh pr merge 115 --repo fagenorn/argus --merge --match-head-commit 0bd5fb02c8545ed0247fe85fcf90d6e2e8b7360e --delete-branch` | argus clone | 2 | `lifecycle guard: protection lookup failed: stderr=gh: Upgrade to GitHub Pro or make this repository public to enable this feature. (HTTP 403); …` | 2026-11-03T10:03:10Z |

Both verdicts are the expected ones. Open PRs into `main` were 115 (clean) and 108 (dirty); 115 was probed. With no registered row, the plan-gated 403 declares no check, which is the bootstrap refusal (552 D8).

### Owner gate
Owner gate: open and merge adopt-e37b7e24779f at head 553b2c59e1192f5bfad06073f00ca1dde2e127da
1. Open the PR from any Argus checkout, or on GitHub with base main and head adopt-e37b7e24779f:
   gh pr create --repo fagenorn/argus --base main --head adopt-e37b7e24779f --title "Adopt the project contract" --body "Adds the Argus project contract and the adopt-project adoption commit for https://github.com/fagenorn/nix-config/issues/129. Merge with a merge commit once the required check is green on the pushed head."
2. Wait until the check memory foundation (unit + forced checks) is green on head 553b2c59e1192f5bfad06073f00ca1dde2e127da. If it is red, leave the PR open and unmerged.
3. Merge with a merge commit, never squash or rebase, deleting the branch:
   gh pr merge <n> --repo fagenorn/argus --merge --match-head-commit 553b2c59e1192f5bfad06073f00ca1dde2e127da --delete-branch
   or use GitHub's Create a merge commit.
Resume: the run continues at Task 6, which confirms the merge before anything else.
