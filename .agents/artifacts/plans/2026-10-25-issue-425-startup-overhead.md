# Subagent Start-up Trim Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `mechanic` and `reviewer-lite` subagents start without the `CLAUDE.md` files, the generated settings hide twelve skills from the model's listing, and a new `claude-orchestrate` command starts Claude Code with claude.ai connectors off, with before/after evidence that the start-up bill shrank and `from-issue` eval 1 still passes.

**Architecture:** Task 1 adds `omitClaudeMd: true` to the two brief-driven agent definitions and pays for the line inside each file. Task 2 adds `skillOverrides` to the `settings` attrset in `home/common/claude-code/default.nix` and opens a new installed-tier test module, `tests/test_claude_code_installed.py`, fed the built settings artifact by `just agent-installed-skill-tests`. Task 3 adds `claude-orchestrate` to `claudeWithAccounts`' `bin` and extends the same module and recipe with launcher tests fed the built Claude package. Tasks 4 and 5 measure AC3 and AC4 on mbp from the build output, without activation, and write the acceptance record.

**Tech stack:** Nix (home-manager module, `pkgs.symlinkJoin` `postBuild`), POSIX shell launchers, Python 3.13 standard library `unittest`, Just, Claude Code 2.1.302 (`claude -p`), `agent-costs --report cache` (issue 421).

Spec: `.agents/artifacts/specs/2026-10-25-issue-425-startup-overhead-design.md` (this plan appends ledger rows D9–D10). Its `## Decision ledger` rows are cited by ID. Issue: https://github.com/fagenorn/nix-config/issues/425.

## Global Constraints

- Base `04a396606d69fe6b720596c20846934b040abaa6` (`origin/main` at planning). Tasks land in index order, each on the one before it.
- Out of scope and unchanged: `CLAUDE.md`, `home/common/agent-guidance/AGENTS.md`, `home/common/claude-code/skills/orchestrate-issues/SKILL.md`, `home/common/agent-skills/evals/run-eval.sh`, `home/common/claude-code/lifecycle_guard.py`, every agent `tools:` line, `enabledPlugins`, `home/linux/claude-local/` (D4, D8). No tool allowlist or denylist anywhere.
- No ceiling in `home/common/agent-skills/instruction-load.json` is raised; `just agent-instruction-budget` must end in `check: pass` without `--raise-label` (D5). A ceiling left more than 5 % loose would be lowered (D5); Task 1's texts leave none loose, so the file is not edited.
- Never run `just switch`, never edit `~/.claude/settings.json` or anything under `~/.claude-accounts`; evidence comes from the build output (D7).
- Comments, docstrings and README sentences describe the code as it behaves at that task's commit; write "issue 425", never a bare `#425`, in code and docs; no `TODO` or `FIXME`; no mutable default argument.
- Every long command, each test and build command included, runs in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>` with an explicit timeout above its duration. Commits go through `launch-commit … -- <git commit args>`, signed, ending with the session's trailers. Scratch files and sandboxes live under the root `launch-scope scratch …` prints.
- **Matrix tests** (timeout 600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_agent_model_matrix.py home/common/agent-skills/tests/test_dispatch_contracts.py 2>&1 | tail -4'`.
- **Installed tier** (timeout 3600 s; it builds mbp first, 68 s at base with a warm store): `bash -c 'set -o pipefail; just agent-installed-skill-tests 2>&1 | grep -E "^(FAIL|ERROR):|^Ran |^OK|^FAILED|expected exactly" | tail -15'`. At base it prints `Ran 228 tests …` and `OK (skipped=1)`.
- **Budget gate** (timeout 600 s): `bash -c 'set -o pipefail; just agent-instruction-budget 2>&1 | tail -3'`; passing ends in `check: pass`.
- **Build** (timeout 3600 s): `bash -c 'set -o pipefail; just build mbp 2>&1 | tail -3'`.
- Final gate (sdd, once on the final head): `just build` and `just agent-workflow-tests` (timeout 3600 s each). The anis-desktop evaluation is CI's required `Nix Eval` job on the PR, not a local command (D10).

## Test seams

- Agent frontmatter through `test_agent_model_matrix.py`'s `frontmatter()` helper over `home/common/claude-code/agents/*.md`, run by `just agent-workflow-tests` (D3).
- The built settings artifact and the built Claude package, discovered in `./result`'s closure by store-path suffix (one each) by `just agent-installed-skill-tests` and read by `tests/test_claude_code_installed.py`; launchers judged by the argv and environment a `CLAUDE_BIN` stub records (D6).
- Build and gates: `just build mbp`, `just agent-instruction-budget`, CI `Nix Eval` (D5, D10).
- Evidence only: a sandbox `claude -p` harness read through `agent-costs --report cache` and `agent_cache_report.scan_transcript` (Task 4, D7, D9); the eval's tree mode (Task 5, D7).

## Delivery estimate and boundaries

Estimates only: seven changed files plus the acceptance record, one eval-history line, this plan and the spec ledger. The two agent definitions shrink by 3 and 4 bytes net; `tests/test_agent_model_matrix.py` about +8 lines; `home/common/claude-code/default.nix` about +25 lines; `justfile` about +15 lines; the new `tests/test_claude_code_installed.py` about 120 lines; `home/common/claude-code/README.md` two new paragraphs. One review package. Task 1 is independently deliverable, and so is Task 2; Task 3 builds on Task 2's test module and recipe; Tasks 4 and 5 need all three.

