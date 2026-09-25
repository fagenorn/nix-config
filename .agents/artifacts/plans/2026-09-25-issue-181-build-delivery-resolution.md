# Build-Delivery Resolution Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `workflow-state build-delivery --kind contract` relays a resolver
refusal's document exactly, states that it seals the policy resolved at
`--repo-root`, and refuses when an existing contract worktree resolves to
different sealed policy
([#181](https://github.com/fagenorn/nix-config/issues/181)).

**Architecture:** `workflow-state.py` gets a labelled resolver-outcome classifier
that turns each outcome into the refused, failed or timed-out line (Task 1). The
pure build module gains one sealed-member table, which derivation, the provenance
digest and a new `check_worktree_policy` comparison all read, and
`DeliveryRuntime` forwards it (Task 2). The command resolves an existing input
`worktree` after the build succeeds, vetoes on divergence and documents the root
in its help (Task 3). `CLAUDE.md` and the two contract-building skills state the
root and relay the stderr line verbatim (Task 4).

**Tech stack:** Python 3 stdlib (`argparse`, `json`, `subprocess`, `unittest`,
`unittest.mock`), Markdown skill prose, `just`.

Spec (source of truth, read it whole):
`.agents/artifacts/specs/2026-09-25-issue-181-build-delivery-resolution-design.md`, D1–D9.

## Global Constraints

- Scope is exactly the spec's. Its `## Out of scope` list binds: no
  `resolve-project` change, no change to the other six kinds, no
  `delivery-contract/v1` change, no re-check of installed contracts, and no move
  into `agent_tools`.
- The provenance digest keeps its #171 members and bytes. The builder interface
  version stays 1 (D5). The build module does no I/O (#171 D27).
- Every `build-delivery` refusal still exits 2 with empty stdout and exactly one
  stderr line, `workflow-state: <message>\n`, through the existing `main`. Only
  the message text changes (spec §1).
- The resolver still runs as `[*resolve_project_argv(), "resolve", "--repo-root",
  <root>]` with `capture_output=True, check=False, timeout=60`.
- Tests use only the seams below. They use temporary project roots and `HOME`s.
  Never open or repair `.superpowers/workflows/` in the primary checkout.
- The helpers under `~/.agents/bin` are `main`'s build. Every gate runs this
  worktree's `home/common/agent-skills/scripts/*` directly or through the tests.
- No file is created and no `.nix` file changes. `just build` runs once, in the
  final gate. Never run `just switch`.
- Run targeted tests from the worktree root as
  `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/<file>.py -k <Class>`.
  Summarize output to the `FAIL:`/`ERROR:` ids and the `Ran`/`OK`/`FAILED` lines.
- Commits are conventional and SSH-signed. Never disable signing, and surface a
  signing failure. Each message ends with the trailer
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

Path abbreviations used in members: `S` = `home/common/agent-skills/scripts`,
`T` = `home/common/agent-skills/tests`, `SK` = `home/common/agent-skills/skills`,
`OI` = `home/common/claude-code/skills/orchestrate-issues`.

## Test seams

- **Builder CLI subprocess seam:** `BuilderHarness` in `T/test_delivery_workflow.py`.
  It covers refusal relay, divergent, agreeing, unsealed and unresolvable
  worktrees, the digest check and help (D8, D9).
- **workflow-state module seam:** `load_source_module` plus `mock.patch.object` in
  `T/test_workflow_state.py`. It covers only non-conforming outcomes and the
  timeout (D2, D8).
- **Runtime-facade seam:** `runpy` of `S/workflow_delivery.py` in
  `T/test_workflow_delivery.py`. It covers only `check_worktree_policy`'s message
  order and its worktree missing and mistyped refusals (D9).
- **Skill contract seam:** `WorkflowSkillContractsTest` in
  `T/test_workflow_skill_contracts.py` (D7, D8).

## Delivery estimate and boundaries

These figures are estimates. Ten files change and none is created. Product code
grows by about 90 lines across `S/workflow-state.py`,
`S/workflow_delivery_build.py` and `S/workflow_delivery.py`. Tests grow by about
230 lines across four files. The docs gain about four sentences in `CLAUDE.md`
and two skills. The diff should be about 30 KB, which fits one review package.
The main growth risk is Task 2's table refactor changing contract bytes, and the
Task 2 digest check pins that. Tasks run in index order, and each depends on
every earlier one. The base suite at `2e78e5e` ran 1228 tests, OK (skipped=2),
in about 6 minutes. The plan adds 12 tests.

## Task index

Task 1 — Relay resolver refusals and label every resolver outcome — `S/workflow-state.py`, `T/test_delivery_workflow.py`, `T/test_workflow_state.py` — full — [task-1.md](2026-09-25-issue-181-build-delivery-resolution.tasks/task-1.md)

Task 2 — One sealed-member table and the pure worktree policy comparison — `S/workflow_delivery_build.py`, `S/workflow_delivery.py`, `T/test_workflow_delivery.py`, `T/test_delivery_workflow.py` — full — [task-2.md](2026-09-25-issue-181-build-delivery-resolution.tasks/task-2.md)

Task 3 — Cross-check an existing contract worktree and state the root in help — `S/workflow-state.py`, `T/test_delivery_workflow.py` — full — [task-3.md](2026-09-25-issue-181-build-delivery-resolution.tasks/task-3.md)

Task 4 — State the root and the verbatim relay in living docs and skills — `CLAUDE.md`, `SK/from-issue/SKILL.md`, `OI/SKILL.md`, `T/test_workflow_skill_contracts.py` — full — [task-4.md](2026-09-25-issue-181-build-delivery-resolution.tasks/task-4.md)

## Criterion → task trace

| Criterion | Task |
|---|---|
| AC1: exit 2, empty stdout, and `error.code`, `repair_id` and ordered `violations` preserved exactly | 1 |
| AC2: the root is stated in help text | 3 (help), 4 (docs, skills) |
| AC2: the build refuses when the two roots' policy differs | 2 (comparison), 3 (wiring) |
| AC3: a refusal with non-empty `violations` | 1 |
| AC3: a worktree whose `.agents/project.json` differs | 3 |

## Decisions

The spec's `## Decision ledger` is authoritative. Tasks cite D1–D8 from design.
Planning added one row. **D9** extends D8's seams: a runtime-facade test of
`check_worktree_policy`, plus CLI cases for `unsupported_schema`, a
dangling-symlink worktree and the provenance digest.

A planning probe ran the resolver on each fixture these tasks use. The
two-violation contract gave `invalid_contract` with two sorted pointers.
`schema_version` 2 gave `unsupported_schema` with a `reason_code`. An empty
directory, a dangling symlink and a regular file each gave `not_onboarded`.
Setting `integration_branch` to `dev` or `max_parallel` to 5 still resolved, and
so did a project directory renamed into `.worktrees/`. The probe then applied
every task's code, tests and prose, exactly as written, to a scratch copy of
`2e78e5e`. Each targeted gate passed, and
`WORKFLOW_POLICY_SURFACE=source just agent-workflow-tests` gave `Ran 1240 tests`
and `OK (skipped=2)`. `just build` was not probed, since no `.nix` or tracked-file
set changes.

---

## Standards review provenance

- Reviewer: Claude fallback (one fresh Opus reviewer given the identical packet, isolated and read-only). The configured `codex-review` run failed on a Codex account usage limit (`turn.failed`, no agent message). That is a completed, non-capacity runtime failure, so it got the one native fallback and no retry.
- Base SHA: `763465ff0c6d562d1a5dcd43a5fe0b47a522c57e`. No focus narrowing.
- Findings: 0 Blocking, 2 Should fix, 3 Discussion. Accepted 4: the Task 3 help claim is limited to refusals after argument parsing; the Task 4 negative gate now uses whitespace-normalized text, because the live sentence wraps; the Task 1 docstring names the labelled refused, failed and timed-out outcomes; the file count is ten. Rejected 1: the `lexists` fail-open on an unsearchable ancestor, per spec D10. Deferred 0.
