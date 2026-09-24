# Recover #121 Tasks 4–6: Adoption Plan, Apply and Verify Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Land the reviewed #121 Task 4–6 slice on `main` by replaying its nine
commits with their provenance. The slice is `adopt-project` with `plan`, `apply`
and `verify [--register]`, plus the fleet-registry writer. Then prove it on the
built generation.

**Architecture:** Nine `git cherry-pick -x` commits carry the slice verbatim:
five adoption modules, four suites, the registry-writer hunk in
`agent_platform.py`, and the `default.nix` and `justfile` wiring. Pick 1's
conflict resolves as a union (D1, D2). No reconciliation commit is planned (D3).
The slice is then proven by the focused suites, the workflow suite, `just build`
and the nine-step run against the built generation under a scratch `HOME`
(D4, D5).

**Tech stack:** Python 3 standard library (`unittest`, `subprocess`), git
(cherry-pick, patch-id, worktrees), home-manager file publication in
`home/common/agent-skills/default.nix`, `just`, Nix.

**Authority:** the spec `.claude/specs/2026-09-24-issue-148-adoption-plan-apply-verify-design.md`
and its `## Decision ledger` (D1–D10). The spec also carries the recovered-commit
table and the digest of the #121 IDs that the recovered code cites.

## Global Constraints

- The base is `origin/main` `185cc1a46668faf960be605734b6136d9234e245`. The
  retained branch `worktree-issue-121-adoption-v1` (tip `fe85677c`) and its
  worktree `.worktrees/worktree-issue-121-adoption-v1` are read-only: `git show`,
  `git log` and `git cat-file` only. #149 still reads them.
- Replay exactly these commits, in this order:
  `08c9caf0 72b47ae2 c31d64e1 4fdbb8c6 36275eb6 d70a08ef 03c08ffe 44afaa06 11b1e9bc`.
  No other retained commit is replayed, and none of the seven docs-only commits
  is replayed (spec "Recovered commits").
- A pick keeps its original message, trailers and author, and gains only the
  `-x` line. It gets no new attribution (D1).
- Every commit is signed normally. Never pass `--no-gpg-sign` or
  `-c commit.gpgsign=false`. A signing failure stops the task and is reported.
- Recovered content is carried verbatim, and the pick-1 union is its only edit
  (D1, D2). New code lands only as a D3 fix commit, within D10's bounds.
- Each commit this plan authors ends with exactly these two lines:
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01XJQu22Bg2fayzv7KNKKbaA`.
- Outside `.claude/`, the branch changes exactly the twelve slice files named in
  Task 1. There is no Task 7–8 path (`.agents/project.json`, `.gitignore`,
  `.out-of-scope/**`) and no #121 design or plan document (D2).
- No closed vocabulary widens: `ADOPT_ERROR_CODES`, the outcomes, plan states,
  operation kinds, verify results, and every conformance check id and purpose
  stay as recovered (D6, D7). There is no new `adopt-project` surface.
- No `just switch`, no deploy, no shim, no `CLAUDE.md` edit (D8). No change to
  `review-package` or the feasibility tooling.
- The main-based run never writes the operator's `~/.agents/state`. It only
  hashes the registry and `adopt/` there, before and after (D4, D5 step 9). Its
  git commands run with `GIT_CONFIG_GLOBAL` and `GIT_CONFIG_SYSTEM` set to
  `/dev/null`.

## Test seams

These are the spec's seams (spec "Test seams"), and a task that needs another
seam is a plan bug:
- `adopt-project` as a subprocess under a temporary `HOME` holding the libraries,
  a fixture manifest and an executable resolver copy (#121 D23), with real
  `git init` fixtures;
- the resolver CLI as a subprocess under that same `HOME`, where the two
  binaries meet over the registry;
- the in-process `adopt_failure` wrapper seam (resolver D23);
- the built generation, reached through the D4 scratch `HOME`, as the Nix
  publication seam (#147 D9);
- `conformance run` and `validate-report` as subprocesses.

## Delivery estimate and boundaries

These figures are estimates from a scratch replay of the nine picks on the base.
The final bytes come from the packager.
- **Changed files:** 15. That is the 12 slice files, the spec, and this plan's
  root and one member.
- **Review package** (`git diff -U10`, whole-file first-fit, caps 524,288 total,
  8 members and 65,536 per member):
  - the slice's diff is about 287 KB across 12 files (+6,258/−4 lines);
  - the largest file diff is `tests/test_adopt_project.py` at about 58.9 KB, then
    `scripts/adopt-project.py` at about 39 KB;
  - the spec's probe packaged the picks as 6 members (about 289 KB, largest
    member 63,235 bytes), and the spec and plan add about 51 KB (D9).
- **Growth risk:** packing is by whole file, and `test_adopt_project.py`'s diff
  is about 6.6 KB under the 65,536-byte member cap on its own. That is why D10
  keeps a D3 fix's failing case out of that file.
- **Slices:** nothing smaller ships on its own (D10), so the slice is one task and
  one PR.
- **Package feasibility (AC6):** sdd's cumulative delivery gate runs
  `review-package` over the whole range after Task 1 and before the final
  review (D9). Implementers never run `review-package` themselves, because a
  second publication of the same range collides with that gate. If the gate
  reports `decompose_required`, stop and escalate: the documents are trimmed,
  never the recovered code (D9).
- **Delivery:**
  - After ship-issue's sync with `origin/main`, re-run Task 1's Step 7, so that
    the run is proven on a main-current head (D5).
  - The PR body and the closing comment name `just switch` on each host as the
    post-merge activation step (D8).

## Task index

Task 1 — Replay the nine Task 4–6 commits and prove them on the built generation — `home/common/agent-skills/default.nix`, `home/common/agent-skills/scripts/adopt-project.py`, `home/common/agent-skills/scripts/adopt_inspection.py`, `home/common/agent-skills/scripts/adopt_planning.py`, `home/common/agent-skills/scripts/adopt_apply.py`, `home/common/agent-skills/scripts/adopt_verify.py`, `home/common/agent-skills/scripts/agent_platform.py`, `home/common/agent-skills/tests/test_adopt_project.py`, `home/common/agent-skills/tests/test_adopt_project_boundaries.py`, `home/common/agent-skills/tests/test_adopt_apply.py`, `home/common/agent-skills/tests/test_adopt_verify.py`, `justfile` — full — [task-1.md](2026-09-24-issue-148-adoption-plan-apply-verify.tasks/task-1.md)

## Decisions

The spec's ledger holds every decision. Task 1 rests on D1–D5 and D10. The
fleet and conformance boundary is D6 and D7, and delivery rests on D8 and D9.
Planning added one row: D10 (one task, and the bounds on a D3 fix).

---
