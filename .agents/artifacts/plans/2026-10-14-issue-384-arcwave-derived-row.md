# Arcwave by Its Derived Row Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Remove the hand-written `fagenorn/arcwave` integration-base literal from the guard's store base policy, so `guard-policy compile` derives Arcwave's row (`main`/`dev`) from its registered contract and the guard judges Arcwave through that row.

**Architecture:** The base policy's `integrationBases` becomes an empty attrset that keeps its general comment (spec D1). No guard, compiler, row-check or schema code changes. Tests that relied on the store literal move to fixture base policies under neutral slugs (D2, D3), and the guard suite gains one Arcwave-shaped compile-and-judge round trip (D4). The host's compiled policy is evidenced by a scratch compile against the live registry; the post-switch read is a human step (D6).

**Tech stack:** Nix (home-manager module, `just build`), Python 3 `unittest` (`tests/test_claude_permission_guard.py` against the build, `tests/test_guard_policy.py` and `tests/guard_policy_world.py` from source).

Spec: `.agents/artifacts/specs/2026-10-14-issue-384-arcwave-derived-row-design.md`. Its `## Decision ledger` rows D1–D7 are cited by ID. Issue: https://github.com/fagenorn/nix-config/issues/384.

## Global Constraints

- Base: `0cc5768b` (`origin/main` at planning). Tasks land in index order; Task 2 assumes Task 1.
- Unchanged: `home/common/claude-code/lifecycle_guard.py`, everything under `python/agent_tools/`, both policy schemas, the `integration_bases` loader support, the adversarial table in `tests/test_claude_permission_guard.py`, `hosts/common/darwin-github-runners.nix`, Arcwave's repository and registry entry.
- No test reads the host fleet registry or `~/.agents/state/guard/policy.json`, or contacts a network remote. Only Task 2 reads the live registry, and only through a compile whose `--output` lies under the scratch root (D6).
- Never run `just switch`, the installed `claude-guard-policy`, or any command that writes `~/.agents/state/`.
- Prose that lands in code or documentation describes the code as it behaves at that task's commit. Use full issue URLs or the words "issue 384", never a bare `#384`. No edit to `CLAUDE.md`, `AGENTS.md` or `.agents/instructions/` (instruction budget).
- Every long command, each test command included, runs in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>` with an explicit timeout above its duration. Commits go through `launch-commit … -- <git commit args>`, signed, with the session's trailers. Scratch files live under `launch-scope scratch`'s root.
- `tests/test_guard_policy.py` runs as `set -o pipefail; env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_guard_policy.py 2>&1 | tail -4` (pipefail keeps the suite's exit status, not `tail`'s) (timeout 900 s). Neither it nor the guard suite is in `just agent-workflow-tests`.
- `just build` (timeout 3600 s) evaluates the git tree. The guard suite runs against that build. Its one invocation (timeout 1200 s; 3600 s when the build is cold) is called **the guard-suite invocation** below:

  ```bash
  set -e -o pipefail
  just build
  REQ=$(nix-store --query --requisites ./result)
  CLAUDE_SETTINGS_PATH=$(printf '%s\n' "$REQ" | grep -- '-claude-code-settings\.json$') \
  CLAUDE_GUARD_BASE_POLICY_PATH=$(printf '%s\n' "$REQ" | grep -- '-claude-bash-lifecycle-guard-base-policy\.json$') \
  PYTHONPATH="$PWD/python" python3 -m unittest tests/test_claude_permission_guard.py 2>&1 | tail -4
  ```

  A `-k <pattern>` may follow the test file for a focused run.
- Final gate, once on the final head: `just agent-workflow-tests` (timeout 3600 s), the guard-suite invocation and the `tests/test_guard_policy.py` run, each `OK`. Task 2 runs it.

## Test seams

- The built base policy, read by the guard suite through `CLAUDE_GUARD_BASE_POLICY_PATH` (`test_built_base_policy_holds_exactly_the_five_trusted_members`; D3).
- The guard executable fed a fixture base policy (`write_base`, `--base-policy`) and a fixture compiled policy (`write_policy`, `--policy`), with the fake `gh` (D2).
- The compiler from source over `tests/guard_policy_world.py` (`GuardPolicyWorld.project`, `.compile`, `.policy`, `.write_base`), and the guard judging with that world's compiled file and `GuardPolicyWorld.row_check()` (D4; prior art `test_a_compiled_policy_round_trips_through_the_guard`).

## Delivery estimate and boundaries

Estimate: 5 changed files plus the spec and the acceptance record. `default.nix` about −4/+3 lines, `README.md` one clause, `tests/test_claude_permission_guard.py` about +55 lines, `tests/guard_policy_world.py` and `tests/test_guard_policy.py` one line each. One review package. Aggregate-growth risk (estimate): `tests/test_claude_permission_guard.py`, 1807 lines at base and about 1860 after. Task 1 is the whole code change and deliverable alone; Task 2 is host evidence and the final gate.

## Task index

Task 1 — Drop the Arcwave literal and prove its derived row in the suites — `home/common/claude-code/default.nix`, `home/common/claude-code/README.md`, `tests/test_claude_permission_guard.py`, `tests/guard_policy_world.py`, `tests/test_guard_policy.py` — full — [task-1.md](2026-10-14-issue-384-arcwave-derived-row.tasks/task-1.md)
Task 2 — Host compile evidence, final gate and acceptance record — `.agents/artifacts/plans/2026-10-14-issue-384-arcwave-derived-row.acceptance.md` — full — [task-2.md](2026-10-14-issue-384-arcwave-derived-row.tasks/task-2.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | evidence (classified) | Task 2 | (a) After `just build`, the built `guard-policy compile` run against the live registry with `--base` the built base policy and `--output` under the scratch root; threshold: its report's `derived` lists `fagenorn/arcwave`, the output's row for it has `default_branch` `main` and `integration_branch` `dev`, and no `refused` entry names it (in particular no `literal_conflict`). (b) Post-switch human step, by the user: read `derived_repositories["fagenorn/arcwave"]` from `~/.agents/state/guard/policy.json` (D6, D7). Acceptance-record row `AC1`. |
| AC2 | code (classified) | Task 1 | Guard suite: new `test_an_arcwave_shaped_project_is_judged_by_its_compiled_row` (feature PR create into `dev`, feature merge into `dev`, green and red `dev` → `main` release merge, unrelated repository refused) and `test_a_row_beside_a_literal_integration_base_is_refused` on a fixture base, both green with the literal removed; the adversarial table green. |
| AC3 | code (classified) | Task 1 | Guard suite `test_built_base_policy_holds_exactly_the_five_trusted_members`: `integration_bases == {}` and `default.nix` contains no `fagenorn/arcwave` (D3). |
| AC4 | evidence (classified) | Task 2 | `just build`, `just agent-workflow-tests`, the guard-suite invocation and the `tests/test_guard_policy.py` run on the final head; threshold: exit 0 each, the two suites printing `OK`. Acceptance-record row `AC4`. |

## Decisions

- Empty literal set kept with its general comment: per D1. Fixture literals under neutral slugs and an empty world default: per D2.
- Exact-`{}` pin and source assertion: per D3. One Arcwave-shaped round trip: per D4.
- No literal fallback on a failed compile: per D5. Two-part AC1 evidence: per D6; how its verdict is recorded: per D7 (added by planning).

---

## Standards review provenance

Reviewer: Codex (`codex-plan-review`, `codex-companion task --fresh --reviewer plan-review`, gpt-6-astra, xhigh), isolated read-only, base `0cc5768b`, plan head `8352ab01`, no focus, no fallback. Findings: 0 blocking, 3 should-fix, 0 discussion. Accepted 3 (PR384-01 pipefail on the piped suite runs; PR384-02 the red release case asserts the rollup diagnostic; PR384-03 the README's derive-from-source test list gains the new test), rejected 0, deferred 0. All three were verified against live files; none is a non-obvious decision, so no ledger row was added.
