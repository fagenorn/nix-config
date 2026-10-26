# Slim Fresh-Owner Boot Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `just agent-costs --report boot` splits every owner boot into twelve buckets that sum to B, per host and pooled. A two-host baseline then judges the three candidate cuts, and each cut that pays ships as its own pinned commit. The pre-merge sweeps and the post-deploy protocol are recorded for the evidence hold.

**Architecture:** A new `agent_tools.agent_boot_report` takes lineages and boots from the owner report unchanged (D1). It re-reads each boot transcript's request records and tool results to attribute every call's growth to a closed bucket set (D2, D3, D17), and groups the boots by host, cohort and phase group (D4, D15). `agent_costs.main` dispatches `--report boot` to it (D14). Skill-text cuts follow, each judged by D5 against projections from the tool's own baseline (D16): sdd's `--reviewed` (D6), the resume entry (D7, D20) and the index's support-file sections (D8).

**Tech stack:** Python 3.13 standard library (`json`, `re`, `statistics`, `socket`, `tarfile`, `posixpath`), `unittest` driving `python -m agent_tools.agent_costs`, Markdown skill documents, Bash, Nix (`just build`), Just.

Spec: `.agents/artifacts/specs/2026-10-26-issue-448-slim-owner-boot-design.md` (a bare "Dn" cites its ledger; this plan appends D16–D20, and Phase 5 D21–D22). Issue: https://github.com/fagenorn/nix-config/issues/448. Acceptance record: `.agents/artifacts/plans/2026-10-26-issue-448-slim-owner-boot.acceptance.md`. Task 3 creates it, Tasks 4–6 fill their cut rows and Task 7 completes it.

## Global Constraints

