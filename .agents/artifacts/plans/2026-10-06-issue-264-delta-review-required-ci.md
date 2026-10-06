# Issue 264 Delta Review and Required-Only CI Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Ship reviews only what sdd's final review did not see, and its CI wait blocks only on required checks while it reports the advisory ones (https://github.com/fagenorn/nix-config/issues/264).

**Architecture:** A new read-only decision helper, `agent_tools.review_range` (`review-range`), takes the final-review head and the post-sync ship head and returns `delta`, `empty` or `full` as one JSON object. It builds a synced-equivalent base when the path carries sync merges and measures that range with `diff_scope.measure`. Skill prose then pins what `head_sha` means (sdd → handoff), routes Phase 5's existing two-axis review over the range the helper selected, and switches Phase 6 to `gh pr checks --required` with an all-checks fallback and an advisory listing in the ship summary's notes. The [spec](../specs/2026-10-06-issue-264-delta-review-required-ci-design.md) owns the design and the decision ledger D1–D12.

**Tech stack:** Python 3 standard library, unittest, Git plumbing (`merge-tree --write-tree`, `commit-tree`, `rev-list --first-parent`), Nix (`lib/agent-tools.nix`), just, Markdown skill prose with Python contract tests.

## Global Constraints

- Work only in `/Users/anis/tmp/nix-config/.worktrees/worktree-issue-264-orchestrated` (branch `worktree-issue-264-orchestrated`). Never touch the primary checkout `/Users/anis/tmp/nix-config`. `BASE` = `40fa9c7` (origin/main at planning time).
- Commits go through `launch-commit --repo-root /Users/anis/tmp/nix-config --run-id run-20261006-261-262-263-264-265 --worker-id <your worker id> -- <git commit args>`, run in the worktree after `git add`. They are SSH-signed (never disable signing), with subjects of 64 bytes or fewer in the style `feat(review-range): … (#264)`, and end with the lines `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01QpGEgn23dNP1QXn2of1cto`.
- New helper code follows `docs/standards/agent-helpers.md`: a module of `agent_tools` under `python/`, one command-table row, a thin argv shell over importable functions, no `sys.path`/`importlib`/`__file__`, and tests that run `python -m agent_tools.review_range`.
- No schema changes: the sdd report, legacy ship-handoff, `ship-handoff/v2`, `ship-summary` and `ship-summary/v2` validators keep their exact key sets (per D1, D7).
- Out of scope, never edited: `home/common/claude-code/lifecycle_guard.py`, `.github/branch-protection.json`, `.github/workflows/ci.yaml`, `ship-release/SKILL.md`, from-issue's inline no-ship-issue fallback (`ship-handoff.md`'s "Then wait for CI (`<tracker-cli> pr checks --watch`)" paragraph), and sdd's review mechanics (per D9 and the spec's Out of scope).
- The `ship-issue-merge-delta-review` dispatch marker and its call line in `ship-issue/SKILL.md` stay byte-identical, because `home/common/agent-skills/model-matrix.json` pins them; so do the other ship-issue dispatch markers and call lines (per D4, D11).
- The gate thresholds have one home: the Phase-5 bullet in `ship-issue/SKILL.md`, spelled `≤1,000 product lines AND ≤20 product files` and passed as `--max-lines 1000 --max-files 20`. The helper carries no threshold default (per D2).
- **Instruction-load ceilings.** `home/common/agent-skills/instruction-load.json`'s `ceiling_bytes` hold each profile's hot bytes with zero slack. A task that grows a hot member raises exactly the breached `(profile, host)` ceilings to the measured value, in its own commit, and appends to that profile's `note` one sentence `Ceiling raised for #264: <what grew> (#155 D10).` Measure with:

```bash
PYTHONPATH="$PWD/python" python3 - <<'PY'
from pathlib import Path
from agent_tools import instruction_load as il
read = il.tree_reader(Path("."))
model = il.load_model(read(il.MODEL_PATH))
measured = il.measure(model, read)
print("\n".join(il.over_ceiling(model, measured)) or "NO-BREACH")
for profile in model["profiles"]:
    for host in profile["hosts"]:
        print(profile["id"], host, measured["profiles"][profile["id"]][host]["hot"]["bytes"], profile["ceiling_bytes"][host])
PY
```

- Payload discipline (writing-plans): targeted `rg` and bounded reads; summarize test output to the `Ran N tests` / `OK` / failing lines; write long logs to `${TMPDIR:-/tmp}` and pass paths. Every command that may run past 2 minutes runs in the foreground under an explicit `timeout`; never background work.

## Test seams