## Task index

Task 1 — Brief-driven agents omit CLAUDE.md, paid for in place — `home/common/claude-code/agents/mechanic.md`, `home/common/claude-code/agents/reviewer-lite.md`, `home/common/agent-skills/tests/test_agent_model_matrix.py` — full — [task-1.md](2026-10-25-issue-425-startup-overhead.tasks/task-1.md)
Task 2 — Hidden skills in the generated settings and the installed settings test — `home/common/claude-code/default.nix`, `tests/test_claude_code_installed.py`, `justfile`, `home/common/claude-code/README.md` — full — [task-2.md](2026-10-25-issue-425-startup-overhead.tasks/task-2.md)
Task 3 — The `claude-orchestrate` launcher and its installed tests — `home/common/claude-code/default.nix`, `tests/test_claude_code_installed.py`, `justfile`, `home/common/claude-code/README.md` — full — [task-3.md](2026-10-25-issue-425-startup-overhead.tasks/task-3.md)
Task 4 — AC3 start-up evidence and the acceptance record — `.agents/artifacts/plans/2026-10-25-issue-425-startup-overhead.acceptance.md` — low-risk — [task-4.md](2026-10-25-issue-425-startup-overhead.tasks/task-4.md)
Task 5 — AC4 eval evidence — `.agents/artifacts/plans/2026-10-25-issue-425-startup-overhead.acceptance.md`, `home/common/agent-skills/evals/results/results.jsonl` — low-risk — [task-5.md](2026-10-25-issue-425-startup-overhead.tasks/task-5.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | `home/common/agent-skills/tests/test_agent_model_matrix.py::AgentModelMatrixTest::test_only_the_brief_driven_agents_omit_claude_md` (`omitClaudeMd` is `true` for `mechanic` and `reviewer-lite`, absent for `implementer` and `reviewer`), run by `just agent-workflow-tests` in sdd's final gate. |
| AC2 | code | Task 3 | `tests/test_claude_code_installed.py`: `ClaudeSettingsInstalledTest::test_skill_overrides_hide_exactly_the_listed_skills` (the artifact `just show-claude-settings` prints), `ClaudeLaunchersInstalledTest::test_claude_orchestrate_turns_claude_ai_connectors_off` and `::test_plain_claude_leaves_claude_ai_connectors_alone`, run by `just agent-installed-skill-tests`, which builds mbp first; the anis-desktop evaluation is the PR's required `Nix Eval` job (D10). |
| AC3 | evidence | Task 4 | On mbp at the final code head, no activation: the Task 4 harness run before (deployed `claude`, deployed settings, base agents) and after (built `claude-orchestrate`, `--settings` the built file, branch agents), each read with `just agent-costs --report cache --projects-dir <that run's isolated copy> --events-since <start> --events-before <end>` and `scan_transcript`; thresholds: `reviewer-lite` first-request write+read at least 2,500 tokens smaller, `mechanic` `skill_listing` at least 30 % smaller, zero `claude.ai …` names in the after run's `mcp_instructions_delta` records. Acceptance-record row `AC3`; a void run is no measurement and nothing is tuned (D7, D9). |
| AC4 | evidence | Task 5 | On mbp at the final code head: `CLAUDE_ACCOUNT=<the caller's account> EVAL_TREE=<worktree> EVAL_SETTINGS=<built settings> ENABLE_CLAUDEAI_MCP_SERVERS=false just evals from-issue 1`; threshold: `VERDICT: PASS` and exit 0. Acceptance-record row `AC4` (D7). |

Nothing is owner-run at delivery. The one check outside the worktree is the anis-desktop evaluation, which CI's `Nix Eval` job runs on the PR (D10).

## Decisions

- `omitClaudeMd` on `mechanic` and `reviewer-lite` only, pinned in the matrix test, per D3; the line paid for in place, per D5 (Task 1).
- The twelve `skillOverrides` keys and value per D1; the kept skill-creator and unchanged `enabledPlugins` per D2 (Task 2).
- The launcher shape per D4 (Task 3); the installed-tier seam per D6 (Tasks 2, 3); docs per D8 (Tasks 2, 3).
- The anis-desktop evaluation left to CI per D10 (Task 3, AC2).
- Evidence before activation per D7; the AC3 harness, its isolation and its void rules per D9 (Tasks 4, 5).

## Standards review provenance

- Reviewer: Codex (`codex-companion task --fresh --reviewer plan-review`, gpt-6-astra, xhigh), isolated read-only mode, no focus; base `04a396606d69fe6b720596c20846934b040abaa6`; no fallback.
- Accepted 3, rejected 0, deferred 0: R425-01 (Blocking — Task 3 Step 4 compares the padded BSD `wc -l` output numerically), R425-02 (Should fix — Task 5 passes and records `CLAUDE_ACCOUNT`, read as in Task 4), R425-03 (Should fix — Task 3 also corrects the README's "execs the pinned binary" sentence, since `run` waits on `claude`).

---
