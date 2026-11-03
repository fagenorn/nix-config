# Cheap Use-Time Row Check Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `guard-policy derive --repository elevenyellow/nodocom` (the guard's row check) finishes in a median of at most 5 s on `mbp` by reading `origin` cheaply, while staying the compiler's own full proof, so the guard confirms Nodo's derived row and allows a PR into `dev`.

**Architecture:** The shared read of `origin` (`adopt_verify.remote_source`) keeps its one branch-selection rule and gains a reader parameter. The guard's compiler passes a cheap reader that pins each branch at its listed commit with no fetch when the object store already holds it, and exports only the contract and its projection files (new `agent_tools.contract_export`, path list from `resolve_project.projection_paths`) with no tree inventory. `adopt-project` keeps the default reader, and the guard file is untouched.

**Tech stack:** Python 3 standard library (`agent_tools` under `python/`), git plumbing (`ls-remote`, `cat-file`, `ls-tree`), `unittest` over `tests/guard_policy_world.py` (local bare `origin`, `git`/`gh` shims), Nix (`just build`).

Spec: `.agents/artifacts/specs/2026-10-13-issue-385-cheap-row-check-design.md`. Its `## Decision ledger` rows D1–D12 are cited by ID. Issue: https://github.com/fagenorn/nix-config/issues/385.

## Global Constraints