- Seam 1: `python -m agent_tools.review_range` over scratch git repositories in `tests/test_review_range.py` (TemporaryDirectory, no network), asserting the parsed stdout object and exit code. Pure functions may also be imported.
- Seam 2: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` contract tests over skill prose and `ship-issue/evals/evals.json` eval 1, using its `section`, `normalized` and `assert_ordered` helpers and the `GATE_LINE_BOUNDARY`/`GATE_FILE_BOUNDARY` constants.
- Seam 3: the installed launcher, through the existing `tests/test_agent_tools_launchers.py` and `just build` (the command-table assertion and import check).
- Run a module as `PYTHONPATH="$PWD/python" python3 -m unittest <path>` from the worktree root; one test as `PYTHONPATH="$PWD/python" python3 -m unittest <path> -k <name>`.

## Delivery estimate and boundaries

- Estimate: about 14 changed files. One new module of roughly 250 lines and its test file of roughly 350 lines. Small edits to `lib/agent-tools.nix`, the `justfile` and two test vocabularies. Prose edits to `ship-issue/{SKILL,REVIEW,CI-MERGE}.md`, `ship-issue/evals/evals.json`, `from-issue/{SKILL,ship-handoff}.md` and `sdd/{SKILL,final-review}.md`. Contract-test additions, and ceiling bumps in `instruction-load.json`. All figures are estimates.
- Tasks 1–2 (the helper) and Task 3 (the `head_sha` meaning) can each ship alone. Task 4 depends on Tasks 1–3. Task 5 is independent of Tasks 1–4 except that it shares files with Task 4, so it runs after it.

## Task index

Task 1 — review-range decision helper — python/agent_tools/review_range.py, tests/test_review_range.py — full — [task-1.md](2026-10-06-issue-264-delta-review-required-ci.tasks/task-1.md)
Task 2 — Deploy the review-range command — lib/agent-tools.nix, justfile, tests/test_agent_tools_launchers.py, home/common/agent-skills/tests/test_shell_example_contracts.py — full — [task-2.md](2026-10-06-issue-264-delta-review-required-ci.tasks/task-2.md)
Task 3 — Pin head_sha as the final-review head — home/common/agent-skills/skills/sdd/SKILL.md, home/common/agent-skills/skills/sdd/final-review.md, home/common/agent-skills/skills/from-issue/ship-handoff.md, home/common/agent-skills/skills/from-issue/SKILL.md, home/common/agent-skills/tests/test_workflow_skill_contracts.py, home/common/agent-skills/instruction-load.json — full — [task-3.md](2026-10-06-issue-264-delta-review-required-ci.tasks/task-3.md)
Task 4 — Phase 5 reviews the selected range — home/common/agent-skills/skills/ship-issue/SKILL.md, home/common/agent-skills/skills/ship-issue/REVIEW.md, home/common/agent-skills/skills/ship-issue/evals/evals.json, home/common/agent-skills/skills/from-issue/ship-handoff.md, home/common/agent-skills/tests/test_workflow_skill_contracts.py, home/common/agent-skills/instruction-load.json — full — [task-4.md](2026-10-06-issue-264-delta-review-required-ci.tasks/task-4.md)
Task 5 — Phase 6 waits on required checks only — home/common/agent-skills/skills/ship-issue/SKILL.md, home/common/agent-skills/skills/ship-issue/CI-MERGE.md, home/common/agent-skills/skills/ship-issue/evals/evals.json, home/common/agent-skills/skills/from-issue/ship-handoff.md, home/common/agent-skills/tests/test_workflow_skill_contracts.py, home/common/agent-skills/instruction-load.json — full — [task-5.md](2026-10-06-issue-264-delta-review-required-ci.tasks/task-5.md)

## Decisions

Task 1 rests on D2, D3, D10 and D12. Task 2 rests on D2. Task 3 rests on D1 and D10. Task 4 rests on D4, D5, D10, D11 and D12. Task 5 rests on D6, D7, D8, D9 and D11. The spec's `## Decision ledger` holds every row, including the planning rows D11 and D12.

---

## Standards review provenance

- Reviewer: Codex (`codex-plan-review`, gpt-6-astra/xhigh), isolated read-only fresh thread; no fallback.
- Base SHA: 40fa9c7db3863a49d31960a71f3c5c1c479b9377; reviewed plan commit a92df9a.
- Findings: 2 accepted, 0 rejected, 0 deferred. PR264-01 (Blocking): focused-test commands now use an absolute `PYTHONPATH="$PWD/python"`, and Task 1's `git_env()` absolutizes inherited `PYTHONPATH` entries for helper subprocesses run from temporary directories. PR264-02 (Should fix): every verification command piped into `tail` now runs under `set -o pipefail`.
