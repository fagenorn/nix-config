# Recover #121 Tasks 1–3: Platform Manifest and Status Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Land the reviewed #121 Task 1–3 slice on `main` by replaying its commits
with their provenance. Then reconcile the #122 conformance ladder with it, so that a
main-based conformance run reports the installed platform version, the supported
project schemas and this project's compatibility.

**Architecture:** Nine `git cherry-pick -x` commits carry the platform manifest,
the `agent_platform` library, the contract's `platform` interval, the resolver gate
and `platform-status` verbatim. The only edit is one `justfile` conflict (D1, D2).
One reconciliation commit then rewires `check_contract_resolvable` to the recovered
resolver, in the order platform → present → schema → valid → range → projection →
capability. The same commit publishes the compatibility facts on
`compatibility.contract.schema_supported` and installs the platform into the
conformance suites' hermetic `HOME` (D4–D7).

**Tech stack:** Python 3 standard library (`unittest`, `importlib`, `unittest.mock`),
home-manager file publication in `home/common/agent-skills/default.nix`, `just`, git.

**Authority:** the spec `.claude/specs/2026-09-23-issue-147-platform-manifest-status-design.md`
and its `## Decision ledger` (D1–D11). The spec also carries a digest of the #121 IDs
that the recovered code cites.

## Global Constraints

- The base is `origin/main` `4f74c47742b4dcebd37edb2e49a4cc227cc53238`. The retained
  branch `worktree-issue-121-adoption-v1` (tip `fe85677c`) and its worktree
  `.worktrees/worktree-issue-121-adoption-v1` are read-only: read, `git log` and
  `git show` only.
- Replay exactly these commits, in this order:
  `862547dd afa5ceba 15a20e53 363c2c7d d87253f2 b2202040 e4cd1d6c a74c4d7a 8e6f0681`.
  No other retained commit is replayed (spec "Recovered commits").
- A cherry-picked commit keeps its original message, trailers and author, and gains
  only the `-x` line. It gets no new attribution (D1).
- Every commit is signed normally. Never pass `--no-gpg-sign` or
  `-c commit.gpgsign=false`. A signing failure stops the task and is reported.
- Recovered content is carried verbatim, and the `justfile` conflict is its only edit
  (D1, D2). New code lands only in the reconciliation commit.
- Each commit this plan authors ends with exactly these two lines:
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01XJQu22Bg2fayzv7KNKKbaA`.
- No closed set widens. Check ids, reason codes, repair ids, purposes,
  `CODE_STAGES`, `STAGE_ORDER` and the report schema stay unchanged (D5, D6).
- A failed check carries at most 8 fact keys (#122 D9). Authored values enter
  `facts` only through `bound_fact` or `bound_facts` (#122 D30). A suppressed check
  carries exactly `suppressed_by`.
- No `just switch`, no deploy, no shim, no `CLAUDE.md` edit (D8). No #121 design or
  plan document, and no Task 4–8 code or suite (D3).

## Test seams

These are all existing seams (spec "Test seams"), and a task that needs another seam
is a plan bug:
- the resolver CLI, run as a subprocess under a temporary `HOME` (`install_home`,
  #121 D23);
- the conformance CLI, run as a subprocess under `HERMETIC_ENV` or `platform_env`,
  with the platform installed (#122 D16, D35; D7);
- `conformance validate-report`, run as a subprocess (`ReportAssertions.assert_validates`);
- the S3 in-process seams (`load_module()` + `main([...])`), with `HOME` pinned by
  `PlatformHome` (D7);
- the built generation's `home-manager-files` tree used as `HOME` (D9, D10).

## Delivery estimate and boundaries

These figures are estimates, measured on a scratch replay of the picks and a
prototype of Task 2. The final bytes come from the packager.
- **Changed files:** about 15. That is the 9 recovered files, 4 conformance files,
  the spec and this plan (the root and 2 members).
- **Review package** (`git diff -U10`, whole-file first-fit, caps 524,288 total /
  8 members / 65,536 per member):
  - the recovered slice is about 177 KB, and its largest file is
    `scripts/resolve-project.py` at about 50 KB;
  - the reconciliation is about 26–32 KB, the spec about 23 KB and the plan about
    44 KB;
  - a dry run of `review-package` over a scratch branch was `complete`. That branch
    held the picks, the Task 2 prototype, the spec and this plan. The package came
    to 278,217 bytes, with `file_count` 6 (5 shards and the manifest) and
    `largest_member_bytes` 62,738;
  - expect about 270–290 KB in 5–6 shards, which is about 53% of the aggregate cap
    and leaves 2 free member slots.
- **Growth risk:** first-fit packed one shard to 62,738 bytes. Packing is by whole
  file, so a file that does not fit opens another shard, and no single file's diff
  exceeds about 50 KB.
  `resolve-project.py` does not change after Task 1, and
  `tests/test_conformance.py` grows by about 10 KB.
- **Slices:** nothing smaller can ship on its own. Task 1 alone leaves the
  conformance suites red (D1), so both tasks ship in one PR. sdd's cumulative
  delivery gate measures the real package after each task. If that gate ever
  reports `decompose_required`, stop and escalate instead of trimming recovered
  code (D2).
- **Delivery:**
  - After ship-issue's sync with `origin/main`, re-run Task 2's Step 6 so the Demo
    is proven on a main-current head (D10).
  - The PR body and the closing comment must state that `just switch` on each host
    is the post-merge activation step. Until the switch, the deployed resolver
    refuses the new contract, and after it a pre-slice checkout refuses until it
    merges `main` (D8).

## Task index

Task 1 — Replay the nine reviewed Task 1-3 commits with provenance — `.agents/project.json`, `home/common/agent-skills/default.nix`, `home/common/agent-skills/platform-manifest.json`, `home/common/agent-skills/scripts/agent_platform.py`, `home/common/agent-skills/scripts/resolve-project.py`, `home/common/agent-skills/tests/test_resolve_project.py`, `home/common/agent-skills/tests/test_resolve_platform.py`, `home/common/agent-skills/tests/test_resolve_platform_status.py`, `justfile` — full — [task-1.md](2026-09-23-issue-147-platform-manifest-status.tasks/task-1.md)
Task 2 — Reconcile the conformance ladder and publish the Demo facts — `home/common/agent-skills/scripts/conformance-checks.py`, `home/common/agent-skills/tests/conformance_test_support.py`, `home/common/agent-skills/tests/test_conformance.py`, `home/common/agent-skills/tests/test_conformance_registry.py` — full — [task-2.md](2026-09-23-issue-147-platform-manifest-status.tasks/task-2.md)

## Decisions

The spec's ledger holds every decision. Task 1 rests on D1–D3. Task 2 rests on
D4–D7, D9, D10 and D11. Delivery rests on D8. Planning added two rows: D10 (the
assertions of the built-generation run) and D11 (the sources of the suite fixtures'
facts).

## Standards review provenance

A Codex plan review ran isolated and read-only (`gpt-6-astra` through the
`codex-reviewer` bridge; the bridge reported no job id). It had no configured
focus, used base `4f74c47742b4dcebd37edb2e49a4cc227cc53238`, and reviewed plan
commit `1ee411c`. It raised 0 Blocking, 1 Should-fix and no actionable Discussion.
The Should-fix was checked against the live package and accepted: Task 2 gains
`test_the_installed_schema_set_decides_schema_support`, which proves that schema
support comes from the installed manifest's set (D4, D6), and its expected counts
are updated. 0 findings were rejected or deferred, and no fallback was used. The
reviewer's transcript is not copied here.

---
