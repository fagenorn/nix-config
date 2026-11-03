# Argus Adoption Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Adopt Argus (`fagenorn/argus`) through `adopt-project plan`, `apply` and `verify --register`, with every fact declared in Argus's own contract, and prove issue 129's nine criteria on host `mbp` and the forge, changing no nix-config product file.

**Architecture:** Eight operational tasks in the spec's section 4 order. Each runs installed commands against live host and forge state and appends one evidence section to `E` (D18); Task 8 writes the acceptance record. Two human gates: the Touch ID switch in Task 2 if it cannot complete, and the owner's open-and-merge of the bootstrap PR between Tasks 5 and 6 (D8, D16).

**Tech stack:** the installed agent tools, the registered guard hook, `git`, `gh`, `jq`, `just`/nix-darwin, Node 22 and npm.

Spec: `.agents/artifacts/specs/2026-11-03-issue-129-argus-adoption-design.md`. A bare "Dn" cites its `## Decision ledger`. Issue: https://github.com/fagenorn/nix-config/issues/129.

## Global Constraints

- The base is `ed33215598521ba745f6262233e0c2c98ef1479f` (`origin/main`). The spec commit is `6c8e4d57`, followed by the planning commit that appends D16–D20.
- nix-config writes are limited to two files: `E` = `.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md` (Tasks 1–8) and `A` = `.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.acceptance.md` (Task 8). No other nix-config path changes (AC8).
- Argus gets exactly two commits, the contract (Task 3) and the tool's adoption commit (Task 4), on `adopt-<digest12>`, pushed once (Task 4); never `--acknowledge-deletions`. `/Users/anis/Projects/argus` is read-only (D14, D17); only Task 7's registration and derive fetch into its remote-tracking refs.
- No release (D6): no `release transaction` verb, no `build-notifier` run, no `codesign`, no `launchctl` other than `print`, and no host clean-up.
- No agent runs `gh pr create` or `gh pr merge` for Argus (D16). The one `git push` runs alone in its own Bash call, never inside `launch-scope exec`, because the guard refuses a verb that sits in an argument position.
- Run every long command in the foreground as `launch-scope exec --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration. `SCR` is the root that `launch-scope scratch` (same flags) prints. All scratch lives under `SCR`, and `SCR` dies with the launch (D17). Shell variables do not survive between Bash calls, so substitute `SCR` and every recorded value as a literal.
- Commit nix-config changes from the worktree root through `launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "docs(issue-129/T<n>): <summary>" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`. Commits are SSH-signed; never disable signing. Write "issue 129", never `#129`.
- Spell every `gh` call `env -u GITHUB_TOKEN -u GH_TOKEN gh …` (Argus's scrub; the keyring credential).
- Evidence (D18): each task appends exactly one `## Task <n> — <title>` section to `E`. Times are UTC (`date -u +%Y-%m-%dT%H:%M:%SZ`). Each report is condensed to its outcome, every check that did not pass with its `reason_code` and `repair_id`, and the checks the task asserts. Never paste more than 40 lines of raw output or record a credential; `E` stays within each task's cumulative byte cap (one review shard).
- Stop routes. **Contract gap** (a binding, capability or artifact class the contract cannot express): return `BLOCKED contract_gap` with the observation; the controller records it on issue 129, files a blocking nix-config issue and suspends; no Argus-local workaround ships. **Human gate**: return `BLOCKED human_gate` with the gate block in `E`; the controller suspends `blocked_on=human_gate` and resumes at the task the block names.

## Test seams

The spec's § Test seams; no test is added: the installed commands as an operator runs them, the registered guard hook fed a payload file (D13), and the forge. Declared verification is `nix-build`; `agent-workflow-tests` is skipped, as nothing in its `when_changed` set changes (D18).

## Delivery estimate and boundaries

- `all` (Tasks 1–8) is the one boundary: one branch and one PR. The nix-config change is evidence only.
- Tasks run strictly in order; each human gate is a resumable task boundary (D16, D20).

## Task index

Task 1 — Fresh baseline — `.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md` — low-risk — [task-1.md](2026-11-03-issue-129-argus-adoption.tasks/task-1.md)

Task 2 — Switch `mbp` and prove installed/source conformance — `.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md` — full — [task-2.md](2026-11-03-issue-129-argus-adoption.tasks/task-2.md)

Task 3 — Argus's contract commit, pre-flight and doctor report 1 — `.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md` — full — [task-3.md](2026-11-03-issue-129-argus-adoption.tasks/task-3.md)

Task 4 — Adoption plan, apply, profile inspection and push — `.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md` — full — [task-4.md](2026-11-03-issue-129-argus-adoption.tasks/task-4.md)

Task 5 — Pre-registration guard probes and the owner gate — `.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md` — full — [task-5.md](2026-11-03-issue-129-argus-adoption.tasks/task-5.md)

Task 6 — The merge, doctor report 2, verify and conformance — `.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md` — full — [task-6.md](2026-11-03-issue-129-argus-adoption.tasks/task-6.md)

Task 7 — Registration and the derived row — `.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md` — full — [task-7.md](2026-11-03-issue-129-argus-adoption.tasks/task-7.md)

Task 8 — Guard probes, central-literal diff and the acceptance record — `.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md`, `.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.acceptance.md` — full — [task-8.md](2026-11-03-issue-129-argus-adoption.tasks/task-8.md)

## Acceptance map

The criteria are untagged; all nine are classified `evidence`, each filling row `ACn` of `A` (Task 8, from `E`).

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | evidence (classified) | Task 7 | `adopt-project verify --register` on `/Users/anis/Projects/argus`: `adopted`, `registered` `true`; registry entry exactly `{"project_id": "fagenorn/argus", "root": "/Users/anis/Projects/argus"}`; `platform-status --repo-root` on the merged clone `compatible`; the `--fleet` row `compatible` only after the owner fast-forwards the primary checkout, so that half is `human_pending` (D21) |
| AC2 | evidence (classified) | Task 8 | Task 7's row `main`/`main`/`["memory foundation (unit + forced checks)"]`; installed-guard probes: push and PR creation exit 0; a green open PR's merge exits 0 with `--match-head-commit` and 2 (the floor) without; AC8 holds. No qualifying PR: merge half `human_pending` (D13) |
| AC3 | evidence (classified) | Task 6 | Doctor reports 1 (Task 3) and 2: no `host` check `failed`; `host.policy_path.no_follow_readable` and `host.executor.helper_on_path` `passed` in both; all `host` checks `passed` in report 2; each report-1 finding closed by its Task 4 operation (D10) |
| AC4 | evidence (classified) | Task 4 | § Knowledge classification gives one action per item; the adoption plan's evidence row for `.claude/skills` is `retain-product`; no evidence row is `needs-decision` |
| AC5 | evidence (classified) | Task 4 | On `adopt-<digest12>`: `resolve-project resolve` exits 0, `release` `available`, handles `daemon`, `notifier`, `repository`; `release profile inspect` of both profiles exits 0, the three `repository.release_profile.*` checks `passed`, no finding |
| AC6 | evidence (classified) | Task 1 | Task 1's section is committed before Task 4 runs `adopt-project plan`; every completed, non-cancelled run among the last ten `CI` runs took at most 15 minutes |
| AC7 | evidence (classified) | Task 4 | The AC5 check, plus Task 4's statement of the bare-helper limitation (D5) |
| AC8 | evidence (classified) | Task 8 | `git log --no-merges ed33215598521ba745f6262233e0c2c98ef1479f..HEAD ^origin/main -- home/common/claude-code/ python/agent_tools/ home/common/agent-skills/scripts/ lib/ hosts/` prints nothing (the spec's diff over this branch's own commits); the installed base policy has no `argus`; row, floor check, targets and adapter executables trace to Argus's contract |
| AC9 | evidence (classified) | Task 6 | Doctor report 2 `passed`, plain `verify` `adopted` and installed/source conformance held, each with a UTC time earlier than Task 7's registration |

## Knowledge classification (AC4, per D7)

The spec's section 3 table: each item of the issue 62 inventory that names Argus, with its one reconciliation action. Candidates are carried, not decided.

| Item (issue 62 class) | Action |
|---|---|
| `AGENTS.md` § How we collaborate, the root-causes and verify leads (duplicate-of-global) | `retain-product`; demotion candidates |
| `AGENTS.md` § Key facts about the pi kernel (vendor-derived) | `retain-product`; dated re-verification stays with Argus |
| `.claude/skills/writing-pi-extensions/`, `.claude/skills/writing-pi-skills/` (vendor-derived) | `retain-product` (class `legacy-native-store`; the adoption evidence row `.claude/skills`) |
| `docs/standards/README.md` (duplicate-of-global) | `retain-product`; bound as `paths.standards`; demotion candidate |
| `docs/standards/pi-extensions.md` (vendor-derived) | `retain-product` |

`AGENTS.md` and `CLAUDE.md` keep the tool's `native-projection` classification.

## Decisions

- Contract, verification and profiles: D1–D5, D9, D19 (Task 3); no release: D6. Doctor and repairs: D10 (Tasks 3, 4, 6). Switch and conformance: D11, D20 (Tasks 2, 6).
- Bootstrap gate: D8, D16 (Tasks 5, 6). Registration and compile: D12, D14 (Task 7). Probes: D13 (Tasks 5, 8). Clones: D17; evidence: D18; no ADR: D15. Planning appended D16–D20.

---

## Standards review provenance

- Reviewer: Codex (`codex-companion task --fresh --reviewer plan-review`, gpt-6-astra, xhigh), isolated read-only mode, base `ed33215598521ba745f6262233e0c2c98ef1479f`, plan head `d6f95e1e`, no focus, no fallback.
- Accepted 4, rejected 0, deferred 0. AR129-01 (fleet compatibility reads the primary checkout's working tree) became D21 and Task 7 Step 6; AR129-02 (Task 4 rebuild creates `.agents/` and stages in the clone); AR129-03 (Task 6 and Task 8 commit subjects within 64 bytes); AR129-04 (Task 6 requires the floor check to complete before `mergedAt`).
- The reviewer could not read the issue comments (no network in its sandbox); the packet carried their summaries.

## Review feasibility delivery

```json
{"actual_evidence":{"head":"72ccd35d61c65585266e53c82b37684ff60123c3","kind":"git-range-ownership/v1","process_ranges":[{"base":"ed33215598521ba745f6262233e0c2c98ef1479f","boundaries":["all"],"head":"7d8ddfa16cb420fa99a85e2ecc14c5e931f88ca3"},{"base":"fa5e602c2c1a4c35158627664375085e41876674","boundaries":["all"],"head":"58f89f6744b68bc208aedfd6e27f509c113bb1e7"},{"base":"02f0884e3e73070733f18ce7333d44f0394a5e4c","boundaries":["all"],"head":"97eeed52ee1d2728a7f130e26cbe224f994dba39"},{"base":"186316a098f0d93861a79d41b6af01518c4a3dd7","boundaries":["all"],"head":"0882b079830426c506de23e5f005c7b6c887991e"}],"tree":"e1cd382b7cbfe26814ffa874546004d432a4b75b"},"boundaries":[{"acceptance":"Issue 129 complete: AC1 to AC9 recorded in the acceptance record from live host and forge evidence, and just build green","depends_on":[],"id":"all","parent":null,"prerequisite":{"kind":"delivery-base"},"process_commit_subject_bytes":[64,64,64,64,64,64,64,64,64,64,64],"process_forecast_ids":["s","p","t1","t2","t3","t4","t5","t6","t7","t8"],"process_package":{"plan":".agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.md","spec":".agents/artifacts/specs/2026-11-03-issue-129-argus-adoption-design.md","tasks":[".agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.tasks/task-1.md",".agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.tasks/task-2.md",".agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.tasks/task-3.md",".agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.tasks/task-4.md",".agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.tasks/task-5.md",".agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.tasks/task-6.md",".agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.tasks/task-7.md",".agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.tasks/task-8.md"]},"tasks":[1,2,3,4,5,6,7,8]}],"delivery_base":"ed33215598521ba745f6262233e0c2c98ef1479f","derived_from":null,"kind":"review-feasibility-delivery","process_records":[{"bounds":[{"added_lines":340,"boundary":"all","deleted_lines":0,"record_bytes":45056,"support":{"covers":["s"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"s","last_task":8,"owner":0,"path":".agents/artifacts/specs/2026-11-03-issue-129-argus-adoption-design.md"},{"bounds":[{"added_lines":115,"boundary":"all","deleted_lines":0,"record_bytes":24576,"support":{"covers":["p"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.md"},{"bounds":[{"added_lines":125,"boundary":"all","deleted_lines":0,"record_bytes":11264,"support":{"covers":["t1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.tasks/task-1.md"},{"bounds":[{"added_lines":125,"boundary":"all","deleted_lines":0,"record_bytes":10240,"support":{"covers":["t2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t2","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.tasks/task-2.md"},{"bounds":[{"added_lines":190,"boundary":"all","deleted_lines":0,"record_bytes":16384,"support":{"covers":["t3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t3","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.tasks/task-3.md"},{"bounds":[{"added_lines":135,"boundary":"all","deleted_lines":0,"record_bytes":13312,"support":{"covers":["t4"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t4","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.tasks/task-4.md"},{"bounds":[{"added_lines":110,"boundary":"all","deleted_lines":0,"record_bytes":10240,"support":{"covers":["t5"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t5","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.tasks/task-5.md"},{"bounds":[{"added_lines":120,"boundary":"all","deleted_lines":0,"record_bytes":11264,"support":{"covers":["t6"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t6","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.tasks/task-6.md"},{"bounds":[{"added_lines":110,"boundary":"all","deleted_lines":0,"record_bytes":9216,"support":{"covers":["t7"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t7","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.tasks/task-7.md"},{"bounds":[{"added_lines":125,"boundary":"all","deleted_lines":0,"record_bytes":12288,"support":{"covers":["t8"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t8","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.tasks/task-8.md"}],"proposed_boundary":"all","schema_version":3}
```