- Base `ca6ba1ae` (`origin/main` at planning); spec commits `a2c7064e`, `cf7232c1`. Tasks land in index order. Tasks 4–6 each start by reading their cut's row in the acceptance record. A `reject` there means the task builds nothing and commits nothing (D16).
- Python standard library only. `docs/standards/agent-helpers.md` rules 1–6 bind every module and test. The parser's `prog` stays `agent-costs`. Package code has no `sys.path` edit, no `importlib` load and no `__file__` lookup. Tests run `python -m agent_tools.agent_costs` or import modules. Skill-text tests pin identifiers only (file names, headings, literal tokens, argv), and a phrase pin on text a task rewrites is deleted in that task.
- Not edited: `transcript_calls.read_transcript`, `agent_owner_report.boot_slice`/`boot_facts`/`collect`, `agent_owner_replay`, `home/common/agent-skills/scripts/workflow-state.py`, the resume pack's schema and 4,096-byte bound, `home/common/claude-code/lifecycle_guard.py`, `.agents/project.json`, and every Instruction Budget gate file other than `home/common/agent-skills/instruction-load.json`.
- Comments, docstrings and README sentences describe the code as it behaves at that task's commit. Write "issue 448", never a bare `#448`. No `TODO`/`FIXME`, no mutable default argument, and no knob, field or flag for cut 4 or cut 5 (D9, D10).
- Instruction load: never add the `instruction-budget-raise` label and never raise a ceiling. Headroom at `cf7232c1` is as follows. `from-issue-controller`: hot 2 B, conditional 144 B. `orchestration-dispatcher`: hot 7 B. `implementation-owner`: hot 8 B, conditional 1,788 B. `orchestrated-issue-owner`: hot 474 B, conditional 1,835 B. Corpus: 8,840 B. Each cut is net-negative in bytes over the skill documents it touches (D5). Lowering a ceiling is the only allowed change to `instruction-load.json`, done with `just agent-instruction-load tighten` and only when the gate reports tightness.
- Transcripts: anis-desktop data comes only through D18's copy, read-only, into the task's launch-scope scratch. It is never written into the repository and is removed when the task ends. The acceptance record holds aggregate figures only: no transcript path, session ID or run ID from either host (D15, D18).
- Never run `just switch`, never touch the primary checkout or `~/.agents/share/`, never push.
- Every long command, each test command included, runs in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration. Commits go through `launch-commit … -- <git commit args>`, SSH-signed, ending with the session's two trailer lines. Scratch files live under the root that `launch-scope scratch` prints.
- **Boot tests** (timeout 900 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_agent_boot_report.py 2>&1 | tail -4'`.
- **Report tests** (timeout 900 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_agent_costs.py tests/test_agent_owner_report.py tests/test_agent_owner_replay.py tests/test_agent_boot_report.py 2>&1 | tail -4'`.
- **Skill contract tests** (timeout 900 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_skill_lint.py 2>&1 | tail -4'`.
- **Budget** (timeout 600 s): `bash -c 'set -o pipefail; just agent-instruction-budget 2>&1 | tail -6'`, passing with no `--raise-label`.
- **Build** (timeout 3600 s): `bash -c 'set -o pipefail; just build 2>&1 | tail -3'`.
- Final gate (sdd, once on the final head): `just build`, `just agent-workflow-tests` (timeout 3600 s each) and `just agent-instruction-budget`, each passing.

## Test seams

- Seam 1: `python -m agent_tools.agent_costs --report boot --format json --days 0 --projects-dir <tmp>` (text without `--format`) over fixture transcripts built by `tests/owner_transcripts.Session`, extended with request-shape, request and blob records, Skill meta messages and any tool use (D1–D4, D14, D15, D17).
- Seam 2: identifier-only pins in `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, class `SlimBootContractsTest`, one test group per kept cut (D20).
- Seam 3: `just agent-instruction-budget` with no raise label, plus each cut's net-bytes check.
- Seam 4: acceptance-record rows and sections: the baseline, the projections, the pre-merge sweeps and the post-deploy protocol (D12, D13, D16, D19). The final gate covers the rest.

## Delivery estimate and boundaries

Estimates: about 15 changed files. `agent_boot_report.py` ~420 lines; `test_agent_boot_report.py` ~330; `owner_transcripts.py` +40; `agent_costs.py` +60; README +2 paragraphs; skill text net-negative across about 7 documents; the acceptance record ~12 KB. Aggregate growth is mostly the new module and its tests, about 900 product lines, so one review package should hold it. Independently deliverable slices if a split is forced: S1 = Tasks 1–2 (the report), S2 = Task 3 (baseline and verdicts), S3 = Tasks 4–6 (one commit per kept cut), S4 = Task 7 (evidence).

## Task index

Task 1 — The boot report over one root: attribution, cohorts, groups, JSON and text — `python/agent_tools/agent_boot_report.py`, `python/agent_tools/agent_costs.py`, `tests/owner_transcripts.py`, `tests/test_agent_boot_report.py`, `justfile`, `python/README.md` — full — [task-1.md](2026-10-26-issue-448-slim-owner-boot.tasks/task-1.md)
Task 2 — Hosts: repeatable labelled roots, per-host and pooled groups — `python/agent_tools/agent_costs.py`, `python/agent_tools/agent_boot_report.py`, `tests/test_agent_boot_report.py`, `python/README.md` — full — [task-2.md](2026-10-26-issue-448-slim-owner-boot.tasks/task-2.md)
Task 3 — Two-host baseline, cut projections and keep verdicts — `.agents/artifacts/plans/2026-10-26-issue-448-slim-owner-boot.acceptance.md` — full — [task-3.md](2026-10-26-issue-448-slim-owner-boot.tasks/task-3.md)
Task 4 — Cut 1: one task file per dispatch (`--reviewed`) — `home/common/agent-skills/skills/sdd/SKILL.md`, `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `.agents/artifacts/plans/2026-10-26-issue-448-slim-owner-boot.acceptance.md` — full — [task-4.md](2026-10-26-issue-448-slim-owner-boot.tasks/task-4.md)
Task 5 — Cut 2: the resume entry — `home/common/claude-code/skills/orchestrate-issues/SKILL.md`, `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/agent-skills/skills/from-issue/resume-pack.md`, `home/common/agent-skills/skills/from-issue/AUTO.md`, `home/common/agent-skills/README.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `.agents/artifacts/plans/2026-10-26-issue-448-slim-owner-boot.acceptance.md` — full — [task-5.md](2026-10-26-issue-448-slim-owner-boot.tasks/task-5.md)
Task 6 — Cut 3: support-file sections in the index — `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/agent-skills/skills/from-issue/AUTO.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `.agents/artifacts/plans/2026-10-26-issue-448-slim-owner-boot.acceptance.md` — full — [task-6.md](2026-10-26-issue-448-slim-owner-boot.tasks/task-6.md)
Task 7 — Pre-merge sweeps, threshold statement and the post-deploy protocol — `.agents/artifacts/plans/2026-10-26-issue-448-slim-owner-boot.acceptance.md` — full — [task-7.md](2026-10-26-issue-448-slim-owner-boot.tasks/task-7.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | `tests/test_agent_boot_report.py`, run by `just agent-workflow-tests`. `BootReportTest` (Task 1) checks the per-owner rows: the bucket sum equals B, the call-0 split at 2.44, read-backs, re-reads, resume content, skill sub-maps, cohorts, `unsplit`, refused flags and the text sections, plus the mean rows. `HostsTest` (Task 2) adds per-host and pooled means over two labelled roots. |
| AC2 | code | Task 7 | `SlimBootContractsTest` in `home/common/agent-skills/tests/test_workflow_skill_contracts.py`: one test group per cut that Tasks 4–6 built, named in the record's cut rows. Also `just agent-instruction-budget` with no `--raise-label` (Task 7 runs it and fills row `AC2`), and `just agent-workflow-tests` and `just build`, which sdd's final gate runs on the final head. |
| AC3 | evidence | Task 7 | **Before merge:** Task 3's two-host baseline. The window is 2026-10-24T00:00:00Z → record time, from roots `mbp` and an `anis-desktop` scratch copy, with host-`all`, `fresh`, phase-group-`all` B without tool schemas, each host's figure and every stratum count. Task 7 adds one `just agent-costs --report owners --sweep` per host root over 2026-10-24T00:00:00Z → its record time, with each chosen threshold stated with reasons (D13, D19). **Held** (issue kept open as `needs-verification`, D12): `--report boot` over the window from the later host's first post-merge `just switch`. The window closes once every baseline host × phase-group stratum has 5 or more `fresh` boots, 20 or more in all. Met when the baseline combined mean of B without tool schemas, minus the post-deploy stratum means reweighted to the baseline's host × phase-group mix, is at least **25,000**; each host's fall is reported alongside. Then the per-host post-deploy sweeps. Row `AC3` of the acceptance record. |

## Decisions

- Task 1 per D1–D4, D14, D17; Task 2 per D15, D17; Task 3 per D5, D11, D12, D15, D16, D18; Task 4 per D5, D6, D16, D20; Task 5 per D5, D7, D16, D20; Task 6 per D5, D8, D16, D20; Task 7 per D12, D13, D15, D18, D19, D21, D22.
- Not built: cut 4 (D9) and cut 5 (D10); Task 3 records their projections for information only (D16).
- Planning appended D16 (projection formulas and the build-or-skip rule), D17 (attribution rules the spec left open), D18 (the anis-desktop transfer), D19 (the pre-merge sweep window) and D20 (the entry placeholder and the identifier pins).

---

## Standards review provenance

- Reviewer: Codex (`codex-plan-review`, gpt-6-astra, xhigh), isolated read-only mode, no focus; no fallback.
- Base SHA: ca6ba1ae2b37e56c1361a8656c29af1f39b89348; plan reviewed at 5d14b3d9.
- Findings: 4 accepted (Blocking R1 → Task 7 Step 2b and D21; Blocking R2 → Task 7 post-deploy step 1 and D22; Should-fix R3 → Task 2's pooling fixture; Should-fix R4 → Task 4's ledger-on-entry wording), 0 rejected, 0 deferred.
- SDD's initial conflict scan (reviewer, read-only): 5 plan conflicts (C1–C5) resolved in the plan before execution; no member unreadable.