- Base: `6958c11645165f1a725ac73a7dcc87c9ef617d03` (`origin/main` at planning). Tasks land in index order; a later task assumes every earlier one.
- Unchanged: `home/common/claude-code/lifecycle_guard.py`, `home/common/claude-code/default.nix`, `tests/test_claude_permission_guard.py`, the guard's bounds (`--derive-timeout-seconds` 15, 27 s deadline), the trust split, the base policy, the compiled-policy and `derive` report schemas, `adopt-project` behaviour, reports and writes (D1, D5).
- `adopt_verify` and every `adopt_*` module never import `resolve_project` (issue 148 D26); `contract_export` may. `guard_policy` stays a thin command module (`docs/standards/agent-helpers.md` rule 2); new helper code lives in `python/agent_tools/`.
- No test measures time, contacts a network remote, reads the host fleet registry or reads `~/.agents/state/guard/policy.json` (D7). Only Task 3 touches the host's Nodo checkout, and only through the built row check and guard.
- Never run `just switch`. Nothing outside Task 3's AC2 restoration step runs the installed `claude-guard-policy`.
- Prose that lands in code or documentation describes the code as it behaves at that task's commit. Where a task lists facts instead of a sentence, write the sentence from the implemented code. Use full issue URLs or the words "issue 385", never a bare `#385`. No edit to `CLAUDE.md`, `AGENTS.md` or `.agents/instructions/` (instruction budget).
- Every long command, each test command included, runs in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>` with an explicit timeout above its duration. Commits go through `launch-commit … -- <git commit args>`, signed, with the session's trailers. Scratch files live under `launch-scope scratch`'s root.
- Python suites run as `env PYTHONPATH="$PWD/python" python3 -m unittest <test file> [-k <pattern>]` (timeout 900 s; 1800 s for `home/common/agent-skills/tests/test_adopt_verify.py`). A `Run:` line piped into `tail` runs under `set -o pipefail`. Judge it by the command's own exit status and the expected text.
- `just build` (timeout 3600 s) evaluates the git tree, so `git add` every new file first. The guard suite runs against that build and is in no `just` recipe. Its one invocation (timeout 1200 s) is called **the guard-suite invocation** below:

  ```bash
  set -e -o pipefail
  just build
  REQ=$(nix-store --query --requisites ./result)
  CLAUDE_SETTINGS_PATH=$(printf '%s\n' "$REQ" | grep -- '-claude-code-settings\.json$') \
  CLAUDE_GUARD_BASE_POLICY_PATH=$(printf '%s\n' "$REQ" | grep -- '-claude-bash-lifecycle-guard-base-policy\.json$') \
  PYTHONPATH="$PWD/python" python3 -m unittest tests/test_claude_permission_guard.py 2>&1 | tail -4
  ```

- Final gate, once on the final head: `just agent-workflow-tests` (timeout 3600 s), `just build` (timeout 3600 s) and the guard-suite invocation, which must print `OK`. Task 3 runs it.

## Test seams

- The compiler command, `python -m agent_tools.guard_policy derive|compile`, over `tests/guard_policy_world.py` (`GuardPolicyWorld.derive`, `.compile`, `.policy`, and the new `.advance`), asserting on reports, rows and the checkout's refs (issue 126 D10, issue 377 D8).
- The module function `contract_export.export_contract` on a world checkout, with `guard_policy.resolver` run in process on its output and on `adopt_inspection.export_commit`'s output (`ContractExportTest` in `tests/test_guard_policy.py`; D11). It is the one direct seam of this change.
- The adopt suites, unchanged and green: they show that `--register` kept the default reader.
- The built guard suite (`tests/test_claude_permission_guard.py`) and its round trip, unchanged: it runs the real `derive` over the fixture world, so it exercises the cheap reader.

## Delivery estimate and boundaries

Estimate: 9 changed files plus the spec and the acceptance record. 5 production modules (`resolve_project.py`, new `contract_export.py`, `adopt_inspection.py`, `adopt_verify.py`, `guard_policy.py`), 2 test files, 2 READMEs. About +220 production lines and +330 test lines, one review package. Aggregate-growth risk (estimate): `tests/test_guard_policy.py`, 477 lines at base and about 780 after. Task 1 is additive and deliverable alone, because nothing calls the export yet. Task 2 switches the proof to the cheap read. Task 3 is host evidence and the measured figures.

## Task index

Task 1 — Sparse contract export and the resolver's projection paths — `python/agent_tools/resolve_project.py`, `python/agent_tools/adopt_inspection.py`, `python/agent_tools/contract_export.py`, `tests/test_guard_policy.py` — full — [task-1.md](2026-10-13-issue-385-cheap-row-check.tasks/task-1.md)
Task 2 — Listed-commit pin, the reader parameter and the cheap proof — `python/agent_tools/adopt_inspection.py`, `python/agent_tools/adopt_verify.py`, `python/agent_tools/guard_policy.py`, `tests/guard_policy_world.py`, `tests/test_guard_policy.py`, `python/README.md`, `home/common/claude-code/README.md` — full — [task-2.md](2026-10-13-issue-385-cheap-row-check.tasks/task-2.md)
Task 3 — Host acceptance: timing series, dry adjudication, measured cost and final gate — `home/common/claude-code/README.md`, `.agents/artifacts/plans/2026-10-13-issue-385-cheap-row-check.acceptance.md` — full — [task-3.md](2026-10-13-issue-385-cheap-row-check.tasks/task-3.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | evidence (classified) | Task 3 | 10 consecutive runs of the built `claude-guard-row-check --repository elevenyellow/nodocom` on `mbp`, `GITHUB_TOKEN`/`GH_TOKEN` unset, registered checkout `/Users/anis/Projects/nodocom`. Threshold: median ≤ 5 s, no run > 10 s, every run exit 0 / `derived` / `main` / `dev` (D7). Acceptance-record row `AC1`. |
| AC2 | evidence (classified) | Task 3 | Dry adjudication by the built guard wrapper of a `PreToolUse` payload (`unset GITHUB_TOKEN && gh pr create --repo elevenyellow/nodocom --base dev --head <branch> --title "x" --body "y"`, `cwd` an existing Nodo worktree on `<branch>` ∉ {`main`, `dev`}). Threshold: exit 0 and empty stderr. Acceptance-record row `AC2`. |
| AC3 | code (classified) | Task 2 | Guard-suite invocation prints `OK`, with `test_a_compiled_policy_round_trips_through_the_guard` (forged row), `test_a_row_for_an_unregistered_repository_is_refused_at_use`, `test_a_row_whose_branches_differ_from_the_derivation_is_refused`, `test_a_row_beside_a_literal_integration_base_is_refused` and `test_a_bad_compiled_policy_contributes_no_row` unchanged; `tests/test_guard_policy.py` `ProjectRefusalTest` green, with the new `test_a_symlinked_projection_target_is_contract_unresolved`. |
| AC4 | evidence (classified) | Task 3 | `just build`, `just agent-workflow-tests` and the guard-suite invocation on the final head. Threshold: exit 0 each, with the guard suite printing `OK`. Acceptance-record row `AC4`. |

## Decisions

- Re-derivation stays the use-time check and the guard is untouched: per D1. Compile shares the read: per D6.
- Listed commit, fetch only when missing: per D2. Remote-tracking refs and evidence spelling: per D3.
- Sparse export, path list and mode rules: per D4. Read mechanics: per D10. Symlink divergence: per D9.
- Reader parameter, `inventory=None`, interfaces and test placement: per D5, D11.
- Target, evidence and fetch detection: per D7, D12. No knowledge surface: per D8.
- No lazy fetch on the cheap path: per D13. A separate batch parser from `adopt_links`: per D14.
- Planning added D9–D12 to the spec's ledger; the standards review added D13–D14.

## Standards review provenance

- Reviewer: Codex (`codex-companion task --fresh --reviewer plan-review`, isolated read-only), job `01a1350e-76a5-77d3-b74d-372e7b744c16`, base `6958c11645165f1a725ac73a7dcc87c9ef617d03`, no fallback.
- Accepted 4, rejected 0, deferred 0. Blocking: lazy fetch on the cheap reads, applied (D13; Tasks 1–2). Should fix: the duplicate batch reader, resolved by recording why it stays separate (D14); the AC1 script's uncaught run timeout, now recorded as a failed run with its process group killed (Task 3); two stale `adopt_verify` docstrings added to Task 2's prose list.

---
